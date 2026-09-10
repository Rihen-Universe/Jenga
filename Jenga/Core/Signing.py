#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Signing.py — signature des applications de bureau : Windows, macOS, Linux.

POURQUOI CE FICHIER EXISTE
==========================
Jenga savait signer un APK Android et rien d'autre. Les applications de bureau
sortaient donc **non signées**, et cela a un coût mesurable : Windows Defender
met en quarantaine les exécutables sans auteur connu, surtout quand ils
installent une chaîne de compilation. Les utilisateurs de NKCode l'ont signalé,
et la vérification des binaires livrés a confirmé l'absence totale de signature
Authenticode.

Une signature ne rend pas un programme sûr. Elle répond à une question plus
modeste et plus utile : **qui l'a produit, et le fichier a-t-il changé depuis ?**
C'est ce que les systèmes d'exploitation demandent, et c'est ce que leur absence
fait échouer.

LES TROIS SYSTÈMES NE FONT PAS LA MÊME CHOSE
============================================
C'est le point à comprendre avant de lire le code, et la raison pour laquelle il
n'y a pas une fonction mais trois.

**Windows — Authenticode, DANS le fichier.** La signature est écrite dans
l'exécutable lui-même, dans le répertoire de certificats de l'en-tête PE. Le
système la vérifie à chaque lancement. C'est le seul des trois où signer change
ce que voit l'utilisateur : « Éditeur : Rihen » au lieu de « Éditeur inconnu ».

**macOS — codesign, DANS le fichier aussi**, plus une étape de plus :
la **notarisation**. Apple veut avoir vu le binaire avant que Gatekeeper le
laisse s'ouvrir. Signer sans notariser ne suffit pas depuis macOS 10.15.

**Linux — RIEN dans le fichier.** Il n'existe aucun équivalent d'Authenticode
pour un ELF : le noyau ne vérifie pas de signature au lancement. La convention
du monde Linux est ailleurs, et elle est très établie : on publie des
**signatures détachées GPG** (`fichier.asc`) et des **sommes de contrôle**
(`SHA256SUMS`), et l'utilisateur vérifie avant d'installer. Les paquets `.deb`
et `.rpm`, eux, ont leur propre signature, portée par le gestionnaire de
paquets.

Prétendre que les trois font la même chose serait plus simple à documenter et
faux. Ce module fait donc ce que chaque système attend réellement.

LES MOTS DE PASSE
=================
Un mot de passe de certificat écrit dans un fichier `.jenga` finit dans git,
puis sur GitHub. Le module lit donc d'abord les variables d'environnement :

    JENGA_WINDOWS_CERT_PASSWORD
    JENGA_MACOS_KEYCHAIN_PASSWORD
    JENGA_GPG_PASSPHRASE

et n'accepte la valeur du projet qu'en dernier recours, avec un avertissement.
Aucun mot de passe n'est jamais journalisé : les commandes sont affichées avec
la valeur remplacée par `***`.
"""

import os
import shutil
import subprocess
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

from ..Utils import FileSystem, Process, Reporter


# Horodatage : sans lui, la signature cesse d'être valable à l'expiration du
# certificat, et tous les binaires deja distribues deviennent « non fiables ».
# Ce n'est pas une option, c'est la difference entre signer une fois et
# resigner chaque annee tout ce qu'on a publie.
HORODATAGE_PAR_DEFAUT = "http://timestamp.digicert.com"


def _Masquer(args: Sequence[str], secrets: Sequence[str]) -> str:
    """La ligne de commande, avec les secrets remplaces par ***.

    On masque un argument ENTIER quand il est exactement le secret. Le
    remplacement de sous-chaine n'intervient que pour les secrets d'au moins
    huit caracteres, parce qu'un mot de passe court est souvent un morceau de
    nom de fichier : avec un secret « essai », le chemin `essai.pfx` devenait
    `***.pfx`, ce qui masque une information utile sans rien proteger de plus.
    """
    rendu = []
    for a in args:
        masque = a
        for s in secrets:
            if not s:
                continue
            if masque == s:
                masque = "***"
            elif len(s) >= 8 and s in masque:
                masque = masque.replace(s, "***")
        rendu.append(masque)
    return " ".join(rendu)


def _Secret(nom_env: str, valeur_projet: str, quoi: str) -> str:
    """Le secret, pris dans l'environnement d'abord, dans le projet ensuite."""
    depuis_env = os.environ.get(nom_env, "")
    if depuis_env:
        return depuis_env
    if valeur_projet:
        Reporter.Warning(
            f"{quoi} lu depuis le fichier de projet. Preferez la variable "
            f"d'environnement {nom_env} : un secret dans un .jenga finit dans git."
        )
        return valeur_projet
    return ""


def _Lancer(args: List[str], secrets: Sequence[str] = ()) -> bool:
    """Execute, en montrant la commande sans ses secrets."""
    Reporter.Info("  " + _Masquer(args, secrets))
    resultat = Process.ExecuteCommand(args, captureOutput=True, silent=False)
    if resultat.returnCode != 0:
        sortie = (resultat.stderr or resultat.stdout or "").strip()
        if sortie:
            Reporter.Error("  " + sortie.splitlines()[-1])
        return False
    return True


# =============================================================================
#  WINDOWS — Authenticode
# =============================================================================
def TrouverOutilWindows() -> Tuple[str, str]:
    """Rend (chemin, genre) ou ("", "").

    Deux outils font le travail, et il faut les deux parce qu'ils ne vivent pas
    au meme endroit :

      * `signtool` vient du SDK Windows. C'est l'outil officiel, et il n'existe
        que sur Windows.
      * `osslsigncode` est un equivalent libre qui tourne AUSSI sur Linux et
        macOS. C'est lui qui permet de signer un binaire Windows depuis un CI
        Linux, ce que fait la moitie du monde.
    """
    direct = FileSystem.FindExecutable("signtool")
    if direct:
        return direct, "signtool"

    # signtool n'est presque jamais dans le PATH : il est range par version de
    # SDK, dans un sous-dossier par architecture. On prend la plus recente.
    for base in (r"C:\Program Files (x86)\Windows Kits\10\bin",
                 r"C:\Program Files\Windows Kits\10\bin"):
        racine = Path(base)
        if not racine.exists():
            continue
        versions = sorted((d for d in racine.iterdir() if d.is_dir()), reverse=True)
        for v in versions:
            for arch in ("x64", "x86", "arm64"):
                candidat = v / arch / "signtool.exe"
                if candidat.exists():
                    return str(candidat), "signtool"

    libre = FileSystem.FindExecutable("osslsigncode")
    if libre:
        return libre, "osslsigncode"
    return "", ""


def SignerWindows(fichiers: Sequence[str], certificat: str, motdepasse: str = "",
                  horodatage: str = "", nom_affiche: str = "",
                  url: str = "") -> bool:
    """Signe des .exe, .dll ou .msi en Authenticode.

    `certificat` est soit un fichier .pfx/.p12, soit — avec signtool seulement —
    le nom du sujet d'un certificat present dans le magasin de l'utilisateur.
    """
    if not fichiers:
        return True

    outil, genre = TrouverOutilWindows()
    if not outil:
        Reporter.Error(
            "Aucun outil de signature Windows. Installez le SDK Windows "
            "(signtool) ou osslsigncode."
        )
        return False

    horodatage = horodatage or HORODATAGE_PAR_DEFAUT
    secret = _Secret("JENGA_WINDOWS_CERT_PASSWORD", motdepasse,
                     "Mot de passe du certificat Windows")

    Reporter.Info(f"Signature Authenticode ({genre}) : {len(fichiers)} fichier(s)")
    tout_va_bien = True

    for f in fichiers:
        chemin = Path(f)
        if not chemin.exists():
            Reporter.Warning(f"  absent, ignore : {f}")
            continue

        if genre == "signtool":
            args = [outil, "sign", "/fd", "SHA256", "/tr", horodatage, "/td", "SHA256"]
            if certificat and Path(certificat).exists():
                args += ["/f", certificat]
                if secret:
                    args += ["/p", secret]
            elif certificat:
                # Pas un fichier : c'est le nom du sujet dans le magasin.
                args += ["/n", certificat]
            if nom_affiche:
                args += ["/d", nom_affiche]
            if url:
                args += ["/du", url]
            args.append(str(chemin))
        else:
            if not (certificat and Path(certificat).exists()):
                Reporter.Error(
                    "osslsigncode exige un fichier .pfx : le magasin de "
                    "certificats de Windows ne lui est pas accessible."
                )
                return False
            sortie = chemin.with_suffix(chemin.suffix + ".signed")
            args = [outil, "sign", "-pkcs12", certificat]
            if secret:
                args += ["-pass", secret]
            args += ["-h", "sha256", "-ts", horodatage]
            if nom_affiche:
                args += ["-n", nom_affiche]
            if url:
                args += ["-i", url]
            args += ["-in", str(chemin), "-out", str(sortie)]

        if not _Lancer(args, [secret]):
            tout_va_bien = False
            continue

        if genre == "osslsigncode":
            # osslsigncode ecrit a cote : on remet en place, sinon l'appelant
            # publie le fichier NON signe sans s'en apercevoir.
            sortie = chemin.with_suffix(chemin.suffix + ".signed")
            if sortie.exists():
                shutil.move(str(sortie), str(chemin))

        Reporter.Success(f"  signe : {chemin.name}")

    return tout_va_bien


def VerifierWindows(fichier: str) -> bool:
    """Relit la signature du fichier produit.

    On ne suppose jamais qu'une signature a ete posee : on la relit. Un
    signtool qui rend 0 sur un fichier verrouille existe.
    """
    outil, genre = TrouverOutilWindows()
    if not outil:
        return False
    if genre == "signtool":
        args = [outil, "verify", "/pa", "/v", fichier]
    else:
        args = [outil, "verify", "-in", fichier]
    resultat = Process.ExecuteCommand(args, captureOutput=True, silent=True)
    return resultat.returnCode == 0


# =============================================================================
#  macOS — codesign, puis notarisation
# =============================================================================
def TrouverOutilMacos() -> Tuple[str, str]:
    """`codesign` sur un vrai Mac, `rcodesign` partout ailleurs."""
    natif = FileSystem.FindExecutable("codesign")
    if natif:
        return natif, "codesign"
    croise = FileSystem.FindExecutable("rcodesign")
    if croise:
        return croise, "rcodesign"
    return "", ""


def SignerMacos(fichiers: Sequence[str], identite: str, entitlements: str = "",
                horodatage: bool = True, runtime_durci: bool = True) -> bool:
    """Signe des exécutables, .dylib ou bundles .app.

    `identite` est le nom du certificat dans le trousseau, par exemple
    « Developer ID Application: Rihen (XXXXXXXXXX) ». Pour distribuer hors de
    l'App Store, ce doit etre un certificat **Developer ID**, pas un
    « Apple Development » : les deux se signent, un seul passe Gatekeeper.
    """
    if not fichiers:
        return True

    outil, genre = TrouverOutilMacos()
    if not outil:
        Reporter.Error(
            "Aucun outil de signature Apple. Sur macOS, installez les outils "
            "en ligne de commande de Xcode ; ailleurs, rcodesign."
        )
        return False
    if not identite:
        Reporter.Error("Aucune identite de signature : macossigningidentity() est vide.")
        return False

    Reporter.Info(f"Signature Apple ({genre}) : {len(fichiers)} element(s)")
    tout_va_bien = True

    for f in fichiers:
        chemin = Path(f)
        if not chemin.exists():
            Reporter.Warning(f"  absent, ignore : {f}")
            continue

        if genre == "codesign":
            args = [outil, "--force", "--sign", identite]
            if horodatage:
                args.append("--timestamp")
            if runtime_durci:
                # Le « hardened runtime » est EXIGE pour la notarisation.
                # Sans lui, la soumission est acceptee puis rejetee, et le
                # message n'arrive que par courriel.
                args += ["--options", "runtime"]
            if entitlements and Path(entitlements).exists():
                args += ["--entitlements", entitlements]
            args.append(str(chemin))
        else:
            args = [outil, "sign"]
            if entitlements and Path(entitlements).exists():
                args += ["--entitlements-xml-path", entitlements]
            args += ["--code-signature-flags", "runtime"] if runtime_durci else []
            args.append(str(chemin))

        if not _Lancer(args):
            tout_va_bien = False
            continue
        Reporter.Success(f"  signe : {chemin.name}")

    return tout_va_bien


def NotariserMacos(archive: str, profil: str) -> bool:
    """Soumet une archive à Apple et agrafe le ticket.

    `profil` est un profil `notarytool` deja enregistre :

        xcrun notarytool store-credentials rihen --apple-id … --team-id … --password …

    La notarisation N'EST PAS une option depuis macOS 10.15 : un binaire signe
    mais non notarise s'ouvre avec « impossible de verifier le developpeur ».
    """
    xcrun = FileSystem.FindExecutable("xcrun")
    if not xcrun:
        Reporter.Error("xcrun introuvable : la notarisation exige un Mac.")
        return False

    Reporter.Info(f"Notarisation de {Path(archive).name} (attente d'Apple)...")
    if not _Lancer([xcrun, "notarytool", "submit", archive,
                    "--keychain-profile", profil, "--wait"]):
        return False

    # Agrafer le ticket : sans cela, l'utilisateur hors ligne voit encore
    # l'avertissement, parce que Gatekeeper ne peut pas interroger Apple.
    return _Lancer([xcrun, "stapler", "staple", archive])


# =============================================================================
#  LINUX — signatures détachées et sommes de contrôle
# =============================================================================
def SignerLinux(fichiers: Sequence[str], cle_gpg: str = "",
                sommes: bool = True, dossier_sortie: str = "") -> bool:
    """Produit `<fichier>.asc` et `SHA256SUMS` a cote des fichiers.

    IL N'Y A PAS DE SIGNATURE DANS UN ELF. Le noyau Linux ne verifie rien au
    lancement, et aucun outil ne le fait a sa place. Ce que le monde Linux
    attend d'un editeur, c'est une signature DETACHEE et des sommes de
    controle publiees a cote du telechargement.

    Les sommes seules ont deja une valeur : elles prouvent que le fichier
    telecharge est celui qui a ete publie. Elles ne prouvent pas QUI l'a
    publie — c'est le role de la signature GPG.
    """
    if not fichiers:
        return True

    presents = [Path(f) for f in fichiers if Path(f).exists()]
    if not presents:
        Reporter.Warning("Aucun fichier a signer.")
        return True

    sortie = Path(dossier_sortie) if dossier_sortie else presents[0].parent
    sortie.mkdir(parents=True, exist_ok=True)
    tout_va_bien = True

    # ── 1. Les sommes de controle ────────────────────────────────────────
    if sommes:
        import hashlib
        lignes = []
        for f in presents:
            h = hashlib.sha256()
            with open(f, "rb") as fd:
                for bloc in iter(lambda: fd.read(1 << 20), b""):
                    h.update(bloc)
            # Format `sha256sum` : empreinte, deux espaces, nom du fichier.
            # Respecte a la lettre pour que `sha256sum -c` fonctionne.
            lignes.append(f"{h.hexdigest()}  {f.name}")
        fichier_sommes = sortie / "SHA256SUMS"
        fichier_sommes.write_text("\n".join(lignes) + "\n", encoding="utf-8")
        Reporter.Success(f"  {fichier_sommes.name} ({len(lignes)} fichier(s))")
        presents_pour_gpg = presents + [fichier_sommes]
    else:
        presents_pour_gpg = presents

    # ── 2. Les signatures detachees ──────────────────────────────────────
    if not cle_gpg:
        Reporter.Info(
            "Aucune cle GPG (linuxgpgkey()) : sommes de controle seules. "
            "Elles prouvent l'integrite, pas l'origine."
        )
        return tout_va_bien

    gpg = FileSystem.FindExecutable("gpg") or FileSystem.FindExecutable("gpg2")
    if not gpg:
        Reporter.Error("gpg introuvable.")
        return False

    passphrase = _Secret("JENGA_GPG_PASSPHRASE", "", "Phrase secrete GPG")
    Reporter.Info(f"Signatures detachees GPG : {len(presents_pour_gpg)} fichier(s)")

    for f in presents_pour_gpg:
        asc = Path(str(f) + ".asc")
        if asc.exists():
            asc.unlink()
        args = [gpg, "--batch", "--yes", "--local-user", cle_gpg,
                "--armor", "--detach-sign", "--output", str(asc), str(f)]
        if passphrase:
            args = [gpg, "--batch", "--yes", "--pinentry-mode", "loopback",
                    "--passphrase", passphrase, "--local-user", cle_gpg,
                    "--armor", "--detach-sign", "--output", str(asc), str(f)]
        if not _Lancer(args, [passphrase]):
            tout_va_bien = False
            continue
        Reporter.Success(f"  signe : {asc.name}")

    return tout_va_bien


# =============================================================================
#  Point d'entrée commun
# =============================================================================
def SignerProjet(projet, fichiers: Sequence[str], systeme: str) -> bool:
    """Signe selon ce que le projet declare, pour le systeme donne.

    Rend True quand la signature n'est pas demandee : ne rien signer n'est pas
    une erreur, c'est le defaut.
    """
    systeme = (systeme or "").lower()

    if systeme in ("windows", "win", "win32", "win64"):
        if not getattr(projet, "windowsSign", False):
            return True
        return SignerWindows(
            fichiers,
            certificat=getattr(projet, "windowsCertificate", ""),
            motdepasse=getattr(projet, "windowsCertificatePass", ""),
            horodatage=getattr(projet, "windowsTimestampUrl", ""),
            nom_affiche=getattr(projet, "targetName", "") or projet.name,
            url=getattr(projet, "appUrl", ""),
        )

    if systeme in ("macos", "osx", "darwin"):
        if not getattr(projet, "macosSign", False):
            return True
        ok = SignerMacos(
            fichiers,
            identite=getattr(projet, "macosSigningIdentity", ""),
            entitlements=getattr(projet, "macosEntitlements", ""),
        )
        profil = getattr(projet, "macosNotaryProfile", "")
        if ok and profil:
            for f in fichiers:
                if Path(f).suffix in (".zip", ".dmg", ".pkg"):
                    ok = NotariserMacos(f, profil) and ok
        return ok

    if systeme in ("linux",):
        if not getattr(projet, "linuxSign", False):
            return True
        return SignerLinux(
            fichiers,
            cle_gpg=getattr(projet, "linuxGpgKey", ""),
            sommes=True,
        )

    return True
