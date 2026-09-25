"""Der Rueckweg: Ereignisse vom Qt-Hauptthread zu den WebSocket-Clients.

Der Observer laeuft auf dem Qt-Thread und darf NIE ws.send_str aufrufen --
das gehoert dem asyncio-Loop im Server-Thread. Der einzige Uebergang ist
``loop.call_soon_threadsafe``; ab dort liegt alles in einer asyncio-Queue, aus
der ein Broadcast-Task die Clients speist.

Die Queue ist BESCHRAENKT. Laeuft sie ueber (ein Client haengt, ein riesiger
Recompute), wird ihr Inhalt verworfen und durch ein einzelnes ``cad.resync``
ersetzt: der Client laedt dann neu, statt dass der FreeCAD-Prozess Speicher
anhaeuft. Ohne verbundene Clients wird gar nichts gepuffert -- wer sich spaeter
verbindet, bekommt mit dem hello ohnehin den Anlass, alles neu zu laden.

Pro Flush geht EIN Frame hinaus (``{"type": "events", "events": [...]}``),
nicht ein Frame pro Aenderung.
"""

import asyncio
import json

from freecad_bridge import log

#: Obergrenze in Batches (ein Batch = ein Flush des Observers).
MAX_PENDING_BATCHES = 256


class EventHub(object):
    def __init__(self, loop, session_id):
        self.loop = loop
        self.session_id = session_id
        self.clients = set()
        self.queue = asyncio.Queue(maxsize=MAX_PENDING_BATCHES)
        self.task = None
        self.overflows = 0
        self.published = 0

    # -- Aufruf vom Qt-Hauptthread ------------------------------------

    def publish_threadsafe(self, events):
        """Vom Observer aufgerufen. Nur Uebergabe, keine Arbeit."""
        if not events:
            return
        try:
            self.loop.call_soon_threadsafe(self._enqueue, list(events))
        except RuntimeError:
            pass  # Loop bereits beendet -- Bruecke faehrt herunter

    # -- ab hier im Loop-Thread ---------------------------------------

    def _enqueue(self, events):
        if not self.clients:
            return
        try:
            self.queue.put_nowait(events)
        except asyncio.QueueFull:
            self.overflows += 1
            while not self.queue.empty():
                self.queue.get_nowait()
            self.queue.put_nowait(
                [{"type": "cad.resync", "reason": "overflow", "session_id": self.session_id}]
            )
            log.warn("Ereignis-Queue uebergelaufen -- Clients erhalten cad.resync")

    async def run(self):
        while True:
            events = await self.queue.get()
            frame = json.dumps(
                {"type": "events", "session_id": self.session_id, "events": events}
            )
            self.published += len(events)
            for ws in list(self.clients):
                try:
                    await ws.send_str(frame)
                except Exception:
                    self.clients.discard(ws)

    def start(self):
        self.task = self.loop.create_task(self.run())
        return self.task

    async def close(self):
        if self.task is not None:
            self.task.cancel()
            try:
                await self.task
            except (asyncio.CancelledError, Exception):
                pass
        for ws in list(self.clients):
            try:
                await ws.close(code=1001, message=b"bridge stopping")
            except Exception:
                pass
        self.clients.clear()
