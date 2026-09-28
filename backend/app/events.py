"""Ein Ereignisstrom zum Browser.

Der Browser haelt genau EINE WebSocket-Verbindung -- zum Backend, nie zur
Bruecke. Darauf kommen:
  * die Ereignisse aus FreeCAD (von der Bruecke weitergereicht, gebuendelt)
  * der Verbindungsstatus der Bruecke
  * spaeter eigene Ereignisse der Projektmodule

Jeder Client hat eine eigene, BESCHRAENKTE Warteschlange. Haengt ein Tab (etwa
im Hintergrund gedrosselt), laeuft nur seine Schlange ueber -- dann wird ihr
Inhalt durch ein einzelnes cad.resync ersetzt. Der Stau steht damit nicht
einfach einen Prozess weiter.

Der Browser invalidiert bei JEDEM Verbindungsaufbau ohnehin alles; ein Replay
verpasster Ereignisse gibt es bewusst nicht.
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
        """Einen verbundenen Browser bedienen, bis er geht."""
        client = _Client(websocket)
        self._clients.add(client)
        client.task = asyncio.create_task(self._sender(client))
        try:
            await websocket.send_text(json.dumps(hello))
            # Der Kanal ist server->client. Lesen nur, um das Schliessen zu merken.
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
        """Beliebiger Frame, etwa von einem Projektmodul ({"type": "bds.*"})."""
        self._push(frame)

    def publish_events(self, events):
        if events:
            self._push({"type": ev.BATCH, "events": list(events)})

    def publish_status(self, status):
        self._push({"type": "bridge.status", "status": status})
