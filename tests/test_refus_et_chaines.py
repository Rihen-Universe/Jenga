#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_refus_et_chaines.py
==============================
AUTEUR : TEUGUIA TADJUIDJE Rodolf Séderis — Rihen

Banc de 2.8.17 : « quel compilateur, quelle bibliotheque C++ », et les refus
dits AVANT de compiler.

Deux mesures du 2026-10-08, sur le projet d'un cours :
  - un kit compile avec le clang de MSYS2 (libstdc++), lie par llvm-mingw
    (libc++) : 600 lignes « undefined symbol: std::__cxx11::... », sans un mot
    sur la cause ;
  - un kit qui ne contenait que Release, un projet construit en Debug : le kit
    ne branchait AUCUNE bibliotheque, 230 « undefined reference ».

Ce banc tient :
  (d) le diagnostic d'un lien manque nomme la bibliotheque C++ attendue ;
  (s) la sonde lit la bibliotheque C++ d'un compilateur ;
  (b) builderror() refuse de construire, sous son filtre seulement ;
  (k) kitrequire() refuse une chaine dont la bibliotheque C++ differe ;
  (a) la bibliotheque C++ d'un kit se lit dans ses archives ;
  (g) un kit Release seul, construit en Debug : UN refus, lisible ; en Release : il lie.

Usage :
  python -m pytest tests/test_refus_et_chaines.py -v
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from Jenga.Commands.Kit import KitCommand
from Jenga.Core.Builder import Builder
from Jenga.Core.Toolchains import ToolchainManager

_CXX = shutil.which("clang++") or shutil.which("g++")
_AVEC_COMPILATEUR = pytest.mark.skipif(_CXX is None, reason="aucun compilateur C++ GNU (clang++/g++) dans le PATH")

# ── les deux sorties reelles du 2026-10-08 (extraits) ─────────────────────────
LLD_LIBSTDCXX = """\
ld.lld: error: undefined symbol: std::__cxx11::basic_string<char, std::char_traits<char>, std::allocator<char>>::_M_create(unsigned long long&, unsigned long long)
>>> referenced by NKRHI.lib(src_NKRHI_Vulkan_NkVulkanDevice.obj):(nkentseu::NkVulkanDevice::CreateShader(nkentseu::NkShaderDesc const&))
>>> referenced by NKSL.lib(src_NKSL_ShaderConvert_NkShaderConvert.obj):(nkentseu::NkShaderFileResolver::BasePath(nkentseu::NkString const&))
>>> referenced 593 more times
ld.lld: error: undefined symbol: std::__throw_length_error(char const*)
>>> referenced by NKGLSlang.lib(glslang_MachineIndependent_ShaderLang.obj):(glslang::TShader::preprocess())
clang-18: error: linker command failed with exit code 1 (use -v to see invocation)
"""
GNU_SANS_BIBLIOTHEQUES = """\
C:/msys64/ucrt64/bin/ld: C:\\P\\Build\\Obj\\Debug-Windows\\App\\src_main.obj: in function `WinMain':
C:\\P\\Kit\\include/NKWindow/EntryPoints/NkWindowsDesktop.h:64:(.text+0x13a): undefined reference to `nkentseu::NkString::NkString(unsigned long long, char)'
C:/msys64/ucrt64/bin/ld: C:\\P\\src/main.cpp:38:(.text+0x4a3): undefined reference to `nkentseu::NkWindow::NkWindow(nkentseu::NkWindowConfig const&)'
"""
GNU_LIBCXX = """\
C:/msys64/ucrt64/bin/ld: Moteur.a(rendu.o):rendu.cpp:(.text+0x40): undefined reference to `std::__1::basic_string<char, std::__1::char_traits<char>, std::__1::allocator<char> >::~basic_string()'
collect2.exe: error: ld returned 1 exit status
"""


# ── (d) le diagnostic d'un lien manque ────────────────────────────────────────
def test_d1_lld_output_names_libstdcxx_and_the_archives():
    d = Builder.DiagnostiquerLien(LLD_LIBSTDCXX)
    assert d is not None and d["attendue"] == "libstdc++"
    assert d["archives"][:3] == ["NKRHI.lib", "NKSL.lib", "NKGLSlang.lib"]


def test_d2_gnu_ld_output_names_libcxx():
    d = Builder.DiagnostiquerLien(GNU_LIBCXX)
    assert d is not None and d["attendue"] == "libc++" and d["archives"] == ["Moteur.a"]


def test_d3_missing_libraries_are_not_called_a_stdlib_mix():
    # 230 symboles du moteur introuvables : ce n'est PAS un melange de bibliotheques C++.
    assert Builder.DiagnostiquerLien(GNU_SANS_BIBLIOTHEQUES) is None
    assert Builder.DiagnostiquerLien("") is None


def test_d4_both_families_missing_is_left_undecided():
    assert Builder.DiagnostiquerLien(LLD_LIBSTDCXX + GNU_LIBCXX) is None


def test_d5_clang_and_gcc_objects_mixed_are_named():
    sortie = ("C:/msys64/ucrt64/bin/ld.exe: Kit/lib/NKRHI.lib(src_NkDeviceFactory.obj):NkDeviceFactory.cpp:(.bss+0x0): "
              "multiple definition of `guard variable for nkentseu::math::NkRandom::Instance()::singletonInstance'; "
              "Build/Obj/src_main.obj:NkRandom.h:82: first defined here\ncollect2.exe: error: ld returned 1 exit status\n")
    d = Builder.DiagnostiquerLien(sortie)
    assert d is not None and d.get("melange") == "compilateurs" and d["archives"] == ["NKRHI.lib"]


# ── (s) la sonde de la bibliotheque C++ ───────────────────────────────────────
def test_s1_macros_tell_the_library():
    assert ToolchainManager.StdlibDepuisMacros("#define _LIBCPP_VERSION 180100\n") == "libc++"
    assert ToolchainManager.StdlibDepuisMacros("#define __GLIBCXX__ 20250425\n") == "libstdc++"
    assert ToolchainManager.StdlibDepuisMacros("#define _MSVC_STL_VERSION 143\n") == "msvc-stl"
    assert ToolchainManager.StdlibDepuisMacros("#define __clang__ 1\n") == ""


@_AVEC_COMPILATEUR
def test_s2_the_host_compiler_answers(tmp_path, monkeypatch):
    monkeypatch.setenv("JENGA_SONDES_SANS_CACHE", "1")
    assert ToolchainManager.StdlibOf(_CXX) in ("libc++", "libstdc++")
    assert ToolchainManager.StdlibOf(str(tmp_path / "absent.exe")) == ""


@pytest.mark.skipif(sys.platform != "win32", reason="chaines GNU de Windows")
def test_s3_each_installed_compiler_has_its_own_named_toolchain():
    chaines = ToolchainManager.DetectWindowsGnuInstallations()
    noms = [tc.name for tc in chaines]
    assert len(noms) == len(set(noms))  # une chaine, un nom
    for tc in chaines:
        assert Path(tc.cxxPath).is_file() and tc.name != "clang-mingw"
        # le nom dit l'installation : il se retrouve dans le chemin
        if tc.name.startswith("msys2-"):
            assert tc.name.split("-")[1] in str(tc.cxxPath).lower()
    ucrt = Path(r"C:\msys64\ucrt64\bin\clang++.exe")
    if ucrt.is_file():
        assert "msys2-ucrt64-clang" in noms


# ── (a) la bibliotheque C++ d'un kit, lue dans ses archives ───────────────────
def test_a1_archives_tell_their_library(tmp_path):
    d = tmp_path / "lib"
    d.mkdir()
    assert KitCommand._StdlibOfArchives(d) == ""
    (d / "a.lib").write_bytes(b"!<arch>\n" + b"\0" * 64 + b"_ZNSt3__112basic_stringIcEE" + b"\0" * 8)
    assert KitCommand._StdlibOfArchives(d) == "libc++"
    (d / "a.lib").write_bytes(b"!<arch>\n_ZNSt7__cxx1112basic_stringIcEE\0")
    assert KitCommand._StdlibOfArchives(d) == "libstdc++"
    (d / "b.lib").write_bytes(b"!<arch>\n_ZNKSt3__16vectorIiE4sizeEv\0")
    assert KitCommand._StdlibOfArchives(d) == "mixte"
    (d / "a.lib").write_bytes(b"!<arch>\nnk_c_seulement\0")
    (d / "b.lib").write_bytes(b"")
    assert KitCommand._StdlibOfArchives(d) == ""


def test_a2_archives_tell_their_compiler_family(tmp_path):
    d = tmp_path / "lib"
    d.mkdir()
    assert KitCommand._FamilyOfArchives(d) == ""
    (d / "a.lib").write_bytes(b"!<arch>\n.text\x00.llvm_addrsig\x00")
    assert KitCommand._FamilyOfArchives(d) == "clang"
    (d / "a.lib").write_bytes(b"!<arch>\n.rdata$zzz\x00GCC: (Rev2, Built by MSYS2 project) 15.1.0\x00")
    assert KitCommand._FamilyOfArchives(d) == "gcc"
    (d / "b.lib").write_bytes(b"!<arch>\n.llvm_addrsig\x00")
    assert KitCommand._FamilyOfArchives(d) == "mixte"


def test_s4_a_compiler_runs_with_its_own_folder_first_in_path():
    sep = os.pathsep
    autre, sien = os.path.join(os.sep, "autre", "bin"), os.path.join(os.sep, "sien", "bin")
    cxx = os.path.join(os.path.abspath(sien), "g++.exe")
    sien_abs = os.path.dirname(cxx)
    p = ToolchainManager.PathAvecLeCompilateurEnTete(cxx, autre + sep + sien_abs + sep + "reste")
    assert p.split(sep) == [sien_abs, autre, "reste"]  # le sien d'abord, une seule fois
    assert ToolchainManager.PathAvecLeCompilateurEnTete(cxx, p) == p  # deja en tete : inchange
    assert ToolchainManager.PathAvecLeCompilateurEnTete("g++", autre) == autre  # un nom nu ne dit pas ou


# ── les workspaces d'essai ────────────────────────────────────────────────────
def _jenga(root: Path, *args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    env["PYTHONIOENCODING"] = "utf-8"
    extra = ["--no-daemon"] if args and args[0] == "build" else []
    return subprocess.run([sys.executable, "-m", "Jenga", *args, *extra], cwd=str(root), env=env,
                          capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600)


def _sortie(r: subprocess.CompletedProcess) -> str:
    import re
    return re.sub(r"\x1b\[[0-9;]*m", "", (r.stdout or "") + (r.stderr or ""))


APP = """from Jenga import *

with workspace("W"):
    configurations(["Debug", "Release"])

    with project("App"):
        consoleapp()
        language("C++")
        files(["src/**.cpp"])
{corps}
"""


def _app(tmp: Path, corps: str) -> Path:
    (tmp / "src").mkdir(parents=True, exist_ok=True)
    (tmp / "src" / "main.cpp").write_text("int main() { return 0; }\n", encoding="utf-8")
    (tmp / "W.jenga").write_text(APP.format(corps=corps), encoding="utf-8")
    return tmp


# ── (b) builderror() ──────────────────────────────────────────────────────────
@_AVEC_COMPILATEUR
def test_b1_builderror_refuses_under_its_filter_only(tmp_path):
    root = _app(tmp_path, '        with filter("configurations:Debug"):\n'
                          '            builderror("Pas de Debug pour App : essayez Release.")\n')
    r = _jenga(root, "build", "--config", "Debug")
    s = _sortie(r)
    assert r.returncode != 0, s
    assert "Pas de Debug pour App" in s and "Build Refused" in s
    assert "Compiled" not in s  # dit AVANT de compiler
    r2 = _jenga(root, "build", "--config", "Release")
    s2 = _sortie(r2)
    assert "Build Refused" not in s2 and "Pas de Debug" not in s2, s2
    assert r2.returncode == 0, s2


def test_b2_builderror_outside_a_project_is_refused_by_the_dsl(tmp_path):
    (tmp_path / "W.jenga").write_text(
        'from Jenga import *\n\nwith workspace("W"):\n    configurations(["Debug"])\n    builderror("hors projet")\n',
        encoding="utf-8")
    r = _jenga(tmp_path, "info")
    assert r.returncode != 0 and "builderror" in _sortie(r)


# ── (k) kitrequire() ──────────────────────────────────────────────────────────
@_AVEC_COMPILATEUR
def test_k1_a_kit_built_against_another_stdlib_is_refused_before_compiling(tmp_path):
    autre = "libc++" if ToolchainManager.StdlibOf(_CXX) == "libstdc++" else "libstdc++"
    root = _app(tmp_path, f'        kitrequire("Faux", stdlib="{autre}")\n')
    r = _jenga(root, "build", "--config", "Debug")
    s = _sortie(r)
    assert r.returncode != 0, s
    assert "Le kit Faux a ete compile avec " + autre in s and "Compiled" not in s


@_AVEC_COMPILATEUR
def test_k2_same_stdlib_or_another_system_builds(tmp_path):
    meme = ToolchainManager.StdlibOf(_CXX)
    ailleurs = "Linux" if sys.platform == "win32" else "Windows"
    root = _app(tmp_path, f'        kitrequire("Bon", stdlib="{meme}")\n'
                          f'        kitrequire("Ailleurs", stdlib="une-autre", system="{ailleurs}")\n')
    r = _jenga(root, "build", "--config", "Debug")
    assert r.returncode == 0 and "Build Refused" not in _sortie(r), _sortie(r)


# ── (g) un kit qui ne sert pas toutes les configurations ──────────────────────
MOTEUR = """from Jenga import *

with workspace("Moteur"):
    configurations(["Debug", "Release"])

    with project("Outil"):
        staticlib()
        language("C++")
        files(["src/**.cpp"])
        includedirs(["include"])
"""
CLIENT = """from Jenga import *

with workspace("Client"):
    configurations(["Debug", "Release"])
    useconfig("Kit/Kit.jenga")

    with project("App"):
        consoleapp()
        language("C++")
        files(["src/**.cpp"])
        usekit()
"""


@_AVEC_COMPILATEUR
def test_g1_a_release_only_kit_refuses_debug_clearly_and_links_in_release(tmp_path):
    moteur = tmp_path / "moteur"
    (moteur / "src").mkdir(parents=True)
    (moteur / "include").mkdir()
    (moteur / "include" / "outil.h").write_text("#pragma once\n#include <string>\nstd::string Bonjour();\n", encoding="utf-8")
    (moteur / "src" / "outil.cpp").write_text('#include "outil.h"\nstd::string Bonjour() { return "bonjour"; }\n', encoding="utf-8")
    (moteur / "Moteur.jenga").write_text(MOTEUR, encoding="utf-8")
    r = _jenga(moteur, "build", "--config", "Release")
    assert r.returncode == 0, _sortie(r)

    client = tmp_path / "client"
    (client / "src").mkdir(parents=True)
    (client / "src" / "main.cpp").write_text(
        '#include "outil.h"\nint main() { return Bonjour().size() == 7 ? 0 : 1; }\n', encoding="utf-8")
    rk = _jenga(moteur, "kit", "--target", "Outil", "--config", "Release", "--name", "Kit",
                "--output", str(client / "Kit"))
    sk = _sortie(rk)
    assert rk.returncode == 0, sk
    assert "ne sert que Release" in sk  # dit a celui qui fabrique le kit
    texte = (client / "Kit" / "Kit.jenga").read_text(encoding="utf-8")
    assert "KIT_STDLIB" in texte and 'globals().get("builderror")' in texte
    assert ToolchainManager.StdlibOf(_CXX) in texte  # la bibliotheque C++ lue dans l'archive

    (client / "Client.jenga").write_text(CLIENT, encoding="utf-8")
    rd = _jenga(client, "build", "--config", "Debug")
    sd = _sortie(rd)
    assert rd.returncode != 0, sd
    assert "ne contient pas de bibliotheques pour Debug-" in sd and "il contient : Release" in sd
    assert "Compiled" not in sd and "undefined" not in sd  # UN refus, pas 230 symboles
    rr = _jenga(client, "build", "--config", "Release")
    assert rr.returncode == 0 and "Build Refused" not in _sortie(rr), _sortie(rr)


if __name__ == "__main__":
    sys.exit(subprocess.run([sys.executable, "-m", "pytest", __file__, "-v", "--tb=short"], cwd=str(ROOT)).returncode)
