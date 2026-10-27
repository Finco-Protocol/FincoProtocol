import { useState } from "react";
import "../../styles/rcm-analysis.css";
import { CapexStudio } from "../capex/CapexStudio";

export type StudioId = "capex-profile";
const STUDIOS: ReadonlyArray<{ id: StudioId; label: string }> = [
  { id: "capex-profile", label: "CAPEX spending profile" },
];

/** Inputs > Studios (RC-UX): focused editors that sit beside the canonical grid, CAPEX / OPEX lines and Revenue & PPA contracts.  Each studio
 *  states its own Save scope; none of them runs the model and none computes a financial result in the browser. */
export function InputStudios({ project, protectedReference, reloadKey, onSaved }: {
  project: string; protectedReference: boolean; reloadKey: number; onSaved: () => void;
}) {
  const [studio, setStudio] = useState<StudioId>("capex-profile");
  return (
    <section className="rx-card" data-input-studios="true" aria-label="Input studios">
      <h2>Studios</h2>
      <p className="rx-note">Focused editors for construction spending{/* revenue and import studios join this list */}. Each saves on its own and never runs the model.</p>
      {STUDIOS.length > 1 && (
        <div className="rcm-tabs" role="tablist" aria-label="Input studios">
          {STUDIOS.map((s) => (
            <button key={s.id} type="button" role="tab" aria-selected={studio === s.id} className={`rcm-tab${studio === s.id ? " active" : ""}`}
              data-studio-tab={s.id} onClick={() => setStudio(s.id)}>{s.label}</button>
          ))}
        </div>
      )}
      {studio === "capex-profile" && (protectedReference
        ? <p className="rx-empty" role="status" data-capex-unavailable="true">Templates are read-only. Start a project from this template to plan a CAPEX spending profile.</p>
        : <CapexStudio project={project} reloadKey={reloadKey} onSaved={onSaved} />)}
    </section>
  );
}
