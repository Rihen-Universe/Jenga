#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_linux_sysroot.py — Construit un sysroot Linux (x86_64) pour cross-compiler
avec Zig depuis Windows/macOS, SANS WSL ni docker.

Pourquoi : zig fournit déjà glibc/musl (le CLI Linux se compile sans rien). Mais
pour une app GUI (X11 / XCB / Wayland / OpenGL / EGL), il faut les en-têtes et
les .so de dev de la distro. Ce script les récupère depuis les paquets Debian
« bullseye » et les extrait dans un dossier sysroot utilisable via :

    zig cc -target x86_64-linux-gnu --sysroot <OUT> -isystem <OUT>/usr/include ...

Usage :
    python build_linux_sysroot.py [--out DIR] [--add pkg1,pkg2]

Par défaut : --out = <repo>/sysroot/linux-x86_64

100 % stdlib (urllib + tarfile + lzma). Extraction des .deb (format `ar`) faite
à la main. Les paquets sont en .tar.xz sous bullseye (géré par lzma) — si un
paquet passe en .tar.zst, le script le signale (installer 'zstandard' ou choisir
une release plus ancienne).

NOTE : la liste PACKAGES couvre X11/GL/XCB/Wayland. Si l'éditeur de liens se
plaint d'un .so/-dev manquant, ajoute le paquet avec --add et relance.
"""

import argparse
import gzip
import io
import lzma
import os
import sys
import tarfile
import urllib.request

MIRROR = "http://deb.debian.org/debian"
DIST = "bullseye"
ARCH = "amd64"

# Paquets de dev + runtime (.so) pour une app GUI Linux typique (X11 + GL +
# XCB + Wayland). On N'inclut PAS libc6 : zig fournit sa propre libc, et les .so
# ici ne référencent la libc qu'au chargement (résolu sur la cible), pas au link.
PACKAGES = [
    # Protocoles / base X11
    "x11proto-dev", "xtrans-dev",
    "libxau-dev", "libxau6",
    "libxdmcp-dev", "libxdmcp6",
    "libxcb1-dev", "libxcb1",
    "libx11-dev", "libx11-6", "libx11-data",
    "libxext-dev", "libxext6",
    "libxrandr-dev", "libxrandr2",
    "libxrender-dev", "libxrender1",
    "libxi-dev", "libxi6",
    "libxfixes-dev", "libxfixes3",
    "libxcursor-dev", "libxcursor1",
    # Clavier
    "libxkbcommon-dev", "libxkbcommon0",
    # Wayland
    "libwayland-dev", "libwayland-client0", "libwayland-cursor0",
    "libwayland-egl1", "libwayland-server0",
    # OpenGL / EGL (libglvnd + mesa)
    "libglvnd-dev", "libglvnd0",
    "libgl-dev", "libgl1",
    "libglx-dev", "libglx0",
    "libegl-dev", "libegl1",
    "libopengl0",
    "libgl1-mesa-dev", "libglx-mesa0", "libegl-mesa0", "mesa-common-dev",
    "libgles-dev", "libgles2",
    # deps mesa/drm
    "libdrm-dev", "libdrm2",
    "libexpat1-dev", "libexpat1",
    "libffi-dev", "libffi7",
]


def fetch(url: str) -> bytes:
    print(f"  GET {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "jenga-sysroot/1.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def load_packages_index() -> dict:
    """Télécharge et parse Packages.gz -> {pkg: {'Filename':..., ...}}."""
    url = f"{MIRROR}/dists/{DIST}/main/binary-{ARCH}/Packages.gz"
    raw = gzip.decompress(fetch(url)).decode("utf-8", "replace")
    index, cur = {}, {}
    for line in raw.split("\n"):
        if not line.strip():
            if cur.get("Package"):
                index[cur["Package"]] = cur
            cur = {}
            continue
        if line[0] in " \t":
            continue  # continuation (description) : ignorée
        if ":" in line:
            k, v = line.split(":", 1)
            cur[k.strip()] = v.strip()
    if cur.get("Package"):
        index[cur["Package"]] = cur
    return index


def ar_members(data: bytes):
    """Itère les membres d'une archive `ar` (format .deb) : (name, bytes)."""
    if data[:8] != b"!<arch>\n":
        raise ValueError("pas une archive ar (.deb invalide)")
    off = 8
    while off + 60 <= len(data):
        header = data[off:off + 60]
        name = header[0:16].decode("ascii", "replace").strip()
        size = int(header[48:58].decode("ascii").strip())
        start = off + 60
        yield name.rstrip("/"), data[start:start + size]
        off = start + size + (size & 1)  # padding pair


def extract_deb(deb: bytes, out_dir: str):
    """Extrait data.tar.* d'un .deb dans out_dir."""
    for name, blob in ar_members(deb):
        if not name.startswith("data.tar"):
            continue
        if name.endswith(".xz"):
            tar_bytes = lzma.decompress(blob)
        elif name.endswith(".gz"):
            tar_bytes = gzip.decompress(blob)
        elif name.endswith(".zst"):
            raise RuntimeError(
                f"{name} est en zstd — installe 'pip install zstandard' et adapte, "
                "ou utilise une release Debian plus ancienne (bullseye = xz)."
            )
        else:  # data.tar non compressé
            tar_bytes = blob
        with tarfile.open(fileobj=io.BytesIO(tar_bytes)) as tf:
            tf.extractall(out_dir)  # préserve ./usr/include, ./usr/lib, ...
        return
    raise RuntimeError("aucun data.tar dans le .deb")


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    default_out = os.path.join(os.path.dirname(here), "sysroot", "linux-x86_64")

    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=default_out, help="dossier sysroot de sortie")
    ap.add_argument("--add", default="", help="paquets supplémentaires (séparés par des virgules)")
    args = ap.parse_args()

    packages = list(PACKAGES)
    if args.add:
        packages += [p.strip() for p in args.add.split(",") if p.strip()]

    os.makedirs(args.out, exist_ok=True)
    print(f"[1/3] Index des paquets {DIST}/{ARCH}...")
    index = load_packages_index()

    print(f"[2/3] Téléchargement + extraction de {len(packages)} paquets -> {args.out}")
    missing, done = [], 0
    for pkg in packages:
        meta = index.get(pkg)
        if not meta or "Filename" not in meta:
            missing.append(pkg)
            print(f"  ! introuvable dans l'index : {pkg}")
            continue
        try:
            deb = fetch(f"{MIRROR}/{meta['Filename']}")
            extract_deb(deb, args.out)
            done += 1
        except Exception as e:  # noqa: BLE001
            missing.append(pkg)
            print(f"  ! échec {pkg} : {e}")

    # Beaucoup de .so sont des symlinks versionnés (libGL.so -> libGL.so.1).
    # Sous Windows sans droits symlink, ils peuvent manquer : on les recrée en
    # copies quand la cible existe.
    print("[3/3] Réparation des symlinks .so manquants (Windows)...")
    libdir = os.path.join(args.out, "usr", "lib", "x86_64-linux-gnu")
    fixed = 0
    if os.path.isdir(libdir):
        names = set(os.listdir(libdir))
        for n in list(names):
            # ex. libGL.so.1.7.0 -> créer libGL.so.1 et libGL.so si absents
            if ".so." in n:
                base = n.split(".so.")[0] + ".so"
                for cand in (base, base + "." + n.split(".so.")[1].split(".")[0]):
                    tgt = os.path.join(libdir, cand)
                    if not os.path.exists(tgt):
                        try:
                            import shutil
                            shutil.copy2(os.path.join(libdir, n), tgt)
                            fixed += 1
                        except Exception:
                            pass

    print("\n=== Terminé ===")
    print(f"  paquets extraits : {done}/{len(packages)}")
    print(f"  symlinks .so recréés : {fixed}")
    if missing:
        print(f"  manquants/échoués : {', '.join(missing)}")
    print(f"\nSysroot : {args.out}")
    print("Test :")
    print(f'  zig cc -target x86_64-linux-gnu --sysroot "{args.out}" \\')
    print(f'    -isystem "{args.out}/usr/include" \\')
    print(f'    -L "{args.out}/usr/lib/x86_64-linux-gnu" \\')
    print('    hello.c -lX11 -lGL -o hello')


if __name__ == "__main__":
    main()
