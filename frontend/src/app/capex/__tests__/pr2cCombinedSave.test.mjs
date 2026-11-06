// PR2c — combined CAPEX amount + monthly profile Save All: builder + store integration.
// Runs on node:test + esbuild (same harness as editing.test.mjs) with a Windows-safe
// resolveDir (fileURLToPath), so it runs locally on win32 and in the Linux CI alike.
import assert from 'node:assert/strict';
import test from 'node:test';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { pathToFileURL, fileURLToPath } from 'node:url';
import { build } from 'esbuild';

const here = fileURLToPath(new URL('../../editing/', import.meta.url));
const output = await mkdtemp(join(tmpdir(), 'finco-pr2c-test-'));
await build({
  stdin: {
    contents: `export * as S from './saveAll'; export * as P from './pendingEdits'; export * as PD from '../capex/profileDraft';`,
    resolveDir: here, loader: 'ts',
  },
  bundle: true, outfile: join(output, 'pr2c.mjs'), format: 'esm', platform: 'node',
});
const { S, P, PD } = await import(pathToFileURL(join(output, 'pr2c.mjs')));
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
