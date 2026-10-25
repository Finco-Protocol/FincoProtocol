// WF-React-1 — canonical EUR/kEUR/mEUR display conversion and number formatting.
// Pure presentation checks: exact decimal-string scaling, no binary float drift.
import assert from "node:assert/strict";
import test from "node:test";
import {
  formatMoneyText, formatRatioText, formatStatementCell, formatUnitLabel, plotValue,
  resolveRowFormat, sheetUnitLabel,
} from "../../src/app/units.ts";

test("kEUR canonical text converts exactly to EUR and mEUR", () => {
  assert.equal(formatMoneyText("1,232.50", "kEUR", "kEUR", 1), "1,232.5");
  assert.equal(formatMoneyText("1,232.50", "kEUR", "EUR", 0), "1,232,500");
  assert.equal(formatMoneyText("1,232.50", "kEUR", "mEUR", 3), "1.233");
  assert.equal(formatMoneyText("1,232.50", "kEUR", "mEUR", 2), "1.23");
  assert.equal(formatMoneyText("1,232.50", "kEUR", "mEUR", 4), "1.2325");
  assert.equal(formatMoneyText("0.00", "kEUR", "mEUR", 1), "0.0");
});

test("rounding is half away from zero on the decimal string and carries across digits", () => {
  assert.equal(formatMoneyText("999.95", "kEUR", "kEUR", 1), "1,000.0");
  assert.equal(formatMoneyText("0.0005", "mEUR", "mEUR", 3), "0.001");
  assert.equal(formatMoneyText("2.675", "kEUR", "kEUR", 2), "2.68", "no binary float drift (2.675 stays a tie)");
  assert.equal(formatMoneyText("1.005", "kEUR", "kEUR", 2), "1.01");
});

test("negative money uses parentheses; a value rounding to zero is not negative", () => {
  assert.equal(formatMoneyText("-1,232.50", "kEUR", "kEUR", 1), "(1,232.5)");
  assert.equal(formatMoneyText("(33.70)", "kEUR", "kEUR", 1), "(33.7)");
  assert.equal(formatMoneyText("-0.04", "kEUR", "kEUR", 1), "0.0");
});

test("unavailable and status text never become zero", () => {
  assert.equal(formatMoneyText("—", "kEUR", "kEUR", 1), "—");
  assert.equal(formatMoneyText("", "kEUR", "kEUR", 1), "—");
  assert.equal(formatMoneyText(undefined, "kEUR", "mEUR", 1), "—");
  assert.equal(formatMoneyText("NOT AVAILABLE", "kEUR", "kEUR", 1), "NOT AVAILABLE");
  assert.equal(formatMoneyText("not evaluated", "kEUR", "kEUR", 1), "NOT EVALUATED");
});

test("ratios and percentages keep canonical precision and are never unit-scaled", () => {
  assert.equal(formatRatioText("1.25", "ratio"), "1.25x");
  assert.equal(formatRatioText("9.88x", "ratio"), "9.88x");
  assert.equal(formatRatioText("11.77%", "percent"), "11.77%");
  assert.equal(formatRatioText("-0.50", "ratio"), "-0.50x");
  assert.equal(formatRatioText("—", "ratio"), "—");
  const dscr = resolveRowFormat("DSCR (x)", undefined, "keur");
  assert.deepEqual(dscr, { kind: "ratio" });
  for (const unit of ["EUR", "kEUR", "mEUR"]) assert.equal(formatStatementCell("1.25", dscr, unit, 0), "1.25x");
});

test("row classification: canonical unit metadata wins; label heuristic uses word boundaries", () => {
  assert.deepEqual(resolveRowFormat("Tax", undefined, "keur"), { kind: "money", base: "kEUR" });
  assert.deepEqual(resolveRowFormat("Net Tax", null, "keur"), { kind: "money", base: "kEUR" });
  assert.deepEqual(resolveRowFormat("Senior debt (aggregate) — DSCR (x)", undefined, "keur"), { kind: "ratio" });
  assert.deepEqual(resolveRowFormat("Equity IRR", undefined, "keur"), { kind: "percent" });
  assert.deepEqual(resolveRowFormat("Anything", "x", "keur"), { kind: "ratio" });
  assert.deepEqual(resolveRowFormat("Anything", "eur", "keur"), { kind: "money", base: "EUR" });
  assert.deepEqual(resolveRowFormat("Revenues", undefined, "keur"), { kind: "money", base: "kEUR" });
  assert.equal(formatMoneyText("1,000", "EUR", "kEUR", 1), "1.0");
});

test("unit labels", () => {
  assert.equal(sheetUnitLabel("keur"), "kEUR");
  assert.equal(sheetUnitLabel("x"), "x");
  assert.equal(sheetUnitLabel(undefined), "unit unavailable");
  assert.equal(formatUnitLabel({ kind: "money", base: "kEUR" }, "mEUR"), "mEUR");
  assert.equal(formatUnitLabel({ kind: "ratio" }, "mEUR"), "x");
});

test("plotValue positions marks from the authoritative displayed number only", () => {
  assert.equal(plotValue("1,232.50"), 1232.5);
  assert.equal(plotValue("(33.70)"), -33.7);
  assert.equal(plotValue("—"), null);
  assert.equal(plotValue("NOT AVAILABLE"), null);
});
