#!/usr/bin/env python3
"""
CompileFlags.py — `jenga compile-flags` : émet en JSON les flags de compilation d'un
projet (compilateur du toolchain, standard C++, include dirs, defines). Sert aux IDE
(NKCode) pour la vérification de syntaxe / diagnostics (squiggles) SANS lancer un build.

Sortie (stdout, une ligne JSON) :
  {"compiler": "...", "family": "clang", "msvc": false, "std": "c++20",
   "syntaxOnly": ["-fsyntax-only"], "includes": ["/abs/inc", ...], "defines": ["FOO=1", ...],
   "project": "NKCode", "lang": "c++"}
"""
import argparse
import json
from pathlib import Path

from ..Core.Loader import Loader
from ..Utils import FileSystem
from .Build import BuildCommand


class CompileFlagsCommand:
    @staticmethod
    def Execute(args) -> int:
        parser = argparse.ArgumentParser(prog="jenga compile-flags", add_help=False)
        parser.add_argument("--target", default=None, help="Projet ciblé (sinon startProject / premier)")
        parser.add_argument("--platform", default=None)
        parser.add_argument("--config", default="Debug")
        parser.add_argument("--file", default=None, help="Fichier source (pour deviner le projet)")
        parser.add_argument("--jenga-file", default=None)
        parser.add_argument("--toolchain", default=None)
        parsed, _ = parser.parse_known_args(args)

        def emit_err(msg: str) -> int:
            print(json.dumps({"error": msg}))
            return 1

        # ── Fichier workspace ──
        if parsed.jenga_file:
            entry = Path(parsed.jenga_file).resolve()
        else:
            entry = FileSystem.FindWorkspaceEntry(Path.cwd())
        if not entry or not Path(entry).exists():
            return emit_err("no workspace")

        try:
            loader = Loader()
            workspace = loader.LoadWorkspace(str(entry))
        except Exception as e:  # noqa: BLE001
            return emit_err(f"load: {e}")

        projects = getattr(workspace, "projects", {}) or {}
        if not projects:
            return emit_err("no project")

        # ── Un builder (résout le toolchain une fois), réutilisé pour TOUS les projets ──
        sp = getattr(workspace, "startProject", None)
        seed = projects[sp] if (sp and sp in projects) else next(iter(projects.values()))
        extra = [f"toolchain:{parsed.toolchain}"] if parsed.toolchain else None
        options = BuildCommand.CollectFilterOptions(
            config=parsed.config, platform=parsed.platform, target=seed.name,
            verbose=False, no_cache=True, no_daemon=True, extra=extra)
        try:
            builder = BuildCommand.CreateBuilder(
                workspace, config=parsed.config, platform=parsed.platform,
                target=seed.name, verbose=False, options=options)
        except Exception as e:  # noqa: BLE001
            return emit_err(f"builder: {e}")

        tc = getattr(builder, "toolchain", None)
        fam = str(getattr(tc, "compilerFamily", "")).lower()
        is_msvc = "msvc" in fam
        cxx = str(getattr(tc, "cxxPath", "") or getattr(tc, "ccPath", "") or "")

        # ── FORMAT PROPRIÉTAIRE .jcdb (Jenga Compilation DataBase) — plat, tab-séparé,
        #    UNE SECTION PAR PROJET (chacun a ses includes/defines/std/dossier). ──
        lines = ["# jcdb/1  Jenga Compilation DataBase",
                 f"compiler\t{cxx}",
                 f"msvc\t{1 if is_msvc else 0}"]

        for name, proj in projects.items():
            try:
                builder._ApplyProjectFilters(proj)
            except Exception:  # noqa: BLE001
                pass
            std = str(getattr(proj, "cppdialect", "") or "").replace(" ", "").lower()
            if not std:
                std = "c++20"
            elif not std.startswith("c++"):
                std = "c++" + std.lstrip("+")
            base = getattr(proj, "location", None) or getattr(proj, "_jengaPath", None) or getattr(proj, "_jengaFile", None)
            pdir = ""
            if base:
                bp = Path(base)
                pdir = str((bp.parent if (bp.suffix and not bp.is_dir()) else bp).resolve())
            lines.append(f"project\t{name}")
            lines.append(f"dir\t{pdir}")
            lines.append(f"std\t{std}")
            for inc in (getattr(proj, "includeDirs", []) or []):
                try:
                    lines.append(f"inc\t{Path(builder.ResolveProjectPath(proj, inc)).resolve()}")
                except Exception:  # noqa: BLE001
                    lines.append(f"inc\t{inc}")
            for d in (getattr(proj, "defines", []) or []):
                lines.append(f"def\t{d}")

        payload = "\n".join(lines) + "\n"
        try:
            jdir = Path(entry).parent / ".jenga"
            jdir.mkdir(parents=True, exist_ok=True)
            (jdir / "compileflags.jcdb").write_text(payload, encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass

        # stdout : JSON récap (pratique/debug) — le fichier .jcdb reste l'interface IDE.
        print(json.dumps({"format": "jcdb/1", "compiler": cxx, "msvc": is_msvc,
                          "projects": len(projects)}))
        return 0

    @staticmethod
    def _FindProjectForFile(projects, filepath):
        """Projet dont le dossier (celui de son .jenga) est l'ancêtre le plus PROCHE
        du fichier. Chaque Project connaît `_jengaPath` (le .jenga qui l'a défini)."""
        try:
            target = Path(filepath).resolve()
        except Exception:  # noqa: BLE001
            return None
        best, best_len = None, -1
        for p in projects.values():
            base = getattr(p, "_jengaPath", None) or getattr(p, "_jengaFile", None) \
                or getattr(p, "location", None) or getattr(p, "baseDir", None)
            if not base:
                continue
            try:
                bp = Path(base)
                if bp.is_file() or bp.suffix:
                    bp = bp.parent
                bp = bp.resolve()
                if bp == target or bp in target.parents:
                    n = len(str(bp))
                    if n > best_len:
                        best, best_len = p, n
            except Exception:  # noqa: BLE001
                pass
        return best
