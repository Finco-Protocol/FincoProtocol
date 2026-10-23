import React, { useEffect, useMemo, useState } from "react";
import { Field, readProjectContext, Status } from "../_shared/FincoShell";
import { useDemoSessionState } from "../_shared/demoSession";
import SourceAuthorityDrawer from "../_shared/SourceAuthorityDrawer";
import { workbookHref } from "./catalog";

type FacilityId = "Senior Debt A" | "Senior Debt B" | "Junior / Mezzanine" | "Shareholder Loan (SHL)" | "Sponsor Equity";
type Facility = {
  id: FacilityId; instrument: string; commitment: string; currency: string;
  referenceRate: string; interestType: string; rate: string; maturity: string;
  grace: string; repayment: string; fee: string; pCase: string; dscr: string;
  cashSweep: string; pik: string; availability: string;
};
type FacilityMap = Record<FacilityId, Facility>;
const facilityIds: FacilityId[] = ["Senior Debt A", "Senior Debt B", "Junior / Mezzanine", "Shareholder Loan (SHL)", "Sponsor Equity"];
const initialFacilities: FacilityMap = {
  "Senior Debt A": { id: "Senior Debt A", instrument: "Senior secured", commitment: "42.0", currency: "EUR", referenceRate: "EURIBOR", interestType: "Floating", rate: "2.35", maturity: "2045-06-30", grace: "24", repayment: "Sculpted · preview only", fee: "1.25", pCase: "P50", dscr: "1.25", cashSweep: "Preview only", pik: "0", availability: "Illustrative · not credit approved" },
  "Senior Debt B": { id: "Senior Debt B", instrument: "Senior secured", commitment: "25.0", currency: "EUR", referenceRate: "EURIBOR", interestType: "Floating", rate: "2.65", maturity: "2043-06-30", grace: "18", repayment: "Amortising · preview only", fee: "1.00", pCase: "P90", dscr: "1.30", cashSweep: "Preview only", pik: "0", availability: "Illustrative · not credit approved" },
  "Junior / Mezzanine": { id: "Junior / Mezzanine", instrument: "Junior / mezzanine", commitment: "6.0", currency: "EUR", referenceRate: "Fixed", interestType: "Fixed", rate: "8.25", maturity: "2037-06-30", grace: "36", repayment: "Bullet · preview only", fee: "2.00", pCase: "P90", dscr: "1.10", cashSweep: "Unavailable", pik: "1.50", availability: "Optional synthetic example; not sized" },
  "Shareholder Loan (SHL)": { id: "Shareholder Loan (SHL)", instrument: "Shareholder loan", commitment: "4.0", currency: "EUR", referenceRate: "Fixed", interestType: "Fixed", rate: "3.00", maturity: "2045-06-30", grace: "60", repayment: "Bullet · preview only", fee: "0.00", pCase: "Not assessed", dscr: "Not assessed", cashSweep: "Unavailable", pik: "2.00", availability: "Synthetic example; subordination not modelled" },
  "Sponsor Equity": { id: "Sponsor Equity", instrument: "Ordinary shares", commitment: "31.8", currency: "EUR", referenceRate: "N/A", interestType: "N/A", rate: "0", maturity: "2045-06-30", grace: "0", repayment: "Residual · not calculated", fee: "0.00", pCase: "Not assessed", dscr: "Not assessed", cashSweep: "Unavailable", pik: "0", availability: "Illustrative sponsor contribution" },
};
const validDate = (value: string) => {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const parsed = new Date(`${value}T00:00:00Z`);
  return Number.isFinite(parsed.getTime()) && parsed.toISOString().slice(0, 10) === value;
};

export default function FinanceWorkspace({ sheet, onOpen, onDraftDirty, onSelectFacility }: { sheet: string; onOpen: (id: string) => void; onDraftDirty: (id: string, dirty: boolean) => void; onSelectFacility: (id: FacilityId) => void }) {
  const project = readProjectContext();
  const scenarioId = new URLSearchParams(window.location.search).get("scenario") || "base";
  const [drafts, setDrafts] = useDemoSessionState<FacilityMap>("facility-drafts", initialFacilities);
  const [saved, setSaved] = useDemoSessionState<FacilityMap>("facility-saved", initialFacilities);
  const [savedFacilities, setSavedFacilities] = useDemoSessionState<Record<FacilityId, boolean>>("facility-save-acknowledgements", {
    "Senior Debt A": false, "Senior Debt B": false, "Junior / Mezzanine": false, "Shareholder Loan (SHL)": false, "Sponsor Equity": false,
  });
  const [active, setActive] = useState<FacilityId>(() => {
    const requested = new URLSearchParams(window.location.search).get("facility") as FacilityId | null;
    return requested && facilityIds.includes(requested) ? requested : "Senior Debt A";
  });
  const [notice, setNotice] = useState("");
  const current = drafts[active];
  const dirty = JSON.stringify(current) !== JSON.stringify(saved[active]);
  const anyDirty = facilityIds.some(id => JSON.stringify(drafts[id]) !== JSON.stringify(saved[id]));
  useEffect(() => { onDraftDirty("finance", anyDirty); }, [anyDirty, onDraftDirty]);
  function updateContextParam(key: string, value: string) {
    const params = new URLSearchParams(window.location.search);
    params.set(key, value);
    window.history.replaceState(null, "", `${window.location.pathname}?${params.toString()}${window.location.hash}`);
  }
  const isEquity = active === "Sponsor Equity";
  const errors = useMemo(() => {
    const found: string[] = [];
    const commitment = Number(current.commitment);
    if (!Number.isFinite(commitment) || commitment < 0) found.push("Commitment must be a finite nonnegative amount.");
    if (!validDate(current.maturity)) found.push("Enter a valid maturity date.");
    if (!isEquity && current.rate && (!Number.isFinite(Number(current.rate)) || Number(current.rate) < 0 || Number(current.rate) > 30)) found.push("Rate example must be between 0 and 30%.");
    if (!Number.isFinite(Number(current.grace)) || Number(current.grace) < 0) found.push("Grace period must be a nonnegative month count.");
    return found;
  }, [current, isEquity]);
  function update<K extends keyof Facility>(key: K, value: Facility[K]) {
    setDrafts(old => ({ ...old, [active]: { ...old[active], [key]: value } }));
    setSavedFacilities(old => ({ ...old, [active]: false }));
    setNotice("");
  }
  function selectFacility(id: FacilityId) {
    setActive(id);
    setNotice("");
    updateContextParam("facility", id);
    onSelectFacility(id);
  }
  function save() {
    if (errors.length) { setNotice("Facility Save blocked by input validation. No values were acknowledged."); return; }
    setSaved(old => ({ ...old, [active]: { ...current } }));
    setSavedFacilities(old => ({ ...old, [active]: true }));
    setNotice(`${active} acknowledged locally. No sizing, sculpting or model Run occurred.`);
  }
  const showFacility = sheet === "senior-debt" || sheet === "investor";
  const showSources = sheet === "sources-uses";
  return <div className="fm-wf" aria-label="Synthetic financing and capital structure">
    <div className="fm-wf-notice" role="note"><strong>SYNTHETIC DEMO · no financing calculations</strong><span>Drafts stay in this browser tab's session only. Commitments do not size, balance or recalculate debt.</span></div>
    <div className="fm-wf-toolbar"><strong>Facility register</strong><span className="fm-wf-muted">Local selectors · illustrative terms only</span><button type="button" className="fm-btn" onClick={() => onOpen("credit-decision")}>Open lender review →</button></div>
    <nav className="fm-wf-finance-nav" aria-label="Financing review path">
      <button type="button" onClick={() => onOpen("senior-debt")}>Facility register</button>
      <button type="button" onClick={() => onOpen("sources-uses")}>Sources &amp; Uses</button>
      <a href={workbookHref("debt")}>Debt schedule</a>
      <button type="button" onClick={() => onOpen("credit-decision")}>Credit review</button>
      <span>Navigation only · no calculation lineage</span>
    </nav>
    <div className="fm-wf-scroll">
      <table className="fm-table fm-wf-table">
        <thead><tr><th scope="col">Instrument</th><th scope="col">Commitment</th><th scope="col">Rate type</th><th scope="col">Rate / margin</th><th scope="col">Maturity</th><th scope="col">Repayment</th><th scope="col">State</th></tr></thead>
        <tbody>{facilityIds.map(id => {
          const facility = drafts[id];
          return <tr key={id} className={active === id ? "fm-wf-row-active" : ""}>
            <th scope="row"><button type="button" className="fm-wf-row-button" aria-pressed={active === id} onClick={() => selectFacility(id)}>{id}</button></th>
            <td className="fm-mono">{facility.currency} {facility.commitment}m</td><td>{facility.interestType}</td><td className="fm-mono">{facility.rate}%</td>
            <td className="fm-mono">{facility.maturity}</td><td>{facility.repayment}</td><td>Demo · not approved</td>
          </tr>;
        })}</tbody>
      </table>
    </div>
    {(showFacility || showSources) && <div className="fm-wf-grid fm-wf-summary">
      <div><span>Senior Debt A/B</span><strong>Illustrative register entries</strong><small>No committed debt or sizing authority.</small></div>
      <div><span>Junior / SHL</span><strong>Preview-only examples</strong><small>Cash / PIK and subordination are not calculated.</small></div>
      <div><span>Sponsor equity</span><strong>Local demo commitment</strong><small>No waterfall or return calculation.</small></div>
      <div><span>Model state</span><strong>NOT RUN · fixed results</strong><small>Selection and Save do not change outputs.</small></div>
    </div>}
    {showFacility && <section className="fm-wf-section" aria-label={`${active} editor`}>
      <div className="fm-wf-editor-head">
        <div><h3>{active} assumptions</h3><p>Switching facilities preserves each in-page draft. This is not a lender offer.</p></div>
        <span className={dirty ? "fm-wf-dirty" : "fm-wf-muted"}>{dirty ? "WORKING COPY · UNSAVED" : "LOCAL SAVE · NOT RUN"}</span>
      </div>
      <div className="fm-wf-grid fm-wf-fields">
        <Field label="Instrument" value={current.instrument} onChange={value => update("instrument", value)} />
        <Field label="Commitment" value={current.commitment} unit="€m" error={errors[0]?.includes("Commitment") ? errors[0] : undefined} onChange={value => update("commitment", value)} />
        <label className="fm-wf-field">Currency <span>Illustrative</span><select aria-label="Facility currency" value={current.currency} onChange={event => update("currency", event.target.value)}><option>EUR</option><option>USD</option><option>GBP</option></select></label>
        <label className="fm-wf-field">Interest type <span>{isEquity ? "Not applicable" : "Demo assumption"}</span><select aria-label="Interest type" disabled={isEquity} value={current.interestType} onChange={event => update("interestType", event.target.value)}><option>Floating</option><option>Fixed</option><option>N/A</option></select></label>
        <label className="fm-wf-field">Reference rate <span>Not a curve</span><select aria-label="Reference rate" disabled={isEquity} value={current.referenceRate} onChange={event => update("referenceRate", event.target.value)}><option>EURIBOR</option><option>Fixed</option><option>N/A</option></select></label>
        <Field label={isEquity ? "Illustrative return label" : "Margin / rate"} value={current.rate} unit="%" error={errors.find(error => error.startsWith("Rate"))} onChange={value => update("rate", value)} />
        <Field label="Maturity" value={current.maturity} type="date" error={errors.find(error => error.startsWith("Enter a valid maturity"))} onChange={value => update("maturity", value)} />
        <Field label="Grace period" value={current.grace} unit="months" error={errors.find(error => error.startsWith("Grace"))} onChange={value => update("grace", value)} />
        <Field label="Arrangement / commitment fee" value={current.fee} unit="%" onChange={value => update("fee", value)} />
        <label className="fm-wf-field">Repayment type <span>Preview-only; no schedule</span><select aria-label="Repayment type" value={current.repayment} onChange={event => update("repayment", event.target.value)}><option>Sculpted · preview only</option><option>Amortising · preview only</option><option>Bullet · preview only</option><option>Residual · not calculated</option></select></label>
        {!isEquity && <Field label="P50 / P90 lender case" value={current.pCase} onChange={value => update("pCase", value)} />}
        {!isEquity && <Field label="DSCR covenant assumption" value={current.dscr} unit="x" onChange={value => update("dscr", value)} />}
        {!isEquity && <Field label="Cash sweep" value={current.cashSweep} calculated />}
        {(active === "Junior / Mezzanine" || active === "Shareholder Loan (SHL)") && <Field label="PIK coupon assumption" value={current.pik} unit="%" onChange={value => update("pik", value)} />}
        <Field label="Availability / authority" value={current.availability} calculated />
      </div>
      <div className="fm-wf-note"><strong>Unavailable:</strong> debt sizing, DSCR sculpting, cash-sweep waterfalls, covenant tests, lender bankability and intercreditor enforcement. No formula is executed.</div>
      <SourceAuthorityDrawer
        project={project}
        scenarioId={scenarioId}
        selection={`${active} · ${current.instrument}`}
        valueLabel={`${current.commitment} ${current.currency} m`}
        state={project.mode === "reference" ? "reference" : dirty ? "draft" : savedFacilities[active] ? "saved" : "draft"}
        sourceLabel="Synthetic facility register example"
        relatedHref={workbookHref("debt")}
        relatedLabel="Open fixed Debt statement example →"
        note="Facility terms are local display assumptions. The statement link is contextual navigation only; it does not establish facility-level calculation lineage."
      />
      <div className="fm-wf-actions"><span className="fm-wf-muted">Save facility draft only · no Run</span><button type="button" className="fm-btn fm-btn-primary" disabled={Boolean(errors.length)} onClick={save}>Save {active} demo</button></div>
      {notice && <div className="fm-info-note" role="status">{notice}</div>}
      {errors.length > 0 && <ul className="fm-wf-errors" role="alert">{errors.map(error => <li key={error}>{error}</li>)}</ul>}
    </section>}
    {showSources && <section className="fm-wf-section" aria-label="Sources and uses fixed example">
      <div className="fm-wf-editor-head"><div><h3>Sources & Uses</h3><p>Period-aligned funding review layout · values are fixed synthetic examples.</p></div><Status tone="amber">NOT RECONCILED TO DRAFTS</Status></div>
      <div className="fm-wf-sources">
        <div className="fm-wf-scroll"><table className="fm-table fm-wf-table"><caption>Uses · fixed synthetic example</caption><thead><tr><th scope="col">Use</th><th scope="col">EUR m</th><th scope="col">State</th></tr></thead><tbody>
          {[["Hard CAPEX","82.6"],["Development costs","12.4"],["Financing fees","1.8"],["IDC","4.2"],["Initial reserve funding","1.8"],["Other identified costs","2.0"]].map(([label,value])=><tr key={label}><th scope="row">{label}</th><td className="fm-mono">{value}</td><td>Fixed example</td></tr>)}
          <tr className="fm-wf-total"><th scope="row">Total Uses · illustrative</th><td className="fm-mono">104.8</td><td>Not recalculated</td></tr>
        </tbody></table></div>
        <div className="fm-wf-scroll"><table className="fm-table fm-wf-table"><caption>Sources · fixed synthetic example</caption><thead><tr><th scope="col">Source</th><th scope="col">EUR m</th><th scope="col">State</th></tr></thead><tbody>
          {[["Senior Debt A / B","67.0"],["Junior / Mezzanine","0.0"],["Shareholder Loan (SHL)","0.0"],["Sponsor Equity","37.8"]].map(([label,value])=><tr key={label}><th scope="row">{label}</th><td className="fm-mono">{value}</td><td>Fixed example</td></tr>)}
          <tr className="fm-wf-total"><th scope="row">Total Sources · illustrative</th><td className="fm-mono">104.8</td><td>Not recalculated</td></tr>
        </tbody></table></div>
      </div>
      <div className="fm-wf-note"><strong>Balancing example:</strong> both displayed totals are fixed at €104.8m and are not reconciled to edited facilities, CAPEX, fees, IDC or reserves. The amounts do not update on selection or Save.</div>
      <div className="fm-wf-editor-head"><div><h3>Reserves & debt-service trace</h3><p>Fixed sample periods, not a calculation or sizing schedule.</p></div><Status tone="gray">ENGINE NOT CONNECTED</Status></div>
      <div className="fm-wf-scroll">
        <table className="fm-table fm-wf-table fm-wf-period-table"><thead><tr><th scope="col">Metric · EUR m</th><th scope="col">2025</th><th scope="col">2026</th><th scope="col">2027</th><th scope="col">2028</th><th scope="col">2029</th><th scope="col">2030</th></tr></thead><tbody>
          {[
            ["DSRA · fixed reference","0.0","0.0","1.2","1.2","1.3","1.3"],
            ["DSRF · fixed reference","0.0","0.0","0.4","0.4","0.4","0.4"],
            ["Opening debt balance","0.0","12.2","30.9","67.0","65.3","62.8"],
            ["Construction draw / IDC","12.2","18.7","36.1","0.0","0.0","0.0"],
            ["Interest / principal","0.0","0.0","(3.8)","(4.7)","(4.9)","(5.1)"],
            ["Closing debt balance","12.2","30.9","67.0","65.3","62.8","60.1"],
            ["CFADS · fixed sample","0.0","0.0","8.4","10.6","10.9","11.0"],
            ["DSCR · fixed sample","—","—","1.25x","1.26x","1.28x","1.28x"],
          ].map(([label,...values])=><tr key={label}><th scope="row">{label}</th>{values.map((value,index)=><td className="fm-mono" key={index}>{value}</td>)}</tr>)}
        </tbody></table>
      </div>
      <p className="fm-wf-muted">Debt opening/closing, interest, principal, CFADS and DSCR lines are separately authored synthetic snapshots; they are not cross-sheet reconciled. Sculpting and DSRA/DSRF sizing remain unavailable.</p>
      <a className="fm-btn" href={workbookHref("debt")}>Open fixed Statements & Debt example →</a>
    </section>}
    <div style={{ display: sheet === "senior-debt" ? "block" : "none" }}><p className="fm-wf-muted">The statement workbook retains fixed Senior and Mezzanine samples; the new facility register is not connected to those rows.</p><button type="button" className="fm-btn" onClick={() => onOpen("debt")}>Open fixed Statements & Debt sheet</button></div>
  </div>;
}
