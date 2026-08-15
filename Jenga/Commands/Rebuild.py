#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Rebuild command – Clean + Build.
"""

import argparse
import sys
from typing import List, Optional, Tuple

from .Clean import CleanCommand
from .Build import BuildCommand


class RebuildCommand:
    """jenga rebuild [options] = clean + build"""

    @staticmethod
    def Execute(args: List[str]) -> int:
        parser = argparse.ArgumentParser(prog="jenga rebuild", description="Clean and build.")
        # On accepte les mêmes options que build et clean
        parser.add_argument("--config", default="Debug", help="Build configuration")
        parser.add_argument("--platform", default=None, help="Target platform")
        parser.add_argument("--target", default=None, help="Specific project to build")
        parser.add_argument("--no-cache", action="store_true", help="Ignore cache")
        parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
        parser.add_argument("--no-daemon", action="store_true", help="Do not use daemon")
        parser.add_argument("--jenga-file", help="Path to the workspace .jenga file (default: auto-detected)")
        parser.add_argument("--keep-going", "-k", action="store_true",
                            help="Build everything that can be built instead of stopping at the "
                                 "first failure (see `jenga build --keep-going`)")
        # Clean spécifique
        parser.add_argument("--clean-all", action="store_true", help="Clean all artifacts (including cache)")
        parsed = parser.parse_args(args)

        # 1. Clean
        clean_args = []
        if parsed.clean_all:
            clean_args.append("--all")
        if parsed.config:
            clean_args += ["--config", parsed.config]
        if parsed.no_daemon:
            clean_args.append("--no-daemon")
        if parsed.jenga_file:
            clean_args += ["--jenga-file", parsed.jenga_file]
        ret = CleanCommand.Execute(clean_args)
        if ret != 0:
            return ret

        # 2. Build
        build_args = [
            "--config", parsed.config,
            "--action", "rebuild",
            "--no-cache" if parsed.no_cache else "",
            "--verbose" if parsed.verbose else "",
            "--no-daemon" if parsed.no_daemon else "",
            "--keep-going" if parsed.keep_going else ""
        ]
        if parsed.platform:
            build_args += ["--platform", parsed.platform]
        if parsed.target:
            build_args += ["--target", parsed.target]
        if parsed.jenga_file:
            build_args += ["--jenga-file", parsed.jenga_file]
        build_args = [arg for arg in build_args if arg]  # enlever les chaînes vides
        return BuildCommand.Execute(build_args)
