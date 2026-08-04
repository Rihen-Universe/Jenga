#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Loader – Chargement des workspaces et projets Jenga.

Responsabilités :
  - Exécuter un fichier .jenga racine et construire l'objet Workspace.
  - Gérer les inclusions (include, batchinclude) via l'API déjà existante.
  - Post-traiter le workspace : expansion des variables, normalisation des chemins.
  - Permettre le rechargement individuel d'un fichier externe pour mise à jour incrémentale.
  - Charger un projet standalone (hors workspace).

Utilise l'API définie dans Jenga.Api et le moteur d'expansion Variables.
"""

import os
import sys
from pathlib import Path
from typing import Optional, Dict, List, Any, Tuple, Callable
import traceback
import importlib.util

# Import de l'API Jenga (définit workspace, project, etc.)
from Jenga.Core import Api
from .Variables import VariableExpander
from .GlobalToolchains import ApplyGlobalRegistryToWorkspace
from ..Utils import Colored, FileSystem


# ── Fichiers .jenga REELLEMENT lus pendant le dernier chargement ────────────
# Un `include()` peut tirer n'importe quel fichier, ou qu'il soit : balayer le
# disque pour les retrouver serait a la fois lent et faux. On les enregistre
# donc a la source, au moment ou ils sont executes. Sert a un hote qui garde un
# workspace en cache (voir Core/Embed.py) a savoir quand le relire.
_loadedFiles: List[Path] = []


def GetLoadedFiles() -> List[Path]:
    """Fichiers lus lors du dernier LoadWorkspace (entree + includes)."""
    return list(_loadedFiles)


class Loader:
    """
    Chargeur de workspaces et projets.
    Instance unique par commande, mais peut être réutilisée.
    """

    def __init__(self, verbose: bool = False):
        self.verbose = verbose
        self._expandCache: Dict[str, VariableExpander] = {}  # expandeur par workspace
        self._currentWorkspace: Optional[Any] = None
        self._currentProject: Optional[Any] = None

    def _ValidateWorkspace(self, workspace: Any) -> bool:
        """
        Vérifie que le workspace est valide : doit avoir au moins un projet non interne.
        Retourne True si valide, False sinon.
        """
        if workspace is None:
            return False
        # Compter les projets qui ne commencent pas par '__'
        non_internal = [p for p in workspace.projects.keys() if not p.startswith('__')]
        if not non_internal:
            self._Log("Workspace has no non-internal projects – treating as invalid.", "warning")
            return False
        return True

    # -----------------------------------------------------------------------
    # Private helpers – _PascalCase
    # -----------------------------------------------------------------------

    def _Log(self, message: str, level: str = "info") -> None:
        """Log conditionnel selon verbose."""
        if not self.verbose and level not in ("error", "warning"):
            return
        if level == "error":
            Colored.PrintError(f"[Loader] {message}")
        elif level == "warning":
            Colored.PrintWarning(f"[Loader] {message}")
        else:
            Colored.PrintInfo(f"[Loader] {message}")

    def _PrepareGlobals(self,
                        filePath: Path,
                        parentWorkspace: Optional[Any] = None,
                        isInclude: bool = False) -> dict:
        """
        Prépare le dictionnaire global pour l'exécution d'un fichier .jenga.
        Réinitialise l'état de l'API et injecte les symboles publics.
        """
        # Réinitialisation propre
        Api.resetstate()

        # Si on est dans un include, on crée un workspace temporaire qui hérite
        if parentWorkspace is not None:
            tempWks = Api.Workspace(name=f"__include_{filePath.stem}__")
            tempWks.location = str(filePath.parent)
            # Héritage des toolchains et unitest
            tempWks.toolchains = dict(parentWorkspace.toolchains)
            tempWks.defaultToolchain = parentWorkspace.defaultToolchain
            tempWks.unitestConfig = parentWorkspace.unitestConfig
            Api._currentWorkspace = tempWks
        else:
            # Fichier racine : le workspace sera créé par l'utilisateur
            Api._currentWorkspace = None

        # Construction du contexte d'exécution
        globals_dict = {
            '__file__': str(filePath),
            '__name__': '__main__' if parentWorkspace is None else '__external__',
            '__builtins__': __builtins__,
            'Path': Path,
        }

        # Injecter tous les symboles publics de l'API
        for name in Api.__all__:
            if not name.startswith('_'):
                globals_dict[name] = getattr(Api, name)

        return globals_dict

    def _CreateExpanderForWorkspace(self, workspace: Any) -> VariableExpander:
        """Crée un expandeur configuré pour un workspace donné."""
        expander = VariableExpander(
            workspace=workspace,
            baseDir=Path(workspace.location) if workspace.location else Path.cwd(),
            jengaRoot=None  # auto-détecté
        )
        if workspace.unitestConfig:
            expander.SetUnitestConfig(workspace.unitestConfig)
        return expander

    def _PostProcessWorkspace(self, workspace: Any, entryFile: Path) -> None:
        """
        Applique les transformations après chargement :
        - Définit les valeurs par défaut (objDir, targetDir)
        - Expansion des variables (sans résolution des chemins relatifs pour les sources)
        - Résolution des chemins de sortie et des toolchains (deviennent absolus)
        """
        if workspace is None:
            return

        # Normalize workspace.location to an absolute path anchored to the
        # entry .jenga directory. This keeps build outputs/cache stable even
        # when Jenga is invoked from different current working directories.
        location_raw = str(getattr(workspace, "location", "") or "").strip()
        if not location_raw or location_raw.startswith('%{'):
            workspace_dir = entryFile.parent.resolve()
        else:
            workspace_dir = Path(location_raw)
            if not workspace_dir.is_absolute():
                workspace_dir = (entryFile.parent / workspace_dir).resolve()
            else:
                workspace_dir = workspace_dir.resolve()
        workspace.location = str(workspace_dir)

        # Inject global Jenga toolchains (shared registry) before expansions.
        ApplyGlobalRegistryToWorkspace(workspace)

        baseDir = workspace_dir
        expander = self._CreateExpanderForWorkspace(workspace)
        self._expandCache[str(entryFile)] = expander

        # ------------------------------------------------------------
        # 1. Valeurs par défaut pour objDir et targetDir (avec variables)
        # ------------------------------------------------------------
        for proj in workspace.projects.values():
            if proj.objDir is None or proj.objDir == "":
                proj.objDir = "%{wks.location}/Build/Obj/%{cfg.buildcfg}-%{cfg.system}/%{prj.name}"
            if proj.targetDir is None or proj.targetDir == "":
                if proj.kind in (Api.ProjectKind.STATIC_LIB, Api.ProjectKind.SHARED_LIB):
                    proj.targetDir = "%{wks.location}/Build/Lib/%{cfg.buildcfg}-%{cfg.system}/%{prj.name}"
                else:
                    proj.targetDir = "%{wks.location}/Build/Bin/%{cfg.buildcfg}-%{cfg.system}/%{prj.name}"

        # ------------------------------------------------------------
        # 2. Expansion des variables dans TOUT le workspace.
        #    Puis second passage projet par projet pour résoudre %{prj.*}
        #    (le passage global n'a pas de projet courant).
        # ------------------------------------------------------------
        expander.ExpandAll(workspace, recursive=True)
        for proj in workspace.projects.values():
            expander.SetProject(proj)
            expander.ExpandAll(proj, recursive=True)

        # ------------------------------------------------------------
        # 3. Résolution des chemins de sortie et des toolchains (doivent être absolus)
        # ------------------------------------------------------------
        for proj in workspace.projects.values():
            # Location du projet (optionnel, peut rester relatif)
            if proj.location and not proj.location.startswith('%{'):
                proj.location = expander.ResolvePath(proj.location, baseDir)
            proj_base = Path(proj.location) if proj.location and not proj.location.startswith('%{') else baseDir

            # Chemins de sortie → absolus
            if proj.objDir:
                proj.objDir = expander.ResolvePath(proj.objDir, baseDir)
            if proj.targetDir:
                proj.targetDir = expander.ResolvePath(proj.targetDir, baseDir)

            # PCH (fichiers spécifiques)
            if proj.pchHeader and not proj.pchHeader.startswith('%{'):
                proj.pchHeader = expander.ResolvePath(proj.pchHeader, proj_base)
            if proj.pchSource and not proj.pchSource.startswith('%{'):
                proj.pchSource = expander.ResolvePath(proj.pchSource, proj_base)

            # Fichiers de test (fichiers spécifiques, pas des patterns)
            if proj.testMainFile and not proj.testMainFile.startswith('%{'):
                proj.testMainFile = expander.ResolvePath(proj.testMainFile, baseDir)
            if proj.testMainTemplate and not proj.testMainTemplate.startswith('%{'):
                proj.testMainTemplate = expander.ResolvePath(proj.testMainTemplate, baseDir)

        # ------------------------------------------------------------
        # 4. Résolution des chemins des toolchains (absolus)
        # ------------------------------------------------------------
        for tc in workspace.toolchains.values():
            if tc.toolchainDir and not tc.toolchainDir.startswith('%{'):
                tc.toolchainDir = expander.ResolvePath(tc.toolchainDir, baseDir)
            if tc.sysroot and not tc.sysroot.startswith('%{'):
                tc.sysroot = expander.ResolvePath(tc.sysroot, baseDir)

        self._Log(f"Workspace '{workspace.name}' post-processed.")

    # -----------------------------------------------------------------------
    # Public API – PascalCase
    # -----------------------------------------------------------------------

    def LoadWorkspace(self, entryFile: str) -> Optional[Any]:
        """
        Charge le workspace à partir du fichier .jenga donné.
        Retourne l'objet Workspace (Api.Workspace) ou None en cas d'erreur.
        """
        filePath = Path(entryFile).resolve()
        if not filePath.exists():
            raise FileNotFoundError(f"Jenga file not found: {filePath}")
        # Nouveau chargement : le registre repart de zero (sinon il accumule les
        # fichiers de tous les chargements precedents du processus).
        _loadedFiles.clear()

        self._Log(f"Loading workspace from {filePath}")

        globals_dict = self._PrepareGlobals(filePath, parentWorkspace=None)

        # Exposer le namespace LIVE du workspace racine pour que `include()` propage
        # automatiquement aux fichiers inclus tout ce que l'utilisateur definit ici
        # (config/fonctions/classes/imports) -> plus besoin de les re-importer dans
        # chaque .jenga inclus. Les includes s'executent inline pendant l'exec
        # ci-dessous, donc ils voient tout ce qui est declare AU-DESSUS d'eux.
        # cf. Api.include._CreateExecContext (lecture de Api._workspaceGlobals).
        Api._workspaceGlobals = globals_dict

        # Changer de répertoire pendant l'exécution (comportement de l'API include)
        old_cwd = Path.cwd()
        os.chdir(filePath.parent)

        # Rendre le module no-op du stub useconfig importable au runtime : permet
        # `from jengaconfig import *` dans les .jenga (purement cosmetique pour
        # l'editeur ; les vrais symboles viennent de la propagation useconfig).
        import sys as _sys
        _typings = str(filePath.parent / ".jenga-typings")
        _typings_added = _typings not in _sys.path
        if _typings_added:
            _sys.path.insert(0, _typings)

        try:
            _loadedFiles.append(filePath)
            exec(filePath.read_text(encoding='utf-8-sig'), globals_dict)
            workspace = Api.getcurrentworkspace()
            if workspace is None:
                raise RuntimeError("No workspace defined in the entry file.")
            self._PostProcessWorkspace(workspace, filePath)
            self._currentWorkspace = workspace
            return workspace
        except Exception as e:
            Colored.PrintError(f"Error loading workspace: {e}")
            if self.verbose:
                traceback.print_exc()
            return None
        finally:
            os.chdir(old_cwd)
            if _typings_added:
                try:
                    _sys.path.remove(_typings)
                except ValueError:
                    pass
            # Evite toute fuite de namespace entre deux chargements de workspace.
            Api._workspaceGlobals = None
            # On ne reset pas l'API ici car on veut garder le workspace chargé
            # Api.resetstate() serait trop brutal; on le fait manuellement ?

    def LoadExternalFile(self,
                         filePath: str,
                         parentWorkspace: Any) -> Tuple[Any, Dict[str, Any]]:
        """
        Charge un fichier .jenga externe (via include) et retourne
        le workspace temporaire ainsi qu'un dictionnaire de métadonnées.
        Utilisé par le cache pour recharger un fichier individuellement.
        """
        fp = Path(filePath).resolve()
        if not fp.exists():
            raise FileNotFoundError(f"External file not found: {fp}")

        self._Log(f"Loading external file: {fp}")

        globals_dict = self._PrepareGlobals(fp, parentWorkspace, isInclude=True)

        old_cwd = Path.cwd()
        os.chdir(fp.parent)

        try:
            _loadedFiles.append(fp)
            exec(fp.read_text(encoding='utf-8-sig'), globals_dict)
            tempWks = Api._currentWorkspace
            if tempWks is None:
                # Si le fichier ne définit pas de workspace, on en crée un factice
                tempWks = Api.Workspace(name=f"__dummy_{fp.stem}__")
                tempWks.location = str(fp.parent)
            # On ne post-process pas ici, ce sera fait lors de la fusion dans le cache
            return tempWks, {
                'path': str(fp),
                'timestamp': fp.stat().st_mtime,
                'projects': list(tempWks.projects.keys()),
                'toolchains': list(tempWks.toolchains.keys()),
            }
        except Exception as e:
            Colored.PrintError(f"Error loading external file {fp}: {e}")
            if self.verbose:
                traceback.print_exc()
            raise
        finally:
            os.chdir(old_cwd)
            # On ne reset pas complètement l'état car on a besoin du résultat
            # Cependant, l'API a modifié _currentWorkspace, _currentProject, etc.
            # On va les réinitialiser manuellement après récupération.
            # Pour l'instant, on garde tel quel, l'appelant devra gérer.

    def LoadProject(self, projectFile: str) -> Optional[Any]:
        """
        Charge un fichier .jenga qui ne contient qu'un seul projet (standalone).
        Retourne l'objet Project ou None.
        """
        filePath = Path(projectFile).resolve()
        if not filePath.exists():
            raise FileNotFoundError(f"Project file not found: {filePath}")

        self._Log(f"Loading standalone project from {filePath}")

        # On crée un workspace temporaire pour accueillir le projet
        Api.resetstate()
        wks = Api.Workspace(name=f"__standalone_{filePath.stem}__")
        wks.location = str(filePath.parent)
        Api._currentWorkspace = wks

        globals_dict = {
            '__file__': str(filePath),
            '__name__': '__project__',
            '__builtins__': __builtins__,
            'Path': Path,
        }
        # Injecter API
        for name in Api.__all__:
            if not name.startswith('_'):
                globals_dict[name] = getattr(Api, name)

        old_cwd = Path.cwd()
        os.chdir(filePath.parent)

        try:
            _loadedFiles.append(filePath)
            exec(filePath.read_text(encoding='utf-8-sig'), globals_dict)
            # Récupérer le projet courant ou le premier du workspace
            proj = Api._currentProject
            if proj is None and wks.projects:
                proj = next(iter(wks.projects.values()))
            if proj is None:
                raise RuntimeError("No project defined in the file.")

            # Expansion
            expander = VariableExpander(workspace=wks, project=proj, baseDir=filePath.parent)
            expander.ExpandAll(proj, recursive=True)
            proj._standalone = True
            return proj
        except Exception as e:
            Colored.PrintError(f"Error loading project: {e}")
            if self.verbose:
                traceback.print_exc()
            return None
        finally:
            os.chdir(old_cwd)
            Api.resetstate()

    def GetExpanderForWorkspace(self, workspace: Any) -> Optional[VariableExpander]:
        """Retourne l'expandeur associé à un workspace (créé si nécessaire)."""
        # On utilise le chemin du workspace.location comme clé
        key = str(Path(workspace.location).resolve()) if workspace.location else "."
        if key not in self._expandCache:
            self._expandCache[key] = self._CreateExpanderForWorkspace(workspace)
        return self._expandCache[key]

    def Reset(self) -> None:
        """Réinitialise le loader (supprime les caches d'expandeur)."""
        self._expandCache.clear()
        self._currentWorkspace = None
        self._currentProject = None
        Api.resetstate()
