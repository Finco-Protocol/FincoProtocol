import assert from "node:assert/strict";
import test from "node:test";
import {
  parsePreviewState,
  previewStateOptions,
  resolvePlainLanguageStatus,
} from "../../src/finco/_shared/plainLanguageStatus.ts";

test("all required development preview states have user-facing labels", () => {
  assert.deepEqual(previewStateOptions.map(({ id }) => id), [
    "up-to-date",
    "unsaved",
    "saved-not-calculated",
    "calculating",
    "calculation-failed",
    "attention",
    "no-results",
    "reference-read-only",
    "project-changed",
    "scenario-no-results",
  ]);
  for (const option of previewStateOptions) {
    assert.equal(parsePreviewState(option.id), option.id);
    assert.equal(resolvePlainLanguageStatus(option.id, {}).label, option.label);
  }
  assert.equal(parsePreviewState("unknown-state"), null);
});

test("real read-only, invalid and unsaved conditions override conflicting preview selections", () => {
  assert.equal(
    resolvePlainLanguageStatus("up-to-date", { readOnly: true }).label,
    "This is a read-only reference — create a working copy to edit",
  );
  assert.equal(
    resolvePlainLanguageStatus("up-to-date", { invalidInputs: true }).label,
    "Some inputs need attention",
  );
  assert.equal(
    resolvePlainLanguageStatus("up-to-date", { unsaved: true }).label,
    "You have unsaved changes",
  );
});

test("default and saved states do not imply a calculation", () => {
  assert.equal(resolvePlainLanguageStatus(null, {}).label, "No results yet — run the model");
  const saved = resolvePlainLanguageStatus(null, { saved: true });
  assert.equal(saved.label, "Changes saved — results not yet calculated");
  assert.match(saved.detail, /does not calculate/i);
});
