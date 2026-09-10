#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AppleUniversal.py — binaires universels macOS et iOS (plusieurs architectures
dans un seul fichier Mach-O).

POURQUOI CE FICHIER EXISTE
==========================
Jusqu'ici, `Macos.py` et `Ios.py` choisissaient UNE architecture :

    if self.targetArch == TargetArch.ARM64:   flags += ["-arch", "arm64"]
    elif self.targetArch == TargetArch.X86_64: flags += ["-arch", "x86_64"]

Le binaire produit ne tourne donc que sur la moitié du parc : un Mac Apple
Silicon ou un Mac Intel, jamais les deux. Toutes les applications macOS
distribuées depuis 2020 sont universelles, et une application qui ne l'est pas
se voit immédiatement : sur un Mac Intel elle refuse de se lancer, sur un Mac
Apple Silicon elle passe par Rosetta et perd la moitié de ses images par
seconde.

Android et HarmonyOS avaient déjà leur mécanisme multi-architecture
(`androidabis`, `harmonyabis`). Celui-ci est son équivalent Apple, et il en
reprend délibérément la structure pour qu'on puisse lire les trois côte à côte.

POURQUOI PAS UN SEUL APPEL AVEC PLUSIEURS -arch
================================================
Apple clang accepte `-arch arm64 -arch x86_64` en une seule invocation et
produit directement un binaire gras. C'est ce que fait Xcode, et c'est plus
court que ce fichier.

On ne peut pas s'en servir ici : Jenga génère les dépendances de compilation
par `-MD -MF <fichier>.d`, pour ne recompiler que ce qui a changé. Or clang
refuse de combiner la génération de dépendances avec plusieurs `-arch` :

    error: cannot use '-MF' option with multiple compilations

Il faudrait donc sacrifier la compilation incrémentale, sur la plateforme où
elle est la plus utile. On compile donc une fois par architecture, chacune dans
son propre dossier d'objets, puis on assemble avec `lipo`. C'est exactement ce
que fait le chemin multi-ABI d'Android.

CE QUE `lipo` FAIT, ET CE QU'IL NE FAIT PAS
===========================================
`lipo -create -output final a.bin b.bin` colle plusieurs binaires Mach-O
d'architectures différentes dans un seul fichier. Le système choisit la tranche
au lancement. Cela vaut pour les exécutables, les `.dylib` et les `.a`.

**Cela ne vaut PAS pour combiner iOS appareil et iOS simulateur.** Les deux
sont en `arm64` depuis les Mac Apple Silicon, et `lipo` refuse deux tranches de
même architecture. Apple a créé le format `.xcframework` pour ce cas précis.
Sur iOS, ce fichier sert donc à produire un simulateur universel
(`arm64` + `x86_64`), ce qui couvre les Mac Intel et Apple Silicon du même
studio ; l'appareil reste `arm64` seul, et c'est correct, il n'existe pas
d'iPhone Intel.

ÉTAT
====
Écrit le 10 septembre 2026. **Non exécuté** : la machine de développement est
sous Windows, et `lipo` n'existe que sur macOS. La logique de redirection par
architecture est copiée d'un chemin éprouvé (`_BuildUniversalHAP`), la partie
propre à Apple est à vérifier sur un Mac.
"""

import os
import shutil
from pathlib import Path
from typing import Dict, List, Optional

from Jenga.Core.Api import Project, ProjectKind, TargetArch
from ...Utils import Process, FileSystem, Reporter


# Les seules architectures Apple vivantes. ppc et i386 sont mortes, arm64e est
# réservée aux binaires système d'Apple.
APPLE_ARCH_TO_TARGET = {
    "arm64": TargetArch.ARM64,
    "x86_64": TargetArch.X86_64,
}


def NormaliserArchsApple(archs: List[str]) -> List[str]:
    """Nettoie une liste d'architectures : connues, uniques, dans l'ordre donné.

    On garde l'ordre de l'utilisateur parce que `lipo` le conserve, et que la
    première tranche est celle que certains outils anciens lisent quand ils ne
    savent pas lire un binaire gras.
    """
    vues = []
    for a in archs or []:
        cle = str(a).strip().lower()
        if cle == "x64":
            cle = "x86_64"
        if cle == "aarch64":
            cle = "arm64"
        if cle not in APPLE_ARCH_TO_TARGET:
            Reporter.Warning(f"Architecture Apple inconnue, ignoree : {a}")
            continue
        if cle not in vues:
            vues.append(cle)
    return vues


class AppleUniversalMixin:
    """À mélanger dans MacOSBuilder et IOSBuilder.

    Fournit `BuildUniversalApple(project, archs)`, qui compile le projet une
    fois par architecture puis assemble le résultat avec `lipo`.
    """

    # Redéfini par chaque builder : sert à nommer les dossiers intermédiaires.
    APPLE_OS_TAG = "Apple"

    # -------------------------------------------------------------------------
    def _OnAppleArchChanged(self) -> None:
        """Appelé après chaque changement d'architecture.

        Un builder qui a mis en cache quelque chose de dépendant de
        l'architecture, un triplet cible par exemple, le recalcule ici. Le
        builder macOS n'a rien à faire ; celui d'iOS garde `target_triple`,
        calculé une fois au constructeur, et qui serait périmé sans ce point
        d'accroche. Un triplet périmé ne provoque pas d'erreur : il produit
        simplement des objets de la mauvaise architecture, que `lipo` refusera
        ensuite avec un message qui ne parle pas du triplet.
        """
        return None

    # -------------------------------------------------------------------------
    def _CheminLipo(self) -> Optional[str]:
        """Trouve `lipo`. Il vient des outils en ligne de commande de Xcode."""
        chemin = shutil.which("lipo")
        if chemin:
            return chemin
        # Emplacement quand seuls les Command Line Tools sont installés.
        pour_essai = "/usr/bin/lipo"
        if os.path.exists(pour_essai):
            return pour_essai
        return None

    # -------------------------------------------------------------------------
    def _AssemblerAvecLipo(self, tranches: List[str], sortie: Path) -> bool:
        """`lipo -create` les tranches dans `sortie`."""
        lipo = self._CheminLipo()
        if not lipo:
            Reporter.Error(
                "lipo introuvable. Il fait partie des outils en ligne de commande "
                "de Xcode : `xcode-select --install`."
            )
            return False

        FileSystem.MakeDirectory(sortie.parent)
        args = [lipo, "-create", "-output", str(sortie)] + tranches
        resultat = Process.ExecuteCommand(args, captureOutput=True, silent=False)
        if resultat.returnCode != 0:
            Reporter.Error("lipo -create a echoue.")
            return False

        # On vérifie ce qu'on vient de produire plutôt que de le supposer :
        # `lipo -info` nomme les tranches réellement présentes. Ce contrôle
        # coûte quelques millisecondes et attrape le cas où une tranche a été
        # silencieusement écartée.
        info = Process.ExecuteCommand([lipo, "-info", str(sortie)],
                                      captureOutput=True, silent=True)
        if info.returnCode == 0:
            Reporter.Info("  " + (info.stdout or "").strip())
        return True

    # -------------------------------------------------------------------------
    def BuildUniversalApple(self, project: Project, archs: List[str]) -> bool:
        """Compile `project` une fois par architecture, puis assemble.

        Reprend la redirection par architecture de `_BuildUniversalHAP` : sans
        elle, les objets et les bibliothèques de deux architectures se
        mélangeraient dans les mêmes dossiers, et l'édition de liens prendrait
        silencieusement l'objet de la mauvaise tranche.
        """
        archs = NormaliserArchsApple(archs)
        if len(archs) < 2:
            return False  # l'appelant retombe sur le chemin ordinaire

        Reporter.Info(
            f"Binaire universel {self.APPLE_OS_TAG} pour {project.name} "
            f"({len(archs)} architectures : {', '.join(archs)})"
        )

        # Le cache de workspace ne suit pas les changements d'architecture : on
        # s'appuie sur les horodatages, comme les chemins Android et HarmonyOS.
        cache_origine = getattr(self.workspace, "_cache_status", None)
        self.workspace._cache_status = None
        arch_origine = self.targetArch
        plateforme_origine = self.platform
        temoin = object()

        # Chemin final : celui qu'aurait produit une construction ordinaire.
        sortie_finale = self.GetTargetPath(project)
        tranches: List[str] = []

        try:
            for arch in archs:
                Reporter.Info(f"  -> Compilation pour {arch}...")

                self.targetArch = APPLE_ARCH_TO_TARGET[arch]
                self.platform = f"{self.APPLE_OS_TAG.lower()}-{arch}"
                self._PrepareToolchain()
                self._OnAppleArchChanged()

                etiquette = f"{self.config}-{self.APPLE_OS_TAG}-{arch}"
                filtre = f"platform:{self.platform}"
                a_restaurer: Dict[str, dict] = {}

                for nom_proj, ctx in self.workspace.projects.items():
                    if nom_proj.startswith("__"):
                        continue
                    racine = Path(self.workspace.location) / "Build"
                    if ctx.kind in (ProjectKind.STATIC_LIB, ProjectKind.SHARED_LIB):
                        cible = racine / "Lib" / etiquette / ctx.name
                    elif ctx.kind == ProjectKind.TEST_SUITE:
                        cible = racine / "Tests" / etiquette
                    else:
                        cible = racine / "Bin" / etiquette / ctx.name
                    objets = racine / "Obj" / etiquette / ctx.name

                    a_restaurer[nom_proj] = {
                        "targetDir": ctx.targetDir,
                        "objDir": ctx.objDir,
                        "appliedContext": getattr(ctx, "_jenga_applied_filter_context", None),
                        "filteredTargetDir": ctx._filteredTargetDir.get(filtre, temoin),
                        "filteredObjDir": ctx._filteredObjDir.get(filtre, temoin),
                    }
                    ctx._filteredTargetDir[filtre] = str(cible.resolve())
                    ctx._filteredObjDir[filtre] = str(objets.resolve())
                    ctx._jenga_applied_filter_context = None

                succes = False
                try:
                    # super() de la classe CONCRÈTE : le mixin ne connaît pas
                    # la hiérarchie, c'est le builder qui la lui donne.
                    succes = (self._BuildUneArchitecture(project.name) == 0)
                    if succes:
                        # Collecte AVANT restauration : c'est la seule fenêtre
                        # où GetTargetPath rend le chemin de CETTE architecture.
                        produit = self.GetTargetPath(project)
                        if produit.exists():
                            tranches.append(str(produit))
                        else:
                            Reporter.Error(
                                f"{arch} : construit, mais {produit} est absent"
                            )
                            succes = False
                finally:
                    for nom_proj, sauve in a_restaurer.items():
                        ctx = self.workspace.projects.get(nom_proj)
                        if not ctx:
                            continue
                        if sauve["filteredTargetDir"] is temoin:
                            ctx._filteredTargetDir.pop(filtre, None)
                        else:
                            ctx._filteredTargetDir[filtre] = sauve["filteredTargetDir"]
                        if sauve["filteredObjDir"] is temoin:
                            ctx._filteredObjDir.pop(filtre, None)
                        else:
                            ctx._filteredObjDir[filtre] = sauve["filteredObjDir"]
                        ctx.targetDir = sauve["targetDir"]
                        ctx.objDir = sauve["objDir"]
                        ctx._jenga_applied_filter_context = sauve["appliedContext"]

                if not succes:
                    Reporter.Error(f"Echec de la compilation pour {arch}")
                    return False
                Reporter.Success(f"  {arch} compile")

            if len(tranches) < 2:
                Reporter.Error("Moins de deux tranches : rien a assembler")
                return False

            if not self._AssemblerAvecLipo(tranches, sortie_finale):
                return False

            Reporter.Success(
                f"Binaire universel : {sortie_finale} "
                f"({', '.join(archs)})"
            )
            return True

        finally:
            self.targetArch = arch_origine
            self.platform = plateforme_origine
            self.workspace._cache_status = cache_origine
            self._PrepareToolchain()
            self._OnAppleArchChanged()
