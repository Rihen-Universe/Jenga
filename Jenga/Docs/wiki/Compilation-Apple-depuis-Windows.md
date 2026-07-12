# Compilation Apple depuis Windows (macOS / iOS / tvOS / watchOS)

Jenga peut **cross-compiler des binaires Apple depuis Windows** (ou Linux), sans
Mac, en s'appuyant sur **Zig** (compilateur) et **`ld.lld -flavor darwin`**
(linker Mach-O, fourni par le NDK Android). C'est **additif et opt-in** : les
builders natifs (Xcode/clang sur un vrai Mac) ne sont jamais modifiés.

| Cible | Compile | Link | Bundle | Activation |
|---|---|---|---|---|
| **macOS** | Zig 0.13 | Zig 0.13 | `.app` | `--macos-backend=zig` |
| **iOS** | Zig 0.13 | `ld.lld -flavor darwin` | `.app` + `.ipa` | `--ios-backend=zig` |
| **tvOS** | Zig 0.13 | `ld.lld -flavor darwin` | `.app` + `.ipa` | `--ios-backend=zig` |
| **watchOS** | Zig 0.13 | `ld.lld -flavor darwin` | `.app` + `.ipa` | `--ios-backend=zig` |

> ⚠️ **Exécuter** un binaire Apple exige toujours du matériel Apple (Windows
> **produit** le `.app`/`.ipa`, ne le lance pas). La **signature/notarisation**
> se fait ensuite (voir plus bas).

---

## 1. Prérequis

1. **Zig 0.13.0** (impératif : 0.14/0.16 font *segfaulter* le linker Mach-O).
2. **SDK Apple** :
   - macOS : SDK complet (ex. [phracker/MacOSX-SDKs 11.3](https://github.com/phracker/MacOSX-SDKs/releases/tag/11.3)).
   - iOS/tvOS/watchOS : **SDK COMPLET extrait de Xcode** (avec
     `usr/lib/libSystem.tbd`, `libc++.tbd`, `libobjc.tbd`). Les SDK « theos »
     *headers-only* (ex. certains dépôts communautaires) **ne suffisent PAS** au
     link.
3. **NDK Android** (pour `ld.lld`, le linker Mach-O). `ANDROID_NDK_HOME` défini.

## 2. Installation automatique

```bat
python Jenga/scripts/setup_apple_toolchain.py --root C:\apple-sdks ^
    --ios-sdk-url <URL_d_un_SDK_iOS_complet.tar.gz>
```
Le script : installe Zig 0.13, télécharge/répare les SDK (jonctions frameworks +
`.tbd`), crée les wrappers `zig-cc`/`zig-c++`, détecte `ld.lld` du NDK, **vérifie**
par un compile+link macOS **et** iOS, puis affiche les variables à définir.

Sources par défaut : macOS = phracker ; iOS =
[qianjigui/iOS-sdks](https://github.com/qianjigui/iOS-sdks) (vérifier qu'il est
complet, sinon utiliser un dump Xcode).

## 3. Configuration (manuelle)

```bat
set PATH=%PATH%;C:\apple-sdks\bin
set ZIG_MACOS=C:\apple-sdks\zigldl\zig-windows-x86_64-0.13.0\zig.exe
set MACOS_SDK=C:\apple-sdks\MacOSX11.3.sdk
set IOS_SDK=C:\apple-sdks\iPhoneOS12.2.sdk
set LD64=C:\Android\ndk\<ver>\toolchains\llvm\prebuilt\windows-x86_64\bin\ld.lld.exe
```
(Alternative au `set` : DSL `macossdkpath()`, `iossdkpath()`, `tvossdkpath()`,
`watchossdkpath()` dans le `.jenga`.)

## 4. Build

```bat
jenga build --platform macOS --macos-backend=zig
jenga build --platform iOS   --ios-backend=zig
jenga build --platform tvOS  --ios-backend=zig
```
Produit `Build/Bin/.../<App>.app` (+ `.ipa` non signé pour iOS/tvOS/watchOS).
Ajouter `MACOS_ARCH=x86_64` pour du macOS Intel.

## 5. Comment ça marche (recette)

**Compile** (toutes cibles) :
```
zig cc/c++ -target <arch>-<os> --sysroot <SDK> -isysroot <SDK>
           -isystem <SDK>/usr/include -F <SDK>/System/Library/Frameworks
```
`-isystem` (pas `-I`) pour préserver l'ordre des headers libc++.

**Link macOS** : `zig` gère le link Mach-O nativement (avec `--sysroot`).

**Link iOS/tvOS/watchOS** : le driver `zig cc` **ne sait pas** linker ces cibles
(sa libSystem/libc interne est câblée pour `.macos` uniquement). On contourne
avec un vrai ld64 :
```
ld.lld -flavor darwin -arch <arch> -platform_version <plat> <min> <sdk>
       -syslibroot <SDK> (-dylib|-execute) -o <out> <objs>
       -framework X ... -lSystem -lc++ -lobjc
```

## 6. Signature (intégrée, opt-in) & installation

La signature est **câblée dans le builder** via [`rcodesign`](https://github.com/indygreg/apple-platform-rs)
(un binaire Rust qui signe des Mach-O **depuis Windows**, sans Mac). Par défaut le
`.app` est **non signé** ; on l'active par variables d'environnement :

| Env | Rôle |
|-----|------|
| `RCODESIGN` | chemin de `rcodesign.exe` (sinon cherché dans le `PATH`) |
| `IOS_SIGN=adhoc` | signature **ad-hoc** (dev/local, pas d'installation device) |
| `IOS_SIGN=<cert.p12>` | signature avec **certificat Apple** (`.p12`) |
| `IOS_SIGN_PASS` | mot de passe du `.p12` |
| `IOS_PROVISION` | profil de provisionnement (`.mobileprovision`) pour l'install device |

```powershell
# Ad-hoc (local) — s'affiche « [ios-zig] signé (ad-hoc) : NKCode.app » en fin de build
$env:RCODESIGN="C:\apple-sdks\tools\rcodesign.exe"; $env:IOS_SIGN="adhoc"
jenga build --platform iOS --ios-backend=zig --target NKCode

# Device réel (compte Apple)
$env:IOS_SIGN="C:\certs\dev.p12"; $env:IOS_SIGN_PASS="****"
$env:IOS_PROVISION="C:\certs\NKCode.mobileprovision"
jenga build --platform iOS --ios-backend=zig --target NKCode
```

**Installation :**
- **macOS** : ad-hoc suffit en local ; distribution = Developer ID + **notarisation**
  (`rcodesign notary-submit`).
- **iOS** : `.p12` + provisioning (compte Apple) → install USB via `ideviceinstaller`,
  ou **AltStore/Sideloadly** (compte gratuit, resignature 7 jours).
- ⚠️ `rcodesign verify` affiche un **warning CMS connu** (bug documenté de l'outil) :
  ce n'est **pas** un échec de signature. Vérifier plutôt avec
  `rcodesign print-signature-info <app>/<exe>` (doit montrer `flags: ...ADHOC...`
  ou le certificat, `digest_type: sha256`).

## 7. Limites

- Il faut un **SDK iOS complet** (Xcode) — les headers-only ne linkent pas.
- La **version du SDK** = deployment target max (ex. SDK 12.2 → iOS ≤ 12.2 d'API).
- **Exécution/test** = matériel Apple (ou simulateur = Mac uniquement).
- `watchOS` (`arm64_32`) est *best-effort*.

---

## English (summary)

Jenga cross-compiles Apple targets **from Windows** using **Zig 0.13** (compiler)
and **`ld.lld -flavor darwin`** (Mach-O linker, shipped with the Android NDK).
Opt-in via `--macos-backend=zig` / `--ios-backend=zig`; the native Xcode builders
are untouched. **iOS/tvOS/watchOS require a COMPLETE Xcode SDK** (with
`usr/lib/libSystem.tbd` etc.) — headers-only SDKs cannot link. Run
`python Jenga/scripts/setup_apple_toolchain.py` to install Zig + SDKs + wrappers
and verify. Produces `.app`/`.ipa`; sign with `rcodesign` afterwards.
