#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Resource — métadonnées Windows du stub installateur (anti-faux-positifs AV).

Génère et compile une ressource Windows liée au stub :
  * VERSIONINFO : éditeur (Rihen), version, description, copyright. Un exécutable
    « identifié » est nettement moins suspect pour les antivirus/SmartScreen.
  * Manifeste UAC : `asInvoker` par défaut (pas d'élévation inutile), ou
    `requireAdministrator` si l'installation l'exige (firewall, all-users).

La ressource est best-effort : si aucun compilateur de ressources n'est trouvé
(rc.exe / windres), la compilation du stub continue SANS ressource (avec un
avertissement). L'installateur reste fonctionnel.

Nomenclature : fonctions/classes en PascalCase ; variables locales en snake_case.
"""
from __future__ import annotations

import glob
import os
import shutil
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# GUID supportedOS (compatibility manifest) : Win7 → Win10/11.
_SUPPORTED_OS_GUIDS = (
    "{8e0f7a12-bfb3-4fe8-b9a5-48fd50a15a9a}",  # Windows 10 / 11
    "{1f676c76-80e1-4239-95bb-83d0f6d0da78}",  # Windows 8.1
    "{4a2f28e3-53b9-4441-ba9c-d69d4a4a6e38}",  # Windows 8
    "{35138b9a-5d96-4fbd-8e2d-a2440225f93a}",  # Windows 7
)


class ResourceError(Exception):
    """Erreur de génération/compilation de la ressource Windows."""


def _ParseVersionQuad(version: str) -> Tuple[int, int, int, int]:
    """Convertit "2.0.3" → (2, 0, 3, 0). Tolérant aux suffixes ("2.0.3-rc1")."""
    parts: List[int] = []
    for chunk in str(version).replace("-", ".").replace("+", ".").split("."):
        digits = "".join(ch for ch in chunk if ch.isdigit())
        if digits == "":
            break
        parts.append(int(digits))
        if len(parts) == 4:
            break
    while len(parts) < 4:
        parts.append(0)
    return parts[0], parts[1], parts[2], parts[3]


def _EscapeRcString(value: str) -> str:
    """Échappe une chaîne pour un littéral .rc (guillemets doublés)."""
    return str(value).replace('"', '""')


def RenderUacManifest(name: str, version: str, publisher: str,
                      require_admin: bool = False) -> str:
    """Rend le manifeste d'application Windows (UAC + compatibilité OS + DPI).

    `require_admin=False` → `asInvoker` (défaut, recommandé anti-faux-positifs)."""
    major, minor, patch, build = _ParseVersionQuad(version)
    level = "requireAdministrator" if require_admin else "asInvoker"
    # Identité d'assembly : <Publisher>.<Name>.Installer (sans espaces).
    identity_publisher = "".join(ch for ch in publisher if ch.isalnum()) or "Rihen"
    identity_name = "".join(ch for ch in name if ch.isalnum()) or "App"
    supported = "\n".join(
        f'      <supportedOS Id="{guid}"/>' for guid in _SUPPORTED_OS_GUIDS
    )
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<assembly xmlns="urn:schemas-microsoft-com:asm.v1" manifestVersion="1.0">
  <assemblyIdentity version="{major}.{minor}.{patch}.{build}" processorArchitecture="*" name="{identity_publisher}.{identity_name}.Installer" type="win32"/>
  <trustInfo xmlns="urn:schemas-microsoft-com:asm.v3">
    <security>
      <requestedPrivileges>
        <requestedExecutionLevel level="{level}" uiAccess="false"/>
      </requestedPrivileges>
    </security>
  </trustInfo>
  <compatibility xmlns="urn:schemas-microsoft-com:compatibility.v1">
    <application>
{supported}
    </application>
  </compatibility>
  <application xmlns="urn:schemas-microsoft-com:asm.v3">
    <windowsSettings>
      <dpiAware xmlns="http://schemas.microsoft.com/SMI/2005/WindowsSettings">true</dpiAware>
    </windowsSettings>
  </application>
</assembly>
"""


def RenderVersionInfoRc(manifest: Dict[str, str], manifest_filename: str,
                        icon_path: Optional[str] = None,
                        copyright_year: Optional[int] = None) -> str:
    """Rend le fichier .rc : VERSIONINFO + (optionnel) icône + manifeste RT_MANIFEST.

    `manifest_filename` est le nom du fichier manifeste embarqué (RT_MANIFEST=24).
    `icon_path` (si fourni) ajoute l'icône principale de l'exécutable."""
    name = manifest.get("name", "App")
    version = manifest.get("version", "1.0.0")
    publisher = manifest.get("publisher", "Rihen")
    exe = manifest.get("exe", f"{name}.exe")
    major, minor, patch, build = _ParseVersionQuad(version)
    version_str = f"{major}.{minor}.{patch}.{build}"
    if copyright_year is None:
        import datetime
        copyright_year = datetime.date.today().year
    desc = f"{name} Installer"
    original = f"{name}-setup.exe"

    lines: List[str] = []
    lines.append("#include <winver.h>")
    lines.append("")
    if icon_path:
        # ICON id 1 : l'icône de l'application (chemins en `\\` pour le .rc).
        rc_icon = str(icon_path).replace("\\", "\\\\")
        lines.append(f'1 ICON "{rc_icon}"')
        lines.append("")
    lines.append("1 VERSIONINFO")
    lines.append(f"FILEVERSION {major},{minor},{patch},{build}")
    lines.append(f"PRODUCTVERSION {major},{minor},{patch},{build}")
    lines.append("FILEOS VOS__WINDOWS32")
    lines.append("FILETYPE VFT_APP")
    lines.append("{")
    lines.append('  BLOCK "StringFileInfo"')
    lines.append("  {")
    lines.append('    BLOCK "040904B0"')   # US English (0x0409) + Unicode (1200)
    lines.append("    {")
    lines.append(f'      VALUE "CompanyName", "{_EscapeRcString(publisher)}"')
    lines.append(f'      VALUE "FileDescription", "{_EscapeRcString(desc)}"')
    lines.append(f'      VALUE "FileVersion", "{version_str}"')
    lines.append(f'      VALUE "ProductName", "{_EscapeRcString(name)}"')
    lines.append(f'      VALUE "ProductVersion", "{version_str}"')
    lines.append(f'      VALUE "LegalCopyright", "Copyright (C) {copyright_year} {_EscapeRcString(publisher)}"')
    lines.append(f'      VALUE "OriginalFilename", "{_EscapeRcString(original)}"')
    lines.append(f'      VALUE "InternalName", "{_EscapeRcString(name)}-setup"')
    lines.append("    }")
    lines.append("  }")
    lines.append('  BLOCK "VarFileInfo"')
    lines.append("  {")
    lines.append('    VALUE "Translation", 0x409, 1200')
    lines.append("  }")
    lines.append("}")
    lines.append("")
    # RT_MANIFEST (24) id 1 : manifeste UAC/compatibilité/DPI.
    rc_manifest = str(manifest_filename).replace("\\", "\\\\")
    lines.append(f'1 24 "{rc_manifest}"')
    lines.append("")
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# Détection des compilateurs de ressources
# ─────────────────────────────────────────────────────────────────────────────
def DetectRcExe() -> Optional[str]:
    """Localise `rc.exe` (Windows SDK) : PATH d'abord, puis Windows Kits."""
    found = shutil.which("rc")
    if found:
        return found
    roots = [
        os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
        os.environ.get("ProgramFiles", r"C:\Program Files"),
    ]
    candidates: List[str] = []
    for root in roots:
        pattern = os.path.join(root, "Windows Kits", "10", "bin", "*", "x64", "rc.exe")
        candidates.extend(glob.glob(pattern))
        pattern_x86 = os.path.join(root, "Windows Kits", "10", "bin", "*", "x86", "rc.exe")
        candidates.extend(glob.glob(pattern_x86))
    if candidates:
        # La version la plus récente (tri lexicographique des dossiers SDK).
        candidates.sort()
        return candidates[-1]
    return None


def DetectWindres() -> Optional[str]:
    """Localise `windres` (MinGW) ; à défaut `llvm-rc`."""
    return shutil.which("windres") or shutil.which("llvm-rc")


# ─────────────────────────────────────────────────────────────────────────────
# Compilation de la ressource → objet liable au stub
# ─────────────────────────────────────────────────────────────────────────────
def CompileWindowsResource(out_dir: Path,
                           manifest: Dict[str, str],
                           is_cl: bool,
                           require_admin: bool = False,
                           icon_path: Optional[str] = None,
                           verbose: bool = False) -> Optional[Path]:
    """Génère .rc + .manifest puis compile la ressource.

    Retourne le chemin de l'objet à lier (.res pour MSVC, .o pour MinGW), ou
    None si aucun compilateur de ressources n'est disponible (best-effort)."""
    out_dir = Path(out_dir)
    manifest_name = "Stub.manifest"
    rc_path = out_dir / "Stub.rc"
    manifest_path = out_dir / manifest_name

    manifest_path.write_text(
        RenderUacManifest(
            name=manifest.get("name", "App"),
            version=manifest.get("version", "1.0.0"),
            publisher=manifest.get("publisher", "Rihen"),
            require_admin=require_admin,
        ),
        encoding="utf-8",
    )
    rc_path.write_text(
        RenderVersionInfoRc(manifest, manifest_name, icon_path=icon_path),
        encoding="utf-8",
    )

    if is_cl:
        rc_exe = DetectRcExe()
        if not rc_exe:
            if verbose:
                print("  [resource] rc.exe introuvable — stub compilé sans VERSIONINFO/manifeste.")
            return None
        res_path = out_dir / "Stub.res"
        cmd = [rc_exe, "/nologo", "/fo", str(res_path), str(rc_path)]
        if _RunResource(cmd, verbose, cwd=str(out_dir)) and res_path.exists():
            return res_path
        return None

    windres = DetectWindres()
    if not windres:
        if verbose:
            print("  [resource] windres/llvm-rc introuvable — stub compilé sans VERSIONINFO/manifeste.")
        return None
    is_llvm_rc = Path(windres).stem.lower() == "llvm-rc"
    if is_llvm_rc:
        # llvm-rc produit un .res (liable par lld) — pas un .o GCC.
        res_path = out_dir / "Stub.res"
        cmd = [windres, f"/fo", str(res_path), str(rc_path)]
        if _RunResource(cmd, verbose, cwd=str(out_dir)) and res_path.exists():
            return res_path
        return None
    obj_path = out_dir / "Stub_res.o"
    cmd = [windres, "-O", "coff", "-i", str(rc_path), "-o", str(obj_path)]
    if _RunResource(cmd, verbose, cwd=str(out_dir)) and obj_path.exists():
        return obj_path
    return None


def _RunResource(cmd: List[str], verbose: bool, cwd: Optional[str] = None) -> bool:
    """Exécute le compilateur de ressources. Best-effort : retourne False sans
    lever en cas d'échec (le stub sera compilé sans ressource)."""
    if verbose:
        print("  $", " ".join(cmd))
    try:
        proc = subprocess.run(cmd, cwd=cwd, capture_output=not verbose, text=True)
    except OSError as exc:
        if verbose:
            print(f"  [resource] échec lancement: {exc}")
        return False
    if proc.returncode != 0:
        if verbose:
            msg = (proc.stderr or proc.stdout or "").strip()
            print(f"  [resource] compilation échouée (code {proc.returncode}). {msg}")
        return False
    return True
