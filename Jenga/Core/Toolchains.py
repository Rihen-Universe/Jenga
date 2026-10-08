#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Toolchains â€“ DÃ©tection automatique et gestion des toolchains.
Fournit des mÃ©thodes pour :
  - DÃ©tecter les compilateurs installÃ©s (MSVC, GCC, Clang, Android NDK, Emscripten, MinGW)
  - CrÃ©er des objets Toolchain correspondants
  - RÃ©soudre la toolchain Ã  utiliser pour une cible donnÃ©e
"""

import os
import sys
from pathlib import Path
from typing import List, Dict, Optional, Tuple, Any

from Jenga.Core.Api import Toolchain, CompilerFamily, TargetOS, TargetArch, TargetEnv
from ..Utils import Process
from .Platform import Platform
from .GlobalToolchains import GetJengaRoot


class ToolchainManager:
    """
    Gestionnaire global de toolchains.
    Peut Ãªtre instanciÃ© pour un workspace ou utilisÃ© statiquement.
    """

    def __init__(self, workspace: Optional[Any] = None):
        self.workspace = workspace
        self._detected: Dict[str, Toolchain] = {}
        self._cache: Dict[Tuple[TargetOS, TargetArch, Optional[TargetEnv]], Optional[str]] = {}

    def _GetCompilersRoot(self, workspace: Optional[Any] = None) -> Optional[Path]:
        wks = workspace or self.workspace
        if wks and getattr(wks, "location", ""):
            root = Path(wks.location).resolve() / ".jenga" / "compilers"
            if root.exists():
                return root
        global_root = GetJengaRoot() / ".jenga" / "compilers"
        return global_root if global_root.exists() else None

    def _CollectExtraBinaryPaths(self, workspace: Optional[Any] = None) -> List[str]:
        root = self._GetCompilersRoot(workspace)
        if not root:
            return []
        paths: List[str] = []
        candidates = [root, root / "bin"]
        for child in root.iterdir():
            if child.is_dir():
                candidates.append(child)
                candidates.append(child / "bin")
        for p in candidates:
            if p.exists() and p.is_dir():
                paths.append(str(p))
        # De-duplicate while preserving order.
        deduped: List[str] = []
        seen = set()
        for p in paths:
            if p in seen:
                continue
            seen.add(p)
            deduped.append(p)
        return deduped

    # ── Cache de DETECTION (duree de vie : le processus) ────────────────────
    #
    # Sonder un compilateur coute un lancement de processus. Ces sondes etaient
    # refaites POUR CHAQUE PROJET : sur un workspace de 22 projets dont aucun
    # n'avait change, 31 lancements de clang/gcc/vswhere pour redecouvrir a
    # chaque fois la meme chose.
    #
    # Le compilateur installe ne change pas pendant un build. On memorise donc
    # le resultat pour le PROCESSUS.
    _cacheRunnable: Dict[tuple, Optional[str]] = {}
    _cacheFamily: Dict[str, "CompilerFamily"] = {}

    # ── Et d'un lancement a l'autre, sous conditions (2.8.14) ────────────────
    # Mesure du 06/10/2026 sur un projet de cours : `jenga build` SANS rien a
    # faire durait 2,0 s, dont 1,0 s a relancer 12 compilateurs pour verifier
    # qu'ils repondent. Chaque « Construire » d'un IDE payait cette seconde.
    #
    # La crainte d'origine (« un cache sur disque survivrait a une installation
    # ou une desinstallation ») est tenue par la CLE, pas par l'absence de cache :
    #   - le chemin de l'executable, sa date et sa taille : une desinstallation
    #     (plus de fichier), une reinstallation ou une mise a jour invalident ;
    #   - une empreinte du PATH : une DLL devenue introuvable parce qu'un autre
    #     compilateur passe devant est le cas reel du diagnostic 0xC0000135 ;
    #   - 24 h au plus ;
    #   - SEULS LES SUCCES sont memorises : un compilateur qui echoue est
    #     re-sonde a chaque fois, sa reparation est vue aussitot.
    # JENGA_SONDES_SANS_CACHE=1 le coupe ; JENGA_SONDES_CACHE=<fichier> le deplace.
    _sondes: Optional[Dict[str, float]] = None
    _sondesModifiees: bool = False
    _SONDES_DUREE = 24 * 3600.0

    @staticmethod
    def _SondesFichier() -> Path:
        force = os.environ.get("JENGA_SONDES_CACHE")
        return Path(force) if force else Path.home() / ".jenga" / "cache" / "sondes_compilateurs.json"

    @staticmethod
    def _SondeCle(path: str, version_arg: str) -> Optional[str]:
        try:
            st = os.stat(path)
        except OSError:
            return None
        import hashlib
        empreinte = hashlib.sha1(os.environ.get("PATH", "").encode("utf-8", "replace")).hexdigest()[:16]
        return f"{os.path.normcase(os.path.abspath(path))}|{version_arg}|{st.st_mtime_ns}|{st.st_size}|{empreinte}"

    @staticmethod
    def _SondesCharger() -> Dict[str, float]:
        if ToolchainManager._sondes is None:
            ToolchainManager._sondes = {}
            if not os.environ.get("JENGA_SONDES_SANS_CACHE"):
                try:
                    import json
                    brut = json.loads(ToolchainManager._SondesFichier().read_text(encoding="utf-8"))
                    if isinstance(brut, dict):
                        ToolchainManager._sondes = {
                            str(k): v for k, v in brut.items()
                            if isinstance(v, (int, float))
                            or (isinstance(v, list) and len(v) == 2 and isinstance(v[0], (int, float)))}
                except (OSError, ValueError, TypeError):
                    pass  # absent ou illisible : on re-sonde, rien de plus
        return ToolchainManager._sondes

    @staticmethod
    def _SondeConnue(path: str, version_arg: str) -> bool:
        """Ce compilateur a-t-il deja repondu, dans le meme etat, depuis moins de 24 h ?"""
        if os.environ.get("JENGA_SONDES_SANS_CACHE"):
            return False
        cle = ToolchainManager._SondeCle(path, version_arg)
        if cle is None:
            return False
        import time
        quand = ToolchainManager._SondesCharger().get(cle)
        return isinstance(quand, (int, float)) and 0.0 <= time.time() - quand < ToolchainManager._SONDES_DUREE

    @staticmethod
    def _SondeNoter(path: str, version_arg: str) -> None:
        """Memorise un SUCCES (jamais un echec), et l'ecrit a la sortie du processus."""
        if os.environ.get("JENGA_SONDES_SANS_CACHE"):
            return
        cle = ToolchainManager._SondeCle(path, version_arg)
        if cle is None:
            return
        import time
        ToolchainManager._SondesCharger()[cle] = time.time()
        ToolchainManager._SondesMarquer()

    @staticmethod
    def _SondesMarquer() -> None:
        if not ToolchainManager._sondesModifiees:
            ToolchainManager._sondesModifiees = True
            import atexit
            atexit.register(ToolchainManager._SondesEcrire)

    @staticmethod
    def _FamilleConnue(path: str) -> Optional["CompilerFamily"]:
        """La famille deja lue de `--version`, meme cle que la sonde (executable, PATH, 24 h)."""
        if os.environ.get("JENGA_SONDES_SANS_CACHE"):
            return None
        cle = ToolchainManager._SondeCle(path, "famille")
        if cle is None:
            return None
        import time
        v = ToolchainManager._SondesCharger().get(cle)
        if isinstance(v, list) and 0.0 <= time.time() - v[0] < ToolchainManager._SONDES_DUREE:
            try:
                return CompilerFamily[str(v[1])]
            except KeyError:
                return None
        return None

    @staticmethod
    def _FamilleNoter(path: str, famille: "CompilerFamily") -> None:
        if os.environ.get("JENGA_SONDES_SANS_CACHE"):
            return
        cle = ToolchainManager._SondeCle(path, "famille")
        if cle is None:
            return
        import time
        ToolchainManager._SondesCharger()[cle] = [time.time(), famille.name]
        ToolchainManager._SondesMarquer()

    @staticmethod
    def _SondesEcrire() -> None:
        if not ToolchainManager._sondesModifiees or ToolchainManager._sondes is None:
            return
        try:
            import json
            import time
            maintenant = time.time()
            vivantes = {k: v for k, v in ToolchainManager._sondes.items()
                        if 0.0 <= maintenant - (v[0] if isinstance(v, list) else v) < ToolchainManager._SONDES_DUREE}
            fichier = ToolchainManager._SondesFichier()
            fichier.parent.mkdir(parents=True, exist_ok=True)
            provisoire = fichier.with_suffix(".tmp")
            provisoire.write_text(json.dumps(vivantes, indent=0), encoding="utf-8")
            os.replace(provisoire, fichier)
            ToolchainManager._sondesModifiees = False
        except OSError:
            pass  # un cache qui ne s'ecrit pas ne doit jamais faire echouer un build

    # ── Ce que la detection a essaye, candidat par candidat ─────────────────
    # « No suitable toolchain found » ne disait ni ou Jenga avait cherche, ni
    # pourquoi il avait rejete ce qu'il avait trouve. Cas reel (2.8.2) : un PATH
    # pointant sur C:\msys64\ucrt64\x86_64-w64-mingw32\bin (binutils seuls) au
    # lieu de C:\msys64\ucrt64\bin ; clang et g++ repondaient dans le terminal
    # MSYS2, et rien ne permettait de comprendre pourquoi Jenga ne les voyait
    # pas. Chaque sonde note ici son resultat ; DescribeDetection() le restitue.
    _diagnostics: Dict[str, str] = {}

    # Dossiers MSYS2 standards, fouilles APRES le PATH (Windows seulement).
    # Meme ordre que RegisterJengaGlobalToolchains() : ucrt64 d'abord (le
    # defaut recommande par MSYS2), puis clang64, puis mingw64.
    # Point d'extension : une autre racine se donne par MSYS2_ROOT.
    @staticmethod
    def _WindowsFallbackDirs() -> List[Path]:
        if sys.platform != "win32":
            return []
        racines = []
        env_root = os.environ.get("MSYS2_ROOT", "").strip()
        if env_root:
            racines.append(Path(env_root))
        racines.append(Path(r"C:\msys64"))
        dossiers: List[Path] = []
        for r in racines:
            for sous in ("ucrt64", "clang64", "mingw64"):
                d = r / sous / "bin"
                if d.is_dir() and d not in dossiers:
                    dossiers.append(d)
        return dossiers

    @staticmethod
    def _FindExecutable(name: str) -> Optional[str]:
        """PATH d'abord ; sinon, sous Windows, les dossiers MSYS2 standards."""
        path = Process.Which(name)
        if path:
            return path
        for d in ToolchainManager._WindowsFallbackDirs():
            candidat = d / (name if name.lower().endswith(".exe") else name + ".exe")
            if candidat.is_file():
                return str(candidat)
        return None

    @staticmethod
    def _ToolNextTo(compiler_path: Optional[str], names: List[str]) -> Optional[str]:
        """Outil (ar, ld...) du MEME dossier que le compilateur retenu, sinon PATH/MSYS2.

        Un clang de ucrt64 associe a l'ar d'une autre installation trouvee plus
        haut dans le PATH produit des archives que son editeur de liens peut
        refuser. On prend donc d'abord l'outil qui a ete livre avec lui.
        """
        if compiler_path:
            dossier = Path(compiler_path).parent
            for name in names:
                for nom in (name, name + ".exe"):
                    p = dossier / nom
                    if p.is_file():
                        return str(p)
        for name in names:
            p = ToolchainManager._FindExecutable(name)
            if p:
                return p
        return None

    @staticmethod
    def _FirstRunnable(candidates: List[str], version_arg: str = "--version") -> Optional[str]:
        cle = (tuple(candidates), version_arg)
        if cle in ToolchainManager._cacheRunnable:
            return ToolchainManager._cacheRunnable[cle]
        resultat = None
        diag = ToolchainManager._diagnostics
        for name in candidates:
            path = ToolchainManager._FindExecutable(name)
            if not path:
                replis = ToolchainManager._WindowsFallbackDirs()
                diag.setdefault(name, "not found in PATH"
                                + (" nor in " + ", ".join(str(d) for d in replis) if replis else ""))
                continue
            origine = "" if Process.Which(name) else " (not in PATH, found in MSYS2 folder)"
            if ToolchainManager._SondeConnue(path, version_arg):
                diag[name] = f"OK: {path}{origine} (sonde memorisee)"
                resultat = path
                break
            try:
                probe = Process.ExecuteCommand([path, version_arg], captureOutput=True, silent=True)
                if probe.returnCode == 0:
                    ToolchainManager._SondeNoter(path, version_arg)
                    diag[name] = f"OK: {path}{origine}"
                    resultat = path
                    break
                rc = probe.returnCode
                # 0xC0000135 : STATUS_DLL_NOT_FOUND, vu signe ou non signe.
                dll = (" -- a DLL is missing (another compiler earlier in PATH?)"
                       if rc in (3221225781, -1073741515) else "")
                diag[name] = f"found {path}{origine}, but '{name} {version_arg}' failed (exit {rc}){dll}"
            except Exception as exc:
                diag[name] = f"found {path}{origine}, but could not run it: {exc}"
                continue
        ToolchainManager._cacheRunnable[cle] = resultat
        return resultat

    @staticmethod
    def DescribeDetection() -> str:
        """Ce que la detection a vu : a joindre a tout refus faute de toolchain."""
        import platform as _pf
        lignes = [f"  host: {_pf.system()} (Python {sys.executable}, sys.platform={sys.platform})"]
        for name, etat in ToolchainManager._diagnostics.items():
            lignes.append(f"  {name}: {etat}")
        if sys.platform == "win32":
            lignes.append("  -> Add the folder that CONTAINS your compiler to PATH (e.g. C:\\msys64\\ucrt64\\bin,"
                          " not ...\\x86_64-w64-mingw32\\bin), then open a NEW terminal.")
        return "\n".join(lignes)

    @staticmethod
    def _AddToolchainIfValid(toolchains: Dict[str, Toolchain], tc: Optional[Toolchain]) -> None:
        if tc is None or not tc.name:
            return
        if tc.name not in toolchains:
            toolchains[tc.name] = tc

    @staticmethod
    def _CloneToolchainWithName(base: Toolchain, name: str) -> Toolchain:
        clone = Toolchain(
            name=name,
            compilerFamily=base.compilerFamily,
            targetOs=base.targetOs,
            targetArch=base.targetArch,
            targetEnv=base.targetEnv,
            targetTriple=base.targetTriple,
            sysroot=base.sysroot,
            ccPath=base.ccPath,
            cxxPath=base.cxxPath,
            arPath=base.arPath,
            ldPath=base.ldPath,
            stripPath=base.stripPath,
            ranlibPath=base.ranlibPath,
            asmPath=base.asmPath,
            toolchainDir=base.toolchainDir,
        )
        clone.defines = list(base.defines or [])
        clone.cflags = list(base.cflags or [])
        clone.cxxflags = list(base.cxxflags or [])
        clone.asmflags = list(base.asmflags or [])
        clone.ldflags = list(base.ldflags or [])
        clone.arflags = list(base.arflags or [])
        clone.frameworks = list(base.frameworks or [])
        clone.frameworkPaths = list(base.frameworkPaths or [])
        clone.perConfigFlags = dict(base.perConfigFlags or {})
        return clone

    # -----------------------------------------------------------------------
    # DÃ©tection des compilateurs hÃ´tes â€“ prioritÃ© : Clang > GCC > MSVC
    # -----------------------------------------------------------------------
    @staticmethod
    def _BuildHostToolchain(name: str, cc_path: str, cxx_candidates: List[str]) -> Optional[Toolchain]:
        if not cc_path:
            return None
        cxx_path = ToolchainManager._FirstRunnable(cxx_candidates) or cc_path
        if Platform.GetHostOS() == TargetOS.MACOS:
            ar_path = Process.Which("ar") or Process.Which("llvm-ar")
        else:
            ar_path = Process.Which("llvm-ar") or Process.Which("ar")
        ld_path = Process.Which("ld") or cxx_path or cc_path

        family = ToolchainManager._DetectCompilerFamily(cc_path)
        tc = Toolchain(
            name=name,
            compilerFamily=family,
            ccPath=cc_path,
            cxxPath=cxx_path,
            arPath=ar_path,
            ldPath=ld_path,
        )
        tc.targetOs = Platform.GetHostOS()
        tc.targetArch = Platform.GetHostArchitecture()
        tc.targetEnv = Platform.GetHostEnvironment()

        if sys.platform == "win32":
            if family == CompilerFamily.GCC:
                tc.targetEnv = TargetEnv.MINGW
            elif family == CompilerFamily.CLANG:
                cc_low = (cc_path or "").lower()
                if any(token in cc_low for token in ("msys64", "mingw", "ucrt")):
                    tc.targetEnv = TargetEnv.MINGW
                elif Process.Which("clang-cl"):
                    tc.targetEnv = TargetEnv.MSVC
                else:
                    tc.targetEnv = TargetEnv.MINGW
            elif family == CompilerFamily.MSVC:
                tc.targetEnv = TargetEnv.MSVC
        return tc

    @staticmethod
    def DetectHostClang() -> Optional[Toolchain]:
        cc_path = ToolchainManager._FirstRunnable(["clang", "clang-18", "clang-17", "cc"])
        if not cc_path:
            return None
        family = ToolchainManager._DetectCompilerFamily(cc_path)
        if family not in (CompilerFamily.CLANG, CompilerFamily.APPLE_CLANG):
            return None
        return ToolchainManager._BuildHostToolchain(
            name=f"host-{family.value}",
            cc_path=cc_path,
            cxx_candidates=["clang++", "c++"],
        )

    @staticmethod
    def DetectHostGCC() -> Optional[Toolchain]:
        cc_path = ToolchainManager._FirstRunnable(["gcc"])
        if not cc_path:
            return None
        family = ToolchainManager._DetectCompilerFamily(cc_path)
        if family != CompilerFamily.GCC:
            return None
        return ToolchainManager._BuildHostToolchain(
            name="host-gcc",
            cc_path=cc_path,
            cxx_candidates=["g++", "c++"],
        )

    @staticmethod
    def DetectHostCC() -> Optional[Toolchain]:
        """Detect the default host C/C++ toolchain."""
        return (
            ToolchainManager.DetectHostClang()
            or ToolchainManager.DetectHostGCC()
            or ToolchainManager._BuildHostToolchain(
                name="host-cc",
                cc_path=ToolchainManager._FirstRunnable(["cc", "zig-cc"]) or "",
                cxx_candidates=["c++", "zig-c++"],
            )
        )
    @staticmethod
    def DetectMSVC() -> Optional[Toolchain]:
        """Detect MSVC from the active environment or Visual Studio installation."""
        if sys.platform != "win32":
            return None

        cl_path = ToolchainManager._FirstRunnable(["cl", "cl.exe"], version_arg="/?")
        link_path = Process.Which("link") or Process.Which("link.exe")
        lib_path = Process.Which("lib") or Process.Which("lib.exe")

        if cl_path:
            tc = Toolchain(
                name="msvc",
                compilerFamily=CompilerFamily.MSVC,
                ccPath=cl_path,
                cxxPath=cl_path,
                arPath=lib_path,
                ldPath=link_path or cl_path,
                toolchainDir=str(Path(cl_path).parent),
            )
            tc.targetOs = TargetOS.WINDOWS
            tc.targetArch = Platform.GetHostArchitecture()
            tc.targetEnv = TargetEnv.MSVC
            return tc

        vswhere_path = Path(os.environ.get("ProgramFiles(x86)", "C:/Program Files (x86)")) / "Microsoft Visual Studio" / "Installer" / "vswhere.exe"
        if not vswhere_path.exists():
            return None

        try:
            install_root = Process.Capture([str(vswhere_path), "-latest", "-property", "installationPath"]).strip()
        except Exception:
            return None

        if not install_root:
            return None

        install_path = Path(install_root)
        msvc_root = install_path / "VC" / "Tools" / "MSVC"
        if not msvc_root.exists():
            return None

        host_arch = Platform.GetHostArchitecture()
        host_bin = "Hostx64/x64" if host_arch == TargetArch.X86_64 else "Hostx86/x86"

        versions = sorted([p for p in msvc_root.iterdir() if p.is_dir()], reverse=True)
        for version_dir in versions:
            bin_dir = version_dir / "bin" / Path(host_bin)
            cl_candidate = bin_dir / "cl.exe"
            if not cl_candidate.exists():
                continue
            link_candidate = bin_dir / "link.exe"
            lib_candidate = bin_dir / "lib.exe"
            tc = Toolchain(
                name="msvc",
                compilerFamily=CompilerFamily.MSVC,
                ccPath=str(cl_candidate),
                cxxPath=str(cl_candidate),
                arPath=str(lib_candidate) if lib_candidate.exists() else None,
                ldPath=str(link_candidate) if link_candidate.exists() else str(cl_candidate),
                toolchainDir=str(version_dir),
            )
            tc.targetOs = TargetOS.WINDOWS
            tc.targetArch = host_arch
            tc.targetEnv = TargetEnv.MSVC
            return tc

        return None


    @staticmethod
    def DetectClangOnWindows() -> Optional[Toolchain]:
        """DÃ©tecte Clang sur Windows. clang-cl -> MSVC ABI, clang -> MinGW ABI."""
        if sys.platform != "win32":
            return None
        # Prefer clang/clang++ MinGW-style toolchain (MSYS2/UCRT) when present.
        # (2.8.16) CLANG_MINGW_CC / CLANG_MINGW_CXX passent DEVANT le PATH : un hote
        # (NKCode) qui a choisi son compilateur le dit par la, comme pour
        # GlobalToolchains. Mesure du 08/10 : avec le lanceur de NKCode (llvm-mingw en
        # tete du PATH), un projet lie a un kit compile par le clang de msys64 ne se
        # lie qu'avec ces deux variables ; msys64 ajoute au PATH ne suffit pas.
        env_cc = os.environ.get("CLANG_MINGW_CC", "")
        env_cxx = os.environ.get("CLANG_MINGW_CXX", "")
        if env_cc and env_cxx and Path(env_cc).exists() and Path(env_cxx).exists():
            clang_path, clangpp_path = env_cc, env_cxx
        else:
            clang_path = ToolchainManager._FirstRunnable(["clang"])
            clangpp_path = ToolchainManager._FirstRunnable(["clang++"])
        if clang_path and clangpp_path:
            tc = Toolchain(
                name="clang-mingw",
                compilerFamily=CompilerFamily.CLANG,
                ccPath=clang_path,
                cxxPath=clangpp_path,
                arPath=ToolchainManager._ToolNextTo(clang_path, ["llvm-ar", "ar"]),
                ldPath=clangpp_path,
            )
            tc.targetOs = TargetOS.WINDOWS
            tc.targetArch = Platform.GetHostArchitecture()
            tc.targetEnv = TargetEnv.MINGW
            return tc

        clang_cl_path = ToolchainManager._FirstRunnable(["clang-cl"], version_arg="/?")
        if clang_cl_path:
            tc = Toolchain(
                name="clang-cl",
                compilerFamily=CompilerFamily.CLANG,
                ccPath=clang_cl_path,
                cxxPath=clang_cl_path,
                arPath=Process.Which("llvm-ar") or Process.Which("ar"),
                ldPath=Process.Which("lld-link") or clang_cl_path,
            )
            tc.targetOs = TargetOS.WINDOWS
            tc.targetArch = Platform.GetHostArchitecture()
            tc.targetEnv = TargetEnv.MSVC
            return tc
        return None

    @staticmethod
    def DetectMinGW() -> Optional[Toolchain]:
        """DÃ©tecte MinGW-w64 (gcc/g++ sous Windows)."""
        if sys.platform != "win32":
            return None
        gcc_path = ToolchainManager._FirstRunnable(["x86_64-w64-mingw32-gcc", "gcc"])
        if not gcc_path:
            return None
        if ToolchainManager._DetectCompilerFamily(gcc_path) != CompilerFamily.GCC:
            return None
        gpp_path = ToolchainManager._FirstRunnable(["x86_64-w64-mingw32-g++", "g++"])
        ar_path = ToolchainManager._ToolNextTo(gcc_path, ["x86_64-w64-mingw32-ar", "ar"])
        tc = Toolchain(
            name="mingw",
            compilerFamily=CompilerFamily.GCC,
            ccPath=gcc_path,
            cxxPath=gpp_path or gcc_path,
            arPath=ar_path,
            ldPath=ToolchainManager._ToolNextTo(gcc_path, ["ld"]) or gcc_path,
        )
        tc.targetOs = TargetOS.WINDOWS
        tc.targetArch = Platform.GetHostArchitecture()
        tc.targetEnv = TargetEnv.MINGW
        return tc

    # ------------------------------------------------------------------
    # (2.8.17) LA BIBLIOTHEQUE C++ D'UN COMPILATEUR, ET UNE CHAINE PAR INSTALLATION
    #
    # « clang-mingw » ne dit pas QUEL clang : celui de MSYS2 ucrt64 lie libstdc++,
    # llvm-mingw et MSYS2 clang64 lient libc++. Des bibliotheques compilees avec
    # l'une ne se lient pas avec l'autre (mesure du 08/10/2026 : un kit fait avec le
    # clang de msys64, lie par llvm-mingw : 600 symboles « std::__cxx11 » introuvables).
    # Chaque compilateur installe recoit donc AUSSI une chaine a son nom, que
    # --toolchain designe sans ambiguite, et dont on sait dire la bibliotheque C++.
    # ------------------------------------------------------------------
    @staticmethod
    def PathAvecLeCompilateurEnTete(compilateur: str, path: Optional[str] = None) -> str:
        # Le PATH dans lequel un compilateur doit tourner : SON dossier d'abord.
        # Mesure du 08/10/2026 : le g++ de MSYS2, lance avec le bin/ de llvm-mingw en tete
        # du PATH (ce que fait un IDE qui embarque son compilateur), sort en erreur sans un
        # mot -- son cc1plus charge les DLL d'un autre. Un compilateur designe par son
        # chemin complet travaille avec les DLL de sa propre installation.
        actuel = os.environ.get("PATH", "") if path is None else path
        chemin = str(compilateur or "")
        if not chemin or not os.path.isabs(chemin):
            return actuel
        dossier = os.path.dirname(chemin)
        morceaux = [m for m in actuel.split(os.pathsep) if m]
        if morceaux and os.path.normcase(os.path.normpath(morceaux[0])) == os.path.normcase(os.path.normpath(dossier)):
            return actuel
        reste = [m for m in morceaux
                 if os.path.normcase(os.path.normpath(m)) != os.path.normcase(os.path.normpath(dossier))]
        return os.pathsep.join([dossier] + reste)

    @staticmethod
    def StdlibDepuisMacros(texte: str) -> str:
        # Ce que `<compilateur> -dM -E` dit, sur un fichier qui inclut <version>.
        if "_LIBCPP_VERSION" in texte:
            return "libc++"
        if "__GLIBCXX__" in texte:
            return "libstdc++"
        if "_MSVC_STL_VERSION" in texte or "_CPPLIB_VER" in texte:
            return "msvc-stl"
        return ""

    @staticmethod
    def StdlibOf(cxx_path: str) -> str:
        # « libc++ », « libstdc++ », « msvc-stl », ou vide si on ne sait pas.
        # Demande au compilateur lui-meme (les dossiers ne prouvent rien : MSYS2 ucrt64
        # peut avoir les deux installees). Memorise 24 h avec les autres sondes.
        if not cxx_path:
            return ""
        chemin = str(cxx_path)
        if not os.path.isfile(chemin):
            trouve = ToolchainManager._FindExecutable(chemin)
            if not trouve:
                return ""
            chemin = trouve
        import time
        cle = ToolchainManager._SondeCle(chemin, "stdlib")
        if cle and not os.environ.get("JENGA_SONDES_SANS_CACHE"):
            v = ToolchainManager._SondesCharger().get(cle)
            if isinstance(v, list) and 0.0 <= time.time() - v[0] < ToolchainManager._SONDES_DUREE:
                return str(v[1])
        resultat = ""
        try:
            import subprocess
            drapeaux = 0x08000000 if sys.platform == "win32" else 0  # CREATE_NO_WINDOW
            env = dict(os.environ)
            env["PATH"] = ToolchainManager.PathAvecLeCompilateurEnTete(chemin)
            r = subprocess.run([chemin, "-x", "c++", "-dM", "-E", "-"], input="#include <version>\n",
                               capture_output=True, text=True, timeout=20, creationflags=drapeaux, env=env)
            if r.returncode == 0:
                resultat = ToolchainManager.StdlibDepuisMacros(r.stdout or "")
        except Exception:
            resultat = ""
        if resultat and cle and not os.environ.get("JENGA_SONDES_SANS_CACHE"):
            ToolchainManager._SondesCharger()[cle] = [time.time(), resultat]
            ToolchainManager._SondesMarquer()
        return resultat

    @staticmethod
    def _ChaineGnuWindows(name: str, cc: Path, cxx: Path, gcc: bool) -> Optional[Toolchain]:
        if not (cc.is_file() and cxx.is_file()):
            return None
        if not ToolchainManager._FirstRunnable([str(cxx)]):
            return None  # present mais ne demarre pas : on ne le propose pas
        tc = Toolchain(
            name=name,
            compilerFamily=CompilerFamily.GCC if gcc else CompilerFamily.CLANG,
            ccPath=str(cc),
            cxxPath=str(cxx),
            arPath=ToolchainManager._ToolNextTo(str(cc), ["ar"] if gcc else ["llvm-ar", "ar"]),
            ldPath=(ToolchainManager._ToolNextTo(str(cc), ["ld"]) or str(cxx)) if gcc else str(cxx),
        )
        tc.targetOs = TargetOS.WINDOWS
        tc.targetArch = Platform.GetHostArchitecture()
        tc.targetEnv = TargetEnv.MINGW
        return tc

    @staticmethod
    def DetectWindowsGnuInstallations() -> List[Toolchain]:
        # Une chaine PAR compilateur installe : msys2-ucrt64-clang, msys2-ucrt64-gcc,
        # msys2-clang64, msys2-mingw64-clang, msys2-mingw64-gcc, llvm-mingw.
        if sys.platform != "win32":
            return []
        trouvees: List[Toolchain] = []
        for d in ToolchainManager._WindowsFallbackDirs():
            sous = d.parent.name.lower()  # ucrt64, clang64, mingw64
            nom_clang = "msys2-clang64" if sous == "clang64" else f"msys2-{sous}-clang"
            tc = ToolchainManager._ChaineGnuWindows(nom_clang, d / "clang.exe", d / "clang++.exe", False)
            if tc:
                trouvees.append(tc)
            if sous != "clang64":
                tc = ToolchainManager._ChaineGnuWindows(f"msys2-{sous}-gcc", d / "gcc.exe", d / "g++.exe", True)
                if tc:
                    trouvees.append(tc)
        # llvm-mingw : designe (LLVM_MINGW_BIN), embarque (JENGA_COMPILERS_DIR), ou dans le PATH.
        candidats: List[Path] = []
        for v in (os.environ.get("LLVM_MINGW_BIN", ""),):
            if v.strip():
                candidats.append(Path(v.strip()))
        racine = os.environ.get("JENGA_COMPILERS_DIR", "").strip()
        if racine:
            candidats.append(Path(racine) / "llvm-mingw" / "bin")
        for morceau in os.environ.get("PATH", "").split(os.pathsep):
            if morceau.strip():
                candidats.append(Path(morceau.strip()))
        for d in candidats:
            try:
                if not (d / "x86_64-w64-mingw32-clang++.exe").is_file():
                    continue
            except OSError:
                continue
            cc = d / "clang.exe"
            cxx = d / "clang++.exe"
            if not cc.is_file():
                cc, cxx = d / "x86_64-w64-mingw32-clang.exe", d / "x86_64-w64-mingw32-clang++.exe"
            tc = ToolchainManager._ChaineGnuWindows("llvm-mingw", cc, cxx, False)
            if tc:
                trouvees.append(tc)
                break
        return trouvees

    @staticmethod
    def DescribeCompiler(tc: Toolchain) -> Tuple[str, str]:
        # (chemin du compilateur C++, bibliotheque C++) d'une chaine ; vides si sans objet.
        cxx = str(getattr(tc, "cxxPath", "") or getattr(tc, "ccPath", "") or "")
        if not cxx:
            return "", ""
        chemin = cxx if os.path.isfile(cxx) else (ToolchainManager._FindExecutable(cxx) or "")
        if not chemin:
            return cxx, ""
        famille = getattr(tc, "compilerFamily", None)
        if famille not in (CompilerFamily.CLANG, CompilerFamily.GCC, CompilerFamily.APPLE_CLANG):
            return chemin, ""
        if getattr(tc, "targetOs", None) not in (TargetOS.WINDOWS, TargetOS.LINUX, TargetOS.MACOS):
            return chemin, ""
        if getattr(tc, "targetOs", None) != Platform.GetHostOS():
            return chemin, ""  # une chaine croisee : son <version> n'est pas celui de l'hote
        return chemin, ToolchainManager.StdlibOf(chemin)

    @staticmethod
    def DetectCrossWindows() -> Optional[Toolchain]:
        """
        DÃ©tecte une toolchain de cross-compilation Windows depuis un hÃ´te non-Windows.
        PrioritÃ© :
          1) MinGW-w64 GCC (x86_64-w64-mingw32-*)
          2) Clang avec --target=x86_64-w64-windows-gnu
        """
        if sys.platform == "win32":
            return None

        # 1) GNU MinGW cross toolchain (le plus fiable pour link/runtime).
        gcc_path = Process.Which("x86_64-w64-mingw32-gcc")
        gpp_path = Process.Which("x86_64-w64-mingw32-g++")
        if gcc_path and gpp_path:
            tc = Toolchain(
                name="mingw",
                compilerFamily=CompilerFamily.GCC,
                ccPath=gcc_path,
                cxxPath=gpp_path,
                arPath=Process.Which("x86_64-w64-mingw32-ar") or Process.Which("ar"),
                ldPath=gpp_path,
            )
            tc.targetOs = TargetOS.WINDOWS
            tc.targetArch = TargetArch.X86_64
            tc.targetEnv = TargetEnv.MINGW
            tc.targetTriple = "x86_64-w64-mingw32"
            return tc

        # 2) Clang cross (si le target GNU Windows est supportÃ©).
        clang_path = Process.Which("clang")
        clangxx_path = Process.Which("clang++")
        if clang_path and clangxx_path:
            for triple in ("x86_64-w64-windows-gnu", "x86_64-pc-windows-gnu"):
                test_cmd = [clang_path, f"--target={triple}", "-c", "-x", "c", "-", "-o", os.devnull]
                # Essai de compilation memorise comme une sonde (meme cle, meme duree).
                if not ToolchainManager._SondeConnue(clang_path, f"cible:{triple}"):
                    try:
                        result = Process.ExecuteCommand(
                            test_cmd,
                            captureOutput=True,
                            input="int main(){return 0;}\n",
                            silent=True,
                        )
                    except Exception:
                        continue
                    if result.returnCode != 0:
                        continue
                    ToolchainManager._SondeNoter(clang_path, f"cible:{triple}")

                tc = Toolchain(
                    name="clang-mingw",
                    compilerFamily=CompilerFamily.CLANG,
                    ccPath=clang_path,
                    cxxPath=clangxx_path,
                    arPath=Process.Which("llvm-ar") or Process.Which("x86_64-w64-mingw32-ar") or Process.Which("ar"),
                    ldPath=clangxx_path,
                )
                tc.targetOs = TargetOS.WINDOWS
                tc.targetArch = TargetArch.X86_64
                tc.targetEnv = TargetEnv.MINGW
                tc.targetTriple = triple
                tc.cflags.append(f"--target={triple}")
                tc.cxxflags.append(f"--target={triple}")
                tc.ldflags.append(f"--target={triple}")
                return tc

        return None

    @staticmethod
    def _DetectCompilerFamily(compiler_path: str) -> CompilerFamily:
        """Famille du compilateur, deduite de --version. MEMORISEE.

        La famille d'un binaire donne ne change pas pendant un build, et
        l'interroger coute un lancement de processus a chaque appel.
        """
        if compiler_path in ToolchainManager._cacheFamily:
            return ToolchainManager._cacheFamily[compiler_path]
        famille = ToolchainManager._FamilleConnue(compiler_path)
        if famille is None:
            ToolchainManager._familleLue = False
            famille = ToolchainManager._DetectCompilerFamilyImpl(compiler_path)
            # Seule une famille LUE dans la sortie est memorisee : le repli « GCC »
            # d'un compilateur qui n'a pas repondu ne doit pas durer 24 h.
            if ToolchainManager._familleLue:
                ToolchainManager._FamilleNoter(compiler_path, famille)
        ToolchainManager._cacheFamily[compiler_path] = famille
        return famille

    _familleLue: bool = False

    @staticmethod
    def _DetectCompilerFamilyImpl(compiler_path: str) -> CompilerFamily:
        try:
            out = Process.Capture([compiler_path, "--version"])
            out_lower = out.lower()
            ToolchainManager._familleLue = True
            if "clang" in out_lower:
                if "apple" in out_lower:
                    return CompilerFamily.APPLE_CLANG
                return CompilerFamily.CLANG
            if "zig" in out_lower:
                return CompilerFamily.CLANG
            if "gcc" in out_lower or "g++" in out_lower:
                return CompilerFamily.GCC
            if "msvc" in out_lower or "microsoft" in out_lower:
                return CompilerFamily.MSVC
            if "emscripten" in out_lower:
                return CompilerFamily.EMSCRIPTEN
            ToolchainManager._familleLue = False
        except:
            pass
        return CompilerFamily.GCC

    @staticmethod
    def DetectAndroidNDK(ndkPath: Optional[Path] = None) -> Optional[Toolchain]:
        """DÃ©tecte le NDK Android et crÃ©e une toolchain gÃ©nÃ©rique."""
        if ndkPath is None:
            candidates = []
            if "ANDROID_NDK_ROOT" in os.environ:
                candidates.append(Path(os.environ["ANDROID_NDK_ROOT"]))
            if "ANDROID_NDK_HOME" in os.environ:
                candidates.append(Path(os.environ["ANDROID_NDK_HOME"]))
            if "ANDROID_HOME" in os.environ:
                candidates.append(Path(os.environ["ANDROID_HOME"]) / "ndk-bundle")
            if sys.platform == "win32":
                candidates.append(Path("C:/Program Files/Android/NDK"))
            elif sys.platform == "darwin":
                candidates.append(Path("~/Library/Android/sdk/ndk-bundle").expanduser())
            else:
                candidates.append(Path("~/Android/Sdk/ndk-bundle").expanduser())
            if "JENGA_COMPILERS_DIR" in os.environ:
                root = Path(os.environ["JENGA_COMPILERS_DIR"])
                candidates.append(root / "android" / "ndk")
                sdk_ndk = root / "android" / "sdk" / "ndk"
                if sdk_ndk.exists():
                    for version in sorted(sdk_ndk.iterdir(), reverse=True):
                        candidates.append(version)
            for cand in candidates:
                if cand and cand.exists():
                    ndkPath = cand
                    break
        if not ndkPath or not ndkPath.exists():
            return None
        llvm_dir = None
        for p in ndkPath.glob("toolchains/llvm/prebuilt/*"):
            if p.is_dir():
                llvm_dir = p
                break
        if not llvm_dir:
            return None
        tc = Toolchain(
            name="android-ndk",
            compilerFamily=CompilerFamily.ANDROID_NDK,
            toolchainDir=str(llvm_dir),
            ccPath=str(llvm_dir / "bin" / "clang"),
            cxxPath=str(llvm_dir / "bin" / "clang++"),
            arPath=str(llvm_dir / "bin" / "llvm-ar"),
            ldPath=str(llvm_dir / "bin" / "ld"),
            stripPath=str(llvm_dir / "bin" / "llvm-strip"),
            ranlibPath=str(llvm_dir / "bin" / "llvm-ranlib"),
        )
        tc.targetOs = TargetOS.ANDROID
        tc.targetArch = TargetArch.ARM64
        tc.targetEnv = TargetEnv.ANDROID
        return tc

    @staticmethod
    def DetectEmscripten(emsdkPath: Optional[Path] = None) -> Optional[Toolchain]:
        """DÃ©tecte Emscripten SDK."""
        emcc_from_path = Process.Which("emcc")
        emcc_direct = Path(emcc_from_path) if emcc_from_path else None
        if emsdkPath is None:
            if emcc_direct:
                # Typical layouts:
                # - <emsdk>/upstream/emscripten/emcc(.bat)
                # - <emsdk>/emcc(.bat)
                parent = emcc_direct.parent
                if parent.name.lower() == "emscripten" and parent.parent.name.lower() == "upstream":
                    emsdkPath = parent.parent.parent
                else:
                    emsdkPath = parent.parent
            else:
                if sys.platform == "win32":
                    candidates = [Path("C:/emsdk")]
                else:
                    candidates = [Path.home() / "emsdk", Path("/opt/emsdk")]
                if "JENGA_COMPILERS_DIR" in os.environ:
                    candidates.append(Path(os.environ["JENGA_COMPILERS_DIR"]) / "emsdk")
                for cand in candidates:
                    if cand.exists():
                        emsdkPath = cand
                        break
        if not emsdkPath or not emsdkPath.exists():
            return None
        emcc_candidates = []
        if emcc_direct and emcc_direct.exists():
            emcc_candidates.append(emcc_direct)
        names = ["emcc", "emcc.bat", "emcc.cmd", "emcc.exe"]
        for name in names:
            emcc_candidates.extend([
                emsdkPath / name,
                emsdkPath / "emsdk" / name,
                emsdkPath / "upstream" / "emscripten" / name,
            ])
        emcc_path = None
        for cand in emcc_candidates:
            if cand.exists():
                emcc_path = cand
                break
        if not emcc_path:
            return None
        em_dir = emcc_path.parent
        empp_path = None
        emar_path = None
        for name in ("em++", "em++.bat", "em++.cmd", "em++.exe"):
            cand = em_dir / name
            if cand.exists():
                empp_path = cand
                break
        for name in ("emar", "emar.bat", "emar.cmd", "emar.exe"):
            cand = em_dir / name
            if cand.exists():
                emar_path = cand
                break
        tc = Toolchain(
            name="emscripten",
            compilerFamily=CompilerFamily.EMSCRIPTEN,
            toolchainDir=str(emsdkPath),
            ccPath=str(emcc_path),
            cxxPath=str(empp_path or (em_dir / "em++")),
            arPath=str(emar_path or (em_dir / "emar")),
        )
        tc.targetOs = TargetOS.WEB
        tc.targetArch = TargetArch.WASM32
        return tc

    @staticmethod
    def DetectCrossLinuxOnWindows() -> Optional[Toolchain]:
        """DÃ©tecte un cross-compilateur Linux sur Windows (GNU or clang --target)."""
        if sys.platform != "win32":
            return None

        # Prefer a real GNU cross toolchain if available.
        gcc_candidates = [
            ("x86_64-linux-gnu-gcc", "x86_64-linux-gnu-g++", "x86_64-linux-gnu-ar", "x86_64-unknown-linux-gnu"),
            ("x86_64-pc-linux-gnu-gcc", "x86_64-pc-linux-gnu-g++", "x86_64-pc-linux-gnu-ar", "x86_64-pc-linux-gnu"),
        ]
        for cc_name, cxx_name, ar_name, triple in gcc_candidates:
            gcc_path = Process.Which(cc_name)
            if not gcc_path:
                continue
            tc = Toolchain(
                name="gcc-cross-linux",
                compilerFamily=CompilerFamily.GCC,
                ccPath=gcc_path,
                cxxPath=Process.Which(cxx_name) or gcc_path,
                arPath=Process.Which(ar_name) or Process.Which("ar"),
                ldPath=Process.Which(cxx_name) or gcc_path,
            )
            tc.targetOs = TargetOS.LINUX
            tc.targetArch = TargetArch.X86_64
            tc.targetEnv = TargetEnv.GNU
            tc.targetTriple = triple
            return tc

        # Fallback: clang with Linux target triple (compile support check).
        clang_path = Process.Which("clang")
        clangxx_path = Process.Which("clang++")
        if clang_path and clangxx_path:
            triple = "x86_64-unknown-linux-gnu"
            test_cmd = [clang_path, f"--target={triple}", "-c", "-x", "c", "-", "-o", os.devnull]
            try:
                # Essai de compilation memorise comme une sonde (meme cle, meme duree).
                reussi = ToolchainManager._SondeConnue(clang_path, f"cible:{triple}")
                if not reussi:
                    result = Process.ExecuteCommand(test_cmd, captureOutput=True, input="int main(){return 0;}\n", silent=True)
                    reussi = result.returnCode == 0
                    if reussi:
                        ToolchainManager._SondeNoter(clang_path, f"cible:{triple}")
                if reussi:
                    tc = Toolchain(
                        name="clang-cross-linux",
                        compilerFamily=CompilerFamily.CLANG,
                        ccPath=clang_path,
                        cxxPath=clangxx_path,
                        arPath=Process.Which("llvm-ar") or Process.Which("ar"),
                        ldPath=clangxx_path,
                    )
                    tc.targetOs = TargetOS.LINUX
                    tc.targetArch = TargetArch.X86_64
                    tc.targetEnv = TargetEnv.GNU
                    tc.targetTriple = triple
                    tc.cflags.append(f"--target={triple}")
                    tc.cxxflags.append(f"--target={triple}")
                    tc.ldflags.append(f"--target={triple}")
                    return tc
            except Exception:
                pass
        return None
    @staticmethod
    def _EnsureZigShims() -> Tuple[Optional[str], Optional[str], Optional[str]]:
        """Retourne (zig_cc, zig_cxx, zig_ar). Priorité aux shims déjà présents sur le
        PATH ; sinon, si `zig` natif est trouvé, génère des shims dans ~/.jenga/bin
        (zig-cc -> `zig cc`, etc.) et les renvoie. (None, None, None) si zig absent.
        Rend zig détectable SANS installation manuelle de wrappers."""
        cc = ToolchainManager._FirstRunnable(["zig-cc"])
        cxx = ToolchainManager._FirstRunnable(["zig-c++"])
        if cc and cxx:
            ar = ToolchainManager._FirstRunnable(["zig-ar"]) or Process.Which("llvm-ar") or Process.Which("ar")
            return cc, cxx, ar
        zig = Process.Which("zig")
        if not zig:
            return None, None, None
        try:
            bindir = Path.home() / ".jenga" / "bin"
            bindir.mkdir(parents=True, exist_ok=True)
            is_win = sys.platform == "win32"
            made: Dict[str, str] = {}
            for name, sub in (("zig-cc", "cc"), ("zig-c++", "c++"), ("zig-ar", "ar")):
                if is_win:
                    p = bindir / f"{name}.cmd"
                    p.write_text(f'@echo off\r\n"{zig}" {sub} %*\r\n', encoding="ascii")
                else:
                    p = bindir / name
                    p.write_text(f'#!/bin/sh\nexec "{zig}" {sub} "$@"\n', encoding="ascii")
                    p.chmod(0o755)
                made[name] = str(p)
            return made["zig-cc"], made["zig-c++"], made["zig-ar"]
        except Exception:
            return None, None, None

    @staticmethod
    def DetectZigToolchains() -> Dict[str, Toolchain]:
        """Detect Zig wrapper toolchains (zig-cc/zig-c++/zig-ar).
        Auto-génère les shims depuis `zig` natif si les wrappers sont absents."""
        zig_cc, zig_cxx, zig_ar = ToolchainManager._EnsureZigShims()
        if not zig_cc or not zig_cxx:
            return {}

        detected: Dict[str, Toolchain] = {}

        def _register(name: str,
                      target_os: TargetOS,
                      target_arch: TargetArch,
                      target_env: Optional[TargetEnv],
                      triple: str) -> None:
            tc = Toolchain(
                name=name,
                compilerFamily=CompilerFamily.CLANG,
                ccPath=zig_cc,
                cxxPath=zig_cxx,
                arPath=zig_ar,
                ldPath=zig_cxx,
            )
            tc.targetOs = target_os
            tc.targetArch = target_arch
            if target_env is not None:
                tc.targetEnv = target_env
            tc.targetTriple = triple
            tc.cflags.extend(["-target", triple])
            tc.cxxflags.extend(["-target", triple])
            tc.ldflags.extend(["-target", triple])
            detected[name] = tc

        _register("zig-linux-x86_64", TargetOS.LINUX, TargetArch.X86_64, TargetEnv.GNU, "x86_64-linux-gnu")
        _register("zig-linux-x64", TargetOS.LINUX, TargetArch.X86_64, TargetEnv.GNU, "x86_64-linux-gnu")
        _register("zig-windows-x86_64", TargetOS.WINDOWS, TargetArch.X86_64, TargetEnv.MINGW, "x86_64-windows-gnu")
        _register("zig-windows-x64", TargetOS.WINDOWS, TargetArch.X86_64, TargetEnv.MINGW, "x86_64-windows-gnu")
        _register("zig-macos-x86_64", TargetOS.MACOS, TargetArch.X86_64, TargetEnv.GNU, "x86_64-macos")
        _register("zig-macos-arm64", TargetOS.MACOS, TargetArch.ARM64, TargetEnv.GNU, "aarch64-macos")
        # Apple mobile (compile via zig ; link via ld.lld -flavor darwin — voir
        # Core/Builders/IosZig.py). Enregistrees pour que la resolution reussisse
        # sur un hote non-macOS ; le IosZigBuilder ignore le compilateur ci-dessus.
        _register("zig-ios-arm64", TargetOS.IOS, TargetArch.ARM64, None, "aarch64-ios")
        _register("zig-tvos-arm64", TargetOS.TVOS, TargetArch.ARM64, None, "aarch64-tvos")
        _register("zig-watchos-arm64", TargetOS.WATCHOS, TargetArch.ARM64, None, "aarch64-watchos")
        _register("zig-android-arm64", TargetOS.ANDROID, TargetArch.ARM64, TargetEnv.ANDROID, "aarch64-linux-android21")
        _register("zig-web-wasm32", TargetOS.WEB, TargetArch.WASM32, None, "wasm32-wasi")

        return detected

    # -----------------------------------------------------------------------
    # Interface publique
    # -----------------------------------------------------------------------

    def DetectAll(self, workspace: Optional[Any] = None) -> Dict[str, Toolchain]:
        """Detect all available toolchains for the current host and common targets."""
        toolchains: Dict[str, Toolchain] = {}
        original_path = os.environ.get("PATH", "")
        old_compilers_env = os.environ.get("JENGA_COMPILERS_DIR")
        compilers_root = self._GetCompilersRoot(workspace)
        extra_paths = self._CollectExtraBinaryPaths(workspace)
        try:
            if extra_paths:
                os.environ["PATH"] = os.pathsep.join(extra_paths + [original_path])
            if compilers_root:
                os.environ["JENGA_COMPILERS_DIR"] = str(compilers_root)

            # 1) Host-native compilers.
            self._AddToolchainIfValid(toolchains, self.DetectHostClang())
            self._AddToolchainIfValid(toolchains, self.DetectHostGCC())
            self._AddToolchainIfValid(toolchains, self.DetectHostCC())

            # 2) Windows families.
            if sys.platform == "win32":
                self._AddToolchainIfValid(toolchains, self.DetectMSVC())
                self._AddToolchainIfValid(toolchains, self.DetectClangOnWindows())
                self._AddToolchainIfValid(toolchains, self.DetectMinGW())
                self._AddToolchainIfValid(toolchains, self.DetectCrossLinuxOnWindows())
                # (2.8.17) une chaine par compilateur installe, a son nom
                for _tc in self.DetectWindowsGnuInstallations():
                    self._AddToolchainIfValid(toolchains, _tc)
            else:
                self._AddToolchainIfValid(toolchains, self.DetectCrossWindows())

            # 3) SDK-managed toolchains.
            self._AddToolchainIfValid(toolchains, self.DetectAndroidNDK())
            self._AddToolchainIfValid(toolchains, self.DetectEmscripten())

            # 4) Zig wrappers (if installed).
            for zig_name, zig_tc in self.DetectZigToolchains().items():
                self._AddToolchainIfValid(toolchains, zig_tc)

            # 5) Compatibility aliases used by existing workspaces/examples.
            if "zig-linux-x86_64" in toolchains and "zig-linux-x64" not in toolchains:
                toolchains["zig-linux-x64"] = self._CloneToolchainWithName(toolchains["zig-linux-x86_64"], "zig-linux-x64")
            if "zig-windows-x86_64" in toolchains and "zig-windows-x64" not in toolchains:
                toolchains["zig-windows-x64"] = self._CloneToolchainWithName(toolchains["zig-windows-x86_64"], "zig-windows-x64")

            self._detected = toolchains
            return toolchains
        finally:
            os.environ["PATH"] = original_path
            if old_compilers_env is None:
                os.environ.pop("JENGA_COMPILERS_DIR", None)
            else:
                os.environ["JENGA_COMPILERS_DIR"] = old_compilers_env

    def ResolveForTarget(self,
                         targetOs: TargetOS,
                         targetArch: TargetArch,
                         targetEnv: Optional[TargetEnv] = None,
                         prefer: Optional[List[str]] = None,
                         exclude: Optional[List[str]] = None) -> Optional[str]:
        """Trouve la meilleure toolchain pour une cible donnÃ©e."""
        exclude_set = {str(name).strip().lower() for name in (exclude or []) if str(name).strip()}
        use_cache = not exclude_set
        cache_key = (targetOs, targetArch, targetEnv)
        if use_cache and cache_key in self._cache:
            return self._cache[cache_key]
        candidates = []
        for name, tc in self._detected.items():
            if str(name).strip().lower() in exclude_set:
                continue
            if tc.targetOs == targetOs and tc.targetArch == targetArch:
                if targetEnv is None or tc.targetEnv == targetEnv:
                    candidates.append(name)
        if not candidates:
            for name, tc in self._detected.items():
                if str(name).strip().lower() in exclude_set:
                    continue
                if tc.targetOs == targetOs:
                    candidates.append(name)
        if not candidates:
            if use_cache:
                self._cache[cache_key] = None
            return None
        if prefer:
            for pref in prefer:
                if pref in candidates:
                    if use_cache:
                        self._cache[cache_key] = pref
                    return pref
        selected = candidates[0]
        if use_cache:
            self._cache[cache_key] = selected
        return selected

    def GetToolchain(self, name: str) -> Optional[Toolchain]:
        return self._detected.get(name)

    def AddToolchain(self, toolchain: Toolchain) -> None:
        self._detected[toolchain.name] = toolchain

    def ClearCache(self) -> None:
        self._cache.clear()