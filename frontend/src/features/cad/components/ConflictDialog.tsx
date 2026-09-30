import { useTranslation } from "react-i18next"

import {
  AlertDialog,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog"
import { Button } from "@/components/ui/button"
import type { Conflict } from "../editing"
import { formatValue } from "../format"

/** A conflict is made visible -- never silently overwritten. */
export function ConflictDialog({ conflict }: { conflict: Conflict | null }) {
  const { t } = useTranslation()
  return (
    <AlertDialog
      open={conflict !== null}
      onOpenChange={(open) => {
        if (!open) conflict?.resolve("discard")
      }}
    >
      {conflict && (
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              {t("conflict.title", { object: conflict.objectLabel, prop: conflict.prop })}
            </AlertDialogTitle>
            <AlertDialogDescription>
              {t("conflict.description")}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 rounded-md border p-3 text-sm">
            <dt className="text-muted-foreground">{t("conflict.theirs")}</dt>
            <dd className="font-mono">{conflict.theirs ? formatValue(conflict.theirs.value) : t("conflict.gone")}</dd>
            <dt className="text-muted-foreground">{t("conflict.mine")}</dt>
            <dd className="font-mono">{conflict.mine}</dd>
          </dl>
          <AlertDialogFooter>
            <AlertDialogCancel onClick={() => conflict.resolve("discard")}>{t("conflict.keepTheirs")}</AlertDialogCancel>
            <Button variant="destructive" onClick={() => conflict.resolve("overwrite")}>
              {t("conflict.overwrite")}
            </Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      )}
    </AlertDialog>
  )
}
