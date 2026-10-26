import assert from 'node:assert/strict';
import test from 'node:test';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';
import { build } from 'esbuild';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';

// Fixtures below exercise rendering only; they are never imported by product code.
const output = await mkdtemp(join(tmpdir(), 'finco-insights-test-'));
await build({ stdin: { contents: `export * from './index'; export * from './presentation';`,
  resolveDir: new URL('..', import.meta.url).pathname, loader: 'ts' },
  bundle: true, outfile: join(output, 'insights.mjs'), format: 'esm', platform: 'node',
  packages: 'external', loader: { '.css': 'empty' }, jsx: 'automatic' });
// External React must resolve against the existing frontend dependencies.
const { symlink } = await import('node:fs/promises');
await symlink(new URL('../../../../node_modules', import.meta.url).pathname, join(output, 'node_modules'));
const ui = await import(pathToFileURL(join(output, 'insights.mjs')));
test.after(() => rm(output, { recursive: true, force: true }));
const identity = { history_id: 'hist-a', snapshot_id: 'snapshot-a', scenario_id: 'scenario-a', scenario: 'Committed A',
  ran_at: '2026-01-02T12:00:00Z', composite_hash: 'composite-a', engine_version: 'engine-v1', workbook_version: 'workbook-v1', state: 'HISTORICAL' };
const run = { identity, links: { statements: '/v2/workbook/run-history/statements?project=P&history_id=hist-a' } };
const metric = { key: 'debt', label: 'Senior debt', raw_value: 1234.56789, display_value: '1,235 kEUR',
  unit: 'kEUR', availability: 'available', source: 'runtime_summary.senior_debt_keur', reason: '', period: 'AGGREGATE',
  history_id: 'hist-a', snapshot_id: 'snapshot-a', scenario_id: 'scenario-a' };
const render = (Component, props) => renderToStaticMarkup(React.createElement(Component, props));

test('money display uses persisted numeric precision, while canonical ratio/percent precision is preserved', () => {
  assert.equal(ui.evidenceDisplay(1234.56789, '1,235 kEUR', 'kEUR'), '1,234.57');
  assert.equal(ui.evidenceDisplay(1.236, '1.24x', 'x'), '1.24x');
  assert.equal(ui.evidenceDisplay(0.0851, '8.51%', '%'), '8.51%');
  assert.equal(ui.evidenceDisplay(null, '0', 'kEUR'), 'Unavailable');
  assert.equal(ui.evidenceDisplay(0, '0', 'kEUR'), '0.00');
});
test('geometry preserves negative/zero persisted values, breaks missing intervals, and never parses display labels', () => {
  const geometry = ui.timelineGeometry([{ v: -4, d: '999' }, { v: 0, d: 'missing' }, { v: null, d: '999' }, { v: 8, d: '0' }]);
  assert.deepEqual(geometry.points.map(point => point?.value ?? null), [-4, 0, null, 8]);
  assert.equal(geometry.segments.length, 2);
  assert.equal(geometry.min, -4); assert.equal(geometry.max, 8);
  assert.ok(geometry.points[0].y > geometry.zeroY);
  assert.ok(geometry.points[3].y < geometry.zeroY);
  assert.ok(ui.timelineGeometry([{ v: 0, d: '0' }]).points.every(point => Number.isFinite(point.y)));
});
test('metric cards preserve full selected identity and unavailable PLCR remains unavailable', () => {
  const html = render(ui.MetricCards, { project: 'P', run, metrics: [metric,
    { ...metric, key: 'plcr', label: 'PLCR', raw_value: null, display_value: '—', unit: 'x', reason: 'PLCR authority unavailable.' }] });
  assert.match(html, /1,234.57/); assert.match(html, /snapshot-a/); assert.match(html, /scenario-a/);
  assert.match(html, /composite-a/); assert.match(html, /engine-v1/); assert.match(html, /PLCR authority unavailable/);
  assert.match(html, /data-available="false"/); assert.match(html, /runtime_summary.senior_debt_keur/);
});
test('timeline exposes every interval and numeric cell in a keyboard-accessible table', () => {
  const html = render(ui.CreditTimeline, { project: 'P', run, timeline: { available: true, reason: '',
    columns: [{ index: 1, date: '2026-01-01' }, { index: 2, date: null }, { index: 3, date: '2027-01-01' }],
    rows: [{ key: 'cfads', label: 'CFADS', kind: 'keur', link: 'statements',
      cells: [{ v: -2.123, d: '-2' }, { v: null, d: '—', reason: 'Not persisted' }, { v: 0, d: '0' }] }] } });
  assert.match(html, /role="img"/); assert.match(html, /<table/); assert.match(html, /tabindex="0"/);
  assert.match(html, /Date unavailable/); assert.match(html, /Not persisted/); assert.match(html, /data-numeric-value="-2.123"/);
  assert.match(html, /0.00/); assert.match(html, /Annual presentation unavailable/);
});
test('historical selector requires explicit selection and distinguishes scenarios with no committed Run', () => {
  const history = { project: { code: 'P', project_id: 'project-a', name: 'Project' }, working_copy: { freshness: 'STALE' },
    max_runs: 3, history: [run], scenarios: [{ scenario_id: 'unrun', name: 'Unrun', committed_run: null, availability: 'not_run' }], history_limit: 25, scenarios_complete: true };
  const html = render(ui.HistoricalRunSelector, { history, selected: [], onChange() {}, onRead() {} });
  assert.match(html, /No committed Run exists for this scenario/); assert.match(html, /disabled=""/);
  assert.doesNotMatch(html, /checked=""/); assert.match(html, /historical does not mean stale/);
  const otherProject = { project: { project_id: 'other' }, runs: [{ identity }], comparison: { columns: [], rows: [] }, credit: {} };
  const rejected = render(ui.FinancialInsightsView, { history, payload: otherProject, selected: ['hist-a'], onSelection() {}, onRead() {} });
  assert.doesNotMatch(rejected, /Committed Run KPI comparison/);
});
test('comparison displays canonical server deltas without browser subtraction', () => {
  const payload = { project: { name: 'Project' }, comparison: { columns: [identity, { ...identity, history_id: 'hist-b' }], rows: [
    { key: 'irr', label: 'Project IRR', unit: '%', values: ['8.00%', '9.00%'], raw_values: [.08, .09],
      availability: ['available', 'available'], deltas: ['—', 'CANONICAL CHANGE'], source: 'approved comparison' }] } };
  const html = render(ui.ScenarioComparison, { payload });
  assert.match(html, /CANONICAL CHANGE/); assert.match(html, /hist-a/); assert.match(html, /hist-b/);
});
test('evidence links accept local canonical paths only', () => {
  assert.equal(ui.evidenceHref('/v2/workbook?project=P'), '/v2/workbook?project=P');
  for (const path of ['https://elsewhere.test', '//elsewhere.test', 'javascript:alert(1)', '/v2/\\elsewhere', '/v2/\nsecret']) assert.equal(ui.evidenceHref(path), undefined);
});
test('client is GET-only, uncached, explicit, and never substitutes a scenario for a history ID', async () => {
  const original = globalThis.fetch;
  const requests = [];
  globalThis.fetch = async (url, options) => { requests.push({ url, options }); return { ok: true, status: 200, json: async () => ({ ok: true }) }; };
  try {
    const invalid = await ui.fetchInsights('P', []); assert.equal(invalid.ok, false); assert.equal(requests.length, 0);
    await ui.fetchInsights('P & secret', ['hist-a', 'hist-b']);
    assert.match(requests[0].url, /run=hist-a&run=hist-b/);
    assert.equal(requests[0].options.method, 'GET'); assert.equal(requests[0].options.cache, 'no-store');
    assert.equal(requests[0].options.credentials, 'same-origin');
    await ui.fetchInsights('P', ['a', 'a']); assert.equal(requests.length, 1);
  } finally { globalThis.fetch = original; }
});

test('approved sponsor and distribution columns preserve negative, zero, missing, repeated periods and stored dates', () => {
  const scheduleRun = { ...run, sponsor: {
    sponsor_source: 'RuntimeResult.sponsor_schedule.periods', distribution_source: 'RuntimeResult.distribution_schedule.periods',
    sponsor_rows: [{ period: 0, date: '2025-01-01', share_capital_contribution_keur: -10.125,
      share_premium_contribution_keur: 0, other_committed_equity_contribution_keur: 2.5,
      additional_equity_contribution_keur: null, shl_cash_interest_receipt_keur: 3.5, shl_principal_receipt_keur: 4.5,
      legal_equity_distribution_keur: 5.5 }, { period: 0, date: '2025-07-01' }],
    distribution_rows: [{ period: 0, date: '2025-07-01', distribution_keur: 0, cum_distribution_keur: 1,
      cf_after_reserves_keur: -2, dsra_balance_keur: 3, dsra_contribution_keur: 4,
      mra_balance_keur: 5, mra_contribution_keur: null, lockup_active: true }, { period: 1, lockup_active: false }],
  } };
  const html = render(ui.SponsorSchedules, { run: scheduleRun });
  for (const label of ['Other committed equity', 'SHL cash interest received', 'SHL principal received', 'Legal equity distribution',
    'Cumulative distribution', 'DSRA contribution', 'MRA balance', 'MRA contribution', 'Lock-up']) assert.ok(html.includes(label));
  for (const value of ['(10.13)', '0.00', '2.50', 'Unavailable', '2025-01-01', '2025-07-01', 'Active', 'Open']) assert.ok(html.includes(value));
  assert.doesNotMatch(html, /construction|operations/); assert.match(html, /<th scope="row">0<\/th>/);
  assert.match(html, /hist-a/); assert.match(html, /RuntimeResult.sponsor_schedule.periods/);
});

test('canonical percent and ratio card values carry exactly one unit suffix', () => {
  const html = render(ui.MetricCards, { project: 'P', run, metrics: [
    { ...metric, key: 'irr', label: 'Project IRR', raw_value: .08, display_value: '8.00%', unit: '%' },
    { ...metric, key: 'dscr', label: 'DSCR', raw_value: 1.5, display_value: '1.50x', unit: 'x' },
  ] });
  assert.match(html, /8.00%/); assert.match(html, /1.50x/);
  assert.doesNotMatch(html, /8.00% <small>%|1.50x <small>x/);
  assert.equal(ui.evidenceUnitLabel(.08, '8.00%', '%'), '');
  assert.equal(ui.evidenceUnitLabel(1.5, '1.50x', 'ratio'), '');
});


test('unknown scenario evidence never becomes a verified no-Run assertion', () => {
  const history = { project: { code: 'P', project_id: 'project-a', name: 'Project' }, working_copy: { freshness: 'STALE' },
    max_runs: 3, history: [], scenarios: [{ scenario_id: 'unknown', name: 'Unknown scenario', committed_run: null,
      availability: 'unavailable', reason: 'Committed Run identity could not be verified.' }], history_limit: 25, scenarios_complete: true };
  const html = render(ui.HistoricalRunSelector, { history, selected: [], onChange() {}, onRead() {} });
  assert.match(html, /Committed Run evidence unavailable/);
  assert.match(html, /Committed Run identity could not be verified/);
  assert.doesNotMatch(html, /No committed Run exists for this scenario/);
});
