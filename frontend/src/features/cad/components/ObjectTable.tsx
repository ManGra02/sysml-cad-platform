import { useQuery } from "@tanstack/react-query"
import { useVirtualizer } from "@tanstack/react-virtual"
import { useMemo, useRef, useState } from "react"

import { Input } from "@/components/ui/input"
import { cn } from "@/lib/utils"
import { describeError, formatValue } from "../format"
import { batchQuery } from "../queries"
import type { PropertyEntry, Tree } from "../types"
import { stateTone } from "./StateBadges"

const ROW_HEIGHT = 30
const DEFAULT_COLUMNS = "Placement"

/**
 * Alle Objekte als Tabelle, frei waehlbare Property-Spalten.
 *
 * Die Spalten kommen ueber die Batch-Route: EINE Anfrage fuer alle Objekte
 * statt einer pro Zeile (ohne sie waeren das N+1 Spruenge auf FreeCADs
 * Hauptthread).
 */
export function ObjectTable({
  doc,
  tree,
  selected,
  search,
  onSelect,
}: {
  doc: string
  tree: Tree
  selected: string | undefined
  search: string
  onSelect: (name: string) => void
}) {
  const [columnText, setColumnText] = useState(DEFAULT_COLUMNS)
  const [committed, setCommitted] = useState(DEFAULT_COLUMNS)
  const fields = useMemo(
    () => [...new Set(committed.split(",").map((part) => part.trim()).filter(Boolean))],
    [committed],
  )
  const batch = useQuery(batchQuery(doc, fields))

  const values = useMemo(() => {
    const map = new Map<string, Map<string, PropertyEntry>>()
    for (const object of batch.data?.objects ?? []) {
      map.set(object.name, new Map(object.properties.map((entry) => [entry.name, entry])))
    }
    return map
  }, [batch.data])

  const labels = useMemo(() => {
    const map: Record<string, string> = {}
    for (const node of Object.values(tree.nodes)) map[node.name] = node.label
    return map
  }, [tree])

  const rows = useMemo(() => {
    const needle = search.trim().toLowerCase()
    return Object.values(tree.nodes)
      .filter((node) => !needle || node.label.toLowerCase().includes(needle) || node.name.toLowerCase().includes(needle))
      .sort((a, b) => a.label.localeCompare(b.label))
  }, [tree, search])

  const scrollRef = useRef<HTMLDivElement>(null)
  const virtualizer = useVirtualizer({
    count: rows.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => ROW_HEIGHT,
    overscan: 12,
  })

  const template = "minmax(10rem,1.2fr) minmax(8rem,1fr) " + fields.map(() => "minmax(8rem,1fr)").join(" ")

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex items-center gap-2 border-b p-2">
        <span className="shrink-0 text-xs text-muted-foreground">Spalten</span>
        <Input
          value={columnText}
          onChange={(event) => setColumnText(event.target.value)}
          onBlur={() => setCommitted(columnText)}
          onKeyDown={(event) => event.key === "Enter" && setCommitted(columnText)}
          placeholder="z. B. Length, Width, Placement"
          className="h-7 text-xs"
        />
      </div>
      {batch.isError && <p className="p-2 text-xs text-destructive">{describeError(batch.error)}</p>}
      <div ref={scrollRef} className="min-h-0 flex-1 overflow-auto">
        <div className="min-w-max">
          <div
            className="sticky top-0 z-10 grid border-b bg-background text-xs font-medium text-muted-foreground"
            style={{ gridTemplateColumns: template }}
          >
            <div className="px-2 py-1.5">Objekt</div>
            <div className="px-2 py-1.5">Typ</div>
            {fields.map((field) => (
              <div key={field} className="px-2 py-1.5">
                {field}
              </div>
            ))}
          </div>
          <div className="relative" style={{ height: virtualizer.getTotalSize() }}>
            {virtualizer.getVirtualItems().map((item) => {
              const node = rows[item.index]
              const props = values.get(node.name)
              const tone = stateTone(node.state)
              return (
                <div
                  key={node.name}
                  className={cn(
                    "absolute left-0 grid w-full cursor-default items-center border-b text-xs",
                    node.name === selected ? "bg-accent" : "hover:bg-muted/60",
                  )}
                  style={{ top: item.start, height: ROW_HEIGHT, gridTemplateColumns: template }}
                  onClick={() => onSelect(node.name)}
                >
                  <div className={cn("truncate px-2", tone === "error" && "text-destructive")} title={node.name}>
                    {node.label}
                  </div>
                  <div className="truncate px-2 font-mono text-muted-foreground">{node.typeId}</div>
                  {fields.map((field) => {
                    const entry = props?.get(field)
                    return (
                      <div key={field} className="truncate px-2 font-mono" title={entry ? formatValue(entry.value, labels) : ""}>
                        {batch.isLoading ? "…" : entry ? formatValue(entry.value, labels) : <span className="text-muted-foreground">–</span>}
                      </div>
                    )
                  })}
                </div>
              )
            })}
          </div>
        </div>
      </div>
    </div>
  )
}
