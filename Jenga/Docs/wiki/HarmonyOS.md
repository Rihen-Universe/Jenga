# HarmonyOS / OpenHarmony

**Langues / Languages :** [Français](#français) · [English](#english)

---

## Français

Jenga compile, package et signe des applications **HarmonyOS** (HAP) à partir de
sources C/C++ natives, avec génération automatique de la structure de projet
ArkTS attendue par `hvigor`.

> **Statut :** ✅ Intégré — builder complet, packaging HAP, permissions réseau.
> Testable depuis Windows, Linux et macOS (le SDK OpenHarmony est cross-platform).

---

## 1. Prérequis

| Outil | Détail | Variable d'environnement |
|-------|--------|--------------------------|
| SDK OpenHarmony / HarmonyOS | Contient le NDK natif (LLVM) + `hvigorw` | `OHOS_SDK`, `HARMONY_OS_SDK` ou `HARMONY_SDK` |
| DevEco Studio (optionnel) | Fournit le template officiel + `hvigor` | détecté automatiquement |
| Node.js | Requis par `hvigorw` pour assembler le `.hap` | dans le PATH |

```bash
# Windows
set HARMONY_OS_SDK=C:\Users\%USERNAME%\AppData\Local\OpenHarmony\Sdk

# Linux / macOS
export OHOS_SDK=$HOME/OpenHarmony/Sdk
```

Le builder résout automatiquement le NDK dans
`<sdk>/default/openharmony/native/` et détecte `clang`, `llvm-ar`, `llvm-strip`.

---

## 2. Plateforme et architectures

| TargetOS | Architectures | Triples cibles |
|----------|---------------|----------------|
| `TargetOS.HARMONYOS` | `ARM` (armv7a), `ARM64` (aarch64), `X86_64` | `aarch64-linux-ohos`, `arm-linux-ohos`, `x86_64-linux-ohos` |

---

## 3. Exemple minimal

```python
# harmony_app.jenga
from Jenga import *
from Jenga.GlobalToolchains import RegisterJengaGlobalToolchains

with workspace("HarmonyDemo"):
    RegisterJengaGlobalToolchains()
    configurations(["Debug", "Release"])
    targetoses([TargetOS.HARMONYOS])
    targetarchs([TargetArch.ARM64])

    harmonysdk(os.getenv("HARMONY_OS_SDK", ""))   # workspace-level

    with project("MyApp"):
        windowedapp()                  # -> génère un .hap (sinon .so/.a/ELF)
        language("C++")
        cppdialect("C++17")
        files(["src/**.cpp"])

        # Métadonnées HAP
        harmonybundlename("com.monentreprise.myapp")
        harmonyminsdk(12)              # API level minimum
        harmonyversioncode(1000000)
        harmonyversionname("1.0.0")

        # Réseau (LAN / Internet) — injecte les permissions OHOS
        networkenabled(True)
```

```bash
jenga build harmony_app.jenga --platform HarmonyOS-arm64 --config Release
jenga package --platform harmonyos --type hap --project MyApp --output ./dist
```

---

## 4. Fonctions DSL HarmonyOS

| Fonction DSL | Description |
|--------------|-------------|
| `harmonysdk("<path>")` | Chemin du SDK (workspace-level) |
| `harmonyminsdk(12)` | API level minimum (compatibleSdkVersion) |
| `harmonytargetapi(12)` | API level cible |
| `harmonybundlename("com.x.y")` | Bundle name (identité de l'app) |
| `harmonyversioncode(1000000)` | Code de version (entier) |
| `harmonyversionname("1.0.0")` | Nom de version (semver) |
| `harmonypermissions([...])` | Permissions `ohos.permission.*` ✅ **nouveau** |
| `harmonyets(["ets/"])` | Répertoires de sources ArkTS/ETS ✅ **nouveau** |
| `harmonyresources([...])` | Dossiers de ressources (string.json, color.json, media…) |
| `harmonyassets([...])` | Fichiers bruts → `resources/rawfile/` |
| `harmonyappicon("icon.png")` | Icône applicative (sinon Jenga en génère une unie) |
| `harmonyabis(["arm64-v8a", "x86_64"])` | ABIs embarquées dans un HAP unique ✅ **nouveau** |
| `harmonyorientation("landscape")` | Orientation de l'écran ✅ **nouveau** |
| `harmonysign(True)` | Active la signature du HAP |
| `harmonycertfile`, `harmonyprofile`, `harmonykeystore`, `harmonykeyalias`, `harmonykeypwd` | Paramètres de signature |

---

## 5. Permissions réseau (LAN / Internet)

Sur HarmonyOS, **sans `ohos.permission.INTERNET` une app ne peut pas ouvrir de
socket** — les connexions LAN/Internet échouent silencieusement au runtime.

Jenga injecte automatiquement les permissions réseau dans
`entry/src/main/module.json5 > requestPermissions` dès que vous activez le
réseau :

```python
with project("MyApp"):
    windowedapp()
    networkenabled(True)     # injecte INTERNET + GET_NETWORK_INFO + GET_WIFI_INFO
```

Génère dans `module.json5` :

```json5
{
  "module": {
    "name": "entry",
    "type": "entry",
    "requestPermissions": [
      { "name": "ohos.permission.INTERNET" },
      { "name": "ohos.permission.GET_NETWORK_INFO" },
      { "name": "ohos.permission.GET_WIFI_INFO" }
    ],
    ...
  }
}
```

### Permissions supplémentaires

```python
with project("MyApp"):
    windowedapp()
    networkenabled(True)
    harmonypermissions([
        "ohos.permission.CAMERA",
        "ohos.permission.MICROPHONE",
    ])
    # -> fusionne réseau auto + ces permissions, sans doublon
```

> 🌐 Le DSL réseau (`networkenabled`, `firewallrule`, …) est **multi-plateforme** :
> la même déclaration produit les règles `netsh` (Windows), `socketfilterfw`
> (macOS), `ufw/iptables` (Linux DEB), les `uses-permission` (Android) et les
> `requestPermissions` (HarmonyOS). Voir
> [Packaging, Déploiement, Publication](Packaging-Deploiement-Publication.md).

---

## 6. Ce que génère Jenga

> **Jenga génère le projet HAP en entier**, sans dépendre de DevEco Studio. La
> structure était auparavant copiée depuis le template de l'IDE quand il était
> présent, ce qui importait ses artefacts — le paquet installé déclarait par
> exemple un `EntryFormAbility` que le projet ne demandait nulle part.
>
> Le template reste un repli, réactivable par `NKJENGA_HARMONY_TEMPLATE=1`, si
> une version de hvigor introduit un format que Jenga ne produit pas encore.
>
> Conséquence pratique : **une machine avec les seuls Command Line Tools**
> (sans DevEco Studio) construit un HAP complet. Les icônes manquantes sont
> générées (PNG uni 192×192, sans dépendance à Pillow).

```
Build/Bin/Release-HarmonyOS/MyApp/
├── libMyApp.so                       ← bibliothèque native compilée
└── harmony-build/                    ← projet hvigor généré (ne touche pas vos sources)
    ├── build-profile.json5
    ├── oh-package.json5
    ├── hvigorfile.ts
    └── entry/
        ├── build-profile.json5
        ├── hvigorfile.ts
        └── src/main/
            ├── module.json5          ← avec requestPermissions
            ├── ets/entryability/EntryAbility.ets
            ├── libs/arm64-v8a/libMyApp.so
            └── resources/...
```

Le `.hap` final est assemblé via `hvigorw assembleHap` et copié dans `./dist`.

---

## 6bis. Orientation de l'écran

```python
harmonyorientation("landscape")   # verrouillé en paysage
```

| Valeur | Effet |
|--------|-------|
| `portrait` | verrouillé en portrait |
| `landscape` | verrouillé en paysage |
| `auto_rotation` | suit le capteur, les quatre sens |
| `auto_rotation_landscape` | suit le capteur, paysage uniquement |
| `auto_rotation_portrait` | suit le capteur, portrait uniquement |
| `follow_recent` | reprend l'orientation précédente |
| `unspecified` | laisse le système décider |

**Sans appel, aucune clé n'est écrite** et le système applique son défaut — du
portrait sur téléphone. Une démo 3D ou un jeu veut généralement `landscape`.

C'est l'équivalent HarmonyOS d'`androidallowrotation()` ; les deux coexistent
parce que les deux systèmes n'offrent pas les mêmes modes.

---

## 6ter. HAP multi-ABI — indispensable pour les émulateurs

```python
harmonyabis(["arm64-v8a", "x86_64"])
```

Les **émulateurs HarmonyOS-NEXT sur PC tournent en x86_64**
(`const.product.cpu.abilist`), alors que les appareils réels sont en arm64. Un
HAP mono-ABI ne peut donc pas servir aux deux, et l'échec côté émulateur est
particulièrement muet :

```
error: failed to install bundle. code:9568347
error: install parse native so failed.
```

Ce message ne mentionne **nulle part** l'architecture. Déclarer les deux ABIs
produit un HAP unique qui s'installe partout.

> **Piège vérifié** — `libc++_shared.so` doit être **dans le HAP**. Comme sur
> Android, le système ne fournit pas la STL du NDK : aucune `libc++_shared.so`
> dans `/system/lib64`. Jenga l'embarque désormais automatiquement, par ABI.
> Sans elle, `dlopen` échoue **en silence** au chargement du XComponent :
> l'ArkTS reçoit `undefined` et plante sur
> `TypeError: Cannot read property <export> of undefined` — un symptôme qui ne
> désigne jamais sa cause, d'autant que l'**installation, elle, réussit**.

---

## 7. Signature du HAP

```python
with project("MyApp"):
    windowedapp()
    harmonysign(True)
    harmonycertfile("cert/app.cer")
    harmonyprofile("cert/app.p7b")
    harmonykeystore("cert/app.p12")
    harmonykeyalias("debugKey")
    harmonykeypwd("xxxxxx")
```

---

## 8. Limitations connues

| Limitation | Détail |
|------------|--------|
| Backend natif fenêtré | L'exemple `27_nk_window` a un squelette HarmonyOS ; le backend natif réel reste à compléter selon votre moteur de rendu. |
| `hvigorw` requis | L'assemblage du `.hap` nécessite Node.js + `hvigor` (fournis par DevEco Studio ou le SDK). |
| Régénération `module.json5` | Le fichier n'est généré que s'il n'existe pas (préserve vos éditions). Supprimez `harmony-build/` pour forcer la régénération avec de nouvelles permissions. |

---

## 9. Dépannage

- **`HarmonyOS SDK not found`** → définir `HARMONY_OS_SDK` / `OHOS_SDK`.
- **`hvigorw not found`** → installer DevEco Studio ou ajouter le SDK au PATH.
- **App n'accède pas au réseau** → vérifier `networkenabled(True)` et regarder
  `module.json5 > requestPermissions` dans `harmony-build/entry/src/main/`.
- **Permissions non mises à jour après changement** → supprimer le dossier
  `harmony-build/` puis relancer le build.

---

## English

Jenga builds, packages and signs **HarmonyOS** apps (HAP) from native C/C++
sources, automatically generating the ArkTS project structure expected by
`hvigor`.

> **Status:** ✅ Integrated — full builder, HAP packaging, network permissions.
> Buildable from Windows, Linux and macOS (the OpenHarmony SDK is cross-platform).

### 1. Requirements

| Tool | Detail | Environment variable |
|------|--------|----------------------|
| OpenHarmony/HarmonyOS SDK | Native NDK (LLVM) + `hvigorw` | `OHOS_SDK`, `HARMONY_OS_SDK` or `HARMONY_SDK` |
| DevEco Studio (optional) | Fallback template only — **not used by default** | `NKJENGA_HARMONY_TEMPLATE=1` |
| Node.js | Required by `hvigorw` to assemble the `.hap` | on PATH |

```bash
# Windows
set HARMONY_OS_SDK=C:\Users\%USERNAME%\AppData\Local\OpenHarmony\Sdk
# Linux / macOS
export OHOS_SDK=$HOME/OpenHarmony/Sdk
```

### 2. Platform and architectures

`TargetOS.HARMONYOS` with `ARM` (armv7a), `ARM64` (aarch64), `X86_64` →
triples `aarch64-linux-ohos`, `arm-linux-ohos`, `x86_64-linux-ohos`.

### 3. Minimal example

```python
from Jenga import *
from Jenga.GlobalToolchains import RegisterJengaGlobalToolchains

with workspace("HarmonyDemo"):
    RegisterJengaGlobalToolchains()
    configurations(["Debug", "Release"])
    targetoses([TargetOS.HARMONYOS])
    targetarchs([TargetArch.ARM64])
    harmonysdk(os.getenv("HARMONY_OS_SDK", ""))

    with project("MyApp"):
        windowedapp()                  # -> produces a .hap (else .so/.a/ELF)
        language("C++"); cppdialect("C++17")
        files(["src/**.cpp"])
        harmonybundlename("com.company.myapp")
        harmonyminsdk(12)
        harmonyversioncode(1000000)
        harmonyversionname("1.0.0")
        networkenabled(True)           # injects ohos network permissions
```

```bash
jenga build harmony_app.jenga --platform HarmonyOS-arm64 --config Release
jenga package --platform harmonyos --type hap --project MyApp --output ./dist
```

### 4. DSL functions

`harmonysdk` · `harmonyminsdk` · `harmonytargetapi` · `harmonybundlename` ·
`harmonyversioncode` · `harmonyversionname` · `harmonypermissions` (✅ new) ·
`harmonyets` (✅ new) · `harmonyresources` · `harmonyassets` · `harmonyappicon` ·
`harmonyabis` (✅ new) · `harmonyorientation` (✅ new) ·
`harmonysign` · `harmonycertfile` · `harmonyprofile` · `harmonykeystore` ·
`harmonykeyalias` · `harmonykeypwd`.

### 5. Network permissions (LAN / Internet)

Without `ohos.permission.INTERNET` a HarmonyOS app cannot open a socket — LAN/
Internet calls fail silently. Jenga auto-injects the permissions into
`entry/src/main/module.json5 > requestPermissions` as soon as you enable
networking:

```python
with project("MyApp"):
    windowedapp()
    networkenabled(True)     # INTERNET + GET_NETWORK_INFO + GET_WIFI_INFO

# extra permissions:
harmonypermissions(["ohos.permission.CAMERA", "ohos.permission.MICROPHONE"])
```

The cross-platform network DSL is shared — see
[Networking & Firewall](Reseau-et-Pare-feu.md).

### 6. What Jenga generates

> **Jenga generates the whole HAP project**, with no dependency on DevEco
> Studio. The structure used to be copied from the IDE's template when present,
> which dragged in its artefacts — the installed bundle declared an
> `EntryFormAbility` the project never asked for.
>
> The template remains a fallback, re-enabled with
> `NKJENGA_HARMONY_TEMPLATE=1`, should a hvigor release introduce a format Jenga
> does not produce yet.
>
> In practice: **a machine with only the Command Line Tools** (no DevEco Studio)
> builds a complete HAP. Missing icons are generated (flat 192×192 PNG, with no
> dependency on Pillow).

```
Build/Bin/Release-HarmonyOS/MyApp/
├── libMyApp.so
└── harmony-build/                    # generated hvigor project (sources untouched)
    └── entry/src/main/
        ├── module.json5              # with requestPermissions
        ├── ets/entryability/EntryAbility.ets
        └── libs/arm64-v8a/libMyApp.so
```

### 6bis. Screen orientation

```python
harmonyorientation("landscape")   # locked to landscape
```

| Value | Effect |
|-------|--------|
| `portrait` | locked to portrait |
| `landscape` | locked to landscape |
| `auto_rotation` | follows the sensor, all four ways |
| `auto_rotation_landscape` | follows the sensor, landscape only |
| `auto_rotation_portrait` | follows the sensor, portrait only |
| `follow_recent` | reuses the previous orientation |
| `unspecified` | lets the system decide |

**Without a call, no key is written** and the system applies its own default —
portrait on phones. A 3D demo or a game usually wants `landscape`.

This is the HarmonyOS counterpart of `androidallowrotation()`; both exist
because the two systems do not offer the same modes.

---

### 6ter. Multi-ABI HAP — required for emulators

```python
harmonyabis(["arm64-v8a", "x86_64"])
```

**HarmonyOS-NEXT emulators on PC run x86_64** (`const.product.cpu.abilist`),
while real devices are arm64. A single-ABI HAP cannot serve both, and the
emulator-side failure is remarkably silent:

```
error: failed to install bundle. code:9568347
error: install parse native so failed.
```

That message never mentions the architecture. Declaring both ABIs produces one
HAP that installs everywhere.

> **Verified pitfall** — `libc++_shared.so` must be **inside the HAP**. As on
> Android, the system does not ship the NDK's STL: there is no
> `libc++_shared.so` under `/system/lib64`. Jenga now embeds it automatically,
> per ABI. Without it `dlopen` fails **silently** when the XComponent loads:
> ArkTS receives `undefined` and throws
> `TypeError: Cannot read property <export> of undefined` — a symptom that
> never points at its cause, all the more so since **installation succeeds**.

---

### 7. Signing the HAP

```python
with project("MyApp"):
    windowedapp()
    harmonysign(True)
    harmonycertfile("cert/app.cer"); harmonyprofile("cert/app.p7b")
    harmonykeystore("cert/app.p12"); harmonykeyalias("debugKey")
    harmonykeypwd("xxxxxx")
```

### 8. Known limitations

- Windowed native backend: example `27_nk_window` has a HarmonyOS skeleton; the
  real native backend depends on your rendering engine.
- `hvigorw` (Node.js + hvigor) is required to assemble the `.hap`.
- `module.json5` is only generated if absent (preserves your edits) — delete
  `harmony-build/` to force regeneration with new permissions.

### 9. Troubleshooting

- `HarmonyOS SDK not found` → set `HARMONY_OS_SDK` / `OHOS_SDK`.
- `hvigorw not found` → install DevEco Studio or add the SDK to PATH.
- App has no network access → check `networkenabled(True)` and inspect
  `module.json5 > requestPermissions` under `harmony-build/entry/src/main/`.
- Permissions not updated → delete `harmony-build/` and rebuild.
