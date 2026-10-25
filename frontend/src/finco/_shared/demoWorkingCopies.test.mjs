import assert from "node:assert/strict";
import test from "node:test";
import { createDemoWorkingCopy, createLocalDemoProject, listDemoWorkingCopies } from "./demoWorkingCopies.ts";
import {
  demoSessionStoragePrefix,
  DEMO_WORKING_COPIES_KEY,
  discardDemoDraftsToLastSave,
  readDemoLastRunReference,
  saveDemoLastRunReference,
} from "./demoSessionKeys.ts";
import {
  classifyDraftNavigation,
  readDraftHistoryIndex,
  withDraftHistoryIndex,
} from "./draftNavigation.ts";

class MemoryStorage {
  values = new Map();
  failWriteKey = null;
  get length() { return this.values.size; }
  key(index) { return [...this.values.keys()][index] ?? null; }
  getItem(key) { return this.values.get(key) ?? null; }
  setItem(key, value) {
    if (key === this.failWriteKey) throw new Error("Blocked write");
    this.values.set(key, String(value));
  }
  removeItem(key) { this.values.delete(key); }
}

const reference = {
  id: "PRJ-0241",
  name: "Adriatic Solar I",
  technology: "Solar PV",
  size: "84 MW",
  region: "Dalmatia",
  sponsor: "Synthetic demo sponsor",
};

test("reference copies get deterministic identity, parent attribution and a clean independent state scope", () => {
  const storage = new MemoryStorage();
  const referencePrefix = demoSessionStoragePrefix(reference.id, "reference");
  const referenceDrafts = {
    "scalar-draft": { capacity: "84" },
    "scalar-saved": { capacity: "80" },
    "cost-line-draft": { capex: [["1.2"]], opex: [["0.35"]] },
    "cost-line-saved": { capex: [["1.0"]], opex: [["0.30"]] },
    "ppa-contract-drafts": { "PPA-A": { tariff: "63.50" }, "PPA-B": { tariff: "58.00" }, "PPA-C": { tariff: "61.00" } },
    "ppa-contract-saved": { "PPA-A": { tariff: "63.50" }, "PPA-B": { tariff: "58.00" }, "PPA-C": { tariff: "61.00" } },
    "facility-drafts": { "Senior Debt A": { commitment: "42.0" }, "Junior / Mezzanine": { commitment: "6.0" } },
    "facility-saved": { "Senior Debt A": { commitment: "42.0" }, "Junior / Mezzanine": { commitment: "6.0" } },
    "scenario-drafts": { base: { powerDelta: "0" }, downside: { powerDelta: "-12" }, upside: { powerDelta: "8" } },
    "scenario-saved": { base: { powerDelta: "0" }, downside: { powerDelta: "-12" }, upside: { powerDelta: "8" } },
    "timeline-draft": { start: "2026-01-01" },
    "tax-draft": { rate: "25" },
  };
  for (const [key, value] of Object.entries(referenceDrafts)) {
    storage.setItem(`${referencePrefix}${key}`, JSON.stringify(value));
  }
  storage.setItem(`${referencePrefix}scalar-save-acknowledged`, JSON.stringify(true));

  const copy = createDemoWorkingCopy(reference, storage);
  const copyPrefix = demoSessionStoragePrefix(copy.id);
  assert.equal(copy.id, "DEMO-WC-PRJ-0241-01");
  assert.equal(copy.parentReferenceId, reference.id);
  assert.equal(copy.parentReferenceName, reference.name);
  assert.equal(copy.kind, "reference-copy");
  assert.equal(copy.note, "Demo only — not persisted");
  for (const key of ["scalar-draft", "cost-line-draft", "ppa-contract-drafts", "facility-drafts", "scenario-drafts", "timeline-draft", "tax-draft"]) {
    assert.deepEqual(JSON.parse(storage.getItem(`${copyPrefix}${key}`)), referenceDrafts[key]);
  }
  const savedToDraft = {
    "scalar-saved": "scalar-draft",
    "cost-line-saved": "cost-line-draft",
    "ppa-contract-saved": "ppa-contract-drafts",
    "facility-saved": "facility-drafts",
    "scenario-saved": "scenario-drafts",
  };
  for (const [savedKey, draftKey] of Object.entries(savedToDraft)) {
    assert.deepEqual(JSON.parse(storage.getItem(`${copyPrefix}${savedKey}`)), referenceDrafts[draftKey]);
  }
  assert.equal(JSON.parse(storage.getItem(`${copyPrefix}scalar-save-acknowledged`)), false);

  storage.setItem(`${copyPrefix}scalar-draft`, JSON.stringify({ capacity: "90" }));
  storage.setItem(`${copyPrefix}ppa-contract-drafts`, JSON.stringify({ "PPA-A": { tariff: "99" } }));
  storage.setItem(`${copyPrefix}facility-drafts`, JSON.stringify({ "Senior Debt A": { commitment: "99" } }));
  storage.setItem(`${copyPrefix}scenario-drafts`, JSON.stringify({ base: { powerDelta: "-99" } }));
  storage.setItem(`${copyPrefix}cost-line-draft`, JSON.stringify({ capex: [["9.9"]], opex: [["0.35"]] }));
  assert.deepEqual(JSON.parse(storage.getItem(`${referencePrefix}scalar-draft`)), { capacity: "84" });
  assert.deepEqual(JSON.parse(storage.getItem(`${referencePrefix}ppa-contract-drafts`)), referenceDrafts["ppa-contract-drafts"]);
  assert.deepEqual(JSON.parse(storage.getItem(`${referencePrefix}facility-drafts`)), referenceDrafts["facility-drafts"]);
  assert.deepEqual(JSON.parse(storage.getItem(`${referencePrefix}scenario-drafts`)), referenceDrafts["scenario-drafts"]);
  assert.deepEqual(JSON.parse(storage.getItem(`${referencePrefix}cost-line-draft`)), referenceDrafts["cost-line-draft"]);
  assert.deepEqual(listDemoWorkingCopies(storage), [copy]);
  assert.equal(storage.getItem(DEMO_WORKING_COPIES_KEY) !== null, true);
});

test("duplicate reference copies receive distinct deterministic names and IDs", () => {
  const storage = new MemoryStorage();
  const first = createDemoWorkingCopy(reference, storage);
  const second = createDemoWorkingCopy(reference, storage);
  assert.notEqual(first.id, second.id);
  assert.notEqual(first.name, second.name);
  assert.equal(first.name, "Adriatic Solar I — Working copy");
  assert.equal(second.name, "Adriatic Solar I — Working copy (2)");
});

test("failed working-copy storage writes do not register a partial copy or reuse partial state", () => {
  const storage = new MemoryStorage();
  const sourceKey = `${demoSessionStoragePrefix(reference.id, "reference")}scalar-draft`;
  storage.setItem(sourceKey, JSON.stringify({ capacity: "84" }));
  storage.failWriteKey = `${demoSessionStoragePrefix("DEMO-WC-PRJ-0241-01")}scalar-saved`;

  assert.throws(() => createDemoWorkingCopy(reference, storage), /Could not create a local working copy/);
  assert.deepEqual(listDemoWorkingCopies(storage), []);
  assert.equal(
    [...storage.values.keys()].some(key => key.startsWith(demoSessionStoragePrefix("DEMO-WC-PRJ-0241-01"))),
    false,
  );

  storage.failWriteKey = null;
  const created = createDemoWorkingCopy(reference, storage);
  assert.equal(created.id, "DEMO-WC-PRJ-0241-01");
  assert.deepEqual(
    JSON.parse(storage.getItem(`${demoSessionStoragePrefix(created.id)}scalar-draft`)),
    { capacity: "84" },
  );
});

test("new local demo projects are session-only and do not claim a reference parent", () => {
  const storage = new MemoryStorage();
  const project = createLocalDemoProject({
    name: "New solar project",
    technology: "Solar PV",
    size: "—",
    region: "—",
    sponsor: "Demo sponsor",
  }, storage);
  assert.equal(project.id, "DEMO-LOCAL-01");
  assert.equal(project.parentReferenceId, null);
  assert.equal(project.kind, "new-demo-project");
  assert.equal(listDemoWorkingCopies(storage)[0].id, project.id);
});

test("discard restores only the active project's drafts to its last local saves", () => {
  const storage = new MemoryStorage();
  const active = demoSessionStoragePrefix("DEMO-WC-PRJ-0241-01");
  const other = demoSessionStoragePrefix("DEMO-WC-PRJ-0241-02");
  const referencePrefix = demoSessionStoragePrefix("PRJ-0241", "reference");
  const pairs = [
    ["scalar-draft", "scalar-saved"],
    ["cost-line-draft", "cost-line-saved"],
    ["ppa-contract-drafts", "ppa-contract-saved"],
    ["facility-drafts", "facility-saved"],
    ["timeline-draft", "timeline-saved"],
    ["tax-draft", "tax-saved"],
    ["scenario-drafts", "scenario-saved"],
  ];
  for (const [draft, saved] of pairs) {
    storage.setItem(`${active}${draft}`, JSON.stringify({ value: "unsaved" }));
    storage.setItem(`${active}${saved}`, JSON.stringify({ value: "last-saved" }));
    storage.setItem(`${other}${draft}`, JSON.stringify({ value: "other-copy" }));
    storage.setItem(`${referencePrefix}${draft}`, JSON.stringify({ value: "protected-reference" }));
  }

  const restored = discardDemoDraftsToLastSave(storage, "DEMO-WC-PRJ-0241-01");
  assert.equal(restored.length, pairs.length);
  for (const [draft] of pairs) {
    assert.deepEqual(JSON.parse(storage.getItem(`${active}${draft}`)), { value: "last-saved" });
    assert.deepEqual(JSON.parse(storage.getItem(`${other}${draft}`)), { value: "other-copy" });
    assert.deepEqual(JSON.parse(storage.getItem(`${referencePrefix}${draft}`)), { value: "protected-reference" });
  }
  for (const [, saved] of pairs) {
    assert.deepEqual(JSON.parse(storage.getItem(`${active}${saved}`)), { value: "last-saved" });
  }
});

test("failed discard restores previous draft storage and leaves other scopes untouched", () => {
  const storage = new MemoryStorage();
  const scope = demoSessionStoragePrefix("DEMO-WC-PRJ-0241-01");
  storage.setItem(`${scope}scalar-draft`, JSON.stringify({ value: "unsaved" }));
  storage.setItem(`${scope}scalar-saved`, JSON.stringify({ value: "last-save" }));
  storage.setItem(`${scope}cost-line-draft`, JSON.stringify({ value: "unsaved-cost" }));
  storage.setItem(`${scope}cost-line-saved`, JSON.stringify({ value: "last-cost" }));
  storage.failWriteKey = `${scope}cost-line-draft`;

  assert.throws(() => discardDemoDraftsToLastSave(storage, "DEMO-WC-PRJ-0241-01"), /Blocked write/);
  assert.deepEqual(JSON.parse(storage.getItem(`${scope}scalar-draft`)), { value: "unsaved" });
  assert.deepEqual(JSON.parse(storage.getItem(`${scope}cost-line-draft`)), { value: "unsaved-cost" });
});

test("navigation classification guards project, reference and scenario changes but preserves same-workbook routes", () => {
  const current = "https://finco.test/ModelWorkspace?projectId=DEMO-WC-PRJ-0241-01&mode=working-copy&scenario=base&sheet=input-grid#workbook";
  assert.equal(classifyDraftNavigation(current, "https://finco.test/ModelWorkspace?projectId=DEMO-WC-PRJ-0241-02&mode=working-copy"), "project");
  assert.equal(classifyDraftNavigation(current, "https://finco.test/ModelWorkspace?projectId=PRJ-0241&mode=reference"), "reference");
  assert.equal(classifyDraftNavigation(current, "https://finco.test/ModelWorkspace?projectId=DEMO-WC-PRJ-0241-01&scenario=downside&sheet=scenarios"), "scenario");
  assert.equal(classifyDraftNavigation(current, "https://finco.test/ResultsAnalysis?projectId=DEMO-WC-PRJ-0241-01&scenario=base#results"), null);
  assert.equal(classifyDraftNavigation(current, "https://finco.test/ProjectLibrary"), "project");
  assert.equal(classifyDraftNavigation(current, "https://other.test/ModelWorkspace?projectId=elsewhere"), null);
});

test("history index metadata preserves object state and supports null state", () => {
  const original = { router: "keep", nested: { route: "results" } };
  const wrapped = withDraftHistoryIndex(original, 7);
  assert.deepEqual(wrapped.router, original.router);
  assert.deepEqual(wrapped.nested, original.nested);
  assert.equal(readDraftHistoryIndex(wrapped), 7);
  assert.equal(readDraftHistoryIndex(withDraftHistoryIndex(null, 3)), 3);
  assert.equal(readDraftHistoryIndex({}), null);
});

test("fixed demo Last Run context stays scoped to its working copy and rejects unknown data", () => {
  const values = new Map();
  const storage = {
    getItem: key => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, value),
    removeItem: key => values.delete(key),
  };
  const context = { runId: "DEMO-FIXED-018", scenarioId: "base", freshness: "CURRENT_DEMO_SNAPSHOT" };
  saveDemoLastRunReference(storage, "DEMO-WC-A", context);
  assert.deepEqual(readDemoLastRunReference(storage, "DEMO-WC-A"), context);
  assert.equal(readDemoLastRunReference(storage, "DEMO-WC-B"), null);
  values.set("finco-design-demo:v2:last-run:DEMO-WC-B", JSON.stringify({ ...context, runId: "REAL-RUN-123" }));
  assert.equal(readDemoLastRunReference(storage, "DEMO-WC-B"), null);
});
