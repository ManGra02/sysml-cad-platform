"""M8 acceptance: a project module works programmatically on the real CAD model.

    cd backend
    uv run python ../scripts/e2e/m8_acceptance.py

The BDS case: create a parameter spreadsheet, a part with a SysML ID
and a formula binding in ONE operation. Afterwards: change a cell -> length follows,
echo recognized as our own, delete with dependents rejected, an error rolls
everything back.

Prerequisites as for M5: ports 8000 and 8765 free, FreeCAD 1.1 installed.
"""

import asyncio
import os
import sys

import uvicorn

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(HERE)), "backend"))

from m5_acceptance import DOC, FreeCADProcess, check, results, wait_for  # noqa: E402

from app.main import create_app  # noqa: E402
from app.projects.base import CadError, ProjectModule  # noqa: E402


class AcceptanceModule(ProjectModule):
    id = "e2e"
    title = "Abnahme"

    def __init__(self):
        self.events = []

    async def on_cad_event(self, event):
        self.events.append((event, self.ctx.cad.is_own(event)))


async def main():
    freecad = FreeCADProcess()
    app = create_app(project_modules=[AcceptanceModule])
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=8000, log_level="warning", lifespan="on"))
    server_task = asyncio.create_task(server.serve())
    await wait_for(lambda: server.started)

    registry = app.state.registry
    module = registry.modules["e2e"]
    cad = module.ctx.cad
    try:
        print("\n[1] FreeCAD, bridge, document")
        await freecad.run("start")
        await freecad.run("newdoc")
        await registry.activate("e2e")
        ok = await wait_for(lambda: app.state.bridge.state == "ok")
        check("Backend connected to the bridge", ok)

        print("\n[2] BDS case in ONE operation")
        async with cad.transaction(DOC, "BDS: Motor anlegen") as tx:
            tx.create("Spreadsheet::Sheet", name="Params")
            tx.set_cells("Params", {"A1": "40 mm"}, aliases={"A1": "motor_laenge"})
            group = tx.create("App::DocumentObjectGroup", name="Antrieb")
            motor = tx.create("Part::Box", name="Motor", group=group, props={"Width": "12 mm"})
            tx.add_property(motor, "App::PropertyString", "SysMLId", value="elem-42", group="SysML")
            tx.set_expression(motor, "Length", "Params.motor_laenge")
        name = tx.result.name(motor)
        check("Operation atomic", tx.result.atomic, tx.result.created)

        detail = await cad.object(DOC, name)
        props = {p["name"]: p for p in detail["properties"]}
        check("SysML ID on the part", props["SysMLId"]["value"] == "elem-42")
        check("Length comes from the spreadsheet", props["Length"]["value"]["value"] == 40.0,
              props["Length"]["expression"])
        docs = await cad.documents()
        undo = [d for d in docs["documents"] if d["name"] == DOC][0]
        check("exactly one undo step", undo["undoNames"][:1] == ["BDS: Motor anlegen"], undo["undoNames"])

        print("\n[3] Change parameter -> geometry follows")
        await cad.set_cells(DOC, "Params", {"A1": "55 mm"})
        detail = await cad.object(DOC, name)
        length = [p for p in detail["properties"] if p["name"] == "Length"][0]["value"]["value"]
        check("Length follows the cell", length == 55.0, length)
        cells = await cad.cells(DOC, "Params")
        check("Cell readable with alias", cells["cells"]["A1"]["alias"] == "motor_laenge")

        print("\n[4] Echo recognized")
        got = await wait_for(lambda: any(e["type"] == "cad.created" and e.get("obj") == name
                                         for e, _ in module.events))
        own = [is_own for e, is_own in module.events if e.get("obj") == name]
        check("Events of our own operation recognized as own", got and own and all(own), own[:3])
        await freecad.run("set Box Length 20")
        foreign = await wait_for(lambda: any(e.get("obj") == "Box" and not is_own for e, is_own in module.events))
        check("Change in FreeCAD is foreign", foreign)

        print("\n[5] Protection and rollback")
        try:
            await cad.delete(DOC, "Params")
            check("Delete with dependents rejected", False)
        except CadError as exc:
            check("Delete with dependents rejected", exc.code == "has_dependents", exc.detail)

        before = len((await cad.tree(DOC))["nodes"])
        try:
            async with cad.transaction(DOC) as tx:
                tx.create("Part::Box", name="Wegwerf")
                tx.patch("Box", {"Length": "3 kg"})
            check("Error in operation reported", False)
        except CadError as exc:
            check("Error names the operation", exc.failed_op == 1, exc.code)
        after = len((await cad.tree(DOC))["nodes"])
        check("nothing created after error", before == after, "%d -> %d" % (before, after))
    finally:
        try:
            await freecad.run("quit", timeout=10)
        except Exception:
            freecad.kill()
        server.should_exit = True
        await server_task

    failed = [n for n, ok in results if not ok]
    print("\n===== %d OK, %d FAIL =====" % (len(results) - len(failed), len(failed)))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
