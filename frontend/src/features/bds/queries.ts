import { queryOptions, type QueryClient } from "@tanstack/react-query"

import { api, seg } from "@/lib/api"

// The BDS module's HTTP API (backend/app/projects/bds/__init__.py). The keys live under
// ["bds"], NOT under projectKeys.module("bds"): handleProjectFrame refreshes that on every
// "bds.*" frame, and the module sends one per FreeCAD change -- every catalogue and gate
// check would be read again from Flexo and FreeCAD. The workspace page decides itself
// what a frame means (see useBdsFrames).

export type Quantity = { value: number; unit: string; text: string }

export type LastRunInfo = {
  summary: RunSummary
  violated: boolean
  context: RunContext
}

export type Workspace = {
  name: string
  sysml_project: string
  cad_document: string
  limits_sheet: string
  axes: Record<string, string>
  mapping: boolean
  proposals: boolean
  gold: boolean
  counts: { parts_confirmed: number | null; attributes_confirmed: number | null; proposals_pending: number }
  last_run: LastRunInfo | null
}

export type WorkspaceSettings = {
  sysml_project: string
  cad_document: string
  axes?: Record<string, string> | null
  limits_sheet?: string | null
}

export type CatalogAttribute = { name: string; element_id: string; type: string; dimension: string | null }
export type CatalogPart = {
  name: string
  element_id: string
  definition: string
  package: string
  container: string | null
  attributes: CatalogAttribute[]
}
export type CadTarget = {
  adapter: string
  reference: string
  kind: "part" | "assembly"
  name: string
  methods: string[]
  note: string
  depth: number
  container: string | null
  parameters: Record<string, string>
}
export type Requirement = {
  requirement: string
  element_id: string
  subject: string
  subject_id: string
  attribute: string
  operator: string
  limit: Quantity
  text: string
}
export type Catalog = {
  source: string
  axes: Record<string, string>
  sysml: CatalogPart[]
  cad: CadTarget[]
  sysml_project_id: string
  sysml_commit_id: string
  requirements: Requirement[]
  not_extracted: string[]
}

export type PartMapping = {
  sysml_part: string
  adapter: string
  cad_object: string
  status: "proposed" | "confirmed" | "disabled"
  author: string
  confirmed_at: string
  note: string
}
export type AttributeMapping = {
  sysml_part: string
  attribute: string
  method: string
  requirement: string
  args: Record<string, unknown> | null
  direction: string
  tolerance: string | number | null
  status: "proposed" | "confirmed" | "disabled"
  author: string
  confirmed_at: string
  note: string
}
export type Mapping = { digest: string; parts: PartMapping[]; attributes: AttributeMapping[] }

export type GateVerdict = "valid" | "unknown" | "invalid"
export type GateResult = { gate: string; verdict: GateVerdict; detail: string; code?: string }
export type GateCheck = {
  sysml_part: string
  attribute: string
  cad_object: string
  method: string
  status: string
  verdict: GateVerdict
  measured: Quantity | null
  gates: GateResult[]
}
export type Gates = {
  mapping_digest: string
  sysml_commit_id: string
  entries: GateCheck[]
  summary: Record<GateVerdict, number>
  unused_parts: string[]
}

export type ProposalStatus = "proposed" | "confirmed" | "rejected"
export type Proposal = {
  id: string
  sysml_part: string
  attribute: string
  adapter: string
  cad_object: string
  method: string
  args: Record<string, unknown>
  requirement: string
  direction: string
  confidence: number
  rationale: string
  proposed_by: string
  proposed_at: string
  provenance: Record<string, string>
  status: ProposalStatus
  decided_at: string
  reason: string
  /** only with ?check=true, for pending proposals */
  check?: GateCheck
}
export type GateRejection = {
  sysml_part: string
  attribute?: string
  cad_object?: string
  method?: string
  code?: string
  reason: string
}
export type ProposeResult = {
  proposer: string
  candidates: Proposal[]
  stored: string[]
  rejected_by_gates: GateRejection[]
  dropped_by_proposer: string[]
}

export type RunContext = {
  workspace: string
  sysml_project_id: string
  sysml_commit_id: string
  cad_adapter: string
  cad_state_id: string
  mapping_digest: string
  started_at: string
}
export type RunSummary = { compliant: number; within_tolerance: number; violated: number; not_checked: number }
export type VerdictStatus = "compliant" | "within_tolerance" | "violated"
export type Verdict = Requirement & {
  measured: Quantity
  deviation: Quantity
  tolerance: Quantity | null
  method: string
  status: VerdictStatus
}
export type Run = { context: RunContext; verdicts: Verdict[]; gaps: string[]; summary: RunSummary; violated: boolean }

export type LimitChange = { alias: string; old: Quantity | null; new: Quantity }
export type SyncResult = {
  apply: boolean
  sheet: string
  mapping_digest: string
  sysml_commit_id: string
  documents: Array<{ document: string; limits?: Record<string, Quantity>; changes: LimitChange[]; error?: string }>
  skipped: Array<{ requirement: string; reason: string }>
  held_back: string[]
  changes: number
  failures: number
}

/** The model state a request is about: a commit, or the head of the default branch. */
export type Version = { commit?: string }

export const bdsKeys = {
  all: () => ["bds"] as const,
  workspaces: () => [...bdsKeys.all(), "workspaces"] as const,
  workspace: (ws: string) => [...bdsKeys.workspaces(), ws] as const,
  catalog: (ws: string, commit?: string) => [...bdsKeys.workspace(ws), "catalog", commit ?? "head"] as const,
  mapping: (ws: string) => [...bdsKeys.workspace(ws), "mapping"] as const,
  gates: (ws: string, commit?: string) => [...bdsKeys.workspace(ws), "gates", commit ?? "head"] as const,
  proposals: (ws: string) => [...bdsKeys.workspace(ws), "proposals"] as const,
  lastRun: (ws: string) => [...bdsKeys.workspace(ws), "lastRun"] as const,
  syncPlan: (ws: string, commit?: string) => [...bdsKeys.workspace(ws), "sync", commit ?? "head"] as const,
}

const base = (ws: string) => "/api/projects/bds/workspaces/" + seg(ws)

export const workspacesQuery = queryOptions({
  queryKey: bdsKeys.workspaces(),
  queryFn: ({ signal }) => api<{ workspaces: Workspace[] }>("/api/projects/bds/workspaces", { signal }),
  select: (data) => data.workspaces,
})

export const workspaceQuery = (ws: string) =>
  queryOptions({
    queryKey: [...bdsKeys.workspace(ws), "settings"],
    queryFn: ({ signal }) => api<Workspace>(base(ws), { signal }),
  })

export const catalogQuery = (ws: string, commit?: string) =>
  queryOptions({
    queryKey: bdsKeys.catalog(ws, commit),
    queryFn: ({ signal }) => api<Catalog>(base(ws) + "/catalog", { signal, query: { commit } }),
    staleTime: 30_000,
  })

export const mappingQuery = (ws: string) =>
  queryOptions({
    queryKey: bdsKeys.mapping(ws),
    queryFn: ({ signal }) => api<Mapping>(base(ws) + "/mapping", { signal }),
  })

export const gatesQuery = (ws: string, commit?: string) =>
  queryOptions({
    queryKey: bdsKeys.gates(ws, commit),
    queryFn: ({ signal }) => api<Gates>(base(ws) + "/gates", { signal, query: { commit } }),
  })

/** ``check`` gates every pending proposal (reads Flexo and FreeCAD) -- for the review cards. */
export const proposalsQuery = (ws: string, commit?: string, check = true) =>
  queryOptions({
    queryKey: [...bdsKeys.proposals(ws), commit ?? "head", check],
    queryFn: ({ signal }) =>
      api<{ proposals: Proposal[] }>(base(ws) + "/proposals", {
        signal,
        query: { check: check ? "true" : undefined, commit: check ? commit : undefined },
      }),
    select: (data) => data.proposals,
  })

export const lastRunQuery = (ws: string) =>
  queryOptions({
    queryKey: bdsKeys.lastRun(ws),
    queryFn: ({ signal }) => api<Run>(base(ws) + "/verify/last", { signal }),
    retry: false, // 404 bds_no_run is an answer, not a failure
  })

/** The dry run: what a sync WOULD write. Read-only, so a query. */
export const syncPlanQuery = (ws: string, commit?: string) =>
  queryOptions({
    queryKey: bdsKeys.syncPlan(ws, commit),
    queryFn: ({ signal }) =>
      api<SyncResult>(base(ws) + "/sync", { method: "POST", body: { apply: false, commit }, signal }),
  })

// -- Writes -------------------------------------------------------------------

export function saveWorkspace(name: string, settings: WorkspaceSettings) {
  return api<Workspace>(base(name), { method: "PUT", body: settings })
}

export function propose(ws: string, body: { proposer: "difflib" | "ai"; top: number; dry_run: boolean } & Version) {
  return api<ProposeResult>(base(ws) + "/proposals", { method: "POST", body })
}

export function confirmProposal(ws: string, id: string, body: { requirement?: string } & Version) {
  return api<{ proposal: Proposal; check: GateCheck; written: string[]; part_usable: boolean }>(
    base(ws) + "/proposals/" + seg(id) + "/confirm",
    { method: "POST", body },
  )
}

export function rejectProposal(ws: string, id: string, reason: string) {
  return api<Proposal>(base(ws) + "/proposals/" + seg(id) + "/reject", { method: "POST", body: { reason } })
}

export function runVerify(ws: string, version: Version) {
  return api<Run>(base(ws) + "/verify", { method: "POST", body: version })
}

export function applySync(ws: string, version: Version) {
  return api<SyncResult>(base(ws) + "/sync", { method: "POST", body: { ...version, apply: true } })
}

/** Everything a decision about the mapping changes. */
export function invalidateMapping(queryClient: QueryClient, ws: string) {
  void queryClient.invalidateQueries({ queryKey: bdsKeys.workspace(ws) })
  void queryClient.invalidateQueries({ queryKey: bdsKeys.workspaces(), exact: true })
}
