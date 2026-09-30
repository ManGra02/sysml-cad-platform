"""The return path: events from the Qt main thread to the WebSocket clients.

The observer runs on the Qt thread and must NEVER call ws.send_str --
that belongs to the asyncio loop in the server thread. The only hand-over is
``loop.call_soon_threadsafe``; from there on everything sits in an asyncio
queue from which a broadcast task feeds the clients.

The queue is BOUNDED. If it overflows (a client hangs, a huge
recompute), its contents are discarded and replaced by a single
``cad.resync``: the client then reloads instead of the FreeCAD process
accumulating memory. Without connected clients nothing is buffered at all --
whoever connects later gets the cue to reload everything with the hello anyway.

ONE frame goes out per flush (``{"type": "events", "events": [...]}``),
not one frame per change.
"""

import asyncio
import json

from freecad_bridge import log

#: Upper bound in batches (one batch = one flush of the observer).
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

    # -- Called from the Qt main thread -------------------------------

    def publish_threadsafe(self, events):
        """Called by the observer. Hand-over only, no work."""
        if not events:
            return
        try:
            self.loop.call_soon_threadsafe(self._enqueue, list(events))
        except RuntimeError:
            pass  # loop already closed -- bridge is shutting down

    # -- from here on in the loop thread -----------------------------

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
            log.warn("Event queue overflowed -- clients receive cad.resync")

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
