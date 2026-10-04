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
# 2.8.1 (2026-09-23) : ccache/sccache se place DEVANT le compilateur au lieu de
# le remplacer. Avec ccache dans le PATH, toute compilation GCC/Clang echouait
# sur « ccache: unknown option -- g » : g++ avait disparu de la commande et
# ccache lisait les drapeaux du compilateur comme les siens.
# 2.8.2 (2026-09-24) : Android. libc++_shared.so empaquetee quand un .so en
# depend (lu dans DT_NEEDED) -- l'app mourait au lancement sur un vrai
# telephone. EGL/GLESv2 ne sont plus lies d'office : seuls -llog et -landroid,
# exiges par la colle NativeActivity. `jenga deploy` nomme la cause d'un echec
# d'installation. Le code de retour de prebuild/postbuild arrete le projet.
# 2.8.3 (2026-09-24) : Windows. La detection automatique fouille aussi
# C:\msys64\{ucrt64,clang64,mingw64}\bin apres le PATH (MSYS2_ROOT pour une
# autre racine), et ar/ld sont pris a cote du compilateur retenu. « No suitable
# toolchain found » liste desormais chaque candidat et la raison de son rejet.
# 2.8.4 (2026-09-24) : `jenga gen` reconstruit contre les vrais outils. CMake
# (chemins « \ » refuses, OBJC exige), Visual Studio (v143 en dur : MSB8020
# sous VS 2026 ; GUID divergents), Makefile (chemin mange par le shell) et
# Android.mk (ni -llog ni colle NativeActivity ; minsdk ignore) ne
# construisaient plus. Nouveau : --compile-commands, capture des commandes
# reelles du build.
# 2.8.5 (2026-09-27) : le diagnostic de binaire VERROUILLE ne devine plus. Il
# NOMME le tenant (Restart Manager), ATTEND quand c'est un tiers -- antivirus,
# indexeur, assistant d'editeur relachent seuls -- et echoue tout de suite quand
# c'est une execution de la cible, qui ne se fermera pas d'elle-meme. L'ancien
# message affirmait « une execution precedente tourne encore » et conseillait
# `taskkill` sur un binaire dont aucun processus n'existait : quarante minutes
# passees a chercher un coupable qui n'existait pas. Plafond d'attente reglable
# par JENGA_ATTENTE_VERROU (0 = echouer tout de suite, pour l'integration
# continue).
# 2.8.6 (2026-09-29) : VS Code et le C++. `jenga build` tient a jour
# Build/compile_commands.json et .vscode/c_cpp_properties.json -- regeneres
# quand un .jenga change OU quand la liste des sources change -- sans quoi
# l'extension C/C++ ne resolvait aucun #include (ni Ctrl+clic, ni definition).
# Corrige le strip JSONC, qui prenait `/*` DANS les chaines pour un
# commentaire : `"**/*.jenga", "**/*.py"` devenait `"***.py"`, et chaque build
# en ajoutait un dans settings.json (150 dans Nkentseu). Les restes sont purges.
# 2.8.7 (2026-09-30) : macOS, Linux et Web passent enfin les cxxflags()/cflags()
# d'un PROJET au compilateur (seul Windows le faisait) ; l'exemple 27 (NKWindow)
# recompile sur toutes les plateformes -- ses neuf backends suivent l'API a
# pointeurs, et Win32 livre ses evenements -- verifie sur un vrai Mac par la CI.
# 2.8.8 (2026-10-01) : macOS -- les frameworks des bibliotheques STATIQUES
# arrivent au lien de l'executable ; objcarc() (ARC sur les .m/.mm, eteint par
# defaut) ; clang-native designe le clang de l'hote ; un toolchain introuvable
# revient au defaut du build au lieu d'heriter du projet precedent. Verifie par
# la CI macOS de Nkentseu (Metal dans NKRenderer et NKCanvas).
__version__ = "2.8.9"

# Éditeur / entreprise. Rihen édite Jenga. Utilisé comme valeur par défaut
# du publisher des installeurs (Manufacturer MSI, AppPublisher Inno, Maintainer
# DEB) quand le développeur ne fournit pas apppublisher() dans son .jenga.
__author__ = "Rihen"
__publisher__ = "Rihen"
__email__ = "rihen.universe@gmail.com"
