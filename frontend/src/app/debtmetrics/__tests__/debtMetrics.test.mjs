import assert from "node:assert/strict";
import test from "node:test";
import { readFile, writeFile, mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import ts from "typescript";

// Transpile the pure TypeScript helpers on the fly (same approach as reportFormatting.test.mjs); no bundler, no DOM.
const dir = await mkdtemp(join(tmpdir(), "finco-debt-metrics-"));
const load = async (name) => {
  const source = await readFile(new URL(`../${name}.ts`, import.meta.url), "utf8");
  const out = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ES2022, target: ts.ScriptTarget.ES2020 } }).outputText;
  await writeFile(join(dir, `${name}.mjs`), out);
  return import(pathToFileURL(join(dir, `${name}.mjs`)));
};
const f = await load("format");
const l = await load("debtMetricsLink");
test.after(() => rm(dir, { recursive: true, force: true }));

test("formatRatio never reads equal to a reference unless it is equal (mirrors the server rule)", () => {
  const cases = [[0.9951, [1], "0.995x"], [0.99999, [1], "0.99999x"], [0.7559018708368817, [1], "0.76x"], [1.2, [1], "1.20x"], [1, [1], "1.00x"],
    [1.004, [1], "1.004x"], [1.05, [1.05], "1.05x"], [0.5, [1, 1.05], "0.50x"]];
  for (const [value, refs, shown] of cases) assert.equal(f.formatRatio(value, refs), shown, String(value));
  for (const [value, ref] of [[0.9951, 1], [0.99999, 1], [1.049999999, 1.05], [1.0500001, 1.05], [1.004, 1]]) {
    assert.notEqual(f.formatRatio(value, [ref]), f.formatRatio(ref, [ref]));
    assert.equal(Number.parseFloat(f.formatRatio(value, [ref])) < ref, value < ref);
  }
  for (const bad of [null, undefined, NaN, Infinity, "1.0"]) assert.equal(f.formatRatio(bad), "—");
});

test("a one-ulp breach is distinguishable from the threshold", () => {
  const below = 1.05 - Number.EPSILON;
  assert.ok(below < 1.05);
  assert.notEqual(f.formatRatio(below, [1.05]), "1.05x");
});

test("formatDeltaX shows a small difference with two significant digits, never as zero", () => {
  const cases = [[0.15, "+0.15x"], [-0.0074885, "-0.0075x"], [-0.00001234, "-0.000012x"], [1.234, "+1.23x"], [0, "+0.00x"], [-0.1, "-0.10x"]];
  for (const [delta, shown] of cases) assert.equal(f.formatDeltaX(delta), shown, String(delta));
  assert.equal(f.formatDeltaX(null), "—");
});

test("brokenPath breaks the line wherever a period has no value: no 0x line is drawn across a gap", () => {
  const d = f.brokenPath([{ x: 0, y: 5 }, { x: 1, y: 6 }, { x: 2, y: null }, { x: 3, y: 7 }, { x: 4, y: 8 }, { x: 5, y: null }]);
  assert.equal(d, "M0.00,5.00L1.00,6.00M3.00,7.00L4.00,8.00");
  assert.equal(f.brokenPath([{ x: 0, y: null }]), "");
  assert.equal(f.brokenPath([{ x: 0, y: NaN }, { x: 1, y: 2 }]), "M1.00,2.00");
});

test("scales, ticks and domain always contain every plotted value and every drawn threshold", () => {
  const [lo, hi] = f.yDomain([1.28, 0.9925, null, 1.5], [1, 1.05, null, 1.2]);
  assert.ok(lo < 0.9925 && hi > 1.5);
  const [lo2, hi2] = f.yDomain([1.0], []);
  assert.ok(lo2 < 1 && hi2 > 1);
  assert.deepEqual(f.yDomain([], []), [0, 2]);
  const scale = f.linearScale([0, 2], [100, 0]);
  assert.equal(scale(0), 100); assert.equal(scale(2), 0); assert.equal(scale(1), 50);
  assert.equal(f.linearScale([1, 1], [0, 10])(1), 5);
  const ticks = f.niceTicks(0.9, 1.6, 5);
  assert.ok(ticks.length >= 3 && ticks[0] >= 0.9 && ticks[ticks.length - 1] <= 1.6 + 1e-9);
});

test("labelIndexes always includes the first and last period and never more than the maximum", () => {
  assert.deepEqual(f.labelIndexes(0), []);
  assert.deepEqual(f.labelIndexes(3), [0, 1, 2]);
  const many = f.labelIndexes(58, 8);
  assert.equal(many[0], 0); assert.equal(many[many.length - 1], 57); assert.ok(many.length <= 9);
});

test("scheduleCsv exports the persisted raw values, quotes safely and marks a missing value n/a", () => {
  const csv = f.scheduleCsv(
    [{ label: "2031 H1", date: "2031-06-30" }, { label: "2031 H2", date: null }],
    [{ label: 'Cover, "debt"', rows: [{ label: "DSCR (base case)", unit: "x", available: true, values: [1.2805499457437635, null] },
      { label: "Below 1.00x", unit: "flag", available: true, values: [false, true] }, { label: "LLCR", unit: "x", available: false, values: [null, null] }] }],
  );
  const lines = csv.trimEnd().split("\n");
  assert.equal(lines[0], "Group,Line,Unit,2031 H1 (2031-06-30),2031 H2");
  assert.equal(lines[1], '"Cover, ""debt""",DSCR (base case),x,1.2805499457437635,n/a');
  assert.equal(lines[2].split(",").slice(-2).join(","), "no,yes");
  assert.equal(lines[3].split(",").slice(-2).join(","), "n/a,n/a");
});

test("debtMetricsSearch selects the Financing → Debt metrics tab, keeps every other parameter and clears a stale Run", () => {
  assert.equal(l.debtMetricsSearch(null, "?project=ABC"), "?project=ABC&financing=debt-metrics");
  assert.equal(l.debtMetricsSearch("run-1", "?project=ABC&financing=terms"), "?project=ABC&financing=debt-metrics&dm_run=run-1");
  assert.equal(l.debtMetricsSearch(null, "?project=A&dm_run=old"), "?project=A&financing=debt-metrics");
  assert.equal(l.debtMetricsSearch(undefined, ""), "?financing=debt-metrics");
});

test("internal links are hash-only (the workspace turns any other anchor into a guarded full navigation)", () => {
  assert.equal(l.debtMetricsHref(), "#financing");
});
