import assert from 'node:assert/strict';
import test from 'node:test';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, dirname } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { build } from 'esbuild';
import { synthetic } from './synthetic.mjs';
const dir = await mkdtemp(join(tmpdir(), 'f04-'));
await build({ stdin: { contents: `export {debtProvenance} from './debtProvenanceModel';`, resolveDir: dirname(fileURLToPath(new URL('../debtProvenanceModel.ts', import.meta.url))), loader: 'ts' }, outfile: join(dir, 'model.cjs'), bundle: true, platform: 'node', format: 'cjs' });
const { debtProvenance: model } = await import(pathToFileURL(join(dir, 'model.cjs')));
test.after(() => rm(dir, { recursive: true, force: true }));
function sync(e) {
  e.creditBefore = structuredClone(e.credit);
  e.studio.selected_run.view.repayment.axis = structuredClone(e.credit.data.runs[0].debt_metrics.axis);
  e.studio.selected_run.view.repayment.rows = e.credit.data.runs[0].debt_metrics.periods.map(p => ({ ...p, axis: 'RUN_DEBT_SERVICE_PERIOD' }));
  return e;
}
function fixture(state = 'CURRENT') {
  const e = synthetic(state), dm = e.credit.data.runs[0].debt_metrics;
  // Independent two-period ledger: 100 - 40 - 60 = 0; service 40+5=45, 60+3=63.
  dm.axis = { frequency: 'SEMIANNUAL', periods_per_year: 2, period_count: 2 };
  dm.periods = [{ ...dm.periods[0], period_index: 3, date: '2027-06-30', senior_opening_keur: 100, principal_keur: 40, interest_keur: 5, debt_service_keur: 45, senior_closing_keur: 60 },
    { ...dm.periods[0], period_index: 4, date: '2027-12-31', senior_opening_keur: 60, principal_keur: 60, interest_keur: 3, debt_service_keur: 63, senior_closing_keur: 0 }];
  return sync(e);
}
test('native amounts, identity, independent principal sum and immutability', () => {
  const e=fixture(), before=JSON.stringify(e), m=model(e);
  assert.equal(m.reason,'');assert.equal(m.periods.length,2);assert.deepEqual(m.periods.map(p=>p.debt_service_keur),[45,63]);
  assert.equal(m.periods.reduce((s,p)=>s+p.principal_keur,0),100);assert.equal(m.identity.history_id,'synthetic-history');assert.equal(JSON.stringify(e),before);
});
test('five concepts preserve target, sized, absent commitment, FC-only draw and closing balance', () => {
  const m=model(fixture());assert.deepEqual(m.concepts.map(c=>c.label),['Requested','Sized','Committed','Drawn','Outstanding']);
  assert.deepEqual(m.concepts.map(c=>c.value),['80.0%','70','UNAVAILABLE','0','0']);
  assert.equal(m.concepts[0].unit,'ratio displayed as %');assert.equal(m.concepts[1].unit,'kEUR');assert.equal(m.concepts[3].period,'FC/COD only');assert.match(m.concepts[4].period,/2027-12-31/);
});
for(const frequency of ['ANNUAL','SEMIANNUAL','QUARTERLY'])test(`${frequency} never becomes monthly`,()=>{
  const e=fixture();e.credit.data.runs[0].debt_metrics.axis.frequency=frequency;e.credit.data.runs[0].debt_metrics.axis.periods_per_year={ANNUAL:1,SEMIANNUAL:2,QUARTERLY:4}[frequency];sync(e);const m=model(e);assert.equal(m.periods.length,2);assert.equal(m.monthly,'MONTHLY_SCHEDULE_NOT_AVAILABLE');
});
for(const [name,mutate] of Object.entries({
 duplicate:p=>p.push({...p[1]}),missing:p=>{p[1].period_index=5;},unordered:p=>p.reverse(),
 closing:p=>{p[1].senior_closing_keur=9;},service:p=>{p[0].debt_service_keur=44;},
 carry:p=>{p[1].senior_opening_keur=61;p[1].principal_keur=61;p[1].debt_service_keur=64;},
 date:p=>{p[1].date='invalid';},nonfinite:p=>{p[0].interest_keur=Infinity;},
}))test(`native table fails closed: ${name}`,()=>{
 const e=fixture();mutate(e.credit.data.runs[0].debt_metrics.periods);sync(e);const m=model(e);assert.equal(m.periods.length,0);assert.ok(m.reason);assert.equal(m.concepts[4].value,'UNAVAILABLE');
});
test('monthly aggregate evidence needs complete native month identity',()=>{const e=fixture();const dm=e.credit.data.runs[0].debt_metrics;dm.axis.frequency='MONTHLY';dm.axis.periods_per_year=12;sync(e);assert.equal(model(e).periods.length,0);dm.periods[0].year=1;dm.periods[0].period_in_year=1;dm.periods[0].date='2027-01-31';dm.periods[1].year=1;dm.periods[1].period_in_year=2;dm.periods[1].date='2027-02-28';sync(e);assert.equal(model(e).periods.length,2);assert.equal(model(e).monthly,'MONTHLY_SCHEDULE_NOT_AVAILABLE');dm.periods[1].period_in_year=3;sync(e);assert.equal(model(e).periods.length,0);});
for(const [name,mutate] of Object.entries({
 scenario:e=>{e.scope.scenarioId='other';},project:e=>{e.scope.project='other';},history:e=>{e.scope.historyId='other';},
 hash:e=>{e.studio.identity.content_hash='other';},digest:e=>{e.studio.selected_run.view.repayment.rows[0].principal_keur=999;},
}))test(`source fence: ${name}`,()=>{const e=fixture();mutate(e);const m=model(e);assert.equal(m.periods.length,0);assert.ok(m.concepts.every(c=>c.value==='UNAVAILABLE'));});
test('stale stays explicitly stale',()=>{const m=model(fixture('STALE'));assert.equal(m.gate.state,'STALE');assert.equal(m.periods.length,2);});
test('unknown cash and wrong source currency never become zero',()=>{
 const e=fixture();e.studio.selected_run.view.construction.fc_senior_draw.unit='EUR';for(const p of e.credit.data.runs[0].debt_metrics.periods)p.senior_closing_keur=null;sync(e);
 const m=model(e);assert.equal(m.concepts[3].value,'UNAVAILABLE');assert.equal(m.concepts[4].value,'UNAVAILABLE');assert.equal(m.periods[0].senior_closing_keur,null);
});
test('known zero debt and below-one ratio preserve independent Integrity verdicts',()=>{
 const e=fixture();for(const p of e.credit.data.runs[0].debt_metrics.periods)for(const k of ['senior_opening_keur','principal_keur','interest_keur','debt_service_keur','senior_closing_keur'])p[k]=0;sync(e);
 assert.equal(model(e).periods.length,2);assert.equal(e.credit.data.runs[0].integrity.status,'PASS');
 e.credit.data.runs[0].integrity.status='FAIL';sync(e);assert.equal(model(e).periods.length,2);assert.equal(e.credit.data.runs[0].integrity.status,'FAIL');
});
test('multiple instruments never acquire allocated amounts',()=>{const e=fixture();e.studio.capital_stack.rows.push({...e.studio.capital_stack.rows[0],instrument_id:'other',currency:'USD'});e.studio.multisenior.active=true;const m=model(e);assert.match(m.concepts[1].coverage,/no per-facility/);assert.equal(m.concepts[2].value,'UNAVAILABLE');assert.equal(m.concepts[1].unit,'kEUR');});

test('server-accepted rounding residual is not rejected by a stricter UI tolerance',()=>{
 const e=fixture();e.credit.data.runs[0].debt_metrics.periods[1].senior_closing_keur=5e-7;sync(e);assert.equal(model(e).periods.length,2);
});
test('mixed construction axis cannot masquerade as operating repayments',()=>{
 const e=fixture();e.studio.selected_run.view.repayment.rows[0].axis='RUN_CONSTRUCTION_PERIOD';assert.equal(model(e).periods.length,0);
});
