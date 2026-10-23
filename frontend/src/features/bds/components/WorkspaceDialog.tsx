import { useQuery, useQueryClient } from "@tanstack/react-query"
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
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { describeError } from "@/features/cad/format"
import { documentsQuery } from "@/features/cad/queries"
import { sysmlProjectsQuery } from "@/features/sysml/queries"

import { bdsKeys, saveWorkspace, type Workspace } from "../queries"

/** Axis conventions a CAD system uses for a box's length, width and height. */
const AXIS_PRESETS = {
  freecad: { length: "X", width: "Y", height: "Z" },
  chili3d: { length: "Y", width: "Z", height: "X" },
} as const
type Preset = keyof typeof AXIS_PRESETS | "custom"

function presetOf(axes: Record<string, string> | undefined): Preset {
  if (!axes) return "freecad"
  for (const [name, preset] of Object.entries(AXIS_PRESETS)) {
    if (axes.length === preset.length && axes.width === preset.width && axes.height === preset.height) return name as Preset
  }
  return "custom"
}

const NONE = "__none__"
const NAME = /^[A-Za-z0-9][A-Za-z0-9_.-]*$/

/** Create a workspace, or change one (``existing``). The SysML project must exist in Flexo. */
export function WorkspaceDialog({ open, onOpenChange, existing, onSaved }: {
  open: boolean
  onOpenChange: (open: boolean) => void
  existing?: Workspace
  onSaved?: (workspace: Workspace) => void
}) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const projects = useQuery({ ...sysmlProjectsQuery, enabled: open })
  const documents = useQuery({ ...documentsQuery, enabled: open, retry: false })
  const [name, setName] = useState(existing?.name ?? "")
  const [project, setProject] = useState(existing?.sysml_project ?? "")
  const [document, setDocument] = useState(existing?.cad_document ?? "")
  const [preset, setPreset] = useState<Preset>(presetOf(existing?.axes))
  const [sheet, setSheet] = useState(existing?.limits_sheet ?? "SysML")
  const [pending, setPending] = useState(false)

  const documentNames = documents.data?.documents.map((d) => d.name) ?? []
  if (document && !documentNames.includes(document)) documentNames.unshift(document)
  const nameValid = NAME.test(name)

  const submit = async () => {
    setPending(true)
    try {
      const axes = preset === "custom" ? existing?.axes : preset === "freecad" ? null : AXIS_PRESETS[preset]
      const saved = await saveWorkspace(name, {
        sysml_project: project,
        cad_document: document,
        axes: axes ? { ...axes } : null,
        limits_sheet: sheet || null,
      })
      await queryClient.invalidateQueries({ queryKey: bdsKeys.all() })
      toast.success(t(existing ? "bds.dialog.saved" : "bds.dialog.created", { name: saved.name }))
      onOpenChange(false)
      onSaved?.(saved)
    } catch (error) {
      toast.error(describeError(error))
    } finally {
      setPending(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{existing ? t("bds.dialog.editTitle", { name: existing.name }) : t("bds.dialog.newTitle")}</DialogTitle>
          <DialogDescription>{t("bds.dialog.description")}</DialogDescription>
        </DialogHeader>

        <form
          className="space-y-4"
          onSubmit={(event) => {
            event.preventDefault()
            void submit()
          }}
        >
          <div className="space-y-1.5">
            <Label htmlFor="bds-name">{t("bds.dialog.name")}</Label>
            <Input id="bds-name" value={name} disabled={!!existing} onChange={(e) => setName(e.target.value)} />
            {name && !nameValid && <p className="text-xs text-destructive">{t("bds.dialog.nameRule")}</p>}
          </div>

          <div className="space-y-1.5">
            <Label>{t("bds.dialog.sysmlProject")}</Label>
            <Select value={project || undefined} onValueChange={setProject}>
              <SelectTrigger className="w-full">
                <SelectValue placeholder={projects.isError ? t("bds.dialog.flexoDown") : t("bds.dialog.choose")} />
              </SelectTrigger>
              <SelectContent>
                {(projects.data ?? []).map((p) => (
                  <SelectItem key={p.id} value={p.name}>
                    {p.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-1.5">
            <Label>{t("bds.dialog.cadDocument")}</Label>
            <Select value={document || NONE} onValueChange={(v) => setDocument(v === NONE ? "" : v)}>
              <SelectTrigger className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={NONE}>{t("bds.dialog.noDocument")}</SelectItem>
                {documentNames.map((doc) => (
                  <SelectItem key={doc} value={doc}>
                    {doc}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <p className="text-xs text-muted-foreground">
              {documents.isError ? t("bds.dialog.bridgeDown") : t("bds.dialog.documentHint")}
            </p>
          </div>

          <details className="text-sm">
            <summary className="cursor-pointer font-medium">{t("bds.dialog.advanced")}</summary>
            <div className="mt-3 space-y-3">
              <div className="space-y-1.5">
                <Label>{t("bds.dialog.axes")}</Label>
                <Select value={preset} onValueChange={(v) => setPreset(v as Preset)}>
                  <SelectTrigger className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="freecad">{t("bds.dialog.axesFreecad")}</SelectItem>
                    <SelectItem value="chili3d">{t("bds.dialog.axesChili3d")}</SelectItem>
                    {existing && presetOf(existing.axes) === "custom" && (
                      <SelectItem value="custom">{t("bds.dialog.axesCustom")}</SelectItem>
                    )}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="bds-sheet">{t("bds.dialog.sheet")}</Label>
                <Input id="bds-sheet" value={sheet} onChange={(e) => setSheet(e.target.value)} />
                <p className="text-xs text-muted-foreground">{t("bds.dialog.sheetHint", { sheet: sheet || "SysML" })}</p>
              </div>
            </div>
          </details>

          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              {t("bds.common.cancel")}
            </Button>
            <Button type="submit" disabled={pending || !nameValid || !project}>
              {existing ? t("bds.dialog.save") : t("bds.dialog.create")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
