#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_examples_archive.py — Construit l'archive d'exemples ALLEGEE.

Produit, dans le dossier de sortie (defaut: <repo>/dist) :
    jenga-examples-<version>.zip
    jenga-examples-<version>.tar.gz

Contenu : TOUS les exemples de Jenga/Exemples MAIS sans les dossiers de build
ni les externals lourds ni les binaires generes. C'est la source unique de
verite des exclusions, reutilisee par cri.bat, cri.sh et
.github/workflows/release.yml — pour que le local et le CI produisent
exactement la meme archive.

Usage :
    python scripts/build_examples_archive.py [OUTDIR]

L'archive est ce que `jenga examples copy <id>` telecharge a la demande pour
les exemples absents du wheel.
"""
from __future__ import annotations
import fnmatch
import os
import re
import sys
import tarfile
import tempfile
import shutil
import zipfile
from pathlib import Path

# --- Dossiers exclus (compares par nom, a tout niveau) ----------------------
EXCLUDE_DIRS = {
    "build", "Build", "out", "bin", "obj",
    "CMakeFiles", ".cmake",
    "Externals", "External", "externals",
    "third_party", "ThirdParty", "vendor", "node_modules",
    ".git", ".github", ".vs", ".idea", ".vscode",
    "__pycache__", ".jenga_cache",
}
# --- Dossiers exclus par motif (glob sur le nom) ----------------------------
EXCLUDE_DIR_GLOBS = ["cmake-build-*", "*.app", "*.egg-info"]
# --- Extensions de fichiers exclues -----------------------------------------
# Binaires generes + gros assets (textures, modeles 3D, audio, video, docs,
# archives). On garde le CODE : sources, headers, .jenga, README, shaders,
# json/txt/yaml, fonts. But : une archive "code" legere, pas les ressources.
EXCLUDE_EXT = {
    # binaires de build / compilation
    ".o", ".obj", ".a", ".so", ".dll", ".dylib", ".lib", ".pdb", ".ilk",
    ".exp", ".wasm", ".apk", ".aab", ".ipa", ".hap", ".exe",
    ".pyc", ".jenga_sig",
    # images / textures
    ".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tga", ".dds", ".ktx",
    ".ktx2", ".exr", ".hdr", ".psd", ".tif", ".tiff", ".webp", ".ico", ".icns",
    # modeles 3D
    ".fbx", ".glb", ".gltf", ".dae", ".obj", ".mtl", ".stl", ".ply",
    ".3ds", ".blend",
    # audio / video
    ".mp3", ".wav", ".ogg", ".flac", ".aac", ".m4a",
    ".mp4", ".avi", ".mov", ".mkv", ".webm",
    # documents / archives
    ".pdf",
    ".zip", ".7z", ".rar", ".tar", ".tgz", ".gz", ".bz2", ".xz",
}


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _read_version(root: Path) -> str:
    # Source unique de vérité : Jenga/_version.py. Fallback __init__.py au cas
    # où (ancienne disposition).
    for rel in ("Jenga/_version.py", "Jenga/__init__.py"):
        path = root / rel
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        m = re.search(r"__version__\s*=\s*[\"']([^\"']+)", text)
        if m:
            return m.group(1)
    return "latest"


def _skip_dir(name: str) -> bool:
    if name in EXCLUDE_DIRS:
        return True
    return any(fnmatch.fnmatch(name, g) for g in EXCLUDE_DIR_GLOBS)


def _skip_file(name: str) -> bool:
    # Suffixe compose (ex .so.1) ou extension simple
    if any(name.endswith(ext) for ext in EXCLUDE_EXT):
        return True
    return bool(re.search(r"\.so(\.\d+)+$", name))


def _stage_examples(src: Path, stage_root: Path) -> int:
    """Copie filtree de src -> stage_root/jenga-examples. Retourne le nb de fichiers."""
    dst_root = stage_root / "jenga-examples"
    count = 0
    for dirpath, dirnames, filenames in os.walk(src):
        # Elagage des dossiers exclus (modifie dirnames in-place).
        dirnames[:] = [d for d in dirnames if not _skip_dir(d)]
        rel = Path(dirpath).relative_to(src)
        for fn in filenames:
            if _skip_file(fn):
                continue
            target_dir = dst_root / rel
            target_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(Path(dirpath) / fn, target_dir / fn)
            count += 1
    return count


def main() -> int:
    root = _repo_root()
    src = root / "Jenga" / "Exemples"
    if not src.is_dir():
        print(f"[ERREUR] Dossier d'exemples introuvable : {src}", file=sys.stderr)
        return 1

    outdir = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else (root / "dist")
    outdir.mkdir(parents=True, exist_ok=True)
    version = _read_version(root)

    with tempfile.TemporaryDirectory() as tmp:
        stage = Path(tmp)
        n = _stage_examples(src, stage)
        base = stage / "jenga-examples"

        zip_path = outdir / f"jenga-examples-{version}.zip"
        tar_path = outdir / f"jenga-examples-{version}.tar.gz"

        # ZIP
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for f in base.rglob("*"):
                if f.is_file():
                    zf.write(f, f.relative_to(stage))
        # TAR.GZ
        with tarfile.open(tar_path, "w:gz") as tf:
            tf.add(base, arcname="jenga-examples")

    zmb = zip_path.stat().st_size / 1e6
    tmb = tar_path.stat().st_size / 1e6
    print(f"[OK] Archive d'exemples allegee ({n} fichiers, version {version}) :")
    print(f"     {zip_path}  ({zmb:.1f} Mo)")
    print(f"     {tar_path}  ({tmb:.1f} Mo)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
