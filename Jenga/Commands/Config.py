#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Commande 'jenga config' - Gestion de la configuration globale Jenga.
"""

import argparse
import json
from pathlib import Path
from typing import Optional

from ..Core.JengaConfig import GetGlobalConfig
from ..Utils import Colored


class ConfigCommand:
    """
    Commandes de configuration Jenga.

    jenga config init                 - Initialise la configuration
    jenga config show                 - Affiche la configuration
    jenga config set <key> <value>    - Définit une valeur
    jenga config get <key>            - Récupère une valeur

    jenga config toolchain add <name> <file>    - Ajoute un toolchain
    jenga config toolchain list                 - Liste les toolchains
    jenga config toolchain remove <name>        - Supprime un toolchain

    jenga config sysroot add <name> <path>      - Enregistre un sysroot
    jenga config sysroot list                   - Liste les sysroots
    jenga config sysroot remove <name>          - Supprime un sysroot
    """

    @staticmethod
    def Execute(args: list) -> int:
        """Point d'entrée de la commande."""
        parser = argparse.ArgumentParser(
            prog="jenga config",
            description="Gestion de la configuration globale Jenga"
        )

        subparsers = parser.add_subparsers(dest='subcommand', help='Sous-commandes')

        # jenga config init
        subparsers.add_parser('init', help='Initialise la configuration')

        # jenga config show
        subparsers.add_parser('show', help='Affiche la configuration')

        # jenga config set
        set_parser = subparsers.add_parser('set', help='Définit une valeur')
        set_parser.add_argument('key', help='Clé de configuration')
        set_parser.add_argument('value', help='Valeur')

        # jenga config get
        get_parser = subparsers.add_parser('get', help='Récupère une valeur')
        get_parser.add_argument('key', help='Clé de configuration')

        # jenga config toolchain
        toolchain_parser = subparsers.add_parser('toolchain', help='Gestion des toolchains')
        toolchain_sub = toolchain_parser.add_subparsers(dest='toolchain_cmd')

        toolchain_add = toolchain_sub.add_parser('add', help='Ajoute un toolchain')
        toolchain_add.add_argument('name', help='Nom du toolchain')
        toolchain_add.add_argument('file', help='Fichier JSON du toolchain')

        toolchain_sub.add_parser('list', help='Liste les toolchains')

        toolchain_remove = toolchain_sub.add_parser('remove', help='Supprime un toolchain')
        toolchain_remove.add_argument('name', help='Nom du toolchain')

        # jenga config sysroot
        sysroot_parser = subparsers.add_parser('sysroot', help='Gestion des sysroots')
        sysroot_sub = sysroot_parser.add_subparsers(dest='sysroot_cmd')

        sysroot_add = sysroot_sub.add_parser('add', help='Enregistre un sysroot')
        sysroot_add.add_argument('name', help='Nom du sysroot')
        sysroot_add.add_argument('path', help='Chemin du sysroot')
        sysroot_add.add_argument('--os', default='Linux', help='OS cible')
        sysroot_add.add_argument('--arch', default='x86_64', help='Architecture cible')

        sysroot_sub.add_parser('list', help='Liste les sysroots')

        sysroot_remove = sysroot_sub.add_parser('remove', help='Supprime un sysroot')
        sysroot_remove.add_argument('name', help='Nom du sysroot')

        if not args:
            parser.print_help()
            return 0

        parsed = parser.parse_args(args)

        if parsed.subcommand == 'init':
            return ConfigCommand._Init()
        elif parsed.subcommand == 'show':
            return ConfigCommand._Show()
        elif parsed.subcommand == 'set':
            return ConfigCommand._Set(parsed.key, parsed.value)
        elif parsed.subcommand == 'get':
            return ConfigCommand._Get(parsed.key)
        elif parsed.subcommand == 'toolchain':
            return ConfigCommand._Toolchain(parsed)
        elif parsed.subcommand == 'sysroot':
            return ConfigCommand._Sysroot(parsed)
        else:
            parser.print_help()
            return 0

    @staticmethod
    def _Init() -> int:
        """Initialise la configuration."""
        config = GetGlobalConfig()
        Colored.PrintSuccess(f"Configuration initialisée dans : {config.config_dir}")
        Colored.PrintInfo("Structure créée :")
        print(f"  - Toolchains: {config.config_dir / 'toolchains'}")
        print(f"  - Sysroots:   {config.config_dir / 'sysroots'}")
        print(f"  - Cache:      {config.cache_dir}")
        print(f"  - Logs:       {config.logs_dir}")
        return 0

    @staticmethod
    def _Show() -> int:
        """Affiche la configuration."""
        config = GetGlobalConfig()
        Colored.PrintInfo("Configuration Jenga :")
        print(f"\nRépertoire : {config.config_dir}")
        print(f"\nToolchains enregistrés : {len(config.ListToolchains())}")
        for tc in config.ListToolchains():
            print(f"  - {tc}")

        print(f"\nSysroots enregistrés : {len(config.ListSysroots())}")
        for sr in config.ListSysroots():
            info = config.GetSysroot(sr)
            if info:
                print(f"  - {sr} ({info.get('target_os')}/{info.get('target_arch')})")

        print(f"\nParamètres :")
        print(f"  Cache global:     {config.Get('global_cache_enabled')}")
        print(f"  Jobs parallèles:  {config.Get('max_parallel_jobs')}")
        print(f"  Erreurs verbose:  {config.Get('verbose_errors')}")
        print(f"  Auto-découverte:  {config.Get('auto_discover_toolchains')}")

        return 0

    @staticmethod
    def _Set(key: str, value: str) -> int:
        """Définit une valeur."""
        config = GetGlobalConfig()

        # Conversion automatique des types
        if value.lower() in ('true', 'false'):
            value = value.lower() == 'true'
        elif value.isdigit():
            value = int(value)

        if config.Set(key, value):
            Colored.PrintSuccess(f"Configuration mise à jour : {key} = {value}")
            return 0
        else:
            Colored.PrintError(f"Erreur lors de la mise à jour de {key}")
            return 1

    @staticmethod
    def _Get(key: str) -> int:
        """Récupère une valeur."""
        config = GetGlobalConfig()
        value = config.Get(key)
        if value is not None:
            print(f"{key} = {value}")
            return 0
        else:
            Colored.PrintWarning(f"Clé non trouvée : {key}")
            return 1

    @staticmethod
    def _Toolchain(parsed) -> int:
        """Gestion des toolchains."""
        config = GetGlobalConfig()

        if parsed.toolchain_cmd == 'add':
            # Charger le fichier JSON
            toolchain_file = Path(parsed.file)
            if not toolchain_file.exists():
                Colored.PrintError(f"Fichier non trouvé : {toolchain_file}")
                return 1

            try:
                # 'utf-8-sig' et non le codec par défaut de la plateforme :
                #  - sans `encoding`, Windows lit en cp1252 -> un chemin de
                #    compilateur accentué (« C:/Users/José/... ») échouait ;
                #  - '-sig' avale un éventuel BOM UTF-8, que produisent Notepad
                #    et `Out-File -Encoding utf8` (PowerShell 5.1). Un JSON écrit
                #    à la main sous Windows partait sinon en
                #    « Expecting value: line 1 column 1 (char 0) ».
                with open(toolchain_file, 'r', encoding='utf-8-sig') as f:
                    toolchain_data = json.load(f)

                if config.RegisterToolchain(parsed.name, toolchain_data):
                    Colored.PrintSuccess(f"Toolchain '{parsed.name}' enregistré")
                    return 0
                else:
                    Colored.PrintError(f"Erreur lors de l'enregistrement du toolchain")
                    return 1
            except json.JSONDecodeError as e:
                # Message ACTIONNABLE : l'ancien « Erreur : Expecting value... »
                # ne disait ni quel fichier ni quoi corriger.
                Colored.PrintError(f"JSON invalide dans {toolchain_file} (ligne {e.lineno}, colonne {e.colno}) : {e.msg}")
                return 1
            except Exception as e:
                Colored.PrintError(f"Erreur en lisant {toolchain_file} : {e}")
                return 1

        elif parsed.toolchain_cmd == 'list':
            toolchains = config.ListToolchains()
            if toolchains:
                Colored.PrintInfo("Toolchains enregistrés :")
                for tc in toolchains:
                    data = config.GetToolchain(tc)
                    if data:
                        tc_type = data.get('type', 'unknown')
                        target = data.get('target', {})
                        target_str = f"{target.get('os', '?')}/{target.get('arch', '?')}"
                        print(f"  - {tc} ({tc_type}, {target_str})")
            else:
                Colored.PrintWarning("Aucun toolchain enregistré")
            return 0

        elif parsed.toolchain_cmd == 'remove':
            if config.RemoveToolchain(parsed.name):
                Colored.PrintSuccess(f"Toolchain '{parsed.name}' supprimé")
                return 0
            else:
                Colored.PrintError(f"Erreur lors de la suppression du toolchain")
                return 1

        return 0

    @staticmethod
    def _Sysroot(parsed) -> int:
        """Gestion des sysroots."""
        config = GetGlobalConfig()

        if parsed.sysroot_cmd == 'add':
            sysroot_path = Path(parsed.path)
            if not sysroot_path.exists():
                Colored.PrintError(f"Chemin non trouvé : {sysroot_path}")
                return 1

            if config.RegisterSysroot(parsed.name, str(sysroot_path), parsed.os, parsed.arch):
                Colored.PrintSuccess(f"Sysroot '{parsed.name}' enregistré")
                print(f"  Chemin: {sysroot_path.absolute()}")
                print(f"  Cible:  {parsed.os}/{parsed.arch}")
                return 0
            else:
                Colored.PrintError(f"Erreur lors de l'enregistrement du sysroot")
                return 1

        elif parsed.sysroot_cmd == 'list':
            sysroots = config.ListSysroots()
            if sysroots:
                Colored.PrintInfo("Sysroots enregistrés :")
                for sr in sysroots:
                    data = config.GetSysroot(sr)
                    if data:
                        print(f"  - {sr}")
                        print(f"      Chemin: {data.get('path')}")
                        print(f"      Cible:  {data.get('target_os')}/{data.get('target_arch')}")
            else:
                Colored.PrintWarning("Aucun sysroot enregistré")
            return 0

        elif parsed.sysroot_cmd == 'remove':
            if config.RemoveSysroot(parsed.name):
                Colored.PrintSuccess(f"Sysroot '{parsed.name}' supprimé (fichiers conservés)")
                return 0
            else:
                Colored.PrintError(f"Erreur lors de la suppression du sysroot")
                return 1

        return 0
