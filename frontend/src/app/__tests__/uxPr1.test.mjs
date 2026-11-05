import assert from 'node:assert/strict';
import test from 'node:test';
import {mkdtemp, rm, symlink} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {build} from 'esbuild';
const output=await mkdtemp(join(tmpdir(),'finco-ux-pr1-'));
await build({stdin:{contents:`export * from './workspaceNavigation'; export {showPerMwKeur,showKeur} from './costAmounts'; export {isLegacyReference} from './CanonicalInputGrid';`,resolveDir:new URL('..',import.meta.url).pathname,loader:'ts'},bundle:true,outfile:join(output,'ux.mjs'),format:'esm',platform:'node',packages:'external',loader:{'.css':'empty'},jsx:'automatic'});
await symlink(new URL('../../../node_modules',import.meta.url).pathname,join(output,'node_modules'));
const U=await import(pathToFileURL(join(output,'ux.mjs')));
test.after(()=>rm(output,{recursive:true,force:true}));
test('every canonical navigation destination resolves, including financing and debt output',()=>{
 const destinations=U.WORKSPACE_NAV_GROUPS.flatMap(g=>[...(g.destination?[g.destination]:[]),...g.items.map(i=>i.destination)]);
 assert.equal(new Set(destinations).size,destinations.length);
 for(const d of destinations) assert.equal(U.workspaceRoute(d).destination,d);
 assert.ok(destinations.includes('financing'));assert.ok(destinations.includes('debt-metrics'));
 assert.equal(U.workspaceRoute('unreviewed').destination,'overview');
});
test('bookmarks retain period views and parent active state',()=>{
 for(const [alias,canonical] of Object.entries({capex:'inputs/capex','capex/monthly':'inputs/capex/monthly',opex:'inputs/opex','opex/years':'inputs/opex/years'})){
  assert.equal(U.workspaceRoute('#'+alias).destination,canonical);
  assert.equal(U.canonicalHash(canonical),canonical);
 }
 assert.equal(U.activeNavigationDestination('inputs/capex/monthly'),'inputs/capex');
 assert.equal(U.activeNavigationDestination('inputs/opex/years'),'inputs/opex');
});
test('dedicated per-MW precision preserves small nonzero values and unavailable versus zero',()=>{
 for(const unit of ['EUR','kEUR','mEUR']){
  assert.equal(U.showPerMwKeur(null,unit,0),'—');
  assert.equal(U.showPerMwKeur('',unit,0),'—');
  assert.equal(U.showPerMwKeur('0',unit,0),'0.00');
  assert.match(U.showPerMwKeur('0.00001',unit,0),/[1-9]/);
  assert.match(U.showPerMwKeur('0.000000000001',unit,0),/[1-9]/);
  assert.match(U.showPerMwKeur('0.0000000000000000000000001',unit,0),/^</);
  assert.match(U.showPerMwKeur('-0.0000000000000000000000001',unit,0),/^\(</);
 }
 assert.equal(U.showPerMwKeur('0.625','kEUR',0),'0.63');
 assert.equal(U.showPerMwKeur('0.625','EUR',0),'625.00');
 assert.equal(U.showPerMwKeur('0.625','kEUR',3),'0.625');
 assert.equal(U.showKeur('1234.56789','kEUR',0),'1,235');
});
test('only server-labelled locked legacy references are eligible for disclosure',()=>{
 assert.equal(U.isLegacyReference({field_id:'',label:'Tariff (legacy key)',editable:false}),true);
 for(const r of [{field_id:'revenue.tariff',label:'Tariff (legacy key)',editable:true},{field_id:'revenue.tariff',label:'Tariff (legacy key)',editable:false},{field_id:'',label:'Actual saved tariff',editable:false}]) assert.equal(U.isLegacyReference(r),false);
});
