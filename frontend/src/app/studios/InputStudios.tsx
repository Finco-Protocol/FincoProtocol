import { useState } from "react";
import "../../styles/rcm-analysis.css";
import { CapexStudio } from "../capex/CapexStudio";
import { ImportWorkspace } from "../importer/ImportWorkspace";
import { SheetFieldsEditor } from "../workflow/SheetFieldsEditor";

export type StudioId = "capex-profile" | "revenue-assumptions" | "import";
const STUDIOS: ReadonlyArray<{ id: StudioId; label: string }> = [
  { id: "capex-profile", label: "CAPEX spending profile" },
  { id: "revenue-assumptions", label: "Revenue assumptions" },
  { id: "import", label: "Import from Excel / CSV" },
];

/** Inputs > Studios (RC-UX): focused editors that sit beside the canonical grid, CAPEX / OPEX lines and Revenue & PPA contracts.  Each studio
 *  states its own Save scope; none of them runs the model and none computes a financial result in the browser. */
export function InputStudios({ project, protectedReference, reloadKey, onSaved }: {
  project: string; protectedReference: boolean; reloadKey: number; onSaved: () => void;
}) {
  // Closed until chosen: the Inputs page stays compact (U01) and each studio loads only when it is opened.
  const [studio, setStudio] = useState<StudioId | null>(null);
  return (
    <section className="rx-card" data-input-studios="true" aria-label="Input studios">
      <h2>Studios</h2>
      <p className="rx-note">Focused editors for construction spending and revenue assumptions, and import from a spreadsheet. Each saves on its own and never runs the model.</p>
      {STUDIOS.length > 1 && (
        <div className="rcm-tabs" role="tablist" aria-label="Input studios">
          {STUDIOS.map((s) => (
            <button key={s.id} type="button" role="tab" aria-selected={studio === s.id} className={`rcm-tab${studio === s.id ? " active" : ""}`}
              data-studio-tab={s.id} onClick={() => setStudio(studio === s.id ? null : s.id)}>{s.label}</button>
          ))}
        </div>
      )}
      {studio === null && <p className="rx-note" data-studios-closed="true">Choose a studio above to open it.</p>}
      {studio === "capex-profile" && (protectedReference
        ? <p className="rx-empty" role="status" data-capex-unavailable="true">Templates are read-only. Start a project from this template to plan a CAPEX spending profile.</p>
        : <CapexStudio project={project} reloadKey={reloadKey} onSaved={onSaved} />)}
      {studio === "revenue-assumptions" && (
        <div data-revenue-assumptions="true">
          <p className="rx-note">Revenue price, indexation and operating assumptions of the project. Each field saves on its own and never runs the model. Contract-level terms are edited under Revenue &amp; PPA contracts above.</p>
          <SheetFieldsEditor project={project} sheet="revenue" title="Revenue assumptions" reloadKey={reloadKey} onSaved={onSaved} />
        </div>
      )}
      {studio === "import" && <ImportWorkspace project={project} protectedReference={protectedReference} onSaved={onSaved} />}
    </section>
  );
}