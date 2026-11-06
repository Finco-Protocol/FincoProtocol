// UX-PR2a — read-only inline CAPEX month cells for the Lines grid.
// ONE source of truth: the saved profile document (GET capex/profiles) and the canonical server preview of exactly that saved document
// (GET capex/preview).  Nothing here allocates, rounds, sums or normalises a financial value; month amounts are server-formatted strings.
// Editing a profile stays in the existing Monthly schedule (CapexStudio, its own Save): this hook holds NO draft state that could drift from it.
import { useEffect, useState } from "react";
import { encodeSpec, fetchCapexPreview, fetchCapexProfiles } from "./api";
import type { Draft } from "./types";

export const MAX_SPEC_CHARS = 8000;

export interface TimelineRow {
  shape: string;
  /** "100%" ONLY when the server's own plan validated this saved row (its allocator requires the weights to total 100%); otherwise "—". The browser sums nothing. */
  sigma: string;
  /** Server month amounts M1..Mn, or null when the server did not return a valid allocation for this item. */
  cells: string[] | null;
  status: "valid" | "invalid" | "unavailable";
  detail: string | null;
}
export type CapexTimelineState =
  | { project: string; kind: "idle" }
  | { project: string; kind: "loading" }
  | { project: string; kind: "error"; code: string; message: string }
  | { project: string; kind: "ready"; months: number; rows: Record<string, TimelineRow>; bound: boolean; bindingCode: string; baseCase: boolean };

export function useCapexSavedTimeline(project: string, enabled: boolean, reloadKey: number): CapexTimelineState {
  const [state, setState] = useState<CapexTimelineState>({ project, kind: "idle" });
  useEffect(() => {
    if (!enabled) { setState({ project, kind: "idle" }); return undefined; }
    const controller = new AbortController();
    setState({ project, kind: "loading" });
    void (async () => {
      const profiles = await fetchCapexProfiles(project, controller.signal);
      if (controller.signal.aborted) return;
      if (profiles.ok !== true) { setState({ project, kind: "error", code: profiles.code, message: profiles.message ?? "The saved timeline could not be read." }); return; }
      const draft: Draft = {};
      for (const [key, row] of Object.entries(profiles.saved.rows)) draft[key] = { shape: row.shape, explicit: row.explicit, milestone: row.milestone };
      const binding = profiles.saved.binding;
      const base = { months: profiles.months, bound: binding.bound, bindingCode: binding.code, baseCase: profiles.edit.base_case };
      const keys = profiles.items.map((item) => item.item_key);
      const savedKeys = keys.filter((key) => draft[key]?.shape);
      if (savedKeys.length === 0) { setState({ project, kind: "ready", rows: {}, ...base }); return; }
      const spec = encodeSpec(keys, draft);
      if (spec.length > MAX_SPEC_CHARS) {
        setState({ project, kind: "error", code: "SPEC_TOO_LARGE", message: "The saved profile is too large to preview inline. Open the Monthly schedule for the full view." });
        return;
      }
      const preview = await fetchCapexPreview(project, spec, controller.signal);
      if (controller.signal.aborted) return;
      const rows: Record<string, TimelineRow> = {};
      for (const key of savedKeys) {
        const saved = draft[key];
        rows[key] = { shape: saved.shape, sigma: "—", cells: null, status: "unavailable", detail: null };
      }
      if (preview.ok !== true) {
        for (const key of savedKeys) rows[key].detail = preview.message ?? "The server preview is unavailable.";
        setState({ project, kind: "ready", rows, ...base });
        return;
      }
      // The preview and the saved profile must describe the same snapshot and the same construction length; otherwise nothing is shown as authoritative.
      if (preview.content_hash !== profiles.save.content_hash || preview.plan.months_count !== profiles.months) {
        for (const key of savedKeys) rows[key].detail = "The preview and the saved profile are from different saved states. Reload.";
        setState({ project, kind: "ready", rows, ...base });
        return;
      }
      for (const planRow of preview.plan.rows) {
        const row = rows[planRow.item_key];
        if (!row) continue;
        row.status = planRow.status;
        row.sigma = planRow.status === "valid" ? "100%" : "—";
        row.detail = planRow.error_detail ?? planRow.error_code;
        if (planRow.status === "valid") row.cells = preview.plan.months.map((m) => m.items[planRow.item_key] ?? "—");
      }
      setState({ project, kind: "ready", rows, ...base });
    })();
    return () => controller.abort();
  }, [project, enabled, reloadKey]);
  return state;
}
