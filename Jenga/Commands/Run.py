#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Run command – Exécute l'exécutable d'un projet (après build si nécessaire).
"""

import argparse
import sys
import time as _time
from pathlib import Path
from typing import List, Optional, Tuple

from ..Core.Loader import Loader
from ..Core.Cache import Cache
from ..Core.Builder import Builder
from ..Core import Api
from ..Core.Platform import Platform
from ..Utils import Colored, Process, FileSystem
from .Build import BuildCommand
from .Deploy import DeployCommand


class RunCommand:
    """jenga run [PROJECT] [--config NAME] [--platform NAME] [--args ...]"""

    @staticmethod
    def Execute(args: List[str]) -> int:
        parser = argparse.ArgumentParser(prog="jenga run", description="Run a project executable.")
        parser.add_argument("project", nargs="?", default=None, help="Project name to run (default: startProject or first executable)")
        parser.add_argument("--config", default="Debug", help="Build configuration")
        parser.add_argument("--platform", default=None, help="Target platform")
        parser.add_argument("--args", nargs=argparse.REMAINDER, default=[], help="Arguments to pass to the executable")
        parser.add_argument("--build", action="store_true", help="Force rebuild before running (default: skip build)")
        parser.add_argument("--no-daemon", action="store_true", help="Do not use daemon")
        parser.add_argument("--jenga-file", help="Path to the workspace .jenga file (default: auto-detected)")
        parser.add_argument("--target", help="Mobile only: device serial / UDID to run on (skip if a single device is connected)")
        # Une application CONSOLE lancee depuis un IDE herite d'un TUBE, pas d'une
        # console : elle ne peut rien lire au clavier. On lui ouvre donc une
        # console dediee. Ce drapeau permet de s'en passer (redirection voulue,
        # integration continue, test automatise).
        parser.add_argument("--no-console", action="store_true",
                            help="Ne pas ouvrir de console dediee pour une application console (Windows)")
        parser.add_argument("--device", help="Alias for --target")
        parsed = parser.parse_args(args)

        if parsed.device and not parsed.target:
            parsed.target = parsed.device

        # Déterminer le répertoire de travail (workspace root)
        workspace_root = Path.cwd()
        if parsed.jenga_file:
            entry_file = Path(parsed.jenga_file).resolve()
            if not entry_file.exists():
                Colored.PrintError(f"Jenga file not found: {entry_file}")
                return 1
        else:
            entry_file = FileSystem.FindWorkspaceEntry(workspace_root)
            if not entry_file:
                Colored.PrintError("No .jenga workspace file found.")
                return 1
        workspace_root = entry_file.parent

        # Utiliser le daemon si disponible
        if not parsed.no_daemon:
            from ..Core.Daemon import DaemonClient, DaemonStatus
            client = DaemonClient(workspace_root)
            if client.IsAvailable():
                try:
                    response = client.SendCommand('run', {
                        'project': parsed.project,
                        'config': parsed.config,
                        'platform': parsed.platform,
                        'args': parsed.args,
                        'build': parsed.build
                    })
                    if response.get('status') == 'ok':
                        return response.get('return_code', 0)
                    else:
                        Colored.PrintError(f"Daemon run failed: {response.get('message')}")
                        return 1
                except Exception as e:
                    Colored.PrintWarning(f"Daemon error: {e}, falling back.")

        # Mode direct
        loader = Loader(verbose=False)
        cache = Cache(workspace_root)
        workspace = cache.LoadWorkspace(entry_file, loader)
        if workspace is None:
            workspace = loader.LoadWorkspace(str(entry_file))
            if workspace:
                cache.SaveWorkspace(workspace, entry_file, loader)
            else:
                Colored.PrintError("Failed to load workspace.")
                return 1

        # Déterminer le projet à exécuter
        project_name = parsed.project
        if not project_name:
            project_name = workspace.startProject
        if not project_name:
            # Chercher le premier projet de type exécutable
            for name, proj in workspace.projects.items():
                if proj.kind in (Api.ProjectKind.CONSOLE_APP, Api.ProjectKind.WINDOWED_APP, Api.ProjectKind.TEST_SUITE):
                    project_name = name
                    break
        if not project_name:
            Colored.PrintError("No executable project found.")
            return 1

        if project_name not in workspace.projects:
            Colored.PrintError(f"Project '{project_name}' not found.")
            return 1

        project = workspace.projects[project_name]

        # ── Mode mobile : Android via adb monkey ─────────────────────────
        # Si --platform android, on assume que l'APK est deja installe sur le
        # device et on se contente de le lancer via adb. Pour faire un cycle
        # complet (build + install + run), utiliser :
        #   jenga deploy --platform android --apk <apk> --target <serial>
        #   puis
        #   jenga run --platform android --target <serial>
        platform_norm = (parsed.platform or "").strip().lower()
        if platform_norm == 'android':
            pkg = getattr(project, 'androidApplicationId', None)
            if not pkg:
                Colored.PrintError(
                    f"Project '{project_name}' has no androidApplicationId. "
                    f"Set it via androidapplicationid(\"com.example.app\") in the .jenga file."
                )
                return 1

            adb = DeployCommand._ResolveAdb(workspace=workspace)
            if not adb:
                Colored.PrintError("adb not found. Set ANDROID_SDK_ROOT or add adb to PATH.")
                return 1

            # Si pas de --target, verifier qu'un seul device est connecte.
            target = parsed.target
            if not target:
                devices_result = Process.ExecuteCommand(
                    [str(adb), "devices"], captureOutput=True, silent=True)
                serials = []
                for line in (devices_result.stdout or "").splitlines():
                    s = line.strip()
                    if not s or s.startswith("List of devices"):
                        continue
                    parts = s.split()
                    if len(parts) >= 2 and parts[1] == "device":
                        serials.append(parts[0])
                if len(serials) == 0:
                    Colored.PrintError("No Android device connected.")
                    return 1
                if len(serials) > 1:
                    Colored.PrintError(
                        "Multiple Android devices connected. Specify --target SERIAL. Available:")
                    for s in serials:
                        Colored.PrintError(f"  - {s}")
                    return 1
                target = serials[0]

            # Lance via monkey (categorie LAUNCHER, marche pour NativeActivity).
            cmd = [str(adb), "-s", target,
                   "shell", "monkey", "-p", pkg,
                   "-c", "android.intent.category.LAUNCHER", "1"]
            Colored.PrintInfo(f"Launching {pkg} on {target}...")
            result = Process.ExecuteCommand(cmd, captureOutput=True, silent=True)
            if result.returnCode == 0:
                Colored.PrintSuccess(f"App launched: {pkg}")
                return 0
            Colored.PrintError(f"Failed to launch {pkg} on {target}.")
            if result.stderr:
                Colored.PrintError(result.stderr.strip())
            return 1
        is_test_project = bool(
            project.isTest
            or project.kind == Api.ProjectKind.TEST_SUITE
            or project.name == "__Unitest__"
        )

        if is_test_project and bool(getattr(workspace, "disableUnitTestExecution", False)):
            Colored.PrintError(
                "Unit-test execution is disabled by workspace policy "
                "(disableunittestexecution)."
            )
            return 1

        if parsed.build and is_test_project and bool(getattr(workspace, "disableUnitTestCompilation", False)):
            Colored.PrintError(
                "Unit-test compilation is disabled by workspace policy "
                "(disableunittestcompilation)."
            )
            return 1

        # Build si demandé explicitement (par défaut : skip build)
        if parsed.build:
            Colored.PrintInfo(f"Building {project_name}...")
            build_args = ["--config", parsed.config]
            build_args += ["--action", "run"]
            if parsed.platform:
                build_args += ["--platform", parsed.platform]
            if parsed.jenga_file:
                build_args += ["--jenga-file", str(entry_file)]
            build_args += ["--target", project_name]
            ret = BuildCommand.Execute(build_args)
            if ret != 0:
                return ret

        # Déterminer le chemin de l'exécutable
        # Il faut un builder pour connaître l'extension et le chemin exact
        try:
            builder = BuildCommand.CreateBuilder(
                workspace,
                config=parsed.config,
                platform=parsed.platform or (workspace.targetOses[0].value if workspace.targetOses else "Windows"),
                target=project_name,
                verbose=False,
                action="run",
                options=BuildCommand.CollectFilterOptions(
                    config=parsed.config,
                    platform=parsed.platform,
                    target=project_name,
                    verbose=False,
                    no_cache=False,
                    no_daemon=parsed.no_daemon,
                    extra=["action:run"]
                )
            )
        except Exception as e:
            Colored.PrintError(f"Cannot create builder: {e}")
            return 1

        exe_path = builder.GetTargetPath(project)
        if not exe_path.exists():
            Colored.PrintError(f"Executable not found: {exe_path}")
            return 1

        # ── WEB : « executer » = SERVIR puis ouvrir le navigateur ────────────
        # Un module WASM ne se lance pas comme un binaire, et file:// ne suffit
        # pas : le runtime charge .data et .wasm par XHR, interdits hors HTTP.
        # Jenga fait donc les deux gestes lui-meme — serveur local + navigateur
        # par defaut — au lieu d'exiger un script externe par plateforme :
        # webbrowser/http.server sont le « .bat ou .sh » universel de Python.
        if getattr(builder, "targetOs", None) == Api.TargetOS.WEB:
            return RunCommand._RunWeb(exe_path, parsed.args)

        # ── Frontiere VISIBLE entre construction et execution ────────────────
        # Tout arrive sur le meme flux : bannieres de build, compilation, puis la
        # sortie du programme. Sans marque, on ne sait plus ou commence ce qui
        # nous interesse vraiment — l'execution. D'ou un cadre net, et un bilan
        # de fin qui donne le code de sortie (jusqu'ici affiche nulle part) et la
        # duree du programme SEUL, sans le temps de construction.
        cmd = [str(exe_path)] + parsed.args
        # Binaire construit pour un AUTRE systeme que l'hote : tenter de le lancer
        # tel quel donnait un message incomprehensible de l'OS (sous Windows :
        # « [WinError 193] %1 n'est pas une application Win32 valide »). On passe
        # par WSL quand c'est possible, sinon on explique.
        cmd, note, chemin_affiche = RunCommand._AdapterAuHote(cmd, exe_path, builder)
        if cmd is None:
            Colored.PrintError(note)
            return 1
        largeur = 80
        depart = _time.time()  # chronometre le PROGRAMME, pas la construction
        ligne_args = (" " + " ".join(parsed.args)) if parsed.args else ""
        Colored.Print("")
        Colored.Print("━" * largeur, color="brightcyan")
        # `note` dit COMMENT on lance quand ce n'est pas en direct (ex. « via WSL »),
        # et `chemin_affiche` est le chemin REELLEMENT execute : sous WSL, montrer
        # le chemin Windows ferait chercher un probleme de chemin inexistant.
        suffixe = f"  ({note})" if note else ""
        Colored.Print(f"  ▶  EXECUTION  —  {exe_path.name}{ligne_args}{suffixe}", color="brightcyan", bold=True)
        Colored.Print(f"     {chemin_affiche}", color="cyan")
        Colored.Print("━" * largeur, color="brightcyan")
        Colored.Print("")

        # ── Application CONSOLE lancee SANS terminal interactif ──────────────
        #
        # Par defaut le programme herite des flux du parent. Depuis un vrai
        # terminal c'est ce qu'on veut. Mais lance depuis un IDE (NKCode) ou
        # tout appelant qui capture la sortie, il herite d'un TUBE : il n'a plus
        # de console. Une application console qui attend une saisie ne recoit
        # alors jamais rien — elle parait figee, puis echoue.
        #
        # Retour d'un utilisateur : « le running du programme s'affiche mais il
        # ne s'ouvre jamais dans le terminal et cela fait planter le programme ».
        # Son contournement — lancer le .exe a la main — confirmait que le
        # binaire etait bon et que seul le MODE DE LANCEMENT posait probleme.
        #
        # On ouvre donc une VRAIE console quand les trois conditions sont
        # reunies : Windows, projet de type console, et sortie non interactive.
        # Depuis un terminal (isatty vrai), le comportement ne change pas.
        if not parsed.no_console:
            try:
                import sys as _sys
                from ..Core.Platform import Platform as _Plat
                est_console = getattr(project, 'kind', None) == Api.ProjectKind.CONSOLE_APP
                sans_terminal = not _sys.stdout.isatty()
                if _Plat.GetHostOS() == Api.TargetOS.WINDOWS and est_console and sans_terminal:
                    import subprocess as _sp
                    Colored.PrintInfo("Application console sans terminal : ouverture d'une console dediee.")
                    # CREATE_NEW_CONSOLE : fenetre console propre, entrees
                    # clavier fonctionnelles. On ATTEND la fin, pour que le code
                    # de sortie reste celui du programme.
                    p = _sp.Popen(cmd, creationflags=0x00000010)  # CREATE_NEW_CONSOLE
                    return RunCommand._Bilan(p.wait(), _time.time() - depart, largeur)
            except Exception as e:
                # Jamais bloquant : en cas de souci on retombe sur le
                # comportement historique plutot que d'empecher l'execution.
                Colored.PrintWarning(f"Console dediee indisponible ({e}) — lancement standard.")

        # Vider NOS tampons avant de rendre la main au programme. Il ecrit
        # directement sur le descripteur, alors que les print() de Python sont
        # bufferises des que la sortie n'est pas un terminal : sans ce flush, la
        # sortie du programme apparait AVANT la banniere de construction.
        try:
            import sys as _s
            _s.stdout.flush()
            _s.stderr.flush()
        except Exception:  # noqa: BLE001
            pass
        return RunCommand._Bilan(Process.Run(cmd), _time.time() - depart, largeur)

    @staticmethod
    def _CheminWsl(p: Path) -> Optional[str]:
        """Traduit un chemin Windows en chemin WSL. `wslpath` fait autorite (il
        connait les points de montage reels) ; a defaut, conversion manuelle
        D:\\a\\b -> /mnt/d/a/b, qui couvre le cas courant."""
        try:
            r = Process.ExecuteCommand(["wsl", "wslpath", "-a", str(p)],
                                       captureOutput=True, silent=True)
            chemin = (r.stdout or "").strip()
            if r.returnCode == 0 and chemin:
                return chemin
        except Exception:  # noqa: BLE001
            pass
        s = str(p)
        if len(s) > 2 and s[1] == ":":
            return "/mnt/" + s[0].lower() + s[2:].replace("\\", "/")
        return None

    @staticmethod
    def _AdapterAuHote(cmd: List[str], exe_path: Path, builder) -> Tuple[Optional[List[str]], str, str]:
        """Adapte la commande quand le binaire ne vise PAS le systeme hote.

        Retourne (commande, note, chemin_affiche). Commande None = impossible,
        `note` explique. `chemin_affiche` est le chemin REELLEMENT execute — sous
        WSL ce n'est pas le chemin Windows, et afficher ce dernier ferait chercher
        un probleme de chemin la ou il n'y en a pas.
        Aujourd'hui : Linux depuis Windows via WSL. Les autres combinaisons
        (macOS depuis Windows, Windows depuis Linux...) n'ont pas d'equivalent
        universel — on le dit clairement plutot que d'echouer dans l'OS."""
        cible = getattr(builder, "targetOs", None)
        hote = Platform.GetHostOS()
        if cible is None or cible == hote:
            return cmd, "", str(exe_path)

        if cible == Api.TargetOS.LINUX and hote == Api.TargetOS.WINDOWS:
            # Deux echecs DIFFERENTS, qui ne se corrigent pas de la meme facon :
            # WSL absent (a installer) et WSL present mais sans distribution
            # (a installer, mais autre commande). Les confondre enverrait
            # l'utilisateur sur une fausse piste.
            presente, r = False, None
            try:
                r = Process.ExecuteCommand(["wsl", "--status"], captureOutput=True, silent=True)
                presente = True
            except Exception:  # noqa: BLE001
                presente = False
            if not presente:
                return None, ("Binaire Linux : WSL introuvable, impossible de l'executer sous Windows.\n"
                              "  Installez-le avec `wsl --install` (redemarrage requis) — Jenga s'en\n"
                              "  servira ensuite automatiquement — ou lancez le binaire sur une\n"
                              "  machine Linux."), ""
            if r is not None and r.returnCode != 0:
                return None, ("Binaire Linux : WSL est installe mais aucune distribution n'est prete.\n"
                              "  Installez-en une avec `wsl --install -d Ubuntu`, puis reessayez."), ""
            chemin = RunCommand._CheminWsl(exe_path)
            if not chemin:
                return None, (f"Binaire Linux : chemin non traduisible pour WSL ({exe_path})."), ""
            # Le chemin RETOURNE est celui reellement execute : l'afficher evite
            # de faire chercher un probleme de chemin la ou il n'y en a pas.
            return ["wsl", "--", chemin] + cmd[1:], "via WSL", chemin

        nom_cible = getattr(cible, "value", str(cible))
        nom_hote = getattr(hote, "value", str(hote))
        return None, (f"Binaire construit pour {nom_cible}, hote {nom_hote} : "
                      f"execution impossible ici.\n"
                      f"  Deployez-le sur une machine {nom_cible} "
                      f"(voir `jenga deploy`), ou construisez pour {nom_hote} "
                      f"avec --platform {nom_hote}."), ""

    @staticmethod
    def _RunWeb(html_path: Path, args: List[str]) -> int:
        """Sert le dossier des artefacts sur 127.0.0.1 et ouvre le navigateur.

        - Bind EXPLICITE sur 127.0.0.1 : un serveur IPv6-only rend la page
          inaccessible aux clients qui resolvent localhost en 127.0.0.1 (vecu :
          navigateur en ::1, outil headless en IPv4 — l'un charge, l'autre non).
        - Cache-Control: no-store : pendant le developpement, un .wasm en cache
          fait « tester » un build precedent sans que rien ne le signale.
        - COOP/COEP : sans effet aujourd'hui, indispensables le jour ou un build
          active les pthreads (SharedArrayBuffer exige l'isolation cross-origin).
        - Les arguments --cle=valeur deviennent des parametres d'URL (?cle=valeur),
          seul canal d'arguments d'une page : main.cpp les lit via URLSearchParams.
        - Chaque requete servie est journalisee : c'est la telemetrie qui dit ce
          que la page a REELLEMENT charge (.js sans .data/.wasm = echec precoce).
        """
        import http.server as _hs
        import webbrowser as _wb

        dossier = str(html_path.parent)
        largeur = 80

        parametres = []
        for a in args:
            morceau = a.lstrip("-")
            if morceau:
                parametres.append(morceau)
        query = "&".join(parametres)

        class _Handler(_hs.SimpleHTTPRequestHandler):
            def __init__(self, *a, **kw):
                super().__init__(*a, directory=dossier, **kw)

            def end_headers(self):
                self.send_header("Cache-Control", "no-store")
                self.send_header("Cross-Origin-Opener-Policy", "same-origin")
                self.send_header("Cross-Origin-Embedder-Policy", "require-corp")
                super().end_headers()

            def log_message(self, fmt, *a):
                Colored.Print("     " + (fmt % a), color="cyan")

        srv = _hs.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        port = srv.server_address[1]
        url = f"http://127.0.0.1:{port}/{html_path.name}"
        if query:
            url += f"?{query}"

        depart = _time.time()
        Colored.Print("")
        Colored.Print("━" * largeur, color="brightcyan")
        Colored.Print(f"  ▶  EXECUTION WEB  —  {html_path.name}", color="brightcyan", bold=True)
        Colored.Print(f"     {url}", color="cyan")
        Colored.Print("     Ctrl+C pour arreter le serveur.", color="cyan")
        Colored.Print("━" * largeur, color="brightcyan")
        Colored.Print("")
        # VIDAGE EXPLICITE : sys.stdout est bufferise en BLOC des qu'il n'est
        # plus un terminal (redirection vers fichier/pipe). serve_forever() ne
        # rend jamais la main -> sans ce flush, ces lignes restent coincees en
        # memoire pour toujours et l'URL n'apparait NULLE PART, alors que le
        # serveur tourne reellement. Vecu : 5 minutes d'attente sur un fichier
        # de sortie vide pendant que le serveur repondait deja aux requetes.
        sys.stdout.flush()
        _wb.open(url)
        try:
            srv.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            srv.server_close()
        return RunCommand._Bilan(0, _time.time() - depart, largeur)

    @staticmethod
    def _Bilan(code: int, duree: float, largeur: int) -> int:
        """Ferme le cadre d'execution : code de sortie et duree du PROGRAMME
        seul (le temps de construction n'y entre pas). Retourne `code`, pour
        s'inserer directement dans un `return`."""
        couleur = "brightgreen" if code == 0 else "brightred"
        etat = "termine normalement" if code == 0 else f"termine avec le code {code}"
        Colored.Print("")
        Colored.Print("━" * largeur, color=couleur)
        Colored.Print(f"  ◀  FIN D'EXECUTION  —  {etat}  ({duree:.2f}s)", color=couleur, bold=True)
        Colored.Print("━" * largeur, color=couleur)
        return code
