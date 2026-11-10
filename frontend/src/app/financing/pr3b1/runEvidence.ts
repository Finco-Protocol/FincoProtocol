import type { Evidence, Gate, Workspace, Run } from './types';

const present = (v: unknown): v is string => typeof v === 'string' && v.length > 0;
const numeric = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v);
export function rawAmount(v: unknown): number | null {
  const value = v && typeof v === 'object' && 'value' in v ? v.value : v;
  return numeric(value) ? value : null;
}
function anchor(w: Workspace): string {
  return JSON.stringify([w.project.code, w.workbook, w.freshness, w.identity]);
}
function runAnchor(r: Run | undefined): string { return JSON.stringify(r?.identity ?? null); }
function sameDebtPeriods(e: Evidence, r: Run): boolean {
  const period = e.studio.selected_run?.view?.repayment;
  const dm = r.debt_metrics;
  if (!period || !dm || period.available !== dm.available) return false;
  if (!dm.available) return true;
  const keys = ['period_index','date','senior_opening_keur','principal_keur','interest_keur',
    'debt_service_keur','senior_closing_keur','dscr','shortfall_keur','cash_after_senior_keur'];
  const values = (rows: readonly object[]) => rows.map(row =>
    keys.map(key => (row as Record<string,unknown>)[key] ?? null));
  return JSON.stringify(values(period.rows)) === JSON.stringify(values(dm.periods));
}

/** A selected committed Run must match Credit identity exactly. Studio Last Run
 * is not substituted for historical data. The cross-view assurance stays
 * MITIGATED_NOT_PROVEN because Studio has no independent snapshot attestation.
 */
export function checkRunEvidence(e: Evidence): Gate {
  const deny = (detail: string): Gate => ({state:'UNAVAILABLE',showRun:false,
    reason:'Selected Run changed — reload. '+detail,assurance:'NOT_PROVEN'});
  const {scope,before,after,studio:s,credit:c,creditBefore:cb,fields}=e;
  if (!scope || !before?.project || !after?.project || !before.workbook || !after.workbook
      || !before.freshness || !after.freshness || !s?.identity || !s.project || !s.sources_uses
      || !c?.project || !cb?.project || !Array.isArray(c.history_rows) || !Array.isArray(cb.history_rows)
      || !fields?.project || !fields.save || !Array.isArray(fields.fields)
      || (c.data && !Array.isArray(c.data.runs)) || (cb.data && !Array.isArray(cb.data.runs)))
    return deny('Response shape/identity missing.');
  if (![before,after,s,c,cb,fields].every(x => x.ok && x.project.code===scope.project)
      || (c.data && c.data.project_code!==scope.project)
      || (cb.data && cb.data.project_code!==scope.project)) return deny('Project differs.');
  if (anchor(before)!==anchor(after)) return deny('Workspace changed during read.');
  if (before.workbook.scenario_id!==scope.scenarioId || s.identity.scenario_id!==scope.scenarioId)
    return deny('Working Copy scenario differs.');
  if (!present(s.identity.content_hash) || s.identity.content_hash!==before.workbook.composite_hash
      || s.identity.workbook_version!==before.workbook.version
      || fields.save.content_hash!==s.identity.content_hash
      || fields.save.workbook_version!==s.identity.workbook_version) return deny('Working Copy identity differs.');
  const r=c.data?.runs[0];
  if (runAnchor(cb.data?.runs[0])!==runAnchor(r) || cb.freshness!==c.freshness
      || JSON.stringify(cb.history_rows)!==JSON.stringify(c.history_rows))
    return deny('Run selection changed during read.');
  if (before.freshness.state==='NOT_RUN' && s.freshness==='NOT_RUN' && c.freshness==='NOT_RUN'
      && !r && !before.identity && !scope.historyId && !s.selected_run?.available)
    return {state:'NOT_RUN',showRun:false,reason:'NOT_RUN — no committed selected Run.',assurance:'NOT_PROVEN'};
  if (!r || c.data?.runs.length!==1 || !r.identity || !r.structure || !r.capacity)
    return deny('Exactly one committed selected Run required.');
  const id=r.identity;
  if (![id.snapshot_id,id.history_id,id.ran_at,id.composite_hash].every(present))
    return deny('Run identity missing.');
  const row=c.history_rows.find(h => h.history_id===id.history_id);
  if (!row?.selected || (scope.historyId && scope.historyId!==id.history_id))
    return deny('Selected history id differs.');
  const selected=s.selected_run?.view;
  if (!s.selected_run?.available || !selected) return deny(s.selected_run?.reason || 'Selected evidence absent.');
  const b=selected.identity;
  if (!b || selected.source_authority!=='ONE_COMMITTED_RUN_HISTORY_ENTRY'
      || selected.internal_run_binding!=='PROVEN_BACKEND_ENTRY'
      || selected.studio_credit_cross_view!=='MITIGATED_NOT_PROVEN'
      || b.history_id!==id.history_id || b.snapshot_id!==id.snapshot_id
      || b.composite_hash!==id.composite_hash || b.scenario_id!==id.scenario_id
      || !selected.sources_uses?.has_run || !selected.sources_uses.has_financing_evidence)
    return deny('Selected financing source identity differs.');
  if (!sameDebtPeriods(e,r)) return deny('Sealed repayment evidence differs.');
  for (const key of ['total_sources','total_uses'] as const) {
    const su=rawAmount(selected.sources_uses[key]),credit:unknown=r.structure[key]?.v;
    if (su===null || !numeric(credit) || su!==credit)
      return deny('Selected source total differs: '+key);
  }
  if (s.freshness!==before.freshness.state || c.freshness!==before.freshness.state)
    return deny('Freshness race.');
  if (row.is_last) {
    const state=b.state;
    if ((state!=='CURRENT' && state!=='STALE') || id.state!=='LAST RUN · '+state
        || s.freshness!==state || !before.identity
        || before.identity.snapshot_id!==id.snapshot_id || before.identity.composite_hash!==id.composite_hash
        || before.identity.ran_at!==id.ran_at || id.scenario_id!==scope.scenarioId
        || !s.sources_uses.available || !s.sources_uses.view?.has_run
        || !s.sources_uses.view.has_financing_evidence || s.sources_uses.view.run_kind!=='LAST_RUN'
        || s.sources_uses.view.freshness!==state)
      return deny('Last Run anchor or freshness differs.');
    if (state==='CURRENT' && s.identity.content_hash!==id.composite_hash)
      return deny('Current Run content hash differs.');
    for(const key of ['total_sources','total_uses'] as const) {
      if (rawAmount(s.sources_uses.view[key])!==rawAmount(selected.sources_uses[key]))
        return deny('Studio Last Run mismatch: '+key);
    }
    return {state,showRun:true,reason:state==='STALE'
      ? 'STALE — committed Last Run; Working Copy changed.'
      : 'CURRENT — selected Last Run matches Working Copy.',assurance:'MITIGATED_NOT_PROVEN'};
  }
  if (b.state!=='HISTORICAL' || id.state!=='HISTORICAL'
      || selected.sources_uses.run_kind!=='HISTORICAL_RUN'
      || selected.sources_uses.freshness!=='HISTORICAL') return deny('Historical state differs.');
  return {state:'HISTORICAL',showRun:true,
    reason:'HISTORICAL — selected committed Run; Working Copy is separate.',
    assurance:'MITIGATED_NOT_PROVEN'};
}
