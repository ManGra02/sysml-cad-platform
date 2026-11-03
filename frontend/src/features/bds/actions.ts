import { useMutation, useQueryClient } from "@tanstack/react-query"
import { useTranslation } from "react-i18next"
import { toast } from "sonner"

import { describeError } from "@/features/cad/format"

import {
  bdsKeys,
  confirmProposal,
  createEntry,
  deleteEntry,
  invalidateMapping,
  rejectProposal,
  runVerify,
  type AttributeMapping,
  type Run,
} from "./queries"

/**
 * The writes of the workspace page. Every change to the assignments re-reads what it
 * touched and runs the check again -- the table always shows the consequence of a decision.
 */
export function useWorkspaceActions(ws: string, commit: string | undefined, onChecked?: (run: Run) => void) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()

  const verify = useMutation({
    mutationFn: () => runVerify(ws, { commit }),
    onSuccess: (run) => {
      queryClient.setQueryData(bdsKeys.lastRun(ws), run)
      void queryClient.invalidateQueries({ queryKey: bdsKeys.workspaces(), exact: true })
      onChecked?.(run)
    },
  })

  const changed = () => {
    invalidateMapping(queryClient, ws)
    verify.mutate()
  }

  const accept = async (proposalId: string, requirement: string | undefined, label: string) => {
    try {
      await confirmProposal(ws, proposalId, { requirement: requirement || undefined, commit })
      toast.success(t("bds.proposal.accepted", { requirement: label }))
      changed()
    } catch (error) {
      toast.error(describeError(error))
      invalidateMapping(queryClient, ws)
    }
  }

  const discard = async (proposalId: string) => {
    try {
      await rejectProposal(ws, proposalId, "")
      toast(t("bds.proposal.discarded"))
      invalidateMapping(queryClient, ws)
    } catch (error) {
      toast.error(describeError(error))
    }
  }

  /** Release an assignment; the toast offers to put it back exactly as it was. */
  const release = async (entry: AttributeMapping, cadObject: string | undefined) => {
    try {
      await deleteEntry(ws, entry)
      changed()
      toast(t("bds.row.released"), {
        action: cadObject
          ? {
              label: t("bds.row.undo"),
              onClick: () =>
                void createEntry(ws, {
                  sysml_part: entry.sysml_part,
                  attribute: entry.attribute,
                  cad_object: cadObject,
                  method: entry.method,
                  args: entry.args,
                  requirement: entry.requirement,
                  tolerance: entry.tolerance,
                  commit,
                }).then(
                  () => {
                    toast.success(t("bds.row.restored"))
                    changed()
                  },
                  (error) => toast.error(describeError(error)),
                ),
            }
          : undefined,
      })
    } catch (error) {
      toast.error(describeError(error))
    }
  }

  return { verify, changed, accept, discard, release }
}

export type WorkspaceActions = ReturnType<typeof useWorkspaceActions>
