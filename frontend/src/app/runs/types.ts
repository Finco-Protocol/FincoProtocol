// RC-UX B2/B3 transport contract for GET /v2/model-react/compare.  Every figure is a server-formatted or server-supplied value;
// nothing in the browser derives a financial number.
export interface CompareColumn {
  history_id: string; snapshot_id: string; scenario_id: string | null; scenario: string; ran_at: string;
  composite_hash: string; engine_version: string | null; workbook_version?: string | null; state: string;
  runtime_origin?: string | null; links: Record<string, string>;
}
export interface CompareRow {
  key: string; label: string; fmt: string; unit: string; kind: "kpi" | "evidence";
  values: string[]; raw_values: (number | null)[]; abs_deltas: string[]; pct_deltas: string[]; pct_raw: (number | null)[];
  availability: string[]; source: string; reason?: string;
}
export interface CashflowRun { history_id: string; values: (number | null)[]; total: number | null; available: boolean }
export interface CashflowSeries {
  key: string; label: string; unit: string; source: string; periods: number[]; dates: string[]; calendar_mismatch: boolean; runs: CashflowRun[];
}
export interface LineDifference { line_id: string; group: string; values: (number | null)[] }
export interface OverrideDifference { key: string; values: unknown[] }
export interface AssumptionDifferences {
  composite_hash_equal: boolean; composite_hashes: (string | null)[]; identity_persisted: boolean[];
  scenario_overrides: OverrideDifference[]; capex_lines: LineDifference[]; opex_lines: LineDifference[]; limitation: string;
}
export interface ComparePayload {
  ok: true; schema: string; project: { code: string; project_id: string; name: string };
  working_copy: { freshness: string; composite_hash: string | null }; reference_history_id: string;
  columns: CompareColumn[]; rows: CompareRow[];
  cashflow: { axis: string; series: CashflowSeries[]; note: string };
  assumptions: AssumptionDifferences;
  semantics: { read_only: boolean; is_a_run: boolean; basis: string };
}
export interface CompareFailure { ok: false; code: string; message?: string }
