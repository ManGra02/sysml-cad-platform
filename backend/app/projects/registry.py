"""Welche Projekte es gibt und welches gerade aktiv ist.

Die Liste der Module steht hier EXPLIZIT, nicht per Autodiscovery: ein neues
Projekt ist eine bewusste, reviewte Zeile in dieser Datei.

Das aktive Projekt ist eine Einstellung des Backends, nicht eines Browser-Tabs:
nur so erreichen FreeCAD-Ereignisse eindeutig das richtige Modul, auch wenn
gerade kein Tab die Projektseite zeigt. Es wird in einer kleinen JSON-Datei
gemerkt und ueberlebt --reload und Neustarts.
"""

import asyncio
import json
import logging
import os

from fastapi import APIRouter

from app import config
from app.projects.base import CadClient, ProjectContext
from app.projects.bds import BdsModule
from app.projects.mcr import McrModule

log = logging.getLogger("platform.projects")

#: Die registrierten Projekte, in Anzeigereihenfolge.
MODULES = [BdsModule, McrModule]

STATE_FILE = "state.json"

#: Ereignis-Stapel, die auf das aktive Modul warten. Darueber wird verworfen und
#: dem Modul ein cad.resync zugestellt -- wie ueberall in der Plattform.
MAX_PENDING_BATCHES = 200


class UnknownProject(KeyError):
    pass


class ProjectRegistry:
    def __init__(self, bridge, publish, modules=None, state_dir=None):
        self._publish = publish
        self._state_path = os.path.join(str(state_dir or config.state_dir()), STATE_FILE)
        self.modules = {}
        for cls in modules or MODULES:
            module = cls()
            if not module.id or module.id in self.modules:
                raise ValueError("Projekt-id fehlt oder doppelt: %r" % module.id)
            module.ctx = ProjectContext(module.id, CadClient(bridge, module.id), publish)
            self.modules[module.id] = module
        self.active_id = None
        self._queue = asyncio.Queue(maxsize=MAX_PENDING_BATCHES)
        self._worker = None
        self._lock = asyncio.Lock()

    # -- Lebenszyklus -----------------------------------------------------

    async def start(self):
        self._worker = asyncio.create_task(self._deliver())
        saved = self._read_state().get("active")
        if saved in self.modules:
            self.active_id = saved
            await self._call(saved, "on_activate")

    async def stop(self):
        if self._worker is not None:
            self._worker.cancel()
            try:
                await self._worker
            except asyncio.CancelledError:
                pass

    # -- Abfragen ---------------------------------------------------------

    def describe(self):
        return {
            "active": self.active_id,
            "projects": [
                {
                    "id": module.id,
                    "title": module.title,
                    "description": module.description,
                    "icon": module.icon,
                    "active": module.id == self.active_id,
                }
                for module in self.modules.values()
            ],
        }

    # -- Umschalten -------------------------------------------------------

    async def activate(self, project_id):
        if project_id not in self.modules:
            raise UnknownProject(project_id)
        async with self._lock:
            if project_id == self.active_id:
                return
            previous = self.active_id
            if previous is not None:
                await self._call(previous, "on_deactivate")
            self.active_id = project_id
            self._write_state({"active": project_id})
            await self._call(project_id, "on_activate")
        self._publish({"type": "project.activated", "id": project_id, "previous": previous})

    # -- Ereignisse aus FreeCAD -------------------------------------------

    def on_events(self, events):
        """Vom bridge_client aufgerufen (synchron). Zustellung geordnet im Worker."""
        if not events or self.active_id is None:
            return
        try:
            self._queue.put_nowait(list(events))
        except asyncio.QueueFull:
            while not self._queue.empty():
                self._queue.get_nowait()
            self._queue.put_nowait([{"type": "cad.resync", "reason": "project_overflow"}])

    async def _deliver(self):
        while True:
            events = await self._queue.get()
            module_id = self.active_id
            if module_id is None:
                continue
            for event in events:
                await self._call(module_id, "on_cad_event", event)

    async def _call(self, module_id, hook, *args):
        """Einen Haken aufrufen. Ein Fehler im Modul darf die Plattform nicht stoppen."""
        try:
            await getattr(self.modules[module_id], hook)(*args)
        except Exception:
            log.exception("Projekt %s: %s fehlgeschlagen", module_id, hook)

    # -- Routen -----------------------------------------------------------

    def mount(self, app):
        for module in self.modules.values():
            router = APIRouter(prefix="/api/projects/%s" % module.id, tags=[module.title])
            module.register_routes(router)
            app.include_router(router)

    # -- Zustand ----------------------------------------------------------

    def _read_state(self):
        try:
            with open(self._state_path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _write_state(self, data):
        directory = os.path.dirname(self._state_path)
        try:
            os.makedirs(directory, exist_ok=True)
            tmp = self._state_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as handle:
                json.dump(data, handle)
            os.replace(tmp, self._state_path)
        except OSError:
            # Nur ein Komfort: ohne Datei gilt die Wahl bis zum naechsten Neustart.
            log.warning("Aktives Projekt konnte nicht gespeichert werden (%s)", self._state_path)
