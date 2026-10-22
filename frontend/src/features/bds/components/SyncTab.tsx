import { useQuery, useQueryClient } from "@tanstack/react-query"
import { RefreshCw } from "lucide-react"
import { useState } from "react"
import { Trans, useTranslation } from "react-i18next"
import { toast } from "sonner"

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { describeError } from "@/features/cad/format"
import { cn } from "@/lib/utils"

import { applySync, bdsKeys, syncPlanQuery, type SyncResult } from "../queries"
import type { TabProps } from "../WorkspacePage"
import { EmptyNote } from "./bits"

/** Requirement limits into the FreeCAD sheet the sync owns: always the dry run first. */
export function SyncTab({ workspace, commit }: TabProps) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const plan = useQuery(syncPlanQuery(workspace.name, commit))
  const [confirming, setConfirming] = useState(false)
  const [pending, setPending] = useState(false)
  const sheet = workspace.limits_sheet

  const apply = async () => {
    setPending(true)
    try {
      const result = await applySync(workspace.name, { commit })
      if (result.failures) toast.error(t("bds.sync.failed", { count: result.failures }))
      else toast.success(t("bds.sync.applied", { count: result.changes }), { description: t("bds.sync.undoHint") })
      void queryClient.invalidateQueries({ queryKey: bdsKeys.syncPlan(workspace.name, commit) })
    } catch (error) {
      toast.error(describeError(error))
    } finally {
      setPending(false)
      setConfirming(false)
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-start gap-4">
        <div className="min-w-0 flex-1">
          <h2 className="mb-1 font-semibold">{t("bds.sync.title")}</h2>
          <p className="text-sm text-muted-foreground">
            <Trans
              i18nKey="bds.sync.hint"
              values={{ sheet }}
              components={{ strong: <strong />, code: <code className="rounded bg-muted px-1 py-0.5" /> }}
            />
          </p>
        </div>
        <Button variant="outline" size="sm" disabled={plan.isFetching} onClick={() => void plan.refetch()}>
          <RefreshCw className={cn(plan.isFetching && "animate-spin")} /> {t("bds.sync.refresh")}
        </Button>
      </div>

      {plan.isPending && <Skeleton className="h-40" />}
      {plan.isError && <p className="text-sm text-destructive">{describeError(plan.error)}</p>}
      {plan.data && <Plan plan={plan.data} sheet={sheet} />}

      {plan.data && plan.data.changes > 0 && (
        <div className="flex flex-wrap items-center gap-3">
          <span className="text-xs text-muted-foreground">{t("bds.sync.applyHint")}</span>
          <Button className="ml-auto" onClick={() => setConfirming(true)}>
            {t("bds.sync.apply", { count: plan.data.changes })}
          </Button>
        </div>
      )}

      <AlertDialog open={confirming} onOpenChange={setConfirming}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              {t("bds.sync.confirmTitle", { count: plan.data?.changes ?? 0, document: workspace.cad_document })}
            </AlertDialogTitle>
            <AlertDialogDescription>{t("bds.sync.confirmText", { sheet })}</AlertDialogDescription>
          </AlertDialogHeader>
          <ul className="list-disc pl-5 text-sm">
            {plan.data?.documents.flatMap((d) =>
              d.changes.map((c) => (
                <li key={d.document + c.alias}>
                  {sheet}.{c.alias} = {c.new.text}
                </li>
              )),
            )}
          </ul>
          <AlertDialogFooter>
            <AlertDialogCancel>{t("bds.common.cancel")}</AlertDialogCancel>
            <AlertDialogAction disabled={pending} onClick={(event) => (event.preventDefault(), void apply())}>
              {t("bds.sync.write")}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}

function Plan({ plan, sheet }: { plan: SyncResult; sheet: string }) {
  const { t } = useTranslation()
  if (plan.documents.length === 0 && plan.skipped.length === 0) return <EmptyNote>{t("bds.sync.nothing")}</EmptyNote>
  return (
    <div className="space-y-3">
      {plan.documents.map((doc) => (
        <section key={doc.document} className="overflow-hidden rounded-lg border">
          <div className="flex flex-wrap items-center gap-2 border-b bg-muted/40 px-4 py-2 text-sm">
            <strong>{doc.document}</strong>
            <span className="ml-auto">
              {doc.error ? t("bds.sync.notWritable") : t("bds.sync.changes", { count: doc.changes.length })}
            </span>
          </div>
          {doc.error ? (
            <p className="px-4 py-3 text-sm text-destructive">{doc.error}</p>
          ) : doc.changes.length === 0 ? (
            <p className="px-4 py-3 text-sm text-muted-foreground">{t("bds.sync.upToDate", { sheet })}</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[36rem] text-sm">
                <thead className="text-left text-muted-foreground">
                  <tr>
                    <th className="px-4 py-2 font-medium">{t("bds.sync.columns.alias")}</th>
                    <th className="px-2 py-2 font-medium">{t("bds.sync.columns.now")}</th>
                    <th className="px-4 py-2 font-medium">{t("bds.sync.columns.becomes")}</th>
                  </tr>
                </thead>
                <tbody>
                  {doc.changes.map((change) => (
                    <tr key={change.alias} className="border-t">
                      <td className="px-4 py-2">
                        <code>
                          {sheet}.{change.alias}
                        </code>
                      </td>
                      <td className="px-2 py-2 text-muted-foreground">{change.old?.text ?? t("bds.sync.new")}</td>
                      <td className="px-4 py-2 font-medium">{change.new.text}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      ))}

      {plan.held_back.length > 0 && (
        <section className="rounded-lg border border-warning/40 bg-warning/5 px-4 py-3 text-sm">
          <strong>{t("bds.sync.heldBack", { count: plan.held_back.length })}</strong>
          <ul className="mt-1 list-disc pl-5 text-muted-foreground">
            {plan.held_back.map((note) => (
              <li key={note}>{note}</li>
            ))}
          </ul>
        </section>
      )}
      {plan.skipped.length > 0 && (
        <section className="rounded-lg border px-4 py-3 text-sm">
          <strong>{t("bds.sync.skipped", { count: plan.skipped.length })}</strong>
          <ul className="mt-1 list-disc pl-5 text-muted-foreground">
            {plan.skipped.map((s) => (
              <li key={s.requirement}>
                {s.requirement}: {s.reason}
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  )
}
