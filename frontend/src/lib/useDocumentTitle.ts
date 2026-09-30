import { useEffect } from "react"

const APP = "SysML-CAD Platform"

/** Descriptive tab title: most specific first, app name last ("Box · Doc · CAD-Explorer"). */
export function useDocumentTitle(...parts: Array<string | null | undefined | false>) {
  const title = [...parts.filter(Boolean), APP].join(" · ")
  useEffect(() => {
    document.title = title
  }, [title])
}
