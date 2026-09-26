#!/usr/bin/env bash
# Startet Backend (und Vite, sobald das Frontend existiert) fuer die Entwicklung.
# FreeCAD startet ihr selbst; das Backend verbindet sich, sobald die Bruecke laeuft.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONNOUSERSITE=1
# Zeigt OPENSSL_CONF auf eine fehlende Datei (z. B. von PostgreSQL), bricht pnpm ab.
if [ -n "${OPENSSL_CONF:-}" ] && [ ! -f "$OPENSSL_CONF" ]; then unset OPENSSL_CONF; fi

pids=()
cleanup() { for pid in "${pids[@]}"; do kill "$pid" 2>/dev/null || true; done; }
trap cleanup EXIT INT TERM

(cd "$REPO/backend" && uv run python -m app --reload --dev) &
pids+=($!)
echo "Backend -> http://127.0.0.1:8000"

if [ -f "$REPO/frontend/package.json" ]; then
  [ -d "$REPO/frontend/node_modules" ] || (cd "$REPO/frontend" && pnpm install)
  (cd "$REPO/frontend" && pnpm dev) &
  pids+=($!)
  echo "Vite    -> http://127.0.0.1:5173"
else
  echo "Frontend noch nicht angelegt -- nur Backend."
fi

wait
