import type { CreditPayload, CreditRunView } from '../../credit/types';
import type { DebtMetricsView } from '../../debtmetrics/types';
import type { FinancingStudioPayload, SourcesUsesView, SuRow } from '../types';

/** Narrow extensions verified against the existing GET projections. No new API. */
export type Run = CreditRunView & { debt_metrics?: DebtMetricsView };
export type Credit = CreditPayload & { data: (NonNullable<CreditPayload['data']> & { runs: Run[] }) | null };
export type SourcesUses = SourcesUsesView & {
  construction_rows?: Array<{ period: number; date: string | null; fields: SuRow[] }>;
  su_authority_gap?: string; funding_waterfall_reason?: string;
};
export type Studio = FinancingStudioPayload & { sources_uses: FinancingStudioPayload['sources_uses'] & { view?: SourcesUses } };
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
  state: 'NOT_RUN' | 'CURRENT' | 'STALE' | 'UNAVAILABLE'; showRun: boolean; reason: string;
  assurance: 'MITIGATED_NOT_PROVEN' | 'NOT_PROVEN';
}
