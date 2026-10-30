import assert from "node:assert/strict";
import test from "node:test";
import { mkdtemp, rm, symlink } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import { build } from "esbuild";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";

// Fixtures exercise rendering only; they are never imported by product code.  The component draws server-evaluated statuses: it computes nothing.
const output = await mkdtemp(join(tmpdir(), "finco-period-matrix-"));
await build({ entryPoints: [new URL("../PeriodStatusMatrix.tsx", import.meta.url).pathname], bundle: true, outfile: join(output, "matrix.mjs"), format: "esm", platform: "node",
  packages: "external", loader: { ".css": "empty" }, jsx: "automatic" });
await symlink(new URL("../../../../node_modules", import.meta.url).pathname, join(output, "node_modules"));
const { PeriodStatusMatrix } = await import(pathToFileURL(join(output, "matrix.mjs")));
test.after(() => rm(output, { recursive: true, force: true }));

const periods = (n, perYear = 4) => Array.from({ length: n }, (_, i) => ({ period_index: i, label: `${2031 + Math.floor(i / perYear)} Q${(i % perYear) + 1}`,
  date: `${2031 + Math.floor(i / perYear)}-0${(i % perYear) * 3 + 3}-30`.replace(/-0(\d\d)-/, "-$1-"), year: 2031 + Math.floor(i / perYear), period_in_year: (i % perYear) + 1 }));
const row = (id, label, source, statuses) => ({ id, label, source, map: `source of ${id}`, cells: statuses.map((s, i) => [s, `P${i} — ${label}: ${s}`]) });
const matrixOf = (n) => ({
  available: true, reason: "", periods: n,
  rows: [
    row("LOCKUP", "Distribution lock-up", "RUN RESULT", Array.from({ length: n }, (_, i) => (i === 0 ? "WARN" : "OK"))),
    row("MIN_DSCR", "Minimum DSCR", "INPUT RECORDED WITH THIS RUN", Array.from({ length: n }, (_, i) => (i === 0 ? "ALERT" : "OK"))),
    row("CONTRACTUAL_DSCR", "Contractual DSCR", "INPUT RECORDED WITH THIS RUN", Array.from({ length: n }, () => "NA")),
    row("COVERAGE_1X", "Debt-service coverage 1.00x", "RUN RESULT", Array.from({ length: n }, (_, i) => (i < 2 ? "ALERT" : "OK"))),
    row("CASH_SHORTFALL", "Cash shortfall (before reserves)", "RUN RESULT", Array.from({ length: n }, () => "NA")),
  ],
  summary: [{ id: "LOCKUP", label: "Lock-up", alerts: 1, evaluated: n, applicable: n }, { id: "MIN_DSCR", label: "Below Minimum DSCR", alerts: 1, evaluated: n, applicable: n },
    { id: "CONTRACTUAL_DSCR", label: "Covenant breaches", alerts: null, evaluated: 0, applicable: n }, { id: "COVERAGE_1X", label: "Coverage below 1.00x", alerts: 2, evaluated: n - 3, applicable: n },
    { id: "CASH_SHORTFALL", label: "Cash shortfall", alerts: null, evaluated: 0, applicable: n }],
  gaps: [{ id: "DSRA_REQUIRED", label: "DSRA requirement / reserve draw", status: "UNAVAILABLE", reason: "Unavailable — the required DSRA amount and any reserve draw per period are not recorded with this Run." }],
});
const html = (n) => renderToStaticMarkup(React.createElement(PeriodStatusMatrix, { matrix: matrixOf(n), periods: periods(n), onJump: () => {} }));

test("a 54-period semiannual and a 120-period quarterly Run render as a compact grid with real table semantics", () => {
  for (const [n, perYear] of [[54, 2], [120, 4]]) {
    const m = matrixOf(n);
    const out = renderToStaticMarkup(React.createElement(PeriodStatusMatrix, { matrix: m, periods: periods(n, perYear), onJump: () => {} }));
    assert.equal((out.match(/<td /g) ?? []).length, 5 * n, `${n} periods x 5 metrics`);
    assert.equal((out.match(/scope="row"/g) ?? []).length, 5);
    assert.ok((out.match(/scope="col"/g) ?? []).length >= n + 1 && /scope="colgroup"/.test(out));
    assert.ok(/role="grid"/.test(out) && /data-dm-mx-scroll="true"/.test(out));
    assert.ok(!/OPEN|LOCKED/.test(out.replace(/Distribution lock-up: (OK|WARN)/g, "")), "no large OPEN/LOCKED tiles");
  }
});

test("the year header groups consecutive periods of the same saved year", () => {
  const out = html(10);                                     // 2031 Q1..Q4, 2032 Q1..Q4, 2033 Q1..Q2
  assert.deepEqual([...out.matchAll(/scope="colgroup" colSpan="(\d+)" class="dm-mx-year">(\d+)</g)].map((x) => [x[2], Number(x[1])]), [["2031", 4], ["2032", 4], ["2033", 2]]);
});

test("every status carries its own glyph and a text alternative; a missing figure is a grey dash, never a tick", () => {
  const out = html(6);
  for (const [status, glyph] of [["OK", "✓"], ["ALERT", "×"], ["WARN", "!"], ["NA", "—"]]) assert.ok(out.includes(`data-s="${status}"`) && out.includes(`dm-dot-${status.toLowerCase()}" aria-hidden="true">${glyph}`), status);
  const contractual = out.match(/<tr data-dm-mx-row="CONTRACTUAL_DSCR">.*?<\/tr>/s)[0];
  assert.ok(!contractual.includes("✓") && !contractual.includes("dm-dot-ok"), "an unrecorded term is never green");
  assert.ok(/aria-label="P0 — Minimum DSCR: ALERT"/.test(out));
});

test("the summary states counts only where the Run evidence made them computable", () => {
  const out = html(8);
  assert.ok(/data-dm-mx-count="CONTRACTUAL_DSCR">Covenant breaches: <strong>Not recorded<\/strong>/.test(out));
  assert.ok(/data-dm-mx-count="COVERAGE_1X">Coverage below 1\.00x: <strong>2<\/strong>.*5 of 8 periods evaluated/s.test(out));
  assert.ok(/<strong>8<\/strong> periods/.test(out));
});

test("an unavailable DSRA requirement is disclosed outside the matrix and no DSRA status row is invented", () => {
  const out = html(4);
  assert.ok(/data-dm-mx-gap="DSRA_REQUIRED"/.test(out) && /Unavailable — the required DSRA amount/.test(out));
  assert.ok(!/data-dm-mx-row="DSRA/.test(out));
});

test("exactly one cell is tabbable (roving focus) and the unavailable state names its reason", () => {
  const out = html(30);
  assert.equal((out.match(/tabindex="0"/g) ?? []).length, 1);
  const none = renderToStaticMarkup(React.createElement(PeriodStatusMatrix, { matrix: { available: false, reason: "This Run persisted no per-period debt evidence.", rows: [], summary: [], gaps: [] }, periods: [], onJump: () => {} }));
  assert.ok(/data-dm-matrix-unavailable="true"/.test(none) && /persisted no per-period debt evidence/.test(none));
});
