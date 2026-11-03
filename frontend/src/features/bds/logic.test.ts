import { describe, expect, it } from "vitest"

import {
  cadRefOf,
  crossCheck,
  describeMeasurement,
  dimensionOf,
  gapRequirement,
  gaugePosition,
  marginOf,
  firstProposalId,
  measurementOptions,
  otherAssignments,
  nextStep,
  assignState,
  checkState,
  otherProposals,
  progress,
  requirementRows,
  runStaleness,
  splitReference,
} from "./logic"
import type { AttributeMapping, CadTarget, Mapping, Proposal, Requirement, Run, Verdict } from "./queries"

const AXES = { length: "X", width: "Y", height: "Z", thickness: "Z" }

const requirement = (id: string, subject: string, attribute: string, limit = 95): Requirement => ({
  requirement: id,
  element_id: id,
  subject,
  subject_id: "",
  attribute,
  operator: "<=",
  limit: { value: limit, unit: "mm", text: `${limit} mm` },
  text: id,
})

const REQUIREMENTS = [
  requirement("MaxHousingLength", "housing", "length"),
  requirement("MinBoreRadius", "housing", "boreRadius", 8),
  requirement("MaxCoverThickness", "Gearbox::cover", "thickness", 8),
  requirement("MaxAssemblyMass", "gearbox", ""),
]

const entry = (part: string, attribute: string, requirementId = "", over: Partial<AttributeMapping> = {}): AttributeMapping => ({
  sysml_part: part,
  attribute,
  method: "bbox_size",
  requirement: requirementId,
  args: { axis: "X" },
  direction: "cad_owns",
  tolerance: null,
  status: "confirmed",
  author: "manual",
  confirmed_at: "",
  note: "",
  ...over,
})

const mapping = (attributes: AttributeMapping[]): Mapping => ({
  digest: "d",
  parts: [...new Set(attributes.map((a) => a.sysml_part))].map((part) => ({
    sysml_part: part,
    adapter: "freecad",
    cad_object: "Gearbox#" + part,
    status: "confirmed",
    author: "",
    confirmed_at: "",
    note: "",
  })),
  attributes,
})

const proposal = (id: string, part: string, attribute: string, over: Partial<Proposal> = {}): Proposal => ({
  id,
  sysml_part: part,
  attribute,
  adapter: "freecad",
  cad_object: "Gearbox#Body001",
  method: "bbox_size",
  args: { axis: "Z" },
  requirement: "",
  direction: "cad_owns",
  confidence: 0.5,
  rationale: "",
  proposed_by: "baseline:difflib",
  proposed_at: "",
  provenance: {},
  status: "proposed",
  decided_at: "",
  reason: "",
  ...over,
})

const verdict = (id: string, subject: string, status: Verdict["status"], measured: number, limit = 95): Verdict => ({
  ...requirement(id, subject, "length", limit),
  measured: { value: measured, unit: "mm", text: `${measured} mm` },
  deviation: { value: measured - limit, unit: "mm", text: "" },
  tolerance: null,
  method: "bbox_size({'axis': 'X'}) on freecad:Gearbox#Body",
  status,
})

const run = (verdicts: Verdict[], gaps: string[] = []): Run => ({
  context: { workspace: "w", sysml_project_id: "p", sysml_commit_id: "c1", cad_adapter: "freecad", cad_state_id: "s",
    mapping_digest: "d", started_at: "2026-10-22T10:00:00+00:00" },
  verdicts,
  gaps,
  summary: { compliant: 0, within_tolerance: 0, violated: 0, not_checked: 0 },
  violated: false,
})

const catalog = (not_extracted: string[] = []) => ({ requirements: REQUIREMENTS, not_extracted })
const byId = (rows: ReturnType<typeof requirementRows>) => Object.fromEntries(rows.map((r) => [r.id, r]))

describe("requirementRows", () => {
  it("nothing assigned: unassigned, or unclear when the model does not say the attribute", () => {
    const rows = byId(requirementRows({ catalog: catalog() }))
    expect(rows.MaxHousingLength.state).toBe("unassigned")
    expect(rows.MaxCoverThickness.part).toBe("cover")
    expect(rows.MaxAssemblyMass.state).toBe("attributeUnclear")
  })

  it("a pending proposal for the constrained attribute makes it a row to review", () => {
    const rows = byId(requirementRows({
      catalog: catalog(),
      proposals: [proposal("p-1", "cover", "thickness", { confidence: 0.4 }), proposal("p-2", "cover", "thickness", { confidence: 0.9 }),
        proposal("p-3", "cover", "length"), proposal("p-4", "cover", "thickness", { status: "rejected" })],
    }))
    expect(rows.MaxCoverThickness.state).toBe("proposal")
    expect(rows.MaxCoverThickness.proposals.map((p) => p.id)).toEqual(["p-2", "p-1"])
  })

  it("an assignment shows its verdict, its gap, or that it is not checked yet", () => {
    const m = mapping([
      entry("housing", "length", "MaxHousingLength"),
      entry("housing", "boreRadius", "MinBoreRadius", { method: "cylinder_radius", args: { kind: "hole" } }),
      entry("cover", "thickness", "MaxCoverThickness", { args: { axis: "Z" } }),
    ])
    const r = run([verdict("MaxHousingLength", "housing", "violated", 100)], [
      "MinBoreRadius: Gearbox#Body (Housing): it changed since the last recompute -- recompute in FreeCAD first",
    ])
    const rows = byId(requirementRows({ catalog: catalog(), mapping: m, run: r, documentOpen: true }))
    expect(rows.MaxHousingLength.state).toBe("violated")
    expect(rows.MaxHousingLength.cadObject).toBe("Gearbox#housing")
    expect(rows.MinBoreRadius.state).toBe("notRecomputed")
    expect(rows.MinBoreRadius.reason).toContain("recompute in FreeCAD")
    expect(rows.MaxCoverThickness.state).toBe("assigned")
  })

  it("a closed document makes every assignment not measurable", () => {
    const m = mapping([entry("housing", "length", "MaxHousingLength")])
    const r = run([verdict("MaxHousingLength", "housing", "compliant", 90)])
    expect(byId(requirementRows({ catalog: catalog(), mapping: m, run: r, documentOpen: false })).MaxHousingLength.state).toBe("documentClosed")
  })

  it("unreadable requirements and entries for vanished ones stay in the table", () => {
    const m = mapping([entry("housing", "width", "GoneRequirement")])
    const rows = requirementRows({ catalog: catalog(["Band: not extracted -- 2 comparisons; compound constraints are not supported"]), mapping: m })
    const states = Object.fromEntries(rows.map((r) => [r.id, r.state]))
    expect(states.Band).toBe("notExtracted")
    expect(states.GoneRequirement).toBe("orphaned")
    expect(progress(rows).total).toBe(5)              // orphaned rows are not requirements
  })
})

describe("next step and area states", () => {
  const p = (assigned: number, total = 4, violated = 0, more: { unchecked?: number; unmeasured?: number } = {}) =>
    ({ total, assigned, checked: 0, passed: 0, tolerance: 0, violated, open: total - assigned, unchecked: 0, unmeasured: 0, ...more })
  const fresh = { run: true, stale: false }
  it("the overview points to one step, in working order", () => {
    expect(nextStep(p(0, 0), 0, fresh).kind).toBe("empty")
    expect(nextStep(p(1), 3, fresh)).toEqual({ kind: "review", count: 3 })
    expect(nextStep(p(0), 0, fresh).kind).toBe("start")
    expect(nextStep(p(2), 0, { run: true, stale: true, bridgeDown: true }).kind).toBe("offline")
    expect(nextStep(p(2), 0, { run: true, stale: false, documentOpen: false }).kind).toBe("closed")
    expect(nextStep(p(2), 0, { run: false, stale: false }).kind).toBe("check")
    expect(nextStep(p(2), 0, { run: true, stale: true }).kind).toBe("recheck")
    expect(nextStep(p(2, 4, 0, { unchecked: 1 }), 0, fresh).kind).toBe("recheck")   // assigned after the check
    expect(nextStep(p(2, 4, 1), 0, fresh)).toEqual({ kind: "violated", count: 1 })
    expect(nextStep(p(2, 4, 0, { unmeasured: 1 }), 0, fresh)).toEqual({ kind: "unmeasured", count: 1 })
    expect(nextStep(p(2), 0, fresh)).toEqual({ kind: "rest", count: 2 })
    expect(nextStep(p(4), 0, fresh).kind).toBe("done")
  })
  it("assign shows linked or not, check shows no suggestions", () => {
    const m = mapping([entry("housing", "length", "MaxHousingLength")])
    const r = run([verdict("MaxHousingLength", "housing", "violated", 99)])
    const rows = byId(requirementRows({ catalog: catalog(), mapping: m, run: r, proposals: [proposal("p-1", "cover", "thickness")] }))
    expect(assignState(rows.MaxHousingLength)).toBe("linked")
    expect(checkState(rows.MaxHousingLength)).toBe("violated")
    expect(assignState(rows.MaxCoverThickness)).toBe("proposal")
    expect(checkState(rows.MaxCoverThickness)).toBe("unassigned")
    expect(checkState(rows.MaxAssemblyMass)).toBe("unassigned")   // attribute unclear
  })
  it("only the first suggestion on the page is the primary one", () => {
    const rows = requirementRows({ catalog: catalog(), proposals: [proposal("p-7", "cover", "thickness"), proposal("p-3", "housing", "length")] })
    expect(firstProposalId(rows)).toBe("p-3")         // MaxHousingLength comes first in REQUIREMENTS
  })
})

describe("other assignments", () => {
  it("entries without a requirement; linkable when exactly one requirement constrains that attribute", () => {
    const m = mapping([entry("housing", "length"), entry("housing", "width"), entry("cover", "thickness", "MaxCoverThickness")])
    const others = otherAssignments(m, REQUIREMENTS)
    expect(others.map((a) => [a.entry.attribute, a.linkable?.requirement])).toEqual([
      ["length", "MaxHousingLength"],
      ["width", undefined],
    ])
  })
  it("an already linked requirement is not offered again", () => {
    const m = mapping([entry("housing", "length", "MaxHousingLength"), entry("housing", "length", "", { args: { axis: "Y" } })])
    expect(otherAssignments(m, REQUIREMENTS)[0].linkable).toBeUndefined()
  })
  it("proposals for attributes no requirement constrains", () => {
    const rows = requirementRows({ catalog: catalog() })
    expect(otherProposals([proposal("p-1", "cover", "length"), proposal("p-2", "cover", "thickness")], rows).map((p) => p.id)).toEqual(["p-1"])
  })
})

describe("progress", () => {
  it("counts assigned, met, exceeded and violated", () => {
    const m = mapping([entry("housing", "length", "MaxHousingLength"), entry("housing", "boreRadius", "MinBoreRadius")])
    const r = run([verdict("MaxHousingLength", "housing", "compliant", 90), verdict("MinBoreRadius", "housing", "within_tolerance", 8.1, 8)])
    const p = progress(requirementRows({ catalog: catalog(), mapping: m, run: r }))
    expect(p).toEqual({ total: 4, assigned: 2, checked: 2, passed: 1, tolerance: 1, violated: 0, open: 2, unchecked: 0, unmeasured: 0 })
  })
})

describe("measurements in words", () => {
  const target = { sheet_parameters: ["Params.CoverThickness"] }
  it("names the axis's meaning and where the value comes from", () => {
    expect(describeMeasurement("bbox_size", { axis: "x" }, AXES)).toEqual({ text: { kind: "bbox", axis: "X", meaning: "length" }, source: "geometry" })
    expect(describeMeasurement("cylinder_radius", { kind: "hole", axis: "z" }, AXES).text).toEqual({ kind: "radius", hole: true, axis: "Z" })
    expect(describeMeasurement("parameter", { name: "Params.CoverThickness" }, AXES, target).source).toBe("sheet")
    expect(describeMeasurement("parameter", { name: "Pad001.Length" }, AXES, target).source).toBe("feature")
    expect(describeMeasurement("mass", {}, AXES).source).toBe("geometry")
  })
  it("reads the dimension of a parameter's text", () => {
    expect(dimensionOf("8 mm")).toBe("[length]")
    expect(dimensionOf("0.5 kg")).toBe("[mass]")
    expect(dimensionOf("360 deg")).toBeUndefined()
  })
})

const COVER: CadTarget = {
  adapter: "freecad",
  reference: "gearbox#Cover",
  kind: "part",
  name: "Cover",
  methods: ["bbox_size", "volume", "mass", "face_count", "cylinder_radius", "parameter"],
  note: "",
  depth: 1,
  container: "gearbox",
  parameters: { "Params.CoverThickness": "6 mm", "CoverBox.Length": "90 mm", "CoverBore.Angle": "360 deg" },
  sheet_parameters: ["Params.CoverThickness"],
  size: [90, 60, 6],
  mass: { value: 0.084, unit: "kg", text: "0.084 kg" },
  material: "Aluminum-Generic",
  cylinders: [{ kind: "hole", radius: 8, axis: "Z" }],
  error: null,
}

describe("measurementOptions", () => {
  it("a length: three extents, the bore, length parameters -- table values first", () => {
    const options = measurementOptions(COVER, "[length]")
    expect(options.map((o) => [o.method, o.args, o.value])).toEqual([
      ["bbox_size", { axis: "X" }, "90 mm"],
      ["bbox_size", { axis: "Y" }, "60 mm"],
      ["bbox_size", { axis: "Z" }, "6 mm"],
      ["cylinder_radius", { kind: "hole", axis: "Z" }, "8 mm"],
      ["parameter", { name: "Params.CoverThickness" }, "6 mm"],
      ["parameter", { name: "CoverBox.Length" }, "90 mm"],
    ])
  })
  it("a mass: only the mass", () => {
    expect(measurementOptions(COVER, "[mass]").map((o) => o.method)).toEqual(["mass"])
  })
})

describe("crossCheck", () => {
  it("catches a thickness offered as the length", () => {
    expect(crossCheck("length", 6, COVER, AXES, "parameter")).toEqual({ axis: "X", expected: 90, fits: false })
    expect(crossCheck("thickness", 6, COVER, AXES, "parameter")).toEqual({ axis: "Z", expected: 6, fits: true })
    expect(crossCheck("boreRadius", 8, COVER, AXES, "cylinder_radius")).toBeUndefined()
    expect(crossCheck("mass", 1, COVER, AXES, "bbox_size")).toBeUndefined()
  })
})

describe("numbers", () => {
  it("the limit always sits at 80 % of the bar", () => {
    expect(gaugePosition(95, 95)).toEqual({ value: 0.8, limit: 0.8 })
    expect(gaugePosition(200, 95)).toEqual({ value: 1, limit: 0.8 })
    expect(gaugePosition(0, 0)).toEqual({ value: 0, limit: 0.8 })
  })
  it("margin reads in the direction that matters", () => {
    expect(marginOf({ operator: "<=", deviation: { value: 5, unit: "mm", text: "" } })).toEqual({ over: true, amount: 5, unit: "mm" })
    expect(marginOf({ operator: "<=", deviation: { value: -2, unit: "mm", text: "" } }).over).toBe(false)
    expect(marginOf({ operator: ">=", deviation: { value: -1, unit: "mm", text: "" } }).over).toBe(true)
    expect(marginOf({ operator: ">=", deviation: { value: 0, unit: "mm", text: "" } }).over).toBe(false)
  })
})

describe("runStaleness", () => {
  const r = { context: { sysml_commit_id: "c1", started_at: "2026-10-22T10:00:00+00:00" } } as never
  it("a newer commit or a later FreeCAD change makes it stale", () => {
    expect(runStaleness(r, { headCommit: "c1" })).toBeUndefined()
    expect(runStaleness(r, { headCommit: "c2" })).toBe("commit")
    expect(runStaleness(r, { headCommit: "c2", selectedCommit: "c1" })).toBeUndefined()
    expect(runStaleness(r, { headCommit: "c1", cadChangedAt: Date.parse("2026-10-22T10:05:00Z") })).toBe("cad")
    expect(runStaleness(r, { headCommit: "c1", cadChangedAt: Date.parse("2026-10-22T09:55:00Z") })).toBeUndefined()
    expect(runStaleness(undefined, { headCommit: "c2" })).toBeUndefined()
  })
})

describe("references", () => {
  it("reads the requirement id of a gap", () => {
    expect(gapRequirement("MaxLength: no mapping entry")).toBe("MaxLength")
    expect(gapRequirement("dimension [mass] does not match")).toBeUndefined()
  })
  it("reads document and object", () => {
    expect(cadRefOf("bbox_size({'axis': 'X'}) on freecad:Gearbox#Body")).toEqual({ doc: "Gearbox", name: "Body" })
    expect(cadRefOf("mass")).toBeUndefined()
    expect(splitReference("gearbox#Cover")).toEqual({ doc: "gearbox", name: "Cover" })
    expect(splitReference("gearbox")).toEqual({ doc: "gearbox" })
  })
})
