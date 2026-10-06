# -*- coding: utf-8 -*-
"""Le cache des sondes « ce compilateur repond-il ? » (2.8.14).

`jenga build` sans rien a faire durait 2,0 s, dont 1,0 s a relancer 12
compilateurs. Un succes est memorise 24 h, mais la CLE doit tomber des que
quelque chose a pu changer : l'executable (date, taille), le PATH, le temps.
Un echec n'est jamais memorise.
"""
import json
import os
import time

import pytest

from Jenga.Core.Toolchains import ToolchainManager


@pytest.fixture
def cache(tmp_path, monkeypatch):
    fichier = tmp_path / "sondes.json"
    monkeypatch.delenv("JENGA_SONDES_SANS_CACHE", raising=False)
    monkeypatch.setenv("JENGA_SONDES_CACHE", str(fichier))
    monkeypatch.setenv("PATH", "C:\\un;C:\\deux")
    ToolchainManager._sondes = None
    ToolchainManager._sondesModifiees = False
    yield fichier
    ToolchainManager._sondes = None
    ToolchainManager._sondesModifiees = False


def _exe(tmp_path, contenu=b"MZ-compilateur"):
    p = tmp_path / "clang++.exe"
    p.write_bytes(contenu)
    return str(p)


def test_inconnue_puis_connue_apres_un_succes(cache, tmp_path):
    exe = _exe(tmp_path)
    assert ToolchainManager._SondeConnue(exe, "--version") is False
    ToolchainManager._SondeNoter(exe, "--version")
    assert ToolchainManager._SondeConnue(exe, "--version") is True


def test_ecrite_puis_relue_par_un_autre_processus(cache, tmp_path):
    exe = _exe(tmp_path)
    ToolchainManager._SondeNoter(exe, "--version")
    ToolchainManager._SondesEcrire()
    assert json.loads(cache.read_text(encoding="utf-8"))
    ToolchainManager._sondes = None  # comme un nouveau lancement de jenga
    assert ToolchainManager._SondeConnue(exe, "--version") is True


def test_l_executable_change_invalide(cache, tmp_path):
    exe = _exe(tmp_path)
    ToolchainManager._SondeNoter(exe, "--version")
    with open(exe, "ab") as f:  # mise a jour : la taille change
        f.write(b"-nouvelle-version")
    assert ToolchainManager._SondeConnue(exe, "--version") is False


def test_le_path_change_invalide(cache, tmp_path, monkeypatch):
    exe = _exe(tmp_path)
    ToolchainManager._SondeNoter(exe, "--version")
    monkeypatch.setenv("PATH", "C:\\autre-compilateur;C:\\un;C:\\deux")
    assert ToolchainManager._SondeConnue(exe, "--version") is False


def test_expire_apres_24_heures(cache, tmp_path):
    exe = _exe(tmp_path)
    ToolchainManager._SondeNoter(exe, "--version")
    cle = ToolchainManager._SondeCle(exe, "--version")
    ToolchainManager._sondes[cle] = time.time() - 25 * 3600
    assert ToolchainManager._SondeConnue(exe, "--version") is False


def test_executable_disparu(cache, tmp_path):
    exe = _exe(tmp_path)
    ToolchainManager._SondeNoter(exe, "--version")
    os.remove(exe)
    assert ToolchainManager._SondeConnue(exe, "--version") is False


def test_coupe_par_la_variable(cache, tmp_path, monkeypatch):
    exe = _exe(tmp_path)
    ToolchainManager._SondeNoter(exe, "--version")
    monkeypatch.setenv("JENGA_SONDES_SANS_CACHE", "1")
    assert ToolchainManager._SondeConnue(exe, "--version") is False
