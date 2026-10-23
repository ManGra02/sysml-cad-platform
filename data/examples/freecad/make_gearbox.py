"""Builds gearbox.FCStd: the CAD side of data/examples/sysml/bds/gearbox.json.

The two-part reference assembly from the bidirectional-sync PoC (cad/gearbox.py),
rebuilt parametrically in FreeCAD so a change in the model shows up in a BDS
verification:

    Gearbox (App::Part, the assembly)
      Housing (PartDesign Body)  box 90 x 60 x 40 mm with a bore of radius 8 mm
      Cover   (PartDesign Body)  box 90 x 60 x 6 mm on top, same bore
    Params (Spreadsheet)         HousingLength, HousingWidth, HousingHeight,
                                 CoverThickness, BoreRadius -- every dimension
                                 above is an expression on one of these aliases

Both bodies carry the material Aluminum-Generic (2.70 g/cm^3, the density the PoC
uses for AlSi10Mg, which FreeCAD's library does not have).

Run from the repository root:

    "<FreeCAD>/bin/freecadcmd.exe" data/examples/freecad/make_gearbox.py

It writes data/examples/freecad/gearbox.FCStd next to this file.
"""

import os

import FreeCAD as App
import Materials

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "gearbox.FCStd")

PARAMS = [
    ("HousingLength", "90 mm"),
    ("HousingWidth", "60 mm"),
    ("HousingHeight", "40 mm"),
    ("CoverThickness", "6 mm"),
    ("BoreRadius", "8 mm"),
]
MATERIAL = "Aluminum-Generic"


def material(name):
    manager = Materials.MaterialManager()
    for found in manager.Materials.values():
        if found.Name == name:
            return found
    raise SystemExit("material %r not found in the FreeCAD library" % name)


def body(doc, name, thickness, z):
    """A box with a centred through-bore; ``thickness`` and ``z`` are expressions."""
    part = doc.addObject("PartDesign::Body", name)
    box = doc.addObject("PartDesign::AdditiveBox", name + "Box")
    part.addObject(box)
    box.setExpression("Length", "Params.HousingLength")
    box.setExpression("Width", "Params.HousingWidth")
    box.setExpression("Height", thickness)
    box.setExpression(".Placement.Base.z", z)

    bore = doc.addObject("PartDesign::SubtractiveCylinder", name + "Bore")
    part.addObject(bore)
    bore.setExpression("Radius", "Params.BoreRadius")
    bore.setExpression("Height", thickness)
    bore.setExpression(".Placement.Base.x", "Params.HousingLength / 2")
    bore.setExpression(".Placement.Base.y", "Params.HousingWidth / 2")
    bore.setExpression(".Placement.Base.z", z)
    return part


def main():
    doc = App.newDocument("Gearbox")

    sheet = doc.addObject("Spreadsheet::Sheet", "Params")
    for row, (alias, value) in enumerate(PARAMS, start=1):
        sheet.set("A%d" % row, alias)
        sheet.set("B%d" % row, "=" + value)
        sheet.setAlias("B%d" % row, alias)
    doc.recompute()

    housing = body(doc, "Housing", "Params.HousingHeight", "0 mm")
    cover = body(doc, "Cover", "Params.CoverThickness", "Params.HousingHeight")

    alu = material(MATERIAL)
    for part in (housing, cover):
        part.ShapeMaterial = alu

    assembly = doc.addObject("App::Part", "Gearbox")
    assembly.addObject(housing)
    assembly.addObject(cover)

    doc.recompute()
    broken = [o.Name for o in doc.Objects if "Invalid" in o.State or "Touched" in o.State]
    if broken:
        raise SystemExit("recompute left objects broken: %s" % ", ".join(broken))

    doc.saveAs(OUT)
    for part in (housing, cover):
        box = part.Shape.BoundBox
        mass = part.Shape.Volume * alu.getPhysicalValue("Density").Value
        print("%-8s %.1f x %.1f x %.1f mm, %.3f kg" % (part.Name, box.XLength, box.YLength, box.ZLength, mass))
    print("saved", OUT)


main()
