import React from "react";
import { Status } from "../_shared/FincoShell";
import { workbookHref, workbookModules } from "./catalog";

export default function ModelDeliveryWorkspace({ sheet }: { sheet: string }) {
  const trust = sheet === "trust-pack";
  const exports = sheet === "exports";
  if (!trust && !exports) return <section className="fm-wf-section" aria-label="Excel migration workflow">
    <div className="fm-wf-notice" role="note"><strong>WORKBOOK MIGRATION · UNAVAILABLE</strong><span>No workbook bytes are accepted or parsed. This is a workflow design, not an import capability.</span></div>
    <div className="fm-wf-toolbar"><div><strong>Excel migration review</strong><div className="fm-wf-muted">Mapping preview · no file processing</div></div><Status tone="amber">IMPORT DISABLED</Status></div>
    <ol className="fm-wf-migration-steps">
      {[
        ["1", "Identify workbook", "Upload control is intentionally disabled; no file is read."],
        ["2", "Map template", "Preview fields map only to the 21 scalar demo examples."],
        ["3", "Map scenarios", "No scenario values or formulas are parsed."],
        ["4", "Review unsupported structures", "Macros, formulas, links, period grids and named ranges are unavailable."],
        ["5", "Reconcile & sign off", "Reconciliation is not evaluated; explicit Run-first acceptance is unavailable."],
      ].map(([step,title,copy]) => <li key={step}><span>{step}</span><div><strong>{title}</strong><p>{copy}</p></div><Status tone="gray">NOT IMPLEMENTED</Status></li>)}
    </ol>
    <div className="fm-wf-actions"><label className="fm-wf-field">Workbook file · disabled<input type="file" aria-label="Workbook file import unavailable" disabled accept=".xlsx,.xlsm,.xls" /></label><button type="button" className="fm-btn" disabled>Review import · unavailable</button></div>
    <div className="fm-wf-note">Only the existing validated scalar TSV paste is implemented. No Excel file, macro, formula, external link, upload, or reconciliation will be processed.</div>
  </section>;

  return <div className="fm-wf fm-delivery-workspace" aria-label={trust ? "Trust Pack and model provenance" : "Export design preview"}>
    <div className="fm-wf-notice" role="note"><strong>{trust ? "MODEL TRUST REGISTER" : "MODEL EXPORTS · DISABLED"}</strong><span>Design coverage only. No signed provenance, certified result, external storage, generated file or engine connection exists.</span></div>
    <div className="fm-wf-toolbar"><div><strong>{trust ? "Trust Pack & run provenance" : "Export center"}</strong><div className="fm-wf-muted">DEMO-FIXED-018 · shared synthetic example</div></div><Status tone="amber">{trust ? "NOT CERTIFIED" : "EXPORT UNAVAILABLE"}</Status></div>
    {trust ? <>
      <div className="fm-wf-summary fm-trust-summary">
        {[
          ["Assumption register", "Partial demo inputs", "Only local scalar/cost-line examples; not a full schema."],
          ["Input provenance", "NOT VERIFIED", "No source file, owner, timestamp or immutable snapshot."],
          ["Run identity", "DEMO-FIXED-018", "Authored fixed example; not a real model execution."],
          ["Engine/version", "NOT CONNECTED", "No versioned calculation engine is attached."],
          ["Financial integrity", "NOT EVALUATED", "No balance, cash-flow or covenant check executed."],
          ["Calculation trace", "DISPLAY LABELS ONLY", "Trace UI does not prove numeric dependency."],
          ["Historical runs", "3 FIXED EXAMPLES", "No appended, persisted or audited run events."],
          ["Export readiness", "UNAVAILABLE", "No certified Trust Pack or file export."],
        ].map(([label,value,detail]) => <div key={label}><span>{label}</span><strong>{value}</strong><small>{detail}</small></div>)}
      </div>
      <div className="fm-wf-section"><div className="fm-wf-editor-head"><div><h3>Coverage and release authority</h3><p>“Listed in inventory” is not proof of current production availability.</p></div><Status tone="gray">AUTHORITY UNKNOWN UNLESS VERIFIED</Status></div>
        <div className="fm-wf-scroll"><table className="fm-table fm-wf-table fm-trust-table">
          <thead><tr><th scope="col">Product area</th><th scope="col">Design destination</th><th scope="col">Prototype state</th><th scope="col">Release authority</th><th scope="col">Known limits</th></tr></thead>
          <tbody>{workbookModules.map(module => <tr key={module.id}><th scope="row"><a href={workbookHref(module.id)}>{module.label}</a></th><td>{module.destination ? "Results workbook / panel" : "Workspace sheet"}</td><td>{module.state}</td><td>{module.authority || "UNKNOWN · not independently verified"}</td><td>{module.detail}</td></tr>)}</tbody>
        </table></div>
      </div>
      <div className="fm-wf-actions">
        <span className="fm-wf-muted">Trust Pack export is unavailable; no file will be created.</span>
        <a className="fm-btn" href={workbookHref("exports")}>Review export options →</a>
        <button type="button" className="fm-btn" disabled>Export Trust Pack · unavailable</button>
      </div>
    </> : <>
      <div className="fm-wf-grid fm-wf-fields">
        <label className="fm-wf-field">Export content <span>Preview selection only</span><select aria-label="Export content" defaultValue="Statements"><option>Statements</option><option>Assumptions</option><option>Scenario comparison</option><option>Credit analysis</option><option>Run evidence</option></select></label>
        <label className="fm-wf-field">Destination <span>Disabled</span><select aria-label="Export destination" disabled defaultValue="Excel"><option>Excel</option><option>PDF</option></select></label>
        <label className="fm-wf-field">Run identity <span>Fixed reference</span><input aria-label="Export run identity" value="DEMO-FIXED-018" readOnly /></label>
        <label className="fm-wf-field">Certification state <span>Not available</span><input aria-label="Export certification state" value="NOT CERTIFIED" readOnly /></label>
      </div>
      <div className="fm-wf-note">Export destinations are visual-only controls. No Excel/PDF bytes, financial statements, assumptions, credit analysis or run evidence are generated.</div>
      <div className="fm-wf-actions"><span className="fm-wf-muted">No file will be created or downloaded.</span><button type="button" className="fm-btn" disabled>Export · unavailable</button></div>
    </>}
  </div>;
}
