import React, { useEffect, useRef, useState } from "react";
import "./ResultsAnalysis.css";
import "./_group.css";
import StatementWorkbook from "./_workbook/StatementWorkbook";
import WorkbookNavigation from "./_workbook/WorkbookNavigation";
import "./_workbook/workbook.css";
import { DemoBanner, DemoContextStrip, fincoBasePath, ModelNav, navigateFinco, Panel, readProjectContext, Shell, Status } from "./_shared/FincoShell";
import { preferredScrollBehavior } from "./_shared/motion";
import type { StatementRunStatus, StatementWorkbookSnapshot } from "./_workbook/statementContract";

const periods = ["2027", "2028", "2029", "2030", "2031", "2032", "2033", "2034"];
const rows = [
  ["Net generation (GWh)", "185.0", "194.4", "193.5", "192.7", "191.8", "190.9", "190.1", "189.2"],
  ["Revenue (€m)", "13.1", "15.2", "15.4", "15.6", "15.7", "15.9", "16.0", "16.2"],
  ["Operating costs (€m)", "(1.8)", "(1.7)", "(1.8)", "(1.8)", "(1.9)", "(1.9)", "(2.0)", "(2.0)"],
  ["EBITDA (€m)", "11.3", "13.5", "13.6", "13.8", "13.8", "14.0", "14.0", "14.2"],
  ["Cash available for debt service (€m)", "8.4", "10.6", "10.9", "11.0", "11.2", "11.4", "11.6", "11.8"],
  ["Scheduled debt service (€m)", "(6.7)", "(8.4)", "(8.5)", "(8.6)", "(8.7)", "(8.9)", "(9.0)", "(9.2)"],
  ["DSCR (x)", "1.25", "1.26", "1.28", "1.28", "1.29", "1.28", "1.29", "1.28"],
  ["Cash flow to equity (€m)", "1.1", "1.7", "1.8", "1.8", "1.9", "1.9", "2.0", "2.0"],
];

function RevenueChart() {
  return <svg className="fm-chart" viewBox="0 0 600 155" role="img" aria-label="Illustrative revenue by year, increasing from 13.1 to 16.2 million euros">
    {[25, 58, 91, 124].map((y) => <line key={y} x1="47" y1={y} x2="584" y2={y} className="fm-chart-grid" />)}
    <path d="M50 107 L125 85 L200 81 L275 75 L350 72 L425 65 L500 61 L577 55 L577 124 L50 124 Z" className="fm-chart-area" />
    <path d="M50 107 L125 85 L200 81 L275 75 L350 72 L425 65 L500 61 L577 55" className="fm-chart-line" />
    {[["2027",50],["2028",125],["2029",200],["2030",275],["2031",350],["2032",425],["2033",500],["2034",577]].map(([year,x]) => <text key={year} x={x} y="145" textAnchor="middle" className="fm-chart-label">{year}</text>)}
    <text x="4" y="28" className="fm-chart-label">€18m</text><text x="4" y="126" className="fm-chart-label">€10m</text>
    {[["13.1",50,107],["15.2",125,85],["16.2",577,55]].map(([v,x,y]) => <circle key={`${v}-${x}`} cx={x} cy={y} r="2.8" fill="#315f83" />)}
  </svg>;
}
function CashChart() {
  const cashAvailable = rows[4].slice(1).map(Number);
  const debtService = rows[5].slice(1).map((value) => Number(value.replace(/[()]/g, "")));
  const height = (value: number) => value / 14 * 99;
  return <svg className="fm-chart" viewBox="0 0 600 155" role="img" aria-label="Illustrative cash flow and debt service trend">
    {[25, 58, 91, 124].map((y) => <line key={y} x1="45" y1={y} x2="585" y2={y} className="fm-chart-grid" />)}
    {periods.map((year, i) => {
      const x = 62 + i * 72;
      return <g key={year}><rect x={x} y={124-height(cashAvailable[i])} width="18" height={height(cashAvailable[i])} className="fm-chart-bar"><title>{year} cash available: €{cashAvailable[i].toFixed(1)}m</title></rect><rect x={x+20} y={124-height(debtService[i])} width="18" height={height(debtService[i])} className="fm-chart-bar-alt"><title>{year} debt service: €{debtService[i].toFixed(1)}m</title></rect><text x={x+19} y="145" textAnchor="middle" className="fm-chart-label">{year}</text></g>;
    })}
    <text x="3" y="28" className="fm-chart-label">€14m</text><text x="3" y="126" className="fm-chart-label">€0</text>
  </svg>;
}
function WaterfallChart() {
  const amounts = rows[5].slice(1).map((value) => Number(value.replace(/[()]/g, "")));
  return <svg className="fm-chart" viewBox="0 0 600 155" role="img" aria-label="Illustrative annual debt service profile">
    {[25, 58, 91, 124].map((y) => <line key={y} x1="46" y1={y} x2="586" y2={y} className="fm-chart-grid" />)}
    {periods.map((year, i) => {
      const x=58+i*66;
      const height = amounts[i] / 10 * 99;
      return <g key={year}><rect x={x} y={124-height} width="33" height={height} className="fm-chart-bar"><title>{year}: €{amounts[i].toFixed(1)}m scheduled debt service</title></rect><text x={x+16} y="145" textAnchor="middle" className="fm-chart-label">{year}</text></g>;
    })}
    <text x="4" y="28" className="fm-chart-label">€10m</text><text x="4" y="126" className="fm-chart-label">€0</text>
  </svg>;
}

export type ResultsAnalysisProps = {
  statementSnapshot?: StatementWorkbookSnapshot;
  statementStatus?: StatementRunStatus;
};

export function ResultsAnalysis({ statementSnapshot, statementStatus }: ResultsAnalysisProps = {}) {
  const statement = useRef<HTMLDivElement>(null);
  const project = readProjectContext();
  const [statementSheet, setStatementSheet] = useState(new URLSearchParams(window.location.search).get("statement") || "pl");
  const [section, setSection] = useState(window.location.hash.slice(1) || "results");
  const [panel, setPanel] = useState<"none" | "history" | "scenarios">(() => window.location.hash === "#scenarios" ? "scenarios" : window.location.hash === "#history" ? "history" : "none");
  const [kpiTrace, setKpiTrace] = useState<null | { label: string; value: string; source: string; workspaceSheet: string; statement: string; row: string }>(null);
  const scenarioKey = new URLSearchParams(window.location.search).get("scenario");
  const scenarioNames: Record<string, string> = { base: "Base case", downside: "Downside", upside: "Upside" };
  const [selectedScenario, setSelectedScenario] = useState(scenarioNames[scenarioKey || "base"] || "Base case");
  useEffect(() => {
    const sync = () => {
      const id = window.location.hash.slice(1) || "results";
      setSection(id);
      setPanel(id === "scenarios" ? "scenarios" : id === "history" ? "history" : "none");
    };
    window.addEventListener("hashchange", sync);
    return () => window.removeEventListener("hashchange", sync);
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
  function kpiTraceHref(trace: NonNullable<typeof kpiTrace>) {
    const params = new URLSearchParams(window.location.search);
    params.delete("statement");
    params.delete("statementView");
    params.delete("traceRow");
    params.set("sheet", trace.workspaceSheet);
    params.set("returnStatement", trace.statement);
    params.set("returnView", "annual");
    params.set("returnRow", trace.row);
    params.set("returnPeriod", "0");
    params.set("returnScrollLeft", "0");
    params.set("returnScrollY", String(Math.round(window.scrollY)));
    return `${fincoBasePath()}ModelWorkspace?${params.toString()}#workbook`;
  }
  const activeNav = section === "scenarios" ? "Scenarios" : section === "analysis" ? "Analysis" : "Results";
  function chooseScenario(name: string) {
    setSelectedScenario(name);
    const key = Object.entries(scenarioNames).find(([, label]) => label === name)?.[0] || "base";
    const params = new URLSearchParams(window.location.search);
    params.set("scenario", key);
    window.history.replaceState(null, "", `${window.location.pathname}?${params}${window.location.hash}`);
  }
  return <Shell crumb={`${project.name} · ${project.technology} · Results`}>
    <main className="fm-shell" id="results" tabIndex={-1}>
      <DemoBanner copy="FIXED SYNTHETIC DEMO VALUES · Shared illustrative outputs, not project-specific results. Input edits do not recalculate or sync." />
      <DemoContextStrip workingState="FIXED LAST RUN REFERENCE · READ-ONLY" />
      <div className="fm-shell-header">
        <div><div className="fm-eyebrow">{project.id} · Shared demo v1.4 · 18 Jun 2025</div><h1 className="fm-title">Results & analysis</h1><div className="fm-subtitle">{project.name} <span style={{ margin: "0 7px" }}>·</span> {project.technology} <span style={{ margin: "0 7px" }}>·</span> Shared synthetic example · EUR nominal</div></div>
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
        <strong style={{ color: "var(--ink)" }}>Results are fixed demo values.</strong> “Run demo” only opens this predetermined illustration. No calculations are run and no results reflect the input edits made in the workspace. Project identity is shown for navigation context only.
      </div>
      <div className="fm-kpi-grid" style={{ marginBottom: 13 }}>
        {[
          { label: "Project IRR", value: "7.82%", note: "Unlevered · nominal EUR", source: "Sponsor Returns", workspaceSheet: "investor", statement: "sponsor", row: "sponsor-irr" },
          { label: "Equity IRR", value: "12.46%", note: "Levered · post-tax", source: "Investor / sponsor returns", workspaceSheet: "investor", statement: "sponsor", row: "sponsor-irr" },
          { label: "NPV @ 7.0%", value: "€8.7m", note: "Project cash flow · nominal", source: "Cash Flow", workspaceSheet: "inputs", statement: "cashflow", row: "net-change" },
          { label: "Minimum DSCR", value: "1.25x", note: "Year 2027 · senior debt", source: "CFADS", workspaceSheet: "credit-decision", statement: "cfads", row: "dscr" },
        ].map(item => <div className="fm-kpi" key={item.label}>
          <div className="fm-kpi-label">{item.label}</div><div className="fm-kpi-value">{item.value}</div><div className="fm-kpi-note">{item.note}</div>
          <button className="fm-kpi-trace" type="button" aria-label={`Open synthetic trace for ${item.label}`} onClick={() => setKpiTrace(item)}>Trace source</button>
        </div>)}
      </div>
      {kpiTrace && <section className="fm-card fm-kpi-trace-panel" aria-label={`${kpiTrace.label} source trace`}>
        <div className="fm-card-title"><h2>{kpiTrace.label} · {kpiTrace.value}</h2><button className="fm-small-link" type="button" onClick={() => setKpiTrace(null)}>Close trace</button></div>
        <div className="fm-sw-trace-copy">
          <strong>SYNTHETIC KPI TRACE · DEMO-FIXED-018</strong>
          <span>Suggested workbook section: {kpiTrace.source} · Annual illustrative context.</span>
          <span><strong>Calculation lineage unavailable.</strong> This navigation reference does not prove numerical dependency; the KPI stays fixed and does not recalculate.</span>
        </div>
        <a className="fm-sw-trace-open" href={kpiTraceHref(kpiTrace)}>Open {kpiTrace.source} context →</a>
      </section>}
      <section className="fm-result-lineage" aria-label="Working Copy compared with fixed synthetic result">
        <div>
          <span>WORKING COPY · WORKSPACE</span>
          <strong>Local draft assumptions</strong>
          <small>Edits remain in Model Workspace; no live model or project-specific values are passed to this view.</small>
        </div>
        <div>
          <span>DISPLAYED OUTPUT · PRESET DEMO</span>
          <strong>DEMO-FIXED-018 · synthetic snapshot</strong>
          <small>Project IRR, Equity IRR, NPV and DSCR are fixed illustrations—not a run of the Working Copy.</small>
        </div>
      </section>
      {panel !== "none" && <section id={panel} tabIndex={-1} aria-label={panel === "history" ? "Demo run history" : "Demo scenario comparison"} className="fm-card fm-section" style={{ marginBottom: 13 }}>
        <div className="fm-card-title"><h2>{panel === "history" ? "Run history" : "Scenario comparison"}</h2><button className="fm-small-link" onClick={() => { window.location.hash = "results"; }} type="button">Close panel</button></div>
        {panel === "history" ? <div className="fm-table-wrap"><table className="fm-table"><thead><tr><th>Run ref.</th><th>Model version</th><th>Scenario</th><th>Timestamp</th><th>Equity IRR</th><th>State</th></tr></thead><tbody>
          <tr><td className="fm-mono">DEMO-FIXED-018</td><td>v1.4</td><td>Base case</td><td className="fm-mono">18 Jun 2025 · synthetic</td><td className="fm-mono">12.46%</td><td><Status tone="gray">Fixed illustrative record</Status></td></tr>
          <tr><td className="fm-mono">DEMO-FIXED-017</td><td>v1.3</td><td>Downside</td><td className="fm-mono">16 Jun 2025 · synthetic</td><td className="fm-mono">9.18%</td><td><Status tone="gray">Fixed illustrative record</Status></td></tr>
          <tr><td className="fm-mono">DEMO-FIXED-014</td><td>Unverified</td><td>P90 reference</td><td className="fm-mono">12 Jun 2025 · synthetic</td><td className="fm-mono">8.74%</td><td><Status tone="gray">Fixed illustrative record</Status></td></tr>
        </tbody></table></div> : <div className="fm-table-wrap"><table className="fm-table"><thead><tr><th>Scenario</th><th>Power price</th><th>Yield</th><th>Project IRR</th><th>Equity IRR</th><th>Min DSCR</th><th>NPV</th></tr></thead><tbody>
          {[["Base case","€62.50/MWh","P50","7.82%","12.46%","1.25x","€8.7m"],["Downside","−12%","P90","6.11%","9.18%","1.08x","€(4.2)m"],["Upside","+8%","P50 +3%","9.06%","15.31%","1.39x","€21.3m"]].map((row) => <tr key={row[0]} style={{ background: selectedScenario === row[0] ? "#f0f4f7" : undefined }}>{row.map((v,i) => <td key={v} className={i > 0 ? "fm-mono" : ""}>{i === 0 ? <button className="fm-scenario-select" type="button" aria-pressed={selectedScenario === v} onClick={() => chooseScenario(v)}>{v}</button> : v}</td>)}</tr>)}
        </tbody></table><div style={{ padding: "8px 12px", color: "var(--muted)", fontSize: 9 }} role="status">Selected comparison case: {selectedScenario}. Selection only highlights a row; all figures and headline KPIs remain fixed synthetic examples.</div></div>}
      </section>}
      <div className="fm-wb-status"><span>Run identity: <strong>DEMO-FIXED-018</strong></span><span>UI state: <strong>{new URLSearchParams(window.location.search).get("demoRun") ? "CURRENT DEMO SNAPSHOT" : "NOT RUN · fixed reference only"}</strong></span><span>Financial freshness: <strong>UNKNOWN / no input linkage</strong></span><span>Integrity: <strong>NOT EVALUATED</strong></span><span>Engine: <strong>NOT CONNECTED</strong></span></div>
      <div className="fm-wb-layout" style={{ marginBottom: 16 }}>
        <WorkbookNavigation active={statementSheet} />
        <StatementWorkbook
          snapshot={statementSnapshot}
          status={statementStatus}
          onSheetChange={setStatementSheet}
        />
      </div>
      <div className="fm-analysis-grid fm-section" id="analysis" tabIndex={-1}>
        <Panel title="Operating statement & debt service" meta="EUR millions, unless stated">
          <div className="fm-table-tools">
            <span id="statement-scroll-help">Scroll periods ↔ · Focus table, then use ← / →<br /><strong>Fixed synthetic statement · Not recalculated</strong></span>
            <div><button type="button" className="fm-btn" aria-label="Scroll financial periods left" onClick={() => statement.current?.scrollBy({ left: -240, behavior: preferredScrollBehavior() })}>←</button> <button type="button" className="fm-btn" aria-label="Scroll financial periods right" onClick={() => statement.current?.scrollBy({ left: 240, behavior: preferredScrollBehavior() })}>→</button></div>
          </div>
          <div ref={statement} className="fm-table-wrap fm-statement-scroll" role="region" aria-label="Synthetic operating statement, scrollable periods" aria-describedby="statement-scroll-help" tabIndex={0}
            onKeyDown={event => {
              if (event.key === "ArrowRight" || event.key === "ArrowLeft") {
                event.preventDefault();
                event.currentTarget.scrollBy({ left: event.key === "ArrowRight" ? 120 : -120 });
              }
            }}>
          <table className="fm-table fm-statement-table">
            <caption className="fm-sr-only">Fixed synthetic operating statement and debt service, annual periods 2027–2034. Input edits do not change these figures.</caption>
            <thead><tr><th scope="col">Annual operating period</th>{periods.map((p) => <th scope="col" key={p} className="right">{p}</th>)}</tr></thead>
            <tbody>{rows.map((row) => <tr key={row[0]} style={row[0].startsWith("Cash available") || row[0].startsWith("DSCR") ? { background: "#f3f6f8" } : undefined}>
              <th scope="row" style={{ color: row[0].startsWith("Cash available") ? "var(--ink)" : undefined, fontWeight: row[0].startsWith("Cash available") || row[0].startsWith("DSCR") ? 700 : undefined }}>{row[0]}</th>
              {row.slice(1).map((v, i) => <td key={i} className="right fm-mono">{v}</td>)}
            </tr>)}</tbody>
          </table></div>
        </Panel>
        <div style={{ display: "grid", gap: 13 }}>
          <Panel title="Key credit observations" meta="Fixed demonstration notes">
            <div className="fm-tiny-stat"><span>Lowest DSCR</span><strong>1.25x · 2027</strong></div>
            <div className="fm-tiny-stat"><span>Weighted average DSCR</span><strong>1.28x</strong></div>
            <div className="fm-tiny-stat"><span>Debt / total uses</span><strong>63.9%</strong></div>
            <div className="fm-tiny-stat"><span>PPA contracted generation</span><strong>82% · 18 years</strong></div>
            <div className="fm-tiny-stat"><span>Debt maturity</span><strong>2045</strong></div>
          </Panel>
          <Panel title="Capital structure" meta="At financial close">
            <div className="fm-tiny-stat"><span>Senior secured debt</span><strong>€67.0m · 63.9%</strong></div>
            <div className="fm-tiny-stat"><span>Sponsor equity</span><strong>€37.8m · 36.1%</strong></div>
            <div className="fm-tiny-stat"><span>Total project cost</span><strong>€104.8m</strong></div>
          </Panel>
        </div>
      </div>
      <div className="fm-analysis-grid" style={{ marginTop: 13 }}>
        <Panel title="Revenue profile" meta="€m · synthetic series">
          <RevenueChart />
          <div style={{ display: "flex", gap: 13, padding: "0 13px 11px", color: "var(--muted)", fontSize: 9 }}><span><i style={{ display: "inline-block", width: 9, height: 3, background: "#315f83", marginRight: 5, verticalAlign: "middle" }} />Revenue</span><span>PPA tariff with merchant tail · annual periods</span></div>
        </Panel>
        <Panel title="Cash available & debt service" meta="€m · synthetic series">
          <CashChart />
          <div style={{ display: "flex", gap: 13, padding: "0 13px 11px", color: "var(--muted)", fontSize: 9 }}><span><i style={{ display: "inline-block", width: 8, height: 8, background: "#507797", marginRight: 5, verticalAlign: "middle" }} />Cash available</span><span><i style={{ display: "inline-block", width: 8, height: 8, background: "#b8c6d0", marginRight: 5, verticalAlign: "middle" }} />Debt service</span></div>
        </Panel>
      </div>
      <div style={{ marginTop: 13 }}>
        <Panel title="Scheduled debt service profile" meta="€m · same fixed series as statement"><WaterfallChart /></Panel>
      </div>
      <div className="fm-footer">Synthetic values are illustrative, not investment advice or a model output · No export or live run is available in this prototype</div>
    </main>
  </Shell>;
}
