"""Prozessweiter Zustand der Bruecke.

WARUM NICHT IM MODULNAMENSRAUM: Beim Entwickeln wird das Addon per
``del sys.modules[...]`` + Neuimport neu geladen. Modulglobale wuerden dabei
zuruecksetzen, waehrend Thread, QTimer und DocumentObserver der alten Instanz
weiterlaufen -- man haette zwei Bruecken und keinen Zugriff mehr auf die alte.
Deshalb lebt der Zustand in ``FreeCAD.__dict__`` und ueberlebt den Reload.

Die ``generation`` steigt bei jedem Start. Callbacks, die zu einer aelteren
Generation gehoeren (haengende QTimer, verwaiste Futures), erkennen das und
beenden sich selbst.
"""

import uuid

import FreeCAD

_KEY = "__sysml_cad_bridge_state__"


class BridgeState(object):
    """Der eine Zustand, den es pro FreeCAD-Prozess gibt."""

    def __init__(self):
        self.generation = 0
        self.session_id = None      # UUID, neu bei jedem Start
        self.running = False
        self.shutting_down = False
        self.host = "127.0.0.1"
        self.port = None
        self.token = None
        self.event_seq = 0
        self.last_error = None
        # Von start() belegt, von stop_bridge() abgeraeumt:
        self.loop = None            # asyncio-Loop des Server-Threads
        self.thread = None
        self.runner = None          # aiohttp AppRunner
        self.observer = None
        self.flush_timer = None
        self.stop_event = None
        self.hub = None                # EventHub, gehoert dem Loop des Server-Threads
        self.active_request_id = None  # waehrend eines eigenen Schreibvorgangs gesetzt
        self.revisions = {}
        self.waker = None
        self.quit_hook_installed = False

    def begin_session(self):
        """Neue Sitzung beginnen: Generation hochzaehlen, frische session_id."""
        self.generation += 1
        self.revisions = {}  # neue session_id = Backend laedt ohnehin alles neu
        self.session_id = str(uuid.uuid4())
        self.event_seq = 0
        self.shutting_down = False
        self.last_error = None
        return self.generation

    def next_seq(self):
        self.event_seq += 1
        return self.event_seq

    def describe(self):
        """Kurzfassung fuer Dock-Panel und Logs."""
        if self.last_error:
            return "Fehler: %s" % self.last_error
        if self.shutting_down:
            return "wird beendet ..."
        if self.running:
            return "laeuft auf %s:%s" % (self.host, self.port)
        return "gestoppt"


def get_state():
    """Den prozessweiten Zustand holen, notfalls anlegen."""
    state = FreeCAD.__dict__.get(_KEY)
    if state is None:
        state = BridgeState()
        FreeCAD.__dict__[_KEY] = state
    return state
