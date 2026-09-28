"""Platzhalter-Verhalten fuer ein noch leeres Projekt.

Zeigt, dass die Verdrahtung steht: das Modul zaehlt die FreeCAD-Ereignisse,
die es seit seiner Aktivierung bekommen hat, meldet sie per WebSocket an den
Browser und stellt sie unter GET /api/projects/<id>/info bereit.

Wer mit der eigentlichen Logik beginnt, erbt direkt von ProjectModule und
loescht diese Klasse aus seinem Modul.
"""

import collections
import time

from app.projects.base import ProjectModule

RECENT = 20


class StubModule(ProjectModule):
    def __init__(self):
        self.active_since = None
        self.events_seen = 0
        self.recent = collections.deque(maxlen=RECENT)

    def register_routes(self, router):
        @router.get("/info")
        async def info():
            return {
                "id": self.id,
                "stub": True,
                "activeSince": self.active_since,
                "eventsSeen": self.events_seen,
                "recent": list(self.recent),
            }

    async def on_activate(self):
        self.active_since = time.time()
        self.events_seen = 0
        self.recent.clear()

    async def on_cad_event(self, event):
        self.events_seen += 1
        self.recent.appendleft({
            "type": event.get("type"),
            "doc": event.get("doc"),
            "obj": event.get("obj"),
            "props": event.get("props"),
            "origin": event.get("origin"),
            "at": time.time(),
        })
        self.ctx.publish("cad_seen", {"eventsSeen": self.events_seen})
