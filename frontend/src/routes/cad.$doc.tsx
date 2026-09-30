import { useQuery, useQueryClient } from "@tanstack/react-query"
import { Link, createFileRoute } from "@tanstack/react-router"
import { ListTree, MousePointerClick, RefreshCw, Search, Table2 } from "lucide-react"
import { useState, type ReactNode } from "react"
import { useTranslation } from "react-i18next"
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
import { useDocumentTitle } from "@/lib/useDocumentTitle"
import { cn } from "@/lib/utils"

// Addressing always goes through doc.Name (path) and obj.Name (?obj=) -- never
// through labels. The browser deliberately does NOT automatically follow the
// active FreeCAD document: every write request carries its target document explicitly.
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
  const { t } = useTranslation()
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
  const selectedLabel = obj ? (tree.data?.nodes[obj]?.label ?? obj) : undefined
  useDocumentTitle(selectedLabel, info?.label ?? doc, t("nav.cadExplorer"))

  if (!ready) return <BridgeNotReady state={bridge} />

  const select = (name: string, options?: { replace?: boolean }) =>
    navigate({ search: (old) => ({ ...old, obj: name }), replace: options?.replace })

  const fromFreeCAD = async () => {
    try {
      const { available, selection } = await getSelection()
      if (!available) return toast.info(t("explorer.noGuiSelection"))
      const first = selection[0]
      if (!first) return toast.info(t("explorer.nothingSelected"))
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
      toast.success(t("explorer.recomputed", { count: result.recomputed }))
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
              <TooltipContent>{t("explorer.recompute")}</TooltipContent>
            </Tooltip>
          </div>
          {info?.modified && (
            <Badge variant="outline" className="border-warning text-warning" title={t("explorer.unsavedHint")}>
              {t("explorer.unsavedBadge")}
            </Badge>
          )}
          <div className="flex items-center gap-2">
            <div className="flex rounded-md border p-0.5">
              <ViewButton active={view === "tree"} onClick={() => navigate({ search: (old) => ({ ...old, view: undefined }) })}>
                <ListTree className="size-3.5" /> {t("explorer.viewTree")}
              </ViewButton>
              <ViewButton active={view === "table"} onClick={() => navigate({ search: (old) => ({ ...old, view: "table" }) })}>
                <Table2 className="size-3.5" /> {t("explorer.viewTable")}
              </ViewButton>
            </div>
            <Tooltip>
              <TooltipTrigger asChild>
                <Button variant="outline" size="sm" className="ml-auto h-7 text-xs" onClick={() => void fromFreeCAD()}>
                  <MousePointerClick /> {t("explorer.fromFreeCAD")}
                </Button>
              </TooltipTrigger>
              <TooltipContent>{t("explorer.fromFreeCADHint")}</TooltipContent>
            </Tooltip>
          </div>
          <div className="relative">
            <Search className="absolute top-2 left-2 size-3.5 text-muted-foreground" />
            <Input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder={t("explorer.searchPlaceholder")}
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
              {t("explorer.showInternal")}
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
                  {t("explorer.toDocumentList")}
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
            {t("explorer.count", { shown: Object.keys(tree.data.nodes).length, total: tree.data.objectCount })}
            {tree.data.hiddenInternal > 0 && " · " + t("explorer.hiddenInternal", { count: tree.data.hiddenInternal })}
            {!tree.data.guiAccurate && (
              <span title={t("explorer.simplifiedTreeHint")}>
                {" "}
                · {t("explorer.simplifiedTree")}
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
              {t("explorer.emptyHint")}
              <br />
              {t("explorer.editHint")}
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
