#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# AUTEUR : TEUGUIA TADJUIDJE Rodolf Séderis — Rihen
"""
FastWhich : un `shutil.which` qui ne sonde pas le disque une fois par (dossier x extension x commande).

Mesure du 06/11/2026 (`jenga build` d'un projet a jour, 3,0 s) : 1,6 s partaient dans la detection des
toolchains, dont 125 appels a `shutil.which` = 36 404 `os.path.exists` (48 dossiers du PATH x 12 extensions
de PATHEXT x chaque outil cherche). Ici : UN `os.scandir` par dossier du PATH, gardé 1 s, puis chaque recherche est une consultation de dictionnaire.

Compatibilité : mêmes règles que `shutil.which` sous Windows (le nom tel quel s'il porte déjà une extension
de PATHEXT, puis le nom + chaque extension), SAUF le dossier courant, jamais consulté ici ; ailleurs, le nom exact et exécutable.
Tout cas qui sort de ce cadre (chemin avec séparateur, `path=` explicite) est rendu à `shutil.which`.
"""
import os
import shutil
import sys
import time
from typing import Dict, Optional, Tuple

_INDEX: Dict[str, Tuple[float, Dict[str, str]]] = {}  # dossier -> (instant, {nom en minuscules (Windows) ou exact : nom reel})
_DUREE_S = 1.0  # un outil installe en cours de route (SDK telecharge par Jenga) est vu au plus 1 s plus tard
_WINDOWS = sys.platform == "win32"


def _contenu(dossier: str) -> Dict[str, str]:
    maintenant = time.monotonic()
    deja = _INDEX.get(dossier)
    if deja is not None and maintenant - deja[0] < _DUREE_S:
        return deja[1]
    noms: Dict[str, str] = {}
    try:
        with os.scandir(dossier) as it:
            for e in it:
                noms[e.name.lower() if _WINDOWS else e.name] = e.name
    except OSError:
        pass
    _INDEX[dossier] = (maintenant, noms)
    return noms


def Which(cmd: str, path: Optional[str] = None) -> Optional[str]:
    """Comme `shutil.which(cmd)`, sans sondage répété du disque."""
    if path is not None or not cmd or os.path.dirname(cmd):
        return shutil.which(cmd, path=path)
    valeur_path = os.environ.get("PATH", "")
    trouve: Optional[str] = None
    if _WINDOWS:
        pathext = [e for e in os.environ.get("PATHEXT", ".COM;.EXE;.BAT;.CMD").split(os.pathsep) if e]
        bas = cmd.lower()
        candidats = [bas] if any(bas.endswith(e.lower()) for e in pathext) else []
        candidats += [bas + e.lower() for e in pathext]
        if not any(bas.endswith(e.lower()) for e in pathext):
            candidats.append(bas)
        dossiers = [d for d in valeur_path.split(os.pathsep) if d]
    else:
        candidats = [cmd]
        dossiers = [d for d in valeur_path.split(os.pathsep) if d]
    for d in dossiers:
        noms = _contenu(d)
        for c in candidats:
            reel = noms.get(c)
            if reel is None:
                continue
            complet = os.path.join(d, reel)
            if os.path.isfile(complet) and (_WINDOWS or os.access(complet, os.X_OK)):
                trouve = complet
                break
        if trouve:
            break
    return trouve
