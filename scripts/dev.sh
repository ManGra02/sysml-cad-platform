#!/usr/bin/env bash
# Starts the backend (and Vite, once the frontend exists) for development.
# You start FreeCAD yourself; the backend connects as soon as the bridge is running.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=_common.sh
. "$REPO/scripts/_common.sh"

pids=()
cleanup() { for pid in "${pids[@]}"; do kill "$pid" 2>/dev/null || true; done; }
trap cleanup EXIT INT TERM

(cd "$REPO/backend" && uv run python -m app --reload --dev) &
pids+=($!)
echo "Backend -> http://127.0.0.1:8000"

if [ -f "$REPO/frontend/package.json" ]; then
  [ -d "$REPO/frontend/node_modules" ] || (cd "$REPO/frontend" && pnpm_cmd install --frozen-lockfile)
  (cd "$REPO/frontend" && pnpm_cmd dev) &
  pids+=($!)
  echo "Vite    -> http://127.0.0.1:5173"
else
  echo "Frontend not created yet -- backend only."
fi

wait
