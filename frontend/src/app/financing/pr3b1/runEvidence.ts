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

/** Equality of existing raw evidence, never financial thresholds or tolerance arithmetic.
 * Workspace and credit bookends fence concurrent Saves/Runs; Studio still lacks snapshot_id.
 */
export function checkRunEvidence(e: Evidence): Gate {
  const deny = (detail: string): Gate => ({ state: 'UNAVAILABLE', showRun: false,
    reason: `Last Run changed — reload. ${detail}`, assurance: 'NOT_PROVEN' });
  const { scope, before, after, studio: s, credit: c, creditBefore: cb, fields } = e;
  if (!scope || !before?.project || !after?.project || !before.workbook || !after.workbook
      || !before.freshness || !after.freshness || !s?.identity || !s.project || !s.sources_uses
      || !c?.project || !cb?.project || !Array.isArray(c.history_rows) || !Array.isArray(cb.history_rows)
      || !fields?.project || !fields.save || !Array.isArray(fields.fields)
      || (c.data && !Array.isArray(c.data.runs)) || (cb.data && !Array.isArray(cb.data.runs))) return deny('Response identity or shape is missing.');
  if (![before, after, s, c, cb, fields].every(x => x.ok && x.project.code === scope.project)
      || (c.data && c.data.project_code !== scope.project) || (cb.data && cb.data.project_code !== scope.project)) return deny('Project scope differs.');
  if (anchor(before) !== anchor(after)) return deny('Workspace changed during read.');
  if (before.workbook.scenario_id !== scope.scenarioId || s.identity.scenario_id !== scope.scenarioId) return deny('Scenario scope differs.');
  if (!present(s.identity.content_hash) || s.identity.content_hash !== before.workbook.composite_hash
      || s.identity.workbook_version !== before.workbook.version || fields.save.content_hash !== s.identity.content_hash
      || fields.save.workbook_version !== s.identity.workbook_version) return deny('Working Copy identity differs.');
  const r = c.data?.runs[0];
  if (runAnchor(cb.data?.runs[0]) !== runAnchor(r) || cb.freshness !== c.freshness
      || JSON.stringify(cb.history_rows) !== JSON.stringify(c.history_rows)) return deny('Run selection changed during read.');
  const su = s.sources_uses.view;
  if (before.freshness.state === 'NOT_RUN' && s.freshness === 'NOT_RUN' && c.freshness === 'NOT_RUN'
      && !r && !before.identity && !scope.historyId && !su?.has_run) return {
    state: 'NOT_RUN', showRun: false, reason: 'NOT_RUN — no committed Last Run. Saved Sources & Uses is NOT AVAILABLE.', assurance: 'NOT_PROVEN' };
  if (!r || c.data?.runs.length !== 1) return deny('One selected Run is required.');
  const id = r.identity;
  if (!id || !r.structure || !r.capacity) return deny('Run evidence shape is missing.');
  if (![id.snapshot_id, id.history_id, id.ran_at, id.composite_hash].every(present)) return deny('Run identity is missing.');
  const last = c.history_rows.find(h => h.history_id === id.history_id);
  if (!last?.is_last || !last.selected || (scope.historyId && scope.historyId !== id.history_id)) return deny('Selected history is not the current Sources & Uses Last Run. Open Debt metrics for historical evidence.');
  if (!before.identity || before.identity.snapshot_id !== id.snapshot_id || before.identity.composite_hash !== id.composite_hash
      || before.identity.ran_at !== id.ran_at || id.scenario_id !== scope.scenarioId) return deny('Last Run scope cannot be established.');
  const state = s.freshness;
  if ((state !== 'CURRENT' && state !== 'STALE') || before.freshness.state !== state || c.freshness !== state
      || id.state !== `LAST RUN · ${state}` || !s.sources_uses.available || !su?.has_run
      || !su.has_financing_evidence || su.run_kind !== 'LAST_RUN' || su.freshness !== state) return deny(s.sources_uses.reason || su?.su_authority_gap || 'Freshness or financing evidence is unavailable.');
  if (state === 'CURRENT' && s.identity.content_hash !== id.composite_hash) return deny('Current Run hash differs.');
  for (const key of ['total_sources', 'total_uses'] as const) {
    const sv = rawAmount(su[key]); const cv: unknown = r.structure[key]?.v;
    if (sv === null || !numeric(cv) || sv !== cv) return deny(`Raw ${key} missing or different.`);
  }
  return { state, showRun: true, reason: state === 'STALE' ? 'STALE — historical Last Run; Working Copy has changed.' : 'CURRENT — Last Run inputs match Working Copy.', assurance: 'MITIGATED_NOT_PROVEN' };
}
