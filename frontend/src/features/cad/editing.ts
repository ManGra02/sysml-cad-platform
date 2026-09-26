import { useQueryClient } from "@tanstack/react-query"
import { useCallback, useRef, useState } from "react"
import { toast } from "sonner"

import { ApiError, newRequestId } from "@/lib/api"
import { describeError, sameValue } from "./format"
import { cadKeys, patchObject } from "./queries"
import { beginOwnRequest, endOwnRequest } from "./sync"
import type { ObjectDetail, PropertyEntry, PropertyValue, RevisionConflictDetail, WriteResult } from "./types"

// Schreiben aus dem Property-Editor -- mit optimistischer Sperre.
//
// Beim ersten Anfassen eines Feldes merkt sich der Editor den Wert und den rev
// des Objekts ("Basis"). Beim Absenden:
//   1. Hat sich GENAU DIESES Feld seitdem geaendert (in FreeCAD oder von einem
//      anderen Tab)? -> Konflikt sofort anzeigen, ohne Anfrage.
//   2. Sonst PATCH mit If-Match: <aktueller rev>. Aenderungen an ANDEREN
//      Feldern desselben Objekts sind kein Konflikt -- der Editor zieht die
//      Basis still nach ("rebase").
//   3. 409 rev_mismatch (jemand war in den Millisekunden dazwischen schneller):
//      die Antwort traegt den aktuellen Stand; betrifft er dieses Feld,
//      entscheidet der Nutzer: neu laden oder ueberschreiben.
// Nichts wird still ueberschrieben.

export type CommitOutcome = { ok: true } | { ok: false; message?: string; discarded?: boolean }

export type Conflict = {
  objectLabel: string
  prop: string
  mine: string
  theirs: PropertyEntry | undefined
  resolve: (choice: "overwrite" | "discard") => void
}

type Base = { rev: number; value: PropertyValue }

const MAX_ATTEMPTS = 4

export function useObjectEditor(doc: string, name: string) {
  const queryClient = useQueryClient()
  const key = cadKeys.object(doc, name)
  const bases = useRef(new Map<string, Base>())
  const [conflict, setConflict] = useState<Conflict | null>(null)

  const current = useCallback(() => queryClient.getQueryData<ObjectDetail>(key), [queryClient, doc, name])

  /** Beim Fokus: die Basis festhalten, gegen die spaeter verglichen wird. */
  const begin = useCallback(
    (entry: PropertyEntry) => {
      if (bases.current.has(entry.name)) return
      bases.current.set(entry.name, { rev: current()?.rev ?? 0, value: entry.value })
    },
    [current],
  )

  const cancel = useCallback((prop: string) => {
    bases.current.delete(prop)
  }, [])

  const ask = (prop: string, mine: string, theirs: PropertyEntry | undefined) =>
    new Promise<"overwrite" | "discard">((resolve) => {
      // Erst nach dem laufenden Tastatur-Ereignis oeffnen (siehe TextField).
      setTimeout(() => setConflict({
        objectLabel: current()?.label ?? name,
        prop,
        mine,
        theirs,
        resolve: (choice) => {
          setConflict(null)
          resolve(choice)
        },
      }))
    })

  const refresh = () =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey: key }),
      queryClient.invalidateQueries({ queryKey: cadKeys.geometry(doc, name) }),
      queryClient.invalidateQueries({ queryKey: cadKeys.trees(doc) }),
      queryClient.invalidateQueries({ queryKey: cadKeys.batches(doc) }),
      queryClient.invalidateQueries({ queryKey: cadKeys.documents() }),
    ])

  const send = async (changes: Record<string, unknown>, ifMatch: number | undefined) => {
    const requestId = newRequestId()
    beginOwnRequest(requestId) // das WS-Echo dieser Anfrage wird ignoriert
    try {
      return await patchObject({ doc, name, changes, requestId, ifMatch })
    } finally {
      endOwnRequest(requestId)
    }
  }

  const commit = async (entry: PropertyEntry, payload: unknown, mine: string): Promise<CommitOutcome> => {
    const prop = entry.name
    const latest = current()
    const base = bases.current.get(prop) ?? { rev: latest?.rev ?? 0, value: entry.value }
    let rev = latest?.rev ?? base.rev

    try {
      const latestEntry = latest?.properties.find((p) => p.name === prop)
      if (latestEntry && !sameValue(latestEntry.value, base.value)) {
        if ((await ask(prop, mine, latestEntry)) === "discard") return { ok: false, discarded: true }
        base.value = latestEntry.value
      }

      for (let attempt = 1; attempt <= MAX_ATTEMPTS; attempt++) {
        let result: WriteResult
        try {
          result = await send({ [prop]: payload }, rev)
        } catch (error) {
          if (!(error instanceof ApiError && error.code === "rev_mismatch")) throw error
          const detail = error.detail as RevisionConflictDetail
          queryClient.setQueryData(key, detail.object)
          rev = detail.current
          const theirs = detail.object.properties.find((p) => p.name === prop)
          if (theirs && sameValue(theirs.value, base.value)) continue // nur andere Felder -> rebase
          if ((await ask(prop, mine, theirs)) === "discard") return { ok: false, discarded: true }
          base.value = theirs?.value ?? null // "ueberschreiben" bezieht sich auf DIESEN Stand
          continue
        }
        report(result)
        return { ok: true }
      }
      return { ok: false, message: "Das Objekt aendert sich gerade laufend -- bitte erneut versuchen." }
    } catch (error) {
      return { ok: false, message: describeError(error) }
    } finally {
      bases.current.delete(prop)
      await refresh()
    }
  }

  return { begin, cancel, commit, conflict }
}

function report(result: WriteResult) {
  if (!result.atomic) {
    toast.warning("Änderung übernommen, aber nicht als eigener Undo-Schritt", {
      description: "Ein FreeCAD-Befehl lief gleichzeitig; Strg+Z nimmt beides zusammen zurück.",
    })
  }
  if (result.errors.length) {
    toast.warning("Nach dem Neuberechnen sind Objekte fehlerhaft", {
      description: result.errors.map((error) => error.name + " (" + error.state.join(", ") + ")").join(" · "),
    })
  }
}

/** Sichtbarkeit umschalten -- ohne Konfliktdialog, der Zustand ist binaer. */
export async function toggleVisibility(queryClient: ReturnType<typeof useQueryClient>, doc: string, name: string, visible: boolean) {
  const requestId = newRequestId()
  beginOwnRequest(requestId)
  try {
    await patchObject({ doc, name, changes: { Visibility: visible }, requestId })
  } catch (error) {
    toast.error(describeError(error))
  } finally {
    endOwnRequest(requestId)
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: cadKeys.trees(doc) }),
      queryClient.invalidateQueries({ queryKey: cadKeys.object(doc, name) }),
    ])
  }
}
