#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_signature_compilation.py
===================================
AUTEUR : TEUGUIA TADJUIDJE Rodolf Séderis — Rihen

Banc de la signature de compilation (2.8.15) : elle depend de ce qui change
l'objet, pas de la facon dont jenga a ete appele.

Le defaut : la signature portait l'action (`build`, `run`, `test`) et tous les
jetons d'option, dont `target:<cible demandee>`. Demander une autre cible
changeait la signature de chaque objet de chaque projet dont elle depend.
Mesure sur le workspace Nkentseu, le 07/10/2026 : passer de `--target PV3DE` a
`--target NKCode` recompilait 380 fichiers, dont tout le noyau, sans qu'une
ligne ait change.

Ce que le banc exige :
  - la signature d'un fichier d'une bibliotheque est LA MEME quelle que soit
    l'application demandee, l'action, `--verbose`, `--no-daemon` ;
  - elle CHANGE quand un filtre declenche par ces memes jetons change vraiment
    la compilation (une definition en plus) : on n'a pas rendu la signature
    aveugle, on l'a rendue juste.

Aucune compilation : seule la signature est calculee.

Usage :
  python -m pytest tests/test_signature_compilation.py -v
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pytest
import Jenga.Core.Api as Api
from Jenga.Core.Loader import Loader
from Jenga.Commands.Build import BuildCommand


WORKSPACE = '''from Jenga import *

with workspace("Atelier"):
    configurations(["Debug", "Release"])

    with project("Socle"):
        staticlib()
        language("C++")
        files(["socle/**.cpp"])
        %(filtre)s

    with project("Un"):
        consoleapp()
        language("C++")
        files(["un/**.cpp"])
        dependson(["Socle"])

    with project("Deux"):
        consoleapp()
        language("C++")
        files(["deux/**.cpp"])
        dependson(["Socle"])
'''


def _ecrire(tmp_path, filtre="pass"):
    for d in ("socle", "un", "deux"):
        (tmp_path / d).mkdir(exist_ok=True)
        (tmp_path / d / "a.cpp").write_text("int f_%s() { return 0; }\n" % d, encoding="utf-8")
    f = tmp_path / "Atelier.jenga"
    f.write_text(WORKSPACE % {"filtre": filtre}, encoding="utf-8")
    return f


def _constructeur(fichier, cible, action="build", verbose=False, no_daemon=False):
    """Le constructeur que `jenga <action> --target <cible>` fabrique, avec les
    jetons d'option que la ligne de commande produit."""
    Api.resetstate()
    ws = Loader(verbose=False).LoadWorkspace(str(fichier))
    assert ws is not None
    options = BuildCommand.CollectFilterOptions(
        config="Debug", platform=None, target=cible, verbose=verbose,
        no_cache=False, no_daemon=no_daemon, extra=["action:%s" % action])
    try:
        builder = BuildCommand.CreateBuilder(ws, "Debug", None, cible, verbose, action=action, options=options)
    except Exception as e:  # pas de compilateur sur cette machine
        pytest.skip("aucun constructeur pour l'hote : %s" % e)
    return ws, builder


def _signature(fichier, cible, **k):
    ws, b = _constructeur(fichier, cible, **k)
    p = ws.projects["Socle"]
    b._ApplyProjectFilters(p)
    src = str((Path(fichier).parent / "socle" / "a.cpp").resolve())
    obj = str(Path(b.GetObjectDir(p)) / b.GetObjectName(p, Path(src)))
    return b._ComputeCompileSignature(p, src, obj), list(b.options), list(p.defines)


class TestLaSignatureIgnoreLaFaconDAppeler:
    def test_une_autre_cible_ne_change_pas_la_signature_de_la_bibliotheque(self, tmp_path):
        f = _ecrire(tmp_path)
        s1, o1, _ = _signature(f, "Un")
        s2, o2, _ = _signature(f, "Deux")
        # le montage porte bien la difference qui causait le defaut
        assert "target:un" in o1 and "target:deux" in o2
        assert s1 == s2

    def test_run_et_test_ne_recompilent_pas_ce_que_build_a_fait(self, tmp_path):
        f = _ecrire(tmp_path)
        s_build, o_build, _ = _signature(f, "Un", action="build")
        s_run, o_run, _ = _signature(f, "Un", action="run")
        s_test, _, _ = _signature(f, "Un", action="test")
        assert "action:build" in o_build and "action:run" in o_run
        assert s_build == s_run == s_test

    def test_bavard_ou_sans_demon_ne_change_rien(self, tmp_path):
        f = _ecrire(tmp_path)
        s0, _, _ = _signature(f, "Un")
        s1, o1, _ = _signature(f, "Un", verbose=True, no_daemon=True)
        assert "verbose" in o1 and "no-daemon" in o1
        assert s0 == s1


class TestLaSignatureVoitToujoursCeQuiChangeLObjet:
    """Les contre-epreuves : le meme jeton, quand un filtre s'en sert pour changer
    la compilation, invalide bien l'objet -- par la definition qu'il ajoute."""

    def test_un_filtre_sur_la_cible_qui_ajoute_une_definition(self, tmp_path):
        filtre = 'with filter("options:target:deux"):\n            defines(["POUR_DEUX"])'
        f = _ecrire(tmp_path, filtre)
        s1, _, d1 = _signature(f, "Un")
        s2, _, d2 = _signature(f, "Deux")
        assert "POUR_DEUX" not in d1 and "POUR_DEUX" in d2, (d1, d2)
        assert s1 != s2

    def test_un_filtre_sur_l_action_qui_ajoute_une_definition(self, tmp_path):
        filtre = 'with filter("action:test"):\n            defines(["EN_TEST"])'
        f = _ecrire(tmp_path, filtre)
        s_build, _, d_build = _signature(f, "Un", action="build")
        s_test, _, d_test = _signature(f, "Un", action="test")
        assert "EN_TEST" not in d_build and "EN_TEST" in d_test, (d_build, d_test)
        assert s_build != s_test

    def test_la_configuration_change_toujours_la_signature(self, tmp_path):
        f = _ecrire(tmp_path)
        Api.resetstate()
        ws = Loader(verbose=False).LoadWorkspace(str(f))
        sigs = []
        for cfg in ("Debug", "Release"):
            try:
                b = BuildCommand.CreateBuilder(ws, cfg, None, "Un", False, action="build", options=[])
            except Exception as e:
                pytest.skip("aucun constructeur pour l'hote : %s" % e)
            p = ws.projects["Socle"]
            b._ApplyProjectFilters(p)
            src = str((tmp_path / "socle" / "a.cpp").resolve())
            sigs.append(b._ComputeCompileSignature(p, src, str(Path(b.GetObjectDir(p)) / "a.o")))
        assert sigs[0] != sigs[1]
