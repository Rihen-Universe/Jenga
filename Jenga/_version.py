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
__version__ = "2.0.3"

# Éditeur / entreprise. Rihen édite Jenga. Utilisé comme valeur par défaut
# du publisher des installeurs (Manufacturer MSI, AppPublisher Inno, Maintainer
# DEB) quand le développeur ne fournit pas apppublisher() dans son .jenga.
__author__ = "Rihen"
__publisher__ = "Rihen"
__email__ = "rihen.universe@gmail.com"
