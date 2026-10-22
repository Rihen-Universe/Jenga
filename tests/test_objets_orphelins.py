# AUTEUR : TEUGUIA TADJUIDJE Rodolf Séderis — Rihen
"""
(2.10.0) Le menage des OBJETS ORPHELINS apres une construction reussie.

Jenga 2.9.0 laissait pour toujours l'objet d'une source retiree ou renommee (et ses .d, .jenga_sig) dans le
dossier des objets ; pire, la cible passait pour a jour (plus recente que les objets restants) et une
archive statique gardait le membre retire (`ar rcs` ne retire rien). Demande de Rodolf (22/10/2026) :
« Jenga necessite enormement d'espace disque : comment y remedier sans perdre l'efficacite ? ».

Deux niveaux :
  - TestRegle : la regle seule (quels fichiers sont orphelins, lesquels ne le sont JAMAIS), sans compilateur ;
  - TestBoutEnBout : une vraie construction (bibliotheque statique + programme), une source renommee puis
    une source retiree ; saute s'il n'y a aucun compilateur sur la machine.
Contre-epreuve a l'ecriture : sur la v2.9.0, l'objet renomme reste, l'archive garde ses membres retires.
"""
import os
import subprocess
import sys
import tempfile
import textwrap
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pytest
import Jenga.Core.Api as Api
from Jenga.Core.Api import CompilerFamily, Project, ProjectKind, TargetOS, TargetArch, Toolchain, Workspace


def _builder(tmp, obj_dir_brut=""):
    from Jenga.Core.Builders.Linux import LinuxBuilder
    Api._currentWorkspace = Api._currentProject = Api._currentToolchain = Api._currentFilter = None
    wks = Workspace(name="W", location=str(tmp))
    tc = Toolchain(name="tc", compilerFamily=CompilerFamily.GCC, ccPath="gcc", cxxPath="g++", arPath="ar",
                   targetOs=TargetOS.LINUX, targetArch=TargetArch.X86_64)
    wks.toolchains["tc"] = tc
    wks.defaultToolchain = "tc"
    b = LinuxBuilder.__new__(LinuxBuilder)
    b.workspace, b.config, b.platform = wks, "Debug", "Linux"
    b.targetOs, b.targetArch, b.targetEnv = TargetOS.LINUX, TargetArch.X86_64, None
    b.verbose, b.action, b.options, b.toolchain = False, "build", [], tc
    b.jobs, b._expander, b._lastResult = 1, None, None
    p = Project(name="P")
    p.kind = ProjectKind.STATIC_LIB
    p.objDir = obj_dir_brut
    wks.projects["P"] = p
    return b, p, wks


def _poser(d: Path, nom: str, sig=True, dep=True):
    (d / nom).write_bytes(b"objet")
    if sig:
        (d / (nom + ".jenga_sig")).write_text("0" * 64 + "\n", encoding="utf-8")
    if dep:
        (d / (nom + ".d")).write_text("x.o: x.cpp\n", encoding="utf-8")


class TestRegle:
    def test_seul_l_objet_de_jenga_hors_liste_est_orphelin(self, tmp_path):
        b, p, _ = _builder(tmp_path)
        d = b.GetObjectDir(p)
        d.mkdir(parents=True)
        _poser(d, "src_a.o")
        _poser(d, "src_b.o")                      # orphelin : compile par Jenga, hors liste
        _poser(d, "a_moi.o", sig=False)           # pose par l'utilisateur : jamais touche
        _poser(d, "__jenga_pch.o")                # interne a Jenga : jamais touche
        (d / "P.pch").write_bytes(b"pch")         # autre extension : jamais touche
        orphelins = b._ObjetsOrphelins(p, d, [str(d / "src_a.o")])
        assert [o.name for o in orphelins] == ["src_b.o"]
        assert b._RetirerObjetsOrphelins(p, orphelins) == 1
        restes = sorted(x.name for x in d.iterdir())
        assert restes == sorted(["src_a.o", "src_a.o.jenga_sig", "src_a.o.d", "a_moi.o", "a_moi.o.d", "__jenga_pch.o",
                                 "__jenga_pch.o.jenga_sig", "__jenga_pch.o.d", "P.pch"]), restes

    def test_objdir_sans_nom_de_projet_rien_n_est_retire(self, tmp_path):
        """Un objdir() propre au projet qui ne nomme pas le projet peut etre partage : au doute, rien."""
        b, p, _ = _builder(tmp_path, obj_dir_brut=str(tmp_path / "Obj"))
        d = b.GetObjectDir(p)
        d.mkdir(parents=True)
        _poser(d, "src_b.o")
        assert b._ObjetsOrphelins(p, d, []) == []

    def test_dossier_commun_a_deux_projets_rien_n_est_retire(self, tmp_path):
        b, p, wks = _builder(tmp_path, obj_dir_brut=str(tmp_path / "Obj" / "P"))
        q = Project(name="Q")
        q.kind = ProjectKind.STATIC_LIB
        q.objDir = str(tmp_path / "Obj" / "P")    # le meme dossier, ecrit en dur
        wks.projects["Q"] = q
        d = b.GetObjectDir(p)
        d.mkdir(parents=True)
        _poser(d, "src_q.o")
        assert b._ObjetsOrphelins(p, d, []) == []

    def test_temoin_dossier_propre_au_projet(self, tmp_path):
        b, p, _ = _builder(tmp_path, obj_dir_brut=str(tmp_path / "Obj" / "%{prj.name}").replace("%{prj.name}", "P"))
        d = b.GetObjectDir(p)
        d.mkdir(parents=True)
        _poser(d, "src_b.o")
        assert [o.name for o in b._ObjetsOrphelins(p, d, [])] == ["src_b.o"]


_WORKSPACE = textwrap.dedent("""\
    from Jenga import *
    from Jenga.GlobalToolchains import *

    with workspace("Orphelins"):
        configurations(["Debug"])
        RegisterJengaGlobalToolchains()

        with project("Lib"):
            staticlib()
            language("C++")
            files(["lib/*.cpp"])

        with project("App"):
            consoleapp()
            language("C++")
            files(["main.cpp"])
            dependson(["Lib"])
            links(["Lib"])
""")


def _jenga(root: Path, *args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run([sys.executable, "-m", "Jenga", "build", *args, "--no-daemon", "--jenga-file", str(root / "Orphelins.jenga")],
                          cwd=str(root), env=env, capture_output=True, text=True, encoding="utf-8", errors="replace",
                          timeout=600)


def _un(chemin: Path, motif: str):
    return sorted(chemin.rglob(motif))


class TestBoutEnBout:
    def test_renommer_puis_retirer_une_source(self, tmp_path):
        r = tmp_path
        (r / "Orphelins.jenga").write_text(_WORKSPACE, encoding="utf-8")
        (r / "lib").mkdir()
        (r / "lib" / "un.cpp").write_text("int un() { return 1; }\n", encoding="utf-8")
        (r / "lib" / "deux.cpp").write_text("int deux() { return 2; }\n", encoding="utf-8")
        (r / "lib" / "inutile.cpp").write_text("int inutile_fonction() { return 9; }\n", encoding="utf-8")
        (r / "main.cpp").write_text("int un();\nint deux();\nint main() { return un() + deux() == 3 ? 0 : 1; }\n",
                                    encoding="utf-8")
        p1 = _jenga(r)
        if p1.returncode != 0:
            pytest.skip("pas de compilateur utilisable ici :\n" + (p1.stdout + p1.stderr)[-600:])
        un = _un(r / "Build", "lib_un.o*")
        un = [x for x in un if x.suffix in (".o", ".obj")]
        assert un and _un(r / "Build", "lib_deux.o*"), p1.stdout[-800:]
        t_un = un[0].stat().st_mtime_ns
        archive = [x for x in _un(r / "Build", "*Lib*") if x.suffix in (".a", ".lib")][0]

        # 1. RENOMMER deux.cpp en trois.cpp (meme contenu)
        time.sleep(1.1)
        (r / "lib" / "deux.cpp").rename(r / "lib" / "trois.cpp")
        p2 = _jenga(r)
        assert p2.returncode == 0, (p2.stdout + p2.stderr)[-1500:]
        assert not _un(r / "Build", "lib_deux.*"), "l'objet de la source renommee est reste (et ses compagnons)"
        assert [x for x in _un(r / "Build", "lib_trois.o*") if x.suffix in (".o", ".obj")]
        assert un[0].stat().st_mtime_ns == t_un, "un.cpp a ete recompile : le menage ne doit rien reconstruire"
        contenu = archive.read_bytes()
        assert b"lib_trois" in contenu and b"lib_deux" not in contenu, "l'archive garde le membre renomme"
        assert "orphelin" in p2.stdout + p2.stderr

        # 2. RETIRER inutile.cpp : la cible ne passe plus pour a jour, l'archive le perd, rien ne se recompile
        time.sleep(1.1)
        (r / "lib" / "inutile.cpp").unlink()
        p3 = _jenga(r)
        assert p3.returncode == 0, (p3.stdout + p3.stderr)[-1500:]
        assert not _un(r / "Build", "lib_inutile.*")
        assert b"inutile_fonction" not in archive.read_bytes(), "l'archive contient encore le code retire"
        assert un[0].stat().st_mtime_ns == t_un

        # 3. Temoin : rien ne change, rien ne bouge (ni relien, ni message)
        t_archive = archive.stat().st_mtime_ns
        p4 = _jenga(r)
        assert p4.returncode == 0
        assert archive.stat().st_mtime_ns == t_archive and "orphelin" not in p4.stdout + p4.stderr
