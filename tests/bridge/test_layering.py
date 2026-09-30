"""Layering rules, checked mechanically.

The design rule "anything that does not touch the FreeCAD API does not belong
in the bridge" only holds if it can be verified. A comment in the README
erodes over the course of a semester.

AST instead of grep: otherwise docstrings and comments that EXPLAIN the rule
would be flagged as violations.
"""

import ast
import os
import unittest

import freecad_bridge

BRIDGE_DIR = os.path.dirname(os.path.abspath(freecad_bridge.__file__))


def freecad_attribute_uses(path):
    """Real FreeCAD./App. accesses in the code -- excluding comments and docstrings."""
    with open(path, "r", encoding="utf-8") as handle:
        tree = ast.parse(handle.read(), filename=path)

    hits = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Attribute):
            continue
        parts = []
        current = node
        while isinstance(current, ast.Attribute):
            parts.append(current.attr)
            current = current.value
        if isinstance(current, ast.Name) and current.id in ("FreeCAD", "App"):
            hits.append("%s.%s (line %d)" % (current.id, ".".join(reversed(parts)), node.lineno))
    return hits


class LayeringTest(unittest.TestCase):
    def test_http_schicht_fasst_freecad_nicht_an(self):
        """server.py is a pure transport layer.

        Logging goes through freecad_bridge.log, everything touching the document
        through dispatch() in the adapter modules.
        """
        path = os.path.join(BRIDGE_DIR, "server.py")
        hits = freecad_attribute_uses(path)
        self.assertEqual(
            hits,
            [],
            "server.py accesses FreeCAD directly: %s\n"
            "Logging belongs in freecad_bridge.log, document access behind dispatch()." % hits,
        )

    def test_nur_log_modul_nutzt_die_console(self):
        """Console.Print* is the only thread-safe FreeCAD API.

        So that it stays a deliberate exception and does not turn up scattered
        everywhere, it may only appear in log.py.
        """
        offenders = {}
        for name in os.listdir(BRIDGE_DIR):
            if not name.endswith(".py") or name in ("log.py", "__init__.py"):
                continue
            hits = [h for h in freecad_attribute_uses(os.path.join(BRIDGE_DIR, name))
                    if h.startswith("FreeCAD.Console")]
            if hits:
                offenders[name] = hits
        self.assertEqual(
            offenders,
            {},
            "FreeCAD.Console belongs exclusively in log.py: %s" % offenders,
        )


if __name__ == "__main__":
    unittest.main()
