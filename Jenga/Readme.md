# Jenga — Package Python

Ce répertoire contient le **package Python `Jenga`**, le cœur du système de build.
Il expose l'API DSL, les commandes CLI, le moteur de build, les utilitaires et le
framework de tests unitaires C++.

> 📖 Pour l'usage **utilisateur** (installation, premiers pas, commandes), voir le
> [README racine](../README.md) et le [Wiki (FR / EN)](https://github.com/Rihen-Universe/Jenga/wiki).
> Cette page s'adresse aux **développeurs/contributeurs** du package.

---

## 🧱 Structure du package

```
Jenga/
├── __init__.py            # API publique réexportée
├── _version.py            # Source unique : version (2.0.2) + éditeur (Rihen)
├── Jenga.py               # Point d'entrée CLI (console_script)
├── Commands/              # Implémentation des commandes CLI (build, run, package…)
├── Core/
│   ├── Api.py             # DSL : context managers, énumérations, dataclasses
│   ├── Builder.py         # Moteur de build + cache incrémental
│   ├── FirewallSpec.py    # Génération des règles réseau/pare-feu multi-plateformes
│   ├── Loader.py / Cache.py / Daemon.py / Variables.py …
│   └── Builders/          # Un builder par plateforme (Windows, Linux, Android…)
├── Unitest/               # Framework de tests C++ (sources + binaires)
├── Utils/                 # Utilitaires transverses (console, fs, process, UI)
└── Docs/                  # Guides, ROADMAP, sources du wiki
```

Le package est installable via `pip` et fournit le point d'entrée `jenga`.

---

## 📦 Installation (développement)

```bash
# Depuis la racine du dépôt
pip install -e .

jenga --version    # -> 2.0.2
```

Dépendances minimales (voir `pyproject.toml`) : `watchdog` (pour `jenga watch`),
`colorama` (Windows), `requests` (commandes `publish`, optionnel).

---

## 🐍 Utilisation comme bibliothèque

L'API exposée dans `__init__.py` est identique à celle de `Core/Api.py`. On peut
manipuler workspaces, projets et toolchains par programmation :

```python
from Jenga import workspace, project, consoleapp, files
from Jenga.Utils import Colored

with workspace("MonWorkspace"):
    with project("MonProjet"):
        consoleapp()
        files(["src/**.cpp"])
        Colored.PrintSuccess("Projet configuré")
```

---

## 🧩 Modules principaux

| Module | Description | Doc |
|--------|-------------|-----|
| `Core/Api.py` | DSL : workspace, project, toolchain, filter, réseau… | — |
| `Commands/` | Toutes les commandes CLI | [Readme](./Commands/Readme.md) |
| `Core/` | Moteur : Loader, Cache, Builder, Daemon, Variables | [Readme](./Core/Readme.md) |
| `Core/Builders/` | Implémentations par plateforme | [Readme](./Core/Builders/Readme.md) |
| `Core/FirewallSpec.py` | Règles réseau/pare-feu (netsh, socketfilterfw, ufw…) | [wiki](https://github.com/Rihen-Universe/Jenga/wiki/Reseau-et-Pare-feu) |
| `Unitest/` | Framework de tests unitaires C++ | [Readme](./Unitest/Readme.md) |
| `Utils/` | Console colorée, fichiers, processus, rapports | [Readme](./Utils/Readme.md) |

---

## 🏷️ Versionnage & métadonnées

La version et l'éditeur sont centralisés dans **`_version.py`** (source unique de
vérité). Tout le reste les lit : `__init__.py`, `pyproject.toml`, les commandes,
les scripts et la CI. **Pour changer la version, ne modifier que ce fichier.**

```python
# Jenga/_version.py
__version__   = "2.0.2"
__author__    = "Rihen"     # Rihen édite Jenga
__publisher__ = "Rihen"
__email__     = "rihen.universe@gmail.com"
```

---

## 🤝 Contribuer

1. `pip install -e .` (mode développement).
2. Respecter les **conventions de nommage** :
   - `PascalCase` : classes, méthodes publiques, énumérations
   - `_PascalCase` : méthodes privées
   - `lower` : fonctions DSL utilisateur (un seul mot, sans `_`)
   - `_camelCase` : attributs privés/protégés ; `UPPER_SNAKE_CASE` : constantes
3. Tester les modifications (`python -m pytest tests/ -v`).
4. Documenter toute nouvelle fonctionnalité dans le README / wiki approprié.

---

## 🔗 Liens

- [README racine](../README.md) — vue d'ensemble & démarrage
- [Roadmap](./Docs/ROADMAP.md) — fait / en cours / à faire
- [Wiki (FR / EN)](https://github.com/Rihen-Universe/Jenga/wiki) — documentation complète
- [Sources du wiki](./Docs/wiki/) · [Guide complet](./Docs/GUIDE_COMPLET_JENGA.md)

---

## 📄 Licence & éditeur

**Jenga** est un produit développé et maintenu par **Rihen** (<rihen.universe@gmail.com>).
Licence **propriétaire** — voir [`LICENSE`](../LICENSE).
