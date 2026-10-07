import { Box, ChevronRight, Package } from "lucide-react"
import { useState } from "react"
import { useTranslation } from "react-i18next"

import { Badge } from "@/components/ui/badge"
import { cn } from "@/lib/utils"

import type { SysmlTreeNode } from "../queries"

type TreeProps = {
  nodes: SysmlTreeNode[]
  selected: string | null
  onSelect: (id: string) => void
  /** Parts without sub-parts get a "leaf" badge. */
  leafIds: Set<string>
}

/** Collapsible part tree; packages are shown but cannot be selected. */
export function PartTree({ nodes, selected, onSelect, leafIds }: TreeProps) {
  return (
    <ul role="tree" className="text-sm">
      {nodes.map((node) => (
        <TreeRow key={node.element.id} node={node} depth={0} selected={selected} onSelect={onSelect} leafIds={leafIds} />
      ))}
    </ul>
  )
}

function TreeRow({ node, depth, selected, onSelect, leafIds }: Omit<TreeProps, "nodes"> & { node: SysmlTreeNode; depth: number }) {
  const { t } = useTranslation()
  const [open, setOpen] = useState(true)
  const e = node.element
  const isPackage = e.kind === "package"
  const hasChildren = node.children.length > 0

  return (
    <li role="treeitem" aria-expanded={hasChildren ? open : undefined} aria-selected={selected === e.id}>
      <div
        className={cn(
          "flex items-center gap-1 rounded-md py-1 pr-2 hover:bg-muted/60",
          selected === e.id && "bg-accent text-accent-foreground",
        )}
        style={{ paddingLeft: depth * 16 + 4 }}
      >
        <button
          type="button"
          className={cn("grid size-5 place-items-center text-muted-foreground", !hasChildren && "invisible")}
          onClick={() => setOpen(!open)}
          aria-label={open ? t("sysml.tree.collapse") : t("sysml.tree.expand")}
        >
          <ChevronRight className={cn("size-3.5 transition-transform", open && "rotate-90")} />
        </button>
        <button
          type="button"
          className="flex min-w-0 flex-1 items-center gap-1.5 text-left"
          onClick={() => !isPackage && onSelect(e.id)}
        >
          {isPackage ? (
            <Package className="size-3.5 shrink-0 text-muted-foreground" />
          ) : (
            <Box className="size-3.5 shrink-0 text-primary" />
          )}
          <span className={cn("truncate", isPackage && "text-muted-foreground")}>{e.name}</span>
          {leafIds.has(e.id) && (
            <Badge variant="outline" className="ml-auto h-4 px-1 text-[10px]">
              {t("sysml.tree.leaf")}
            </Badge>
          )}
        </button>
      </div>
      {open && hasChildren && (
        <ul role="group">
          {node.children.map((child) => (
            <TreeRow
              key={child.element.id}
              node={child}
              depth={depth + 1}
              selected={selected}
              onSelect={onSelect}
              leafIds={leafIds}
            />
          ))}
        </ul>
      )}
    </li>
  )
}
