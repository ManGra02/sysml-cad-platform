import { describe, expect, it } from "vitest"

import { formatNumber, formatValue, parseNumber, sameValue } from "./format"
import { axisAngleToQuat, quatToAxisAngle } from "./rotation"
import { beginOwnRequest, endOwnRequest, isOwnOrigin, planInvalidation } from "./sync"
import { ancestorKeys, findPath, flattenTree, pathKey, searchTree } from "./tree"
import type { Tree, TreeNode } from "./types"

function node(name: string, children: string[] = [], extra: Partial<TreeNode> = {}): TreeNode {
  return {
    doc: "D",
    name,
    label: extra.label ?? name,
    typeId: "Part::Feature",
    id: null,
    internal: false,
    visible: true,
    state: [],
    rev: 0,
    children,
    deps: [],
    childSource: "claimChildren",
    ...extra,
  }
}

function makeTree(nodes: TreeNode[], roots: string[]): Tree {
  return {
    doc: "D",
    roots,
    nodes: Object.fromEntries(nodes.map((n) => [n.name, n])),
    objectCount: nodes.length,
    hiddenInternal: 0,
    guiAccurate: true,
  }
}

describe("Baum", () => {
  // Body -> Pad -> Sketch, und Sketch haengt zusaetzlich an einem zweiten Pad (DAG)
  const tree = makeTree(
    [node("Body", ["Pad", "Pad001"]), node("Pad", ["Sketch"]), node("Pad001", ["Sketch"]), node("Sketch"), node("Loose")],
    ["Body", "Loose"],
  )

  it("zeigt zugeklappt nur die Wurzeln", () => {
    expect(flattenTree(tree, new Set()).map((r) => r.name)).toEqual(["Body", "Loose"])
  })

  it("ein Objekt darf mehrfach erscheinen -- Schluessel ist der Pfad", () => {
    const expanded = new Set([pathKey(["Body"]), pathKey(["Body", "Pad"]), pathKey(["Body", "Pad001"])])
    const rows = flattenTree(tree, expanded)
    const sketches = rows.filter((r) => r.name === "Sketch")
    expect(sketches).toHaveLength(2)
    expect(new Set(rows.map((r) => r.key)).size).toBe(rows.length)
    expect(sketches[0].depth).toBe(2)
  })

  it("Zyklen haengen den Aufbau nicht auf", () => {
    const cyclic = makeTree([node("A", ["B"]), node("B", ["A"])], ["A"])
    const expanded = new Set([pathKey(["A"]), pathKey(["A", "B"]), pathKey(["A", "B", "A"])])
    const rows = flattenTree(cyclic, expanded)
    expect(rows.map((r) => r.name)).toEqual(["A", "B", "A"])
    expect(rows[2].cycle).toBe(true)
    expect(rows[2].hasChildren).toBe(false)
  })

  it("Kanten auf ausgeblendete Objekte werden ignoriert", () => {
    const partial = makeTree([node("Body", ["Origin"])], ["Body"])
    expect(flattenTree(partial, new Set([pathKey(["Body"])]))[0].hasChildren).toBe(false)
  })

  it("findet den Pfad zu einem Objekt und die aufzuklappenden Vorfahren", () => {
    const path = findPath(tree, "Sketch")
    expect(path).toEqual(["Body", "Pad", "Sketch"])
    expect(ancestorKeys(path!)).toEqual([pathKey(["Body"]), pathKey(["Body", "Pad"])])
    expect(findPath(tree, "Gibtsnicht")).toBeNull()
  })

  it("Pfadschluessel sind eindeutig, auch wenn Namen Trenner enthalten", () => {
    expect(pathKey(["a/b"])).not.toBe(pathKey(["a", "b"]))
  })

  it("Suche trifft Label und Name, ohne Gross/Klein", () => {
    const labelled = makeTree([node("Box", [], { label: "Gehäuse" }), node("Zylinder")], ["Box", "Zylinder"])
    expect(searchTree(labelled, "gehä").map((r) => r.name)).toEqual(["Box"])
    expect(searchTree(labelled, "BOX").map((r) => r.name)).toEqual(["Box"])
    expect(searchTree(labelled, "  ")).toEqual([])
  })
})

describe("Ereignisse -> Invalidierung", () => {
  const never = () => false

  it("cad.changed laedt Objekt und Baum nach, nicht das ganze Dokument", () => {
    const plan = planInvalidation([{ type: "cad.changed", doc: "D", obj: "Box", props: ["Length"], origin: "freecad:user" }], never)
    expect(plan.objects).toEqual([["D", "Box"]])
    expect([...plan.trees]).toEqual(["D"])
    expect(plan.docs.size).toBe(0)
    expect(plan.all).toBe(false)
  })

  it("das Echo einer eigenen Mutation wird ignoriert", () => {
    const plan = planInvalidation(
      [{ type: "cad.changed", doc: "D", obj: "Box", origin: "bridge:mine" }],
      (origin) => origin === "bridge:mine",
    )
    expect(plan.objects).toEqual([])
    expect(plan.trees.size).toBe(0)
  })

  it("Undo verwirft das ganze Dokument statt inkrementell nachzuziehen", () => {
    const plan = planInvalidation(
      [
        { type: "cad.deleted", doc: "D", obj: "Box" },
        { type: "cad.history", doc: "D", action: "undo" },
      ],
      never,
    )
    expect([...plan.docs]).toEqual(["D"])
    expect(plan.documents).toBe(true)
  })

  it("ein neu angelegtes Objekt laedt auch seine Detailansicht nach", () => {
    const plan = planInvalidation([{ type: "cad.created", doc: "D", obj: "Kugel0" }], never)
    expect(plan.objects).toEqual([["D", "Kugel0"]])
    expect(plan.documents).toBe(true)
  })

  it("resync ohne Dokument laedt alles neu", () => {
    expect(planInvalidation([{ type: "cad.resync", reason: "overflow" }], never).all).toBe(true)
  })

  it("doc.modified betrifft nur die Dokumentliste", () => {
    const plan = planInvalidation([{ type: "doc.modified", doc: "D", dirty: true }], never)
    expect(plan.documents).toBe(true)
    expect(plan.objects).toEqual([])
    expect(plan.trees.size).toBe(0)
  })

  it("mehrfache Aenderungen am selben Objekt ergeben eine Invalidierung", () => {
    const plan = planInvalidation(
      [
        { type: "cad.changed", doc: "D", obj: "Box" },
        { type: "cad.changed", doc: "D", obj: "Box" },
      ],
      never,
    )
    expect(plan.objects).toHaveLength(1)
  })

  it("eigene Anfragen gelten nach der Antwort noch kurz als eigen", () => {
    beginOwnRequest("r1")
    expect(isOwnOrigin("bridge:r1")).toBe(true)
    endOwnRequest("r1", 1_000)
    expect(isOwnOrigin("bridge:r1", 2_000)).toBe(true)
    expect(isOwnOrigin("bridge:r1", 10_000)).toBe(false)
    expect(isOwnOrigin("freecad:user")).toBe(false)
    expect(isOwnOrigin("bridge:fremd")).toBe(false)
  })
})

describe("Drehung", () => {
  it("Rundreise Achse/Winkel <-> Quaternion", () => {
    const q = axisAngleToQuat([0, 0, 1], 90)
    const { axis, angle } = quatToAxisAngle(q)
    expect(angle).toBeCloseTo(90)
    expect(axis[2]).toBeCloseTo(1)
  })

  it("keine Drehung ist Winkel 0 um z", () => {
    expect(quatToAxisAngle([0, 0, 0, 1])).toEqual({ axis: [0, 0, 1], angle: 0 })
  })

  it("Achse wird normiert", () => {
    const q = axisAngleToQuat([0, 0, 5], 180)
    expect(Math.hypot(...q)).toBeCloseTo(1)
  })

  it("Achse (0,0,0) mit Winkel ist ein Fehler", () => {
    expect(() => axisAngleToQuat([0, 0, 0], 30)).toThrow()
  })
})

describe("Formatierung", () => {
  it("kein Float-Rauschen", () => {
    expect(formatNumber(0.1 + 0.2)).toBe("0.3")
    expect(formatNumber(-0.0000000001)).toBe("0")
  })

  it("Komma als Dezimaltrenner, Unsinn wird abgelehnt", () => {
    expect(parseNumber("12,5")).toBe(12.5)
    expect(parseNumber(" -3e2 ")).toBe(-300)
    expect(parseNumber("12 mm")).toBeNull()
    expect(parseNumber("")).toBeNull()
  })

  it("Quantity zeigt den verlustfreien Text", () => {
    expect(formatValue({ kind: "quantity", value: 10, unit: "mm", unitType: "Length", text: "10 mm" })).toBe("10 mm")
  })

  it("Link zeigt Label und Name", () => {
    expect(formatValue({ kind: "link", ref: { doc: "D", name: "Box" } }, { Box: "Gehäuse" })).toBe("Gehäuse (Box)")
  })

  it("Strukturgleichheit", () => {
    expect(sameValue({ kind: "vector", x: 1, y: 2, z: 3 }, { kind: "vector", x: 1, y: 2, z: 3 })).toBe(true)
    expect(sameValue({ a: [1, 2] }, { a: [1, 3] })).toBe(false)
    expect(sameValue(null, {})).toBe(false)
  })
})
