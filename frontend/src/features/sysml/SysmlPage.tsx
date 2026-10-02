import { useQuery } from "@tanstack/react-query"
import {
  Box,
  ChevronRight,
  CircleAlert,
  CircleCheck,
  ClipboardCheck,
  GitCommitHorizontal,
  Layers,
  Package,
  RefreshCw,
  Ruler,
  Search,
} from "lucide-react"
import { useMemo, useState } from "react"
import { useTranslation } from "react-i18next"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Skeleton } from "@/components/ui/skeleton"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { describeError } from "@/features/cad/format"
import { cn } from "@/lib/utils"
import { useDocumentTitle } from "@/lib/useDocumentTitle"

import {
  formatAttribute,
  formatSi,
  leafParts,
  partTree,
  requirementsOf,
  sysmlCommitsQuery,
  sysmlProjectsQuery,
  sysmlSnapshotQuery,
  sysmlStatusQuery,
  type SysmlAttribute,
  type SysmlElement,
  type SysmlSnapshot,
  type SysmlTreeNode,
} from "./queries"

/** Read-only view of the SysML v2 model in Flexo -- the same data as /api/sysml/*, for humans. */
export function SysmlPage() {
  const { t } = useTranslation()
  useDocumentTitle(t("sysml.pageTitle"))
  const status = useQuery(sysmlStatusQuery)
  const reachable = status.data?.reachable === true
  const projects = useQuery({ ...sysmlProjectsQuery, enabled: reachable })
  const [chosen, setChosen] = useState<string | null>(null)
  const project = chosen ?? projects.data?.[0]?.id ?? null
  const snapshot = useQuery({ ...sysmlSnapshotQuery(project ?? ""), enabled: reachable && project !== null })

  return (
    <div className="mx-auto max-w-6xl space-y-6 p-6">
      <div>
        <h1 className="mb-1 text-xl font-semibold">{t("sysml.title")}</h1>
        <p className="text-sm text-muted-foreground">{t("sysml.hint")}</p>
      </div>

      <StatusCard />

      {reachable && projects.isPending && <Skeleton className="h-10 w-72" />}
      {projects.isError && <p className="text-sm text-destructive">{describeError(projects.error)}</p>}
      {projects.data && projects.data.length === 0 && (
        <div className="rounded-md border border-dashed p-8 text-center text-sm text-muted-foreground">
          <p className="mb-2">{t("sysml.noProjects")}</p>
          <code className="rounded bg-muted px-2 py-1 text-xs">uv run python -m app.sysml seed-demo</code>
        </div>
      )}

      {projects.data && projects.data.length > 0 && project && (
        <div className="flex flex-wrap items-center gap-3">
          <span className="text-sm text-muted-foreground">{t("sysml.project")}</span>
          <Select value={project} onValueChange={setChosen}>
            <SelectTrigger className="w-72" aria-label={t("sysml.project")}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {projects.data.map((p) => (
                <SelectItem key={p.id} value={p.id}>
                  {p.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          {snapshot.data && (
            <span className="flex items-center gap-1 text-xs text-muted-foreground" title={snapshot.data.version}>
              <GitCommitHorizontal className="size-3.5" />
              {t("sysml.version", { id: snapshot.data.version.slice(0, 8) })}
            </span>
          )}
          <Button
            variant="ghost"
            size="sm"
            className="ml-auto"
            onClick={() => void snapshot.refetch()}
            disabled={snapshot.isFetching}
          >
            <RefreshCw className={cn(snapshot.isFetching && "animate-spin")} />
            {t("sysml.reload")}
          </Button>
        </div>
      )}

      {snapshot.isPending && project && reachable && (
        <div className="grid gap-3 sm:grid-cols-4">
          {[0, 1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-20" />
          ))}
        </div>
      )}
      {snapshot.isError && <p className="text-sm text-destructive">{describeError(snapshot.error)}</p>}
      {snapshot.data && project && <ModelView snapshot={snapshot.data} project={project} />}
    </div>
  )
}

function StatusCard() {
  const { t } = useTranslation()
  const status = useQuery(sysmlStatusQuery)
  if (status.isPending) return <Skeleton className="h-16" />
  if (status.isError) {
    return (
      <Card className="border-destructive/50 py-4">
        <CardContent className="flex items-center gap-3 px-4 text-sm">
          <CircleAlert className="size-5 text-destructive" />
          {describeError(status.error)}
        </CardContent>
      </Card>
    )
  }
  const s = status.data
  if (s.reachable) {
    return (
      <Card className="py-4">
        <CardContent className="flex flex-wrap items-center gap-3 px-4 text-sm">
          <CircleCheck className="size-5 text-success" />
          <span className="font-medium">{t("sysml.status.ok")}</span>
          <span className="text-muted-foreground">
            {t("sysml.status.projects", { count: s.projects ?? 0 })} · <span className="font-mono">{s.url}</span>
          </span>
        </CardContent>
      </Card>
    )
  }
  return (
    <Card className="border-warning py-4">
      <CardContent className="space-y-2 px-4 text-sm">
        <p className="flex items-center gap-3 font-medium">
          <CircleAlert className="size-5 text-warning" />
          {t("sysml.status.down", { url: s.url })}
        </p>
        <p className="text-muted-foreground">{t("sysml.status.downHint")}</p>
        <code className="block w-fit rounded bg-muted px-2 py-1 text-xs">cd flexo &amp;&amp; docker compose up -d</code>
      </CardContent>
    </Card>
  )
}

function ModelView({ snapshot, project }: { snapshot: SysmlSnapshot; project: string }) {
  const { t } = useTranslation()
  const tree = useMemo(() => partTree(snapshot), [snapshot])
  const leaves = useMemo(() => leafParts(snapshot), [snapshot])
  const requirements = useMemo(() => requirementsOf(snapshot), [snapshot])
  const parts = snapshot.elements.filter((e) => e.kind === "part")
  const [selected, setSelected] = useState<string | null>(null)
  const current = (selected && snapshot.elements.find((e) => e.id === selected)) || parts[0] || null

  return (
    <>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Tile icon={Box} label={t("sysml.tiles.parts")} value={parts.length} hint={t("sysml.tiles.partsHint")} />
        <Tile icon={Layers} label={t("sysml.tiles.leaves")} value={leaves.length} hint={t("sysml.tiles.leavesHint")} />
        <Tile
          icon={Ruler}
          label={t("sysml.tiles.attributes")}
          value={snapshot.attributes.length}
          hint={t("sysml.tiles.attributesHint")}
        />
        <Tile
          icon={ClipboardCheck}
          label={t("sysml.tiles.requirements")}
          value={requirements.length}
          hint={t("sysml.tiles.requirementsHint")}
        />
      </div>

      <Tabs defaultValue="structure">
        <TabsList>
          <TabsTrigger value="structure">{t("sysml.tabs.structure")}</TabsTrigger>
          <TabsTrigger value="attributes">{t("sysml.tabs.attributes")}</TabsTrigger>
          <TabsTrigger value="requirements">{t("sysml.tabs.requirements")}</TabsTrigger>
          <TabsTrigger value="history">{t("sysml.tabs.history")}</TabsTrigger>
        </TabsList>

        <TabsContent value="structure">
          <div className="grid gap-4 md:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]">
            <Card className="gap-2 py-3">
              <CardHeader className="px-4">
                <CardTitle className="text-sm">{t("sysml.tree.title")}</CardTitle>
                <CardDescription className="text-xs">{t("sysml.tree.hint")}</CardDescription>
              </CardHeader>
              <CardContent className="px-2">
                {tree.length === 0 ? (
                  <p className="px-2 py-4 text-sm text-muted-foreground">{t("sysml.tree.empty")}</p>
                ) : (
                  <ul role="tree" className="text-sm">
                    {tree.map((node) => (
                      <TreeRow
                        key={node.element.id}
                        node={node}
                        depth={0}
                        selected={current?.id ?? null}
                        onSelect={setSelected}
                        leafIds={new Set(leaves.map((l) => l.id))}
                      />
                    ))}
                  </ul>
                )}
              </CardContent>
            </Card>
            {current && <ElementDetails snapshot={snapshot} element={current} onSelect={setSelected} />}
          </div>
        </TabsContent>

        <TabsContent value="attributes">
          <AttributeTable snapshot={snapshot} />
        </TabsContent>

        <TabsContent value="requirements">
          <RequirementList snapshot={snapshot} requirements={requirements} />
        </TabsContent>

        <TabsContent value="history">
          <History project={project} current={snapshot.version} />
        </TabsContent>
      </Tabs>

      {snapshot.warnings.length > 0 && (
        <details className="text-xs text-muted-foreground">
          <summary className="cursor-pointer">{t("sysml.warnings", { count: snapshot.warnings.length })}</summary>
          <ul className="mt-2 list-disc pl-5">
            {snapshot.warnings.map((w, i) => (
              <li key={i}>{w}</li>
            ))}
          </ul>
        </details>
      )}
    </>
  )
}

function Tile({ icon: Icon, label, value, hint }: { icon: typeof Box; label: string; value: number; hint: string }) {
  return (
    <Card className="gap-1 py-4" title={hint}>
      <CardHeader className="px-4">
        <CardDescription className="flex items-center gap-1.5 text-xs">
          <Icon className="size-3.5" />
          {label}
        </CardDescription>
        <CardTitle className="text-2xl tabular-nums">{value}</CardTitle>
      </CardHeader>
      <CardContent className="px-4 text-xs text-muted-foreground">{hint}</CardContent>
    </Card>
  )
}

function TreeRow({
  node,
  depth,
  selected,
  onSelect,
  leafIds,
}: {
  node: SysmlTreeNode
  depth: number
  selected: string | null
  onSelect: (id: string) => void
  leafIds: Set<string>
}) {
  const { t } = useTranslation()
  const [open, setOpen] = useState(true)
  const e = node.element
  const isPackage = e.kind === "package"
  return (
    <li role="treeitem" aria-expanded={node.children.length ? open : undefined} aria-selected={selected === e.id}>
      <div
        className={cn(
          "flex items-center gap-1 rounded-md py-1 pr-2 hover:bg-muted/60",
          selected === e.id && "bg-accent text-accent-foreground",
        )}
        style={{ paddingLeft: depth * 16 + 4 }}
      >
        <button
          type="button"
          className={cn("grid size-5 place-items-center text-muted-foreground", !node.children.length && "invisible")}
          onClick={() => setOpen(!open)}
          aria-label={open ? t("sysml.tree.collapse") : t("sysml.tree.expand")}
        >
          <ChevronRight className={cn("size-3.5 transition-transform", open && "rotate-90")} />
        </button>
        <button
          type="button"
          className="flex min-w-0 flex-1 items-center gap-1.5 text-left"
          onClick={() => !isPackage && onSelect(e.id)}
        >
          {isPackage ? (
            <Package className="size-3.5 shrink-0 text-muted-foreground" />
          ) : (
            <Box className="size-3.5 shrink-0 text-primary" />
          )}
          <span className={cn("truncate", isPackage && "text-muted-foreground")}>{e.name}</span>
          {leafIds.has(e.id) && (
            <Badge variant="outline" className="ml-auto h-4 px-1 text-[10px]">
              {t("sysml.tree.leaf")}
            </Badge>
          )}
        </button>
      </div>
      {open && node.children.length > 0 && (
        <ul role="group">
          {node.children.map((child) => (
            <TreeRow
              key={child.element.id}
              node={child}
              depth={depth + 1}
              selected={selected}
              onSelect={onSelect}
              leafIds={leafIds}
            />
          ))}
        </ul>
      )}
    </li>
  )
}

function ElementDetails({
  snapshot,
  element,
  onSelect,
}: {
  snapshot: SysmlSnapshot
  element: SysmlElement
  onSelect: (id: string) => void
}) {
  const { t } = useTranslation()
  const byId = new Map(snapshot.elements.map((e) => [e.id, e]))
  const attributes = snapshot.attributes.filter((a) => a.owner_id === element.id)
  const types = element.type_ids.map((id) => byId.get(id)?.name).filter(Boolean)
  const children = snapshot.elements.filter((e) => e.parent_id === element.id && e.kind === "part")
  const parent = element.parent_id ? byId.get(element.parent_id) : undefined
  const satisfies = snapshot.relations
    .filter((r) => r.kind === "satisfies" && r.source_id === element.id)
    .map((r) => byId.get(r.target_id))
    .filter((r): r is SysmlElement => r !== undefined)

  return (
    <Card className="gap-3 py-4">
      <CardHeader className="px-4">
        <CardTitle className="flex flex-wrap items-center gap-2">
          <Box className="size-4 text-primary" />
          {element.name}
          {types.length > 0 && <Badge variant="secondary">: {types.join(", ")}</Badge>}
        </CardTitle>
        <CardDescription className="space-y-0.5 text-xs">
          <p className="font-mono break-all">{element.qualified_name || element.id}</p>
          {element.doc && <p>{element.doc}</p>}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4 px-4 text-sm">
        <section>
          <h3 className="mb-1.5 text-xs font-medium tracking-wide text-muted-foreground uppercase">
            {t("sysml.details.attributes")}
          </h3>
          {attributes.length === 0 ? (
            <p className="text-muted-foreground">{t("sysml.details.noAttributes")}</p>
          ) : (
            <AttributeRows attributes={attributes} />
          )}
        </section>

        {satisfies.length > 0 && (
          <section>
            <h3 className="mb-1.5 text-xs font-medium tracking-wide text-muted-foreground uppercase">
              {t("sysml.details.satisfies")}
            </h3>
            <ul className="space-y-1">
              {satisfies.map((r) => (
                <li key={r.id} className="flex items-start gap-2">
                  <ClipboardCheck className="mt-0.5 size-3.5 shrink-0 text-success" />
                  <span>
                    {r.extra.req_id && <span className="mr-1 font-mono text-xs">{r.extra.req_id}</span>}
                    {r.extra.text || r.name}
                  </span>
                </li>
              ))}
            </ul>
          </section>
        )}

        <section className="flex flex-wrap gap-x-6 gap-y-1 text-xs text-muted-foreground">
          {parent && parent.kind === "part" && (
            <span>
              {t("sysml.details.partOf")}{" "}
              <button type="button" className="underline" onClick={() => onSelect(parent.id)}>
                {parent.name}
              </button>
            </span>
          )}
          {children.length > 0 && (
            <span>
              {t("sysml.details.contains")}{" "}
              {children.map((c, i) => (
                <span key={c.id}>
                  {i > 0 && ", "}
                  <button type="button" className="underline" onClick={() => onSelect(c.id)}>
                    {c.name}
                  </button>
                </span>
              ))}
            </span>
          )}
          {children.length === 0 && <span>{t("sysml.details.leafHint")}</span>}
        </section>
      </CardContent>
    </Card>
  )
}

function AttributeRows({ attributes, owners }: { attributes: SysmlAttribute[]; owners?: Map<string, SysmlElement> }) {
  const { t } = useTranslation()
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead className="text-left text-xs text-muted-foreground">
          <tr className="border-b">
            {owners && <th className="py-1.5 pr-3 font-medium">{t("sysml.columns.element")}</th>}
            <th className="py-1.5 pr-3 font-medium">{t("sysml.columns.attribute")}</th>
            <th className="py-1.5 pr-3 font-medium">{t("sysml.columns.value")}</th>
            <th className="py-1.5 font-medium">{t("sysml.columns.si")}</th>
          </tr>
        </thead>
        <tbody>
          {attributes.map((a) => {
            const si = formatSi(a)
            return (
              <tr key={a.id} className="border-b last:border-0">
                {owners && <td className="py-1.5 pr-3">{owners.get(a.owner_id)?.name ?? "—"}</td>}
                <td className="py-1.5 pr-3 font-mono text-xs">{a.name}</td>
                <td className="py-1.5 pr-3 tabular-nums" title={a.expression ?? undefined}>
                  {formatAttribute(a)}
                  {a.warnings.length > 0 && (
                    <CircleAlert className="ml-1 inline size-3.5 text-warning" aria-label={a.warnings.join("; ")} />
                  )}
                </td>
                <td className="py-1.5 text-muted-foreground tabular-nums">{si ?? "—"}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

function AttributeTable({ snapshot }: { snapshot: SysmlSnapshot }) {
  const { t } = useTranslation()
  const [filter, setFilter] = useState("")
  const owners = useMemo(() => new Map(snapshot.elements.map((e) => [e.id, e])), [snapshot])
  const needle = filter.trim().toLowerCase()
  const rows = snapshot.attributes
    .filter((a) => !needle || a.name.toLowerCase().includes(needle) || (owners.get(a.owner_id)?.name ?? "").toLowerCase().includes(needle))
    .sort((a, b) => (owners.get(a.owner_id)?.name ?? "").localeCompare(owners.get(b.owner_id)?.name ?? "") || a.name.localeCompare(b.name))
  return (
    <Card className="gap-3 py-4">
      <CardHeader className="px-4">
        <CardTitle className="text-sm">{t("sysml.attributes.title")}</CardTitle>
        <CardDescription className="text-xs">{t("sysml.attributes.hint")}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3 px-4">
        <div className="relative w-72 max-w-full">
          <Search className="absolute top-2.5 left-2.5 size-3.5 text-muted-foreground" />
          <Input
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            placeholder={t("sysml.attributes.filter")}
            className="pl-8"
          />
        </div>
        {rows.length === 0 ? (
          <p className="text-sm text-muted-foreground">{t("sysml.attributes.none")}</p>
        ) : (
          <AttributeRows attributes={rows} owners={owners} />
        )}
      </CardContent>
    </Card>
  )
}

function RequirementList({ snapshot, requirements }: { snapshot: SysmlSnapshot; requirements: SysmlElement[] }) {
  const { t } = useTranslation()
  const byId = new Map(snapshot.elements.map((e) => [e.id, e]))
  if (requirements.length === 0) {
    return <p className="rounded-md border border-dashed p-8 text-center text-sm text-muted-foreground">{t("sysml.requirements.none")}</p>
  }
  return (
    <div className="grid gap-3 md:grid-cols-2">
      {requirements.map((r) => {
        const by = snapshot.relations
          .filter((rel) => rel.kind === "satisfies" && rel.target_id === r.id)
          .map((rel) => byId.get(rel.source_id)?.name)
          .filter(Boolean)
        return (
          <Card key={r.id} className="gap-2 py-4">
            <CardHeader className="px-4">
              <CardTitle className="flex items-center gap-2 text-sm">
                <ClipboardCheck className="size-4 text-muted-foreground" />
                {r.extra.req_id && <span className="font-mono">{r.extra.req_id}</span>}
                <span className="truncate text-muted-foreground">{r.name}</span>
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-2 px-4 text-sm">
              <p>{r.extra.text || r.doc || "—"}</p>
              <p className="flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
                {by.length > 0 ? (
                  <>
                    {t("sysml.requirements.satisfiedBy")}
                    {by.map((name) => (
                      <Badge key={name} variant="secondary">
                        {name}
                      </Badge>
                    ))}
                  </>
                ) : (
                  <Badge variant="outline" className="border-warning text-warning">
                    {t("sysml.requirements.notSatisfied")}
                  </Badge>
                )}
              </p>
            </CardContent>
          </Card>
        )
      })}
    </div>
  )
}

function History({ project, current }: { project: string; current: string }) {
  const { t, i18n } = useTranslation()
  const commits = useQuery(sysmlCommitsQuery(project))
  if (commits.isPending) return <Skeleton className="h-24" />
  if (commits.isError) return <p className="text-sm text-destructive">{describeError(commits.error)}</p>
  return (
    <Card className="gap-2 py-4">
      <CardHeader className="px-4">
        <CardTitle className="text-sm">{t("sysml.history.title")}</CardTitle>
        <CardDescription className="text-xs">{t("sysml.history.hint")}</CardDescription>
      </CardHeader>
      <CardContent className="px-4">
        <ol className="space-y-2 text-sm">
          {commits.data.map((c) => (
            <li key={c.id} className="flex flex-wrap items-center gap-2">
              <GitCommitHorizontal className="size-4 text-muted-foreground" />
              <span className="font-mono text-xs" title={c.id}>
                {c.id.slice(0, 8)}
              </span>
              <span>{c.description || t("sysml.history.noDescription")}</span>
              {c.created && (
                <span className="text-xs text-muted-foreground">
                  {new Date(c.created).toLocaleString(i18n.language)}
                </span>
              )}
              {c.id === current && <Badge variant="secondary">{t("sysml.history.shown")}</Badge>}
            </li>
          ))}
        </ol>
      </CardContent>
    </Card>
  )
}
