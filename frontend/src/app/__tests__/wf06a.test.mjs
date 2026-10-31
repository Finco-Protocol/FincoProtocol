import assert from 'node:assert/strict';
import test from 'node:test';
import { mkdtemp, rm, symlink } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';
import { build } from 'esbuild';

// WF-06A: pure presentation contracts (Save All guide copy, Run failure classification, DSCR units, cost group labels).
const output = await mkdtemp(join(tmpdir(), 'finco-wf06a-test-'));
await build({ stdin: { contents: `export { classifyRunFailure } from './RunFailureNotice'; export { SAVE_ALL_INCLUDES, SAVE_ALL_EXCLUDES } from './InputsGuide';
  export { costGroupLabel } from './workflow/CostLineManager'; export { reportMetric, reportCell, reportEvidence } from './reportFormatting';
  export { SAVE_ALL_EXCLUDED_KEYS } from './editing/pendingEdits'; export { buildSaveAllRequest, saveAllAvailability } from './editing/saveAll';`,
  resolveDir: new URL('..', import.meta.url).pathname, loader: 'ts' },
  bundle: true, outfile: join(output, 'wf06a.mjs'), format: 'esm', platform: 'node', packages: 'external', loader: { '.css': 'empty' }, jsx: 'automatic' });
await symlink(new URL('../../../node_modules', import.meta.url).pathname, join(output, 'node_modules'));
const W = await import(pathToFileURL(join(output, 'wf06a.mjs')));
test.after(() => rm(output, { recursive: true, force: true }));

test('Save All guide copy matches the actual request contract and exclusions', () => {
  assert.match(W.SAVE_ALL_INCLUDES, /cells/); assert.match(W.SAVE_ALL_INCLUDES, /CAPEX and OPEX lines/); assert.match(W.SAVE_ALL_INCLUDES, /PPA/);
  assert.match(W.SAVE_ALL_EXCLUDES, /Financing collections/);
  assert.deepEqual([...W.SAVE_ALL_EXCLUDED_KEYS].sort(), ['debt.financing.instruments', 'revenue.multistream.contracts']);
  // the guide never reports an unadvertised capability as active
  assert.equal(W.saveAllAvailability(null).state, 'blocked');
  assert.equal(W.saveAllAvailability({ available: false, reason: 'read-only' }).state, 'blocked');
});

test('run failures: constraint refusals are never retryable, transient ones are, and every link is a real workspace anchor', () => {
  const real = new Set(['#inputs', '#inputs/project', '#financing', '#diagnostics']);
  const cases = [
    ['SHL_MATURITY_RESIDUAL_FAILS_CLOSED', 'These inputs leave part of the shareholder loan unpaid at its maturity', 'SHL', false],
    ['FINANCIAL_REFUSED', 'The shareholder loan still has an unpaid balance at maturity.', 'SHL', false],
    ['ENGINE_FAILED', 'Base cash cannot pay the contractual Senior service (Reference: F3_CONTRACTUAL_SERVICE_CASH_SHORTFALL)', 'FINANCING', false],
    ['ENGINE_FAILED', 'SHL maturity is not on the PERIOD_GRID', 'TIMELINE', false],
    ['ADMISSION_REFUSED', 'Calculation capacity is currently busy.', 'TRANSIENT', true],
    ['ENGINE_TIMEOUT', 'The calculation took too long and was stopped.', 'TRANSIENT', true],
    ['FINAL_CAS_CONFLICT', 'The workbook changed while the model was running.', 'CONFLICT', true],
    ['ENGINE_FAILED', 'The model\'s integrity checks stopped this run for the current inputs', 'REFUSED', false],
    ['FINANCIAL_REFUSED', 'The Run could not be completed or saved.', 'REFUSED', false],
    ['ENGINE_FAILED', 'Engine run failed — please try again or contact support.', 'EXECUTION', false],
    [undefined, 'The saved inputs are incomplete', 'INPUTS', false],
  ];
  for (const [code, message, kind, retryable] of cases) {
    const view = W.classifyRunFailure(code, message);
    assert.equal(view.kind, kind, `${code} ${message}`); assert.equal(view.retryable, retryable, `${code} ${message}`);
    assert.ok(view.links.length > 0 && view.links.every((link) => real.has(link.href)), `${kind} links`);
    assert.ok(view.guidance.length > 20);
  }
  // a refusal never tells the user to retry blindly; a DSCR/covenant finding is not a failure kind at all
  assert.doesNotMatch(W.classifyRunFailure('FINANCIAL_REFUSED', 'x').guidance, /safe to choose Run model again/);
  assert.doesNotMatch(W.classifyRunFailure('ENGINE_FAILED', 'x').guidance, /safe to choose Run model again/);
});

test('DSCR and other ratios never acquire a money suffix and never round a breach up to 1.00x', () => {
  assert.equal(W.reportMetric('1.25x', 'kEUR', 0), '1.25x');
  assert.equal(W.reportMetric('7.35%', 'kEUR', 0), '7.35%');
  assert.equal(W.reportCell('1.00', { kind: 'ratio' }, 'kEUR', 0, 0.9999), '0.9999x');
  assert.equal(W.reportCell('1.00', { kind: 'ratio' }, 'mEUR', 3, 1.0), '1.00x');
  assert.equal(W.reportEvidence(0.9996, '1.00x', 'Minimum DSCR', 0), '0.9996x');
  assert.match(W.reportMetric('1,234 kEUR', 'kEUR', 0), /kEUR$/);
});

test('calculated cost groups are named; unknown codes are shown as received, never invented', () => {
  const eligible = [{ code: 'C.01', label: 'C.01 Production Units' }];
  assert.equal(W.costGroupLabel('C.01', eligible), 'C.01 Production Units');
  assert.equal(W.costGroupLabel('C.13', eligible), 'C.13 Contingency');
  assert.equal(W.costGroupLabel('B.13', []), 'B.13 Contingencies');
  assert.equal(W.costGroupLabel('C.99', eligible), 'C.99');
});
