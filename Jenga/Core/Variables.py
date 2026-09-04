#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Variables – Moteur d'expansion des variables pour le DSL Jenga.
AUTEUR : TEUGUIA TADJUIDJE Rodolf Séderis — Rihen

Supporte :
  - %{wks.nom} ou %{workspace.nom} : propriétés du workspace courant
  - %{prj.nom} ou %{project.nom}   : propriétés du projet courant
  - %{cfg.nom}                     : propriétés de la configuration de build
  - %{unitest.nom}                : propriétés de la configuration Unitest
  - %{test.nom}                   : propriétés du projet de test courant
  - %{nomProjet.nom}              : propriétés d'un projet quelconque du workspace
  - %{env.NOM}                    : variables d'environnement
  - %{Jenga.Root}                : racine d'installation de Jenga
  - %{Jenga.Version}             : version de Jenga

Les chemins sont automatiquement résolus par rapport au répertoire de base approprié.
L'expansion peut être appliquée récursivement sur des objets entiers.

Toutes les méthodes publiques sont en PascalCase, les méthodes privées en _PascalCase.
Les attributs de classe (constantes) sont en UPPER_SNAKE_CASE.
"""

import os
import re
from pathlib import Path
from typing import Dict, Any, Optional, Union, List, Callable
from functools import lru_cache

from ..Utils import FileSystem  # déjà implémenté
from .._version import __version__

# ✅ Import absolu cohérent avec l'API utilisateur
from Jenga.Core import Api


class VariableExpander:
    """
    Expansion des variables contextuelles. Instance unique par workspace/commande.
    """

    # Pattern pour capturer %{...}
    _VAR_PATTERN = re.compile(r"%\{([^}]+)\}")

    # -----------------------------------------------------------------------
    # Initialisation / configuration
    # -----------------------------------------------------------------------

    def __init__(self,
                 workspace: Optional[Any] = None,
                 project: Optional[Any] = None,
                 config: Optional[Dict[str, str]] = None,
                 unitestConfig: Optional[Any] = None,
                 testProject: Optional[Any] = None,
                 baseDir: Optional[Path] = None,
                 jengaRoot: Optional[Path] = None):
        """
        Crée un expandeur avec un contexte donné.
        Les paramètres peuvent être modifiés plus tard via les setters.
        """
        self._workspace = workspace
        self._project = project
        self._config = config or {}
        self._unitestConfig = unitestConfig
        self._testProject = testProject
        self._baseDir = baseDir or Path.cwd()
        self._jengaRoot = jengaRoot or self._DetectJengaRoot()
        self._toolchain = None   # Toolchain courante

        # Cache interne pour les accès répétés
        self._projectCache: Dict[str, Any] = {}

    # -----------------------------------------------------------------------
    # Private helpers – _PascalCase
    # -----------------------------------------------------------------------

    @staticmethod
    def _DetectJengaRoot() -> Path:
        """Détecte le répertoire racine de l'installation Jenga."""
        # Si on est dans le package installé, __file__ est dans Jenga/Core/
        return Path(__file__).parent.parent.parent.resolve()

    def _GetWorkspaceVariable(self, var: str) -> Optional[str]:
        """Récupère une propriété du workspace."""
        if self._workspace is None:
            return None
        key = var.lower()

        mapping: Dict[str, Union[str, Callable]] = {
            'name': 'name',
            'location': 'location',
            'configurations': lambda w: ','.join(getattr(w, 'configurations', [])),
            'platforms': lambda w: ','.join(getattr(w, 'platforms', [])),
            'startproject': 'startProject',
            'defaulttoolchain': 'defaultToolchain',
            'disableunittestcompilation': 'disableUnitTestCompilation',
            'disableunittestexecution': 'disableUnitTestExecution',
            'unittestcompilationallow': lambda w: ','.join(getattr(w, 'unitTestCompilationAllow', []) or []),
            'unittestexecutionallow': lambda w: ','.join(getattr(w, 'unitTestExecutionAllow', []) or []),
        }
        if key in mapping:
            attr = mapping[key]
            if callable(attr):
                return attr(self._workspace)
            val = getattr(self._workspace, attr, '')
            return str(val) if val is not None else ''
        return None

    def _GetProjectVariable(self, project: Any, var: str) -> Optional[str]:
        """Récupère une propriété d'un projet donné."""
        if project is None:
            return None
        key = var.lower()

        mapping: Dict[str, Union[str, Callable]] = {
            'name': 'name',
            'location': 'location',
            'targetdir': 'targetDir',
            'objdir': 'objDir',
            'targetname': 'targetName',
            'kind': lambda p: p.kind.value if p.kind else '',
            'language': lambda p: p.language.value if p.language else '',
            'cppdialect': 'cppdialect',
            'cdialect': 'cdialect',
            'toolchain': 'toolchain',
            'istest': 'isTest',
        }
        if key in mapping:
            attr = mapping[key]
            if callable(attr):
                return attr(project)
            val = getattr(project, attr, '')
            return str(val) if val is not None else ''
        return None

    def _GetUnitestVariable(self, var: str) -> Optional[str]:
        """Récupère une propriété de la configuration Unitest."""
        if self._unitestConfig is None:
            return None
        key = var.lower()

        mapping = {
            'mode': 'mode',
            'includedir': 'includeDir',
            'include': 'includeDir',
            'libdir': 'libDir',
            'lib': 'libName',
            'libname': 'libName',
            'targetdir': 'targetDir',
            'targetname': 'targetName',
            'objdir': 'objDir',
        }
        if key in mapping:
            val = getattr(self._unitestConfig, mapping[key], '')
            return str(val) if val is not None else ''
        return None

    def _GetTestVariable(self, var: str) -> Optional[str]:
        """Récupère une propriété du projet de test courant."""
        if self._testProject is None:
            return None
        return self._GetProjectVariable(self._testProject, var)

    def _GetNamedProjectVariable(self, projectName: str, var: str) -> Optional[str]:
        """Récupère une propriété d'un projet nommé dans le workspace."""
        if self._workspace is None:
            return None
        # Cache du projet pour éviter les accès répétés
        if projectName not in self._projectCache:
            proj = self._workspace.projects.get(projectName)
            self._projectCache[projectName] = proj
        else:
            proj = self._projectCache[projectName]
        if proj is None:
            return None
        return self._GetProjectVariable(proj, var)

    # -----------------------------------------------------------------------
    # Setters publics
    # -----------------------------------------------------------------------
    def SetToolchain(self, toolchain: Any) -> None:
        """Définit la toolchain courante (pour l'expansion de %{toolchain.*})."""
        self._toolchain = toolchain

    # -----------------------------------------------------------------------
    # Nouvelle méthode privée
    # -----------------------------------------------------------------------
    def _GetToolchainVariable(self, var: str) -> Optional[str]:
        """Récupère une propriété de la toolchain courante."""
        if self._toolchain is None:
            return None
        key = var.lower()

        mapping = {
            'name': 'name',
            'compilerfamily': lambda tc: tc.compilerFamily.value if tc.compilerFamily else '',
            'targetos': lambda tc: tc.targetOs.value if tc.targetOs else '',
            'targetarch': lambda tc: tc.targetArch.value if tc.targetArch else '',
            'targetenv': lambda tc: tc.targetEnv.value if tc.targetEnv else '',
            'targettriple': 'targetTriple',
            'sysroot': 'sysroot',
            'toolchaindir': 'toolchainDir',
            'cc': 'ccPath',
            'cxx': 'cxxPath',
            'ar': 'arPath',
            'ld': 'ldPath',
            'strip': 'stripPath',
            'ranlib': 'ranlibPath',
            'asm': 'asmPath',
        }
        if key in mapping:
            attr = mapping[key]
            if callable(attr):
                return attr(self._toolchain)
            val = getattr(self._toolchain, attr, '')
            return str(val) if val is not None else ''
        return None

    def _GetJengaVariable(self, var: str) -> Optional[str]:
        """Variables internes du système Jenga."""
        key = var.lower()
        package_root = Path(__file__).resolve().parents[1]  # .../Jenga
        unitest_root = package_root / "Unitest"
        if not unitest_root.exists():
            candidate = self._jengaRoot / "Jenga" / "Unitest"
            unitest_root = candidate if candidate.exists() else (self._jengaRoot / "Unitest")

        mapping = {
            'root': str(self._jengaRoot),
            'version': __version__,
            'unitest.source': str(unitest_root),
            'unitest.include': str(unitest_root / 'src'),
            'unitest.lib': str(unitest_root / 'libs' / 'Unitest.lib'),
            'unitest.objdir': str(self._jengaRoot / 'Build' / 'Obj' / 'Unitest'),
            'unitest.targetdir': str(self._jengaRoot / 'Build' / 'Lib'),
            'unitest.automaintemplate': str(unitest_root / 'Entry' / 'Entry.cpp'),
        }
        return mapping.get(key)

    def _GetImplicitVariable(self, var: str) -> Optional[str]:
        """
        Résolution d'une variable non namespacée (%{name}, %{targetdir}, ...).
        Priorité: cfg -> project -> workspace -> env.
        """
        val = self._GetConfigVariable(var)
        if val is not None:
            return val
        val = self._GetProjectVariable(self._project, var)
        if val is not None:
            return val
        val = self._GetWorkspaceVariable(var)
        if val is not None:
            return val
        if var in os.environ:
            return os.environ[var]
        if var.upper() in os.environ:
            return os.environ[var.upper()]
        return None

    def _GetConfigVariable(self, var: str) -> Optional[str]:
        """Récupère une variable de configuration avec aliases et casse tolérante."""
        if self._config is None:
            return None

        key = var.lower()
        aliases = {
            'config': 'buildcfg',
            'configuration': 'buildcfg',
            'system': 'targetos',
            'os': 'targetos',
            'arch': 'targetarch',
            'architecture': 'targetarch',
            'env': 'targetenv',
        }

        candidates = [var, key, var.upper()]
        alias = aliases.get(key)
        if alias:
            candidates.extend([alias, alias.lower(), alias.upper()])

        for candidate in candidates:
            if candidate in self._config:
                value = self._config[candidate]
                return '' if value is None else str(value)

        return None

    def _ExpandString(self, text: str) -> str:
        """Remplace les variables dans une chaîne unique."""
        if not text or '%{' not in text:
            return text

        def replacer(match):
            full_var = match.group(1)
            parts = full_var.split('.')
            if len(parts) < 2:
                implicit = self._GetImplicitVariable(full_var)
                return implicit if implicit is not None else match.group(0)

            namespace_raw = parts[0]
            namespace = namespace_raw.lower()
            variable = '.'.join(parts[1:])

            # 1. Configuration courante
            if namespace == 'cfg' and self._config is not None:
                cfg_val = self._GetConfigVariable(variable)
                return cfg_val if cfg_val is not None else match.group(0)

            # 2. Workspace
            if namespace in ('wks', 'workspace'):
                val = self._GetWorkspaceVariable(variable)
                if val is not None:
                    return val

            # 3. Projet courant
            if namespace in ('prj', 'project'):
                val = self._GetProjectVariable(self._project, variable)
                if val is not None:
                    return val

            # 4. Unitest
            if namespace == 'unitest':
                val = self._GetUnitestVariable(variable)
                if val is not None:
                    return val

            # 5. Test
            if namespace == 'test':
                val = self._GetTestVariable(variable)
                if val is not None:
                    return val

            # 6. Projet nommé
            val = self._GetNamedProjectVariable(namespace_raw, variable)
            if val is None:
                val = self._GetNamedProjectVariable(namespace_raw.lower(), variable)
            if val is not None:
                return val

            # 7. Environnement
            if namespace == 'env' and variable in os.environ:
                return os.environ[variable]

            # 8. Jenga interne
            if namespace == 'jenga':
                val = self._GetJengaVariable(variable)
                if val is not None:
                    return val

            # 9. Toolchain courante  ←  ✅ MAINTENANT À L'INTÉRIEUR
            if namespace == 'toolchain':
                val = self._GetToolchainVariable(variable)
                if val is not None:
                    return val

            # 10. Sinon, on laisse le placeholder intact
            return match.group(0)

        return self._VAR_PATTERN.sub(replacer, text)

    def _ResolvePath(self, value: str, relativeTo: Optional[Path] = None) -> str:
        """
        Résout un chemin : le rend absolu s'il est relatif et ne contient pas de variable.
        Si le chemin contient encore des variables, on le laisse tel quel.
        """
        if not value or '%{' in value:
            return value
        p = Path(value)
        if p.is_absolute():
            return value
        base = relativeTo or self._baseDir
        return str((base / p).resolve())

    # -----------------------------------------------------------------------
    # Public API – PascalCase
    # -----------------------------------------------------------------------

    def SetWorkspace(self, workspace: Any) -> None:
        self._workspace = workspace
        self._projectCache.clear()  # Les projets peuvent avoir changé

    def SetProject(self, project: Any) -> None:
        self._project = project

    def SetConfig(self, config: Dict[str, str]) -> None:
        self._config = config

    def SetUnitestConfig(self, unitestConfig: Any) -> None:
        self._unitestConfig = unitestConfig

    def SetTestProject(self, testProject: Any) -> None:
        self._testProject = testProject

    def SetBaseDir(self, baseDir: Path) -> None:
        self._baseDir = baseDir

    def Expand(self, text: str, recursive: bool = False) -> str:
        """
        Étend les variables dans une chaîne.
        Si recursive = True, applique l'expansion jusqu'à ce qu'il n'y ait plus de changements.
        """
        if not recursive:
            return self._ExpandString(text)

        # Expansion itérative jusqu'à stabilisation
        prev = text
        while True:
            cur = self._ExpandString(prev)
            if cur == prev:
                break
            prev = cur
        return cur

    def ExpandAll(self, obj: Any, recursive: bool = True) -> Any:
        """
        Parcourt récursivement un objet (dataclass, dict, list, str) et étend toutes les chaînes.
        Retourne une copie modifiée ou modifie sur place selon le type.
        Pour les objets complexes, on suppose qu'ils sont mutables.
        """
        import sys
        from types import SimpleNamespace

        if isinstance(obj, str):
            return self.Expand(obj, recursive=recursive)

        if isinstance(obj, list):
            new_list = []
            for item in obj:
                new_list.append(self.ExpandAll(item, recursive))
            return new_list

        if isinstance(obj, tuple):
            return tuple(self.ExpandAll(item, recursive) for item in obj)

        if isinstance(obj, dict):
            new_dict = {}
            for k, v in obj.items():
                new_dict[k] = self.ExpandAll(v, recursive)
            return new_dict

        # Pour les dataclasses ou objets avec __dict__
        if hasattr(obj, '__dict__'):
            for attr, val in obj.__dict__.items():
                if not attr.startswith('_') and isinstance(val, (str, list, dict)):
                    expanded = self.ExpandAll(val, recursive)
                    setattr(obj, attr, expanded)
            return obj

        # Autres types (int, float, bool, None) : inchangé
        return obj

    def ResolvePath(self, path: str, relativeTo: Optional[Path] = None) -> str:
        """
        Applique d'abord l'expansion, puis résout le chemin absolu si possible.
        """
        expanded = self.Expand(path)
        return self._ResolvePath(expanded, relativeTo)

    def ResolvePathList(self, paths: List[str], relativeTo: Optional[Path] = None) -> List[str]:
        """Applique ResolvePath à une liste de chemins."""
        return [self.ResolvePath(p, relativeTo) for p in paths]
