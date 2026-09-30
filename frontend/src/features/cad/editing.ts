import { useQueryClient } from "@tanstack/react-query"
import { useCallback, useRef, useState } from "react"
import { toast } from "sonner"

import i18n, { TranslatableError } from "@/i18n"
import { ApiError, newRequestId } from "@/lib/api"
import { describeError, sameValue } from "./format"
import { cadKeys, patchObject } from "./queries"
import { beginOwnRequest, endOwnRequest } from "./sync"
import type { ObjectDetail, PropertyEntry, PropertyValue, RevisionConflictDetail, WriteResult } from "./types"

// Writing from the property editor -- with optimistic locking.
//
// When a field is first touched, the editor remembers its value and the
// object's rev (the "base"). On submit:
//   1. Has EXACTLY THIS field changed since then (in FreeCAD or from another
//      tab)? -> show the conflict immediately, without a request.
//   2. Otherwise PATCH with If-Match: <current rev>. Changes to OTHER fields
//      of the same object are not a conflict -- the editor silently moves
//      the base forward ("rebase").
//   3. 409 rev_mismatch (someone was faster in the milliseconds in between):
//      the response carries the current state; if it affects this field,
//      the user decides: reload or overwrite.
// Nothing is ever silently overwritten.

/** error: the cause (ApiError, TranslatableError) -- the text is only built at display time. */
export type CommitOutcome = { ok: true } | { ok: false; error?: unknown; discarded?: boolean }

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

  /** On focus: capture the base that later comparisons are made against. */
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
      // Open only after the current keyboard event (see TextField).
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
    beginOwnRequest(requestId) // the WS echo of this request is ignored
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
          if (theirs && sameValue(theirs.value, base.value)) continue // only other fields -> rebase
          if ((await ask(prop, mine, theirs)) === "discard") return { ok: false, discarded: true }
          base.value = theirs?.value ?? null // "overwrite" refers to THIS state
          continue
        }
        report(result)
        return { ok: true }
      }
      return { ok: false, error: new TranslatableError("editing.keepsChanging") }
    } catch (error) {
      return { ok: false, error }
    } finally {
      bases.current.delete(prop)
      await refresh()
    }
  }

  return { begin, cancel, commit, conflict }
}

function report(result: WriteResult) {
  if (!result.atomic) {
    toast.warning(i18n.t("editing.notAtomicTitle"), {
      description: i18n.t("editing.notAtomicHint"),
    })
  }
  if (result.errors.length) {
    toast.warning(i18n.t("editing.brokenTitle"), {
      description: result.errors.map((error) => error.name + " (" + error.state.join(", ") + ")").join(" · "),
    })
  }
}

/** Toggle visibility -- without a conflict dialog, the state is binary. */
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
