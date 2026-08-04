# Jenga User Guide

**Version 2.0.2**
**Complete Reference for Building Native Applications**

---

## Table of Contents

1. [Introduction](#introduction)
2. [Installation](#installation)
3. [Getting Started](#getting-started)
4. [Quick Start Tutorial](#quick-start-tutorial)
5. [Workspace Configuration](#workspace-configuration)
6. [Project Configuration](#project-configuration)
7. [DSL Function Reference](#dsl-function-reference)
8. [Build Commands](#build-commands)
9. [Toolchains and Cross-Compilation](#toolchains-and-cross-compilation)
10. [Platform-Specific Development](#platform-specific-development)
11. [Testing and Quality](#testing-and-quality)
12. [Advanced Features](#advanced-features)
13. [Example Projects Explained](#example-projects-explained)
14. [Troubleshooting](#troubleshooting)
15. [Best Practices](#best-practices)

---

## Introduction

### What is Jenga?

Jenga is a professional cross-platform build system for native applications written in C, C++, Objective-C, Objective-C++, Assembly, Rust, and Zig. Unlike traditional build systems that rely on complex configuration files, Jenga uses a Python-based DSL (Domain-Specific Language) that is both powerful and intuitive.

### Key Features

- **Multi-Platform Support**: Windows, Linux, macOS, Android, iOS, Web (WebAssembly), HarmonyOS, Xbox, PlayStation, Nintendo Switch
- **Multi-Architecture**: x86, x86_64, ARM, ARM64, WASM32, WASM64, PowerPC, MIPS
- **Cross-Compilation**: Build for any target from any host with proper toolchain
- **Multiple Compilers**: MSVC, GCC, Clang, Apple Clang, MinGW, Android NDK, Emscripten, Zig
- **Modern C++ Support**: C++11 through C++23, including C++20 modules
- **Built-in Testing**: Integrated Unitest framework for unit testing
- **Incremental Builds**: Fast rebuilds with SQLite-backed caching
- **Package Management**: APK/AAB for Android, IPA for iOS
- **Code Signing**: Automatic signing for mobile platforms
- **Project Generation**: Export to CMake, Makefiles, Visual Studio solutions

### Who Should Use Jenga?

Jenga is designed for:
- Game developers targeting multiple platforms
- Application developers needing cross-platform support
- Teams wanting a unified build system across all platforms
- Developers who prefer Python-based configuration over CMake/Makefiles
- Projects requiring advanced features like C++20 modules, precompiled headers, or custom toolchains

---

## Installation

### Requirements

- **Python**: 3.8 or higher
- **Operating System**: Windows 10+, Linux (Ubuntu 18.04+, any modern distro), macOS 10.15+
- **Compilers**: At least one C/C++ compiler installed (MSVC, GCC, Clang, etc.)

### Installation via pip

```bash
pip install Jenga
```

### Installation from Source

```bash
git clone https://github.com/Rihen-Universe/Jenga.git
cd Jenga
pip install -e .
```

### Verify Installation

```bash
Jenga --version
```

Expected output:
```
Jenga Build System v2.0.2
```

### Installing Compilers

#### Windows
- **MSVC**: Install Visual Studio 2017+ with C++ workload
- **Clang**: Download from [LLVM releases](https://releases.llvm.org/)
- **MinGW**: Install via [MSYS2](https://www.msys2.org/)

#### Linux
```bash
# GCC
sudo apt install build-essential

# Clang
sudo apt install clang
```

#### macOS
```bash
# Install Xcode Command Line Tools
xcode-select --install
```

---

## Getting Started

### Creating Your First Workspace

A **workspace** is the top-level container for your projects. Let's create one:

```bash
Jenga init MyWorkspace
```

Or use the interactive mode:

```bash
Jenga workspace
```

The interactive mode will guide you through:
1. Workspace name
2. Build configurations (Debug, Release, etc.)
3. Target operating systems
4. Target architectures
5. Default compiler selection
6. C++ standard selection
7. Optional initial project creation

This creates a file named `MyWorkspace.jenga` with basic structure:

```python
from Jenga import *

with workspace("MyWorkspace", location="."):
    configurations(["Debug", "Release"])
    targetoses([TargetOS.WINDOWS, TargetOS.LINUX, TargetOS.MACOS])
    targetarchs([TargetArch.X86_64])

    with project("MyProject"):
        consoleapp()
        language("C++")
        cppdialect("C++17")
        files(["src/**.cpp"])
        includedirs(["include"])

        with filter("configurations:Debug"):
            defines(["DEBUG", "_DEBUG"])
            optimize("Off")
            symbols("On")

        with filter("configurations:Release"):
            defines(["NDEBUG"])
            optimize("Speed")
            symbols("Off")
```

### Building Your Project

```bash
Jenga build
```

Optional flags:
- `--config Debug` or `--config Release` - Specify configuration
- `--platform Windows-x86_64` - Specify target platform
- `--verbose` - Show detailed compilation output
- `--no-cache` - Disable caching for clean build

### Running Your Application

```bash
Jenga run
```

This automatically builds (if needed) and runs the executable.

### Cleaning Build Artifacts

```bash
Jenga clean
```

Or clean everything including cache:

```bash
Jenga clean --all
```

---

## Quick Start Tutorial

### Tutorial 1: Hello World Console Application

Create `hello.jenga`:

```python
from Jenga import *

with workspace("HelloWorld"):
    configurations(["Debug", "Release"])
    targetoses([TargetOS.WINDOWS, TargetOS.LINUX, TargetOS.MACOS])
    targetarchs([TargetArch.X86_64])

    with project("Hello"):
        consoleapp()
        language("C++")
        files(["main.cpp"])
```

Create `main.cpp`:

```cpp
#include <iostream>

int main() {
    std::cout << "Hello from Jenga!" << std::endl;
    return 0;
}
```

Build and run:

```bash
Jenga build
Jenga run
```

### Tutorial 2: Static Library with Application

Create `library_demo.jenga`:

```python
from Jenga import *

with workspace("LibraryDemo"):
    configurations(["Debug", "Release"])
    targetoses([TargetOS.WINDOWS, TargetOS.LINUX, TargetOS.MACOS])
    targetarchs([TargetArch.X86_64])

    # Math library
    with project("MathLib"):
        staticlib()
        language("C++")
        location("mathlib")
        files(["src/**.cpp"])
        includedirs(["include"])

    # Application using the library
    with project("App"):
        consoleapp()
        language("C++")
        location("app")
        files(["main.cpp"])
        includedirs(["%{wks.location}/mathlib/include"])
        links(["MathLib"])
        dependson(["MathLib"])
```

Directory structure:
```
library_demo/
├── library_demo.jenga
├── mathlib/
│   ├── include/
│   │   └── math.h
│   └── src/
│       └── math.cpp
└── app/
    └── main.cpp
```

`mathlib/include/math.h`:
```cpp
#pragma once

int add(int a, int b);
int multiply(int a, int b);
```

`mathlib/src/math.cpp`:
```cpp
#include "math.h"

int add(int a, int b) {
    return a + b;
}

int multiply(int a, int b) {
    return a * b;
}
```

`app/main.cpp`:
```cpp
#include <iostream>
#include "math.h"

int main() {
    std::cout << "5 + 3 = " << add(5, 3) << std::endl;
    std::cout << "5 * 3 = " << multiply(5, 3) << std::endl;
    return 0;
}
```

Build:
```bash
Jenga build
Jenga run
```

### Tutorial 3: Unit Testing

Create `test_demo.jenga`:

```python
from Jenga import *

with workspace("TestDemo"):
    configurations(["Debug", "Release"])
    targetoses([TargetOS.WINDOWS, TargetOS.LINUX, TargetOS.MACOS])
    targetarchs([TargetArch.X86_64])

    # Configure Unitest framework
    with unitest() as u:
        u.Compile(cxxflags=["-fexceptions"])

    with project("Calculator"):
        staticlib()
        language("C++")
        files(["src/**.cpp"])
        includedirs(["include"])

        # Test suite for Calculator
        with test():
            testfiles(["tests/**.cpp"])
```

`include/calculator.h`:
```cpp
#pragma once

class Calculator {
public:
    int add(int a, int b);
    int subtract(int a, int b);
    int multiply(int a, int b);
    int divide(int a, int b);
};
```

`src/calculator.cpp`:
```cpp
#include "calculator.h"

int Calculator::add(int a, int b) { return a + b; }
int Calculator::subtract(int a, int b) { return a - b; }
int Calculator::multiply(int a, int b) { return a * b; }
int Calculator::divide(int a, int b) { return a / b; }
```

`tests/test_calculator.cpp`:
```cpp
#include <Unitest/Unitest.h>
#include <Unitest/TestMacro.h>
#include "calculator.h"

TEST_CASE(Calculator, Addition) {
    Calculator calc;
    ASSERT_EQUAL(5, calc.add(2, 3));
    ASSERT_EQUAL(0, calc.add(-1, 1));
}

TEST_CASE(Calculator, Subtraction) {
    Calculator calc;
    ASSERT_EQUAL(1, calc.subtract(3, 2));
    ASSERT_EQUAL(-2, calc.subtract(0, 2));
}

TEST_CASE(Calculator, Multiplication) {
    Calculator calc;
    ASSERT_EQUAL(6, calc.multiply(2, 3));
    ASSERT_EQUAL(0, calc.multiply(5, 0));
}

TEST_CASE(Calculator, Division) {
    Calculator calc;
    ASSERT_EQUAL(2, calc.divide(6, 3));
    ASSERT_EQUAL(5, calc.divide(10, 2));
}
```

Run tests:
```bash
Jenga test
```

---

## Workspace Configuration

### Workspace Basics

A workspace is defined using the `workspace()` context manager:

```python
with workspace("MyWorkspace", location="."):
    # Workspace configuration here
    pass
```

**Parameters:**
- `name` (required): Workspace name
- `location` (optional): Workspace root directory (default: current directory)

### Build Configurations

Configurations define different build variants (Debug, Release, etc.):

```python
configurations(["Debug", "Release", "RelWithDebInfo", "MinSizeRel"])
```

Common configurations:
- **Debug**: No optimization, full debug symbols, debug assertions enabled
- **Release**: Full optimization, no debug symbols, NDEBUG defined
- **RelWithDebInfo**: Optimization + debug symbols for profiling
- **MinSizeRel**: Size optimization for embedded systems

### Target Platforms

Specify target operating systems:

```python
targetoses([TargetOS.WINDOWS, TargetOS.LINUX, TargetOS.MACOS])
```

Available target OSes:
- `TargetOS.WINDOWS` - Windows 10/11
- `TargetOS.LINUX` - Linux distributions
- `TargetOS.MACOS` - macOS 10.15+
- `TargetOS.ANDROID` - Android 5.0+ (API 21+)
- `TargetOS.IOS` - iOS 14.0+
- `TargetOS.TVOS` - tvOS
- `TargetOS.WATCHOS` - watchOS
- `TargetOS.WEB` - WebAssembly (Emscripten)
- `TargetOS.HARMONYOS` - HarmonyOS
- `TargetOS.XBOX_ONE` - Xbox One
- `TargetOS.XBOX_SERIES` - Xbox Series X/S
- `TargetOS.PS4`, `TargetOS.PS5` - PlayStation
- `TargetOS.SWITCH` - Nintendo Switch
- `TargetOS.FREEBSD`, `TargetOS.OPENBSD` - BSD variants

Specify target architectures:

```python
targetarchs([TargetArch.X86_64, TargetArch.ARM64])
```

Available architectures:
- `TargetArch.X86` - 32-bit x86
- `TargetArch.X86_64` - 64-bit x86 (AMD64)
- `TargetArch.ARM` - 32-bit ARM (ARMv7)
- `TargetArch.ARM64` - 64-bit ARM (ARMv8/AArch64)
- `TargetArch.WASM32` - 32-bit WebAssembly
- `TargetArch.WASM64` - 64-bit WebAssembly
- `TargetArch.POWERPC`, `TargetArch.POWERPC64` - PowerPC
- `TargetArch.MIPS`, `TargetArch.MIPS64` - MIPS

### Single Target Shortcuts

For single-target projects:

```python
targetos(TargetOS.WINDOWS)
targetarch(TargetArch.X86_64)
```

Or use aliases:

```python
platform(TargetOS.ANDROID)
architecture(TargetArch.ARM64)
```

### Startup Project

For workspaces with multiple projects, specify which to run by default:

```python
startproject("MyMainApp")
```

### SDK Paths

Configure SDK paths for mobile development:

```python
# Android
androidsdkpath("/path/to/android-sdk")
androidndkpath("/path/to/android-ndk")
javajdkpath("/path/to/jdk")

# iOS
iosSdkPath("/Applications/Xcode.app/Contents/Developer/Platforms/iPhoneOS.platform/Developer/SDKs/iPhoneOS.sdk")
```

Or use environment variables:

```python
import os
androidsdkpath(os.getenv("ANDROID_SDK_ROOT", ""))
androidndkpath(os.getenv("ANDROID_NDK_HOME", ""))
```

---

## Project Configuration

### Project Basics

Projects are defined within a workspace:

```python
with project("MyProject"):
    # Project configuration here
    pass
```

### Project Kinds

Specify the output type:

```python
consoleapp()      # Console executable
windowedapp()     # GUI application
staticlib()       # Static library (.lib, .a)
sharedlib()       # Shared library (.dll, .so, .dylib)
testsuite()       # Test executable
```

Or use generic `kind()`:

```python
kind(ProjectKind.CONSOLE_APP)
```

### Language and Dialect

Set programming language:

```python
language("C++")
```

Supported languages:
- `"C"` or `Language.C`
- `"C++"` or `Language.CPP`
- `"Objective-C"` or `Language.OBJC`
- `"Objective-C++"` or `Language.OBJCPP`
- `"Assembly"` or `Language.ASM`
- `"Rust"` or `Language.RUST`
- `"Zig"` or `Language.ZIG`

Set C++ standard:

```python
cppdialect("C++17")
# Or: cppversion("C++17")
```

Supported C++ standards:
- `"C++11"`, `"C++14"`, `"C++17"`, `"C++20"`, `"C++23"`

Set C standard:

```python
cdialect("C17")
# Or: cversion("C17")
```

Supported C standards:
- `"C89"`, `"C99"`, `"C11"`, `"C17"`, `"C23"`

### Files and Patterns

Add source files using glob patterns:

```python
files([
    "src/**.cpp",           # All .cpp files in src/ recursively
    "src/main.c",           # Specific file
    "platform/*.cpp",       # All .cpp in platform/ (non-recursive)
])
```

Exclude files:

```python
excludefiles([
    "src/old/**.cpp",       # Exclude old directory
    "**/*_test.cpp",        # Exclude test files
])
```

Exclude main entry points (useful for libraries with test mains):

```python
excludemainfiles([
    "tests/main.cpp"
])
```

### Directories

Set project location:

```python
location("engine")  # Relative to workspace root
```

Include directories:

```python
includedirs([
    "include",
    "vendor/glm",
    "%{wks.location}/common/include",  # Using variable expansion
])
```

Library directories:

```python
libdirs([
    "lib",
    "/usr/local/lib",
])
```

Object file directory:

```python
objdir("Build/Obj/%{cfg.buildcfg}/%{prj.name}")
```

Output directory:

```python
targetdir("Build/Bin/%{cfg.buildcfg}")
```

Output file name:

```python
targetname("MyApp")  # Without extension
```

### Dependencies

Link to libraries:

```python
links([
    "MathLib",              # Project in workspace
    "opengl32",             # System library
    "/path/to/custom.lib",  # Absolute path
])
```

Project dependencies (ensures build order):

```python
dependson([
    "Engine",
    "Utilities",
])
```

File dependencies (rebuild when these change):

```python
dependfiles([
    "assets/**",
    "config.json",
])
```

Embed resources (platform-specific):

```python
embedresources([
    "assets/textures/**",
    "data/levels/**",
])
```

### Compiler Settings

Preprocessor defines:

```python
defines([
    "PLATFORM_WINDOWS",
    "VERSION=1",
    "_CRT_SECURE_NO_WARNINGS",
])
```

Optimization level:

```python
optimize("Off")     # No optimization
optimize("Size")    # Optimize for size (-Os)
optimize("Speed")   # Optimize for speed (-O2)
optimize("Full")    # Maximum optimization (-O3)
```

Or use enum:

```python
optimize(Optimization.SPEED)
```

Debug symbols:

```python
symbols("On")   # Enable debug symbols
symbols("Off")  # Disable debug symbols
```

Warning level:

```python
warnings("None")        # No warnings
warnings("Default")     # Default warnings
warnings("All")         # -Wall
warnings("Extra")       # -Wall -Wextra
warnings("Pedantic")    # -Wall -Wextra -Wpedantic
warnings("Everything")  # All warnings
warnings("Error")       # Treat warnings as errors
```

Or use enum:

```python
warnings(WarningLevel.EXTRA)
```

### Precompiled Headers

Enable PCH for faster compilation:

```python
pchheader("pch.h")
pchsource("pch.cpp")  # MSVC requires this
```

### Build Hooks

Execute commands before/after build:

```python
prebuild([
    "python scripts/generate_version.py",
    "echo Building...",
])

postbuild([
    "python scripts/copy_assets.py",
    "echo Build complete!",
])

prelink([
    "echo Linking...",
])

postlink([
    "strip %{cfg.buildtarget.abspath}",  # Strip symbols on Linux
])
```

---

## DSL Function Reference

### Context Managers

#### workspace(name, location="")
Define a workspace (top-level container).

```python
with workspace("MyWorkspace", location="."):
    pass
```

#### project(name)
Define a project within workspace.

```python
with project("MyProject"):
    pass
```

#### toolchain(name, compilerFamily)
Define custom toolchain.

```python
with toolchain("my_gcc", "gcc"):
    ccompiler("/usr/bin/gcc-11")
    cppcompiler("/usr/bin/g++-11")
```

#### newoption(...)
Declare custom CLI options at workspace scope (Premake-like).

```python
with workspace("MyWorkspace"):
    newoption(trigger="with-sdl3", description="Enable SDL3 integration")
    newoption(
        trigger="sdl3-root",
        value="path",
        description="Path to SDL3 package root",
        allowed=["/opt/sdl3", "/vendor/sdl3"],  # optional
    )
```

Usage from CLI:

```bash
Jenga build --with-sdl3 --sdl3-root /opt/sdl3
```

Notes:
- `--flag` sets a boolean-style option.
- `--key=value` and `--key value` are both supported.
- `--no-flag` sets the option value to `false`.
- If an option declares `value=...`, passing it without a value triggers an error.

#### filter(expression)
Apply settings conditionally.

```python
with filter("configurations:Debug"):
    defines(["DEBUG"])
    symbols("On")

with filter("platforms:Windows"):
    links(["user32", "gdi32"])

with filter("configurations:Debug or configurations:RelWithDebInfo"):
    symbols("On")
```

Filter expressions:
- `configurations:Debug` - Match configuration
- `platforms:Windows-x86_64` - Match platform
- `system:Windows` - Match target OS
- `architecture:x86_64` - Match architecture
- `action:build` - Match build action context
- `action:gen-cmake` / `action:gen-vs2022` / `action:gen-xcode` - Match generation action context
- `options:with-sdl3` - Match custom option presence/value
- `options:sdl3-root=*` - Match option value pattern
- `language:C++` - Match language
- Combine with `or`, `and`, `not`

#### unitest()
Configure unit testing framework.

```python
with unitest() as u:
    u.Compile(
        cxxflags=["-fexceptions"],
        ldflags=["-pthread"],
        defines=["UNITEST_CUSTOM"]
    )
```

Or use precompiled mode:

```python
with unitest() as u:
    u.Precompiled()
```

#### test(subname="")
Define test project for current project.

```python
with project("MyLib"):
    staticlib()
    files(["src/**.cpp"])

    with test():
        testfiles(["tests/**.cpp"])
        testoptions(["--verbose"])
```

#### include(jengaFile)
Include external .jenga file.

```python
with include("libs/logger.jenga"):
    pass
```

With project filtering:

```python
with include("external/all_libs.jenga") as inc:
    inc.only(["Logger", "Math"])  # Include only these projects
```

Or exclude:

```python
with include("external/all_libs.jenga") as inc:
    inc.skip(["Deprecated", "Experimental"])
```

#### batchinclude(includes)
Include multiple files at once.

```python
batchinclude([
    "libs/logger.jenga",
    "libs/math.jenga",
    "libs/network.jenga",
])
```

Or with dict for per-file filtering:

```python
batchinclude({
    "libs/logger.jenga": ["Logger"],
    "libs/math.jenga": ["Math", "Geometry"],
    "libs/network.jenga": None,  # Include all
})
```

### Workspace Functions

#### configurations(names)
Set build configurations.

```python
configurations(["Debug", "Release"])
```

#### targetoses(oslist)
Set target operating systems.

```python
targetoses([TargetOS.WINDOWS, TargetOS.LINUX, TargetOS.MACOS])
```

#### targetarchs(archlist)
Set target architectures.

```python
targetarchs([TargetArch.X86_64, TargetArch.ARM64])
```

#### targetos(os) / platform(os)
Set single target OS.

```python
targetos(TargetOS.ANDROID)
```

#### targetarch(arch) / architecture(arch)
Set single target architecture.

```python
targetarch(TargetArch.ARM64)
```

#### startproject(name)
Set startup project for run command.

```python
startproject("MainApp")
```

#### disableunittestcompilation(enable=True)
Disable compilation of unit-test projects (`testsuite`, `isTest`, `__Unitest__`) for this workspace.

```python
disableunittestcompilation(True)
```

#### disableunittestexecution(enable=True)
Disable unit-test execution for this workspace (`jenga test`, and `jenga run` on test projects).

```python
disableunittestexecution(True)
```

### Project Kind Functions

#### consoleapp()
Console application executable.

```python
consoleapp()
```

#### windowedapp()
GUI/windowed application.

```python
windowedapp()
```

#### staticlib()
Static library (.lib, .a).

```python
staticlib()
```

#### sharedlib()
Shared/dynamic library (.dll, .so, .dylib).

```python
sharedlib()
```

#### testsuite()
Test executable.

```python
testsuite()
```

#### kind(k)
Generic kind setter.

```python
kind(ProjectKind.STATIC_LIB)
```

### Language Functions

#### language(lang)
Set programming language.

```python
language("C++")
```

#### cppdialect(dialect) / cppversion(dialect)
Set C++ standard.

```python
cppdialect("C++20")
```

#### cdialect(dialect) / cversion(dialect)
Set C standard.

```python
cdialect("C17")
```

### File Functions

#### location(path)
Set project directory.

```python
location("engine")
```

#### files(patterns)
Add source files.

```python
files(["src/**.cpp", "platform/win32/*.cpp"])
```

#### excludefiles(patterns) / removefiles(patterns)
Exclude files from build.

```python
excludefiles(["src/deprecated/**"])
```

#### excludemainfiles(patterns) / removemainfiles(patterns)
Exclude main entry points.

```python
excludemainfiles(["tests/main.cpp"])
```

#### includedirs(dirs)
Add include directories.

```python
includedirs(["include", "vendor/glm"])
```

#### libdirs(dirs)
Add library search directories.

```python
libdirs(["lib", "%{wks.location}/external/lib"])
```

#### objdir(path)
Set object file directory.

```python
objdir("Build/Obj/%{cfg.buildcfg}")
```

#### targetdir(path)
Set output directory.

```python
targetdir("Build/Bin/%{cfg.buildcfg}")
```

#### targetname(name)
Set output filename (without extension).

```python
targetname("MyApp_v2")
```

### Dependency Functions

#### links(libs)
Link libraries.

```python
links(["MathLib", "opengl32", "pthread"])
```

#### dependson(deps)
Set project dependencies.

```python
dependson(["Engine", "Core"])
```

#### dependfiles(patterns)
Set file dependencies.

```python
dependfiles(["assets/**", "config.json"])
```

#### embedresources(resources)
Embed resources (platform-specific).

```python
embedresources(["assets/**"])
```

### Compiler Settings Functions

#### defines(defs)
Add preprocessor defines.

```python
defines(["DEBUG", "PLATFORM_WINDOWS", "VERSION=2"])
```

#### optimize(level)
Set optimization level.

```python
optimize("Speed")  # Or Optimization.SPEED
```

#### symbols(enable)
Enable/disable debug symbols.

```python
symbols("On")  # Or symbols(True)
```

#### warnings(level)
Set warning level.

```python
warnings("Extra")  # Or WarningLevel.EXTRA
```

### PCH Functions

#### pchheader(header)
Set precompiled header file.

```python
pchheader("stdafx.h")
```

#### pchsource(source)
Set PCH source (MSVC only).

```python
pchsource("stdafx.cpp")
```

### Build Hook Functions

#### prebuild(cmds)
Commands before build.

```python
prebuild(["python generate.py"])
```

#### postbuild(cmds)
Commands after build.

```python
postbuild(["echo Done!"])
```

#### prelink(cmds)
Commands before linking.

```python
prelink(["echo Linking..."])
```

#### postlink(cmds)
Commands after linking.

```python
postlink(["strip %{cfg.buildtarget}"])
```

### Toolchain Functions

#### usetoolchain(name)
Use specific toolchain.

```python
usetoolchain("my_clang")
```

#### settarget(os, arch, env=None)
Set toolchain target (within toolchain context).

```python
with toolchain("cross", "gcc"):
    settarget("Linux", "x86_64", "gnu")
```

#### sysroot(path)
Set sysroot path.

```python
sysroot("/opt/sysroots/arm-linux-gnueabihf")
```

#### targettriple(triple)
Set LLVM target triple.

```python
targettriple("aarch64-linux-gnu")
```

#### ccompiler(path)
Set C compiler path.

```python
ccompiler("/usr/bin/clang-14")
```

#### cppcompiler(path)
Set C++ compiler path.

```python
cppcompiler("/usr/bin/clang++-14")
```

#### linker(path)
Set linker path.

```python
linker("/usr/bin/ld.lld")
```

#### archiver(path)
Set archiver/lib tool path.

```python
archiver("/usr/bin/llvm-ar")
```

#### addcflag(flag)
Add single C compiler flag.

```python
addcflag("-ffast-math")
```

#### addcxxflag(flag)
Add single C++ compiler flag.

```python
addcxxflag("-fno-rtti")
```

#### addldflag(flag)
Add single linker flag.

```python
addldflag("-Wl,--gc-sections")
```

#### cflags(flags)
Set C compiler flags.

```python
cflags(["-O3", "-march=native"])
```

#### cxxflags(flags)
Set C++ compiler flags.

```python
cxxflags(["-std=c++20", "-fno-exceptions"])
```

#### ldflags(flags)
Set linker flags.

```python
ldflags(["-static", "-pthread"])
```

#### asmflags(flags)
Set assembler flags.

```python
asmflags(["-march=armv8-a"])
```

#### arflags(flags)
Set archiver flags.

```python
arflags(["rcs"])
```

### Framework Functions (macOS/iOS)

#### framework(name)
Link framework.

```python
framework("Cocoa")
```

#### frameworkpath(path)
Add framework search path.

```python
frameworkpath("/System/Library/Frameworks")
```

#### librarypath(path) / library(lib)
Add library path or link library.

```python
librarypath("/usr/local/lib")
library("pthread")
```

#### rpath(path)
Set runtime library path.

```python
rpath("@loader_path")
```

### Code Generation Functions

#### sanitize(san)
Enable sanitizer.

```python
sanitize("address")  # AddressSanitizer
sanitize("thread")   # ThreadSanitizer
sanitize("undefined") # UndefinedBehaviorSanitizer
sanitize("memory")   # MemorySanitizer
```

#### nostdlib()
Don't link standard library.

```python
nostdlib()
```

#### nostdinc()
Don't use standard includes.

```python
nostdinc()
```

#### pic()
Position-independent code.

```python
pic()
```

#### pie()
Position-independent executable.

```python
pie()
```

### Build Preset Functions

#### debug()
Debug configuration preset.

```python
debug()  # Equivalent to: optimize("Off"); symbols("On")
```

#### release()
Release configuration preset.

```python
release()  # Equivalent to: optimize("Full"); symbols("Off")
```

#### reldebinfo()
Release with debug info.

```python
reldebinfo()  # Equivalent to: optimize("Speed"); symbols("On")
```

#### minsizerel()
Minimum size release.

```python
minsizerel()  # Equivalent to: optimize("Size"); symbols("Off")
```

### Debug Format Functions

#### debuggdb()
GDB debug format.

```python
debuggdb()  # Adds -ggdb
```

#### debuglldb()
LLDB debug format.

```python
debuglldb()  # Adds -glldb
```

#### debugcodeview()
CodeView debug format (MSVC).

```python
debugcodeview()  # Adds /Zi /DEBUG
```

### Profiling Functions

#### profilegprof()
Enable gprof profiling.

```python
profilegprof()  # Adds -pg
```

#### profilevs()
Enable Visual Studio profiler.

```python
profilevs()  # Adds /PROFILE
```

#### profileinstruments()
Enable Xcode Instruments profiling.

```python
profileinstruments()
```

### Coverage Functions

#### coveragegcov()
Enable gcov coverage.

```python
coveragegcov()  # Adds -fprofile-arcs -ftest-coverage
```

#### coveragevs()
Enable Visual Studio coverage.

```python
coveragevs()
```

### Sanitizer Preset Functions

#### sanitizeaddress()
AddressSanitizer.

```python
sanitizeaddress()
```

#### sanitizethread()
ThreadSanitizer.

```python
sanitizethread()
```

#### sanitizeundefined()
UndefinedBehaviorSanitizer.

```python
sanitizeundefined()
```

#### sanitizememory()
MemorySanitizer (Clang).

```python
sanitizememory()
```

### Build Options Functions

#### buildoption(option, values)
Add single build option.

```python
buildoption("EnableAssertions", ["true", "false"])
```

#### buildoptions(opts)
Add multiple build options.

```python
buildoptions({
    "EnableAssertions": "true",
    "MemoryModel": ["Default", "Custom"],
})
```

### Android Functions

#### androidsdkpath(path)
Set Android SDK path.

```python
androidsdkpath("/path/to/android-sdk")
```

#### androidndkpath(path)
Set Android NDK path.

```python
androidndkpath("/path/to/android-ndk")
```

#### javajdkpath(path)
Set Java JDK path.

```python
javajdkpath("/path/to/jdk")
```

#### androidapplicationid(appid)
Set application package name.

```python
androidapplicationid("com.mycompany.myapp")
```

#### androidversioncode(code)
Set version code (integer).

```python
androidversioncode(1)
```

#### androidversionname(name)
Set version string.

```python
androidversionname("1.0.0")
```

#### androidminsdk(sdk)
Set minimum SDK API level.

```python
androidminsdk(21)  # Android 5.0
```

#### androidtargetsdk(sdk)
Set target SDK API level.

```python
androidtargetsdk(34)  # Android 14
```

#### androidcompilesdk(sdk)
Set compile SDK API level.

```python
androidcompilesdk(34)
```

#### androidabis(abis)
Set target ABIs.

```python
androidabis(["arm64-v8a", "armeabi-v7a", "x86", "x86_64"])
```

#### androidproguard(enable=True)
Enable ProGuard/R8 obfuscation.

```python
androidproguard(True)
```

#### androidproguardrules(rules)
Add ProGuard rules.

```python
androidproguardrules([
    "-keep class com.myapp.** { *; }",
    "-dontwarn javax.annotation.**",
])
```

#### androidassets(patterns)
Add asset patterns.

```python
androidassets(["assets/**"])
```

#### androidpermissions(perms)
Add permissions to manifest.

```python
androidpermissions([
    "android.permission.INTERNET",
    "android.permission.WRITE_EXTERNAL_STORAGE",
])
```

#### androidnativeactivity(enable=True)
Use NativeActivity entry point.

```python
androidnativeactivity(True)
```

#### ndkversion(ver)
Set NDK version.

```python
ndkversion("25.1.8937393")
```

#### androidsign(enable=True)
Enable APK signing.

```python
androidsign(True)
```

#### androidkeystore(path)
Set keystore path.

```python
androidkeystore("release.keystore")
```

#### androidkeystorepass(pwd)
Set keystore password.

```python
androidkeystorepass("mypassword")
```

#### androidkeyalias(alias)
Set key alias.

```python
androidkeyalias("mykey")
```

### iOS Functions

#### iosbundleid(bid)
Set bundle identifier.

```python
iosbundleid("com.mycompany.myapp")
```

#### iosversion(ver)
Set version string.

```python
iosversion("1.0.0")
```

#### iosminsdk(sdk)
Set minimum SDK version.

```python
iosminsdk("14.0")
```

#### iossigningidentity(identity)
Set code signing identity.

```python
iossigningidentity("iPhone Developer")
```

#### iosentitlements(path)
Set entitlements file path.

```python
iosentitlements("MyApp.entitlements")
```

#### iosappicon(icon)
Set app icon path.

```python
iosappicon("Assets.xcassets/AppIcon.appiconset")
```

#### iosbuildnumber(number)
Set build number.

```python
iosbuildnumber(1)
```

### Emscripten Functions

#### emscriptenshellfile(path)
Set HTML template.

```python
emscriptenshellfile("template.html")
```

#### emscriptencanvasid(canvas_id)
Set canvas element ID.

```python
emscriptencanvasid("canvas")
```

#### emscripteninitialmemory(mb)
Set initial memory in MB.

```python
emscripteninitialmemory(256)
```

#### emscriptenstacksize(mb)
Set stack size in MB.

```python
emscriptenstacksize(5)
```

#### emscriptenexportname(name)
Set export name.

```python
emscriptenexportname("Module")
```

#### emscriptenextraflags(flags)
Add extra emcc flags.

```python
emscriptenextraflags(["-s ALLOW_MEMORY_GROWTH=1"])
```

### Test Functions

#### testoptions(opts)
Set test options.

```python
testoptions(["--verbose", "--color"])
```

#### testfiles(patterns)
Add test file patterns.

```python
testfiles(["tests/**.cpp"])
```

#### testmainfile(mainfile)
Set test main file.

```python
testmainfile("tests/custom_main.cpp")
```

#### testmaintemplate(tmpl)
Set test main template.

```python
testmaintemplate("custom")
```

### Project Introspection Functions

#### useproject(projectname, copyincludes=True, copydefines=True)
Copy settings from another project.

```python
useproject("BaseLib", copyincludes=True, copydefines=True)
```

#### getprojectproperties(projectname=None)
Get project properties as dict.

```python
props = getprojectproperties("MyLib")
print(props["includedirs"])
```

### Include Utility Functions

#### includefromdirectory(directory, pattern="*.jenga")
Include all .jenga files from directory.

```python
includefromdirectory("libs", "*.jenga")
```

#### listincludes() / lip()
List all included projects.

```python
listincludes()
```

#### getincludeinfo(projectname)
Get information about included project.

```python
info = getincludeinfo("Logger")
```

#### validateincludes() / vip()
Validate all dependencies.

```python
validateincludes()
```

#### getincludedprojects()
Get all included projects as dict.

```python
projects = getincludedprojects()
```

#### generatedependencyreport(filepath="DEPENDENCIES.md")
Generate dependency markdown report.

```python
generatedependencyreport("DEPENDENCIES.md")
```

#### listallprojects()
List all projects with basic info.

```python
listallprojects()
```

### Utility Functions

#### getcurrentworkspace()
Get current workspace object.

```python
wks = getcurrentworkspace()
print(wks.name)
```

#### resetstate()
Reset global state (advanced).

```python
resetstate()
```

---

## Build Commands

### Jenga build

Compile workspace or specific project.

```bash
Jenga build [options]
```

**Options:**
- `--config <name>` or `-c <name>`: Build configuration (Debug, Release, etc.)
- `--platform <platform>`: Target platform (e.g., Windows-x86_64, Linux-ARM64)
- `--target <project>`: Build specific project
- `--action <name>`: Action context used by `filter("action:...")` (default: `build`)
- `--android-build-system <native|ndk-mk>`: Android build flow selector
- `--use-android-mk`: Shortcut for `--android-build-system ndk-mk`
- `--android-ndk-mk-mode <split|universal|both>`: ndk-mk APK output strategy
- `--android-abis <list>`: Override ABIs for Android build (`arm64-v8a,x86_64`, etc.)
- `--no-cache`: Disable caching
- `--verbose` or `-v`: Verbose output
- `--no-daemon`: Don't use daemon for incremental builds
- `--jenga-file <file>`: Specify .jenga file (default: auto-detect)
- `--<custom-option>`: Any `newoption(...)` declared in workspace is accepted (`--foo`, `--foo=bar`, `--foo bar`, `--no-foo`)

**Examples:**

```bash
# Build all projects in Release configuration
Jenga build --config Release

# Build specific project
Jenga build --target MyApp

# Cross-compile for Linux ARM64
Jenga build --platform Linux-ARM64

# Android build using Android.mk / ndk-build
Jenga build --platform Android-arm64 --target SDL3NativeDemo --android-build-system ndk-mk

# Android ndk-mk: split APKs + universal APK in one pass (default for multi-ABI)
Jenga build --platform Android-arm64 --target SDL3NativeDemo \
  --android-build-system ndk-mk \
  --android-ndk-mk-mode both \
  --android-abis armeabi-v7a,arm64-v8a,x86,x86_64

# Custom option values used by filter("options:...")
Jenga build --with-sdl3 --sdl3-root /opt/sdl3

# Verbose build with no cache
Jenga build --verbose --no-cache
```

**Aliases:** `Jenga b`

### Option-Driven Android ndk-mk Workflow

This pattern combines `newoption(...)`, `filter("options:...")`, `filter("action:...")`, and Android.mk mode.

```python
from Jenga import *

with workspace("AndroidSDL3"):
    targetoses([TargetOS.ANDROID])
    targetarchs([TargetArch.ARM64, TargetArch.X86_64])

    newoption(trigger="with-sdl3", description="Enable SDL3 integration")
    newoption(trigger="sdl3-root", value="path", description="Path to SDL3 package root")

    with project("SDL3NativeDemo"):
        windowedapp()
        language("C++")
        files(["src/**.cpp"])
        androidnativeactivity(True)

        with filter("options:with-sdl3"):
            defines(["USE_SDL3"])

        with filter("options:sdl3-root=*"):
            defines(["SDL3_ROOT_FROM_OPTION"])

        with filter("action:build and options:android-build-system=ndk-mk"):
            defines(["JENGA_ANDROID_NDK_MK_FLOW"])
```

Build commands:

```bash
# Default Jenga Android native flow
Jenga build --platform Android-arm64 --target SDL3NativeDemo

# Android.mk/ndk-build flow
Jenga build --platform Android-arm64 --target SDL3NativeDemo --android-build-system ndk-mk

# Android.mk/ndk-build with split output only (APK per ABI)
Jenga build --platform Android-arm64 --target SDL3NativeDemo \
  --android-build-system ndk-mk \
  --android-ndk-mk-mode split \
  --android-abis arm64-v8a,x86_64

# Android.mk/ndk-build with universal APK only
Jenga build --platform Android-arm64 --target SDL3NativeDemo \
  --android-build-system ndk-mk \
  --android-ndk-mk-mode universal \
  --android-abis arm64-v8a,x86_64

# Option values for filters
Jenga build --platform Android-arm64 --target SDL3NativeDemo \
  --android-build-system ndk-mk \
  --with-sdl3 --sdl3-root /absolute/path/to/SDL3-android
```

### Jenga run

Execute built application.

```bash
Jenga run [project] [options] [-- args]
```

**Options:**
- `--config <name>`: Configuration to run
- `--platform <platform>`: Platform to run
- `--args <args>`: Arguments to pass to executable
- `--no-build`: Don't rebuild before running
- `--jenga-file <file>`: Specify .jenga file

**Examples:**

```bash
# Run startup project
Jenga run

# Run specific project
Jenga run MyApp

# Pass arguments to application
Jenga run MyApp -- --verbose --input=data.txt

# Run without rebuilding
Jenga run --no-build
```

**Aliases:** `Jenga r`

### Jenga test

Run unit tests.

```bash
Jenga test [options]
```

**Options:**
- `--config <name>`: Test configuration
- `--platform <platform>`: Test platform
- `--project <project>`: Test specific project
- `--no-build`: Don't rebuild before testing
- `--verbose`: Verbose test output

**Examples:**

```bash
# Run all tests
Jenga test

# Run tests for specific project
Jenga test --project Calculator

# Verbose test output
Jenga test --verbose
```

**Aliases:** `Jenga t`

### Jenga clean

Remove build artifacts.

```bash
Jenga clean [options]
```

**Options:**
- `--config <name>`: Clean specific configuration
- `--platform <platform>`: Clean specific platform
- `--project <project>`: Clean specific project
- `--all`: Clean everything including cache

**Examples:**

```bash
# Clean all build artifacts
Jenga clean

# Clean everything including cache
Jenga clean --all

# Clean specific configuration
Jenga clean --config Debug
```

**Aliases:** `Jenga c`

### Jenga rebuild

Clean and build.

```bash
Jenga rebuild [options]
```

Same options as `build`.

**Example:**

```bash
Jenga rebuild --config Release
```

### Jenga watch

Watch files and rebuild on changes.

```bash
Jenga watch [options]
```

**Options:**
- `--config <name>`: Watch configuration
- `--platform <platform>`: Watch platform
- `--interval <seconds>`: Watch interval (default: 1)

**Example:**

```bash
Jenga watch --config Debug
```

**Aliases:** `Jenga w`

### Jenga info

Display workspace information.

```bash
Jenga info [options]
```

**Options:**
- `--verbose`: Show detailed information
- `--jenga-file <file>`: Specify .jenga file

**Example:**

```bash
Jenga info --verbose
```

**Aliases:** `Jenga i`

### Jenga gen

Generate project files.

```bash
Jenga gen [options]
```

**Options:**
- `--all`: Generate all supported outputs
- `--cmake`: Generate `CMakeLists.txt`
- `--makefile`: Generate `Makefile`
- `--mk`: Generate `<Workspace>.mk` include file
- `--android-mk`: Generate `Android.mk` and `Application.mk`
- `--vs2022`: Generate Visual Studio 2022 solution
- `--xcode`: Generate Xcode project (`.xcodeproj`)
- `--config <name>`: Generation context configuration for filters
- `--platform <platform>`: Generation context platform for filters
- `--output <dir>`: Output directory (default: current)
- `--jenga-file <file>`: Specify .jenga file

**Examples:**

```bash
# Generate CMake files
Jenga gen --cmake

# Generate Visual Studio solution
Jenga gen --vs2022

# Generate Android ndk-build files
Jenga gen --android-mk

# Generate to specific directory
Jenga gen --cmake --output build_cmake

# Generate everything
Jenga gen --all --output build_exports
```

### Jenga init / Jenga workspace

Create new workspace.

```bash
Jenga init <name>
# or
Jenga workspace
```

Interactive mode guides through workspace creation.

**Example:**

```bash
Jenga workspace
```

### Jenga create / Jenga project

Create new project in existing workspace.

```bash
Jenga create <name> [options]
# or
Jenga project
```

**Options:**
- `--kind <kind>`: Project kind (console, windowed, staticlib, sharedlib, test)
- `--lang <language>`: Language (C, C++, etc.)
- `--location <dir>`: Project directory

**Examples:**

```bash
# Interactive mode
Jenga project

# Direct mode
Jenga create MyLib --kind staticlib --lang C++
```

### Jenga add / Jenga file

Add files to existing project.

```bash
Jenga add [project] [options]
# or
Jenga file
```

**Options:**
- `--src <patterns>`: Add source files
- `--inc <dirs>`: Add include directories
- `--link <libs>`: Add libraries
- `--def <defines>`: Add defines
- `--interactive`: Interactive mode

**Examples:**

```bash
# Interactive mode
Jenga file

# Add source files
Jenga add MyProject --src "new_module/*.cpp"

# Add include directories
Jenga add MyProject --inc "vendor/includes"
```

### Jenga package

Package application for distribution.

```bash
Jenga package [options]
```

**Options:**
- `--config <name>`: Configuration to package
- `--platform <platform>`: Platform to package
- `--output <dir>`: Output directory

**Examples:**

```bash
# Package Android APK
Jenga package --platform Android-ARM64

# Package iOS IPA
Jenga package --platform iOS-ARM64
```

### Jenga deploy

Deploy to device.

```bash
Jenga deploy [options]
```

**Options:**
- `--device <id>`: Device ID
- `--platform <platform>`: Target platform

**Examples:**

```bash
# Deploy to Android device
Jenga deploy --platform Android

# Deploy to specific iOS device
Jenga deploy --platform iOS --device <udid>
```

### Jenga sign

Code signing (Android/iOS).

```bash
Jenga sign <file> [options]
```

**Options:**
- `--keystore <path>`: Keystore path (Android)
- `--alias <alias>`: Key alias (Android)
- `--identity <identity>`: Signing identity (iOS)

**Examples:**

```bash
# Sign Android APK
Jenga sign app.apk --keystore release.keystore --alias mykey

# Sign iOS IPA
Jenga sign app.ipa --identity "iPhone Developer"
```

**Aliases:** `Jenga s`

### Jenga keygen

Generate Android keystore.

```bash
Jenga keygen [options]
```

**Options:**
- `--output <path>`: Keystore output path
- `--alias <alias>`: Key alias
- `--name <name>`: Certificate name

**Example:**

```bash
Jenga keygen --output release.keystore --alias mykey
```

**Aliases:** `Jenga k`

### Jenga docs

Generate API documentation.

```bash
Jenga docs [subcommand] [options]
```

**Subcommands:**
- `extract`: Extract documentation from source
- `stats`: Show documentation statistics
- `list`: List documented elements
- `clean`: Clean generated docs

**Options:**
- `--project <name>`: Document specific project
- `--output <dir>`: Output directory (default: docs/)
- `--format <format>`: Output format (markdown, html, pdf, all)
- `--include-private`: Include private members
- `--verbose`: Verbose output

**Examples:**

```bash
# Extract documentation
Jenga docs extract

# Generate HTML documentation
Jenga docs extract --format html

# Show statistics
Jenga docs stats
```

**Aliases:** `Jenga d`

### Jenga profile

Performance profiling.

```bash
Jenga profile [options]
```

**Options:**
- `--tool <tool>`: Profiling tool (gprof, vs, instruments)
- `--output <file>`: Profile output file

**Example:**

```bash
Jenga profile --tool gprof
```

### Jenga bench

Run benchmarks.

```bash
Jenga bench [options]
```

**Options:**
- `--iterations <n>`: Number of iterations
- `--output <file>`: Benchmark results file

**Example:**

```bash
Jenga bench --iterations 1000
```

### Jenga config

Manage global configuration.

```bash
Jenga config <subcommand> [args]
```

**Subcommands:**
- `init`: Initialize configuration
- `show`: Show current settings
- `set <key> <value>`: Set value
- `get <key>`: Get value
- `toolchain add <name> <file>`: Register toolchain
- `toolchain list`: List toolchains
- `toolchain remove <name>`: Remove toolchain
- `sysroot add <name> <path> --os <os> --arch <arch>`: Register sysroot
- `sysroot list`: List sysroots
- `sysroot remove <name>`: Remove sysroot

**Examples:**

```bash
# Initialize config
Jenga config init

# Show all settings
Jenga config show

# Set max parallel jobs
Jenga config set max_parallel_jobs 8

# Register custom toolchain
Jenga config toolchain add my_gcc toolchain.json

# Register sysroot
Jenga config sysroot add rpi_sysroot /opt/rpi --os Linux --arch ARM
```

### Jenga help

Display help information.

```bash
Jenga help [command]
```

**Examples:**

```bash
# General help
Jenga help

# Command-specific help
Jenga help build
```

**Aliases:** `Jenga h`

---

## Toolchains and Cross-Compilation

### Understanding Toolchains

A **toolchain** is a collection of tools (compiler, linker, archiver) configured for a specific target platform. Jenga automatically detects system toolchains but also supports custom toolchains.

### Auto-Detected Toolchains

Jenga automatically detects:
- **Windows**: MSVC (Visual Studio), Clang, MinGW
- **Linux**: GCC, Clang
- **macOS**: Apple Clang
- **Android**: Android NDK (via environment variables)
- **Emscripten**: Emscripten SDK

### Custom Toolchain Definition

Define custom toolchain in .jenga file:

```python
with toolchain("my_clang", "clang"):
    settarget("Linux", "x86_64", "gnu")
    ccompiler("/usr/bin/clang-14")
    cppcompiler("/usr/bin/clang++-14")
    linker("/usr/bin/ld.lld")
    archiver("/usr/bin/llvm-ar")
    cflags(["-march=native"])
    cxxflags(["-std=c++20", "-march=native"])
    ldflags(["-fuse-ld=lld"])
```

Use in project:

```python
with project("MyApp"):
    consoleapp()
    usetoolchain("my_clang")
    files(["src/**.cpp"])
```

### Cross-Compilation

Cross-compile by specifying different target OS/arch:

```python
with workspace("CrossCompile"):
    configurations(["Release"])
    targetoses([TargetOS.LINUX])
    targetarchs([TargetArch.ARM64])

    with toolchain("aarch64-gcc", "gcc"):
        settarget("Linux", "ARM64", "gnu")
        targettriple("aarch64-linux-gnu")
        sysroot("/opt/sysroots/aarch64-linux-gnu")
        ccompiler("aarch64-linux-gnu-gcc")
        cppcompiler("aarch64-linux-gnu-g++")
        linker("aarch64-linux-gnu-g++")
        archiver("aarch64-linux-gnu-ar")

    usetoolchain("aarch64-gcc")

    with project("MyApp"):
        consoleapp()
        files(["src/**.cpp"])
```

### Zig for Cross-Compilation

Zig provides built-in cross-compilation:

```python
with workspace("ZigCross"):
    configurations(["Release"])
    targetoses([TargetOS.LINUX])
    targetarchs([TargetArch.X86_64])

    with toolchain("zig-linux-x64", "clang"):
        settarget("Linux", "x86_64", "gnu")
        targettriple("x86_64-linux-gnu")
        ccompiler("zig cc")
        cppcompiler("zig c++")
        linker("zig c++")
        archiver("zig ar")
        cflags(["-target", "x86_64-linux-gnu"])
        cxxflags(["-target", "x86_64-linux-gnu"])
        ldflags(["-target", "x86_64-linux-gnu"])

    usetoolchain("zig-linux-x64")

    with project("MyApp"):
        consoleapp()
        files(["src/**.cpp"])
```

### Sysroot Configuration

For cross-compilation, specify sysroot containing target system headers/libraries:

```python
sysroot("/opt/sysroots/armv7-linux-gnueabihf")
includedirs(["%{toolchain.sysroot}/usr/include"])
libdirs(["%{toolchain.sysroot}/usr/lib"])
```

### Target Triple Format

LLVM target triple format: `<arch>-<vendor>-<os>-<env>`

Examples:
- `x86_64-pc-windows-msvc` - Windows x64 MSVC
- `x86_64-unknown-linux-gnu` - Linux x64 GNU
- `aarch64-apple-darwin` - macOS ARM64
- `armv7a-linux-androideabi21` - Android ARMv7 API 21
- `wasm32-unknown-emscripten` - WebAssembly Emscripten

---

## Platform-Specific Development

### Windows Development

#### MSVC Configuration

```python
with workspace("WindowsApp"):
    configurations(["Debug", "Release"])
    targetoses([TargetOS.WINDOWS])
    targetarchs([TargetArch.X86_64])

    with project("WinApp"):
        windowedapp()
        language("C++")
        cppdialect("C++17")
        files(["src/**.cpp"])
        includedirs(["include"])
        links(["user32", "gdi32", "kernel32"])

        with filter("configurations:Debug"):
            defines(["_DEBUG", "WIN32", "_WINDOWS"])
            symbols("On")
            optimize("Off")

        with filter("configurations:Release"):
            defines(["NDEBUG", "WIN32", "_WINDOWS"])
            symbols("Off")
            optimize("Speed")
```

#### Win32 API Example

```cpp
// main.cpp
#include <windows.h>

LRESULT CALLBACK WindowProc(HWND hwnd, UINT uMsg, WPARAM wParam, LPARAM lParam) {
    switch (uMsg) {
        case WM_DESTROY:
            PostQuitMessage(0);
            return 0;
    }
    return DefWindowProc(hwnd, uMsg, wParam, lParam);
}

int WINAPI WinMain(HINSTANCE hInstance, HINSTANCE, LPSTR, int nCmdShow) {
    // Register window class
    WNDCLASS wc = {};
    wc.lpfnWndProc = WindowProc;
    wc.hInstance = hInstance;
    wc.lpszClassName = L"MyWindowClass";
    RegisterClass(&wc);

    // Create window
    HWND hwnd = CreateWindowEx(
        0, L"MyWindowClass", L"Hello Jenga",
        WS_OVERLAPPEDWINDOW, CW_USEDEFAULT, CW_USEDEFAULT,
        800, 600, NULL, NULL, hInstance, NULL
    );

    ShowWindow(hwnd, nCmdShow);

    // Message loop
    MSG msg = {};
    while (GetMessage(&msg, NULL, 0, 0)) {
        TranslateMessage(&msg);
        DispatchMessage(&msg);
    }

    return 0;
}
```

### Linux Development

#### X11 Application

```python
with workspace("LinuxApp"):
    configurations(["Debug", "Release"])
    targetoses([TargetOS.LINUX])
    targetarchs([TargetArch.X86_64])

    with project("X11Window"):
        windowedapp()
        language("C++")
        files(["src/**.cpp"])
        links(["X11"])

        with filter("configurations:Debug"):
            symbols("On")
            optimize("Off")

        with filter("configurations:Release"):
            symbols("Off")
            optimize("Speed")
```

#### X11 Example

```cpp
// main.cpp
#include <X11/Xlib.h>
#include <cstdlib>

int main() {
    Display* display = XOpenDisplay(NULL);
    if (!display) return 1;

    int screen = DefaultScreen(display);
    Window window = XCreateSimpleWindow(
        display, RootWindow(display, screen),
        10, 10, 800, 600, 1,
        BlackPixel(display, screen),
        WhitePixel(display, screen)
    );

    XSelectInput(display, window, ExposureMask | KeyPressMask);
    XMapWindow(display, window);

    XEvent event;
    while (true) {
        XNextEvent(display, &event);
        if (event.type == KeyPress) break;
    }

    XCloseDisplay(display);
    return 0;
}
```

### macOS Development

#### Cocoa Application

```python
with workspace("MacApp"):
    configurations(["Debug", "Release"])
    targetoses([TargetOS.MACOS])
    targetarchs([TargetArch.X86_64, TargetArch.ARM64])

    with toolchain("apple_clang", "apple-clang"):
        settarget("macOS", "x86_64")
        framework("Cocoa")

    usetoolchain("apple_clang")

    with project("CocoaWindow"):
        windowedapp()
        language("Objective-C++")
        files(["src/**.mm"])
```

#### Cocoa Example

```objc
// main.mm
#import <Cocoa/Cocoa.h>

int main(int argc, const char * argv[]) {
    @autoreleasepool {
        [NSApplication sharedApplication];

        NSWindow *window = [[NSWindow alloc]
            initWithContentRect:NSMakeRect(0, 0, 800, 600)
            styleMask:(NSWindowStyleMaskTitled |
                      NSWindowStyleMaskClosable |
                      NSWindowStyleMaskResizable)
            backing:NSBackingStoreBuffered
            defer:NO];

        [window setTitle:@"Hello Jenga"];
        [window center];
        [window makeKeyAndOrderFront:nil];

        [NSApp run];
    }
    return 0;
}
```

### Android Development

#### Android NDK Setup

```python
import os
from Jenga import *

with workspace("AndroidApp"):
    configurations(["Debug", "Release"])
    targetoses([TargetOS.ANDROID])
    targetarchs([TargetArch.ARM64, TargetArch.ARM])

    # SDK/NDK paths from environment
    androidsdkpath(os.getenv("ANDROID_SDK_ROOT", ""))
    androidndkpath(os.getenv("ANDROID_NDK_HOME", ""))
    javajdkpath(os.getenv("JAVA_HOME", ""))

    with project("NativeApp"):
        windowedapp()
        language("C++")
        cppdialect("C++17")
        files(["jni/**.cpp"])
        includedirs(["jni"])

        # Android configuration
        androidapplicationid("com.example.nativeapp")
        androidversioncode(1)
        androidversionname("1.0.0")
        androidminsdk(21)    # Android 5.0
        androidtargetsdk(34)  # Android 14
        androidcompilesdk(34)
        androidabis(["arm64-v8a", "armeabi-v7a"])
        androidnativeactivity(True)
        androidpermissions([
            "android.permission.INTERNET",
        ])

        # Signing
        androidsign(True)
        androidkeystore("release.keystore")
        androidkeyalias("mykey")
        androidkeystorepass("password")
```

#### Native Activity Example

```cpp
// jni/main.cpp
#include <android_native_app_glue.h>
#include <android/log.h>

#define LOG_TAG "NativeApp"
#define LOGI(...) __android_log_print(ANDROID_LOG_INFO, LOG_TAG, __VA_ARGS__)

void android_main(struct android_app* state) {
    LOGI("Starting application");

    while (true) {
        int events;
        struct android_poll_source* source;

        while (ALooper_pollAll(0, NULL, &events, (void**)&source) >= 0) {
            if (source) {
                source->process(state, source);
            }

            if (state->destroyRequested) {
                LOGI("Exiting application");
                return;
            }
        }
    }
}
```

Build APK:

```bash
Jenga build --config Release --platform Android-ARM64
Jenga package --platform Android-ARM64
```

### iOS Development

#### iOS Application Setup

```python
with workspace("iOSApp"):
    configurations(["Debug", "Release"])
    targetoses([TargetOS.IOS])
    targetarchs([TargetArch.ARM64])

    with project("MyiOSApp"):
        windowedapp()
        language("Objective-C++")
        files(["src/**.mm"])

        # iOS configuration
        iosbundleid("com.example.myiosapp")
        iosversion("1.0.0")
        iosminsdk("14.0")
        iosbuildnumber(1)
        iossigningidentity("iPhone Developer")
        iosentitlements("MyiOSApp.entitlements")
```

#### UIKit Example

```objc
// src/main.mm
#import <UIKit/UIKit.h>

@interface AppDelegate : UIResponder <UIApplicationDelegate>
@property (strong, nonatomic) UIWindow *window;
@end

@implementation AppDelegate

- (BOOL)application:(UIApplication *)application
    didFinishLaunchingWithOptions:(NSDictionary *)launchOptions {

    self.window = [[UIWindow alloc] initWithFrame:[[UIScreen mainScreen] bounds]];
    self.window.backgroundColor = [UIColor whiteColor];

    UIViewController *viewController = [[UIViewController alloc] init];
    self.window.rootViewController = viewController;

    [self.window makeKeyAndVisible];
    return YES;
}

@end

int main(int argc, char * argv[]) {
    @autoreleasepool {
        return UIApplicationMain(argc, argv, nil, NSStringFromClass([AppDelegate class]));
    }
}
```

### WebAssembly Development

#### Emscripten Setup

```python
with workspace("WasmApp"):
    configurations(["Release"])
    targetoses([TargetOS.WEB])
    targetarchs([TargetArch.WASM32])

    with toolchain("emscripten", "emscripten"):
        settarget("Web", "wasm32")
        ccompiler("emcc")
        cppcompiler("em++")
        archiver("emar")

    usetoolchain("emscripten")

    with project("WebApp"):
        windowedapp()
        language("C++")
        cppdialect("C++17")
        files(["src/**.cpp"])

        # Emscripten options
        emscriptenshellfile("template.html")
        emscriptencanvasid("canvas")
        emscripteninitialmemory(256)
        emscriptenstacksize(5)
        emscriptenexportname("Module")
```

#### WebGL Example

```cpp
// src/main.cpp
#include <emscripten/emscripten.h>
#include <emscripten/html5.h>
#include <GLES2/gl2.h>
#include <cstdio>

void render_frame() {
    glClearColor(0.0f, 0.5f, 1.0f, 1.0f);
    glClear(GL_COLOR_BUFFER_BIT);
}

void main_loop() {
    render_frame();
}

int main() {
    EmscriptenWebGLContextAttributes attrs;
    emscripten_webgl_init_context_attributes(&attrs);

    EMSCRIPTEN_WEBGL_CONTEXT_HANDLE context =
        emscripten_webgl_create_context("#canvas", &attrs);
    emscripten_webgl_make_context_current(context);

    emscripten_set_main_loop(main_loop, 0, 1);
    return 0;
}
```

Build for web:

```bash
Jenga build --config Release --platform Web-WASM32
```

---

## Testing and Quality

### Unit Testing with Unitest

Jenga includes a built-in C++ unit testing framework called **Unitest**.

#### Configuring Unitest

In your .jenga file:

```python
with workspace("MyProject"):
    configurations(["Debug", "Release"])
    targetoses([TargetOS.WINDOWS, TargetOS.LINUX, TargetOS.MACOS])
    targetarchs([TargetArch.X86_64])

    # Configure Unitest framework
    with unitest() as u:
        u.Compile(
            cxxflags=["-fexceptions"],
            ldflags=["-pthread"],
            defines=["UNITEST_VERBOSE"]
        )

    with project("MyLib"):
        staticlib()
        language("C++")
        files(["src/**.cpp"])
        includedirs(["include"])

        # Define test project
        with test():
            testfiles(["tests/**.cpp"])
```

#### Writing Tests

Use `TEST_CASE` macro:

```cpp
// tests/test_math.cpp
#include <Unitest/Unitest.h>
#include <Unitest/TestMacro.h>
#include "math.h"

TEST_CASE(Math, Addition) {
    ASSERT_EQUAL(5, add(2, 3));
    ASSERT_EQUAL(0, add(-1, 1));
    ASSERT_EQUAL(-5, add(-2, -3));
}

TEST_CASE(Math, Subtraction) {
    ASSERT_EQUAL(1, sub(3, 2));
    ASSERT_EQUAL(-1, sub(2, 3));
}

TEST_CASE(Math, Multiplication) {
    ASSERT_EQUAL(6, mul(2, 3));
    ASSERT_EQUAL(0, mul(0, 100));
    ASSERT_EQUAL(-6, mul(-2, 3));
}
```

#### Assertion Macros

- `ASSERT_TRUE(condition)` - Assert condition is true
- `ASSERT_FALSE(condition)` - Assert condition is false
- `ASSERT_EQUAL(expected, actual)` - Assert equality
- `ASSERT_NOT_EQUAL(a, b)` - Assert inequality
- `ASSERT_LESS(a, b)` - Assert a < b
- `ASSERT_LESS_EQUAL(a, b)` - Assert a <= b
- `ASSERT_GREATER(a, b)` - Assert a > b
- `ASSERT_GREATER_EQUAL(a, b)` - Assert a >= b
- `ASSERT_NULL(ptr)` - Assert pointer is null
- `ASSERT_NOT_NULL(ptr)` - Assert pointer is not null
- `ASSERT_THROWS(expr, exception_type)` - Assert expression throws
- `ASSERT_NO_THROW(expr)` - Assert expression doesn't throw

#### Running Tests

```bash
Jenga test
```

Output example:

```
Running tests...
[PASS] Math::Addition
[PASS] Math::Subtraction
[PASS] Math::Multiplication
[FAIL] Math::Division
  Expected: 2
  Actual: 0
  At tests/test_math.cpp:25

====================
Tests: 4
Passed: 3
Failed: 1
Time: 0.05s
```

### Code Coverage

#### Enable Coverage with GCC/Clang

```python
with filter("configurations:Debug"):
    coveragegcov()
```

Or manually:

```python
with filter("configurations:Debug"):
    cxxflags(["--coverage"])
    ldflags(["--coverage"])
```

Generate coverage report:

```bash
Jenga test --config Debug
gcov src/*.cpp
gcovr -r . --html --html-details -o coverage.html
```

### Sanitizers

#### Address Sanitizer

Detect memory errors:

```python
with filter("configurations:Debug"):
    sanitizeaddress()
```

#### Thread Sanitizer

Detect data races:

```python
with filter("configurations:Debug"):
    sanitizethread()
```

#### Undefined Behavior Sanitizer

Detect undefined behavior:

```python
with filter("configurations:Debug"):
    sanitizeundefined()
```

#### Memory Sanitizer

Detect uninitialized reads (Clang only):

```python
with filter("configurations:Debug"):
    sanitizememory()
```

### Profiling

#### gprof Profiling (Linux/GCC)

```python
with filter("configurations:Release"):
    profilegprof()
```

Build and profile:

```bash
Jenga build --config Release
Jenga run
gprof Build/Bin/Release/MyApp gmon.out > analysis.txt
```

#### Visual Studio Profiler (Windows)

```python
with filter("configurations:Release"):
    profilevs()
```

#### Xcode Instruments (macOS)

```python
with filter("configurations:Release"):
    profileinstruments()
```

---

## Advanced Features

### C++20 Modules

Jenga supports C++20 modules:

```python
with workspace("ModulesDemo"):
    configurations(["Debug", "Release"])
    targetoses([TargetOS.WINDOWS])
    targetarchs([TargetArch.X86_64])

    with project("MathModule"):
        staticlib()
        language("C++")
        cppdialect("C++20")
        files([
            "src/math.cppm",  # Module interface
            "src/math.cpp",    # Module implementation
        ])
```

Module interface:

```cpp
// src/math.cppm
export module math;

export int add(int a, int b);
export int multiply(int a, int b);
```

Module implementation:

```cpp
// src/math.cpp
module math;

int add(int a, int b) {
    return a + b;
}

int multiply(int a, int b) {
    return a * b;
}
```

Use module:

```cpp
// main.cpp
import math;
#include <iostream>

int main() {
    std::cout << add(2, 3) << std::endl;
    return 0;
}
```

### Precompiled Headers

Speed up compilation with PCH:

```python
with project("MyApp"):
    consoleapp()
    language("C++")
    files(["src/**.cpp"])

    # Precompiled header
    pchheader("pch.h")
    pchsource("pch.cpp")  # MSVC requires this
```

Create PCH files:

```cpp
// pch.h
#pragma once

// Include frequently used standard library headers
#include <iostream>
#include <string>
#include <vector>
#include <map>
#include <memory>
#include <algorithm>
```

```cpp
// pch.cpp
#include "pch.h"
// Empty file, just includes the header
```

### Variable Expansion

Jenga supports powerful variable expansion:

#### Workspace Variables

- `%{wks.name}` - Workspace name
- `%{wks.location}` - Workspace directory

#### Project Variables

- `%{prj.name}` - Project name
- `%{prj.location}` - Project directory

#### Configuration Variables

- `%{cfg.name}` - Configuration name (Debug, Release, etc.)
- `%{cfg.buildcfg}` - Build configuration

#### Platform Variables

- `%{platform}` - Target platform
- `%{os}` - Target OS
- `%{arch}` - Target architecture

#### Jenga Variables

- `%{Jenga.Root}` - Jenga installation root
- `%{Jenga.Version}` - Jenga version

#### Environment Variables

- `%{env.VARNAME}` - Environment variable

#### Examples

```python
objdir("Build/Obj/%{cfg.buildcfg}/%{prj.name}")
targetdir("Build/Bin/%{cfg.buildcfg}")
includedirs(["%{wks.location}/common/include"])
```

### Filter Expressions

Complex conditional configuration:

```python
# Multiple configurations
with filter("configurations:Debug or configurations:RelWithDebInfo"):
    symbols("On")

# Platform-specific
with filter("system:Windows"):
    links(["user32", "gdi32"])
    defines(["_WIN32"])

with filter("system:Linux"):
    links(["X11", "pthread"])
    defines(["_LINUX"])

# Architecture-specific
with filter("architecture:x86_64"):
    defines(["ARCH_64BIT"])

with filter("architecture:x86"):
    defines(["ARCH_32BIT"])

# Combined filters
with filter("configurations:Release and system:Windows"):
    ldflags(["/LTCG"])  # Link-time code generation
```

### Multi-Project Workspaces

Manage complex dependencies:

```python
with workspace("GameEngine"):
    configurations(["Debug", "Release"])
    targetoses([TargetOS.WINDOWS, TargetOS.LINUX])
    targetarchs([TargetArch.X86_64])
    startproject("Game")

    # Core engine library
    with project("Core"):
        staticlib()
        language("C++")
        location("Core")
        files(["src/**.cpp"])
        includedirs(["include"])

    # Rendering engine
    with project("Renderer"):
        staticlib()
        language("C++")
        location("Renderer")
        files(["src/**.cpp"])
        includedirs(["include", "../Core/include"])
        links(["Core"])
        dependson(["Core"])

    # Physics engine
    with project("Physics"):
        staticlib()
        language("C++")
        location("Physics")
        files(["src/**.cpp"])
        includedirs(["include", "../Core/include"])
        links(["Core"])
        dependson(["Core"])

    # Main game application
    with project("Game"):
        consoleapp()
        language("C++")
        location("Game")
        files(["src/**.cpp"])
        includedirs([
            "../Core/include",
            "../Renderer/include",
            "../Physics/include",
        ])
        links(["Core", "Renderer", "Physics"])
        dependson(["Core", "Renderer", "Physics"])
```

### External Includes

Modularize large projects:

```python
# main.jenga
with workspace("MyWorkspace"):
    configurations(["Debug", "Release"])
    targetoses([TargetOS.WINDOWS, TargetOS.LINUX])
    targetarchs([TargetArch.X86_64])

    # Include external libraries
    with include("libs/logger.jenga"):
        pass

    with include("libs/math.jenga"):
        pass

    # Main application
    with project("App"):
        consoleapp()
        files(["src/main.cpp"])
        includedirs([
            "libs/logger/include",
            "libs/math/include",
        ])
        links(["Logger", "MathLib"])
        dependson(["Logger", "MathLib"])
```

```python
# libs/logger.jenga
with project("Logger"):
    staticlib()
    language("C++")
    location("logger")
    files(["src/**.cpp"])
    includedirs(["include"])
```

### Build Hooks

Execute custom scripts during build:

```python
with project("MyApp"):
    consoleapp()
    files(["src/**.cpp"])

    # Generate version header before build
    prebuild([
        "python scripts/generate_version.py src/version.h",
    ])

    # Copy assets after build
    postbuild([
        "python scripts/copy_assets.py Build/Bin/%{cfg.buildcfg}/assets",
    ])

    # Strip symbols after linking (Release only)
    with filter("configurations:Release"):
        postlink([
            "strip %{cfg.buildtarget.abspath}",
        ])
```

---

## Example Projects Explained

This section provides detailed walkthroughs of all 22 example projects included with Jenga. Each example demonstrates specific features and best practices.

### Example 01: Hello Console

**Location:** `Exemples/01_hello_console/`

**Purpose:** Demonstrates the absolute basics - a simple "Hello World" console application.

**Key Concepts:**
- Basic workspace structure
- Simple console application
- Multi-platform configuration

**Files:**
```
01_hello_console/
├── 01_hello_console.jenga
└── main.cpp
```

**Configuration (.jenga):**
```python
from Jenga import *

with workspace("HelloConsole"):
    configurations(["Debug", "Release"])
    targetoses([TargetOS.WINDOWS, TargetOS.LINUX, TargetOS.MACOS])
    targetarchs([TargetArch.X86_64])

    with project("Hello"):
        consoleapp()
        language("C++")
        files(["**.cpp"])
```

**Source Code (main.cpp):**
```cpp
#include <iostream>

int main() {
    std::cout << "Hello from Jenga!" << std::endl;
    return 0;
}
```

**Building:**
```bash
cd Exemples/01_hello_console
Jenga build
Jenga run
```

**What You Learn:**
- How to create a minimal workspace
- Using `consoleapp()` for console applications
- The `files()` function with glob patterns (`**.cpp` matches all .cpp files recursively)
- Multi-platform targeting with a single configuration

---

### Example 02: Static Library

**Location:** `Exemples/02_static_library/`

**Purpose:** Demonstrates creating a static library and linking it to an application.

**Key Concepts:**
- Static library creation
- Project dependencies
- Include directory management
- Variable expansion (`%{wks.location}`)

**Directory Structure:**
```
02_static_library/
├── 02_static_library.jenga
├── mathlib/
│   ├── include/
│   │   └── mathlib.h
│   └── src/
│       └── mathlib.cpp
└── app/
    └── main.cpp
```

**Configuration:**
```python
from Jenga import *

with workspace("StaticLibraryExample"):
    configurations(["Debug", "Release"])
    targetoses([TargetOS.WINDOWS, TargetOS.LINUX, TargetOS.MACOS])
    targetarchs([TargetArch.X86_64])

    # Static library project
    with project("MathLib"):
        staticlib()
        language("C++")
        location("mathlib")
        files(["src/**.cpp"])
        includedirs(["include"])

    # Application using the library
    with project("App"):
        consoleapp()
        language("C++")
        location("app")
        files(["main.cpp"])
        includedirs(["%{wks.location}/mathlib/include"])
        links(["MathLib"])
        dependson(["MathLib"])
```

**Library Header (mathlib.h):**
```cpp
#pragma once

int add(int a, int b);
int subtract(int a, int b);
int multiply(int a, int b);
```

**Library Implementation (mathlib.cpp):**
```cpp
#include "mathlib.h"

int add(int a, int b) { return a + b; }
int subtract(int a, int b) { return a - b; }
int multiply(int a, int b) { return a * b; }
```

**Application (main.cpp):**
```cpp
#include <iostream>
#include "mathlib.h"

int main() {
    std::cout << "5 + 3 = " << add(5, 3) << std::endl;
    std::cout << "5 - 3 = " << subtract(5, 3) << std::endl;
    std::cout << "5 * 3 = " << multiply(5, 3) << std::endl;
    return 0;
}
```

**What You Learn:**
- Creating static libraries with `staticlib()`
- Using `location()` to organize projects in subdirectories
- Linking libraries with `links()` and `dependson()`
- Variable expansion with `%{wks.location}`
- Proper include directory setup for multi-project workspaces

---

### Example 03: Shared Library

**Location:** `Exemples/03_shared_library/`

**Purpose:** Demonstrates creating dynamic/shared libraries (.dll, .so, .dylib).

**Key Concepts:**
- Shared library creation
- Dynamic linking
- Platform-specific library extensions

**Configuration Difference:**
```python
with project("Greeter"):
    sharedlib()  # Changed from staticlib()
    language("C++")
    location("greeter")
    files(["src/**.cpp"])
    includedirs(["include"])
```

**What You Learn:**
- The difference between static and shared libraries
- Using `sharedlib()` for dynamic libraries
- Platform-specific output: Windows (.dll), Linux (.so), macOS (.dylib)
- Runtime library path considerations

**Best Practice:** For cross-platform shared libraries, ensure proper symbol export/import:

```cpp
// greeter.h
#pragma once

#if defined(_WIN32) || defined(_WIN64)
    #ifdef GREETER_EXPORTS
        #define GREETER_API __declspec(dllexport)
    #else
        #define GREETER_API __declspec(dllimport)
    #endif
#else
    #define GREETER_API
#endif

GREETER_API const char* greet();
```

---

### Example 04: Unit Tests

**Location:** `Exemples/04_unit_tests/`

**Purpose:** Demonstrates the built-in Unitest framework for C++ unit testing.

**Key Concepts:**
- Unitest framework configuration
- Writing test cases with macros
- Test project structure
- Assertion macros

**Configuration:**
```python
with workspace("UnitTestDemo"):
    configurations(["Debug", "Release"])
    targetoses([TargetOS.WINDOWS, TargetOS.LINUX, TargetOS.MACOS])
    targetarchs([TargetArch.X86_64])

    # Configure Unitest
    with unitest() as u:
        u.Compile(cxxflags=["-fexceptions"])

    # Library to test
    with project("Calculator"):
        staticlib()
        language("C++")
        files(["src/**.cpp"])
        includedirs(["include"])

        # Test project
        with test():
            testfiles(["tests/**.cpp"])
```

**Test File (tests/test_calculator.cpp):**
```cpp
#include <Unitest/Unitest.h>
#include <Unitest/TestMacro.h>
#include "calculator.h"

TEST_CASE(Calculator, Add) {
    ASSERT_EQUAL(5, add(2, 3));
    ASSERT_EQUAL(0, add(-1, 1));
    ASSERT_EQUAL(-5, add(-2, -3));
}

TEST_CASE(Calculator, Subtract) {
    ASSERT_EQUAL(1, subtract(3, 2));
    ASSERT_EQUAL(-1, subtract(2, 3));
}

TEST_CASE(Calculator, Multiply) {
    ASSERT_EQUAL(6, multiply(2, 3));
    ASSERT_EQUAL(0, multiply(0, 5));
}

TEST_CASE(Calculator, Divide) {
    ASSERT_EQUAL(2, divide(6, 3));
    ASSERT_EQUAL(5, divide(10, 2));
}
```

**Running Tests:**
```bash
Jenga test
```

**What You Learn:**
- Configuring Unitest with `unitest()` context manager
- Using `test()` to create test projects
- TEST_CASE macro syntax: `TEST_CASE(SuiteName, TestName)`
- Available assertion macros
- Automatic test discovery and execution

---

### Example 05: Android NDK

**Location:** `Exemples/05_android_ndk/`

**Purpose:** Demonstrates building native Android applications using the NDK.

**Key Concepts:**
- Android SDK/NDK configuration
- Native activity
- Multi-ABI builds
- APK packaging

**Configuration:**
```python
import os
from Jenga import *

with workspace("AndroidDemo"):
    configurations(["Debug", "Release"])
    targetoses([TargetOS.ANDROID])
    targetarchs([TargetArch.ARM64, TargetArch.X86_64])

    # SDK/NDK paths from environment variables
    androidsdkpath(os.getenv("ANDROID_SDK_ROOT", ""))
    androidndkpath(os.getenv("ANDROID_NDK_ROOT", os.getenv("ANDROID_NDK_HOME", "")))

    with project("NativeApp"):
        windowedapp()
        language("C++")
        files(["src/**.cpp"])

        # Android-specific configuration
        androidapplicationid("com.Jenga.nativedemo")
        androidminsdk(24)      # Android 7.0
        androidtargetsdk(34)   # Android 14
        androidcompilesdk(34)
        androidabis(["arm64-v8a", "x86_64"])
        androidnativeactivity(True)
```

**Native Code (src/main.cpp):**
```cpp
#include <android_native_app_glue.h>
#include <android/log.h>

#define LOGI(...) __android_log_print(ANDROID_LOG_INFO, "NativeApp", __VA_ARGS__)

void android_main(struct android_app* state) {
    LOGI("Application started");

    while (true) {
        int events;
        struct android_poll_source* source;

        while (ALooper_pollAll(0, NULL, &events, (void**)&source) >= 0) {
            if (source) {
                source->process(state, source);
            }

            if (state->destroyRequested) {
                LOGI("Application exiting");
                return;
            }
        }
    }
}
```

**Building APK:**
```bash
# Set environment variables first
export ANDROID_SDK_ROOT=/path/to/android-sdk
export ANDROID_NDK_HOME=/path/to/android-ndk

# Build
Jenga build --config Release --platform Android-ARM64

# Package APK
Jenga package --platform Android-ARM64
```

**What You Learn:**
- Android SDK/NDK path configuration
- Using `androidapplicationid()` for package naming
- Setting API levels with `androidminsdk()`, `androidtargetsdk()`, `androidcompilesdk()`
- Multi-ABI support with `androidabis()`
- Native activity entry point
- APK packaging workflow

---

### Example 06: iOS App

**Location:** `Exemples/06_ios_app/`

**Purpose:** Demonstrates building iOS applications with Objective-C++.

**Key Concepts:**
- iOS bundle configuration
- Objective-C++ source files (.mm)
- Minimum SDK version
- Code signing configuration

**Configuration:**
```python
with workspace("IOSDemo"):
    configurations(["Debug", "Release"])
    targetoses([TargetOS.IOS])
    targetarchs([TargetArch.ARM64, TargetArch.X86_64])

    with project("IOSApp"):
        windowedapp()
        language("Objective-C++")
        files(["src/**.mm"])

        # iOS-specific settings
        iosbundleid("com.Jenga.iosdemo")
        iosversion("1.0")
        iosminsdk("14.0")
        iosbuildnumber(1)
```

**What You Learn:**
- iOS target configuration
- Bundle identifier setup
- Version and build number management
- Objective-C++ file extension (.mm)
- Simulator vs device builds (x86_64 vs ARM64)

---

### Example 07: WebAssembly

**Location:** `Exemples/07_web_wasm/`

**Purpose:** Demonstrates compiling C++ to WebAssembly using Emscripten.

**Key Concepts:**
- Emscripten toolchain configuration
- WASM32 architecture
- Resource embedding
- Custom shell files

**Configuration:**
```python
with workspace("WebDemo"):
    configurations(["Release"])
    targetoses([TargetOS.WEB])
    targetarchs([TargetArch.WASM32])

    # Emscripten toolchain
    with toolchain("emscripten", "emscripten"):
        settarget("Web", "wasm32")
        ccompiler(r"C:\emsdk-4.0.22\upstream\emscripten\emcc.bat")
        cppcompiler(r"C:\emsdk-4.0.22\upstream\emscripten\em++.bat")
        archiver(r"C:\emsdk-4.0.22\upstream\emscripten\emar.bat")

    usetoolchain("emscripten")

    with project("WasmApp"):
        consoleapp()
        language("C++")
        files(["src/**.cpp"])
        embedresources(["assets/**"])
```

**Source Code:**
```cpp
#include <iostream>

int main() {
    std::cout << "Hello from WebAssembly!" << std::endl;
    return 0;
}
```

**Building:**
```bash
Jenga build --config Release --platform Web-WASM32
```

**Output:** Generates `.wasm`, `.js`, and `.html` files.

**What You Learn:**
- Emscripten SDK integration
- Custom toolchain definition
- Web target configuration
- Resource embedding for web deployment

---

### Example 08: Custom Toolchain

**Location:** `Exemples/08_custom_toolchain/`

**Purpose:** Demonstrates defining and using custom compiler toolchains.

**Key Concepts:**
- Toolchain context manager
- Compiler path specification
- Custom compiler flags
- Target environment selection

**Configuration:**
```python
with workspace("CustomToolchain"):
    configurations(["Debug", "Release"])
    targetoses([TargetOS.WINDOWS])
    targetarchs([TargetArch.X86_64])

    # Define custom Clang toolchain
    with toolchain("ucrt_clang", "clang"):
        settarget("Windows", "x86_64", "mingw")
        ccompiler("clang")
        cppcompiler("clang++")
        linker("clang++")
        archiver("llvm-ar")
        cflags(["-O2"])
        cxxflags(["-O2", "-std=c++20"])

    # Use the custom toolchain
    usetoolchain("ucrt_clang")

    with project("ToolchainDemo"):
        consoleapp()
        language("C++")
        files(["src/**.cpp"])
```

**What You Learn:**
- Creating custom toolchains with `toolchain()` context
- Setting target with `settarget(os, arch, env)`
- Specifying compiler executables
- Adding custom compiler and linker flags
- Using `usetoolchain()` to activate

---

### Example 09: Multi-Projects

**Location:** `Exemples/09_multi_projects/`

**Purpose:** Demonstrates complex workspace with multiple interdependent projects.

**Key Concepts:**
- Multi-project dependency graph
- Startup project configuration
- Shared libraries between projects
- Hierarchical project structure

**Directory Structure:**
```
09_multi_projects/
├── 09_multi_projects.jenga
├── engine/
│   ├── include/
│   └── src/
├── tools/
│   └── src/
└── game/
    └── src/
```

**Configuration:**
```python
with workspace("MultiProjects"):
    configurations(["Debug", "Release"])
    targetoses([TargetOS.WINDOWS, TargetOS.LINUX])
    targetarchs([TargetArch.X86_64])
    startproject("Game")

    # Core engine library
    with project("Engine"):
        staticlib()
        language("C++")
        location("engine")
        files(["src/**.cpp"])
        includedirs(["include"])

    # Utility tools
    with project("Tools"):
        consoleapp()
        language("C++")
        location("tools")
        files(["src/**.cpp"])

    # Main game application
    with project("Game"):
        consoleapp()
        language("C++")
        location("game")
        files(["src/**.cpp"])
        includedirs(["../engine/include"])
        links(["Engine"])
        dependson(["Engine"])
```

**What You Learn:**
- Managing multiple projects in one workspace
- Project dependency chains with `dependson()`
- Setting startup project with `startproject()`
- Organizing projects in subdirectories with `location()`
- Relative include paths between projects

---

### Example 10: C++20 Modules

**Location:** `Exemples/10_modules_cpp20/`

**Purpose:** Demonstrates C++20 modules feature.

**Key Concepts:**
- C++20 module interface files (.cppm)
- Module compilation
- Importing modules
- BMI (Binary Module Interface) generation

**Configuration:**
```python
with workspace("ModulesCpp20"):
    configurations(["Debug", "Release"])
    targetoses([TargetOS.WINDOWS])
    targetarchs([TargetArch.X86_64])

    with project("MathApp"):
        consoleapp()
        language("C++")
        cppdialect("C++20")
        files(["src/math.cppm", "src/main.cpp"])
```

**Module Interface (src/math.cppm):**
```cpp
export module math;

export int add(int a, int b) {
    return a + b;
}

export int multiply(int a, int b) {
    return a * b;
}
```

**Main Application (src/main.cpp):**
```cpp
import math;
#include <iostream>

int main() {
    std::cout << "2 + 3 = " << add(2, 3) << std::endl;
    std::cout << "2 * 3 = " << multiply(2, 3) << std::endl;
    return 0;
}
```

**What You Learn:**
- Enabling C++20 with `cppdialect("C++20")`
- Module interface files (.cppm extension)
- `export module` syntax
- `import` statements
- Jenga's automatic module dependency resolution

**Note:** C++20 modules require:
- MSVC 2019+ (Windows)
- Clang 16+ (Linux/macOS)
- GCC 11+ with experimental support

---

### Example 11: Benchmark

**Location:** `Exemples/11_benchmark/`

**Purpose:** Demonstrates performance benchmarking techniques.

**Key Concepts:**
- High-resolution timing
- Preventing compiler optimizations
- Performance measurement

**Source Code:**
```cpp
#include <chrono>
#include <cstdint>
#include <iostream>

static std::uint64_t work(std::uint64_t n) {
    std::uint64_t sum = 0;
    for (std::uint64_t i = 0; i < n; ++i) {
        sum += (i * 2654435761u) ^ (sum >> 1);
    }
    return sum;
}

int main() {
    auto t0 = std::chrono::high_resolution_clock::now();
    volatile auto result = work(5000000);
    auto t1 = std::chrono::high_resolution_clock::now();

    auto ms = std::chrono::duration_cast<std::chrono::milliseconds>(t1 - t0).count();
    std::cout << "result=" << result << " time_ms=" << ms << std::endl;

    return 0;
}
```

**What You Learn:**
- Using `std::chrono::high_resolution_clock` for timing
- `volatile` keyword to prevent optimization
- Benchmarking loop patterns
- Measuring execution time in milliseconds

---

### Example 12: External Includes

**Location:** `Exemples/12_external_includes/`

**Purpose:** Demonstrates modular workspace organization with external .jenga files.

**Key Concepts:**
- Include external configuration files
- Modular project organization
- Reusable library definitions

**Main Configuration (12_external_includes.jenga):**
```python
with workspace("ExternalIncludesDemo"):
    configurations(["Debug", "Release"])
    targetoses([TargetOS.WINDOWS, TargetOS.LINUX])
    targetarchs([TargetArch.X86_64])

    # Include external project definitions
    with include("libs/logger.jenga"):
        pass

    with include("libs/math.jenga"):
        pass

    # Main application
    with project("App"):
        consoleapp()
        language("C++")
        files(["src/main.cpp"])
        includedirs(["libs/logger/include", "libs/math/include"])
        links(["Logger", "MathLib"])
        dependson(["Logger", "MathLib"])
```

**External File (libs/logger.jenga):**
```python
from Jenga import *

with project("Logger"):
    staticlib()
    language("C++")
    location("logger")
    files(["src/**.cpp"])
    includedirs(["include"])
```

**What You Learn:**
- Using `include()` context manager
- Organizing large projects into multiple .jenga files
- Reusable library configurations
- Workspace modularity

---

### Example 13: Packaging

**Location:** `Exemples/13_packaging/`

**Purpose:** Demonstrates asset packaging and file dependencies.

**Key Concepts:**
- File dependencies
- Asset management
- Packaging workflow

**Configuration:**
```python
with workspace("PackagingDemo"):
    configurations(["Release", "Debug"])
    targetoses([TargetOS.WINDOWS, TargetOS.LINUX])
    targetarchs([TargetArch.X86_64])

    with project("PackApp"):
        consoleapp()
        language("C++")
        files(["src/**.cpp"])
        dependfiles(["assets/**"])
```

**What You Learn:**
- Using `dependfiles()` to track non-source dependencies
- Asset directory patterns
- Triggering rebuilds when assets change

---

### Example 14: Cross-Compile

**Location:** `Exemples/14_cross_compile/`

**Purpose:** Demonstrates cross-compilation for Linux from Windows.

**Key Concepts:**
- Cross-compilation setup
- Target triple specification
- Clang cross-compilation
- Multiple target platforms

**Configuration:**
```python
import os
from Jenga import *

with workspace("CrossCompileDemo"):
    configurations(["Debug", "Release"])
    targetoses([TargetOS.LINUX, TargetOS.ANDROID])
    targetarchs([TargetArch.X86_64, TargetArch.ARM64])

    androidsdkpath(os.getenv("ANDROID_SDK_ROOT", ""))
    androidndkpath(os.getenv("ANDROID_NDK_ROOT", ""))

    # Cross-compilation toolchain for Linux
    with toolchain("linux_cross", "clang"):
        settarget("Linux", "x86_64", "gnu")
        targettriple("x86_64-unknown-linux-gnu")
        ccompiler("clang")
        cppcompiler("clang++")
        linker("clang++")
        archiver("ar")
        cflags(["--target=x86_64-unknown-linux-gnu"])
        cxxflags(["--target=x86_64-unknown-linux-gnu"])
        ldflags(["--target=x86_64-unknown-linux-gnu"])

    usetoolchain("linux_cross")

    with project("CrossCore"):
        staticlib()
        language("C++")
        files(["src/**.cpp"])
```

**What You Learn:**
- Setting up cross-compilation toolchains
- Using `targettriple()` for LLVM target specification
- Clang's `--target` flag for cross-compilation
- Supporting multiple platforms simultaneously

---

### Example 15: Win32 Window

**Location:** `Exemples/15_window_win32/`

**Purpose:** Demonstrates native Windows GUI application using Win32 API.

**Key Concepts:**
- Windowed application
- Win32 API
- System library linking
- Windows-specific code

**Configuration:**
```python
with workspace("Win32WindowDemo"):
    configurations(["Debug", "Release"])
    targetoses([TargetOS.WINDOWS])
    targetarchs([TargetArch.X86_64])

    with project("Win32Window"):
        windowedapp()
        language("C++")
        files(["src/**.cpp"])
        links(["user32", "gdi32"])
```

**What You Learn:**
- Using `windowedapp()` for GUI applications
- Linking Windows system libraries (user32, gdi32)
- Win32 API window creation
- Message loop implementation

---

### Example 16: X11 Window (Linux)

**Location:** `Exemples/16_window_x11_linux/`

**Purpose:** Demonstrates X11 windowed application on Linux.

**Key Concepts:**
- X11 library linking
- Cross-compilation from Windows to Linux
- Sysroot configuration
- Global toolchains

**Configuration:**
```python
from Jenga import *
from Jenga.GlobalToolchains import RegisterJengaGlobalToolchains

with workspace("X11WindowDemo"):
    RegisterJengaGlobalToolchains()

    configurations(["Debug", "Release"])
    targetoses([TargetOS.LINUX])
    targetarchs([TargetArch.X86_64])

    usetoolchain("clang-cross-linux")

    with project("X11Window"):
        windowedapp()
        language("C++")
        files(["src/**.cpp"])

        sysroot(r"E:/Projets/Closed/Jenga/sysroot/linux-x86_64")
        includedirs([r"E:/Projets/Closed/Jenga/sysroot/linux-x86_64/usr/include"])

        links(["X11"])
```

**What You Learn:**
- Using global toolchains with `RegisterJengaGlobalToolchains()`
- Sysroot configuration for cross-compilation
- X11 library linking
- Cross-compiling GUI applications

---

### Example 17: macOS Cocoa Window

**Location:** `Exemples/17_window_macos_cocoa/`

**Purpose:** Demonstrates native macOS application using Cocoa framework.

**Key Concepts:**
- Cocoa framework linking
- Objective-C++ (.mm files)
- macOS framework system
- Universal binaries (x86_64 + ARM64)

**Configuration:**
```python
with workspace("CocoaWindowDemo"):
    configurations(["Debug", "Release"])
    targetoses([TargetOS.MACOS])
    targetarchs([TargetArch.X86_64, TargetArch.ARM64])

    with toolchain("apple_clang", "apple-clang"):
        settarget("macOS", "x86_64", "gnu")
        ccompiler("clang")
        cppcompiler("clang++")
        linker("clang++")
        framework("Cocoa")

    usetoolchain("apple_clang")

    with project("CocoaWindow"):
        windowedapp()
        language("Objective-C++")
        files(["src/**.mm"])
```

**What You Learn:**
- Linking macOS frameworks with `framework()`
- Objective-C++ language support
- Universal binary support (Intel + Apple Silicon)
- Apple Clang toolchain configuration

---

### Example 18: Android Native Window

**Location:** `Exemples/18_window_android_native/`

**Purpose:** Demonstrates Android native windowed application.

**Key Concepts:**
- Android NativeActivity
- Native window management
- Android application ID
- Minimal Android configuration

**Configuration:**
```python
import os
from Jenga import *

with workspace("AndroidWindowDemo"):
    configurations(["Debug", "Release"])
    targetoses([TargetOS.ANDROID])
    targetarchs([TargetArch.ARM64])

    androidsdkpath(os.getenv("ANDROID_SDK_ROOT", ""))
    androidndkpath(os.getenv("ANDROID_NDK_ROOT", ""))

    with project("AndroidWindow"):
        windowedapp()
        language("C++")
        files(["src/**.cpp"])
        androidapplicationid("com.Jenga.window")
        androidnativeactivity(True)
```

**What You Learn:**
- Minimal Android native app configuration
- NativeActivity for C++-only Android apps
- Single ABI targeting for faster iteration

---

### Example 19: Web Canvas

**Location:** `Exemples/19_window_web_canvas/`

**Purpose:** Demonstrates WebAssembly application with HTML Canvas.

**Key Concepts:**
- Emscripten shell files
- Canvas element integration
- Memory configuration
- Web graphics

**Configuration:**
```python
with workspace("WebCanvasDemo"):
    configurations(["Release"])
    targetoses([TargetOS.WEB])
    targetarchs([TargetArch.WASM32])

    with toolchain("emscripten", "emscripten"):
        settarget("Web", "wasm32")
        ccompiler(r"C:\emsdk-4.0.22\upstream\emscripten\emcc.bat")
        cppcompiler(r"C:\emsdk-4.0.22\upstream\emscripten\em++.bat")
        archiver(r"C:\emsdk-4.0.22\upstream\emscripten\emar.bat")

    usetoolchain("emscripten")

    with project("WebCanvas"):
        windowedapp()
        language("C++")
        files(["src/**.cpp"])

        emscriptenshellfile("emscripten_fullscreen.html")
        emscriptencanvasid("canvas")
        emscripteninitialmemory(16)
        emscriptenstacksize(5)
```

**What You Learn:**
- Custom HTML shell files with `emscriptenshellfile()`
- Canvas ID customization
- Memory and stack size configuration
- WebGL/Canvas integration

---

### Example 20: iOS UIKit Window

**Location:** `Exemples/20_window_ios_uikit/`

**Purpose:** Demonstrates iOS application with UIKit framework.

**Key Concepts:**
- UIKit framework
- iOS bundle configuration
- Objective-C++ for iOS
- Simulator vs device builds

**Configuration:**
```python
with workspace("UIKitWindowDemo"):
    configurations(["Debug", "Release"])
    targetoses([TargetOS.IOS])
    targetarchs([TargetArch.ARM64, TargetArch.X86_64])

    with project("UIKitWindow"):
        windowedapp()
        language("Objective-C++")
        files(["src/**.mm"])
        iosbundleid("com.Jenga.uikitwindow")
        iosversion("1.0")
        iosminsdk("14.0")
```

**What You Learn:**
- iOS application structure
- UIKit framework (implicit linking)
- Supporting both device (ARM64) and simulator (x86_64)

---

### Example 21: Zig Cross-Compilation

**Location:** `Exemples/21_zig_cross_compile/`

**Purpose:** Demonstrates using Zig compiler for cross-compilation.

**Key Concepts:**
- Zig as C++ compiler
- Zig wrapper scripts
- Filter-based configuration
- Cross-platform from single host

**Configuration:**
```python
from Jenga import *

with workspace("ZigCrossDemo"):
    configurations(["Debug", "Release"])
    targetoses([TargetOS.LINUX])
    targetarchs([TargetArch.X86_64])

    with toolchain("zig-linux-x64", "clang"):
        settarget("Linux", "x86_64", "gnu")
        targettriple("x86_64-linux-gnu")
        ccompiler(r"E:\Projets\Closed\Jenga\scripts\zig-cc.bat")
        cppcompiler(r"E:\Projets\Closed\Jenga\scripts\zig-c++.bat")
        linker(r"E:\Projets\Closed\Jenga\scripts\zig-c++.bat")
        archiver(r"C:\Zig\zig-x86_64-windows-0.16.0\zig.exe")
        cflags(["-target", "x86_64-linux-gnu"])
        cxxflags(["-target", "x86_64-linux-gnu", "-std=c++17"])
        ldflags(["-target", "x86_64-linux-gnu"])
        arflags(["ar"])

    usetoolchain("zig-linux-x64")

    with project("ZigCrossApp"):
        consoleapp()
        language("C++")
        files(["src/**.cpp"])
        cppdialect("C++17")

        with filter("configurations:Debug"):
            defines(["DEBUG"])
            optimize("Off")
            symbols("On")

        with filter("configurations:Release"):
            defines(["NDEBUG"])
            optimize("Speed")
            symbols("Off")
```

**What You Learn:**
- Zig as universal cross-compiler
- Wrapper scripts for Zig commands
- Advanced filter usage
- Target triple specification

---

### Example 22: NK Multiplatform Sandbox

**Location:** `Exemples/22_nk_multiplatform_sandbox/`

**Purpose:** Comprehensive multi-platform demonstration targeting 7 platforms.

**Key Concepts:**
- Maximum platform coverage
- Multi-project workspace (framework, sandbox, tests)
- Large-scale project organization
- Platform abstraction

**Configuration:**
```python
from Jenga import *

with workspace("NKMultiPlatformSandbox"):
    configurations(["Debug", "Release"])
    targetoses([
        TargetOS.WINDOWS,
        TargetOS.LINUX,
        TargetOS.MACOS,
        TargetOS.ANDROID,
        TargetOS.WEB,
        TargetOS.IOS,
        TargetOS.HARMONYOS,
    ])
    targetarchs([
        TargetArch.X86_64,
        TargetArch.ARM64,
        TargetArch.WASM32,
    ])

    # Core framework
    with project("NKFramework"):
        staticlib()
        language("C++")
        files([
            "src/core/**.cpp",
            "src/internal/**.cpp",
            "src/platform/**.cpp",
            "src/entry/**.cpp",
        ])
        includedirs(["include"])

    # Sandbox application
    with project("NKSandbox"):
        windowedapp()
        language("C++")
        files([
            "src/core/**.cpp",
            "src/internal/**.cpp",
            "src/platform/**.cpp",
            "src/entry/**.cpp",
            "sandbox/**.cpp",
        ])
        includedirs(["include"])

    # Test suite
    with project("NKSandboxTests"):
        consoleapp()
        language("C++")
        files([
            "src/core/**.cpp",
            "src/internal/**.cpp",
            "src/platform/**.cpp",
            "tests/**.cpp",
        ])
        includedirs(["include"])
```

**What You Learn:**
- Targeting 7 different platforms simultaneously
- 3 different architectures
- Multi-project organization (framework, app, tests)
- Platform abstraction layer design
- Shared source between projects
- Scalability of Jenga configuration

---

## Troubleshooting

### Common Build Errors

#### Error: "Compiler not found"

**Problem:** Jenga cannot find the C/C++ compiler.

**Solutions:**
1. **Install a compiler:**
   - Windows: Install Visual Studio with C++ workload
   - Linux: `sudo apt install build-essential`
   - macOS: `xcode-select --install`

2. **Add compiler to PATH:**
   ```bash
   # Windows (PowerShell)
   $env:PATH += ";C:\Program Files\LLVM\bin"

   # Linux/macOS
   export PATH="/usr/local/bin:$PATH"
   ```

3. **Specify compiler explicitly:**
   ```python
   with toolchain("my_gcc", "gcc"):
       ccompiler("/usr/bin/gcc-11")
       cppcompiler("/usr/bin/g++-11")
   ```

---

#### Error: "Cannot find .jenga file"

**Problem:** Jenga cannot locate workspace configuration.

**Solutions:**
1. Run from workspace root directory
2. Specify explicitly: `Jenga build --jenga-file path/to/file.jenga`
3. Ensure file has `.jenga` extension

---

#### Error: "Circular dependency detected"

**Problem:** Projects depend on each other in a cycle.

**Example:**
```
ProjectA depends on ProjectB
ProjectB depends on ProjectC
ProjectC depends on ProjectA  <-- Circular!
```

**Solutions:**
1. Review dependency graph
2. Break circular dependencies by refactoring
3. Use `Jenga info --verbose` to visualize dependencies

---

#### Error: "Link error: undefined reference to..."

**Problem:** Function/variable declared but not defined or library not linked.

**Solutions:**
1. **Check library linking:**
   ```python
   links(["MissingLibrary"])
   ```

2. **Verify source files included:**
   ```python
   files(["src/**.cpp"])  # Make sure implementation files are included
   ```

3. **Check link order** (libraries should come after objects that use them):
   ```python
   links(["MyLib", "SystemLib"])  # Correct order
   ```

4. **Platform-specific libraries:**
   ```python
   with filter("system:Windows"):
       links(["user32", "gdi32"])
   ```

---

#### Error: "Module not found" (C++20 modules)

**Problem:** C++20 module compilation fails.

**Solutions:**
1. **Ensure C++20 is enabled:**
   ```python
   cppdialect("C++20")
   ```

2. **Check compiler version:**
   - MSVC 2019 16.8+ required
   - Clang 16+ required
   - GCC 11+ (experimental)

3. **Verify module file extensions:**
   - Use `.cppm`, `.ixx`, or `.c++m` for module interfaces

---

#### Error: "Android SDK/NDK not found"

**Problem:** Android build cannot find SDK or NDK.

**Solutions:**
1. **Set environment variables:**
   ```bash
   export ANDROID_SDK_ROOT=/path/to/android-sdk
   export ANDROID_NDK_HOME=/path/to/android-ndk
   ```

2. **Specify in .jenga file:**
   ```python
   androidsdkpath("/path/to/android-sdk")
   androidndkpath("/path/to/android-ndk")
   ```

3. **Verify paths exist and are correct**

---

### Performance Issues

#### Slow Builds

**Solutions:**
1. **Enable caching** (default, but check if disabled):
   ```bash
   Jenga build  # Uses cache
   ```

2. **Use daemon for incremental builds:**
   ```bash
   Jenga build  # Daemon runs automatically
   ```

3. **Parallel compilation** (automatic based on CPU cores)

4. **Use precompiled headers:**
   ```python
   pchheader("pch.h")
   pchsource("pch.cpp")
   ```

5. **Disable verbose output:**
   ```bash
   Jenga build  # Without --verbose
   ```

---

#### Cache Issues

**Problem:** Build not detecting changes or using stale cache.

**Solutions:**
1. **Invalidate cache:**
   ```bash
   Jenga clean --all
   ```

2. **Rebuild without cache:**
   ```bash
   Jenga build --no-cache
   ```

3. **Delete cache manually:**
   ```bash
   rm -rf .jenga/cache.db
   ```

---

### Platform-Specific Issues

#### Windows: "MSVC not detected"

**Solutions:**
1. **Install Visual Studio** (not just Build Tools)
2. **Run from Developer Command Prompt**
3. **Specify MSVC toolchain:**
   ```bash
   Jenga build --platform Windows-x86_64-msvc
   ```

---

#### Linux: "X11 library not found"

**Solutions:**
1. **Install X11 development libraries:**
   ```bash
   sudo apt install libx11-dev
   ```

2. **Specify library path:**
   ```python
   libdirs(["/usr/lib/x86_64-linux-gnu"])
   ```

---

#### macOS: "Framework not found"

**Solutions:**
1. **Ensure Xcode installed:**
   ```bash
   xcode-select --install
   ```

2. **Link framework explicitly:**
   ```python
   framework("Cocoa")
   ```

3. **Add framework path:**
   ```python
   frameworkpath("/System/Library/Frameworks")
   ```

---

#### Android: "Keystore not found"

**Solutions:**
1. **Generate keystore:**
   ```bash
   Jenga keygen --output release.keystore --alias mykey
   ```

2. **Verify keystore path:**
   ```python
   androidkeystore("release.keystore")  # Relative or absolute path
   ```

---

### Debugging Techniques

#### Enable Verbose Output

```bash
Jenga build --verbose
```

Shows detailed compilation commands and output.

---

#### Check Workspace Info

```bash
Jenga info --verbose
```

Displays:
- All projects
- Configurations
- Target platforms
- Toolchains
- Dependencies

---

#### Validate Configuration

```python
# In .jenga file
validateincludes()  # Check for circular dependencies
```

---

#### Generate Dependency Report

```python
generatedependencyreport("DEPENDENCIES.md")
```

Creates markdown file with full dependency graph.

---

#### Test Individual Project

```bash
Jenga build --target ProjectName
```

Builds only specified project and its dependencies.

---

### Getting Help

1. **Command Help:**
   ```bash
   Jenga help
   Jenga help build
   ```

2. **Documentation Command:**
   ```bash
   Jenga docs
   ```

3. **GitHub Issues:**
   - Report bugs: https://github.com/Rihen-Universe/Jenga/issues
   - Feature requests welcome

4. **Verbose Error Messages:**
   Always include `--verbose` output when reporting issues.

---

## Best Practices

### Project Organization

#### 1. Use Consistent Directory Structure

**Recommended:**
```
MyProject/
├── MyProject.jenga
├── include/          # Public headers
├── src/              # Implementation
├── tests/            # Unit tests
├── docs/             # Documentation
├── assets/           # Resources
└── Build/            # Build output (generated)
    ├── Obj/          # Object files
    └── Bin/          # Executables
```

#### 2. Separate Public and Private Headers

```python
with project("MyLib"):
    staticlib()
    files([
        "src/**.cpp",
        "src/internal/**.cpp",  # Private implementation
    ])
    includedirs([
        "include",              # Public API
        "src/internal",         # Private headers
    ])
```

#### 3. Use Variable Expansion for Paths

**Bad:**
```python
includedirs(["C:/Projects/MyWorkspace/common/include"])
```

**Good:**
```python
includedirs(["%{wks.location}/common/include"])
```

---

### Configuration Management

#### 1. Define Common Settings Once

```python
with workspace("MyWorkspace"):
    configurations(["Debug", "Release"])

    # Common Debug settings
    with filter("configurations:Debug"):
        defines(["DEBUG", "_DEBUG"])
        optimize("Off")
        symbols("On")

    # Common Release settings
    with filter("configurations:Release"):
        defines(["NDEBUG"])
        optimize("Speed")
        symbols("Off")

    # Projects inherit these settings
    with project("App1"):
        consoleapp()
        # ...
```

#### 2. Use Filters for Platform-Specific Code

```python
with project("CrossPlatformApp"):
    consoleapp()
    files(["src/common/**.cpp"])

    with filter("system:Windows"):
        files(["src/platform/windows/**.cpp"])
        links(["user32", "gdi32"])
        defines(["PLATFORM_WINDOWS"])

    with filter("system:Linux"):
        files(["src/platform/linux/**.cpp"])
        links(["X11", "pthread"])
        defines(["PLATFORM_LINUX"])

    with filter("system:macOS"):
        files(["src/platform/macos/**.mm"])
        framework("Cocoa")
        defines(["PLATFORM_MACOS"])
```

#### 3. Separate Debug and Release Builds

```python
# Debug: Fast compilation, debugging symbols
with filter("configurations:Debug"):
    optimize("Off")
    symbols("On")
    defines(["DEBUG_LOGGING", "ENABLE_ASSERTS"])

# Release: Optimized, no debug info
with filter("configurations:Release"):
    optimize("Speed")
    symbols("Off")
    defines(["NDEBUG"])
    ldflags(["-s"])  # Strip symbols (Linux/macOS)

# RelWithDebInfo: Best of both worlds
with filter("configurations:RelWithDebInfo"):
    optimize("Speed")
    symbols("On")
```

---

### Dependency Management

#### 1. Explicit Dependencies

```python
with project("App"):
    consoleapp()
    links(["Engine", "Utilities"])
    dependson(["Engine", "Utilities"])  # Explicit build order
```

#### 2. Avoid Circular Dependencies

**Bad:**
```python
# ProjectA depends on ProjectB
# ProjectB depends on ProjectA
# = Circular dependency error!
```

**Good:**
```python
# Extract common code to ProjectC
# ProjectA depends on ProjectC
# ProjectB depends on ProjectC
```

#### 3. Use External Includes for Modularity

```python
# main.jenga
with include("libs/logger.jenga"):
    pass

with include("libs/network.jenga"):
    pass

# Keeps main file clean and modular
```

---

### Performance Optimization

#### 1. Enable Precompiled Headers

```python
with project("LargeProject"):
    consoleapp()
    pchheader("pch.h")
    pchsource("pch.cpp")
    files(["src/**.cpp"])
```

**pch.h:**
```cpp
#pragma once

// Include frequently used standard library headers
#include <iostream>
#include <string>
#include <vector>
#include <map>
#include <algorithm>
#include <memory>
```

#### 2. Use Incremental Builds

Default behavior - Jenga automatically detects changes and rebuilds only what's needed.

#### 3. Parallel Compilation

Automatic - Jenga uses all available CPU cores.

#### 4. Link-Time Optimization (LTO)

```python
with filter("configurations:Release"):
    with filter("system:Windows"):
        cxxflags(["/GL"])
        ldflags(["/LTCG"])

    with filter("system:Linux"):
        cxxflags(["-flto"])
        ldflags(["-flto"])
```

---

### Code Quality

#### 1. Enable High Warning Levels

```python
warnings("Extra")  # Or WarningLevel.EXTRA

# Treat warnings as errors in CI builds
with filter("action:ci"):
    warnings("Error")
```

#### 2. Use Sanitizers in Debug Builds

```python
with filter("configurations:Debug"):
    sanitizeaddress()  # Detect memory errors
    sanitizeundefined()  # Detect undefined behavior
```

#### 3. Write Unit Tests

```python
with unitest() as u:
    u.Compile()

with project("MyLib"):
    staticlib()
    files(["src/**.cpp"])

    with test():
        testfiles(["tests/**.cpp"])
```

#### 4. Enable Code Coverage

```python
with filter("configurations:Debug"):
    coveragegcov()
```

---

### Cross-Platform Development

#### 1. Abstract Platform-Specific Code

```cpp
// platform.h
#pragma once

#if defined(_WIN32)
    #define PLATFORM_WINDOWS
    #include "platform/windows.h"
#elif defined(__linux__)
    #define PLATFORM_LINUX
    #include "platform/linux.h"
#elif defined(__APPLE__)
    #define PLATFORM_MACOS
    #include "platform/macos.h"
#endif
```

#### 2. Use Consistent File Paths

Always use forward slashes in .jenga files:
```python
files(["src/platform/windows/**.cpp"])  # Good
files(["src\\platform\\windows\\**.cpp"])  # Bad (Windows-only)
```

#### 3. Test on All Target Platforms

Regularly build and test on all platforms:
```bash
Jenga build --platform Windows-x86_64
Jenga build --platform Linux-x86_64
Jenga build --platform macOS-ARM64
```

---

### Version Control

#### 1. Ignore Build Artifacts

**.gitignore:**
```
Build/
.jenga/
*.obj
*.o
*.exe
*.dll
*.so
*.dylib
*.a
*.lib
```

#### 2. Commit .jenga Files

Always commit workspace and project configuration files:
```bash
git add MyProject.jenga
git commit -m "Add project configuration"
```

#### 3. Document SDK Paths

Use environment variables and document them:

**README.md:**
```markdown
## Build Requirements

Set these environment variables:
- ANDROID_SDK_ROOT: Path to Android SDK
- ANDROID_NDK_HOME: Path to Android NDK
```

---

### Naming Conventions

#### 1. Workspace and Project Names

Use PascalCase:
```python
with workspace("MyWorkspace"):
    with project("MyProject"):
        pass
```

#### 2. Configuration Names

Standard naming:
- Debug
- Release
- RelWithDebInfo
- MinSizeRel

#### 3. Platform Naming

Use standard platform strings:
- Windows-x86_64
- Linux-ARM64
- macOS-ARM64
- Android-ARM64
- iOS-ARM64

---

### Documentation

#### 1. Comment Complex Configurations

```python
with workspace("ComplexProject"):
    # Targeting both desktop and mobile platforms
    targetoses([TargetOS.WINDOWS, TargetOS.LINUX, TargetOS.ANDROID])

    # Use Clang for consistent behavior across platforms
    with toolchain("clang_cross", "clang"):
        # Configure cross-compilation target
        settarget("Linux", "x86_64", "gnu")
        # ...
```

#### 2. Generate API Documentation

```bash
Jenga docs extract --format html --output docs/
```

#### 3. Maintain DEPENDENCIES.md

```python
generatedependencyreport("DEPENDENCIES.md")
```

---

### Security Best Practices

#### 1. Don't Commit Secrets

Never commit:
- Keystore passwords
- API keys
- Signing certificates

Use environment variables instead:
```python
androidkeystorepass(os.getenv("KEYSTORE_PASSWORD", ""))
```

#### 2. Use Separate Debug/Release Keystores

```python
with filter("configurations:Debug"):
    androidkeystore("debug.keystore")
    androidkeystorepass("android")

with filter("configurations:Release"):
    androidkeystore(os.getenv("RELEASE_KEYSTORE", ""))
    androidkeystorepass(os.getenv("RELEASE_KEYSTORE_PASSWORD", ""))
```

#### 3. Enable Security Features

```python
with filter("configurations:Release"):
    # Stack protection
    cxxflags(["-fstack-protector-strong"])

    # Position-independent executable
    pie()

    # ASLR support
    ldflags(["-Wl,-z,relro", "-Wl,-z,now"])
```

---

### Continuous Integration

#### 1. CI-Friendly Configuration

```python
# .jenga file
with filter("configurations:CI"):
    warnings("Error")  # Treat warnings as errors
    symbols("On")
    optimize("Speed")
```

#### 2. Automated Testing

```bash
# CI script
Jenga build --config CI
Jenga test --config CI
```

#### 3. Multi-Platform CI

```yaml
# .github/workflows/build.yml (example)
jobs:
  build:
    strategy:
      matrix:
        os: [windows-latest, ubuntu-latest, macos-latest]
    steps:
      - uses: actions/checkout@v2
      - name: Install Jenga
        run: pip install Jenga
      - name: Build
        run: Jenga build --config Release
      - name: Test
        run: Jenga test --config Release
```

---

### Maintenance

#### 1. Regular Updates

Keep Jenga updated:
```bash
pip install --upgrade Jenga
```

#### 2. Clean Builds Periodically

```bash
Jenga clean --all
Jenga build
```

#### 3. Review Dependencies

Periodically review and update:
- Compiler versions
- SDK versions
- Library dependencies

---

### Summary of Best Practices

✅ **DO:**
- Use variable expansion for paths
- Enable high warning levels
- Write unit tests
- Use precompiled headers for large projects
- Commit .jenga files to version control
- Document platform requirements
- Use filters for platform-specific code
- Enable sanitizers in debug builds

❌ **DON'T:**
- Hardcode absolute paths
- Commit build artifacts
- Create circular dependencies
- Ignore compiler warnings
- Skip testing on target platforms
- Commit secrets (passwords, keys)
- Use backslashes in paths
- Disable caching without reason

---

## Appendices

### Appendix A: DSL Quick Reference Card

**Workspace Setup:**
```python
from Jenga import *

with workspace("Name", location="."):
    configurations(["Debug", "Release"])
    targetoses([TargetOS.WINDOWS, TargetOS.LINUX])
    targetarchs([TargetArch.X86_64])
```

**Project Definition:**
```python
with project("Name"):
    consoleapp()  # or windowedapp(), staticlib(), sharedlib()
    language("C++")
    cppdialect("C++17")
    files(["src/**.cpp"])
    includedirs(["include"])
    links(["Library"])
    dependson(["Library"])
```

**Conditional Configuration:**
```python
with filter("configurations:Debug"):
    symbols("On")
    optimize("Off")

with filter("system:Windows"):
    links(["user32"])
```

**Testing:**
```python
with unitest() as u:
    u.Compile()

with project("MyLib"):
    staticlib()
    with test():
        testfiles(["tests/**.cpp"])
```

---

### Appendix B: Compiler Flag Reference

#### MSVC Flags

| Flag | Purpose |
|------|---------|
| `/O0` | No optimization |
| `/O1` | Minimize size |
| `/O2` | Maximize speed |
| `/Ox` | Maximum optimization |
| `/Zi` | Debug information |
| `/W3` | Warning level 3 |
| `/W4` | Warning level 4 |
| `/WX` | Warnings as errors |
| `/std:c++17` | C++17 standard |
| `/EHsc` | Exception handling |
| `/MD` | Multi-threaded DLL runtime |
| `/MT` | Multi-threaded static runtime |

#### GCC/Clang Flags

| Flag | Purpose |
|------|---------|
| `-O0` | No optimization |
| `-Os` | Optimize for size |
| `-O2` | Optimize for speed |
| `-O3` | Maximum optimization |
| `-g` | Debug information |
| `-Wall` | All warnings |
| `-Wextra` | Extra warnings |
| `-Werror` | Warnings as errors |
| `-std=c++17` | C++17 standard |
| `-fPIC` | Position-independent code |
| `-pthread` | POSIX threads |
| `-march=native` | CPU-specific optimizations |

---

### Appendix C: Platform Support Matrix

| Platform | Architectures | Compilers | Status |
|----------|---------------|-----------|--------|
| Windows | x86, x86_64, ARM64 | MSVC, Clang, MinGW | ✅ Full |
| Linux | x86_64, ARM, ARM64 | GCC, Clang | ✅ Full |
| macOS | x86_64, ARM64 | Apple Clang | ✅ Full |
| Android | ARM, ARM64, x86, x86_64 | NDK Clang | ✅ Full |
| iOS | ARM64, x86_64 | Apple Clang | ✅ Full |
| Web | WASM32 | Emscripten | ✅ Full |
| HarmonyOS | ARM64 | HarmonyOS SDK | ⚠️ Experimental |
| Xbox | x86_64 | MSVC | ⚠️ Stub |
| PlayStation | x86_64 | PS SDK | ⚠️ Stub |
| Switch | ARM64 | Switch SDK | ⚠️ Stub |

---

### Appendix D: Environment Variables

| Variable | Purpose | Example |
|----------|---------|---------|
| `ANDROID_SDK_ROOT` | Android SDK path | `/opt/android-sdk` |
| `ANDROID_NDK_HOME` | Android NDK path | `/opt/android-ndk` |
| `JAVA_HOME` | Java JDK path | `/usr/lib/jvm/java-11` |
| `PATH` | Executable search path | Modified for compilers |

---

### Appendix E: File Extensions

| Extension | Purpose |
|-----------|---------|
| `.jenga` | Workspace/project configuration |
| `.cpp` | C++ source |
| `.c` | C source |
| `.h`, `.hpp` | Headers |
| `.mm` | Objective-C++ source |
| `.cppm`, `.ixx` | C++20 module interface |
| `.o`, `.obj` | Object files |
| `.a`, `.lib` | Static libraries |
| `.so`, `.dll`, `.dylib` | Shared libraries |

---

### Appendix F: Common Error Codes

| Code | Message | Solution |
|------|---------|----------|
| 1 | Build failed | Check compiler errors |
| 2 | Configuration error | Fix .jenga syntax |
| 3 | Dependency cycle | Review dependencies |
| 4 | Toolchain not found | Install compiler |
| 5 | File not found | Check paths |

---

### Appendix G: Glossary

**ABI** - Application Binary Interface, defines low-level interface

**APK** - Android Package, installable Android app format

**ARM64** - 64-bit ARM architecture (AArch64)

**BMI** - Binary Module Interface, compiled C++20 module

**Cross-Compilation** - Building for different platform than host

**DSL** - Domain-Specific Language, Jenga's Python-based configuration

**IPA** - iOS Package Archive, installable iOS app format

**NDK** - Native Development Kit (Android)

**PCH** - Precompiled Header, speeds up compilation

**SDK** - Software Development Kit

**Sysroot** - Root directory containing target system's headers/libraries

**Target Triple** - LLVM format: arch-vendor-os-env

**Toolchain** - Set of compiler, linker, and tools

**WASM** - WebAssembly, portable binary format for web

**Workspace** - Top-level container for projects

**x86_64** - 64-bit x86 architecture (AMD64)

---

## Conclusion

This user guide has covered all aspects of using Jenga, from basic console applications to complex multi-platform projects. You've learned:

✅ Installation and setup
✅ Workspace and project configuration
✅ All DSL functions and their usage
✅ Build commands and workflows
✅ Cross-compilation and toolchains
✅ Platform-specific development (Windows, Linux, macOS, Android, iOS, Web)
✅ Testing and quality assurance
✅ Advanced features (C++20 modules, PCH, filters, etc.)
✅ All 22 example projects in detail
✅ Troubleshooting common issues
✅ Best practices for professional development

Jenga provides a powerful, flexible, and intuitive build system for native application development. Whether you're building a simple console tool or a complex multi-platform game engine, Jenga has the features you need.

**Next Steps:**
1. Explore the example projects in `Exemples/`
2. Create your first project with `Jenga workspace`
3. Read the Developer Guide for extending Jenga
4. Join the community and contribute

**Resources:**
- GitHub: https://github.com/Rihen-Universe/Jenga
- Documentation: Run `Jenga docs`
- Issue Tracker: https://github.com/Rihen-Universe/Jenga/issues

Happy building with Jenga! 🎉

---

**Jenga Build System v2.0.2**
© 2026 Rihen. All rights reserved.
