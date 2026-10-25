import React from "react";
import { Status } from "../_shared/FincoShell";
import { workbookHref, workbookModules } from "./catalog";

export default function ModelDeliveryWorkspace({ sheet }: { sheet: string }) {
  const trust = sheet === "trust-pack";
  const exports = sheet === "exports";
  if (!trust && !exports) return <section className="fm-wf-section" aria-label="Excel migration workflow">
    <div className="fm-wf-notice" role="note"><strong>WORKBOOK IMPORT · NOT AVAILABLE</strong><span>No workbook file is opened or read in this preview.</span></div>
    <div className="fm-wf-toolbar"><div><strong>Excel import preview</strong><div className="fm-wf-muted">Preview only · files cannot be opened here</div></div><Status tone="amber">NOT AVAILABLE</Status></div>
    <ol className="fm-wf-migration-steps">
      {[
        ["1", "Choose a workbook", "File selection is disabled; no file is opened."],
        ["2", "Review project inputs", "This preview shows a small set of illustrative inputs only."],
        ["3", "Review scenarios", "Workbook formulas and scenario data are not read."],
        ["4", "Review workbook layout", "Advanced workbook structures are not available here."],
        ["5", "Review before use", "No reconciliation or approval is performed."],
      ].map(([step,title,copy]) => <li key={step}><span>{step}</span><div><strong>{title}</strong><p>{copy}</p></div><Status tone="gray">NOT AVAILABLE</Status></li>)}
    </ol>
    <div className="fm-wf-actions"><label className="fm-wf-field">Workbook file · unavailable<input type="file" aria-label="Workbook file import unavailable" disabled accept=".xlsx,.xlsm,.xls" /></label><button type="button" className="fm-btn" disabled>Review import · unavailable</button></div>
    <div className="fm-wf-note">You can enter or paste simple values in the Input Grid. Workbook file import is not available.</div>
  </section>;

  return <div className="fm-wf fm-delivery-workspace" aria-label={trust ? "Model record" : "Export design preview"}>
    <div className="fm-wf-notice" role="note"><strong>{trust ? "MODEL RECORD · EXAMPLE" : "MODEL EXPORTS · NOT AVAILABLE"}</strong><span>This preview shows fixed illustrative information only. It has not been recalculated or reviewed.</span></div>
    <div className="fm-wf-toolbar"><div><strong>{trust ? "Model record" : "Export options"}</strong><div className="fm-wf-muted">DEMO-FIXED-018 · shared example</div></div><Status tone="amber">{trust ? "EXAMPLE ONLY" : "NOT AVAILABLE"}</Status></div>
    {trust ? <>
      <div className="fm-wf-summary fm-trust-summary">
        {[
          ["Project inputs", "Partial preview", "Only a small set of illustrative input fields is shown."],
          ["Input sources", "Not included", "No source documents or review records are attached."],
          ["Example results", "DEMO-FIXED-018", "A fixed example; not a live calculation."],
          ["Calculation", "Not run", "This preview is not connected to a calculation service."],
          ["Financial checks", "Not available", "No statements or lender tests have been checked."],
          ["Assumption links", "Navigation only", "Links open related pages; they do not show how figures were calculated."],
          ["Run history", "3 fixed examples", "These examples are not saved run records."],
          ["Download", "Not available", "No review pack or file can be created here."],
        ].map(([label,value,detail]) => <div key={label}><span>{label}</span><strong>{value}</strong><small>{detail}</small></div>)}
      </div>
      <div className="fm-wf-section"><div className="fm-wf-editor-head"><div><h3>Available pages</h3><p>Availability describes this preview only, not a connected financial product.</p></div><Status tone="gray">PREVIEW ONLY</Status></div>
        <div className="fm-wf-scroll"><table className="fm-table fm-wf-table fm-trust-table">
          <thead><tr><th scope="col">Area</th><th scope="col">Open page</th><th scope="col">Preview status</th><th scope="col">What to expect</th></tr></thead>
          <tbody>{workbookModules.map(module => <tr key={module.id}><th scope="row">{module.label}</th><td>{module.destination ? <a href={workbookHref(module.id)}>Open page</a> : "Workspace page"}</td><td>{module.destination ? "Example view" : "Not available"}</td><td>{module.destination ? "Illustrative content only" : "No inputs or results are provided here."}</td></tr>)}</tbody>
        </table></div>
      </div>
      <div className="fm-wf-actions">
        <span className="fm-wf-muted">No report or file will be created.</span>
        <a className="fm-btn" href={workbookHref("exports")}>Review download options →</a>
        <button type="button" className="fm-btn" disabled>Download · unavailable</button>
      </div>
    </> : <>
      <div className="fm-wf-grid fm-wf-fields">
        <label className="fm-wf-field">Export content <span>Preview selection only</span><select aria-label="Export content" defaultValue="Statements"><option>Statements</option><option>Assumptions</option><option>Scenario comparison</option><option>Credit analysis</option><option>Run evidence</option></select></label>
        <label className="fm-wf-field">Destination <span>Disabled</span><select aria-label="Export destination" disabled defaultValue="Excel"><option>Excel</option><option>PDF</option></select></label>
          <label className="fm-wf-field">Example reference <span>Fixed example</span><input aria-label="Export example reference" value="DEMO-FIXED-018" readOnly /></label>
          <label className="fm-wf-field">Review status <span>Not checked</span><input aria-label="Export review status" value="Not checked" readOnly /></label>
      </div>
      <div className="fm-wf-note">Download options are shown for review only. No Excel or PDF file will be created.</div>
      <div className="fm-wf-actions"><span className="fm-wf-muted">No file will be created or downloaded.</span><button type="button" className="fm-btn" disabled>Download · unavailable</button></div>
    </>}
  </div>;
}
