#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_cache_include.py
===========================
AUTEUR : TEUGUIA TADJUIDJE Rodolf Séderis — Rihen

Banc du cache de workspace de l'API embarquee (Core/Embed.py) face aux
fichiers INCLUS (2.8.16).

`with include("P/P.jenga")` lit son fichier lui-meme, sans passer par le
Loader : le registre GetLoadedFiles ne contenait que le fichier d'entree, et
le cache ne voyait pas un fichier inclus changer. Mesure du 2026-10-08 dans
NKCode : un location("app") corrige en location(".") donnait toujours
« Not a directory: ...\\app » jusqu'au redemarrage.

Usage :
  python -m pytest tests/test_cache_include.py -v
"""
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from Jenga.Core import Embed
from Jenga.Core.Loader import GetLoadedFiles

WKS = 'from Jenga import *\n\nwith workspace("W"):\n    configurations(["Debug"])\n\n    with include("P/P.jenga"):\n        pass\n'
PRJ = 'from Jenga import *\n\nwith project("P"):\n    consoleapp()\n    location("{loc}")\n    files(["src/**.cpp"])\n'


def _Ecrire(f: Path, texte: str) -> None:
    f.write_text(texte, encoding="utf-8")
    # le cache compare (mtime_ns, taille) : on garantit un mtime different
    t = time.time() + 2
    os.utime(f, (t, t))


def _Emplacement(entry: Path) -> str:
    ws = Embed._LoadWorkspaceCached(entry)
    return str(ws.projects["P"].location).replace("\\", "/")


def test_included_files_are_registered(tmp_path):
    (tmp_path / "P").mkdir()
    entry = tmp_path / "W.jenga"
    entry.write_text(WKS, encoding="utf-8")
    (tmp_path / "P" / "P.jenga").write_text(PRJ.format(loc="."), encoding="utf-8")
    Embed.InvalidateWorkspaceCache()
    Embed._LoadWorkspaceCached(entry)
    noms = sorted(Path(p).name for p in GetLoadedFiles())
    assert noms == ["P.jenga", "W.jenga"]


def test_a_change_in_an_included_file_is_seen_by_the_cache(tmp_path):
    (tmp_path / "P").mkdir()
    entry = tmp_path / "W.jenga"
    inclus = tmp_path / "P" / "P.jenga"
    entry.write_text(WKS, encoding="utf-8")
    inclus.write_text(PRJ.format(loc="app"), encoding="utf-8")
    Embed.InvalidateWorkspaceCache()
    assert _Emplacement(entry).endswith("P/app")
    _Ecrire(inclus, PRJ.format(loc="."))          # le fichier d'ENTREE ne change pas
    assert _Emplacement(entry).endswith("P")      # avant 2.8.16 : encore « P/app »


def test_an_unchanged_workspace_is_served_from_the_cache(tmp_path):
    (tmp_path / "P").mkdir()
    entry = tmp_path / "W.jenga"
    entry.write_text(WKS, encoding="utf-8")
    (tmp_path / "P" / "P.jenga").write_text(PRJ.format(loc="."), encoding="utf-8")
    Embed.InvalidateWorkspaceCache()
    a = Embed._LoadWorkspaceCached(entry)
    b = Embed._LoadWorkspaceCached(entry)
    assert a is b                                  # le cache sert toujours : rien n'a change
