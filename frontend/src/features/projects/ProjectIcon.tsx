import { ArrowLeftRight, Boxes, Puzzle, type LucideIcon } from "lucide-react"

// Modules name their icon by its lucide name. Only the ones actually used are
// registered here -- importing all icons would bloat the bundle.
const ICONS: Record<string, LucideIcon> = {
  "arrow-left-right": ArrowLeftRight,
  puzzle: Puzzle,
  boxes: Boxes,
}

export function ProjectIcon({ name, className }: { name: string; className?: string }) {
  const Icon = ICONS[name] ?? Boxes
  return <Icon className={className} />
}
