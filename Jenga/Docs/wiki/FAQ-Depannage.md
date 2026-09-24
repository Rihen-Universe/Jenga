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

### `No suitable toolchain found for Windows x86_64`

Jenga n'a trouvé aucun compilateur qui réponde. Depuis la **2.8.3**, le message
liste chaque candidat cherché et pourquoi il a été écarté. Causes fréquentes :

- le `PATH` pointe sur `C:\msys64\ucrt64\x86_64-w64-mingw32\bin` (outils
  internes seulement) au lieu de **`C:\msys64\ucrt64\bin`** ;
- le terminal ou VS Code a été ouvert **avant** la modification des variables
  d'environnement : fermez-les tous et rouvrez-les ;
- dans le terminal MSYS2 tout marche mais pas ailleurs : c'est MSYS2 qui ajoute
  lui-même `ucrt64\bin` au `PATH`.

Vérifiez dans PowerShell : `where.exe clang gcc` doit afficher
`C:\msys64\ucrt64\bin\...`. Depuis la 2.8.3, Jenga fouille aussi
`C:\msys64\{ucrt64,clang64,mingw64}\bin` quand le `PATH` ne donne rien (autre
racine : variable `MSYS2_ROOT`).

### `ccache: unknown option -- g`

Jenga active ccache (ou sccache) tout seul s'il est dans le `PATH`. Avant la
**2.8.1**, il remplaçait le compilateur au lieu de se placer devant, et toute
compilation GCC/Clang échouait ainsi. Mettez Jenga à jour, ou désactivez le
cache :

```bash
export JENGA_DISABLE_CCACHE=1      # PowerShell : $env:JENGA_DISABLE_CCACHE = "1"
```

### Android : `dlopen failed: library "libc++_shared.so" not found`

L'application s'installe, se lance et revient au bureau sans un mot. Avant la
**2.8.2**, Jenga oubliait `libc++_shared.so` dans l'APK (toujours pour une seule
ABI, et pour plusieurs sans `cppdialect()`). Mettez Jenga à jour ; ou, sur une
version antérieure, liez la STL statiquement : `androidstl("c++_static")`.

### Android : `undefined symbol: eglGetDisplay` après la mise à jour

Depuis la **2.8.2**, Jenga ne lie plus EGL et GLES d'office : il ne garde que
`-llog` et `-landroid`, dont a besoin la colle NativeActivity qu'il ajoute
lui-même. Déclarez ce que votre code utilise :

```python
with filter("system:Android"):
    links(["EGL", "GLESv3"])
```

### `jenga deploy` : « Deploy failed: device … is 'unauthorized' »

Acceptez l'invite « Autoriser le débogage USB » sur le téléphone, puis relancez.
Depuis la **2.8.2**, `jenga deploy` nomme la cause de chaque échec (appareil
non autorisé ou hors ligne, signature incompatible, ABI absente, stockage
plein…) au lieu de « adb install failed. ».

### Une commande `prebuild` / `postbuild` échoue et arrête le build

Depuis la **2.8.2**, leur code de retour compte : un `prebuild` en échec arrête
le projet avant compilation, un `postbuild` en échec le marque en échec (et un
`postbuild` ne s'exécute plus après une compilation ratée). Avant, l'échec était
ignoré en silence. Si une commande peut échouer sans gravité, rendez-la
tolérante vous-même (`cmd || exit 0`).

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

### `No suitable toolchain found for Windows x86_64`

Jenga found no compiler that answers. Since **2.8.3**, the message lists every
candidate it looked for and why it was rejected. Common causes:

- `PATH` points to `C:\msys64\ucrt64\x86_64-w64-mingw32\bin` (internal tools
  only) instead of **`C:\msys64\ucrt64\bin`**;
- the terminal or VS Code was opened **before** the environment variables were
  changed: close them all and reopen;
- everything works in the MSYS2 terminal but not elsewhere: MSYS2 adds
  `ucrt64\bin` to `PATH` by itself.

Check in PowerShell: `where.exe clang gcc` must print `C:\msys64\ucrt64\bin\...`.
Since 2.8.3, Jenga also searches `C:\msys64\{ucrt64,clang64,mingw64}\bin` when
`PATH` gives nothing (other root: `MSYS2_ROOT` variable).

### `ccache: unknown option -- g`

Jenga enables ccache (or sccache) automatically when it is on the `PATH`.
Before **2.8.1** it replaced the compiler instead of prefixing it, so every
GCC/Clang compilation failed this way. Update Jenga, or disable the cache:

```bash
export JENGA_DISABLE_CCACHE=1      # PowerShell: $env:JENGA_DISABLE_CCACHE = "1"
```

### Android: `dlopen failed: library "libc++_shared.so" not found`

The app installs, starts and drops back to the home screen without a word.
Before **2.8.2**, Jenga left `libc++_shared.so` out of the APK (always for a
single ABI, and for several without `cppdialect()`). Update Jenga; or, on an
older version, link the STL statically: `androidstl("c++_static")`.

### Android: `undefined symbol: eglGetDisplay` after updating

Since **2.8.2**, Jenga no longer links EGL and GLES implicitly: only `-llog` and
`-landroid` remain, which the NativeActivity glue Jenga adds itself requires.
Declare what your code uses:

```python
with filter("system:Android"):
    links(["EGL", "GLESv3"])
```

### `jenga deploy`: "Deploy failed: device … is 'unauthorized'"

Accept the "Allow USB debugging" prompt on the phone, then retry. Since
**2.8.2**, `jenga deploy` names the cause of every failure (unauthorized or
offline device, incompatible signature, missing ABI, storage full…) instead of
"adb install failed.".

### A `prebuild` / `postbuild` command fails and stops the build

Since **2.8.2**, their exit code counts: a failing `prebuild` stops the project
before compiling, a failing `postbuild` marks it failed (and a `postbuild` no
longer runs after a failed compilation). Before, the failure was silently
ignored. If a command may fail harmlessly, make it tolerant yourself
(`cmd || exit 0`).

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
