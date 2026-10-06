"""Tout ce que Jenga cree pour un workspace vit sous <racine>/.jenga, jamais
relativement au dossier courant ; .jenga-typings est migre vers .jenga/typings."""
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


def _jenga(args, cwd):
    env = dict(os.environ, PYTHONPATH=str(REPO), JENGA_NO_ANIM="1")
    return subprocess.run([sys.executable, "-m", "Jenga", *args], cwd=str(cwd),
                          env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180)


def _tree(root: Path):
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*"))


def test_workspace_ne_cree_rien_hors_du_workspace(tmp_path):
    r = _jenga(["workspace", "MonJeu"], tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert [p.name for p in tmp_path.iterdir()] == ["MonJeu"]
    for p in (tmp_path / "MonJeu").rglob("*"):
        assert ".jenga-typings" not in p.parts
    assert not (tmp_path / "MonJeu" / ".jenga-typings").exists()


def test_commande_sans_workspace_ne_cree_aucun_dossier(tmp_path):
    _jenga(["--version"], tmp_path)
    _jenga(["--help"], tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_sous_dossier_ecrit_sous_la_racine(tmp_path):
    root = tmp_path / "W"
    sub = root / "src" / "deep"
    sub.mkdir(parents=True)
    code = (
        "import sys\n"
        "from pathlib import Path\n"
        "from Jenga.Core import Api\n"
        "from Jenga.Core.Cache import Cache\n"
        "from Jenga.Core.Daemon import Daemon\n"
        "class W: location = sys.argv[1]\n"
        "Api._currentWorkspace = W()\n"
        "Api.ExternalToolsManager().SaveCache()\n"
        "c = Cache(Path(sys.argv[1]))\n"
        "print('DB', c.dbPath)\n"
        "print('DAEMON', Path(sys.argv[1]) / Daemon._DAEMON_DIR)\n"
    )
    env = dict(os.environ, PYTHONPATH=str(REPO))
    r = subprocess.run([sys.executable, "-c", code, str(root)], cwd=str(sub),
                       env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
    assert r.returncode == 0, r.stderr
    assert (root / ".jenga" / "tools_cache.json").is_file()
    assert not (sub / ".jenga").exists()
    assert not (sub.parent / ".jenga").exists()
    out = dict(l.split(" ", 1) for l in r.stdout.splitlines() if l[:2] in ("DB", "DA"))
    assert Path(out["DB"]).is_relative_to(root / ".jenga" / "cache")
    assert Path(out["DAEMON"]).is_relative_to(root / ".jenga" / "daemon")


def test_commande_depuis_sous_dossier_ne_pollue_pas_le_sous_dossier(tmp_path):
    assert _jenga(["workspace", "W"], tmp_path).returncode == 0
    sub = tmp_path / "W" / "sub"
    sub.mkdir()
    _jenga(["info"], sub)
    assert list(sub.iterdir()) == []
    assert not (tmp_path / ".jenga").exists()


def test_migration_jenga_typings(tmp_path):
    from Jenga.Core.IDEConfigurator import MigrateLegacyTypings
    old = tmp_path / ".jenga-typings"
    old.mkdir()
    (old / "jengaconfig.pyi").write_text("a: int\n", encoding="utf-8")
    (old / "perso.txt").write_text("a moi", encoding="utf-8")
    new = tmp_path / ".jenga" / "typings"
    new.mkdir(parents=True)
    (new / "perso.txt").write_text("deja la", encoding="utf-8")
    assert MigrateLegacyTypings(tmp_path) is True
    assert (new / "jengaconfig.pyi").read_text(encoding="utf-8") == "a: int\n"
    # rien n'est ecrase ni perdu : le conflit reste dans l'ancien dossier
    assert (new / "perso.txt").read_text(encoding="utf-8") == "deja la"
    assert (old / "perso.txt").read_text(encoding="utf-8") == "a moi"
    # sans conflit, l'ancien dossier disparait une fois vide
    (old / "perso.txt").unlink()
    MigrateLegacyTypings(tmp_path)
    assert not old.exists()
    assert MigrateLegacyTypings(tmp_path) is False


def test_pyright_pointe_vers_jenga_typings():
    from Jenga.Core import IDEConfigurator as I
    assert I._STUB_DIR_NAME == ".jenga/typings"
