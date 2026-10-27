import { useEffect, useMemo, useState } from "react";
import { copyTsv, downloadCsv } from "../analysis/shared";
import { runIdentityText } from "../runIdentity";
import { fetchCompare } from "./api";
import type { CashflowSeries, ComparePayload, CompareRow } from "./types";

type DeltaMode = "abs" | "pct" | "both";

const stateChip = (state: string) => (state.includes("CURRENT") ? "rcm-chip ok" : state.includes("STALE") ? "rcm-chip warn" : "rcm-chip");
const cell = (v: number | null, unit: string) => (v === null ? "—" : unit === "x" ? `${v.toFixed(2)}x` : v.toLocaleString("en-GB", { maximumFractionDigits: 0 }));

/** Compare two or three explicitly selected COMMITTED Runs.  Everything shown is persisted Run evidence formatted by the server;
 *  the first Run is the reference.  A metric a Run did not persist stays "—" / "not available" — never zero.  No Run is started. */
export function CompareWorkspace({ project, historyIds, workbookHash, onClear }: {
  project: string; historyIds: string[]; workbookHash: string; onClear: () => void;
}) {
  const [payload, setPayload] = useState<ComparePayload | null>(null);
  const [error, setError] = useState<{ code: string; message: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [mode, setMode] = useState<DeltaMode>("both");
  const [seriesKey, setSeriesKey] = useState("");
  const key = historyIds.join("|");

  // `workbookHash` is a dependency only so the CURRENT / STALE labels are re-read after a Save: the Runs themselves are immutable.
  useEffect(() => {
    if (historyIds.length < 2) { setPayload(null); setError(null); return undefined; }
    const controller = new AbortController();
    setBusy(true); setError(null); setPayload(null);
    void fetchCompare(project, historyIds, controller.signal).then((result) => {
      if (controller.signal.aborted) return;
      if (result.ok) { setPayload(result); setSeriesKey((current) => current || result.cashflow.series[0]?.key || ""); }
      else setError({ code: result.code, message: result.message ?? "The comparison could not be read." });
      setBusy(false);
    }).catch(() => { /* effect cancelled */ });
    return () => controller.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [project, key, workbookHash]);

  // Evidence is rendered only for exactly the Runs that were selected, in that order.
  const matching = payload && payload.columns.length === historyIds.length && payload.columns.every((c, i) => c.history_id === historyIds[i]);
  const rows = useMemo(() => (payload?.rows ?? []), [payload]);
  const series: CashflowSeries | undefined = payload?.cashflow.series.find((s) => s.key === seriesKey);

  if (historyIds.length < 2) {
    return <section className="rx-card" data-compare-state="IDLE"><h2>Compare Runs</h2>
      <p className="rx-empty" role="status">Select two or three committed Runs in the history above to compare them. The first selected Run is the reference.</p></section>;
  }

  const exportRows = (p: ComparePayload): string[][] => [
    ["Metric", "Unit", ...p.columns.flatMap((c, i) => i === 0 ? [`${c.scenario} ${c.history_id} (reference)`] : [`${c.scenario} ${c.history_id}`, "Absolute change", "Relative change"])],
    ...p.rows.map((r) => [r.label, r.unit, ...r.values.flatMap((v, i) => i === 0 ? [v] : [v, r.abs_deltas[i], r.pct_deltas[i]])]),
  ];

  return (
    <section className="rx-card" aria-label="Run comparison" data-compare-state={busy ? "LOADING" : error ? "ERROR" : matching ? "READY" : "IDLE"}>
      <h2>Compare Runs <span className="rcm-badge">COMMITTED EVIDENCE · READ-ONLY</span></h2>
      <p className="rx-note">Comparing {historyIds.length} committed Runs. Nothing here saves, runs or changes the Working Copy; a metric a Run did not persist is shown as unavailable.</p>
      <div className="rcm-table-actions"><button type="button" className="rx-button rx-button-secondary" data-compare-clear="true" onClick={onClear}>Clear selection</button></div>
      {busy && <p className="rx-note" role="status" data-compare-loading="true">Reading the selected committed evidence…</p>}
      {error && <p className="rx-status rx-status-error" role="alert" data-compare-error={error.code}>{error.message}</p>}
      {matching && payload && (
        <>
          <p className="rx-note" data-compare-freshness={payload.working_copy.freshness}>Working Copy: {payload.working_copy.freshness}. {payload.semantics.basis}</p>
          <div className="rcm-modes" role="group" aria-label="Change display">
            {([["abs", "Absolute"], ["pct", "Percent"], ["both", "Both"]] as const).map(([id, label]) => (
              <button key={id} type="button" className={`rcm-mode${mode === id ? " active" : ""}`} aria-pressed={mode === id} data-delta-mode={id} onClick={() => setMode(id)}>{label}</button>
            ))}
          </div>
          <div className="rcm-table-actions">
            <button type="button" className="rx-button rx-button-secondary" data-copy-table="true" onClick={() => void copyTsv(exportRows(payload))}>Copy table</button>
            <button type="button" className="rx-button rx-button-secondary" data-download-csv="true" onClick={() => downloadCsv("run-comparison.csv", exportRows(payload))}>Download CSV</button>
          </div>
          <p className="rcm-scroll-hint" aria-hidden="true">Swipe or scroll sideways for more columns →</p>
          <div className="rcm-scroll" tabIndex={0} role="region" aria-label="KPI comparison (scrolls horizontally)">
            <table className="rcm-table" data-compare-table="true">
              <caption className="rx-note">Persisted KPIs and supporting evidence · {payload.project.name}</caption>
              <thead>
                <tr><th scope="col" className="rcm-sticky">Metric</th><th scope="col" className="rcm-left">Unit</th>
                  {payload.columns.map((c, i) => (
                    <th scope="col" key={c.history_id} data-compare-column={c.history_id}>
                      {i === 0 ? "Reference · " : ""}{c.scenario}
                      <span className="rcm-unit">{runIdentityText(c.snapshot_id)}</span>
                      <span className={stateChip(c.state)}>{c.state}</span>
                    </th>
                  ))}
                  <th scope="col" className="rcm-left">Source</th></tr>
              </thead>
              <tbody>
                {rows.map((r: CompareRow) => (
                  <tr key={r.key} data-compare-row={r.key} data-row-kind={r.kind}>
                    <th scope="row" className="rcm-sticky">{r.label}</th>
                    <td className="rcm-input-cell">{r.unit || "—"}</td>
                    {r.values.map((v, i) => (
                      <td key={payload.columns[i].history_id} data-availability={r.availability[i]} data-history-id={payload.columns[i].history_id}>
                        {v}
                        {r.availability[i] !== "available" && <span className="rcm-delta">not available</span>}
                        {i > 0 && (mode === "abs" || mode === "both") && <span className="rcm-delta" data-abs-delta="true">Δ {r.abs_deltas[i]}</span>}
                        {i > 0 && (mode === "pct" || mode === "both") && <span className="rcm-delta" data-pct-delta="true">Δ% {r.pct_deltas[i]}</span>}
                      </td>
                    ))}
                    <td className="rcm-input-cell" style={{ whiteSpace: "normal" }}>{r.source}{r.reason ? ` — ${r.reason}` : ""}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <h3 className="rcm-h3">Cash-flow comparison</h3>
          <p className="rx-note" data-cashflow-note="true">{payload.cashflow.note}</p>
          <label className="rcm-field">Series
            <select value={seriesKey} data-cashflow-series="true" onChange={(e) => setSeriesKey(e.target.value)}>
              {payload.cashflow.series.map((s) => <option key={s.key} value={s.key}>{s.label} ({s.unit})</option>)}
            </select>
          </label>
          {series && (
            <div data-cashflow-table-wrap={series.key}>
              {series.calendar_mismatch && <p className="rx-banner rx-banner-stale" role="status">The compared Runs carry different dates for the same model period; read the dates per Run.</p>}
              <div className="rcm-scroll" tabIndex={0} role="region" aria-label={`${series.label} by period (scrolls)`}>
                <table className="rcm-table" data-cashflow-table="true">
                  <thead><tr><th scope="col" className="rcm-sticky">Period</th><th scope="col" className="rcm-left">Date</th>
                    {payload.columns.map((c) => <th scope="col" key={c.history_id}>{c.scenario}<span className="rcm-unit">{series.unit}</span></th>)}</tr></thead>
                  <tbody>
                    <tr className="is-base" data-cashflow-total="true"><th scope="row" className="rcm-sticky">Total (sum of persisted periods)</th><td />
                      {series.runs.map((r) => <td key={r.history_id}>{r.available ? (r.total === null ? "n/a (ratio)" : cell(r.total, series.unit)) : "—"}</td>)}</tr>
                    {series.periods.map((p, i) => (
                      <tr key={p}><th scope="row" className="rcm-sticky">{p}</th><td className="rcm-input-cell">{series.dates[i] || "—"}</td>
                        {series.runs.map((r) => <td key={r.history_id}>{cell(r.values[i] ?? null, series.unit)}</td>)}</tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          <h3 className="rcm-h3">Assumption differences</h3>
          <AssumptionBlock payload={payload} />
        </>
      )}
    </section>
  );
}

function AssumptionBlock({ payload }: { payload: ComparePayload }) {
  const a = payload.assumptions;
  const names = payload.columns.map((c) => c.scenario);
  return (
    <div data-assumptions="true">
      <p className="rcm-status-line">
        <span className={`rcm-chip ${a.composite_hash_equal ? "ok" : "warn"}`} data-composite-equal={String(a.composite_hash_equal)}>
          {a.composite_hash_equal ? "Identical composite input hash" : "Composite input hashes differ"}
        </span>
      </p>
      {a.scenario_overrides.length > 0 && (
        <DiffTable title="Scenario overrides" head={["Override", ...names]} rows={a.scenario_overrides.map((o) => [o.key, ...o.values.map((v) => (v === null || v === undefined ? "—" : String(v)))])} />
      )}
      {a.capex_lines.length > 0 && (
        <DiffTable title="CAPEX lines that differ (kEUR)" head={["Line", "Group", ...names]} rows={a.capex_lines.map((l) => [l.line_id, l.group, ...l.values.map((v) => cell(v, "kEUR"))])} />
      )}
      {a.opex_lines.length > 0 && (
        <DiffTable title="OPEX lines that differ (kEUR)" head={["Line", "Group", ...names]} rows={a.opex_lines.map((l) => [l.line_id, l.group, ...l.values.map((v) => cell(v, "kEUR"))])} />
      )}
      {!a.scenario_overrides.length && !a.capex_lines.length && !a.opex_lines.length && (
        <p className="rx-note" data-assumptions-none="true">No scenario-override, CAPEX-line or OPEX-line difference is recorded between these Runs.</p>
      )}
      <p className="rx-note" data-assumptions-limitation="true">{a.limitation}</p>
      <details><summary>Run provenance</summary>
        <dl className="rcm-facts">
          {payload.columns.map((c) => (
            <div key={c.history_id} data-provenance={c.history_id}>
              <dt>{c.scenario}</dt>
              <dd>Run {c.history_id}<br />Snapshot {c.snapshot_id}<br />Composite {c.composite_hash || "unavailable"}<br />Engine {c.engine_version ?? "unavailable"} · Workbook {c.workbook_version ?? "unavailable"}</dd>
            </div>
          ))}
        </dl>
      </details>
    </div>
  );
}

function DiffTable({ title, head, rows }: { title: string; head: string[]; rows: string[][] }) {
  return (
    <div>
      <h4 className="rcm-h3">{title}</h4>
      <div className="rcm-scroll" tabIndex={0} role="region" aria-label={`${title} (scrolls)`}>
        <table className="rcm-table"><thead><tr>{head.map((h, i) => <th scope="col" key={h + i} className={i < 2 ? "rcm-left" : ""}>{h}</th>)}</tr></thead>
          <tbody>{rows.map((r) => <tr key={r[0]}>{r.map((c, i) => i === 0 ? <th scope="row" key={i} className="rcm-sticky">{c}</th> : <td key={i}>{c}</td>)}</tr>)}</tbody></table>
      </div>
    </div>
  );
}
