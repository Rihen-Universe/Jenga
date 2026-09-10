# -*- coding: utf-8 -*-
"""Banc de la signature des applications de bureau.

Ce qui est vérifiable sans certificat ni Mac : le DSL, la lecture des secrets,
le masquage dans les journaux, et le format des sommes de contrôle. La pose
d'une vraie signature Authenticode demande un certificat et le SDK Windows ;
elle a été éprouvée à la main le 10 septembre 2026, avec horodatage.
"""
import hashlib
import os
import subprocess
import sys
from pathlib import Path

import pytest

from Jenga.Core import Api, Signing


# =============================================================================
#  Le DSL
# =============================================================================
def test_les_mots_du_dsl_existent():
    for mot in ("windowssign", "windowscertificate", "windowscertificatepass",
                "windowstimestampurl", "macossign", "macossigningidentity",
                "macosentitlements", "macosnotaryprofile",
                "linuxsign", "linuxgpgkey", "appurl"):
        assert hasattr(Api, mot), mot
        assert mot in Api.__all__, f"{mot} absent de __all__"


def test_ne_rien_signer_est_le_defaut():
    """Un projet qui ne demande rien ne doit pas se mettre a signer."""
    p = Api.Project(name="Muet")
    assert p.windowsSign is False
    assert p.macosSign is False
    assert p.linuxSign is False
    # Et le point d'entree commun le respecte, sur les trois systemes.
    for systeme in ("windows", "macos", "linux"):
        assert Signing.SignerProjet(p, ["inexistant.bin"], systeme) is True


# =============================================================================
#  Les secrets
# =============================================================================
def test_l_environnement_l_emporte_sur_le_projet(monkeypatch):
    monkeypatch.setenv("JENGA_WINDOWS_CERT_PASSWORD", "depuis-env")
    assert Signing._Secret("JENGA_WINDOWS_CERT_PASSWORD", "depuis-projet", "x") == "depuis-env"


def test_le_projet_sert_de_repli(monkeypatch):
    monkeypatch.delenv("JENGA_WINDOWS_CERT_PASSWORD", raising=False)
    assert Signing._Secret("JENGA_WINDOWS_CERT_PASSWORD", "depuis-projet", "x") == "depuis-projet"


def test_un_secret_long_ne_fuit_pas_dans_le_journal():
    ligne = Signing._Masquer(["signtool", "/p", "MotDePasseTresLong"],
                             ["MotDePasseTresLong"])
    assert "MotDePasseTresLong" not in ligne
    assert "***" in ligne


def test_un_secret_court_ne_mange_pas_le_reste_de_la_ligne():
    """Un mot de passe court est souvent un morceau de nom de fichier.

    Avec un secret « essai », le chemin `essai.pfx` devenait `***.pfx` : on
    masquait une information utile sans rien proteger de plus.
    """
    ligne = Signing._Masquer(["signtool", "/f", "essai.pfx", "/p", "essai"],
                             ["essai"])
    assert "essai.pfx" in ligne          # le chemin reste lisible
    assert ligne.endswith("***")         # le mot de passe, non


# =============================================================================
#  Linux : sommes de contrôle
# =============================================================================
def test_les_sommes_ont_le_format_de_sha256sum(tmp_path):
    a = tmp_path / "a.bin"
    a.write_bytes(b"bonjour")
    b = tmp_path / "b.bin"
    b.write_bytes(b"le monde")

    assert Signing.SignerLinux([str(a), str(b)], cle_gpg="", sommes=True) is True

    sommes = (tmp_path / "SHA256SUMS").read_text(encoding="utf-8")
    lignes = [l for l in sommes.splitlines() if l.strip()]
    assert len(lignes) == 2

    for ligne, fichier in zip(lignes, (a, b)):
        empreinte, nom = ligne.split("  ", 1)   # DEUX espaces : c'est la norme
        assert nom == fichier.name
        assert empreinte == hashlib.sha256(fichier.read_bytes()).hexdigest()


def test_sans_fichier_la_signature_linux_ne_fait_rien(tmp_path):
    assert Signing.SignerLinux([], cle_gpg="", sommes=True) is True
    assert not (tmp_path / "SHA256SUMS").exists()


# =============================================================================
#  Windows : bout en bout, quand la machine le permet
# =============================================================================
@pytest.mark.skipif(sys.platform != "win32", reason="Authenticode : Windows seulement")
def test_signature_authenticode_de_bout_en_bout(tmp_path):
    """Signe un vrai binaire avec un certificat jetable, et relit l'en-tete PE.

    On ne verifie PAS la validite de la chaine : un certificat auto-signe n'est
    pas de confiance, et c'est normal. On verifie que la signature a bien ete
    ECRITE dans le fichier, ce qui est la part du travail qui revient a Jenga.
    """
    outil, _ = Signing.TrouverOutilWindows()
    if not outil:
        pytest.skip("signtool absent : SDK Windows non installe")

    pfx = tmp_path / "jetable.pfx"
    creation = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         f"$c = New-SelfSignedCertificate -Type CodeSigningCert "
         f"-Subject 'CN=Jenga Test' -CertStoreLocation Cert:\\CurrentUser\\My "
         f"-KeyUsage DigitalSignature -NotAfter (Get-Date).AddYears(1); "
         f"$p = ConvertTo-SecureString -String 'test' -Force -AsPlainText; "
         f"Export-PfxCertificate -Cert $c -FilePath '{pfx}' -Password $p | Out-Null"],
        capture_output=True, text=True)
    if creation.returncode != 0 or not pfx.exists():
        pytest.skip("impossible de creer un certificat jetable")

    # Un vrai PE a signer : celui de l'interpreteur qui fait tourner ce test.
    cible = tmp_path / "cible.exe"
    cible.write_bytes(Path(sys.executable).read_bytes())

    os.environ["JENGA_WINDOWS_CERT_PASSWORD"] = "test"
    try:
        assert Signing.SignerWindows([str(cible)], certificat=str(pfx)) is True
    finally:
        os.environ.pop("JENGA_WINDOWS_CERT_PASSWORD", None)

    assert _TailleDuRepertoireDeCertificats(cible) > 0, \
        "signtool a rendu 0 mais aucune signature n'est dans le fichier"


def _TailleDuRepertoireDeCertificats(chemin: Path) -> int:
    """L'entree 4 du DataDirectory d'un PE : la signature Authenticode."""
    import struct
    d = chemin.read_bytes()[:0x600]
    off = struct.unpack_from("<I", d, 0x3C)[0]
    if d[off:off + 4] != b"PE\x00\x00":
        return 0
    magic = struct.unpack_from("<H", d, off + 24)[0]
    base = off + 24 + (112 if magic == 0x20b else 96)
    _, taille = struct.unpack_from("<II", d, base + 4 * 8)
    return taille
