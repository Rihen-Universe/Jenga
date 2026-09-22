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
        # SOURCE UNIQUE : Registry.py. Cette liste et celle de Jenga.py étaient
        # recopiées l'une de l'autre et avaient divergé de cinq commandes.
        from Jenga.Commands.Registry import command_list
        cmds = command_list()
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
