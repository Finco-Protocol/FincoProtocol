// Raw input + validation only. Money allocation always comes from the canonical server preview.
import { checkExplicit, parseOneMonth, parsePercentages, type CommaMode } from "./profileImport";
import type { CapexProfiles, Draft, SavedRow } from "./types";

export type ExplicitInput = { kind: "cells"; values: string[] } | { kind: "text"; text: string; commaMode?: CommaMode };
export interface ProfileDraftRow { shape: string; explicit: ExplicitInput; milestone: string }
export type ProfileDraft = Record<string, ProfileDraftRow>;
export const SHAPE_LABEL: Record<string, string> = {
  UNIFORM: "Uniform", FRONT_LOADED: "Front-loaded", BACK_LOADED: "Back-loaded", EXPLICIT: "Explicit % per month", MILESTONE: "Milestone (one month)",
};
export const emptyProfileRow = (): ProfileDraftRow => ({ shape: "", explicit: { kind: "cells", values: [] }, milestone: "" });
export function rowFromSaved(row?: SavedRow): ProfileDraftRow {
  return row ? { shape: row.shape, explicit: { kind: "cells", values: row.explicit ? row.explicit.split(",") : [] }, milestone: row.milestone } : emptyProfileRow();
}
export function profileDraftFromSaved(data: CapexProfiles): ProfileDraft {
  return Object.fromEntries([...new Set([...data.items.map(i => i.item_key), ...Object.keys(data.saved.rows)])]
    .map(key => [key, rowFromSaved(data.saved.rows[key])]));
}
export function explicitInputText(input: ExplicitInput): string {
  return input.kind === "text" ? input.text : input.values.join(", ");
}
export function explicitValues(input: ExplicitInput) {
  if (input.kind === "text") return parsePercentages(input.text, input.commaMode);
  const values = input.values.map(v => parseOneMonth(v));
  const bad = values.findIndex(v => v === null);
  return bad < 0 ? { status: "ok" as const, values: values as string[] }
    : { status: "error" as const, message: `Month ${bad + 1}: "${input.values[bad]}" is not a non-negative percentage.` };
}
/** Never pads a missing month with 0. Empty and invalid text remain in the ONE draft. */
export function editMonth(input: ExplicitInput, index: number, text: string): ExplicitInput {
  const parsed = explicitValues(input);
  const old = input.kind === "cells" ? input.values : parsed.status === "ok" ? parsed.values : [];
  const values = Array.from({ length: Math.max(old.length, index + 1) }, (_, i) => old[i] ?? "");
  values[index] = text;
  return { kind: "cells", values };
}
export function pasteMonths(input: ExplicitInput, index: number, text: string, commaMode?: CommaMode) {
  const pasted = parsePercentages(text, commaMode);
  if (pasted.status !== "ok") return pasted;
  const parsed = explicitValues(input);
  const old = input.kind === "cells" ? input.values : parsed.status === "ok" ? parsed.values : [];
  const values = Array.from({ length: Math.max(old.length, index + pasted.values.length) }, (_, i) => old[i] ?? "");
  pasted.values.forEach((v, i) => { values[index + i] = v; });
  return { status: "ok" as const, input: { kind: "cells" as const, values } };
}
export function rowProblems(row: ProfileDraftRow, months: number, shapes: readonly string[]): string[] {
  if (!row.shape) return [];
  if (!shapes.includes(row.shape)) return ["This shape is not offered by the server."];
  if (!Number.isInteger(months) || months < 1 || months > 60) return ["Construction duration is outside the canonical profile contract (1–60 months)."];
  if (row.shape === "EXPLICIT") {
    const parsed = explicitValues(row.explicit);
    if (parsed.status !== "ok") return [parsed.status === "ambiguous" ? parsed.reason : parsed.message];
    return checkExplicit(parsed.values, months).problems;
  }
  if (row.shape === "MILESTONE" && (!/^\d+$/.test(row.milestone.trim()) || Number(row.milestone) < 1 || Number(row.milestone) > months)) {
    return [`Milestone must be a construction month from 1 to ${months}.`];
  }
  return [];
}
/** Only active fields are serialised; no rounding, rescaling or amount arithmetic. */
export function rowToWire(row: ProfileDraftRow): SavedRow {
  const parsed = explicitValues(row.explicit);
  if (row.shape === "EXPLICIT" && parsed.status !== "ok") throw new Error("Resolve the monthly percentage input before previewing or saving.");
  return { shape: row.shape, explicit: row.shape === "EXPLICIT" && parsed.status === "ok" ? parsed.values.join(",") : "",
    milestone: row.shape === "MILESTONE" && /^\d+$/.test(row.milestone.trim()) ? String(Number(row.milestone)) : row.shape === "MILESTONE" ? row.milestone : "" };
}
export function wireProfileDraft(keys: readonly string[], draft: ProfileDraft): Draft {
  return Object.fromEntries(keys.map(k => [k, rowToWire(draft[k] ?? emptyProfileRow())]));
}
/** PR2c (OD-B2 gated): the D7 Save All profile document — the exact wire format
 *  `save_profiles_in_tx` parses (`{"version":1,"profiles":[{item_key, shape,
 *  explicit_percent: string[], milestone_month: int|null}]}`).  A real mutation that
 *  clears the final/only profile serialises the canonical EMPTY document
 *  (`{"version":1,"profiles":[]}`): the server parser accepts it and its canonical
 *  form is "", which removes the saved profile document inside the same transaction
 *  (the base token is still verified first).  `null` means either "nothing to save"
 *  (no mutation in evidence) or "not serialisable yet" (invalid EXPLICIT input) —
 *  a serialization error is never mistaken for a legitimate empty document. */
export function profileD7Document(keys: readonly string[], draft: ProfileDraft, saved?: ProfileDraft): string | null {
  const profiles: Array<Record<string, unknown>> = [];
  for (const key of keys) {
    const row = draft[key] ?? emptyProfileRow();
    if (!row.shape) continue;
    try {
      const wire = rowToWire(row);
      profiles.push({
        item_key: key, shape: wire.shape,
        explicit_percent: wire.explicit === "" ? [] : wire.explicit.split(","),
        milestone_month: wire.milestone === "" ? null : Number(wire.milestone),
      });
    } catch { return null; }
  }
  if (!saved) return profiles.length ? JSON.stringify({ version: 1, profiles }) : null;
  // With the saved baseline in evidence, "nothing to save" is exact: a draft equal to the
  // saved document is never serialised (with or without profiles), and a real mutation
  // serialises either the full document or the canonical EMPTY one (removal).
  const changed = [...new Set([...Object.keys(saved), ...Object.keys(draft)])]
    .some(k => !sameDraftRow(draft[k] ?? emptyProfileRow(), saved[k] ?? emptyProfileRow()));
  if (!changed) return null;
  return JSON.stringify({ version: 1, profiles });
}
export function profileDocument(keys: readonly string[], draft: ProfileDraft): Record<string, SavedRow> {
  const wire = wireProfileDraft(keys, draft);
  return Object.fromEntries(keys.filter(k => wire[k].shape).map(k => [k, wire[k]]));
}
export function sameProfileDocument(a: Record<string, SavedRow>, b: Record<string, SavedRow>): boolean {
  const keys = Object.keys(a).sort();
  return keys.join("|") === Object.keys(b).sort().join("|") && keys.every(k =>
    a[k].shape === b[k].shape && a[k].explicit === b[k].explicit && a[k].milestone === b[k].milestone);
}
export function sameDraftRow(a: ProfileDraftRow, b: ProfileDraftRow): boolean {
  try { return JSON.stringify(rowToWire(a)) === JSON.stringify(rowToWire(b)); }
  catch { return JSON.stringify(a) === JSON.stringify(b); }
}
