// Typed view models for the UX-01 React PoC.
//
// These types mirror — but do NOT re-define — the canonical server contracts:
// the bootstrap payload is produced by app/v2/react_poc_router.py over the
// existing PostRunRequestContext + statement services, and the Save contract is
// the existing POST /v2/workbook/grid/save (app/v2/grid_router.py).  The React
// app performs NO financial calculation; every value here is display data from
// the canonical server evidence.

/** One statement cell. `v: null` means the Run never produced this value — it
 *  must render as unavailable (—), never as a zero. */
export interface StatementCell {
  v: number | null;
  text: string;
  unit: string;
  neg: boolean;
}

export interface StatementColumn {
  index: number;
  date: string;
  label: string;
  year0: boolean;
}

export interface StatementRow {
  key: string;
  label: string;
  total: boolean;
  unit: string;
  cells: StatementCell[];
  css_class: string;
  status_title: string;
}

export interface StatementTable {
  id: string;
  title: string;
  note: string;
  classification: string;
  /** Row labels whose cells are all unavailable — the canonical unavailable list. */
  unavailable: string[];
  available: boolean;
  columns: StatementColumn[];
  rows: StatementRow[];
  /** Canonical annual view (flows summed; stocks year-end). */
  annual?: StatementTable;
}

export interface RunIdentity {
  snapshot_id: string;
  ran_at: string;
  composite_hash: string;
  scenario: string;
  scenario_proven: boolean;
  engine_version: string;
}

export interface IntegritySummary {
  status: "PASS" | "FAIL" | "INCOMPLETE" | "UNAVAILABLE";
  label: string;
  counts: Record<string, unknown>;
  failures: Array<{ id: string | null; title: string | null; reason: string | null }>;
}

export interface StatusDimensions {
  run_context: string;
  input_freshness: string | null;
  input_freshness_basis: string;
  engine_currency: string;
  engine_persisted_version: string | null;
  engine_current_version: string | null;
  engine_identity_source: string;
  engine_reason: string;
  integrity: string;
  engine_superseded_treatment: string;
}

export interface OutputsProjection {
  state: "NOT_RUN" | "CURRENT" | "STALE" | "UNAVAILABLE";
  identity: RunIdentity | null;
  integrity: IntegritySummary;
  status_dimensions?: StatusDimensions;
  banner: string;
  /** Profit & Loss table only (PoC scope); null when NOT_RUN / UNAVAILABLE. */
  pnl: StatementTable | null;
}

export interface FreshnessProjection {
  state: "NOT_RUN" | "CURRENT" | "STALE";
  basis: string;
  has_runtime: boolean;
  is_stale: boolean;
}

export interface FieldProjection {
  field_id: string;
  label: string;
  unit: string | null;
  min: number | null;
  max: number | null;
  decimals: number | null;
  editable: boolean;
  /** Server-canonical display string of the authorized Working Copy value. */
  value: string;
}

export interface ProjectProjection {
  code: string;
  name: string;
  project_type: string;
  protected_reference: boolean;
}

export interface WorkbookIdentityProjection {
  version: string;
  composite_hash: string;
  scenario_id: string | null;
  scenario_name: string | null;
}

export interface BootstrapPayload {
  ok: true;
  react_poc: { version: string };
  project: ProjectProjection;
  workbook: WorkbookIdentityProjection;
  field: FieldProjection;
  csrf_token: string;
  freshness: FreshnessProjection;
  outputs: OutputsProjection;
}

export type BootstrapFailureCode =
  | "REACT_POC_DISABLED"
  | "AUTH_REQUIRED"
  | "PROJECT_NOT_FOUND"
  | "WORKSPACE_UNAVAILABLE";

export interface BootstrapError {
  ok: false;
  code: BootstrapFailureCode;
  message?: string;
}

export interface SavedCell {
  field_id: string;
  value: string;
}

/** Success body of the EXISTING canonical POST /v2/workbook/grid/save. */
export interface GridSaveSuccess {
  ok: true;
  saved: SavedCell[];
  content_hash: string;
  workbook_version: string;
  scenario_id: string | null;
  run_state: "NOT_RUN" | "CURRENT" | "STALE";
  model_executed: false;
}

export interface GridSaveFailure {
  ok: false;
  code: string;
  message?: string;
  detail?: string;
  reload?: boolean;
  cells?: Array<{ field_id: string; ok: boolean; code?: string; message?: string }>;
}
