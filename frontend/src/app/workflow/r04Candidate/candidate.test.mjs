import assert from 'node:assert/strict';
import test from 'node:test';
import { mkdtemp, rm, symlink } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';
import { build } from 'esbuild';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { quantityIssue } from './AnnualQuantityDraft.ts';

let dir;
let Field;
test.before(async () => {
  dir = await mkdtemp(join(tmpdir(), 'r04-p2-component-'));
  await build({ entryPoints: [new URL('./AnnualQuantityCandidateField.tsx', import.meta.url).pathname],
    bundle: true, outfile: join(dir, 'component.mjs'), format: 'esm', platform: 'node',
    external: ['react'], jsx: 'automatic' });
  await symlink(new URL('../../../../node_modules', import.meta.url).pathname, join(dir, 'node_modules'), 'dir');
  ({ AnnualQuantityCandidateField: Field } = await import(pathToFileURL(join(dir, 'component.mjs'))));
});
test.after(async () => { if (dir) await rm(dir, { recursive: true, force: true }); });

test('syntax retains arbitrary decimal text without float conversion or an approved business precision', () => {
  for (const amount of ['80', '0.000000000000000000000001', '80.0000001']) assert.equal(quantityIssue({ amount, unit: 'GWh' }), null);
  for (const amount of ['0', '0.000', '-1', 'NaN', 'Infinity', '8e1', ' 80', '01']) assert.ok(quantityIssue({ amount, unit: 'GWh' }));
});

test('rendered draft keeps units and explicit production gate, without inventing an available zero', () => {
  const html = renderToStaticMarkup(React.createElement(Field, { value: { amount: '80', unit: 'GWh' }, onChange() {} }));
  assert.ok(html.includes('GWh/year') && html.includes('Save and Run are unavailable'));
  assert.ok(html.includes('No server period review is available.'));
  assert.ok(!html.includes('<dt>Available</dt>') && !html.includes('<button'));
});

test('server display is shown literally, not recalculated from the quantity draft', () => {
  const serverReview = { scope: 'DECLARED_PERIOD_DELIVERY_CAP_ONLY', annual_semantics_verified: false, production_supported: false,
    case: 'P90-10y', interval: '2028-01-01 / 2028-06-30', available: '90', allocated: '100', remaining: '-10', unit: 'GWh' };
  const html = renderToStaticMarkup(React.createElement(Field, { value: { amount: '80', unit: 'MWh' }, readOnly: true, onChange() {}, serverReview }));
  assert.ok(html.includes('P90-10y') && html.includes('-10 GWh'));
  assert.ok(html.includes('readonly=""') && html.includes('disabled=""'));
  assert.ok(html.includes('declared period quantities only') && html.includes('Save and Run are unavailable'));
});
