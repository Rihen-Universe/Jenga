<!-- AUTEUR : TEUGUIA TADJUIDJE Rodolf Séderis — Rihen -->
# Commandes CLI / CLI Commands

**Langues / Languages :** [Français](#français) · [English](#english)

---

## Français

Jenga expose **24 commandes**. Syntaxe générale : `jenga <commande> [options]`.
Beaucoup de commandes acceptent un **alias court** (ex. `b` = `build`).

### Flags globaux

- `--version` / `-v` — affiche la version
- `--help` / `-h` — aide générale

### Flags communs (cycle de build)

- `--config CONFIG` — configuration (`Debug`, `Release`…) ; défaut `Debug`
- `--platform PLATFORM` — cible (`Windows`, `Linux-x86_64`, `Android-arm64`…),
  ou `jengaall` pour toutes les plateformes déclarées
- `--target` / `--project` — projet ciblé
- `--no-cache` — ignore le cache incrémental
- `--no-daemon` — n'utilise pas le daemon
- `--verbose` / `-v` — sortie détaillée
- `--jenga-file PATH` — chemin du workspace (sinon auto-détecté)

### Cycle de développement

| Commande | Alias | Rôle | Options clés |
|----------|-------|------|--------------|
| `build` | `b` | Compile le workspace ou un projet | `--config --platform --target --jobs/-j --keep-going/-k --tests --force-tests --no-cache --no-daemon`, options Android (`--android-build-system`, `--android-abis`, `--use-android-mk`, `--android-ndk-mk-mode`) |
| `run` | `r` | Exécute un projet (build si besoin) | `project --args --build --force --target/--device` |
| `gdb` | `g` (`debug`) | Débogue un projet avec GDB (ou LLDB) | `project --config --break/-b --run --batch --args --build --debugger (auto\|gdb\|lldb)` |
| `test` | `t` | Compile et lance les suites de tests | `--project --no-build --force` |
| `clean` | `c` | Supprime objets/binaires/cache | `--all --config --platform --project` |
| `rebuild` | — | `clean` puis `build` | `--clean-all` + options build |
| `watch` | `w` | Rebuild automatique sur changement | `--polling --no-daemon` |
| `info` | `i` | Workspace, projets, toolchains, daemon | `--verbose` |

```bash
jenga build --config Release --platform Linux-x86_64 --target CoreLib
jenga run MonApp --args --level hard --fullscreen
jenga test --project Core_Tests --config Debug
jenga test --project Core_Tests --force        # malgré dutc/dute, cette fois-ci (Tests-Unitest §5)
jenga build --target Core_Tests --force-tests  # construction seule, malgré dutc
jenga build -j8                     # 8 jobs parallèles
jenga build --platform jengaall     # toutes les plateformes déclarées
jenga build --keep-going            # construit tout ce qui peut l'être
jenga build --tests                 # inclut aussi les cibles de test
```

#### `--keep-going` / `-k` — compter au lieu de s'arrêter

Par défaut, le build **s'arrête** à la première cible en échec. Sur un workspace
de plusieurs centaines de cibles, on ne découvre alors qu'**un** bloqueur à la
fois : un correctif, un commit, on recommence — et on ignore combien de cibles
sont réellement cassées.

`--keep-going` construit tout ce qui peut l'être et distingue **quatre états** :

| état | signification |
|---|---|
| **réussie** | construite |
| **échouée** | cassée — c'est ici qu'est le travail |
| **sautée** | *non tentée* : une de ses dépendances a échoué |
| **non atteinte** | le build s'est arrêté avant (mode par défaut uniquement) |

La catégorie **sautée** est celle qui fait la valeur du mode : une cible bloquée
n'est **pas tentée**, parce que la tenter produit une erreur *dérivée* — un
`no such file or directory` sur une archive absente — qui ressemble à un second
défaut et fait réparer deux fois le même.

```
Projects Built:  3/5
Failed:          1
Skipped:         1  (dépendance échouée)

Échecs (1) — à corriger :
  ✗ LibBad
Sautées (1) — bloquées par une dépendance, non tentées :
  ⊘ en attente de LibBad : AppDep
```

> **Depuis la v2.3.0**, `--verbose` ne poursuit **plus** après un échec. C'était
> un `--keep-going` accidentel, non documenté et à la mauvaise sémantique : il
> *tentait* les cibles bloquées. Un drapeau de verbosité ne décide pas de la
> politique d'échec.

#### `--tests` — les cibles de test sont des **racines**

**Une cible de test est une RACINE, jamais une dépendance.** Rien ne peut en
dépendre — `dependson()` vers une cible de test lève une erreur nommant l'arête
fautive. Elles sont donc **exclues du build par défaut** : sur un workspace réel
de 272 cibles, 66 étaient des tests, soit **24 % de travail que personne n'avait
demandé** quand on voulait simplement construire son application.

```bash
jenga build                      # les cibles de test sont ignorées
jenga build --tests              # elles sont incluses
jenga build --target Core_Tests  # nommée explicitement : construite dans tous les cas
jenga test --project Core_Tests  # Core, ses tests, leur fermeture — rien d'autre
```

Le dernier point compte : `jenga test` ne construit **pas** les tests des
dépendances de la cible, seulement les siens.

#### Débogage avec `gdb`

`jenga gdb` (re)compile en `Debug` si besoin, localise le binaire et lance GDB
(ou LLDB en l'absence de GDB). Détection automatique du debugger.

```bash
jenga gdb                              # débogue le startProject en Debug
jenga gdb MonApp --break main          # breakpoint sur main (répétable avec -b)
jenga gdb MonApp -b fichier.cpp:42 --run   # breakpoint + démarrage immédiat
jenga gdb MonApp --args --level hard   # passe des args au programme débogué
jenga gdb MonApp --debugger lldb       # force LLDB
jenga gdb MonApp --batch               # exécute + backtrace + quitte (CI)
```

### Création & édition

| Commande | Alias | Rôle | Options clés |
|----------|-------|------|--------------|
| `workspace` | `init` | Crée un workspace | `name --path --configs --oses --archs --interactive/-i` |
| `project` | `create` | Crée un projet ou un élément de code | `name --kind --lang --location --element --name --template -i` |
| `file` | `add` | Ajoute sources/includes/libs/defines | `project --src --inc --link --def --type -i` |

```bash
jenga workspace MonJeu --interactive
jenga project Moteur --kind static --lang C++
jenga project Outil --location apps          # -> apps/Outil/
jenga project --element class --name Player --project Moteur
jenga file MonApp --src "src/**.cpp" --inc include --link pthread
```

`--kind` : `console`, `windowed`, `static`, `shared`, `test`.
`--element` : `class`, `struct`, `enum`, `union`, `interface`, `function`,
`source`, `header`, `custom`.

> **Placement des projets** : `jenga project Foo` crée le projet dans un dossier
> **portant son nom** sous le workspace (`<workspace>/Foo/`). Avec
> `--location apps`, le projet est placé dans `<workspace>/apps/Foo/`. Le DSL
> généré renseigne `location("Foo")` (ou `location("apps/Foo")`).

### Génération IDE & documentation

| Commande | Alias | Rôle | Options clés |
|----------|-------|------|--------------|
| `gen` | — | Génère fichiers projet IDE | `--cmake --makefile --mk --android-mk --vs2022 --xcode --all --output/-o` |
| `docs` | `d` | Génère la doc (Doxygen → MD/HTML/PDF) | selon projet |
| `ide-setup` | `ide` | Configure l'éditeur pour `.jenga` | `--editor (auto\|vscode\|lsp\|all) --force --info` |

```bash
jenga gen --cmake --vs2022 --output generated
jenga ide-setup --editor vscode
```

### Packaging, déploiement, signature

| Commande | Rôle | Options clés |
|----------|------|--------------|
| `package` | Crée un package distribuable | `--platform (requis) --type --config --output/-o --project --ios-builder` |
| `deploy` | Déploie sur un appareil | `--platform (requis) --target/--device --apk --hap --list-devices --uninstall --run` |
| `sign` | Signe un APK/IPA | `--apk --ipa --keystore --alias --storepass --keypass --project` |
| `keygen` | Génère une keystore | `--alias --validity --output/-o -i --harmony` |
| `publish` | Publie sur un registre | `--registry (requis) --package --version --api-key --repo --dry-run` |

```bash
jenga package --platform windows --type msi --project MonApp -o ./dist
jenga package --platform android --type apk --project MonApp
jenga deploy --platform android --target emulator-5554 --run
jenga keygen --interactive
jenga sign --apk app.apk --keystore my.jks --alias key --storepass xxx --keypass xxx
```

> Types par plateforme : Android `apk`/`aab`, iOS `ipa`, Windows `msi`/`exe`/`zip`,
> Linux `deb`/`rpm`/`appimage`/`snap`, macOS `pkg`/`dmg`, Web `zip`, HarmonyOS `hap`.

### Outillage & analyse

| Commande | Rôle | Options clés |
|----------|------|--------------|
| `bench` | Lance des benchmarks | `--project --iterations --output/-o` |
| `profile` | Profilage CPU/mémoire | `--platform (requis) --tool --duration --output/-o` |
| `install` | Dépendances / toolchains globales | sous-commandes `toolchain list\|detect\|install` |
| `config` | Configuration globale Jenga | `init\|show\|set\|get`, `toolchain …`, `sysroot …` |
| `examples` | Liste/copie les exemples | sous-commandes `list\|copy` |
| `help` | Aide générale ou d'une commande | `command` |

```bash
jenga install toolchain list
jenga install toolchain install android-ndk --path /path/to/ndk
jenga config set max_parallel_jobs 12
jenga bench --project BenchApp --iterations 20
jenga help build
```

### Liste des alias

`b`=build · `r`=run · `t`=test · `c`=clean · `w`=watch · `i`=info · `e`=examples ·
`d`=docs · `k`=keygen · `s`=sign · `h`=help · `init`=workspace · `create`=project ·
`add`=file · `ide`=ide-setup.

---

## English

Jenga exposes **24 commands**. General syntax: `jenga <command> [options]`.
Many commands accept a **short alias** (e.g. `b` = `build`).

### Global flags

- `--version` / `-v` — print version
- `--help` / `-h` — general help

### Common flags (build cycle)

- `--config CONFIG` — configuration (`Debug`, `Release`…); default `Debug`
- `--platform PLATFORM` — target (`Windows`, `Linux-x86_64`, `Android-arm64`…),
  or `jengaall` for every declared platform
- `--target` / `--project` — targeted project
- `--no-cache` — ignore the incremental cache
- `--no-daemon` — do not use the daemon
- `--verbose` / `-v` — verbose output
- `--jenga-file PATH` — workspace path (otherwise auto-detected)

### Development cycle

| Command | Alias | Purpose | Key options |
|---------|-------|---------|-------------|
| `build` | `b` | Compile workspace or a project | `--config --platform --target --jobs/-j --keep-going/-k --tests --force-tests --no-cache --no-daemon`, Android options (`--android-build-system`, `--android-abis`, `--use-android-mk`, `--android-ndk-mk-mode`) |
| `run` | `r` | Run a project (build if needed) | `project --args --build --force --target/--device` |
| `gdb` | `g` (`debug`) | Debug a project with GDB (or LLDB) | `project --config --break/-b --run --batch --args --build --debugger (auto\|gdb\|lldb)` |
| `test` | `t` | Build and run test suites | `--project --no-build --force` |
| `clean` | `c` | Remove objects/binaries/cache | `--all --config --platform --project` |
| `rebuild` | — | `clean` then `build` | `--clean-all` + build options |
| `watch` | `w` | Auto-rebuild on change | `--polling --no-daemon` |
| `info` | `i` | Workspace, projects, toolchains, daemon | `--verbose` |

```bash
jenga build --config Release --platform Linux-x86_64 --target CoreLib
jenga run MyApp --args --level hard --fullscreen
jenga test --project Core_Tests --config Debug
jenga test --project Core_Tests --force        # despite dutc/dute, this once (Tests-Unitest §5)
jenga build --target Core_Tests --force-tests  # build only, despite dutc
jenga build -j8                     # 8 parallel jobs
jenga build --platform jengaall     # every declared platform
jenga build --keep-going            # build everything that can be built
jenga build --tests                 # also build test targets
```

#### `--keep-going` / `-k` — count instead of stopping

By default the build **stops** at the first failing target. On a workspace with
hundreds of targets you then discover **one** blocker at a time: one fix, one
commit, start over — and nobody knows how many targets are actually broken.

`--keep-going` builds everything it can and distinguishes **four states**:

| state | meaning |
|---|---|
| **succeeded** | built |
| **failed** | broken — this is where the work is |
| **skipped** | *not attempted*: one of its dependencies failed |
| **not reached** | the build stopped before it (default mode only) |

**Skipped** is what makes the mode worth having: a blocked target is **not
attempted**, because attempting it produces a *derived* error — a
`no such file or directory` on a missing archive — that looks like a second
defect and gets the same one fixed twice.

```
Projects Built:  3/5
Failed:          1
Skipped:         1  (failed dependency)

Failures (1) — to fix:
  ✗ LibBad
Skipped (1) — blocked by a dependency, not attempted:
  ⊘ waiting for LibBad: AppDep
```

> **Since v2.3.0**, `--verbose` no longer continues past a failure. It was an
> accidental `--keep-going`, undocumented and with the wrong semantics: it
> *attempted* blocked targets. A verbosity flag does not decide failure policy.

#### `--tests` — test targets are **roots**

**A test target is a ROOT, never a dependency.** Nothing may depend on one —
`dependson()` pointing at a test target raises an error naming the offending
edge. They are therefore **excluded from the default build**: on a real 272-target
workspace, 66 were tests — **24 % of work nobody asked for** when all you wanted
was to build your application.

```bash
jenga build                      # test targets are ignored
jenga build --tests              # they are included
jenga build --target Core_Tests  # named explicitly: always built
jenga test --project Core_Tests  # Core, its tests, their closure — nothing else
```

That last point matters: `jenga test` does **not** build the tests of the
target's dependencies, only its own.

#### Debugging with `gdb`

`jenga gdb` (re)builds in `Debug` if needed, locates the binary and launches GDB
(or LLDB when GDB is missing). The debugger is auto-detected.

```bash
jenga gdb                              # debug the startProject in Debug
jenga gdb MyApp --break main           # breakpoint on main (repeatable with -b)
jenga gdb MyApp -b file.cpp:42 --run   # breakpoint + start immediately
jenga gdb MyApp --args --level hard    # pass args to the debugged program
jenga gdb MyApp --debugger lldb        # force LLDB
jenga gdb MyApp --batch                # run + backtrace + quit (CI)
```

### Creation & editing

| Command | Alias | Purpose | Key options |
|---------|-------|---------|-------------|
| `workspace` | `init` | Create a workspace | `name --path --configs --oses --archs --interactive/-i` |
| `project` | `create` | Create a project or code element | `name --kind --lang --location --element --name --template -i` |
| `file` | `add` | Add sources/includes/libs/defines | `project --src --inc --link --def --type -i` |

```bash
jenga workspace MyGame --interactive
jenga project Engine --kind static --lang C++
jenga project Tool --location apps           # -> apps/Tool/
jenga project --element class --name Player --project Engine
jenga file MyApp --src "src/**.cpp" --inc include --link pthread
```

`--kind`: `console`, `windowed`, `static`, `shared`, `test`.
`--element`: `class`, `struct`, `enum`, `union`, `interface`, `function`,
`source`, `header`, `custom`.

> **Project placement**: `jenga project Foo` creates the project inside a folder
> **named after it** under the workspace (`<workspace>/Foo/`). With
> `--location apps`, the project goes to `<workspace>/apps/Foo/`. The generated
> DSL sets `location("Foo")` (or `location("apps/Foo")`).

### IDE generation & documentation

| Command | Alias | Purpose | Key options |
|---------|-------|---------|-------------|
| `gen` | — | Generate IDE project files | `--cmake --makefile --mk --android-mk --vs2022 --xcode --all --output/-o` |
| `docs` | `d` | Generate docs (Doxygen → MD/HTML/PDF) | project-dependent |
| `ide-setup` | `ide` | Configure editor for `.jenga` | `--editor (auto\|vscode\|lsp\|all) --force --info` |

```bash
jenga gen --cmake --vs2022 --output generated
jenga ide-setup --editor vscode
```

### Packaging, deployment, signing

| Command | Purpose | Key options |
|---------|---------|-------------|
| `package` | Create a distributable package | `--platform (required) --type --config --output/-o --project --ios-builder` |
| `deploy` | Deploy to a device | `--platform (required) --target/--device --apk --hap --list-devices --uninstall --run` |
| `sign` | Sign an APK/IPA | `--apk --ipa --keystore --alias --storepass --keypass --project` |
| `keygen` | Generate a keystore | `--alias --validity --output/-o -i --harmony` |
| `publish` | Publish to a registry | `--registry (required) --package --version --api-key --repo --dry-run` |

```bash
jenga package --platform windows --type msi --project MyApp -o ./dist
jenga package --platform android --type apk --project MyApp
jenga deploy --platform android --target emulator-5554 --run
jenga keygen --interactive
jenga sign --apk app.apk --keystore my.jks --alias key --storepass xxx --keypass xxx
```

> Types per platform: Android `apk`/`aab`, iOS `ipa`, Windows `msi`/`exe`/`zip`,
> Linux `deb`/`rpm`/`appimage`/`snap`, macOS `pkg`/`dmg`, Web `zip`, HarmonyOS `hap`.

### Tooling & analysis

| Command | Purpose | Key options |
|---------|---------|-------------|
| `bench` | Run benchmarks | `--project --iterations --output/-o` |
| `profile` | CPU/memory profiling | `--platform (required) --tool --duration --output/-o` |
| `install` | Dependencies / global toolchains | subcommands `toolchain list\|detect\|install` |
| `config` | Global Jenga configuration | `init\|show\|set\|get`, `toolchain …`, `sysroot …` |
| `examples` | List/copy examples | subcommands `list\|copy` |
| `help` | General or per-command help | `command` |

```bash
jenga install toolchain list
jenga install toolchain install android-ndk --path /path/to/ndk
jenga config set max_parallel_jobs 12
jenga bench --project BenchApp --iterations 20
jenga help build
```

### Alias list

`b`=build · `r`=run · `t`=test · `c`=clean · `w`=watch · `i`=info · `e`=examples ·
`d`=docs · `k`=keygen · `s`=sign · `h`=help · `init`=workspace · `create`=project ·
`add`=file · `ide`=ide-setup.
