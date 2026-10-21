import React, { useState } from "react";
import { Status } from "../_shared/FincoShell";

const scenarioRows = [
  ["Installed capacity", "100 MWp", "100 MWp", "100 MWp", "—"],
  ["Yield case", "P50", "P90", "P50 + 3%", "—"],
  ["PPA / merchant price", "€62.50/MWh", "−12% fixed case", "+8% fixed case", "Illustrative only"],
  ["PPA allocation", "82% fixed ref.", "82% fixed ref.", "82% fixed ref.", "Not recalculated"],
  ["CAPEX", "€104.8m ref.", "€104.8m ref.", "€104.8m ref.", "Not linked to draft"],
  ["OPEX", "€1.8m ref.", "€1.8m ref.", "€1.8m ref.", "Not linked to draft"],
  ["Senior debt", "€67.0m ref.", "€67.0m ref.", "€67.0m ref.", "Not sized"],
  ["Project IRR", "7.82%", "6.11%", "9.06%", "Fixed snapshots"],
  ["Equity IRR", "12.46%", "9.18%", "15.31%", "Fixed snapshots"],
  ["NPV", "€8.7m", "€(4.2)m", "€21.3m", "Fixed snapshots"],
  ["Minimum DSCR", "1.25x", "1.08x", "1.39x", "Not a covenant test"],
  ["LLCR", "Unavailable", "Unavailable", "Unavailable", "No calculation"],
];
const runs = [
  { id: "DEMO-FIXED-018", date: "18 Jun 2025 · synthetic", scenario: "Base case", irr: "12.46%", dscr: "1.25x", version: "Not connected", capex: "€104.8m" },
  { id: "DEMO-FIXED-017", date: "16 Jun 2025 · synthetic", scenario: "Downside", irr: "9.18%", dscr: "1.08x", version: "Not connected", capex: "€104.8m" },
  { id: "DEMO-FIXED-014", date: "12 Jun 2025 · synthetic", scenario: "P90", irr: "8.74%", dscr: "1.02x", version: "Not connected", capex: "€106.1m" },
];
const sensitivity: Record<string, string[][]> = {
  "Energy yield": [["P90", "8.2%", "9.4%", "10.7%"], ["P50", "10.3%", "12.46%", "14.5%"], ["P50 + 3%", "11.1%", "13.6%", "15.8%"]],
  "PPA tariff": [["−10%", "8.2%", "9.7%", "11.2%"], ["Base", "10.3%", "12.46%", "14.5%"], ["+10%", "12.0%", "14.1%", "16.0%"]],
  "Merchant price": [["−10%", "8.6%", "10.4%", "12.1%"], ["Base", "10.3%", "12.46%", "14.5%"], ["+10%", "11.4%", "13.3%", "15.2%"]],
  "CAPEX": [["+10%", "9.1%", "10.7%", "12.2%"], ["Base", "10.3%", "12.46%", "14.5%"], ["−10%", "11.8%", "13.9%", "15.9%"]],
  "OPEX": [["+10%", "9.7%", "11.9%", "13.8%"], ["Base", "10.3%", "12.46%", "14.5%"], ["−10%", "10.9%", "13.1%", "15.0%"]],
  "Interest rate": [["+200 bps", "8.7%", "10.1%", "11.4%"], ["Base", "10.3%", "12.46%", "14.5%"], ["−100 bps", "11.0%", "13.2%", "15.1%"]],
};
const otherSensitivity: Record<string, Record<string, string[][]>> = {
  "Project IRR": {
    "Energy yield": [["P90", "5.7%", "6.1%", "6.6%"], ["P50", "6.9%", "7.82%", "8.7%"], ["P50 + 3%", "7.4%", "8.4%", "9.2%"]],
    "PPA tariff": [["−10%", "6.2%", "7.0%", "7.8%"], ["Base", "6.9%", "7.82%", "8.7%"], ["+10%", "7.7%", "8.6%", "9.5%"]],
    "Merchant price": [["−10%", "6.6%", "7.4%", "8.2%"], ["Base", "6.9%", "7.82%", "8.7%"], ["+10%", "7.2%", "8.1%", "9.0%"]],
    "CAPEX": [["+10%", "6.4%", "7.2%", "8.0%"], ["Base", "6.9%", "7.82%", "8.7%"], ["−10%", "7.4%", "8.3%", "9.2%"]],
    "OPEX": [["+10%", "6.7%", "7.6%", "8.5%"], ["Base", "6.9%", "7.82%", "8.7%"], ["−10%", "7.1%", "8.0%", "8.9%"]],
    "Interest rate": [["+200 bps", "6.4%", "7.2%", "8.0%"], ["Base", "6.9%", "7.82%", "8.7%"], ["−100 bps", "7.1%", "8.0%", "8.9%"]],
  },
  "Minimum DSCR": {
    "Energy yield": [["P90", "1.02x", "1.08x", "1.13x"], ["P50", "1.18x", "1.25x", "1.31x"], ["P50 + 3%", "1.22x", "1.29x", "1.35x"]],
    "PPA tariff": [["−10%", "1.12x", "1.18x", "1.23x"], ["Base", "1.18x", "1.25x", "1.31x"], ["+10%", "1.23x", "1.30x", "1.36x"]],
    "Merchant price": [["−10%", "1.15x", "1.21x", "1.27x"], ["Base", "1.18x", "1.25x", "1.31x"], ["+10%", "1.20x", "1.27x", "1.33x"]],
    "CAPEX": [["+10%", "1.14x", "1.20x", "1.26x"], ["Base", "1.18x", "1.25x", "1.31x"], ["−10%", "1.21x", "1.28x", "1.34x"]],
    "OPEX": [["+10%", "1.16x", "1.22x", "1.28x"], ["Base", "1.18x", "1.25x", "1.31x"], ["−10%", "1.20x", "1.27x", "1.33x"]],
    "Interest rate": [["+200 bps", "1.11x", "1.17x", "1.23x"], ["Base", "1.18x", "1.25x", "1.31x"], ["−100 bps", "1.22x", "1.28x", "1.34x"]],
  },
};

export default function DecisionAnalysisWorkspace({ sheet }: { sheet: string }) {
  const [selectedRuns, setSelectedRuns] = useState<string[]>(() => {
    const params = new URLSearchParams(window.location.search);
    const requested = (params.get("runSet") || "").split(",").filter(id => runs.some(run => run.id === id)).slice(0, 3);
    return requested.length ? requested : ["DEMO-FIXED-018", "DEMO-FIXED-017"];
  });
  const [driver, setDriver] = useState(() => {
    const requested = new URLSearchParams(window.location.search).get("driver");
    return requested && Object.prototype.hasOwnProperty.call(sensitivity, requested) ? requested : "Energy yield";
  });
  const [outcome, setOutcome] = useState(() => {
    const requested = new URLSearchParams(window.location.search).get("outcome");
    return requested && Object.prototype.hasOwnProperty.call(otherSensitivity, requested) ? requested : "Equity IRR";
  });
  const [target, setTarget] = useState(() => {
    const requested = new URLSearchParams(window.location.search).get("target");
    return ["Equity IRR", "Project IRR", "Minimum DSCR", "NPV"].includes(requested || "") ? requested || "Equity IRR" : "Equity IRR";
  });
  const isScenario = sheet === "compare";
  const isRunCompare = sheet === "run-compare";
  const isSensitivity = sheet === "sensitivity";
  const heading = isScenario ? "Scenario comparison workbook" : isRunCompare ? "Fixed Run comparison" : isSensitivity ? "Sensitivity analysis" : "Goal Seek · decision tool";

  function toggleRun(id: string) {
    setSelectedRuns(current => {
      const next = current.includes(id) ? current.filter(item => item !== id) : current.length < 3 ? [...current, id] : current;
      const params = new URLSearchParams(window.location.search);
      params.set("runSet", next.join(","));
      window.history.replaceState(null, "", `${window.location.pathname}?${params.toString()}${window.location.hash}`);
      return next;
    });
  }

  function setDisplayContext(key: string, value: string, setter: (value: string) => void) {
    setter(value);
    const params = new URLSearchParams(window.location.search);
    params.set(key, value);
    window.history.replaceState(null, "", `${window.location.pathname}?${params.toString()}${window.location.hash}`);
  }

  return <div className="fm-wf fm-decision-workspace" aria-label={heading}>
    <div className="fm-wf-notice" role="note"><strong>SYNTHETIC DECISION ANALYSIS</strong><span>Pre-authored fixed tables only. Editing assumptions never generates financial outcomes; no solver or model Run is connected.</span></div>
    <div className="fm-wf-toolbar"><div><strong>{heading}</strong><div className="fm-wf-muted">DEMO-FIXED-018 · fixed comparison context</div></div><Status tone="amber">NO LIVE CALCULATIONS</Status></div>

    {isScenario && <section className="fm-wf-section">
      <div className="fm-wf-editor-head"><div><h3>Base, Downside & Upside</h3><p>Fixed scenario snapshots; assumption values do not recalculate outcomes.</p></div><Status tone="gray">DIFFERENCE COLUMN IS DESCRIPTIVE</Status></div>
      <div className="fm-wf-scroll"><table className="fm-table fm-wf-table fm-wf-period-table">
        <thead><tr>{["Metric", "Base case", "Downside", "Upside", "Difference / status"].map(label => <th key={label} scope="col">{label}</th>)}</tr></thead>
        <tbody>{scenarioRows.map(row => <tr key={row[0]}><th scope="row">{row[0]}</th>{row.slice(1).map((value, index) => <td key={index}>{value}</td>)}</tr>)}</tbody>
      </table></div>
      <div className="fm-wf-note">PPA shares, costs and debt are fixed reference values. Scenario IRR, NPV and DSCR are authored examples; no deltas are calculated.</div>
    </section>}

    {isRunCompare && <section className="fm-wf-section">
      <div className="fm-wf-editor-head"><div><h3>Select up to three illustrative runs</h3><p>Selections change only the displayed fixed context and never mutate a Working Copy.</p></div><Status tone="gray">NO EXECUTION HISTORY</Status></div>
      <div className="fm-wf-run-picker">{runs.map(run => <label key={run.id}><input type="checkbox" checked={selectedRuns.includes(run.id)} onChange={() => toggleRun(run.id)} disabled={!selectedRuns.includes(run.id) && selectedRuns.length >= 3} /><span><strong>{run.id}</strong><small>{run.scenario} · {run.date}</small></span></label>)}</div>
      <div className="fm-wf-scroll"><table className="fm-table fm-wf-table fm-wf-period-table">
        <thead><tr><th scope="col">Metric</th>{runs.filter(run => selectedRuns.includes(run.id)).map(run => <th scope="col" key={run.id}>{run.id}</th>)}</tr></thead>
        <tbody>{([
          ["Scenario", run => run.scenario], ["Snapshot date", run => run.date], ["Engine version", run => run.version],
          ["Equity IRR · fixed", run => run.irr], ["Minimum DSCR · fixed", run => run.dscr], ["CAPEX reference", run => run.capex],
          ["Input snapshot", () => "Unavailable"], ["Period match", () => "NOT VERIFIED"],
        ] as [string, (run: typeof runs[number]) => string][]).map(([label, getter]) => <tr key={label}><th scope="row">{label}</th>{runs.filter(run => selectedRuns.includes(run.id)).map(run => <td key={run.id}>{getter(run)}</td>)}</tr>)}</tbody>
      </table></div>
      <div className="fm-wf-note">Period-by-period DSCR/debt-service matching is unavailable. Period dates and input hashes are not verified; no alignment by array index is claimed.</div>
    </section>}

    {isSensitivity && <section className="fm-wf-section">
      <div className="fm-wf-editor-head"><div><h3>Fixed sensitivity fixture</h3><p>Read-only matrix examples. Not a live solver or recalculation.</p></div><Status tone="gray">PRE-AUTHORED EXAMPLES</Status></div>
      <div className="fm-wf-controls">
        <label className="fm-wf-field">Illustrative driver <span>Changes displayed fixture only</span><select aria-label="Sensitivity driver" value={driver} onChange={event => setDisplayContext("driver", event.target.value, setDriver)}>{Object.keys(sensitivity).map(value => <option key={value}>{value}</option>)}</select></label>
        <label className="fm-wf-field">Displayed outcome <span>Fixed table selector</span><select aria-label="Sensitivity output metric" value={outcome} onChange={event => setDisplayContext("outcome", event.target.value, setOutcome)}><option>Project IRR</option><option>Equity IRR</option><option>Minimum DSCR</option></select></label>
      </div>
      <div className="fm-wf-scroll"><table className="fm-table fm-wf-table fm-wf-period-table">
        <caption>Fixed synthetic {outcome} snapshot · driver: {driver}</caption>
        <thead><tr><th scope="col">{driver} fixture</th><th scope="col">Low case</th><th scope="col">Reference case</th><th scope="col">High case</th></tr></thead>
        <tbody>{(outcome === "Equity IRR" ? sensitivity[driver] : otherSensitivity[outcome][driver]).map((row,index) => <tr key={row[0]}><th scope="row">{row[0]}</th>{row.slice(1).map(value => <td className="fm-mono" key={value}>{value}</td>)}</tr>)}</tbody>
      </table></div>
      <div className="fm-wf-note">PPA tariff, merchant price, CAPEX, OPEX, interest, yield, Project IRR, Equity IRR and DSCR are relevant analysis families. This limited static fixture does not calculate any family or return a solver result.</div>
    </section>}

    {!isScenario && !isRunCompare && !isSensitivity && <section className="fm-wf-section">
      <div className="fm-wf-editor-head"><div><h3>Goal Seek setup</h3><p>Design preview only. No financial solver is available.</p></div><Status tone="amber">SOLVER UNAVAILABLE</Status></div>
      <div className="fm-wf-grid fm-wf-fields">
        <label className="fm-wf-field">Target metric <span>Preview selection</span><select aria-label="Goal seek target metric" value={target} onChange={event => setDisplayContext("target", event.target.value, setTarget)}><option>Equity IRR</option><option>Project IRR</option><option>Minimum DSCR</option><option>NPV</option></select></label>
        <label className="fm-wf-field">Adjustable variable <span>Not connected to inputs</span><select aria-label="Goal seek adjustable variable"><option>PPA tariff</option><option>CAPEX</option><option>Debt commitment</option><option>Interest rate</option></select></label>
        <label className="fm-wf-field">Target value <span>Illustrative target</span><input aria-label="Goal seek target value" defaultValue={target === "Minimum DSCR" ? "1.25x" : "12.0%"} /></label>
        <label className="fm-wf-field">Bounds / constraints <span>Design example</span><input aria-label="Goal seek bounds" defaultValue="Not evaluated" /></label>
      </div>
      <div className="fm-wf-summary fm-wf-summary">
        <div><span>Solver status</span><strong>UNAVAILABLE</strong><small>No convergence or result will be fabricated.</small></div>
        <div><span>Illustrative output</span><strong>{target} · Not calculated</strong><small>Changing the target only changes this label.</small></div>
      </div>
      <div className="fm-wf-actions"><span className="fm-wf-muted">No model Run or input mutation</span><button type="button" className="fm-btn" disabled>Run Goal Seek · unavailable</button></div>
    </section>}
  </div>;
}
