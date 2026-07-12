#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MacosZig Builder — Cross-compilation macOS depuis Windows/Linux via Zig.

ADDITIF et OPT-IN : ne remplace JAMAIS MacOSBuilder (build natif Xcode/clang sur
un vrai Mac). Activé uniquement par l'option de build `macos-backend=zig`.

Recette validée (zig 0.13.0 + SDK macOS) :
    zig cc/c++ -target <arch>-macos --sysroot <SDK> -isysroot <SDK>
               -isystem <SDK>/usr/include -F <SDK>/System/Library/Frameworks
               -framework X ...
Les .mm sont détectés automatiquement comme Objective-C++ par clang (extension).

Configuration (priorité décroissante) :
    - env  ZIG_MACOS : chemin de l'exécutable zig (défaut : 'zig' du PATH)
    - env  MACOS_SDK : chemin du SDK macOS (sysroot)   [ou workspace.macosSdkPath]
    - arch : depuis targetArch (aarch64 / x86_64)

Note : ce builder ignore le compilateur de la toolchain sélectionnée (ex.
'clang-native') et force zig — c'est ce qui permet de garder le .jenga natif
inchangé tout en cross-compilant depuis Windows.
"""

import os
import shlex
import shutil
import plistlib
from pathlib import Path
from typing import List, Optional

from Jenga.Core.Api import Project, ProjectKind, TargetArch
from ...Utils import Process, FileSystem, ProcessResult, Colored
from ..Builder import Builder


class MacosZigBuilder(Builder):
    """Builder macOS via Zig (cross depuis Windows/Linux)."""

    # Autorise la cross-compilation macOS depuis un hote non-macOS.
    allowsCrossCompileFromNonHost = True

    # -----------------------------------------------------------------------
    # Résolution de la configuration (zig / SDK / triple)
    # -----------------------------------------------------------------------

    @staticmethod
    def _EnumValue(v):
        return v.value if hasattr(v, "value") else v

    def _ZigExe(self) -> str:
        return os.environ.get("ZIG_MACOS") or os.environ.get("ZIG") or "zig"

    def _Sdk(self) -> Optional[str]:
        sdk = os.environ.get("MACOS_SDK")
        if not sdk:
            sdk = getattr(self.workspace, "macosSdkPath", "") or ""
        sdk = (sdk or "").strip()
        return sdk or None

    def _Arch(self) -> str:
        env_arch = (os.environ.get("MACOS_ARCH") or "").strip().lower()
        if env_arch in ("aarch64", "arm64"):
            return "aarch64"
        if env_arch in ("x86_64", "x64"):
            return "x86_64"
        return "aarch64" if self.targetArch == TargetArch.ARM64 else "x86_64"

    def _Triple(self) -> str:
        return f"{self._Arch()}-macos"

    def _AppleFlags(self) -> List[str]:
        sdk = self._Sdk()
        if not sdk:
            raise RuntimeError(
                "MacosZig: SDK macOS introuvable. Definir MACOS_SDK (ou "
                "workspace.macosSdkPath), ex. C:\\apple-sdks\\MacOSX11.3.sdk"
            )
        frameworks = str(Path(sdk) / "System" / "Library" / "Frameworks")
        usr_include = str(Path(sdk) / "usr" / "include")
        return [
            "--sysroot", sdk,
            "-isysroot", sdk,
            "-isystem", usr_include,
            "-F", frameworks,
        ]

    # -----------------------------------------------------------------------
    # Extensions
    # -----------------------------------------------------------------------

    def GetObjectExtension(self) -> str:
        return ".o"

    def GetOutputExtension(self, project: Project) -> str:
        if project.kind == ProjectKind.STATIC_LIB:
            return ".a"
        if project.kind == ProjectKind.SHARED_LIB:
            return ".dylib"
        return ""  # exécutable Unix

    def GetModuleFlags(self, project: Project, sourceFile: str) -> List[str]:
        if not self.IsModuleFile(sourceFile):
            return []
        return ["-fmodules", "-fcxx-modules"]

    @staticmethod
    def _IsDirectLibPath(lib: str) -> bool:
        p = Path(lib)
        return p.suffix in (".a", ".dylib", ".so", ".framework") or "/" in lib or "\\" in lib or p.is_absolute()

    @staticmethod
    def _IsCppSource(project: Project, src: Path) -> bool:
        if project.language.value in ("C++", "Objective-C++"):
            return True
        return src.suffix.lower() in (".cpp", ".cc", ".cxx", ".c++", ".mm")

    # -----------------------------------------------------------------------
    # Compilation / Link
    # -----------------------------------------------------------------------

    def Compile(self, project: Project, sourceFile: str, objectFile: str) -> ProcessResult:
        src = Path(sourceFile)
        obj = Path(objectFile)
        FileSystem.MakeDirectory(obj.parent)

        lang_cmd = "c++" if self._IsCppSource(project, src) else "cc"
        args = [self._ZigExe(), lang_cmd, "-target", self._Triple()]
        args.extend(self._AppleFlags())
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

        args = [self._ZigExe(), "c++", "-target", self._Triple()]
        args.extend(self._AppleFlags())
        if project.kind == ProjectKind.SHARED_LIB:
            args.append("-dynamiclib")
        args.extend(objectFiles)
        args.extend(["-o", str(out)])

        # Frameworks (toolchain puis projet)
        tc_frameworks = list(getattr(self.toolchain, "frameworks", []) or [])
        for fw in tc_frameworks:
            args.extend(["-framework", fw])
        for fw in project.frameworks:
            args.extend(["-framework", fw])

        # Frameworks Apple par défaut (parité MacOSBuilder) pour les apps/tests :
        # résout le runtime Objective-C + les APIs Cocoa/Metal courantes même
        # quand le .jenga ne déclare pas explicitement de frameworks (la DSL
        # frameworks() étant un no-op hors 'with toolchain()').
        if project.kind in (ProjectKind.CONSOLE_APP, ProjectKind.WINDOWED_APP, ProjectKind.TEST_SUITE):
            default_frameworks = [
                "Cocoa", "QuartzCore", "CoreGraphics",
                "GameController", "AVFoundation", "CoreMedia", "CoreVideo",
            ]
            already = set(tc_frameworks) | set(project.frameworks or [])
            for fw in default_frameworks:
                if fw not in already:
                    args.extend(["-framework", fw])

        # Répertoires de libs
        for libdir in project.libDirs:
            args.append(f"-L{self.ResolveProjectPath(project, libdir)}")
        # Libs
        for lib in project.links:
            if self._IsDirectLibPath(lib):
                args.append(self.ResolveProjectPath(project, lib))
            else:
                args.append(f"-l{lib}")

        # rpath standard
        args.append("-Wl,-rpath,@loader_path")
        args.extend(self._GetLinkerFlags(project))

        result = Process.ExecuteCommand(args, captureOutput=True, silent=False)
        self._lastResult = result
        if result.returnCode != 0:
            return False

        # Bundle .app pour les apps fenêtrées : Contents/{MacOS/<exe>, Info.plist,
        # Resources/}. L'exécutable standalone reste dispo (workflows CLI/run).
        if project.kind == ProjectKind.WINDOWED_APP:
            self._CreateAppBundle(project, out)
        return True

    # -----------------------------------------------------------------------
    # Bundle .app (macOS)
    # -----------------------------------------------------------------------

    def _CreateAppBundle(self, project: Project, exe_path: Path) -> Optional[Path]:
        app_name = project.targetName or project.name
        bundle = exe_path.parent / f"{app_name}.app"
        macos_dir = bundle / "Contents" / "MacOS"
        res_dir = bundle / "Contents" / "Resources"
        FileSystem.MakeDirectory(macos_dir)
        FileSystem.MakeDirectory(res_dir)

        try:
            shutil.copy2(str(exe_path), str(macos_dir / exe_path.name))
        except Exception as e:  # noqa: BLE001
            Colored.PrintWarning(f"[macos-zig] copie exe -> bundle echouee : {e}")
            return None

        plist = {
            "CFBundleExecutable":         exe_path.name,
            "CFBundleIdentifier":         (getattr(project, "macosBundleId", "")
                                           or getattr(project, "iosBundleId", "")
                                           or f"com.jenga.{project.name.lower()}"),
            "CFBundleName":               app_name,
            "CFBundleDisplayName":        app_name,
            "CFBundlePackageType":        "APPL",
            "CFBundleShortVersionString": getattr(project, "appVersion", "") or "1.0",
            "CFBundleVersion":            "1",
            "CFBundleInfoDictionaryVersion": "6.0",
            "LSMinimumSystemVersion":     "11.0",
            "NSHighResolutionCapable":    True,
        }

        # Icone : copie directe si une .icns est fournie (pas de conversion PNG
        # ici pour rester sans dependance Pillow ; MacOSBuilder gere la conversion).
        icon = getattr(project, "appIcon", "") or getattr(project, "icon", "") or ""
        if icon:
            icon_path = Path(self.ResolveProjectPath(project, icon))
            if icon_path.exists() and icon_path.suffix.lower() == ".icns":
                try:
                    shutil.copy2(str(icon_path), str(res_dir / "AppIcon.icns"))
                    plist["CFBundleIconFile"] = "AppIcon"
                except Exception:
                    pass

        try:
            with open(bundle / "Contents" / "Info.plist", "wb") as f:
                plistlib.dump(plist, f)
        except Exception as e:  # noqa: BLE001
            Colored.PrintWarning(f"[macos-zig] ecriture Info.plist echouee : {e}")
            return None

        Colored.PrintInfo(f"[macos-zig] bundle .app cree : {bundle.name}")
        return bundle

    # -----------------------------------------------------------------------
    # Flags
    # -----------------------------------------------------------------------

    def _GetCompilerFlags(self, project: Project) -> List[str]:
        flags: List[str] = []

        for inc in project.includeDirs:
            flags.append(f"-I{self.ResolveProjectPath(project, inc)}")

        for define in getattr(self.toolchain, "defines", []) or []:
            flags.append(f"-D{define}")
        for define in project.defines:
            flags.append(f"-D{define}")

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
        elif warn == "Error":
            flags.append("-Werror")

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

        if project.kind == ProjectKind.SHARED_LIB:
            flags.append("-fPIC")

        return flags

    def _GetLinkerFlags(self, project: Project) -> List[str]:
        flags: List[str] = []
        for f in project.ldflags:
            if isinstance(f, str):
                flags.extend(shlex.split(f))
            else:
                flags.append(str(f))
        for f in getattr(self.toolchain, "ldflags", []) or []:
            if f in ("c++", "cc"):
                continue
            if isinstance(f, str):
                flags.extend(shlex.split(f))
            else:
                flags.append(str(f))
        return flags
