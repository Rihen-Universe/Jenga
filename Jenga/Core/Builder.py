#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Builder – Classe de base pour tous les builders de plateforme.
Coordonne le build : résolution des dépendances, compilation, link.
"""

import abc
import hashlib
import json
import time
import glob
import re
import fnmatch
import os
import shutil
import multiprocessing
import concurrent.futures
from typing import List, Dict, Optional, Any, Tuple, Set
from pathlib import Path

from Jenga.Core import Api
from Jenga.Core.Api import Workspace, Project, Toolchain, ProjectKind, TargetOS, TargetArch, TargetEnv, CompilerFamily
from ..Utils import FileSystem, Process, Colored, Reporter, BuildLogger, ProcessResult
from .State import BuildState
from .DependencyResolver import DependencyResolver
from .Toolchains import ToolchainManager
from .Platform import Platform
 
 
# ---------------------------------------------------------------------------
# Extensions de fichiers — constantes partagées entre tous les builders
# ---------------------------------------------------------------------------
 
# Extensions compilables par le compilateur natif C/C++/ObjC/ASM
NATIVE_COMPILABLE_EXTENSIONS: Set[str] = {
    '.c',
    '.cpp', '.cc', '.cxx', '.c++',
    '.cppm', '.ixx', '.mpp', '.c++m',   # C++20 modules
    '.m',                                 # Objective-C
    '.mm',                                # Objective-C++
    '.s', '.asm', '.S',                   # Assembleur
    '.rs',                                # Rust
    '.zig',                               # Zig
}
 
# Extensions gérées par des builders platform-spécifiques (pas par le compilateur natif)
# Ces fichiers sont déclarables dans files() mais ne passent pas dans Compile().
PLATFORM_SPECIFIC_EXTENSIONS: Dict[str, str] = {
    # HarmonyOS ArkTS — copiés dans entry/src/main/ets/ par HarmonyOsBuilder
    '.ts':   'harmonyos',
    '.ets':  'harmonyos',
    # Swift — compilé par XcodeBuilder (jamais par clang++ direct)
    '.swift': 'xcode',
    # Kotlin/Java Android — compilés par AndroidBuilder (javac + d8)
    '.kt':   'android',
    '.java': 'android',
    # Shaders — compilés par un shader compiler dédié (futur)
    '.hlsl': 'shader',
    '.glsl': 'shader',
    '.metal': 'xcode',
}


class Builder(abc.ABC):
    """
    Classe abstraite de base pour un builder spécifique à une plateforme/cible.
    Chaque sous-classe doit implémenter :
      - Compile()
      - Link()
      - GetOutputExtension()
    """

    def __init__(self,
                 workspace: Workspace,
                 config: str,
                 platform: str,
                 targetOs: TargetOS,
                 targetArch: TargetArch,
                 targetEnv: Optional[TargetEnv] = None,
                 verbose: bool = False,
                 action: str = "build",
                 options: Optional[List[str]] = None):
        self.workspace = workspace
        self.config = config
        self.platform = platform
        self.targetOs = targetOs
        self.targetArch = targetArch
        # Keep target env optional: when unspecified, toolchain resolution can
        # pick the best available ABI/environment for the target OS.
        self.targetEnv = targetEnv
        self.verbose = verbose
        self.action = (action or "build").strip().lower()
        self.options = sorted({str(opt).strip().lower() for opt in (options or []) if str(opt).strip()})

        self._expander = None
        if workspace:
            from .Variables import VariableExpander
            self._expander = VariableExpander(workspace=workspace)
            platform_value = platform if platform else targetOs.value
            target_env_value = targetEnv.value if targetEnv else ""
            self._expander.SetConfig({
                'name': config,
                'buildcfg': config,
                'configuration': config,
                'platform': platform_value,
                'system': targetOs.value,
                'os': targetOs.value,
                'arch': targetArch.value,
                'architecture': targetArch.value,
                'targetos': targetOs.value,
                'targetarch': targetArch.value,
                'env': target_env_value,
                'targetenv': target_env_value,
                'action': self.action,
                'options': " ".join(self.options),
            })

        # Create BuildState with platform/arch context for multi-ABI builds
        self.state = BuildState(workspace, platform=platform, targetArch=targetArch.value if targetArch else "")
        self.toolchainManager = ToolchainManager(workspace)
        self.toolchain: Optional[Toolchain] = None
        self._lastResult = None  # Last ProcessResult from compile/link

        # Parallel compilation: 0 = auto-detect, 1 = sequential, N = N jobs
        self.jobs = 0  # Will be set by BuildCommand.CreateBuilder()

        self._ValidateHostTarget()
        self._ResolveToolchain()

    def _ValidateHostTarget(self):
        host_os = Platform.GetHostOS()
        if self.targetOs == TargetOS.MACOS and host_os != TargetOS.MACOS:
            raise RuntimeError(f"Cannot build for macOS from {host_os.value}. macOS builds require macOS with Apple toolchain.")
        if self.targetOs == TargetOS.IOS and host_os != TargetOS.MACOS:
            raise RuntimeError(f"Cannot build for iOS from {host_os.value}. iOS builds require macOS with Xcode.")
        if self.targetOs in (TargetOS.XBOX_ONE, TargetOS.XBOX_SERIES) and host_os != TargetOS.WINDOWS:
            raise RuntimeError(f"Cannot build for Xbox from {host_os.value}. Xbox builds require Windows with Microsoft GDK.")
        if self.targetOs == TargetOS.TVOS and host_os != TargetOS.MACOS:
            raise RuntimeError("tvOS builds require macOS.")
        if self.targetOs == TargetOS.WATCHOS and host_os != TargetOS.MACOS:
            raise RuntimeError("watchOS builds require macOS.")
        if self.targetOs == TargetOS.VISIONOS and host_os != TargetOS.MACOS:
            raise RuntimeError("visionOS builds require macOS with Xcode 15+.")

    def _ResolveToolchain(self) -> None:
        if self.workspace.defaultToolchain:
            tc_name = self.workspace.defaultToolchain
            tc = self.workspace.toolchains.get(tc_name)
            if tc:
                self.toolchain = tc
                return
        self.toolchainManager.DetectAll(self.workspace)
        # Merge workspace-registered toolchains (global registry) into detected set
        for tc_name, tc in self.workspace.toolchains.items():
            if tc_name not in self.toolchainManager._detected:
                self.toolchainManager.AddToolchain(tc)
        prefer = []
        if self.targetOs == TargetOS.WINDOWS:
            if Platform.GetHostOS() != TargetOS.WINDOWS:
                # Cross-compile from Linux/macOS: prefer mingw (has full STL headers)
                prefer = ['mingw', 'clang-mingw', 'clang-cl', 'msvc', 'zig-windows-x64', 'host-clang', 'host-gcc']
            else:
                prefer = ['clang-mingw', 'mingw', 'clang-cl', 'msvc', 'zig-windows-x64', 'host-clang', 'host-gcc']
        elif self.targetOs == TargetOS.LINUX:
            if Platform.GetHostOS() == TargetOS.LINUX:
                # Native Linux: prefer system compilers, then zig
                prefer = ['host-clang', 'host-gcc', 'zig-linux-x64', 'zig-linux-x86_64', 'clang-cross-linux', 'gcc-cross-linux']
            else:
                # Cross-compile from Windows/macOS: prefer zig
                prefer = ['zig-linux-x64', 'zig-linux-x86_64', 'clang-cross-linux', 'gcc-cross-linux', 'host-clang', 'host-gcc']
        elif self.targetOs == TargetOS.MACOS:
            prefer = ['host-apple-clang', 'host-clang', 'zig-macos-arm64', 'zig-macos-x86_64', 'host-gcc']
        elif self.targetOs == TargetOS.ANDROID:
            prefer = ['android-ndk', 'zig-android-arm64']
        elif self.targetOs == TargetOS.IOS:
            prefer = ['host-apple-clang']
        elif self.targetOs == TargetOS.TVOS:
            prefer = ['host-apple-clang']
        elif self.targetOs == TargetOS.WATCHOS:
            prefer = ['host-apple-clang']
        elif self.targetOs == TargetOS.VISIONOS:
            prefer = ['host-apple-clang']
        elif self.targetOs == TargetOS.WEB:
            prefer = ['emscripten', 'zig-web-wasm32']
        elif self.targetOs == TargetOS.HARMONYOS:
            prefer = ['ohos-ndk']
        tc_name = self.toolchainManager.ResolveForTarget(self.targetOs, self.targetArch, self.targetEnv, prefer=prefer)
        # Apple mobile targets (iOS/tvOS/watchOS) are compiled with host Apple Clang.
        # Detected host toolchain is usually tagged as macOS; fallback to macOS lookup.
        if not tc_name and self.targetOs in (TargetOS.IOS, TargetOS.TVOS, TargetOS.WATCHOS, TargetOS.VISIONOS):
            tc_name = self.toolchainManager.ResolveForTarget(TargetOS.MACOS, self.targetArch, None, prefer=prefer)
        if tc_name:
            self.toolchain = self.toolchainManager.GetToolchain(tc_name)
        if not self.toolchain:
            raise RuntimeError(f"No suitable toolchain found for {self.targetOs.value} {self.targetArch.value}")

        # Auto-detect and enable ccache/sccache for faster builds
        self._DetectCompilerCache()

    def _DetectCompilerCache(self) -> None:
        """
        Détecte et active ccache/sccache automatiquement.

        ccache/sccache accélèrent drastiquement les recompilations:
        - Stocke les fichiers .o compilés dans un cache global basé sur le hash du source
        - Si le même .cpp est compilé 2x avec les mêmes flags → réutilise le .o existant
        - Gain: 10-100x plus rapide pour les rebuilds (après clean par exemple)

        Priorité: sccache (plus moderne, multi-plateforme) > ccache
        """
        import shutil

        # Check if user disabled compiler cache via environment variable
        if os.environ.get('JENGA_DISABLE_CCACHE', '').lower() in ('1', 'true', 'yes'):
            return

        # Detect available compiler cache (sccache preferred over ccache)
        cache_wrapper = None
        if shutil.which("sccache"):
            cache_wrapper = "sccache"
        elif shutil.which("ccache"):
            cache_wrapper = "ccache"

        if not cache_wrapper:
            return

        # Wrap compiler paths with cache wrapper
        # Note: Only wrap for GCC/Clang-compatible compilers, not MSVC
        # (sccache supports MSVC, but integration is more complex)
        if self.toolchain.compilerFamily in (CompilerFamily.GCC, CompilerFamily.CLANG, CompilerFamily.APPLE_CLANG):
            # Store original paths
            if not hasattr(self.toolchain, '_original_ccPath'):
                self.toolchain._original_ccPath = self.toolchain.ccPath
            if not hasattr(self.toolchain, '_original_cxxPath'):
                self.toolchain._original_cxxPath = self.toolchain.cxxPath

            # Wrap with cache
            if self.toolchain.ccPath:
                self.toolchain.ccPath = Path(cache_wrapper)
                # Store actual compiler as environment variable for cache to use
                os.environ['CCACHE_CC'] = str(self.toolchain._original_ccPath)
            if self.toolchain.cxxPath:
                self.toolchain.cxxPath = Path(cache_wrapper)
                os.environ['CCACHE_CXX'] = str(self.toolchain._original_cxxPath)

            if self.verbose:
                Reporter.Info(f"Using {cache_wrapper} for faster builds")

    def _GetEffectiveJobs(self) -> int:
        """
        Calcule le nombre effectif de jobs de compilation parallèle.

        Returns:
            - self.jobs si > 0 (défini explicitement)
            - (CPU cores - 1) si self.jobs == 0 (auto-detect)
            - 1 minimum (compilation séquentielle)
        """
        if self.jobs > 0:
            return self.jobs

        # Auto-detect: utiliser (N cores - 1) pour laisser de la marge au système
        try:
            cpu_count = multiprocessing.cpu_count()
            return max(1, cpu_count - 1)
        except Exception:
            # Fallback si multiprocessing.cpu_count() échoue
            return 1

    # -----------------------------------------------------------------------
    # Méthodes abstraites
    # -----------------------------------------------------------------------

    @abc.abstractmethod
    def Compile(self, project: Project, sourceFile: str, objectFile: str) -> ProcessResult:
        """
        Compile un fichier source.
        Retourne un ProcessResult contenant le code de retour, stdout et stderr.
        """
        pass

    @abc.abstractmethod
    def Link(self, project: Project, objectFiles: List[str], outputFile: str) -> bool:
        pass

    @abc.abstractmethod
    def GetOutputExtension(self, project: Project) -> str:
        pass

    @abc.abstractmethod
    def GetObjectExtension(self) -> str:
        pass

    @abc.abstractmethod
    def GetModuleFlags(self, project: Project, sourceFile: str) -> List[str]:
        """Retourne les flags de compilation pour un fichier module C++20."""
        pass

    def PreparePCH(self, project: Project, objDir: Path) -> bool:
        """
        Optional PCH preparation hook.
        Builders may set:
          - project._jengaPchFile
          - project._jengaPchHeaderResolved
          - project._jengaPchSourceResolved
        """
        return True

    # -----------------------------------------------------------------------
    # Hook : copie des bibliothèques dynamiques dans le dossier de l'application
    # -----------------------------------------------------------------------


    # -----------------------------------------------------------------------
    # API pour les fichiers platform-spécifiques (.ts/.ets/.swift/.java...)
    # -----------------------------------------------------------------------

    @staticmethod
    def IsPlatformSpecificFile(sourceFile: str) -> bool:
        """
        Retourne True si le fichier est géré par un builder platform-spécifique
        et NE DOIT PAS être compilé par le compilateur natif C/C++.

        Fichiers reconnus :
          .ts / .ets  → HarmonyOS ArkTS (copié dans HAP par HarmonyOsBuilder)
          .swift      → Swift (XcodeBuilder)
          .kt / .java → Kotlin/Java (AndroidBuilder)
          .hlsl/.glsl → Shaders (ShaderBuilder)
          .metal      → Metal (XcodeBuilder)
        """
        return Path(sourceFile).suffix.lower() in PLATFORM_SPECIFIC_EXTENSIONS

    @staticmethod
    def IsNativeCompilable(sourceFile: str) -> bool:
        """
        Retourne True si le fichier est compilable par le compilateur natif.
        Exclut les fichiers platform-spécifiques (.ts, .ets, .swift, etc.).
        """
        ext = Path(sourceFile).suffix.lower()
        return ext in NATIVE_COMPILABLE_EXTENSIONS and ext not in PLATFORM_SPECIFIC_EXTENSIONS

    def GetPlatformSpecificFiles(self, project: Project,
                                  extensions: Optional[List[str]] = None) -> List[str]:
        """
        Retourne les fichiers platform-spécifiques déclarés dans files() du projet.

        C'est la méthode que les builders platform utilisent pour récupérer
        leurs fichiers depuis files() — même logique que .mm pour Cocoa.

        Usage dans HarmonyOsBuilder :
          arkts = self.GetPlatformSpecificFiles(project, ['.ts', '.ets'])
          # → ["harmony/ets/NkHarmonyBridge.ts", "harmony/ets/EntryAbility.ets"]

        Usage dans AndroidBuilder :
          java_files = self.GetPlatformSpecificFiles(project, ['.java', '.kt'])

        Args:
          project    : projet à analyser
          extensions : liste d'extensions à filtrer (None = toutes les platform-spécifiques)
        """
        if extensions is None:
            target_exts = set(PLATFORM_SPECIFIC_EXTENSIONS.keys())
        else:
            target_exts = {e.lower() for e in extensions}

        result = []
        all_files = self._CollectAllDeclaredFiles(project)
        for f in all_files:
            p = Path(f)
            if p.suffix.lower() in target_exts and p.exists():
                result.append(str(p))
        return result

    def _CollectAllDeclaredFiles(self, project: Project) -> List[str]:
        """
        Résout TOUS les fichiers déclarés dans files() du projet, quelle que soit
        leur extension. Utilisé pour extraire les fichiers platform-spécifiques.

        Contrairement à _CollectSourceFiles(), ne filtre PAS par extension —
        retourne tout ce que files() et les filtres actifs déclarent.
        """
        result = []
        workspace_base = Path(self.workspace.location).resolve() \
            if self.workspace and self.workspace.location else Path.cwd()

        if project.location:
            base_dir_str = project.location
            if self._expander:
                self._expander.SetProject(project)
                base_dir_str = self._expander.Expand(base_dir_str, recursive=True)
            base_dir_path = Path(base_dir_str)
            if not base_dir_path.is_absolute():
                base_dir_path = workspace_base / base_dir_path
            base_dir = base_dir_path.resolve()
        else:
            base_dir = workspace_base

        # Patterns depuis files() + filtres actifs
        all_patterns = list(project.files)
        for filter_name, ffiles in getattr(project, '_filteredFiles', {}).items():
            if self._FilterMatches(filter_name, project):
                all_patterns.extend(ffiles)

        for pattern in all_patterns:
            expanded = pattern
            if self._expander:
                self._expander.SetProject(project)
                expanded = self._expander.Expand(pattern, recursive=True)
            p = Path(expanded)
            if p.is_absolute():
                if any(ch in expanded for ch in ('*', '?', '[')):
                    result.extend(m for m in glob.glob(expanded, recursive=True)
                                  if Path(m).is_file())
                elif p.exists():
                    result.append(str(p))
            else:
                matched = FileSystem.ListFiles(base_dir, pattern=expanded,
                                               recursive=True, fullPath=True)
                result.extend(matched)

        return result

    def GetSharedLibExtensions(self) -> List[str]:
        """
        Retourne la liste des extensions de bibliothèques dynamiques
        pour le système cible courant.
        Peut être surchargée par les sous-classes (ex: EmscriptenBuilder → .wasm).
        """
        if self.targetOs == TargetOS.WINDOWS:
            return [".dll"]
        elif self.targetOs == TargetOS.MACOS:
            return [".dylib"]
        elif self.targetOs == TargetOS.IOS:
            return [".dylib"]
        elif self.targetOs == TargetOS.ANDROID:
            return [".so"]
        elif self.targetOs == TargetOS.WEB:
            return [".wasm"]
        else:
            # Linux, et tous les autres Unix-like
            return [".so"]

    def CopyRuntimeDependencies(self, project: Project, appOutputPath: Path) -> None:
        """
        Copie toutes les bibliothèques dynamiques (SHARED_LIB) dont dépend
        un projet CONSOLE_APP / WINDOWED_APP / TEST_SUITE dans le même dossier
        que l'exécutable/application généré.

        Appelé systématiquement après chaque build de projet application,
        y compris en build incrémental (quand le link est skipé), afin de
        garantir que les fichiers runtime sont toujours présents.

        IMPORTANT : on itère sur project.dependsOn et non project.links, car
        project.links est réécrit avec des chemins absolus par dep_link_map
        dans BuildProject — workspace.projects.get(chemin_absolu) retourne None.

        Les sous-classes peuvent surcharger cette méthode pour un comportement
        spécifique (ex: EmscriptenBuilder pour les side modules WASM).
        """
        if project.kind not in (ProjectKind.CONSOLE_APP, ProjectKind.WINDOWED_APP, ProjectKind.TEST_SUITE):
            return

        dest_dir = appOutputPath.parent
        shared_exts = self.GetSharedLibExtensions()

        # Utiliser dependsOn (noms symboliques stables) plutôt que links
        # (qui peut contenir des chemins absolus après résolution par dep_link_map)
        dep_names_to_check = list(project.dependsOn)

        # Fallback : inclure aussi les links originaux (snapshot avant réécriture)
        base_links = list(getattr(project, "_jenga_filter_base_state", {}).get("links", []))
        for name in base_links:
            if name not in dep_names_to_check:
                dep_names_to_check.append(name)

        for dep_name in dep_names_to_check:
            dep_proj = self.workspace.projects.get(dep_name)
            if not dep_proj or dep_proj.kind != ProjectKind.SHARED_LIB:
                continue

            dep_out = self.GetTargetPath(dep_proj)

            # Chercher le fichier avec l'extension attendue pour cette plateforme
            candidate = dep_out
            if not candidate.exists():
                # Essayer toutes les extensions connues pour ce système
                found = False
                for ext in shared_exts:
                    alt = dep_out.with_suffix(ext)
                    if alt.exists():
                        candidate = alt
                        found = True
                        break
                if not found:
                    print(f"[WARNING] Shared lib not found for '{dep_name}': {dep_out}")
                    continue

            dest = dest_dir / candidate.name

            # Copie seulement si absent ou source plus récent
            if not dest.exists() or candidate.stat().st_mtime > dest.stat().st_mtime:
                try:
                    shutil.copy2(candidate, dest)
                    print(f"[INFO] Copied {candidate} → {dest}")
                except Exception as e:
                    print(f"[WARNING] Could not copy {candidate} to {dest}: {e}")
            else:
                if self.verbose:
                    print(f"[INFO] Up to date: {dest}")

    # -----------------------------------------------------------------------
    # Méthodes communes
    # -----------------------------------------------------------------------

    def GetObjectDir(self, project: Project) -> Path:
        if project.objDir:
            if self._expander:
                self._expander.SetProject(project)
                expanded = self._expander.Expand(project.objDir, recursive=True)
                return Path(expanded).resolve()
            else:
                return Path(project.objDir).resolve()
        else:
            base = Path(self.workspace.location) / "Build" / "Obj" / self.config
            if self.platform:
                base = base / self.platform
            return (base / project.name).resolve()

    def GetTargetDir(self, project: Project) -> Path:
        if project.targetDir:
            if self._expander:
                self._expander.SetProject(project)
                expanded = self._expander.Expand(project.targetDir, recursive=True)
                return Path(expanded).resolve()
            else:
                return Path(project.targetDir).resolve()
        else:
            base = Path(self.workspace.location) / "Build"
            if project.kind in (ProjectKind.STATIC_LIB, ProjectKind.SHARED_LIB):
                base = base / "Lib"
            else:
                base = base / "Bin"
            base = base / self.config
            if self.platform:
                base = base / self.platform
            return (base / project.name).resolve()

    def GetTargetPath(self, project: Project) -> Path:
        target_dir = self.GetTargetDir(project)
        target_name = project.targetName or project.name
        ext = self.GetOutputExtension(project)
        return target_dir / f"{target_name}{ext}"

    def ResolveProjectPath(self, project: Project, value: str) -> str:
        """Resolve a project-relative path against project.location."""
        if not value:
            return value
        if '%{' in value:
            return value
        p = Path(value)
        if p.is_absolute():
            return str(p)

        workspace_base = Path(self.workspace.location).resolve() if self.workspace and self.workspace.location else Path.cwd()
        if project.location:
            base_dir_str = project.location
            if self._expander:
                self._expander.SetProject(project)
                base_dir_str = self._expander.Expand(base_dir_str, recursive=True)
            base_dir_path = Path(base_dir_str)
            if not base_dir_path.is_absolute():
                base_dir_path = workspace_base / base_dir_path
            base_dir = base_dir_path.resolve()
        else:
            base_dir = workspace_base
        return str((base_dir / p).resolve())

    # -----------------------------------------------------------------------
    # Filter application (system/config)
    # -----------------------------------------------------------------------

    @staticmethod
    def _NormalizeSystemName(system_name: str) -> str:
        raw = (system_name or "").strip().lower()
        aliases = {
            "win": "windows",
            "win32": "windows",
            "win64": "windows",
            "linux": "linux",
            "gnu/linux": "linux",
            "mac": "macos",
            "osx": "macos",
            "darwin": "macos",
            "maccatalyst": "macos",
            "catalyst": "macos",
            "web": "web",
            "emscripten": "web",
            "ios": "ios",
            "iphoneos": "ios",
            "iphonesimulator": "ios",
            "ipados": "ios",
            "visionos": "ios",
            "xros": "ios",
            "xrsimulator": "ios",
            "tvos": "tvos",
            "appletv": "tvos",
            "apple_tv": "tvos",
            "watchos": "watchos",
            "applewatch": "watchos",
            "apple_watch": "watchos",
            "android": "android",
            "xbox": "xboxseries",
            "xboxone": "xboxone",
            "xboxseries": "xboxseries",
            "xbox_uwp": "xboxseries",
            "harmony": "harmonyos",
            "harmonyos": "harmonyos",
        }
        return aliases.get(raw, raw)

    def _FilterMatches(self, filter_name: Any, project: Optional[Project] = None) -> bool:
        """Return True if a filter expression matches current build context."""
        if filter_name is None:
            return False

        if isinstance(filter_name, (list, tuple, set)):
            terms = [str(term).strip() for term in filter_name if str(term).strip()]
            if not terms:
                return False
            return all(self._FilterMatches(term, project) for term in terms)

        raw = str(filter_name).strip()
        if not raw:
            return False

        try:
            tokens = self._TokenizeFilterExpr(raw)
            result, _ = self._ParseFilterOr(tokens, 0, project)
            return result
        except Exception:
            return False

    def _TokenizeFilterExpr(self, expr: str) -> List[str]:
        """Tokenize a filter expression: handles ||, &&, !, (), and/or/not keywords."""
        tokens: List[str] = []
        i = 0
        n = len(expr)
        while i < n:
            c = expr[i]
            if c in ' \t\r\n':
                i += 1
                continue
            if expr[i:i+2] == '||':
                tokens.append('||')
                i += 2
                continue
            if expr[i:i+2] == '&&':
                tokens.append('&&')
                i += 2
                continue
            if c == '(':
                tokens.append('(')
                i += 1
                continue
            if c == ')':
                tokens.append(')')
                i += 1
                continue
            if c == '!':
                tokens.append('!')
                i += 1
                continue
            # Read atom/keyword until delimiter
            j = i
            while j < n and expr[j] not in ' \t\r\n()!':
                if expr[j:j+2] in ('||', '&&'):
                    break
                j += 1
            atom = expr[i:j]
            i = j
            if not atom:
                i += 1
                continue
            al = atom.lower()
            if al == 'or':
                tokens.append('||')
            elif al == 'and':
                tokens.append('&&')
            elif al == 'not':
                tokens.append('!')
            else:
                tokens.append(atom)
        return tokens

    def _ParseFilterOr(self, tokens: List[str], pos: int, project) -> Tuple[bool, int]:
        """or_expr = and_expr ('||' and_expr)*"""
        result, pos = self._ParseFilterAnd(tokens, pos, project)
        while pos < len(tokens) and tokens[pos] == '||':
            pos += 1
            right, pos = self._ParseFilterAnd(tokens, pos, project)
            result = result or right
        return result, pos

    def _ParseFilterAnd(self, tokens: List[str], pos: int, project) -> Tuple[bool, int]:
        """and_expr = not_expr ('&&' not_expr)*"""
        result, pos = self._ParseFilterNot(tokens, pos, project)
        while pos < len(tokens) and tokens[pos] == '&&':
            pos += 1
            right, pos = self._ParseFilterNot(tokens, pos, project)
            result = result and right
        return result, pos

    def _ParseFilterNot(self, tokens: List[str], pos: int, project) -> Tuple[bool, int]:
        """not_expr = '!' not_expr | atom_expr"""
        if pos < len(tokens) and tokens[pos] == '!':
            pos += 1
            val, pos = self._ParseFilterNot(tokens, pos, project)
            return not val, pos
        return self._ParseFilterAtom(tokens, pos, project)

    def _ParseFilterAtom(self, tokens: List[str], pos: int, project) -> Tuple[bool, int]:
        """atom_expr = '(' or_expr ')' | term"""
        if pos < len(tokens) and tokens[pos] == '(':
            pos += 1
            val, pos = self._ParseFilterOr(tokens, pos, project)
            if pos < len(tokens) and tokens[pos] == ')':
                pos += 1
            return val, pos
        if pos < len(tokens) and tokens[pos] not in ('||', '&&', '!', '(', ')'):
            atom = tokens[pos]
            pos += 1
            return self._EvalFilterAtom(atom, project), pos
        return False, pos

    def _EvalFilterAtom(self, raw: str, project) -> bool:
        """Evaluate a single leaf filter term."""
        if not raw:
            return False
        lowered = raw.lower()

        # "filter({a,b})" canonicalized fallback: "a,b" means "a && b"
        if "," in raw and ":" in raw:
            parts = [p.strip() for p in raw.split(",") if p.strip()]
            if len(parts) > 1:
                return all(self._EvalFilterAtom(p, project) for p in parts)

        # system:Windows
        if lowered.startswith("system:"):
            system_value = raw.split(":", 1)[1].strip()
            expected_pattern = self._NormalizeSystemName(system_value)
            active_os = self._NormalizeSystemName(self.targetOs.value)
            active_platform = ""
            if self.platform:
                active_platform = self._NormalizeSystemName(self.platform.split("-", 1)[0])
            for active in {active_os, active_platform}:
                if active and fnmatch.fnmatch(active, expected_pattern):
                    return True
            return False

        # configurations:Debug, configuration:Release, config:Debug
        for prefix in ("configurations:", "configuration:", "config:", "cfg:"):
            if lowered.startswith(prefix):
                cfg_pattern = raw.split(":", 1)[1].strip().lower()
                return fnmatch.fnmatch(self.config.lower(), cfg_pattern)

        # architecture:x86_64 / arch:arm64
        for prefix in ("architecture:", "arch:", "targetarch:"):
            if lowered.startswith(prefix):
                arch_pattern = raw.split(":", 1)[1].strip().lower()
                return fnmatch.fnmatch(self.targetArch.value.lower(), arch_pattern)

        # platform:Windows-x86_64 / platforms:Windows
        for prefix in ("platform:", "platforms:"):
            if lowered.startswith(prefix):
                platform_pattern = raw.split(":", 1)[1].strip().lower()
                active_platform = (self.platform or "").strip().lower()
                if active_platform:
                    return fnmatch.fnmatch(active_platform, platform_pattern)
                return fnmatch.fnmatch(self.targetOs.value.lower(), platform_pattern)

        # action:build / action:gen-cmake
        if lowered.startswith("action:"):
            action_pattern = raw.split(":", 1)[1].strip().lower()
            return fnmatch.fnmatch(self.action, action_pattern)

        # options:foo
        if lowered.startswith("options:") or lowered.startswith("option:"):
            _, value = raw.split(":", 1)
            opt_pattern = value.strip().lower()
            if not self.options:
                return False
            return any(fnmatch.fnmatch(opt, opt_pattern) for opt in self.options)

        # kind:StaticLib / kind:ConsoleApp
        if lowered.startswith("kind:") and project is not None:
            kind_pattern = raw.split(":", 1)[1].strip().lower()
            kind_tokens = {project.kind.value.lower(), project.kind.name.lower()}
            return any(fnmatch.fnmatch(token, kind_pattern) for token in kind_tokens)

        # language:C++ / language:C
        if lowered.startswith("language:") and project is not None:
            lang_pattern = raw.split(":", 1)[1].strip().lower()
            lang_tokens = {project.language.value.lower(), project.language.name.lower()}
            return any(fnmatch.fnmatch(token, lang_pattern) for token in lang_tokens)

        # toolset:clang / toolset:gcc
        if lowered.startswith("toolset:") and self.toolchain is not None:
            toolset_pattern = raw.split(":", 1)[1].strip().lower()
            tool_tokens = {
                str(getattr(self.toolchain, "name", "")).lower(),
                str(getattr(self.toolchain, "compilerFamily", "")).lower(),
                str(getattr(getattr(self.toolchain, "compilerFamily", None), "value", "")).lower(),
            }
            return any(token and fnmatch.fnmatch(token, toolset_pattern) for token in tool_tokens)

        # Premake-style shorthand tokens: "windows", "Debug", "x86_64"
        token = lowered
        active_os = self._NormalizeSystemName(self.targetOs.value)
        if token == self.config.lower() or fnmatch.fnmatch(self.config.lower(), token):
            return True
        if token == self.targetArch.value.lower() or fnmatch.fnmatch(self.targetArch.value.lower(), token):
            return True
        if token == active_os or fnmatch.fnmatch(active_os, token):
            return True

        return False

    @staticmethod
    def _AppendUnique(items: List[str], values: List[str]) -> None:
        for value in values:
            if value not in items:
                items.append(value)

    @staticmethod
    def _RemoveMatching(items: List[str], patterns: List[str]) -> List[str]:
        if not items or not patterns:
            return items

        def _matches(value: str) -> bool:
            for pattern in patterns:
                if value == pattern or fnmatch.fnmatch(value, pattern):
                    return True
            return False

        return [value for value in items if not _matches(value)]

    def _ApplyProjectFilters(self, project: Project) -> None:
        """
        Materialize filtered properties onto project for the active target/config.
        Called once per project/build context.
        """
        context_key = (
            f"{self.targetOs.value}|{self.targetArch.value}|{self.config}|{self.platform or ''}"
            f"|{self.action}|{','.join(self.options)}"
        )
        if getattr(project, "_jenga_applied_filter_context", None) == context_key:
            return

        # Snapshot project base values once, then re-materialize on each context.
        base = getattr(project, "_jenga_filter_base_state", None)
        if base is None:
            base = {
                "files": list(project.files),
                "excludeFiles": list(project.excludeFiles),
                "excludeMainFiles": list(project.excludeMainFiles),
                "includeDirs": list(project.includeDirs),
                "libDirs": list(project.libDirs),
                "dependsOn": list(project.dependsOn),
                "dependFiles": list(project.dependFiles),
                "embedResources": list(project.embedResources),
                "links": list(project.links),
                "defines": list(project.defines),
                "cflags": list(project.cflags),
                "cxxflags": list(project.cxxflags),
                "ldflags": list(project.ldflags),
                "preBuildCommands": list(project.preBuildCommands),
                "postBuildCommands": list(project.postBuildCommands),
                "preLinkCommands": list(project.preLinkCommands),
                "postLinkCommands": list(project.postLinkCommands),
                "objDir": project.objDir,
                "targetDir": project.targetDir,
                "targetName": project.targetName,
                "pchHeader": project.pchHeader,
                "pchSource": project.pchSource,
                "optimize": project.optimize,
                "symbols": project.symbols,
                "warnings": project.warnings,
            }
            project._jenga_filter_base_state = base

        project.files = list(base["files"])
        project.excludeFiles = list(base["excludeFiles"])
        project.excludeMainFiles = list(base["excludeMainFiles"])
        project.includeDirs = list(base["includeDirs"])
        project.libDirs = list(base["libDirs"])
        project.dependsOn = list(base["dependsOn"])
        project.dependFiles = list(base["dependFiles"])
        project.embedResources = list(base["embedResources"])
        project.links = list(base["links"])
        project.defines = list(base["defines"])
        project.cflags = list(base["cflags"])
        project.cxxflags = list(base["cxxflags"])
        project.ldflags = list(base["ldflags"])
        project.preBuildCommands = list(base["preBuildCommands"])
        project.postBuildCommands = list(base["postBuildCommands"])
        project.preLinkCommands = list(base["preLinkCommands"])
        project.postLinkCommands = list(base["postLinkCommands"])
        project.objDir = base["objDir"]
        project.targetDir = base["targetDir"]
        project.targetName = base["targetName"]
        project.pchHeader = base["pchHeader"]
        project.pchSource = base["pchSource"]
        project.optimize = base["optimize"]
        project.symbols = base["symbols"]
        project.warnings = base["warnings"]

        # 1) system links collected via links() inside filter("system:...")
        active_system = self._NormalizeSystemName(self.targetOs.value)
        for system_name, libs in project.systemLinks.items():
            if self._NormalizeSystemName(system_name) == active_system:
                self._AppendUnique(project.links, list(libs))
        for system_name, defs in project.systemDefines.items():
            if self._NormalizeSystemName(system_name) == active_system:
                self._AppendUnique(project.defines, list(defs))

        # 2) generic filtered properties captured by API
        for filter_name, files in getattr(project, "_filteredFiles", {}).items():
            if self._FilterMatches(filter_name, project):
                self._AppendUnique(project.files, list(files))
        for filter_name, files in getattr(project, "_filteredExcludeFiles", {}).items():
            if self._FilterMatches(filter_name, project):
                self._AppendUnique(project.excludeFiles, list(files))
        for filter_name, files in getattr(project, "_filteredExcludeMainFiles", {}).items():
            if self._FilterMatches(filter_name, project):
                self._AppendUnique(project.excludeMainFiles, list(files))
        for filter_name, dirs in getattr(project, "_filteredIncludeDirs", {}).items():
            if self._FilterMatches(filter_name, project):
                self._AppendUnique(project.includeDirs, list(dirs))
        for filter_name, dirs in getattr(project, "_filteredLibDirs", {}).items():
            if self._FilterMatches(filter_name, project):
                self._AppendUnique(project.libDirs, list(dirs))
        for filter_name, deps in getattr(project, "_filteredDependsOn", {}).items():
            if self._FilterMatches(filter_name, project):
                self._AppendUnique(project.dependsOn, list(deps))
        for filter_name, depfiles in getattr(project, "_filteredDependFiles", {}).items():
            if self._FilterMatches(filter_name, project):
                self._AppendUnique(project.dependFiles, list(depfiles))
        for filter_name, resources in getattr(project, "_filteredEmbedResources", {}).items():
            if self._FilterMatches(filter_name, project):
                self._AppendUnique(project.embedResources, list(resources))

        for filter_name, defs in project._filteredDefines.items():
            if self._FilterMatches(filter_name, project):
                self._AppendUnique(project.defines, list(defs))
        for filter_name, links in getattr(project, "_filteredLinks", {}).items():
            if self._FilterMatches(filter_name, project):
                self._AppendUnique(project.links, list(links))
        for filter_name, flags in getattr(project, "_filteredCFlags", {}).items():
            if self._FilterMatches(filter_name, project):
                self._AppendUnique(project.cflags, list(flags))
        for filter_name, flags in getattr(project, "_filteredCxxFlags", {}).items():
            if self._FilterMatches(filter_name, project):
                self._AppendUnique(project.cxxflags, list(flags))
        for filter_name, flags in getattr(project, "_filteredLdFlags", {}).items():
            if self._FilterMatches(filter_name, project):
                self._AppendUnique(project.ldflags, list(flags))
        for filter_name, cmds in getattr(project, "_filteredPreBuildCommands", {}).items():
            if self._FilterMatches(filter_name, project):
                self._AppendUnique(project.preBuildCommands, list(cmds))
        for filter_name, cmds in getattr(project, "_filteredPostBuildCommands", {}).items():
            if self._FilterMatches(filter_name, project):
                self._AppendUnique(project.postBuildCommands, list(cmds))
        for filter_name, cmds in getattr(project, "_filteredPreLinkCommands", {}).items():
            if self._FilterMatches(filter_name, project):
                self._AppendUnique(project.preLinkCommands, list(cmds))
        for filter_name, cmds in getattr(project, "_filteredPostLinkCommands", {}).items():
            if self._FilterMatches(filter_name, project):
                self._AppendUnique(project.postLinkCommands, list(cmds))
        for filter_name, obj_dir in getattr(project, "_filteredObjDir", {}).items():
            if self._FilterMatches(filter_name, project):
                project.objDir = obj_dir
        for filter_name, target_dir in getattr(project, "_filteredTargetDir", {}).items():
            if self._FilterMatches(filter_name, project):
                project.targetDir = target_dir
        for filter_name, target_name in getattr(project, "_filteredTargetName", {}).items():
            if self._FilterMatches(filter_name, project):
                project.targetName = target_name
        for filter_name, pch_header in getattr(project, "_filteredPchHeader", {}).items():
            if self._FilterMatches(filter_name, project):
                project.pchHeader = pch_header
        for filter_name, pch_source in getattr(project, "_filteredPchSource", {}).items():
            if self._FilterMatches(filter_name, project):
                project.pchSource = pch_source

        for filter_name, k in getattr(project, "_filteredKind", {}).items():
            if self._FilterMatches(filter_name, project):
                project.kind = k

        for filter_name, tc_name in getattr(project, "_filteredToolchain", {}).items():
            if self._FilterMatches(filter_name, project):
                project.toolchain = tc_name
                project._explicitToolchain = True

        for filter_name, opt in project._filteredOptimize.items():
            if self._FilterMatches(filter_name, project):
                project.optimize = opt

        for filter_name, sym in project._filteredSymbols.items():
            if self._FilterMatches(filter_name, project):
                project.symbols = sym

        for filter_name, warn in project._filteredWarnings.items():
            if self._FilterMatches(filter_name, project):
                project.warnings = warn

        # 3) explicit remove* directives (Premake-compatible behavior)
        for filter_name, dirs in getattr(project, "_filteredRemoveIncludeDirs", {}).items():
            if self._FilterMatches(filter_name, project):
                project.includeDirs = self._RemoveMatching(project.includeDirs, list(dirs))
        for filter_name, dirs in getattr(project, "_filteredRemoveLibDirs", {}).items():
            if self._FilterMatches(filter_name, project):
                project.libDirs = self._RemoveMatching(project.libDirs, list(dirs))
        for filter_name, libs in getattr(project, "_filteredRemoveLinks", {}).items():
            if self._FilterMatches(filter_name, project):
                project.links = self._RemoveMatching(project.links, list(libs))
        for filter_name, deps in getattr(project, "_filteredRemoveDependsOn", {}).items():
            if self._FilterMatches(filter_name, project):
                project.dependsOn = self._RemoveMatching(project.dependsOn, list(deps))
        for filter_name, defs in getattr(project, "_filteredRemoveDefines", {}).items():
            if self._FilterMatches(filter_name, project):
                project.defines = self._RemoveMatching(project.defines, list(defs))

        project._jenga_applied_filter_context = context_key

    # -----------------------------------------------------------------------
    # Incremental compilation helpers
    # -----------------------------------------------------------------------

    def GetDependencyFilePath(self, objectFile: str) -> Path:
        """Dependency sidecar path used by GCC/Clang style compilers."""
        return Path(f"{objectFile}.d")

    def GetDependencyFlags(self, objectFile: str) -> List[str]:
        """
        Dependency emission flags for GCC/Clang:
        -MMD (user headers), -MF (output), -MT (target).
        """
        dep_file = self.GetDependencyFilePath(objectFile)
        return ["-MMD", "-MF", str(dep_file), "-MT", str(objectFile)]

    def _ParseDependencyFile(self, depFile: Path, project: Project) -> List[Path]:
        """
        Parse a Make-style .d dependency file and return normalized paths.
        This parser is tolerant to Windows drive letters and escaped colons.
        """
        if not depFile.exists():
            return []
        try:
            content = depFile.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return []

        content = content.replace("\\\r\n", " ").replace("\\\n", " ")
        tokens = content.split()
        deps: List[Path] = []
        after_target = False

        for token in tokens:
            if token == "\\":
                continue
            if not after_target:
                if token.endswith(":"):
                    after_target = True
                continue

            cleaned = token.strip().rstrip("\\")
            cleaned = cleaned.replace("\\ ", " ").replace("\\:", ":")
            if not cleaned:
                continue

            p = Path(cleaned)
            if not p.is_absolute():
                p = Path(self.ResolveProjectPath(project, cleaned))
            else:
                p = p.resolve()
            deps.append(p)

        return deps

    def _NeedsCompileSource(self, project: Project, sourceFile: str, objectFile: str) -> bool:
        """
        Return True if source must be recompiled:
          - object missing
          - source newer than object
          - dependency file missing
          - any dependency newer than object
          - compile signature changed (defines/includes/flags/context/toolchain)
        """
        src = Path(sourceFile)
        obj = Path(objectFile)
        if not src.exists():
            return False
        if not obj.exists():
            return True

        obj_mtime = obj.stat().st_mtime
        if src.stat().st_mtime > obj_mtime:
            return True

        dep_file = self.GetDependencyFilePath(objectFile)
        if not dep_file.exists():
            return True

        deps = self._ParseDependencyFile(dep_file, project)
        if not deps:
            return True

        for dep in deps:
            try:
                if not dep.exists():
                    return True
                if dep.stat().st_mtime > obj_mtime:
                    return True
            except OSError:
                return True

        expected_signature = self._ComputeCompileSignature(project, sourceFile, objectFile)
        current_signature = self._ReadCompileSignature(objectFile)
        if current_signature != expected_signature:
            return True

        return False

    def _GetCompileSignaturePath(self, objectFile: str) -> Path:
        """Sidecar file storing the compile signature for an object file."""
        return Path(f"{objectFile}.jenga_sig")

    def _ReadCompileSignature(self, objectFile: str) -> str:
        sig_path = self._GetCompileSignaturePath(objectFile)
        if not sig_path.exists():
            return ""
        try:
            return sig_path.read_text(encoding="utf-8").strip()
        except OSError:
            return ""

    def _WriteCompileSignature(self, objectFile: str, signature: str) -> None:
        sig_path = self._GetCompileSignaturePath(objectFile)
        try:
            sig_path.parent.mkdir(parents=True, exist_ok=True)
            sig_path.write_text(signature + "\n", encoding="utf-8")
        except OSError:
            # Signature sidecar is best effort; build outputs remain valid.
            pass

    def _ComputeCompileSignature(self, project: Project, sourceFile: str, objectFile: str) -> str:
        """
        Build a deterministic signature for one compile unit.
        Any change in compile-relevant context should invalidate cached objects.
        """
        try:
            module_flags = [str(f) for f in self.GetModuleFlags(project, sourceFile)]
        except Exception:
            module_flags = []

        include_dirs = [
            str(Path(self.ResolveProjectPath(project, inc)).resolve())
            for inc in project.includeDirs
        ]

        toolchain_payload = {
            "name": str(getattr(self.toolchain, "name", "") or ""),
            "family": str(getattr(getattr(self.toolchain, "compilerFamily", None), "value", "") or ""),
            "triple": str(getattr(self.toolchain, "targetTriple", "") or ""),
            "sysroot": str(getattr(self.toolchain, "sysroot", "") or ""),
            "cc": str(getattr(self.toolchain, "ccPath", "") or ""),
            "cxx": str(getattr(self.toolchain, "cxxPath", "") or ""),
            "defines": [str(d) for d in getattr(self.toolchain, "defines", [])],
            "cflags": [str(f) for f in getattr(self.toolchain, "cflags", [])],
            "cxxflags": [str(f) for f in getattr(self.toolchain, "cxxflags", [])],
        }

        payload = {
            "builder": self.__class__.__name__,
            "context": {
                "config": self.config,
                "platform": self.platform or "",
                "target_os": self.targetOs.value,
                "target_arch": self.targetArch.value,
                "target_env": self.targetEnv.value if self.targetEnv else "",
                "action": self.action,
                "options": list(self.options),
            },
            "toolchain": toolchain_payload,
            "project": {
                "name": project.name,
                "language": project.language.value if project.language else "",
                "cppdialect": project.cppdialect,
                "cdialect": project.cdialect,
                "optimize": project.optimize.value if hasattr(project.optimize, "value") else str(project.optimize),
                "symbols": bool(project.symbols),
                "warnings": project.warnings.value if hasattr(project.warnings, "value") else str(project.warnings),
                "defines": [str(d) for d in project.defines],
                "include_dirs": include_dirs,
                "cflags": [str(f) for f in project.cflags],
                "cxxflags": [str(f) for f in project.cxxflags],
                "pch_header": str(getattr(project, "_jengaPchHeaderResolved", project.pchHeader or "")),
                "pch_source": str(getattr(project, "_jengaPchSourceResolved", project.pchSource or "")),
                "pch_binary": str(getattr(project, "_jengaPchFile", "")),
            },
            "source": str(Path(sourceFile).resolve()),
            "object": str(Path(objectFile).resolve()),
            "module_flags": module_flags,
        }
        encoded = json.dumps(payload, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    # ============================================================
    # Support modules C++20
    # ============================================================

    def _ExtractModuleName(self, moduleFile: str) -> str:
        """
        Extrait le nom du module depuis 'export module <name>;'

        Args:
            moduleFile: Chemin du fichier module (.cppm, .ixx, etc.)

        Returns:
            Nom du module ou nom du fichier sans extension si non trouvé
        """
        try:
            with open(moduleFile, 'r', encoding='utf-8') as f:
                for line in f:
                    # Chercher 'export module <name>;'
                    line_stripped = line.strip()
                    if line_stripped.startswith('export') and 'module' in line_stripped:
                        # export module math;
                        # export module utils.string;
                        parts = line_stripped.split()
                        if len(parts) >= 3 and parts[0] == 'export' and parts[1] == 'module':
                            module_name = parts[2].rstrip(';')
                            return module_name
        except Exception as e:
            Colored.PrintWarning(f"Could not extract module name from {moduleFile}: {e}")

        # Fallback : utiliser le nom du fichier
        return Path(moduleFile).stem

    def _GetBMIExtension(self) -> str:
        """Retourne l'extension BMI selon le compilateur."""
        if self.toolchain.compilerFamily == CompilerFamily.MSVC:
            return ".ifc"
        else:  # Clang/GCC
            return ".pcm"

    def _PrecompileModules(self, project: Project, module_files: List[str], obj_dir: Path) -> bool:
        """
        Précompile tous les modules C++20 pour générer les BMI.

        Args:
            project: Projet en cours
            module_files: Liste des fichiers modules
            obj_dir: Répertoire des fichiers objets

        Returns:
            True si succès, False sinon
        """
        bmi_dir = obj_dir / "modules"
        FileSystem.MakeDirectory(bmi_dir)

        for mod_file in module_files:
            src = Path(mod_file)
            mod_name = self._ExtractModuleName(str(src))
            bmi_ext = self._GetBMIExtension()
            bmi_path = bmi_dir / f"{src.stem}{bmi_ext}"

            # Commande de précompilation selon le compilateur
            if self.toolchain.compilerFamily == CompilerFamily.MSVC:
                # MSVC: cl /std:c++20 /interface module.cppm /Fo module.ifc
                args = [str(self.toolchain.cxxPath), "/std:c++20", "/interface",
                        str(src), "/Fo", str(bmi_path)]
                args.extend(self._GetModulePCHIncludes(project))
            elif self.toolchain.compilerFamily == CompilerFamily.GCC:
                # GCC: g++ -std=c++20 -fmodules-ts -c module.cppm -o module.o
                # Note: GCC génère directement un .o, pas de BMI séparé
                args = [str(self.toolchain.cxxPath), "-std=c++20", "-fmodules-ts",
                        "-c", str(src), "-o", str(bmi_path.with_suffix('.o'))]
                args.extend(self._GetCompilerFlagsForModules(project))
            else:  # Clang (défaut)
                # Clang: clang++ -std=c++20 --precompile module.cppm -o module.pcm
                args = [str(self.toolchain.cxxPath), "-std=c++20", "--precompile",
                        str(src), "-o", str(bmi_path)]
                args.extend(self._GetCompilerFlagsForModules(project))

            # Exécuter la précompilation
            result = Process.ExecuteCommand(args, captureOutput=True, silent=False)
            self._lastResult = result
            if result.returnCode != 0:
                Colored.PrintError(f"Failed to precompile module: {mod_file}")
                return False

            # Stocker le BMI pour utilisation ultérieure
            project._jengaModuleBMIs[mod_name] = str(bmi_path)
            Reporter.Success(f"Module '{mod_name}' precompiled -> {bmi_path.name}")

        return True

    def _CompileModuleToObject(self, project: Project, moduleFile: str, objectFile: str, obj_dir: Path) -> bool:
        """
        Compile un BMI de module en fichier objet.

        Pour Clang/MSVC: compile le .pcm/.ifc en .o
        Pour GCC: le .o est déjà généré par _PrecompileModules

        Args:
            project: Projet en cours
            moduleFile: Fichier module source
            objectFile: Fichier objet destination
            obj_dir: Répertoire objets

        Returns:
            True si succès, False sinon
        """
        # GCC génère directement un .o, donc on copie juste
        if self.toolchain.compilerFamily == CompilerFamily.GCC:
            mod_name = self._ExtractModuleName(moduleFile)
            bmi_path = project._jengaModuleBMIs.get(mod_name)
            if bmi_path and Path(bmi_path).exists():
                # Le .o existe déjà depuis la précompilation
                import shutil
                shutil.copy2(bmi_path, objectFile)
                return True
            return False

        # Pour Clang/MSVC: compiler le BMI en objet
        mod_name = self._ExtractModuleName(moduleFile)
        bmi_path = project._jengaModuleBMIs.get(mod_name)

        if not bmi_path or not Path(bmi_path).exists():
            Colored.PrintError(f"BMI not found for module {mod_name}")
            return False

        if self.toolchain.compilerFamily == CompilerFamily.MSVC:
            # MSVC: cl /c /Fo output.o module.ifc
            args = [str(self.toolchain.cxxPath), "/c", "/Fo", objectFile, bmi_path]
        else:  # Clang
            # Clang: clang++ -c -o output.o module.pcm
            args = [str(self.toolchain.cxxPath), "-c", "-o", objectFile, bmi_path]
            args.extend(self._GetCompilerFlagsForModules(project))

        result = Process.ExecuteCommand(args, captureOutput=True, silent=False)
        self._lastResult = result
        return result.returnCode == 0

    def _GetCompilerFlagsForModules(self, project: Project) -> List[str]:
        """Retourne les flags de compilation pour les modules."""
        flags = []

        # Includes
        for inc in project.includeDirs:
            flags.append(f"-I{self.ResolveProjectPath(project, inc)}")

        # Defines
        for define in project.defines:
            flags.append(f"-D{define}")

        # Debug
        if project.symbols:
            flags.append("-g")

        # Optimization
        opt = project.optimize.value if hasattr(project.optimize, 'value') else project.optimize
        if opt == "Off":
            flags.append("-O0")
        elif opt == "Size":
            flags.append("-Os")
        elif opt == "Speed":
            flags.append("-O2")
        elif opt == "Full":
            flags.append("-O3")

        return flags

    def _GetModulePCHIncludes(self, project: Project) -> List[str]:
        """Retourne les flags pour MSVC."""
        flags = []

        # Includes
        for inc in project.includeDirs:
            flags.append(f"/I{self.ResolveProjectPath(project, inc)}")

        # Defines
        for define in project.defines:
            flags.append(f"/D{define}")

        return flags

    def _GetModuleImportFlags(self, project: Project) -> List[str]:
        """
        Retourne les flags nécessaires pour importer les modules C++20 précompilés.

        Returns:
            Liste de flags à ajouter lors de la compilation
        """
        flags = []
        module_bmis = getattr(project, '_jengaModuleBMIs', {})

        if not module_bmis:
            return flags

        for mod_name, bmi_path in module_bmis.items():
            if self.toolchain.compilerFamily == CompilerFamily.MSVC:
                # MSVC: /reference:module_name=path/to/module.ifc
                flags.append(f"/reference:{mod_name}={bmi_path}")
            else:  # Clang/GCC
                # Clang: -fmodule-file=module_name=path/to/module.pcm
                flags.append(f"-fmodule-file={mod_name}={bmi_path}")

        return flags

    # def BuildProject(self, project: Project) -> bool:
    #     # Check if project is already compiled for this platform/arch context
    #     if self.state.IsProjectCompiled(project.name, self.platform, self.targetArch.value if self.targetArch else ""):
    #         return True

    #     # Apply filter(system/config) materialization before any build decision.
    #     self._ApplyProjectFilters(project)

    #     # Re-resolve toolchain if filter changed project.toolchain
    #     if project._explicitToolchain and project.toolchain:
    #         tc = self.workspace.toolchains.get(project.toolchain)
    #         if not tc:
    #             tc = self.toolchainManager.GetToolchain(project.toolchain)
    #         if tc:
    #             self.toolchain = tc
    #             # Re-run platform-specific toolchain preparation if available
    #             if hasattr(self, '_PrepareNDKToolchain'):
    #                 self._PrepareNDKToolchain()

    #     # Create logger with project info
    #     kind_str = project.kind.name if hasattr(project.kind, 'name') else str(project.kind)
    #     workspace_root = self.workspace.location if self.workspace else None
    #     logger = BuildLogger(project.name, kind_str, workspace_root)

    #     # Print beautiful project header
    #     logger.PrintProjectHeader()

    #     obj_dir = self.GetObjectDir(project)
    #     FileSystem.MakeDirectory(obj_dir)
    #     sources = self._CollectSourceFiles(project)
    #     if not sources:
    #         Colored.PrintWarning(f"No source files found for project {project.name}")
    #         self.state.MarkProjectCompiled(project.name, success=True, platform=self.platform,
    #                                       targetArch=self.targetArch.value if self.targetArch else "")
    #         return True
    #     if not self.PreparePCH(project, obj_dir):
    #         self.state.MarkProjectCompiled(project.name, success=False, platform=self.platform,
    #                                       targetArch=self.targetArch.value if self.targetArch else "")
    #         return False
    #     pch_source = getattr(project, "_jengaPchSourceResolved", "")
    #     if pch_source:
    #         pch_src_norm = str(Path(pch_source).resolve())
    #         sources = [s for s in sources if str(Path(s).resolve()) != pch_src_norm]

    #     # ===== Support modules C++20 =====
    #     module_files = [s for s in sources if self.IsModuleFile(s)]
    #     regular_files = [s for s in sources if not self.IsModuleFile(s)]

    #     project._jengaModuleBMIs = {}

    #     # Set total for logger
    #     logger.SetTotal(len(module_files) + len(regular_files))

    #     # Precompile modules
    #     if module_files:
    #         Reporter.Info(f"Precompiling {len(module_files)} C++20 module(s)...")
    #         if not self._PrecompileModules(project, module_files, obj_dir):
    #             self.state.MarkProjectCompiled(project.name, success=False, platform=self.platform,
    #                                           targetArch=self.targetArch.value if self.targetArch else "")
    #             logger.PrintResultBox(False)
    #             return False

    #     object_files = []
    #     success = True

    #     # Compile modules to object files
    #     for mod_file in module_files:
    #         src_path = Path(mod_file)
    #         obj_name = src_path.with_suffix(self.GetObjectExtension()).name
    #         obj_path = obj_dir / obj_name

    #         self._lastResult = None
    #         if self._CompileModuleToObject(project, str(src_path), str(obj_path), obj_dir):
    #             object_files.append(str(obj_path))
    #             self.state.AddProjectOutput(project.name, str(obj_path))
    #             logger.LogCompile(str(src_path), self._lastResult)
    #         else:
    #             logger.LogCompile(str(src_path), self._lastResult)
    #             success = False
    #             break

    #     if not success:
    #         self.state.MarkProjectCompiled(project.name, success=False, platform=self.platform,
    #                                       targetArch=self.targetArch.value if self.targetArch else "")
    #         logger.PrintStats()
    #         return False

    #     # Compile regular sources (with parallel compilation support)
    #     num_jobs = self._GetEffectiveJobs()

    #     # Sequential compilation (jobs == 1) or parallel compilation (jobs > 1)
    #     if num_jobs == 1:
    #         for src in regular_files:
    #             src_path = Path(src)
    #             obj_name = src_path.with_suffix(self.GetObjectExtension()).name
    #             obj_path = obj_dir / obj_name

    #             if not self._NeedsCompileSource(project, str(src_path), str(obj_path)):
    #                 object_files.append(str(obj_path))
    #                 self.state.AddProjectOutput(project.name, str(obj_path))
    #                 logger.LogCached(str(src_path))
    #                 continue

    #             self._lastResult = None
    #             if self.Compile(project, str(src_path), str(obj_path)):
    #                 signature = self._ComputeCompileSignature(project, str(src_path), str(obj_path))
    #                 self._WriteCompileSignature(str(obj_path), signature)
    #                 object_files.append(str(obj_path))
    #                 self.state.AddProjectOutput(project.name, str(obj_path))
    #                 logger.LogCompile(str(src_path), self._lastResult)
    #             else:
    #                 logger.LogCompile(str(src_path), self._lastResult)
    #                 # Afficher l'erreur détaillée
    #                 if self._lastResult and self._lastResult.stderr:
    #                     Reporter.Error(self._lastResult.stderr.strip())
    #                 elif self._lastResult and self._lastResult.stdout:
    #                     Reporter.Error(self._lastResult.stdout.strip())
    #                 else:
    #                     Reporter.Error(f"Compilation failed for {src_path}")
    #                 success = False
    #                 break
    #     else:
    #         # Parallel compilation using ThreadPoolExecutor
    #         with concurrent.futures.ThreadPoolExecutor(max_workers=num_jobs) as executor:
    #             # Prepare compilation tasks
    #             compile_tasks = []
    #             cached_files = []

    #             for src in regular_files:
    #                 src_path = Path(src)
    #                 obj_name = src_path.with_suffix(self.GetObjectExtension()).name
    #                 obj_path = obj_dir / obj_name

    #                 # Check if compilation needed
    #                 if not self._NeedsCompileSource(project, str(src_path), str(obj_path)):
    #                     cached_files.append((str(src_path), str(obj_path)))
    #                     continue

    #                 # Submit compilation task
    #                 future = executor.submit(self.Compile, project, str(src_path), str(obj_path))
    #                 compile_tasks.append((future, str(src_path), str(obj_path)))

    #             # Log cached files immediately
    #             for src_path, obj_path in cached_files:
    #                 object_files.append(obj_path)
    #                 self.state.AddProjectOutput(project.name, obj_path)
    #                 logger.LogCached(src_path)

    #             # Wait for parallel compilations and collect results
    #             for future, src_path, obj_path in compile_tasks:
    #                 try:
    #                     compile_success = future.result()
    #                     if compile_success:
    #                         signature = self._ComputeCompileSignature(project, src_path, obj_path)
    #                         self._WriteCompileSignature(obj_path, signature)
    #                         object_files.append(obj_path)
    #                         self.state.AddProjectOutput(project.name, obj_path)
    #                         logger.LogCompile(src_path, None)
    #                     else:
    #                         logger.LogCompile(src_path, None)
    #                         # Récupérer l'erreur (difficile avec ThreadPoolExecutor, on peut stocker l'erreur dans un attribut)
    #                         if self._lastResult and self._lastResult.stderr:
    #                             Reporter.Error(self._lastResult.stderr.strip())
    #                         elif self._lastResult and self._lastResult.stdout:
    #                             Reporter.Error(self._lastResult.stdout.strip())
    #                         else:
    #                             Reporter.Error(f"Compilation failed for {src_path}")
    #                         success = False
    #                 except Exception as e:
    #                     logger.LogCompile(src_path, None)
    #                     Reporter.Error(f"Compilation exception for {src_path}: {e}")
    #                     success = False

    #     if not success:
    #         self.state.MarkProjectCompiled(project.name, success=False, platform=self.platform,
    #                                       targetArch=self.targetArch.value if self.targetArch else "")
    #         logger.PrintStats()
    #         return False

    #     # Helpful visibility for incremental builds: all regular sources were
    #     # cache hits, so no compile command was executed for this project.
    #     if regular_files and logger.cached == len(regular_files):
    #         logger.LogUpToDate()

    #     # Auto-wire local library dependencies for link phase while preserving
    #     # the user-declared link order (important for GNU-like linkers).
    #     dep_link_map: Dict[str, str] = {}
    #     for dep_name in project.dependsOn:
    #         dep_proj = self.workspace.projects.get(dep_name)
    #         if not dep_proj:
    #             continue
    #         if dep_proj.kind not in (ProjectKind.STATIC_LIB, ProjectKind.SHARED_LIB):
    #             continue
    #         dep_dir = str(self.GetTargetDir(dep_proj))
    #         dep_out = str(self.GetTargetPath(dep_proj))
    #         if dep_dir not in project.libDirs:
    #             project.libDirs.append(dep_dir)
    #         dep_link_map[dep_name] = dep_out

    #     if dep_link_map:
    #         new_links: List[str] = []
    #         seen: set[str] = set()

    #         for link in project.links:
    #             resolved = dep_link_map.get(link, link)
    #             if resolved not in seen:
    #                 new_links.append(resolved)
    #                 seen.add(resolved)

    #         # Ensure dependencies are present even if not explicitly listed in links().
    #         missing_dep_outputs: List[str] = []
    #         for dep_out in dep_link_map.values():
    #             if dep_out not in seen:
    #                 missing_dep_outputs.append(dep_out)
    #                 seen.add(dep_out)

    #         # Missing auto-wired dependency archives are prepended so that
    #         # GNU-like linkers resolve their symbols before system/provider libs.
    #         project.links = missing_dep_outputs + new_links

    #     if project.kind in (ProjectKind.CONSOLE_APP, ProjectKind.WINDOWED_APP,
    #                         ProjectKind.SHARED_LIB, ProjectKind.STATIC_LIB,
    #                         ProjectKind.TEST_SUITE):
    #         target_path = self.GetTargetPath(project)
    #         FileSystem.MakeDirectory(target_path.parent)

    #         self._lastResult = None
    #         link_ok = self.Link(project, object_files, str(target_path))
    #         logger.LogLink(str(target_path), self._lastResult)

    #         # Copier les bibliothèques dynamiques dans le dossier de l'application.
    #         # Appelé SYSTEMATIQUEMENT (pas seulement si link effectué) pour garantir
    #         # que les fichiers runtime sont présents même en build incrémental.
    #         self.CopyRuntimeDependencies(project, target_path)

    #         if link_ok:
    #             self.state.AddProjectOutput(project.name, str(target_path))
    #             self.state.MarkProjectCompiled(project.name, success=True, platform=self.platform,
    #                                           targetArch=self.targetArch.value if self.targetArch else "")
    #             logger.PrintResultBox(True)
    #             return True
    #         else:
    #             self.state.MarkProjectCompiled(project.name, success=False, platform=self.platform,
    #                                       targetArch=self.targetArch.value if self.targetArch else "")
    #             logger.PrintResultBox(False)
    #             return False
    #     else:
    #         self.state.MarkProjectCompiled(project.name, success=True)
    #         logger.PrintResultBox(True)
    #         return True

    def BuildProject(self, project: Project) -> bool:
        # Check if project is already compiled for this platform/arch context
        if self.state.IsProjectCompiled(project.name, self.platform, self.targetArch.value if self.targetArch else ""):
            return True

        # Apply filter(system/config) materialization before any build decision.
        self._ApplyProjectFilters(project)

        # Re-resolve toolchain if filter changed project.toolchain
        if project._explicitToolchain and project.toolchain:
            tc = self.workspace.toolchains.get(project.toolchain)
            if not tc:
                tc = self.toolchainManager.GetToolchain(project.toolchain)
            if tc:
                self.toolchain = tc
                # Re-run platform-specific toolchain preparation if available
                if hasattr(self, '_PrepareNDKToolchain'):
                    self._PrepareNDKToolchain()

        # Create logger with project info
        kind_str = project.kind.name if hasattr(project.kind, 'name') else str(project.kind)
        workspace_root = self.workspace.location if self.workspace else None
        logger = BuildLogger(project.name, kind_str, workspace_root)
        self._last_logger = logger  # Expose to Build() for global stats accumulation

        # Print beautiful project header
        logger.PrintProjectHeader()

        obj_dir = self.GetObjectDir(project)
        FileSystem.MakeDirectory(obj_dir)
        sources = self._CollectSourceFiles(project)
        if not sources:
            Colored.PrintWarning(f"No source files found for project {project.name}")
            self.state.MarkProjectCompiled(project.name, success=True, platform=self.platform,
                                        targetArch=self.targetArch.value if self.targetArch else "")
            return True
        if not self.PreparePCH(project, obj_dir):
            self.state.MarkProjectCompiled(project.name, success=False, platform=self.platform,
                                        targetArch=self.targetArch.value if self.targetArch else "")
            return False
        pch_source = getattr(project, "_jengaPchSourceResolved", "")
        if pch_source:
            pch_src_norm = str(Path(pch_source).resolve())
            sources = [s for s in sources if str(Path(s).resolve()) != pch_src_norm]

        # ===== Support modules C++20 =====
        module_files = [s for s in sources if self.IsModuleFile(s)]
        regular_files = [s for s in sources if not self.IsModuleFile(s)]

        project._jengaModuleBMIs = {}

        # Set total for logger
        logger.SetTotal(len(module_files) + len(regular_files))

        # Precompile modules
        if module_files:
            Reporter.Info(f"Precompiling {len(module_files)} C++20 module(s)...")
            if not self._PrecompileModules(project, module_files, obj_dir):
                self.state.MarkProjectCompiled(project.name, success=False, platform=self.platform,
                                            targetArch=self.targetArch.value if self.targetArch else "")
                logger.PrintResultBox(False)
                return False

        object_files = []
        success = True

        # Compile modules to object files
        for mod_file in module_files:
            src_path = Path(mod_file)
            obj_name = src_path.with_suffix(self.GetObjectExtension()).name
            obj_path = obj_dir / obj_name

            # _CompileModuleToObject retourne bool pour l'instant, on garde
            if self._CompileModuleToObject(project, str(src_path), str(obj_path), obj_dir):
                object_files.append(str(obj_path))
                self.state.AddProjectOutput(project.name, str(obj_path))
                logger.LogCompile(str(src_path), None)  # Pas de ProcessResult pour module
            else:
                logger.LogCompile(str(src_path), None)
                success = False
                break

        if not success:
            self.state.MarkProjectCompiled(project.name, success=False, platform=self.platform,
                                        targetArch=self.targetArch.value if self.targetArch else "")
            logger.PrintResultBox(False)
            return False

        # Compile regular sources (with parallel compilation support)
        num_jobs = self._GetEffectiveJobs()

        if num_jobs == 1:
            # Sequential compilation
            for src in regular_files:
                src_path = Path(src)
                obj_name = src_path.with_suffix(self.GetObjectExtension()).name
                obj_path = obj_dir / obj_name

                if not self._NeedsCompileSource(project, str(src_path), str(obj_path)):
                    object_files.append(str(obj_path))
                    self.state.AddProjectOutput(project.name, str(obj_path))
                    logger.LogCached(str(src_path))
                    continue

                result = self.Compile(project, str(src_path), str(obj_path))
                if result.returnCode == 0:
                    signature = self._ComputeCompileSignature(project, str(src_path), str(obj_path))
                    self._WriteCompileSignature(str(obj_path), signature)
                    object_files.append(str(obj_path))
                    self.state.AddProjectOutput(project.name, str(obj_path))
                    logger.LogCompile(str(src_path), result)
                else:
                    logger.LogCompile(str(src_path), result)
                    success = False
                    break
        else:
            # Parallel compilation using ThreadPoolExecutor
            with concurrent.futures.ThreadPoolExecutor(max_workers=num_jobs) as executor:
                future_to_paths: Dict[concurrent.futures.Future, tuple] = {}
                cached_files = []

                for src in regular_files:
                    src_path = Path(src)
                    obj_name = src_path.with_suffix(self.GetObjectExtension()).name
                    obj_path = obj_dir / obj_name

                    if not self._NeedsCompileSource(project, str(src_path), str(obj_path)):
                        cached_files.append((str(src_path), str(obj_path)))
                        continue

                    future = executor.submit(self.Compile, project, str(src_path), str(obj_path))
                    future_to_paths[future] = (str(src_path), str(obj_path))

                # Log cached files immediately
                for src_path, obj_path in cached_files:
                    object_files.append(obj_path)
                    self.state.AddProjectOutput(project.name, obj_path)
                    logger.LogCached(src_path)

                # Wait for parallel compilations in completion order (as_completed = real-time errors)
                for future in concurrent.futures.as_completed(future_to_paths):
                    src_path, obj_path = future_to_paths[future]
                    try:
                        result = future.result()
                        if result.returnCode == 0:
                            signature = self._ComputeCompileSignature(project, src_path, obj_path)
                            self._WriteCompileSignature(obj_path, signature)
                            object_files.append(obj_path)
                            self.state.AddProjectOutput(project.name, obj_path)
                            logger.LogCompile(src_path, result)
                        else:
                            logger.LogCompile(src_path, result)
                            success = False
                    except Exception as exc:
                        logger.LogCompile(src_path, None)
                        Reporter.Error(f"Compilation exception for {src_path}: {exc}")
                        success = False

        if not success:
            self.state.MarkProjectCompiled(project.name, success=False, platform=self.platform,
                                        targetArch=self.targetArch.value if self.targetArch else "")
            logger.PrintResultBox(False)
            return False

        # Helpful visibility for incremental builds: all regular sources were cache hits
        if regular_files and logger.cached == len(regular_files):
            logger.LogUpToDate()

        # Auto-wire local library dependencies for link phase
        dep_link_map: Dict[str, str] = {}
        for dep_name in project.dependsOn:
            dep_proj = self.workspace.projects.get(dep_name)
            if not dep_proj:
                continue
            if dep_proj.kind not in (ProjectKind.STATIC_LIB, ProjectKind.SHARED_LIB):
                continue
            dep_dir = str(self.GetTargetDir(dep_proj))
            dep_out = str(self.GetTargetPath(dep_proj))
            if dep_dir not in project.libDirs:
                project.libDirs.append(dep_dir)
            dep_link_map[dep_name] = dep_out

        if dep_link_map:
            new_links: List[str] = []
            seen: set[str] = set()

            for link in project.links:
                # Skip WINDOWED_APP/CONSOLE_APP deps — they produce executables, not linkable libraries
                dep_for_link = self.workspace.projects.get(link)
                if dep_for_link and dep_for_link.kind in (ProjectKind.CONSOLE_APP, ProjectKind.WINDOWED_APP):
                    continue
                resolved = dep_link_map.get(link, link)
                if resolved not in seen:
                    new_links.append(resolved)
                    seen.add(resolved)

            missing_dep_outputs: List[str] = []
            for dep_out in dep_link_map.values():
                if dep_out not in seen:
                    missing_dep_outputs.append(dep_out)
                    seen.add(dep_out)

            # Preserve explicit project link order first (important for GNU-like
            # one-pass linkers). Only append missing dependency outputs.
            project.links = new_links + missing_dep_outputs

        if project.kind in (ProjectKind.CONSOLE_APP, ProjectKind.WINDOWED_APP,
                            ProjectKind.SHARED_LIB, ProjectKind.STATIC_LIB,
                            ProjectKind.TEST_SUITE):
            target_path = self.GetTargetPath(project)
            FileSystem.MakeDirectory(target_path.parent)

            # Link - capture ProcessResult pour afficher les erreurs
            link_ok = self.Link(project, object_files, str(target_path))
            logger.LogLink(str(target_path), self._lastResult)  # Affiche les erreurs de linking si le linking échoue

            self.CopyRuntimeDependencies(project, target_path)

            if link_ok:
                self.state.AddProjectOutput(project.name, str(target_path))
                self.state.MarkProjectCompiled(project.name, success=True, platform=self.platform,
                                            targetArch=self.targetArch.value if self.targetArch else "")
                logger.PrintResultBox(True)
                return True
            else:
                self.state.MarkProjectCompiled(project.name, success=False, platform=self.platform,
                                            targetArch=self.targetArch.value if self.targetArch else "")
                logger.PrintResultBox(False)
                return False
        else:
            self.state.MarkProjectCompiled(project.name, success=True)
            logger.PrintResultBox(True)
            return True

    @staticmethod
    def GetSourceFileExtensions(language: Api.Language) -> List[str]:
        extensions = {
            Api.Language.C:        ['.c'],
            # Keep `.mm` for Apple entry points/backends that are selected via filters
            # while the project language remains C++.
            Api.Language.CPP:      ['.cpp', '.cc', '.cxx', '.c++', '.cppm', '.ixx', '.mpp', '.c++m', '.mm'],
            Api.Language.OBJC:     ['.m'],
            Api.Language.OBJCPP:   ['.mm'],
            Api.Language.ASM:      ['.s', '.asm', '.S'],
            Api.Language.RUST:     ['.rs'],
            Api.Language.ZIG:      ['.zig'],
        }
        return extensions.get(language, ['.c', '.cpp', '.cc', '.cxx', '.m', '.mm'])

    @staticmethod
    def IsModuleFile(filepath: str) -> bool:
        ext = Path(filepath).suffix.lower()
        return ext in ('.cppm', '.ixx', '.mpp', '.c++m')

    @staticmethod
    def GetHeaderFileExtensions() -> List[str]:
        return ['.h', '.hpp', '.hxx', '.h++', '.inl', '.inc', '.tpp', '.ipp']

    @staticmethod
    def GetObjectExtensionForPlatform(platform: str) -> str:
        if platform.lower() in ('windows', 'win32', 'win64', 'msvc'):
            return '.obj'
        else:
            return '.o'

    @staticmethod
    def GetOutputExtensionsForProject(project: Project) -> List[str]:
        exts = []
        if project.kind in (ProjectKind.CONSOLE_APP, ProjectKind.WINDOWED_APP, ProjectKind.TEST_SUITE):
            exts.append('.exe')
            exts.append('')
        elif project.kind == ProjectKind.SHARED_LIB:
            exts.extend(['.dll', '.so', '.dylib'])
            exts.append('.lib')
        elif project.kind == ProjectKind.STATIC_LIB:
            exts.extend(['.lib', '.a'])
        return exts

    def _CollectSourceFiles(self, project: Project) -> List[str]:
        files = []
        workspace_base = Path(self.workspace.location).resolve() if self.workspace and self.workspace.location else Path.cwd()
        if project.location:
            base_dir_str = project.location
            if self._expander:
                self._expander.SetProject(project)
                base_dir_str = self._expander.Expand(base_dir_str, recursive=True)
            base_dir_path = Path(base_dir_str)
            if not base_dir_path.is_absolute():
                base_dir_path = workspace_base / base_dir_path
            base_dir = base_dir_path.resolve()
        else:
            base_dir = workspace_base
        src_exts = self.GetSourceFileExtensions(project.language)
        for pattern in project.files:
            expanded_pattern = pattern
            if self._expander:
                self._expander.SetProject(project)
                expanded_pattern = self._expander.Expand(pattern, recursive=True)
            p = Path(expanded_pattern)
            if p.is_absolute():
                if any(ch in expanded_pattern for ch in ("*", "?", "[")):
                    matched = [m for m in glob.glob(expanded_pattern, recursive=True) if Path(m).is_file()]
                elif p.exists():
                    matched = [str(p)]
                else:
                    matched = []
            else:
                matched = FileSystem.ListFiles(base_dir, pattern=expanded_pattern, recursive=True, fullPath=True)
            for f in matched:
                # Exclure silencieusement les fichiers platform-spécifiques
                # (.ts, .ets, .swift, .java, .kt...) — ils sont gérés par
                # GetPlatformSpecificFiles() dans les builders platform.
                # Même logique que .mm pour Cocoa : déclaré dans files(),
                # ignoré par le compilateur natif si le builder ne le supporte pas.
                if Path(f).suffix.lower() in PLATFORM_SPECIFIC_EXTENSIONS:
                    continue
                if any(f.lower().endswith(ext) for ext in src_exts):
                    files.append(f)
        exclude = set()
        for pattern in project.excludeFiles:
            expanded_pattern = pattern
            if self._expander:
                self._expander.SetProject(project)
                expanded_pattern = self._expander.Expand(pattern, recursive=True)
            p = Path(expanded_pattern)
            if p.is_absolute():
                if any(ch in expanded_pattern for ch in ("*", "?", "[")):
                    matched = [m for m in glob.glob(expanded_pattern, recursive=True) if Path(m).is_file()]
                elif p.exists():
                    matched = [str(p)]
                else:
                    matched = []
            else:
                matched = FileSystem.ListFiles(base_dir, pattern=expanded_pattern, recursive=True, fullPath=True)
            exclude.update(matched)
        files = [f for f in files if f not in exclude]
        files.sort()
        return files

    def _IsUnitTestProject(self, projectName: str, project: Optional[Project]) -> bool:
        if project is None:
            return False
        if projectName == "__Unitest__" or project.name == "__Unitest__":
            return True
        return bool(project.isTest or project.kind == ProjectKind.TEST_SUITE)

    def _ApplyUnitTestCompilationPolicy(self,
                                        order: List[str],
                                        targetProject: Optional[str]) -> Optional[List[str]]:
        if not bool(getattr(self.workspace, "disableUnitTestCompilation", False)):
            return order

        blocked = []
        for proj_name in order:
            proj = self.workspace.projects.get(proj_name)
            if self._IsUnitTestProject(proj_name, proj):
                blocked.append(proj_name)

        if not blocked:
            return order

        blocked_set = set(blocked)
        if targetProject and targetProject in blocked_set:
            Reporter.Error(
                f"Unit-test compilation is disabled by workspace policy. "
                f"Blocked target: '{targetProject}'."
            )
            return None

        for proj_name in order:
            if proj_name in blocked_set:
                continue
            proj = self.workspace.projects.get(proj_name)
            if not proj:
                continue
            blocked_deps = [dep for dep in proj.dependsOn if dep in blocked_set]
            if blocked_deps:
                Reporter.Error(
                    f"Project '{proj_name}' depends on blocked unit-test project(s): "
                    f"{', '.join(blocked_deps)}."
                )
                return None

        Reporter.Info(
            "Skipping unit-test compilation due to workspace policy: "
            + ", ".join(blocked)
        )
        return [proj_name for proj_name in order if proj_name not in blocked_set]

    def Build(self, targetProject: Optional[str] = None) -> int:
        from ..Utils.Reporter import BuildCoordinator

        # Materialize all context-dependent filters before dependency resolution.
        for proj in self.workspace.projects.values():
            self._ApplyProjectFilters(proj)

        # Resolve build order
        try:
            order = DependencyResolver.ResolveBuildOrder(self.workspace, targetProject)
        except ValueError as e:
            # Target introuvable : message actionnable listant les projets connus.
            available = sorted(self.workspace.projects.keys())
            Reporter.Error(str(e))
            if available:
                Reporter.Info("Available projects: " + ", ".join(available))
            else:
                Reporter.Info("This workspace declares no project.")
            return 1
        except RuntimeError as e:
            Reporter.Error(f"Dependency resolution failed: {e}")
            return 1
        order = self._ApplyUnitTestCompilationPolicy(order, targetProject)
        if order is None:
            return 1
        if not order:
            Reporter.Info("No projects to build after applying workspace policy.")
            return 0

        # Prepare build order information for header
        build_order_info = []
        for proj_name in order:
            proj = self.workspace.projects.get(proj_name)
            if not proj:
                continue
            kind_str = proj.kind.name if hasattr(proj.kind, 'name') else str(proj.kind)
            deps = [d for d in proj.dependsOn if d in self.workspace.projects]
            build_order_info.append((proj_name, kind_str, deps))

        # Create build coordinator and print header
        toolchain_name = self.toolchain.name if self.toolchain else ""
        cache_status = getattr(self.workspace, '_cache_status', None)
        coordinator = BuildCoordinator(
            workspace_name=self.workspace.name,
            config=self.config,
            target_os=self.targetOs.value,
            target_arch=self.targetArch.value,
            toolchain=toolchain_name
        )
        coordinator.PrintHeader(build_order_info, cache_status)

        # Build each project
        success_count = 0
        fail_count = 0
        for proj_name in order:
            proj = self.workspace.projects.get(proj_name)
            if not proj:
                continue
            run_cwd = proj.location or self.workspace.location
            for cmd in proj.preBuildCommands:
                expanded_cmd = cmd
                if self._expander:
                    self._expander.SetProject(proj)
                    expanded_cmd = self._expander.Expand(cmd, recursive=True)
                Process.Run(expanded_cmd, shell=True, cwd=run_cwd)
            ok = self.BuildProject(proj)
            coordinator.MarkProjectBuilt(ok)
            # Accumulate per-project error/warning counts for global footer summary
            last_logger = getattr(self, '_last_logger', None)
            if last_logger:
                coordinator.AccumulateStats(last_logger.errors_count, last_logger.warnings_count)
            for cmd in proj.postBuildCommands:
                expanded_cmd = cmd
                if self._expander:
                    self._expander.SetProject(proj)
                    expanded_cmd = self._expander.Expand(cmd, recursive=True)
                Process.Run(expanded_cmd, shell=True, cwd=run_cwd)
            if ok:
                success_count += 1
            else:
                fail_count += 1
                if not self.verbose:
                    break

        # Print footer
        coordinator.PrintFooter()

        if fail_count == 0:
            return 0
        else:
            return 1
