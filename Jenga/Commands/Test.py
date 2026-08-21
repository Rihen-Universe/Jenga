#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test command – Exécute les suites de tests.
Recherche les projets de type TEST_SUITE, les compile et les exécute.
"""

import argparse
import sys
from pathlib import Path
from typing import List

from ..Core import Api
from ..Core.Loader import Loader
from ..Core.Cache import Cache
from ..Core.Builder import Builder
from ..Utils import Colored, Reporter, Process, FileSystem
from .Build import BuildCommand


class TestCommand:
    """jenga test [--config NAME] [--platform NAME] [--project NAME] [--no-build] [--force]"""

    @staticmethod
    def Execute(args: List[str]) -> int:
        parser = argparse.ArgumentParser(prog="jenga test", description="Run unit tests.")
        parser.add_argument("--config", default="Debug", help="Build configuration")
        parser.add_argument("--platform", default=None, help="Target platform")
        parser.add_argument("--project", default=None, help="Specific test project to run")
        parser.add_argument("--no-build", action="store_true", help="Skip build step")
        # --force leve la politique de workspace POUR CETTE INVOCATION.
        #
        # POURQUOI ELLE EXISTE : `dutc`/`dute` excluent les projets de test du
        # build par defaut -- c'est legitime, un workspace de 100 projets ne doit
        # pas payer ses tests a chaque compilation.
        #
        # POURQUOI ELLE DOIT POUVOIR SE LEVER : sans contournement, la politique
        # ne rend pas les tests optionnels, elle les rend INEXISTANTS. Un banc qui
        # ne peut jamais s'executer ne peut jamais contredire ce que le code
        # affirme. Mesure sur Nkentseu le 2026-08-21 : un en-tete annoncait une
        # capacite comme "non implementee" alors qu'elle l'etait, et l'erreur a
        # survecu DEUX MOIS -- non par negligence, mais parce que rien dans le
        # depot ne pouvait la refuter.
        #
        # Explicite par invocation : le defaut reste rapide, la preuve reste
        # possible.
        parser.add_argument("--force", action="store_true",
                            help="Run tests even when the workspace disables unit-test "
                                 "compilation/execution (dutc/dute). Per-invocation override.")
        parser.add_argument("--no-daemon", action="store_true", help="Do not use daemon")
        parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
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

        # Utiliser daemon
        if not parsed.no_daemon:
            from ..Core.Daemon import DaemonClient, DaemonStatus
            client = DaemonClient(workspace_root)
            if client.IsAvailable():
                try:
                    response = client.SendCommand('test', {
                        'config': parsed.config,
                        'platform': parsed.platform,
                        'project': parsed.project,
                        'no_build': parsed.no_build,
                        'verbose': parsed.verbose
                    })
                    if response.get('status') == 'ok':
                        return response.get('return_code', 0)
                    else:
                        Colored.PrintError(f"Daemon test failed: {response.get('message')}")
                        return 1
                except Exception as e:
                    Colored.PrintWarning(f"Daemon error: {e}, falling back.")

        # Mode direct
        loader = Loader(verbose=parsed.verbose)
        cache = Cache(workspace_root)
        workspace = cache.LoadWorkspace(entry_file, loader)
        if workspace is None:
            workspace = loader.LoadWorkspace(str(entry_file))
            if workspace:
                cache.SaveWorkspace(workspace, entry_file, loader)
            else:
                Colored.PrintError("Failed to load workspace.")
                return 1

        if (not parsed.force) and bool(getattr(workspace, "disableUnitTestExecution", False)):
            Colored.PrintError(
                "Unit-test execution is disabled by workspace policy "
                "(disableunittestexecution). Use --force to override."
            )
            return 1

        if (not parsed.no_build) and (not parsed.force) and bool(getattr(workspace, "disableUnitTestCompilation", False)):
            Colored.PrintError(
                "Unit-test compilation is disabled by workspace policy "
                "(disableunittestcompilation). Use --force to build them anyway, "
                "or --no-build to run existing binaries."
            )
            return 1

        # Collecter les projets de test
        test_projects = []
        for name, proj in workspace.projects.items():
            if proj.isTest or proj.kind == Api.ProjectKind.TEST_SUITE:
                if parsed.project and name != parsed.project:
                    continue
                test_projects.append((name, proj))

        if not test_projects:
            Colored.PrintError("No test projects found.")
            return 1

        # Builder les projets de test (et leurs dépendances)
        if not parsed.no_build:
            for name, _ in test_projects:
                Colored.PrintInfo(f"Building {name}...")
                build_args = ["--config", parsed.config]
                build_args += ["--action", "test"]
                if parsed.platform:
                    build_args += ["--platform", parsed.platform]
                if parsed.jenga_file:
                    build_args += ["--jenga-file", str(entry_file)]
                build_args += ["--target", name]
                ret = BuildCommand.Execute(build_args)
                if ret != 0:
                    return ret

        # Exécuter chaque test
        overall = 0
        for name, proj in test_projects:
            Colored.PrintInfo(f"\nRunning tests for {name}...")

            # Déterminer le chemin de l'exécutable de test
            try:
                builder = BuildCommand.CreateBuilder(
                    workspace,
                    config=parsed.config,
                    # Keep platform selection consistent with `jenga build`:
                    # when --platform is omitted, CreateBuilder picks host OS/arch.
                    platform=parsed.platform,
                    target=name,
                    verbose=False,
                    action="test",
                    options=BuildCommand.CollectFilterOptions(
                        config=parsed.config,
                        platform=parsed.platform,
                        target=name,
                        verbose=parsed.verbose,
                        no_cache=False,
                        no_daemon=parsed.no_daemon,
                        extra=["action:test"]
                    )
                )
            except Exception as e:
                Colored.PrintError(f"Cannot create builder: {e}")
                overall = 1
                continue

            exe_path = builder.GetTargetPath(proj)
            if not exe_path.exists():
                Colored.PrintError(f"Test executable not found: {exe_path}")
                overall = 1
                continue

            # Exécuter avec les options de test
            cmd = [str(exe_path)] + proj.testOptions
            result = Process.ExecuteCommand(cmd, captureOutput=False, silent=False)
            if result.returnCode != 0:
                overall = 1
                Colored.PrintError(f"Tests failed for {name}.")
            else:
                Colored.PrintSuccess(f"All tests passed for {name}.")

        return overall
