#!/usr/bin/env bash
#
# gitcommit.sh — Commit PROPRE : identite LeTeguis forcee, AUCUNE mention Claude.
# -----------------------------------------------------------------------------
# L'identite AUTEUR *et* COMMITTER est imposee via `git -c` (independant de la
# config git globale) -> le commit est attribue a LeTeguis, "comme si c'est
# l'utilisateur qui commit". Le message est EXACTEMENT celui passe (jamais de
# trailer Co-Authored-By Claude).
#
# USAGE
#   ./gitcommit.sh "<message>" [chemin1 chemin2 ...]
#     - chemins fournis  -> stage UNIQUEMENT ceux-la (commit cible et propre).
#     - aucun chemin      -> stage les changements des fichiers SUIVIS (git add -u).
#
# EXEMPLES
#   ./gitcommit.sh "feat(api): useconfig" Jenga/Core/Api.py CHANGELOG.md
#   ./gitcommit.sh "docs: maj wiki"
# -----------------------------------------------------------------------------
set -uo pipefail

# Identite imposee (cf. memoire feedback_git_identity_leteguis / no-claude-coauthor).
GIT_NAME="LeTeguis"
GIT_EMAIL="teuguiasederis@gmail.com"

[ "${1:-}" != "" ] || { echo "Usage: $0 \"<message>\" [chemins...]" >&2; exit 1; }
MSG="$1"; shift

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT" || { echo "[gitcommit] cd $ROOT impossible" >&2; exit 1; }

if [ "$#" -gt 0 ]; then
  git add -- "$@" || { echo "[gitcommit] git add a echoue" >&2; exit 1; }
else
  git add -u || { echo "[gitcommit] git add -u a echoue" >&2; exit 1; }
fi


if git diff --cached --quiet; then
  echo "[gitcommit] rien a committer (index vide)."
  exit 0
fi

git -c user.name="$GIT_NAME" -c user.email="$GIT_EMAIL" commit -m "$MSG" \
  || { echo "[gitcommit] git commit a echoue" >&2; exit 1; }

echo "[gitcommit] OK — commit par $GIT_NAME <$GIT_EMAIL> (zero mention Claude)."
git --no-pager log -1 --format='   %h  A:%an <%ae>  C:%cn <%ce>'
