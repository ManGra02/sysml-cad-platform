import { useQuery } from "@tanstack/react-query"
import { Plug, Unplug } from "lucide-react"

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"
import { useSocketState, type SocketState } from "@/lib/ws"
import { statusQuery } from "../queries"
import type { BridgeState } from "../types"

// Vier Zustaende der Bruecke, nicht zwei -- "busy" heisst: FreeCAD rechnet,
// nicht: kaputt. Dazu der eigene Draht zum Backend.

const BRIDGE_TEXT: Record<BridgeState, { label: string; tone: string; help: string }> = {
  ok: { label: "Verbunden", tone: "bg-success", help: "FreeCAD-Brücke antwortet." },
  busy: {
    label: "FreeCAD rechnet",
    tone: "bg-warning",
    help: "Die Brücke lebt, FreeCAD ist aber gerade beschäftigt (z. B. Neuberechnung).",
  },
  unreachable: {
    label: "Brücke nicht erreichbar",
    tone: "bg-destructive",
    help: "FreeCAD läuft nicht mehr oder die Brücke wurde gestoppt.",
  },
  unconfigured: {
    label: "Brücke nicht gestartet",
    tone: "bg-muted-foreground",
    help: "In FreeCAD die Workbench „SysML-CAD Brücke“ wählen und die Brücke starten.",
  },
}

const SOCKET_TEXT: Record<SocketState, string> = {
  open: "verbunden",
  connecting: "verbindet …",
  closed: "getrennt – neuer Versuch läuft",
}

export function useBridgeState(): BridgeState | undefined {
  return useQuery(statusQuery).data?.bridge.state
}

export function ConnectionStatus() {
  const socket = useSocketState()
  const { data, isError } = useQuery(statusQuery)
  const bridge = data?.bridge
  const backendDown = isError || socket === "closed"
  const info = bridge ? BRIDGE_TEXT[bridge.state] : undefined

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="sm" className="gap-2">
          {backendDown ? <Unplug className="text-destructive" /> : <Plug />}
          <span className={cn("size-2 rounded-full", backendDown ? "bg-destructive" : (info?.tone ?? "bg-muted"))} />
          <span className="hidden sm:inline">{backendDown ? "Backend getrennt" : (info?.label ?? "…")}</span>
          {bridge && !bridge.contract.match && <span className="text-warning">⚠</span>}
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-80">
        <DropdownMenuLabel>Verbindung</DropdownMenuLabel>
        <DropdownMenuSeparator />
        <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1.5 p-2 text-xs">
          <dt className="text-muted-foreground">Backend</dt>
          <dd>{SOCKET_TEXT[socket]}</dd>
          <dt className="text-muted-foreground">Brücke</dt>
          <dd>
            {info?.label ?? "unbekannt"}
            {info && <p className="text-muted-foreground">{info.help}</p>}
            {bridge?.detail && <p className="text-muted-foreground">{bridge.detail}</p>}
          </dd>
          <dt className="text-muted-foreground">Vertrag</dt>
          <dd className={cn(bridge && !bridge.contract.match && "text-warning")}>
            Brücke {bridge?.contract.bridge ?? "–"} · Backend {bridge?.contract.backend ?? "–"}
            {bridge && !bridge.contract.match && (
              <p>Versionen weichen ab – siehe CHANGELOG.md; Brücke oder Backend aktualisieren.</p>
            )}
          </dd>
          <dt className="text-muted-foreground">Sitzung</dt>
          <dd className="truncate font-mono">{bridge?.session_id ?? "–"}</dd>
        </dl>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

/** Platzhalter fuer CAD-Seiten, solange die Bruecke nicht bereit ist. */
export function BridgeNotReady({ state }: { state: BridgeState | undefined }) {
  const info = state ? BRIDGE_TEXT[state] : undefined
  return (
    <div className="mx-auto max-w-md p-10 text-center">
      <Unplug className="mx-auto mb-4 size-10 text-muted-foreground" />
      <h2 className="mb-2 text-lg font-semibold">{info?.label ?? "Verbindung wird aufgebaut …"}</h2>
      <p className="text-sm text-muted-foreground">
        {info?.help ?? "Warte auf das Backend."} Die Seite aktualisiert sich von selbst, sobald FreeCAD bereit ist.
      </p>
    </div>
  )
}
