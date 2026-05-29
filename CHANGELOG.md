# Changelog

Toutes les modifications notables de Jenga sont documentées ici.
Format inspiré de [Keep a Changelog](https://keepachangelog.com) ; versionnage [SemVer](https://semver.org).

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
