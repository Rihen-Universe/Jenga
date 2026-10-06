#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Info command – Affiche les informations du workspace et des toolchains.
"""

import argparse
import sys
from pathlib import Path
from typing import List, Optional, Tuple

from ..Core.Loader import Loader
from ..Core.Cache import Cache
from ..Core.Toolchains import ToolchainManager
from ..Core.Platform import Platform
from ..Utils import Colored, Display, FileSystem
from ..Core import Api
from .._version import __version__


class InfoCommand:
    """jenga info [--verbose] [--no-daemon]"""

    @staticmethod
    def Execute(args: List[str]) -> int:
        parser = argparse.ArgumentParser(prog="jenga info", description="Show workspace and toolchain information.")
        parser.add_argument("--verbose", "-v", action="store_true", help="Show detailed info")
        parser.add_argument("--no-daemon", action="store_true", help="Do not query daemon")
        parser.add_argument("--jenga-file", help="Path to the workspace .jenga file (default: auto-detected)")
        parsed = parser.parse_args(args)

        # Déterminer le répertoire de travail (workspace root)
        workspace_root = Path.cwd()
        if parsed.jenga_file:
            entry_file = Path(parsed.jenga_file).resolve()
            if not entry_file.exists():
                Colored.PrintError(f"Jenga file not found: {entry_file}")
                return 1
        else:
            entry_file = FileSystem.FindWorkspaceEntry(workspace_root)
            if not entry_file:
                Colored.PrintError("No .jenga workspace file found.")
                return 1
        workspace_root = entry_file.parent

        # Charger le workspace (sans cache pour avoir les dernières infos)
        loader = Loader(verbose=parsed.verbose)
        workspace = loader.LoadWorkspace(str(entry_file))
        if workspace is None:
            Colored.PrintError("Failed to load workspace.")
            return 1

        # En-tête
        Display.PrintHeader(f"Jenga Workspace: {workspace.name}", char="=", color="cyan")
        print()

        # Informations générales
        print(f"Location: {workspace.location}")
        print(f"Entry file: {entry_file}")
        print(f"Configurations: {', '.join(workspace.configurations)}")
        print(f"Platforms: {', '.join(workspace.platforms)}")
        print(f"Target OSes: {', '.join([os.value for os in workspace.targetOses])}")
        print(f"Target Architectures: {', '.join([arch.value for arch in workspace.targetArchs])}")
        # Toolchains DECLAREES par le workspace (inclusions comprises) et celle par
        # defaut. « Available Toolchains » plus bas liste tout ce que la MACHINE
        # sait faire ; un IDE (NKCode) n'affiche que celles-ci quand il y en a.
        print(f"Workspace toolchains: {', '.join(sorted(workspace.toolchains.keys()))}")
        if workspace.defaultToolchain:
            print(f"Default toolchain: {workspace.defaultToolchain}")
        if workspace.startProject:
            print(f"Start project: {workspace.startProject}")
        print()

        # Projets
        Display.Subsection("Projects")
        if workspace.projects:
            rows = []
            for name, proj in workspace.projects.items():
                rows.append([
                    name,
                    proj.kind.value if proj.kind else "",
                    proj.language.value if proj.language else "",
                    "Yes" if proj.isTest else "No",
                    "Yes" if getattr(proj, '_external', False) else "No"
                ])
            Display.PrintTable(
                rows,
                headers=["Name", "Kind", "Language", "Test", "External"],
                headerColor="white"
            )
        else:
            print("No projects defined.")
        print()

        # Toolchains (détectées)
        Display.Subsection("Available Toolchains")
        tc_manager = ToolchainManager(workspace)
        toolchains = tc_manager.DetectAll()
        if toolchains:
            rows = []
            for name, tc in toolchains.items():
                rows.append([
                    name,
                    tc.compilerFamily.value if tc.compilerFamily else "",
                    tc.targetOs.value if tc.targetOs else "",
                    tc.targetArch.value if tc.targetArch else "",
                    tc.targetEnv.value if tc.targetEnv else ""
                ])
            Display.PrintTable(
                rows,
                headers=["Name", "Family", "Target OS", "Arch", "Env"],
                headerColor="white"
            )
        else:
            print("No toolchains detected.")
        print()

        # Daemon status
        Display.Subsection("Daemon")
        from ..Core.Daemon import DaemonClient, DaemonStatus
        daemon_status = DaemonStatus(workspace_root)
        if daemon_status.get('running'):
            print(f"Status: {Colored.Colorize('Running', color='green')}")
            print(f"PID: {daemon_status.get('pid')}")
            print(f"Port: {daemon_status.get('port')}")
            print(f"Uptime: {daemon_status.get('uptime', 0):.1f}s")
            print(f"Watcher active: {daemon_status.get('watcher', False)}")
        else:
            print(f"Status: {Colored.Colorize('Not running', color='red')}")
        print()

        # Informations système
        if parsed.verbose:
            Display.Subsection("System")
            print(f"Host OS: {Platform.GetHostOS().value}")
            print(f"Host Architecture: {Platform.GetHostArchitecture().value}")
            print(f"Host Environment: {Platform.GetHostEnvironment().value}")
            print(f"Host Triple: {Platform.GetHostTriple()}")
            print(f"Python: {sys.version}")
            print(f"Jenga version: {__version__}")
            print()

        return 0
