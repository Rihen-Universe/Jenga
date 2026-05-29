#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Create command – Ajoute un nouveau projet ou un nouvel élément (classe, enum, etc.).
Alias : project
Peut créer des projets de différents types (console, static, shared, test).
Peut créer des fichiers avec templates (class, struct, enum, union, custom).
"""

import argparse
import sys
from pathlib import Path
from typing import List, Optional

from ..Utils import Colored, FileSystem, Display
from ..Core.Loader import Loader
from ..Core.Cache import Cache
from ..Core import Api


class CreateCommand:
    """jenga project NAME [--kind KIND] [--lang LANG] [--location DIR] [--interactive]
       jenga project --element CLASS --name MyClass --project MyProject
    """

    PROJECT_KINDS = {
        'console': 'CONSOLE_APP',
        'windowed': 'WINDOWED_APP',
        'static': 'STATIC_LIB',
        'shared': 'SHARED_LIB',
        'test': 'TEST_SUITE',
    }

    ELEMENT_TYPES = {
        'class': '.hpp',
        'struct': '.hpp',
        'enum': '.hpp',
        'union': '.hpp',
        'interface': '.hpp',
        'function': '.cpp',
        'source': '.cpp',
        'header': '.hpp',
        'custom': '.txt'
    }

    @staticmethod
    def Execute(args: List[str]) -> int:
        parser = argparse.ArgumentParser(
            prog="jenga project",
            description="Create a new project or a new code element in an existing project.",
            epilog="Examples:\n"
                   "  jenga project Game --kind console\n"
                   "  jenga project --element class --name Player --project Game\n"
                   "  jenga project --element custom --name config.json --project Game --template json"
        )
        parser.add_argument("name", nargs="?", help="Project name (required for project creation)")
        parser.add_argument("--kind", choices=list(CreateCommand.PROJECT_KINDS.keys()), default="console",
                            help="Project kind (default: console)")
        parser.add_argument("--lang", default="C++", help="Programming language (default: C++)")
        parser.add_argument("--location", default=".", help="Project location relative to workspace (default: .)")
        parser.add_argument("--separate", "--own-file", dest="separate", action="store_true",
                            help="Put the project in its OWN .jenga file (included via include()) instead of inline in the workspace .jenga")
        parser.add_argument("--element", choices=list(CreateCommand.ELEMENT_TYPES.keys()),
                            help="Create a code element instead of a project")
        parser.add_argument("--name", help="Name of the element (class, enum, etc.)")
        parser.add_argument("--project", help="Target project for the element")
        parser.add_argument("--template", help="Template name for custom files")
        parser.add_argument("--interactive", "-i", action="store_true", help="Interactive mode")
        parser.add_argument("--no-interactive", action="store_true", help="Non-interactive mode")
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

        # Si on crée un projet
        if not parsed.element:
            return CreateCommand._CreateProject(parsed, entry_file)
        else:
            return CreateCommand._CreateElement(parsed, entry_file, workspace_root)

    @staticmethod
    def _CreateProject(args, entry_file: Path) -> int:
        """Crée un nouveau projet."""
        # Mode interactif
        interactive = args.interactive or (args.name is None and not args.no_interactive)

        if interactive:
            return CreateCommand._CreateProjectInteractive(args, entry_file)
        else:
            if not args.name:
                Colored.PrintError("Project name required. Use --interactive or provide a name.")
                return 1
            return CreateCommand._CreateProjectDirect(args, entry_file)

    @staticmethod
    def _ResolveProjectRelativeLocation(name: str, location: str) -> str:
        """
        Calcule le chemin relatif (au workspace) ou vivra le projet.

        Regle (demandee par l'utilisateur) : chaque projet est place dans un
        dossier portant SON nom, sous le workspace — ou sous un sous-dossier
        si l'utilisateur le precise via --location.

          location "." (defaut)  -> "<name>"
          location "apps"        -> "apps/<name>"
          location "src/games"   -> "src/games/<name>"

        Si l'utilisateur termine deja --location par le nom du projet (ex.
        "apps/MonApp" pour le projet "MonApp"), on ne duplique pas le segment.
        """
        raw = (location or ".").strip().replace("\\", "/").strip("/")
        if raw in ("", "."):
            return name
        # Eviter "apps/MonApp/MonApp" si l'user a deja inclus le nom.
        if raw == name or raw.endswith("/" + name):
            return raw
        return f"{raw}/{name}"

    @staticmethod
    def _CreateProjectDirect(args, entry_file: Path) -> int:
        """Création directe d'un projet."""
        # Charger le workspace
        loader = Loader()
        cache = Cache(entry_file.parent, workspaceName=entry_file.stem)
        workspace = cache.LoadWorkspace(entry_file, loader)
        if workspace is None:
            workspace = loader.LoadWorkspace(str(entry_file))
            if workspace is None:
                Colored.PrintError("Failed to load workspace.")
                return 1

        if args.name in workspace.projects:
            Colored.PrintError(f"Project '{args.name}' already exists.")
            return 1

        # Déterminer le chemin du projet : un dossier au nom du projet, sous le
        # workspace (ou sous le sous-dossier demande via --location).
        relative_location = CreateCommand._ResolveProjectRelativeLocation(
            args.name, args.location)
        project_dir = Path(workspace.location) / relative_location
        FileSystem.MakeDirectory(project_dir)

        # Ajouter le projet au workspace
        kind_enum = getattr(Api.ProjectKind, CreateCommand.PROJECT_KINDS[args.kind])
        lang_enum = getattr(Api.Language, args.lang.upper().replace('+', 'P').replace('-', ''))

        # Deux modes d'ajout au workspace :
        #   - inline (defaut)  : bloc `with project(...)` ecrit dans le .jenga
        #                        du workspace.
        #   - separate (--separate) : le projet a son PROPRE fichier .jenga dans
        #                        son dossier, rattache au workspace via include().
        dialect = getattr(args, 'dialect', '')
        if getattr(args, 'separate', False):
            CreateCommand._WriteSeparateProjectJenga(
                project_dir, args.name, kind_enum, lang_enum, dialect)
            rel_jenga = f"{relative_location}/{args.name}.jenga"
            CreateCommand._AppendIncludeToWorkspace(entry_file, args.name, rel_jenga)
        else:
            CreateCommand._AppendProjectToJengaFile(
                entry_file, args.name, kind_enum, lang_enum, relative_location, dialect=dialect
            )

        # Créer des fichiers source par défaut
        if args.kind in ('console', 'windowed', 'test'):
            CreateCommand._CreateDefaultSource(project_dir, args.name, args.lang)

        Colored.PrintSuccess(
            f"Project '{args.name}' created in '{relative_location}/'.")
        return 0

    @staticmethod
    def _CreateProjectInteractive(args, entry_file: Path) -> int:
        """Création interactive d'un projet."""
        Display.Section("Create a new project")

        # 1. Project name
        name = Display.Prompt("Project name")
        if not name:
            Colored.PrintError("Project name required.")
            return 1

        # 2. Project type
        kind_choices = list(CreateCommand.PROJECT_KINDS.keys())
        kind = Display.PromptChoice("Project type", choices=kind_choices, default="console")

        # 3. Language
        lang_choices = ["C++", "C"]
        lang = Display.PromptChoice("Language", choices=lang_choices, default="C++")

        # 4. Language standard
        if lang == "C++":
            std_choices = ["C++17", "C++20", "C++23"]
            std = Display.PromptChoice("Language standard", choices=std_choices, default="C++17")
        else:
            std_choices = ["C11", "C17", "C23"]
            std = Display.PromptChoice("Language standard", choices=std_choices, default="C17")

        # 5. Location
        location = Display.Prompt("Location (relative to workspace)", default=".")

        # 5b. Fichier .jenga separe (inclus) ou inline dans le workspace ?
        separate = Display.PromptYesNo(
            "Donner au projet son PROPRE fichier .jenga (inclus via include) ? "
            "(Non = inline dans le .jenga du workspace)", default=False)

        # 6. Namespace
        use_namespace = Display.PromptYesNo("Use a namespace?", default=False)
        namespace = None
        if use_namespace:
            namespace = Display.Prompt("Namespace name", default=name)

        # 7. Create subdirectories
        create_dirs = Display.PromptYesNo("Create source directories (src/ include/)?", default=True)

        # 8. Create initial files
        create_files = Display.PromptYesNo("Create starter files?", default=True)

        # Summary
        Display.Section("Summary")
        print(f"  Project:      {Colored.Colorize(name, bold=True, color='cyan')}")
        print(f"  Type:         {kind}")
        print(f"  Language:     {lang} ({std})")
        print(f"  Location:     {location}")
        print(f"  Jenga file:   {'separate (.jenga inclus)' if separate else 'inline dans le workspace'}")
        if namespace:
            print(f"  Namespace:    {namespace}")
        print(f"  Directories:  {'Yes' if create_dirs else 'No'}")
        print(f"  Starter files:{'Yes' if create_files else 'No'}")

        # Structure preview — le projet vit dans un dossier a son nom.
        relative_location = CreateCommand._ResolveProjectRelativeLocation(name, location)
        project_root = Path(entry_file.parent) / relative_location
        print(f"\n  Structure:")
        print(f"  {relative_location}/")
        if separate:
            print(f"  +-- {name}.jenga   (projet inclus via include)")
        if create_dirs:
            print(f"  +-- src/")
            if create_files:
                ext = ".cpp" if lang == "C++" else ".c"
                print(f"  |   +-- main{ext}")
            print(f"  +-- include/")

        print()
        if not Display.PromptYesNo("Create project?", default=True):
            Colored.PrintInfo("Cancelled.")
            return 0

        parsed = argparse.Namespace(
            name=name,
            kind=kind,
            lang=lang,
            location=location,
            dialect=std,
            separate=separate,
        )
        result = CreateCommand._CreateProjectDirect(parsed, entry_file)
        if result != 0:
            return result

        # Create additional directories if requested
        if create_dirs:
            project_dir = project_root
            FileSystem.MakeDirectory(project_dir / "src")
            FileSystem.MakeDirectory(project_dir / "include")

        # Create starter files with namespace if requested
        if create_files and namespace:
            ext = ".cpp" if lang == "C++" else ".c"
            src_file = project_root / "src" / f"main{ext}"
            if src_file.exists():
                if lang == "C++":
                    content = f'''#include <iostream>

namespace {namespace} {{

int Run() {{
    std::cout << "Hello from {name}!" << std::endl;
    return 0;
}}

}} // namespace {namespace}

int main() {{
    return {namespace}::Run();
}}
'''
                    FileSystem.WriteFile(src_file, content)

        Display.Success(f"Project '{name}' created!")
        return 0

    @staticmethod
    def _CreateElement(args, entry_file: Path, workspace_root: Path) -> int:
        """Crée un élément (classe, enum, etc.) dans un projet existant."""
        if not args.name:
            Colored.PrintError("Element name required with --name.")
            return 1
        if not args.project:
            Colored.PrintError("Target project required with --project.")
            return 1

        # Charger le workspace pour obtenir le chemin du projet
        loader = Loader()
        cache = Cache(workspace_root, workspaceName=entry_file.stem if entry_file else "temp")
        workspace = cache.LoadWorkspace(entry_file, loader) if entry_file else None
        if workspace is None and entry_file:
            workspace = loader.LoadWorkspace(str(entry_file))

        if not workspace or args.project not in workspace.projects:
            Colored.PrintError(f"Project '{args.project}' not found.")
            return 1

        project = workspace.projects[args.project]
        project_location = Path(workspace.location) / project.location if project.location else Path.cwd()

        # Déterminer l'extension et le template
        ext = CreateCommand.ELEMENT_TYPES.get(args.element, '.txt')
        template = args.template or args.element

        # Générer le contenu
        content = CreateCommand._GenerateElementContent(args.element, args.name, template)

        # Déterminer le répertoire de destination
        if args.element in ('class', 'struct', 'enum', 'union', 'interface', 'header'):
            dest_dir = project_location / 'include'
        else:
            dest_dir = project_location / 'src'
        FileSystem.MakeDirectory(dest_dir)

        # Nom du fichier
        filename = f"{args.name}{ext}"
        filepath = dest_dir / filename

        if filepath.exists():
            overwrite = Display.Prompt(f"{filepath} already exists. Overwrite?", default="n")
            if overwrite.lower() not in ('y', 'yes'):
                Colored.PrintInfo("Cancelled.")
                return 0

        FileSystem.WriteFile(filepath, content)
        Colored.PrintSuccess(f"Created {args.element} '{args.name}' at {filepath}")

        # Optionnel : ajouter automatiquement le fichier au projet via AddCommand
        add_args = [
            args.project,
            "--src", str(filepath.relative_to(project_location)),
            "--type", "source" if args.element in ('function', 'source') else "header"
        ]
        from .Add import AddCommand
        AddCommand.Execute(add_args)

        return 0

    @staticmethod
    def _GenerateElementContent(element_type: str, name: str, template: str) -> str:
        """Génère le contenu d'un fichier selon le template."""
        year = __import__('datetime').datetime.now().year

        templates = {
            'class': f'''#ifndef {name.upper()}_HPP
#define {name.upper()}_HPP

/**
 * @file {name}.hpp
 * @brief {name} class definition
 * @author Generated by Jenga
 * @date {year}
 */

class {name} {{
public:
    {name}();
    ~{name}();

private:
}};

#endif // {name.upper()}_HPP
''',
            'struct': f'''#ifndef {name.upper()}_HPP
#define {name.upper()}_HPP

/**
 * @file {name}.hpp
 * @brief {name} struct definition
 * @author Generated by Jenga
 * @date {year}
 */

struct {name} {{
    {name}();
    ~{name}();
}};

#endif // {name.upper()}_HPP
''',
            'enum': f'''#ifndef {name.upper()}_HPP
#define {name.upper()}_HPP

/**
 * @file {name}.hpp
 * @brief {name} enum definition
 * @author Generated by Jenga
 * @date {year}
 */

enum class {name} {{
    Value1,
    Value2,
    Value3
}};

#endif // {name.upper()}_HPP
''',
            'union': f'''#ifndef {name.upper()}_HPP
#define {name.upper()}_HPP

/**
 * @file {name}.hpp
 * @brief {name} union definition
 * @author Generated by Jenga
 * @date {year}
 */

union {name} {{
    int i;
    float f;
    char c;
}};

#endif // {name.upper()}_HPP
''',
            'interface': f'''#ifndef {name.upper()}_HPP
#define {name.upper()}_HPP

/**
 * @file {name}.hpp
 * @brief {name} interface
 * @author Generated by Jenga
 * @date {year}
 */

class {name} {{
public:
    virtual ~{name}() = default;
    virtual void method() = 0;
}};

#endif // {name.upper()}_HPP
''',
            'function': f'''#include "{name}.hpp"

/**
 * @brief {name} function implementation
 */
 // TODO: implement {name}
''',
            'source': f'''/**
 * @file {name}.cpp
 * @brief Source file for {name}
 * @author Generated by Jenga
 * @date {year}
 */

// TODO: add your code here
''',
            'header': f'''#ifndef {name.upper()}_HPP
#define {name.upper()}_HPP

/**
 * @file {name}.hpp
 * @brief Header file for {name}
 * @author Generated by Jenga
 * @date {year}
 */

// TODO: add your declarations here

#endif // {name.upper()}_HPP
'''
        }

        if template in templates:
            return templates[template]
        else:
            # Custom template – simple fichier vide avec commentaire
            return f'''// {name} – Custom file
// Generated by Jenga on {__import__('datetime').datetime.now().strftime('%Y-%m-%d')}
// Template: {template}
'''

    @staticmethod
    def _AppendProjectToJengaFile(entry_file: Path, name: str, kind_enum, lang_enum, location: str,
                                   dialect: str = ""):
        """Ajoute une entrée de projet à la fin du fichier .jenga."""
        kind_to_dsl = {
            Api.ProjectKind.CONSOLE_APP: "consoleapp",
            Api.ProjectKind.WINDOWED_APP: "windowedapp",
            Api.ProjectKind.STATIC_LIB: "staticlib",
            Api.ProjectKind.SHARED_LIB: "sharedlib",
            Api.ProjectKind.TEST_SUITE: "testsuite",
        }
        kind_fn = kind_to_dsl.get(kind_enum, "consoleapp")

        # Determine dialect DSL call (indente a 8 espaces : contenu du projet,
        # lui-meme indente a 4 dans le bloc `with workspace(...)`).
        dialect_line = ""
        if dialect:
            if lang_enum.value in ("C++", "Objective-C++"):
                dialect_line = f'\n        cppdialect("{dialect}")'
            else:
                dialect_line = f'\n        cdialect("{dialect}")'

        # Determine file extensions based on language
        if lang_enum.value in ("C++", "Objective-C++"):
            files_pattern = 'files(["src/**.cpp", "include/**.hpp"])'
        else:
            files_pattern = 'files(["src/**.c", "include/**.h"])'

        # Le bloc projet est INDENTE (4 espaces) pour vivre A L'INTERIEUR du
        # `with workspace(...):`. Pas de shebang/coding (le fichier en a deja
        # un en tete). On ajoute une ligne vide de separation avant le bloc.
        with open(entry_file, 'a', encoding='utf-8') as f:
            f.write(f'''
    # Project: {name}
    with project("{name}"):
        {kind_fn}()
        language("{lang_enum.value}"){dialect_line}
        location("{location}")
        {files_pattern}
''')

    @staticmethod
    def _WriteSeparateProjectJenga(project_dir: Path, name: str, kind_enum, lang_enum,
                                    dialect: str = ""):
        """Ecrit un fichier .jenga DEDIE pour le projet, dans son propre dossier.

        Ce fichier est destine a etre rattache au workspace via `with include()`.
        On utilise location(".") : le mecanisme include resout "." vers le dossier
        du fichier inclus — donc le projet vit dans le dossier de CE .jenga.
        """
        kind_to_dsl = {
            Api.ProjectKind.CONSOLE_APP: "consoleapp",
            Api.ProjectKind.WINDOWED_APP: "windowedapp",
            Api.ProjectKind.STATIC_LIB: "staticlib",
            Api.ProjectKind.SHARED_LIB: "sharedlib",
            Api.ProjectKind.TEST_SUITE: "testsuite",
        }
        kind_fn = kind_to_dsl.get(kind_enum, "consoleapp")

        dialect_line = ""
        if dialect:
            if lang_enum.value in ("C++", "Objective-C++"):
                dialect_line = f'\n    cppdialect("{dialect}")'
            else:
                dialect_line = f'\n    cdialect("{dialect}")'

        if lang_enum.value in ("C++", "Objective-C++"):
            files_pattern = 'files(["src/**.cpp", "include/**.hpp"])'
        else:
            files_pattern = 'files(["src/**.c", "include/**.h"])'

        content = f'''#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# {name} - Jenga Project (inclus dans le workspace via include())

from Jenga import *

with project("{name}"):
    {kind_fn}()
    language("{lang_enum.value}"){dialect_line}
    location(".")
    {files_pattern}
'''
        FileSystem.WriteFile(project_dir / f"{name}.jenga", content)

    @staticmethod
    def _AppendIncludeToWorkspace(entry_file: Path, name: str, rel_jenga: str):
        """Ajoute un `with include(...)` indente DANS le `with workspace(...)`
        pour rattacher le projet (fichier .jenga separe) au workspace."""
        rel = rel_jenga.replace("\\", "/")
        with open(entry_file, 'a', encoding='utf-8') as f:
            f.write(f'''
    # Project: {name} (fichier .jenga separe, inclus)
    with include("{rel}"):
        pass
''')

    @staticmethod
    def _CreateDefaultSource(project_dir: Path, name: str, lang: str):
        """Crée un fichier source minimal."""
        src_dir = project_dir / "src"
        inc_dir = project_dir / "include"
        FileSystem.MakeDirectory(src_dir)
        FileSystem.MakeDirectory(inc_dir)

        if lang.lower() == 'c++':
            content = f'''#include <iostream>

int main() {{
    std::cout << "Hello from {name}!" << std::endl;
    return 0;
}}
'''
            ext = '.cpp'
        elif lang.lower() == 'c':
            content = f'''#include <stdio.h>

int main() {{
    printf("Hello from {name}!\\n");
    return 0;
}}
'''
            ext = '.c'
        else:
            content = f'// {name} project'
            ext = '.txt'

        src_file = src_dir / f"main{ext}"
        FileSystem.WriteFile(src_file, content)
