import { useCallback, useEffect, useRef, useState } from 'react';
import { fetchSheetFields, fetchWorkspace } from '../../api';
import { useOptionalChanges } from '../../editing/ChangesProvider';
import { postSaveAll } from '../../editing/saveAllApi';
import type { SaveAllRequest } from '../../editing/saveAll';
import type { SheetFieldsPayload } from '../../types';
import { useReportDirty, useReportPending, useSingleFlight, useUnresolvedLock } from '../../workflow/workflowShared';
import { BankabilityEditor } from '../BankabilityEditor';
import { fetchFinancingStudio } from '../financingApi';
import type { FinancingStudioPayload } from '../types';
import { BLOCKS, blockOf, buildBlockRequest, canEdit, structured, type Block, type EditingWorkspace } from './blockContract';
import './financingEditing.css';
import { validateSheetField } from '../../workflow/SheetFieldsEditor';
import type { SheetFieldPayload } from '../../types';
// UX-FINAL-01: unit beside its label, and as many field columns as fit (4 at desktop, 1 on a phone) — presentation only, no stylesheet change.
const CAPTION = { display: 'flex', flexWrap: 'wrap', alignItems: 'baseline', gap: '.1rem .4rem', fontWeight: 600 } as const;
const FIELD_GRID = { gridTemplateColumns: 'repeat(auto-fit, minmax(16rem, 1fr))', gap: '.45rem .8rem' } as const;

type SavedRead = { workspace: EditingWorkspace; fields: SheetFieldsPayload; studio: FinancingStudioPayload };
type Phase = 'clean' | 'dirty' | 'saving' | 'saved' | 'error' | 'stale';
/** Existing writers only. Drafts use the shell's ONE scalar store and existing leave guard. */
export function FinancingEditing({ project, scenarioId, reloadKey, onSaved }: {
  project: string; scenarioId: string | null; reloadKey: number; onSaved: () => void;
}) {
  const store = useOptionalChanges();
  const [read, setRead] = useState<SavedRead | null>(null), [loading, setLoading] = useState(true);
  const [notice, setNotice] = useState(''), [phase, setPhase] = useState<Partial<Record<Block, Phase>>>({});
  const [busy, setBusy] = useState<Block | null>(null);
  const [unknown, setUnknown] = useState<{ block: Block; url: string; request: SaveAllRequest } | null>(null);
  const [locked, setLocked] = useUnresolvedLock('sheet-debt-inline');
  const flight = useSingleFlight(), generation = useRef(0), live = useRef(true);
  const storeRef = useRef(store); storeRef.current = store;
  useEffect(() => { live.current = true; return () => { live.current = false; generation.current++; }; }, []);
  const load = useCallback(async () => {
    const mine = ++generation.current;setLoading(true);
    try {
      const w = await fetchWorkspace(project);
      const [fields, studio] = await Promise.all([fetchSheetFields(project, 'debt'), fetchFinancingStudio(project)]);
      const fence = await fetchWorkspace(project);
      if (!w.ok || !fence.ok || !fields.ok || !studio.ok || w.project.code !== project || fence.project.code !== project
        || fields.project.code !== project || studio.project.code !== project || w.workbook.scenario_id !== scenarioId
        || fence.workbook.scenario_id !== scenarioId || studio.identity.scenario_id !== scenarioId
        || w.workbook.composite_hash !== fence.workbook.composite_hash || fields.save.content_hash !== fence.workbook.composite_hash
        || studio.identity.content_hash !== fence.workbook.composite_hash) throw new Error('Saved inputs changed or are unavailable. Reload to refresh.');
      if (!live.current || mine !== generation.current) return null;
      const next = { workspace: fence as EditingWorkspace, fields, studio };setRead(next);
      const st = storeRef.current;
      if (st) st.rebase({ projectId: project, activeScenario: scenarioId, workbookVersion: fence.workbook.version,
        contentHash: fence.workbook.composite_hash, lastRunSnapshotId: fence.identity?.snapshot_id ?? null },
      Object.fromEntries(st.edits.filter(e => e.section === 'financing').map(e => [e.id, { value: String(fields.fields.find(f => f.field_id === e.key)?.value ?? '') }])));
      return next;
    } catch (e) { if (live.current && mine === generation.current) setNotice(e instanceof Error ? e.message : 'Read unavailable.');return null; }
    finally { if (live.current && mine === generation.current) setLoading(false); }
  }, [project, scenarioId]);
  useEffect(() => { void load(); }, [load, reloadKey]);
  const edits = store?.edits.filter(e => e.section === 'financing' && read?.fields.fields.some(f => f.field_id === e.key)) ?? [];
  useReportDirty('sheet-debt-inline', edits.length);
  useReportPending('sheet-debt-inline', busy !== null || locked);
  const commit = async (block: Block, url: string, request: SaveAllRequest) => {
    const result = await postSaveAll(url, request);
    if (!live.current) return;
    if (result.kind === 'unknown') {
      setUnknown({ block, url, request });setLocked(true);setPhase(p => ({ ...p, [block]: 'error' }));setNotice(result.message);return;
    }
    setUnknown(null);setLocked(false);
    if (result.kind !== 'saved') { setPhase(p => ({ ...p, [block]: result.kind === 'stale' ? 'stale' : 'error' }));setNotice(result.message);return; }
    // Keep the draft until the authoritative read proves the intended values persisted.
    const fresh = await load();
    if (!fresh || !request.cells.every(c => {
      const f = fresh.fields.fields.find(f => f.field_id === c.field_id);
      if (!f) return false; const a = String(f.value ?? '').trim(), b = c.value.trim();
      return a === b || (a !== '' && b !== '' && Number.isFinite(Number(a)) && Number(a) === Number(b));
    })) { setLocked(true);setNotice('Save was accepted, but read-back is not proven. Draft retained; reload the workspace to reconcile.');setPhase(p => ({ ...p, [block]: 'stale' }));return; }
    const st = storeRef.current;
    st?.committed(request.cells.map(c => `financing:${c.field_id}`), { projectId: project, activeScenario: scenarioId,
      workbookVersion: fresh.workspace.workbook.version, contentHash: fresh.workspace.workbook.composite_hash,
      lastRunSnapshotId: fresh.workspace.identity?.snapshot_id ?? null });
    setPhase(p => ({ ...p, [block]: 'saved' }));setNotice(`Saved and read back: ${request.cells.map(c => fresh.fields.fields.find(f => f.field_id === c.field_id)?.label).join(', ')}. The model was not run.`);onSaved();
  };
  const save = (block: Block) => void flight(async () => {
    if (!read || !store || busy || locked || loading) return;
    setBusy(block);setPhase(p => ({ ...p, [block]: 'saving' }));setNotice('');
    try {
      const w = await fetchWorkspace(project), f = await fetchSheetFields(project, 'debt');
      if (!live.current) return;
      if (!w.ok || !f.ok) throw new Error('Save tokens unavailable. Reload saved values.');
      if (store.identity?.projectId !== project || store.identity.activeScenario !== scenarioId) throw new Error('STALE: draft scope differs. Reload and review.');
      const mine = edits.filter(e => blockOf(read.fields.fields.find(f => f.field_id === e.key)!) === block);
      const request = buildBlockRequest(w as EditingWorkspace, f, project, scenarioId, read.workspace.workbook.composite_hash, mine, `fin-${crypto.randomUUID()}`);
      await commit(block, (w as EditingWorkspace).save_all!.url!, request);
    } catch (e) { setPhase(p => ({ ...p, [block]: e instanceof Error && e.message.startsWith('STALE') ? 'stale' : 'error' }));setNotice(e instanceof Error ? e.message : 'Save unavailable; draft retained.'); }
    finally { if (live.current) setBusy(null); }
  });
  if (!read) return <section aria-label="Financing inputs"><p role="status">{loading ? 'Loading saved Financing inputs…' : notice}</p><button type="button" onClick={() => void load()}>Reload saved values</button></section>;
  const w = read.workspace, fields = read.fields;
  const disabled = loading || busy !== null || locked || !store;
  const doc = fields.fields.find(f => f.field_id === 'debt.bankability.configuration');
  const bankEditable = w.save_all?.available === true && read.studio.editable && doc?.binding_label === 'bound' && !fields.project.protected_reference;
  const stage = (f: SheetFieldPayload, value: string) => {
    store?.stage({ section: 'financing', key: f.field_id, label: f.label, unit: f.unit ?? '', baseline: String(f.value ?? ''), value,
      error: validateSheetField(f, value) ?? undefined }, { coalesce: true });
    setPhase(p => ({ ...p, [blockOf(f)]: 'dirty' }));setNotice('');
  };
  return <section className="pr3b2" aria-label="Financing inputs" data-financing-editing="true" aria-busy={loading}>
    <header><h3>Financing inputs <small>Working Copy</small></h3><button type="button" disabled={busy !== null || locked} onClick={() => void load()}>Reload saved values</button></header>
    <p className="pr3b2-note">Save each block together. Saving changes inputs only; Last Run stays historical until Run.</p>
    {notice && <p role={Object.values(phase).some(x => x === 'error' || x === 'stale') || locked ? 'alert' : 'status'}>{notice}</p>}
    {locked && !unknown && <p role="alert">A previous Save has an unresolved outcome. Reload the workspace to reconcile saved values before editing.</p>}
    {unknown && <button type="button" disabled={busy !== null} onClick={() => void flight(async () => { setBusy(unknown.block);try { await commit(unknown.block, unknown.url, unknown.request); } finally { setBusy(null); } })}>Check and retry identical Save</button>}
    {BLOCKS.map(block => {
      const fs = fields.fields.filter(f => blockOf(f) === block.id && !structured(f.field_id));
      const pending = edits.filter(e => fs.some(f => f.field_id === e.key));
      const state = phase[block.id] === 'saving' || phase[block.id] === 'stale' || phase[block.id] === 'error' ? phase[block.id] : pending.length ? 'dirty' : phase[block.id] ?? 'clean';
      return <fieldset key={block.id} data-financing-block={block.id} data-state={state} disabled={disabled}>
        <legend>{block.label} <small role="status">{state}</small></legend>
        <div className="pr3b2-fields" style={FIELD_GRID}>{fs.map(f => {
          const e = store?.get('financing', f.field_id), persisted = String(f.value ?? '');
          const foreign = !!e && (e.conflict?.code === 'SCOPE_CHANGED' || store?.identity?.projectId !== project || store.identity.activeScenario !== scenarioId);
          const value = foreign ? persisted : e?.value ?? persisted;
          return <label key={f.field_id}><span className="pr3b2-cap" style={CAPTION}>{f.label} <small id={`pr3b2-unit-${f.field_id}`}>{f.unit}</small></span>{canEdit(f, w, fields) && store ? <>
            {f.field_type === 'select' && f.options?.length ? <select disabled={foreign} aria-label={f.label} aria-describedby={`pr3b2-unit-${f.field_id}`} aria-invalid={!!e?.error} value={value} onChange={ev => stage(f, ev.target.value)}>
              {!f.options.includes(value) && <option value={value}>{value || '—'}</option>}{f.options.map(o => <option key={o} value={o}>{f.option_labels?.[o] ?? o}</option>)}</select>
              : <input disabled={foreign} aria-label={f.label} aria-describedby={`pr3b2-unit-${f.field_id}`} aria-invalid={!!e?.error} autoComplete="off" value={value} onChange={ev => stage(f, ev.target.value)} />}
            {e?.conflict && <small role="alert">{e.conflict.message}</small>}
            {e?.error && <small role="alert">{e.error}</small>}
          </> : <output>{f.display_value ?? persisted}<small>Read-only · {w.save_all?.reason || f.binding_label}. Existing editor retains its authority.</small></output>}</label>;
        })}</div>
        {!fs.length && <p>No scalar fields supplied. Use the existing facility / investor editor below.</p>}
        {fs.some(f => canEdit(f, w, fields)) && <div className="pr3b2-actions"><button type="button" disabled={!pending.length || pending.some(e => e.conflict) || disabled} onClick={() => save(block.id)}>Save {block.label}</button>
          <button type="button" disabled={!pending.length || disabled} onClick={() => { pending.forEach(e => store?.revert(e.id));setPhase(p => ({ ...p, [block.id]: 'clean' })); }}>Reset {block.label}</button>
          {pending.some(e => e.conflict) && !pending.some(e => e.conflict?.code === 'SCOPE_CHANGED') && <button type="button" disabled={disabled} onClick={() => { pending.forEach(e => { const f = fs.find(f => f.field_id === e.key)!;store?.revert(e.id);store?.stage({ section: 'financing', key: e.key, label: e.label, unit: e.unit, baseline: String(f.value ?? ''), value: e.value }); });setPhase(p => ({ ...p, [block.id]: 'dirty' })); }}>Keep my draft against these saved values</button>}</div>}
      </fieldset>;
    })}
    <details className="pr3b2-bank"><summary>Advanced · Bankability, repayment profile, fees &amp; reserves</summary>
      <p>One configuration document, one Save. These settings cannot be saved independently without changing their existing contract.</p>
      <BankabilityEditor project={project} view={read.studio.bankability} editable={bankEditable && !disabled} identityHash={read.studio.identity.content_hash}
        onSaved={() => { void load();onSaved(); }} onChanged={() => { setNotice('Saved inputs changed. Reload saved values; your bankability draft stays visible.'); }} />
    </details>
    <details><summary>Notes &amp; editing availability</summary><p>Facility collections and investor agreements use their full existing editors below. Repayment follows the selected supported sizing method; additional facility repayment controls are unavailable.</p></details>
  </section>;
}
