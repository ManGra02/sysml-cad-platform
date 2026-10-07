import { CircleAlert } from "lucide-react"
import { useTranslation } from "react-i18next"

import { formatAttribute, formatSi, type SysmlAttribute, type SysmlElement } from "../queries"

type Props = {
  attributes: SysmlAttribute[]
  /** Pass the elements to get an extra "Part" column (all-values table); leave out inside one part. */
  owners?: Map<string, SysmlElement>
}

/** Table of values: attribute, value as modelled, value in SI. Shared by the details panel and the Values tab. */
export function AttributeRows({ attributes, owners }: Props) {
  const { t } = useTranslation()
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead className="text-left text-xs text-muted-foreground">
          <tr className="border-b">
            {owners && <th className="py-1.5 pr-3 font-medium">{t("sysml.columns.element")}</th>}
            <th className="py-1.5 pr-3 font-medium">{t("sysml.columns.attribute")}</th>
            <th className="py-1.5 pr-3 font-medium">{t("sysml.columns.value")}</th>
            <th className="py-1.5 font-medium">{t("sysml.columns.si")}</th>
          </tr>
        </thead>
        <tbody>
          {attributes.map((a) => (
            <tr key={a.id} className="border-b last:border-0">
              {owners && <td className="py-1.5 pr-3">{owners.get(a.owner_id)?.name ?? "—"}</td>}
              <td className="py-1.5 pr-3 font-mono text-xs">{a.name}</td>
              <td className="py-1.5 pr-3 tabular-nums" title={a.expression ?? undefined}>
                {formatAttribute(a)}
                {a.warnings.length > 0 && (
                  <CircleAlert className="ml-1 inline size-3.5 text-warning" aria-label={a.warnings.join("; ")} />
                )}
              </td>
              <td className="py-1.5 text-muted-foreground tabular-nums">{formatSi(a) ?? "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
