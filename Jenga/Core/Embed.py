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
from .Loader import Loader
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
class WorkspaceInfo:
    name: str = ""
    startProject: str = ""
    configurations: List[str] = field(default_factory=list)
    projects: List[ProjectInfo] = field(default_factory=list)
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
            loader = Loader(verbose=verbose)
            workspace = loader.LoadWorkspace(str(entry))
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
            loader = Loader()
            workspace = loader.LoadWorkspace(str(entry))
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
        return out
    finally:
        ResetState()
