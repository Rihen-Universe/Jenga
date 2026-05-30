#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Build command – Compile le workspace ou un projet spécifique.
Utilise le daemon s'il est actif, sinon exécute un build direct.
"""

import argparse
import sys
from pathlib import Path
from typing import Dict, List, Optional

from ..Core.Builder import Builder
from ..Core.Platform import Platform
from ..Core.Cache import Cache
from ..Core.Loader import Loader
from ..Core.State import BuildState
from ..Utils import Colored, Reporter, FileSystem
from ..Core import Api


class BuildCommand:
    """jenga build [--config NAME] [--platform NAME] [--target PROJECT] [--action NAME] [--no-cache] [--verbose]"""
    ALL_PLATFORMS_TOKEN = "jengaall"

    @staticmethod
    def NormalizeOptionTrigger(trigger: str) -> str:
        token = str(trigger or "").strip().lower()
        if token.startswith("--"):
            token = token[2:]
        return token

    @staticmethod
    def ParseCustomOptionArgs(raw_args: List[str]) -> Dict[str, Optional[str]]:
        """
        Parse CLI unknown args into custom option map.
        Supports:
          --feature
          --feature=value
          --feature value
          --no-feature
        """
        custom: Dict[str, Optional[str]] = {}
        i = 0
        while i < len(raw_args):
            token = raw_args[i]
            if not token.startswith("--"):
                raise ValueError(f"Unknown argument: {token}")

            body = token[2:]
            if not body:
                raise ValueError(f"Invalid option token: {token}")

            value: Optional[str] = None
            if "=" in body:
                trigger, raw_value = body.split("=", 1)
                value = raw_value
            elif body.startswith("no-") and len(body) > 3:
                trigger = body[3:]
                value = "false"
            else:
                trigger = body
                # `--opt value` form
                if i + 1 < len(raw_args) and not raw_args[i + 1].startswith("-"):
                    value = raw_args[i + 1]
                    i += 1

            trigger = BuildCommand.NormalizeOptionTrigger(trigger)
            if not trigger:
                raise ValueError(f"Invalid option trigger in token: {token}")
            custom[trigger] = value
            i += 1
        return custom

    @staticmethod
    def _OptionValueIsTruthy(value: Optional[str]) -> bool:
        if value is None:
            return True
        return str(value).strip().lower() not in ("0", "false", "off", "no")

    @staticmethod
    def ResolveWorkspaceOptions(workspace, cli_options: Optional[Dict[str, Optional[str]]] = None) -> Dict[str, Optional[str]]:
        """
        Merge workspace `newoption(...)` defaults with CLI-provided custom options.
        CLI values always override defaults.
        """
        resolved: Dict[str, Optional[str]] = {}
        definitions = dict(getattr(workspace, "options", {}) or {})
        normalized_cli: Dict[str, Optional[str]] = {}
        for key, value in (cli_options or {}).items():
            trigger = BuildCommand.NormalizeOptionTrigger(key)
            if trigger:
                normalized_cli[trigger] = value

        # Apply defaults from DSL declarations.
        for trigger, meta in definitions.items():
            norm_trigger = BuildCommand.NormalizeOptionTrigger(trigger)
            if not norm_trigger:
                continue
            if norm_trigger in normalized_cli:
                continue
            if not isinstance(meta, dict):
                continue
            if "default" not in meta:
                continue
            default_value = meta.get("default")
            if default_value is None:
                continue
            if isinstance(default_value, bool):
                if default_value:
                    resolved[norm_trigger] = None
                continue
            default_text = str(default_value).strip()
            if not default_text:
                continue
            resolved[norm_trigger] = default_text

        # Apply CLI values.
        resolved.update(normalized_cli)

        # Validate declared options.
        for trigger, meta in definitions.items():
            norm_trigger = BuildCommand.NormalizeOptionTrigger(trigger)
            if not norm_trigger or norm_trigger not in resolved:
                continue
            if not isinstance(meta, dict):
                continue

            value_key = str(meta.get("value", "") or "").strip()
            value = resolved[norm_trigger]
            if value_key and (value is None or not str(value).strip()):
                raise ValueError(f"Option '--{norm_trigger}' requires a value.")

            allowed = list(meta.get("allowed") or [])
            if allowed and value is not None:
                allowed_norm = {str(v).strip().lower() for v in allowed}
                if str(value).strip().lower() not in allowed_norm:
                    raise ValueError(
                        f"Invalid value for '--{norm_trigger}': {value}. "
                        f"Allowed: {', '.join(str(v) for v in allowed)}"
                    )

        return resolved

    @staticmethod
    def OptionValuesToTokens(option_values: Optional[Dict[str, Optional[str]]]) -> List[str]:
        """
        Convert custom option map to filter tokens.
        Example:
          {'with-sdl': '/opt/sdl3', 'asan': None} ->
            ['asan', 'with-sdl', 'with-sdl=/opt/sdl3']
        """
        tokens: List[str] = []
        for trigger, raw_value in (option_values or {}).items():
            norm_trigger = BuildCommand.NormalizeOptionTrigger(trigger)
            if not norm_trigger:
                continue
            if BuildCommand._OptionValueIsTruthy(raw_value):
                tokens.append(norm_trigger)
            if raw_value is not None:
                tokens.append(f"{norm_trigger}={str(raw_value).strip()}")
        return tokens

    @staticmethod
    def ResolveAppleMobileBuilderMode(workspace,
                                      target: Optional[str],
                                      options: Optional[List[str]]) -> str:
        """
        Resolve Apple mobile builder backend.
        Default: direct (option 1).
        Supported tokens in options:
          - ios-builder=direct|xcode|1|2
          - apple-builder=direct|xcode|1|2
          - xbuilder / xcode / direct
        """
        mode = "direct"

        # Optional project-level preference from DSL/data model.
        project_mode = ""
        if workspace:
            selected_project = None
            if target and target in workspace.projects:
                selected_project = workspace.projects[target]
            elif workspace.startProject and workspace.startProject in workspace.projects:
                selected_project = workspace.projects[workspace.startProject]
            elif len(workspace.projects) == 1:
                selected_project = next(iter(workspace.projects.values()))

            if selected_project is not None:
                project_mode = str(getattr(selected_project, "iosBuildSystem", "") or "").strip().lower()
                if project_mode in ("2", "xcode", "xbuilder"):
                    mode = "xcode"
                elif project_mode in ("1", "direct"):
                    mode = "direct"

        for token in (options or []):
            opt = str(token or "").strip().lower()
            if not opt:
                continue
            if opt in ("xcode", "xbuilder", "2", "ios-builder:xcode", "apple-builder:xcode", "ios-builder:2", "apple-builder:2"):
                mode = "xcode"
                continue
            if opt in ("direct", "1", "ios-builder:direct", "apple-builder:direct", "ios-builder:1", "apple-builder:1"):
                mode = "direct"
                continue

            if "=" in opt:
                key, value = opt.split("=", 1)
                key = key.strip()
                value = value.strip()
                if key in ("ios-builder", "apple-builder", "ios-build-system", "apple-build-system"):
                    if value in ("xcode", "xbuilder", "2"):
                        mode = "xcode"
                    elif value in ("direct", "1"):
                        mode = "direct"
        return mode

    @staticmethod
    def CreateBuilder(workspace,
                      config: str,
                      platform: str,
                      target: Optional[str],
                      verbose: bool,
                      action: str = "build",
                      options: Optional[List[str]] = None,
                      jobs: int = 0) -> Builder:
        """Crée un builder pour la configuration et la plateforme spécifiées."""
        # Déterminer la cible à partir de la plateforme
        target_os = None
        target_arch = None
        target_env = None

        if platform:
            parts = platform.split('-')
            os_name = parts[0]
            for os_enum in Api.TargetOS:
                if os_enum.value.lower() == os_name.lower():
                    target_os = os_enum
                    break
            if target_os is None and hasattr(Api, "_NormalizeOSName"):
                try:
                    normalized_os = Api._NormalizeOSName(os_name)
                    target_os = Api.TargetOS[normalized_os]
                except Exception:
                    target_os = None
            if len(parts) > 1:
                arch_name = parts[1]
                for arch_enum in Api.TargetArch:
                    if arch_enum.value.lower() == arch_name.lower():
                        target_arch = arch_enum
                        break
                if target_arch is None and hasattr(Api, "_NormalizeArchName"):
                    try:
                        normalized_arch = Api._NormalizeArchName(arch_name)
                        target_arch = Api.TargetArch[normalized_arch]
                    except Exception:
                        target_arch = None
            if len(parts) > 2:
                env_name = parts[2]
                for env_enum in Api.TargetEnv:
                    if env_enum.value.lower() == env_name.lower():
                        target_env = env_enum
                        break
                if target_env is None and hasattr(Api, "_NormalizeEnvName"):
                    try:
                        normalized_env = Api._NormalizeEnvName(env_name)
                        target_env = Api.TargetEnv[normalized_env]
                    except Exception:
                        target_env = None

        # Valeurs par défaut
        if target_os is None:
            if workspace.targetOses:
                host_os = Platform.GetHostOS()
                target_os = host_os if host_os in workspace.targetOses else workspace.targetOses[0]
            else:
                target_os = Platform.GetHostOS()
        if target_arch is None:
            if workspace.targetArchs:
                host_arch = Platform.GetHostArchitecture()
                target_arch = host_arch if host_arch in workspace.targetArchs else workspace.targetArchs[0]
            else:
                target_arch = Platform.GetHostArchitecture()
        # Leave env unspecified unless explicitly requested in --platform.
        # This lets resolver prefer the best matching toolchain (e.g. mingw clang++).
        if target_env is None:
            target_env = None

        # Utiliser le système de résolution des builders
        from ..Core.Builders import get_builder_class
        apple_mode = BuildCommand.ResolveAppleMobileBuilderMode(workspace, target, options)
        builder_class = get_builder_class(target_os.value, apple_mobile_mode=apple_mode)
        if not builder_class:
            raise RuntimeError(f"Unsupported target platform: {target_os.value}")

        try:
            builder = builder_class(
                workspace=workspace,
                config=config,
                platform=platform,
                targetOs=target_os,
                targetArch=target_arch,
                targetEnv=target_env,
                verbose=verbose,
                action=action,
                options=options or []
            )
            builder.jobs = jobs  # Set parallel jobs count
            return builder
        except TypeError as e:
            # Backward compatibility: some concrete builders still expose the old __init__ signature.
            msg = str(e)
            if "unexpected keyword argument 'action'" not in msg and "unexpected keyword argument 'options'" not in msg:
                raise
            builder = builder_class(
                workspace=workspace,
                config=config,
                platform=platform,
                targetOs=target_os,
                targetArch=target_arch,
                targetEnv=target_env,
                verbose=verbose
            )
            builder.action = (action or "build").strip().lower()
            builder.options = sorted({str(opt).strip().lower() for opt in (options or []) if str(opt).strip()})
            builder.jobs = jobs  # Set parallel jobs count
            if getattr(builder, "_expander", None) is not None:
                cfg = dict(getattr(builder._expander, "_config", {}) or {})
                cfg["action"] = builder.action
                cfg["options"] = " ".join(builder.options)
                builder._expander.SetConfig(cfg)
            return builder

    @staticmethod
    def CollectFilterOptions(config: str,
                             platform: Optional[str],
                             target: Optional[str],
                             verbose: bool,
                             no_cache: bool,
                             no_daemon: bool,
                             extra: Optional[List[str]] = None,
                             custom_option_values: Optional[Dict[str, Optional[str]]] = None) -> List[str]:
        """
        Build a list of option tokens usable by filter("options:...").
        Example tokens: verbose, no-cache, config:Debug, platform:Windows-x86_64, target:Sandbox.
        """
        opts: List[str] = []
        if verbose:
            opts.append("verbose")
        if no_cache:
            opts.append("no-cache")
        if no_daemon:
            opts.append("no-daemon")
        if config:
            opts.append(f"config:{config}")
        if platform:
            opts.append(f"platform:{platform}")
        if target:
            opts.append(f"target:{target}")
        if custom_option_values:
            opts.extend(BuildCommand.OptionValuesToTokens(custom_option_values))
        if extra:
            opts.extend([str(x).strip() for x in extra if str(x).strip()])
        # normalize + unique
        dedup = sorted({x.lower() for x in opts})
        return dedup

    @staticmethod
    def IsAllPlatformsRequest(platform: Optional[str]) -> bool:
        """True si --platform jengaall a été demandé."""
        return bool(platform) and platform.strip().lower() == BuildCommand.ALL_PLATFORMS_TOKEN

    @staticmethod
    def GetAllDeclaredPlatforms(workspace) -> List[str]:
        """
        Génère la liste des plateformes à construire pour jengaall
        à partir des target OS et architectures déclarés.
        """
        oses = workspace.targetOses or [Platform.GetHostOS()]
        archs = workspace.targetArchs or [Platform.GetHostArchitecture()]

        platforms: List[str] = []
        for os_enum in oses:
            os_name = os_enum.value if hasattr(os_enum, "value") else str(os_enum)
            for arch_enum in archs:
                arch_name = arch_enum.value if hasattr(arch_enum, "value") else str(arch_enum)
                platform_name = f"{os_name}-{arch_name}" if arch_name else os_name
                if platform_name not in platforms:
                    platforms.append(platform_name)
        return platforms

    @staticmethod
    def BuildAcrossPlatforms(workspace, config: str, platforms: List[str],
                             target: Optional[str], verbose: bool,
                             action: str = "build",
                             options: Optional[List[str]] = None,
                             jobs: int = 0) -> int:
        """
        Build séquentiel sur plusieurs plateformes.
        Continue même si une plateforme échoue, puis renvoie un code global.
        """
        if not platforms:
            Colored.PrintError("No platform available for --platform jengaall.")
            return 1

        Colored.PrintInfo(f"Building across {len(platforms)} platform(s): {', '.join(platforms)}")
        failures = 0

        for idx, platform_name in enumerate(platforms, start=1):
            Colored.PrintInfo(f"\n[{idx}/{len(platforms)}] Building platform: {platform_name}")
            try:
                builder = BuildCommand.CreateBuilder(
                    workspace,
                    config=config,
                    platform=platform_name,
                    target=target,
                    verbose=verbose,
                    action=action,
                    options=(options or []) + [f"platform:{platform_name}"],
                    jobs=jobs
                )
            except Exception as e:
                failures += 1
                Colored.PrintError(f"[{platform_name}] Cannot create builder: {e}")
                continue

            ret = builder.Build(target)
            if ret != 0:
                failures += 1
                Colored.PrintError(f"[{platform_name}] Build failed.")
            else:
                Colored.PrintSuccess(f"[{platform_name}] Build succeeded.")

        if failures:
            Colored.PrintError(f"Multi-platform build finished with {failures} failure(s).")
            return 1

        Colored.PrintSuccess("Multi-platform build succeeded.")
        return 0

    @staticmethod
    def Execute(args: List[str]) -> int:
        """Point d'entrée CLI. Wrap Reset + résumé warnings/erreurs en queue,
        puis délègue le travail réel à _ExecuteCore."""
        from ..Utils.Reporter import Reporter
        Reporter.Reset()
        rc = 1
        try:
            rc = BuildCommand._ExecuteCore(args)
            return rc
        finally:
            # Résumé final (warnings critiques / errors / warnings) en encadré
            # visible, après packaging APK/MSI/... — visible même au milieu de
            # 1000 lignes de logs. No-op si rien à dire.
            Reporter.PrintCollectedSummary()
            # Politique : si des warnings critiques ont été levés et le build
            # est resté à 0, on n'élève PAS automatiquement le code pour
            # rester compat avec l'existant. Le résumé suffit à attirer l'œil.

    @staticmethod
    def _ExecuteCore(args: List[str]) -> int:

        parser = argparse.ArgumentParser(prog="jenga build", description="Build the workspace or a specific project.")
        parser.add_argument("--config", default="Debug", help="Build configuration (Debug, Release, etc.)")
        parser.add_argument("--platform", default=None, help="Target platform (Windows, Linux, Android-arm64, etc.) or 'jengaall'")
        parser.add_argument("--target", default=None, help="Specific project to build")
        parser.add_argument("--action", default="build", help="Action context for filters (default: build)")
        parser.add_argument("--android-build-system", choices=["native", "ndk-mk"], default=None,
                            help="Android build mode override (default: native)")
        parser.add_argument("--use-android-mk", action="store_true",
                            help="Shortcut for --android-build-system ndk-mk")
        parser.add_argument("--android-ndk-mk-mode", choices=["split", "universal", "both"], default=None,
                            help="ndk-mk APK output mode: split, universal, or both (default: auto)")
        parser.add_argument("--android-abis", default=None,
                            help="Override Android ABIs (comma-separated): armeabi-v7a,arm64-v8a,x86,x86_64")
        parser.add_argument("--no-cache", action="store_true", help="Ignore cache and reload workspace")
        parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
        parser.add_argument("--no-daemon", action="store_true", help="Do not use daemon even if available")
        parser.add_argument("--jobs", "-j", type=int, default=0,
                            help="Number of parallel compilation jobs (0 = auto-detect CPU cores, 1 = sequential)")
        parser.add_argument("--jenga-file", help="Path to the workspace .jenga file (default: auto-detected)")
        parsed, unknown_args = parser.parse_known_args(args)
        try:
            cli_custom_options = BuildCommand.ParseCustomOptionArgs(unknown_args)
        except ValueError as e:
            Colored.PrintError(str(e))
            return 1
        if parsed.android_build_system:
            cli_custom_options["android-build-system"] = parsed.android_build_system
        if parsed.use_android_mk:
            cli_custom_options["android-build-system"] = "ndk-mk"
        if parsed.android_ndk_mk_mode:
            cli_custom_options["android-ndk-mk-mode"] = parsed.android_ndk_mk_mode
        if parsed.android_abis:
            cli_custom_options["android-abis"] = parsed.android_abis

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

        # ── Auto-config IDE (silencieuse + idempotente) ─────────────────────
        # Configure VSCode/Cursor/Windsurf + pyrightconfig.json pour que les
        # fichiers *.jenga aient coloration syntaxique Python + autocomplete.
        # No-op si la config est deja a jour (verif par marker).
        # Desactiver via JENGA_NO_IDE_CONFIG=1.
        try:
            from ..Core.IDEConfigurator import AutoConfigure
            AutoConfigure(workspace_root, force=False, verbose=False)
        except Exception:
            # On ne fait JAMAIS echouer le build pour une erreur IDE setup.
            pass

        if BuildCommand.IsAllPlatformsRequest(parsed.platform):
            # Multi-platform orchestration is done in direct mode from CLI.
            parsed.no_daemon = True

        daemon_filter_options = BuildCommand.CollectFilterOptions(
            config=parsed.config,
            platform=parsed.platform,
            target=parsed.target,
            verbose=parsed.verbose,
            no_cache=parsed.no_cache,
            no_daemon=parsed.no_daemon,
            extra=[f"action:{parsed.action}"],
            custom_option_values=cli_custom_options
        )

        # Essayer d'utiliser le daemon si disponible
        if not parsed.no_daemon:
            from ..Core.Daemon import DaemonClient, Daemon
            client = DaemonClient(workspace_root)
            if client.IsAvailable():
                Colored.PrintInfo("Using build daemon...")
                try:
                    response = client.SendCommand('build', {
                        'config': parsed.config,
                        'platform': parsed.platform,
                        'target': parsed.target,
                        'verbose': parsed.verbose,
                        'no_cache': parsed.no_cache,
                        'options': daemon_filter_options,
                        'custom_options': cli_custom_options,
                        'action': parsed.action,
                    })
                    if response.get('status') == 'ok':
                        return response.get('return_code', 0)
                    else:
                        Colored.PrintError(f"Daemon build failed: {response.get('message')}")
                        return 1
                except Exception as e:
                    Colored.PrintWarning(f"Daemon communication failed: {e}. Falling back to direct build.")

        # Direct build (sans daemon)
        # 1. Charger le workspace (avec cache si non --no-cache)
        loader = Loader(verbose=parsed.verbose)
        cache = Cache(workspace_root)

        loaded_from_cache = False

        if parsed.no_cache:
            cache.Invalidate()
            workspace = loader.LoadWorkspace(str(entry_file))
            if workspace:
                cache.SaveWorkspace(workspace, entry_file, loader)
        else:
            workspace = cache.LoadWorkspace(entry_file, loader)
            loaded_from_cache = workspace is not None
            if workspace is None:
                Colored.PrintInfo("Loading workspace...")
                workspace = loader.LoadWorkspace(str(entry_file))
                if workspace:
                    cache.SaveWorkspace(workspace, entry_file, loader)

        if workspace is None:
            Colored.PrintError("Failed to load workspace.")
            return 1

        try:
            custom_option_values = BuildCommand.ResolveWorkspaceOptions(workspace, cli_custom_options)
        except ValueError as e:
            Colored.PrintError(str(e))
            return 1

        declared_options = dict(getattr(workspace, "options", {}) or {})
        if declared_options:
            builtin_custom_options = {
                "android-build-system",
                "android-ndk-mk-mode",
                "android-ndk-mk-output",
                "android-abis",
                "android-ndk-mk-abis",
                "android-ndk-mk-split",
                "android-ndk-mk-universal",
                "android-ndk-mk-both",
                "emscripten-fullscreen-shell",
                "emscripten-fullscreen",
            }
            undeclared = sorted(
                key for key in cli_custom_options.keys()
                if BuildCommand.NormalizeOptionTrigger(key) not in builtin_custom_options
                if BuildCommand.NormalizeOptionTrigger(key) not in {
                    BuildCommand.NormalizeOptionTrigger(opt_key) for opt_key in declared_options.keys()
                }
            )
            if undeclared:
                Colored.PrintWarning(
                    "Undeclared custom option(s) accepted for compatibility: "
                    + ", ".join(f"--{name}" for name in undeclared)
                )

        filter_options = BuildCommand.CollectFilterOptions(
            config=parsed.config,
            platform=parsed.platform,
            target=parsed.target,
            verbose=parsed.verbose,
            no_cache=parsed.no_cache,
            no_daemon=parsed.no_daemon,
            extra=[f"action:{parsed.action}"],
            custom_option_values=custom_option_values
        )

        if BuildCommand.IsAllPlatformsRequest(parsed.platform):
            platforms = BuildCommand.GetAllDeclaredPlatforms(workspace)
            return BuildCommand.BuildAcrossPlatforms(
                workspace,
                config=parsed.config,
                platforms=platforms,
                target=parsed.target,
                verbose=parsed.verbose,
                action=parsed.action,
                options=filter_options,
                jobs=parsed.jobs
            )

        # 2. Créer le builder
        try:
            builder = BuildCommand.CreateBuilder(
                workspace,
                config=parsed.config,
                platform=parsed.platform,
                target=parsed.target,
                verbose=parsed.verbose,
                action=parsed.action,
                options=filter_options,
                jobs=parsed.jobs
            )
        except Exception as e:
            Colored.PrintError(f"Cannot create builder: {e}")
            return 1

        # 3. Exécuter le build
        result = builder.Build(parsed.target)

        # Fallback robuste: si le build échoue avec un cache "no changes",
        # on force un rechargement complet une seule fois.
        if (
            result != 0
            and not parsed.no_cache
            and loaded_from_cache
            and getattr(workspace, "_cache_status", "") == "no_changes"
        ):
            Colored.PrintWarning("Build failed with cached workspace. Retrying once with fresh workspace...")
            cache.Invalidate()
            workspace = loader.LoadWorkspace(str(entry_file))
            if workspace is None:
                return result
            cache.SaveWorkspace(workspace, entry_file, loader)

            try:
                builder = BuildCommand.CreateBuilder(
                    workspace,
                    config=parsed.config,
                    platform=parsed.platform,
                    target=parsed.target,
                    verbose=parsed.verbose,
                    action=parsed.action,
                    options=filter_options,
                    jobs=parsed.jobs
                )
            except Exception as e:
                Colored.PrintError(f"Cannot create builder after cache refresh: {e}")
                return result

            return builder.Build(parsed.target)

        return result

    """
    Patch pour BuildCommand.py
    Remplacer le bloc de détection du fichier workspace dans Execute() :

        AVANT (lignes ~310-318) :
        ─────────────────────────────────────────────────────────────────
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

        APRÈS :
        ─────────────────────────────────────────────────────────────────
            if parsed.jenga_file:
                entry_file = Path(parsed.jenga_file).resolve()
                if not entry_file.exists():
                    Colored.PrintError(f"Jenga file not found: {entry_file}")
                    return 1
            else:
                entry_file = BuildCommand._FindWorkspaceEntry(workspace_root)
                if not entry_file:
                    Colored.PrintError(
                        f"No .jenga workspace file found in '{workspace_root}' or its parents.\n"
                        f"  Tip: Make sure you are inside a Jenga project directory.\n"
                        f"  Tip: Use --jenga-file <path> to specify the file explicitly."
                    )
                    return 1
            workspace_root = entry_file.parent

    Ajouter aussi la méthode statique _FindWorkspaceEntry dans BuildCommand :
    """

    # ─────────────────────────────────────────────────────────────────────────────
    # Méthode à ajouter dans la classe BuildCommand (avec les autres @staticmethod)
    # ─────────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _FindWorkspaceEntry(start_dir: Path) -> Optional[Path]:
        """
        Trouve le fichier .jenga workspace en remontant depuis start_dir.

        Règles :
          - Seuls les FICHIERS sont considérés (pas les dossiers).
          - Les fichiers dont un composant du chemin est ".jenga" sont ignorés
            (évite de confondre le dossier de cache .jenga/ avec un workspace).
          - Si plusieurs fichiers .jenga coexistent, on préfère celui dont le
            stem correspond au nom du dossier parent, sinon le premier alphabétiquement.
          - Remonte jusqu'à la racine du système de fichiers.

        Args:
            start_dir: Répertoire de départ.

        Returns:
            Path absolu du fichier .jenga, ou None si introuvable.
        """
        current = Path(start_dir).resolve()
        visited: set = set()

        while True:
            if current in visited:
                break
            visited.add(current)

            # Collecter les fichiers .jenga dans ce dossier
            candidates = []
            try:
                for entry in current.iterdir():
                    # Fichiers uniquement
                    if not entry.is_file():
                        continue
                    # Extension .jenga (insensible à la casse)
                    if entry.suffix.lower() != ".jenga":
                        continue
                    # Ignorer si le fichier est à l'intérieur du dossier de cache .jenga/
                    if any(part == ".jenga" for part in entry.parts):
                        continue
                    candidates.append(entry)
            except PermissionError:
                pass

            if candidates:
                candidates.sort()  # tri alphabétique stable

                # Priorité 1 : stem == nom exact du dossier courant
                dir_name = current.name
                for c in candidates:
                    if c.stem == dir_name:
                        return c

                # Priorité 2 : correspondance partielle (NKWindow dans NKWindow01)
                for c in candidates:
                    if dir_name.startswith(c.stem) or c.stem.startswith(dir_name):
                        return c

                # Fallback : premier alphabétiquement
                return candidates[0]

            # Remonter d'un niveau
            parent = current.parent
            if parent == current:
                break  # racine atteinte
            current = parent

        return None