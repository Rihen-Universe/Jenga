#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Correctif Jenga 2.8.0 : dire OU et POURQUOI un .jenga casse au chargement.

    python corriger.py                    pose le correctif
    python corriger.py --retirer          le retire
    python corriger.py --ou               dit quel Jenga serait modifie
    python corriger.py --racine <chemin>  vise une AUTRE copie de Jenga

CE QUE CA CHANGE
================
Avant, un fichier .jenga fautif donnait une seule ligne :

    Error loading workspace: name 'PkgExists' is not defined

Ni le fichier, ni la ligne, ni la cause. Apres :

    Error loading workspace: name 'PkgExists' is not defined
      dans ...\\NKWindow\\NKWindow.jenga, ligne 31
        _HAS_LIBDECOR = PkgExists("libdecor-0")
      PkgExists n'est pas un mot de Jenga : c'est une fonction que le
      workspace D'ORIGINE de ce fichier definit lui-meme, en general dans
      un config/*.jenga charge par useconfig.
      Ce fichier vient d'un AUTRE projet. Si vous employez un kit, ne
      l'incluez pas : le kit contient deja ce module compile.

Et tout kit produit ensuite par `jenga kit` porte le meme avertissement
dans son en-tete et dans son KIT.txt.

CE QU'IL FAUT SAVOIR AVANT DE LE LANCER
=======================================
  - Il modifie l'installation de Jenga que la commande `jenga` importe. Il
    la trouve seule, sans qu'on ait a chercher le chemin.
  - Il sauvegarde chaque fichier en `<nom>.avant-correctif` avant d'ecrire.
  - Il ne fait rien s'il est deja pose : on peut le relancer sans risque.
  - Il PRESERVE les fins de ligne du fichier : sur un depot git, le diff ne
    montre que les lignes reellement changees.
  - Une mise a jour de Jenga l'effacera. C'est normal, il est provisoire.
  - Il ne touche qu'aux messages : ni la construction, ni les chaines
    d'outils, ni rien qui produise un binaire.

IL Y A PLUSIEURS COPIES DE JENGA SUR UNE MACHINE DE DEVELOPPEMENT.
Celle que la commande lit est celle que Python importe ; l'arbre source du
depot en est une autre. Pour tenir les deux d'accord :

    python corriger.py
    python corriger.py --racine D:\\Projets\\MacShared\\Projets\\Jenga\\Jenga
"""
import argparse
import ast
import io
import os
import shutil
import sys

VERSION_VISEE = "2.8.0"

# ── Loader.py : le bloc qui avalait la cause ────────────────────────────────
LOADER_AVANT = """        except Exception as e:
            Colored.PrintError(f"Error loading workspace: {e}")
            if self.verbose:
                traceback.print_exc()
            return None"""

LOADER_APRES = """        except Exception as e:
            # ── DIRE OU, ET POURQUOI ────────────────────────────────────
            #
            # « name 'PkgExists' is not defined » n'apprend rien : ni le
            # fichier, ni la ligne, ni la cause. Or un .jenga est du Python
            # execute, donc la pile porte le fichier et la ligne fautifs.
            Colored.PrintError(f"Error loading workspace: {e}")

            _tb, _coupable = e.__traceback__, None
            while _tb is not None:
                _nom = _tb.tb_frame.f_code.co_filename
                if _nom.endswith(".jenga"):
                    _coupable = (_nom, _tb.tb_lineno)
                _tb = _tb.tb_next

            if _coupable is not None:
                Colored.PrintError(
                    f"  dans {_coupable[0]}, ligne {_coupable[1]}")
                try:
                    with open(_coupable[0], "r", encoding="utf-8-sig") as _f:
                        _src = _f.readlines()
                    if 0 < _coupable[1] <= len(_src):
                        Colored.PrintError(
                            f"    {_src[_coupable[1] - 1].rstrip()}")
                except OSError:
                    pass

            if isinstance(e, NameError):
                _quoi = str(e).split("'")[1] if "'" in str(e) else "ce nom"
                Colored.PrintWarning(
                    f"  {_quoi} n'est pas un mot de Jenga : c'est une "
                    "fonction que le workspace D'ORIGINE de ce fichier")
                Colored.PrintWarning(
                    "  definit lui-meme, en general dans un config/*.jenga "
                    "charge par useconfig.")
                if _coupable is not None and not str(_coupable[0]).startswith(
                        str(filePath.parent)):
                    Colored.PrintWarning(
                        "  Ce fichier vient d'un AUTRE projet. Si vous "
                        "employez un kit, ne l'incluez pas : le kit")
                    Colored.PrintWarning(
                        "  contient deja ce module compile. Retirez son "
                        "include() et appelez la fonction du kit.")

            if self.verbose:
                traceback.print_exc()
            return None"""

# ── Kit.py : l'avertissement dans le kit genere ─────────────────────────────
KIT_AVANT = '''        add("# L'ordre des archives est celui que l'editeur de liens exige (du plus")
        add("# dependant au plus fondamental) ; ne le changez pas.")
        add("# =============================================================================")'''

KIT_APRES = '''        add("# L'ordre des archives est celui que l'editeur de liens exige (du plus")
        add("# dependant au plus fondamental) ; ne le changez pas.")
        add("#")
        add("# /!\\\\ N'INCLUEZ AUCUN .jenga DU PROJET D'ORIGINE.")
        add("#")
        add("#     with include(\\".../UnModule/UnModule.jenga\\"):   <-- NON")
        add("#")
        add("# Ces fichiers appellent des fonctions que leur propre workspace")
        add("# definit par useconfig, et qui n'existent pas chez vous : la lecture")
        add("# echoue sur un « name '...' is not defined ». C'est aussi inutile, le")
        add("# module etant deja dans ce kit, compile, avec ses dependances.")
        add("# =============================================================================")'''

TXT_AVANT = '''            "Citez la date de construction dans vos retours.",'''

TXT_APRES = '''            "N'incluez aucun .jenga du projet d'origine dans votre",
            "workspace : ces fichiers dependent de la configuration de LEUR",
            "workspace et casseront a la lecture. Tout ce dont vous avez",
            "besoin est deja ici.",
            "",
            "Citez la date de construction dans vos retours.",'''

REMPLACEMENTS = [
    (os.path.join("Core", "Loader.py"), [(LOADER_AVANT, LOADER_APRES)]),
    (os.path.join("Commands", "Kit.py"), [(KIT_AVANT, KIT_APRES),
                                          (TXT_AVANT, TXT_APRES)]),
]


def lire(chemin):
    """Lit en gardant les fins de ligne telles quelles."""
    with io.open(chemin, "r", encoding="utf-8", newline="") as f:
        return f.read()


def ecrire(chemin, texte):
    with io.open(chemin, "w", encoding="utf-8", newline="") as f:
        f.write(texte)


def adapter(motif, modele):
    """Le motif, avec les fins de ligne du fichier vise."""
    return motif.replace("\n", "\r\n") if "\r\n" in modele else motif


def trouver_jenga():
    try:
        import Jenga
    except ImportError:
        print("Jenga n'est pas installe pour ce Python.")
        print("Lancez ce script avec le meme Python que la commande jenga.")
        return None
    return os.path.dirname(os.path.abspath(Jenga.__file__))


def version_de(racine):
    try:
        for ligne in lire(os.path.join(racine, "_version.py")).splitlines():
            if "__version__" in ligne and "=" in ligne:
                return ligne.split("=")[1].strip().strip('"\'')
    except OSError:
        pass
    return "inconnue"


def etat(racine):
    poses = total = 0
    for relatif, paires in REMPLACEMENTS:
        chemin = os.path.join(racine, relatif)
        if not os.path.exists(chemin):
            continue
        texte = lire(chemin)
        for _, apres in paires:
            total += 1
            if adapter(apres, texte) in texte:
                poses += 1
    if total == 0:
        return "indeterminable"
    if poses == 0:
        return "absent"
    return "pose" if poses == total else "partiel"


def appliquer(racine, retirer=False):
    fait = 0
    for relatif, paires in REMPLACEMENTS:
        chemin = os.path.join(racine, relatif)
        if not os.path.exists(chemin):
            print("  ! %s absent, ignore" % relatif)
            continue
        texte = original = lire(chemin)
        for avant, apres in paires:
            a, b = adapter(avant, texte), adapter(apres, texte)
            de, vers = (b, a) if retirer else (a, b)
            if vers in texte:
                continue
            if texte.count(de) != 1:
                print("  ! %s : le texte attendu n'y est pas (%d fois)."
                      % (relatif, texte.count(de)))
                print("    Ce Jenga n'est pas celui que le correctif vise.")
                print("    Ne forcez pas : signalez-le.")
                return -1
            texte = texte.replace(de, vers)
        if texte == original:
            print("  = %s : rien a faire" % relatif)
            continue
        try:
            ast.parse(texte)
        except SyntaxError as err:
            print("  ! %s : le resultat ne compile pas (%s). Rien ecrit."
                  % (relatif, err))
            return -1
        sauvegarde = chemin + ".avant-correctif"
        if not os.path.exists(sauvegarde):
            shutil.copy2(chemin, sauvegarde)
        ecrire(chemin, texte)
        print("  %s %s" % ("retire de" if retirer else "pose dans", relatif))
        fait += 1
    return fait


def main():
    p = argparse.ArgumentParser(description="Correctif Jenga 2.8.0")
    p.add_argument("--retirer", action="store_true")
    p.add_argument("--ou", action="store_true")
    p.add_argument("--racine", default=None,
                   help="une autre copie de Jenga (l'arbre source du depot)")
    a = p.parse_args()

    racine = a.racine or trouver_jenga()
    if racine is None:
        return 1
    if not os.path.isdir(racine):
        print("Dossier introuvable : %s" % racine)
        return 1

    print("Jenga  : %s" % racine)
    v = version_de(racine)
    print("Version: %s" % v)
    print("Etat   : correctif %s" % etat(racine))
    if a.ou:
        return 0

    if v != VERSION_VISEE:
        print()
        print("Ce correctif vise Jenga %s, et celui-ci est en %s."
              % (VERSION_VISEE, v))
        print("Chaque remplacement est verifie : rien ne sera ecrit si le")
        print("texte attendu n'y est pas.")

    print()
    n = appliquer(racine, a.retirer)
    print()
    if n < 0:
        return 1
    if n == 0:
        print("Rien a faire : le correctif etait deja dans l'etat demande.")
    else:
        print("Termine. Pour revenir en arriere : python corriger.py --retirer")
    return 0


if __name__ == "__main__":
    sys.exit(main())
