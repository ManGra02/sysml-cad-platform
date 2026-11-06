import { createContext, createElement, useContext, useEffect, useId, type ReactNode } from "react"

const APP = "SysML-CAD Platform"

// Frames (ProjectFrame) set a title for everything inside them, and a page inside a
// frame sets a more specific one. React runs a parent's effects AFTER its children's,
// so "last write wins" would always leave the frame's title. Instead every title is
// registered with its depth; the deepest one is shown.
const Depth = createContext(0)
const registered = new Map<string, { depth: number; title: string }>()

function apply() {
  let best: { depth: number; title: string } | undefined
  for (const entry of registered.values()) if (!best || entry.depth >= best.depth) best = entry
  if (best) document.title = best.title
}

/** Descriptive tab title: most specific first, app name last ("Box · Doc · CAD-Explorer"). */
export function useDocumentTitle(...parts: Array<string | null | undefined | false>) {
  const title = [...parts.filter(Boolean), APP].join(" · ")
  const depth = useContext(Depth)
  const id = useId()
  useEffect(() => {
    registered.set(id, { depth, title })
    apply()
    return () => {
      registered.delete(id)
      apply()
    }
  }, [id, depth, title])
}

/** Marks everything inside as more specific than the component rendering it. */
export function TitleScope({ children }: { children: ReactNode }) {
  const depth = useContext(Depth)
  return createElement(Depth.Provider, { value: depth + 1 }, children)
}
