import type { Tree, TreeNode } from "./types"

// The bridge delivers a FLAT node list plus edges (children from
// claimChildren). The structure is a DAG, not a tree: an object may appear
// under several parents. Therefore a row's key is its PATH, not obj.Name --
// and every descent carries a visited guard against cycles.

export type TreeRow = {
  /** path of object names, unique per row ("Body/Pad/Sketch") */
  key: string
  name: string
  depth: number
  node: TreeNode
  hasChildren: boolean
  expanded: boolean
  /** The object already appears further up in THIS path. */
  cycle: boolean
}

const SEPARATOR = "/"

export function pathKey(parts: string[]): string {
  return parts.map(encodeURIComponent).join(SEPARATOR)
}

export function flattenTree(tree: Tree, expanded: ReadonlySet<string>): TreeRow[] {
  const rows: TreeRow[] = []

  const visit = (name: string, depth: number, path: string[], ancestors: Set<string>) => {
    const node = tree.nodes[name]
    if (!node) return
    const parts = [...path, name]
    const key = pathKey(parts)
    const cycle = ancestors.has(name)
    const children = node.children.filter((child) => child in tree.nodes)
    const hasChildren = !cycle && children.length > 0
    const isExpanded = hasChildren && expanded.has(key)
    rows.push({ key, name, depth, node, hasChildren, expanded: isExpanded, cycle })
    if (!isExpanded) return
    const next = new Set(ancestors).add(name)
    for (const child of children) visit(child, depth + 1, parts, next)
  }

  for (const root of tree.roots) visit(root, 0, [], new Set())
  return rows
}

/** Search hits as a flat list -- label or name, case-insensitive. */
export function searchTree(tree: Tree, query: string): TreeRow[] {
  const needle = query.trim().toLowerCase()
  if (!needle) return []
  return Object.values(tree.nodes)
    .filter(
      (node) => node.label.toLowerCase().includes(needle) || node.name.toLowerCase().includes(needle),
    )
    .sort((a, b) => a.label.localeCompare(b.label))
    .map((node) => ({
      key: "search:" + node.name,
      name: node.name,
      depth: 0,
      node,
      hasChildren: false,
      expanded: false,
      cycle: false,
    }))
}

/**
 * A path from a root to ``name`` (breadth-first search, shortest first) --
 * so that "selection from FreeCAD" can expand and show the object in the tree.
 */
export function findPath(tree: Tree, name: string): string[] | null {
  if (!(name in tree.nodes)) return null
  const queue: string[][] = tree.roots.map((root) => [root])
  const seen = new Set<string>()
  while (queue.length) {
    const path = queue.shift()!
    const last = path[path.length - 1]
    if (last === name) return path
    if (seen.has(last)) continue
    seen.add(last)
    for (const child of tree.nodes[last]?.children ?? []) {
      if (child in tree.nodes) queue.push([...path, child])
    }
  }
  return null
}

/** Keys of all ancestors of a path -- these must be expanded. */
export function ancestorKeys(path: string[]): string[] {
  const keys: string[] = []
  for (let index = 1; index < path.length; index++) keys.push(pathKey(path.slice(0, index)))
  return keys
}

// -- Keyboard ---------------------------------------------------------------

export type TreeMove = { index: number; expand?: string; collapse?: string }

/**
 * Keyboard in the tree, as in file explorers (WAI-ARIA Tree View):
 * ↑/↓ adjacent row, Home/End, → expand or go to the first child,
 * ← collapse or go to the parent node. null = key does not belong to the tree.
 */
export function moveInTree(rows: TreeRow[], index: number, key: string): TreeMove | null {
  if (!rows.length) return null
  const current = Math.min(Math.max(index, 0), rows.length - 1)
  const row = rows[current]
  switch (key) {
    case "ArrowDown":
      return { index: Math.min(current + 1, rows.length - 1) }
    case "ArrowUp":
      return { index: Math.max(current - 1, 0) }
    case "Home":
      return { index: 0 }
    case "End":
      return { index: rows.length - 1 }
    case "ArrowRight":
      if (!row.hasChildren) return { index: current }
      if (!row.expanded) return { index: current, expand: row.key }
      return { index: Math.min(current + 1, rows.length - 1) }
    case "ArrowLeft": {
      if (row.expanded) return { index: current, collapse: row.key }
      for (let i = current - 1; i >= 0; i--) {
        if (rows[i].depth === row.depth - 1) return { index: i }
      }
      return { index: current }
    }
    default:
      return null
  }
}
