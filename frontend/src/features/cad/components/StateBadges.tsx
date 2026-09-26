import { Badge } from "@/components/ui/badge"

const ERROR_STATES = new Set(["Invalid", "Error", "RecomputeError"])

/** FreeCADs Objektzustand: fehlerhaft oder "muss neu berechnet werden". */
export function StateBadges({ state }: { state: string[] }) {
  const errors = state.filter((flag) => ERROR_STATES.has(flag))
  const touched = state.includes("Touched")
  return (
    <>
      {errors.length > 0 && <Badge variant="destructive">{errors.join(", ")}</Badge>}
      {touched && (
        <Badge variant="outline" className="border-warning text-warning" title="Muss neu berechnet werden">
          geändert
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
