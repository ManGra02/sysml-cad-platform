import { useQuery, useQueryClient } from "@tanstack/react-query"
import { Link, createFileRoute } from "@tanstack/react-router"
import { ListTree, MousePointerClick, RefreshCw, Search, Table2 } from "lucide-react"
import { useState, type ReactNode } from "react"
import { toast } from "sonner"
import { z } from "zod"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Skeleton } from "@/components/ui/skeleton"
import { Switch } from "@/components/ui/switch"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { BridgeNotReady, useBridgeState } from "@/features/cad/components/ConnectionStatus"
import { ObjectTable } from "@/features/cad/components/ObjectTable"
import { ObjectTree } from "@/features/cad/components/ObjectTree"
import { PropertyPanel } from "@/features/cad/components/PropertyPanel"
import { describeError } from "@/features/cad/format"
import { cadKeys, documentsQuery, getSelection, recomputeDocument, treeQuery } from "@/features/cad/queries"
import { ApiError } from "@/lib/api"
import { cn } from "@/lib/utils"

// Adressiert wird immer ueber doc.Name (Pfad) und obj.Name (?obj=) -- nie
// ueber Labels. Der Browser folgt bewusst NICHT automatisch dem aktiven
// FreeCAD-Dokument: jede Schreibanfrage traegt ihr Zieldokument explizit.
const searchSchema = z.object({
  obj: z.string().optional().catch(undefined),
  internal: z.boolean().optional().catch(undefined),
  view: z.enum(["tree", "table"]).optional().catch(undefined),
})

export const Route = createFileRoute("/cad/$doc")({
  validateSearch: searchSchema,
  component: Explorer,
})

function Explorer() {
  const { doc } = Route.useParams()
  const { obj, internal = false, view = "tree" } = Route.useSearch()
  const navigate = Route.useNavigate()
  const queryClient = useQueryClient()
  const bridge = useBridgeState()
  const ready = bridge === "ok" || bridge === "busy"
  const [search, setSearch] = useState("")

  const tree = useQuery({ ...treeQuery(doc, internal), enabled: ready })
  const documents = useQuery({ ...documentsQuery, enabled: ready })
  const info = documents.data?.documents.find((entry) => entry.name === doc)

  if (!ready) return <BridgeNotReady state={bridge} />

  const select = (name: string) => navigate({ search: (old) => ({ ...old, obj: name }) })

  const fromFreeCAD = async () => {
    try {
      const { available, selection } = await getSelection()
      if (!available) return toast.info("FreeCAD läuft ohne Oberfläche – keine Auswahl verfügbar.")
      const first = selection[0]
      if (!first) return toast.info("In FreeCAD ist nichts ausgewählt.")
      if (first.doc !== doc) {
        return navigate({ to: "/cad/$doc", params: { doc: first.doc }, search: { obj: first.name } })
      }
      select(first.name)
    } catch (error) {
      toast.error(describeError(error))
    }
  }

  const recompute = async () => {
    try {
      const result = await recomputeDocument(doc)
      toast.success(result.recomputed + " Objekte neu berechnet")
    } catch (error) {
      toast.error(describeError(error))
    } finally {
      void queryClient.invalidateQueries({ queryKey: cadKeys.doc(doc) })
    }
  }

  const docClosed = tree.error instanceof ApiError && tree.error.code === "doc_not_open"

  return (
    <div
      className={cn(
        "grid h-full min-h-0",
        view === "table" ? "grid-cols-[minmax(0,1fr)_minmax(22rem,30rem)]" : "grid-cols-[minmax(18rem,26rem)_minmax(0,1fr)]",
      )}
    >
      <aside className="flex min-h-0 flex-col border-r">
        <div className="space-y-2 border-b p-3">
          <div className="flex items-center gap-2">
            <Select value={doc} onValueChange={(name) => navigate({ to: "/cad/$doc", params: { doc: name }, search: {} })}>
              <SelectTrigger size="sm" className="min-w-0 flex-1">
                <SelectValue placeholder={doc} />
              </SelectTrigger>
              <SelectContent>
                {(documents.data?.documents ?? []).map((entry) => (
                  <SelectItem key={entry.name} value={entry.name}>
                    {entry.label}
                  </SelectItem>
                ))}
                {!info && <SelectItem value={doc}>{doc}</SelectItem>}
              </SelectContent>
            </Select>
            <Tooltip>
              <TooltipTrigger asChild>
                <Button variant="outline" size="icon-sm" onClick={() => void recompute()}>
                  <RefreshCw />
                </Button>
              </TooltipTrigger>
              <TooltipContent>Dokument neu berechnen</TooltipContent>
            </Tooltip>
          </div>
          {info?.modified && (
            <Badge variant="outline" className="border-warning text-warning" title="Gespeichert wird in FreeCAD (Strg+S)">
              Ungespeicherte Änderungen in FreeCAD
            </Badge>
          )}
          <div className="flex items-center gap-2">
            <div className="flex rounded-md border p-0.5">
              <ViewButton active={view === "tree"} onClick={() => navigate({ search: (old) => ({ ...old, view: undefined }) })}>
                <ListTree className="size-3.5" /> Baum
              </ViewButton>
              <ViewButton active={view === "table"} onClick={() => navigate({ search: (old) => ({ ...old, view: "table" }) })}>
                <Table2 className="size-3.5" /> Tabelle
              </ViewButton>
            </div>
            <Tooltip>
              <TooltipTrigger asChild>
                <Button variant="outline" size="sm" className="ml-auto h-7 text-xs" onClick={() => void fromFreeCAD()}>
                  <MousePointerClick /> Aus FreeCAD
                </Button>
              </TooltipTrigger>
              <TooltipContent>Das in FreeCAD ausgewählte Objekt hier öffnen</TooltipContent>
            </Tooltip>
          </div>
          <div className="relative">
            <Search className="absolute top-2 left-2 size-3.5 text-muted-foreground" />
            <Input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Objekt suchen (Label oder Name)"
              className="h-7 pl-7 text-xs"
            />
          </div>
          <div className="flex items-center gap-2">
            <Switch
              id="internal"
              checked={internal}
              onCheckedChange={(checked) => navigate({ search: (old) => ({ ...old, internal: checked || undefined }) })}
            />
            <Label htmlFor="internal" className="text-xs font-normal text-muted-foreground">
              Hilfsgeometrie anzeigen (Ursprung, Achsen, Ebenen)
            </Label>
          </div>
        </div>

        <div className="min-h-0 flex-1">
          {tree.isPending && (
            <div className="space-y-1 p-3">
              {Array.from({ length: 10 }, (_, index) => (
                <Skeleton key={index} className="h-6" />
              ))}
            </div>
          )}
          {tree.isError && (
            <div className="p-4 text-sm text-muted-foreground">
              {describeError(tree.error)}{" "}
              {docClosed && (
                <Link to="/cad" className="underline">
                  Zur Dokumentliste
                </Link>
              )}
            </div>
          )}
          {tree.data &&
            (view === "table" ? (
              <ObjectTable doc={doc} tree={tree.data} selected={obj} search={search} onSelect={select} />
            ) : (
              <ObjectTree tree={tree.data} selected={obj} search={search} onSelect={select} />
            ))}
        </div>

        {tree.data && (
          <footer className="border-t px-3 py-1.5 text-xs text-muted-foreground">
            {Object.keys(tree.data.nodes).length} von {tree.data.objectCount} Objekten
            {tree.data.hiddenInternal > 0 && " · " + tree.data.hiddenInternal + " Hilfsobjekte ausgeblendet"}
            {!tree.data.guiAccurate && (
              <span title="Ohne FreeCAD-Oberfläche baut die Brücke den Baum aus Gruppen nach; er kann von FreeCADs Ansicht abweichen.">
                {" "}
                · vereinfachter Baum
              </span>
            )}
          </footer>
        )}
      </aside>

      <section className="min-h-0 min-w-0">
        {obj && !docClosed ? (
          <PropertyPanel key={doc + "\u0000" + obj} doc={doc} name={obj} tree={tree.data} onNavigate={select} />
        ) : (
          <div className="grid h-full place-items-center p-6 text-center text-sm text-muted-foreground">
            <p>
              Objekt im Baum wählen – oder in FreeCAD auswählen und „Aus FreeCAD“ klicken.
              <br />
              Änderungen werden beim Verlassen eines Feldes (oder mit Enter) übernommen, Esc verwirft.
            </p>
          </div>
        )}
      </section>
    </div>
  )
}

function ViewButton({ active, onClick, children }: { active: boolean; onClick: () => void; children: ReactNode }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "flex items-center gap-1 rounded px-2 py-0.5 text-xs",
        active ? "bg-accent text-accent-foreground" : "text-muted-foreground hover:text-foreground",
      )}
    >
      {children}
    </button>
  )
}
