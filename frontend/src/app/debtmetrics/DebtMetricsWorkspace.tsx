import { useCallback, useEffect, useRef, useState } from "react";
import "../../styles/rcm-debtmetrics.css";
import { useReportPrecision } from "../ReportPrecision";
import { LoadingNote, UnavailableNote } from "../workflow/workflowShared";
import { fetchDebtMetrics, type DebtMetricsFailure, type DebtMetricsPayload } from "./api";
import { CovenantTable } from "./CovenantTable";
import { RUN_PARAM, selectedRunFromUrl } from "./debtMetricsLink";
import { DscrProfileChart } from "./DscrProfileChart";
import { KpiRow } from "./KpiRow";
import { PeriodSchedule, type ScheduleHandle } from "./PeriodSchedule";
import { ReservesPanel } from "./ReservesPanel";

const RUN_TEXT: Record<string, string> = {
  "LAST RUN · CURRENT": "Completed · current Last Run", "LAST RUN · STALE": "Completed · Last Run is STALE (inputs changed since)", HISTORICAL: "Completed · historical Run",
};
const label = (v: string) => v.replace(/_/g, " ").toLowerCase().replace(/^./, (c) => c.toUpperCase());

/** Debt Metrics of ONE committed Run: covenant monitor, key metrics, DSCR profile, distribution & reserves and the dated schedule.  Read-only: it never
 *  runs the model, writes nothing and shows only what that Run persisted.  The three outcomes — Run, Integrity, Credit — are shown independently. */
export function DebtMetricsWorkspace({ project, reloadKey, onEditTerms }: { project: string; reloadKey: number; onEditTerms?: () => void }) {
  const [runId, setRunId] = useState<string | null>(selectedRunFromUrl);
  const [state, setState] = useState<{ payload: DebtMetricsPayload } | { failure: DebtMetricsFailure } | null>(null);
  const [nonce, setNonce] = useState(0);
  const schedule = useRef<ScheduleHandle>(null);
  const { precision } = useReportPrecision();

  useEffect(() => {
    const controller = new AbortController();
    setState(null);
    (async () => {
      try {
        const result = await fetchDebtMetrics(project, runId, controller.signal);
        if (controller.signal.aborted) return;
        setState(result.ok ? { payload: result } : { failure: result });
      } catch { /* aborted: a newer request owns the view */ }
    })();
    return () => controller.abort();
  }, [project, runId, reloadKey, nonce]);

  const choose = useCallback((id: string) => {
    const next = id || null;
    setRunId(next);
    const url = new URL(window.location.href);
    if (next) url.searchParams.set(RUN_PARAM, next); else url.searchParams.delete(RUN_PARAM);
    window.history.replaceState(null, "", `${url.pathname}${url.search}${url.hash}`);
  }, []);

  if (!state) return <LoadingNote label="Loading the Debt Metrics…" />;
  if ("failure" in state) return <UnavailableNote message={state.failure.message || "Debt Metrics are unavailable right now. Nothing was changed."} onRetry={() => setNonce((n) => n + 1)} />;
  const { payload } = state;
  const run = payload.run;
  if (!run) {
    return <section data-dm-empty="true" className="dm-card"><h3 className="rcm-h3">Debt Metrics</h3>
      <p className="rx-empty" role="status">No committed Run yet. Enter and save inputs, then choose Run model. No debt metric is estimated before a Run.</p></section>;
  }
  const view = run.debt_metrics;
  const ev = view.evaluation;
  const stateText = RUN_TEXT[String(run.identity.state)] ?? label(String(run.identity.state));
  const integrity = run.integrity.status;
  return (
    <div className="dm-root" data-debt-metrics="true" data-dm-run={String(run.identity.history_id)} data-dm-state={String(run.identity.state)} data-dm-available={view.available}>
      <div className="dm-head">
        <h2 className="dm-title">Debt Metrics</h2>
        <label className="dm-picker">Committed Run
          <select aria-label="Committed Run" value={String(run.identity.history_id)} onChange={(e) => choose(e.target.value)} data-dm-picker="true">
            {payload.history_rows.map((r) => <option key={r.history_id} value={r.history_id}>{r.is_last ? "Last Run · " : ""}{r.ran_at} · {r.scenario}</option>)}
          </select>
        </label>
      </div>

      <ul className="dm-chips" aria-label="Independent outcomes of this Run" data-dm-chips="true">
        <li className="dm-chip dm-chip-run" data-dm-chip="run"><span className="dm-chip-k">Run</span> {stateText}</li>
        <li className={`dm-chip dm-chip-int dm-int-${integrity.toLowerCase()}`} data-dm-chip="integrity" data-integrity={integrity}><span className="dm-chip-k">Integrity</span> {integrity === "PASS" ? "PASS" : integrity === "FAIL" ? "FAIL — review before relying on results" : integrity === "INCOMPLETE" ? "INCOMPLETE — some checks could not be evaluated" : "Not available"}</li>
        <li className="dm-chip dm-chip-credit" data-dm-chip="credit"><span className="dm-chip-k">Credit</span>
          <span data-dm-credit="coverage"> Coverage: {label(ev.coverage.status)}</span> ·
          <span data-dm-credit="covenant"> Covenant: {label(ev.covenant.status)}</span> ·
          <span data-dm-credit="eod"> EoD threshold: {label(ev.eod.status)}</span></li>
      </ul>
      {String(run.identity.state).includes("STALE") && <p className="rx-banner rx-banner-stale" role="status" data-dm-stale="true">STALE — these figures belong to the saved Run; the inputs changed after it. Terms edited since then apply to the next Run only. Save, then Run explicitly to update.</p>}
      {String(run.identity.state) === "HISTORICAL" && <p className="dm-note" role="status" data-dm-historical="true">Historical Run — evaluated against the terms recorded when it was committed, never against today&rsquo;s inputs.</p>}
      {integrity === "FAIL" && <div className="rx-status rx-status-error" role="alert" data-dm-integrity-fail="true"><strong>INTEGRITY FAIL — review this Run before relying on its financial results.</strong>
        <p>A completed calculation does not establish financial viability.</p>
        {run.integrity.failures.length > 0 && <ul>{run.integrity.failures.map((f, i) => <li key={f.id || i}>{f.title || f.id}{f.reason ? `: ${f.reason}` : ""}</li>)}</ul>}</div>}

      {!view.available ? <section className="dm-card" data-dm-unavailable="true"><h3 className="rcm-h3">Debt Metrics unavailable for this Run</h3><p className="dm-na" role="status">{view.reason}</p></section> : <>
        <TermsPanel view={view} onEditTerms={onEditTerms} />
        <CovenantTable rows={view.covenant_table} onJump={(i) => schedule.current?.jumpTo(i)} />
        <KpiRow view={view} />
        <div className="dm-two">
          <DscrProfileChart view={view} />
          <ReservesPanel view={view} precision={precision} />
        </div>
        <PeriodSchedule ref={schedule} view={view} precision={precision} runId={String(run.identity.history_id)} />
      </>}
      <p className="dm-note" data-dm-disclosure="true">{view.basis_note} {payload.disclosure}</p>
    </div>
  );
}

function TermsPanel({ view, onEditTerms }: { view: import("./types").DebtMetricsView; onEditTerms?: () => void }) {
  const t = view.contract_terms;
  const show = (term: { status: string; raw: string | null }) => (term.status === "CONFIGURED" ? `${term.raw}x` : term.status === "INVALID" ? "Invalid value saved" : "Not configured");
  return (
    <section className="dm-card" data-dm-terms="true" aria-labelledby="dm-terms-h">
      <h3 id="dm-terms-h" className="rcm-h3">Contractual DSCR terms recorded with this Run</h3>
      {!t.recorded ? <p className="dm-na" role="status" data-dm-terms-unrecorded="true">{t.reason}</p> : null}
      <dl className="dm-terms">
        <div><dt>Minimum DSCR (EoD threshold) <span className="dm-tag">Input</span></dt><dd data-dm-term="eod">{t.recorded ? show(t.eod_minimum_dscr) : "Not recorded"}</dd></div>
        <div><dt>Contractual DSCR (covenant) <span className="dm-tag">Input</span></dt><dd data-dm-term="contractual">{t.recorded ? show(t.contractual_dscr) : "Not recorded"}</dd></div>
        <div><dt>Achieved Minimum DSCR <span className="dm-tag dm-tag-result">Run result</span></dt>
          <dd data-dm-term="achieved">{view.kpis.achieved_min_dscr.available ? view.kpis.achieved_min_dscr.display : "Not available"}</dd></div>
      </dl>
      <p className="dm-note">{t.note} The Senior sizing target and the lock-up threshold are separate controls and are not these terms.{" "}
        {onEditTerms && <button type="button" className="dm-link" onClick={onEditTerms} data-dm-edit-terms="true">Edit the two terms in Debt terms</button>}</p>
      <details className="dm-more"><summary>Test basis</summary>
        <ul>{Object.entries(t.test_basis).map(([k, v]) => <li key={k}><strong>{label(k)}:</strong> {v}</li>)}</ul></details>
    </section>
  );
}
