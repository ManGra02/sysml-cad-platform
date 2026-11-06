import { useQuery, useQueryClient } from "@tanstack/react-query"
import { Link } from "@tanstack/react-router"
import { ArrowLeft, ChevronDown, Settings, Sparkles } from "lucide-react"
import { useState, type ReactNode } from "react"
import { useTranslation } from "react-i18next"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { aiStatusQuery } from "@/features/ai/queries"
import { describeError } from "@/features/cad/format"
import type { SysmlCommit } from "@/features/sysml/queries"
import { cn } from "@/lib/utils"

import type { WorkspaceData } from "../context"
import { type Assignment, type RequirementRow } from "../logic"
import { invalidateMapping, propose, updateEntry, type Proposal, type ProposeResult, type Workspace } from "../queries"
import { Measurement } from "./bits"
import { ProposalCard, type TableContext } from "./RequirementTable"

// The workspace's frame: header and area tabs, an area's heading, the "suggest" menu, and
// the sections under the assignment table.

/** Name and what it links; model version and settings sit in one menu (rarely needed). */
export function WorkspaceHeader({ workspace, commits, commit, onCommit, onSettings, children }: {
  workspace: Workspace
  commits: SysmlCommit[]
  commit?: string
  onCommit: (commit?: string) => void
  onSettings: () => void
  /** The area tabs, at the header's lower edge. */
  children?: ReactNode
}) {
  const { t, i18n } = useTranslation()
  const head = commits[0]?.id
  return (
    <header className="border-b bg-background">
      <div className="mx-auto flex max-w-6xl flex-col gap-1 px-4 pt-3 sm:px-6">
        <Link to="/projects/bds" className="inline-flex w-fit items-center gap-1 text-sm text-muted-foreground hover:underline">
          <ArrowLeft className="size-3.5" aria-hidden="true" /> {t("bds.page.back")}
        </Link>
        <div className="flex flex-wrap items-center gap-x-5 gap-y-2">
          <h1 className="text-xl font-semibold">{workspace.name}</h1>
          <span className="text-sm text-muted-foreground">
            SysML „{workspace.sysml_project}“ ↔ FreeCAD „{workspace.cad_document || t("bds.page.noDocument")}“
          </span>
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="outline" size="sm" className="ml-auto">
                <Settings /> {t("bds.page.settings")} <ChevronDown />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-72">
              <DropdownMenuItem onSelect={onSettings}>{t("bds.page.editSettings")}</DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuSub>
                <DropdownMenuSubTrigger>
                  {t("bds.page.version")}: {commit ? commit.slice(0, 8) : t("bds.page.head")}
                </DropdownMenuSubTrigger>
                <DropdownMenuSubContent className="max-h-80 w-80 overflow-y-auto">
                  <DropdownMenuLabel className="text-xs font-normal text-muted-foreground">{t("bds.page.versionHint")}</DropdownMenuLabel>
                  <DropdownMenuRadioGroup value={commit ?? "head"} onValueChange={(value) => onCommit(value === "head" ? undefined : value)}>
                    <DropdownMenuRadioItem value="head">
                      {head ? t("bds.page.headId", { id: head.slice(0, 8) }) : t("bds.page.head")}
                    </DropdownMenuRadioItem>
                    {commits.slice(1).map((c) => (
                      <DropdownMenuRadioItem key={c.id} value={c.id}>
                        {c.id.slice(0, 8)}
                        {c.created ? " · " + new Date(c.created).toLocaleString(i18n.language) : ""}
                        {c.description ? " · " + c.description : ""}
                      </DropdownMenuRadioItem>
                    ))}
                  </DropdownMenuRadioGroup>
                </DropdownMenuSubContent>
              </DropdownMenuSub>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
        <div className="mt-2">{children}</div>
      </div>
    </header>
  )
}

type Area = { to: "/projects/bds/$ws" | "/projects/bds/$ws/assign" | "/projects/bds/$ws/check" | "/projects/bds/$ws/limits" | "/projects/bds/$ws/models"; label: string; direction?: string; badge?: ReactNode }

/**
 * The areas of a workspace, each answering one question: assign (which measurement
 * belongs to which requirement), check (CAD -> SysML), limits (SysML -> CAD, optional),
 * models (reference). The badge says where the area stands.
 */
export function WorkspaceTabs({ data }: { data: WorkspaceData }) {
  const { t } = useTranslation()
  const { progress: p, pending, run, stale } = data
  const badge = (text: string, tone: "muted" | "warning" | "destructive" = "muted") => (
    <span
      className={cn(
        "rounded-full px-1.5 text-[11px] leading-4 font-medium",
        tone === "muted" && "bg-muted text-muted-foreground",
        tone === "warning" && "bg-warning/15 text-foreground",
        tone === "destructive" && "bg-destructive/15 text-foreground",
      )}
    >
      {text}
    </span>
  )
  const areas: Area[] = [
    { to: "/projects/bds/$ws", label: t("bds.tabs.overview") },
    {
      to: "/projects/bds/$ws/assign",
      label: t("bds.tabs.assign"),
      direction: t("bds.tabs.assignDir"),
      badge: p.total > 0 && badge(`${p.assigned}/${p.total}`, pending > 0 ? "warning" : "muted"),
    },
    {
      to: "/projects/bds/$ws/check",
      label: t("bds.tabs.check"),
      direction: t("bds.tabs.checkDir"),
      badge: run && (stale || p.unchecked > 0 ? badge(t("bds.tabs.stale"), "warning") : p.violated > 0 ? badge(t("bds.tabs.violated", { count: p.violated }), "destructive") : null),
    },
    { to: "/projects/bds/$ws/limits", label: t("bds.tabs.limits"), direction: t("bds.tabs.limitsDir"), badge: badge(t("bds.tabs.optional")) },
    { to: "/projects/bds/$ws/models", label: t("bds.tabs.models") },
  ]
  return (
    <nav aria-label={t("bds.tabs.label")} className="-mb-px flex overflow-x-auto [scrollbar-width:none]">
      {areas.map((area) => (
        <Link
          key={area.to}
          to={area.to}
          params={{ ws: data.workspace.name }}
          search={(s) => s}
          activeOptions={{ exact: true, includeSearch: false }}
          className="flex shrink-0 flex-col border-b-2 border-transparent px-3 pt-2 pb-2 text-sm text-muted-foreground hover:text-foreground"
          activeProps={{ className: "border-foreground! text-foreground font-medium", "aria-current": "page" }}
        >
          <span className="flex items-center gap-1.5">
            {area.label} {area.badge}
          </span>
          <span className="text-[11px] leading-4 font-normal text-muted-foreground">{area.direction ?? "\u00a0"}</span>
        </Link>
      ))}
    </nav>
  )
}

/** Heading of an area: what it is for, and its one main action on the right. */
export function AreaIntro({ title, badge, children, actions }: { title: string; badge?: string; children: ReactNode; actions?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-4">
      <div className="min-w-0 flex-[1_1_28rem] space-y-1">
        <h2 className="flex items-center gap-2 text-lg font-semibold">
          {title}
          {badge && <span className="rounded-full bg-muted px-2 text-xs font-medium text-muted-foreground">{badge}</span>}
        </h2>
        <div className="text-sm text-muted-foreground">{children}</div>
      </div>
      {actions && <div className="flex flex-col items-end gap-1">{actions}</div>}
    </div>
  )
}

/** "Suggest assignments ▾": by name match, or with the AI when it is set up. */
export function GenerateMenu({ ws, commit, primary, label, onResult }: {
  ws: string
  commit?: string
  primary?: boolean
  label?: string
  onResult: (result: ProposeResult) => void
}) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const ai = useQuery(aiStatusQuery)
  const model = ai.data?.projects.bds?.model
  const aiReady = !!ai.data?.configured && !!model
  const [pending, setPending] = useState(false)

  const run = async (proposer: "difflib" | "ai") => {
    setPending(true)
    try {
      const result = await propose(ws, { proposer, top: 1, dry_run: false, commit })
      onResult(result)
      invalidateMapping(queryClient, ws)
      const discarded = result.rejected_by_gates.length + result.dropped_by_proposer.length
      const message = result.stored.length ? t("bds.actions.generated", { count: result.stored.length }) : t("bds.actions.generatedNone")
      toast.success(message, discarded ? { description: t("bds.actions.discarded", { count: discarded }) } : undefined)
    } catch (error) {
      toast.error(describeError(error))
    } finally {
      setPending(false)
    }
  }

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant={primary ? "default" : "outline"} disabled={pending}>
          <Sparkles /> {pending ? t("bds.actions.generating") : label ?? t("bds.actions.generate")} <ChevronDown />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="w-80">
        <DropdownMenuItem onSelect={() => void run("difflib")} className="flex-col items-start gap-0.5">
          <span className="font-medium">{t("bds.actions.byName")}</span>
          <span className="text-xs text-muted-foreground">{t("bds.actions.byNameHint")}</span>
        </DropdownMenuItem>
        <DropdownMenuItem disabled={!aiReady} onSelect={() => void run("ai")} className="flex-col items-start gap-0.5">
          <span className="font-medium">{t("bds.actions.byAi")}</span>
          <span className="text-xs text-muted-foreground">
            {aiReady ? t("bds.actions.byAiHint", { model }) : t("bds.actions.aiOff")}
          </span>
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

/** Confirmed entries no requirement uses -- and suggestions for attributes without one. */
export function OtherAssignments({ assignments, proposals, context }: {
  assignments: Assignment[]
  proposals: Proposal[]
  context: TableContext
}) {
  const { t } = useTranslation()
  const [busy, setBusy] = useState<string>()
  if (assignments.length === 0 && proposals.length === 0) return null

  const link = async (a: Assignment) => {
    if (!a.linkable) return
    setBusy(a.entry.sysml_part + "." + a.entry.attribute)
    try {
      await updateEntry(context.workspace.name, a.entry, { requirement: a.linkable.requirement })
      context.actions.changed()
    } catch (error) {
      toast.error(describeError(error))
    } finally {
      setBusy(undefined)
    }
  }

  return (
    <div className="space-y-3">
      {assignments.length > 0 && (
        <details className="rounded-lg border bg-card px-4 py-3">
          <summary className="cursor-pointer text-sm">
            <span className="font-semibold">{t("bds.other.title", { count: assignments.length })}</span>{" "}
            <span className="text-muted-foreground">{t("bds.other.hint")}</span>
          </summary>
          <ul className="mt-3 divide-y text-sm">
            {assignments.map((a) => {
              const target = a.cadObject ? context.targets.get(a.cadObject) : undefined
              const key = a.entry.sysml_part + "." + a.entry.attribute
              return (
                <li key={key + a.entry.method} className="flex flex-wrap items-center gap-x-2 gap-y-1 py-2">
                  <code className="rounded bg-muted px-1.5 py-0.5 text-xs">{key}</code>
                  <span aria-hidden="true" className="text-muted-foreground">←</span>
                  <Measurement method={a.entry.method} args={a.entry.args} axes={context.workspace.axes} target={target} objectName={target?.name} attribute={a.entry.attribute} />
                  <span className="ml-auto flex gap-2">
                    {a.linkable && (
                      <Button size="sm" variant="outline" disabled={busy === key} onClick={() => void link(a)}>
                        {t("bds.other.link", { requirement: a.linkable.requirement })}
                      </Button>
                    )}
                    <Button size="sm" variant="ghost" onClick={() => void context.actions.release(a.entry, a.cadObject)}>
                      {t("bds.row.release")}
                    </Button>
                  </span>
                </li>
              )
            })}
          </ul>
        </details>
      )}
      {proposals.length > 0 && (
        <details className="rounded-lg border bg-card px-4 py-3">
          <summary className="cursor-pointer text-sm">
            <span className="font-semibold">{t("bds.other.proposals", { count: proposals.length })}</span>{" "}
            <span className="text-muted-foreground">{t("bds.other.hint")}</span>
          </summary>
          <div className="mt-3 space-y-2">
            {proposals.map((p) => (
              <ProposalCard key={p.id} proposal={p} row={{ id: "", part: p.sysml_part, attribute: p.attribute }} context={context} />
            ))}
          </div>
        </details>
      )}
    </div>
  )
}

/** Discarded suggestions -- by a person, or by the checks before anyone saw them. Shown on request. */
export function RejectedList({ proposals, discarded }: { proposals: Proposal[]; discarded: ProposeResult | undefined }) {
  const { t, i18n } = useTranslation()
  const before = discarded
    ? [
        ...discarded.rejected_by_gates.map((r) => (r.attribute ? `${r.sysml_part}.${r.attribute} → ${r.cad_object}: ${r.reason}` : `${r.sysml_part}: ${r.reason}`)),
        ...discarded.dropped_by_proposer,
      ]
    : []
  return (
    <div className="space-y-3 rounded-lg border bg-card px-4 py-3 text-sm">
      {proposals.length > 0 && (
        <ul className="space-y-1">
          {proposals.map((p) => (
            <li key={p.id} className="flex flex-wrap gap-x-2 text-muted-foreground">
              <code className="text-xs">
                {p.sysml_part}.{p.attribute}
              </code>
              → {p.cad_object} · {p.method}
              <span className="ml-auto text-xs">
                {t("bds.footer.rejectedAt", { when: p.decided_at ? new Date(p.decided_at).toLocaleString(i18n.language) : "—" })}
                {p.reason ? " · " + p.reason : ""}
              </span>
            </li>
          ))}
        </ul>
      )}
      {before.length > 0 && (
        <div>
          <strong className="font-medium">{t("bds.footer.discardedBefore")}</strong>
          <ul className="mt-1 list-disc space-y-1 pl-5 text-xs text-muted-foreground">
            {before.map((reason, i) => (
              <li key={i}>{reason}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}

export type { RequirementRow }
