#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_identite_windows.py
==============================
AUTEUR : TEUGUIA TADJUIDJE Rodolf Séderis — Rihen

Banc de la FICHE D'IDENTITE d'un executable Windows (2.8.16) :
  - la ressource VERSIONINFO porte ce que le .jenga dit (editeur, description,
    version, copyright), et n'ecrit pas un champ vide ;
  - une version « 1.2.3-beta.4 » donne le quadruplet 1,2,3,0 sans perdre son
    texte ;
  - `apppublisher` et `appcopyright` s'ecrivent dans un projet OU au niveau du
    workspace (valeur par defaut) ; `appdescription` hors d'un projet se REFUSE.

Mesure d'origine (2026-10-08, Smart App Control actif) : le journal d'integrite
du code montrait, pour chaque executable refuse, zero signature et une fiche
vide (« 0.0.0.0 », aucune societe, aucun produit).

Usage :
  python -m pytest tests/test_identite_windows.py -v
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pytest
import Jenga.Core.Api as Api
from Jenga.Core.Api import (
    workspace, project, consoleapp, apppublisher, appversion, appdescription, appcopyright,
)
from Jenga.Core.Builders.Windows import VersionQuadruple, WindowsVersionInfoRc


def _reset():
    Api.resetstate()


# ===========================================================================
# 1. La version : quatre nombres pour FILEVERSION, le texte entier a cote
# ===========================================================================

class TestVersionQuadruple:
    @pytest.mark.parametrize("texte, attendu", [
        ("1.2.3", (1, 2, 3, 0)),
        ("0.1.0-beta.11", (0, 1, 0, 0)),
        ("v2.8.16", (2, 8, 16, 0)),
        ("4", (4, 0, 0, 0)),
        ("1.2.3.4.5", (1, 2, 3, 4)),
        ("70000.1", (65535, 1, 0, 0)),   # FILEVERSION ne porte que 16 bits par nombre
        ("", (1, 0, 0, 0)),
        ("sans numero", (1, 0, 0, 0)),
    ])
    def test_numbers_are_read_from_the_head(self, texte, attendu):
        assert VersionQuadruple(texte) == attendu


# ===========================================================================
# 2. Le bloc VERSIONINFO
# ===========================================================================

class TestVersionInfoRc:
    def test_it_carries_what_the_jenga_file_says(self):
        rc = WindowsVersionInfoRc("Jeu", "Jeu.exe", publisher="Mon Studio", description="Le jeu du studio",
                                  version="1.2.0-beta.3", copyright="© 2026 Mon Studio")
        assert "1 VERSIONINFO" in rc
        assert "FILEVERSION 1,2,0,0" in rc and "PRODUCTVERSION 1,2,0,0" in rc
        assert 'VALUE "CompanyName", "Mon Studio"' in rc
        assert 'VALUE "FileDescription", "Le jeu du studio"' in rc
        assert 'VALUE "FileVersion", "1.2.0-beta.3"' in rc      # le texte entier, pas le quadruplet
        assert 'VALUE "LegalCopyright", "© 2026 Mon Studio"' in rc
        assert 'VALUE "OriginalFilename", "Jeu.exe"' in rc
        assert 'VALUE "ProductName", "Jeu"' in rc
        assert 'VALUE "Translation", 0x409, 1200' in rc

    def test_an_empty_field_is_not_written(self):
        rc = WindowsVersionInfoRc("Outil", "Outil.exe")
        assert "CompanyName" not in rc and "LegalCopyright" not in rc
        # sans rien dire : le nom du projet, et 1.0.0
        assert 'VALUE "FileDescription", "Outil"' in rc
        assert 'VALUE "FileVersion", "1.0.0"' in rc and "FILEVERSION 1,0,0,0" in rc

    def test_quotes_backslashes_and_newlines_cannot_break_the_block(self):
        rc = WindowsVersionInfoRc("P", "P.exe", publisher='Studio "A"\nB', description="C:\\dossier")
        assert 'VALUE "CompanyName", "Studio ""A"" B"' in rc
        assert 'VALUE "FileDescription", "C:\\\\dossier"' in rc
        # une valeur = une ligne : aucune ne s'est coupee
        assert all(l.count('"') % 2 == 0 for l in rc.splitlines())


# ===========================================================================
# 3. Les mots du DSL et leur portee
# ===========================================================================

class TestIdentityWords:
    def test_workspace_gives_the_default_and_a_project_says_its_own(self):
        _reset()
        with workspace("W"):
            apppublisher("Mon Studio")
            appcopyright("© Studio")
            with project("A"):
                consoleapp()
                appversion("2.0.1")
                appdescription("L'application A")
            with project("B"):
                consoleapp()
                apppublisher("Un Autre")
        wks = Api.getcurrentworkspace()
        assert wks.appPublisher == "Mon Studio" and wks.appCopyright == "© Studio"
        a, b = wks.projects["A"], wks.projects["B"]
        assert a.appPublisher == "" and a.appDescription == "L'application A" and a.appVersion == "2.0.1"
        assert b.appPublisher == "Un Autre"       # le sien, pas celui du workspace
        assert wks.appPublisher == "Mon Studio"    # et le workspace n'a pas bouge

    def test_appdescription_outside_a_project_is_refused(self):
        _reset()
        with workspace("W"):
            with pytest.raises(RuntimeError) as e:
                appdescription("nulle part")
        assert "appdescription" in str(e.value)

    def test_apppublisher_outside_any_workspace_is_refused(self):
        _reset()
        with pytest.raises(RuntimeError):
            apppublisher("personne")
