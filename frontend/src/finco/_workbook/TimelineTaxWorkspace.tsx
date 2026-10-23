import React, { useEffect, useMemo, useState } from "react";
import { Field, Status } from "../_shared/FincoShell";
import { persistCurrentDemoSessionBatch, useDemoSessionState } from "../_shared/demoSession";

type Timeline = {
  financialClose: string; constructionStart: string; cod: string; operationStart: string;
  ppaExpiry: string; debtMaturity: string; horizon: string;
};
const initialTimeline: Timeline = {
  financialClose: "2025-09-15", constructionStart: "2025-10-01", cod: "2027-07-01",
  operationStart: "2027-07-01", ppaExpiry: "2045-06-30", debtMaturity: "2045-06-30", horizon: "2057-06-30",
};
type TaxInputs = {
  corporateRate: string; taxBasis: string; lossCarryForward: string; lossExpiry: string;
  depreciation: string; assetLife: string; vatMode: string; vatRate: string;
  withholding: string; paymentTiming: string;
};
const initialTax: TaxInputs = {
  corporateRate: "18", taxBasis: "Cash tax · preview only", lossCarryForward: "0.6",
  lossExpiry: "2030", depreciation: "Straight-line · preview only", assetLife: "25",
  vatMode: "Recoverable · not modelled", vatRate: "25", withholding: "0", paymentTiming: "Quarterly · view label",
};
const validDate = (value: string) => {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const date = new Date(`${value}T00:00:00Z`);
  return Number.isFinite(date.getTime()) && date.toISOString().slice(0, 10) === value;
};

export default function TimelineTaxWorkspace({ onDraftDirty }: { onDraftDirty: (id: string, dirty: boolean) => void }) {
  const [timeline, setTimeline] = useDemoSessionState("timeline-draft", initialTimeline);
  const [savedTimeline, setSavedTimeline] = useDemoSessionState("timeline-saved", initialTimeline);
  const [tax, setTax] = useDemoSessionState("tax-draft", initialTax);
  const [savedTax, setSavedTax] = useDemoSessionState("tax-saved", initialTax);
  const [message, setMessage] = useState("");
  const [operatingView, setOperatingView] = useState("Quarterly · 3M");
  const timelineDirty = JSON.stringify(timeline) !== JSON.stringify(savedTimeline);
  const taxDirty = JSON.stringify(tax) !== JSON.stringify(savedTax);
  useEffect(() => { onDraftDirty("tax-timing", timelineDirty || taxDirty); }, [timelineDirty, taxDirty, onDraftDirty]);
  const timelineErrors = useMemo(() => {
    const labels = Object.entries(timeline) as [keyof Timeline, string][];
    const invalid = labels.filter(([, value]) => !validDate(value));
    const ordered = labels.map(([, value]) => value);
    const outOfOrder = ordered.some((value, index) => index > 0 && value < ordered[index - 1]);
    return invalid.length ? "Every milestone must be a valid date." : outOfOrder ? "Milestones must remain in chronological order." : "";
  }, [timeline]);
  const taxErrors = useMemo(() => {
    const errors: string[] = [];
    for (const [name, value] of [["Corporate tax", tax.corporateRate], ["VAT", tax.vatRate], ["Withholding", tax.withholding]] as const) {
      const number = Number(value);
      if (!Number.isFinite(number) || number < 0 || number > 100) errors.push(`${name} rate must be between 0% and 100%.`);
    }
    if (!Number.isInteger(Number(tax.assetLife)) || Number(tax.assetLife) < 1 || Number(tax.assetLife) > 100) errors.push("Asset life must be an integer from 1 to 100 years.");
    if (!/^\d{4}$/.test(tax.lossExpiry)) errors.push("Enter the loss-expiry calendar year.");
    return errors;
  }, [tax]);
  function updateTimeline(key: keyof Timeline, value: string) {
    setTimeline(old => ({ ...old, [key]: value })); setMessage("");
  }
  function updateTax(key: keyof TaxInputs, value: string) {
    setTax(old => ({ ...old, [key]: value })); setMessage("");
  }
  function saveTimeline() {
    if (timelineErrors) { setMessage("Timeline Save blocked. Correct the marked date sequence."); return; }
    if (!persistCurrentDemoSessionBatch([["timeline-saved", { ...timeline }]])) {
      setMessage("Save could not be confirmed because browser storage is unavailable. Timeline edits remain unsaved in this view.");
      return;
    }
    setSavedTimeline({ ...timeline }); setMessage("Timeline inputs acknowledged in this page only. No schedule or model Run was created.");
  }
  function saveTax() {
    if (taxErrors.length) { setMessage("Tax Save blocked. Correct the marked assumptions."); return; }
    if (!persistCurrentDemoSessionBatch([["tax-saved", { ...tax }]])) {
      setMessage("Save could not be confirmed because browser storage is unavailable. Tax edits remain unsaved in this view.");
      return;
    }
    setSavedTax({ ...tax }); setMessage("Tax assumptions acknowledged in this page only. No tax calculation or model Run was created.");
  }
  const timelineFields: [keyof Timeline, string][] = [
    ["financialClose", "Financial close"], ["constructionStart", "Construction start"],
    ["cod", "Commercial operation date (COD)"], ["operationStart", "Operating-period start"],
    ["ppaExpiry", "PPA expiry · reference"], ["debtMaturity", "Debt maturity · reference"],
    ["horizon", "Model horizon · reference"],
  ];
  return <div className="fm-wf" aria-label="Synthetic project timeline and tax workspace">
    <div className="fm-wf-notice" role="note"><strong>SYNTHETIC EXAMPLE · no timing or tax calculations</strong><span>Fields and view choices only. Dates, periods, tax and depreciation do not generate a schedule or cash flow.</span></div>
    <section className="fm-wf-section" aria-label="Project timeline">
      <div className="fm-wf-editor-head"><div><h3>Project & timing milestones</h3><p>Chronology is a basic input check; this is not a construction or operating model.</p></div><span className={timelineDirty ? "fm-wf-dirty" : "fm-wf-muted"}>{timelineDirty ? "WORKING COPY · UNSAVED" : "LOCAL SAVE · NOT RUN"}</span></div>
      <div className="fm-wf-grid fm-wf-fields">{timelineFields.map(([key,label])=><Field key={key} label={label} value={timeline[key]} type="date" error={!validDate(timeline[key]) ? "Enter a valid calendar date." : undefined} onChange={value => updateTimeline(key,value)} />)}</div>
      {timelineErrors && <div className="fm-wf-error-summary" role="alert">{timelineErrors}</div>}
      <div className="fm-wf-timeline" aria-label="Illustrative milestone sequence">
        {timelineFields.map(([key,label],index)=><div key={key} className="fm-wf-milestone"><span>{String(index + 1).padStart(2,"0")}</span><strong>{label}</strong><code>{timeline[key]}</code></div>)}
      </div>
      <div className="fm-wf-grid fm-wf-summary">
        <div><span>Construction periods</span><strong>Monthly · example view</strong><small>This display choice does not set a live model frequency.</small></div>
        <label className="fm-wf-field">Operation display <span>View-only design choice</span><select aria-label="Operation period display" value={operatingView} onChange={event => setOperatingView(event.target.value)}><option>Quarterly · 3M</option><option>Semiannual · 6M</option></select></label>
        <div><span>Model frequency</span><strong>Not available</strong><small>Changing this selector does not change displayed figures.</small></div>
      </div>
      <div className="fm-wf-actions"><span className="fm-wf-muted">Timeline Save only · no Run</span><button type="button" className="fm-btn fm-btn-primary" disabled={Boolean(timelineErrors)} onClick={saveTimeline}>Save timing demo</button></div>
    </section>
    <section className="fm-wf-section" aria-label="Tax assumptions and schedules">
      <div className="fm-wf-editor-head"><div><h3>Tax, depreciation & indirect tax</h3><p>Editable assumption examples with explicit non-computation states.</p></div><span className={taxDirty ? "fm-wf-dirty" : "fm-wf-muted"}>{taxDirty ? "WORKING COPY · UNSAVED" : "LOCAL SAVE · NOT RUN"}</span></div>
      <div className="fm-wf-grid fm-wf-fields">
        <Field label="Corporate income tax rate" value={tax.corporateRate} unit="%" onChange={value => updateTax("corporateRate", value)} error={taxErrors.find(error => error.startsWith("Corporate"))} />
        <label className="fm-wf-field">Tax basis <span>Preview only</span><select aria-label="Tax basis" value={tax.taxBasis} onChange={event => updateTax("taxBasis",event.target.value)}><option>Cash tax · preview only</option><option>Accrual tax · preview only</option></select></label>
        <Field label="Loss carryforward · reference" value={tax.lossCarryForward} unit="€m" onChange={value => updateTax("lossCarryForward",value)} />
        <Field label="Loss expiry year" value={tax.lossExpiry} onChange={value => updateTax("lossExpiry",value)} error={taxErrors.find(error => error.startsWith("Enter the loss"))} />
        <label className="fm-wf-field">Depreciation method <span>No depreciation schedule</span><select aria-label="Depreciation method" value={tax.depreciation} onChange={event => updateTax("depreciation",event.target.value)}><option>Straight-line · preview only</option><option>Declining balance · preview only</option><option>Tax pool · unavailable</option></select></label>
        <Field label="Illustrative asset life" value={tax.assetLife} unit="years" onChange={value => updateTax("assetLife",value)} error={taxErrors.find(error => error.startsWith("Asset life"))} />
        <label className="fm-wf-field">VAT recovery <span>Not calculated</span><select aria-label="VAT recovery" value={tax.vatMode} onChange={event => updateTax("vatMode",event.target.value)}><option>Recoverable · not modelled</option><option>Non-recoverable · not modelled</option><option>Partial · not modelled</option></select></label>
        <Field label="VAT rate · jurisdictional example" value={tax.vatRate} unit="%" onChange={value => updateTax("vatRate",value)} error={taxErrors.find(error => error.startsWith("VAT"))} />
        <Field label="Withholding tax assumption" value={tax.withholding} unit="%" onChange={value => updateTax("withholding",value)} error={taxErrors.find(error => error.startsWith("Withholding"))} />
        <label className="fm-wf-field">Payment timing label <span>Display only</span><select aria-label="Tax payment timing label" value={tax.paymentTiming} onChange={event => updateTax("paymentTiming",event.target.value)}><option>Quarterly · view label</option><option>Semiannual · view label</option><option>Annual · view label</option></select></label>
      </div>
      {taxErrors.length > 0 && <ul className="fm-wf-errors" role="alert">{taxErrors.map(error=><li key={error}>{error}</li>)}</ul>}
      <div className="fm-wf-grid fm-wf-summary">
        <div><span>Tax loss schedule</span><strong>NOT MODELED</strong><small>Carryforward input is illustrative only; no utilization logic.</small></div>
        <div><span>Depreciation tax shield</span><strong>NOT MODELED</strong><small>Method selector does not create a tax schedule.</small></div>
        <div><span>VAT / withholding cash timing</span><strong>NOT MODELED</strong><small>No recoverability, payment lag or cash-flow impact.</small></div>
      </div>
      <div className="fm-wf-actions"><span className="fm-wf-muted">Tax Save only · no Run</span><button type="button" className="fm-btn fm-btn-primary" disabled={Boolean(taxErrors.length)} onClick={saveTax}>Save tax demo</button></div>
    </section>
    {message && <div className="fm-info-note" role={message.includes("blocked") || message.includes("could not be confirmed") ? "alert" : "status"}>{message}</div>}
    <div className="fm-wf-note"><Status tone="amber">NOT A TAX OPINION</Status> The prototype does not implement jurisdiction rules, tax-loss utilization, VAT recovery, depreciation, withholding or payment schedules.</div>
  </div>;
}
