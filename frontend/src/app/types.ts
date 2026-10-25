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
  project_id: string;
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

// ── UX-04/05/06 canonical surface projections ──────────────────────────────

export interface SheetFieldPayload {
  field_id: string;
  label: string;
  value: string | null;
  display_value?: string | null;
  binding_label: string; // "bound" | "partial" | "display-only" | "template-locked"
  unit?: string | null;
  field_type?: string;
  section_id?: string;
  section_label?: string;
  options?: string[];
  option_labels?: Record<string, string>;
  required?: boolean;
  min_value?: number | null;
  max_value?: number | null;
  step?: string | null;
  help_text?: string | null;
}

export interface SheetFieldsPayload {
  ok: true;
  sheet: string;
  project: { code: string; protected_reference: boolean };
  fields: SheetFieldPayload[];
  save: {
    url: string;
    method: string;
    csrf_token: string;
    financing_csrf_token: string;
    content_hash: string;
    workbook_version: string;
  };
}

export interface CostLinePayload {
  sub_line_id: string;
  label: string;
  amount_keur: number | string | null;
  row_version: string;
  notes: string | null;
  inflation_pct: number | null;
  active: boolean;
  category: string;
}

export interface CostLinesPayload {
  ok: true;
  sheet: "capex" | "opex";
  project: { code: string; protected_reference: boolean };
  lines: CostLinePayload[];
  save: {
    url: string;
    method: string;
    csrf_token: string;
    content_hash: string;
    workbook_version: string;
    max_batch_lines: number;
  };
  /** WF-React-2: canonical line-management routes (add / deactivate / reactivate). */
  line_management: {
    add: { url: string; group_field: string };
    deactivate: { url: string };
    reactivate: { url: string };
    eligible_groups: Array<{ code: string; label: string }>;
    csrf_note: string;
  };
}

export interface RevenueContractsPayload {
  ok: true;
  project: { code: string; protected_reference: boolean };
  contracts: Record<string, unknown>;
  save: {
    url: string;
    method: string;
    csrf_token: string;
    content_hash: string;
    workbook_version: string;
  };
}

export interface RunHistoryEntry {
  history_id: string;
  project_code: string;
  runtime_snapshot_id: string;
  runtime_origin: string | null;
  ran_at: string;
  active_scenario_id: string | null;
  active_scenario_name: string | null;
  last_runtime_scenario_id: string | null;
  engine_version: string | null;
  workbook_version: string | null;
  composite_hash: string | null;
}

export interface RunsPayload {
  ok: true;
  project: { code: string; protected_reference: boolean };
  runs: RunHistoryEntry[];
  run_contract: { url: string; method: string; csrf_token: string; note: string };
  /** WF-React-2: read-only canonical export entry points. */
  exports?: {
    last_run: { url: string; method: string; authority: string; available: boolean; unavailable_reason: string; note: string };
    historical: { url: string; query: string[]; note: string };
  };
}

export interface ScenarioOverrideFieldPayload {
  field_id: string;
  label: string;
  unit: string;
  base_value: number | string | null;
  override_value: number | string | null;
  overridden: boolean;
}

export interface ScenarioOverridesPayload {
  ok: true;
  project: { code: string; protected_reference: boolean };
  scenario: { scenario_id: string; name: string; is_base_case: boolean };
  editable: boolean;
  fields: ScenarioOverrideFieldPayload[];
  unsupported_override_keys: string[];
  mutations: {
    update: { url: string; fields: string[] };
    remove: { url: string; fields: string[] };
    note: string;
  };
}

export interface PersistedIntegrity {
  overall?: string;
  counts?: Record<string, number>;
  checks?: Array<Record<string, unknown>>;
  run_identity?: Record<string, unknown>;
  scope?: string;
}

export interface DiagnosticsPayload {
  ok: true;
  run_state: string;
  integrity: PersistedIntegrity | null;
  insight: Record<string, unknown>;
  diagnostics: Record<string, unknown>;
}

export interface DeferredTrustAction {
  state: "DEFERRED" | "UNAVAILABLE";
  reason: string;
  authority: string;
  scope: string;
  load_url: string | null;
  not_verify: true;
}

export interface TrustPayload {
  ok: true;
  run_state: string;
  identity: Record<string, unknown> | null;
  integrity: PersistedIntegrity | null;
  certificate: DeferredTrustAction;
  validation: DeferredTrustAction;
}

// ── UX-07 scenario management & compare ─────────────────────────────────────

export interface ScenarioRecordPayload {
  scenario_id: string;
  name: string;
  is_base_case: boolean;
  archived: boolean;
  override_count: number;
  updated_at: string | null;
  active: boolean;
}

export interface ScenariosPayload {
  ok: true;
  project: { code: string; protected_reference: boolean };
  active_scenario_id: string | null;
  active_scenario_name: string | null;
  scenarios: ScenarioRecordPayload[];
  mutations: {
    create: { url: string; fields: string[] };
    select: { url: string; fields: string[] };
    rename: { url: string; fields: string[] };
    archive: { url: string; fields: string[] };
    note: string;
  };
}

export interface ScenarioRunEvidence {
  state: "AVAILABLE" | "UNAVAILABLE";
  snapshot_id?: string | null;
  ran_at?: string | null;
  history_id?: string | null;
  note?: string;
}

export interface ScenarioComparePayload {
  ok: true;
  base: { label: string; scenario_id: string | null; run_evidence: ScenarioRunEvidence };
  scenario: { label: string; scenario_id: string; archived: boolean; override_count: number; run_evidence: ScenarioRunEvidence } | null;
  differences: Array<{
    field_id: string;
    base_value: unknown;
    scenario_value: unknown;
    explicitly_overridden: boolean;
    scenario_only: boolean;
  }>;
  kpi_compare: { available: false; reason: string };
}
