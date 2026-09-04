#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_unittest_policy.py
=============================
AUTEUR : TEUGUIA TADJUIDJE Rodolf Séderis — Rihen

Banc des politiques de tests unitaires d'espace de travail (2.5.0) :
`dutc(enable, allow=[...])` / `dute(enable, allow=[...])` — liste blanche par
projet — et `--force` qui traverse jusqu'au Builder.

Deux etages :
  1. sans compilateur : la politique du Builder (`_ApplyUnitTestCompilationPolicy`),
     la validation DSL (un nom inconnu est une erreur DITE, pas un silence) et
     le chargement par le Loader ;
  2. avec compilateur (saute sinon, en le disant) : un espace de travail reel,
     deux suites, politique ON, une suite listee qui se compile ET s'execute,
     une suite non listee bloquee avec le message, `--force` qui debloque, et
     deux mutations qui font rougir — la suite retiree de la liste est bloquee,
     et une assertion cassee fait echouer `jenga test` (preuve que le binaire
     est bien lance, pas seulement construit).

Usage :
  python -m pytest tests/test_unittest_policy.py -v
"""
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pytest
import Jenga.Core.Api as Api
from Jenga.Core.Api import (
    Workspace, Project, Toolchain, ProjectKind, TargetOS, TargetArch, CompilerFamily,
)
from Jenga.Core.Loader import Loader


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _reset():
    Api._currentWorkspace = None
    Api._currentProject = None
    Api._currentToolchain = None
    Api._currentFilter = None


def _make_builder():
    """Builder minimal (meme forme que tests/test_jenga_complete.py)."""
    from Jenga.Core.Builder import Builder

    class _FakeBuilder(Builder):
        def Compile(self, *a): pass
        def Link(self, *a): pass
        def GetOutputExtension(self, *a): return ""
        def GetObjectExtension(self): return ".o"
        def GetModuleFlags(self, *a): return []

    _reset()
    wks = Workspace(name="W", location=tempfile.mkdtemp())
    stub_tc = Toolchain(name="stub", compilerFamily=CompilerFamily.CLANG,
                        ccPath="clang", cxxPath="clang++",
                        targetOs=TargetOS.WINDOWS, targetArch=TargetArch.X86_64)
    wks.toolchains["stub"] = stub_tc
    wks.defaultToolchain = "stub"

    b = _FakeBuilder.__new__(_FakeBuilder)
    b.workspace = wks
    b.config = "Debug"
    b.platform = "Windows-x86_64"
    b.targetOs = TargetOS.WINDOWS
    b.targetArch = TargetArch.X86_64
    b.targetEnv = None
    b.verbose = False
    b.action = "build"
    b.options = []
    b.toolchain = stub_tc
    b.forceUnitTests = False
    return b


def _policy_builder(allow=None, force=False):
    """Deux bibliotheques, deux suites, le cadre __Unitest__, politique ON."""
    b = _make_builder()
    wks = b.workspace
    wks.disableUnitTestCompilation = True
    wks.unitTestCompilationAllow = list(allow or [])
    b.forceUnitTests = force

    def lib(name):
        p = Project(name=name)
        p.kind = ProjectKind.STATIC_LIB
        return p

    def suite(parent):
        p = Project(name=f"{parent}_Tests")
        p.kind = ProjectKind.TEST_SUITE
        p.isTest = True
        p.dependsOn = [parent, "__Unitest__"]
        return p

    unitest = Project(name="__Unitest__")
    unitest.kind = ProjectKind.STATIC_LIB
    wks.projects = {
        "Alpha": lib("Alpha"), "Beta": lib("Beta"), "__Unitest__": unitest,
        "Alpha_Tests": suite("Alpha"), "Beta_Tests": suite("Beta"),
    }
    return b


ORDER = ["Alpha", "Beta", "__Unitest__", "Alpha_Tests", "Beta_Tests"]


# ===========================================================================
# 1. Politique du Builder : liste blanche, __Unitest__, --force
# ===========================================================================

class TestBuilderPolicyAllowList:
    def test_without_allow_nor_force_behaves_as_before(self):
        b = _policy_builder()
        assert b._ApplyUnitTestCompilationPolicy(ORDER, None) == ["Alpha", "Beta"]
        assert b._ApplyUnitTestCompilationPolicy(ORDER, "Alpha_Tests") is None

    def test_allowed_suite_survives_and_keeps_its_unitest_library(self):
        b = _policy_builder(allow=["Alpha_Tests"])
        order = b._ApplyUnitTestCompilationPolicy(ORDER, None)
        assert order == ["Alpha", "Beta", "__Unitest__", "Alpha_Tests"]

    def test_allowed_suite_as_explicit_target_is_not_blocked(self):
        b = _policy_builder(allow=["Alpha_Tests"])
        order = b._ApplyUnitTestCompilationPolicy(
            ["Alpha", "__Unitest__", "Alpha_Tests"], "Alpha_Tests")
        assert order == ["Alpha", "__Unitest__", "Alpha_Tests"]

    def test_unlisted_suite_as_explicit_target_stays_blocked(self):
        b = _policy_builder(allow=["Alpha_Tests"])
        assert b._ApplyUnitTestCompilationPolicy(
            ["Beta", "__Unitest__", "Beta_Tests"], "Beta_Tests") is None

    def test_mutation_removing_the_suite_from_the_list_blocks_it_again(self):
        b = _policy_builder(allow=["Alpha_Tests"])
        assert b._ApplyUnitTestCompilationPolicy(
            ["Alpha", "__Unitest__", "Alpha_Tests"], "Alpha_Tests") is not None
        b.workspace.unitTestCompilationAllow = []
        assert b._ApplyUnitTestCompilationPolicy(
            ["Alpha", "__Unitest__", "Alpha_Tests"], "Alpha_Tests") is None

    def test_force_lifts_the_policy_for_every_suite(self):
        b = _policy_builder(force=True)
        assert b._ApplyUnitTestCompilationPolicy(ORDER, None) == ORDER
        assert b._ApplyUnitTestCompilationPolicy(ORDER, "Beta_Tests") == ORDER

    def test_policy_off_ignores_allow_and_force(self):
        b = _policy_builder(allow=["Alpha_Tests"])
        b.workspace.disableUnitTestCompilation = False
        assert b._ApplyUnitTestCompilationPolicy(ORDER, None) == ORDER


# ===========================================================================
# 2. DSL : allow= se pose, et un nom inconnu est une erreur DITE
# ===========================================================================

def _dsl_workspace(compile_allow=None, exec_allow=None):
    """Un workspace DSL avec un projet Calc et sa suite Calc_Tests, sans
    passer par unitest() (le projet __Unitest__ est pose a la main)."""
    _reset()
    from Jenga.Core.Api import workspace, project, staticlib, dutc, dute
    with workspace("Wdsl"):
        if compile_allow is not None:
            dutc(True, allow=compile_allow)
        if exec_allow is not None:
            dute(True, allow=exec_allow)
        wks = Api._currentWorkspace
        u = Project(name="__Unitest__")
        u.kind = ProjectKind.STATIC_LIB
        wks.projects["__Unitest__"] = u
        with project("Calc"):
            staticlib()
        t = Project(name="Calc_Tests")
        t.kind = ProjectKind.TEST_SUITE
        t.isTest = True
        wks.projects["Calc_Tests"] = t
    return Api._currentWorkspace


class TestDslAllowList:
    def test_allow_is_stored_on_each_policy_separately(self):
        wks = _dsl_workspace(compile_allow=["Calc_Tests"])
        assert wks.disableUnitTestCompilation is True
        assert wks.unitTestCompilationAllow == ["Calc_Tests"]
        assert wks.disableUnitTestExecution is False
        assert wks.unitTestExecutionAllow == []

    def test_a_single_string_is_accepted(self):
        wks = _dsl_workspace(exec_allow="Calc_Tests")
        assert wks.unitTestExecutionAllow == ["Calc_Tests"]

    def test_no_allow_keeps_the_old_shape(self):
        _reset()
        from Jenga.Core.Api import workspace, dutc, dute
        with workspace("Wold"):
            dutc(enable=True)
            dute(enable=True)
        wks = Api._currentWorkspace
        assert (wks.disableUnitTestCompilation, wks.disableUnitTestExecution) == (True, True)
        assert wks.unitTestCompilationAllow == [] and wks.unitTestExecutionAllow == []

    def test_unknown_project_is_a_said_error_with_the_known_suites(self):
        with pytest.raises(ValueError) as exc:
            _dsl_workspace(compile_allow=["Nope_Tests"])
        msg = str(exc.value)
        assert "dutc(allow=...)" in msg and "'Nope_Tests'" in msg
        assert "Calc_Tests" in msg  # les suites connues sont nommees

    def test_module_name_instead_of_suite_name_gets_a_hint(self):
        with pytest.raises(ValueError) as exc:
            _dsl_workspace(exec_allow=["Calc"])
        msg = str(exc.value)
        assert "dute(allow=...)" in msg
        assert "n'est pas une suite de tests" in msg and "'<Projet>_Tests'" in msg

    def test_typo_without_suffix_suggests_the_suite(self):
        _reset()
        from Jenga.Core.Api import workspace, dutc
        with pytest.raises(ValueError) as exc:
            with workspace("Whint"):
                dutc(True, allow=["Calc"])
                t = Project(name="Calc_Tests")
                t.kind = ProjectKind.TEST_SUITE
                t.isTest = True
                Api._currentWorkspace.projects["Calc_Tests"] = t
        assert "vouliez-vous dire 'Calc_Tests'" in str(exc.value)

    def test_validation_does_not_mask_an_exception_in_flight(self):
        _reset()
        from Jenga.Core.Api import workspace, dutc
        with pytest.raises(RuntimeError, match="premiere"):
            with workspace("Wexc"):
                dutc(True, allow=["Nope_Tests"])
                raise RuntimeError("premiere")


# ===========================================================================
# 3. Espace de travail reel : compile, execute, bloque, --force, mutations
# ===========================================================================

_CXX = shutil.which("clang++") or shutil.which("g++") or shutil.which("cl")

_WORKSPACE_TEMPLATE = """\
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from Jenga import *
from Jenga.GlobalToolchains import *

with workspace("PolicyBench"):
    configurations(["Debug"])
    targetoses([TargetOS.WINDOWS, TargetOS.LINUX, TargetOS.MACOS])
    targetarchs([TargetArch.X86_64, TargetArch.ARM64])
    RegisterJengaGlobalToolchains()

    dutc(enable=True, allow={allow!r})
    dute(enable=True, allow={allow!r})

    with unitest() as u:
        u.Compile(cxxflags=["-fexceptions"])

    for _name in ("Alpha", "Beta"):
        with project(_name):
            staticlib()
            language("C++")
            cppdialect("C++17")
            files([_name + "/src/**.cpp"])
            includedirs([_name + "/include"])
            with test():
                testfiles([_name + "/tests/**.cpp"])
"""


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = text.encode("utf-8")
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def _make_bench_workspace(root: Path, allow, beta_expected: int = 5) -> Path:
    for name in ("Alpha", "Beta"):
        low = name.lower()
        _write(root / name / "include" / f"{low}.h",
               f"#pragma once\nint {low}_add(int a, int b);\n")
        _write(root / name / "src" / f"{low}.cpp",
               f'#include "{low}.h"\nint {low}_add(int a, int b) {{ return a + b; }}\n')
        expected = 5 if name == "Alpha" else beta_expected
        _write(root / name / "tests" / f"test_{low}.cpp", textwrap.dedent(f"""\
            #include <Unitest/Unitest.h>
            #include <Unitest/TestMacro.h>
            #include "{low}.h"

            TEST_CASE({name}, Add) {{
                ASSERT_EQUAL({expected}, {low}_add(2, 3));
            }}
            """))
    entry = root / "PolicyBench.jenga"
    _write(entry, _WORKSPACE_TEMPLATE.format(allow=list(allow)))
    return entry


def _jenga(root: Path, *args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(
        [sys.executable, "-m", "Jenga", *args, "--no-daemon",
         "--jenga-file", str(root / "PolicyBench.jenga")],
        cwd=str(root), env=env, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=600,
    )


@pytest.mark.skipif(_CXX is None, reason="aucun compilateur C++ (clang++/g++/cl) dans le PATH")
class TestRealWorkspacePolicy:
    """Chaque methode reconstruit peu : le cache incremental de Jenga fait le
    reste. Le dossier est partage par la classe pour ne compiler Unitest
    qu'une fois."""

    @pytest.fixture(scope="class")
    def bench(self, tmp_path_factory):
        root = tmp_path_factory.mktemp("policy_bench")
        _make_bench_workspace(root, allow=["Alpha_Tests"])
        return root

    def test_listed_suite_compiles_and_runs(self, bench):
        r = _jenga(bench, "test", "--project", "Alpha_Tests")
        out = r.stdout + r.stderr
        assert r.returncode == 0, out
        assert "All tests passed for Alpha_Tests" in out

    def test_unlisted_suite_is_blocked_with_the_message(self, bench):
        r = _jenga(bench, "test", "--project", "Beta_Tests")
        out = r.stdout + r.stderr
        assert r.returncode == 1, out
        assert "disableunittestcompilation" in out
        assert "'Beta_Tests' is not in its allow list" in out
        assert "dutc(True, allow=['Beta_Tests'])" in out
        assert "Running tests for Beta_Tests" not in out

    def test_force_unblocks_the_unlisted_suite_down_to_the_builder(self, bench):
        r = _jenga(bench, "test", "--project", "Beta_Tests", "--force")
        out = r.stdout + r.stderr
        assert r.returncode == 0, out
        assert "Blocked target" not in out  # le defaut d'avant : --force accepte, Builder rebloquait
        assert "All tests passed for Beta_Tests" in out

    def test_without_project_only_the_listed_suite_runs(self, bench):
        r = _jenga(bench, "test")
        out = r.stdout + r.stderr
        assert r.returncode == 0, out
        assert "All tests passed for Alpha_Tests" in out
        assert "Skipped by workspace policy (dutc/dute): Beta_Tests" in out
        assert "Running tests for Beta_Tests" not in out

    def test_run_respects_the_list_and_force(self, bench):
        blocked = _jenga(bench, "run", "Beta_Tests", "--build", "--no-console")
        out = blocked.stdout + blocked.stderr
        assert blocked.returncode == 1, out
        assert "'Beta_Tests' is not in its allow list" in out

        forced = _jenga(bench, "run", "Beta_Tests", "--build", "--no-console", "--force")
        out = forced.stdout + forced.stderr
        assert forced.returncode == 0, out
        assert "Blocked target" not in out

    def test_build_target_honours_the_list_and_force_tests(self, bench):
        blocked = _jenga(bench, "build", "--target", "Beta_Tests")
        out = blocked.stdout + blocked.stderr
        assert blocked.returncode != 0, out
        assert "Blocked target: 'Beta_Tests'" in out

        allowed = _jenga(bench, "build", "--target", "Alpha_Tests")
        assert allowed.returncode == 0, allowed.stdout + allowed.stderr

        forced = _jenga(bench, "build", "--target", "Beta_Tests", "--force-tests")
        assert forced.returncode == 0, forced.stdout + forced.stderr

    def test_mutation_removing_the_suite_from_the_list_blocks_it(self, bench):
        _write(bench / "PolicyBench.jenga", _WORKSPACE_TEMPLATE.format(allow=[]))
        try:
            r = _jenga(bench, "test", "--project", "Alpha_Tests")
            out = r.stdout + r.stderr
            assert r.returncode == 1, out
            assert "'Alpha_Tests' is not in its allow list" in out
        finally:
            _write(bench / "PolicyBench.jenga", _WORKSPACE_TEMPLATE.format(allow=["Alpha_Tests"]))

    def test_mutation_breaking_an_assertion_makes_jenga_test_fail(self, bench):
        """Preuve que la suite est LANCEE, pas seulement construite."""
        test_cpp = bench / "Alpha" / "tests" / "test_alpha.cpp"
        original = test_cpp.read_text(encoding="utf-8")
        assert original.count("ASSERT_EQUAL(5,") == 1
        try:
            _write(test_cpp, original.replace("ASSERT_EQUAL(5,", "ASSERT_EQUAL(6,"))
            r = _jenga(bench, "test", "--project", "Alpha_Tests")
            out = r.stdout + r.stderr
            assert r.returncode == 1, out
            assert "Tests failed for Alpha_Tests" in out
        finally:
            _write(test_cpp, original)
        r = _jenga(bench, "test", "--project", "Alpha_Tests")
        assert r.returncode == 0, r.stdout + r.stderr

    def test_unknown_name_in_allow_is_a_said_error_at_load(self, bench):
        _write(bench / "PolicyBench.jenga", _WORKSPACE_TEMPLATE.format(allow=["Gamma_Tests"]))
        try:
            r = _jenga(bench, "test", "--project", "Alpha_Tests")
            out = r.stdout + r.stderr
            assert r.returncode == 1, out
            assert "projet de test inconnu 'Gamma_Tests'" in out
            assert "Alpha_Tests, Beta_Tests" in out
        finally:
            _write(bench / "PolicyBench.jenga", _WORKSPACE_TEMPLATE.format(allow=["Alpha_Tests"]))


if __name__ == "__main__":
    sys.exit(subprocess.run(
        [sys.executable, "-m", "pytest", __file__, "-v", "--tb=short"], cwd=str(ROOT)
    ).returncode)
