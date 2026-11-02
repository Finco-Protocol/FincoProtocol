// PR-U1 — the ONE CAPEX workbench and the ONE OPEX workbench (dedicated destinations, two views each):
//   CAPEX: Lines | Monthly schedule      OPEX: Lines | Years
// Everything here reuses an existing component and writer: the cost-line grid (atomic batch save, add / retire / reactivate routes), the OPEX
// base amounts (canonical cells, staged in the same store, saved by Save All), the CAPEX spending-profile editor (its own document and Save),
// the read-only OPEX year projection and the generic Excel / CSV import. No Run, no engine, no new route.
import { useState } from "react";
import { CapexStudio } from "./capex/CapexStudio";
import { CostLinesGridView } from "./editing/CostLinesGridView";
import { ImportWorkspace } from "./importer/ImportWorkspace";
import { OpexProjection } from "./projection/OpexProjection";
import { COST_VIEWS, type CostSheetId, type CostView, type WorkspaceDestination } from "./workspaceNavigation";
import type { InputsPayload } from "./types";

function baseRowsOf(inputs: InputsPayload | null): InputsPayload["grid"]["sections"][number]["categories"][number]["rows"] {
  if (!inputs) return [];
  return inputs.grid.sections.flatMap((s) => s.categories.flatMap((c) => c.rows)).filter((r) => (r.field_id || r.code).startsWith("opex.lines."));
}

export function CostWorkbench({ project, sheet, view, inputs, protectedReference, reloadKey, query, scenarioName, onMutated, onNavigate }: {
  project: string; sheet: CostSheetId; view: CostView; inputs: InputsPayload | null; protectedReference: boolean; reloadKey: number;
  query: string; scenarioName: string; onMutated: () => void; onNavigate: (destination: WorkspaceDestination) => void;
}) {
  const [importOpen, setImportOpen] = useState(false);
  const title = sheet === "capex" ? "CAPEX" : "OPEX";
  return (
    <section id="wf-inputs-costs" tabIndex={-1} className="cw" data-cost-workbench={sheet} data-cost-view={view} aria-label={`${title} workbench`}>
      <div className="cw-head">
        <a className="rx-legacy-link" href="#inputs" data-cw-back="true" onClick={(e) => { e.preventDefault(); onNavigate("inputs"); }}>← Back to Inputs</a>
        <nav className="cw-tabs" aria-label={`${title} views`}>
          {COST_VIEWS[sheet].map((v) => (
            <a key={v.id} href={`#${v.hash}`} className={view === v.id ? "active" : ""} aria-current={view === v.id ? "page" : undefined} data-cost-view-link={v.id}
               onClick={(e) => { e.preventDefault(); onNavigate(v.hash as WorkspaceDestination); }}>{v.label}</a>
          ))}
        </nav>
        {!protectedReference && (
          <button type="button" className="fm-btn" aria-expanded={importOpen} data-cw-import="true" onClick={() => setImportOpen((v) => !v)}>
            {importOpen ? "Close import" : "Import from Excel / CSV…"}
          </button>)}
      </div>
      {importOpen && !protectedReference && (
        <div className="cw-import" data-cw-import-panel="true">
          <ImportWorkspace project={project} protectedReference={protectedReference} onSaved={onMutated} />
        </div>)}
      {view === "lines" && (
        <CostLinesGridView key={sheet} project={project} sheet={sheet} reloadKey={reloadKey} onMutated={onMutated} query={query} scenarioName={scenarioName}
          baseRows={sheet === "opex" ? baseRowsOf(inputs) : []} onSheet={(next) => onNavigate(`inputs/${next}` as WorkspaceDestination)} />
      )}
      {view === "monthly" && (
        <div data-capex-monthly="true">
          <p className="rx-note" data-capex-monthly-note="true">
            When each CAPEX line is paid. The monthly profile is one document with its own <strong>Save profile</strong>; it is separate from the line amounts, which are saved on the
            Lines view. Neither saves the other and neither runs the model.
          </p>
          {protectedReference
            ? <p className="rx-empty" role="status" data-capex-unavailable="true">Templates are read-only. Start a project from this template to plan a CAPEX spending profile.</p>
            : <CapexStudio project={project} reloadKey={reloadKey} onSaved={onMutated} />}
        </div>
      )}
      {view === "years" && (
        <div data-opex-years="true">
          <OpexProjection project={project} reloadKey={reloadKey} />
        </div>
      )}
    </section>
  );
}
