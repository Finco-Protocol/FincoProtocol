import assert from 'node:assert/strict';
import test from 'node:test';
import { mkdtemp, rm, readFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, dirname } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { build } from 'esbuild';
import { synthetic } from './synthetic.mjs';
const dir = await mkdtemp(join(tmpdir(),'pr3b1-tests-'));
const root = dirname(fileURLToPath(new URL('../FinancingOverview.tsx',import.meta.url)));
await build({stdin:{contents:`export {checkRunEvidence} from './runEvidence'; export {termSheetModel} from './termSheetModel'; export {sourcesUsesModel} from './sourcesUsesModel'; export {coverageModel} from './coverageModel'; export {readEvidence} from './readEvidence'; import {FinancingOverview} from './FinancingOverview'; import {createElement} from 'react'; import {renderToStaticMarkup} from 'react-dom/server'; export const render = e => renderToStaticMarkup(createElement(FinancingOverview,{evidence:e,onReload:()=>{}}));`,resolveDir:root,loader:'tsx'},outfile:join(dir,'entry.cjs'),bundle:true,platform:'node',format:'cjs',jsx:'automatic',loader:{'.css':'empty'}});
const m=await import(pathToFileURL(join(dir,'entry.cjs')));
test.after(()=>rm(dir,{recursive:true,force:true}));
const gate=e=>m.checkRunEvidence(e);
test('CURRENT and safely anchored STALE accepted with honest snapshot caveat',()=>{for(const state of ['CURRENT','STALE']){const g=gate(synthetic(state));assert.equal(g.showRun,true,g.reason);assert.equal(g.state,state);assert.equal(g.assurance,'MITIGATED_NOT_PROVEN');}});
test('NOT_RUN remains distinct from unavailable',()=>{const e=synthetic('NOT_RUN');for(const c of [e.credit,e.creditBefore]){c.data=null;c.history_rows=[];}for(const w of [e.before,e.after])w.identity=null;e.studio.sources_uses.view.has_run=false;assert.equal(gate(e).state,'NOT_RUN');assert.equal(gate(e).showRun,false);});
const negatives={
 'raw totals mismatch':e=>{e.studio.sources_uses.view.total_sources.value=100.0000000001},
 'formatted equality is insufficient':e=>{e.studio.sources_uses.view.total_sources.value='100'},
 'missing total is not zero':e=>{e.studio.sources_uses.view.total_uses.value=null},
 'missing Studio identity':e=>{delete e.studio.identity},
 'missing Run identity':e=>{delete e.credit.data.runs[0].identity},
 'missing snapshot':e=>{delete e.credit.data.runs[0].identity.snapshot_id},
 'missing history':e=>{delete e.credit.data.runs[0].identity.history_id},
 'project switch':e=>{e.scope.project='other'},
 'scenario switch':e=>{e.scope.scenarioId='other'},
 'credit project':e=>{e.credit.data.project_code='other'},
 'studio hash':e=>{e.studio.identity.content_hash='other'},
 'current hash':e=>{for(const c of [e.credit,e.creditBefore])c.data.runs[0].identity.composite_hash='other';for(const w of [e.before,e.after])w.identity.composite_hash='other'},
 'workspace race':e=>{e.after.workbook.composite_hash='other'},
 'run race':e=>{e.credit.data.runs[0].identity.snapshot_id='other'},
 'freshness race':e=>{e.credit.freshness='STALE'},
 'selected historical':e=>{for(const c of [e.credit,e.creditBefore])c.history_rows[0].is_last=false},
 'requested run differs':e=>{e.scope.historyId='other'},
 'missing financing evidence':e=>{e.studio.sources_uses.view.has_financing_evidence=false},
 'field read race':e=>{e.fields.save.content_hash='other'},
 'stale missing workspace last-run anchor':e=>{e.before.identity=null;e.after.identity=null},
};
for(const [name,mutate] of Object.entries(negatives))test(`fail closed: ${name}`,()=>{const e=synthetic(name.startsWith('stale')?'STALE':'CURRENT');mutate(e);const g=gate(e);assert.equal(g.showRun,false,g.reason);assert.equal(m.sourcesUsesModel(e,g),null);assert.equal(m.coverageModel(e,g),null);const html=m.render(e);assert.ok(html.includes('Last Run changed'));assert.ok(!html.includes('aria-label="Sources &amp; Uses Last Run"'));assert.ok(!html.includes('aria-label="Coverage Last Run"'));});
test('five debt concepts keep raw source units and never sum draws',()=>{const e=synthetic(),g=gate(e),terms=m.termSheetModel(e,g)[0].rows;assert.equal(terms[0].display,'80.0%');assert.equal(terms[1].display,'85.0%');assert.equal(terms[2].label,'Senior commitment (sized)');assert.equal(terms[2].display,'70 kEUR');assert.equal(terms[3].display,'N/A — sized commitment (single Senior)');assert.deepEqual(m.sourcesUsesModel(e,g).drawn.map(x=>x.seniorDraw.value),[50,20]);assert.deepEqual(m.coverageModel(e,g).outstanding,[{period:1,date:'2027-06-30',opening:70,closing:65}]);});
test('S&U passes through zero, null, total sources and server balance independently',()=>{const e=synthetic(),su=m.sourcesUsesModel(e,gate(e));assert.equal(su.sources[2].value,0);assert.equal(su.uses[1].value,null);assert.equal(su.totals[0].value,100);assert.equal(su.sources[0].value,70);const html=m.render(e);assert.match(html,/NOT AVAILABLE/);assert.match(html,/BALANCED/);});
test('below-one server warning does not turn model Integrity into FAIL',()=>{const e=synthetic(),c=m.coverageModel(e,gate(e));assert.equal(c.integrity.status,'PASS');assert.equal(c.debtMetrics.evaluation.coverage.status,'WARN');assert.equal(c.debtMetrics.evaluation.covenant.status,'BREACH');assert.equal(c.integrityFindings[0].classification,'PROVENANCE');assert.equal(c.bankabilityFindings[0].classification,'SENIOR_DEBT');assert.equal(c.periods[0].below_one,true);});
test('all eight categories, seven legacy paths, edit lock, fee restriction and unsupported status visible',()=>{const e=synthetic(),html=m.render(e);for(const g of ['Size','Pricing','Tenor','Repayment','Fees','Covenants','Reserves','Sponsor','Model Integrity','Financial Bankability','Covenant Compliance'])assert.ok(html.includes(g),g);for(const path of ['terms','overview','debt-metrics','bankability','facilities','sources-uses','investors'])assert.ok(html.includes('financing='+path),path);assert.match(html,/Locked: Synthetic calibrated schedule/);assert.match(html,/fees read-only/);assert.match(html,/Junior unsupported/);assert.ok(!html.includes('<option value="senior2"'));assert.ok(!html.includes('type="submit"'));});
test('two-Senior does not masquerade as single-Senior commitment',()=>{const e=synthetic();e.studio.multisenior.active=true;const rows=m.termSheetModel(e,gate(e))[0].rows;assert.match(rows[3].display,/NOT AVAILABLE/);assert.ok(!rows[3].display.includes('70'));});
test('read orchestration bookends all calls; no writes and abort signal retained',async()=>{const e=synthetic();let calls=[];const signal=new AbortController().signal;const fake=async(url,opts)=>{calls.push([url,opts]);let b=url.includes('workspace')?e.before:url.includes('credit-decision')?e.credit:url.includes('studio')?e.studio:e.fields;return {ok:true,json:async()=>b}};const out=await m.readEvidence(e.scope,signal,fake);assert.equal(gate(out).showRun,true);assert.equal(calls.length,6);assert.match(calls[0][0],/workspace/);assert.match(calls[1][0],/credit-decision/);assert.match(calls[4][0],/credit-decision/);assert.match(calls[5][0],/workspace/);for(const [url,opts] of calls){assert.equal(opts.method,'GET');assert.equal(opts.cache,'no-store');assert.equal(opts.signal,signal);assert.ok(!('body' in opts));assert.ok(url.includes('project=synthetic-project'));}});
test('failed endpoint never returns partial evidence',async()=>{await assert.rejects(m.readEvidence(synthetic().scope,new AbortController().signal,async()=>({ok:false,status:503})),/503/);});
test('source layer has no financial writer or aggregation implementation',async()=>{for(const f of ['readEvidence.ts','termSheetModel.ts','sourcesUsesModel.ts','coverageModel.ts','FinancingOverview.tsx']){const s=await readFile(join(root,f),'utf8');assert.doesNotMatch(s,/method:\s*['"](?:POST|PATCH|PUT|DELETE)|\.reduce\(|\/workbook\/(?:update|run|save-all)/);}});
