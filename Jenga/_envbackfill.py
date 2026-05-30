#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
_envbackfill — propage les variables d'environnement permanentes (Windows) dans
`os.environ` quand elles manquent dans la session courante.

Probleme adresse : sur Windows, `setx` (et l'UI "Variables d'environnement") ne
mettent a jour QUE les nouvelles sessions. Si l'utilisateur a une PowerShell
deja ouverte au moment ou il configure ANDROID_NDK_ROOT, cette session ne voit
pas la variable -> Jenga echoue avec "No suitable toolchain found for Android"
alors que tout est correctement installe.

Solution : a l'import de Jenga, lire HKCU\\Environment (et HKLM\\System\\...\\
Environment pour les vars systeme) et hydrater `os.environ` pour les cles
connues, uniquement si elles sont absentes ou vides en session.

Multi-plateforme : sur macOS / Linux, c'est un no-op (les shells propagent
deja les env vars correctement via .bashrc / launchd).

Nomenclature : fonctions en PascalCase, variables locales en snake_case.
"""
from __future__ import annotations

import os
import sys

# Cles que Jenga lit habituellement et qui doivent etre disponibles meme dans
# une session ouverte avant `setx`.
_BACKFILL_KEYS = (
    "ANDROID_HOME", "ANDROID_SDK_ROOT", "ANDROID_NDK_ROOT", "ANDROID_NDK_HOME",
    "JAVA_HOME", "JDK_HOME",
    "EMSDK", "EMSCRIPTEN_ROOT", "EMSCRIPTEN",
    "OHOS_SDK", "HARMONY_SDK", "OHOS_NDK_HOME",
    "ZIG_ROOT",
    "GameDK", "GRDKLatest", "GXDKLatest",
)


def BackfillWindowsEnv(keys=_BACKFILL_KEYS) -> dict:
    """Sur Windows, recupere les vars permanentes depuis le registre et les
    injecte dans `os.environ` si absentes. Retourne le dict des cles ajoutees
    (pour journalisation / debug). No-op ailleurs."""
    if not sys.platform.startswith("win"):
        return {}
    try:
        import winreg                                       # type: ignore[import]
    except ImportError:
        return {}

    injected: dict = {}
    # 1. Variables utilisateur : HKCU\Environment
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Environment") as key:
            user_env = _ReadRegistryEnv(key, keys)
    except OSError:
        user_env = {}

    # 2. Variables systeme : HKLM\SYSTEM\CurrentControlSet\Control\Session Manager\Environment
    sys_env: dict = {}
    try:
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment",
        ) as key:
            sys_env = _ReadRegistryEnv(key, keys)
    except OSError:
        pass

    # Priorite : User > System (cf. comportement Windows).
    for name in keys:
        if os.environ.get(name):
            continue   # deja en session
        value = user_env.get(name) or sys_env.get(name)
        if value:
            os.environ[name] = value
            injected[name] = value
    return injected


def _ReadRegistryEnv(key, names) -> dict:
    """Lit les valeurs nommees `names` depuis une cle ouverte. Tolerant : retourne
    un dict (cle -> valeur) pour celles trouvees, ignore les absentes."""
    import winreg                                           # type: ignore[import]
    out: dict = {}
    for name in names:
        try:
            value, _ = winreg.QueryValueEx(key, name)
        except FileNotFoundError:
            continue
        if value:
            # Les REG_EXPAND_SZ peuvent contenir %FOO%; on developpe pour Python.
            out[name] = os.path.expandvars(str(value))
    return out
