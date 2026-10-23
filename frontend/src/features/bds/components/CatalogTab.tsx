import { useQuery } from "@tanstack/react-query"
import { Fragment, useState } from "react"
import { useTranslation } from "react-i18next"
import { toast } from "sonner"

import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { Switch } from "@/components/ui/switch"
import { describeError } from "@/features/cad/format"
import { showInFreeCAD } from "@/features/cad/queries"
import { cn } from "@/lib/utils"

import { attributeState, requirementsOf, type AttributeState } from "../logic"
import { catalogQuery, mappingQuery, proposalsQuery, type CadTarget } from "../queries"
import type { TabProps } from "../WorkspacePage"

/** Both sides next to each other -- exactly what a proposer sees, plus where the mapping stands. */
export function CatalogTab({ workspace, commit, onTab }: TabProps) {
  const { t } = useTranslation()
  const catalog = useQuery(catalogQuery(workspace.name, commit))
  const mapping = useQuery(mappingQuery(workspace.name))
  const proposals = useQuery(proposalsQuery(workspace.name, commit, false))
  const [filter, setFilter] = useState("")
  const [openOnly, setOpenOnly] = useState(false)

  if (catalog.isPending) return <Skeleton className="h-64" />
  if (catalog.isError) return <p className="text-sm text-destructive">{describeError(catalog.error)}</p>

  const needle = filter.trim().toLowerCase()
  const parts = catalog.data.sysml
    .map((part) => ({
      part,
      attributes: part.attributes
        .map((a) => ({ attribute: a, state: attributeState(mapping.data, proposals.data, part.name, a.name) }))
        .filter(({ attribute, state }) =>
          (!openOnly || state.state === "open") &&
          (!needle || (part.name + "." + attribute.name).toLowerCase().includes(needle)),
        ),
    }))
    .filter(({ attributes }) => attributes.length > 0)
  const targets = catalog.data.cad.filter(
    (target) => !needle || (target.name + " " + target.reference).toLowerCase().includes(needle),
  )
  const axes = catalog.data.axes

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <p className="min-w-0 flex-1 text-sm text-muted-foreground">{t("bds.catalog.hint")}</p>
        <label className="flex items-center gap-2 text-sm">
          <Switch checked={openOnly} onCheckedChange={setOpenOnly} /> {t("bds.catalog.openOnly")}
        </label>
        <Input
          aria-label={t("bds.catalog.filter")}
          placeholder={t("bds.catalog.filter")}
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          className="h-8 w-52"
        />
      </div>

      {catalog.data.not_extracted.length > 0 && (
        <div className="rounded-md border border-warning/40 bg-warning/5 px-4 py-2 text-sm">
          <strong>{t("bds.catalog.notExtracted", { count: catalog.data.not_extracted.length })}</strong>
          <ul className="list-disc pl-5 text-muted-foreground">
            {catalog.data.not_extracted.map((reason) => (
              <li key={reason}>{reason}</li>
            ))}
          </ul>
        </div>
      )}

      <div className="flex flex-wrap items-start gap-4">
        <section className="min-w-0 flex-[1_1_28rem] overflow-hidden rounded-lg border">
          <h2 className="border-b bg-muted/40 px-4 py-2 text-sm font-semibold">
            {t("bds.catalog.sysmlTitle", { project: workspace.sysml_project, count: catalog.data.sysml.length })}
          </h2>
          {catalog.data.sysml.length === 0 ? (
            <p className="p-4 text-sm text-muted-foreground">{t("bds.catalog.noParts")}</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <tbody>
                  {parts.map(({ part, attributes }) => (
                    <Fragment key={part.element_id}>
                      <tr className="border-t bg-muted/30 first:border-t-0">
                        <td colSpan={3} className="px-4 py-2">
                          <span className="font-semibold">{part.name}</span>{" "}
                          <span className="text-muted-foreground">
                            : {part.definition || "?"}
                            {part.container ? " · " + t("bds.catalog.inside", { container: part.container }) : ""}
                          </span>
                          <span className="ml-2 inline-flex flex-wrap gap-1">
                            {requirementsOf(catalog.data.requirements, part.name).map((r) => (
                              <span key={r.requirement} className="rounded bg-muted px-1.5 text-xs" title={r.text}>
                                {r.requirement} {r.operator} {r.limit.text}
                              </span>
                            ))}
                          </span>
                        </td>
                      </tr>
                      {attributes.map(({ attribute, state }) => (
                        <tr key={attribute.element_id} className="border-t">
                          <td className="py-1.5 pr-2 pl-8">{attribute.name}</td>
                          <td className="px-2 py-1.5 text-muted-foreground">
                            {attribute.type || "?"}
                            {attribute.dimension ? "" : " · " + t("bds.catalog.unknownDimension")}
                          </td>
                          <td className="px-4 py-1.5 text-right">
                            <StateLabel state={state} onTab={onTab} />
                          </td>
                        </tr>
                      ))}
                    </Fragment>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>

        <section className="min-w-0 flex-[1_1_28rem] overflow-hidden rounded-lg border">
          <h2 className="border-b bg-muted/40 px-4 py-2 text-sm font-semibold">
            {t("bds.catalog.cadTitle", { document: workspace.cad_document || "—", count: catalog.data.cad.length })}
          </h2>
          {catalog.data.cad.length === 0 ? (
            <p className="p-4 text-sm text-muted-foreground">{t("bds.catalog.noTargets")}</p>
          ) : (
            <ul className="divide-y">
              {targets.map((target) => (
                <TargetItem key={target.reference} target={target} />
              ))}
            </ul>
          )}
        </section>
      </div>
      <p className="text-xs text-muted-foreground">
        {t("bds.catalog.axes", { length: axes.length, width: axes.width, height: axes.height })}
      </p>
    </div>
  )
}

function StateLabel({ state, onTab }: { state: AttributeState; onTab: TabProps["onTab"] }) {
  const { t } = useTranslation()
  if (state.state === "confirmed") {
    return state.requirement ? (
      <span className="text-success">● {state.requirement}</span>
    ) : (
      <span className="text-warning">● {t("bds.catalog.confirmedNoRequirement")}</span>
    )
  }
  if (state.state === "proposed") {
    return (
      <button type="button" className="text-warning underline" onClick={() => onTab("proposals")}>
        ◐ {t("bds.catalog.proposed", { id: state.proposal })}
      </button>
    )
  }
  return <span className="text-muted-foreground">○ {t(`bds.catalog.state.${state.state}`)}</span>
}

function TargetItem({ target }: { target: CadTarget }) {
  const { t } = useTranslation()
  const [doc, name] = target.reference.split("#")
  const parameters = Object.entries(target.parameters)
  const show = async () => {
    try {
      await showInFreeCAD(doc, name)
    } catch (error) {
      toast.error(describeError(error))
    }
  }
  return (
    <li className={cn("space-y-1.5 px-4 py-3", target.depth > 0 && "pl-8")}>
      <div className="flex flex-wrap items-baseline gap-2">
        <strong className="text-sm">{target.name}</strong>
        {name ? (
          <button type="button" className="text-xs text-muted-foreground underline" onClick={() => void show()}>
            {target.reference}
          </button>
        ) : (
          <code className="text-xs text-muted-foreground">{target.reference}</code>
        )}
        <span className="ml-auto text-xs text-muted-foreground">{t(`bds.catalog.kind.${target.kind}`)}</span>
      </div>
      <div className="flex flex-wrap gap-1.5 text-xs">
        {target.methods.length === 0 ? (
          <span className="text-destructive">{t("bds.catalog.notMeasurable")}</span>
        ) : (
          target.methods.map((method) => (
            <span key={method} className="rounded border px-1.5">
              {method}
            </span>
          ))
        )}
      </div>
      <p className="text-xs text-muted-foreground">{target.note}</p>
      {parameters.length > 0 && (
        <p className="text-xs text-muted-foreground">
          {t("bds.catalog.parameters")}: {parameters.map(([key, value]) => `${key} = ${value}`).join(" · ")}
        </p>
      )}
    </li>
  )
}
