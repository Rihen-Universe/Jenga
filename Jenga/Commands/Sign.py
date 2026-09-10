#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Sign command – Signe un APK Android ou IPA iOS.
Délègue aux builders spécifiques.
"""

import argparse
import sys, os
from pathlib import Path
from typing import List, Optional, Tuple

from ..Utils import Colored, FileSystem
from ..Core.Loader import Loader
from ..Core.Cache import Cache
from ..Core.Platform import Platform
from ..Core import Api


class SignCommand:
    """jenga sign --apk FILE [--keystore KS] [--alias ALIAS] [--storepass PASS] [--keypass PASS]"""

    @staticmethod
    def Execute(args: List[str]) -> int:
        parser = argparse.ArgumentParser(
            prog="jenga sign",
            description="Sign an application: Android APK, iOS IPA, or a desktop "
                        "artifact for Windows, macOS or Linux."
        )
        parser.add_argument("--apk", help="Android APK file to sign")
        parser.add_argument("--ipa", help="iOS IPA file to sign")
        parser.add_argument("--keystore", help="Keystore file (Android)")
        parser.add_argument("--alias", help="Key alias")
        parser.add_argument("--storepass", help="Keystore password")
        parser.add_argument("--keypass", help="Key password")
        parser.add_argument("--project", help="Project name (to get signing config)")
        parser.add_argument("--no-daemon", action="store_true", help="Do not use daemon")
        parser.add_argument("--jenga-file", help="Path to the workspace .jenga file (default: auto-detected)")
        # ── Bureau ───────────────────────────────────────────────────────
        # Les fichiers sont donnes explicitement : une release contient
        # l'executable ET son installeur, et on veut les deux signes.
        parser.add_argument("--file", action="append", default=[],
                            help="Desktop file to sign (repeatable): .exe, .msi, "
                                 ".app, .dylib, or any Linux artifact")
        parser.add_argument("--platform", choices=["windows", "macos", "linux"],
                            help="Desktop platform (default: the host)")
        parser.add_argument("--certificate", help="Windows .pfx, or subject name in the store")
        parser.add_argument("--identity", help="macOS signing identity")
        parser.add_argument("--gpg-key", help="Linux GPG key id, for detached signatures")
        parser.add_argument("--notary-profile", help="macOS notarytool keychain profile")
        parser.add_argument("--timestamp-url", help="Authenticode timestamp server")
        parsed = parser.parse_args(args)

        if not parsed.apk and not parsed.ipa and not parsed.file:
            Colored.PrintError("Specify --apk, --ipa, or --file.")
            return 1

        if parsed.file:
            return SignCommand._SignDesktop(parsed)
        if parsed.apk:
            return SignCommand._SignAndroid(parsed)
        return SignCommand._SignIOS(parsed)

    # -------------------------------------------------------------------------
    @staticmethod
    def _SignDesktop(args) -> int:
        """Signe des artefacts de bureau : Windows, macOS ou Linux.

        Les options de la ligne de commande l'emportent sur ce que le projet
        declare. C'est l'ordre attendu d'un outil : le fichier de projet porte
        la configuration habituelle, la ligne de commande tranche pour ce
        lancement-ci, ce dont un CI a besoin.
        """
        from ..Core import Signing

        systeme = args.platform
        if not systeme:
            hote = Platform.GetHostOS()
            systeme = {
                Api.TargetOS.WINDOWS: "windows",
                Api.TargetOS.MACOS: "macos",
                Api.TargetOS.LINUX: "linux",
            }.get(hote, "")
            if not systeme:
                Colored.PrintError("Unsupported host; pass --platform explicitly.")
                return 1

        projet = SignCommand._ChargerProjet(args)

        def choisir(depuis_ligne, attribut, defaut=""):
            if depuis_ligne:
                return depuis_ligne
            if projet is not None:
                return getattr(projet, attribut, defaut) or defaut
            return defaut

        fichiers = [f for f in args.file]
        manquants = [f for f in fichiers if not Path(f).exists()]
        if manquants:
            # On refuse tot plutot que de signer la moitie du lot : une release
            # a moitie signee est pire qu'une release non signee, parce que
            # personne ne va la verifier fichier par fichier.
            for f in manquants:
                Colored.PrintError(f"File not found: {f}")
            return 1

        if systeme == "windows":
            ok = Signing.SignerWindows(
                fichiers,
                certificat=choisir(args.certificate, "windowsCertificate"),
                motdepasse=choisir(None, "windowsCertificatePass"),
                horodatage=choisir(args.timestamp_url, "windowsTimestampUrl"),
                nom_affiche=(projet.name if projet is not None else ""),
                url=choisir(None, "appUrl"),
            )
            if ok:
                # On relit ce qu'on vient d'ecrire. Une signature posee n'est
                # pas une signature valide, et c'est justement la difference
                # qui compte pour l'utilisateur final.
                echecs = [f for f in fichiers if not Signing.VerifierWindows(f)]
                if echecs:
                    for f in echecs:
                        Colored.PrintError(f"Signed, but verification failed: {f}")
                    Colored.PrintWarning(
                        "La cause la plus frequente est un certificat dont la "
                        "racine n'est pas de confiance sur cette machine : un "
                        "certificat auto-signe se pose parfaitement et ne "
                        "vaudra rien chez l'utilisateur. Seul un certificat "
                        "delivre par une autorite reconnue leve l'alerte de "
                        "Windows."
                    )
                    ok = False
            return 0 if ok else 1

        if systeme == "macos":
            ok = Signing.SignerMacos(
                fichiers,
                identite=choisir(args.identity, "macosSigningIdentity"),
                entitlements=choisir(None, "macosEntitlements"),
            )
            profil = choisir(args.notary_profile, "macosNotaryProfile")
            if ok and profil:
                for f in fichiers:
                    if Path(f).suffix in (".zip", ".dmg", ".pkg"):
                        ok = Signing.NotariserMacos(f, profil) and ok
            return 0 if ok else 1

        ok = Signing.SignerLinux(
            fichiers,
            cle_gpg=choisir(args.gpg_key, "linuxGpgKey"),
            sommes=True,
        )
        return 0 if ok else 1

    # -------------------------------------------------------------------------
    @staticmethod
    def _ChargerProjet(args):
        """Le projet nomme par --project, ou None. Jamais fatal.

        Signer des fichiers sans espace de travail est un usage legitime : on
        signe une release deja construite, parfois sur une autre machine.
        """
        if not args.project:
            return None
        try:
            if args.jenga_file:
                entry = Path(args.jenga_file).resolve()
            else:
                entry = FileSystem.FindWorkspaceEntry(Path.cwd())
            if not entry or not Path(entry).exists():
                return None
            loader = Loader()
            cache = Cache(Path(entry).parent, workspaceName=Path(entry).stem)
            workspace = cache.LoadWorkspace(Path(entry), loader)
            if workspace and args.project in workspace.projects:
                return workspace.projects[args.project]
        except Exception as e:
            Colored.PrintWarning(f"Could not load workspace ({e}); using CLI options only.")
        return None

    @staticmethod
    def _SignAndroid(args) -> int:
        """Signe un APK avec apksigner."""
        # Si un projet est spécifié, charger ses paramètres depuis le workspace
        keystore = args.keystore
        alias = args.alias
        storepass = args.storepass
        keypass = args.keypass

        if args.project:
            # Déterminer le répertoire de travail (workspace root)
            workspace_root = Path.cwd()
            if args.jenga_file:
                entry_file = Path(args.jenga_file).resolve()
                if not entry_file.exists():
                    Colored.PrintError(f"Jenga file not found: {entry_file}")
                    return 1
            else:
                entry_file = FileSystem.FindWorkspaceEntry(workspace_root)
                if not entry_file:
                    Colored.PrintError("No .jenga workspace file found.")
                    return 1
            workspace_root = entry_file.parent
            
            if entry_file:
                loader = Loader()
                cache = Cache(entry_file.parent, workspaceName=entry_file.stem)
                workspace = cache.LoadWorkspace(entry_file, loader)
                if workspace and args.project in workspace.projects:
                    proj = workspace.projects[args.project]
                    keystore = keystore or proj.androidKeystore
                    alias = alias or proj.androidKeyAlias
                    storepass = storepass or proj.androidKeystorePass
                    # keypass = keypass or proj.androidKeyPass? (pas dans l'API actuelle)

        if not keystore or not Path(keystore).exists():
            Colored.PrintError("Keystore not found. Provide --keystore or configure in project.")
            return 1

        # Chercher apksigner dans le SDK Android
        apksigner = SignCommand._FindApksigner()
        if not apksigner:
            Colored.PrintError("apksigner not found. Install Android SDK build-tools.")
            return 1

        cmd = [
            apksigner, "sign",
            "--ks", keystore,
            "--ks-pass", f"pass:{storepass or ''}",
            "--ks-key-alias", alias or "mykey",
            "--out", str(Path(args.apk).with_suffix(".signed.apk")),
            args.apk
        ]
        if keypass:
            cmd.extend(["--key-pass", f"pass:{keypass}"])

        Colored.PrintInfo(f"Signing {args.apk}...")
        import subprocess
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            Colored.PrintSuccess(f"Signed APK created.")
            return 0
        else:
            Colored.PrintError(f"Signing failed: {result.stderr}")
            return 1

    @staticmethod
    def _SignIOS(args) -> int:
        """Signe un IPA avec codesign (nécessite macOS)."""
        if Platform.GetHostOS() != Api.TargetOS.MACOS:
            Colored.PrintError("iOS signing requires macOS.")
            return 1
        # Déléguer à xcodebuild / codesign
        Colored.PrintInfo("iOS signing not yet implemented.")
        return 1

    @staticmethod
    def _FindApksigner() -> str:
        """Localise apksigner dans le SDK Android."""
        # Chercher dans les variables d'environnement
        sdk = os.environ.get("ANDROID_SDK_ROOT") or os.environ.get("ANDROID_HOME")
        if sdk:
            sdk_path = Path(sdk)
            bt_dir = sdk_path / "build-tools"
            if bt_dir.exists():
                versions = sorted([d for d in bt_dir.iterdir() if d.is_dir()], reverse=True)
                for ver in versions:
                    apk = ver / "apksigner"
                    if sys.platform == "win32":
                        apk = apk.with_suffix(".exe")
                    if apk.exists():
                        return str(apk)
        # Fallback: which
        return FileSystem.FindExecutable("apksigner") or ""
