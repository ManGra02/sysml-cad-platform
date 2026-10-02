import { queryOptions } from "@tanstack/react-query"

import { api, seg } from "@/lib/api"

// The SysML side of the platform: the backend reads the SysML v2 model from
// Flexo MMS (backend/app/sysml) and hands it to the browser as the common
// engineering model. The browser never talks to Flexo itself.

export type SysmlStatus = {
  url: string
  reachable: boolean
  projects?: number
  code?: string
  message?: string
}

export type SysmlProject = {
  id: string
  name: string
  description: string | null
  defaultBranch: string | null
  created: string | null
}

export type SysmlCommit = {
  id: string
  created: string | null
  description: string | null
  previous: string | string[] | null
}

export type SysmlElement = {
  id: string
  name: string
  kind: string
  source: string
  native_type: string
  qualified_name: string
  parent_id: string | null
  type_ids: string[]
  short_name: string | null
  doc: string | null
  is_definition: boolean
  extra: { req_id?: string | null; text?: string | null; [key: string]: unknown }
}

export type SysmlAttribute = {
  id: string
  owner_id: string
  name: string
  value: number | boolean | string | null
  unit: string | null
  value_si: number | null
  unit_si: string | null
  expression: string | null
  value_element_id: string | null
  warnings: string[]
}

export type SysmlRelation = {
  source_id: string
  target_id: string
  kind: string
  id: string | null
}

export type SysmlSnapshot = {
  source: string
  project_id: string
  version: string
  branch_id: string | null
  retrieved_at: string
  stats: Record<string, number>
  elements: SysmlElement[]
  attributes: SysmlAttribute[]
  relations: SysmlRelation[]
  warnings: string[]
}

export const sysmlKeys = {
  all: ["sysml"] as const,
  status: () => [...sysmlKeys.all, "status"] as const,
  projects: () => [...sysmlKeys.all, "projects"] as const,
  snapshot: (project: string) => [...sysmlKeys.all, "snapshot", project] as const,
  commits: (project: string) => [...sysmlKeys.all, "commits", project] as const,
}

export const sysmlStatusQuery = queryOptions({
  queryKey: sysmlKeys.status(),
  queryFn: ({ signal }) => api<SysmlStatus>("/api/sysml/status", { signal }),
  refetchInterval: 10_000,
})

export const sysmlProjectsQuery = queryOptions({
  queryKey: sysmlKeys.projects(),
  queryFn: ({ signal }) => api<SysmlProject[]>("/api/sysml/projects", { signal }),
})

export const sysmlSnapshotQuery = (project: string) =>
  queryOptions({
    queryKey: sysmlKeys.snapshot(project),
    queryFn: ({ signal }) => api<SysmlSnapshot>("/api/sysml/projects/" + seg(project) + "/snapshot", { signal }),
  })

export const sysmlCommitsQuery = (project: string) =>
  queryOptions({
    queryKey: sysmlKeys.commits(project),
    queryFn: ({ signal }) => api<SysmlCommit[]>("/api/sysml/projects/" + seg(project) + "/commits", { signal }),
  })

// -- Helpers on a snapshot (pure, unit-tested) --------------------------------

export type SysmlTreeNode = { element: SysmlElement; children: SysmlTreeNode[] }

const TREE_KINDS = new Set(["part", "package"])

/** The part tree: part usages under their owning part (packages as roots). */
export function partTree(snapshot: SysmlSnapshot): SysmlTreeNode[] {
  const parts = snapshot.elements.filter((e) => TREE_KINDS.has(e.kind))
  const ids = new Set(parts.map((e) => e.id))
  const byParent = new Map<string | null, SysmlElement[]>()
  for (const e of parts) {
    const parent = e.parent_id && ids.has(e.parent_id) ? e.parent_id : null
    byParent.set(parent, [...(byParent.get(parent) ?? []), e])
  }
  const build = (parent: string | null, seen: Set<string>): SysmlTreeNode[] =>
    (byParent.get(parent) ?? [])
      .filter((e) => !seen.has(e.id))
      .sort((a, b) => a.name.localeCompare(b.name))
      .map((e) => ({ element: e, children: build(e.id, new Set([...seen, e.id])) }))
  // Packages without any part below them are noise in a part tree.
  const prune = (nodes: SysmlTreeNode[]): SysmlTreeNode[] =>
    nodes
      .map((n) => ({ ...n, children: prune(n.children) }))
      .filter((n) => n.element.kind !== "package" || n.children.length > 0)
  return prune(build(null, new Set()))
}

/** Leaf parts = part usages without child parts (candidates for "missing CAD"). */
export function leafParts(snapshot: SysmlSnapshot): SysmlElement[] {
  const parts = snapshot.elements.filter((e) => e.kind === "part")
  const parents = new Set(parts.map((p) => p.parent_id))
  return parts.filter((p) => !parents.has(p.id))
}

export function requirementsOf(snapshot: SysmlSnapshot): SysmlElement[] {
  return snapshot.elements.filter((e) => e.kind === "requirement" || e.kind === "requirement_def")
}

/** Value as a human reads it: "9.8 kg", "true", "—". */
export function formatAttribute(attribute: Pick<SysmlAttribute, "value" | "unit" | "expression">): string {
  const { value, unit } = attribute
  if (value === null || value === undefined) return attribute.expression ?? "—"
  if (typeof value === "number") return formatPlain(value) + (unit ? " " + unit : "")
  return String(value) + (unit ? " " + unit : "")
}

export function formatSi(attribute: Pick<SysmlAttribute, "value_si" | "unit_si">): string | null {
  if (attribute.value_si === null || attribute.value_si === undefined) return null
  return formatPlain(attribute.value_si) + (attribute.unit_si ? " " + attribute.unit_si : "")
}

function formatPlain(value: number): string {
  return Number.isInteger(value) ? String(value) : String(Number(value.toPrecision(12)))
}
