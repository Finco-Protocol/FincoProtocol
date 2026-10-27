import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import "../../styles/rcm-analysis.css";
import { useDirtyTotal } from "../workflow/workflowShared";
import { fetchSensitivityCatalog, runMatrix, runStrip } from "./analysisApi";
import { TierNote, downloadCsv, copyTsv } from "./shared";
import type { AdapterFailure, DriverInfo, MatrixResult, SensitivityCatalog, StripResult } from "./types";

type Mode = "strip" | "matrix";
type Outcome = { kind: "strip"; result: StripResult } | { kind: "matrix"; result: MatrixResult };

const FAILURE_TEXT: Record<string, string> = {
  MODEL_BUSY: "The model engine is busy. Wait a moment and run again.",
  MATRIX_CONTEXT_CHANGED: "The Working Copy changed while the analysis was running, so the result was discarded. Run it again.",
};

function levelsText(driver: DriverInfo | undefined, size: 3 | 5): string {
  if (!driver) return "";
  return (size === 5 ? driver.default_levels : driver.default_levels_3).map((l) => l.value).join(", ");
}

/** Analysis > Sensitivity: one driver at five levels, or a two-driver matrix.  Every figure is the canonical engine result
 *  for the saved Working Copy; the browser only lays it out.  Nothing here is saved and nothing is a Run. */
export function SensitivityPanel({ project, workbookHash }: { project: string; workbookHash: string }) {
  const [catalog, setCatalog] = useState<SensitivityCatalog | null>(null);
  const [failure, setFailure] = useState<AdapterFailure | null>(null);
  const [mode, setMode] = useState<Mode>("strip");
  const [driver, setDriver] = useState("");
  const [levels, setLevels] = useState("");
  const [driverA, setDriverA] = useState("");
  const [driverB, setDriverB] = useState("");
  const [metric, setMetric] = useState("project_irr");
  const [grid, setGrid] = useState<"3" | "5">("3");
  const [levelsA, setLevelsA] = useState("");
  const [levelsB, setLevelsB] = useState("");
  const [threshold, setThreshold] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<{ code: string; message: string } | null>(null);
  const [outcome, setOutcome] = useState<Outcome | null>(null);
  const abort = useRef<AbortController | null>(null);
  const sequence = useRef(0);
  const { total: unsaved } = useDirtyTotal();

  useEffect(() => {
    let live = true;
    void fetchSensitivityCatalog(project).then((result) => {
      if (!live) return;
      if (result.ok) {
        setCatalog(result);
        const first = result.drivers.find((d) => d.key === "tariff") ?? result.drivers[0];
        setDriver(first?.key ?? "");
        setLevels(levelsText(first, 5));
        const a = result.drivers.find((d) => d.key === "tariff") ?? result.drivers[0];
        const b = result.drivers.find((d) => d.key === "capex" && d.key !== a?.key) ?? result.drivers.find((d) => d.key !== a?.key);
        setDriverA(a?.key ?? ""); setDriverB(b?.key ?? "");
      } else setFailure(result);
    });
    return () => { live = false; abort.current?.abort(); };
  }, [project]);

  const byKey = useMemo(() => new Map((catalog?.drivers ?? []).map((d) => [d.key, d])), [catalog]);

  const run = useCallback(async () => {
    if (!catalog || busy) return;
    abort.current?.abort();
    const controller = new AbortController();
    abort.current = controller;
    const mine = ++sequence.current;
    setBusy(true);
    setError(null);
    const result = mode === "strip"
      ? await runStrip({ project, driver, levels: levels.trim(), scenarioId: "" }, controller.signal)
      : await runMatrix({ project, driverA, driverB, metric, grid, levelsA: levelsA.trim(), levelsB: levelsB.trim(), threshold: threshold.trim(), scenarioId: "" }, controller.signal);
    if (mine !== sequence.current) return;                       // a newer request owns the screen
    setBusy(false);
    if (result.ok) setOutcome(mode === "strip" ? { kind: "strip", result: result as StripResult } : { kind: "matrix", result: result as MatrixResult });
    else setError({ code: result.code, message: FAILURE_TEXT[result.code] ?? result.message ?? "The analysis could not be run. Nothing was changed." });
  }, [catalog, busy, mode, project, driver, levels, driverA, driverB, metric, grid, levelsA, levelsB, threshold]);

  const cancel = () => { abort.current?.abort(); };

  if (failure) {
    return (
      <section className="rx-card" data-sensitivity-state={failure.code} aria-labelledby="rcm-sens-title">
        <h2 id="rcm-sens-title">Sensitivity analysis</h2>
        <p className="rx-empty" role="alert" data-sensitivity-unavailable="true">
          {failure.code === "MATRIX_PROTECTED_REFERENCE"
            ? "Reference models are read-only. Create a working copy to run a sensitivity analysis."
            : failure.message || "Sensitivity analysis is not available for this project."}
        </p>
        <p className="rx-note">NOT RELEASED for this project. The classic workbook&rsquo;s Sensitivity sheet remains available.</p>
      </section>
    );
  }
  if (!catalog) return <section className="rx-card"><p className="rx-boot-loading" role="status">Loading the sensitivity drivers…</p></section>;

  const active = outcome && (outcome.kind === "strip" ? outcome.result.run : outcome.result.run);
  const outdated = Boolean(active && workbookHash && !workbookHash.startsWith(active.basis_hash));

  return (
    <section className="rx-card rcm-analysis" data-sensitivity-panel="true" aria-labelledby="rcm-sens-title">
      <h2 id="rcm-sens-title">Sensitivity analysis <span className="rcm-badge" data-ephemeral-badge="true">NOT A RUN · NOT SAVED</span></h2>
      <TierNote vertical={catalog.vertical} />
      <p className="rx-note" data-sensitivity-basis="true">
        Each point is a full canonical engine run on the <strong>saved Working Copy</strong> with only the chosen driver(s) shocked. Nothing is interpolated,
        saved or recorded in Run History. Maximum {catalog.limits.max_cells} points per matrix.
      </p>
      {unsaved > 0 && (
        <p className="rx-status rx-status-conflict" role="status" data-unsaved-warning="true">
          {unsaved} unsaved edit{unsaved === 1 ? "" : "s"} in this browser are NOT included — Save them first to analyse them.
        </p>
      )}

      <div className="rcm-modes" role="radiogroup" aria-label="Analysis type">
        {(["strip", "matrix"] as Mode[]).map((m) => (
          <button key={m} type="button" role="radio" aria-checked={mode === m} className={`rcm-mode${mode === m ? " active" : ""}`}
                  data-sens-mode={m} onClick={() => setMode(m)}>
            {m === "strip" ? "One driver · 5 points" : "Two drivers · matrix"}
          </button>
        ))}
      </div>

      <form className="rcm-controls" onSubmit={(e) => { e.preventDefault(); void run(); }} data-sensitivity-form={mode}>
        {mode === "strip" ? (
          <>
            <label className="rcm-field">Driver
              <select value={driver} data-sens-driver="true" onChange={(e) => { setDriver(e.target.value); setLevels(levelsText(byKey.get(e.target.value), 5)); }}>
                {catalog.drivers.map((d) => <option key={d.key} value={d.key}>{d.label} ({d.unit})</option>)}
              </select>
            </label>
            <label className="rcm-field">Levels ({byKey.get(driver)?.unit}, 3–5 comma-separated)
              <input value={levels} data-sens-levels="true" inputMode="decimal" onChange={(e) => setLevels(e.target.value)} />
              <span className="rx-note">0 = unchanged base · |level| ≤ {byKey.get(driver)?.max_abs_level} {byKey.get(driver)?.unit}</span>
            </label>
          </>
        ) : (
          <>
            <label className="rcm-field">Driver A (columns)
              <select value={driverA} data-sens-driver-a="true" onChange={(e) => { setDriverA(e.target.value); setLevelsA(""); }}>
                {catalog.drivers.map((d) => <option key={d.key} value={d.key}>{d.label} ({d.unit})</option>)}
              </select>
            </label>
            <label className="rcm-field">Driver B (rows)
              <select value={driverB} data-sens-driver-b="true" onChange={(e) => { setDriverB(e.target.value); setLevelsB(""); }}>
                {catalog.drivers.map((d) => <option key={d.key} value={d.key}>{d.label} ({d.unit})</option>)}
              </select>
            </label>
            <label className="rcm-field">Metric
              <select value={metric} data-sens-metric="true" onChange={(e) => setMetric(e.target.value)}>
                {catalog.metrics.map((m) => <option key={m.key} value={m.key}>{m.label}{m.note ? ` — ${m.note}` : ""}</option>)}
              </select>
            </label>
            <label className="rcm-field">Grid
              <select value={grid} data-sens-grid="true" onChange={(e) => setGrid(e.target.value as "3" | "5")}>
                {catalog.limits.grid_sizes.map((g) => <option key={g} value={g}>{g} × {g} ({g * g} points)</option>)}
              </select>
            </label>
            <label className="rcm-field">Levels A (optional)
              <input value={levelsA} placeholder={levelsText(byKey.get(driverA), Number(grid) as 3 | 5)} onChange={(e) => setLevelsA(e.target.value)} />
            </label>
            <label className="rcm-field">Levels B (optional)
              <input value={levelsB} placeholder={levelsText(byKey.get(driverB), Number(grid) as 3 | 5)} onChange={(e) => setLevelsB(e.target.value)} />
            </label>
            <label className="rcm-field">Threshold (optional, display units)
              <input value={threshold} inputMode="decimal" data-sens-threshold="true" onChange={(e) => setThreshold(e.target.value)} />
            </label>
          </>
        )}
        <div className="rcm-controls-actions">
          <button type="submit" className="rx-button" disabled={busy} data-sens-run="true" aria-busy={busy}>{busy ? "Running…" : mode === "strip" ? "Run 5-point sensitivity" : `Run ${grid}×${grid} matrix`}</button>
          {busy && <button type="button" className="rx-button rx-button-secondary" data-sens-cancel="true" onClick={cancel}>Cancel</button>}
        </div>
      </form>
      {busy && <p className="rx-note" role="status" data-sens-progress="true">Running canonical engine evaluations — this can take a little while. Nothing is saved.</p>}
      {error && (
        <p className="rx-status rx-status-error" role="alert" data-sens-error={error.code}>
          {error.message}
        </p>
      )}

      {outcome && (
        <div className="rcm-result" data-sens-result={outcome.kind} data-result-outdated={outdated}>
          {outdated && (
            <p className="rx-banner rx-banner-stale" role="status" data-outdated-banner="true">
              OUTDATED — the Working Copy changed after this analysis was computed. Run it again to analyse the current inputs.
            </p>
          )}
          {outcome.kind === "strip" ? <StripTable result={outcome.result} /> : <MatrixTable result={outcome.result} />}
        </div>
      )}
    </section>
  );
}

function RunFooter({ run, provenance }: { run: StripResult["run"]; provenance: string }) {
  return (
    <p className="rx-note" data-run-footer="true">
      {run.evaluations} canonical evaluation{run.evaluations === 1 ? "" : "s"} · {run.seconds}s · basis: {run.scenario} · Working Copy {run.basis_hash}… ·
      {" "}computed now, not a committed Run. {provenance}
    </p>
  );
}

function StripTable({ result }: { result: StripResult }) {
  const header = ["Case", `${result.driver.label} (${result.driver.unit})`, "Driver input", ...result.columns.map((c) => `${c.label}${c.unit ? ` (${c.unit})` : ""}`)];
  const rows = result.rows.map((r) => [r.label, r.status, r.input.text || (r.is_base ? "base" : "—"), ...result.columns.map((c) => r.values[c.key]?.display ?? "—")]);
  return (
    <div data-strip-result="true">
      <h3 className="rcm-h3">{result.driver.label} — {result.levels.length} evaluated levels</h3>
      <div className="rcm-table-actions">
        <button type="button" className="rx-button rx-button-secondary" data-copy-table="true" onClick={() => void copyTsv([header, ...rows])}>Copy table</button>
        <button type="button" className="rx-button rx-button-secondary" data-download-csv="true" onClick={() => downloadCsv("sensitivity-strip.csv", [header, ...rows])}>Download CSV</button>
      </div>
      <p className="rcm-scroll-hint" aria-hidden="true">Swipe or scroll sideways for more columns →</p>
      <div className="rcm-scroll" tabIndex={0} role="region" aria-label="Sensitivity results table (scrolls horizontally)">
        <table className="rcm-table" data-strip-table="true">
          <thead>
            <tr><th scope="col" className="rcm-sticky">Case</th><th scope="col" className="rcm-left">Driver input</th>
              {result.columns.map((c) => <th scope="col" key={c.key}>{c.label}<span className="rcm-unit">{c.unit}</span></th>)}</tr>
          </thead>
          <tbody>
            {result.rows.map((r) => (
              <tr key={r.index} className={r.is_base ? "is-base" : ""} data-strip-row={r.label} data-status={r.status}>
                <th scope="row" className="rcm-sticky">{r.label}{r.is_base && <span className="rcm-tag">BASE</span>}{r.status !== "OK" && <span className="rcm-tag rcm-tag-bad">{r.status}</span>}</th>
                <td className="rcm-input-cell">{r.input.text || (r.is_base ? "unchanged" : "—")}</td>
                {r.status !== "OK"
                  ? <td colSpan={result.columns.length} className="rcm-na">{r.reason || "No result"}</td>
                  : result.columns.map((c) => {
                    const v = r.values[c.key];
                    return <td key={c.key} className="rcm-num" data-kpi={c.key}>{v?.display ?? "—"}{!r.is_base && v?.delta !== null && v?.delta !== undefined && <span className="rcm-delta">Δ {v.delta_display}</span>}</td>;
                  })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <RunFooter run={result.run} provenance={result.provenance} />
    </div>
  );
}

function MatrixTable({ result }: { result: MatrixResult }) {
  const m = result.matrix;
  const header = [`${m.driver_b.label} ↓ / ${m.driver_a.label} →`, ...m.driver_a.levels.map((l) => l.label)];
  const rows = m.rows.map((row, j) => [m.driver_b.levels[j].label, ...row.map((c) => (c.status === "OK" ? c.display : c.status))]);
  return (
    <div data-matrix-result="true">
      <h3 className="rcm-h3">{m.metric.label}: {m.driver_a.label} × {m.driver_b.label}</h3>
      <p className="rx-note" data-matrix-base="true">Base ({m.metric.label}): <strong>{m.base.display}</strong>{m.base.status !== "OK" ? " — unavailable" : ""}</p>
      <div className="rcm-table-actions">
        <button type="button" className="rx-button rx-button-secondary" data-copy-table="true" onClick={() => void copyTsv([header, ...rows])}>Copy table</button>
        <button type="button" className="rx-button rx-button-secondary" data-download-csv="true" onClick={() => downloadCsv("sensitivity-matrix.csv", [header, ...rows])}>Download CSV</button>
      </div>
      <p className="rcm-scroll-hint" aria-hidden="true">Swipe or scroll sideways for more columns →</p>
      <div className="rcm-scroll" tabIndex={0} role="region" aria-label="Sensitivity matrix (scrolls horizontally)">
        <table className="rcm-table rcm-matrix" data-matrix-table="true">
          <thead>
            <tr><th scope="col" className="rcm-sticky">{m.driver_b.label} ↓ · {m.driver_a.label} →</th>
              {m.driver_a.levels.map((l) => <th scope="col" key={l.value}>{l.label}</th>)}</tr>
          </thead>
          <tbody>
            {m.rows.map((row, j) => (
              <tr key={j}>
                <th scope="row" className="rcm-sticky">{m.driver_b.levels[j].label}</th>
                {row.map((c) => (
                  <td key={c.i} className={`rcm-num rcm-cell st-${c.status.toLowerCase()} th-${c.threshold_status.toLowerCase()}${c.is_base ? " is-base" : ""}`}
                      data-matrix-cell={`${c.i},${c.j}`} data-status={c.status} data-threshold={c.threshold_status}>
                    {c.status === "OK"
                      ? <>{c.display}{!c.is_base && <span className="rcm-delta">Δ {c.delta_display}</span>}
                        {m.threshold && (c.threshold_status === "PASS" || c.threshold_status === "FAIL") && <span className="rcm-tag">{c.threshold_status}</span>}</>
                      : <><span className="rcm-tag rcm-tag-bad">{c.status}</span><span className="rcm-delta">{c.reason}</span></>}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {m.threshold && <p className="rx-note" data-matrix-threshold="true">Threshold {m.threshold.comparator} {m.threshold.display}: {m.threshold.origin}</p>}
      {m.brackets.map((b, i) => <p key={i} className="rx-note" data-matrix-bracket="true">{b.note} ({b.from.join(" / ")} ↔ {b.to.join(" / ")})</p>)}
      <RunFooter run={result.run} provenance={result.provenance} />
    </div>
  );
}
