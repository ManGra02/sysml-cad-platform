import type { QueryClient } from "@tanstack/react-query"

import type { Frame } from "@/lib/ws"
import { cadKeys, statusKey } from "./queries"
import type { BridgeStatus, CadEvent, PlatformStatus } from "./types"

// Events from FreeCAD -> targeted invalidation in the query cache.
//
// Events carry only identity, no values: the browser re-reads via the
// normal route. Two rules prevent the property editor from overwriting
// itself while typing:
//   * the echo of an OWN mutation (origin "bridge:<own request id>") is
//     ignored -- the mutation reloads by itself after its response;
//   * queries.ts discards responses with a lower rev than the cache.

// -- Own mutations -------------------------------------------------------

/** How long a completed mutation still counts as "own": the WS event
 *  may also arrive AFTER the HTTP response. */
const ECHO_WINDOW_MS = 5_000

const ownRequests = new Map<string, number>() // id -> expiry time (Infinity = running)

export function beginOwnRequest(id: string) {
  ownRequests.set(id, Infinity)
}

export function endOwnRequest(id: string, now = Date.now()) {
  ownRequests.set(id, now + ECHO_WINDOW_MS)
}

export function isOwnOrigin(origin: string | undefined, now = Date.now()): boolean {
  if (!origin || !origin.startsWith("bridge:")) return false
  for (const [id, expires] of ownRequests) {
    if (expires < now) ownRequests.delete(id)
  }
  return ownRequests.has(origin.slice("bridge:".length))
}

// -- Planning (pure, testable) -------------------------------------------

export type InvalidationPlan = {
  /** everything under ["cad"] */
  all: boolean
  documents: boolean
  /** documents whose cache is discarded entirely */
  docs: Set<string>
  trees: Set<string>
  objects: Array<[string, string]>
}

/** After these events the document is reloaded entirely, not
 *  incrementally: undoing a create fires "deleted", undoing a delete
 *  "created" -- the slots don't say that it was an undo. */
const FULL_RELOAD = new Set(["cad.history", "cad.resync", "doc.opened", "doc.closed"])

const DOCUMENT_LIST = new Set([
  "doc.opened",
  "doc.closed",
  "doc.saved",
  "doc.relabeled",
  "doc.modified",
  "doc.activated",
  "cad.transaction",
  "cad.history",
  "cad.created",
  "cad.deleted",
])

export function planInvalidation(events: CadEvent[], isOwn: (origin?: string) => boolean): InvalidationPlan {
  const plan: InvalidationPlan = {
    all: false,
    documents: false,
    docs: new Set(),
    trees: new Set(),
    objects: [],
  }
  const seen = new Set<string>()

  for (const event of events) {
    if (DOCUMENT_LIST.has(event.type)) plan.documents = true

    if (FULL_RELOAD.has(event.type)) {
      if (event.doc) plan.docs.add(event.doc)
      else plan.all = true
      continue
    }
    if (!event.doc) continue

    switch (event.type) {
      case "cad.recomputed":
        plan.trees.add(event.doc)
        break
      case "cad.created":
      case "cad.deleted":
        // The object itself as well: an open detail view that just showed
        // "does not exist" should display the newly created object.
        plan.trees.add(event.doc)
        if (event.obj) plan.objects.push([event.doc, event.obj])
        break
      case "cad.changed":
      case "cad.schema_changed":
        if (isOwn(event.origin)) break
        plan.trees.add(event.doc) // label, visibility, state live in the tree
        if (event.obj && !seen.has(event.doc + "\u0000" + event.obj)) {
          seen.add(event.doc + "\u0000" + event.obj)
          plan.objects.push([event.doc, event.obj])
        }
        break
    }
  }
  return plan
}

// -- Applying ------------------------------------------------------------

export function applyPlan(queryClient: QueryClient, plan: InvalidationPlan) {
  if (plan.all) {
    void queryClient.invalidateQueries({ queryKey: cadKeys.all })
    return
  }
  if (plan.documents) void queryClient.invalidateQueries({ queryKey: cadKeys.documents() })
  for (const doc of plan.docs) void queryClient.invalidateQueries({ queryKey: cadKeys.doc(doc) })
  for (const doc of plan.trees) {
    if (plan.docs.has(doc)) continue
    void queryClient.invalidateQueries({ queryKey: cadKeys.trees(doc) })
    void queryClient.invalidateQueries({ queryKey: cadKeys.batches(doc) })
  }
  for (const [doc, name] of plan.objects) {
    if (plan.docs.has(doc)) continue
    void queryClient.invalidateQueries({ queryKey: cadKeys.object(doc, name) })
    void queryClient.invalidateQueries({ queryKey: cadKeys.geometry(doc, name) })
  }
}

// -- Frames from the backend ---------------------------------------------

let lastSession: string | null | undefined = undefined

function setBridgeStatus(queryClient: QueryClient, bridge: BridgeStatus) {
  // Otherwise an in-flight GET /api/status could arrive AFTER this frame
  // and overwrite the newer state with an older one.
  void queryClient.cancelQueries({ queryKey: statusKey })
  queryClient.setQueryData<PlatformStatus>(statusKey, (old) => ({
    backend: old?.backend ?? { contract_version: bridge.contract.backend, clients: 0 },
    bridge,
  }))
  if (bridge.state !== "ok") return
  // New bridge session: rev starts over. The cache is therefore RESET
  // instead of merely invalidated -- otherwise the rev lock in queries.ts
  // would hold on to the old (higher) states.
  if (lastSession !== undefined && bridge.session_id !== lastSession) {
    void queryClient.resetQueries({ queryKey: cadKeys.all })
  } else {
    void queryClient.invalidateQueries({ queryKey: cadKeys.all })
  }
  lastSession = bridge.session_id
}

export function handleFrame(queryClient: QueryClient, frame: Frame) {
  switch (frame.type) {
    case "hello":
      // Every (re)connect: whatever happened in the meantime is unknown.
      setBridgeStatus(queryClient, frame.bridge as BridgeStatus)
      break
    case "bridge.status":
      setBridgeStatus(queryClient, frame.status as BridgeStatus)
      break
    case "events": {
      const events = (frame.events as CadEvent[]) ?? []
      const resync = events.find((event) => event.type === "cad.resync")
      if (resync && resync.session_id !== undefined && resync.session_id !== lastSession) {
        lastSession = resync.session_id
        void queryClient.resetQueries({ queryKey: cadKeys.all })
        return
      }
      applyPlan(queryClient, planInvalidation(events, (origin) => isOwnOrigin(origin)))
      break
    }
  }
}
