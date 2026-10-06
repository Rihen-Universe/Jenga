# -*- coding: utf-8 -*-
"""Le stub du PCH (__jenga_pch.cpp) ne doit pas etre reecrit a l'identique.

Reecrit a chaque build, il etait toujours plus recent que le PCH : le test de
fraicheur (Builder.PchIsFresh) le compte parmi ses entrees, et le PCH etait
reconstruit A CHAQUE build. Mesure du 06/10/2026 (kit Canvas, clang-mingw) :
5,9 s de PCH par build ; un fichier touche passait de ~3,7 s a ~9,9 s.
"""
import os
import time

from Jenga.Core.Builders.Windows import EcrireSiDifferent


def test_contenu_identique_ne_touche_pas_la_date(tmp_path):
    f = tmp_path / "__jenga_pch.cpp"
    assert EcrireSiDifferent(f, '#include "pch.h"\n') is True
    ancien = time.time() - 3600
    os.utime(f, (ancien, ancien))
    assert EcrireSiDifferent(f, '#include "pch.h"\n') is False
    assert abs(f.stat().st_mtime - ancien) < 1.0


def test_contenu_different_est_reecrit(tmp_path):
    f = tmp_path / "__jenga_pch.cpp"
    EcrireSiDifferent(f, '#include "a.h"\n')
    assert EcrireSiDifferent(f, '#include "b.h"\n') is True
    assert f.read_text(encoding="utf-8") == '#include "b.h"\n'


def test_fichier_absent_est_cree(tmp_path):
    f = tmp_path / "absent" / ".." / "__jenga_pch.cpp"
    assert EcrireSiDifferent(f, "x\n") is True
    assert f.read_text(encoding="utf-8") == "x\n"
