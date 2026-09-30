"""Monotonic revision counter per object.

FreeCAD has no change counter of its own. Without ``rev`` the property editor
would later overwrite itself while typing: the WebSocket event of our own
change can arrive BEFORE the PATCH response, and an older response must then
not overwrite the newer state in the cache.

In M3 only our own writes increment it; from M4 on, the observer does too for
changes made in FreeCAD itself.

The counter lives in the process-wide state so that it survives a module
reload. After a bridge restart it starts over -- this is intentional: the
new session_id tells the backend anyway that it has to reload everything.
"""

from freecad_bridge import state as bridge_state


def _table():
    state = bridge_state.get_state()
    table = getattr(state, "revisions", None)
    if table is None:
        table = {}
        state.revisions = table
    return table


def current(doc_name, obj_name):
    return _table().get((doc_name, obj_name), 0)


def bump(doc_name, obj_name):
    table = _table()
    key = (doc_name, obj_name)
    table[key] = table.get(key, 0) + 1
    return table[key]


def reset():
    _table().clear()
