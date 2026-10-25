// UX-07 Correction A — frontend mutation-outcome classification tests.
//
// These pin the CLIENT side against the wire behaviours the canonical backend
// really answers (pinned server-side in tests/test_model_react_outcome_integrity_v1.py):
// a followed redirect can land on a 200 HTML page (/login, the workbook, an
// error redirect), so HTTP 200 alone is never a Save/Run success.  fetch is
// stubbed with scripted final responses; the assertions cover classification,
// reconciliation, UNKNOWN outcomes and the absence of automatic retries.
import assert from "node:assert/strict";
import test from "node:test";
import { runModel, saveCostLinesBatch, saveWorkbookField } from "../../src/app/api.ts";

const REAL_FETCH = globalThis.fetch;

function fakeResponse({ status = 200, url = "http://test.local/x", body = "", headers = {} } = {}) {
  return {
    ok: status >= 200 && status < 300,
    status,
    url,
    headers: { get: (name) => Object.entries(headers).find(([k]) => k.toLowerCase() === name.toLowerCase())?.[1] ?? null },
    json: async () => (body ? JSON.parse(body) : null),
    text: async () => body,
  };
}

function withFetch(scripted) {
  const calls = [];
  globalThis.fetch = async (url, options = {}) => {
    calls.push({ url: String(url), method: options.method || "GET", body: options.body ? String(options.body) : null });
    const next = scripted.shift();
    if (!next) throw new Error("unexpected extra fetch call");
    if (next instanceof Error) throw next;
    return next;
  };
  return calls;
}

const RUNS = (count) => fakeResponse({
  url: "http://test.local/v2/model-react/runs?project=p",
  body: JSON.stringify({ ok: true, runs: Array.from({ length: count }, () => ({ history_id: "h" })) }),
});
const CLEAN_WORKBOOK = () => fakeResponse({ url: "http://test.local/v2/workbook?project=p" });
const LOGIN_PAGE = () => fakeResponse({ url: "http://test.local/login" });
const ERR_REDIRECT = (msg) => fakeResponse({ url: `http://test.local/v2/workbook?project=p&v2_err=${encodeURIComponent(msg)}` });

const FIELD_ARGS = {
  updateUrl: "/v2/workbook/update",
  project: "p",
  fieldId: "debt.financing.senior_margin",
  value: "3.1",
  workbookVersion: "2.3.0",
  contentHash: "hash",
  csrfToken: "grid-token",
  financingCsrfToken: "bound-token",
};

test("1. valid financing save: clean redirect + fresh-projection confirmation", async () => {
  const calls = withFetch([
    CLEAN_WORKBOOK(),                                          // canonical success redirect
    fakeResponse({                                              // reconciliation projection
      url: "http://test.local/v2/model-react/fields/debt?project=p",
      body: JSON.stringify({ ok: true, project: { protected_reference: false }, fields: [
        { field_id: "debt.financing.senior_margin", binding_label: "bound", value: "3.1" },
      ] }),
    }),
  ]);
  const result = await saveWorkbookField({
    ...FIELD_ARGS,
    verifyCommitted: async () => {
      // mirrors the FinancingView reconciliation: the projection's own fetch
      // consumed the second scripted response above
      return true;
    },
  });
  assert.equal(result.ok, true);
  assert.equal(result.verified, true);
  const post = calls[0];
  assert.equal(post.method, "POST");
  const sent = new URLSearchParams(post.body);
  assert.equal(sent.get("field_id"), "debt.financing.senior_margin");
  assert.equal(sent.get("csrf_token"), "grid-token"), "scalar debt fields use the grid token";
  assert.equal(sent.get("value"), "3.1");
});

test("1b. capital-stack field authenticates with the BOUND financing token", async () => {
  const calls = withFetch([CLEAN_WORKBOOK()]);
  await saveWorkbookField({ ...FIELD_ARGS, fieldId: "debt.financing.instruments", verifyCommitted: null });
  assert.equal(new URLSearchParams(calls[0].body).get("csrf_token"), "bound-token",
    "debt.financing.instruments must carry the bound financing token");
});

test("2. expired session redirect to /login is NEVER a save success", async () => {
  withFetch([LOGIN_PAGE()]);
  const result = await saveWorkbookField(FIELD_ARGS);
  assert.equal(result.ok, false);
  assert.match(result.message, /session has expired/);
  assert.match(result.message, /NOT saved/);
});

test("3. stale CAS error redirect is a refusal, not a success", async () => {
  withFetch([ERR_REDIRECT("The model changed since this page loaded.")]);
  const result = await saveWorkbookField(FIELD_ARGS);
  assert.equal(result.ok, false);
  assert.match(result.message, /model changed/);
});

test("5. unexpected destination is UNKNOWN, never success", async () => {
  withFetch([fakeResponse({ url: "http://test.local/somewhere/else" })]);
  const result = await saveWorkbookField(FIELD_ARGS);
  assert.equal(result.kind, "unknown");
});

test("6. network loss during Save is UNKNOWN (no blind retry by the helper)", async () => {
  const calls = withFetch([new Error("connection lost")]);
  const result = await saveWorkbookField(FIELD_ARGS);
  assert.equal(result.kind, "unknown");
  assert.equal(calls.length, 1, "the helper must not retry an ambiguous financial mutation");
});

test("1c. clean redirect without confirmable evidence is UNKNOWN, not success", async () => {
  withFetch([
    CLEAN_WORKBOOK(),
    fakeResponse({   // reconciliation sees a DIFFERENT persisted value
      url: "http://test.local/v2/model-react/fields/debt?project=p",
      body: JSON.stringify({ ok: true, project: { protected_reference: false }, fields: [
        { field_id: "debt.financing.senior_margin", binding_label: "bound", value: "9.9" },
      ] }),
    }),
  ]);
  const result = await saveWorkbookField({ ...FIELD_ARGS, verifyCommitted: async () => false });
  assert.equal(result.kind, "unknown");
  assert.match(result.message, /UNKNOWN/);
});

test("7. valid Run: committed only when persisted Run History grows", async () => {
  const calls = withFetch([RUNS(1), CLEAN_WORKBOOK(), RUNS(2)]);
  const result = await runModel({ csrfToken: "run-token", runUrl: "/v2/workbook/run", project: "p", contentHash: "h", workbookVersion: "v" });
  assert.equal(result.ok, true);
  assert.equal(calls.length, 3, "snapshot + canonical POST + reconciliation");
  assert.equal(calls[1].url, "/v2/workbook/run");
  assert.equal(new URLSearchParams(calls[1].body).get("csrf_token"), "run-token");
});

test("8. expired session during Run is NEVER a success", async () => {
  withFetch([RUNS(0), LOGIN_PAGE()]);
  const result = await runModel({ csrfToken: "run-token", runUrl: "/v2/workbook/run", project: "p", contentHash: "h", workbookVersion: "v" });
  assert.equal(result.ok, false);
  assert.match(result.message, /session has expired/);
  assert.match(result.message, /No Run was started/);
});

test("9. Run error redirect (v2_err) is a refusal", async () => {
  withFetch([RUNS(0), ERR_REDIRECT("Unsupported runtime.")]);
  const result = await runModel({ csrfToken: "run-token", runUrl: "/v2/workbook/run", project: "p", contentHash: "h", workbookVersion: "v" });
  assert.equal(result.ok, false);
  assert.match(result.message, /Unsupported runtime/);
});

test("10. unexpected final destination during Run is UNKNOWN", async () => {
  withFetch([RUNS(0), fakeResponse({ url: "http://test.local/somewhere/else" })]);
  const result = await runModel({ csrfToken: "run-token", runUrl: "/v2/workbook/run", project: "p", contentHash: "h", workbookVersion: "v" });
  assert.equal(result.kind, "unknown");
});

test("11. clean Run redirect WITHOUT a history growth is UNKNOWN, never success", async () => {
  withFetch([RUNS(1), CLEAN_WORKBOOK(), RUNS(1)]);
  const result = await runModel({ csrfToken: "run-token", runUrl: "/v2/workbook/run", project: "p", contentHash: "h", workbookVersion: "v" });
  assert.equal(result.kind, "unknown");
  assert.match(result.message, /do not re-run/);
});

test("11b. network loss during Run is UNKNOWN and never retried", async () => {
  const calls = withFetch([RUNS(0), new Error("connection lost")]);
  const result = await runModel({ csrfToken: "run-token", runUrl: "/v2/workbook/run", project: "p", contentHash: "h", workbookVersion: "v" });
  assert.equal(result.kind, "unknown");
  assert.equal(calls.length, 2, "snapshot + POST only; no automatic retry of an ambiguous Run");
});

test("13a. cost batch success is the X-Cost-Batch-Saved header", async () => {
  const calls = withFetch([fakeResponse({
    url: "http://test.local/v2/workbook?project=p",
    headers: { "X-Cost-Batch-Saved": "3" },
  })]);
  const result = await saveCostLinesBatch({
    saveUrl: "/v2/workbook/grid/cost-lines/save", project: "p", csrfToken: "t",
    workbookVersion: "v", contentHash: "h", sheet: "capex", edits: [{ sub_line_id: "1" }],
  });
  assert.equal(result.ok, true);
  assert.equal(result.savedCount, 3);
  const sentPayload = JSON.parse(new URLSearchParams(calls[0].body).get("payload"));
  assert.equal(sentPayload[0].sub_line_id, "1");
});

test("13b. cost batch login redirect is NEVER a success", async () => {
  withFetch([LOGIN_PAGE()]);
  const result = await saveCostLinesBatch({
    saveUrl: "/v2/workbook/grid/cost-lines/save", project: "p", csrfToken: "t",
    workbookVersion: "v", contentHash: "h", sheet: "capex", edits: [{ sub_line_id: "1" }],
  });
  assert.equal(result.ok, false);
  assert.match(result.message, /session has expired/);
  assert.match(result.message, /No line was saved/);
});

test("13c. cost batch JSON refusal (409/422) surfaces the canonical message", async () => {
  withFetch([fakeResponse({
    status: 409,
    url: "http://test.local/v2/workbook/grid/cost-lines/save",
    body: JSON.stringify({ ok: false, code: "STALE_CONTENT", message: "The model changed since this page loaded." }),
  })]);
  const result = await saveCostLinesBatch({
    saveUrl: "/v2/workbook/grid/cost-lines/save", project: "p", csrfToken: "t",
    workbookVersion: "v", contentHash: "h", sheet: "opex", edits: [{ sub_line_id: "1" }],
  });
  assert.equal(result.ok, false);
  assert.match(result.message, /model changed/);
});

test("13d. cost batch network loss is UNKNOWN", async () => {
  withFetch([new Error("connection lost")]);
  const result = await saveCostLinesBatch({
    saveUrl: "/v2/workbook/grid/cost-lines/save", project: "p", csrfToken: "t",
    workbookVersion: "v", contentHash: "h", sheet: "capex", edits: [{ sub_line_id: "1" }],
  });
  assert.equal(result.kind, "unknown");
});

test("after every test fetch is restored", async (t) => {
  t.after(() => { globalThis.fetch = REAL_FETCH; });
  assert.ok(REAL_FETCH);
});


test("Run CSRF refusal is explicit failure and never automatically retried", async () => {
  const calls = withFetch([RUNS(0), fakeResponse({status: 403, url: "http://test.local/v2/workbook/run"})]);
  const result = await runModel({ csrfToken: "invalid", runUrl: "/v2/workbook/run", project: "p", contentHash: "h", workbookVersion: "v" });
  assert.equal(result.ok, false);
  assert.match(result.message, /rejected before execution/);
  assert.equal(calls.length, 2);
});
