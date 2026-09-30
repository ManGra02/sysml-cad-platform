#!/usr/bin/env bash
# Setup from scratch: dependencies, UI build, addon link, diagnostics.
#
# After a fresh "git clone", this one script is all you need; it is
# repeatable (e.g. after "git pull").
#
#   bash scripts/setup.sh              # everything
#   bash scripts/setup.sh --skip-link  # without addon link (second working copy)
#
# Prerequisites: FreeCAD 1.1, uv, node (22 LTS), pnpm >= 10 (otherwise corepack).
# Specify FreeCAD's Python via FREECAD_PYTHON=<path> if needed.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SKIP_LINK=""
[ "${1:-}" = "--skip-link" ] && SKIP_LINK=1
# shellcheck source=_common.sh
. "$REPO/scripts/_common.sh"

step() { printf '\n== %s\n' "$1"; }

step "Tools"
missing=0
for pair in "uv|https://docs.astral.sh/uv/" "node|https://nodejs.org (Node 22 LTS)"; do
  tool="${pair%%|*}"; hint="${pair#*|}"
  if command -v "$tool" >/dev/null 2>&1; then
    printf '  %-5s %s\n' "$tool" "$(command -v "$tool")"
  else
    echo "  $tool missing -> $hint" >&2
    missing=1
  fi
done
[ "$missing" = 0 ] || { echo "Please install the missing tools and run again." >&2; exit 1; }

step "Backend: Python environment (uv sync)"
(cd "$REPO/backend" && uv sync)

step "Frontend: dependencies (pnpm install)"
(cd "$REPO/frontend" && pnpm_cmd install --frozen-lockfile)

step "Frontend: build UI (pnpm build)"
(cd "$REPO/frontend" && pnpm_cmd build)

if [ -n "$SKIP_LINK" ]; then
  step "Link addon: skipped (--skip-link)"
else
  step "Link addon into FreeCAD"
  bash "$REPO/scripts/link-addon.sh"
fi

step "Diagnostics"
(cd "$REPO/backend" && uv run python ../scripts/doctor.py)

echo ""
echo "Done."
echo "  1. Start FreeCAD, select the 'SysML-CAD Bridge' workbench, start the bridge"
echo "  2. bash scripts/start.sh   -> http://127.0.0.1:8000"
echo "     (development with hot reload: bash scripts/dev.sh -> http://127.0.0.1:5173)"
