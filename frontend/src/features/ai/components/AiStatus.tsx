import { useQuery, useQueryClient } from "@tanstack/react-query"
import { RefreshCw, Sparkles } from "lucide-react"
import { useState } from "react"
import { useTranslation } from "react-i18next"

import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { cn } from "@/lib/utils"
import { aiKeys, aiState, aiStatusQuery, refreshAiStatus, type AiState } from "../queries"

const TONE: Record<AiState, string> = {
  ok: "bg-success",
  model_missing: "bg-warning",
  unreachable: "bg-destructive",
  unconfigured: "bg-muted-foreground",
}

/** Header marker: is the LLM (Ollama Cloud) usable, and which model does each project get? */
export function AiStatus() {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const { data, isError } = useQuery(aiStatusQuery)
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
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="sm" className="gap-2" title={t("ai.title")}>
          <Sparkles />
          <span className={cn("size-2 rounded-full", state ? TONE[state] : isError ? "bg-destructive" : "bg-muted")} />
          <span className="hidden sm:inline">{t("ai.short")}</span>
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-80">
        <DropdownMenuLabel className="flex items-center justify-between">
          {t("ai.title")}
          <Button variant="ghost" size="icon-sm" onClick={check} disabled={checking} title={t("ai.check")}>
            <RefreshCw className={cn(checking && "animate-spin")} />
          </Button>
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1.5 p-2 text-xs">
          <dt className="text-muted-foreground">{t("ai.status")}</dt>
          <dd>
            {state ? t(`ai.state.${state}`) : t("common.unknown")}
            {state && state !== "ok" && <p className="text-muted-foreground">{t(`ai.help.${state}`)}</p>}
            {data?.message && state === "unreachable" && <p className="text-muted-foreground">{data.message}</p>}
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
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

function ProjectModel({ id, model, available }: { id: string; model: string | null; available?: boolean }) {
  const { t } = useTranslation()
  return (
    <>
      <dt className="text-muted-foreground">{t("ai.model", { project: id.toUpperCase() })}</dt>
      <dd className={cn("font-mono", available === false && "text-warning")}>
        {model ?? t("ai.noModel")}
        {available === false && model && <p className="font-sans">{t("ai.modelMissing")}</p>}
      </dd>
    </>
  )
}
