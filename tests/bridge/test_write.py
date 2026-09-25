"""M3: Schreiben -- Rundreise, Atomaritaet, Undo, ehrliche Fehler.

Die Tests pruefen genau die Zusagen, die an FreeCADs Transaktionsmodell leicht
lautlos scheitern: ein PATCH ist genau ein Undo; ein Teilfehler rollt alles
zurueck; ohne Undo wird abgewiesen statt Atomaritaet vorzutaeuschen.
"""

import unittest

import FreeCAD
from aiohttp.test_utils import AioHTTPTestCase

from cad_contract import types
from freecad_bridge import documents, properties, revisions, server, snapshot, writes
from freecad_bridge import state as bridge_state
from freecad_bridge.dispatch import CadBusyError

DOC_NAME = "WriteTestDoc"
TOKEN = "write-test-token"


def build_document():
    try:
        FreeCAD.closeDocument(DOC_NAME)
    except Exception:
        pass
    doc = FreeCAD.newDocument(DOC_NAME)
    doc.UndoMode = 1

    box = doc.addObject("Part::Box", "Box")
    box.Length, box.Width, box.Height = 30, 20, 10
    cylinder = doc.addObject("Part::Cylinder", "Zylinder")
    cut = doc.addObject("Part::Cut", "Schnitt")
    cut.Base, cut.Tool = box, cylinder

    sheet = doc.addObject("Spreadsheet::Sheet", "Sheet")
    sheet.set("A1", "42")
    sheet.setAlias("A1", "laenge")

    doc.recompute()
    doc.clearUndos()
    writes._replay_cache.clear()
    revisions.reset()
    return doc


def close_document():
    try:
        FreeCAD.closeDocument(DOC_NAME)
    except Exception:
        pass


class RoundTripTest(unittest.TestCase):
    """Was gelesen wird, laesst sich unveraendert zurueckschreiben."""

    def setUp(self):
        self.doc = build_document()
        self.box = self.doc.getObject("Box")

    def tearDown(self):
        close_document()

    def roundtrip(self, name):
        entry = properties.describe_property(self.box, name)
        before = getattr(self.box, name)
        writes.patch_object(DOC_NAME, "Box", {name: entry["value"]})
        return before, getattr(self.box, name)

    def test_quantity(self):
        before, after = self.roundtrip("Length")
        self.assertEqual(before.Value, after.Value)

    def test_placement(self):
        self.box.Placement = FreeCAD.Placement(
            FreeCAD.Vector(1, 2, 3), FreeCAD.Rotation(FreeCAD.Vector(0, 0, 1), 30)
        )
        before, after = self.roundtrip("Placement")
        self.assertTrue(before.isSame(after, 1e-9))

    def test_bool(self):
        before, after = self.roundtrip("Visibility")
        self.assertEqual(before, after)

    def test_string(self):
        before, after = self.roundtrip("Label")
        self.assertEqual(before, after)


class PatchSemanticsTest(unittest.TestCase):
    def setUp(self):
        self.doc = build_document()
        self.box = self.doc.getObject("Box")

    def tearDown(self):
        close_document()

    def test_ein_patch_ist_genau_ein_undo(self):
        result = writes.patch_object(DOC_NAME, "Box", {"Length": "40 mm", "Width": "25 mm"})
        self.assertTrue(result["atomic"])
        self.assertEqual(result["status"], "done")
        self.assertEqual(self.doc.UndoCount, 1)
        self.assertEqual(self.box.Length.Value, 40.0)

        self.doc.undo()
        self.assertEqual(self.box.Length.Value, 30.0)
        self.assertEqual(self.box.Width.Value, 20.0, "Undo muss BEIDE Felder zuruecknehmen")

    def test_gleicher_wert_ist_ein_no_op(self):
        """FreeCAD legt fuer einen unveraenderten Wert keine Transaktion an."""
        result = writes.patch_object(DOC_NAME, "Box", {"Length": "30 mm"})
        self.assertFalse(result["changed"])
        self.assertEqual(result["recomputed"], 0)
        self.assertEqual(result["rev"], 0, "ohne Aenderung keine neue Revision")
        self.assertEqual(self.doc.UndoCount, 0, "kein leerer Undo-Eintrag")
        self.assertIsNone(FreeCAD.getActiveTransaction())

    def test_unveraenderte_felder_werden_uebersprungen(self):
        result = writes.patch_object(DOC_NAME, "Box", {"Length": "30 mm", "Width": "25 mm"})
        self.assertEqual(result["applied"], ["Width"])
        self.assertEqual(result["unchanged"], ["Length"])
        self.assertEqual(self.doc.UndoNames[0], "Browser: Box.Width")

    def test_transaktionsname_ist_sprechend(self):
        writes.patch_object(DOC_NAME, "Box", {"Length": "41 mm"})
        self.assertEqual(self.doc.UndoNames[0], "Browser: Box.Length")

    def test_zahl_ist_interne_einheit(self):
        writes.patch_object(DOC_NAME, "Box", {"Length": 12.5})
        self.assertEqual(self.box.Length.Value, 12.5)

    def test_abhaengige_objekte_werden_neu_berechnet(self):
        cut = self.doc.getObject("Schnitt")
        before = cut.Shape.Volume
        writes.patch_object(DOC_NAME, "Box", {"Length": "60 mm"})
        self.assertNotAlmostEqual(cut.Shape.Volume, before)

    def test_label_trotz_output_flag(self):
        writes.patch_object(DOC_NAME, "Box", {"Label": "Gehaeuse"})
        self.assertEqual(self.box.Label, "Gehaeuse")

    def test_rev_steigt(self):
        first = writes.patch_object(DOC_NAME, "Box", {"Length": "31 mm"})["rev"]
        second = writes.patch_object(DOC_NAME, "Box", {"Length": "32 mm"})["rev"]
        self.assertEqual(second, first + 1)
        self.assertEqual(revisions.current(DOC_NAME, "Box"), second)

    def test_link_ueber_namen(self):
        writes.patch_object(
            DOC_NAME, "Schnitt",
            {"Tool": {"kind": types.LINK, "ref": {"doc": DOC_NAME, "name": "Box"}}},
        )
        self.assertEqual(self.doc.getObject("Schnitt").Tool.Name, "Box")


class RejectionTest(unittest.TestCase):
    """Abgewiesen wird VOR dem ersten Schreibzugriff -- nichts wird angefasst."""

    def setUp(self):
        self.doc = build_document()
        self.box = self.doc.getObject("Box")

    def tearDown(self):
        close_document()

    def assert_untouched(self):
        self.assertEqual(self.box.Length.Value, 30.0)
        self.assertEqual(self.doc.UndoCount, 0)

    def test_falsche_einheit(self):
        with self.assertRaises(properties.InvalidValue):
            writes.patch_object(DOC_NAME, "Box", {"Length": "3 kg"})
        self.assert_untouched()

    def test_unparsbarer_text(self):
        with self.assertRaises(properties.InvalidValue):
            writes.patch_object(DOC_NAME, "Box", {"Length": "abc"})
        self.assert_untouched()

    def test_ein_ungueltiges_feld_blockiert_alle(self):
        with self.assertRaises(properties.InvalidValue):
            writes.patch_object(DOC_NAME, "Box", {"Width": "5 mm", "Length": "3 kg"})
        self.assertEqual(self.box.Width.Value, 20.0, "Width darf nicht vorab geschrieben sein")
        self.assert_untouched()

    def test_mehrere_ungueltige_felder_werden_gesammelt(self):
        with self.assertRaises(writes.InvalidPatch) as ctx:
            writes.patch_object(DOC_NAME, "Box", {"Width": "x", "Length": "3 kg"})
        self.assertEqual(len(ctx.exception.detail), 2)

    def test_shape_ist_nicht_schreibbar(self):
        with self.assertRaises(properties.NotWritable):
            writes.patch_object(DOC_NAME, "Box", {"Shape": None})

    def test_unbekannte_property(self):
        with self.assertRaises(properties.InvalidValue):
            writes.patch_object(DOC_NAME, "Box", {"GibtsNicht": 1})

    def test_interne_property(self):
        with self.assertRaises(properties.InvalidValue):
            writes.patch_object(DOC_NAME, "Box", {"_ElementMapVersion": "x"})

    def test_gebundene_expression(self):
        self.box.setExpression("Height", "Sheet.laenge")
        self.doc.recompute()
        with self.assertRaises(properties.ExpressionBound):
            writes.patch_object(DOC_NAME, "Box", {"Height": "5 mm"})

    def test_leerer_patch(self):
        with self.assertRaises(writes.InvalidPatch):
            writes.patch_object(DOC_NAME, "Box", {})

    def test_fremde_offene_transaktion(self):
        """Sonst landete unsere Aenderung in der Undo-Einheit des Nutzers."""
        FreeCAD.setActiveTransaction("Nutzerbefehl")
        try:
            with self.assertRaises(CadBusyError) as ctx:
                writes.patch_object(DOC_NAME, "Box", {"Length": "40 mm"})
            self.assertEqual(ctx.exception.detail, "transaction_open")
        finally:
            FreeCAD.closeActiveTransaction(True)
        self.assertEqual(self.box.Length.Value, 30.0)

    def test_ohne_undo_wird_abgewiesen(self):
        """Bei UndoMode 0 waere ein Abbruch wirkungslos -- also gar nicht erst schreiben."""
        original = documents.ensure_undo_enabled
        documents.ensure_undo_enabled = lambda doc: False
        self.doc.UndoMode = 0
        try:
            with self.assertRaises(writes.UndoDisabled):
                writes.patch_object(DOC_NAME, "Box", {"Length": "40 mm"})
        finally:
            documents.ensure_undo_enabled = original
            self.doc.UndoMode = 1
        self.assertEqual(self.box.Length.Value, 30.0)

    def test_undo_mode_wird_nachgezogen(self):
        """Vom Nutzer geoeffnete Dokumente haben oft UndoMode 0."""
        self.doc.UndoMode = 0
        result = writes.patch_object(DOC_NAME, "Box", {"Length": "40 mm"})
        self.assertTrue(result["atomic"])
        self.assertEqual(self.doc.UndoMode, 1)


class RollbackTest(unittest.TestCase):
    """Scheitert ein Wert MITTEN im Schreiben, wird alles zurueckgerollt."""

    def setUp(self):
        self.doc = build_document()
        self.box = self.doc.getObject("Box")

    def tearDown(self):
        close_document()

    def test_teilfehler_rollt_alles_zurueck(self):
        original = properties.decode_for_write

        def sabotage(obj, name, payload):
            if name == "Length":
                return "kein gueltiger Wert"  # setattr wirft erst in der Transaktion
            return original(obj, name, payload)

        properties.decode_for_write = sabotage
        try:
            with self.assertRaises(properties.InvalidValue) as ctx:
                writes.patch_object(DOC_NAME, "Box", {"Width": "5 mm", "Length": "x"})
        finally:
            properties.decode_for_write = original

        self.assertTrue(ctx.exception.detail["rolledBack"])
        self.assertEqual(self.box.Width.Value, 20.0, "Width muss zurueckgerollt sein")
        self.assertEqual(self.doc.UndoCount, 0, "Kein halber Undo-Eintrag")
        self.assertIsNone(FreeCAD.getActiveTransaction(), "Transaktion muss geschlossen sein")


class ReplayTest(unittest.TestCase):
    def setUp(self):
        self.doc = build_document()

    def tearDown(self):
        close_document()

    def test_gleiche_request_id_fuehrt_nicht_zweimal_aus(self):
        first = writes.patch_object(DOC_NAME, "Box", {"Length": "40 mm"}, request_id="r-1")
        second = writes.patch_object(DOC_NAME, "Box", {"Length": "40 mm"}, request_id="r-1")
        self.assertTrue(second["replayed"])
        self.assertEqual(second["rev"], first["rev"])
        self.assertEqual(self.doc.UndoCount, 1)


class RecomputeErrorTest(unittest.TestCase):
    def setUp(self):
        self.doc = build_document()

    def tearDown(self):
        close_document()

    def test_fehlerhaftes_feature_erscheint_in_errors(self):
        """Sonst meldete die Bruecke 200, waehrend ein Feature ungueltig ist."""
        cut = self.doc.getObject("Schnitt")
        cut.Tool = None  # ein Cut ohne Werkzeug ist ungueltig
        result = writes.recompute_document(DOC_NAME)
        names = [e["name"] for e in result["errors"]]
        self.assertIn("Schnitt", names)


class WriteRoutesTest(AioHTTPTestCase):
    async def get_application(self):
        self.doc = build_document()
        state = bridge_state.get_state()
        state.token = TOKEN
        state.session_id = "write-routes"
        state.running = True
        snapshot.refresh()
        return server.create_app()

    async def tearDownAsync(self):
        close_document()
        await super().tearDownAsync()

    def headers(self, request_id=None):
        headers = {"Authorization": "Bearer " + TOKEN}
        if request_id:
            headers["X-Request-Id"] = request_id
        return headers

    async def patch(self, obj, body, request_id=None):
        return await self.client.patch(
            "/api/cad/documents/%s/objects/%s" % (DOC_NAME, obj),
            headers=self.headers(request_id),
            json=body,
        )

    async def test_patch_ok(self):
        response = await self.patch("Box", {"Length": "45 mm"})
        self.assertEqual(response.status, 200)
        body = await response.json()
        self.assertEqual(body["status"], "done")
        self.assertTrue(body["atomic"])
        self.assertEqual(self.doc.getObject("Box").Length.Value, 45.0)

    async def test_patch_ungueltig_400(self):
        response = await self.patch("Box", {"Length": "3 kg"})
        self.assertEqual(response.status, 400)
        self.assertEqual((await response.json())["error"]["code"], "invalid_value")

    async def test_patch_nicht_schreibbar_409(self):
        response = await self.patch("Box", {"Shape": None})
        self.assertEqual(response.status, 409)
        self.assertEqual((await response.json())["error"]["code"], "not_writable")

    async def test_patch_unbekanntes_objekt_404(self):
        response = await self.patch("Nixda", {"Length": "1 mm"})
        self.assertEqual(response.status, 404)

    async def test_request_id_steht_im_fehler(self):
        response = await self.patch("Box", {"Length": "3 kg"}, request_id="abc-123")
        self.assertEqual((await response.json())["error"]["request_id"], "abc-123")

    async def test_rev_erscheint_in_der_leseantwort(self):
        await self.patch("Box", {"Length": "46 mm"})
        response = await self.client.get(
            "/api/cad/documents/%s/objects/Box" % DOC_NAME, headers=self.headers()
        )
        self.assertEqual((await response.json())["rev"], 1)

    async def test_recompute_route(self):
        response = await self.client.post(
            "/api/cad/documents/%s/recompute" % DOC_NAME, headers=self.headers()
        )
        self.assertEqual(response.status, 200)
        self.assertEqual((await response.json())["status"], "done")

    async def test_patch_braucht_token(self):
        response = await self.client.patch(
            "/api/cad/documents/%s/objects/Box" % DOC_NAME, json={"Length": "1 mm"}
        )
        self.assertEqual(response.status, 401)


if __name__ == "__main__":
    unittest.main()
