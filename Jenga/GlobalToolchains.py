#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Global toolchain registration helpers.

This module exposes explicit `Toolchain*` functions that register default
toolchains by platform/path, plus one aggregator:
`RegisterJengaGlobalToolchains()`.
"""

from __future__ import annotations

import os
import platform as host_platform
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Sequence

from Jenga.Utils.FastWhich import Which as _which
from Jenga.Core.Api import (
	androidndkpath,
	androidsdkpath,
	archiver,
	ccompiler,
	cflags,
	cppcompiler,
	cxxflags,
	getcurrentworkspace,
	javajdkpath,
	ldflags,
	linker,
	settarget,
	sysroot,
	targettriple,
	toolchain,
)
from Jenga.Core.GlobalToolchains import LoadGlobalRegistry
from Jenga.Core.Toolchains import ToolchainManager


def _expand_path(path_value: str) -> str:
	return os.path.expandvars(os.path.expanduser(str(path_value or "").strip()))


def _is_executable(path_or_cmd: str) -> bool:
	value = _expand_path(path_or_cmd)
	if not value:
		return False

	candidate = Path(value)
	has_sep = (os.sep and os.sep in value) or (os.altsep and os.altsep in value)
	if has_sep or candidate.is_absolute() or value.startswith("."):
		return candidate.exists()

	return _which(value) is not None


def _first_existing_dir(paths: Sequence[str]) -> str:
	for value in paths:
		expanded = _expand_path(value)
		if expanded and Path(expanded).is_dir():
			return expanded
	return ""


def _first_executable(*, commands: Sequence[str] = (), paths: Sequence[str] = ()) -> str:
	for value in paths:
		expanded = _expand_path(value)
		if expanded and Path(expanded).exists():
			return expanded

	for command in commands:
		cmd = str(command or "").strip()
		if not cmd:
			continue
		resolved = _which(cmd)
		if resolved:
			return resolved

	return ""


def _to_list(values: Iterable[Any]) -> list[str]:
	return [str(v) for v in (values or []) if str(v).strip()]


def _workspace_has_toolchain(name: str) -> bool:
	workspace = getcurrentworkspace()
	return bool(workspace and name in workspace.toolchains)


def _host_os_name() -> str:
	system = host_platform.system().lower()
	if system == "windows":
		return "Windows"
	if system == "darwin":
		return "macOS"
	if system == "linux":
		return "Linux"
	return "Linux"


def _host_arch_name() -> str:
	machine = host_platform.machine().lower()
	if machine in ("x86_64", "amd64"):
		return "x86_64"
	if machine in ("arm64", "aarch64"):
		return "arm64"
	if machine.startswith("arm"):
		return "arm"
	if machine in ("x86", "i386", "i686"):
		return "x86"
	if machine in ("wasm32",):
		return "wasm32"
	return "x86_64"


def _host_env_name() -> str:
	host_os = _host_os_name()
	if host_os == "Windows":
		return "mingw"
	if host_os == "Linux":
		return "gnu"
	return ""


def _is_apple_clang(compiler_path: str) -> bool:
	if not compiler_path:
		return False
	try:
		result = subprocess.run(
			[compiler_path, "--version"],
			check=False,
			capture_output=True,
			text=True,
			encoding="utf-8",
			errors="ignore",
		)
		output = f"{result.stdout}\n{result.stderr}".lower()
		return "apple clang" in output or "apple llvm" in output
	except Exception:
		return False


def _find_latest_subdir(root_path: str) -> str:
	root = Path(_expand_path(root_path))
	if not root.exists() or not root.is_dir():
		return ""

	children = sorted((p for p in root.iterdir() if p.is_dir()), key=lambda p: p.name, reverse=True)
	if not children:
		return ""
	return str(children[0])


def _find_emsdk_root(options: Dict[str, Any], registry: Dict[str, Any]) -> str:
	candidates = [
		options.get("emsdk_root", ""),
		options.get("emsdkRoot", ""),
		os.getenv("EMSDK", ""),
		registry.get("sdk", {}).get("emsdkPath", ""),
	]
	if os.name == "nt":
		candidates.extend([r"C:\emsdk", r"%USERPROFILE%\emsdk"])
	elif host_platform.system().lower() == "darwin":
		candidates.extend(["~/emsdk", "/opt/emsdk"])
	else:
		candidates.extend(["~/emsdk", "/opt/emsdk"])
	return _first_existing_dir(candidates)


def _find_android_sdk_root(options: Dict[str, Any], registry: Dict[str, Any]) -> str:
	candidates = [
		options.get("android_sdk_root", ""),
		options.get("androidSdkPath", ""),
		registry.get("sdk", {}).get("androidSdkPath", ""),
		os.getenv("ANDROID_SDK_ROOT", ""),
		os.getenv("ANDROID_HOME", ""),
	]
	if os.name == "nt":
		candidates.extend([r"%LOCALAPPDATA%\Android\Sdk", r"C:\Android\Sdk"])
	elif host_platform.system().lower() == "darwin":
		candidates.extend(["~/Library/Android/sdk", "/opt/android-sdk"])
	else:
		candidates.extend(["~/Android/Sdk", "/opt/android-sdk", "/usr/lib/android-sdk"])
	return _first_existing_dir(candidates)


def _find_android_ndk_root(options: Dict[str, Any], registry: Dict[str, Any], sdk_root: str = "") -> str:
	candidates = [
		options.get("android_ndk_root", ""),
		options.get("androidNdkPath", ""),
		registry.get("sdk", {}).get("androidNdkPath", ""),
		os.getenv("ANDROID_NDK_ROOT", ""),
		os.getenv("ANDROID_NDK_HOME", ""),
	]

	if sdk_root:
		sdk_ndk_dir = Path(sdk_root) / "ndk"
		if sdk_ndk_dir.exists():
			candidates.append(_find_latest_subdir(str(sdk_ndk_dir)))
		candidates.append(str(Path(sdk_root) / "ndk-bundle"))

	if os.name == "nt":
		candidates.extend([r"%LOCALAPPDATA%\Android\Sdk\ndk-bundle", r"C:\Android\Sdk\ndk-bundle"])
	elif host_platform.system().lower() == "darwin":
		candidates.extend(["~/Library/Android/sdk/ndk-bundle", "~/Library/Android/sdk/ndk"])
	else:
		candidates.extend(["~/Android/Sdk/ndk-bundle", "~/Android/Sdk/ndk", "/opt/android-sdk/ndk"])

	expanded = [_expand_path(v) for v in candidates if str(v or "").strip()]
	for candidate in expanded:
		path = Path(candidate)
		if path.is_dir() and (path / "toolchains" / "llvm").exists():
			return str(path)
		if path.is_dir() and path.name.lower() == "ndk":
			latest = _find_latest_subdir(str(path))
			if latest:
				latest_path = Path(latest)
				if (latest_path / "toolchains" / "llvm").exists():
					return str(latest_path)
	return ""


def _find_jdk_root(options: Dict[str, Any]) -> str:
	direct_candidates = [
		options.get("java_jdk_root", ""),
		options.get("javaJdkPath", ""),
		options.get("jdk_root", ""),
		options.get("jdkPath", ""),
		os.getenv("JAVA_HOME", ""),
		os.getenv("JDK_HOME", ""),
	]

	for candidate in direct_candidates:
		root = _expand_path(candidate)
		if not root:
			continue
		javac = Path(root) / "bin" / ("javac.exe" if os.name == "nt" else "javac")
		if javac.exists():
			return root

	javac_from_path = _which("javac")
	if javac_from_path:
		javac_path = Path(javac_from_path).resolve()
		if javac_path.parent.name.lower() == "bin":
			return str(javac_path.parent.parent)

	roots: list[str] = []
	if os.name == "nt":
		roots.extend([r"C:\Program Files\Java", r"C:\Program Files\Eclipse Adoptium", r"C:\Program Files\Microsoft"])
	elif host_platform.system().lower() == "darwin":
		roots.append("/Library/Java/JavaVirtualMachines")
	else:
		roots.append("/usr/lib/jvm")

	for root in roots:
		base = Path(_expand_path(root))
		if not base.exists() or not base.is_dir():
			continue

		if host_platform.system().lower() == "darwin":
			homes = sorted((p / "Contents" / "Home" for p in base.iterdir() if p.is_dir()), reverse=True)
			for home in homes:
				javac = home / "bin" / "javac"
				if javac.exists():
					return str(home)
		else:
			for child in sorted((p for p in base.iterdir() if p.is_dir()), key=lambda p: p.name, reverse=True):
				javac = child / "bin" / ("javac.exe" if os.name == "nt" else "javac")
				if javac.exists():
					return str(child)
	return ""


def _register_entry(entry: Dict[str, Any]) -> bool:
	name = str(entry.get("name", "")).strip()
	family = str(entry.get("compilerFamily", "clang")).strip().lower()
	if not name or _workspace_has_toolchain(name):
		return False

	cc = str(entry.get("ccPath", "")).strip()
	cxx = str(entry.get("cxxPath", "")).strip()
	ld = str(entry.get("ldPath", "")).strip()
	ar = str(entry.get("arPath", "")).strip()

	if not cc and cxx:
		cc = cxx
	if not cxx and cc:
		cxx = cc

	if not cc and not cxx:
		return False
	if cc and not _is_executable(cc):
		return False
	if cxx and not _is_executable(cxx):
		return False
	if ld and not _is_executable(ld):
		ld = ""
	if ar and not _is_executable(ar):
		ar = ""

	with toolchain(name, family):
		target_os = str(entry.get("targetOs", "")).strip()
		target_arch = str(entry.get("targetArch", "")).strip()
		target_env = str(entry.get("targetEnv", "")).strip()

		if target_os and target_arch and target_env:
			settarget(target_os, target_arch, target_env)
		elif target_os and target_arch:
			settarget(target_os, target_arch)

		target_triple = str(entry.get("targetTriple", "")).strip()
		if target_triple:
			targettriple(target_triple)

		sys_root = str(entry.get("sysroot", "")).strip()
		if sys_root:
			sysroot(sys_root)

		if cc:
			ccompiler(cc)
		if cxx:
			cppcompiler(cxx)
		if ld:
			linker(ld)
		if ar:
			archiver(ar)

		cflag_values = _to_list(entry.get("cflags", []))
		if cflag_values:
			cflags(cflag_values)

		cxxflag_values = _to_list(entry.get("cxxflags", []))
		if cxxflag_values:
			cxxflags(cxxflag_values)

		ldflag_values = _to_list(entry.get("ldflags", []))
		if ldflag_values:
			ldflags(ldflag_values)

	return True


def _entry_from_toolchain(tc: Any) -> Dict[str, Any]:
	return {
		"name": tc.name,
		"compilerFamily": tc.compilerFamily.value if getattr(tc, "compilerFamily", None) else "clang",
		"targetOs": tc.targetOs.value if getattr(tc, "targetOs", None) else "",
		"targetArch": tc.targetArch.value if getattr(tc, "targetArch", None) else "",
		"targetEnv": tc.targetEnv.value if getattr(tc, "targetEnv", None) else "",
		"targetTriple": tc.targetTriple or "",
		"sysroot": tc.sysroot or "",
		"ccPath": tc.ccPath or "",
		"cxxPath": tc.cxxPath or "",
		"ldPath": tc.ldPath or "",
		"arPath": tc.arPath or "",
		"cflags": list(tc.cflags or []),
		"cxxflags": list(tc.cxxflags or []),
		"ldflags": list(tc.ldflags or []),
	}


def ApplyAndroidSdkNdkJdkDefaults(options: Optional[Dict[str, Any]] = None,
								  registry: Optional[Dict[str, Any]] = None) -> Dict[str, str]:
	options = options or {}
	registry = registry or {}

	sdk_root = _find_android_sdk_root(options, registry)
	ndk_root = _find_android_ndk_root(options, registry, sdk_root=sdk_root)
	jdk_root = _find_jdk_root(options)

	if sdk_root:
		androidsdkpath(sdk_root)
	if ndk_root:
		androidndkpath(ndk_root)
	if jdk_root:
		javajdkpath(jdk_root)

	return {
		"android_sdk_root": sdk_root,
		"android_ndk_root": ndk_root,
		"java_jdk_root": jdk_root,
	}


def ToolchainHostAppleClangDefault(options: Optional[Dict[str, Any]] = None) -> bool:
	options = options or {}
	name = "host-apple-clang"
	if _workspace_has_toolchain(name):
		return False

	cc = _first_executable(
		commands=["clang"],
		paths=[
			options.get("host_apple_clang_cc", ""),
			"/usr/bin/clang",
			"/opt/homebrew/opt/llvm/bin/clang",
			"/usr/local/opt/llvm/bin/clang",
		],
	)
	cxx = _first_executable(
		commands=["clang++"],
		paths=[
			options.get("host_apple_clang_cxx", ""),
			"/usr/bin/clang++",
			"/opt/homebrew/opt/llvm/bin/clang++",
			"/usr/local/opt/llvm/bin/clang++",
		],
	)

	if not cc or not cxx or not _is_apple_clang(cc):
		return False

	ar = _first_executable(commands=["ar", "llvm-ar"], paths=["/usr/bin/ar"])

	with toolchain(name, "apple-clang"):
		settarget("macOS", _host_arch_name())
		ccompiler(cc)
		cppcompiler(cxx)
		linker(cxx)
		if ar:
			archiver(ar)
	return True


def ToolchainHostClangDefault(options: Optional[Dict[str, Any]] = None) -> bool:
	options = options or {}
	name = "host-clang"
	if _workspace_has_toolchain(name):
		return False

	cc = _first_executable(
		commands=["clang"],
		paths=[
			options.get("host_clang_cc", ""),
			r"C:\msys64\ucrt64\bin\clang.exe",
			r"C:\msys64\clang64\bin\clang.exe",
			"/usr/bin/clang",
			"/usr/local/bin/clang",
			"/opt/homebrew/opt/llvm/bin/clang",
			"/usr/local/opt/llvm/bin/clang",
		],
	)
	cxx = _first_executable(
		commands=["clang++"],
		paths=[
			options.get("host_clang_cxx", ""),
			r"C:\msys64\ucrt64\bin\clang++.exe",
			r"C:\msys64\clang64\bin\clang++.exe",
			"/usr/bin/clang++",
			"/usr/local/bin/clang++",
			"/opt/homebrew/opt/llvm/bin/clang++",
			"/usr/local/opt/llvm/bin/clang++",
		],
	)
	if not cc or not cxx:
		return False
	if _is_apple_clang(cc):
		return False

	ar = _first_executable(
		commands=["llvm-ar", "ar"],
		paths=[
			r"C:\msys64\ucrt64\bin\llvm-ar.exe",
			r"C:\msys64\clang64\bin\llvm-ar.exe",
			"/usr/bin/llvm-ar",
			"/usr/local/bin/llvm-ar",
			"/usr/bin/ar",
		],
	)

	host_os = _host_os_name()
	host_arch = _host_arch_name()
	host_env = _host_env_name()

	with toolchain(name, "clang"):
		if host_env:
			settarget(host_os, host_arch, host_env)
		else:
			settarget(host_os, host_arch)
		ccompiler(cc)
		cppcompiler(cxx)
		linker(cxx)
		if ar:
			archiver(ar)
	return True


def ToolchainHostGccDefault(options: Optional[Dict[str, Any]] = None) -> bool:
	options = options or {}
	name = "host-gcc"
	if _workspace_has_toolchain(name):
		return False

	cc = _first_executable(
		commands=["gcc"],
		paths=[
			options.get("host_gcc_cc", ""),
			r"C:\msys64\ucrt64\bin\gcc.exe",
			r"C:\msys64\mingw64\bin\gcc.exe",
			"/usr/bin/gcc",
			"/usr/local/bin/gcc",
		],
	)
	cxx = _first_executable(
		commands=["g++"],
		paths=[
			options.get("host_gcc_cxx", ""),
			r"C:\msys64\ucrt64\bin\g++.exe",
			r"C:\msys64\mingw64\bin\g++.exe",
			"/usr/bin/g++",
			"/usr/local/bin/g++",
		],
	)
	if not cc or not cxx:
		return False

	ar = _first_executable(commands=["ar"], paths=[r"C:\msys64\ucrt64\bin\ar.exe", "/usr/bin/ar", "/usr/local/bin/ar"])
	host_os = _host_os_name()
	host_arch = _host_arch_name()
	host_env = _host_env_name()

	with toolchain(name, "gcc"):
		if host_env:
			settarget(host_os, host_arch, host_env)
		else:
			settarget(host_os, host_arch)
		ccompiler(cc)
		cppcompiler(cxx)
		linker(cxx)
		if ar:
			archiver(ar)
	return True


def ToolchainClangMingwDefault(options: Optional[Dict[str, Any]] = None) -> bool:
	options = options or {}
	name = "clang-mingw"
	if _workspace_has_toolchain(name):
		return False

	cc = _first_executable(
		commands=["x86_64-w64-windows-gnu-clang", "clang"],
		paths=[
			options.get("clang_mingw_cc", ""),
			os.getenv("CLANG_MINGW_CC", ""),
			r"C:\msys64\ucrt64\bin\clang.exe",
			r"C:\msys64\clang64\bin\clang.exe",
			r"C:\msys64\mingw64\bin\clang.exe",
		],
	)
	cxx = _first_executable(
		commands=["x86_64-w64-windows-gnu-clang++", "clang++"],
		paths=[
			options.get("clang_mingw_cxx", ""),
			os.getenv("CLANG_MINGW_CXX", ""),
			r"C:\msys64\ucrt64\bin\clang++.exe",
			r"C:\msys64\clang64\bin\clang++.exe",
			r"C:\msys64\mingw64\bin\clang++.exe",
		],
	)
	if not cc or not cxx:
		return False

	ar = _first_executable(
		commands=["llvm-ar", "x86_64-w64-mingw32-ar", "ar"],
		paths=[
			r"C:\msys64\ucrt64\bin\llvm-ar.exe",
			r"C:\msys64\clang64\bin\llvm-ar.exe",
			r"C:\msys64\ucrt64\bin\ar.exe",
		],
	)
	triple = "x86_64-w64-windows-gnu"

	with toolchain(name, "clang"):
		settarget("Windows", "x86_64", "mingw")
		targettriple(triple)
		ccompiler(cc)
		cppcompiler(cxx)
		linker(cxx)
		if ar:
			archiver(ar)
		cflags([f"--target={triple}"])
		cxxflags([f"--target={triple}"])
		ldflags([f"--target={triple}"])
	return True


def ToolchainMingwGnuDefault(options: Optional[Dict[str, Any]] = None) -> bool:
	options = options or {}
	name = "mingw"
	if _workspace_has_toolchain(name):
		return False

	cc = _first_executable(
		commands=["x86_64-w64-mingw32-gcc", "gcc"],
		paths=[
			options.get("mingw_gcc_cc", ""),
			r"C:\msys64\ucrt64\bin\gcc.exe",
			r"C:\msys64\mingw64\bin\gcc.exe",
		],
	)
	cxx = _first_executable(
		commands=["x86_64-w64-mingw32-g++", "g++"],
		paths=[
			options.get("mingw_gcc_cxx", ""),
			r"C:\msys64\ucrt64\bin\g++.exe",
			r"C:\msys64\mingw64\bin\g++.exe",
		],
	)
	if not cc or not cxx:
		return False

	ar = _first_executable(
		commands=["x86_64-w64-mingw32-ar", "ar"],
		paths=[r"C:\msys64\ucrt64\bin\ar.exe", r"C:\msys64\mingw64\bin\ar.exe"],
	)

	with toolchain(name, "gcc"):
		settarget("Windows", "x86_64", "mingw")
		targettriple("x86_64-w64-mingw32")
		ccompiler(cc)
		cppcompiler(cxx)
		linker(cxx)
		if ar:
			archiver(ar)
	return True


def ToolchainMsvcDefault(options: Optional[Dict[str, Any]] = None) -> bool:
	options = options or {}
	name = "msvc"
	if _workspace_has_toolchain(name):
		return False

	detected = ToolchainManager.DetectMSVC()
	cc = ""
	cxx = ""
	ld = ""
	ar = ""
	arch = _host_arch_name()
	if detected:
		cc = str(detected.ccPath or "")
		cxx = str(detected.cxxPath or detected.ccPath or "")
		ld = str(detected.ldPath or "")
		ar = str(detected.arPath or "")
		if getattr(detected, "targetArch", None):
			arch = str(detected.targetArch.value)
	else:
		cc = _first_executable(commands=["cl.exe", "cl"], paths=[options.get("msvc_cl", "")])
		cxx = cc
		ld = _first_executable(commands=["link.exe", "link"], paths=[options.get("msvc_link", "")])
		ar = _first_executable(commands=["lib.exe", "lib"], paths=[options.get("msvc_lib", "")])

	if not cc:
		return False
	if not cxx:
		cxx = cc
	if not ld:
		ld = cc

	with toolchain(name, "msvc"):
		settarget("Windows", arch, "msvc")
		ccompiler(cc)
		cppcompiler(cxx)
		linker(ld)
		if ar:
			archiver(ar)
	return True


def ToolchainGccCrossLinuxDefault(options: Optional[Dict[str, Any]] = None) -> bool:
	options = options or {}
	name = "gcc-cross-linux"
	if _workspace_has_toolchain(name):
		return False

	cc = _first_executable(
		commands=["x86_64-linux-gnu-gcc"],
		paths=[options.get("gcc_cross_linux_cc", "")],
	)
	cxx = _first_executable(
		commands=["x86_64-linux-gnu-g++"],
		paths=[options.get("gcc_cross_linux_cxx", "")],
	)
	if not cc or not cxx:
		return False

	ar = _first_executable(commands=["x86_64-linux-gnu-ar", "ar"], paths=[options.get("gcc_cross_linux_ar", "")])

	with toolchain(name, "gcc"):
		settarget("Linux", "x86_64", "gnu")
		targettriple("x86_64-linux-gnu")
		ccompiler(cc)
		cppcompiler(cxx)
		linker(cxx)
		if ar:
			archiver(ar)
	return True


def ToolchainClangCrossLinuxDefault(options: Optional[Dict[str, Any]] = None) -> bool:
	options = options or {}
	name = "clang-cross-linux"
	if _workspace_has_toolchain(name):
		return False

	cc = _first_executable(
		commands=["x86_64-linux-gnu-clang", "clang"],
		paths=[options.get("clang_cross_linux_cc", "")],
	)
	cxx = _first_executable(
		commands=["x86_64-linux-gnu-clang++", "clang++"],
		paths=[options.get("clang_cross_linux_cxx", "")],
	)
	if not cc or not cxx:
		return False

	cc_name = Path(cc).name.lower()
	cxx_name = Path(cxx).name.lower()
	if _host_os_name() != "Linux" and "x86_64-linux-gnu" not in cc_name and "x86_64-linux-gnu" not in cxx_name:
		return False

	ar = _first_executable(commands=["llvm-ar", "x86_64-linux-gnu-ar", "ar"], paths=[options.get("clang_cross_linux_ar", "")])
	triple = "x86_64-unknown-linux-gnu"

	with toolchain(name, "clang"):
		settarget("Linux", "x86_64", "gnu")
		targettriple(triple)
		ccompiler(cc)
		cppcompiler(cxx)
		linker(cxx)
		if ar:
			archiver(ar)
		cflags([f"--target={triple}"])
		cxxflags([f"--target={triple}"])
		ldflags([f"--target={triple}"])
	return True


def ToolchainEmscriptenDefault(options: Optional[Dict[str, Any]] = None,
							   registry: Optional[Dict[str, Any]] = None) -> bool:
	options = options or {}
	registry = registry or {}
	name = "emscripten"
	if _workspace_has_toolchain(name):
		return False

	emsdk_root = _find_emsdk_root(options, registry)
	emsdk_paths: list[str] = []
	if emsdk_root:
		emsdk_paths.extend([
			str(Path(emsdk_root) / "upstream" / "emscripten"),
			str(Path(emsdk_root)),
		])

	emcc = _first_executable(
		commands=["emcc", "emcc.bat", "emcc.cmd"],
		paths=[str(Path(p) / "emcc") for p in emsdk_paths] + [str(Path(p) / "emcc.bat") for p in emsdk_paths] + [str(Path(p) / "emcc.cmd") for p in emsdk_paths],
	)
	empp = _first_executable(
		commands=["em++", "em++.bat", "em++.cmd"],
		paths=[str(Path(p) / "em++") for p in emsdk_paths] + [str(Path(p) / "em++.bat") for p in emsdk_paths] + [str(Path(p) / "em++.cmd") for p in emsdk_paths],
	)
	emar = _first_executable(
		commands=["emar", "emar.bat", "emar.cmd"],
		paths=[str(Path(p) / "emar") for p in emsdk_paths] + [str(Path(p) / "emar.bat") for p in emsdk_paths] + [str(Path(p) / "emar.cmd") for p in emsdk_paths],
	)

	if not emcc or not empp:
		return False

	with toolchain(name, "emscripten"):
		settarget("Web", "wasm32")
		ccompiler(emcc)
		cppcompiler(empp)
		linker(empp)
		if emar:
			archiver(emar)
	return True


def _find_android_llvm_prebuilt(ndk_root: str) -> str:
	root = Path(ndk_root) / "toolchains" / "llvm" / "prebuilt"
	if not root.exists() or not root.is_dir():
		return ""

	preferred: list[str] = []
	if os.name == "nt":
		preferred.append("windows-x86_64")
	elif host_platform.system().lower() == "darwin":
		preferred.extend(["darwin-arm64", "darwin-x86_64"])
	else:
		preferred.append("linux-x86_64")

	for tag in preferred:
		candidate = root / tag
		if candidate.exists():
			return str(candidate)

	for child in sorted((p for p in root.iterdir() if p.is_dir()), key=lambda p: p.name):
		return str(child)
	return ""


def ToolchainAndroidNdkDefault(options: Optional[Dict[str, Any]] = None,
							   registry: Optional[Dict[str, Any]] = None) -> bool:
	options = options or {}
	registry = registry or {}
	name = "android-ndk"
	if _workspace_has_toolchain(name):
		return False

	resolved = ApplyAndroidSdkNdkJdkDefaults(options, registry)
	ndk_root = resolved.get("android_ndk_root", "")
	if not ndk_root:
		return False

	prebuilt = _find_android_llvm_prebuilt(ndk_root)
	if not prebuilt:
		return False

	bin_dir = Path(prebuilt) / "bin"
	cc = _first_executable(
		paths=[
			str(bin_dir / "clang"),
			str(bin_dir / "clang.cmd"),
			str(bin_dir / "clang.exe"),
		],
	)
	cxx = _first_executable(
		paths=[
			str(bin_dir / "clang++"),
			str(bin_dir / "clang++.cmd"),
			str(bin_dir / "clang++.exe"),
		],
	)
	ar = _first_executable(
		paths=[
			str(bin_dir / "llvm-ar"),
			str(bin_dir / "llvm-ar.exe"),
		],
	)

	if not cc or not cxx:
		return False

	triple = str(options.get("android_target_triple", "aarch64-linux-android21")).strip() or "aarch64-linux-android21"
	sysroot_dir = str(Path(prebuilt) / "sysroot")

	with toolchain(name, "android-ndk"):
		settarget("Android", "arm64", "android")
		targettriple(triple)
		if Path(sysroot_dir).exists():
			sysroot(sysroot_dir)
		ccompiler(cc)
		cppcompiler(cxx)
		linker(cxx)
		if ar:
			archiver(ar)
		cflags([f"--target={triple}"])
		cxxflags([f"--target={triple}"])
		ldflags([f"--target={triple}"])
	return True


def ToolchainZigDefaults(options: Optional[Dict[str, Any]] = None) -> bool:
	options = options or {}

	zig_root_candidates = [
		options.get("zig_root", ""),
		options.get("zigRoot", ""),
		os.getenv("ZIG_ROOT", ""),
	]
	if os.name == "nt":
		zig_root_candidates.extend([r"C:\zig", r"C:\Program Files\zig", r"C:\msys64\ucrt64\bin"])
	elif host_platform.system().lower() == "darwin":
		zig_root_candidates.extend(["/opt/zig", "/opt/homebrew/bin", "/usr/local/bin"])
	else:
		zig_root_candidates.extend(["/opt/zig", "/usr/local/bin", "/usr/bin"])

	zig_wrapper_paths: list[str] = []
	for root in zig_root_candidates:
		expanded = _expand_path(root)
		if not expanded:
			continue
		zig_wrapper_paths.extend(
			[
				str(Path(expanded) / "zig-cc"),
				str(Path(expanded) / "zig-c++"),
				str(Path(expanded) / "zig-ar"),
				str(Path(expanded) / "bin" / "zig-cc"),
				str(Path(expanded) / "bin" / "zig-c++"),
				str(Path(expanded) / "bin" / "zig-ar"),
				str(Path(expanded) / "zig-cc.exe"),
				str(Path(expanded) / "zig-c++.exe"),
				str(Path(expanded) / "zig-ar.exe"),
				str(Path(expanded) / "bin" / "zig-cc.exe"),
				str(Path(expanded) / "bin" / "zig-c++.exe"),
				str(Path(expanded) / "bin" / "zig-ar.exe"),
			]
		)

	zig_cc = _first_executable(commands=["zig-cc"], paths=zig_wrapper_paths)
	zig_cxx = _first_executable(commands=["zig-c++"], paths=zig_wrapper_paths)
	if not zig_cc or not zig_cxx:
		return False

	zig_ar = _first_executable(commands=["zig-ar", "llvm-ar", "ar"], paths=zig_wrapper_paths)

	def _register(name: str, os_name: str, arch_name: str, env_name: str, triple: str) -> bool:
		if _workspace_has_toolchain(name):
			return False
		with toolchain(name, "clang"):
			if env_name:
				settarget(os_name, arch_name, env_name)
			else:
				settarget(os_name, arch_name)
			targettriple(triple)
			ccompiler(zig_cc)
			cppcompiler(zig_cxx)
			linker(zig_cxx)
			if zig_ar:
				archiver(zig_ar)
			cflags(["-target", triple])
			cxxflags(["-target", triple])
			ldflags(["-target", triple])
		return True

	registered = False
	registered = _register("zig-linux-x86_64", "Linux", "x86_64", "gnu", "x86_64-linux-gnu") or registered
	registered = _register("zig-linux-x64", "Linux", "x86_64", "gnu", "x86_64-linux-gnu") or registered
	registered = _register("zig-windows-x86_64", "Windows", "x86_64", "mingw", "x86_64-windows-gnu") or registered
	registered = _register("zig-windows-x64", "Windows", "x86_64", "mingw", "x86_64-windows-gnu") or registered
	registered = _register("zig-macos-x86_64", "macOS", "x86_64", "gnu", "x86_64-macos") or registered
	registered = _register("zig-macos-arm64", "macOS", "arm64", "gnu", "aarch64-macos") or registered
	registered = _register("zig-android-arm64", "Android", "arm64", "android", "aarch64-linux-android21") or registered
	registered = _register("zig-web-wasm32", "Web", "wasm32", "", "wasm32-wasi") or registered
	return registered


def ToolchainHarmonyOsDefault(options: Optional[Dict[str, Any]] = None) -> bool:
    options = options or {}
    name = "ohos-ndk"
    if _workspace_has_toolchain(name):
        return False

    # Résolution du SDK OHOS
    ohos_sdk = _expand_path(
        options.get("ohos_sdk", "")
        or os.getenv("OHOS_SDK", "")
        or os.getenv("HARMONY_SDK", "")
    )
    if not ohos_sdk:
        # Chemin par défaut Windows
        default = Path("C:/ohos/command-line-tools/sdk/default/openharmony")
        if default.exists():
            ohos_sdk = str(default)
    if not ohos_sdk:
        return False

    ndk_path = Path(ohos_sdk) / "native"
    llvm_bin = ndk_path / "llvm" / "bin"
    sysroot_path = ndk_path / "sysroot"

    if not llvm_bin.exists():
        return False

    exe = ".exe" if os.name == "nt" else ""
    cc  = str(llvm_bin / f"clang{exe}")
    cxx = str(llvm_bin / f"clang++{exe}")
    ar  = str(llvm_bin / f"llvm-ar{exe}")
    ld  = str(llvm_bin / f"ld{exe}")

    if not Path(cc).exists() or not Path(cxx).exists():
        return False

    triple = "aarch64-linux-ohos"

    with toolchain(name, "clang"):
        settarget("HarmonyOS", "arm64")
        targettriple(triple)
        if sysroot_path.exists():
            sysroot(str(sysroot_path))
        ccompiler(cc)
        cppcompiler(cxx)
        linker(cxx)
        if Path(ar).exists():
            archiver(ar)
        cflags([f"--target={triple}", "-fPIC", "-D__OHOS__"])
        cxxflags([f"--target={triple}", "-fPIC", "-D__OHOS__"])
        ldflags([f"--target={triple}"])
    return True


def RegisterDefaultPathToolchains(options: Optional[Dict[str, Any]] = None,
								  registry: Optional[Dict[str, Any]] = None) -> None:
	options = options or {}
	registry = registry or {}

	ApplyAndroidSdkNdkJdkDefaults(options, registry)

	ToolchainHostAppleClangDefault(options)
	ToolchainHostClangDefault(options)
	ToolchainHostGccDefault(options)

	ToolchainMsvcDefault(options)
	ToolchainClangMingwDefault(options)
	ToolchainMingwGnuDefault(options)

	ToolchainGccCrossLinuxDefault(options)
	ToolchainClangCrossLinuxDefault(options)

	ToolchainEmscriptenDefault(options, registry)
	ToolchainAndroidNdkDefault(options, registry)
	ToolchainZigDefaults(options)
	
	ToolchainHarmonyOsDefault(options)  # ← ajouter ici


def RegisterJengaGlobalToolchains(options: Optional[Dict[str, Any]] = None):
	"""Register toolchains from registry + default-path functions + auto-detect."""
	options = options or {}
	registry = LoadGlobalRegistry()

	ApplyAndroidSdkNdkJdkDefaults(options, registry)

	for entry in registry.get("toolchains", []) or []:
		_register_entry(entry)

	RegisterDefaultPathToolchains(options, registry)

	detected = ToolchainManager().DetectAll()
	for tc in detected.values():
		_register_entry(_entry_from_toolchain(tc))
