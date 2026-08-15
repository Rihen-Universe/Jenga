#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DependencyResolver – Ordonnancement topologique des projets.
Détecte les cycles et fournit l'ordre de build.
Toutes les méthodes publiques sont en PascalCase.
"""

from typing import List, Dict, Set, Tuple, Optional, Any
from collections import deque, defaultdict

# ✅ Import absolu cohérent avec l'API utilisateur
from Jenga.Core import Api


class DependencyResolver:
    """
    Résout les dépendances entre projets d'un workspace.
    Utilise un tri topologique (algorithme de Kahn) sur le graphe des dépendances.
    """

    # ── UNE CIBLE DE TEST EST UNE RACINE, JAMAIS UNE DEPENDANCE ─────────────
    #
    # Trois consequences, et elles sont la raison d'etre des deux methodes qui
    # suivent :
    #   1. rien ne peut dependre d'une cible de test  -> ValidateTestRoots()
    #   2. le parcours n'entre donc jamais dans une cible de test (consequence
    #      GRATUITE de 1 : un noeud dont personne n'est le successeur n'est
    #      atteignable par aucune fermeture d'ancetres) ;
    #   3. le build par defaut ignore les racines de test -> `includeTests`.
    #
    # Le point 2 ne demande aucun code : il decoule de la structure du graphe.
    # Ecrire un verrou pour l'imposer serait du code qui protege d'un evenement
    # impossible. C'est le point 1 qui le garantit, en amont.

    @staticmethod
    def IsTestTarget(project: Any) -> bool:
        """Une cible de test, au sens du graphe de dependances.

        Attention a NE PAS confondre avec `Builder._IsUnitTestProject`, qui
        compte AUSSI `__Unitest__` : celui-ci est la BIBLIOTHEQUE du cadre de
        test, une StaticLib ordinaire dont les racines de test dependent
        legitimement. Le confondre avec une racine ferait echouer la validation
        ci-dessous sur tous les workspaces qui utilisent Unitest.
        """
        if project is None:
            return False
        return bool(getattr(project, "isTest", False)
                    or getattr(project, "kind", None) == Api.ProjectKind.TEST_SUITE)

    @staticmethod
    def ValidateTestRoots(workspace: Any) -> List[str]:
        """Retourne les aretes qui violent « rien ne depend d'une cible de test ».

        Cette propriete etait vraie par accident d'usage — mesure du 15/08 sur
        272 projets : zero violation. Elle n'etait imposee par rien. Un contrat
        que seul l'usage respecte n'est pas un contrat : le jour ou quelqu'un
        ecrit `dependson(["NKLogger_Tests"])`, la suite de tests entre dans la
        fermeture de son application et y reste, invisible.
        """
        fautes: List[str] = []
        for name, proj in workspace.projects.items():
            for dep in getattr(proj, "dependsOn", []) or []:
                cible = workspace.projects.get(dep)
                if DependencyResolver.IsTestTarget(cible):
                    fautes.append(f"'{name}' depends on test target '{dep}'")
        return fautes

    @staticmethod
    def ResolveBuildOrder(workspace: Any,
                          targetProject: Optional[str] = None,
                          includeTests: bool = False) -> List[str]:
        """
        Retourne la liste ordonnée des noms de projets à compiler.
        Si targetProject est spécifié, ne retourne que les dépendances de ce projet.
        Lève une exception en cas de cycle.

        `includeTests` ne concerne QUE le build sans cible : demander
        explicitement une racine de test la construit toujours, sinon
        `jenga test` et `jenga build --target X_Tests` ne pourraient plus rien
        faire.
        """
        # 0. Le contrat, verifie a CHAQUE resolution : c'est le seul endroit par
        #    lequel toutes les commandes passent.
        fautes = DependencyResolver.ValidateTestRoots(workspace)
        if fautes:
            raise ValueError(
                "A test target is a ROOT, never a dependency — nothing may depend on it.\n  "
                + "\n  ".join(fautes)
                + "\nMove the shared code into a library and depend on that library instead."
            )

        # 1. Construire le graphe des dépendances (prédécesseurs)
        pred: Dict[str, Set[str]] = {}
        all_projects = set(workspace.projects.keys())

        # Racines de test hors du build par defaut. Mesure du 15/08 sur
        # Nkentseu : 272 cibles ordonnancees dont 66 tests, soit 24 % de travail
        # qu'on ne demandait pas. Elles ne sont retirees que du build SANS
        # cible ; aucune autre cible ne peut en dependre (contrat ci-dessus),
        # donc les retirer ne casse la fermeture de personne.
        if targetProject is None and not includeTests:
            all_projects = {n for n in all_projects
                            if not DependencyResolver.IsTestTarget(workspace.projects.get(n))}

            # Le cadre de test devenu ORPHELIN part avec elles. `__Unitest__` est
            # la bibliotheque d'Unitest : une fois les racines de test retirees,
            # plus rien ne la lie, et la compiler produit une archive que
            # personne n'ouvrira. La condition « plus aucun dependant » est
            # verifiee et non supposee — un workspace ou quelqu'un en depend
            # directement la garde.
            if "__Unitest__" in all_projects:
                encore_utile = any(
                    "__Unitest__" in (getattr(workspace.projects.get(n), "dependsOn", []) or [])
                    for n in all_projects if n != "__Unitest__"
                )
                if not encore_utile:
                    all_projects.discard("__Unitest__")

        for name, proj in workspace.projects.items():
            if name not in all_projects:
                continue
            deps = set(proj.dependsOn)
            deps = {d for d in deps if d in all_projects}
            pred[name] = deps

        # Si on cible un projet spécifique, on réduit le graphe aux projets concernés
        if targetProject:
            if targetProject not in pred:
                raise ValueError(f"Target project '{targetProject}' not found in workspace")
            # On veut tous les ancêtres (dépendances directes et indirectes)
            visited = set()
            stack = [targetProject]
            while stack:
                node = stack.pop()
                if node in visited:
                    continue
                visited.add(node)
                stack.extend(pred[node])
            # Restreindre le graphe aux nœuds visités
            pred = {k: {d for d in v if d in visited} for k, v in pred.items() if k in visited}

        # 2. Construire le graphe des successeurs
        succ: Dict[str, Set[str]] = {node: set() for node in pred}
        for node, deps in pred.items():
            for dep in deps:
                succ[dep].add(node)

        # 3. Tri topologique (Kahn) en utilisant les prédécesseurs
        #    degré entrant = nombre de prédécesseurs
        in_degree = {node: len(pred[node]) for node in pred}
        queue = deque([node for node in pred if in_degree[node] == 0])
        order = []

        while queue:
            node = queue.popleft()
            order.append(node)
            for neighbor in succ[node]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        if len(order) != len(pred):
            # Détection de cycle
            cycles = DependencyResolver._FindCycles(pred)
            raise RuntimeError(f"Circular dependencies detected: {cycles}")

        return order

    @staticmethod
    def _FindCycles(graph: Dict[str, Set[str]]) -> List[List[str]]:
        """Détecte les cycles dans le graphe des prédécesseurs."""
        cycles = []
        visited = set()
        stack = []

        def dfs(node, path):
            if node in stack:
                idx = stack.index(node)
                cycles.append(stack[idx:] + [node])
                return
            if node in visited:
                return
            visited.add(node)
            stack.append(node)
            for neighbor in graph.get(node, []):
                dfs(neighbor, path)
            stack.pop()

        for node in graph:
            dfs(node, [])
        return cycles

    @staticmethod
    def GetDependencyTree(workspace: Any, rootProject: str) -> Dict[str, List[str]]:
        """
        Retourne un arbre de dépendances (récursif) pour un projet racine.
        """
        result = {}
        visited = set()

        def recurse(name):
            if name in visited:
                return
            visited.add(name)
            proj = workspace.projects.get(name)
            if not proj:
                result[name] = []
                return
            deps = [d for d in proj.dependsOn if d in workspace.projects]
            result[name] = deps
            for d in deps:
                recurse(d)

        recurse(rootProject)
        return result

    @staticmethod
    def ValidateDependencies(workspace: Any) -> List[str]:
        """
        Vérifie que toutes les dépendances existent et qu'il n'y a pas de cycle.
        Retourne une liste d'erreurs (vide si tout est OK).
        """
        errors = []
        all_projects = set(workspace.projects.keys())

        for name, proj in workspace.projects.items():
            for dep in proj.dependsOn:
                if dep not in all_projects:
                    errors.append(f"Project '{name}' depends on unknown project '{dep}'")
                if dep == name:
                    errors.append(f"Project '{name}' depends on itself")

        if not errors:
            try:
                DependencyResolver.ResolveBuildOrder(workspace)
            except RuntimeError as e:
                errors.append(str(e))

        return errors