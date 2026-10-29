import assert from 'node:assert/strict';
import test from 'node:test';
import { mkdtemp, rm, symlink } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';
import { build } from 'esbuild';

// WS-2: the pure editing modules (percent transform, pending-edit store, grid keyboard/paste, Save All request).
const output = await mkdtemp(join(tmpdir(), 'finco-editing-test-'));
await build({
  stdin: {
    contents: `export * as P from './percent'; export * as D from './decimal'; export * as S from './pendingEdits'; export * as G from './grid'; export * as A from './saveAll'; export * as N from './saveAllApi'; export * as Q from './ppaStaging'; export * as SS from './saveAllSession';`,
    resolveDir: new URL('..', import.meta.url).pathname, loader: 'ts',
  },
  bundle: true, outfile: join(output, 'editing.mjs'), format: 'esm', platform: 'node',
});
const { P, D, S, G, A, N, Q, SS } = await import(pathToFileURL(join(output, 'editing.mjs')));
test.after(() => rm(output, { recursive: true, force: true }));

// ── M-013: PPA percent <-> canonical ratio ──
test('2 UI => 0.02 canonical => 2 UI, and 100 UI => 1 => 100', () => {
  const two = P.toCanonical('2');
  assert.equal(two.ok, true); assert.equal(two.canonical, '0.02'); assert.equal(P.toDisplay(two.canonical), '2');
  const hundred = P.toCanonical('100');
  assert.equal(hundred.canonical, '1'); assert.equal(P.toDisplay('1'), '100');
  assert.equal(P.toCanonical('0').canonical, '0'); assert.equal(P.toDisplay('0'), '0');
});
test('exact decimals: no binary floating point artefacts', () => {
  for (const [ui, ratio] of [['2.5', '0.025'], ['12.345', '0.12345'], ['0.1', '0.001'], ['33.33', '0.3333'], ['0.07', '0.0007'], ['99.99', '0.9999']]) {
    assert.equal(P.toCanonical(ui).canonical, ratio); assert.equal(P.toDisplay(ratio), ui);
  }
});
test('trailing percent sign, locale comma and padding are accepted once', () => {
  assert.equal(P.toCanonical('2 %').canonical, '0.02');
  assert.equal(P.toCanonical('2,5').canonical, '0.025');
  assert.equal(P.toCanonical(' 02.50 ').canonical, '0.025');
  assert.equal(P.toCanonical('2.5', '.').canonical, '0.025');
});
test('range and format errors are typed, never coerced', () => {
  assert.equal(P.toCanonical('100.01').code, 'ABOVE_100');
  assert.equal(P.toCanonical('-1').code, 'NEGATIVE');
  assert.equal(P.toCanonical('').code, 'EMPTY');
  assert.equal(P.toCanonical('abc').code, 'NOT_A_NUMBER');
  assert.equal(P.toCanonical('1,234,5').code, 'AMBIGUOUS_SEPARATOR');
  assert.equal(P.toCanonical('-0').ok, true);
});
test('canonical values with exponents or trailing zeros display correctly; out-of-range ratios do not', () => {
  assert.equal(P.toDisplay('1e-2'), '1'); assert.equal(P.toDisplay('0.020'), '2'); assert.equal(P.toDisplay('0.0'), '0');
  assert.equal(P.toDisplay('1.5'), null); assert.equal(P.toDisplay('-0.1'), null); assert.equal(P.toDisplay('x'), null);
  assert.equal(P.sameRatio('0.020', '0.02'), true); assert.equal(P.sameRatio('0.02', '0.03'), false);
});
test('round trip is stable for every 0.01% step (no double conversion drift)', () => {
  for (let n = 0; n <= 10000; n += 1) {
    const ui = (n / 100).toFixed(2).replace(/\.?0+$/, '') || '0';
    const c = P.toCanonical(ui);
    assert.equal(c.ok, true, ui);
    assert.equal(P.toDisplay(c.canonical), ui, ui);
  }
});

// ── decimal parsing ──
test('decimal separators', () => {
  const f = (t, s) => { const r = D.parseDecimal(t, s); return r.ok ? D.formatDecimal(r) : r.reason; };
  assert.equal(f('1,234.50'), '1234.5'); assert.equal(f('1.234,50'), '1234.5'); assert.equal(f('1,234,567'), '1234567');
  assert.equal(f('1,234', '.'), '1234'); assert.equal(f('1,234', ','), '1.234'); assert.equal(f('1 234,5', ','), '1234.5');
  assert.equal(f('1,23,4'), 'ambiguous'); assert.equal(f('1e3'), '1000'); assert.equal(f('1.5e-3'), '0.0015'); assert.equal(f('x'), 'format'); assert.equal(f(''), 'empty');
});

// ── M-007/M-010: grid keyboard ──
const grid = {
  columns: ['amount', 'infl'],
  rows: [
    { id: 'r0', editable: { amount: true, infl: true } },
    { id: 'r1', editable: { amount: false, infl: false } },          // derived row
    { id: 'r2', editable: { amount: true, infl: false } },
    { id: 'r3', editable: { amount: true, infl: true } },
  ],
};
const key = (k, extra = {}) => ({ key: k, shiftKey: false, altKey: false, ctrlKey: false, metaKey: false, target: { tagName: 'INPUT', type: 'text' }, ...extra });
test('Enter / ArrowDown go to the next editable row in the same column; ArrowUp / Shift+Enter go back', () => {
  assert.deepEqual(G.navigate(grid, { row: 0, col: 0 }, key('Enter')), { kind: 'move', to: { row: 2, col: 0 } });
  assert.deepEqual(G.navigate(grid, { row: 0, col: 0 }, key('ArrowDown')), { kind: 'move', to: { row: 2, col: 0 } });
  assert.deepEqual(G.navigate(grid, { row: 0, col: 1 }, key('Enter')), { kind: 'move', to: { row: 3, col: 1 } });  // skips readonly infl in r2
  assert.deepEqual(G.navigate(grid, { row: 3, col: 0 }, key('ArrowUp')), { kind: 'move', to: { row: 2, col: 0 } });
  assert.deepEqual(G.navigate(grid, { row: 3, col: 0 }, key('Enter', { shiftKey: true })), { kind: 'move', to: { row: 2, col: 0 } });
  assert.deepEqual(G.navigate(grid, { row: 3, col: 0 }, key('Enter')), { kind: 'stay' });
});
test('Tab / Shift+Tab traverse editable cells in reading order and never trap focus', () => {
  assert.deepEqual(G.navigate(grid, { row: 0, col: 0 }, key('Tab')), { kind: 'move', to: { row: 0, col: 1 } });
  assert.deepEqual(G.navigate(grid, { row: 0, col: 1 }, key('Tab')), { kind: 'move', to: { row: 2, col: 0 } });
  assert.deepEqual(G.navigate(grid, { row: 2, col: 0 }, key('Tab', { shiftKey: true })), { kind: 'move', to: { row: 0, col: 1 } });
  assert.deepEqual(G.navigate(grid, { row: 3, col: 1 }, key('Tab')), { kind: 'none' });
  assert.deepEqual(G.navigate(grid, { row: 0, col: 0 }, key('Tab', { shiftKey: true })), { kind: 'none' });
});
test('Escape cancels; IME, modifiers, selects, textareas and date inputs are never hijacked', () => {
  assert.deepEqual(G.navigate(grid, { row: 0, col: 0 }, key('Escape')), { kind: 'cancel' });
  for (const ev of [key('Enter', { isComposing: true }), key('Enter', { keyCode: 229 }), key('ArrowDown', { ctrlKey: true }), key('Enter', { altKey: true }), key('ArrowUp', { metaKey: true }),
    key('Enter', { target: { tagName: 'SELECT' } }), key('ArrowDown', { target: { tagName: 'TEXTAREA' } }), key('Enter', { target: { tagName: 'INPUT', type: 'date' } }),
    key('Enter', { target: { tagName: 'DIV', isContentEditable: true } }), key('ArrowDown', { shiftKey: true })]) {
    assert.deepEqual(G.navigate(grid, { row: 0, col: 0 }, ev), { kind: 'none' }, JSON.stringify(ev));
  }
});

// ── TSV paste ──
test('TSV parsing: CRLF, trailing newline, quoted cells with tabs/newlines/quotes', () => {
  assert.deepEqual(G.parseTsv('1\t2\r\n3\t4\r\n'), [['1', '2'], ['3', '4']]);
  assert.deepEqual(G.parseTsv('a\n\nb'), [['a'], [''], ['b']]);
  assert.deepEqual(G.parseTsv('"x\ty"\t"say ""hi"""\n"l1\nl2"'), [['x\ty', 'say "hi"'], ['l1\nl2']]);
  assert.deepEqual(G.parseTsv('7'), [['7']]);
  assert.deepEqual(G.parseTsv(''), []);
});
test('paste plan is all-or-nothing, validates type/range/read-only/bounds, and leaves no partial result', () => {
  const v = { amount: G.numberValidator({ min: 0 }), infl: G.numberValidator({ min: 0, max: 100 }) };
  const ok = G.planPaste(grid, { row: 2, col: 0 }, [['1,250.5'], ['(0)']], v);
  assert.equal(ok.ok, true);
  assert.deepEqual(ok.assignments.map((a) => [a.rowId, a.colId, a.value]), [['r2', 'amount', '1250.5'], ['r3', 'amount', '0']]);
  const wide = G.planPaste(grid, { row: 0, col: 0 }, [['10', '2'], ['11', '3']], v);       // lands on derived r1
  assert.equal(wide.ok, false); assert.match(wide.errors[0].message, /read-only/);
  const bad = G.planPaste(grid, { row: 2, col: 0 }, [['5'], ['abc']], v);
  assert.equal(bad.ok, false); assert.equal(bad.errors.length, 1); assert.equal(bad.errors[0].rowId, 'r3');
  const tooLong = G.planPaste(grid, { row: 3, col: 0 }, [['1'], ['2']], v);
  assert.equal(tooLong.ok, false);
  const neg = G.planPaste(grid, { row: 0, col: 0 }, [['-5']], v);
  assert.equal(neg.ok, false); assert.match(neg.errors[0].message, /negative/);
  const range = G.planPaste(grid, { row: 0, col: 1 }, [['101']], v);
  assert.equal(range.ok, false);
});
test('numberValidator: units, currency decoration, decimals', () => {
  const n = G.numberValidator({ allowNegative: true, maxDecimals: 2 });
  assert.deepEqual(n('€ 1,000'), { ok: true, value: '1000' });
  assert.deepEqual(n('(1,000.50) kEUR'), { ok: true, value: '-1000.5' });
  assert.equal(n('1.005').ok, false); assert.equal(n('').ok, false); assert.equal(n('1e999').ok, false);
});

// ── M-008: pending-edit store ──
const identity = { projectId: 'p1', workbookVersion: 'v2', contentHash: 'h1', activeScenario: null, lastRunSnapshotId: 's1' };
const stageIn = (key, value, baseline = '100', extra = {}) => ({ section: 'capex', key, label: key, unit: 'kEUR', baseline, value, ...extra });
const run = (state, ...actions) => actions.reduce(S.pendingReducer, state);
test('staging records old/new, counts per section, and equal-to-baseline clears the edit', () => {
  let s = S.initialState(identity);
  s = run(s, { type: 'stage', edit: stageIn('a#amount', '150') }, { type: 'stage', edit: { ...stageIn('f1', '2', '1'), section: 'inputs' } });
  assert.deepEqual(S.countBySection(s), { inputs: 1, ppa: 0, capex: 1, opex: 0, financing: 0 });
  assert.equal(S.totalCount(s), 2);
  s = run(s, { type: 'stage', edit: stageIn('a#amount', '100') });
  assert.equal(S.totalCount(s), 1);
});
test('undo / redo, keystroke coalescing and one-step paste', () => {
  let s = S.initialState(identity);
  s = run(s, { type: 'stage', edit: stageIn('a#amount', '1'), coalesce: true }, { type: 'stage', edit: stageIn('a#amount', '12'), coalesce: true }, { type: 'stage', edit: stageIn('a#amount', '123'), coalesce: true });
  assert.equal(s.past.length, 1);                     // three keystrokes, ONE undo step
  s = run(s, { type: 'undo' }); assert.equal(S.totalCount(s), 0);
  s = run(s, { type: 'redo' }); assert.equal(s.edits['capex:a#amount'].value, '123');
  s = run(s, { type: 'stageMany', edits: [stageIn('b#amount', '1'), stageIn('c#amount', '2'), stageIn('d#amount', '3')] });
  assert.equal(S.totalCount(s), 4);
  s = run(s, { type: 'undo' }); assert.equal(S.totalCount(s), 1);   // the whole paste is one step
  s = run(s, { type: 'stage', edit: stageIn('z#amount', '9') }); assert.equal(s.future.length, 0);   // a new edit clears redo
});
test('per-field revert, section revert, discard all; documents follow their section', () => {
  let s = S.initialState(identity);
  s = run(s, { type: 'stage', edit: stageIn('a#amount', '1') }, { type: 'stage', edit: { ...stageIn('x', '2'), section: 'ppa' } }, { type: 'document', section: 'ppa', json: '{"v":2}' });
  assert.equal(s.documents.ppa, '{"v":2}');
  s = run(s, { type: 'revert', id: 'ppa:x' }); assert.equal(s.documents.ppa, undefined); assert.equal(S.totalCount(s), 1);
  s = run(s, { type: 'stage', edit: stageIn('b#amount', '3') }, { type: 'revertSection', section: 'capex' }); assert.equal(S.totalCount(s), 0);
  s = run(s, { type: 'stage', edit: stageIn('a#amount', '1') }, { type: 'discardAll' }); assert.equal(S.totalCount(s), 0);
  s = run(s, { type: 'undo' }); assert.equal(S.totalCount(s), 1);   // discard is itself undoable
});
test('rebase marks moved baselines and scope changes as conflicts; it never rebases silently and blocks Save All', () => {
  let s = S.initialState(identity);
  s = run(s, { type: 'stage', edit: stageIn('a#amount', '150', '100', { rowVersion: 'rv1' }) });
  const moved = run(s, { type: 'rebase', identity: { ...identity, contentHash: 'h2' }, baselines: { 'capex:a#amount': { value: '120', rowVersion: 'rv2' } } });
  assert.equal(moved.edits['capex:a#amount'].conflict.code, 'CHANGED_ELSEWHERE');
  assert.equal(moved.edits['capex:a#amount'].value, '150');
  assert.equal(moved.edits['capex:a#amount'].baseline, '100');
  assert.match(S.blockingReason(moved), /changed elsewhere/);
  const same = run(s, { type: 'rebase', identity: { ...identity, contentHash: 'h2' }, baselines: { 'capex:a#amount': { value: '100', rowVersion: 'rv1' } } });
  assert.equal(same.edits['capex:a#amount'].conflict, undefined);
  const scenario = run(s, { type: 'rebase', identity: { ...identity, activeScenario: 'sc2' }, baselines: {} });
  assert.equal(scenario.edits['capex:a#amount'].conflict.code, 'SCOPE_CHANGED');
});
test('invalid drafts stay visible and block; committed drops exactly the saved edits and the history', () => {
  let s = S.initialState(identity);
  s = run(s, { type: 'stage', edit: stageIn('a#amount', 'abc', '100', { error: 'Not a number.' }) }, { type: 'stage', edit: stageIn('b#amount', '5') });
  assert.equal(S.invalid(s).length, 1); assert.match(S.blockingReason(s), /invalid/);
  s = run(s, { type: 'committed', ids: ['capex:b#amount'], identity: { ...identity, contentHash: 'h3' } });
  assert.equal(S.totalCount(s), 1); assert.equal(s.identity.contentHash, 'h3'); assert.equal(s.past.length, 0);
  assert.equal(S.blockingReason(S.initialState(identity)), 'There are no pending changes.');
});

// ── Save All request / availability ──
test('Save All is BLOCKED unless the server publishes the capability; never a sequence of per-section calls', () => {
  assert.equal(A.saveAllAvailability(null).state, 'blocked');
  assert.equal(A.saveAllAvailability({ available: false }).state, 'blocked');
  assert.equal(A.saveAllAvailability({ available: true, url: '/x' }).state, 'blocked');          // no CSRF token
  assert.deepEqual(A.saveAllAvailability({ available: true, url: '/v2/x', csrf_token: 't' }), { state: 'available', url: '/v2/x', csrfToken: 't' });
  assert.match(A.saveAllAvailability(undefined).reason, /Financial Owner/);
});
test('Save All builds ONE request: scalar cells, one merged cost line per row, PPA document; refuses invalid/conflicted/foreign state', () => {
  let s = S.initialState(identity);
  const line = (key, value, baseline, extra = {}) => ({ section: 'opex', key, label: 'O&M', unit: 'kEUR', baseline, value, rowVersion: 'rv9', meta: { label: 'O&M contract', amount_keur: baseline }, ...extra });
  s = run(s,
    { type: 'stage', edit: { section: 'inputs', key: 'project_setup.capacity', label: 'Capacity', unit: 'MW', baseline: '10', value: '12' } },
    { type: 'stage', edit: { section: 'financing', key: 'debt.senior.interest_rate_pct', label: 'Rate', unit: '%', baseline: '5', value: '5.5' } },
    { type: 'stage', edit: line('L1#amount', '900', '800') }, { type: 'stage', edit: line('L1#inflation', '2.5', '2') },
    { type: 'stage', edit: { section: 'ppa', key: 's1:indexation_rate', label: 'Indexation', unit: '%', baseline: '2', value: '3', canonical: '0.03' } },
    { type: 'document', section: 'ppa', json: '{"version":2}' });
  const built = A.buildSaveAllRequest(s, identity, 'tok', 'req-1');
  assert.equal(built.ok, true);
  assert.deepEqual(built.request.cells, [{ field_id: 'project_setup.capacity', value: '12' }, { field_id: 'debt.senior.interest_rate_pct', value: '5.5' }]);
  assert.deepEqual(built.request.cost_lines, [{ kind: 'opex', sub_line_id: 'L1', label: 'O&M contract', amount_keur: '900', row_version: 'rv9', inflation_pct: '2.5' }]);
  assert.equal(built.request.contracts_json, '{"version":2}');
  assert.equal(built.request.request_id, 'req-1'); assert.equal(built.request.content_hash, 'h1'); assert.equal(built.request.scenario_id, null);
  const withoutDoc = run(s, { type: 'document', section: 'ppa', json: null });
  assert.equal(A.buildSaveAllRequest(withoutDoc, identity, 't', 'r').ok, false);
  assert.equal(A.buildSaveAllRequest(run(s, { type: 'markRejected', conflicts: { 'opex:L1#amount': { code: 'SERVER_REJECTED', message: 'x' } } }), identity, 't', 'r').ok, false);
  assert.equal(A.buildSaveAllRequest(s, { ...identity, contentHash: 'other' }, 't', 'r').ok, false);
  assert.equal(A.buildSaveAllRequest(S.initialState(identity), identity, 't', 'r').ok, false);
  const bad = run(S.initialState(identity), { type: 'stage', edit: stageIn('q#amount', 'x', '1', { error: 'bad' }) });
  assert.equal(A.buildSaveAllRequest(bad, identity, 't', 'r').ok, false);
});

// ── F3 limitation and the Save All HTTP adapter ──
test('pending Financing-collection edits are never claimed as saved: they block Save All with an explicit reason', () => {
  let s = S.initialState(identity);
  s = run(s, { type: 'stage', edit: { section: 'financing', key: 'debt.financing.instruments', label: 'Capital stack', unit: '', baseline: '[]', value: '[1]' } },
    { type: 'stage', edit: stageIn('a#amount', '5') });
  assert.equal(S.unsupported(s).length, 1);
  assert.match(S.blockingReason(s), /Financing collections/);
  const built = A.buildSaveAllRequest(s, identity, 't', 'r');
  assert.equal(built.ok, false); assert.match(built.reason, /not included in Save All/);
});
const fakeFetch = (status, body, throws = false) => async () => { if (throws) throw new Error('offline'); return { ok: status < 300, status, json: async () => { if (body === undefined) throw new Error('bad json'); return body; } }; };
const req = { project: 'p', csrf_token: 't', workbook_version: 'v', content_hash: 'h', scenario_id: null, request_id: 'req-12345678', cells: [], contracts_json: null, cost_lines: [] };
test('Save All outcomes: saved, stale, rejected with per-line conflicts, unknown (safe idempotent retry)', async () => {
  assert.deepEqual(await N.postSaveAll('/x', req, fakeFetch(200, { ok: true, content_hash: 'h2', run_state: 'STALE' })), { kind: 'saved', contentHash: 'h2', runState: 'STALE', savedIds: [] });
  assert.equal((await N.postSaveAll('/x', req, fakeFetch(409, { ok: false, code: 'STALE_CONTENT', reload: true, message: 'm' }))).kind, 'stale');
  const rej = await N.postSaveAll('/x', req, fakeFetch(409, { ok: false, code: 'COST_BATCH_CONFLICT', message: 'm', lines: [{ ok: false, kind: 'capex', sub_line_id: 'L1', message: 'stale row' }, { ok: true, kind: 'opex', sub_line_id: 'L2' }] }));
  assert.equal(rej.kind, 'rejected'); assert.deepEqual(Object.keys(rej.conflicts), ['capex:L1#amount']);
  assert.equal((await N.postSaveAll('/x', req, fakeFetch(422, { ok: false, code: 'FIELD_INVALID', message: 'bad' }))).kind, 'rejected');
  assert.equal((await N.postSaveAll('/x', req, fakeFetch(0, null, true))).kind, 'unknown');
  assert.equal((await N.postSaveAll('/x', req, fakeFetch(502, undefined))).kind, 'unknown');
  assert.equal((await N.postSaveAll('/x', req, fakeFetch(401, undefined))).kind, 'rejected');
});

// ── Save All attempt bookkeeping: an id follows ONE exact body ──
test('request id is reused only while the body is identical (CSRF refresh does not change it); an edit starts a new id', async () => {
  const { build } = await import('esbuild');
  const { mkdtemp } = await import('node:fs/promises');
  const out = await mkdtemp(join(tmpdir(), 'finco-session-'));
  await build({ entryPoints: [new URL('../saveAllSession.ts', import.meta.url).pathname], bundle: true, outfile: join(out, 's.mjs'), format: 'esm', platform: 'node' });
  const { createSaveAllSession } = await import(pathToFileURL(join(out, 's.mjs')));
  const base = { project: 'p', csrf_token: 't1', workbook_version: 'v', content_hash: 'h', scenario_id: null, request_id: 'x', cells: [{ field_id: 'a', value: '1' }], contracts_json: null, cost_lines: [] };
  let n = 0; const mk = () => `id-${++n}`;
  const s = createSaveAllSession();
  const first = s.next(base, mk);
  assert.equal(first.request_id, 'id-1');
  assert.equal(s.next({ ...base, csrf_token: 't2' }, mk).request_id, 'id-1');            // unknown outcome retried unchanged
  assert.equal(s.next({ ...base, cells: [{ field_id: 'a', value: '2' }] }, mk).request_id, 'id-2');   // edited body => new id
  s.settle();
  assert.equal(s.next(base, mk).request_id, 'id-3');                                     // after a definitive outcome
  await rm(out, { recursive: true, force: true });
});

// ── WS-2 integration: PPA document staging, replaceSection, request-id discipline ──
const stream = (over = {}) => ({ id: 'ppa-1', type: 'ppa', start_date: '2027-01-01', end_date: '2037-01-01', volume_share: '0.8', price_eur_mwh: '60', indexation_rate: '0.02', source_ref: 'PPA 1', capture_rate: '', curve: null, isNew: false, ...over });
const model = (streams) => ({ version: 2, technology: 'solar', streams, preservedKeys: streams.map(() => []) });
test('PPA percent edits are listed as human percent with the exact canonical ratio', () => {
  const inputs = Q.ppaStageInputs(model([stream()]), model([stream({ volume_share: '1', indexation_rate: '0.025' })]));
  const vol = inputs.find((e) => e.key === 'ppa-1:volume_share'), idx = inputs.find((e) => e.key === 'ppa-1:indexation_rate');
  assert.deepEqual([vol.baseline, vol.value, vol.canonical], ['80', '100', '1']);
  assert.deepEqual([idx.baseline, idx.value, idx.canonical], ['2', '2.5', '0.025']);
  assert.equal(inputs.length, 2);
});
test('PPA: unchanged draft stages nothing; added and removed contracts are listed', () => {
  assert.equal(Q.ppaStageInputs(model([stream()]), model([stream()])).length, 0);
  const added = Q.ppaStageInputs(model([stream()]), model([stream(), stream({ id: 'ppa-2', isNew: true })]));
  assert.equal(added.length, 1); assert.match(added[0].label, /added/);
  const removed = Q.ppaStageInputs(model([stream(), stream({ id: 'ppa-2' })]), model([stream()]));
  assert.equal(removed.length, 1); assert.match(removed[0].label, /removed/);
});
test('replaceSection states a section exactly, is one coalesced undo step, and is a no-op when identical', () => {
  const id = { projectId: 'p', workbookVersion: 'v', contentHash: 'h', activeScenario: null, lastRunSnapshotId: null };
  let st = S.initialState(id);
  const input = (value) => ({ section: 'ppa', key: 'ppa-1:volume_share', label: 'x', unit: '%', baseline: '80', value, canonical: '1' });
  st = S.pendingReducer(st, { type: 'replaceSection', section: 'ppa', edits: [input('100')] });
  st = S.pendingReducer(st, { type: 'document', section: 'ppa', json: '{"a":1}' });
  const same = S.pendingReducer(st, { type: 'replaceSection', section: 'ppa', edits: [input('100')] });
  assert.equal(same, st);
  const next = S.pendingReducer(st, { type: 'replaceSection', section: 'ppa', edits: [input('90')] });
  assert.equal(next.past.length, st.past.length);                       // coalesced with the previous step
  const cleared = S.pendingReducer(next, { type: 'replaceSection', section: 'ppa', edits: [] });
  assert.equal(S.totalCount(cleared), 0); assert.equal(cleared.documents.ppa, undefined);
});
test('request id follows the body: identical body keeps the id, any change gets a new one', () => {
  const session = SS.createSaveAllSession();
  const body = { project: 'p', csrf_token: 'c1', workbook_version: 'v', content_hash: 'h', scenario_id: null, request_id: '', cells: [{ field_id: 'a', value: '1' }], contracts_json: null, cost_lines: [] };
  let n = 0; const mint = () => `id-${++n}`;
  const first = session.next(body, mint);
  assert.equal(session.next({ ...body, csrf_token: 'c2' }, mint).request_id, first.request_id);   // token is not part of the meaning
  assert.notEqual(session.next({ ...body, cells: [{ field_id: 'a', value: '2' }] }, mint).request_id, first.request_id);
});
