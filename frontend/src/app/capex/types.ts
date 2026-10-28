// RC-UX A2 transport contract for GET /v2/model-react/capex/{profiles,preview}.  Amounts are server-formatted exact kEUR strings;
// nothing in the browser allocates, rounds or sums a financial value.
export interface CapexItem { item_key: string; kind: string; label: string; category_code: string; amount_keur: number; amount_display: string }
export interface CapexTimeline {
  available: boolean; reason: string; months: number; source: string; month_start: string[]; month_to_period: number[];
  period_starts: string[]; period_ends: string[];
}
export interface SavedRow { shape: string; explicit: string; milestone: string }
export interface SourcesUsesValue { value: number; display: string }
export interface CapexLastRun {
  available: boolean; note?: string; freshness?: string; used_profile?: boolean; ran_at?: string; basis?: string;
  sources_uses?: Record<string, SourcesUsesValue | null>;
  periods?: { period: number | string | null; uses: string; sources: string; difference: string }[];
}
export interface CapexProfiles {
  ok: true; project: { code: string; name: string; vertical: string; pilot_tier: string };
  months: number; timeline: CapexTimeline; shapes: string[]; items: CapexItem[]; excluded: CapexItem[];
  saved: { rows: Record<string, SavedRow>; error: string | null; binding: { saved: boolean; bound: boolean; code: string; items: number } };
  last_run: CapexLastRun;
  edit: { allowed: boolean; reason: string; base_case: boolean };
  save: { url: string; csrf_token: string; content_hash: string; scenario_id: string };
  semantics: { save_runs_the_model: boolean; preview_is_a_result: boolean; idc_and_sources_uses: string };
}
export interface PlanRow {
  item_key: string; label: string; shape: string; amount_display: string; status: "valid" | "invalid"; error_code: string | null;
  error_detail: string | null; unallocated_display: string; rounding_residual: string | null; period_equivalent: string[];
}
export interface PlanMonth { month: number; start: string | null; period: number | null; items: Record<string, string>; total: string; cumulative: string; remaining: string }
export interface CapexPlan {
  months_count: number; rows: PlanRow[]; months: PlanMonth[]; item_order: string[];
  totals: { planned: string; profiled: string; unallocated: string; reconciles: boolean };
  period_equivalent_total: string[]; global_errors: string[]; notice: string; canonical: boolean;
}
export interface CapexPreview { ok: true; plan: CapexPlan; content_hash: string }
export interface CapexFailure { ok: false; code: string; message?: string }
export interface DraftRow { shape: string; explicit: string; milestone: string }
export type Draft = Record<string, DraftRow>;
