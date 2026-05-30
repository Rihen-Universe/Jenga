# Changelog

Toutes les modifications notables de Jenga sont documentées ici.
Format inspiré de [Keep a Changelog](https://keepachangelog.com) ; versionnage [SemVer](https://semver.org).

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
