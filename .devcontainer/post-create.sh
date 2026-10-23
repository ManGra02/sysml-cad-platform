#!/usr/bin/env bash
# postCreateCommand of the devcontainer: runs once, after the container was created.
#
# The same steps as scripts/setup.sh, minus what needs FreeCAD (addon link,
# doctor) -- FreeCAD runs on the host, never in this container. The UI is not
# built here: scripts/start.sh builds it when it is stale, scripts/dev.sh
# does not need it.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=../scripts/_common.sh
. "$REPO/scripts/_common.sh"

step() { printf '\n== %s\n' "$1"; }

step "Backend: Python environment (uv sync)"
(cd "$REPO/backend" && uv sync)

step "Frontend: dependencies (pnpm install)"
(cd "$REPO/frontend" && pnpm_cmd install --frozen-lockfile)
