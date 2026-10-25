import React, { useEffect, useState } from "react";
import { fincoBasePath, Status } from "../_shared/FincoShell";
import { persistCurrentDemoSessionBatch, useDemoSessionState } from "../_shared/demoSession";
import { workbookHref } from "./catalog";

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

export default function ScenarioGovernanceWorkspace({ sheet, onDraftDirty, onScenarioChangeRequest, onContextChange }: {
  sheet: string;
  onDraftDirty: (id: string, dirty: boolean) => void;
  onScenarioChangeRequest?: (id: string, proceed: () => void) => void;
  onContextChange?: (key: string, value: string) => void;
}) {
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
  useEffect(() => {
    const syncFromHistory = () => {
      const requested = new URLSearchParams(window.location.search).get("scenario") as ScenarioId | null;
      if (requested && scenarioIds.includes(requested)) setSelected(requested);
    };
    window.addEventListener("popstate", syncFromHistory);
    return () => window.removeEventListener("popstate", syncFromHistory);
  }, []);
  function update<K extends keyof Scenario>(key: K, value: Scenario[K]) {
    setDrafts(old => ({ ...old, [selected]: { ...old[selected], [key]: value } }));
    setNotice("");
  }
  function selectScenario(id: ScenarioId) {
    if (id === selected) return;
    const proceed = () => {
      setSelected(id);
      setNotice("");
      const params = new URLSearchParams(window.location.search);
      params.set("scenario", id);
      window.history.pushState(null, "", `${window.location.pathname}?${params.toString()}${window.location.hash}`);
      onContextChange?.("scenario", id);
    };
    if (onScenarioChangeRequest) onScenarioChangeRequest(id, proceed);
    else proceed();
  }
  function save() {
    const numeric = [Number(current.powerDelta), Number(current.seniorMargin), Number(current.dscr)];
    if (numeric.some(value => !Number.isFinite(value)) || Number(current.seniorMargin) < 0 || Number(current.dscr) <= 0) {
      setNotice("Scenario Save blocked by field validation. No scenario was acknowledged.");
      return;
    }
    const nextSaved = { ...saved, [selected]: { ...current } };
    if (!persistCurrentDemoSessionBatch([["scenario-saved", nextSaved]])) {
      setNotice("Save could not be confirmed because browser storage is unavailable. Scenario edits remain unsaved in this view.");
      return;
    }
    setSaved(nextSaved);
    setNotice(`${current.name} acknowledged locally. Fixed results were not recalculated or changed.`);
  }
  const scenarioView = sheet === "scenarios";
  const historyView = sheet === "history";
  const diagnosticsView = sheet === "diagnostics";
  if (!scenarioView && !historyView && !diagnosticsView) return null;
  return <div className="fm-wf" aria-label={scenarioView ? "Synthetic scenario editor" : historyView ? "Run history examples" : "Findings preview"}>
    <div className="fm-wf-notice" role="note"><strong>ILLUSTRATIVE EXAMPLE · fixed figures</strong><span>Scenario and history pages show examples only. They do not calculate or update financial results.</span></div>
    {scenarioView && <>
      <div className="fm-wf-toolbar"><strong>Scenario register</strong><span className="fm-wf-muted">Separate preview assumptions · same fixed example results</span><Status tone="amber">RESULTS STAY THE SAME</Status></div>
      <div className="fm-wf-scroll"><table className="fm-table fm-wf-table"><thead><tr><th scope="col">Scenario ID</th><th scope="col">Scenario</th><th scope="col">Power-price delta</th><th scope="col">Yield case</th><th scope="col">Senior margin</th><th scope="col">DSCR assumption</th><th scope="col">State</th></tr></thead><tbody>{scenarioIds.map(id => {
        const scenario = drafts[id];
        return <tr key={id} className={selected === id ? "fm-wf-row-active" : ""}>
          <td className="fm-mono">{scenario.id}</td><th scope="row"><button type="button" className="fm-wf-row-button" aria-pressed={selected === id} onClick={() => selectScenario(id)}>{scenario.name}</button></th>
          <td>{scenario.powerDelta}%</td><td>{scenario.yieldCase}</td><td>{scenario.seniorMargin}%</td><td>{scenario.dscr}x</td><td>{saved[id].state}</td>
        </tr>;
      })}</tbody></table></div>
      <div className="fm-wf-editor-head"><div><h3>{current.name} assumptions</h3><p>Scenario reference: <code>{current.id}</code> · drafts are separate; these inputs do not change the fixed example results.</p></div><span className={dirty ? "fm-wf-dirty" : "fm-wf-muted"}>{dirty ? "Unsaved changes" : "Saved in preview · results unchanged"}</span></div>
      <div className="fm-wf-grid fm-wf-fields">
        <label className="fm-wf-field">Scenario name <span>Local label</span><input aria-label="Scenario name" value={current.name} onChange={event => update("name",event.target.value)} /></label>
        <label className="fm-wf-field">Power-price delta <span>Synthetic assumption</span><div className="fm-wf-unit-input"><input aria-label="Scenario power price delta" value={current.powerDelta} onChange={event => update("powerDelta",event.target.value)} /><i>%</i></div></label>
        <label className="fm-wf-field">Yield case <span>View label only</span><select aria-label="Scenario yield case" value={current.yieldCase} onChange={event => update("yieldCase",event.target.value)}><option>P50</option><option>P90</option></select></label>
        <label className="fm-wf-field">Senior margin assumption <span>Not a lender quote</span><div className="fm-wf-unit-input"><input aria-label="Scenario senior margin" value={current.seniorMargin} onChange={event => update("seniorMargin",event.target.value)} /><i>%</i></div></label>
        <label className="fm-wf-field">Minimum DSCR assumption <span>Not tested</span><div className="fm-wf-unit-input"><input aria-label="Scenario minimum DSCR" value={current.dscr} onChange={event => update("dscr",event.target.value)} /><i>x</i></div></label>
        <div className="fm-wf-field"><span>Scenario state</span><strong className="fm-wf-fixed-value">{current.state}</strong></div>
      </div>
      <div className="fm-wf-actions"><span className="fm-wf-muted">Saving keeps a preview draft; results stay unchanged.</span><button type="button" className="fm-btn fm-btn-primary" onClick={save}>Save {current.name} preview</button></div>
      {notice && <div className="fm-info-note" role={notice.includes("unavailable") || notice.includes("could not be confirmed") ? "alert" : "status"}>{notice}</div>}
      <div className="fm-wf-section">
        <div className="fm-wf-editor-head"><div><h3>Comparison entry points</h3><p>Results remain the same fixed synthetic example for every selected scenario.</p></div><Status tone="gray">SCENARIO RESULTS NOT CALCULATED</Status></div>
        <div className="fm-wf-grid fm-wf-summary">
          {scenarioIds.map(id => <div key={id}><span>{drafts[id].name}</span><strong>Inputs: {drafts[id].yieldCase} · {drafts[id].powerDelta}% power-price example</strong><small>Results are fixed examples and do not change with these inputs.</small><a href={resultHref("scenarios",id)}>Open fixed comparison example →</a></div>)}
        </div>
        <div className="fm-wf-note">No scenario probabilities, volume allocation, debt sizing, sensitivities or IRR/NPV/DSCR outputs are calculated here.</div>
      </div>
    </>}
    {historyView && <section className="fm-wf-section" aria-label="Fixed run history register">
      <div className="fm-wf-editor-head"><div><h3>Run history · example records</h3><p>Saving or opening a preview does not add a calculation record.</p></div><Status tone="gray">EXAMPLES ONLY</Status></div>
      <div className="fm-wf-scroll"><table className="fm-table fm-wf-table"><thead><tr><th scope="col">Example</th><th scope="col">Project</th><th scope="col">Scenario</th><th scope="col">Calculation details</th><th scope="col">Result status</th><th scope="col">Financial checks</th><th scope="col">Type</th><th scope="col">View</th></tr></thead><tbody>
        <tr><th scope="row">DEMO-FIXED-018</th><td>Adriatic Solar I · synthetic</td><td>Base case · fixed</td><td>Not included</td><td>Fixed example</td><td>Not checked</td><td>Illustrative only</td><td><a href={resultHref("results","base")}>Open results →</a></td></tr>
        <tr><th scope="row">DEMO-FIXED-017</th><td>Adriatic Solar I · synthetic</td><td>Downside · fixed</td><td>Not included</td><td>Fixed example</td><td>Not checked</td><td>Illustrative only</td><td><a href={resultHref("results","downside")}>Open results →</a></td></tr>
        <tr><th scope="row">DEMO-FIXED-014</th><td>Adriatic Solar I · synthetic</td><td>P90 · fixed</td><td>Not included</td><td>Fixed example</td><td>Not checked</td><td>Illustrative only</td><td><a href={resultHref("results","downside")}>Open P90 context →</a></td></tr>
      </tbody></table></div>
      <div className="fm-wf-note"><strong>Example records:</strong> these are fixed sample rows, not saved calculations. No date or input record is attached.</div>
      <a className="fm-btn" href={resultHref("results",selected)}>Open fixed Results example →</a>
    </section>}
    {diagnosticsView && <section className="fm-wf-section" aria-label="Findings preview">
      <div className="fm-wf-editor-head"><div><h3>Findings</h3><p>Detailed project and lender review is not part of this preview.</p></div><Status tone="gray">NOT AVAILABLE</Status></div>
      <div className="fm-wf-notice" role="note"><strong>No financial findings are provided here.</strong><span>Only basic input format checks are shown when you edit a field. No project-wide review or approval is performed.</span></div>
      <div className="fm-wf-actions"><a className="fm-btn" href={workbookHref("input-grid")}>Review inputs →</a></div>
    </section>}
  </div>;
}
