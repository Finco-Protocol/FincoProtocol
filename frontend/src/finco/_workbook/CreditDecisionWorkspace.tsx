import React, { useEffect, useState } from "react";
import { readProjectContext, Status } from "../_shared/FincoShell";
import { workbookHref } from "./catalog";

type Facility = "Senior Debt A" | "Senior Debt B" | "Junior / Mezzanine";
type Basis = "annual" | "model";

const reviewRows = [
  ["Minimum DSCR", "1.25x", "1.08x", "1.02x", "≥ 1.20x", "REVIEW REQUIRED", "DEMO-FIXED-018 · not a covenant test"],
  ["Average DSCR", "1.28x", "1.16x", "1.11x", "≥ 1.25x", "NOT EVALUATED", "No period aggregation performed"],
  ["Maturity / repayment status", "2045 · sculpted ref.", "2043 · amortising ref.", "Not assessed", "Not assessed", "NOT EVALUATED", "No maturity or repayment test"],
  ["CFADS", "€8.4m", "€7.1m", "€6.8m", "Unavailable", "OBSERVED", "Fixed CFADS example"],
  ["Debt service", "€6.7m", "€6.5m", "€6.4m", "Unavailable", "OBSERVED", "Fixed statement snapshot"],
  ["LLCR", "Unavailable", "Unavailable", "Unavailable", "Unavailable", "UNAVAILABLE", "No discounted debt-life analysis"],
  ["PLCR", "Unavailable", "Unavailable", "Unavailable", "Unavailable", "UNAVAILABLE", "No discounted project-life analysis"],
  ["Debt balance at maturity", "Not assessed", "Not assessed", "Not assessed", "Not assessed", "NOT EVALUATED", "No maturity test"],
  ["Distribution lock-up / cash sweep", "Not assessed", "Not assessed", "Not assessed", "Unavailable", "NOT EVALUATED", "No covenant or restriction test"],
];

const annualPeriods = ["2027", "2028", "2029", "2030", "2031", "2032"];
const modelPeriods = ["2026 M10", "2026 M12", "2027 Q3", "2027 Q4", "2028 Q1", "2028 Q2"];
const facilityRows: Record<Facility, { opening: string[]; draws: string[]; interest: string[]; principal: string[]; service: string[]; closing: string[]; cfads: string[]; dscr: string[]; reserve: string[] }> = {
  "Senior Debt A": {
    opening: ["—", "12.6", "18.7", "18.7", "18.7", "16.3"],
    draws: ["12.1", "5.8", "—", "—", "—", "—"],
    interest: ["(0.4)", "(0.6)", "(0.9)", "(0.9)", "(0.8)", "(0.8)"],
    principal: ["—", "—", "(2.4)", "(2.5)", "(2.2)", "(2.3)"],
    service: ["—", "—", "(3.4)", "(3.5)", "(3.1)", "(3.2)"],
    closing: ["12.6", "18.7", "18.7", "18.7", "16.3", "14.0"],
    cfads: ["—", "—", "2.6", "2.7", "2.8", "2.7"],
    dscr: ["—", "—", "1.30x", "1.29x", "1.27x", "1.24x"],
    reserve: ["0.2", "0.4", "0.6", "0.8", "0.9", "1.0"],
  },
  "Senior Debt B": {
    opening: ["—", "8.4", "14.1", "14.1", "14.1", "13.2"],
    draws: ["8.1", "5.2", "—", "—", "—", "—"],
    interest: ["(0.3)", "(0.5)", "(0.8)", "(0.8)", "(0.8)", "(0.7)"],
    principal: ["—", "—", "(1.4)", "(1.5)", "(1.5)", "(1.5)"],
    service: ["—", "—", "(2.2)", "(2.3)", "(2.3)", "(2.2)"],
    closing: ["8.4", "14.1", "14.1", "14.1", "13.2", "11.7"],
    cfads: ["—", "—", "2.6", "2.7", "2.8", "2.7"],
    dscr: ["—", "—", "1.18x", "1.17x", "1.16x", "1.15x"],
    reserve: ["0.1", "0.3", "0.4", "0.5", "0.6", "0.7"],
  },
  "Junior / Mezzanine": {
    opening: ["—", "2.4", "3.5", "3.5", "3.5", "3.2"],
    draws: ["2.3", "1.0", "—", "—", "—", "—"],
    interest: ["(0.1)", "(0.2)", "(0.3)", "(0.3)", "(0.3)", "(0.3)"],
    principal: ["—", "—", "(0.1)", "(0.1)", "(0.1)", "(0.1)"],
    service: ["—", "—", "(0.4)", "(0.4)", "(0.4)", "(0.4)"],
    closing: ["2.4", "3.5", "3.5", "3.5", "3.2", "3.1"],
    cfads: ["—", "—", "2.6", "2.7", "2.8", "2.7"],
    dscr: ["—", "—", "1.08x", "1.07x", "1.06x", "1.05x"],
    reserve: ["—", "—", "Not linked", "Not linked", "Not linked", "Not linked"],
  },
};

const scheduleLabels: [keyof typeof facilityRows["Senior Debt A"], string][] = [
  ["opening", "Opening debt"],
  ["draws", "Construction draw"],
  ["interest", "Interest / IDC"],
  ["principal", "Scheduled principal"],
  ["service", "Total debt service"],
  ["closing", "Closing debt"],
  ["cfads", "CFADS · fixed reference"],
  ["dscr", "DSCR · fixed reference"],
  ["reserve", "Reserve balance · fixed reference"],
];
const isScheduleMetric = (value: string | null): value is keyof typeof facilityRows["Senior Debt A"] =>
  Boolean(value && scheduleLabels.some(([key]) => key === value));

export default function CreditDecisionWorkspace() {
  const project = readProjectContext();
  const params = new URLSearchParams(window.location.search);
  const [facility, setFacility] = useState<Facility>(() => {
    const requested = params.get("facility") as Facility | null;
    return requested && Object.prototype.hasOwnProperty.call(facilityRows, requested) ? requested : "Senior Debt A";
  });
  const [lenderCase, setLenderCase] = useState(() => params.get("creditCase") === "P90 downside" ? "P90 downside" : "P50 base");
  const [basis, setBasis] = useState<Basis>(() => params.get("creditBasis") === "model" ? "model" : "annual");
  const [selectedMetric, setSelectedMetric] = useState<keyof typeof facilityRows["Senior Debt A"]>(() =>
    isScheduleMetric(params.get("creditMetric")) ? params.get("creditMetric") as keyof typeof facilityRows["Senior Debt A"] : "dscr");
  const [selectedPeriod, setSelectedPeriod] = useState(() => params.get("creditPeriod") || "");
  const periods = basis === "annual" ? annualPeriods : modelPeriods;
  const activePeriod = periods.includes(selectedPeriod) ? selectedPeriod : periods[0];
  const periodIndex = Math.max(0, periods.indexOf(activePeriod));
  const selectedRows = facilityRows[facility];
  const selectedValue = selectedRows[selectedMetric][periodIndex] ?? "—";
  const hasSelectedValue = !["", "—", "–", "Not linked", "Not assessed", "Unavailable"].includes(selectedValue);
  const scenarioId = new URLSearchParams(window.location.search).get("scenario") || "base";
  function updateContextParam(key: string, value: string) {
    const params = new URLSearchParams(window.location.search);
    params.set(key, value);
    window.history.replaceState(null, "", `${window.location.pathname}?${params.toString()}${window.location.hash}`);
  }
  function chooseMetric(metric: keyof typeof facilityRows["Senior Debt A"], period = activePeriod) {
    setSelectedMetric(metric);
    setSelectedPeriod(period);
    updateContextParam("creditMetric", metric);
    updateContextParam("creditPeriod", period);
  }
  useEffect(() => {
    if (!periods.includes(selectedPeriod)) {
      setSelectedPeriod(periods[0]);
      updateContextParam("creditPeriod", periods[0]);
    }
  }, [periods, selectedPeriod]);

  return <div className="fm-wf fm-credit-workspace" aria-label="Synthetic lender credit review">
    <div className="fm-wf-notice" role="note"><strong>SYNTHETIC CREDIT REVIEW · NOT AN APPROVAL</strong><span>Fixed illustrative evidence only. No debt sizing, covenant test, bankability conclusion or financial calculation is performed.</span></div>
    <div className="fm-wf-toolbar">
      <div><strong>Lender review & bankability</strong><div className="fm-wf-muted">Read-only synthetic credit evidence · DEMO-FIXED-018</div></div>
      <Status tone="amber">CREDIT DECISION · NOT ASSESSED</Status>
    </div>
    <div className="fm-wf-controls">
      <label className="fm-wf-field">Lender case <span>Fixed comparison context</span><select aria-label="Lender case" value={lenderCase} onChange={event => { setLenderCase(event.target.value); updateContextParam("creditCase", event.target.value); }}><option>P50 base</option><option>P90 downside</option></select></label>
      <label className="fm-wf-field">Facility <span>Fixed sample schedule</span><select aria-label="Credit facility" value={facility} onChange={event => { const value = event.target.value as Facility; setFacility(value); updateContextParam("facility", value); }}>{Object.keys(facilityRows).map(item => <option key={item}>{item}</option>)}</select></label>
      <label className="fm-wf-field">Period basis <span>Display-only choice</span><select aria-label="Credit period basis" value={basis} onChange={event => { const value = event.target.value as Basis; setBasis(value); updateContextParam("creditBasis", value); }}><option value="annual">Annual</option><option value="model">Model-period snapshots</option></select></label>
      <label className="fm-wf-field">Reporting period <span>Fixed sample period</span><select aria-label="Credit reporting period" value={activePeriod} onChange={event => { setSelectedPeriod(event.target.value); updateContextParam("creditPeriod", event.target.value); }}>{periods.map(period => <option key={period}>{period}</option>)}</select></label>
    </div>
    <div className="fm-wf-summary fm-credit-summary">
      <div><span>DSCR-constrained sizing</span><strong>NOT EVALUATED</strong><small>No sizing solver or binding constraint result.</small></div>
      <div><span>Gearing-constrained sizing</span><strong>UNAVAILABLE</strong><small>No gearing calculation performed.</small></div>
      <div><span>Senior A/B debt reference</span><strong>€67.0m · fixed summary</strong><small>Authored display only; not a facility sum.</small></div>
      <div><span>Debt / total uses reference</span><strong>63.9% · fixed summary</strong><small>Not recalculated from commitments.</small></div>
      <div><span>DSRA evidence</span><strong>€2.1m · fixed example</strong><small>Not linked to facility or period balances.</small></div>
      <div><span>DSRF evidence</span><strong>Not assessed</strong><small>Availability and requirements not tested.</small></div>
      <div><span>Cash sweep / distributions</span><strong>NOT EVALUATED</strong><small>No restriction or covenant conclusion.</small></div>
      <div><span>Selected case</span><strong>{lenderCase}</strong><small>Switching case changes context only.</small></div>
    </div>
    <section className="fm-wf-section" aria-label="Lender review matrix">
      <div className="fm-wf-editor-head"><div><h3>Credit observations</h3><p>Thresholds are illustrative review prompts, not compliance tests.</p></div><Status tone="gray">NO COVENANT PASS CLAIMS</Status></div>
      <div className="fm-wf-scroll">
        <table className="fm-table fm-wf-table fm-credit-review">
          <caption>Fixed synthetic lender-review matrix · selected context: {lenderCase}</caption>
          <thead><tr>{["Metric", "Base case", "Downside", "P90 case", "Threshold", "Observation", "Evidence"].map(label => <th scope="col" key={label}>{label}</th>)}</tr></thead>
          <tbody>{reviewRows.map(row => <tr key={row[0]}><th scope="row">{row[0]}</th>{row.slice(1).map((value, index) => <td key={index}>{value}</td>)}</tr>)}</tbody>
        </table>
      </div>
    </section>
    <section className="fm-wf-section" aria-label={`${facility} fixed credit schedule`}>
      <div className="fm-wf-editor-head"><div><h3>Period-level credit workspace</h3><p>{facility} · {basis === "annual" ? "annual example array" : "model-period snapshot array"} · no relationship to edited facility assumptions</p></div><Status tone="gray">STATIC EXAMPLE · NOT RECONCILED</Status></div>
      <div className="fm-wf-scroll" role="region" aria-label="Credit period schedule, horizontally scrollable" tabIndex={0}>
        <table className="fm-table fm-wf-table fm-wf-period-table">
          <thead><tr><th scope="col">Metric · €m unless stated</th>{periods.map(period => <th scope="col" key={period}>{period}</th>)}</tr></thead>
          <tbody>{scheduleLabels.map(([key, label]) => <tr key={key} className={selectedMetric === key ? "fm-wf-row-active" : undefined}>
            <th scope="row"><button id={`credit-metric-${key}`} className="fm-credit-metric-button" type="button" aria-pressed={selectedMetric === key} onClick={() => chooseMetric(key)}>{label}</button></th>
            {selectedRows[key].map((value, index) => <td className="fm-mono" key={`${key}-${index}`}>
              <button className="fm-credit-cell-button" type="button" data-testid={`credit-cell-${key}-${index}`} aria-pressed={selectedMetric === key && activePeriod === periods[index]} aria-label={`Select ${label} for ${periods[index]}: ${value}`}
                onClick={() => chooseMetric(key, periods[index])}>{value}</button>
            </td>)}
          </tr>)}</tbody>
        </table>
      </div>
      <section className="fm-credit-evidence" data-testid="credit-evidence-panel" aria-live="polite" aria-label="Selected synthetic credit observation">
        <div className="fm-wf-editor-head"><div><h3>Selected evidence · {selectedMetric === "dscr" ? "DSCR" : scheduleLabels.find(([key]) => key === selectedMetric)?.[1]}</h3><p>{project.name} · scenario {scenarioId} · {facility} · {activePeriod}</p></div><Status tone="amber">{hasSelectedValue ? selectedMetric === "dscr" ? "FIXED VALUE · NOT A COVENANT RESULT" : "FIXED SYNTHETIC OBSERVATION" : "UNAVAILABLE / NOT EVALUATED"}</Status></div>
        <div className="fm-credit-evidence-value"><span>{selectedMetric === "dscr" ? "Displayed reference value" : scheduleLabels.find(([key]) => key === selectedMetric)?.[1]}</span><strong>{hasSelectedValue ? selectedValue : "Unavailable"}</strong></div>
        <dl className="fm-credit-evidence-meta">
          <div><dt>Fixed demo Run ID</dt><dd>DEMO-FIXED-018</dd></div>
          <div><dt>Evidence state</dt><dd>{hasSelectedValue ? "Authored sample value · no covenant or reconciliation test" : "No value supplied for this facility / period"}</dd></div>
          <div><dt>Financial integrity</dt><dd>NOT EVALUATED · no verified calculation lineage</dd></div>
        </dl>
        <p>Selections identify a displayed row and period only. They do not establish a mathematical dependency, lender conclusion, or relationship to edited financing assumptions.</p>
        <div className="fm-credit-evidence-links">
          <a href={workbookHref("senior-debt")}>Open facility assumptions · navigation only →</a>
          <a href={workbookHref("debt")}>Open fixed Statements &amp; Debt example →</a>
        </div>
      </section>
      <div className="fm-wf-note">Facility and period selectors choose authored fixed examples; they do not size, sculpt, aggregate, reconcile or recalculate debt. No lender approval is implied.</div>
    </section>
  </div>;
}
