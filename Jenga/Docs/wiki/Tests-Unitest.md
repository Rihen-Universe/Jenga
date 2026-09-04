<!-- AUTEUR : TEUGUIA TADJUIDJE Rodolf Séderis — Rihen -->
# Tests Unitest / Unitest Tests

**Langues / Languages :** [Français](#français) · [English](#english)

---

## Français

**Unitest** est le framework de tests C++ intégré à Jenga. Les sources et un
binaire précompilé sont livrés avec le package — aucune dépendance externe
(pas de GoogleTest, Catch2…).

### 1. Activer Unitest

Au niveau workspace, déclarez le mode :

```python
with workspace("UnitWorkspace"):
    configurations(["Debug", "Release"])
    targetoses([TargetOS.LINUX])
    targetarchs([TargetArch.X86_64])

    with unitest() as u:
        u.Precompiled()       # utilise la lib précompilée livrée (défaut)
        # ou
        # u.Compile(kind="STATIC_LIB", objDir="...", targetDir="...")
```

- **`Precompiled()`** : utilise le binaire Unitest fourni — démarrage immédiat.
- **`Compile(...)`** : recompile Unitest depuis les sources (utile en
  cross-compilation ou pour une plateforme exotique).

### 2. Déclarer une suite de tests

Le bloc `with test():` **doit être imbriqué directement** dans un `with
project():`. Il crée automatiquement un projet `<Projet>_Tests` dépendant du
projet parent et de Unitest.

```python
with project("Calculator"):
    staticlib()
    language("C++"); cppdialect("C++17")
    files(["src/**.cpp"])
    includedirs(["include"])

    with test():
        testfiles(["tests/**.cpp"])
        testmainfile("src/main.cpp")    # exclut le main du projet testé
        testoptions(["--verbose"])
```

#### La suite fournit son propre `main()` — `testownmain()` _(2.6.0+)_

Par défaut Jenga génère le point d'entrée (Unitest `AutoMain`). Une suite qui
a **son** `main()` — un programme de test, un banc — le dit :

```python
    with test():
        testfiles(["tests/**.cpp"])
        testownmain()                   # ne pas générer de main : le mien est dans tests/
```

Le Builder vérifie **avant de compiler** : une suite, un `main()`.
- `testownmain()` et aucun `main()` dans ses sources → erreur ;
- **deux `main()` ou plus** (avec ou sans le mot) → refusé **en nommant les
  fichiers** : `Test suite 'X_Tests' defines main() in 2 files: tests/a.cpp,
  tests/b.cpp. One suite, one main: declare one sub-suite per program…`. Deux
  programmes dans `tests/` sont deux sous-suites :

  ```python
      with test("Serial"):            # -> X_Serial_Tests
          testfiles(["tests/serial_main.cpp"]); testownmain()
      with test("Binary"):            # -> X_Binary_Tests
          testfiles(["tests/binary_main.cpp"]); testownmain()
  ```
- un `main()` sans `testownmain()` alors que Jenga en génère un → refusé en
  disant le mot (`declare testownmain() in its test() block, or exclude the
  file`). L'ancien contournement — `testmaintemplate()` sur un fichier vide —
  reste accepté ; `testownmain()` et `testmaintemplate()` ensemble se
  contredisent (erreur au chargement).

La détection est textuelle (`int|auto|void main|wmain|WinMain|wWinMain(` suivi
d'une accolade avant tout `;`, commentaires retirés) : un `main()` sous
`#if 0` compte encore. Elle est bruyante quand elle se trompe, jamais muette.

### 3. Écrire un test

```cpp
#include <Unitest/Unitest.h>

TEST_CASE(MathSuite, Addition) {
    ASSERT_EQUAL(4, 2 + 2);
    ASSERT_TRUE(3 > 2);
}

TEST(SimpleCheck) {
    ASSERT_NEAR(3.14, 3.14159, 0.01);
}
```

Macros disponibles : `TEST_CASE(suite, nom)`, `TEST(nom)`, `ASSERT_EQUAL`,
`ASSERT_TRUE`, `ASSERT_NULL`, `ASSERT_LESS`, `ASSERT_NEAR`, `ASSERT_THROWS`,
`ASSERT_CONTAINS`. Le framework fournit aussi du **benchmarking** et du
**profilage** (flamegraph).

### 4. Compiler et exécuter

```bash
jenga test                              # compile + lance toutes les suites
jenga test --project Calculator_Tests   # une suite précise
jenga test --config Debug --no-build    # sans recompiler
jenga test --project Calculator_Tests --force   # malgré dutc/dute (voir §5)
jenga test --project Calculator_Tests --no-runtime-path   # sans le bin de la chaîne sur le PATH
```

`jenga test` continue même si une suite échoue, et agrège les résultats dans un
rapport console.

**PATH d'exécution** _(2.6.0+)_ : au moment de lancer la cible, `jenga test` et
`jenga run` mettent en tête du `PATH` le répertoire des exécutables de **la
chaîne du projet** et les dossiers de sortie des `SharedLib` dont la cible
dépend. Sans cela, une suite liée contre `libstdc++-6.dll` (clang-mingw)
sortait en **127 sans un mot** dès que `ucrt64/bin` manquait au `PATH` de
l'appelant. `--no-runtime-path` reproduit l'environnement d'un utilisateur :
c'est le geste pour vérifier qu'un binaire est autonome (voir §6).

### 5. Politiques de workspace

```python
disableunittestcompilation(True)   # ou dutc(True) — ne pas compiler les tests
disableunittestexecution(True)     # ou dute(True) — ne pas exécuter les tests
```

Posées dans le bloc `with workspace(...)`, elles valent pour **tout** l'espace
de travail : les suites sortent de l'ordre de construction, une cible de test
explicite est refusée (*« Blocked target »*), `jenga test` s'arrête.

#### Liste blanche par projet — `allow=[...]` _(2.5.0+)_

Pour rouvrir les tests **module par module** sans lever la politique pour tout
le monde, chaque politique accepte une liste de suites qui y **échappent** :

```python
with workspace("Nkentseu"):
    dutc(enable=True, allow=["NKCore_Tests", "NKMath_Tests"])
    dute(enable=True, allow=["NKCore_Tests", "NKMath_Tests"])
    ...
    with include("Kernel/Foundation/NKCore/NKCore.jenga"):   # déclare NKCore + NKCore_Tests
        pass
```

- **Sémantique** : la politique reste en place ; les suites nommées se
  compilent (`dutc`) et s'exécutent (`dute`) comme si elle n'existait pas ;
  toutes les autres restent bloquées. `jenga test` sans `--project` lance les
  suites autorisées et dit celles qu'il saute (*« Skipped by workspace policy »*).
- **Deux listes, deux politiques** : `dutc` et `dute` sont distinctes, leurs
  listes aussi. Une suite listée dans `dutc` seulement se compile mais ne se
  lance pas ; l'inverse est possible (`--no-build` sur un binaire existant).
- **Noms** : ceux des projets de test, `<Projet>_Tests` (ou
  `<Projet>_<Sous-nom>_Tests` pour `test("Sous-nom")`) — pas le nom du module.
  Une chaîne seule vaut une liste d'un élément. `allow` **remplace** la liste
  précédente, il ne l'étend pas.
- **Un nom inconnu est une erreur, pas un silence**, vérifiée à la fermeture du
  bloc `with workspace(...)` (les projets des `include` sont alors connus) :

  ```
  Error loading workspace: dutc(allow=...) : projet de test inconnu 'NKCore'
  dans l'espace de travail 'Nkentseu' — vouliez-vous dire 'NKCore_Tests' ?
  Suites connues : NKContainers_Tests, NKCore_Tests, NKMath_Tests, …
  ```

- **Sans `allow`** (ou `allow=[]`), rien ne change par rapport aux versions
  précédentes.
- Variables : `%{wks.unittestcompilationallow}`, `%{wks.unittestexecutionallow}`.

#### Lever la politique pour une invocation — `--force` _(effectif depuis 2.5.0)_

```bash
jenga test --project NKPhysics_Tests --force      # compile ET lance, malgré dutc/dute
jenga run  NKPhysics_Tests --build --force         # idem par run
jenga build --target NKPhysics_Tests --force-tests # construction seule, malgré dutc
```

`--force` lève les deux politiques **pour cette invocation seulement** ; le
défaut de l'espace de travail reste rapide. Avant 2.5.0, `jenga test --force`
levait les contrôles de la commande mais ne transmettait rien au Builder, qui
rebloquait la cible (*« Blocked target »*) : le drapeau était accepté et sans
effet. Il traverse désormais, en direct comme via le daemon.

Le témoin de tout ceci est `tests/test_unittest_policy.py` (espace de travail
réel, deux suites, une mutation qui fait rougir).

### 6. Erreurs fréquentes

- `test context must be placed directly inside a project block` → le bloc
  `with test():` doit être imbriqué dans `with project(...):`.
- Unitest non configuré → ajouter `with unitest() as u: u.Precompiled()` dans le
  workspace avant les projets qui utilisent `test()`.
- **`'X_Tests.exe' did not start: exit code 0xC0000135 (STATUS_DLL_NOT_FOUND)`**
  _(2.6.0+)_ → le binaire n'a **pas démarré** : ce n'est pas un test rouge. Jenga
  nomme les DLL importées introuvables (`libstdc++-6.dll, libgcc_s_seh-1.dll,
  libwinpthread-1.dll` = runtime MinGW lié dynamiquement). Remède durable :
  lier le runtime statiquement — `staticruntime()` sur le projet, ou
  `ldflags(["-static-libstdc++", "-static-libgcc"])` sur la chaîne — ou livrer
  la DLL à côté du binaire. Sans `--no-runtime-path`, Jenga met le `bin` de la
  chaîne sur le `PATH` et la suite parle ; ça ne rend pas le binaire livrable.
  Même diagnostic pour `127` (bash / `ld.so`), `0xC0000139` (symbole absent :
  mauvaise version de DLL sur le `PATH`) et `0xC000007B` (DLL de la mauvaise
  architecture trouvée d'abord).
- `Test suite 'X_Tests' defines main() in 2 files` → deux programmes dans une
  suite : une sous-suite par programme (`with test("Sub"):` + `testownmain()`),
  ou `excludefiles` pour ce qui n'est pas un test (§2).
- `defines main() in tests/foo.cpp while Jenga generates one` → ajouter
  `testownmain()` dans le bloc `test()` (§2).

---

## English

**Unitest** is the C++ testing framework built into Jenga. Sources and a
precompiled binary ship with the package — no external dependency
(no GoogleTest, Catch2…).

### 1. Enable Unitest

Declare the mode at workspace level:

```python
with workspace("UnitWorkspace"):
    configurations(["Debug", "Release"])
    targetoses([TargetOS.LINUX])
    targetarchs([TargetArch.X86_64])

    with unitest() as u:
        u.Precompiled()       # use the shipped precompiled lib (default)
        # or
        # u.Compile(kind="STATIC_LIB", objDir="...", targetDir="...")
```

- **`Precompiled()`**: uses the bundled Unitest binary — instant start.
- **`Compile(...)`**: rebuilds Unitest from source (useful for
  cross-compilation or exotic platforms).

### 2. Declare a test suite

The `with test():` block **must be nested directly** inside a `with
project():`. It automatically creates a `<Project>_Tests` project depending on
the parent project and on Unitest.

```python
with project("Calculator"):
    staticlib()
    language("C++"); cppdialect("C++17")
    files(["src/**.cpp"])
    includedirs(["include"])

    with test():
        testfiles(["tests/**.cpp"])
        testmainfile("src/main.cpp")    # exclude the tested project's main
        testoptions(["--verbose"])
```

#### The suite provides its own `main()` — `testownmain()` _(2.6.0+)_

By default Jenga generates the entry point (Unitest `AutoMain`). A suite that
has **its own** `main()` — a test program, a benchmark — says so:

```python
    with test():
        testfiles(["tests/**.cpp"])
        testownmain()                   # generate no main: mine is in tests/
```

The Builder checks **before compiling**: one suite, one `main()`.
- `testownmain()` with no `main()` in its sources → error;
- **two or more `main()`** (with or without the word) → refused **naming the
  files**: `Test suite 'X_Tests' defines main() in 2 files: tests/a.cpp,
  tests/b.cpp. One suite, one main: declare one sub-suite per program…`. Two
  programs under `tests/` are two sub-suites:

  ```python
      with test("Serial"):            # -> X_Serial_Tests
          testfiles(["tests/serial_main.cpp"]); testownmain()
      with test("Binary"):            # -> X_Binary_Tests
          testfiles(["tests/binary_main.cpp"]); testownmain()
  ```
- a `main()` without `testownmain()` while Jenga generates one → refused
  saying the word (`declare testownmain() in its test() block, or exclude the
  file`). The old workaround — `testmaintemplate()` on an empty file — is still
  accepted; `testownmain()` and `testmaintemplate()` together contradict each
  other (error at load).

Detection is textual (`int|auto|void main|wmain|WinMain|wWinMain(` followed by
a brace before any `;`, comments stripped): a `main()` under `#if 0` still
counts. It is loud when wrong, never silent.

### 3. Write a test

```cpp
#include <Unitest/Unitest.h>

TEST_CASE(MathSuite, Addition) {
    ASSERT_EQUAL(4, 2 + 2);
    ASSERT_TRUE(3 > 2);
}

TEST(SimpleCheck) {
    ASSERT_NEAR(3.14, 3.14159, 0.01);
}
```

Available macros: `TEST_CASE(suite, name)`, `TEST(name)`, `ASSERT_EQUAL`,
`ASSERT_TRUE`, `ASSERT_NULL`, `ASSERT_LESS`, `ASSERT_NEAR`, `ASSERT_THROWS`,
`ASSERT_CONTAINS`. The framework also provides **benchmarking** and
**profiling** (flamegraph).

### 4. Build and run

```bash
jenga test                              # build + run all suites
jenga test --project Calculator_Tests   # a specific suite
jenga test --config Debug --no-build    # without rebuilding
jenga test --project Calculator_Tests --force   # despite dutc/dute (see §5)
jenga test --project Calculator_Tests --no-runtime-path   # without the toolchain bin on PATH
```

`jenga test` keeps going even if a suite fails, and aggregates results into a
console report.

**Runtime PATH** _(2.6.0+)_: when launching the target, `jenga test` and
`jenga run` prepend to `PATH` the executables directory of **the project's
toolchain** and the output directories of the `SharedLib`s the target depends
on. Without it, a suite linked against `libstdc++-6.dll` (clang-mingw) exited
**127 without a word** whenever `ucrt64/bin` was missing from the caller's
`PATH`. `--no-runtime-path` reproduces a user's environment: that is how you
check a binary is self-contained (see §6).

### 5. Workspace policies

```python
disableunittestcompilation(True)   # or dutc(True) — don't compile tests
disableunittestexecution(True)     # or dute(True) — don't run tests
```

Set inside `with workspace(...)`, they apply to the **whole** workspace: test
suites leave the build order, an explicit test target is refused (*"Blocked
target"*), `jenga test` stops.

#### Per-project allow list — `allow=[...]` _(2.5.0+)_

To reopen tests **module by module** without lifting the policy for everyone,
each policy accepts a list of suites that **escape** it:

```python
with workspace("Nkentseu"):
    dutc(enable=True, allow=["NKCore_Tests", "NKMath_Tests"])
    dute(enable=True, allow=["NKCore_Tests", "NKMath_Tests"])
    ...
    with include("Kernel/Foundation/NKCore/NKCore.jenga"):   # declares NKCore + NKCore_Tests
        pass
```

- **Semantics**: the policy stays; the named suites compile (`dutc`) and run
  (`dute`) as if it did not exist; every other suite stays blocked.
  `jenga test` without `--project` runs the allowed suites and names the ones
  it skips (*"Skipped by workspace policy"*).
- **Two lists, two policies**: `dutc` and `dute` are distinct, so are their
  lists. A suite listed in `dutc` only compiles but does not run; the reverse
  works too (`--no-build` on an existing binary).
- **Names**: those of the test projects, `<Project>_Tests` (or
  `<Project>_<Subname>_Tests` for `test("Subname")`) — not the module name. A
  single string counts as a one-element list. `allow` **replaces** the previous
  list, it does not extend it.
- **An unknown name is an error, not silence**, checked when the
  `with workspace(...)` block closes (projects from `include` are known by then):

  ```
  Error loading workspace: dutc(allow=...) : projet de test inconnu 'NKCore'
  dans l'espace de travail 'Nkentseu' — vouliez-vous dire 'NKCore_Tests' ?
  Suites connues : NKContainers_Tests, NKCore_Tests, NKMath_Tests, …
  ```

- **Without `allow`** (or `allow=[]`), nothing changes from previous versions.
- Variables: `%{wks.unittestcompilationallow}`, `%{wks.unittestexecutionallow}`.

#### Lifting the policy for one invocation — `--force` _(effective since 2.5.0)_

```bash
jenga test --project NKPhysics_Tests --force      # build AND run, despite dutc/dute
jenga run  NKPhysics_Tests --build --force         # same through run
jenga build --target NKPhysics_Tests --force-tests # build only, despite dutc
```

`--force` lifts both policies **for this invocation only**; the workspace
default stays fast. Before 2.5.0, `jenga test --force` lifted the command's own
checks but passed nothing to the Builder, which blocked the target again
(*"Blocked target"*): the flag was accepted and had no effect. It now goes all
the way through, directly and via the daemon.

The witness for all of this is `tests/test_unittest_policy.py` (real workspace,
two suites, a mutation that turns it red).

### 6. Common errors

- `test context must be placed directly inside a project block` → the
  `with test():` block must be nested inside `with project(...):`.
- Unitest not configured → add `with unitest() as u: u.Precompiled()` to the
  workspace before any project that uses `test()`.
- **`'X_Tests.exe' did not start: exit code 0xC0000135 (STATUS_DLL_NOT_FOUND)`**
  _(2.6.0+)_ → the binary did **not start**: this is not a red test. Jenga names
  the imported DLLs it could not find (`libstdc++-6.dll, libgcc_s_seh-1.dll,
  libwinpthread-1.dll` = MinGW runtime linked dynamically). Durable fix: link
  the runtime statically — `staticruntime()` on the project, or
  `ldflags(["-static-libstdc++", "-static-libgcc"])` on the toolchain — or ship
  the DLL next to the binary. Without `--no-runtime-path`, Jenga puts the
  toolchain `bin` on `PATH` and the suite speaks; that does not make the binary
  shippable. Same diagnosis for `127` (bash / `ld.so`), `0xC0000139` (missing
  symbol: wrong DLL version on `PATH`) and `0xC000007B` (DLL of the wrong
  architecture found first).
- `Test suite 'X_Tests' defines main() in 2 files` → two programs in one suite:
  one sub-suite per program (`with test("Sub"):` + `testownmain()`), or
  `excludefiles` for what is not a test (§2).
- `defines main() in tests/foo.cpp while Jenga generates one` → add
  `testownmain()` to the `test()` block (§2).

See example `04_unit_tests`.
