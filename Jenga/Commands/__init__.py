#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Jenga.Commands – Ensemble des commandes CLI disponibles.
Ce module initialise le registre des commandes et expose l'interface publique.
"""

# Importer d'abord le registre, puis les commandes
from .Registry import COMMANDS, ALIASES, get_command_class, execute_command

# Import de toutes les commandes (les classes sont enregistrées dans COMMANDS au fur et à mesure)
from .Build import BuildCommand
from .Run import RunCommand
from .Gdb import GdbCommand
from .Test import TestCommand
from .Clean import CleanCommand
from .Rebuild import RebuildCommand
from .Watch import WatchCommand
from .Info import InfoCommand
from .Gen import GenCommand
from .Init import InitCommand
from .Create import CreateCommand
from .Add import AddCommand
from .Install import InstallCommand
from .Keygen import KeygenCommand
from .Sign import SignCommand
from .Docs import DocsCommand
from .Help import HelpCommand
from .Package import PackageCommand
from .Deploy import DeployCommand
from .Publish import PublishCommand
from .Profile import ProfileCommand
from .Bench import BenchCommand
from .Config import ConfigCommand
from .Examples import ExamplesCommand
from .IdeSetup import IdeSetupCommand
from .CompileFlags import CompileFlagsCommand

# Enregistrement des commandes
COMMANDS.update({
    'compile-flags': CompileFlagsCommand,   # flags de compilation (JSON) pour diagnostics IDE
    'build': BuildCommand,
    'run': RunCommand,
    'gdb': GdbCommand,
    'debug': GdbCommand,        # alias
    'test': TestCommand,
    'clean': CleanCommand,
    'rebuild': RebuildCommand,
    'watch': WatchCommand,
    'info': InfoCommand,
    'gen': GenCommand,
    'workspace': InitCommand,   # alias
    'init': InitCommand,
    'project': CreateCommand,   # alias
    'create': CreateCommand,
    'file': AddCommand,         # alias
    'add': AddCommand,
    'install': InstallCommand,
    'keygen': KeygenCommand,
    'sign': SignCommand,
    'docs': DocsCommand,
    'package': PackageCommand,
    'deploy': DeployCommand,
    'publish': PublishCommand,
    'profile': ProfileCommand,
    'bench': BenchCommand,
    'config': ConfigCommand,
    'examples': ExamplesCommand,
    'ide-setup': IdeSetupCommand,
    'ide': IdeSetupCommand,         # alias court
    'help': HelpCommand,
})

# Enregistrement des alias courts
ALIASES.update({
    'b': 'build',
    'r': 'run',
    'g': 'gdb',
    't': 'test',
    'c': 'clean',
    'w': 'watch',
    'i': 'info',
    'init': 'workspace',
    'create': 'project',
    'add': 'file',
    'k': 'keygen',
    's': 'sign',
    'd': 'docs',
    'e': 'examples',
    'h': 'help',
})

__all__ = [
    'COMMANDS', 'ALIASES', 'get_command_class', 'execute_command',
    'BuildCommand', 'RunCommand', 'TestCommand', 'CleanCommand',
    'RebuildCommand', 'WatchCommand', 'InfoCommand', 'GenCommand',
    'InitCommand', 'CreateCommand', 'AddCommand', 'InstallCommand',
    'KeygenCommand', 'SignCommand', 'DocsCommand', 'HelpCommand',
    'PackageCommand', 'DeployCommand', 'PublishCommand',
    'ProfileCommand', 'BenchCommand', 'ConfigCommand', 'ExamplesCommand',
    'IdeSetupCommand',
]
