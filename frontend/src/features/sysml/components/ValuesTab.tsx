import { Search } from "lucide-react"
import { useMemo, useState } from "react"
import { useTranslation } from "react-i18next"

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"

import type { SysmlAttribute, SysmlElement, SysmlSnapshot } from "../queries"
import { AttributeRows } from "./AttributeRows"

/** "All values" tab: every attribute of the model, filterable by part or attribute name. */
export function ValuesTab({ snapshot }: { snapshot: SysmlSnapshot }) {
  const { t } = useTranslation()
  const [filter, setFilter] = useState("")
  const owners = useMemo(() => new Map(snapshot.elements.map((e) => [e.id, e])), [snapshot])
  const rows = filterAndSort(snapshot.attributes, owners, filter)

  return (
    <Card className="gap-3 py-4">
      <CardHeader className="px-4">
        <CardTitle className="text-sm">{t("sysml.attributes.title")}</CardTitle>
        <CardDescription className="text-xs">{t("sysml.attributes.hint")}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3 px-4">
        <div className="relative w-72 max-w-full">
          <Search className="absolute top-2.5 left-2.5 size-3.5 text-muted-foreground" />
          <Input
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            placeholder={t("sysml.attributes.filter")}
            aria-label={t("sysml.attributes.filter")}
            className="pl-8"
          />
        </div>
        {rows.length === 0 ? (
          <p className="text-sm text-muted-foreground">{t("sysml.attributes.none")}</p>
        ) : (
          <AttributeRows attributes={rows} owners={owners} />
        )}
      </CardContent>
    </Card>
  )
}

/** Matches on the attribute or its part name (case-insensitive); sorted by part, then attribute. */
function filterAndSort(attributes: SysmlAttribute[], owners: Map<string, SysmlElement>, filter: string) {
  const needle = filter.trim().toLowerCase()
  const ownerName = (a: SysmlAttribute) => owners.get(a.owner_id)?.name ?? ""
  return attributes
    .filter((a) => !needle || a.name.toLowerCase().includes(needle) || ownerName(a).toLowerCase().includes(needle))
    .sort((a, b) => ownerName(a).localeCompare(ownerName(b)) || a.name.localeCompare(b.name))
}
