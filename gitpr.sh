#!/usr/bin/env bash
#
# gitpr.sh — Cree (ou met a jour) une Pull Request PROPRE via gh.
# -----------------------------------------------------------------------------
# - La PR est ouverte par le compte gh authentifie (LeTeguis).
# - Le corps de la PR est EXACTEMENT celui fourni : AUCUNE mention Claude / aucun
#   "Generated with Claude Code".
#
# USAGE
#   ./gitpr.sh "<titre>" "<corps>" [base]
#   ./gitpr.sh "<titre>" --body-file <fichier.md> [base]
#     base par defaut : main. La branche HEAD courante est utilisee comme source.
#
# Necessite: gh installe + `gh auth login` (compte avec acces au repo).
# -----------------------------------------------------------------------------
set -uo pipefail

[ "${1:-}" != "" ] || { echo "Usage: $0 \"<titre>\" \"<corps>|--body-file f\" [base]" >&2; exit 1; }
TITLE="$1"; shift

GH="gh"; command -v "$GH" >/dev/null 2>&1 || GH="/c/Program Files/GitHub CLI/gh.exe"

HEAD="$(git symbolic-ref --short -q HEAD)" || { echo "[gitpr] HEAD detache" >&2; exit 1; }

if [ "${1:-}" = "--body-file" ]; then
  BODYFILE="${2:?--body-file requiert un chemin}"; shift 2
  BASE="${1:-main}"
  "$GH" pr create --base "$BASE" --head "$HEAD" --title "$TITLE" --body-file "$BODYFILE"
else
  BODY="${1:-}"; shift || true
  BASE="${1:-main}"
  "$GH" pr create --base "$BASE" --head "$HEAD" --title "$TITLE" --body "$BODY"
fi
