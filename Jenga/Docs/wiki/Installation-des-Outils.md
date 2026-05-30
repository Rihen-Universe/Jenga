# Installation des outils / Tools Installation

> Comment installer **les compilateurs, SDK et NDK** que Jenga détecte et utilise.
> Voir aussi : [Installation](Installation.md) (pour installer Jenga lui-même)
> et [Toolchains et Sysroots](Toolchains-et-Sysroots.md) (pour leur usage).
>
> How to install **the compilers, SDKs and NDKs** Jenga detects and uses. See
> also: [Installation](Installation.md) (Jenga itself) and
> [Toolchains et Sysroots](Toolchains-et-Sysroots.md) (how to use them).

---

## Français

### 1. Compilateurs C/C++ (clang, gcc, MSVC)

#### Windows

**Option A — MSVC (recommandé pour cibler Windows natif)** : installer
*Visual Studio Build Tools 2022* (~1.5 Go, gratuit) avec la charge de travail
*Desktop development with C++* :

```powershell
winget install Microsoft.VisualStudio.2022.BuildTools `
  --override "--add Microsoft.VisualStudio.Workload.VCTools --quiet"
```

**Option B — LLVM officiel (clang)** :

```powershell
winget install LLVM.LLVM     # ajoute clang/clang++ au PATH
```

**Option C — MSYS2 (gcc + clang Unix-like)** :

```powershell
winget install MSYS2.MSYS2
# Puis dans MSYS2 UCRT64 :
pacman -S --noconfirm mingw-w64-ucrt-x86_64-toolchain `
  mingw-w64-ucrt-x86_64-clang
# Ajouter au PATH : C:\msys64\ucrt64\bin
```

#### Linux

```bash
# Debian / Ubuntu
sudo apt update && sudo apt install -y build-essential clang lld

# Fedora / RHEL
sudo dnf install -y gcc gcc-c++ clang lld make

# Arch
sudo pacman -S --needed base-devel clang lld
```

#### macOS

```bash
# Apple Clang (livré avec Xcode Command Line Tools, suffit pour la majorité)
xcode-select --install

# (optionnel) clang/llvm via Homebrew, en plus
brew install llvm
```

### 2. Android : NDK + SDK + JDK

**JDK 17** (requis pour `apksigner`, `d8`, `aapt2`) :

```powershell
# Windows
winget install EclipseAdoptium.Temurin.17.JDK
# Linux : sudo apt install openjdk-17-jdk
# macOS : brew install --cask temurin@17
```

**Android SDK + NDK via *Command Line Tools*** (sans installer Android Studio) :

1. Télécharger les *Command line tools only* :
   <https://developer.android.com/studio#command-line-tools-only>
2. Décompresser dans `C:\Android\cmdline-tools\latest\` (Windows) ou
   `~/Android/cmdline-tools/latest/` (Linux/macOS).
3. Installer SDK + NDK via `sdkmanager` :

```bash
# Depuis <SDK>/cmdline-tools/latest/bin/
./sdkmanager --install "platform-tools" "platforms;android-34" \
             "build-tools;34.0.0" "ndk;27.0.12077973"
./sdkmanager --licenses   # accepter les licences
```

**Variables d'environnement à poser** (chemins à adapter) :

```powershell
# Windows — permanent via setx (effet aux NOUVELLES sessions ;
# Jenga rattrape via HKCU au boot, cf. section 5)
setx ANDROID_HOME       "C:\Android"
setx ANDROID_SDK_ROOT   "C:\Android"
setx ANDROID_NDK_ROOT   "C:\Android\ndk\27.0.12077973"
setx ANDROID_NDK_HOME   "C:\Android\ndk\27.0.12077973"
setx JAVA_HOME          "C:\Program Files\Java\jdk-17"
```

```bash
# Linux / macOS — dans ~/.zshrc ou ~/.bashrc
export ANDROID_HOME=$HOME/Android
export ANDROID_SDK_ROOT=$ANDROID_HOME
export ANDROID_NDK_ROOT=$ANDROID_HOME/ndk/27.0.12077973
export ANDROID_NDK_HOME=$ANDROID_NDK_ROOT
export JAVA_HOME=$(/usr/libexec/java_home -v 17)   # macOS
# Linux : export JAVA_HOME=/usr/lib/jvm/java-17-openjdk
```

### 3. HarmonyOS : Command Line Tools

DevEco SDK requis (NDK OpenHarmony + outils `hvigor`, `hap-sign-tool`,
`hdc`). Deux options :

**Option A — DevEco Studio complet** (graphique, installe automatiquement
le SDK) : <https://developer.huawei.com/consumer/en/deveco-studio/>.

**Option B — SDK seul** (CI, postes sans IDE) :

1. Inscription compte Huawei Developer.
2. Télécharger l'archive *OpenHarmony SDK* depuis
   <https://gitee.com/openharmony/docs> (ou *DevEco SDK* sur le portail).
3. Décompresser dans `C:\Huawei\Sdk\openharmony\<version>\` (Windows) ou
   `~/Huawei/Sdk/openharmony/<version>/` (Linux/macOS).
4. Variables d'env :

```powershell
setx OHOS_SDK     "C:\Huawei\Sdk\openharmony\11"
setx HARMONY_SDK  "C:\Huawei\Sdk\openharmony\11"
# Optionnel : NDK natif OpenHarmony
setx OHOS_NDK_HOME "C:\Huawei\Sdk\openharmony\11\native"
```

### 4. Emscripten (WebAssembly / Web)

Multi-plateforme via le script officiel `emsdk` :

```bash
git clone https://github.com/emscripten-core/emsdk.git
cd emsdk
./emsdk install latest      # Windows : emsdk.bat install latest
./emsdk activate latest     # Windows : emsdk.bat activate latest
# Activer dans la session courante :
source ./emsdk_env.sh       # Windows : emsdk_env.bat
```

**Variables d'env permanentes** (pour que Jenga détecte sans `emsdk_env`) :

```powershell
# Windows
setx EMSDK              "C:\emsdk"
setx EMSCRIPTEN_ROOT    "C:\emsdk\upstream\emscripten"
```

```bash
# Linux / macOS
export EMSDK=$HOME/emsdk
export EMSCRIPTEN_ROOT=$EMSDK/upstream/emscripten
export PATH="$EMSDK:$EMSCRIPTEN_ROOT:$PATH"
```

### 5. Variables d'environnement — récapitulatif

| Variable | Pour quoi | Exemple |
|---|---|---|
| `ANDROID_HOME` / `ANDROID_SDK_ROOT` | SDK Android | `C:\Android` |
| `ANDROID_NDK_ROOT` / `ANDROID_NDK_HOME` | NDK Android | `C:\Android\ndk\27.0.12077973` |
| `JAVA_HOME` / `JDK_HOME` | JDK (apksigner, d8) | `C:\Program Files\Eclipse Adoptium\jdk-17` |
| `OHOS_SDK` / `HARMONY_SDK` | SDK OpenHarmony | `C:\Huawei\Sdk\openharmony\11` |
| `OHOS_NDK_HOME` | NDK natif OpenHarmony | `C:\Huawei\Sdk\openharmony\11\native` |
| `EMSDK` | Racine emsdk | `C:\emsdk` |
| `EMSCRIPTEN_ROOT` | clang Emscripten | `C:\emsdk\upstream\emscripten` |
| `ZIG_ROOT` | Zig (cross-compile) | `C:\zig\0.13.0` |

**Astuce Windows — sessions ouvertes avant `setx`** : à l'`import Jenga`,
Jenga hydrate automatiquement `os.environ` depuis le registre
(`HKCU\Environment` puis `HKLM\…\Environment`). Plus besoin de redémarrer le
terminal après configuration permanente. Voir [_envbackfill.py](../../_envbackfill.py).

### 6. Vérifier l'installation

```bash
# Vérifie tout d'un coup (Jenga liste les toolchains détectées)
jenga config toolchains

# Manuellement :
cc --version              # ou clang --version / gcc --version / cl
which javac               # ou where javac (Windows)
$ANDROID_NDK_ROOT/toolchains/llvm/prebuilt/*/bin/clang --version
emcc --version
```

---

## English

### 1. C/C++ compilers (clang, gcc, MSVC)

#### Windows

**Option A — MSVC (recommended for native Windows targets)**: install
*Visual Studio Build Tools 2022* (~1.5 GB, free) with the *Desktop development
with C++* workload:

```powershell
winget install Microsoft.VisualStudio.2022.BuildTools `
  --override "--add Microsoft.VisualStudio.Workload.VCTools --quiet"
```

**Option B — Official LLVM (clang)**:

```powershell
winget install LLVM.LLVM     # adds clang/clang++ to PATH
```

**Option C — MSYS2 (gcc + clang, Unix-like)**:

```powershell
winget install MSYS2.MSYS2
# Then in MSYS2 UCRT64:
pacman -S --noconfirm mingw-w64-ucrt-x86_64-toolchain `
  mingw-w64-ucrt-x86_64-clang
# Add to PATH: C:\msys64\ucrt64\bin
```

#### Linux

```bash
# Debian / Ubuntu
sudo apt update && sudo apt install -y build-essential clang lld

# Fedora / RHEL
sudo dnf install -y gcc gcc-c++ clang lld make

# Arch
sudo pacman -S --needed base-devel clang lld
```

#### macOS

```bash
# Apple Clang (ships with Xcode Command Line Tools, enough for most cases)
xcode-select --install

# (optional) extra clang/llvm via Homebrew
brew install llvm
```

### 2. Android: NDK + SDK + JDK

**JDK 17** (required for `apksigner`, `d8`, `aapt2`):

```powershell
# Windows
winget install EclipseAdoptium.Temurin.17.JDK
# Linux: sudo apt install openjdk-17-jdk
# macOS: brew install --cask temurin@17
```

**Android SDK + NDK via *Command Line Tools*** (without installing
Android Studio):

1. Download *Command line tools only*:
   <https://developer.android.com/studio#command-line-tools-only>
2. Extract to `C:\Android\cmdline-tools\latest\` (Windows) or
   `~/Android/cmdline-tools/latest/` (Linux/macOS).
3. Install SDK + NDK via `sdkmanager`:

```bash
# From <SDK>/cmdline-tools/latest/bin/
./sdkmanager --install "platform-tools" "platforms;android-34" \
             "build-tools;34.0.0" "ndk;27.0.12077973"
./sdkmanager --licenses   # accept licenses
```

**Environment variables** (adapt the paths):

```powershell
# Windows — persistent via setx (applies to NEW sessions;
# Jenga backfills already-open sessions from HKCU at boot, see section 5)
setx ANDROID_HOME       "C:\Android"
setx ANDROID_SDK_ROOT   "C:\Android"
setx ANDROID_NDK_ROOT   "C:\Android\ndk\27.0.12077973"
setx ANDROID_NDK_HOME   "C:\Android\ndk\27.0.12077973"
setx JAVA_HOME          "C:\Program Files\Eclipse Adoptium\jdk-17"
```

```bash
# Linux / macOS — in ~/.zshrc or ~/.bashrc
export ANDROID_HOME=$HOME/Android
export ANDROID_SDK_ROOT=$ANDROID_HOME
export ANDROID_NDK_ROOT=$ANDROID_HOME/ndk/27.0.12077973
export ANDROID_NDK_HOME=$ANDROID_NDK_ROOT
export JAVA_HOME=$(/usr/libexec/java_home -v 17)   # macOS
# Linux: export JAVA_HOME=/usr/lib/jvm/java-17-openjdk
```

### 3. HarmonyOS: Command Line Tools

You need the DevEco SDK (OpenHarmony NDK + `hvigor`, `hap-sign-tool`, `hdc`).
Two options:

**Option A — Full DevEco Studio** (GUI, installs the SDK automatically):
<https://developer.huawei.com/consumer/en/deveco-studio/>.

**Option B — SDK only** (CI, headless machines):

1. Register a Huawei Developer account.
2. Download the *OpenHarmony SDK* from
   <https://gitee.com/openharmony/docs> (or *DevEco SDK* from the portal).
3. Extract to `C:\Huawei\Sdk\openharmony\<version>\` (Windows) or
   `~/Huawei/Sdk/openharmony/<version>/` (Linux/macOS).
4. Environment variables:

```powershell
setx OHOS_SDK     "C:\Huawei\Sdk\openharmony\11"
setx HARMONY_SDK  "C:\Huawei\Sdk\openharmony\11"
# Optional: native OpenHarmony NDK
setx OHOS_NDK_HOME "C:\Huawei\Sdk\openharmony\11\native"
```

### 4. Emscripten (WebAssembly / Web)

Cross-platform via the official `emsdk` script:

```bash
git clone https://github.com/emscripten-core/emsdk.git
cd emsdk
./emsdk install latest      # Windows: emsdk.bat install latest
./emsdk activate latest     # Windows: emsdk.bat activate latest
# Activate in current session:
source ./emsdk_env.sh       # Windows: emsdk_env.bat
```

**Persistent env vars** (so Jenga detects without `emsdk_env`):

```powershell
# Windows
setx EMSDK              "C:\emsdk"
setx EMSCRIPTEN_ROOT    "C:\emsdk\upstream\emscripten"
```

```bash
# Linux / macOS
export EMSDK=$HOME/emsdk
export EMSCRIPTEN_ROOT=$EMSDK/upstream/emscripten
export PATH="$EMSDK:$EMSCRIPTEN_ROOT:$PATH"
```

### 5. Environment variables — summary

| Variable | Purpose | Example |
|---|---|---|
| `ANDROID_HOME` / `ANDROID_SDK_ROOT` | Android SDK | `C:\Android` |
| `ANDROID_NDK_ROOT` / `ANDROID_NDK_HOME` | Android NDK | `C:\Android\ndk\27.0.12077973` |
| `JAVA_HOME` / `JDK_HOME` | JDK (apksigner, d8) | `C:\Program Files\Eclipse Adoptium\jdk-17` |
| `OHOS_SDK` / `HARMONY_SDK` | OpenHarmony SDK | `C:\Huawei\Sdk\openharmony\11` |
| `OHOS_NDK_HOME` | Native OpenHarmony NDK | `C:\Huawei\Sdk\openharmony\11\native` |
| `EMSDK` | emsdk root | `C:\emsdk` |
| `EMSCRIPTEN_ROOT` | Emscripten clang | `C:\emsdk\upstream\emscripten` |
| `ZIG_ROOT` | Zig (cross-compile) | `C:\zig\0.13.0` |

**Windows tip — sessions opened before `setx`**: at `import Jenga`, Jenga
automatically hydrates `os.environ` from the registry (`HKCU\Environment`
then `HKLM\…\Environment`). No need to restart your terminal after
persistent configuration. See [_envbackfill.py](../../_envbackfill.py).

### 6. Verify the installation

```bash
# Check everything at once (Jenga lists detected toolchains)
jenga config toolchains

# Manually:
cc --version              # or clang --version / gcc --version / cl
which javac               # or where javac (Windows)
$ANDROID_NDK_ROOT/toolchains/llvm/prebuilt/*/bin/clang --version
emcc --version
```
