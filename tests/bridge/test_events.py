"""M4: Ereignisse -- koalesziert, identitaetsbasiert, ohne Sturm.

Headless gibt es keine Qt-Ereignisschleife, der 100-ms-Timer feuert also nie.
Die Tests rufen flush() dort selbst auf, wo sonst der Timer greifen wuerde.
Alle anderen Flush-Grenzen (Commit, Undo, Recompute, Close) loest FreeCAD
selbst aus -- die werden hier unveraendert geprueft.
"""

import asyncio
import os
import socket
import tempfile
import unittest

import FreeCAD

from freecad_bridge import observer, revisions, runner, writes
from freecad_bridge import state as bridge_state

DOC_NAME = "EventTestDoc"
EXAMPLES = os.path.join(FreeCAD.getResourceDir(), "examples")


def close_all():
    for name in list(FreeCAD.listDocuments()):
        try:
            FreeCAD.closeDocument(name)
        except Exception:
            pass


class ObserverTestCase(unittest.TestCase):
    """Observer mit einer Auffangliste statt des WebSocket-Hubs."""

    def setUp(self):
        close_all()
        self.batches = []
        self.state = bridge_state.get_state()
        self.state.session_id = "event-test"
        self.state.event_seq = 0
        revisions.reset()
        writes._replay_cache.clear()
        self.observer = observer.install(self.state, publish=self.batches.append)

        self.doc = FreeCAD.newDocument(DOC_NAME)
        self.doc.UndoMode = 1
        self.box = self.doc.addObject("Part::Box", "Box")
        cylinder = self.doc.addObject("Part::Cylinder", "Zylinder")
        cut = self.doc.addObject("Part::Cut", "Schnitt")
        cut.Base, cut.Tool = self.box, cylinder
        self.doc.recompute()
        self.doc.clearUndos()
        self.observer.flush("setup")
        self.batches.clear()

    def tearDown(self):
        observer.uninstall(self.state)
        close_all()

    def events(self, type_=None):
        flat = [event for batch in self.batches for event in batch]
        if type_ is None:
            return flat
        return [event for event in flat if event["type"] == type_]


class CoalescingTest(ObserverTestCase):
    def test_aenderung_ausserhalb_transaktion(self):
        self.box.Length = 42
        self.observer.flush("timer")
        changed = [e for e in self.events("cad.changed") if e["obj"] == "Box"]
        self.assertEqual(len(changed), 1)
        self.assertIn("Length", changed[0]["props"])
        self.assertEqual(changed[0]["origin"], observer.USER_ORIGIN)
        self.assertEqual(changed[0]["cause"], "timer")

    def test_viele_aenderungen_ein_ereignis(self):
        for value in range(1, 51):
            self.box.Length = value
        self.observer.flush("timer")
        changed = [e for e in self.events("cad.changed") if e["obj"] == "Box"]
        self.assertEqual(len(changed), 1, "50 Aenderungen muessen zu EINEM Ereignis werden")

    def test_ein_flush_ist_ein_batch(self):
        self.box.Length = 12
        self.doc.getObject("Zylinder").Radius = 3
        self.observer.flush("timer")
        self.assertEqual(len(self.batches), 1)

    def test_interne_properties_erscheinen_nicht(self):
        self.box.Length = 13
        self.doc.recompute()
        for event in self.events("cad.changed"):
            for prop in event["props"]:
                self.assertFalse(prop.startswith("_"), prop)

    def test_ereignisse_tragen_keine_werte(self):
        """Nur Identitaet -- der Browser liest ueber die normale Route nach."""
        self.box.Length = 14
        self.observer.flush("timer")
        event = self.events("cad.changed")[0]
        self.assertNotIn("value", event)
        self.assertNotIn("properties", event)
        for key in ("doc", "obj", "seq", "session_id", "rev", "origin", "cause"):
            self.assertIn(key, event)

    def test_seq_ist_monoton(self):
        self.box.Length = 15
        self.observer.flush("timer")
        self.box.Length = 16
        self.observer.flush("timer")
        seqs = [e["seq"] for e in self.events()]
        self.assertEqual(seqs, sorted(seqs))
        self.assertEqual(len(seqs), len(set(seqs)))

    def test_rev_steigt_mit_jedem_flush(self):
        self.box.Length = 17
        self.observer.flush("timer")
        self.box.Length = 18
        self.observer.flush("timer")
        revs = [e["rev"] for e in self.events("cad.changed") if e["obj"] == "Box"]
        self.assertEqual(revs, [1, 2])


class BoundaryTest(ObserverTestCase):
    """FreeCADs eigene Grenzen loesen den Flush aus -- ohne Timer."""

    def test_recompute_flusht(self):
        self.box.Length = 20
        self.doc.recompute()
        self.assertTrue(self.events("cad.recomputed"))
        names = {e["obj"] for e in self.events("cad.changed")}
        self.assertIn("Box", names)
        self.assertIn("Schnitt", names, "abhaengiges Objekt wurde neu berechnet")

    def test_commit_flusht(self):
        FreeCAD.setActiveTransaction("Nutzer")
        self.box.Length = 21
        FreeCAD.closeActiveTransaction()
        transactions = self.events("cad.transaction")
        self.assertEqual(transactions[0]["result"], "committed")
        self.assertEqual(transactions[0]["name"], "Nutzer")

    def test_undo_ist_als_history_erkennbar(self):
        """Undo eines Create feuert slotDeletedObject -- ohne cad.history nicht unterscheidbar."""
        FreeCAD.setActiveTransaction("t")
        self.box.Length = 22
        FreeCAD.closeActiveTransaction()
        self.batches.clear()

        self.doc.undo()
        history = self.events("cad.history")
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["action"], "undo")
        changed = [e for e in self.events("cad.changed") if e["obj"] == "Box"]
        self.assertEqual(changed[0]["cause"], "undo", "Aenderungen kommen VOR slotUndoDocument")


class LifecycleEventTest(ObserverTestCase):
    def test_neues_objekt_nur_als_created(self):
        obj = self.doc.addObject("Part::Sphere", "Kugel")
        obj.Radius = 4
        self.observer.flush("timer")
        created = [e for e in self.events("cad.created") if e["obj"] == "Kugel"]
        changed = [e for e in self.events("cad.changed") if e["obj"] == "Kugel"]
        self.assertEqual(len(created), 1)
        self.assertEqual(changed, [], "created impliziert vollstaendiges Nachlesen")

    def test_geloeschtes_objekt_nur_als_deleted(self):
        """Nach slotDeletedObject feuern noch Aenderungen (AttachmentSupport)."""
        self.doc.removeObject("Zylinder")
        self.observer.flush("timer")
        deleted = [e for e in self.events("cad.deleted") if e["obj"] == "Zylinder"]
        changed = [e for e in self.events("cad.changed") if e["obj"] == "Zylinder"]
        self.assertEqual(len(deleted), 1)
        self.assertEqual(changed, [])

    def test_schemaaenderung(self):
        self.box.addProperty("App::PropertyString", "Notiz")
        self.observer.flush("timer")
        self.assertTrue([e for e in self.events("cad.schema_changed") if e["obj"] == "Box"])

    def test_dokument_schliessen(self):
        FreeCAD.closeDocument(DOC_NAME)
        closed = self.events("doc.closed")
        self.assertEqual([e["doc"] for e in closed], [DOC_NAME])

    def test_neues_dokument_meldet_opened(self):
        FreeCAD.newDocument("Zweites")
        self.observer.flush("timer")
        opened = [e for e in self.events("doc.opened") if e["doc"] == "Zweites"]
        self.assertEqual(len(opened), 1)


class RestoreTest(ObserverTestCase):
    def test_datei_oeffnen_ergibt_ein_opened(self):
        path = os.path.join(tempfile.gettempdir(), "event_restore_test.FCStd")
        self.doc.saveAs(path)
        FreeCAD.closeDocument(self.doc.Name)
        self.batches.clear()

        reopened = FreeCAD.openDocument(path)
        self.observer.flush("timer")

        opened = [e for e in self.events("doc.opened") if e["doc"] == reopened.Name]
        self.assertEqual(len(opened), 1)
        self.assertEqual(opened[0]["objectCount"], len(reopened.Objects))
        object_events = [e for e in self.events() if e["type"].startswith("cad.") and e.get("obj")]
        self.assertEqual(object_events, [], "Restore-Ereignisse muessen verworfen werden")
        self.assertEqual(reopened.UndoMode, 1, "UndoMode wird nach dem Restore nachgezogen")

    @unittest.skipUnless(
        os.path.isfile(os.path.join(EXAMPLES, "BIMExample.FCStd")),
        "BIMExample.FCStd nicht mitgeliefert",
    )
    def test_bim_beispiel_ohne_ereignissturm(self):
        """Abnahme M4: 26.971 Callbacks duerfen nicht zu 26.971 Frames werden."""
        self.batches.clear()
        doc = FreeCAD.openDocument(os.path.join(EXAMPLES, "BIMExample.FCStd"))
        self.observer.flush("timer")
        opened = [e for e in self.events("doc.opened") if e["doc"] == doc.Name]
        self.assertEqual(len(opened), 1)
        self.assertLess(len(self.events()), 10, "Ereignissturm: %d" % len(self.events()))


class RobustnessTest(ObserverTestCase):
    def test_fehler_im_publish_erreicht_freecad_nicht(self):
        def broken(_events):
            raise RuntimeError("Hub kaputt")

        self.observer._publish = broken
        self.box.Length = 30
        self.observer.flush("timer")  # darf nicht werfen

    def test_uninstall_stoppt_meldungen(self):
        observer.uninstall(self.state)
        self.box.Length = 31
        self.doc.recompute()
        self.assertEqual(self.events(), [])


class WriteOriginTest(ObserverTestCase):
    def test_eigener_patch_traegt_request_id(self):
        result = writes.patch_object(DOC_NAME, "Box", {"Length": "33 mm"}, request_id="req-7")
        box_events = [e for e in self.events("cad.changed") if e["obj"] == "Box"]
        self.assertTrue(box_events)
        self.assertEqual(box_events[-1]["origin"], "bridge:req-7")
        self.assertEqual(result["rev"], box_events[-1]["rev"],
                         "Antwort und Ereignis muessen dieselbe Revision tragen")

    def test_abhaengige_objekte_tragen_dieselbe_herkunft(self):
        writes.patch_object(DOC_NAME, "Box", {"Length": "34 mm"}, request_id="req-8")
        cut_events = [e for e in self.events("cad.changed") if e["obj"] == "Schnitt"]
        self.assertTrue(cut_events)
        self.assertEqual(cut_events[-1]["origin"], "bridge:req-8")


def run_with_main_thread_pump(scenario_factory, timeout=20.0):
    """Client-Szenario in einem Worker, Hauptthread leert die Dispatch-Queue.

    Das bildet den GUI-Betrieb nach: dort ruft Qt drain() auf dem Hauptthread
    auf. Headless gibt es niemanden dafuer -- also pumpt der Test.
    """
    import threading
    import time

    from freecad_bridge import dispatch

    box = {}

    def worker():
        try:
            box["result"] = asyncio.run(scenario_factory())
        except BaseException as exc:  # noqa: BLE001 - an den Test weiterreichen
            box["error"] = exc

    thread = threading.Thread(target=worker, name="ws-client")
    thread.start()
    deadline = time.monotonic() + timeout
    while thread.is_alive() and time.monotonic() < deadline:
        dispatch.drain(reschedule=False)
        time.sleep(0.01)
    thread.join(1.0)
    if "error" in box:
        raise box["error"]
    if "result" not in box:
        raise AssertionError("Szenario nicht innerhalb von %ss beendet" % timeout)
    return box["result"]


def port_is_taken():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind(("127.0.0.1", runner.PORT))
            return False
        except OSError:
            return True


class WebSocketEndToEndTest(unittest.TestCase):
    """Echter Server, echter WebSocket: PATCH -> Ereignis beim Client."""

    def setUp(self):
        close_all()
        runner.stop_bridge(quiet=True)
        if port_is_taken():
            self.skipTest("Port %d belegt (FreeCAD mit laufender Bruecke?)" % runner.PORT)
        runner.start_bridge()
        self.state = bridge_state.get_state()
        doc = FreeCAD.newDocument(DOC_NAME)
        doc.UndoMode = 1
        doc.addObject("Part::Box", "Box")
        doc.recompute()
        observer.flush_now("setup")

    def tearDown(self):
        runner.stop_bridge(quiet=True)
        close_all()

    def test_patch_erscheint_als_ereignis(self):
        import aiohttp

        token = self.state.token
        base = "http://127.0.0.1:%d" % runner.PORT
        headers = {"Authorization": "Bearer " + token}

        async def scenario():
            async with aiohttp.ClientSession() as session:
                async with session.ws_connect(base + "/ws", headers=headers) as ws:
                    hello = await ws.receive_json(timeout=5)
                    self.assertEqual(hello["type"], "hello")
                    self.assertEqual(hello["session_id"], self.state.session_id)

                    response = await session.patch(
                        base + "/api/cad/documents/%s/objects/Box" % DOC_NAME,
                        headers=dict(headers, **{"X-Request-Id": "ws-1"}),
                        json={"Length": "44 mm"},
                    )
                    self.assertEqual(response.status, 200)

                    while True:
                        frame = await ws.receive_json(timeout=5)
                        if frame["type"] != "events":
                            continue
                        box = [e for e in frame["events"]
                               if e["type"] == "cad.changed" and e.get("obj") == "Box"]
                        if box:
                            return box[0]

        event = run_with_main_thread_pump(scenario)
        self.assertEqual(event["origin"], "bridge:ws-1")
        self.assertIn("Length", event["props"])

    def test_websocket_ohne_token_abgewiesen(self):
        import aiohttp

        async def scenario():
            async with aiohttp.ClientSession() as session:
                try:
                    async with session.ws_connect("http://127.0.0.1:%d/ws" % runner.PORT):
                        return "verbunden"
                except aiohttp.WSServerHandshakeError as exc:
                    return exc.status

        self.assertEqual(asyncio.run(scenario()), 401)


if __name__ == "__main__":
    unittest.main()
