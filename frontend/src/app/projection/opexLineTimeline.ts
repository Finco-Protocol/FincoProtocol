// UX-PR2a — read-only inline OPEX year cells for the Lines grid.  The numbers are the server's saved-line projection (the same payload the
// Years view shows); nothing is calculated, escalated or summed in the browser.  This is NOT Last Run all-in OPEX (that stays its own panel).
import { useEffect, useState } from "react";
import { loadOpexLineYears, type Payload } from "./OpexLineYears";

export interface OpexLineTimeline { years: number[]; byLine: Record<string, { values: Array<number | null>; groupReconciles: boolean | null }>; basis: string }
export type OpexTimelineState =
  | { project: string; kind: "idle" } | { project: string; kind: "loading" }
  | { project: string; kind: "error"; code: string; message: string }
  | { project: string; kind: "ready"; data: OpexLineTimeline };

export function useOpexLineTimeline(project: string, enabled: boolean, reloadKey: number): OpexTimelineState {
  const [state, setState] = useState<OpexTimelineState>({ project, kind: "idle" });
  useEffect(() => {
    if (!enabled) { setState({ project, kind: "idle" }); return undefined; }
    const controller = new AbortController();
    setState({ project, kind: "loading" });
    void loadOpexLineYears(project, controller.signal).then((r) => {
      if (controller.signal.aborted) return;
      if (!("years" in r)) { setState({ project, kind: "error", code: r.code, message: r.message ?? "The yearly projection could not be read." }); return; }
      const p = r as Payload;
      const byLine: OpexLineTimeline["byLine"] = {};
      for (const g of p.groups) for (const l of g.lines) byLine[l.sub_line_id] = { values: l.values, groupReconciles: g.reconciles };
      setState({ project, kind: "ready", data: { years: p.years, byLine, basis: p.basis } });
    });
    return () => controller.abort();
  }, [project, enabled, reloadKey]);
  return state;
}
