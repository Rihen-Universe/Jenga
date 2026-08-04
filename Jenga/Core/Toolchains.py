#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Toolchains â€“ DÃ©tection automatique et gestion des toolchains.
Fournit des mÃ©thodes pour :
  - DÃ©tecter les compilateurs installÃ©s (MSVC, GCC, Clang, Android NDK, Emscripten, MinGW)
  - CrÃ©er des objets Toolchain correspondants
  - RÃ©soudre la toolchain Ã  utiliser pour une cible donnÃ©e
"""

import os
import sys
from pathlib import Path
from typing import List, Dict, Optional, Tuple, Any

from Jenga.Core.Api import Toolchain, CompilerFamily, TargetOS, TargetArch, TargetEnv
from ..Utils import Process
from .Platform import Platform
from .GlobalToolchains import GetJengaRoot


class ToolchainManager:
    """
    Gestionnaire global de toolchains.
    Peut Ãªtre instanciÃ© pour un workspace ou utilisÃ© statiquement.
    """

    def __init__(self, workspace: Optional[Any] = None):
        self.workspace = workspace
        self._detected: Dict[str, Toolchain] = {}
        self._cache: Dict[Tuple[TargetOS, TargetArch, Optional[TargetEnv]], Optional[str]] = {}

    def _GetCompilersRoot(self, workspace: Optional[Any] = None) -> Optional[Path]:
        wks = workspace or self.workspace
        if wks and getattr(wks, "location", ""):
            root = Path(wks.location).resolve() / ".jenga" / "compilers"
            if root.exists():
                return root
        global_root = GetJengaRoot() / ".jenga" / "compilers"
        return global_root if global_root.exists() else None

    def _CollectExtraBinaryPaths(self, workspace: Optional[Any] = None) -> List[str]:
        root = self._GetCompilersRoot(workspace)
        if not root:
            return []
        paths: List[str] = []
        candidates = [root, root / "bin"]
        for child in root.iterdir():
            if child.is_dir():
                candidates.append(child)
                candidates.append(child / "bin")
        for p in candidates:
            if p.exists() and p.is_dir():
                paths.append(str(p))
        # De-duplicate while preserving order.
        deduped: List[str] = []
        seen = set()
        for p in paths:
            if p in seen:
                continue
            seen.add(p)
            deduped.append(p)
        return deduped

    # ── Cache de DETECTION (duree de vie : le processus) ────────────────────
    #
    # Sonder un compilateur coute un lancement de processus. Ces sondes etaient
    # refaites POUR CHAQUE PROJET : sur un workspace de 22 projets dont aucun
    # n'avait change, 31 lancements de clang/gcc/vswhere pour redecouvrir a
    # chaque fois la meme chose.
    #
    # Le compilateur installe ne change pas pendant un build. On memorise donc
    # le resultat. Portee volontairement limitee au PROCESSUS : un cache sur
    # disque survivrait a une installation ou une desinstallation de toolchain
    # et donnerait des reponses fausses.
    _cacheRunnable: Dict[tuple, Optional[str]] = {}
    _cacheFamily: Dict[str, "CompilerFamily"] = {}

    @staticmethod
    def _FirstRunnable(candidates: List[str], version_arg: str = "--version") -> Optional[str]:
        cle = (tuple(candidates), version_arg)
        if cle in ToolchainManager._cacheRunnable:
            return ToolchainManager._cacheRunnable[cle]
        resultat = None
        for name in candidates:
            path = Process.Which(name)
            if not path:
                continue
            try:
                probe = Process.ExecuteCommand([path, version_arg], captureOutput=True, silent=True)
                if probe.returnCode == 0:
                    resultat = path
                    break
            except Exception:
                continue
        ToolchainManager._cacheRunnable[cle] = resultat
        return resultat

    @staticmethod
    def _AddToolchainIfValid(toolchains: Dict[str, Toolchain], tc: Optional[Toolchain]) -> None:
        if tc is None or not tc.name:
            return
        if tc.name not in toolchains:
            toolchains[tc.name] = tc

    @staticmethod
    def _CloneToolchainWithName(base: Toolchain, name: str) -> Toolchain:
        clone = Toolchain(
            name=name,
            compilerFamily=base.compilerFamily,
            targetOs=base.targetOs,
            targetArch=base.targetArch,
            targetEnv=base.targetEnv,
            targetTriple=base.targetTriple,
            sysroot=base.sysroot,
            ccPath=base.ccPath,
            cxxPath=base.cxxPath,
            arPath=base.arPath,
            ldPath=base.ldPath,
            stripPath=base.stripPath,
            ranlibPath=base.ranlibPath,
            asmPath=base.asmPath,
            toolchainDir=base.toolchainDir,
        )
        clone.defines = list(base.defines or [])
        clone.cflags = list(base.cflags or [])
        clone.cxxflags = list(base.cxxflags or [])
        clone.asmflags = list(base.asmflags or [])
        clone.ldflags = list(base.ldflags or [])
        clone.arflags = list(base.arflags or [])
        clone.frameworks = list(base.frameworks or [])
        clone.frameworkPaths = list(base.frameworkPaths or [])
        clone.perConfigFlags = dict(base.perConfigFlags or {})
        return clone

    # -----------------------------------------------------------------------
    # DÃ©tection des compilateurs hÃ´tes â€“ prioritÃ© : Clang > GCC > MSVC
    # -----------------------------------------------------------------------
    @staticmethod
    def _BuildHostToolchain(name: str, cc_path: str, cxx_candidates: List[str]) -> Optional[Toolchain]:
        if not cc_path:
            return None
        cxx_path = ToolchainManager._FirstRunnable(cxx_candidates) or cc_path
        if Platform.GetHostOS() == TargetOS.MACOS:
            ar_path = Process.Which("ar") or Process.Which("llvm-ar")
        else:
            ar_path = Process.Which("llvm-ar") or Process.Which("ar")
        ld_path = Process.Which("ld") or cxx_path or cc_path

        family = ToolchainManager._DetectCompilerFamily(cc_path)
        tc = Toolchain(
            name=name,
            compilerFamily=family,
            ccPath=cc_path,
            cxxPath=cxx_path,
            arPath=ar_path,
            ldPath=ld_path,
        )
        tc.targetOs = Platform.GetHostOS()
        tc.targetArch = Platform.GetHostArchitecture()
        tc.targetEnv = Platform.GetHostEnvironment()

        if sys.platform == "win32":
            if family == CompilerFamily.GCC:
                tc.targetEnv = TargetEnv.MINGW
            elif family == CompilerFamily.CLANG:
                cc_low = (cc_path or "").lower()
                if any(token in cc_low for token in ("msys64", "mingw", "ucrt")):
                    tc.targetEnv = TargetEnv.MINGW
                elif Process.Which("clang-cl"):
                    tc.targetEnv = TargetEnv.MSVC
                else:
                    tc.targetEnv = TargetEnv.MINGW
            elif family == CompilerFamily.MSVC:
                tc.targetEnv = TargetEnv.MSVC
        return tc

    @staticmethod
    def DetectHostClang() -> Optional[Toolchain]:
        cc_path = ToolchainManager._FirstRunnable(["clang", "clang-18", "clang-17", "cc"])
        if not cc_path:
            return None
        family = ToolchainManager._DetectCompilerFamily(cc_path)
        if family not in (CompilerFamily.CLANG, CompilerFamily.APPLE_CLANG):
            return None
        return ToolchainManager._BuildHostToolchain(
            name=f"host-{family.value}",
            cc_path=cc_path,
            cxx_candidates=["clang++", "c++"],
        )

    @staticmethod
    def DetectHostGCC() -> Optional[Toolchain]:
        cc_path = ToolchainManager._FirstRunnable(["gcc"])
        if not cc_path:
            return None
        family = ToolchainManager._DetectCompilerFamily(cc_path)
        if family != CompilerFamily.GCC:
            return None
        return ToolchainManager._BuildHostToolchain(
            name="host-gcc",
            cc_path=cc_path,
            cxx_candidates=["g++", "c++"],
        )

    @staticmethod
    def DetectHostCC() -> Optional[Toolchain]:
        """Detect the default host C/C++ toolchain."""
        return (
            ToolchainManager.DetectHostClang()
            or ToolchainManager.DetectHostGCC()
            or ToolchainManager._BuildHostToolchain(
                name="host-cc",
                cc_path=ToolchainManager._FirstRunnable(["cc", "zig-cc"]) or "",
                cxx_candidates=["c++", "zig-c++"],
            )
        )
    @staticmethod
    def DetectMSVC() -> Optional[Toolchain]:
        """Detect MSVC from the active environment or Visual Studio installation."""
        if sys.platform != "win32":
            return None

        cl_path = ToolchainManager._FirstRunnable(["cl", "cl.exe"], version_arg="/?")
        link_path = Process.Which("link") or Process.Which("link.exe")
        lib_path = Process.Which("lib") or Process.Which("lib.exe")

        if cl_path:
            tc = Toolchain(
                name="msvc",
                compilerFamily=CompilerFamily.MSVC,
                ccPath=cl_path,
                cxxPath=cl_path,
                arPath=lib_path,
                ldPath=link_path or cl_path,
                toolchainDir=str(Path(cl_path).parent),
            )
            tc.targetOs = TargetOS.WINDOWS
            tc.targetArch = Platform.GetHostArchitecture()
            tc.targetEnv = TargetEnv.MSVC
            return tc

        vswhere_path = Path(os.environ.get("ProgramFiles(x86)", "C:/Program Files (x86)")) / "Microsoft Visual Studio" / "Installer" / "vswhere.exe"
        if not vswhere_path.exists():
            return None

        try:
            install_root = Process.Capture([str(vswhere_path), "-latest", "-property", "installationPath"]).strip()
        except Exception:
            return None

        if not install_root:
            return None

        install_path = Path(install_root)
        msvc_root = install_path / "VC" / "Tools" / "MSVC"
        if not msvc_root.exists():
            return None

        host_arch = Platform.GetHostArchitecture()
        host_bin = "Hostx64/x64" if host_arch == TargetArch.X86_64 else "Hostx86/x86"

        versions = sorted([p for p in msvc_root.iterdir() if p.is_dir()], reverse=True)
        for version_dir in versions:
            bin_dir = version_dir / "bin" / Path(host_bin)
            cl_candidate = bin_dir / "cl.exe"
            if not cl_candidate.exists():
                continue
            link_candidate = bin_dir / "link.exe"
            lib_candidate = bin_dir / "lib.exe"
            tc = Toolchain(
                name="msvc",
                compilerFamily=CompilerFamily.MSVC,
                ccPath=str(cl_candidate),
                cxxPath=str(cl_candidate),
                arPath=str(lib_candidate) if lib_candidate.exists() else None,
                ldPath=str(link_candidate) if link_candidate.exists() else str(cl_candidate),
                toolchainDir=str(version_dir),
            )
            tc.targetOs = TargetOS.WINDOWS
            tc.targetArch = host_arch
            tc.targetEnv = TargetEnv.MSVC
            return tc

        return None


    @staticmethod
    def DetectClangOnWindows() -> Optional[Toolchain]:
        """DÃ©tecte Clang sur Windows. clang-cl -> MSVC ABI, clang -> MinGW ABI."""
        if sys.platform != "win32":
            return None
        # Prefer clang/clang++ MinGW-style toolchain (MSYS2/UCRT) when present.
        clang_path = ToolchainManager._FirstRunnable(["clang"])
        clangpp_path = ToolchainManager._FirstRunnable(["clang++"])
        if clang_path and clangpp_path:
            tc = Toolchain(
                name="clang-mingw",
                compilerFamily=CompilerFamily.CLANG,
                ccPath=clang_path,
                cxxPath=clangpp_path,
                arPath=Process.Which("llvm-ar") or Process.Which("ar"),
                ldPath=clangpp_path,
            )
            tc.targetOs = TargetOS.WINDOWS
            tc.targetArch = Platform.GetHostArchitecture()
            tc.targetEnv = TargetEnv.MINGW
            return tc

        clang_cl_path = ToolchainManager._FirstRunnable(["clang-cl"], version_arg="/?")
        if clang_cl_path:
            tc = Toolchain(
                name="clang-cl",
                compilerFamily=CompilerFamily.CLANG,
                ccPath=clang_cl_path,
                cxxPath=clang_cl_path,
                arPath=Process.Which("llvm-ar") or Process.Which("ar"),
                ldPath=Process.Which("lld-link") or clang_cl_path,
            )
            tc.targetOs = TargetOS.WINDOWS
            tc.targetArch = Platform.GetHostArchitecture()
            tc.targetEnv = TargetEnv.MSVC
            return tc
        return None

    @staticmethod
    def DetectMinGW() -> Optional[Toolchain]:
        """DÃ©tecte MinGW-w64 (gcc/g++ sous Windows)."""
        if sys.platform != "win32":
            return None
        gcc_path = ToolchainManager._FirstRunnable(["x86_64-w64-mingw32-gcc", "gcc"])
        if not gcc_path:
            return None
        if ToolchainManager._DetectCompilerFamily(gcc_path) != CompilerFamily.GCC:
            return None
        gpp_path = ToolchainManager._FirstRunnable(["x86_64-w64-mingw32-g++", "g++"])
        ar_path = Process.Which("x86_64-w64-mingw32-ar") or Process.Which("ar")
        tc = Toolchain(
            name="mingw",
            compilerFamily=CompilerFamily.GCC,
            ccPath=gcc_path,
            cxxPath=gpp_path or gcc_path,
            arPath=ar_path,
            ldPath=Process.Which("ld") or gcc_path,
        )
        tc.targetOs = TargetOS.WINDOWS
        tc.targetArch = Platform.GetHostArchitecture()
        tc.targetEnv = TargetEnv.MINGW
        return tc

    @staticmethod
    def DetectCrossWindows() -> Optional[Toolchain]:
        """
        DÃ©tecte une toolchain de cross-compilation Windows depuis un hÃ´te non-Windows.
        PrioritÃ© :
          1) MinGW-w64 GCC (x86_64-w64-mingw32-*)
          2) Clang avec --target=x86_64-w64-windows-gnu
        """
        if sys.platform == "win32":
            return None

        # 1) GNU MinGW cross toolchain (le plus fiable pour link/runtime).
        gcc_path = Process.Which("x86_64-w64-mingw32-gcc")
        gpp_path = Process.Which("x86_64-w64-mingw32-g++")
        if gcc_path and gpp_path:
            tc = Toolchain(
                name="mingw",
                compilerFamily=CompilerFamily.GCC,
                ccPath=gcc_path,
                cxxPath=gpp_path,
                arPath=Process.Which("x86_64-w64-mingw32-ar") or Process.Which("ar"),
                ldPath=gpp_path,
            )
            tc.targetOs = TargetOS.WINDOWS
            tc.targetArch = TargetArch.X86_64
            tc.targetEnv = TargetEnv.MINGW
            tc.targetTriple = "x86_64-w64-mingw32"
            return tc

        # 2) Clang cross (si le target GNU Windows est supportÃ©).
        clang_path = Process.Which("clang")
        clangxx_path = Process.Which("clang++")
        if clang_path and clangxx_path:
            for triple in ("x86_64-w64-windows-gnu", "x86_64-pc-windows-gnu"):
                test_cmd = [clang_path, f"--target={triple}", "-c", "-x", "c", "-", "-o", os.devnull]
                try:
                    result = Process.ExecuteCommand(
                        test_cmd,
                        captureOutput=True,
                        input="int main(){return 0;}\n",
                        silent=True,
                    )
                except Exception:
                    continue
                if result.returnCode != 0:
                    continue

                tc = Toolchain(
                    name="clang-mingw",
                    compilerFamily=CompilerFamily.CLANG,
                    ccPath=clang_path,
                    cxxPath=clangxx_path,
                    arPath=Process.Which("llvm-ar") or Process.Which("x86_64-w64-mingw32-ar") or Process.Which("ar"),
                    ldPath=clangxx_path,
                )
                tc.targetOs = TargetOS.WINDOWS
                tc.targetArch = TargetArch.X86_64
                tc.targetEnv = TargetEnv.MINGW
                tc.targetTriple = triple
                tc.cflags.append(f"--target={triple}")
                tc.cxxflags.append(f"--target={triple}")
                tc.ldflags.append(f"--target={triple}")
                return tc

        return None

    @staticmethod
    def _DetectCompilerFamily(compiler_path: str) -> CompilerFamily:
        """Famille du compilateur, deduite de --version. MEMORISEE.

        La famille d'un binaire donne ne change pas pendant un build, et
        l'interroger coute un lancement de processus a chaque appel.
        """
        if compiler_path in ToolchainManager._cacheFamily:
            return ToolchainManager._cacheFamily[compiler_path]
        famille = ToolchainManager._DetectCompilerFamilyImpl(compiler_path)
        ToolchainManager._cacheFamily[compiler_path] = famille
        return famille

    @staticmethod
    def _DetectCompilerFamilyImpl(compiler_path: str) -> CompilerFamily:
        try:
            out = Process.Capture([compiler_path, "--version"])
            out_lower = out.lower()
            if "clang" in out_lower:
                if "apple" in out_lower:
                    return CompilerFamily.APPLE_CLANG
                return CompilerFamily.CLANG
            if "zig" in out_lower:
                return CompilerFamily.CLANG
            if "gcc" in out_lower or "g++" in out_lower:
                return CompilerFamily.GCC
            if "msvc" in out_lower or "microsoft" in out_lower:
                return CompilerFamily.MSVC
            if "emscripten" in out_lower:
                return CompilerFamily.EMSCRIPTEN
        except:
            pass
        return CompilerFamily.GCC

    @staticmethod
    def DetectAndroidNDK(ndkPath: Optional[Path] = None) -> Optional[Toolchain]:
        """DÃ©tecte le NDK Android et crÃ©e une toolchain gÃ©nÃ©rique."""
        if ndkPath is None:
            candidates = []
            if "ANDROID_NDK_ROOT" in os.environ:
                candidates.append(Path(os.environ["ANDROID_NDK_ROOT"]))
            if "ANDROID_NDK_HOME" in os.environ:
                candidates.append(Path(os.environ["ANDROID_NDK_HOME"]))
            if "ANDROID_HOME" in os.environ:
                candidates.append(Path(os.environ["ANDROID_HOME"]) / "ndk-bundle")
            if sys.platform == "win32":
                candidates.append(Path("C:/Program Files/Android/NDK"))
            elif sys.platform == "darwin":
                candidates.append(Path("~/Library/Android/sdk/ndk-bundle").expanduser())
            else:
                candidates.append(Path("~/Android/Sdk/ndk-bundle").expanduser())
            if "JENGA_COMPILERS_DIR" in os.environ:
                root = Path(os.environ["JENGA_COMPILERS_DIR"])
                candidates.append(root / "android" / "ndk")
                sdk_ndk = root / "android" / "sdk" / "ndk"
                if sdk_ndk.exists():
                    for version in sorted(sdk_ndk.iterdir(), reverse=True):
                        candidates.append(version)
            for cand in candidates:
                if cand and cand.exists():
                    ndkPath = cand
                    break
        if not ndkPath or not ndkPath.exists():
            return None
        llvm_dir = None
        for p in ndkPath.glob("toolchains/llvm/prebuilt/*"):
            if p.is_dir():
                llvm_dir = p
                break
        if not llvm_dir:
            return None
        tc = Toolchain(
            name="android-ndk",
            compilerFamily=CompilerFamily.ANDROID_NDK,
            toolchainDir=str(llvm_dir),
            ccPath=str(llvm_dir / "bin" / "clang"),
            cxxPath=str(llvm_dir / "bin" / "clang++"),
            arPath=str(llvm_dir / "bin" / "llvm-ar"),
            ldPath=str(llvm_dir / "bin" / "ld"),
            stripPath=str(llvm_dir / "bin" / "llvm-strip"),
            ranlibPath=str(llvm_dir / "bin" / "llvm-ranlib"),
        )
        tc.targetOs = TargetOS.ANDROID
        tc.targetArch = TargetArch.ARM64
        tc.targetEnv = TargetEnv.ANDROID
        return tc

    @staticmethod
    def DetectEmscripten(emsdkPath: Optional[Path] = None) -> Optional[Toolchain]:
        """DÃ©tecte Emscripten SDK."""
        emcc_from_path = Process.Which("emcc")
        emcc_direct = Path(emcc_from_path) if emcc_from_path else None
        if emsdkPath is None:
            if emcc_direct:
                # Typical layouts:
                # - <emsdk>/upstream/emscripten/emcc(.bat)
                # - <emsdk>/emcc(.bat)
                parent = emcc_direct.parent
                if parent.name.lower() == "emscripten" and parent.parent.name.lower() == "upstream":
                    emsdkPath = parent.parent.parent
                else:
                    emsdkPath = parent.parent
            else:
                if sys.platform == "win32":
                    candidates = [Path("C:/emsdk")]
                else:
                    candidates = [Path.home() / "emsdk", Path("/opt/emsdk")]
                if "JENGA_COMPILERS_DIR" in os.environ:
                    candidates.append(Path(os.environ["JENGA_COMPILERS_DIR"]) / "emsdk")
                for cand in candidates:
                    if cand.exists():
                        emsdkPath = cand
                        break
        if not emsdkPath or not emsdkPath.exists():
            return None
        emcc_candidates = []
        if emcc_direct and emcc_direct.exists():
            emcc_candidates.append(emcc_direct)
        names = ["emcc", "emcc.bat", "emcc.cmd", "emcc.exe"]
        for name in names:
            emcc_candidates.extend([
                emsdkPath / name,
                emsdkPath / "emsdk" / name,
                emsdkPath / "upstream" / "emscripten" / name,
            ])
        emcc_path = None
        for cand in emcc_candidates:
            if cand.exists():
                emcc_path = cand
                break
        if not emcc_path:
            return None
        em_dir = emcc_path.parent
        empp_path = None
        emar_path = None
        for name in ("em++", "em++.bat", "em++.cmd", "em++.exe"):
            cand = em_dir / name
            if cand.exists():
                empp_path = cand
                break
        for name in ("emar", "emar.bat", "emar.cmd", "emar.exe"):
            cand = em_dir / name
            if cand.exists():
                emar_path = cand
                break
        tc = Toolchain(
            name="emscripten",
            compilerFamily=CompilerFamily.EMSCRIPTEN,
            toolchainDir=str(emsdkPath),
            ccPath=str(emcc_path),
            cxxPath=str(empp_path or (em_dir / "em++")),
            arPath=str(emar_path or (em_dir / "emar")),
        )
        tc.targetOs = TargetOS.WEB
        tc.targetArch = TargetArch.WASM32
        return tc

    @staticmethod
    def DetectCrossLinuxOnWindows() -> Optional[Toolchain]:
        """DÃ©tecte un cross-compilateur Linux sur Windows (GNU or clang --target)."""
        if sys.platform != "win32":
            return None

        # Prefer a real GNU cross toolchain if available.
        gcc_candidates = [
            ("x86_64-linux-gnu-gcc", "x86_64-linux-gnu-g++", "x86_64-linux-gnu-ar", "x86_64-unknown-linux-gnu"),
            ("x86_64-pc-linux-gnu-gcc", "x86_64-pc-linux-gnu-g++", "x86_64-pc-linux-gnu-ar", "x86_64-pc-linux-gnu"),
        ]
        for cc_name, cxx_name, ar_name, triple in gcc_candidates:
            gcc_path = Process.Which(cc_name)
            if not gcc_path:
                continue
            tc = Toolchain(
                name="gcc-cross-linux",
                compilerFamily=CompilerFamily.GCC,
                ccPath=gcc_path,
                cxxPath=Process.Which(cxx_name) or gcc_path,
                arPath=Process.Which(ar_name) or Process.Which("ar"),
                ldPath=Process.Which(cxx_name) or gcc_path,
            )
            tc.targetOs = TargetOS.LINUX
            tc.targetArch = TargetArch.X86_64
            tc.targetEnv = TargetEnv.GNU
            tc.targetTriple = triple
            return tc

        # Fallback: clang with Linux target triple (compile support check).
        clang_path = Process.Which("clang")
        clangxx_path = Process.Which("clang++")
        if clang_path and clangxx_path:
            triple = "x86_64-unknown-linux-gnu"
            test_cmd = [clang_path, f"--target={triple}", "-c", "-x", "c", "-", "-o", os.devnull]
            try:
                result = Process.ExecuteCommand(test_cmd, captureOutput=True, input="int main(){return 0;}\n", silent=True)
                if result.returnCode == 0:
                    tc = Toolchain(
                        name="clang-cross-linux",
                        compilerFamily=CompilerFamily.CLANG,
                        ccPath=clang_path,
                        cxxPath=clangxx_path,
                        arPath=Process.Which("llvm-ar") or Process.Which("ar"),
                        ldPath=clangxx_path,
                    )
                    tc.targetOs = TargetOS.LINUX
                    tc.targetArch = TargetArch.X86_64
                    tc.targetEnv = TargetEnv.GNU
                    tc.targetTriple = triple
                    tc.cflags.append(f"--target={triple}")
                    tc.cxxflags.append(f"--target={triple}")
                    tc.ldflags.append(f"--target={triple}")
                    return tc
            except Exception:
                pass
        return None
    @staticmethod
    def _EnsureZigShims() -> Tuple[Optional[str], Optional[str], Optional[str]]:
        """Retourne (zig_cc, zig_cxx, zig_ar). Priorité aux shims déjà présents sur le
        PATH ; sinon, si `zig` natif est trouvé, génère des shims dans ~/.jenga/bin
        (zig-cc -> `zig cc`, etc.) et les renvoie. (None, None, None) si zig absent.
        Rend zig détectable SANS installation manuelle de wrappers."""
        cc = ToolchainManager._FirstRunnable(["zig-cc"])
        cxx = ToolchainManager._FirstRunnable(["zig-c++"])
        if cc and cxx:
            ar = ToolchainManager._FirstRunnable(["zig-ar"]) or Process.Which("llvm-ar") or Process.Which("ar")
            return cc, cxx, ar
        zig = Process.Which("zig")
        if not zig:
            return None, None, None
        try:
            bindir = Path.home() / ".jenga" / "bin"
            bindir.mkdir(parents=True, exist_ok=True)
            is_win = sys.platform == "win32"
            made: Dict[str, str] = {}
            for name, sub in (("zig-cc", "cc"), ("zig-c++", "c++"), ("zig-ar", "ar")):
                if is_win:
                    p = bindir / f"{name}.cmd"
                    p.write_text(f'@echo off\r\n"{zig}" {sub} %*\r\n', encoding="ascii")
                else:
                    p = bindir / name
                    p.write_text(f'#!/bin/sh\nexec "{zig}" {sub} "$@"\n', encoding="ascii")
                    p.chmod(0o755)
                made[name] = str(p)
            return made["zig-cc"], made["zig-c++"], made["zig-ar"]
        except Exception:
            return None, None, None

    @staticmethod
    def DetectZigToolchains() -> Dict[str, Toolchain]:
        """Detect Zig wrapper toolchains (zig-cc/zig-c++/zig-ar).
        Auto-génère les shims depuis `zig` natif si les wrappers sont absents."""
        zig_cc, zig_cxx, zig_ar = ToolchainManager._EnsureZigShims()
        if not zig_cc or not zig_cxx:
            return {}

        detected: Dict[str, Toolchain] = {}

        def _register(name: str,
                      target_os: TargetOS,
                      target_arch: TargetArch,
                      target_env: Optional[TargetEnv],
                      triple: str) -> None:
            tc = Toolchain(
                name=name,
                compilerFamily=CompilerFamily.CLANG,
                ccPath=zig_cc,
                cxxPath=zig_cxx,
                arPath=zig_ar,
                ldPath=zig_cxx,
            )
            tc.targetOs = target_os
            tc.targetArch = target_arch
            if target_env is not None:
                tc.targetEnv = target_env
            tc.targetTriple = triple
            tc.cflags.extend(["-target", triple])
            tc.cxxflags.extend(["-target", triple])
            tc.ldflags.extend(["-target", triple])
            detected[name] = tc

        _register("zig-linux-x86_64", TargetOS.LINUX, TargetArch.X86_64, TargetEnv.GNU, "x86_64-linux-gnu")
        _register("zig-linux-x64", TargetOS.LINUX, TargetArch.X86_64, TargetEnv.GNU, "x86_64-linux-gnu")
        _register("zig-windows-x86_64", TargetOS.WINDOWS, TargetArch.X86_64, TargetEnv.MINGW, "x86_64-windows-gnu")
        _register("zig-windows-x64", TargetOS.WINDOWS, TargetArch.X86_64, TargetEnv.MINGW, "x86_64-windows-gnu")
        _register("zig-macos-x86_64", TargetOS.MACOS, TargetArch.X86_64, TargetEnv.GNU, "x86_64-macos")
        _register("zig-macos-arm64", TargetOS.MACOS, TargetArch.ARM64, TargetEnv.GNU, "aarch64-macos")
        # Apple mobile (compile via zig ; link via ld.lld -flavor darwin — voir
        # Core/Builders/IosZig.py). Enregistrees pour que la resolution reussisse
        # sur un hote non-macOS ; le IosZigBuilder ignore le compilateur ci-dessus.
        _register("zig-ios-arm64", TargetOS.IOS, TargetArch.ARM64, None, "aarch64-ios")
        _register("zig-tvos-arm64", TargetOS.TVOS, TargetArch.ARM64, None, "aarch64-tvos")
        _register("zig-watchos-arm64", TargetOS.WATCHOS, TargetArch.ARM64, None, "aarch64-watchos")
        _register("zig-android-arm64", TargetOS.ANDROID, TargetArch.ARM64, TargetEnv.ANDROID, "aarch64-linux-android21")
        _register("zig-web-wasm32", TargetOS.WEB, TargetArch.WASM32, None, "wasm32-wasi")

        return detected

    # -----------------------------------------------------------------------
    # Interface publique
    # -----------------------------------------------------------------------

    def DetectAll(self, workspace: Optional[Any] = None) -> Dict[str, Toolchain]:
        """Detect all available toolchains for the current host and common targets."""
        toolchains: Dict[str, Toolchain] = {}
        original_path = os.environ.get("PATH", "")
        old_compilers_env = os.environ.get("JENGA_COMPILERS_DIR")
        compilers_root = self._GetCompilersRoot(workspace)
        extra_paths = self._CollectExtraBinaryPaths(workspace)
        try:
            if extra_paths:
                os.environ["PATH"] = os.pathsep.join(extra_paths + [original_path])
            if compilers_root:
                os.environ["JENGA_COMPILERS_DIR"] = str(compilers_root)

            # 1) Host-native compilers.
            self._AddToolchainIfValid(toolchains, self.DetectHostClang())
            self._AddToolchainIfValid(toolchains, self.DetectHostGCC())
            self._AddToolchainIfValid(toolchains, self.DetectHostCC())

            # 2) Windows families.
            if sys.platform == "win32":
                self._AddToolchainIfValid(toolchains, self.DetectMSVC())
                self._AddToolchainIfValid(toolchains, self.DetectClangOnWindows())
                self._AddToolchainIfValid(toolchains, self.DetectMinGW())
                self._AddToolchainIfValid(toolchains, self.DetectCrossLinuxOnWindows())
            else:
                self._AddToolchainIfValid(toolchains, self.DetectCrossWindows())

            # 3) SDK-managed toolchains.
            self._AddToolchainIfValid(toolchains, self.DetectAndroidNDK())
            self._AddToolchainIfValid(toolchains, self.DetectEmscripten())

            # 4) Zig wrappers (if installed).
            for zig_name, zig_tc in self.DetectZigToolchains().items():
                self._AddToolchainIfValid(toolchains, zig_tc)

            # 5) Compatibility aliases used by existing workspaces/examples.
            if "zig-linux-x86_64" in toolchains and "zig-linux-x64" not in toolchains:
                toolchains["zig-linux-x64"] = self._CloneToolchainWithName(toolchains["zig-linux-x86_64"], "zig-linux-x64")
            if "zig-windows-x86_64" in toolchains and "zig-windows-x64" not in toolchains:
                toolchains["zig-windows-x64"] = self._CloneToolchainWithName(toolchains["zig-windows-x86_64"], "zig-windows-x64")

            self._detected = toolchains
            return toolchains
        finally:
            os.environ["PATH"] = original_path
            if old_compilers_env is None:
                os.environ.pop("JENGA_COMPILERS_DIR", None)
            else:
                os.environ["JENGA_COMPILERS_DIR"] = old_compilers_env

    def ResolveForTarget(self,
                         targetOs: TargetOS,
                         targetArch: TargetArch,
                         targetEnv: Optional[TargetEnv] = None,
                         prefer: Optional[List[str]] = None,
                         exclude: Optional[List[str]] = None) -> Optional[str]:
        """Trouve la meilleure toolchain pour une cible donnÃ©e."""
        exclude_set = {str(name).strip().lower() for name in (exclude or []) if str(name).strip()}
        use_cache = not exclude_set
        cache_key = (targetOs, targetArch, targetEnv)
        if use_cache and cache_key in self._cache:
            return self._cache[cache_key]
        candidates = []
        for name, tc in self._detected.items():
            if str(name).strip().lower() in exclude_set:
                continue
            if tc.targetOs == targetOs and tc.targetArch == targetArch:
                if targetEnv is None or tc.targetEnv == targetEnv:
                    candidates.append(name)
        if not candidates:
            for name, tc in self._detected.items():
                if str(name).strip().lower() in exclude_set:
                    continue
                if tc.targetOs == targetOs:
                    candidates.append(name)
        if not candidates:
            if use_cache:
                self._cache[cache_key] = None
            return None
        if prefer:
            for pref in prefer:
                if pref in candidates:
                    if use_cache:
                        self._cache[cache_key] = pref
                    return pref
        selected = candidates[0]
        if use_cache:
            self._cache[cache_key] = selected
        return selected

    def GetToolchain(self, name: str) -> Optional[Toolchain]:
        return self._detected.get(name)

    def AddToolchain(self, toolchain: Toolchain) -> None:
        self._detected[toolchain.name] = toolchain

    def ClearCache(self) -> None:
        self._cache.clear()