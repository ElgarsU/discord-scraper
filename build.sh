#!/usr/bin/env bash
# Stage discord-scraper source for deployment by the infra repo.
# No compile step — the venv + pip install happen on the VPS (host interpreter).
#
# Output: clean source tree in ./dist/ + ./dist/MANIFEST
# Needs: rsync.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
DIST="$ROOT/dist"
rm -rf "$DIST"; mkdir -p "$DIST"
rsync -a \
  --exclude='.git' --exclude='.venv' --exclude='dist' --exclude='__pycache__' \
  --exclude='.env' --exclude='data' --exclude='.DS_Store' --exclude='.claude' \
  --exclude='.idea' \
  "$ROOT/" "$DIST/"
( cd "$DIST" && find . -type f ! -name MANIFEST | sed 's#^\./##' | sort ) > "$DIST/MANIFEST"
echo "Staged $(wc -l < "$DIST/MANIFEST") files into $DIST"
