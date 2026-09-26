import type { QueryClient } from "@tanstack/react-query"

import type { Frame } from "@/lib/ws"
import { cadKeys, statusKey } from "./queries"
import type { BridgeStatus, CadEvent, PlatformStatus } from "./types"

// Ereignisse aus FreeCAD -> gezielte Invalidierung im Query-Cache.
//
// Ereignisse tragen nur Identitaet, keine Werte: der Browser liest ueber die
// normale Route nach. Zwei Regeln verhindern, dass sich der Property-Editor
// beim Tippen selbst ueberschreibt:
//   * das Echo einer EIGENEN Mutation (origin "bridge:<eigene Request-Id>")
//     wird ignoriert -- die Mutation laedt nach ihrer Antwort selbst nach;
//   * Antworten mit kleinerem rev als im Cache verwirft queries.ts.

// -- Eigene Mutationen ---------------------------------------------------

/** Wie lange eine abgeschlossene Mutation noch als "eigene" gilt: das
 *  WS-Ereignis kann auch NACH der HTTP-Antwort eintreffen. */
const ECHO_WINDOW_MS = 5_000

const ownRequests = new Map<string, number>() // id -> Ablaufzeitpunkt (Infinity = laeuft)

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

// -- Planung (rein, testbar) ---------------------------------------------

export type InvalidationPlan = {
  /** alles unter ["cad"] */
  all: boolean
  documents: boolean
  /** Dokumente, deren Cache komplett verworfen wird */
  docs: Set<string>
  trees: Set<string>
  objects: Array<[string, string]>
}

/** Nach diesen Ereignissen wird das Dokument komplett neu geladen, nicht
 *  inkrementell: Undo eines Create feuert "deleted", Undo eines Delete
 *  "created" -- die Slots sagen nicht, dass es ein Undo war. */
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
        // Auch das Objekt selbst: eine offene Detailansicht, die eben noch
        // "gibt es nicht" zeigte, soll das neu angelegte Objekt anzeigen.
        plan.trees.add(event.doc)
        if (event.obj) plan.objects.push([event.doc, event.obj])
        break
      case "cad.changed":
      case "cad.schema_changed":
        if (isOwn(event.origin)) break
        plan.trees.add(event.doc) // Label, Sichtbarkeit, Zustand stehen im Baum
        if (event.obj && !seen.has(event.doc + "\u0000" + event.obj)) {
          seen.add(event.doc + "\u0000" + event.obj)
          plan.objects.push([event.doc, event.obj])
        }
        break
    }
  }
  return plan
}

// -- Anwenden ------------------------------------------------------------

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

// -- Rahmen vom Backend --------------------------------------------------

let lastSession: string | null | undefined = undefined

function setBridgeStatus(queryClient: QueryClient, bridge: BridgeStatus) {
  // Ein laufender GET /api/status koennte sonst NACH diesem Frame ankommen
  // und den neueren Zustand mit einem aelteren ueberschreiben.
  void queryClient.cancelQueries({ queryKey: statusKey })
  queryClient.setQueryData<PlatformStatus>(statusKey, (old) => ({
    backend: old?.backend ?? { contract_version: bridge.contract.backend, clients: 0 },
    bridge,
  }))
  if (bridge.state !== "ok") return
  // Neue Bruecken-Sitzung: rev beginnt von vorn. Der Cache wird deshalb
  // ZURUECKGESETZT statt nur invalidiert -- sonst hielte die rev-Sperre in
  // queries.ts die alten (hoeheren) Staende fest.
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
      // Jeder (Wieder-)Aufbau: was in der Zwischenzeit geschah, ist unbekannt.
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
