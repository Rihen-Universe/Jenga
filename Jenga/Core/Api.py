#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Jenga Build System - Core API
Provides the DSL for configuring workspaces and projects

Naming conventions (strict):
- PascalCase       : classes, enums, public methods/functions
- _PascalCase      : private methods
- lower            : user‑exposed functions (all lowercase, no underscores, one word)
- _camelCase       : private/protected member variables
- camelCase        : non‑public member variables (internal, not part of public API)
- UPPER_SNAKE_CASE : enum values and constants
"""

from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any, Union, Tuple
from pathlib import Path
from enum import Enum
import copy
import os
import sys
import re
import fnmatch
import json
import shutil
import subprocess
from functools import lru_cache

# ---------------------------------------------------------------------------
# Enums – UPPER_SNAKE_CASE
# ---------------------------------------------------------------------------

class ProjectKind(Enum):
    """Only four fundamental project types + test suite."""
    CONSOLE_APP   = "ConsoleApp"
    WINDOWED_APP  = "WindowedApp"
    STATIC_LIB    = "StaticLib"
    SHARED_LIB    = "SharedLib"
    TEST_SUITE    = "TestSuite"

class Language(Enum):
    C      = "C"
    CPP    = "C++"
    OBJC   = "Objective-C"
    OBJCPP = "Objective-C++"
    ASM    = "Assembly"
    RUST   = "Rust"
    ZIG    = "Zig"

class Optimization(Enum):
    OFF    = "Off"
    SIZE   = "Size"
    SPEED  = "Speed"
    FULL   = "Full"

class WarningLevel(Enum):
    NONE      = "None"
    DEFAULT   = "Default"
    ALL       = "All"
    EXTRA     = "Extra"
    PEDANTIC  = "Pedantic"
    EVERYTHING= "Everything"
    ERROR     = "Error"

class TargetOS(Enum):
    WINDOWS   = "Windows"
    LINUX     = "Linux"
    MACOS     = "macOS"
    ANDROID   = "Android"
    IOS       = "iOS"
    TVOS      = "tvOS"
    WATCHOS   = "watchOS"
    IPADOS     = "iPadOS"
    VISIONOS   = "visionOS"
    WEB       = "Web"
    PS4       = "PS4"
    PS5       = "PS5"
    XBOX_ONE  = "XboxOne"
    XBOX_SERIES = "XboxSeries"
    SWITCH    = "Switch"
    HARMONYOS = "HarmonyOS"
    FREEBSD   = "FreeBSD"
    OPENBSD   = "OpenBSD"

class TargetArch(Enum):
    X86       = "x86"
    X86_64    = "x86_64"
    X64       = "x86_64"   # alias
    ARM       = "arm"
    ARM64     = "arm64"
    WASM32    = "wasm32"
    WASM64    = "wasm64"
    POWERPC   = "ppc"
    POWERPC64 = "ppc64"
    MIPS      = "mips"
    MIPS64    = "mips64"

class TargetEnv(Enum):
    GNU     = "gnu"
    MUSL    = "musl"
    MSVC    = "msvc"
    MINGW   = "mingw"
    ANDROID = "android"
    IOS     = "ios"

class CompilerFamily(Enum):
    GCC        = "gcc"
    CLANG      = "clang"
    MSVC       = "msvc"
    EMSCRIPTEN = "emscripten"
    ANDROID_NDK= "android-ndk"
    APPLE_CLANG= "apple-clang"

# ---------------------------------------------------------------------------
# Dataclasses – fields in camelCase, private/protected in _camelCase
# ---------------------------------------------------------------------------

@dataclass
class Toolchain:
    """Cross‑platform toolchain with target awareness."""
    name: str
    compilerFamily: CompilerFamily
    targetOs: Optional[TargetOS] = None
    targetArch: Optional[TargetArch] = None
    targetEnv: Optional[TargetEnv] = None
    targetTriple: Optional[str] = None
    sysroot: Optional[str] = None

    # Paths to executables
    ccPath: Optional[str] = None
    cxxPath: Optional[str] = None
    arPath: Optional[str] = None
    ldPath: Optional[str] = None
    stripPath: Optional[str] = None
    ranlibPath: Optional[str] = None
    asmPath: Optional[str] = None

    # Toolchain root directory
    toolchainDir: Optional[str] = None

    # Global flags (apply to all configurations/filters)
    defines: List[str] = field(default_factory=list)
    cflags: List[str] = field(default_factory=list)
    cxxflags: List[str] = field(default_factory=list)
    asmflags: List[str] = field(default_factory=list)
    ldflags: List[str] = field(default_factory=list)
    arflags: List[str] = field(default_factory=list)

    # Per‑configuration flags
    perConfigFlags: Dict[str, Dict[str, List[str]]] = field(default_factory=dict)

    # Frameworks (macOS/iOS)
    frameworks: List[str] = field(default_factory=list)
    frameworkPaths: List[str] = field(default_factory=list)

    # Metadata for external toolchains
    _external: bool = False
    _externalFile: str = ""
    _externalDir: str = ""

    def setTarget(self, os: Union[str, TargetOS], arch: Union[str, TargetArch],
                  env: Optional[Union[str, TargetEnv]] = None) -> None:
        """PascalCase public method."""
        if isinstance(os, str):
            os = TargetOS[os.upper()]
        if isinstance(arch, str):
            arch = TargetArch[arch.upper()]
        if env and isinstance(env, str):
            env = TargetEnv[env.upper()]
        self.targetOs = os
        self.targetArch = arch
        self.targetEnv = env


@dataclass
class UnitestConfig:
    """Configuration of the Unitest testing framework at workspace level."""
    mode: str = "precompiled"   # "precompiled" or "compile"

    # For compile mode – project properties
    kind: ProjectKind = ProjectKind.STATIC_LIB
    objDir: str = "%{wks.location}/Build/Obj/%{cfg.buildcfg}-%{cfg.system}/%{prj.name}"
    targetDir: str = "%{wks.location}/Build/Lib/%{cfg.buildcfg}-%{cfg.system}/%{prj.name}"
    targetName: str = "Unitest"
    cxxflags: List[str] = field(default_factory=list)
    ldflags: List[str] = field(default_factory=list)
    defines: List[str] = field(default_factory=list)

    # For precompiled mode – these are set by Jenga internal
    includeDir: str = ""   # resolved by backend
    libDir: str = ""       # resolved by backend
    libName: str = "Unitest"

    def isPrecompiled(self) -> bool:
        return self.mode == "precompiled"

    def isCompile(self) -> bool:
        return self.mode == "compile"


@dataclass
class FirewallRule:
    """
    Regle de pare-feu cree par l'installer au deploiement de l'app.

    Champs :
      name      : nom de la regle (visible dans le pare-feu OS). Si vide,
                  l'installer utilise "{AppName} (Network)".
      direction : "in" (entrant, defaut) | "out" (sortant) | "both"
      action    : "allow" (defaut) | "block"
      protocol  : "any" (defaut) | "tcp" | "udp"
      ports     : liste de ports/ranges, ex ["7777", "8000-8100"]. Vide = tous.
      profiles  : profils Windows actifs : "any" (defaut), ou sous-ensemble de
                  {"domain","private","public"}. Sur macOS/Linux, ignore.
      programOverride : si fourni, applique la regle a un autre exe que
                  l'exe principal du projet (rare, ex helper process).

    Une regle minimale `FirewallRule()` cree la meme regle que l'ancien
    comportement code en dur : entrant, allow, tous protocoles/ports, tous
    profils, sur l'exe du projet.
    """
    name:            str       = ""
    direction:       str       = "in"
    action:          str       = "allow"
    protocol:        str       = "any"
    ports:           List[str] = field(default_factory=list)
    profiles:        List[str] = field(default_factory=lambda: ["any"])
    programOverride: str       = ""


@dataclass
class Project:
    """Project configuration – cross‑platform ready."""
    name: str
    kind: ProjectKind = ProjectKind.CONSOLE_APP
    language: Language = Language.CPP
    location: str = "."          # relative to workspace or absolute

    cppdialect: str = "C++17"
    cdialect: str = "C11"

    cflags: List[str] = field(default_factory=list)   # Additional C compiler flags
    cxxflags: List[str] = field(default_factory=list) # Additional C++ compiler flags
    ldflags: List[str] = field(default_factory=list)  # Additional linker flags
    
    # Target overrides (if different from workspace)
    targetOs: Optional[TargetOS] = None
    targetArch: Optional[TargetArch] = None
    targetEnv: Optional[TargetEnv] = None
    targetTriple: Optional[str] = None
    sysroot: Optional[str] = None

    # Files
    files: List[str] = field(default_factory=list)
    excludeFiles: List[str] = field(default_factory=list)
    excludeMainFiles: List[str] = field(default_factory=list)

    # Precompiled headers
    pchHeader: str = ""
    pchSource: str = ""

    # Directories
    includeDirs: List[str] = field(default_factory=list)
    libDirs: List[str] = field(default_factory=list)

    # Output
    objDir: str = ""
    targetDir: str = ""
    targetName: str = ""

    # Dependencies
    links: List[str] = field(default_factory=list)
    frameworks: List[str] = field(default_factory=list)
    dependsOn: List[str] = field(default_factory=list)

    # File dependencies (copy after build)
    dependFiles: List[str] = field(default_factory=list)

    # Embedded resources (compiled into binary)
    embedResources: List[str] = field(default_factory=list)

    # Icone d'application (cross-platform). Voir Core/IconConverter.py pour
    # les regles de dispatch :
    #   - appIcon est l'API "single source" : un PNG/JPG distribue a toutes
    #     les plateformes (jenga convertit en .ico/.icns/mipmap-*/favicon).
    #     Si le format n'est pas universel (.ico, .icns, mipmap-*), seule la
    #     plateforme concernee l'utilisera.
    #   - androidAppIcon / windowsIcon / macosIcon / iosAppIcon / webFavicon
    #     sont des overrides par plateforme : ils gagnent sur appIcon.
    appIcon:        str = ""
    androidAppIcon: str = ""
    windowsIcon:    str = ""
    macosIcon:      str = ""
    # iosAppIcon est declare plus bas dans la section "iOS specifics".
    webFavicon:     str = ""

    # Installer packaging (MSI/EXE/DEB/PKG). Voir Commands/Package.py.
    #   licenseFile : path vers un .txt/.md/.rtf affiche pendant l'install
    #                 (l'user doit l'accepter pour continuer). Si .txt/.md,
    #                 jenga le convertit automatiquement en RTF minimal.
    #   createDesktopShortcut : si True, l'installer cree un raccourci sur
    #                 le bureau (toggle visible pour l'user pendant l'install).
    #   appPublisher : nom du publisher affiche dans "Programs and Features"
    #                 (sinon "Jenga" par defaut).
    #   appVersion  : version semver "x.y.z" pour les metadonnees installer.
    licenseFile:           str  = ""
    createDesktopShortcut: bool = True
    appPublisher:          str  = ""
    appVersion:            str  = ""
    # Bag d'options libres lues par les builders installer. Permet a l'user
    # d'ajouter de nouvelles options (autostart, registry entries, branding,
    # etc.) sans qu'on doive elargir l'API. Voir installeroption() ci-dessous.
    installerOptions:      Dict[str, "object"] = field(default_factory=dict)

    # Permissions reseau / firewall — installer-time. Voir DSL networkenabled()
    # et firewallrule(). Les builders d'installer (MSI WiX 3/4, Inno EXE, DEB
    # postinst, PKG postinstall) creent les regles necessaires pour que l'app
    # puisse accepter des connexions LAN/Internet entrantes sans intervention
    # manuelle de l'utilisateur (cf [[pong_firewall_lan_fix]]).
    #
    #   networkEnabled        : True par defaut pour les apps exe/windowed.
    #                           Si False, aucune regle firewall n'est creee.
    #   firewallRules         : liste de regles personnalisees (FirewallRule).
    #                           Si vide ET networkEnabled, une regle par defaut
    #                           "{AppName} (Network)" est creee, dir=in,
    #                           profile=any, allow all programs/ports.
    #   networkUsageDescription : phrase affichee a l'utilisateur (iOS
    #                           NSLocalNetworkUsageDescription, prompts macOS
    #                           si firewall stealth mode activement). Si vide,
    #                           fallback "{AppName} a besoin d'acceder au reseau
    #                           local pour fonctionner".
    #   bonjourServices       : liste de types Bonjour/mDNS (ex "_http._tcp")
    #                           publies/decouverts par l'app. Injecte dans
    #                           NSBonjourServices (iOS) et dans la regle
    #                           firewall macOS (port 5353).
    #   allowArbitraryLoads   : iOS NSAppTransportSecurity allowsArbitraryLoads
    #                           (autorise HTTP en clair, requis pour LAN sans
    #                           TLS). False par defaut.
    networkEnabled:           bool         = False
    firewallRules:            List["FirewallRule"] = field(default_factory=list)
    networkUsageDescription:  str          = ""
    bonjourServices:          List[str]    = field(default_factory=list)
    allowArbitraryLoads:      bool         = False

    # Compiler settings
    defines: List[str] = field(default_factory=list)
    optimize: Optimization = Optimization.OFF
    symbols: bool = True
    warnings: WarningLevel = WarningLevel.DEFAULT
    runtime: Optional[str] = None  # MSVC runtime library: "Debug"/"Release" or "MD"/"MDd"/"MT"/"MTd"

    # Toolchain
    toolchain: Optional[str] = None
    _explicitToolchain: bool = False

    # Build hooks
    preBuildCommands: List[str] = field(default_factory=list)
    postBuildCommands: List[str] = field(default_factory=list)
    preLinkCommands: List[str] = field(default_factory=list)
    postLinkCommands: List[str] = field(default_factory=list)

    # Platform specific (system: filter)
    systemDefines: Dict[str, List[str]] = field(default_factory=dict)
    systemLinks: Dict[str, List[str]] = field(default_factory=dict)

    # Android specifics
    androidApplicationId: str = ""
    androidVersionCode: int = 1
    androidVersionName: str = "1.0"
    androidMinSdk: int = 21
    androidTargetSdk: int = 33
    androidCompileSdk: int = 33
    androidAbis: List[str] = field(default_factory=list)
    androidProguard: bool = False
    androidProguardRules: List[str] = field(default_factory=list)
    androidAssets: List[str] = field(default_factory=list)
    androidPermissions: List[str] = field(default_factory=list)
    androidNativeActivity: bool = True
    androidAllowRotation: bool = True
    androidStl: str = ""  # "c++_static" | "c++_shared" | "" (auto)
    androidScreenOrientation: str = ""
    ndkVersion: str = ""
    androidSign: bool = False
    androidKeystore: str = ""
    androidKeystorePass: str = ""
    androidKeyAlias: str = ""
    androidJavaFiles: List[str] = field(default_factory=list)
    androidJavaLibs: List[str] = field(default_factory=list)

    # iOS specifics (extended)
    iosBundleId: str = ""
    iosVersion: str = "1.0"
    iosMinSdk: str = ""
    iosTargetSdk: str = ""  # éventuellement
    iosBuildNumber: str = "1"
    iosSigningIdentity: str = ""
    iosEntitlements: str = ""
    iosAppIcon: str = ""
    iosBuildSystem: str = "direct"   # "direct" ou "xcode"
    iosDistributionType: str = "development"
    iosTeamId: str = ""
    iosProvisioningProfile: str = ""

    # Ressources spécifiques iOS (à copier dans le bundle)
    iosResources: List[str] = field(default_factory=list)

    # Pour tvOS, watchOS, iPadOS, visionOS on peut avoir des champs similaires
    tvosMinSdk: str = ""
    watchosMinSdk: str = ""
    ipadosMinSdk: str = ""
    visionosMinSdk: str = ""

    # Frameworks à embarquer (optionnel)
    iosEmbedFrameworks: List[str] = field(default_factory=list)

    # Xbox specifics
    xboxSigningMode: str = "test"      # test, random, stable
    xboxPackageName: str = ""
    xboxPublisher: str = "Jenga"
    xboxVersion: str = "1.0.0.0"
    xboxLEKBPath: str = ""
    xboxAssetChunks: List[str] = field(default_factory=list)

    # Emscripten specifics
    emscriptenShellFile: str = ""      # Custom HTML template (shell file)
    emscriptenUseFullscreenShell: Optional[bool] = None  # Override workspace fullscreen shell default
    emscriptenCanvasId: str = "canvas"  # HTML canvas element ID
    emscriptenInitialMemory: int = 16   # Initial memory in MB
    emscriptenStackSize: int = 5        # Stack size in MB
    emscriptenExportName: str = "Module" # Global export name
    emscriptenExtraFlags: List[str] = field(default_factory=list)  # Extra emcc flags

    # HarmonyOs
    harmonyMinSdk: str = ""
    harmonyTargetApi: int = 12
    harmonyBundleName: str = ""
    harmonyVersionCode: int = 1
    harmonyVersionName: str = "1.0.0"
    harmonySign: bool = False
    harmonyCertFile: str = ""
    harmonyProfile: str = ""
    harmonyAppIcon: str = ""
    harmonyKeyPwd : str = ""
    harmonyKeyAlias : str = ""
    harmonyKeystore : str = ""
    harmonyResDirs: List[str] = field(default_factory=list)
    harmonyAssets: List[str] = field(default_factory=list)
    # Permissions HarmonyOS (ohos.permission.*) injectees dans module.json5 >
    # requestPermissions. Fusionnees avec les permissions reseau auto si
    # networkenabled(True). Voir harmonypermissions() + Core/FirewallSpec.py.
    harmonyPermissions: List[str] = field(default_factory=list)
    # Repertoires de sources ArkTS/ETS (.ets) a copier dans entry/src/main/ets.
    # Le builder les cherche via getattr(project, 'harmonyEtsDirs', []).
    harmonyEtsDirs: List[str] = field(default_factory=list)

    # Test settings
    isTest: bool = False
    parentProject: Optional[str] = None
    testOptions: List[str] = field(default_factory=list)
    testFiles: List[str] = field(default_factory=list)
    testMainFile: str = ""
    testMainTemplate: str = ""

    # Build options (generic)
    buildOptions: Dict[str, List[str]] = field(default_factory=dict)

    # Filter context – internal
    _currentFilter: Optional[str] = None
    _filteredFiles: Dict[str, List[str]] = field(default_factory=dict)
    _filteredExcludeFiles: Dict[str, List[str]] = field(default_factory=dict)
    _filteredExcludeMainFiles: Dict[str, List[str]] = field(default_factory=dict)
    _filteredIncludeDirs: Dict[str, List[str]] = field(default_factory=dict)
    _filteredLibDirs: Dict[str, List[str]] = field(default_factory=dict)
    _filteredObjDir: Dict[str, str] = field(default_factory=dict)
    _filteredTargetDir: Dict[str, str] = field(default_factory=dict)
    _filteredTargetName: Dict[str, str] = field(default_factory=dict)
    _filteredPchHeader: Dict[str, str] = field(default_factory=dict)
    _filteredPchSource: Dict[str, str] = field(default_factory=dict)
    _filteredDependsOn: Dict[str, List[str]] = field(default_factory=dict)
    _filteredDependFiles: Dict[str, List[str]] = field(default_factory=dict)
    _filteredEmbedResources: Dict[str, List[str]] = field(default_factory=dict)
    _filteredDefines: Dict[str, List[str]] = field(default_factory=dict)
    _filteredLinks: Dict[str, List[str]] = field(default_factory=dict)
    _filteredCFlags: Dict[str, List[str]] = field(default_factory=dict)
    _filteredCxxFlags: Dict[str, List[str]] = field(default_factory=dict)
    _filteredLdFlags: Dict[str, List[str]] = field(default_factory=dict)
    _filteredPreBuildCommands: Dict[str, List[str]] = field(default_factory=dict)
    _filteredPostBuildCommands: Dict[str, List[str]] = field(default_factory=dict)
    _filteredPreLinkCommands: Dict[str, List[str]] = field(default_factory=dict)
    _filteredPostLinkCommands: Dict[str, List[str]] = field(default_factory=dict)
    _filteredRemoveIncludeDirs: Dict[str, List[str]] = field(default_factory=dict)
    _filteredRemoveLibDirs: Dict[str, List[str]] = field(default_factory=dict)
    _filteredRemoveLinks: Dict[str, List[str]] = field(default_factory=dict)
    _filteredRemoveDependsOn: Dict[str, List[str]] = field(default_factory=dict)
    _filteredRemoveDefines: Dict[str, List[str]] = field(default_factory=dict)
    _filteredKind: Dict[str, 'ProjectKind'] = field(default_factory=dict)
    _filteredToolchain: Dict[str, str] = field(default_factory=dict)
    _filteredOptimize: Dict[str, Optimization] = field(default_factory=dict)
    _filteredSymbols: Dict[str, bool] = field(default_factory=dict)
    _filteredWarnings: Dict[str, WarningLevel] = field(default_factory=dict)
    _filteredRuntime: Dict[str, str] = field(default_factory=dict)

    # Inclusion metadata
    _external: bool = False
    _externalFile: str = ""
    _externalDir: str = ""
    _originalLocation: str = ""
    _inWorkspace: bool = False
    _standalone: bool = False


@dataclass
class Workspace:
    """Workspace configuration – cross‑platform."""
    name: str
    location: str = ""
    configurations: List[str] = field(default_factory=lambda: ["Debug", "Release"])
    platforms: List[str] = field(default_factory=lambda: ["Windows"])   # legacy, use targetOses
    targetOses: List[TargetOS] = field(default_factory=list)
    targetArchs: List[TargetArch] = field(default_factory=list)
    startProject: str = ""
    options: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    projects: Dict[str, Project] = field(default_factory=dict)
    toolchains: Dict[str, Toolchain] = field(default_factory=dict)
    defaultToolchain: Optional[str] = None

    # Unitest configuration (optional)
    unitestConfig: Optional[UnitestConfig] = None
    disableUnitTestCompilation: bool = False
    disableUnitTestExecution: bool = False

    # Android SDK/NDK paths
    androidSdkPath: str = ""
    androidNdkPath: str = ""
    javaJdkPath: str = ""

    # Emscripten workspace defaults
    # Enabled by default for a cleaner fullscreen Web shell.
    # Can be disabled per workspace/project with emscriptenfullscreenshell(False).
    emscriptenDefaultFullscreenShell: bool = True

    # iOS SDK paths (auto‑detected)
    iosSdkPath: str = ""

    # Xbox SDK/configuration
    gdkPath: str = ""
    xboxPlatform: str = ""      # XboxOne, Scarlett, Desktop
    xboxMode: str = "gdk"       # gdk (GameCore) or uwp (Dev Mode)

    # ← AJOUTER CETTE LIGNE
    harmonySdkPath: str = ""

    # Current context
    _currentProject: Optional[Project] = None
    _currentToolchain: Optional[Toolchain] = None


# ---------------------------------------------------------------------------
# Global state (internal) – _camelCase
# ---------------------------------------------------------------------------

_currentWorkspace: Optional[Workspace] = None
_currentProject: Optional[Project] = None
_currentToolchain: Optional[Toolchain] = None
_currentFilter: Optional[str] = None


def _NormalizeFilterExpression(expr: Any) -> str:
    """Normalize filter expressions to a stable, hashable key."""
    if expr is None:
        return ""
    if isinstance(expr, dict):
        return ""
    if isinstance(expr, (list, tuple)):
        parts = [str(part).strip() for part in expr if str(part).strip()]
        return " && ".join(parts)
    if isinstance(expr, set):
        parts = [str(part).strip() for part in expr if str(part).strip()]
        return " && ".join(sorted(parts))
    return str(expr).strip()


def _NormalizeOptionTrigger(trigger: str) -> str:
    value = str(trigger or "").strip()
    if value.startswith("--"):
        value = value[2:]
    return value.strip().lower()


def _AppendFilteredValues(mapping: Dict[str, List[str]], filter_key: str, values: List[str]) -> None:
    if filter_key not in mapping:
        mapping[filter_key] = []
    mapping[filter_key].extend(values)


def _RemoveValuesInPlace(items: List[str], values: List[str]) -> None:
    if not items or not values:
        return
    patterns = [str(v) for v in values]

    def _should_remove(item: str) -> bool:
        for pattern in patterns:
            if pattern == item or fnmatch.fnmatch(item, pattern):
                return True
        return False

    items[:] = [item for item in items if not _should_remove(item)]

# ---------------------------------------------------------------------------
# Context managers – PascalCase
# ---------------------------------------------------------------------------

class workspace:
    """Workspace context manager – no automatic Unitest injection."""
    def __init__(self, name: str, location: str = ""):
        self._workspace = Workspace(name=name, location=location)

    def __enter__(self) -> Workspace:
        global _currentWorkspace
        _currentWorkspace = self._workspace
        return self._workspace

    def __exit__(self, exc_type, exc_val, exc_tb):
        global _currentWorkspace
        # Keep workspace for later commands
        return False


class project:
    """Project context manager."""
    def __init__(self, name: str):
        self._name = name
        self._project = None

    def __enter__(self) -> Project:
        global _currentWorkspace, _currentProject

        self._project = Project(name=self._name)

        if _currentWorkspace:
            self._project.location = "."
            if _currentWorkspace.defaultToolchain:
                self._project.toolchain = _currentWorkspace.defaultToolchain
                self._project._explicitToolchain = False
            self._project._inWorkspace = True
            _currentWorkspace.projects[self._name] = self._project
        else:
            self._project._inWorkspace = False
            self._project._standalone = True

        _currentProject = self._project
        return self._project

    def __exit__(self, exc_type, exc_val, exc_tb):
        global _currentProject
        if _currentWorkspace is not None:
            _currentProject = None
        return False


class toolchain:
    """Toolchain context manager."""
    def __init__(self, name: str, compilerFamily: Union[str, CompilerFamily]):
        self._name = name
        if isinstance(compilerFamily, str):
            norm = compilerFamily.upper().replace("-", "_").replace(" ", "_")
            if norm == "ANDROIDNDK":
                norm = "ANDROID_NDK"
            if norm == "APPLECLANG":
                norm = "APPLE_CLANG"
            compilerFamily = CompilerFamily[norm]
        self._compilerFamily = compilerFamily
        self._toolchain = None

    def __enter__(self) -> Toolchain:
        global _currentWorkspace, _currentToolchain

        if _currentWorkspace is None:
            raise RuntimeError("toolchain must be defined inside a workspace")

        self._toolchain = Toolchain(name=self._name, compilerFamily=self._compilerFamily)
        _currentWorkspace.toolchains[self._name] = self._toolchain
        _currentToolchain = self._toolchain
        return self._toolchain

    def __exit__(self, exc_type, exc_val, exc_tb):
        global _currentToolchain
        _currentToolchain = None
        return False


class filter:
    """Filter context for conditional settings."""
    def __init__(self, expr: Any):
        self._expr = expr
        self._previous = None

    def __enter__(self):
        global _currentFilter, _currentProject
        self._previous = _currentFilter
        _currentFilter = _NormalizeFilterExpression(self._expr)
        if _currentProject:
            _currentProject._currentFilter = _currentFilter
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        global _currentFilter, _currentProject
        _currentFilter = self._previous
        if _currentProject:
            _currentProject._currentFilter = self._previous
        return False


class unitest:
    """
    Unitest configuration context (workspace level).
    When this block exits, the __Unitest__ project is created in the workspace.
    """
    def __init__(self):
        self._config = UnitestConfig()

    def Precompiled(self) -> 'unitest':
        """Use precompiled version of Unitest (default)."""
        self._config.mode = "precompiled"
        return self

    def Compile(self, *,
                kind: Union[str, ProjectKind] = ProjectKind.STATIC_LIB,
                objDir: str = "",
                targetDir: str = "",
                targetName: str = "",
                cxxflags: List[str] = None,
                ldflags: List[str] = None,
                defines: List[str] = None) -> 'unitest':
        """Compile Unitest from system sources with custom settings."""
        self._config.mode = "compile"
        if isinstance(kind, str):
            kind = ProjectKind[kind.upper()]
        self._config.kind = kind
        if objDir:
            self._config.objDir = objDir
        if targetDir:
            self._config.targetDir = targetDir
        if targetName:
            self._config.targetName = targetName
        if cxxflags:
            self._config.cxxflags.extend(cxxflags)
        if ldflags:
            self._config.ldflags.extend(ldflags)
        if defines:
            self._config.defines.extend(defines)
        return self

    def __enter__(self) -> 'unitest':
        global _currentWorkspace
        if _currentWorkspace is None:
            raise RuntimeError("unitest context must be inside a workspace")
        _currentWorkspace.unitestConfig = self._config
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        _EnsureUnitestProject(_currentWorkspace)
        return False


def _EnsureUnitestProject(workspace: Optional[Workspace]) -> None:
    """
    Ensure the internal __Unitest__ project exists whenever unitestConfig is set.
    This is used both on leaving `with unitest():` and as a safety net in `with test():`.
    """
    if workspace is None or workspace.unitestConfig is None:
        return

    if "__Unitest__" in workspace.projects:
        return

    config = workspace.unitestConfig

    unitestProj = Project(name="__Unitest__")
    unitestProj.kind = config.kind
    unitestProj.language = Language.CPP
    unitestProj.cppdialect = "C++20"

    if config.isPrecompiled():
        # Precompiled mode: values resolved by backend/variable expander.
        unitestProj.location = "%{Jenga.Unitest.Location}"
        unitestProj.includeDirs = ["%{Jenga.Unitest.Include}"]
        unitestProj.libDirs = ["%{Jenga.Unitest.Lib}"]
        unitestProj.targetDir = "%{Jenga.Unitest.TargetDir}"
        unitestProj.targetName = config.targetName
        unitestProj.objDir = "%{Jenga.Unitest.ObjDir}"
    else:
        # Compile mode: compile Unitest sources from bundled tree.
        unitestProj.location = "%{Jenga.Unitest.Source}"
        unitestProj.includeDirs = ["%{Jenga.Unitest.Source}/src"]
        unitestProj.files = [
            "%{Jenga.Unitest.Source}/src/Unitest/**.cpp",
            "%{Jenga.Unitest.Source}/src/Unitest/**.h",
        ]
        unitestProj.objDir = config.objDir
        unitestProj.targetDir = config.targetDir
        unitestProj.targetName = config.targetName
        unitestProj.cxxflags = config.cxxflags
        unitestProj.ldflags = config.ldflags
        unitestProj.defines = config.defines

    workspace.projects["__Unitest__"] = unitestProj


class test:
    """
    Test suite context – creates a test project that depends on Unitest.
    MUST be placed directly inside a project block (indented under 'with project(...):').
    """
    def __init__(self, subname: str = ""):
        self._subname = subname
        self._testProject = None
        self._parent = None
        self._capturedFilter = None  # filter active when the test block was opened

    def __enter__(self) -> Project:
        global _currentWorkspace, _currentProject
        self._capturedFilter = _currentFilter  # capture before any project switch

        if _currentWorkspace is None:
            raise RuntimeError("test context must be inside a workspace")

        # 🔒 CRITICAL: test MUST be placed directly under a non‑test project
        if _currentProject is None or _currentProject.isTest:
            raise RuntimeError(
                "test context must be placed directly inside a project block "
                "(and after a non‑test project)"
            )

        self._parent = _currentProject

        # Ensure Unitest is configured
        if _currentWorkspace.unitestConfig is None:
            raise RuntimeError("Unitest is not configured. Please add a 'unitest' block in the workspace.")

        # Safety net: ensure __Unitest__ exists even if the unitest context did not
        # materialize the project yet (e.g., legacy/stale execution context).
        _EnsureUnitestProject(_currentWorkspace)

        if "__Unitest__" not in _currentWorkspace.projects:
            raise RuntimeError("Unitest project '__Unitest__' not found. Did the unitest block fail to create it?")

        # Create test project
        testName = f"{self._parent.name}_Tests"
        if self._subname:
            testName = f"{self._parent.name}_{self._subname}_Tests"

        self._testProject = Project(name=testName)
        self._testProject.kind = ProjectKind.TEST_SUITE
        self._testProject.language = self._parent.language
        self._testProject.cppdialect = self._parent.cppdialect
        self._testProject.cdialect = self._parent.cdialect
        self._testProject.isTest = True
        self._testProject.parentProject = self._parent.name

        # Location: same as parent
        self._testProject.location = self._parent.location if self._parent.location else "."

        # Dependencies: parent + Unitest + all of parent's deps (needed for dep_link_map path resolution)
        self._testProject.dependsOn = (
            [self._parent.name, "__Unitest__"]
            + [d for d in self._parent.dependsOn if d not in ("__Unitest__", self._parent.name)]
        )

        # Copy include dirs, defines, libDirs from parent
        self._testProject.includeDirs = list(self._parent.includeDirs)
        self._testProject.defines     = list(self._parent.defines)
        self._testProject.libDirs     = list(self._parent.libDirs)

        # Copy all per-filter settings from parent (toolchain, links, defines, etc.)
        self._testProject._filteredLinks        = copy.deepcopy(self._parent._filteredLinks)
        self._testProject._filteredDefines      = copy.deepcopy(self._parent._filteredDefines)
        self._testProject._filteredLibDirs      = copy.deepcopy(self._parent._filteredLibDirs)
        self._testProject._filteredIncludeDirs  = copy.deepcopy(self._parent._filteredIncludeDirs)
        self._testProject._filteredDependsOn    = copy.deepcopy(self._parent._filteredDependsOn)
        self._testProject._filteredToolchain    = copy.deepcopy(self._parent._filteredToolchain)
        self._testProject._filteredOptimize     = copy.deepcopy(self._parent._filteredOptimize)
        self._testProject._filteredSymbols      = copy.deepcopy(self._parent._filteredSymbols)

        # Add Unitest include/lib using variables (resolved by backend)
        if _currentWorkspace.unitestConfig.isPrecompiled():
            self._testProject.includeDirs.append("%{Jenga.Unitest.Include}")
            self._testProject.libDirs.append("%{Jenga.Unitest.TargetDir}")
            self._testProject.links.append("%{Jenga.Unitest.Lib}")
        else:
            # Compile mode: include Unitest headers from source tree.
            self._testProject.includeDirs.append("%{Jenga.Unitest.Source}/src")

        # Inherit links from parent: [Unitest.Lib already added above] + parent lib + parent deps + parent global links
        _inherited = []
        _existing  = set(self._testProject.links)
        for lib in ([self._parent.name]
                    + [d for d in self._parent.dependsOn if d != "__Unitest__"]
                    + list(self._parent.links)):
            if lib not in _existing and lib not in _inherited:
                _inherited.append(lib)
        self._testProject.links.extend(_inherited)

        # Set output directories
        self._testProject.targetDir = "%{wks.location}/Build/Tests/%{cfg.buildcfg}-%{cfg.system}"
        self._testProject.objDir = "%{wks.location}/Build/Obj/%{cfg.buildcfg}-%{cfg.system}/%{prj.name}"

        # Add to workspace
        _currentWorkspace.projects[testName] = self._testProject
        _currentProject = self._testProject

        return self._testProject

    def __exit__(self, exc_type, exc_val, exc_tb):
        global _currentProject

        # Auto‑include test files if testfiles() was called inside the test context without a filter.
        # (Filter-guarded testfiles were already routed to _filteredFiles by testfiles().)
        if self._testProject.testFiles:
            self._testProject.files.extend(self._testProject.testFiles)

        # Exclude main file from parent if specified
        if self._testProject.testMainFile:
            self._testProject.excludeMainFiles.append(self._testProject.testMainFile)

        # Determine whether any test files were registered (filtered or not).
        _has_any_test_files = (
            bool(self._testProject.testFiles)
            or bool(getattr(self._testProject, "_filteredFiles", {}))
        )

        # Inject test main template only when test files actually exist.
        wks = _currentWorkspace
        if _has_any_test_files and wks and wks.unitestConfig:
            if not self._testProject.testMainTemplate:
                self._testProject.testMainTemplate = "%{Jenga.Unitest.AutoMainTemplate}"

        # Add the template under the same filter that guarded testfiles(), if any.
        if _has_any_test_files and self._testProject.testMainTemplate:
            if self._capturedFilter:
                _AppendFilteredValues(
                    self._testProject._filteredFiles,
                    self._capturedFilter,
                    [self._testProject.testMainTemplate],
                )
            else:
                self._testProject.files.append(self._testProject.testMainTemplate)

        _currentProject = None
        return False


class include:
    """
    Context manager for including external .jenga files.
    Supports filtering with .only() and .skip().
    """
    def __init__(self, jengaFile: str):
        self._jengaFile = jengaFile
        self._jengaPath = None
        self._externalDir = None
        self._parentWorkspace = None
        self._tempWorkspace = None
        self._filterMode = None
        self._filterProjects = []

    def __enter__(self):
        global _currentWorkspace
        if _currentWorkspace is None:
            raise RuntimeError("include must be used inside a workspace")

        self._parentWorkspace = _currentWorkspace
        self._jengaPath = Path(self._jengaFile)
        if not self._jengaPath.is_absolute():
            wksDir = Path(self._parentWorkspace.location) if self._parentWorkspace.location else Path.cwd()
            self._jengaPath = wksDir / self._jengaPath
        if not self._jengaPath.exists():
            raise FileNotFoundError(f"External file not found: {self._jengaPath}")

        self._externalDir = self._jengaPath.parent.absolute()
        self._tempWorkspace = Workspace(name=f"__include_{self._jengaPath.stem}__")
        self._tempWorkspace.location = str(self._externalDir)

        # Inherit toolchains and unitest config from parent
        self._tempWorkspace.toolchains = dict(self._parentWorkspace.toolchains)
        self._tempWorkspace.defaultToolchain = self._parentWorkspace.defaultToolchain
        self._tempWorkspace.unitestConfig = self._parentWorkspace.unitestConfig

        # Read and prepare external code
        content = self._jengaPath.read_text(encoding='utf-8-sig')
        # Comment out jenga imports
        content = re.sub(
            r'^(\s*)(from\s+[Jj]enga\..*?import\s+.*?)$',
            r'\1# \2',
            content,
            flags=re.MULTILINE
        )

        exec_globals = self._CreateExecContext()
        old_cwd = Path.cwd()
        os.chdir(self._externalDir)

        try:
            _currentWorkspace = self._tempWorkspace
            exec(content, exec_globals)
        finally:
            _currentWorkspace = self._parentWorkspace
            os.chdir(old_cwd)

        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Transfer selected projects from temp workspace to parent."""
        def _ResolvePath(p: str, baseDir: Optional[Path] = None) -> str:
            if baseDir is None:
                baseDir = self._externalDir
            pobj = Path(p)
            if pobj.is_absolute() or '%{' in p:
                return p
            resolved = baseDir / pobj
            wksDir = Path(self._parentWorkspace.location) if self._parentWorkspace.location else Path.cwd()
            try:
                return str(resolved.relative_to(wksDir))
            except ValueError:
                return str(resolved)

        projectsToInclude = set(self._tempWorkspace.projects.keys())
        if self._filterMode == 'only':
            projectsToInclude &= set(self._filterProjects)
        elif self._filterMode == 'skip':
            projectsToInclude -= set(self._filterProjects)
        # Exclude internal projects (starting with __)
        projectsToInclude = {p for p in projectsToInclude if not p.startswith('__')}

        for projName in projectsToInclude:
            proj = self._tempWorkspace.projects[projName]

            # Adjust location
            if proj.location in (".", ""):
                proj.location = str(self._externalDir)
            elif not Path(proj.location).is_absolute() and '%{' not in proj.location:
                proj.location = str(self._externalDir / Path(proj.location))
            proj_base = Path(proj.location) if proj.location else self._externalDir

            # Adjust all path fields
            # Keep source patterns relative to project location.
            proj.files = list(proj.files)
            proj.excludeFiles = list(proj.excludeFiles)
            proj.excludeMainFiles = list(proj.excludeMainFiles)
            proj.includeDirs = list(proj.includeDirs)
            proj.libDirs = list(proj.libDirs)
            proj.dependFiles = list(proj.dependFiles)
            proj.embedResources = list(proj.embedResources)
            proj.testFiles = list(proj.testFiles)

            # Mark as external
            proj._external = True
            proj._externalFile = str(self._jengaPath)
            proj._externalDir = str(self._externalDir)

            self._parentWorkspace.projects[projName] = proj

        # Transfer new toolchains
        for tcName, tc in self._tempWorkspace.toolchains.items():
            if tcName not in self._parentWorkspace.toolchains:
                if tc.sysroot and not Path(tc.sysroot).is_absolute() and '%{' not in tc.sysroot:
                    tc.sysroot = _ResolvePath(tc.sysroot)
                if tc.toolchainDir and not Path(tc.toolchainDir).is_absolute() and '%{' not in tc.toolchainDir:
                    tc.toolchainDir = _ResolvePath(tc.toolchainDir)
                tc._external = True
                tc._externalFile = str(self._jengaPath)
                self._parentWorkspace.toolchains[tcName] = tc

        return False

    def only(self, projects: List[str]) -> 'include':
        """Include only specified projects."""
        self._filterMode = 'only'
        self._filterProjects = projects
        return self

    def skip(self, projects: List[str]) -> 'include':
        """Skip specified projects."""
        self._filterMode = 'skip'
        self._filterProjects = projects
        return self

    def _CreateExecContext(self) -> dict:
        """Create isolated execution context for external file."""
        import sys
        from pathlib import Path

        exec_globals = {
            '__file__': str(self._jengaPath),
            '__name__': '__external__',
            '__builtins__': __builtins__,
            'Path': Path,
            '_currentWorkspace': self._tempWorkspace,
            '_currentProject': None,
            '_currentToolchain': None,
            '_currentFilter': None,
        }

        # Inject all public API functions and classes
        current_module = sys.modules[__name__]
        exclude = {'include', 'getcurrentworkspace', 'resetstate'}
        for name in dir(current_module):
            if not name.startswith('_') and name not in exclude:
                exec_globals[name] = getattr(current_module, name)

        return exec_globals


class batchinclude:
    """
    Include multiple .jenga files at once.
    Usage:
        with batchinclude([
            "libs/logger.jenga",
            "libs/math.jenga"
        ]):
            pass

        with batchinclude({
            "libs/logger.jenga": ["Logger"],
            "libs/math.jenga": None   # all
        }):
            pass
    """
    def __init__(self, includes: Union[List[str], Dict[str, Optional[List[str]]]]):
        self._includes = includes
        self._includedProjects = []

    def __enter__(self):
        if isinstance(self._includes, list):
            for file in self._includes:
                with include(file) as inc:
                    self._includedProjects.extend(inc._includedProjects)
        else:
            for file, filterList in self._includes.items():
                with include(file) as inc:
                    if filterList is not None:
                        inc.only(filterList)
                    self._includedProjects.extend(inc._includedProjects)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return False


# ---------------------------------------------------------------------------
# User‑exposed functions – ALL LOWERCASE, NO UNDERSCORES, ONE WORD
# ---------------------------------------------------------------------------

# --- Workspace configuration ---
def configurations(names: List[str]) -> None:
    if _currentWorkspace:
        _currentWorkspace.configurations = names

# ============================================================================
# 5. AMÉLIORATION DE platforms() (legacy mais toujours amélioré)
# ============================================================================

def platforms(names):
    """
    Définit les plateformes (legacy) avec normalisation.
    
    Args:
        names: Liste de noms de plateformes
    
    Note:
        Cette fonction est legacy. Utilisez targetoses() et targetarchs() à la place.
    """
    if _currentWorkspace:
        # Normaliser les noms de plateformes
        normalized = []
        for name in names:
            normalized_name = _NormalizeOSName(name)
            # Pour platforms, on garde les chaînes (legacy)
            # Mais on les normalise pour la cohérence
            if normalized_name in [e.name for e in TargetOS]:
                normalized.append(TargetOS[normalized_name].value)
            else:
                # Garder la chaîne originale si pas reconnue
                normalized.append(name)
        
        _currentWorkspace.platforms = normalized

def targetoses(oslist: List[Union[str, TargetOS]]) -> None:
    if _currentWorkspace:
        _currentWorkspace.targetOses = [
            TargetOS[o.upper()] if isinstance(o, str) else o for o in oslist
        ]

def targetarchs(archlist: List[Union[str, TargetArch]]) -> None:
    if _currentWorkspace:
        _currentWorkspace.targetArchs = [
            TargetArch[a.upper()] if isinstance(a, str) else a for a in archlist
        ]

def targetos(ositem: Union[str, TargetOS]) -> None:
    """Shortcut: set a single target OS."""
    targetoses([ositem])

def targetarch(architem: Union[str, TargetArch]) -> None:
    """Shortcut: set a single target architecture."""
    targetarchs([architem])

def platform(ositem: Union[str, TargetOS]) -> None:
    """Shortcut alias for targetos()."""
    targetos(ositem)

def architecture(architem: Union[str, TargetArch]) -> None:
    """Shortcut alias for targetarch()."""
    targetarch(architem)

def startproject(name: str) -> None:
    if _currentWorkspace:
        _currentWorkspace.startProject = name

def disableunittestcompilation(enable: bool = True) -> None:
    """Disable compilation of unit-test projects at workspace scope."""
    if _currentWorkspace:
        _currentWorkspace.disableUnitTestCompilation = bool(enable)

def disableunittestexecution(enable: bool = True) -> None:
    """Disable execution of unit tests at workspace scope."""
    if _currentWorkspace:
        _currentWorkspace.disableUnitTestExecution = bool(enable)

def dutc(enable: bool = True) -> None:
    """Shortcut for disableunittestcompilation()."""
    disableunittestcompilation(enable)

def dute(enable: bool = True) -> None:
    """Shortcut for disableunittestexecution()."""
    disableunittestexecution(enable)


def newoption(option: Optional[Union[Dict[str, Any], str]] = None, **kwargs) -> None:
    """
    Register a Premake-like CLI option at workspace scope.

    Examples:
      newoption({"trigger": "with-sdl", "value": "path", "description": "SDL3 root"})
      newoption(trigger="asan", description="Enable AddressSanitizer", default=True)
    """
    if _currentWorkspace is None:
        raise RuntimeError("newoption must be used inside a workspace")

    payload: Dict[str, Any] = {}
    if isinstance(option, dict):
        payload.update(option)
    elif isinstance(option, str):
        payload["trigger"] = option
    elif option is not None:
        raise TypeError("newoption expects a dict, a trigger string, or keyword arguments")
    payload.update(kwargs)

    trigger = _NormalizeOptionTrigger(payload.get("trigger", ""))
    if not trigger:
        raise ValueError("newoption requires a non-empty 'trigger'")

    value_name = str(payload.get("value", "") or "").strip()
    description = str(payload.get("description", "") or "").strip()
    category = str(payload.get("category", "") or "").strip()
    default_value = payload.get("default", None)

    allowed_raw = payload.get("allowed", payload.get("values", []))
    allowed_values: List[str] = []
    if isinstance(allowed_raw, dict):
        allowed_values = [str(k).strip() for k in allowed_raw.keys() if str(k).strip()]
    elif isinstance(allowed_raw, (list, tuple, set)):
        for entry in allowed_raw:
            if isinstance(entry, (list, tuple)) and entry:
                token = str(entry[0]).strip()
                if token:
                    allowed_values.append(token)
            else:
                token = str(entry).strip()
                if token:
                    allowed_values.append(token)

    existing = dict((_currentWorkspace.options or {}).get(trigger, {}))
    existing.update({
        "trigger": trigger,
        "value": value_name,
        "description": description,
        "category": category,
        "allowed": allowed_values,
    })
    if "default" in payload:
        existing["default"] = default_value
    elif "default" not in existing:
        existing["default"] = None

    _currentWorkspace.options[trigger] = existing

# --- Project kind setters (filter-aware) ---
def _SetProjectKind(k: ProjectKind) -> None:
    """Internal: set project kind, respecting active filter context."""
    if not _currentProject:
        return
    if _currentFilter:
        _currentProject._filteredKind[_currentFilter] = k
    else:
        _currentProject.kind = k

def consoleapp() -> None:
    _SetProjectKind(ProjectKind.CONSOLE_APP)

def windowedapp() -> None:
    _SetProjectKind(ProjectKind.WINDOWED_APP)

def staticlib() -> None:
    _SetProjectKind(ProjectKind.STATIC_LIB)

def sharedlib() -> None:
    _SetProjectKind(ProjectKind.SHARED_LIB)

def testsuite() -> None:
    _SetProjectKind(ProjectKind.TEST_SUITE)
    if _currentProject and not _currentFilter:
        _currentProject.isTest = True

def kind(k: Union[str, ProjectKind]) -> None:
    """Generic kind setter (alternative to specific functions)."""
    if _currentProject:
        if isinstance(k, str):
            k = ProjectKind[k.upper()]
        _SetProjectKind(k)
        if k == ProjectKind.TEST_SUITE and not _currentFilter:
            _currentProject.isTest = True

def kindexport(k: Union[str, ProjectKind], ke: str) -> None:
    """Generic kind export setter (alternative to specific functions)."""
    if _currentProject:
        kind(k)

        name = "" if len(ke) == 0 or ke == "" else f"{ke.upper()}"

        if k == ProjectKind.STATIC_LIB:
            defines([f"{name}_STATIC_LIB"])
        elif k == ProjectKind.SHARED_LIB:
            defines([f"{name}_BUILD_SHARED_LIB"])

# --- Language and dialect ---
def language(lang: Union[str, Language]) -> None:
    if _currentProject:
        if isinstance(lang, str):
            key = lang.strip().lower()
            aliases = {
                "c": Language.C,
                "cpp": Language.CPP,
                "c++": Language.CPP,
                "objective-c": Language.OBJC,
                "objc": Language.OBJC,
                "objective-c++": Language.OBJCPP,
                "objc++": Language.OBJCPP,
                "assembly": Language.ASM,
                "asm": Language.ASM,
                "rust": Language.RUST,
                "zig": Language.ZIG,
            }
            if key in aliases:
                _currentProject.language = aliases[key]
            else:
                norm = lang.upper().replace("+", "P").replace("-", "").replace(" ", "")
                _currentProject.language = Language[norm]
        else:
            _currentProject.language = lang

def cppdialect(dialect: str) -> None:
    if _currentProject:
        _currentProject.cppdialect = dialect

def cppversion(dialect: str) -> None:
    if _currentProject:
        _currentProject.cppdialect = dialect

def cdialect(dialect: str) -> None:
    if _currentProject:
        _currentProject.cdialect = dialect

def cversion(dialect: str) -> None:
    if _currentProject:
        _currentProject.cdialect = dialect

# --- Project location ---
def location(path: str) -> None:
    if _currentProject:
        _currentProject.location = path

# --- Files and directories ---
def files(patterns: List[str]) -> None:
    if _currentProject:
        if _currentFilter:
            _AppendFilteredValues(_currentProject._filteredFiles, _currentFilter, patterns)
        else:
            _currentProject.files.extend(patterns)

def excludefiles(patterns: List[str]) -> None:
    if _currentProject:
        if _currentFilter:
            _AppendFilteredValues(_currentProject._filteredExcludeFiles, _currentFilter, patterns)
        else:
            _currentProject.excludeFiles.extend(patterns)

removefiles = excludefiles

def excludemainfiles(patterns: List[str]) -> None:
    if _currentProject:
        if _currentFilter:
            _AppendFilteredValues(_currentProject._filteredExcludeMainFiles, _currentFilter, patterns)
        else:
            _currentProject.excludeMainFiles.extend(patterns)

removemainfiles = excludemainfiles

def includedirs(dirs: List[str]) -> None:
    if _currentProject:
        if _currentFilter:
            _AppendFilteredValues(_currentProject._filteredIncludeDirs, _currentFilter, dirs)
        else:
            _currentProject.includeDirs.extend(dirs)

def externalincludedirs(dirs: List[str]) -> None:
    """
    Premake-compatible alias.
    Jenga currently treats external include dirs the same as regular include dirs.
    """
    includedirs(dirs)

def sysincludedirs(dirs: List[str]) -> None:
    """Premake-compatible alias for system include directories."""
    includedirs(dirs)

def removeincludedirs(dirs: List[str]) -> None:
    if _currentProject:
        if _currentFilter:
            _AppendFilteredValues(_currentProject._filteredRemoveIncludeDirs, _currentFilter, dirs)
        else:
            _RemoveValuesInPlace(_currentProject.includeDirs, dirs)

def libdirs(dirs: List[str]) -> None:
    if _currentProject:
        if _currentFilter:
            _AppendFilteredValues(_currentProject._filteredLibDirs, _currentFilter, dirs)
        else:
            _currentProject.libDirs.extend(dirs)

def syslibdirs(dirs: List[str]) -> None:
    """Premake-compatible alias for system library directories."""
    libdirs(dirs)

def removelibdirs(dirs: List[str]) -> None:
    if _currentProject:
        if _currentFilter:
            _AppendFilteredValues(_currentProject._filteredRemoveLibDirs, _currentFilter, dirs)
        else:
            _RemoveValuesInPlace(_currentProject.libDirs, dirs)

def objdir(path: str) -> None:
    if _currentProject:
        if _currentFilter:
            _currentProject._filteredObjDir[_currentFilter] = path
        else:
            _currentProject.objDir = path

def targetdir(path: str) -> None:
    if _currentProject:
        if _currentFilter:
            _currentProject._filteredTargetDir[_currentFilter] = path
        else:
            _currentProject.targetDir = path

def targetname(name: str) -> None:
    if _currentProject:
        if _currentFilter:
            _currentProject._filteredTargetName[_currentFilter] = name
        else:
            _currentProject.targetName = name

# --- Dependencies ---
def links(libs: List[str]) -> None:
    if _currentProject:
        if _currentFilter:
            _AppendFilteredValues(_currentProject._filteredLinks, _currentFilter, libs)

            # Keep legacy per-system map for compatibility/introspection.
            if _currentFilter.startswith("system:"):
                system = _currentFilter.split(":")[1]
                if system not in _currentProject.systemLinks:
                    _currentProject.systemLinks[system] = []
                _currentProject.systemLinks[system].extend(libs)
        else:
            _currentProject.links.extend(libs)

def removelinks(libs: List[str]) -> None:
    if _currentProject:
        if _currentFilter:
            _AppendFilteredValues(_currentProject._filteredRemoveLinks, _currentFilter, libs)
        else:
            _RemoveValuesInPlace(_currentProject.links, libs)

def dependson(deps: List[str]) -> None:
    if _currentProject:
        if _currentFilter:
            _AppendFilteredValues(_currentProject._filteredDependsOn, _currentFilter, deps)
        else:
            _currentProject.dependsOn.extend(deps)

def removedependson(deps: List[str]) -> None:
    if _currentProject:
        if _currentFilter:
            _AppendFilteredValues(_currentProject._filteredRemoveDependsOn, _currentFilter, deps)
        else:
            _RemoveValuesInPlace(_currentProject.dependsOn, deps)

def dependfiles(patterns: List[str]) -> None:
    if _currentProject:
        if _currentFilter:
            _AppendFilteredValues(_currentProject._filteredDependFiles, _currentFilter, patterns)
        else:
            _currentProject.dependFiles.extend(patterns)

def embedresources(resources: List[str]) -> None:
    if _currentProject:
        if _currentFilter:
            _AppendFilteredValues(_currentProject._filteredEmbedResources, _currentFilter, resources)
        else:
            _currentProject.embedResources.extend(resources)

# --- Compiler settings ---
def defines(defs: List[str]) -> None:
    if _currentToolchain:
        _currentToolchain.defines.extend(defs)
    elif _currentProject:
        if _currentFilter:
            _AppendFilteredValues(_currentProject._filteredDefines, _currentFilter, defs)
        else:
            _currentProject.defines.extend(defs)

def removedefines(defs: List[str]) -> None:
    if _currentProject:
        if _currentFilter:
            _AppendFilteredValues(_currentProject._filteredRemoveDefines, _currentFilter, defs)
        else:
            _RemoveValuesInPlace(_currentProject.defines, defs)

undefines = removedefines

def optimize(level: Union[str, Optimization]) -> None:
    if _currentProject:
        if isinstance(level, str):
            opt = Optimization[level.upper()]
        else:
            opt = level
        if _currentFilter:
            _currentProject._filteredOptimize[_currentFilter] = opt
        else:
            _currentProject.optimize = opt

def symbols(enable: Union[bool, str]) -> None:
    if _currentProject:
        if isinstance(enable, str):
            sym = enable.lower() in ("on", "true", "yes", "1")
        else:
            sym = enable
        if _currentFilter:
            _currentProject._filteredSymbols[_currentFilter] = sym
        else:
            _currentProject.symbols = sym

def runtime(lib: str) -> None:
    """
    Set MSVC runtime library type (Windows/MSVC specific).
    Common values:
      - "Debug" or "MDd": Multi-threaded DLL Debug
      - "Release" or "MD": Multi-threaded DLL Release
      - "MT": Multi-threaded static
      - "MTd": Multi-threaded static Debug
    """
    if _currentProject:
        if _currentFilter:
            _currentProject._filteredRuntime[_currentFilter] = lib
        else:
            _currentProject.runtime = lib

def warnings(level: Union[str, WarningLevel]) -> None:
    if _currentToolchain:
        _warningsTc(level)
    elif _currentProject:
        if isinstance(level, str):
            lvl = WarningLevel[level.upper()]
        else:
            lvl = level
        if _currentFilter:
            _currentProject._filteredWarnings[_currentFilter] = lvl
        else:
            _currentProject.warnings = lvl

# --- Precompiled headers ---
def pchheader(header: str) -> None:
    if _currentProject:
        if _currentFilter:
            _currentProject._filteredPchHeader[_currentFilter] = header
        else:
            _currentProject.pchHeader = header

def pchsource(source: str) -> None:
    if _currentProject:
        if _currentFilter:
            _currentProject._filteredPchSource[_currentFilter] = source
        else:
            _currentProject.pchSource = source

# --- Build hooks ---
def prebuild(cmds: List[str]) -> None:
    if _currentProject:
        if _currentFilter:
            _AppendFilteredValues(_currentProject._filteredPreBuildCommands, _currentFilter, cmds)
        else:
            _currentProject.preBuildCommands.extend(cmds)

def postbuild(cmds: List[str]) -> None:
    if _currentProject:
        if _currentFilter:
            _AppendFilteredValues(_currentProject._filteredPostBuildCommands, _currentFilter, cmds)
        else:
            _currentProject.postBuildCommands.extend(cmds)

def prelink(cmds: List[str]) -> None:
    if _currentProject:
        if _currentFilter:
            _AppendFilteredValues(_currentProject._filteredPreLinkCommands, _currentFilter, cmds)
        else:
            _currentProject.preLinkCommands.extend(cmds)

def postlink(cmds: List[str]) -> None:
    if _currentProject:
        if _currentFilter:
            _AppendFilteredValues(_currentProject._filteredPostLinkCommands, _currentFilter, cmds)
        else:
            _currentProject.postLinkCommands.extend(cmds)

# --- Toolchain selection ---
def usetoolchain(name: str) -> None:
    global _currentProject, _currentWorkspace, _currentFilter
    if _currentProject:
        if _currentFilter:
            # Deferred validation: toolchain will be checked at build time
            _currentProject._filteredToolchain[_currentFilter] = name
        else:
            if _currentWorkspace and name not in _currentWorkspace.toolchains:
                raise ValueError(f"Toolchain '{name}' not defined")
            _currentProject.toolchain = name
            _currentProject._explicitToolchain = True
    elif _currentWorkspace:
        if name not in _currentWorkspace.toolchains:
            raise ValueError(f"Toolchain '{name}' not defined")
        _currentWorkspace.defaultToolchain = name
        for proj in _currentWorkspace.projects.values():
            if not proj._explicitToolchain:
                proj.toolchain = name
    else:
        raise RuntimeError("usetoolchain must be inside workspace or project")

# --- Android specific ---
def androidsdkpath(path: str) -> None:
    if _currentWorkspace:
        _currentWorkspace.androidSdkPath = path

def androidndkpath(path: str) -> None:
    if _currentWorkspace:
        _currentWorkspace.androidNdkPath = path

def javajdkpath(path: str) -> None:
    if _currentWorkspace:
        _currentWorkspace.javaJdkPath = path

def androidapplicationid(appid: str) -> None:
    if _currentProject:
        _currentProject.androidApplicationId = appid

def androidversioncode(code: int) -> None:
    if _currentProject:
        _currentProject.androidVersionCode = code

def androidversionname(name: str) -> None:
    if _currentProject:
        _currentProject.androidVersionName = name

def androidminsdk(sdk: int) -> None:
    if _currentProject:
        _currentProject.androidMinSdk = sdk

def androidtargetsdk(sdk: int) -> None:
    if _currentProject:
        _currentProject.androidTargetSdk = sdk

def androidcompilesdk(sdk: int) -> None:
    if _currentProject:
        _currentProject.androidCompileSdk = sdk

def androidabis(abis: List[str]) -> None:
    if _currentProject:
        _currentProject.androidAbis = abis

def androidproguard(enable: bool = True) -> None:
    if _currentProject:
        _currentProject.androidProguard = enable

def androidproguardrules(rules: List[str]) -> None:
    if _currentProject:
        if not hasattr(_currentProject, 'androidProguardRules'):
            _currentProject.androidProguardRules = []
        _currentProject.androidProguardRules.extend(rules)

def androidassets(patterns: List[str]) -> None:
    if _currentProject:
        if not hasattr(_currentProject, 'androidAssets'):
            _currentProject.androidAssets = []
        _currentProject.androidAssets.extend(patterns)

def androidisgame(enable: bool = True) -> None:
    """Marque l'application comme un jeu Android.

    Active dans le manifest :
      - android:isGame="true"            (API < 26, deprecated mais reconnu)
      - android:appCategory="game"       (API 26+, valeur officielle)

    Effets cote OS :
      - Apparition dans le Game Dashboard (Android 12+)
      - Enregistrement d'ecran via le Dashboard, capture audio
      - Categorisation correcte sur le Play Store
      - Optimisations CPU/GPU specifiques jeu (selon le constructeur)

    Si la fonction n'est PAS appelee, l'application est traitee comme une
    app normale (default).
    """
    if _currentProject:
        _currentProject.androidIsGame = bool(enable)

def androidpermissions(perms: List[str]) -> None:
    if _currentProject:
        if not hasattr(_currentProject, 'androidPermissions'):
            _currentProject.androidPermissions = []
        _currentProject.androidPermissions.extend(perms)

def androidstl(stl: str = "c++_static") -> None:
    """Set the Android C++ STL type: 'c++_static' (default) or 'c++_shared'."""
    if _currentProject:
        _currentProject.androidStl = stl

def androidnativeactivity(enable: bool = True) -> None:
    if _currentProject:
        _currentProject.androidNativeActivity = enable

def androidallowrotation(enable: bool = True) -> None:
    if _currentProject:
        _currentProject.androidAllowRotation = enable

def androidscreenorientation(value: str) -> None:
    if not _currentProject:
        return
    val = (value or "").strip()
    allowed = {
        "",
        "unspecified",
        "behind",
        "landscape",
        "portrait",
        "reverseLandscape",
        "reversePortrait",
        "sensorLandscape",
        "sensorPortrait",
        "userLandscape",
        "userPortrait",
        "sensor",
        "fullSensor",
        "nosensor",
        "user",
        "fullUser",
        "locked",
    }
    if val not in allowed:
        raise ValueError(
            f"Invalid Android screenOrientation '{value}'. "
            f"Allowed values: {sorted(allowed)}"
        )
    _currentProject.androidScreenOrientation = val

def ndkversion(ver: str) -> None:
    if _currentProject:
        _currentProject.ndkVersion = ver

def androidsign(enable: bool = True) -> None:
    if _currentProject:
        _currentProject.androidSign = enable

def androidkeystore(path: str) -> None:
    if _currentProject:
        _currentProject.androidKeystore = path

def androidkeystorepass(pwd: str) -> None:
    if _currentProject:
        _currentProject.androidKeystorePass = pwd

def androidkeyalias(alias: str) -> None:
    if _currentProject:
        _currentProject.androidKeyAlias = alias

def androidjavafiles(patterns: List[str]) -> None:
    """Définit les patterns des fichiers sources Java."""
    if _currentProject:
        if not hasattr(_currentProject, 'androidJavaFiles'):
            _currentProject.androidJavaFiles = []
        _currentProject.androidJavaFiles.extend(patterns)

def androidjavalibs(patterns: List[str]) -> None:
    """Définit les patterns des bibliothèques Java (.jar)."""
    if _currentProject:
        if not hasattr(_currentProject, 'androidJavaLibs'):
            _currentProject.androidJavaLibs = []
        _currentProject.androidJavaLibs.extend(patterns)

# --- Emscripten specific ---
def emscriptenshellfile(path: str) -> None:
    """Set custom HTML template (shell file) for Emscripten output."""
    if _currentProject:
        _currentProject.emscriptenShellFile = path

def emscriptenfullscreenshell(enable: bool = True) -> None:
    """
    Enable/disable fullscreen Emscripten shell template (`emscripten_fullscreen.html`).
    Default workspace behavior is enabled.

    Scope:
      - inside `workspace`: default applied to all Emscripten projects
      - inside `project`: override for current project only
    """
    if _currentProject:
        _currentProject.emscriptenUseFullscreenShell = bool(enable)
    elif _currentWorkspace:
        _currentWorkspace.emscriptenDefaultFullscreenShell = bool(enable)

def emscriptencanvasid(canvas_id: str) -> None:
    """Set HTML canvas element ID."""
    if _currentProject:
        _currentProject.emscriptenCanvasId = canvas_id

def emscripteninitialmemory(mb: int) -> None:
    """Set initial memory size in MB."""
    if _currentProject:
        _currentProject.emscriptenInitialMemory = mb

def emscriptenstacksize(mb: int) -> None:
    """Set stack size in MB."""
    if _currentProject:
        _currentProject.emscriptenStackSize = mb

def emscriptenexportname(name: str) -> None:
    """Set global export name for the Module."""
    if _currentProject:
        _currentProject.emscriptenExportName = name

def emscriptenextraflags(flags: List[str]) -> None:
    """Add extra emcc compiler/linker flags."""
    if _currentProject:
        if not hasattr(_currentProject, 'emscriptenExtraFlags'):
            _currentProject.emscriptenExtraFlags = []
        _currentProject.emscriptenExtraFlags.extend(flags)

# --- iOS specific (extended) ---
def iosbundleid(bid: str) -> None:
    if _currentProject:
        _currentProject.iosBundleId = bid

def iosversion(ver: str) -> None:
    if _currentProject:
        _currentProject.iosVersion = ver

def iosminsdk(sdk: str) -> None:
    if _currentProject:
        _currentProject.iosMinSdk = sdk

def iossigningidentity(identity: str) -> None:
    """Set the code signing identity for iOS builds (e.g. 'Apple Development: ...')."""
    if _currentProject:
        _currentProject.iosSigningIdentity = identity

def iosentitlements(path: str) -> None:
    """Set the path to the .entitlements file for iOS code signing."""
    if _currentProject:
        _currentProject.iosEntitlements = path

def iosappicon(icon: str) -> None:
    """Set the path to the app icon file (PNG, ICNS) for iOS bundles."""
    if _currentProject:
        _currentProject.iosAppIcon = icon


# ─────────────────────────────────────────────────────────────────────────────
# Cross-platform app icon API
# ─────────────────────────────────────────────────────────────────────────────
# Pattern :
#   - appicon(path) est l'API "single source" : un PNG/JPG est convertit en
#     interne par jenga (via Core/IconConverter.py) vers tous les formats
#     natifs requis (.ico Windows, .icns macOS, hierarchie mipmap-* Android,
#     favicon set Web). Si le fichier passe n'est PAS universel (.ico, .icns,
#     mipmap-*/), seule la plateforme compatible l'utilisera.
#   - androidappicon / windowsicon / macosicon / iosappicon / webfavicon sont
#     des overrides : ils gagnent sur appicon().
# Voir Core/IconConverter.py::ResolveIconFor pour la logique de dispatch.
# ─────────────────────────────────────────────────────────────────────────────
def appicon(icon: str) -> None:
    """Set a single app icon dispatched to ALL platforms (PNG/JPG recommended).
    Native formats (.ico/.icns/mipmap-*) are applied only to their target
    platform. Per-platform overrides (androidappicon, windowsicon, ...) win."""
    if _currentProject:
        _currentProject.appIcon = icon


def androidappicon(icon: str) -> None:
    """Override Android-specific app icon. Accepts PNG (auto mipmap generation)
    or a res/mipmap-*/ directory tree (copied as-is). Wins over appicon()."""
    if _currentProject:
        _currentProject.androidAppIcon = icon


def windowsicon(icon: str) -> None:
    """Override Windows-specific app icon. Accepts PNG (converted to .ico)
    or an .ico file (linked directly). Wins over appicon()."""
    if _currentProject:
        _currentProject.windowsIcon = icon


def macosicon(icon: str) -> None:
    """Override macOS-specific app icon. Accepts PNG (converted to .icns) or
    .icns file (copied as-is). Wins over appicon()."""
    if _currentProject:
        _currentProject.macosIcon = icon


def webfavicon(icon: str) -> None:
    """Override Emscripten/Web favicon. Accepts PNG (favicon.ico + sizes set
    are generated). Wins over appicon()."""
    if _currentProject:
        _currentProject.webFavicon = icon


# ─────────────────────────────────────────────────────────────────────────────
# Installer packaging DSL (consomme par `jenga package` MSI/EXE/DEB/PKG)
# ─────────────────────────────────────────────────────────────────────────────
def licensefile(path: str) -> None:
    """Definit le fichier de licence (LICENSE/EULA) affiche pendant
    l'installation. Formats : .txt, .md, .rtf. Si .txt ou .md, jenga
    convertit automatiquement en RTF minimal pour WiX/MSI."""
    if _currentProject:
        _currentProject.licenseFile = str(path or "").strip()


def createdesktopshortcut(enable: bool = True) -> None:
    """Active/desactive la creation d'un raccourci bureau lors de
    l'installation (MSI + Inno EXE). True par defaut, l'user peut decocher
    pendant l'install."""
    if _currentProject:
        _currentProject.createDesktopShortcut = bool(enable)


def apppublisher(name: str) -> None:
    """Nom du publisher/editeur de l'application (affiche dans 'Programs and
    Features' Windows + Info Inno + control panel macOS)."""
    if _currentProject:
        _currentProject.appPublisher = str(name or "").strip()


def appversion(version: str) -> None:
    """Version semver de l'application (ex: '1.2.3'). Utilise dans
    AppVersion (Inno), Version (MSI), CFBundleShortVersionString (macOS/iOS).
    Si vide, fallback sur iosVersion puis '1.0.0'."""
    if _currentProject:
        _currentProject.appVersion = str(version or "").strip()


# ─────────────────────────────────────────────────────────────────────────────
# Signature de code de l'installateur self-extracting (--type jng).
# Sans certificat -> l'installateur est produit mais non signe (warning).
# Levier decisif contre les alertes SmartScreen et les faux positifs antivirus.
# ─────────────────────────────────────────────────────────────────────────────
def signingcertificate(path: str) -> None:
    """Windows : certificat de signature de code (.pfx). Combine avec
    signingpassword() si protege. Ex : signingcertificate('keys/rihen.pfx')."""
    if _currentProject:
        _currentProject.signCertificate = str(path or "").strip()


def signingpassword(password: str) -> None:
    """Mot de passe du certificat .pfx (Windows). Evite de hardcoder : lis
    plutot une variable d'env via os.environ dans le .jenga."""
    if _currentProject:
        _currentProject.signPassword = str(password or "")


def signingthumbprint(thumbprint: str) -> None:
    """Windows : empreinte SHA-1 du certificat dans le magasin (CurrentUser\\My).
    Alternative a signingcertificate() quand le cert est deja installe."""
    if _currentProject:
        _currentProject.signThumbprint = str(thumbprint or "").strip()


def signingidentity(identity: str) -> None:
    """macOS : identite codesign (ex : 'Developer ID Application: Rihen (TEAMID)').
    Sans identite, l'installateur macOS reste non signe."""
    if _currentProject:
        _currentProject.signIdentity = str(identity or "").strip()


def signingtimestampurl(url: str) -> None:
    """Windows : URL du serveur de timestamp Authenticode
    (defaut : http://timestamp.digicert.com). Le timestamp garantit la
    validite de la signature apres expiration du certificat."""
    if _currentProject:
        _currentProject.signTimestampUrl = str(url or "").strip()


def signinggpgkey(keyId: str) -> None:
    """Linux : empreinte/ID de la cle GPG pour produire une signature detachee
    `<installateur>.sig`. Utile pour les depots verifiables."""
    if _currentProject:
        _currentProject.signGpgKey = str(keyId or "").strip()


def signingentitlements(path: str) -> None:
    """macOS : fichier d'entitlements (.plist) passe a codesign. Necessaire pour
    certains droits (App Sandbox, Hardened Runtime exceptions)."""
    if _currentProject:
        _currentProject.signEntitlements = str(path or "").strip()


def signingrequireadmin(value: bool = True) -> None:
    """Windows : force le manifeste UAC `requireAdministrator` au lieu du defaut
    intelligent (asInvoker, sauf si une regle de pare-feu est embarquee).
    Anti-faux-positifs AV : laisse `asInvoker` quand l'admin n'est pas requis."""
    if _currentProject:
        _currentProject.signRequireAdmin = bool(value)


def installeroption(key: str, value) -> None:
    """
    API extensible pour les options installer avancees. Permet d'ajouter
    n'importe quelle cle de configuration sans elargir l'API jenga officielle.

    Exemples d'utilisation futures :
        installeroption("autostart_on_login", True)
        installeroption("registry_entry", "HKLM\\\\Software\\\\Pong")
        installeroption("custom_branding_image", "branding.bmp")
        installeroption("autoupdate_url", "https://updates.example.com")
        installeroption("require_admin", True)
        installeroption("install_for_all_users", False)

    Chaque builder (MSI WiX, Inno EXE, DEB, PKG) lit les options qu'il
    reconnait et logue un warning + skip pour les autres. Si une option
    devient frequente, elle peut etre promue en fonction DSL dediee.
    """
    if _currentProject:
        _currentProject.installerOptions[str(key)] = value


# ─────────────────────────────────────────────────────────────────────────────
# Network / Firewall DSL — installer-time
# ─────────────────────────────────────────────────────────────────────────────
# Le bloc ci-dessous configure les permissions reseau ajoutees AU MOMENT DE
# L'INSTALLATION (pas au runtime). Couvre Windows (netsh advfirewall via WiX 3,
# WiX 4 et Inno Setup), macOS (socketfilterfw), Linux DEB (ufw/firewall-cmd/
# iptables fallback), Android (uses-permission INTERNET) et iOS (Info.plist :
# NSLocalNetworkUsageDescription, NSBonjourServices, NSAppTransportSecurity).
#
# Usage minimal — autorise les connexions LAN entrantes :
#     with project("MyGame"):
#         consoleapp()
#         networkenabled(True)   # une regle par defaut sur l'exe est creee
#
# Usage avance — regles specifiques :
#     with project("MyServer"):
#         consoleapp()
#         networkenabled(True)
#         firewallrule(name="MyServer TCP", protocol="tcp", ports=["7777"])
#         firewallrule(name="MyServer UDP discovery", protocol="udp",
#                      ports=["5353"], profiles=["private", "public"])
#         networkusagedescription("MyServer a besoin du LAN pour la decouverte "
#                                 "de pairs.")
#         bonjourservices(["_myserver._tcp"])
#         iosallowarbitraryloads(True)  # iOS HTTP sans TLS pour LAN
def networkenabled(enable: bool = True) -> None:
    """Active les permissions reseau / regles firewall a l'installation.

    True par defaut cree une regle "in/allow/any" sur l'exe pour les 3 profils
    Windows. Sur Android, injecte automatiquement android.permission.INTERNET
    et android.permission.ACCESS_NETWORK_STATE si pas deja declarees. Sur iOS,
    declenche l'injection de NSLocalNetworkUsageDescription dans Info.plist."""
    if _currentProject:
        _currentProject.networkEnabled = bool(enable)


def firewallrule(name:            str       = "",
                 direction:       str       = "in",
                 action:          str       = "allow",
                 protocol:        str       = "any",
                 ports:           Optional[List[str]] = None,
                 profiles:        Optional[List[str]] = None,
                 programOverride: str       = "") -> None:
    """Declare une regle de pare-feu personnalisee creee par l'installer.

    Si au moins un firewallrule() est declare, networkEnabled est implicitement
    active. Les regles personnalisees REMPLACENT la regle par defaut "tout
    autoriser" — pour la garder en plus, declare-la explicitement.

    Parametres :
      name      : nom visible (ex "MyGame TCP"). Vide -> auto "{AppName} (Network)"
      direction : "in" | "out" | "both"
      action    : "allow" | "block"
      protocol  : "any" | "tcp" | "udp"
      ports     : liste ["7777", "8000-8100"]. Vide = tous.
      profiles  : Windows-only, sous-ensemble de {"any","domain","private","public"}
      programOverride : autre exe que celui du projet (rare)
    """
    if not _currentProject:
        return
    rule = FirewallRule(
        name            = str(name or "").strip(),
        direction       = str(direction or "in").strip().lower(),
        action          = str(action or "allow").strip().lower(),
        protocol        = str(protocol or "any").strip().lower(),
        ports           = [str(p) for p in (ports or [])],
        profiles        = [str(p).strip().lower() for p in (profiles or ["any"])],
        programOverride = str(programOverride or "").strip(),
    )
    # Validation defensive : evite que l'user passe des valeurs aberrantes qui
    # produiraient un netsh / socketfilterfw invalide.
    if rule.direction not in ("in", "out", "both"):
        raise ValueError(f"firewallrule(direction) invalide: {rule.direction!r}")
    if rule.action not in ("allow", "block"):
        raise ValueError(f"firewallrule(action) invalide: {rule.action!r}")
    if rule.protocol not in ("any", "tcp", "udp"):
        raise ValueError(f"firewallrule(protocol) invalide: {rule.protocol!r}")
    _currentProject.firewallRules.append(rule)
    # Declarer au moins une regle implique vouloir le reseau active.
    _currentProject.networkEnabled = True


def networkusagedescription(text: str) -> None:
    """Phrase expliquant pourquoi l'app a besoin du reseau local.

    Affichee a l'utilisateur sur iOS (NSLocalNetworkUsageDescription, requis
    pour Bonjour/mDNS) et sur macOS si le firewall demande confirmation."""
    if _currentProject:
        _currentProject.networkUsageDescription = str(text or "").strip()


def bonjourservices(services: List[str]) -> None:
    """Liste des services Bonjour/mDNS publies/decouverts par l'app.

    Ex: ["_http._tcp", "_mygame._udp"]. Injecte dans NSBonjourServices
    (Info.plist iOS) + ouverture port 5353/udp sur macOS si firewall actif."""
    if not _currentProject:
        return
    _currentProject.bonjourServices = [str(s).strip() for s in (services or []) if s]


def iosallowarbitraryloads(enable: bool = True) -> None:
    """Autorise les requetes HTTP non-TLS sur iOS (LAN/IoT sans certificat).

    Ajoute NSAppTransportSecurity > NSAllowsArbitraryLoads dans Info.plist.
    NB: l'App Store peut demander une justification a la review."""
    if _currentProject:
        _currentProject.allowArbitraryLoads = bool(enable)


def iosbuildnumber(number: Union[str, int]) -> None:
    """Set the build number (CFBundleVersion) for iOS bundles."""
    if _currentProject:
        _currentProject.iosBuildNumber = str(number)

def iosbuildsystem(mode: str) -> None:
    """Select Apple mobile build backend: 1/direct or 2/xcode/xbuilder."""
    if not _currentProject:
        return
    value = str(mode or "").strip().lower()
    if value in ("2", "xcode", "xbuilder"):
        _currentProject.iosBuildSystem = "xcode"
    elif value in ("1", "direct"):
        _currentProject.iosBuildSystem = "direct"
    else:
        raise ValueError("iosbuildsystem(mode) expects: 1/direct or 2/xcode/xbuilder")

def iosdistributiontype(kind: str) -> None:
    """Set iOS distribution type: development, app-store, ad-hoc, enterprise."""
    if not _currentProject:
        return
    value = str(kind or "").strip().lower()
    if value not in ("development", "app-store", "ad-hoc", "enterprise"):
        raise ValueError("iosdistributiontype(kind) expects: development, app-store, ad-hoc, enterprise")
    _currentProject.iosDistributionType = value

def iosteamid(team_id: str) -> None:
    """Set Apple Team ID used for xcode export options."""
    if _currentProject:
        _currentProject.iosTeamId = str(team_id or "").strip()

def iosprovisioningprofile(profile: str) -> None:
    """Set provisioning profile specifier used for xcode export options."""
    if _currentProject:
        _currentProject.iosProvisioningProfile = str(profile or "").strip()

def iosresources(patterns: List[str]) -> None:
    """Définit les ressources à copier dans le bundle iOS."""
    if _currentProject:
        if not hasattr(_currentProject, 'iosResources'):
            _currentProject.iosResources = []
        _currentProject.iosResources.extend(patterns)

def iosminsdk(sdk: str) -> None:
    """Définit la version minimale iOS (ex: '13.0')."""
    if _currentProject:
        _currentProject.iosMinSdk = sdk

def tvosminsdk(sdk: str) -> None:
    """Définit la version minimale tvOS (ex: '13.0')."""
    if _currentProject:
        _currentProject.tvosMinSdk = sdk

def watchosminsdk(sdk: str) -> None:
    """Définit la version minimale watchOS (ex: '7.0')."""
    if _currentProject:
        _currentProject.watchosMinSdk = sdk

def ipadosminsdk(sdk: str) -> None:
    if _currentProject:
        _currentProject.ipadosMinSdk = sdk

def visionosminsdk(sdk: str) -> None:
    if _currentProject:
        _currentProject.visionosMinSdk = sdk


def harmonyminsdk(api_level: int) -> None:
    """Set the minimum HarmonyOS API level (e.g. 9 for HarmonyOS 4.0)."""
    if _currentProject:
        _currentProject.harmonyMinSdk = str(api_level)


def harmonysdk(path: str) -> None:
    """Set the HarmonyOS SDK path for this workspace."""
    if _currentWorkspace:
        _currentWorkspace.harmonySdkPath = str(path or "").strip()

def harmonybundlename(name: str) -> None:
    """Set HarmonyOS bundle name (ex: com.nkentseu.game)."""
    if _currentProject:
        _currentProject.harmonyBundleName = str(name or "").strip()

def harmonyversioncode(code: int) -> None:
    if _currentProject:
        _currentProject.harmonyVersionCode = int(code)

def harmonyversionname(name: str) -> None:
    if _currentProject:
        _currentProject.harmonyVersionName = str(name or "").strip()

def harmonytargetapi(api: int) -> None:
    if _currentProject:
        _currentProject.harmonyTargetApi = int(api)

def harmonysign(enable: bool = True) -> None:
    if _currentProject:
        _currentProject.harmonySign = bool(enable)

def harmonycertfile(path: str) -> None:
    if _currentProject:
        _currentProject.harmonyCertFile = str(path or "").strip()

def harmonyprofile(path: str) -> None:
    if _currentProject:
        _currentProject.harmonyProfile = str(path or "").strip()

def harmonykeystore(path: str) -> None:
    if _currentProject:
        _currentProject.harmonyKeystore = str(path or "").strip()

def harmonykeyalias(alias: str) -> None:
    if _currentProject:
        _currentProject.harmonyKeyAlias = str(alias or "").strip()

def harmonykeypwd(pwd: str) -> None:
    if _currentProject:
        _currentProject.harmonyKeyPwd = str(pwd or "").strip()

def harmonyappicon(path: str) -> None:
    if _currentProject:
        _currentProject.harmonyAppIcon = str(path or "").strip()

def harmonyresources(dirs: List[str]) -> None:
    """Dossiers de ressources HarmonyOS à inclure dans le HAP.
    
    Copiés dans entry/src/main/resources/ de la structure de build.
    Équivalent de androidresDirs() pour Android.
    
    Structure attendue dans chaque dossier :
      base/element/string.json
      base/element/color.json  
      base/media/icon.png
      base/profile/main_pages.json
      en_US/element/string.json  (i18n)
    """
    if _currentProject:
        if not hasattr(_currentProject, 'harmonyResDirs'):
            _currentProject.harmonyResDirs = []
        _currentProject.harmonyResDirs.extend(dirs)

def harmonyassets(dirs: List[str]) -> None:
    """Assets HarmonyOS (fichiers bruts) copiés dans entry/src/main/resources/rawfile/.

    Équivalent de androidassets() pour Android.
    Accessibles via $rawfile('filename') dans ArkTS.
    """
    if _currentProject:
        if not hasattr(_currentProject, 'harmonyAssets'):
            _currentProject.harmonyAssets = []
        _currentProject.harmonyAssets.extend(dirs)


def harmonypermissions(perms: List[str]) -> None:
    """Permissions HarmonyOS (ohos.permission.*) injectees dans module.json5 >
    requestPermissions.

    Equivalent de androidpermissions() pour HarmonyOS. Fusionne avec les
    permissions reseau auto-injectees si networkenabled(True) est actif
    (ohos.permission.INTERNET, GET_NETWORK_INFO, GET_WIFI_INFO).

    Exemple :
        harmonypermissions(["ohos.permission.CAMERA",
                            "ohos.permission.MICROPHONE"])
    """
    if _currentProject:
        if not hasattr(_currentProject, 'harmonyPermissions'):
            _currentProject.harmonyPermissions = []
        _currentProject.harmonyPermissions.extend(perms)


def harmonyets(dirs: List[str]) -> None:
    """Repertoires de sources ArkTS/ETS (.ets) a copier dans le HAP.

    Copies dans entry/src/main/ets/ de la structure de build. Si non declare,
    le builder utilise les .ets trouves via files() ou l'auto-detection.

    Exemple :
        harmonyets(["ets/", "ui/pages/"])
    """
    if _currentProject:
        if not hasattr(_currentProject, 'harmonyEtsDirs'):
            _currentProject.harmonyEtsDirs = []
        _currentProject.harmonyEtsDirs.extend(dirs)


def gdkpath(path: str) -> None:
    """Set the Microsoft GDK root path (workspace-level)."""
    if _currentWorkspace:
        _currentWorkspace.gdkPath = str(path or "").strip()


def xboxmode(mode: str) -> None:
    """Set Xbox build mode: 'gdk' (default) or 'uwp'."""
    if not _currentWorkspace:
        return
    value = str(mode or "").strip().lower()
    if value not in ("gdk", "uwp"):
        raise ValueError("xboxmode(mode) expects: 'gdk' or 'uwp'")
    _currentWorkspace.xboxMode = value


def xboxplatform(platform_name: str) -> None:
    """Set Xbox platform flavor: XboxOne, Scarlett, Desktop or UWP."""
    if not _currentWorkspace:
        return
    raw = str(platform_name or "").strip()
    key = raw.lower().replace(" ", "").replace("-", "").replace("_", "")
    mapping = {
        "xboxone": "XboxOne",
        "xbone": "XboxOne",
        "xboxseries": "Scarlett",
        "scarlett": "Scarlett",
        "xbox": "Scarlett",
        "desktop": "Desktop",
        "pc": "Desktop",
        "uwp": "UWP",
        "xboxuwp": "UWP",
    }
    _currentWorkspace.xboxPlatform = mapping.get(key, raw)


def xboxsigningmode(mode: str) -> None:
    """Set Xbox package signing mode: test, random, stable."""
    if not _currentProject:
        return
    value = str(mode or "").strip().lower()
    if value not in ("test", "random", "stable"):
        raise ValueError("xboxsigningmode(mode) expects: test, random or stable")
    _currentProject.xboxSigningMode = value


def xboxpackagename(name: str) -> None:
    """Set Xbox package identity name."""
    if _currentProject:
        _currentProject.xboxPackageName = str(name or "").strip()


def xboxpublisher(name: str) -> None:
    """Set Xbox package publisher."""
    if _currentProject:
        _currentProject.xboxPublisher = str(name or "").strip()


def xboxversion(version: str) -> None:
    """Set Xbox package version (e.g. 1.0.0.0)."""
    if _currentProject:
        _currentProject.xboxVersion = str(version or "").strip()


def xboxlekbpath(path: str) -> None:
    """Set Xbox LEKB path for stable signing mode."""
    if _currentProject:
        _currentProject.xboxLEKBPath = str(path or "").strip()


def xboxassetchunks(patterns: List[str]) -> None:
    """Set additional Xbox asset chunk patterns for packaging."""
    if _currentProject:
        _currentProject.xboxAssetChunks = list(patterns or [])

# --- Test settings (only inside test context) ---
def testoptions(opts: List[str]) -> None:
    if _currentProject and _currentProject.isTest:
        _currentProject.testOptions.extend(opts)

def testfiles(patterns: List[str]) -> None:
    if _currentProject and _currentProject.isTest:
        if _currentFilter:
            # Respect the enclosing filter so test files are only compiled on matching platforms.
            _AppendFilteredValues(_currentProject._filteredFiles, _currentFilter, patterns)
        else:
            _currentProject.testFiles.extend(patterns)

def testmainfile(mainfile: str) -> None:
    if _currentProject and _currentProject.isTest:
        _currentProject.testMainFile = mainfile

def testmaintemplate(tmpl: str) -> None:
    if _currentProject and _currentProject.isTest:
        _currentProject.testMainTemplate = tmpl

# --- Toolchain advanced functions ---

# ============================================================================
# 1. DÉTECTION AUTOMATIQUE DE LA PLATEFORME HÔTE
# ============================================================================

def _GetHostPlatform() -> str:
    """Detect the current host platform."""
    import platform
    system = platform.system().lower()
    if system == "windows":
        return "Windows"
    elif system == "linux":
        return "Linux"
    elif system == "darwin":
        return "macOS"
    else:
        return "Windows"  # fallback


def _GetHostArch() -> str:
    """Detect the current host architecture."""
    import platform
    machine = platform.machine().lower()
    
    # Normaliser les noms d'architectures
    if machine in ("x86_64", "amd64", "x64"):
        return "x86_64"
    elif machine in ("i386", "i686", "x86"):
        return "x86"
    elif machine in ("aarch64", "arm64"):
        return "arm64"
    elif machine.startswith("arm"):
        return "arm"
    else:
        return "x86_64"  # fallback moderne
    
    
# ============================================================================
# 2. NORMALISATION DES NOMS D'ARCHITECTURES (ALIASES)
# ============================================================================

# Dictionnaire d'aliases pour les architectures
ARCH_ALIASES = {
    # x86_64 variants
    "x64": "X86_64",
    "x86_64": "X86_64",
    "amd64": "X86_64",
    "x86-64": "X86_64",
    
    # x86 variants
    "x86": "X86",
    "i386": "X86",
    "i686": "X86",
    "ia32": "X86",
    
    # ARM64 variants
    "arm64": "ARM64",
    "aarch64": "ARM64",
    "armv8": "ARM64",
    
    # ARM32 variants
    "arm": "ARM",
    "armv7": "ARM",
    "armhf": "ARM",
    
    # WebAssembly variants
    "wasm": "WASM32",
    "wasm32": "WASM32",
    "wasm64": "WASM64",
    
    # PowerPC variants
    "ppc": "POWERPC",
    "powerpc": "POWERPC",
    "ppc64": "POWERPC64",
    "powerpc64": "POWERPC64",
    
    # MIPS variants
    "mips": "MIPS",
    "mips64": "MIPS64",
}

# Dictionnaire d'aliases pour les OS
OS_ALIASES = {
    # Windows variants
    "windows": "WINDOWS",
    "win": "WINDOWS",
    "win32": "WINDOWS",
    "win64": "WINDOWS",
    "winnt": "WINDOWS",

    # Linux variants
    "linux": "LINUX",

    # macOS variants
    "macos": "MACOS",
    "darwin": "MACOS",
    "osx": "MACOS",
    "mac": "MACOS",
    "macosx": "MACOS",
    "maccatalyst": "MACOS",
    "mac_catalyst": "MACOS",
    "catalyst": "MACOS",

    # Android variants
    "android": "ANDROID",

    # iOS variants
    "ios": "IOS",
    "iphoneos": "IOS",
    "iphonesimulator": "IOS",
    "iossimulator": "IOS",
    "ipados": "IOS",
    "ipadsimulator": "IOS",
    "visionos": "IOS",
    "xros": "IOS",
    "xrsimulator": "IOS",

    # tvOS variants
    "tvos": "TVOS",
    "appletv": "TVOS",
    "apple_tv": "TVOS",
    "appletvos": "TVOS",
    "appletvsimulator": "TVOS",

    # watchOS variants
    "watchos": "WATCHOS",
    "applewatch": "WATCHOS",
    "apple_watch": "WATCHOS",
    "watchsimulator": "WATCHOS",

    # Web variants
    "web": "WEB",
    "wasm": "WEB",
    "emscripten": "WEB",

    # Console variants
    "ps4": "PS4",
    "playstation4": "PS4",

    "ps5": "PS5",
    "playstation5": "PS5",

    "xbox": "XBOX_SERIES",
    "xboxone": "XBOX_ONE",
    "xbox_one": "XBOX_ONE",
    "xbone": "XBOX_ONE",

    "xboxseries": "XBOX_SERIES",
    "xbox_series": "XBOX_SERIES",
    "xsx": "XBOX_SERIES",
    "xss": "XBOX_SERIES",
    "xboxuwp": "XBOX_SERIES",
    "xbox_uwp": "XBOX_SERIES",

    "switch": "SWITCH",
    "nintendoswitch": "SWITCH",
    "nintendo_switch": "SWITCH",

    # Other OS
    "harmonyos": "HARMONYOS",
    "harmony": "HARMONYOS",

    "freebsd": "FREEBSD",
    "openbsd": "OPENBSD",
}

# Dictionnaire d'aliases pour les environnements
ENV_ALIASES = {
    "gnu": "GNU",
    "glibc": "GNU",
    
    "musl": "MUSL",
    
    "msvc": "MSVC",
    "microsoft": "MSVC",
    
    "mingw": "MINGW",
    "mingw32": "MINGW",
    "mingw64": "MINGW",
    
    "android": "ANDROID",
    
    "ios": "IOS",
}


# ============================================================================
# 3. FONCTION DE NORMALISATION
# ============================================================================

def _NormalizeArchName(arch: str) -> str:
    """
    Normalise le nom d'une architecture en gérant les aliases.
    
    Args:
        arch: Nom de l'architecture (peut être en minuscule, majuscule, avec alias)
    
    Returns:
        Nom normalisé de l'architecture (UPPER_SNAKE_CASE)
    
    Examples:
        _NormalizeArchName("x64") -> "X86_64"
        _NormalizeArchName("amd64") -> "X86_64"
        _NormalizeArchName("ARM64") -> "ARM64"
    """
    arch_lower = arch.lower().replace("-", "_").replace(" ", "")
    
    # Vérifier les aliases
    if arch_lower in ARCH_ALIASES:
        return ARCH_ALIASES[arch_lower]
    
    # Sinon, convertir en majuscules
    return arch.upper().replace("-", "_")


def _NormalizeOSName(os_name: str) -> str:
    """
    Normalise le nom d'un OS en gérant les aliases.
    
    Args:
        os_name: Nom de l'OS (peut être en minuscule, majuscule, avec alias)
    
    Returns:
        Nom normalisé de l'OS (UPPER_SNAKE_CASE)
    
    Examples:
        _NormalizeOSName("windows") -> "WINDOWS"
        _NormalizeOSName("darwin") -> "MACOS"
        _NormalizeOSName("Win64") -> "WINDOWS"
    """
    os_lower = os_name.lower().replace("-", "_").replace(" ", "")
    
    # Vérifier les aliases
    if os_lower in OS_ALIASES:
        return OS_ALIASES[os_lower]
    
    # Sinon, convertir en majuscules
    return os_name.upper().replace("-", "_")


def _NormalizeEnvName(env_name: str) -> str:
    """
    Normalise le nom d'un environnement en gérant les aliases.
    
    Args:
        env_name: Nom de l'environnement
    
    Returns:
        Nom normalisé de l'environnement (UPPER_SNAKE_CASE)
    """
    env_lower = env_name.lower().replace("-", "_").replace(" ", "")
    
    # Vérifier les aliases
    if env_lower in ENV_ALIASES:
        return ENV_ALIASES[env_lower]
    
    # Sinon, convertir en minuscules (les env sont en lowercase dans l'enum)
    return env_name.lower()


# ============================================================================
# 6. AMÉLIORATION DE setTarget() dans Toolchain
# ============================================================================

def setTarget_improved(self, os, arch, env=None):
    """
    Version améliorée de setTarget() avec normalisation.
    
    À utiliser dans la classe Toolchain.
    """
    # Normaliser OS
    if isinstance(os, str):
        os_normalized = _NormalizeOSName(os)
        try:
            os = TargetOS[os_normalized]
        except KeyError:
            raise ValueError(f"Unknown OS: '{os}' (normalized to '{os_normalized}')")
    
    # Normaliser Architecture
    if isinstance(arch, str):
        arch_normalized = _NormalizeArchName(arch)
        try:
            arch = TargetArch[arch_normalized]
        except KeyError:
            raise ValueError(f"Unknown architecture: '{arch}' (normalized to '{arch_normalized}')")
    
    # Normaliser Environnement
    if env and isinstance(env, str):
        env_normalized = _NormalizeEnvName(env)
        try:
            env = TargetEnv[env_normalized.upper()]
        except KeyError:
            raise ValueError(f"Unknown environment: '{env}' (normalized to '{env_normalized}')")
    
    self.targetOs = os
    self.targetArch = arch
    self.targetEnv = env


def settarget(os, arch, env=None):
    """
    Version améliorée de settarget() avec normalisation.
    
    Examples:
        settarget("linux", "x64")           # Fonctionne
        settarget("WINDOWS", "amd64")       # Fonctionne
        settarget("Darwin", "arm64", "gnu") # Fonctionne
    """
    if _currentToolchain:
        # Utiliser la version améliorée
        setTarget_improved(_currentToolchain, os, arch, env)

def sysroot(path: str) -> None:
    if _currentToolchain:
        _currentToolchain.sysroot = path

def targettriple(triple: str) -> None:
    if _currentToolchain:
        _currentToolchain.targetTriple = triple

def ccompiler(path: str) -> None:
    if _currentToolchain:
        _currentToolchain.ccPath = path

def cppcompiler(path: str) -> None:
    if _currentToolchain:
        _currentToolchain.cxxPath = path

def linker(path: str) -> None:
    if _currentToolchain:
        _currentToolchain.ldPath = path

def archiver(path: str) -> None:
    if _currentToolchain:
        _currentToolchain.arPath = path

def addcflag(flag: str) -> None:
    if _currentToolchain:
        _currentToolchain.cflags.append(flag)

def addcxxflag(flag: str) -> None:
    if _currentToolchain:
        _currentToolchain.cxxflags.append(flag)

def addldflag(flag: str) -> None:
    if _currentToolchain:
        _currentToolchain.ldflags.append(flag)

def cflags(flags: List[str]) -> None:
    if _currentProject:
        if _currentFilter:
            _AppendFilteredValues(_currentProject._filteredCFlags, _currentFilter, flags)
        else:
            _currentProject.cflags.extend(flags)
    elif _currentToolchain:
        _currentToolchain.cflags.extend(flags)

def cxxflags(flags: List[str]) -> None:
    if _currentProject:
        if _currentFilter:
            _AppendFilteredValues(_currentProject._filteredCxxFlags, _currentFilter, flags)
        else:
            _currentProject.cxxflags.extend(flags)
    elif _currentToolchain:
        _currentToolchain.cxxflags.extend(flags)

def ldflags(flags: List[str]) -> None:
    if _currentProject:
        if _currentFilter:
            _AppendFilteredValues(_currentProject._filteredLdFlags, _currentFilter, flags)
        else:
            _currentProject.ldflags.extend(flags)
    elif _currentToolchain:
        _currentToolchain.ldflags.extend(flags)

def asmflags(flags: List[str]) -> None:
    if _currentToolchain:
        _currentToolchain.asmflags.extend(flags)

def arflags(flags: List[str]) -> None:
    if _currentToolchain:
        _currentToolchain.arflags.extend(flags)

def frameworks(names: Union[str, List[str]]) -> None:
    """Add one or more frameworks (macOS/iOS). Can accept single name or list."""
    if not _currentToolchain:
        return
    if isinstance(names, str):
        _currentToolchain.frameworks.append(names)
    else:
        _currentToolchain.frameworks.extend(names)

def framework(name: str) -> None:
    """Backward-compatible singular alias for frameworks()."""
    frameworks(name)

def frameworkpath(path: str) -> None:
    if _currentToolchain:
        _currentToolchain.frameworkPaths.append(path)

def librarypath(path: str) -> None:
    if _currentToolchain:
        _currentToolchain.ldflags.append(f"-L{path}")

def library(lib: str) -> None:
    if _currentToolchain:
        _currentToolchain.ldflags.append(f"-l{lib}")

def rpath(path: str) -> None:
    if _currentToolchain:
        _currentToolchain.ldflags.append(f"-Wl,-rpath,{path}")

def sanitize(san: str) -> None:
    if _currentToolchain:
        flag = f"-fsanitize={san}"
        _currentToolchain.cflags.append(flag)
        _currentToolchain.cxxflags.append(flag)
        _currentToolchain.ldflags.append(flag)

def nostdlib() -> None:
    if _currentToolchain:
        _currentToolchain.ldflags.append("-nostdlib")

def nostdinc() -> None:
    if _currentToolchain:
        _currentToolchain.cflags.append("-nostdinc")
        _currentToolchain.cxxflags.append("-nostdinc++")

def pic() -> None:
    if _currentToolchain:
        _currentToolchain.cflags.append("-fPIC")
        _currentToolchain.cxxflags.append("-fPIC")

def pie() -> None:
    if _currentToolchain:
        _currentToolchain.ldflags.append("-pie")
        _currentToolchain.cflags.append("-fPIE")
        _currentToolchain.cxxflags.append("-fPIE")

# --- Toolchain warning/optimization helpers (private) ---
def _warningsTc(level: Union[str, WarningLevel]) -> None:
    if _currentToolchain:
        if isinstance(level, str):
            lvl = WarningLevel[level.upper()]
        else:
            lvl = level
        if lvl == WarningLevel.ALL:
            _currentToolchain.cflags.append("-Wall")
            _currentToolchain.cxxflags.append("-Wall")
        elif lvl == WarningLevel.EXTRA:
            _currentToolchain.cflags.append("-Wextra")
            _currentToolchain.cxxflags.append("-Wextra")
        elif lvl == WarningLevel.PEDANTIC:
            _currentToolchain.cflags.append("-pedantic")
            _currentToolchain.cxxflags.append("-pedantic")
        elif lvl == WarningLevel.EVERYTHING and _currentToolchain.compilerFamily in (CompilerFamily.CLANG, CompilerFamily.APPLE_CLANG):
            _currentToolchain.cxxflags.append("-Weverything")
        elif lvl == WarningLevel.ERROR:
            _currentToolchain.cflags.append("-Werror")
            _currentToolchain.cxxflags.append("-Werror")

def _optimizationTc(level: str) -> None:
    if _currentToolchain:
        lvl = level.lower()
        if lvl in ("0", "off", "none"):
            _currentToolchain.cflags.append("-O0")
            _currentToolchain.cxxflags.append("-O0")
        elif lvl in ("s", "size"):
            _currentToolchain.cflags.append("-Os")
            _currentToolchain.cxxflags.append("-Os")
        elif lvl in ("1", "fast"):
            _currentToolchain.cflags.append("-O1")
            _currentToolchain.cxxflags.append("-O1")
        elif lvl in ("2", "balanced"):
            _currentToolchain.cflags.append("-O2")
            _currentToolchain.cxxflags.append("-O2")
        elif lvl in ("3", "aggressive", "full"):
            _currentToolchain.cflags.append("-O3")
            _currentToolchain.cxxflags.append("-O3")
        elif lvl == "ofast":
            _currentToolchain.cflags.append("-Ofast")
            _currentToolchain.cxxflags.append("-Ofast")

def _debugTc(enable: bool = True) -> None:
    if _currentToolchain:
        if enable:
            _currentToolchain.cflags.append("-g")
            _currentToolchain.cxxflags.append("-g")
        else:
            _currentToolchain.cflags.append("-g0")
            _currentToolchain.cxxflags.append("-g0")

# --- Build options ---
def buildoption(option: str, values: List[str]) -> None:
    if _currentProject:
        if not hasattr(_currentProject, 'buildOptions'):
            _currentProject.buildOptions = {}
        if option not in _currentProject.buildOptions:
            _currentProject.buildOptions[option] = []
        _currentProject.buildOptions[option].extend(values)

def buildoptions(opts: Union[Dict[str, Union[str, List[str]]], List[str], Tuple[str, ...]]) -> None:
    if _currentProject:
        # Premake-style shorthand: buildoptions(["-fno-rtti", ...])
        if isinstance(opts, (list, tuple)):
            cflags(list(opts))
            cxxflags(list(opts))
            return

        if not hasattr(_currentProject, 'buildOptions'):
            _currentProject.buildOptions = {}
        for k, v in opts.items():
            if isinstance(v, list):
                _currentProject.buildOptions.setdefault(k, []).extend(v)
            else:
                _currentProject.buildOptions.setdefault(k, []).append(v)

def linkoptions(flags: List[str]) -> None:
    """Premake-compatible alias for linker options."""
    ldflags(flags)

# --- Project properties introspection (from original) ---
def useproject(projectname: str, copyincludes: bool = True, copydefines: bool = True) -> None:
    """
    Use properties from another project in current project.
    Original: useproject()
    """
    global _currentProject, _currentWorkspace
    if not _currentProject:
        raise RuntimeError("useproject must be called within a project context")
    if not _currentWorkspace:
        raise RuntimeError("No active workspace")
    if projectname not in _currentWorkspace.projects:
        raise ValueError(f"Project '{projectname}' not found in workspace")
    src = _currentWorkspace.projects[projectname]
    if copyincludes and src.includeDirs:
        _currentProject.includeDirs.extend(src.includeDirs)
    if copydefines and src.defines:
        _currentProject.defines.extend(src.defines)
    if projectname not in _currentProject.dependsOn:
        _currentProject.dependsOn.append(projectname)

def getprojectproperties(projectname: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """
    Get properties of a project (current or specified).
    Original: getpp()
    """
    global _currentWorkspace, _currentProject
    if not _currentWorkspace:
        return None
    if projectname is None:
        if _currentProject:
            proj = _currentProject
        else:
            return None
    else:
        if projectname in _currentWorkspace.projects:
            proj = _currentWorkspace.projects[projectname]
        else:
            return None
    props = {
        'name': proj.name,
        'kind': proj.kind.value,
        'language': proj.language.value,
        'location': proj.location,
        'cppdialect': proj.cppdialect,
        'cdialect': proj.cdialect,
        'files': list(proj.files),
        'excludefiles': list(proj.excludeFiles),
        'includedirs': list(proj.includeDirs),
        'libdirs': list(proj.libDirs),
        'objdir': proj.objDir,
        'targetdir': proj.targetDir,
        'targetname': proj.targetName,
        'defines': list(proj.defines),
        'optimize': proj.optimize.value,
        'symbols': proj.symbols,
        'warnings': proj.warnings.value,
        'links': list(proj.links),
        'dependson': list(proj.dependsOn),
        'toolchain': proj.toolchain,
        'istest': proj.isTest,
        'parentproject': proj.parentProject,
    }
    if proj._external:
        props.update({
            'external': True,
            'externalfile': proj._externalFile,
            'externaldir': proj._externalDir,
        })
    return props

# --- Include utilities (from original) ---
def includefromdirectory(directory: str, pattern: str = "*.jenga") -> List[str]:
    """
    Include all .jenga files from a directory.
    Original: include_from_directory()
    """
    from pathlib import Path
    dirPath = Path(directory)
    if not dirPath.is_absolute():
        if _currentWorkspace and _currentWorkspace.location:
            dirPath = Path(_currentWorkspace.location) / dirPath
    files = list(dirPath.glob(pattern))
    included = []
    for f in files:
        with include(str(f)):
            pass
        included.append(str(f))
    return included

def listincludes() -> List[Dict[str, str]]:
    """
    List all included (external) projects in current workspace.
    Original: listincludes()
    """
    global _currentWorkspace
    if not _currentWorkspace:
        return []
    result = []
    for name, proj in _currentWorkspace.projects.items():
        if proj._external:
            result.append({
                'name': name,
                'sourcefile': proj._externalFile,
                'sourcedir': proj._externalDir,
                'location': proj.location,
            })
    return result

def getincludeinfo(projectname: str) -> Optional[Dict[str, Any]]:
    """
    Get detailed information about an included project.
    Original: getincludeinfo()
    """
    global _currentWorkspace
    if not _currentWorkspace or projectname not in _currentWorkspace.projects:
        return None
    proj = _currentWorkspace.projects[projectname]
    if not proj._external:
        return None
    return {
        'name': proj.name,
        'kind': proj.kind.value,
        'language': proj.language.value,
        'location': proj.location,
        'sourcefile': proj._externalFile,
        'sourcedir': proj._externalDir,
        'standalone': proj._standalone,
    }

def validateincludes() -> None:
    """
    Validate that all included projects have valid dependencies.
    Original: validateincludes()
    """
    global _currentWorkspace
    if not _currentWorkspace:
        return
    errors = []
    for proj in _currentWorkspace.projects.values():
        for dep in proj.dependsOn:
            if dep not in _currentWorkspace.projects:
                errors.append(f"Project '{proj.name}' depends on '{dep}' which doesn't exist")
    if errors:
        raise RuntimeError("Dependency validation failed:\n" + "\n".join(f"  - {e}" for e in errors))

def lip() -> List[Dict[str, Any]]:
    """Alias for listincludes() – original naming."""
    return listincludes()

def vip() -> None:
    """Alias for validateincludes() – original naming."""
    validateincludes()

def getincludedprojects() -> Dict[str, Dict[str, Any]]:
    """
    Get all included projects as dict.
    Original: getincludedprojects()
    """
    global _currentWorkspace
    if not _currentWorkspace:
        return {}
    result = {}
    for name, proj in _currentWorkspace.projects.items():
        if proj._external:
            result[name] = {
                'file': proj._externalFile,
                'dir': proj._externalDir,
                'standalone': proj._standalone,
                'location': proj.location,
                'original_location': proj._originalLocation,
            }
    return result

def generatedependencyreport(filepath: str = "DEPENDENCIES.md") -> None:
    """
    Generate a dependency report markdown file.
    Original: generatedependencyreport()
    """
    included = getincludedprojects()
    report = "# Jenga Dependency Report\n\n"
    report += "## External Libraries\n\n"
    for name, info in included.items():
        report += f"### {name}\n"
        report += f"- **Source**: `{info['file']}`\n"
        report += f"- **Location**: `{info['location']}`\n"
        report += f"- **Type**: {'Standalone' if info['standalone'] else 'Workspace'}\n\n"
    Path(filepath).write_text(report, encoding='utf-8')

def listallprojects() -> List[Dict[str, Any]]:
    """
    List all projects in workspace with basic info.
    Original: listallprojects()
    """
    global _currentWorkspace
    if not _currentWorkspace:
        return []
    return [
        {
            'name': name,
            'kind': proj.kind.value,
            'location': proj.location,
            'external': proj._external,
            'istest': proj.isTest,
        }
        for name, proj in _currentWorkspace.projects.items()
    ]

# --- Utility functions ---
def getcurrentworkspace() -> Optional[Workspace]:
    return _currentWorkspace

def resetstate() -> None:
    global _currentWorkspace, _currentProject, _currentToolchain, _currentFilter
    _currentWorkspace = None
    _currentProject = None
    _currentToolchain = None
    _currentFilter = None

# ---------------------------------------------------------------------------
# External Tools Management (complete)
# ---------------------------------------------------------------------------

@dataclass
class ToolConfig:
    """Configuration of an external tool (compiler, SDK, NDK, etc.)"""
    name: str
    type: str                       # 'compiler', 'sdk', 'ndk', 'emscripten', 'custom'
    version: str = ""
    path: str = ""

    # Compiler specific
    cc: str = ""
    cxx: str = ""
    ar: str = ""
    ld: str = ""
    strip: str = ""
    ranlib: str = ""

    # SDK specific
    sdkPath: str = ""
    includePaths: List[str] = field(default_factory=list)
    libraryPaths: List[str] = field(default_factory=list)
    frameworks: List[str] = field(default_factory=list)

    # Environment variables
    envVars: Dict[str, str] = field(default_factory=dict)

    # Tool flags
    cflags: List[str] = field(default_factory=list)
    cxxflags: List[str] = field(default_factory=list)
    ldflags: List[str] = field(default_factory=list)

    # System configuration
    sysroot: str = ""
    targetTriple: str = ""

    # Validation
    validated: bool = False
    validationError: str = ""

    def Validate(self) -> bool:
        """Validate that the tool exists and is functional."""
        import subprocess
        if self.path and not Path(self.path).exists():
            self.validationError = f"Tool path not found: {self.path}"
            return False
        for exe in [self.cc, self.cxx, self.ar, self.ld]:
            if exe:
                try:
                    result = subprocess.run(
                        [exe, '--version'] if not exe.endswith('.exe') else [exe],
                        capture_output=True, text=True, timeout=2
                    )
                    if result.returncode != 0:
                        self.validationError = f"Tool not executable: {exe}"
                        return False
                except (FileNotFoundError, subprocess.TimeoutExpired):
                    self.validationError = f"Tool not found: {exe}"
                    return False
        self.validated = True
        return True

    def ToDict(self) -> dict:
        return {
            'name': self.name, 'type': self.type, 'version': self.version,
            'path': self.path, 'cc': self.cc, 'cxx': self.cxx, 'ar': self.ar,
            'ld': self.ld, 'strip': self.strip, 'ranlib': self.ranlib,
            'sdkPath': self.sdkPath, 'includePaths': self.includePaths,
            'libraryPaths': self.libraryPaths, 'frameworks': self.frameworks,
            'envVars': self.envVars, 'cflags': self.cflags,
            'cxxflags': self.cxxflags, 'ldflags': self.ldflags,
            'sysroot': self.sysroot, 'targetTriple': self.targetTriple,
            'validated': self.validated
        }


class ExternalToolsManager:
    """Manager for external tools with caching."""
    def __init__(self):
        self._tools: Dict[str, ToolConfig] = {}
        self._activeTools: List[str] = []
        self._cacheFile = self._ResolveCacheFile()
        self._loaded = False

    @staticmethod
    def _ResolveCacheFile() -> Path:
        """
        Resolve a writable cache path.
        Prefer local workspace .jenga, then Jenga root, then user home.
        """
        candidates = [
            Path(".jenga") / "tools_cache.json",
            Path(__file__).resolve().parents[2] / ".jenga" / "tools_cache.json",
            Path.home() / ".jenga" / "tools_cache.json",
        ]
        for cand in candidates:
            try:
                cand.parent.mkdir(parents=True, exist_ok=True)
                return cand
            except Exception:
                continue
        # Last-resort fallback; SaveCache already handles failures.
        return Path(".jenga") / "tools_cache.json"

    def LoadCache(self):
        if not self._loaded and self._cacheFile.exists():
            try:
                with open(self._cacheFile, 'r') as f:
                    data = json.load(f)
                for name, tdata in data.get('tools', {}).items():
                    tool = ToolConfig(
                        name=tdata['name'], type=tdata['type'],
                        version=tdata.get('version', ''),
                        path=tdata.get('path', ''),
                        cc=tdata.get('cc', ''),
                        cxx=tdata.get('cxx', ''),
                        ar=tdata.get('ar', ''),
                        ld=tdata.get('ld', ''),
                        strip=tdata.get('strip', ''),
                        ranlib=tdata.get('ranlib', ''),
                        sdkPath=tdata.get('sdkPath', ''),
                        includePaths=tdata.get('includePaths', []),
                        libraryPaths=tdata.get('libraryPaths', []),
                        frameworks=tdata.get('frameworks', []),
                        envVars=tdata.get('envVars', {}),
                        cflags=tdata.get('cflags', []),
                        cxxflags=tdata.get('cxxflags', []),
                        ldflags=tdata.get('ldflags', []),
                        sysroot=tdata.get('sysroot', ''),
                        targetTriple=tdata.get('targetTriple', ''),
                        validated=tdata.get('validated', False)
                    )
                    self._tools[name] = tool
                self._activeTools = data.get('activeTools', [])
                self._loaded = True
            except Exception:
                pass

    def SaveCache(self):
        try:
            self._cacheFile.parent.mkdir(parents=True, exist_ok=True)
            data = {
                'tools': {name: t.ToDict() for name, t in self._tools.items()},
                'activeTools': self._activeTools
            }
            with open(self._cacheFile, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception:
            pass

    def AddTool(self, tool: ToolConfig, activate: bool = True) -> bool:
        if tool.Validate():
            self._tools[tool.name] = tool
            if activate and tool.name not in self._activeTools:
                self._activeTools.append(tool.name)
            self.SaveCache()
            return True
        else:
            print(f"❌ Failed to add tool '{tool.name}': {tool.validationError}")
            return False

    def GetTool(self, name: str) -> Optional[ToolConfig]:
        self.LoadCache()
        return self._tools.get(name)

    def GetActiveTools(self) -> List[ToolConfig]:
        self.LoadCache()
        return [self._tools[n] for n in self._activeTools if n in self._tools]

    def ActivateTool(self, name: str) -> bool:
        self.LoadCache()
        if name in self._tools:
            if name not in self._activeTools:
                self._activeTools.append(name)
            self.SaveCache()
            return True
        return False

    def DeactivateTool(self, name: str) -> bool:
        self.LoadCache()
        if name in self._activeTools:
            self._activeTools.remove(name)
            self.SaveCache()
            return True
        return False

    def ListTools(self) -> List[dict]:
        self.LoadCache()
        return [
            {'name': t.name, 'type': t.type, 'version': t.version,
             'path': t.path, 'active': t.name in self._activeTools,
             'validated': t.validated}
            for t in self._tools.values()
        ]


# Global tools manager
_toolsManager = ExternalToolsManager()


class addtools:
    """
    Context manager for adding external tools to the build system.
    Supports file path, built‑in tool name, or inline dict.
    """
    def __init__(self, toolsConfig, activate: bool = True):
        self._toolsConfig = toolsConfig
        self._activate = activate
        self._resolvedPath = None
        self._loadedTools = []
        self._previousActiveTools = []

    def __enter__(self):
        global _toolsManager
        self._previousActiveTools = _toolsManager._activeTools.copy()
        self._ResolveAndLoad()
        if self._activate:
            for toolName in self._loadedTools:
                _toolsManager.ActivateTool(toolName)
        self._ApplyEnvVars()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        global _toolsManager
        self._RestoreEnvVars()
        _toolsManager._activeTools = self._previousActiveTools
        _toolsManager.SaveCache()
        return False

    def _ResolveAndLoad(self):
        if isinstance(self._toolsConfig, dict):
            self._LoadFromDict(self._toolsConfig)
            return

        cfgStr = str(self._toolsConfig)
        # Check built‑in
        builtin = JengaToolsRegistry.LoadBuiltinToolConfig(cfgStr)
        if builtin:
            self._LoadFromDict(builtin)
            return

        # Resolve file path
        self._resolvedPath = self._ResolveToolsConfig(cfgStr)
        if not self._resolvedPath:
            raise FileNotFoundError(f"Tools config not found: {cfgStr}")
        ext = self._resolvedPath.suffix.lower()
        if ext == '.jenga':
            self._LoadFromJengaFile()
        elif ext == '.json':
            self._LoadFromJsonFile()
        elif ext == '.py':
            self._LoadFromPythonFile()
        else:
            self._LoadAutoDetect()

    def _ResolveToolsConfig(self, cfgStr: str) -> Optional[Path]:
        """Search in multiple locations."""
        search = []
        cur = Path.cwd()
        search.extend([cur / cfgStr, cur / f"{cfgStr}.jenga", cur / f"{cfgStr}.json", cur / f"{cfgStr}.py"])
        wksPath = self._FindWorkspacePath()
        if wksPath:
            search.extend([
                wksPath / cfgStr, wksPath / f"{cfgStr}.jenga",
                wksPath / f"{cfgStr}.json", wksPath / f"{cfgStr}.py",
                wksPath / "tools" / cfgStr, wksPath / "tools" / f"{cfgStr}.jenga"
            ])
        jtPath = self._GetJengaToolsPath()
        if jtPath:
            search.extend([
                jtPath / cfgStr, jtPath / f"{cfgStr}.jenga",
                jtPath / f"{cfgStr}.json", jtPath / f"{cfgStr}.py"
            ])
        userPath = Path.home() / ".jenga" / "tools"
        if userPath.exists():
            search.extend([
                userPath / cfgStr, userPath / f"{cfgStr}.jenga",
                userPath / f"{cfgStr}.json"
            ])
        for loc in search:
            if loc.exists():
                return loc
        return None

    def _FindWorkspacePath(self) -> Optional[Path]:
        if _currentWorkspace and _currentWorkspace.location:
            return Path(_currentWorkspace.location)
        cur = Path.cwd()
        for parent in [cur] + list(cur.parents):
            if any(parent.glob("*.jenga")):
                return parent
        return None

    def _GetJengaToolsPath(self) -> Optional[Path]:
        import sys
        for sp in sys.path:
            p = Path(sp) / "Jenga" / "Tools"
            if p.exists():
                return p
        try:
            import Jenga
            return Path(Jenga.__file__).parent / "Tools"
        except ImportError:
            return None

    def _LoadFromDict(self, d: dict):
        global _toolsManager
        for name, cfg in d.items():
            if isinstance(cfg, dict):
                cfg['name'] = name
                tool = self._CreateToolFromDict(cfg)
                if tool and _toolsManager.AddTool(tool, activate=self._activate):
                    self._loadedTools.append(name)

    def _LoadFromJengaFile(self):
        content = self._resolvedPath.read_text(encoding='utf-8')
        import re
        pattern = r'(\w+)\s*=\s*(\{[^}]*\})'
        for match in re.finditer(pattern, content, re.DOTALL):
            name = match.group(1)
            dictStr = match.group(2)
            try:
                d = self._SafeEvalDict(dictStr)
                d['name'] = name
                tool = self._CreateToolFromDict(d)
                if tool and _toolsManager.AddTool(tool, activate=self._activate):
                    self._loadedTools.append(name)
            except Exception:
                pass

    def _LoadFromJsonFile(self):
        with open(self._resolvedPath, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if isinstance(data, dict):
            self._LoadFromDict(data)

    def _LoadFromPythonFile(self):
        exec_globals = {'__file__': str(self._resolvedPath), '__name__': '__tools__', 'Path': Path}
        exec(self._resolvedPath.read_text(encoding='utf-8'), exec_globals)
        for name, val in exec_globals.items():
            if not name.startswith('_') and isinstance(val, dict) and ('type' in val or 'path' in val):
                val['name'] = name
                tool = self._CreateToolFromDict(val)
                if tool and _toolsManager.AddTool(tool, activate=self._activate):
                    self._loadedTools.append(name)

    def _LoadAutoDetect(self):
        # Placeholder for auto-detection logic
        pass

    def _CreateToolFromDict(self, d: dict) -> Optional[ToolConfig]:
        try:
            return ToolConfig(
                name=d['name'],
                type=d.get('type', 'custom'),
                version=d.get('version', ''),
                path=d.get('path', ''),
                cc=d.get('cc', ''),
                cxx=d.get('cxx', ''),
                ar=d.get('ar', ''),
                ld=d.get('ld', ''),
                strip=d.get('strip', ''),
                ranlib=d.get('ranlib', ''),
                sdkPath=d.get('sdkPath', ''),
                includePaths=d.get('includePaths', []),
                libraryPaths=d.get('libraryPaths', []),
                frameworks=d.get('frameworks', []),
                envVars=d.get('envVars', {}),
                cflags=d.get('cflags', []),
                cxxflags=d.get('cxxflags', []),
                ldflags=d.get('ldflags', []),
                sysroot=d.get('sysroot', ''),
                targetTriple=d.get('targetTriple', '')
            )
        except Exception:
            return None

    def _SafeEvalDict(self, s: str) -> dict:
        import ast
        try:
            return ast.literal_eval(s)
        except:
            import re
            result = {}
            pairs = re.findall(r'"([^"]+)"\s*:\s*"([^"]*)"', s)
            for k, v in pairs:
                result[k] = v
            return result

    def _ApplyEnvVars(self):
        global _toolsManager
        self._originalEnv = {}
        for tool in _toolsManager.GetActiveTools():
            for k, v in tool.envVars.items():
                if k in os.environ:
                    self._originalEnv[k] = os.environ[k]
                os.environ[k] = v

    def _RestoreEnvVars(self):
        for k, v in self._originalEnv.items():
            os.environ[k] = v


class JengaToolsRegistry:
    """Registry of built‑in Jenga tools."""
    BUILTIN_TOOLS = {
        "android-ndk": {"name": "android-ndk", "type": "ndk", "configTemplate": "android_ndk.jenga"},
        "emscripten": {"name": "emscripten", "type": "emscripten", "configTemplate": "emscripten.jenga"},
        "msvc": {"name": "msvc", "type": "compiler", "configTemplate": "msvc.jenga"},
        "xcode": {"name": "xcode", "type": "sdk", "configTemplate": "xcode.jenga"},
    }

    @classmethod
    def LoadBuiltinToolConfig(cls, name: str) -> Optional[dict]:
        if name not in cls.BUILTIN_TOOLS:
            return None
        # Simplified: return a template; real implementation would load from file.
        return {
            "name": name,
            "type": cls.BUILTIN_TOOLS[name]["type"],
            "path": f"%{{Jenga.Tools}}/{name}"
        }


# --- User‑exposed functions for tools (all lowercase) ---
_AddToolsContext = addtools

def addtools(config, activate: bool = True):
    """Return an addtools context manager (usable with `with addtools(...):`)."""
    return _AddToolsContext(config, activate)

def usetool(toolName: str):
    """Use a specific tool for the current project."""
    global _currentProject, _toolsManager
    if not _currentProject:
        raise RuntimeError("usetool must be inside a project context")
    tool = _toolsManager.GetTool(toolName)
    if not tool:
        raise ValueError(f"Tool not found: {toolName}")
    _toolsManager.ActivateTool(toolName)
    _currentProject.toolchain = f"tool_{toolName}"

def listtools() -> List[dict]:
    return _toolsManager.ListTools()

def gettoolinfo(toolName: str) -> Optional[dict]:
    tool = _toolsManager.GetTool(toolName)
    if not tool:
        return None
    info = tool.ToDict()
    info['active'] = toolName in _toolsManager._activeTools
    return info

def validatetools() -> List[dict]:
    results = []
    for tool in _toolsManager.GetActiveTools():
        ok = tool.Validate()
        results.append({
            'name': tool.name, 'valid': ok,
            'error': tool.validationError if not ok else '',
            'type': tool.type
        })
    return results

# --- Pre‑configured tool templates (factory functions) – PascalCase ---
def CreateAndroidNdkTool(ndkPath: str, apiLevel: int = 21, arch: str = "arm64-v8a") -> dict:
    ndkPath = Path(ndkPath).absolute()
    triples = {
        "arm64-v8a": f"aarch64-linux-android{apiLevel}",
        "armeabi-v7a": f"armv7a-linux-androideabi{apiLevel}",
        "x86": f"i686-linux-android{apiLevel}",
        "x86_64": f"x86_64-linux-android{apiLevel}"
    }
    triple = triples.get(arch, f"aarch64-linux-android{apiLevel}")
    toolchainDir = None
    for p in ndkPath.glob("toolchains/llvm/prebuilt/*"):
        if p.is_dir():
            toolchainDir = p
            break
    if not toolchainDir:
        raise FileNotFoundError(f"LLVM toolchain not found in {ndkPath}")
    return {
        "name": f"android-ndk-api{apiLevel}-{arch}",
        "type": "ndk",
        "path": str(ndkPath),
        "cc": str(toolchainDir / "bin" / f"{triple}-clang"),
        "cxx": str(toolchainDir / "bin" / f"{triple}-clang++"),
        "ar": str(toolchainDir / "bin" / "llvm-ar"),
        "ld": str(toolchainDir / "bin" / "ld"),
        "strip": str(toolchainDir / "bin" / "llvm-strip"),
        "ranlib": str(toolchainDir / "bin" / "llvm-ranlib"),
        "sysroot": str(toolchainDir / "sysroot"),
        "targetTriple": triple,
        "cflags": [f"-DANDROID", f"-D__ANDROID_API__={apiLevel}", "-fPIC"],
        "cxxflags": ["-std=c++17"],
        "ldflags": ["-llog", "-landroid", "-lEGL", "-lGLESv3"],
        "envVars": {"ANDROID_NDK_ROOT": str(ndkPath), "ANDROID_NDK_HOME": str(ndkPath), "ANDROID_API": str(apiLevel)}
    }

def CreateEmscriptenTool(emsdkPath: str) -> dict:
    emsdkPath = Path(emsdkPath).absolute()
    emccPath = None
    for p in [emsdkPath / "emcc", emsdkPath / "emsdk" / "emcc", emsdkPath / "upstream" / "emscripten" / "emcc"]:
        if p.exists():
            emccPath = p.parent
            break
    if not emccPath:
        import shutil
        ep = shutil.which("emcc")
        if ep:
            emccPath = Path(ep).parent
    if not emccPath:
        raise FileNotFoundError("emcc not found")
    return {
        "name": "emscripten",
        "type": "emscripten",
        "path": str(emsdkPath),
        "cc": str(emccPath / "emcc"),
        "cxx": str(emccPath / "em++"),
        "ar": str(emccPath / "emar"),
        "cflags": ["-D__EMSCRIPTEN__", "-s WASM=1", "-s USE_WEBGL2=1"],
        "cxxflags": ["-std=c++17", "-s USE_PTHREADS=1"],
        "ldflags": ["-s ALLOW_MEMORY_GROWTH=1", "-s EXPORTED_FUNCTIONS='[\"_main\"]'"],
        "envVars": {"EMSDK": str(emsdkPath)}
    }

def CreateCustomGccTool(gccPath: str, version: str = "") -> dict:
    gccPath = Path(gccPath).absolute()
    return {
        "name": f"gcc-custom-{version}" if version else "gcc-custom",
        "type": "compiler",
        "path": str(gccPath),
        "version": version,
        "cc": str(gccPath / "bin" / "gcc"),
        "cxx": str(gccPath / "bin" / "g++"),
        "ar": str(gccPath / "bin" / "ar"),
        "ld": str(gccPath / "bin" / "ld"),
        "strip": str(gccPath / "bin" / "strip"),
        "ranlib": str(gccPath / "bin" / "ranlib"),
        "cflags": ["-march=native", "-mtune=native", "-O3", "-pipe"],
        "cxxflags": ["-std=c++20", "-fcoroutines"],
        "envVars": {"CUSTOM_GCC_ROOT": str(gccPath)}
    }


# ---------------------------------------------------------------------------
# Build presets – optimisation, debug symbols, profiling, coverage, sanitizers
# ---------------------------------------------------------------------------

def debug() -> None:
    """Set project to Debug configuration: no optimization, full debug symbols."""
    if _currentProject:
        _currentProject.optimize = Optimization.OFF
        _currentProject.symbols = True
        # Supprimer les flags d'optimisation éventuels
        _currentProject.cflags = [f for f in _currentProject.cflags if not f.startswith('-O')]
        _currentProject.cxxflags = [f for f in _currentProject.cxxflags if not f.startswith('-O')]
        # Pas d'optimisation = -O0 pour GCC/Clang, /Od pour MSVC
        # Ces flags seront ajoutés par les builders selon la toolchain.

def release() -> None:
    """Set project to Release configuration: full optimization, no debug symbols."""
    if _currentProject:
        _currentProject.optimize = Optimization.SPEED
        _currentProject.symbols = False

def reldebinfo() -> None:
    """Set project to RelWithDebInfo: optimized with debug symbols."""
    if _currentProject:
        _currentProject.optimize = Optimization.SPEED
        _currentProject.symbols = True

def minsizerel() -> None:
    """Set project to MinSizeRel: optimize for size."""
    if _currentProject:
        _currentProject.optimize = Optimization.SIZE
        _currentProject.symbols = False

# --- Debug information format ---
def debuggdb() -> None:
    """Generate debug info compatible with GDB (adds -ggdb on GCC/Clang)."""
    if _currentProject:
        # Forcer les symboles
        _currentProject.symbols = True
        # Ajouter les flags spécifiques – seront interprétés par les builders
        _currentProject.cflags.append("-ggdb")
        _currentProject.cxxflags.append("-ggdb")

def debuglldb() -> None:
    """Generate debug info compatible with LLDB (adds -glldb on Clang, -g on others)."""
    if _currentProject:
        _currentProject.symbols = True
        # Sur Clang, on peut utiliser -glldb ; sur GCC, -g suffit.
        # On ajoute -glldb, les builders adapteront.
        _currentProject.cflags.append("-glldb")
        _currentProject.cxxflags.append("-glldb")

def debugcodeview() -> None:
    """Generate CodeView debug info (MSVC format, adds /Zi and /DEBUG)."""
    if _currentProject:
        _currentProject.symbols = True
        # Flags MSVC : /Zi pour le compilateur, /DEBUG pour l'éditeur de liens
        _currentProject.cflags.append("/Zi")
        _currentProject.cxxflags.append("/Zi")
        _currentProject.ldflags.append("/DEBUG")

# --- Profiling ---
def profilegprof() -> None:
    """Enable profiling with gprof (adds -pg on GCC/Clang)."""
    if _currentProject:
        _currentProject.cflags.append("-pg")
        _currentProject.cxxflags.append("-pg")
        _currentProject.ldflags.append("-pg")

def profilevs() -> None:
    """Enable profiling with Visual Studio Profiler (adds /PROFILE)."""
    if _currentProject:
        _currentProject.ldflags.append("/PROFILE")

def profileinstruments() -> None:
    """Enable profiling with Xcode Instruments (no special flags, just keep symbols)."""
    if _currentProject:
        _currentProject.symbols = True
        # Les instruments fonctionnent avec les symboles dwarf standard.

# --- Code coverage ---
def coveragegcov() -> None:
    """Enable code coverage with gcov (adds -fprofile-arcs -ftest-coverage)."""
    if _currentProject:
        _currentProject.cflags.append("-fprofile-arcs")
        _currentProject.cflags.append("-ftest-coverage")
        _currentProject.cxxflags.append("-fprofile-arcs")
        _currentProject.cxxflags.append("-ftest-coverage")
        _currentProject.ldflags.append("-fprofile-arcs")
        _currentProject.ldflags.append("-lgcov")

def coveragevs() -> None:
    """Enable code coverage with Visual Studio (adds /PROFILE)."""
    if _currentProject:
        _currentProject.ldflags.append("/PROFILE")
        # Sous MSVC, la couverture est intégrée au profilage.

# --- Sanitizers (déjà partiellement dans toolchain, on ajoute la version projet) ---
def sanitizeaddress() -> None:
    """Enable AddressSanitizer."""
    if _currentProject:
        _currentProject.cflags.append("-fsanitize=address")
        _currentProject.cxxflags.append("-fsanitize=address")
        _currentProject.ldflags.append("-fsanitize=address")

def sanitizethread() -> None:
    """Enable ThreadSanitizer."""
    if _currentProject:
        _currentProject.cflags.append("-fsanitize=thread")
        _currentProject.cxxflags.append("-fsanitize=thread")
        _currentProject.ldflags.append("-fsanitize=thread")

def sanitizeundefined() -> None:
    """Enable UndefinedBehaviorSanitizer."""
    if _currentProject:
        _currentProject.cflags.append("-fsanitize=undefined")
        _currentProject.cxxflags.append("-fsanitize=undefined")
        _currentProject.ldflags.append("-fsanitize=undefined")

def sanitizememory() -> None:
    """Enable MemorySanitizer (Clang only)."""
    if _currentProject:
        _currentProject.cflags.append("-fsanitize=memory")
        _currentProject.cxxflags.append("-fsanitize=memory")
        _currentProject.ldflags.append("-fsanitize=memory")

# --- Custom flags helper ---
def addcflag(flag: str) -> None:
    """Add a custom C flag to the current toolchain or project."""
    if _currentToolchain:
        _currentToolchain.cflags.append(flag)
    elif _currentProject:
        _currentProject.cflags.append(flag)

def addcxxflag(flag: str) -> None:
    """Add a custom C++ flag to the current toolchain or project."""
    if _currentToolchain:
        _currentToolchain.cxxflags.append(flag)
    elif _currentProject:
        _currentProject.cxxflags.append(flag)

def addldflag(flag: str) -> None:
    """Add a custom linker flag to the current toolchain or project."""
    if _currentToolchain:
        _currentToolchain.ldflags.append(flag)
    elif _currentProject:
        _currentProject.ldflags.append(flag)


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------

def inittools():
    """Initialize the tools system (call at Jenga startup)."""
    global _toolsManager
    _toolsManager.LoadCache()
    for tool in _toolsManager.GetActiveTools():
        for k, v in tool.envVars.items():
            os.environ[k] = v

# ---------------------------------------------------------------------------
# Export public symbols (only what users need)
# ---------------------------------------------------------------------------

__all__ = [
    # Enums
    'ProjectKind', 'Language', 'Optimization', 'WarningLevel',
    'TargetOS', 'TargetArch', 'TargetEnv', 'CompilerFamily',
    # Context managers
    'workspace', 'project', 'toolchain', 'filter', 'unitest', 'test', 'include', 'batchinclude', 'addtools',
    # User functions (lowercase)
    'configurations', 'platforms', 'targetoses', 'targetarchs', 'targetos', 'targetarch', 'platform', 'architecture', 'startproject', 'disableunittestcompilation', 'disableunittestexecution', 'dutc', 'dute', 'newoption',
    'consoleapp', 'windowedapp', 'staticlib', 'sharedlib', 'testsuite', 'kind',
    'language', 'cppdialect', 'cdialect',
    'location', 'files', 'excludefiles', 'removefiles', 'excludemainfiles', 'removemainfiles',
    'includedirs', 'externalincludedirs', 'sysincludedirs', 'removeincludedirs',
    'libdirs', 'syslibdirs', 'removelibdirs', 'objdir', 'targetdir', 'targetname',
    'links', 'removelinks', 'dependson', 'removedependson', 'dependfiles', 'embedresources',
    'defines', 'removedefines', 'undefines', 'optimize', 'symbols', 'warnings', 'runtime',
    'pchheader', 'pchsource',
    'prebuild', 'postbuild', 'prelink', 'postlink',
    'usetoolchain',
    'androidsdkpath', 'androidndkpath', 'javajdkpath',
    'androidapplicationid', 'androidversioncode', 'androidversionname',
    'androidminsdk', 'androidtargetsdk', 'androidcompilesdk',
    'androidabis', 'androidproguard', 'androidproguardrules',
    'androidassets', 'androidisgame', 'androidpermissions', 'androidnativeactivity',
    'androidstl', 'androidallowrotation', 'androidscreenorientation',
    'androidjavafiles', 'androidjavalibs',
    'ndkversion', 'androidsign', 'androidkeystore', 'androidkeystorepass', 'androidkeyalias',
    'emscriptenshellfile', 'emscriptenfullscreenshell', 'emscriptencanvasid', 'emscripteninitialmemory',
    'emscriptenstacksize', 'emscriptenexportname', 'emscriptenextraflags',
    'iosbundleid', 'iosversion', 'iosminsdk', 'tvosminsdk', 'watchosminsdk', 'ipadosminsdk', 'visionosminsdk',
    'iossigningidentity', 'iosentitlements', 'iosappicon', 'iosbuildnumber',
    'iosbuildsystem', 'iosdistributiontype', 'iosteamid', 'iosprovisioningprofile',
    # Cross-platform app icon API (voir Core/IconConverter.py)
    'appicon', 'androidappicon', 'windowsicon', 'macosicon', 'webfavicon',
    # Installer packaging DSL (MSI/EXE/DEB/PKG)
    'licensefile', 'createdesktopshortcut', 'apppublisher', 'appversion',
    'installeroption',
    # Code signing DSL (--type jng : self-extracting installer)
    'signingcertificate', 'signingpassword', 'signingthumbprint',
    'signingidentity', 'signingtimestampurl', 'signinggpgkey',
    'signingentitlements', 'signingrequireadmin',
    # Network / firewall DSL (installer-time) — voir Commands/Package.py
    'networkenabled', 'firewallrule', 'networkusagedescription',
    'bonjourservices', 'iosallowarbitraryloads', 'FirewallRule',
    'harmonyminsdk', 'harmonysdk',
    'harmonybundlename', 'harmonyversioncode', 'harmonyversionname',
    'harmonytargetapi', 'harmonysign', 'harmonycertfile', 'harmonyprofile',
    'harmonykeystore', 'harmonykeyalias', 'harmonykeypwd', 'harmonyappicon',
    'harmonyresources', 'harmonyassets', 'harmonypermissions', 'harmonyets',
    'testoptions', 'testfiles', 'testmainfile', 'testmaintemplate',
    'settarget', 'sysroot', 'targettriple', 'ccompiler', 'cppcompiler',
    'linker', 'archiver', 'addcflag', 'addcxxflag', 'addldflag',
    'cflags', 'cxxflags', 'ldflags', 'asmflags', 'arflags',
    'framework', 'frameworks', 'frameworkpath', 'librarypath', 'library', 'rpath',
    'sanitize', 'nostdlib', 'nostdinc', 'pic', 'pie',
    'buildoption', 'buildoptions', 'linkoptions',
    'useproject', 'getprojectproperties',
    'includefromdirectory', 'listincludes', 'getincludeinfo', 'validateincludes',
    'lip', 'vip', 'getincludedprojects', 'generatedependencyreport', 'listallprojects',
    'getcurrentworkspace', 'resetstate',
    # Tools
    'addtools', 'usetool', 'listtools', 'gettoolinfo', 'validatetools',
    'CreateAndroidNdkTool', 'CreateEmscriptenTool', 'CreateCustomGccTool',
    'inittools'
]

# ---------------------------------------------------------------------------
# Example .jenga file (commented)
# ---------------------------------------------------------------------------

"""
# ============================================================
# Exemple 1 – Workspace avec Unitest précompilé et test
# ============================================================

with workspace("MonJeu"):
    configurations(["Debug", "Release"])
    targetoses(["Windows", "Linux"])
    targetarchs(["x86_64"])

    # Configuration de Unitest (précompilé)
    with unitest() as u:
        u.Precompiled()

    with toolchain("gcc", "gcc"):
        settarget("Linux", "x86_64", "gnu")
        ccompiler("/usr/bin/gcc")
        cppcompiler("/usr/bin/g++")

    usetoolchain("gcc")

    with project("Moteur"):
        staticlib()
        language("C++")
        files(["src/**.cpp"])
        includedirs(["include"])

        # 🔹 TEST – obligatoirement indenté sous le projet
        with test():
            testfiles(["tests/**.cpp"])
            testmainfile("src/main.cpp")

# ============================================================
# Exemple 2 – Workspace avec Unitest compilé sur mesure
# ============================================================

with workspace("Application"):
    with unitest() as u:
        u.Compile(
            kind="STATIC_LIB",
            objDir="Build/Obj/Unitest",
            targetDir="Libs",
            targetName="Unitest",
            cxxflags=["-O2", "-DNDEBUG"]
        )

    with project("Core"):
        # ...
        with test("Unit"):
            testfiles(["unit/**.cpp"])

# ============================================================
# Exemple 3 – Inclusion de toolchains externes
# ============================================================

with include("toolchains/android.jenga"):
    pass   # les toolchains sont importées

usetoolchain("android_arm64")

# ============================================================
# Exemple 4 – Utilisation de batchinclude
# ============================================================

with batchinclude([
    "libs/logger.jenga",
    "libs/math.jenga"
]):
    pass
"""

# ---------------------------------------------------------------------------
# End of api.py
# ---------------------------------------------------------------------------
