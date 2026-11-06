import { useTranslation } from "react-i18next"
import { toast } from "sonner"

import { describeError } from "@/features/cad/format"
import { showInFreeCAD } from "@/features/cad/queries"
import { useDocumentTitle } from "@/lib/useDocumentTitle"

import { formatQuantity, formatValue } from "../components/bits"
import { AreaIntro } from "../components/Sections"
import { useWorkspaceData } from "../context"
import { leaf, splitReference } from "../logic"

/** Both models as the platform reads them -- for reference only. */
export function ModelsView() {
  const { t, i18n } = useTranslation()
  const { workspace, catalog } = useWorkspaceData()
  useDocumentTitle(t("bds.tabs.models"), workspace.name, t("bds.list.title"))
  const constrainedBy = (part: string, attribute: string) =>
    catalog.requirements.filter((r) => leaf(r.subject) === part && r.attribute === attribute).map((r) => r.requirement)
  const show = async (reference: string) => {
    const { doc, name } = splitReference(reference)
    if (!name) return
    try {
      await showInFreeCAD(doc, name)
    } catch (error) {
      toast.error(describeError(error))
    }
  }
  const sheetValues = new Map<string, string>()
  for (const target of catalog.cad) for (const name of target.sheet_parameters) sheetValues.set(name, target.parameters[name])

  return (
    <div className="space-y-4">
      <AreaIntro title={t("bds.models.title")}>{t("bds.models.hint")}</AreaIntro>

      <div className="flex flex-wrap items-start gap-4">
        <section className="min-w-0 flex-[1_1_22rem] overflow-hidden rounded-lg border">
          <h3 className="border-b bg-muted/40 px-4 py-2 text-sm font-semibold">
            {t("bds.models.sysml", { project: workspace.sysml_project, count: catalog.sysml.length })}
          </h3>
          {catalog.sysml.length === 0 && <p className="p-4 text-sm text-muted-foreground">{t("bds.models.noParts")}</p>}
          <ul className="divide-y">
            {catalog.sysml.map((part) => (
              <li key={part.element_id} className="space-y-1.5 px-4 py-3 text-sm">
                <div>
                  <strong>{part.name}</strong>{" "}
                  <span className="text-muted-foreground">
                    : {part.definition || "?"}
                    {part.container ? " · " + t("bds.models.partOf", { container: part.container }) : ""}
                  </span>
                </div>
                <ul className="space-y-0.5">
                  {part.attributes.map((a) => {
                    const requirements = constrainedBy(part.name, a.name)
                    return (
                      <li key={a.element_id} className="grid grid-cols-[minmax(0,9rem)_minmax(0,1fr)_auto] gap-2 text-xs">
                        <span className="truncate">{a.name}</span>
                        <span className="text-muted-foreground">
                          {a.dimension
                            ? t(`bds.measureDialog.dimension.${["[length]", "[mass]", "[length] ** 3"].includes(a.dimension) ? a.dimension : "other"}` as never)
                            : t("bds.models.unknownDimension")}
                        </span>
                        <span className={requirements.length ? "font-medium" : "text-muted-foreground"}>
                          {requirements.length ? requirements.join(", ") : t("bds.models.noRequirement")}
                        </span>
                      </li>
                    )
                  })}
                </ul>
              </li>
            ))}
          </ul>
          {catalog.not_extracted.length > 0 && (
            <div className="border-t px-4 py-3 text-xs text-muted-foreground">
              <strong className="text-foreground">{t("bds.models.notExtracted", { count: catalog.not_extracted.length })}</strong>
              <ul className="mt-1 list-disc pl-4">
                {catalog.not_extracted.map((r) => (
                  <li key={r}>{r}</li>
                ))}
              </ul>
            </div>
          )}
        </section>

        <section className="min-w-0 flex-[1_1_22rem] overflow-hidden rounded-lg border">
          <h3 className="border-b bg-muted/40 px-4 py-2 text-sm font-semibold">
            {t("bds.models.cad", { document: workspace.cad_document || "—", count: catalog.cad.length })}
          </h3>
          {catalog.cad.length === 0 && <p className="p-4 text-sm text-muted-foreground">{t("bds.models.noTargets")}</p>}
          <ul className="divide-y">
            {catalog.cad.map((x) => {
              const features = Object.entries(x.parameters).filter(([name]) => !x.sheet_parameters.includes(name))
              const children = catalog.cad.filter((c) => c.container === x.reference).map((c) => c.name)
              return (
                <li key={x.reference} className="space-y-1.5 px-4 py-3 text-sm" style={{ paddingLeft: `${1 + x.depth * 1.25}rem` }}>
                  <div className="flex flex-wrap items-baseline gap-2">
                    <strong>{x.name}</strong>
                    <span className="text-muted-foreground">
                      {t(x.kind === "assembly" ? "bds.models.assembly" : "bds.models.part")}
                      {x.material ? " · " + x.material : x.kind === "part" ? " · " + t("bds.models.noMaterial") : ""}
                    </span>
                    {splitReference(x.reference).name && (
                      <button type="button" className="ml-auto text-xs underline underline-offset-2" onClick={() => void show(x.reference)}>
                        {t("bds.row.showInFreecad")}
                      </button>
                    )}
                  </div>
                  {children.length > 0 && <p className="text-xs text-muted-foreground">{t("bds.models.contains", { children: children.join(", ") })}</p>}
                  {x.error && <p className="text-xs text-warning">{t("bds.models.notMeasurable", { reason: x.error })}</p>}
                  <dl className="grid grid-cols-3 gap-2 text-xs">
                    <div>
                      <dt className="text-muted-foreground">{t("bds.models.size")}</dt>
                      <dd className="tabular-nums">{x.size ? x.size.map((v) => formatValue(v, "", i18n.language)).join(" × ") + " mm" : "–"}</dd>
                    </div>
                    <div>
                      <dt className="text-muted-foreground">{t("bds.models.mass")}</dt>
                      <dd className="tabular-nums">{formatQuantity(x.mass, i18n.language)}</dd>
                    </div>
                    <div>
                      <dt className="text-muted-foreground">{t("bds.models.cylinders")}</dt>
                      <dd>
                        {x.cylinders.length
                            ? x.cylinders
                                .map((c) => t(c.kind === "hole" ? "bds.models.hole" : "bds.models.boss", { radius: formatValue(c.radius, "", i18n.language) }))
                                .join(", ")
                            : "–"}
                      </dd>
                    </div>
                  </dl>
                  {features.length > 0 && (
                    <details className="text-xs text-muted-foreground">
                      <summary className="cursor-pointer">{t("bds.models.featureValues", { count: features.length })}</summary>
                      <p className="mt-1">{features.map(([name, value]) => `${name} = ${value}`).join(" · ")}</p>
                    </details>
                  )}
                </li>
              )
            })}
          </ul>
          {sheetValues.size > 0 && (
            <div className="space-y-1 border-t px-4 py-3 text-sm">
              <strong>{t("bds.models.sheetValues")}</strong>
              <dl className="grid grid-cols-1 gap-x-6 gap-y-0.5 text-xs sm:grid-cols-2">
                {[...sheetValues].sort().map(([name, value]) => (
                  <div key={name} className="flex justify-between gap-2">
                    <dt>{name}</dt>
                    <dd className="tabular-nums">{value}</dd>
                  </div>
                ))}
              </dl>
            </div>
          )}
        </section>
      </div>
      <p className="text-xs text-muted-foreground">
        {t("bds.models.axes", { length: workspace.axes.length, width: workspace.axes.width, height: workspace.axes.height })}
      </p>
    </div>
  )
}
