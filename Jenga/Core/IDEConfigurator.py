#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
IDEConfigurator.py
==================
Configuration automatique des editeurs de code pour les projets jenga.

Probleme adresse : les fichiers `*.jenga` sont du Python (au sens runtime),
mais l'IDE ne le sait pas par defaut. Sans configuration :
  - Pas de coloration syntaxique sur les .jenga
  - Pas d'autocomplete sur les fonctions DSL (appicon, project, files, ...)
  - Warnings 'undefined' sur tous les symboles importes via `from Jenga import *`

Ce module configure automatiquement l'IDE de l'utilisateur en :
  1. Associant .jenga -> Python (coloration syntaxique)
  2. Ajoutant le module Jenga aux extraPaths (pyright/pylance resoud les
     symboles)
  3. Desactivant les warnings de wildcard import (faux positifs sur .jenga)

Strategie : MERGE NON-DESTRUCTIF.
  - Si une cle jenga existe deja dans la config user, on la met a jour SANS
    toucher aux autres prefs.
  - Si la config user n'existe pas, on la cree.
  - Idempotent : un marker (fingerprint de la config jenga) evite de
    re-ecrire si la config est deja a jour.

Editeurs supportes en E0 :
  - VSCode/Cursor/Windsurf  : .vscode/settings.json (merge JSONC)
  - LSP universel (Neovim+pyright, Emacs+lsp-mode, Helix, Sublime+LSP,
    Zed, ...) : pyrightconfig.json (commun a tous les clients LSP utilisant
    pyright comme backend Python)

Auto-trigger :
  - IDEConfigurator.AutoConfigure() est appelee silencieusement au debut de
    `jenga build`. Le marker assure qu'on ne re-ecrit pas si rien n'a change.

Auteur : Rihen
"""

from __future__ import annotations
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple
import json
import os
import re
import subprocess
import sys
import hashlib


# Version du schema de config jenga IDE. Bumper si on change les cles ecrites
# (force une regeneration au prochain build).
_CONFIG_SCHEMA_VERSION = "1.0"

# Base de compilation lue par l'extension C/C++ (et clangd), rangee sous Build/
# comme le reste des sorties : jamais suivie par git.
COMPILE_COMMANDS_NAME = "compile_commands.json"


# ─────────────────────────────────────────────────────────────────────────────
# Auto-resolution du chemin Jenga (le user n'a jamais a le hardcoder)
# ─────────────────────────────────────────────────────────────────────────────
def GetJengaHome() -> Optional[str]:
    """
    Retourne le chemin PARENT du package Jenga (= ce qui doit etre dans
    extraPaths pour que `import Jenga` resolve correctement).

    Exemple : si Jenga est installe a `/usr/lib/python3.10/site-packages/Jenga/`,
    retourne `/usr/lib/python3.10/site-packages` (le dossier qui CONTIENT Jenga).
    """
    try:
        import Jenga as _j
        jenga_pkg = Path(_j.__file__).resolve().parent  # .../Jenga/
        return str(jenga_pkg.parent).replace("\\", "/")
    except Exception:
        return None


# ─────────────────────────────────────────────────────────────────────────────
# JSONC support (JSON with Comments) — VSCode autorise // et /* */ dans
# settings.json. On strip les commentaires avant `json.loads` pour eviter
# le crash sur configs existantes. ATTENTION : ce strip simple ne preserve
# pas les commentaires en re-ecriture (on accepte ce trade-off).
#
# Le strip LIT LES CHAINES. L'ancien strip par regex prenait `/*` et `*/`
# a l'interieur des chaines pour un commentaire : dans
# `"**/*.jenga", "**/*.py"` il retirait `/*.jenga", "**/` et laissait
# `"***.py"`. L'union des listes rajoutait alors les bonnes valeurs a chaque
# ecriture : settings.json gagnait une entree `"***.py"` par machine et par
# build (150 dans Nkentseu le 2026-09-29). Meme sort pour `"https://..."`,
# coupe par `//`.
# ─────────────────────────────────────────────────────────────────────────────
_JSONC_TRAILING_COMMA = re.compile(r",(\s*[}\]])")

# Ce que l'ancien strip fabriquait a partir de nos propres motifs. On les
# retire des listes a la lecture : ce ne sont pas des choix de l'utilisateur.
_JSONC_BUG_ARTIFACTS = {"***.py", "***.jenga"}


def _StripJsoncComments(text: str) -> str:
    """Retire les commentaires // et /* */ HORS des chaines JSON."""
    out: List[str] = []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c == '"':
            # Chaine : recopiee telle quelle, echappements compris.
            j = i + 1
            while j < n and text[j] != '"':
                j += 2 if text[j] == "\\" else 1
            out.append(text[i:j + 1])
            i = j + 1
        elif text.startswith("//", i):
            j = text.find("\n", i)
            i = n if j < 0 else j
        elif text.startswith("/*", i):
            j = text.find("*/", i + 2)
            i = n if j < 0 else j + 2
        else:
            out.append(c)
            i += 1
    return "".join(out)


def _ParseJsonc(text: str) -> Any:
    """Parse JSON avec support des commentaires // et /* */ + trailing commas."""
    cleaned = _StripJsoncComments(text)
    cleaned = _JSONC_TRAILING_COMMA.sub(r"\1", cleaned)
    return json.loads(cleaned)


def _PurgeBugArtifacts(data: Any) -> bool:
    """Retire recursivement les `"***.py"` laisses par l'ancien strip ; True si retire."""
    changed = False
    if isinstance(data, dict):
        for v in data.values():
            changed = _PurgeBugArtifacts(v) or changed
    elif isinstance(data, list):
        garde = [x for x in data if not (isinstance(x, str) and x in _JSONC_BUG_ARTIFACTS)]
        if len(garde) != len(data):
            data[:] = garde
            changed = True
        for v in data:
            changed = _PurgeBugArtifacts(v) or changed
    return changed


def _LoadJsonFile(path: Path) -> Optional[Dict[str, Any]]:
    """
    Charge un fichier JSON/JSONC. Retourne dict ou None si le fichier
    n'existe pas / est invalide. Jamais lever : on logue silencieusement.
    """
    if not path.exists():
        return {}
    try:
        raw = path.read_bytes()
    except Exception:
        return None
    # Corruption frequente sur Windows : write interrompu -> fichier rempli de
    # NULs, ou reecriture PowerShell -> UTF-16. On strip les NULs de tete + BOM
    # et on essaie plusieurs encodages. Si vide/illisible -> {} (REGENERER) ;
    # si du vrai JSON invalide (contenu user) -> None (ne pas clobber).
    stripped = raw.lstrip(b"\x00")
    if not stripped.strip():
        return {}
    text: Optional[str] = None
    for enc in ("utf-8-sig", "utf-16", "utf-8"):
        try:
            text = stripped.decode(enc)
            break
        except Exception:
            text = None
    if text is None or not text.strip():
        return {}
    try:
        return _ParseJsonc(text)
    except Exception:
        return None


def _WriteJsonFile(path: Path, data: Dict[str, Any]) -> bool:
    """Ecrit un dict en JSON pretty (indent=4). Cree le parent si besoin."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        # ensure_ascii=False pour preserver les accents francais dans les chaines.
        text = json.dumps(data, indent=4, ensure_ascii=False, sort_keys=False)
        path.write_text(text + "\n", encoding="utf-8")
        return True
    except Exception:
        return False


def _Fingerprint(data: Dict[str, Any]) -> str:
    """Hash stable des cles jenga pour le marker d'idempotence."""
    payload = json.dumps(data, sort_keys=True, ensure_ascii=False)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]


# ─────────────────────────────────────────────────────────────────────────────
# Stubs des symboles de config (useconfig) — coloration + go-to-def cote editeur
# ─────────────────────────────────────────────────────────────────────────────
# Les symboles definis dans les fichiers charges via useconfig("...") (helpers,
# classes, constantes) sont injectes au RUNTIME (propagation) -> l'editeur ne les
# voit pas statiquement. On genere donc un stub `.pyi` qui les DECLARE, ajoute au
# `extraPaths`. L'editeur peut alors les resoudre (un `from jengaconfig import *`
# optionnel donne go-to-def + autocomplete ; sinon la coloration reste).
_STUB_DIR_NAME = ".jenga-typings"
_STUB_MODULE   = "jengaconfig"


def _FindRootJenga(workspace_root: Path) -> Optional[Path]:
    """Le .jenga racine = le 1er (a la racine) qui declare un `with workspace(`."""
    try:
        candidates = sorted(workspace_root.glob("*.jenga"))
    except Exception:
        return None
    for f in candidates:
        try:
            if "with workspace(" in f.read_text(encoding="utf-8-sig"):
                return f
        except Exception:
            continue
    return candidates[0] if candidates else None


def _ExtractUseconfigSymbols(workspace_root: Path) -> Dict[str, str]:
    """
    Charge chaque fichier reference par useconfig("...") dans le .jenga racine et
    retourne {symbole_public: categorie} (func | class | const). Best-effort : ne
    leve jamais (la generation de stub ne doit jamais casser un build).
    """
    # Collecter les fichiers references par useconfig(...) dans N'IMPORTE QUEL
    # .jenga du workspace (racine OU module) : le stub capture ainsi tous les
    # symboles, quel que soit l'endroit ou la config est chargee. Les chemins
    # useconfig sont relatifs a la racine du workspace (cwd au runtime).
    _SKIP = ("Build", "Externals", _STUB_DIR_NAME, ".git", "__pycache__", "node_modules")
    cfg_paths: List[str] = []
    seen: set = set()
    try:
        jenga_files = workspace_root.rglob("*.jenga")
    except Exception:
        return {}
    for jf in jenga_files:
        if any(part in _SKIP for part in jf.parts):
            continue
        try:
            text = jf.read_text(encoding="utf-8-sig")
        except Exception:
            continue
        if "useconfig" not in text:
            continue
        for call in re.findall(r"useconfig\(([^)]*)\)", text):
            for m in re.findall(r"[\"']([^\"']+)[\"']", call):
                if m not in seen:
                    seen.add(m)
                    cfg_paths.append(m)
    if not cfg_paths:
        return {}
    import types as _types
    try:
        import Jenga.Core.Api as _Api
        import Jenga as _J
    except Exception:
        return {}
    # Exclure tout ce qui vient de Jenga (API + GlobalToolchains + sous-packages),
    # importe dans les configs via `from Jenga import *` : ce n'est PAS un symbole
    # de config, c'est deja resolu par l'editeur via le package Jenga.
    api_names = {n for n in dir(_Api) if not n.startswith("_")}  # injectes dans l'exec
    excluded = set(api_names)                                    # + filtre de sortie
    excluded |= set(getattr(_J, "__all__", []))
    excluded |= {n for n in dir(_J) if not n.startswith("_")}
    out: Dict[str, str] = {}
    for rel in cfg_paths:
        cfg = workspace_root / rel
        if not cfg.is_file():
            continue
        g: Dict[str, Any] = {
            "__file__": str(cfg), "__name__": "__jengaconfig__",
            "__builtins__": __builtins__, "Path": Path,
        }
        for n in api_names:
            try:
                g[n] = getattr(_Api, n)
            except Exception:
                pass
        try:
            cfgText = cfg.read_text(encoding="utf-8-sig")
            # Retire les `from jengaconfig import ...` : ce module-stub n'est pas
            # importable au moment de la generation (c'est justement ce qu'on cree
            # -> chicken-egg). Les symboles viennent de l'exec direct du fichier.
            cfgText = re.sub(r"(?m)^[ \t]*from[ \t]+jengaconfig[ \t]+import.*$", "", cfgText)
            exec(compile(cfgText, str(cfg), "exec"), g)
        except Exception:
            continue
        for name, val in list(g.items()):
            if name.startswith("_") or name in excluded or name == "Path":
                continue
            if name in out or isinstance(val, _types.ModuleType):
                continue
            if isinstance(val, type):
                out[name] = "class"
            elif callable(val):
                out[name] = "func"
            else:
                out[name] = "const"
    return out


def _RenderConfigStub(symbols: Dict[str, str]) -> str:
    lines = [
        "# =============================================================================",
        "# jengaconfig.pyi — STUB GENERE par Jenga (au build / `jenga ide`). NE PAS EDITER.",
        "# Declare les symboles des fichiers de config charges via useconfig(), pour que",
        "# l'editeur (Pyright/Pylance) les COLORE et donne go-to-def / autocomplete.",
        "# =============================================================================",
        "from typing import Any",
        "",
    ]
    for name in sorted(symbols):
        cat = symbols[name]
        if cat == "func":
            lines.append(f"def {name}(*args: Any, **kwargs: Any) -> Any: ...")
        elif cat == "class":
            lines.append(f"class {name}:")
            lines.append("    def __init__(self, *args: Any, **kwargs: Any) -> None: ...")
            lines.append("    def __getattr__(self, name: str) -> Any: ...")
        else:
            lines.append(f"{name}: Any")
    return "\n".join(lines) + "\n"


def GenerateConfigStubs(workspace_root: Path, verbose: bool = False) -> bool:
    """
    Genere <workspace>/.jenga-typings/jengaconfig.pyi a partir des symboles des
    fichiers useconfig(). Retourne True si ecrit/mis a jour. Best-effort.
    """
    workspace_root = Path(workspace_root)
    symbols = _ExtractUseconfigSymbols(workspace_root)
    if not symbols:
        return False
    content = _RenderConfigStub(symbols)
    stub_dir  = workspace_root / _STUB_DIR_NAME
    stub_path = stub_dir / f"{_STUB_MODULE}.pyi"
    # Module no-op runtime : `from jengaconfig import *` doit etre importable au
    # runtime SANS rien faire (les vrais symboles viennent de la propagation
    # useconfig). Le Loader ajoute .jenga-typings au sys.path -> l'import marche
    # et reste cosmetique (purement pour l'editeur, via le .pyi).
    noop_path = stub_dir / f"{_STUB_MODULE}.py"
    noop_body = (
        "# Module no-op genere par Jenga. `from jengaconfig import *` est resolu\n"
        "# par jengaconfig.pyi cote editeur ; au runtime les symboles viennent de\n"
        "# la propagation useconfig(). Ne rien mettre ici.\n"
    )
    try:
        if stub_path.exists() and stub_path.read_text(encoding="utf-8") == content \
           and noop_path.exists():
            return False
        stub_dir.mkdir(parents=True, exist_ok=True)
        stub_path.write_text(content, encoding="utf-8")
        if not noop_path.exists() or noop_path.read_text(encoding="utf-8") != noop_body:
            noop_path.write_text(noop_body, encoding="utf-8")
        if verbose:
            print(f"[ide-setup] stub config : {stub_path} ({len(symbols)} symboles)")
        return True
    except Exception:
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Editeur : VSCode (et compatibles Cursor / Windsurf qui lisent .vscode/)
# ─────────────────────────────────────────────────────────────────────────────
def _GetVSCodeJengaConfig(jenga_home: Optional[str]) -> Dict[str, Any]:
    """
    Construit le dict des cles jenga a injecter dans .vscode/settings.json.
    Ce dict represente UNIQUEMENT les cles que jenga gere — le reste de la
    config user est preserve.
    """
    cfg: Dict[str, Any] = {
        # 1. Association *.jenga -> Python (coloration syntaxique)
        "files.associations": {
            "*.jenga": "python",
        },
        # 2. Analyser les .jenga avec pylance/pyright
        "python.analysis.include": ["**/*.jenga", "**/*.py"],
        # 3. Tolerer les wildcard imports (faux positifs sur .jenga)
        "python.analysis.diagnosticSeverityOverrides": {
            "reportWildcardImportFromLibrary": "none",
            "reportMissingImports": "warning",
            "reportUndefinedVariable": "warning",
        },
        # 5. C/C++ (ms-vscode.cpptools) : les VRAIES commandes du build, tenues
        #    a jour par RefreshCompileCommands au debut de `jenga build`. Sans
        #    elles l'extension ne resout aucun `#include "NKCore/..."` : ni
        #    Ctrl+clic sur le chemin, ni aller a la definition.
        "C_Cpp.default.compileCommands": "${workspaceFolder}/Build/" + COMPILE_COMMANDS_NAME,
    }
    # 4. extraPaths : Jenga (resolution de l'API) + dossier de stubs des symboles
    #    charges via useconfig() (.jenga-typings).
    extra: List[str] = []
    if jenga_home:
        extra.append(jenga_home)
    extra.append(_STUB_DIR_NAME)
    cfg["python.analysis.extraPaths"] = extra
    return cfg


def _MergeVSCodeSettings(
    existing: Dict[str, Any], jenga_cfg: Dict[str, Any]
) -> Tuple[Dict[str, Any], bool]:
    """
    Fusionne `jenga_cfg` dans `existing` de maniere non-destructive.
    Pour chaque cle :
      - Si la cle n'existe pas dans existing, on l'ajoute.
      - Si elle existe mais avec une valeur dict : merge recursif (liste = union).
      - Si elle existe mais avec une autre forme : on remplace par la valeur jenga.

    Retourne (dict fusionne, changed bool).
    """
    changed = False
    result = dict(existing)  # copy shallow

    for key, jenga_value in jenga_cfg.items():
        if key not in result:
            result[key] = jenga_value
            changed = True
            continue
        existing_value = result[key]
        # Cas 1 : tous les deux sont dict -> merge profond
        if isinstance(existing_value, dict) and isinstance(jenga_value, dict):
            merged_sub, sub_changed = _MergeVSCodeSettings(existing_value, jenga_value)
            if sub_changed:
                result[key] = merged_sub
                changed = True
        # Cas 2 : tous les deux sont list -> union (preserve l'ordre user d'abord)
        elif isinstance(existing_value, list) and isinstance(jenga_value, list):
            for item in jenga_value:
                if item not in existing_value:
                    existing_value.append(item)
                    changed = True
        # Cas 3 : types incompatibles ou autres -> remplacement (jenga gagne)
        else:
            if existing_value != jenga_value:
                result[key] = jenga_value
                changed = True
    return result, changed


def ConfigureVSCode(workspace_root: Path, force: bool = False,
                    verbose: bool = False) -> bool:
    """
    Genere/maj .vscode/settings.json dans workspace_root.

    Marker d'idempotence : on stocke le fingerprint de la config jenga dans
    une cle privee `_jengaIdeConfigVersion` du settings.json. Si le marker
    est present avec le bon hash, on skip (sauf force=True).

    Retourne True si une maj a ete ecrite, False sinon.
    """
    settings_path = workspace_root / ".vscode" / "settings.json"

    jenga_home = GetJengaHome()
    jenga_cfg  = _GetVSCodeJengaConfig(jenga_home)
    fp_target  = _Fingerprint({"v": _CONFIG_SCHEMA_VERSION, "cfg": jenga_cfg})

    existing = _LoadJsonFile(settings_path)
    if existing is None:
        # Fichier present mais invalide JSON : on ne touche pas (eviter de
        # casser une config user).
        if verbose:
            print(f"[ide-setup] {settings_path} invalide, skip.")
        return False

    # Les `"***.py"` de l'ancien strip passent AVANT le marker : un fichier a
    # jour selon le marker peut encore en contenir.
    purged = _PurgeBugArtifacts(existing)

    # Marker check : si deja a jour, skip.
    marker_key = "_jengaIdeConfigVersion"
    if not force and not purged and existing.get(marker_key) == fp_target:
        return False

    # Merge non-destructif des cles jenga.
    merged, changed = _MergeVSCodeSettings(existing, jenga_cfg)
    if not changed and not purged and existing.get(marker_key) == fp_target:
        return False

    merged[marker_key] = fp_target
    if _WriteJsonFile(settings_path, merged):
        if verbose:
            print(f"[ide-setup] VSCode settings.json mis a jour : {settings_path}")
        return True
    return False


# ─────────────────────────────────────────────────────────────────────────────
# Editeur : LSP universel (pyrightconfig.json)
# Couvre : Neovim+pyright via nvim-lspconfig, Emacs+lsp-mode, Helix,
# Sublime+LSP, Zed, et n'importe quel client LSP qui consomme pyright.
# ─────────────────────────────────────────────────────────────────────────────
def _GetPyrightJengaConfig(jenga_home: Optional[str]) -> Dict[str, Any]:
    """Config pyrightconfig.json (universel LSP)."""
    cfg: Dict[str, Any] = {
        "include": ["**/*.py", "**/*.jenga"],
        "exclude": [
            "Build/**",
            "Externals/**",
            ".vscode/**",
            "**/__pycache__",
            "**/node_modules",
        ],
        "pythonVersion": "3.8",
        "reportMissingImports": "warning",
        "reportUndefinedVariable": "warning",
        "reportWildcardImportFromLibrary": "none",
    }
    extra: List[str] = []
    if jenga_home:
        extra.append(jenga_home)
    extra.append(_STUB_DIR_NAME)
    cfg["extraPaths"] = extra
    return cfg


def ConfigurePyrightConfig(workspace_root: Path, force: bool = False,
                           verbose: bool = False) -> bool:
    """
    Genere/maj pyrightconfig.json a la racine du workspace.

    Comme c'est un fichier dedie a pyright, on assume que jenga le possede
    et on l'ecrit en plein (avec un marker integre). Si l'user veut une
    config custom, il peut la mettre dans .vscode/settings.json (qui gagne
    sur pyrightconfig.json pour pylance).
    """
    pyright_path = workspace_root / "pyrightconfig.json"

    jenga_home = GetJengaHome()
    jenga_cfg  = _GetPyrightJengaConfig(jenga_home)
    fp_target  = _Fingerprint({"v": _CONFIG_SCHEMA_VERSION, "cfg": jenga_cfg})

    existing = _LoadJsonFile(pyright_path)
    if existing is None:
        if verbose:
            print(f"[ide-setup] {pyright_path} invalide, skip.")
        return False

    marker_key = "_jengaIdeConfigVersion"
    if not force and existing.get(marker_key) == fp_target:
        return False

    # Merge : on ecrase nos cles jenga mais on preserve toute cle inconnue
    # que l'user aurait ajoutee (rare pour pyrightconfig mais possible).
    merged = dict(existing)
    for k, v in jenga_cfg.items():
        merged[k] = v
    merged[marker_key] = fp_target

    if _WriteJsonFile(pyright_path, merged):
        if verbose:
            print(f"[ide-setup] pyrightconfig.json mis a jour : {pyright_path}")
        return True
    return False


# ─────────────────────────────────────────────────────────────────────────────
# Detection de l'editeur present dans le workspace
# ─────────────────────────────────────────────────────────────────────────────
def DetectEditors(workspace_root: Path) -> List[str]:
    """
    Detecte quels editeurs sont configures dans le workspace.
    Retourne une liste de tags : 'vscode', 'nkcode', 'jetbrains', 'sublime',
    'neovim', 'lsp-generic'.

    ⚠️ ON N'ASSUME PLUS VSCODE QUAND RIEN N'EST DETECTE, et c'est la correction
    de fond de cette fonction (2026-09-02, signalee par Rodolf : « le .vscode ne
    devait etre la que quand on code sur vscode, pas sur nkcode »).

    L'ancienne version finissait par :

        if not any(e in found for e in (...)):
            found.insert(0, "vscode")     # « le plus repandu »

    Trois defauts, et le deuxieme est le pire :

    1. ELLE CREAIT UN DOSSIER QUE PERSONNE N'AVAIT DEMANDE. Un utilisateur de
       NKCode obtenait un `.vscode/settings.json` des la creation du workspace,
       pour un editeur qu'il n'ouvre jamais.
    2. LE DOSSIER CREE ETAIT ENSUITE DETECTE, dix lignes plus haut, par
       `(workspace_root / ".vscode").exists()`. Une SUPPOSITION du premier
       passage devenait un FAIT au second, definitivement. Un defaut qui se
       consolide lui-meme ne se corrige jamais tout seul -- et il devient
       indiscernable d'un choix de l'utilisateur.
    3. Elle ecrivait dans un fichier que l'utilisateur partage avec ses propres
       reglages, donc versionne, qui bougeait a chaque commande.

    CE QUI REMPLACE : on n'ecrit que pour un editeur DONT LA TRACE EXISTE. Sans
    trace, seul `pyrightconfig.json` est produit -- il n'appartient a aucun
    editeur, il sert tous les clients LSP (NKCode compris), et il n'engage rien.

    Un utilisateur de VSCode qui n'a pas encore de `.vscode/` le demande une
    fois : `jenga ide-setup --editor vscode`. Un opt-in explicite vaut mieux
    qu'un dossier apparu tout seul.
    """
    found: List[str] = []
    if (workspace_root / ".vscode").exists():
        found.append("vscode")
    # NKCode marque son espace de travail par un dossier `.nkcode/`. Il consomme
    # pyrightconfig.json comme n'importe quel client LSP : il n'a RIEN a faire
    # d'un `.vscode/`, et c'est tout l'objet de cette detection.
    if (workspace_root / ".nkcode").exists():
        found.append("nkcode")
    if (workspace_root / ".idea").exists() or list(workspace_root.glob("*.iml")):
        found.append("jetbrains")
    if list(workspace_root.glob("*.sublime-project")):
        found.append("sublime")
    if (workspace_root / ".nvim.lua").exists() or \
       (workspace_root / "init.lua").exists():
        found.append("neovim")

    # Toujours generer pyrightconfig.json (universel LSP, ne nuit pas) : c'est
    # le seul fichier que Jenga s'autorise a produire sans marqueur, parce
    # qu'il n'appartient a aucun editeur en particulier.
    if "lsp-generic" not in found:
        found.append("lsp-generic")

    return found


# ─────────────────────────────────────────────────────────────────────────────
# C/C++ : compile_commands.json et c_cpp_properties.json tenus a jour
# ─────────────────────────────────────────────────────────────────────────────
# Dossiers qui ne contiennent ni .jenga ni source du workspace (ou trop gros
# pour etre parcourus a chaque build).
_SCAN_PRUNE = {".git", "Build", "build", "node_modules", "__pycache__", ".jenga",
               ".nkcode", ".vscode", "dist", "cache"}
_SOURCE_EXTS = (".c", ".cc", ".cpp", ".cxx", ".c++", ".m", ".mm")

# Empreinte de la derniere generation, a cote de la base.
_COMPILE_STAMP_NAME = "compile_commands.stamp"

# Nom de la configuration que Jenga possede dans c_cpp_properties.json. Un
# fichier qui en contient une AUTRE appartient a l'utilisateur : on n'y touche pas.
CPP_PROPERTIES_CONFIG = "Jenga"


def _ScanWorkspace(workspace_root: Path) -> Tuple[float, str]:
    """
    Un seul parcours : (mtime du .jenga le plus recent, empreinte de la LISTE
    des sources). Une source ajoutee, supprimee ou renommee change l'empreinte
    sans toucher a aucun .jenga -- c'est ce que la date seule ne voyait pas.
    """
    newest = 0.0
    sources: List[str] = []
    for dirpath, dirnames, filenames in os.walk(workspace_root):
        dirnames[:] = [d for d in dirnames if d not in _SCAN_PRUNE]
        for f in filenames:
            if f.endswith(".jenga"):
                try:
                    newest = max(newest, os.path.getmtime(os.path.join(dirpath, f)))
                except OSError:
                    pass
            elif f.lower().endswith(_SOURCE_EXTS):
                sources.append(os.path.relpath(os.path.join(dirpath, f), workspace_root)
                               .replace("\\", "/"))
    sources.sort()
    return newest, hashlib.sha1("\n".join(sources).encode("utf-8")).hexdigest()[:16]


def _ReadStamp(path: Path) -> str:
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("sources", "")
    except Exception:
        return ""


def _CppPropertiesFromDb(workspace_root: Path, db: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    La configuration « Jenga » de c_cpp_properties.json, tiree de la base.

    compileCommands sert chaque fichier QUI Y EST avec ses vrais drapeaux.
    includePath est le REPLI pour un fichier qui n'y est pas encore (cree
    depuis le dernier build) : l'union des -I du workspace, pour que ses
    #include soient deja resolus -- Ctrl+clic compris -- sans attendre.
    """
    root = str(Path(workspace_root).resolve())
    incs: Dict[str, None] = {}
    compilers: Dict[str, int] = {}
    stds: Dict[str, int] = {}
    for e in db:
        args = e.get("arguments") or []
        if args:
            compilers[args[0]] = compilers.get(args[0], 0) + 1
        it = iter(args[1:])
        for a in it:
            d = None
            if a.startswith("-I") or a.startswith("/I"):
                d = a[2:] or next(it, "")
            elif a == "-isystem":
                d = next(it, "")
            elif a.startswith("-std=") and "++" in a:
                stds[a[5:]] = stds.get(a[5:], 0) + 1
            if not d:
                continue
            d = os.path.normpath(d)
            try:
                rel = os.path.relpath(d, root)
            except ValueError:  # autre lecteur sous Windows
                rel = ".."
            if not rel.startswith(".."):
                d = "${workspaceFolder}/" + rel
            incs[d.replace("\\", "/")] = None
    cfg: Dict[str, Any] = {
        "name": CPP_PROPERTIES_CONFIG,
        "compileCommands": "${workspaceFolder}/Build/" + COMPILE_COMMANDS_NAME,
        "includePath": list(incs),
    }
    if compilers:
        cfg["compilerPath"] = max(compilers, key=compilers.get).replace("\\", "/")
    if stds:
        # cpptools ne connait que les noms « c++NN ».
        cfg["cppStandard"] = max(stds, key=stds.get).replace("gnu++", "c++")
    return cfg


def _WriteCppProperties(workspace_root: Path, db_path: Path, verbose: bool = False) -> bool:
    """Ecrit .vscode/c_cpp_properties.json s'il est a Jenga (ou absent) ; True si ecrit."""
    path = Path(workspace_root) / ".vscode" / "c_cpp_properties.json"
    if not path.parent.is_dir():
        return False
    existing = _LoadJsonFile(path)
    if existing is None:
        return False  # present mais illisible : a l'utilisateur
    configs = existing.get("configurations") or []
    if any(not isinstance(c, dict) or c.get("name") != CPP_PROPERTIES_CONFIG for c in configs):
        return False  # une configuration de l'utilisateur : on n'y touche pas
    try:
        db = json.loads(Path(db_path).read_text(encoding="utf-8"))
    except Exception:
        return False
    data = {"configurations": [_CppPropertiesFromDb(workspace_root, db)], "version": 4}
    if existing == data:
        return False
    if _WriteJsonFile(path, data):
        if verbose:
            print(f"[ide-setup] c_cpp_properties.json mis a jour : {path}")
        return True
    return False


def RefreshCompileCommands(workspace_root: Path, entry_file: Path,
                           verbose: bool = False) -> bool:
    """
    Regenere Build/compile_commands.json s'il manque, si un .jenga est plus
    recent, ou si la LISTE des sources a change (ajout, suppression,
    renommage). Puis tient .vscode/c_cpp_properties.json a jour. Appele au
    debut de `jenga build`, apres AutoConfigure.

    Les commandes sont celles de `jenga gen --compile-commands` (le vrai
    builder, capture). Un sous-processus plutot qu'un appel direct : `gen`
    recharge le workspace et remplace Process.ExecuteCommand le temps de la
    capture, ce qui ne doit pas deborder sur le build qui suit.

    Retourne True si la base a ete (re)ecrite.
    """
    workspace_root = Path(workspace_root)
    if os.environ.get("JENGA_NO_IDE_CONFIG", "").lower() in ("1", "true", "yes"):
        return False
    dest = workspace_root / "Build" / COMPILE_COMMANDS_NAME
    stamp = dest.with_name(_COMPILE_STAMP_NAME)
    # Seulement pour qui s'en sert : VSCode detecte, ou une base deja la
    # (clangd, CLion...). Un espace vierge ne paie pas la generation.
    if not dest.exists() and "vscode" not in DetectEditors(workspace_root):
        return False
    newest_jenga, sources_fp = _ScanWorkspace(workspace_root)
    if (dest.exists() and os.path.getmtime(dest) >= newest_jenga
            and _ReadStamp(stamp) == sources_fp):
        _WriteCppProperties(workspace_root, dest, verbose)  # s'il manque encore
        return False

    print(f"[ide-setup] {COMPILE_COMMANDS_NAME} : regeneration (Build/)...", flush=True)
    cmd = [sys.executable, "-m", "Jenga", "gen", "--compile-commands",
           "-o", str(dest.parent), "--jenga-file", str(entry_file)]
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        r = subprocess.run(cmd, cwd=str(workspace_root), capture_output=True,
                           text=True, errors="replace", timeout=600)
    except Exception as e:  # noqa: BLE001
        print(f"[ide-setup] {COMPILE_COMMANDS_NAME} non regenere : {e}", flush=True)
        return False
    if r.returncode != 0 or not dest.exists():
        # Dit une fois, sans faire echouer le build ; la sortie de `gen` dit pourquoi.
        detail = (r.stderr or r.stdout).strip().splitlines()[-1:] or ["(aucune sortie)"]
        print(f"[ide-setup] {COMPILE_COMMANDS_NAME} non regenere (code {r.returncode}) : "
              f"{detail[0]}", flush=True)
        return False
    _WriteJsonFile(stamp, {"sources": sources_fp})
    _WriteCppProperties(workspace_root, dest, verbose)
    if verbose:
        print(r.stdout.strip())
    return True


# ─────────────────────────────────────────────────────────────────────────────
# API publique
# ─────────────────────────────────────────────────────────────────────────────
def AutoConfigure(workspace_root: Path, force: bool = False,
                  verbose: bool = False) -> List[str]:
    """
    Configure tous les editeurs detectes pour le workspace_root.

    Args:
        workspace_root: dossier racine du workspace (contenant le .jenga).
        force: si True, regenere meme si le marker indique deja-fait.
        verbose: si True, log chaque fichier touche.

    Returns:
        Liste des editeurs effectivement configures (ceux qui ont eu une
        ecriture). Liste vide si tout etait deja a jour.
    """
    workspace_root = Path(workspace_root)
    if not workspace_root.is_dir():
        return []

    # Opt-out par variable d'environnement (CI / users mecontents).
    if os.environ.get("JENGA_NO_IDE_CONFIG", "").lower() in ("1", "true", "yes"):
        return []

    editors = DetectEditors(workspace_root)
    written: List[str] = []

    # Stub des symboles charges via useconfig() (coloration + go-to-def editeur).
    if GenerateConfigStubs(workspace_root, verbose=verbose):
        written.append("config-stubs")

    if "vscode" in editors:
        if ConfigureVSCode(workspace_root, force=force, verbose=verbose):
            written.append("vscode")

    if "lsp-generic" in editors:
        if ConfigurePyrightConfig(workspace_root, force=force, verbose=verbose):
            written.append("lsp-generic")

    # JetBrains / Sublime / Neovim natifs : a venir en E1+.
    return written


def Describe(workspace_root: Path) -> str:
    """Helper : decrit l'etat de la config IDE pour `jenga ide-setup --info`."""
    workspace_root = Path(workspace_root)
    editors = DetectEditors(workspace_root)
    lines = [
        f"Workspace : {workspace_root}",
        f"Editeurs detectes : {', '.join(editors) or '(aucun)'}",
        f"Jenga home : {GetJengaHome() or '(non resolu)'}",
        f"Schema version : {_CONFIG_SCHEMA_VERSION}",
    ]
    return "\n".join(lines)
