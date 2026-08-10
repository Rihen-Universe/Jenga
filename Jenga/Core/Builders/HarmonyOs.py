#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HarmonyOS Builder – Compilation et packaging pour HarmonyOS / OpenHarmony.

Fonctionnalités :
  - Compilation C/C++ via le NDK OHOS (clang aarch64-linux-ohos)
  - Génération automatique de la structure de projet HAP (hvigor)
    → générée dans le dossier de build Jenga (Build/Bin/<cfg>-HarmonyOS/<project>/harmony-build/)
    → pas dans le dossier source du projet (comme AndroidBuilder)
  - Packaging .hap via hvigorw (équivalent de l'APK Android)
  - Signature du .hap via hap-sign-tool (nécessite certificat Huawei)
  - Support des architectures : arm64-v8a (principal), armeabi-v7a, x86_64

Équivalences Android → HarmonyOS :
  AndroidManifest.xml  →  module.json5 + app.json5
  aapt2                →  hvigor (build tool basé sur Node.js/TypeScript)
  apksigner + .jks     →  hap-sign-tool + .p12 + .cer + .p7b
  zipalign             →  intégré dans hvigor
  adb install          →  hdc install

Structure HAP générée automatiquement dans le dossier de build :
  Build/Bin/<cfg>-HarmonyOS/<project>/harmony-build/
    hvigor/hvigor-config.json5
    hvigorfile.ts                   (appTasks)
    oh-package.json5                (modelVersion)
    build-profile.json5             (compatibleSdkVersion "X.Y.Z(api)")
    AppScope/
      app.json5
      resources/base/element/string.json
      resources/base/media/
    entry/
      hvigorfile.ts                 (hapTasks — obligatoire)
      oh-package.json5              (name/version du module)
      build-profile.json5
      src/main/
        module.json5
        resources/base/element/string.json
        resources/base/element/color.json
        resources/base/media/
        resources/base/profile/main_pages.json
        ets/entryability/EntryAbility.ets
        ets/pages/Index.ets
        cpp/CMakeLists.txt
      libs/arm64-v8a/               <- .so compilés par Jenga

Notes importantes sur le format hvigor 6.x (API 21 / HarmonyOS 6.0.1) :
  - compatibleSdkVersion : STRING au format "X.Y.Z(api)"  ex: "5.0.0(12)"
  - PAS de compileSdkVersion dans build-profile.json5 racine
  - oh-package.json5 racine : champ "modelVersion", pas "name"
  - entry/hvigorfile.ts utilise hapTasks (pas appTasks)
  - hvigor-config.json5 : sections execution/logging/debugging commentées
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import List, Optional

from Jenga.Core.Api import Project, ProjectKind, TargetArch, TargetOS, TargetEnv, CompilerFamily
from ...Utils import Process, FileSystem, Colored, ProcessResult, Reporter
from ..Builder import Builder
from ..Platform import Platform
from ..Toolchains import ToolchainManager


# Mapping API level entier → chaîne de version OHOS au format "X.Y.Z(api)"
# Format attendu par hvigor 6.x pour compatibleSdkVersion.
# Exemple : API 12 → "5.0.0(12)"
_OHOS_API_TO_VERSION = {
    # API 9 hors plage hvigor 6.x (min: 4.0.0(10)) — remappe a 10
    9:  "4.0.0(10)",
    10: "4.0.0(10)",
    11: "4.1.0(11)",
    12: "5.0.0(12)",
    13: "5.0.1(13)",
    14: "5.0.2(14)",
    15: "5.0.3(15)",
    16: "5.0.3(16)",
    17: "5.1.0(17)",
    18: "5.1.0(18)",
    19: "5.1.0(19)",
    20: "6.0.0(20)",
    21: "6.0.1(21)",
}
_OHOS_DEFAULT_SDK_VERSION = "6.0.1(21)"


def _api_to_sdk_version(api_level: int) -> str:
    """
    Convertit un niveau d'API OHOS (entier) en chaîne de version SDK
    au format "X.Y.Z(api)" attendu par hvigor 6.x.

    Exemple : 12 → "5.0.0(12)", 21 → "6.0.1(21)"

    hvigor refuse les entiers et les strings sans suffixe (api) —
    il attend impérativement le format "X.Y.Z(N)".
    """
    return _OHOS_API_TO_VERSION.get(api_level, _OHOS_DEFAULT_SDK_VERSION)


class HarmonyOsBuilder(Builder):
    """
    Builder pour HarmonyOS.

    Supporte les architectures : arm64-v8a (ARM64), armeabi-v7a (ARM), x86_64.
    Pour les projets WINDOWED_APP, génère automatiquement un .hap après compilation.
    Pour les projets SHARED_LIB / STATIC_LIB / CONSOLE_APP, compile uniquement.

    La structure HAP temporaire est créée dans le dossier de build Jenga
    (sous Build/Bin/<config>-HarmonyOS/<project>/harmony-build/) et non dans
    le dossier source du projet, de la même façon qu'AndroidBuilder crée
    ses fichiers temporaires dans GetTargetDir().
    """

    def __init__(self, workspace, config, platform, targetOs, targetArch,
                 targetEnv=None, verbose=False,
                 action: str = "build", options: Optional[List[str]] = None):
        super().__init__(workspace, config, platform, targetOs, targetArch,
                         targetEnv, verbose, action=action, options=options or [])

        # Résolution du SDK OHOS et du NDK
        self.sdk_path = self._ResolveHarmonySDK()
        self.ndk_path = self._ResolveHarmonyNDK()

        # Configuration de la toolchain clang OHOS
        self._PrepareToolchain()

    # -----------------------------------------------------------------------
    # Résolution des chemins SDK / NDK
    # -----------------------------------------------------------------------

    def _ResolveHarmonySDK(self) -> Optional[Path]:
        """
        Trouve le SDK HarmonyOS (openharmony/).

        Ordre de priorité :
          1. Variables d'environnement : OHOS_SDK, HARMONY_OS_SDK, HARMONY_SDK
          2. DSL workspace : harmonysdk("...")
          3. Chemins par défaut selon la plateforme hôte
        """
        for env_var in ["OHOS_SDK", "HARMONY_OS_SDK", "HARMONY_SDK"]:
            if env_var in os.environ:
                return Path(os.environ[env_var])

        if hasattr(self.workspace, 'harmonySdkPath') and self.workspace.harmonySdkPath:
            return Path(self.workspace.harmonySdkPath)

        if sys.platform == "win32":
            candidates = [
                Path("C:/ohos/command-line-tools/sdk/default/openharmony"),
            ]
        elif sys.platform == "darwin":
            candidates = [
                Path("/Applications/HarmonyOS/sdk/default/openharmony"),
                Path.home() / "ohos/command-line-tools/sdk/default/openharmony",
            ]
        else:
            candidates = [
                Path("/opt/ohos/sdk/default/openharmony"),
                Path.home() / "ohos/command-line-tools/sdk/default/openharmony",
            ]

        for cand in candidates:
            if cand.exists():
                return cand

        return None

    def _ResolveHarmonyNDK(self) -> Optional[Path]:
        """
        Trouve le NDK OHOS à partir du SDK.

        Structure réelle :
          sdk/default/openharmony/native/
            llvm/bin/clang++.exe
            sysroot/
        """
        if not self.sdk_path:
            return None

        ndk = self.sdk_path / "native"
        if ndk.exists():
            return ndk

        return None

    def _ResolveCliTools(self) -> Path:
        """
        Remonte depuis sdk/default/openharmony/ vers command-line-tools/.

        sdk_path = .../sdk/default/openharmony
          parents[0] = default/
          parents[1] = sdk/
          parents[2] = command-line-tools/
        """
        if self.sdk_path:
            return self.sdk_path.parents[2]

        return Path("C:/ohos/command-line-tools")

    # -----------------------------------------------------------------------
    # Configuration de la toolchain clang OHOS
    # -----------------------------------------------------------------------

    def _PrepareToolchain(self):
        """
        Configure la toolchain clang OHOS pour l'architecture cible.

        Triple cible : aarch64-linux-ohos (différent d'Android : aarch64-linux-android).
        """
        if not self.ndk_path:
            raise RuntimeError(
                "HarmonyOS NDK not found.\n"
                "Solutions :\n"
                "  - Definir OHOS_SDK vers .../sdk/default/openharmony\n"
                "  - Utiliser harmonysdk('...') dans votre .jenga\n"
                "  - Installer les HarmonyOS Command Line Tools dans C:/ohos/"
            )

        llvm_dir = self.ndk_path / "llvm"
        if not llvm_dir.exists():
            raise RuntimeError(
                f"Repertoire LLVM introuvable dans le NDK : {self.ndk_path}\n"
                "Verifiez que les HarmonyOS Command Line Tools sont installes."
            )

        # Mapping architecture Jenga → triple OHOS
        arch_map = {
            TargetArch.ARM:    "armv7a-linux-ohos",
            TargetArch.ARM64:  "aarch64-linux-ohos",
            TargetArch.X86_64: "x86_64-linux-ohos",
        }
        triple = arch_map.get(self.targetArch, "aarch64-linux-ohos")

        # Flags spécifiques ARM 32-bit
        arm_flags = []
        if self.targetArch == TargetArch.ARM:
            arm_flags = ["-march=armv7-a", "-mfloat-abi=softfp", "-mfpu=vfpv3-d16"]

        exe = ".exe" if sys.platform == "win32" else ""

        if self.toolchain:
            self.toolchain.ccPath    = str(llvm_dir / "bin" / f"clang{exe}")
            self.toolchain.cxxPath   = str(llvm_dir / "bin" / f"clang++{exe}")
            self.toolchain.arPath    = str(llvm_dir / "bin" / f"llvm-ar{exe}")
            self.toolchain.ldPath    = str(llvm_dir / "bin" / f"ld{exe}")
            self.toolchain.stripPath = str(llvm_dir / "bin" / f"llvm-strip{exe}")
            self.toolchain.targetTriple = triple
            self.toolchain.sysroot   = str(self.ndk_path / "sysroot")

            if arm_flags:
                self.toolchain.cflags   = list(getattr(self.toolchain, "cflags",   []) or []) + arm_flags
                self.toolchain.cxxflags = list(getattr(self.toolchain, "cxxflags", []) or []) + arm_flags

    # -----------------------------------------------------------------------
    # Dossier de build HAP
    # -----------------------------------------------------------------------

    def _GetHAPBuildDir(self, project: Project) -> Path:
        """
        Retourne le dossier de travail pour la structure HAP.

        Chemin : Build/Bin/<config>-HarmonyOS/<project>/harmony-build/
        Créé dans Build/, jamais dans les sources du projet.
        """
        return self.GetTargetDir(project) / "harmony-build"

    # -----------------------------------------------------------------------
    # Extensions des fichiers générés
    # -----------------------------------------------------------------------

    def GetObjectExtension(self) -> str:
        return ".o"

    def GetOutputExtension(self, project: Project) -> str:
        """
        SHARED_LIB   → .so
        STATIC_LIB   → .a
        WINDOWED_APP → .so  (NativeAbility)
        CONSOLE_APP  → ""   (ELF sans extension)
        """
        if project.kind == ProjectKind.SHARED_LIB:
            return ".so"
        elif project.kind == ProjectKind.STATIC_LIB:
            return ".a"
        elif project.kind == ProjectKind.WINDOWED_APP:
            return ".so"
        else:
            return ""

    def GetTargetPath(self, project: Project) -> Path:
        """
        Chemin complet du fichier de sortie.
        Ajoute le préfixe "lib" pour les .so si absent.
        """
        target_dir  = self.GetTargetDir(project)
        target_name = project.targetName or project.name
        ext         = self.GetOutputExtension(project)

        if project.kind in (ProjectKind.WINDOWED_APP, ProjectKind.SHARED_LIB,
                             ProjectKind.STATIC_LIB):
            if not target_name.startswith("lib"):
                target_name = f"lib{target_name}"

        return target_dir / f"{target_name}{ext}"

    # -----------------------------------------------------------------------
    # Compilation
    # -----------------------------------------------------------------------

    def Compile(self, project: Project, sourceFile: str, objectFile: str) -> ProcessResult:
        """Compile un fichier source C/C++ avec clang OHOS."""
        src = Path(sourceFile)
        obj = Path(objectFile)
        FileSystem.MakeDirectory(obj.parent)

        compiler = (
            self.toolchain.cxxPath
            if project.language.value in ("C++", "Objective-C++")
            else self.toolchain.ccPath
        )

        args = [compiler, "-c", "-o", str(obj)]
        args.extend(self.GetDependencyFlags(str(obj)))
        args.extend(self._GetCompilerFlags(project))

        if self.IsModuleFile(sourceFile):
            args.extend(self.GetModuleFlags(project, sourceFile))

        args.append(str(src))

        result = Process.ExecuteCommand(args, captureOutput=True, silent=False)
        self._lastResult = result
        return result

    def GetModuleFlags(self, project: Project, sourceFile: str) -> List[str]:
        """Flags pour les modules C++20."""
        if not self.IsModuleFile(sourceFile):
            return []
        return ["-fmodules", "-fbuiltin-module-map", "-std=c++20"]

    # -----------------------------------------------------------------------
    # Link
    # -----------------------------------------------------------------------

    def Link(self, project: Project, objectFiles: List[str], outputFile: str) -> bool:
        """
        Link les fichiers objets.

        STATIC_LIB   → llvm-ar rcs
        SHARED_LIB / WINDOWED_APP → clang++ -shared
        CONSOLE_APP  → clang++
        """
        out = Path(outputFile)
        FileSystem.MakeDirectory(out.parent)

        if project.kind == ProjectKind.STATIC_LIB:
            ar   = self.toolchain.arPath or "llvm-ar"
            args = [ar, "rcs", str(out)] + objectFiles
            result = Process.ExecuteCommand(args, captureOutput=True, silent=False)
            self._lastResult = result
            return result.returnCode == 0

        linker = self.toolchain.cxxPath

        if project.kind in (ProjectKind.SHARED_LIB, ProjectKind.WINDOWED_APP):
            args = [linker, "-shared", "-o", str(out)]
        else:
            args = [linker, "-o", str(out)]

        args.extend(self._GetLinkerFlags(project))

        for libdir in project.libDirs:
            args.append(f"-L{self.ResolveProjectPath(project, libdir)}")

        for lib in project.links:
            if self._IsDirectLibPath(lib):
                args.append(self.ResolveProjectPath(project, lib))
            else:
                args.append(f"-l{lib}")

        args.extend(objectFiles)

        result = Process.ExecuteCommand(args, captureOutput=True, silent=False)
        self._lastResult = result
        return result.returnCode == 0

    @staticmethod
    def _IsDirectLibPath(lib: str) -> bool:
        p = Path(lib)
        return (
            p.suffix in (".a", ".so", ".dylib", ".lib")
            or "/" in lib
            or "\\" in lib
            or p.is_absolute()
        )

    # -----------------------------------------------------------------------
    # Flags compilateur et linker
    # -----------------------------------------------------------------------

    def _GetCompilerFlags(self, project: Project) -> List[str]:
        """Flags clang pour la compilation OHOS."""
        flags = []

        flags.append(f"--target={self.toolchain.targetTriple}")
        if self.toolchain.sysroot:
            flags.append(f"--sysroot={self.toolchain.sysroot}")

        for inc in project.includeDirs:
            flags.append(f"-I{self.ResolveProjectPath(project, inc)}")

        for define in project.defines:
            flags.append(f"-D{define}")
        flags.append("-D__OHOS__")

        if getattr(project, 'harmonyMinSdk', ''):
            flags.append(f"-D__OHOS_API__={project.harmonyMinSdk}")

        if project.symbols:
            flags.append("-g")

        opt = project.optimize.value if hasattr(project.optimize, 'value') else project.optimize
        opt_map = {"Off": "-O0", "Size": "-Os", "Speed": "-O2", "Full": "-O3"}
        if opt in opt_map:
            flags.append(opt_map[opt])

        warn = project.warnings.value if hasattr(project.warnings, 'value') else project.warnings
        warn_map = {"All": "-Wall", "Extra": "-Wextra", "Error": "-Werror"}
        if warn in warn_map:
            flags.append(warn_map[warn])

        if project.language.value == "C++":
            flags.append(f"-std={project.cppdialect.lower()}")
        else:
            flags.append(f"-std={project.cdialect.lower()}")

        if project.kind != ProjectKind.CONSOLE_APP:
            flags.append("-fPIC")
        else:
            flags.append("-fPIE")

        if project.language.value in ("C++", "Objective-C++"):
            flags.extend(project.cxxflags or [])
        else:
            flags.extend(project.cflags or [])

        return flags

    def _GetLinkerFlags(self, project: Project) -> List[str]:
        """
        Flags clang pour le link OHOS.

        Les libs système (liblog, libhilog, libohos) sont ajoutées
        uniquement si elles existent dans le sysroot.
        """
        flags = []

        flags.append(f"--target={self.toolchain.targetTriple}")
        if self.toolchain.sysroot:
            flags.append(f"--sysroot={self.toolchain.sysroot}")

            sysroot_path = Path(self.toolchain.sysroot)
            arch_lib_dir = sysroot_path / "usr" / "lib" / self.toolchain.targetTriple
            if arch_lib_dir.exists():
                flags.append(f"-L{arch_lib_dir}")

            for lib_name in ["log", "hilog", "ohos"]:
                lib_file = arch_lib_dir / f"lib{lib_name}.so"
                if lib_file.exists():
                    flags.append(f"-l{lib_name}")

        flags.extend(project.ldflags or [])

        return flags

    # -----------------------------------------------------------------------
    # Génération automatique de la structure du projet HAP
    # -----------------------------------------------------------------------

    def _CopyHarmonyArkTSFiles(self, project: Project, build_dir: Path):
        """
        Copie les fichiers ArkTS/ETS dans entry/src/main/ets/ de la structure HAP.

        Sources (ordre de priorité, cumulatif) :

          1. Depuis files() — même pattern que .mm/.m pour Cocoa/ObjC.
             L'utilisateur déclare simplement les .ts/.ets dans files() et
             Jenga sait que ces fichiers vont dans le HAP, pas dans le compilateur.

             Exemple .jenga :
               files(["src/**.cpp", "harmony/ets/NkHarmonyBridge.ts"])
               files(["src/**.cpp", "harmony/ets/**.ts"])   # wildcard aussi

          2. Depuis harmonyets() — DSL explicite (maintenu pour compatibilité).
             harmonyets(["harmony/ets/"])

          3. Convention auto-detection — NkHarmonyBridge.ts dans harmony/ets/.
             Copié automatiquement si présent, même sans déclaration.

        Mapping de destination (même logique que .mm → entryability/pages) :
          *Ability.ts/.ets  → entry/src/main/ets/entryability/
          *page*.*          → entry/src/main/ets/pages/
          NkHarmony*.ts     → entry/src/main/ets/   (racine ets)
          Autres *.ts/.ets  → entry/src/main/ets/   (racine ets)

        Fusion EntryAbility :
          Si un EntryAbility.ets est fourni, il REMPLACE le stub généré.
          Sinon, le stub est patché automatiquement pour importer NkHarmonyBridge.
        """
        ARKTS_EXTENSIONS = {'.ts', '.ets'}
        dest_ets = build_dir / "entry" / "src" / "main" / "ets"
        copied_any = False

        # ── Source 1 : fichiers déclarés dans files() ─────────────────────────
        # Collecter tous les fichiers .ts/.ets résolus depuis files() du projet.
        # Le Builder de base les a déjà résolus (globs, filtres, etc.) mais
        # les a ignorés car non compilables C++. On les récupère ici.
        arkts_from_files = []
        all_files = self._ResolveAllProjectFiles(project)
        for f in all_files:
            p = Path(f)
            if p.suffix.lower() in ARKTS_EXTENSIONS and p.exists():
                arkts_from_files.append(p)

        for src_file in arkts_from_files:
            dest = self._ArkTSDestination(src_file.name, dest_ets)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_file, dest)
            Reporter.Info(f"  ArkTS [files()]: {src_file.name} -> ets/{dest.parent.name}/")
            copied_any = True

        # ── Source 2 : harmonyets() DSL explicite ─────────────────────────────
        ets_dirs = getattr(project, 'harmonyEtsDirs', []) or []
        for src_pattern in ets_dirs:
            src_path = Path(self.ResolveProjectPath(project, src_pattern))
            if not src_path.exists():
                Reporter.Warning(f"[HarmonyOS] harmonyets: introuvable : {src_path}")
                continue
            if src_path.is_dir():
                for f in src_path.rglob("*"):
                    if not f.is_file() or f.suffix.lower() not in ARKTS_EXTENSIONS:
                        continue
                    rel  = f.relative_to(src_path)
                    dest = dest_ets / rel
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(f, dest)
                    Reporter.Info(f"  ArkTS [harmonyets()]: {rel}")
                    copied_any = True
            else:
                if src_path.suffix.lower() not in ARKTS_EXTENSIONS:
                    continue
                dest = self._ArkTSDestination(src_path.name, dest_ets)
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src_path, dest)
                Reporter.Info(f"  ArkTS [harmonyets()]: {src_path.name}")
                copied_any = True

        # ── Source 3 : convention auto-detection ──────────────────────────────
        if not copied_any:
            self._CopyDefaultBridge(project, build_dir)
            return

        # ── Patch EntryAbility si NkHarmonyBridge a été copié ─────────────────
        bridge_dest = dest_ets / "NkHarmonyBridge.ts"
        if bridge_dest.exists():
            self._PatchEntryAbilityForBridge(build_dir)

    def _ArkTSDestination(self, filename: str, dest_ets: Path) -> Path:
        """
        Détermine le sous-dossier de destination dans entry/src/main/ets/
        selon le nom du fichier — même logique que .mm → entryability/pages.

          *ability*.ts/.ets → entryability/
          *page*.ts/.ets    → pages/
          *bridge*.ts/.ets  → .  (racine ets)
          nk*.ts/.ets       → .  (racine ets)
          autres            → .  (racine ets)
        """
        lower = filename.lower()
        if "ability" in lower:
            return dest_ets / "entryability" / filename
        if "page" in lower or "index" in lower:
            return dest_ets / "pages" / filename
        return dest_ets / filename

    def _ResolveAllProjectFiles(self, project: Project) -> List[str]:
        """
        Retourne la liste complète des fichiers résolus depuis project.files,
        y compris les globs et les fichiers filtrés par platform.

        Si le Builder de base expose déjà une méthode pour ça, on l'utilise.
        Sinon on résout manuellement depuis project.files.
        """
        import fnmatch, glob as _glob

        result = []
        proj_root = Path(self.ResolveProjectPath(project, "."))

        all_patterns = list(project.files)

        # Ajouter les patterns filtrés par platform actuelle
        filter_key = f"system:{self.platform}"
        for fkey, ffiles in project._filteredFiles.items():
            if fkey == filter_key or fkey == "":
                all_patterns.extend(ffiles)

        for pattern in all_patterns:
            p = Path(self.ResolveProjectPath(project, pattern))
            if "**" in str(p) or "*" in str(p):
                matches = _glob.glob(str(p), recursive=True)
                result.extend(matches)
            elif p.exists():
                result.append(str(p))

        return result

    def _CopyDefaultBridge(self, project: Project, build_dir: Path):
        """
        Cherche NkHarmonyBridge.ts dans le dossier harmony/ du projet.

        Convention : si le projet a un dossier harmony/ets/ contenant
        NkHarmonyBridge.ts, il est copié automatiquement sans que l'utilisateur
        ait besoin de déclarer harmonyets() dans le .jenga.
        """
        proj_root = Path(self.ResolveProjectPath(project, "."))
        candidates = [
            proj_root / "harmony" / "ets" / "NkHarmonyBridge.ts",
            proj_root / "harmony" / "NkHarmonyBridge.ts",
            proj_root / "NkHarmonyBridge.ts",
        ]
        dest_ets = build_dir / "entry" / "src" / "main" / "ets"

        for cand in candidates:
            if cand.exists():
                dest_ets.mkdir(parents=True, exist_ok=True)
                shutil.copy2(cand, dest_ets / "NkHarmonyBridge.ts")
                Reporter.Info(f"  ArkTS: NkHarmonyBridge.ts (auto-detected)")
                # Patcher EntryAbility.ets pour importer le bridge
                self._PatchEntryAbilityForBridge(build_dir)
                return

    def _PatchEntryAbilityForBridge(self, build_dir: Path):
        """
        Patche EntryAbility.ets pour importer et initialiser NkHarmonyBridge.

        Si EntryAbility.ets existe déjà dans la structure et ne contient pas
        encore l'import du bridge, on l'injecte automatiquement.
        C'est l'approche la moins invasive : l'utilisateur n'a pas besoin de
        modifier son Ability manuellement.
        """
        ability_path = (build_dir / "entry" / "src" / "main" / "ets"
                        / "entryability" / "EntryAbility.ets")
        if not ability_path.exists():
            return

        content = ability_path.read_text(encoding="utf-8")

        # Déjà patché ?
        if "NkHarmonyBridge" in content:
            return

        # Injecter l'import en tête de fichier
        import_line = ("import { NkHarmonyBridge } from '../NkHarmonyBridge';\n")

        if "import " in content:
            # Ajouter après le dernier import existant
            lines = content.splitlines(keepends=True)
            last_import = 0
            for i, line in enumerate(lines):
                if line.strip().startswith("import "):
                    last_import = i
            lines.insert(last_import + 1, import_line)
            content = "".join(lines)
        else:
            content = import_line + content

        # Injecter l'init dans onWindowStageCreate
        if "onWindowStageCreate" in content and "NkHarmonyBridge.init" not in content:
            content = content.replace(
                "onWindowStageCreate(windowStage: window.WindowStage): void {",
                "onWindowStageCreate(windowStage: window.WindowStage): void {\n"
                "    NkHarmonyBridge.init(windowStage, this.context);"
            )

        # Injecter destroy dans onWindowStageDestroy
        if "onWindowStageDestroy" in content and "NkHarmonyBridge.destroy" not in content:
            content = content.replace(
                "onWindowStageDestroy(): void {}",
                "onWindowStageDestroy(): void { NkHarmonyBridge.destroy(); }"
            )

        ability_path.write_text(content, encoding="utf-8")
        Reporter.Info("  ArkTS: EntryAbility.ets patched with NkHarmonyBridge")

    def _CopyHarmonyResources(self, project: Project, build_dir: Path):
        """
        Copie les dossiers de ressources HarmonyOS déclarés via harmonyresources()
        dans la structure HAP de build (entry/src/main/resources/).

        Équivalent de androidResDirs dans AndroidBuilder (_CompileResources).

        Structure attendue dans chaque dossier source :
          base/element/string.json      ← chaînes, couleurs, booleans
          base/media/icon.png           ← images, icônes
          base/profile/main_pages.json  ← profils de navigation
          en_US/element/string.json     ← i18n anglais
          zh_CN/element/string.json     ← i18n chinois

        Fusion intelligente des string.json :
          Si le string.json destination existe déjà (généré par _GenerateHAPProject),
          les nouvelles entrées sont fusionnées plutôt qu'écrasées, pour ne pas
          perdre les chaînes requises (module_desc, EntryAbility_label, etc.).
        """
        res_dirs = getattr(project, 'harmonyResDirs', []) or []
        if not res_dirs:
            return

        dest_res = build_dir / "entry" / "src" / "main" / "resources"

        for res_dir_pattern in res_dirs:
            res_dir = Path(self.ResolveProjectPath(project, res_dir_pattern))
            if not res_dir.exists():
                Reporter.Warning(f"[HarmonyOS] harmonyresources: dossier introuvable : {res_dir}")
                continue

            Reporter.Info(f"  Copying resources from {res_dir.name}/")

            # Parcourir tous les fichiers du dossier source
            for src_file in res_dir.rglob("*"):
                if not src_file.is_file():
                    continue

                # Chemin relatif au dossier de ressources source
                rel = src_file.relative_to(res_dir)
                dest_file = dest_res / rel

                dest_file.parent.mkdir(parents=True, exist_ok=True)

                # Fusion intelligente pour les fichiers JSON de chaînes/couleurs
                if (dest_file.exists()
                        and src_file.suffix == ".json"
                        and dest_file.suffix == ".json"):
                    self._MergeJsonResource(src_file, dest_file)
                else:
                    shutil.copy2(src_file, dest_file)

        Reporter.Info(f"  Resources copied to entry/src/main/resources/")

    def _MergeJsonResource(self, src: Path, dest: Path):
        """
        Fusionne un fichier JSON de ressources HarmonyOS (string.json, color.json...).

        Format HarmonyOS :
          { "string": [ {"name": "key", "value": "val"}, ... ] }
          { "color":  [ {"name": "key", "value": "#FFF"}, ... ] }

        Stratégie : les entrées du fichier source écrasent les entrées existantes
        de même nom dans la destination. Les nouvelles entrées sont ajoutées.
        Les entrées existantes non présentes dans source sont conservées.
        """
        import json

        try:
            src_data  = json.loads(src.read_text(encoding="utf-8"))
            dest_data = json.loads(dest.read_text(encoding="utf-8"))
        except Exception:
            # Si lecture/parse échoue, copie directe
            shutil.copy2(src, dest)
            return

        # Trouver la clé principale (string, color, float, integer, boolean...)
        root_key = None
        for k in src_data:
            if isinstance(src_data[k], list):
                root_key = k
                break

        if not root_key or root_key not in dest_data:
            # Format inconnu ou clé absente dans dest → copie directe
            shutil.copy2(src, dest)
            return

        # Construire un dict name→entry pour la destination
        dest_entries = {
            e["name"]: e
            for e in dest_data[root_key]
            if isinstance(e, dict) and "name" in e
        }

        # Fusionner : les entrées source écrasent dest si même nom
        for entry in src_data.get(root_key, []):
            if isinstance(entry, dict) and "name" in entry:
                dest_entries[entry["name"]] = entry

        # Réécrire dest avec les entrées fusionnées
        dest_data[root_key] = list(dest_entries.values())
        dest.write_text(
            json.dumps(dest_data, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )

    def _CopyHarmonyAssets(self, project: Project, build_dir: Path):
        """
        Copie les assets HarmonyOS déclarés via harmonyassets() dans
        entry/src/main/resources/rawfile/.

        Les assets sont des fichiers bruts (images, audio, données binaires)
        accessibles depuis ArkTS via $rawfile('filename') ou
        getContext().resourceManager.getRawFileContent('filename').

        Équivalent de androidassets() pour Android (dossier assets/ dans l'APK).
        """
        asset_dirs = getattr(project, 'harmonyAssets', []) or []
        if not asset_dirs:
            return

        rawfile_dir = build_dir / "entry" / "src" / "main" / "resources" / "rawfile"
        rawfile_dir.mkdir(parents=True, exist_ok=True)

        for asset_pattern in asset_dirs:
            asset_path = Path(self.ResolveProjectPath(project, asset_pattern))
            if not asset_path.exists():
                Reporter.Warning(f"[HarmonyOS] harmonyassets: introuvable : {asset_path}")
                continue

            if asset_path.is_dir():
                # Copier tout le dossier en préservant la hiérarchie
                for f in asset_path.rglob("*"):
                    if f.is_file():
                        rel  = f.relative_to(asset_path)
                        dest = rawfile_dir / rel
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(f, dest)
                Reporter.Info(f"  Assets copied: {asset_path.name}/ -> rawfile/")
            else:
                # Fichier individuel
                shutil.copy2(asset_path, rawfile_dir / asset_path.name)
                Reporter.Info(f"  Asset copied: {asset_path.name} -> rawfile/")

    @staticmethod
    def _MakeSolidPng(size: int, rgb) -> bytes:
        """Fabrique un PNG uni, sans aucune dependance tierce.

        Pillow n'est qu'une dependance OPTIONNELLE de Jenga : l'icone par defaut
        ne peut pas en dependre, sans quoi une machine sans Pillow ET sans
        DevEco Studio ne pourrait construire aucun HAP. zlib et struct suffisent
        — un PNG est un en-tete, des lignes filtrees compressees, et un CRC.
        """
        import struct
        import zlib

        def chunk(tag: bytes, data: bytes) -> bytes:
            return (struct.pack(">I", len(data)) + tag + data +
                    struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

        r, g, b = rgb
        # Chaque ligne est precedee de son octet de filtre (0 = aucun).
        ligne = b"\x00" + bytes([r, g, b]) * size
        brut = ligne * size
        return (b"\x89PNG\r\n\x1a\n" +
                chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)) +
                chunk(b"IDAT", zlib.compress(brut, 9)) +
                chunk(b"IEND", b""))

    def _WriteDefaultHAPIcons(self, build_dir: Path):
        """Ecrit les trois icones que HarmonyOS exige, si elles manquent.

        Volontairement UNIES et sobres (bleu petrole de la charte) : c'est un
        repli technique, pas une identite visuelle. Une application qui tient a
        son icone la declare avec appicon() ou harmonyappicon().
        """
        cibles = [
            (build_dir / "AppScope" / "resources" / "base" / "media", ["app_icon.png"]),
            (build_dir / "entry" / "src" / "main" / "resources" / "base" / "media",
             ["layered_image.png", "startIcon.png", "background.png", "foreground.png"]),
        ]
        png = self._MakeSolidPng(192, (10, 85, 95))
        ecrites = 0
        for dossier, noms in cibles:
            dossier.mkdir(parents=True, exist_ok=True)
            for nom in noms:
                f = dossier / nom
                if not f.exists():
                    f.write_bytes(png)
                    ecrites += 1
        if ecrites:
            Reporter.Info(f"  Icones par defaut generees ({ecrites} fichier(s), 192x192)")

    def _PrepareHAPIcons(self, project: Project, build_dir: Path):
        """
        Copie ou génère les icônes de l'application dans la structure HAP.

        HarmonyOS utilise trois icônes PNG dans AppScope/resources/base/media/ :
          - app_icon.png    : icône globale de l'app (référencée dans app.json5)
          - layered_image.png : icône layered de l'Ability (référencée dans module.json5)
          - startIcon.png   : icône du splash screen

        Source de l'icône (ordre de priorité) :
          1. harmonyappicon("path/to/icon.png") — override spécifique HarmonyOS
          2. appicon("path/to/icon.png")        — icône générique multi-plateforme
          3. Pas d'icône configurée → conserve les placeholders du template DevEco

        Si Pillow est installé, redimensionne automatiquement vers 192x192px.
        Sinon, copie directement le PNG source.
        """
        # Résolution de la source d'icône
        icon_src = (
            getattr(project, 'harmonyAppIcon', '') or
            getattr(project, 'appIcon', '') or
            ''
        )
        if not icon_src:
            # Aucune icone declaree : on en ECRIT une. Compter sur les
            # placeholders du template DevEco rendait la construction
            # impossible sans cet IDE — hvigor s'arrete sur
            #     Error: The resource reference '$media:app_icon' is not defined
            # et le message ne dit pas que la cause est un template absent.
            self._WriteDefaultHAPIcons(build_dir)
            return

        icon_path = Path(self.ResolveProjectPath(project, icon_src))
        if not icon_path.exists():
            Reporter.Warning(f"[HarmonyOS] Icone introuvable : {icon_path}")
            return

        if icon_path.suffix.lower() not in ('.png', '.jpg', '.jpeg', '.webp'):
            Reporter.Warning(f"[HarmonyOS] Format d'icone non supporte : {icon_path.suffix}")
            return

        # Dossiers cibles
        app_media   = build_dir / "AppScope" / "resources" / "base" / "media"
        entry_media = build_dir / "entry" / "src" / "main" / "resources" / "base" / "media"
        app_media.mkdir(parents=True, exist_ok=True)
        entry_media.mkdir(parents=True, exist_ok=True)

        # Noms des icônes HarmonyOS
        icon_names = ["app_icon.png", "layered_image.png", "startIcon.png",
                      "foreground.png", "background.png"]

        try:
            from PIL import Image

            img = Image.open(icon_path).convert("RGBA")

            # app_icon.png et layered_image.png → 192x192 (recommandé HarmonyOS)
            img_192 = img.resize((192, 192), Image.LANCZOS)
            for name in ["app_icon.png", "layered_image.png"]:
                img_192.save(app_media / name)
                img_192.save(entry_media / name)

            # startIcon.png → 144x144 (taille splash screen)
            img_144 = img.resize((144, 144), Image.LANCZOS)
            img_144.save(app_media / "startIcon.png")
            img_144.save(entry_media / "startIcon.png")

            # foreground.png → icône layered foreground (288x288 avec padding)
            # HarmonyOS layered icons : zone safe = 2/3 du centre
            img_288 = Image.new("RGBA", (288, 288), (0, 0, 0, 0))
            img_192_center = img.resize((192, 192), Image.LANCZOS)
            img_288.paste(img_192_center, (48, 48), img_192_center)
            img_288.save(app_media / "foreground.png")
            img_288.save(entry_media / "foreground.png")

            # background.png → fond blanc 288x288
            bg = Image.new("RGBA", (288, 288), (255, 255, 255, 255))
            bg.save(app_media / "background.png")
            bg.save(entry_media / "background.png")

            Reporter.Info(f"  Icons generated from {icon_path.name}")

        except ImportError:
            # Pillow non installé — copie directe sans redimensionnement
            for name in ["app_icon.png", "layered_image.png", "startIcon.png"]:
                shutil.copy2(icon_path, app_media / name)
                shutil.copy2(icon_path, entry_media / name)
            Reporter.Warning(
                "[HarmonyOS] Pillow non installe — icone copiee sans redimensionnement.\n"
                "  Installer : pip install Pillow"
            )

        except Exception as e:
            Reporter.Warning(f"[HarmonyOS] Echec generation icone : {e}")

    def _FindDevEcoTemplate(self) -> Optional[Path]:
        """
        Cherche le template de projet officiel DevEco Studio sur le système.

        Ce template contient exactement la structure attendue par hvigor,
        incluant les bonnes versions de tous les fichiers de configuration.
        L'utiliser directement évite tout problème de format ou de version.
        """
        candidates = [
            # Windows — emplacements standards DevEco Studio
            Path("C:/Program Files/Huawei/DevEco Studio/plugins/codegenie-plugin/previewProject"),
            Path("C:/Program Files (x86)/Huawei/DevEco Studio/plugins/codegenie-plugin/previewProject"),
            # Variable d'environnement personnalisée
        ]
        deveco_home = os.environ.get("DEVECO_STUDIO_HOME", "")
        if deveco_home:
            candidates.insert(0, Path(deveco_home) / "plugins/codegenie-plugin/previewProject")

        for cand in candidates:
            if cand.exists() and (cand / "hvigor" / "hvigor-config.json5").exists():
                return cand

        return None

    def _GenerateHAPProject(self, project: Project, build_dir: Path) -> bool:
        """
        Génère la structure de projet HAP dans build_dir (dossier de build Jenga).

        Stratégie en deux temps :
          1. Si DevEco Studio est installé, copie le template officiel directement
             (garantit la compatibilité avec la version de hvigor installée).
          2. Sinon, génère les fichiers manuellement à partir des valeurs connues.

        Format calqué exactement sur les templates DevEco Studio / hvigor 6.x :
          - compatibleSdkVersion = "X.Y.Z(api)"  ex: "5.0.0(12)"
          - PAS de compileSdkVersion
          - oh-package.json5 racine avec modelVersion
          - entry/hvigorfile.ts avec hapTasks (différent de la racine appTasks)
          - entry/oh-package.json5 avec name/version
          - hvigor-config.json5 avec sections commentées execution/logging/debugging
          - module.json5 avec skills pour l'intent-filter (home screen)
        """
        bundle_name  = getattr(project, 'harmonyBundleName', '') or f"com.nkentseu.{project.name.lower()}"
        version_name = getattr(project, 'harmonyVersionName', '') or "1.0.0"
        version_code = getattr(project, 'harmonyVersionCode', 1) or 1
        app_name     = project.targetName or project.name

        # Conversion API level → "X.Y.Z(api)" — format obligatoire hvigor 6.x
        min_api     = int(getattr(project, 'harmonyMinSdk',   12) or 12)
        compat_ver  = _api_to_sdk_version(min_api)  # ex: "5.0.0(12)"

        # Nom lib sans préfixe "lib"
        lib_name = app_name
        if lib_name.startswith("lib"):
            lib_name = lib_name[3:]

        Reporter.Info(f"[HarmonyOS] Generating HAP project structure in {build_dir}")
        build_dir.mkdir(parents=True, exist_ok=True)

        # ── Stratégie 1 : copier le template officiel DevEco Studio ──────
        # Si DevEco Studio est installé, on copie son template directement.
        # C'est la méthode la plus fiable — le template est toujours à jour
        # avec la version de hvigor installée sur la machine.
        # On ne copie que si les fichiers de base n'existent pas encore.
        # ── PRIORITE A LA GENERATION MAISON ───────────────────────────────
        # Regle du projet : tout ce qui est necessaire a une application doit
        # pouvoir sortir de Jenga SEUL, sans dependre d'un IDE tiers installe
        # sur la machine. Copier le template de DevEco Studio contredisait ce
        # principe et importait au passage ses artefacts : le paquet installe
        # declarait par exemple un `EntryFormAbility` (widget d'ecran d'accueil)
        # que le projet ne demande nulle part.
        #
        # Le template reste un REPLI, utilisable quand la generation maison
        # echoue ou quand une version de hvigor introduit un format qu'on ne
        # produit pas encore. NKJENGA_HARMONY_TEMPLATE=1 le redemande
        # explicitement, pour comparer les deux en cas de doute.
        veut_template = os.environ.get("NKJENGA_HARMONY_TEMPLATE", "") == "1"
        deveco_template = self._FindDevEcoTemplate() if veut_template else None
        if deveco_template and not (build_dir / "hvigor" / "hvigor-config.json5").exists():
            Reporter.Info(f"  Using DevEco Studio template from {deveco_template}")
            try:
                # Copier tout le template dans build_dir
                for item in deveco_template.iterdir():
                    dest = build_dir / item.name
                    if item.is_dir():
                        if not dest.exists():
                            shutil.copytree(str(item), str(dest))
                    else:
                        shutil.copy2(str(item), str(dest))
                Reporter.Info(f"  Template copied successfully")
                # Personnaliser les fichiers copiés avec les métadonnées du projet
                self._CustomizeHAPTemplate(project, build_dir, bundle_name,
                                           version_name, version_code, app_name,
                                           compat_ver, lib_name)
                Reporter.Success(f"[HarmonyOS] HAP project structure ready in {build_dir}")
                return True
            except Exception as e:
                Reporter.Warning(f"  Failed to copy DevEco template ({e}), falling back to manual generation")

        # ── Stratégie 2 : génération manuelle ────────────────────────────

        # ── 1. hvigor/hvigor-config.json5 ────────────────────────────────
        # Format officiel DevEco Studio avec sections commentées.
        hvigor_dir    = build_dir / "hvigor"
        hvigor_config = hvigor_dir / "hvigor-config.json5"
        if not hvigor_config.exists():
            hvigor_dir.mkdir(parents=True, exist_ok=True)
            hvigor_config.write_text(
                '{\n'
                '  "modelVersion": "5.0.0",\n'
                '  "dependencies": {\n'
                '  },\n'
                '  "execution": {\n'
                '    // "analyze": "normal",\n'
                '    // "daemon": true,\n'
                '    // "incremental": true,\n'
                '    // "parallel": true,\n'
                '    // "typeCheck": false,\n'
                '  },\n'
                '  "logging": {\n'
                '    // "level": "info"\n'
                '  },\n'
                '  "debugging": {\n'
                '    // "stacktrace": false\n'
                '  },\n'
                '  "nodeOptions": {\n'
                '    // "maxOldSpaceSize": 8192\n'
                '    // "exposeGC": true\n'
                '  }\n'
                '}\n',
                encoding="utf-8"
            )
            Reporter.Info(f"  Created: hvigor/hvigor-config.json5")

        # ── 2. hvigorfile.ts (racine) — appTasks ─────────────────────────
        # La racine utilise appTasks, le module entry utilise hapTasks.
        hvigorfile = build_dir / "hvigorfile.ts"
        if not hvigorfile.exists():
            hvigorfile.write_text(
                "import { appTasks } from '@ohos/hvigor-ohos-plugin';\n\n"
                "export default {\n"
                "    system: appTasks,  /* Built-in plugin of Hvigor. It cannot be modified. */\n"
                "    plugins:[]         /* Custom plugin to extend the functionality of Hvigor. */\n"
                "}\n",
                encoding="utf-8"
            )
            Reporter.Info(f"  Created: hvigorfile.ts")

        # ── 3. oh-package.json5 (racine) — modelVersion ──────────────────
        # La racine utilise modelVersion (pas name/version comme le module).
        oh_package = build_dir / "oh-package.json5"
        if not oh_package.exists():
            oh_package.write_text(
                '{\n'
                '  "modelVersion": "5.0.0",\n'
                '  "description": "Please describe the basic information.",\n'
                '  "dependencies": {\n'
                '  },\n'
                '  "devDependencies": {\n'
                '    "@ohos/hypium": "1.0.18",\n'
                '    "@ohos/hamock": "1.0.1-rc2"\n'
                '  }\n'
                '}\n',
                encoding="utf-8"
            )
            Reporter.Info(f"  Created: oh-package.json5")

        # ── 4. build-profile.json5 (racine) ───────────────────────────────
        # IMPORTANT :
        #   - compatibleSdkVersion au format "X.Y.Z(api)"  ex: "5.0.0(12)"
        #   - PAS de compileSdkVersion (absent du template officiel)
        #   - signingConfig référence "default" (même si signingConfigs est vide)
        build_profile = build_dir / "build-profile.json5"
        if not build_profile.exists():
            harmony_version_code = max(version_code, 1000000)
            build_profile.write_text(
                '{\n'
                '  "app": {\n'
                '    "signingConfigs": [],\n'
                '    "products": [\n'
                '      {\n'
                '        "name": "default",\n'
                '        "signingConfig": "default",\n'
                f'        "compatibleSdkVersion": "{compat_ver}",\n'
                '        "runtimeOS": "HarmonyOS",\n'
                '      }\n'
                '    ],\n'
                '    "buildModeSet": [\n'
                '      {\n'
                '        "name": "debug",\n'
                '      },\n'
                '      {\n'
                '        "name": "release"\n'
                '      }\n'
                '    ]\n'
                '  },\n'
                '  "modules": [\n'
                '    {\n'
                '      "name": "entry",\n'
                '      "srcPath": "./entry",\n'
                '      "targets": [\n'
                '        {\n'
                '          "name": "default",\n'
                '          "applyToProducts": [\n'
                '            "default"\n'
                '          ]\n'
                '        }\n'
                '      ]\n'
                '    }\n'
                '  ]\n'
                '}\n',
                encoding="utf-8"
            )
            Reporter.Info(f"  Created: build-profile.json5")

        # ── 5. AppScope/app.json5 ─────────────────────────────────────────
        app_scope = build_dir / "AppScope"
        app_json  = app_scope / "app.json5"
        if not app_json.exists():
            app_scope.mkdir(parents=True, exist_ok=True)
            harmony_version_code = max(version_code, 1000000)
            app_json.write_text(
                '{\n'
                '  "app": {\n'
                f'    "bundleName": "{bundle_name}",\n'
                '    "vendor": "nkentseu",\n'
                f'    "versionCode": {harmony_version_code},\n'
                f'    "versionName": "{version_name}",\n'
                '    "icon": "$media:app_icon",\n'
                '    "label": "$string:app_name"\n'
                '  }\n'
                '}\n',
                encoding="utf-8"
            )
            Reporter.Info(f"  Created: AppScope/app.json5")

        # ── 6. AppScope/resources/base/element/string.json ────────────────
        app_res_element = app_scope / "resources" / "base" / "element"
        app_strings     = app_res_element / "string.json"
        if not app_strings.exists():
            app_res_element.mkdir(parents=True, exist_ok=True)
            app_strings.write_text(
                '{\n'
                '  "string": [\n'
                '    {\n'
                f'      "name": "app_name",\n'
                f'      "value": "{app_name}"\n'
                '    }\n'
                '  ]\n'
                '}\n',
                encoding="utf-8"
            )
            Reporter.Info(f"  Created: AppScope/resources/base/element/string.json")

        # Dossier media AppScope (placeholder icône app_icon)
        (app_scope / "resources" / "base" / "media").mkdir(parents=True, exist_ok=True)

        # ── 7. entry/hvigorfile.ts — hapTasks ────────────────────────────
        # CRITIQUE : le module entry doit utiliser hapTasks (pas appTasks).
        # C'est différent de la racine. hvigor refuse si c'est appTasks ici.
        entry_dir       = build_dir / "entry"
        entry_hvigorfile = entry_dir / "hvigorfile.ts"
        if not entry_hvigorfile.exists():
            entry_dir.mkdir(parents=True, exist_ok=True)
            entry_hvigorfile.write_text(
                "import { hapTasks } from '@ohos/hvigor-ohos-plugin';\n\n"
                "export default {\n"
                "    system: hapTasks,  /* Built-in plugin of Hvigor. It cannot be modified. */\n"
                "    plugins:[]         /* Custom plugin to extend the functionality of Hvigor. */\n"
                "}\n",
                encoding="utf-8"
            )
            Reporter.Info(f"  Created: entry/hvigorfile.ts")

        # ── 8. entry/oh-package.json5 — name/version du module ───────────
        # Le module entry a son propre oh-package.json5 avec name/version
        # (différent du racine qui utilise modelVersion).
        entry_oh_package = entry_dir / "oh-package.json5"
        if not entry_oh_package.exists():
            entry_oh_package.write_text(
                '{\n'
                '  "name": "entry",\n'
                '  "version": "1.0.0",\n'
                '  "description": "Please describe the basic information.",\n'
                '  "main": "",\n'
                '  "author": "",\n'
                '  "license": "",\n'
                '  "dependencies": {}\n'
                '}\n',
                encoding="utf-8"
            )
            Reporter.Info(f"  Created: entry/oh-package.json5")

        # ── 9. entry/build-profile.json5 ─────────────────────────────────
        # Format minimal sans externalNativeOptions — le .so est fourni
        # directement dans entry/libs/ sans passer par CMake.
        entry_build_profile = entry_dir / "build-profile.json5"
        # ECRIT SYSTEMATIQUEMENT : quand la structure vient du template DevEco,
        # le fichier existe deja avec des options qui ne nous appartiennent pas.
        # Jenga reste maitre de ce qu'il genere (regle du projet : tout doit
        # pouvoir sortir de Jenga seul, sans heritage d'un IDE tiers).
        #
        # Forme MINIMALE volontairement. Un bloc nativeLib/abiFilters a ete
        # essaye ici et REJETE par hvigor (00303038 « Schema validate failed »).
        # Il etait de toute facon inutile : les .so precompilees deposees dans
        # entry/libs/<abi>/ sont empaquetees puis installees pour la bonne ABI
        # sans aucune declaration — verifie, la lib x86_64 arrivait bien sur
        # l'emulateur. Le vrai probleme de chargement etait l'absence de
        # libc++_shared.so dans le HAP (cf. BuildHAP).
        entry_build_profile.write_text(
            '{\n'
            '  "apiType": "stageMode",\n'
            '  "buildOption": {\n'
            '  },\n'
            '  "targets": [\n'
            '    {\n'
            '      "name": "default"\n'
            '    }\n'
            '  ]\n'
            '}\n',
            encoding="utf-8"
        )
        Reporter.Info("  Created: entry/build-profile.json5")

        # ── 10. entry/src/main/module.json5 ──────────────────────────────
        # Format officiel avec skills (intent-filter pour l'écran d'accueil).
        # Sans skills, l'app n'apparaît pas dans le launcher HarmonyOS.
        entry_main  = entry_dir / "src" / "main"
        module_json = entry_main / "module.json5"
        if not module_json.exists():
            entry_main.mkdir(parents=True, exist_ok=True)

            # requestPermissions : fusion des permissions reseau auto (si
            # networkenabled(True)) + permissions explicites harmonypermissions().
            # Sans ohos.permission.INTERNET, l'app ne peut pas ouvrir de socket
            # -> echec LAN/Internet au runtime (cf [[pong_firewall_lan_fix]]).
            try:
                from ..FirewallSpec import ResolveHarmonyNetworkPermissions
                net_perms = ResolveHarmonyNetworkPermissions(project)
            except Exception:
                net_perms = []
            seen_perms = set()
            all_perms = net_perms + list(getattr(project, 'harmonyPermissions', []))
            ordered_perms = []
            for perm in all_perms:
                if perm and perm not in seen_perms:
                    seen_perms.add(perm)
                    ordered_perms.append(perm)

            # Construit le bloc JSON5 "requestPermissions" (omis si vide pour
            # rester proche du template officiel quand l'app n'a pas de perms).
            permissions_block = ""
            if ordered_perms:
                entries = ",\n".join(
                    '      { "name": "' + p + '" }' for p in ordered_perms
                )
                permissions_block = (
                    '    "requestPermissions": [\n'
                    + entries + "\n"
                    '    ],\n'
                )

            # Orientation : ecrite UNIQUEMENT si le projet en demande une. Sans
            # cle, le systeme applique son defaut (portrait sur telephone) — ce
            # qui surprend pour une demo 3D, d'ou harmonyorientation().
            _orient = str(getattr(project, "harmonyOrientation", "") or "")
            _orientation_json = ('        "orientation": "%s",\n' % _orient) if _orient else ""
            module_json.write_text(
                '{\n'
                '  "module": {\n'
                '    "name": "entry",\n'
                '    "type": "entry",\n'
                '    "description": "$string:module_desc",\n'
                '    "mainElement": "EntryAbility",\n'
                '    "deviceTypes": [\n'
                '      "phone",\n'
                '      "tablet",\n'
                '      "2in1"\n'
                '    ],\n'
                '    "deliveryWithInstall": true,\n'
                '    "installationFree": false,\n'
                + permissions_block +
                '    "pages": "$profile:main_pages",\n'
                '    "abilities": [\n'
                '      {\n'
                '        "name": "EntryAbility",\n'
                '        "srcEntry": "./ets/entryability/EntryAbility.ets",\n'
                '        "description": "$string:EntryAbility_desc",\n'
                '        "icon": "$media:layered_image",\n'
                '        "label": "$string:EntryAbility_label",\n'
                '        "startWindowIcon": "$media:startIcon",\n'
                '        "startWindowBackground": "$color:start_window_background",\n'
                + _orientation_json +
                '        "exported": true,\n'
                '        "skills": [\n'
                '          {\n'
                '            "entities": [\n'
                '              "entity.system.home"\n'
                '            ],\n'
                '            "actions": [\n'
                '              "action.system.home"\n'
                '            ]\n'
                '          }\n'
                '        ]\n'
                '      }\n'
                '    ]\n'
                '  }\n'
                '}\n',
                encoding="utf-8"
            )
            Reporter.Info(f"  Created: entry/src/main/module.json5"
                          + (f" (+{len(ordered_perms)} permissions)" if ordered_perms else ""))

        # ── 11. entry/src/main/resources/ ────────────────────────────────
        entry_res_element = entry_main / "resources" / "base" / "element"
        entry_strings     = entry_res_element / "string.json"
        if not entry_strings.exists():
            entry_res_element.mkdir(parents=True, exist_ok=True)
            entry_strings.write_text(
                '{\n'
                '  "string": [\n'
                '    { "name": "module_desc",       "value": "module description" },\n'
                '    { "name": "EntryAbility_desc",  "value": "description" },\n'
                '    { "name": "EntryAbility_label", "value": "' + app_name + '" }\n'
                '  ]\n'
                '}\n',
                encoding="utf-8"
            )
            Reporter.Info(f"  Created: entry/src/main/resources/base/element/string.json")

        entry_color = entry_res_element / "color.json"
        if not entry_color.exists():
            entry_color.write_text(
                '{\n'
                '  "color": [\n'
                '    { "name": "start_window_background", "value": "#FFFFFF" },\n'
                '    { "name": "item_title_font",          "value": "#E6000000" }\n'
                '  ]\n'
                '}\n',
                encoding="utf-8"
            )
            Reporter.Info(f"  Created: entry/src/main/resources/base/element/color.json")

        (entry_main / "resources" / "base" / "media").mkdir(parents=True, exist_ok=True)

        # Profile pages
        entry_profile = entry_main / "resources" / "base" / "profile"
        entry_profile.mkdir(parents=True, exist_ok=True)
        main_pages = entry_profile / "main_pages.json"
        if not main_pages.exists():
            main_pages.write_text(
                '{\n'
                '  "src": [\n'
                '    "pages/Index"\n'
                '  ]\n'
                '}\n',
                encoding="utf-8"
            )
            Reporter.Info(f"  Created: entry/src/main/resources/base/profile/main_pages.json")

        # ── 12. entry/src/main/ets/entryability/EntryAbility.ets ─────────
        # Format officiel DevEco Studio avec @kit imports (hvigor 6.x).
        entry_ets     = entry_main / "ets" / "entryability"
        entry_ability = entry_ets / "EntryAbility.ets"
        if not entry_ability.exists():
            entry_ets.mkdir(parents=True, exist_ok=True)
            entry_ability.write_text(
                "import { AbilityConstant, UIAbility, Want } from '@kit.AbilityKit';\n"
                "import { hilog } from '@kit.PerformanceAnalysisKit';\n"
                "import { window } from '@kit.ArkUI';\n\n"
                "export default class EntryAbility extends UIAbility {\n"
                "  onCreate(want: Want, launchParam: AbilityConstant.LaunchParam): void {\n"
                "    hilog.info(0x0000, 'testTag', '%{public}s', 'Ability onCreate');\n"
                "  }\n\n"
                "  onDestroy(): void {\n"
                "    hilog.info(0x0000, 'testTag', '%{public}s', 'Ability onDestroy');\n"
                "  }\n\n"
                "  onWindowStageCreate(windowStage: window.WindowStage): void {\n"
                "    hilog.info(0x0000, 'testTag', '%{public}s', 'Ability onWindowStageCreate');\n"
                "    windowStage.loadContent('pages/Index', (err) => {\n"
                "      if (err.code) {\n"
                "        hilog.error(0x0000, 'testTag', 'Failed to load content. Cause: %{public}s',\n"
                "          JSON.stringify(err) ?? '');\n"
                "        return;\n"
                "      }\n"
                "      hilog.info(0x0000, 'testTag', 'Succeeded in loading the content.');\n"
                "    });\n"
                "  }\n\n"
                "  onWindowStageDestroy(): void {}\n"
                "  onForeground(): void {}\n"
                "  onBackground(): void {}\n"
                "}\n",
                encoding="utf-8"
            )
            Reporter.Info(f"  Created: entry/src/main/ets/entryability/EntryAbility.ets")

        # ── 13. entry/src/main/ets/pages/Index.ets ───────────────────────
        # Format officiel DevEco Studio avec RelativeContainer.
        entry_pages = entry_main / "ets" / "pages"
        index_page  = entry_pages / "Index.ets"
        if not index_page.exists():
            entry_pages.mkdir(parents=True, exist_ok=True)
            index_page.write_text(
                "@Entry\n"
                "@Component\n"
                "struct Index {\n"
                "  @State message: string = '" + app_name + "';\n\n"
                "  build() {\n"
                "    RelativeContainer() {\n"
                "      Text(this.message)\n"
                "        .id('HelloWorld')\n"
                "        .fontSize(50)\n"
                "        .fontWeight(FontWeight.Bold)\n"
                "        .alignRules({\n"
                "          center: { anchor: '__container__', align: VerticalAlign.Center },\n"
                "          middle: { anchor: '__container__', align: HorizontalAlign.Center }\n"
                "        })\n"
                "    }\n"
                "    .height('100%')\n"
                "    .width('100%')\n"
                "  }\n"
                "}\n",
                encoding="utf-8"
            )
            Reporter.Info(f"  Created: entry/src/main/ets/pages/Index.ets")

        # Les icones etaient preparees UNIQUEMENT dans _CustomizeHAPTemplate,
        # donc jamais sans template DevEco : hvigor s'arretait alors sur
        # « The resource reference '$media:app_icon' is not defined ». La
        # generation maison doit produire une application COMPLETE.
        self._PrepareHAPIcons(project, build_dir)

        Reporter.Success(f"[HarmonyOS] HAP project structure ready in {build_dir}")
        return True

    def _CustomizeHAPTemplate(self, project: Project, build_dir: Path,
                              bundle_name: str, version_name: str,
                              version_code: int, app_name: str,
                              compat_ver: str, lib_name: str):
        """
        Personnalise les fichiers du template DevEco Studio copié avec
        les métadonnées du projet (bundleName, versionCode, appName...).

        Modifie uniquement :
          - AppScope/app.json5 : bundleName, versionCode, versionName
          - AppScope/resources/base/element/string.json : app_name
          - build-profile.json5 : compatibleSdkVersion
          - entry/src/main/resources/base/element/string.json : labels
        """
        harmony_version_code = max(version_code, 1000000)

        # AppScope/app.json5
        app_json = build_dir / "AppScope" / "app.json5"
        if app_json.exists():
            app_json.write_text(
                '{\n'
                '  "app": {\n'
                f'    "bundleName": "{bundle_name}",\n'
                '    "vendor": "nkentseu",\n'
                f'    "versionCode": {harmony_version_code},\n'
                f'    "versionName": "{version_name}",\n'
                '    "icon": "$media:app_icon",\n'
                '    "label": "$string:app_name"\n'
                '  }\n'
                '}\n',
                encoding="utf-8"
            )

        # AppScope/resources/base/element/string.json
        app_strings = build_dir / "AppScope" / "resources" / "base" / "element" / "string.json"
        if app_strings.exists():
            app_strings.write_text(
                '{\n'
                '  "string": [\n'
                '    {\n'
                f'      "name": "app_name",\n'
                f'      "value": "{app_name}"\n'
                '    }\n'
                '  ]\n'
                '}\n',
                encoding="utf-8"
            )

        # build-profile.json5 — mettre à jour compatibleSdkVersion
        build_profile = build_dir / "build-profile.json5"
        if build_profile.exists():
            content = build_profile.read_text(encoding="utf-8")
            # Remplacer la valeur existante de compatibleSdkVersion
            import re
            content = re.sub(
                r'"compatibleSdkVersion"\s*:\s*"[^"]*"',
                f'"compatibleSdkVersion": "{compat_ver}"',
                content
            )
            build_profile.write_text(content, encoding="utf-8")

        # entry/src/main/resources/base/element/string.json — labels Ability
        entry_strings = (build_dir / "entry" / "src" / "main" /
                         "resources" / "base" / "element" / "string.json")
        if entry_strings.exists():
            entry_strings.write_text(
                '{\n'
                '  "string": [\n'
                '    { "name": "module_desc",       "value": "module description" },\n'
                '    { "name": "EntryAbility_desc",  "value": "description" },\n'
                f'   {{ "name": "EntryAbility_label", "value": "{app_name}" }}\n'
                '  ]\n'
                '}\n',
                encoding="utf-8"
            )

        # Préparer les icônes si configurées dans le projet
        self._PrepareHAPIcons(project, build_dir)

        Reporter.Info(f"  Customized template with project metadata ({bundle_name})")

    # -----------------------------------------------------------------------
    # Packaging HAP
    # -----------------------------------------------------------------------

    # Nom du dossier ABI attendu par hvigor dans entry/libs/. Une seule source
    # de verite : la table etait auparavant codee en dur sur "arm64-v8a".
    _ABI_DIRS = {
        TargetArch.ARM:    "armeabi-v7a",
        TargetArch.ARM64:  "arm64-v8a",
        TargetArch.X86_64: "x86_64",
    }

    def _AbiDirName(self, arch=None) -> str:
        return self._ABI_DIRS.get(arch or self.targetArch, "arm64-v8a")

    def BuildHAP(self, project: Project, native_libs) -> bool:
        """
        Assemble un .hap HarmonyOS à partir des .so compilés.

        Étapes :
          1. Créer le dossier de build HAP dans Build/ (pas dans les sources)
          2. Générer la structure de projet HAP (_GenerateHAPProject)
          3. Copier les .so dans entry/libs/arm64-v8a/
          4. Invoquer hvigorw assembleHap
          5. Copier le .hap final dans le dossier de sortie Jenga
          6. Signer si harmonysign(True) (_SignHAP)

        Équivalent Android : BuildAPK() dans AndroidBuilder.
        """
        Reporter.Info(f"[HarmonyOS] Building HAP for {project.name}")

        # Étape 1 : dossier de build dans Build/ (pas dans les sources)
        build_dir = self._GetHAPBuildDir(project)
        FileSystem.MakeDirectory(build_dir)

        # Étape 2 : générer la structure HAP
        if not self._GenerateHAPProject(project, build_dir):
            Colored.PrintError("[HarmonyOS] Echec de la generation de la structure HAP.")
            return False

        # Étape 2b : copier les ressources utilisateur si déclarées
        self._CopyHarmonyResources(project, build_dir)
        self._CopyHarmonyAssets(project, build_dir)

        # Étape 2c : copier les fichiers ArkTS/ETS utilisateur
        # Ce sont des fichiers de CODE compilés par hvigor (pas des ressources).
        # Ils vont dans entry/src/main/ets/ et sont intégrés au HAP.
        self._CopyHarmonyArkTSFiles(project, build_dir)

        # Étape 3 : copier les .so dans entry/libs/<ABI>/, une entree par ABI
        #
        # Le dossier etait code en dur sur "arm64-v8a". Les emulateurs
        # HarmonyOS-NEXT sur PC tournent pourtant en x86_64 (comme les AVD
        # Android x86_64 sur hote x86) : un HAP dont les .so sont ranges sous
        # arm64-v8a y est refuse a l'installation avec
        #
        #     error: install parse native so failed. code:9568347
        #
        # message qui ne mentionne nulle part l'architecture. On derive donc le
        # dossier de l'architecture REELLEMENT compilee.
        # `native_libs` accepte les DEUX formes : une liste (une seule ABI, celle
        # compilee) ou un dictionnaire {abi: [libs]} produit par le chemin
        # multi-ABI. La seconde evite de dupliquer toute cette fonction.
        if isinstance(native_libs, dict):
            libs_par_abi = native_libs
        else:
            libs_par_abi = {self._AbiDirName(): list(native_libs)}

        # Triple du NDK par dossier ABI — pour retrouver la STL a embarquer.
        # ATTENTION : le dossier de lib 32 bits du NDK s'appelle arm-linux-ohos,
        # PAS armv7a-linux-ohos (qui n'est que le triple de COMPILATION).
        stl_triples = {
            "armeabi-v7a": "arm-linux-ohos",
            "arm64-v8a":   "aarch64-linux-ohos",
            "x86_64":      "x86_64-linux-ohos",
        }
        for abi_dir, libs in libs_par_abi.items():
            libs_dir = build_dir / "entry" / "libs" / abi_dir
            libs_dir.mkdir(parents=True, exist_ok=True)
            for lib in libs:
                lib_path = Path(lib)
                shutil.copy2(lib_path, libs_dir / lib_path.name)
                Reporter.Info(f"  Copied: {lib_path.name} -> entry/libs/{abi_dir}/")

            # ── libc++_shared.so : OBLIGATOIRE dans le HAP ─────────────────────
            # Meme regle qu'Android : le systeme ne fournit PAS la STL du NDK.
            # Verifie sur l'emulateur HarmonyOS-NEXT : /system/lib64 n'a aucune
            # libc++_shared.so, alors que la .so du projet la declare en NEEDED.
            # Sans elle, dlopen echoue en silence au chargement du XComponent :
            # l'ArkTS recoit `undefined` en guise d'exports et plante sur
            #     TypeError: Cannot read property nkSetResMgr of undefined
            # — un symptome qui ne designe jamais la vraie cause. Le chemin
            # Android (_BuildUniversalAPK) faisait deja cet embarquement ; celui
            # de HarmonyOS ne l'avait jamais fait, et ne pouvait pas etre pris en
            # defaut tant que l'installation arm64-seule echouait avant meme
            # d'executer quoi que ce soit.
            deja = any(Path(l).name == "libc++_shared.so" for l in libs)
            triple = stl_triples.get(abi_dir)
            if not deja and triple and self.ndk_path:
                stl = self.ndk_path / "llvm" / "lib" / triple / "libc++_shared.so"
                if stl.exists():
                    shutil.copy2(stl, libs_dir / stl.name)
                    Reporter.Info(f"  Copied: libc++_shared.so ({triple}) -> entry/libs/{abi_dir}/")
                else:
                    Reporter.Warning(
                        f"libc++_shared.so introuvable pour {abi_dir} ({stl}) — "
                        "le HAP risque d'echouer au chargement de la .so"
                    )

        # Étape 4 : trouver hvigorw
        cli_tools = self._ResolveCliTools()
        hvigor    = cli_tools / "bin" / "hvigorw.bat"
        if not hvigor.exists():
            hvigor = cli_tools / "bin" / "hvigorw"
        if not hvigor.exists():
            Colored.PrintError(
                f"hvigorw introuvable dans {cli_tools / 'bin'}.\n"
                "Verifiez que les HarmonyOS Command Line Tools sont installes dans C:/ohos/"
            )
            return False

        # Étape 5 : lancer hvigorw assembleHap
        # cwd = build_dir pour que hvigor trouve hvigorfile.ts et build-profile.json5
        Reporter.Info(f"  Running: hvigorw assembleHap in {build_dir}")
        result = subprocess.run(
            [str(hvigor), "assembleHap", "--mode", "module", "-p", "product=default"],
            cwd=str(build_dir)
        )
        if result.returncode != 0:
            Colored.PrintError(
                "[HarmonyOS] hvigorw assembleHap a echoue.\n"
                "Verifiez que :\n"
                "  - Node.js est installe et dans le PATH\n"
                "  - Les dependances ohpm sont accessibles"
            )
            return False

        # Étape 6 : récupérer le .hap généré (entry/build/default/outputs/default/)
        hap_files = list(build_dir.rglob("*.hap"))
        if not hap_files:
            Colored.PrintError("[HarmonyOS] Aucun .hap genere par hvigor.")
            return False

        # Étape 7 : copier le .hap dans le dossier de sortie Jenga
        target_dir = self.GetTargetDir(project)
        FileSystem.MakeDirectory(target_dir)
        final_hap  = target_dir / f"{project.targetName or project.name}.hap"
        shutil.copy2(hap_files[0], final_hap)
        Reporter.Success(f"[HarmonyOS] HAP generated: {final_hap}")

        # Étape 8 : signature optionnelle
        if getattr(project, 'harmonySign', False):
            return self._SignHAP(project, final_hap)

        return True

    # -----------------------------------------------------------------------
    # Signature HAP
    # -----------------------------------------------------------------------

    def _SignHAP(self, project: Project, hap_path: Path) -> bool:
        """
        Signe un .hap avec hap-sign-tool.jar (outil officiel Huawei).

        Prérequis configurés dans le .jenga :
          harmonykeystore("path/to/key.p12")
          harmonycertfile("path/to/cert.cer")
          harmonyprofile("path/to/profile.p7b")
          harmonykeypwd("password")           # optionnel
          harmonykeyed("alias")               # optionnel, défaut: harmony

        Équivalent Android : _SignApk() avec apksigner.
        """
        sign_tool = self._FindHapSignTool()
        if not sign_tool:
            Colored.PrintError(
                "[HarmonyOS] hap-sign-tool.jar introuvable.\n"
                "Telechargez-le depuis :\n"
                "  https://developer.huawei.com/consumer/en/doc/harmonyos-guides/ide-hapsigntool\n"
                "Ou definissez HAP_SIGN_TOOL vers le .jar"
            )
            return False

        cert_file = getattr(project, 'harmonyCertFile', '') or ''
        profile   = getattr(project, 'harmonyProfile',  '') or ''
        keystore  = getattr(project, 'harmonyKeystore', '') or ''
        key_alias = getattr(project, 'harmonyKeyAlias', '') or 'harmony'
        key_pwd   = getattr(project, 'harmonyKeyPwd',   '') or ''

        if not cert_file or not profile or not keystore:
            Colored.PrintError(
                "[HarmonyOS] Parametres de signature manquants.\n"
                "Configurez dans votre .jenga :\n"
                "  harmonycertfile('path/to/cert.cer')\n"
                "  harmonyprofile('path/to/profile.p7b')\n"
                "  harmonykeystore('path/to/key.p12')"
            )
            return False

        signed_hap = hap_path.with_name(hap_path.stem + "-signed.hap")

        cmd = [
            "java", "-jar", str(sign_tool),
            "sign-app",
            "-keyAlias",     key_alias,
            "-keyPwd",       key_pwd,
            "-appCertFile",  cert_file,
            "-profileFile",  profile,
            "-keystoreFile", keystore,
            "-inFile",       str(hap_path),
            "-outFile",      str(signed_hap),
            "-signAlg",      "SHA256withECDSA",
        ]

        Reporter.Info(f"[HarmonyOS] Signing HAP...")
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            Reporter.Success(f"[HarmonyOS] HAP signed: {signed_hap}")
            shutil.move(str(signed_hap), str(hap_path))
            return True
        else:
            Colored.PrintError(f"[HarmonyOS] Signature echouee :\n{result.stderr}")
            return False

    def _FindHapSignTool(self) -> Optional[Path]:
        """
        Cherche hap-sign-tool.jar dans :
          1. Variable HAP_SIGN_TOOL
          2. command-line-tools/tool/lib/hap-sign-tool.jar
          3. command-line-tools/hap-sign-tool.jar
          4. C:/ohos/hap-sign-tool.jar
        """
        env_path = os.environ.get("HAP_SIGN_TOOL", "")
        if env_path and Path(env_path).exists():
            return Path(env_path)

        cli_tools = self._ResolveCliTools()
        candidates = [
            cli_tools / "tool" / "lib" / "hap-sign-tool.jar",
            cli_tools / "hap-sign-tool.jar",
            Path("C:/ohos/hap-sign-tool.jar"),
        ]
        for candidate in candidates:
            if candidate.exists():
                return candidate

        return None

    # -----------------------------------------------------------------------
    # Build principal
    # -----------------------------------------------------------------------

    def _BuildUniversalHAP(self, project: Project, target_abis: List[str]) -> bool:
        """Compile le projet pour CHAQUE ABI demandee et assemble un HAP unique.

        Transposition de `AndroidBuilder._BuildUniversalAPK` : meme mecanisme de
        redirection par ABI des dossiers de sortie (`_filteredTargetDir` /
        `_filteredObjDir`), sans quoi les archives .a et les .so d'architectures
        differentes se melangeraient dans les memes dossiers — et le lien
        prendrait silencieusement l'objet de la mauvaise ABI.

        Raison d'etre : les emulateurs HarmonyOS-NEXT sur PC tournent en x86_64
        (verifie : `const.product.cpu.abilist` = x86_64), alors que les appareils
        reels sont en arm64. Un HAP mono-ABI ne peut donc pas servir aux deux, et
        l'echec cote emulateur est particulierement muet :

            error: install parse native so failed. code:9568347
        """
        Reporter.Info(
            f"Building universal HAP for {project.name} "
            f"({len(target_abis)} ABIs: {', '.join(target_abis)})"
        )

        abi_to_arch = {
            "armeabi-v7a": TargetArch.ARM,
            "arm64-v8a":   TargetArch.ARM64,
            "x86_64":      TargetArch.X86_64,
        }

        # Le cache de workspace ne suit pas les changements de plateforme/arch :
        # on s'appuie sur les horodatages (meme choix que le chemin Android).
        original_cache_status = getattr(self.workspace, "_cache_status", None)
        self.workspace._cache_status = None
        original_arch = self.targetArch
        original_platform = self.platform
        sentinel = object()
        all_native_libs = {}

        try:
            for abi in target_abis:
                if abi not in abi_to_arch:
                    Reporter.Warning(f"ABI inconnue : {abi}, ignoree")
                    continue
                Reporter.Info(f"  -> Compilation pour {abi}...")

                self.targetArch = abi_to_arch[abi]
                self.platform = f"harmonyos-{abi}"
                self._PrepareToolchain()

                abi_tag = f"{self.config}-HarmonyOS-{abi}"
                abi_filter = f"platform:{self.platform}"
                restore = {}
                for proj_name, proj_ctx in self.workspace.projects.items():
                    if proj_name.startswith("__"):
                        continue
                    if proj_ctx.kind in (ProjectKind.STATIC_LIB, ProjectKind.SHARED_LIB):
                        forced_target = Path(self.workspace.location) / "Build" / "Lib" / abi_tag / proj_ctx.name
                    elif proj_ctx.kind == ProjectKind.TEST_SUITE:
                        forced_target = Path(self.workspace.location) / "Build" / "Tests" / abi_tag
                    else:
                        forced_target = Path(self.workspace.location) / "Build" / "Bin" / abi_tag / proj_ctx.name
                    forced_obj = Path(self.workspace.location) / "Build" / "Obj" / abi_tag / proj_ctx.name

                    restore[proj_name] = {
                        "targetDir": proj_ctx.targetDir,
                        "objDir": proj_ctx.objDir,
                        "appliedContext": getattr(proj_ctx, "_jenga_applied_filter_context", None),
                        "filteredTargetDir": proj_ctx._filteredTargetDir.get(abi_filter, sentinel),
                        "filteredObjDir": proj_ctx._filteredObjDir.get(abi_filter, sentinel),
                    }
                    proj_ctx._filteredTargetDir[abi_filter] = str(forced_target.resolve())
                    proj_ctx._filteredObjDir[abi_filter] = str(forced_obj.resolve())
                    proj_ctx._jenga_applied_filter_context = None

                native_libs = []
                success = False
                try:
                    success = (super(HarmonyOsBuilder, self).Build(project.name) == 0)
                    if success:
                        # Collecte AVANT restauration : c'est la seule fenetre ou
                        # GetTargetPath rend les chemins de CETTE ABI.
                        out = self.GetTargetPath(project)
                        if out.exists():
                            native_libs.append(str(out))
                        for dep_name in project.dependsOn:
                            dep = self.workspace.projects.get(dep_name)
                            if not dep:
                                continue
                            dep_out = self.GetTargetPath(dep)
                            if dep.kind == ProjectKind.SHARED_LIB and dep_out.exists():
                                native_libs.append(str(dep_out))
                finally:
                    for proj_name, snap in restore.items():
                        proj_ctx = self.workspace.projects.get(proj_name)
                        if not proj_ctx:
                            continue
                        if snap["filteredTargetDir"] is sentinel:
                            proj_ctx._filteredTargetDir.pop(abi_filter, None)
                        else:
                            proj_ctx._filteredTargetDir[abi_filter] = snap["filteredTargetDir"]
                        if snap["filteredObjDir"] is sentinel:
                            proj_ctx._filteredObjDir.pop(abi_filter, None)
                        else:
                            proj_ctx._filteredObjDir[abi_filter] = snap["filteredObjDir"]
                        proj_ctx.targetDir = snap["targetDir"]
                        proj_ctx.objDir = snap["objDir"]
                        proj_ctx._jenga_applied_filter_context = snap["appliedContext"]

                if not success:
                    Reporter.Error(f"Echec de la compilation pour {abi}")
                    return False
                if not native_libs:
                    Reporter.Warning(f"Aucune bibliotheque native pour {abi}")
                else:
                    all_native_libs[abi] = native_libs
                    Reporter.Success(f"  {abi} compile ({len(native_libs)} lib(s))")

            if not all_native_libs:
                Reporter.Error("Aucune bibliotheque native pour aucune ABI")
                return False
            return self.BuildHAP(project, all_native_libs)
        finally:
            self.targetArch = original_arch
            self.platform = original_platform
            self._PrepareToolchain()
            self.workspace._cache_status = original_cache_status

    def Build(self, targetProject: Optional[str] = None) -> int:
        """
        Build principal : compile puis package en .hap si WINDOWED_APP.

        WINDOWED_APP  → compile .so + BuildHAP
        SHARED_LIB    → compile .so uniquement
        STATIC_LIB    → compile .a uniquement
        CONSOLE_APP   → compile ELF uniquement

        Équivalent Android : Build() → BuildAPK() dans AndroidBuilder.
        """
        # Multi-ABI demande (harmonyabis) : chemin dedie, qui compile lui-meme
        # une fois par ABI. On ne passe donc PAS par la compilation simple.
        if targetProject:
            proj = self.workspace.projects.get(targetProject)
            abis = list(getattr(proj, "harmonyAbis", []) or []) if proj else []
            if proj and proj.kind == ProjectKind.WINDOWED_APP and len(abis) > 1:
                return 0 if self._BuildUniversalHAP(proj, abis) else 1

        # Étape 1 : compilation via la classe de base
        code = super().Build(targetProject)
        if code != 0:
            return code

        # Étape 2 : packaging HAP pour les WINDOWED_APP uniquement
        for name, proj in self.workspace.projects.items():
            if targetProject and name != targetProject:
                continue

            if proj.kind != ProjectKind.WINDOWED_APP:
                continue

            # Bibliothèque principale
            native_libs = []
            out = self.GetTargetPath(proj)
            if out.exists():
                native_libs.append(str(out))

            # Dépendances SHARED_LIB (comme AndroidBuilder pour les APK)
            for dep_name in proj.dependsOn:
                dep = self.workspace.projects.get(dep_name)
                if not dep:
                    continue
                dep_out = self.GetTargetPath(dep)
                if dep.kind == ProjectKind.SHARED_LIB and dep_out.exists():
                    native_libs.append(str(dep_out))

            if not native_libs:
                Reporter.Error(
                    f"[HarmonyOS] Aucune bibliotheque native trouvee pour '{proj.name}'."
                )
                return 1

            if not self.BuildHAP(proj, native_libs):
                return 1

        return 0