import { useQuery, useQueryClient } from "@tanstack/react-query"
import { useState } from "react"
import { Trans, useTranslation } from "react-i18next"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { describeError } from "@/features/cad/format"
import { useDocumentTitle } from "@/lib/useDocumentTitle"

import { AreaIntro } from "../components/Sections"
import { useWorkspaceData } from "../context"
import { applySync, bdsKeys, syncPlanQuery } from "../queries"

/**
 * Optional, SysML -> CAD: requirement limits into the FreeCAD sheet the sync owns, as
 * reference values. The dry run first, always; the model only changes where a designer
 * uses them in a formula.
 */
export function LimitsView() {
  const { t } = useTranslation()
  const { workspace, commit, bridgeDown, documentOpen } = useWorkspaceData()
  useDocumentTitle(t("bds.tabs.limits"), workspace.name, t("bds.list.title"))
  const queryClient = useQueryClient()
  const plan = useQuery(syncPlanQuery(workspace.name, commit))
  const [pending, setPending] = useState(false)
  const sheet = workspace.limits_sheet
  const changes = plan.data?.documents.flatMap((d) => d.changes.map((c) => ({ ...c, document: d.document }))) ?? []
  const overwritten = changes.filter((c) => c.old !== null).length

  const apply = async () => {
    setPending(true)
    try {
      const result = await applySync(workspace.name, { commit })
      if (result.failures) toast.error(t("bds.limits.failed", { count: result.failures }))
      else toast.success(t("bds.limits.applied", { count: result.changes, sheet }))
      void queryClient.invalidateQueries({ queryKey: bdsKeys.syncPlan(workspace.name, commit) })
    } catch (error) {
      toast.error(describeError(error))
    } finally {
      setPending(false)
    }
  }

  return (
    <div className="max-w-3xl space-y-4">
      <AreaIntro
        title={t("bds.limits.title")}
        badge={t("bds.tabs.optional")}
        actions={
          changes.length > 0 && (
            <Button disabled={pending || bridgeDown} onClick={() => void apply()}>
              {t("bds.limits.apply", { count: changes.length })}
            </Button>
          )
        }
      >
        <Trans
          i18nKey="bds.limits.text"
          values={{ sheet, document: workspace.cad_document }}
          components={{ strong: <strong />, code: <code className="rounded bg-muted px-1 py-0.5" /> }}
        />
      </AreaIntro>

      {bridgeDown && <p className="rounded-md border border-warning/40 bg-warning/5 px-4 py-2 text-sm">{t("bds.limits.noBridge")}</p>}
      {!bridgeDown && documentOpen === false && (
        <p className="rounded-md border border-warning/40 bg-warning/5 px-4 py-2 text-sm">{t("bds.banner.closed", { document: workspace.cad_document })}</p>
      )}
      {plan.isPending && <Skeleton className="h-32" />}
      {plan.isError && <p className="text-sm text-destructive">{describeError(plan.error)}</p>}
      {plan.data && (
        <div className="space-y-3">
          {/* A closed document or a missing bridge is said above, in words; other errors as they come. */}
          {!bridgeDown && documentOpen !== false && plan.data.documents.map((doc) =>
            doc.error ? (
              <p key={doc.document} className="text-sm text-destructive">
                {t("bds.limits.notWritable", { error: doc.error })}
              </p>
            ) : null,
          )}
          {changes.length > 0 ? (
            <div className="overflow-x-auto rounded-md border">
              <table className="w-full text-sm">
                <thead className="bg-muted/40 text-left text-muted-foreground">
                  <tr>
                    <th className="px-3 py-2 font-medium">{t("bds.limits.name")}</th>
                    <th className="px-3 py-2 font-medium">{t("bds.limits.before")}</th>
                    <th className="px-3 py-2 font-medium">{t("bds.limits.after")}</th>
                  </tr>
                </thead>
                <tbody>
                  {changes.map((c) => (
                    <tr key={c.document + c.alias} className="border-t">
                      <td className="px-3 py-2">
                        <code className="text-xs">{c.alias}</code>
                      </td>
                      <td className="px-3 py-2 text-muted-foreground">{c.old?.text ?? "–"}</td>
                      <td className="px-3 py-2 font-medium">
                        {c.new.text} <span className="text-xs font-normal text-muted-foreground">{c.old ? t("bds.limits.changed") : t("bds.limits.new")}</span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : plan.data.documents.length > 0 && !plan.data.documents.some((d) => d.error) ? (
            <p className="text-sm text-muted-foreground">{t("bds.limits.upToDate", { sheet })}</p>
          ) : (
            plan.data.documents.length === 0 && <p className="text-sm text-muted-foreground">{t("bds.limits.nothing")}</p>
          )}
          {overwritten > 0 && <p className="text-sm text-warning">{t("bds.limits.overwrite", { count: overwritten, sheet })}</p>}
          {plan.data.skipped.length > 0 && (
            <div className="text-sm">
              <strong>{t("bds.limits.skipped")}</strong>
              <ul className="mt-1 list-disc pl-5 text-muted-foreground">
                {plan.data.skipped.map((s) => (
                  <li key={s.requirement}>
                    <strong className="font-medium text-foreground">{s.requirement}</strong> – {s.reason}
                  </li>
                ))}
              </ul>
            </div>
          )}
          {plan.data.held_back.length > 0 && (
            <div className="text-sm">
              <strong>{t("bds.limits.heldBack")}</strong>
              <ul className="mt-1 list-disc pl-5 text-muted-foreground">
                {plan.data.held_back.map((note) => (
                  <li key={note}>{note}</li>
                ))}
              </ul>
            </div>
          )}
          {changes.length > 0 && <p className="text-xs text-muted-foreground">{t("bds.limits.undo")}</p>}
        </div>
      )}

    </div>
  )
}
