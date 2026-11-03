import { useQuery } from "@tanstack/react-query"
import { useState } from "react"
import { Trans, useTranslation } from "react-i18next"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Skeleton } from "@/components/ui/skeleton"
import { describeError } from "@/features/cad/format"
import { showInFreeCAD } from "@/features/cad/queries"
import { cn } from "@/lib/utils"

import type { WorkspaceActions } from "../actions"
import { describeMeasurement, measurementOptions, splitReference, type MeasurementOption } from "../logic"
import { bdsKeys, createEntry, type Catalog, type Mapping, type Workspace } from "../queries"
import { formatQuantity, LimitText, measurementWords, operatorSymbol, SanityCheck, SourceTag } from "./bits"
import type { MeasureRequest } from "./RequirementTable"

const DIMENSIONS = ["[length]", "[mass]", "[length] ** 3"]

/**
 * Choose a measurement by hand: 1 the FreeCAD object, 2 what is measured on it (only
 * kinds that give the attribute's unit), 3 a dry run of the checks and the verdict --
 * before anything is written.
 */
export function MeasurementDialog({ request, workspace, commit, catalog, mapping, actions, onClose }: {
  request: MeasureRequest
  workspace: Workspace
  commit?: string
  catalog: Catalog
  mapping?: Mapping
  actions: WorkspaceActions
  onClose: () => void
}) {
  const { t, i18n } = useTranslation()
  const { part, attribute, requirement, replace } = request
  const dimension = catalog.sysml.find((p) => p.name === part)?.attributes.find((a) => a.name === attribute)?.dimension ?? null
  const dimensionWord = t(`bds.measureDialog.dimension.${DIMENSIONS.includes(dimension ?? "") ? dimension : "other"}` as never)

  // A part stands for one CAD object: once it has other assignments, they decide.
  const partEntry = mapping?.parts.find((p) => p.sysml_part === part)
  const others = (mapping?.attributes ?? []).filter(
    (e) => e.sysml_part === part && !(replace && e.attribute === replace.attribute && e.requirement === replace.requirement),
  )
  const locked = partEntry && others.length > 0 ? partEntry.cad_object : undefined
  const targets = catalog.cad.filter((target) => !locked || target.reference === locked)

  const [reference, setReference] = useState<string | undefined>(locked ?? (replace ? partEntry?.cad_object : undefined))
  const [option, setOption] = useState<MeasurementOption | undefined>(
    replace ? { method: replace.method, args: replace.args ?? {}, source: "geometry" } : undefined,
  )
  const [tolerance, setTolerance] = useState("")
  const [pending, setPending] = useState(false)
  const target = targets.find((x) => x.reference === reference)
  const options = target ? measurementOptions(target, dimension) : []

  const fields = reference && option
    ? {
        sysml_part: part,
        attribute,
        cad_object: reference,
        method: option.method,
        args: option.args,
        requirement: requirement?.requirement ?? "",
        // A replacement keeps its tolerance (changed in its own dialog).
        tolerance: replace ? replace.tolerance : tolerance.trim() || null,
        replaces: replace ? replace.requirement : undefined,
      }
    : undefined
  const unchanged = !!replace && !!fields && fields.cad_object === partEntry?.cad_object && fields.method === replace.method &&
    JSON.stringify(fields.args) === JSON.stringify(replace.args ?? {})

  // The dry run -- nothing to check when the choice is the entry as it already is.
  const check = useQuery({
    queryKey: [...bdsKeys.workspace(workspace.name), "dryRun", fields, commit],
    queryFn: ({ signal }) => createEntry(workspace.name, { ...fields!, dry_run: true, commit }, signal),
    enabled: !!fields && !unchanged,
    retry: false,
    staleTime: 10_000,
  })
  const invalid = check.data?.check.verdict === "invalid"

  const submit = async () => {
    if (!fields) return
    setPending(true)
    try {
      await createEntry(workspace.name, { ...fields, commit })
      const { text } = describeMeasurement(option!.method, option!.args, workspace.axes, target, attribute)
      toast.success(t("bds.measureDialog.saved", { label: `${requirement?.requirement ?? part + "." + attribute} ← ${target?.name ?? reference} · ${measurementWords(text, t as never)}` }))
      actions.changed()
      onClose()
    } catch (error) {
      toast.error(describeError(error))
      actions.changed()
    } finally {
      setPending(false)
    }
  }

  const show = async (ref: string) => {
    const { doc, name } = splitReference(ref)
    if (!name) return
    try {
      await showInFreeCAD(doc, name)
    } catch (error) {
      toast.error(describeError(error))
    }
  }

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>
            {requirement
              ? t("bds.measureDialog.title", { requirement: requirement.requirement })
              : t("bds.measureDialog.titleFree", { part, attribute })}
          </DialogTitle>
          <DialogDescription>
            <Trans
              i18nKey="bds.measureDialog.wanted"
              values={{
                part,
                attribute,
                dimension: dimensionWord,
                limit: requirement
                  ? t("bds.measureDialog.limit", {
                      operator: operatorSymbol(requirement.operator),
                      value: formatQuantity(requirement.limit, i18n.language),
                    })
                  : "",
              }}
              components={{ code: <code className="rounded bg-muted px-1 py-0.5" />, strong: <strong /> }}
            />
          </DialogDescription>
        </DialogHeader>

        <fieldset className="space-y-2">
          <legend className="mb-2 text-sm font-semibold">{t("bds.measureDialog.where")}</legend>
          {locked && (
            <p className="text-xs text-muted-foreground">
              {t("bds.measureDialog.locked", { part, object: targets[0]?.name ?? locked })}
            </p>
          )}
          {targets.length === 0 && <p className="text-sm text-muted-foreground">{t("bds.measureDialog.noObjects")}</p>}
          <div className="space-y-1.5">
            {targets.map((x) => (
              <label
                key={x.reference}
                className={cn(
                  "flex cursor-pointer items-center gap-3 rounded-md border px-3 py-2 text-sm",
                  reference === x.reference ? "border-foreground ring-1 ring-foreground" : "hover:bg-accent/50",
                  x.depth > 0 && "ml-6",
                  x.error && "opacity-70",
                )}
              >
                <input
                  type="radio"
                  name="bds-object"
                  className="accent-foreground"
                  checked={reference === x.reference}
                  onChange={() => {
                    setReference(x.reference)
                    setOption(undefined)
                  }}
                />
                <span className="min-w-0 flex-1">
                  <strong className="font-medium">{x.name}</strong>{" "}
                  <span className="text-muted-foreground">
                    · {t(x.kind === "assembly" ? "bds.models.assembly" : "bds.models.part")}
                    {x.material ? " · " + x.material : ""}
                  </span>
                  {x.error && <span className="block text-xs text-warning">{t("bds.measureDialog.objectError", { reason: x.error })}</span>}
                </span>
                {x.size && (
                  <span className="text-xs text-muted-foreground tabular-nums">
                    {x.size.map((v) => formatQuantity({ value: v, unit: "", text: "" }, i18n.language)).join(" × ")} mm
                  </span>
                )}
                {splitReference(x.reference).name && (
                  <button
                    type="button"
                    className="text-xs underline underline-offset-2"
                    onClick={(event) => (event.preventDefault(), void show(x.reference))}
                  >
                    {t("bds.measureDialog.showInFreecad")}
                  </button>
                )}
              </label>
            ))}
          </div>
        </fieldset>

        {target && (
          <fieldset className="space-y-2">
            <legend className="mb-2 text-sm font-semibold">
              {t("bds.measureDialog.what")}{" "}
              {dimension && <span className="font-normal text-muted-foreground">({t("bds.measureDialog.whatHint", { dimension: dimensionWord })})</span>}
            </legend>
            {options.length === 0 && <p className="text-sm text-muted-foreground">{t("bds.measureDialog.none")}</p>}
            <div className="space-y-1.5">
              {options.map((o) => {
                const key = o.method + JSON.stringify(o.args)
                const selected = !!option && option.method === o.method && JSON.stringify(option.args) === JSON.stringify(o.args)
                const { text } = describeMeasurement(o.method, o.args, workspace.axes, target, attribute)
                return (
                  <label
                    key={key}
                    className={cn(
                      "flex cursor-pointer items-center gap-3 rounded-md border px-3 py-2 text-sm",
                      selected ? "border-foreground ring-1 ring-foreground" : "hover:bg-accent/50",
                    )}
                  >
                    <input type="radio" name="bds-measure" className="accent-foreground" checked={selected} onChange={() => setOption(o)} />
                    <span className="flex min-w-0 flex-1 flex-wrap items-center gap-2">
                      {measurementWords(text, t as never)}
                      <SourceTag source={o.source} />
                    </span>
                    {o.value && <span className="font-medium tabular-nums">{o.value}</span>}
                  </label>
                )
              })}
            </div>
          </fieldset>
        )}

        {requirement && !replace && (
          <div className="space-y-1.5">
            <Label htmlFor="bds-tolerance">{t("bds.measureDialog.tolerance")}</Label>
            <Input
              id="bds-tolerance"
              value={tolerance}
              onChange={(e) => setTolerance(e.target.value)}
              placeholder={t("bds.measureDialog.tolerancePlaceholder")}
              className="w-56"
            />
            <p className="text-xs text-muted-foreground">{t("bds.measureDialog.toleranceHint")}</p>
          </div>
        )}

        <section className="space-y-2 rounded-md border bg-muted/30 p-3" aria-live="polite">
          <h3 className="text-sm font-semibold">{t("bds.measureDialog.check")}</h3>
          {!fields ? (
            <p className="text-sm text-muted-foreground">{t("bds.measureDialog.pick")}</p>
          ) : unchanged ? null : check.isPending ? (
            <Skeleton className="h-16" />
          ) : check.isError ? (
            <p className="text-sm text-destructive">{describeError(check.error)}</p>
          ) : check.data ? (
            <>
              {check.data.check.measured && (
                <p className="text-sm">
                  <strong className="tabular-nums">{formatQuantity(check.data.check.measured, i18n.language)}</strong>
                  {check.data.preview && requirement && (
                    <>
                      {" · "}
                      {t("bds.proposal.effect", {
                        status: t(`bds.verdict.${check.data.preview.status}`),
                        measured: formatQuantity(check.data.preview.measured, i18n.language),
                        operator: operatorSymbol(check.data.preview.operator),
                        limit: formatQuantity(check.data.preview.limit, i18n.language),
                      })}
                    </>
                  )}
                </p>
              )}
              <SanityCheck gates={check.data.check.gates} detailed />
            </>
          ) : null}
          {requirement && <span className="sr-only"><LimitText requirement={requirement} /></span>}
        </section>

        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            {t("bds.common.cancel")}
          </Button>
          <Button disabled={!fields || pending || invalid || unchanged || (check.isPending && !!fields)} onClick={() => void submit()}>
            {t("bds.measureDialog.submit")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
