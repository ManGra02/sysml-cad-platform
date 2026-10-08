import { useMemo, useState } from "react"
import { useTranslation } from "react-i18next"

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"

import { leafParts, partTree, type SysmlSnapshot } from "../queries"
import { ElementDetails } from "./ElementDetails"
import { PartTree } from "./PartTree"

/** "Structure" tab: the part tree on the left, the selected part's details on the right. */
export function StructureTab({ snapshot }: { snapshot: SysmlSnapshot }) {
  const { t } = useTranslation()
  const tree = useMemo(() => partTree(snapshot), [snapshot])
  const leafIds = useMemo(() => new Set(leafParts(snapshot).map((l) => l.id)), [snapshot])
  const [selected, setSelected] = useState<string | null>(null)

  // Nothing clicked yet (or the part vanished in a newer version): show the first part.
  const current =
    (selected && snapshot.elements.find((e) => e.id === selected)) ||
    snapshot.elements.find((e) => e.kind === "part") ||
    null

  return (
    <div className="grid gap-4 md:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]">
      <Card className="gap-2 py-3">
        <CardHeader className="px-4">
          <CardTitle className="text-sm">{t("sysml.tree.title")}</CardTitle>
          <CardDescription className="text-xs">{t("sysml.tree.hint")}</CardDescription>
        </CardHeader>
        <CardContent className="px-2">
          {tree.length === 0 ? (
            <p className="px-2 py-4 text-sm text-muted-foreground">{t("sysml.tree.empty")}</p>
          ) : (
            <PartTree nodes={tree} selected={current?.id ?? null} onSelect={setSelected} leafIds={leafIds} />
          )}
        </CardContent>
      </Card>
      {current && <ElementDetails snapshot={snapshot} element={current} onSelect={setSelected} />}
    </div>
  )
}
