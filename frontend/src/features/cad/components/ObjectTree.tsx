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
import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react"
import { useTranslation } from "react-i18next"

import { cn } from "@/lib/utils"
import { toggleVisibility } from "../editing"
import { ancestorKeys, findPath, flattenTree, moveInTree, pathKey, searchTree, type TreeRow } from "../tree"
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
 * Object tree as in FreeCAD -- virtualized so that even thousands of objects
 * stay smooth. The row key is the path, because an object in the DAG may
 * sit under several parents.
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
  /** replace: keyboard selection replaces the history entry instead of creating a new one per arrow key. */
  onSelect: (name: string, options?: { replace?: boolean }) => void
}) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const [focusIndex, setFocusIndex] = useState(0)
  const [hasFocus, setHasFocus] = useState(false)
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

  // Selection from outside (URL, "selection from FreeCAD"): expand the path and scroll to it.
  const revealed = useRef<string | undefined>(undefined)
  useEffect(() => {
    if (!selected || revealed.current === selected || search.trim()) return
    const path = findPath(tree, selected)
    if (!path) return
    const missing = ancestorKeys(path).filter((key) => !expanded.has(key))
    if (missing.length) {
      setExpanded((old) => new Set([...old, ...missing]))
      return // again after expanding
    }
    revealed.current = selected
    const index = rows.findIndex((row) => row.key === pathKey(path))
    if (index >= 0) virtualizer.scrollToIndex(index, { align: "auto" })
  }, [selected, tree, rows, expanded, search, virtualizer])

  // Keyboard focus follows a selection made by mouse or from outside.
  useEffect(() => {
    const index = rows.findIndex((row) => row.name === selected)
    if (index >= 0 && rows[focusIndex]?.name !== selected) setFocusIndex(index)
  }, [selected, rows])

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const row = rows[focusIndex]
    if ((event.key === "Enter" || event.key === " ") && row) {
      event.preventDefault()
      if (row.node.name !== selected) onSelect(row.node.name)
      else if (row.hasChildren) toggle(row)
      return
    }
    const move = moveInTree(rows, focusIndex, event.key)
    if (!move) return
    event.preventDefault()
    if (move.expand) setExpanded((old) => new Set(old).add(move.expand!))
    if (move.collapse)
      setExpanded((old) => {
        const next = new Set(old)
        next.delete(move.collapse!)
        return next
      })
    if (move.index !== focusIndex) {
      setFocusIndex(move.index)
      virtualizer.scrollToIndex(move.index, { align: "auto" })
      onSelect(rows[move.index].node.name, { replace: true })
    }
  }

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
        {search.trim() ? t("tree.noMatch") : t("tree.empty")}
      </p>
    )
  }

  return (
    <div
      ref={scrollRef}
      className="h-full overflow-y-auto outline-none"
      role="tree"
      aria-label={t("tree.label")}
      tabIndex={0}
      aria-activedescendant={rows[focusIndex] ? "tree-row-" + focusIndex : undefined}
      onKeyDown={onKeyDown}
      onFocus={() => setHasFocus(true)}
      onBlur={() => setHasFocus(false)}
    >
      <div className="relative" style={{ height: virtualizer.getTotalSize() }}>
        {virtualizer.getVirtualItems().map((item) => {
          const row = rows[item.index]
          const node = row.node
          const Icon = iconFor(node.typeId)
          const tone = stateTone(node.state)
          const isSelected = node.name === selected
          const isFocused = hasFocus && item.index === focusIndex
          return (
            <div
              key={row.key}
              id={"tree-row-" + item.index}
              role="treeitem"
              aria-level={row.depth + 1}
              aria-selected={isSelected}
              aria-expanded={row.hasChildren ? row.expanded : undefined}
              className={cn(
                "group absolute left-0 flex w-full cursor-default items-center gap-1 pr-2 text-sm select-none",
                isSelected ? "bg-accent text-accent-foreground" : "hover:bg-muted/60",
                isFocused && "ring-2 ring-ring/60 ring-inset",
              )}
              style={{ top: item.start, height: ROW_HEIGHT, paddingLeft: 4 + row.depth * 16 }}
              onClick={() => {
                setFocusIndex(item.index)
                onSelect(node.name)
              }}
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
              {row.cycle && <Repeat className="size-3.5 shrink-0 text-muted-foreground" aria-label={t("tree.cycle")} />}
              {tone === "touched" && (
                <span className="size-1.5 shrink-0 rounded-full bg-warning" title={t("tree.touched")} />
              )}
              {node.visible !== null && (
                <button
                  type="button"
                  tabIndex={-1}
                  title={node.visible ? t("tree.hide") : t("tree.show")}
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
