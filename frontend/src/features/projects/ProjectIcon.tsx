import { ArrowLeftRight, Boxes, Puzzle, type LucideIcon } from "lucide-react"

// Module nennen ihr Icon per lucide-Name. Nur die tatsaechlich benutzten sind
// hier eingetragen -- ein Import aller Icons wuerde das Bundle aufblaehen.
const ICONS: Record<string, LucideIcon> = {
  "arrow-left-right": ArrowLeftRight,
  puzzle: Puzzle,
  boxes: Boxes,
}

export function ProjectIcon({ name, className }: { name: string; className?: string }) {
  const Icon = ICONS[name] ?? Boxes
  return <Icon className={className} />
}
