# Feuille de route — Compilation & signature macOS/iOS depuis Windows via Zig

> Objectif : produire, **depuis Windows**, des binaires macOS (`.app`) et iOS
> (`.ipa`) signés, via la toolchain Zig, en réutilisant l'infrastructure de build
> Jenga existante (bundles, `Info.plist`, IPA). Ce document est une **feuille de
> route**, pas une implémentation.
>
> Projets concernés : `Jenga` (le système de build) et `NKCode` (l'app cible).

---

## 0. État réel de Jenga (point de départ)

| Brique | Fichier | État |
|---|---|---|
| Cross-compilation Zig générique | `Core/Builders/Zig.py` | `zig cc/c++ -target` → compile/link/`ar`. **Aucun** bundle, plist, ni signature |
| Toolchains Zig macOS déjà enregistrées | `Core/Toolchains.py:640-641` | `zig-macos-x86_64` (`x86_64-macos`), `zig-macos-arm64` (`aarch64-macos`). **Pas d'iOS** |
| Builder macOS (Apple Clang) | `Core/Builders/Macos.py` | Crée `.app`, gère `-isysroot`/`-F`/frameworks/icône. **Ne signe pas** |
| Builder iOS | `Core/Builders/Ios.py` | Bundle `.app` + `Info.plist` + `codesign` + `.ipa`. **Verrouillé macOS** (`xcrun`, `security`, `codesign`, `libtool`, `RuntimeError` si hôte ≠ macOS à `Ios.py:565`) |
| Signature (installeur) | `Tools/Installer/Signing.py` + DSL `signingxxx` | Authenticode/codesign/GPG pour le `.jng`, **pas** pour les bundles Apple |
| Sélection du builder | `Core/Builders/__init__.py:22-59` | Mappe `macOS→MacOSBuilder`, `iOS→IOSBuilder` par nom d'OS cible |

**Le verrou central** : la chaîne macOS suppose Apple Clang + SDK local ; la chaîne
iOS suppose un Mac (`xcrun`/`codesign`/`security`). Zig sait déjà produire du
Mach-O depuis Windows, mais **rien ne relie Zig aux étapes bundle + signature +
notarisation**. C'est ce gap que la feuille de route comble.

---

## Phase 0 — Décision d'architecture

Deux stratégies. **Retenue : B.**

- **A. Étendre `ZigBuilder`** pour produire aussi les bundles Apple. → Duplique la
  logique `.app`/`Info.plist`/`.ipa` déjà présente dans `Macos.py`/`Ios.py`.
- **B. Rendre `MacOSBuilder`/`DirectIOSBuilder` agnostiques de l'hôte
  (recommandé).** Introduire une abstraction « Apple toolchain » à deux
  implémentations :
  - `apple-clang` (hôte = Mac) : `xcrun` + `codesign` + `security` (existant).
  - `apple-zig` (hôte = Windows/Linux) : `zig cc/c++ -target <triple> -isysroot <SDK>`
    pour compiler/lier, **`rcodesign`** pour signer.

  On garde ainsi tout le code bundle/plist/IPA (correct) et on ne remplace que le
  **compilateur** et le **signataire** derrière une interface commune.

**Livrables** : interface `AppleToolchainBackend` (`compile()`, `link()`,
`sign(bundle, opts)`, `sdk_path(sdk_name)`). Le `RuntimeError` de `Ios.py:565`
n'est levé que lorsque aucun backend Apple n'est disponible.

---

## Phase 1 — SDK Apple + sysroot (prérequis matériel)

Zig fournit sa propre libc macOS **mais pas les frameworks Apple** (Cocoa, Metal,
OpenGL, UIKit…). NKCode/NKGui utilise Cocoa+OpenGL → **le SDK Apple est
obligatoire**.

1. Récupérer :
   - macOS SDK (`MacOSX.sdk`).
   - iOS SDK (`iPhoneOS.sdk` + `iPhoneSimulator.sdk`).
   - Sources : dépôts communautaires (`joseluisq/macosx-sdks`,
     `phracker/MacOSX-SDKs`) **ou** extraction depuis Xcode (licence Apple :
     usage interne, ne pas redistribuer dans un repo public).
2. Ranger dans un cache versionné, ex. `~/.jenga/apple-sdks/MacOSX14.5.sdk`,
   `iPhoneOS17.5.sdk`. **Ne pas committer** (`.gitignore`, comme `sysroot/`).
3. Câbler dans les toolchains : `toolchain.sysroot` (déjà consommé par `-isysroot`
   dans `Macos.py:274`) + `frameworkPaths` → `-F<SDK>/System/Library/Frameworks`.
   Les frameworks Apple sont livrés en `.tbd` (text stubs) que `ld64`/Zig linkent.
4. DSL : `applesdkpath(macos=..., ios=...)` ou détection via `JENGA_APPLE_SDK`
   (cohérent avec `_envbackfill.py`).

**Vigilance** : figer les versions SDK (min deployment target vs version SDK).

---

## Phase 2 — Compilation Zig vers Apple

1. **Enregistrer les triples manquants** dans `DetectZigToolchains()`
   (`Toolchains.py:636`) :
   - `zig-ios-arm64` → `aarch64-ios`
   - `zig-ios-sim-arm64` → `aarch64-ios-simulator`, `zig-ios-sim-x64` → `x86_64-ios-simulator`
   - (macOS déjà présent).
2. **Injecter avec le triple** : `-isysroot <SDK>`, `-F<frameworks>`, flag de
   version min (`-mios-version-min=`, `-mmacosx-version-min=`). Logique déjà
   présente côté clang dans `Ios.py:196-211`, à réutiliser pour Zig.
3. **Objective-C/C++** : le backend Cocoa passe par `.mm` / `NkMain.h`. Zig gère
   `zig c++ -x objective-c++`. Réutiliser `_NeedsObjectiveCppMode`
   (`Macos.py:57-78`).
4. **Validation** : hello-CLI Mach-O → NKWindow (lib) → NKCode complet. Vérifier
   avec `zig objdump` / `llvm-otool`.

**Risque connu** : des headers Apple récents utilisent des extensions Clang que le
Clang embarqué dans Zig ne suit pas toujours. Mitigation : épingler une version de
Zig testée ; garder Apple Clang comme secours sur Mac.

---

## Phase 3 — Bundles & packaging (réutilisation)

- **macOS** : `.app` déjà produit par `Macos.py:181` (`_CreateMacosAppBundle`).
  Rendre son appel indépendant du compilateur.
- **iOS** : `.app` + `Info.plist` + `.ipa` déjà dans `Ios.py:341-591`. Ces étapes
  (fichiers/plist/zip) sont **pur Python, déjà cross-platform** — elles
  fonctionnent sous Windows une fois le compilateur et le signataire remplacés.
- Injection réseau `Info.plist` (`BuildIosInfoPlistNetworkKeys`) : déjà branchée.

---

## Phase 4 — Signature cross-platform (cœur du sujet)

Remplacer `codesign`/`security` (macOS-only) par **`rcodesign`** (projet
`apple-codesign`, écrit en Rust, tourne nativement sur **Windows**) : signe
ad-hoc, avec certificat, gère entitlements, notarise.

Niveaux, du plus simple au plus complet :

1. **Ad-hoc (local, sans compte Apple)** — `rcodesign sign`. Permet d'exécuter le
   binaire **sur sa propre machine Apple**. Suffisant pour tester le pipeline. **Ne
   se distribue pas.**
2. **macOS Developer ID** — certificat `.p12` (Keychain d'un Mac ou portail Apple
   Developer). `rcodesign sign --p12-file cert.p12 --p12-password ...`. Requiert un
   **compte Apple Developer payant** pour un Developer ID distribuable.
3. **iOS** — le plus contraint :
   - `.p12` du certificat *Apple Development*/*Distribution*,
   - **provisioning profile** (`.mobileprovision`) lié au **Team ID** + **App ID**
     + **UDIDs** des appareils,
   - **entitlements** (`.plist`) cohérents avec le profil,
   - embarquer le profil (`embedded.mobileprovision`) puis signer avec `rcodesign`.

**Extensions DSL** (calquées sur les `signingxxx` existants) :
`applesigningcertificate(p12)`, `applesigningpassword(...)`, `appleteamid(...)`,
`provisioningprofile(path)`, `codesignentitlements(path)`,
`applesigningadhoc(True)`. Les champs `project.iosSigningIdentity`/`iosEntitlements`
existent déjà (`Ios.py:439-493`) — à généraliser.

---

## Phase 5 — Notarisation & installation

- **macOS (hors App Store)** : notarisation obligatoire depuis macOS 10.15.
  `rcodesign notarize` avec une **clé API App Store Connect** (`.p8` + Key ID +
  Issuer ID) — appel réseau, fonctionne depuis Windows. Puis stapling. Sans
  notarisation, Gatekeeper bloque (« développeur non identifié »).
- **iOS — installation sur appareil sans Mac** :
  - Sideload via **AltStore / SideStore / Sideloadly** (injecte le certificat),
  - ou `ideviceinstaller` (**libimobiledevice**, dispo Windows) via USB.
- **App Store** : upload via **Transporter / iTMSTransporter** (Java → Windows)
  avec la clé API App Store Connect. La revue App Store reste inévitable.

---

## Phase 6 — Intégration Jenga, CI & tests

1. **Factory** (`Core/Builders/__init__.py`) : backend `apple-zig` quand
   `host_os != macOS` (ou forcé via `usetoolchain("zig-macos-arm64")`), sinon
   `apple-clang`.
2. **NKCode.jenga** (`NKCode.jenga:91-95`) : le filtre `system:macOS` force
   aujourd'hui `usetoolchain("clang-native")`. Ajouter un embranchement Zig+SDK +
   frameworks. Ajouter un bloc `system:iOS`.
3. **Tests** : hello-CLI → NKWindow (lib) → NKCode (`.app`) → (`.ipa` signé).
   Validation finale sur matériel Apple réel uniquement.
4. Documenter (wiki : « Toolchains-et-Sysroots » + « Cible Apple depuis Windows »).

---

## Les 3 limites qu'aucune ingénierie ne supprime

1. **Compte Apple Developer** requis dès qu'on dépasse l'ad-hoc/local (Developer
   ID, provisioning iOS, notarisation, App Store).
2. **Le SDK Apple appartient à Apple** — obtention légale via Xcode, pas de
   redistribution publique.
3. **Exécuter/valider** exige du matériel Apple : Zig produit le Mach-O sous
   Windows, mais un binaire macOS ne *tourne* que sur un Mac, un `.ipa` que sur un
   iPhone (ou le simulateur, macOS-only). La chaîne de build est 100 % Windows ;
   la vérification finale ne l'est pas.

**Ordre de démarrage conseillé** : Phase 1 (SDK) → Phase 2 sur hello-CLI macOS →
signature ad-hoc (4.1) → NKCode `.app` → puis iOS (provisioning) → notarisation.

---

## Annexe — Tester sur son propre iPhone SANS Mac

Possible et fonctionnel **sur son propre appareil**, avec des contraintes :

| Aspect | Compte Apple **gratuit** | Compte Apple **payant (99 $/an)** |
|---|---|---|
| Durée de validité du certificat | **7 jours** (resigner/réinstaller chaque semaine) | **1 an** |
| Nb d'apps sideloadées simultanées | 3 max | large |
| Entitlements avancés (push, CarPlay…) | non | oui |
| Enregistrement UDID | auto via AltStore/Sideloadly | portail Developer |
| Distribution à d'autres personnes | non | TestFlight / App Store |

Chaîne concrète Windows → iPhone :
1. Build `.app`/`.ipa` iOS via Zig (Phases 1-3).
2. Signature : `rcodesign` **ou** laisser **AltStore/Sideloadly** signer avec
   l'Apple ID (ils gèrent certificat + provisioning + UDID automatiquement).
3. Installation USB via AltStore/SideStore/Sideloadly (ou `ideviceinstaller`).

**Ce qui reste impossible sans Mac** : lancer le **simulateur iOS** (macOS-only) ;
extraire soi-même le **SDK iOS** (nécessite Xcode une fois, ou dépôt communautaire).

---

## Annexe B — État réel du backend iOS de Nkentseu (audit code, juil. 2026)

Le prérequis n°1 avant toute toolchain, c'est que le moteur ait un backend iOS
fonctionnel. Audit du code source `Kernel/` :

**Verdict : backend iOS RÉEL, ~75 % complet. Le chemin UIKit + Metal fonctionne.**

| Composant | État | Preuve |
|---|---|---|
| Détection plateforme | ✅ Réel | `NkPlatformDetect.h:148-157` (`TARGET_OS_IPHONE` → `NKENTSEU_PLATFORM_IOS`, +SIMULATOR) |
| Fenêtre UIKit | ✅ Réel | `Platform/UIKit/NkUIKitWindow.mm` (750 lignes — parité ~Cocoa 816) : UIWindow/UIView/UIViewController, safe-area, multi-écran |
| Entrée tactile | ✅ Réel | `NkUIKitWindow.mm:32-127` multi-touch (32 points), pression/rayon ; `NkTouchEvent.h` gestes (pinch/rotate/pan/swipe/tap/long-press) |
| Point d'entrée app | ✅ Réel | `EntryPoints/NkAppleMobile.h` : `main()` → `UIApplicationMain` → `NkAppDelegate:UIApplicationDelegate` → `nkmain(state)` |
| Rendu **Metal** | ✅ Réel | `Backend/Metal/NkMetalContext.mm:48-92` : `CAMetalLayer` iOS, MTLDevice/Queue/depth/drawable. Factory `NkContextFactory.cpp:74-76` mappe iOS → Metal |
| Rendu **OpenGL ES** | ❌ **Stub** | `NkOpenGLContext.cpp:1133-1139` : `InitEAGL()` renvoie `false` (« compile NkOpenGLContext_iOS.mm » — **fichier absent**). Pas d'EAGLContext |
| Automatisation build iOS | ❌ Absent | Aucun bloc `system:iOS`, aucun template |
| App iOS d'exemple / test device | ❌ Absent | Aucune app testée sur appareil |

**Conséquences concrètes :**

1. **Sur iOS, il faut rendre en Metal, pas en OpenGL ES.** Le factory sélectionne
   déjà Metal automatiquement sur iOS — c'est cohérent. Mais l'OpenGL ES est une
   coquille : tout code qui force le chemin GL échouera à l'init.

2. **NKCode n'est PAS encore configuré pour iOS.** `NKCode.jenga` :
   - n'a **aucun bloc `filter("system:iOS")`** ;
   - dépend de **`NKGlad`** (loader OpenGL desktop) et lie l'OpenGL desktop dans le
     bloc Windows.
   → Pour tourner sur iPhone, NKCode doit gagner un bloc iOS qui : sélectionne le
   backend **Metal**, retire NKGlad/OpenGL desktop, et lie les frameworks
   **UIKit / Metal / QuartzCore / Foundation**. C'est un ajout applicatif, en plus
   de la toolchain Zig+SDK des Phases 1-6.

3. **Manques restants côté moteur** (à combler pour une vraie app) : clavier
   logiciel / IME iOS (non modélisé), cycle de vie background/notifications
   minimal. Non bloquants pour un premier rendu à l'écran, mais nécessaires pour un
   IDE utilisable.

**Chemin le plus court vers « NKCode s'affiche sur mon iPhone » :**
Phase 1 (SDK iOS) → Phase 2 (compilation Zig `aarch64-ios`, `.mm` en
objective-c++) → bloc `system:iOS` dans NKCode.jenga (backend **Metal**, frameworks
UIKit/Metal) → Phase 3 bundle `.ipa` → signature **ad-hoc/Sideloadly** (Phase 4.1)
→ install USB. Le moteur est prêt architecturalement ; le travail restant est la
**glu build (Zig+SDK+bloc iOS)** et la **signature**, pas le backend graphique.

---

## Annexe C — Résultats d'implémentation (juillet 2026)

Cette annexe documente ce qui a été **réellement construit et validé** (au-delà de
la feuille de route). Environnement de validation : Windows 11, **Zig 0.13.0**
(dossier local `C:\apple-sdks\zigldl\zig-windows-x86_64-0.13.0`), SDK macOS
`MacOSX11.3.sdk`, NDK r27, émulateur MEmu.

### C.1 — macOS depuis Windows : ✅ FONCTIONNEL (build Jenga + `.app`)

**Recette validée** (compile ObjC++ Cocoa/Metal + link + `.app`, arm64 & x86_64) :
```
zig-0.13.0 cc/c++ -target <arch>-macos \
   --sysroot <SDK> -isysroot <SDK> \
   -isystem <SDK>/usr/include \
   -F <SDK>/System/Library/Frameworks -framework X …
```
Deux déblocages décisifs : **Zig 0.13.0** (0.14/0.16 font *segfaulter* le linker
Mach-O) **+ `--sysroot`** (résolution des dépendances `/usr/lib/*.tbd`). `-isystem`
(pas `-I`) pour ne pas casser l'ordre des headers libc++.

**Réparation du SDK sous Windows** (symlinks impossibles) : les frameworks (et
`usr/lib`) utilisent des symlinks `Versions/Current/…` que `tar` ne peut pas créer.
Corrigé en recréant les entrées racine des frameworks via **jonctions Windows**
(`New-Item -ItemType Junction`, sans élévation) + copie des `.tbd` + restauration
de `libSystem.tbd`.

**Intégration Jenga (additive, opt-in, ne touche PAS le natif) :**
- `Core/Builders/MacosZig.py` — nouveau `MacosZigBuilder` (compile/link/`.app`).
- `Core/Builder.py` — attribut `allowsCrossCompileFromNonHost` (défaut **False**).
- `Commands/Build.py` — routage opt-in via l'option **`macos-backend=zig`**.
- `Core/Api.py` + `__init__.py` — DSL `macossdkpath()`, exports.
- Détection toolchain : wrappers `zig-cc`/`zig-c++`/`zig-ar` dans `C:\apple-sdks\bin`
  (sur le PATH) → Jenga enregistre `zig-macos-arm64`/`x86_64`.
- **Bundle `.app`** généré pour les `windowedapp()` (`_CreateAppBundle` : `Contents/
  MacOS/<exe>`, `Info.plist`, `Resources/`).

**Usage :**
```
set MACOS_SDK=C:\apple-sdks\MacOSX11.3.sdk        (ou macossdkpath() dans le .jenga)
PATH += C:\apple-sdks\bin
jenga build --platform macOS --macos-backend=zig  (+ MACOS_ARCH=x86_64 pour Intel)
```
**Validé end-to-end** : un workspace ObjC++/Foundation produit
`Build/Bin/<app>.app` (Mach-O arm64 valide + `Info.plist`).

**Wrappers autonomes (hors Jenga)** : `zig-macos-cc`/`zig-macos-c++`/`zig-macos-ar`
dans `C:\apple-sdks\bin` — compilent/lient un Mach-O macOS directement, sans Jenga.

**Limites** : SDK 11.3 = deployment target ≤ 11.3 ; **exécuter** un binaire macOS
exige un Mac (Windows produit le `.app`, ne le lance pas). Signature = Phase 4/5.

### C.2 — Linux depuis Windows : ✅ (zig natif + script sysroot)

Zig lie Linux nativement (glibc/musl embarqués). Pour du GUI (X11/GL/XCB/Wayland),
`Jenga/scripts/build_linux_sysroot.py` construit un sysroot depuis les `.deb`
Debian (100 % Windows, sans WSL). Validé : `Xlib.h` + `libX11.so` extraits.

### C.3 — IME Android complet : ✅ construit, wiring validé sur MEmu

- 3 classes Java `com.nkentseu.window` (`NkNativeActivity`, `NkTextInputView`,
  `NkInputConnection`) sous `NKWindow/…/Platform/Android/java/`.
- Pont JNI natif `NkAndroidTextInputJNI.cpp` → `NkTextInputEvent` (+ ancre anti-GC
  car natives appelées uniquement depuis Java, sinon éliminées du `.so`).
- `NkWindow::ShowSoftKeyboard` (Android) pilote l'Activity Java (IME complet CJK)
  et retombe sur le clavier natif (`KeyCharacterMap`) sinon.
- **Corrections Jenga (utiles à tout le projet)** : `androidjavafiles` résout
  maintenant `%{Module.location}` + le glob récursif `**.java` ; DSL
  `androidactivityclass()` + génération de l'`<activity>` custom dans le manifeste
  (la branche `has_java` était vide).
- **Validé sur MEmu** (`dumpsys`) : Activity custom lancée, `NkWindow` crée la
  fenêtre, **clavier affiché** (`mInputShown=true`), `mServedView=NkTextInputView`,
  `InputConnection` bindé, boucle native OK (touch → callback). Reste la
  confirmation d'un caractère via `commitText` (l'injection `adb input` de MEmu ne
  passe pas par `commitText` ; test réel = frappe clavier PC + `adb logcat -s NKIME`).

### C.4 — iOS / tvOS / watchOS depuis Windows : ✅ RÉSOLU (solution A+B)

**Le blocage initial** (documenté pour mémoire) : le driver `zig cc` ne sait pas
linker les cibles `.ios/.tvos/.watchos` — sa libSystem/libc interne est câblée
pour `.macos` uniquement (`target.os.tag == .macos`). Symptômes vérifiés :
`ldiv_t` (libc++ recompilée sans libc iOS) et « unable to find libSystem ». Le
`-isystem` ne propage pas au build interne de libc++ ; copier libSystem dans le
sysroot ne suffit pas. **La compilation, elle, marche.**

**La solution (A+B), validée end-to-end :**

1. **Compiler** avec `zig cc/c++` (marche déjà) → `.o` iOS.
2. **Lier avec un ld64 dédié = `ld.lld -flavor darwin`**, **fourni gratuitement
   par le NDK Android** (`…/toolchains/llvm/prebuilt/*/bin/ld.lld.exe`). Il
   contourne le driver Zig et résout les `.tbd` du SDK :
   ```
   ld.lld -flavor darwin -arch arm64 -platform_version ios <min> <sdk>
          -syslibroot <SDK> -execute -o <out> <objs>
          -framework UIKit -framework Foundation -framework Metal
          -lSystem -lc++ -lobjc
   ```
3. **SDK iOS COMPLET** (extrait de Xcode) : `usr/lib/{libSystem,libc++,libobjc}.tbd`
   présents. Les SDK « theos » headers-only **ne suffisent pas**.

**Résultat prouvé** : un `.mm` UIKit+Metal+CAMetalLayer → **Mach-O 64-bit arm64
iOS** (`platform ios, minos 12.0`), 100 % depuis Windows.

**Intégration Jenga (additive, opt-in, ne touche PAS le natif Ios.py) :**
- `Core/Builders/IosZig.py` — `IosZigBuilder` (compile zig + link ld.lld + bundle
  `.app` + `.ipa`), profils **iOS / tvOS / watchOS**.
- `Commands/Build.py` — routage opt-in **`ios-backend=zig`** (`apple-backend=zig`).
- `Core/Toolchains.py` — toolchains `zig-ios-arm64`/`zig-tvos-arm64`/`zig-watchos-arm64`.
- `Core/Api.py` + `__init__.py` — DSL `iossdkpath()`/`tvossdkpath()`/`watchossdkpath()`.
- Config : env `IOS_SDK`/`TVOS_SDK`/`WATCHOS_SDK`, `LD64` (défaut : ld.lld du NDK).

**Validé end-to-end** : `jenga build --platform iOS --ios-backend=zig` produit
`Build/Bin/<App>.app` (Mach-O arm64 + `Info.plist`) **et** `<App>.ipa` (non signé).

**Installation automatique** : `python Jenga/scripts/setup_apple_toolchain.py`
(zig 0.13 + SDKs + wrappers + détection ld.lld + vérification compile/link).
Wiki : [Compilation-Apple-depuis-Windows](Compilation-Apple-depuis-Windows.md).

**Reste** (hors périmètre build) : **signature/notarisation** du `.ipa` via
`rcodesign` (Windows) + provisioning Apple → install AltStore/Sideloadly.

### C.5 — Récapitulatif

| Cible depuis Windows | Compile | Link | Bundle | Statut |
|---|---|---|---|---|
| **macOS** (zig 0.13 + SDK) | ✅ | ✅ (zig) | ✅ `.app` | **Opérationnel** (`--macos-backend=zig`) |
| **Linux** (zig natif) | ✅ | ✅ | — | Opérationnel (+ script sysroot GUI) |
| **Android** (NDK) | ✅ | ✅ | ✅ APK | Opérationnel + **IME complet** |
| **iOS / tvOS / watchOS** | ✅ | ✅ (ld.lld darwin) | ✅ `.app`+`.ipa` | **Opérationnel** (`--ios-backend=zig`, SDK Xcode complet) |

> Prérequis iOS/tvOS/watchOS : **SDK Xcode complet** + **NDK** (pour `ld.lld`).
