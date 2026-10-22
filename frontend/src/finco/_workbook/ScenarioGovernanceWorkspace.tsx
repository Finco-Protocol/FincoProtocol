import React, { useEffect, useState } from "react";
import { fincoBasePath, Status } from "../_shared/FincoShell";
import { useDemoSessionState } from "../_shared/demoSession";

type ScenarioId = "base" | "downside" | "upside";
type Scenario = { id: ScenarioId; name: string; powerDelta: string; yieldCase: string; seniorMargin: string; dscr: string; state: string };
type ScenarioMap = Record<ScenarioId, Scenario>;
const initialScenarios: ScenarioMap = {
  base: { id: "base", name: "Base case", powerDelta: "0", yieldCase: "P50", seniorMargin: "2.35", dscr: "1.25", state: "Illustrative reference" },
  downside: { id: "downside", name: "Downside", powerDelta: "-12", yieldCase: "P90", seniorMargin: "2.85", dscr: "1.35", state: "Illustrative stress inputs" },
  upside: { id: "upside", name: "Upside", powerDelta: "8", yieldCase: "P50", seniorMargin: "2.15", dscr: "1.20", state: "Illustrative alternative inputs" },
};
const scenarioIds: ScenarioId[] = ["base", "downside", "upside"];

function resultHref(hash: "scenarios" | "results", scenario: ScenarioId) {
  const params = new URLSearchParams(window.location.search);
  params.delete("sheet");
  params.delete("statement");
  params.set("scenario", scenario);
  return `${fincoBasePath()}ResultsAnalysis?${params.toString()}#${hash}`;
}

export default function ScenarioGovernanceWorkspace({ sheet, onDraftDirty }: { sheet: string; onDraftDirty: (id: string, dirty: boolean) => void }) {
  const [drafts, setDrafts] = useDemoSessionState<ScenarioMap>("scenario-drafts", initialScenarios);
  const [saved, setSaved] = useDemoSessionState<ScenarioMap>("scenario-saved", initialScenarios);
  const [selected, setSelected] = useState<ScenarioId>(() => {
    const requested = new URLSearchParams(window.location.search).get("scenario") as ScenarioId | null;
    return requested && scenarioIds.includes(requested) ? requested : "base";
  });
  const [notice, setNotice] = useState("");
  const current = drafts[selected];
  const dirty = JSON.stringify(current) !== JSON.stringify(saved[selected]);
  const anyDirty = scenarioIds.some(id => JSON.stringify(drafts[id]) !== JSON.stringify(saved[id]));
  useEffect(() => { onDraftDirty("scenarios", anyDirty); }, [anyDirty, onDraftDirty]);
  function update<K extends keyof Scenario>(key: K, value: Scenario[K]) {
    setDrafts(old => ({ ...old, [selected]: { ...old[selected], [key]: value } }));
    setNotice("");
  }
  function selectScenario(id: ScenarioId) {
    setSelected(id);
    setNotice("");
    const params = new URLSearchParams(window.location.search);
    params.set("scenario", id);
    window.history.replaceState(null, "", `${window.location.pathname}?${params.toString()}${window.location.hash}`);
  }
  function save() {
    const numeric = [Number(current.powerDelta), Number(current.seniorMargin), Number(current.dscr)];
    if (numeric.some(value => !Number.isFinite(value)) || Number(current.seniorMargin) < 0 || Number(current.dscr) <= 0) {
      setNotice("Scenario Save blocked by field validation. No scenario was acknowledged.");
      return;
    }
    setSaved(old => ({ ...old, [selected]: { ...current } }));
    setNotice(`${current.name} acknowledged locally. Fixed results were not recalculated or changed.`);
  }
  const scenarioView = sheet === "scenarios";
  const historyView = sheet === "history";
  const diagnosticsView = sheet === "diagnostics";
  if (!scenarioView && !historyView && !diagnosticsView) return null;
  return <div className="fm-wf" aria-label={scenarioView ? "Synthetic scenario editor" : historyView ? "Fixed run history" : "Model diagnostics and integrity"}>
    <div className="fm-wf-notice" role="note"><strong>SYNTHETIC DEMO · no engine connection</strong><span>Scenario drafts and run records are local illustrative UI only. They do not create or recalculate model outputs.</span></div>
    {scenarioView && <>
      <div className="fm-wf-toolbar"><strong>Scenario register</strong><span className="fm-wf-muted">Independent local assumption sets · fixed result identity DEMO-FIXED-018</span><Status tone="amber">OUTPUTS NOT SCENARIO-DRIVEN</Status></div>
      <div className="fm-wf-scroll"><table className="fm-table fm-wf-table"><thead><tr><th scope="col">Scenario</th><th scope="col">Power-price delta</th><th scope="col">Yield case</th><th scope="col">Senior margin</th><th scope="col">DSCR assumption</th><th scope="col">State</th></tr></thead><tbody>{scenarioIds.map(id => {
        const scenario = drafts[id];
        return <tr key={id} className={selected === id ? "fm-wf-row-active" : ""}>
          <th scope="row"><button type="button" className="fm-wf-row-button" aria-pressed={selected === id} onClick={() => selectScenario(id)}>{scenario.name}</button></th>
          <td>{scenario.powerDelta}%</td><td>{scenario.yieldCase}</td><td>{scenario.seniorMargin}%</td><td>{scenario.dscr}x</td><td>{saved[id].state}</td>
        </tr>;
      })}</tbody></table></div>
      <div className="fm-wf-editor-head"><div><h3>{current.name} assumptions</h3><p>Each scenario has independent local drafts. Inputs are labels/examples, not a model engine.</p></div><span className={dirty ? "fm-wf-dirty" : "fm-wf-muted"}>{dirty ? "WORKING COPY · UNSAVED" : "LOCAL SAVE · NOT RUN"}</span></div>
      <div className="fm-wf-grid fm-wf-fields">
        <label className="fm-wf-field">Scenario name <span>Local label</span><input aria-label="Scenario name" value={current.name} onChange={event => update("name",event.target.value)} /></label>
        <label className="fm-wf-field">Power-price delta <span>Synthetic assumption</span><div className="fm-wf-unit-input"><input aria-label="Scenario power price delta" value={current.powerDelta} onChange={event => update("powerDelta",event.target.value)} /><i>%</i></div></label>
        <label className="fm-wf-field">Yield case <span>View label only</span><select aria-label="Scenario yield case" value={current.yieldCase} onChange={event => update("yieldCase",event.target.value)}><option>P50</option><option>P90</option></select></label>
        <label className="fm-wf-field">Senior margin assumption <span>Not a lender quote</span><div className="fm-wf-unit-input"><input aria-label="Scenario senior margin" value={current.seniorMargin} onChange={event => update("seniorMargin",event.target.value)} /><i>%</i></div></label>
        <label className="fm-wf-field">Minimum DSCR assumption <span>Not tested</span><div className="fm-wf-unit-input"><input aria-label="Scenario minimum DSCR" value={current.dscr} onChange={event => update("dscr",event.target.value)} /><i>x</i></div></label>
        <div className="fm-wf-field"><span>Scenario state</span><strong className="fm-wf-fixed-value">{current.state}</strong></div>
      </div>
      <div className="fm-wf-actions"><span className="fm-wf-muted">Local scenario Save only · no Run</span><button type="button" className="fm-btn fm-btn-primary" onClick={save}>Save {current.name} demo</button></div>
      {notice && <div className="fm-info-note" role="status">{notice}</div>}
      <div className="fm-wf-section">
        <div className="fm-wf-editor-head"><div><h3>Comparison entry points</h3><p>Results remain the fixed synthetic snapshot for every selected scenario.</p></div><Status tone="gray">NO SCENARIO CALCULATION</Status></div>
        <div className="fm-wf-grid fm-wf-summary">
          {scenarioIds.map(id => <div key={id}><span>{drafts[id].name}</span><strong>Inputs: {drafts[id].yieldCase} · {drafts[id].powerDelta}% power-price reference</strong><small>Results state: fixed demo output, not updated by these inputs.</small><a href={resultHref("scenarios",id)}>Open fixed comparison context →</a></div>)}
        </div>
        <div className="fm-wf-note">No scenario probabilities, volume allocation, debt sizing, sensitivities or IRR/NPV/DSCR outputs are calculated here.</div>
      </div>
    </>}
    {historyView && <section className="fm-wf-section" aria-label="Fixed run history register">
      <div className="fm-wf-editor-head"><div><h3>Run History · fixed illustrative records</h3><p>No new history records are created by Save or Run in this prototype.</p></div><Status tone="gray">RUN ENGINE NOT CONNECTED</Status></div>
      <div className="fm-wf-scroll"><table className="fm-table fm-wf-table"><thead><tr><th scope="col">Run ID</th><th scope="col">Project snapshot</th><th scope="col">Scenario</th><th scope="col">Model / engine version</th><th scope="col">Freshness</th><th scope="col">Integrity</th><th scope="col">Status</th><th scope="col">View</th></tr></thead><tbody>
        <tr><th scope="row">DEMO-FIXED-018</th><td>Adriatic Solar I · synthetic</td><td>Base case · fixed</td><td>Not connected</td><td>Fixed snapshot</td><td>Not evaluated</td><td>Illustrative only</td><td><a href={resultHref("results","base")}>Open results →</a></td></tr>
        <tr><th scope="row">DEMO-FIXED-017</th><td>Adriatic Solar I · synthetic</td><td>Downside · fixed</td><td>Not connected</td><td>Fixed snapshot</td><td>Not evaluated</td><td>Illustrative only</td><td><a href={resultHref("results","downside")}>Open results →</a></td></tr>
        <tr><th scope="row">DEMO-FIXED-014</th><td>Adriatic Solar I · synthetic</td><td>P90 · fixed</td><td>Not connected</td><td>Fixed snapshot</td><td>Not evaluated</td><td>Illustrative only</td><td><a href={resultHref("results","downside")}>Open P90 context →</a></td></tr>
      </tbody></table></div>
      <div className="fm-wf-note"><strong>Run identity:</strong> these three records are authored demo rows, not executions. No timestamp, input hash, engine version, audit event or persisted run is claimed.</div>
      <a className="fm-btn" href={resultHref("results",selected)}>Open fixed Results snapshot →</a>
    </section>}
    {diagnosticsView && <section className="fm-wf-section" aria-label="Model diagnostics">
      <div className="fm-wf-editor-head"><div><h3>Model checks & trust state</h3><p>Input validation, financial integrity, freshness and provenance are distinct concepts.</p></div><Status tone="amber">NOT A MODEL AUDIT</Status></div>
      <div className="fm-wf-scroll"><table className="fm-table fm-wf-table fm-diagnostics-table">
        <thead><tr><th scope="col">Diagnostic group</th><th scope="col">Current state</th><th scope="col">Evidence / limit</th><th scope="col">Status</th></tr></thead>
        <tbody>
          <tr><th scope="row">Input validation</th><td>Basic format and range checks</td><td>Edited demo fields only; no financial rule engine.</td><td>DEMO CHECK ONLY</td></tr>
          <tr><th scope="row">Construction funding consistency</th><td>NOT EVALUATED</td><td>Sources, uses and CAPEX drafts are not reconciled.</td><td>NOT EVALUATED</td></tr>
          <tr><th scope="row">Sources & Uses reconciliation</th><td>NOT EVALUATED</td><td>Fixed €104.8m snapshot is not linked to facility or cost edits.</td><td>NOT EVALUATED</td></tr>
          <tr><th scope="row">Debt maturity / DSCR evidence</th><td>NOT EVALUATED</td><td>No maturity, DSCR, covenant or bankability test.</td><td>NOT EVALUATED</td></tr>
          <tr><th scope="row">Financial statement integrity</th><td>NOT EVALUATED</td><td>No cross-statement reconciliation or balance-sheet check.</td><td>NOT EVALUATED</td></tr>
          <tr><th scope="row">Scenario assumptions</th><td>LOCAL DRAFTS</td><td>Three local assumptions; no execution or output linkage.</td><td>NOT RUN</td></tr>
          <tr><th scope="row">Run provenance / freshness</th><td>NOT CONNECTED</td><td>No engine version, input hash, audit event or persisted output.</td><td>UNKNOWN</td></tr>
          <tr><th scope="row">Numerical validation availability</th><td>UNAVAILABLE</td><td>No numeric engine or source calculation graph exists here.</td><td>UNAVAILABLE</td></tr>
        </tbody>
      </table></div>
      <div className="fm-wf-note">Do not interpret any green/amber UI state as an engineering, financial, tax, credit or investment approval.</div>
    </section>}
  </div>;
}
