#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
IosZig Builder — Cross-compilation iOS / tvOS / watchOS depuis Windows/Linux.

ADDITIF et OPT-IN : ne remplace JAMAIS le builder Apple mobile natif (Ios.py,
xcrun/Xcode). Activé par l'option de build `ios-backend=zig`.

Chaîne validée (Windows -> iOS Mach-O) :
  - COMPILE : zig cc/c++ -target <arch>-<os> --sysroot <SDK> -isysroot <SDK>
              -isystem <SDK>/usr/include -F <SDK>/System/Library/Frameworks
  - LINK    : ld.lld -flavor darwin (fourni par le NDK) car `zig cc` ne sait pas
              linker .ios/.tvos/.watchos (libSystem interne conditionné à .macos).
              ld.lld -flavor darwin -arch <arch> -platform_version <plat> <min> <sdk>
                     -syslibroot <SDK> (-dylib|-execute) -o <out> <objs>
                     -framework X ... -lSystem -lc++ -lobjc

Config : ZIG_MACOS/ZIG ; LD64 (defaut ld.lld du NDK) ; IOS_SDK/TVOS_SDK/WATCHOS_SDK
(ou workspace.iosSdkPath/...). REQUIERT un SDK Apple COMPLET (Xcode) avec
usr/lib/{libSystem,libc++,libobjc}.tbd (les SDK theos headers-only ne suffisent pas).
"""

import os
import glob
import re
import shutil
import plistlib
import zipfile
import tempfile
from pathlib import Path
from typing import List, Optional, Dict

from Jenga.Core.Api import Project, ProjectKind, TargetOS
from ...Utils import Process, FileSystem, ProcessResult, Colored
from ..Builder import Builder


class IosZigBuilder(Builder):
    """Builder iOS/tvOS/watchOS via Zig (compile) + ld.lld darwin (link)."""

    allowsCrossCompileFromNonHost = True

    _PROFILES: Dict[object, Dict[str, object]] = {
        TargetOS.IOS:     {"zig_os": "ios",     "ld_plat": "ios",     "arch": "aarch64",
                           "ld_arch": "arm64",    "min": "12.0", "sdk_env": "IOS_SDK",
                           "ws_attr": "iosSdkPath",     "frameworks": ["UIKit", "Foundation"],
                           "define": "IOS"},
        TargetOS.TVOS:    {"zig_os": "tvos",    "ld_plat": "tvos",    "arch": "aarch64",
                           "ld_arch": "arm64",    "min": "12.0", "sdk_env": "TVOS_SDK",
                           "ws_attr": "tvosSdkPath",    "frameworks": ["UIKit", "Foundation"],
                           "define": "TVOS"},
        TargetOS.WATCHOS: {"zig_os": "watchos", "ld_plat": "watchos", "arch": "aarch64",
                           "ld_arch": "arm64_32", "min": "4.0",  "sdk_env": "WATCHOS_SDK",
                           "ws_attr": "watchosSdkPath", "frameworks": ["WatchKit", "Foundation"],
                           "define": "WATCHOS"},
    }

    @staticmethod
    def _EnumValue(v):
        return v.value if hasattr(v, "value") else v

    def _Profile(self) -> Dict[str, object]:
        prof = self._PROFILES.get(self.targetOs)
        if not prof:
            raise RuntimeError(f"IosZig: cible non supportee {self.targetOs}")
        return prof

    def _ZigExe(self) -> str:
        return os.environ.get("ZIG_MACOS") or os.environ.get("ZIG") or "zig"

    def _Ld64(self) -> str:
        ld = os.environ.get("LD64")
        if ld and Path(ld).exists():
            return ld
        ndk = os.environ.get("ANDROID_NDK_HOME") or os.environ.get("ANDROID_NDK_ROOT") or ""
        if ndk:
            cands = glob.glob(str(Path(ndk) / "toolchains" / "llvm" / "prebuilt" / "*" / "bin" / "ld.lld*"))
            cands = [c for c in cands if not c.lower().endswith((".cmd", ".ps1"))]
            if cands:
                return cands[0]
        return "ld.lld"

    def _Sdk(self) -> str:
        prof = self._Profile()
        sdk = os.environ.get(str(prof["sdk_env"]))
        if not sdk:
            sdk = getattr(self.workspace, str(prof["ws_attr"]), "") or ""
        sdk = (sdk or "").strip()
        if not sdk:
            raise RuntimeError(
                f"IosZig: SDK {self.targetOs.value} introuvable. Definir "
                f"{prof['sdk_env']} (ou workspace.{prof['ws_attr']}) vers un SDK "
                "Apple COMPLET (Xcode, avec usr/lib/libSystem.tbd)."
            )
        return sdk

    def _MinVersion(self, project: Project) -> str:
        prof = self._Profile()
        attr = {
            TargetOS.IOS: "iosMinSdk", TargetOS.TVOS: "tvosMinSdk",
            TargetOS.WATCHOS: "watchosMinSdk",
        }.get(self.targetOs, "iosMinSdk")
        v = getattr(project, attr, None)
        return str(v) if v else str(prof["min"])

    def _SdkVersion(self, project: Project) -> str:
        m = re.search(r"(\d+\.\d+)", Path(self._Sdk()).name)
        return m.group(1) if m else self._MinVersion(project)

    def _Triple(self) -> str:
        prof = self._Profile()
        return f'{prof["arch"]}-{prof["zig_os"]}'

    def _AppleCompileFlags(self) -> List[str]:
        sdk = self._Sdk()
        return [
            "--sysroot", sdk,
            "-isysroot", sdk,
            "-isystem", str(Path(sdk) / "usr" / "include"),
            "-F", str(Path(sdk) / "System" / "Library" / "Frameworks"),
        ]

    def GetObjectExtension(self) -> str:
        return ".o"

    def GetOutputExtension(self, project: Project) -> str:
        if project.kind == ProjectKind.STATIC_LIB:
            return ".a"
        if project.kind == ProjectKind.SHARED_LIB:
            return ".dylib"
        return ""

    def GetModuleFlags(self, project: Project, sourceFile: str) -> List[str]:
        if not self.IsModuleFile(sourceFile):
            return []
        return ["-fmodules", "-fcxx-modules"]

    @staticmethod
    def _IsCppSource(project: Project, src: Path) -> bool:
        if project.language.value in ("C++", "Objective-C++"):
            return True
        return src.suffix.lower() in (".cpp", ".cc", ".cxx", ".c++", ".mm")

    def _NeedsObjectiveCppMode(self, src: Path) -> bool:
        """Un .cpp qui inclut le point d'entree UIKit (NkMain.h) ou des en-tetes
        Apple doit etre compile en Objective-C++ (sinon les macros CF_ENUM des
        en-tetes Foundation echouent en mode C++ pur). Les .mm/.m sont deja ObjC."""
        ext = src.suffix.lower()
        if ext in (".mm", ".m"):
            return True
        if ext not in (".cpp", ".cc", ".cxx", ".c++", ".cp"):
            return False
        try:
            content = src.read_text(encoding="utf-8", errors="ignore").lower()
        except Exception:  # noqa: BLE001
            return False
        if ("nkmain.h" in content
                or "#import" in content):
            return True
        # En-tetes parapluie de frameworks Apple qui tirent des types Objective-C
        # (NS_ENUM/NSInteger/CF_ENUM) : un .cpp qui les inclut doit passer en
        # Objective-C++, sinon erreurs "non-defining declaration of enumeration"
        # ou macros CF_ENUM en echec (ex. NKAudio <AudioToolbox/AudioToolbox.h>).
        _APPLE_OBJC_HEADERS = (
            "uikit/", "foundation/", "cocoa/", "appkit/", "audiotoolbox/",
            "coreaudio/", "audiounit/", "avfoundation/", "coremedia/",
            "corevideo/", "coreimage/", "coretext/", "coreanimation/",
            "quartzcore/", "metalkit/", "gamecontroller/", "coremotion/",
            "corelocation/", "photos/", "avkit/", "spritekit/", "scenekit/",
        )
        return any(h in content for h in _APPLE_OBJC_HEADERS)

    @staticmethod
    def _IsDirectLibPath(lib: str) -> bool:
        p = Path(lib)
        return p.suffix in (".a", ".dylib", ".tbd", ".framework") or "/" in lib or "\\" in lib or p.is_absolute()

    def Compile(self, project: Project, sourceFile: str, objectFile: str) -> ProcessResult:
        src = Path(sourceFile)
        obj = Path(objectFile)
        FileSystem.MakeDirectory(obj.parent)
        lang_cmd = "c++" if self._IsCppSource(project, src) else "cc"
        args = [self._ZigExe(), lang_cmd, "-target", self._Triple()]
        args.extend(self._AppleCompileFlags())
        # .cpp incluant du code UIKit/Foundation -> forcer Objective-C++.
        if self._NeedsObjectiveCppMode(src) and src.suffix.lower() not in (".mm", ".m"):
            args.extend(["-x", "objective-c++"])
        args.extend(["-c", str(src), "-o", str(obj)])
        args.extend(self._GetCompilerFlags(project))
        result = Process.ExecuteCommand(args, captureOutput=True, silent=False)
        self._lastResult = result
        return result

    def Link(self, project: Project, objectFiles: List[str], outputFile: str) -> bool:
        out = Path(outputFile)
        FileSystem.MakeDirectory(out.parent)

        if project.kind == ProjectKind.STATIC_LIB:
            args = [self._ZigExe(), "ar", "rcs", str(out)]
            args.extend(objectFiles)
            result = Process.ExecuteCommand(args, captureOutput=True, silent=False)
            self._lastResult = result
            return result.returnCode == 0

        prof = self._Profile()
        sdk = self._Sdk()
        min_v = self._MinVersion(project)
        sdk_v = self._SdkVersion(project)
        exe_out = out if project.kind == ProjectKind.SHARED_LIB else (out.parent / (project.targetName or project.name))

        args = [
            self._Ld64(), "-flavor", "darwin",
            "-arch", str(prof["ld_arch"]),
            "-platform_version", str(prof["ld_plat"]), min_v, sdk_v,
            "-syslibroot", sdk,
            "-o", str(exe_out),
        ]
        args.append("-dylib" if project.kind == ProjectKind.SHARED_LIB else "-execute")
        args.extend(objectFiles)

        default_fw = list(prof["frameworks"]) + ["CoreGraphics", "QuartzCore", "Metal"]
        tc_fw = list(getattr(self.toolchain, "frameworks", []) or [])
        seen = set()
        for fw in default_fw + tc_fw + list(project.frameworks or []):
            if fw and fw not in seen:
                seen.add(fw)
                args.extend(["-framework", fw])

        for libdir in project.libDirs:
            args.append(f"-L{self.ResolveProjectPath(project, libdir)}")
        for lib in project.links:
            if self._IsDirectLibPath(lib):
                args.append(self.ResolveProjectPath(project, lib))
            else:
                args.append(f"-l{lib}")

        # libc++ : la libc++.tbd d'un vieux SDK iOS ne matche pas les en-têtes
        # libc++ de Zig (v19). On lie donc une libc++/libc++abi de Zig re-taggée
        # pour la plateforme iOS (voir scripts/make_ios_libcxx.py) si disponible,
        # sinon on retombe sur la libc++ du SDK (-lc++).
        libcpp_dir = os.environ.get("IOS_LIBCPP_DIR") or r"C:\apple-sdks\libcxx-ios"
        libcpp_a = Path(libcpp_dir) / "libc++.a"
        if libcpp_a.exists():
            args.append(str(libcpp_a))
            abi = Path(libcpp_dir) / "libc++abi.a"
            if abi.exists():
                args.append(str(abi))
            compat = Path(libcpp_dir) / "ios_compat.o"
            if compat.exists():
                args.append(str(compat))
            args.extend(["-lSystem", "-lobjc"])
        else:
            args.extend(["-lSystem", "-lc++", "-lobjc"])

        result = Process.ExecuteCommand(args, captureOutput=True, silent=False)
        self._lastResult = result
        if result.returnCode != 0:
            return False

        if project.kind in (ProjectKind.CONSOLE_APP, ProjectKind.WINDOWED_APP):
            app = self._CreateAppBundle(project, exe_out)
            if app:
                self._MaybeCodesign(app)
                self._ExportIPA(project, app)
        return True

    def _MaybeCodesign(self, app_bundle: Path) -> None:
        """Signature opt-in du .app via rcodesign (tourne sous Windows).
        Activée par l'env IOS_SIGN :
          - IOS_SIGN=adhoc        -> signature ad-hoc (local/dev)
          - IOS_SIGN=<chemin.p12> -> certificat Apple (+ IOS_SIGN_PASS)
        rcodesign : env RCODESIGN ou sur le PATH. Non signé si IOS_SIGN absent."""
        mode = (os.environ.get("IOS_SIGN") or "").strip()
        if not mode:
            return
        rc = os.environ.get("RCODESIGN") or shutil.which("rcodesign")
        if not rc:
            Colored.PrintWarning("[ios-zig] IOS_SIGN défini mais rcodesign introuvable (env RCODESIGN).")
            return
        args = [rc, "sign"]
        if mode.lower() != "adhoc":
            args += ["--p12-file", mode]
            pw = os.environ.get("IOS_SIGN_PASS")
            if pw:
                args += ["--p12-password", pw]
            prov = os.environ.get("IOS_PROVISION")
            if prov:
                args += ["--provisioning-profile", prov]
        args.append(str(app_bundle))
        result = Process.ExecuteCommand(args, captureOutput=True, silent=False)
        if result.returnCode == 0:
            Colored.PrintInfo(f"[ios-zig] signé ({'ad-hoc' if mode.lower()=='adhoc' else 'p12'}) : {app_bundle.name}")
        else:
            Colored.PrintWarning(f"[ios-zig] échec signature : {app_bundle.name}")

    def _CreateAppBundle(self, project: Project, executable: Path) -> Optional[Path]:
        app_name = project.targetName or project.name
        bundle = executable.parent / f"{app_name}.app"
        FileSystem.RemoveDirectory(bundle, recursive=True, ignoreErrors=True)
        FileSystem.MakeDirectory(bundle)
        try:
            shutil.copy2(str(executable), str(bundle / app_name))
        except Exception as e:  # noqa: BLE001
            Colored.PrintWarning(f"[ios-zig] copie exe -> bundle echouee : {e}")
            return None

        prof = self._Profile()
        bundle_id = getattr(project, "iosBundleId", "") or f"com.jenga.{project.name.lower()}"
        plist = {
            "CFBundleName": app_name,
            "CFBundleDisplayName": app_name,
            "CFBundleIdentifier": bundle_id,
            "CFBundleExecutable": app_name,
            "CFBundleVersion": getattr(project, "iosBuildNumber", "") or "1",
            "CFBundleShortVersionString": getattr(project, "iosVersion", "") or getattr(project, "appVersion", "") or "1.0",
            "CFBundlePackageType": "APPL",
            "CFBundleInfoDictionaryVersion": "6.0",
            "MinimumOSVersion": self._MinVersion(project),
            "CFBundleSupportedPlatforms": ["iPhoneOS" if self.targetOs == TargetOS.IOS else str(prof["ld_plat"])],
            "UIDeviceFamily": [1, 2] if self.targetOs == TargetOS.IOS else [3],
        }
        if self.targetOs == TargetOS.IOS:
            plist["LSRequiresIPhoneOS"] = True
            plist["UISupportedInterfaceOrientations"] = [
                "UIInterfaceOrientationPortrait",
                "UIInterfaceOrientationLandscapeLeft",
                "UIInterfaceOrientationLandscapeRight",
            ]
        try:
            with open(bundle / "Info.plist", "wb") as f:
                plistlib.dump(plist, f)
        except Exception as e:  # noqa: BLE001
            Colored.PrintWarning(f"[ios-zig] Info.plist echoue : {e}")
            return None

        Colored.PrintInfo(f"[ios-zig] bundle .app cree : {bundle.name}")
        return bundle

    def _ExportIPA(self, project: Project, app_bundle: Path) -> Optional[Path]:
        app_name = project.targetName or project.name
        ipa = app_bundle.parent / f"{app_name}.ipa"
        try:
            with tempfile.TemporaryDirectory() as tmp:
                payload = Path(tmp) / "Payload"
                FileSystem.MakeDirectory(payload)
                shutil.copytree(app_bundle, payload / app_bundle.name, dirs_exist_ok=True)
                with zipfile.ZipFile(ipa, "w", zipfile.ZIP_DEFLATED) as zf:
                    for entry in payload.rglob("*"):
                        zf.write(entry, entry.relative_to(tmp))
            Colored.PrintInfo(f"[ios-zig] .ipa (non signe) : {ipa.name}")
            return ipa
        except Exception as e:  # noqa: BLE001
            Colored.PrintWarning(f"[ios-zig] export .ipa echoue : {e}")
            return None

    def _GetCompilerFlags(self, project: Project) -> List[str]:
        flags: List[str] = []
        prof = self._Profile()
        for inc in project.includeDirs:
            flags.append(f"-I{self.ResolveProjectPath(project, inc)}")
        for define in getattr(self.toolchain, "defines", []) or []:
            flags.append(f"-D{define}")
        for define in project.defines:
            flags.append(f"-D{define}")
        flags.append(f"-D{prof['define']}")
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
        if project.language.value in ("C++", "Objective-C++"):
            if project.cppdialect:
                flags.append(f"-std={project.cppdialect.lower()}")
            flags.extend(getattr(self.toolchain, "cxxflags", []) or [])
            flags.extend(project.cxxflags)
        else:
            if project.cdialect:
                flags.append(f"-std={project.cdialect.lower()}")
            flags.extend(getattr(self.toolchain, "cflags", []) or [])
            flags.extend(project.cflags)
        return flags
