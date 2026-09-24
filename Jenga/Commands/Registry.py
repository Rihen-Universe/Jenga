#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Registry – Registre central des commandes CLI.
Ce module est dédié à la gestion des commandes et des alias pour éviter les imports circulaires.
Il ne doit importer aucune commande.
"""

from typing import Dict, Type, Callable, List
import sys

# Dictionnaire des commandes (sera rempli par Commands/__init__.py)
COMMANDS: Dict[str, Type] = {}

# Dictionnaire des alias (commande courte -> nom long)
ALIASES: Dict[str, str] = {}


# =============================================================================
#  LA DESCRIPTION DES COMMANDES, ECRITE UNE FOIS
#
#  Elle etait recopiee a DEUX endroits, Jenga/Jenga.py et Commands/Help.py, et
#  les deux listes ont diverge : `jenga --help` s'arretait a `docs` et ne
#  mentionnait ni `package`, ni `deploy`, ni `publish`, ni `profile`, ni
#  `bench`, tandis que `jenga help` les listait. Constate le 10 septembre 2026
#  en cherchant comment fabriquer un APK : la commande existait, repondait a
#  `--help`, et n'apparaissait dans aucune aide consultee.
#
#  Le garde-fou compte plus que la correction : command_list() compare ce
#  tableau au registre REEL et ajoute ce qui manque. Une commande nouvelle
#  apparait donc dans l'aide meme si son auteur oublie de la decrire, suivie
#  d'une mention qui l'invite a le faire. Une commande ne peut plus etre
#  invisible.
# =============================================================================
DESCRIPTIONS: Dict[str, str] = {
    "build":         "Compile le workspace ou un projet",
    "run":           "Exécute un projet",
    "gdb":           "Débogue un projet avec GDB (ou LLDB)",
    "test":          "Lance les tests unitaires",
    "clean":         "Supprime les fichiers générés",
    "rebuild":       "Nettoie et compile",
    "watch":         "Surveille les fichiers et rebuild automatiquement",
    "info":          "Affiche les informations du workspace",
    "gen":           "Génère des fichiers projet (CMake, VS, Makefile, Android.mk, Xcode, compile_commands.json)",
    "workspace":     "Crée un nouveau workspace",
    "project":       "Crée un nouveau projet",
    "file":          "Ajoute des fichiers/dépendances à un projet",
    "examples":      "Liste et copie des projets d'exemple",
    "install":       "Installe dépendances et toolchains locales",
    "kit":           "Extrait un kit redistribuable (en-tetes + libs construites)",
    "keygen":        "Génère une keystore Android",
    "sign":          "Signe un APK ou IPA",
    "package":       "Fabrique un paquet distribuable (APK, HAP, IPA, MSI...)",
    "deploy":        "Installe et lance l'application sur un appareil",
    "publish":       "Publie un paquet sur un registre",
    "profile":       "Lance un profilage de performance",
    "bench":         "Exécute des benchmarks",
    "docs":          "Génère la documentation du projet",
    "config":        "Lit et écrit la configuration de Jenga",
    "ide-setup":     "Prépare l'éditeur (complétion, typings)",
    "compile-flags": "Écrit .jenga/compileflags.jcdb (diagnostics de NKCode) ; compile_commands.json : jenga gen --compile-commands",
    "debug":         "Alias de gdb",
    "ide":           "Alias de ide-setup",
    "help":          "Affiche cette aide",
}

# L'ordre d'affichage. Ce qui n'y figure pas est ajouté à la fin par
# command_list() : oublier une commande ici ne la cache plus.
ORDRE: List[str] = [
    "build", "run", "gdb", "debug", "test", "clean", "rebuild", "watch", "info",
    "gen", "workspace", "project", "file", "examples", "install", "kit",
    "keygen", "sign", "package", "deploy", "publish", "profile", "bench",
    "docs", "config", "ide-setup", "ide", "compile-flags", "help",
]


def command_list():
    """Rend [(noms affichés, description)] pour l'aide.

    Les noms portent leurs alias : « build, b ». La liste couvre TOUT le
    registre : une commande enregistrée mais non décrite apparaît quand même,
    suivie de « (sans description) ».
    """
    par_cible: Dict[str, List[str]] = {}
    for court, long in ALIASES.items():
        par_cible.setdefault(long, []).append(court)

    connus = set(ORDRE)
    restants = [c for c in sorted(COMMANDS)
                if c not in connus and c not in ALIASES]

    lignes = []
    for nom in ORDRE + restants:
        if nom not in COMMANDS and nom not in ALIASES:
            continue          # décrite mais pas (encore) enregistrée
        affiche = ", ".join([nom] + sorted(par_cible.get(nom, [])))
        lignes.append((affiche, DESCRIPTIONS.get(nom, "(sans description)")))
    return lignes


def get_command_class(name: str):
    """Retourne la classe de commande correspondant au nom (avec gestion des alias)."""
    cmd = ALIASES.get(name, name)
    return COMMANDS.get(cmd)


def execute_command(name: str, args: List[str]) -> int:
    """Exécute une commande par son nom."""
    cmd_class = get_command_class(name)
    if not cmd_class:
        print(f"jenga: unknown command '{name}'", file=sys.stderr)
        return 1
    try:
        return cmd_class.Execute(args)
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 130
    except Exception as e:
        print(f"jenga: error executing command '{name}': {e}", file=sys.stderr)
        if '--verbose' in sys.argv or '-v' in sys.argv:
            import traceback
            traceback.print_exc()
        return 1


__all__ = [
    'COMMANDS', 'ALIASES', 'DESCRIPTIONS', 'ORDRE', 'command_list',
    'get_command_class', 'execute_command'
]
