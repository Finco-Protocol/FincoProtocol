import assert from 'node:assert/strict';
import test from 'node:test';
import { mkdtemp, rm, symlink } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';
import { build } from 'esbuild';

// RC-UX Addendum B: business wording is a pure mapping; stable codes are never lost.
const output = await mkdtemp(join(tmpdir(), 'finco-language-test-'));
await build({ stdin: { contents: `export * from './productLanguage'; export { splitLabelUnit } from './fieldLabel'; export { normalizePastedWeights } from './capex/CapexStudio';`,
  resolveDir: new URL('..', import.meta.url).pathname, loader: 'ts' },
  bundle: true, outfile: join(output, 'language.mjs'), format: 'esm', platform: 'node', packages: 'external', loader: { '.css': 'empty' }, jsx: 'automatic' });
await symlink(new URL('../../../node_modules', import.meta.url).pathname, join(output, 'node_modules'));
const L = await import(pathToFileURL(join(output, 'language.mjs')));
test.after(() => rm(output, { recursive: true, force: true }));

test('result freshness is business wording; unknown states never read as a result', () => {
  assert.equal(L.resultStatus('CURRENT'), 'Results up to date');
  assert.equal(L.resultStatus('STALE'), 'Results outdated');
  assert.equal(L.resultStatus('NOT_RUN'), 'Not run yet');
  assert.equal(L.resultStatus('whatever'), 'Status unavailable');
  assert.equal(L.runStateLabel('HISTORICAL'), 'Earlier Run');
  assert.equal(L.runStateLabel('LAST RUN · CURRENT'), 'Last Run · results up to date');
  assert.equal(L.runStateLabel('LAST RUN · STALE'), 'Last Run · results outdated');
});

test('internal codes become the specified business messages and the code stays available', () => {
  assert.match(L.friendlyMessage('CAS_VERSION_MISMATCH'), /updated|changed elsewhere/i);
  assert.equal(L.friendlyMessage('CAS_VERSION_MISMATCH'), 'This project was changed elsewhere. Reload the latest version before saving.');
  assert.equal(L.friendlyMessage('INVALID_COD_RELATIVE_PERIOD'),
    "The selected date is outside the project's supported financing timeline. Choose a date within the available period.");
  assert.equal(L.friendlyMessage('SCALAR_SHOCK_UNSUPPORTED'), 'This assumption cannot be adjusted in the selected financial configuration.');
  assert.equal(L.friendlyMessage('Q4_STALE_PREVIEW_CONFLICT'), 'This project was changed elsewhere. Reload the latest version before saving.');
  assert.match(L.friendlyMessage('CAPEX_PROFILE_WEIGHT_SUM_INVALID'), /100%/);
});

test('a code that merely contains the letters CAS is not a conflict', () => {
  assert.equal(L.friendlyMessage('CASH_FLOW_UNAVAILABLE', 'CASH_FLOW_UNAVAILABLE'), 'Something went wrong. Nothing was changed.');
});

test('a human server sentence is kept, a bare code or jargon is replaced, and an unknown code never reaches the user bare', () => {
  assert.equal(L.friendlyMessage('X', 'Target DSCR must be at least 1.0.'), 'Target DSCR must be at least 1.0.');
  assert.equal(L.looksTechnical('HTTP_404'), true);
  assert.equal(L.looksTechnical('INVALID_COD_RELATIVE_PERIOD'), true);
  assert.equal(L.looksTechnical('The canonical writer refused it'), true);
  assert.equal(L.looksTechnical('Enter a project name.'), false);
  assert.equal(L.friendlyMessage('SOME_UNKNOWN_CODE', 'SOME_UNKNOWN_CODE'), 'Something went wrong. Nothing was changed.');
  assert.equal(L.friendlyMessage('CAS_CONFLICT', 'HTTP_409'), 'This project was changed elsewhere. Reload the latest version before saving.');
});

test('server copy is cleaned of implementation vocabulary but financial terms are untouched', () => {
  assert.equal(L.plain('Working Copy / Base'), 'Project / Base');
  assert.equal(L.plain('Tariff (legacy key)'), 'Tariff');
  assert.equal(L.plain('Not persisted by the canonical clean sponsor schedule'), 'Not saved by the sponsor schedule');
  assert.equal(L.plain('Min DSCR 1.20x, LLCR, PLCR, IRR, NPV, PPA, CAPEX, OPEX'), 'Min DSCR 1.20x, LLCR, PLCR, IRR, NPV, PPA, CAPEX, OPEX');
  assert.equal(L.splitLabelUnit('PPA Term (legacy key)', 'years').label, 'PPA Term');
  assert.equal(L.dataSourceLabel('runtime_summary.financing_evidence.x'), 'Financing results');
  assert.equal(L.dataSourceLabel('sponsor_schedule.summary'), 'Sponsor returns');
  assert.equal(L.dataSourceLabel('debt_schedule.summary'), 'Debt schedule');
});

test('an Excel paste becomes the comma list the contract reads, without parsing or summing any number', () => {
  assert.equal(L.normalizePastedWeights('10\n20\n70'), '10,20,70');
  assert.equal(L.normalizePastedWeights('10\t20\t70'), '10,20,70');
  assert.equal(L.normalizePastedWeights('10%; 20% ;70%'), '10,20,70');
  assert.equal(L.normalizePastedWeights('  '), '');
});
