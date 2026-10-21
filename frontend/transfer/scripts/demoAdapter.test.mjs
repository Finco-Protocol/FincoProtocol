import test from "node:test";
import assert from "node:assert/strict";
import {
  applyDemoSaveResponse,
  beginDemoSave,
  formatDemoStatementValue,
  saveDemoField,
} from "../src/components/mockups/finco-model/_shared/demoAdapter.ts";

const currentState = (overrides = {}) => ({
  fieldId: "project.capacity",
  scenarioId: "base",
  editable: true,
  draftValue: "120",
  committedValue: "120",
  revision: "working-copy-17",
  latestRequestId: 0,
  lastRun: {
    runId: "DEMO-FIXED-018",
    revision: "working-copy-17",
    engineVersion: null,
    statementValue: { availability: "available", value: 0, unit: "MW" },
  },
  freshness: "CURRENT",
  integrity: "NOT_EVALUATED",
  saveState: "CLEAN",
  message: "",
  ...overrides,
});

test("successful fake save commits one scalar, preserves fixed output, and marks an older Run stale", async () => {
  const calls = [];
  const state = currentState({ draftValue: "121" });
  const outputBefore = structuredClone(state.lastRun);
  const next = await saveDemoField(state, {
    async saveField(request) {
      calls.push(request);
      return { status: "saved", revision: "working-copy-18", scenarioId: "base" };
    },
  });

  assert.equal(calls.length, 1);
  assert.deepEqual(calls[0], {
    fieldId: "project.capacity",
    scenarioId: "base",
    value: "121",
    expectedRevision: "working-copy-17",
    requestId: 1,
  });
  assert.equal(next.committedValue, "121");
  assert.equal(next.freshness, "STALE");
  assert.equal(next.integrity, "NOT_EVALUATED");
  assert.deepEqual(next.lastRun, outputBefore);
  assert.match(next.message, /No Run was invoked/);
});

test("validation error keeps the typed value and committed value unchanged", async () => {
  const state = currentState({ draftValue: "-1" });
  const next = await saveDemoField(state, {
    async saveField() {
      return { status: "invalid", message: "Capacity must be greater than zero." };
    },
  });

  assert.equal(next.draftValue, "-1");
  assert.equal(next.committedValue, "120");
  assert.equal(next.saveState, "VALIDATION_ERROR");
  assert.equal(next.freshness, "CURRENT");
  assert.equal(next.integrity, "NOT_EVALUATED");
});

test("simulated HTTP 422 validation response preserves the typed value without Run", async () => {
  let calls = 0;
  const state = currentState({ draftValue: "0" });
  const next = await saveDemoField(state, {
    async saveField() {
      calls += 1;
      return { status: "unprocessable_entity", message: "Synthetic validation error (422)." };
    },
  });

  assert.equal(calls, 1);
  assert.equal(next.draftValue, "0");
  assert.equal(next.committedValue, "120");
  assert.equal(next.saveState, "VALIDATION_ERROR");
  assert.equal(next.lastRun.runId, "DEMO-FIXED-018");
  assert.equal(next.integrity, "NOT_EVALUATED");
});

test("CAS conflict does not retry and preserves the user's draft", async () => {
  let calls = 0;
  const state = currentState({ draftValue: "122" });
  const next = await saveDemoField(state, {
    async saveField() {
      calls += 1;
      return { status: "conflict", currentRevision: "working-copy-19" };
    },
  });

  assert.equal(calls, 1);
  assert.equal(next.draftValue, "122");
  assert.equal(next.committedValue, "120");
  assert.equal(next.revision, "working-copy-17");
  assert.equal(next.freshness, "STALE");
  assert.equal(next.saveState, "CONFLICT");
});

test("fake 401 and 403 rejections preserve draft without claiming authorization", async () => {
  for (const status of ["unauthorized", "forbidden"]) {
    const next = await saveDemoField(currentState({ draftValue: "121" }), {
      async saveField() { return { status, message: `fake ${status}` }; },
    });
    assert.equal(next.draftValue, "121");
    assert.equal(next.committedValue, "120");
    assert.equal(next.saveState, "AUTH_REJECTED");
    assert.match(next.message, /fake/);
  }
});

test("protected reference values never reach the fake transport", async () => {
  let calls = 0;
  const next = await saveDemoField(currentState({ editable: false }), {
    async saveField() {
      calls += 1;
      return { status: "saved", revision: "unexpected" };
    },
  });

  assert.equal(calls, 0);
  assert.equal(next.saveState, "READ_ONLY");
  assert.equal(next.committedValue, "120");
});

test("out-of-order older response cannot replace the latest draft or acknowledgement", () => {
  const first = beginDemoSave(currentState({ draftValue: "121" }));
  const latest = beginDemoSave({ ...first.state, draftValue: "122" });
  const next = applyDemoSaveResponse(latest.state, first.request, {
    status: "saved",
    revision: "working-copy-18",
    scenarioId: "base",
  });

  assert.equal(next.latestRequestId, latest.request.requestId);
  assert.equal(next.draftValue, "122");
  assert.equal(next.committedValue, "120");
  assert.equal(next.saveState, "STALE_RESPONSE");
  assert.match(next.message, /Out-of-order/);
});

test("a response for another scenario is rejected without changing the selected scenario", () => {
  const state = currentState({ draftValue: "121" });
  const attempt = beginDemoSave(state);
  const next = applyDemoSaveResponse(attempt.state, attempt.request, {
    status: "saved",
    revision: "downside-18",
    scenarioId: "downside",
  });

  assert.equal(next.scenarioId, "base");
  assert.equal(next.committedValue, "120");
  assert.equal(next.saveState, "CONTEXT_MISMATCH");
  assert.equal(next.integrity, "NOT_EVALUATED");
});

test("missing Last Run stays UNKNOWN after save and does not change integrity", async () => {
  const next = await saveDemoField(currentState({ draftValue: "121", lastRun: null, freshness: "UNKNOWN" }), {
    async saveField() { return { status: "saved", revision: "working-copy-18", scenarioId: "base" }; },
  });
  assert.equal(next.freshness, "UNKNOWN");
  assert.equal(next.lastRun, null);
  assert.equal(next.integrity, "NOT_EVALUATED");
});

test("CURRENT freshness is independent from financial integrity", async () => {
  const state = currentState({ draftValue: "121", lastRun: { ...currentState().lastRun, revision: "working-copy-18" } });
  const next = await saveDemoField(state, {
    async saveField() { return { status: "saved", revision: "working-copy-18", scenarioId: "base" }; },
  });
  assert.equal(next.freshness, "CURRENT");
  assert.equal(next.integrity, "NOT_EVALUATED");
});

test("available zero is distinct from an unavailable statement value", () => {
  assert.equal(formatDemoStatementValue({ availability: "available", value: 0, unit: "DSCR" }), "0 DSCR");
  assert.equal(formatDemoStatementValue({ availability: "unavailable", reason: "not in fixture" }), "— (not in fixture)");
});

test("Save contract has no Run operation and a Save with unavailable output preserves the fixture", async () => {
  const transport = {
    async saveField() { return { status: "saved", revision: "working-copy-18", scenarioId: "base" }; },
  };
  const state = currentState({
    draftValue: "121",
    lastRun: {
      runId: "DEMO-FIXED-018",
      revision: "working-copy-17",
      engineVersion: null,
      statementValue: { availability: "unavailable", reason: "not in the fixed fixture" },
    },
  });
  const fixedBefore = structuredClone(state.lastRun);
  const next = await saveDemoField(state, transport);

  assert.deepEqual(Object.keys(transport), ["saveField"]);
  assert.equal(next.saveState, "DEMO_SAVED");
  assert.equal(next.freshness, "STALE");
  assert.deepEqual(next.lastRun, fixedBefore);
  assert.equal(next.lastRun.statementValue.availability, "unavailable");
  assert.match(next.message, /No Run was invoked/);
});
