// RC-REACT-MVP — committed-Run KPI comparison inside the Scenarios section.
//
// Replaces the former "unavailable" notice now that the canonical WF-React-3
// projection exists.  This is a thin read-only container over the existing
// insights components and client: it adds no data-access layer, selects nothing
// automatically, never changes the active scenario, never saves or runs, and
// computes no financial value (every figure and delta comes from the server).
// A scenario's saved assumptions (the assumption compare above) are a different
// thing from its committed Run results (this panel).

import { useEffect, useState } from "react";
import { HistoricalRunSelector, ScenarioComparison, fetchInsights, fetchInsightsHistory } from "../insights";
import type { HistoryPayload, InsightsPayload } from "../insights";
import "../insights/insights.css";

export function ScenarioKpiComparison({ project }: { project: string }) {
  const [history, setHistory] = useState<HistoryPayload | null>(null);
  const [selected, setSelected] = useState<string[]>([]);
  const [payload, setPayload] = useState<InsightsPayload | null>(null);
  const [request, setRequest] = useState<{ ids: string[]; sequence: number } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    setHistory(null); setSelected([]); setPayload(null); setRequest(null); setError("");
    void fetchInsightsHistory(project, controller.signal).then((result) => {
      if (controller.signal.aborted) return;
      if (result.ok) setHistory(result); else setError(result.message || result.code);
    }).catch(() => { /* effect cancelled */ });
    return () => controller.abort();
  }, [project]);

  useEffect(() => {
    if (!request) return undefined;
    const controller = new AbortController();
    setBusy(true); setPayload(null); setError("");
    void fetchInsights(project, request.ids, controller.signal).then((result) => {
      if (controller.signal.aborted) return;
      if (result.ok) setPayload(result); else setError(result.message || result.code);
      setBusy(false);
    }).catch(() => { if (!controller.signal.aborted) { setError("Committed Run evidence could not be read."); setBusy(false); } });
    return () => controller.abort();
  }, [project, request]);

  // Evidence is rendered only for exactly the Runs the user selected, in that order.
  const matching = payload && history && payload.project.project_id === history.project.project_id
    && payload.runs.length === selected.length
    && payload.runs.every((run, index) => run.identity.history_id === selected[index]);

  return (
    <section className="fm-card fm-section fi-insights" aria-label="Committed Run KPI comparison" data-kpi-compare="committed-runs">
      <div className="fm-card-title"><h3>Scenario KPI comparison (committed Runs)</h3><span>read-only · persisted evidence only</span></div>
      <p className="fm-info-note" role="note">
        Compares the results of committed Runs you select, one to three. It does not use the active scenario, runs nothing and calculates nothing
        in the browser. A scenario&rsquo;s saved assumptions (above) are not its committed Run results; a scenario without a committed Run shows none.
      </p>
      {!history && <p className="fm-info-note" role="status">{error || "Reading committed Run history…"}</p>}
      {history && (
        <>
          <HistoricalRunSelector history={history} selected={selected} busy={busy}
            onChange={(ids) => { setSelected(ids); setPayload(null); }}
            onRead={() => setRequest((previous) => ({ ids: [...selected], sequence: (previous?.sequence ?? 0) + 1 }))} />
          {error && <p role="alert" className="fm-info-note">{error}</p>}
          <div aria-live="polite">{busy ? "Reading selected committed evidence…" : ""}</div>
          {matching && payload && <ScenarioComparison payload={payload} />}
        </>
      )}
    </section>
  );
}
