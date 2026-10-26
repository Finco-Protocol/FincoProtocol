/** Read-only WF-REACT-3 transport contract; financial values belong to the server. */
export interface RunIdentity {
  history_id: string; snapshot_id: string; scenario_id: string | null; scenario: string;
  ran_at: string; composite_hash: string; engine_version: string | null;
  workbook_version?: string | null; state: string;
}
export interface RunReference { identity: RunIdentity; links: Record<string, string> }
export interface Metric {
  key: string; label: string; raw_value: number | null; display_value: string;
  unit: string; availability: string; source: string; reason: string; period: string;
  history_id: string; snapshot_id: string; scenario_id: string | null;
}
export interface EvidenceCell { v: number | string | boolean | null; d: string; reason?: string; basis?: string }
export interface TimelineRow { key: string; label: string; kind: string; link: string; cells: EvidenceCell[] }
export interface Timeline {
  available: boolean; reason: string; columns: { index: number; date: string | null; start?: string | null }[];
  rows: TimelineRow[]; basis?: string;
}
export interface Finding {
  id: string; title: string; classification: string; status: string; source: string;
  detail?: string; authority?: string; reason?: string; evidence_source?: string;
  actual?: EvidenceCell; threshold?: EvidenceCell; headroom?: EvidenceCell;
}
export interface Credit {
  identity: RunIdentity; timeline: Timeline; capacity: Record<string, unknown>;
  structure: Record<string, unknown>; findings: Finding[];
  integrity: { status: string; reason?: string; failures?: unknown[] };
}
export interface SponsorMetric {
  key: string; label: string; value: number | null; display: string; unit: string;
  source: string; availability?: string; reason?: string;
}
export interface SponsorPeriodRow extends Readonly<Record<string, unknown>> {
  readonly period?: number | null; readonly date?: string | null;
  readonly share_capital_contribution_keur?: number | null;
  readonly share_premium_contribution_keur?: number | null;
  readonly other_committed_equity_contribution_keur?: number | null;
  readonly additional_equity_contribution_keur?: number | null;
  readonly shl_cash_interest_receipt_keur?: number | null;
  readonly shl_principal_receipt_keur?: number | null;
  readonly legal_equity_distribution_keur?: number | null;
}
export interface DistributionPeriodRow extends Readonly<Record<string, unknown>> {
  readonly period?: number | null; readonly date?: string | null;
  readonly distribution_keur?: number | null; readonly cum_distribution_keur?: number | null;
  readonly cf_after_reserves_keur?: number | null; readonly dsra_balance_keur?: number | null;
  readonly dsra_contribution_keur?: number | null; readonly mra_balance_keur?: number | null;
  readonly mra_contribution_keur?: number | null; readonly lockup_active?: boolean | null;
}
export interface Sponsor {
  state: string; has_runtime: boolean; metrics: SponsorMetric[];
  sponsor_rows: readonly SponsorPeriodRow[]; distribution_rows: readonly DistributionPeriodRow[];
  sponsor_available: boolean; distribution_available: boolean;
  sponsor_source: string; distribution_source: string; total_shl_funded: number | null;
}
export interface InsightRun extends RunReference { metrics: Metric[]; credit: Credit; sponsor: Sponsor }
export interface HistoryPayload {
  ok: true; schema: string; project: { code: string; project_id: string; name: string };
  working_copy: { freshness: string }; max_runs: number; history: RunReference[];
  scenarios: { scenario_id: string | null; name: string; is_base_case: boolean;
    committed_run: { history_id: string; snapshot_id: string; scenario_id: string | null } | null;
    availability: string; reason: string }[];
  history_limit: number; scenarios_complete: boolean; scenarios_omitted: number;
}
export interface ComparisonRow {
  key: string; label: string; fmt: string; values: string[]; deltas: string[];
  raw_values: (number | null)[]; variances: string[]; unit: string; source: string; sources?: string[]; availability: string[];
}
export interface InsightsPayload {
  ok: true; schema: string; project: HistoryPayload['project']; working_copy: { freshness: string };
  runs: InsightRun[]; comparison: { columns: RunIdentity[]; rows: ComparisonRow[] };
  credit: { policy?: { disclosure?: string; classes?: Record<string, string> } };
}
export interface InsightsFailure { ok: false; code: string; message?: string }
export type InsightsResult<T> = T | InsightsFailure;
