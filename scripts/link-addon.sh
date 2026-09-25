#!/usr/bin/env bash
# Verlinkt bridge/ als FreeCAD-Addon (Symlink, keine Kopie).
#
# Der Zielpfad wird zur LAUFZEIT von FreeCAD erfragt, nicht geraten:
# AppImage, Snap und Homebrew legen ihn jeweils woanders ab. FreeCAD 1.1 nutzt
# versionierte Benutzerverzeichnisse -- "v1-1" mit Bindestrich.
#
# Alternative ohne Verlinkung:  freecad -M "<repo>/bridge"
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SOURCE="$REPO/bridge"
LINK_NAME="SysMLCadPlatform"
FORCE="${1:-}"

[ -f "$SOURCE/package.xml" ] || { echo "bridge/package.xml fehlt unter $SOURCE" >&2; exit 1; }

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
[ -n "$PY" ] || { echo "FreeCADs Python nicht gefunden. FREECAD_PYTHON=<pfad> setzen." >&2; exit 1; }

export PYTHONNOUSERSITE=1
MOD_DIR="$("$PY" -c "import FreeCAD, os; print(os.path.join(FreeCAD.getUserAppDataDir(), 'Mod'))" 2>/dev/null || true)"
if [ -z "$MOD_DIR" ]; then
  echo "FreeCAD konnte mit '$PY' nicht importiert werden." >&2
  echo "FREECAD_PYTHON auf FreeCADs eigenes Python setzen." >&2
  exit 1
fi

echo "Mod-Verzeichnis: $MOD_DIR"
mkdir -p "$MOD_DIR"
TARGET="$MOD_DIR/$LINK_NAME"

if [ -e "$TARGET" ] || [ -L "$TARGET" ]; then
  if [ ! -L "$TARGET" ]; then
    echo "FEHLER: $TARGET ist eine echte KOPIE, kein Link." >&2
    echo "Ihr wuerdet eine tote Kopie bearbeiten. Bitte pruefen und loeschen." >&2
    exit 1
  fi
  if [ "$FORCE" != "--force" ]; then
    echo "Link existiert bereits -> $(readlink "$TARGET")"
    echo "Mit --force neu anlegen."
    exit 0
  fi
  rm "$TARGET"
  echo "Alten Link entfernt."
fi

ln -s "$SOURCE" "$TARGET"
echo ""
echo "Verlinkt: $TARGET -> $SOURCE"
echo "FreeCAD neu starten, dann Workbench 'SysML-CAD Bruecke' waehlen."
