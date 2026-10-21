import test from "node:test";
import assert from "node:assert/strict";
import {
  isEditablePeriodCell,
  periodCellError,
  periodHeaders,
  periodRows,
  pastePeriodRectangle,
} from "../src/components/mockups/finco-model/_workbook/periodGrid.ts";

const capexRows = periodRows("capex", "quarterly");
const capexValues = capexRows.map((row) => [...row.values]);

test("CAPEX fixture exposes 18 monthly periods and preserves a zero amount", () => {
  assert.equal(periodHeaders("capex", "quarterly").length, 18);
  assert.equal(periodCellError(capexRows[1], "0"), undefined);
  assert.equal(isEditablePeriodCell("capex", "quarterly", 1, 0), true);
});

test("CRLF TSV rectangle validates and stages as one full draft", () => {
  const result = pastePeriodRectangle(
    "0.25\t0.40\r\n0.10\t0.20\r\n",
    1,
    0,
    capexRows,
    capexValues,
    "capex",
    "quarterly",
  );
  assert.equal(result.error, undefined);
  assert.equal(result.values?.[1][0], "0.25");
  assert.equal(result.values?.[2][1], "0.20");
  assert.equal(capexValues[1][0], "0.2");
});

test("a rectangle containing a negative number is rejected without a partial result", () => {
  const result = pastePeriodRectangle(
    "0.25\t-0.40\r\n",
    1,
    0,
    capexRows,
    capexValues,
    "capex",
    "quarterly",
  );
  assert.equal(result.values, undefined);
  assert.match(result.error, /nonnegative/);
  assert.equal(capexValues[1][0], "0.2");
});

test("blank, ragged and out-of-bounds rectangles are rejected", () => {
  assert.match(pastePeriodRectangle("", 1, 0, capexRows, capexValues, "capex", "quarterly").error, /empty/);
  assert.match(pastePeriodRectangle("0.2\t0.3\r\n0.4\r\n", 1, 0, capexRows, capexValues, "capex", "quarterly").error, /ragged/);
  assert.match(pastePeriodRectangle("0.2\t0.3", 1, 17, capexRows, capexValues, "capex", "quarterly").error, /bounds/);
});

test("blank TSV cells and oversized rectangles reject atomically", () => {
  const before = structuredClone(capexValues);
  const blankCell = pastePeriodRectangle("0.2\t", 1, 0, capexRows, capexValues, "capex", "quarterly");
  const oversized = pastePeriodRectangle(Array(19).fill("0.4").join("\t"), 1, 0, capexRows, capexValues, "capex", "quarterly");
  assert.equal(blankCell.values, undefined);
  assert.match(blankCell.error, /finite nonnegative decimal/);
  assert.equal(oversized.values, undefined);
  assert.match(oversized.error, /bounds/);
  assert.deepEqual(capexValues, before);
});

test("locked summary rows reject pastes and leave the source draft untouched", () => {
  const before = structuredClone(capexValues);
  const result = pastePeriodRectangle(
    "7.0",
    11,
    0,
    capexRows,
    capexValues,
    "capex",
    "quarterly",
  );
  assert.equal(result.values, undefined);
  assert.match(result.error, /locked/);
  assert.deepEqual(capexValues, before);
});

test("invalid calendar dates are rejected atomically while valid ISO dates pass", () => {
  const invalid = pastePeriodRectangle(
    "2027-02-30",
    10,
    0,
    capexRows,
    capexValues,
    "capex",
    "quarterly",
  );
  const valid = pastePeriodRectangle(
    "2027-02-28",
    10,
    0,
    capexRows,
    capexValues,
    "capex",
    "quarterly",
  );
  assert.equal(invalid.values, undefined);
  assert.match(invalid.error, /calendar date/);
  assert.equal(valid.values?.[10][0], "2027-02-28");
});

test("semiannual OPEX is a locked reference, not an aggregate", () => {
  const rows = periodRows("opex", "semiannual");
  assert.equal(periodHeaders("opex", "semiannual").length, 6);
  assert.equal(isEditablePeriodCell("opex", "semiannual", 1, 0), false);
  assert.equal(periodCellError(rows[11], "—"), undefined);
  assert.equal(rows[1].values[0], "0.70");
});

test("60/80/120-quarter fixtures retain a 60-quarter edit boundary and explicit unavailable tail", () => {
  for (const quarters of [60, 80, 120]) {
    const rows = periodRows("opex", "quarterly", quarters);
    assert.equal(periodHeaders("opex", "quarterly", quarters).length, quarters);
    assert.equal(periodHeaders("opex", "semiannual", quarters).length, quarters / 2);
    assert.equal(isEditablePeriodCell("opex", "quarterly", 1, 59, quarters), true);
    assert.equal(isEditablePeriodCell("opex", "quarterly", 1, 60, quarters), false);
  }

  const stressRows = periodRows("opex", "quarterly", 120);
  const editableDraft = periodRows("opex", "quarterly", true).map((row) => [...row.values]);
  assert.equal(stressRows[1].values[59], "0.00");
  assert.equal(stressRows[1].values[60], "—");
  const before = structuredClone(editableDraft);
  const rejected = pastePeriodRectangle("0.1\t0.2", 1, 59, stressRows, editableDraft, "opex", "quarterly", 120);
  assert.equal(rejected.values, undefined);
  assert.match(rejected.error, /locked/);
  assert.deepEqual(editableDraft, before);
});
