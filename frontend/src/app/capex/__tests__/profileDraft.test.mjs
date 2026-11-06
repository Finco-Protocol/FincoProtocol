import assert from 'node:assert/strict';
import test from 'node:test';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';
import { build } from 'esbuild';
const output = await mkdtemp(join(tmpdir(), 'finco-pr2b-draft-'));
await build({ entryPoints: [new URL('../profileDraft.ts', import.meta.url).pathname], bundle: true,
  outfile: join(output, 'draft.mjs'), format: 'esm', platform: 'node' });
const P = await import(pathToFileURL(join(output, 'draft.mjs')));
test.after(() => rm(output, { recursive: true, force: true }));
const row = values => ({ shape: 'EXPLICIT', explicit: { kind: 'cells', values }, milestone: '' });
const shapes = ['EXPLICIT', 'MILESTONE', 'UNIFORM'];
test('raw months remain exact; empty/invalid and excess cells are retained, never zero-filled or truncated', () => {
  let input = P.editMonth({ kind: 'cells', values: [] }, 2, '33.33333333333333333333');
  assert.deepEqual(input.values, ['', '', '33.33333333333333333333']);
  input = P.editMonth(input, 0, '-1'); assert.equal(input.values[0], '-1');
  assert.ok(P.rowProblems({ ...row([]), explicit: input }, 3, shapes).length);
  const pasted = P.pasteMonths({ kind: 'cells', values: [] }, 0, '0\t100\t0\t0');
  assert.equal(pasted.status, 'ok'); assert.equal(pasted.input.values.length, 4);
  assert.ok(P.rowProblems({ ...row([]), explicit: pasted.input }, 3, shapes).length);
});
test('N-1/N/N+1, non100, negatives and canonical tolerance without rounding', () => {
  assert.ok(P.rowProblems(row(['100', '0']), 3, shapes).length);
  assert.deepEqual(P.rowProblems(row(['0', '100', '0']), 3, shapes), []);
  assert.ok(P.rowProblems(row(['0', '100', '0', '0']), 3, shapes).length);
  for (const values of [['33.33', '33.33', '33.33'], ['50', '-1', '51'], ['NaN', '100', '0']])
    assert.ok(P.rowProblems(row(values), 3, shapes).length);
  const exact = ['33.33333333', '33.33333333', '33.33333334'];
  assert.deepEqual(P.rowProblems(row(exact), 3, shapes), []);
  assert.equal(P.rowToWire(row(exact)).explicit, exact.join(','));
});
test('ambiguous pasted comma needs a choice; row/column decimal-comma retain typed precision', () => {
  assert.equal(P.pasteMonths({ kind: 'cells', values: [] }, 0, '12,5').status, 'ambiguous');
  assert.deepEqual(P.pasteMonths({ kind: 'cells', values: [] }, 0, '12,5\n87,5').input.values, ['12.5', '87.5']);
  assert.equal(P.explicitValues({ kind: 'text', text: '12,5' }).status, 'ambiguous');
  assert.throws(() => P.rowToWire({ ...row([]), explicit: { kind: 'text', text: '12,5' } }));
});
test('milestone endpoints and duration changes; only server shapes accepted', () => {
  const m = milestone => ({ ...P.emptyProfileRow(), shape: 'MILESTONE', milestone });
  for (const v of ['1', '12']) assert.deepEqual(P.rowProblems(m(v), 12, shapes), []);
  for (const v of ['0', '13', '-1', '1.5', '']) assert.ok(P.rowProblems(m(v), 12, shapes).length);
  assert.ok(P.rowProblems(m('12'), 11, shapes).length);
  assert.ok(P.rowProblems({ ...m('1'), shape: 'PIK' }, 12, shapes).length);
});
test('read-back equality checks exact explicit, milestone and keys, not shapes only', () => {
  const saved = { a: { shape: 'EXPLICIT', explicit: '12.50,87.50', milestone: '' }, b: { shape: 'MILESTONE', explicit: '', milestone: '2' } };
  assert.equal(P.sameProfileDocument(saved, structuredClone(saved)), true);
  for (const change of [x => x.a.explicit = '12.5,87.5', x => x.b.milestone = '1', x => delete x.a, x => x.c = x.b]) {
    const tampered = structuredClone(saved); change(tampered); assert.equal(P.sameProfileDocument(saved, tampered), false);
  }
  assert.deepEqual(P.rowToWire({ ...row(['100']), shape: 'UNIFORM', milestone: '2' }), { shape: 'UNIFORM', explicit: '', milestone: '' });
});
