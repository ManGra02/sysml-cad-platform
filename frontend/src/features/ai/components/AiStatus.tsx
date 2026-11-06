import { useQuery, useQueryClient } from "@tanstack/react-query"
import { RefreshCw } from "lucide-react"
import { useState } from "react"
import { useTranslation } from "react-i18next"

import { Button } from "@/components/ui/button"
import { projectsQuery } from "@/features/projects/queries"
import { cn } from "@/lib/utils"
import { aiKeys, aiState, aiStatusQuery, refreshAiStatus } from "../queries"

/** Is the LLM (Ollama Cloud) usable, and which model does each project get? A section of the status menu. */
export function AiDetails() {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const { data } = useQuery(aiStatusQuery)
  const [checking, setChecking] = useState(false)
  const state = data ? aiState(data) : undefined

  async function check() {
    setChecking(true)
    try {
      queryClient.setQueryData(aiKeys.status(), await refreshAiStatus())
    } finally {
      setChecking(false)
    }
  }

  return (
    <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1.5 text-xs">
      <dd className="col-span-2 flex items-start justify-between gap-2">
        <span className="text-muted-foreground">
          {state && state !== "ok" && <span className="block">{t(`ai.help.${state}`)}</span>}
          {data?.message && state === "unreachable" && <span className="block">{data.message}</span>}
        </span>
        <Button variant="ghost" size="sm" className="h-7 shrink-0 gap-1 px-2 text-xs" onClick={check} disabled={checking}>
          <RefreshCw className={cn(checking && "animate-spin")} /> {t("ai.check")}
        </Button>
      </dd>
      <dt className="text-muted-foreground">{t("ai.provider")}</dt>
      <dd className="truncate">{data?.url ?? "–"}</dd>
      {data?.models && (
        <>
          <dt className="text-muted-foreground">{t("ai.offered")}</dt>
          <dd title={data.models.join("\n")}>{t("ai.modelCount", { count: data.models.length })}</dd>
        </>
      )}
      {data &&
        Object.entries(data.projects).map(([id, project]) => (
          <ProjectModel key={id} id={id} model={project.model} available={project.available} />
        ))}
    </dl>
  )
}

function ProjectModel({ id, model, available }: { id: string; model: string | null; available?: boolean }) {
  const { t } = useTranslation()
  const { data } = useQuery(projectsQuery)
  const title = data?.projects.find((p) => p.id === id)?.title ?? id
  return (
    <>
      <dt className="text-muted-foreground">{t("ai.model", { project: title })}</dt>
      <dd className={cn("font-mono", available === false && "text-warning")}>
        {model ?? t("ai.noModel")}
        {available === false && model && <p className="font-sans">{t("ai.modelMissing")}</p>}
      </dd>
    </>
  )
}
