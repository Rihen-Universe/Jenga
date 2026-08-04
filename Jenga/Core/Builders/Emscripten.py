#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Emscripten Builder – Compilation WebAssembly.
Gère les bibliothèques partagées (SIDE_MODULE) et les applications (MAIN_MODULE).
"""

from pathlib import Path
from typing import List, Optional
import shlex
import os
import shutil

from Jenga.Core.Api import Project, ProjectKind
from ...Utils import Process, FileSystem, ProcessResult, Colored
from ..Builder import Builder
from ..IconConverter import (
    ResolveIconFor, DetectIconFormat, GenerateFaviconSet, HasPillow,
    PLATFORM_WEB, FORMAT_PNG, FORMAT_JPG,
)
# Port par defaut du petit serveur HTTP genere a cote du .html (scripts .bat/.sh).
# 9001 plutot que 8080, trop souvent deja pris par un autre service. Expose comme
# CONSTANTE : les tests s'y referent au lieu de recopier le chiffre, sinon chaque
# changement de port cassait un test sans que rien ne soit casse.
EMSCRIPTEN_DEFAULT_PORT = 9001


class EmscriptenBuilder(Builder):
    """
    Builder pour WebAssembly via Emscripten.
    Supporte :
      - STATIC_LIB  → archive .a
      - SHARED_LIB  → side module .wasm (avec -sSIDE_MODULE=1)
      - CONSOLE_APP / WINDOWED_APP → main module .html/.js/.wasm (avec -sMAIN_MODULE=1 si dépendances partagées)
    """

    def GetObjectExtension(self) -> str:
        return ".o"

    @staticmethod
    def _EnumValue(v):
        return v.value if hasattr(v, "value") else v

    def GetSharedLibExtensions(self) -> List[str]:
        """Sur Emscripten, les bibliothèques dynamiques sont des side modules .wasm."""
        return [".wasm"]

    def PreparePCH(self, project: Project, objDir: Path) -> bool:
        project._jengaPchFile = ""
        project._jengaPchHeaderResolved = ""
        project._jengaPchSourceResolved = ""
        if not project.pchHeader:
            return True
        header = Path(self.ResolveProjectPath(project, project.pchHeader))
        if not header.exists():
            return False
        pch_path = objDir / f"{project.name}.pch"
        compiler = self.toolchain.cxxPath or self.toolchain.ccPath
        args = [compiler, "-x", "c++-header", str(header), "-o", str(pch_path)]
        pch_flags = []
        skip_next = False
        for f in self._GetCompilerFlags(project):
            if skip_next:
                skip_next = False
                continue
            if f == "-include-pch":
                skip_next = True
                continue
            pch_flags.append(f)
        args.extend(pch_flags)
        result = Process.ExecuteCommand(args, captureOutput=True, silent=False)
        self._lastResult = result
        if result.returnCode != 0:
            return False
        project._jengaPchFile = str(pch_path)
        project._jengaPchHeaderResolved = str(header)
        if project.pchSource:
            project._jengaPchSourceResolved = self.ResolveProjectPath(project, project.pchSource)
        return True

    def GetOutputExtension(self, project: Project) -> str:
        if project.kind == ProjectKind.STATIC_LIB:
            return ".a"
        if project.kind == ProjectKind.SHARED_LIB:
            return ".wasm"
        # Pour les applications, on génère un .html (qui référence .js et .wasm)
        return ".html"

    def GetTargetPath(self, project: Project) -> Path:
        """Retourne le chemin complet du fichier de sortie du projet."""
        target_dir = self.GetTargetDir(project)
        target_name = project.targetName or project.name
        ext = self.GetOutputExtension(project)
        return target_dir / f"{target_name}{ext}"

    def Compile(self, project: Project, sourceFile: str, objectFile: str) -> ProcessResult:
        src = Path(sourceFile)
        obj = Path(objectFile)
        FileSystem.MakeDirectory(obj.parent)

        compiler = self.toolchain.cxxPath if project.language.value in ("C++", "Objective-C++") else self.toolchain.ccPath
        args = [compiler, "-c", "-o", str(obj)]
        args.extend(self.GetDependencyFlags(str(obj)))
        args.extend(self._GetCompilerFlags(project))
        args.extend(self.GetModuleFlags(project, sourceFile))
        args.append(str(src))

        use_shell = compiler and (str(compiler).endswith('.bat') or str(compiler).endswith('.cmd'))
        result = Process.ExecuteCommand(args, captureOutput=True, silent=False, shell=use_shell)
        self._lastResult = result
        return result

    def GetModuleFlags(self, project: Project, sourceFile: str) -> List[str]:
        flags = []
        if not self.IsModuleFile(sourceFile):
            return flags
        flags.extend(["-fmodules", "-fbuiltin-module-map", "-std=c++20"])
        obj_dir = self.GetObjectDir(project)
        pcm_name = Path(sourceFile).with_suffix('.pcm').name
        pcm_path = obj_dir / pcm_name
        flags.append(f"-o{str(pcm_path)}")
        return flags

    def _CollectSideModuleNames(self, project: Project) -> List[str]:
        """Collecte les noms de fichiers des side modules (.wasm) dont dépend le projet."""
        names = []
        for dep_name in project.links:
            dep_proj = self.workspace.projects.get(dep_name)
            if dep_proj and dep_proj.kind == ProjectKind.SHARED_LIB:
                names.append(dep_proj.targetName or dep_proj.name)
        return names

    def _CollectSideModulePaths(self, project: Project) -> List[Path]:
        """Collecte les chemins des side modules (.wasm) compilés dont dépend le projet."""
        paths = []
        for dep_name in project.links:
            dep_proj = self.workspace.projects.get(dep_name)
            if dep_proj and dep_proj.kind == ProjectKind.SHARED_LIB:
                dep_out = self.GetTargetPath(dep_proj)
                if dep_out.exists():
                    paths.append(dep_out)
                else:
                    print(f"[WARNING] Side module not found: {dep_out}")
        return paths

    def Link(self, project: Project, objectFiles: List[str], outputFile: str) -> bool:
        out = Path(outputFile)
        FileSystem.MakeDirectory(out.parent)

        if project.kind == ProjectKind.STATIC_LIB:
            ar = self.toolchain.arPath or "emar"
            args = [ar, "rcs", str(out)] + objectFiles
            use_shell = ar and (str(ar).endswith('.bat') or str(ar).endswith('.cmd'))
            result = Process.ExecuteCommand(args, captureOutput=True, silent=False, shell=use_shell)
            self._lastResult = result
            return result.returnCode == 0

        linker = self.toolchain.cxxPath or self.toolchain.ccPath
        args = [linker]

        if project.kind == ProjectKind.SHARED_LIB:
            args.append("-sSIDE_MODULE=1")
            args.append("-sEXPORT_ALL=1")
        elif project.kind in (ProjectKind.CONSOLE_APP, ProjectKind.WINDOWED_APP):
            # N'activer MAIN_MODULE que si des side-modules existent réellement.
            # Forcer MAIN_MODULE pour une app standalone dégrade le runtime JS
            # (callbacks indirects/dynCall) et peut casser les entrées HTML5.
            side_module_names = self._CollectSideModuleNames(project)
            if side_module_names:
                args.append("-sMAIN_MODULE=1")
                args.append("-sERROR_ON_UNDEFINED_SYMBOLS=0")

                # RUNTIME_LINKED_LIBS : indique à Emscripten quels .wasm charger au démarrage
                libs_list = ",".join(f'"{name}.wasm"' for name in side_module_names)
                args.append(f"-sRUNTIME_LINKED_LIBS=[{libs_list}]")

                # Passer les .wasm au linker pour résoudre les symboles à la compilation
                # (sans ça, Emscripten génère "external symbol is missing" au runtime)
                for wasm_path in self._CollectSideModulePaths(project):
                    args.append(str(wasm_path))

        args += ["-o", str(out)]
        args.extend(self._GetLinkerFlags(project))
        args.extend(objectFiles)

        for libdir in project.libDirs:
            args.append(f"-L{self.ResolveProjectPath(project, libdir)}")
        for lib in project.links:
            # Ne pas re-passer les side modules WASM via -l (déjà passés en chemin direct ci-dessus)
            dep_proj = self.workspace.projects.get(lib)
            if dep_proj and dep_proj.kind == ProjectKind.SHARED_LIB:
                continue
            if self._IsDirectLibPath(lib):
                args.append(self.ResolveProjectPath(project, lib))
            else:
                args.append(f"-l{lib}")
        args.extend(self.toolchain.ldflags)

        use_shell = linker and (str(linker).endswith('.bat') or str(linker).endswith('.cmd'))
        result = Process.ExecuteCommand(args, captureOutput=True, silent=False, shell=use_shell)
        self._lastResult = result

        if result.returnCode == 0:
            self._GenerateRunnerScripts(project, out)
            # Genere les favicons (favicon.ico + favicon-*.png) a cote du .html
            # pour les apps web. Pas d'effet pour les libs ou si aucune icone
            # n'est configuree via appicon() ou webfavicon().
            if project.kind in (ProjectKind.CONSOLE_APP, ProjectKind.WINDOWED_APP):
                self._GenerateWebFavicons(project, out)

        return result.returnCode == 0

    # -----------------------------------------------------------------------
    # Favicon set : genere favicon.ico + favicon-*.png a cote du .html
    # Le template emscripten_fullscreen.html reference ces fichiers via <link>.
    # -----------------------------------------------------------------------
    def _GenerateWebFavicons(self, project: Project, output_path: Path) -> None:
        icon_src = ResolveIconFor(project, PLATFORM_WEB)
        if not icon_src:
            return

        icon_path = Path(self.ResolveProjectPath(project, icon_src))
        if not icon_path.exists():
            Colored.PrintWarning(
                f"[Web:icon] icone configuree introuvable : {icon_path}"
            )
            return

        fmt = DetectIconFormat(icon_path)
        if fmt not in (FORMAT_PNG, FORMAT_JPG):
            Colored.PrintWarning(
                f"[Web:icon] format non supporte ({fmt}) pour le favicon : {icon_path}"
            )
            return
        if not HasPillow():
            Colored.PrintWarning(
                "[Web:icon] Pillow non installe -- generation favicons ignoree. "
                "Installer : pip install Pillow"
            )
            return

        dst_dir = output_path.parent
        generated = GenerateFaviconSet(icon_path, dst_dir)
        if not generated:
            Colored.PrintWarning(f"[Web:icon] generation favicon set echouee : {icon_path}")

    def _GenerateRunnerScripts(self, project: Project, output_path: Path) -> None:
        """Génère les scripts de lancement pour le serveur HTTP local."""
        if project.kind not in (ProjectKind.CONSOLE_APP, ProjectKind.WINDOWED_APP, ProjectKind.TEST_SUITE):
            return

        html_name = output_path.name
        proj_name = project.name
        out_dir = output_path.parent
        port_default = EMSCRIPTEN_DEFAULT_PORT

        # --- Script Windows (.bat) ---
        bat_content = f'''@echo off
title {proj_name}
setlocal enabledelayedexpansion

set PORT=%1
if "%PORT%"=="" set PORT={port_default}

echo ================================================
echo  {proj_name} — WASM Runner
echo ================================================
echo.
echo  Server: http://localhost:!PORT!/{html_name}
echo  CTRL+C to stop.
echo.

:: Se placer dans le répertoire du script
pushd "%~dp0" || (
    echo Erreur : impossible d'accéder au répertoire "%~dp0"
    pause
    exit /b 1
)

:: Vérifier que le fichier HTML existe
if not exist "{html_name}" (
    echo Erreur : fichier {html_name} introuvable dans "%~dp0"
    echo Assurez-vous que la compilation WebAssembly a réussi.
    pause
    exit /b 1
)

:: Lancer le navigateur après un délai (1 seconde)
start /B "" cmd /c "timeout /t 1 /nobreak >nul & start \"\" \"http://localhost:!PORT!/{html_name}\""

:: Démarrer le serveur HTTP
python -m http.server !PORT!
if errorlevel 1 (
    py -m http.server !PORT!
    if errorlevel 1 (
        python3 -m http.server !PORT!
        if errorlevel 1 (
            echo Erreur : impossible de démarrer le serveur HTTP.
            pause
            exit /b 1
        )
    )
)
popd
endlocal
'''
        bat_path = out_dir / f"{proj_name}.bat"
        try:
            bat_path.write_text(bat_content, encoding="utf-8")
        except OSError:
            pass

        # --- Script Unix (.sh) ---
        sh_content = f'''#!/usr/bin/env bash
PORT="${{1:-{port_default}}}"
SCRIPT_DIR="$(cd "$(dirname "${{BASH_SOURCE[0]}}")" && pwd)"

echo "================================================"
echo " {proj_name} — WASM Runner"
echo "================================================"
echo ""
echo " Server: http://localhost:$PORT/{html_name}"
echo " CTRL+C to stop."
echo ""

cd "$SCRIPT_DIR" || {{ echo "Erreur : impossible d'accéder à $SCRIPT_DIR"; exit 1; }}

# Vérifier que le fichier HTML existe
if [ ! -f "{html_name}" ]; then
    echo "Erreur : fichier {html_name} introuvable dans $SCRIPT_DIR"
    echo "Assurez-vous que la compilation WebAssembly a réussi."
    exit 1
fi

# Lancer le navigateur après un délai
( sleep 1; xdg-open "http://localhost:$PORT/{html_name}" 2>/dev/null || open "http://localhost:$PORT/{html_name}" 2>/dev/null ) &

# Démarrer le serveur HTTP
if command -v python3 &>/dev/null; then
    python3 -m http.server "$PORT"
elif command -v python &>/dev/null; then
    python -m http.server "$PORT"
else
    echo "Erreur : Python introuvable."
    exit 1
fi
'''
        sh_path = out_dir / f"{proj_name}.sh"
        try:
            sh_path.write_text(sh_content, encoding="utf-8")
            sh_path.chmod(sh_path.stat().st_mode | 0o111)
        except OSError:
            pass

    @staticmethod
    def _IsDirectLibPath(lib: str) -> bool:
        p = Path(lib)
        return p.suffix in (".a", ".bc", ".o", ".so", ".dylib", ".lib") or "/" in lib or "\\" in lib or p.is_absolute()

    def _ResolveOptionBool(self, *names: str):
        """Résout une option booléenne depuis la ligne de commande."""
        tokens = [str(opt).strip().lower() for opt in getattr(self, "options", []) if str(opt).strip()]
        for raw_name in names:
            name = str(raw_name).strip().lower()
            if not name:
                continue
            for token in tokens:
                if token == name:
                    return True
                prefix = f"{name}="
                if token.startswith(prefix):
                    value = token[len(prefix):].strip().lower()
                    if value in ("", "1", "true", "yes", "on"):
                        return True
                    if value in ("0", "false", "no", "off"):
                        return False
                    return True
        return None

    def _ResolveShellFile(self, project: Project) -> str:
        """Détermine le fichier shell HTML à utiliser."""
        explicit = str(getattr(project, 'emscriptenShellFile', '') or '').strip()
        if explicit:
            return explicit

        cli_toggle = self._ResolveOptionBool(
            "emscripten-fullscreen-shell",
            "emscripten-fullscreen",
        )
        if cli_toggle is not None:
            return "emscripten_fullscreen.html" if cli_toggle else ""

        project_toggle = getattr(project, 'emscriptenUseFullscreenShell', None)
        if project_toggle is not None:
            return "emscripten_fullscreen.html" if bool(project_toggle) else ""

        workspace_toggle = bool(getattr(self.workspace, 'emscriptenDefaultFullscreenShell', True))
        return "emscripten_fullscreen.html" if workspace_toggle else ""

    def _GetCompilerFlags(self, project: Project) -> List[str]:
        flags = []

        # Includes
        for inc in project.includeDirs:
            flags.append(f"-I{self.ResolveProjectPath(project, inc)}")
        pch_file = getattr(project, "_jengaPchFile", "")
        if pch_file:
            flags.extend(["-include-pch", pch_file])

        # Définitions
        for define in self.toolchain.defines:
            flags.append(f"-D{define}")
        for define in project.defines:
            flags.append(f"-D{define}")
        flags.append("-D__EMSCRIPTEN__")

        # PIC pour les bibliothèques partagées (obligatoire pour les side modules)
        if project.kind == ProjectKind.SHARED_LIB:
            flags.append("-fPIC")

        # Debug
        if project.symbols:
            flags.append("-g")
            flags.append("-gsource-map")

        # Optimisation
        opt = self._EnumValue(project.optimize)
        if opt == "Off":
            flags.append("-O0")
        elif opt == "Size":
            flags.append("-Os")
        elif opt == "Speed":
            flags.append("-O2")
        elif opt == "Full":
            flags.append("-O3")

        # Warnings
        warn = self._EnumValue(project.warnings)
        if warn == "All":
            flags.append("-Wall")
        elif warn == "Extra":
            flags.append("-Wextra")
        elif warn == "Error":
            flags.append("-Werror")

        # Standard
        if project.language.value == "C++":
            flags.append(f"-std={project.cppdialect.lower()}")
            flags.extend(self.toolchain.cxxflags)
        else:
            flags.append(f"-std={project.cdialect.lower()}")
            flags.extend(self.toolchain.cflags)

        # Flags d'importation des modules C++20 précompilés
        flags.extend(self._GetModuleImportFlags(project))

        return flags

    def _GetLinkerFlags(self, project: Project) -> List[str]:
        flags = []

        # Mode de sortie : toujours WASM
        flags.extend(["-s", "WASM=1"])

        # ALLOW_MEMORY_GROWTH n'est pas compatible avec les side modules
        if project.kind != ProjectKind.SHARED_LIB:
            flags.extend(["-s", "ALLOW_MEMORY_GROWTH=1"])

        # Shell file (uniquement pour les applications)
        if project.kind in (ProjectKind.CONSOLE_APP, ProjectKind.WINDOWED_APP):
            shell_file = self._ResolveShellFile(project)
            if shell_file:
                shell_path = Path(self.ResolveProjectPath(project, shell_file))
                if shell_path.exists():
                    flags.extend(["--shell-file", str(shell_path)])
                else:
                    template_path = Path(__file__).parent.parent.parent / "Templates" / shell_file
                    if template_path.exists():
                        flags.extend(["--shell-file", str(template_path)])

        # Canvas ID (applications)
        if project.kind in (ProjectKind.CONSOLE_APP, ProjectKind.WINDOWED_APP):
            canvas_id = getattr(project, 'emscriptenCanvasId', 'canvas')
            if canvas_id != 'canvas':
                flags.extend(["-s", f"CANVAS_ID='{canvas_id}'"])

        # Initial memory (applications)
        if project.kind in (ProjectKind.CONSOLE_APP, ProjectKind.WINDOWED_APP):
            initial_memory = getattr(project, 'emscriptenInitialMemory', 16)
            if initial_memory > 0:
                flags.extend(["-s", f"INITIAL_MEMORY={initial_memory}MB"])

        # Stack size (applications)
        if project.kind in (ProjectKind.CONSOLE_APP, ProjectKind.WINDOWED_APP):
            stack_size = getattr(project, 'emscriptenStackSize', 5)
            if stack_size > 0:
                flags.extend(["-s", f"STACK_SIZE={stack_size}MB"])

        # Export name (applications)
        if project.kind in (ProjectKind.CONSOLE_APP, ProjectKind.WINDOWED_APP):
            export_name = getattr(project, 'emscriptenExportName', 'Module')
            if export_name != 'Module':
                flags.extend(["-s", f"EXPORT_NAME='{export_name}'"])

        # Extra flags
        extra_flags = getattr(project, 'emscriptenExtraFlags', [])
        if extra_flags:
            flags.extend(extra_flags)

        # Optimisation de la taille
        if self._EnumValue(project.optimize) == "Size":
            flags.append("-Oz")

        # Flags utilisateur
        for f in project.ldflags:
            if isinstance(f, str):
                flags.extend(shlex.split(f))
            else:
                flags.append(str(f))

        return flags
