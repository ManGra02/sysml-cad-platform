"""M8: Vorgaenge -- mehrere Aenderungen als ein Undo-Schritt, alles oder nichts.

Die Operationen, die ein Projektmodul (BDS) programmatisch braucht: anlegen,
loeschen, Properties setzen, Formeln binden, Tabellenzellen, eigene Properties.
"""

import os
import tempfile
import unittest

import FreeCAD
from aiohttp.test_utils import AioHTTPTestCase

from freecad_bridge import observer, operations, revisions, server, snapshot, writes
from freecad_bridge import state as bridge_state
from freecad_bridge.dispatch import BridgeError

DOC_NAME = "OpsTestDoc"
TOKEN = "ops-test-token"


def build_document():
    try:
        FreeCAD.closeDocument(DOC_NAME)
    except Exception:
        pass
    doc = FreeCAD.newDocument(DOC_NAME)
    doc.UndoMode = 1
    doc.addObject("App::DocumentObjectGroup", "Antrieb")
    box = doc.addObject("Part::Box", "Box")
    cylinder = doc.addObject("Part::Cylinder", "Zylinder")
    cut = doc.addObject("Part::Cut", "Schnitt")
    cut.Base, cut.Tool = box, cylinder
    doc.addObject("Spreadsheet::Sheet", "Params")
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


def run(ops, **kw):
    return operations.run(DOC_NAME, ops, **kw)


class OperationsTest(unittest.TestCase):
    def setUp(self):
        self.doc = build_document()

    def tearDown(self):
        close_document()

    def names(self):
        return sorted(o.Name for o in self.doc.Objects)

    # -- Der BDS-Fall in einem Vorgang ---------------------------------------

    def test_teil_mit_sysml_id_und_formel_in_einem_vorgang(self):
        result = run(
            [
                {"op": "set_cells", "sheet": "Params", "cells": {"A1": "40 mm"}, "aliases": {"A1": "motor_laenge"}},
                {"op": "create", "type": "Part::Box", "name": "Motor", "label": "Motor",
                 "group": "Antrieb", "props": {"Width": "12 mm"}, "as": "m"},
                {"op": "add_property", "obj": "$m", "type": "App::PropertyString", "name": "SysMLId",
                 "group": "SysML", "value": "a1b2-c3"},
                {"op": "set_expression", "obj": "$m", "prop": "Length", "expr": "Params.motor_laenge"},
            ],
            name="BDS: Motor anlegen",
        )
        motor = self.doc.getObject(result["created"]["m"])
        self.assertEqual(motor.Length.Value, 40.0)
        self.assertEqual(motor.Width.Value, 12.0)
        self.assertEqual(motor.SysMLId, "a1b2-c3")
        self.assertIn(motor, self.doc.getObject("Antrieb").Group)
        self.assertEqual(self.doc.UndoCount, 1)
        self.assertEqual(self.doc.UndoNames[0], "BDS: Motor anlegen")
        self.assertTrue(result["atomic"] and result["changed"])
        self.assertIn(motor.Name, result["revs"])

        # Die Bindung lebt in FreeCAD: Zelle aendern -> Laenge folgt.
        run([{"op": "set_cells", "sheet": "Params", "cells": {"A1": "55 mm"}}])
        self.assertEqual(motor.Length.Value, 55.0)

    def test_platzhalter_bei_namenskollision(self):
        result = run([{"op": "create", "type": "Part::Box", "name": "Box", "as": "b"},
                      {"op": "patch", "obj": "$b", "props": {"Height": "3 mm"}}])
        self.assertEqual(result["created"]["b"], "Box001")
        self.assertEqual(self.doc.getObject("Box001").Height.Value, 3.0)
        self.assertEqual(self.doc.getObject("Box").Height.Value, 10.0)

    # -- Alles oder nichts ---------------------------------------------------

    def test_fehler_nimmt_alles_zurueck_auch_angelegte_objekte(self):
        before = self.names()
        with self.assertRaises(BridgeError) as caught:
            run([
                {"op": "create", "type": "Part::Box", "name": "Neu", "as": "n"},
                {"op": "add_property", "obj": "$n", "type": "App::PropertyString", "name": "SysMLId"},
                {"op": "set_cells", "sheet": "Params", "cells": {"B2": "7"}},
                {"op": "patch", "obj": "Box", "props": {"Length": "3 kg"}},
            ])
        self.assertEqual(caught.exception.detail["failedOp"], 3)
        self.assertEqual(caught.exception.code, "invalid_value")
        self.assertEqual(self.names(), before)
        self.assertEqual(self.doc.getObject("Params").getUsedCells(), [])
        self.assertEqual(self.doc.UndoCount, 0)

    def test_loeschen_wird_zurueckgenommen(self):
        with self.assertRaises(BridgeError):
            run([{"op": "delete", "obj": "Schnitt"}, {"op": "patch", "obj": "Gibtsnicht", "props": {"x": 1}}])
        self.assertIsNotNone(self.doc.getObject("Schnitt"))

    def test_strict_formel_auf_unbekannten_alias(self):
        with self.assertRaises(BridgeError) as caught:
            run([{"op": "set_expression", "obj": "Box", "prop": "Length", "expr": "Params.gibtsnicht"}])
        self.assertEqual(caught.exception.code, "recompute_failed")
        self.assertEqual(self.doc.getObject("Box").ExpressionEngine, [])
        self.assertEqual(self.doc.UndoCount, 0)

    def test_ohne_strict_wird_der_fehler_nur_gemeldet(self):
        result = run([{"op": "set_expression", "obj": "Box", "prop": "Length", "expr": "Params.gibtsnicht"}],
                     strict=False)
        self.assertIn("Box", [e["name"] for e in result["errors"]])

    def test_vorher_fehlerhafte_objekte_blockieren_nicht(self):
        self.doc.getObject("Schnitt").Tool = None
        self.doc.recompute()
        self.doc.clearUndos()
        result = run([{"op": "patch", "obj": "Box", "props": {"Height": "4 mm"}}])
        self.assertTrue(result["changed"])

    # -- Loeschen ------------------------------------------------------------

    def test_loeschen_mit_abhaengigen_wird_abgewiesen(self):
        with self.assertRaises(BridgeError) as caught:
            run([{"op": "delete", "obj": "Box"}])
        self.assertEqual(caught.exception.code, "has_dependents")
        self.assertEqual(caught.exception.http_status, 409)
        self.assertEqual([d["name"] for d in caught.exception.detail["detail"]["dependents"]], ["Schnitt"])
        self.assertIsNotNone(self.doc.getObject("Box"))

    def test_loeschen_mit_force(self):
        result = run([{"op": "delete", "obj": "Box", "force": True}], strict=False)
        self.assertIsNone(self.doc.getObject("Box"))
        self.assertEqual(result["results"][0]["brokenDependents"], ["Schnitt"])

    def test_gruppenmitgliedschaft_zaehlt_nicht_als_abhaengigkeit(self):
        run([{"op": "create", "type": "Part::Sphere", "name": "Kugel", "group": "Antrieb"}])
        run([{"op": "delete", "obj": "Kugel"}])
        self.assertIsNone(self.doc.getObject("Kugel"))

    # -- Formeln und Tabellen ------------------------------------------------

    def test_formel_entfernen(self):
        run([{"op": "set_cells", "sheet": "Params", "cells": {"A1": "20 mm"}, "aliases": {"A1": "lang"}},
             {"op": "set_expression", "obj": "Box", "prop": "Length", "expr": "Params.lang"}])
        run([{"op": "set_expression", "obj": "Box", "prop": "Length", "expr": None}])
        self.assertEqual(self.doc.getObject("Box").ExpressionEngine, [])

    def test_syntaxfehler_in_formel(self):
        with self.assertRaises(BridgeError) as caught:
            run([{"op": "set_expression", "obj": "Box", "prop": "Length", "expr": "Params.l +"}])
        self.assertEqual(caught.exception.code, "invalid_expression")

    def test_zu_lange_formel(self):
        with self.assertRaises(BridgeError):
            run([{"op": "set_expression", "obj": "Box", "prop": "Length", "expr": "1" * 3000}])

    def test_zellen_lesen(self):
        run([{"op": "set_cells", "sheet": "Params", "cells": {"A1": "40 mm", "B3": "Motor", "C9": "2"},
              "aliases": {"A1": "laenge"}}])
        data = operations.read_cells(DOC_NAME, "Params", "A1:B5")
        self.assertEqual(sorted(data["cells"]), ["A1", "B3"])
        self.assertEqual(data["cells"]["A1"]["alias"], "laenge")
        self.assertEqual(data["cells"]["A1"]["value"]["value"], 40.0)
        self.assertEqual(data["cells"]["B3"]["value"], "Motor")
        self.assertEqual(sorted(operations.read_cells(DOC_NAME, "Params")["cells"]), ["A1", "B3", "C9"])

    def test_zelle_leeren_und_alias_entfernen(self):
        run([{"op": "set_cells", "sheet": "Params", "cells": {"A1": "1"}, "aliases": {"A1": "x"}}])
        run([{"op": "set_cells", "sheet": "Params", "cells": {"A1": None}, "aliases": {"A1": None}}])
        self.assertEqual(operations.read_cells(DOC_NAME, "Params")["cells"], {})

    def test_ungueltige_zelle_und_alias(self):
        for op in (
            {"op": "set_cells", "sheet": "Params", "cells": {"a1": "1"}},
            {"op": "set_cells", "sheet": "Params", "aliases": {"A1": "1abc"}},
            {"op": "set_cells", "sheet": "Box", "cells": {"A1": "1"}},
        ):
            with self.assertRaises(BridgeError):
                run([op])

    def test_bereich_parsen(self):
        self.assertEqual(operations.parse_range("B2:A1"), ((1, 1), (2, 2)))
        self.assertEqual(operations.parse_range("AA10"), ((27, 10), (27, 10)))
        with self.assertRaises(BridgeError):
            operations.parse_range("A1:B2:C3")

    # -- Eigene Properties ---------------------------------------------------

    def test_eigene_properties_und_entfernen(self):
        run([{"op": "add_property", "obj": "Box", "type": "App::PropertyStringList", "name": "Tags",
              "value": ["a", "b"]},
             {"op": "add_property", "obj": "Box", "type": "App::PropertyLength", "name": "Budget",
              "value": "80 mm"}])
        box = self.doc.getObject("Box")
        self.assertEqual(box.Tags, ["a", "b"])
        self.assertEqual(box.Budget.Value, 80.0)
        run([{"op": "remove_property", "obj": "Box", "name": "Tags"}])
        self.assertNotIn("Tags", box.PropertiesList)

    def test_eingebaute_property_ist_nicht_entfernbar(self):
        with self.assertRaises(BridgeError) as caught:
            run([{"op": "remove_property", "obj": "Box", "name": "Length"}])
        self.assertEqual(caught.exception.code, "not_dynamic")

    def test_property_typ_und_name_werden_geprueft(self):
        for op in (
            {"op": "add_property", "obj": "Box", "type": "App::PropertyPythonObject", "name": "X"},
            {"op": "add_property", "obj": "Box", "type": "App::PropertyString", "name": "1x"},
            {"op": "add_property", "obj": "Box", "type": "App::PropertyString", "name": "Length"},
        ):
            with self.assertRaises(BridgeError):
                run([op])

    def test_eigene_property_ueberlebt_speichern_und_laden(self):
        run([{"op": "add_property", "obj": "Box", "type": "App::PropertyString", "name": "SysMLId",
              "value": "elem-42"}])
        path = os.path.join(tempfile.mkdtemp(), "ops.FCStd")
        self.doc.saveAs(path)
        FreeCAD.closeDocument(self.doc.Name)
        reopened = FreeCAD.openDocument(path)
        try:
            self.assertEqual(reopened.getObject("Box").SysMLId, "elem-42")
        finally:
            FreeCAD.closeDocument(reopened.Name)

    # -- Anlegen: Grenzen ----------------------------------------------------

    def test_gesperrte_und_unbekannte_typen(self):
        with self.assertRaises(BridgeError) as caught:
            run([{"op": "create", "type": "Part::FeaturePython"}])
        self.assertEqual(caught.exception.code, "type_not_allowed")
        with self.assertRaises(BridgeError):
            run([{"op": "create", "type": "Gibts::Nicht"}])

    def test_gruppe_muss_container_sein(self):
        with self.assertRaises(BridgeError):
            run([{"op": "create", "type": "Part::Box", "group": "Box"}])

    # -- Vorgang als Ganzes --------------------------------------------------

    def test_eingaben_werden_vorab_geprueft(self):
        for ops in ([], "x", [{"op": "zaubern"}], [{"op": "patch", "as": "p", "obj": "Box", "props": {}}],
                    [{"op": "create", "type": "Part::Box", "as": "a"}, {"op": "create", "type": "Part::Box", "as": "a"}],
                    [{"op": "patch", "obj": "$nie", "props": {"Height": 1}}]):
            with self.assertRaises(BridgeError):
                run(ops)
        self.assertEqual(self.doc.UndoCount, 0)

    def test_if_match_im_vorgang(self):
        writes.patch_object(DOC_NAME, "Box", {"Height": "5 mm"})  # rev 0 -> 1
        with self.assertRaises(BridgeError) as caught:
            run([{"op": "patch", "obj": "Box", "props": {"Height": "6 mm"}, "if_match": 0}])
        self.assertEqual(caught.exception.code, "rev_mismatch")

    def test_gleiche_request_id_fuehrt_nicht_zweimal_aus(self):
        ops = [{"op": "create", "type": "Part::Box", "name": "Einmal"}]
        first = run(ops, request_id="op-1")
        again = run(ops, request_id="op-1")
        self.assertTrue(again["replayed"])
        self.assertEqual(first["created"], again["created"])
        self.assertEqual(len([o for o in self.doc.Objects if o.Name.startswith("Einmal")]), 1)

    def test_ein_undo_nimmt_den_ganzen_vorgang_zurueck(self):
        run([{"op": "create", "type": "Part::Box", "name": "A"},
             {"op": "create", "type": "Part::Box", "name": "B"},
             {"op": "patch", "obj": "Box", "props": {"Height": "7 mm"}}])
        self.doc.undo()
        self.assertIsNone(self.doc.getObject("A"))
        self.assertIsNone(self.doc.getObject("B"))
        self.assertEqual(self.doc.getObject("Box").Height.Value, 10.0)


class OperationEventsTest(unittest.TestCase):
    """Die Ereignisse eines Vorgangs tragen seine Herkunft -- Grundlage fuer is_own."""

    def setUp(self):
        self.doc = build_document()
        self.published = []
        state = bridge_state.get_state()
        state.hub = None
        observer.install(state, self.published.extend)

    def tearDown(self):
        observer.uninstall(bridge_state.get_state())
        close_document()

    def test_herkunft_und_rev(self):
        result = run([{"op": "create", "type": "Part::Box", "name": "Neu", "as": "n"},
                      {"op": "add_property", "obj": "$n", "type": "App::PropertyString", "name": "SysMLId"}],
                     request_id="vorgang-7")
        created = [e for e in self.published if e["type"] == "cad.created" and e["obj"] == result["created"]["n"]]
        self.assertTrue(created)
        self.assertEqual(created[0]["origin"], "bridge:vorgang-7")
        self.assertEqual(result["revs"][result["created"]["n"]], revisions.current(DOC_NAME, result["created"]["n"]))


class OperationRoutesTest(AioHTTPTestCase):
    async def get_application(self):
        self.doc = build_document()
        state = bridge_state.get_state()
        state.token = TOKEN
        state.session_id = "ops-routes"
        state.running = True
        snapshot.refresh()
        return server.create_app()

    async def tearDownAsync(self):
        close_document()
        await super().tearDownAsync()

    def headers(self):
        return {"Authorization": "Bearer " + TOKEN, "X-Request-Id": "route-1"}

    async def test_vorgang_ueber_http(self):
        response = await self.client.post(
            "/api/cad/documents/%s/operations" % DOC_NAME,
            headers=self.headers(),
            json={"name": "HTTP", "ops": [{"op": "create", "type": "Part::Box", "name": "Http", "as": "h"}]},
        )
        self.assertEqual(response.status, 200)
        self.assertEqual((await response.json())["created"]["h"], "Http")

    async def test_fehler_nennt_die_operation(self):
        response = await self.client.post(
            "/api/cad/documents/%s/operations" % DOC_NAME,
            headers=self.headers(),
            json={"ops": [{"op": "create", "type": "Part::Box"}, {"op": "delete", "obj": "Box"}]},
        )
        self.assertEqual(response.status, 409)
        error = (await response.json())["error"]
        self.assertEqual(error["code"], "has_dependents")
        self.assertEqual(error["detail"]["failedOp"], 1)
        self.assertEqual(error["request_id"], "route-1")

    async def test_zellen_ueber_http(self):
        operations.run(DOC_NAME, [{"op": "set_cells", "sheet": "Params", "cells": {"A1": "5"}}])
        response = await self.client.get(
            "/api/cad/documents/%s/sheets/Params/cells?range=A1:A5" % DOC_NAME, headers=self.headers()
        )
        self.assertEqual(response.status, 200)
        self.assertIn("A1", (await response.json())["cells"])

    async def test_kein_json(self):
        response = await self.client.post(
            "/api/cad/documents/%s/operations" % DOC_NAME, headers=self.headers(), data=b"nix"
        )
        self.assertEqual(response.status, 400)


if __name__ == "__main__":
    unittest.main()
