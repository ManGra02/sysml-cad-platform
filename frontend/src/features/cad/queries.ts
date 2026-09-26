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

// Query-Keys: alles eines Dokuments liegt unter ["cad", "doc", <name>], damit
// ein Ereignis wie cad.history das ganze Dokument auf einmal verwerfen kann.
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
  // Massgeblich ist der WebSocket (hello + bridge.status); der GET liefert
  // nur den Anfangszustand.
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
 * Eine Antwort mit kleinerem rev als im Cache ist veraltet und wird verworfen.
 * Innerhalb einer Bruecken-Sitzung steigt rev monoton; bei einer neuen Sitzung
 * wird der Cache ohnehin zurueckgesetzt (siehe sync.ts).
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

/** Abgeleitete Geometrie ist teuer (FreeCAD cacht Shape.Volume nicht) -- nur auf Anforderung. */
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

/** Batch-Route: alle Objekte mit ausgewaehlten Properties in EINER Dispatch-Runde. */
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
