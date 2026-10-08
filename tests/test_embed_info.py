#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_embed_info.py
========================
AUTEUR : TEUGUIA TADJUIDJE Rodolf Séderis — Rihen

L'API embarquee (Core/Embed.py, `Info()`) doit dire LA MEME CHOSE que la
commande `jenga info` (2.8.18).

Mesure du 2026-10-08 dans NKCode : `Info()` rendait le genre d'un projet par
le NOM de l'enumeration (« CONSOLE_APP ») ; la commande imprime sa VALEUR
(« ConsoleApp »). L'hote cherchait « Console » : une application passait pour
une bibliotheque et « Demarrer » ne lancait rien.

Le temoin ne recopie pas la liste des genres : il lit ce que la commande
imprime pour le meme workspace, et compare.

Usage :
  python -m pytest tests/test_embed_info.py -v
"""
import io
import re
import sys
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from Jenga.Commands.Info import InfoCommand
from Jenga.Core import Embed

WKS = (
    'from Jenga import *\n\n'
    'with workspace("W"):\n'
    '    configurations(["Debug", "Release"])\n'
    '    targetoses([TargetOS.WINDOWS, TargetOS.LINUX])\n'
    '    targetarchs([TargetArch.X86_64])\n'
    '    startproject("App")\n\n'
    '    with project("Lib"):\n        staticlib()\n        files(["src/**.cpp"])\n\n'
    '    with project("Greffon"):\n        sharedlib()\n        files(["src/**.cpp"])\n\n'
    '    with project("App"):\n        consoleapp()\n        files(["src/**.cpp"])\n\n'
    '    with project("Vue"):\n        windowedapp()\n        files(["src/**.cpp"])\n'
)


def _Workspace(tmp_path: Path) -> Path:
    (tmp_path / "src").mkdir()
    entree = tmp_path / "W.jenga"
    entree.write_text(WKS, encoding="utf-8")
    return entree


def _CeQueDitLaCommande(entree: Path) -> str:
    tampon = io.StringIO()
    with redirect_stdout(tampon):
        rc = InfoCommand.Execute(["--jenga-file", str(entree)])
    assert rc == 0, tampon.getvalue()
    # la commande colore ses titres : on lit le texte, sans les codes de couleur
    return re.sub(r'\x1b\[[0-9;]*m', '', tampon.getvalue())


def _GenresDeLaCommande(texte: str) -> dict:
    # la table « Projects » : « Name  Kind  Language  Test  External »
    genres, dans = {}, False
    for ligne in texte.splitlines():
        mots = ligne.split()
        if mots[:2] == ["Name", "Kind"]:
            dans = True
            continue
        if dans:
            if not mots:
                break
            if set(ligne.strip()) <= set("-=+| "):
                continue
            genres[mots[0]] = mots[1]
    return genres


def _Ligne(texte: str, titre: str) -> list:
    for ligne in texte.splitlines():
        if ligne.startswith(titre):
            return [x.strip() for x in ligne[len(titre):].split(",") if x.strip()]
    return []


def test_e1_le_genre_est_celui_que_la_commande_imprime(tmp_path):
    entree = _Workspace(tmp_path)
    attendu = _GenresDeLaCommande(_CeQueDitLaCommande(entree))
    Embed.InvalidateWorkspaceCache()
    info = Embed.Info(str(entree))
    assert info.errorMessage == ""
    rendu = {p.name: p.kind for p in info.projects}
    assert attendu == {"Lib": "StaticLib", "Greffon": "SharedLib", "App": "ConsoleApp", "Vue": "WindowedApp"}
    assert rendu == attendu


def test_e2_ce_que_le_workspace_declare(tmp_path):
    entree = _Workspace(tmp_path)
    texte = _CeQueDitLaCommande(entree)
    Embed.InvalidateWorkspaceCache()
    info = Embed.Info(str(entree))
    assert info.startProject == "App"
    assert info.targetOses == _Ligne(texte, "Target OSes:") == ["Windows", "Linux"]
    assert info.targetArchs == _Ligne(texte, "Target Architectures:") == ["x86_64"]
    assert info.workspaceToolchains == _Ligne(texte, "Workspace toolchains:")


def test_e3_chaque_chaine_dit_son_compilateur_comme_la_commande(tmp_path):
    entree = _Workspace(tmp_path)
    texte = _CeQueDitLaCommande(entree)
    # le bloc « Toolchain compilers: » : « nom | compilateur C++ | bibliotheque C++ »
    attendu, dans = {}, False
    for ligne in texte.splitlines():
        if ligne.startswith("Toolchain compilers:"):
            dans = True
            continue
        if dans:
            if not ligne.strip():
                break
            nom, cxx, stdlib = [x.strip() for x in ligne.split("|")]
            attendu[nom] = (cxx, stdlib)
    Embed.InvalidateWorkspaceCache()
    info = Embed.Info(str(entree))
    rendu = {t.name: (t.cxx, t.stdlib) for t in info.toolchains if t.cxx}
    assert rendu == attendu
