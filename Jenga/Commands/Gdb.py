#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Gdb command – Lance un debugger (GDB par defaut, LLDB en fallback) sur
l'executable d'un projet.

Workflow :
  1. Localise le workspace + le projet (comme `jenga run`).
  2. (Re)compile en Debug avec symboles si demande (--build) ou si l'exe manque.
  3. Localise le binaire via le builder.
  4. Detecte le debugger (gdb, sinon lldb) et le lance sur l'exe.

Exemples :
  jenga gdb                         # debug le startProject en Debug
  jenga gdb MonApp --break main     # pose un breakpoint sur main
  jenga gdb MonApp --run            # demarre l'execution immediatement
  jenga gdb MonApp --args foo bar   # passe des args au programme debug
  jenga gdb MonApp --debugger lldb  # force LLDB
"""

import argparse
from pathlib import Path
from typing import List, Optional

from ..Core.Loader import Loader
from ..Core.Cache import Cache
from ..Core import Api
from ..Utils import Colored, Process, FileSystem
from .Build import BuildCommand


class GdbCommand:
    """jenga gdb [PROJECT] [--config NAME] [--platform NAME] [--break LOC] [--args ...]"""

    @staticmethod
    def Execute(args: List[str]) -> int:
        parser = argparse.ArgumentParser(
            prog="jenga gdb",
            description="Debug a project executable with GDB (or LLDB).")
        parser.add_argument("project", nargs="?", default=None,
                            help="Project to debug (default: startProject or first executable)")
        parser.add_argument("--config", default="Debug",
                            help="Build configuration (default: Debug — recommended for debugging)")
        parser.add_argument("--platform", default=None, help="Target platform")
        parser.add_argument("--debugger", choices=["auto", "gdb", "lldb"], default="auto",
                            help="Debugger backend (default: auto — gdb then lldb)")
        parser.add_argument("--break", "-b", dest="breakpoints", action="append", default=[],
                            metavar="LOCATION",
                            help="Set a breakpoint (e.g. main, file.cpp:42). Repeatable.")
        parser.add_argument("--run", action="store_true",
                            help="Start execution immediately (gdb: -ex run / lldb: -o run)")
        parser.add_argument("--batch", action="store_true",
                            help="Batch mode: run then quit (non-interactive, useful in CI)")
        parser.add_argument("--args", nargs=argparse.REMAINDER, default=[],
                            help="Arguments passed to the debugged program")
        parser.add_argument("--build", action="store_true",
                            help="Force rebuild before debugging")
        parser.add_argument("--no-daemon", action="store_true", help="Do not use daemon")
        parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
        parser.add_argument("--jenga-file", help="Path to the workspace .jenga file (default: auto-detected)")
        parser.add_argument("--toolchain", default=None,
                            help="Toolchain to build and debug with (same as `jenga build --toolchain`).")
        parsed = parser.parse_args(args)

        # ── 1. Localiser le workspace ─────────────────────────────────────
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

        loader = Loader(verbose=parsed.verbose)
        cache = Cache(workspace_root, workspaceName=entry_file.stem)
        workspace = cache.LoadWorkspace(entry_file, loader)
        if workspace is None:
            workspace = loader.LoadWorkspace(str(entry_file))
            if workspace:
                cache.SaveWorkspace(workspace, entry_file, loader)
            else:
                Colored.PrintError("Failed to load workspace.")
                return 1

        # ── 2. Determiner le projet a debugger ────────────────────────────
        project_name = parsed.project or workspace.startProject
        if not project_name:
            for name, proj in workspace.projects.items():
                if proj.kind in (Api.ProjectKind.CONSOLE_APP,
                                 Api.ProjectKind.WINDOWED_APP,
                                 Api.ProjectKind.TEST_SUITE):
                    project_name = name
                    break
        if not project_name or project_name not in workspace.projects:
            Colored.PrintError("No executable project found to debug.")
            return 1
        project = workspace.projects[project_name]

        # ── 3. Detecter le debugger ───────────────────────────────────────
        debugger, kind = GdbCommand._ResolveDebugger(parsed.debugger)
        if not debugger:
            Colored.PrintError(
                "No debugger found. Install GDB or LLDB:\n"
                "  - Windows (MSYS2/UCRT64) : pacman -S mingw-w64-ucrt-x86_64-gdb\n"
                "  - Linux (Debian/Ubuntu)  : sudo apt install gdb\n"
                "  - macOS                  : xcode-select --install  (lldb inclus)")
            return 1

        # ── 4. Build si demande (ou si l'exe manque) ──────────────────────
        # (2.8.19) Sans --platform, CreateBuilder choisit comme `jenga build` : la machine hote si le
        # workspace la declare. Avant : `parsed.platform or (workspace.targetOses[0].value if
        # workspace.targetOses else "Windows")`.
        platform = parsed.platform

        try:
            builder = BuildCommand.CreateBuilder(
                workspace,
                config=parsed.config,
                platform=platform,
                target=project_name,
                verbose=parsed.verbose,
                action="debug",
                options=BuildCommand.CollectFilterOptions(
                    config=parsed.config,
                    platform=parsed.platform,
                    target=project_name,
                    verbose=parsed.verbose,
                    no_cache=False,
                    no_daemon=parsed.no_daemon,
                    extra=["action:debug"] + ([f"toolchain:{str(parsed.toolchain).strip()}"]
                                              if parsed.toolchain else [])
                )
            )
        except Exception as e:
            Colored.PrintError(f"Cannot create builder: {e}")
            return 1

        exe_path = builder.GetTargetPath(project)
        if parsed.build or not exe_path.exists():
            Colored.PrintInfo(f"Building {project_name} ({parsed.config})...")
            build_args = ["--config", parsed.config, "--action", "debug",
                          "--target", project_name]
            if parsed.platform:
                build_args += ["--platform", parsed.platform]
            if parsed.jenga_file:
                build_args += ["--jenga-file", str(entry_file)]
            if parsed.toolchain:  # (2.8.19) la meme chaine que `build --toolchain`
                build_args += ["--toolchain", str(parsed.toolchain).strip()]
            if BuildCommand.Execute(build_args) != 0:
                return 1
            exe_path = builder.GetTargetPath(project)

        if not exe_path.exists():
            Colored.PrintError(f"Executable not found: {exe_path}")
            return 1

        if parsed.config.lower() != "debug":
            Colored.PrintWarning(
                f"Debugging a '{parsed.config}' build — symbols may be missing. "
                f"Prefer --config Debug.")

        # ── 5. Construire la ligne de commande du debugger ────────────────
        if kind == "gdb":
            cmd = GdbCommand._BuildGdbCommand(debugger, exe_path, parsed)
        else:
            cmd = GdbCommand._BuildLldbCommand(debugger, exe_path, parsed)

        Colored.PrintInfo(f"Launching {kind} on {exe_path}...")
        if parsed.verbose:
            Colored.PrintInfo("  " + " ".join(cmd))
        return Process.Run(cmd)

    # -----------------------------------------------------------------------
    @staticmethod
    def _ResolveDebugger(preference: str):
        """Retourne (chemin_debugger, 'gdb'|'lldb') ou (None, None)."""
        if preference == "gdb":
            p = FileSystem.FindExecutable("gdb")
            return (p, "gdb") if p else (None, None)
        if preference == "lldb":
            p = FileSystem.FindExecutable("lldb")
            return (p, "lldb") if p else (None, None)
        # auto : gdb d'abord, puis lldb
        p = FileSystem.FindExecutable("gdb")
        if p:
            return (p, "gdb")
        p = FileSystem.FindExecutable("lldb")
        if p:
            return (p, "lldb")
        return (None, None)

    @staticmethod
    def _BuildGdbCommand(gdb: str, exe_path: Path, parsed) -> List[str]:
        cmd = [str(gdb), "-q"]
        if parsed.batch:
            cmd.append("--batch")
        for bp in parsed.breakpoints:
            cmd += ["-ex", f"break {bp}"]
        if parsed.run or parsed.batch:
            cmd += ["-ex", "run"]
            if parsed.batch:
                cmd += ["-ex", "bt"]   # backtrace utile en CI si crash
        # `--args` doit etre en dernier : exe puis arguments du programme.
        cmd += ["--args", str(exe_path)] + parsed.args
        return cmd

    @staticmethod
    def _BuildLldbCommand(lldb: str, exe_path: Path, parsed) -> List[str]:
        cmd = [str(lldb)]
        if parsed.batch:
            cmd.append("--batch")
        for bp in parsed.breakpoints:
            cmd += ["-o", f"breakpoint set --name {bp}"
                    if ":" not in bp else f"breakpoint set --file {bp.split(':')[0]} "
                    f"--line {bp.split(':')[1]}"]
        if parsed.run or parsed.batch:
            cmd += ["-o", "run"]
            if parsed.batch:
                cmd += ["-o", "bt", "-o", "quit"]
        # lldb : `-- <exe> <args>` separe le programme de ses arguments.
        cmd += ["--", str(exe_path)] + parsed.args
        return cmd
