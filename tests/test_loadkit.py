#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_loadkit.py
=====================
AUTEUR : TEUGUIA TADJUIDJE Rodolf Séderis — Rihen

Banc de 2.8.20 : un kit se charge OU QU'IL SOIT sur la machine.

Rodolf, 14/10/2026 : « jenga recherche le kit forcement a la racine du workspace,
pourtant on peut mettre une bibliotheque n'importe ou sur le systeme ». Le kit ne
tenait pas a sa place (KIT_ROOT vient de son propre fichier) ; c'est la facon de le
charger qui l'attachait a la racine : useconfig() part de la racine pour un chemin
relatif, rien ne cherchait un kit par son nom, et `jenga kit` conseillait un chemin
relatif a la racine.

Ce banc tient :
  (l1) un kit HORS du workspace, par son chemin absolu : ses en-tetes et sa fonction
       arrivent dans le projet ;
  (l2) par son NOM, trouve dans JENGA_KITS ;
  (l3) par son nom, dans un dossier de kitpaths(), relatif au .jenga qui l'appelle ;
  (l4) par son nom, dans le dossier de kits de l'utilisateur (LOCALAPPDATA) ;
  (l5) l'usage d'avant : un kit a la racine du workspace se trouve toujours ;
  (l6) un chemin relatif dans un .jenga de SOUS-DOSSIER part de ce fichier, pas de la racine ;
  (l7) introuvable : l'erreur dit chaque endroit fouille ;
  (l8) un chemin Windows dont les « \\ » sont devenus une tabulation : on le dit ;
  (l9) un kit nomme « Kit » (sa fonction s'appelle usekit) n'ecrase pas loadkit.

Usage :
  python -m pytest tests/test_loadkit.py -v
"""
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from Jenga.Core import Api
from Jenga.Core.Loader import Loader

KIT = '''from pathlib import Path as _Path
KIT_ROOT = str(_Path(__file__).resolve().parent).replace("\\\\", "/")
KIT_NAME = "{nom}"

def use{fonction}():
    includedirs([KIT_ROOT + "/include"])
'''

WS = '''from Jenga import *

with workspace("W"):
    configurations(["Debug"])
{avant}
    with project("App"):
        consoleapp()
        language("C++")
        files(["src/**.cpp"])
        use{fonction}()
'''


def _kit(dossier: Path, nom: str = "Truc") -> Path:
    """Un kit minimal dans <dossier>/<nom>/ : son .jenga et un include/."""
    k = dossier / nom
    (k / "include").mkdir(parents=True, exist_ok=True)
    (k / f"{nom}.jenga").write_text(KIT.format(nom=nom, fonction=nom.lower()), encoding="utf-8")
    return k


def _ws(dossier: Path, avant: str, fonction: str = "truc") -> Path:
    dossier.mkdir(parents=True, exist_ok=True)
    (dossier / "src").mkdir(exist_ok=True)
    (dossier / "src" / "main.cpp").write_text("int main() { return 0; }\n", encoding="utf-8")
    f = dossier / "W.jenga"
    f.write_text(WS.format(avant=avant, fonction=fonction), encoding="utf-8")
    return f


def _charger(f: Path, monkeypatch, env=None):
    for k in ("JENGA_KITS",):
        monkeypatch.delenv(k, raising=False)
    for k, v in (env or {}).items():
        monkeypatch.setenv(k, v)
    Api.resetstate()
    return Loader().LoadWorkspace(str(f))


def _inclut(ws, kit_dir: Path) -> bool:
    attendu = (kit_dir / "include").resolve().as_posix().lower()
    return any(Path(d).resolve().as_posix().lower() == attendu for d in ws.projects["App"].includeDirs)


def test_l1_kit_hors_du_workspace_par_chemin_absolu(tmp_path, monkeypatch):
    kit = _kit(tmp_path / "ailleurs" / "kits")
    ws = _charger(_ws(tmp_path / "projet", f'    loadkit("{kit.as_posix()}")\n'), monkeypatch,
                  {"LOCALAPPDATA": str(tmp_path / "vide")})
    assert ws is not None and _inclut(ws, kit)


def test_l2_par_son_nom_dans_JENGA_KITS(tmp_path, monkeypatch):
    kit = _kit(tmp_path / "Programmes" / "Kits")
    ws = _charger(_ws(tmp_path / "projet", '    loadkit("Truc")\n'), monkeypatch,
                  {"JENGA_KITS": str(tmp_path / "nulle-part") + os.pathsep + str(tmp_path / "Programmes" / "Kits"),
                   "LOCALAPPDATA": str(tmp_path / "vide")})
    assert ws is not None and _inclut(ws, kit)


def test_l3_par_son_nom_dans_kitpaths_relatif_au_jenga(tmp_path, monkeypatch):
    kit = _kit(tmp_path / "partage" / "kits")
    ws = _charger(_ws(tmp_path / "projet", '    kitpaths("../partage/kits")\n    loadkit("Truc")\n'), monkeypatch,
                  {"LOCALAPPDATA": str(tmp_path / "vide")})
    assert ws is not None and _inclut(ws, kit)


def test_l4_par_son_nom_dans_le_dossier_de_l_utilisateur(tmp_path, monkeypatch):
    kit = _kit(tmp_path / "local" / "Jenga" / "kits")
    ws = _charger(_ws(tmp_path / "projet", '    loadkit("Truc")\n'), monkeypatch,
                  {"LOCALAPPDATA": str(tmp_path / "local")})
    assert ws is not None and _inclut(ws, kit)


def test_l5_l_usage_d_avant_un_kit_a_la_racine(tmp_path, monkeypatch):
    projet = tmp_path / "projet"
    kit = _kit(projet)
    ws = _charger(_ws(projet, '    loadkit("Truc")\n'), monkeypatch, {"LOCALAPPDATA": str(tmp_path / "vide")})
    assert ws is not None and _inclut(ws, kit)


def test_l6_chemin_relatif_dans_un_jenga_de_sous_dossier(tmp_path, monkeypatch):
    projet = tmp_path / "projet"
    kit = _kit(projet / "moteur" / "kits")
    f = _ws(projet, '    useconfig("moteur/config.jenga")\n')
    (projet / "moteur" / "config.jenga").write_text('loadkit("kits/Truc")\n', encoding="utf-8")
    # La meme chaine, lue depuis la racine, ne mene a rien : seul le dossier du fichier qui appelle la resout.
    assert not (projet / "kits" / "Truc").exists()
    ws = _charger(f, monkeypatch, {"LOCALAPPDATA": str(tmp_path / "vide")})
    assert ws is not None and _inclut(ws, kit)


def test_l7_introuvable_dit_chaque_endroit_fouille(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("JENGA_KITS", str(tmp_path / "kits-env"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    Api.resetstate()
    with pytest.raises(FileNotFoundError) as e:
        Api.loadkit("Absent")
    m = str(e.value)
    assert "introuvable" in m
    assert str(tmp_path / "kits-env" / "Absent" / "Absent.jenga") in m
    assert str(tmp_path / "local" / "Jenga" / "kits" / "Absent" / "Absent.jenga") in m
    assert "JENGA_KITS" in m and "kitpaths" in m


def test_l8_un_chemin_windows_casse_par_les_antislashs(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Api.resetstate()
    with pytest.raises(ValueError) as e:
        Api.loadkit("C:\\kits\tests")  # le « \t » est devenu une tabulation
    assert "tabulation" in str(e.value) and "/" in str(e.value)


def test_l9_un_kit_nomme_Kit_n_ecrase_pas_loadkit(tmp_path, monkeypatch):
    kit = _kit(tmp_path / "kits", nom="Kit")  # sa fonction s'appelle « usekit »
    autre = _kit(tmp_path / "kits", nom="Truc")
    avant = (f'    loadkit("{kit.as_posix()}")\n'
             f'    loadkit("{autre.as_posix()}")\n')
    f = _ws(tmp_path / "projet", avant, fonction="truc")
    ws = _charger(f, monkeypatch, {"LOCALAPPDATA": str(tmp_path / "vide")})
    assert ws is not None and _inclut(ws, autre)
