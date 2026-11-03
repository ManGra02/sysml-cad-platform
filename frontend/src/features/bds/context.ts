import { createContext, useContext } from "react"

import type { WorkspaceActions } from "./actions"
import type { MeasureRequest, TableContext } from "./components/RequirementTable"
import type { Assignment, Progress, RequirementRow, Staleness } from "./logic"
import type { Catalog, Mapping, Proposal, ProposeResult, Run, Workspace } from "./queries"

/**
 * Everything the areas of a workspace (overview, assign, check, limits, models) share:
 * read once by the workspace layout, so switching areas costs no round through FreeCAD.
 */
export type WorkspaceData = {
  workspace: Workspace
  commit?: string
  catalog: Catalog
  mapping?: Mapping
  run?: Run
  /** Loading the stored result failed for another reason than "never checked". */
  runError?: unknown
  rows: RequirementRow[]
  progress: Progress
  /** Open suggestions for requirements. */
  pending: number
  others: Assignment[]
  /** Open suggestions for attributes no requirement constrains. */
  strayProposals: Proposal[]
  rejected: Proposal[]
  lastProposal?: ProposeResult
  setLastProposal: (result: ProposeResult) => void
  table: TableContext
  actions: WorkspaceActions
  bridgeDown: boolean
  documentOpen?: boolean
  stale: Staleness
  cadChangedAt?: number
  onMeasure: (request: MeasureRequest) => void
}

export const WorkspaceContext = createContext<WorkspaceData | undefined>(undefined)

export function useWorkspaceData(): WorkspaceData {
  const data = useContext(WorkspaceContext)
  if (!data) throw new Error("useWorkspaceData outside of a workspace")
  return data
}
