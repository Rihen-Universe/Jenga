# Changelog

Toutes les modifications notables de Jenga sont documentées ici.
Format inspiré de [Keep a Changelog](https://keepachangelog.com) ; versionnage [SemVer](https://semver.org).

## v2.6.3

### Ajouté

- **`jenga kit` — extraire un kit redistribuable d'un workspace.**
  `jenga kit --target M --config all --platform P --output D` récolte les
  en-têtes publics et les bibliothèques déjà construites des modules demandés,
  puis écrit un fichier de configuration Jenga que le consommateur charge par
  `useconfig()`. La commande résout la **fermeture transitive** : une archive
  statique ne contient pas ses dépendances, elle garde ses trous — demander
  `NKLogger` emporte les six modules, sans quoi le kit compile et ne lie pas.

### Corrigé

- **L'évaluateur de filtres renonçait devant `!` et `||`.** Un kit Windows
  sortait donc **sans `user32` ni `gdi32`** — impossible d'ouvrir une fenêtre
  chez celui qui le reçoit — parce que les liens Windows sont posés sous
  `system:Windows && !options:windows-runtime=uwp && !system:XboxSeries && !system:XboxOne`.
  L'évaluateur traite maintenant `&&`, `||` et `!`. Une option n'est jamais
  posée au moment de fabriquer un kit : `options:x` est faux, `!options:x` vrai.
  Un atome de genre inconnu rend l'expression fausse, **sans** négation — on
  préfère un lien manquant, qui se voit, à un lien de trop, qui ne se voit pas.
  Le kit NKWindow passe de 0 à 15 bibliothèques système.

## v2.6.2

### Corrigé

- **`%{Projet.location}` ne se résolvait pas sous `with filter(...)`.**
  Mesuré par l'agent Noge sur Nkentseu le 2026-09-04 : dans la sous-suite
  `ReflectPhase5` de `NKSerialization` (déclarée sous le filtre desktop, comme
  toutes les suites de Nkentseu), `includedirs(["%{NKMath.location}/src"])`
  arrivait **littéral** au compilateur — `-I%{NKMath.location}/src` —
  parce que `includedirs()` sous filtre écrit dans `_filteredIncludeDirs`,
  que l'expansion du Loader sautait (attribut privé) et que le Builder
  fusionnait tel quel ; `ResolveProjectPath` rendait ensuite la chaîne
  intacte dès qu'elle contenait `%{`. Ce n'était pas la sous-suite : hors
  filtre, la même ligne se résolvait. Trois gestes, du bas vers le haut :
  - `Variables.ExpandAll` expanse les formes filtrées (`_filtered*`) comme
    les formes nues — même propriété, même expansion ;
  - `Builder.ResolveProjectPath` **expanse avant de résoudre** : une variable
    qui ne se lit qu'à la construction (`%{cfg.*}`) ou une forme filtrée d'un
    espace construit sans Loader arrive absolue au compilateur ; une variable
    inconnue reste intacte, jamais inventée ;
  - le Loader rend les locations de projet **absolues avant l'expansion** :
    en espace mono-fichier, `%{A.location}` lisait `location("libA")` tel
    qu'écrit — relatif — puis le collait à la location du *lecteur*
    (`<wks>/libB/libA/src`), faux en silence. C'est la forme « reste relatif »
    du même signalement.

  Les `.jenga` inclus (`with include(...)`) avaient déjà une location absolue
  à la sortie de l'`include` : c'est pour cela que la forme nue de
  `%{X.location}` marchait dans Nkentseu depuis toujours, et que seule la
  forme sous filtre manquait.

### Témoin

`tests/test_filtered_variables.py` — 9 cas. Par le Loader : sous-suite sous
filtre → `_filteredIncludeDirs` et `_filteredLibDirs` absolus ; sous-suite
sans filtre et suite principale inchangées ; espace mono-fichier à locations
relatives → `%{A.location}/src` absolu, sous filtre aussi ; une variable de
construction (`%{cfg.buildcfg}`) est laissée au Builder. Par le Builder sans
Loader : `ResolveProjectPath` expanse puis résout, les listes filtrées
fusionnées se résolvent à l'usage, un projet inconnu reste intact. Espace
réel compilé : une sous-suite sous filtre inclut un en-tête qui n'existe
**que** sous `%{Far.location}/include` et `jenga test` la lance
(`REACH RAN 9`) ; **mutation** — l'en-tête déplacé → rouge. Contre-épreuve
sur le produit : `_filtered*` de nouveau sautés par `ExpandAll` → rouge ;
`ResolveProjectPath` rendu sourd → rouge ; locations rendues absolues après
l'expansion → rouge. Le chargement réel de `Nkentseu.jenga` (60 suites)
passe inchangé, et ne laisse plus aucun `%{X.location}` littéral dans les
listes filtrées.

## v2.6.1

### Corrigé

- **Le bloc `test()` remettait le projet courant à `None` en sortant**
  (`Api.py`, `test.__exit__`). Deux conséquences, mesurées par l'agent Noge sur
  Nkentseu le 2026-09-04 après usage de 2.6.0 : **un second `with test("…")`
  dans le même projet échouait** (*« test context must be placed directly
  inside a project block »*), et **tout mot du DSL écrit après un bloc `test()`
  était ignoré en silence** — un `.jenga` qui déclare et dont la déclaration ne
  produit rien. Les sous-suites que `testownmain()` rend possibles
  (NKSerialization ×5, NKECS, NKXR, bancs NKLogger/NKTime) étaient nommées,
  pas actives. Le bloc **rend le projet tel qu'il l'a trouvé** : plusieurs
  `test()` par projet = plusieurs suites (`X_Tests`, `X_Sub_Tests`) ; un mot
  après le bloc s'applique au parent.

### Ajouté

- **Un mot du DSL hors de sa portée se refuse, en le disant.** 128 mots
  commençaient par `if _currentProject:` et ne faisaient rien sinon. Ils sont
  désormais enveloppés (`_RefuseOutside`, fin de `Core/Api.py`) : hors portée,
  `RuntimeError` qui nomme **le mot et la ligne du `.jenga`** —
  `'files()' used outside any project block (at D:\…\Core.jenga:12). It would
  have had no effect: refused rather than ignored.` Quatre portées : projet
  (120 mots), `test()` (5 : `testfiles`, `testoptions`, `testmainfile`,
  `testmaintemplate`, `testownmain`), projet-ou-toolchain (`cflags`,
  `cxxflags`, `ldflags`), projet-ou-workspace (`emscriptenfullscreenshell`).
  Les mots qui portent déjà leur refus (`usetoolchain`, `firewallrule`, …) ou
  qui ont un repli d'une portée à l'autre (`defines`, `warnings`, …) ne
  changent pas. À l'intérieur de leur portée, rien ne change.

### Témoin

`tests/test_dsl_scope.py` — 10 cas : deux `test()` dans un projet → deux
suites (`Serial_Tests`, `Serial_Bench_Tests` avec `testownmain`) ; un mot après
le bloc → honoré par le parent, pas par la suite ; le projet courant est le
parent à la sortie ; `files()` hors projet → erreur nommant le mot et la
ligne ; `testfiles()`/`testownmain()` hors `test()` → erreur ; `ldflags()`
accepté dans une toolchain, refusé hors des deux ; noms conservés ; par le
Loader : le `.jenga` à deux suites + mot après charge, le `.jenga` au mot hors
projet est refusé avec `Wl.jenga:4`. Contre-épreuve sur le produit : `None`
remis à la sortie de `test()` → rouge ; enveloppes retirées → rouge. Le
chargement réel de `Nkentseu.jenga` (60 suites, 35+ fichiers) passe inchangé.

## v2.6.0

### Ajouté

- **`testownmain()` — la suite fournit son propre `main()`, Jenga n'en génère
  pas.** Jusqu'ici la seule forme était un contournement : `testmaintemplate()`
  pointé sur un fichier **vide**, pour que rien ne soit injecté (Nkentseu :
  NKPhysics, NKCollision, NKImage). Le mot dit ce qu'il fait, et le Builder
  vérifie avant de compiler — **une suite, un `main()`** :
  - `testownmain()` sans aucun `main()` dans ses sources → erreur ;
  - **deux `main()` ou plus, quelle que soit la forme → refusé en nommant les
    fichiers** (`Test suite 'X_Tests' defines main() in 2 files: a.cpp, b.cpp`)
    et en disant la forme attendue : une sous-suite par programme
    (`with test("Sub"):`). NKSerialization en a 6, NKXR 5, NKAudio 5 : ce sont
    des sous-suites à déclarer, pas une suite à fusionner ;
  - un `main()` sans le mot alors que Jenga en génère un → refusé **en disant
    le mot** (`declare testownmain()`), plutôt qu'un `multiple definition of
    main` du lieur. L'ancien contournement au gabarit vide reste accepté.
  - `testownmain()` et `testmaintemplate()` dans la même suite se contredisent :
    erreur au chargement.

  Détection textuelle (`int|auto|void main|wmain|WinMain|wWinMain(` suivi d'une
  accolade avant tout point-virgule, commentaires retirés) : bruyante quand
  elle se trompe, jamais silencieuse ; dans l'autre sens le lieur rattrape.

- **`jenga test` / `jenga run` mettent le `bin` de la chaîne en tête du
  `PATH` au moment d'exécuter la cible** — et les dossiers de sortie des
  `SharedLib` dont elle dépend, transitivement. Mesuré sur Nkentseu le
  2026-09-04 : `NKMath_Tests.exe`, lié contre `libstdc++-6.dll` de clang-mingw,
  sortait en **127 muet** dès que `ucrt64/bin` n'était pas sur le `PATH` de
  l'appelant ; la suite était verte, le verdict n'arrivait pas. La chaîne est
  celle **du projet** (filtres appliqués, `Builder.ResolveProjectToolchain`),
  pas celle de l'espace de travail. `--no-runtime-path` reproduit
  l'environnement d'un utilisateur — c'est ainsi qu'on vérifie qu'un binaire
  est autonome.

- **Un binaire qui n'a PAS démarré se dit.** `0xC0000135`
  (`STATUS_DLL_NOT_FOUND`), `0xC0000139`, `0xC000007B` — sous leur forme signée
  aussi, telle que Python les rend — et `127` ne sont plus des échecs
  ordinaires : `jenga test`/`run` nomment la cible, le code, et **les DLL
  importées introuvables** (table d'import PE lue sans dépendance externe ;
  les API sets `api-ms-win-*` sont ignorés) à côté du binaire, sur le `PATH`
  réellement utilisé et dans les répertoires système ; puis le remède
  (`staticruntime()` / `-static-libstdc++ -static-libgcc`, ou livrer la DLL).
  Sur le vrai `NKMath_Tests.exe` : `libgcc_s_seh-1.dll, libwinpthread-1.dll,
  libstdc++-6.dll`. Nouveau module `Jenga/Utils/RuntimeDiag.py`.

### Mesuré, et pas corrigé côté Jenga

- **`config/toolchain.jenga:92-94` de Nkentseu (`-static`) n'atteint pas le
  lien — parce qu'il n'est pas dans la branche exécutée.** Ces lignes sont dans
  le bloc *« Cross-compilation Windows depuis Linux/WSL2 »* (`else:`). Le bloc
  Windows natif (`if os.name == "nt":`, l. 34-55) promet en commentaire le
  lien statique du runtime et ne passe que `--target=x86_64-w64-windows-gnu`.
  Mesuré sur l'espace de travail chargé : `nk-windows-clang-mingw.ldflags ==
  ['--target=x86_64-w64-windows-gnu']`, et `NKMath_Tests` résout bien vers
  cette chaîne (`_explicitToolchain=True` après filtres). Jenga honore ce
  qu'on lui donne ; le défaut est dans le `.jenga`, à corriger là.

### Témoin

`tests/test_unittest_runner.py` — 14 cas. Sans compilateur : définition contre
déclaration contre commentaire, `WinMain`, deux fichiers ; codes du chargeur
sous les deux signes ; un fichier qui n'est pas un PE. Avec compilateur : la
suite démarre quand le `PATH` de l'appelant ignore la chaîne ; avec
`--no-runtime-path` sur ce même `PATH`, `jenga test` et `jenga run` disent
`STATUS_DLL_NOT_FOUND` et `libstdc++-6.dll` ; `testownmain()` compile et son
`main` s'exécute (`OWN MAIN RAN 5`) ; deux `main()` refusés en nommant les deux
fichiers ; un `main()` sans le mot refusé en disant le mot ; mutation : le mot
retiré → rouge ; `testownmain()` + `testmaintemplate()` → contradiction dite.
Contre-épreuve sur le produit : runner sans PATH d'exécution → 2 rouges ;
Builder qui ne compte plus les `main()` → 3 rouges.

## v2.5.0

### Ajouté

- **`dutc(enable, allow=[...])` / `dute(enable, allow=[...])` — les politiques
  de tests unitaires ont une liste blanche par projet.** Mesuré sur Nkentseu le
  2026-09-04 : `Nkentseu.jenga` porte `dutc(enable=True)` / `dute(enable=True)`
  depuis le 2026-03-12, et **aucun des 60 projets `*_Tests` ne pouvait rougir**
  depuis six mois — la politique n'avait qu'une portée : tout l'espace de
  travail. Rouvrir les tests « module par module » n'avait pas de forme.

  ```python
  dutc(enable=True, allow=["NKCore_Tests", "NKMath_Tests"])
  dute(enable=True, allow=["NKCore_Tests", "NKMath_Tests"])
  ```

  La politique reste posée ; les suites nommées y échappent. Les deux listes
  sont **distinctes**, comme les deux politiques : une suite peut être
  compilable sans être exécutable, et inversement. `allow` remplace la liste
  précédente (il ne l'étend pas) ; une chaîne seule vaut une liste d'un élément.
  Lue par le Builder (`_ApplyUnitTestCompilationPolicy`), `jenga test` et
  `jenga run`. `__Unitest__`, la bibliothèque du cadre de test, suit les
  suites : elle se construit dès qu'une suite autorisée en dépend.

  **Un nom inconnu est une erreur dite, pas un silence** — vérifiée à la
  fermeture du bloc `with workspace(...)`, quand les projets des `include` sont
  connus : `dutc(allow=...) : projet de test inconnu 'NKCore' dans l'espace de
  travail 'Nkentseu' — vouliez-vous dire 'NKCore_Tests' ? Suites connues : …`.
  Une liste blanche qui accepterait l'inconnu « autoriserait » une faute de
  frappe et laisserait la vraie suite bloquée sans un mot.

  Variables : `%{wks.unittestcompilationallow}` / `%{wks.unittestexecutionallow}`.

- **`jenga build --force-tests`** — construit une cible de test malgré `dutc`,
  pour cette invocation. C'est le relais que `jenga test --force` et
  `jenga run --force` transmettent au Builder (voir Corrigé). Nommé
  `--force-tests` et non `--force` : sur `build`, un `--force` nu se lirait
  « recompile tout ».

### Corrigé

- **`jenga test --force` et `jenga run --force` n'avaient aucun effet.** Les
  deux commandes levaient leurs propres contrôles (`Test.py`, `Run.py`) puis
  appelaient `jenga build --target X_Tests` **sans rien transmettre** : le
  Builder rebloquait la cible que la commande venait d'autoriser — mesuré sur
  Nkentseu : *« Blocked target: 'NKPhysics_Tests' »* malgré `--force
  --no-daemon`. Le drapeau traverse désormais jusqu'au Builder
  (`Builder.forceUnitTests`), en direct comme via le daemon (`force` / `force_tests`
  relayés dans les trois commandes).

### Comportement inchangé

- Un espace de travail **sans** `allow` et **sans** `--force` se comporte
  exactement comme avant : tests exclus du build par défaut, cible de test
  explicite bloquée avec le même message (complété d'une phrase qui dit comment
  la lever), `jenga test` refusé par `dute`.

### Témoin

`tests/test_unittest_policy.py` — 23 cas. Sept sur la politique du Builder
(liste blanche, `__Unitest__` conservé pour une suite autorisée, `--force`,
politique éteinte), sept sur le DSL (forme, chaîne seule, erreur dite avec les
suites connues et la suggestion `_Tests`, exception en vol non masquée), et
**neuf sur un espace de travail réel** compilé par le compilateur de la machine
(sautés, en le disant, s'il n'y en a pas) : suite listée compilée **et lancée**,
suite non listée bloquée avec le message, `--force` qui débloque `test`, `run`
et `build --force-tests`, puis **deux mutations qui font rougir** — la suite
retirée de la liste redevient bloquée, et une assertion cassée dans le `.cpp`
fait échouer `jenga test` (preuve que le binaire est lancé, pas seulement
construit). Contre-épreuve faite sur le produit : le Builder rendu sourd à
`forceUnitTests` → 4 rouges ; `jenga test` ne relayant plus `--force-tests` →
1 rouge.

## v2.4.0

### Retiré

- **Le sous-module `Jenga/Exemples/Nkentseu` est retiré du dépôt.** Ce n'est pas
  du ménage : **le dépôt n'était pas clonable.** Mesuré par le clone lui-même :

  ```
  git clone --recurse-submodules <jenga>
  Submodule path 'Jenga/Exemples/Nkentseu': checked out '05f25e39...'
  fatal: No url found for submodule path
         'Jenga/Exemples/Nkentseu/Externals/Libs/NKSPIRVCross' in .gitmodules
  fatal: Failed to recurse into submodule path 'Jenga/Exemples/Nkentseu'
  EXIT = 128
  ```

  La cause est **un cran plus bas que le sous-module lui-même**. Le commit
  épinglé `05f25e39` (28/03/2026) se récupère très bien ; il est peuplé
  (2 351 fichiers). Mais l'instantané de Nkentseu de mars 2026 porte
  **deux gitlinks orphelins** — `Externals/Libs/NKSPIRVCross` et
  `Externals/Libs/NKShaderc`, enregistrés en mode `160000` dans son arbre —
  **sans aucun fichier `.gitmodules` pour leur donner une URL**. Git ne peut donc
  pas descendre d'un niveau, et abandonne le clone entier.

  Jenga ne peut pas réparer ça depuis son côté : le défaut est dans le contenu
  du commit épinglé, pas dans sa déclaration.
  - Retrait complet, pas un `rm` : `.gitmodules` (supprimé, la déclaration y
    était unique), gitlink de l'index, page wiki `Docs/wiki/Exemples.md` (FR+EN),
    exclusions de `scripts/build_examples_archive.py` et de `pyproject.toml`,
    mentions de `cri.sh` / `cri.bat` / `.github/workflows/release.yml`, et le
    garde-fou « ne jamais committer le pointeur » devenu sans objet dans
    `gitcommit.sh`, `gitpush.sh`, `gitpush.bat`.
  - **Le catalogue de `jenga examples` n'est pas touché** : vérifié, son
    dictionnaire `EXAMPLES` (28 entrées) ne contenait aucun identifiant
    `Nkentseu` — l'exemple n'a jamais été listé ni documenté par la commande. Il
    n'était atteignable que par coïncidence de chemin
    (`jenga examples copy Nkentseu` dans un clone), ce qui retourne désormais
    l'erreur « exemple introuvable » habituelle.

### Changement de comportement

- **Jenga ne crée plus de `.vscode/` quand aucun éditeur n'est détecté.**
  Signalé par un utilisateur de NKCode : *« je croyais que le `.vscode` ne devait
  être là que quand on code sur VSCode »*. Il avait raison — `DetectEditors`
  finissait par :

  ```python
  # Si rien detecte, on assume VSCode (le plus repandu) [...]
  if not any(e in found for e in ("vscode", "jetbrains", "sublime", "neovim")):
      found.insert(0, "vscode")
  ```

  Trois défauts, et **le deuxième est celui qui rendait la chose durable** :

  1. un dossier apparaissait pour un éditeur que l'utilisateur n'ouvre jamais ;
  2. ce dossier était ensuite **détecté** par le test `(root / ".vscode").exists()`
     dix lignes plus haut — donc une *supposition* du premier passage devenait un
     *fait* au second, définitivement. Un défaut qui se confirme lui-même ne se
     corrige jamais tout seul, et il devient indiscernable d'un choix de
     l'utilisateur ;
  3. il écrivait dans un fichier versionné que l'utilisateur partage avec ses
     propres réglages.

  **Ce qui remplace** : Jenga n'écrit que pour un éditeur **dont la trace
  existe**. Sans trace, seul `pyrightconfig.json` est produit — il n'appartient à
  aucun éditeur, tout client LSP le consomme (NKCode compris), et il n'engage
  rien.

  **`.nkcode/` est désormais reconnu** comme marqueur d'espace de travail. Ce
  n'est pas décoratif : NKCode y écrit réellement `compile_commands.json`,
  `session.nk`, `ui.cfg` et `last_build_fail.log`.

  **Rien n'est retiré à VSCode.** Un espace qui a déjà un `.vscode/` continue
  d'être configuré ; celui qui n'en a pas encore le demande une fois, par
  `jenga ide-setup --editor vscode`. *Un opt-in explicite vaut mieux qu'un
  dossier apparu tout seul.*

  Vérifié par quatre cas, dont un d'anti-régression — sans lui on prouverait
  seulement qu'on a désactivé quelque chose :

  | cas | `.vscode/` | `pyrightconfig.json` |
  |---|---|---|
  | espace vierge, aucun marqueur | non | oui |
  | espace avec `.nkcode/` | non | oui |
  | espace avec `.vscode/` déjà là | **oui** | oui |
  | `ide-setup --editor vscode` | **oui** | — |

  ⚠️ **Et la contre-épreuve a été faite** : le défaut réinjecté, le premier cas
  repasse à `.vscode/` créé. Un banc qui n'a jamais rougi est une intention, pas
  un contrôle.

### Limites connues

- **Jenga perd ici son seul exemple à grande échelle**, et c'est mesuré :
  l'exemple retiré comptait **35 fichiers `.jenga` et 1 226 fichiers source** ;
  le plus gros restant, `27_nk_window`, en compte **2 et 135**. Aucun exemple
  restant ne démontre la composition multi-`.jenga` par `include()` à cette
  échelle. Le remplacer — ou pointer vers le dépôt Nkentseu public — reste à
  décider.
- Le contenu retiré (arborescence de mars 2026, `Modules/Runtime/`, plus 431
  entrées modifiées non commitées) a été **archivé avant la coupe**, hors dépôt.
- **Ré-ajouter un jour un exemple Nkentseu suppose de vérifier d'abord que le
  commit visé déclare ses propres sous-modules.** C'est exactement ce qui
  manquait ici, et un `.gitmodules` correct côté Jenga ne suffit pas à s'en
  prémunir.

## v2.3.0

> ⚠️ Ce fichier saute de `v2.0.5` à `v2.3.0` : les versions intermédiaires n'y
> ont pas été consignées. L'entrée ci-dessous ne couvre donc **que** ce qui est
> décrit, pas l'écart.

### Ajouté

- **`jenga build --keep-going` / `-k`** — construit tout ce qui peut l'être au
  lieu de s'arrêter à la première cible en échec, et distingue **quatre états**
  dans le compte-rendu final : *réussie*, *échouée* (avec son nom), **sautée**
  (non tentée, une dépendance a échoué) et *non atteinte*.
  - **« Sautée » est la catégorie utile** : elle sépare « cassé » de « bloqué
    par autre chose ». Une cible bloquée n'est **pas tentée** — la tenter
    produit une erreur *dérivée* (`no such file or directory` sur une archive
    absente) qui ressemble à un second défaut et fait réparer deux fois le même.
  - Relayé jusqu'au bout : `jenga rebuild -k`, chemin **daemon**, et événement
    structuré `OnProjectSkipped(project, blocker)` pour les hôtes embarqués.
- **`jenga build --tests`** — inclut les cibles de test dans le build du
  workspace, d'où elles sont désormais exclues par défaut (voir ci-dessous).

### Modifié

- **Une cible de test est une RACINE, jamais une dépendance.** Les cibles de
  test sont **exclues du build sans `--target`** : mesuré sur un workspace réel
  de 272 cibles, 66 étaient des tests — **24 %** de travail non demandé. Les
  nommer explicitement (`--target X_Tests`, `jenga test`) les construit
  toujours. Le cadre `__Unitest__` devenu orphelin est élagué avec elles
  (condition « plus aucun dépendant » vérifiée, pas supposée).
- **`Projects Built` ne compte plus que les réussites.** Le compteur
  s'incrémentait **même en échec** : le pied de page annonçait « 1/5 » là où
  zéro cible avait abouti. Les chiffres d'avancement lus dans ce pied de page
  **surestimaient**. Nouvelle ligne `Not reached` pour les cibles jamais
  atteintes après un arrêt.

### Corrigé

- **`dependson()` vers une cible de test lève désormais une erreur** nommant
  l'arête fautive. La propriété était vraie par accident d'usage — rien ne
  l'imposait.

### Changement de comportement

- **`--verbose` ne poursuit plus après un échec.** C'était un `--keep-going`
  accidentel (`if not self.verbose: break`), non documenté et à la mauvaise
  sémantique : il *tentait* les cibles bloquées. Un drapeau de verbosité ne
  décide pas de la politique d'échec. Utiliser `--keep-going`.

### Limites connues

- L'empaquetage **APK (Android)** et **HAP (HarmonyOS)** n'honore pas
  `--keep-going` : ces builders redéfinissent `Build()` et ne délèguent à la
  boucle générique que la phase de compilation. Constat de **lecture du code**,
  non mesuré sur émulateur.

## v2.0.5

### Ajouté

- **`useconfig(*chemins)`** — config partagée au niveau workspace. Charge un ou
  plusieurs fichiers de config (de simples `.jenga` ne contenant que des
  définitions : constantes, classes, fonctions) et **propage leurs symboles** au
  workspace **et à tous les `.jenga` inclus via `include(...)`**, sans aucun
  `import`. Permet des fichiers `.jenga` de module beaucoup plus propres (plus de
  `from Jenga import *` ni `from config import *` répétés dans chaque module).
  - Le fichier de config peut vivre dans un **sous-dossier** (chemin explicite) et
    n'a **pas besoin** de `from Jenga import *` (l'API Jenga y est injectée).
  - **Multi-fichiers** : `useconfig("a.jenga", "b.jenga")` (les derniers
    surchargent). Constantes, classes et fonctions sont toutes propagées.
  - Additif et rétro-compatible : l'ancien `from config import *` continue de
    fonctionner. Implémentation : `Jenga/Core/Api.py` (`useconfig`) au-dessus de
    la propagation `_workspaceGlobals` (`Jenga/Core/Loader.py`).
  - Doc : [DSL-Reference](https://github.com/RihenUniverse/Jenga/wiki/DSL-Reference#config-partagée--useconfig) ·
    exemple : `Jenga/Exemples/12_external_includes`.

## v2.0.4

### Ajouté

- **Installateur self-extracting MAISON** (`Jenga/Tools/Installer/`) — alternative
  intégrée à Inno Setup / WiX, sans dépendance externe :
  - Stub C portable (`Stub/Installer.c`) + payload (manifeste + archive) + trailer
    80 octets avec **SHA-256 anti-tampering** (vérifié AVANT extraction).
  - Builder Python (`Builder.py`) : compile le stub, assemble le payload.
  - **Anti-faux-positifs antivirus** (`Resource.py`) : VERSIONINFO (éditeur
    Rihen, version, description, copyright) + **manifeste UAC `asInvoker`**
    (compatibilité OS Win7→Win11, DPI aware) embarqués dans le PE Windows.
  - **Signature de code multi-plateforme** (`Signing.py`) : Authenticode
    (`signtool`) sur Windows, `codesign` sur macOS, signature détachée GPG
    sur Linux. Skip propre sans certificat (warning, pas erreur).
  - **Icône composée** (`Branding.py`) : icône user + petit "Jenga" incrusté
    en bas à droite sur le stub Setup.exe (les raccourcis user gardent l'icône
    propre). Pillow soft-dep avec dégradation gracieuse.
  - Raccourcis Windows (`.lnk` via COM/IShellLink), Linux (`.desktop`),
    entrée Programmes et fonctionnalités (registre Uninstall HKCU),
    règles pare-feu via `FirewallSpec`.
  - Intégré à `jenga package --type jng` (Windows/Linux/macOS) sans
    remplacer msi/exe/zip/deb/pkg.
- **DSL signature** (8 fonctions, `Jenga/Core/Api.py`) : `signingcertificate(path)`,
  `signingpassword(pwd)`, `signingthumbprint(hex)`, `signingidentity(name)`,
  `signingtimestampurl(url)`, `signinggpgkey(id)`, `signingentitlements(path)`,
  `signingrequireadmin(bool)`.
- **Résumé final des warnings/erreurs de build** (`Jenga/Utils/Reporter.py`) :
  `Reporter.PrintCollectedSummary()` affiche un encadré rouge/jaune après
  "BUILD COMPLETED" listant **tous** les warnings et erreurs émis pendant
  le build — fini les warnings critiques noyés dans 1000 lignes de logs.
  Nouveau flag `Reporter.Warning(..., critical=True)` pour les warnings
  bloquants fonctionnellement (ex. APK non signable).

### Corrigé

- **Sessions Windows aveugles aux `setx`** (`Jenga/_envbackfill.py`) : à
  `import Jenga`, hydrate `os.environ` depuis `HKCU\\Environment` puis
  `HKLM\\…\\Environment` pour `ANDROID_*`, `JAVA_HOME`, `EMSDK`, `OHOS_SDK`,
  `GameDK`, `ZIG_ROOT`. Plus besoin de redémarrer le terminal après un
  `setx`/Paramètres Système. No-op sur Unix.
- **`AndroidBuilder` retournait 0 silencieusement pour une cible lib**
  (`Jenga/Core/Builders/Android.py`) : cibler une `StaticLib`/`SharedLib`
  pour Android (`jenga build --platform android --target NKWindow`) ne
  faisait rien et sortait avec succès. Le builder délègue maintenant à
  `super().Build()` pour compiler la lib + sa chaîne de deps via
  `DependencyResolver`, avec message clair. Idem sans target et sans app
  déclaré dans le workspace.
- **Target introuvable peu visible** (`Jenga/Core/Builder.py`) : `Build()`
  attrape maintenant `ValueError` (en plus de `RuntimeError`) levé par
  `DependencyResolver.ResolveBuildOrder` et affiche la liste des projets
  disponibles.
- **Warning keystore Android escalé en `critical=True`** : remonte dans le
  résumé final en rouge (impossible à manquer même au milieu de logs).

## v2.0.3

### Corrigé
- **Génération des `.jenga` cassée** : `jenga project` écrivait le bloc
  `with project(...)` **sans indentation** (donc hors du `with workspace(...)`)
  et répétait le shebang `#!/usr/bin/env python3` à chaque projet. Le workspace
  généré était sémantiquement invalide (projets non rattachés). Le bloc est
  désormais correctement indenté **dans** le workspace, sans shebang dupliqué.
- Mode interactif : la bannière s'affichait **deux fois** → une seule.
- Mode interactif : l'aperçu de structure reflète la **vraie** arborescence
  (le projet vit dans `<workspace>/<projet>/`, plus de `src/`/`include/` à la racine).

### Ajouté
- `jenga workspace <nom>` crée le workspace dans un **dossier à son nom**
  (`<nom>/<nom>.jenga`), pour que les projets créés ensuite tombent dans
  `<workspace>/<projet>` (ex. `lou/bob`). `--path` devient le dossier parent.
- **Projet inline ou fichier `.jenga` séparé** : `jenga project <nom> --separate`
  (ou la question en mode interactif) crée le projet dans son propre `.jenga`,
  rattaché au workspace via `with include(...)`. Par défaut, le projet reste
  inline dans le `.jenga` du workspace.
- Fichiers de **coloration IDE** (`.vscode/settings.json`, `pyrightconfig.json`)
  générés **dès la création** du workspace (comme au premier `jenga build`).
- **`.gitignore`** généré à la création : exclut les fichiers IDE (qui
  contiennent un `extraPaths` absolu, machine-spécifique), `Build/` et les caches.

### Notes
- Le projet n'est créable **que dans un workspace** ; `jenga project` peut être
  lancé depuis la racine du workspace **ou un sous-dossier** (remontée auto vers
  le `.jenga`).

## v2.0.2

- Réseau/pare-feu **multi-plateforme** à l'installation (Windows `netsh`,
  macOS `socketfilterfw`, Linux `ufw`/`firewalld`/`iptables`, Android, iOS,
  HarmonyOS) via `Core/FirewallSpec.py` + DSL (`networkenabled`, `firewallrule`,
  `bonjourservices`, …).
- **Version centralisée** dans `Jenga/_version.py` (source unique).
- **Éditeur = Rihen** par défaut (installeurs MSI/Inno/DEB, métadonnées).
- HarmonyOS, documentation/wiki bilingue, nettoyage du dépôt.
