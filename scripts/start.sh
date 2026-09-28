#!/usr/bin/env bash
# Startet die Plattform im Normalbetrieb: EIN Prozess, http://127.0.0.1:8000.
#
# Das Backend liefert die gebaute Oberflaeche selbst aus. Ist der Build
# veraltet (etwa nach "git pull"), wird vorher neu gebaut.
#
#   bash scripts/start.sh [--no-browser] [--rebuild]
#
# Zum Entwickeln mit Hot-Reload stattdessen scripts/dev.sh.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
URL="http://127.0.0.1:8000"
NO_BROWSER=""; REBUILD=""
for arg in "$@"; do
  case "$arg" in
    --no-browser) NO_BROWSER=1 ;;
    --rebuild) REBUILD=1 ;;
    *) echo "Unbekannte Option: $arg" >&2; exit 2 ;;
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

[ -d "$REPO/backend/.venv" ] || { echo "Backend nicht eingerichtet. Zuerst scripts/setup.sh ausfuehren." >&2; exit 1; }

if backend_up; then
  echo "Backend laeuft bereits -> $URL"
  open_browser
  exit 0
fi

STATE="$(cd "$REPO/backend" && uv run python ../scripts/build_status.py || true)"
if [ -n "$REBUILD" ] || [ "${STATE%% *}" != "fresh" ]; then
  echo "Oberflaeche: $STATE -> baue neu ..."
  (cd "$REPO/frontend" && pnpm_cmd install --frozen-lockfile && pnpm_cmd build)
fi

(cd "$REPO/backend" && exec uv run python -m app) &
BACKEND=$!
trap 'kill "$BACKEND" 2>/dev/null || true' EXIT INT TERM

for _ in $(seq 1 100); do
  backend_up && break
  kill -0 "$BACKEND" 2>/dev/null || { echo "Backend beendet sich sofort (Port 8000 belegt?)." >&2; exit 1; }
  sleep 0.3
done
backend_up || { echo "Backend antwortet nicht innerhalb von 30 s." >&2; exit 1; }

echo ""
echo "Plattform laeuft -> $URL"
echo "FreeCAD: Workbench 'SysML-CAD Bruecke', Bruecke starten. Strg+C beendet."
open_browser
wait "$BACKEND"
