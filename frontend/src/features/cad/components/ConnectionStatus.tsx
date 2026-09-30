import { useQuery } from "@tanstack/react-query"
import { Plug, Unplug } from "lucide-react"
import { useTranslation } from "react-i18next"

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"
import { useSocketState } from "@/lib/ws"
import { statusQuery } from "../queries"
import type { BridgeState, BridgeStatus } from "../types"

// Four bridge states, not two -- "busy" means: FreeCAD is computing,
// not: broken. Plus our own wire to the backend.

const TONE: Record<BridgeState, string> = {
  ok: "bg-success",
  busy: "bg-warning",
  unreachable: "bg-destructive",
  unconfigured: "bg-muted-foreground",
}

export function useBridgeState(): BridgeState | undefined {
  return useQuery(statusQuery).data?.bridge.state
}

/** More precise reason from the backend (reason) -- translated, otherwise its plain English text. */
function useReasonText(bridge: BridgeStatus | undefined): string | null {
  const { t, i18n } = useTranslation()
  if (!bridge) return null
  const key = "connection.reason." + bridge.reason
  if (bridge.reason && i18n.exists(key)) return t(key as never)
  return bridge.detail
}

export function ConnectionStatus() {
  const { t } = useTranslation()
  const socket = useSocketState()
  const { data, isError } = useQuery(statusQuery)
  const bridge = data?.bridge
  const reason = useReasonText(bridge)
  const backendDown = isError || socket === "closed"

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="sm" className="gap-2">
          {backendDown ? <Unplug className="text-destructive" /> : <Plug />}
          <span
            className={cn("size-2 rounded-full", backendDown ? "bg-destructive" : bridge ? TONE[bridge.state] : "bg-muted")}
          />
          <span className="hidden sm:inline">
            {backendDown ? t("connection.backendDown") : bridge ? t(`connection.state.${bridge.state}`) : "…"}
          </span>
          {bridge && !bridge.contract.match && <span className="text-warning">⚠</span>}
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-80">
        <DropdownMenuLabel>{t("connection.title")}</DropdownMenuLabel>
        <DropdownMenuSeparator />
        <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1.5 p-2 text-xs">
          <dt className="text-muted-foreground">{t("connection.backend")}</dt>
          <dd>{t(`connection.socket.${socket}`)}</dd>
          <dt className="text-muted-foreground">{t("connection.bridge")}</dt>
          <dd>
            {bridge ? t(`connection.state.${bridge.state}`) : t("common.unknown")}
            {bridge && <p className="text-muted-foreground">{t(`connection.help.${bridge.state}`)}</p>}
            {reason && <p className="text-muted-foreground">{reason}</p>}
          </dd>
          <dt className="text-muted-foreground">{t("connection.contract")}</dt>
          <dd className={cn(bridge && !bridge.contract.match && "text-warning")}>
            {t("connection.contractValues", {
              bridge: bridge?.contract.bridge ?? "–",
              backend: bridge?.contract.backend ?? "–",
            })}
            {bridge && !bridge.contract.match && <p>{t("connection.contractMismatch")}</p>}
          </dd>
          <dt className="text-muted-foreground">{t("connection.session")}</dt>
          <dd className="truncate font-mono">{bridge?.session_id ?? "–"}</dd>
        </dl>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

/** Placeholder for CAD pages while the bridge is not ready. */
export function BridgeNotReady({ state }: { state: BridgeState | undefined }) {
  const { t } = useTranslation()
  return (
    <div className="mx-auto max-w-md p-10 text-center">
      <Unplug className="mx-auto mb-4 size-10 text-muted-foreground" />
      <h2 className="mb-2 text-lg font-semibold">
        {state ? t(`connection.state.${state}`) : t("connection.connecting")}
      </h2>
      <p className="text-sm text-muted-foreground">
        {state ? t(`connection.help.${state}`) : t("connection.waitBackend")} {t("connection.autoRefresh")}
      </p>
    </div>
  )
}
