#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Kit command - extrait d'un workspace un KIT redistribuable.

Un kit, c'est le moteur sans le moteur : les en-tetes publics des modules
demandes, leurs bibliotheques DEJA CONSTRUITES pour les plateformes et les
configurations voulues, et un fichier de configuration Jenga qui permet a un
workspace etranger de s'y lier en une ligne.

    jenga kit --target NKLogger --config Debug --config Release
              --platform Windows --platform Linux --output ../KitNkentseu

Ce que le kit resout pour l'utilisateur, et qu'il devrait sinon deviner :

  - LA FERMETURE TRANSITIVE. Demander NKLogger ne suffit pas : une archive
    statique ne contient pas ses dependances, elle garde ses trous. Les six
    modules dont NKLogger depend doivent etre dans le kit, sans quoi il
    compile et ne lie pas.
  - L'ORDRE DE LIEN. `ld` lit la ligne une seule fois de gauche a droite. Les
    archives doivent etre listees du plus dependant au plus fondamental. Le
    kit ecrit cet ordre lui-meme, dans le fichier de configuration.
  - LE NOM DES FICHIERS. Windows produit NKLogger.lib, Linux NKLogger.a (sans
    le prefixe `lib`), Android libNKLogger.a. Le fichier genere donne des
    chemins complets, ce qui rend la question sans objet.

Voir aussi : Commands/Package.py (empaqueter une APPLICATION pour son
utilisateur final) - orthogonal, un kit s'adresse a un developpeur.
"""

import argparse
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from ..Core import Api
from ..Core.Api import ProjectKind
from ..Core.DependencyResolver import DependencyResolver
from ..Core.Loader import Loader
from ..Core.Platform import Platform
from ..Core.Variables import VariableExpander
from ..Utils import Colored, Display, FileSystem
from .._version import __version__


# Extensions considerees comme des en-tetes publics.
HEADER_EXTENSIONS = {".h", ".hpp", ".hxx", ".h++", ".inl", ".inc", ".tpp", ".ipp"}

# Jetons qui veulent dire "tout ce que le workspace declare".
ALL_TOKENS = {"all", "jengaall", "tout"}

# Prefixe et extension d'une bibliotheque statique, par systeme cible.
# Miroir de Builders/<Platform>.py : GetOutputExtension et GetTargetPath.
STATIC_LIB_NAMING: Dict[str, Tuple[str, str]] = {
    "Windows":    ("",    ".lib"),
    "Linux":      ("",    ".a"),
    "macOS":      ("",    ".a"),
    "iOS":        ("",    ".a"),
    "tvOS":       ("",    ".a"),
    "watchOS":    ("",    ".a"),
    "Web":        ("",    ".a"),
    "Android":    ("lib", ".a"),
    "HarmonyOS":  ("lib", ".a"),
}

SHARED_LIB_NAMING: Dict[str, Tuple[str, str]] = {
    "Windows":    ("",    ".dll"),
    "Linux":      ("lib", ".so"),
    "macOS":      ("lib", ".dylib"),
    "Android":    ("lib", ".so"),
    "HarmonyOS":  ("lib", ".so"),
}


class KitCommand:
    """jenga kit --target NAME [...] [--config C] [--platform P] [--output DIR]"""

    # ------------------------------------------------------------------
    # Entree
    # ------------------------------------------------------------------
    @staticmethod
    def Execute(args: List[str]) -> int:
        parser = argparse.ArgumentParser(
            prog="jenga kit",
            description="Extrait un kit redistribuable : en-tetes + bibliotheques deja "
                        "construites + un fichier de configuration Jenga pour s'y lier.",
            epilog="Exemple : jenga kit --target NKLogger --config all --platform Windows "
                   "--platform Linux --output ../KitNkentseu",
        )
        parser.add_argument("--target", "-t", action="append", default=[], metavar="PROJET",
                            help="Module a emporter. Repetable, ou liste separee par des virgules.")
        parser.add_argument("--config", "-c", action="append", default=[], metavar="CONFIG",
                            help="Configuration a emporter (Debug, Release, 'all'). "
                                 "Repetable. Defaut : toutes celles du workspace.")
        parser.add_argument("--platform", "-p", action="append", default=[], metavar="PLATEFORME",
                            help="Plateforme a emporter (Windows, Linux, Windows-x86_64, "
                                 "'all'/'jengaall'). Repetable. Defaut : l'hote.")
        parser.add_argument("--output", "-o", default="", metavar="DOSSIER",
                            help="Dossier du kit. Defaut : Build/Kit/<nom>.")
        parser.add_argument("--name", "-n", default="", metavar="NOM",
                            help="Nom du kit : il donne <NOM>.jenga et use<nom>(). "
                                 "Defaut : le nom du dossier de --output, "
                                 "sinon <Workspace>Kit.")
        parser.add_argument("--jenga-file", default="", metavar="FICHIER",
                            help="Fichier .jenga du workspace (defaut : detecte).")
        parser.add_argument("--build", "-b", action="store_true",
                            help="Construire les cibles demandees avant de recolter, "
                                 "au lieu d'exiger qu'elles soient deja construites.")
        parser.add_argument("--allow-missing", action="store_true",
                            help="Continuer si une bibliotheque n'a pas ete construite "
                                 "(la cible concernee est alors absente du kit).")
        parser.add_argument("--force", "-f", action="store_true",
                            help="Effacer le dossier du kit s'il existe deja.")
        parser.add_argument("--dry-run", action="store_true",
                            help="Montrer ce qui serait fait, sans rien ecrire.")
        parser.add_argument("--verbose", "-v", action="store_true")

        parsed = parser.parse_args(args)

        targets = KitCommand._SplitList(parsed.target)
        if not targets:
            Colored.PrintError("jenga kit : il faut au moins un --target.")
            Colored.PrintInfo("Exemple : jenga kit --target NKLogger --output ../KitNkentseu")
            return 1

        # ---- workspace ------------------------------------------------
        entry_file = KitCommand._ResolveEntryFile(parsed.jenga_file)
        if entry_file is None:
            return 1

        loader = Loader(verbose=parsed.verbose)
        workspace = loader.LoadWorkspace(str(entry_file))
        if workspace is None:
            Colored.PrintError("Chargement du workspace impossible.")
            return 1

        Display.PrintHeader(f"Jenga kit - {workspace.name}", char="=", color="cyan")
        print()

        # ---- cibles ---------------------------------------------------
        unknown = [t for t in targets if t not in workspace.projects]
        if unknown:
            Colored.PrintError(f"Projet(s) introuvable(s) : {', '.join(unknown)}")
            Colored.PrintInfo(f"Projets du workspace : {', '.join(sorted(workspace.projects))}")
            return 1

        try:
            modules = KitCommand._ResolveModules(workspace, targets)
        except (RuntimeError, ValueError) as exc:
            Colored.PrintError(f"Resolution des dependances : {exc}")
            return 1

        if not modules:
            Colored.PrintError("Aucune bibliotheque a emporter : les cibles demandees ne "
                               "sont pas des bibliotheques et ne dependent d'aucune.")
            return 1

        # L'ordre de lien est l'inverse de l'ordre de construction.
        link_order = list(reversed(modules))

        # ---- configurations et plateformes ----------------------------
        configs = KitCommand._ResolveConfigs(workspace, parsed.config)
        if not configs:
            return 1
        platforms = KitCommand._ResolvePlatforms(workspace, parsed.platform)
        if not platforms:
            return 1

        # Le nom du kit, dans cet ordre : --name, puis le dossier de
        # --output, puis <Workspace>Kit.
        #
        # Le dossier compte, parce que c'est le nom que l'utilisateur a
        # ecrit lui-meme. `jenga kit --output ../MonKit` doit produire
        # MonKit.jenga et usemonkit(), et non NkentseuKit.jenga et
        # usenkentseukit() : un kit est une chose nouvelle, qui porte son
        # nom a elle et non celui du workspace d'ou on l'a tire. Sans
        # cela, deux kits extraits du meme workspace declarent la meme
        # fonction, et le second ecrase le premier chez le consommateur.
        if parsed.name:
            kit_name = parsed.name
        else:
            kit_name = (KitCommand._NameFromOutput(parsed.output)
                        or f"{workspace.name}Kit")
        if parsed.output:
            kit_root = Path(parsed.output)
        else:
            kit_root = Path(workspace.location) / "Build" / "Kit" / kit_name
        kit_root = kit_root.resolve()

        Display.Subsection("Ce que le kit va contenir")
        print(f"Nom          : {kit_name}")
        print(f"Dossier      : {kit_root}")
        print(f"Modules      : {len(modules)}")
        print(f"Ordre de lien: {' '.join(link_order)}")
        print(f"Configurations : {', '.join(configs)}")
        print(f"Plateformes    : {', '.join(platforms)}")
        print()

        if parsed.dry_run:
            Colored.PrintInfo("--dry-run : rien n'a ete ecrit.")
            return 0

        # ---- construire d'abord, si on le demande ---------------------
        if parsed.build:
            ok = KitCommand._BuildTargets(targets, configs, platforms, parsed.verbose)
            # Chaque `jenga build` recharge le workspace et remet a zero l'etat
            # global du DSL : il faut relire le notre avant de recolter.
            workspace = Loader(verbose=parsed.verbose).LoadWorkspace(str(entry_file))
            if workspace is None:
                Colored.PrintError("Rechargement du workspace impossible apres construction.")
                return 1
            if not ok:
                Colored.PrintWarning("Des constructions ont echoue ; le kit ne contiendra "
                                     "que les cibles reellement produites.")
                print()

        # ---- dossier --------------------------------------------------
        if kit_root.exists():
            if not parsed.force:
                Colored.PrintError(f"Le dossier existe deja : {kit_root}")
                Colored.PrintInfo("Relancez avec --force pour l'effacer et le refaire.")
                return 1
            shutil.rmtree(kit_root, ignore_errors=True)
        (kit_root / "include").mkdir(parents=True, exist_ok=True)

        # ---- recolte --------------------------------------------------
        header_count = KitCommand._HarvestHeaders(
            workspace, modules, kit_root / "include", configs[0], platforms[0], parsed.verbose)

        libs: Dict[Tuple[str, str], Dict[str, str]] = {}
        missing: List[str] = []
        for config in configs:
            for platform in platforms:
                found, absent = KitCommand._HarvestLibraries(
                    workspace, modules, kit_root, config, platform, parsed.verbose)
                if absent:
                    missing.extend(f"{m} ({config}-{platform})" for m in absent)
                if found:
                    libs[(config, KitCommand._OsOf(platform))] = found

        if missing and not parsed.allow_missing:
            print()
            Colored.PrintError("Des bibliotheques n'ont pas ete construites :")
            for m in missing[:20]:
                print(f"    {m}")
            if len(missing) > 20:
                print(f"    ... et {len(missing) - 20} autres")
            Colored.PrintInfo("Construisez-les d'abord, par exemple :")
            for config in configs:
                Colored.PrintInfo(f"    jenga build --target {targets[0]} --config {config}")
            Colored.PrintInfo("Ou relancez avec --allow-missing pour un kit partiel.")
            shutil.rmtree(kit_root, ignore_errors=True)
            return 1

        if not libs:
            Colored.PrintError("Aucune bibliotheque trouvee : le kit serait vide.")
            shutil.rmtree(kit_root, ignore_errors=True)
            return 1

        # ---- fichier de configuration et manifeste --------------------
        syslibs: Dict[Tuple[str, str], List[str]] = {}
        extdirs: Dict[Tuple[str, str], List[str]] = {}
        for (config, os_name) in libs:
            syslibs[(config, os_name)] = KitCommand._SystemLinks(
                workspace, modules, config, os_name)
            extdirs[(config, os_name)] = KitCommand._ExternalLibDirs(
                workspace, modules, config, os_name)

        # (2.8.17) la bibliotheque C++ de chaque cible, lue dans ses archives
        stdlibs: Dict[Tuple[str, str], str] = {}
        for (config, os_name) in libs:
            stdlibs[(config, os_name)] = KitCommand._StdlibOfArchives(
                kit_root / "lib" / f"{config}-{os_name}")

        familles: Dict[str, str] = {}
        for os_name in sorted({o for (_c, o) in libs}):
            vues = sorted({KitCommand._FamilyOfArchives(kit_root / "lib" / f"{c}-{o}")
                           for (c, o) in libs if o == os_name} - {""})
            familles[os_name] = vues[0] if (len(vues) == 1 and vues[0] != "mixte") else ""

        config_file = kit_root / f"{kit_name}.jenga"
        KitCommand._WriteKitConfig(config_file, kit_name, workspace,
                                   modules, link_order, libs, syslibs, extdirs, stdlibs, familles)
        KitCommand._WriteManifest(kit_root / "KIT.txt", kit_name, workspace,
                                  modules, link_order, libs, syslibs, extdirs,
                                  header_count, stdlibs)

        # ---- resume ---------------------------------------------------
        print()
        Display.Subsection("Kit ecrit")
        rows = []
        for (config, os_name), files in sorted(libs.items()):
            rows.append([f"{config}-{os_name}", str(len(files)), "lib/" + f"{config}-{os_name}"])
        Display.PrintTable(rows, headers=["Cible", "Bibliotheques", "Dossier"],
                           headerColor="white")
        print()
        print(f"En-tetes copies : {header_count}")
        print(f"Taille du kit   : {KitCommand._HumanSize(KitCommand._DirSize(kit_root))}")
        print()
        Colored.PrintSuccess(f"Kit pret : {kit_root}")
        print()
        Colored.PrintInfo("Pour l'utiliser depuis un autre workspace :")
        print()
        print(f'    with workspace("MonJeu"):')
        # Le dossier reel, et non le nom du kit : avec --output les deux
        # peuvent differer, et une instruction fausse se recopie telle
        # quelle dans le workspace du consommateur.
        print(f'        useconfig("{kit_root.name}/{kit_name}.jenga")')
        print()
        print(f'        with project("Jeu"):')
        print(f'            consoleapp()')
        print(f'            files(["src/**.cpp"])')
        print(f'            {KitCommand._FunctionName(kit_name)}()')
        print()
        if missing:
            Colored.PrintWarning(f"{len(missing)} bibliotheque(s) manquante(s), kit partiel.")
        # (2.8.17) Ce que ce kit ne sert PAS, dit a celui qui le fabrique : un projet construit
        # dans une configuration absente sera REFUSE avec un message (il se liait a rien du
        # tout, sans un mot : 230 symboles introuvables chez l'utilisateur, 08/10/2026).
        toutes = list(workspace.configurations or [])
        for os_name in sorted({o for (_c, o) in libs}):
            servies = sorted(c for (c, o) in libs if o == os_name)
            absentes = [c for c in toutes if c not in servies]
            if absentes:
                Colored.PrintWarning(
                    f"Ce kit ne sert que {', '.join(servies)} pour {os_name} : un projet construit en "
                    f"{', '.join(absentes)} sera refuse, avec ce message. Pour tout servir : --config all "
                    "(apres avoir construit chaque configuration).")
            libs_cpp = sorted({stdlibs.get((c, os_name), "") for c in servies} - {""})
            if len(libs_cpp) > 1 or "mixte" in libs_cpp:
                Colored.PrintWarning(
                    f"Les cibles {os_name} n'ont pas toutes ete compilees avec la meme bibliotheque C++ ("
                    + ", ".join(f"{c} : {stdlibs.get((c, os_name), '') or 'aucune'}" for c in servies)
                    + ") : le kit ne peut pas dire laquelle il exige.")
            elif libs_cpp:
                Colored.PrintInfo(f"Bibliotheque C++ des archives {os_name} : {libs_cpp[0]} "
                                  "(le consommateur devra lier avec la meme).")
            if familles.get(os_name):
                Colored.PrintInfo(f"Compilateur des archives {os_name} : {familles[os_name]}.")
        return 0

    # ------------------------------------------------------------------
    # Workspace
    # ------------------------------------------------------------------
    @staticmethod
    def _ResolveEntryFile(jenga_file: str) -> Optional[Path]:
        if jenga_file:
            entry = Path(jenga_file).resolve()
            if not entry.exists():
                Colored.PrintError(f"Fichier .jenga introuvable : {entry}")
                return None
            return entry
        entry = FileSystem.FindWorkspaceEntry(Path.cwd())
        if not entry:
            Colored.PrintError("Aucun fichier .jenga de workspace trouve.")
            return None
        return entry

    # ------------------------------------------------------------------
    # Construction prealable
    # ------------------------------------------------------------------
    @staticmethod
    def _BuildTargets(targets: List[str], configs: List[str],
                      platforms: List[str], verbose: bool) -> bool:
        """Construit chaque cible pour chaque couple demande.

        On appelle `jenga build`, on ne le reecrit pas : c'est lui qui connait
        les chaines d'outils, le graphe et l'incremental. Une cible qui echoue
        n'arrete pas les autres ; une chaine croisee absente (viser Linux
        depuis Windows sans toolchain) est un echec normal, et le kit dira
        simplement que cette cible manque.
        """
        from .Build import BuildCommand

        every = True
        for config in configs:
            for platform in platforms:
                for target in targets:
                    Display.Subsection(f"Construction : {target} {config}-{platform}")
                    args = ["--target", target, "--config", config, "--platform", platform]
                    if verbose:
                        args.append("--verbose")
                    try:
                        code = BuildCommand.Execute(args)
                    except SystemExit as exc:
                        code = int(exc.code or 0)
                    except Exception as exc:
                        Colored.PrintError(f"{target} {config}-{platform} : {exc}")
                        code = 1
                    if code != 0:
                        every = False
                        Colored.PrintWarning(
                            f"{target} {config}-{platform} : construction echouee.")
        return every

    # ------------------------------------------------------------------
    # Modules : fermeture transitive, en ordre de construction
    # ------------------------------------------------------------------
    @staticmethod
    def _ResolveModules(workspace, targets: List[str]) -> List[str]:
        """Fermeture transitive des cibles, en ordre de construction
        (dependances d'abord), reduite aux bibliotheques."""
        closure: Set[str] = set()
        for target in targets:
            for name in DependencyResolver.ResolveBuildOrder(workspace, target):
                closure.add(name)

        full_order = DependencyResolver.ResolveBuildOrder(workspace)
        ordered = [n for n in full_order if n in closure]

        libs = []
        for name in ordered:
            project = workspace.projects.get(name)
            if project is None:
                continue
            if project.kind in (ProjectKind.STATIC_LIB, ProjectKind.SHARED_LIB):
                libs.append(name)
        return libs

    # ------------------------------------------------------------------
    # Configurations et plateformes
    # ------------------------------------------------------------------
    @staticmethod
    def _SplitList(values: List[str]) -> List[str]:
        out: List[str] = []
        for value in values:
            for part in str(value).split(","):
                part = part.strip()
                if part and part not in out:
                    out.append(part)
        return out

    @staticmethod
    def _ResolveConfigs(workspace, requested: List[str]) -> List[str]:
        available = list(workspace.configurations or ["Debug", "Release"])
        asked = KitCommand._SplitList(requested)
        if not asked or any(a.lower() in ALL_TOKENS for a in asked):
            return available
        resolved = []
        for a in asked:
            match = next((c for c in available if c.lower() == a.lower()), None)
            if match is None:
                Colored.PrintError(f"Configuration inconnue : {a}")
                Colored.PrintInfo(f"Disponibles : {', '.join(available)}")
                return []
            if match not in resolved:
                resolved.append(match)
        return resolved

    @staticmethod
    def _ResolvePlatforms(workspace, requested: List[str]) -> List[str]:
        declared = []
        for os_enum in (workspace.targetOses or [Platform.GetHostOS()]):
            value = os_enum.value if hasattr(os_enum, "value") else str(os_enum)
            if value not in declared:
                declared.append(value)

        asked = KitCommand._SplitList(requested)
        if not asked:
            host = Platform.GetHostOS()
            host_value = host.value if hasattr(host, "value") else str(host)
            return [host_value] if host_value in declared else declared[:1]
        if any(a.lower() in ALL_TOKENS for a in asked):
            return declared

        resolved = []
        for a in asked:
            os_part = a.split("-")[0]
            match = next((d for d in declared if d.lower() == os_part.lower()), None)
            if match is None:
                Colored.PrintError(f"Plateforme non declaree par le workspace : {a}")
                Colored.PrintInfo(f"Declarees : {', '.join(declared)}")
                return []
            entry = match if "-" not in a else a
            if entry not in resolved:
                resolved.append(entry)
        return resolved

    @staticmethod
    def _OsOf(platform: str) -> str:
        return platform.split("-")[0]

    @staticmethod
    def _ArchOf(workspace, platform: str) -> str:
        parts = platform.split("-")
        if len(parts) > 1:
            return parts[1]
        archs = workspace.targetArchs or []
        if archs:
            first = archs[0]
            return first.value if hasattr(first, "value") else str(first)
        host = Platform.GetHostArchitecture()
        return host.value if hasattr(host, "value") else str(host)

    # ------------------------------------------------------------------
    # Expansion des chemins sans construire de Builder
    # ------------------------------------------------------------------
    @staticmethod
    def _MakeExpander(workspace, project, config: str, platform: str) -> VariableExpander:
        os_name = KitCommand._OsOf(platform)
        arch = KitCommand._ArchOf(workspace, platform)
        expander = VariableExpander(workspace=workspace)
        expander.SetConfig({
            "name": config, "buildcfg": config, "configuration": config,
            "platform": platform, "system": os_name, "os": os_name,
            "arch": arch, "architecture": arch,
            "targetos": os_name, "targetarch": arch,
            "env": "", "targetenv": "",
            "action": "build", "options": "",
        })
        expander.SetProject(project)
        return expander

    @staticmethod
    def _LibraryFile(workspace, project, config: str, platform: str) -> Path:
        """Chemin de la bibliotheque construite, pour cette cible."""
        expander = KitCommand._MakeExpander(workspace, project, config, platform)
        target_dir = project.targetDir or (
            "%{wks.location}/Build/Lib/%{cfg.buildcfg}-%{cfg.system}/%{prj.name}")
        target_dir = Path(expander.Expand(target_dir, recursive=True))
        if not target_dir.is_absolute():
            target_dir = Path(workspace.location) / target_dir

        name = project.targetName or project.name
        os_name = KitCommand._OsOf(platform)
        if project.kind == ProjectKind.SHARED_LIB:
            prefix, ext = SHARED_LIB_NAMING.get(os_name, ("lib", ".so"))
        else:
            prefix, ext = STATIC_LIB_NAMING.get(os_name, ("", ".a"))
        return (target_dir / f"{prefix}{name}{ext}").resolve()

    # ------------------------------------------------------------------
    # Recolte des en-tetes
    # ------------------------------------------------------------------
    @staticmethod
    def _HarvestHeaders(workspace, modules: List[str], dest: Path,
                        config: str, platform: str, verbose: bool) -> int:
        """Copie, pour chaque module, le contenu de ses racines d'inclusion.

        On copie le CONTENU de la racine, pas la racine elle-meme : un module
        dont l'en-tete est a src/NKLogger/NkLog.h et qui s'inclut avec
        -I .../src donne include/NKLogger/NkLog.h. Un seul -I reproduit alors
        toutes les inclusions du moteur, a l'identique.
        """
        copied = 0
        for name in modules:
            project = workspace.projects.get(name)
            if project is None:
                continue

            expander = KitCommand._MakeExpander(workspace, project, config, platform)
            location = Path(expander.Expand(project.location or ".", recursive=True))
            if not location.is_absolute():
                location = (Path(workspace.location) / location)
            location = location.resolve()

            roots = KitCommand._IncludeRoots(project)
            for raw in roots:
                root = Path(expander.Expand(raw, recursive=True))
                if not root.is_absolute():
                    root = location / root
                try:
                    root = root.resolve()
                except OSError:
                    continue
                if not root.is_dir():
                    continue
                # Une racine hors du module est une dependance, pas un en-tete
                # a redistribuer : on ne l'emporte pas.
                if not KitCommand._IsInside(root, location):
                    continue
                copied += KitCommand._CopyHeaderTree(root, dest, verbose)
        return copied

    @staticmethod
    def _IncludeRoots(project) -> List[str]:
        """Racines d'inclusion declarees, filtres compris."""
        roots = list(project.includeDirs or [])
        filtered = getattr(project, "_filteredIncludeDirs", None) or {}
        for values in filtered.values():
            for value in values:
                if value not in roots:
                    roots.append(value)
        return roots

    @staticmethod
    def _IsInside(path: Path, parent: Path) -> bool:
        try:
            path.relative_to(parent)
            return True
        except ValueError:
            return False

    @staticmethod
    def _CopyHeaderTree(root: Path, dest: Path, verbose: bool) -> int:
        count = 0
        for src in root.rglob("*"):
            if not src.is_file():
                continue
            if src.suffix.lower() not in HEADER_EXTENSIONS:
                continue
            relative = src.relative_to(root)
            target = dest / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, target)
            count += 1
            if verbose:
                print(f"    include/{relative.as_posix()}")
        return count

    # ------------------------------------------------------------------
    # Recolte des bibliotheques
    # ------------------------------------------------------------------
    @staticmethod
    def _HarvestLibraries(workspace, modules: List[str], kit_root: Path,
                          config: str, platform: str,
                          verbose: bool) -> Tuple[Dict[str, str], List[str]]:
        """Copie les archives d'une cible. Retourne (module -> nom de fichier,
        modules absents)."""
        os_name = KitCommand._OsOf(platform)
        dest = kit_root / "lib" / f"{config}-{os_name}"
        found: Dict[str, str] = {}
        absent: List[str] = []

        for name in modules:
            project = workspace.projects.get(name)
            if project is None:
                continue
            source = KitCommand._LibraryFile(workspace, project, config, platform)
            if not source.is_file():
                absent.append(name)
                if verbose:
                    print(f"    absent : {source}")
                continue
            dest.mkdir(parents=True, exist_ok=True)
            target = dest / source.name
            shutil.copy2(source, target)
            found[name] = source.name
            if verbose:
                print(f"    lib/{config}-{os_name}/{source.name}")

        # Une cible incomplete est pire qu'une cible absente : elle se copie,
        # elle se distribue, et elle echoue a l'edition de liens chez celui qui
        # recoit le kit. Tout ou rien.
        if absent:
            shutil.rmtree(dest, ignore_errors=True)
            return {}, absent
        return found, absent

    # ------------------------------------------------------------------
    # (2.8.17) La bibliotheque C++ contre laquelle les archives ont ete compilees
    # ------------------------------------------------------------------
    @staticmethod
    def _StdlibOfArchives(dossier: Path) -> str:
        # Lue DANS les archives (les symboles qu'elles citent), pas devinee d'apres le
        # compilateur du moment : c'est ce que l'editeur de liens du consommateur verra.
        # « libc++ », « libstdc++ », « mixte », ou vide (aucune bibliotheque C++ citee).
        import mmap
        gnu = llvm = False
        try:
            fichiers = sorted(f for f in dossier.iterdir() if f.is_file())
        except OSError:
            return ""
        for f in fichiers:
            try:
                if f.stat().st_size == 0:
                    continue
                with open(f, "rb") as fh, mmap.mmap(fh.fileno(), 0, access=mmap.ACCESS_READ) as m:
                    if not llvm and (m.find(b"St3__1") >= 0):
                        llvm = True
                    if not gnu and (m.find(b"St7__cxx11") >= 0 or m.find(b"__glibcxx") >= 0):
                        gnu = True
            except (OSError, ValueError):
                continue
            if gnu and llvm:
                break
        if gnu and llvm:
            return "mixte"
        return "libstdc++" if gnu else ("libc++" if llvm else "")

    @staticmethod
    def _FamilyOfArchives(dossier: Path) -> str:
        # « clang », « gcc », « mixte » ou vide, d'apres ce que chaque compilateur laisse dans
        # ses objets : la section « .llvm_addrsig » de clang, la marque « GCC: ( » de gcc.
        # Mesure du 08/10/2026 : des archives de clang liees par g++ (MinGW, meme libstdc++)
        # echouent sur « multiple definition of guard variable » -- les variables statiques
        # des fonctions inline ne sont pas rangees de la meme facon.
        import mmap
        clang = gcc = False
        try:
            fichiers = sorted(f for f in dossier.iterdir() if f.is_file())
        except OSError:
            return ""
        for f in fichiers:
            try:
                if f.stat().st_size == 0:
                    continue
                with open(f, "rb") as fh, mmap.mmap(fh.fileno(), 0, access=mmap.ACCESS_READ) as m:
                    if not clang and m.find(b".llvm_addrsig") >= 0:
                        clang = True
                    if not gcc and m.find(b"GCC: (") >= 0:
                        gcc = True
            except (OSError, ValueError):
                continue
            if clang and gcc:
                break
        if clang and gcc:
            return "mixte"
        return "clang" if clang else ("gcc" if gcc else "")

    # ------------------------------------------------------------------
    # Bibliotheques SYSTEME heritees des modules
    # ------------------------------------------------------------------
    @staticmethod
    def _SystemLinks(workspace, modules: List[str], config: str, os_name: str) -> List[str]:
        """Les bibliotheques du systeme dont les modules ont besoin.

        Un module du moteur ne se suffit pas a lui-meme : NKThreading appelle
        `pthread` sous Linux, `log` sous Android, `hilog_ndk.z` sous HarmonyOS.
        Ces liens sont declares dans le module, sous un `filter`, et le
        consommateur du kit n'a aucun moyen de les deviner. Ils doivent donc
        voyager avec le kit, et etre emis APRES les archives : un editeur de
        liens GNU resout en une passe, et ce qui est utilise doit preceder ce
        qui l'implemente.
        """
        collected: List[str] = []

        def add(values):
            for value in values or []:
                if value in modules:      # une archive du kit, pas une lib systeme
                    continue
                if value not in collected:
                    collected.append(value)

        for name in modules:
            project = workspace.projects.get(name)
            if project is None:
                continue

            # 1. Liens inconditionnels.
            add(project.links)


            # 2. Liens poses sous un `filter("system:X")` : Jenga les range aussi
            #    dans systemLinks, indexes par systeme.
            system_links = getattr(project, "systemLinks", None) or {}
            add(system_links.get(os_name))

            # 3. Les autres filtres, quand ils sont simples et qu'ils
            #    s'appliquent a cette cible. Une expression qu'on ne sait pas
            #    lire sans ambiguite est ignoree : mieux vaut un lien manquant,
            #    qui se voit, qu'un lien de trop, qui ne se voit pas.
            for expression, values in (getattr(project, "_filteredLinks", None) or {}).items():
                if KitCommand._FilterMatches(expression, config, os_name):
                    add(values)

        return collected

    @staticmethod
    def _ExternalLibDirs(workspace, modules: List[str], config: str,
                         platform: str) -> List[str]:
        """Les dossiers de bibliotheques QUI NE SONT PAS dans le workspace.

        Un module peut se lier a un SDK installe ailleurs sur la machine :
        `NKCanvas` pose `libdirs([VULKAN_LIB])` a cote de `links(["vulkan-1"])`.
        Emporter le nom sans le dossier donne un kit qui echoue au lien sur
        `cannot find -lvulkan-1`. On emporte donc aussi le chemin.

        Les dossiers internes au workspace sont ignores : ce sont les
        bibliotheques du kit, deja rangees dans lib/<Config>-<OS>/.
        """
        root = Path(workspace.location).resolve()
        collected: List[str] = []

        for name in modules:
            project = workspace.projects.get(name)
            if project is None:
                continue
            expander = KitCommand._MakeExpander(workspace, project, config, platform)

            candidates = list(project.libDirs or [])
            for expression, values in (getattr(project, "_filteredLibDirs", None) or {}).items():
                if KitCommand._FilterMatches(expression, config, platform.split("-")[0]):
                    candidates.extend(values)

            for raw in candidates:
                if not raw:
                    continue
                try:
                    path = Path(expander.Expand(str(raw), recursive=True))
                    if not path.is_absolute():
                        continue        # relatif au projet : interne, donc deja pris
                    path = path.resolve()
                except (OSError, ValueError):
                    continue
                if KitCommand._IsInside(path, root):
                    continue            # une sortie du workspace : c'est le kit
                entry = str(path).replace("\\", "/")
                if entry not in collected:
                    collected.append(entry)
        return collected

    @staticmethod
    def _FilterMatches(expression: str, config: str, os_name: str) -> bool:
        """Vrai si une expression de filtre s'applique a (config, systeme).

        On evalue reellement l'expression, negations et alternatives comprises.
        C'est necessaire : les liens systeme de Windows sont poses sous

            system:Windows && !options:windows-runtime=uwp
                           && !system:XboxSeries && !system:XboxOne

        et un evaluateur qui renonce devant un `!` laisserait un kit Windows
        sans user32 ni gdi32, donc incapable d'ouvrir une fenetre.

        Une option n'est jamais posee au moment de fabriquer un kit : on
        fabrique la configuration par defaut. `options:x` est donc faux, et
        `!options:x` vrai. Un atome d'un genre qu'on ne sait pas lire rend
        toute l'expression fausse, pour ne jamais emporter un lien de trop.
        """
        text = (expression or "").strip()
        if not text:
            return False
        # `&&` lie plus fort que `||`, comme dans Builder._ParseFilterOr.
        for alternative in text.split("||"):
            if not alternative.strip():
                continue
            if all(KitCommand._AtomMatches(atom, config, os_name)
                   for atom in alternative.split("&&") if atom.strip()):
                return True
        return False

    @staticmethod
    def _AtomMatches(atom: str, config: str, os_name: str) -> bool:
        atom = atom.strip()
        negated = atom.startswith("!")
        if negated:
            atom = atom[1:].strip()
        if ":" not in atom:
            return False
        key, _, value = atom.partition(":")
        key = key.strip().lower()
        value = value.strip().lower()

        if key in ("system", "systems"):
            result = (value == os_name.lower())
        elif key in ("configurations", "configuration", "config", "cfg"):
            result = (value == config.lower())
        elif key in ("options", "option"):
            result = False          # aucune option posee a la fabrication
        else:
            return False            # genre inconnu : on renonce, sans negation
        return (not result) if negated else result

    # ------------------------------------------------------------------
    # Fichier de configuration Jenga
    # ------------------------------------------------------------------
    @staticmethod
    def _NameFromOutput(output: str) -> str:
        """Le nom du kit, deduit du dossier de sortie.

        Rend une chaine vide si le dossier ne donne rien d'utilisable :
        l'appelant retombe alors sur le nom du workspace.
        """
        if not output:
            return ""
        name = Path(output).resolve().name
        return "".join(ch for ch in name if ch.isalnum() or ch in "-_")

    @staticmethod
    def _FunctionName(kit_name: str) -> str:
        safe = "".join(ch for ch in kit_name if ch.isalnum())
        # Un nom de fonction ne commence pas par un chiffre, et un kit
        # appele « 2026 » est parfaitement legitime.
        if not safe or safe[0].isdigit():
            safe = "kit" + safe
        return f"use{safe.lower()}"

    @staticmethod
    def _WriteKitConfig(path: Path, kit_name: str, workspace,
                        modules: List[str], link_order: List[str],
                        libs: Dict[Tuple[str, str], Dict[str, str]],
                        syslibs: Dict[Tuple[str, str], List[str]],
                        extdirs: Dict[Tuple[str, str], List[str]],
                        stdlibs: Optional[Dict[Tuple[str, str], str]] = None,
                        familles: Optional[Dict[str, str]] = None) -> None:
        """Ecrit le .jenga que le workspace consommateur charge par useconfig().

        Le fichier ne declare AUCUN projet : il n'a pas de sources, un projet
        vide ne produirait pas d'archive. Il declare une fonction, appelee
        dans le `with project(...)` du consommateur, qui emet les includedirs,
        les libdirs et les links, dans le bon ordre et avec des chemins
        complets. La racine est calculee a partir de l'emplacement de CE
        fichier : le kit est donc deplacable.
        """
        function = KitCommand._FunctionName(kit_name)
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M")

        lines: List[str] = []
        add = lines.append

        add("#!/usr/bin/env python3")
        add("# -*- coding: utf-8 -*-")
        add("# =============================================================================")
        add(f"# {kit_name}.jenga - ECRIT PAR `jenga kit`. Ne pas modifier a la main.")
        add("# =============================================================================")
        add(f"# Kit extrait du workspace '{workspace.name}' le {stamp}")
        add(f"# Jenga {__version__}")
        add("#")
        add("# Chargez-le dans le .jenga de VOTRE workspace :")
        add("#")
        add(f'#     useconfig("chemin/vers/{kit_name}.jenga")')
        add("#")
        add("# puis, dans chaque projet qui utilise le kit :")
        add("#")
        add(f"#     {function}()")
        add("#")
        add("# L'ordre des archives est celui que l'editeur de liens exige (du plus")
        add("# dependant au plus fondamental) ; ne le changez pas.")
        add("#")
        add("# /!\\ N'INCLUEZ AUCUN .jenga DU PROJET D'ORIGINE.")
        add("#")
        add("#     with include(\".../UnModule/UnModule.jenga\"):   <-- NON")
        add("#")
        add("# Ces fichiers appellent des fonctions que leur propre workspace")
        add("# definit par useconfig, et qui n'existent pas chez vous : la lecture")
        add("# echoue sur un « name '...' is not defined ». C'est aussi inutile, le")
        add("# module etant deja dans ce kit, compile, avec ses dependances.")
        add("# =============================================================================")
        add("")
        add("from pathlib import Path as _Path")
        add("")
        add("# Racine du kit, deduite de l'emplacement de ce fichier : le kit peut etre")
        add("# copie n'importe ou, y compris dans le depot du consommateur.")
        add('KIT_ROOT = str(_Path(__file__).resolve().parent).replace("\\\\", "/")')
        add(f'KIT_NAME = "{kit_name}"')
        add(f'KIT_WORKSPACE = "{workspace.name}"')
        add(f'KIT_BUILT = "{stamp}"')
        add(f'KIT_JENGA = "{__version__}"')
        add("")
        add("# Modules du kit, dans l'ORDRE DE LIEN (dependants d'abord).")
        add("KIT_MODULES = [")
        for name in link_order:
            add(f'    "{name}",')
        add("]")
        add("")
        add("# Dependances directes de chaque module, telles que le workspace les declarait.")
        add("KIT_DEPENDS = {")
        for name in link_order:
            project = workspace.projects.get(name)
            deps = [d for d in (project.dependsOn or []) if d in modules] if project else []
            add(f'    "{name}": {deps!r},')
        add("}")
        add("")
        add("# Cibles presentes dans ce kit : (configuration, systeme) -> archives.")
        add("KIT_TARGETS = {")
        for (config, os_name) in sorted(libs):
            add(f'    ("{config}", "{os_name}"): "lib/{config}-{os_name}",')
        add("}")
        add("")
        add("# Bibliotheques DU SYSTEME dont les modules ont besoin. Elles ne sont pas")
        add("# dans le kit : elles sont sur la machine. Le kit se contente de dire")
        add("# lesquelles, ce que le consommateur ne peut pas deviner.")
        add("KIT_SYSTEM_LIBS = {")
        for (config, os_name) in sorted(libs):
            add(f'    ("{config}", "{os_name}"): {syslibs.get((config, os_name), [])!r},')
        add("}")
        add("")
        # (2.8.17) La bibliotheque C++ des archives, par systeme, quand toutes ses cibles
        # s'accordent. Celui qui lie doit utiliser la meme : libc++ et libstdc++ ne se
        # melangent pas.
        add("# Bibliotheque C++ contre laquelle les archives ont ete compilees (lue dans")
        add("# les archives). Le consommateur doit lier avec la meme.")
        add("KIT_STDLIB = {")
        for os_name in sorted({o for (_c, o) in libs}):
            valeurs = sorted({(stdlibs or {}).get((c, o), "") for (c, o) in libs if o == os_name} - {""})
            accord = valeurs[0] if (len(valeurs) == 1 and valeurs[0] != "mixte") else ""
            add(f'    "{os_name}": "{accord}",')
        add("}")
        add("# Famille du compilateur qui a produit les archives (clang ou gcc). Sous MinGW,")
        add("# les objets de l'un ne se lient pas toujours avec ceux de l'autre.")
        add("KIT_COMPILER = {")
        for os_name in sorted({o for (_c, o) in libs}):
            add(f'    "{os_name}": "{(familles or {}).get(os_name, "")}",')
        add("}")
        add("")
        add("")
        add("def _kit_selection(modules=None):")
        add('    """Les modules demandes plus leurs dependances, en ordre de lien."""')
        add("    if not modules:")
        add("        return list(KIT_MODULES)")
        add("    wanted = set()")
        add("    pending = list(modules)")
        add("    while pending:")
        add("        name = pending.pop()")
        add("        if name in wanted:")
        add("            continue")
        add("        if name not in KIT_DEPENDS:")
        add("            raise ValueError(")
        add('                "%s : module absent du kit %s. Modules : %s"')
        add("                % (name, KIT_NAME, \", \".join(KIT_MODULES)))")
        add("        wanted.add(name)")
        add("        pending.extend(KIT_DEPENDS[name])")
        add("    return [m for m in KIT_MODULES if m in wanted]")
        add("")
        add("")
        add(f"def {function}(modules=None, extra_includes=None):")
        add('    """Lie ce projet au kit : en-tetes, dossiers de bibliotheques, archives.')
        add("")
        add("    modules : les modules voulus (leurs dependances suivent toutes seules).")
        add("              Par defaut, tout le kit.")
        add("    extra_includes : dossiers d'inclusion propres au projet.")
        add('    """')
        add("    selection = _kit_selection(modules)")
        add("")
        add("    includes = [KIT_ROOT + \"/include\"]")
        add("    for extra in (extra_includes or []):")
        add("        includes.append(extra)")
        add("    includedirs(includes)")
        add("")
        # (2.8.17) Ce que le kit EXIGE, et ce qu'il ne sert PAS : dit avant de compiler.
        add("    # Ce que ce kit exige de la chaine qui le lie, et les configurations qu'il")
        add("    # ne sert pas : un message clair avant de compiler (Jenga >= 2.8.17), au")
        add("    # lieu de centaines de symboles introuvables a l'edition de liens.")
        add("    _exiger = globals().get(\"kitrequire\")")
        add("    _refuser = globals().get(\"builderror\")")
        add("    for _os, _lib in sorted(KIT_STDLIB.items()):")
        add("        _fam = KIT_COMPILER.get(_os, \"\")")
        add("        if _exiger and (_lib or _fam):")
        add("            _exiger(KIT_NAME, stdlib=_lib, compiler=_fam, system=_os)")
        add("    try:")
        add("        from Jenga.Core.Api import getcurrentworkspace as _ws_courant")
        add("        _configs = list(_ws_courant().configurations or [])")
        add("    except Exception:")
        add("        _configs = []")
        add("    for _os in sorted({_o for (_c, _o) in KIT_TARGETS}):")
        add("        _servies = sorted(_c for (_c, _o) in KIT_TARGETS if _o == _os)")
        add("        for _cfg in _configs:")
        add("            if (_cfg, _os) in KIT_TARGETS:")
        add("                continue")
        add("            _msg = (\"Le kit %s ne contient pas de bibliotheques pour %s-%s (il contient : %s). \"")
        add("                    \"Construisez en %s, ou refaites le kit avec cette configuration \"")
        add("                    \"(jenga kit ... --config %s).\"")
        add("                    % (KIT_NAME, _cfg, _os, \", \".join(_servies), \" ou \".join(_servies), _cfg))")
        add("            if _refuser:")
        add("                with filter(\"system:%s && configurations:%s\" % (_os, _cfg)):")
        add("                    _refuser(_msg)")
        add("            else:")
        add("                print(\"[kit %s] ATTENTION : %s\" % (KIT_NAME, _msg))")
        add("")

        # Un bloc par cible presente : chemins litteraux, aucune variable a
        # expanser, aucune ambiguite sur le nom du fichier.
        for (config, os_name) in sorted(libs):
            files = libs[(config, os_name)]
            ordered = [n for n in link_order if n in files]
            add(f'    with filter("system:{os_name} && configurations:{config}"):')
            external = extdirs.get((config, os_name)) or []
            if external:
                add("        # Dossiers de SDK exterieurs au kit : ils doivent exister")
                add("        # sur la machine qui construit. Voir KIT.txt.")
                add(f'        libdirs([KIT_ROOT + "/lib/{config}-{os_name}"] + {external!r})')
            else:
                add(f'        libdirs([KIT_ROOT + "/lib/{config}-{os_name}"])')
            add("        _archives = []")
            add("        for _m in selection:")
            add("            _f = {")
            for name in ordered:
                add(f'                "{name}": "{files[name]}",')
            add("            }.get(_m)")
            add("            if _f:")
            add(f'                _archives.append(KIT_ROOT + "/lib/{config}-{os_name}/" + _f)')
            add("        if _archives:")
            add("            links(_archives)")
            system = syslibs.get((config, os_name)) or []
            if system:
                add("        # Les bibliotheques du systeme viennent APRES les archives :")
                add("        # un editeur de liens GNU resout en une passe.")
                add(f"        links({system!r})")
            add("")

        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    # ------------------------------------------------------------------
    # Manifeste
    # ------------------------------------------------------------------
    @staticmethod
    def _WriteManifest(path: Path, kit_name: str, workspace,
                       modules: List[str], link_order: List[str],
                       libs: Dict[Tuple[str, str], Dict[str, str]],
                       syslibs: Dict[Tuple[str, str], List[str]],
                       extdirs: Dict[Tuple[str, str], List[str]],
                       header_count: int,
                       stdlibs: Optional[Dict[Tuple[str, str], str]] = None) -> None:
        """Un kit sans date ment en silence : le moteur avance, le kit non, et
        un rapport de bug ne dit plus contre quoi il a ete constate."""
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        lines = [
            f"{kit_name} - kit Jenga",
            "=" * (len(kit_name) + 14),
            "",
            f"construit le  : {stamp}",
            f"workspace     : {workspace.name}",
            f"jenga         : {__version__}",
            f"en-tetes      : {header_count} fichiers dans include/",
            "",
            "Modules, dans l'ordre de lien (du plus dependant au plus fondamental) :",
        ]
        for name in link_order:
            lines.append(f"    {name}")
        lines += ["", "Cibles construites :"]
        for (config, os_name) in sorted(libs):
            system = syslibs.get((config, os_name)) or []
            suffix = f", + systeme : {', '.join(system)}" if system else ""
            cpp = (stdlibs or {}).get((config, os_name), "")
            cpp_dit = f" [bibliotheque C++ : {cpp}]" if cpp else ""
            lines.append(
                f"    {config}-{os_name} : {len(libs[(config, os_name)])} bibliotheques{cpp_dit}{suffix}")
        externes = sorted({d for values in extdirs.values() for d in values})
        if externes:
            lines += [
                "",
                "A INSTALLER SUR LA MACHINE QUI CONSTRUIT :",
                "",
                "Ces dossiers ne sont PAS dans le kit. Ils appartiennent a des SDK",
                "installes a part, et le kit ne fait que dire ou ils etaient chez son",
                "producteur. Si les votres sont ailleurs, corrigez les chemins dans le",
                "fichier de configuration du kit.",
                "",
            ]
            for d in externes:
                lines.append(f"    {d}")
            lines += [
                "",
                "Leurs EN-TETES ne sont pas necessaires : les modules du kit les",
                "encapsulent et n'en exposent rien dans leurs en-tetes publics. Seules",
                "les bibliotheques sont reclamees, a l'edition de liens.",
            ]

        lines += [
            "",
            "Pour une cible absente de cette liste, il faut refaire le kit depuis le",
            "depot : un kit ne contient que ce qui a ete construit avant lui.",
            "",
            "N'incluez aucun .jenga du projet d'origine dans votre",
            "workspace : ces fichiers dependent de la configuration de LEUR",
            "workspace et casseront a la lecture. Tout ce dont vous avez",
            "besoin est deja ici.",
            "",
            "Citez la date de construction dans vos retours.",
            "",
        ]
        path.write_text("\n".join(lines), encoding="utf-8")

    # ------------------------------------------------------------------
    # Divers
    # ------------------------------------------------------------------
    @staticmethod
    def _DirSize(path: Path) -> int:
        return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())

    @staticmethod
    def _HumanSize(size: int) -> str:
        value = float(size)
        for unit in ("o", "Ko", "Mo", "Go"):
            if value < 1024.0 or unit == "Go":
                return f"{value:.1f} {unit}"
            value /= 1024.0
        return f"{value:.1f} Go"
