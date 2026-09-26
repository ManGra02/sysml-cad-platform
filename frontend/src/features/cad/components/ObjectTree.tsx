import { useQueryClient } from "@tanstack/react-query"
import { useVirtualizer } from "@tanstack/react-virtual"
import {
  Box,
  ChevronRight,
  Cuboid,
  Eye,
  EyeOff,
  Folder,
  Link2,
  PenTool,
  Repeat,
  Shapes,
  Table2,
  type LucideIcon,
} from "lucide-react"
import { useEffect, useMemo, useRef, useState } from "react"

import { cn } from "@/lib/utils"
import { toggleVisibility } from "../editing"
import { ancestorKeys, findPath, flattenTree, pathKey, searchTree, type TreeRow } from "../tree"
import type { Tree } from "../types"
import { stateTone } from "./StateBadges"

const ROW_HEIGHT = 28

function iconFor(typeId: string): LucideIcon {
  if (typeId === "PartDesign::Body" || typeId === "App::Part") return Box
  if (typeId.startsWith("Sketcher::")) return PenTool
  if (typeId.startsWith("Spreadsheet::")) return Table2
  if (typeId === "App::DocumentObjectGroup") return Folder
  if (typeId.startsWith("App::Link")) return Link2
  if (typeId.startsWith("Part::") || typeId.startsWith("PartDesign::")) return Cuboid
  return Shapes
}

/**
 * Objektbaum wie in FreeCAD -- virtualisiert, damit auch Tausende Objekte
 * fluessig bleiben. Zeilen-Schluessel ist der Pfad, weil ein Objekt im DAG
 * unter mehreren Eltern stehen darf.
 */
export function ObjectTree({
  tree,
  selected,
  search,
  onSelect,
}: {
  tree: Tree
  selected: string | undefined
  search: string
  onSelect: (name: string) => void
}) {
  const queryClient = useQueryClient()
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set(tree.roots.map((root) => pathKey([root]))))
  const scrollRef = useRef<HTMLDivElement>(null)

  const rows = useMemo(
    () => (search.trim() ? searchTree(tree, search) : flattenTree(tree, expanded)),
    [tree, expanded, search],
  )

  const virtualizer = useVirtualizer({
    count: rows.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => ROW_HEIGHT,
    overscan: 12,
  })

  // Auswahl von aussen (URL, "Auswahl aus FreeCAD"): Pfad aufklappen und hinscrollen.
  const revealed = useRef<string | undefined>(undefined)
  useEffect(() => {
    if (!selected || revealed.current === selected || search.trim()) return
    const path = findPath(tree, selected)
    if (!path) return
    const missing = ancestorKeys(path).filter((key) => !expanded.has(key))
    if (missing.length) {
      setExpanded((old) => new Set([...old, ...missing]))
      return // nach dem Aufklappen erneut
    }
    revealed.current = selected
    const index = rows.findIndex((row) => row.key === pathKey(path))
    if (index >= 0) virtualizer.scrollToIndex(index, { align: "auto" })
  }, [selected, tree, rows, expanded, search, virtualizer])

  const toggle = (row: TreeRow) =>
    setExpanded((old) => {
      const next = new Set(old)
      if (next.has(row.key)) next.delete(row.key)
      else next.add(row.key)
      return next
    })

  if (!rows.length) {
    return (
      <p className="p-4 text-sm text-muted-foreground">
        {search.trim() ? "Kein Objekt passt zur Suche." : "Das Dokument enthält keine Objekte."}
      </p>
    )
  }

  return (
    <div ref={scrollRef} className="h-full overflow-y-auto" role="tree">
      <div className="relative" style={{ height: virtualizer.getTotalSize() }}>
        {virtualizer.getVirtualItems().map((item) => {
          const row = rows[item.index]
          const node = row.node
          const Icon = iconFor(node.typeId)
          const tone = stateTone(node.state)
          const isSelected = node.name === selected
          return (
            <div
              key={row.key}
              role="treeitem"
              aria-selected={isSelected}
              aria-expanded={row.hasChildren ? row.expanded : undefined}
              className={cn(
                "group absolute left-0 flex w-full cursor-default items-center gap-1 pr-2 text-sm select-none",
                isSelected ? "bg-accent text-accent-foreground" : "hover:bg-muted/60",
              )}
              style={{ top: item.start, height: ROW_HEIGHT, paddingLeft: 4 + row.depth * 16 }}
              onClick={() => onSelect(node.name)}
              onDoubleClick={() => row.hasChildren && toggle(row)}
            >
              <button
                type="button"
                tabIndex={-1}
                className={cn("grid size-5 shrink-0 place-items-center rounded", !row.hasChildren && "invisible")}
                onClick={(event) => {
                  event.stopPropagation()
                  toggle(row)
                }}
              >
                <ChevronRight className={cn("size-3.5 transition-transform", row.expanded && "rotate-90")} />
              </button>
              <Icon className={cn("size-4 shrink-0", node.internal ? "text-muted-foreground" : "text-primary/70")} />
              <span
                className={cn(
                  "min-w-0 flex-1 truncate",
                  node.visible === false && "text-muted-foreground",
                  tone === "error" && "text-destructive",
                )}
                title={node.name + " · " + node.typeId}
              >
                {node.label}
                {search.trim() && node.label !== node.name && (
                  <span className="ml-1 text-xs text-muted-foreground">{node.name}</span>
                )}
              </span>
              {row.cycle && <Repeat className="size-3.5 shrink-0 text-muted-foreground" aria-label="Zyklus" />}
              {tone === "touched" && (
                <span className="size-1.5 shrink-0 rounded-full bg-warning" title="Muss neu berechnet werden" />
              )}
              {node.visible !== null && (
                <button
                  type="button"
                  tabIndex={-1}
                  title={node.visible ? "Ausblenden" : "Einblenden"}
                  className={cn(
                    "grid size-5 shrink-0 place-items-center rounded text-muted-foreground hover:text-foreground",
                    node.visible && "opacity-0 group-hover:opacity-100",
                  )}
                  onClick={(event) => {
                    event.stopPropagation()
                    void toggleVisibility(queryClient, node.doc, node.name, !node.visible)
                  }}
                >
                  {node.visible ? <Eye className="size-3.5" /> : <EyeOff className="size-3.5" />}
                </button>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
