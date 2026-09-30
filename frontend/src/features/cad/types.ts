// The bridge's value format, mirrored from bridge/cad_contract/types.py.
// A change there bumps CONTRACT_VERSION -- then update this file as well.

/** The ONLY key for an object: (doc.Name, obj.Name). Never the label. */
export type ObjRef = { doc: string; name: string; subs?: string[] }

export type Quantity = {
  kind: "quantity"
  value: number
  unit: string
  unitType: string | null
  text: string
}
export type VectorValue = { kind: "vector"; x: number; y: number; z: number }
export type PlacementValue = { kind: "placement"; pos: number[]; q: number[] }
export type RotationValue = { kind: "rotation"; q: number[] }
export type MatrixValue = { kind: "matrix"; a: number[] }
export type ColorValue = { kind: "color"; rgba: number[] }
export type EnumValue = { kind: "enum"; value: string | number; choices: string[] }
export type LinkValue = { kind: "link"; ref: ObjRef | null }
export type LinkListValue = { kind: "link_list"; refs: ObjRef[] }
export type LinkSubValue = { kind: "link_sub"; ref: ObjRef }
export type LinkSubListValue = { kind: "link_sub_list"; refs: ObjRef[] }
export type MaterialRefValue = { kind: "material_ref"; uuid: string; name: string }
export type MapValue = { kind: "map"; entries: Record<string, string> }
export type SetValue = { kind: "set"; values: string[] }
export type UnsupportedValue = { kind: "unsupported"; typeId: string; summary: string }

export type KindValue =
  | Quantity
  | VectorValue
  | PlacementValue
  | RotationValue
  | MatrixValue
  | ColorValue
  | EnumValue
  | LinkValue
  | LinkListValue
  | LinkSubValue
  | LinkSubListValue
  | MaterialRefValue
  | MapValue
  | SetValue
  | UnsupportedValue

export type PropertyValue =
  | KindValue
  | boolean
  | number
  | string
  | null
  | Array<number | string | boolean | number[] | VectorValue | PlacementValue>

export type PropertyEntry = {
  name: string
  typeId: string
  /** encoded: editable format · derived: derived (Shape) · unsupported: present, not representable */
  status: "encoded" | "derived" | "unsupported"
  value: PropertyValue
  group: string | null
  doc: string | null
  flags: string[]
  writable: boolean
  dynamic: boolean
  /** bound -> a literal value would be discarded on the next recompute */
  expression: string | null
}

export type ObjectSummary = {
  doc: string
  name: string
  label: string
  typeId: string
  id: number | null
  internal: boolean
  visible: boolean | null
  state: string[]
  rev: number
  instanceOf?: string | null
}

export type TreeNode = ObjectSummary & {
  children: string[]
  deps: string[]
  childSource: "claimChildren" | "group" | null
}

export type Tree = {
  doc: string
  roots: string[]
  nodes: Record<string, TreeNode>
  objectCount: number
  hiddenInternal: number
  guiAccurate: boolean
}

export type Geometry = {
  null: boolean
  shapeType?: string | null
  volume?: number
  area?: number
  valid?: boolean
  boundBox?: { min: number[]; max: number[]; lengths: number[]; center: number[]; diagonal: number }
  centerOfMass?: number[]
  counts?: { solids?: number; faces?: number; edges?: number; vertexes?: number }
}

export type ObjectDetail = ObjectSummary & {
  properties: PropertyEntry[]
  geometry?: Geometry | null
}

export type ObjectBatch = { doc: string; objects: ObjectDetail[]; missing?: string[] }

export type DocumentInfo = {
  name: string
  label: string
  fileName: string | null
  saved: boolean
  /** only known while the FreeCAD GUI is running */
  modified: boolean | null
  objectCount: number
  undoCount: number | null
  undoNames: string[]
  transacting: boolean
  restoring: boolean
}

export type DocumentList = { documents: DocumentInfo[]; active: string | null }

export type BridgeState = "unconfigured" | "unreachable" | "busy" | "ok"

export type BridgeStatus = {
  state: BridgeState
  /** machine-readable reason (the UI translates it), e.g. "orphaned_handshake" */
  reason: string | null
  /** plain English text -- fallback for unknown reasons */
  detail: string | null
  session_id: string | null
  last_seq: number | null
  contract: { bridge: string | null; backend: string; match: boolean }
}

export type PlatformStatus = {
  backend: { contract_version: string; clients: number }
  bridge: BridgeStatus
}

export type WriteResult = {
  status: "done"
  atomic: boolean
  changed: boolean
  applied: string[]
  unchanged: string[]
  recomputed: number
  errors: Array<{ doc: string; name: string; state: string[] }>
  rev: number
  ref: ObjRef
  replayed?: boolean
}

export type SelectionEntry = ObjRef & { label: string; typeId: string }
export type Selection = { available: boolean; selection: SelectionEntry[] }

export type CadEvent = {
  type: string
  doc?: string
  obj?: string
  label?: string | null
  props?: string[]
  origin?: string
  cause?: string
  rev?: number
  seq?: number
  session_id?: string | null
  reason?: string
  [key: string]: unknown
}

/** detail of a 409 rev_mismatch response (cad_contract 0.4.0). */
export type RevisionConflictDetail = {
  expected: number
  current: number
  object: ObjectDetail
}
