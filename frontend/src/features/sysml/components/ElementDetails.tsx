import { Box, ClipboardCheck } from "lucide-react"
import type { ReactNode } from "react"
import { useTranslation } from "react-i18next"

import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"

import type { SysmlElement, SysmlSnapshot } from "../queries"
import { AttributeRows } from "./AttributeRows"

type Props = {
  snapshot: SysmlSnapshot
  element: SysmlElement
  /** Jump to another part (parent or child links). */
  onSelect: (id: string) => void
}

/** One part: its type, values, the requirements it satisfies, parent and children. */
export function ElementDetails({ snapshot, element, onSelect }: Props) {
  const { t } = useTranslation()
  const byId = new Map(snapshot.elements.map((e) => [e.id, e]))
  const attributes = snapshot.attributes.filter((a) => a.owner_id === element.id)
  const types = element.type_ids.map((id) => byId.get(id)?.name).filter(Boolean)
  const children = snapshot.elements.filter((e) => e.parent_id === element.id && e.kind === "part")
  const parent = element.parent_id ? byId.get(element.parent_id) : undefined
  const satisfies = snapshot.relations
    .filter((r) => r.kind === "satisfies" && r.source_id === element.id)
    .map((r) => byId.get(r.target_id))
    .filter((r): r is SysmlElement => r !== undefined)

  return (
    <Card className="gap-3 py-4">
      <CardHeader className="px-4">
        <CardTitle className="flex flex-wrap items-center gap-2">
          <Box className="size-4 text-primary" />
          {element.name}
          {types.length > 0 && <Badge variant="secondary">: {types.join(", ")}</Badge>}
        </CardTitle>
        <CardDescription className="space-y-0.5 text-xs">
          <p className="font-mono break-all">{element.qualified_name || element.id}</p>
          {element.doc && <p>{element.doc}</p>}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4 px-4 text-sm">
        <section>
          <SectionTitle>{t("sysml.details.attributes")}</SectionTitle>
          {attributes.length === 0 ? (
            <p className="text-muted-foreground">{t("sysml.details.noAttributes")}</p>
          ) : (
            <AttributeRows attributes={attributes} />
          )}
        </section>

        {satisfies.length > 0 && (
          <section>
            <SectionTitle>{t("sysml.details.satisfies")}</SectionTitle>
            <ul className="space-y-1">
              {satisfies.map((r) => (
                <li key={r.id} className="flex items-start gap-2">
                  <ClipboardCheck className="mt-0.5 size-3.5 shrink-0 text-success" />
                  <span>
                    {r.extra.req_id && <span className="mr-1 font-mono text-xs">{r.extra.req_id}</span>}
                    {r.extra.text || r.name}
                  </span>
                </li>
              ))}
            </ul>
          </section>
        )}

        <section className="flex flex-wrap gap-x-6 gap-y-1 text-xs text-muted-foreground">
          {parent && parent.kind === "part" && (
            <span>
              {t("sysml.details.partOf")}{" "}
              <button type="button" className="underline" onClick={() => onSelect(parent.id)}>
                {parent.name}
              </button>
            </span>
          )}
          {children.length > 0 ? (
            <span>
              {t("sysml.details.contains")}{" "}
              {children.map((c, i) => (
                <span key={c.id}>
                  {i > 0 && ", "}
                  <button type="button" className="underline" onClick={() => onSelect(c.id)}>
                    {c.name}
                  </button>
                </span>
              ))}
            </span>
          ) : (
            <span>{t("sysml.details.leafHint")}</span>
          )}
        </section>
      </CardContent>
    </Card>
  )
}

function SectionTitle({ children }: { children: ReactNode }) {
  return <h3 className="mb-1.5 text-xs font-medium tracking-wide text-muted-foreground uppercase">{children}</h3>
}
