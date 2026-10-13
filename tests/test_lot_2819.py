#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_lot_2819.py
======================
AUTEUR : TEUGUIA TADJUIDJE Rodolf Séderis — Rihen

Banc de 2.8.19 : six retours de terrain d'octobre 2026.

  (c) LE CADRE D'ERREUR VIDE. Un compilateur mort sans ecrire une ligne (le clang de MSYS2 lance
      depuis PowerShell, ses DLL hors du PATH) donnait un cadre rouge sans rien dedans. Le cadre dit
      la commande, le code de retour et ce qu'il veut dire. Une exception pendant une compilation
      n'affiche plus « Compiled module ».
  (d) `--toolchain` pour run, rebuild, test, gdb et clean : seul `build` le connaissait.
  (f) `run` sans `--platform` prend la machine hote, comme `build` : sous Linux et macOS il cherchait
      l'executable Windows.
  (e) Les flux standard peuvent manquer : sans console, sys.stdout et sys.stderr valent None.
  (b) Le Jenga du systeme trouve le compilateur d'un NKCode present sur la machine.
  (a) Quand aucune chaine ne lie la bibliotheque C++ d'un kit, le refus dit quoi faire.

Chaque temoin est ROUGE sur 2.8.18 (voir le journal des versions pour le compte).

Usage :
  python -m pytest tests/test_lot_2819.py -v
"""
import io
import os
import shutil
import subprocess
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from Jenga.Core.Api import TargetOS
from Jenga.Core.Builder import Builder
from Jenga.Core.Toolchains import ToolchainManager
from Jenga.Utils.Process import ProcessResult
from Jenga.Utils.Reporter import BuildLogger

_CXX = shutil.which("clang++") or shutil.which("g++")
_AVEC_COMPILATEUR = pytest.mark.skipif(_CXX is None, reason="aucun compilateur C++ GNU (clang++/g++) dans le PATH")
_WINDOWS = pytest.mark.skipif(sys.platform != "win32", reason="propre a Windows")


def _jenga(root: Path, *args: str, env_plus=None) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    env["PYTHONIOENCODING"] = "utf-8"
    env.update(env_plus or {})
    extra = ["--no-daemon"] if args and args[0] in ("build", "rebuild", "run", "test", "clean") else []
    return subprocess.run([sys.executable, "-m", "Jenga", *args, *extra], cwd=str(root), env=env,
                          capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600)


def _sortie(r: subprocess.CompletedProcess) -> str:
    import re
    return re.sub(r"\x1b\[[0-9;]*m", "", (r.stdout or "") + (r.stderr or ""))


APP = """from Jenga import *

with workspace("W"):
    configurations(["Debug", "Release"])
{tete}
    with project("App"):
        consoleapp()
        language("C++")
        files(["src/**.cpp"])
{corps}
"""


def _app(tmp: Path, corps: str = "", tete: str = "", source: str = "int main() { return 0; }\n") -> Path:
    (tmp / "src").mkdir(parents=True, exist_ok=True)
    (tmp / "src" / "main.cpp").write_text(source, encoding="utf-8")
    (tmp / "W.jenga").write_text(APP.format(corps=corps, tete=tete), encoding="utf-8")
    return tmp


# ── (c) le cadre d'erreur vide ───────────────────────────────────────────────
def test_c1_a_silent_failure_says_the_code_and_the_command():
    s = BuildLogger._DireSilence(ProcessResult(1, "", "", "clang++ -c a.cpp -o a.o"), "Le compilateur")
    assert "sans rien ecrire" in s and "Code de retour : 1." in s
    assert "Commande : clang++ -c a.cpp -o a.o" in s


@_WINDOWS
def test_c2_a_loader_failure_is_named_not_started():
    s = BuildLogger._DireSilence(ProcessResult(-1073741515, "", "", "clang++ -c a.cpp"), "Le compilateur")
    assert "0xC0000135" in s and "n'a PAS demarre" in s and "DLL" in s
    assert "--toolchain" in s  # l'issue est dite
    s = BuildLogger._DireSilence(ProcessResult(-1073741819, "", "", "ld -o a"), "L'editeur de liens")
    assert "0xC0000005" in s and "plante" in s and s.startswith("L'editeur de liens")


def test_c3_the_compile_frame_is_never_empty(capsys):
    journal = BuildLogger("App")
    journal.SetTotal(1)
    capsys.readouterr()
    journal.LogCompile("src/a.cpp", ProcessResult(3, "", "", "clang++ -c src/a.cpp"))
    s = capsys.readouterr().out
    assert "sans rien ecrire" in s and "Code de retour : 3." in s and "clang++ -c src/a.cpp" in s
    assert journal.failed == 1


def test_c4_a_compiler_that_speaks_is_left_alone(capsys):
    journal = BuildLogger("App")
    journal.SetTotal(1)
    capsys.readouterr()
    journal.LogCompile("src/a.cpp", ProcessResult(1, "", "src/a.cpp:3:5: error: expected ';'\n", "clang++ -c src/a.cpp"))
    s = capsys.readouterr().out
    assert "expected ';'" in s and "sans rien ecrire" not in s and "Commande :" not in s


def test_c5_a_silent_link_failure_gets_its_frame(capsys):
    journal = BuildLogger("App")
    capsys.readouterr()
    journal.LogLink("Build/Bin/App.exe", ProcessResult(5, "", "", "clang++ a.o -o App.exe"))
    s = capsys.readouterr().out
    assert "L'editeur de liens s'est arrete sans rien ecrire" in s and "Code de retour : 5." in s
    assert "clang++ a.o -o App.exe" in s


def test_c6_an_exception_is_a_failure_not_a_compiled_module(capsys):
    r = Builder._EchecDepuisException(FileNotFoundError("Command not found: zz++ -c a.cpp"))
    assert r.returnCode == 127 and "Command not found: zz++" in r.stderr
    assert Builder._EchecDepuisException(TimeoutError()).returnCode == 1
    assert Builder._EchecDepuisException(TimeoutError()).stderr == "TimeoutError"  # jamais vide
    journal = BuildLogger("App")
    journal.SetTotal(1)
    capsys.readouterr()
    journal.LogCompile("src/a.cpp", r)
    s = capsys.readouterr().out
    assert "Command not found: zz++" in s and "Compiled module" not in s and journal.failed == 1


# ── (d) --toolchain partout ─────────────────────────────────────────────────
@pytest.mark.parametrize("commande", ["run", "rebuild", "test", "gdb", "clean"])
def test_d1_every_building_command_knows_the_option(tmp_path, commande):
    s = _sortie(_jenga(tmp_path, commande, "--help"))
    assert "--toolchain" in s, s


@_AVEC_COMPILATEUR
def test_d2_the_option_reaches_the_build(tmp_path):
    root = _app(tmp_path)
    # Un nom inconnu : `build` le dit et retombe sur la resolution automatique. Si la phrase sort,
    # c'est que l'option est arrivee jusqu'a la construction.
    phrase = "Toolchain 'pas-une-chaine'"
    r = _jenga(root, "rebuild", "--toolchain", "pas-une-chaine")
    assert r.returncode == 0 and phrase in _sortie(r), _sortie(r)
    r = _jenga(root, "run", "--build", "--no-console", "--toolchain", "pas-une-chaine")
    assert phrase in _sortie(r) and "unrecognized arguments" not in _sortie(r), _sortie(r)
    r = _jenga(root, "clean", "--toolchain", "pas-une-chaine")
    assert r.returncode == 0 and "unrecognized arguments" not in _sortie(r), _sortie(r)


# ── (f) run sans --platform : la machine hote ───────────────────────────────
@_AVEC_COMPILATEUR
def test_f1_run_picks_the_host_like_build(tmp_path):
    from Jenga.Core.Platform import Platform
    hote = Platform.GetHostOS()
    autre = TargetOS.LINUX if hote != TargetOS.LINUX else TargetOS.WINDOWS
    # l'AUTRE systeme est declare en premier : c'est lui que `run` prenait.
    root = _app(tmp_path, tete=f"    targetoses([TargetOS.{autre.name}, TargetOS.{hote.name}])\n",
                source='#include <cstdio>\nint main() { std::puts("ICI_L_HOTE"); return 0; }\n')
    r = _jenga(root, "build", "--config", "Debug")
    assert r.returncode == 0, _sortie(r)
    r = _jenga(root, "run", "--no-console")
    assert r.returncode == 0 and "ICI_L_HOTE" in _sortie(r), _sortie(r)


# ── (e) sans console ───────────────────────────────────────────────────────
def test_e1_run_sees_no_terminal_when_there_is_no_stream(monkeypatch):
    from Jenga.Commands.Run import RunCommand
    monkeypatch.setattr(sys, "stdout", None)
    assert RunCommand._SansTerminal() is True
    monkeypatch.setattr(sys, "stdout", io.StringIO())
    assert RunCommand._SansTerminal() is True
    monkeypatch.setattr(sys, "stdout", types.SimpleNamespace(isatty=lambda: True))
    assert RunCommand._SansTerminal() is False


def test_e2_the_package_lives_without_standard_streams(tmp_path):
    # Un processus a part, flux retires AVANT tout import : ce que vit Jenga lance par pythonw ou par
    # une application fenetree. Le temoin est ecrit dans un fichier, il n'y a plus de sortie.
    temoin = tmp_path / "temoin.txt"
    code = (
        "import sys\n"
        "sys.stdout = None\n"
        "sys.stderr = None\n"
        f"sys.path.insert(0, {str(ROOT)!r})\n"
        "import Jenga.Commands.Docs\n"
        "from Jenga.Utils.Colored import Colored\n"
        "Colored._supportsColor = None\n"
        "Colored._isWindows = False\n"  # la branche « Unix-like », quel que soit l'hote
        "assert Colored._DetectColorSupport() is False\n"
        "Colored.PrintInfo('rien ne doit lever')\n"
        "from Jenga.Commands.Run import RunCommand\n"
        "assert RunCommand._SansTerminal() is True\n"
        f"open({str(temoin)!r}, 'w').write('vivant')\n"
    )
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=120)
    assert r.returncode == 0 and temoin.is_file() and temoin.read_text() == "vivant", (r.returncode, r.stderr)


# ── (b) le compilateur de NKCode ────────────────────────────────────────────
def test_b1_nkcode_folders_come_in_order(tmp_path, monkeypatch):
    local = tmp_path / "Local"
    (local / "NKCode").mkdir(parents=True)
    (local / "NKCode" / "emplacement.cfg").write_text(
        "# ecrit par NKCode a son demarrage\ndossier = D:\\Outils\\NKCode\n autre = rien\nDossier=\"E:\\NKCode 2\"\n",
        encoding="utf-8")
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    monkeypatch.setenv("JENGA_NKCODE_DIR", str(tmp_path / "designe"))
    monkeypatch.setattr(ToolchainManager, "_NkCodeDepuisLeRegistre", staticmethod(lambda: [Path("C:/installe")]))
    assert ToolchainManager.DossiersDeNkCode() == [
        tmp_path / "designe", Path("D:\\Outils\\NKCode"), Path("E:\\NKCode 2"), Path("C:/installe"),
        local / "Programs" / "NKCode"]
    # rien de pose : la liste est vide, et rien ne leve
    monkeypatch.delenv("JENGA_NKCODE_DIR")
    monkeypatch.delenv("LOCALAPPDATA")
    monkeypatch.setattr(ToolchainManager, "_NkCodeDepuisLeRegistre", staticmethod(lambda: []))
    assert ToolchainManager.DossiersDeNkCode() == []


def _un_nkcode() -> str:
    """Un vrai dossier NKCode avec son compilateur, pour le temoin b2 : JENGA_TEST_NKCODE le designe."""
    d = os.environ.get("JENGA_TEST_NKCODE", "").strip()
    if d and (Path(d) / "tools" / "compilers" / "llvm-mingw" / "bin" / "x86_64-w64-mingw32-clang++.exe").is_file():
        return d
    return ""


@_WINDOWS
@pytest.mark.skipif(not _un_nkcode(), reason="JENGA_TEST_NKCODE ne designe pas un dossier NKCode avec son compilateur")
def test_b2_the_compiler_of_a_nkcode_is_found_and_links_libcxx(tmp_path, monkeypatch):
    # Le PATH du systeme seul, aucune variable qui designe llvm-mingw : comme dans le PowerShell d'un etudiant.
    racine = os.environ.get("SystemRoot", r"C:\Windows")
    monkeypatch.setenv("PATH", os.pathsep.join([os.path.join(racine, "System32"), racine]))
    for v in ("LLVM_MINGW_BIN", "JENGA_COMPILERS_DIR", "JENGA_NKCODE_DIR"):
        monkeypatch.delenv(v, raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))  # ni emplacement.cfg, ni dossier par defaut
    monkeypatch.setattr(ToolchainManager, "_NkCodeDepuisLeRegistre", staticmethod(lambda: []))
    assert "llvm-mingw" not in [t.name for t in ToolchainManager.DetectWindowsGnuInstallations()]
    # NKCode ecrit ou il est : le compilateur est trouve.
    (tmp_path / "NKCode").mkdir()
    (tmp_path / "NKCode" / "emplacement.cfg").write_text("dossier = " + _un_nkcode() + "\n", encoding="utf-8")
    trouvees = {t.name: t for t in ToolchainManager.DetectWindowsGnuInstallations()}
    assert "llvm-mingw" in trouvees, list(trouvees)
    assert ToolchainManager.DescribeCompiler(trouvees["llvm-mingw"])[1] == "libc++"


# ── (a) le refus dit quoi faire ───────────────────────────────────────────
def test_a1_no_matching_toolchain_still_has_a_way_out():
    windows = types.SimpleNamespace(targetOs=TargetOS.WINDOWS)
    s = "\n".join(Builder._IssuesSansChaine(windows, "libc++"))
    assert "Aucune chaine de cette machine ne lie libc++" in s
    assert "NKCode" in s and "tools\\jenga.cmd" in s and "JENGA_NKCODE_DIR" in s and "--toolchain llvm-mingw" in s
    s = "\n".join(Builder._IssuesSansChaine(windows, "libstdc++"))
    assert "MSYS2" in s and "msys2-ucrt64-gcc" in s and "NKCode" not in s
    linux = types.SimpleNamespace(targetOs=TargetOS.LINUX)
    assert Builder._IssuesSansChaine(linux, "libc++") == [
        "  Aucune chaine de cette machine ne lie libc++ (`jenga info` liste celles qui sont la)."]


@_AVEC_COMPILATEUR
def test_a2_the_refusal_always_names_a_next_step(tmp_path):
    autre = "libc++" if ToolchainManager.StdlibOf(_CXX) == "libstdc++" else "libstdc++"
    root = _app(tmp_path, f'        kitrequire("Faux", stdlib="{autre}")\n')
    r = _jenga(root, "build", "--config", "Debug")
    s = _sortie(r)
    assert r.returncode != 0 and "Le kit Faux a ete compile avec " + autre in s, s
    # soit une chaine de la machine convient et elle est nommee, soit le refus dit ou en trouver une
    assert ("Choisissez une chaine qui lie " + autre in s) or ("Aucune chaine de cette machine ne lie " + autre in s), s
