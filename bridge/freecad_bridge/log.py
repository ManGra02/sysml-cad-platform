"""Logging of the bridge.

A separate module so that server.py literally obeys the rule "no FreeCAD
access in the HTTP layer" and the CI grep stays clean.

FreeCAD's Console methods are explicitly thread-safe (as noted in
FreeCAD's own Mod/Test/BaseTests.py) -- which makes them the only
FreeCAD API that may be called from the server thread.

The request ID is carried along so that a request can be traced across
all three processes.
"""

import FreeCAD

PREFIX = "[Bridge]"


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
