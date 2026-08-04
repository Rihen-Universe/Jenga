#!/usr/bin/env bash
# =============================================================================
# cri.sh — Jenga Dev + Distribution Build Script
#
# Mode dev (par défaut) :
#   ./cri.sh          → nettoie, réinstalle en mode éditable, build dist/
#
# Avec tests :
#   ./cri.sh --tests  → identique + lance la suite pytest
# =============================================================================

set -euo pipefail

# --- Forcer UTF-8 ---
export PYTHONUTF8=1
export PYTHONIOENCODING=utf-8
export LANG="${LANG:-en_US.UTF-8}"
export LC_ALL="${LC_ALL:-en_US.UTF-8}"

# --- Aller dans le répertoire du script ---
cd "$(dirname "$(realpath "$0")")"

# =============================================================================
# Couleurs (désactivées si pas de terminal)
# =============================================================================
# Couleurs : uniquement sur un vrai terminal, et jamais si NO_COLOR est defini
# (convention https://no-color.org, respectee par la plupart des outils).
if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then
    C_RESET="\033[0m"
    C_OK="\033[0;32m"
    C_WARN="\033[1;33m"   # jaune vif, aligne sur gitpush.sh
    C_ERR="\033[0;31m"
    C_INFO="\033[0;36m"
else
    C_RESET="" C_OK="" C_WARN="" C_ERR="" C_INFO=""
fi

ok()   { echo -e "${C_OK}[OK]${C_RESET} $*"; }
warn() { echo -e "${C_WARN}[AVERTISSEMENT]${C_RESET} $*"; }
err()  { echo -e "${C_ERR}[ERREUR]${C_RESET} $*" >&2; }
info() { echo -e "${C_INFO}$*${C_RESET}"; }

# =============================================================================
# Arguments
# =============================================================================
RUN_TESTS=0
for arg in "$@"; do
    case "$arg" in
        --tests|-t) RUN_TESTS=1 ;;
        *)
            err "Argument inconnu : $arg"
            echo "Usage: $0 [--tests|-t]"
            exit 1
            ;;
    esac
done

# =============================================================================
# Détection Python
# =============================================================================
PY=""
for candidate in python3 python py; do
    if command -v "$candidate" &>/dev/null; then
        PY="$candidate"
        break
    fi
done

if [ -z "$PY" ]; then
    err "Python introuvable dans le PATH."
    exit 1
fi

# Vérification version minimale (Python >= 3.8)
PY_VER=$("$PY" -c "import sys; print(sys.version_info >= (3,8))" 2>/dev/null || echo "False")
if [ "$PY_VER" != "True" ]; then
    err "Python 3.8+ requis. Version détectée : $("$PY" --version 2>&1)"
    exit 1
fi

echo ""
echo "============================================================"
echo "  Jenga Build Script — Dev + Distribution"
echo "  Python : $("$PY" --version 2>&1)  →  $(command -v "$PY")"
echo "============================================================"
echo ""

# =============================================================================
# Helper : installe un paquet pip uniquement s'il est absent
# Usage  : pip_ensure <nom_paquet>
# =============================================================================
pip_ensure() {
    local pkg="$1"
    if "$PY" -m pip show "$pkg" &>/dev/null; then
        echo "  [pip] $pkg déjà présent, aucune action réseau."
    else
        echo "  [pip] $pkg absent — installation en cours ..."
        if "$PY" -m pip install "$pkg" --quiet; then
            echo "  [pip] $pkg installé avec succès."
        else
            warn "impossible d'installer $pkg."
        fi
    fi
}

# =============================================================================
# [1/6] Nettoyage .pyc et __pycache__
# =============================================================================
info "[1/6] Nettoyage des fichiers .pyc et __pycache__ ..."
find . -type f -name "*.pyc" -delete
find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true

# =============================================================================
# [2/6] Suppression des artefacts de build précédents
# =============================================================================
info "[2/6] Suppression des artefacts de build précédents ..."
rm -rf build dist
find . -maxdepth 1 -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true

# =============================================================================
# [3/6] Désinstallation des anciens paquets Jenga
# =============================================================================
info "[3/6] Désinstallation des anciens paquets Jenga ..."
"$PY" -m pip uninstall Jenga jenga jenga-build-system -y 2>/dev/null || true

# Vérification (et installation si absents) de setuptools et wheel
echo "[3/6] Vérification de setuptools et wheel ..."
pip_ensure setuptools
pip_ensure wheel

# Installation éditable avec --no-build-isolation pour éviter
# de recréer un env isolé et de retélécharger setuptools/wheel
echo "[3/6] Réinstallation en mode développement (editable) ..."
if "$PY" -m pip install -e . --no-build-isolation --quiet; then
    ok "Installation dev terminée."
else
    warn "L'installation en mode éditable a échoué."
    warn "Vous pourrez installer le wheel après le build."
fi

# =============================================================================
# [4/6] Tests (optionnels)
# =============================================================================
if [ "$RUN_TESTS" -eq 1 ]; then
    echo ""
    info "[4/6] Lancement de la suite de tests pytest ..."
    pip_ensure pytest
    if "$PY" -m pytest tests/ -v --tb=short; then
        ok "Tous les tests sont verts."
    else
        warn "Des tests ont échoué — le build de distribution continue."
    fi
else
    info "[4/6] Tests ignorés (utilisez --tests pour les lancer)"
fi

# =============================================================================
# [5/7] Build de la distribution (wheel + sdist) — LEGER (sans Exemples)
# =============================================================================
echo ""
info "[5/7] Build de la distribution utilisateur (wheel + sdist) ..."
pip_ensure build

# Utilise --no-isolation si setuptools est déjà disponible localement,
# ce qui évite tout appel réseau supplémentaire.
if "$PY" -m pip show setuptools &>/dev/null; then
    "$PY" -m build --no-isolation
else
    "$PY" -m build
fi

# Affiche la taille du wheel : il doit etre LEGER (~1 Mo). S'il depasse
# plusieurs dizaines de Mo, c'est que pyproject embarque Exemples par erreur.
WHL=$(ls -t dist/*.whl 2>/dev/null | head -1)
if [ -n "$WHL" ]; then
    WHL_SIZE=$(du -h "$WHL" | cut -f1)
    echo "  → wheel : $(basename "$WHL")  ($WHL_SIZE)"
fi

# =============================================================================
# [6/7] Vérification du package avec twine (avant d'ajouter l'archive exemples)
# =============================================================================
echo ""
info "[6/7] Vérification des artefacts ..."
pip_ensure twine
# Les vieux twine importent pkg_resources, retiré par setuptools récent /
# Python 3.13+. Si twine est cassé, on le met à jour (importlib.metadata).
if ! "$PY" -m twine --version &>/dev/null; then
    warn "twine cassé (pkg_resources manquant) — mise à jour ..."
    "$PY" -m pip install -U twine --quiet || true
fi
# On ne vérifie QUE le package (wheel + sdist), pas l'archive d'exemples.
if "$PY" -m twine check dist/*.whl dist/jenga-[0-9]*.tar.gz; then
    ok "twine check OK."
else
    warn "twine check a signalé des problèmes (non bloquant)."
fi

# =============================================================================
# [7/7] Archive d'exemples allégée (sans build, sans externals, sans Nkentseu)
# =============================================================================
echo ""
info "[7/7] Construction de l'archive d'exemples allégée ..."
if "$PY" scripts/build_examples_archive.py dist; then
    ok "Archive d'exemples générée dans dist/."
else
    warn "Échec de la génération de l'archive d'exemples."
fi

# =============================================================================
# Résumé final
# =============================================================================
echo ""
echo "============================================================"
echo "  ARTEFACTS GÉNÉRÉS POUR DISTRIBUTION :"
echo "============================================================"
ls dist/
echo ""
echo "  Pour installer localement le wheel :"
LATEST_WHL=$(ls -t dist/*.whl 2>/dev/null | head -1)
if [ -n "$LATEST_WHL" ]; then
    echo "    pip install $LATEST_WHL --force-reinstall"
fi
echo ""
echo "  Pour publier le package sur PyPI (wheel + sdist UNIQUEMENT) :"
echo "    python -m twine upload dist/*.whl dist/jenga-[0-9]*.tar.gz"
echo "    (NB: ne pas uploader jenga-examples-*.{zip,tar.gz} sur PyPI —"
echo "         ces archives vont sur la release GitHub.)"
echo ""
echo "============================================================"
ok "TERMINÉ avec succès."
echo "============================================================"
echo ""