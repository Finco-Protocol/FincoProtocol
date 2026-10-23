import assert from "node:assert/strict";
import test from "node:test";
import {
  contextualFindings,
  filterFindings,
  insightChangesSummary,
  presentFindings,
} from "../../src/finco/_insight/insightContract.ts";
import { SYNTHETIC_INSIGHT_FINDINGS } from "../../src/finco/_insight/syntheticInsightFixtures.ts";

const baseContext = {
  projectName: "Solar Example",
  projectId: "DEMO-SOL-01",
  technology: "Solar PV",
  scenarioId: "base",
  activeArea: "overview",
  activeScreen: "Project overview",
  statusLabel: "Results are up to date",
  statusDetail: "Fixed illustrative results only.",
  readOnly: false,
  hasUnsavedEdits: false,
  savedInPreview: true,
  conflict: false,
  runState: "current",
  runId: "DEMO-FIXED-018",
  runScenario: "base",
  resultOriginLabel: "Fixed illustrative example",
  resultDateLabel: "Not supplied",
  engineCurrencyLabel: "Not supplied in this preview",
  resultChecksLabel: "Not assessed",
};

test("Review and Findings share the same four fixed examples and severity/area/status filters", () => {
  const findings = presentFindings(SYNTHETIC_INSIGHT_FINDINGS, baseContext);
  assert.equal(findings.length, 4);
  assert.deepEqual(
    contextualFindings(findings, "overview").map(({ id }) => id),
    findings.map(({ id }) => id),
  );
  assert.deepEqual(
    filterFindings(findings, { severity: "high", area: "all", status: "all" }).map(({ id }) => id),
    ["mezz-dscr-reference"],
  );
  assert.deepEqual(
    filterFindings(findings, { severity: "all", area: "inputs", status: "all" }).map(({ id }) => id),
    ["ppa-term-reference"],
  );
  assert.ok(findings.every((finding) => finding.title && finding.why));
});

test("fixed advisory examples are shown only with a current eligible preview state", () => {
  const current = presentFindings(SYNTHETIC_INSIGHT_FINDINGS, baseContext);
  const debt = current.find(({ id }) => id === "mezz-dscr-reference");
  assert.equal(debt?.evidenceState, "current");
  assert.equal(debt?.displayedValue, "1.08x");
  assert.equal(debt?.displayedThreshold, "1.20x");
  assert.equal(debt?.adviceText, "Review the debt-service assumptions.");

  for (const blockedContext of [
    { ...baseContext, runState: "stale" },
    { ...baseContext, runState: "not-run" },
    { ...baseContext, runState: "unknown" },
    { ...baseContext, hasUnsavedEdits: true },
    { ...baseContext, readOnly: true },
    { ...baseContext, conflict: true },
  ]) {
    const blocked = presentFindings(SYNTHETIC_INSIGHT_FINDINGS, blockedContext);
    assert.ok(blocked.every(({ priorityGroup }) => priorityGroup === "could-not-check"));
    assert.ok(blocked.every(({ adviceText, displayedValue }) => adviceText === undefined && displayedValue === "Unavailable"));
  }
});

test("missing evidence stays unavailable and never becomes a passing lender conclusion", () => {
  const findings = presentFindings(SYNTHETIC_INSIGHT_FINDINGS, baseContext);
  const tax = findings.find(({ id }) => id === "tax-schedule-detail");
  const scenario = findings.find(({ id }) => id === "scenario-run-evidence");
  assert.equal(tax?.priorityGroup, "could-not-check");
  assert.equal(tax?.displayedValue, "Unavailable");
  assert.equal(tax?.adviceText, undefined);
  assert.equal(scenario?.priorityGroup, "could-not-check");
  assert.equal(findings.some(({ title }) => /all good|passed|approved/i.test(title)), false);
});

test("context filtering keeps analysis relevant to the active workbook area", () => {
  const findings = presentFindings(SYNTHETIC_INSIGHT_FINDINGS, baseContext);
  assert.deepEqual(
    contextualFindings(findings, "inputs").map(({ id }) => id),
    ["ppa-term-reference"],
  );
  assert.deepEqual(
    contextualFindings(findings, "scenarios").map(({ id }) => id).sort(),
    ["scenario-run-evidence"],
  );
});

test("Changes reports aggregate status without inventing per-field history", () => {
  const summary = insightChangesSummary({ ...baseContext, hasUnsavedEdits: true, statusLabel: "You have unsaved changes" });
  assert.equal(summary.inputs, "You have unsaved changes");
  assert.equal(summary.currentStatus, "You have unsaved changes");
  assert.match(summary.note, /overall preview state only/i);
  assert.doesNotMatch(JSON.stringify(summary), /before value|after value|changed ppa|field history/i);
});
