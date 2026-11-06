#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Cancel – l'ANNULATION COOPERATIVE d'une construction (2.10.2).
AUTEUR : TEUGUIA TADJUIDJE Rodolf Séderis — Rihen

Un IDE qui embarque Jenga (NKCode) doit pouvoir dire « arrete la construction » sans tuer le fil qui
execute l'interpreteur. Le contrat :

  - `Request()` leve le drapeau ET termine les processus que JENGA a lances (compilateurs, editeurs de
    liens, commandes prebuild/postbuild) -- chacun avec ses descendants, jamais un autre processus : la
    liste est celle des Popen enregistres par `Utils/Process.py`.
  - Jenga LIT le drapeau entre deux unites de compilation et entre deux projets (`Check()`), et
    `Process.ExecuteCommand` leve `BuildCancelled` quand un processus qu'on vient de terminer rend un
    code d'echec : une annulation n'est JAMAIS comptee comme une erreur de compilation.
  - `BuildCancelled` derive de BaseException : les `except Exception` des boucles de compilation ne
    l'avalent pas ; seul l'appelant d'une action (Core/Embed.py) l'attrape, et rend « Construction
    arretee » avec un code DISTINCT de l'echec (CANCEL_EXIT_CODE).
  - Aucun fichier a moitie ecrit n'est pris pour bon a la construction suivante : le Builder retire
    l'objet (+ .d + .jenga_sig) du fichier en cours, la cible en cours d'edition de liens, et l'en-tete
    precompile en cours (voir Builder._CompileGuarded, BuildProject).

LE DRAPEAU VIENT DE L'HOTE SANS GIL : l'hote ne peut pas appeler Python depuis un autre fil (le fil qui
porte l'interpreteur le garde, meme au repos). Il donne donc a `StartWatcher` une SONDE (une fonction qui
lit un drapeau natif) ; un petit fil Python la lit toutes les 100 ms et appelle `Request()`.
"""

import os
import signal
import subprocess
import sys
import threading

CANCEL_EXIT_CODE = 130  # le code de sortie d'une annulation (celui d'un Ctrl+C) : distinct de l'echec (1)


class BuildCancelled(BaseException):
    """Levee quand la construction a ete annulee (voir le module)."""


_event = threading.Event()
_lock = threading.Lock()
_children = {}  # pid -> Popen : les processus lances PAR JENGA, et eux seuls
_watch_stop = None
_watch_thread = None
_forward = None  # relais : quand l'annulation est demandee ICI, la dire au demon qui construit a notre place


def Clear() -> None:
    _event.clear()


def IsRequested() -> bool:
    return _event.is_set()


def Check() -> None:
    """Leve BuildCancelled si l'annulation est demandee (a appeler entre deux unites de travail)."""
    if _event.is_set():
        raise BuildCancelled()


def Register(proc) -> None:
    with _lock:
        _children[proc.pid] = proc
    if _event.is_set():  # demande arrivee entre le lancement et l'enregistrement
        _KillTree(proc)


def Unregister(proc) -> None:
    with _lock:
        _children.pop(proc.pid, None)


def _KillTree(proc) -> None:
    """Termine `proc` et ses descendants (jamais un autre processus : `proc` est un enfant de Jenga)."""
    try:
        if proc.poll() is not None:
            return
    except Exception:  # noqa: BLE001
        return
    try:
        if sys.platform == "win32":
            # chemin ABSOLU de taskkill : le PATH d'un hote embarque peut ne pas porter System32 (et un nom nu suivrait le PATH)
            taskkill = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "taskkill.exe")
            r = subprocess.run([taskkill, "/F", "/T", "/PID", str(proc.pid)],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               creationflags=0x08000000)  # CREATE_NO_WINDOW
            _Trace("taskkill pid %s -> %s" % (proc.pid, r.returncode))
            if r.returncode != 0:
                proc.kill()  # au moins l'enfant direct
        else:
            try:
                os.killpg(proc.pid, signal.SIGKILL)  # Process.ExecuteCommand lance chaque enfant avec setsid
            except (ProcessLookupError, PermissionError):
                proc.kill()
    except Exception:  # noqa: BLE001
        try:
            proc.kill()
        except Exception:  # noqa: BLE001
            pass


def _Trace(msg: str) -> None:
    """JENGA_TRACE_CANCEL=1 : dit ce que fait l'annulation (diagnostic ; sur stderr, donc dans le transcript de l'hote)."""
    if os.environ.get("JENGA_TRACE_CANCEL") == "1":
        print("[annulation] " + msg, file=sys.stderr, flush=True)


def Request() -> None:
    """Demande l'annulation : leve le drapeau et termine les processus enfants en cours."""
    _Trace("Request : %d enfant(s) enregistre(s)" % len(_children))
    _event.set()
    fwd = _forward
    if fwd is not None:  # (demon) la construction se fait dans un AUTRE processus : on lui transmet la demande
        try:
            fwd()
        except Exception as e:  # noqa: BLE001
            _Trace("le relais vers le demon a echoue : %r" % (e,))
    with _lock:
        vivants = list(_children.values())
    for p in vivants:
        _KillTree(p)


def SetForward(fn) -> None:
    """(demon) `fn` est appelee par Request() : le client transmet l'annulation au demon (Commands/Build.py)."""
    global _forward
    _forward = fn


def RunWithFlagFile(fn):
    """(2.10.2) Un hote qui lance `jenga` en SOUS-PROCESSUS (NKCode, quand l'interpreteur n'est pas dans son processus) demande
    l'arret en CREANT le fichier nomme par JENGA_CANCEL_FILE : un fil le surveille (100 ms) et appelle Request(). Rend le code
    de `fn`, ou CANCEL_EXIT_CODE avec « Construction arretee » si la construction est annulee."""
    chemin = os.environ.get("JENGA_CANCEL_FILE")
    Clear()
    if chemin:
        StartWatcher(lambda: os.path.exists(chemin))
    try:
        return fn()
    except BuildCancelled:
        print("Construction arretee")
        return CANCEL_EXIT_CODE
    finally:
        StopWatcher()


def ChildCount() -> int:
    with _lock:
        return len(_children)


def StartWatcher(probe) -> None:
    """Lance le fil qui lit la sonde de l'hote (toutes les 100 ms) et appelle Request() quand elle rend vrai."""
    global _watch_stop, _watch_thread
    StopWatcher()
    if probe is None:
        _Trace("StartWatcher : pas de sonde")
        return
    stop = threading.Event()
    _Trace("StartWatcher : sonde donnee")

    def _boucle():
        while not stop.wait(0.1):
            try:
                if probe():
                    _Trace("la sonde de l'hote rend vrai")
                    Request()
                    return
            except Exception as e:  # noqa: BLE001
                _Trace("la sonde a leve : %r" % (e,))
                return

    t = threading.Thread(target=_boucle, name="jenga-cancel-watch", daemon=True)
    _watch_stop, _watch_thread = stop, t
    t.start()


def StopWatcher() -> None:
    global _watch_stop, _watch_thread
    if _watch_stop is not None:
        _watch_stop.set()
    if _watch_thread is not None and _watch_thread is not threading.current_thread():
        _watch_thread.join(timeout=1.0)
    _watch_stop = _watch_thread = None
