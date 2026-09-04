#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RuntimeDiag – dire POURQUOI un binaire n'a pas demarre.
AUTEUR : TEUGUIA TADJUIDJE Rodolf Séderis — Rihen

Mesure sur Nkentseu le 2026-09-04 : `NKMath_Tests.exe` sortait en 127 (vu de
bash ; 0xC0000135 vu de Windows) sans une ligne — `libstdc++-6.dll` introuvable
— alors que la suite etait verte. Un test qui ne trouve pas sa DLL et se tait
est le pire des verts : il passe pour un echec ordinaire, ou pour rien.

Ce module ne repare rien ; il NOMME. Il reconnait les codes de sortie qui
signifient « le chargeur n'a pas pu demarrer le programme », lit la table
d'import PE du binaire (sans dependance externe) et dit quelles DLL importees
ne sont trouvees ni a cote du binaire, ni sur le PATH utilise, ni dans les
repertoires systeme.
"""

import os
import struct
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence


class RuntimeDiag:
    STATUS_DLL_NOT_FOUND = 0xC0000135
    STATUS_ENTRYPOINT_NOT_FOUND = 0xC0000139
    STATUS_INVALID_IMAGE_FORMAT = 0xC000007B

    LOADER_CODES: Dict[int, str] = {
        STATUS_DLL_NOT_FOUND: "STATUS_DLL_NOT_FOUND",
        STATUS_ENTRYPOINT_NOT_FOUND: "STATUS_ENTRYPOINT_NOT_FOUND",
        STATUS_INVALID_IMAGE_FORMAT: "STATUS_INVALID_IMAGE_FORMAT",
    }

    # Les « API sets » (api-ms-win-*, ext-ms-*) n'existent pas comme fichiers :
    # le chargeur les resout par une table interne. Les chercher sur disque
    # produirait un faux « manquant » a chaque binaire UCRT.
    _VIRTUAL_PREFIXES = ("api-ms-win-", "ext-ms-")

    # ------------------------------------------------------------------
    @staticmethod
    def Unsigned32(code: int) -> int:
        return int(code) & 0xFFFFFFFF

    @classmethod
    def IsLoaderFailure(cls, code: int) -> bool:
        """Vrai si le code de sortie signifie « pas demarre » plutot que
        « demarre puis echoue » : NTSTATUS du chargeur Windows (aussi sous leur
        forme signee, telle que Python les rend), ou 127 — le code que bash et
        ld.so donnent quand le programme ou une bibliotheque partagee manque."""
        if code is None:
            return False
        return cls.Unsigned32(code) in cls.LOADER_CODES or int(code) == 127

    @classmethod
    def CodeName(cls, code: int) -> str:
        u = cls.Unsigned32(code)
        if u in cls.LOADER_CODES:
            return f"0x{u:08X} ({cls.LOADER_CODES[u]})"
        return str(code)

    # ------------------------------------------------------------------
    @staticmethod
    def PeImports(path: Path) -> List[str]:
        """Noms des DLL importees par un executable PE (32 ou 64 bits).
        Liste vide si le fichier n'est pas un PE lisible — jamais d'exception :
        un diagnostic qui plante vaut moins qu'un diagnostic absent."""
        try:
            data = Path(path).read_bytes()
            if data[:2] != b"MZ":
                return []
            pe_off = struct.unpack_from("<I", data, 0x3C)[0]
            if data[pe_off:pe_off + 4] != b"PE\0\0":
                return []
            coff = pe_off + 4
            n_sections = struct.unpack_from("<H", data, coff + 2)[0]
            opt_size = struct.unpack_from("<H", data, coff + 16)[0]
            opt = coff + 20
            magic = struct.unpack_from("<H", data, opt)[0]
            if magic == 0x20B:      # PE32+
                dd_off = opt + 112
            elif magic == 0x10B:    # PE32
                dd_off = opt + 96
            else:
                return []
            import_rva = struct.unpack_from("<I", data, dd_off + 8)[0]   # DataDirectory[1]
            if import_rva == 0:
                return []
            sections = []
            sec = opt + opt_size
            for i in range(n_sections):
                s = sec + i * 40
                vsize, vaddr, rsize, rptr = struct.unpack_from("<IIII", data, s + 8)
                sections.append((vaddr, max(vsize, rsize), rptr))

            def to_off(rva: int) -> Optional[int]:
                for vaddr, size, rptr in sections:
                    if vaddr <= rva < vaddr + size:
                        return rptr + (rva - vaddr)
                return None

            def cstr(off: int) -> str:
                end = data.find(b"\0", off)
                return data[off:end if end != -1 else off].decode("ascii", "replace")

            names: List[str] = []
            desc = to_off(import_rva)
            if desc is None:
                return []
            while desc + 20 <= len(data):
                name_rva = struct.unpack_from("<I", data, desc + 12)[0]
                if name_rva == 0:
                    break
                off = to_off(name_rva)
                if off is not None:
                    names.append(cstr(off))
                desc += 20
            return names
        except Exception:  # noqa: BLE001 — voir docstring
            return []

    @classmethod
    def SystemDirs(cls) -> List[str]:
        if sys.platform != "win32":
            return []
        root = os.environ.get("SystemRoot") or os.environ.get("WINDIR") or r"C:\Windows"
        return [os.path.join(root, "System32"), os.path.join(root, "SysWOW64"), root]

    @classmethod
    def MissingImports(cls, exe: Path, pathEnv: str) -> List[str]:
        """DLL importees par `exe` introuvables a cote de lui, sur `pathEnv`
        (la valeur de PATH REELLEMENT utilisee pour le lancer) et dans les
        repertoires systeme. Ne dit rien des dependances transitives."""
        exe = Path(exe)
        dirs = [str(exe.parent)] + [d for d in (pathEnv or "").split(os.pathsep) if d] + cls.SystemDirs()
        missing: List[str] = []
        for dll in cls.PeImports(exe):
            low = dll.lower()
            if low.startswith(cls._VIRTUAL_PREFIXES):
                continue
            if not any(os.path.isfile(os.path.join(d, dll)) for d in dirs):
                missing.append(dll)
        return missing

    # ------------------------------------------------------------------
    @classmethod
    def Explain(cls, code: int, exe: Path, pathEnv: str,
                prepended: Sequence[str] = ()) -> Optional[str]:
        """Texte a afficher quand `exe` n'a PAS demarre ; None pour tout autre
        echec (un test rouge est un echec ordinaire, il se dit tout seul)."""
        if not cls.IsLoaderFailure(code):
            return None
        exe = Path(exe)
        lines: List[str] = []
        u = cls.Unsigned32(code)
        if u in cls.LOADER_CODES:
            what = {
                cls.STATUS_DLL_NOT_FOUND: "a DLL it imports is missing",
                cls.STATUS_ENTRYPOINT_NOT_FOUND: "a DLL was found but lacks a symbol it needs (wrong version on PATH)",
                cls.STATUS_INVALID_IMAGE_FORMAT: "a DLL of the wrong architecture (32/64 bit) was found first on PATH",
            }[u]
            lines.append(f"'{exe.name}' did not start: exit code {cls.CodeName(code)} — {what}.")
        else:
            lines.append(f"'{exe.name}' did not start: exit code 127 — the loader could not run it "
                         f"(program or shared library missing).")

        imports = cls.PeImports(exe)
        if imports:
            missing = cls.MissingImports(exe, pathEnv)
            if missing:
                lines.append("Imported DLL(s) not found next to the binary, on PATH, nor in the system: "
                             + ", ".join(missing) + ".")
            else:
                non_system = [d for d in imports
                              if not d.lower().startswith(cls._VIRTUAL_PREFIXES)
                              and not any(os.path.isfile(os.path.join(s, d)) for s in cls.SystemDirs())]
                lines.append("Every directly imported DLL was found — suspect a transitive dependency of: "
                             + (", ".join(non_system) if non_system else "(none outside the system)") + ".")
        elif sys.platform != "win32":
            lines.append(f"Check the shared libraries it needs: ldd {exe}")

        if prepended:
            lines.append("Runtime search path prepended by Jenga: " + os.pathsep.join(prepended))
        else:
            lines.append("No runtime search path was prepended (--no-runtime-path, or no toolchain directory known).")
        lines.append("Fix: link the runtime statically (staticruntime(), or ldflags "
                     "-static-libstdc++ -static-libgcc on the toolchain), or ship the DLL next to the binary. "
                     "`jenga test --no-runtime-path` reproduces a user's environment.")
        return "\n".join(lines)
