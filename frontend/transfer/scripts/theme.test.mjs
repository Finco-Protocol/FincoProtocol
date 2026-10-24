import assert from "node:assert/strict";
import test from "node:test";
import {
  applyTheme,
  FINCO_THEME_IDS,
  FINCO_THEME_LABELS,
  isFincoThemeId,
  loadStoredTheme,
  storeTheme,
} from "../../src/finco/_shared/theme.ts";

function fakeStorage(initial = {}) {
  const data = new Map(Object.entries(initial));
  return {
    getItem: (k) => (data.has(k) ? data.get(k) : null),
    setItem: (k, v) => { data.set(k, String(v)); },
    removeItem: (k) => { data.delete(k); },
  };
}

test("theme catalogue is exactly the three owner-approved choices", () => {
  assert.deepEqual([...FINCO_THEME_IDS], ["b-slate-teal", "d-high-contrast", "g-forest-green-white"]);
  for (const id of FINCO_THEME_IDS) assert.equal(typeof FINCO_THEME_LABELS[id], "string");
});

test("isFincoThemeId accepts only known ids", () => {
  assert.equal(isFincoThemeId("b-slate-teal"), true);
  assert.equal(isFincoThemeId("g-forest-green-white"), true);
  assert.equal(isFincoThemeId("dark-g-obsolete"), false);
  assert.equal(isFincoThemeId(""), false);
  assert.equal(isFincoThemeId(null), false);
  assert.equal(isFincoThemeId(undefined), false);
});

test("loadStoredTheme returns null on missing storage, empty or unknown values", () => {
  assert.equal(loadStoredTheme(null), null);
  assert.equal(loadStoredTheme(fakeStorage()), null);
  assert.equal(loadStoredTheme(fakeStorage({ fincoReactTheme: "not-a-theme" })), null);
  assert.equal(loadStoredTheme(fakeStorage({ fincoReactTheme: "d-high-contrast" })), "d-high-contrast");
});

test("storeTheme persists valid ids, clears on null, reports refusal without throwing", () => {
  const s = fakeStorage();
  assert.equal(storeTheme("g-forest-green-white", s), true);
  assert.equal(loadStoredTheme(s), "g-forest-green-white");
  assert.equal(storeTheme(null, s), true);
  assert.equal(loadStoredTheme(s), null);
  assert.equal(storeTheme("b-slate-teal", null), false);
  const throwing = { getItem() { throw new Error("denied"); }, setItem() { throw new Error("denied"); }, removeItem() { throw new Error("denied"); } };
  assert.equal(loadStoredTheme(throwing), null);
  assert.equal(storeTheme("b-slate-teal", throwing), false);
});

test("applyTheme writes the attribute only on the given host element", () => {
  const host = { attrs: new Map(), setAttribute(k, v) { this.attrs.set(k, v); }, removeAttribute(k) { this.attrs.delete(k); } };
  applyTheme(host, "b-slate-teal");
  assert.equal(host.attrs.get("data-fm-theme"), "b-slate-teal");
  applyTheme(host, null);
  assert.equal(host.attrs.has("data-fm-theme"), false);
  applyTheme(null, "b-slate-teal");
});
