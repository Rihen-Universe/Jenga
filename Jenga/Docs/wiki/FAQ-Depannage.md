# FAQ / Dépannage — FAQ / Troubleshooting

**Langues / Languages :** [Français](#français) · [English](#english)

---

## Français

### `No .jenga workspace file found`

Vous exécutez une commande dans un dossier sans fichier workspace.

```bash
jenga workspace MonWorkspace
# ou préciser le fichier :
jenga build --jenga-file ./MonWorkspace.jenga
```

### `Project 'X' not found`

Le nom du projet n'existe pas dans le workspace chargé. Vérifiez le nom exact
dans le `.jenga` et le bon fichier workspace.

### `Toolchain 'X' not defined`

Vous appelez `usetoolchain("X")` sans l'avoir déclaré.

- Déclarez `with toolchain("X", "..."):` dans le workspace, **ou**
- ajoutez `RegisterJengaGlobalToolchains()` pour la détection auto, **ou**
- enregistrez une toolchain globale : `jenga install toolchain install ...`.

### Build lent ou incohérent

```bash
jenga clean --all
jenga build --no-cache --no-daemon --verbose
```

### `ccache: unknown option -- g`

Jenga active ccache (ou sccache) tout seul s'il est dans le `PATH`. Avant la
**2.8.1**, il remplaçait le compilateur au lieu de se placer devant, et toute
compilation GCC/Clang échouait ainsi. Mettez Jenga à jour, ou désactivez le
cache :

```bash
export JENGA_DISABLE_CCACHE=1      # PowerShell : $env:JENGA_DISABLE_CCACHE = "1"
```

### Android SDK / NDK introuvable

Vérifiez `ANDROID_SDK_ROOT` / `ANDROID_NDK_ROOT`, ou en DSL :

```python
androidsdkpath("..."); androidndkpath("...")
```

### Tests qui ne se lancent pas

Vérifiez la présence de `with unitest() as u: u.Precompiled()`, d'un bloc
`with test():` imbriqué dans un `project()`, et l'existence des fichiers
`testfiles([...])`.

### Débogage : « no debugger found »

`jenga gdb` nécessite GDB (ou LLDB). Installez-le :
- Windows (MSYS2/UCRT64) : `pacman -S mingw-w64-ucrt-x86_64-gdb`
- Linux : `sudo apt install gdb`
- macOS : `xcode-select --install` (LLDB inclus).

### L'app ne reçoit pas de connexions réseau (LAN)

Ajoutez `networkenabled(True)` (ou `firewallrule(...)`) au projet et
re-packagez : la règle de pare-feu est créée à l'installation. Voir
[Réseau et Pare-feu](Reseau-et-Pare-feu.md).

### Génération docs vide

Vérifiez la présence de commentaires Doxygen / `///`, des sources dans `src/` et
`include/`, puis `jenga docs extract --verbose`.

### `command not found: jenga`

Le dossier `Scripts` (Windows) ou `~/.local/bin` (Linux) de pip n'est pas dans le
PATH. Ajoutez-le, ou lancez `python -m Jenga ...`.

---

## English

### `No .jenga workspace file found`

You ran a command in a folder without a workspace file.

```bash
jenga workspace MyWorkspace
# or point to the file:
jenga build --jenga-file ./MyWorkspace.jenga
```

### `Project 'X' not found`

The project name doesn't exist in the loaded workspace. Check the exact name in
the `.jenga` and the right workspace file.

### `Toolchain 'X' not defined`

You call `usetoolchain("X")` without declaring it.

- Declare `with toolchain("X", "..."):` in the workspace, **or**
- add `RegisterJengaGlobalToolchains()` for auto-detection, **or**
- register a global toolchain: `jenga install toolchain install ...`.

### Slow or inconsistent build

```bash
jenga clean --all
jenga build --no-cache --no-daemon --verbose
```

### `ccache: unknown option -- g`

Jenga enables ccache (or sccache) automatically when it is on the `PATH`.
Before **2.8.1** it replaced the compiler instead of prefixing it, so every
GCC/Clang compilation failed this way. Update Jenga, or disable the cache:

```bash
export JENGA_DISABLE_CCACHE=1      # PowerShell: $env:JENGA_DISABLE_CCACHE = "1"
```

### Android SDK / NDK not found

Check `ANDROID_SDK_ROOT` / `ANDROID_NDK_ROOT`, or in DSL:

```python
androidsdkpath("..."); androidndkpath("...")
```

### Tests don't run

Ensure `with unitest() as u: u.Precompiled()` is present, a `with test():`
block is nested inside a `project()`, and the `testfiles([...])` exist.

### Debugging: "no debugger found"

`jenga gdb` needs GDB (or LLDB). Install it:
- Windows (MSYS2/UCRT64): `pacman -S mingw-w64-ucrt-x86_64-gdb`
- Linux: `sudo apt install gdb`
- macOS: `xcode-select --install` (LLDB included).

### The app doesn't receive network (LAN) connections

Add `networkenabled(True)` (or `firewallrule(...)`) to the project and re-package:
the firewall rule is created at install time. See
[Networking & Firewall](Reseau-et-Pare-feu.md).

### Empty documentation output

Ensure Doxygen `///` comments exist, sources are under `src/` and `include/`,
then run `jenga docs extract --verbose`.

### `command not found: jenga`

pip's `Scripts` dir (Windows) or `~/.local/bin` (Linux) isn't on PATH. Add it, or
run `python -m Jenga ...`.
