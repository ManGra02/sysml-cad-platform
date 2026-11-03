import { Link } from "@tanstack/react-router"
import { Play } from "lucide-react"
import { useTranslation } from "react-i18next"

import { Button } from "@/components/ui/button"
import { describeError } from "@/features/cad/format"
import { useDocumentTitle } from "@/lib/useDocumentTitle"

import { EmptyNote } from "../components/bits"
import { RequirementTable } from "../components/RequirementTable"
import { AreaIntro } from "../components/Sections"
import { useWorkspaceData } from "../context"

/**
 * "Check", CAD -> SysML: measure the assigned values in FreeCAD and compare them with the
 * limits. Everything about the result's freshness (FreeCAD gone, document closed, model
 * changed) is said here, and only here.
 */
export function CheckView() {
  const { t, i18n } = useTranslation()
  const { workspace, rows, progress: p, run, runError, table, actions, bridgeDown, documentOpen, stale, cadChangedAt } = useWorkspaceData()
  useDocumentTitle(t("bds.tabs.check"), workspace.name, t("bds.list.title"))

  const blocked = p.assigned === 0 ? t("bds.actions.verifyBlocked") : bridgeDown ? t("bds.actions.bridgeDown") : undefined
  // Primary while there is no result or it is outdated; a fresh result needs no new check.
  const primary = !run || !!stale || p.unchecked > 0
  const when = run ? new Date(run.context.started_at).toLocaleString(i18n.language) : "—"
  const ago = cadChangedAt
    ? new Intl.RelativeTimeFormat(i18n.language, { numeric: "auto" }).format(-Math.max(0, Math.round((Date.now() - cadChangedAt) / 60_000)), "minute")
    : ""
  const box = "rounded-md border px-4 py-2 text-sm"

  return (
    <div className="space-y-4">
      <AreaIntro
        title={t("bds.check.title")}
        actions={
          <>
            <Button variant={primary && !blocked ? "default" : "outline"} disabled={!!blocked || actions.verify.isPending} onClick={() => actions.verify.mutate()}>
              <Play /> {actions.verify.isPending ? t("bds.actions.verifying") : t("bds.actions.verify")}
            </Button>
            {blocked && <p className="text-xs text-muted-foreground">{blocked}</p>}
          </>
        }
      >
        {t("bds.check.text")}
      </AreaIntro>

      <p className="text-sm font-medium">
        {run ? t("bds.check.last", { when, passed: p.passed, tolerance: p.tolerance, violated: p.violated }) : t("bds.check.never")}
        {p.open > 0 && (
          <>
            {" · "}
            <Link to="/projects/bds/$ws/assign" params={{ ws: workspace.name }} search={(s) => s} className="underline underline-offset-4">
              {t("bds.check.unassigned", { count: p.open })}
            </Link>
          </>
        )}
      </p>

      <div className="space-y-2" role="status">
        {bridgeDown && (
          <p className={box + " border-warning/40 bg-warning/5"}>{run ? t("bds.banner.noBridge", { time: when }) : t("bds.banner.noBridgeNever")}</p>
        )}
        {!bridgeDown && documentOpen === false && (
          <p className={box + " border-warning/40 bg-warning/5"}>{t("bds.banner.closed", { document: workspace.cad_document })}</p>
        )}
        {stale && !bridgeDown && documentOpen !== false && (
          <p className={box + " border-blue-300 bg-blue-50 text-blue-950 dark:border-blue-800 dark:bg-blue-950 dark:text-blue-50"}>
            {stale === "cad" ? t("bds.banner.cad", { when: ago }) : t("bds.banner.commit")}
          </p>
        )}
        {run && !stale && p.unchecked > 0 && (
          <p className={box + " border-blue-300 bg-blue-50 text-blue-950 dark:border-blue-800 dark:bg-blue-950 dark:text-blue-50"}>
            {t("bds.banner.unchecked", { count: p.unchecked })}
          </p>
        )}
        {!!actions.verify.error && (
          <p className={box + " border-destructive/40 bg-destructive/5 text-destructive"}>
            {t("bds.banner.verifyFailed", { error: describeError(actions.verify.error) })}
          </p>
        )}
        {!!runError && <p className={box + " border-destructive/40 bg-destructive/5 text-destructive"}>{describeError(runError)}</p>}
      </div>

      {rows.length === 0 ? <EmptyNote>{t("bds.table.empty")}</EmptyNote> : <RequirementTable rows={rows} context={table} mode="check" />}
    </div>
  )
}
