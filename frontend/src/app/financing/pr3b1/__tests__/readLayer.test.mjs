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
for(const [name,mutate] of Object.entries(negatives))test(`fail closed: ${name}`,()=>{const e=synthetic(name.startsWith('stale')?'STALE':'CURRENT');mutate(e);const g=gate(e);assert.equal(g.showRun,false,g.reason);assert.equal(m.sourcesUsesModel(e,g),null);assert.equal(m.coverageModel(e,g),null);const html=m.render(e);assert.ok(html.includes('Selected Run changed'));assert.ok(!html.includes('aria-label="Sources &amp; Uses selected Run"'));assert.ok(!html.includes('aria-label="Coverage selected Run"'));});
test('five debt concepts keep raw source units and never sum draws',()=>{const e=synthetic(),g=gate(e),terms=m.termSheetModel(e,g)[0].rows;assert.equal(terms[0].display,'80.0%');assert.equal(terms[1].display,'85.0%');assert.equal(terms[2].label,'Senior commitment (sized)');assert.equal(terms[2].display,'70 kEUR');assert.equal(terms[3].display,'UNAVAILABLE — no independently evidenced lender commitment');assert.deepEqual(m.sourcesUsesModel(e,g).drawn.map(x=>x.seniorDraw.value),[50,20]);assert.deepEqual(m.coverageModel(e,g).outstanding,[{period:1,date:'2027-06-30',opening:70,closing:65}]);});
test('S&U passes through zero, null, total sources and server balance independently',()=>{const e=synthetic(),su=m.sourcesUsesModel(e,gate(e));assert.equal(su.sources[2].value,0);assert.equal(su.uses[1].value,null);assert.equal(su.totals[0].value,100);assert.equal(su.sources[0].value,70);const html=m.render(e);assert.match(html,/NOT AVAILABLE/);assert.match(html,/BALANCED/);});
test('below-one server warning does not turn model Integrity into FAIL',()=>{const e=synthetic(),c=m.coverageModel(e,gate(e));assert.equal(c.integrity.status,'PASS');assert.equal(c.debtMetrics.evaluation.coverage.status,'WARN');assert.equal(c.debtMetrics.evaluation.covenant.status,'BREACH');assert.equal(c.integrityFindings[0].classification,'PROVENANCE');assert.equal(c.bankabilityFindings[0].classification,'SENIOR_DEBT');assert.equal(c.periods[0].below_one,true);});
test('all eight categories, seven legacy paths, edit lock, fee restriction and unsupported status visible',()=>{const e=synthetic(),html=m.render(e);for(const g of ['Size','Pricing','Tenor','Repayment','Fees','Covenants','Reserves','Sponsor','Model Integrity','Financial Bankability','Covenant Compliance'])assert.ok(html.includes(g),g);for(const path of ['terms','overview','debt-metrics','bankability','facilities','sources-uses','investors'])assert.ok(html.includes('financing='+path),path);assert.match(html,/Locked: Synthetic calibrated schedule/);assert.match(html,/Fees read-only/);assert.match(html,/Junior unsupported/);assert.ok(!html.includes('<option value="senior2"'));assert.ok(!html.includes('type="submit"'));});
test('two-Senior does not masquerade as single-Senior commitment',()=>{const e=synthetic();e.studio.multisenior.active=true;const rows=m.termSheetModel(e,gate(e))[0].rows;assert.match(rows[3].display,/UNAVAILABLE/);assert.ok(!rows[3].display.includes('70'));});
test('read orchestration bookends all calls; no writes and abort signal retained',async()=>{const e=synthetic();let calls=[];const signal=new AbortController().signal;const fake=async(url,opts)=>{calls.push([url,opts]);let b=url.includes('workspace')?e.before:url.includes('credit-decision')?e.credit:url.includes('studio')?e.studio:e.fields;return {ok:true,json:async()=>b}};const out=await m.readEvidence(e.scope,signal,fake);assert.equal(gate(out).showRun,true);assert.equal(calls.length,6);assert.match(calls[0][0],/workspace/);assert.match(calls[1][0],/credit-decision/);assert.match(calls[4][0],/credit-decision/);assert.match(calls[5][0],/workspace/);for(const [url,opts] of calls){assert.equal(opts.method,'GET');assert.equal(opts.cache,'no-store');assert.equal(opts.signal,signal);assert.ok(!('body' in opts));assert.ok(url.includes('project=synthetic-project'));}});
test('failed endpoint never returns partial evidence',async()=>{await assert.rejects(m.readEvidence(synthetic().scope,new AbortController().signal,async()=>({ok:false,status:503})),/503/);});
test('relative GET URLs preserve special project and selected Run characters without query injection',async()=>{
 const e=synthetic(),project='Solar / č &+=?#%',history='Run / ž &+=?#%';
 e.scope.project=project;e.scope.historyId=history;
 for(const body of [e.before,e.after,e.studio,e.fields,e.creditBefore,e.credit])body.project={...body.project,code:project};
 for(const credit of [e.creditBefore,e.credit])credit.data.project_code=project;
 const signal=new AbortController().signal,calls=[];
 const fake=async(url,options)=>{
  calls.push([url,options]);
  const path=url.split('?')[0];
  return {ok:true,json:async()=>path.endsWith('workspace')?e.before:path.endsWith('credit-decision')?e.credit:path.endsWith('studio')?e.studio:e.fields};
 };
 await m.readEvidence(e.scope,signal,fake);
 const paths=['/v2/model-react/workspace','/v2/model-react/analysis/credit-decision','/v2/model-react/financing/studio','/v2/model-react/fields/debt','/v2/model-react/analysis/credit-decision','/v2/model-react/workspace'];
 assert.equal(calls.length,paths.length);
 calls.forEach(([url,options],i)=>{
  const selected=paths[i].endsWith('credit-decision') || paths[i].endsWith('financing/studio');
  const query=new URLSearchParams({project});if(selected)query.append('run',history);
  assert.equal(url,`${paths[i]}?${query.toString()}`);
  assert.deepEqual([...new URLSearchParams(url.slice(url.indexOf('?')+1))],selected?[['project',project],['run',history]]:[['project',project]]);
  assert.equal(options.method,'GET');assert.equal(options.cache,'no-store');assert.equal(options.credentials,'same-origin');assert.equal(options.signal,signal);assert.ok(!('body' in options));
 });
});
for(const kind of ['project','scenario'])test(`wrong ${kind} cannot return Working Copy evidence`,async()=>{
 const e=synthetic();
 if(kind==='project')e.studio.project={...e.studio.project,code:'synthetic-other-project'};
 else e.studio.identity={...e.studio.identity,scenario_id:'synthetic-other-scenario'};
 const fake=async url=>({ok:true,json:async()=>url.includes('workspace')?e.before:url.includes('credit-decision')?e.credit:url.includes('studio')?e.studio:e.fields});
 await assert.rejects(m.readEvidence(e.scope,new AbortController().signal,fake),/scope changed/);
});
test('source layer has no financial writer or aggregation implementation',async()=>{for(const f of ['readEvidence.ts','termSheetModel.ts','sourcesUsesModel.ts','coverageModel.ts','FinancingOverview.tsx']){const s=await readFile(join(root,f),'utf8');assert.doesNotMatch(s,/method:\s*['"](?:POST|PATCH|PUT|DELETE)|\.reduce\(|\/workbook\/(?:update|run|save-all)/);}});

test('addendum: one workspace with anchors, unique transitional destinations and existing Results',()=>{
 const html=m.render(synthetic());
 assert.ok(!html.includes('role="tablist"'));assert.ok(!html.includes('pr3b1-blocks'));assert.ok(!html.includes('Financing Studio'));
 for(const id of ['terms','overview','debt-metrics','bankability','facilities','sources-uses','investors'])assert.equal((html.match(new RegExp('financing='+id+'#','g'))??[]).length,1,id);
 for(const id of ['pr3b1-terms','pr3b1-funding','pr3b1-run','pr3b1-quality'])assert.ok(html.includes('id="'+id+'"'));
 assert.ok(html.includes('href="#results"'));assert.ok(!html.includes('Valuation (read-only)'));
});
test('Working sponsor input provenance never masquerades as Last Run',()=>{
 const e=synthetic();e.studio.sponsor_view.equity=[{label:'Synthetic equity input',value:30,display:'30',source:'Working ProjectInputs.financing.share_capital_keur',reason:''}];
 const html=m.render(e);assert.match(html,/Synthetic equity input<\/dt><dd>30<small title="Working ProjectInputs.financing.share_capital_keur">Working Copy/);
});
for (const technology of ['Solar','Wind','Battery (synthetic wire only; release gated)']) {
 test(`${technology}: read contract preserves native evidence without technology transfer`,()=>{
  const e=synthetic();e.before.project.project_type=technology;e.after.project.project_type=technology;
  const g=gate(e);assert.equal(g.showRun,true);assert.equal(g.assurance,'MITIGATED_NOT_PROVEN');
  assert.equal(m.termSheetModel(e,g)[0].rows[0].display,'80.0%');
  assert.deepEqual(m.sourcesUsesModel(e,g).drawn.map(r=>r.seniorDraw.value),[50,20]);
  assert.equal(m.coverageModel(e,g).outstanding[0].opening,70);
  e.studio.capital_stack.rows=[];assert.match(m.render(e),/no configured facility terms supplied/);
  e.studio.multisenior.active=true;assert.match(m.termSheetModel(e,gate(e))[0].rows[3].display,/UNAVAILABLE/);
  e.credit.data.runs[0].integrity={status:'FAIL',failures:[{id:'SYNTHETIC_INVALIDITY',reason:'Server-supplied failure'}]};
  assert.match(m.render(e),/Server-supplied failure/);
 });
 test(`${technology}: incomplete or historical evidence never mixes with Last Run`,()=>{
  for (const broken of ['total','snapshot','history','freshness']) {
   const e=synthetic();
   if(broken==='total')e.studio.sources_uses.view.total_sources.value=null;
   if(broken==='snapshot')delete e.credit.data.runs[0].identity.snapshot_id;
   if(broken==='history')for(const c of [e.credit,e.creditBefore])c.history_rows[0].is_last=false;
   if(broken==='freshness')e.studio.sources_uses.view.freshness='STALE';
   assert.equal(gate(e).showRun,false,broken);
  }
 });
}
test('typed refusals and aborted GETs do not produce partial evidence',async()=>{
 for(const status of [403,404,409])await assert.rejects(m.readEvidence(synthetic().scope,new AbortController().signal,async()=>({ok:false,status})),new RegExp(String(status)));
 const abort=new AbortController();abort.abort();
 await assert.rejects(m.readEvidence(synthetic().scope,abort.signal,async(url,options)=>{options.signal.throwIfAborted()}),err=>err.name==='AbortError');
});

test('real tenor wire cells render their server display; missing maturity stays unavailable',()=>{
 const e=synthetic(),tenor=m.termSheetModel(e,gate(e)).find(g=>g.label==='Tenor').rows;
 assert.equal(tenor[0].display,'2027-06-30');assert.equal(tenor[1].display,'2030-12-31');assert.equal(tenor[2].display,'NOT AVAILABLE');
 assert.doesNotThrow(()=>m.render(e));
});

test('F03 selected HISTORICAL binds its own persisted Sources & Uses, not Studio Last Run',()=>{
 const e=synthetic();
 for (const c of [e.credit,e.creditBefore]) {
   c.history_rows[0].is_last=false;
   c.data.runs[0].identity.state='HISTORICAL';
 }
 e.scope.historyId='synthetic-history';
 e.studio.selected_run.view.identity.state='HISTORICAL';
 e.studio.selected_run.view.sources_uses={...structuredClone(e.studio.sources_uses.view),run_kind:'HISTORICAL_RUN',freshness:'HISTORICAL'};
 e.studio.sources_uses.view.total_sources.value=999;
 const g=gate(e);
 assert.equal(g.state,'HISTORICAL',g.reason);
 assert.equal(g.showRun,true,g.reason);
 assert.equal(m.sourcesUsesModel(e,g).totals[0].value,100);
 assert.match(m.render(e),/HISTORICAL — selected committed Run/);
});
test('F03 wrong selected run identifiers, debt rows and missing evidence fail closed',()=>{
 const cases={
  history:e=>e.studio.selected_run.view.identity.history_id='other',
  snapshot:e=>e.studio.selected_run.view.identity.snapshot_id='other',
  hash:e=>e.studio.selected_run.view.identity.composite_hash='other',
  debt:e=>e.studio.selected_run.view.repayment.rows[0].senior_opening_keur=999,
  totals:e=>e.studio.selected_run.view.sources_uses.total_sources.value=99,
  authority:e=>e.studio.selected_run.view.internal_run_binding='NOT_PROVEN',
  missing:e=>delete e.studio.selected_run,
 };
 for(const [name,mutate] of Object.entries(cases)){
  const e=synthetic();mutate(e);
  assert.equal(gate(e).showRun,false,name);
  assert.equal(m.sourcesUsesModel(e,gate(e)),null,name);
 }
 const zero=synthetic();
 assert.match(m.render(zero),/Separate FC\/COD Senior draw · 0 kEUR/);
 const absent=synthetic();absent.studio.selected_run.view.construction.fc_senior_draw.value=null;
 assert.match(m.render(absent),/Separate FC\/COD Senior draw · UNAVAILABLE/);
});
