import assert from 'node:assert/strict';
import { readFile, writeFile, mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';
import ts from 'typescript';
const dir = await mkdtemp(join(tmpdir(), 'finco-report-format-'));
try {
  for (const name of ['units', 'reportFormatting']) {
    const source = await readFile(new URL(`./${name}.ts`, import.meta.url), 'utf8');
    const output = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ES2022, target: ts.ScriptTarget.ES2020 } }).outputText.replace('"./units"', '"./units.mjs"');
    await writeFile(join(dir, name + '.mjs'), output);
  }
  const f = await import(pathToFileURL(join(dir, 'reportFormatting.mjs')));
  const u = await import(pathToFileURL(join(dir, 'units.mjs')));
  assert.equal(f.DEFAULT_REPORT_PRECISION, 0);
  for (const [raw,zero,two] of [[72994.47,'72,994','72,994.47'],[1512.4,'1,512','1,512.40'],[-125.75,'(126)','(125.75)'],[0,'0','0.00']]) {
    assert.equal(f.reportAmount(raw), zero);
    assert.equal(f.reportAmount(raw,2), two);
    assert.equal(f.reportAmount(raw,0), zero);
  }
  assert.equal(f.reportAmount(null), '—');
  assert.equal(f.reportAmount(Infinity), '—');
  assert.equal(f.reportCell('0.76',{kind:'ratio'},'kEUR',0,0.756),'0.76x');
  assert.equal(f.reportCell('1.00',{kind:'ratio'},'kEUR',0,0.9999),'0.9999x');
  assert.equal(f.reportCell('0.00',{kind:'ratio'},'kEUR',0,-0.0003),'-0.0003x');
  assert.equal(f.reportCell('0.30%',{kind:'percent'},'kEUR',0,0.003),'0.30%');
  assert.equal(f.reportMetric('7.35%','kEUR',0),'7.35%');
  assert.equal(f.reportEvidence(0.9996,'1.00x','Minimum DSCR',0),'0.9996x');
  assert.equal(f.reportEvidence(1234.56789,'1,234.57 kEUR','Senior debt',3),'1,234.568 kEUR');
  assert.equal(f.reportCell('1.00',{kind:'ratio'},'kEUR',0,null),'—');
  assert.equal(f.reportDelta('+5,000.25 kEUR','kEUR',0),'+5,000 kEUR');
  assert.equal(f.reportCell('1,512.4',u.resolveRowFormat('Energy','MWh','keur'),'EUR',0,1512.4),'1,512');
  const canonical = Object.freeze({ value:72994.47, contentHash:'unchanged', historyId:'same-run' });
  const before=JSON.stringify(canonical);
  for (const precision of [0,2,3,0]) f.reportAmount(canonical.value,precision);
  assert.equal(JSON.stringify(canonical),before);
  console.log('Report formatting: acceptance examples passed; canonical values unchanged.');
} finally { await rm(dir,{recursive:true,force:true}); }
