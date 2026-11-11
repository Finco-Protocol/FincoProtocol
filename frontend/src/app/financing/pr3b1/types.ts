import type { CreditPayload, CreditRunView, CreditCell } from '../../credit/types';
import type { DebtMetricsView } from '../../debtmetrics/types';
import type { FinancingStudioPayload, SourcesUsesView, SuRow } from '../types';

/** Narrow extensions verified against the existing GET projections. No new API. */
export type Run = Omit<CreditRunView, 'structure'> & {
  structure: {
    requested_gearing?: CreditCell; total_sources?: CreditCell; total_uses?: CreditCell;
    tenor?: { first_debt_service_date?: CreditCell; last_debt_service_date?: CreditCell; contractual_maturity_date?: CreditCell };
    interest?: { annual_rate_min?: CreditCell; annual_rate_max?: CreditCell };
  };
  debt_metrics?: DebtMetricsView;
};
export type Credit = Omit<CreditPayload, 'data'> & { data: (Omit<NonNullable<CreditPayload['data']>, 'runs'> & { runs: Run[] }) | null };
export type SourcesUses = SourcesUsesView & {
  construction_rows?: Array<{ period: number; date: string | null; fields: SuRow[] }>;
  su_authority_gap?: string; funding_waterfall_reason?: string;
};
export interface SelectedRun {
  identity: {history_id:string; snapshot_id:string; composite_hash:string; scenario_id:string|null; state:'CURRENT'|'STALE'|'HISTORICAL'};
  sources_uses: SourcesUses;
  construction:{rows:Array<{period_index:number;date:string|null;fields:SuRow[]}>;fc_senior_draw:{value:number|null;unit:string;source:string}};
  repayment:{available:boolean;reason:string;rows:Array<Record<string, unknown>>};
  source_authority:string;internal_run_binding:string;studio_credit_cross_view:string;
}
export type Studio = FinancingStudioPayload & { sources_uses: FinancingStudioPayload['sources_uses'] & { view?: SourcesUses };
  selected_run?:{available:boolean;reason?:string;view?:SelectedRun} };
export interface Workspace {
  ok: true; project: { code: string };
  workbook: { version: string; composite_hash: string; scenario_id: string | null; scenario_name: string | null };
  freshness: { state: string };
  identity: { snapshot_id: string; composite_hash: string; ran_at: string; scenario_proven?: boolean } | null;
}
export interface Fields {
  ok: true; project: { code: string };
  save: { content_hash: string; workbook_version: string };
  fields: Array<{ field_id: string; value: unknown; display_value?: string; unit?: string }>;
}
export interface Scope { project: string; scenarioId: string | null; historyId?: string }
export interface Evidence {
  scope: Scope; before: Workspace; after: Workspace; creditBefore: Credit; credit: Credit; studio: Studio; fields: Fields;
}
export interface Gate {
  state: 'NOT_RUN' | 'CURRENT' | 'STALE' | 'HISTORICAL' | 'UNAVAILABLE'; showRun: boolean; reason: string;
  assurance: 'MITIGATED_NOT_PROVEN' | 'NOT_PROVEN';
}
