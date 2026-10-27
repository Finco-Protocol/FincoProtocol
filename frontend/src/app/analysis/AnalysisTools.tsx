import { useState, type ReactNode } from "react";
import "../../styles/rcm-analysis.css";
import { GoalSeekPanel } from "./GoalSeekPanel";
import { SensitivityPanel } from "./SensitivityPanel";
import { RunsWorkspace } from "../runs/RunsWorkspace";

export type AnalysisTool = "overview" | "sensitivity" | "goal-seek" | "runs";
const TOOLS: ReadonlyArray<{ id: AnalysisTool; label: string }> = [
  { id: "overview", label: "Last Run charts" },
  { id: "sensitivity", label: "Sensitivity" },
  { id: "goal-seek", label: "Goal Seek" },
  { id: "runs", label: "Run history & compare" },
];

function toolFromUrl(): AnalysisTool {
  const raw = new URLSearchParams(window.location.search).get("analysis");
  return TOOLS.some((t) => t.id === raw) ? (raw as AnalysisTool) : "overview";
}

/** Analysis hub: the existing Last Run analysis stays the first tab; Sensitivity and Goal Seek sit beside it.  The tool is kept in
 *  the URL query (`?analysis=`) so it can be linked, refreshed and navigated with Back/Forward-free `replaceState`. */
export function AnalysisTools({ project, protectedReference, workbookHash, onApplied, overview }: {
  project: string; protectedReference: boolean; workbookHash: string; onApplied: () => void; overview: ReactNode;
}) {
  const [tool, setTool] = useState<AnalysisTool>(toolFromUrl);

  function choose(next: AnalysisTool) {
    setTool(next);
    const url = new URL(window.location.href);
    if (next === "overview") url.searchParams.delete("analysis"); else url.searchParams.set("analysis", next);
    window.history.replaceState(null, "", `${url.pathname}${url.search}${url.hash}`);
  }

  return (
    <div data-analysis-tools="true" data-analysis-tool={tool}>
      <div className="rcm-tabs" role="tablist" aria-label="Analysis tools">
        {TOOLS.map((t) => (
          <button key={t.id} type="button" role="tab" id={`rcm-tab-${t.id}`} aria-selected={tool === t.id} aria-controls="rcm-tool-panel"
                  className={`rcm-tab${tool === t.id ? " active" : ""}`} data-analysis-tab={t.id} onClick={() => choose(t.id)}
                  onKeyDown={(e) => {
                    const i = TOOLS.findIndex((x) => x.id === tool);
                    if (e.key === "ArrowRight") { e.preventDefault(); choose(TOOLS[(i + 1) % TOOLS.length].id); }
                    if (e.key === "ArrowLeft") { e.preventDefault(); choose(TOOLS[(i + TOOLS.length - 1) % TOOLS.length].id); }
                  }}>{t.label}</button>
        ))}
      </div>
      <div id="rcm-tool-panel" role="tabpanel" aria-labelledby={`rcm-tab-${tool}`}>
        {tool === "overview" && overview}
        {tool === "sensitivity" && (protectedReference
          ? <section className="rx-card" data-sensitivity-state="PROTECTED"><h2>Sensitivity analysis</h2><p className="rx-empty" role="status" data-sensitivity-unavailable="true">Templates are read-only. Start a project from this template to run a sensitivity analysis.</p></section>
          : <SensitivityPanel project={project} workbookHash={workbookHash} />)}
        {tool === "goal-seek" && (protectedReference
          ? <section className="rx-card" data-goal-seek-state="PROTECTED"><h2>Goal Seek — tender pricing</h2><p className="rx-empty" role="status" data-goal-seek-unavailable="true">Templates are read-only. Start a project from this template to solve a tariff.</p></section>
          : <GoalSeekPanel project={project} workbookHash={workbookHash} onApplied={onApplied} />)}
        {tool === "runs" && (protectedReference
          ? <section className="rx-card" data-runs-state="PROTECTED"><h2>Run history &amp; compare</h2><p className="rx-empty" role="status" data-runs-unavailable="true">Templates are read-only. Start a project from this template to review its committed Run history.</p></section>
          : <RunsWorkspace project={project} workbookHash={workbookHash} />)}
      </div>
    </div>
  );
}
