#!/usr/bin/env bash
# Einrichtung von Null: Abhaengigkeiten, Oberflaeche bauen, Addon verlinken, Diagnose.
#
# Nach einem frischen "git clone" genuegt dieses eine Skript; es ist
# wiederholbar (etwa nach "git pull").
#
#   bash scripts/setup.sh              # alles
#   bash scripts/setup.sh --skip-link  # ohne Addon-Link (zweite Arbeitskopie)
#
# Voraussetzungen: FreeCAD 1.1, uv, node (22 LTS), pnpm >= 10 (sonst corepack).
# FreeCADs Python ggf. per FREECAD_PYTHON=<pfad> angeben.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SKIP_LINK=""
[ "${1:-}" = "--skip-link" ] && SKIP_LINK=1
# shellcheck source=_common.sh
. "$REPO/scripts/_common.sh"

step() { printf '\n== %s\n' "$1"; }

step "Werkzeuge"
missing=0
for pair in "uv|https://docs.astral.sh/uv/" "node|https://nodejs.org (Node 22 LTS)"; do
  tool="${pair%%|*}"; hint="${pair#*|}"
  if command -v "$tool" >/dev/null 2>&1; then
    printf '  %-5s %s\n' "$tool" "$(command -v "$tool")"
  else
    echo "  $tool fehlt -> $hint" >&2
    missing=1
  fi
done
[ "$missing" = 0 ] || { echo "Bitte die fehlenden Werkzeuge installieren und erneut starten." >&2; exit 1; }

step "Backend: Python-Umgebung (uv sync)"
(cd "$REPO/backend" && uv sync)

step "Frontend: Abhaengigkeiten (pnpm install)"
(cd "$REPO/frontend" && pnpm_cmd install --frozen-lockfile)

step "Frontend: Oberflaeche bauen (pnpm build)"
(cd "$REPO/frontend" && pnpm_cmd build)

if [ -n "$SKIP_LINK" ]; then
  step "Addon verlinken: uebersprungen (--skip-link)"
else
  step "Addon nach FreeCAD verlinken"
  bash "$REPO/scripts/link-addon.sh"
fi

step "Diagnose"
(cd "$REPO/backend" && uv run python ../scripts/doctor.py)

echo ""
echo "Fertig."
echo "  1. FreeCAD starten, Workbench 'SysML-CAD Bruecke' waehlen, Bruecke starten"
echo "  2. bash scripts/start.sh   -> http://127.0.0.1:8000"
echo "     (Entwicklung mit Hot-Reload: bash scripts/dev.sh -> http://127.0.0.1:5173)"
