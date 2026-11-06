import { useState } from "react"
import { useTranslation } from "react-i18next"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { describeError } from "@/features/cad/format"

import type { WorkspaceActions } from "../actions"
import type { RequirementRow } from "../logic"
import { updateEntry, type Workspace } from "../queries"
import { formatQuantity, operatorSymbol } from "./bits"

// The tolerance of one assignment -- the one dialog besides choosing a measurement.

export function ToleranceDialog({ row, workspace, actions, onClose }: {
  row: RequirementRow
  workspace: Workspace
  actions: WorkspaceActions
  onClose: () => void
}) {
  const { t, i18n } = useTranslation()
  const [value, setValue] = useState(row.entry?.tolerance != null ? String(row.entry.tolerance) : "")
  const [pending, setPending] = useState(false)
  if (!row.entry || !row.requirement) return null
  const entry = row.entry
  const requirement = row.requirement

  const save = async () => {
    setPending(true)
    try {
      await updateEntry(workspace.name, entry, { tolerance: value.trim() || null })
      toast.success(t("bds.toleranceDialog.saved"))
      actions.changed()
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
          <DialogTitle>{t("bds.toleranceDialog.title", { requirement: row.id })}</DialogTitle>
          <DialogDescription>
            {t("bds.toleranceDialog.text", {
              operator: operatorSymbol(requirement.operator),
              limit: formatQuantity(requirement.limit, i18n.language),
            })}
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-1.5">
          <Label htmlFor="bds-tolerance-edit">{t("bds.measureDialog.tolerance")}</Label>
          <Input
            id="bds-tolerance-edit"
            value={value}
            onChange={(e) => setValue(e.target.value)}
            placeholder={t("bds.measureDialog.tolerancePlaceholder")}
            className="w-56"
          />
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            {t("bds.common.cancel")}
          </Button>
          <Button disabled={pending} onClick={() => void save()}>
            {t("bds.toleranceDialog.save")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
