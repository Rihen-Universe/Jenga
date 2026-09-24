#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Deploy command – Déploie l'application sur des appareils (consoles, mobiles) ou sur des stores/testers.
Support : Android (adb), iOS (ios-deploy), Xbox (xbapp), HarmonyOS (hdc), etc.
"""

import argparse
import sys, shutil, os
from pathlib import Path
from typing import List, Optional

from ..Utils import Colored, Display, FileSystem, Process
from ..Core.Loader import Loader
from ..Core.Cache import Cache
from ..Core import Api


class DeployCommand:
    """jenga deploy [--platform PLATFORM] [--target DEVICE] [--config CONFIG] [--project PROJECT]
    Android direct install : jenga deploy --platform android --apk <file.apk> [--target SERIAL]
    HarmonyOS direct install : jenga deploy --platform harmonyos --hap <file.hap> [--target IP:PORT]
    """

    @staticmethod
    def Execute(args: List[str]) -> int:
        parser = argparse.ArgumentParser(
            prog="jenga deploy",
            description="Deploy app to device or store.")
        parser.add_argument(
            "--platform", required=True,
            choices=['android', 'ios', 'tvos', 'watchos',
                     'xbox', 'linux', 'macos', 'windows', 'harmonyos'],
            help="Target platform")
        parser.add_argument("--ios-builder", choices=["direct", "xcode", "xbuilder"], default=None,
                            help="Apple mobile builder backend (direct or xcode/xbuilder).")
        parser.add_argument("--target",
                            help="Device identifier (IP:PORT for HarmonyOS, serial for Android, UDID for iOS)")
        parser.add_argument("--device",
                            help="Alias for --target (device serial/identifier)")

        # Android flags
        parser.add_argument("--apk",
                            help="Direct APK path for Android install (skip build/project lookup)")
        parser.add_argument("--list-devices", action="store_true",
                            help="List connected devices (Android: adb, HarmonyOS: hdc) and exit")
        parser.add_argument("--detailed", action="store_true",
                            help="With --list-devices, show device details")
        parser.add_argument("--uninstall", action="store_true",
                            help="Uninstall existing app before installing (clean install)")
        parser.add_argument("--force-stop", action="store_true",
                            help="Android: force-stop existing app before installing (keeps data)")
        parser.add_argument("--run", action="store_true",
                            help="Launch the app after install")

        # HarmonyOS flags
        parser.add_argument("--hap",
                            help="Direct HAP path for HarmonyOS install (skip build/project lookup)")
        parser.add_argument("--ability",
                            help="HarmonyOS: EntryAbility name to launch (default: EntryAbility)")
        parser.add_argument("--bundle",
                            help="HarmonyOS/Android: bundle/package name override")

        parser.add_argument("--config", default="Release", help="Build configuration")
        parser.add_argument("--project", help="Project to deploy (default: first executable)")
        parser.add_argument("--no-daemon", action="store_true")
        parser.add_argument("--verbose", "-v", action="store_true")
        parser.add_argument("--jenga-file",
                            help="Path to the workspace .jenga file (default: auto-detected)")
        parsed = parser.parse_args(args)

        # Résolution alias --device → --target
        if parsed.device and not parsed.target:
            parsed.target = parsed.device
        elif parsed.device and parsed.target and parsed.device != parsed.target:
            Colored.PrintWarning("--device and --target both provided, using --target.")

        # ── HarmonyOS mode direct ─────────────────────────────────────────────
        if parsed.platform == 'harmonyos' and (parsed.list_devices or parsed.hap):
            return DeployCommand._HarmonyDirectMode(parsed)

        # ── Android mode direct ───────────────────────────────────────────────
        if parsed.platform == 'android' and (parsed.list_devices or parsed.apk):
            return DeployCommand._AndroidDirectMode(parsed)

        # ── Mode workspace (build + deploy) ──────────────────────────────────
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

        loader    = Loader(verbose=parsed.verbose)
        cache     = Cache(workspace_root, workspaceName=entry_file.stem)
        workspace = None

        if not parsed.no_daemon:
            from ..Core.Daemon import DaemonClient
            client = DaemonClient(workspace_root)
            if client.IsAvailable():
                try:
                    response = client.SendCommand('deploy', {
                        'platform': parsed.platform,
                        'target':   parsed.target,
                        'config':   parsed.config,
                        'project':  parsed.project,
                        'verbose':  parsed.verbose,
                    })
                    if response.get('status') == 'ok':
                        return response.get('return_code', 0)
                    Colored.PrintError(f"Daemon deploy failed: {response.get('message')}")
                    return 1
                except Exception as e:
                    Colored.PrintWarning(f"Daemon error: {e}, falling back.")

        if workspace is None:
            workspace = cache.LoadWorkspace(entry_file, loader)
        if workspace is None:
            workspace = loader.LoadWorkspace(str(entry_file))
            if workspace:
                cache.SaveWorkspace(workspace, entry_file, loader)

        if workspace is None:
            Colored.PrintError("Failed to load workspace.")
            return 1

        # Déterminer le projet cible
        project_name = parsed.project or workspace.startProject
        if not project_name:
            for name, proj in workspace.projects.items():
                if proj.kind in (Api.ProjectKind.CONSOLE_APP, Api.ProjectKind.WINDOWED_APP):
                    project_name = name
                    break
        if not project_name or project_name not in workspace.projects:
            Colored.PrintError(f"Project '{project_name}' not found.")
            return 1

        project = workspace.projects[project_name]

        dispatch = {
            'android':   DeployCommand._DeployAndroid,
            'harmonyos': DeployCommand._DeployHarmonyOS,
            'xbox':      DeployCommand._DeployXbox,
            'linux':     DeployCommand._DeployLinux,
            'macos':     DeployCommand._DeployMacOS,
            'windows':   DeployCommand._DeployWindows,
        }
        if parsed.platform in ('ios', 'tvos', 'watchos'):
            return DeployCommand._DeployIOS(workspace, project, parsed, parsed.platform)
        fn = dispatch.get(parsed.platform)
        if fn:
            return fn(workspace, project, parsed)

        Colored.PrintError(f"Deploy for platform '{parsed.platform}' not implemented.")
        return 1

    # =========================================================================
    # HarmonyOS — mode direct (--hap / --list-devices)
    # =========================================================================

    @staticmethod
    def _HarmonyDirectMode(parsed) -> int:
        """
        Mode direct HarmonyOS sans workspace.
        Équivalent du mode direct Android (--apk).

        Commandes hdc utilisées :
          hdc list targets              ← lister les devices
          hdc install <file.hap>        ← installer un HAP
          hdc uninstall <bundleName>    ← désinstaller avant
          hdc shell aa start ...        ← lancer l'app
          hdc shell hilog               ← logs (hors scope ici)
        """
        hdc = DeployCommand._ResolveHdc(workspace=None)
        if not hdc:
            Colored.PrintError(
                "hdc not found.\n"
                "Vérifiez que les HarmonyOS Command Line Tools sont installés dans C:/ohos/\n"
                "ou que hdc est dans le PATH.")
            return 1

        # ── --list-devices ────────────────────────────────────────────────────
        if parsed.list_devices:
            return DeployCommand._HarmonyListDevices(hdc, parsed)

        # ── --hap mode direct ────────────────────────────────────────────────
        if not parsed.hap:
            return 0

        hap_path = Path(parsed.hap).expanduser().resolve()
        if not hap_path.exists():
            Colored.PrintError(f"HAP not found: {hap_path}")
            return 1

        return DeployCommand._HarmonyInstallAndRun(
            hdc       = hdc,
            hap_path  = hap_path,
            target    = parsed.target,
            bundle    = parsed.bundle,
            ability   = parsed.ability or "EntryAbility",
            uninstall = parsed.uninstall,
            run       = parsed.run,
            verbose   = parsed.verbose,
        )

    @staticmethod
    def _HarmonyListDevices(hdc: Path, parsed) -> int:
        """
        Liste les devices HarmonyOS connectés (émulateurs et physiques).

        hdc list targets retourne des lignes du type :
          127.0.0.1:5555    ← émulateur local DevEco Studio
          192.168.x.x:5555  ← connexion WiFi
          <USB serial>      ← appareil physique USB
        """
        hdc_base = [str(hdc)]

        result = Process.ExecuteCommand(
            hdc_base + ["list", "targets"],
            captureOutput=True, silent=True)

        if result.returnCode != 0:
            Colored.PrintError("hdc list targets failed.")
            return 1

        output = (result.stdout or "").strip()
        if not output or output == "[Empty]":
            Colored.PrintWarning(
                "No HarmonyOS device/emulator found.\n"
                "  → Démarrer l'émulateur dans DevEco Studio : Tools → Device Manager\n"
                "  → Ou connecter un appareil Huawei en mode développeur")
            return 0

        targets = [l.strip() for l in output.splitlines() if l.strip()]

        if parsed.detailed:
            # Interroger chaque device pour obtenir le modèle via hdc shell
            headers = ("TARGET", "MODELE", "VERSION", "TYPE")
            rows    = []
            for target in targets:
                base = hdc_base + ["-t", target, "shell"]

                def _shell(cmd: str) -> str:
                    r = Process.ExecuteCommand(
                        base + cmd.split(),
                        captureOutput=True, silent=True)
                    return (r.stdout or "").strip() if r.returnCode == 0 else "?"

                model   = _shell("param get const.product.name")
                version = _shell("param get const.ohos.fullname")
                # Détecter si émulateur (adresse locale) ou physique
                dev_type = "emulator" if target.startswith("127.") else "device"
                rows.append((target, model or "?", version or "?", dev_type))

            widths = [
                max(len(h), max((len(r[i]) for r in rows), default=0))
                for i, h in enumerate(headers)
            ]
            sep      = "  "
            line_fmt = sep.join("{:<%d}" % w for w in widths)
            print(line_fmt.format(*headers))
            print(sep.join("-" * w for w in widths))
            for row in rows:
                print(line_fmt.format(*row))
        else:
            Colored.PrintInfo("HarmonyOS devices/emulators:")
            for t in targets:
                dev_type = " (emulator)" if t.startswith("127.") else " (device)"
                print(f"  {t}{dev_type}")

        return 0

    @staticmethod
    def _HarmonyInstallAndRun(
            hdc: Path,
            hap_path: Path,
            target: Optional[str],
            bundle: Optional[str],
            ability: str,
            uninstall: bool,
            run: bool,
            verbose: bool) -> int:
        """
        Installe un .hap sur un device HarmonyOS via hdc et optionnellement le lance.

        Équivalent de la séquence Android :
          adb install -r app.apk  →  hdc install app.hap
          adb shell am start ...  →  hdc shell aa start -a Ability -b bundleName
        """
        # Base hdc avec ou sans target
        hdc_base = [str(hdc)]
        if target:
            hdc_base += ["-t", target]

        # Résolution du bundleName (nécessaire pour --uninstall et --run)
        bundle_name = bundle or DeployCommand._GetHapBundleName(hap_path)

        # ── Désinstallation préalable ─────────────────────────────────────────
        if uninstall and bundle_name:
            Colored.PrintInfo(f"Uninstalling {bundle_name}...")
            result = Process.ExecuteCommand(
                hdc_base + ["uninstall", bundle_name],
                captureOutput=not verbose, silent=not verbose)
            if result.returnCode == 0:
                Colored.PrintInfo(f"  Uninstalled: {bundle_name}")
            else:
                Colored.PrintWarning(f"  Uninstall failed (maybe not installed): {bundle_name}")

        # ── Installation ──────────────────────────────────────────────────────
        Colored.PrintInfo(f"Installing {hap_path.name}...")
        result = Process.ExecuteCommand(
            hdc_base + ["install", str(hap_path)],
            captureOutput=False, silent=False)

        if result.returnCode != 0:
            Colored.PrintError(
                "hdc install failed.\n"
                "Causes fréquentes :\n"
                "  - Aucun émulateur démarré (jenga deploy --platform harmonyos --list-devices)\n"
                "  - Signature invalide ou absente\n"
                "  - Version SDK incompatible avec l'émulateur\n"
                "  - bundleName déjà installé sans --uninstall")
            return 1

        Colored.PrintSuccess(f"HAP installed: {hap_path.name}")

        # ── Lancement ─────────────────────────────────────────────────────────
        if run:
            if not bundle_name:
                Colored.PrintWarning(
                    "--run ignoré : bundleName introuvable.\n"
                    "  Utiliser --bundle com.votre.app pour forcer.")
                return 0

            ability_name = ability if ability else "EntryAbility"
            Colored.PrintInfo(f"Launching {bundle_name}/{ability_name}...")
            result = Process.ExecuteCommand(
                hdc_base + [
                    "shell", "aa", "start",
                    "-a", ability_name,
                    "-b", bundle_name,
                ],
                captureOutput=False, silent=False)

            if result.returnCode == 0:
                Colored.PrintSuccess(f"App launched: {bundle_name}")
            else:
                Colored.PrintError(f"Launch failed for {bundle_name}/{ability_name}.")
                return 1

        return 0

    @staticmethod
    def _GetHapBundleName(hap_path: Path) -> Optional[str]:
        """
        Extrait le bundleName depuis un .hap (qui est un ZIP contenant module.json).

        Équivalent de _GetApkPackageId() pour Android.
        Retourne None si introuvable (--run et --uninstall seront ignorés).
        """
        import zipfile, json

        try:
            with zipfile.ZipFile(hap_path, 'r') as zf:
                # Chercher pack.info ou module.json dans le HAP
                for candidate in ("pack.info", "module.json", "app.json"):
                    if candidate in zf.namelist():
                        data = json.loads(zf.read(candidate).decode("utf-8"))
                        # pack.info → packages[0].bundleName
                        if candidate == "pack.info":
                            pkgs = data.get("packages", [])
                            if pkgs:
                                return pkgs[0].get("bundleName")
                        # module.json / app.json → app.bundleName
                        app = data.get("app", {})
                        if app.get("bundleName"):
                            return app["bundleName"]
                        # module.json → module.bundleName (fallback)
                        module = data.get("module", {})
                        if module.get("bundleName"):
                            return module["bundleName"]
        except Exception:
            pass

        return None

    @staticmethod
    def _ResolveHdc(workspace=None) -> Optional[Path]:
        """
        Résout le chemin vers hdc (HarmonyOS Device Connector).

        Ordre de recherche :
          1. OHOS_SDK env var → remonter vers command-line-tools/bin/hdc
          2. harmonySdkPath depuis le workspace DSL
          3. C:/ohos/command-line-tools/bin/hdc (chemin par défaut Windows)
          4. hdc dans le PATH système
        """
        exe_name = "hdc.exe" if sys.platform == "win32" else "hdc"

        # 1. Variable d'environnement OHOS_SDK
        ohos_sdk = os.environ.get("OHOS_SDK", "")
        if ohos_sdk:
            # OHOS_SDK = .../sdk/default/openharmony → remonter 3 niveaux
            cli_tools = Path(ohos_sdk).parents[2]
            hdc = cli_tools / "bin" / exe_name
            if hdc.exists():
                return hdc

        # 2. harmonySdkPath depuis le workspace
        if workspace and hasattr(workspace, 'harmonySdkPath') and workspace.harmonySdkPath:
            sdk_path = Path(workspace.harmonySdkPath)
            cli_tools = sdk_path.parents[2]
            hdc = cli_tools / "bin" / exe_name
            if hdc.exists():
                return hdc

        # 3. Chemin par défaut Windows
        if sys.platform == "win32":
            default = Path("C:/ohos/command-line-tools/bin") / exe_name
            if default.exists():
                return default

        # 4. PATH système
        found = FileSystem.FindExecutable("hdc")
        return Path(found) if found else None

    # =========================================================================
    # HarmonyOS — mode workspace (build + deploy)
    # =========================================================================

    @staticmethod
    def _DeployHarmonyOS(workspace, project, parsed) -> int:
        """
        Build + deploy HarmonyOS complet depuis un workspace Jenga.

        Flux :
          1. jenga build --platform harmonyos-arm64
          2. Localiser le .hap généré
          3. hdc install + hdc shell aa start
        """
        hdc = DeployCommand._ResolveHdc(workspace)
        if not hdc:
            Colored.PrintError(
                "hdc not found. Vérifiez l'installation des HarmonyOS Command Line Tools.")
            return 1

        # ── Étape 1 : Build ───────────────────────────────────────────────────
        from .Build import BuildCommand
        build_args = [
            "--config",   parsed.config,
            "--action",   "deploy",
            "--platform", "harmonyos-arm64",
            "--target",   project.name,
        ]
        if parsed.jenga_file:
            build_args += ["--jenga-file", parsed.jenga_file]
        if BuildCommand.Execute(build_args) != 0:
            Colored.PrintError("Build failed, cannot deploy.")
            return 1

        # ── Étape 2 : Localiser le .hap ──────────────────────────────────────
        builder = BuildCommand.CreateBuilder(
            workspace, parsed.config, "harmonyos-arm64",
            project.name, parsed.verbose,
            action="deploy",
            options=BuildCommand.CollectFilterOptions(
                config      = parsed.config,
                platform    = "harmonyos-arm64",
                target      = project.name,
                verbose     = parsed.verbose,
                no_cache    = False,
                no_daemon   = parsed.no_daemon,
                extra       = ["action:deploy", "deploy:harmonyos"],
            )
        )

        target_dir = builder.GetTargetDir(project)
        hap_name   = f"{project.targetName or project.name}.hap"
        hap_path   = target_dir / hap_name

        if not hap_path.exists():
            Colored.PrintError(
                f"HAP not found: {hap_path}\n"
                "Le build a réussi mais hvigor n'a pas généré le .hap.\n"
                "Vérifiez la structure du projet dans le dossier harmony-build/.")
            return 1

        # Résoudre le bundleName depuis le projet DSL ou le HAP lui-même
        bundle_name = (
            parsed.bundle
            or getattr(project, 'harmonyBundleName', '')
            or DeployCommand._GetHapBundleName(hap_path)
        )
        ability_name = parsed.ability or "EntryAbility"

        # ── Étape 3 : Install + Run ───────────────────────────────────────────
        return DeployCommand._HarmonyInstallAndRun(
            hdc       = hdc,
            hap_path  = hap_path,
            target    = parsed.target,
            bundle    = bundle_name,
            ability   = ability_name,
            uninstall = parsed.uninstall,
            run       = parsed.run,
            verbose   = parsed.verbose,
        )

    # =========================================================================
    # Android
    # =========================================================================

    @staticmethod
    def _AndroidDirectMode(parsed) -> int:
        """Mode direct Android (--apk / --list-devices)."""
        adb = DeployCommand._ResolveAdb(workspace=None)
        if not adb:
            Colored.PrintError("adb not found. Set ANDROID_SDK_ROOT or add adb to PATH.")
            return 1

        if parsed.list_devices:
            if parsed.detailed:
                result = Process.ExecuteCommand(
                    [str(adb), "devices"], captureOutput=True, silent=True)
                if result.returnCode != 0:
                    Colored.PrintError("Failed to list adb devices.")
                    return 1
                serials = []
                for line in (result.stdout or "").splitlines():
                    s = line.strip()
                    if not s or s.startswith("List of devices"):
                        continue
                    parts = s.split()
                    if len(parts) >= 2 and parts[1] == "device":
                        serials.append(parts[0])
                if not serials:
                    Colored.PrintWarning("No Android device connected.")
                    if not parsed.apk:
                        return 0
                else:
                    def _getprop(serial: str, key: str) -> str:
                        r = Process.ExecuteCommand(
                            [str(adb), "-s", serial, "shell", "getprop", key],
                            captureOutput=True, silent=True)
                        return (r.stdout or "").strip() if r.returnCode == 0 else ""

                    rows    = []
                    headers = ("SERIAL", "MARQUE", "MODELE", "ANDROID", "ABI")
                    for serial in serials:
                        rows.append((
                            serial,
                            _getprop(serial, "ro.product.manufacturer") or "?",
                            _getprop(serial, "ro.product.model") or "?",
                            _getprop(serial, "ro.build.version.release") or "?",
                            _getprop(serial, "ro.product.cpu.abi") or "?",
                        ))
                    widths   = [max(len(h), max((len(r[i]) for r in rows), default=0))
                                for i, h in enumerate(headers)]
                    sep      = "  "
                    line_fmt = sep.join("{:<%d}" % w for w in widths)
                    print(line_fmt.format(*headers))
                    print(sep.join("-" * w for w in widths))
                    for row in rows:
                        print(line_fmt.format(*row))
            else:
                result = Process.ExecuteCommand(
                    [str(adb), "devices"], captureOutput=False, silent=False)
                if result.returnCode != 0:
                    Colored.PrintError("Failed to list adb devices.")
                    return 1

            if not parsed.apk:
                return 0

        apk_path = Path(parsed.apk).expanduser().resolve()
        if not apk_path.exists() or not apk_path.is_file():
            Colored.PrintError(f"APK not found: {apk_path}")
            return 1

        pkg_id   = parsed.bundle or DeployCommand._GetApkPackageId(adb, apk_path)
        adb_base = [str(adb)]
        if parsed.target:
            adb_base += ["-s", parsed.target]

        if parsed.uninstall and pkg_id:
            Colored.PrintInfo(f"Uninstalling existing {pkg_id}...")
            Process.ExecuteCommand(
                adb_base + ["uninstall", pkg_id],
                captureOutput=True, silent=True)

        if parsed.force_stop and pkg_id:
            Colored.PrintInfo(f"Force-stopping {pkg_id}...")
            Process.ExecuteCommand(
                adb_base + ["shell", "am", "force-stop", pkg_id],
                captureOutput=True, silent=True)

        if DeployCommand._AndroidInstall(adb, apk_path, parsed.target) != 0:
            return 1

        Colored.PrintSuccess(f"APK installed: {apk_path}")

        if parsed.run and pkg_id:
            Colored.PrintInfo(f"Launching {pkg_id}...")
            launch = Process.ExecuteCommand(
                adb_base + ["shell", "monkey", "-p", pkg_id,
                            "-c", "android.intent.category.LAUNCHER", "1"],
                captureOutput=True, silent=True)
            if launch.returnCode == 0:
                Colored.PrintSuccess(f"App launched: {pkg_id}")
            else:
                Colored.PrintError(f"Launch failed for {pkg_id}.")
                return 1

        return 0

    @staticmethod
    def _DeployAndroid(workspace, project, parsed) -> int:
        """Déploiement Android depuis workspace (build + adb install)."""
        adb = DeployCommand._ResolveAdb(workspace)
        if not adb:
            Colored.PrintError("adb not found.")
            return 1

        from .Build import BuildCommand
        build_args = [
            "--config", parsed.config, "--action", "deploy",
            "--platform", "Android", "--target", project.name,
        ]
        if parsed.jenga_file:
            build_args += ["--jenga-file", parsed.jenga_file]
        if BuildCommand.Execute(build_args) != 0:
            return 1

        builder = BuildCommand.CreateBuilder(
            workspace, parsed.config, "Android", project.name, parsed.verbose,
            action="deploy",
            options=BuildCommand.CollectFilterOptions(
                config=parsed.config, platform="Android", target=project.name,
                verbose=parsed.verbose, no_cache=False, no_daemon=parsed.no_daemon,
                extra=["action:deploy", "deploy:android"]))

        apk_path = builder.GetTargetDir(project) / f"{project.targetName or project.name}.apk"
        if not apk_path.exists():
            Colored.PrintError(f"APK not found: {apk_path}")
            return 1

        if DeployCommand._AndroidInstall(adb, apk_path, parsed.target) != 0:
            return 1
        Colored.PrintSuccess("APK installed successfully.")
        return 0

    # -----------------------------------------------------------------------
    # Installation Android : un echec se DIT avec sa cause.
    # Avant : "adb install failed." pour tout (autorisation revoquee, signature
    # incompatible, ABI absente, stockage plein...). L'information existe dans
    # la sortie d'adb ; on la lit au lieu de la jeter.
    # -----------------------------------------------------------------------

    # Code d'echec du gestionnaire de paquets -> (cause, geste a faire).
    # Point d'extension : ajouter une ligne ici pour tout nouveau code rencontre.
    _ADB_INSTALL_ERRORS = {
        "INSTALL_FAILED_UPDATE_INCOMPATIBLE":
            ("the installed app is signed with a different key",
             "uninstall it first (jenga deploy --uninstall, or adb uninstall <package>), then retry"),
        "INSTALL_FAILED_NO_MATCHING_ABIS":
            ("the APK contains no native library for this device's CPU ABI",
             "add the device ABI to androidabis() (arm64-v8a for almost every phone) and rebuild"),
        "INSTALL_FAILED_INSUFFICIENT_STORAGE":
            ("not enough free space on the device", "free some storage, then retry"),
        "INSTALL_FAILED_VERSION_DOWNGRADE":
            ("the installed app has a higher versionCode",
             "raise androidversioncode(), or uninstall the installed app first"),
        "INSTALL_FAILED_OLDER_SDK":
            ("the device Android version is older than androidminsdk()",
             "lower androidminsdk() or use a newer device"),
        "INSTALL_PARSE_FAILED_NO_CERTIFICATES":
            ("the APK is not signed",
             "check JAVA_HOME and ~/.android/debug.keystore, then rebuild"),
        "INSTALL_FAILED_INVALID_APK":
            ("the APK is malformed", "rebuild it and check the build log for packaging warnings"),
        "INSTALL_FAILED_USER_RESTRICTED":
            ("the device refused the install (USB install disabled or prompt declined)",
             "enable 'Install via USB' in developer options and accept the prompt on the device"),
        "INSTALL_FAILED_TEST_ONLY":
            ("the APK is marked test-only", "retry with: adb install -t"),
        "INSTALL_FAILED_DUPLICATE_PERMISSION":
            ("another installed app declares the same permission",
             "uninstall the conflicting app"),
        "INSTALL_FAILED_ALREADY_EXISTS":
            ("the app already exists and cannot be replaced", "uninstall it first"),
    }

    # Etat rendu par `adb devices` -> geste a faire.
    _ADB_DEVICE_STATES = {
        "unauthorized": "accept the USB debugging prompt on the device, then retry",
        "offline": "unplug and replug the device (or run: adb kill-server), then retry",
        "no permissions": "fix the udev rules for this device (Linux), then retry",
        "recovery": "reboot the device into Android, then retry",
        "bootloader": "reboot the device into Android, then retry",
        "sideload": "reboot the device into Android, then retry",
    }

    @staticmethod
    def _ParseAdbDevices(text: str) -> List[tuple]:
        """Lignes de `adb devices` -> [(serie, etat)]. L'etat peut contenir un espace."""
        devices = []
        for line in (text or "").splitlines():
            s = line.strip()
            if not s or s.startswith("List of devices") or s.startswith("*"):
                continue
            parts = s.split(None, 1)
            if len(parts) == 2:
                devices.append((parts[0], parts[1].strip()))
        return devices

    @staticmethod
    def _DiagnoseAdbInstall(output: str, where: str, returnCode: int) -> str:
        """Sortie d'`adb install` en echec -> message qui nomme la cause et le geste."""
        for code, (cause, hint) in DeployCommand._ADB_INSTALL_ERRORS.items():
            if code in output:
                return f"Deploy failed on {where}: {code} — {cause}; {hint}."
        for state, hint in DeployCommand._ADB_DEVICE_STATES.items():
            if f"device {state}" in output or f"device '{state}'" in output:
                return f"Deploy failed: {where} is '{state}' — {hint}."
        # Code inconnu : on le cite tel quel plutot que de le taire.
        reason = next((l.strip() for l in output.splitlines()
                       if "INSTALL_" in l or "Failure" in l or "error" in l.lower()), "")
        return f"Deploy failed on {where}: " + (reason or f"adb exited with code {returnCode}") + "."

    @staticmethod
    def _AndroidInstall(adb: Path, apk_path: Path, target: Optional[str]) -> int:
        """Installe un APK ; en cas d'echec, nomme l'appareil, la cause et le geste."""
        # 1. Etat des appareils AVANT d'installer : l'erreur d'adb sur un
        #    appareil non autorise est plus obscure que la notre.
        listing = Process.ExecuteCommand([str(adb), "devices"], captureOutput=True, silent=True)
        if listing.returnCode == 0:
            devices = DeployCommand._ParseAdbDevices(listing.stdout)
            if target:
                chosen = [d for d in devices if d[0] == target]
                if not chosen:
                    known = ", ".join(f"{d[0]} ({d[1]})" for d in devices) or "none"
                    Colored.PrintError(f"Deploy failed: device {target} is not connected. Connected: {known}.")
                    return 1
            else:
                if not devices:
                    Colored.PrintError("Deploy failed: no Android device connected — plug a device with USB debugging enabled, then retry.")
                    return 1
                if len(devices) > 1:
                    known = ", ".join(f"{d[0]} ({d[1]})" for d in devices)
                    Colored.PrintError(f"Deploy failed: {len(devices)} devices connected ({known}) — choose one with --target <serial>.")
                    return 1
                chosen = devices
            serial, state = chosen[0]
            if state != "device":
                hint = DeployCommand._ADB_DEVICE_STATES.get(state, "check the device, then retry")
                Colored.PrintError(f"Deploy failed: device {serial} is '{state}' — {hint}.")
                return 1
            target = serial

        # 2. Installation, sortie capturee puis re-affichee : on la montre ET on la lit.
        cmd = [str(adb)] + (["-s", target] if target else []) + ["install", "-r", str(apk_path)]
        result = Process.ExecuteCommand(cmd, captureOutput=True, silent=True)
        output = ((result.stdout or "") + "\n" + (result.stderr or "")).strip()
        if output:
            print(output)

        # adb a deja rendu 0 avec "Failure [...]" dans la sortie : la sortie fait foi.
        failed = result.returnCode != 0 or "Failure [" in output or "adb: failed to install" in output
        if not failed:
            return 0
        where = f"device {target}" if target else "the device"
        Colored.PrintError(DeployCommand._DiagnoseAdbInstall(output, where, result.returnCode))
        return 1

    @staticmethod
    def _GetApkPackageId(adb: Path, apk_path: Path) -> Optional[str]:
        """Extrait l'applicationId depuis un APK via aapt/aapt2."""
        sdk_path = os.environ.get("ANDROID_SDK_ROOT") or os.environ.get("ANDROID_HOME")
        candidates = []
        if sdk_path:
            bt_dir = Path(sdk_path) / "build-tools"
            if bt_dir.exists():
                versions = sorted(
                    [d for d in bt_dir.iterdir() if d.is_dir()], reverse=True)
                for v in versions:
                    for name in ("aapt2", "aapt"):
                        exe = v / (name + (".exe" if sys.platform == "win32" else ""))
                        if exe.exists():
                            candidates.append(exe)
                            break
                    if candidates:
                        break
        for tool in candidates:
            try:
                r = Process.ExecuteCommand(
                    [str(tool), "dump", "badging", str(apk_path)],
                    captureOutput=True, silent=True)
                if r.returnCode == 0 and r.stdout:
                    for line in r.stdout.splitlines():
                        if line.startswith("package:"):
                            i = line.find("name='")
                            if i >= 0:
                                j = line.find("'", i + 6)
                                if j > i:
                                    return line[i + 6:j]
            except Exception:
                continue
        return None

    @staticmethod
    def _ResolveAdb(workspace=None) -> Optional[Path]:
        """Résout le chemin vers adb."""
        sdk_path = None
        if workspace is not None:
            sdk_path = (workspace.androidSdkPath
                        or os.environ.get("ANDROID_SDK_ROOT")
                        or os.environ.get("ANDROID_HOME"))
        else:
            sdk_path = os.environ.get("ANDROID_SDK_ROOT") or os.environ.get("ANDROID_HOME")

        if sdk_path:
            for rel in (
                Path(sdk_path) / "platform-tools" / "adb",
                Path(sdk_path) / "adb",
            ):
                if sys.platform == "win32":
                    exe = Path(str(rel) + ".exe")
                    if exe.exists():
                        return exe
                if rel.exists():
                    return rel

        found = FileSystem.FindExecutable("adb")
        return Path(found) if found else None

    # =========================================================================
    # iOS / tvOS / watchOS
    # =========================================================================

    @staticmethod
    def _DeployIOS(workspace, project, parsed, apple_platform: str = "ios") -> int:
        """Déploiement Apple mobile (iOS/tvOS/watchOS)."""
        if Api.Platform.GetHostOS() != Api.TargetOS.MACOS:
            Colored.PrintError("Apple mobile deployment requires macOS.")
            return 1

        platform_token = {
            "ios":     "iOS",
            "tvos":    "tvOS",
            "watchos": "watchOS",
        }.get((apple_platform or "ios").lower(), "iOS")

        from .Build import BuildCommand
        build_args = [
            "--config", parsed.config, "--action", "deploy",
            "--platform", platform_token, "--target", project.name,
        ]
        if parsed.ios_builder:
            build_args += [f"--ios-builder={parsed.ios_builder}"]
        if parsed.jenga_file:
            build_args += ["--jenga-file", parsed.jenga_file]
        if BuildCommand.Execute(build_args) != 0:
            return 1

        extra_options = ["action:deploy", f"deploy:{apple_platform.lower()}"]
        if parsed.ios_builder:
            extra_options.append(f"ios-builder={parsed.ios_builder}")

        builder = BuildCommand.CreateBuilder(
            workspace, parsed.config, platform_token, project.name, parsed.verbose,
            action="deploy",
            options=BuildCommand.CollectFilterOptions(
                config=parsed.config, platform=platform_token, target=project.name,
                verbose=parsed.verbose, no_cache=False, no_daemon=parsed.no_daemon,
                extra=extra_options))

        app_bundle = builder.GetTargetDir(project) / f"{project.targetName or project.name}.app"
        if not app_bundle.exists():
            Colored.PrintError(f".app bundle not found: {app_bundle}")
            return 1

        target = (parsed.target or "").strip()

        if apple_platform.lower() == "ios":
            ios_deploy = FileSystem.FindExecutable("ios-deploy")
            if ios_deploy:
                cmd = [ios_deploy, "--bundle", str(app_bundle)]
                if target:
                    cmd += ["--id", target]
                result = Process.ExecuteCommand(cmd, captureOutput=False, silent=False)
                if result.returnCode == 0:
                    return 0
                Colored.PrintWarning("ios-deploy failed, trying simctl.")

        xcrun = FileSystem.FindExecutable("xcrun")
        if not xcrun:
            Colored.PrintError("xcrun not found. Install Xcode command line tools.")
            return 1

        sim_target = target or "booted"
        result_install = Process.ExecuteCommand(
            [xcrun, "simctl", "install", sim_target, str(app_bundle)],
            captureOutput=False, silent=False)
        if result_install.returnCode != 0:
            Colored.PrintError("simctl install failed.")
            return 1

        bundle_id = (project.iosBundleId or "").strip()
        if bundle_id:
            Process.ExecuteCommand(
                [xcrun, "simctl", "launch", sim_target, bundle_id],
                captureOutput=False, silent=False)
        return 0

    # =========================================================================
    # Xbox
    # =========================================================================

    @staticmethod
    def _DeployXbox(workspace, project, parsed) -> int:
        """Déploiement sur Xbox via xbapp."""
        try:
            from ..Core.Builders.Xbox import XboxBuilder
        except ImportError:
            Colored.PrintError("XboxBuilder not available.")
            return 1

        from .Build import BuildCommand
        build_args = [
            "--config", parsed.config, "--action", "deploy",
            "--platform", "Xbox", "--target", project.name,
        ]
        if parsed.jenga_file:
            build_args += ["--jenga-file", parsed.jenga_file]
        if BuildCommand.Execute(build_args) != 0:
            return 1

        builder = BuildCommand.CreateBuilder(
            workspace, parsed.config, "Xbox", project.name, parsed.verbose,
            action="deploy",
            options=BuildCommand.CollectFilterOptions(
                config=parsed.config, platform="Xbox", target=project.name,
                verbose=parsed.verbose, no_cache=False, no_daemon=parsed.no_daemon,
                extra=["action:deploy", "deploy:xbox"]))

        layout_dir = builder.GetTargetDir(project) / builder.xbox_platform
        if not layout_dir.exists():
            Colored.PrintError("Xbox layout directory not found.")
            return 1

        return 0 if builder.DeployToConsole(project, layout_dir, parsed.target) else 1

    # =========================================================================
    # Linux / macOS / Windows
    # =========================================================================

    @staticmethod
    def _DeployLinux(workspace, project, parsed) -> int:
        """Déploiement Linux (build + copie locale ou remote scp)."""
        from .Build import BuildCommand
        build_args = [
            "--config", parsed.config, "--action", "deploy",
            "--platform", "Linux", "--target", project.name,
        ]
        if parsed.jenga_file:
            build_args += ["--jenga-file", parsed.jenga_file]
        if BuildCommand.Execute(build_args) != 0:
            return 1

        builder = BuildCommand.CreateBuilder(
            workspace, parsed.config, "Linux", project.name, parsed.verbose,
            action="deploy",
            options=BuildCommand.CollectFilterOptions(
                config=parsed.config, platform="Linux", target=project.name,
                verbose=parsed.verbose, no_cache=False, no_daemon=parsed.no_daemon,
                extra=["action:deploy", "deploy:linux"]))

        exe_path = builder.GetTargetPath(project)
        if not exe_path.exists():
            Colored.PrintError(f"Executable not found: {exe_path}")
            return 1

        target = (parsed.target or "").strip()
        if not target:
            Colored.PrintSuccess(f"Linux deploy ready: {exe_path}")
            return 0

        if ":" in target and not target.startswith("/"):
            scp = FileSystem.FindExecutable("scp")
            if not scp:
                Colored.PrintError("scp not found for remote Linux deployment.")
                return 1
            result = Process.ExecuteCommand(
                [scp, str(exe_path), target], captureOutput=False, silent=False)
            if result.returnCode == 0:
                Colored.PrintSuccess(f"Linux deploy copied to {target}")
                return 0
            return 1

        dst_dir = Path(target).expanduser().resolve()
        FileSystem.MakeDirectory(dst_dir)
        shutil.copy2(exe_path, dst_dir / exe_path.name)
        Colored.PrintSuccess(f"Linux deploy copied to {dst_dir / exe_path.name}")
        return 0

    @staticmethod
    def _DeployMacOS(workspace, project, parsed) -> int:
        """Déploiement macOS (copie locale)."""
        from .Build import BuildCommand
        build_args = [
            "--config", parsed.config, "--action", "deploy",
            "--platform", "macOS", "--target", project.name,
        ]
        if parsed.jenga_file:
            build_args += ["--jenga-file", parsed.jenga_file]
        if BuildCommand.Execute(build_args) != 0:
            return 1

        builder = BuildCommand.CreateBuilder(
            workspace, parsed.config, "macOS", project.name, parsed.verbose,
            action="deploy",
            options=BuildCommand.CollectFilterOptions(
                config=parsed.config, platform="macOS", target=project.name,
                verbose=parsed.verbose, no_cache=False, no_daemon=parsed.no_daemon,
                extra=["action:deploy", "deploy:macos"]))

        app_bundle = builder.GetTargetDir(project) / f"{project.targetName or project.name}.app"
        if app_bundle.exists():
            Colored.PrintInfo(f"Application built at: {app_bundle}")
            if parsed.target == "/Applications":
                dest = Path("/Applications") / app_bundle.name
                shutil.copytree(app_bundle, dest, dirs_exist_ok=True)
                Colored.PrintSuccess(f"App installed to {dest}")
        return 0

    @staticmethod
    def _DeployWindows(workspace, project, parsed) -> int:
        """Déploiement Windows (copie locale)."""
        from .Build import BuildCommand
        build_args = [
            "--config", parsed.config, "--action", "deploy",
            "--platform", "Windows", "--target", project.name,
        ]
        if parsed.jenga_file:
            build_args += ["--jenga-file", parsed.jenga_file]
        if BuildCommand.Execute(build_args) != 0:
            return 1

        builder = BuildCommand.CreateBuilder(
            workspace, parsed.config, "Windows", project.name, parsed.verbose,
            action="deploy",
            options=BuildCommand.CollectFilterOptions(
                config=parsed.config, platform="Windows", target=project.name,
                verbose=parsed.verbose, no_cache=False, no_daemon=parsed.no_daemon,
                extra=["action:deploy", "deploy:windows"]))

        exe_path = builder.GetTargetPath(project)
        if exe_path.exists():
            Colored.PrintInfo(f"Executable built at: {exe_path}")
        return 0