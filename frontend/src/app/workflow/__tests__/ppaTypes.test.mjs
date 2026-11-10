import assert from 'node:assert/strict';
import test from 'node:test';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';
import { build } from 'esbuild';
const output = await mkdtemp(join(tmpdir(), 'finco-ppa-types-'));
await build({ entryPoints: [new URL('../ModelWorkflowValidation.ts', import.meta.url).pathname], bundle: true, outfile: join(output, 'v.mjs'), format: 'esm', platform: 'node' });
const V = await import(pathToFileURL(join(output, 'v.mjs')));
test.after(() => rm(output, { recursive: true, force: true }));

const stream = (o = {}) => ({ id: 'ppa-a', type: 'ppa', start_date: '2030-01-01', end_date: '2035-01-01', volume_share: '0.6', price_eur_mwh: '60', indexation_rate: '0', source_ref: 'x', capture_rate: '', curve: null, isNew: false, ...o });
const RAW = JSON.stringify({ version: 2, technology: 'solar', indexation_basis: 'OPERATING_YEAR', unknown_top: { keep: 1 }, streams: [
  { id: 'ppa-a', type: 'ppa', start_date: '2030-01-01', end_date: '2035-01-01', volume_share: 0.6, price_eur_mwh: 60, indexation_rate: 0, settlement: 'SAME_PERIOD', source_ref: 'x', extra_key: 'k' },
  { id: 'ppa-b', type: 'ppa', start_date: '2035-01-01', end_date: '2040-01-01', volume_share: 0.6, price_eur_mwh: 55, indexation_rate: 0.02, settlement: 'SAME_PERIOD', source_ref: 'y', index_series: [{ a: 1 }], price_rounding: { mode: 'x' } },
  { id: 'cfd-1', type: 'cfd', start_date: '2030-01-01', end_date: '2035-01-01', volume_share: 0.3, price_eur_mwh: 50, indexation_rate: 0, settlement: 'SAME_PERIOD', source_ref: 'z', reference_stream_id: 'm-1' },
  { id: 'm-1', type: 'merchant', start_date: '2030-01-01', end_date: '2040-01-01', volume_share: null, price_eur_mwh: 30, indexation_rate: 0, settlement: 'SAME_PERIOD', source_ref: 'm', capture_rate: 0.9 }] });

test('a plain Fixed or Indexed PPA may switch between the two; the scheduled option needs a version-2 book', () => {
  const fixed = V.ppaTypeState(stream(), [], 2);
  assert.equal(fixed.value, 'fixed'); assert.equal(fixed.editable, true); assert.ok(fixed.allowed.indexed.ok && fixed.allowed.scheduled.ok);
  assert.equal(V.ppaTypeState(stream({ indexation_rate: '0.02' }), [], 2).value, 'indexed');
  assert.equal(V.ppaTypeState(stream(), [], 2, true).value, 'indexed');                      // chosen, rate still to be entered
  const v1 = V.ppaTypeState(stream(), [], 1);
  assert.equal(v1.allowed.scheduled.ok, false); assert.match(v1.allowed.scheduled.reason, /version-2/);
});

test('protected price terms, curves and non-PPA streams keep their type read-only with a reason', () => {
  for (const preserved of [['index_series'], ['indexation_timing'], ['price_rounding']]) {
    const s = V.ppaTypeState(stream({ indexation_rate: '0.02' }), preserved, 2);
    assert.equal(s.editable, false); assert.match(s.reason, /preserved read-only/);
    assert.equal(V.applyPpaType(stream({ indexation_rate: '0.02' }), preserved, 2, 'fixed'), null);
  }
  const curve = stream({ curve: [{ period_start: '2030-01-01', price_eur_mwh: '60' }] });
  assert.equal(V.ppaTypeState(curve, [], 2).editable, false); assert.equal(V.applyPpaType(curve, [], 2, 'fixed'), null);
  for (const type of ['merchant', 'cfd']) { const s = V.ppaTypeState(stream({ type }), [], 2); assert.equal(s.value, null); assert.equal(s.editable, false); }
});

test('choosing a type only patches existing scalar/curve fields; Indexed patches nothing and never invents a rate', () => {
  assert.deepEqual(V.applyPpaType(stream({ indexation_rate: '0.02' }), [], 2, 'fixed'), { indexation_rate: '0' });
  assert.deepEqual(V.applyPpaType(stream(), [], 2, 'indexed'), {});
  assert.deepEqual(V.applyPpaType(stream(), [], 2, 'scheduled'), { curve: [{ period_start: '2030-01-01', price_eur_mwh: '60' }], indexation_rate: '0' });
  assert.equal(V.applyPpaType(stream(), [], 1, 'scheduled'), null);
});

test('no unavailable option can be selected or serialised: no cap, tier or volume key ever reaches the payload', () => {
  assert.ok(V.PPA_TYPE_UNAVAILABLE.some((u) => /Base \+ Reduced/.test(u.label) && /Awaiting approved volume-cap economics and numerical proof/.test(u.reason)));
  const parsed = V.parseContractModel(RAW); assert.ok(parsed.ok);
  const model = parsed.model; model.streams[0] = { ...model.streams[0], ...V.applyPpaType(model.streams[0], model.preservedKeys[0], model.version, 'scheduled') };
  const out = JSON.parse(V.buildContractPayload(RAW, model));
  const keys = new Set(out.streams.flatMap((s) => Object.keys(s)));
  for (const forbidden of ['cap', 'cap_mwh', 'cap_gwh', 'cap_unit', 'cap_window', 'cap_kind', 'volume_tiers', 'tier', 'reduced_price_eur_mwh']) assert.ok(!keys.has(forbidden), forbidden);
});

test('Duplicate copies only a plain PPA with a new unique identity; protected, curve and non-PPA streams are never cloned', () => {
  const parsed = V.parseContractModel(RAW); const m = parsed.model;
  const copy = V.duplicatePpa(m.streams, m.streams[0], m.preservedKeys[0]);
  assert.equal(copy.id, 'ppa-a-copy'); assert.equal(copy.isNew, true); assert.equal(copy.source_ref, ''); assert.equal(copy.price_eur_mwh, '60');
  assert.equal(V.duplicatePpa([...m.streams, copy], m.streams[0], m.preservedKeys[0]).id, 'ppa-a-copy-2');
  assert.equal(V.duplicatePpa(m.streams, m.streams[1], m.preservedKeys[1]), null);          // preserved index series / rounding
  assert.equal(V.duplicatePpa(m.streams, m.streams[2], m.preservedKeys[2]), null);          // CfD
  assert.equal(V.duplicatePpa(m.streams, m.streams[3], m.preservedKeys[3]), null);          // merchant
  assert.equal(V.duplicatePpa(m.streams, stream({ curve: [{ period_start: '2030-01-01', price_eur_mwh: '60' }] }), []), null);
});

test('merchant, CfD, unknown keys, index series and rounding are byte-identical after a type change and a duplicate', () => {
  const parsed = V.parseContractModel(RAW); const m = parsed.model;
  m.streams[0] = { ...m.streams[0], indexation_rate: '0.03' };
  const dup = V.duplicatePpa(m.streams, m.streams[0], m.preservedKeys[0]); m.streams.push({ ...dup, source_ref: 'Entered in FINCO workspace' }); m.preservedKeys.push([]);
  const before = JSON.parse(RAW), after = JSON.parse(V.buildContractPayload(RAW, m));
  assert.deepEqual(after.unknown_top, before.unknown_top); assert.equal(after.streams[0].extra_key, 'k');
  for (const i of [1, 2, 3]) assert.deepEqual(after.streams[i], before.streams[i]);          // ppa-b (index series, rounding), CfD, merchant: untouched
  assert.equal(after.streams.length, 5); assert.equal(after.streams[4].id, 'ppa-a-copy'); assert.equal(after.streams[0].indexation_rate, 0.03);
});

test('the summary is numbers-first and shows residual / missing values honestly, never zero', () => {
  assert.equal(V.streamSummary(stream(), 'Fixed'), 'Fixed · 60% · 60 €/MWh · 2030-01-01 → 2035-01-01');
  assert.match(V.streamSummary(stream({ volume_share: '', price_eur_mwh: '', start_date: '' }), 'Merchant'), /residual · no tariff · \? →/);
});
