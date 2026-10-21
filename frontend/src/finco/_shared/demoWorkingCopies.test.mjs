import assert from "node:assert/strict";
import test from "node:test";
import { createDemoWorkingCopy, createLocalDemoProject, listDemoWorkingCopies } from "./demoWorkingCopies.ts";
import { demoSessionStoragePrefix, DEMO_WORKING_COPIES_KEY } from "./demoSessionKeys.ts";

class MemoryStorage {
  values = new Map();
  get length() { return this.values.size; }
  key(index) { return [...this.values.keys()][index] ?? null; }
  getItem(key) { return this.values.get(key) ?? null; }
  setItem(key, value) { this.values.set(key, String(value)); }
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
