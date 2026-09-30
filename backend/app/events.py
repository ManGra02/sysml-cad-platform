"""One event stream to the browser.

The browser holds exactly ONE WebSocket connection -- to the backend, never
to the bridge. It carries:
  * the events from FreeCAD (relayed by the bridge, batched)
  * the bridge's connection status
  * later, the project modules' own events

Each client has its own BOUNDED queue. If a tab stalls (e.g. throttled in
the background), only its queue overflows -- its contents are then replaced
by a single cad.resync. That way the backlog doesn't simply pile up one
process further along.

The browser invalidates everything on EVERY (re)connect anyway; replaying
missed events is deliberately not supported.
"""

import asyncio
import json

from cad_contract import events as ev

MAX_PENDING_FRAMES = 256


class _Client:
    def __init__(self, websocket):
        self.websocket = websocket
        self.queue = asyncio.Queue(maxsize=MAX_PENDING_FRAMES)
        self.task = None


class BrowserHub:
    def __init__(self):
        self._clients = set()

    @property
    def client_count(self):
        return len(self._clients)

    async def serve(self, websocket, hello):
        """Serve a connected browser until it goes away."""
        client = _Client(websocket)
        self._clients.add(client)
        client.task = asyncio.create_task(self._sender(client))
        try:
            await websocket.send_text(json.dumps(hello))
            # The channel is server->client. Read only to notice the close.
            while True:
                message = await websocket.receive()
                if message.get("type") == "websocket.disconnect":
                    break
        finally:
            self._clients.discard(client)
            client.task.cancel()

    async def _sender(self, client):
        try:
            while True:
                frame = await client.queue.get()
                await client.websocket.send_text(frame)
        except asyncio.CancelledError:
            pass
        except Exception:
            self._clients.discard(client)

    def _push(self, frame):
        text = json.dumps(frame)
        for client in list(self._clients):
            try:
                client.queue.put_nowait(text)
            except asyncio.QueueFull:
                while not client.queue.empty():
                    client.queue.get_nowait()
                client.queue.put_nowait(json.dumps(
                    {"type": ev.BATCH, "events": [{"type": ev.RESYNC, "reason": "overflow"}]}
                ))

    def publish(self, frame):
        """Arbitrary frame, e.g. from a project module ({"type": "bds.*"})."""
        self._push(frame)

    def publish_events(self, events):
        if events:
            self._push({"type": ev.BATCH, "events": list(events)})

    def publish_status(self, status):
        self._push({"type": "bridge.status", "status": status})
