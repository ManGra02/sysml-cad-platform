import { Link } from "@tanstack/react-router"
import { ArrowRight } from "lucide-react"
import { useState } from "react"
import { useTranslation } from "react-i18next"

import { Button } from "@/components/ui/button"
import { useDocumentTitle } from "@/lib/useDocumentTitle"

import { EmptyNote } from "../components/bits"
import { RequirementTable } from "../components/RequirementTable"
import { AreaIntro, GenerateMenu, OtherAssignments, RejectedList } from "../components/Sections"
import { useWorkspaceData } from "../context"

/**
 * "Assign": which measurement in FreeCAD belongs to which requirement. Suggestions are
 * decided here, row by row; results are the "Check" area's business.
 */
export function AssignView() {
  const { t } = useTranslation()
  const { workspace, commit, rows, progress: p, pending, others, strayProposals, rejected, lastProposal, setLastProposal, table } =
    useWorkspaceData()
  useDocumentTitle(t("bds.tabs.assign"), workspace.name, t("bds.list.title"))
  const [showRejected, setShowRejected] = useState(false)
  const discarded = lastProposal ? lastProposal.rejected_by_gates.length + lastProposal.dropped_by_proposer.length : 0
  const allDone = p.total > 0 && p.open === 0 && pending === 0

  return (
    <div className="space-y-4">
      <AreaIntro
        title={t("bds.assign.title")}
        actions={
          <GenerateMenu
            ws={workspace.name}
            commit={commit}
            // One primary action: suggesting, while nothing waits and something is missing.
            primary={pending === 0 && p.open > 0}
            onResult={setLastProposal}
          />
        }
      >
        {t("bds.assign.text")}
      </AreaIntro>

      {p.total > 0 && (
        <p className="text-sm font-medium">
          {t("bds.assign.status", { assigned: p.assigned, total: p.total })}
          {pending > 0 && " · " + t("bds.overview.pending", { count: pending })}
        </p>
      )}

      {allDone && (
        <div className="flex flex-wrap items-center gap-3 rounded-md border border-success/40 bg-success/5 px-4 py-2 text-sm">
          <span className="flex-1">{t("bds.assign.allDone")}</span>
          <Button asChild size="sm">
            <Link to="/projects/bds/$ws/check" params={{ ws: workspace.name }} search={(s) => s}>
              {t("bds.assign.toCheck")} <ArrowRight />
            </Link>
          </Button>
        </div>
      )}

      {rows.length === 0 ? <EmptyNote>{t("bds.table.empty")}</EmptyNote> : <RequirementTable rows={rows} context={table} mode="assign" />}

      <OtherAssignments assignments={others} proposals={strayProposals} context={table} />

      {rejected.length + discarded > 0 && (
        <button
          type="button"
          className="text-sm text-muted-foreground underline underline-offset-4"
          aria-expanded={showRejected}
          onClick={() => setShowRejected(!showRejected)}
        >
          {showRejected ? t("bds.footer.hideRejected") : t("bds.footer.rejected", { count: rejected.length + discarded })}
        </button>
      )}
      {showRejected && <RejectedList proposals={rejected} discarded={lastProposal} />}
    </div>
  )
}
