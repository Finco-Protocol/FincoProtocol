import assert from "node:assert/strict";
import test from "node:test";
import {
  canonicalFincoHref,
  contextFromRoute,
  FINCO_ROUTE_CONFIG,
  resolveFincoRoute,
} from "../src/finco-transfer/routes.ts";
import { TRANSFER_DEMO_RUN_STATUS, TRANSFER_DEMO_STATEMENT } from "../src/finco-transfer/fixtures.ts";
import {
  TRANSFER_CALLER_RESULTS_STATUS,
  TRANSFER_DEMO_RESULTS,
  TRANSFER_DEMO_RESULTS_STATUS,
  TRANSFER_EMPTY_RESULTS_STATUS,
  TRANSFER_PARTIAL_RESULTS,
} from "../src/finco-transfer/resultsFixtures.ts";

const basePath = "/finco-transfer/";
globalThis.window = { location: { origin: "https://finco.test" } };

test("transfer route table exposes distinct library, workbook and results routes", () => {
  assert.deepEqual(FINCO_ROUTE_CONFIG.map((route) => route.id), ["library", "workspace", "results"]);
  assert.deepEqual(FINCO_ROUTE_CONFIG.map((route) => route.component), ["ProjectLibrary", "ModelWorkspace", "ResultsAnalysis"]);
});

test("canonical routes retain project identity and map to the existing page", () => {
  const route = resolveFincoRoute("/finco-transfer/projects/COPY%3A42/workbook", "?scenario=downside", basePath);
  assert.equal(route.page, "workspace");
  assert.equal(route.projectId, "COPY:42");
  assert.equal(resolveFincoRoute("/finco-transfer/projects/PRJ-0241/results", "", basePath).page, "results");
});

test("existing preview-page links canonicalize inside the React app", () => {
  const workspace = canonicalFincoHref(
    "https://finco.test/finco-transfer/ModelWorkspace?projectId=PRJ-0236&technology=Onshore+wind#workbook",
    basePath,
    "PRJ-0241",
  );
  assert.equal(
    workspace,
    "/finco-transfer/projects/PRJ-0236/workbook?projectId=PRJ-0236&technology=Onshore+wind#workbook",
  );
  assert.equal(
    canonicalFincoHref("https://finco.test/outside", basePath, "PRJ-0241"),
    null,
  );
});

test("route context carries project, scenario, contract and facility identity", () => {
  const route = resolveFincoRoute("/finco-transfer/projects/PRJ-0236/results", "?scenario=upside&contract=PPA-C&facility=SHL&mode=reference", basePath);
  assert.deepEqual(contextFromRoute(route, route.search), {
    projectId: "PRJ-0236",
    projectName: "Adriatic Solar I",
    technology: "Solar PV",
    mode: "reference",
    scenarioId: "upside",
    contractId: "PPA-C",
    facilityId: "SHL",
  });
});

test("external statement provider keeps zero distinct and labels fixed synthetic status", () => {
  assert.equal(TRANSFER_DEMO_STATEMENT.sheets.length, 6);
  assert.equal(TRANSFER_DEMO_STATEMENT.sheets[0].rows[0].annual[0], "13.1");
  assert.equal(TRANSFER_DEMO_STATEMENT.sheets[3].rows[0].annual[0], "1.25");
  assert.equal(TRANSFER_DEMO_RUN_STATUS.freshness, "unknown");
  assert.equal(TRANSFER_DEMO_RUN_STATUS.integrity, "not evaluated");
  assert.equal(TRANSFER_DEMO_RUN_STATUS.engineVersion, null);
  assert.equal(TRANSFER_DEMO_RUN_STATUS.dataOrigin, "synthetic-demo");
});

test("transfer results fixture is independent from the Canvas provider and supports empty/partial caller states", () => {
  assert.equal(TRANSFER_DEMO_RESULTS.kpis[0].value.text, "7.82%");
  assert.equal(TRANSFER_DEMO_RESULTS.summaryRows.length, 8);
  assert.equal(TRANSFER_DEMO_RESULTS_STATUS.dataOrigin, "synthetic-demo");
  assert.equal(TRANSFER_EMPTY_RESULTS_STATUS.runState, "not-run");
  assert.equal(TRANSFER_CALLER_RESULTS_STATUS.freshness, "stale");
  assert.equal(TRANSFER_PARTIAL_RESULTS.kpis[0].value.text, "0.00%");
  assert.equal(TRANSFER_PARTIAL_RESULTS.kpis[1].value.kind, "unavailable");
});
