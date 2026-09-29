# 27_nk_window

## Android Guide (NKWindow)

For Android programming details (safe area, rotation policy/runtime control, touch flow, camera notes), see:

- `Jenga/Exemples/27_nk_window/README_ANDROID_NKWINDOW.md`

## Launchers (Windows/Linux/macOS/Web)

After a build, you can generate run scripts for produced binaries/web outputs:

```bash
python3 scripts/generate_launchers.py --example-dir Jenga/Exemples/27_nk_window
```

Generated files (inside each `Build/Bin/<Config-Platform>/<Project>/` folder):
- `run.bat` for Windows native apps
- `run.sh` for Linux/macOS native apps
- `run_web.bat` and `run_web.sh` for Web targets

Important for Web/WASM:
- Do not open `*.html` directly with `file://...`
- Use `run_web.bat` or `run_web.sh` (they start a local HTTP server) to avoid CORS/WASM fetch errors.

## Description

Framework complet de **fenêtrage et gestion d'événements multi-plateformes** (7 systèmes d'exploitation) construit avec Jenga. Ce projet démontre une architecture professionnelle pour créer des applications graphiques portables avec :

- **7 plateformes supportées** : Windows, Linux, macOS, Android, iOS, Web, HarmonyOS
- **Abstraction complète** : API unifiée pour window creation, events, rendering
- **Architecture modulaire** : Core + Platform backends + User sandbox
- **Production-ready** : Gestion d'erreurs, logging, lifecycle complet

C'est l'exemple le plus complexe et abouti de Jenga, idéal pour démarrer un projet graphique multi-plateformes.

## Plateformes supportées

| Plateforme | Windowing API | Backend | Architectures |
|-----------|--------------|---------|---------------|
| **Windows** | Win32 API | Win32Window | x86_64 |
| **Linux** | X11/XCB | XlibWindow / XcbWindow | x86_64, ARM64 |
| **macOS** | Cocoa/AppKit | MacosWindow | x86_64, ARM64 (Apple Silicon) |
| **Android** | NativeActivity | AndroidWindow | arm64-v8a, x86_64 |
| **iOS** | UIKit | IosWindow | arm64 |
| **Web** | Canvas/HTML5 | EmscriptenWindow | wasm32 |
| **HarmonyOS** | ArkUI Native | HarmonyWindow | arm64 |

## Architecture du Projet

```
27_nk_window/
├── 27_nk_window.jenga              # Configuration multi-projets
├── NKWindow/                        # Bibliothèque core (staticlib)
│   ├── src/
│   │   ├── NKWindow/Core/          # API abstraite cross-platform
│   │   │   ├── NkEventSystem.cpp   # System d'événements
│   │   │   ├── NkGraphicsContext.cpp # Contexte graphique
│   │   │   ├── NkPlatform.cpp      # Détection plateforme
│   │   │   ├── NkRenderer.cpp      # Renderer abstrait
│   │   │   └── NkWindow.cpp        # Window abstraction
│   │   ├── NKWindow/Platform/      # Implémentations natives
│   │   │   ├── Win32/              # Windows backend
│   │   │   ├── Linux/              # X11/XCB backends
│   │   │   ├── macOS/              # Cocoa backend
│   │   │   ├── Android/            # Android backend
│   │   │   ├── iOS/                # UIKit backend
│   │   │   ├── Web/                # Emscripten backend
│   │   │   └── HarmonyOS/          # HarmonyOS backend
│   │   └── NKWindow/Entry/         # Entry points par plateforme
│   │       ├── main_win32.cpp
│   │       ├── main_linux.cpp
│   │       ├── main_macos.cpp
│   │       ├── main_android.cpp
│   │       ├── main_ios.cpp
│   │       ├── main_emscripten.cpp
│   │       └── main_harmony.cpp
├── Sandbox/                         # Application utilisateur (windowedapp)
│   └── src/
│       └── camera_full_example.cpp  # Exemple d'utilisation complète
└── Externals/                       # Dépendances externes (si nécessaire)
```

## Projets Jenga

Le workspace contient **2 projets** :

### 1. NKWindow (Static Library)
- **Type** : `staticlib()`
- **Rôle** : Framework de fenêtrage portable
- **Exports** : Headers dans `include/`
- **Backends** : Implémentations conditionnelles par plateforme

### 2. Sandbox (Windowed Application)
- **Type** : `windowedapp()`
- **Rôle** : Application de démonstration
- **Dépendances** : Link avec NKWindow
- **Code** : Utilise l'API NKWindow pour créer une fenêtre et gérer les événements

## API NKWindow (Abstractions)

### Core Classes

```cpp
// Platform detection et configuration
class Platform {
    static PlatformType GetCurrent();
    static const char* GetName();
};

// Gestion de fenêtre
class Window {
    bool Create(int width, int height, const char* title);
    void Show();
    void Hide();
    bool ShouldClose();
    void PollEvents();
    void SwapBuffers();
};

// Système d'événements
class EventSystem {
    void DispatchEvent(const Event& event);
    void RegisterHandler(EventType type, EventCallback callback);
};

// Contexte graphique (OpenGL/Vulkan/Metal/etc.)
class GraphicsContext {
    bool Initialize(Window* window);
    void MakeCurrent();
    void SwapBuffers();
};

// Renderer abstrait
class Renderer {
    void Clear(float r, float g, float b, float a);
    void Present();
};
```

## Fichiers Clés

### NkPlatformDetect.h
Macros de détection de plateforme :
```cpp
#define NK_PLATFORM_WINDOWS
#define NK_PLATFORM_LINUX
#define NK_PLATFORM_MACOS
#define NK_PLATFORM_ANDROID
#define NK_PLATFORM_IOS
#define NK_PLATFORM_WEB
#define NK_PLATFORM_HARMONY
```

### NkEventSystem.hpp
Types d'événements supportés :
- `EventType::WindowClose`
- `EventType::WindowResize`
- `EventType::KeyPress` / `KeyRelease`
- `EventType::MouseMove` / `MouseButton`
- `EventType::TouchBegin` / `TouchMove` / `TouchEnd`

### Entry Points
Chaque plateforme a son entry point spécifique :
- **Windows** : `WinMain()` dans `main_win32.cpp`
- **Linux** : `main()` dans `main_linux.cpp`
- **macOS** : `NSApplicationMain()` dans `main_macos.mm`
- **Android** : `android_main()` dans `main_android.cpp`
- **iOS** : `UIApplicationMain()` dans `main_ios.mm`
- **Web** : `main()` + `emscripten_set_main_loop()` dans `main_emscripten.cpp`
- **HarmonyOS** : `napi_*` entry dans `main_harmony.cpp`

## Compilation

### Build pour toutes les plateformes

```bash
jenga build --platform jengaall
```

### Build par plateforme

```bash
# Windows
jenga build --platform windows-x64-msvc

# Linux
jenga build --platform linux-x64-gcc

# macOS
jenga build --platform macos-arm64-clang

# Android (génère APK)
jenga build --platform android-arm64-ndk

# iOS (génère .app)
jenga build --platform ios-arm64-xcode

# Web (génère .wasm + .html)
jenga build --platform web-wasm32-emscripten

# HarmonyOS (génère .hap)
jenga build --platform harmonyos-arm64-ndk
```

## Exécution

### Desktop (Windows/Linux/macOS)
```bash
jenga run Sandbox
```

### Android
```bash
jenga deploy --platform android --device <device_id>
```

### iOS
```bash
# Ouvrir Xcode project généré
open Build/Xcode/Window.xcodeproj
# Ou deployer directement
jenga deploy --platform ios --device <device_id>
```

### Web
```bash
python -m http.server 8000 -d Build/Bin/Debug-Web/Sandbox/
# http://localhost:8000/Sandbox.html
```

## Code d'Exemple (Sandbox)

### camera_full_example.cpp

Démontre l'utilisation de l'API :

```cpp
#include <NKWindow/nk.hpp>

int nk_user_main() {
    using namespace nk;

    // Créer fenêtre
    Window window;
    if (!window.Create(800, 600, "NKWindow Demo")) {
        return -1;
    }

    // Créer contexte graphique
    GraphicsContext context;
    context.Initialize(&window);

    // Boucle principale
    while (!window.ShouldClose()) {
        window.PollEvents();

        // Rendu
        context.MakeCurrent();
        Renderer::Clear(0.2f, 0.3f, 0.4f, 1.0f);
        // ... votre code de rendu ...
        context.SwapBuffers();
    }

    return 0;
}
```

## Configuration Android & iOS

### Android
```python
androidapplicationid("com.Jenga.nativedemo")
androidminsdk(24)
androidtargetsdk(34)
androidabis(["arm64-v8a", "x86_64"])
androidnativeactivity(True)
```

### iOS
```python
iosbundleid("com.jenga.iosdemo")
iosversion("1.0")
iosminsdk("14.0")
```

## Points Clés

### Architecture en Couches

1. **Core** : API abstraite cross-platform
2. **Platform** : Implémentations natives par OS
3. **Entry** : Points d'entrée spécifiques
4. **Sandbox** : Application utilisateur

### Backends Multiples

- **Linux** : Support X11 (Xlib) et XCB (modern)
- **macOS** : Objective-C++ pour Cocoa
- **Mobile** : Gestion complète du lifecycle (pause/resume)
- **Web** : Integration avec Emscripten main loop

### Gestion d'Événements

- Pattern Observer pour les événements
- Callbacks type-safe
- Support touch + mouse + clavier
- Événements système (lifecycle, resize)

### Linking Conditionnel

Chaque plateforme link ses bibliothèques natives :
- **Windows** : `user32`, `gdi32`, `opengl32`
- **Linux** : `X11`, `GL`, `xcb` (optionnel)
- **macOS** : `Cocoa.framework`, `QuartzCore.framework`
- **Android** : `android`, `log`, `EGL`, `GLESv3`
- **iOS** : `UIKit.framework`, `OpenGLES.framework`

## Prérequis

### Tous
- Compilateur C++17 minimum

### Android
```bash
export ANDROID_SDK_ROOT=/path/to/android/sdk
export ANDROID_NDK_ROOT=/path/to/android/ndk
```

### iOS
- macOS avec Xcode 12+

### HarmonyOS
- HarmonyOS SDK + DevEco Studio

## Si NKWindow ne compile pas

**Symptôme** — `jenga build` échoue dès la bibliothèque NKWindow, sur **toutes**
les plateformes (Windows, macOS, Linux…), avec des erreurs comme :

```
NkWin32EventImpl.h: error: virtual function 'Front' has a different return type
    ('const NkEvent &') than the function it overrides (which has return type 'NkEvent *')
error: non-virtual member function marked 'override' hides virtual member function
NkSystem.cpp: error: allocating an object of abstract class type 'NkWin32EventImpl'
NkCocoaWindowImpl.mm:44:  error: no viable conversion from 'NkEvent' to 'std::unique_ptr<NkEvent>'   (macOS)
NkCocoaWindowImpl.mm:171: error: no viable conversion from 'NkEvent' to 'NkEvent *'                  (macOS)
```

puis, une fois la bibliothèque passée, dans Sandbox :
`NkEntry.h: fatal error: 'NKPatform/NkPlatformDetect.h' file not found`.

**Cause** — la file d'événements interne (`Core/IEventImpl.h`) avait été passée
aux pointeurs, comme l'API publique (`EventSystem::PollEvent()` rend un
`NkEvent*`) : `NkEvent* Front()`, `PushEvent(std::unique_ptr<NkEvent>)`,
`DispatchEvent(NkEvent*, …)`. Les neuf backends (`Platform/Win32`, `Cocoa`,
`XLib`, `XCB`, `Android`, `WASM`, `UIKit`, `UWP`, `Noop`) étaient restés à
l'ancienne API par valeur. S'y ajoutait un `#include` hérité du moteur
(`NKPatform/…`) dans `Core/NkEntry.h`. Et sous Windows, une fois compilé, aucun
événement n'arrivait à l'application (clavier, souris, demande de fermeture) :
`WindowProcStatic` ne retenait jamais l'`EventImpl` active.

**Version corrigée** — branche `fix/exemple27-evenements-pointeurs` du dépôt
Jenga ; toute version de Jenga **postérieure à 2.8.6** qui l'intègre contient la
correction (2.8.6 et avant : non corrigées). Votre copie est corrigée si
`NKWindow/src/NKWindow/Platform/Cocoa/NkCocoaEventImpl.h` déclare
`NkEvent* Front() const` (et non plus `const NkEvent& Front() const`).

La correction ne touche que le dossier `NKWindow/` : votre propre code
(`Sandbox/`) ne change pas. Il s'écrit avec l'API à pointeurs, comme
`Sandbox/src/main.cpp` :

```cpp
while (NkEvent* event = es.PollEvent())
{
    if (auto* e = event->As<NkWindowCloseEvent>()) { window.Close(); running = false; }
}
```

Pour mettre une copie à jour sans perdre son travail : remplacer uniquement
son dossier `NKWindow/` par celui de la version corrigée, puis relancer
`jenga build`.

À savoir sur macOS : le rendu logiciel n'a pas encore de chemin Cocoa
(`NkSoftwareRendererImpl::BlitOS` ne traite que Win32, XLib, XCB, Android et
Web) : même compilé, ce que dessine `Renderer` n'apparaît pas dans la fenêtre.

## Dépannage

**Erreur "Platform not detected"** :
- Vérifiez `NkPlatformDetect.h`
- Vérifiez que les macros de plateforme sont définies

**Linking errors** :
- Windows : Vérifiez que les .lib sont accessibles
- Linux : Installez `libx11-dev`, `libgl1-mesa-dev`
- macOS : Vérifiez que Frameworks sont trouvés

**Fenêtre ne s'ouvre pas** :
- Vérifiez les logs (stderr ou logcat sur Android)
- Vérifiez les permissions (Android: INTERNET, etc.)
- Testez d'abord un exemple simple par plateforme

**Crash au démarrage (Mobile)** :
- Android : Vérifiez `AndroidManifest.xml` généré
- iOS : Vérifiez `Info.plist` et provisioning

## Extensions Possibles

- **Vulkan/Metal support** : Ajouter backends graphiques modernes
- **Input abstraction** : Gamepad, touch gestures avancés
- **Audio** : Intégrer OpenAL ou SDL_mixer
- **Networking** : Sockets abstraits
- **File I/O** : Chemins platform-agnostic
- **ImGui integration** : UI immediate mode

## Comparaison avec SDL/GLFW

| Feature | NKWindow | SDL | GLFW |
|---------|----------|-----|------|
| Windows | ✓ | ✓ | ✓ |
| Linux | ✓ | ✓ | ✓ |
| macOS | ✓ | ✓ | ✓ |
| Android | ✓ | ✓ | ✗ |
| iOS | ✓ | ✓ | ✗ |
| Web | ✓ | ✓ | ✗ |
| HarmonyOS | ✓ | ✗ | ✗ |
| Custom | Complet | Limité | Limité |
| Jenga-native | ✓ | ✗ | ✗ |

**Avantage NKWindow** : Contrôle total, code source, Jenga-integration

## Étapes Suivantes

1. **Étudier** : Examinez les backends pour comprendre chaque plateforme
2. **Customiser** : Adaptez le code à vos besoins (Vulkan, audio, etc.)
3. **Étendre** : Ajoutez support pour d'autres plateformes (FreeBSD, PS5, Switch)
4. **Optimiser** : Profilez et optimisez les hot paths
5. **Produire** : Utilisez comme base pour votre moteur de jeu ou app

## Ressources

- **Exemple 22** : `22_nk_multiplatform_sandbox` (version alternative)
- **Exemple 15-20** : Exemples de fenêtrage simple par plateforme
- **Exemple 25** : OpenGL triangle multi-plateformes
- [Win32 API Reference](https://docs.microsoft.com/en-us/windows/win32/api/)
- [X11 Programming](https://tronche.com/gui/x/xlib/)
- [Cocoa Documentation](https://developer.apple.com/documentation/appkit)
- [Android NDK Guide](https://developer.android.com/ndk/guides)
