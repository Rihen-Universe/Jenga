#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Init command – Crée un nouveau workspace Jenga.
Alias : workspace
Peut fonctionner en mode interactif ou avec arguments directs.
"""

import argparse
import sys
import re
from pathlib import Path
from typing import List, Optional

from ..Utils import Colored, FileSystem, Display
from ..Core.Loader import Loader
from ..Core import Api


class InitCommand:
    """jenga workspace [NAME] [--path DIR] [--configs LIST] [--oses LIST] [--interactive]"""

    @staticmethod
    def Execute(args: List[str]) -> int:
        parser = argparse.ArgumentParser(
            prog="jenga workspace",
            description="Create a new Jenga workspace.",
            epilog="Examples:\n"
                   "  jenga workspace MyGame             # -> ./MyGame/MyGame.jenga\n"
                   "  jenga workspace MyGame --path apps # -> apps/MyGame/MyGame.jenga\n"
                   "  jenga workspace --interactive"
        )
        parser.add_argument("name", nargs="?", help="Workspace name")
        parser.add_argument("--path", default=".", help="Parent directory; the workspace is created in <path>/<name>/ (default: .)")
        parser.add_argument("--configs", default="Debug,Release", help="Comma-separated build configurations (default: Debug,Release)")
        parser.add_argument("--oses", default="Windows,Linux,macOS", help="Comma-separated target OSes (default: Windows,Linux,macOS)")
        parser.add_argument("--archs", default="x86_64", help="Comma-separated target architectures (default: x86_64)")
        parser.add_argument("--interactive", "-i", action="store_true", help="Interactive mode")
        parser.add_argument("--no-interactive", action="store_true", help="Non-interactive mode (default if arguments provided)")
        parsed = parser.parse_args(args)

        # Mode interactif si demandé ou si aucun nom fourni
        interactive = parsed.interactive or (parsed.name is None and not parsed.no_interactive)

        if interactive:
            return InitCommand._RunInteractive(parsed)
        else:
            if not parsed.name:
                Colored.PrintError("Workspace name required. Use --interactive or provide a name.")
                return 1
            return InitCommand._RunDirect(parsed)

    @staticmethod
    def _ResolveWorkspaceRoot(path: str, name: str) -> Path:
        """Le workspace est cree dans un dossier portant SON nom, sous `path`.

          --path "."      -> ./<name>
          --path "apps"   -> apps/<name>
          --path <absolu> -> <absolu>/<name>

        Deduplication : si le dernier segment de `path` est deja <name>
        (ex: --path ./<name>), on ne re-ajoute pas le segment."""
        base = Path(path or ".")
        if base.name == name:
            return base.resolve()
        return (base / name).resolve()

    @staticmethod
    def _RunDirect(args) -> int:
        """Création directe avec arguments."""
        workspace_name = args.name
        # Le workspace vit dans un dossier portant SON nom (sous --path), pour
        # que les projets crees ensuite tombent dans <name>/<projet>.
        workspace_root = InitCommand._ResolveWorkspaceRoot(args.path, workspace_name)

        # Vérifier s'il existe déjà un workspace DANS ce dossier précis
        # (on ne remonte pas : un workspace parent ne doit pas bloquer).
        if workspace_root.exists():
            existing = [f for f in workspace_root.glob("*.jenga") if f.is_file()]
            if existing:
                Colored.PrintError(
                    f"A workspace already exists in {workspace_root} ({existing[0].name})")
                return 1
        else:
            FileSystem.MakeDirectory(workspace_root)

        # Générer le fichier .jenga
        entry_file = workspace_root / f"{workspace_name}.jenga"
        content = InitCommand._GenerateWorkspaceContent(
            name=workspace_name,
            configs=args.configs.split(','),
            oses=args.oses.split(','),
            archs=args.archs.split(','),
        )
        FileSystem.WriteFile(entry_file, content)

        # Generer les fichiers de coloration syntaxique / config IDE pour le
        # .jenga (traite comme du Python), comme c'est fait au 1er `jenga build`.
        InitCommand._ConfigureIDE(workspace_root)
        # .gitignore de base : les fichiers IDE generes contiennent des chemins
        # ABSOLUS machine-specifiques (extraPaths -> install Jenga) ; on les
        # exclut du versionnement pour ne pas casser la config des autres.
        InitCommand._EnsureWorkspaceGitignore(workspace_root)

        Colored.PrintSuccess(f"Workspace '{workspace_name}' created at {entry_file}")
        return 0

    @staticmethod
    def _ConfigureIDE(workspace_root: Path) -> None:
        """Genere les fichiers de coloration/IDE du .jenga (non bloquant)."""
        try:
            from ..Core.IDEConfigurator import AutoConfigure
            AutoConfigure(workspace_root, force=False, verbose=False)
        except Exception:
            pass  # la creation du workspace reste prioritaire

    @staticmethod
    def _EnsureWorkspaceGitignore(workspace_root: Path) -> None:
        """Cree un .gitignore de base (s'il n'existe pas deja).

        Les fichiers IDE generes par Jenga (.vscode/settings.json,
        pyrightconfig.json) contiennent un `extraPaths` ABSOLU vers l'install
        Jenga, donc machine-specifique : ils sont regeneres localement a chaque
        build et NE doivent PAS etre versionnes/partages. On les ignore, avec
        les artefacts de build et caches."""
        gitignore = workspace_root / ".gitignore"
        if gitignore.exists():
            return  # ne pas ecraser un .gitignore existant
        content = '''# Genere par Jenga a la creation du workspace.

# Config IDE locale (chemins machine-specifiques -> regeneree a chaque build)
.vscode/
pyrightconfig.json

# Artefacts de build et caches Jenga
Build/
.jenga/

# Python
__pycache__/
*.py[cod]
'''
        try:
            FileSystem.WriteFile(gitignore, content)
        except Exception:
            pass

    @staticmethod
    def _RunInteractive(args) -> int:
        """Création interactive (questions/réponses)."""
        # NB: la banniere est deja affichee par le dispatcher CLI (Jenga.py),
        # on ne la re-affiche pas ici (evite le doublon).
        Display.Section("Create a new Jenga workspace")

        # 1. Nom du workspace
        default_name = Path.cwd().name
        name = Display.Prompt("Workspace name", default=default_name)
        if not name:
            name = default_name

        # 2. Chemin (dossier PARENT ; le workspace est cree dans <path>/<name>)
        default_path = "."
        path = Display.Prompt("Parent directory (workspace goes in <path>/<name>)", default=default_path)
        workspace_root = InitCommand._ResolveWorkspaceRoot(path, name)

        # 3. Configurations
        all_configs = ["Debug", "Release", "Profile", "Distribution"]
        configs = Display.PromptMultiChoice(
            "Build configurations",
            choices=all_configs,
            defaults=["Debug", "Release"]
        )

        # 4. OS cibles
        all_oses = ["Windows", "Linux", "macOS", "Android", "iOS", "Web"]
        default_os = []
        import platform
        host = platform.system()
        if host == "Windows":
            default_os = ["Windows"]
        elif host == "Linux":
            default_os = ["Linux"]
        elif host == "Darwin":
            default_os = ["macOS"]
        oses = Display.PromptMultiChoice(
            "Target operating systems",
            choices=all_oses,
            defaults=default_os
        )

        # 5. Architectures
        all_archs = ["x86_64", "x86", "arm64", "arm", "wasm32"]
        archs = Display.PromptMultiChoice(
            "Target architectures",
            choices=all_archs,
            defaults=["x86_64"]
        )

        # 6. Compiler preference
        compilers = ["Auto-detect", "GCC", "Clang", "MSVC", "Zig"]
        compiler = Display.PromptChoice(
            "Preferred compiler",
            choices=compilers,
            default="Auto-detect"
        )

        # 7. C++ standard
        standards = ["C++17", "C++20", "C++23", "C11", "C17"]
        standard = Display.PromptChoice(
            "Language standard",
            choices=standards,
            default="C++17"
        )

        # 8. Create initial project?
        create_project = Display.PromptYesNo("Create an initial project in this workspace?", default=True)
        project_name = None
        project_kind = None
        project_separate = False
        if create_project:
            project_name = Display.Prompt("Project name", default=name)
            kind_choices = ["console", "windowed", "static", "shared"]
            project_kind = Display.PromptChoice(
                "Project type",
                choices=kind_choices,
                default="console"
            )
            # Fichier .jenga separe (inclus) ou inline dans le workspace ?
            project_separate = Display.PromptYesNo(
                "Donner au projet son PROPRE fichier .jenga (inclus via include) ? "
                "(Non = inline dans le .jenga du workspace)", default=False)

        # 9. Unit test framework
        use_tests = Display.PromptYesNo("Enable unit testing (Unitest)?", default=False)

        # Summary with structure preview
        Display.Section("Summary")
        print(f"  Workspace:    {Colored.Colorize(name, bold=True, color='cyan')}")
        print(f"  Path:         {workspace_root}")
        print(f"  Configs:      {', '.join(configs)}")
        print(f"  OSes:         {', '.join(oses)}")
        print(f"  Archs:        {', '.join(archs)}")
        print(f"  Compiler:     {compiler}")
        print(f"  Standard:     {standard}")
        if project_name:
            print(f"  Project:      {project_name} ({project_kind})")
        print(f"  Unit tests:   {'Yes' if use_tests else 'No'}")

        # Directory structure preview — reflete la VRAIE structure : le projet
        # vit dans un sous-dossier <project_name>/ du workspace.
        print(f"\n  Directory structure:")
        print(f"  {workspace_root.name}/")
        print(f"  +-- {name}.jenga")
        if project_name:
            ext = "cpp" if standard.startswith("C++") else "c"
            print(f"  +-- {project_name}/")
            if project_separate:
                print(f"  |   +-- {project_name}.jenga   (projet inclus via include)")
            print(f"  |   +-- src/")
            print(f"  |   |   +-- main.{ext}")
            print(f"  |   +-- include/")

        print()
        if not Display.PromptYesNo("Create workspace?", default=True):
            Colored.PrintInfo("Cancelled.")
            return 0

        # Create workspace
        parsed = argparse.Namespace(
            name=name,
            path=str(workspace_root),
            configs=','.join(configs),
            oses=','.join(oses),
            archs=','.join(archs),
        )
        result = InitCommand._RunDirect(parsed)
        if result != 0:
            return result

        # Optionally add initial project
        if project_name:
            from .Create import CreateCommand
            proj_args = argparse.Namespace(
                name=project_name,
                kind=project_kind,
                lang="C++" if standard.startswith("C++") else "C",
                location=".",
                dialect=standard,
                separate=project_separate,
            )
            entry_file = workspace_root / f"{name}.jenga"
            CreateCommand._CreateProjectDirect(proj_args, entry_file)

        Display.Success(f"Workspace '{name}' is ready!")
        Display.Info(f"Next: cd {workspace_root} && Jenga build")
        return 0

    @staticmethod
    def _GenerateWorkspaceContent(name: str, configs: List[str], oses: List[str], archs: List[str]) -> str:
        """Génère le contenu du fichier .jenga."""
        # Convertir les noms d'OS en énumérations TargetOS
        os_mapping = {
            'Windows': 'TargetOS.WINDOWS',
            'Linux': 'TargetOS.LINUX',
            'macOS': 'TargetOS.MACOS',
            'Android': 'TargetOS.ANDROID',
            'iOS': 'TargetOS.IOS',
            'Web': 'TargetOS.WEB',
            'XboxOne': 'TargetOS.XBOX_ONE',
            'XboxSeries': 'TargetOS.XBOX_SERIES',
            'Switch': 'TargetOS.SWITCH',
        }
        os_list = [os_mapping.get(o, f'"{o}"') for o in oses]

        # Architectures
        arch_mapping = {
            'x86': 'TargetArch.X86',
            'x86_64': 'TargetArch.X86_64',
            'arm': 'TargetArch.ARM',
            'arm64': 'TargetArch.ARM64',
            'wasm32': 'TargetArch.WASM32',
        }
        arch_list = [arch_mapping.get(a, f'"{a}"') for a in archs]

        return f'''#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# {name} – Jenga Workspace
# Generated by `jenga workspace` on {__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

from Jenga import *

with workspace("{name}"):
    configurations({configs!r})
    targetoses([{', '.join(os_list)}])
    targetarchs([{', '.join(arch_list)}])
    
    # Default toolchain (auto-detected)
    # usetoolchain("host-gcc")
    
    # Uncomment to use Unitest testing framework
    # with unitest() as u:
    #     u.Precompiled()
    
    # Add your projects here
    # with project("MyApp"):
    #     consoleapp()
    #     language("C++")
    #     files(["src/**.cpp"])
'''
