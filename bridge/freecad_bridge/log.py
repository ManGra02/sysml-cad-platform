"""Logging der Bruecke.

Eigenes Modul, damit server.py die Regel "kein FreeCAD-Zugriff in der
HTTP-Schicht" buchstaeblich einhaelt und der CI-Grep sauber bleibt.

FreeCADs Console-Methoden sind ausdruecklich threadsicher (so vermerkt in
FreeCADs eigenem Mod/Test/BaseTests.py) -- sie sind damit die einzige
FreeCAD-API, die aus dem Server-Thread aufgerufen werden darf.

Die Request-ID wird mitgefuehrt, damit sich eine Anfrage ueber alle drei
Prozesse hinweg verfolgen laesst.
"""

import FreeCAD

PREFIX = "[Bruecke]"


def _format(message, request_id=None):
    if request_id:
        return "%s (%s) %s\n" % (PREFIX, request_id, message)
    return "%s %s\n" % (PREFIX, message)


def info(message, request_id=None):
    FreeCAD.Console.PrintMessage(_format(message, request_id))


def warn(message, request_id=None):
    FreeCAD.Console.PrintWarning(_format(message, request_id))


def error(message, request_id=None):
    FreeCAD.Console.PrintError(_format(message, request_id))


def debug(message, request_id=None):
    FreeCAD.Console.PrintLog(_format(message, request_id))
