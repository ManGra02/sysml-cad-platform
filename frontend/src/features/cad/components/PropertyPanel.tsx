import { useQuery } from "@tanstack/react-query"
import { Box, ChevronDown, Crosshair, FunctionSquare, Lock, Ruler, Search } from "lucide-react"
import { useMemo, useState } from "react"
import { toast } from "sonner"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { ApiError } from "@/lib/api"
import { cn } from "@/lib/utils"
import { useObjectEditor } from "../editing"
import { describeError, formatNumber } from "../format"
import { geometryQuery, objectQuery, showInFreeCAD } from "../queries"
import type { PropertyEntry, Tree } from "../types"
import { ConflictDialog } from "./ConflictDialog"
import { PropertyField, fieldKind, type FieldContext } from "./PropertyFields"
import { StateBadges } from "./StateBadges"

export function PropertyPanel({
  doc,
  name,
  tree,
  onNavigate,
}: {
  doc: string
  name: string
  tree: Tree | undefined
  onNavigate: (name: string) => void
}) {
  const query = useQuery(objectQuery(doc, name))
  const editor = useObjectEditor(doc, name)
  const [filter, setFilter] = useState("")
  const [showGeometry, setShowGeometry] = useState(false)
  const [showHidden, setShowHidden] = useState(false)

  const labels = useMemo(() => {
    const map: Record<string, string> = {}
    for (const node of Object.values(tree?.nodes ?? {})) map[node.name] = node.label
    return map
  }, [tree])
  const objects = useMemo(() => Object.values(tree?.nodes ?? {}), [tree])

  if (query.isPending) return <PanelSkeleton />
  if (query.isError) {
    const gone = query.error instanceof ApiError && query.error.code === "object_not_found"
    return (
      <div className="p-6 text-sm text-muted-foreground">
        {gone ? "Das Objekt gibt es nicht mehr – vermutlich wurde es in FreeCAD gelöscht." : describeError(query.error)}
      </div>
    )
  }

  const data = query.data
  const ctx: FieldContext = {
    begin: editor.begin,
    cancel: editor.cancel,
    commit: editor.commit,
    labels,
    objects,
    self: name,
    navigate: onNavigate,
  }

  // Wie FreeCADs eigener Property-Editor: als "Hidden" markierte Properties
  // (AttacherType, Proxy-Interna ...) nur auf Wunsch.
  const hiddenCount = data.properties.filter((entry) => entry.flags.includes("Hidden")).length
  const needle = filter.trim().toLowerCase()
  const visible = data.properties.filter(
    (entry) =>
      (showHidden || !entry.flags.includes("Hidden")) && (!needle || entry.name.toLowerCase().includes(needle)),
  )
  const groups = groupProperties(visible)

  return (
    <div className="flex h-full min-h-0 flex-col">
      <header className="space-y-2 border-b p-4">
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <h2 className="truncate text-lg font-semibold" title={data.label}>
              {data.label}
            </h2>
            <p className="truncate font-mono text-xs text-muted-foreground">
              {data.name} · {data.typeId}
            </p>
          </div>
          <div className="flex shrink-0 gap-1">
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  variant="outline"
                  size="icon-sm"
                  onClick={() =>
                    showInFreeCAD(doc, name).catch((error: unknown) => toast.error(describeError(error)))
                  }
                >
                  <Crosshair />
                </Button>
              </TooltipTrigger>
              <TooltipContent>In FreeCAD auswählen und anzeigen</TooltipContent>
            </Tooltip>
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  variant={showGeometry ? "secondary" : "outline"}
                  size="icon-sm"
                  onClick={() => setShowGeometry((value) => !value)}
                >
                  <Ruler />
                </Button>
              </TooltipTrigger>
              <TooltipContent>Geometrie (Volumen, Hüllquader) berechnen</TooltipContent>
            </Tooltip>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          <Badge variant="outline" className="font-mono text-[10px]" title="Revision: steigt bei jeder Änderung">
            rev {data.rev}
          </Badge>
          <StateBadges state={data.state} />
          {data.visible === false && <Badge variant="secondary">ausgeblendet</Badge>}
        </div>
        <div className="flex items-center gap-2">
          <div className="relative flex-1">
            <Search className="absolute top-2 left-2 size-3.5 text-muted-foreground" />
            <Input
              value={filter}
              onChange={(event) => setFilter(event.target.value)}
              placeholder="Property suchen"
              className="h-7 pl-7 text-xs"
            />
          </div>
          {hiddenCount > 0 && (
            <Button
              variant={showHidden ? "secondary" : "ghost"}
              size="sm"
              className="h-7 text-xs"
              onClick={() => setShowHidden((value) => !value)}
            >
              {showHidden ? "Versteckte ausblenden" : hiddenCount + " versteckte"}
            </Button>
          )}
        </div>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto">
        {showGeometry && <GeometrySection doc={doc} name={name} />}
        {groups.map(([group, entries]) => (
          <Collapsible key={group} defaultOpen className="border-b">
            <CollapsibleTrigger className="group flex w-full items-center gap-1 bg-muted/40 px-3 py-1.5 text-left text-xs font-medium">
              <ChevronDown className="size-3.5 transition-transform group-data-[state=closed]:-rotate-90" />
              {group}
              <span className="ml-auto text-muted-foreground">{entries.length}</span>
            </CollapsibleTrigger>
            <CollapsibleContent>
              {entries.map((entry) => (
                <PropertyRow key={entry.name} entry={entry} ctx={ctx} />
              ))}
            </CollapsibleContent>
          </Collapsible>
        ))}
        {groups.length === 0 && <p className="p-4 text-sm text-muted-foreground">Keine passende Property.</p>}
      </div>
      <ConflictDialog conflict={editor.conflict} />
    </div>
  )
}

function PropertyRow({ entry, ctx }: { entry: PropertyEntry; ctx: FieldContext }) {
  const kind = fieldKind(entry)
  const locked = kind === "readonly" && !entry.expression
  return (
    <div className="grid grid-cols-[minmax(7rem,36%)_1fr] items-start gap-2 px-3 py-1 hover:bg-muted/30">
      <Tooltip>
        <TooltipTrigger asChild>
          <span className="flex min-w-0 items-center gap-1 py-1 text-xs">
            <span className="truncate">{entry.name}</span>
            {entry.expression && <FunctionSquare className="size-3.5 shrink-0 text-primary" />}
            {locked && <Lock className="size-3 shrink-0 text-muted-foreground" />}
          </span>
        </TooltipTrigger>
        <TooltipContent side="left" className="max-w-sm">
          <p className="font-medium">{entry.name}</p>
          {entry.doc && <p className="mt-1">{entry.doc}</p>}
          <p className="mt-1 font-mono opacity-70">{entry.typeId}</p>
          {entry.expression && <p className="mt-1">Gebunden an: {entry.expression} – in FreeCAD bearbeiten</p>}
          {locked && entry.flags.length > 0 && <p className="mt-1 opacity-70">Flags: {entry.flags.join(", ")}</p>}
        </TooltipContent>
      </Tooltip>
      <div className={cn("min-w-0", entry.expression && "opacity-80")}>
        <PropertyField entry={entry} ctx={ctx} />
        {entry.expression && <p className="truncate font-mono text-[10px] text-primary">= {entry.expression}</p>}
      </div>
    </div>
  )
}

function groupProperties(entries: PropertyEntry[]): Array<[string, PropertyEntry[]]> {
  const groups = new Map<string, PropertyEntry[]>()
  for (const entry of entries) {
    const group = entry.group || "Base" // FreeCAD liefert fuer die Basis-Properties eine leere Gruppe
    if (!groups.has(group)) groups.set(group, [])
    groups.get(group)!.push(entry)
  }
  // "Base" zuletzt: die generischen Felder (Label, Placement ...) stehen in
  // FreeCAD auch unten; oben das, was den Objekttyp ausmacht.
  return [...groups.entries()].sort(([a], [b]) => (a === "Base") === (b === "Base") ? a.localeCompare(b) : a === "Base" ? 1 : -1)
}

function GeometrySection({ doc, name }: { doc: string; name: string }) {
  const query = useQuery(geometryQuery(doc, name))
  const rows: Array<[string, string]> = []
  const geometry = query.data
  if (geometry && !geometry.null) {
    if (geometry.shapeType) rows.push(["Form", geometry.shapeType])
    if (geometry.volume !== undefined) rows.push(["Volumen", formatNumber(geometry.volume, 3) + " mm³"])
    if (geometry.area !== undefined) rows.push(["Oberfläche", formatNumber(geometry.area, 3) + " mm²"])
    if (geometry.boundBox)
      rows.push(["Hüllquader", geometry.boundBox.lengths.map((n) => formatNumber(n, 3)).join(" × ") + " mm"])
    if (geometry.centerOfMass)
      rows.push(["Schwerpunkt", "(" + geometry.centerOfMass.map((n) => formatNumber(n, 3)).join(", ") + ")"])
    if (geometry.counts)
      rows.push([
        "Topologie",
        [
          geometry.counts.solids + " Körper",
          geometry.counts.faces + " Flächen",
          geometry.counts.edges + " Kanten",
        ].join(" · "),
      ])
    if (geometry.valid === false) rows.push(["Gültig", "nein"])
  }
  return (
    <section className="border-b p-3">
      <h3 className="mb-2 flex items-center gap-1 text-xs font-medium">
        <Box className="size-3.5" /> Geometrie
      </h3>
      {query.isPending && <Skeleton className="h-16" />}
      {query.isError && <p className="text-xs text-destructive">{describeError(query.error)}</p>}
      {query.isSuccess && !rows.length && <p className="text-xs text-muted-foreground">Keine Geometrie.</p>}
      <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs">
        {rows.map(([label, value]) => (
          <div key={label} className="contents">
            <dt className="text-muted-foreground">{label}</dt>
            <dd className="font-mono">{value}</dd>
          </div>
        ))}
      </dl>
    </section>
  )
}

function PanelSkeleton() {
  return (
    <div className="space-y-3 p-4">
      <Skeleton className="h-6 w-1/2" />
      <Skeleton className="h-4 w-1/3" />
      {Array.from({ length: 8 }, (_, index) => (
        <Skeleton key={index} className="h-7" />
      ))}
    </div>
  )
}
