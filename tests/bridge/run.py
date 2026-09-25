"""Einstiegspunkt der Bruecken-Tests.

Aufruf:
    PYTHONNOUSERSITE=1 "<FreeCAD>/bin/python.exe" tests/bridge/run.py

WARUM NICHT ``freecadcmd -t``: das druckt "FAILED (errors=1)" und liefert
trotzdem Exit-Code 0. Eine CI darauf waere dauerhaft gruen. Hier wird der
Exit-Code explizit aus dem Ergebnis gebildet.

WARUM NICHT pytest: in FreeCADs Python ist pytest nicht installiert, und in
FreeCADs Python wird nichts installiert. aiohttp.test_utils und stdlib-unittest
reichen vollstaendig.
"""

import os
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(os.path.dirname(_HERE))
_BRIDGE = os.path.join(_REPO, "bridge")

for path in (_BRIDGE, _HERE):
    if path not in sys.path:
        sys.path.insert(0, path)


def main():
    try:
        import FreeCAD
    except ImportError:
        sys.stderr.write(
            "FreeCAD ist nicht importierbar.\n"
            "Diese Tests muessen mit FreeCADs gebuendeltem Python laufen:\n"
            '  "<FreeCAD>/bin/python.exe" tests/bridge/run.py\n'
        )
        return 2

    sys.stdout.write(
        "FreeCAD %s | GuiUp=%s | Python %s\n\n"
        % (".".join(FreeCAD.Version()[:3]), FreeCAD.GuiUp, sys.version.split()[0])
    )

    loader = unittest.TestLoader()
    suite = loader.discover(start_dir=_HERE, pattern="test_*.py", top_level_dir=_HERE)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
