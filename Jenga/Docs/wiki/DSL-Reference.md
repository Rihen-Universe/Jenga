<!-- AUTEUR : TEUGUIA TADJUIDJE Rodolf Séderis — Rihen -->
# DSL Reference

**Langues / Languages :** [Français](#français) · [English](#english)

Le DSL est importé via `from Jenga import *`. / The DSL is imported via `from Jenga import *`.

---

## Français

### Context managers

| Manager | Signature | Rôle |
|---------|-----------|------|
| `workspace` | `workspace(name, location="")` | Conteneur racine (configs, plateformes, projets) |
| `project` | `project(name)` | Unité de compilation (app, lib, test) |
| `toolchain` | `toolchain(name, compilerFamily)` | Définit une toolchain (`gcc`/`clang`/`msvc`/`emscripten`/`android-ndk`/`apple-clang`) |
| `filter` | `filter(expr)` | Bloc conditionnel (`system:`, `config:`, `arch:`, `options:`) |
| `unitest` | `unitest()` | Config du framework de tests (`.Precompiled()` ou `.Compile(...)`) |
| `test` | `test(subname="")` | Suite de tests rattachée au projet parent |
| `include` | `include(jengaFile)` | Inclut un `.jenga` externe (`.only([...])` / `.skip([...])`) |
| `batchinclude` | `batchinclude(list_or_dict)` | Inclut plusieurs `.jenga` |

### Exemple complet

```python
from Jenga import *
from Jenga.GlobalToolchains import RegisterJengaGlobalToolchains

with workspace("GameWorkspace"):
    RegisterJengaGlobalToolchains()
    configurations(["Debug", "Release"])
    targetoses([TargetOS.WINDOWS, TargetOS.LINUX])
    targetarchs([TargetArch.X86_64, TargetArch.ARM64])
    startproject("Game")

    with project("Engine"):
        staticlib()
        language("C++"); cppdialect("C++20")
        files(["engine/src/**.cpp"])
        includedirs(["engine/include"])

    with project("Game"):
        windowedapp()
        language("C++")
        files(["game/src/**.cpp"])
        dependson(["Engine"])
        networkenabled(True)          # permissions réseau cross-plateforme

        with filter("system:Windows"):
            links(["d3d11", "dxgi"]); defines(["PLATFORM_WINDOWS"])
        with filter("config:Debug"):
            optimize("OFF"); symbols(True); defines(["_DEBUG"])
```

### Configuration du workspace

`configurations(list)` · `targetoses(list)` · `targetarchs(list)` ·
`targetos(x)` · `targetarch(x)` · `platform(x)` · `architecture(x)` ·
`startproject(name)` · `disableunittestcompilation(bool, allow=[...])` /
`dutc(bool, allow=[...])` · `disableunittestexecution(bool, allow=[...])` /
`dute(bool, allow=[...])` · `newoption(...)` (option CLI custom, style Premake).

`allow` _(2.5.0+)_ : liste blanche de suites (`<Projet>_Tests`) qui **échappent**
à la politique posée ; deux listes distinctes pour deux politiques distinctes ;
un nom inconnu est une erreur à la fermeture du bloc `workspace`. Détail et
exemple : [Tests Unitest §5](Tests-Unitest.md).

```python
dutc(enable=True, allow=["NKCore_Tests", "NKMath_Tests"])   # seuls ceux-ci se compilent
dute(enable=True, allow=["NKCore_Tests"])                   # seul celui-ci se lance
```

### Config partagée — `useconfig` _(2.0.5+)_

`useconfig(*chemins)` charge un ou plusieurs fichiers de **config partagée** (de
simples `.jenga` ne contenant que des **définitions** : constantes, classes,
fonctions) et **propage leurs symboles** au workspace **et à tous les `.jenga`
inclus via `include(...)`** — sans aucun `import`, pour des `.jenga` beaucoup
plus propres.

```python
with workspace("MyApp"):
    useconfig("cfg/shared.jenga")     # peut vivre dans un sous-dossier ; multi-fichiers OK
    with include("modules/logger.jenga"):
        pass
```

```python
# cfg/shared.jenga — QUE des définitions, AUCUN import (l'API Jenga est injectée)
SHARED_DIALECT = "C++17"

def apply_common():
    language("C++")
    cppdialect(SHARED_DIALECT)
```

```python
# modules/logger.jenga — minimal : ni `from Jenga import *` ni `from config import *`
with project("Logger"):
    staticlib()
    apply_common()                    # propagé depuis la config
    files(["src/**.cpp"])
```

- Chemin relatif au dossier du `.jenga` workspace (ou absolu) ; peut pointer dans
  un **sous-dossier**.
- **Plusieurs** fichiers / appels : `useconfig("a.jenga", "b.jenga")` (les derniers
  surchargent). Constantes, classes **et** fonctions sont propagées.
- Le fichier de config n'a **pas besoin** de `from Jenga import *` (API injectée) ;
  remplace proprement le `from config import *` répété dans chaque module.
- Exemple : [`Exemples/12_external_includes`](https://github.com/Rihen-Universe/Jenga/tree/main/Jenga/Exemples/12_external_includes).

### Type de projet

`consoleapp()` · `windowedapp()` · `staticlib()` · `sharedlib()` ·
`testsuite()` · `kind(k)` · `kindexport(k, ke)`.

### Langage & dialecte

`language(lang)` (`C`/`C++`/`Objective-C`/`Objective-C++`/`Asm`/`Rust`/`Zig`) ·
`cppdialect(d)` / `cppversion(d)` (C++11→C++23) · `cdialect(d)` / `cversion(d)`
(C89→C23).

### Sources & includes

`files(patterns)` · `excludefiles(p)` / `removefiles(p)` ·
`excludemainfiles(p)` / `removemainfiles(p)` · `includedirs(d)` ·
`externalincludedirs(d)` · `sysincludedirs(d)` · `removeincludedirs(d)` ·
`libdirs(d)` · `syslibdirs(d)` · `removelibdirs(d)` · `location(path)` ·
`objdir(path)` · `targetdir(path)` · `targetname(name)`.

> Les patterns supportent le glob récursif : `src/**.cpp`, `include/**.hpp`.

### Dépendances & liaison

`links(libs)` · `removelinks(libs)` · `dependson(deps)` ·
`removedependson(deps)` · `dependfiles(patterns)` (fichiers copiés/embarqués au
packaging) · `embedresources(resources)`.

### Compilation & optimisation

`defines(defs)` · `removedefines(d)` / `undefines(d)` ·
`optimize(level)` (`OFF`/`SIZE`/`SPEED`/`FULL`) · `symbols(bool)` ·
`warnings(level)` (`NONE`/`DEFAULT`/`ALL`/`EXTRA`/`PEDANTIC`/`EVERYTHING`/`ERROR`) ·
`runtime(lib)` (MSVC : `MD`/`MDd`/`MT`/`MTd`) ·
`staticruntime([enabled])` (GCC/Clang : lie `libstdc++`/`libgcc` en statique →
exe autonome sans DLL runtime ; défaut projet = dynamique) ·
`pchheader(h)` · `pchsource(s)`.

> **`staticruntime()`** — sur les toolchains GCC/Clang (dont **clang-mingw** et
> **gcc-mingw** sous Windows, et GCC/Clang sous Linux) ajoute
> `-static-libstdc++ -static-libgcc` à l'édition de liens. L'exécutable embarque le
> runtime C++/GCC au lieu d'en dépendre en DLL : il **démarre quel que soit le PATH**,
> sans copier `libstdc++-6.dll`/`libgcc_s_seh-1.dll` à côté (et sans risquer de charger
> le mauvais `libstdc++` d'un autre msys → crash `0xC0000139` avant `main`). Coût :
> +~2 Mo/exe. Sans effet sur MSVC (y utiliser `runtime("MT")`) ni macOS (libc++).
> Exemple : `with project("App"): consoleapp(); staticruntime()`.

### Hooks de build

`prebuild(cmds)` · `postbuild(cmds)` · `prelink(cmds)` · `postlink(cmds)`.

### Toolchain & compilation avancée

`usetoolchain(name)` · `settarget(os, arch, env)` · `sysroot(path)` ·
`targettriple(triple)` · `ccompiler(p)` · `cppcompiler(p)` · `linker(p)` ·
`archiver(p)` · `cflags(f)` · `cxxflags(f)` · `ldflags(f)` · `asmflags(f)` ·
`arflags(f)` · `addcflag(f)` · `addcxxflag(f)` · `addldflag(f)` ·
`framework(n)` / `frameworks(ns)` · `frameworkpath(p)` · `librarypath(p)` ·
`library(l)` · `rpath(p)` · `sanitize(s)` · `pic()` · `pie()` · `nostdlib()` ·
`nostdinc()` · `buildoption(o, v)` · `buildoptions(opts)` · `linkoptions(f)`.

### Android

`androidsdkpath` · `androidndkpath` · `javajdkpath` · `androidapplicationid` ·
`androidversioncode` · `androidversionname` · `androidminsdk` ·
`androidtargetsdk` · `androidcompilesdk` · `androidabis` · `androidproguard` ·
`androidproguardrules` · `androidassets` · `androidisgame` ·
`androidpermissions` · `androidstl` · `androidnativeactivity` ·
`androidallowrotation` · `androidlargeheap` · `androidscreenorientation` · `ndkversion` ·
`androidsign` · `androidkeystore` · `androidkeystorepass` · `androidkeyalias` ·
`androidjavafiles` · `androidjavalibs`.

### Apple (iOS / tvOS / watchOS / visionOS)

`iosbundleid` · `iosversion` · `iosminsdk` · `iossigningidentity` ·
`iosentitlements` · `iosappicon` · `iosbuildnumber` · `iosbuildsystem`
(`direct`/`xcode`) · `iosdistributiontype` · `iosteamid` ·
`iosprovisioningprofile` · `iosresources` · `tvosminsdk` · `watchosminsdk` ·
`ipadosminsdk` · `visionosminsdk`.

### Emscripten / Web

`emscriptenshellfile` · `emscriptenfullscreenshell` · `emscriptencanvasid` ·
`emscripteninitialmemory` · `emscriptenstacksize` · `emscriptenexportname` ·
`emscriptenextraflags`.

### HarmonyOS

`harmonysdk` · `harmonyminsdk` · `harmonytargetapi` · `harmonybundlename` ·
`harmonyversioncode` · `harmonyversionname` · `harmonysign` · `harmonycertfile` ·
`harmonyprofile` · `harmonykeystore` · `harmonykeyalias` · `harmonykeypwd` ·
`harmonyappicon` · `harmonyresources` · `harmonyassets` · `harmonypermissions` ·
`harmonyets`. Voir [HarmonyOS](HarmonyOS.md).

### Xbox

`gdkpath` · `xboxmode` (`gdk`/`uwp`) · `xboxplatform` ·
`xboxsigningmode` · `xboxpackagename` · `xboxpublisher` · `xboxversion` ·
`xboxlekbpath` · `xboxassetchunks`.

### Icônes (cross-plateforme)

`appicon(icon)` (universel, PNG/JPG auto-converti) · `androidappicon` ·
`windowsicon` · `macosicon` · `webfavicon`.

### Installer / packaging

`licensefile(path)` (.txt/.md/.rtf) · `createdesktopshortcut(bool)` ·
`apppublisher(name)` · `appversion(version)` · `installeroption(key, value)`.

### Réseau / pare-feu

`networkenabled(bool)` · `firewallrule(name, direction, action, protocol, ports, profiles, programOverride)` ·
`networkusagedescription(text)` · `bonjourservices(list)` ·
`iosallowarbitraryloads(bool)`. Voir [Réseau et Pare-feu](Reseau-et-Pare-feu.md).

### Tests

`testoptions(opts)` · `testfiles(patterns)` · `testmainfile(f)` ·
`testmaintemplate(tmpl)` · `testownmain()` _(2.6.0+ : la suite fournit son
`main()`, Jenga n'en génère pas ; deux `main()` dans une suite sont refusés)_.
Voir [Tests Unitest](Tests-Unitest.md).

### Enums

| Enum | Valeurs |
|------|---------|
| `TargetOS` | `WINDOWS LINUX MACOS ANDROID IOS TVOS WATCHOS IPADOS VISIONOS WEB PS4 PS5 XBOX_ONE XBOX_SERIES SWITCH HARMONYOS FREEBSD OPENBSD` |
| `TargetArch` | `X86 X86_64 (X64) ARM ARM64 WASM32 WASM64 POWERPC POWERPC64 MIPS MIPS64` |
| `ProjectKind` | `CONSOLE_APP WINDOWED_APP STATIC_LIB SHARED_LIB TEST_SUITE` |
| `Optimization` | `OFF SIZE SPEED FULL` |
| `WarningLevel` | `NONE DEFAULT ALL EXTRA PEDANTIC EVERYTHING ERROR` |
| `Language` | `C CPP OBJC OBJCPP ASM RUST ZIG` |

### Variables dynamiques `%{...}`

| Namespace | Exemples |
|-----------|----------|
| `wks` | `%{wks.name}` `%{wks.location}` `%{wks.configurations}` `%{wks.startproject}` |
| `prj` | `%{prj.name}` `%{prj.location}` `%{prj.kind}` `%{prj.targetdir}` `%{prj.objdir}` `%{prj.targetname}` |
| `cfg` | `%{cfg.buildcfg}` `%{cfg.system}` `%{cfg.targetos}` `%{cfg.targetarch}` `%{cfg.targetenv}` |
| `toolchain` | `%{toolchain.name}` `%{toolchain.cc}` `%{toolchain.cxx}` `%{toolchain.sysroot}` `%{toolchain.targettriple}` |
| `Jenga` | `%{Jenga.Root}` `%{Jenga.Version}` `%{Jenga.Unitest.Include}` `%{Jenga.Unitest.Lib}` |
| `env` | `%{env.PATH}` `%{env.HOME}` |
| nommé | `%{Logger.location}` (par nom de projet) |

Exemple : `targetdir("%{wks.location}/Build/Bin/%{cfg.buildcfg}-%{cfg.system}/%{prj.name}")`.

### Système de filtres

```python
with filter("system:Windows"): links(["user32"])
with filter("config:Debug"): symbols(True)
with filter("arch:x86_64 && system:Linux"): cflags(["-march=x86-64"])
with filter("system:Windows || system:Linux"): defines(["DESKTOP"])
with filter("!system:macOS"): defines(["NOT_APPLE"])
with filter("options:with-sdl3"): links(["SDL3"])
```

Préfixes : `system:` `config:` `arch:` `options:` `action:`.
Opérateurs : `&&` (ET), `||` (OU), `!` (NON), espace = ET implicite.

### Bonnes pratiques

- Patterns de fichiers explicites (`src/**.cpp`).
- Toujours définir `startproject(...)` pour simplifier `jenga run`.
- Un projet par bibliothèque majeure, relié via `dependson([...])`.
- `RegisterJengaGlobalToolchains()` pour la détection automatique.

---

## English

### Context managers

| Manager | Signature | Purpose |
|---------|-----------|---------|
| `workspace` | `workspace(name, location="")` | Root container (configs, platforms, projects) |
| `project` | `project(name)` | Compilation unit (app, lib, test) |
| `toolchain` | `toolchain(name, compilerFamily)` | Define a toolchain (`gcc`/`clang`/`msvc`/`emscripten`/`android-ndk`/`apple-clang`) |
| `filter` | `filter(expr)` | Conditional block (`system:`, `config:`, `arch:`, `options:`) |
| `unitest` | `unitest()` | Test framework config (`.Precompiled()` or `.Compile(...)`) |
| `test` | `test(subname="")` | Test suite attached to the parent project |
| `include` | `include(jengaFile)` | Include an external `.jenga` (`.only([...])` / `.skip([...])`) |
| `batchinclude` | `batchinclude(list_or_dict)` | Include several `.jenga` files |

### Full example

```python
from Jenga import *
from Jenga.GlobalToolchains import RegisterJengaGlobalToolchains

with workspace("GameWorkspace"):
    RegisterJengaGlobalToolchains()
    configurations(["Debug", "Release"])
    targetoses([TargetOS.WINDOWS, TargetOS.LINUX])
    targetarchs([TargetArch.X86_64, TargetArch.ARM64])
    startproject("Game")

    with project("Engine"):
        staticlib()
        language("C++"); cppdialect("C++20")
        files(["engine/src/**.cpp"])
        includedirs(["engine/include"])

    with project("Game"):
        windowedapp()
        language("C++")
        files(["game/src/**.cpp"])
        dependson(["Engine"])
        networkenabled(True)          # cross-platform network permissions

        with filter("system:Windows"):
            links(["d3d11", "dxgi"]); defines(["PLATFORM_WINDOWS"])
        with filter("config:Debug"):
            optimize("OFF"); symbols(True); defines(["_DEBUG"])
```

### Workspace configuration

`configurations(list)` · `targetoses(list)` · `targetarchs(list)` ·
`targetos(x)` · `targetarch(x)` · `platform(x)` · `architecture(x)` ·
`startproject(name)` · `disableunittestcompilation(bool, allow=[...])` /
`dutc(bool, allow=[...])` · `disableunittestexecution(bool, allow=[...])` /
`dute(bool, allow=[...])` · `newoption(...)` (custom CLI option, Premake-style).

`allow` _(2.5.0+)_: allow list of suites (`<Project>_Tests`) that **escape** the
policy; two distinct lists for two distinct policies; an unknown name is an
error when the `workspace` block closes. Details and example:
[Unitest Tests §5](Tests-Unitest.md).

```python
dutc(enable=True, allow=["NKCore_Tests", "NKMath_Tests"])   # only these compile
dute(enable=True, allow=["NKCore_Tests"])                   # only this one runs
```

### Shared config — `useconfig` _(2.0.5+)_

`useconfig(*paths)` loads one or more **shared config** files (plain `.jenga`
files containing only **definitions**: constants, classes, functions) and
**propagates their symbols** to the workspace **and to every `.jenga` included
via `include(...)`** — with no `import` at all, for much cleaner `.jenga` files.

```python
with workspace("MyApp"):
    useconfig("cfg/shared.jenga")     # may live in a subfolder; multiple files OK
    with include("modules/logger.jenga"):
        pass
```

```python
# cfg/shared.jenga — ONLY definitions, NO import (the Jenga API is injected)
SHARED_DIALECT = "C++17"

def apply_common():
    language("C++")
    cppdialect(SHARED_DIALECT)
```

```python
# modules/logger.jenga — minimal: no `from Jenga import *`, no `from config import *`
with project("Logger"):
    staticlib()
    apply_common()                    # propagated from the shared config
    files(["src/**.cpp"])
```

- Path is relative to the workspace `.jenga` directory (or absolute); it may point
  into a **subfolder**.
- **Multiple** files / calls: `useconfig("a.jenga", "b.jenga")` (later ones
  override). Constants, classes **and** functions are propagated.
- The config file needs **no** `from Jenga import *` (API is injected); it cleanly
  replaces the `from config import *` repeated in every module.
- Example: [`Exemples/12_external_includes`](https://github.com/Rihen-Universe/Jenga/tree/main/Jenga/Exemples/12_external_includes).

### Project kind

`consoleapp()` · `windowedapp()` · `staticlib()` · `sharedlib()` ·
`testsuite()` · `kind(k)` · `kindexport(k, ke)`.

### Language & dialect

`language(lang)` (`C`/`C++`/`Objective-C`/`Objective-C++`/`Asm`/`Rust`/`Zig`) ·
`cppdialect(d)` / `cppversion(d)` (C++11→C++23) · `cdialect(d)` / `cversion(d)`
(C89→C23).

### Sources & includes

`files(patterns)` · `excludefiles(p)` / `removefiles(p)` ·
`excludemainfiles(p)` / `removemainfiles(p)` · `includedirs(d)` ·
`externalincludedirs(d)` · `sysincludedirs(d)` · `removeincludedirs(d)` ·
`libdirs(d)` · `syslibdirs(d)` · `removelibdirs(d)` · `location(path)` ·
`objdir(path)` · `targetdir(path)` · `targetname(name)`.

> Patterns support recursive globbing: `src/**.cpp`, `include/**.hpp`.

### Dependencies & linking

`links(libs)` · `removelinks(libs)` · `dependson(deps)` ·
`removedependson(deps)` · `dependfiles(patterns)` (files copied/embedded at
packaging) · `embedresources(resources)`.

### Compilation & optimization

`defines(defs)` · `removedefines(d)` / `undefines(d)` ·
`optimize(level)` (`OFF`/`SIZE`/`SPEED`/`FULL`) · `symbols(bool)` ·
`warnings(level)` (`NONE`/`DEFAULT`/`ALL`/`EXTRA`/`PEDANTIC`/`EVERYTHING`/`ERROR`) ·
`runtime(lib)` (MSVC: `MD`/`MDd`/`MT`/`MTd`) ·
`staticruntime([enabled])` (GCC/Clang: static-link `libstdc++`/`libgcc` → standalone
exe, no runtime DLL; project default = dynamic) · `pchheader(h)` · `pchsource(s)`.

> **`staticruntime()`** — on GCC/Clang toolchains (incl. **clang-mingw** & **gcc-mingw**
> on Windows, GCC/Clang on Linux) appends `-static-libstdc++ -static-libgcc` at link time,
> so the executable embeds the C++/GCC runtime instead of depending on DLLs: it **starts
> regardless of PATH**, no need to ship `libstdc++-6.dll`/`libgcc_s_seh-1.dll` next to it
> (and no risk of loading the wrong `libstdc++` from another msys → `0xC0000139` crash
> before `main`). Cost: +~2 MB/exe. No effect on MSVC (use `runtime("MT")`) or macOS (libc++).

### Build hooks

`prebuild(cmds)` · `postbuild(cmds)` · `prelink(cmds)` · `postlink(cmds)`.

### Toolchain & advanced compilation

`usetoolchain(name)` · `settarget(os, arch, env)` · `sysroot(path)` ·
`targettriple(triple)` · `ccompiler(p)` · `cppcompiler(p)` · `linker(p)` ·
`archiver(p)` · `cflags(f)` · `cxxflags(f)` · `ldflags(f)` · `asmflags(f)` ·
`arflags(f)` · `addcflag(f)` · `addcxxflag(f)` · `addldflag(f)` ·
`framework(n)` / `frameworks(ns)` · `frameworkpath(p)` · `librarypath(p)` ·
`library(l)` · `rpath(p)` · `sanitize(s)` · `pic()` · `pie()` · `nostdlib()` ·
`nostdinc()` · `buildoption(o, v)` · `buildoptions(opts)` · `linkoptions(f)`.

### Android / Apple / Emscripten / HarmonyOS / Xbox

Same function families as the French section above — every `android*`, `ios*`/
`tvos*`/`watchos*`/`ipados*`/`visionos*`, `emscripten*`, `harmony*` and `xbox*`
function is available. See [HarmonyOS](HarmonyOS.md).

### Icons (cross-platform)

`appicon(icon)` (universal, PNG/JPG auto-converted) · `androidappicon` ·
`windowsicon` · `macosicon` · `webfavicon`.

### Installer / packaging

`licensefile(path)` (.txt/.md/.rtf) · `createdesktopshortcut(bool)` ·
`apppublisher(name)` · `appversion(version)` · `installeroption(key, value)`.

### Networking / firewall

`networkenabled(bool)` · `firewallrule(name, direction, action, protocol, ports, profiles, programOverride)` ·
`networkusagedescription(text)` · `bonjourservices(list)` ·
`iosallowarbitraryloads(bool)`. See [Networking & Firewall](Reseau-et-Pare-feu.md).

### Tests

`testoptions(opts)` · `testfiles(patterns)` · `testmainfile(f)` ·
`testmaintemplate(tmpl)` · `testownmain()` _(2.6.0+: the suite provides its
own `main()`, Jenga generates none; two `main()` in one suite are refused)_.
See [Unitest Tests](Tests-Unitest.md).

### Enums

| Enum | Values |
|------|--------|
| `TargetOS` | `WINDOWS LINUX MACOS ANDROID IOS TVOS WATCHOS IPADOS VISIONOS WEB PS4 PS5 XBOX_ONE XBOX_SERIES SWITCH HARMONYOS FREEBSD OPENBSD` |
| `TargetArch` | `X86 X86_64 (X64) ARM ARM64 WASM32 WASM64 POWERPC POWERPC64 MIPS MIPS64` |
| `ProjectKind` | `CONSOLE_APP WINDOWED_APP STATIC_LIB SHARED_LIB TEST_SUITE` |
| `Optimization` | `OFF SIZE SPEED FULL` |
| `WarningLevel` | `NONE DEFAULT ALL EXTRA PEDANTIC EVERYTHING ERROR` |
| `Language` | `C CPP OBJC OBJCPP ASM RUST ZIG` |

### Dynamic variables `%{...}`

Namespaces `wks`, `prj`, `cfg`, `toolchain`, `Jenga`, `env`, plus per-project
name. Example:
`targetdir("%{wks.location}/Build/Bin/%{cfg.buildcfg}-%{cfg.system}/%{prj.name}")`.

### Filter system

```python
with filter("system:Windows"): links(["user32"])
with filter("arch:x86_64 && system:Linux"): cflags(["-march=x86-64"])
with filter("system:Windows || system:Linux"): defines(["DESKTOP"])
with filter("!system:macOS"): defines(["NOT_APPLE"])
with filter("options:with-sdl3"): links(["SDL3"])
```

Prefixes: `system:` `config:` `arch:` `options:` `action:`.
Operators: `&&` (AND), `||` (OR), `!` (NOT), whitespace = implicit AND.

### Best practices

- Use explicit file patterns (`src/**.cpp`).
- Always set `startproject(...)` to simplify `jenga run`.
- One project per major library, wired via `dependson([...])`.
- Use `RegisterJengaGlobalToolchains()` for automatic detection.
