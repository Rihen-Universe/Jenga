# Jenga — Roadmap du projet

**Version courante :** v2.0.2 (réseau/pare-feu multi-plateforme, mai 2026)
**Document rédigé :** 27 mai 2026
**Auteur :** synthèse du code et des documents existants

> **Jenga** est un système de build cross-plateforme écrit en Python pour les
> projets C, C++, Objective-C, Assembly, Rust, Zig. Il remplace les
> Makefiles / CMakeLists par un DSL Python décrit dans des fichiers `.jenga`
> et compile directement (sans génération intermédiaire).

---

## 1. Vue d'ensemble

### 1.1 Objectifs initiaux du projet

| # | Objectif | Statut |
|---|----------|--------|
| 1 | DSL Python lisible avec `with workspace()` / `with project()` | ✅ Fait |
| 2 | Compilation directe sans génération de fichiers intermédiaires (vs CMake) | ✅ Fait |
| 3 | Support de **20+ plateformes** depuis une seule description | 🟡 Partiel (8 plateformes en production) |
| 4 | Détection automatique des toolchains (MSVC, GCC, Clang, NDK, Emscripten…) | ✅ Fait |
| 5 | Cache incrémental performant (gain x5 à x8.7 sur builds successifs) | ✅ Fait |
| 6 | Daemon pour commandes instantanées (50–200 ms) | ✅ Fait |
| 7 | Tests unitaires C++ intégrés (framework Unitest) | ✅ Fait |
| 8 | Packaging multi-format (MSI, EXE, ZIP, DEB, RPM, APK, AAB, IPA, PKG, DMG…) | 🟡 Partiel |
| 9 | Déploiement (adb, ios-deploy, etc.) | 🟡 Partiel (Linux non implémenté) |
| 10 | Publication sur registres (NuGet, vcpkg, Conan, npm, PyPI) | 🟡 Partiel (NuGet seul) |
| 11 | C++20 Modules (MSVC, Clang, GCC) | ✅ Fait |
| 12 | Générateurs de projets (CMake, Makefile, VS2022) | ✅ Fait |

### 1.2 Plateformes — état réel

| Plateforme | Statut | Notes |
|------------|--------|-------|
| Windows x64 | ✅ Production Ready | clang 21 (MSYS64/UCRT64), g++ 15, MSVC 14.44 |
| Linux x64 | ✅ Production Ready | clang 14, g++ 11 (Ubuntu 22.04 / WSL2) |
| Android (4 ABIs) | ✅ Production Ready | NDK r27c (arm64-v8a, armeabi-v7a, x86, x86_64) |
| Web / WASM | ✅ Production Ready | emsdk 4.0.22 |
| macOS | ✅ Prêt (machine macOS requise) | Apple Clang via `xcrun` |
| iOS / tvOS / watchOS / visionOS | ✅ Prêt (macOS + Xcode) | Apple Clang via `xcrun` |
| Xbox One / Series X\|S | 🟡 Partiel | Statique OK, DLL link KO sans Microsoft GDK |
| HarmonyOS | ✅ Prêt | LLVM du NDK OpenHarmony |
| Nintendo Switch | 🔒 Bloqué | Nécessite licence Nintendo |
| PlayStation 4/5 | 🔒 Bloqué | Nécessite licence Sony |

---

## 2. Outils de création d'installeurs Windows intégrés

> **Question posée :** quels outils Windows sont déjà intégrés pour générer
> les installeurs et activer les permissions réseau (PC ↔ PC, PC ↔ autre
> équipement) ?

### 2.1 Outils de packaging Windows supportés

La commande `jenga package --platform windows --type <type>` produit trois
formats. Voir [Jenga/Commands/Package.py:430](Jenga/Commands/Package.py#L430).

| Type | Outil utilisé | Détail | Statut |
|------|---------------|--------|--------|
| `zip` | `zipfile` (stdlib Python) | Archive simple avec exe + dépendances + DLLs auto-détectées | ✅ Fait |
| `msi` | **WiX Toolset 4+** (commande `wix`) | Format moderne `<Package>` + `<StandardDirectory>` + UI Wizard (EULA, choix dossier, raccourcis) | ✅ Fait |
| `msi` | **WiX Toolset 3** (`candle` + `light`) | Fallback legacy si WiX 4 absent | ✅ Fait |
| `exe` | **Inno Setup** (`iscc`) | Installeur EXE avec UI complète (EULA, choix dossier, raccourci bureau optionnel, estimation espace disque) | ✅ Fait |

### 2.2 Détection automatique des outils

Au lancement de `jenga package --platform windows`, Jenga **augmente
automatiquement le PATH de la session** pour trouver WiX / Inno Setup
installés aux emplacements standards
([Jenga/Commands/Package.py:386](Jenga/Commands/Package.py#L386)) :

```
%LOCALAPPDATA%\Programs\Inno Setup 6           (installation winget user)
%LOCALAPPDATA%\Programs\Inno Setup 5
C:\Program Files (x86)\Inno Setup 6             (installation MSI vendor)
C:\Program Files (x86)\Inno Setup 5
C:\Program Files\Inno Setup 6
%USERPROFILE%\.dotnet\tools                     (WiX 4 dotnet global tool)
C:\Program Files (x86)\WiX Toolset v3.11\bin    (WiX 3 legacy)
C:\Program Files (x86)\WiX Toolset v3.14\bin
```

L'utilisateur n'a donc pas à configurer son `PATH` manuellement : si WiX
ou Inno Setup sont installés au chemin par défaut, Jenga les trouve.

### 2.3 Installation des outils

| Outil | Commande d'installation |
|-------|------------------------|
| WiX 4+ (recommandé) | `dotnet tool install --global wix` |
| WiX 3 (legacy) | `winget install WiX.Toolset` (requiert admin) |
| Inno Setup | `winget install JRSoftware.InnoSetup` |
| Extension UI WiX 4 | installée automatiquement par Jenga (`wix extension add WixToolset.UI.wixext/5.0.2`) |

### 2.4 DSL associé (fichier `.jenga`)

Voir [Jenga/Core/Api.py:1870-1902](Jenga/Core/Api.py#L1870-L1902).

```python
with project("MonApp"):
    consoleapp()
    files(["src/**.cpp"])

    # Métadonnées installer
    apppublisher("Mon Studio")
    appversion("1.2.3")
    licensefile("LICENSE.md")          # .txt/.md auto-converti en RTF
    createdesktopshortcut(True)        # défaut : True
    dependfiles(["../../Resources"])   # ressources + DLLs embarquées

    # Icône — auto-conversion PNG/JPG → ICO
    appicon("res/icon.png")
    windowsicon("res/icon_win.ico")    # override Windows
```

---

## 3. Activation des connexions réseau (firewall Windows)

> **Question posée :** comment Jenga active-t-il les connexions réseau
> entre ordinateurs et autres équipements lors de l'installation ?

### 3.1 Problématique

Sans règle de firewall explicite, **Windows Defender bloque silencieusement
les connexions UDP/TCP entrantes** vers un exécutable. Conséquence
concrète : un jeu multijoueur LAN (ex. Pong PC ↔ Android) ne peut **pas
accepter de connexions entrantes** côté PC.

### 3.2 Solution implémentée — `netsh advfirewall`

Jenga utilise **`netsh.exe`** (livré nativement avec Windows depuis XP)
plutôt que la WiX Firewall Extension (qui nécessite un wixext séparé).
La règle s'applique aux **3 profils** (`Domain`, `Private`, `Public`).

#### 3.2.1 Installeur MSI (WiX 4) — CustomActions

Voir [Jenga/Commands/Package.py:894-941](Jenga/Commands/Package.py#L894-L941).

```xml
<!-- À l'installation : autorise l'exe en inbound TCP+UDP, tous profils -->
<CustomAction Id="Nk_FirewallAdd"
              Directory="INSTALLDIR"
              ExeCommand='netsh advfirewall firewall add rule
                          name="MonApp (Network)" dir=in action=allow
                          program="[#ExeFile]" enable=yes profile=any'
              Execute="deferred"
              Impersonate="no"
              Return="ignore"/>

<!-- À la désinstallation : retire la règle -->
<CustomAction Id="Nk_FirewallDel"
              Directory="INSTALLDIR"
              ExeCommand='netsh advfirewall firewall delete rule
                          name="MonApp (Network)"'
              Execute="deferred"
              Impersonate="no"
              Return="ignore"/>

<InstallExecuteSequence>
  <Custom Action="Nk_FirewallAdd" After="InstallFiles">NOT Installed</Custom>
  <Custom Action="Nk_FirewallDel" Before="RemoveFiles">Installed AND REMOVE="ALL"</Custom>
</InstallExecuteSequence>
```

Points clés :
- `Execute="deferred"` + `Impersonate="no"` → la CustomAction tourne en
  `NT AUTHORITY\SYSTEM` (privilèges admin requis pour modifier le firewall).
- `Return="ignore"` → on tolère les erreurs (ex. règle déjà existante).
- `[#ExeFile]` → MSI substitue le chemin d'install réel au moment du
  déploiement.

#### 3.2.2 Installeur EXE (Inno Setup) — section [Run] / [UninstallRun]

Voir [Jenga/Commands/Package.py:1075-1085](Jenga/Commands/Package.py#L1075-L1085).

```ini
[Run]
Filename: "{sys}\netsh.exe";
  Parameters: "advfirewall firewall add rule name=""MonApp (Network)""
              dir=in action=allow program=""{app}\MonApp.exe""
              enable=yes profile=any";
  StatusMsg: "Configuration du pare-feu Windows...";
  Flags: runhidden

[UninstallRun]
Filename: "{sys}\netsh.exe";
  Parameters: "advfirewall firewall delete rule name=""MonApp (Network)""";
  Flags: runhidden
```

### 3.3 Couverture par format (mise à jour — réseau multi-plateforme)

Toute la logique est centralisée dans [Jenga/Core/FirewallSpec.py](../Core/FirewallSpec.py)
et pilotée par le DSL `networkenabled()` / `firewallrule()`.

| Plateforme / Format | Permission/règle à l'install | Retrait au uninstall |
|---------------------|------------------------------|----------------------|
| Windows MSI (WiX 4+) | ✅ `CustomAction` deferred SYSTEM (netsh) | ✅ |
| Windows MSI (WiX 3 legacy) | ✅ `CustomAction` netsh (**parité atteinte**) | ✅ |
| Windows EXE (Inno Setup) | ✅ `[Run]` netsh | ✅ `[UninstallRun]` |
| Windows ZIP | ❌ pas d'install (manuel) | — |
| macOS PKG | ✅ postinstall `socketfilterfw --add/--unblockapp` | ✅ postinstall remove |
| macOS DMG | ❌ pas d'install (manuel) | — |
| Linux DEB | ✅ `postinst` ufw/firewalld/iptables (auto-détecté) | ✅ `postrm` |
| Android APK/AAB | ✅ `INTERNET`+`ACCESS_NETWORK_STATE`+`ACCESS_WIFI_STATE` auto | n/a |
| HarmonyOS HAP | ✅ `INTERNET`+`GET_NETWORK_INFO`+`GET_WIFI_INFO` (module.json5) | n/a |
| iOS IPA | ✅ `NSLocalNetworkUsageDescription`+`NSBonjourServices`+ATS | n/a |

### 3.4 Cas d'usage validés

- ✅ **Jeu multijoueur LAN PC ↔ Android** (ex. Pong) — référence au commentaire
  inline `[[pong_firewall_lan_fix]]` dans [Jenga/Commands/Package.py:1055](Jenga/Commands/Package.py#L1055).
- ✅ **Serveur HTTP local** (ex. Emscripten runner `run_<App>.bat`) — la règle
  autorise le port 8080 par défaut.
- ✅ **PC ↔ PC** (TCP/UDP entrant arbitraire vers l'exe).

---

## 4. Ce qu'il fallait faire (cahier des charges initial)

D'après le `Readme.md` racine et la philosophie du projet :

1. **Remplacer CMake / Makefile** par un DSL Python lisible et expressif.
2. **Une seule description = toutes les plateformes** (Windows, Linux,
   macOS, Android, iOS, Web, consoles).
3. **Builds rapides** : cache incrémental + daemon.
4. **Packaging et déploiement intégrés** (pas besoin d'outils externes
   comme `electron-builder`, `pkgbuild`, `gradle assembleRelease`…).
5. **Tests unitaires natifs** sans dépendance externe (Google Test, etc.).
6. **Toolchains détectées automatiquement** depuis l'environnement.
7. **Extensible** : nouveaux builders, nouvelles commandes ajoutables.
8. **Installeurs Windows complets** incluant EULA, raccourcis, **règles
   firewall** pour les apps réseau.

---

## 5. Ce qui a été fait (jusqu'à v2.0.2)

### 5.1 Cœur du build system

- ✅ DSL Python complet (200+ fonctions dans `Jenga/Core/Api.py`)
- ✅ Moteur de build (`Builder.py`) avec cache incrémental 3 niveaux
  (mtime → `.d` deps → SHA256 `.jenga_sig`)
- ✅ Daemon background pour commandes instantanées
- ✅ Compilation parallèle (`-j` flag, `ThreadPoolExecutor`)
- ✅ Résolution de dépendances par tri topologique (algorithme de Kahn)
- ✅ Système de filtres (`system:`, `config:`, `arch:`, `&&`, `||`, `!`)
- ✅ Expansion de variables dynamiques (`%{wks.location}`, `%{prj.name}`…)

### 5.2 Builders plateforme (10 implémentés)

- ✅ `Windows.py` — MSVC / clang-cl / MinGW
- ✅ `Linux.py` — GCC / Clang natif et cross-compile
- ✅ `Android.py` — NDK + APK / AAB + Universal APK multi-ABI
- ✅ `Emscripten.py` — WebAssembly + scripts runners `.bat`/`.sh`
- ✅ `Macos.py` — Apple Clang / Mach-O
- ✅ `Ios.py` — iOS / tvOS / watchOS / visionOS direct
- ✅ `MacosXcodeBuilder.py` — iOS via `xcodebuild`
- ✅ `Xbox.py` — GDK (GameCore) + UWP Dev Mode
- ✅ `HarmonyOs.py` — OpenHarmony NDK
- ✅ `Zig.py` — Cross-compilation via Zig
- ✅ `Switch.py` — Nintendo Switch (requiert SDK Nintendo)

### 5.3 Commandes CLI (23 disponibles)

`build`, `run`, `test`, `bench`, `clean`, `rebuild`, `package`, `deploy`,
`publish`, `sign`, `keygen`, `install`, `init`, `create`, `add`, `gen`,
`info`, `config`, `docs`, `examples`, `help`, `watch`, `registry`,
`profile`, `ide-setup`.

### 5.4 Packaging Windows (point central de votre question)

- ✅ ZIP (stdlib `zipfile`)
- ✅ MSI via **WiX 4+** moderne avec `WixUI_InstallDir` wizard
  (Welcome → EULA → InstallDir → Confirm → Install)
- ✅ MSI via **WiX 3 legacy** (fallback `candle`+`light`)
- ✅ EXE via **Inno Setup** avec EULA + choix dossier + raccourci bureau
  optionnel + estimation espace disque précise
- ✅ **Auto-détection** des outils WiX/Inno Setup dans les chemins
  standards (winget user, vendor MSI, dotnet tool, WiX 3 legacy)
- ✅ **Auto-extension** WiX UI (`WixToolset.UI.wixext/5.0.2`) installée
  idempotemment avant build
- ✅ **Conversion automatique** PNG/JPG → ICO pour les raccourcis bureau
  et menu Démarrer (via Pillow)
- ✅ **Conversion automatique** licence `.txt`/`.md` → `.rtf` (requis par
  WiX MSI EULA)
- ✅ **Auto-détection des DLL** transitives (`SHARED_LIB` dépendantes
  embarquées automatiquement à côté de l'exe)
- ✅ **Embarquage** des `dependfiles()` (resources, assets) avec
  préservation de la hiérarchie (`Resources/Pong/Textures/logo.png`)
- ✅ **Règles firewall Windows** ajoutées à l'install / retirées au
  uninstall (MSI WiX **3 et 4** + EXE Inno) — `netsh advfirewall` tous profils
- ✅ **Raccourcis** Menu Démarrer (toujours) + Bureau (configurable via
  `createdesktopshortcut()`) avec icône explicite

### 5.4bis Réseau multi-plateforme (nouveau — mai 2026)

- ✅ Module centralisé [Jenga/Core/FirewallSpec.py](../Core/FirewallSpec.py)
- ✅ DSL `networkenabled()`, `firewallrule(name, direction, action, protocol,
  ports, profiles, programOverride)`, `networkusagedescription()`,
  `bonjourservices()`, `iosallowarbitraryloads()`
- ✅ Windows MSI **WiX 3 legacy** : parité firewall avec WiX 4
- ✅ macOS PKG : postinstall/postupgrade `socketfilterfw`
- ✅ Linux DEB : hooks `postinst`/`postrm` ufw/firewalld/iptables auto-détectés
- ✅ Android : auto-injection `INTERNET`/`ACCESS_NETWORK_STATE`/`ACCESS_WIFI_STATE`
- ✅ HarmonyOS HAP : auto-injection `ohos.permission.INTERNET`/`GET_NETWORK_INFO`/
  `GET_WIFI_INFO` dans `module.json5` + DSL `harmonypermissions()`, `harmonyets()`
- ✅ iOS/macOS : `NSLocalNetworkUsageDescription`, `NSBonjourServices`,
  `NSAppTransportSecurity` dans Info.plist
- ✅ Règles personnalisées : ports précis, plages, protocoles tcp/udp, profils
  Windows, direction in/out/both
- ✅ Validé par 7 suites de tests unitaires (génération netsh/socketfilterfw/
  ufw, XML WiX 3/4, script Inno, JSON module.json5) — aucune régression

### 5.5 Autres plateformes — packaging

- ✅ Android : APK + AAB + Universal APK multi-ABI
- ✅ iOS : IPA via `xcrun` ou `xcodebuild`
- ✅ Linux : DEB (`dpkg-deb`)
- ✅ macOS : PKG (`pkgbuild`) + DMG (`create-dmg`)
- ✅ Web : ZIP avec favicons générés
- 🟡 Linux RPM, AppImage, Snap : pas encore implémentés

### 5.6 Tests, qualité, documentation

- ✅ 95 tests unitaires Python (`pytest`) — toutes les couches couvertes
- ✅ Guide complet utilisateur (`GUIDE_COMPLET_JENGA.md`, 20 chapitres)
- ✅ Wiki (`Jenga/Docs/wiki/`) — Installation, Premier Workspace,
  Commandes CLI, Toolchains, Tests, Documentation auto, Packaging, FAQ
- ✅ 27 exemples fonctionnels (`Jenga/Exemples/01_hello_console`
  → `27_nk_window`)
- ✅ Analyse complète du code : 3 bugs critiques corrigés et documentés
  (notes de version)

### 5.7 Installateur self-extracting maison (v2.0.4, mai 2026)

Alternative intégrée à Inno Setup / WiX, multi-plateforme, sans dépendance
externe. Code : [Jenga/Tools/Installer/](../Tools/Installer/). Spec :
[DESIGN.md](../Tools/Installer/DESIGN.md).

- ✅ Format `[stub natif C] + [payload manifeste+archive] + [trailer 80 octets]`
  avec **SHA-256 anti-tampering** vérifié AVANT extraction
- ✅ Stub C portable (Windows / Linux / macOS) : extraction, raccourcis,
  registre Uninstall, exécution firewall, désinstalleur
- ✅ **Anti-faux-positifs antivirus** : VERSIONINFO (éditeur Rihen, version)
  + manifeste UAC `asInvoker` + DPI aware + supportedOS Win7→Win11 (compilés
  via `rc.exe` MSVC ou `windres` MinGW, best-effort)
- ✅ **Signature de code multi-plateforme** : Authenticode `signtool` Windows
  (SHA-256 + timestamp), `codesign` macOS (`--options runtime --timestamp`),
  signature détachée GPG Linux. Skip propre sans certificat.
- ✅ **Icône composée** : icône user + petit "Jenga" en pill noire
  semi-transparente bas-droite sur le Setup.exe (les raccourcis user
  gardent l'icône clean). Multi-tailles 16→256, Pillow soft-dep.
- ✅ DSL signature (8 fonctions) : `signingcertificate`, `signingpassword`,
  `signingthumbprint`, `signingidentity`, `signingtimestampurl`,
  `signinggpgkey`, `signingentitlements`, `signingrequireadmin`
- ✅ Intégré à `jenga package --type jng` (Windows/Linux/macOS) sans
  remplacer msi/exe/zip/deb/pkg

### 5.8 UX du build (v2.0.4)

- ✅ **Résumé final warnings/erreurs** ([Reporter.py](../Utils/Reporter.py)) :
  `Reporter.PrintCollectedSummary()` affiche un encadré rouge/jaune après
  "BUILD COMPLETED" listant **tous** les warnings et erreurs émis pendant
  le build (texte intégral, pas de compteurs seuls)
- ✅ Flag `Reporter.Warning(..., critical=True)` pour les warnings bloquants
  fonctionnellement (ex. APK non signable) — surfacé en rouge
- ✅ Warning keystore Android escalé en `critical=True`
- ✅ **Sessions Windows aveugles aux `setx`** ([_envbackfill.py](../_envbackfill.py)) :
  à `import Jenga`, hydrate `os.environ` depuis HKCU/HKLM pour `ANDROID_*`,
  `JAVA_HOME`, `EMSDK`, `OHOS_SDK`, `GameDK`, `ZIG_ROOT` — plus besoin de
  redémarrer le terminal après configuration permanente
- ✅ **`AndroidBuilder` compile maintenant StaticLib/SharedLib** ([Android.py:986](../Core/Builders/Android.py#L986)) :
  cibler une lib pour Android (ex. `jenga build --platform android --target NKWindow`)
  compile la lib + ses deps via `super().Build()`, sans packaging APK,
  avec message clair (avant : retour 0 silencieux)
- ✅ **`Builder.Build` clarifie target introuvable** ([Builder.py:2073](../Core/Builder.py#L2073)) :
  attrape `ValueError` (en plus de `RuntimeError`) + liste des projets disponibles

---

## 6. Ce qui reste à faire

### 6.1 Court terme (v2.1, prioritaire)

| # | Tâche | Domaine | Effort estimé | Statut |
|---|-------|---------|---------------|--------|
| 1 | ~~Règle firewall MSI WiX 3 legacy (parité WiX 4)~~ | Packaging Windows | — | ✅ Fait |
| 2 | Publication PyPI officielle de `jenga-build` | Distribution | 0.5 j | ⬜ |
| 3 | Implémenter `RPM packaging` (`rpmbuild`) | Linux | 1 j | ⬜ |
| 4 | Implémenter `AppImage` (`appimagetool`) | Linux | 1 j | ⬜ |
| 5 | Implémenter `Snap` (`snapcraft`) | Linux | 1 j | ⬜ |
| 6 | Implémenter `jenga deploy --platform linux` | Déploiement | 1 j | ⬜ |
| 7 | Tests UI MSI (vérifier wizard sur Win10/Win11) | Validation | 0.5 j | ⬜ |
| 8 | Détection auto de **WiX 5+** (futur) | Packaging Windows | 0.5 j | ⬜ |
| 9 | ~~Documentation `firewall` dans le wiki~~ | Doc | — | ✅ Fait (Reseau-et-Pare-feu.md) |
| 10 | ~~DSL `firewallrule(...)` règles personnalisées~~ | API | — | ✅ Fait |
| 11 | Backend natif fenêtré HarmonyOS réel (exemple 27) | HarmonyOS | 2 j | ⬜ |
| 12 | Tests unitaires HarmonyOS dédiés | Qualité | 0.5 j | ⬜ |

### 6.2 Moyen terme (v2.2 — v2.5)

| # | Tâche | Domaine | Statut |
|---|-------|---------|--------|
| 1 | Publication multi-registres : `vcpkg`, `Conan`, `npm`, `PyPI` (NuGet déjà fait) | Distribution | ⬜ |
| 2 | Profilage complet pour toutes les plateformes (actuellement placeholder) | Outillage | ⬜ |
| 3 | ~~Code-signing automatisé Windows (signtool, certificats EV)~~ | Sécurité | ✅ v2.0.4 (installateur `--type jng`, DSL `signingxxx`) |
| 4 | Notarisation macOS automatisée (`xcrun notarytool`) | macOS | 🟡 codesign fait, notarisation à câbler |
| 5 | Mode `jenga doctor` — diagnostic complet de l'environnement | UX | ⬜ |
| 6 | Hot reload pour `jenga watch` sur exemples interactifs | DX | ⬜ |
| 7 | Plugin VS Code (syntaxe `.jenga`, IntelliSense) | Outillage | ⬜ |
| 8 | Intégration GitHub Actions (templates `.yml` générés) | CI/CD | ⬜ |
| 9 | Cache distribué (S3, Azure Blob) pour CI/CD partagé | Performance | ⬜ |
| 10 | Support **CMake → Jenga importer** (migration assistée) | Adoption | ⬜ |
| 11 | Installateur `--type jng` Phase 3 : GUI wizard EULA/dossier/composants + compression LZMA/zstd + hooks pré/post-install | Packaging | ⬜ |
| 12 | Installateur `--type jng` Phase 4 : multi-langues + associations fichiers/PATH + upgrade/repair | Packaging | ⬜ |

### 6.3 Long terme (v3.x)

| # | Vision |
|---|--------|
| 1 | Support natif Rust (toolchain `cargo` bridge) |
| 2 | Support natif Zig comme cible de premier ordre (au-delà du cross-compile) |
| 3 | Plateformes consoles non-Microsoft : PS4/5 et Switch (sous licence) |
| 4 | Mode SaaS : daemon distant pour builds incrementaux multi-machines |
| 5 | UI graphique optionnelle (TUI/GUI) pour workspaces complexes |
| 6 | Support packaging Linux Flatpak |
| 7 | Documentation interactive avec exemples exécutables (Jupyter-like) |

### 6.4 Dette technique / chantiers ouverts

- ⚠️ Cache SQLite volontairement désactivé en v2 — décider : remettre en
  service ou supprimer ?
- ⚠️ `Xbox.py` : link DLL KO sans Microsoft GDK installé. À documenter
  comme prérequis non-bloquant ou ajouter détection avec message clair.
- ⚠️ Builders `unused/` (`AppleMobileBuilder.py`, `Xbox_original.py`,
  `Xbox01.py`) à archiver ou supprimer définitivement.
- ⚠️ Convention `.jenga` vs `.py` — clarifier dans la doc pourquoi
  l'extension custom (parsing, IDE support).

---

## 7. Récapitulatif visuel — réponse à la question

```
Question : Quels outils Windows et activation réseau sont intégrés ?

┌─────────────────────────────────────────────────────────────────┐
│                                                                 │
│   Création installeur Windows (jenga package --platform windows)│
│                                                                 │
│   ┌──────────┐  ┌──────────────┐  ┌──────────────────┐          │
│   │   ZIP    │  │     MSI      │  │       EXE        │          │
│   │ (stdlib) │  │  WiX 4+ /3   │  │   Inno Setup     │          │
│   └──────────┘  └──────────────┘  └──────────────────┘          │
│                       │                    │                    │
│                       └────────┬───────────┘                    │
│                                ▼                                │
│              Auto-détection PATH (winget/vendor/dotnet)         │
│                                ▼                                │
│              UI Wizard (EULA + InstallDir + Shortcuts)          │
│                                                                 │
│   Activation réseau au déploiement :                            │
│                                                                 │
│   ┌─────────────────────────────────────────────────────┐       │
│   │  netsh advfirewall firewall add rule                │       │
│   │     name="App (Network)" dir=in action=allow        │       │
│   │     program="<exe>" enable=yes profile=any          │       │
│   └─────────────────────────────────────────────────────┘       │
│                                                                 │
│   ✓ Tous profils (Domain + Private + Public)                    │
│   ✓ Cas Inno EXE : section [Run] / [UninstallRun]               │
│   ✓ Cas MSI WiX 4 : <CustomAction> deferred SYSTEM              │
│   ✓ Désinstallation propre (règle retirée)                      │
│   ✗ MSI WiX 3 legacy : pas encore (à faire en v2.1)             │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## 8. Références dans le code

| Sujet | Fichier | Lignes |
|-------|---------|--------|
| Dispatch packaging par plateforme | [Jenga/Commands/Package.py](Jenga/Commands/Package.py) | 175–189 |
| Auto-augmentation du PATH (WiX/Inno) | [Jenga/Commands/Package.py](Jenga/Commands/Package.py#L386) | 386–426 |
| Pipeline Windows complet | [Jenga/Commands/Package.py](Jenga/Commands/Package.py#L429) | 429–526 |
| Génération WiX 4+ avec firewall | [Jenga/Commands/Package.py](Jenga/Commands/Package.py#L686) | 686–946 |
| Génération Inno Setup avec firewall | [Jenga/Commands/Package.py](Jenga/Commands/Package.py#L948) | 948–1086 |
| DSL installer (`licensefile`, etc.) | [Jenga/Core/Api.py](Jenga/Core/Api.py#L1870) | 1870–1910 |
| Champs dataclass Project | [Jenga/Core/Api.py](Jenga/Core/Api.py#L269) | 269–280 |

---

## 9. Comment tester l'installeur réseau

```bash
# 1. Build + package
jenga build  monapp.jenga
jenga package --platform windows --type exe   --project MonApp --output ./dist
jenga package --platform windows --type msi   --project MonApp --output ./dist

# 2. Exécuter l'installeur (admin pour la règle firewall)
.\dist\MonApp_setup.exe

# 3. Vérifier que la règle est créée
netsh advfirewall firewall show rule name="MonApp (Network)"

# 4. Tester la connexion LAN (depuis un autre PC / smartphone)
#    → l'app doit accepter les connexions entrantes UDP/TCP

# 5. Désinstaller et vérifier que la règle est supprimée
netsh advfirewall firewall show rule name="MonApp (Network)"
# → "Aucune règle correspondante" attendu
```

---

*Document généré à partir d'une lecture systématique du code et de la
documentation existante. Mettre à jour lors des prochaines releases.*
