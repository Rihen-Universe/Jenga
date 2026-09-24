# AUTEUR : TEUGUIA TADJUIDJE Rodolf Séderis — Rihen
#
# Detection des compilateurs : repli MSYS2 et diagnostic de refus (2.8.3).
#
# Cas qui a motive ces tests : un PATH pointant sur
# C:\msys64\ucrt64\x86_64-w64-mingw32\bin (binutils seuls) au lieu de
# C:\msys64\ucrt64\bin. Jenga repondait « No suitable toolchain found » sans
# dire ce qu'il avait cherche, alors que clang et g++ etaient installes.
import sys
from pathlib import Path

import pytest

from Jenga.Core.Toolchains import ToolchainManager as TM
from Jenga.Utils import Process


@pytest.fixture(autouse=True)
def caches_vides():
    """Les caches de detection vivent le temps du processus : on les isole."""
    TM._cacheRunnable.clear()
    TM._diagnostics.clear()
    yield
    TM._cacheRunnable.clear()
    TM._diagnostics.clear()


def test_introuvable_est_note(monkeypatch):
    monkeypatch.setattr(TM, "_WindowsFallbackDirs", staticmethod(lambda: []))
    assert TM._FirstRunnable(["compilateur-qui-n-existe-pas-2c9f"]) is None
    assert TM._diagnostics["compilateur-qui-n-existe-pas-2c9f"].startswith("not found in PATH")


def test_repli_msys2_trouve_hors_path(monkeypatch, tmp_path):
    # Un « compilateur » absent du PATH, present dans un dossier de repli.
    faux = tmp_path / "fauxcc.exe"
    faux.write_bytes(b"")
    monkeypatch.setattr(TM, "_WindowsFallbackDirs", staticmethod(lambda: [tmp_path]))
    monkeypatch.setattr(Process, "Which", staticmethod(lambda name: None))
    assert TM._FindExecutable("fauxcc") == str(faux)


def test_sans_repli_rien_n_est_trouve(monkeypatch, tmp_path):
    # Contre-epreuve du precedent : meme fichier, repli desactive -> None.
    (tmp_path / "fauxcc.exe").write_bytes(b"")
    monkeypatch.setattr(TM, "_WindowsFallbackDirs", staticmethod(lambda: []))
    monkeypatch.setattr(Process, "Which", staticmethod(lambda name: None))
    assert TM._FindExecutable("fauxcc") is None


def test_trouve_mais_version_echoue_est_note(monkeypatch):
    # Python lui-meme, avec une option inconnue : trouve, mais la sonde echoue.
    monkeypatch.setattr(TM, "_WindowsFallbackDirs", staticmethod(lambda: []))
    assert TM._FirstRunnable([sys.executable], version_arg="--option-inconnue-2c9f") is None
    etat = TM._diagnostics[sys.executable]
    assert etat.startswith("found ") and "failed (exit" in etat


def test_trouve_et_repond_est_retenu(monkeypatch):
    monkeypatch.setattr(TM, "_WindowsFallbackDirs", staticmethod(lambda: []))
    assert TM._FirstRunnable([sys.executable]) is not None
    assert TM._diagnostics[sys.executable].startswith("OK: ")


def test_description_liste_chaque_candidat(monkeypatch):
    monkeypatch.setattr(TM, "_WindowsFallbackDirs", staticmethod(lambda: []))
    TM._FirstRunnable(["compilateur-qui-n-existe-pas-2c9f"])
    texte = TM.DescribeDetection()
    assert "host:" in texte
    assert "compilateur-qui-n-existe-pas-2c9f: not found in PATH" in texte


def test_outil_pris_a_cote_du_compilateur(monkeypatch, tmp_path):
    (tmp_path / "clang.exe").write_bytes(b"")
    ar = tmp_path / "llvm-ar.exe"
    ar.write_bytes(b"")
    # Un autre ar « plus haut dans le PATH » ne doit pas l'emporter.
    monkeypatch.setattr(Process, "Which", staticmethod(lambda name: r"C:\ailleurs\ar.exe"))
    assert TM._ToolNextTo(str(tmp_path / "clang.exe"), ["llvm-ar", "ar"]) == str(ar)
