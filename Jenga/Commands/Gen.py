#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Gen command – Génère des fichiers projet pour différents outils de build.
Support : CMake, Makefile, MK, Android NDK MK, Visual Studio 2022, Xcode.
"""

import argparse
import os
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..Core.Loader import Loader
from ..Core.Cache import Cache
from ..Core.Builder import Builder
from ..Core.Platform import Platform
from ..Utils import FileSystem, Colored
from ..Core import Api


class GenCommand:
    """jenga gen [--cmake] [--makefile] [--vs2022] [--xcode] [--output DIR] [--no-cache]"""

    @staticmethod
    def Execute(args: List[str]) -> int:
        parser = argparse.ArgumentParser(prog="jenga gen", description="Generate IDE project files.")
        parser.add_argument("--all", action="store_true", help="Generate all available outputs")
        parser.add_argument("--cmake", action="store_true", help="Generate CMakeLists.txt")
        parser.add_argument("--makefile", action="store_true", help="Generate Makefile")
        parser.add_argument("--mk", action="store_true", help="Generate workspace.mk include file")
        parser.add_argument("--android-mk", action="store_true", help="Generate Android.mk/Application.mk")
        parser.add_argument("--vs2022", "--vs", dest="vs2022", action="store_true",
                            help="Generate a Visual Studio solution (any VS >= 2019: toolset = the opening VS's default)")
        parser.add_argument("--xcode", action="store_true", help="Generate Xcode project (.xcodeproj)")
        parser.add_argument("--compile-commands", action="store_true",
                            help="Generate compile_commands.json (clangd, VS Code, CLion) from the REAL build commands")
        parser.add_argument("--config", default="Debug", help="Context configuration for filters")
        parser.add_argument("--platform", default=None, help="Context platform for filters (e.g. Windows-x86_64)")
        parser.add_argument("--output", "-o", default=".", help="Output directory")
        parser.add_argument("--no-cache", action="store_true", help="Reload workspace without cache")
        parser.add_argument("--jenga-file", help="Path to the workspace .jenga file (default: auto-detected)")
        parsed, unknown_args = parser.parse_known_args(args)

        if parsed.all:
            parsed.cmake = parsed.makefile = parsed.mk = parsed.android_mk = parsed.vs2022 = parsed.xcode = True
            parsed.compile_commands = True

        if not (parsed.cmake or parsed.makefile or parsed.mk or parsed.android_mk or parsed.vs2022
                or parsed.xcode or parsed.compile_commands):
            Colored.PrintError("No generator specified. Use --cmake, --makefile, --mk, --android-mk, --vs, "
                               "--xcode or --compile-commands.")
            return 1

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

        # Charger le workspace
        loader = Loader(verbose=False)
        cache = Cache(workspace_root)
        if parsed.no_cache:
            workspace = loader.LoadWorkspace(str(entry_file))
        else:
            workspace = cache.LoadWorkspace(entry_file, loader)
            if workspace is None:
                workspace = loader.LoadWorkspace(str(entry_file))

        if workspace is None:
            Colored.PrintError("Failed to load workspace.")
            return 1

        output_dir = Path(parsed.output).resolve()
        FileSystem.MakeDirectory(output_dir)
        
        from .Build import BuildCommand
        try:
            cli_custom_options = BuildCommand.ParseCustomOptionArgs(unknown_args)
        except ValueError as e:
            Colored.PrintError(str(e))
            return 1

        try:
            custom_option_values = BuildCommand.ResolveWorkspaceOptions(workspace, cli_custom_options)
        except ValueError as e:
            Colored.PrintError(str(e))
            return 1

        # Each generator gets its own filter action context.
        context_platform = parsed.platform
        if not context_platform:
            host_os = Platform.GetHostOS().value
            host_arch = Platform.GetHostArchitecture().value
            context_platform = f"{host_os}-{host_arch}"

        android_context_platform = context_platform
        if not parsed.platform and parsed.android_mk:
            android_arch = None
            for arch in (workspace.targetArchs or []):
                if GenCommand._MapArchToAndroidAbi(arch):
                    android_arch = arch
                    break
            if android_arch is None:
                android_arch = Api.TargetArch.ARM64
            android_context_platform = f"{Api.TargetOS.ANDROID.value}-{android_arch.value}"

        def _build_gen_context(action: str, generator_token: str, platform_override: Optional[str] = None) -> Builder:
            active_platform = platform_override or context_platform
            opts = BuildCommand.CollectFilterOptions(
                config=parsed.config,
                platform=active_platform,
                target=None,
                verbose=False,
                no_cache=parsed.no_cache,
                no_daemon=True,
                extra=[f"action:{action}", f"generator:{generator_token}"],
                custom_option_values=custom_option_values
            )
            bld = GenCommand._CreateGenerationBuilder(
                workspace,
                config=parsed.config,
                platform=active_platform,
                action=action,
                options=opts
            )
            GenCommand._ApplyGenerationFilters(workspace, bld)
            return bld

        if parsed.cmake:
            builder = _build_gen_context("gen-cmake", "cmake")
            GenCommand._GenerateCMake(workspace, output_dir, builder)
        if parsed.makefile:
            builder = _build_gen_context("gen-makefile", "makefile")
            GenCommand._GenerateMakefile(workspace, output_dir, builder, entry_file)
        if parsed.mk:
            builder = _build_gen_context("gen-mk", "mk")
            GenCommand._GenerateMk(workspace, output_dir, builder, entry_file)
        if parsed.android_mk:
            builder = _build_gen_context("gen-android-mk", "android-mk", platform_override=android_context_platform)
            GenCommand._GenerateAndroidMk(workspace, output_dir, builder)
        if parsed.vs2022:
            builder = _build_gen_context("gen-vs2022", "vs2022")
            GenCommand._GenerateVS2022(workspace, output_dir, builder)
        if parsed.xcode:
            builder = _build_gen_context("gen-xcode", "xcode")
            GenCommand._GenerateXcode(workspace, output_dir, builder)
        if parsed.compile_commands:
            # Builder REEL (pas le builder de generation, dont Compile() ne fait
            # rien) : on veut les commandes que `jenga build` lancerait.
            opts = BuildCommand.CollectFilterOptions(
                config=parsed.config, platform=context_platform, target=None,
                verbose=False, no_cache=parsed.no_cache, no_daemon=True,
                extra=["action:build"], custom_option_values=custom_option_values)
            try:
                real = BuildCommand.CreateBuilder(workspace, parsed.config, context_platform, None, False,
                                                  action="build", options=opts)
            except Exception as e:  # noqa: BLE001
                Colored.PrintError(f"compile_commands.json: cannot create builder: {e}")
                return 1
            if not GenCommand._GenerateCompileCommands(workspace, output_dir, real):
                return 1

        return 0

    @staticmethod
    def _ApplyGenerationFilters(workspace, builder: Builder) -> None:
        """Materialize project filters for the generation action/context."""
        for proj in workspace.projects.values():
            if proj.name.startswith("__"):
                continue
            builder._ApplyProjectFilters(proj)

    @staticmethod
    def _CreateGenerationBuilder(workspace,
                                 config: str,
                                 platform: Optional[str],
                                 action: str,
                                 options: Optional[List[str]] = None) -> Builder:
        """
        Create a lightweight builder context for generation/filter resolution.
        This intentionally avoids toolchain detection so `jenga gen` works even
        when no compiler toolchain is installed on the host.
        """
        target_os = None
        target_arch = None
        target_env = None

        if platform:
            parts = platform.split("-")
            os_name = parts[0]
            for os_enum in Api.TargetOS:
                if os_enum.value.lower() == os_name.lower():
                    target_os = os_enum
                    break
            if len(parts) > 1:
                arch_name = parts[1]
                for arch_enum in Api.TargetArch:
                    if arch_enum.value.lower() == arch_name.lower():
                        target_arch = arch_enum
                        break
            if len(parts) > 2:
                env_name = parts[2]
                for env_enum in Api.TargetEnv:
                    if env_enum.value.lower() == env_name.lower():
                        target_env = env_enum
                        break

        if target_os is None:
            target_os = Platform.GetHostOS()
        if target_arch is None:
            target_arch = Platform.GetHostArchitecture()

        platform_value = platform or f"{target_os.value}-{target_arch.value}"

        class _GenerationContextBuilder(Builder):
            def _ValidateHostTarget(self):
                # Generation does not emit binaries, so host-target restrictions
                # (e.g. iOS/macOS) are not relevant here.
                return

            def _ResolveToolchain(self) -> None:
                class _GenToolchain:
                    name = "gen-context"
                    compilerFamily = Api.CompilerFamily.CLANG
                self.toolchain = _GenToolchain()

            def Compile(self, project, sourceFile: str, objectFile: str) -> bool:
                return True

            def Link(self, project, objectFiles: List[str], outputFile: str) -> bool:
                return True

            def GetOutputExtension(self, project) -> str:
                return ""

            def GetObjectExtension(self) -> str:
                return ".o"

            def GetModuleFlags(self, project, sourceFile: str) -> List[str]:
                return []

        return _GenerationContextBuilder(
            workspace=workspace,
            config=config,
            platform=platform_value,
            targetOs=target_os,
            targetArch=target_arch,
            targetEnv=target_env,
            verbose=False,
            action=action,
            options=options or [],
        )

    # -----------------------------------------------------------------------
    # Générateur CMake
    # -----------------------------------------------------------------------

    # -----------------------------------------------------------------------
    # compile_commands.json (clangd, VS Code C/C++, CLion, Qt Creator)
    # -----------------------------------------------------------------------
    # L'aide de jenga annonçait ce fichier depuis longtemps ; aucune commande
    # ne l'ecrivait (`compile-flags` produit le .jcdb interne de NKCode).
    #
    # Les commandes ne sont PAS reconstruites : on appelle le vrai
    # builder.Compile() de la plateforme, et on CAPTURE la commande qu'il
    # passerait a Process.ExecuteCommand au lieu de la lancer. La base decrit
    # donc exactement le build de Jenga -- toolchain, --target, defines de
    # filtre compris -- et suit toute evolution des builders sans rien a
    # maintenir ici.
    _LANCEURS = {"ccache", "ccache.exe", "sccache", "sccache.exe"}

    @staticmethod
    def _GenerateCompileCommands(workspace, output_dir: Path, builder) -> bool:
        import json
        from ..Utils import Process, ProcessResult

        entrees: List[Dict[str, Any]] = []
        capturees: List[List[str]] = []

        def _capture(args, *a, **k):
            liste = [str(x) for x in args] if isinstance(args, (list, tuple)) else [str(args)]
            capturees.append(liste)
            return ProcessResult(returnCode=0, stdout="", stderr="", command=" ".join(liste))

        # L'attribut tel qu'il est DANS la classe (le staticmethod), pour le
        # restaurer a l'identique quoi qu'il arrive.
        origine = Process.__dict__["ExecuteCommand"]
        Process.ExecuteCommand = staticmethod(_capture)
        try:
            for name, proj in workspace.projects.items():
                if name.startswith("__") or proj.kind not in (
                        Api.ProjectKind.CONSOLE_APP, Api.ProjectKind.WINDOWED_APP, Api.ProjectKind.TEST_SUITE,
                        Api.ProjectKind.STATIC_LIB, Api.ProjectKind.SHARED_LIB):
                    continue
                builder.PrepareProjectForCompile(proj)
                obj_dir = Path(builder.GetObjectDir(proj))
                base = Path(proj.location) if proj.location else Path(workspace.location or ".")
                if not base.is_absolute():
                    base = Path(workspace.location or ".") / base
                for src in builder._CollectSourceFiles(proj):
                    src_path = Path(src).resolve()
                    obj = obj_dir / builder.GetObjectName(proj, src_path)
                    capturees.clear()
                    try:
                        builder.Compile(proj, str(src_path), str(obj))
                    except Exception as e:  # noqa: BLE001
                        Colored.PrintWarning(f"compile_commands.json: {name}/{src_path.name} skipped ({e})")
                        continue
                    cmd = next((c for c in reversed(capturees) if str(src_path) in c or src in c), None)
                    if not cmd:
                        continue
                    if Path(cmd[0]).name.lower() in GenCommand._LANCEURS:
                        cmd = cmd[1:]
                    entrees.append({
                        "directory": str(base.resolve()),
                        "file": str(src_path),
                        "arguments": cmd,
                        "output": str(obj),
                    })
        finally:
            Process.ExecuteCommand = origine

        if not entrees:
            # Un fichier vide n'est pas un resultat : on le dit au lieu de
            # l'ecrire (clangd croirait n'avoir rien a indexer).
            Colored.PrintError("compile_commands.json: no compile command captured (no source file?)")
            return False
        chemin = output_dir / "compile_commands.json"
        texte = json.dumps(entrees, indent=2, ensure_ascii=False) + "\n"
        tmp = chemin.with_suffix(".json.tmp")
        tmp.write_bytes(texte.encode("utf-8"))
        os.replace(tmp, chemin)
        Colored.PrintSuccess(f"compile_commands.json generated: {chemin} ({len(entrees)} entries)")
        return True

    # -----------------------------------------------------------------------
    # Chemins ecrits dans les fichiers generes
    # -----------------------------------------------------------------------
    # Avant 2.8.4, tous les generateurs ecrivaient str(Path) : sous Windows,
    # « C:\Users\... » avec des antislashs. CMake les lit comme des sequences
    # d'echappement (« Invalid character escape '\U' ») et le shell de make les
    # mange (« C:Users... »). Les fichiers generes etaient en plus lies a la
    # machine qui les avait produits.
    #
    # Regle : toujours des « / » ; relatif au fichier genere quand c'est
    # possible (le dossier se deplace avec ses sources), absolu en « / » sinon
    # (autre lecteur Windows).

    @staticmethod
    def _Posix(path) -> str:
        return str(path).replace("\\", "/")

    @staticmethod
    def _RelTo(path, base: Path, prefix: str = "") -> str:
        """Chemin relatif a `base`, en « / », precede de `prefix` s'il est donne."""
        cible = Path(path)
        if not cible.is_absolute():
            cible = (Path(base) / cible)
        try:
            rel = os.path.relpath(str(cible.resolve()), str(Path(base).resolve()))
        except ValueError:
            return GenCommand._Posix(cible.resolve())
        rel = GenCommand._Posix(rel)
        return f"{prefix}/{rel}" if prefix else rel

    # Extension -> langage CMake. Point d'extension : un nouveau langage se
    # declare ici, et `project(... LANGUAGES ...)` ne demandera que ceux qui
    # ont reellement des sources.
    _CMAKE_LANG_BY_EXT = {
        ".c": "C",
        ".cpp": "CXX", ".cc": "CXX", ".cxx": "CXX", ".c++": "CXX", ".cppm": "CXX", ".ixx": "CXX",
        ".s": "ASM", ".asm": "ASM",
        ".m": "OBJC",
        ".mm": "OBJCXX",
    }

    @staticmethod
    def _GenerateCMake(workspace, output_dir: Path, builder: Builder):
        """Génère un CMakeLists.txt à la racine du workspace."""
        cmake_path = output_dir / "CMakeLists.txt"

        # Les langages DEMANDES a CMake sont ceux qui ont des sources. Declarer
        # OBJC/OBJCXX pour un projet C++ obligeait CMake a trouver un
        # compilateur Objective-C, et la configuration echouait sans lui.
        fichiers: Dict[str, Tuple[List[str], List[str]]] = {}
        langages = ["C", "CXX"]
        for proj_name, proj in workspace.projects.items():
            if proj_name.startswith('__'):
                continue
            fichiers[proj_name] = GenCommand._CollectProjectFilesForGen(proj, builder)
            for src in fichiers[proj_name][0]:
                lang = GenCommand._CMAKE_LANG_BY_EXT.get(Path(src).suffix.lower())
                if lang and lang not in langages:
                    langages.append(lang)

        with open(cmake_path, 'w', encoding='utf-8') as f:
            f.write("cmake_minimum_required(VERSION 3.20)\n")
            f.write(f"project({workspace.name} LANGUAGES {' '.join(langages)})\n\n")

            # Options de configuration (multi-config generators)
            if workspace.configurations:
                joined_cfg = " ".join(workspace.configurations)
                f.write(f"set(CMAKE_CONFIGURATION_TYPES \"{joined_cfg}\" CACHE STRING \"Jenga configurations\" FORCE)\n")
                f.write("if(NOT CMAKE_BUILD_TYPE)\n")
                f.write(f"  set(CMAKE_BUILD_TYPE \"{workspace.configurations[0]}\" CACHE STRING \"\" FORCE)\n")
                f.write("endif()\n\n")

            # Ajouter tous les projets
            for proj_name, proj in workspace.projects.items():
                if proj_name.startswith('__'):
                    continue
                GenCommand._WriteCMakeProject(f, proj_name, proj, workspace, builder,
                                              output_dir, fichiers[proj_name])

        Colored.PrintSuccess(f"CMakeLists.txt generated: {cmake_path}")

    @staticmethod
    def _WriteCMakeProject(f, name: str, proj, workspace, builder: Builder,
                           output_dir: Path, fichiers: Tuple[List[str], List[str]]):
        """Écrit un projet CMake (add_executable ou add_library)."""
        # Déterminer le type. WIN32 : sous Windows, une application fenetree
        # utilise le sous-systeme GUI (WinMain) ; CMake l'ignore ailleurs.
        if proj.kind == Api.ProjectKind.WINDOWED_APP:
            cmd = f"add_executable({name} WIN32"
        elif proj.kind in (Api.ProjectKind.CONSOLE_APP, Api.ProjectKind.TEST_SUITE):
            cmd = f"add_executable({name}"
        elif proj.kind == Api.ProjectKind.STATIC_LIB:
            cmd = f"add_library({name} STATIC"
        elif proj.kind == Api.ProjectKind.SHARED_LIB:
            cmd = f"add_library({name} SHARED"
        else:
            return

        base = "${CMAKE_CURRENT_SOURCE_DIR}"
        chemin = lambda p: GenCommand._RelTo(p, output_dir, base)

        f.write(f"\n# Project: {name}\n")
        src_files, hdr_files = fichiers

        # Écrire la commande principale
        f.write(f"{cmd}\n")
        for sf in src_files:
            f.write(f"  \"{chemin(sf)}\"\n")
        f.write(")\n")

        # Headers (pour IDE)
        if hdr_files:
            f.write(f"target_sources({name} PRIVATE\n")
            for hf in hdr_files:
                f.write(f"  \"{chemin(hf)}\"\n")
            f.write(")\n")

        # Includes
        if proj.includeDirs:
            f.write(f"target_include_directories({name} PRIVATE\n")
            for inc in proj.includeDirs:
                f.write(f"  \"{chemin(builder.ResolveProjectPath(proj, inc))}\"\n")
            f.write(")\n")

        # Library search paths
        if proj.libDirs:
            f.write(f"target_link_directories({name} PRIVATE\n")
            for libdir in proj.libDirs:
                f.write(f"  \"{chemin(builder.ResolveProjectPath(proj, libdir))}\"\n")
            f.write(")\n")

        # Définitions
        if proj.defines:
            f.write(f"target_compile_definitions({name} PRIVATE\n")
            for d in proj.defines:
                f.write(f"  {d}\n")
            f.write(")\n")

        # Compile options
        c_flags = [flag for flag in proj.cflags if flag]
        cxx_flags = [flag for flag in proj.cxxflags if flag]
        if c_flags:
            f.write(f"target_compile_options({name} PRIVATE\n")
            for flag in c_flags:
                f.write(f"  $<$<COMPILE_LANGUAGE:C>:{flag}>\n")
            f.write(")\n")
        if cxx_flags:
            f.write(f"target_compile_options({name} PRIVATE\n")
            for flag in cxx_flags:
                f.write(f"  $<$<COMPILE_LANGUAGE:CXX>:{flag}>\n")
            f.write(")\n")

        # Link options
        if proj.ldflags:
            f.write(f"target_link_options({name} PRIVATE\n")
            for flag in proj.ldflags:
                f.write(f"  {flag}\n")
            f.write(")\n")

        # Librairies. Jenga lie AUTOMATIQUEMENT les bibliotheques du workspace
        # citees dans dependson() (Builders/Windows.py, Linux.py) : le CMake
        # genere doit faire de meme, sinon un projet qui ne les repete pas dans
        # links() construit avec Jenga et echoue au lien avec CMake.
        a_lier: List[str] = [str(lib) for lib in proj.links]
        for dep in proj.dependsOn:
            dep_proj = workspace.projects.get(dep)
            if (dep_proj is not None and not dep.startswith("__")
                    and dep_proj.kind in (Api.ProjectKind.STATIC_LIB, Api.ProjectKind.SHARED_LIB)
                    and dep not in a_lier):
                a_lier.append(dep)
        if a_lier:
            f.write(f"target_link_libraries({name} PRIVATE\n")
            for lib in a_lier:
                if lib in workspace.projects or not ("/" in lib or "\\" in lib):
                    f.write(f"  {lib}\n")
                else:
                    f.write(f"  \"{chemin(builder.ResolveProjectPath(proj, lib))}\"\n")
            f.write(")\n")

        # Dépendances explicites de build order
        deps = [dep for dep in proj.dependsOn if dep in workspace.projects and not dep.startswith("__")]
        if deps:
            f.write(f"add_dependencies({name}\n")
            for dep in deps:
                f.write(f"  {dep}\n")
            f.write(")\n")

        # Propriétés spécifiques
        if proj.kind == Api.ProjectKind.SHARED_LIB:
            f.write(f"set_target_properties({name} PROPERTIES PREFIX \"\")\n")  # évite lib en préfixe sur Windows

        # Langage et standard
        std_flag = ""
        if proj.language == Api.Language.CPP:
            std_flag = f"set_property(TARGET {name} PROPERTY CXX_STANDARD {proj.cppdialect.replace('C++', '')})\n"
        elif proj.language == Api.Language.C:
            std_flag = f"set_property(TARGET {name} PROPERTY C_STANDARD {proj.cdialect.replace('C', '')})\n"
        f.write(std_flag)

        # Répertoires de sortie (selon contexte de génération)
        target_dir = chemin(builder.GetTargetDir(proj))
        f.write(f"set_target_properties({name} PROPERTIES\n")
        if proj.kind in (Api.ProjectKind.CONSOLE_APP, Api.ProjectKind.WINDOWED_APP, Api.ProjectKind.TEST_SUITE):
            f.write(f"  RUNTIME_OUTPUT_DIRECTORY \"{target_dir}\"\n")
        elif proj.kind == Api.ProjectKind.SHARED_LIB:
            f.write(f"  LIBRARY_OUTPUT_DIRECTORY \"{target_dir}\"\n")
            f.write(f"  RUNTIME_OUTPUT_DIRECTORY \"{target_dir}\"\n")
        elif proj.kind == Api.ProjectKind.STATIC_LIB:
            f.write(f"  ARCHIVE_OUTPUT_DIRECTORY \"{target_dir}\"\n")
        f.write(")\n")

        f.write("\n")

    @staticmethod
    def _CollectProjectFilesForGen(proj, builder: Builder) -> Tuple[List[str], List[str]]:
        """Collect source/header files for generators using project globs and excludes."""
        import glob as _glob

        src_files = builder._CollectSourceFiles(proj)

        # Collect headers from project file patterns while honoring exclusions.
        hdr_exts = set(Builder.GetHeaderFileExtensions())
        header_files: List[str] = []
        workspace_base = Path(builder.workspace.location).resolve() if builder.workspace and builder.workspace.location else Path.cwd()
        if proj.location:
            proj_base = Path(proj.location)
            if not proj_base.is_absolute():
                proj_base = (workspace_base / proj_base).resolve()
            else:
                proj_base = proj_base.resolve()
        else:
            proj_base = workspace_base

        excluded = set()
        for pattern in proj.excludeFiles:
            expanded_pattern = pattern
            if getattr(builder, "_expander", None):
                builder._expander.SetProject(proj)
                expanded_pattern = builder._expander.Expand(pattern, recursive=True)
            p = Path(expanded_pattern)
            if p.is_absolute():
                if any(ch in expanded_pattern for ch in ("*", "?", "[")):
                    excluded.update([m for m in _glob.glob(expanded_pattern, recursive=True) if Path(m).is_file()])
                elif p.exists():
                    excluded.add(str(p.resolve()))
            else:
                excluded.update(FileSystem.ListFiles(proj_base, pattern=expanded_pattern, recursive=True, fullPath=True))

        for pattern in proj.files:
            expanded_pattern = pattern
            if getattr(builder, "_expander", None):
                builder._expander.SetProject(proj)
                expanded_pattern = builder._expander.Expand(pattern, recursive=True)

            p = Path(expanded_pattern)
            if p.is_absolute():
                if any(ch in expanded_pattern for ch in ("*", "?", "[")):
                    matched = [m for m in _glob.glob(expanded_pattern, recursive=True) if Path(m).is_file()]
                elif p.exists():
                    matched = [str(p.resolve())]
                else:
                    matched = []
            else:
                matched = FileSystem.ListFiles(proj_base, pattern=expanded_pattern, recursive=True, fullPath=True)

            for f in matched:
                p = Path(f).resolve()
                if str(p) in excluded:
                    continue
                if p.suffix.lower() in hdr_exts:
                    header_files.append(str(p))

        src_files = sorted(set(src_files))
        header_files = sorted(set(header_files))
        return src_files, header_files

    # -----------------------------------------------------------------------
    # Générateur Makefile (simple)
    # -----------------------------------------------------------------------

    @staticmethod
    def _GenerateMakefile(workspace, output_dir: Path, builder: Builder, entry_file: Path):
        """Génère un Makefile robuste pour le workspace."""
        make_path = output_dir / "Makefile"
        projects = [name for name in workspace.projects.keys() if not name.startswith("__")]
        default_platform = builder.platform or builder.targetOs.value
        default_target = workspace.startProject or (projects[0] if projects else "")
        with open(make_path, 'w', encoding='utf-8') as f:
            f.write("# Makefile generated by Jenga\n\n")
            f.write(f"WORKSPACE = {workspace.name}\n")
            f.write(f"JENGA ?= jenga\n")
            # Guillemets et « / » : le shell de make mangeait les antislashs
            # d'un chemin Windows (« C:\Users » devenait « C:Users »).
            f.write(f"JENGA_FILE ?= \"{GenCommand._Posix(Path(entry_file).resolve())}\"\n")
            f.write("CONFIG ?= Debug\n")
            f.write(f"PLATFORM ?= {default_platform}\n")
            if default_target:
                f.write(f"TARGET ?= {default_target}\n")
            f.write("\n")

            if projects:
                f.write(f"PROJECTS := {' '.join(projects)}\n\n")
                f.write("all: $(PROJECTS:%=build-%)\n\n")
                f.write("build-%:\n")
                f.write("\t@$(JENGA) build --action build --config $(CONFIG) --platform $(PLATFORM) --target $* --jenga-file $(JENGA_FILE)\n\n")
            else:
                f.write("all:\n")
                f.write("\t@$(JENGA) build --action build --config $(CONFIG) --platform $(PLATFORM) --jenga-file $(JENGA_FILE)\n\n")

            f.write("build:\n")
            f.write("\t@$(JENGA) build --action build --config $(CONFIG) --platform $(PLATFORM) --jenga-file $(JENGA_FILE)\n\n")

            f.write("clean:\n")
            f.write("\t@$(JENGA) clean --config $(CONFIG) --jenga-file $(JENGA_FILE)\n\n")

            f.write("rebuild:\n")
            f.write("\t@$(JENGA) rebuild --config $(CONFIG) --platform $(PLATFORM) --jenga-file $(JENGA_FILE)\n\n")

            if default_target:
                f.write("run:\n")
                f.write("\t@$(JENGA) run $(TARGET) --config $(CONFIG) --platform $(PLATFORM) --jenga-file $(JENGA_FILE)\n\n")

            f.write("test:\n")
            f.write("\t@$(JENGA) test --config $(CONFIG) --platform $(PLATFORM) --jenga-file $(JENGA_FILE)\n\n")

            phony_targets = ["all", "build", "clean", "rebuild", "test"]
            if default_target:
                phony_targets.append("run")
            if projects:
                phony_targets.append("build-%")
            f.write(f".PHONY: {' '.join(phony_targets)}\n")

        Colored.PrintSuccess(f"Makefile generated: {make_path}")

    @staticmethod
    def _GenerateMk(workspace, output_dir: Path, builder: Builder, entry_file: Path):
        """Generate a reusable .mk include file for the workspace."""
        mk_path = output_dir / f"{workspace.name}.mk"
        projects = [name for name in workspace.projects.keys() if not name.startswith("__")]
        default_platform = builder.platform or builder.targetOs.value
        default_target = workspace.startProject or (projects[0] if projects else "")

        with open(mk_path, "w", encoding="utf-8") as f:
            f.write("# workspace.mk generated by Jenga\n")
            f.write(f"WORKSPACE := {workspace.name}\n")
            f.write("JENGA ?= jenga\n")
            # Guillemets et « / » : le shell de make mangeait les antislashs
            # d'un chemin Windows (« C:\Users » devenait « C:Users »).
            f.write(f"JENGA_FILE ?= \"{GenCommand._Posix(Path(entry_file).resolve())}\"\n")
            f.write("CONFIG ?= Debug\n")
            f.write(f"PLATFORM ?= {default_platform}\n")
            if default_target:
                f.write(f"TARGET ?= {default_target}\n")
            f.write("\n")
            if projects:
                f.write(f"PROJECTS := {' '.join(projects)}\n\n")
            else:
                f.write("PROJECTS :=\n\n")

            f.write("define JENGA_BUILD\n")
            f.write("\t@$(JENGA) build --action build --config $(CONFIG) --platform $(PLATFORM) --jenga-file $(JENGA_FILE) $(1)\n")
            f.write("endef\n\n")

            f.write("build:\n")
            f.write("\t$(call JENGA_BUILD,)\n\n")

            f.write("build-%:\n")
            f.write("\t$(call JENGA_BUILD,--target $*)\n\n")

            f.write("clean:\n")
            f.write("\t@$(JENGA) clean --config $(CONFIG) --jenga-file $(JENGA_FILE)\n\n")

            f.write("rebuild:\n")
            f.write("\t@$(JENGA) rebuild --config $(CONFIG) --platform $(PLATFORM) --jenga-file $(JENGA_FILE)\n\n")

            f.write("test:\n")
            f.write("\t@$(JENGA) test --config $(CONFIG) --platform $(PLATFORM) --jenga-file $(JENGA_FILE)\n\n")

            if default_target:
                f.write("run:\n")
                f.write("\t@$(JENGA) run $(TARGET) --config $(CONFIG) --platform $(PLATFORM) --jenga-file $(JENGA_FILE)\n\n")

            f.write(".PHONY: build build-% clean rebuild test")
            if default_target:
                f.write(" run")
            f.write("\n")

        Colored.PrintSuccess(f"MK include generated: {mk_path}")

    @staticmethod
    def _MapArchToAndroidAbi(arch: Api.TargetArch) -> Optional[str]:
        mapping = {
            Api.TargetArch.ARM: "armeabi-v7a",
            Api.TargetArch.ARM64: "arm64-v8a",
            Api.TargetArch.X86: "x86",
            Api.TargetArch.X86_64: "x86_64",
        }
        return mapping.get(arch)

    @staticmethod
    def _GenerateAndroidMk(workspace, output_dir: Path, builder: Builder):
        """
        Generate Android.mk + Application.mk for ndk-build workflows.
        This is additive and does not replace the default native Jenga Android flow.
        """
        android_mk_path = output_dir / "Android.mk"
        application_mk_path = output_dir / "Application.mk"

        projects = [
            proj for proj in workspace.projects.values()
            if not proj.name.startswith("__")
        ]
        if not projects:
            Colored.PrintWarning("No project available for Android.mk generation.")
            return

        module_names: Dict[str, str] = {}
        for proj in projects:
            module_names[proj.name] = (proj.targetName or proj.name).replace(" ", "_")

        lines: List[str] = []
        besoin_glue = False
        lines.append("# Android.mk generated by Jenga")
        lines.append("LOCAL_PATH := $(call my-dir)")
        lines.append("")

        for proj in projects:
            src_files, _ = GenCommand._CollectProjectFilesForGen(proj, builder)
            if not src_files:
                continue

            module_name = module_names[proj.name]
            # Sources relatives a LOCAL_PATH (ndk-build les prefixe lui-meme),
            # includes via $(LOCAL_PATH) ; « / » dans les deux cas.
            project_srcs = [GenCommand._RelTo(src, output_dir) for src in src_files]
            include_dirs = [GenCommand._RelTo(builder.ResolveProjectPath(proj, inc), output_dir, "$(LOCAL_PATH)")
                            for inc in proj.includeDirs]
            defines = [f"-D{d}" for d in proj.defines if d]
            cflags = [f for f in proj.cflags if f]
            cxxflags = [f for f in proj.cxxflags if f]
            ldlibs: List[str] = []
            local_static: List[str] = []
            local_shared: List[str] = []

            for dep_name in proj.dependsOn:
                dep_proj = workspace.projects.get(dep_name)
                if not dep_proj or dep_name.startswith("__"):
                    continue
                dep_module = module_names.get(dep_name)
                if not dep_module:
                    continue
                if dep_proj.kind == Api.ProjectKind.STATIC_LIB:
                    local_static.append(dep_module)
                else:
                    local_shared.append(dep_module)

            for link in proj.links:
                if link in module_names:
                    continue
                link_token = str(link).strip()
                if not link_token:
                    continue
                if link_token.startswith("-l"):
                    ldlibs.append(link_token)
                elif "/" in link_token or "\\" in link_token:
                    # path-like libs should be handled by LOCAL_LDFLAGS
                    ldlibs.append(link_token)
                else:
                    ldlibs.append(f"-l{link_token}")

            # NativeActivity : le build natif de Jenga compile lui-meme
            # android_native_app_glue et lie -llog -landroid (Builders/Android.py).
            # Sans le meme contrat ici, ndk-build echouait au lien
            # (« undefined symbol: __android_log_print »), et sans la colle une
            # app qui liait quand meme mourait au lancement.
            native_activity = (proj.kind == Api.ProjectKind.WINDOWED_APP
                               and bool(getattr(proj, "androidNativeActivity", False)))
            if native_activity:
                besoin_glue = True
                for lib in ("-llog", "-landroid"):
                    if lib not in ldlibs:
                        ldlibs.append(lib)
                local_static.append("android_native_app_glue")

            lines.append("include $(CLEAR_VARS)")
            lines.append(f"LOCAL_MODULE := {module_name}")
            lines.append("LOCAL_SRC_FILES := \\")
            for idx, src in enumerate(project_srcs):
                suffix = " \\" if idx < len(project_srcs) - 1 else ""
                lines.append(f"\t{src}{suffix}")

            if include_dirs:
                lines.append("LOCAL_C_INCLUDES := \\")
                for idx, inc in enumerate(include_dirs):
                    suffix = " \\" if idx < len(include_dirs) - 1 else ""
                    lines.append(f"\t{inc}{suffix}")

            # Standard C++ PAR MODULE, lu dans cppdialect() : un -std=c++17 global
            # dans Application.mk ecrasait le C++20 d'un projet qui le declarait.
            if proj.language in (Api.Language.CPP, Api.Language.OBJCPP) and getattr(proj, "cppdialect", ""):
                std = str(proj.cppdialect).lower().replace("gnu++", "c++")
                if std == "c++latest":
                    std = "c++2b"
                cxxflags = [f"-std={std}"] + cxxflags
            if defines or cflags:
                lines.append(f"LOCAL_CFLAGS += {' '.join(defines + cflags)}")
            if defines or cxxflags:
                lines.append(f"LOCAL_CPPFLAGS += {' '.join(defines + cxxflags)}")
            if ldlibs:
                lines.append(f"LOCAL_LDLIBS += {' '.join(ldlibs)}")
            if local_static:
                lines.append(f"LOCAL_STATIC_LIBRARIES += {' '.join(local_static)}")
            if local_shared:
                lines.append(f"LOCAL_SHARED_LIBRARIES += {' '.join(local_shared)}")
            if native_activity:
                # Sans -u, l'editeur de liens jette ANativeActivity_onCreate
                # (rien ne l'appelle dans le .so) et l'activite ne demarre pas.
                lines.append("LOCAL_LDFLAGS += -u ANativeActivity_onCreate")

            if proj.kind == Api.ProjectKind.STATIC_LIB:
                lines.append("include $(BUILD_STATIC_LIBRARY)")
            else:
                lines.append("include $(BUILD_SHARED_LIBRARY)")
            lines.append("")

        if besoin_glue:
            lines.append("$(call import-module,android/native_app_glue)")

        android_mk_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

        # Application.mk
        app_abis: List[str] = []
        for arch in (workspace.targetArchs or []):
            abi = GenCommand._MapArchToAndroidAbi(arch)
            if abi and abi not in app_abis:
                app_abis.append(abi)
        if not app_abis:
            fallback = GenCommand._MapArchToAndroidAbi(builder.targetArch)
            if fallback:
                app_abis.append(fallback)
        if not app_abis:
            app_abis = ["arm64-v8a"]

        # APP_PLATFORM = le PLUS ELEVE des androidminsdk() declares : un module
        # qui exige l'API 24 ne se compile pas contre l'API 21. (Avant 2.8.4 :
        # min(21, ...) -- tout minsdk superieur a 21 etait ignore.)
        min_sdk = 21
        declares: List[int] = []
        for proj in projects:
            if getattr(proj, "androidMinSdk", None):
                try:
                    declares.append(int(proj.androidMinSdk))
                except Exception:
                    pass
        if declares:
            min_sdk = max(declares)

        # APP_STL : androidstl() s'il est declare (c++_static l'emporte s'il est
        # demande quelque part : un seul runtime par application), sinon c++_shared.
        stls = {str(getattr(p, "androidStl", "") or "") for p in projects}
        app_stl = "c++_static" if "c++_static" in stls else "c++_shared"

        app_lines = [
            "# Application.mk generated by Jenga",
            f"APP_ABI := {' '.join(app_abis)}",
            f"APP_PLATFORM := android-{min_sdk}",
            f"APP_STL := {app_stl}",
        ]
        application_mk_path.write_text("\n".join(app_lines) + "\n", encoding="utf-8")

        Colored.PrintSuccess(f"Android.mk generated: {android_mk_path}")
        Colored.PrintSuccess(f"Application.mk generated: {application_mk_path}")

    # -----------------------------------------------------------------------
    # Générateur Visual Studio 2022 (amélioré)
    # -----------------------------------------------------------------------

    @staticmethod
    def _GenerateVS2022(workspace, output_dir: Path, builder: Builder):
        """Génère une solution Visual Studio 2022 avec tous les projets."""
        sln_path = output_dir / f"{workspace.name}.sln"
        vs_version = "17.0"

        # Générer un GUID unique pour la solution
        sln_guid = "{" + str(uuid.uuid4()).upper() + "}"

        with open(sln_path, 'w') as f:
            f.write("\n")
            f.write("Microsoft Visual Studio Solution File, Format Version 12.00\n")
            f.write(f"# Visual Studio Version {vs_version}\n")
            f.write("VisualStudioVersion = 17.0.31903.59\n")
            f.write("MinimumVisualStudioVersion = 10.0.40219.1\n")

            # Projets (générer d'abord tous les GUIDs pour résoudre dépendances avant écriture)
            project_guids = {
                proj_name: "{" + str(uuid.uuid4()).upper() + "}"
                for proj_name in workspace.projects.keys()
                if not proj_name.startswith('__')
            }
            for proj_name, proj in workspace.projects.items():
                if proj_name.startswith('__'):
                    continue
                proj_guid = project_guids[proj_name]
                proj_path = f"{proj_name}.vcxproj"
                f.write(f'Project("{{8BC9CEB8-8B4A-11D0-8D11-00A0C91BC942}}") = "{proj_name}", "{proj_path}", "{proj_guid}"\n')
                project_deps = [dep for dep in proj.dependsOn if dep in workspace.projects and not dep.startswith("__")]
                if project_deps:
                    f.write("\tProjectSection(ProjectDependencies) = postProject\n")
                    for dep in project_deps:
                        dep_guid = project_guids.get(dep)
                        if dep_guid:
                            f.write(f"\t\t{dep_guid} = {dep_guid}\n")
                    f.write("\tEndProjectSection\n")
                f.write("EndProject\n")

            # Global
            f.write("Global\n")
            f.write("\tGlobalSection(SolutionConfigurationPlatforms) = preSolution\n")
            for config in workspace.configurations:
                f.write(f"\t\t{config}|x64 = {config}|x64\n")
                f.write(f"\t\t{config}|Win32 = {config}|Win32\n")
                f.write(f"\t\t{config}|ARM64 = {config}|ARM64\n")
            f.write("\tEndGlobalSection\n")

            f.write("\tGlobalSection(ProjectConfigurationPlatforms) = postSolution\n")
            for proj_name, proj_guid in project_guids.items():
                for config in workspace.configurations:
                    for plat in ["x64", "Win32", "ARM64"]:
                        f.write(f"\t\t{proj_guid}.{config}|{plat}.ActiveCfg = {config}|{plat}\n")
                        f.write(f"\t\t{proj_guid}.{config}|{plat}.Build.0 = {config}|{plat}\n")
            f.write("\tEndGlobalSection\n")
            f.write("EndGlobal\n")

        # Générer les .vcxproj
        for proj_name, proj in workspace.projects.items():
            if proj_name.startswith('__'):
                continue
            GenCommand._GenerateVCXProj(proj, output_dir / f"{proj_name}.vcxproj", workspace, builder,
                                        project_guids[proj_name])

        Colored.PrintSuccess(f"Visual Studio 2022 solution generated: {sln_path}")

    @staticmethod
    def _GenerateVCXProj(project, proj_path: Path, workspace, builder: Builder, project_guid: str):
        """Génère un fichier .vcxproj avec dépendances et chemins complets.

        project_guid : celui que la solution declare pour ce projet. Avant 2.8.4,
        le .vcxproj en tirait un second au hasard -- la solution et le projet ne
        se designaient pas par le meme identifiant.
        """
        from xml.etree.ElementTree import Element, SubElement, tostring
        import xml.dom.minidom

        root = Element("Project", DefaultTargets="Build", xmlns="http://schemas.microsoft.com/developer/msbuild/2003")

        # Configurations
        ig = SubElement(root, "ItemGroup", Label="ProjectConfigurations")
        for config in workspace.configurations:
            for plat in ["x64", "Win32", "ARM64"]:
                pc = SubElement(ig, "ProjectConfiguration", Include=f"{config}|{plat}")
                SubElement(pc, "Configuration").text = config
                SubElement(pc, "Platform").text = plat

        # Globals
        pg = SubElement(root, "PropertyGroup", Label="Globals")
        SubElement(pg, "ProjectGuid").text = project_guid
        SubElement(pg, "Keyword").text = "Win32Proj"
        SubElement(pg, "RootNamespace").text = project.name
        SubElement(pg, "WindowsTargetPlatformVersion").text = "10.0"

        # Default properties
        SubElement(root, "Import", Project="$(VCTargetsPath)\\Microsoft.Cpp.Default.props")

        # Configuration groups
        for config in workspace.configurations:
            for plat in ["x64", "Win32", "ARM64"]:
                pg = SubElement(root, "PropertyGroup", Condition=f"'$(Configuration)|$(Platform)'=='{config}|{plat}'", Label="Configuration")
                SubElement(pg, "ConfigurationType").text = GenCommand._GetVSConfigurationType(project.kind)
                SubElement(pg, "UseDebugLibraries").text = "true" if config == "Debug" else "false"
                # $(DefaultPlatformToolset) : l'ensemble d'outils de la version
                # de Visual Studio qui ouvre le projet (defini par
                # Microsoft.Cpp.Default.props, importe juste au-dessus). « v143 »
                # ecrit en dur rendait le projet inconstructible sous VS 2026
                # (v145) : MSB8020.
                SubElement(pg, "PlatformToolset").text = "$(DefaultPlatformToolset)"
                if project.kind == Api.ProjectKind.SHARED_LIB:
                    SubElement(pg, "LinkIncremental").text = "false"
                target_dir = str(builder.GetTargetDir(project))
                obj_dir = str(builder.GetObjectDir(project))
                SubElement(pg, "OutDir").text = target_dir + "\\"
                SubElement(pg, "IntDir").text = str(Path(obj_dir) / config / plat) + "\\"

        SubElement(root, "Import", Project="$(VCTargetsPath)\\Microsoft.Cpp.props")

        # Property sheet placeholders (MSBuild convention)
        import_group = SubElement(root, "ImportGroup", Label="ExtensionSettings")
        SubElement(root, "ImportGroup", Label="Shared")
        for config in workspace.configurations:
            for plat in ["x64", "Win32", "ARM64"]:
                ig = SubElement(root, "ImportGroup", Label="PropertySheets", Condition=f"'$(Configuration)|$(Platform)'=='{config}|{plat}'")
                SubElement(ig, "Import", Project="$(UserRootDir)\\Microsoft.Cpp.$(Platform).user.props",
                           Condition="exists('$(UserRootDir)\\Microsoft.Cpp.$(Platform).user.props')",
                           Label="LocalAppDataPlatform")
        SubElement(root, "PropertyGroup", Label="UserMacros")

        # Compiler/Linker settings per config/platform
        for config in workspace.configurations:
            for plat in ["x64", "Win32", "ARM64"]:
                ig_def = SubElement(root, "ItemDefinitionGroup", Condition=f"'$(Configuration)|$(Platform)'=='{config}|{plat}'")
                cl = SubElement(ig_def, "ClCompile")
                link = SubElement(ig_def, "Link")

                # Includes
                include_dirs = [builder.ResolveProjectPath(project, inc) for inc in project.includeDirs]
                include_dirs.append("%(AdditionalIncludeDirectories)")
                SubElement(cl, "AdditionalIncludeDirectories").text = ";".join(include_dirs)

                # Defines
                defs = list(project.defines)
                if config.lower() == "debug":
                    defs.extend(["_DEBUG", "DEBUG"])
                else:
                    defs.extend(["NDEBUG", "RELEASE"])
                defs.append("%(PreprocessorDefinitions)")
                SubElement(cl, "PreprocessorDefinitions").text = ";".join(dict.fromkeys(defs))

                # Language standard
                if project.language == Api.Language.CPP:
                    SubElement(cl, "LanguageStandard").text = "stdcpp" + project.cppdialect.replace("C++", "")
                elif project.language == Api.Language.C:
                    SubElement(cl, "LanguageStandard_C").text = "stdc" + project.cdialect.replace("C", "")

                # Warnings
                warn = project.warnings.value if hasattr(project.warnings, "value") else str(project.warnings)
                warn_map = {
                    "None": "TurnOffAllWarnings",
                    "Default": "Level3",
                    "All": "Level4",
                    "Extra": "Level4",
                    "Pedantic": "Level4",
                    "Everything": "EnableAllWarnings",
                    "Error": "Level4",
                }
                SubElement(cl, "WarningLevel").text = warn_map.get(warn, "Level3")
                if warn == "Error":
                    SubElement(cl, "TreatWarningAsError").text = "true"

                # Debug symbols
                if project.symbols or config.lower() == "debug":
                    SubElement(cl, "DebugInformationFormat").text = "ProgramDatabase"

                # Optimization
                opt = project.optimize.value if hasattr(project.optimize, 'value') else project.optimize
                opt_map = {
                    "Off": "Disabled",
                    "Size": "MinSpace",
                    "Speed": "MaxSpeed",
                    "Full": "Full",
                }
                SubElement(cl, "Optimization").text = opt_map.get(opt, "Disabled" if config.lower() == "debug" else "MaxSpeed")

                # Custom compile flags
                extra_compile = list(project.cflags) + list(project.cxxflags)
                if extra_compile:
                    SubElement(cl, "AdditionalOptions").text = " ".join(extra_compile) + " %(AdditionalOptions)"

                # Link dependencies
                libs: List[str] = []
                for lib in project.links:
                    if lib in workspace.projects:
                        deps_proj = workspace.projects[lib]
                        lib_name = deps_proj.targetName or deps_proj.name
                        if not lib_name.lower().endswith(".lib"):
                            lib_name += ".lib"
                        libs.append(lib_name)
                    else:
                        lib_text = lib
                        if not (lib_text.lower().endswith(".lib") or "\\" in lib_text or "/" in lib_text):
                            lib_text += ".lib"
                        libs.append(lib_text)
                libs.append("%(AdditionalDependencies)")
                SubElement(link, "AdditionalDependencies").text = ";".join(dict.fromkeys(libs))

                # Link directories
                lib_dirs = [builder.ResolveProjectPath(project, d) for d in project.libDirs]
                for dep in project.dependsOn:
                    if dep in workspace.projects and not dep.startswith("__"):
                        lib_dirs.append(str(builder.GetTargetDir(workspace.projects[dep])))
                lib_dirs.append("%(AdditionalLibraryDirectories)")
                SubElement(link, "AdditionalLibraryDirectories").text = ";".join(dict.fromkeys(lib_dirs))

                # Sous-systeme : une application fenetree (WinMain) doit etre
                # liee en Windows, sinon l'editeur de liens cherche main().
                if project.kind == Api.ProjectKind.WINDOWED_APP:
                    SubElement(link, "SubSystem").text = "Windows"
                elif project.kind in (Api.ProjectKind.CONSOLE_APP, Api.ProjectKind.TEST_SUITE):
                    SubElement(link, "SubSystem").text = "Console"

                # Custom link options
                if project.ldflags:
                    SubElement(link, "AdditionalOptions").text = " ".join(project.ldflags) + " %(AdditionalOptions)"

        # Fichiers sources / headers
        src_files, hdr_files = GenCommand._CollectProjectFilesForGen(project, builder)
        if src_files:
            ig_src = SubElement(root, "ItemGroup")
            for src in src_files:
                SubElement(ig_src, "ClCompile", Include=src)
        if hdr_files:
            ig_hdr = SubElement(root, "ItemGroup")
            for hdr in hdr_files:
                SubElement(ig_hdr, "ClInclude", Include=hdr)

        # Project references for local dependencies
        dep_projects = [dep for dep in project.dependsOn if dep in workspace.projects and not dep.startswith("__")]
        if dep_projects:
            ig_refs = SubElement(root, "ItemGroup")
            for dep in dep_projects:
                SubElement(ig_refs, "ProjectReference", Include=f"{dep}.vcxproj")

        SubElement(root, "Import", Project="$(VCTargetsPath)\\Microsoft.Cpp.targets")
        SubElement(root, "ImportGroup", Label="ExtensionTargets")

        # Pretty print
        xml_str = tostring(root, encoding='utf-8')
        dom = xml.dom.minidom.parseString(xml_str)
        pretty = dom.toprettyxml(indent="  ")
        proj_path.write_text(pretty, encoding='utf-8')

    @staticmethod
    def _GetVSConfigurationType(kind) -> str:
        """Convertit ProjectKind en type Visual Studio."""
        from ..Core.Api import ProjectKind
        if kind in (ProjectKind.CONSOLE_APP, ProjectKind.WINDOWED_APP, ProjectKind.TEST_SUITE):
            return "Application"
        elif kind == ProjectKind.STATIC_LIB:
            return "StaticLibrary"
        elif kind == ProjectKind.SHARED_LIB:
            return "DynamicLibrary"
        else:
            return "Application"

    @staticmethod
    def _GenerateXcode(workspace, output_dir: Path, builder: Optional[Builder] = None):
        """Generate a real .xcodeproj with project.pbxproj."""
        if builder is None:
            Colored.PrintError("Xcode generation requires a generation builder context.")
            return

        import plistlib

        xcodeproj_dir = output_dir / f"{workspace.name}.xcodeproj"
        FileSystem.MakeDirectory(xcodeproj_dir)

        pbxproj, target_meta = GenCommand._BuildXcodePbxProj(workspace, builder)
        pbxproj_path = xcodeproj_dir / "project.pbxproj"
        with open(pbxproj_path, "wb") as f:
            plistlib.dump(pbxproj, f, fmt=plistlib.FMT_XML, sort_keys=False)

        # Shared scheme for start project (or first non-internal target)
        start_target = workspace.startProject
        if not start_target or start_target not in workspace.projects or start_target.startswith("__"):
            for proj_name in workspace.projects.keys():
                if not proj_name.startswith("__"):
                    start_target = proj_name
                    break
        if start_target and start_target in target_meta:
            GenCommand._WriteXcodeScheme(xcodeproj_dir, workspace, start_target, target_meta[start_target])
        GenCommand._WriteXcodeWorkspaceSettings(xcodeproj_dir)

        Colored.PrintSuccess(f"Xcode project generated: {xcodeproj_dir}")

    @staticmethod
    def _XcodeNewId(state: Dict[str, int]) -> str:
        state["counter"] += 1
        return f"{state['counter']:024X}"

    @staticmethod
    def _XcodeFileType(path: Path) -> str:
        ext = path.suffix.lower()
        mapping = {
            ".c": "sourcecode.c.c",
            ".m": "sourcecode.c.objc",
            ".mm": "sourcecode.cpp.objcpp",
            ".cc": "sourcecode.cpp.cpp",
            ".cpp": "sourcecode.cpp.cpp",
            ".cxx": "sourcecode.cpp.cpp",
            ".c++": "sourcecode.cpp.cpp",
            ".cppm": "sourcecode.cpp.cpp",
            ".ixx": "sourcecode.cpp.cpp",
            ".mpp": "sourcecode.cpp.cpp",
            ".h": "sourcecode.c.h",
            ".hpp": "sourcecode.c.h",
            ".hxx": "sourcecode.c.h",
            ".hh": "sourcecode.c.h",
            ".inl": "sourcecode.c.h",
            ".s": "sourcecode.asm",
            ".asm": "sourcecode.asm",
        }
        return mapping.get(ext, "text")

    @staticmethod
    def _XcodeDialectCpp(dialect: str) -> str:
        value = (dialect or "C++17").strip().lower().replace(" ", "")
        if value.startswith("c++"):
            value = "c++" + value[3:]
        return value

    @staticmethod
    def _XcodeDialectC(dialect: str) -> str:
        value = (dialect or "C11").strip().lower().replace(" ", "")
        if value.startswith("c"):
            value = "gnu" + value
        return value

    @staticmethod
    def _XcodeOptimization(project, config_name: str) -> str:
        config_lower = (config_name or "").strip().lower()
        if config_lower == "debug":
            return "0"
        opt = project.optimize.value if hasattr(project.optimize, "value") else str(project.optimize)
        mapping = {
            "Off": "0",
            "Size": "s",
            "Speed": "3",
            "Full": "fast",
        }
        return mapping.get(str(opt), "3")

    @staticmethod
    def _XcodeProductSpec(project) -> Dict[str, str]:
        target_name = (project.targetName or project.name).replace(" ", "_")
        if project.kind == Api.ProjectKind.STATIC_LIB:
            return {
                "product_type": "com.apple.product-type.library.static",
                "product_file_type": "archive.ar",
                "product_file_name": f"lib{target_name}.a",
                "executable_extension": "a",
                "executable_prefix": "lib",
                "mach_o_type": "staticlib",
            }
        if project.kind == Api.ProjectKind.SHARED_LIB:
            return {
                "product_type": "com.apple.product-type.library.dynamic",
                "product_file_type": "compiled.mach-o.dylib",
                "product_file_name": f"lib{target_name}.dylib",
                "executable_extension": "dylib",
                "executable_prefix": "lib",
                "mach_o_type": "mh_dylib",
            }
        if project.kind == Api.ProjectKind.WINDOWED_APP:
            return {
                "product_type": "com.apple.product-type.application",
                "product_file_type": "wrapper.application",
                "product_file_name": f"{target_name}.app",
                "executable_extension": "",
                "executable_prefix": "",
                "mach_o_type": "mh_execute",
            }
        # Console app + test suite default to command line tool.
        return {
            "product_type": "com.apple.product-type.tool",
            "product_file_type": "compiled.mach-o.executable",
            "product_file_name": target_name,
            "executable_extension": "",
            "executable_prefix": "",
            "mach_o_type": "mh_execute",
        }

    @staticmethod
    def _BuildXcodeTargetBuildSettings(project, workspace, builder: Builder, config_name: str) -> Dict[str, Any]:
        include_dirs = [str(Path(builder.ResolveProjectPath(project, inc)).resolve()) for inc in project.includeDirs]
        lib_dirs = [str(Path(builder.ResolveProjectPath(project, d)).resolve()) for d in project.libDirs]
        for dep_name in project.dependsOn:
            dep_proj = workspace.projects.get(dep_name)
            if dep_proj and not dep_name.startswith("__"):
                dep_dir = str(builder.GetTargetDir(dep_proj))
                if dep_dir not in lib_dirs:
                    lib_dirs.append(dep_dir)

        defines = [str(d) for d in project.defines if str(d).strip()]
        if config_name.lower() == "debug":
            if "DEBUG=1" not in defines:
                defines.append("DEBUG=1")
        else:
            if "NDEBUG=1" not in defines:
                defines.append("NDEBUG=1")
        defines.append("$(inherited)")

        other_ldflags: List[str] = []
        for link in project.links:
            token = str(link).strip()
            if not token or token in workspace.projects:
                continue
            if token.startswith("-"):
                other_ldflags.append(token)
            elif "/" in token or "\\" in token:
                other_ldflags.append(token)
            else:
                other_ldflags.append(f"-l{token}")
        other_ldflags.extend([str(flag) for flag in project.ldflags if str(flag).strip()])
        other_ldflags.append("$(inherited)")

        settings: Dict[str, Any] = {
            "ALWAYS_SEARCH_USER_PATHS": "NO",
            "CLANG_ENABLE_MODULES": "YES",
            "CLANG_CXX_LANGUAGE_STANDARD": GenCommand._XcodeDialectCpp(project.cppdialect),
            "CLANG_CXX_LIBRARY": "libc++",
            "GCC_C_LANGUAGE_STANDARD": GenCommand._XcodeDialectC(project.cdialect),
            "HEADER_SEARCH_PATHS": include_dirs + ["$(inherited)"],
            "LIBRARY_SEARCH_PATHS": lib_dirs + ["$(inherited)"],
            "GCC_PREPROCESSOR_DEFINITIONS": defines,
            "OTHER_CFLAGS": [str(flag) for flag in project.cflags if str(flag).strip()] + ["$(inherited)"],
            "OTHER_CPLUSPLUSFLAGS": [str(flag) for flag in project.cxxflags if str(flag).strip()] + ["$(inherited)"],
            "OTHER_LDFLAGS": other_ldflags,
            "CONFIGURATION_BUILD_DIR": str(builder.GetTargetDir(project)),
            "DEBUG_INFORMATION_FORMAT": "dwarf" if config_name.lower() == "debug" else "dwarf-with-dsym",
            "GCC_OPTIMIZATION_LEVEL": GenCommand._XcodeOptimization(project, config_name),
            "ENABLE_TESTABILITY": "YES" if config_name.lower() == "debug" else "NO",
            "SDKROOT": "macosx",
            "MACOSX_DEPLOYMENT_TARGET": "11.0",
        }

        product_spec = GenCommand._XcodeProductSpec(project)
        target_name = (project.targetName or project.name).replace(" ", "_")
        settings["PRODUCT_NAME"] = target_name
        settings["MACH_O_TYPE"] = product_spec["mach_o_type"]
        if product_spec["executable_prefix"]:
            settings["EXECUTABLE_PREFIX"] = product_spec["executable_prefix"]
        if product_spec["executable_extension"]:
            settings["EXECUTABLE_EXTENSION"] = product_spec["executable_extension"]
        return settings

    @staticmethod
    def _BuildXcodePbxProj(workspace, builder: Builder) -> Tuple[Dict[str, Any], Dict[str, Dict[str, Any]]]:
        ids = {"counter": 0}
        objects: Dict[str, Dict[str, Any]] = {}
        configs = list(workspace.configurations or ["Debug", "Release"])

        main_group_id = GenCommand._XcodeNewId(ids)
        products_group_id = GenCommand._XcodeNewId(ids)
        project_config_list_id = GenCommand._XcodeNewId(ids)
        project_id = GenCommand._XcodeNewId(ids)

        objects[main_group_id] = {
            "isa": "PBXGroup",
            "children": [],
            "sourceTree": "<group>",
        }
        objects[products_group_id] = {
            "isa": "PBXGroup",
            "children": [],
            "name": "Products",
            "sourceTree": "<group>",
        }

        project_cfg_ids: List[str] = []
        for cfg_name in configs:
            cfg_id = GenCommand._XcodeNewId(ids)
            project_cfg_ids.append(cfg_id)
            objects[cfg_id] = {
                "isa": "XCBuildConfiguration",
                "name": cfg_name,
                "buildSettings": {
                    "ALWAYS_SEARCH_USER_PATHS": "NO",
                },
            }
        objects[project_config_list_id] = {
            "isa": "XCConfigurationList",
            "buildConfigurations": project_cfg_ids,
            "defaultConfigurationIsVisible": "0",
            "defaultConfigurationName": configs[0] if configs else "Debug",
        }

        target_ids: List[str] = []
        target_meta: Dict[str, Dict[str, Any]] = {}

        projects = [
            (proj_name, proj) for proj_name, proj in workspace.projects.items()
            if not proj_name.startswith("__")
        ]

        for proj_name, proj in projects:
            target_name = (proj.targetName or proj.name).replace(" ", "_")
            product_spec = GenCommand._XcodeProductSpec(proj)

            group_id = GenCommand._XcodeNewId(ids)
            product_ref_id = GenCommand._XcodeNewId(ids)
            sources_phase_id = GenCommand._XcodeNewId(ids)
            frameworks_phase_id = GenCommand._XcodeNewId(ids)
            target_config_list_id = GenCommand._XcodeNewId(ids)
            target_id = GenCommand._XcodeNewId(ids)
            resources_phase_id = GenCommand._XcodeNewId(ids) if proj.kind == Api.ProjectKind.WINDOWED_APP else None

            objects[group_id] = {
                "isa": "PBXGroup",
                "children": [],
                "name": proj_name,
                "sourceTree": "<group>",
            }

            src_files, hdr_files = GenCommand._CollectProjectFilesForGen(proj, builder)
            file_refs: List[str] = []
            source_build_files: List[str] = []
            for filepath in src_files + hdr_files:
                path_obj = Path(filepath)
                file_ref_id = GenCommand._XcodeNewId(ids)
                objects[file_ref_id] = {
                    "isa": "PBXFileReference",
                    "lastKnownFileType": GenCommand._XcodeFileType(path_obj),
                    "name": path_obj.name,
                    "path": str(path_obj.resolve()),
                    "sourceTree": "<absolute>",
                }
                file_refs.append(file_ref_id)
                if filepath in src_files:
                    build_file_id = GenCommand._XcodeNewId(ids)
                    objects[build_file_id] = {
                        "isa": "PBXBuildFile",
                        "fileRef": file_ref_id,
                    }
                    source_build_files.append(build_file_id)

            objects[group_id]["children"] = file_refs

            objects[sources_phase_id] = {
                "isa": "PBXSourcesBuildPhase",
                "buildActionMask": "2147483647",
                "files": source_build_files,
                "runOnlyForDeploymentPostprocessing": "0",
            }
            objects[frameworks_phase_id] = {
                "isa": "PBXFrameworksBuildPhase",
                "buildActionMask": "2147483647",
                "files": [],
                "runOnlyForDeploymentPostprocessing": "0",
            }
            if resources_phase_id:
                objects[resources_phase_id] = {
                    "isa": "PBXResourcesBuildPhase",
                    "buildActionMask": "2147483647",
                    "files": [],
                    "runOnlyForDeploymentPostprocessing": "0",
                }

            target_cfg_ids: List[str] = []
            for cfg_name in configs:
                cfg_id = GenCommand._XcodeNewId(ids)
                target_cfg_ids.append(cfg_id)
                objects[cfg_id] = {
                    "isa": "XCBuildConfiguration",
                    "name": cfg_name,
                    "buildSettings": GenCommand._BuildXcodeTargetBuildSettings(proj, workspace, builder, cfg_name),
                }
            objects[target_config_list_id] = {
                "isa": "XCConfigurationList",
                "buildConfigurations": target_cfg_ids,
                "defaultConfigurationIsVisible": "0",
                "defaultConfigurationName": configs[0] if configs else "Debug",
            }

            objects[product_ref_id] = {
                "isa": "PBXFileReference",
                "explicitFileType": product_spec["product_file_type"],
                "includeInIndex": "0",
                "path": product_spec["product_file_name"],
                "sourceTree": "BUILT_PRODUCTS_DIR",
            }

            build_phases = [sources_phase_id, frameworks_phase_id]
            if resources_phase_id:
                build_phases.append(resources_phase_id)
            objects[target_id] = {
                "isa": "PBXNativeTarget",
                "buildConfigurationList": target_config_list_id,
                "buildPhases": build_phases,
                "buildRules": [],
                "dependencies": [],
                "name": proj_name,
                "productName": target_name,
                "productReference": product_ref_id,
                "productType": product_spec["product_type"],
            }

            target_ids.append(target_id)
            objects[main_group_id]["children"].append(group_id)
            objects[products_group_id]["children"].append(product_ref_id)
            target_meta[proj_name] = {
                "target_id": target_id,
                "frameworks_phase_id": frameworks_phase_id,
                "product_ref_id": product_ref_id,
                "buildable_name": product_spec["product_file_name"],
            }

        # Attach product group after all project groups.
        objects[main_group_id]["children"].append(products_group_id)

        # Target dependencies + linked local products
        for proj_name, proj in projects:
            meta = target_meta.get(proj_name)
            if not meta:
                continue
            target_obj = objects.get(meta["target_id"], {})
            frameworks_phase_obj = objects.get(meta["frameworks_phase_id"], {})
            dep_refs: List[str] = []
            framework_build_files: List[str] = list(frameworks_phase_obj.get("files", []))
            linked_locals = set()

            local_links = [dep for dep in proj.dependsOn if dep in target_meta]
            local_links.extend([lib for lib in proj.links if lib in target_meta])

            for dep_name in local_links:
                if dep_name == proj_name or dep_name in linked_locals:
                    continue
                linked_locals.add(dep_name)
                dep_meta = target_meta[dep_name]

                proxy_id = GenCommand._XcodeNewId(ids)
                dep_id = GenCommand._XcodeNewId(ids)
                build_file_id = GenCommand._XcodeNewId(ids)

                objects[proxy_id] = {
                    "isa": "PBXContainerItemProxy",
                    "containerPortal": project_id,
                    "proxyType": "1",
                    "remoteGlobalIDString": dep_meta["target_id"],
                    "remoteInfo": dep_name,
                }
                objects[dep_id] = {
                    "isa": "PBXTargetDependency",
                    "target": dep_meta["target_id"],
                    "targetProxy": proxy_id,
                }
                objects[build_file_id] = {
                    "isa": "PBXBuildFile",
                    "fileRef": dep_meta["product_ref_id"],
                }

                dep_refs.append(dep_id)
                framework_build_files.append(build_file_id)

            if dep_refs:
                target_obj["dependencies"] = dep_refs
            if framework_build_files:
                frameworks_phase_obj["files"] = framework_build_files

        objects[project_id] = {
            "isa": "PBXProject",
            "attributes": {
                "LastUpgradeCheck": "1500",
            },
            "buildConfigurationList": project_config_list_id,
            "compatibilityVersion": "Xcode 14.0",
            "developmentRegion": "en",
            "hasScannedForEncodings": "0",
            "knownRegions": ["en"],
            "mainGroup": main_group_id,
            "productRefGroup": products_group_id,
            "projectDirPath": "",
            "projectRoot": "",
            "targets": target_ids,
        }

        pbx = {
            "archiveVersion": "1",
            "classes": {},
            "objectVersion": "56",
            "objects": objects,
            "rootObject": project_id,
        }
        return pbx, target_meta

    @staticmethod
    def _WriteXcodeWorkspaceSettings(xcodeproj_dir: Path) -> None:
        settings_dir = xcodeproj_dir / "project.xcworkspace" / "xcshareddata"
        FileSystem.MakeDirectory(settings_dir)
        settings_path = settings_dir / "WorkspaceSettings.xcsettings"
        settings_path.write_text(
            """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>BuildSystemType</key>
    <string>Original</string>
</dict>
</plist>
""",
            encoding="utf-8",
        )

    @staticmethod
    def _WriteXcodeScheme(xcodeproj_dir: Path, workspace, project_name: str, target_info: Dict[str, Any]) -> None:
        scheme_dir = xcodeproj_dir / "xcshareddata" / "xcschemes"
        FileSystem.MakeDirectory(scheme_dir)
        proj = workspace.projects.get(project_name)
        if proj is None:
            return
        buildable_name = str(target_info.get("buildable_name") or (proj.targetName or proj.name).replace(" ", "_"))
        blueprint_id = str(target_info.get("target_id", ""))
        if not blueprint_id:
            return

        scheme_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<Scheme LastUpgradeVersion="1500" version="1.7">
  <BuildAction parallelizeBuildables="YES" buildImplicitDependencies="YES">
    <BuildActionEntries>
      <BuildActionEntry buildForTesting="YES" buildForRunning="YES" buildForProfiling="YES" buildForArchiving="YES" buildForAnalyzing="YES">
        <BuildableReference BuildableIdentifier="primary" BlueprintIdentifier="{blueprint_id}" BuildableName="{buildable_name}" BlueprintName="{project_name}" ReferencedContainer="container:{workspace.name}.xcodeproj"/>
      </BuildActionEntry>
    </BuildActionEntries>
  </BuildAction>
  <TestAction buildConfiguration="Debug" selectedDebuggerIdentifier="Xcode.DebuggerFoundation.Debugger.LLDB" selectedLauncherIdentifier="Xcode.DebuggerFoundation.Launcher.LLDB" shouldUseLaunchSchemeArgsEnv="YES">
    <Testables/>
  </TestAction>
  <LaunchAction buildConfiguration="Debug" selectedDebuggerIdentifier="Xcode.DebuggerFoundation.Debugger.LLDB" selectedLauncherIdentifier="Xcode.DebuggerFoundation.Launcher.LLDB" launchStyle="0" useCustomWorkingDirectory="NO" ignoresPersistentStateOnLaunch="NO" debugDocumentVersioning="YES" debugServiceExtension="internal" allowLocationSimulation="YES"/>
  <ProfileAction buildConfiguration="Release" shouldUseLaunchSchemeArgsEnv="YES" savedToolIdentifier="" useCustomWorkingDirectory="NO" debugDocumentVersioning="YES"/>
  <AnalyzeAction buildConfiguration="Debug"/>
  <ArchiveAction buildConfiguration="Release" revealArchiveInOrganizer="YES"/>
</Scheme>
"""
        scheme_path = scheme_dir / f"{project_name}.xcscheme"
        scheme_path.write_text(scheme_content, encoding="utf-8")
