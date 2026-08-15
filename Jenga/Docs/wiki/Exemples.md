# Exemples / Examples

**Langues / Languages :** [Français](#français) · [English](#english)

Les exemples se trouvent dans le dossier [`Exemples/`](../../Exemples/) du dépôt.
Copiez-en un avec `jenga examples copy <nom>` ou explorez-le directement.

---

## Français

### Tableau récapitulatif

| # | Exemple | Sujet | Plateformes | Niveau |
|---|---------|-------|-------------|--------|
| 01 | hello_console | App console minimale | Win/Linux/Android/Web | Débutant |
| 02 | static_library | Bibliothèque statique + lien | Win/Linux/Android/Web | Débutant |
| 03 | shared_library | Bibliothèque dynamique (.dll/.so) | Win/Linux/Android/Web | Débutant |
| 04 | unit_tests | Tests unitaires Unitest | Win/Linux/Android/Web | Intermédiaire |
| 05 | android_ndk | APK Android NativeActivity multi-ABI | Android | Avancé |
| 06 | ios_app | App iOS (Objective-C++) | iOS | Avancé |
| 07 | web_wasm | WebAssembly (Emscripten) | Web | Intermédiaire |
| 08 | custom_toolchain | Toolchain Clang personnalisée | Windows | Avancé |
| 09 | multi_projects | Workspace multi-projets + dépendances | Win/Linux/Android/Web | Intermédiaire |
| 10 | modules_cpp20 | Modules C++20 (`.cppm`) | Win/Linux | Avancé |
| 11 | benchmark | Google Benchmark | Win/Linux | Intermédiaire |
| 12 | external_includes | Composition via `include()` | Win/Linux/Android/Web | Intermédiaire |
| 13 | packaging | DEB/APK post-build + `dependfiles` | Win/Linux | Intermédiaire |
| 14 | cross_compile | Cross-compile Linux/Android (clang) | Linux/Android | Avancé |
| 15 | window_win32 | Fenêtre native Win32 | Windows | Intermédiaire |
| 16 | window_x11_linux | Fenêtre Linux X11 | Linux | Intermédiaire |
| 17 | window_macos_cocoa | Fenêtre macOS Cocoa (ObjC++) | macOS | Avancé |
| 18 | window_android_native | Fenêtre Android NativeActivity + EGL | Android | Avancé |
| 19 | window_web_canvas | Fenêtre Web Canvas (Emscripten) | Web | Intermédiaire |
| 20 | window_ios_uikit | Fenêtre iOS UIKit (ObjC++) | iOS | Avancé |
| 21 | zig_cross_compile | Cross-compile via Zig | Linux | Avancé |
| 22 | nk_multiplatform_sandbox | Framework fenêtrage multi-OS | 7 plateformes | Avancé |
| 23 | android_sdl3_ndk_mk | SDL3 Android via ndk-build | Win/Linux/Android | Avancé |
| 24 | all_platforms | Un projet, toutes les plateformes (filters) | Win/Linux/Android/Web | Avancé |
| 25 | opengl_triangle | Triangle OpenGL (WGL/GLX/EGL/WebGL) | Win/Linux/Android/Web | Avancé |
| 26 | xbox_project_kinds / uwp_dev_mode | Projets Xbox (GDK / UWP) | Xbox | Avancé |
| 27 | nk_window | Framework fenêtrage complet 7 plateformes | 7 plateformes | Avancé |

### Bases (01–04)

- **01_hello_console** — workspace minimal, `consoleapp()`, configurations
  Debug/Release, multi-plateformes via `filter()`. `jenga build`.
- **02_static_library** — `staticlib()` + app console, `dependson()`, `links()`,
  `location()`.
- **03_shared_library** — `sharedlib()` (.dll/.so/.dylib) liée à une app.
- **04_unit_tests** — `unitest()`, `with test():`, `testfiles()`. `jenga test`.

### Plateformes spécifiques (05–08, 15–20)

- **05_android_ndk** — APK NativeActivity multi-ABI (arm64-v8a, x86_64),
  `androidapplicationid`, `androidabis`, `androidnativeactivity(True)`.
- **06_ios_app** — app iOS Objective-C++, `iosbundleid`, `iosversion`.
- **07_web_wasm** — WebAssembly Emscripten, `emscripteninitialmemory`, serveur
  HTTP local généré.
- **08_custom_toolchain** — `with toolchain()`, `ccompiler`, `cppcompiler`.
- **15–20** — fenêtres natives : Win32, X11/Linux, Cocoa/macOS, Android EGL,
  Web Canvas, iOS UIKit.

### Avancé & cross-compilation (09–14, 21–27)

- **09_multi_projects** — graphe de dépendances, `startproject()`.
- **10_modules_cpp20** — modules C++20 `.cppm` (MSVC/Clang/GCC).
- **11_benchmark** — `jenga bench`, Google Benchmark.
- **12_external_includes** — modularité via `include("libs/*.jenga")`.
- **13_packaging** — `dependfiles()` + post-build.
- **14_cross_compile** — `targettriple()` Linux/Android depuis Windows.
- **21_zig_cross_compile** — Zig comme cross-compilateur.
- **22 / 27** — frameworks de fenêtrage multi-OS (Win, Linux, macOS, Android,
  iOS, Web, HarmonyOS).
- **23_android_sdl3_ndk_mk** — `newoption()`, build via `ndk-build`/Android.mk.
- **24_all_platforms** — un seul projet qui change de `kind`/toolchain par
  plateforme via filtres. `jenga build --platform jengaall`.
- **25_opengl_triangle** — rendu OpenGL multi-API (WGL/GLX/EGL+GLES3/WebGL).
- **26_xbox_*** — projets Xbox GDK (`xboxmode("gdk")`) et UWP Dev Mode.

### Fichiers de synthèse

- [`exemples.md`](../../Exemples/exemples.md) — doc détaillée des exemples.
- [`toolchains_by_example.md`](../../Exemples/toolchains_by_example.md) — toolchains recommandées par exemple.
- [`toolchains_cross_platform_templates.md`](../../Exemples/toolchains_cross_platform_templates.md) — templates Zig/Emscripten/NDK/HarmonyOS/Xbox.

---

## English

### Summary table

| # | Example | Topic | Platforms | Level |
|---|---------|-------|-----------|-------|
| 01 | hello_console | Minimal console app | Win/Linux/Android/Web | Beginner |
| 02 | static_library | Static library + linking | Win/Linux/Android/Web | Beginner |
| 03 | shared_library | Dynamic library (.dll/.so) | Win/Linux/Android/Web | Beginner |
| 04 | unit_tests | Unitest unit tests | Win/Linux/Android/Web | Intermediate |
| 05 | android_ndk | Multi-ABI Android NativeActivity APK | Android | Advanced |
| 06 | ios_app | iOS app (Objective-C++) | iOS | Advanced |
| 07 | web_wasm | WebAssembly (Emscripten) | Web | Intermediate |
| 08 | custom_toolchain | Custom Clang toolchain | Windows | Advanced |
| 09 | multi_projects | Multi-project workspace + deps | Win/Linux/Android/Web | Intermediate |
| 10 | modules_cpp20 | C++20 modules (`.cppm`) | Win/Linux | Advanced |
| 11 | benchmark | Google Benchmark | Win/Linux | Intermediate |
| 12 | external_includes | Composition via `include()` | Win/Linux/Android/Web | Intermediate |
| 13 | packaging | DEB/APK post-build + `dependfiles` | Win/Linux | Intermediate |
| 14 | cross_compile | Cross-compile Linux/Android (clang) | Linux/Android | Advanced |
| 15 | window_win32 | Native Win32 window | Windows | Intermediate |
| 16 | window_x11_linux | Linux X11 window | Linux | Intermediate |
| 17 | window_macos_cocoa | macOS Cocoa window (ObjC++) | macOS | Advanced |
| 18 | window_android_native | Android NativeActivity + EGL window | Android | Advanced |
| 19 | window_web_canvas | Web Canvas window (Emscripten) | Web | Intermediate |
| 20 | window_ios_uikit | iOS UIKit window (ObjC++) | iOS | Advanced |
| 21 | zig_cross_compile | Cross-compile via Zig | Linux | Advanced |
| 22 | nk_multiplatform_sandbox | Multi-OS windowing framework | 7 platforms | Advanced |
| 23 | android_sdl3_ndk_mk | SDL3 Android via ndk-build | Win/Linux/Android | Advanced |
| 24 | all_platforms | One project, every platform (filters) | Win/Linux/Android/Web | Advanced |
| 25 | opengl_triangle | OpenGL triangle (WGL/GLX/EGL/WebGL) | Win/Linux/Android/Web | Advanced |
| 26 | xbox_project_kinds / uwp_dev_mode | Xbox projects (GDK / UWP) | Xbox | Advanced |
| 27 | nk_window | Full 7-platform windowing framework | 7 platforms | Advanced |

### Basics (01–04)

- **01_hello_console** — minimal workspace, `consoleapp()`, Debug/Release,
  multi-platform via `filter()`. `jenga build`.
- **02_static_library** — `staticlib()` + console app, `dependson()`, `links()`.
- **03_shared_library** — `sharedlib()` (.dll/.so/.dylib) linked to an app.
- **04_unit_tests** — `unitest()`, `with test():`, `testfiles()`. `jenga test`.

### Platform-specific (05–08, 15–20)

- **05_android_ndk** — multi-ABI NativeActivity APK.
- **06_ios_app** — iOS Objective-C++ app.
- **07_web_wasm** — Emscripten WebAssembly + generated local HTTP server.
- **08_custom_toolchain** — manual `with toolchain()` definition.
- **15–20** — native windows: Win32, X11/Linux, Cocoa/macOS, Android EGL,
  Web Canvas, iOS UIKit.

### Advanced & cross-compilation (09–14, 21–27)

- **09_multi_projects** — dependency graph, `startproject()`.
- **10_modules_cpp20** — C++20 `.cppm` modules.
- **11_benchmark** — `jenga bench`, Google Benchmark.
- **12_external_includes** — modularity via `include("libs/*.jenga")`.
- **13_packaging** — `dependfiles()` + post-build.
- **14_cross_compile** — `targettriple()` Linux/Android from Windows.
- **21_zig_cross_compile** — Zig as a cross-compiler.
- **22 / 27** — multi-OS windowing frameworks (Win, Linux, macOS, Android, iOS,
  Web, HarmonyOS).
- **23_android_sdl3_ndk_mk** — `newoption()`, build via `ndk-build`/Android.mk.
- **24_all_platforms** — a single project switching `kind`/toolchain per platform
  via filters. `jenga build --platform jengaall`.
- **25_opengl_triangle** — multi-API OpenGL rendering (WGL/GLX/EGL+GLES3/WebGL).
- **26_xbox_*** — Xbox GDK projects (`xboxmode("gdk")`) and UWP Dev Mode.

### Summary files

- [`exemples.md`](../../Exemples/exemples.md) — detailed example docs.
- [`toolchains_by_example.md`](../../Exemples/toolchains_by_example.md) — recommended toolchains per example.
- [`toolchains_cross_platform_templates.md`](../../Exemples/toolchains_cross_platform_templates.md) — Zig/Emscripten/NDK/HarmonyOS/Xbox templates.
