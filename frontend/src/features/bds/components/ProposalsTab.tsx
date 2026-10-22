import { useQuery, useQueryClient } from "@tanstack/react-query"
import { Sparkles } from "lucide-react"
import { useState } from "react"
import { useTranslation } from "react-i18next"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Skeleton } from "@/components/ui/skeleton"
import { Switch } from "@/components/ui/switch"
import { aiStatusQuery } from "@/features/ai/queries"
import { describeError } from "@/features/cad/format"
import { cn } from "@/lib/utils"

import { defaultRequirement, describeMethod, requirementsOf } from "../logic"
import {
  catalogQuery,
  confirmProposal,
  invalidateMapping,
  propose,
  proposalsQuery,
  rejectProposal,
  type Proposal,
  type ProposalStatus,
  type ProposeResult,
  type Requirement,
} from "../queries"
import type { TabProps } from "../WorkspacePage"
import { EmptyNote, GateChip } from "./bits"

const NO_REQUIREMENT = "__none__"

export function ProposalsTab({ workspace, commit }: TabProps) {
  const { t } = useTranslation()
  const proposals = useQuery(proposalsQuery(workspace.name, commit))
  const catalog = useQuery(catalogQuery(workspace.name, commit))
  const [status, setStatus] = useState<ProposalStatus>("proposed")
  const [lastRun, setLastRun] = useState<ProposeResult>()
  const all = proposals.data ?? []
  const shown = all.filter((p) => p.status === status)
  const count = (s: ProposalStatus) => all.filter((p) => p.status === s).length

  return (
    <div className="space-y-4">
      <GenerateBar ws={workspace.name} commit={commit} onResult={setLastRun} />
      {lastRun && <LastRunNotice result={lastRun} />}

      <nav aria-label={t("bds.proposals.filter")} className="flex gap-1 text-sm">
        {(["proposed", "confirmed", "rejected"] as const).map((s) => (
          <button
            key={s}
            type="button"
            onClick={() => setStatus(s)}
            className={cn("rounded-md px-3 py-1.5", s === status ? "bg-muted font-medium" : "text-muted-foreground")}
          >
            {t(`bds.proposals.status.${s}`)} ({count(s)})
          </button>
        ))}
      </nav>

      {proposals.isPending && <Skeleton className="h-40" />}
      {proposals.isError && <p className="text-sm text-destructive">{describeError(proposals.error)}</p>}
      {proposals.data && shown.length === 0 && (
        <EmptyNote>{status === "proposed" ? t("bds.proposals.nonePending") : t("bds.proposals.none")}</EmptyNote>
      )}
      <div className="space-y-3">
        {shown.map((proposal) => (
          <ProposalCard
            key={proposal.id}
            ws={workspace.name}
            commit={commit}
            proposal={proposal}
            requirements={catalog.data?.requirements ?? []}
          />
        ))}
      </div>
    </div>
  )
}

function GenerateBar({ ws, commit, onResult }: { ws: string; commit?: string; onResult: (r: ProposeResult) => void }) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const ai = useQuery(aiStatusQuery)
  const model = ai.data?.projects.bds?.model
  const aiReady = !!ai.data?.configured && !!model
  const [proposer, setProposer] = useState<"difflib" | "ai">("difflib")
  const [top, setTop] = useState("1")
  const [dryRun, setDryRun] = useState(false)
  const [pending, setPending] = useState(false)

  const generate = async () => {
    setPending(true)
    try {
      const result = await propose(ws, { proposer, top: Number(top), dry_run: dryRun, commit })
      onResult(result)
      invalidateMapping(queryClient, ws)
      toast.success(
        dryRun
          ? t("bds.proposals.generatedDry", { count: result.candidates.length })
          : t("bds.proposals.generated", { count: result.stored.length }),
      )
    } catch (error) {
      toast.error(describeError(error))
    } finally {
      setPending(false)
    }
  }

  return (
    <section className="flex flex-wrap items-center gap-3 rounded-lg border bg-muted/30 px-4 py-3">
      <span className="text-sm font-semibold">{t("bds.proposals.newTitle")}</span>
      <div role="group" aria-label={t("bds.proposals.proposer")} className="flex overflow-hidden rounded-md border text-sm">
        <button
          type="button"
          onClick={() => setProposer("difflib")}
          className={cn("h-8 px-3", proposer === "difflib" ? "bg-primary text-primary-foreground" : "bg-background")}
        >
          {t("bds.proposals.difflib")}
        </button>
        <button
          type="button"
          disabled={!aiReady}
          title={aiReady ? undefined : t("bds.proposals.aiUnavailable")}
          onClick={() => setProposer("ai")}
          className={cn(
            "h-8 border-l px-3 disabled:opacity-50",
            proposer === "ai" ? "bg-primary text-primary-foreground" : "bg-background",
          )}
        >
          <Sparkles className="mr-1 inline size-3.5" />
          {t("bds.proposals.ai", { model: model ?? "—" })}
        </button>
      </div>
      <label className="flex items-center gap-2 text-sm">
        {t("bds.proposals.top")}
        <Select value={top} onValueChange={setTop}>
          <SelectTrigger size="sm" className="w-16">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="1">1</SelectItem>
            <SelectItem value="3">3</SelectItem>
          </SelectContent>
        </Select>
      </label>
      <label className="flex items-center gap-2 text-sm">
        <Switch checked={dryRun} onCheckedChange={setDryRun} /> {t("bds.proposals.dryRun")}
      </label>
      <Button className="ml-auto" disabled={pending} onClick={() => void generate()}>
        {pending ? t("bds.proposals.generating") : t("bds.proposals.generate")}
      </Button>
    </section>
  )
}

function LastRunNotice({ result }: { result: ProposeResult }) {
  const { t } = useTranslation()
  const rejected = result.rejected_by_gates
  const dropped = result.dropped_by_proposer
  return (
    <details open={rejected.length + dropped.length > 0} className="rounded-lg border border-blue-200 bg-blue-50 px-4 py-3 text-sm text-blue-900 dark:border-blue-800 dark:bg-blue-950 dark:text-blue-100">
      <summary className="cursor-pointer font-medium">
        {t("bds.proposals.lastRun", {
          proposer: result.proposer,
          candidates: result.candidates.length,
          stored: result.stored.length,
          rejected: rejected.length,
          dropped: dropped.length,
        })}
      </summary>
      <ul className="mt-2 list-disc space-y-1 pl-5">
        {rejected.map((r, i) => (
          <li key={"g" + i}>
            {r.attribute ? `${r.sysml_part}.${r.attribute} → ${r.cad_object} (${r.method})` : r.sysml_part}: <em>{r.reason}</em>
          </li>
        ))}
        {dropped.map((reason, i) => (
          <li key={"d" + i}>
            {t("bds.proposals.droppedByModel")}: <em>{reason}</em>
          </li>
        ))}
      </ul>
    </details>
  )
}

function ProposalCard({ ws, commit, proposal: p, requirements }: {
  ws: string
  commit?: string
  proposal: Proposal
  requirements: Requirement[]
}) {
  const { t, i18n } = useTranslation()
  const queryClient = useQueryClient()
  const options = requirementsOf(requirements, p.sysml_part)
  const suggested = defaultRequirement(requirements, p.sysml_part, p.attribute)
  // The suggestion arrives with the catalogue; a choice of the reviewer wins over it.
  const [chosen, setRequirement] = useState<string>()
  const requirement = chosen ?? (p.requirement || suggested || NO_REQUIREMENT)
  const [rejecting, setRejecting] = useState(false)
  const [pending, setPending] = useState(false)
  const blocked = p.check?.verdict === "invalid"
  const ai = p.proposed_by.startsWith("ai:")

  const confirm = async () => {
    setPending(true)
    try {
      const result = await confirmProposal(ws, p.id, {
        requirement: requirement === NO_REQUIREMENT ? undefined : requirement,
        commit,
      })
      toast.success(t("bds.proposals.confirmed", { id: p.id }))
      if (!result.part_usable) toast.warning(t("bds.proposals.partNotConfirmed", { part: p.sysml_part }))
      invalidateMapping(queryClient, ws)
    } catch (error) {
      toast.error(describeError(error))
      invalidateMapping(queryClient, ws)
    } finally {
      setPending(false)
    }
  }

  return (
    <article className={cn("space-y-3 rounded-lg border p-4", p.check?.verdict === "unknown" && "border-warning/40")}>
      <div className="flex flex-wrap items-center gap-2">
        <code className="text-xs text-muted-foreground">{p.id}</code>
        <span className="font-semibold">
          {p.sysml_part}.{p.attribute}
        </span>
        <span className="text-muted-foreground">→</span>
        <code className="text-sm">{p.cad_object}</code>
        <span className="text-sm text-muted-foreground">{describeMethod(p.method, p.args)}</span>
        <span
          className={cn(
            "ml-auto rounded-full px-2 py-0.5 text-xs",
            ai ? "bg-violet-100 text-violet-800 dark:bg-violet-950 dark:text-violet-200" : "bg-muted",
          )}
          title={p.provenance?.prompt_digest ? t("bds.proposals.provenance", { model: p.provenance.model, prompt_digest: p.provenance.prompt_digest }) : undefined}
        >
          {ai ? t("bds.proposals.byAi", { model: p.proposed_by.slice(3) }) : t("bds.proposals.byDifflib")}
        </span>
      </div>

      <div className="flex items-center gap-2 text-xs text-muted-foreground">
        {t("bds.proposals.confidence")}
        <span className="h-1.5 w-40 overflow-hidden rounded-full bg-muted" aria-hidden="true">
          <span className="block h-1.5 bg-foreground" style={{ width: `${Math.round(p.confidence * 100)}%` }} />
        </span>
        {p.confidence.toFixed(2)}
      </div>

      {p.rationale && <p className="text-sm text-muted-foreground">{p.rationale}</p>}

      {p.check && (
        <div className="flex flex-wrap gap-1.5">
          {p.check.gates.map((result) => (
            <GateChip key={result.gate} result={result} />
          ))}
        </div>
      )}

      {p.status === "proposed" ? (
        <div className="flex flex-wrap items-center gap-3 border-t pt-3">
          <Label className="text-sm font-normal">
            {t("bds.proposals.checkedBy")}
            <Select value={requirement} onValueChange={setRequirement}>
              <SelectTrigger size="sm" className="min-w-60">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={NO_REQUIREMENT}>{t("bds.proposals.noRequirement")}</SelectItem>
                {options.map((r) => (
                  <SelectItem key={r.requirement} value={r.requirement}>
                    {r.requirement} ({r.operator} {r.limit.text})
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </Label>
          <span className={cn("text-xs", requirement === NO_REQUIREMENT ? "text-warning" : "text-muted-foreground")}>
            {requirement === NO_REQUIREMENT
              ? t("bds.proposals.noRequirementHint")
              : requirement === suggested
                ? t("bds.proposals.suggested")
                : ""}
          </span>
          <span className="ml-auto flex gap-2">
            <Button variant="outline" size="sm" onClick={() => setRejecting(true)}>
              {t("bds.proposals.reject")}
            </Button>
            <Button
              size="sm"
              disabled={pending || blocked}
              title={blocked ? t("bds.proposals.blocked") : undefined}
              onClick={() => void confirm()}
            >
              {t("bds.proposals.confirm")}
            </Button>
          </span>
        </div>
      ) : (
        <p className="border-t pt-3 text-xs text-muted-foreground">
          {t(`bds.proposals.decided.${p.status}`, {
            when: p.decided_at ? new Date(p.decided_at).toLocaleString(i18n.language) : "—",
          })}
          {p.reason ? " · " + p.reason : ""}
        </p>
      )}

      {rejecting && <RejectDialog ws={ws} proposal={p} onClose={() => setRejecting(false)} />}
    </article>
  )
}

function RejectDialog({ ws, proposal: p, onClose }: { ws: string; proposal: Proposal; onClose: () => void }) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const [reason, setReason] = useState("")
  const [pending, setPending] = useState(false)

  const reject = async () => {
    setPending(true)
    try {
      await rejectProposal(ws, p.id, reason)
      toast.success(t("bds.proposals.rejected", { id: p.id }))
      invalidateMapping(queryClient, ws)
      onClose()
    } catch (error) {
      toast.error(describeError(error))
    } finally {
      setPending(false)
    }
  }

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("bds.proposals.rejectTitle", { id: p.id })}</DialogTitle>
          <DialogDescription>
            {p.sysml_part}.{p.attribute} → {p.cad_object} · {describeMethod(p.method, p.args)}. {t("bds.proposals.rejectHint")}
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-1.5">
          <Label htmlFor="bds-reason">{t("bds.proposals.reason")}</Label>
          <textarea
            id="bds-reason"
            rows={4}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            className="w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm shadow-xs outline-none focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50"
          />
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            {t("bds.common.cancel")}
          </Button>
          <Button variant="destructive" disabled={pending} onClick={() => void reject()}>
            {t("bds.proposals.reject")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
