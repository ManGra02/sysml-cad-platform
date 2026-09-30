import { queryOptions, replaceEqualDeep } from "@tanstack/react-query"

import { api, newRequestId, seg } from "@/lib/api"
import type {
  DocumentList,
  Geometry,
  ObjectBatch,
  ObjectDetail,
  PlatformStatus,
  Selection,
  Tree,
  WriteResult,
} from "./types"

// Query keys: everything of a document lives under ["cad", "doc", <name>], so
// that an event like cad.history can discard the whole document at once.
export const cadKeys = {
  all: ["cad"] as const,
  documents: () => ["cad", "documents"] as const,
  doc: (doc: string) => ["cad", "doc", doc] as const,
  tree: (doc: string, internal: boolean) => ["cad", "doc", doc, "tree", { internal }] as const,
  trees: (doc: string) => ["cad", "doc", doc, "tree"] as const,
  object: (doc: string, name: string) => ["cad", "doc", doc, "object", name] as const,
  geometry: (doc: string, name: string) => ["cad", "doc", doc, "geometry", name] as const,
  batches: (doc: string) => ["cad", "doc", doc, "batch"] as const,
  batch: (doc: string, fields: string[]) => ["cad", "doc", doc, "batch", fields] as const,
}

export const statusKey = ["status"] as const

const base = (doc: string) => "/api/cad/documents/" + seg(doc)

export const statusQuery = queryOptions({
  queryKey: statusKey,
  queryFn: () => api<PlatformStatus>("/api/status"),
  // The WebSocket is authoritative (hello + bridge.status); the GET only
  // provides the initial state.
  staleTime: Infinity,
})

export const documentsQuery = queryOptions({
  queryKey: cadKeys.documents(),
  queryFn: () => api<DocumentList>("/api/cad/documents"),
})

export const treeQuery = (doc: string, internal: boolean) =>
  queryOptions({
    queryKey: cadKeys.tree(doc, internal),
    queryFn: () => api<Tree>(base(doc) + "/tree", { query: { include: internal ? "internal" : undefined } }),
  })

/**
 * A response with a lower rev than the cache is stale and gets discarded.
 * Within a bridge session rev increases monotonically; on a new session the
 * cache is reset anyway (see sync.ts).
 */
function keepNewerRevision(old: unknown, next: unknown): unknown {
  const previous = old as ObjectDetail | undefined
  const incoming = next as ObjectDetail | undefined
  if (previous && incoming && incoming.rev < previous.rev) return previous
  return replaceEqualDeep(old, next)
}

export const objectQuery = (doc: string, name: string) =>
  queryOptions({
    queryKey: cadKeys.object(doc, name),
    queryFn: () => api<ObjectDetail>(base(doc) + "/objects/" + seg(name)),
    structuralSharing: keepNewerRevision,
  })

/** Derived geometry is expensive (FreeCAD doesn't cache Shape.Volume) -- only on demand. */
export const geometryQuery = (doc: string, name: string) =>
  queryOptions({
    queryKey: cadKeys.geometry(doc, name),
    queryFn: async () => {
      const data = await api<ObjectDetail>(base(doc) + "/objects/" + seg(name), {
        query: { include: "geometry", fields: "Label" },
      })
      return data.geometry ?? null
    },
  })

/** Batch route: all objects with selected properties in ONE dispatch round. */
export const batchQuery = (doc: string, fields: string[]) =>
  queryOptions({
    queryKey: cadKeys.batch(doc, fields),
    queryFn: () => api<ObjectBatch>(base(doc) + "/objects", { query: { fields: fields.join(",") } }),
    enabled: fields.length > 0,
  })

export function patchObject(args: {
  doc: string
  name: string
  changes: Record<string, unknown>
  requestId?: string
  ifMatch?: number
}) {
  return api<WriteResult>(base(args.doc) + "/objects/" + seg(args.name), {
    method: "PATCH",
    body: args.changes,
    requestId: args.requestId ?? newRequestId(),
    ifMatch: args.ifMatch,
  })
}

export function getSelection() {
  return api<Selection>("/api/cad/selection")
}

export function showInFreeCAD(doc: string, name: string) {
  return api<{ selected: unknown[]; zoomed: boolean }>("/api/cad/selection", {
    method: "PUT",
    body: { refs: [{ doc, name }], zoom: true },
  })
}

export function recomputeDocument(doc: string) {
  return api<{ recomputed: number }>(base(doc) + "/recompute", {
    method: "POST",
    requestId: newRequestId(),
  })
}

export type { Geometry }
