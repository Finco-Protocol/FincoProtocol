// Typed payloads for the UX-02 React workspace projections (server-authored).
// Every type mirrors app/v2/react_workspace_router.py output; the React layer
// performs NO financial calculation — all values arrive as server-formatted
// display data.

export type FreshnessState = "NOT_RUN" | "CURRENT" | "STALE";

export interface FreshnessProjection {
  state: FreshnessState;
  basis: string;
  has_runtime: boolean;
  is_stale: boolean;
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

export interface EngineProjection {
  persisted_version: string | null;
  current_version: string | null;
  currency: string | null;
  treatment: string | null;
}

export interface ProjectIdentity {
  code: string;
  name: string;
  project_type: string;
  template_source?: string;
  protected_reference: boolean;
}

export interface WorkspacePayload {
  ok: true;
  react_workspace: { version: string };
  project: ProjectIdentity;
  workbook: { version: string; composite_hash: string; scenario_id: string | null; scenario_name: string | null };
  freshness: FreshnessProjection;
  identity: RunIdentity | null;
  integrity: IntegritySummary | null;
  integrity_available: boolean;
  status_dimensions: StatusDimensions | null;
  engine: EngineProjection;
}

export interface LibraryProject {
  code: string;
  name: string;
  project_type: string;
  template_source: string;
  protected_reference: boolean;
  reference: boolean;
  last_run: { available: boolean; freshness: string; snapshot_id: string; ran_at: string } | null;
}

export interface LibraryPayload {
  ok: true;
  react_workspace: { version: string };
  projects: LibraryProject[];
  references: LibraryProject[];
  page: number;
  page_size: number;
  total: number;
  total_pages: number;
  clone_url: string;
  csrf_token: string;
}

/** Server-adapted StatementSheet — mirrors the harvested statementContract shape. */
export interface StatementSheetPayload {
  id: string;
  label: string;
  title: string;
  unit: string;
  rows: Array<{ id: string; label: string; model: string[]; annual: string[]; kind?: string }>;
  available: boolean;
  note: string;
  unavailable: string[];
}

export interface StatementRunStatusPayload {
  label: string;
  runId: string;
  freshness: "unknown" | "current" | "stale" | "not run";
  integrity: "not evaluated";
  engineVersion: string | null;
  dataOrigin: "synthetic-demo" | "caller-provided" | "unavailable";
}

export interface ResultsPayload {
  available: boolean;
  metrics: Array<{ label: string; display: string; available: boolean; source: string }>;
  distributions: CanonicalTable | null;
  sponsor_table: CanonicalTable | null;
  sponsor_source: string | null;
  distribution_source: string | null;
  scenario: string | null;
  ran_at: string | null;
  engine_version: string | null;
}

/** Canonical single-view table (columns + rows of server-formatted cells). */
export interface CanonicalTable {
  id?: string;
  title?: string;
  available?: boolean;
  columns?: Array<{ index: number; date: string; label: string; year0?: boolean }>;
  rows?: Array<{ key: string; label: string; unit: string; total?: boolean; cells: Array<{ v: number | null; text: string; unit: string; neg: boolean }> }>;
  note?: string;
  unavailable?: string[];
}

export interface StatementsPayload {
  ok: true;
  react_workspace: { version: string };
  project: { code: string; name: string; protected_reference: boolean };
  state: "NOT_RUN" | "CURRENT" | "STALE" | "UNAVAILABLE";
  message: string;
  snapshot: {
    annualPeriods: string[];
    modelPeriods: string[];
    periodBands: Array<{ label: string; span: number }>;
    sheets: StatementSheetPayload[];
    debtRowsByFacility: Record<string, Array<{ id: string; label: string; model: string[]; annual: string[]; kind?: string }>>;
  } | null;
  status: StatementRunStatusPayload;
  results: ResultsPayload;
  freshness: FreshnessProjection;
  integrity: IntegritySummary | null;
  integrity_available: boolean;
  status_dimensions: StatusDimensions | null;
  banner: string;
}

export interface GridRowPayload {
  code: string;
  label: string;
  unit: string;
  field_id: string;
  value: string;
  editable: boolean;
  reason: string;
  min_value: number | null;
  max_value: number | null;
  step: string;
  modified_since_run: boolean;
  baseline: string;
  category_value: string;
  nav_tab: string;
  nav_group: string;
}

export interface GridCategoryPayload {
  code: string;
  label: string;
  total_display: string;
  rows: GridRowPayload[];
  editable_count: number;
  modified_count: number;
}

export interface GridSectionPayload {
  section_id: string;
  title: string;
  sheet_tab_id: string;
  categories: GridCategoryPayload[];
}

export interface GridProjectionPayload {
  sections: GridSectionPayload[];
  editable: boolean;
  editable_count: number;
  modified_since_run_count: number;
  baseline_note: string;
  content_hash: string;
  workbook_version: string;
  scenario_id: string;
}

export interface InputsPayload {
  ok: true;
  react_workspace: { version: string };
  project: { code: string; name: string; protected_reference: boolean };
  grid: GridProjectionPayload;
  save: {
    url: string;
    csrf_token: string;
    content_hash: string;
    workbook_version: string;
    scenario_id: string | null;
    max_cells: number;
    max_value_chars: number;
  };
  cost_line_boundary: { note: string; capex_opex_editable: boolean };
}
