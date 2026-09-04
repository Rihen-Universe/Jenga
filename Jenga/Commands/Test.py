#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test command – Exécute les suites de tests.
Recherche les projets de type TEST_SUITE, les compile et les exécute.
AUTEUR : TEUGUIA TADJUIDJE Rodolf Séderis — Rihen
"""

import argparse
import os
import sys
from pathlib import Path
from typing import List

from ..Core import Api
from ..Utils.RuntimeDiag import RuntimeDiag
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
        # Par defaut le runner met en tete du PATH le bin de la chaine et les
        # dossiers des SharedLib de l'espace de travail : sans cela, une suite
        # liee contre libstdc++-6.dll sort en 127 sans un mot (Nkentseu,
        # 2026-09-04). Ce drapeau reproduit l'environnement d'un utilisateur —
        # c'est ainsi qu'on verifie qu'un binaire est autonome.
        parser.add_argument("--no-runtime-path", action="store_true",
                            help="Do not prepend the toolchain/shared-lib directories to PATH "
                                 "when running (checks the binary runs on its own).")
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
                        'force': parsed.force,
                        'no_runtime_path': parsed.no_runtime_path,
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

        # Politiques d'espace de travail, PAR PROJET (2.5.0).
        #   dutc/dute posent la politique ; leur `allow=[...]` en exempte des
        #   suites nommees ; --force la leve pour cette invocation. Les deux
        #   politiques sont distinctes et lues separement : une suite peut etre
        #   compilable sans etre executable, et inversement.
        # Sans liste blanche ni --force, le comportement est celui d'avant.
        dutc_on = bool(getattr(workspace, "disableUnitTestCompilation", False))
        dute_on = bool(getattr(workspace, "disableUnitTestExecution", False))
        compile_allow = set(getattr(workspace, "unitTestCompilationAllow", []) or [])
        exec_allow = set(getattr(workspace, "unitTestExecutionAllow", []) or [])
        need_build = not parsed.no_build

        def _CanCompile(name: str) -> bool:
            return parsed.force or (not dutc_on) or name in compile_allow

        def _CanExecute(name: str) -> bool:
            return parsed.force or (not dute_on) or name in exec_allow

        # Collecter les projets de test
        all_tests = [
            (name, proj) for name, proj in workspace.projects.items()
            if proj.isTest or proj.kind == Api.ProjectKind.TEST_SUITE
        ]
        if not all_tests:
            Colored.PrintError("No test projects found.")
            return 1

        if parsed.project:
            test_projects = [(n, p) for n, p in all_tests if n == parsed.project]
            if not test_projects:
                Colored.PrintError(f"No test project named '{parsed.project}'.")
                Colored.PrintInfo("Known test projects: " + ", ".join(sorted(n for n, _ in all_tests)))
                return 1
            name = parsed.project
            if need_build and not _CanCompile(name):
                Colored.PrintError(
                    f"Unit-test compilation is disabled by workspace policy "
                    f"(disableunittestcompilation) and '{name}' is not in its allow list. "
                    f"Allow it with dutc(True, allow=['{name}']), use --force for this "
                    f"invocation, or --no-build to run existing binaries."
                )
                return 1
            if not _CanExecute(name):
                Colored.PrintError(
                    f"Unit-test execution is disabled by workspace policy "
                    f"(disableunittestexecution) and '{name}' is not in its allow list. "
                    f"Allow it with dute(True, allow=['{name}']) or use --force for this invocation."
                )
                return 1
        else:
            test_projects = [
                (n, p) for n, p in all_tests
                if ((not need_build) or _CanCompile(n)) and _CanExecute(n)
            ]
            skipped = [n for n, _ in all_tests if n not in {m for m, _ in test_projects}]
            if not test_projects:
                if dute_on and not parsed.force:
                    Colored.PrintError(
                        "Unit-test execution is disabled by workspace policy "
                        "(disableunittestexecution). Use --force to override, "
                        "or name the suites to keep: dute(True, allow=[...])."
                    )
                    return 1
                Colored.PrintError(
                    "Unit-test compilation is disabled by workspace policy "
                    "(disableunittestcompilation). Use --force to build them anyway, "
                    "--no-build to run existing binaries, "
                    "or name the suites to keep: dutc(True, allow=[...])."
                )
                return 1
            if skipped:
                Colored.PrintInfo(
                    "Skipped by workspace policy (dutc/dute): " + ", ".join(sorted(skipped))
                )

        # Builder les projets de test (et leurs dépendances)
        if not parsed.no_build:
            for name, _ in test_projects:
                Colored.PrintInfo(f"Building {name}...")
                build_args = ["--config", parsed.config]
                build_args += ["--action", "test"]
                if parsed.force:
                    # Sans ce relais, le Builder rebloque la cible que l'on
                    # vient d'autoriser (mesure sur Nkentseu le 2026-09-04).
                    build_args += ["--force-tests"]
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
            env, prepended = TestCommand.RuntimeEnvironment(builder, proj, parsed.no_runtime_path)
            if prepended and parsed.verbose:
                Colored.PrintInfo("Runtime search path prepended: " + os.pathsep.join(prepended))
            result = Process.ExecuteCommand(cmd, captureOutput=False, silent=False, env=env)
            if result.returnCode != 0:
                overall = 1
                # Un binaire qui n'a PAS demarre n'est pas un test rouge : il
                # faut le dire, avec la DLL soupconnee, sinon il passe pour
                # un echec ordinaire — ou pour rien (127 muet).
                why = RuntimeDiag.Explain(result.returnCode, exe_path,
                                          (env or os.environ).get("PATH", ""), prepended)
                if why:
                    Colored.PrintError(why)
                Colored.PrintError(f"Tests failed for {name} (exit code {RuntimeDiag.CodeName(result.returnCode)}).")
            else:
                Colored.PrintSuccess(f"All tests passed for {name}.")

        return overall

    @staticmethod
    def RuntimeEnvironment(builder, project, noRuntimePath: bool):
        """(env, prepended) pour lancer `project` : PATH avec, en tete, les
        repertoires que Builder.RuntimeSearchPaths() a nommes. env=None quand
        il n'y a rien a ajouter (ou --no-runtime-path) : l'environnement du
        parent sert tel quel, comme avant 2.6.0."""
        if noRuntimePath:
            return None, []
        try:
            prepended = builder.RuntimeSearchPaths(project)
        except Exception as e:  # noqa: BLE001 — ne jamais empecher l'execution
            Colored.PrintWarning(f"Runtime search path unavailable ({e}); running with the parent PATH.")
            return None, []
        if not prepended:
            return None, []
        path = os.pathsep.join(prepended + [os.environ.get("PATH", "")])
        return {"PATH": path}, prepended
