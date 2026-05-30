#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Builder — construit un installateur self-extracting Jenga.

Étapes :
  1. Compile le stub C (Jenga/Tools/Installer/Stub/Installer.c) en binaire natif.
  2. Construit le payload : manifeste (texte) + archive (entrées de fichiers).
  3. Concatène : [stub] + [payload] + [trailer 48 octets] -> installateur final.

Format détaillé : voir DESIGN.md. Aucune dépendance externe (stdlib seulement).

Nomenclature : fonctions/classes en PascalCase ; variables locales en snake_case
(convention Python de Jenga).
"""
from __future__ import annotations

import hashlib
import os
import shutil
import struct
import subprocess
import tempfile
import zlib
from pathlib import Path
from typing import Dict, List, Optional, Tuple

MAGIC = b"JNGINST1"           # 8 octets
TRAILER_SIZE = 80            # 48 (entetes) + 32 (SHA-256 du payload)

# Une entrée de fichier à embarquer : (arcName, cheminAbsolu, modePosix)
FileEntry = Tuple[str, str, int]


class BuilderError(Exception):
    """Erreur de construction de l'installateur."""


# ─────────────────────────────────────────────────────────────────────────────
# Détection / compilation du stub C
# ─────────────────────────────────────────────────────────────────────────────
def DetectCCompiler() -> Optional[List[str]]:
    """Retourne la commande d'un compilateur C disponible, ou None.

    Ordre : cc, clang, gcc (drivers POSIX-like), puis cl (MSVC)."""
    for compiler in ("cc", "clang", "gcc"):
        if shutil.which(compiler):
            return [compiler]
    if shutil.which("cl"):
        return ["cl"]
    return None


def CompileStub(stub_src: Path, out_bin: Path, cc: Optional[List[str]] = None,
                verbose: bool = False, manifest: Optional[Dict[str, str]] = None,
                require_admin: bool = False, icon_path: Optional[str] = None) -> None:
    """Compile le stub C en binaire natif (optimisé, autonome).

    Sur Windows, génère et lie une ressource (VERSIONINFO + manifeste UAC) qui
    réduit les faux positifs antivirus. La ressource est best-effort : si l'outil
    (rc.exe/windres) manque ou échoue, le stub est compilé sans elle."""
    cc = cc or DetectCCompiler()
    if not cc:
        raise BuilderError(
            "Aucun compilateur C trouvé (cc/clang/gcc/cl). "
            "Installe un compilateur C pour générer l'installateur self-extracting."
        )
    out_bin.parent.mkdir(parents=True, exist_ok=True)
    is_cl = cc[0].lower() == "cl"
    on_windows = os.name == "nt"

    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)

        # Ressource Windows (métadonnées éditeur + manifeste UAC). Best-effort.
        resource_obj: Optional[Path] = None
        if on_windows and manifest:
            from .Resource import CompileWindowsResource
            try:
                resource_obj = CompileWindowsResource(
                    td_path, manifest, is_cl=is_cl,
                    require_admin=require_admin, icon_path=icon_path, verbose=verbose)
            except Exception as exc:   # noqa: BLE001 — best-effort, ne bloque pas le build
                if verbose:
                    print(f"  [resource] ignorée: {exc}")
                resource_obj = None

        if is_cl:
            # MSVC : /O2 optimise ; .res passé comme entrée (lié automatiquement).
            # Libs Windows : COM (.lnk via IShellLink), registre (Uninstall), shell.
            head = cc + ["/nologo", "/O2", "/MT", str(stub_src)]
            tail = [f"/Fe:{out_bin}", f"/Fo:{td_path / 'stub.obj'}",
                    "/link", "ole32.lib", "uuid.lib", "shell32.lib", "advapi32.lib"]
            attempts = []
            if resource_obj:
                attempts.append(head + [str(resource_obj)] + tail)
            attempts.append(head + tail)   # repli sans ressource
            _RunFirstThatWorks(attempts, verbose, cwd=td, on_fallback=(
                "  [resource] lien échoué — recompilation sans ressource." if resource_obj else None))
        else:
            # gcc/clang/cc : -O2, -s (strip) pour un stub compact. Sur Windows,
            # lier ole32/uuid/shell32/advapi32 (raccourcis COM + registre).
            win_libs = ["-lole32", "-luuid", "-lshell32", "-ladvapi32"] if on_windows else []
            res = [str(resource_obj)] if resource_obj else []
            attempts = [
                cc + ["-O2", "-s", str(stub_src)] + res + ["-o", str(out_bin)] + win_libs,
                cc + ["-O2", str(stub_src)] + res + ["-o", str(out_bin)] + win_libs,
            ]
            if res:
                # Dernier recours : sans ressource (ex. .res non liable par gcc).
                attempts.append(cc + ["-O2", str(stub_src), "-o", str(out_bin)] + win_libs)
            _RunFirstThatWorks(attempts, verbose, on_fallback=(
                "  [resource] lien échoué — recompilation sans ressource." if res else None))

    if not out_bin.exists():
        raise BuilderError(f"La compilation du stub n'a produit aucun binaire : {out_bin}")


def _Run(cmd: List[str], verbose: bool, cwd: Optional[str] = None) -> None:
    if verbose:
        print("  $", " ".join(cmd))
    proc = subprocess.run(cmd, cwd=cwd, capture_output=not verbose, text=True)
    if proc.returncode != 0:
        msg = (proc.stderr or proc.stdout or "").strip() if not verbose else ""
        raise BuilderError(f"Échec compilation stub (code {proc.returncode}).\n{msg}")


def _RunFirstThatWorks(attempts: List[List[str]], verbose: bool,
                       cwd: Optional[str] = None, on_fallback: Optional[str] = None) -> None:
    """Tente chaque commande dans l'ordre ; s'arrête à la première qui réussit.
    Lève la dernière erreur si toutes échouent."""
    last_err: Optional[BuilderError] = None
    for index, cmd in enumerate(attempts):
        try:
            _Run(cmd, verbose, cwd=cwd)
            return
        except BuilderError as exc:
            last_err = exc
            if index == 0 and on_fallback and verbose:
                print(on_fallback)
    if last_err:
        raise last_err


# ─────────────────────────────────────────────────────────────────────────────
# Manifeste + payload
# ─────────────────────────────────────────────────────────────────────────────
def RenderManifest(manifest: Dict[str, str]) -> str:
    """Rend le manifeste au format `cle=valeur` (une paire par ligne).

    Les valeurs multi-lignes ne sont pas autorisées (une commande firewall tient
    sur une ligne). Les clés à valeur vide sont omises."""
    lines = []
    for key, value in manifest.items():
        if value is None:
            continue
        value = str(value).replace("\n", " ").replace("\r", " ")
        if value == "":
            continue
        lines.append(f"{key}={value}")
    return "\n".join(lines) + "\n"


def _BuildArchive(files: List[FileEntry]) -> Tuple[bytes, int]:
    """Construit l'archive binaire. Retourne (octets, nombre_d_entrees)."""
    buf = bytearray()
    count = 0
    for arc_name, abs_path, mode in files:
        path = Path(abs_path)
        if not path.is_file():
            raise BuilderError(f"Fichier introuvable pour l'archive : {abs_path}")
        data = path.read_bytes()
        name_bytes = arc_name.replace("\\", "/").encode("utf-8")
        buf += struct.pack("<I", len(name_bytes))
        buf += name_bytes
        buf += struct.pack("<I", int(mode) & 0xFFFFFFFF)
        buf += struct.pack("<Q", len(data))
        buf += data
        count += 1
    return bytes(buf), count


# ─────────────────────────────────────────────────────────────────────────────
# Construction de l'installateur
# ─────────────────────────────────────────────────────────────────────────────
def BuildInstaller(files: List[FileEntry],
                   manifest: Dict[str, str],
                   output: Path,
                   stub_src: Optional[Path] = None,
                   cc: Optional[List[str]] = None,
                   verbose: bool = False,
                   platform: Optional[str] = None,
                   require_admin: bool = False,
                   icon_path: Optional[str] = None,
                   sign_options: Optional[Dict[str, str]] = None) -> Path:
    """
    Construit un installateur self-extracting.

    files        : liste de (arcName, cheminAbsolu, modePosix). `arcName` est le
                   chemin relatif dans le dossier d'installation final.
    manifest     : métadonnées (name, version, publisher, default_dir_*, exe,
                   firewall_add/firewall_del, ...).
    output       : chemin de l'installateur à produire.
    platform     : plateforme cible (windows/linux/macos) ; défaut = OS courant.
    require_admin: manifeste UAC `requireAdministrator` (sinon `asInvoker`).
    icon_path    : icône à embarquer dans le stub Windows (optionnel).
    sign_options : infos de signature de code (cf. Signing.SignBinary) ; sans
                   certificat, l'installateur est produit mais non signé.
    Retourne le chemin de l'installateur.
    """
    output = Path(output)
    platform = (platform or _CurrentPlatform()).lower()
    stub_src = Path(stub_src) if stub_src else (Path(__file__).parent / "Stub" / "Installer.c")
    if not stub_src.is_file():
        raise BuilderError(f"Source du stub introuvable : {stub_src}")

    # 1. Compiler le stub dans un emplacement temporaire (avec ressource Windows).
    with tempfile.TemporaryDirectory() as td:
        stub_bin = Path(td) / ("stub.exe" if os.name == "nt" else "stub")
        CompileStub(stub_src, stub_bin, cc=cc, verbose=verbose,
                    manifest=manifest, require_admin=require_admin, icon_path=icon_path)
        stub_bytes = stub_bin.read_bytes()

    # 2. Manifeste + archive.
    manifest_bytes = RenderManifest(manifest).encode("utf-8")
    archive_bytes, entry_count = _BuildArchive(files)

    # 3. Offsets ABSOLUS dans le fichier final (le payload suit le stub).
    manifest_off = len(stub_bytes)
    archive_off = manifest_off + len(manifest_bytes)
    payload = manifest_bytes + archive_bytes
    crc = zlib.crc32(payload) & 0xFFFFFFFF
    # SHA-256 du payload : vérifié par le stub avant extraction (anti-tampering).
    sha256 = hashlib.sha256(payload).digest()    # 32 octets

    # 4. Trailer 80 octets : magic(8) + 4×u64 + crc(u32) + reserved(u32) + sha256(32).
    trailer = (MAGIC
               + struct.pack("<QQQQ", manifest_off, len(manifest_bytes), archive_off, entry_count)
               + struct.pack("<II", crc, 0)
               + sha256)
    assert len(trailer) == TRAILER_SIZE, f"trailer={len(trailer)}"

    # 5. Écriture : stub + payload + trailer.
    output.parent.mkdir(parents=True, exist_ok=True)
    with open(output, "wb") as f:
        f.write(stub_bytes)
        f.write(payload)
        f.write(trailer)

    # 6. Exécutable sur Unix.
    if os.name != "nt":
        import stat as _stat
        output.chmod(output.stat().st_mode | _stat.S_IEXEC | _stat.S_IXGRP | _stat.S_IXOTH)

    # 7. Signature de code (anti-faux-positifs AV) — uniquement si certificat fourni.
    from .Signing import SignBinary, HasSigningInfo, SigningError
    if HasSigningInfo(sign_options):
        try:
            result = SignBinary(output, sign_options, platform, verbose=verbose)
            if verbose or not result.signed:
                print(f"  [sign] {result.message}")
        except SigningError as exc:
            # La signature ne doit pas détruire un installateur déjà produit :
            # on prévient mais on conserve le binaire non signé.
            print(f"  [sign] AVERTISSEMENT : signature échouée — {exc}")

    return output


def _CurrentPlatform() -> str:
    """Plateforme de l'OS courant : windows / macos / linux."""
    import sys
    if sys.platform.startswith("win"):
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    return "linux"
