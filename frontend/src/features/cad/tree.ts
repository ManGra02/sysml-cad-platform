import type { Tree, TreeNode } from "./types"

// Die Bruecke liefert eine FLACHE Knotenliste plus Kanten (children aus
// claimChildren). Die Struktur ist ein DAG, kein Baum: ein Objekt darf unter
// mehreren Eltern auftauchen. Deshalb ist der Schluessel einer Zeile ihr PFAD,
// nicht obj.Name -- und jeder Abstieg traegt einen Besuchsschutz gegen Zyklen.

export type TreeRow = {
  /** Pfad aus Objektnamen, eindeutig pro Zeile ("Body/Pad/Sketch") */
  key: string
  name: string
  depth: number
  node: TreeNode
  hasChildren: boolean
  expanded: boolean
  /** Das Objekt taucht bereits weiter oben in DIESEM Pfad auf. */
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

/** Treffer der Suche als flache Liste -- Label oder Name, ohne Gross/Klein. */
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
 * Ein Pfad von einer Wurzel zu ``name`` (Breitensuche, kuerzester zuerst) --
 * damit "Auswahl aus FreeCAD" das Objekt im Baum aufklappen und anzeigen kann.
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

/** Schluessel aller Vorfahren eines Pfads -- die muessen aufgeklappt sein. */
export function ancestorKeys(path: string[]): string[] {
  const keys: string[] = []
  for (let index = 1; index < path.length; index++) keys.push(pathKey(path.slice(0, index)))
  return keys
}
