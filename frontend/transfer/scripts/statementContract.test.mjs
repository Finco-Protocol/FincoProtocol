import test from "node:test";
import assert from "node:assert/strict";
import { statementCellText, statementStatusText } from "../src/components/mockups/finco-model/_workbook/statementContract.ts";

test("statement display preserves numeric zero and keeps unavailable values distinct", () => {
  assert.equal(statementCellText("0"), "0");
  assert.equal(statementCellText("0.0"), "0.0");
  assert.equal(statementCellText(undefined), "—");
  assert.equal(statementCellText("—"), "—");
});

test("statement disclosure keeps run, freshness, integrity, and unknown engine separate", () => {
  const status = statementStatusText({
    label: "Illustrative run",
    runId: "DEMO-FIXED-018",
    freshness: "unknown",
    integrity: "not evaluated",
    engineVersion: null,
  });
  assert.equal(status.run, "Illustrative run · DEMO-FIXED-018");
  assert.equal(status.freshness, "Freshness: unknown");
  assert.equal(status.integrity, "Integrity: not evaluated");
  assert.equal(status.engine, "Engine: unknown / not connected");
});
