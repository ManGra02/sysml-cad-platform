"""Monotoner Revisionszaehler pro Objekt.

FreeCAD hat keinen eigenen Aenderungszaehler. Ohne ``rev`` ueberschreibt sich
der Property-Editor spaeter beim Tippen selbst: das WebSocket-Event einer
eigenen Aenderung kann VOR der PATCH-Antwort ankommen, und eine aeltere Antwort
darf dann nicht den neueren Stand im Cache ueberschreiben.

In M3 zaehlen nur eigene Schreibvorgaenge hoch; ab M4 auch der Observer bei
Aenderungen aus FreeCAD selbst.

Der Zaehler lebt im prozessweiten State, damit er einen Modul-Reload
ueberlebt. Nach einem Bruecken-Neustart beginnt er von vorn -- das ist
beabsichtigt: die neue session_id sagt dem Backend ohnehin, dass es alles neu
laden muss.
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
