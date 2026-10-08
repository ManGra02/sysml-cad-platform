import { ClipboardCheck } from "lucide-react"
import { useMemo } from "react"
import { useTranslation } from "react-i18next"

import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"

import { requirementsOf, type SysmlElement, type SysmlSnapshot } from "../queries"

/** "Requirements" tab: each requirement with the parts that satisfy it -- or a warning if none does. */
export function RequirementsTab({ snapshot }: { snapshot: SysmlSnapshot }) {
  const { t } = useTranslation()
  const requirements = useMemo(() => requirementsOf(snapshot), [snapshot])
  const satisfiedBy = useMemo(() => satisfierNames(snapshot), [snapshot])

  if (requirements.length === 0) {
    return (
      <p className="rounded-md border border-dashed p-8 text-center text-sm text-muted-foreground">
        {t("sysml.requirements.none")}
      </p>
    )
  }
  return (
    <div className="grid gap-3 md:grid-cols-2">
      {requirements.map((r) => (
        <RequirementCard key={r.id} requirement={r} satisfiedBy={satisfiedBy.get(r.id) ?? []} />
      ))}
    </div>
  )
}

function RequirementCard({ requirement: r, satisfiedBy }: { requirement: SysmlElement; satisfiedBy: string[] }) {
  const { t } = useTranslation()
  return (
    <Card className="gap-2 py-4">
      <CardHeader className="px-4">
        <CardTitle className="flex items-center gap-2 text-sm">
          <ClipboardCheck className="size-4 text-muted-foreground" />
          {r.extra.req_id && <span className="font-mono">{r.extra.req_id}</span>}
          <span className="truncate text-muted-foreground">{r.name}</span>
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-2 px-4 text-sm">
        <p>{r.extra.text || r.doc || "—"}</p>
        <p className="flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
          {satisfiedBy.length > 0 ? (
            <>
              {t("sysml.requirements.satisfiedBy")}
              {satisfiedBy.map((name) => (
                <Badge key={name} variant="secondary">
                  {name}
                </Badge>
              ))}
            </>
          ) : (
            <Badge variant="outline" className="border-warning text-warning">
              {t("sysml.requirements.notSatisfied")}
            </Badge>
          )}
        </p>
      </CardContent>
    </Card>
  )
}

/** requirement id -> names of the parts that satisfy it (from the "satisfies" relations). */
function satisfierNames(snapshot: SysmlSnapshot): Map<string, string[]> {
  const names = new Map(snapshot.elements.map((e) => [e.id, e.name]))
  const out = new Map<string, string[]>()
  for (const rel of snapshot.relations) {
    if (rel.kind !== "satisfies") continue
    const name = names.get(rel.source_id)
    if (name) out.set(rel.target_id, [...(out.get(rel.target_id) ?? []), name])
  }
  return out
}
