// Shapes of `runs[i].debt_metrics` in GET /v2/model-react/analysis/credit-decision (app/v2/debt_metrics_projection.py, schema WF04_DEBT_METRICS_V1).
// Everything arrives from the committed Run's own persisted evidence.  The view never calculates a financial number: raw values (`v`, numbers) are
// used only to place marks and to compare nothing — every status below is decided on the server on raw doubles.
export interface DmCell { v: number | null; d: string; reason?: string }
export interface DmPoint { period_index: number; date: string | null; dscr: number | null; base_cfads_keur: number | null; debt_service_keur: number | null;
  principal_keur: number | null; interest_keur: number | null; shortfall_keur: number | null; gap_x?: number }
export interface DmTableRow {
  id: string; label: string; role: string; description: string; basis: string;
  required: { v: number | null; d: string; operator: string; note?: string };
  actual: DmCell;
  headroom: { absolute: { v: number; d: string }; relative: { v: number; d: string }; note: string } | null;
  status: string; status_label: string; severity: "CRITICAL" | "WARNING" | "OK" | "NEUTRAL"; reason: string; periods: DmPoint[]; periods_total: number;
}
export interface DmKpi { label: string; available: boolean; value: number | string | null; display: string; basis: string; reason: string;
  period?: DmPoint | null; status?: string | null; reproduced_from_periods?: boolean }
export interface DmPeriod {
  period_index: number; date: string | null; year: number | null; period_in_year: number | null; label: string; has_debt_service: boolean;
  dscr: number | null; bank_dscr: number | null; sizing_target_dscr: number | null;
  base_cfads_keur: number | null; bank_cfads_keur: number | null; debt_service_keur: number | null; principal_keur: number | null; interest_keur: number | null;
  senior_opening_keur: number | null; senior_closing_keur: number | null; shortfall_keur: number | null;
  below_one: boolean | null; eod_breach: boolean | null; covenant_breach: boolean | null; lockup_active: boolean | null;
  dsra_balance_keur: number | null; dsra_contribution_keur: number | null; dsra_funding_keur: number | null; dsra_release_keur: number | null;
  distribution_keur: number | null; cash_sweep_keur: number | null; senior_balance_keur: number | null;
}
export interface DmVerdict { status: string; reason: string; threshold_x: number | null; threshold_raw: string | null; breaching_periods: DmPoint[];
  worst: DmPoint | null; headroom: { absolute_x: number; relative_pct: number } | null; message?: string; note?: string }
export interface DmEvaluation {
  schema: string; basis: Record<string, string>; terms_recorded: boolean; terms_reason: string;
  achieved_min_dscr: { available: boolean; reason: string; min: number | null; period: DmPoint | null };
  bank_case_min_dscr: { available: boolean; min: number | null; period: (DmPoint & { bank_dscr?: number }) | null };
  coverage: { status: string; reason: string; message?: string; periods: DmPoint[]; total_shortfall_keur?: number };
  eod: DmVerdict; covenant: DmVerdict;
}
export interface DmScheduleRow { key: string; label: string; unit: "kEUR" | "x" | "flag"; values: Array<number | boolean | null>; available: boolean; reason: string }
export interface DmLockup { available: boolean; reason: string; active_count: number | null; note?: string; periods: Array<{ period_index: number; label: string; date: string | null; active: boolean }> }
export interface DmReserves {
  dsra: { available: boolean; present: boolean; reason: string; initial_funding_keur?: number | null; peak_balance_keur?: number; required?: { available: boolean; reason: string } };
  dsrf: { available: boolean; reason: string }; lockup: DmLockup;
  unavailable_conclusions: Array<{ id: string; label: string; status: string; missing: string[] }>;
}
export interface DebtMetricsView {
  schema: string; available: boolean; reason: string; run_state: string; basis_note: string;
  contract_terms: {
    recorded: boolean; reason: string; note: string; test_basis: Record<string, string>;
    eod_minimum_dscr: { status: string; value: number | null; raw: string | null; label: string };
    contractual_dscr: { status: string; value: number | null; raw: string | null; label: string };
  };
  evaluation: DmEvaluation; covenant_table: DmTableRow[]; kpis: Record<string, DmKpi>;
  axis: { frequency: string; periods_per_year: number | null; period_count: number; note: string };
  periods: DmPeriod[];
  series: { llcr: { available: boolean; reason: string }; thresholds: { coverage_x: number; eod_x: number | null; contractual_x: number | null; sizing_target_note: string } };
  reserves: DmReserves | null; schedule: Array<{ id: string; label: string; rows: DmScheduleRow[] }>;
  integrity: { status: string; failures: Array<{ id: string; title?: string; reason?: string }> };
}
