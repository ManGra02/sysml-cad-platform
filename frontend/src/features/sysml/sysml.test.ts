import { describe, expect, it } from "vitest"

import { formatAttribute, formatSi, leafParts, partTree, requirementsOf, type SysmlElement, type SysmlSnapshot } from "./queries"

function el(id: string, name: string, kind: string, parent: string | null = null): SysmlElement {
  return {
    id, name, kind, source: "sysml", native_type: "", qualified_name: name, parent_id: parent,
    type_ids: [], short_name: null, doc: null, is_definition: false, extra: {},
  }
}

const snapshot: SysmlSnapshot = {
  source: "sysml", project_id: "p", version: "c1", branch_id: null, retrieved_at: "", stats: {}, warnings: [],
  elements: [
    el("pkg", "EBike", "package"),
    el("empty", "Library", "package"),
    el("bike", "eBike", "part", "pkg"),
    el("drive", "driveUnit", "part", "bike"),
    el("motor", "motor", "part", "drive"),
    el("battery", "battery", "part", "bike"),
    el("Motor", "Motor", "part_def", "pkg"),
    el("req", "massReq", "requirement", "pkg"),
  ],
  attributes: [],
  relations: [],
}

describe("sysml snapshot helpers", () => {
  it("builds the part tree and drops packages without parts", () => {
    const tree = partTree(snapshot)
    expect(tree.map((n) => n.element.name)).toEqual(["EBike"])
    const bike = tree[0].children[0]
    expect(bike.element.name).toBe("eBike")
    expect(bike.children.map((n) => n.element.name)).toEqual(["battery", "driveUnit"])
    expect(bike.children[1].children[0].element.name).toBe("motor")
  })

  it("finds leaf parts and requirements", () => {
    expect(leafParts(snapshot).map((p) => p.name).sort()).toEqual(["battery", "motor"])
    expect(requirementsOf(snapshot).map((r) => r.id)).toEqual(["req"])
  })

  it("formats values without float noise", () => {
    expect(formatAttribute({ value: 9.8, unit: "kg", expression: "9.8 [kg]" })).toBe("9.8 kg")
    expect(formatAttribute({ value: null, unit: null, expression: "a + b" })).toBe("a + b")
    expect(formatSi({ value_si: 0.30000000000000004, unit_si: "m" })).toBe("0.3 m")
    expect(formatSi({ value_si: null, unit_si: null })).toBeNull()
  })
})
