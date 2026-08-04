#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Examples command – List and copy example projects.
"""

import argparse
import shutil
import sys
import zipfile
import urllib.request
from pathlib import Path
from typing import List, Dict, Any, Optional

from ..Utils import Colored, Display


class ExamplesCommand:
    """jenga examples [list|copy] [options]"""

    # Depot GitHub d'ou telecharger l'archive d'exemples (release assets).
    GITHUB_REPO = "Rihen-Universe/Jenga"

    # Example projects metadata
    EXAMPLES = {
        "01_hello_console": {
            "name": "Hello Console",
            "description": "Simple Hello World console application",
            "language": "C++",
            "platforms": ["Windows", "Linux", "macOS"],
            "difficulty": "Beginner"
        },
        "02_static_library": {
            "name": "Static Library",
            "description": "Create and use a static library",
            "language": "C++",
            "platforms": ["Windows", "Linux", "macOS"],
            "difficulty": "Beginner"
        },
        "03_shared_library": {
            "name": "Shared Library",
            "description": "Create and use a shared/dynamic library",
            "language": "C++",
            "platforms": ["Windows", "Linux", "macOS"],
            "difficulty": "Beginner"
        },
        "04_unit_tests": {
            "name": "Unit Tests",
            "description": "Unit testing with Jenga's built-in test framework",
            "language": "C++",
            "platforms": ["Windows", "Linux", "macOS"],
            "difficulty": "Beginner"
        },
        "05_android_ndk": {
            "name": "Android NDK",
            "description": "Android native application with APK packaging",
            "language": "C++",
            "platforms": ["Android"],
            "difficulty": "Intermediate"
        },
        "06_ios_app": {
            "name": "iOS Application",
            "description": "iOS native application with Objective-C++",
            "language": "Objective-C++",
            "platforms": ["iOS"],
            "difficulty": "Intermediate"
        },
        "07_web_wasm": {
            "name": "WebAssembly",
            "description": "Compile C++ to WebAssembly with Emscripten",
            "language": "C++",
            "platforms": ["Web"],
            "difficulty": "Intermediate"
        },
        "08_custom_toolchain": {
            "name": "Custom Toolchain",
            "description": "Define and use custom toolchains",
            "language": "C++",
            "platforms": ["Windows", "Linux"],
            "difficulty": "Advanced"
        },
        "09_multi_projects": {
            "name": "Multi-Project Workspace",
            "description": "Multiple projects with dependencies",
            "language": "C++",
            "platforms": ["Windows", "Linux", "macOS"],
            "difficulty": "Intermediate"
        },
        "10_modules_cpp20": {
            "name": "C++20 Modules",
            "description": "Using C++20 modules with MSVC/Clang",
            "language": "C++20",
            "platforms": ["Windows", "Linux"],
            "difficulty": "Advanced"
        },
        "11_benchmark": {
            "name": "Benchmarking",
            "description": "Performance benchmarking suite",
            "language": "C++",
            "platforms": ["Windows", "Linux", "macOS"],
            "difficulty": "Intermediate"
        },
        "12_external_includes": {
            "name": "External Includes",
            "description": "Using external libraries and headers",
            "language": "C++",
            "platforms": ["Windows", "Linux", "macOS"],
            "difficulty": "Beginner"
        },
        "13_packaging": {
            "name": "Packaging",
            "description": "Package distribution and installation",
            "language": "C++",
            "platforms": ["Windows", "Linux", "macOS"],
            "difficulty": "Advanced"
        },
        "14_cross_compile": {
            "name": "Cross Compilation",
            "description": "Cross-compile for different platforms",
            "language": "C++",
            "platforms": ["Windows", "Linux"],
            "difficulty": "Advanced"
        },
        "15_window_win32": {
            "name": "Win32 Window",
            "description": "Native Win32 window application",
            "language": "C++",
            "platforms": ["Windows"],
            "difficulty": "Intermediate"
        },
        "16_window_x11_linux": {
            "name": "X11 Window (Linux)",
            "description": "Native X11 window on Linux",
            "language": "C++",
            "platforms": ["Linux"],
            "difficulty": "Intermediate"
        },
        "17_window_macos_cocoa": {
            "name": "Cocoa Window (macOS)",
            "description": "Native Cocoa window on macOS",
            "language": "Objective-C++",
            "platforms": ["macOS"],
            "difficulty": "Intermediate"
        },
        "18_window_android_native": {
            "name": "Android Native Window",
            "description": "Native Android window with NativeActivity",
            "language": "C++",
            "platforms": ["Android"],
            "difficulty": "Advanced"
        },
        "19_window_web_canvas": {
            "name": "Web Canvas",
            "description": "HTML5 canvas with WebAssembly",
            "language": "C++",
            "platforms": ["Web"],
            "difficulty": "Intermediate"
        },
        "20_window_ios_uikit": {
            "name": "iOS UIKit Window",
            "description": "iOS window with UIKit",
            "language": "Objective-C++",
            "platforms": ["iOS"],
            "difficulty": "Advanced"
        },
        "21_zig_cross_compile": {
            "name": "Zig Cross Compilation",
            "description": "Cross-compile with Zig toolchain",
            "language": "C++",
            "platforms": ["Windows", "Linux", "macOS"],
            "difficulty": "Advanced"
        },
        "22_nk_multiplatform_sandbox": {
            "name": "Nuklear Multi-Platform Sandbox",
            "description": "Complete multi-platform GUI application with Nuklear",
            "language": "C++",
            "platforms": ["Windows", "Linux", "macOS", "Android", "iOS", "Web"],
            "difficulty": "Advanced"
        },
        "23_android_sdl3_ndk_mk": {
            "name": "Android SDL3 (ndk-build)",
            "description": "SDL3 Android via Android.mk/ndk-build",
            "language": "C++",
            "platforms": ["Android"],
            "difficulty": "Advanced"
        },
        "24_all_platforms": {
            "name": "All Platforms",
            "description": "Single project configured for multiple platforms",
            "language": "C++",
            "platforms": ["Windows", "Linux", "Android", "Web"],
            "difficulty": "Advanced"
        },
        "25_opengl_triangle": {
            "name": "OpenGL Triangle",
            "description": "Cross-platform OpenGL/GLES triangle demo",
            "language": "C++",
            "platforms": ["Windows", "Linux", "Android", "Web"],
            "difficulty": "Advanced"
        },
        "26_xbox_project_kinds": {
            "name": "Xbox Project Kinds",
            "description": "Xbox static/shared libraries plus console and windowed apps",
            "language": "C++",
            "platforms": ["Xbox One", "Xbox Series", "Windows"],
            "difficulty": "Advanced"
        },
        "26_xbox_uwp_dev_mode": {
            "name": "Xbox UWP Dev Mode",
            "description": "Explicit UWP Dev Mode flow for Xbox without GDK packaging",
            "language": "C++",
            "platforms": ["Xbox Dev Mode (UWP)", "Windows"],
            "difficulty": "Advanced"
        },
        "27_nk_window": {
            "name": "NK Window Framework",
            "description": "Multi-platform windowing framework with NKWindow and Sandbox demos",
            "language": "C++",
            "platforms": ["Windows", "Linux", "macOS", "Android", "iOS", "Web", "HarmonyOS"],
            "difficulty": "Advanced"
        }
    }

    @staticmethod
    def GetExamplesPath() -> Path:
        """Get the path to the examples directory."""
        module_path = Path(__file__).resolve().parent.parent.parent  # package root

        candidates = [
            module_path / "Exemples",            # legacy layout
            module_path / "Jenga" / "Exemples", # current repo layout
        ]

        for candidate in candidates:
            if candidate.exists():
                return candidate

        # Fallback: try common installation paths
        import site
        try:
            site_paths = site.getsitepackages()
        except Exception:
            site_paths = []
        for site_path in site_paths:
            installed_candidates = [
                Path(site_path) / "Jenga" / "Exemples",
                Path(site_path) / "Jenga" / "Jenga" / "Exemples",
            ]
            for candidate in installed_candidates:
                if candidate.exists():
                    return candidate

        return candidates[0]

    # -----------------------------------------------------------------------
    # Telechargement a la demande des exemples absents du wheel
    # -----------------------------------------------------------------------
    @staticmethod
    def _GetVersion() -> str:
        """Version courante de Jenga (pour cibler l'asset de release)."""
        try:
            from .. import __version__
            return __version__
        except Exception:
            return "latest"

    @staticmethod
    def _ExamplesCacheDir() -> Path:
        """Dossier de cache des exemples telecharges (~/.jenga/examples-cache/<version>)."""
        return Path.home() / ".jenga" / "examples-cache" / ExamplesCommand._GetVersion()

    @staticmethod
    def _DownloadAndExtractExamples() -> bool:
        """
        Telecharge l'archive d'exemples allegee depuis la release GitHub
        correspondant a la version courante, et l'extrait dans le cache.
        L'archive contient un dossier racine 'jenga-examples/<id>/...'.
        Retourne True si l'extraction a reussi.
        """
        version = ExamplesCommand._GetVersion()
        url = (f"https://github.com/{ExamplesCommand.GITHUB_REPO}"
               f"/releases/download/v{version}/jenga-examples-{version}.zip")
        cache = ExamplesCommand._ExamplesCacheDir()
        cache.mkdir(parents=True, exist_ok=True)
        tmp_zip = cache / "_download.zip"

        Colored.PrintInfo(f"Telechargement des exemples depuis : {url}")
        try:
            urllib.request.urlretrieve(url, tmp_zip)
        except Exception as e:
            Colored.PrintError(f"Echec du telechargement : {e}")
            Colored.PrintInfo(
                "Verifie que la release existe, ou clone le depot pour obtenir "
                "tous les exemples : "
                f"https://github.com/{ExamplesCommand.GITHUB_REPO}")
            return False
        try:
            with zipfile.ZipFile(tmp_zip) as zf:
                zf.extractall(cache)
        except Exception as e:
            Colored.PrintError(f"Archive d'exemples invalide : {e}")
            return False
        finally:
            try:
                tmp_zip.unlink()
            except OSError:
                pass
        return True

    @staticmethod
    def _ResolveExampleDir(example_id: str) -> Optional[Path]:
        """
        Localise le dossier d'un exemple, dans l'ordre :
          1. Local : depot clone ou mini-echantillon embarque dans le wheel.
          2. Cache : archive deja telechargee.
          3. Telechargement a la demande depuis la release GitHub.
        Retourne le Path, ou None si introuvable apres tentative de download.
        """
        local = ExamplesCommand.GetExamplesPath() / example_id
        if local.exists():
            return local

        cached = ExamplesCommand._ExamplesCacheDir() / "jenga-examples" / example_id
        if cached.exists():
            return cached

        Colored.PrintInfo(
            f"Exemple '{example_id}' absent en local — telechargement a la demande...")
        if ExamplesCommand._DownloadAndExtractExamples() and cached.exists():
            return cached
        return None

    @staticmethod
    def ListExamples(args: List[str]) -> int:
        """List all available example projects."""
        parser = argparse.ArgumentParser(prog="jenga examples list", description="List all available example projects.")
        parser.add_argument("--filter", default=None, help="Filter by platform or difficulty")
        parsed = parser.parse_args(args)

        examples_path = ExamplesCommand.GetExamplesPath()
        cache_root = ExamplesCommand._ExamplesCacheDir() / "jenga-examples"
        # Pas d'echec si le dossier est absent : les exemples non-locaux sont
        # marques "telechargeables a la demande" (voir jenga examples copy).

        # Header
        print()
        print(Colored.Colorize("═" * 100, color='cyan', bold=True))
        title = "Jenga EXAMPLE PROJECTS"
        print(Colored.Colorize(title.center(100), color='white', bold=True))
        print(Colored.Colorize("═" * 100, color='cyan', bold=True))
        print()

        # Filter examples
        filtered = ExamplesCommand.EXAMPLES.items()
        if parsed.filter:
            filter_lower = parsed.filter.lower()
            filtered = [
                (key, meta) for key, meta in ExamplesCommand.EXAMPLES.items()
                if filter_lower in meta.get("difficulty", "").lower()
                or any(filter_lower in p.lower() for p in meta.get("platforms", []))
            ]

        if not filtered:
            Colored.PrintWarning(f"No examples match filter: {parsed.filter}")
            return 0

        # Display examples in a nice table format
        for idx, (key, meta) in enumerate(filtered, 1):
            # Disponibilite : local (clone/wheel sample) ou cache telecharge.
            exists_local = (examples_path / key).exists() or (cache_root / key).exists()

            # Number and name
            num = Colored.Colorize(f"{idx:2d}.", color='cyan', bold=True)
            name = Colored.Colorize(meta['name'], color='white', bold=True)

            # Status : ✓ disponible localement, ⤓ telechargeable a la demande.
            status = (Colored.Colorize("✓", color='green') if exists_local
                      else Colored.Colorize("⤓", color='yellow'))

            print(f"{num} {status} {name}")
            print(f"    {Colored.Colorize('ID:', color='yellow')} {key}")
            print(f"    {Colored.Colorize('Description:', color='yellow')} {meta['description']}")

            # Platforms
            platforms_str = ", ".join(meta['platforms'])
            platforms_colored = Colored.Colorize(platforms_str, color='cyan')
            print(f"    {Colored.Colorize('Platforms:', color='yellow')} {platforms_colored}")

            # Difficulty
            difficulty = meta['difficulty']
            diff_color = {'Beginner': 'green', 'Intermediate': 'yellow', 'Advanced': 'red'}.get(difficulty, 'white')
            diff_colored = Colored.Colorize(difficulty, color=diff_color, bold=True)
            print(f"    {Colored.Colorize('Difficulty:', color='yellow')} {diff_colored}")

            print()

        # Footer with usage
        print(Colored.Colorize("─" * 100, color='cyan'))
        print(f"  {Colored.Colorize('✓', color='green')} disponible localement   "
              f"{Colored.Colorize('⤓', color='yellow')} téléchargé à la demande "
              f"depuis la release GitHub")
        print(Colored.Colorize("Usage:", color='yellow', bold=True))
        print(f"  {Colored.Colorize('jenga examples copy', color='green')} {Colored.Colorize('<example-id>', color='cyan')} {Colored.Colorize('<destination-parent>', color='cyan')} [{Colored.Colorize('--name', color='yellow')} {Colored.Colorize('<new-name>', color='cyan')}]")
        print(f"  Example: {Colored.Colorize('jenga examples copy 01_hello_console ~/projects --name hello_demo', color='green')}")
        print(Colored.Colorize("═" * 100, color='cyan', bold=True))
        print()

        return 0

    @staticmethod
    def CopyExample(args: List[str]) -> int:
        """Copy an example project to a destination."""
        parser = argparse.ArgumentParser(
            prog="jenga examples copy",
            description="Copy an example project to a destination directory."
        )
        parser.add_argument("example_id", help="Example project ID (e.g., 01_hello_console)")
        parser.add_argument("destination", help="Destination parent directory path")
        parser.add_argument("--name", "-n", default="", help="Override destination folder name")
        parser.add_argument("--force", "-f", action="store_true", help="Overwrite if destination exists")
        parsed = parser.parse_args(args)

        # Validate example ID
        if parsed.example_id not in ExamplesCommand.EXAMPLES:
            Colored.PrintError(f"Unknown example ID: {parsed.example_id}")
            Colored.PrintInfo("Use 'jenga examples list' to see available examples.")
            return 1

        # Get paths — local (clone/wheel sample), cache, ou telechargement.
        source_path = ExamplesCommand._ResolveExampleDir(parsed.example_id)
        dest_root = Path(parsed.destination).resolve()
        dest_name = (parsed.name or parsed.example_id).strip()
        if not dest_name:
            Colored.PrintError("Invalid destination folder name.")
            return 1
        dest_path = dest_root / dest_name

        # Check source exists (apres tentative de telechargement a la demande)
        if source_path is None or not source_path.exists():
            Colored.PrintError(f"Example not found and download failed: {parsed.example_id}")
            return 1

        # Check destination parent
        if dest_root.exists() and not dest_root.is_dir():
            Colored.PrintError(f"Destination parent is not a directory: {dest_root}")
            return 1
        if not dest_root.exists():
            dest_root.mkdir(parents=True, exist_ok=True)

        # Check destination folder
        if dest_path.exists():
            if not parsed.force:
                Colored.PrintError(f"Destination already exists: {dest_path}")
                Colored.PrintInfo("Use --force to overwrite.")
                return 1
            else:
                Colored.PrintWarning(f"Removing existing directory: {dest_path}")
                shutil.rmtree(dest_path)

        # Copy example
        meta = ExamplesCommand.EXAMPLES[parsed.example_id]
        print()
        Colored.PrintInfo(f"Copying example: {Colored.Colorize(meta['name'], color='white', bold=True)}")
        print(f"  {Colored.Colorize('From:', color='cyan')} {source_path}")
        print(f"  {Colored.Colorize('To:', color='cyan')}   {dest_path}")
        print()

        try:
            shutil.copytree(source_path, dest_path)

            # Keep workspace file name aligned with copied folder name when renamed.
            if dest_name != parsed.example_id:
                source_jenga = dest_path / f"{parsed.example_id}.jenga"
                if source_jenga.exists():
                    target_jenga = dest_path / f"{dest_name}.jenga"
                    source_jenga.rename(target_jenga)
                else:
                    jenga_files = list(dest_path.glob("*.jenga"))
                    if len(jenga_files) == 1 and jenga_files[0].stem != dest_name:
                        target_jenga = dest_path / f"{dest_name}.jenga"
                        jenga_files[0].rename(target_jenga)

            Colored.PrintSuccess(f"Example copied successfully!")
            print()
            Colored.PrintInfo("Next steps:")
            print(f"  1. {Colored.Colorize('cd', color='green')} {dest_path}")
            print(f"  2. {Colored.Colorize('jenga build', color='green')}")
            print()
            return 0
        except Exception as e:
            Colored.PrintError(f"Failed to copy example: {e}")
            return 1

    @staticmethod
    def Execute(args: List[str]) -> int:
        """Execute the examples command."""
        if not args or args[0] in ("-h", "--help"):
            print()
            print(Colored.Colorize("jenga examples", color='green', bold=True) + " - Manage example projects")
            print()
            print(Colored.Colorize("Commands:", color='yellow', bold=True))
            print(f"  {Colored.Colorize('list', color='cyan')}   - List all available example projects")
            print(f"  {Colored.Colorize('copy', color='cyan')}   - Copy an example project to a directory")
            print()
            print(Colored.Colorize("Usage:", color='yellow', bold=True))
            print(f"  jenga examples list [--filter <platform|difficulty>]")
            print(f"  jenga examples copy <example-id> <destination-parent> [--name <new-name>] [--force]")
            print()
            print(Colored.Colorize("Examples:", color='yellow', bold=True))
            print(f"  jenga examples list")
            print(f"  jenga examples list --filter Android")
            print(f"  jenga examples list --filter Advanced")
            print(f"  jenga examples copy 01_hello_console ~/projects")
            print(f"  jenga examples copy 01_hello_console ~/projects --name my_console")
            print(f"  jenga examples copy 09_multi_projects ./test --force")
            print()
            return 0

        command = args[0]

        if command == "list":
            return ExamplesCommand.ListExamples(args[1:])
        elif command == "copy":
            return ExamplesCommand.CopyExample(args[1:])
        else:
            Colored.PrintError(f"Unknown command: {command}")
            Colored.PrintInfo("Use 'jenga examples --help' for usage.")
            return 1
