import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import {
  resolveStatementRunStatus,
  resolveStatementSnapshot,
  statementCellTabIndex,
  statementCellText,
  statementStatusText,
} from "../src/components/mockups/finco-model/_workbook/statementContract.ts";
import {
  SYNTHETIC_STATEMENT_SNAPSHOT,
  SYNTHETIC_STATEMENT_STATUS,
} from "../src/components/mockups/finco-model/_workbook/syntheticStatementProvider.ts";

test("statement display preserves numeric zero and keeps unavailable values distinct", () => {
  assert.equal(statementCellText("0"), "0");
  assert.equal(statementCellText("0.0"), "0.0");
  assert.equal(statementCellText("(1.8)"), "(1.8)");
  assert.equal(statementCellText(undefined), "—");
  assert.equal(statementCellText("—"), "—");
});

test("statement table exposes one roving data-cell tab stop", () => {
  const rows = ["revenue", "opex"];
  const columns = [0, 1, 2];
  const initialStops = rows.flatMap((rowId, rowIndex) =>
    columns.map((column, columnIndex) => statementCellTabIndex(
      rowId, column, null, 0, rowIndex === 0 && columnIndex === 0,
    )),
  ).filter(tabIndex => tabIndex === 0);
  assert.equal(initialStops.length, 1);
  assert.equal(statementCellTabIndex("opex", 2, "opex", 2, false), 0);
  assert.equal(statementCellTabIndex("revenue", 2, "opex", 2, false), -1);
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

test("synthetic statement provider preserves six sheet identities, periods, and band layout", () => {
  const snapshot = SYNTHETIC_STATEMENT_SNAPSHOT;
  assert.deepEqual(snapshot.sheets.map((sheet) => sheet.id), [
    "pl", "balance", "cashflow", "cfads", "debt", "sponsor",
  ]);
  assert.deepEqual(snapshot.annualPeriods, ["2027", "2028", "2029", "2030", "2031", "2032", "2033", "2034"]);
  assert.deepEqual(snapshot.modelPeriods, [
    "2026 M10", "2026 M12", "2027 Q3", "2027 Q4", "2028 Q1", "2028 Q2", "2029 6M", "2030 6M",
  ]);
  assert.deepEqual(snapshot.periodBands, [
    { label: "Construction snapshots", span: 2 },
    { label: "Operating quarter snapshots", span: 4 },
    { label: "Operating half-year snapshots", span: 2 },
  ]);
  assert.deepEqual(snapshot.sheets.map((sheet) => sheet.rows.map((row) => row.id)), [
    ["revenue", "opex", "ebitda", "depreciation", "ebit", "finance-cost", "pbt", "tax", "net-income"],
    ["assets", "liabilities", "equity", "balance-check"],
    ["operating-cf", "investing-cf", "financing-cf", "net-change", "cash-opening", "cash-closing"],
    ["cfads-ebitda", "cash-tax", "working-capital", "reserve-movement", "cfads-total", "scheduled-service", "dscr", "cash-equity"],
    ["senior-draw", "senior-opening", "senior-idc", "senior-fee", "senior-interest", "senior-principal", "senior-service", "senior-closing"],
    ["sponsor-contributions", "sponsor-distributions", "sponsor-net-cash", "sponsor-irr", "sponsor-moic"],
  ]);

  const flatten = (rows) => rows.flatMap((row) => [row, ...(row.children ? flatten(row.children) : [])]);
  const rowsById = new Map(snapshot.sheets.flatMap((sheet) => flatten(sheet.rows)).map((row) => [row.id, row]));
  for (const sheet of snapshot.sheets) {
    assert.ok(sheet.rows.length > 0, `${sheet.id} has fixture rows`);
    for (const row of flatten(sheet.rows)) {
      assert.equal(row.annual.length, snapshot.annualPeriods.length, `${sheet.id}/${row.id} annual width`);
      assert.equal(row.model.length, snapshot.modelPeriods.length, `${sheet.id}/${row.id} model width`);
    }
  }
  assert.equal(rowsById.get("cash-operating")?.annual[0], "(1.8)");
  assert.equal(rowsById.get("working-capital")?.annual[2], "0.0");
  assert.equal(rowsById.get("balance-check")?.annual[0], "NOT EVALUATED");
});

test("synthetic debt facility snapshots keep Senior and Mezzanine rows distinct", () => {
  const debtRows = SYNTHETIC_STATEMENT_SNAPSHOT.debtRowsByFacility;
  assert.ok(debtRows?.senior?.some((row) => row.id === "senior-opening"));
  assert.ok(debtRows?.mezzanine?.some((row) => row.id === "mezz-opening"));
  assert.equal(debtRows?.senior?.some((row) => row.id === "mezz-opening"), false);
  assert.equal(debtRows?.mezzanine?.some((row) => row.id === "senior-opening"), false);
  assert.equal(SYNTHETIC_STATEMENT_STATUS.freshness, "unknown");
  assert.equal(SYNTHETIC_STATEMENT_STATUS.integrity, "not evaluated");
  assert.equal(SYNTHETIC_STATEMENT_STATUS.engineVersion, null);
});

test("external statement props replace demo data and explicit null stays unavailable", () => {
  const externalSnapshot = { ...SYNTHETIC_STATEMENT_SNAPSHOT, sheets: [] };
  assert.equal(resolveStatementSnapshot(externalSnapshot, SYNTHETIC_STATEMENT_SNAPSHOT), externalSnapshot);
  assert.equal(resolveStatementSnapshot(null, SYNTHETIC_STATEMENT_SNAPSHOT), null);
  assert.equal(resolveStatementSnapshot(undefined, SYNTHETIC_STATEMENT_SNAPSHOT), SYNTHETIC_STATEMENT_SNAPSHOT);
  assert.equal(resolveStatementRunStatus(undefined, externalSnapshot, SYNTHETIC_STATEMENT_STATUS).dataOrigin, "caller-provided");
  assert.equal(resolveStatementRunStatus(undefined, null, SYNTHETIC_STATEMENT_STATUS).dataOrigin, "unavailable");
});

test("statement presentation has no dependency on the synthetic fixture provider", async () => {
  const source = await readFile(new URL("../src/components/mockups/finco-model/_workbook/StatementWorkbook.tsx", import.meta.url), "utf8");
  const resultsView = await readFile(new URL("../src/components/mockups/finco-model/ResultsAnalysisView.tsx", import.meta.url), "utf8");
  const transferApp = await readFile(new URL("../src/finco-transfer/App.tsx", import.meta.url), "utf8");
  const contract = await readFile(new URL("../src/components/mockups/finco-model/_workbook/statementContract.ts", import.meta.url), "utf8");
  assert.doesNotMatch(source, /syntheticStatementProvider/);
  assert.doesNotMatch(resultsView, /syntheticStatementProvider/);
  assert.match(transferApp, /ResultsAnalysisView/);
  assert.doesNotMatch(transferApp, /components\/mockups\/finco-model\/ResultsAnalysis["']/);
  assert.match(source, /StatementWorkbookProps/);
  assert.match(contract, /snapshot: StatementWorkbookSnapshot \| null/);
});
