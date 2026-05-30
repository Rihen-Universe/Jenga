#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Signing — signature de code de l'installateur final (anti-faux-positifs AV).

La signature de code est le levier décisif contre les alertes SmartScreen et
antivirus (cf. DESIGN.md §9). Ce module signe le binaire produit par le Builder
via les outils natifs, *uniquement si un certificat/identité est fourni* :

  * Windows : `signtool` (Authenticode), certificat .pfx ou empreinte du store.
  * macOS   : `codesign` (+ option `--timestamp`, durcissement runtime).
  * Linux   : signature détachée GPG (`.sig`), facultative.

Sans information de signature → opération ignorée proprement (pas une erreur) :
l'installateur reste valide, simplement non signé.

Nomenclature : fonctions/classes en PascalCase ; variables locales en snake_case.
"""
from __future__ import annotations

import glob
import os
import shutil
import subprocess
from pathlib import Path
from typing import Dict, List, Optional

DEFAULT_TIMESTAMP_URL = "http://timestamp.digicert.com"


class SigningError(Exception):
    """Erreur lors de la signature du binaire."""


class SignResult:
    """Issue d'une tentative de signature."""

    def __init__(self, signed: bool, message: str):
        self.signed = signed
        self.message = message

    def __bool__(self) -> bool:
        return self.signed


# ─────────────────────────────────────────────────────────────────────────────
# Détection des outils
# ─────────────────────────────────────────────────────────────────────────────
def DetectSigntool() -> Optional[str]:
    """Localise `signtool.exe` : PATH d'abord, puis Windows Kits."""
    found = shutil.which("signtool")
    if found:
        return found
    roots = [
        os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
        os.environ.get("ProgramFiles", r"C:\Program Files"),
    ]
    candidates: List[str] = []
    for root in roots:
        for arch in ("x64", "x86"):
            pattern = os.path.join(root, "Windows Kits", "10", "bin", "*", arch, "signtool.exe")
            candidates.extend(glob.glob(pattern))
    if candidates:
        candidates.sort()
        return candidates[-1]
    return None


def HasSigningInfo(sign_options: Optional[Dict[str, str]]) -> bool:
    """Indique si `sign_options` contient de quoi signer sur la plateforme."""
    if not sign_options:
        return False
    keys = ("cert_file", "cert_thumbprint", "identity", "gpg_key", "enabled")
    return any(sign_options.get(k) for k in keys)


# ─────────────────────────────────────────────────────────────────────────────
# Signature par plateforme
# ─────────────────────────────────────────────────────────────────────────────
def SignBinary(binary_path: Path,
               sign_options: Optional[Dict[str, str]],
               platform: str,
               verbose: bool = False) -> SignResult:
    """Signe `binary_path` selon la plateforme cible.

    `sign_options` (toutes les clés sont optionnelles) :
      Windows : cert_file + cert_password | cert_thumbprint ; timestamp_url.
      macOS   : identity (ex. "Developer ID Application: Rihen (TEAMID)") ;
                timestamp (bool) ; hardened_runtime (bool).
      Linux   : gpg_key (id/empreinte) → produit `<binary>.sig`.
    Sans info de signature → SignResult(False, ...) sans erreur."""
    binary_path = Path(binary_path)
    if not HasSigningInfo(sign_options):
        return SignResult(False, "Aucun certificat fourni — installateur non signé.")
    assert sign_options is not None  # garanti par HasSigningInfo

    plat = (platform or "").lower()
    if plat.startswith("win"):
        return _SignWindows(binary_path, sign_options, verbose)
    if plat in ("macos", "osx", "darwin", "ios"):
        return _SignMacos(binary_path, sign_options, verbose)
    return _SignLinux(binary_path, sign_options, verbose)


def _SignWindows(binary_path: Path, opts: Dict[str, str], verbose: bool) -> SignResult:
    signtool = DetectSigntool()
    if not signtool:
        raise SigningError(
            "signtool introuvable (Windows SDK requis pour signer). "
            "Installe le Windows SDK ou ajoute signtool.exe au PATH."
        )
    timestamp_url = opts.get("timestamp_url") or DEFAULT_TIMESTAMP_URL
    cmd: List[str] = [signtool, "sign", "/fd", "SHA256",
                      "/tr", timestamp_url, "/td", "SHA256"]
    if opts.get("cert_thumbprint"):
        # Certificat du magasin Windows (CurrentUser\My par défaut).
        cmd += ["/sha1", str(opts["cert_thumbprint"])]
    elif opts.get("cert_file"):
        cmd += ["/f", str(opts["cert_file"])]
        if opts.get("cert_password"):
            cmd += ["/p", str(opts["cert_password"])]
    else:
        return SignResult(False, "Signature Windows : ni cert_file ni cert_thumbprint.")
    if opts.get("description"):
        cmd += ["/d", str(opts["description"])]
    cmd.append(str(binary_path))
    _RunSign(cmd, verbose, secret_args={opts.get("cert_password")})
    return SignResult(True, "Installateur signé (Authenticode SHA-256 + timestamp).")


def _SignMacos(binary_path: Path, opts: Dict[str, str], verbose: bool) -> SignResult:
    codesign = shutil.which("codesign")
    if not codesign:
        raise SigningError("codesign introuvable (Xcode Command Line Tools requis).")
    identity = opts.get("identity")
    if not identity:
        return SignResult(False, "Signature macOS : 'identity' manquante.")
    cmd: List[str] = [codesign, "--force", "--sign", str(identity)]
    if str(opts.get("hardened_runtime", "1")) not in ("0", "false", "False", ""):
        cmd += ["--options", "runtime"]
    if str(opts.get("timestamp", "1")) not in ("0", "false", "False", ""):
        cmd.append("--timestamp")
    if opts.get("entitlements"):
        cmd += ["--entitlements", str(opts["entitlements"])]
    cmd.append(str(binary_path))
    _RunSign(cmd, verbose)
    return SignResult(True, f"Installateur signé (codesign : {identity}).")


def _SignLinux(binary_path: Path, opts: Dict[str, str], verbose: bool) -> SignResult:
    gpg_key = opts.get("gpg_key")
    if not gpg_key:
        return SignResult(False, "Signature Linux : 'gpg_key' manquante (skip).")
    gpg = shutil.which("gpg")
    if not gpg:
        raise SigningError("gpg introuvable (signature détachée Linux indisponible).")
    sig_path = binary_path.with_suffix(binary_path.suffix + ".sig")
    cmd = [gpg, "--batch", "--yes", "--local-user", str(gpg_key),
           "--output", str(sig_path), "--detach-sign", str(binary_path)]
    _RunSign(cmd, verbose)
    return SignResult(True, f"Signature détachée GPG produite : {sig_path.name}.")


def _RunSign(cmd: List[str], verbose: bool, secret_args: Optional[set] = None) -> None:
    """Exécute l'outil de signature. Masque les secrets dans les logs."""
    if verbose:
        secret_args = {s for s in (secret_args or set()) if s}
        shown = ["***" if (secret_args and a in secret_args) else a for a in cmd]
        print("  $", " ".join(shown))
    proc = subprocess.run(cmd, capture_output=not verbose, text=True)
    if proc.returncode != 0:
        msg = (proc.stderr or proc.stdout or "").strip() if not verbose else ""
        raise SigningError(f"Échec signature (code {proc.returncode}).\n{msg}")
