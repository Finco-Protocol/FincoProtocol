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

export default function ModuleSurface({ sheet, onOpen, errors, onDraftDirty, onContextChange }: { sheet: string; onOpen: (id: string) => void; errors: number; onDraftDirty: (id: string, dirty: boolean) => void; onContextChange: (key: string, value: string) => void }) {
  const entry = workbookModules.find(m => m.id === sheet) || workbookModules[0];
  const visible = sheet !== "inputs" && sheet !== "input-grid";
  const slot = (id: string, child: React.ReactNode) => <div key={id} style={{ display: sheet === id ? "block" : "none" }} aria-hidden={sheet !== id}>{child}</div>;
  return <section className="fm-card fm-wb-module" aria-label={`${entry.label} module`} aria-hidden={!visible} style={{ display: visible ? undefined : "none" }}>
    <div className="fm-card-title"><h2>{entry.label}</h2><span>{entry.state}</span></div>
    <div className="fm-info-note">{entry.detail} <strong>All data synthetic. Main presence is based on supplied inventory; production release status is unverified.</strong></div>
    {sheet === "overview" && <div className="fm-wb-module-body">
      <p>Workbook surface coverage, not a 21-field replacement for the full FINCO product. Use the sheet tree to review every mapped family.</p>
      <div className="fm-toolbar"><button className="fm-btn fm-btn-primary" onClick={() => onOpen("input-grid")}>Open keyboard Input Grid</button><a className="fm-btn" href={workbookHref("pl")}>Open financial statement workbook</a></div>
      <p>Scalar batch saves, CAPEX line saves and OPEX line saves are separate. No Save automatically runs a model.</p>
    </div>}
    {slot("revenue", <RevenueWorkspace onDraftDirty={onDraftDirty} onSelectContract={id => onContextChange("contract", id)} />)}
    {["capex", "opex"].includes(sheet) && <div className="fm-wb-module-body"><p>{sheet === "capex" ? "CAPEX → categories → cost sublines → monthly spending planner." : "OPEX → categories → line items → operating step profiles."} The partial editable line planner below has a distinct save boundary.</p>
      <p>Construction: monthly · Operation: quarterly (3M) / semiannual (6M). <b>VIEW-ONLY design choices; frequency policy is not confirmed and no math changes.</b></p>
      <div className="fm-toolbar">
        {sheet === "capex" ? <a className="fm-btn" href={workbookHref("debt")}>Open fixed construction draw / IDC statement →</a> : <>
          <a className="fm-btn" href={workbookHref("pl")}>Open fixed P&amp;L example →</a>
          <a className="fm-btn" href={workbookHref("cfads")}>Open fixed CFADS example →</a>
        </>}
        <span className="fm-wf-muted">Navigation context only · no financial dependency</span>
      </div>
    </div>}
    {sheet === "tax" && <div className="fm-wb-module-body"><div className="fm-toolbar"><a className="fm-btn" href={workbookHref("pl")}>Open fixed P&amp;L tax-line example →</a><span className="fm-wf-muted">Tax edits do not update statements.</span></div></div>}
    <div style={{ display: ["senior-debt", "investor", "sources-uses"].includes(sheet) ? "block" : "none" }} aria-hidden={!["senior-debt", "investor", "sources-uses"].includes(sheet)}><FinanceWorkspace sheet={sheet} onOpen={onOpen} onDraftDirty={onDraftDirty} onSelectFacility={id => onContextChange("facility", id)} /></div>
    {slot("tax", <TimelineTaxWorkspace onDraftDirty={onDraftDirty} />)}
    <div style={{ display: ["scenarios", "history", "diagnostics"].includes(sheet) ? "block" : "none" }} aria-hidden={!["scenarios", "history", "diagnostics"].includes(sheet)}><ScenarioGovernanceWorkspace sheet={sheet} onDraftDirty={onDraftDirty} /></div>
    {sheet === "diagnostics" && <div className="fm-wb-module-body">
      <strong>{errors} local scalar validation errors on Project Inputs</strong>
      <p>Input validity is separate from financial integrity. No balance-sheet, cash-waterfall, covenant or engine-version checks run.</p>
      <div className="fm-toolbar">
        <button className="fm-btn" onClick={() => onOpen("inputs")}>Review validated inputs</button>
        <button className="fm-btn" onClick={() => onOpen("sources-uses")}>Open Sources & Uses</button>
        <button className="fm-btn" onClick={() => onOpen("credit-decision")}>Open lender review</button>
        <a className="fm-btn" href={workbookHref("trust-pack")}>Open Trust Pack</a>
      </div>
    </div>}
    {sheet === "investor" && <div className="fm-wb-module-body"><p>Sponsor contribution, ownership and instrument fields are editable in the dedicated facility register above. Distributions, IRR and MOIC remain fixed examples.</p><a href={workbookHref("sponsor")}>Open fixed Sponsor Returns sheet →</a><p>Distribution priority and investor-class waterfalls are unavailable.</p></div>}
    {["compare", "run-compare", "sensitivity", "goal-seek"].includes(sheet) && <DecisionAnalysisWorkspace sheet={sheet} />}
    {sheet === "credit-decision" && <CreditDecisionWorkspace />}
    {sheet === "financing-trace" && <div className="fm-wb-module-body"><p>Illustrative path: Facility commitment → construction draws / IDC / fees → operating service → closing balance.</p><p>Each label is a design trace, not verified source lineage. Open a debt metric in Statements & Debt for a synthetic display-only detail.</p><a href={workbookHref("debt")}>Open facility statement →</a></div>}
    {["trust-pack", "excel-migration", "exports"].includes(sheet) && <ModelDeliveryWorkspace sheet={sheet} />}
    {["advanced-revenue", "developer-economics", "developer-decision", "acquisition", "investor-waterfall", "bess-storage", "data-center", "ev-charging", "advanced-technology", "advanced"].includes(sheet) && <div className="fm-wb-module-body">
      <p>Capability gate only. This destination records the requested product surface without claiming that the feature is available or released.</p>
      <div className="fm-wb-module-gate"><strong>{entry.label}</strong><span>{entry.authority || "Release authority unknown · no editor or calculation is implemented."}</span><Status tone="gray">UNAVAILABLE / GATED</Status></div>
      <p>{entry.detail} No data import, model execution, approval or result is implied.</p>
    </div>}
  </section>;
}
