import { useTranslation } from "react-i18next"

import { Badge } from "@/components/ui/badge"

const ERROR_STATES = new Set(["Invalid", "Error", "RecomputeError"])

/** FreeCAD's object state: erroneous or "needs to be recomputed". */
export function StateBadges({ state }: { state: string[] }) {
  const { t } = useTranslation()
  const errors = state.filter((flag) => ERROR_STATES.has(flag))
  const touched = state.includes("Touched")
  return (
    <>
      {errors.length > 0 && <Badge variant="destructive">{errors.join(", ")}</Badge>}
      {touched && (
        <Badge variant="outline" className="border-warning text-warning" title={t("state.touchedHint")}>
          {t("state.touched")}
        </Badge>
      )}
    </>
  )
}

export function stateTone(state: string[]): "error" | "touched" | null {
  if (state.some((flag) => ERROR_STATES.has(flag))) return "error"
  if (state.includes("Touched")) return "touched"
  return null
}
