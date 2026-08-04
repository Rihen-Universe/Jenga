# Installation

**Langues / Languages :** [Français](#français) · [English](#english)

---

## Français

### Prérequis

- **Python 3.8 ou supérieur** (aucune autre dépendance obligatoire).
- Un **compilateur** adapté à votre cible :
  - Windows : MSVC, clang-cl, clang-mingw (MSYS2/UCRT64), MinGW (gcc), Zig
  - Linux : GCC ou Clang
  - macOS / iOS : Xcode + Apple Clang
  - Android : NDK r27c + SDK + JDK 17
  - Web : Emscripten (emsdk)
  - HarmonyOS : SDK OpenHarmony

Dépendances Python (installées automatiquement) : `watchdog` (mode `watch`),
`requests` (publication). Extras optionnels : `markdown`, `pygments` (pour
`jenga docs`).

### Installation via pip (recommandé)

```bash
pip install jenga
```

### Installation depuis les sources (développement)

```bash
git clone https://github.com/Rihen-Universe/Jenga.git
cd Jenga
pip install -e .
```

Le point d'entrée `console_scripts` expose la commande `jenga`
(défini par `jenga = Jenga.Jenga:main`).

### Vérifier l'installation

```bash
jenga --version
# ou, sans installation pip :
python -m Jenga --version
python Jenga/Jenga.py --version
```

### Mise à jour

```bash
pip install --upgrade jenga
```

### Erreurs courantes

| Erreur | Cause | Solution |
|--------|-------|----------|
| `No .jenga workspace file found` | Aucun workspace dans le dossier courant | `jenga workspace MonWorkspace` |
| `keytool not found` (Android) | JDK absent du PATH | Installer le JDK 17, vérifier `keytool -help` |
| `command not found: jenga` | Le dossier Scripts de pip n'est pas dans le PATH | Ajouter `.../Scripts` (Windows) ou `~/.local/bin` (Linux) au PATH |
| `Toolchain not found` | SDK/compilateur non détecté | Voir [Toolchains et Sysroots](Toolchains-et-Sysroots.md) |

---

## English

### Requirements

- **Python 3.8 or newer** (no other mandatory dependency).
- A **compiler** matching your target:
  - Windows: MSVC, clang-cl, clang-mingw (MSYS2/UCRT64), MinGW (gcc), Zig
  - Linux: GCC or Clang
  - macOS / iOS: Xcode + Apple Clang
  - Android: NDK r27c + SDK + JDK 17
  - Web: Emscripten (emsdk)
  - HarmonyOS: OpenHarmony SDK

Python dependencies (installed automatically): `watchdog` (`watch` mode),
`requests` (publishing). Optional extras: `markdown`, `pygments` (for
`jenga docs`).

### Install via pip (recommended)

```bash
pip install jenga
```

### Install from source (development)

```bash
git clone https://github.com/Rihen-Universe/Jenga.git
cd Jenga
pip install -e .
```

The `console_scripts` entry point exposes the `jenga` command
(defined as `jenga = Jenga.Jenga:main`).

### Verify the installation

```bash
jenga --version
# or, without a pip install:
python -m Jenga --version
python Jenga/Jenga.py --version
```

### Upgrade

```bash
pip install --upgrade jenga
```

### Common errors

| Error | Cause | Fix |
|-------|-------|-----|
| `No .jenga workspace file found` | No workspace in the current folder | `jenga workspace MyWorkspace` |
| `keytool not found` (Android) | JDK missing from PATH | Install JDK 17, check `keytool -help` |
| `command not found: jenga` | pip Scripts dir not on PATH | Add `.../Scripts` (Windows) or `~/.local/bin` (Linux) to PATH |
| `Toolchain not found` | SDK/compiler not detected | See [Toolchains & Sysroots](Toolchains-et-Sysroots.md) |
