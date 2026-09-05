#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Jenga – Point d'entrée principal de la CLI Jenga.
Syntaxe : Jenga <commande> [arguments...]

Ce script est destiné à être installé via setuptools (console_script entry point).
"""

import sys
import argparse
from pathlib import Path

# Ajouter le répertoire parent au PYTHONPATH pour les exécutions directes
if __name__ == '__main__' and __package__ is None:
    parent = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(parent))
    __package__ = 'Jenga'

from Jenga.Commands import execute_command, COMMANDS, ALIASES
from Jenga.Utils.Display import Display
from Jenga import __version__


def main():
    """Point d'entrée principal."""
    Display.PrintBanner()
    
    # Si aucun argument, afficher l'aide général
    if len(sys.argv) < 2:
        print_global_help()
        return 1

    command = sys.argv[1]
    args = sys.argv[2:]

    # Gestion des options globales avant la commande (--version, --help)
    if command in ('--version', '-v'):
        print(f"Jenga version {__version__}")
        return 0
    if command in ('--help', '-h'):
        print_global_help()
        return 0

    # Exécuter la commande
    return execute_command(command, args)


def print_global_help():
    """Affiche l'aide générale avec la liste des commandes."""
    print(f"Jenga Build System v{__version__}")
    print("Usage: Jenga <command> [options]")
    print("\nCommandes principales :")
    cmds = [
        ("build, b", "Compile le workspace ou un projet"),
        ("run, r", "Exécute un projet"),
        ("gdb, g, debug", "Débogue un projet avec GDB (ou LLDB)"),
        ("test, t", "Lance les tests unitaires"),
        ("clean, c", "Supprime les fichiers générés"),
        ("rebuild", "Nettoie et compile"),
        ("watch, w", "Surveille les fichiers et rebuild automatiquement"),
        ("info, i", "Affiche les informations du workspace"),
        ("gen", "Génère des fichiers projet (CMake, VS, Makefile)"),
        ("workspace, init", "Crée un nouveau workspace"),
        ("project, create", "Crée un nouveau projet"),
        ("file, add", "Ajoute des fichiers/dépendances à un projet"),
        ("examples, e", "Liste et copie des projets d'exemple"),
        ("install", "Installe dépendances et toolchains locales"),
        ("kit", "Extrait un kit redistribuable (en-tetes + libs construites)"),
        ("keygen", "Génère une keystore Android"),
        ("sign", "Signe un APK ou IPA"),
        ("docs", "Génère la documentation du projet"),
    ]
    for cmd, desc in cmds:
        print(f"  {cmd:<20} {desc}")

    print("\nPour plus d'aide sur une commande : Jenga <commande> --help")
    print("\nAlias disponibles :")
    alias_list = [(k, v) for k, v in ALIASES.items()]
    for alias, target in alias_list:
        print(f"  {alias} -> {target}")
    print("\nSite web: https://jenga.build")


if __name__ == '__main__':
    sys.exit(main())
