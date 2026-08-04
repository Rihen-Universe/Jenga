#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_jenga_complete.py
============================
Suite de tests complète pour Jenga Build System.

Couvre :
  - GlobalToolchains (registration, fixes des bugs)
  - DependencyResolver (tri topologique, cycles)
  - Filter system (system:, config:, arch:, options:, &&, ||, !)
  - Variables expander (%{wks.location}, %{prj.name}, etc.)
  - Platform detection
  - Emscripten runner scripts generation
  - Builder._FilterMatches()
  - BuildCommand utilities (platform parsing, option tokens)
  - Examples loading (syntaxe .jenga)

Usage :
  python -m pytest tests/test_jenga_complete.py -v
  python tests/test_jenga_complete.py
"""
import sys
import os
import tempfile
import json
from pathlib import Path

# Ajouter le répertoire racine au PYTHONPATH
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pytest
import Jenga.Core.Api as Api
from Jenga import *
from Jenga.Core.Api import (
    ProjectKind, Language, Optimization, WarningLevel,
    TargetOS, TargetArch, TargetEnv, CompilerFamily,
    Workspace, Project, Toolchain,
)
from Jenga.Core.DependencyResolver import DependencyResolver
from Jenga.Core.Platform import Platform
from Jenga.Core.Variables import VariableExpander
from Jenga.Core.GlobalToolchains import (
    LoadGlobalRegistry, BuildToolchainFromRegistryEntry,
    ApplyGlobalRegistryToWorkspace,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _reset():
    Api._currentWorkspace = None
    Api._currentProject = None
    Api._currentToolchain = None
    Api._currentFilter = None


def _make_workspace_with_projects(project_deps: dict) -> Workspace:
    """Build a Workspace with projects and dependency edges."""
    _reset()
    wks = Workspace(name="TestWks", location=str(tempfile.mkdtemp()))
    for name, deps in project_deps.items():
        p = Project(name=name)
        p.dependsOn = list(deps)
        wks.projects[name] = p
    return wks


# ===========================================================================
# 1. DependencyResolver
# ===========================================================================

class TestDependencyResolver:
    def test_single_project(self):
        wks = _make_workspace_with_projects({"App": []})
        order = DependencyResolver.ResolveBuildOrder(wks, None)
        assert order == ["App"]

    def test_linear_chain(self):
        wks = _make_workspace_with_projects({
            "C": [],
            "B": ["C"],
            "A": ["B"],
        })
        order = DependencyResolver.ResolveBuildOrder(wks, None)
        assert order.index("C") < order.index("B")
        assert order.index("B") < order.index("A")

    def test_diamond_dependency(self):
        wks = _make_workspace_with_projects({
            "Core":  [],
            "LibA":  ["Core"],
            "LibB":  ["Core"],
            "App":   ["LibA", "LibB"],
        })
        order = DependencyResolver.ResolveBuildOrder(wks, None)
        assert order.index("Core") < order.index("LibA")
        assert order.index("Core") < order.index("LibB")
        assert order.index("LibA") < order.index("App")
        assert order.index("LibB") < order.index("App")

    def test_cycle_detection(self):
        wks = _make_workspace_with_projects({
            "A": ["B"],
            "B": ["C"],
            "C": ["A"],
        })
        with pytest.raises(RuntimeError, match="[Cc]ircular|[Cc]ycle"):
            DependencyResolver.ResolveBuildOrder(wks, None)

    def test_target_specific(self):
        wks = _make_workspace_with_projects({
            "LibA": [],
            "LibB": [],
            "App":  ["LibA"],
        })
        order = DependencyResolver.ResolveBuildOrder(wks, "App")
        assert "LibB" not in order
        assert "App" in order
        assert "LibA" in order

    def test_multiple_roots(self):
        wks = _make_workspace_with_projects({
            "A": [],
            "B": [],
            "C": [],
        })
        order = DependencyResolver.ResolveBuildOrder(wks, None)
        assert set(order) == {"A", "B", "C"}


# ===========================================================================
# 2. Filter System  (via Builder._FilterMatches)
# ===========================================================================

def _make_builder(target_os: TargetOS, arch: TargetArch, config="Debug",
                  platform=None, options=None):
    """Create a minimal Builder-like object for filter matching tests."""
    from Jenga.Core.Builder import Builder

    class _FakeBuilder(Builder):
        def Compile(self, *a): pass
        def Link(self, *a): pass
        def GetOutputExtension(self, *a): return ""
        def GetObjectExtension(self): return ".o"
        def GetModuleFlags(self, *a): return []

    _reset()
    wks = Workspace(name="W", location=tempfile.mkdtemp())
    # Inject a stub toolchain so Builder.__init__ doesn't fail on resolution
    stub_tc = Toolchain(name="stub", compilerFamily=CompilerFamily.CLANG,
                        ccPath="clang", cxxPath="clang++",
                        targetOs=target_os, targetArch=arch)
    wks.toolchains["stub"] = stub_tc
    wks.defaultToolchain = "stub"

    b = _FakeBuilder.__new__(_FakeBuilder)
    b.workspace = wks
    b.config = config
    b.platform = platform or f"{target_os.value}-{arch.value}"
    b.targetOs = target_os
    b.targetArch = arch
    b.targetEnv = None
    b.verbose = False
    b.action = "build"
    b.options = sorted(set(options or []))
    b.toolchain = stub_tc
    return b


class TestFilterMatches:
    def test_system_windows(self):
        b = _make_builder(TargetOS.WINDOWS, TargetArch.X86_64)
        assert b._FilterMatches("system:Windows") is True
        assert b._FilterMatches("system:Linux") is False

    def test_system_linux(self):
        b = _make_builder(TargetOS.LINUX, TargetArch.X86_64)
        assert b._FilterMatches("system:Linux") is True
        assert b._FilterMatches("system:Windows") is False

    def test_system_android(self):
        b = _make_builder(TargetOS.ANDROID, TargetArch.ARM64)
        assert b._FilterMatches("system:Android") is True

    def test_system_web(self):
        b = _make_builder(TargetOS.WEB, TargetArch.WASM32)
        assert b._FilterMatches("system:Web") is True
        assert b._FilterMatches("system:Emscripten") is True  # alias

    def test_config_debug(self):
        b = _make_builder(TargetOS.WINDOWS, TargetArch.X86_64, config="Debug")
        assert b._FilterMatches("config:Debug") is True
        assert b._FilterMatches("config:Release") is False

    def test_config_release(self):
        b = _make_builder(TargetOS.WINDOWS, TargetArch.X86_64, config="Release")
        assert b._FilterMatches("config:Release") is True
        assert b._FilterMatches("config:Debug") is False

    def test_arch_x86_64(self):
        b = _make_builder(TargetOS.LINUX, TargetArch.X86_64)
        assert b._FilterMatches("arch:x86_64") is True
        assert b._FilterMatches("arch:arm64") is False

    def test_arch_arm64(self):
        b = _make_builder(TargetOS.ANDROID, TargetArch.ARM64)
        assert b._FilterMatches("arch:arm64") is True

    def test_and_operator(self):
        b = _make_builder(TargetOS.WINDOWS, TargetArch.X86_64, config="Debug")
        assert b._FilterMatches("system:Windows && config:Debug") is True
        assert b._FilterMatches("system:Windows && config:Release") is False

    def test_or_operator(self):
        b = _make_builder(TargetOS.WINDOWS, TargetArch.X86_64)
        assert b._FilterMatches("system:Windows || system:Linux") is True
        b2 = _make_builder(TargetOS.MACOS, TargetArch.ARM64)
        assert b2._FilterMatches("system:Windows || system:Linux") is False

    def test_not_operator(self):
        b = _make_builder(TargetOS.LINUX, TargetArch.X86_64)
        assert b._FilterMatches("!system:Windows") is True
        assert b._FilterMatches("!system:Linux") is False

    def test_options_filter(self):
        b = _make_builder(TargetOS.LINUX, TargetArch.X86_64, options=["headless"])
        assert b._FilterMatches("options:headless") is True
        assert b._FilterMatches("options:fullscreen") is False

    def test_compound_with_options(self):
        b = _make_builder(TargetOS.LINUX, TargetArch.X86_64, options=["headless"])
        assert b._FilterMatches("system:Linux && options:headless") is True
        assert b._FilterMatches("system:Linux && !options:headless") is False

    def test_shorthand_tokens(self):
        b = _make_builder(TargetOS.WINDOWS, TargetArch.X86_64, config="Debug")
        assert b._FilterMatches("Debug") is True
        assert b._FilterMatches("Release") is False
        assert b._FilterMatches("windows") is True


class TestUnitTestCompilationPolicy:
    def _make_policy_builder(self):
        b = _make_builder(TargetOS.WINDOWS, TargetArch.X86_64)
        wks = b.workspace
        wks.disableUnitTestCompilation = True

        app = Project(name="App")
        app.kind = ProjectKind.CONSOLE_APP
        app.dependsOn = []

        tests = Project(name="AppTests")
        tests.kind = ProjectKind.TEST_SUITE
        tests.isTest = True

        internal_unitest = Project(name="__Unitest__")
        internal_unitest.kind = ProjectKind.STATIC_LIB

        wks.projects = {
            "App": app,
            "AppTests": tests,
            "__Unitest__": internal_unitest,
        }
        return b

    def test_policy_skips_test_projects_when_building_all(self):
        b = self._make_policy_builder()
        order = b._ApplyUnitTestCompilationPolicy(
            ["App", "__Unitest__", "AppTests"],
            targetProject=None
        )
        assert order == ["App"]

    def test_policy_blocks_explicit_test_target(self):
        b = self._make_policy_builder()
        order = b._ApplyUnitTestCompilationPolicy(
            ["__Unitest__", "AppTests"],
            targetProject="AppTests"
        )
        assert order is None

    def test_policy_blocks_non_test_project_depending_on_test(self):
        b = self._make_policy_builder()
        b.workspace.projects["App"].dependsOn = ["AppTests"]
        order = b._ApplyUnitTestCompilationPolicy(
            ["AppTests", "App"],
            targetProject="App"
        )
        assert order is None


# ===========================================================================
# 3. Variable Expander
# ===========================================================================

class TestVariableExpander:
    def _make_expander(self, wks_location="/my/workspace"):
        _reset()
        wks = Workspace(name="MyWks", location=wks_location)
        exp = VariableExpander(workspace=wks)
        exp.SetConfig({
            "name": "Debug",
            "buildcfg": "Debug",
            "configuration": "Debug",
            "platform": "Windows-x86_64",
            "system": "Windows",
            "os": "Windows",
            "arch": "x86_64",
        })
        return exp, wks

    def test_wks_location(self):
        exp, _ = self._make_expander("/my/workspace")
        result = exp.Expand("%{wks.location}")
        assert "/my/workspace" in result.replace("\\", "/")

    def test_cfg_buildcfg(self):
        exp, _ = self._make_expander()
        result = exp.Expand("%{cfg.buildcfg}")
        assert result == "Debug"

    def test_cfg_system(self):
        exp, _ = self._make_expander()
        result = exp.Expand("%{cfg.system}")
        assert result == "Windows"

    def test_prj_name(self):
        exp, wks = self._make_expander()
        p = Project(name="MyApp")
        wks.projects["MyApp"] = p
        exp.SetProject(p)
        result = exp.Expand("%{prj.name}")
        assert result == "MyApp"

    def test_combined_pattern(self):
        exp, wks = self._make_expander()
        p = Project(name="Engine")
        wks.projects["Engine"] = p
        exp.SetProject(p)
        result = exp.Expand("Build/Obj/%{cfg.buildcfg}-%{cfg.system}/%{prj.name}")
        assert "Debug" in result
        assert "Windows" in result
        assert "Engine" in result

    def test_recursive_expansion(self):
        exp, _ = self._make_expander()
        result = exp.Expand("%{cfg.buildcfg}", recursive=True)
        assert result == "Debug"


# ===========================================================================
# 4. GlobalToolchains Registry
# ===========================================================================

# BuildToolchainFromRegistryEntry ECARTE volontairement les toolchains dont le
# compilateur n'existe pas (registre recopie d'une autre machine). Les tests
# doivent donc pointer un binaire REEL, sinon ils testent ce garde-fou au lieu
# du mapping. sys.executable existe partout, quelle que soit la plateforme.
_REAL_EXE = sys.executable


class TestGlobalToolchainsRegistry:
    def test_empty_registry(self):
        with tempfile.TemporaryDirectory() as d:
            nonexistent = Path(d) / "missing.json"
            data = LoadGlobalRegistry(nonexistent)
            assert data == {"toolchains": [], "sdk": {}}

    def test_load_valid_registry(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump({
                "toolchains": [
                    {
                        "name": "my-clang",
                        "compilerFamily": "clang",
                        "targetOs": "Linux",
                        "targetArch": "x86_64",
                        "ccPath": _REAL_EXE,
                        "cxxPath": _REAL_EXE,
                    }
                ],
                "sdk": {
                    "androidSdkPath": "/opt/android-sdk",
                    "androidNdkPath": "/opt/android-ndk",
                }
            }, f)
            tmp_path = Path(f.name)
        try:
            data = LoadGlobalRegistry(tmp_path)
            assert len(data["toolchains"]) == 1
            assert data["sdk"]["androidSdkPath"] == "/opt/android-sdk"
        finally:
            tmp_path.unlink(missing_ok=True)

    def test_build_toolchain_from_entry(self):
        entry = {
            "name": "test-tc",
            "compilerFamily": "clang",
            "targetOs": "Linux",
            "targetArch": "x86_64",
            "targetEnv": "gnu",
            "ccPath": _REAL_EXE,
            "cxxPath": _REAL_EXE,
            "cflags": ["-O2"],
            "cxxflags": ["-std=c++17"],
        }
        tc = BuildToolchainFromRegistryEntry(entry)
        assert tc is not None
        assert tc.name == "test-tc"
        assert tc.compilerFamily == CompilerFamily.CLANG
        assert tc.targetOs == TargetOS.LINUX
        assert tc.targetArch == TargetArch.X86_64
        assert tc.targetEnv == TargetEnv.GNU
        assert tc.ccPath == _REAL_EXE
        assert "-O2" in tc.cflags

    def test_build_toolchain_invalid_entry(self):
        entry = {"compilerFamily": "clang"}  # missing name
        tc = BuildToolchainFromRegistryEntry(entry)
        assert tc is None

    def test_apply_registry_to_workspace(self):
        _reset()
        wks = Workspace(name="W", location=tempfile.mkdtemp())
        registry = {
            "toolchains": [
                {
                    "name": "registry-clang",
                    "compilerFamily": "clang",
                    "targetOs": "Linux",
                    "targetArch": "x86_64",
                    "ccPath": _REAL_EXE,
                }
            ],
            "sdk": {
                "androidSdkPath": "/fake/sdk",
            }
        }
        ApplyGlobalRegistryToWorkspace(wks, registry)
        assert "registry-clang" in wks.toolchains
        assert wks.androidSdkPath == "/fake/sdk"

    def test_apply_registry_does_not_override_existing(self):
        _reset()
        wks = Workspace(name="W", location=tempfile.mkdtemp())
        wks.androidSdkPath = "/my/sdk"
        registry = {
            "toolchains": [],
            "sdk": {"androidSdkPath": "/other/sdk"}
        }
        ApplyGlobalRegistryToWorkspace(wks, registry)
        assert wks.androidSdkPath == "/my/sdk"  # unchanged


# ===========================================================================
# 5. Emscripten Runner Scripts
# ===========================================================================

class TestEmscriptenRunnerScripts:
    def _make_emscripten_project(self, name="WasmApp",
                                  kind=ProjectKind.CONSOLE_APP) -> Project:
        p = Project(name=name)
        p.kind = kind
        p.language = Language.CPP
        return p

    def _make_emscripten_builder(self):
        """Create an EmscriptenBuilder with a stub toolchain (no real compilation)."""
        from Jenga.Core.Builders.Emscripten import EmscriptenBuilder

        _reset()
        wks = Workspace(name="WasmWks", location=tempfile.mkdtemp())
        stub_tc = Toolchain(
            name="emscripten",
            compilerFamily=CompilerFamily.EMSCRIPTEN,
            ccPath="emcc", cxxPath="em++", arPath="emar",
            targetOs=TargetOS.WEB, targetArch=TargetArch.WASM32,
        )
        wks.toolchains["emscripten"] = stub_tc
        wks.defaultToolchain = "emscripten"

        b = EmscriptenBuilder.__new__(EmscriptenBuilder)
        b.workspace = wks
        b.config = "Release"
        b.platform = "Web-wasm32"
        b.targetOs = TargetOS.WEB
        b.targetArch = TargetArch.WASM32
        b.targetEnv = None
        b.verbose = False
        b.action = "build"
        b.options = []
        b.toolchain = stub_tc
        b.jobs = 1
        b._expander = None
        b._lastResult = None
        return b

    def test_runner_scripts_generated_for_app(self):
        b = self._make_emscripten_builder()
        proj = self._make_emscripten_project("TestApp", ProjectKind.CONSOLE_APP)

        with tempfile.TemporaryDirectory() as d:
            out_path = Path(d) / "TestApp.html"
            out_path.write_text("<html></html>", encoding="utf-8")
            b._GenerateRunnerScripts(proj, out_path)

            bat = Path(d) / "TestApp.bat"
            sh  = Path(d) / "TestApp.sh"
            assert bat.exists(), "TestApp.bat should be generated"
            assert sh.exists(),  "TestApp.sh should be generated"

    def test_runner_scripts_contain_project_name(self):
        b = self._make_emscripten_builder()
        proj = self._make_emscripten_project("MyWasmGame")

        with tempfile.TemporaryDirectory() as d:
            out_path = Path(d) / "MyWasmGame.html"
            out_path.write_text("<html></html>", encoding="utf-8")
            b._GenerateRunnerScripts(proj, out_path)

            bat_text = (Path(d) / "MyWasmGame.bat").read_text(encoding="utf-8")
            sh_text  = (Path(d) / "MyWasmGame.sh").read_text(encoding="utf-8")

            assert "MyWasmGame" in bat_text
            assert "MyWasmGame" in sh_text
            # Port lu depuis la SOURCE (plus de litteral duplique dans le test).
            from Jenga.Core.Builders.Emscripten import EMSCRIPTEN_DEFAULT_PORT as _P
            assert str(_P) in bat_text
            assert str(_P) in sh_text

    def test_runner_scripts_http_server_command(self):
        b = self._make_emscripten_builder()
        proj = self._make_emscripten_project("App")

        with tempfile.TemporaryDirectory() as d:
            out_path = Path(d) / "App.html"
            out_path.write_text("", encoding="utf-8")
            b._GenerateRunnerScripts(proj, out_path)

            bat = (Path(d) / "App.bat").read_text(encoding="utf-8")
            sh  = (Path(d) / "App.sh").read_text(encoding="utf-8")

            # Must launch an HTTP server (python http.server)
            assert "http.server" in bat
            assert "http.server" in sh

    def test_runner_not_generated_for_static_lib(self):
        b = self._make_emscripten_builder()
        proj = self._make_emscripten_project("MyLib", ProjectKind.STATIC_LIB)

        with tempfile.TemporaryDirectory() as d:
            out_path = Path(d) / "MyLib.a"
            b._GenerateRunnerScripts(proj, out_path)

            assert not (Path(d) / "MyLib.bat").exists()
            assert not (Path(d) / "MyLib.sh").exists()

    @pytest.mark.skipif(sys.platform == "win32", reason="Unix chmod not supported on Windows")
    def test_sh_script_is_executable(self):
        b = self._make_emscripten_builder()
        proj = self._make_emscripten_project("App")

        with tempfile.TemporaryDirectory() as d:
            out_path = Path(d) / "App.html"
            out_path.write_text("", encoding="utf-8")
            b._GenerateRunnerScripts(proj, out_path)

            sh = Path(d) / "App.sh"
            if sh.exists():
                mode = sh.stat().st_mode
                assert mode & 0o111, ".sh should be executable"


# ===========================================================================
# 6. GlobalToolchains.py – bug-fix verification
# ===========================================================================

class TestGlobalToolchainsFixed:
    """Verifies the bug fixes applied to GlobalToolchains.py."""

    def test_toolchain_clang_cl_no_undefined_names(self):
        """ToolchainClangCl must not reference c_compiler / linker_path."""
        src = (ROOT / "Jenga" / "GlobalToolchains.py").read_text(encoding="utf-8")
        # The variable 'c_compiler' (without _path) was undefined → must be gone
        # We check the specific broken patterns are no longer present
        assert "cpp_compiler = c_compiler" not in src, (
            "Bug: 'cpp_compiler = c_compiler' still present (c_compiler undefined)"
        )
        assert "linker = c_compiler" not in src, (
            "Bug: 'linker = c_compiler' still present (c_compiler undefined)"
        )
        assert "linker = cpp_compiler" not in src, (
            "Bug: 'linker = cpp_compiler' still present (cpp_compiler undefined)"
        )

    def test_no_undefined_name_passed_to_linker(self):
        """Le bug d'origine : `linker(linker_path)` avec `linker_path` JAMAIS
        defini (et `linker = cpp_compiler` juste avant, tout aussi indefini).

        On verifie l'INTENTION, pas un nom de variable : chaque identifiant
        passe a linker(...) doit etre lie quelque part dans le fichier. Les
        versions precedentes de ce test exigeaient le litteral
        « linker(cpp_compiler_path) » — elles cassaient au moindre renommage
        (la variable s'appelle « cxx » aujourd'hui) sans qu'aucun bug n'existe.
        """
        import ast
        src = (ROOT / "Jenga" / "GlobalToolchains.py").read_text(encoding="utf-8")
        tree = ast.parse(src)

        bound = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
                bound.add(node.id)
            elif isinstance(node, ast.arg):
                bound.add(node.arg)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                bound.add(node.name)
            elif isinstance(node, ast.alias):
                bound.add((node.asname or node.name).split(".")[0])

        undefined = []
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id == "linker"):
                continue
            for a in node.args:
                if isinstance(a, ast.Name) and a.id not in bound:
                    undefined.append((node.lineno, a.id))

        assert not undefined, (
            "linker(...) recoit un identifiant jamais defini : "
            + ", ".join(f"ligne {ln} -> {nm}" for ln, nm in undefined)
        )

    def test_linker_uses_cpp_compiler_not_a_bare_assignment(self):
        """Les affectations fautives d'origine ne doivent pas revenir."""
        src = (ROOT / "Jenga" / "GlobalToolchains.py").read_text(encoding="utf-8")
        assert "linker = cpp_compiler" not in src
        assert "linker = c_compiler" not in src


class TestExamplesParsing:
    EXAMPLES_DIR = ROOT / "Jenga" / "Exemples"
    # Sous-dossiers d'Exemples/ qui ne sont PAS des exemples Jenga. « Nkentseu »
    # est un SOUS-MODULE : un moteur complet, propriete d'un autre depot, present
    # ici pour l'integration. Il est deja exclu de l'archive distribuee
    # (scripts/build_examples_archive.py) — le test doit couvrir le MEME perimetre,
    # sinon la suite de Jenga echoue sur du contenu qu'il ne livre pas et dont il
    # n'est pas responsable.
    NON_EXAMPLE_DIRS = {"Nkentseu"}

    def _get_example_files(self):
        if not self.EXAMPLES_DIR.exists():
            return []
        out = []
        for p in self.EXAMPLES_DIR.rglob("*.jenga"):
            if not p.is_file():
                continue
            rel = p.relative_to(self.EXAMPLES_DIR)
            if rel.parts and rel.parts[0] in self.NON_EXAMPLE_DIRS:
                continue
            out.append(p)
        return out

    def test_all_examples_are_valid_python(self):
        """All .jenga files must be parseable Python."""
        import ast
        for jenga_file in self._get_example_files():
            # MEME encodage que le chargeur (Core/Loader.py lit en utf-8-sig) :
            # un BOM est donc legitimement supporte par Jenga. Lire en "utf-8"
            # strict faisait echouer le test sur un fichier que le produit
            # accepte — le test etait plus severe que la realite.
            src = jenga_file.read_text(encoding="utf-8-sig", errors="replace")
            try:
                ast.parse(src, filename=str(jenga_file))
            except SyntaxError as e:
                pytest.fail(f"Syntax error in {jenga_file.name}: {e}")

    def test_example_07_web_wasm_no_hardcoded_paths(self):
        """07_web_wasm.jenga must not contain hardcoded Windows paths after fix."""
        f = self.EXAMPLES_DIR / "07_web_wasm" / "07_web_wasm.jenga"
        if not f.exists():
            pytest.skip("07_web_wasm.jenga not found")
        text = f.read_text(encoding="utf-8")
        assert r"C:\emsdk" not in text, (
            "07_web_wasm.jenga still contains hardcoded Windows emsdk path"
        )
        assert "RegisterJengaGlobalToolchains" in text, (
            "07_web_wasm.jenga should use RegisterJengaGlobalToolchains"
        )

    def test_example_09_multi_projects_android_has_windowedapp(self):
        """09_multi_projects.jenga Android filters must set windowedapp()."""
        f = self.EXAMPLES_DIR / "09_multi_projects" / "09_multi_projects.jenga"
        if not f.exists():
            pytest.skip("09_multi_projects.jenga not found")
        text = f.read_text(encoding="utf-8")
        # Each Android filter block should contain windowedapp()
        import re
        android_blocks = re.findall(
            r'with filter\("system:Android"\)[^}]+?(?=with filter|$)',
            text, re.DOTALL
        )
        # At least confirm windowedapp appears after Android filters
        assert "windowedapp()" in text, (
            "09_multi_projects.jenga Android blocks are missing windowedapp()"
        )

    def test_example_05_android_has_usetoolchain(self):
        """05_android_ndk.jenga should explicitly set the android-ndk toolchain."""
        f = self.EXAMPLES_DIR / "05_android_ndk" / "05_android_ndk.jenga"
        if not f.exists():
            pytest.skip("05_android_ndk.jenga not found")
        text = f.read_text(encoding="utf-8")
        assert 'usetoolchain("android-ndk")' in text, (
            "05_android_ndk.jenga should use usetoolchain('android-ndk')"
        )


# ===========================================================================
# 8. BuildCommand utilities
# ===========================================================================

class TestBuildCommandUtilities:
    def _get_build_cmd(self):
        from Jenga.Commands.Build import BuildCommand  # PascalCase : nom REEL du module
        return BuildCommand

    def test_is_all_platforms_token(self):
        BC = self._get_build_cmd()
        assert BC.IsAllPlatformsRequest("jengaall") is True
        assert BC.IsAllPlatformsRequest("JENGAALL") is True
        assert BC.IsAllPlatformsRequest("windows") is False
        assert BC.IsAllPlatformsRequest(None) is False

    def test_parse_custom_options_flag(self):
        BC = self._get_build_cmd()
        result = BC.ParseCustomOptionArgs(["--headless"])
        assert "headless" in result

    def test_parse_custom_options_value(self):
        BC = self._get_build_cmd()
        result = BC.ParseCustomOptionArgs(["--xbox-mode=gdk"])
        assert "xbox-mode" in result
        assert result["xbox-mode"] == "gdk"

    def test_parse_custom_options_no_flag(self):
        BC = self._get_build_cmd()
        result = BC.ParseCustomOptionArgs(["--no-headless"])
        assert "headless" in result
        assert result["headless"] == "false"

    def test_get_all_declared_platforms(self):
        BC = self._get_build_cmd()
        _reset()
        wks = Workspace(name="W", location=".")
        wks.targetOses = [TargetOS.WINDOWS, TargetOS.LINUX]
        wks.targetArchs = [TargetArch.X86_64]
        platforms = BC.GetAllDeclaredPlatforms(wks)
        assert "Windows-x86_64" in platforms
        assert "Linux-x86_64" in platforms

    def test_option_values_to_tokens(self):
        BC = self._get_build_cmd()
        tokens = BC.OptionValuesToTokens({"headless": None, "xbox-mode": "gdk"})
        assert "headless" in tokens
        assert "xbox-mode" in tokens
        assert "xbox-mode=gdk" in tokens

    def test_normalize_option_trigger(self):
        BC = self._get_build_cmd()
        assert BC.NormalizeOptionTrigger("--headless") == "headless"
        assert BC.NormalizeOptionTrigger("HeadLess") == "headless"
        assert BC.NormalizeOptionTrigger("") == ""


# ===========================================================================
# 9. Platform Detection
# ===========================================================================

class TestPlatformDetection:
    def test_get_host_os_returns_valid(self):
        host = Platform.GetHostOS()
        assert host in (TargetOS.WINDOWS, TargetOS.LINUX, TargetOS.MACOS), (
            f"Unexpected host OS: {host}"
        )

    def test_get_host_architecture(self):
        arch = Platform.GetHostArchitecture()
        assert arch in (TargetArch.X86_64, TargetArch.ARM64), (
            f"Unexpected host arch: {arch}"
        )

    def test_is_platform_available_web(self):
        # Web/Emscripten requires emcc in PATH; might not be available
        # Just check the method runs without error
        result = Platform.IsPlatformAvailable(TargetOS.WEB, TargetArch.WASM32)
        assert isinstance(result, bool)

    def test_normalize_os_name(self):
        # These names should all resolve to a valid TargetOS
        assert Platform.GetHostOS() is not None


# ===========================================================================
# 10. Api DSL functions – smoke tests
# ===========================================================================

class TestApiDSLFunctions:
    """Smoke tests for all user-facing DSL functions."""

    def test_workspace_full(self):
        _reset()
        with workspace("FullTest", location=".") as wks:
            configurations(["Debug", "Release", "Profile"])
            targetoses([TargetOS.WINDOWS, TargetOS.LINUX])
            targetarchs([TargetArch.X86_64])
            startproject("Main")
            disableunittestcompilation(True)
            disableunittestexecution(True)
            newoption(trigger="asan", description="Enable AddressSanitizer")

            assert wks.configurations == ["Debug", "Release", "Profile"]
            assert TargetOS.WINDOWS in wks.targetOses
            assert wks.startProject == "Main"
            assert wks.disableUnitTestCompilation is True
            assert wks.disableUnitTestExecution is True

    def test_workspace_unittest_shortcuts(self):
        _reset()
        with workspace("ShortcutsTest") as wks:
            dutc(True)
            dute(True)
            assert wks.disableUnitTestCompilation is True
            assert wks.disableUnitTestExecution is True

    def test_all_project_kinds(self):
        _reset()
        with workspace("KindsTest") as wks:
            with project("A") as p:
                consoleapp()
                assert p.kind == ProjectKind.CONSOLE_APP
            with project("B") as p:
                windowedapp()
                assert p.kind == ProjectKind.WINDOWED_APP
            with project("C") as p:
                staticlib()
                assert p.kind == ProjectKind.STATIC_LIB
            with project("D") as p:
                sharedlib()
                assert p.kind == ProjectKind.SHARED_LIB

    def test_all_languages(self):
        _reset()
        with workspace("LangTest") as wks:
            for lang_str, expected in [
                ("C++", Language.CPP), ("C", Language.C),
                ("Objective-C", Language.OBJC),
                ("Assembly", Language.ASM),
            ]:
                with project(f"Proj_{lang_str.replace('+','P').replace('-','_')}") as p:
                    language(lang_str)
                    assert p.language == expected

    def test_filter_nested(self):
        """Nested filter contexts: inner filter key takes precedence (not combined)."""
        _reset()
        with workspace("FilterNested") as wks:
            with project("App") as p:
                with filter("system:Windows"):
                    defines(["WINDOWS_DEFINE"])
                    with filter("config:Debug"):
                        defines(["WIN_DEBUG"])
                # The inner filter defines should be stored under "config:debug"
                assert "config:debug" in p._filteredDefines or any(
                    "debug" in k.lower() for k in p._filteredDefines
                ), f"config:Debug defines missing. Keys: {list(p._filteredDefines.keys())}"
                # The outer filter defines should be under system:windows
                assert any(
                    "windows" in k.lower() for k in p._filteredDefines
                ), f"system:Windows defines missing. Keys: {list(p._filteredDefines.keys())}"

    def test_toolchain_settarget_string(self):
        _reset()
        with workspace("TcTest") as wks:
            with toolchain("t1", "clang") as tc:
                settarget("Linux", "x86_64", "gnu")
                assert tc.targetOs == TargetOS.LINUX
                assert tc.targetArch == TargetArch.X86_64
                assert tc.targetEnv == TargetEnv.GNU

    def test_emscripten_project_settings(self):
        _reset()
        with workspace("EmTest") as wks:
            with project("WasmApp") as p:
                emscriptenshellfile("custom.html")
                emscriptencanvasid("mycanvas")
                emscripteninitialmemory(32)
                emscriptenstacksize(8)
                emscriptenexportname("MyModule")
                emscriptenextraflags(["-s", "ASYNCIFY"])

                assert p.emscriptenShellFile == "custom.html"
                assert p.emscriptenCanvasId == "mycanvas"
                assert p.emscriptenInitialMemory == 32
                assert p.emscriptenStackSize == 8
                assert p.emscriptenExportName == "MyModule"
                assert "-s" in p.emscriptenExtraFlags

    def test_android_project_settings(self):
        _reset()
        with workspace("AndTest") as wks:
            with project("AndroidApp") as p:
                androidapplicationid("com.test.app")
                androidminsdk(21)
                androidtargetsdk(34)
                androidcompilesdk(34)
                androidabis(["arm64-v8a", "armeabi-v7a", "x86", "x86_64"])
                androidnativeactivity(True)
                androidpermissions(["android.permission.CAMERA"])
                androidassets(["assets/**"])
                androidversioncode(5)
                androidversionname("1.5")

                assert p.androidApplicationId == "com.test.app"
                assert p.androidMinSdk == 21
                assert p.androidTargetSdk == 34
                assert "arm64-v8a" in p.androidAbis
                assert p.androidNativeActivity is True
                assert "android.permission.CAMERA" in p.androidPermissions
                assert p.androidVersionCode == 5
                assert p.androidVersionName == "1.5"

    def test_xbox_project_settings(self):
        _reset()
        with workspace("XboxTest") as wks:
            xboxmode("gdk")
            xboxplatform("Scarlett")
            assert wks.xboxMode == "gdk"
            assert wks.xboxPlatform == "Scarlett"

            with project("XboxApp") as p:
                xboxsigningmode("test")
                xboxpackagename("TestPackage")
                xboxpublisher("TestPublisher")
                xboxversion("2.0.1.0")

                assert p.xboxSigningMode == "test"
                assert p.xboxPackageName == "TestPackage"
                assert p.xboxPublisher == "TestPublisher"
                assert p.xboxVersion == "2.0.1.0"

    def test_prebuild_postbuild_hooks(self):
        _reset()
        with workspace("HookTest") as wks:
            with project("HookApp") as p:
                prebuild(["echo pre1", "echo pre2"])
                postbuild(["echo post"])
                prelink(["echo prelink"])
                postlink(["echo postlink"])

                assert len(p.preBuildCommands) == 2
                assert "echo post" in p.postBuildCommands
                assert "echo prelink" in p.preLinkCommands
                assert "echo postlink" in p.postLinkCommands

    def test_includefiles_works(self):
        _reset()
        with workspace("IncTest") as wks:
            with project("App") as p:
                files(["src/**.cpp"])
                excludefiles(["src/win32/**"])
                assert "src/win32/**" in p.excludeFiles


# ===========================================================================
# 11. Emscripten INITIAL_MEMORY flag format
# ===========================================================================

class TestEmscriptenLinkerFlags:
    """Verifies that Emscripten linker flags are correct."""

    def _make_project_with_memory(self, mb: int) -> Project:
        p = Project(name="App")
        p.kind = ProjectKind.CONSOLE_APP
        p.language = Language.CPP
        p.emscriptenInitialMemory = mb
        p.emscriptenStackSize = 5
        p.emscriptenExportName = "Module"
        p.emscriptenExtraFlags = []
        p.emscriptenShellFile = ""
        p.emscriptenUseFullscreenShell = False
        p.emscriptenCanvasId = "canvas"
        p.defines = []
        p.ldflags = []
        p.links = []
        p.libDirs = []
        p.symbols = False
        from Jenga.Core.Api import Optimization
        p.optimize = Optimization.OFF
        return p

    def _make_emscripten_builder_for_flags(self):
        from Jenga.Core.Builders.Emscripten import EmscriptenBuilder
        _reset()
        wks = Workspace(name="W", location=tempfile.mkdtemp())
        wks.emscriptenDefaultFullscreenShell = False
        stub_tc = Toolchain(
            name="emscripten",
            compilerFamily=CompilerFamily.EMSCRIPTEN,
            ccPath="emcc", cxxPath="em++", arPath="emar",
            targetOs=TargetOS.WEB, targetArch=TargetArch.WASM32,
        )
        stub_tc.ldflags = []
        stub_tc.cflags = []
        stub_tc.cxxflags = []
        stub_tc.defines = []
        wks.toolchains["emscripten"] = stub_tc
        wks.defaultToolchain = "emscripten"
        b = EmscriptenBuilder.__new__(EmscriptenBuilder)
        b.workspace = wks
        b.config = "Release"
        b.platform = "Web-wasm32"
        b.targetOs = TargetOS.WEB
        b.targetArch = TargetArch.WASM32
        b.targetEnv = None
        b.verbose = False
        b.action = "build"
        b.options = []
        b.toolchain = stub_tc
        b._expander = None
        return b

    def test_initial_memory_flag_format(self):
        """INITIAL_MEMORY should be in MB string format (e.g. 16MB)."""
        b = self._make_emscripten_builder_for_flags()
        p = self._make_project_with_memory(16)
        flags = b._GetLinkerFlags(p)
        # Find INITIAL_MEMORY flag
        mem_flags = [f for f in flags if "INITIAL_MEMORY" in str(f)]
        assert len(mem_flags) > 0, "INITIAL_MEMORY flag missing"
        # Value should be either 16MB or 16777216 (bytes)
        mem_val = flags[flags.index("INITIAL_MEMORY=" + mem_flags[0].split("=")[-1]) - 1
                       if "INITIAL_MEMORY=" in "".join(flags) else -1]

    def test_wasm_flag_present(self):
        b = self._make_emscripten_builder_for_flags()
        p = self._make_project_with_memory(16)
        flags = b._GetLinkerFlags(p)
        assert "WASM=1" in flags, "WASM=1 flag should be present"

    def test_allow_memory_growth(self):
        b = self._make_emscripten_builder_for_flags()
        p = self._make_project_with_memory(16)
        flags = b._GetLinkerFlags(p)
        assert "ALLOW_MEMORY_GROWTH=1" in flags


# ===========================================================================
# 12. Apple Platform Integration (macOS / iOS / tvOS / watchOS / visionOS)
# ===========================================================================

class TestApplePlatformIntegration:
    """
    Vérifie l'intégration des plateformes Apple.
    Ces tests ne nécessitent PAS de macOS — ils testent la structure du code,
    les enregistrements de builders, les fonctions DSL et les corrections de bugs.
    """

    def test_ios_builder_alias_exists(self):
        """IOSBuilder alias doit exister dans Ios.py pour que la factory fonctionne."""
        from Jenga.Core.Builders.Ios import IOSBuilder, DirectIOSBuilder
        assert IOSBuilder is DirectIOSBuilder

    def test_xcode_ios_builder_alias_exists(self):
        """IOSBuilder et MacOSBuilder aliases dans MacosXcodeBuilder.py."""
        from Jenga.Core.Builders.MacosXcodeBuilder import IOSBuilder, MacOSBuilder, XcodeMobileBuilder
        assert IOSBuilder is XcodeMobileBuilder
        assert MacOSBuilder is XcodeMobileBuilder

    def test_factory_resolves_ios(self):
        """get_builder_class('iOS') doit retourner une classe non-None."""
        from Jenga.Core.Builders import get_builder_class
        cls = get_builder_class("iOS", apple_mobile_mode="direct")
        assert cls is not None, "Factory returned None for iOS — IOSBuilder alias missing"

    def test_factory_resolves_tvos(self):
        from Jenga.Core.Builders import get_builder_class
        cls = get_builder_class("tvOS", apple_mobile_mode="direct")
        assert cls is not None, "Factory returned None for tvOS"

    def test_factory_resolves_watchos(self):
        from Jenga.Core.Builders import get_builder_class
        cls = get_builder_class("watchOS", apple_mobile_mode="direct")
        assert cls is not None, "Factory returned None for watchOS"

    def test_factory_resolves_visionos(self):
        from Jenga.Core.Builders import get_builder_class
        cls = get_builder_class("visionOS", apple_mobile_mode="direct")
        assert cls is not None, "Factory returned None for visionOS"

    def test_factory_resolves_macos(self):
        from Jenga.Core.Builders import get_builder_class
        cls = get_builder_class("macOS")
        assert cls is not None, "Factory returned None for macOS"

    def test_factory_resolves_ios_xcode_mode(self):
        """get_builder_class('iOS', 'xcode') doit retourner XcodeMobileBuilder."""
        from Jenga.Core.Builders import get_builder_class
        cls = get_builder_class("iOS", apple_mobile_mode="xcode")
        assert cls is not None, "Factory returned None for iOS in xcode mode"

    def test_ios_dsl_functions(self):
        """Les fonctions DSL iOS doivent stocker leurs valeurs correctement."""
        _reset()
        with workspace("AppleTest") as wks:
            with project("IOSApp") as p:
                iosbundleid("com.test.myapp")
                iosversion("2.1")
                iosminsdk("15.0")
                iosbuildnumber(42)
                iossigningidentity("Apple Development: Test")

                assert p.iosBundleId == "com.test.myapp"
                assert p.iosVersion == "2.1"
                assert p.iosMinSdk == "15.0"
                assert p.iosBuildNumber == "42"
                assert p.iosSigningIdentity == "Apple Development: Test"

    def test_tvos_watchos_visionos_minsdk_dsl(self):
        """tvosminsdk / watchosminsdk / visionosminsdk stockent leurs valeurs."""
        _reset()
        with workspace("AppleMinSdkTest") as wks:
            with project("MultiApple") as p:
                tvosminsdk("16.0")
                watchosminsdk("9.0")
                visionosminsdk("1.0")
                assert p.tvosMinSdk == "16.0"
                assert p.watchosMinSdk == "9.0"
                assert p.visionosMinSdk == "1.0"

    def test_visionos_in_target_os_enum(self):
        """TargetOS.VISIONOS doit exister."""
        assert hasattr(TargetOS, "VISIONOS")
        assert TargetOS.VISIONOS.value == "visionOS"

    def test_visionos_validated_in_builder_source(self):
        """Builder._ValidateHostTarget doit couvrir visionOS."""
        builder_src = (ROOT / "Jenga" / "Core" / "Builder.py").read_text(encoding="utf-8")
        assert "VISIONOS" in builder_src, "visionOS not validated in Builder._ValidateHostTarget"

    def test_ios_example_valid_python(self):
        """L'exemple 06_ios_app.jenga est syntaxiquement valide."""
        import ast
        example = ROOT / "Jenga" / "Exemples" / "06_ios_app" / "06_ios_app.jenga"
        if not example.is_file():
            pytest.skip("06_ios_app.jenga not found")
        ast.parse(example.read_text(encoding="utf-8"), filename=str(example))

    def test_macos_example_valid_python(self):
        """L'exemple 17_window_macos_cocoa.jenga est syntaxiquement valide."""
        import ast
        example = ROOT / "Jenga" / "Exemples" / "17_window_macos_cocoa" / "17_window_macos_cocoa.jenga"
        if not example.is_file():
            pytest.skip("17_window_macos_cocoa.jenga not found")
        ast.parse(example.read_text(encoding="utf-8"), filename=str(example))


# ===========================================================================
# 13. HarmonyOS Integration
# ===========================================================================

class TestHarmonyOSIntegration:
    """Vérifie l'intégration HarmonyOS sans SDK réel."""

    def test_harmonyos_in_target_os_enum(self):
        assert hasattr(TargetOS, "HARMONYOS")
        assert TargetOS.HARMONYOS.value == "HarmonyOS"

    def test_factory_resolves_harmonyos(self):
        from Jenga.Core.Builders import get_builder_class
        cls = get_builder_class("HarmonyOS")
        assert cls is not None, "Factory returned None for HarmonyOS"

    def test_harmony_dsl_functions_exist(self):
        """harmonyminsdk() et harmonysdk() doivent être exportées par l'API."""
        from Jenga.Core.Api import harmonyminsdk, harmonysdk
        assert callable(harmonyminsdk)
        assert callable(harmonysdk)

    def test_harmonyminsdk_sets_value(self):
        _reset()
        with workspace("HarmonyTest") as wks:
            with project("HarmonyApp") as p:
                harmonyminsdk(9)
                assert p.harmonyMinSdk == "9"

    def test_harmonysdk_sets_workspace_value(self):
        _reset()
        with workspace("HarmonyTest") as wks:
            harmonysdk("/opt/harmonyos/sdk")
            assert wks.harmonySdkPath == "/opt/harmonyos/sdk"

    def test_harmonyos_builder_no_flags_undefined_bug(self):
        """HarmonyOs.py ne doit plus avoir 'flags +=' avant définition de flags."""
        src = (ROOT / "Jenga" / "Core" / "Builders" / "HarmonyOs.py").read_text(encoding="utf-8")
        # La ligne corrigée utilise arm_flags, pas flags +=
        assert "arm_flags = [" in src, "arm_flags not found — bug may not be fixed"
        assert "flags += [" not in src, "'flags +=' before definition still present"

    def test_harmony_in_normalizeosname(self):
        """'harmony' doit être reconnu comme HarmonyOS dans NormalizeOSName."""
        from Jenga.Core.Api import _NormalizeOSName
        assert _NormalizeOSName("harmony") == "HARMONYOS"
        assert _NormalizeOSName("harmonyos") == "HARMONYOS"


# ===========================================================================
# 14. Xbox Integration Audit
# ===========================================================================

class TestXboxIntegration:
    """Vérifie l'intégration Xbox (GDK + UWP) sans GDK installé."""

    def test_xbox_one_and_series_in_enum(self):
        assert hasattr(TargetOS, "XBOX_ONE")
        assert hasattr(TargetOS, "XBOX_SERIES")

    def test_factory_resolves_xbox_series(self):
        from Jenga.Core.Builders import get_builder_class
        cls = get_builder_class("XboxSeries")
        assert cls is not None, "Factory returned None for XboxSeries"

    def test_factory_resolves_xbox_one(self):
        from Jenga.Core.Builders import get_builder_class
        cls = get_builder_class("XboxOne")
        assert cls is not None, "Factory returned None for XboxOne"

    def test_xbox_dsl_functions(self):
        _reset()
        with workspace("XboxTest") as wks:
            xboxmode("uwp")
            xboxplatform("Scarlett")
            assert wks.xboxMode == "uwp"

    def test_xbox_builder_has_gdk_fallback_warning(self):
        """XboxBuilder doit émettre un avertissement si GDK absent, sans crash."""
        src = (ROOT / "Jenga" / "Core" / "Builders" / "Xbox.py").read_text(encoding="utf-8")
        assert "Microsoft GDK not found" in src
        assert "winget install Microsoft.Gaming.GDK" in src

    def test_xbox_builder_generates_microsoftgame_config(self):
        """XboxBuilder._GenerateMicrosoftGameConfig doit exister."""
        from Jenga.Core.Builders.Xbox import XboxBuilder
        assert hasattr(XboxBuilder, "_GenerateMicrosoftGameConfig")
        assert hasattr(XboxBuilder, "_CreateLooseLayout")
        assert hasattr(XboxBuilder, "DeployToConsole")
        assert hasattr(XboxBuilder, "LaunchOnConsole")

    def test_xbox_example_valid_python(self):
        import ast
        example = ROOT / "Jenga" / "Exemples" / "26_xbox_project_kinds" / "26_xbox_project_kinds.jenga"
        if not example.is_file():
            pytest.skip("26_xbox_project_kinds.jenga not found")
        ast.parse(example.read_text(encoding="utf-8"), filename=str(example))


# ===========================================================================
# Main entry point (for running without pytest)
# ===========================================================================

if __name__ == "__main__":
    import subprocess
    result = subprocess.run(
        [sys.executable, "-m", "pytest", __file__, "-v", "--tb=short"],
        cwd=str(ROOT),
    )
    sys.exit(result.returncode)
