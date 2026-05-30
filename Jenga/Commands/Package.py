#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Package command – Crée des packages distribuables pour toutes les plateformes supportées.
- Android : APK, AAB (via AndroidBuilder)
- iOS : IPA (via IOSBuilder)
- Windows : MSI, EXE installer, ZIP (via WiX, InnoSetup, ou outils natifs)
- Linux : DEB, RPM, AppImage, Snap
- macOS : PKG, DMG
- Web : ZIP (via EmscriptenBuilder)
"""

import argparse
import sys
import shutil
import tempfile
from pathlib import Path
from typing import List, Optional, Dict

from ..Utils import Colored, Display, FileSystem, Process
from ..Core.Loader import Loader
from ..Core.Cache import Cache
from ..Core.Builder import Builder
from ..Core import Api
# Éditeur par défaut des installeurs (Rihen). Source unique : Jenga/_version.py.
from .._version import __publisher__ as DEFAULT_PUBLISHER, __email__ as DEFAULT_EMAIL


class PackageCommand:
    """jenga package [--platform PLATFORM] [--config CONFIG] [--output DIR] [--project PROJECT] [--type TYPE]"""

    SUPPORTED_PLATFORMS = {
        'android': {'apk', 'aab'},
        'ios': {'ipa'},
        'tvos': {'ipa'},
        'watchos': {'ipa'},
        # 'jng' = installateur self-extracting MAISON (Jenga/Tools/Installer),
        # sans dependance externe. C'est une option DE PLUS (msi/exe/zip restent).
        'windows': {'msi', 'exe', 'zip', 'jng'},
        'linux': {'deb', 'rpm', 'appimage', 'snap', 'jng'},
        'macos': {'pkg', 'dmg', 'jng'},
        'web': {'zip'},
        'harmonyos': {'hap'},
    }

    DEFAULT_PACKAGE_TYPE = {
        'android': 'apk',
        'ios': 'ipa',
        'tvos': 'ipa',
        'watchos': 'ipa',
        'windows': 'zip',
        'linux': 'deb',
        'macos': 'pkg',
        'web': 'zip',
        'harmonyos': 'hap',
    }

    @staticmethod
    def Execute(args: List[str]) -> int:
        parser = argparse.ArgumentParser(prog="jenga package", description="Create distributable packages.")
        parser.add_argument("--platform", required=True, choices=list(PackageCommand.SUPPORTED_PLATFORMS.keys()),
                            help="Target platform")
        parser.add_argument("--ios-builder", choices=["direct", "xcode", "xbuilder"], default=None,
                            help="Apple mobile builder backend (direct or xcode/xbuilder).")
        parser.add_argument("--config", default="Release", help="Build configuration (default: Release)")
        parser.add_argument("--output", "-o", default="./dist", help="Output directory (default: ./dist)")
        parser.add_argument("--project", help="Specific project to package (default: first executable)")
        parser.add_argument("--type", help="Package type (e.g., apk, aab, ipa, msi, deb). Default depends on platform.")
        parser.add_argument("--no-daemon", action="store_true", help="Do not use daemon")
        parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
        parser.add_argument("--jenga-file", help="Path to the workspace .jenga file (default: auto-detected)")
        parsed = parser.parse_args(args)

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

        # Déterminer le type de package par défaut
        pkg_type = parsed.type
        if not pkg_type:
            pkg_type = PackageCommand.DEFAULT_PACKAGE_TYPE.get(parsed.platform)
            if not pkg_type:
                # Fallback de sûreté, stable.
                pkg_type = sorted(PackageCommand.SUPPORTED_PLATFORMS[parsed.platform])[0]

        if pkg_type not in PackageCommand.SUPPORTED_PLATFORMS[parsed.platform]:
            Colored.PrintError(f"Unsupported package type '{pkg_type}' for platform '{parsed.platform}'.")
            return 1

        # Charger le workspace (avec cache si possible)
        loader = Loader(verbose=parsed.verbose)
        cache = Cache(workspace_root, workspaceName=entry_file.stem)

        workspace = None
        if not parsed.no_daemon:
            from ..Core.Daemon import DaemonClient, DaemonStatus
            client = DaemonClient(workspace_root)
            if client.IsAvailable():
                Colored.PrintInfo("Using build daemon...")
                try:
                    response = client.SendCommand('package', {
                        'platform': parsed.platform,
                        'config': parsed.config,
                        'output': parsed.output,
                        'project': parsed.project,
                        'type': pkg_type,
                        'verbose': parsed.verbose
                    })
                    if response.get('status') == 'ok':
                        return response.get('return_code', 0)
                    else:
                        Colored.PrintError(f"Daemon package failed: {response.get('message')}")
                        return 1
                except Exception as e:
                    Colored.PrintWarning(f"Daemon error: {e}, falling back to direct package.")

        if workspace is None:
            workspace = cache.LoadWorkspace(entry_file, loader)
        if workspace is None:
            workspace = loader.LoadWorkspace(str(entry_file))
            if workspace:
                cache.SaveWorkspace(workspace, entry_file, loader)

        if workspace is None:
            Colored.PrintError("Failed to load workspace.")
            return 1

        # Sélectionner le projet à packager
        project_name = parsed.project
        if not project_name:
            # Chercher le startProject ou premier exécutable
            project_name = workspace.startProject
            if not project_name:
                for name, proj in workspace.projects.items():
                    if proj.kind in (Api.ProjectKind.CONSOLE_APP, Api.ProjectKind.WINDOWED_APP):
                        project_name = name
                        break
        if not project_name or project_name not in workspace.projects:
            Colored.PrintError(f"Project '{project_name}' not found.")
            return 1

        project = workspace.projects[project_name]

        # Créer le builder pour ce projet (nécessaire pour connaître les chemins de sortie)
        try:
            from ..Commands.Build import BuildCommand
            builder = PackageCommand._CreateBuilder(
                workspace, parsed.config, parsed.platform, project_name, parsed.verbose,
                action="package",
                options=BuildCommand.CollectFilterOptions(
                    config=parsed.config,
                    platform=parsed.platform,
                    target=project_name,
                    verbose=parsed.verbose,
                    no_cache=False,
                    no_daemon=parsed.no_daemon,
                    extra=(
                        ["action:package", f"package:{pkg_type}"] +
                        ([f"ios-builder={parsed.ios_builder}"] if parsed.ios_builder else [])
                    )
                )
            )
        except Exception as e:
            Colored.PrintError(f"Cannot create builder: {e}")
            return 1

        output_dir = Path(parsed.output).resolve()
        FileSystem.MakeDirectory(output_dir)

        # Type 'jng' : installateur self-extracting maison (multi-plateforme,
        # sans dependance externe). Commun a toutes les plateformes desktop.
        if pkg_type == 'jng':
            return PackageCommand._PackageSelfExtract(project, builder, output_dir, parsed.platform)

        # Dispatch selon plateforme
        if parsed.platform == 'android':
            return PackageCommand._PackageAndroid(project, builder, pkg_type, output_dir)
        elif parsed.platform in ('ios', 'tvos', 'watchos'):
            return PackageCommand._PackageIOS(project, builder, pkg_type, output_dir)
        elif parsed.platform == 'windows':
            return PackageCommand._PackageWindows(project, builder, pkg_type, output_dir)
        elif parsed.platform == 'linux':
            return PackageCommand._PackageLinux(project, builder, pkg_type, output_dir)
        elif parsed.platform == 'macos':
            return PackageCommand._PackageMacOS(project, builder, pkg_type, output_dir)
        elif parsed.platform == 'web':
            return PackageCommand._PackageWeb(project, builder, pkg_type, output_dir)
        elif parsed.platform == 'harmonyos':
            return PackageCommand._PackageHarmonyOS(project, builder, pkg_type, output_dir)
        else:
            Colored.PrintError(f"Packaging for platform '{parsed.platform}' not implemented.")
            return 1

    @staticmethod
    def _CreateBuilder(workspace,
                       config: str,
                       platform: str,
                       target: str,
                       verbose: bool,
                       action: str = "package",
                       options: Optional[List[str]] = None) -> Builder:
        """Crée un builder pour le projet cible."""
        from ..Commands.Build import BuildCommand
        return BuildCommand.CreateBuilder(
            workspace, config, platform, target, verbose,
            action=action,
            options=options
        )

    # -----------------------------------------------------------------------
    # Android
    # -----------------------------------------------------------------------

    @staticmethod
    def _PackageAndroid(project, builder, pkg_type: str, output_dir: Path) -> int:
        """APK / AAB packaging."""
        if not hasattr(builder, 'BuildAPK') or not hasattr(builder, 'BuildAAB'):
            Colored.PrintError("AndroidBuilder not available.")
            return 1

        # Construire les bibliothèques natives si nécessaire
        # Note: On suppose que le build a déjà été fait. Si ce n'est pas le cas, on peut appeler builder.BuildProject(project)
        if not builder.BuildProject(project):
            Colored.PrintError("Build failed, cannot package.")
            return 1

        # Récupérer les .so générés
        libs = []
        target_dir = builder.GetTargetDir(project)
        for so in target_dir.glob("*.so"):
            libs.append(str(so))

        if not libs:
            Colored.PrintError("No native libraries found.")
            return 1

        if pkg_type == 'apk':
            if not builder.BuildAPK(project, libs):
                return 1
            # Copier l'APK vers output_dir
            apk_path = builder.GetTargetDir(project) / f"{project.targetName or project.name}.apk"
            if apk_path.exists():
                shutil.copy2(apk_path, output_dir / apk_path.name)
                Colored.PrintSuccess(f"APK packaged: {output_dir / apk_path.name}")
                return 0
            return 1

        elif pkg_type == 'aab':
            if not hasattr(builder, 'BuildAAB'):
                Colored.PrintError("AAB packaging not supported by this builder.")
                return 1
            if not builder.BuildAAB(project, libs):
                return 1
            aab_path = builder.GetTargetDir(project) / f"{project.targetName or project.name}.aab"
            if aab_path.exists():
                shutil.copy2(aab_path, output_dir / aab_path.name)
                Colored.PrintSuccess(f"AAB packaged: {output_dir / aab_path.name}")
                return 0
            return 1

        return 1

    # -----------------------------------------------------------------------
    # iOS
    # -----------------------------------------------------------------------

    @staticmethod
    def _PackageIOS(project, builder, pkg_type: str, output_dir: Path) -> int:
        """IPA packaging."""
        if not hasattr(builder, 'ExportIPA'):
            Colored.PrintError("IOSBuilder does not support ExportIPA.")
            return 1

        # Build project
        if not builder.BuildProject(project):
            return 1

        # Localiser le bundle .app
        target_dir = builder.GetTargetDir(project)
        app_bundle = target_dir / f"{project.targetName or project.name}.app"
        if not app_bundle.exists():
            Colored.PrintError(f".app bundle not found: {app_bundle}")
            return 1

        # Exporter IPA
        ipa_path = builder.ExportIPA(app_bundle, project)
        if not ipa_path:
            return 1

        shutil.copy2(ipa_path, output_dir / ipa_path.name)
        Colored.PrintSuccess(f"IPA packaged: {output_dir / ipa_path.name}")
        return 0

    # -----------------------------------------------------------------------
    # Windows
    # -----------------------------------------------------------------------

    # -----------------------------------------------------------------------
    # Depend files collection (commun a tous les packagers)
    # -----------------------------------------------------------------------
    @staticmethod
    def _CollectDependFiles(project, builder) -> List[tuple]:
        """
        Collecte tous les fichiers a embarquer dans le package, declares via
        `dependfiles()` dans le .jenga. Retourne une liste de tuples
        (src_absolu, archive_path_relatif).

        Strategie de archive_path :
          - Si la source resolue est SOUS le workspace root, on preserve sa
            structure relative au workspace. Exemple :
              dependfiles(["../../Resources/Pong"])  dans Applications/Pong/
              -> src abs = <wks>/Resources/Pong/
              -> archive_path commence par "Resources/Pong/..."
            C'est le comportement attendu pour les ressources d'app : le code
            C++ utilise `Resources/Pong/Textures/logo.png` au runtime.
          - Sinon (source hors workspace, ex: une DLL externe), on copie au
            basename du chemin source.

        Dossiers : on recurse via rglob("*") pour ajouter chaque fichier.
        Fichiers manquants : silencieusement skippes (un warning est emis).
        """
        if not project.dependFiles:
            return []

        try:
            workspace_root = Path(builder.workspace.location).resolve()
        except Exception:
            workspace_root = None

        collected: List[tuple] = []
        for dep in project.dependFiles:
            # Resolve via builder pour gerer correctement les chemins
            # relatifs au project.location (ex: "../../Resources/Pong").
            try:
                resolved = Path(builder.ResolveProjectPath(project, dep)).resolve()
            except Exception:
                resolved = Path(dep).resolve()

            if not resolved.exists():
                Colored.PrintWarning(f"[package] dependfile introuvable : {dep}")
                continue

            def _archive_path_for(file_abs: Path) -> str:
                """Calcule le chemin relatif dans l'archive pour un fichier source."""
                if workspace_root is not None:
                    try:
                        rel = file_abs.relative_to(workspace_root)
                        return str(rel).replace("\\", "/")
                    except ValueError:
                        pass  # hors workspace : fallback basename
                return file_abs.name

            if resolved.is_file():
                collected.append((resolved, _archive_path_for(resolved)))
            elif resolved.is_dir():
                for f in resolved.rglob("*"):
                    if f.is_file():
                        collected.append((f, _archive_path_for(f)))

        # Auto-detection des SHARED_LIB dependances : si le project depend
        # d'une SHARED_LIB construite par jenga, on embarque automatiquement
        # son binaire (.dll/.so/.dylib) a cote de l'executable dans le package.
        # Le user n'a pas a declarer manuellement chaque DLL transitive.
        try:
            from ..Core.Api import ProjectKind
            for dep_name in (project.dependsOn or []):
                dep_proj = builder.workspace.projects.get(dep_name)
                if dep_proj is None or dep_proj.kind != ProjectKind.SHARED_LIB:
                    continue
                try:
                    dep_lib_path = Path(builder.GetTargetPath(dep_proj)).resolve()
                except Exception:
                    continue
                if not dep_lib_path.exists():
                    continue
                # Les DLLs Windows / .dylib macOS / .so Linux doivent vivre a
                # cote de l'executable au runtime -> on les met au basename
                # (pas de sous-dossier). Eviter les doublons.
                arc = dep_lib_path.name
                if not any(p[0] == dep_lib_path for p in collected):
                    collected.append((dep_lib_path, arc))
        except Exception:
            # Defensif : ne jamais casser le packaging pour une auto-detection.
            pass

        return collected

    @staticmethod
    def _AugmentPathForWindowsInstallerTools():
        """
        Ajoute au PATH (session uniquement) les emplacements standards des
        outils installer Windows. L'user n'a pas besoin de bidouiller son
        environnement : si WiX ou Inno Setup sont installes a leur
        emplacement par defaut (winget, dotnet tool, MSI vendor), jenga les
        trouve automatiquement au moment du package.

        Locations cherchees :
          - Inno Setup 6/5 (winget user install)
          - Inno Setup 6/5 (vendor MSI install)
          - WiX dotnet global tool
          - WiX 3.x (legacy)
        """
        import os as _os
        candidates = [
            # Inno Setup (winget user)
            _os.path.expandvars(r"%LOCALAPPDATA%\Programs\Inno Setup 6"),
            _os.path.expandvars(r"%LOCALAPPDATA%\Programs\Inno Setup 5"),
            # Inno Setup (vendor MSI install)
            r"C:\Program Files (x86)\Inno Setup 6",
            r"C:\Program Files (x86)\Inno Setup 5",
            r"C:\Program Files\Inno Setup 6",
            r"C:\Program Files\Inno Setup 5",
            # WiX dotnet global tool (deja dans le PATH normalement)
            _os.path.expandvars(r"%USERPROFILE%\.dotnet\tools"),
            # WiX 3.x legacy
            r"C:\Program Files (x86)\WiX Toolset v3.11\bin",
            r"C:\Program Files (x86)\WiX Toolset v3.14\bin",
        ]
        added = []
        for c in candidates:
            if _os.path.isdir(c):
                # Verifie qu'il n'est pas deja dans le PATH (case-insensitive
                # sur Windows).
                norm = _os.path.normpath(c).lower()
                paths = _os.environ.get("PATH", "").split(_os.pathsep)
                if not any(_os.path.normpath(p).lower() == norm for p in paths if p):
                    _os.environ["PATH"] = c + _os.pathsep + _os.environ.get("PATH", "")
                    added.append(c)
        return added

    @staticmethod
    def _PackageWindows(project, builder, pkg_type: str, output_dir: Path) -> int:
        """Création d'installateur Windows."""
        # Augmente le PATH avec les emplacements standards d'Inno/WiX pour
        # eviter que l'user doive le configurer manuellement.
        PackageCommand._AugmentPathForWindowsInstallerTools()

        # Build project
        if not builder.BuildProject(project):
            return 1

        exe_path = builder.GetTargetPath(project)
        if not exe_path.exists():
            Colored.PrintError(f"Executable not found: {exe_path}")
            return 1

        if pkg_type == 'zip':
            # Créer une archive ZIP
            import zipfile
            zip_path = output_dir / f"{project.targetName or project.name}.zip"
            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
                zf.write(exe_path, exe_path.name)
                # Embarquer les dependfiles (ressources, DLLs, dossiers entiers)
                for src_abs, archive_path in PackageCommand._CollectDependFiles(project, builder):
                    zf.write(src_abs, archive_path)
            Colored.PrintSuccess(f"ZIP package: {zip_path}")
            return 0

        elif pkg_type == 'msi':
            # WiX Toolset. On supporte 2 generations :
            #   - WiX 4+ (commande `wix` unifiee, installable via
            #     `dotnet tool install -g wix`, format XML moderne)
            #   - WiX 3 (legacy `candle` + `light`)
            # Detection : on essaie `wix` en premier (moderne), puis fallback
            # sur candle/light si seule la version legacy est presente.
            has_wix4 = FileSystem.FindExecutable("wix") is not None
            has_wix3 = (FileSystem.FindExecutable("candle") is not None
                     and FileSystem.FindExecutable("light")  is not None)

            if not has_wix4 and not has_wix3:
                Colored.PrintError(
                    "WiX Toolset not found. Install options :\n"
                    "  - WiX 4+ (recommande) : dotnet tool install --global wix\n"
                    "  - WiX 3 (legacy)     : winget install WiX.Toolset (requiert admin)\n"
                    "  - Ou utiliser `--type zip` ou `--type exe` (Inno Setup)"
                )
                return 1

            wxs_path = output_dir / f"{project.name}.wxs"
            msi_path = output_dir / f"{project.name}.msi"

            if has_wix4:
                # Format moderne WiX 4+ : <Package> + <StandardDirectory>.
                # UI installer (EULA + dir choice + shortcut) necessite
                # l'extension WixToolset.UI.wixext. On l'ajoute idempotemment
                # avant le build (no-op si deja installee). On utilise
                # subprocess direct car Process.Run force captureOutput=False.
                import subprocess as _sp
                try:
                    _sp.run(["wix", "extension", "add",
                             "WixToolset.UI.wixext/5.0.2"],
                            capture_output=True, text=True, timeout=120,
                            shell=False)
                except Exception:
                    pass  # extension peut deja etre installee, on ignore
                PackageCommand._GenerateWiX4Template(project, builder, exe_path, wxs_path)
                # `-ext WixToolset.UI.wixext` active le namespace ui:* + les
                # dialogues standards (WixUI_InstallDir, WixUI_Mondo, etc.).
                cmd = ["wix", "build", str(wxs_path),
                       "-ext", "WixToolset.UI.wixext",
                       "-o", str(msi_path)]
                if Process.Run(cmd) != 0:
                    return 1
            else:
                # Format legacy WiX 3 : <Product>. Garde la backward compat.
                PackageCommand._GenerateWiXTemplate(project, builder, exe_path, wxs_path)
                obj_path = output_dir / f"{project.name}.wixobj"
                if Process.Run(["candle", str(wxs_path), "-o", str(obj_path)]) != 0:
                    return 1
                if Process.Run(["light", str(obj_path), "-o", str(msi_path)]) != 0:
                    return 1

            Colored.PrintSuccess(f"MSI package: {msi_path}")
            return 0

        elif pkg_type == 'exe':
            # Utiliser Inno Setup
            if not FileSystem.FindExecutable("iscc"):
                Colored.PrintError("Inno Setup not found. Please install Inno Setup.")
                return 1
            iss_path = output_dir / f"{project.name}.iss"
            PackageCommand._GenerateInnoScript(project, builder, exe_path, iss_path)
            exe_installer = output_dir / f"{project.name}_setup.exe"
            if Process.Run(["iscc", str(iss_path), f"/O{output_dir}", f"/F{project.name}_setup"]) != 0:
                return 1
            Colored.PrintSuccess(f"EXE installer: {output_dir / f'{project.name}_setup.exe'}")
            return 0

        return 1

    @staticmethod
    def _GenerateWiXTemplate(project, builder, exe_path: Path, output: Path):
        """Genere un fichier .wxs pour WiX 3 legacy.

        Format : namespace 2006 + <Product> root. Cette generation est plus
        simple que WiX 4 (pas de Wizard UI, pas de hierarchie de dossiers
        complete pour les dependfiles — fichiers a plat dans INSTALLDIR).

        Inclut les CustomActions firewall (parite avec WiX 4 et Inno Setup)
        via Core/FirewallSpec.py. Sans cette regle, les apps reseau ne peuvent
        pas accepter de connexions entrantes (cf [[pong_firewall_lan_fix]]).
        """
        import xml.etree.ElementTree as ET
        from ..Core import FirewallSpec
        root = ET.Element("Wix", xmlns="http://schemas.microsoft.com/wix/2006/wi")
        product = ET.SubElement(root, "Product",
                                Name=project.targetName or project.name,
                                Manufacturer=(project.appPublisher or DEFAULT_PUBLISHER),
                                Id="*",
                                UpgradeCode="*",
                                Language="1033",
                                Codepage="1252",
                                Version=(project.appVersion or project.iosVersion or "1.0.0"))
        package = ET.SubElement(product, "Package",
                                InstallerVersion="200",
                                Compressed="yes",
                                InstallScope="perMachine")
        media = ET.SubElement(product, "Media", Id="1", Cabinet="setup.cab", EmbedCab="yes")
        directory = ET.SubElement(product, "Directory", Id="TARGETDIR", Name="SourceDir")
        prog_files = ET.SubElement(directory, "Directory", Id="ProgramFiles64Folder")
        app_dir = ET.SubElement(prog_files, "Directory", Id="INSTALLDIR", Name=project.targetName or project.name)
        comp = ET.SubElement(app_dir, "Component", Id="MainExecutable", Guid="*")
        file_elem = ET.SubElement(comp, "File", Id="ExeFile", Name=exe_path.name, Source=str(exe_path), KeyPath="yes")
        # Embarquer les dependfiles. WiX gere les sous-dossiers via une
        # hierarchie <Directory> imbriquee — on garde ici un schema plat (les
        # fichiers heritent du INSTALLDIR). Pour une vraie hierarchy MSI, voir
        # le pattern Wix Heat Harvester ; on garde simple pour l'instant.
        for idx, (src_abs, archive_path) in enumerate(
            PackageCommand._CollectDependFiles(project, builder)
        ):
            file_id = f"DepFile{idx}"
            ET.SubElement(
                comp, "File",
                Id=file_id,
                Name=Path(archive_path).name,
                Source=str(src_abs),
            )

        # Features
        feature = ET.SubElement(product, "Feature", Id="ProductFeature", Title=project.name, Level="1")
        ET.SubElement(feature, "ComponentRef", Id="MainExecutable")

        # ── CustomActions firewall (parite WiX 4 / Inno) ───────────────────
        # Format WiX 3 : pas de namespace, attribut "Condition" en enfant texte
        # de <Custom>. Sequences sous <InstallExecuteSequence>.
        add_cmds = FirewallSpec.BuildNetshAddCommands(project, "[#ExeFile]")
        del_cmds = FirewallSpec.BuildNetshDeleteCommands(project)
        if add_cmds or del_cmds:
            seq = ET.SubElement(product, "InstallExecuteSequence")
            for idx, cmd in enumerate(add_cmds):
                ca_id = f"Nk_FirewallAdd_{idx}"
                ET.SubElement(product, "CustomAction",
                              Id=ca_id,
                              Directory="INSTALLDIR",
                              ExeCommand=cmd,
                              Execute="deferred",
                              Impersonate="no",
                              Return="ignore")
                custom = ET.SubElement(seq, "Custom",
                                       Action=ca_id,
                                       After="InstallFiles")
                # WiX 3 : la condition est le TEXT du noeud <Custom>, pas un attribut.
                custom.text = "NOT Installed"
            for idx, cmd in enumerate(del_cmds):
                ca_id = f"Nk_FirewallDel_{idx}"
                ET.SubElement(product, "CustomAction",
                              Id=ca_id,
                              Directory="INSTALLDIR",
                              ExeCommand=cmd,
                              Execute="deferred",
                              Impersonate="no",
                              Return="ignore")
                custom = ET.SubElement(seq, "Custom",
                                       Action=ca_id,
                                       Before="RemoveFiles")
                custom.text = "Installed AND REMOVE=\"ALL\""

        tree = ET.ElementTree(root)
        tree.write(output, encoding="utf-8", xml_declaration=True)

    # -----------------------------------------------------------------------
    # Helper : resout/genere un .ico Windows pour les raccourcis bureau /
    # menu Demarrer. Reuse l'IconConverter (PNG -> ICO) en passant par
    # ResolveIconFor (windowsicon override > appicon generique).
    # Retourne le path absolu du .ico, ou None si pas configure / echec.
    # -----------------------------------------------------------------------
    @staticmethod
    def _ResolveWindowsIcoForPackage(project, builder, output_dir: Path) -> Optional[Path]:
        try:
            from ..Core.IconConverter import (
                ResolveIconFor, DetectIconFormat, ConvertPngToIco, HasPillow,
                PLATFORM_WINDOWS, FORMAT_PNG, FORMAT_JPG, FORMAT_ICO,
            )
        except Exception:
            return None
        icon_src = ResolveIconFor(project, PLATFORM_WINDOWS)
        if not icon_src:
            return None
        try:
            resolved = Path(builder.ResolveProjectPath(project, icon_src))
        except Exception:
            resolved = Path(icon_src)
        if not resolved.exists():
            return None
        fmt = DetectIconFormat(resolved)
        if fmt == FORMAT_ICO:
            return resolved.resolve()
        if fmt in (FORMAT_PNG, FORMAT_JPG) and HasPillow():
            out_ico = output_dir / f"{project.name}_app.ico"
            if ConvertPngToIco(resolved, out_ico):
                return out_ico.resolve()
        return None

    # -----------------------------------------------------------------------
    # Helper : resout le fichier de licence project vers un RTF utilisable
    # par WiX (la dialogue EULA n'accepte QUE des .rtf). Si le user fournit
    # un .txt ou .md, jenga convertit automatiquement en RTF minimal.
    # -----------------------------------------------------------------------
    @staticmethod
    def _ResolveLicenseRtf(project, builder, output_dir: Path) -> Optional[Path]:
        license_src = getattr(project, "licenseFile", "")
        if not license_src:
            return None
        try:
            resolved = Path(builder.ResolveProjectPath(project, license_src))
        except Exception:
            resolved = Path(license_src)
        if not resolved.exists():
            Colored.PrintWarning(
                f"[package] licensefile introuvable : {license_src}"
            )
            return None

        ext = resolved.suffix.lower()
        if ext == ".rtf":
            return resolved.resolve()

        # Conversion .txt / .md -> .rtf minimal.
        try:
            text = resolved.read_text(encoding="utf-8")
        except Exception:
            try:
                text = resolved.read_text(encoding="latin-1")
            except Exception:
                Colored.PrintWarning(
                    f"[package] impossible de lire licence : {resolved}"
                )
                return None

        # Echappement RTF : { } \ doivent etre echappes par \. Les sauts de
        # ligne deviennent \par. Les caracteres > 127 doivent etre encodes
        # en \uXXXX (RTF utilise des decimales signees, 16-bit).
        def _rtf_escape(s: str) -> str:
            out = []
            for ch in s:
                cp = ord(ch)
                if ch == '\\':
                    out.append("\\\\")
                elif ch == '{':
                    out.append("\\{")
                elif ch == '}':
                    out.append("\\}")
                elif ch == '\n':
                    out.append("\\par\n")
                elif ch == '\r':
                    continue
                elif 32 <= cp < 128:
                    out.append(ch)
                else:
                    # \uN? avec N en 16-bit signed decimal.
                    if cp > 32767:
                        cp -= 65536
                    out.append(f"\\u{cp}?")
            return "".join(out)

        body = _rtf_escape(text)
        rtf = ("{\\rtf1\\ansi\\ansicpg1252\\deff0"
               "{\\fonttbl{\\f0\\fnil\\fcharset0 Segoe UI;}}"
               "\\viewkind4\\uc1\\pard\\f0\\fs20 "
               + body + "}")
        out_path = output_dir / f"{project.name}_license.rtf"
        try:
            out_path.write_text(rtf, encoding="utf-8")
        except Exception as e:
            Colored.PrintWarning(f"[package] echec ecriture licence RTF : {e}")
            return None
        return out_path.resolve()

    # -----------------------------------------------------------------------
    # WiX 4+ : format moderne <Package> + <StandardDirectory> + hierarchy
    # -----------------------------------------------------------------------

    @staticmethod
    def _GenerateWiX4Template(project, builder, exe_path: Path, output: Path):
        """
        Genere un .wxs au format WiX 4+ avec hierarchie de dossiers complete.

        Differences clefs vs WiX 3 :
          - namespace : http://wixtoolset.org/schemas/v4/wxs
          - <Package> remplace <Product>
          - <StandardDirectory> remplace les Directory chaines
            ProgramFiles64Folder
          - <MediaTemplate> remplace <Media>
          - Pas besoin de declarer InstallerVersion, Codepage explicites
          - Guid="*" reste valide pour auto-generation

        La hierarchie de dossiers est construite a partir des archive_paths
        retournes par _CollectDependFiles. Un fichier `Resources/Pong/Textures/
        logo.png` cree 3 niveaux : Resources -> Pong -> Textures, et le fichier
        est place dans Textures avec son nom de base.
        """
        import xml.etree.ElementTree as ET
        import uuid

        ns    = "http://wixtoolset.org/schemas/v4/wxs"
        ns_ui = "http://wixtoolset.org/schemas/v4/wxs/ui"
        ET.register_namespace("",   ns)
        ET.register_namespace("ui", ns_ui)

        # ── Resolution des metadonnees app ────────────────────────────────
        app_name      = project.targetName or project.name
        publisher     = (project.appPublisher or "").strip() or DEFAULT_PUBLISHER
        version       = (project.appVersion or project.iosVersion or "1.0.0").strip()

        # ── Racine <Wix> + <Package> ───────────────────────────────────────
        root = ET.Element(f"{{{ns}}}Wix")
        pkg = ET.SubElement(root, f"{{{ns}}}Package",
                            Name=app_name,
                            Manufacturer=publisher,
                            Version=version,
                            UpgradeCode=str(uuid.uuid4()).upper())
        ET.SubElement(pkg, f"{{{ns}}}MediaTemplate", EmbedCab="yes")

        # ── UI : EULA (si licence fournie) + choix dossier d'install ──────
        # WixUI_InstallDir presente un wizard standard :
        #   Welcome -> EULA -> InstallDir (choix dossier) -> Confirm -> Install
        # Necessite WIXUI_INSTALLDIR pour pointer vers notre INSTALLDIR.
        license_rtf = PackageCommand._ResolveLicenseRtf(
            project, builder, output.parent)
        if license_rtf is not None:
            # WixUILicenseRtf = fichier RTF affiche dans le dialogue EULA.
            ET.SubElement(pkg, f"{{{ns}}}WixVariable",
                          Id="WixUILicenseRtf",
                          Value=str(license_rtf))
        ET.SubElement(pkg, f"{{{ns}}}Property",
                      Id="WIXUI_INSTALLDIR",
                      Value="INSTALLDIR")
        ET.SubElement(pkg, f"{{{ns_ui}}}WixUI", Id="WixUI_InstallDir")

        # ── Icone applicative pour les raccourcis (.lnk Bureau/Menu) ──────
        # Si on a un .ico (PNG converti via appicon ou .ico direct), on
        # declare une <Icon> referencable par les <Shortcut> ci-dessous.
        # Sans ca, Windows essaie d'extraire l'icone depuis l'exe mais avec
        # Advertise="yes" il faut souvent un Icon explicite pour qu'elle
        # s'affiche correctement.
        ico_path = PackageCommand._ResolveWindowsIcoForPackage(
            project, builder, output.parent)
        icon_id_attr = None
        if ico_path is not None:
            ET.SubElement(pkg, f"{{{ns}}}Icon",
                          Id="AppIcon.ico",
                          SourceFile=str(ico_path))
            ET.SubElement(pkg, f"{{{ns}}}Property",
                          Id="ARPPRODUCTICON",
                          Value="AppIcon.ico")
            icon_id_attr = "AppIcon.ico"

        # ── Hierarchy <StandardDirectory> -> INSTALLDIR -> ... ────────────
        # Declaration des dossiers systeme utilises pour les raccourcis.
        # WiX 4+ requiert ces declarations explicites quand on cree des
        # <Shortcut Directory="ProgramMenuFolder"> ou DesktopFolder.
        ET.SubElement(pkg, f"{{{ns}}}StandardDirectory", Id="ProgramMenuFolder")
        ET.SubElement(pkg, f"{{{ns}}}StandardDirectory", Id="DesktopFolder")
        std_dir = ET.SubElement(pkg, f"{{{ns}}}StandardDirectory",
                                Id="ProgramFiles64Folder")
        install_dir = ET.SubElement(std_dir, f"{{{ns}}}Directory",
                                    Id="INSTALLDIR",
                                    Name=project.targetName or project.name)

        # Construit l'arbre des sous-dossiers a partir des archive_paths.
        # Chaque cle de l'arbre est un nom de dossier (segment), valeur =
        # sous-arbre. Les feuilles sont None.
        #   { "Resources": { "Pong": { "Textures": None, ... }, ... } }
        deps = PackageCommand._CollectDependFiles(project, builder)
        tree_dirs: Dict = {}
        files_at: Dict = {}    # archive_path -> src_abs
        for src_abs, arc in deps:
            arc_norm = arc.replace("\\", "/")
            files_at[arc_norm] = src_abs
            parts = arc_norm.split("/")
            # Tous les segments sauf le dernier sont des dossiers.
            cursor = tree_dirs
            for seg in parts[:-1]:
                if seg not in cursor or cursor[seg] is None:
                    cursor[seg] = {}
                cursor = cursor[seg]

        # Pour generer des Id WiX uniques mais lisibles, on prefixe par
        # "Dir_" + chemin sanitize. WiX Id doit etre [A-Za-z][A-Za-z0-9_.]*.
        def _safe_id(prefix: str, raw: str) -> str:
            cleaned = []
            for ch in raw:
                if ch.isalnum() or ch == '_':
                    cleaned.append(ch)
                else:
                    cleaned.append('_')
            res = prefix + "_" + "".join(cleaned)
            # Tronque pour eviter les Id trop longs (limite MSI ~72 chars).
            return res[:64]

        # Recursion : cree les <Directory> imbriques. Retourne le dict
        # path -> element XML pour pouvoir ajouter des Components dedans.
        dir_elements: Dict[str, ET.Element] = {"": install_dir}

        def _create_dirs(parent_path: str, parent_elem, subtree):
            for name, child in sorted(subtree.items()):
                if child is None:
                    continue
                child_path = (parent_path + "/" + name) if parent_path else name
                d = ET.SubElement(parent_elem, f"{{{ns}}}Directory",
                                  Id=_safe_id("Dir", child_path),
                                  Name=name)
                dir_elements[child_path] = d
                _create_dirs(child_path, d, child)

        _create_dirs("", install_dir, tree_dirs)

        # ── Composants : un Component par fichier (chacun avec son <File>) ─
        # Note : la regle MSI est "1 fichier = 1 component" pour le KeyPath.
        # Plusieurs files dans un meme component est possible mais complique
        # le PatchAdd/Remove. On garde simple.
        component_ids: List[str] = []

        # Composant principal : l'executable. Il porte aussi le raccourci
        # menu Demarrer + Bureau (si createdesktopshortcut(True)).
        exe_comp_id = "Comp_Exe"
        exe_comp = ET.SubElement(install_dir, f"{{{ns}}}Component",
                                 Id=exe_comp_id,
                                 Guid=str(uuid.uuid4()).upper())
        exe_file = ET.SubElement(exe_comp, f"{{{ns}}}File",
                                 Id="ExeFile",
                                 Source=str(exe_path),
                                 Name=exe_path.name,
                                 KeyPath="yes")
        # Raccourci menu Demarrer (toujours cree, behavior standard).
        # Si on a un .ico, on l'attache explicitement (Icon + IconIndex) :
        # ca garantit l'affichage correct du visuel du jeu sur le .lnk.
        sm_attrs = {
            "Id": "StartMenuShortcut",
            "Directory": "ProgramMenuFolder",
            "Name": app_name,
            "Description": f"Lancer {app_name}",
            "WorkingDirectory": "INSTALLDIR",
            "Advertise": "yes",
        }
        if icon_id_attr is not None:
            sm_attrs["Icon"]      = icon_id_attr
            sm_attrs["IconIndex"] = "0"
        ET.SubElement(exe_file, f"{{{ns}}}Shortcut", **sm_attrs)

        # Raccourci Bureau : optionnel (DSL createdesktopshortcut).
        if getattr(project, "createDesktopShortcut", True):
            dt_attrs = {
                "Id": "DesktopShortcut",
                "Directory": "DesktopFolder",
                "Name": app_name,
                "Description": f"Lancer {app_name}",
                "WorkingDirectory": "INSTALLDIR",
                "Advertise": "yes",
            }
            if icon_id_attr is not None:
                dt_attrs["Icon"]      = icon_id_attr
                dt_attrs["IconIndex"] = "0"
            ET.SubElement(exe_file, f"{{{ns}}}Shortcut", **dt_attrs)
        component_ids.append(exe_comp_id)

        # Composants pour chaque depend file, dans son dossier respectif.
        for idx, (src_abs, arc) in enumerate(deps):
            arc_norm = arc.replace("\\", "/")
            parts = arc_norm.split("/")
            file_name = parts[-1]
            sub_path = "/".join(parts[:-1])
            parent_elem = dir_elements.get(sub_path, install_dir)
            comp_id = _safe_id("Comp", arc_norm) + f"_{idx}"
            comp = ET.SubElement(parent_elem, f"{{{ns}}}Component",
                                 Id=comp_id,
                                 Guid=str(uuid.uuid4()).upper())
            ET.SubElement(comp, f"{{{ns}}}File",
                          Source=str(src_abs),
                          Name=file_name,
                          KeyPath="yes")
            component_ids.append(comp_id)

        # ── Feature : declare tous les composants installables ─────────────
        feature = ET.SubElement(pkg, f"{{{ns}}}Feature",
                                Id="ProductFeature",
                                Title=project.name,
                                Level="1")
        for cid in component_ids:
            ET.SubElement(feature, f"{{{ns}}}ComponentRef", Id=cid)

        # ── CustomActions : ajout/retrait regle Firewall Windows ──────────
        # Sans cette regle, Windows Defender bloque silencieusement les
        # connexions UDP/TCP entrantes vers l'exe -> les jeux multijoueurs
        # LAN echouent cote PC quand un mobile (ou autre PC) tente de
        # rejoindre. On utilise netsh.exe (livre Windows depuis XP) plutot
        # que la WiX Firewall extension qui requiert un wixext separe a
        # installer.
        #
        # Les commandes netsh sont generees par Core/FirewallSpec.py a partir
        # du DSL : networkenabled() + firewallrule(). Une seule CustomAction
        # par commande (add / del). Si rien n'est declare et networkEnabled
        # est False, aucune CustomAction n'est emise.
        #
        # Execute="deferred" + Impersonate="no" : la CA tourne en NT AUTHORITY\
        # SYSTEM (privileges admin necessaires pour modifier le firewall).
        # Return="ignore" : on tolere les erreurs (ex: regle deja existante).
        from ..Core import FirewallSpec
        add_cmds = FirewallSpec.BuildNetshAddCommands(project, "[#ExeFile]")
        del_cmds = FirewallSpec.BuildNetshDeleteCommands(project)
        if add_cmds or del_cmds:
            seq = ET.SubElement(pkg, f"{{{ns}}}InstallExecuteSequence")
            for idx, cmd in enumerate(add_cmds):
                ca_id = f"Nk_FirewallAdd_{idx}"
                ET.SubElement(pkg, f"{{{ns}}}CustomAction",
                              Id=ca_id,
                              Directory="INSTALLDIR",
                              ExeCommand=cmd,
                              Execute="deferred",
                              Impersonate="no",
                              Return="ignore")
                add_action = ET.SubElement(seq, f"{{{ns}}}Custom",
                                           Action=ca_id,
                                           After="InstallFiles")
                add_action.set("Condition", "NOT Installed")
            for idx, cmd in enumerate(del_cmds):
                ca_id = f"Nk_FirewallDel_{idx}"
                ET.SubElement(pkg, f"{{{ns}}}CustomAction",
                              Id=ca_id,
                              Directory="INSTALLDIR",
                              ExeCommand=cmd,
                              Execute="deferred",
                              Impersonate="no",
                              Return="ignore")
                del_action = ET.SubElement(seq, f"{{{ns}}}Custom",
                                           Action=ca_id,
                                           Before="RemoveFiles")
                del_action.set("Condition", "Installed AND REMOVE=\"ALL\"")

        # Ecriture du fichier .wxs
        tree = ET.ElementTree(root)
        ET.indent(tree, space="  ")
        tree.write(output, encoding="utf-8", xml_declaration=True)

    @staticmethod
    def _GenerateInnoScript(project, builder, exe_path: Path, output: Path):
        """Genere un script Inno Setup avec UI complete : EULA (si licence
        fournie), choix dossier d'install, raccourci bureau optionnel,
        et estimation precise de l'espace disque requis."""
        app_name  = project.targetName or project.name
        publisher = (getattr(project, "appPublisher", "") or "").strip() or DEFAULT_PUBLISHER
        version   = ((getattr(project, "appVersion", "") or "").strip()
                  or (project.iosVersion or "1.0.0"))

        # Calcul de l'espace disque total : taille de l'exe + tous les
        # dependfiles (resources + DLLs auto). Inno utilisera cette valeur
        # pour valider que le disque cible a assez d'espace AVANT install,
        # et l'affichera dans le dialogue "Espace requis".
        total_bytes = 0
        try:
            total_bytes += exe_path.stat().st_size
        except Exception:
            pass
        for src_abs, _arc in PackageCommand._CollectDependFiles(project, builder):
            try:
                total_bytes += src_abs.stat().st_size
            except Exception:
                pass
        # Inno ExtraDiskSpaceRequired est en BYTES (le total est ajoute au
        # calcul automatique des fichiers [Files], mais on peut aussi mettre
        # 0 si on veut juste l'auto-calcul Inno. Mettre la taille reelle
        # rend l'estimation plus robuste si certains [Files] sont skipes
        # via {code:...} conditionnels).

        # Licence : Inno accepte .txt, .rtf, .md (en .txt). On laisse le path
        # tel quel — la conversion RTF n'est requise que par WiX/MSI.
        license_line = ""
        license_src = getattr(project, "licenseFile", "")
        if license_src:
            try:
                resolved = Path(builder.ResolveProjectPath(project, license_src))
            except Exception:
                resolved = Path(license_src)
            if resolved.exists():
                license_line = f"LicenseFile={resolved}\n"
            else:
                Colored.PrintWarning(f"[package] licensefile introuvable : {license_src}")

        # Icone applicative pour les raccourcis Bureau/Menu Demarrer. Inno
        # extrait normalement l'icone de l'exe automatiquement (si embed via
        # .rc/.res au link), mais sur certains setups Windows le cache des
        # icones .lnk affiche un fichier blanc. Forcer `IconFilename=` avec
        # un .ico explicite garantit le visuel correct.
        ico_path = PackageCommand._ResolveWindowsIcoForPackage(
            project, builder, output.parent)
        icon_filename_attr = ""
        if ico_path is not None:
            icon_filename_attr = f'; IconFilename: "{{app}}\\app.ico"'

        # Raccourci bureau optionnel : controle par DSL createdesktopshortcut.
        desktop_task = ""
        desktop_icon_line = ""
        if getattr(project, "createDesktopShortcut", True):
            desktop_task = (
                '\n[Tasks]\n'
                'Name: "desktopicon"; Description: "Creer un raccourci sur le bureau"; '
                'GroupDescription: "Raccourcis supplementaires :"\n'
            )
            desktop_icon_line = (
                f'Name: "{{userdesktop}}\\{app_name}"; '
                f'Filename: "{{app}}\\{exe_path.name}"'
                f'{icon_filename_attr}; Tasks: desktopicon\n'
            )

        script = f"""
[Setup]
AppName={app_name}
AppPublisher={publisher}
AppVersion={version}
DefaultDirName={{pf}}\\{app_name}
DefaultGroupName={app_name}
UninstallDisplayIcon={{app}}\\{exe_path.name}
{license_line}DisableDirPage=no
DisableProgramGroupPage=no
Compression=lzma2
SolidCompression=yes
OutputDir=.
OutputBaseFilename={project.name}_setup
{desktop_task}
[Files]
Source: "{exe_path}"; DestDir: "{{app}}"
"""
        # Embarquer les dependfiles avec preservation de la hierarchie via
        # DestDir relatif ({{app}}\<sous-dossier>).
        for src_abs, archive_path in PackageCommand._CollectDependFiles(project, builder):
            sub_dir = Path(archive_path).parent
            dest_dir = "{app}" if str(sub_dir) in (".", "") else f"{{app}}\\{sub_dir}"
            script += f'Source: "{src_abs}"; DestDir: "{dest_dir}"\n'

        # Inclut le .ico dans {app}\app.ico pour que les raccourcis le
        # referencent avec un path absolu connu (evite le bug d'icone
        # blanche de Windows pour les .lnk).
        if ico_path is not None:
            script += f'Source: "{ico_path}"; DestDir: "{{app}}"; DestName: "app.ico"\n'

        # Icones : menu Demarrer (toujours) + bureau (optionnel via Tasks).
        # [Run] : actions post-install transparentes pour l'user :
        #   1. Une entree par regle firewall declaree via DSL (networkenabled
        #      + firewallrule). Sans regle, le jeu multijoueur LAN ne peut pas
        #      accepter de connexions entrantes (cas Pong PC<->Android).
        #      Cf [[pong_firewall_lan_fix]].
        #   2. Lancement de l'app (skipifsilent : pas en mode CI).
        #
        # [UninstallRun] : retire chaque regle Firewall ajoutee, pour ne pas
        # polluer les entries orphelines.
        from ..Core import FirewallSpec
        # Inno : on passe l'exe sous forme "{app}\<exe>" (chemin developpe a
        # l'install). On utilise des marqueurs uniques en input et on les
        # remplace par "" (le double-guillemet litteral d'Inno) en sortie pour
        # eviter de casser le f-string Python avec des triples guillemets.
        netsh_add_cmds = FirewallSpec.BuildNetshAddCommands(
            project, f"{{app}}\\{exe_path.name}")
        netsh_del_cmds = FirewallSpec.BuildNetshDeleteCommands(project)

        def _to_inno_params(netsh_full_cmd: str) -> str:
            """Convertit 'netsh advfirewall firewall add rule ...' en
            'advfirewall firewall add rule ...' (sans le prog netsh prefix)
            et echappe les " en "" (litteral Inno)."""
            stripped = netsh_full_cmd
            if stripped.startswith("netsh "):
                stripped = stripped[len("netsh "):]
            return stripped.replace('"', '""')

        firewall_run_lines: List[str] = []
        for cmd in netsh_add_cmds:
            params = _to_inno_params(cmd)
            firewall_run_lines.append(
                f'Filename: "{{sys}}\\netsh.exe"; Parameters: "{params}"; '
                f'StatusMsg: "Configuration du pare-feu Windows..."; Flags: runhidden'
            )
        firewall_uninst_lines: List[str] = []
        for cmd in netsh_del_cmds:
            params = _to_inno_params(cmd)
            firewall_uninst_lines.append(
                f'Filename: "{{sys}}\\netsh.exe"; Parameters: "{params}"; Flags: runhidden'
            )

        firewall_run_block = "\n".join(firewall_run_lines)
        firewall_uninst_block = "\n".join(firewall_uninst_lines)

        script += f"""
[Icons]
Name: "{{group}}\\{app_name}"; Filename: "{{app}}\\{exe_path.name}"{icon_filename_attr}
{desktop_icon_line}
[Run]
{firewall_run_block}
Filename: "{{app}}\\{exe_path.name}"; Description: "Lancer {app_name}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
{firewall_uninst_block}
"""
        output.write_text(script, encoding='utf-8')

    # -----------------------------------------------------------------------
    # Linux
    # -----------------------------------------------------------------------

    @staticmethod
    def _PackageLinux(project, builder, pkg_type: str, output_dir: Path) -> int:
        """Création de packages Linux (deb, rpm, AppImage, Snap)."""
        if not builder.BuildProject(project):
            return 1

        exe_path = builder.GetTargetPath(project)
        if not exe_path.exists():
            Colored.PrintError(f"Executable not found: {exe_path}")
            return 1

        if pkg_type == 'deb':
            return PackageCommand._CreateDeb(project, builder, exe_path, output_dir)
        elif pkg_type == 'rpm':
            return PackageCommand._CreateRpm(project, builder, exe_path, output_dir)
        elif pkg_type == 'appimage':
            return PackageCommand._CreateAppImage(project, builder, exe_path, output_dir)
        elif pkg_type == 'snap':
            return PackageCommand._CreateSnap(project, builder, exe_path, output_dir)
        return 1

    @staticmethod
    def _CreateDeb(project, builder, exe_path: Path, output_dir: Path) -> int:
        """Crée un package .deb."""
        import subprocess
        # Vérifier la présence de dpkg-deb
        if not FileSystem.FindExecutable("dpkg-deb"):
            Colored.PrintError("dpkg-deb not found. Cannot create .deb package.")
            return 1

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            # Créer la structure de dossier
            deb_root = tmp / "deb"
            usr_bin = deb_root / "usr" / "bin"
            usr_bin.mkdir(parents=True)
            shutil.copy2(exe_path, usr_bin / exe_path.name)

            # Embarquer les dependfiles dans /usr/share/<app>/ en preservant
            # la hierarchie. Convention Linux pour les data files.
            app_name_lower = (project.targetName or project.name).lower()
            share_dir = deb_root / "usr" / "share" / app_name_lower
            for src_abs, archive_path in PackageCommand._CollectDependFiles(project, builder):
                dst = share_dir / archive_path
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src_abs, dst)

            # Créer le fichier DEBIAN/control
            control_dir = deb_root / "DEBIAN"
            control_dir.mkdir()
            control = f"""Package: {project.targetName or project.name}
Version: {project.appVersion or project.iosVersion or '1.0.0'}
Section: utils
Priority: optional
Architecture: amd64
Maintainer: {project.appPublisher or DEFAULT_PUBLISHER} <{DEFAULT_EMAIL}>
Description: {project.name} packaged by Jenga
"""
            (control_dir / "control").write_text(control, encoding='utf-8')

            # Hooks postinst / postrm : ouvre/retire les ports firewall si
            # networkenabled() / firewallrule() declares. Detection runtime
            # de ufw/firewalld/iptables. Voir Core/FirewallSpec.py.
            from ..Core import FirewallSpec
            postinst_lines = FirewallSpec.BuildLinuxFirewallAddScript(project)
            postrm_lines = FirewallSpec.BuildLinuxFirewallRemoveScript(project)
            if postinst_lines:
                postinst = control_dir / "postinst"
                postinst.write_text("\n".join(postinst_lines), encoding="utf-8")
                # dpkg-deb exige que les hooks soient executables.
                import stat as _stat
                postinst.chmod(postinst.stat().st_mode | _stat.S_IEXEC | _stat.S_IXGRP | _stat.S_IXOTH)
            if postrm_lines:
                postrm = control_dir / "postrm"
                postrm.write_text("\n".join(postrm_lines), encoding="utf-8")
                import stat as _stat
                postrm.chmod(postrm.stat().st_mode | _stat.S_IEXEC | _stat.S_IXGRP | _stat.S_IXOTH)

            # Construire le .deb
            deb_path = output_dir / f"{project.name}.deb"
            subprocess.run(["dpkg-deb", "--build", str(deb_root), str(deb_path)], check=True)
            Colored.PrintSuccess(f"DEB package: {deb_path}")
            return 0

    @staticmethod
    def _CreateRpm(project, builder, exe_path: Path, output_dir: Path) -> int:
        """Crée un package .rpm (nécessite rpmbuild)."""
        Colored.PrintWarning("RPM packaging not yet implemented.")
        return 1

    @staticmethod
    def _CreateAppImage(project, builder, exe_path: Path, output_dir: Path) -> int:
        """Crée un AppImage (nécessite appimagetool)."""
        Colored.PrintWarning("AppImage packaging not yet implemented.")
        return 1

    @staticmethod
    def _CreateSnap(project, builder, exe_path: Path, output_dir: Path) -> int:
        """Crée un Snap package (nécessite snapcraft)."""
        Colored.PrintWarning("Snap packaging not yet implemented.")
        return 1

    # -----------------------------------------------------------------------
    # macOS
    # -----------------------------------------------------------------------

    @staticmethod
    def _PackageMacOS(project, builder, pkg_type: str, output_dir: Path) -> int:
        """Création de package macOS (PKG, DMG)."""
        if not builder.BuildProject(project):
            return 1

        if pkg_type == 'pkg':
            # Utiliser pkgbuild
            if not FileSystem.FindExecutable("pkgbuild"):
                Colored.PrintError("pkgbuild not found (macOS required).")
                return 1
            app_bundle = builder.GetTargetDir(project) / f"{project.targetName or project.name}.app"
            if not app_bundle.exists():
                Colored.PrintError(f".app bundle not found: {app_bundle}")
                return 1
            # Copie des dependfiles a cote du .app dans le root scanne par
            # pkgbuild. Ils preservent leur hierarchie relative au workspace.
            pkg_root = app_bundle.parent
            for src_abs, archive_path in PackageCommand._CollectDependFiles(project, builder):
                dst = pkg_root / archive_path
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src_abs, dst)
            pkg_path = output_dir / f"{project.name}.pkg"

            # Postinstall script firewall (si reseau active via DSL). Il
            # autorise l'app dans /usr/libexec/ApplicationFirewall/socketfilterfw.
            # On le place dans un dossier scripts/ separe (pas dans pkg_root,
            # sinon pkgbuild le verrait comme un fichier a installer).
            from ..Core import FirewallSpec
            scripts_dir = PackageCommand._BuildMacosPkgScripts(
                project, output_dir, FirewallSpec)

            cmd = ["pkgbuild",
                   "--root", str(pkg_root),
                   "--identifier", project.iosBundleId or f"com.{project.name}",
                   "--version", project.appVersion or project.iosVersion or "1.0.0"]
            if scripts_dir is not None:
                # --scripts : pkgbuild execute postinstall apres copie des
                # fichiers. Le script herite des privileges admin (l'install
                # macOS demande l'autorisation a l'user au moment du run).
                cmd += ["--scripts", str(scripts_dir)]
            cmd.append(str(pkg_path))
            if Process.Run(cmd) == 0:
                Colored.PrintSuccess(f"PKG package: {pkg_path}")
                return 0
            return 1

        elif pkg_type == 'dmg':
            # Utiliser create-dmg
            if not FileSystem.FindExecutable("create-dmg"):
                Colored.PrintWarning("create-dmg not found. Install with: brew install create-dmg")
                return 1
            app_bundle = builder.GetTargetDir(project) / f"{project.targetName or project.name}.app"
            if not app_bundle.exists():
                return 1
            dmg_path = output_dir / f"{project.name}.dmg"
            cmd = ["create-dmg", "--volname", project.name, str(dmg_path), str(app_bundle)]
            if Process.Run(cmd) == 0:
                Colored.PrintSuccess(f"DMG package: {dmg_path}")
                return 0
            return 1

        return 1

    # -----------------------------------------------------------------------
    # Installateur self-extracting MAISON (type 'jng') — multi-plateforme,
    # sans dependance externe (Jenga/Tools/Installer).
    # -----------------------------------------------------------------------
    @staticmethod
    def _PackageSelfExtract(project, builder, output_dir: Path, platform: str) -> int:
        """Construit un installateur self-extracting (stub C compile + payload).

        Reutilise dependfiles(), l'icone, licensefile() et Core/FirewallSpec.
        C'est une OPTION de plus : msi/exe/zip/deb/pkg restent disponibles.
        """
        try:
            from ..Tools.Installer import BuildInstaller, BuilderError, DetectCCompiler
        except Exception as e:
            Colored.PrintError(f"Module Installer indisponible : {e}")
            return 1
        from ..Core import FirewallSpec

        if DetectCCompiler() is None:
            Colored.PrintError(
                "Aucun compilateur C (cc/clang/gcc/cl) pour construire "
                "l'installateur self-extracting (--type jng).")
            return 1

        if not builder.BuildProject(project):
            Colored.PrintError("Build failed, cannot package.")
            return 1
        exe_path = builder.GetTargetPath(project)
        if not exe_path.exists():
            Colored.PrintError(f"Executable not found: {exe_path}")
            return 1

        app_name = project.targetName or project.name
        exe_name = exe_path.name

        # Fichiers embarques : exe principal + dependfiles (resources, DLLs auto).
        files = [(exe_name, str(exe_path), 0o755)]
        for src_abs, archive_path in PackageCommand._CollectDependFiles(project, builder):
            files.append((archive_path.replace("\\", "/"), str(src_abs), 0o644))

        # Manifeste
        publisher = (getattr(project, "appPublisher", "") or "").strip() or DEFAULT_PUBLISHER
        version = (getattr(project, "appVersion", "") or getattr(project, "iosVersion", "") or "1.0.0")
        manifest = {
            "name": app_name,
            "version": version,
            "publisher": publisher,
            "exe": exe_name,
            "default_dir_windows": rf"%LOCALAPPDATA%\Programs\{app_name}",
            "default_dir_linux": f"~/.local/opt/{app_name}",
            "default_dir_macos": f"/Applications/{app_name}",
            "shortcut_menu": "1",
        }
        if getattr(project, "createDesktopShortcut", True):
            manifest["shortcut_desktop"] = "1"

        # Icone : on garde l'icone user CLEAN dans l'archive (raccourcis user)
        # et on incruste un petit marquage "Jenga" UNIQUEMENT sur l'icone du
        # stub Setup.exe (anti-faux-positifs AV + identification claire qu'il
        # s'agit d'un installateur Jenga).
        stub_icon_path: Optional[str] = None
        try:
            ico = PackageCommand._ResolveWindowsIcoForPackage(project, builder, output_dir)
            if ico is not None and Path(ico).exists():
                files.append((Path(ico).name, str(ico), 0o644))
                manifest["icon"] = Path(ico).name
                if platform == "windows":
                    stub_icon_path = PackageCommand._ComposeStubIcon(Path(ico), output_dir, app_name)
        except Exception:
            pass

        # Pare-feu Windows : commandes netsh avec placeholder {exe} (substitue
        # par le stub avec le chemin reel de l'exe installe).
        if platform == "windows":
            add_cmds = FirewallSpec.BuildNetshAddCommands(project, "{exe}")
            del_cmds = FirewallSpec.BuildNetshDeleteCommands(project)
            if add_cmds:
                manifest["firewall_add"] = " & ".join(add_cmds)
            if del_cmds:
                manifest["firewall_del"] = " & ".join(del_cmds)

        # UAC : asInvoker par defaut (anti-faux-positifs AV). Si une regle de
        # pare-feu netsh est embarquee, elle exige admin -> requireAdministrator.
        # L'utilisateur peut forcer via project.signRequireAdmin.
        require_admin_attr = getattr(project, "signRequireAdmin", None)
        if require_admin_attr is None:
            require_admin = bool(manifest.get("firewall_add"))
        else:
            require_admin = bool(require_admin_attr)

        # Signature de code : options optionnelles du DSL (signingcertificate,
        # signingidentity, signingthumbprint, signingtimestampurl, signinggpgkey).
        sign_options = PackageCommand._CollectSignOptions(project)

        # Construction de l'installateur.
        ext = ".exe" if platform == "windows" else ".run"
        out = output_dir / f"{project.name}-setup{ext}"
        try:
            BuildInstaller(files, manifest, out, verbose=False,
                           platform=platform, require_admin=require_admin,
                           icon_path=stub_icon_path, sign_options=sign_options)
        except BuilderError as e:
            Colored.PrintError(f"Echec construction de l'installateur : {e}")
            return 1
        Colored.PrintSuccess(f"Installateur self-extracting (jng) : {out}")
        return 0

    # -----------------------------------------------------------------------
    # Composition de l'icone du stub Setup.exe : icone user + "Jenga" incruste.
    # -----------------------------------------------------------------------
    @staticmethod
    def _ComposeStubIcon(user_ico: Path, output_dir: Path, app_name: str) -> str:
        """Produit `<output_dir>/<app_name>-setup-icon.ico` avec l'icone user +
        marquage "Jenga" en bas a droite. Retourne le chemin de l'icone
        composee, ou de l'icone user d'origine en fallback (Pillow absent /
        composition echouee)."""
        try:
            from ..Tools.Installer import ComposeInstallerIcon, IsBrandingAvailable
        except Exception:
            return str(user_ico)
        if not IsBrandingAvailable():
            return str(user_ico)
        branded = output_dir / f"{app_name}-setup-icon.ico"
        ok = ComposeInstallerIcon(user_ico, branded, brand_text="Jenga")
        return str(branded) if ok and branded.exists() else str(user_ico)

    # -----------------------------------------------------------------------
    # Collecte des options de signature de code depuis le DSL du projet.
    # -----------------------------------------------------------------------
    @staticmethod
    def _CollectSignOptions(project) -> Optional[Dict[str, str]]:
        """Lit les attributs DSL de signature et renvoie un dict (ou None).

        DSL (cf. Api.py) : signingcertificate(path), signingpassword(pwd),
        signingthumbprint(hex), signingidentity(name), signingtimestampurl(url),
        signinggpgkey(id), signingentitlements(path)."""
        keys = {
            "signCertificate":   "cert_file",
            "signPassword":      "cert_password",
            "signThumbprint":    "cert_thumbprint",
            "signIdentity":      "identity",
            "signTimestampUrl":  "timestamp_url",
            "signGpgKey":        "gpg_key",
            "signEntitlements":  "entitlements",
            "signEnabled":       "enabled",
        }
        opts: Dict[str, str] = {}
        for attr, key in keys.items():
            value = getattr(project, attr, None)
            if value:
                opts[key] = str(value)
        return opts or None

    @staticmethod
    def _BuildMacosPkgScripts(project, output_dir: Path, FirewallSpec) -> Optional[Path]:
        """
        Genere un dossier scripts/ pour pkgbuild --scripts contenant postinstall
        et postupgrade qui autorisent l'app dans le pare-feu applicatif macOS
        (socketfilterfw). Retourne le path du dossier ou None si rien a faire.

        Convention pkgbuild :
          - postinstall : execute apres installation des fichiers.
              $1 = path du .pkg, $2 = location d'install, $3 = volume target.
          - postupgrade : execute lors d'une mise a jour. Idem $1/$2/$3.
        """
        add_lines = FirewallSpec.BuildSocketfilterfwAddScript(project, "$2")
        if not add_lines:
            return None
        scripts_dir = output_dir / f"{project.name}_pkg_scripts"
        if scripts_dir.exists():
            shutil.rmtree(scripts_dir)
        scripts_dir.mkdir(parents=True)
        postinstall = scripts_dir / "postinstall"
        content = "#!/bin/sh\nset -e\n\n" + "\n".join(add_lines) + "\nexit 0\n"
        postinstall.write_text(content, encoding="utf-8")
        # pkgbuild exige que le script soit executable (sinon il l'ignore).
        import stat as _stat
        postinstall.chmod(postinstall.stat().st_mode | _stat.S_IEXEC | _stat.S_IXGRP | _stat.S_IXOTH)
        # Idem postupgrade (meme contenu) pour les mises a jour.
        postupgrade = scripts_dir / "postupgrade"
        postupgrade.write_text(content, encoding="utf-8")
        postupgrade.chmod(postupgrade.stat().st_mode | _stat.S_IEXEC | _stat.S_IXGRP | _stat.S_IXOTH)
        return scripts_dir

    # -----------------------------------------------------------------------
    # Web (Emscripten)
    # -----------------------------------------------------------------------

    @staticmethod
    def _PackageWeb(project, builder, pkg_type: str, output_dir: Path) -> int:
        """Création d'un ZIP pour WebAssembly."""
        if pkg_type != 'zip':
            Colored.PrintError("Only ZIP packaging is supported for Web platform.")
            return 1
        if not builder.BuildProject(project):
            return 1

        target_dir = builder.GetTargetDir(project)
        # Inclure les artefacts WebAssembly + favicons generes par le builder
        # Emscripten (favicon.ico, favicon-*.png).
        import zipfile
        zip_path = output_dir / f"{project.targetName or project.name}.zip"
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            for ext in ['.html', '.js', '.wasm', '.data', '.ico']:
                for f in target_dir.glob(f"*{ext}"):
                    zf.write(f, f.name)
            # PNG favicons (favicon-16.png, favicon-32.png, ...)
            for f in target_dir.glob("favicon-*.png"):
                zf.write(f, f.name)
            # Dependfiles (assets data, etc.)
            for src_abs, archive_path in PackageCommand._CollectDependFiles(project, builder):
                zf.write(src_abs, archive_path)
        Colored.PrintSuccess(f"Web ZIP package: {zip_path}")
        return 0

    @staticmethod
    def _PackageHarmonyOS(project, builder, pkg_type: str, output_dir: Path) -> int:
        """Packaging HarmonyOS : compile le .so via OHOS NDK, puis invoque hvigor."""
        import subprocess, shutil, os

        # 1. Compiler le projet
        if not builder.BuildProject(project):
            Colored.PrintError("Build failed, cannot package.")
            return 1

        so_dir = builder.GetTargetDir(project)
        so_files = list(so_dir.glob("*.so"))
        if not so_files:
            Colored.PrintError("No .so found after build.")
            return 1

        # 2. Trouver hvigorw — OHOS_SDK pointe vers .../sdk/default/openharmony
        #    on remonte 3 niveaux pour atteindre command-line-tools/
        ohos_sdk   = os.environ.get("OHOS_SDK", "")
        harmony_sdk = getattr(builder.workspace, "harmonySdkPath", "")

        if ohos_sdk:
            cli_tools = Path(ohos_sdk).parents[2]
        elif harmony_sdk:
            # harmonysdk() peut pointer vers openharmony/ ou command-line-tools/
            p = Path(harmony_sdk)
            cli_tools = p.parents[2] if p.name == "openharmony" else p
        else:
            cli_tools = Path("C:/ohos/command-line-tools")

        hvigor_wrapper = cli_tools / "bin" / "hvigorw.bat"
        if not hvigor_wrapper.exists():
            hvigor_wrapper = cli_tools / "bin" / "hvigorw"
        if not hvigor_wrapper.exists():
            Colored.PrintError(
                f"hvigorw not found in {cli_tools / 'bin'}.\n"
                "Set OHOS_SDK env var or harmonysdk() in your .jenga."
            )
            return 1

        # 3. Copier le .so dans <project>/libs/arm64-v8a/
        hap_root = Path(project.location)
        libs_dir = hap_root / "libs" / "arm64-v8a"
        libs_dir.mkdir(parents=True, exist_ok=True)
        for so in so_files:
            shutil.copy2(so, libs_dir / so.name)
            Colored.PrintInfo(f"Copied {so.name} -> {libs_dir}")

        # 4. Invoquer hvigor
        result = subprocess.run(
            [str(hvigor_wrapper), "assembleHap",
            "--mode", "module",
            "-p", "product=default"],
            cwd=str(hap_root)
        )
        if result.returncode != 0:
            Colored.PrintError("hvigor assembleHap failed.")
            return 1

        # 5. Récupérer et copier le .hap
        hap_files = list(hap_root.rglob("*.hap"))
        if not hap_files:
            Colored.PrintError("No .hap generated by hvigor.")
            return 1

        for hap in hap_files:
            dest = output_dir / hap.name
            shutil.copy2(hap, dest)
            Colored.PrintSuccess(f"HAP packaged: {dest}")

        return 0