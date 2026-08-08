#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Windows Builder – Compilation pour Microsoft Windows.
Supporte MSVC, Clang (via clang-cl ou clang++), et MinGW (gcc/g++).
Gère les fichiers .exe, .dll, .lib, .pdb, .res (ressources).
Support complet des modules C++20 : .cppm, .ixx, .mpp, .c++m.
"""

import os
import sys
import subprocess
from pathlib import Path
from typing import List, Optional, Dict, Any

from Jenga.Core.Api import Project, ProjectKind, CompilerFamily, TargetEnv, TargetOS
from ...Utils import Process, FileSystem, Colored, ProcessResult
from ..Builder import Builder
from ..Toolchains import ToolchainManager
from ..IconConverter import (
    ResolveIconFor, DetectIconFormat, ConvertPngToIco, HasPillow,
    PLATFORM_WINDOWS, FORMAT_PNG, FORMAT_JPG, FORMAT_ICO,
)
import shutil as _shutil


class WindowsBuilder(Builder):
    """
    Builder pour Windows (PE/COFF).
    """

    def __init__(self, workspace, config, platform, targetOs, targetArch, targetEnv=None, verbose=False):
        super().__init__(workspace, config, platform, targetOs, targetArch, targetEnv, verbose)
        self.is_msvc = self.toolchain.compilerFamily == CompilerFamily.MSVC
        self.is_clang = self.toolchain.compilerFamily == CompilerFamily.CLANG
        self.is_mingw = (self.toolchain.compilerFamily == CompilerFamily.GCC and self.toolchain.targetOs == TargetOS.WINDOWS) or \
                        (self.toolchain.compilerFamily == CompilerFamily.CLANG and self.toolchain.targetEnv == TargetEnv.MINGW)
        self.is_clang_cl = self.is_clang and "clang-cl" in str(self.toolchain.ccPath).lower()
        self._validate_compiler_paths()

    def _validate_compiler_paths(self):
        if self.is_msvc or self.is_clang_cl:
            if self.toolchain.ccPath is None:
                raise RuntimeError(f"MSVC/clang-cl compiler path not set for toolchain '{self.toolchain.name}'")
        elif self.is_mingw or self.is_clang:
            if self.toolchain.ccPath is None:
                raise RuntimeError(f"GCC/Clang compiler path not set for toolchain '{self.toolchain.name}'")

    @staticmethod
    def _EnumValue(v):
        return v.value if hasattr(v, "value") else v

    def PreparePCH(self, project: Project, objDir: Path) -> bool:
        project._jengaPchFile = ""
        project._jengaPchHeaderResolved = ""
        project._jengaPchHeaderToken = ""
        project._jengaPchSourceResolved = ""
        if not project.pchHeader:
            return True

        header_path = Path(self.ResolveProjectPath(project, project.pchHeader))
        if self.verbose:
            Colored.PrintInfo(
                f"[PCH] {project.name}: pchHeader={project.pchHeader!r} "
                f"resolved={header_path} exists={header_path.exists()}"
            )
        if not header_path.exists():
            Colored.PrintError(f"[PCH] Header not found for {project.name}: {header_path}")
            return False
        header_token = header_path.name
        pch_file = objDir / f"{project.name}.pch"
        project._jengaPchHeaderResolved = str(header_path)
        project._jengaPchHeaderToken = header_token
        project._jengaPchFile = str(pch_file)

        source_path = None
        if project.pchSource:
            source_path = Path(self.ResolveProjectPath(project, project.pchSource))
            project._jengaPchSourceResolved = str(source_path)
        else:
            source_path = objDir / "__jenga_pch.cpp"
            source_path.write_text(f'#include "{header_token}"\n', encoding="utf-8")
            project._jengaPchSourceResolved = str(source_path)

        # ── PCH DEJA A JOUR : sauter la COMPILATION, pas la preparation ──────
        #
        # L'en-tete precompile etait refait a CHAQUE build : 16 lancements de
        # clang++ sur un workspace de 22 projets sans la moindre modification.
        #
        # Le test se place ICI, et surtout PAS plus haut : tout ce qui precede
        # renseigne l'etat dont la compilation des sources depend
        # (_jengaPchSourceResolved, et l'ecriture de __jenga_pch.cpp). Un retour
        # anticipe avant ce point laisse le projet sans PCH utilisable et fait
        # RECOMPILER toutes les sources — essaye, mesure : 225 sous-processus
        # et 44 s au lieu de 11 s.
        #
        # En cas de doute, on recompile : un PCH perime provoque des erreurs
        # incomprehensibles (« predefined macro was disabled in precompiled
        # file »). Le doute profite a la correction, jamais a la vitesse.
        entrees = [header_path]
        if source_path and Path(source_path).exists():
            entrees.append(Path(source_path))
        # La verification porte desormais aussi sur les en-tetes INCLUS par le
        # PCH (fichier .d emis plus bas) : sans cela, modifier un en-tete bas
        # niveau laissait le PCH passer pour frais et faisait echouer toutes
        # les sources sur un message qui accuse un fichier innocent.
        if self.PchIsFresh(project, pch_file, entrees):
            return True

        # Le PCH DOIT etre compile avec les MEMES flags d'optimisation et de
        # symboles que les sources qui l'utilisent. Sinon clang/gcc rejettent
        # le PCH avec "predefined macro was disabled in precompiled file"
        # (__OPTIMIZE__, __OPTIMIZE_SIZE__, __NO_INLINE__ different selon -Ox).
        opt  = self._EnumValue(project.optimize)
        syms = bool(project.symbols)

        if self.is_msvc or self.is_clang_cl:
            args = [self.toolchain.ccPath, "/c", f"/Fo{objDir / '__jenga_pch.obj'}", "/nologo"]
            # Flags optim/symbols equivalents a _CompileMSVC.
            if syms:
                args.append("/Zi")
            if   opt == "Speed": args.append("/O2")
            elif opt == "Size":  args.append("/O1")
            elif opt == "Full":  args.append("/Ox")
            else:                args.append("/Od")
            for inc in project.includeDirs:
                args.append(f"/I{self.ResolveProjectPath(project, inc)}")
            args.append(f"/I{header_path.parent}")
            for define in self.toolchain.defines:
                args.append(f"/D{define}")
            for define in project.defines:
                args.append(f"/D{define}")
            if project.language.value in ("C++", "Objective-C++") and project.cppdialect:
                args.append(f"/std:{project.cppdialect.lower()}")
            elif project.cdialect:
                args.append(f"/std:{project.cdialect.lower()}")
            args.append(f"/Yc{header_token}")
            args.append(f"/Fp{pch_file}")
            args.append(str(source_path))
            result = Process.ExecuteCommand(args, captureOutput=True, silent=False)
            self._lastResult = result
            return result.returnCode == 0

        # clang++ / mingw path
        compiler = self.toolchain.cxxPath or self.toolchain.ccPath
        args = [compiler, "-x", "c++-header", str(header_path), "-o", str(pch_file)]
        # Flags optim/symbols equivalents a _CompileMinGW/_GetGCCCommonFlags.
        if syms:
            args.append("-g")
        if   opt == "Off":   args.append("-O0")
        elif opt == "Size":  args.append("-Os")
        elif opt == "Speed": args.append("-O2")
        elif opt == "Full":  args.append("-O3")
        for inc in project.includeDirs:
            args.append(f"-I{self.ResolveProjectPath(project, inc)}")
        args.append(f"-I{header_path.parent}")
        # Emet la liste des en-tetes reellement inclus, a cote du PCH. C'est ce
        # fichier que PchIsFresh relit pour decider s'il est encore valable.
        args.extend(self.GetDependencyFlags(str(pch_file)))
        for define in self.toolchain.defines:
            args.append(f"-D{define}")
        for define in project.defines:
            args.append(f"-D{define}")
        if project.language.value in ("C++", "Objective-C++") and project.cppdialect:
            args.append(f"-std={project.cppdialect.lower()}")
            args.extend(self.toolchain.cxxflags)
            args.extend(project.cxxflags)
        elif project.cdialect:
            args.append(f"-std={project.cdialect.lower()}")
            args.extend(self.toolchain.cflags)
            args.extend(project.cflags)
        result = Process.ExecuteCommand(args, captureOutput=True, silent=False)
        self._lastResult = result
        if result.returnCode != 0:
            Colored.PrintError(f"PCH compilation failed for {project.name}:")
            Colored.PrintError(f"  cmd: {' '.join(str(a) for a in args)}")
            if result.stdout:
                Colored.PrintError(f"  stdout: {result.stdout}")
            if result.stderr:
                Colored.PrintError(f"  stderr: {result.stderr}")
        return result.returnCode == 0

    # -----------------------------------------------------------------------
    # Implémentation des méthodes abstraites
    # -----------------------------------------------------------------------

    def GetObjectExtension(self) -> str:
        return ".obj"

    def GetOutputExtension(self, project: Project) -> str:
        if project.kind == ProjectKind.SHARED_LIB:
            return ".dll"
        elif project.kind == ProjectKind.STATIC_LIB:
            return ".lib"
        elif project.kind in (ProjectKind.CONSOLE_APP, ProjectKind.WINDOWED_APP, ProjectKind.TEST_SUITE):
            return ".exe"
        else:
            return ".exe"

    def Compile(self, project: Project, sourceFile: str, objectFile: str) -> ProcessResult:
        src = Path(sourceFile)
        obj = Path(objectFile)
        FileSystem.MakeDirectory(obj.parent)
        if self.is_msvc:
            return self._CompileMSVC(project, src, obj)
        elif self.is_clang:
            return self._CompileClang(project, src, obj)
        elif self.is_mingw:
            return self._CompileMinGW(project, src, obj)
        else:
            Colored.PrintError(f"Unsupported compiler family for Windows: {self.toolchain.compilerFamily}")
            # Retourner un ProcessResult factice en échec
            return ProcessResult(returnCode=1, stdout="", stderr="Unsupported compiler family")

    def GetModuleFlags(self, project: Project, sourceFile: str) -> List[str]:
        flags = []
        if not self.IsModuleFile(sourceFile):
            return flags
        if self.is_msvc or self.is_clang_cl:
            flags.append("/interface")
            flags.append("/std:c++latest")
            obj_dir = self.GetObjectDir(project)
            ifc_name = Path(sourceFile).with_suffix('.ifc').name
            ifc_path = obj_dir / ifc_name
            flags.append(f"/module:output{str(ifc_path)}")
            if '_part.' in sourceFile or sourceFile.endswith('_part.ixx'):
                flags.append("/internalPartition")
        elif self.is_clang and not self.is_clang_cl:
            flags.extend(["-fmodules", "-fbuiltin-module-map", "-std=c++20"])
            obj_dir = self.GetObjectDir(project)
            pcm_name = Path(sourceFile).with_suffix('.pcm').name
            pcm_path = obj_dir / pcm_name
            flags.append(f"-fmodule-output={str(pcm_path)}")
        elif self.is_mingw:
            flags.extend(["-fmodules-ts", "-std=c++20"])
            obj_dir = self.GetObjectDir(project)
            gcm_dir = obj_dir / "gcm"
            flags.append(f"-fmodule-mapper={str(gcm_dir / 'module.mapper')}")
        return flags

    def Link(self, project: Project, objectFiles: List[str], outputFile: str) -> bool:
        out = Path(outputFile)
        FileSystem.MakeDirectory(out.parent)

        # Icone d'app : on prepare un .res (resource object) que tous les
        # linkers Windows (link.exe, lld-link, gcc/clang+windres) acceptent en
        # entree comme un .obj normal. Ne s'applique pas aux libs (kind != APP).
        if project.kind in (ProjectKind.CONSOLE_APP, ProjectKind.WINDOWED_APP):
            res_obj = self._PrepareWindowsIconObject(project)
            if res_obj is not None:
                objectFiles = list(objectFiles) + [str(res_obj)]

        if self.is_msvc:
            return self._LinkMSVC(project, objectFiles, out)
        elif self.is_clang:
            return self._LinkClang(project, objectFiles, out)
        elif self.is_mingw:
            return self._LinkMinGW(project, objectFiles, out)
        else:
            Colored.PrintError(f"Unsupported compiler family for Windows: {self.toolchain.compilerFamily}")
            return False

    # -----------------------------------------------------------------------
    # App icon : PNG/ICO -> .res (resource object embedded in PE/COFF)
    # -----------------------------------------------------------------------

    def _PrepareWindowsIconObject(self, project: Project) -> Optional[Path]:
        """
        Genere un fichier .res (ou .res.o pour MinGW) contenant l'icone d'app.
        Retourne le path, ou None si pas d'icone configuree / si la compilation
        ressource echoue (un warning est logue).

        Etapes :
          1. Resolve l'icone via IconConverter.
          2. Si PNG -> convertit en .ico (Pillow).
          3. Genere un .rc minimal qui declare IDI_ICON1 ICON "icon.ico".
          4. Compile via rc.exe (MSVC) / llvm-rc (clang) / windres (MinGW).
        """
        icon_src = ResolveIconFor(project, PLATFORM_WINDOWS)
        if not icon_src:
            return None

        icon_path = Path(self.ResolveProjectPath(project, icon_src))
        if not icon_path.exists():
            Colored.PrintWarning(
                f"[Windows:icon] icone configuree introuvable : {icon_path}"
            )
            return None

        obj_dir = Path(self.GetObjectDir(project)) / "app-icon"
        obj_dir.mkdir(parents=True, exist_ok=True)

        # Etape 1 : on resout l'icone vers un .ico (convertit si necessaire).
        fmt = DetectIconFormat(icon_path)
        ico_path = obj_dir / "app_icon.ico"
        if fmt == FORMAT_ICO:
            _shutil.copy2(icon_path, ico_path)
        elif fmt in (FORMAT_PNG, FORMAT_JPG):
            if not HasPillow():
                Colored.PrintWarning(
                    "[Windows:icon] Pillow non installe -- conversion PNG->ICO "
                    "ignoree. Installer : pip install Pillow"
                )
                return None
            if not ConvertPngToIco(icon_path, ico_path):
                Colored.PrintWarning(f"[Windows:icon] conversion PNG->ICO echouee : {icon_path}")
                return None
        else:
            Colored.PrintWarning(
                f"[Windows:icon] format non supporte ({fmt}) pour Windows : {icon_path}"
            )
            return None

        # Etape 2 : on genere le .rc. Pour eviter les soucis de chemin avec
        # rc.exe, on utilise un nom relatif (les deux fichiers sont dans le
        # meme dossier).
        rc_path = obj_dir / "app_icon.rc"
        # Important : on utilise l'ID NUMERIQUE "1" plutot que le nom
        # symbolique "IDI_ICON1". Windres stocke IDI_ICON1 comme STRING name
        # alors que LoadImage(hInst, MAKEINTRESOURCEW(1), ...) cherche un ID
        # numerique. Avec "1" en literal, le windres genere un resource avec
        # ID=1, donc MAKEINTRESOURCEW(1) le trouve. Bonus : Windows utilise
        # "le plus petit ID d'icone" comme icone principale de l'exe (visible
        # dans Explorer + ExtractAssociatedIcon).
        rc_path.write_text(
            '1 ICON DISCARDABLE "app_icon.ico"\n',
            encoding="utf-8"
        )

        # Etape 3 : compilation .rc -> .res (ou .res.o pour MinGW).
        if self.is_mingw:
            res_out = obj_dir / "app_icon.res.o"
            windres = "windres"
            cmd = [windres, "-O", "coff", "-i", str(rc_path), "-o", str(res_out)]
        else:
            res_out = obj_dir / "app_icon.res"
            # Pour MSVC/clang-cl, on essaie rc.exe en premier (Windows SDK),
            # puis llvm-rc en fallback (LLVM bin). Les deux acceptent /fo et /nologo.
            tool = "rc.exe" if (self.is_msvc or self.is_clang_cl) else "llvm-rc"
            cmd = [tool, "/nologo", f"/fo{res_out}", str(rc_path)]

        if self.verbose:
            Colored.PrintInfo(f"[Windows:icon] {' '.join(cmd)}")

        result = Process.ExecuteCommand(cmd, captureOutput=True, silent=False)
        if result.returnCode != 0:
            # Fallback : si rc.exe absent, essayer llvm-rc.
            if not self.is_mingw and cmd[0] == "rc.exe":
                cmd[0] = "llvm-rc"
                result = Process.ExecuteCommand(cmd, captureOutput=True, silent=False)

        if result.returnCode != 0:
            Colored.PrintWarning(
                f"[Windows:icon] compilation du .rc echouee ({cmd[0]}). "
                f"L'executable sera produit sans icone. Verifier rc.exe/llvm-rc dans le PATH."
            )
            return None

        return res_out

    # -----------------------------------------------------------------------
    # Compilation MSVC
    # -----------------------------------------------------------------------

    def _CompileMSVC(self, project: Project, src: Path, obj: Path) -> ProcessResult:
        args = [self.toolchain.ccPath, "/c", f"/Fo{obj}", "/nologo"]
        for inc in project.includeDirs:
            args.append(f"/I{self.ResolveProjectPath(project, inc)}")
        for define in self.toolchain.defines:
            args.append(f"/D{define}")
        for define in project.defines:
            args.append(f"/D{define}")
        opt = self._EnumValue(project.optimize)
        warn = self._EnumValue(project.warnings)
        if project.symbols:
            args.append("/Zi")
        if opt == "Speed":
            args.append("/O2")
        elif opt == "Size":
            args.append("/O1")
        elif opt == "Full":
            args.append("/Ox")
        else:
            args.append("/Od")
        if warn == "All":
            args.append("/W3")
        elif warn == "Extra":
            args.append("/W4")
        elif warn == "Pedantic":
            args.append("/W4")
        elif warn == "Everything":
            args.append("/Wall")
        elif warn == "Error":
            args.append("/WX")
        if project.language.value in ("C++", "Objective-C++"):
            if project.cppdialect:
                args.append(f"/std:{project.cppdialect.lower()}")
        else:
            if project.cdialect:
                args.append(f"/std:{project.cdialect.lower()}")
        if self.IsModuleFile(str(src)):
            args.extend(self.GetModuleFlags(project, str(src)))
        pch_file = getattr(project, "_jengaPchFile", "")
        pch_token = getattr(project, "_jengaPchHeaderToken", "")
        pch_src = getattr(project, "_jengaPchSourceResolved", "")
        if pch_file and pch_token and str(src.resolve()) != str(Path(pch_src).resolve()):
            args.append(f"/Yu{pch_token}")
            args.append(f"/Fp{pch_file}")
        args.extend(self.toolchain.cxxflags if project.language.value in ("C++", "Objective-C++") else self.toolchain.cflags)
        if project.language.value in ("C++", "Objective-C++"):
            args.extend(project.cxxflags)
        else:
            args.extend(project.cflags)
        args.append(str(src))
        result = Process.ExecuteCommand(args, captureOutput=True, silent=False)
        self._lastResult = result
        return result

    def _LinkMSVC(self, project: Project, objectFiles: List[str], output: Path) -> bool:
        if project.kind == ProjectKind.STATIC_LIB:
            return self._CreateStaticLibMSVC(project, objectFiles, output)
        args = [self.toolchain.ldPath, f"/OUT:{output}", "/nologo"]
        if project.kind == ProjectKind.SHARED_LIB:
            args.append("/DLL")
        for libdir in project.libDirs:
            args.append(f"/LIBPATH:{self.ResolveProjectPath(project, libdir)}")
        for lib in project.links:
            if not lib.endswith(".lib"):
                lib += ".lib"
            args.append(lib)
        args.extend(self.toolchain.ldflags)
        args.extend(project.ldflags)
        args.extend(objectFiles)
        result = Process.ExecuteCommand(args, captureOutput=True, silent=False)
        self._lastResult = result
        return result.returnCode == 0

    def _CreateStaticLibMSVC(self, project: Project, objectFiles: List[str], output: Path) -> bool:
        lib_path = Path(self.toolchain.toolchainDir).parent / "lib.exe"
        if not lib_path.exists():
            lib_path = self.toolchain.arPath
        args = [str(lib_path), f"/OUT:{output}", "/nologo"]
        args.extend(self.toolchain.arflags)
        args.extend(objectFiles)
        result = Process.ExecuteCommand(args, captureOutput=True, silent=False)
        self._lastResult = result
        return result.returnCode == 0

    # -----------------------------------------------------------------------
    # Compilation Clang/LLVM (clang-cl ou clang++)
    # -----------------------------------------------------------------------

    def _CompileClang(self, project: Project, src: Path, obj: Path) -> ProcessResult:
        if self.is_clang_cl:
            args = [self.toolchain.ccPath, "/c", f"/Fo{obj}"]
            opt = self._EnumValue(project.optimize)
            if project.symbols:
                args.append("/Zi")
            if opt == "Speed":
                args.append("/O2")
            elif opt == "Size":
                args.append("/O1")
            else:
                args.append("/Od")
            for inc in project.includeDirs:
                args.append(f"/I{self.ResolveProjectPath(project, inc)}")
            for define in self.toolchain.defines:
                args.append(f"/D{define}")
            for define in project.defines:
                args.append(f"/D{define}")
            if self.IsModuleFile(str(src)):
                args.extend(self.GetModuleFlags(project, str(src)))
            pch_file = getattr(project, "_jengaPchFile", "")
            pch_token = getattr(project, "_jengaPchHeaderToken", "")
            pch_src = getattr(project, "_jengaPchSourceResolved", "")
            if pch_file and pch_token and str(src.resolve()) != str(Path(pch_src).resolve()):
                args.append(f"/Yu{pch_token}")
                args.append(f"/Fp{pch_file}")
            if project.language.value in ("C++", "Objective-C++"):
                if project.cppdialect:
                    args.append(f"/std:{project.cppdialect.lower()}")
            else:
                if project.cdialect:
                    args.append(f"/std:{project.cdialect.lower()}")
            args.extend(self.toolchain.cxxflags if project.language.value in ("C++", "Objective-C++") else self.toolchain.cflags)
            if project.language.value in ("C++", "Objective-C++"):
                args.extend(project.cxxflags)
            else:
                args.extend(project.cflags)
            args.append(str(src))
        else:
            args = [self.toolchain.ccPath, "-c", "-o", str(obj)]
            args.extend(self.GetDependencyFlags(str(obj)))
            args.extend(self._GetClangCommonFlags(project))
            pch_file = getattr(project, "_jengaPchFile", "")
            if pch_file:
                args.extend(["-include-pch", pch_file])
            if self.IsModuleFile(str(src)):
                args.extend(self.GetModuleFlags(project, str(src)))
            if project.language.value in ("C++", "Objective-C++"):
                args.extend(project.cxxflags)
            else:
                args.extend(project.cflags)
            args.append(str(src))
        result = Process.ExecuteCommand(args, captureOutput=True, silent=False)
        self._lastResult = result
        return result

    def _LinkClang(self, project: Project, objectFiles: List[str], output: Path) -> bool:
        if self.is_clang_cl:
            if project.kind == ProjectKind.STATIC_LIB:
                return self._CreateStaticLibClang(project, objectFiles, output)

            driver = self.toolchain.cxxPath or self.toolchain.ccPath
            args = [driver]
            if project.kind == ProjectKind.SHARED_LIB:
                args.append("/LD")
            args.extend(objectFiles)
            args.append(f"/Fe{output}")

            link_args = []
            for libdir in project.libDirs:
                link_args.append(f"/LIBPATH:{self.ResolveProjectPath(project, libdir)}")
            for lib in project.links:
                if not lib.endswith(".lib"):
                    lib += ".lib"
                link_args.append(lib)
            link_args.extend(self.toolchain.ldflags)
            link_args.extend(project.ldflags)
            if link_args:
                args.append("/link")
                args.extend(link_args)
        elif self.toolchain.ldPath and "lld-link" in str(self.toolchain.ldPath).lower():
            if project.kind == ProjectKind.STATIC_LIB:
                return self._CreateStaticLibClang(project, objectFiles, output)
            ld = self.toolchain.ldPath if self.toolchain.ldPath else self.toolchain.cxxPath
            args = [ld, f"/OUT:{output}"]
            if project.kind == ProjectKind.SHARED_LIB:
                args.append("/DLL")
            for libdir in project.libDirs:
                args.append(f"/LIBPATH:{self.ResolveProjectPath(project, libdir)}")
            for lib in project.links:
                if not lib.endswith(".lib"):
                    lib += ".lib"
                args.append(lib)
            args.extend(self.toolchain.ldflags)
            args.extend(project.ldflags)
            args.extend(objectFiles)
        else:
            if project.kind == ProjectKind.STATIC_LIB:
                return self._CreateStaticLibClang(project, objectFiles, output)
            ld = self.toolchain.cxxPath
            args = [ld, "-o", str(output)]
            if project.kind == ProjectKind.SHARED_LIB:
                args.append("-shared")
            args.extend(objectFiles)
            for libdir in project.libDirs:
                args.append(f"-L{self.ResolveProjectPath(project, libdir)}")
            if project.links:
                # GNU-like linkers on Windows (clang-mingw) are one-pass and
                # order-sensitive for static archives. Group archives to allow
                # symbol resolution across mutually-dependent libraries.
                args.append("-Wl,--start-group")
            for lib in project.links:
                if Path(lib).is_absolute() or ('/' in lib or '\\' in lib):
                    args.append(lib)
                else:
                    args.append(f"-l{lib}")
            if project.links:
                args.append("-Wl,--end-group")
            args.extend(self._StaticRuntimeFlags(project))  # staticruntime() -> exe autonome (clang-mingw)
            args.extend(self.toolchain.ldflags)
            args.extend(project.ldflags)
        if self.verbose and project.kind != ProjectKind.STATIC_LIB:
            Colored.PrintInfo(f"[Link:Clang:{project.name}] {' '.join(str(a) for a in args)}")
        result = Process.ExecuteCommand(args, captureOutput=True, silent=False)
        self._lastResult = result
        return result.returnCode == 0

    # -----------------------------------------------------------------------
    # Compilation MinGW (GCC)
    # -----------------------------------------------------------------------

    def _CompileMinGW(self, project: Project, src: Path, obj: Path) -> ProcessResult:
        args = [self.toolchain.ccPath, "-c", "-o", str(obj)]
        args.extend(self.GetDependencyFlags(str(obj)))
        args.extend(self._GetGCCCommonFlags(project))
        pch_header = getattr(project, "_jengaPchHeaderResolved", "")
        if pch_header:
            args.extend(["-include", pch_header])
        if self.IsModuleFile(str(src)):
            args.extend(self.GetModuleFlags(project, str(src)))
        if project.language.value in ("C++", "Objective-C++"):
            args.extend(project.cxxflags)
        else:
            args.extend(project.cflags)
        args.append(str(src))
        result = Process.ExecuteCommand(args, captureOutput=True, silent=False)
        self._lastResult = result
        return result

    def _StaticRuntimeFlags(self, project: Project) -> List[str]:
        """Flags de lien du runtime C++/GCC statique si staticruntime() est actif sur le
        projet (GCC/Clang GNU-style seulement). Rend l'exe autonome (pas de libstdc++/
        libgcc en DLL). Ne PAS ajouter `-static` seul (casse la selection lld)."""
        if getattr(project, "staticRuntime", False):
            return ["-static-libstdc++", "-static-libgcc"]
        return []

    def _LinkMinGW(self, project: Project, objectFiles: List[str], output: Path) -> bool:
        if project.kind == ProjectKind.STATIC_LIB:
            return self._CreateStaticLibGCC(project, objectFiles, output)
        args = [self.toolchain.cxxPath, "-o", str(output)]
        if project.kind == ProjectKind.SHARED_LIB:
            args.append("-shared")
        args.extend(objectFiles)
        for libdir in project.libDirs:
            args.append(f"-L{self.ResolveProjectPath(project, libdir)}")
        for lib in project.links:
            if Path(lib).is_absolute() or ('/' in lib or '\\' in lib):
                args.append(lib)
            else:
                args.append(f"-l{lib}")
        args.extend(self._StaticRuntimeFlags(project))
        args.extend(project.ldflags)
        if self.verbose:
            Colored.PrintInfo(f"[Link:MinGW:{project.name}] {' '.join(str(a) for a in args)}")
        result = Process.ExecuteCommand(args, captureOutput=True, silent=False)
        self._lastResult = result
        return result.returnCode == 0

    # -----------------------------------------------------------------------
    # Utilitaires communs
    # -----------------------------------------------------------------------

    def _GetGCCCommonFlags(self, project: Project) -> List[str]:
        flags = []
        for inc in project.includeDirs:
            flags.append(f"-I{self.ResolveProjectPath(project, inc)}")
        for define in self.toolchain.defines:
            flags.append(f"-D{define}")
        for define in project.defines:
            flags.append(f"-D{define}")
        opt = self._EnumValue(project.optimize)
        warn = self._EnumValue(project.warnings)
        if project.symbols:
            flags.append("-g")
        if opt == "Off":
            flags.append("-O0")
        elif opt == "Size":
            flags.append("-Os")
        elif opt == "Speed":
            flags.append("-O2")
        elif opt == "Full":
            flags.append("-O3")
        if warn == "All":
            flags.append("-Wall")
        elif warn == "Extra":
            flags.append("-Wextra")
        elif warn == "Pedantic":
            flags.append("-pedantic")
        elif warn == "Error":
            flags.append("-Werror")
        if project.language.value in ("C++", "Objective-C++"):
            if project.cppdialect:
                flags.append(f"-std={project.cppdialect.lower()}")
            flags.extend(self.toolchain.cxxflags)
        else:
            if project.cdialect:
                flags.append(f"-std={project.cdialect.lower()}")
            flags.extend(self.toolchain.cflags)

        # Ajouter les flags d'import de modules C++20
        flags.extend(self._GetModuleImportFlags(project))

        return flags

    def _GetClangCommonFlags(self, project: Project) -> List[str]:
        return self._GetGCCCommonFlags(project)

    def _CreateStaticLibGCC(self, project: Project, objectFiles: List[str], output: Path) -> bool:
        ar = self.toolchain.arPath or "ar"
        args = [ar, "rcs", str(output)]
        args.extend(self.toolchain.arflags)
        args.extend(objectFiles)
        result = Process.ExecuteCommand(args, captureOutput=True, silent=False)
        self._lastResult = result
        return result.returnCode == 0

    def _CreateStaticLibClang(self, project: Project, objectFiles: List[str], output: Path) -> bool:
        ar = self.toolchain.arPath or "llvm-ar"
        args = [ar, "rcs", str(output)]
        args.extend(self.toolchain.arflags)
        args.extend(objectFiles)
        result = Process.ExecuteCommand(args, captureOutput=True, silent=False)
        self._lastResult = result
        return result.returnCode == 0
