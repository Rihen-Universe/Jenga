#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Linux Builder – Compilation pour Linux ELF.
Supporte GCC et Clang.
Gère les .so, .a, et exécutables.
"""

from pathlib import Path
from typing import List

from Jenga.Core.Api import Project, ProjectKind, CompilerFamily
from ...Utils import Process, FileSystem, ProcessResult
from ..Builder import Builder


class LinuxBuilder(Builder):
    """
    Builder pour Linux (ELF).
    """

    def __init__(self, workspace, config, platform, targetOs, targetArch, targetEnv=None, verbose=False):
        super().__init__(workspace, config, platform, targetOs, targetArch, targetEnv, verbose)
        self.is_gcc = self.toolchain.compilerFamily == CompilerFamily.GCC
        self.is_clang = self.toolchain.compilerFamily in (CompilerFamily.CLANG, CompilerFamily.APPLE_CLANG)

    @staticmethod
    def _EnumValue(v):
        return v.value if hasattr(v, "value") else v

    def PreparePCH(self, project: Project, objDir: Path) -> bool:
        project._jengaPchFile = ""
        project._jengaPchHeaderResolved = ""
        project._jengaPchSourceResolved = ""
        if not project.pchHeader:
            return True

        header = Path(self.ResolveProjectPath(project, project.pchHeader))
        if not header.exists():
            return False

        pch_path = objDir / f"{project.name}.pch"
        compiler = self.toolchain.cxxPath or self.toolchain.ccPath
        if not compiler:
            return False
        # Le PCH etait reconstruit a CHAQUE build ici (aucun test de fraicheur) :
        # correct, mais couteux. On applique le meme test que sous Windows, qui
        # tient compte des en-tetes INCLUS et pas seulement du fichier d'entete.
        source_resolu = Path(self.ResolveProjectPath(project, project.pchSource)) if project.pchSource else None
        entrees = [header] + ([source_resolu] if source_resolu and source_resolu.exists() else [])
        if self.PchIsFresh(project, pch_path, entrees):
            project._jengaPchFile = str(pch_path)
            project._jengaPchHeaderResolved = str(header)
            if project.pchSource:
                project._jengaPchSourceResolved = str(source_resolu)
            return True
        args = [compiler, "-x", "c++-header", str(header), "-o", str(pch_path)]
        args.extend(self.GetDependencyFlags(str(pch_path)))
        pch_flags = [f for f in self._GetCompilerFlags(project) if f not in ("-Winvalid-pch",)]
        filtered = []
        skip_next = False
        for f in pch_flags:
            if skip_next:
                skip_next = False
                continue
            if f == "-include-pch":
                skip_next = True
                continue
            filtered.append(f)
        args.extend(filtered)
        result = Process.ExecuteCommand(args, captureOutput=True, silent=False)
        self._lastResult = result
        if result.returnCode != 0:
            return False

        project._jengaPchFile = str(pch_path)
        project._jengaPchHeaderResolved = str(header)
        if project.pchSource:
            project._jengaPchSourceResolved = self.ResolveProjectPath(project, project.pchSource)
        return True

    @staticmethod
    def _IsDirectLibPath(lib: str) -> bool:
        p = Path(lib)
        return p.suffix in (".a", ".so", ".dylib", ".lib") or "/" in lib or "\\" in lib or p.is_absolute()

    def GetObjectExtension(self) -> str:
        return ".o"

    def GetOutputExtension(self, project: Project) -> str:
        if project.kind == ProjectKind.SHARED_LIB:
            return ".so"
        elif project.kind == ProjectKind.STATIC_LIB:
            return ".a"
        else:
            return ""  # exécutable sans extension

    def Compile(self, project: Project, sourceFile: str, objectFile: str) -> ProcessResult:
        src = Path(sourceFile)
        obj = Path(objectFile)
        FileSystem.MakeDirectory(obj.parent)

        compiler = self.toolchain.cxxPath if project.language.value in ("C++", "Objective-C++") else self.toolchain.ccPath
        args = [compiler, "-c", "-o", str(obj)]
        args.extend(self.GetDependencyFlags(str(obj)))
        args.extend(self._GetCompilerFlags(project))
        if self.IsModuleFile(sourceFile):
            args.extend(self.GetModuleFlags(project, sourceFile))
        args.append(str(src))

        result = Process.ExecuteCommand(args, captureOutput=True, silent=False)
        self._lastResult = result
        return result

    def GetModuleFlags(self, project: Project, sourceFile: str) -> List[str]:
        flags = []
        if not self.IsModuleFile(sourceFile):
            return flags

        if self.toolchain.compilerFamily == CompilerFamily.CLANG:
            flags.extend(["-fmodules", "-fbuiltin-module-map", "-std=c++20"])
            # Clang : génère un fichier .pcm
            obj_dir = self.GetObjectDir(project)
            pcm_name = Path(sourceFile).with_suffix('.pcm').name
            pcm_path = obj_dir / pcm_name
            flags.append(f"-o{str(pcm_path)}")
        else:  # GCC
            flags.append("-fmodules-ts")
            flags.append("-std=c++20")
            # GCC ne permet pas de spécifier le chemin de sortie du .gcm facilement.
        return flags

    def Link(self, project: Project, objectFiles: List[str], outputFile: str) -> bool:
        out = Path(outputFile)
        FileSystem.MakeDirectory(out.parent)

        if project.kind == ProjectKind.STATIC_LIB:
            ar = self.toolchain.arPath or "ar"
            args = [ar, "rcs", str(out)]
            args.extend(self.toolchain.arflags)
            args.extend(project.ldflags)
            args.extend(objectFiles)
        else:
            linker = self.toolchain.cxxPath
            args = [linker, "-o", str(out)]
            if project.kind == ProjectKind.SHARED_LIB:
                args.append("-shared")

            # Object files first.
            args.extend(objectFiles)

            # Runtime C++/GCC statique (staticruntime()) -> binaire autonome (GCC/Clang+libstdc++).
            if getattr(project, "staticRuntime", False):
                args.extend(["-static-libstdc++", "-static-libgcc"])

            # Linker flags before libraries.
            args.extend(self.toolchain.ldflags)
            args.extend(project.ldflags)

            # RPATH
            if project.targetDir:
                args.append("-Wl,-rpath,$ORIGIN")

            # Library search paths.
            for libdir in project.libDirs:
                args.append(f"-L{self.ResolveProjectPath(project, libdir)}")

            # Group libraries to resolve cyclic static dependencies.
            lib_args: List[str] = []
            for lib in project.links:
                if self._IsDirectLibPath(lib):
                    lib_args.append(self.ResolveProjectPath(project, lib))
                else:
                    lib_args.append(f"-l{lib}")

            if lib_args:
                args.append("-Wl,--start-group")
                args.extend(lib_args)
                args.append("-Wl,--end-group")

        result = Process.ExecuteCommand(args, captureOutput=True, silent=False)
        self._lastResult = result
        return result.returnCode == 0

    def _GetCompilerFlags(self, project: Project) -> List[str]:
        flags = []

        # Includes
        for inc in project.includeDirs:
            flags.append(f"-I{self.ResolveProjectPath(project, inc)}")

        pch_file = getattr(project, "_jengaPchFile", "")
        pch_header = getattr(project, "_jengaPchHeaderResolved", "")
        if pch_file:
            if self.is_clang:
                flags.extend(["-include-pch", pch_file])
            elif pch_header:
                flags.extend(["-include", pch_header, "-Winvalid-pch"])

        # Définitions
        for define in self.toolchain.defines:
            flags.append(f"-D{define}")
        for define in project.defines:
            flags.append(f"-D{define}")

        # Debug
        if project.symbols:
            flags.append("-g")

        # Optimisation
        opt = self._EnumValue(project.optimize)
        if opt == "Off":
            flags.append("-O0")
        elif opt == "Size":
            flags.append("-Os")
        elif opt == "Speed":
            flags.append("-O2")
        elif opt == "Full":
            flags.append("-O3")

        # Warnings
        warn = self._EnumValue(project.warnings)
        if warn == "All":
            flags.append("-Wall")
        elif warn == "Extra":
            flags.append("-Wextra")
        elif warn == "Pedantic":
            flags.append("-pedantic")
        elif warn == "Everything" and self.is_clang:
            flags.append("-Weverything")
        elif warn == "Error":
            flags.append("-Werror")

        # Standard
        if project.language.value in ("C++", "Objective-C++"):
            if project.cppdialect:
                flags.append(f"-std={project.cppdialect.lower()}")
            flags.extend(self.toolchain.cxxflags)
        else:
            if project.cdialect:
                flags.append(f"-std={project.cdialect.lower()}")
            flags.extend(self.toolchain.cflags)

        # Position Independent Code (pour les bibliothèques partagées)
        if project.kind == ProjectKind.SHARED_LIB:
            flags.append("-fPIC")

        return flags
