// WF-React-1 — canonical EUR/kEUR/mEUR display conversion and number formatting.
// Pure presentation checks: exact decimal-string scaling, no binary float drift.
import assert from "node:assert/strict";
import test from "node:test";
import { loadUnits } from "./loadUnits.mjs";

const {
  classifyRowUnit, formatMetricDisplay, formatMoneyText, formatRatioText, formatStatementCell, formatUnitLabel,
  plotValue, resolveRowFormat, sheetUnitLabel,
} = await loadUnits();

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

// ── Monetary KPI precision regression matrix (independent BigInt oracle) ────────────
// The oracle shares no code with units.ts: it works on exact rationals (BigInt) and
// rounds half away from zero.
const EXP = { EUR: 0, kEUR: 3, mEUR: 6 };
function oracle(text, base, unit, precision) {
  const raw = text.replace(/,/g, "").replace(/^\((.*)\)$/, "-$1");
  const negative = raw.startsWith("-");
  const [i, f = ""] = raw.replace("-", "").split(".");
  let num = BigInt(i + f);                       // value = num / 10^f.length
  let scalePow = f.length + (EXP[unit] - EXP[base]);   // value_in_unit = num * 10^(EXP[base]-EXP[unit]) / 10^f.length
  // value_in_unit = num / 10^scalePow ; round to `precision` places
  let digits;
  if (scalePow <= precision) digits = num * 10n ** BigInt(precision - scalePow);
  else {
    const div = 10n ** BigInt(scalePow - precision);
    digits = num / div;
    if ((num % div) * 2n >= div) digits += 1n;   // half away from zero (magnitude)
  }
  let str = digits.toString().padStart(precision + 1, "0");
  const whole = precision ? str.slice(0, -precision) : str;
  const frac = precision ? "." + str.slice(-precision) : "";
  const grouped = whole.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  const body = grouped + frac;
  return negative && digits !== 0n ? `(${body})` : body;
}

const MONETARY_SAMPLES = ["2,305", "500", "22,495", "0", "0.00", "1,232.5", "999.9995", "0.0004", "-0.0004",
  "-1,234.5675", "(2.5)", "-500", "1.005", "2.675", "0.0005", "12,345,678.9"];

test("monetary KPI matrix: every unit x precision x value matches the independent oracle", () => {
  let checked = 0;
  for (const base of ["EUR", "kEUR", "mEUR"]) {
    for (const unit of ["EUR", "kEUR", "mEUR"]) {
      for (const precision of [0, 1, 2, 3]) {
        for (const sample of MONETARY_SAMPLES) {
          const shown = formatMetricDisplay(`${sample} ${base}`, unit, precision);
          assert.equal(shown, `${oracle(sample, base, unit, precision)} ${unit}`, `${sample} ${base} -> ${unit}/${precision}`);
          assert.ok(!/\(0(\.0+)?\)/.test(shown), `no negative zero: ${shown}`);
          checked += 1;
        }
      }
    }
  }
  assert.equal(checked, 3 * 3 * 4 * MONETARY_SAMPLES.length);
});

test("canonical-unit monetary KPI still honours the selected precision (no byte-identical bypass)", () => {
  assert.equal(formatMetricDisplay("2,305 kEUR", "kEUR", 0), "2,305 kEUR");
  assert.equal(formatMetricDisplay("2,305 kEUR", "kEUR", 1), "2,305.0 kEUR");
  assert.equal(formatMetricDisplay("2,305 kEUR", "kEUR", 3), "2,305.000 kEUR");
  assert.equal(formatMetricDisplay("22,495.55 kEUR", "kEUR", 1), "22,495.6 kEUR");
  assert.equal(formatMetricDisplay("22,495.55 kEUR", "kEUR", 0), "22,496 kEUR");
  assert.equal(formatMetricDisplay("999.95 kEUR", "kEUR", 1), "1,000.0 kEUR", "carry");
  assert.equal(formatMetricDisplay("-0.04 kEUR", "kEUR", 1), "0.0 kEUR", "no negative zero");
  assert.equal(formatMetricDisplay("-500 kEUR", "kEUR", 2), "(500.00) kEUR");
  assert.equal(formatMetricDisplay("500 kEUR", "mEUR", 3), "0.500 mEUR");
  assert.equal(formatMetricDisplay("500 kEUR", "EUR", 0), "500,000 EUR");
});

test("IRR, XIRR, MOIC, DSCR, percentages, ratios and unavailable text are never treated as currency", () => {
  for (const unit of ["EUR", "kEUR", "mEUR"]) {
    for (const precision of [0, 1, 2, 3]) {
      for (const text of ["11.77%", "31.25%", "16.80%", "-2.5%", "9.88x", "1.25x", "0.00x", "NOT AVAILABLE",
        "—", "", "n/a", "UNAVAILABLE", "1.97", "500"]) {
        assert.equal(formatMetricDisplay(text, unit, precision), text, `${text} must be verbatim (${unit}/${precision})`);
      }
    }
  }
  // a currency suffix with a non-numeric body is not converted either
  assert.equal(formatMetricDisplay("NOT AVAILABLE kEUR", "mEUR", 2), "NOT AVAILABLE kEUR");
});

test("row unit provenance is explicit; ambiguous metadata is never silently converted", () => {
  assert.deepEqual(classifyRowUnit("DSCR (x)", "x", "keur"), { format: { kind: "ratio" }, source: "canonical-row-unit" });
  assert.deepEqual(classifyRowUnit("Revenues", "keur", "keur"), { format: { kind: "money", base: "kEUR" }, source: "canonical-row-unit" });
  assert.deepEqual(classifyRowUnit("DSCR (x)", undefined, "keur"), { format: { kind: "ratio" }, source: "label-inference" });
  assert.deepEqual(classifyRowUnit("Equity IRR", undefined, "keur"), { format: { kind: "percent" }, source: "label-inference" });
  assert.deepEqual(classifyRowUnit("Revenues", undefined, "keur"), { format: { kind: "money", base: "kEUR" }, source: "sheet-unit" });
  // no row unit, no hint in the label, unrecognised sheet unit: shown verbatim, never converted
  const ambiguous = classifyRowUnit("Mystery line", undefined, "widgets");
  assert.deepEqual(ambiguous, { format: { kind: "unspecified" }, source: "unspecified" });
  for (const unit of ["EUR", "kEUR", "mEUR"]) {
    assert.equal(formatStatementCell("1,232.50", ambiguous.format, unit, 3), "1,232.50");
    assert.equal(formatStatementCell("—", ambiguous.format, unit, 3), "—");
    assert.equal(formatStatementCell("", ambiguous.format, unit, 3), "—");
  }
  assert.equal(formatUnitLabel(ambiguous.format, "mEUR"), "unit unavailable");
  assert.deepEqual(classifyRowUnit("Mystery line", undefined, undefined).format, { kind: "unspecified" });
});
