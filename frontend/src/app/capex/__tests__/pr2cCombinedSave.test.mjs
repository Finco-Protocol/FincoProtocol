// PR2c — combined CAPEX amount + monthly profile Save All: builder + store integration.
// Runs on node:test + esbuild (same harness as editing.test.mjs) with a Windows-safe
// resolveDir (fileURLToPath), so it runs locally on win32 and in the Linux CI alike.
import assert from 'node:assert/strict';
import test from 'node:test';
import { mkdtemp, rm, symlink } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { pathToFileURL, fileURLToPath } from 'node:url';
import { build } from 'esbuild';

const here = fileURLToPath(new URL('../../editing/', import.meta.url));
const output = await mkdtemp(join(tmpdir(), 'finco-pr2c-test-'));
await build({
  stdin: {
    contents: `export * as S from './saveAll'; export * as P from './pendingEdits'; export * as PD from '../capex/profileDraft'; export * as PB from '../capex/profilePublish';`,
    resolveDir: here, loader: 'ts',
  },
  bundle: true, outfile: join(output, 'pr2c.mjs'), format: 'esm', platform: 'node',
});
const { S, P, PD, PB } = await import(pathToFileURL(join(output, 'pr2c.mjs')));
test.after(() => rm(output, { recursive: true, force: true }));

const identity = { projectId: 'demo-project', workbookVersion: 'v1', contentHash: 'hash-1', activeScenario: null, lastRunSnapshotId: null };
const source = { projectId: identity.projectId, activeScenario: identity.activeScenario, contentHash: identity.contentHash, baseToken: 'profile-token-1' };

const stateWithProfile = (over = {}) => {
  let state = P.initialState(identity);
  state = P.pendingReducer(state, { type: 'stage', edit: { section: 'capex', key: 'c-12', label: 'Modules', unit: 'kEUR', baseline: '1100.000', value: '1200.000', rowVersion: 'rv-1', meta: { label: 'Modules', amount_keur: '1200.000' } } });
  state = P.pendingReducer(state, { type: 'document', section: 'profile', json: over.profileJson ?? JSON.stringify({ version: 1, profiles: [{ item_key: 'c-12', shape: 'FRONT_LOADED', explicit_percent: [], milestone_month: null }] }), source: over.source ?? source });
  // the provider stages one representative edit for its section (mirroring the PPA pattern)
  state = P.pendingReducer(state, { type: 'stage', edit: { section: 'profile', key: 'document', label: 'CAPEX monthly profile', unit: 'changes', baseline: '', value: 'staged' } });
  return state;
};

// ── builder: the combined request ──
test('combined: profile document + base token ride the ONE request with the staged line', () => {
  const built = S.buildSaveAllRequest(stateWithProfile(), identity, 'csrf-1', 'req-1');
  assert.equal(built.ok, true);
  assert.equal(built.request.profile_json, JSON.stringify({ version: 1, profiles: [{ item_key: 'c-12', shape: 'FRONT_LOADED', explicit_percent: [], milestone_month: null }] }));
  assert.equal(built.request.profile_base_token, 'profile-token-1');
  assert.equal(built.request.cost_lines.length, 1);
  assert.equal(built.request.cost_lines[0].sub_line_id, 'c-12');
  assert.equal(built.request.cost_lines[0].row_version, 'rv-1');
  assert.equal(built.request.contracts_json, null);           // no PPA mutation: never manufactured
});

test('combined: a document without the server-issued token is refused, never guessed', () => {
  let state = stateWithProfile({ source: { ...identity } });   // no baseToken
  const built = S.buildSaveAllRequest(state, identity, 'csrf-1', 'req-1');
  assert.equal(built.ok, false);
  assert.match(built.reason, /no server token/);
});

test('combined: a document serialised against an older identity is refused', () => {
  const staleSource = { projectId: identity.projectId, activeScenario: null, contentHash: 'hash-0', baseToken: 'profile-token-1' };
  const built = S.buildSaveAllRequest(stateWithProfile({ source: staleSource }), identity, 'csrf-1', 'req-1');
  assert.equal(built.ok, false);
  assert.match(built.reason, /older saved version/);
});

test('amounts only: no profile fields are manufactured', () => {
  let state = P.initialState(identity);
  state = P.pendingReducer(state, { type: 'stage', edit: { section: 'capex', key: 'c-12', label: 'Modules', unit: 'kEUR', baseline: '1100.000', value: '1200.000', rowVersion: 'rv-1', meta: { label: 'Modules', amount_keur: '1200.000' } } });
  const built = S.buildSaveAllRequest(state, identity, 'csrf-1', 'req-1');
  assert.equal(built.ok, true);
  assert.equal(built.request.profile_json, undefined);
  assert.equal(built.request.profile_base_token, undefined);
});

test('the profile staged edit alone is a submittable change (no "no pending changes" refusal)', () => {
  let state = P.initialState(identity);
  state = P.pendingReducer(state, { type: 'document', section: 'profile', json: JSON.stringify({ version: 1, profiles: [{ item_key: 'c-12', shape: 'UNIFORM', explicit_percent: [], milestone_month: null }] }), source });
  state = P.pendingReducer(state, { type: 'stage', edit: { section: 'profile', key: 'document', label: 'CAPEX monthly profile', unit: 'changes', baseline: '', value: 'staged' } });
  const built = S.buildSaveAllRequest(state, identity, 'csrf-1', 'req-1');
  assert.equal(built.ok, true);
  assert.deepEqual(JSON.parse(built.request.profile_json).profiles[0].shape, 'UNIFORM');
});

// ── store: profile is a first-class section ──
test('profile is a registered section with label and counts', () => {
  assert.ok(P.EDIT_SECTIONS.includes('profile'));
  assert.equal(P.SECTION_LABEL.profile, 'CAPEX monthly profile');
  let state = P.initialState(identity);
  state = P.pendingReducer(state, { type: 'stage', edit: { section: 'profile', key: 'document', label: 'CAPEX monthly profile', unit: 'changes', baseline: '', value: 'staged' } });
  assert.equal(P.countBySection(state).profile, 1);
});

test('pruning: the profile document lives only while its section still has edits', () => {
  let state = stateWithProfile();
  assert.equal(state.documents.profile !== undefined, true);
  state = P.pendingReducer(state, { type: 'revert', id: 'capex:c-12' });   // line reverted; profile still staged
  assert.equal(state.documents.profile !== undefined, true);
  state = P.pendingReducer(state, { type: 'revert', id: 'profile:document' });  // last profile edit gone
  assert.equal(state.documents.profile, undefined);
});

// ── D7 wire document serializer (client side of the server contract) ──
test('profileD7Document emits the exact server document shape, or null for nothing to save', () => {
  const savedRows = { 'c-12': { shape: 'EXPLICIT', explicit: '60,40', milestone: '' }, 'c-13': { shape: 'MILESTONE', explicit: '', milestone: '3' } };
  let draft = PD.profileDraftFromSaved({ items: Object.keys(savedRows).map(k => ({ item_key: k })), saved: { rows: savedRows, error: null, binding: {} } });
  const doc = JSON.parse(PD.profileD7Document(['c-12', 'c-13'], draft));
  assert.equal(doc.version, 1);
  assert.deepEqual(doc.profiles[0], { item_key: 'c-12', shape: 'EXPLICIT', explicit_percent: ['60', '40'], milestone_month: null });
  assert.deepEqual(doc.profiles[1], { item_key: 'c-13', shape: 'MILESTONE', explicit_percent: [], milestone_month: 3 });
  assert.equal(PD.profileD7Document(['c-12'], {}), null);
  // an unresolved EXPLICIT input is never serialised (throws internally -> null)
  draft = { ...draft, 'c-bad': { shape: 'EXPLICIT', explicit: '60,forty', milestone: '' } };
  assert.equal(PD.profileD7Document(['c-bad'], draft), null);
});

// ── Correction A §2B: removing profiles rides the combined path as the canonical EMPTY document ──
test('removal: clearing the final/only profile serialises the canonical EMPTY document (real removal)', () => {
  const savedRows = { 'c-12': { shape: 'UNIFORM', explicit: '', milestone: '' } };
  const baseline = PD.profileDraftFromSaved({ items: [{ item_key: 'c-12' }], saved: { rows: savedRows, error: null, binding: {} } });
  const draft = { ...baseline, 'c-12': PD.emptyProfileRow() };
  assert.deepEqual(JSON.parse(PD.profileD7Document(['c-12'], draft, baseline)), { version: 1, profiles: [] });
});

test('removal: removing some profiles keeps the remaining ones in the same document', () => {
  const savedRows = { 'c-12': { shape: 'UNIFORM', explicit: '', milestone: '' }, 'c-13': { shape: 'MILESTONE', explicit: '', milestone: '3' } };
  const baseline = PD.profileDraftFromSaved({ items: [{ item_key: 'c-12' }, { item_key: 'c-13' }], saved: { rows: savedRows, error: null, binding: {} } });
  const draft = { ...baseline, 'c-12': PD.emptyProfileRow() };
  const doc = JSON.parse(PD.profileD7Document(['c-12', 'c-13'], draft, baseline));
  assert.equal(doc.profiles.length, 1);
  assert.deepEqual(doc.profiles[0], { item_key: 'c-13', shape: 'MILESTONE', explicit_percent: [], milestone_month: 3 });
});

test('removal: an unchanged draft and a baseline-less draft never manufacture a removal document', () => {
  const savedRows = { 'c-12': { shape: 'UNIFORM', explicit: '', milestone: '' } };
  const baseline = PD.profileDraftFromSaved({ items: [{ item_key: 'c-12' }], saved: { rows: savedRows, error: null, binding: {} } });
  assert.equal(PD.profileD7Document(['c-12'], baseline, baseline), null);   // draft == saved: nothing to save
  assert.equal(PD.profileD7Document(['c-12'], {}, undefined), null);        // no baseline in evidence
});

test('removal: an invalid EXPLICIT row is a serialization error, never mistaken for an empty document', () => {
  const savedRows = { 'c-bad': { shape: 'UNIFORM', explicit: '', milestone: '' } };
  const baseline = PD.profileDraftFromSaved({ items: [{ item_key: 'c-bad' }], saved: { rows: savedRows, error: null, binding: {} } });
  const draft = { ...baseline, 'c-bad': { shape: 'EXPLICIT', explicit: { kind: 'cells', values: ['60', 'forty'] }, milestone: '' } };
  assert.equal(PD.profileD7Document(['c-bad'], draft, baseline), null);
});

// ── Correction A §2A: the completion observer's honest verdicts (pure decision machine) ──
const row = (shape, explicit = '', milestone = '') => ({ shape, explicit, milestone });
const fresh = (rows, hash, scenario = null) => ({ project: { code: 'demo-project' }, save: { content_hash: hash, scenario_id: scenario }, saved: { rows, error: null } });
const session = (hash, expected, baseline) => ({ authoredHash: hash, baseToken: 'tok-1', submission: { project: 'demo-project', scope: 'demo-project|null', expected }, baselineExpected: baseline });

test('observer: a committed combined save is proven by read-back of the exact published rows AND an advanced identity', () => {
  const expected = { 'c-12': row('UNIFORM') };
  assert.equal(PB.decideDisappearance(session('h2', expected, {}), fresh(expected, 'h3')).kind, 'committed');
});

test('observer: rows matching the published document with an UNCHANGED identity is a revert, never a commit (edited-then-undone draft)', () => {
  const baseline = { 'c-12': row('UNIFORM') };
  const s = session('h1', baseline, baseline);   // published document == baseline rows (edited, then undone back)
  assert.equal(PB.decideDisappearance(s, fresh(baseline, 'h1')).kind, 'reverted');
  assert.notEqual(PB.decideDisappearance(s, fresh(baseline, 'h1')).kind, 'committed');
});

test('observer: the empty removal document is committed when the saved profile is really gone', () => {
  assert.equal(PB.decideDisappearance(session('h2', {}, {}), fresh({}, 'h3')).kind, 'committed');
});

test('observer: same composite hash after the staged edit disappeared means an explicit revert, never a commit', () => {
  const baseline = { 'c-12': row('UNIFORM') };
  const s = session('h1', { 'c-12': row('FRONT_LOADED') }, baseline);
  assert.equal(PB.decideDisappearance(s, fresh(baseline, 'h1')).kind, 'reverted');
});

test('observer: identity advanced but the saved profile is unchanged — external clear, draft retained, no lock', () => {
  const baseline = { 'c-12': row('UNIFORM') };
  const s = session('h1', { 'c-12': row('FRONT_LOADED') }, baseline);
  assert.equal(PB.decideDisappearance(s, fresh(baseline, 'h2')).kind, 'unstaged');
});

test('observer: everything else is UNKNOWN — lock for reconciliation, never retry', () => {
  const s = session('h1', { 'c-12': row('FRONT_LOADED') }, { 'c-12': row('UNIFORM') });
  assert.equal(PB.decideDisappearance(s, fresh({ 'c-12': row('BACK_LOADED') }, 'h2')).kind, 'unknown');
  assert.equal(PB.decideDisappearance(null, fresh({}, 'h1')).kind, 'unknown');
  assert.equal(PB.decideDisappearance(s, null).kind, 'unknown');
});

test('observer: a different scope is never accepted as a commit', () => {
  const expected = { 'c-12': row('UNIFORM') };
  const s = session('h1', expected, {});
  const other = { ...fresh(expected, 'h1'), save: { content_hash: 'h1', scenario_id: 'scenario-9' } };
  assert.equal(PB.decideDisappearance(s, other).kind, 'unknown');
});

// ── Correction A §2: mounted provider context wiring (static render smoke; the live
// effects run the decision machine above) ──
const capexDir = fileURLToPath(new URL('../', import.meta.url));
await build({
  stdin: {
    contents: `export * as UI from './ProfileDraftProvider'; export * as CH from '../editing/ChangesProvider';`,
    resolveDir: capexDir, loader: 'tsx',
  },
  bundle: true, outfile: join(output, 'pr2cui.mjs'), format: 'esm', platform: 'node',
  packages: 'external', jsx: 'automatic', loader: { '.css': 'empty' },
});
await symlink(fileURLToPath(new URL('../../../../node_modules', import.meta.url)), join(output, 'node_modules'), 'junction');
const { default: React } = await import('react');
const { renderToStaticMarkup } = await import('react-dom/server');
const ui = await import(pathToFileURL(join(output, 'pr2cui.mjs')));

test('mounted provider: renders standalone without a ChangesProvider (optional context, no throw)', () => {
  const html = renderToStaticMarkup(React.createElement(ui.UI.EnsureCapexProfileDraft, { project: 'demo-project' }, React.createElement('div', { 'data-probe': 'child' })));
  assert.ok(html.includes('data-probe="child"'));
});

test('mounted provider: renders inside the workbench providers (Changes + Dirty)', () => {
  const identity = { projectId: 'demo-project', workbookVersion: 'v1', contentHash: 'hash-1', activeScenario: null, lastRunSnapshotId: null };
  const html = renderToStaticMarkup(React.createElement(ui.CH.EnsureChangesProvider, { identity },
    React.createElement(ui.UI.EnsureCapexProfileDraft, { project: 'demo-project' }, React.createElement('div', { 'data-probe': 'wired' }))));
  assert.ok(html.includes('data-probe="wired"'));
});
