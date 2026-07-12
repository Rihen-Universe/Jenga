#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
setup_apple_toolchain.py — Installe TOUT le nécessaire pour cross-compiler
macOS / iOS / tvOS / watchOS **depuis Windows** avec Zig + ld.lld.

Ce que ça met en place (idempotent) :
  1. Zig 0.13.0 (linker Mach-O stable)                      -> <root>/zigldl/
  2. SDK macOS (phracker MacOSX-SDKs)                       -> <root>/MacOSX11.3.sdk
  3. SDK iOS/tvOS/watchOS (qianjigui/iOS-sdks ou Xcode)     -> <root>/<Plat>.sdk
  4. Réparation Windows des SDK (jonctions frameworks + tbd usr/lib)
  5. Wrappers zig-cc / zig-c++ / zig-ar                     -> <root>/bin/
  6. Détection de ld.lld (linker Mach-O) dans le NDK Android
  7. Vérification : compile+link macOS et iOS d'un mini programme

Puis affiche les variables d'environnement à définir.

Usage :
    python setup_apple_toolchain.py [--root C:\\apple-sdks] [--skip-ios] [--skip-macos]

⚠️  Le link iOS EXIGE un SDK COMPLET (usr/lib/libSystem.tbd). Les SDK "theos"
(headers-only) ne suffisent pas — le script le détecte et prévient.
Sources (surchargeables) :
  - macOS : https://github.com/phracker/MacOSX-SDKs/releases/tag/11.3
  - iOS   : https://github.com/qianjigui/iOS-sdks
"""

import argparse
import io
import os
import re
import subprocess
import sys
import tarfile
import urllib.request
import zipfile
from pathlib import Path

ZIG_URL = "https://ziglang.org/download/0.13.0/zig-windows-x86_64-0.13.0.zip"
ZIG_DIRNAME = "zig-windows-x86_64-0.13.0"

# SDK par défaut. Le macOS phracker est COMPLET (link ok). Pour iOS, préférer un
# SDK Xcode complet ; certains dépôts communautaires sont headers-only (link KO).
MACOS_SDK_URL = "https://github.com/phracker/MacOSX-SDKs/releases/download/11.3/MacOSX11.3.sdk.tar.xz"
MACOS_SDK_DIR = "MacOSX11.3.sdk"


def log(msg):
    print(f"[apple-setup] {msg}", flush=True)


def fetch(url: str) -> bytes:
    log(f"GET {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "jenga-apple-setup/1.0"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read()


def download_to(url: str, dst: Path):
    dst.parent.mkdir(parents=True, exist_ok=True)
    data = fetch(url)
    dst.write_bytes(data)
    return dst


def extract_archive(archive: Path, out_dir: Path):
    out_dir.mkdir(parents=True, exist_ok=True)
    name = archive.name.lower()
    if name.endswith(".zip"):
        with zipfile.ZipFile(archive) as z:
            z.extractall(out_dir)
    else:
        mode = "r:xz" if name.endswith((".xz", ".txz")) else \
               "r:bz2" if name.endswith((".bz2", ".tbz2", ".tbz")) else \
               "r:gz" if name.endswith((".gz", ".tgz")) else "r:*"
        # Windows : les symlinks échouent ; on ignore ces erreurs (réparées après).
        with tarfile.open(archive, mode) as t:
            for m in t.getmembers():
                try:
                    t.extract(m, out_dir)
                except Exception:
                    pass


def find_sdk_root(base: Path, keyword: str) -> Path:
    """Trouve un dossier *.sdk (potentiellement niché dans une arbo Xcode)."""
    cands = list(base.rglob("*.sdk"))
    for c in cands:
        if keyword.lower() in c.name.lower():
            return c
    return cands[0] if cands else base


def repair_sdk(sdk: Path):
    """Recrée les entrées racine des frameworks (jonctions) + tbd usr/lib manquants.
    Nécessaire car Windows ne peut pas extraire les symlinks Versions/Current/…"""
    ps = r'''
$fw = "%s\System\Library\Frameworks"
if (Test-Path $fw) {
  Get-ChildItem $fw -Recurse -Filter *.framework -Directory -EA SilentlyContinue | ForEach-Object {
    $F=$_.FullName; $cur=Join-Path $F "Versions\Current"; if(-not(Test-Path $cur)){$cur=Join-Path $F "Versions\A"}
    if(-not(Test-Path $cur)){return}
    Get-ChildItem $cur -EA SilentlyContinue | ForEach-Object {
      $t=Join-Path $F $_.Name; if(Test-Path $t){return}
      if($_.PSIsContainer){ try{New-Item -ItemType Junction -Path $t -Target $_.FullName -EA Stop|Out-Null}catch{} }
      else{ try{Copy-Item $_.FullName $t -EA Stop}catch{} }
    }
  }
}
$lib = "%s\usr\lib"
if (Test-Path $lib) {
  foreach ($p in @(@("libSystem.B.tbd","libSystem.tbd"),@("libc++.1.tbd","libc++.tbd"),@("libobjc.A.tbd","libobjc.tbd"))) {
    $src=Join-Path $lib $p[0]; $dst=Join-Path $lib $p[1]
    if((Test-Path $src) -and -not(Test-Path $dst)){ Copy-Item $src $dst -EA SilentlyContinue }
  }
}
''' % (str(sdk), str(sdk))
    try:
        subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                       check=False, capture_output=True, text=True, timeout=600)
    except Exception as e:  # noqa: BLE001
        log(f"réparation SDK (avert.) : {e}")


def make_wrappers(root: Path, zig_exe: Path):
    """Crée zig-cc/zig-c++/zig-ar dans <root>/bin (pour la détection Jenga)."""
    bindir = root / "bin"
    bindir.mkdir(parents=True, exist_ok=True)
    z = str(zig_exe)
    for name, sub in (("zig-cc", "cc"), ("zig-c++", "c++"), ("zig-ar", "ar")):
        (bindir / f"{name}.cmd").write_text(f'@echo off\r\n"{z}" {sub} %*\r\n', encoding="ascii")
    return bindir


def find_ld64() -> str:
    ndk = os.environ.get("ANDROID_NDK_HOME") or os.environ.get("ANDROID_NDK_ROOT") or ""
    if ndk:
        import glob
        c = glob.glob(str(Path(ndk) / "toolchains" / "llvm" / "prebuilt" / "*" / "bin" / "ld.lld.exe"))
        if c:
            return c[0]
    return ""


def sdk_link_ready(sdk: Path) -> bool:
    return (sdk / "usr" / "lib" / "libSystem.tbd").exists() or \
           (sdk / "usr" / "lib" / "libSystem.B.tbd").exists()


def verify(root: Path, zig_exe: Path, macos_sdk: Path, ios_sdk: Path, ld64: str):
    tmp = root / "_verify"
    tmp.mkdir(exist_ok=True)
    ok = {}
    # macOS : compile + link C (zig gère le link macOS)
    if macos_sdk and macos_sdk.exists():
        (tmp / "m.c").write_text("int main(void){return 0;}\n")
        r = subprocess.run([str(zig_exe), "cc", "-target", "aarch64-macos",
                            "--sysroot", str(macos_sdk), "-isysroot", str(macos_sdk),
                            "-o", str(tmp / "m_out"), str(tmp / "m.c")],
                           capture_output=True, text=True)
        ok["macOS"] = (r.returncode == 0 and (tmp / "m_out").exists())
    # iOS : compile (zig) + link (ld.lld darwin)
    if ios_sdk and ios_sdk.exists() and ld64 and sdk_link_ready(ios_sdk):
        (tmp / "i.mm").write_text("#import <Foundation/Foundation.h>\nint main(){@autoreleasepool{}return 0;}\n")
        c = subprocess.run([str(zig_exe), "c++", "-target", "aarch64-ios",
                            "--sysroot", str(ios_sdk), "-isysroot", str(ios_sdk),
                            "-isystem", str(ios_sdk / "usr" / "include"),
                            "-F", str(ios_sdk / "System" / "Library" / "Frameworks"),
                            "-x", "objective-c++", "-c", "-o", str(tmp / "i.o"), str(tmp / "i.mm")],
                           capture_output=True, text=True)
        if c.returncode == 0:
            sdkv = re.search(r"(\d+\.\d+)", ios_sdk.name)
            sdkv = sdkv.group(1) if sdkv else "12.0"
            l = subprocess.run([ld64, "-flavor", "darwin", "-arch", "arm64",
                                "-platform_version", "ios", "12.0", sdkv,
                                "-syslibroot", str(ios_sdk), "-execute",
                                "-o", str(tmp / "i_out"), str(tmp / "i.o"),
                                "-framework", "Foundation", "-lSystem", "-lc++", "-lobjc"],
                               capture_output=True, text=True)
            ok["iOS"] = (l.returncode == 0 and (tmp / "i_out").exists())
        else:
            ok["iOS"] = False
    return ok


def do_check(root: Path, as_json: bool = False, run_compile: bool = False) -> int:
    """Sonde de détection SANS rien télécharger (pour NKCode & CI).
    Détecte les 5 composants, retourne 0 si iOS OU macOS est prêt, sinon 1.
    Avec as_json : émet un rapport JSON parsable ; sinon un résumé lisible."""
    import glob as _glob

    # 1) zig 0.13 (macOS ET iOS)
    zig_exe = Path(os.environ.get("ZIG_MACOS") or (root / "zigldl" / ZIG_DIRNAME / "zig.exe"))
    zig_ver = ""
    zig_ok = zig_exe.exists()
    if zig_ok:
        try:
            r = subprocess.run([str(zig_exe), "version"], capture_output=True, text=True)
            zig_ver = (r.stdout or "").strip()
            zig_ok = zig_ver.startswith("0.13")
        except Exception:  # noqa: BLE001
            zig_ok = False

    # 2) SDK macOS
    macos_sdk = Path(os.environ.get("MACOS_SDK") or (root / MACOS_SDK_DIR))
    if not macos_sdk.exists():
        g = list(root.glob("MacOSX*.sdk"))
        if g:
            macos_sdk = g[0]
    macos_sdk_ok = macos_sdk.exists()

    # 3) SDK iOS (doit être COMPLET pour linker)
    ios_env = os.environ.get("IOS_SDK")
    ios_sdk = Path(ios_env) if ios_env else None
    if not (ios_sdk and ios_sdk.exists()):
        g = list(root.glob("iPhoneOS*.sdk"))
        ios_sdk = g[0] if g else ios_sdk
    ios_sdk_present = bool(ios_sdk and ios_sdk.exists())
    ios_sdk_complete = bool(ios_sdk_present and sdk_link_ready(ios_sdk))

    # 4) ld.lld (NDK) + libc++ iOS retaguée
    ld64 = os.environ.get("LD64") or find_ld64()
    ld_ok = bool(ld64 and Path(ld64).exists())
    libcpp_dir = os.environ.get("IOS_LIBCPP_DIR") or str(root / "libcxx-ios")
    libcpp_ok = (Path(libcpp_dir) / "libc++.a").exists()

    # 5) rcodesign (optionnel)
    rc = os.environ.get("RCODESIGN") or ""
    if not rc:
        g = _glob.glob(str(root / "tools" / "apple-codesign-*" / "rcodesign.exe"))
        rc = g[0] if g else ""
    sign_ok = bool(rc and Path(rc).exists())

    ios_available = bool(zig_ok and ios_sdk_complete and ld_ok and libcpp_ok)
    macos_available = bool(zig_ok and macos_sdk_ok)

    # Vérification compile+link optionnelle (plus lente, mais preuve réelle).
    compile_results = {}
    if run_compile and zig_ok:
        compile_results = verify(root, zig_exe,
                                 macos_sdk if macos_sdk_ok else None,
                                 ios_sdk if ios_sdk_present else None, ld64)

    data = {
        "zig":        {"path": str(zig_exe), "ok": zig_ok, "version": zig_ver},
        "macos_sdk":  {"path": str(macos_sdk), "ok": macos_sdk_ok},
        "ios_sdk":    {"path": str(ios_sdk) if ios_sdk else "", "present": ios_sdk_present,
                       "complete": ios_sdk_complete, "ok": ios_sdk_complete},
        "ld64":       {"path": ld64, "ok": ld_ok},
        "ios_libcxx": {"path": libcpp_dir, "ok": libcpp_ok},
        "rcodesign":  {"path": rc, "ok": sign_ok},
        "ios_available":     ios_available,
        "macos_available":   macos_available,
        "signing_available": sign_ok,
        "compile_check":     compile_results,
    }

    if as_json:
        import json
        print(json.dumps(data, indent=2, ensure_ascii=False))
    else:
        def mark(b):
            return "OK " if b else "-- "
        print("========== DÉTECTION TOOLCHAIN APPLE (zig) ==========")
        print(f" [{mark(zig_ok)}] zig 0.13        {zig_exe}  ({zig_ver or 'introuvable'})")
        print(f" [{mark(macos_sdk_ok)}] SDK macOS       {macos_sdk if macos_sdk_ok else 'absent'}")
        print(f" [{mark(ios_sdk_complete)}] SDK iOS complet {ios_sdk or 'absent'}"
              + ("" if ios_sdk_complete else "  (incomplet: pas de usr/lib/libSystem.tbd)" if ios_sdk_present else ""))
        print(f" [{mark(ld_ok)}] ld.lld (NDK)    {ld64 or 'introuvable (ANDROID_NDK_HOME)'}")
        print(f" [{mark(libcpp_ok)}] libc++ iOS      {libcpp_dir}")
        print(f" [{mark(sign_ok)}] rcodesign       {rc or 'absent (signature indispo)'}")
        print("-----------------------------------------------------")
        print(f"  iOS prêt     : {'OUI' if ios_available else 'NON'}")
        print(f"  macOS prêt   : {'OUI' if macos_available else 'NON'}")
        print(f"  signature    : {'OUI' if sign_ok else 'NON'}")
        if run_compile:
            for k, v in compile_results.items():
                print(f"  compile {k:6}: {'OK' if v else 'ÉCHEC'}")
        if not (ios_available or macos_available):
            print("  → Rien de prêt. Lancer sans --check pour installer, ou définir "
                  "ZIG_MACOS/IOS_SDK/LD64/IOS_LIBCPP_DIR.")

    return 0 if (ios_available or macos_available) else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=r"C:\apple-sdks")
    ap.add_argument("--macos-sdk-url", default=MACOS_SDK_URL)
    ap.add_argument("--ios-sdk-url", default="", help="URL .tar.* d'un SDK iOS COMPLET (Xcode)")
    ap.add_argument("--skip-macos", action="store_true")
    ap.add_argument("--skip-ios", action="store_true")
    ap.add_argument("--check", action="store_true",
                    help="Détection seule (aucun téléchargement). Exit 0 si iOS ou macOS prêt.")
    ap.add_argument("--json", action="store_true", help="Avec --check : rapport JSON (pour NKCode).")
    ap.add_argument("--compile-check", action="store_true",
                    help="Avec --check : lance aussi un vrai compile+link (plus lent).")
    args = ap.parse_args()

    root = Path(args.root)

    # Mode sonde : ne crée/ne télécharge rien, détecte et sort avec un code clair.
    if args.check:
        return do_check(root, as_json=args.json, run_compile=args.compile_check)

    root.mkdir(parents=True, exist_ok=True)
    dl = root / "_dl"; dl.mkdir(exist_ok=True)

    # 1) Zig 0.13
    zig_dir = root / "zigldl" / ZIG_DIRNAME
    zig_exe = zig_dir / "zig.exe"
    if not zig_exe.exists():
        log("Installation de Zig 0.13.0…")
        z = download_to(ZIG_URL, dl / "zig.zip")
        extract_archive(z, root / "zigldl")
    log(f"Zig : {zig_exe} ({'OK' if zig_exe.exists() else 'MANQUANT'})")

    # 2) SDK macOS
    macos_sdk = root / MACOS_SDK_DIR
    if not args.skip_macos and not macos_sdk.exists():
        log("Installation du SDK macOS (phracker)…")
        try:
            a = download_to(args.macos_sdk_url, dl / "macos_sdk.tar.xz")
            extract_archive(a, root)
            macos_sdk = find_sdk_root(root, "MacOSX")
            repair_sdk(macos_sdk)
        except Exception as e:  # noqa: BLE001
            log(f"SDK macOS : échec ({e}). Télécharge manuellement depuis "
                "https://github.com/phracker/MacOSX-SDKs/releases/tag/11.3")

    # 3) SDK iOS (optionnel — URL requise, doit être COMPLET)
    ios_sdk = None
    if not args.skip_ios:
        existing = [p for p in root.glob("iPhoneOS*.sdk")]
        if existing:
            ios_sdk = existing[0]
        elif args.ios_sdk_url:
            log("Installation du SDK iOS…")
            try:
                a = download_to(args.ios_sdk_url, dl / "ios_sdk.tar")
                extract_archive(a, root)
                ios_sdk = find_sdk_root(root, "iPhoneOS")
            except Exception as e:  # noqa: BLE001
                log(f"SDK iOS : échec ({e}).")
        if ios_sdk:
            repair_sdk(ios_sdk)

    # 4) Wrappers + ld64
    bindir = make_wrappers(root, zig_exe)
    ld64 = find_ld64()

    # 5) Vérification
    log("Vérification (compile+link)…")
    results = verify(root, zig_exe, macos_sdk if macos_sdk.exists() else None, ios_sdk, ld64)

    # Résumé
    print("\n================= RÉSUMÉ =================")
    print(f"Zig            : {zig_exe}")
    print(f"Wrappers (PATH): {bindir}")
    print(f"ld.lld (NDK)   : {ld64 or 'INTROUVABLE (installer un NDK Android, ANDROID_NDK_HOME)'}")
    print(f"SDK macOS      : {macos_sdk if macos_sdk.exists() else 'absent'}")
    print(f"SDK iOS        : {ios_sdk or 'absent'}")
    if ios_sdk and not sdk_link_ready(ios_sdk):
        print("  ⚠️  SDK iOS INCOMPLET (pas de usr/lib/libSystem.tbd) → link iOS IMPOSSIBLE.")
        print("     Utilise un SDK Xcode complet (usr/lib avec libSystem/libc++/libobjc.tbd).")
    for k, v in results.items():
        print(f"  test {k:6}: {'✅ OK' if v else '❌ ÉCHEC'}")

    print("\n--- Variables d'environnement à définir ---")
    print(f'  set PATH=%PATH%;{bindir}')
    print(f'  set ZIG_MACOS={zig_exe}')
    if macos_sdk.exists():
        print(f'  set MACOS_SDK={macos_sdk}')
    if ios_sdk:
        print(f'  set IOS_SDK={ios_sdk}')
    if ld64:
        print(f'  set LD64={ld64}')
    print("\nEnsuite :")
    print("  jenga build --platform macOS --macos-backend=zig")
    print("  jenga build --platform iOS   --ios-backend=zig")


if __name__ == "__main__":
    sys.exit(main() or 0)
