// WS-2 / M-008, M-013 — maps the PPA editor's whole-contract draft to per-field pending edits.
//
// The PPA editor keeps a typed `ContractModel` draft.  The store needs (a) a reviewable list of what changed and
// (b) the exact serialised contract document Save All submits.  Percent fields are listed as the human percent the
// user typed, with the canonical ratio carried as `canonical` (exact decimal shift, never floating point).

import type { ContractModel, StreamDraft } from "../workflow/ModelWorkflowValidation";
import { toDisplay } from "./percent";
import type { StageInput } from "./pendingEdits";

type FieldSpec = { field: keyof StreamDraft; label: string; unit: string; percent?: boolean };

const FIELDS: readonly FieldSpec[] = [
  { field: "id", label: "Contract identity", unit: "" },
  { field: "start_date", label: "Start date", unit: "date" },
  { field: "end_date", label: "End date", unit: "date" },
  { field: "volume_share", label: "Contracted volume share", unit: "%", percent: true },
  { field: "price_eur_mwh", label: "Tariff", unit: "€/MWh" },
  { field: "indexation_rate", label: "Annual indexation", unit: "%", percent: true },
  { field: "source_ref", label: "Source reference", unit: "" },
  { field: "capture_rate", label: "Capture rate", unit: "0-1" },
];

const shown = (spec: FieldSpec, canonical: string) =>
  spec.percent && canonical.trim() !== "" ? (toDisplay(canonical) ?? canonical) : canonical;

/** One `StageInput` per changed field / added / removed contract / changed price curve.  `errors` keyed `${stream}.${field}`. */
export function ppaStageInputs(saved: ContractModel, draft: ContractModel, errors: Readonly<Record<string, string>> = {}): StageInput[] {
  const out: StageInput[] = [];
  const base = { section: "ppa" as const };
  draft.streams.forEach((stream, i) => {
    const before = saved.streams[i];
    const name = (before?.id || stream.id || `Contract ${i + 1}`);
    if (!before) {
      out.push({ ...base, key: `${stream.id || `new-${i}`}:added`, label: `${stream.id || "New contract"} · added`, unit: "", baseline: "", value: "new PPA contract", meta: { contract: stream.id } });
      return;
    }
    for (const spec of FIELDS) {
      const a = String(before[spec.field] ?? ""), b = String(stream[spec.field] ?? "");
      const error = errors[`${i}.${spec.field}`];
      if (a === b && !error) continue;
      out.push({
        ...base, key: `${before.id}:${spec.field}`, label: `${name} · ${spec.label}`, unit: spec.unit,
        baseline: shown(spec, a), value: shown(spec, b), canonical: spec.percent ? b : undefined, error,
        meta: { contract: before.id },
      });
    }
    if (JSON.stringify(before.curve) !== JSON.stringify(stream.curve)) {
      out.push({ ...base, key: `${before.id}:price_curve`, label: `${name} · Scheduled price curve`, unit: "€/MWh",
        baseline: before.curve ? `${before.curve.length} points` : "none", value: stream.curve ? `${stream.curve.length} points` : "none", meta: { contract: before.id } });
    }
  });
  for (let i = draft.streams.length; i < saved.streams.length; i += 1) {
    const gone = saved.streams[i];
    out.push({ ...base, key: `${gone.id}:removed`, label: `${gone.id} · removed`, unit: "", baseline: "contract", value: "removed", meta: { contract: gone.id } });
  }
  return out;
}

/** Fresh canonical baselines (display form) for already staged PPA edits, for `rebase` after the saved contract moved. */
export function ppaBaselines(saved: ContractModel, edits: ReadonlyArray<{ id: string; key: string }>): Record<string, { value: string }> {
  const out: Record<string, { value: string }> = {};
  for (const edit of edits) {
    const at = edit.key.lastIndexOf(":");
    const stream = saved.streams.find((s) => s.id === edit.key.slice(0, at));
    const spec = FIELDS.find((f) => f.field === edit.key.slice(at + 1));
    out[edit.id] = { value: stream && spec ? shown(spec, String(stream[spec.field] ?? "")) : "" };
  }
  return out;
}
