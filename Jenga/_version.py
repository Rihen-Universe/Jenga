#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Source UNIQUE de vérité des métadonnées du package Jenga.

Modèle éditeur → produit :
  - **Rihen** est l'entreprise / l'éditeur (PUBLISHER / AUTHOR).
  - **Jenga** est l'un de ses produits (le nom du logiciel de build).

⚠️ Pour changer la version OU l'éditeur, ne modifier QUE ce fichier. Tout le
reste lit ces valeurs :
  - Jenga/__init__.py        (réexporte __version__, __author__)
  - pyproject.toml           ([tool.setuptools.dynamic] version = attr Jenga._version.__version__)
  - Jenga/Commands/Info.py, Core/Daemon.py, Core/Variables.py,
    Core/JengaConfig.py, Utils/Display.py, Core/IDEConfigurator.py  (import)
  - Jenga/Commands/Package.py (éditeur par défaut des installeurs MSI/EXE/DEB)
  - scripts/build_examples_archive.py, .github/workflows/release.yml
    (lisent ce fichier par parsing)

Ce module est volontairement minimal et SANS import : il peut être lu très
tôt et par n'importe quel sous-module sans risque d'import circulaire.
"""

# Version du produit Jenga.
# 2.2.0 (2026-08-11) : frameworks() Apple par PROJET et par FILTRE (avant :
# toolchain seulement, perdus en silence au niveau projet) + builder iOS
# direct réparé (init _GetMinimumVersion, packaging Info.plist) — première
# chaîne complète compile+link+bundle iOS/macOS prouvée en CI GitHub Actions.
# 2.5.0 (2026-09-04) : dutc/dute acceptent une liste blanche `allow=[...]`
# (politique de tests par PROJET) et --force traverse jusqu'au Builder
# (jenga test/run --force, jenga build --force-tests).
# 2.6.0 (2026-09-04) : le runner de test/run met le bin de la chaine en tete
# du PATH et DIT un binaire qui n'a pas demarre (DLL manquante, 127) ;
# testownmain() — la suite fournit son main, deux main() sont refuses.
# 2.6.1 (2026-09-04) : test() rend le projet courant (plusieurs suites par
# projet, les mots apres le bloc s'appliquent au parent) ; un mot du DSL hors
# de sa portee se refuse en nommant le mot et la ligne.
# 2.6.2 (2026-09-04) : `%{Projet.location}` se resout sous `with filter(...)`
# (formes filtrees expansees au chargement, ResolveProjectPath expanse avant
# de resoudre) et lit une location absolue en espace mono-fichier.
# 2.6.3 (2026-09-08) : `jenga kit` extrait un kit redistribuable d'un
# workspace (fermeture transitive des modules, en-tetes publics,
# bibliotheques construites, fichier de configuration charge par
# useconfig()) ; l'evaluateur de filtres traite &&, || et ! -- sans quoi
# un kit Windows sortait sans user32 ni gdi32.
# 2.7.0 (2026-09-10) : binaires universels Apple. `macosarchs([...])` et
# `iosarchs([...])` compilent une fois PAR architecture puis assemblent avec
# `lipo` — equivalent Apple de androidabis/harmonyabis. Sans eux, un
# executable macOS ne tournait que sur la moitie du parc, Apple Silicon OU
# Intel. Corrige au passage un defaut latent : l'edition de liens macOS ne
# recevait pas `-arch`, ce qui ne se voyait que le jour ou l'on croise les
# architectures. La chaine d'outils HarmonyOS s'enregistre desormais toute
# seule apres `jenga install harmony-sdk` (la branche installait le SDK sans
# jamais appeler `_UpsertToolchains`, donc aucune construction HarmonyOS ne
# demarrait). `jenga kit` emporte les dossiers de bibliotheques externes au
# workspace.
# 2.8.0 (2026-09-10) : signature des applications de BUREAU. Android et iOS
# avaient la leur, Windows/macOS/Linux non, et cela se payait : Defender met en
# quarantaine les executables sans auteur connu. windowssign(),
# macossign()+macosnotaryprofile(), linuxsign() ; `jenga sign --platform <os>
# --file A --file B`. Les trois systemes ne font PAS la meme chose : Windows et
# macOS ecrivent la signature dans le fichier, Linux n'a aucun equivalent ELF
# et publie des signatures detachees .asc plus un SHA256SUMS. Les secrets
# viennent de JENGA_WINDOWS_CERT_PASSWORD et JENGA_GPG_PASSPHRASE, jamais du
# .jenga, et rien de secret n'est journalise.
__version__ = "2.8.0"

# Éditeur / entreprise. Rihen édite Jenga. Utilisé comme valeur par défaut
# du publisher des installeurs (Manufacturer MSI, AppPublisher Inno, Maintainer
# DEB) quand le développeur ne fournit pas apppublisher() dans son .jenga.
__author__ = "Rihen"
__publisher__ = "Rihen"
__email__ = "rihen.universe@gmail.com"
