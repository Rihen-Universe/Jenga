#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Embed – API programmatique STRUCTUREE de Jenga pour l'embarquement in-process
(NKCode via pybind11, cf. ROADMAP § 6.5 « Zéro-dépendance Python »).

Contrairement au CLI (Jenga.py:main -> argv/exit code/stdout texte), chaque
fonction ici :
  - prend des arguments Python types (pas une liste argv),
  - retourne un objet de resultat structure (dataclass), jamais juste un code,
  - accepte un `sink` optionnel (objet duck-type, methodes PascalCase — voir
    Utils/Reporter.SetBuildSink) qui recoit la progression EN DIRECT pendant
    le build : totaux/index de fichiers compiles, erreurs de compilation avec
    chemins, echecs de lien, projets termines... plus AUCUN scraping de texte
    cote hote.
  - capture le transcript stdout/stderr humain (les jolis cadres du CLI) et le
    REJOUE vers sink.OnLogLine(line) ligne par ligne, pour que l'hote puisse
    toujours afficher le log complet a l'utilisateur.

Reutilise l'infrastructure EXISTANTE (Loader / BuildCommand.CreateBuilder /
Builder.Build), exactement comme Commands/CompileFlags.py le fait deja — le
daemon socket-RPC est volontairement CONTOURNE (aucun sens in-process).

CONTRAINTE DE CONCURRENCE : l'etat du DSL vit dans des globals module-level de
Core/Api.py (_currentWorkspace...) — NON reentrant. L'hote DOIT serialiser tous
les appels a ce module sur UN SEUL thread (cote NKCode : le thread worker unique
de NkEmbeddedJenga). Chaque fonction fait Api.resetstate() en entree ET en
sortie pour ne jamais laisser fuir d'etat entre deux appels successifs.
"""

import io
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from . import Api
from .Loader import Loader, GetLoadedFiles
# NB : `from ..Utils import Reporter` donnerait la CLASSE Reporter (re-exportee
# par Utils/__init__), pas le module — importer le MODULE explicitement.
from ..Utils import Reporter as _ReporterPkgAlias  # noqa: F401 (garde l'init du package)
from ..Utils.Reporter import SetBuildSink
from ..Utils.FileSystem import FileSystem


# ---------------------------------------------------------------------------
# Resultats structures
# ---------------------------------------------------------------------------

@dataclass
class BuildResult:
    exitCode: int = 1
    projectsBuilt: int = 0
    projectsFailed: int = 0
    totalErrors: int = 0
    totalWarnings: int = 0
    errorFiles: List[str] = field(default_factory=list)
    hadLinkFailure: bool = False
    hadWarnings: bool = False
    errorMessage: str = ""  # erreur FATALE (chargement workspace...), vide sinon


@dataclass
class ProjectInfo:
    name: str = ""
    kind: str = ""
    dependsOn: List[str] = field(default_factory=list)


@dataclass
class ToolchainInfo:
    """Toolchain DETECTEE (equivalent de la table « Available Toolchains » de
    `jenga info`). Necessaire a un IDE embarque : sans elle, le sélecteur de
    compilateur reste vide alors qu'aucun `jenga` externe n'est disponible."""
    name: str = ""
    family: str = ""
    targetOs: str = ""
    arch: str = ""
    env: str = ""


@dataclass
class WorkspaceInfo:
    name: str = ""
    startProject: str = ""
    configurations: List[str] = field(default_factory=list)
    projects: List[ProjectInfo] = field(default_factory=list)
    toolchains: List[ToolchainInfo] = field(default_factory=list)
    errorMessage: str = ""


# ---------------------------------------------------------------------------
# Tee stdout/stderr -> sink.OnLogLine (transcript humain preserve)
# ---------------------------------------------------------------------------

class _SinkWriter(io.TextIOBase):
    """Fichier-texte minimal qui decoupe en lignes et pousse chaque ligne
    COMPLETE vers sink.OnLogLine. Ne re-emet PAS vers le stdout d'origine :
    dans un hote fenetre (NKCode) il n'y a pas de console utile, et le CLI
    classique n'utilise jamais ce module."""

    def __init__(self, sink):
        self._sink = sink
        self._buf = ""

    def write(self, s):
        if not s:
            return 0
        self._buf += s
        while True:
            nl = self._buf.find("\n")
            if nl < 0:
                break
            line = self._buf[:nl]
            self._buf = self._buf[nl + 1:]
            self._Emit(line)
        return len(s)

    def flush(self):
        if self._buf:
            self._Emit(self._buf)
            self._buf = ""

    def _Emit(self, line):
        fn = getattr(self._sink, "OnLogLine", None)
        if fn is None:
            return
        try:
            fn(line)
        except Exception:
            pass


class _CollectingSink:
    """Enveloppe le sink UTILISATEUR pour accumuler en plus les champs du
    BuildResult (fichiers en erreur, echec de lien...) sans exiger de l'hote
    qu'il retienne quoi que ce soit. Toutes les methodes delèguent au sink
    d'origine si present."""

    def __init__(self, user_sink):
        self._user = user_sink
        self.errorFiles: List[str] = []
        self.hadLinkFailure = False
        self.hadWarnings = False

    def _Fwd(self, name, *args):
        if self._user is None:
            return
        fn = getattr(self._user, name, None)
        if fn is None:
            return
        try:
            fn(*args)
        except Exception:
            pass

    def OnProjectTotal(self, total):
        self._Fwd("OnProjectTotal", total)

    def OnProjectDone(self, success):
        self._Fwd("OnProjectDone", success)

    def OnFileTotal(self, project, total):
        self._Fwd("OnFileTotal", project, total)

    def OnFileDone(self, project, index, total, file, ok, warned):
        if warned:
            self.hadWarnings = True
        self._Fwd("OnFileDone", project, index, total, file, ok, warned)

    def OnCompileError(self, project, file, message):
        if file not in self.errorFiles:
            self.errorFiles.append(file)
        self._Fwd("OnCompileError", project, file, message)

    def OnLinkError(self, project, file, message):
        self.hadLinkFailure = True
        self._Fwd("OnLinkError", project, file, message)

    def OnLogLine(self, line):
        self._Fwd("OnLogLine", line)


# ---------------------------------------------------------------------------
# Aides internes
# ---------------------------------------------------------------------------

def ResetState() -> None:
    """Remet a zero l'etat global du DSL (Api._currentWorkspace...)."""
    try:
        Api.resetstate()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Cache du workspace (hote persistant uniquement)
# ---------------------------------------------------------------------------
#
# Analyser les .jenga coute ~1,5 s sur un workspace de 186 projets, et chaque
# operation (build, run, info, compile-flags) le refaisait — l'IDE payait donc
# cette seconde et demie a chaque clic. L'interpreteur embarque, lui, VIT tout
# au long de la session : on garde le workspace charge et on ne le relit que si
# un .jenga a bouge.
#
# Pourquoi c'est sur : appliquer les filtres est IDEMPOTENT cote Jenga. Le
# builder photographie l'etat non filtre dans `project._jenga_filter_base_state`
# a la premiere application, puis RESTAURE depuis cette base a chaque fois
# (Core/Builder.py). Construire en Debug puis en Release sur le meme objet
# workspace ne melange donc pas les reglages — c'est une garantie du moteur, pas
# une coincidence, et le test de non-regression ci-dessous la verifie.
#
# L'invalidation porte sur les fichiers REELLEMENT lus (Loader.GetLoadedFiles),
# includes compris : balayer le disque a la recherche de .jenga serait lent, et
# surtout faux des qu'un include pointe ailleurs.

_wsCacheEntry: Optional[str] = None
_wsCacheSig = None
_wsCacheObj = None
_wsCacheFiles: List[str] = []


def _Signature(paths) -> tuple:
    out = []
    for p in paths:
        try:
            st = Path(p).stat()
            out.append((str(p), st.st_mtime_ns, st.st_size))
        except OSError:
            out.append((str(p), 0, -1))  # disparu = signature differente
    return tuple(out)


def InvalidateWorkspaceCache() -> None:
    """Force la relecture au prochain appel (changement de branche, doute...)."""
    global _wsCacheEntry, _wsCacheSig, _wsCacheObj, _wsCacheFiles
    _wsCacheEntry, _wsCacheSig, _wsCacheObj, _wsCacheFiles = None, None, None, []


def _LoadWorkspaceCached(entry: Path, verbose: bool = False):
    """LoadWorkspace, en reutilisant le precedent si aucun .jenga n'a change."""
    global _wsCacheEntry, _wsCacheSig, _wsCacheObj, _wsCacheFiles
    key = str(entry)
    if _wsCacheObj is not None and _wsCacheEntry == key and _wsCacheFiles:
        if _Signature(_wsCacheFiles) == _wsCacheSig:
            return _wsCacheObj
    loader = Loader(verbose=verbose)
    ws = loader.LoadWorkspace(str(entry))
    try:
        files = [str(p) for p in GetLoadedFiles()]
    except Exception:  # noqa: BLE001
        files = []
    if ws is not None and files:
        _wsCacheEntry, _wsCacheFiles = key, files
        _wsCacheSig, _wsCacheObj = _Signature(files), ws
    else:  # rien a garantir -> pas de cache (on relira)
        InvalidateWorkspaceCache()
    return ws


def _ResolveEntry(jenga_file: Optional[str]):
    if jenga_file:
        p = Path(jenga_file).resolve()
        return p if p.exists() else None
    return FileSystem.FindWorkspaceEntry(Path.cwd())


def _RunBuilderAction(jenga_file: Optional[str], target: Optional[str], config: str,
                      platform: Optional[str], toolchain: Optional[str], jobs: int,
                      verbose: bool, action: str, sink) -> BuildResult:
    """Chemin commun build/rebuild/clean : charge le workspace, cree le builder
    (CreateBuilder, comme CompileFlags.py), pose le sink, execute, collecte."""
    from ..Commands.Build import BuildCommand

    res = BuildResult()
    collector = _CollectingSink(sink)
    tee = _SinkWriter(collector)
    old_out, old_err = sys.stdout, sys.stderr
    ResetState()
    SetBuildSink(collector)
    sys.stdout, sys.stderr = tee, tee
    try:
        entry = _ResolveEntry(jenga_file)
        if not entry:
            res.errorMessage = "no workspace (.jenga introuvable)"
            return res
        try:
            workspace = _LoadWorkspaceCached(entry, verbose=verbose)
        except Exception as e:  # noqa: BLE001
            res.errorMessage = f"load: {e}"
            return res

        extra = [f"toolchain:{toolchain}"] if toolchain else None
        options = BuildCommand.CollectFilterOptions(
            config=config, platform=platform, target=target,
            verbose=verbose, no_cache=False, no_daemon=True, extra=extra)
        try:
            builder = BuildCommand.CreateBuilder(
                workspace, config=config, platform=platform, target=target,
                verbose=verbose, action=action, options=options, jobs=jobs)
        except Exception as e:  # noqa: BLE001
            res.errorMessage = f"builder: {e}"
            return res

        try:
            if action == "clean":
                res.exitCode = int(builder.Clean(target) or 0) if hasattr(builder, "Clean") else 1
            else:
                res.exitCode = int(builder.Build(target))
        except Exception as e:  # noqa: BLE001
            res.errorMessage = f"{action}: {e}"
            res.exitCode = 1
            return res

        # Stats finales depuis le collector (evenements reellement recus).
        res.errorFiles = list(collector.errorFiles)
        res.hadLinkFailure = collector.hadLinkFailure
        res.hadWarnings = collector.hadWarnings

        # ── Chemin + Kind du binaire, EN CADEAU du build ────────────────────
        # Un IDE qui construit pour lancer avait besoin d'un second appel
        # (ExecutablePath), qui rechargeait TOUT le workspace : ~1,5 s sur un
        # workspace de 186 projets, pour une information que ce builder-ci
        # possede deja. On l'emet donc ici, sur le meme canal de lignes que le
        # transcript — l'hote reconnait les prefixes, aucun canal a creer.
        if res.exitCode == 0 and target and action != "clean":
            try:
                proj = (getattr(workspace, "projects", {}) or {}).get(target)
                if proj is not None:
                    p = builder.GetTargetPath(proj)
                    if p:
                        kind = getattr(getattr(proj, "kind", None), "value", "") or ""
                        collector.OnLogLine(f"[jenga-exekind] {kind}")
                        collector.OnLogLine(f"[jenga-exepath] {p}")
            except Exception:  # noqa: BLE001
                pass  # simple optimisation : son echec ne doit jamais casser un build
        return res
    finally:
        tee.flush()
        sys.stdout, sys.stderr = old_out, old_err
        SetBuildSink(None)
        ResetState()


# ---------------------------------------------------------------------------
# API publique
# ---------------------------------------------------------------------------

def Build(jenga_file: Optional[str] = None, target: Optional[str] = None,
          config: str = "Debug", platform: Optional[str] = None,
          toolchain: Optional[str] = None, jobs: int = 0,
          verbose: bool = False, sink=None) -> BuildResult:
    return _RunBuilderAction(jenga_file, target, config, platform, toolchain,
                             jobs, verbose, "build", sink)


def Rebuild(jenga_file: Optional[str] = None, target: Optional[str] = None,
            config: str = "Debug", platform: Optional[str] = None,
            toolchain: Optional[str] = None, jobs: int = 0,
            verbose: bool = False, sink=None) -> BuildResult:
    return _RunBuilderAction(jenga_file, target, config, platform, toolchain,
                             jobs, verbose, "rebuild", sink)


# Commandes qui ACCEPTENT `--no-daemon` (verifie dans Jenga/Commands/*.py).
# Le daemon est un RPC socket : aucun sens quand on tourne deja in-process. On
# n'ajoute le drapeau QU'a celles-ci, sinon argparse refuserait l'argument.
_NO_DAEMON_COMMANDS = frozenset({
    "build", "rebuild", "clean", "test", "run", "info", "package", "deploy",
    "gdb", "watch", "sign", "bench", "profile",
})


def RunCommand(argv: List[str], sink=None) -> BuildResult:
    """N'IMPORTE QUELLE commande Jenga, IN-PROCESS — equivalent de `jenga <argv>`.

    `argv[0]` est le nom de la commande (« info », « run », « package »,
    « examples », « config », « compile-flags », « gdb »...), le reste ses
    arguments. Passe par le MEME dispatcher que la CLI
    (`Jenga.Commands.execute_command`) : aucune commande n'est laissee de cote et
    il n'y a pas de liste a maintenir en double.

    Raison d'etre : un IDE qui embarque Jenga ne peut PAS retomber sur un
    `jenga` externe pour les commandes non couvertes — sur une machine sans
    Python, elles echoueraient toutes. Avec ceci, tout passe par l'interpreteur
    embarque.

    - stdout/stderr sont rediriges vers `sink.OnLogLine` (transcript identique a
      celui d'un sous-processus, panneau Sortie inchange).
    - `SetBuildSink` est arme aussi : les commandes qui construisent emettent en
      plus leurs evenements de progression structures.
    - `--no-daemon` est ajoute si la commande l'accepte : le daemon (RPC socket)
      n'a aucun sens in-process.
    - `SystemExit` est intercepte : une commande qui appelle `sys.exit()` ne doit
      pas tuer l'IDE hote.
    """
    res = BuildResult()
    if not argv:
        res.errorMessage = "commande vide"
        res.exitCode = 2
        return res
    from ..Commands import execute_command  # import tardif : evite un cycle

    name = str(argv[0])
    args = [str(a) for a in argv[1:]]
    if "--no-daemon" not in args and name in _NO_DAEMON_COMMANDS:
        args.append("--no-daemon")

    collector = _CollectingSink(sink)
    tee = _SinkWriter(collector)
    old_out, old_err = sys.stdout, sys.stderr
    sys.stdout = sys.stderr = tee
    SetBuildSink(collector)
    ResetState()
    try:
        res.exitCode = int(execute_command(name, args) or 0)
    except SystemExit as e:  # une commande peut appeler sys.exit()
        code = e.code
        res.exitCode = int(code) if isinstance(code, int) else (0 if code is None else 1)
    except Exception as e:  # noqa: BLE001
        res.errorMessage = f"{name}: {e}"
        res.exitCode = 1
    finally:
        tee.flush()
        sys.stdout, sys.stderr = old_out, old_err
        SetBuildSink(None)
        ResetState()
    res.errorFiles = list(collector.errorFiles)
    res.hadLinkFailure = collector.hadLinkFailure
    res.hadWarnings = collector.hadWarnings
    return res


def Clean(jenga_file: Optional[str] = None, target: Optional[str] = None,
          config: str = "Debug", platform: Optional[str] = None,
          toolchain: Optional[str] = None, verbose: bool = False,
          sink=None) -> BuildResult:
    """`jenga clean` in-process (_RunBuilderAction gere deja action="clean")."""
    return _RunBuilderAction(jenga_file, target, config, platform, toolchain,
                             0, verbose, "clean", sink)


def Test(jenga_file: Optional[str] = None, target: Optional[str] = None,
         config: str = "Debug", platform: Optional[str] = None,
         toolchain: Optional[str] = None, jobs: int = 0,
         verbose: bool = False, sink=None) -> BuildResult:
    """`jenga test` in-process. Le builder construit puis execute les suites de
    tests ; on passe donc par l'action « build » avec la cible de test."""
    return _RunBuilderAction(jenga_file, target, config, platform, toolchain,
                             jobs, verbose, "test", sink)


def ExecutablePath(jenga_file: Optional[str] = None, target: Optional[str] = None,
                   config: str = "Debug", platform: Optional[str] = None,
                   toolchain: Optional[str] = None, withKind: bool = False) -> str:
    """Chemin du BINAIRE produit pour `target`, SANS rien construire ni lancer.

    Avec `withKind=True`, renvoie `"<Kind>|<chemin>"` (ex.
    `"ConsoleApp|D:/.../mon_app.exe"`) au lieu du seul chemin : l'IDE sait alors
    s'il doit ouvrir un vrai terminal (ConsoleApp) ou lancer sans console.

    Permet a un IDE de faire lui-meme le lancement : `jenga run` est un processus
    LONG (l'application de l'utilisateur, eventuellement plusieurs instances en
    parallele) et ne peut donc pas occuper l'interpreteur embarque, qui est
    unique et partage avec les builds. Avec ce chemin, l'hote construit via
    l'API embarquee puis lance l'executable NATIVEMENT — aucun `jenga` externe,
    donc aucun besoin de Python installe.

    Renvoie "" si le projet ou le chemin ne peut pas etre resolu.
    """
    from ..Commands.Build import BuildCommand  # meme import tardif que _RunBuilderAction

    ResetState()
    try:
        entry = _ResolveEntry(jenga_file)
        if not entry or not target:
            return ""
        try:
            workspace = _LoadWorkspaceCached(entry)
            extra = [f"toolchain:{toolchain}"] if toolchain else None
            options = BuildCommand.CollectFilterOptions(
                config=config, platform=platform, target=target,
                verbose=False, no_cache=False, no_daemon=True, extra=extra)
            builder = BuildCommand.CreateBuilder(
                workspace, config=config, platform=platform, target=target,
                verbose=False, action="build", options=options, jobs=0)
            # GetTargetPath attend l'OBJET projet (il lit project.targetDir), pas
            # son nom : le passer en chaine leve AttributeError.
            proj = (getattr(workspace, "projects", {}) or {}).get(target)
            if proj is None:
                return ""
            p = builder.GetTargetPath(proj)
            path = str(p) if p else ""
            # Le KIND accompagne le chemin : l'hote (IDE) en a besoin pour choisir
            # OU lancer. Une ConsoleApp veut un vrai terminal (stdin, ANSI, code de
            # sortie visible) ; une WindowedApp n'en a pas besoin. Le calculer ici
            # evite a l'appelant de recharger le workspace une seconde fois.
            kind = getattr(getattr(proj, "kind", None), "value", "") or ""
            return f"{kind}|{path}" if withKind else path
        except Exception:  # noqa: BLE001
            return ""
    finally:
        ResetState()


def Info(jenga_file: Optional[str] = None) -> WorkspaceInfo:
    """Remplacement structure de `jenga info` (plus de table texte a parser)."""
    out = WorkspaceInfo()
    ResetState()
    try:
        entry = _ResolveEntry(jenga_file)
        if not entry:
            out.errorMessage = "no workspace (.jenga introuvable)"
            return out
        try:
            workspace = _LoadWorkspaceCached(entry)
        except Exception as e:  # noqa: BLE001
            out.errorMessage = f"load: {e}"
            return out
        out.name = getattr(workspace, "name", "") or ""
        out.startProject = getattr(workspace, "startProject", "") or ""
        out.configurations = list(getattr(workspace, "configurations", []) or [])
        for name, proj in (getattr(workspace, "projects", {}) or {}).items():
            kind = getattr(proj, "kind", "")
            kind_str = kind.name if hasattr(kind, "name") else str(kind)
            deps = [d for d in (getattr(proj, "dependsOn", []) or [])]
            out.projects.append(ProjectInfo(name=name, kind=kind_str, dependsOn=deps))
        # Toolchains detectees — meme source que la table « Available Toolchains »
        # de `jenga info` (ToolchainManager.DetectAll). Une detection qui echoue ne
        # doit PAS faire echouer tout Info() : le workspace reste exploitable.
        try:
            from .Toolchains import ToolchainManager
            for tcName, tc in (ToolchainManager(workspace).DetectAll() or {}).items():
                def _v(x):
                    return x.value if hasattr(x, "value") else (str(x) if x else "")
                out.toolchains.append(ToolchainInfo(
                    name=tcName,
                    family=_v(getattr(tc, "compilerFamily", None)),
                    targetOs=_v(getattr(tc, "targetOs", None)),
                    arch=_v(getattr(tc, "targetArch", None)),
                    env=_v(getattr(tc, "targetEnv", None))))
        except Exception:  # noqa: BLE001
            pass
        return out
    finally:
        ResetState()
