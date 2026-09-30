"""M2: Reading -- property reflection, tree, batch route, routes.

The tests build a real document with the types on which a generic
serializer tends to break in practice: Quantity, Placement, Link, Shape,
Spreadsheet, PartDesign Body with origin infrastructure.
"""

import unittest

import FreeCAD
from aiohttp.test_utils import AioHTTPTestCase

from cad_contract import types
from freecad_bridge import objects, properties, server, snapshot, tree
from freecad_bridge import state as bridge_state

DOC_NAME = "ReadTestDoc"
TOKEN = "read-test-token"


def build_fixture_document():
    """A document with the critical types."""
    doc = FreeCAD.newDocument(DOC_NAME)
    doc.UndoMode = 1

    box = doc.addObject("Part::Box", "Box")
    box.Length = 30
    box.Width = 20
    box.Height = 10
    # Deliberately a label that matches the NAME of another object --
    # exactly the mix-up that would silently patch the wrong object.
    box.Label = "Zylinder"

    cylinder = doc.addObject("Part::Cylinder", "Zylinder")

    cut = doc.addObject("Part::Cut", "Schnitt")
    cut.Base = box
    cut.Tool = cylinder

    body = doc.addObject("PartDesign::Body", "Body")
    sketch = doc.addObject("Sketcher::SketchObject", "Skizze")
    body.addObject(sketch)

    sheet = doc.addObject("Spreadsheet::Sheet", "Sheet")
    sheet.set("A1", "42")
    sheet.setAlias("A1", "laenge")

    link = doc.addObject("App::Link", "Verweis")
    link.LinkedObject = box

    doc.recompute()
    return doc


def close_fixture_document():
    try:
        FreeCAD.closeDocument(DOC_NAME)
    except Exception:
        pass


class PropertyReflectionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        close_fixture_document()
        cls.doc = build_fixture_document()

    @classmethod
    def tearDownClass(cls):
        close_fixture_document()

    def entries(self, obj_name):
        obj = self.doc.getObject(obj_name)
        return {e["name"]: e for e in properties.describe_properties(obj)}

    def test_label_ist_schreibbar_trotz_output_flag(self):
        """getTypeOfProperty('Label') is ['Output'].

        The naive rule "skip Output" would lock out renaming.
        """
        entry = self.entries("Box")["Label"]
        self.assertIn("Output", entry["flags"])
        self.assertTrue(entry["writable"], "Label must be writable despite Output")

    def test_shape_wird_abgeleitet_nicht_serialisiert(self):
        entry = self.entries("Box")["Shape"]
        self.assertEqual(entry["status"], types.DERIVED)
        self.assertIsNone(entry["value"])
        self.assertFalse(entry["writable"])
        # Shape has status [] -- it could not be filtered via flags.
        self.assertEqual(entry["flags"], [])

    def test_quantity_traegt_symbol_und_groessenart(self):
        value = self.entries("Box")["Length"]["value"]
        self.assertEqual(value["kind"], types.QUANTITY)
        self.assertEqual(value["value"], 30.0)
        self.assertEqual(value["unit"], "mm")
        self.assertEqual(value["unitType"], "Length")
        self.assertNotIn("Unit:", value["unit"], "FreeCAD's repr does not belong on the wire")

    def test_placement_als_quaternion(self):
        """Rotation.Angle is in radians -- only .Q is lossless."""
        value = self.entries("Box")["Placement"]["value"]
        self.assertEqual(value["kind"], types.PLACEMENT)
        self.assertEqual(len(value["pos"]), 3)
        self.assertEqual(len(value["q"]), 4)

    def test_link_referenziert_ueber_name_nicht_label(self):
        value = self.entries("Schnitt")["Base"]["value"]
        self.assertEqual(value["kind"], types.LINK)
        self.assertEqual(value["ref"]["name"], "Box")
        self.assertEqual(value["ref"]["doc"], DOC_NAME)
        # The label of Box is "Zylinder" -- a label-based key
        # would point to the wrong object here.
        self.assertEqual(self.doc.getObject("Box").Label, "Zylinder")

    def test_gebundene_expression_sperrt_das_schreiben(self):
        box = self.doc.getObject("Box")
        box.setExpression("Height", "Sheet.laenge")
        self.doc.recompute()
        try:
            entry = self.entries("Box")["Height"]
            self.assertEqual(entry["expression"], "Sheet.laenge")
            self.assertFalse(
                entry["writable"],
                "A literal write would be discarded on the next recompute",
            )
        finally:
            box.clearExpression("Height")
            self.doc.recompute()

    def test_spreadsheet_zellen_bleiben_draussen(self):
        names = properties.property_names(self.doc.getObject("Sheet"))
        self.assertNotIn("A1", names)
        self.assertIn("Label", names)

    def test_interne_properties_gefiltert(self):
        box = self.doc.getObject("Box")
        names = properties.property_names(box)
        self.assertNotIn("_ElementMapVersion", names)
        self.assertIn("_ElementMapVersion", list(box.PropertiesList))

    def test_kein_str_fallback(self):
        """Every property is either encoded, derived or honestly unsupported."""
        for obj in self.doc.Objects:
            for entry in properties.describe_properties(obj):
                self.assertIn(
                    entry["status"],
                    (types.ENCODED, types.DERIVED, types.UNSUPPORTED),
                    "%s.%s has an unknown status" % (obj.Name, entry["name"]),
                )
                if entry["status"] == types.UNSUPPORTED:
                    self.assertEqual(entry["value"]["kind"], types.UNSUPPORTED)
                    self.assertIn("typeId", entry["value"])


class GeometryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        close_fixture_document()
        cls.doc = build_fixture_document()

    @classmethod
    def tearDownClass(cls):
        close_fixture_document()

    def test_geometrie_nur_auf_anforderung(self):
        """Shape.Volume costs on EVERY call -- FreeCAD does not cache it."""
        box = self.doc.getObject("Box")
        self.assertNotIn("geometry", objects.describe_object(box))
        self.assertIn("geometry", objects.describe_object(box, include_geometry=True))

    def test_geometriewerte_stimmen(self):
        box = self.doc.getObject("Box")
        geometry = objects.describe_object(box, include_geometry=True)["geometry"]
        self.assertAlmostEqual(geometry["volume"], 6000.0, places=6)
        self.assertEqual(geometry["shapeType"], "Solid")
        self.assertEqual(geometry["boundBox"]["lengths"], [30.0, 20.0, 10.0])
        self.assertTrue(geometry["valid"])

    def test_objekt_ohne_shape_liefert_none(self):
        geometry = objects.describe_geometry(self.doc.getObject("Sheet"))
        self.assertIsNone(geometry)


class TreeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        close_fixture_document()
        cls.doc = build_fixture_document()

    @classmethod
    def tearDownClass(cls):
        close_fixture_document()

    def test_origin_infrastruktur_wird_versteckt(self):
        """A Body brings 9 origin objects along; 200 Bodies would be 1800."""
        result = tree.build_tree(DOC_NAME)
        self.assertGreater(result["hiddenInternal"], 0)
        for node in result["nodes"].values():
            self.assertFalse(node["internal"])

    def test_include_internal_zeigt_sie_wieder(self):
        without = tree.build_tree(DOC_NAME)
        with_internal = tree.build_tree(DOC_NAME, include_internal=True)
        self.assertGreater(len(with_internal["nodes"]), len(without["nodes"]))

    def test_kein_objekt_geht_verloren(self):
        """The reconciliation against doc.Objects is the reason for the root building."""
        result = tree.build_tree(DOC_NAME, include_internal=True)
        self.assertEqual(len(result["nodes"]), len(self.doc.Objects))

    def test_kanten_zeigen_nur_auf_vorhandene_knoten(self):
        result = tree.build_tree(DOC_NAME)
        known = set(result["nodes"])
        for name, node in result["nodes"].items():
            for child in node["children"]:
                self.assertIn(child, known, "%s -> %s" % (name, child))
            for dep in node["deps"]:
                self.assertIn(dep, known, "%s -> %s" % (name, dep))

    def test_deps_bilden_die_abhaengigkeit_ab(self):
        """deps is needed by the later impact analysis."""
        result = tree.build_tree(DOC_NAME)
        self.assertEqual(sorted(result["nodes"]["Schnitt"]["deps"]), ["Box", "Zylinder"])

    def test_gui_genauigkeit_wird_gemeldet(self):
        """Headless there is no claimChildren -- the UI needs to know that."""
        result = tree.build_tree(DOC_NAME)
        self.assertIn("guiAccurate", result)
        self.assertFalse(result["guiAccurate"], "without a GUI the tree cannot be exact")

    def test_keine_selbstbezuege(self):
        result = tree.build_tree(DOC_NAME, include_internal=True)
        for name, node in result["nodes"].items():
            self.assertNotIn(name, node["children"])


class BatchAndTypesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        close_fixture_document()
        cls.doc = build_fixture_document()

    @classmethod
    def tearDownClass(cls):
        close_fixture_document()

    def test_fields_begrenzt_die_antwort(self):
        result = objects.list_objects(DOC_NAME, names=["Box"], fields=["Length", "Label"])
        names = [p["name"] for p in result["objects"][0]["properties"]]
        self.assertEqual(sorted(names), ["Label", "Length"])

    def test_fehlende_objekte_werden_gemeldet_nicht_verschwiegen(self):
        result = objects.list_objects(DOC_NAME, names=["Box", "GibtsNicht"])
        self.assertEqual(result["missing"], ["GibtsNicht"])
        self.assertEqual(len(result["objects"]), 1)

    def test_unbekanntes_objekt_nennt_die_name_label_falle(self):
        with self.assertRaises(objects.ObjectNotFound) as ctx:
            objects.get_object(DOC_NAME, "Gehaeuse")
        self.assertIn("Label", str(ctx.exception))

    def test_gefaehrliche_typen_sind_gesperrt(self):
        result = objects.list_types()
        self.assertTrue(result["types"])
        for name in result["types"]:
            self.assertNotIn("FeaturePython", name)
        self.assertNotIn("App::DocumentObjectFileIncluded", result["types"])


class ReadRoutesTest(AioHTTPTestCase):
    async def get_application(self):
        close_fixture_document()
        self.doc = build_fixture_document()
        state = bridge_state.get_state()
        state.token = TOKEN
        state.session_id = "read-routes"
        state.running = True
        snapshot.refresh()
        return server.create_app()

    async def tearDownAsync(self):
        close_fixture_document()
        await super().tearDownAsync()

    @property
    def headers(self):
        return {"Authorization": "Bearer " + TOKEN}

    async def get_json(self, path, expected=200):
        response = await self.client.get(path, headers=self.headers)
        self.assertEqual(response.status, expected, path)
        return await response.json()

    async def test_dokumentliste(self):
        data = await self.get_json("/api/cad/documents")
        names = [d["name"] for d in data["documents"]]
        self.assertIn(DOC_NAME, names)

    async def test_baumroute(self):
        data = await self.get_json("/api/cad/documents/%s/tree" % DOC_NAME)
        self.assertIn("Box", data["nodes"])
        self.assertIn("roots", data)

    async def test_batchroute_mit_feldern(self):
        data = await self.get_json(
            "/api/cad/documents/%s/objects?names=Box,Zylinder&fields=Label" % DOC_NAME
        )
        self.assertEqual(len(data["objects"]), 2)
        for entry in data["objects"]:
            self.assertEqual([p["name"] for p in entry["properties"]], ["Label"])

    async def test_detailroute_ohne_geometrie(self):
        data = await self.get_json("/api/cad/documents/%s/objects/Box" % DOC_NAME)
        self.assertEqual(data["name"], "Box")
        self.assertNotIn("geometry", data)

    async def test_detailroute_mit_geometrie(self):
        data = await self.get_json(
            "/api/cad/documents/%s/objects/Box?include=geometry" % DOC_NAME
        )
        self.assertAlmostEqual(data["geometry"]["volume"], 6000.0, places=6)

    async def test_unbekanntes_dokument_meldet_doc_not_open(self):
        response = await self.client.get(
            "/api/cad/documents/GibtsNicht/tree", headers=self.headers
        )
        self.assertEqual(response.status, 404)
        body = await response.json()
        self.assertEqual(body["error"]["code"], "doc_not_open")

    async def test_unbekanntes_objekt_meldet_object_not_found(self):
        response = await self.client.get(
            "/api/cad/documents/%s/objects/Nixda" % DOC_NAME, headers=self.headers
        )
        self.assertEqual(response.status, 404)
        body = await response.json()
        self.assertEqual(body["error"]["code"], "object_not_found")

    async def test_typenroute(self):
        data = await self.get_json("/api/cad/types")
        self.assertIn("Part::Box", data["types"])

    async def test_auswahl_ohne_gui(self):
        """Headless, selection is cleanly unavailable instead of raising."""
        data = await self.get_json("/api/cad/selection")
        self.assertFalse(data["available"])
        self.assertEqual(data["selection"], [])

    async def test_auswahl_setzen_ohne_gui_ist_409(self):
        response = await self.client.put(
            "/api/cad/selection",
            headers=self.headers,
            json={"refs": [{"doc": DOC_NAME, "name": "Box"}]},
        )
        self.assertEqual(response.status, 409)
        body = await response.json()
        self.assertEqual(body["error"]["code"], "no_gui")

    async def test_leseroute_braucht_token(self):
        response = await self.client.get("/api/cad/documents")
        self.assertEqual(response.status, 401)


if __name__ == "__main__":
    unittest.main()
