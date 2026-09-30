#!/usr/bin/env bash
# Starts the platform in normal mode: ONE process, http://127.0.0.1:8000.
#
# The backend serves the built UI itself. If the build is
# stale (e.g. after "git pull"), it is rebuilt first.
#
#   bash scripts/start.sh [--no-browser] [--rebuild]
#
# For development with hot reload, use scripts/dev.sh instead.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
URL="http://127.0.0.1:8000"
NO_BROWSER=""; REBUILD=""
for arg in "$@"; do
  case "$arg" in
    --no-browser) NO_BROWSER=1 ;;
    --rebuild) REBUILD=1 ;;
    *) echo "Unknown option: $arg" >&2; exit 2 ;;
  esac
done
# shellcheck source=_common.sh
. "$REPO/scripts/_common.sh"

backend_up() { curl -fsS -m 2 "$URL/api/status" >/dev/null 2>&1; }
open_browser() {
  [ -n "$NO_BROWSER" ] && return
  if command -v open >/dev/null 2>&1; then open "$URL"
  elif command -v xdg-open >/dev/null 2>&1; then xdg-open "$URL" >/dev/null 2>&1 &
  fi
}

[ -d "$REPO/backend/.venv" ] || { echo "Backend not set up. Run scripts/setup.sh first." >&2; exit 1; }

if backend_up; then
  echo "Backend already running -> $URL"
  open_browser
  exit 0
fi

STATE="$(cd "$REPO/backend" && uv run python ../scripts/build_status.py || true)"
if [ -n "$REBUILD" ] || [ "${STATE%% *}" != "fresh" ]; then
  echo "UI: $STATE -> rebuilding ..."
  (cd "$REPO/frontend" && pnpm_cmd install --frozen-lockfile && pnpm_cmd build)
fi

(cd "$REPO/backend" && exec uv run python -m app) &
BACKEND=$!
trap 'kill "$BACKEND" 2>/dev/null || true' EXIT INT TERM

for _ in $(seq 1 100); do
  backend_up && break
  kill -0 "$BACKEND" 2>/dev/null || { echo "Backend exits immediately (port 8000 in use?)." >&2; exit 1; }
  sleep 0.3
done
backend_up || { echo "Backend does not respond within 30 s." >&2; exit 1; }

echo ""
echo "Platform running -> $URL"
echo "FreeCAD: 'SysML-CAD Bridge' workbench, start the bridge. Ctrl+C stops."
open_browser
wait "$BACKEND"
