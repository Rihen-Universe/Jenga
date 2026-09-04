#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_unittest_runner.py
=============================
AUTEUR : TEUGUIA TADJUIDJE Rodolf Séderis — Rihen

Banc du runner de tests (2.6.0) :
  1. le PATH d'execution : `jenga test`/`run` mettent en tete le bin de la
     chaine — une suite liee contre libstdc++-6.dll demarre meme quand le PATH
     de l'appelant ne connait pas la chaine ;
  2. un binaire qui n'a PAS demarre (0xC0000135 / 127) se DIT : nom de la
     cible, code nomme, DLL soupconnee (`--no-runtime-path` force le cas) ;
  3. `testownmain()` : la suite fournit son main, Jenga n'en genere pas ; deux
     main() dans une suite sont refuses en nommant les fichiers ; un main()
     sans le mot est refuse en disant le mot. Mutation : le mot retire ->
     rouge.

Mesure d'origine : Nkentseu, 2026-09-04, `NKMath_Tests.exe` en 127 muet.
"""
import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pytest
from Jenga.Core.Builder import Builder
from Jenga.Utils.RuntimeDiag import RuntimeDiag


# ===========================================================================
# 1. Sans compilateur : detection de main(), codes du chargeur
# ===========================================================================

class TestFilesDefiningMain:
    def _write(self, tmp_path, name, text):
        p = tmp_path / name
        p.write_text(textwrap.dedent(text), encoding="utf-8")
        return str(p)

    def test_definition_counts_declaration_and_comment_do_not(self, tmp_path):
        defi = self._write(tmp_path, "a.cpp", """
            #include <cstdio>
            int main(int argc, char** argv) {
                return 0;
            }
            """)
        decl = self._write(tmp_path, "b.cpp", """
            int main(int, char**);
            void f() {}
            """)
        comm = self._write(tmp_path, "c.cpp", """
            // int main() { return 0; }
            /* int main()
               { return 1; } */
            void g() {}
            """)
        header = self._write(tmp_path, "d.h", "int main() { return 0; }\n")
        assert Builder.FilesDefiningMain([defi, decl, comm, header]) == [defi]

    def test_winmain_and_brace_on_next_line(self, tmp_path):
        win = self._write(tmp_path, "w.cpp", """
            #include <windows.h>
            int WINAPI_UNUSED_MARKER;
            int WinMain(HINSTANCE, HINSTANCE, LPSTR, int)
            {
                return 0;
            }
            """)
        assert Builder.FilesDefiningMain([win]) == [win]

    def test_two_files_two_mains(self, tmp_path):
        a = self._write(tmp_path, "a.cpp", "int main() { return 0; }\n")
        b = self._write(tmp_path, "b.cpp", "auto main() -> int { return 0; }\n")
        assert Builder.FilesDefiningMain([a, b]) == [a, b]


class TestRuntimeDiagCodes:
    def test_loader_codes_in_both_signs(self):
        assert RuntimeDiag.IsLoaderFailure(0xC0000135)
        assert RuntimeDiag.IsLoaderFailure(-1073741515)      # meme code, signe
        assert RuntimeDiag.IsLoaderFailure(127)
        assert not RuntimeDiag.IsLoaderFailure(1)
        assert not RuntimeDiag.IsLoaderFailure(0)
        assert "STATUS_DLL_NOT_FOUND" in RuntimeDiag.CodeName(-1073741515)

    def test_ordinary_failure_has_no_explanation(self, tmp_path):
        assert RuntimeDiag.Explain(1, tmp_path / "x.exe", "", []) is None

    def test_not_a_pe_file_yields_no_imports(self, tmp_path):
        p = tmp_path / "not.exe"
        p.write_bytes(b"hello")
        assert RuntimeDiag.PeImports(p) == []
        assert RuntimeDiag.PeImports(tmp_path / "absent.exe") == []


# ===========================================================================
# 2. Espace de travail reel
# ===========================================================================

_CXX = shutil.which("clang++") or shutil.which("g++") or shutil.which("cl")

_WORKSPACE = """\
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from Jenga import *
from Jenga.GlobalToolchains import *

with workspace("RunnerBench"):
    configurations(["Debug"])
    targetoses([TargetOS.WINDOWS, TargetOS.LINUX, TargetOS.MACOS])
    targetarchs([TargetArch.X86_64, TargetArch.ARM64])
    RegisterJengaGlobalToolchains()

    with unitest() as u:
        u.Compile(cxxflags=["-fexceptions"])

    with project("Alpha"):
        staticlib()
        language("C++")
        cppdialect("C++17")
        files(["Alpha/src/**.cpp"])
        includedirs(["Alpha/include"])
        with test():
            testfiles(["Alpha/tests/**.cpp"])

    with project("Own"):
        staticlib()
        language("C++")
        cppdialect("C++17")
        files(["Own/src/**.cpp"])
        includedirs(["Own/include"])
        with test():
            testfiles(["Own/tests/**.cpp"])
            {own_main}

    with project("Twin"):
        staticlib()
        language("C++")
        cppdialect("C++17")
        files(["Twin/src/**.cpp"])
        includedirs(["Twin/include"])
        with test():
            testfiles(["Twin/tests/**.cpp"])
            testownmain()

    with project("Sneaky"):
        staticlib()
        language("C++")
        cppdialect("C++17")
        files(["Sneaky/src/**.cpp"])
        includedirs(["Sneaky/include"])
        with test():
            testfiles(["Sneaky/tests/**.cpp"])
"""


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(text.encode("utf-8"))
    os.replace(tmp, path)


_OWN_MAIN = """\
#include <cstdio>
#include "{low}.h"

int main() {{
    std::printf("OWN MAIN RAN %d\\n", {low}_add(2, 3));
    return {low}_add(2, 3) == 5 ? 0 : 1;
}}
"""

_TEST_CASE = """\
#include <Unitest/Unitest.h>
#include <Unitest/TestMacro.h>
#include "{low}.h"

TEST_CASE({name}, Add) {{
    ASSERT_EQUAL(5, {low}_add(2, 3));
}}
"""


def _lib(root: Path, name: str) -> None:
    low = name.lower()
    _write(root / name / "include" / f"{low}.h", f"#pragma once\nint {low}_add(int a, int b);\n")
    _write(root / name / "src" / f"{low}.cpp",
           f'#include "{low}.h"\nint {low}_add(int a, int b) {{ return a + b; }}\n')


def _make_workspace(root: Path, own_main: str = "testownmain()") -> None:
    for name in ("Alpha", "Own", "Twin", "Sneaky"):
        _lib(root, name)
    _write(root / "Alpha" / "tests" / "test_alpha.cpp", _TEST_CASE.format(name="Alpha", low="alpha"))
    _write(root / "Own" / "tests" / "main_own.cpp", _OWN_MAIN.format(low="own"))
    _write(root / "Twin" / "tests" / "prog_one.cpp", _OWN_MAIN.format(low="twin"))
    _write(root / "Twin" / "tests" / "prog_two.cpp", _OWN_MAIN.format(low="twin"))
    _write(root / "Sneaky" / "tests" / "main_sneaky.cpp", _OWN_MAIN.format(low="sneaky"))
    _write(root / "RunnerBench.jenga", _WORKSPACE.format(own_main=own_main))


def _stripped_path() -> str:
    """PATH sans la chaine : ni clang++, ni libstdc++-6.dll. Ce qui reste
    suffit a Python (subprocess, msys non requis)."""
    keep = []
    for d in os.environ.get("PATH", "").split(os.pathsep):
        if not d:
            continue
        p = Path(d)
        if any((p / n).exists() for n in ("libstdc++-6.dll", "clang++.exe", "clang++", "g++.exe", "g++")):
            continue
        keep.append(d)
    return os.pathsep.join(keep)


def _jenga(root: Path, *args: str, path: str = None) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    env["PYTHONIOENCODING"] = "utf-8"
    if path is not None:
        env["PATH"] = path
    return subprocess.run(
        [sys.executable, "-m", "Jenga", *args, "--no-daemon",
         "--jenga-file", str(root / "RunnerBench.jenga")],
        cwd=str(root), env=env, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=600,
    )


@pytest.mark.skipif(_CXX is None, reason="aucun compilateur C++ (clang++/g++/cl) dans le PATH")
class TestRunnerRealWorkspace:

    @pytest.fixture(scope="class")
    def bench(self, tmp_path_factory):
        root = tmp_path_factory.mktemp("runner_bench")
        _make_workspace(root)
        r = _jenga(root, "test", "--project", "Alpha_Tests")
        assert r.returncode == 0, r.stdout + r.stderr
        return root

    def _exe(self, bench: Path) -> Path:
        found = list(bench.glob("Build/Tests/*/Alpha_Tests*"))
        found = [f for f in found if f.suffix in (".exe", "") and f.is_file()]
        assert found, "Alpha_Tests introuvable sous Build/Tests"
        return found[0]

    # -- 1. PATH d'execution ------------------------------------------------

    def test_suite_starts_even_when_the_callers_path_ignores_the_toolchain(self, bench):
        r = _jenga(bench, "test", "--project", "Alpha_Tests", "--no-build", path=_stripped_path())
        out = r.stdout + r.stderr
        assert r.returncode == 0, out
        assert "All tests passed for Alpha_Tests" in out

    @pytest.mark.skipif(sys.platform != "win32", reason="cas DLL Windows (0xC0000135)")
    def test_missing_dll_is_said_with_its_name(self, bench):
        exe = self._exe(bench)
        imports = [d.lower() for d in RuntimeDiag.PeImports(exe)]
        if "libstdc++-6.dll" not in imports:
            pytest.skip("la suite est liee statiquement : pas de DLL a manquer ici")
        r = _jenga(bench, "test", "--project", "Alpha_Tests", "--no-build", "--no-runtime-path",
                   path=_stripped_path())
        out = r.stdout + r.stderr
        assert r.returncode == 1, out
        assert "did not start" in out and "STATUS_DLL_NOT_FOUND" in out, out
        assert "libstdc++-6.dll" in out, out
        assert "Alpha_Tests" in out

    @pytest.mark.skipif(sys.platform != "win32", reason="cas DLL Windows (0xC0000135)")
    def test_run_says_it_too(self, bench):
        exe = self._exe(bench)
        if "libstdc++-6.dll" not in [d.lower() for d in RuntimeDiag.PeImports(exe)]:
            pytest.skip("la suite est liee statiquement : pas de DLL a manquer ici")
        ok = _jenga(bench, "run", "Alpha_Tests", "--no-console", path=_stripped_path())
        assert ok.returncode == 0, ok.stdout + ok.stderr
        ko = _jenga(bench, "run", "Alpha_Tests", "--no-console", "--no-runtime-path", path=_stripped_path())
        out = ko.stdout + ko.stderr
        assert ko.returncode != 0, out
        assert "STATUS_DLL_NOT_FOUND" in out and "libstdc++-6.dll" in out, out

    # -- 2. testownmain() ---------------------------------------------------

    def test_own_main_suite_builds_and_its_main_runs(self, bench):
        r = _jenga(bench, "test", "--project", "Own_Tests")
        out = r.stdout + r.stderr
        assert r.returncode == 0, out
        assert "OWN MAIN RAN 5" in out, out
        assert "All tests passed for Own_Tests" in out

    def test_two_mains_are_refused_naming_both_files(self, bench):
        r = _jenga(bench, "test", "--project", "Twin_Tests")
        out = r.stdout + r.stderr
        assert r.returncode != 0, out
        assert "defines main() in 2 files" in out, out
        assert "prog_one.cpp" in out and "prog_two.cpp" in out, out
        assert "sub-suite" in out

    def test_main_without_the_word_is_refused_saying_the_word(self, bench):
        r = _jenga(bench, "test", "--project", "Sneaky_Tests")
        out = r.stdout + r.stderr
        assert r.returncode != 0, out
        assert "main_sneaky.cpp" in out and "declare testownmain()" in out, out

    def test_mutation_removing_testownmain_turns_own_red(self, bench):
        _make_workspace(bench, own_main="pass")
        try:
            r = _jenga(bench, "test", "--project", "Own_Tests")
            out = r.stdout + r.stderr
            assert r.returncode != 0, out
            assert "declare testownmain()" in out, out
        finally:
            _make_workspace(bench)

    def test_testownmain_and_testmaintemplate_contradict(self, bench):
        _make_workspace(bench, own_main='testmaintemplate("Own/tests/main_own.cpp")\n            testownmain()')
        try:
            r = _jenga(bench, "test", "--project", "Own_Tests")
            out = r.stdout + r.stderr
            assert r.returncode != 0, out
            assert "contradicts" in out, out
        finally:
            _make_workspace(bench)


if __name__ == "__main__":
    sys.exit(subprocess.run(
        [sys.executable, "-m", "pytest", __file__, "-v", "--tb=short"], cwd=str(ROOT)
    ).returncode)
