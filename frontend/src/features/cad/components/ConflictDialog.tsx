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

/** Ein Konflikt wird sichtbar gemacht -- nie still ueberschrieben. */
export function ConflictDialog({ conflict }: { conflict: Conflict | null }) {
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
              {conflict.objectLabel}.{conflict.prop} wurde inzwischen geändert
            </AlertDialogTitle>
            <AlertDialogDescription>
              Während du bearbeitet hast, hat sich der Wert in FreeCAD geändert. Welcher Wert soll gelten?
            </AlertDialogDescription>
          </AlertDialogHeader>
          <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 rounded-md border p-3 text-sm">
            <dt className="text-muted-foreground">Jetzt in FreeCAD</dt>
            <dd className="font-mono">{conflict.theirs ? formatValue(conflict.theirs.value) : "— (nicht mehr vorhanden)"}</dd>
            <dt className="text-muted-foreground">Deine Eingabe</dt>
            <dd className="font-mono">{conflict.mine}</dd>
          </dl>
          <AlertDialogFooter>
            <AlertDialogCancel onClick={() => conflict.resolve("discard")}>Wert aus FreeCAD übernehmen</AlertDialogCancel>
            <Button variant="destructive" onClick={() => conflict.resolve("overwrite")}>
              Meinen Wert trotzdem setzen
            </Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      )}
    </AlertDialog>
  )
}
