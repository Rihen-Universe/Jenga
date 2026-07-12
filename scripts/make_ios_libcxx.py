#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
make_ios_libcxx.py — Produit une libc++ / libc++abi utilisables au LINK iOS.

Problème résolu : Zig compile avec SES en-têtes libc++ (v19), mais la libc++ des
SDK iOS anciens (ex. 12.2) n'exporte pas les mêmes symboles → undefined symbols
(std::ifstream, basic_filebuf::open, …) au link. Il n'existe pas de libc++.a
Zig taguée iOS (Zig ne la construit qu'au moment du link, qu'on contourne).

Solution : Zig sait construire une libc++.a **macOS** (arm64, ABI identique à iOS
puisque même source v19). On la **re-tague** macOS→iOS dans les load commands
Mach-O (LC_BUILD_VERSION / LC_VERSION_MIN), puis on ajoute un petit shim pour les
symboles absents des vieux libSystem iOS (aligned_alloc → posix_memalign).

Sortie : <out>/{libc++.a, libc++abi.a, ios_compat.o} — le IosZigBuilder les lie
automatiquement s'ils existent (voir Core/Builders/IosZig.py, env IOS_LIBCPP_DIR).

Usage :
    python make_ios_libcxx.py --zig <zig.exe> --sdk <iPhoneOS.sdk> \
                              --ld <ld.lld.exe> [--out C:\\apple-sdks\\libcxx-ios]
"""

import argparse
import glob
import os
import shutil
import struct
import subprocess
import tempfile
from pathlib import Path

LC_BUILD_VERSION = 0x32
LC_VERSION_MIN_MACOSX = 0x24
LC_VERSION_MIN_IPHONEOS = 0x25
PLAT_MACOS = 1
PLAT_IOS = 2


def log(m):
    print(f"[make-ios-libcxx] {m}", flush=True)


def retag_macho(data: bytes) -> bytes:
    """Change la plateforme macOS->iOS dans les load commands d'un Mach-O 64."""
    if len(data) < 32:
        return data
    magic = struct.unpack('<I', data[0:4])[0]
    if magic not in (0xFEEDFACF, 0xCFFAEDFE):
        return data
    b = bytearray(data)
    ncmds = struct.unpack('<I', data[16:20])[0]
    off = 32
    for _ in range(ncmds):
        if off + 8 > len(b):
            break
        cmd, cmdsize = struct.unpack('<II', b[off:off + 8])
        if cmd == LC_BUILD_VERSION:
            if struct.unpack('<I', b[off + 8:off + 12])[0] == PLAT_MACOS:
                struct.pack_into('<I', b, off + 8, PLAT_IOS)
        elif cmd == LC_VERSION_MIN_MACOSX:
            struct.pack_into('<I', b, off, LC_VERSION_MIN_IPHONEOS)
        if cmdsize == 0:
            break
        off += cmdsize
    return bytes(b)


def retag_archive(ar: str, src: Path, dst: Path):
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run([ar, "x", str(src.resolve())], cwd=tmp, check=True, capture_output=True)
        objs = []
        for o in Path(tmp).glob("*.o"):
            o.write_bytes(retag_macho(o.read_bytes()))
            objs.append(str(o))
        if dst.exists():
            dst.unlink()
        subprocess.run([ar, "rcs", str(dst.resolve())] + objs, check=True, capture_output=True)
    return len(objs)


def build_macos_libcxx(zig: str, work: Path) -> Path:
    """Force Zig à construire sa libc++.a macOS (via un link C++ jetable) et la
    retourne depuis le cache Zig (le .a le plus récent contenant basic_filebuf)."""
    src = work / "probe.cpp"
    src.write_text("#include <fstream>\n#include <string>\nint main(){std::ifstream f(\"x\");std::string s;if(f)f>>s;return (int)s.size();}\n")
    # Un link macOS marche nativement avec Zig (contrairement à iOS).
    subprocess.run([zig, "c++", "-target", "aarch64-macos", "-o", str(work / "probe"), str(src)],
                   check=False, capture_output=True)
    cache = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "zig" / "o"
    cands = []
    for a in cache.glob("*/libc++.a"):
        cands.append(a)
    if not cands:
        raise RuntimeError("libc++.a introuvable dans le cache Zig — le link macOS a-t-il réussi ?")
    # Prendre la plus récente.
    return max(cands, key=lambda p: p.stat().st_mtime)


def find_libcxxabi() -> Path:
    cache = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "zig" / "o"
    cands = list(cache.glob("*/libc++abi.a"))
    if not cands:
        raise RuntimeError("libc++abi.a introuvable dans le cache Zig.")
    return max(cands, key=lambda p: p.stat().st_mtime)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--zig", required=True)
    ap.add_argument("--sdk", required=True, help="SDK iOS (pour le shim + version)")
    ap.add_argument("--ar", default="", help="llvm-ar (défaut: celui du NDK)")
    ap.add_argument("--out", default=r"C:\apple-sdks\libcxx-ios")
    args = ap.parse_args()

    ar = args.ar
    if not ar:
        c = glob.glob(str(Path(os.environ.get("ANDROID_NDK_HOME", "")) /
                          "toolchains" / "llvm" / "prebuilt" / "*" / "bin" / "llvm-ar.exe"))
        ar = c[0] if c else "llvm-ar"

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        log("Construction de la libc++.a macOS via Zig…")
        cpp = build_macos_libcxx(args.zig, work)
        abi = find_libcxxabi()
        log(f"libc++.a  = {cpp}")
        log(f"libc++abi = {abi}")

        log("Re-tag Mach-O macOS -> iOS…")
        n1 = retag_archive(ar, cpp, out / "libc++.a")
        n2 = retag_archive(ar, abi, out / "libc++abi.a")
        log(f"  libc++.a: {n1} objets ; libc++abi.a: {n2} objets")

    # Shim aligned_alloc (absent des libSystem iOS < 13).
    shim_c = out / "ios_compat.c"
    shim_c.write_text(
        "#include <stdlib.h>\n"
        "void* aligned_alloc(size_t a, size_t s){void* p=0;"
        "if(posix_memalign(&p,a,s)!=0)return 0;return p;}\n"
    )
    log("Compilation du shim ios_compat.o…")
    subprocess.run([args.zig, "cc", "-target", "aarch64-ios",
                    "-isysroot", args.sdk, "-isystem", str(Path(args.sdk) / "usr" / "include"),
                    "-c", "-o", str(out / "ios_compat.o"), str(shim_c)],
                   check=True, capture_output=True)

    print(f"\n✅ libc++ iOS prête : {out}")
    print("   Le IosZigBuilder la liera automatiquement (ou définir IOS_LIBCPP_DIR).")


if __name__ == "__main__":
    main()
