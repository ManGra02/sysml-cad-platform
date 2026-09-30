import { describe, expect, it } from "vitest"

import { formatNumber, formatValue, parseNumber, sameValue } from "./format"
import { axisAngleToQuat, quatToAxisAngle } from "./rotation"
import { beginOwnRequest, endOwnRequest, isOwnOrigin, planInvalidation } from "./sync"
import { ancestorKeys, findPath, flattenTree, moveInTree, pathKey, searchTree } from "./tree"
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

describe("Tree", () => {
  // Body -> Pad -> Sketch, and Sketch additionally hangs off a second Pad (DAG)
  const tree = makeTree(
    [node("Body", ["Pad", "Pad001"]), node("Pad", ["Sketch"]), node("Pad001", ["Sketch"]), node("Sketch"), node("Loose")],
    ["Body", "Loose"],
  )

  it("shows only the roots when collapsed", () => {
    expect(flattenTree(tree, new Set()).map((r) => r.name)).toEqual(["Body", "Loose"])
  })

  it("an object may appear multiple times -- the key is the path", () => {
    const expanded = new Set([pathKey(["Body"]), pathKey(["Body", "Pad"]), pathKey(["Body", "Pad001"])])
    const rows = flattenTree(tree, expanded)
    const sketches = rows.filter((r) => r.name === "Sketch")
    expect(sketches).toHaveLength(2)
    expect(new Set(rows.map((r) => r.key)).size).toBe(rows.length)
    expect(sketches[0].depth).toBe(2)
  })

  it("cycles do not hang the build", () => {
    const cyclic = makeTree([node("A", ["B"]), node("B", ["A"])], ["A"])
    const expanded = new Set([pathKey(["A"]), pathKey(["A", "B"]), pathKey(["A", "B", "A"])])
    const rows = flattenTree(cyclic, expanded)
    expect(rows.map((r) => r.name)).toEqual(["A", "B", "A"])
    expect(rows[2].cycle).toBe(true)
    expect(rows[2].hasChildren).toBe(false)
  })

  it("edges to hidden objects are ignored", () => {
    const partial = makeTree([node("Body", ["Origin"])], ["Body"])
    expect(flattenTree(partial, new Set([pathKey(["Body"])]))[0].hasChildren).toBe(false)
  })

  it("finds the path to an object and the ancestors to expand", () => {
    const path = findPath(tree, "Sketch")
    expect(path).toEqual(["Body", "Pad", "Sketch"])
    expect(ancestorKeys(path!)).toEqual([pathKey(["Body"]), pathKey(["Body", "Pad"])])
    expect(findPath(tree, "DoesNotExist")).toBeNull()
  })

  it("path keys are unique, even when names contain separators", () => {
    expect(pathKey(["a/b"])).not.toBe(pathKey(["a", "b"]))
  })

  it("search matches label and name, case-insensitively", () => {
    const labelled = makeTree([node("Box", [], { label: "Gehäuse" }), node("Cylinder")], ["Box", "Cylinder"])
    expect(searchTree(labelled, "gehä").map((r) => r.name)).toEqual(["Box"])
    expect(searchTree(labelled, "BOX").map((r) => r.name)).toEqual(["Box"])
    expect(searchTree(labelled, "  ")).toEqual([])
  })
})

describe("Tree via keyboard", () => {
  const tree = makeTree([node("Body", ["Pad"]), node("Pad", ["Sketch"]), node("Sketch"), node("Loose")], ["Body", "Loose"])
  const collapsed = flattenTree(tree, new Set())
  const open = flattenTree(tree, new Set([pathKey(["Body"]), pathKey(["Body", "Pad"])]))
  // open: Body(0) Pad(1) Sketch(2) Loose(3)

  it("up/down stays within bounds", () => {
    expect(moveInTree(open, 0, "ArrowUp")).toEqual({ index: 0 })
    expect(moveInTree(open, 3, "ArrowDown")).toEqual({ index: 3 })
    expect(moveInTree(open, 1, "ArrowDown")).toEqual({ index: 2 })
    expect(moveInTree(open, 2, "Home")).toEqual({ index: 0 })
    expect(moveInTree(open, 0, "End")).toEqual({ index: 3 })
  })

  it("right expands, then moves to the first child", () => {
    expect(moveInTree(collapsed, 0, "ArrowRight")).toEqual({ index: 0, expand: pathKey(["Body"]) })
    expect(moveInTree(open, 0, "ArrowRight")).toEqual({ index: 1 })
    expect(moveInTree(open, 3, "ArrowRight")).toEqual({ index: 3 }) // leaf: nothing
  })

  it("left collapses, then moves to the parent node", () => {
    expect(moveInTree(open, 1, "ArrowLeft")).toEqual({ index: 1, collapse: pathKey(["Body", "Pad"]) })
    expect(moveInTree(open, 2, "ArrowLeft")).toEqual({ index: 1 })
    expect(moveInTree(open, 3, "ArrowLeft")).toEqual({ index: 3 }) // root: stays
  })

  it("other keys do not belong to the tree", () => {
    expect(moveInTree(open, 0, "a")).toBeNull()
    expect(moveInTree([], 0, "ArrowDown")).toBeNull()
  })
})

describe("Events -> invalidation", () => {
  const never = () => false

  it("cad.changed reloads object and tree, not the whole document", () => {
    const plan = planInvalidation([{ type: "cad.changed", doc: "D", obj: "Box", props: ["Length"], origin: "freecad:user" }], never)
    expect(plan.objects).toEqual([["D", "Box"]])
    expect([...plan.trees]).toEqual(["D"])
    expect(plan.docs.size).toBe(0)
    expect(plan.all).toBe(false)
  })

  it("the echo of an own mutation is ignored", () => {
    const plan = planInvalidation(
      [{ type: "cad.changed", doc: "D", obj: "Box", origin: "bridge:mine" }],
      (origin) => origin === "bridge:mine",
    )
    expect(plan.objects).toEqual([])
    expect(plan.trees.size).toBe(0)
  })

  it("undo discards the whole document instead of updating incrementally", () => {
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

  it("a newly created object also reloads its detail view", () => {
    const plan = planInvalidation([{ type: "cad.created", doc: "D", obj: "Sphere0" }], never)
    expect(plan.objects).toEqual([["D", "Sphere0"]])
    expect(plan.documents).toBe(true)
  })

  it("resync without a document reloads everything", () => {
    expect(planInvalidation([{ type: "cad.resync", reason: "overflow" }], never).all).toBe(true)
  })

  it("doc.modified only affects the document list", () => {
    const plan = planInvalidation([{ type: "doc.modified", doc: "D", dirty: true }], never)
    expect(plan.documents).toBe(true)
    expect(plan.objects).toEqual([])
    expect(plan.trees.size).toBe(0)
  })

  it("multiple changes to the same object result in one invalidation", () => {
    const plan = planInvalidation(
      [
        { type: "cad.changed", doc: "D", obj: "Box" },
        { type: "cad.changed", doc: "D", obj: "Box" },
      ],
      never,
    )
    expect(plan.objects).toHaveLength(1)
  })

  it("own requests still count as own shortly after the response", () => {
    beginOwnRequest("r1")
    expect(isOwnOrigin("bridge:r1")).toBe(true)
    endOwnRequest("r1", 1_000)
    expect(isOwnOrigin("bridge:r1", 2_000)).toBe(true)
    expect(isOwnOrigin("bridge:r1", 10_000)).toBe(false)
    expect(isOwnOrigin("freecad:user")).toBe(false)
    expect(isOwnOrigin("bridge:foreign")).toBe(false)
  })
})

describe("Rotation", () => {
  it("round trip axis/angle <-> quaternion", () => {
    const q = axisAngleToQuat([0, 0, 1], 90)
    const { axis, angle } = quatToAxisAngle(q)
    expect(angle).toBeCloseTo(90)
    expect(axis[2]).toBeCloseTo(1)
  })

  it("no rotation is angle 0 around z", () => {
    expect(quatToAxisAngle([0, 0, 0, 1])).toEqual({ axis: [0, 0, 1], angle: 0 })
  })

  it("axis is normalized", () => {
    const q = axisAngleToQuat([0, 0, 5], 180)
    expect(Math.hypot(...q)).toBeCloseTo(1)
  })

  it("axis (0,0,0) with an angle is an error", () => {
    expect(() => axisAngleToQuat([0, 0, 0], 30)).toThrow()
  })
})

describe("Formatting", () => {
  it("no float noise", () => {
    expect(formatNumber(0.1 + 0.2)).toBe("0.3")
    expect(formatNumber(-0.0000000001)).toBe("0")
  })

  it("comma as decimal separator, nonsense is rejected", () => {
    expect(parseNumber("12,5")).toBe(12.5)
    expect(parseNumber(" -3e2 ")).toBe(-300)
    expect(parseNumber("12 mm")).toBeNull()
    expect(parseNumber("")).toBeNull()
  })

  it("quantity shows the lossless text", () => {
    expect(formatValue({ kind: "quantity", value: 10, unit: "mm", unitType: "Length", text: "10 mm" })).toBe("10 mm")
  })

  it("link shows label and name", () => {
    expect(formatValue({ kind: "link", ref: { doc: "D", name: "Box" } }, { Box: "Gehäuse" })).toBe("Gehäuse (Box)")
  })

  it("structural equality", () => {
    expect(sameValue({ kind: "vector", x: 1, y: 2, z: 3 }, { kind: "vector", x: 1, y: 2, z: 3 })).toBe(true)
    expect(sameValue({ a: [1, 2] }, { a: [1, 3] })).toBe(false)
    expect(sameValue(null, {})).toBe(false)
  })
})
