#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Help command – Affiche l'aide générale ou l'aide d'une commande spécifique.
"""

import argparse
import sys
from typing import List

# ⚠️ IMPORTER DEPUIS registry, PAS depuis . (__init__)
from .Registry import COMMANDS, ALIASES, get_command_class
from .. import __version__


class HelpCommand:
    """jenga help [COMMAND]"""

    @staticmethod
    def Execute(args: List[str]) -> int:
        parser = argparse.ArgumentParser(prog="jenga help", description="Show help for a command.")
        parser.add_argument("command", nargs="?", help="Command name")
        parsed = parser.parse_args(args)

        if parsed.command:
            return HelpCommand._ShowCommandHelp(parsed.command)
        else:
            HelpCommand._ShowGlobalHelp()
            return 0

    @staticmethod
    def _ShowGlobalHelp():
        """Affiche l'aide générale."""
        print(f"Jenga Build System v{__version__}")
        print("Usage: Jenga <command> [options]")
        print("\nCommandes principales :")
        cmds = [
            ("build, b", "Compile le workspace ou un projet"),
            ("run, r", "Exécute un projet"),
            ("test, t", "Lance les tests unitaires"),
            ("clean, c", "Supprime les fichiers générés"),
            ("rebuild", "Nettoie et compile"),
            ("watch, w", "Surveille les fichiers et rebuild automatiquement"),
            ("info, i", "Affiche les informations du workspace"),
            ("gen", "Génère des fichiers projet (CMake, VS, Makefile)"),
            ("workspace, init", "Crée un nouveau workspace"),
            ("project, create", "Crée un nouveau projet"),
            ("file, add", "Ajoute des fichiers/dépendances à un projet"),
            ("install", "Installe dépendances et toolchains locales"),
            ("kit", "Extrait un kit redistribuable (en-tetes + libs construites)"),
            ("keygen", "Génère une keystore Android"),
            ("sign", "Signe un APK ou IPA"),
            ("docs", "Génère la documentation du projet"),
            ("package", "Crée des packages distribuables"),
            ("deploy", "Déploie l'application sur un appareil"),
            ("publish", "Publie un package sur un registre"),
            ("profile", "Lance un profilage de performance"),
            ("bench", "Exécute des benchmarks"),
            ("help, h", "Affiche cette aide"),
        ]
        for cmd, desc in cmds:
            print(f"  {cmd:<20} {desc}")

        print("\nPour plus d'aide sur une commande : Jenga help <commande>")
        print("\nAlias disponibles :")
        for alias, target in sorted(ALIASES.items()):
            print(f"  {alias} -> {target}")
        print(f"\nVersion: {__version__}")

    @staticmethod
    def _ShowCommandHelp(command: str):
        """Affiche l'aide d'une commande spécifique."""
        cmd_class = get_command_class(command)
        if not cmd_class:
            print(f"jenga: unknown command '{command}'", file=sys.stderr)
            return 1

        try:
            cmd_class.Execute(["--help"])
        except SystemExit:
            pass
        return 0
