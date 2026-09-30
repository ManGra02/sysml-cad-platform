#!/usr/bin/env bash
# Links bridge/ as a FreeCAD addon (symlink, not a copy).
#
# The target path is queried from FreeCAD at RUNTIME, not guessed:
# AppImage, Snap and Homebrew each put it somewhere else. FreeCAD 1.1 uses
# versioned user directories -- "v1-1" with a hyphen.
#
# Alternative without linking:  freecad -M "<repo>/bridge"
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SOURCE="$REPO/bridge"
LINK_NAME="SysMLCadPlatform"
FORCE="${1:-}"

[ -f "$SOURCE/package.xml" ] || { echo "bridge/package.xml missing under $SOURCE" >&2; exit 1; }

find_python() {
  if [ -n "${FREECAD_PYTHON:-}" ]; then echo "$FREECAD_PYTHON"; return; fi
  for candidate in \
    "/Applications/FreeCAD.app/Contents/Resources/bin/python" \
    "$(command -v freecadcmd || true)" \
    "$(command -v FreeCADCmd || true)" \
    "$(command -v python3 || true)"
  do
    [ -n "$candidate" ] && [ -x "$candidate" ] && { echo "$candidate"; return; }
  done
}

PY="$(find_python)"
[ -n "$PY" ] || { echo "FreeCAD's Python not found. Set FREECAD_PYTHON=<path>." >&2; exit 1; }

export PYTHONNOUSERSITE=1
MOD_DIR="$("$PY" -c "import FreeCAD, os; print(os.path.join(FreeCAD.getUserAppDataDir(), 'Mod'))" 2>/dev/null || true)"
if [ -z "$MOD_DIR" ]; then
  echo "FreeCAD could not be imported with '$PY'." >&2
  echo "Set FREECAD_PYTHON to FreeCAD's own Python." >&2
  exit 1
fi

echo "Mod directory: $MOD_DIR"
mkdir -p "$MOD_DIR"
TARGET="$MOD_DIR/$LINK_NAME"

if [ -e "$TARGET" ] || [ -L "$TARGET" ]; then
  if [ ! -L "$TARGET" ]; then
    echo "ERROR: $TARGET is a real COPY, not a link." >&2
    echo "You would be editing a dead copy. Please check and delete it." >&2
    exit 1
  fi
  if [ "$FORCE" != "--force" ]; then
    CURRENT="$(readlink "$TARGET")"
    if [ "$(cd "$CURRENT" 2>/dev/null && pwd -P)" != "$(cd "$SOURCE" && pwd -P)" ]; then
      echo "Link points to a DIFFERENT repo: $CURRENT"
      echo "FreeCAD will then load the bridge from there. Use --force to redirect it to this repo."
    else
      echo "Link already exists -> $CURRENT"
    fi
    exit 0
  fi
  rm "$TARGET"
  echo "Removed old link."
fi

ln -s "$SOURCE" "$TARGET"
echo ""
echo "Linked: $TARGET -> $SOURCE"
echo "Restart FreeCAD, then select the 'SysML-CAD Bridge' workbench."
