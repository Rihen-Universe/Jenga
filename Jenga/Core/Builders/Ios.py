#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Apple Mobile Direct Builder.
Builds iOS/tvOS/watchOS/iPadOS/visionOS apps and libraries with Apple Clang/xcrun (without xcodebuild).
"""

import os
import plistlib
import shutil
import tempfile
import zipfile
import re
from pathlib import Path
from typing import Dict, List, Optional

from Jenga.Core.Api import CompilerFamily, Project, ProjectKind, TargetArch, TargetEnv, TargetOS
from ...Utils import Colored, FileSystem, Process, ProcessResult
from ..Builder import Builder
from ..Platform import Platform
from ..IconConverter import ResolveIconFor, PLATFORM_IOS


class DirectIOSBuilder(Builder):
    """
    Apple mobile builder (direct clang/xcrun mode).
    """

    _TARGETS: Dict[TargetOS, Dict[str, object]] = {
        TargetOS.IOS: {
            "display": "iOS",
            "sdk_device": "iphoneos",
            "sdk_simulator": "iphonesimulator",
            "triple_os": "ios",
            "min_flag": "mios-version-min",
            "min_flag_sim": "mios-simulator-version-min",
            "platform_device": "iPhoneOS",
            "platform_simulator": "iPhoneSimulator",
            "requires_iphone_os": True,
            "device_family": [1, 2],  # iPhone, iPad
            "define": "IOS",
            "frameworks": ["Foundation", "UIKit"],
            "device_frameworks": ["OpenGLES"],
            "default_min": "12.0",
            "min_sdk_attr": "iosMinSdk",   # fallback pour l'API actuelle
        },
        TargetOS.TVOS: {
            "display": "tvOS",
            "sdk_device": "appletvos",
            "sdk_simulator": "appletvsimulator",
            "triple_os": "tvos",
            "min_flag": "mappletvos-version-min",
            "min_flag_sim": "mtvos-simulator-version-min",
            "platform_device": "AppleTVOS",
            "platform_simulator": "AppleTVSimulator",
            "requires_iphone_os": False,
            "device_family": [3],  # Apple TV
            "define": "TVOS",
            "frameworks": ["Foundation", "UIKit"],
            "device_frameworks": [],
            "default_min": "12.0",
            "min_sdk_attr": "tvosMinSdk",  # à ajouter dans l'API
        },
        TargetOS.WATCHOS: {
            "display": "watchOS",
            "sdk_device": "watchos",
            "sdk_simulator": "watchsimulator",
            "triple_os": "watchos",
            "min_flag": "mwatchos-version-min",
            "min_flag_sim": "mwatchos-simulator-version-min",
            "platform_device": "WatchOS",
            "platform_simulator": "WatchSimulator",
            "requires_iphone_os": False,
            "device_family": [4],  # Apple Watch
            "define": "WATCHOS",
            "frameworks": ["Foundation", "WatchKit"],
            "device_frameworks": [],
            "default_min": "8.0",
            "min_sdk_attr": "watchosMinSdk",  # à ajouter dans l'API
        },
        TargetOS.IPADOS: {
            "display": "iPadOS",
            "sdk_device": "iphoneos",
            "sdk_simulator": "iphonesimulator",
            "triple_os": "ios",
            "min_flag": "mios-version-min",
            "min_flag_sim": "mios-simulator-version-min",
            "platform_device": "iPhoneOS",
            "platform_simulator": "iPhoneSimulator",
            "requires_iphone_os": True,
            "device_family": [2],  # iPad
            "define": "IPADOS",
            "frameworks": ["Foundation", "UIKit"],
            "device_frameworks": ["OpenGLES"],
            "default_min": "13.0",
            "min_sdk_attr": "ipadosMinSdk",
        },
        TargetOS.VISIONOS: {
            "display": "visionOS",
            "sdk_device": "xros",
            "sdk_simulator": "xrsimulator",
            "triple_os": "xros",
            "min_flag": "mxros-version-min",
            "min_flag_sim": "mxros-simulator-version-min",
            "platform_device": "XROS",
            "platform_simulator": "XRSimulator",
            "requires_iphone_os": False,
            "device_family": [7],  # Apple visionOS family
            "define": "VISIONOS",
            "frameworks": ["Foundation"],
            "device_frameworks": [],
            "default_min": "1.0",
            "min_sdk_attr": "visionosMinSdk",
        },
    }

    def __init__(self, workspace, config, platform, targetOs, targetArch, targetEnv=None, verbose=False):
        super().__init__(workspace, config, platform, targetOs, targetArch, targetEnv, verbose)

        if self.targetOs not in self._TARGETS:
            raise RuntimeError(f"Unsupported Apple mobile target for direct builder: {self.targetOs.value}")

        self.target_profile = self._TARGETS[self.targetOs]
        self.is_simulator = self._IsSimulatorTarget()
        self.sdk_name = (
            str(self.target_profile["sdk_simulator"])
            if self.is_simulator else str(self.target_profile["sdk_device"])
        )

        self.sdk_path = self._GetSDKPath(self.sdk_name)
        if not self.sdk_path:
            raise RuntimeError(
                f"{self.target_profile['display']} SDK '{self.sdk_name}' not found. Install Xcode command line tools."
            )

        self._CheckCompiler()
        self.min_version = self._GetMinimumVersion()
        self.target_triple = self._GetTargetTriple()

    @staticmethod
    def _IsDirectLibPath(lib: str) -> bool:
        p = Path(lib)
        return p.suffix in (".a", ".dylib", ".so", ".framework", ".lib") or "/" in lib or "\\" in lib or p.is_absolute()

    def _GetSDKPath(self, sdk: str) -> Optional[Path]:
        try:
            result = Process.Capture(["xcrun", "--sdk", sdk, "--show-sdk-path"])
            return Path(result.strip())
        except Exception as e:
            Colored.PrintError(f"Failed to get SDK path for {sdk}: {e}")
            return None

    def _CheckCompiler(self) -> None:
        try:
            cc_path = Process.Capture(["xcrun", "--find", "clang"]).strip()
            cxx_path = Process.Capture(["xcrun", "--find", "clang++"]).strip()
            self.toolchain.ccPath = cc_path
            self.toolchain.cxxPath = cxx_path
            self.toolchain.compilerFamily = CompilerFamily.APPLE_CLANG
        except Exception as e:
            raise RuntimeError(f"Apple Clang not found. Install Xcode command line tools: {e}")

    def _GetMinimumVersion(self, project: Optional[Project] = None) -> str:
        # Correctif 2026-08-11 : l'__init__ (ligne ~137) appelle sans projet —
        # « missing 1 required positional argument » cassait TOUT build iOS
        # direct (révélé par le premier `--platform ios` en CI). Sans projet,
        # on rend le défaut du profil ; la version PAR PROJET reste calculée
        # aux appels qui en passent un (même logique qu'AppleMobileBuilder).
        if project is None:
            return str(self.target_profile.get("default_min", "12.0"))
        # Selon la cible, on cherche un attribut spécifique
        if self.targetOs == TargetOS.IOS:
            min_ver = getattr(project, 'iosMinSdk', None)
        elif self.targetOs == TargetOS.TVOS:
            min_ver = getattr(project, 'tvosMinSdk', None)
        elif self.targetOs == TargetOS.WATCHOS:
            min_ver = getattr(project, 'watchosMinSdk', None)
        elif self.targetOs == TargetOS.IPADOS:
            min_ver = getattr(project, 'ipadosMinSdk', None)
        elif self.targetOs == TargetOS.VISIONOS:
            min_ver = getattr(project, 'visionosMinSdk', None)
        else:
            min_ver = None

        if min_ver:
            return str(min_ver)
        # Fallback sur la valeur par défaut du profil
        return str(self.target_profile.get("default_min", "12.0"))

    def _IsSimulatorTarget(self) -> bool:
        if self.targetArch in (TargetArch.X86_64, TargetArch.X86):
            return True
        platform_os = (self.platform or "").split("-", 1)[0].strip().lower()
        if "simulator" in platform_os:
            return True
        if self.targetEnv == TargetEnv.IOS and platform_os.endswith("sim"):
            return True
        return False

    def _GetArchName(self) -> str:
        return "arm64" if self.targetArch == TargetArch.ARM64 else "x86_64"

    def _GetMinVersionArg(self) -> str:
        flag_name = self.target_profile["min_flag_sim"] if self.is_simulator else self.target_profile["min_flag"]
        return f"-{flag_name}={self.min_version}"

    def _GetTargetTriple(self) -> str:
        arch = self._GetArchName()
        os_part = str(self.target_profile["triple_os"])
        suffix = "-simulator" if self.is_simulator else ""
        return f"{arch}-apple-{os_part}{self.min_version}{suffix}"

    def _GetTargetFlags(self) -> List[str]:
        return [
            "-target", self.target_triple,
            "-isysroot", str(self.sdk_path),
            self._GetMinVersionArg(),
        ]

    def GetObjectExtension(self) -> str:
        return ".o"

    def GetOutputExtension(self, project: Project) -> str:
        if project.kind == ProjectKind.SHARED_LIB:
            return ".dylib"
        if project.kind == ProjectKind.STATIC_LIB:
            return ".a"
        # Pour les apps, on renvoie .app (le bundle sera créé par la suite)
        return ".app"

    def GetModuleFlags(self, project: Project, sourceFile: str) -> List[str]:
        if not self.IsModuleFile(sourceFile):
            return []
        return [
            "-fmodules",
            "-fcxx-modules",
            "-fbuiltin-module-map",
            *self._GetTargetFlags(),
        ]

    def Compile(self, project: Project, sourceFile: str, objectFile: str) -> ProcessResult:
        src = Path(sourceFile)
        obj = Path(objectFile)
        FileSystem.MakeDirectory(obj.parent)

        compiler = self.toolchain.cxxPath if project.language.value in ("C++", "Objective-C++") else self.toolchain.ccPath
        args = [
            compiler,
            "-c",
            "-o", str(obj),
            *self.GetDependencyFlags(str(obj)),
            *self._GetTargetFlags(),
            "-arch", self._GetArchName(),
        ]
        args.extend(self._GetCompilerFlags(project))
        if self.IsModuleFile(sourceFile):
            args.extend(self.GetModuleFlags(project, sourceFile))
        args.append(str(src))

        result = Process.ExecuteCommand(args, captureOutput=True, silent=False)
        self._lastResult = result
        return result

    def Link(self, project: Project, objectFiles: List[str], outputFile: str) -> bool:
        out = Path(outputFile)
        FileSystem.MakeDirectory(out.parent)

        if project.kind == ProjectKind.STATIC_LIB:
            return self._LinkStaticLib(objectFiles, out)

        executable = out.parent / (project.targetName or project.name)
        if not self._LinkExecutable(project, objectFiles, executable):
            return False

        # Création du bundle .app si c'est une application
        if project.kind in (ProjectKind.CONSOLE_APP, ProjectKind.WINDOWED_APP, ProjectKind.TEST_SUITE):
            app_bundle = self._CreateAppBundle(project, executable)
            if not app_bundle:
                return False

            if not self.is_simulator and project.iosSigningIdentity:
                if not self._Codesign(app_bundle, project):
                    return False

            # Si le fichier de sortie demandé est .app, on crée un lien symbolique ou on copie
            if out.suffix == ".app":
                FileSystem.RemoveDirectory(out, recursive=True, ignoreErrors=True)
                try:
                    os.symlink(app_bundle, out, target_is_directory=True)
                except Exception:
                    shutil.copytree(app_bundle, out, dirs_exist_ok=True)
        return True

    def _LinkStaticLib(self, objectFiles: List[str], output: Path) -> bool:
        args = ["libtool", "-static", "-o", str(output)] + objectFiles
        result = Process.ExecuteCommand(args, captureOutput=True, silent=False)
        self._lastResult = result
        return result.returnCode == 0

    def _LinkExecutable(self, project: Project, objectFiles: List[str], output: Path) -> bool:
        args = [
            self.toolchain.cxxPath,
            "-o", str(output),
            *self._GetTargetFlags(),
            "-arch", self._GetArchName(),
        ]

        # Frameworks (par défaut selon la plateforme)
        for framework in list(self.target_profile["frameworks"]) + list(getattr(self.toolchain, "frameworks", [])):
            args.extend(["-framework", framework])
        if not self.is_simulator:
            for framework in list(self.target_profile["device_frameworks"]):
                args.extend(["-framework", framework])
        # Frameworks spécifiques au projet
        for framework in project.frameworks:
            args.extend(["-framework", framework])

        # Framework paths
        for fw_path in getattr(self.toolchain, "frameworkPaths", []):
            args.append(f"-F{fw_path}")

        # Library directories
        for libdir in project.libDirs:
            args.append(f"-L{self.ResolveProjectPath(project, libdir)}")

        # Libraries (links)
        for lib in project.links:
            if self._IsDirectLibPath(lib):
                args.append(self.ResolveProjectPath(project, lib))
            else:
                args.append(f"-l{lib}")

        # RPath
        args.append("-Wl,-rpath,@loader_path/Frameworks")

        # Toolchain ldflags
        args.extend(getattr(self.toolchain, "ldflags", []))
        # Project ldflags
        args.extend(project.ldflags)

        # Object files
        args.extend(objectFiles)

        result = Process.ExecuteCommand(args, captureOutput=True, silent=False)
        self._lastResult = result
        return result.returnCode == 0

    def _CreateAppBundle(self, project: Project, executable: Path) -> Optional[Path]:
        app_name = project.targetName or project.name
        bundle_dir = executable.parent / f"{app_name}.app"
        FileSystem.RemoveDirectory(bundle_dir, recursive=True, ignoreErrors=True)
        FileSystem.MakeDirectory(bundle_dir)

        dest_exe = bundle_dir / app_name
        shutil.copy2(executable, dest_exe)

        # Copier les ressources (embedResources)
        base_dir = Path(self.ResolveProjectPath(project, "."))
        for pattern in project.embedResources:
            for f in FileSystem.ListFiles(base_dir, pattern, recursive=True, fullPath=True):
                src = Path(f)
                dest = bundle_dir / src.relative_to(base_dir)
                FileSystem.MakeDirectory(dest.parent)
                shutil.copy2(src, dest)

        # Générer Info.plist
        plist_path = self._GenerateInfoPlist(project, bundle_dir)
        if plist_path:
            shutil.copy2(plist_path, bundle_dir / "Info.plist")

        # Icone : iosAppIcon (specifique) gagne, sinon fallback sur appicon()
        # generique (via IconConverter.ResolveIconFor). Le format doit etre
        # compatible iOS (PNG/JPG, ou .appiconset).
        resolved_icon = ResolveIconFor(project, PLATFORM_IOS)
        if resolved_icon:
            icon_path = Path(self.ResolveProjectPath(project, resolved_icon))
            if icon_path.exists():
                shutil.copy2(icon_path, bundle_dir / icon_path.name)

        return bundle_dir

    def _GenerateInfoPlist(self, project: Project, bundle_dir: Path) -> Optional[Path]:
        app_name = project.targetName or project.name
        bundle_id = project.iosBundleId or f"com.{project.name}.app"
        supported_platform = (
            str(self.target_profile["platform_simulator"])
            if self.is_simulator else str(self.target_profile["platform_device"])
        )
        plist = {
            "CFBundleName": app_name,
            "CFBundleDisplayName": app_name,
            "CFBundleIdentifier": bundle_id,
            "CFBundleVersion": project.iosBuildNumber or "1",
            "CFBundleShortVersionString": project.iosVersion or "1.0",
            "CFBundleExecutable": app_name,
            "CFBundlePackageType": "APPL",
            "CFBundleSupportedPlatforms": [supported_platform],
            "CFBundleInfoDictionaryVersion": "6.0",
            "CFBundleDevelopmentRegion": "en",
            "LSMinimumSystemVersion": self.min_version,
            "UIDeviceFamily": list(self.target_profile["device_family"]),
        }
        if bool(self.target_profile["requires_iphone_os"]):
            plist["LSRequiresIPhoneOS"] = True

        # Clés spécifiques à iOS
        if self.targetOs == TargetOS.IOS:
            plist["UISupportedInterfaceOrientations"] = [
                "UIInterfaceOrientationPortrait",
                "UIInterfaceOrientationLandscapeLeft",
                "UIInterfaceOrientationLandscapeRight",
            ]
            plist["UISupportedInterfaceOrientations~ipad"] = [
                "UIInterfaceOrientationPortrait",
                "UIInterfaceOrientationPortraitUpsideDown",
                "UIInterfaceOrientationLandscapeLeft",
                "UIInterfaceOrientationLandscapeRight",
            ]

        # Voir _CreateAppBundle pour la logique de fallback iosAppIcon -> appIcon.
        resolved_icon = ResolveIconFor(project, PLATFORM_IOS)
        if resolved_icon:
            plist["CFBundleIconFile"] = Path(resolved_icon).name

        # Permissions reseau iOS auto-injectees depuis le DSL :
        #   - networkenabled(True) -> NSLocalNetworkUsageDescription (requis
        #     pour Bonjour/mDNS sur iOS 14+, sinon les sockets locales sont
        #     bloquees silencieusement par le sandbox).
        #   - bonjourservices([...]) -> NSBonjourServices
        #   - iosallowarbitraryloads(True) -> NSAppTransportSecurity
        #     (NSAllowsArbitraryLoads = autorise HTTP non-TLS pour LAN/IoT).
        # Voir Core/FirewallSpec.py.
        try:
            from ..FirewallSpec import BuildIosInfoPlistNetworkKeys
            plist.update(BuildIosInfoPlistNetworkKeys(project))
        except Exception:
            # Defensif : ne jamais casser le build iOS pour un probleme firewall.
            pass

        plist_path = bundle_dir / "Info.plist"
        with open(plist_path, "wb") as f:
            plistlib.dump(plist, f)
        return plist_path

    def _Codesign(self, bundle_path: Path, project: Project) -> bool:
        identity = project.iosSigningIdentity
        if not identity:
            identity = self._GetDefaultSigningIdentity()
            if not identity:
                Colored.PrintWarning("No code signing identity found. Skipping codesign.")
                return True

        entitlements = self._ResolveEntitlements(project, bundle_path)
        args = [
            "codesign",
            "--force",
            "--sign", identity,
            "--timestamp",
            "--verbose",
            "--options", "runtime",
        ]
        if entitlements:
            args.extend(["--entitlements", str(entitlements)])
        args.append(str(bundle_path))

        result = Process.ExecuteCommand(args, captureOutput=True, silent=False)
        self._lastResult = result
        if result.returnCode != 0:
            Colored.PrintError(f"Code signing failed for {bundle_path}")
            return False
        return True

    def _GetDefaultSigningIdentity(self) -> Optional[str]:
        try:
            output = Process.Capture(["security", "find-identity", "-v", "-p", "codesigning"])
        except Exception:
            return None
        # Priorité aux identités de développement
        for line in output.splitlines():
            if "Apple Development:" in line:
                match = re.search(r'"([^"]+)"', line)
                if match:
                    return match.group(1)
        # Sinon n'importe quelle identité valide
        for line in output.splitlines():
            if "Developer ID Application:" in line:
                match = re.search(r'"([^"]+)"', line)
                if match:
                    return match.group(1)
        return None

    def _ResolveEntitlements(self, project: Project, bundle_dir: Path) -> Optional[Path]:
        if not project.iosEntitlements:
            return None
        src = Path(self.ResolveProjectPath(project, project.iosEntitlements))
        if not src.exists():
            return None
        dst = bundle_dir.parent / "Entitlements.plist"
        shutil.copy2(src, dst)
        return dst

    def _GetCompilerFlags(self, project: Project) -> List[str]:
        flags: List[str] = []

        # Sysroot déjà géré dans _GetTargetFlags
        for inc in project.includeDirs:
            flags.append(f"-I{self.ResolveProjectPath(project, inc)}")

        for define in getattr(self.toolchain, "defines", []):
            flags.append(f"-D{define}")
        for define in project.defines:
            flags.append(f"-D{define}")
        flags.append(f"-D{self.target_profile['define']}")
        if self.is_simulator:
            flags.append("-D__SIMULATOR__")

        if project.symbols:
            flags.append("-g")

        opt = self._EnumValue(project.optimize)
        if opt == "Off":
            flags.append("-O0")
        elif opt == "Size":
            flags.append("-Os")
        elif opt == "Speed":
            flags.append("-O2")
        elif opt == "Full":
            flags.append("-O3")

        warn = self._EnumValue(project.warnings)
        if warn == "All":
            flags.append("-Wall")
        elif warn == "Extra":
            flags.append("-Wextra")
        elif warn == "Everything":
            flags.append("-Weverything")
        elif warn == "Error":
            flags.append("-Werror")

        if project.language.value in ("C++", "Objective-C++"):
            if project.cppdialect:
                flags.append(f"-std={project.cppdialect.lower()}")
            flags.extend(getattr(self.toolchain, "cxxflags", []))
            flags.extend(project.cxxflags)
        else:
            if project.cdialect:
                flags.append(f"-std={project.cdialect.lower()}")
            flags.extend(getattr(self.toolchain, "cflags", []))
            flags.extend(project.cflags)

        return flags

    @staticmethod
    def _EnumValue(v):
        return v.value if hasattr(v, "value") else v

    def BuildProject(self, project: Project) -> bool:
        # TEST_SUITE projects cannot run on iOS — skip compilation and linking entirely.
        if project.kind == ProjectKind.TEST_SUITE:
            return True

        # Récupération de la version minimum depuis le projet
        # On utilise l'attribut approprié si disponible, sinon la valeur par défaut
        min_attr = self.target_profile.get("min_sdk_attr", "iosMinSdk")
        if hasattr(project, min_attr):
            proj_min = getattr(project, min_attr)
            if proj_min:
                self.min_version = str(proj_min)
        # Recalculer target_triple avec la nouvelle version
        self.target_triple = self._GetTargetTriple()

        if Platform.GetHostOS() != TargetOS.MACOS:
            raise RuntimeError(f"{self.target_profile['display']} builds require macOS with Xcode command line tools.")
        return super().BuildProject(project)

    def ExportIPA(self, app_bundle: Path, project: Project) -> Optional[Path]:
        app_bundle = Path(app_bundle)
        if not app_bundle.exists():
            Colored.PrintError(f".app bundle not found: {app_bundle}")
            return None

        app_name = project.targetName or project.name
        output_ipa = app_bundle.parent / f"{app_name}.ipa"

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            payload_dir = tmp / "Payload"
            FileSystem.MakeDirectory(payload_dir)
            bundle_copy = payload_dir / app_bundle.name
            shutil.copytree(app_bundle, bundle_copy, dirs_exist_ok=True)

            zip_path = tmp / f"{app_name}.zip"
            with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                for entry in payload_dir.rglob("*"):
                    zf.write(entry, entry.relative_to(tmp))
            shutil.copy2(zip_path, output_ipa)

        return output_ipa


# Alias for factory compatibility (factory references 'IOSBuilder')
IOSBuilder = DirectIOSBuilder