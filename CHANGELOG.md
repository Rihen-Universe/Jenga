# Changelog

Toutes les modifications notables de Jenga sont documentées ici.
Format inspiré de [Keep a Changelog](https://keepachangelog.com) ; versionnage [SemVer](https://semver.org).

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
