import assert from 'node:assert/strict';
import test from 'node:test';
import {mkdtemp,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join,dirname} from 'node:path';
import {fileURLToPath,pathToFileURL} from 'node:url';
import {build} from 'esbuild';
const dir=await mkdtemp(join(tmpdir(),'financing-block-'));
await build({entryPoints:[join(dirname(fileURLToPath(import.meta.url)),'blockContract.ts')],outfile:join(dir,'contract.cjs'),bundle:true,platform:'node',format:'cjs'});
const {buildBlockRequest,canEdit}=await import(pathToFileURL(join(dir,'contract.cjs')));test.after(()=>rm(dir,{recursive:true,force:true}));
const fixture=()=>{
 const f={field_id:'debt.senior.interest_rate_pct',label:'All-in rate',field_type:'pct',binding_label:'bound',value:'5',min_value:0,max_value:100};
 return {w:{project:{code:'synthetic',protected_reference:false},workbook:{scenario_id:'scenario-a',version:'v',composite_hash:'hash'},save_all:{available:true,url:'/v2/workbook/save-all',csrf_token:'synthetic-token',sections:['cells'],excluded:['debt.financing.instruments']}},
 fields:{project:{code:'synthetic',protected_reference:false},save:{content_hash:'hash',workbook_version:'v'},fields:[f]},edits:[{id:'financing:'+f.field_id,section:'financing',key:f.field_id,value:'0.056',baseline:'5'}]};
};
const request=x=>buildBlockRequest(x.w,x.fields,'synthetic','scenario-a','hash',x.edits,'synthetic-id');
test('single atomic request retains human percentages and contains only the chosen scalar cells',()=>{
 const x=fixture(),r=request(x);assert.deepEqual(r.cells,[{field_id:'debt.senior.interest_rate_pct',value:'0.056'}]);
 assert.equal(r.scenario_id,'scenario-a');assert.equal(r.contracts_json,null);assert.deepEqual(r.cost_lines,[]);assert.ok(!('profile_json' in r));
});
for(const [name,change] of Object.entries({
 project:x=>x.w.project.code='other',field_project:x=>x.fields.project.code='other',scenario:x=>x.w.workbook.scenario_id='scenario-b',
 hash:x=>x.w.workbook.composite_hash='other',fields_hash:x=>x.fields.save.content_hash='other',version:x=>x.fields.save.workbook_version='other',
 protected:x=>x.w.project.protected_reference=true,role:x=>x.w.save_all.available=false,capability:x=>x.w.save_all.sections=[],
 binding:x=>x.fields.fields[0].binding_label='template-locked',baseline:x=>x.fields.fields[0].value='6',
 unknown_field:x=>x.edits[0].key='debt.unknown',conflict:x=>x.edits[0].conflict={code:'SCOPE_CHANGED'},
 invalid:x=>x.edits[0].value='not-a-number',instruments:x=>{x.edits[0].key=x.fields.fields[0].field_id='debt.financing.instruments';},
 configuration:x=>{x.edits[0].key=x.fields.fields[0].field_id='debt.bankability.configuration';},
}))test(`refuse without building a write: ${name}`,()=>{const x=fixture();change(x);assert.throws(()=>request(x));});
test('capability cannot grant editing to a partial or structured field',()=>{const x=fixture();for(const binding_label of ['partial','display-only','template-locked'])assert.equal(canEdit({...x.fields.fields[0],binding_label},x.w,x.fields),false);});
