import { useTranslation } from "react-i18next"

import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"

import type { SysmlSnapshot } from "../queries"
import { HistoryTab } from "./HistoryTab"
import { RequirementsTab } from "./RequirementsTab"
import { StructureTab } from "./StructureTab"
import { SummaryTiles } from "./SummaryTiles"
import { ValuesTab } from "./ValuesTab"

/** One loaded snapshot: the summary tiles and the four tabs. Each tab owns its own logic. */
export function ModelView({ snapshot, project }: { snapshot: SysmlSnapshot; project: string }) {
  const { t } = useTranslation()
  return (
    <>
      <SummaryTiles snapshot={snapshot} />

      <Tabs defaultValue="structure">
        <TabsList>
          <TabsTrigger value="structure">{t("sysml.tabs.structure")}</TabsTrigger>
          <TabsTrigger value="attributes">{t("sysml.tabs.attributes")}</TabsTrigger>
          <TabsTrigger value="requirements">{t("sysml.tabs.requirements")}</TabsTrigger>
          <TabsTrigger value="history">{t("sysml.tabs.history")}</TabsTrigger>
        </TabsList>
        <TabsContent value="structure">
          <StructureTab snapshot={snapshot} />
        </TabsContent>
        <TabsContent value="attributes">
          <ValuesTab snapshot={snapshot} />
        </TabsContent>
        <TabsContent value="requirements">
          <RequirementsTab snapshot={snapshot} />
        </TabsContent>
        <TabsContent value="history">
          <HistoryTab project={project} current={snapshot.version} />
        </TabsContent>
      </Tabs>

      {snapshot.warnings.length > 0 && (
        <details className="text-xs text-muted-foreground">
          <summary className="cursor-pointer">{t("sysml.warnings", { count: snapshot.warnings.length })}</summary>
          <ul className="mt-2 list-disc pl-5">
            {snapshot.warnings.map((w, i) => (
              <li key={i}>{w}</li>
            ))}
          </ul>
        </details>
      )}
    </>
  )
}
