import assert from "node:assert/strict";
import test from "node:test";
import {
  buildContractPayload, contractClass, countContractEdits, isIsoDate, newPpaStream, nextUniqueId,
  parseContractModel, parseNonNegative, parseStrictDecimal, validateContractModel, validateNewCostLine,
} from "../../src/app/workflow/ModelWorkflowValidation.ts";

const fixed = {
  version: 2, technology: "solar", indexation_basis: "OPERATING_YEAR",
  streams: [{ id: "ppa-1", type: "ppa", start_date: "2027-01-01", end_date: "2037-01-01", volume_share: 0.8,
    price_eur_mwh: 60, indexation_rate: 0, settlement: "SAME_PERIOD", source_ref: "PPA signed 2026" }],
};
const indexed = { ...fixed, streams: [{ ...fixed.streams[0], indexation_rate: 0.02,
  index_series: [[1, 1.0, "CPI"]], indexation_timing: { method: "x", start_rule: "COD" }, price_rounding: { mode: "x" } }] };
const scheduled = { ...fixed, streams: [{ ...fixed.streams[0], price_curve: [
  { period_start: "2027-01-01", price_eur_mwh: 60 }, { period_start: "2028-01-01", price_eur_mwh: 62 }] }] };

const model = (payload) => {
  const parsed = parseContractModel(JSON.stringify(payload));
  assert.equal(parsed.ok, true);
  return parsed.model;
};

test("strict decimal parsing rejects ambiguous forms", () => {
  for (const bad of ["", "  ", "1,5", "1e3", "NaN", "Infinity", "0x10", "1.2.3", "--1", "€5"]) {
    assert.equal(parseStrictDecimal(bad).ok, false, `${JSON.stringify(bad)} must be refused`);
  }
  for (const good of ["0", "12", "-3.5", "+4", ".5", "7."]) assert.equal(parseStrictDecimal(good).ok, true, good);
  assert.equal(parseNonNegative("-1").ok, false);
  assert.equal(parseNonNegative("1.5", 1).ok, false);
});

test("ISO dates must be real calendar dates", () => {
  assert.equal(isIsoDate("2027-02-28"), true);
  assert.equal(isIsoDate("2027-02-30"), false);
  assert.equal(isIsoDate("27-02-28"), false);
  assert.equal(isIsoDate("2027/02/28"), false);
});

test("contract classes: Fixed, Indexed and Scheduled", () => {
  assert.equal(contractClass(model(fixed).streams[0], []), "Fixed");
  const idx = model(indexed);
  assert.equal(contractClass(idx.streams[0], idx.preservedKeys[0]), "Indexed");
  assert.deepEqual(idx.preservedKeys[0], ["index_series", "indexation_timing", "price_rounding"]);
  assert.equal(contractClass(model(scheduled).streams[0], []), "Scheduled");
});

test("a valid book has no field errors; invalid values map to the exact field", () => {
  assert.deepEqual(validateContractModel(model(fixed)), {});
  const m = model(fixed);
  m.streams[0].price_eur_mwh = "-5";
  m.streams[0].end_date = "2026-01-01";
  m.streams[0].volume_share = "1.5";
  m.streams[0].source_ref = " ";
  const errors = validateContractModel(m);
  assert.deepEqual(Object.keys(errors).sort(), [
    "streams.0.end_date", "streams.0.price_eur_mwh", "streams.0.source_ref", "streams.0.volume_share"]);
});

test("only a merchant contract may omit the volume share", () => {
  const m = model(fixed);
  m.streams[0].volume_share = "";
  assert.match(validateContractModel(m)["streams.0.volume_share"], /explicit volume share/);
  m.streams[0].type = "merchant";
  assert.equal(validateContractModel(m)["streams.0.volume_share"], undefined);
});

test("duplicate identities are rejected", () => {
  const m = model(fixed);
  m.streams.push({ ...m.streams[0], isNew: true });
  m.preservedKeys.push([]);
  assert.equal(validateContractModel(m)["streams.1.id"], "Contract identities must be unique.");
});

test("scheduled curves must be strictly ascending inside the tenor", () => {
  const m = model(scheduled);
  m.streams[0].curve = [
    { period_start: "2028-01-01", price_eur_mwh: "62" },
    { period_start: "2028-01-01", price_eur_mwh: "63" },
    { period_start: "2040-01-01", price_eur_mwh: "64" },
    { period_start: "2027-13-01", price_eur_mwh: "x" },
  ];
  const errors = validateContractModel(m);
  assert.match(errors["streams.0.curve.1.period_start"], /strictly ascending/);
  assert.match(errors["streams.0.curve.2.period_start"], /outside the contract tenor/);
  assert.match(errors["streams.0.curve.3.period_start"], /real date/);
  assert.ok(errors["streams.0.curve.3.price_eur_mwh"]);
});

test("a curve cannot be combined with indexation or a version-1 book", () => {
  const m = model(scheduled);
  m.streams[0].indexation_rate = "0.02";
  assert.match(validateContractModel(m)["streams.0.indexation_rate"], /cannot also be indexed/);
  const v1 = model({ ...scheduled, version: 1 });
  assert.match(validateContractModel(v1)["streams.0.curve"], /version-2/);
});

test("version-3 and malformed payloads are not editable", () => {
  assert.equal(parseContractModel(JSON.stringify({ ...fixed, version: 3 })).ok, false);
  assert.equal(parseContractModel("{nope").ok, false);
  assert.equal(parseContractModel("[]").ok, false);
});

test("editing preserves every key the guided editor does not own", () => {
  const raw = JSON.stringify(indexed);
  const m = model(indexed);
  m.streams[0].price_eur_mwh = "61.25";
  const out = JSON.parse(buildContractPayload(raw, m));
  assert.equal(out.streams[0].price_eur_mwh, 61.25);
  assert.deepEqual(out.streams[0].index_series, indexed.streams[0].index_series);
  assert.deepEqual(out.streams[0].indexation_timing, indexed.streams[0].indexation_timing);
  assert.deepEqual(out.streams[0].price_rounding, indexed.streams[0].price_rounding);
  assert.equal(out.indexation_basis, "OPERATING_YEAR");
  assert.equal(out.streams[0].settlement, "SAME_PERIOD");
});

test("an unedited model round-trips to an equivalent payload", () => {
  for (const payload of [fixed, indexed, scheduled]) {
    const raw = JSON.stringify(payload);
    const out = JSON.parse(buildContractPayload(raw, model(payload)));
    assert.deepEqual(out, payload);
  }
});

test("new streams carry only explicit canonical PPA keys and a unique identity", () => {
  const m = model(fixed);
  const added = newPpaStream(m.streams, { start: "2027-01-01", end: "2037-01-01" });
  assert.equal(added.id, "ppa");
  m.streams.push({ ...added, id: "ppa", price_eur_mwh: "55", source_ref: "x" });
  assert.equal(nextUniqueId(["ppa", "ppa-2"], "ppa"), "ppa-3");
  m.preservedKeys.push([]);
  const out = JSON.parse(buildContractPayload(JSON.stringify(fixed), m));
  assert.deepEqual(Object.keys(out.streams[1]).sort(), [
    "end_date", "id", "indexation_rate", "price_eur_mwh", "settlement", "source_ref", "start_date", "type", "volume_share"]);
  assert.equal(out.streams[1].volume_share, null);
});

test("edit counting ignores untouched drafts", () => {
  const saved = model(fixed), draft = model(fixed);
  assert.equal(countContractEdits(saved, draft), 0);
  draft.streams[0].price_eur_mwh = "61";
  draft.streams[0].source_ref = "other";
  assert.equal(countContractEdits(saved, draft), 2);
});

test("new cost lines are validated against eligible groups and numeric syntax", () => {
  const ok = { group: "C.02", label: "Extra works", amount_keur: "-12.5", inflation_pct: "0", notes: "" };
  assert.deepEqual(validateNewCostLine(ok, "capex", ["C.02"]), {});
  const bad = { group: "C.13", label: " ", amount_keur: "1e3", inflation_pct: "x", notes: "" };
  assert.deepEqual(Object.keys(validateNewCostLine(bad, "opex", ["B.01"])).sort(), ["amount_keur", "group", "inflation_pct", "label"]);
});
