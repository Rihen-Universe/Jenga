# AUTEUR : TEUGUIA TADJUIDJE Rodolf Séderis — Rihen
#
# Le diagnostic de binaire VERROUILLE : il doit NOMMER le tenant, attendre un
# tiers, et echouer tout de suite quand c'est la cible elle-meme.
#
# 🔴 CE QUI A MOTIVE CES TESTS (26-27/09/2026). Le message disait « une
#    execution precedente tourne encore » et conseillait
#    `taskkill /IM <cible>` -- sur un verrou qui ne venait PAS de la cible.
#    Aucun processus du binaire n'existait ; le tenant etait un assistant
#    d'IDE, et le message a envoye chercher pendant quarante minutes un
#    processus qui n'a jamais existe.
#
#    *Un diagnostic qui NOMME une cause qu'il n'a pas mesuree coute plus cher
#    qu'un diagnostic muet* : on lui fait confiance.
#
# ⚠️ POURQUOI UN DOSSIER SERT DE CIBLE VERROUILLEE. Il fallait un
#    `PermissionError` DETERMINISTE, sans course entre un processus qui tient un
#    fichier et une construction qui essaie de le relier -- une premiere version
#    de cette epreuve passait ou echouait selon la duree de la compilation, donc
#    elle ne mesurait pas ce qu'elle annoncait. Sous Windows, ouvrir un DOSSIER
#    en ecriture leve PermissionError a coup sur. La cause du refus est la meme
#    du point de vue de la fonction testee : le chemin existe et ne s'ouvre pas.
import os
import sys
import threading
import time
from pathlib import Path

import pytest

from Jenga.Core.Builder import Builder

pytestmark = pytest.mark.skipif(
    os.name != "nt", reason="ouvrir un dossier en ecriture ne leve pas sur POSIX"
)


class _BuilderNu(Builder):
    """Juste assez de Builder pour appeler la fonction testee.

    `Builder` est abstrait ; on n'en veut ni la resolution de dependances ni la
    chaine d'outils, seulement `_VerifierCibleEcrivable`.
    """

    def __init__(self):  # pragma: no cover - aucune logique
        pass

    def Compile(self, *a, **k):  # pragma: no cover
        raise NotImplementedError

    def Link(self, *a, **k):  # pragma: no cover
        raise NotImplementedError

    def GetModuleFlags(self, *a, **k):  # pragma: no cover
        raise NotImplementedError

    def GetObjectExtension(self, *a, **k):  # pragma: no cover
        raise NotImplementedError

    def GetOutputExtension(self, *a, **k):  # pragma: no cover
        raise NotImplementedError


@pytest.fixture
def cible_verrouillee(tmp_path):
    """Un chemin qui existe et refuse l'ecriture, de facon reproductible."""
    p = tmp_path / "NkAnimaEditor.exe"
    p.mkdir()
    return p


def test_le_tenant_est_nomme(cible_verrouillee, monkeypatch, capsys):
    monkeypatch.setenv("JENGA_ATTENTE_VERROU", "0")
    monkeypatch.setattr(
        Builder, "_TenantsDuFichier", staticmethod(lambda _c: ["4242 Assistant Python"])
    )
    b = _BuilderNu()
    assert b._VerifierCibleEcrivable(cible_verrouillee) is False
    sortie = capsys.readouterr()
    texte = sortie.out + sortie.err
    # Le PID ET le nom : un PID seul n'aide pas a decider si c'est a nous.
    assert "4242" in texte
    assert "Assistant Python" in texte


def test_tenant_inconnu_ne_se_devine_pas(cible_verrouillee, monkeypatch, capsys):
    """Quand personne n'est nomme, le message le DIT au lieu d'inventer.

    C'est la regression exacte : l'ancien texte affirmait « une execution
    precedente tourne encore » sans avoir rien mesure.
    """
    monkeypatch.setenv("JENGA_ATTENTE_VERROU", "0")
    monkeypatch.setattr(Builder, "_TenantsDuFichier", staticmethod(lambda _c: []))
    b = _BuilderNu()
    assert b._VerifierCibleEcrivable(cible_verrouillee) is False
    texte = "".join(capsys.readouterr())
    assert "inconnu" in texte.lower()
    assert "execution precedente tourne encore" not in texte


def test_la_cible_elle_meme_echoue_sans_attendre(cible_verrouillee, monkeypatch, capsys):
    """Une execution de la cible ne se fermera pas seule : attendre est inutile.

    ⚠️ LE CRITERE PORTE SUR LE TEMPS, pas seulement sur le verdict. Avec un
       plafond de 30 s, un `False` rendu au bout de 30 s serait le MEME verdict
       pour une raison opposee.
    """
    monkeypatch.setenv("JENGA_ATTENTE_VERROU", "30")
    monkeypatch.setattr(
        Builder,
        "_TenantsDuFichier",
        staticmethod(lambda _c: ["777 NkAnimaEditor.exe"]),
    )
    b = _BuilderNu()
    t0 = time.time()
    assert b._VerifierCibleEcrivable(cible_verrouillee) is False
    assert time.time() - t0 < 3.0, "il a attendu alors que la cible se tient elle-meme"
    texte = "".join(capsys.readouterr())
    assert "sa propre execution" in texte
    assert "777" in texte


def test_un_tiers_qui_relache_laisse_passer(cible_verrouillee, monkeypatch, capsys):
    """Le verrou d'un tiers est attendu, et la construction continue.

    Le dossier disparait au bout de ~1,5 s : le chemin n'existe plus, donc il
    n'y a plus rien a remplacer -- exactement l'etat ou l'edition de liens peut
    reprendre.
    """
    monkeypatch.setenv("JENGA_ATTENTE_VERROU", "20")
    monkeypatch.setattr(
        Builder, "_TenantsDuFichier", staticmethod(lambda _c: ["4242 Indexeur"])
    )

    def relacher():
        time.sleep(1.5)
        try:
            cible_verrouillee.rmdir()
        except OSError:  # pragma: no cover - le test a deja echoue ailleurs
            pass

    fil = threading.Thread(target=relacher, daemon=True)
    fil.start()
    b = _BuilderNu()
    t0 = time.time()
    assert b._VerifierCibleEcrivable(cible_verrouillee) is True
    ecoule = time.time() - t0
    fil.join(timeout=5)
    # Il a VRAIMENT attendu : un `True` immediat voudrait dire que le verrou
    # n'avait jamais ete vu, et le test ne prouverait rien.
    assert ecoule >= 1.0, "il n'a pas attendu : le verrou n'a pas ete vu"
    texte = "".join(capsys.readouterr())
    assert "libere" in texte


def test_plafond_zero_echoue_tout_de_suite(cible_verrouillee, monkeypatch):
    """`JENGA_ATTENTE_VERROU=0` : ce qu'une integration continue veut."""
    monkeypatch.setenv("JENGA_ATTENTE_VERROU", "0")
    monkeypatch.setattr(Builder, "_TenantsDuFichier", staticmethod(lambda _c: []))
    b = _BuilderNu()
    t0 = time.time()
    assert b._VerifierCibleEcrivable(cible_verrouillee) is False
    assert time.time() - t0 < 2.0


def test_plafond_illisible_retombe_sur_le_defaut(monkeypatch):
    """Une valeur absurde ne desactive pas l'attente en silence."""
    monkeypatch.setenv("JENGA_ATTENTE_VERROU", "beaucoup")
    assert Builder._PlafondAttenteVerrou() == Builder._ATTENTE_VERROU_S
    monkeypatch.setenv("JENGA_ATTENTE_VERROU", "-5")
    assert Builder._PlafondAttenteVerrou() == Builder._ATTENTE_VERROU_S
    monkeypatch.setenv("JENGA_ATTENTE_VERROU", "7.5")
    assert Builder._PlafondAttenteVerrou() == 7.5


def test_cible_absente_est_ecrivable(tmp_path):
    """Rien a remplacer = rien a attendre. Le zero de cette fonction."""
    b = _BuilderNu()
    assert b._VerifierCibleEcrivable(tmp_path / "jamais_ecrit.exe") is True


def test_le_tenant_reel_se_nomme(tmp_path):
    """Le Restart Manager repond-il vraiment ? Un cas dont on SAIT la reponse.

    ⚠️ SANS CE TEST, LES AUTRES NE PROUVENT QUE LE MESSAGE. Ils bouchonnent
       `_TenantsDuFichier` : ils verifient qu'un tenant NOMME s'affiche, pas
       qu'on sache le nommer. Ici on tient un fichier en exclusif depuis CE
       processus, dont on connait le PID.
    """
    f = tmp_path / "temoin.bin"
    f.write_bytes(b"temoin")
    import msvcrt  # noqa: F401  (present sur Windows, garde par le skipif)

    # Ouverture en exclusif : le partage est refuse aux autres handles.
    import ctypes
    from ctypes import wintypes

    GENERIC_WRITE = 0x40000000
    OPEN_EXISTING = 3
    h = ctypes.windll.kernel32.CreateFileW(
        wintypes.LPCWSTR(str(f)), GENERIC_WRITE, 0, None, OPEN_EXISTING, 0, None
    )
    assert h != -1, "impossible d'ouvrir le temoin en exclusif"
    try:
        tenants = Builder._TenantsDuFichier(f)
        assert tenants, "le Restart Manager n'a nomme personne sur un verrou CONNU"
        assert any(str(os.getpid()) == t.split(" ", 1)[0] for t in tenants), (
            f"il n'a pas nomme ce processus ({os.getpid()}) : {tenants}"
        )
    finally:
        ctypes.windll.kernel32.CloseHandle(h)
