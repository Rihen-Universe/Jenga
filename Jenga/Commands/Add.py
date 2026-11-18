#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Add command – Ajoute des fichiers à un projet existant.
Alias : file
Peut ajouter des fichiers sources, includes, dépendances, defines, etc.
Modifie directement le fichier .jenga pour persistance.
"""

import argparse
import sys
import re
from pathlib import Path
from typing import List, Optional, Tuple

from ..Utils import Colored, FileSystem, Display
from ..Core.Loader import Loader
from ..Core.Cache import Cache
from ..Core import Api


class AddCommand:
    """jenga file [PROJECT] [--src FILES] [--inc DIRS] [--link LIBS] [--def DEFINES] [--type TYPE]"""

    @staticmethod
    def Execute(args: List[str]) -> int:
        parser = argparse.ArgumentParser(
            prog="jenga file",
            description="Add files, include directories, libraries or defines to a project.",
            epilog="Examples:\n"
                   "  jenga file MyProject --src newfile.cpp\n"
                   "  jenga file --src assets/ --type resource\n"
                   "  jenga file --link opengl32\n"
                   "  jenga file --def MY_MACRO=1"
        )
        parser.add_argument("project", nargs="?", help="Project name (default: first non-internal project)")
        parser.add_argument("--src", nargs="+", help="Source files or patterns to add")
        parser.add_argument("--inc", nargs="+", help="Include directories")
        parser.add_argument("--link", nargs="+", help="Libraries to link")
        parser.add_argument("--def", dest="defines", nargs="+", help="Preprocessor defines")
        parser.add_argument("--type", choices=['source', 'header', 'resource'], default='source',
                            help="Type of files when using --src (default: source)")
        parser.add_argument("--interactive", "-i", action="store_true", help="Interactive mode")
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

        loader = Loader()
        cache = Cache(entry_file.parent, workspaceName=entry_file.stem)
        workspace = cache.LoadWorkspace(entry_file, loader)
        if workspace is None:
            workspace = loader.LoadWorkspace(str(entry_file))
            if workspace is None:
                Colored.PrintError("Failed to load workspace.")
                return 1

        # Déterminer le projet cible
        project_name = parsed.project
        if not project_name:
            # Projet courant : startProject ou premier projet non interne
            project_name = workspace.startProject
            if not project_name:
                for p in workspace.projects:
                    if not p.startswith('__'):
                        project_name = p
                        break
        if not project_name or project_name not in workspace.projects:
            Colored.PrintError(f"Project '{project_name}' not found.")
            return 1

        project = workspace.projects[project_name]

        # Mode interactif
        if parsed.interactive or not (parsed.src or parsed.inc or parsed.link or parsed.defines):
            return AddCommand._RunInteractive(project, entry_file, workspace)
        else:
            return AddCommand._RunDirect(project, entry_file, workspace, parsed)

    @staticmethod
    def _RunDirect(project, entry_file: Path, workspace, args) -> int:
        """Ajout direct avec modification du fichier .jenga."""
        modifications = []
        lines_to_add = []

        # Ajouter des fichiers
        if args.src:
            patterns = AddCommand._NormalizePatterns(args.src, args.type)
            for p in patterns:
                line = f'files(["{p}"])'
                lines_to_add.append(line)
            modifications.append(f"added {len(patterns)} file patterns")

        # Ajouter des include directories
        if args.inc:
            for inc in args.inc:
                line = f'includedirs(["{inc}"])'
                lines_to_add.append(line)
            modifications.append(f"added {len(args.inc)} include directories")

        # Ajouter des librairies
        if args.link:
            for lib in args.link:
                line = f'links(["{lib}"])'
                lines_to_add.append(line)
            modifications.append(f"added {len(args.link)} libraries")

        # Ajouter des defines
        if args.defines:
            for define in args.defines:
                line = f'defines(["{define}"])'
                lines_to_add.append(line)
            modifications.append(f"added {len(args.defines)} defines")

        if not lines_to_add:
            Colored.PrintWarning("No changes specified.")
            return 0

        # Modifier le fichier .jenga
        success = AddCommand._AppendToProjectBlock(
            AddCommand._ProjectFile(project, entry_file), project.name, lines_to_add)
        if not success:
            Colored.PrintError("Failed to update .jenga file.")
            return 1

        # Mettre à jour l'objet workspace en mémoire
        if args.src:
            project.files.extend(AddCommand._NormalizePatterns(args.src, args.type))
        if args.inc:
            project.includeDirs.extend(args.inc)
        if args.link:
            project.links.extend(args.link)
        if args.defines:
            project.defines.extend(args.defines)

        # Invalider le cache
        cache = Cache(entry_file.parent, workspaceName=entry_file.stem)
        cache.Invalidate()

        Colored.PrintSuccess(f"Project '{project.name}' updated.")
        for mod in modifications:
            Colored.PrintInfo(f"  ✓ {mod}")
        return 0

    @staticmethod
    def _DeclRegex(project_name: str):
        return re.compile(
            rf'^(?P<indent>[ \t]*)with\s+project\s*\(\s*["\']{re.escape(project_name)}["\']\s*\)\s*:\s*$'
        )

    @staticmethod
    def _ProjectFile(project, entry_file: Path) -> Path:
        """(2.11.0) Le fichier .jenga qui DECLARE le projet.

        Un projet range dans son propre fichier (`jenga project X --separate`, inclus par
        `with include(...)`) n'a pas son bloc dans le fichier du workspace : 2.10.3 n'y cherchait
        que la, d'ou « Project block for 'X' not found ». Le chargeur note ce fichier dans
        `_externalFile` ; on le prend s'il contient bien le bloc, sinon le fichier du workspace."""
        decl_re = AddCommand._DeclRegex(project.name)
        candidats = []
        externe = getattr(project, "_externalFile", "") or ""
        if externe:
            candidats.append(Path(externe))
        candidats.append(Path(entry_file))
        for f in candidats:
            try:
                if f.is_file() and any(decl_re.match(l) for l in FileSystem.ReadFile(f).splitlines()):
                    return f
            except Exception:
                continue
        return Path(entry_file)

    @staticmethod
    def _AppendToProjectBlock(entry_file: Path, project_name: str, lines: List[str]) -> bool:
        """
        Ajoute des lignes à l'intérieur du bloc `with project("{project_name}"):`.
        Gère l'indentation automatique. `entry_file` est le fichier qui declare le projet
        (voir _ProjectFile), pas forcement celui du workspace.
        """
        content = FileSystem.ReadFile(entry_file)
        eol = "\r\n" if "\r\n" in content else "\n"
        lines_raw = content.splitlines(keepends=True)

        decl_re = AddCommand._DeclRegex(project_name)

        start_idx = -1
        decl_indent = ""
        for idx, raw in enumerate(lines_raw):
            logical = raw.rstrip("\r\n")
            m = decl_re.match(logical)
            if m:
                start_idx = idx
                decl_indent = m.group("indent")
                break

        if start_idx < 0:
            Colored.PrintError(f"Project block for '{project_name}' not found in {entry_file}.")
            return False

        decl_indent_len = len(decl_indent)
        block_indent = None
        end_idx = len(lines_raw)

        for idx in range(start_idx + 1, len(lines_raw)):
            logical = lines_raw[idx].rstrip("\r\n")
            stripped = logical.strip()
            if not stripped:
                continue

            current_indent_len = len(logical) - len(logical.lstrip(" \t"))
            if current_indent_len <= decl_indent_len:
                end_idx = idx
                break

            if block_indent is None:
                block_indent = logical[:current_indent_len]

        if block_indent is None:
            block_indent = decl_indent + "    "

        inserted = [f"{block_indent}{line}{eol}" for line in lines]
        new_lines = lines_raw[:end_idx] + inserted + lines_raw[end_idx:]
        FileSystem.WriteFile(entry_file, "".join(new_lines))
        return True

    @staticmethod
    def _RunInteractive(project, entry_file: Path, workspace) -> int:
        """Mode interactif pour ajouter des fichiers/dépendances."""
        Display.Section(f"Add files to project '{project.name}'")

        print("What would you like to add?")
        print("  1) Source files")
        print("  2) Include directories")
        print("  3) Libraries")
        print("  4) Preprocessor defines")
        print("  0) Done")

        lines_to_add = []
        while True:
            choice = Display.Prompt("Choice", default="0")
            if choice == "0":
                break
            elif choice == "1":
                pattern = Display.Prompt("File pattern (e.g., src/**.cpp, asset/*.png)")
                if pattern:
                    lines_to_add.append(f'files(["{pattern}"])')
                    project.files.append(pattern)
                    Colored.PrintInfo(f"Added: {pattern}")
            elif choice == "2":
                inc = Display.Prompt("Include directory")
                if inc:
                    lines_to_add.append(f'includedirs(["{inc}"])')
                    project.includeDirs.append(inc)
                    Colored.PrintInfo(f"Added include: {inc}")
            elif choice == "3":
                lib = Display.Prompt("Library name (without -l or .lib)")
                if lib:
                    lines_to_add.append(f'links(["{lib}"])')
                    project.links.append(lib)
                    Colored.PrintInfo(f"Added link: {lib}")
            elif choice == "4":
                define = Display.Prompt("Define (e.g., DEBUG=1)")
                if define:
                    lines_to_add.append(f'defines(["{define}"])')
                    project.defines.append(define)
                    Colored.PrintInfo(f"Added define: {define}")
            else:
                Colored.PrintWarning("Invalid choice.")

        if lines_to_add:
            success = AddCommand._AppendToProjectBlock(
                AddCommand._ProjectFile(project, entry_file), project.name, lines_to_add)
            if success:
                cache = Cache(entry_file.parent, workspaceName=entry_file.stem)
                cache.Invalidate()
                Colored.PrintSuccess("Project updated.")
            else:
                Colored.PrintError("Failed to update .jenga file.")
                return 1
        else:
            Colored.PrintInfo("No changes.")
        return 0

    @staticmethod
    def _NormalizePatterns(patterns: List[str], file_type: str) -> List[str]:
        """Normalise les patterns selon le type."""
        result = []
        for p in patterns:
            p = p.replace('\\', '/')
            if file_type == 'source':
                result.append(p)
            elif file_type == 'header':
                if not any(p.endswith(ext) for ext in ['.h', '.hpp', '.hxx', '.inl', '.tpp', '.ipp']):
                    p = p.rstrip('/') + '/**.h'
                result.append(p)
            elif file_type == 'resource':
                # On ajoute à embedResources (mais la commande Add ne gère pas encore embedResources)
                # Pour l'instant, on ajoute simplement comme fichier normal
                result.append(p)
        return result
