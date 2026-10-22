# AUTEUR : TEUGUIA TADJUIDJE Rodolf Séderis — Rihen
"""
(2.10.0) `jenga clean --taille` : la place prise par Build/, par configuration et plateforme, SANS RIEN
SUPPRIMER. Rodolf (22/10/2026) : « Jenga nécessite énormément d'espace disque : comment y remédier sans
perdre l'efficacité ? ». D'abord savoir ou part la place.

Un Build/ fabrique a la main (aucun compilateur) : on lit ce que la commande dit, et on verifie que tout est
encore la. Un fichier lie deux fois (lien physique) ne compte qu'une fois. Contre-epreuve a l'ecriture : la
v2.9.0 refuse `--taille` (argparse, code 2) ; sans l'option, elle aurait nettoye.
"""
import os
import subprocess
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pytest

_WORKSPACE = textwrap.dedent("""\
    from Jenga import *
    with workspace("Taille"):
        configurations(["Debug", "Release"])
        with project("P"):
            consoleapp()
            language("C++")
            files(["main.cpp"])
""")


def _ecrire(f: Path, n: int):
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_bytes(b"x" * n)


def _jenga(root: Path, *args):
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run([sys.executable, "-m", "Jenga", "clean", *args, "--no-daemon", "--jenga-file", str(root / "Taille.jenga")],
                          cwd=str(root), env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300)


@pytest.fixture()
def wks(tmp_path):
    (tmp_path / "Taille.jenga").write_text(_WORKSPACE, encoding="utf-8")
    (tmp_path / "main.cpp").write_text("int main(){return 0;}\n", encoding="utf-8")
    b = tmp_path / "Build"
    _ecrire(b / "Obj" / "Debug-Linux" / "P" / "main.o", 3 * 1024 * 1024)
    _ecrire(b / "Bin" / "Debug-Linux" / "P" / "P", 5 * 1024 * 1024)
    _ecrire(b / "Obj" / "Release-Linux" / "P" / "main.o", 1024 * 1024)
    _ecrire(b / "Demo" / "capture" / "a.bin", 2 * 1024 * 1024)
    return tmp_path


def _tous(root: Path):
    return sorted(str(p.relative_to(root)) for p in (root / "Build").rglob("*") if p.is_file())


def test_releve_par_configuration_sans_rien_supprimer(wks):
    avant = _tous(wks)
    r = _jenga(wks, "--taille")
    sortie = r.stdout + r.stderr
    assert r.returncode == 0, sortie
    assert _tous(wks) == avant, "--taille a supprime quelque chose"
    lignes = {l.split()[0]: l for l in sortie.splitlines() if l.strip().startswith(("Debug-", "Release-"))}
    assert "8,0 Mo" in lignes["Debug-Linux"], sortie        # 3 Mo d'objets + 5 Mo de binaires
    assert "1,0 Mo" in lignes["Release-Linux"], sortie
    assert "Demo 2,0 Mo" in sortie and "11,0 Mo" in sortie, sortie   # le reste, et le total


def test_filtre_par_configuration(wks):
    r = _jenga(wks, "--taille", "--config", "Release")
    sortie = r.stdout + r.stderr
    assert "Release-Linux" in sortie and "Debug-Linux" not in sortie, sortie


def test_lien_physique_compte_une_fois(wks):
    src = wks / "Build" / "Bin" / "Debug-Linux" / "P" / "P"
    dst = wks / "Build" / "Bin" / "Release-Linux" / "P" / "P"
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(src, dst)
    except OSError as e:
        pytest.skip("pas de lien physique ici : %s" % e)
    sortie = _jenga(wks, "--taille").stdout
    assert "Place prise par" in sortie and "11,0 Mo" in sortie.splitlines()[[i for i, l in enumerate(sortie.splitlines())
                                                                          if "Place prise par" in l][0]], sortie


def test_detail_nomme_les_projets(wks):
    sortie = _jenga(wks, "--taille", "--detail").stdout
    assert "Bin/P" in sortie and "Obj/P" in sortie, sortie
