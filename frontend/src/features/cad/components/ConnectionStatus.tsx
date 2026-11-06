import { useQuery } from "@tanstack/react-query"
import { Unplug } from "lucide-react"
import { useTranslation } from "react-i18next"

import { cn } from "@/lib/utils"
import { useSocketState } from "@/lib/ws"
import { statusQuery } from "../queries"
import type { BridgeState, BridgeStatus } from "../types"

// Four bridge states, not two -- "busy" means: FreeCAD is computing,
// not: broken. Plus our own wire to the backend.

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

/** Our wire to the backend and the FreeCAD bridge behind it. A section of the status menu. */
export function CadDetails() {
  const { t } = useTranslation()
  const socket = useSocketState()
  const { data } = useQuery(statusQuery)
  const bridge = data?.bridge
  const reason = useReasonText(bridge)
  return (
    <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1.5 text-xs">
      <dt className="text-muted-foreground">{t("connection.backend")}</dt>
      <dd>{t(`connection.socket.${socket}`)}</dd>
      <dt className="text-muted-foreground">{t("connection.bridge")}</dt>
      <dd className="text-muted-foreground">
        {bridge ? t(`connection.help.${bridge.state}`) : t("common.unknown")}
        {reason && bridge?.state !== "ok" && <p>{reason}</p>}
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
