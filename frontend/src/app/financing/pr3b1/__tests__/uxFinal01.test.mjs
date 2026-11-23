// UX-FINAL-01: the NOT_RUN gate keeps its state and withholds Run values; only its wording changed (no repeated raw code, no zero).
import assert from 'node:assert/strict';
import test from 'node:test';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, dirname } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { build } from 'esbuild';
import { synthetic } from './synthetic.mjs';
const dir = await mkdtemp(join(tmpdir(), 'uxfinal01-tests-'));
const root = dirname(fileURLToPath(new URL('../FinancingOverview.tsx', import.meta.url)));
await build({ stdin: { contents: `export {checkRunEvidence} from './runEvidence'; import {FinancingOverview} from './FinancingOverview'; import {createElement} from 'react'; import {renderToStaticMarkup} from 'react-dom/server'; export const render = e => renderToStaticMarkup(createElement(FinancingOverview,{evidence:e,onReload:()=>{}}));`, resolveDir: root, loader: 'tsx' }, outfile: join(dir, 'entry.cjs'), bundle: true, platform: 'node', format: 'cjs', jsx: 'automatic', loader: { '.css': 'empty' } });
const m = await import(pathToFileURL(join(dir, 'entry.cjs')));
test.after(() => rm(dir, { recursive: true, force: true }));
const noRun = () => {
  const e = synthetic('NOT_RUN');
  for (const c of [e.credit, e.creditBefore]) { c.data = null; c.history_rows = []; }
  for (const w of [e.before, e.after]) w.identity = null;
  e.studio.sources_uses.view.has_run = false;
  return e;
};
test('NOT_RUN keeps its state, shows no Run values and says so once, without repeating the raw code', () => {
  const g = m.checkRunEvidence(noRun());
  assert.equal(g.state, 'NOT_RUN');
  assert.equal(g.showRun, false);
  assert.match(g.reason, /^No committed Run for this project yet\./);
  assert.ok(!g.reason.includes('NOT_RUN'));
});
test('the rendered NOT_RUN banner shows the state once, then the plain reason', () => {
  const html = m.render(noRun());
  assert.ok(html.includes('No committed Run for this project yet.'));
  assert.ok(!html.includes('NOT_RUN — no committed selected Run'));
});
