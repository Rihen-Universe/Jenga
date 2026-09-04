#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_dsl_scope.py
=======================
AUTEUR : TEUGUIA TADJUIDJE Rodolf Séderis — Rihen

Banc de la portee des mots du DSL (2.6.1) :
  - un bloc `test()` rend le projet courant tel qu'il l'a trouve : deux
    `with test()` dans un projet = deux suites, et un mot ecrit apres le bloc
    s'applique au parent ;
  - un mot du DSL hors de sa portee se REFUSE en nommant le mot et la ligne,
    jamais ignore en silence — mesure par l'agent Noge sur Nkentseu le
    2026-09-04 : les sous-suites etaient nommees dans les .jenga, pas actives.

Usage :
  python -m pytest tests/test_dsl_scope.py -v
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pytest
import Jenga.Core.Api as Api
from Jenga.Core.Api import (
    workspace, project, staticlib, test, testfiles, testownmain, files, defines,
    includedirs, ldflags, toolchain, unitest, ProjectKind,
)
from Jenga.Core.Loader import Loader


def _reset():
    Api.resetstate()


# ===========================================================================
# 1. test() rend le projet courant
# ===========================================================================

class TestTestBlockRestoresProject:
    def test_two_test_blocks_make_two_suites(self):
        _reset()
        with workspace("W"):
            with unitest() as u:
                u.Precompiled()
            with project("Serial"):
                staticlib()
                files(["src/**.cpp"])
                with test():
                    testfiles(["tests/case_*.cpp"])
                with test("Bench"):
                    testfiles(["tests/bench_main.cpp"])
                    testownmain()
        wks = Api.getcurrentworkspace()
        assert "Serial_Tests" in wks.projects
        assert "Serial_Bench_Tests" in wks.projects
        bench = wks.projects["Serial_Bench_Tests"]
        assert bench.kind == ProjectKind.TEST_SUITE and bench.testOwnMain
        assert "__Unitest__" in bench.dependsOn and "Serial" in bench.dependsOn
        assert wks.projects["Serial_Tests"].testOwnMain is False

    def test_a_word_after_the_test_block_applies_to_the_parent(self):
        _reset()
        with workspace("W"):
            with unitest() as u:
                u.Precompiled()
            with project("Core"):
                staticlib()
                with test():
                    testfiles(["tests/**.cpp"])
                defines(["AFTER_TEST_BLOCK"])
                includedirs(["after"])
        core = Api.getcurrentworkspace().projects["Core"]
        assert "AFTER_TEST_BLOCK" in core.defines
        assert "after" in core.includeDirs
        # ... et PAS a la suite : le bloc etait ferme.
        assert "AFTER_TEST_BLOCK" not in Api.getcurrentworkspace().projects["Core_Tests"].defines

    def test_current_project_is_the_parent_after_the_block(self):
        _reset()
        with workspace("W"):
            with unitest() as u:
                u.Precompiled()
            with project("P"):
                staticlib()
                parent = Api._currentProject
                with test():
                    assert Api._currentProject is not parent
                    assert Api._currentProject.isTest
                assert Api._currentProject is parent


# ===========================================================================
# 2. Un mot hors de sa portee se refuse en le disant
# ===========================================================================

class TestWordsOutsideTheirScope:
    def test_project_word_outside_any_project_names_word_and_line(self):
        _reset()
        with workspace("W"):
            with pytest.raises(RuntimeError) as exc:
                files(["src/**.cpp"])
        msg = str(exc.value)
        assert "'files()'" in msg and "outside any project block" in msg
        assert Path(__file__).name in msg  # la ligne de l'appelant

    def test_test_word_outside_any_test_block(self):
        _reset()
        with workspace("W"):
            with project("P"):
                staticlib()
                with pytest.raises(RuntimeError, match=r"'testfiles\(\)' used outside any test\(\) block"):
                    testfiles(["tests/**.cpp"])
                with pytest.raises(RuntimeError, match=r"'testownmain\(\)'"):
                    testownmain()

    def test_project_or_toolchain_word_is_fine_in_a_toolchain_and_refused_outside_both(self):
        _reset()
        with workspace("W"):
            with toolchain("tc", "clang"):
                ldflags(["-static-libstdc++"])          # portee toolchain : accepte
            assert Api.getcurrentworkspace().toolchains["tc"].ldflags == ["-static-libstdc++"]
            with pytest.raises(RuntimeError, match=r"'ldflags\(\)' used outside any project or toolchain"):
                ldflags(["-lm"])

    def test_inside_a_project_nothing_changes(self):
        _reset()
        with workspace("W"):
            with project("P"):
                staticlib()
                files(["a.cpp"])
                defines(["X"])
        p = Api.getcurrentworkspace().projects["P"]
        assert p.files == ["a.cpp"] and "X" in p.defines

    def test_wrapped_words_keep_their_names(self):
        assert files.__name__ == "files" and testfiles.__name__ == "testfiles"
        assert getattr(files, "_jengaScope", None) == "project"


# ===========================================================================
# 3. Par le Loader : le .jenga entier refuse, avec la ligne
# ===========================================================================

_JENGA_AFTER_TEST = """\
from Jenga import *
with workspace("Wl"):
    with unitest() as u:
        u.Precompiled()
    with project("Core"):
        staticlib()
        files(["src/**.cpp"])
        with test():
            testfiles(["tests/**.cpp"])
        with test("Bench"):
            testfiles(["tests/bench.cpp"])
            testownmain()
        defines(["AFTER"])
"""

_JENGA_OUTSIDE = """\
from Jenga import *
with workspace("Wl"):
    configurations(["Debug"])
    files(["src/**.cpp"])
"""


class TestThroughTheLoader:
    def test_two_suites_and_a_word_after_the_block_load(self, tmp_path):
        entry = tmp_path / "Wl.jenga"
        entry.write_text(_JENGA_AFTER_TEST, encoding="utf-8")
        wks = Loader(verbose=False).LoadWorkspace(str(entry))
        assert wks is not None
        assert {"Core", "Core_Tests", "Core_Bench_Tests", "__Unitest__"} <= set(wks.projects)
        assert "AFTER" in wks.projects["Core"].defines

    def test_word_outside_project_refuses_the_workspace_with_the_line(self, tmp_path, capsys):
        entry = tmp_path / "Wl.jenga"
        entry.write_text(_JENGA_OUTSIDE, encoding="utf-8")
        wks = Loader(verbose=False).LoadWorkspace(str(entry))
        out = capsys.readouterr()
        text = out.out + out.err
        assert wks is None
        assert "'files()' used outside any project block" in text
        assert "Wl.jenga:4" in text
