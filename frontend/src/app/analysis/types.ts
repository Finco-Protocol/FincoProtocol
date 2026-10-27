// Wire types of the RC-M Analysis adapters (app/v2/react_analysis.py, app/v2/react_goal_seek.py).
// Every value is produced by the canonical sensitivity / goal-seek authorities on the server; the browser calculates nothing.

export type PilotTier = "PILOT_CANDIDATE" | "PREVIEW" | "RELEASE_CLOSED" | "UNCLASSIFIED";
export interface VerticalInfo { key: string; public_name: string; pilot_tier: PilotTier; limitations: string[] }

export interface LevelOption { value: number; label: string }
export interface DriverInfo {
  key: string; label: string; unit: string; mode: "pct" | "abs";
  default_levels: LevelOption[]; default_levels_3: LevelOption[]; max_abs_level: number;
}
export interface MetricInfo { key: string; label: string; unit: string; fmt: string; note: string }

export interface SensitivityCatalog {
  ok: true;
  vertical: VerticalInfo;
  drivers: DriverInfo[];
  metrics: MetricInfo[];
  strip_columns: string[];
  limits: { strip_points: number; grid_sizes: number[]; max_cells: number; max_evaluations: number };
  semantics: { ephemeral: boolean; writes_nothing: boolean; is_a_run: boolean; basis: string };
}

export interface RunInfo {
  evaluations: number; cells: number; seconds: number; base_reused_from_zero_cell: boolean;
  scenario: string; scenario_id: string; basis_hash: string; ephemeral: boolean; writes_nothing: boolean; is_a_run: boolean;
  completed?: number; failed?: number; unavailable?: number;
}

export interface StripValue { raw: number | null; display: string; delta: number | null; delta_display: string }
export interface StripRow {
  index: number; level: number; label: string; is_base: boolean; status: "OK" | "FAILED" | "UNAVAILABLE"; reason: string;
  input: { text: string; original: number | null; shocked: number | null; unit: string };
  values: Record<string, StripValue>;
}
export interface StripResult {
  ok: true; kind: "strip"; vertical: VerticalInfo; driver: DriverInfo;
  levels: LevelOption[]; columns: Array<{ key: string; label: string; unit: string; fmt: string }>; rows: StripRow[];
  base: { status: string; reason: string; values: Record<string, { raw: number | null; display: string }> };
  counts: Record<string, number>; run: RunInfo; provenance: string;
}

export interface MatrixCell {
  i: number; j: number; level_a: number; level_b: number; label_a: string; label_b: string;
  status: "OK" | "FAILED" | "UNAVAILABLE"; reason: string; raw: number | null; display: string;
  delta: number | null; delta_display: string; delta_pct: string | null;
  threshold_status: string; inputs: Record<string, { text?: string }>; is_base: boolean;
}
export interface MatrixView {
  metric: { key: string; label: string; unit: string; fmt: string };
  driver_a: { key: string; label: string; unit: string; levels: LevelOption[] };
  driver_b: { key: string; label: string; unit: string; levels: LevelOption[] };
  base: { status: string; raw: number | null; reason: string; display: string };
  threshold: { raw: number; display: string; comparator: string; origin: string } | null;
  cells: MatrixCell[]; rows: MatrixCell[][];
  brackets: Array<{ axis: string; from: string[]; to: string[]; note: string }>;
  counts: Record<string, number>; threshold_counts: Record<string, number>;
}
export interface MatrixResult { ok: true; kind: "matrix"; vertical: VerticalInfo; matrix: MatrixView; run: RunInfo; provenance: string }

export interface GoalSeekCatalog {
  ok: true; available: boolean; reason: string; vertical: VerticalInfo;
  metrics: Array<{ key: string; label: string }>;
  variable: { key: string; label: string; unit: string; field_id: string } | null;
  current_tariff: number | null;
  budgets: { max_iterations: number; max_model_evaluations: number; target_tolerance: number };
  binding: { content_hash: string; workbook_version: string };
  semantics: { preview_only: boolean; writes_nothing: boolean; is_a_run: boolean; basis: string };
}

export interface GoalSeekApplyBinding {
  field_id: string; value: string; content_hash: string; workbook_version: string;
  target_metric: string; target_value: string; csrf_token: string;
}
export interface GoalSeekResultBody {
  status: string; solved: boolean; message: string; target_metric: string; target_metric_label: string; target_display: string;
  variable: { key: string; label: string; unit: string; field_id: string };
  started_from: number; started_from_display: string; solved_input_value: number | null; solved_display: string | null;
  delta_display: string | null; variance_display: string | null; achieved_display: string | null; error_display: string | null;
  iterations: number; model_evaluations: number; expansions: number; lower_bound: number; upper_bound: number;
  bracket_lower: number | null; bracket_upper: number | null;
}
export interface GoalSeekPreview {
  ok: true; preview_only: boolean; committed: boolean; is_a_run: boolean; vertical: VerticalInfo;
  result: GoalSeekResultBody; budgets: GoalSeekCatalog["budgets"]; apply: GoalSeekApplyBinding | null; provenance: string;
}
export interface GoalSeekApplied {
  ok: true; applied: boolean; field_id: string; value: string; content_hash: string; workbook_version: string; run_state: string; message: string;
}

/** A typed refusal from any adapter: nothing was written unless `code` is an UNKNOWN outcome. */
export interface AdapterFailure { ok: false; code: string; message?: string; status: number }
