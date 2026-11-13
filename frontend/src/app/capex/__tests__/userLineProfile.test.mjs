// C06 — a line the user added (C.NN.U###) is an ordinary profile row: the browser sends exactly the key the server's item list names and decides nothing.
import assert from 'node:assert/strict';
import test from 'node:test';
import { readFile, mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';
import { build } from 'esbuild';

const output = await mkdtemp(join(tmpdir(), 'finco-c06-'));
const bundle = async (entry, name) => {
  await build({ entryPoints: [new URL(entry, import.meta.url).pathname], bundle: true, outfile: join(output, name), format: 'esm', platform: 'node' });
  return import(pathToFileURL(join(output, name)));
};
const D = await bundle('../profileDraft.ts', 'draft.mjs');
const A = await bundle('../api.ts', 'api.mjs');
const F = await bundle('../profileFocus.ts', 'focus.mjs');
test.after(() => rm(output, { recursive: true, force: true }));

const USER = 'C.02.U001';
const NATIVE = 'C.02.01';
const src = (rel) => readFile(new URL(rel, import.meta.url), 'utf8');

test('an added-line key stays a classified key but is a normal draft row: it reaches the wire and the D7 document verbatim', () => {
  assert.equal(F.isUserLineKey(USER), true);
  assert.equal(F.isUserLineKey(NATIVE), false);
  const draft = { [USER]: { ...D.emptyProfileRow(), shape: 'FRONT_LOADED' }, [NATIVE]: D.emptyProfileRow() };
  const wire = D.wireProfileDraft([USER, NATIVE], draft);
  assert.deepEqual(wire[USER], { shape: 'FRONT_LOADED', explicit: '', milestone: '' });
  const doc = JSON.parse(D.profileD7Document([USER, NATIVE], draft));
  assert.deepEqual(doc, { version: 1, profiles: [{ item_key: USER, shape: 'FRONT_LOADED', explicit_percent: [], milestone_month: null }] });
  assert.ok(A.encodeSpec([USER, NATIVE], wire).includes(USER));
});

test('explicit percentages for an added line follow the same exact month-count and 100 % rules as a native line', () => {
  const months = 14;
  const row = (values) => ({ shape: 'EXPLICIT', explicit: { kind: 'cells', values }, milestone: '' });
  const ok = Array.from({ length: months }, (_, i) => (i === 2 ? '37.5' : i === 9 ? '62.5' : '0'));
  assert.deepEqual(D.rowProblems(row(ok), months, ['EXPLICIT']), []);
  assert.notDeepEqual(D.rowProblems(row(['50', '50']), months, ['EXPLICIT']), []);                  // wrong month count
  assert.notDeepEqual(D.rowProblems(row(ok.map((v, i) => (i === 2 ? '40' : v))), months, ['EXPLICIT']), []);   // does not sum to 100
});

test('the browser no longer withholds profile editing from added lines, and says truthfully what happens when one is retired', async () => {
  const provider = await src('../ProfileDraftProvider.tsx');
  const grid = await src('../../editing/CostLinesGridView.tsx');
  const editor = await src('../ProfileRowEditor.tsx');
  assert.ok(!provider.includes('isUserLineKey'), 'bulk apply, clear and editable must not special-case added lines');
  assert.ok(!/isUserLineKey\(profileKey\(line\)\)/.test(grid) && !grid.includes('profiles on added lines are not released') && !grid.includes('data-profile-user-line'));
  assert.ok(!editor.includes('profile editing for added lines is not available'));
  assert.ok(editor.includes('the next Run stops until that profile is cleared'));      // the replayed server behaviour (CAPEX_PROFILE_LEAF_UNKNOWN)
});

test('OPEX years: the inline series is read-only and says why individual years cannot be edited (no annual writer exists)', async () => {
  const grid = await src('../../editing/CostLinesGridView.tsx');
  assert.ok(grid.includes('data-opex-years-edit="canonical-writer-missing"'));
  assert.ok(grid.includes('a saved line holds only a Year-1 amount and one escalation rate'));
  assert.ok(grid.includes('This is not Last Run all-in OPEX'));
  assert.ok(!/data-opex-year-input|opexYearEdit|setOpexYear/.test(grid), 'no annual editor may exist without a canonical writer');
});
