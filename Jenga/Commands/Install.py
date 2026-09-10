#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Install command.

Modes:
  - Legacy deps scan: jenga install [--update] [--interactive]
  - Toolchain management:
      jenga install toolchain list
      jenga install toolchain detect
      jenga install toolchain install <name> --path <dir_or_archive>
"""

import argparse
import json
import os
import shutil
import tarfile
import zipfile
import urllib.request
from pathlib import Path
from typing import List, Dict, Any, Optional

from ..Utils import Colored, FileSystem, Display, Process
from ..Core.Loader import Loader
from ..Core.Cache import Cache
from ..Core import Api
from ..Core.Toolchains import ToolchainManager
from ..Core.GlobalToolchains import GetJengaRoot, GetGlobalRegistryPath
from ..Core.Platform import Platform
from ..Core.Api import TargetOS


class InstallCommand:
    """jenga install"""

    @staticmethod
    def Execute(args: List[str]) -> int:
        parser = argparse.ArgumentParser(
            prog="jenga install",
            description="Install dependencies or global Jenga toolchains."
        )
        parser.add_argument("--update", action="store_true", help="Force update even if already installed")
        parser.add_argument("--no-cache", action="store_true", help="Ignore cache")
        parser.add_argument("--interactive", "-i", action="store_true", help="Interactive mode")
        parser.add_argument("--jenga-file", help="Path to the workspace .jenga file (default: auto-detected)")

        subparsers = parser.add_subparsers(dest="install_scope")

        toolchain = subparsers.add_parser("toolchain", help="Manage global Jenga toolchains")
        t_sub = toolchain.add_subparsers(dest="toolchain_action", required=True)

        t_sub.add_parser("list", help="List registered global toolchains")
        t_sub.add_parser("detect", help="Detect available toolchains and regenerate importable python config")

        t_install = t_sub.add_parser("install", help="Install/register a toolchain into Jenga .jenga/compilers")
        t_install.add_argument("name", choices=["zig", "emsdk", "android-sdk", "android-ndk", "harmony-sdk", "macos-tools"],
                               help="Toolchain or SDK to install/register")
        t_install.add_argument("--path", help="Path to directory or archive (.zip/.tar.*). If omitted, auto-install is attempted.")
        t_install.add_argument("--version", default="", help="Version for auto-install (zig/ndk/build-tools).")
        t_install.add_argument("--force", action="store_true", help="Overwrite existing local installation")

        parsed = parser.parse_args(args)

        if parsed.install_scope == "toolchain":
            entry_file = InstallCommand._ResolveEntryFile(parsed.jenga_file, required=False)
            return InstallCommand._ExecuteToolchain(parsed, entry_file)

        entry_file = InstallCommand._ResolveEntryFile(parsed.jenga_file, required=True)
        if entry_file is None:
            Colored.PrintError("No .jenga workspace file found.")
            return 1

        return InstallCommand._ExecuteLegacyDependencies(parsed, entry_file, entry_file.parent)

    @staticmethod
    def _ResolveEntryFile(jenga_file: Optional[str], required: bool = True) -> Optional[Path]:
        workspace_root = Path.cwd()
        if jenga_file:
            entry_file = Path(jenga_file).resolve()
            if not entry_file.exists():
                Colored.PrintError(f"Jenga file not found: {entry_file}")
                return None
            return entry_file
        found = FileSystem.FindWorkspaceEntry(workspace_root)
        if found or required:
            return found
        return None

    @staticmethod
    def _ExecuteLegacyDependencies(parsed, entry_file: Path, workspace_root: Path) -> int:
        loader = Loader(verbose=False)
        cache = Cache(entry_file.parent, workspaceName=entry_file.stem)

        if parsed.no_cache:
            cache.Invalidate()
            workspace = loader.LoadWorkspace(str(entry_file))
        else:
            workspace = cache.LoadWorkspace(entry_file, loader)
            if workspace is None:
                workspace = loader.LoadWorkspace(str(entry_file))
                if workspace:
                    cache.SaveWorkspace(workspace, entry_file, loader)

        if workspace is None:
            Colored.PrintError("Failed to load workspace.")
            return 1

        included = Api.getincludedprojects() if hasattr(Api, 'getincludedprojects') else {}

        if not included:
            Colored.PrintInfo("No external dependencies found.")
            return 0

        Colored.PrintInfo(f"Found {len(included)} external dependencies.")

        for name, info in included.items():
            src_file = Path(info.get('file', ''))
            if src_file.exists():
                Colored.PrintSuccess(f"  ✓ {name} ({src_file})")
            else:
                Colored.PrintWarning(f"  ⚠ {name} - missing source file: {src_file}")
                if parsed.interactive:
                    answer = Display.Prompt(f"Download {name}?", default="n")
                    if answer.lower() in ('y', 'yes'):
                        Colored.PrintInfo(f"Downloading {name}...")

        return 0

    @staticmethod
    def _ExecuteToolchain(parsed, entry_file: Optional[Path]) -> int:
        jenga_root = GetJengaRoot()
        registry_path = GetGlobalRegistryPath()
        compilers_root = registry_path.parent / "compilers"
        python_config_path = jenga_root / "Jenga" / "GlobalToolchains.py"

        FileSystem.MakeDirectory(compilers_root)
        FileSystem.MakeDirectory(registry_path.parent)

        registry = InstallCommand._LoadRegistry(registry_path)

        if parsed.toolchain_action == "list":
            return InstallCommand._ListToolchains(registry)

        if parsed.toolchain_action == "detect":
            generated = InstallCommand._DetectAndGenerate(entry_file, python_config_path, registry)
            return 0 if generated else 1

        if parsed.toolchain_action == "install":
            ok = InstallCommand._InstallToolchain(
                name=parsed.name,
                source=Path(parsed.path).resolve() if parsed.path else None,
                compilers_root=compilers_root,
                registry=registry,
                force=parsed.force,
                version=parsed.version or "",
            )
            if not ok:
                return 1
            InstallCommand._SaveRegistry(registry_path, registry)
            generated = InstallCommand._GeneratePythonToolchainsConfig(python_config_path, registry)
            if not generated:
                return 1
            Colored.PrintSuccess(f"Toolchain '{parsed.name}' registered.")
            Colored.PrintInfo(f"Global toolchains file updated: {python_config_path}")
            return 0

        Colored.PrintError("Unknown toolchain action")
        return 1

    @staticmethod
    def _LoadRegistry(path: Path) -> Dict[str, Any]:
        if not path.exists():
            return {"toolchains": [], "sdk": {}}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {"toolchains": [], "sdk": {}}

    @staticmethod
    def _SaveRegistry(path: Path, data: Dict[str, Any]) -> None:
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    @staticmethod
    def _ListToolchains(registry: Dict[str, Any]) -> int:
        toolchains = registry.get("toolchains", [])
        sdk = registry.get("sdk", {})
        if not toolchains and not sdk:
            Colored.PrintInfo("No global toolchains registered in Jenga .jenga/toolchains_registry.json")
            return 0

        Colored.PrintInfo("Registered global toolchains:")
        for tc in toolchains:
            Colored.PrintSuccess(f"  - {tc.get('name')} [{tc.get('compilerFamily')}] -> {tc.get('ccPath')}")
        if sdk:
            Colored.PrintInfo("Registered SDK paths:")
            for key, value in sdk.items():
                Colored.PrintInfo(f"  - {key}: {value}")
        return 0

    @staticmethod
    def _ExtractOrCopy(source: Path, destination: Path, force: bool) -> bool:
        if not source.exists():
            Colored.PrintError(f"Source path does not exist: {source}")
            return False

        if destination.exists():
            if not force:
                Colored.PrintError(f"Destination already exists: {destination}. Use --force to overwrite.")
                return False
            FileSystem.RemoveDirectory(destination, recursive=True, ignoreErrors=True)

        FileSystem.MakeDirectory(destination)

        if source.is_dir():
            for item in source.iterdir():
                target = destination / item.name
                if item.is_dir():
                    shutil.copytree(item, target, dirs_exist_ok=True)
                else:
                    shutil.copy2(item, target)
            return True

        lower = source.name.lower()
        try:
            if lower.endswith(".zip"):
                with zipfile.ZipFile(source, "r") as zf:
                    zf.extractall(destination)
                return True
            if lower.endswith(".tar") or lower.endswith(".tar.gz") or lower.endswith(".tgz") or lower.endswith(".tar.xz"):
                with tarfile.open(source, "r:*") as tf:
                    tf.extractall(destination)
                return True
        except Exception as e:
            Colored.PrintError(f"Failed to extract archive: {e}")
            return False

        Colored.PrintError("Unsupported source format. Use a directory, .zip, or .tar.* archive.")
        return False

    @staticmethod
    def _FindExecutable(root: Path, names: List[str]) -> Optional[Path]:
        candidates = []
        for n in names:
            candidates.append(n)
            if os.name == "nt" and not n.endswith(".exe"):
                candidates.append(f"{n}.exe")
            if os.name == "nt" and not n.endswith(".bat"):
                candidates.append(f"{n}.bat")

        for p in root.rglob("*"):
            if not p.is_file():
                continue
            if p.name in candidates:
                return p
        return None

    @staticmethod
    def _DownloadFile(url: str, destination: Path) -> bool:
        try:
            FileSystem.MakeDirectory(destination.parent)
            urllib.request.urlretrieve(url, str(destination))
            return True
        except Exception as e:
            Colored.PrintError(f"Download failed: {url} ({e})")
            return False

    @staticmethod
    def _AutoInstallZig(compilers_root: Path, version: str) -> Optional[Path]:
        ver = version or "0.13.0"
        host = Platform.GetHostOS()
        if host == TargetOS.WINDOWS:
            filename = f"zig-windows-x86_64-{ver}.zip"
        elif host == TargetOS.MACOS:
            filename = f"zig-macos-x86_64-{ver}.tar.xz"
        else:
            filename = f"zig-linux-x86_64-{ver}.tar.xz"
        url = f"https://ziglang.org/download/{ver}/{filename}"
        archive = compilers_root / "downloads" / filename
        if not InstallCommand._DownloadFile(url, archive):
            return None
        return archive

    @staticmethod
    def _AutoInstallEmsdk(compilers_root: Path) -> Optional[Path]:
        # Archive of emsdk repository (contains installer scripts).
        url = "https://github.com/emscripten-core/emsdk/archive/refs/heads/main.zip"
        archive = compilers_root / "downloads" / "emsdk-main.zip"
        if not InstallCommand._DownloadFile(url, archive):
            return None
        return archive

    @staticmethod
    def _AutoInstallAndroidWithSdkManager(name: str, compilers_root: Path, version: str) -> Optional[Path]:
        sdkmanager = shutil.which("sdkmanager") or shutil.which("sdkmanager.bat")
        if not sdkmanager:
            Colored.PrintError("sdkmanager not found. Provide --path or install Android command-line tools first.")
            return None

        sdk_root = compilers_root / "android" / "sdk"
        FileSystem.MakeDirectory(sdk_root)

        base_packages = [
            "cmdline-tools;latest",
            "platform-tools",
            f"platforms;android-34",
            f"build-tools;{version or '34.0.0'}",
        ]
        ndk_pkg = f"ndk;{version or '27.0.12077973'}"
        packages = base_packages + ([ndk_pkg] if name == "android-ndk" else [])

        cmd = [sdkmanager, f"--sdk_root={sdk_root}"] + packages
        result = Process.ExecuteCommand(cmd, captureOutput=False, silent=False)
        if result.returnCode != 0:
            Colored.PrintError("Android SDK/NDK auto-install failed via sdkmanager.")
            return None

        if name == "android-ndk":
            ndk_dir = sdk_root / "ndk"
            if ndk_dir.exists():
                versions = sorted(ndk_dir.iterdir(), reverse=True)
                if versions:
                    return versions[0]
        return sdk_root

    @staticmethod
    def _CreateZigWrappers(install_dir: Path) -> Dict[str, str]:
        bin_dir = install_dir / "bin"
        FileSystem.MakeDirectory(bin_dir)

        zig = InstallCommand._FindExecutable(install_dir, ["zig"])
        if not zig:
            raise FileNotFoundError("zig executable not found in installed folder")

        if os.name == "nt":
            cc = bin_dir / "zig-cc.bat"
            cxx = bin_dir / "zig-c++.bat"
            ar = bin_dir / "zig-ar.bat"
            cc.write_text(f'@echo off\n"{zig}" cc %*\n', encoding="utf-8")
            cxx.write_text(f'@echo off\n"{zig}" c++ %*\n', encoding="utf-8")
            ar.write_text(f'@echo off\n"{zig}" ar %*\n', encoding="utf-8")
        else:
            cc = bin_dir / "zig-cc"
            cxx = bin_dir / "zig-c++"
            ar = bin_dir / "zig-ar"
            cc.write_text(f'#!/usr/bin/env bash\n"{zig}" cc "$@"\n', encoding="utf-8")
            cxx.write_text(f'#!/usr/bin/env bash\n"{zig}" c++ "$@"\n', encoding="utf-8")
            ar.write_text(f'#!/usr/bin/env bash\n"{zig}" ar "$@"\n', encoding="utf-8")
            cc.chmod(0o755)
            cxx.chmod(0o755)
            ar.chmod(0o755)

        return {
            "cc": str(cc),
            "cxx": str(cxx),
            "ar": str(ar),
            "ld": str(cxx),
            "toolchainDir": str(install_dir),
        }

    @staticmethod
    def _InstallToolchain(name: str, source: Optional[Path], compilers_root: Path,
                          registry: Dict[str, Any], force: bool, version: str = "") -> bool:
        if source is None:
            if name == "zig":
                source = InstallCommand._AutoInstallZig(compilers_root, version)
            elif name == "emsdk":
                source = InstallCommand._AutoInstallEmsdk(compilers_root)
            elif name in ("android-sdk", "android-ndk"):
                auto_path = InstallCommand._AutoInstallAndroidWithSdkManager(name, compilers_root, version)
                if auto_path is None:
                    return False
                source = auto_path
            else:
                Colored.PrintError(f"Auto-install not implemented for '{name}'. Provide --path.")
                return False

        if source is None:
            return False

        target_dir = compilers_root / name
        # sdkmanager already installs in-place; don't copy again.
        if not (name in ("android-sdk", "android-ndk") and source.is_dir() and "android/sdk" in str(source).replace("\\", "/")):
            if not InstallCommand._ExtractOrCopy(source, target_dir, force=force):
                return False
        else:
            target_dir = source

        if name == "zig":
            try:
                wrappers = InstallCommand._CreateZigWrappers(target_dir)
            except Exception as e:
                Colored.PrintError(f"Failed to configure zig wrappers: {e}")
                return False

            # Multi-platform presets from the supplied cross-compilation guides.
            presets = [
                {
                    "name": "zig-linux-x86_64",
                    "compilerFamily": "clang",
                    "targetOs": "Linux",
                    "targetArch": "x86_64",
                    "targetEnv": "gnu",
                    "targetTriple": "x86_64-linux-gnu",
                    "ccPath": wrappers["cc"],
                    "cxxPath": wrappers["cxx"],
                    "arPath": wrappers["ar"],
                    "ldPath": wrappers["ld"],
                    "cflags": ["-target", "x86_64-linux-gnu"],
                    "cxxflags": ["-target", "x86_64-linux-gnu"],
                    "ldflags": ["-target", "x86_64-linux-gnu"],
                },
                {
                    "name": "zig-windows-x86_64",
                    "compilerFamily": "clang",
                    "targetOs": "Windows",
                    "targetArch": "x86_64",
                    "targetEnv": "mingw",
                    "targetTriple": "x86_64-windows-gnu",
                    "ccPath": wrappers["cc"],
                    "cxxPath": wrappers["cxx"],
                    "arPath": wrappers["ar"],
                    "ldPath": wrappers["ld"],
                    "cflags": ["-target", "x86_64-windows-gnu"],
                    "cxxflags": ["-target", "x86_64-windows-gnu"],
                    "ldflags": ["-target", "x86_64-windows-gnu"],
                },
                {
                    "name": "zig-android-arm64",
                    "compilerFamily": "clang",
                    "targetOs": "Android",
                    "targetArch": "arm64",
                    "targetEnv": "android",
                    "targetTriple": "aarch64-linux-android21",
                    "ccPath": wrappers["cc"],
                    "cxxPath": wrappers["cxx"],
                    "arPath": wrappers["ar"],
                    "ldPath": wrappers["ld"],
                    "cflags": ["-target", "aarch64-linux-android21"],
                    "cxxflags": ["-target", "aarch64-linux-android21"],
                    "ldflags": ["-target", "aarch64-linux-android21"],
                },
                {
                    "name": "zig-web-wasm32",
                    "compilerFamily": "clang",
                    "targetOs": "Web",
                    "targetArch": "wasm32",
                    "targetTriple": "wasm32-wasi",
                    "ccPath": wrappers["cc"],
                    "cxxPath": wrappers["cxx"],
                    "arPath": wrappers["ar"],
                    "ldPath": wrappers["ld"],
                    "cflags": ["-target", "wasm32-wasi"],
                    "cxxflags": ["-target", "wasm32-wasi"],
                    "ldflags": ["-target", "wasm32-wasi"],
                },
                {
                    "name": "zig-harmonyos-arm64",
                    "compilerFamily": "clang",
                    "targetOs": "HarmonyOS",
                    "targetArch": "arm64",
                    "targetTriple": "aarch64-linux-ohos",
                    "ccPath": wrappers["cc"],
                    "cxxPath": wrappers["cxx"],
                    "arPath": wrappers["ar"],
                    "ldPath": wrappers["ld"],
                    "cflags": ["-target", "aarch64-linux-ohos"],
                    "cxxflags": ["-target", "aarch64-linux-ohos"],
                    "ldflags": ["-target", "aarch64-linux-ohos"],
                },
            ]
            InstallCommand._UpsertToolchains(registry, presets)
            return True

        if name == "emsdk":
            emcc = InstallCommand._FindExecutable(target_dir, ["emcc"])
            empp = InstallCommand._FindExecutable(target_dir, ["em++"])
            emar = InstallCommand._FindExecutable(target_dir, ["emar"])
            if not emcc or not empp:
                Colored.PrintError("emcc/em++ not found in emsdk directory")
                return False
            InstallCommand._UpsertToolchains(registry, [{
                "name": "emscripten",
                "compilerFamily": "emscripten",
                "targetOs": "Web",
                "targetArch": "wasm32",
                "ccPath": str(emcc),
                "cxxPath": str(empp),
                "arPath": str(emar) if emar else "",
                "toolchainDir": str(target_dir),
            }])
            return True

        if name == "android-sdk":
            registry.setdefault("sdk", {})["androidSdkPath"] = str(target_dir)
            return True

        if name == "android-ndk":
            registry.setdefault("sdk", {})["androidNdkPath"] = str(target_dir)
            # Optional default NDK-based toolchain entry.
            llvm = InstallCommand._FindExecutable(target_dir, ["clang"])
            clangxx = InstallCommand._FindExecutable(target_dir, ["clang++"])
            llvm_ar = InstallCommand._FindExecutable(target_dir, ["llvm-ar"])
            if llvm and clangxx:
                InstallCommand._UpsertToolchains(registry, [{
                    "name": "android-ndk",
                    "compilerFamily": "android-ndk",
                    "targetOs": "Android",
                    "targetArch": "arm64",
                    "targetEnv": "android",
                    "ccPath": str(llvm),
                    "cxxPath": str(clangxx),
                    "arPath": str(llvm_ar) if llvm_ar else "",
                    "toolchainDir": str(target_dir),
                }])
            return True

        if name == "harmony-sdk":
            registry.setdefault("sdk", {})["harmonySdkPath"] = str(target_dir)
            # Symetrique du bloc android-ndk ci-dessus. Sans lui, le SDK est
            # enregistre mais AUCUNE chaine ne l'est, et la construction
            # repond « No suitable toolchain found for HarmonyOS » alors que
            # tout est installe. Le nom doit etre exactement « ohos-ndk » :
            # c'est celui que Core/Builder.py demande dans son prefer.
            harmony_native = target_dir / "native"
            harmony_llvm = harmony_native / "llvm" / "bin"
            harmony_sysroot = harmony_native / "sysroot"
            h_cc = InstallCommand._FindExecutable(harmony_llvm, ["clang"])
            h_cxx = InstallCommand._FindExecutable(harmony_llvm, ["clang++"])
            h_ar = InstallCommand._FindExecutable(harmony_llvm, ["llvm-ar"])
            if h_cc and h_cxx:
                h_triple = "aarch64-linux-ohos"
                h_flags = ["--target=" + h_triple, "-fPIC", "-D__OHOS__"]
                InstallCommand._UpsertToolchains(registry, [{
                    "name": "ohos-ndk",
                    "compilerFamily": "clang",
                    "targetOs": "HarmonyOS",
                    "targetArch": "arm64",
                    "targetTriple": h_triple,
                    "sysroot": str(harmony_sysroot) if harmony_sysroot.exists() else "",
                    "ccPath": str(h_cc),
                    "cxxPath": str(h_cxx),
                    "arPath": str(h_ar) if h_ar else "",
                    "toolchainDir": str(target_dir),
                    "cflags": h_flags,
                    "cxxflags": h_flags,
                    "ldflags": ["--target=" + h_triple],
                }])
            else:
                Colored.PrintError(
                    "SDK HarmonyOS trouve, mais clang/clang++ introuvables "
                    "dans " + str(harmony_llvm))
            return True

        if name == "macos-tools":
            registry.setdefault("sdk", {})["xcodePath"] = str(target_dir)
            return True

        Colored.PrintError(f"Unsupported toolchain name: {name}")
        return False

    @staticmethod
    def _UpsertToolchains(registry: Dict[str, Any], entries: List[Dict[str, Any]]) -> None:
        current = registry.setdefault("toolchains", [])
        by_name = {tc.get("name"): tc for tc in current}
        for entry in entries:
            by_name[entry["name"]] = entry
        registry["toolchains"] = [by_name[k] for k in sorted(by_name.keys())]

    @staticmethod
    def _GeneratePythonToolchainsConfig(path: Path, registry: Dict[str, Any]) -> bool:
        toolchains = registry.get("toolchains", [])
        sdk = registry.get("sdk", {})

        lines: List[str] = []
        lines.append("# Auto-generated by 'jenga install toolchain'.")
        lines.append("# Optional import helper for workspace scripts.")
        lines.append("from Jenga import *")
        lines.append("import os")
        lines.append("import shutil")
        lines.append("")
        lines.append("def _is_valid_exe(path_or_cmd):")
        lines.append("    value = str(path_or_cmd or '').strip()")
        lines.append("    if not value:")
        lines.append("        return False")
        lines.append("    expanded = os.path.expandvars(os.path.expanduser(value))")
        lines.append("    if os.sep in expanded or (os.altsep and os.altsep in expanded) or expanded.startswith('.'):")
        lines.append("        return os.path.exists(expanded)")
        lines.append("    return shutil.which(expanded) is not None")
        lines.append("")
        lines.append("def RegisterJengaGlobalToolchains(options=None):")
        lines.append("    \"\"\"Register toolchains installed in Jenga global registry.\"\"\"")

        if not toolchains and not sdk:
            lines.append("    return")
        else:
            for key, value in sdk.items():
                escaped = value.replace("\\", "\\\\")
                if key == "androidSdkPath":
                    lines.append(f'    androidsdkpath(r"{escaped}")')
                elif key == "androidNdkPath":
                    lines.append(f'    androidndkpath(r"{escaped}")')

            for tc in toolchains:
                name = tc.get("name", "")
                family = tc.get("compilerFamily", "clang")
                guard_checks = []
                if tc.get("ccPath"):
                    guard_checks.append(f'_is_valid_exe(r"{tc["ccPath"]}")')
                if tc.get("cxxPath"):
                    guard_checks.append(f'_is_valid_exe(r"{tc["cxxPath"]}")')
                guard_expr = " and ".join(guard_checks) if guard_checks else "True"
                lines.append(f"    if {guard_expr}:")
                lines.append(f'        with toolchain("{name}", "{family}"):')

                tos = tc.get("targetOs")
                tarch = tc.get("targetArch")
                tenv = tc.get("targetEnv")
                if tos and tarch and tenv:
                    lines.append(f'            settarget("{tos}", "{tarch}", "{tenv}")')
                elif tos and tarch:
                    lines.append(f'            settarget("{tos}", "{tarch}")')

                if tc.get("targetTriple"):
                    lines.append(f'            targettriple(r"{tc["targetTriple"]}")')
                if tc.get("ccPath"):
                    lines.append(f'            ccompiler(r"{tc["ccPath"]}")')
                if tc.get("cxxPath"):
                    lines.append(f'            cppcompiler(r"{tc["cxxPath"]}")')
                if tc.get("ldPath"):
                    lines.append(f'            linker(r"{tc["ldPath"]}")')
                if tc.get("arPath"):
                    lines.append(f'            archiver(r"{tc["arPath"]}")')
                if tc.get("sysroot"):
                    lines.append(f'            sysroot(r"{tc["sysroot"]}")')

                cflags = tc.get("cflags", [])
                cxxflags = tc.get("cxxflags", [])
                ldflags = tc.get("ldflags", [])
                if cflags:
                    lines.append(f"            cflags({json.dumps(cflags)})")
                if cxxflags:
                    lines.append(f"            cxxflags({json.dumps(cxxflags)})")
                if ldflags:
                    lines.append(f"            ldflags({json.dumps(ldflags)})")

        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        Colored.PrintSuccess(f"Generated toolchain config: {path}")
        return True

    @staticmethod
    def _DetectAndGenerate(entry_file: Optional[Path], python_config_path: Path, registry: Dict[str, Any]) -> bool:
        workspace = None
        if entry_file is not None:
            loader = Loader(verbose=False)
            workspace = loader.LoadWorkspace(str(entry_file))
            if workspace is None:
                Colored.PrintWarning("Workspace loading failed, continuing with host/global toolchain detection only")

        tm = ToolchainManager(workspace)
        detected = tm.DetectAll(workspace)
        if not detected:
            Colored.PrintWarning("No toolchain detected")
        else:
            entries: List[Dict[str, Any]] = []
            for _, tc in detected.items():
                entries.append({
                    "name": tc.name,
                    "compilerFamily": tc.compilerFamily.value if hasattr(tc.compilerFamily, "value") else str(tc.compilerFamily),
                    "targetOs": tc.targetOs.value if tc.targetOs else "",
                    "targetArch": tc.targetArch.value if tc.targetArch else "",
                    "targetEnv": tc.targetEnv.value if tc.targetEnv else "",
                    "targetTriple": tc.targetTriple or "",
                    "sysroot": tc.sysroot or "",
                    "ccPath": tc.ccPath or "",
                    "cxxPath": tc.cxxPath or "",
                    "arPath": tc.arPath or "",
                    "ldPath": tc.ldPath or "",
                    "cflags": tc.cflags or [],
                    "cxxflags": tc.cxxflags or [],
                    "ldflags": tc.ldflags or [],
                })
            InstallCommand._UpsertToolchains(registry, entries)

        InstallCommand._SaveRegistry(GetGlobalRegistryPath(), registry)
        return InstallCommand._GeneratePythonToolchainsConfig(python_config_path, registry)
