#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_filtered_variables.py
================================
AUTEUR : TEUGUIA TADJUIDJE Rodolf Séderis — Rihen

Banc de `%{Projet.location}` (2.6.2) — mesure par l'agent Noge sur Nkentseu le
2026-09-04 : dans une sous-suite de NKSerialization, `%{NKMath.location}`
« reste relatif ou vide ». Deux mecanismes, deux formes :
  1. sous `with filter(...)`, `includedirs()` va dans `_filteredIncludeDirs`,
     que l'expansion du Loader sautait (attribut prive) et que le Builder
     fusionnait sans expanser : le compilateur recevait le placeholder
     LITTERAL (`-I%{NKMath.location}/src`) — la forme « vide » ;
  2. en espace mono-fichier, `%{A.location}` etait expanse AVANT que la
     location de A soit rendue absolue : `libA/src`, relatif, colle ensuite
     a la location du lecteur (`<wks>/libB/libA/src`) — la forme « relatif ».

Trois etages : le Loader (les deux formes), le Builder sans Loader
(`ResolveProjectPath` expanse avant de resoudre), et un espace de travail
reel compile (saute, en le disant, sans compilateur) : une sous-suite sous
filtre inclut un en-tete qui n'existe QUE sous `%{Autre.location}/include`,
et `jenga test` la lance ; mutation — l'en-tete deplace — rouge.

Usage :
  python -m pytest tests/test_filtered_variables.py -v
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pytest
import Jenga.Core.Api as Api
from Jenga.Core.Api import (
    Workspace, Project, Toolchain, ProjectKind, TargetOS, TargetArch, CompilerFamily,
)
from Jenga.Core.Loader import Loader


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _abs(root: Path, *parts: str) -> str:
    return str((root / Path(*parts)).resolve())


def _norm(p: str) -> str:
    return str(Path(p).resolve())


# ===========================================================================
# 1. Par le Loader — les deux formes
# ===========================================================================

_FILTER = "system:Windows || system:Linux || system:macOS"

_MAIN_INCLUDED = """\
from Jenga import *
with workspace("W"):
    configurations(["Debug"])
    with unitest() as u:
        u.Precompiled()
    with include("A/A.jenga"):
        pass
    with include("B/B.jenga"):
        pass
"""

_A_INCLUDED = """\
from Jenga import *
with project("A"):
    staticlib()
    location(".")
    files(["src/**.cpp"])
"""

_B_INCLUDED = """\
from Jenga import *
with project("B"):
    staticlib()
    location(".")
    files(["src/**.cpp"])
    includedirs(["%{A.location}/src"])
    with test():
        testfiles(["tests/t_main.cpp"])
    with test("Sub"):
        testfiles(["tests/t_sub.cpp"])
        testownmain()
        includedirs(["%{A.location}/sub_nofilter"])
    with filter("FILTER"):
        with test("SubF"):
            testfiles(["tests/t_subf.cpp"])
            testownmain()
            includedirs(["%{A.location}/sub_filter"])
            libdirs(["%{A.location}/lib_filter"])
""".replace("FILTER", _FILTER)

_MONO = """\
from Jenga import *
with workspace("W"):
    configurations(["Debug"])
    with project("A"):
        staticlib()
        location("libA")
        files(["src/**.cpp"])
    with project("B"):
        staticlib()
        location("libB")
        files(["src/**.cpp"])
        includedirs(["%{A.location}/src"])
        with filter("FILTER"):
            includedirs(["%{A.location}/inc_f"])
""".replace("FILTER", _FILTER)


class TestLoaderResolvesNamedLocation:

    @pytest.fixture()
    def included(self, tmp_path):
        _write(tmp_path / "W.jenga", _MAIN_INCLUDED)
        _write(tmp_path / "A" / "A.jenga", _A_INCLUDED)
        _write(tmp_path / "B" / "B.jenga", _B_INCLUDED)
        wks = Loader(verbose=False).LoadWorkspace(str(tmp_path / "W.jenga"))
        assert wks is not None
        return tmp_path, wks

    def test_sub_suite_under_a_filter_gets_an_absolute_path(self, included):
        root, wks = included
        sub = wks.projects["B_SubF_Tests"]
        dirs = sub._filteredIncludeDirs[_FILTER]
        assert dirs == [_abs(root, "A") + "/sub_filter"], dirs
        assert all("%{" not in d for d in dirs)
        assert sub._filteredLibDirs[_FILTER] == [_abs(root, "A") + "/lib_filter"]

    def test_sub_suite_without_filter_and_main_suite_unchanged(self, included):
        root, wks = included
        assert _abs(root, "A") + "/sub_nofilter" in wks.projects["B_Sub_Tests"].includeDirs
        assert _abs(root, "A") + "/src" in wks.projects["B_Tests"].includeDirs
        assert _abs(root, "A") + "/src" in wks.projects["B"].includeDirs

    def test_mono_file_relative_locations_read_absolute(self, tmp_path):
        _write(tmp_path / "W.jenga", _MONO)
        (tmp_path / "libA" / "src").mkdir(parents=True)
        (tmp_path / "libB" / "src").mkdir(parents=True)
        wks = Loader(verbose=False).LoadWorkspace(str(tmp_path / "W.jenga"))
        assert wks is not None
        a, b = wks.projects["A"], wks.projects["B"]
        assert _norm(a.location) == _abs(tmp_path, "libA")
        # Avant 2.6.2 : 'libA/src' — relatif, colle ensuite a libB.
        assert b.includeDirs == [_abs(tmp_path, "libA") + "/src"], b.includeDirs
        assert b._filteredIncludeDirs[_FILTER] == [_abs(tmp_path, "libA") + "/inc_f"]

    def test_a_build_time_variable_is_left_for_the_builder(self, tmp_path):
        _write(tmp_path / "W.jenga", _MONO.replace(
            'includedirs(["%{A.location}/inc_f"])',
            'includedirs(["%{A.location}/inc_f", "%{wks.location}/gen/%{cfg.buildcfg}"])'))
        wks = Loader(verbose=False).LoadWorkspace(str(tmp_path / "W.jenga"))
        dirs = wks.projects["B"]._filteredIncludeDirs[_FILTER]
        assert dirs[1].startswith(str(tmp_path.resolve()))
        assert dirs[1].endswith("/gen/%{cfg.buildcfg}")   # cfg.* n'existe qu'a la construction


# ===========================================================================
# 2. Par le Builder, sans Loader : ResolveProjectPath expanse avant de resoudre
# ===========================================================================

def _builder(root: Path):
    from Jenga.Core.Builder import Builder

    class _FakeBuilder(Builder):
        def Compile(self, *a): pass
        def Link(self, *a): pass
        def GetOutputExtension(self, *a): return ""
        def GetObjectExtension(self): return ".o"
        def GetModuleFlags(self, *a): return []

    Api.resetstate()
    wks = Workspace(name="W", location=str(root))
    tc = Toolchain(name="stub", compilerFamily=CompilerFamily.CLANG,
                   ccPath="clang", cxxPath="clang++",
                   targetOs=TargetOS.WINDOWS, targetArch=TargetArch.X86_64)
    wks.toolchains["stub"] = tc
    wks.defaultToolchain = "stub"
    a = Project(name="A"); a.kind = ProjectKind.STATIC_LIB; a.location = str(root / "libA")
    b = Project(name="B"); b.kind = ProjectKind.STATIC_LIB; b.location = str(root / "libB")
    b._filteredIncludeDirs["system:Windows"] = ["%{A.location}/src"]
    b.includeDirs = ["%{A.location}/include", "local"]
    wks.projects = {"A": a, "B": b}
    return _FakeBuilder(workspace=wks, config="Debug", platform="Windows-x86_64",
                        targetOs=TargetOS.WINDOWS, targetArch=TargetArch.X86_64,
                        verbose=False)


class TestBuilderResolvesNamedLocation:
    def test_resolve_project_path_expands_then_resolves(self, tmp_path):
        b = _builder(tmp_path)
        proj = b.workspace.projects["B"]
        assert _norm(b.ResolveProjectPath(proj, "%{A.location}/include")) == _abs(tmp_path, "libA", "include")
        assert _norm(b.ResolveProjectPath(proj, "local")) == _abs(tmp_path, "libB", "local")

    def test_filtered_dirs_merged_then_resolved(self, tmp_path):
        b = _builder(tmp_path)
        proj = b.workspace.projects["B"]
        b._ApplyProjectFilters(proj)
        assert "%{A.location}/src" in proj.includeDirs        # fusionne tel quel...
        resolved = [_norm(b.ResolveProjectPath(proj, d)) for d in proj.includeDirs]
        assert _abs(tmp_path, "libA", "src") in resolved       # ... et resolu au moment de l'usage
        assert all("%{" not in r for r in resolved)

    def test_unknown_project_is_left_intact_not_invented(self, tmp_path):
        b = _builder(tmp_path)
        proj = b.workspace.projects["B"]
        assert b.ResolveProjectPath(proj, "%{Nobody.location}/src") == "%{Nobody.location}/src"


# ===========================================================================
# 3. Espace de travail reel : la sous-suite sous filtre compile ET se lance
# ===========================================================================

_CXX = shutil.which("clang++") or shutil.which("g++") or shutil.which("cl")

_REAL = """\
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from Jenga import *
from Jenga.GlobalToolchains import *

with workspace("LocBench"):
    configurations(["Debug"])
    targetoses([TargetOS.WINDOWS, TargetOS.LINUX, TargetOS.MACOS])
    targetarchs([TargetArch.X86_64, TargetArch.ARM64])
    RegisterJengaGlobalToolchains()

    with unitest() as u:
        u.Compile(cxxflags=["-fexceptions"])

    with include("Far/Far.jenga"):
        pass
    with include("Near/Near.jenga"):
        pass
"""

_FAR = """\
from Jenga import *
with project("Far"):
    staticlib()
    language("C++")
    cppdialect("C++17")
    location(".")
    files(["src/**.cpp"])
    includedirs(["include"])
"""

_NEAR = """\
from Jenga import *
with project("Near"):
    staticlib()
    language("C++")
    cppdialect("C++17")
    location(".")
    files(["src/**.cpp"])
    includedirs(["include"])
    with filter("FILTER"):
        with test("Reach"):
            testfiles(["tests/reach_main.cpp"])
            testownmain()
            # Far n'est PAS une dependance de Near : la sous-suite l'ajoute,
            # par son nom, sous filtre — la forme exacte de NKSerialization.
            includedirs(["%{Far.location}/include"])
            dependson(["Far"])
            links(["Far"])
""".replace("FILTER", _FILTER)

_REACH_MAIN = """\
#include <cstdio>
#include "near.h"
#include "far.h"      // n'existe QUE sous %{Far.location}/include

int main() {
    int v = near_add(1, 2) + far_mul(2, 3);
    std::printf("REACH RAN %d\\n", v);
    return v == 9 ? 0 : 1;
}
"""


def _make_real(root: Path) -> None:
    _write(root / "Far" / "include" / "far.h", "#pragma once\nint far_mul(int a, int b);\n")
    _write(root / "Far" / "src" / "far.cpp", '#include "far.h"\nint far_mul(int a, int b) { return a * b; }\n')
    _write(root / "Near" / "include" / "near.h", "#pragma once\nint near_add(int a, int b);\n")
    _write(root / "Near" / "src" / "near.cpp", '#include "near.h"\nint near_add(int a, int b) { return a + b; }\n')
    _write(root / "Near" / "tests" / "reach_main.cpp", _REACH_MAIN)
    _write(root / "Far" / "Far.jenga", _FAR)
    _write(root / "Near" / "Near.jenga", _NEAR)
    _write(root / "LocBench.jenga", _REAL)


def _jenga(root: Path, *args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(
        [sys.executable, "-m", "Jenga", *args, "--no-daemon",
         "--jenga-file", str(root / "LocBench.jenga")],
        cwd=str(root), env=env, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=600,
    )


@pytest.mark.skipif(_CXX is None, reason="aucun compilateur C++ (clang++/g++/cl) dans le PATH")
class TestRealWorkspace:

    def test_sub_suite_under_filter_reaches_the_named_location(self, tmp_path):
        _make_real(tmp_path)
        r = _jenga(tmp_path, "test", "--project", "Near_Reach_Tests")
        out = r.stdout + r.stderr
        assert r.returncode == 0, out
        assert "REACH RAN 9" in out
        assert "%{Far.location}" not in out

    def test_mutation_header_moved_turns_red(self, tmp_path):
        _make_real(tmp_path)
        # L'en-tete quitte %{Far.location}/include : si l'include est bien
        # celui-la, et pas un hasard du cwd, la compilation rougit.
        far_h = tmp_path / "Far" / "include" / "far.h"
        (tmp_path / "Far" / "elsewhere").mkdir()
        far_h.rename(tmp_path / "Far" / "elsewhere" / "far.h")
        r = _jenga(tmp_path, "test", "--project", "Near_Reach_Tests")
        assert r.returncode != 0
        assert "REACH RAN" not in (r.stdout + r.stderr)


if __name__ == "__main__":
    sys.exit(subprocess.run(
        [sys.executable, "-m", "pytest", __file__, "-v"], cwd=str(ROOT)).returncode)
