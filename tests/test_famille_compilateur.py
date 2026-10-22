# AUTEUR : TEUGUIA TADJUIDJE Rodolf Séderis — Rihen
"""
(2.10.0) La famille du compilateur suit la chaine COURANTE du builder.

Jenga 2.9.0 la figeait dans __init__ (LinuxBuilder.is_gcc / is_clang, MacOSBuilder.is_apple_clang,
WindowsBuilder.is_msvc / is_clang / is_mingw / is_clang_cl), calculee sur la chaine choisie
AUTOMATIQUEMENT. Build.py re-choisit pourtant la chaine apres __init__ quand `--toolchain` est donne, et
BuildProject la change pour un projet qui a la sienne. Constat du 22/10/2026 (essai publier-kits
39758756603, runner Ubuntu avec clang ET gcc) : `--toolchain host-gcc` envoyait `-include-pch` a gcc,
« fatal error: -pch: No such file or directory » sur chaque fichier.

Aucun compilateur n'est lance : on lit ce que le builder decide. Le banc reel (WSL, NKPlatform) est dans
l'etat de l'agent moteur-retours. Contre-epreuve a l'ecriture : sur le code de la v2.9.0 (famille figee),
les cas « la chaine change apres coup » tombent.
"""
import importlib
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pytest
import Jenga.Core.Api as Api
from Jenga.Core.Api import CompilerFamily, Project, ProjectKind, Language, TargetOS, TargetArch, TargetEnv, Toolchain, Workspace


def _reset():
    Api._currentWorkspace = None
    Api._currentProject = None
    Api._currentToolchain = None
    Api._currentFilter = None


def _chaine(nom, fam, tos, tarch, tenv=None, cc="cc"):
    tc = Toolchain(name=nom, compilerFamily=fam, ccPath=cc, cxxPath=cc + "++", arPath="ar", targetOs=tos, targetArch=tarch)
    if tenv is not None:
        tc.targetEnv = tenv
    return tc


def _builder(module, classe, tc, plat, tos, tarch):
    """Un builder construit par __init__ avec la chaine AUTOMATIQUE `tc` (comme Build.py le fait d'abord)."""
    cls = getattr(importlib.import_module(module), classe)
    _reset()
    wks = Workspace(name="W", location=tempfile.mkdtemp())
    wks.toolchains[tc.name] = tc
    wks.defaultToolchain = tc.name
    b = cls.__new__(cls)
    b.workspace, b.config, b.platform = wks, "Debug", plat
    b.targetOs, b.targetArch, b.targetEnv = tos, tarch, None
    b.verbose, b.action, b.options, b.toolchain = False, "build", [], tc
    b.jobs, b._expander, b._lastResult = 1, None, None
    # Ce que faisait __init__ en 2.9.0 : figer la famille. En 2.10.0 ces noms sont des proprietes, qu'on ne
    # pose pas (le banc reste ainsi valable sur les deux versions pour la contre-epreuve).
    if not isinstance(getattr(cls, "is_gcc", None), property) and classe == "LinuxBuilder":
        b.is_gcc = tc.compilerFamily == CompilerFamily.GCC
        b.is_clang = tc.compilerFamily in (CompilerFamily.CLANG, CompilerFamily.APPLE_CLANG)
    if not isinstance(getattr(cls, "is_apple_clang", None), property) and classe == "MacOSBuilder":
        b.is_apple_clang = tc.compilerFamily == CompilerFamily.APPLE_CLANG
    if not isinstance(getattr(cls, "is_msvc", None), property) and classe == "WindowsBuilder":
        b.is_msvc = tc.compilerFamily == CompilerFamily.MSVC
        b.is_clang = tc.compilerFamily == CompilerFamily.CLANG
        b.is_mingw = ((tc.compilerFamily == CompilerFamily.GCC and tc.targetOs == TargetOS.WINDOWS) or
                      (tc.compilerFamily == CompilerFamily.CLANG and tc.targetEnv == TargetEnv.MINGW))
        b.is_clang_cl = b.is_clang and "clang-cl" in str(tc.ccPath).lower()
    return b


def _projet_avec_pch():
    p = Project(name="P")
    p.kind = ProjectKind.STATIC_LIB
    p.language = Language.CPP
    p._jengaPchFile = "/tmp/obj/P.pch"
    p._jengaPchHeaderResolved = "/src/pch/pch.h"
    return p


class TestLinux:
    LIN = ("Jenga.Core.Builders.Linux", "LinuxBuilder")

    def test_chaine_auto_clang_puis_toolchain_gcc(self):
        """Le cas du runner : choisie seule, host-clang ; puis `--toolchain host-gcc`."""
        clang = _chaine("host-clang", CompilerFamily.CLANG, TargetOS.LINUX, TargetArch.X86_64, cc="clang")
        gcc = _chaine("host-gcc", CompilerFamily.GCC, TargetOS.LINUX, TargetArch.X86_64, cc="gcc")
        b = _builder(*self.LIN, clang, "Linux-x86_64", TargetOS.LINUX, TargetArch.X86_64)
        assert b.is_clang and not b.is_gcc
        b.toolchain = gcc  # ce que fait Build.py (_ResolveToolchain) apres __init__
        assert b.is_gcc and not b.is_clang
        f = b._GetCompilerFlags(_projet_avec_pch())
        assert "-include-pch" not in f, f"gcc recoit encore -include-pch : {f}"
        assert "-include" in f and "/src/pch/pch.h" in f, f"gcc doit inclure l'en-tete du PCH : {f}"

    def test_chaine_auto_gcc_puis_toolchain_clang(self):
        """L'inverse : la famille suit aussi dans l'autre sens."""
        clang = _chaine("host-clang", CompilerFamily.CLANG, TargetOS.LINUX, TargetArch.X86_64, cc="clang")
        gcc = _chaine("host-gcc", CompilerFamily.GCC, TargetOS.LINUX, TargetArch.X86_64, cc="gcc")
        b = _builder(*self.LIN, gcc, "Linux-x86_64", TargetOS.LINUX, TargetArch.X86_64)
        b.toolchain = clang
        f = b._GetCompilerFlags(_projet_avec_pch())
        assert "-include-pch" in f, f"clang doit recevoir son PCH : {f}"

    def test_temoin_sans_changement(self):
        """Temoin : sans changement de chaine, rien ne change (gcc reste gcc)."""
        gcc = _chaine("host-gcc", CompilerFamily.GCC, TargetOS.LINUX, TargetArch.X86_64, cc="gcc")
        b = _builder(*self.LIN, gcc, "Linux-x86_64", TargetOS.LINUX, TargetArch.X86_64)
        f = b._GetCompilerFlags(_projet_avec_pch())
        assert "-include-pch" not in f and "-include" in f


class TestMacosEtWindows:
    def test_macos_apple_clang_suit_la_chaine(self):
        apple = _chaine("host-apple-clang", CompilerFamily.APPLE_CLANG, TargetOS.MACOS, TargetArch.ARM64, cc="clang")
        llvm = _chaine("host-clang", CompilerFamily.CLANG, TargetOS.MACOS, TargetArch.ARM64, cc="clang")
        b = _builder("Jenga.Core.Builders.Macos", "MacOSBuilder", apple, "macOS-arm64", TargetOS.MACOS, TargetArch.ARM64)
        assert b.is_apple_clang
        b.toolchain = llvm
        assert not b.is_apple_clang

    def test_windows_msvc_puis_mingw(self):
        msvc = _chaine("msvc", CompilerFamily.MSVC, TargetOS.WINDOWS, TargetArch.X86_64, cc="cl.exe")
        mingw = _chaine("clang-mingw", CompilerFamily.CLANG, TargetOS.WINDOWS, TargetArch.X86_64, TargetEnv.MINGW, cc="clang.exe")
        b = _builder("Jenga.Core.Builders.Windows", "WindowsBuilder", msvc, "Windows-x86_64", TargetOS.WINDOWS, TargetArch.X86_64)
        assert b.is_msvc and not b.is_mingw
        b.toolchain = mingw
        assert not b.is_msvc and b.is_mingw and b.is_clang and not b.is_clang_cl

    def test_windows_clang_cl(self):
        mingw = _chaine("clang-mingw", CompilerFamily.CLANG, TargetOS.WINDOWS, TargetArch.X86_64, TargetEnv.MINGW, cc="clang.exe")
        clangcl = _chaine("clang-cl", CompilerFamily.CLANG, TargetOS.WINDOWS, TargetArch.X86_64, cc="C:/LLVM/bin/clang-cl.exe")
        b = _builder("Jenga.Core.Builders.Windows", "WindowsBuilder", mingw, "Windows-x86_64", TargetOS.WINDOWS, TargetArch.X86_64)
        b.toolchain = clangcl
        assert b.is_clang_cl and not b.is_mingw
