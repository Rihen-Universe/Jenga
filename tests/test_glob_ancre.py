# Motifs de fichiers ancres a la location du projet (2.8.10).
# « src/**.cpp » : « src » est un enfant DIRECT de la location ; les src/ des
# sous-dossiers (une application rangee sous la bibliotheque) n'y entrent pas.
# « **.cpp » et « *.cpp » restent cherches a toute profondeur.
from pathlib import Path

import pytest

from Jenga.Utils.FileSystem import FileSystem


@pytest.fixture
def arbre(tmp_path):
    projet = tmp_path / "projet"
    for chemin in ("src/a.cpp", "src/sous/b.cpp", "src/c.h",
                   "Applications/Demo/src/main.cpp", "outils/d.cpp",
                   ".cache/src/cache.cpp"):
        f = projet / chemin
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("// essai\n", encoding="utf-8")
    voisin = tmp_path / "voisin" / "src" / "v.cpp"
    voisin.parent.mkdir(parents=True)
    voisin.write_text("// voisin\n", encoding="utf-8")
    return projet


def _rel(projet, liste):
    return sorted(Path(p).as_posix() for p in liste)


def test_dossier_nomme_est_un_enfant_direct(arbre):
    trouves = FileSystem.ListFiles(arbre, "src/**.cpp", recursive=True)
    assert _rel(arbre, trouves) == ["src/a.cpp", "src/sous/b.cpp"]


def test_contre_epreuve_le_src_d_une_application_n_entre_pas(arbre):
    # c'est exactement le cas qui cassait : avec rglob, Applications/Demo/src/main.cpp entrait
    trouves = _rel(arbre, FileSystem.ListFiles(arbre, "src/**.cpp", recursive=True))
    assert "Applications/Demo/src/main.cpp" not in trouves


def test_sans_dossier_toute_profondeur(arbre):
    attendus = ["Applications/Demo/src/main.cpp", "outils/d.cpp", "src/a.cpp", "src/sous/b.cpp"]
    assert _rel(arbre, FileSystem.ListFiles(arbre, "**.cpp", recursive=True)) == attendus
    assert _rel(arbre, FileSystem.ListFiles(arbre, "*.cpp", recursive=True)) == attendus


def test_dossiers_caches_ignores(arbre):
    tous = _rel(arbre, FileSystem.ListFiles(arbre, "**.cpp", recursive=True))
    assert not any(p.startswith(".cache/") for p in tous)


def test_motif_hors_de_la_location(arbre):
    trouves = FileSystem.ListFiles(arbre, "../voisin/src/**.cpp", recursive=True, fullPath=True)
    assert [Path(p).name for p in trouves] == ["v.cpp"]


def test_exclusion_ancree(arbre):
    assert _rel(arbre, FileSystem.ListFiles(arbre, "Applications/**.cpp", recursive=True)) == \
        ["Applications/Demo/src/main.cpp"]
