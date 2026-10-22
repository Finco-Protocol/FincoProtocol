import React, { useEffect, useRef, useState } from "react";
import "./ResultsAnalysis.css";
import "./_group.css";
import StatementWorkbook from "./_workbook/StatementWorkbook";
import WorkbookNavigation from "./_workbook/WorkbookNavigation";
import "./_workbook/workbook.css";
import { DemoBanner, DemoContextStrip, fincoBasePath, ModelNav, navigateFinco, Panel, readProjectContext, Shell, Status } from "./_shared/FincoShell";
import { preferredScrollBehavior } from "./_shared/motion";
import type { StatementRunStatus, StatementWorkbookSnapshot } from "./_workbook/statementContract";
import { resultsValueText, type ResultsChartModel, type ResultsDisplayValue, type ResultsKpi, type ResultsPresentationSnapshot, type ResultsRunStatus } from "./_results/resultsContract";

function availableSegments(points: ResultsChartModel["series"][number]["points"]) {
  const segments: typeof points[] = [];
  let current: typeof points = [];
  for (const point of points) {
    if (point.value.kind === "value" && point.geometry) current.push(point);
    else if (current.length) { segments.push(current); current = []; }
  }
  if (current.length) segments.push(current);
  return segments;
}

function ResultsChart({ chart }: { chart: ResultsChartModel | null }) {
  if (!chart) return <div className="fm-info-note" role="status">Chart data unavailable. No synthetic series was substituted.</div>;
  const usable = chart.series.some((series) => series.points.some((point) => point.value.kind === "value" && point.geometry));
  if (!usable) return <div className="fm-info-note" role="status">Chart values unavailable for the supplied result snapshot.</div>;
  return <>
    <svg className="fm-chart" viewBox="0 0 600 155" role="img" aria-label={chart.ariaLabel}>
      {chart.gridLines.map((y) => <line key={y} x1={chart.gridStartX} y1={y} x2={chart.gridEndX} y2={y} className="fm-chart-grid" />)}
      {chart.series.map((series) => {
        const segments = series.kind === "line" ? availableSegments(series.points) : [];
        return <g key={series.id}>
          {series.kind === "line" && segments.map((segment, index) => {
            const path = segment.map((point, pointIndex) => `${pointIndex === 0 ? "M" : "L"}${point.geometry!.x} ${point.geometry!.y}`).join(" ");
            const fullSeries = segments.length === 1 && segment.length === series.points.length;
            const areaPath = fullSeries && series.area
              ? `${path} L ${segment[segment.length - 1].geometry!.x} ${chart.baselineY} L ${segment[0].geometry!.x} ${chart.baselineY} Z`
              : null;
            return <React.Fragment key={`${series.id}-${index}`}>
              {areaPath && <path d={areaPath} className="fm-chart-area" />}
              <path d={path} className="fm-chart-line" />
            </React.Fragment>;
          })}
          {series.kind === "line" && series.points.filter((point) => point.marker && point.value.kind === "value" && point.geometry).map((point) =>
            <circle key={point.period} cx={point.geometry!.x} cy={point.geometry!.y} r="2.8" fill="#315f83"><title>{point.value.kind === "value" ? point.value.tooltip || `${point.period}: ${point.value.text}` : ""}</title></circle>)}
          {series.kind === "bar" && series.points.filter((point) => point.value.kind === "value" && point.geometry).map((point) => {
            const barClass = series.tone === "secondary" ? "fm-chart-bar-alt" : "fm-chart-bar";
            return <rect key={point.period} x={point.geometry!.x} y={point.geometry!.y} width={point.geometry!.width ?? 18} height={point.geometry!.height ?? 0} className={barClass}>
              <title>{point.value.kind === "value" ? point.value.tooltip || `${point.period}: ${point.value.text}` : ""}</title>
            </rect>;
          })}
        </g>;
      })}
      {chart.periodLabels.map(({ label, x }) => <text key={label} x={x} y="145" textAnchor="middle" className="fm-chart-label">{label}</text>)}
      <text x={chart.axisLabelX} y="28" className="fm-chart-label">{chart.axisTopLabel}</text>
      <text x={chart.axisLabelX} y="126" className="fm-chart-label">{chart.axisBottomLabel}</text>
    </svg>
    <div style={{ display: "flex", gap: 13, padding: "0 13px 11px", color: "var(--muted)", fontSize: 9 }}>
      {chart.series.map((series) => <span key={series.id}><i style={{ display: "inline-block", width: series.kind === "line" ? 9 : 8, height: series.kind === "line" ? 3 : 8, background: series.tone === "secondary" ? "#b8c6d0" : "#507797", marginRight: 5, verticalAlign: "middle" }} />{series.label}</span>)}
      {chart.caption && <span>{chart.caption}</span>}
    </div>
  </>;
}

function ResultsOriginNotice({ status }: { status: ResultsRunStatus }) {
  if (status.dataOrigin === "synthetic-demo") {
    return <DemoBanner copy="FIXED SYNTHETIC DEMO VALUES · Shared illustrative outputs, not project-specific results. Input edits do not recalculate or sync." />;
  }
  const copy = status.dataOrigin === "caller-provided"
    ? "Caller-provided display data · origin is not verified by this design prototype. No calculations are performed here."
    : "Results unavailable · no synthetic fallback is shown.";
  return <div className="fm-banner" role="status"><span className="fm-demo-label">{status.dataOrigin === "caller-provided" ? "ORIGIN UNVERIFIED" : "NO RESULTS DATA"}</span><span className="fm-banner-copy">{copy}</span></div>;
}

function runStateLabel(status: ResultsRunStatus) {
  switch (status.runState) {
    case "fixed-demo": return "FIXED DEMO OUTPUT · NOT A LIVE RUN";
    case "not-run": return "NOT RUN";
    case "current": return "CURRENT · persisted Last Run";
    case "stale": return "STALE · prior persisted Run";
    case "unavailable": return "UNAVAILABLE";
  }
}

function freshnessLabel(value: ResultsRunStatus["freshness"]) {
  return value === "unknown" ? "UNKNOWN" : value.replace("-", " ").toUpperCase();
}

function ResultValue({ value }: { value: ResultsDisplayValue }) {
  const text = resultsValueText(value);
  return <span className={value.kind === "unavailable" ? "fm-result-unavailable" : undefined} aria-label={value.kind === "unavailable" ? `${text}${value.reason ? `: ${value.reason}` : ""}` : undefined}>{text}</span>;
}

export type ResultsAnalysisViewProps = {
  /** Caller-owned results view-model; null is unavailable and never falls back to demo data. */
  resultsSnapshot: ResultsPresentationSnapshot | null;
  resultsStatus: ResultsRunStatus;
  /** Caller-owned statement snapshot; null is an explicit unavailable state. */
  statementSnapshot: StatementWorkbookSnapshot | null;
  statementStatus: StatementRunStatus;
};

export function ResultsAnalysisView({ resultsSnapshot, resultsStatus, statementSnapshot, statementStatus }: ResultsAnalysisViewProps) {
  const statement = useRef<HTMLDivElement>(null);
  const project = readProjectContext();
  const [statementSheet, setStatementSheet] = useState(new URLSearchParams(window.location.search).get("statement") || "pl");
  const [section, setSection] = useState(window.location.hash.slice(1) || "results");
  const [panel, setPanel] = useState<"none" | "history" | "scenarios">(() => window.location.hash === "#scenarios" ? "scenarios" : window.location.hash === "#history" ? "history" : "none");
  const [kpiTrace, setKpiTrace] = useState<ResultsKpi | null>(null);
  const scenarioKey = new URLSearchParams(window.location.search).get("scenario");
  const [selectedScenarioId, setSelectedScenarioId] = useState(scenarioKey || "base");
  const selectedScenario = resultsSnapshot?.scenarios.find((scenario) => scenario.id === selectedScenarioId)?.name || "No scenario selected";
  const workingScenarioId = resultsStatus.productContext?.workingScenarioId || selectedScenarioId;
  const workingScenarioName = resultsSnapshot?.scenarios.find((scenario) => scenario.id === workingScenarioId)?.name || workingScenarioId;
  const selectedRunRecord = resultsSnapshot?.history.find((row) => row.runRef === resultsValueText(resultsStatus.runId));
  useEffect(() => {
    const sync = () => {
      const id = window.location.hash.slice(1) || "results";
      setSection(id);
      setPanel(id === "scenarios" ? "scenarios" : id === "history" ? "history" : "none");
    };
    window.addEventListener("hashchange", sync);
    const syncFromHistory = () => {
      sync();
      const params = new URLSearchParams(window.location.search);
      setSelectedScenarioId(params.get("scenario") || "base");
      setStatementSheet(params.get("statement") || "pl");
    };
    window.addEventListener("popstate", syncFromHistory);
    return () => {
      window.removeEventListener("hashchange", sync);
      window.removeEventListener("popstate", syncFromHistory);
    };
  }, []);
  useEffect(() => {
    if (!window.location.hash) return;
    const frame = requestAnimationFrame(() => {
      const target = document.getElementById(section);
      target?.focus({ preventScroll: true });
      target?.scrollIntoView({ block: "start" });
    });
    return () => cancelAnimationFrame(frame);
  }, [section, panel]);
  function togglePanel(next: "history" | "scenarios") {
    window.location.hash = panel === next ? "results" : next;
  }
  function kpiTraceHref(item: ResultsKpi) {
    if (!item.trace) return `${fincoBasePath()}ModelWorkspace#inputs`;
    const params = new URLSearchParams(window.location.search);
    params.delete("statement");
    params.delete("statementView");
    params.delete("traceRow");
    params.set("sheet", item.trace.workspaceSheet);
    params.set("returnStatement", item.trace.statement);
    params.set("returnView", "annual");
    params.set("returnRow", item.trace.row);
    params.set("returnPeriod", "0");
    params.set("returnScrollLeft", "0");
    params.set("returnScrollY", String(Math.round(window.scrollY)));
    return `${fincoBasePath()}ModelWorkspace?${params.toString()}#workbook`;
  }
  const activeNav = section === "scenarios" ? "Scenarios" : section === "analysis" ? "Analysis" : "Results";
  function chooseScenario(id: string) {
    setSelectedScenarioId(id);
    const params = new URLSearchParams(window.location.search);
    params.set("scenario", id);
    window.history.pushState(null, "", `${window.location.pathname}?${params}${window.location.hash}`);
  }
  const kpiPlaceholders = [
    { id: "project-irr", label: "Project IRR" },
    { id: "equity-irr", label: "Equity IRR" },
    { id: "npv", label: "NPV" },
    { id: "minimum-dscr", label: "Minimum DSCR" },
  ];
  const resultKpis: ResultsKpi[] = resultsSnapshot?.kpis.length ? resultsSnapshot.kpis : kpiPlaceholders.map((item) => ({
    ...item,
    value: { kind: "unavailable" as const, text: "Unavailable", reason: "No result value was supplied." },
    note: "No result value supplied",
  }));
  return <Shell crumb={`${project.name} · ${project.technology} · Results`} mainContentId="results" dataOrigin={resultsStatus.dataOrigin}>
    <main className="fm-shell" id="results" tabIndex={-1}>
      <ResultsOriginNotice status={resultsStatus} />
      <DemoContextStrip workingState={runStateLabel(resultsStatus)} />
      <div className="fm-shell-header">
        <div><div className="fm-eyebrow">{project.id} · {resultsSnapshot?.headingLabel || "Results data unavailable"}</div><h1 className="fm-title">Results & analysis</h1><div className="fm-subtitle">{project.name} <span style={{ margin: "0 7px" }}>·</span> {project.technology} <span style={{ margin: "0 7px" }}>·</span> {resultsSnapshot?.versionLabel || "No result view-model supplied"}</div></div>
        <div className="fm-toolbar">
          <button className="fm-btn" type="button" aria-expanded={panel === "history"} aria-controls="history" onClick={() => togglePanel("history")}>Run history</button>
          <button className="fm-btn" type="button" aria-expanded={panel === "scenarios"} aria-controls="scenarios" onClick={() => togglePanel("scenarios")}>Scenario comparison</button>
          <a className="fm-btn fm-btn-primary" href={`${fincoBasePath()}ModelWorkspace${window.location.search}#inputs`} onClick={event => {
            if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
            event.preventDefault();
            navigateFinco(`${fincoBasePath()}ModelWorkspace${window.location.search}#inputs`);
          }} style={{ display: "inline-flex", alignItems: "center", textDecoration: "none" }}>← Back to inputs</a>
        </div>
      </div>
      <ModelNav active={activeNav} />
      <div className="fm-info-note" style={{ marginBottom: 13 }}>
        <strong style={{ color: "var(--ink)" }}>{resultsStatus.dataOrigin === "synthetic-demo" ? "Results are fixed demo values." : resultsStatus.dataOrigin === "unavailable" ? "No result data is available." : "Results are caller-provided display data."}</strong>{" "}
        {resultsStatus.dataOrigin === "synthetic-demo"
          ? "“Run demo” only opens this predetermined illustration. No calculations are run and no results reflect the input edits made in the workspace. Project identity is shown for navigation context only."
          : resultsStatus.dataOrigin === "caller-provided"
            ? "The source and financial authority of these values are not verified by this design prototype. No calculations are run here."
            : "This view does not substitute synthetic values when result data is absent."}
      </div>
      <div className="fm-kpi-grid" style={{ marginBottom: 13 }}>
        {resultKpis.map(item => <div className="fm-kpi" key={item.id}>
          <div className="fm-kpi-label">{item.label}</div><div className="fm-kpi-value"><ResultValue value={item.value} /></div><div className="fm-kpi-note">{item.note}</div>
          {item.trace && item.value.kind === "value" && <button className="fm-kpi-trace" type="button" aria-label={`Trace source for ${item.label}`} onKeyDown={event => {
            if (event.repeat || (event.key !== "Enter" && event.key !== " ")) return;
            event.preventDefault();
            setKpiTrace(item);
          }} onClick={() => setKpiTrace(item)}>Trace source</button>}
        </div>)}
      </div>
      {kpiTrace && <section className="fm-card fm-kpi-trace-panel" aria-label={`${kpiTrace.label} source trace`}>
        <div className="fm-card-title"><h2>{kpiTrace.label} · {resultsValueText(kpiTrace.value)}</h2><button className="fm-small-link" type="button" onClick={() => setKpiTrace(null)}>Close trace</button></div>
        <div className="fm-sw-trace-copy">
          <strong>{resultsStatus.dataOrigin === "synthetic-demo" ? `SYNTHETIC DISPLAY REFERENCE · ${resultsValueText(resultsStatus.runId)}` : "DISPLAY NAVIGATION REFERENCE · NO VERIFIED LINEAGE"}</strong>
          <span>Suggested workbook section: {kpiTrace.trace?.source} · Annual display context.</span>
          <span><strong>Calculation lineage unavailable.</strong> This navigation reference does not prove numerical dependency; the KPI stays fixed and does not recalculate.</span>
        </div>
        <a className="fm-sw-trace-open" href={kpiTraceHref(kpiTrace)} onKeyDown={event => {
          if (event.key !== "Enter") return;
          event.preventDefault();
          navigateFinco(kpiTraceHref(kpiTrace));
        }}>Open {kpiTrace.trace?.source} context →</a>
      </section>}
      <section className="fm-result-lineage" data-testid="results-working-copy-run-context" aria-label={`Working Copy compared with ${resultsStatus.dataOrigin === "synthetic-demo" ? "fixed synthetic output" : resultsStatus.dataOrigin === "caller-provided" ? "caller-provided output" : "unavailable output"}`}>
        <div>
          <span>{resultsStatus.productContext?.workingCopyMode === "reference" ? "PROTECTED REFERENCE · READ ONLY" : "WORKING COPY · CURRENT INPUT CONTEXT"}</span>
          <strong data-testid="results-scenario-context">Working Copy scenario · Scenario ID · {workingScenarioId} · {workingScenarioName}</strong>
          <small>{resultsStatus.productContext
            ? `Demo state: ${resultsStatus.productContext.workingCopyState.toUpperCase()}. Scenario selection is context only; input edits do not alter fixed output.`
            : "Draft/commit state is not supplied to this Results view. Input edits are not reflected in the displayed outputs."}</small>
        </div>
        <div>
          <span>LAST RUN · {resultsStatus.dataOrigin === "synthetic-demo" ? "FIXED SYNTHETIC REFERENCE" : resultsStatus.dataOrigin === "caller-provided" ? "CALLER-PROVIDED DISPLAY" : "UNAVAILABLE"}</span>
          <strong>{resultsValueText(resultsStatus.runId)} · {runStateLabel(resultsStatus)}</strong>
          <small>{resultsStatus.productContext?.lastRunTimestamp
            ? `Synthetic timestamp: ${resultsStatus.productContext.lastRunTimestamp} · `
            : selectedRunRecord ? `${resultsStatus.dataOrigin === "synthetic-demo" ? "Synthetic snapshot label" : "Unverified supplied timestamp"}: ${selectedRunRecord.timestamp} · ` : ""}
            Last Run scenario · {resultsStatus.productContext?.lastRunScenarioId || "Unavailable"} · Freshness {freshnessLabel(resultsStatus.freshness)} · engine {resultsValueText(resultsStatus.engineCurrency)} · integrity {resultsStatus.integrity.replace("-", " ").toUpperCase()}.</small>
          {resultsStatus.productContext?.lastRunScenarioId && resultsStatus.productContext.lastRunScenarioId !== resultsStatus.productContext.workingScenarioId &&
            <small role="status">Working Copy and Last Run scenarios differ. No scenario alignment or recalculation is implied.</small>}
          {resultsStatus.productContext?.runAttempt && <small role="status" data-testid="results-run-attempt">{resultsStatus.productContext.runAttempt.message}</small>}
        </div>
      </section>
      {panel !== "none" && <section id={panel} tabIndex={-1} aria-label={panel === "history" ? "Demo run history" : "Demo scenario comparison"} className="fm-card fm-section" style={{ marginBottom: 13 }}>
        <div className="fm-card-title"><h2>{panel === "history" ? "Run history" : "Scenario comparison"}</h2><button className="fm-small-link" onClick={() => { window.location.hash = "results"; }} type="button">Close panel</button></div>
        {panel === "history" ? <div className="fm-table-wrap"><table className="fm-table"><thead><tr><th>Run ref.</th><th>Model version</th><th>Scenario</th><th>Timestamp</th><th>Equity IRR</th><th>State</th></tr></thead><tbody>
          {resultsSnapshot?.history.map((row) => <tr key={row.id}><td className="fm-mono">{row.runRef}</td><td>{row.modelVersion}</td><td>{row.scenario}</td><td className="fm-mono">{row.timestamp}</td><td className="fm-mono"><ResultValue value={row.equityIrr} /></td><td><Status tone="gray">{row.state}</Status></td></tr>)}
          {!resultsSnapshot?.history.length && <tr><td colSpan={6}><span role="status">No run-history records were supplied.</span></td></tr>}
        </tbody></table></div> : <div className="fm-table-wrap"><table className="fm-table"><thead><tr><th>Scenario</th><th>Power price</th><th>Yield</th><th>Project IRR</th><th>Equity IRR</th><th>Min DSCR</th><th>NPV</th></tr></thead><tbody>
          {resultsSnapshot?.scenarios.map((row) => <tr key={row.id} style={{ background: selectedScenarioId === row.id ? "#f0f4f7" : undefined }}>
            <td><button className="fm-scenario-select" data-testid={`results-scenario-${row.id}`} type="button" aria-pressed={selectedScenarioId === row.id} onClick={() => chooseScenario(row.id)}>{row.name}</button></td>
            {[row.powerPrice, row.yield, row.projectIrr, row.equityIrr, row.minDscr, row.npv].map((v, i) => <td key={`${row.id}-${i}`} className="fm-mono"><ResultValue value={v} /></td>)}
          </tr>)}
          {!resultsSnapshot?.scenarios.length && <tr><td colSpan={7}><span role="status">No scenario-comparison rows were supplied.</span></td></tr>}
        </tbody></table><div style={{ padding: "8px 12px", color: "var(--muted)", fontSize: 9 }} role="status">
          {selectedScenario === "No scenario selected" ? "No scenario is available to select." : `Selected comparison case: ${selectedScenario}. Selection only highlights a row; it does not calculate outputs.`}
        </div></div>}
      </section>}
      <div className="fm-wb-status" aria-label="Independent result status dimensions">
        <span>Run identity: <strong><ResultValue value={resultsStatus.runId} /></strong></span>
        <span>Output state: <strong>{runStateLabel(resultsStatus)}</strong></span>
        <span>Financial freshness: <strong>{freshnessLabel(resultsStatus.freshness)}</strong></span>
        <span>Integrity: <strong>{resultsStatus.integrity.replace("-", " ").toUpperCase()}</strong></span>
        <span>Engine: <strong><ResultValue value={resultsStatus.engineCurrency} /></strong></span>
      </div>
      <div className="fm-wb-layout" style={{ marginBottom: 16 }}>
        <WorkbookNavigation active={statementSheet} />
        <StatementWorkbook
          snapshot={statementSnapshot}
          status={statementStatus}
          onSheetChange={setStatementSheet}
        />
      </div>
      <div className="fm-analysis-grid fm-section" id="analysis" tabIndex={-1}>
        <Panel title="Operating statement & debt service" meta={resultsSnapshot?.currencyLabel || "No supplied result data"}>
          <div className="fm-table-tools">
            <span id="statement-scroll-help">Scroll periods ↔ · Focus table, then use ← / →<br /><strong>{resultsStatus.dataOrigin === "synthetic-demo" ? "Fixed synthetic statement · Not recalculated" : "Display-only values · no calculations here"}</strong></span>
            <div><button type="button" className="fm-btn" aria-label="Scroll financial periods left" onClick={() => statement.current?.scrollBy({ left: -240, behavior: preferredScrollBehavior() })}>←</button> <button type="button" className="fm-btn" aria-label="Scroll financial periods right" onClick={() => statement.current?.scrollBy({ left: 240, behavior: preferredScrollBehavior() })}>→</button></div>
          </div>
          <div ref={statement} className="fm-table-wrap fm-statement-scroll" role="region" aria-label="Results summary table, scrollable periods" aria-describedby="statement-scroll-help" tabIndex={0}
            onKeyDown={event => {
              if (event.key === "ArrowRight" || event.key === "ArrowLeft") {
                event.preventDefault();
                event.currentTarget.scrollBy({ left: event.key === "ArrowRight" ? 120 : -120 });
              }
            }}>
          <table className="fm-table fm-statement-table">
            <caption className="fm-sr-only">{resultsSnapshot ? `${resultsStatus.dataOrigin === "synthetic-demo" ? "Synthetic " : ""}summary display rows; these are provided values and are not calculated by this component.` : "No results snapshot supplied; no synthetic table rows are shown."}</caption>
            <thead><tr><th scope="col">Annual operating period</th>{resultsSnapshot?.periods.map((period) => <th scope="col" key={period} className="right">{period}</th>)}</tr></thead>
            <tbody>{resultsSnapshot?.summaryRows.map((row) => <tr key={row.id} style={row.emphasis ? { background: "#f3f6f8" } : undefined}>
              <th scope="row" style={{ color: row.emphasis ? "var(--ink)" : undefined, fontWeight: row.emphasis ? 700 : undefined }}>{row.label}</th>
              {resultsSnapshot.periods.map((period, index) => <td key={`${row.id}-${period}`} className="right fm-mono"><ResultValue value={row.values[index] || { kind: "unavailable", reason: "No value supplied for this period." }} /></td>)}
            </tr>)}
            {!resultsSnapshot?.summaryRows.length && <tr><td colSpan={Math.max(1, 1 + (resultsSnapshot?.periods.length || 0))} role="status">No summary rows were supplied.</td></tr>}</tbody>
          </table></div>
        </Panel>
        <div style={{ display: "grid", gap: 13 }}>
          <Panel title="Key credit observations" meta={resultsStatus.dataOrigin === "synthetic-demo" ? "Fixed demonstration notes · not lender conclusions" : "Supplied display values · not assessed"}>
            {resultsSnapshot?.creditObservations.length ? resultsSnapshot.creditObservations.map((item) => <div className="fm-tiny-stat" key={item.id}><span>{item.label}</span><strong><ResultValue value={item.value} /></strong></div>) : <div role="status" className="fm-info-note">Credit observations unavailable.</div>}
          </Panel>
          <Panel title="Capital structure" meta="Display-only · not reconciled">
            {resultsSnapshot?.capitalStructure.length ? resultsSnapshot.capitalStructure.map((item) => <div className="fm-tiny-stat" key={item.id}><span>{item.label}</span><strong><ResultValue value={item.value} /></strong></div>) : <div role="status" className="fm-info-note">Capital structure data unavailable.</div>}
          </Panel>
        </div>
      </div>
      <div className="fm-analysis-grid" style={{ marginTop: 13 }}>
        <Panel title="Revenue profile" meta={resultsSnapshot?.charts.revenue?.meta || "No chart data supplied"}>
          <ResultsChart chart={resultsSnapshot?.charts.revenue || null} />
        </Panel>
        <Panel title="Cash available & debt service" meta={resultsSnapshot?.charts.cashDebt?.meta || "No chart data supplied"}>
          <ResultsChart chart={resultsSnapshot?.charts.cashDebt || null} />
        </Panel>
      </div>
      <div style={{ marginTop: 13 }}>
        <Panel title="Scheduled debt service profile" meta={resultsSnapshot?.charts.debtService?.meta || "No chart data supplied"}><ResultsChart chart={resultsSnapshot?.charts.debtService || null} /></Panel>
      </div>
      <div className="fm-footer">{resultsStatus.dataOrigin === "synthetic-demo" ? "Synthetic values are illustrative, not investment advice or a model output" : resultsStatus.dataOrigin === "caller-provided" ? "Caller-provided display values · source and financial authority are not verified here" : "No result data supplied"} · No export or live run is available in this prototype</div>
    </main>
  </Shell>;
}

export default ResultsAnalysisView;
