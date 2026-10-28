// Shapes of GET /v2/model-react/analysis/credit-decision (app/v2/react_credit_decision.py).  Every figure arrives formatted by the server
// (`d`); `v` is the raw value or null when the Run did not persist it — the view never calculates, rounds or substitutes a value.
export interface CreditCell { v: number | string | boolean | null; d: string; reason?: string }
export type Dict = Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any -- server-projected evidence, rendered as given

export interface CreditRunView {
  identity: Dict; integrity: Dict; links: Record<string, string>; structure: Dict; capacity: Dict;
  timeline: { available: boolean; reason?: string; basis?: string; columns: Array<{ index: number; date: string | null }>;
              rows: Array<{ key: string; label: string; kind: string; link: string; cells: CreditCell[] }> };
  findings: Dict[];
}
export interface CreditFinding {
  id: string; title: string; classification: string; status: string; run_history_id: string; scenario: string; period: string | number | null;
  metric: string; severity?: string; actual: CreditCell | null; threshold: CreditCell | null; threshold_authority?: string; headroom: CreditCell | null;
  evidence_source?: string; reason_code?: string; detail?: string; check_id?: string;
}
export interface CreditData {
  schema: string; project_code: string; runs: CreditRunView[]; findings: CreditFinding[]; finding_counts: Record<string, number>;
  comparison: Dict; working_proposal: Dict | null; credit_v4?: Dict;
  policy: { failed_runs: string; classes: Record<string, string>; disclosure: string };
}
export interface CreditHistoryRow { history_id: string; ran_at: string; scenario: string; engine: string; is_last: boolean; selected: boolean }
export interface CreditPayload {
  ok: true; project: { code: string; name: string }; freshness: string; requested: string[]; max_runs: number;
  history_rows: CreditHistoryRow[]; data: CreditData | null;
}
export interface CreditFailure { ok: false; code: string; message?: string }
