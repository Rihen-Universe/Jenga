<div align="center">

# 🧱 Jenga Build System

**Modern, cross-platform C/C++ build system driven by a unified Python DSL.**

*Un système de build C/C++ multi-plateforme, piloté par un DSL Python unifié.*

[![Version](https://img.shields.io/badge/version-2.0.2-blue.svg)]()
[![License](https://img.shields.io/badge/license-Proprietary-lightgrey.svg)](./LICENSE)
[![Python](https://img.shields.io/badge/python-3.8%2B-blue.svg)](https://www.python.org)
[![Targets](https://img.shields.io/badge/targets-Windows%20%7C%20Linux%20%7C%20macOS%20%7C%20Android%20%7C%20iOS%20%7C%20Web%20%7C%20HarmonyOS%20%7C%20Xbox-green.svg)]()

**📖 [Wiki (FR / EN)](https://github.com/Rihen-Universe/Jenga/wiki) · 🗺️ [Roadmap](./Jenga/Docs/ROADMAP.md) · 🚀 [Quick Start](#-quick-start) · 💬 Édité par [Rihen](#-publisher--license)**

</div>

---

## 🎯 What is Jenga?

**Jenga** is a build system for native projects (C, C++, Objective-C, Assembly, Rust, Zig). Instead of generating intermediate Makefiles or `CMakeLists.txt`, it **compiles directly** through native toolchains, driven by readable `.jenga` files — plain Python enriched with a build DSL.

One description builds your project for **every supported platform**, with packaging, networking permissions, tests and deployment built in. Jenga is developed by **Rihen**.

```python
from Jenga import *

with workspace("HelloWorkspace"):
    configurations(["Debug", "Release"])
    targetoses([TargetOS.WINDOWS, TargetOS.LINUX, TargetOS.MACOS])
    targetarchs([TargetArch.X86_64])

    with project("HelloApp"):
        consoleapp()
        language("C++")
        cppdialect("C++20")
        files(["src/**.cpp", "include/**.hpp"])
```

---

## ✨ Key Features

- **Python DSL** with context managers: `workspace`, `project`, `toolchain`, `filter`, `unitest`, `test`, `include`.
- **Direct compilation** — no intermediate project files (unlike CMake/Meson).
- **Incremental cache** (3 levels: mtime → `.d` deps → SHA256) + **background daemon** for instant commands.
- **Parallel builds** (`-j`, `ThreadPoolExecutor`).
- **Cross-compilation** to any target from any host, with automatic toolchain detection (MSVC, GCC, Clang, NDK, Emscripten, Zig, OHOS…).
- **Multi-platform packaging**: MSI/EXE/ZIP, DEB, PKG/DMG, APK/AAB, IPA, HAP, Web ZIP.
- **Network & firewall permissions** generated automatically at install time, on every platform — see [Networking](#-networking--firewall).
- **Built-in C++ unit testing** (Unitest) and **automatic API documentation** (`jenga docs`).
- **Project generators**: CMake, Makefile, Visual Studio 2022, Xcode.

---

## 🖥️ Supported Platforms

| Platform | Status | Notes |
|----------|--------|-------|
| Windows x64 | ✅ Production | MSVC, clang-cl, MinGW/clang |
| Linux x64 | ✅ Production | GCC, Clang (native & cross) |
| Android (4 ABIs) | ✅ Production | NDK r27c, Universal APK |
| Web / WASM | ✅ Production | Emscripten (emsdk) |
| macOS | ✅ Ready | requires macOS (Apple Clang) |
| iOS / tvOS / watchOS / visionOS | ✅ Ready | requires macOS + Xcode |
| HarmonyOS | ✅ Ready | OpenHarmony NDK — [guide](https://github.com/Rihen-Universe/Jenga/wiki/HarmonyOS) |
| Xbox One / Series | 🟡 Partial | requires Microsoft GDK |
| Nintendo Switch / PS4-PS5 | 🔒 Licensed | requires vendor SDK |

---

## 📦 Installation

**Requirements:** Python 3.8+. Compilers depend on your targets.

```bash
# From source (recommended for this repository)
git clone https://github.com/Rihen-Universe/Jenga.git
cd Jenga
pip install -e .

# Or from a release artifact (GitHub Releases)
pip install jenga-2.0.2-py3-none-any.whl
```

Verify and launch:

```bash
jenga --version
jenga --help          # or: jenga.bat --help (Windows) / bash ./jenga.sh --help
```

Full setup details: **[Installation wiki](https://github.com/Rihen-Universe/Jenga/wiki/Installation)**.

---

## 🚀 Quick Start

```bash
# 1. Create a workspace and a project
jenga workspace HelloWorkspace
jenga project HelloApp --kind console --lang C++

# 2. Build, run, test
jenga build --config Debug
jenga run HelloApp
jenga test
```

Step-by-step: **[First Workspace wiki](https://github.com/Rihen-Universe/Jenga/wiki/Premier-Workspace)**.

---

## 📚 Documentation

The full documentation lives in the **bilingual (FR / EN) [Wiki](https://github.com/Rihen-Universe/Jenga/wiki)**. Source pages are versioned under [`Jenga/Docs/wiki/`](./Jenga/Docs/wiki/) and auto-published to the wiki on push to `main`.

| Page | Description |
|------|-------------|
| [Home](https://github.com/Rihen-Universe/Jenga/wiki/Home) | Wiki entry point |
| [Installation](https://github.com/Rihen-Universe/Jenga/wiki/Installation) | Install & prerequisites |
| [First Workspace](https://github.com/Rihen-Universe/Jenga/wiki/Premier-Workspace) | Your first `.jenga` project |
| [CLI Commands](https://github.com/Rihen-Universe/Jenga/wiki/Commandes-CLI) | All `jenga` commands |
| [DSL Reference](https://github.com/Rihen-Universe/Jenga/wiki/DSL-Reference) | Full DSL API |
| [Toolchains & Sysroots](https://github.com/Rihen-Universe/Jenga/wiki/Toolchains-et-Sysroots) | Custom/cross toolchains |
| [Unitest Tests](https://github.com/Rihen-Universe/Jenga/wiki/Tests-Unitest) | Built-in C++ testing |
| [Automatic Documentation](https://github.com/Rihen-Universe/Jenga/wiki/Documentation-Automatique) | `jenga docs` extractor |
| [Packaging & Deployment](https://github.com/Rihen-Universe/Jenga/wiki/Packaging-Deploiement-Publication) | MSI/EXE/DEB/PKG/APK/IPA/HAP… |
| [Networking & Firewall](https://github.com/Rihen-Universe/Jenga/wiki/Reseau-et-Pare-feu) | Install-time network permissions |
| [HarmonyOS](https://github.com/Rihen-Universe/Jenga/wiki/HarmonyOS) | OpenHarmony / HAP builds |
| [Examples](https://github.com/Rihen-Universe/Jenga/wiki/Exemples) | Sample workspaces |
| [FAQ / Troubleshooting](https://github.com/Rihen-Universe/Jenga/wiki/FAQ-Depannage) | Common issues |

**Other documents:**
- 🗺️ [Roadmap](./Jenga/Docs/ROADMAP.md) — done / in progress / to do
- 📘 [Complete Guide](./Jenga/Docs/GUIDE_COMPLET_JENGA.md) — 20-chapter user guide
- 🛠️ [Developer Guide](./Jenga/Docs/Jenga_Developer_Guide.md)

---

## ⚙️ CLI Overview

```bash
# Core workflow
jenga build [--config Debug|Release] [--platform <os[-arch[-env]]>] [--target <project>]
jenga run [project] | jenga test | jenga clean | jenga rebuild | jenga watch

# Authoring
jenga workspace [name]      jenga project <name> --kind console|windowed|static|shared|test
jenga file [project] --src ... --inc ... --link ... --def ...
jenga gen --cmake|--makefile|--vs2022|--xcode

# Toolchains, packaging, distribution
jenga install toolchain detect|list|install <name>
jenga package --platform windows|linux|macos|android|ios|web [--type <pkg>]
jenga deploy  --platform android|ios|xbox|...        jenga publish --registry nuget|...
jenga docs extract        jenga bench        jenga examples list|copy
```

Aliases: `b`=build, `r`=run, `t`=test, `c`=clean, `w`=watch, `i`=info, `e`=examples, `d`=docs, `h`=help.
Full reference: **[CLI wiki](https://github.com/Rihen-Universe/Jenga/wiki/Commandes-CLI)**.

---

## 🌐 Networking & Firewall

Jenga configures **network permissions automatically at install time**, on every platform, from a single DSL declaration — no more manually opening the firewall for LAN multiplayer games or local servers.

```python
with project("MyGame"):
    consoleapp()
    networkenabled(True)                          # default inbound rule on the app
    firewallrule(protocol="udp", ports=["7777"])  # optional custom rules
```

| Platform | Generated at install |
|----------|----------------------|
| Windows (MSI/EXE) | `netsh advfirewall` rule (all profiles), removed on uninstall |
| macOS (PKG) | `socketfilterfw --add` postinstall |
| Linux (DEB) | `postinst`/`postrm` via `ufw` / `firewall-cmd` / `iptables` |
| Android | `INTERNET` + `ACCESS_NETWORK_STATE` + `ACCESS_WIFI_STATE` |
| iOS | `NSLocalNetworkUsageDescription` + Bonjour keys |
| HarmonyOS | `ohos.permission.INTERNET` + network info |

Details: **[Networking & Firewall wiki](https://github.com/Rihen-Universe/Jenga/wiki/Reseau-et-Pare-feu)**.

---

## 📂 Examples

27 ready-to-use workspaces live in [`Jenga/Exemples/`](./Jenga/Exemples/) — from `01_hello_console` to multi-platform sandboxes.

```bash
jenga examples list
jenga examples copy 01_hello_console ./hello_copy
```

---

## 🗂️ Repository Structure

```text
Jenga/
  _version.py        # Single source of truth: version + publisher (Rihen)
  Core/Api.py        # DSL (200+ functions)
  Core/Builders/     # One builder per platform
  Core/FirewallSpec.py  # Cross-platform network/firewall command generator
  Commands/          # CLI commands
  Unitest/           # Built-in C++ test framework
  Exemples/          # 27 sample workspaces
  Docs/              # Guides, ROADMAP, wiki sources
gitpush.sh / .bat    # Commit + push helpers (branch => wiki, --release => release)
scripts/             # Utility scripts (sysroot, examples archive)
```

---

## ⚠️ Known Limitations

- `jenga publish`: NuGet implemented; vcpkg/conan/npm/pypi are placeholders.
- `jenga profile`: partial `perf` on Linux; other platforms mostly placeholders.
- `jenga deploy`: Android/iOS/Xbox available; Linux not yet implemented.
- Linux packaging: DEB implemented; RPM/AppImage/Snap pending.
- Xbox requires Microsoft GDK; Switch/PlayStation require vendor SDKs.

See the [Roadmap](./Jenga/Docs/ROADMAP.md) for the full status.

---

## 👤 Publisher & License

**Jenga** is a product developed and maintained by **Rihen**.

- Author / Publisher: **Rihen** — <rihen.universe@gmail.com>
- Repository: <https://github.com/Rihen-Universe/Jenga>
- License: **Proprietary** — see [`LICENSE`](./LICENSE).

---

## 📝 Disclaimer

This software is provided "as is", without warranty of any kind. Production use requires validation in your own toolchain and target environment.
