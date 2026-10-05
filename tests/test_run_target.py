#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_run_target.py
========================
AUTEUR : TEUGUIA TADJUIDJE Rodolf Séderis — Rihen

Banc de `jenga run --target` sur ordinateur.

`jenga build --target X` nomme le PROJET ; `jenga run --target X` ignorait ce
nom (reserve au mobile) et lancait le premier executable du workspace, sans
le dire : `--target TD` lancait Snake. Desormais, sur ordinateur, `--target`
nomme le projet ; sur mobile il reste l'appareil.

Deux etages, sans compilateur :
  1. la regle seule (`RunCommand._TargetCommeProjet`) ;
  2. de bout en bout : un workspace a deux applications, Snake declaree AVANT
     TD, rien de construit. `jenga run --target TD` doit chercher l'executable
     de TD (« Executable not found: …TD… ») et jamais celui de Snake. Le
     negatif est dans le meme banc : sans `--target`, c'est bien Snake qui est
     cherche, et le choix est DIT.

Usage :
  py -3.14 -m pytest tests/test_run_target.py -v
"""
import argparse
import os
import subprocess
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pytest
from Jenga.Commands.Run import RunCommand


def _parsed(project=None, target=None, platform=None):
    return argparse.Namespace(project=project, target=target, platform=platform)


class TestRegle:
    def test_target_seul_devient_le_projet(self):
        p = _parsed(target="TD")
        assert RunCommand._TargetCommeProjet(p) is None
        assert p.project == "TD" and p.target is None

    def test_meme_nom_des_deux_cotes_accepte(self):
        p = _parsed(project="TD", target="TD")
        assert RunCommand._TargetCommeProjet(p) is None
        assert p.project == "TD"

    def test_desaccord_refuse_en_le_disant(self):
        msg = RunCommand._TargetCommeProjet(_parsed(project="Snake", target="TD"))
        assert msg and "Snake" in msg and "TD" in msg

    @pytest.mark.parametrize("plateforme", ["android", "Android", "ios"])
    def test_mobile_garde_l_appareil(self, plateforme):
        p = _parsed(target="emulator-5554", platform=plateforme)
        assert RunCommand._TargetCommeProjet(p) is None
        assert p.target == "emulator-5554" and p.project is None

    def test_sans_target_rien_ne_change(self):
        p = _parsed(project="Snake")
        assert RunCommand._TargetCommeProjet(p) is None
        assert p.project == "Snake"


_WORKSPACE = textwrap.dedent("""\
    from Jenga import *
    from Jenga.GlobalToolchains import *

    with workspace("RunTargetBench"):
        configurations(["Debug"])
        targetoses([TargetOS.WINDOWS, TargetOS.LINUX, TargetOS.MACOS])
        targetarchs([TargetArch.X86_64, TargetArch.ARM64])
        RegisterJengaGlobalToolchains()

        for _name in ("Snake", "TD"):
            with project(_name):
                consoleapp()
                language("C++")
                files(["main.cpp"])
""")


def _jenga(root: Path, *args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(
        [sys.executable, "-m", "Jenga", "run", *args, "--no-daemon",
         "--jenga-file", str(root / "RunTargetBench.jenga")],
        cwd=str(root), env=env, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=300,
    )


@pytest.fixture()
def wks(tmp_path):
    (tmp_path / "RunTargetBench.jenga").write_text(_WORKSPACE, encoding="utf-8")
    (tmp_path / "main.cpp").write_text("int main(){return 0;}\n", encoding="utf-8")
    return tmp_path


def _exe_cherche(r: subprocess.CompletedProcess) -> str:
    sortie = r.stdout + r.stderr
    lignes = [l for l in sortie.splitlines() if "Executable not found" in l]
    assert lignes, f"pas de ligne « Executable not found » :\n{sortie}"
    return lignes[0]


class TestBoutEnBout:
    def test_target_lance_le_projet_nomme(self, wks):
        r = _jenga(wks, "--target", "TD")
        ligne = _exe_cherche(r)
        assert "TD" in ligne and "Snake" not in ligne, ligne
        assert r.returncode != 0

    def test_negatif_sans_target_premier_executable_dit(self, wks):
        r = _jenga(wks)
        ligne = _exe_cherche(r)
        assert "Snake" in ligne, ligne
        assert "running 'Snake'" in r.stdout + r.stderr

    def test_target_inconnu_refuse(self, wks):
        r = _jenga(wks, "--target", "Inexistant")
        sortie = r.stdout + r.stderr
        assert "Project 'Inexistant' not found" in sortie, sortie
        assert "Snake" not in sortie
        assert r.returncode != 0


if __name__ == "__main__":
    sys.exit(subprocess.run(
        [sys.executable, "-m", "pytest", __file__, "-v", "--tb=short"], cwd=str(ROOT)
    ).returncode)
