#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Daemon – Processus en arrière‑plan pour accélérer les commandes Jenga.

Architecture robuste :
  - Détachement complet du terminal (daemonization) sur Unix
  - Processus détaché sur Windows (CREATE_NO_WINDOW / DETACHED_PROCESS)
  - Socket TCP localhost avec port aléatoire
  - Persistance du workspace en mémoire et mise à jour incrémentale
  - Communication RPC JSON
  - Gestion des signaux (SIGTERM, SIGINT)
  - Fichier d'information PID/port pour les clients
  - Logs redirigés vers .jenga/daemon/daemon.{out,err}
"""

import os
import sys
import json
import socket
import threading
import time
import signal
import atexit
from pathlib import Path
from typing import Dict, Any, Optional, Callable
from dataclasses import dataclass
import queue
import subprocess
import tempfile
import uuid

from ..Utils import Colored, FileSystem, Process
from .Loader import Loader
from .Cache import Cache
from .Watcher import FileWatcher
from .Incremental import Incremental
from .._version import __version__


# ✅ Import absolu cohérent avec l'API utilisateur
from Jenga.Core import Api


@dataclass
class DaemonInfo:
    """Informations sur un daemon en cours."""
    pid: int
    port: int
    workspace_root: str
    entry_file: str
    start_time: float
    version: str = __version__


class Daemon:
    """
    Serveur RPC exécuté en arrière‑plan.
    Singleton – une seule instance par workspace.
    """

    _DAEMON_DIR = Path(".jenga") / "daemon"
    _INFO_FILE = "daemon.json"

    def __init__(self, workspace_root: Path, entry_file: Path):
        self.workspace_root = workspace_root.resolve()
        self.entry_file = entry_file.resolve()
        self.loader = Loader(verbose=False)
        self.cache = Cache(self.workspace_root)
        self.workspace = None
        self._server_socket = None
        self._running = False
        self._port = None
        self._watcher = None
        self._lock = threading.RLock()
        self._start_time = time.time()

        # Répertoire du daemon
        self._daemon_dir = self.workspace_root / self._DAEMON_DIR
        FileSystem.MakeDirectory(self._daemon_dir)

    # -----------------------------------------------------------------------
    # Démarrage et initialisation
    # -----------------------------------------------------------------------

    def Start(self) -> bool:
        """Charge le workspace et lance le serveur."""
        if not self._LoadWorkspace():
            return False

        # Trouver un port libre
        self._port = self._FindFreePort()
        if self._port is None:
            Colored.PrintError("No free port available.")
            return False

        # Créer le socket serveur
        self._server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server_socket.bind(('127.0.0.1', self._port))
        self._server_socket.listen(5)
        self._server_socket.settimeout(1.0)

        self._running = True

        # Écrire les informations du daemon
        self._WriteDaemonInfo()

        # Thread d'écoute
        listener = threading.Thread(target=self._ListenLoop, daemon=True)
        listener.start()

        # Installer les gestionnaires de signaux
        self._InstallSignalHandlers()

        Colored.PrintSuccess(
            f"Daemon started on port {self._port} (PID: {os.getpid()})\n"
            f"  Workspace: {self.workspace_root}\n"
            f"  Entry: {self.entry_file}"
        )
        return True

    def _LoadWorkspace(self) -> bool:
        """Charge le workspace depuis le cache ou le fichier source."""
        self.workspace = self.cache.LoadWorkspace(self.entry_file, self.loader)
        if self.workspace is None:
            Colored.PrintInfo("Cache invalid, performing full load...")
            self.workspace = self.loader.LoadWorkspace(str(self.entry_file))
            if self.workspace is None:
                Colored.PrintError("Failed to load workspace.")
                return False
            self.cache.SaveWorkspace(self.workspace, self.entry_file, self.loader)
        return True

    # -----------------------------------------------------------------------
    # Boucle d'écoute RPC
    # -----------------------------------------------------------------------

    def _ListenLoop(self):
        """Accepte les connexions et délègue à des threads."""
        while self._running:
            try:
                client, addr = self._server_socket.accept()
                client.settimeout(10.0)
                handler = threading.Thread(
                    target=self._HandleClient,
                    args=(client,),
                    daemon=True
                )
                handler.start()
            except socket.timeout:
                continue
            except Exception as e:
                if self._running:
                    Colored.PrintError(f"Accept error: {e}")

    def _HandleClient(self, client_socket: socket.socket):
        """Traite une requête JSON et renvoie une réponse."""
        try:
            data = client_socket.recv(65536)
            if not data:
                return
            request = json.loads(data.decode('utf-8'))
            response = self._ExecuteCommand(request)
            client_socket.send(json.dumps(response).encode('utf-8'))
        except json.JSONDecodeError:
            client_socket.send(json.dumps({
                'status': 'error',
                'message': 'Invalid JSON'
            }).encode('utf-8'))
        except Exception as e:
            try:
                client_socket.send(json.dumps({
                    'status': 'error',
                    'message': str(e)
                }).encode('utf-8'))
            except:
                pass
        finally:
            client_socket.close()

    def _ExecuteCommand(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """Exécute une commande interne."""
        cmd = request.get('command')
        args = request.get('args', {})
        cmd_id = request.get('id', str(uuid.uuid4()))

        try:
            # Commandes de base
            if cmd == 'ping':
                return {'status': 'ok', 'pid': os.getpid(), 'id': cmd_id}
            elif cmd == 'stop':
                self.Stop()
                return {'status': 'ok', 'message': 'Daemon stopped', 'id': cmd_id}
            elif cmd == 'status':
                return {**self._GetStatus(), 'id': cmd_id}
            elif cmd == 'update':
                with self._lock:
                    changed = self.cache.UpdateIncremental(
                        self.entry_file, self.loader, self.workspace
                    )
                return {'status': 'ok', 'changed': changed, 'id': cmd_id}
            elif cmd == 'watch_start':
                return {**self._StartWatcher(args), 'id': cmd_id}
            elif cmd == 'watch_stop':
                return {**self._StopWatcher(), 'id': cmd_id}

            # Commandes de build
            elif cmd == 'build':
                return {**self._Build(args), 'id': cmd_id}
            elif cmd == 'clean':
                return {**self._Clean(args), 'id': cmd_id}
            elif cmd == 'run':
                return {**self._Run(args), 'id': cmd_id}
            elif cmd == 'test':
                return {**self._Test(args), 'id': cmd_id}
            else:
                return {
                    'status': 'error',
                    'message': f'Unknown command: {cmd}',
                    'id': cmd_id
                }
        except Exception as e:
            return {'status': 'error', 'message': str(e), 'id': cmd_id}

    # -----------------------------------------------------------------------
    # Implémentation des commandes
    # -----------------------------------------------------------------------

    def _Build(self, args: Dict) -> Dict:
        """Exécute un build."""
        config = args.get('config', 'Debug')
        platform = args.get('platform', 'Windows')
        target = args.get('target')
        verbose = args.get('verbose', False)
        # Sans ce relais, `jenga build --keep-going` s'arreterait quand meme au
        # premier echec des qu'un daemon tourne — le drapeau serait accepte par
        # la ligne de commande et ignore en silence, ce qui est precisement le
        # defaut que ce mode existe pour corriger.
        keep_going = bool(args.get('keep_going', False))
        from ..Commands.Build import BuildCommand
        action = args.get('action', 'build')
        cli_custom_options = args.get('custom_options') or {}
        options = args.get('options')
        try:
            resolved_custom_options = BuildCommand.ResolveWorkspaceOptions(self.workspace, cli_custom_options)
        except ValueError as e:
            return {'status': 'error', 'message': str(e), 'return_code': 1}

        if options is None:
            options = BuildCommand.CollectFilterOptions(
                config=config,
                platform=platform,
                target=target,
                verbose=verbose,
                no_cache=bool(args.get('no_cache', False)),
                no_daemon=False,
                extra=[f"action:{action}"],
                custom_option_values=resolved_custom_options
            )
        elif resolved_custom_options:
            # Ensure daemon and direct mode expose the same option tokens.
            merged = set(options)
            merged.update(BuildCommand.OptionValuesToTokens(resolved_custom_options))
            options = sorted({str(opt).strip().lower() for opt in merged if str(opt).strip()})

        if BuildCommand.IsAllPlatformsRequest(platform):
            platforms = BuildCommand.GetAllDeclaredPlatforms(self.workspace)
            return_code = BuildCommand.BuildAcrossPlatforms(
                self.workspace,
                config=config,
                platforms=platforms,
                target=target,
                verbose=verbose,
                action=action,
                options=options,
                keepGoing=keep_going
            )
        else:
            builder = BuildCommand.CreateBuilder(
                self.workspace, config, platform, target, verbose,
                action=action,
                options=options,
                keepGoing=keep_going
            )
            return_code = builder.Build(target)
        return {
            'status': 'ok' if return_code == 0 else 'error',
            'return_code': return_code
        }

    def _Clean(self, args: Dict) -> Dict:
        """Exécute clean."""
        from ..Commands.Clean import CleanCommand
        cmd = CleanCommand()
        return_code = cmd.Execute(self.workspace, args)
        return {'status': 'ok' if return_code == 0 else 'error', 'return_code': return_code}

    def _Run(self, args: Dict) -> Dict:
        """Exécute run."""
        from ..Commands.Run import RunCommand
        # RunCommand.Execute est une STATICMETHODE qui prend une LISTE argv,
        # pas (workspace, dict) : l'ancien appel levait un TypeError a tous
        # les coups, donc `jenga run` echouait des qu'un daemon tournait.
        # On reconstruit donc l'argv, `--args` EN DERNIER (argparse.REMAINDER
        # avale tout ce qui suit).
        argv = []
        proj = args.get('project')
        if proj:
            argv.append(str(proj))
        for cle, drapeau in (('config', '--config'), ('platform', '--platform')):
            v = args.get(cle)
            if v:
                argv += [drapeau, str(v)]
        if args.get('build'):
            argv.append('--build')
        argv.append('--no-daemon')  # on Y EST deja : ne pas se rappeler soi-meme
        extra = args.get('args') or []
        if extra:
            argv += ['--args'] + [str(a) for a in extra]
        return_code = RunCommand.Execute(argv)
        return {'status': 'ok' if return_code == 0 else 'error', 'return_code': return_code}

    def _Test(self, args: Dict) -> Dict:
        """Exécute test."""
        from ..Commands.Test import TestCommand
        # `test` n'a NI argument positionnel, NI --build, NI --args : il prend
        # --project et --no-build. Reutiliser l'argv de `run` produirait une
        # erreur argparse — les deux commandes ont des surfaces differentes.
        argv = []
        proj = args.get('project')
        if proj:
            argv += ['--project', str(proj)]
        for cle, drapeau in (('config', '--config'), ('platform', '--platform')):
            v = args.get(cle)
            if v:
                argv += [drapeau, str(v)]
        if not args.get('build', True):
            argv.append('--no-build')
        argv.append('--no-daemon')  # on y est deja : ne pas se rappeler soi-meme
        return_code = TestCommand.Execute(argv)
        return {'status': 'ok' if return_code == 0 else 'error', 'return_code': return_code}

    def _StartWatcher(self, args: Dict) -> Dict:
        """Démarre le watcher de fichiers."""
        if self._watcher:
            return {'status': 'error', 'message': 'Watcher already running'}

        self._watcher = FileWatcher(use_polling=args.get('polling', False))
        self._watcher.AddWatch(self.workspace_root)

        def on_change(event_type, path):
            Colored.PrintInfo(f"[daemon] File changed: {path}")
            with self._lock:
                self.cache.UpdateIncremental(self.entry_file, self.loader, self.workspace)
            # TODO: option pour rebuild automatique

        self._watcher.AddCallback(on_change)
        self._watcher.Start()
        return {'status': 'ok', 'message': 'Watcher started'}

    def _StopWatcher(self) -> Dict:
        """Arrête le watcher."""
        if self._watcher:
            self._watcher.Stop()
            self._watcher = None
            return {'status': 'ok', 'message': 'Watcher stopped'}
        return {'status': 'error', 'message': 'No watcher running'}

    # -----------------------------------------------------------------------
    # Gestion des informations du daemon
    # -----------------------------------------------------------------------

    def _WriteDaemonInfo(self):
        """Écrit les informations du daemon dans .jenga/daemon/daemon.json."""
        info = DaemonInfo(
            pid=os.getpid(),
            port=self._port,
            workspace_root=str(self.workspace_root),
            entry_file=str(self.entry_file),
            start_time=self._start_time,
            version=__version__
        )
        info_path = self._daemon_dir / self._INFO_FILE
        FileSystem.WriteFile(info_path, json.dumps(info.__dict__, indent=2))

    def _RemoveDaemonInfo(self):
        """Supprime le fichier d'information."""
        info_path = self._daemon_dir / self._INFO_FILE
        FileSystem.RemoveFile(info_path, ignoreErrors=True)

    def _GetStatus(self) -> Dict:
        """Retourne l'état courant du daemon."""
        return {
            'status': 'ok',
            'pid': os.getpid(),
            'port': self._port,
            'workspace': str(self.workspace_root),
            'entry': str(self.entry_file),
            'uptime': time.time() - self._start_time,
            'watcher_active': self._watcher is not None and self._watcher._running
        }

    # -----------------------------------------------------------------------
    # Gestion des signaux et arrêt
    # -----------------------------------------------------------------------

    def _InstallSignalHandlers(self):
        """Installe les gestionnaires pour SIGTERM et SIGINT."""
        if sys.platform != 'win32':
            signal.signal(signal.SIGTERM, self._SignalHandler)
            signal.signal(signal.SIGINT, self._SignalHandler)

    def _SignalHandler(self, signum, frame):
        """Réception d'un signal d'arrêt."""
        Colored.PrintInfo(f"Received signal {signum}, shutting down...")
        self.Stop()

    def Stop(self):
        """Arrête proprement le daemon."""
        if not self._running:
            return
        self._running = False
        if self._watcher:
            self._watcher.Stop()
        if self._server_socket:
            self._server_socket.close()
        self._RemoveDaemonInfo()
        Colored.PrintInfo("Daemon stopped.")

    # -----------------------------------------------------------------------
    # Utilitaires
    # -----------------------------------------------------------------------

    @staticmethod
    def _FindFreePort(start=49152, end=65535) -> Optional[int]:
        """Trouve un port TCP libre en localhost."""
        import random
        for _ in range(50):
            port = random.randint(start, end)
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                try:
                    s.bind(('127.0.0.1', port))
                    return port
                except OSError:
                    continue
        return None

    @classmethod
    def IsDaemonRunning(cls, workspace_root: Path) -> bool:
        """Vérifie si un daemon est actif pour ce workspace."""
        info_path = workspace_root / cls._DAEMON_DIR / cls._INFO_FILE
        if not info_path.exists():
            return False
        try:
            data = json.loads(FileSystem.ReadFile(info_path))
            pid = data['pid']
            # Vérifier si le processus existe toujours
            if sys.platform == 'win32':
                result = subprocess.run(
                    ['tasklist', '/FI', f'PID eq {pid}'],
                    capture_output=True, text=True
                )
                return str(pid) in result.stdout
            else:
                try:
                    os.kill(pid, 0)
                    return True
                except OSError:
                    return False
        except Exception:
            return False


# ---------------------------------------------------------------------------
# Client de communication avec le daemon
# ---------------------------------------------------------------------------

class DaemonClient:
    """Client RPC pour communiquer avec le daemon."""

    def __init__(self, workspace_root: Path):
        self.workspace_root = workspace_root.resolve()
        self._daemon_info = None
        self._LoadDaemonInfo()

    def _LoadDaemonInfo(self):
        """Charge les informations depuis .jenga/daemon/daemon.json."""
        info_path = self.workspace_root / Daemon._DAEMON_DIR / Daemon._INFO_FILE
        if not info_path.exists():
            return
        try:
            data = json.loads(FileSystem.ReadFile(info_path))
            self._daemon_info = DaemonInfo(**data)
        except Exception:
            pass

    def IsAvailable(self) -> bool:
        """Vérifie si le daemon est accessible."""
        if not self._daemon_info:
            return False
        # Vérifier si le processus existe toujours
        if sys.platform == 'win32':
            result = subprocess.run(
                ['tasklist', '/FI', f'PID eq {self._daemon_info.pid}'],
                capture_output=True, text=True
            )
            if str(self._daemon_info.pid) not in result.stdout:
                return False
        else:
            try:
                os.kill(self._daemon_info.pid, 0)
            except OSError:
                return False
        # Vérifier que le port répond
        try:
            with socket.create_connection(('127.0.0.1', self._daemon_info.port), timeout=0.5):
                pass
            return True
        except:
            return False

    def SendCommand(self, command: str, args: Dict = None, timeout: float = 30.0) -> Dict:
        """
        Envoie une commande au daemon et retourne la réponse.
        Lève une exception si le daemon n'est pas disponible.
        """
        if not self.IsAvailable():
            raise ConnectionError("Daemon is not running or unreachable")

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(timeout)
            s.connect(('127.0.0.1', self._daemon_info.port))
            request = {
                'command': command,
                'args': args or {},
                'id': str(uuid.uuid4())
            }
            s.send(json.dumps(request).encode('utf-8'))
            response = s.recv(65536)
            return json.loads(response.decode('utf-8'))


# ---------------------------------------------------------------------------
# Fonctions de contrôle du daemon (pour les commandes CLI)
# ---------------------------------------------------------------------------

def StartDaemon(workspace_root: Path, entry_file: Path,
                foreground: bool = False) -> bool:
    """
    Démarre le daemon en arrière‑plan.
    - foreground: si True, ne pas daemonizer (pour debug)
    """
    if Daemon.IsDaemonRunning(workspace_root):
        Colored.PrintWarning("Daemon already running.")
        return False

    # Construction de la commande de lancement
    python_exe = sys.executable
    script = Path(__file__).resolve()  # daemon.py lui-même
    # On utilise le module -m jenga.core.daemon? Mieux: passer par le module Jenga.
    # Pour lancer le daemon, on peut appeler le même script avec l'argument --daemon
    cmd = [
        python_exe,
        str(script),
        '--daemon',
        '--workspace', str(workspace_root),
        '--entry', str(entry_file)
    ]

    if foreground:
        # Exécution directe (pas de daemonisation)
        daemon = Daemon(workspace_root, entry_file)
        try:
            daemon.Start()
            # Boucle principale
            while daemon._running:
                time.sleep(1)
        except KeyboardInterrupt:
            daemon.Stop()
        return True

    # ========== DAEMONISATION ==========
    if sys.platform == 'win32':
        # Windows : processus détaché sans console
        # Utiliser DETACHED_PROCESS et éventuellement pythonw.exe pour éviter une fenêtre
        if python_exe.endswith('python.exe'):
            # Basculer vers pythonw.exe si disponible
            pythonw = python_exe.replace('python.exe', 'pythonw.exe')
            if Path(pythonw).exists():
                python_exe = pythonw

        creationflags = subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS
        # Rediriger les sorties vers des fichiers
        log_dir = workspace_root / Daemon._DAEMON_DIR
        FileSystem.MakeDirectory(log_dir)
        out_file = open(log_dir / 'daemon.out', 'a')
        err_file = open(log_dir / 'daemon.err', 'a')

        proc = subprocess.Popen(
            cmd,
            stdout=out_file,
            stderr=err_file,
            stdin=subprocess.DEVNULL,
            creationflags=creationflags,
            close_fds=True,
            cwd=str(workspace_root)
        )
        out_file.close()
        err_file.close()
        # Attendre que le daemon écrive son fichier d'info
        timeout = 5
        while timeout > 0 and not Daemon.IsDaemonRunning(workspace_root):
            time.sleep(0.2)
            timeout -= 0.2
        if Daemon.IsDaemonRunning(workspace_root):
            Colored.PrintSuccess(f"Daemon started with PID {proc.pid}")
            return True
        else:
            Colored.PrintError("Daemon failed to start.")
            return False

    else:
        # Unix : double fork daemonization
        # Premier fork
        try:
            pid = os.fork()
            if pid > 0:
                # Parent : attendre que le daemon soit prêt
                timeout = 5
                while timeout > 0 and not Daemon.IsDaemonRunning(workspace_root):
                    time.sleep(0.2)
                    timeout -= 0.2
                if Daemon.IsDaemonRunning(workspace_root):
                    Colored.PrintSuccess(f"Daemon started with PID {pid}")
                    return True
                else:
                    Colored.PrintError("Daemon failed to start.")
                    return False
        except OSError:
            Colored.PrintError("First fork failed")
            return False

        # Démonisation
        os.setsid()
        os.umask(0)
        # Second fork
        try:
            pid = os.fork()
            if pid > 0:
                sys.exit(0)
        except OSError:
            sys.exit(1)

        # Rediriger stdin/stdout/stderr
        sys.stdout.flush()
        sys.stderr.flush()
        log_dir = workspace_root / Daemon._DAEMON_DIR
        FileSystem.MakeDirectory(log_dir)

        with open('/dev/null', 'r') as f:
            os.dup2(f.fileno(), sys.stdin.fileno())
        with open(log_dir / 'daemon.out', 'a') as f:
            os.dup2(f.fileno(), sys.stdout.fileno())
        with open(log_dir / 'daemon.err', 'a') as f:
            os.dup2(f.fileno(), sys.stderr.fileno())

        # Lancer le daemon
        daemon = Daemon(workspace_root, entry_file)
        try:
            daemon.Start()
            while daemon._running:
                time.sleep(1)
        except Exception:
            daemon.Stop()
            sys.exit(1)

    return True


def StopDaemon(workspace_root: Path) -> bool:
    """Arrête le daemon."""
    client = DaemonClient(workspace_root)
    if not client.IsAvailable():
        Colored.PrintWarning("No running daemon found.")
        return False
    try:
        response = client.SendCommand('stop', timeout=5)
        if response.get('status') == 'ok':
            Colored.PrintSuccess("Daemon stopped.")
            return True
        else:
            Colored.PrintError(f"Stop failed: {response.get('message')}")
            return False
    except Exception as e:
        Colored.PrintError(f"Failed to stop daemon: {e}")
        return False


def DaemonStatus(workspace_root: Path) -> Dict:
    """Retourne le statut du daemon."""
    client = DaemonClient(workspace_root)
    if not client.IsAvailable():
        return {'running': False}
    try:
        response = client.SendCommand('status', timeout=2)
        if response.get('status') == 'ok':
            return {
                'running': True,
                'pid': response.get('pid'),
                'port': response.get('port'),
                'uptime': response.get('uptime'),
                'watcher': response.get('watcher_active')
            }
        else:
            return {'running': False}
    except Exception:
        return {'running': False}


# ---------------------------------------------------------------------------
# Point d'entrée pour l'exécution directe (daemon)
# ---------------------------------------------------------------------------
if __name__ == '__main__':
    # Ce bloc est appelé quand le daemon est lancé via `python -m jenga.core.daemon`
    import argparse
    parser = argparse.ArgumentParser(description='Jenga daemon')
    parser.add_argument('--daemon', action='store_true', help='Run as daemon')
    parser.add_argument('--workspace', required=True, help='Workspace root path')
    parser.add_argument('--entry', required=True, help='Entry .jenga file')
    parser.add_argument('--foreground', action='store_true', help='Run in foreground')
    args = parser.parse_args()

    if args.daemon:
        workspace_root = Path(args.workspace).resolve()
        entry_file = Path(args.entry).resolve()
        daemon = Daemon(workspace_root, entry_file)
        try:
            daemon.Start()
            while daemon._running:
                time.sleep(1)
        except KeyboardInterrupt:
            daemon.Stop()
        sys.exit(0)
