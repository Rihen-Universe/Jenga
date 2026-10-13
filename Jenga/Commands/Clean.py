#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Clean command – Supprime les fichiers générés (objets, binaires, cache).
Ne supprime que les fichiers appartenant au projet (pas les répertoires partagés).
"""

import argparse
import sys
from pathlib import Path
from typing import List, Optional

from ..Core.Loader import Loader
from ..Core.Cache import Cache
from ..Core.Variables import VariableExpander
from ..Core.Platform import Platform
from ..Core.Builder import Builder
from ..Utils import FileSystem, Colored


class CleanCommand:
    """jenga clean [--config NAME] [--platform NAME] [--project NAME] [--all] [--no-daemon]"""

    @staticmethod
    def Execute(args: List[str]) -> int:
        parser = argparse.ArgumentParser(prog="jenga clean", description="Remove generated files.")
        parser.add_argument("--config", default=None, help="Build configuration (Debug, Release, etc.)")
        parser.add_argument("--platform", default=None, help="Target platform (Windows, Linux, etc.)")
        parser.add_argument("--project", default=None, help="Clean only a specific project")
        parser.add_argument("--all", action="store_true", help="Remove all build artifacts and cache")
        parser.add_argument("--no-daemon", action="store_true", help="Do not use daemon")
        parser.add_argument("--jenga-file", help="Path to the workspace .jenga file (default: auto-detected)")
        parser.add_argument("--toolchain", default=None,
                            help="Accepted so that one command line serves build, run, test and clean; clean removes the outputs of every toolchain.")
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

        # Utiliser le daemon si disponible
        if not parsed.no_daemon:
            from ..Core.Daemon import DaemonClient
            client = DaemonClient(workspace_root)
            if client.IsAvailable():
                try:
                    response = client.SendCommand('clean', {
                        'config': parsed.config,
                        'platform': parsed.platform,
                        'project': parsed.project,
                        'all': parsed.all
                    })
                    if response.get('status') == 'ok':
                        return response.get('return_code', 0)
                    else:
                        Colored.PrintError(f"Daemon clean failed: {response.get('message')}")
                        return 1
                except Exception as e:
                    Colored.PrintWarning(f"Daemon error: {e}, falling back.")

        # Mode direct : charger le workspace
        loader = Loader(verbose=False)
        cache = Cache(workspace_root)
        workspace = cache.LoadWorkspace(entry_file, loader)
        if workspace is None:
            workspace = loader.LoadWorkspace(str(entry_file))
            if workspace is None:
                Colored.PrintError("Failed to load workspace.")
                return 1

        # --all : supprime tout le cache et le répertoire Build/ entier
        if parsed.all:
            build_dir = workspace_root / "Build"
            if build_dir.exists():
                FileSystem.RemoveDirectory(build_dir, recursive=True)
                Colored.PrintInfo(f"Removed {build_dir}")
            cache.Invalidate()
            return 0

        # Déterminer les configurations et plateformes à nettoyer
        configs = [parsed.config] if parsed.config else workspace.configurations
        if parsed.platform:
            platforms = [parsed.platform]
        elif workspace.targetOses:
            platforms = [os.value for os in workspace.targetOses]
        else:
            platforms = workspace.platforms or [Platform.GetHostOS().value]

        # Déterminer les projets à nettoyer
        projects_to_clean = []
        if parsed.project:
            if parsed.project not in workspace.projects:
                Colored.PrintError(f"Project '{parsed.project}' not found.")
                return 1
            projects_to_clean = [workspace.projects[parsed.project]]
        else:
            projects_to_clean = list(workspace.projects.values())

        # Pour chaque combinaison config/platform, nettoyer les fichiers générés
        for config in configs:
            for platform in platforms:
                expander = loader.GetExpanderForWorkspace(workspace)
                parts = (platform or "").split('-') if platform else []
                system = parts[0] if parts and parts[0] else Platform.GetHostOS().value
                arch = parts[1] if len(parts) > 1 and parts[1] else Platform.GetHostArchitecture().value
                env = parts[2] if len(parts) > 2 and parts[2] else ""
                fake_config = {
                    'name': config,
                    'buildcfg': config,
                    'configuration': config,
                    'platform': platform,
                    'system': system,
                    'os': system,
                    'arch': arch,
                    'architecture': arch,
                    'targetos': system,
                    'targetarch': arch,
                    'env': env,
                    'targetenv': env,
                }
                expander.SetConfig(fake_config)

                for proj in projects_to_clean:
                    if proj.name.startswith('__'):
                        continue
                    # Nettoyer les objets
                    if proj.objDir:
                        obj_dir = expander.Expand(proj.objDir)
                        if obj_dir and Path(obj_dir).exists():
                            # Supprimer uniquement les fichiers objets de ce projet
                            obj_ext = Builder.GetObjectExtensionForPlatform(platform)  # à définir
                            # Ou plus simplement : chercher tous les fichiers ayant une extension objet
                            for ext in ['.o', '.obj']:
                                files = FileSystem.ListFiles(obj_dir, f"*{ext}", recursive=True, fullPath=True)
                                for f in files:
                                    FileSystem.RemoveFile(f, ignoreErrors=True)
                                    Colored.PrintInfo(f"Removed {f}")
                            # Optionnel : supprimer le répertoire s'il est vide
                            try:
                                if not any(Path(obj_dir).iterdir()):
                                    FileSystem.RemoveDirectory(obj_dir, recursive=False, ignoreErrors=True)
                            except:
                                pass

                    # Nettoyer les binaires
                    if proj.targetDir:
                        target_dir = expander.Expand(proj.targetDir)
                        if target_dir and Path(target_dir).exists():
                            # Supprimer uniquement les fichiers de sortie de ce projet
                            # (exe, dll, so, a, lib, etc.)
                            out_ext = Builder.GetOutputExtensionsForProject(proj)  # à définir
                            for ext in out_ext:
                                pattern = f"*{ext}"
                                files = FileSystem.ListFiles(target_dir, pattern, recursive=False, fullPath=True)
                                for f in files:
                                    FileSystem.RemoveFile(f, ignoreErrors=True)
                                    Colored.PrintInfo(f"Removed {f}")
                            # Idem : supprimer le répertoire s'il est vide
                            try:
                                if not any(Path(target_dir).iterdir()):
                                    FileSystem.RemoveDirectory(target_dir, recursive=False, ignoreErrors=True)
                            except:
                                pass

        return 0
