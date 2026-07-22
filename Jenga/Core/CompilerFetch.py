#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CompilerFetch – Telechargement du compilateur PAR DEFAUT (llvm-mingw, Clang
autonome x86_64) pour la distribution legere de NKCode : l'archive testeur
< 50 Mo n'embarque pas le compilateur ; il est recupere ICI au premier build,
via l'interpreteur Python DEJA embarque (urllib + zipfile stdlib, zero
dependance). Progression remontee par le meme `sink` que Embed.Build
(OnFileTotal/OnFileDone animent la barre de NKCode, OnLogLine le transcript).

All public methods are PascalCase (convention Rihen).
"""

import shutil
import urllib.request
import zipfile
from pathlib import Path

LLVM_MINGW_URL = ("https://github.com/mstorsjo/llvm-mingw/releases/download/"
                  "20240619/llvm-mingw-20240619-ucrt-x86_64.zip")

# Cibles inutiles pour NKCode (x86_64 uniquement) — memes exclusions que
# scripts/MakeNkCodeDist.py cote Nkentseu.
_EXCLUDE_DIRS = {"i686-w64-mingw32", "armv7-w64-mingw32",
                 "aarch64-w64-mingw32", "arm64ec-w64-mingw32"}
_EXCLUDE_PREFIXES = ("i686-", "armv7-", "aarch64-", "arm64ec-")


def _Log(sink, msg):
    if sink is not None and hasattr(sink, "OnLogLine"):
        sink.OnLogLine(msg)


def _Progress(sink, pct):
    # Reutilise la barre de progression MODULE de NKCode (index/total).
    if sink is not None and hasattr(sink, "OnFileDone"):
        sink.OnFileDone("llvm-mingw", int(pct), 100, "", True, False)


def IsInstalled(dest_root) -> bool:
    """True si le compilateur par defaut est deja present (marqueur .ok)."""
    d = Path(dest_root) / "llvm-mingw"
    return (d / ".ok").exists() and (d / "bin" / "clang++.exe").exists()


def InstallDefaultCompiler(dest_root: str, sink=None) -> int:
    """Telecharge + extrait llvm-mingw (x86_64 uniquement) dans
    `dest_root`/llvm-mingw. Retourne 0 si OK, 1 sinon. Idempotent."""
    dest_root = Path(dest_root)
    final = dest_root / "llvm-mingw"
    if IsInstalled(dest_root):
        _Log(sink, "[compilateur] deja installe : " + str(final))
        return 0
    dest_root.mkdir(parents=True, exist_ok=True)
    zip_path = dest_root / "llvm-mingw.zip.part"
    try:
        _Log(sink, "[compilateur] telechargement de Clang (llvm-mingw, ~140 Mo)...")
        if sink is not None and hasattr(sink, "OnFileTotal"):
            sink.OnFileTotal("llvm-mingw", 100)

        last = [-1]

        def Hook(blocks, bs, total):
            if total > 0:
                pct = min(99, blocks * bs * 100 // total)
                if pct != last[0]:
                    last[0] = pct
                    _Progress(sink, pct)
                    if pct % 10 == 0:
                        _Log(sink, f"[compilateur] telechargement... {pct}%")

        urllib.request.urlretrieve(LLVM_MINGW_URL, zip_path, reporthook=Hook)
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
        shutil.rmtree(tmp)
        zip_path.unlink(missing_ok=True)
        (final / ".ok").write_text("ok", encoding="utf-8")
        _Progress(sink, 100)
        _Log(sink, "[compilateur] Clang installe : " + str(final / "bin"))
        return 0
    except Exception as ex:  # reseau coupe, disque plein... -> message honnete
        _Log(sink, f"[compilateur] ECHEC : {ex}")
        try:
            zip_path.unlink(missing_ok=True)
        except Exception:
            pass
        return 1
