"""Einstiegspunkt der GUI-Phase.

BEWUSST MINIMAL. FreeCADs Loader liest diese Datei und fuehrt sie via exec
INNERHALB EINER FUNKTION aus. Zwei Konsequenzen, die hier alles bestimmen:

  1. ``__file__`` ist nicht definiert  -> Pfad ueber inspect.currentframe().
  2. Namen auf Modulebene landen in den Locals jener Funktion und sind aus
     Methoden heraus NICHT sichtbar (FreeCADs eigenes Mod/Assembly/InitGui.py
     traegt dafuer einen ``global``-Workaround).

Deshalb steht hier nur das Noetigste; alles Echte liegt in importierbaren
Modulen.
"""

import inspect
import os
import sys

_addon_dir = os.path.dirname(os.path.abspath(inspect.getfile(inspect.currentframe())))
if _addon_dir not in sys.path:
    sys.path.insert(0, _addon_dir)

from bridge_addon.workbench import CadBridgeWorkbench  # noqa: E402

FreeCADGui.addWorkbench(CadBridgeWorkbench())  # noqa: F821  (vom Loader injiziert)
