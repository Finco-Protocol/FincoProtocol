import React from "react";
import { workbookModules, workbookHref } from "./catalog";
import { Status } from "../_shared/FincoShell";
import RevenueWorkspace from "./RevenueWorkspace";
import FinanceWorkspace from "./FinanceWorkspace";
import TimelineTaxWorkspace from "./TimelineTaxWorkspace";
import ScenarioGovernanceWorkspace from "./ScenarioGovernanceWorkspace";
import CreditDecisionWorkspace from "./CreditDecisionWorkspace";
import DecisionAnalysisWorkspace from "./DecisionAnalysisWorkspace";
import ModelDeliveryWorkspace from "./ModelDeliveryWorkspace";
import "./workflows.css";

export default function ModuleSurface({ sheet, onOpen, errors, onDraftDirty, onContextChange, onScenarioChangeRequest, readOnly = false }: {
  sheet: string;
  onOpen: (id: string) => void;
  errors: number;
  onDraftDirty: (id: string, dirty: boolean) => void;
  onContextChange: (key: string, value: string) => void;
  onScenarioChangeRequest?: (id: string, proceed: () => void) => void;
  readOnly?: boolean;
}) {
  const entry = workbookModules.find(m => m.id === sheet) || workbookModules[0];
  const visible = sheet !== "inputs" && sheet !== "input-grid" && sheet !== "overview";
  const slot = (id: string, child: React.ReactNode) => <div key={id} style={{ display: sheet === id ? "block" : "none" }} aria-hidden={sheet !== id}>{child}</div>;
  const protectReference = (content: React.ReactNode) => readOnly
    ? <fieldset className="fm-readonly-fieldset" disabled><legend className="fm-sr-only">{entry.label} · read-only Reference</legend>{content}</fieldset>
    : content;
  return <section className="fm-card fm-wb-module" aria-label={`${entry.label} module`} aria-hidden={!visible} style={{ display: visible ? undefined : "none" }}>
    <div className="fm-card-title"><h2>{entry.label}</h2>{entry.state === "Visual mock" && <span>Preview</span>}</div>
    {readOnly && <p className="fm-info-note" role="note">Read-only Reference · editing and local Save are unavailable.</p>}
    <div className="fm-info-note">{entry.detail}</div>
    {sheet === "cost-plan" && <div className="fm-wb-module-body">
      <p>Choose a cost schedule. The period tables are local examples; totals and profiles are not recalculated.</p>
      <div className="fm-toolbar">
        <button className="fm-btn fm-btn-primary" onClick={() => onOpen("capex")}>Open CAPEX construction plan</button>
        <button className="fm-btn" onClick={() => onOpen("opex")}>Open OPEX operating profile</button>
      </div>
      <div className="fm-info-note" style={{ marginTop: 10 }}>Project Inputs contain summary assumptions only. Edit period line items in this Cost plan area.</div>
    </div>}
    {slot("revenue", protectReference(<RevenueWorkspace onDraftDirty={onDraftDirty} onSelectContract={id => onContextChange("contract", id)} />))}
    {["capex", "opex"].includes(sheet) && <div className="fm-wb-module-body"><p>{sheet === "capex" ? "CAPEX → categories → cost sublines → monthly spending planner." : "OPEX → categories → line items → operating step profiles."} The partial editable line planner below has a distinct save boundary.</p>
      <p>Construction: monthly · Operation: quarterly (3M) / semiannual (6M). <b>VIEW-ONLY design choices; frequency policy is not confirmed and no math changes.</b></p>
      <div className="fm-toolbar">
        <button className="fm-btn" onClick={() => onOpen(sheet === "capex" ? "opex" : "capex")}>Switch to {sheet === "capex" ? "OPEX profile" : "CAPEX plan"}</button>
        {sheet === "capex" ? <a className="fm-btn" href={workbookHref("debt")}>Open fixed construction draw / IDC statement →</a> : <>
          <a className="fm-btn" href={workbookHref("pl")}>Open fixed P&amp;L example →</a>
          <a className="fm-btn" href={workbookHref("cfads")}>Open fixed CFADS example →</a>
        </>}
        <span className="fm-wf-muted">Navigation context only · no financial dependency</span>
      </div>
    </div>}
    {sheet === "tax" && <div className="fm-wb-module-body"><div className="fm-toolbar"><a className="fm-btn" href={workbookHref("pl")}>Open fixed P&amp;L tax-line example →</a><span className="fm-wf-muted">Tax edits do not update statements.</span></div></div>}
    <div style={{ display: ["senior-debt", "investor", "sources-uses"].includes(sheet) ? "block" : "none" }} aria-hidden={!["senior-debt", "investor", "sources-uses"].includes(sheet)}>{protectReference(<FinanceWorkspace sheet={sheet} onOpen={onOpen} onDraftDirty={onDraftDirty} onSelectFacility={id => onContextChange("facility", id)} />)}</div>
    {slot("tax", protectReference(<TimelineTaxWorkspace onDraftDirty={onDraftDirty} />))}
    <div style={{ display: ["scenarios", "history", "diagnostics"].includes(sheet) ? "block" : "none" }} aria-hidden={!["scenarios", "history", "diagnostics"].includes(sheet)}>{protectReference(<ScenarioGovernanceWorkspace sheet={sheet} onDraftDirty={onDraftDirty} onScenarioChangeRequest={onScenarioChangeRequest} onContextChange={onContextChange} />)}</div>
    {sheet === "diagnostics" && <div className="fm-wb-module-body">
      <strong>{errors} input {errors === 1 ? "item needs" : "items need"} review in Project Setup</strong>
      <p>This preview checks input format only. It does not review financial statements or lender requirements.</p>
      <div className="fm-toolbar">
        <button className="fm-btn" onClick={() => onOpen("inputs")}>Review validated inputs</button>
        <button className="fm-btn" onClick={() => onOpen("sources-uses")}>Open Sources & Uses</button>
        <button className="fm-btn" onClick={() => onOpen("credit-decision")}>Open lender review</button>
        <a className="fm-btn" href={workbookHref("trust-pack")}>Open model record</a>
      </div>
    </div>}
    {sheet === "investor" && <div className="fm-wb-module-body"><p>Sponsor contribution, ownership and instrument fields are editable in the dedicated facility register above. Distributions, IRR and MOIC remain fixed examples.</p><a href={workbookHref("sponsor")}>Open fixed Sponsor Returns sheet →</a><p>Distribution priority and investor-class waterfalls are unavailable.</p></div>}
    {["compare", "run-compare", "sensitivity", "goal-seek"].includes(sheet) && protectReference(<DecisionAnalysisWorkspace sheet={sheet} />)}
    {sheet === "credit-decision" && <CreditDecisionWorkspace />}
    {sheet === "financing-trace" && <div className="fm-wb-module-body"><p>Illustrative path: Facility commitment → construction draws / fees → operating service → closing balance.</p><p>This is a navigation guide only; it does not show a calculated relationship.</p><a href={workbookHref("debt")}>Open facility statement →</a></div>}
    {["trust-pack", "excel-migration", "exports"].includes(sheet) && <ModelDeliveryWorkspace sheet={sheet} />}
    {["advanced-revenue", "developer-economics", "developer-decision", "acquisition", "investor-waterfall", "bess-storage", "data-center", "ev-charging", "advanced-technology", "advanced"].includes(sheet) && <div className="fm-wb-module-body">
      <p>This area is not yet available in the current preview.</p>
      <div className="fm-wb-module-gate"><strong>{entry.label}</strong><span>{entry.detail}</span><Status tone="gray">Not yet available</Status></div>
      <p>No file is imported and no financial result or approval is produced here.</p>
    </div>}
  </section>;
}
