#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_info_json.py
=======================
AUTEUR : TEUGUIA TADJUIDJE Rodolf Séderis — Rihen

Banc de `jenga info --json` (2.8.15) : le workspace decrit pour un outil.

NKCode montre le graphe et l'architecture d'un workspace. Lire le texte des
.jenga ne suffit pas : ce sont des programmes (variables, conditions, fichiers
inclus). La description exacte vient donc de Jenga, qui les execute.

Ce que le banc exige :
  - un projet declare dans un fichier INCLUS apparait, avec le fichier qui le
    declare ;
  - une dependance ecrite par une VARIABLE et une autre sous une CONDITION
    apparaissent : c'est exactement ce que la lecture du texte manque ;
  - la sortie se retrouve derriere sa ligne-repere, meme si le .jenga ecrit
    lui-meme sur la sortie.

Usage :
  python -m pytest tests/test_info_json.py -v
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import Jenga.Core.Api as Api
from Jenga.Commands.Info import InfoCommand


WORKSPACE = '''from Jenga import *

print("un .jenga peut ecrire sur la sortie { meme une accolade")

_SOCLE = "Socle"

with workspace("Atelier"):
    configurations(["Debug", "Release"])
    startproject("Outil")

    with project("Socle"):
        staticlib()
        language("C++")
        cppdialect("C++20")
        files(["socle/**.cpp"])

    with project("Outil"):
        consoleapp()
        language("C++")
        files(["outil/**.cpp"])
        dependson([_SOCLE])          # par une variable
        if len(_SOCLE) == 5:
            dependson(["Greffon"])   # sous une condition

    with include("greffon/Greffon.jenga"):
        pass
'''

GREFFON = '''from Jenga import *

with project("Greffon"):
    sharedlib()
    language("C++")
    files(["src/**.cpp"])
    dependson(["Socle"])
'''


def _ecrire(tmp_path):
    (tmp_path / "greffon").mkdir()
    (tmp_path / "Atelier.jenga").write_text(WORKSPACE, encoding="utf-8")
    (tmp_path / "greffon" / "Greffon.jenga").write_text(GREFFON, encoding="utf-8")
    return tmp_path / "Atelier.jenga"


def _decrire(tmp_path, capsys):
    Api.resetstate()
    fichier = _ecrire(tmp_path)
    code = InfoCommand.Execute(["--json", "--jenga-file", str(fichier)])
    sortie = capsys.readouterr().out
    assert code == 0, sortie
    lignes = sortie.splitlines()
    assert InfoCommand.JSON_MARKER in lignes, "la ligne-repere manque : " + sortie[:200]
    apres = lignes[lignes.index(InfoCommand.JSON_MARKER) + 1:]
    return json.loads("\n".join(apres)), sortie, fichier


class TestInfoJson:
    def test_le_workspace_est_decrit(self, tmp_path, capsys):
        d, _, fichier = _decrire(tmp_path, capsys)
        w = d["workspace"]
        assert w["name"] == "Atelier"
        assert w["configurations"] == ["Debug", "Release"]
        assert w["startProject"] == "Outil"
        assert Path(w["file"]) == fichier
        assert d["jenga"]

    def test_le_projet_inclus_apparait_avec_son_fichier(self, tmp_path, capsys):
        d, _, fichier = _decrire(tmp_path, capsys)
        p = {x["name"]: x for x in d["projects"]}
        assert set(p) == {"Socle", "Outil", "Greffon"}
        assert p["Greffon"]["external"] is True
        assert Path(p["Greffon"]["file"]) == fichier.parent / "greffon" / "Greffon.jenga"
        assert p["Greffon"]["kind"] == "SharedLib"
        # declare dans le workspace : son fichier est celui du workspace
        assert p["Socle"]["external"] is False
        assert Path(p["Socle"]["file"]) == fichier
        assert p["Socle"]["kind"] == "StaticLib"
        assert p["Socle"]["cppdialect"] == "C++20"
        assert p["Socle"]["files"] == ["socle/**.cpp"]

    def test_les_dependances_calculees_apparaissent(self, tmp_path, capsys):
        """Celle ecrite par une variable ET celle sous une condition : ce que la
        lecture du texte ne voit pas, et la raison d'etre de la commande."""
        d, _, _ = _decrire(tmp_path, capsys)
        p = {x["name"]: x for x in d["projects"]}
        assert p["Outil"]["dependsOn"] == ["Socle", "Greffon"]
        assert p["Greffon"]["dependsOn"] == ["Socle"]
        assert p["Socle"]["dependsOn"] == []

    def test_la_sortie_du_jenga_ne_trompe_pas_le_lecteur(self, tmp_path, capsys):
        """Le .jenga ecrit une accolade AVANT la description. Qui chercherait « la
        premiere accolade » lirait cette ligne-la : la ligne-repere existe pour cela."""
        _, sortie, _ = _decrire(tmp_path, capsys)
        premiere = sortie.index("{")
        repere = sortie.index(InfoCommand.JSON_MARKER)
        assert premiere < repere, "le montage ne met plus d'accolade avant le repere : le temoin ne temoigne plus"

    def test_aucune_ligne_ne_depasse_ce_qu_un_lecteur_borne_accepte(self, tmp_path, capsys):
        """NKCode lit la sortie d'un processus ligne a ligne, dans 8 Ko : une
        description d'un seul tenant y serait coupee sans un mot. Une valeur par
        ligne, donc ; ici 200 fichiers sources tiennent chacun sur la leur."""
        Api.resetstate()
        fichier = _ecrire(tmp_path)
        texte = fichier.read_text(encoding="utf-8").replace(
            'files(["socle/**.cpp"])',
            'files(["socle/un_nom_de_fichier_assez_long_%03d.cpp" % i for i in range(200)])')
        fichier.write_text(texte, encoding="utf-8")
        assert InfoCommand.Execute(["--json", "--jenga-file", str(fichier)]) == 0
        lignes = capsys.readouterr().out.splitlines()
        apres = lignes[lignes.index(InfoCommand.JSON_MARKER) + 1:]
        d = json.loads("\n".join(apres))
        socle = [p for p in d["projects"] if p["name"] == "Socle"][0]
        assert len(socle["files"]) == 200
        assert sum(len(l) for l in apres) > 8192, "le montage ne depasse plus 8 Ko : le temoin ne temoigne plus"
        assert max(len(l) for l in apres) < 1024

    def test_sans_json_rien_ne_change(self, tmp_path, capsys):
        Api.resetstate()
        fichier = _ecrire(tmp_path)
        code = InfoCommand.Execute(["--no-daemon", "--jenga-file", str(fichier)])
        sortie = capsys.readouterr().out
        assert code == 0
        assert InfoCommand.JSON_MARKER not in sortie
        assert "Jenga Workspace: Atelier" in sortie
