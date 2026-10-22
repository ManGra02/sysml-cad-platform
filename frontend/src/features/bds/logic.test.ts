import { describe, expect, it } from "vitest"

import {
  attributeState,
  cadRefOf,
  defaultRequirement,
  describeMethod,
  gapAction,
  gapRequirement,
  gaugePosition,
  nextSteps,
  runStaleness,
} from "./logic"
import type { Mapping, Proposal, Requirement, Workspace } from "./queries"

const requirement = (id: string, subject: string): Requirement => ({
  requirement: id,
  element_id: id,
  subject,
  subject_id: "",
  attribute: "",
  operator: "<=",
  limit: { value: 1, unit: "mm", text: "1 mm" },
  text: id,
})

const REQUIREMENTS = [
  requirement("MaxHousingLength", "housing"),
  requirement("MinBoreRadius", "housing"),
  requirement("MaxCoverThickness", "Gearbox::cover"),
]

describe("defaultRequirement", () => {
  it("takes the part's requirement that names the attribute", () => {
    expect(defaultRequirement(REQUIREMENTS, "cover", "thickness")).toBe("MaxCoverThickness")
  })
  it("being the only requirement on the part is not enough", () => {
    expect(defaultRequirement(REQUIREMENTS, "cover", "length")).toBeUndefined()
  })
  it("among several, the one that names the attribute", () => {
    expect(defaultRequirement(REQUIREMENTS, "housing", "boreRadius")).toBe("MinBoreRadius")
    expect(defaultRequirement(REQUIREMENTS, "housing", "length")).toBe("MaxHousingLength")
  })
  it("no guess when nothing or several fit", () => {
    expect(defaultRequirement(REQUIREMENTS, "housing", "width")).toBeUndefined()
    expect(defaultRequirement(REQUIREMENTS, "gearbox", "mass")).toBeUndefined()
  })
})

describe("attributeState", () => {
  const mapping = {
    digest: "d",
    parts: [],
    attributes: [
      { sysml_part: "housing", attribute: "length", status: "confirmed", requirement: "MaxHousingLength" },
      { sysml_part: "housing", attribute: "height", status: "disabled", requirement: "" },
    ],
  } as unknown as Mapping
  const proposals = [{ id: "p-03", sysml_part: "cover", attribute: "thickness", status: "proposed" }] as Proposal[]

  it("confirmed, proposed, disabled, open", () => {
    expect(attributeState(mapping, proposals, "housing", "length")).toEqual({ state: "confirmed", requirement: "MaxHousingLength" })
    expect(attributeState(mapping, proposals, "cover", "thickness")).toEqual({ state: "proposed", proposal: "p-03" })
    expect(attributeState(mapping, proposals, "housing", "height")).toEqual({ state: "disabled" })
    expect(attributeState(mapping, proposals, "cover", "mass")).toEqual({ state: "open" })
  })
})

describe("gaps", () => {
  it("maps the backend's sentences to an action", () => {
    expect(gapAction("MaxCoverThickness: mapping is proposed, not confirmed -- not used in this run")).toBe("proposals")
    expect(gapAction("MaxLength: no mapping entry for part 'box'")).toBe("propose")
    expect(gapAction("MaxLength: Gearbox#Body (Housing): it changed since the last recompute -- recompute in FreeCAD first")).toBe("recompute")
    expect(gapAction("MaxLength: FreeCAD document 'Gearbox' is not open -- open it in FreeCAD")).toBe("openDocument")
    expect(gapAction("MinBoreRadius: part 'housing' has confirmed entries without a requirement (boreRadius)")).toBe("link")
    expect(gapAction("something new")).toBeUndefined()
  })
  it("reads the requirement id", () => {
    expect(gapRequirement("MaxLength: no mapping entry")).toBe("MaxLength")
    expect(gapRequirement("dimension [mass] does not match")).toBeUndefined()
  })
})

describe("runStaleness", () => {
  const run = { context: { sysml_commit_id: "c1", started_at: "2026-10-22T10:00:00+00:00" } } as never
  it("a newer commit or a later FreeCAD change makes it stale", () => {
    expect(runStaleness(run, { headCommit: "c1" })).toBeUndefined()
    expect(runStaleness(run, { headCommit: "c2" })).toBe("commit")
    expect(runStaleness(run, { headCommit: "c2", selectedCommit: "c1" })).toBeUndefined()
    expect(runStaleness(run, { headCommit: "c1", cadChangedAt: Date.parse("2026-10-22T10:05:00Z") })).toBe("cad")
    expect(runStaleness(run, { headCommit: "c1", cadChangedAt: Date.parse("2026-10-22T09:55:00Z") })).toBeUndefined()
    expect(runStaleness(undefined, { headCommit: "c2" })).toBeUndefined()
  })
})

describe("nextSteps", () => {
  const workspace = (counts: Partial<Workspace["counts"]>, lastRun: Workspace["last_run"] = null): Workspace =>
    ({
      cad_document: "Gearbox",
      counts: { parts_confirmed: 0, attributes_confirmed: 0, proposals_pending: 0, ...counts },
      last_run: lastRun,
    }) as Workspace

  it("an empty workspace starts with proposals", () => {
    expect(nextSteps(workspace({}), true).map((s) => s.kind)).toEqual(["propose"])
    expect(nextSteps(workspace({}), false).map((s) => s.kind)).toEqual(["openDocument", "propose"])
  })
  it("a mapped workspace wants a run, then fixes, then the sync", () => {
    expect(nextSteps(workspace({ attributes_confirmed: 3, proposals_pending: 2 }), true).map((s) => s.kind)).toEqual([
      "review",
      "verify",
      "sync",
    ])
    const ran = {
      summary: { compliant: 2, within_tolerance: 0, violated: 1, not_checked: 1 },
      violated: true,
      context: {} as never,
    }
    expect(nextSteps(workspace({ attributes_confirmed: 3 }, ran), true)).toEqual([{ kind: "fix", count: 2 }, { kind: "sync" }])
  })
})

describe("formatting", () => {
  it("method with its arguments", () => {
    expect(describeMethod("bbox_size", { axis: "X" })).toBe("bbox_size · X")
    expect(describeMethod("volume", {})).toBe("volume")
  })
  it("gauge keeps both marks on the scale", () => {
    expect(gaugePosition(99, 95)).toEqual({ value: 0.8, limit: 95 / (99 * 1.25) })
    expect(gaugePosition(0, 0)).toEqual({ value: 0, limit: 0 })
  })
})

describe("cadRefOf", () => {
  it("reads document and object from a verdict's method", () => {
    expect(cadRefOf("bbox_size({'axis': 'X'}) on freecad:Gearbox#Body")).toEqual({ doc: "Gearbox", name: "Body" })
    expect(cadRefOf("mass({}) on freecad:Gearbox")).toEqual({ doc: "Gearbox" })
    expect(cadRefOf("mass")).toBeUndefined()
  })
})
