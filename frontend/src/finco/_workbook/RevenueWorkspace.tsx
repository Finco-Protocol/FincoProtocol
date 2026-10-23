import React, { useEffect, useMemo, useState } from "react";
import { Field, readProjectContext, Status } from "../_shared/FincoShell";
import { useDemoSessionState } from "../_shared/demoSession";
import SourceAuthorityDrawer from "../_shared/SourceAuthorityDrawer";
import { workbookHref } from "./catalog";

type ContractId = "PPA-A" | "PPA-B" | "PPA-C";
type ContractType = "Fixed" | "Indexed" | "Scheduled";
type Step = { year: string; tariff: string };
type Contract = {
  id: ContractId;
  counterparty: string;
  type: ContractType;
  indexMode: string;
  start: string;
  expiry: string;
  allocation: string;
  tariff: string;
  indexation: string;
  indexStart: string;
  availabilityNote: string;
  steps: Step[];
};
type ContractMap = Record<ContractId, Contract>;

const initialContracts: ContractMap = {
  "PPA-A": {
    id: "PPA-A", counterparty: "Adriatic Offtaker Demo", type: "Fixed", indexMode: "CPI",
    start: "2027-07-01", expiry: "2045-06-30", allocation: "55", tariff: "63.50",
    indexation: "0", indexStart: "2028-01-01", availabilityNote: "Synthetic baseload example; no hourly shaping.",
    steps: [{ year: "2033", tariff: "68.00" }, { year: "2039", tariff: "72.00" }],
  },
  "PPA-B": {
    id: "PPA-B", counterparty: "Regional Utility Demo", type: "Indexed", indexMode: "CPI",
    start: "2027-07-01", expiry: "2039-06-30", allocation: "27", tariff: "58.00",
    indexation: "1.75", indexStart: "2028-01-01", availabilityNote: "Illustrative indexed tranche; no settlement profile.",
    steps: [{ year: "2033", tariff: "61.00" }, { year: "2039", tariff: "64.00" }],
  },
  "PPA-C": {
    id: "PPA-C", counterparty: "Industrial Buyer Demo", type: "Scheduled", indexMode: "CPI",
    start: "2027-07-01", expiry: "2037-06-30", allocation: "15", tariff: "61.00",
    indexation: "0", indexStart: "2028-01-01", availabilityNote: "Two scheduled price markers; no automatic price curve.",
    steps: [{ year: "2031", tariff: "65.00" }, { year: "2035", tariff: "69.00" }],
  },
};
const contractIds: ContractId[] = ["PPA-A", "PPA-B", "PPA-C"];
const validDate = (value: string) => {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const date = new Date(`${value}T00:00:00Z`);
  return Number.isFinite(date.getTime()) && date.toISOString().slice(0, 10) === value;
};

export default function RevenueWorkspace({ onDraftDirty, onSelectContract }: { onDraftDirty: (id: string, dirty: boolean) => void; onSelectContract: (id: ContractId) => void }) {
  const project = readProjectContext();
  const scenarioId = new URLSearchParams(window.location.search).get("scenario") || "base";
  const [drafts, setDrafts] = useDemoSessionState<ContractMap>("ppa-contract-drafts", initialContracts);
  const [saved, setSaved] = useDemoSessionState<ContractMap>("ppa-contract-saved", initialContracts);
  const [acknowledgedContracts, setAcknowledgedContracts] = useDemoSessionState<Record<ContractId, boolean>>("ppa-save-acknowledgements", {
    "PPA-A": false, "PPA-B": false, "PPA-C": false,
  });
  const [active, setActive] = useState<ContractId>(() => {
    const requested = new URLSearchParams(window.location.search).get("contract") as ContractId | null;
    return requested && contractIds.includes(requested) ? requested : "PPA-A";
  });
  const [notice, setNotice] = useState("");
  const current = drafts[active];
  const currentSaved = saved[active];
  const dirty = contractIds.some(id => JSON.stringify(drafts[id]) !== JSON.stringify(saved[id]));
  const selectedDirty = JSON.stringify(current) !== JSON.stringify(currentSaved);
  useEffect(() => { onDraftDirty("revenue", dirty); }, [dirty, onDraftDirty]);
  const errors = useMemo(() => {
    const result: Partial<Record<keyof Contract, string>> = {};
    if (!validDate(current.start) || !validDate(current.expiry) || current.expiry <= current.start) result.expiry = "Use valid dates; expiry must follow contract start.";
    const allocation = Number(current.allocation);
    if (!Number.isFinite(allocation) || allocation < 0 || allocation > 100) result.allocation = "Allocation must be between 0% and 100%.";
    const tariff = Number(current.tariff);
    if (!Number.isFinite(tariff) || tariff < 0) result.tariff = "Use a nonnegative tariff.";
    if (current.type === "Indexed") {
      const rate = Number(current.indexation);
      if (!Number.isFinite(rate) || rate < -10 || rate > 20) result.indexation = "Illustrative indexation range is −10% to 20%.";
      if (!validDate(current.indexStart)) result.indexStart = "Enter a valid indexation start date.";
    }
    if (current.type === "Scheduled" && current.steps.some(step => !/^\d{4}$/.test(step.year) || !Number.isFinite(Number(step.tariff)) || Number(step.tariff) < 0)) result.steps = "Scheduled year and tariff cells must contain valid values.";
    return result;
  }, [current]);
  function update<K extends keyof Contract>(key: K, value: Contract[K]) {
    setDrafts(old => ({ ...old, [active]: { ...old[active], [key]: value } }));
    setAcknowledgedContracts(old => ({ ...old, [active]: false }));
    setNotice("");
  }
  function selectContract(id: ContractId) {
    setActive(id);
    setNotice("");
    const params = new URLSearchParams(window.location.search);
    params.set("contract", id);
    window.history.replaceState(null, "", `${window.location.pathname}?${params.toString()}${window.location.hash}`);
    onSelectContract(id);
  }
  function updateStep(index: number, key: keyof Step, value: string) {
    const steps = current.steps.map((step, i) => i === index ? { ...step, [key]: value } : step);
    update("steps", steps);
  }
  function save() {
    if (Object.keys(errors).length) {
      setNotice("Save unavailable. Correct the marked fields; no values were acknowledged.");
      return;
    }
    setSaved(old => ({ ...old, [active]: { ...current, steps: current.steps.map(step => ({ ...step })) } }));
    setAcknowledgedContracts(old => ({ ...old, [active]: true }));
    setNotice(`${active} acknowledged in this page only. No model run, revenue allocation or result update occurred.`);
  }
  return <div className="fm-wf" aria-label="Synthetic multi-contract PPA editor">
    <div className="fm-wf-notice" role="note"><strong>SYNTHETIC DEMO · no revenue calculation</strong><span>Each record has its own browser-tab session draft; same-tab reload preserves it, while Reset or closing the tab clears it. Statements do not update.</span></div>
    <div className="fm-wf-toolbar">
      <strong>Contract register</strong>
      <span className="fm-wf-muted">PPA-A fixed · PPA-B indexed · PPA-C scheduled · unsigned examples</span>
      <Status tone="gray">Merchant residual not allocated</Status>
    </div>
    <div className="fm-wf-scroll">
      <table className="fm-table fm-wf-table">
        <thead><tr><th scope="col">Contract</th><th scope="col">Type</th><th scope="col">Start</th><th scope="col">Expiry</th><th scope="col">Allocation</th><th scope="col">Tariff</th><th scope="col">Index / schedule</th><th scope="col">Status</th></tr></thead>
        <tbody>{contractIds.map(id => {
          const contract = drafts[id];
          return <tr key={id} className={active === id ? "fm-wf-row-active" : ""}>
            <th scope="row"><button type="button" className="fm-wf-row-button" aria-pressed={active === id} onClick={() => selectContract(id)}>{id}</button></th>
            <td>{contract.type}</td><td className="fm-mono">{contract.start}</td><td className="fm-mono">{contract.expiry}</td>
            <td className="fm-mono">{contract.allocation}%</td><td className="fm-mono">€{contract.tariff}/MWh</td>
            <td>{contract.type === "Indexed" ? `${contract.indexation}% example` : contract.type === "Scheduled" ? "2 fixed markers" : "Fixed price"}</td>
            <td>Demo · not executed</td>
          </tr>;
        })}</tbody>
      </table>
    </div>
    <div className="fm-wf-grid fm-wf-summary">
      <div><span>Contract share fields</span><strong>Per-record examples</strong><small>No combined allocation or merchant residual is calculated.</small></div>
      <div><span>Merchant residual</span><strong>3% · fixed reference</strong><small>Not linked to the editable contract shares.</small></div>
      <div><span>P50 / P90 yield</span><strong>1,620 / 1,515 kWh/kWp</strong><small>Fixed illustrative assumptions; no yield calculation.</small></div>
      <div><span>Availability / degradation</span><strong>98.0% / 0.45% p.a.</strong><small>Fixed example values; no production reconciliation.</small></div>
    </div>
    <div className="fm-wf-editor-head">
      <div><h3>{active} contract editor</h3><p>Selected contract state is independent of the other two demo records.</p></div>
      <span className={selectedDirty ? "fm-wf-dirty" : "fm-wf-muted"}>{selectedDirty ? "WORKING COPY · UNSAVED" : "LOCAL SAVE · NOT RUN"}</span>
    </div>
    <div className="fm-wf-grid fm-wf-fields">
      <Field label="Counterparty (synthetic)" value={current.counterparty} onChange={value => update("counterparty", value)} />
      <label className="fm-wf-field">Contract type <span>Editable demo</span><select aria-label={`${active} contract type`} value={current.type} onChange={event => update("type", event.target.value as ContractType)}><option>Fixed</option><option>Indexed</option><option>Scheduled</option></select></label>
      <Field label="Contract start" value={current.start} type="date" error={validDate(current.start) ? undefined : "Enter a valid contract start date."} onChange={value => update("start", value)} />
      <Field label="Contract expiry" value={current.expiry} type="date" error={errors.expiry} onChange={value => update("expiry", value)} />
      <Field label="Allocated production share" value={current.allocation} unit="%" error={errors.allocation} hint="Per-contract example only; no allocation solver." onChange={value => update("allocation", value)} />
      <Field label="Base tariff" value={current.tariff} unit="€/MWh" error={errors.tariff} onChange={value => update("tariff", value)} />
      {current.type === "Indexed" && <>
        <label className="fm-wf-field">Indexation mode <span>Example</span><select aria-label="Indexation mode" value={current.indexMode} onChange={event => update("indexMode",event.target.value)}><option>CPI</option><option>EUR HICP</option><option>Fixed percentage</option></select></label>
        <Field label="Annual indexation" value={current.indexation} unit="%" error={errors.indexation} onChange={value => update("indexation", value)} />
        <Field label="Indexation start date" value={current.indexStart} type="date" error={errors.indexStart} onChange={value => update("indexStart", value)} />
      </>}
      {current.type === "Scheduled" && <div className="fm-wf-schedule">
        <strong>Scheduled tariff markers · design example only</strong>
        <div className="fm-wf-scroll"><table className="fm-table fm-wf-table"><thead><tr><th scope="col">Marker</th><th scope="col">Year</th><th scope="col">Tariff · €/MWh</th></tr></thead><tbody>{current.steps.map((step, index) => <tr key={index}><th scope="row">Step {index + 1}</th><td><input aria-label={`Scheduled tariff step ${index + 1} year`} value={step.year} onChange={event => updateStep(index, "year", event.target.value)} /></td><td><input aria-label={`Scheduled tariff step ${index + 1} tariff`} value={step.tariff} onChange={event => updateStep(index, "tariff", event.target.value)} /></td></tr>)}</tbody></table></div>
        {errors.steps && <span className="fm-invalid-note" role="alert">{errors.steps}</span>}
      </div>}
      <Field label="Contract status" value="Illustrative · unsigned" calculated />
      <Field label="Availability notes" value={current.availabilityNote} onChange={value => update("availabilityNote", value)} />
    </div>
    <SourceAuthorityDrawer
      project={project}
      scenarioId={scenarioId}
      selection={`${active} · ${current.type} contract`}
      valueLabel={`${current.tariff} €/MWh · ${current.allocation}% allocation label`}
      state={project.mode === "reference" ? "reference" : selectedDirty ? "draft" : acknowledgedContracts[active] ? "saved" : "draft"}
      sourceLabel="Synthetic PPA register example"
      relatedHref={workbookHref("pl")}
      relatedLabel="Open fixed P&L statement example →"
      note="Contract and tariff values are local illustrations. The statement link is contextual navigation only; no revenue allocation, price curve, or calculation lineage is asserted."
    />
    <div className="fm-wf-actions">
      <span className="fm-wf-muted">Save affects {active} only · no backend · no Run</span>
      <button type="button" className="fm-btn fm-btn-primary" disabled={Boolean(Object.keys(errors).length)} onClick={save}>Save {active} demo</button>
    </div>
    {notice && <div className="fm-info-note" role="status">{notice}</div>}
    <div className="fm-wf-note"><strong>Workflow context:</strong> selected contract ID is carried in the local navigation query only. <a href={workbookHref("pl")}>Open fixed P&amp;L statement example →</a> Contract edits do not flow into that statement.</div>
  </div>;
}
