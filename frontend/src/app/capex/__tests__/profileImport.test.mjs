import assert from 'node:assert/strict';
import test from 'node:test';
import { mkdtemp, rm, symlink } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';
import { build } from 'esbuild';

// PR-U2a (owner D14): Import % parsing and the exact contract check. Synthetic inputs only.
const output = await mkdtemp(join(tmpdir(), 'finco-u2-import-'));
await build({ stdin: { contents: `export * from './profileImport'; export * from './profileFocus';`, resolveDir: new URL('..', import.meta.url).pathname, loader: 'ts' },
  bundle: true, outfile: join(output, 'import.mjs'), format: 'esm', platform: 'node', packages: 'external' });
await symlink(new URL('../../../../node_modules', import.meta.url).pathname, join(output, 'node_modules'));
const P = await import(pathToFileURL(join(output, 'import.mjs')));
test.after(() => rm(output, { recursive: true, force: true }));

const ok = (text, mode) => { const r = P.parsePercentages(text, mode); assert.equal(r.status, 'ok', JSON.stringify(r)); return r.values; };

test('Excel row, Excel column, CSV with semicolons and % signs parse to the typed digits', () => {
  assert.deepEqual(ok('10\t20\t70'), ['10', '20', '70']);
  assert.deepEqual(ok('10\r\n20\r\n70\r\n'), ['10', '20', '70']);
  assert.deepEqual(ok('10%;20 %;70%'), ['10', '20', '70']);
  assert.deepEqual(ok('﻿12.5\t87.5'), ['12.5', '87.5']);
});

test('a decimal comma is read only where it cannot be a separator', () => {
  assert.deepEqual(ok('12,5\t87,5'), ['12.5', '87.5']);              // Excel row from a decimal-comma locale
  assert.deepEqual(ok('12,5\n87,5'), ['12.5', '87.5']);
  assert.deepEqual(ok('12,5 87,5'), ['12.5', '87.5']);               // space separated
  assert.deepEqual(ok('12.5,87.5'), ['12.5', '87.5']);               // points + comma list
  assert.deepEqual(ok('10, 20, 70'), ['10', '20', '70']);            // comma + space list
});

test('ambiguous comma text is never guessed; the user resolves it', () => {
  for (const t of ['12,5', '10,20,70']) assert.equal(P.parsePercentages(t).status, 'ambiguous');
  assert.deepEqual(ok('12,5', 'decimal'), ['12.5']);
  assert.deepEqual(ok('12,5', 'separator'), ['12', '5']);
  assert.deepEqual(ok('10,20,70', 'separator'), ['10', '20', '70']);
  assert.equal(P.parsePercentages('10,20,70', 'decimal').status, 'error');
});

test('negative, NaN, text and thousands-style input are refused with the month named', () => {
  assert.match(P.parsePercentages('50\t-10\t60').message, /negative/);
  for (const t of ['NaN\t100', 'abc;100', '1e2', '50\tInfinity']) assert.equal(P.parsePercentages(t).status, 'error', t);
  assert.match(P.parsePercentages('50\t5O').message, /Month 2/);
});

test('exact check: exactly N values, total 100 % within the contract tolerance, never rounded', () => {
  assert.equal(P.checkExplicit(['100'], 1).ok, true);                                    // 1-month construction
  assert.equal(P.checkExplicit(Array(12).fill('8.333333333333333333'), 12).ok, true);    // 99.999999999999999996: inside the server tolerance (1e-7 points)
  assert.equal(P.checkExplicit(Array(12).fill('8.3333333'), 12).ok, false);              // 99.9999996: 4e-7 points short -> refused, as the server would
  assert.equal(P.checkExplicit(['33.33333333', '33.33333333', '33.33333334'], 3).ok, true);
  assert.equal(P.checkExplicit(['33.33', '33.33', '33.33'], 3).ok, false);
  const low = P.checkExplicit(['50', '49.99'], 2); assert.equal(low.ok, false); assert.equal(low.difference, '0.01'); assert.match(low.problems[0], /missing 0\.01 %/);
  const high = P.checkExplicit(['50', '50.01'], 2); assert.match(high.problems[0], /over by 0\.01 %/);
  assert.match(P.checkExplicit(['50', '50'], 3).problems[0], /exactly 3 needed/);
  assert.match(P.checkExplicit(['50', '50', '0', '0'], 3).problems[0], /4 values for 3/);
  assert.equal(P.checkExplicit(['0', '100', '0'], 3).ok, true);                          // zero weights are allowed
  assert.equal(P.checkExplicit(Array(24).fill('0').map((v, i) => (i === 23 ? '100' : v)), 24).ok, true);
  assert.equal(P.checkExplicit(Array(36).fill('2.7777777777777777777778'), 36).ok, true);
  assert.equal(P.checkExplicit(['-1', '101'], 2).ok, false);
});

test('stale length is detected and only explicit corrections are offered', () => {
  assert.equal(P.staleness('EXPLICIT', '50,50', '', 3), 'too_few');
  assert.equal(P.staleness('EXPLICIT', '50,50,0,0', '', 3), 'too_many');
  assert.equal(P.staleness('MILESTONE', '', '20', 12), 'milestone_out_of_range');
  assert.equal(P.staleness('UNIFORM', '', '', 1), 'none');
  assert.equal(P.padWithZeros('50,50', 4), '50,50,0,0');
  assert.equal(P.trimTrailingZeros('50,50,0,0', 2), '50,50');
  assert.equal(P.trimTrailingZeros('50,40,10', 2), null);                                 // would drop money: not offered
  assert.equal(P.padWithZeros('50,50', 2), null);
});

test('one month box: a comma is a decimal comma', () => {
  assert.equal(P.parseOneMonth('12,5'), '12.5');
  assert.equal(P.parseOneMonth('12.5 %'), '12.5');
  assert.equal(P.parseOneMonth('-3'), null);
  assert.equal(P.isUserLineKey('C.05.U001'), true);
  assert.equal(P.isUserLineKey('C.05.01'), false);
});
