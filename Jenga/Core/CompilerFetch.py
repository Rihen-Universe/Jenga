#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CompilerFetch – Telechargement du compilateur PAR DEFAUT pour la distribution
legere de NKCode : l'archive testeur n'embarque pas de compilateur, il est
recupere ICI au premier build, via l'interpreteur Python DEJA embarque (urllib
+ zipfile/tarfile stdlib, zero dependance). Progression remontee par le meme
`sink` que Embed.Build (OnFileTotal/OnFileDone animent la barre de NKCode,
OnLogLine le transcript).

Le compilateur par defaut DEPEND DE L'HOTE :

  - Windows  -> llvm-mingw (Clang autonome, ~140 Mo). Aucun MSVC requis.
  - Linux    -> Zig (~44 Mo). `zig cc` / `zig c++` EST un Clang complet, et
                Jenga enregistre deja `zig-linux-x86_64` comme toolchain
                (Core/Toolchains.py) : rien de special a configurer ensuite.
  - macOS    -> Zig, pour la meme raison (evite d'exiger Xcode).

Zig plutot qu'un LLVM complet sous Unix : 44 Mo contre ~1 Go, pour le meme
service ici. La version est alignee sur celle vendorisee cote NKCode
(Externals/Libs/ZigToolchain) ET sur le defaut de Commands/Install.py, pour
qu'un testeur obtienne exactement le compilateur teste.

All public methods are PascalCase (convention Rihen).
"""

import os
import platform
import shutil
import tarfile
import urllib.request
import zipfile
from pathlib import Path

LLVM_MINGW_URL = ("https://github.com/mstorsjo/llvm-mingw/releases/download/"
                  "20240619/llvm-mingw-20240619-ucrt-x86_64.zip")

# Aligne sur Externals/Libs/ZigToolchain (NKCode) et sur le defaut de
# Commands/Install.py::_AutoInstallZig. A garder synchronise avec les deux.
ZIG_VERSION = "0.13.0"

# Cibles inutiles pour NKCode (x86_64 uniquement) — memes exclusions que
# scripts/MakeNkCodeDist.py cote Nkentseu.
_EXCLUDE_DIRS = {"i686-w64-mingw32", "armv7-w64-mingw32",
                 "aarch64-w64-mingw32", "arm64ec-w64-mingw32"}
_EXCLUDE_PREFIXES = ("i686-", "armv7-", "aarch64-", "arm64ec-")


def _IsWindows() -> bool:
    return os.name == "nt"


def _Log(sink, msg):
    if sink is not None and hasattr(sink, "OnLogLine"):
        sink.OnLogLine(msg)


def _Progress(sink, name, pct):
    # Reutilise la barre de progression MODULE de NKCode (index/total).
    if sink is not None and hasattr(sink, "OnFileDone"):
        sink.OnFileDone(name, int(pct), 100, "", True, False)


def _Hook(sink, name):
    """reporthook urlretrieve -> barre de progression + log tous les 10 %."""
    last = [-1]

    def Inner(blocks, bs, total):
        if total > 0:
            pct = min(99, blocks * bs * 100 // total)
            if pct != last[0]:
                last[0] = pct
                _Progress(sink, name, pct)
                if pct % 10 == 0:
                    _Log(sink, f"[compilateur] telechargement... {pct}%")

    return Inner


def DefaultCompilerName() -> str:
    """Nom du compilateur par defaut de l'hote — sert AUSSI de nom de dossier
    sous `dest_root`. L'hote C++ (NKCode) doit tester CE dossier, pas
    « llvm-mingw » en dur, sinon il redemande une installation a l'infini sur
    Linux/macOS."""
    return "llvm-mingw" if _IsWindows() else "zig"


def _Root(dest_root) -> Path:
    return Path(dest_root) / DefaultCompilerName()


def BinDir(dest_root) -> str:
    """Dossier a PREFIXER au PATH pour que le compilateur soit trouve.
    llvm-mingw expose ses binaires dans bin/ ; l'archive Zig pose `zig` a la
    racine."""
    d = _Root(dest_root)
    return str(d / "bin") if _IsWindows() else str(d)


def IsInstalled(dest_root) -> bool:
    """True si le compilateur par defaut est deja present (marqueur .ok ecrit
    en DERNIER : une installation interrompue n'est jamais vue comme finie)."""
    d = _Root(dest_root)
    if not (d / ".ok").exists():
        return False
    return (d / "bin" / "clang++.exe").exists() if _IsWindows() else (d / "zig").exists()


def _ZigArchiveName() -> str:
    """Nom de l'archive Zig pour l'hote courant (schema de nommage 0.13.x)."""
    m = platform.machine().lower()
    arch = "aarch64" if m in ("arm64", "aarch64") else "x86_64"
    osname = "macos" if platform.system() == "Darwin" else "linux"
    return f"zig-{osname}-{arch}-{ZIG_VERSION}.tar.xz"


def _InstallZig(dest_root: Path, final: Path, sink) -> int:
    """Telecharge + extrait Zig dans `final`. `zig cc`/`zig c++` fournissent un
    Clang complet, deja connu de Jenga comme toolchain zig-<os>-<arch>."""
    name = _ZigArchiveName()
    url = f"https://ziglang.org/download/{ZIG_VERSION}/{name}"
    archive = dest_root / (name + ".part")
    _Log(sink, f"[compilateur] telechargement de Zig {ZIG_VERSION} (~44 Mo)...")
    if sink is not None and hasattr(sink, "OnFileTotal"):
        sink.OnFileTotal("zig", 100)
    urllib.request.urlretrieve(url, archive, reporthook=_Hook(sink, "zig"))

    _Log(sink, "[compilateur] extraction...")
    tmp = dest_root / "_extract"
    if tmp.exists():
        shutil.rmtree(tmp)
    with tarfile.open(archive, "r:xz") as t:
        t.extractall(tmp)  # tarfile restitue le bit d'execution du binaire zig
    roots = [p for p in tmp.iterdir() if p.is_dir()]
    if not roots:
        _Log(sink, "[compilateur] ERREUR : archive vide/inattendue")
        return 1
    if final.exists():
        shutil.rmtree(final)
    shutil.move(str(roots[0]), str(final))
    shutil.rmtree(tmp, ignore_errors=True)
    archive.unlink(missing_ok=True)
    # Ceinture et bretelles : selon l'umask et le systeme de fichiers (montage
    # Windows sous WSL...), le bit +x peut ne pas survivre a l'extraction.
    exe = final / "zig"
    try:
        exe.chmod(exe.stat().st_mode | 0o111)
    except Exception:
        pass
    _Log(sink, "[compilateur] Zig installe : " + str(final))
    return 0


def _InstallLlvmMingw(dest_root: Path, final: Path, sink) -> int:
    """Telecharge + extrait llvm-mingw (x86_64 uniquement) — chemin Windows."""
    zip_path = dest_root / "llvm-mingw.zip.part"
    _Log(sink, "[compilateur] telechargement de Clang (llvm-mingw, ~140 Mo)...")
    if sink is not None and hasattr(sink, "OnFileTotal"):
        sink.OnFileTotal("llvm-mingw", 100)
    urllib.request.urlretrieve(LLVM_MINGW_URL, zip_path,
                               reporthook=_Hook(sink, "llvm-mingw"))
    _Log(sink, "[compilateur] extraction (x86_64 uniquement)...")
    tmp = dest_root / "_extract"
    if tmp.exists():
        shutil.rmtree(tmp)
    with zipfile.ZipFile(zip_path) as z:
        z.extractall(tmp)
    # l'archive contient un dossier racine llvm-mingw-<date>-ucrt-x86_64
    roots = [p for p in tmp.iterdir() if p.is_dir()]
    if not roots:
        _Log(sink, "[compilateur] ERREUR : archive vide/inattendue")
        return 1
    src = roots[0]
    if final.exists():
        shutil.rmtree(final)
    final.mkdir(parents=True)
    for item in src.iterdir():
        if item.is_dir() and item.name in _EXCLUDE_DIRS:
            continue
        if item.name == "bin":
            (final / "bin").mkdir()
            for f in item.iterdir():
                if f.name.startswith(_EXCLUDE_PREFIXES):
                    continue
                shutil.move(str(f), str(final / "bin" / f.name))
        else:
            shutil.move(str(item), str(final / item.name))
    shutil.rmtree(tmp, ignore_errors=True)
    zip_path.unlink(missing_ok=True)
    _Log(sink, "[compilateur] Clang installe : " + str(final / "bin"))
    return 0


def InstallDefaultCompiler(dest_root: str, sink=None) -> int:
    """Installe le compilateur par defaut de l'HOTE sous `dest_root` :
    llvm-mingw sur Windows, Zig sur Linux/macOS. Retourne 0 si OK, 1 sinon.
    Idempotent."""
    dest_root = Path(dest_root)
    final = _Root(dest_root)
    if IsInstalled(dest_root):
        _Log(sink, "[compilateur] deja installe : " + str(final))
        return 0
    dest_root.mkdir(parents=True, exist_ok=True)
    try:
        rc = _InstallLlvmMingw(dest_root, final, sink) if _IsWindows() \
            else _InstallZig(dest_root, final, sink)
        if rc != 0:
            return rc
        # Marqueur ecrit en DERNIER : voir IsInstalled.
        (final / ".ok").write_text("ok", encoding="utf-8")
        _Progress(sink, DefaultCompilerName(), 100)
        return 0
    except Exception as ex:  # reseau coupe, disque plein... -> message honnete
        _Log(sink, f"[compilateur] ECHEC : {ex}")
        for junk in ("llvm-mingw.zip.part",):
            try:
                (dest_root / junk).unlink(missing_ok=True)
            except Exception:
                pass
        return 1
