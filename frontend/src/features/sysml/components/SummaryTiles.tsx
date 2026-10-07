import { Box, ClipboardCheck, Layers, Ruler, type LucideIcon } from "lucide-react"
import { useMemo } from "react"
import { useTranslation } from "react-i18next"

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"

import { leafParts, requirementsOf, type SysmlSnapshot } from "../queries"

/** The four numbers at the top: parts, leaf parts, values, requirements. */
export function SummaryTiles({ snapshot }: { snapshot: SysmlSnapshot }) {
  const { t } = useTranslation()
  const counts = useMemo(
    () => ({
      parts: snapshot.elements.filter((e) => e.kind === "part").length,
      leaves: leafParts(snapshot).length,
      attributes: snapshot.attributes.length,
      requirements: requirementsOf(snapshot).length,
    }),
    [snapshot],
  )

  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
      <Tile icon={Box} label={t("sysml.tiles.parts")} value={counts.parts} hint={t("sysml.tiles.partsHint")} />
      <Tile icon={Layers} label={t("sysml.tiles.leaves")} value={counts.leaves} hint={t("sysml.tiles.leavesHint")} />
      <Tile
        icon={Ruler}
        label={t("sysml.tiles.attributes")}
        value={counts.attributes}
        hint={t("sysml.tiles.attributesHint")}
      />
      <Tile
        icon={ClipboardCheck}
        label={t("sysml.tiles.requirements")}
        value={counts.requirements}
        hint={t("sysml.tiles.requirementsHint")}
      />
    </div>
  )
}

function Tile({ icon: Icon, label, value, hint }: { icon: LucideIcon; label: string; value: number; hint: string }) {
  return (
    <Card className="gap-1 py-4" title={hint}>
      <CardHeader className="px-4">
        <CardDescription className="flex items-center gap-1.5 text-xs">
          <Icon className="size-3.5" />
          {label}
        </CardDescription>
        <CardTitle className="text-2xl tabular-nums">{value}</CardTitle>
      </CardHeader>
      <CardContent className="px-4 text-xs text-muted-foreground">{hint}</CardContent>
    </Card>
  )
}
