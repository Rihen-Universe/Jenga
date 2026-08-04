#!/usr/bin/env bash
#
# gitpush.sh — add + commit + push du SEUL superprojet Jenga.
#              (Le sous-module Nkentseu n'est JAMAIS pousse ici : il se gere
#               a part, dans son propre depot Rihen-Universe/Nkentseu.)
#
# Deux declencheurs cote GitHub Actions :
#   - Push de la BRANCHE  -> workflow sync-wiki.yml  -> met a jour le WIKI.
#   - Push d'un TAG vX.Y.Z -> workflow release.yml   -> publie la RELEASE.
#
# ─────────────────────────────────────────────────────────────────────────────
# USAGE
#   ./gitpush.sh <branche> "<message>"
#       Commit + push de la branche.  => le WIKI se met a jour automatiquement.
#
#   ./gitpush.sh <branche> "<message>" --release
#       Idem, PUIS cree le tag v<version> (lu dans Jenga/_version.py) et le
#       pousse.  => la RELEASE GitHub est publiee automatiquement.
#
#   ./gitpush.sh <branche> "<message>" --release v2.0.3
#       Idem mais avec une version de tag explicite.
#
#   Options :
#     -d, --dry-run   Affiche les commandes sans rien executer (test a blanc).
#     -h, --help      Affiche cette aide.
#
# EXEMPLES
#   ./gitpush.sh main "docs: maj wiki reseau"                 # wiki seulement
#   ./gitpush.sh main "release 2.0.2" --release               # wiki + release
#   ./gitpush.sh main "test" --dry-run                        # simulation
# ─────────────────────────────────────────────────────────────────────────────
set -uo pipefail

# ── Couleurs (desactivees hors terminal) ─────────────────────────────────────
if [ -t 1 ]; then
  C_OK=$'\033[1;32m'; C_ERR=$'\033[1;31m'; C_INFO=$'\033[1;36m'
  C_WARN=$'\033[1;33m'; C_DIM=$'\033[2m'; C_RST=$'\033[0m'
else
  C_OK=""; C_ERR=""; C_INFO=""; C_WARN=""; C_DIM=""; C_RST=""
fi
info() { echo "${C_INFO}==>${C_RST} $*"; }
ok()   { echo "${C_OK}[OK]${C_RST} $*"; }
warn() { echo "${C_WARN}[!]${C_RST} $*"; }
die()  { echo "${C_ERR}[ERREUR]${C_RST} $*" >&2; exit 1; }
usage() { sed -n '2,40p' "$0" | sed 's/^# \{0,1\}//'; }

# ── Parsing des arguments ────────────────────────────────────────────────────
DRYRUN=0; RELEASE=0; TAGVER=""
POS=()
while [ $# -gt 0 ]; do
  case "$1" in
    -d|--dry-run) DRYRUN=1 ;;
    -h|--help)    usage; exit 0 ;;
    -r|--release)
      RELEASE=1
      # version optionnelle juste apres --release (si ce n'est pas une option)
      if [ $# -gt 1 ] && [ "${2:0:1}" != "-" ]; then TAGVER="$2"; shift; fi
      ;;
    *) POS+=("$1") ;;
  esac
  shift
done
set -- "${POS[@]:-}"

[ "${1:-}" != "" ] && [ "${2:-}" != "" ] || { usage; echo; die "Il faut : <branche> et un <message>."; }
BRANCH="$1"
MSG="$2"

# ── Chemins (marche depuis n'importe ou) ─────────────────────────────────────
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT" || die "impossible d'aller dans $ROOT"
SUBMODULE_PATH="Jenga/Exemples/Nkentseu"

# ── Helper d'execution (respecte --dry-run) ──────────────────────────────────
run() {
  echo "   ${C_DIM}\$ $*${C_RST}"
  if [ "$DRYRUN" -eq 0 ]; then "$@"; else return 0; fi
}

# ── Lecture de la version depuis la source unique Jenga/_version.py ──────────
read_version() {
  local f="$ROOT/Jenga/_version.py"
  [ -f "$f" ] || return 1
  grep -E '^__version__' "$f" | head -1 \
    | sed -E "s/.*=[[:space:]]*[\"']([^\"']+)[\"'].*/\1/"
}

echo "${C_INFO}════════════════════════════════════════════════════════════${C_RST}"
echo " gitpush (Jenga)  |  branche : ${C_OK}$BRANCH${C_RST}$([ "$DRYRUN" -eq 1 ] && echo "   ${C_WARN}(DRY-RUN)${C_RST}")"
echo "   message : \"$MSG\""
echo "   release : $([ "$RELEASE" -eq 1 ] && echo "OUI" || echo "non")"
echo "${C_INFO}════════════════════════════════════════════════════════════${C_RST}"

# ── 1) Se placer sur la bonne branche ────────────────────────────────────────
CUR="$(git symbolic-ref --short -q HEAD || echo "")"
if [ "$CUR" != "$BRANCH" ]; then
  echo "   branche courante : ${CUR:-<HEAD detache>} -> bascule sur '$BRANCH'"
  run git checkout "$BRANCH" || die "checkout '$BRANCH' impossible (conflits ?)."
fi

# ── 2) Indexer Jenga, mais JAMAIS le pointeur du sous-module Nkentseu ─────────
run git add -A || die "git add a echoue."
if ! git diff --cached --quiet -- "$SUBMODULE_PATH" 2>/dev/null; then
  warn "changement de pointeur Nkentseu detecte -> EXCLU (Nkentseu se pousse a part)."
  run git reset -q -- "$SUBMODULE_PATH"
fi

# ── 3) Committer s'il y a quelque chose d'indexe ─────────────────────────────
if git diff --cached --quiet 2>/dev/null; then
  echo "   ${C_DIM}rien de nouveau a committer${C_RST}"
else
  run git commit -m "$MSG" || die "git commit a echoue."
  ok "commit cree : \"$MSG\""
fi

# ── 4) Pousser la branche (=> WIKI). On ne recurse jamais dans le sous-module ─
run git push --no-recurse-submodules origin "$BRANCH" || die "push de la branche '$BRANCH' echoue."
ok "branche '$BRANCH' poussee -> le wiki se met a jour (si Docs/wiki a change)."

# ── 5) Optionnel : tag de version (=> RELEASE) ───────────────────────────────
if [ "$RELEASE" -eq 1 ]; then
  if [ -z "$TAGVER" ]; then
    TAGVER="$(read_version)" || die "version introuvable dans Jenga/_version.py."
    [ -n "$TAGVER" ] || die "version vide dans Jenga/_version.py."
  fi
  TAG="v${TAGVER#v}"   # garantit un seul 'v' en prefixe
  info "Release : tag $TAG"
  if git rev-parse -q --verify "refs/tags/$TAG" >/dev/null 2>&1; then
    warn "le tag $TAG existe deja en local — non recree."
    warn "Pour une nouvelle release, bumpe __version__ dans Jenga/_version.py."
  else
    run git tag -a "$TAG" -m "Release $TAG" || die "creation du tag $TAG echouee."
    ok "tag $TAG cree."
  fi
  run git push origin "$TAG" || die "push du tag $TAG echoue (deja pousse ? remote en avance ?)."
  ok "tag $TAG pousse -> la release GitHub se construit automatiquement."
fi

echo ""
ok "Termine."
[ "$DRYRUN" -eq 1 ] && warn "DRY-RUN : rien n'a ete reellement modifie."
exit 0
