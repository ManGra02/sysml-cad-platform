import { useQuery } from "@tanstack/react-query"
import { Plug, Unplug } from "lucide-react"
import type { ReactNode } from "react"
import { useTranslation } from "react-i18next"

import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { AiDetails } from "@/features/ai/components/AiStatus"
import { aiState, aiStatusQuery } from "@/features/ai/queries"
import { CadDetails } from "@/features/cad/components/ConnectionStatus"
import { statusQuery } from "@/features/cad/queries"
import { sysmlStatusQuery } from "@/features/sysml/queries"
import { cn } from "@/lib/utils"
import { useSocketState } from "@/lib/ws"

type Health = "ok" | "problem" | "unknown"

const DOT: Record<Health, string> = { ok: "bg-success", problem: "bg-warning", unknown: "bg-muted-foreground/40" }

/**
 * ONE marker for every connection the platform depends on -- "all connected" or how many
 * are not; a click shows each one (FreeCAD, SysML/Flexo, AI) with its details.
 */
export function SystemStatus() {
  const { t } = useTranslation()
  const socket = useSocketState()
  const backend = useQuery(statusQuery)
  const sysml = useQuery(sysmlStatusQuery)
  const ai = useQuery(aiStatusQuery)
  const backendDown = backend.isError || socket === "closed"

  const bridgeState = backend.data?.bridge.state
  const cad: Health = backendDown ? "problem" : !bridgeState ? "unknown"
    : (bridgeState === "ok" || bridgeState === "busy") && backend.data!.bridge.contract.match ? "ok" : "problem"
  const flexo: Health = sysml.data ? (sysml.data.reachable ? "ok" : "problem") : sysml.isError ? "problem" : "unknown"
  const llm: Health = ai.data ? (aiState(ai.data) === "ok" ? "ok" : "problem") : ai.isError ? "problem" : "unknown"
  const problems = [cad, flexo, llm].filter((h) => h === "problem").length
  const known = [cad, flexo, llm].every((h) => h !== "unknown")

  const label = backendDown
    ? t("connection.backendDown")
    : problems
      ? t("systemStatus.problems", { count: problems })
      : known
        ? t("systemStatus.allOk")
        : t("systemStatus.checking")

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="sm" className="gap-2" aria-label={`${t("systemStatus.title")}: ${label}`}>
          {backendDown ? <Unplug className="text-destructive" /> : <Plug />}
          <span
            aria-hidden="true"
            className={cn("size-2 rounded-full", backendDown ? "bg-destructive" : problems ? "bg-warning" : known ? "bg-success" : DOT.unknown)}
          />
          <span className="hidden sm:inline">{label}</span>
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-96">
        <DropdownMenuLabel>{t("systemStatus.title")}</DropdownMenuLabel>
        <DropdownMenuSeparator />
        <Section health={cad} title={t("systemStatus.cad")} state={backendDown ? t("connection.backendDown") : bridgeState ? t(`connection.state.${bridgeState}`) : "…"}>
          <CadDetails />
        </Section>
        <DropdownMenuSeparator />
        <Section
          health={flexo}
          title={t("systemStatus.sysml")}
          state={sysml.data ? (sysml.data.reachable ? t("systemStatus.connected") : t("systemStatus.unreachable")) : "…"}
        >
          <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1.5 text-xs">
            <dt className="text-muted-foreground">{t("systemStatus.address")}</dt>
            <dd className="truncate">{sysml.data?.url ?? "–"}</dd>
            {sysml.data?.reachable ? (
              <>
                <dt className="text-muted-foreground">{t("systemStatus.projects")}</dt>
                <dd>{t("sysml.status.projects", { count: sysml.data.projects ?? 0 })}</dd>
              </>
            ) : (
              sysml.data && (
                <>
                  <dt className="text-muted-foreground">{t("systemStatus.hint")}</dt>
                  <dd>{t("sysml.status.downHint")} <code>docker compose -f flexo/docker-compose.yml up -d</code></dd>
                </>
              )
            )}
          </dl>
        </Section>
        <DropdownMenuSeparator />
        <Section health={llm} title={t("systemStatus.ai")} state={ai.data ? t(`ai.state.${aiState(ai.data)}`) : "…"}>
          <AiDetails />
        </Section>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

function Section({ health, title, state, children }: { health: Health; title: string; state: string; children: ReactNode }) {
  return (
    <section className="space-y-2 px-2 py-2">
      <h3 className="flex items-center gap-2 text-sm font-medium">
        <span aria-hidden="true" className={cn("size-2 rounded-full", DOT[health])} />
        {title}
        <span className="ml-auto text-xs font-normal text-muted-foreground">{state}</span>
      </h3>
      {children}
    </section>
  )
}
