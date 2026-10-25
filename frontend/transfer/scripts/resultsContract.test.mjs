import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import {
  resolveResultsRunStatus,
  resolveResultsSnapshot,
  resultsValueText,
} from "../src/components/mockups/finco-model/_results/resultsContract.ts";
import {
  SYNTHETIC_RESULTS_SNAPSHOT,
  SYNTHETIC_RESULTS_STATUS,
} from "../src/components/mockups/finco-model/_results/syntheticResultsProvider.ts";
import {
  TRANSFER_CALLER_RESULTS_STATUS,
  TRANSFER_DEMO_RESULTS,
  TRANSFER_DEMO_RESULTS_STATUS,
  TRANSFER_EMPTY_RESULTS_STATUS,
  TRANSFER_PARTIAL_RESULTS,
} from "../src/finco-transfer/resultsFixtures.ts";
import { resolveTransferProductState } from "../src/finco-transfer/productStates.ts";
import { SYNTHETIC_RUN_PERIODS } from "../src/components/mockups/finco-model/_results/runComparisonFixtures.ts";

const viewPath = new URL("../src/components/mockups/finco-model/ResultsAnalysisView.tsx", import.meta.url);
const canvasPath = new URL("../src/components/mockups/finco-model/ResultsAnalysis.tsx", import.meta.url);
const transferPath = new URL("../src/finco-transfer/resultsFixtures.ts", import.meta.url);

test("caller-provided results override only at the demo boundary; explicit null stays empty", () => {
  const alternate = TRANSFER_PARTIAL_RESULTS;
  assert.equal(resolveResultsSnapshot(alternate, SYNTHETIC_RESULTS_SNAPSHOT), alternate);
  assert.equal(resolveResultsSnapshot(null, SYNTHETIC_RESULTS_SNAPSHOT), null);
  assert.equal(resolveResultsSnapshot(undefined, SYNTHETIC_RESULTS_SNAPSHOT), SYNTHETIC_RESULTS_SNAPSHOT);
  assert.equal(resolveResultsRunStatus(TRANSFER_CALLER_RESULTS_STATUS, alternate, SYNTHETIC_RESULTS_STATUS), TRANSFER_CALLER_RESULTS_STATUS);
  assert.equal(resolveResultsRunStatus(undefined, undefined, SYNTHETIC_RESULTS_STATUS), SYNTHETIC_RESULTS_STATUS);
  assert.equal(resolveResultsRunStatus(undefined, alternate, SYNTHETIC_RESULTS_STATUS).dataOrigin, "caller-provided");
  assert.equal(resolveResultsRunStatus(undefined, null, SYNTHETIC_RESULTS_STATUS).runState, "unavailable");
});

test("valid zero, negatives and unavailable values remain distinct", () => {
  assert.equal(resultsValueText(TRANSFER_PARTIAL_RESULTS.kpis[0].value), "0.00%");
  assert.equal(resultsValueText(TRANSFER_PARTIAL_RESULTS.kpis[1].value), "Unavailable");
  assert.equal(resultsValueText(TRANSFER_PARTIAL_RESULTS.summaryRows[0].values[0]), "0");
  assert.equal(resultsValueText(TRANSFER_PARTIAL_RESULTS.summaryRows[0].values[1]), "Unavailable");
  assert.equal(resultsValueText(SYNTHETIC_RESULTS_SNAPSHOT.summaryRows[2].values[0]), "(1.8)");
});

test("all Canvas result fixtures are fixed display data, not linked to statement or input calculations", () => {
  assert.equal(SYNTHETIC_RESULTS_SNAPSHOT.periods.length, 8);
  assert.deepEqual(SYNTHETIC_RESULTS_SNAPSHOT.kpis.map((item) => item.label), [
    "Project IRR", "Equity IRR", "NPV @ 7.0%", "Minimum DSCR",
  ]);
  assert.equal(SYNTHETIC_RESULTS_SNAPSHOT.summaryRows.length, 8);
  assert.equal(SYNTHETIC_RESULTS_SNAPSHOT.charts.revenue?.series[0]?.points.length, 8);
  assert.equal(SYNTHETIC_RESULTS_SNAPSHOT.charts.cashDebt?.series.length, 2);
  assert.equal(SYNTHETIC_RESULTS_SNAPSHOT.charts.debtService?.series[0]?.points.length, 8);
  assert.equal(SYNTHETIC_RESULTS_SNAPSHOT.history.length, 3);
  assert.equal(SYNTHETIC_RESULTS_SNAPSHOT.scenarios.length, 3);
  assert.equal(SYNTHETIC_RESULTS_SNAPSHOT.kpis[0].value.kind, "value");
  assert.equal(SYNTHETIC_RESULTS_STATUS.runState, "fixed-demo");
  assert.equal(SYNTHETIC_RESULTS_STATUS.freshness, "unknown");
  assert.equal(SYNTHETIC_RESULTS_STATUS.integrity, "not-evaluated");
  assert.equal(SYNTHETIC_RESULTS_STATUS.engineCurrency.kind, "unavailable");
});

test("transfer build owns a separate results fixture and has real empty/partial states", () => {
  assert.notEqual(TRANSFER_DEMO_RESULTS, SYNTHETIC_RESULTS_SNAPSHOT);
  assert.notEqual(TRANSFER_DEMO_RESULTS.charts.revenue, SYNTHETIC_RESULTS_SNAPSHOT.charts.revenue);
  assert.equal(TRANSFER_DEMO_RESULTS.kpis[0].value.kind, "value");
  assert.equal(TRANSFER_EMPTY_RESULTS_STATUS.runState, "not-run");
  assert.equal(TRANSFER_EMPTY_RESULTS_STATUS.dataOrigin, "unavailable");
  assert.equal(TRANSFER_CALLER_RESULTS_STATUS.runState, "stale");
  assert.equal(TRANSFER_CALLER_RESULTS_STATUS.freshness, "stale");
  assert.equal(TRANSFER_CALLER_RESULTS_STATUS.integrity, "not-evaluated");
  assert.equal(TRANSFER_PARTIAL_RESULTS.charts.revenue, null);
  assert.equal(TRANSFER_PARTIAL_RESULTS.summaryRows[0].values[0].kind, "value");
  assert.equal(TRANSFER_PARTIAL_RESULTS.summaryRows[0].values[1].kind, "unavailable");
});

test("transfer product-state matrix keeps Working Copy, Last Run, failure, engine and integrity distinct", () => {
  const notRun = resolveTransferProductState("working-copy-not-run");
  assert.equal(notRun.resultsSnapshot, null);
  assert.equal(notRun.resultsStatus.freshness, "not-run");
  assert.equal(notRun.resultsStatus.integrity, "not-evaluated");

  const current = resolveTransferProductState("last-run-current");
  assert.equal(current.resultsStatus.productContext?.workingCopyState, "saved");
  assert.equal(current.resultsStatus.freshness, "current");
  assert.equal(current.resultsStatus.engineCurrency.kind, "unavailable");
  assert.equal(current.resultsStatus.integrity, "not-evaluated");

  const stale = resolveTransferProductState("working-copy-stale");
  assert.equal(stale.resultsStatus.productContext?.workingScenarioId, "downside");
  assert.equal(stale.resultsStatus.productContext?.lastRunScenarioId, "base");
  assert.equal(stale.resultsStatus.runState, "stale");
  assert.equal(stale.resultsSnapshot, TRANSFER_DEMO_RESULTS);

  const failedAttempt = resolveTransferProductState("run-attempt-failed");
  assert.equal(failedAttempt.resultsStatus.productContext?.runAttempt?.kind, "illustrative-failure");
  assert.equal(resultsValueText(failedAttempt.resultsStatus.runId), "DEMO-LAST-022");
  assert.equal(failedAttempt.resultsSnapshot, TRANSFER_DEMO_RESULTS);

  const unavailable = resolveTransferProductState("unavailable");
  assert.equal(unavailable.resultsSnapshot, null);
  assert.equal(unavailable.resultsStatus.runState, "unavailable");
  assert.equal(unavailable.resultsStatus.engineCurrency.kind, "unavailable");
  assert.equal(unavailable.resultsStatus.integrity, "not-evaluated");

  const reference = resolveTransferProductState("protected-reference");
  assert.equal(reference.mode, "reference");
  assert.equal(reference.resultsStatus.productContext?.workingCopyMode, "reference");
  assert.equal(reference.resultsSnapshot, TRANSFER_DEMO_RESULTS);
});

test("Run Compare keeps native calendars separate and preserves missing metrics as unavailable", () => {
  const annual = SYNTHETIC_RUN_PERIODS["DEMO-FIXED-018"];
  const quarterly = SYNTHETIC_RUN_PERIODS["DEMO-FIXED-017"];
  const semiannual = SYNTHETIC_RUN_PERIODS["DEMO-FIXED-014"];
  assert.equal(annual.frequency, "Annual");
  assert.equal(quarterly.frequency, "Quarterly · 3M");
  assert.equal(semiannual.frequency, "Semiannual · 6M");
  assert.deepEqual(annual.periods.map(({ period }) => period), ["2027", "2028", "2029"]);
  assert.deepEqual(quarterly.periods.map(({ period }) => period), ["2027 Q1", "2027 Q2", "2027 Q4"]);
  assert.notDeepEqual(annual.periods.map(({ period }) => period), quarterly.periods.map(({ period }) => period));
  assert.equal(quarterly.periods[1].cfads.kind, "unavailable");
  assert.equal(quarterly.periods[1].dscr.kind, "unavailable");
  assert.equal(semiannual.periods[2].debtService.kind, "unavailable");
});

test("reusable Results view is provider-free; only Canvas composition imports the synthetic provider", async () => {
  const [view, canvas, transfer] = await Promise.all([
    readFile(viewPath, "utf8"),
    readFile(canvasPath, "utf8"),
    readFile(transferPath, "utf8"),
  ]);
  assert.match(view, /resultsSnapshot: ResultsPresentationSnapshot \| null/);
  assert.match(view, /resultsSnapshot\?\.kpis/);
  assert.match(view, /no synthetic fallback is shown/i);
  assert.doesNotMatch(view, /syntheticResultsProvider|SYNTHETIC_RESULTS_SNAPSHOT|7\.82%|12\.46%|€8\.7m|DEMO-FIXED-018/);
  assert.match(canvas, /SYNTHETIC_RESULTS_SNAPSHOT/);
  assert.doesNotMatch(transfer, /syntheticResultsProvider/);
});
