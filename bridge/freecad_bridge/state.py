"""Process-wide state of the bridge.

WHY NOT IN THE MODULE NAMESPACE: During development the addon is reloaded via
``del sys.modules[...]`` + re-import. Module globals would be reset in the
process, while the thread, QTimer and DocumentObserver of the old instance
keep running -- you would have two bridges and no access to the old one.
That is why the state lives in ``FreeCAD.__dict__`` and survives the reload.

The ``generation`` increases on every start. Callbacks belonging to an older
generation (lingering QTimers, orphaned futures) detect this and terminate
themselves.
"""

import uuid

import FreeCAD

_KEY = "__sysml_cad_bridge_state__"


class BridgeState(object):
    """The single state that exists per FreeCAD process."""

    def __init__(self):
        self.generation = 0
        self.session_id = None      # UUID, new on every start
        self.running = False
        self.shutting_down = False
        self.host = "127.0.0.1"
        self.port = None
        self.token = None
        self.event_seq = 0
        self.last_error = None
        # Set by start(), cleared by stop_bridge():
        self.loop = None            # asyncio loop of the server thread
        self.thread = None
        self.runner = None          # aiohttp AppRunner
        self.observer = None
        self.flush_timer = None
        self.stop_event = None
        self.hub = None                # EventHub, belongs to the server thread's loop
        self.active_request_id = None  # set during one of our own writes
        self.revisions = {}
        self.waker = None
        self.quit_hook_installed = False

    def begin_session(self):
        """Begin a new session: increment the generation, fresh session_id."""
        self.generation += 1
        self.revisions = {}  # new session_id = backend reloads everything anyway
        self.session_id = str(uuid.uuid4())
        self.event_seq = 0
        self.shutting_down = False
        self.last_error = None
        return self.generation

    def next_seq(self):
        self.event_seq += 1
        return self.event_seq

    def describe(self):
        """Short summary for the dock panel and logs."""
        if self.last_error:
            return "Error: %s" % self.last_error
        if self.shutting_down:
            return "shutting down ..."
        if self.running:
            return "running on %s:%s" % (self.host, self.port)
        return "stopped"


def get_state():
    """Get the process-wide state, creating it if necessary."""
    state = FreeCAD.__dict__.get(_KEY)
    if state is None:
        state = BridgeState()
        FreeCAD.__dict__[_KEY] = state
    return state
