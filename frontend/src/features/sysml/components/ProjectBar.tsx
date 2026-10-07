import { GitCommitHorizontal, RefreshCw } from "lucide-react"
import { useTranslation } from "react-i18next"

import { Button } from "@/components/ui/button"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { cn } from "@/lib/utils"

import type { SysmlProject } from "../queries"

type Props = {
  projects: SysmlProject[]
  project: string
  onProjectChange: (id: string) => void
  /** Commit id of the snapshot being shown (undefined while it loads). */
  version?: string
  reloading: boolean
  onReload: () => void
}

/** Project picker, the version being shown and the reload button. */
export function ProjectBar({ projects, project, onProjectChange, version, reloading, onReload }: Props) {
  const { t } = useTranslation()
  return (
    <div className="flex flex-wrap items-center gap-3">
      <span className="text-sm text-muted-foreground">{t("sysml.project")}</span>
      <Select value={project} onValueChange={onProjectChange}>
        <SelectTrigger className="w-72" aria-label={t("sysml.project")}>
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {projects.map((p) => (
            <SelectItem key={p.id} value={p.id}>
              {p.name}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      {version && (
        <span className="flex items-center gap-1 text-xs text-muted-foreground" title={version}>
          <GitCommitHorizontal className="size-3.5" />
          {t("sysml.version", { id: version.slice(0, 8) })}
        </span>
      )}
      <Button variant="ghost" size="sm" className="ml-auto" onClick={onReload} disabled={reloading}>
        <RefreshCw className={cn(reloading && "animate-spin")} />
        {t("sysml.reload")}
      </Button>
    </div>
  )
}
