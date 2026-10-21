import { fincoBasePath } from "../_shared/FincoShell";

export type SurfaceState = "Interactive demo" | "Visual mock" | "Unavailable";
export const workbookModules: { id: string; label: string; family: string; state: SurfaceState; destination?: string; detail: string; authority?: string }[] = [
  { id: "overview", label: "Overview", family: "Review & analysis", state: "Visual mock", detail: "Workbook orientation, fixed run identity and surface coverage." },
  { id: "diagnostics", label: "Model Diagnostics", family: "Review & analysis", state: "Interactive demo", detail: "Local input-validation diagnostics only; no engine integrity checks." },
  { id: "scenarios", label: "Scenarios", family: "Review & analysis", state: "Interactive demo", detail: "Three independently editable local assumption records; all results remain fixed synthetic values." },
  { id: "compare", label: "Scenario Compare", family: "Review & analysis", state: "Interactive demo", detail: "Fixed Base/Downside/Upside decision matrix; no deltas or results are calculated." },
  { id: "run-compare", label: "Run Compare", family: "Review & analysis", state: "Interactive demo", detail: "Select up to three fixed illustrative run snapshots; no runs are created." },
  { id: "sensitivity", label: "Sensitivity", family: "Review & analysis", state: "Interactive demo", detail: "Selectable pre-authored sensitivity fixtures; no live solver." },
  { id: "goal-seek", label: "Goal Seek", family: "Review & analysis", state: "Visual mock", detail: "Target, driver and bounds setup shown; solver execution unavailable." },
  { id: "inputs", label: "Project Setup / Inputs", family: "Assumptions", state: "Interactive demo", detail: "Preserved validated scalar forms and timeline fields." },
  { id: "input-grid", label: "Hybrid Input Grid", family: "Assumptions", state: "Interactive demo", detail: "Keyboard scalar grid, staged edits, undo/cancel and atomic validated paste." },
  { id: "revenue", label: "Revenue / multi-PPA", family: "Assumptions", state: "Interactive demo", detail: "Three independent local contract drafts with mode-specific Fixed, Indexed and Scheduled fields; no price or allocation engine." },
  { id: "advanced-revenue", label: "Advanced revenue / merchant", family: "Capability gates", state: "Unavailable", detail: "Merchant settlement, shaping, imbalance and advanced revenue workflows remain gated.", authority: "UNKNOWN · gated in this design" },
  { id: "capex", label: "CAPEX / spending", family: "Assumptions", state: "Interactive demo", detail: "Separate local cost-line save and partial monthly planner; no drawdown calculation." },
  { id: "opex", label: "OPEX / profiles", family: "Assumptions", state: "Interactive demo", detail: "Separate local cost-line save and partial operating profile; no escalation math." },
  { id: "investor", label: "Investor / Equity", family: "Capital & tax", state: "Interactive demo", detail: "Independent local facility/investor draft fields; returns and distribution waterfalls remain fixed or unavailable." },
  { id: "senior-debt", label: "Senior Debt / facilities", family: "Capital & tax", state: "Interactive demo", detail: "Five independent local facility drafts; sizing, DSCR sculpting, bankability and covenants remain unavailable." },
  { id: "tax", label: "Tax & timing", family: "Capital & tax", state: "Interactive demo", detail: "Local project milestone, frequency-display and tax assumption editors; no schedules or tax calculations." },
  { id: "sources-uses", label: "Sources & Uses / reserves", family: "Capital & tax", state: "Visual mock", detail: "Fixed synthetic funding and reserve snapshot; no reconciliation." },
  { id: "pl", label: "Financial Statements · P&L", family: "Outputs", state: "Interactive demo", destination: "pl", detail: "Fixed statement workbook with expandable rows and sample traces." },
  { id: "balance", label: "Balance Sheet", family: "Outputs", state: "Interactive demo", destination: "balance", detail: "Fixed example balance-sheet rows, not an engine-balanced statement." },
  { id: "cashflow", label: "Cash Flow", family: "Outputs", state: "Interactive demo", destination: "cashflow", detail: "Fixed cash-flow waterfall example." },
  { id: "cfads", label: "CFADS", family: "Outputs", state: "Interactive demo", destination: "cfads", detail: "Fixed CFADS bridge example." },
  { id: "debt", label: "Statements & Debt", family: "Outputs", state: "Interactive demo", destination: "debt", detail: "Per-facility fixed construction and operating schedule samples." },
  { id: "sponsor", label: "Returns / Sponsor Returns", family: "Outputs", state: "Interactive demo", destination: "sponsor", detail: "Fixed sponsor contribution/distribution and return examples." },
  { id: "trust-pack", label: "Trust Pack", family: "Trust & migration", state: "Visual mock", detail: "Assumption, run, provenance and integrity register; no certified pack/export." },
  { id: "history", label: "Run History", family: "Trust & migration", state: "Interactive demo", detail: "Three fixed illustrative history records with links; Save/Run do not append executions." },
  { id: "excel-migration", label: "Excel migration", family: "Trust & migration", state: "Visual mock", detail: "Disabled upload/mapping/reconciliation workflow; file import unavailable." },
  { id: "exports", label: "Exports", family: "Trust & migration", state: "Visual mock", detail: "Disabled Excel/PDF destination design; no files are generated." },
  { id: "financing-trace", label: "Financing trace", family: "Trust & migration", state: "Visual mock", detail: "Illustrative source labels only, not verified engine lineage." },
  { id: "credit-decision", label: "Lender / credit decision", family: "Capital & tax", state: "Interactive demo", detail: "Fixed lender-review matrix and period/facility selectors; no sizing or compliance test." },
  { id: "advanced", label: "Advanced project / technology", family: "Capability gates", state: "Unavailable", detail: "Storage/hybrid/advanced capabilities deliberately gated.", authority: "Main inventory adjacent capability; release authority unknown / gated." },
  { id: "developer-economics", label: "Developer Economics", family: "Capability gates", state: "Unavailable", detail: "Release-closed/unknown capability; no editor or calculation.", authority: "UNKNOWN · gated in this design" },
  { id: "developer-decision", label: "Developer Decision", family: "Capability gates", state: "Unavailable", detail: "Release-closed/unknown capability; no decision workflow.", authority: "UNKNOWN · gated in this design" },
  { id: "acquisition", label: "Acquisition analysis", family: "Capability gates", state: "Unavailable", detail: "No acquisition underwriting editor or valuation workflow.", authority: "UNKNOWN · gated in this design" },
  { id: "investor-waterfall", label: "Investor waterfall", family: "Capability gates", state: "Unavailable", detail: "No investor-class distribution or waterfall calculation.", authority: "UNKNOWN · gated in this design" },
  { id: "bess-storage", label: "BESS / Storage", family: "Capability gates", state: "Unavailable", detail: "Storage dispatch and battery degradation workflows are not implemented.", authority: "UNKNOWN · gated in this design" },
  { id: "data-center", label: "Data Center", family: "Capability gates", state: "Unavailable", detail: "Technology-specific Data Center workflow is not implemented.", authority: "UNKNOWN · gated in this design" },
  { id: "ev-charging", label: "EV Charging", family: "Capability gates", state: "Unavailable", detail: "Technology-specific EV Charging workflow is not implemented.", authority: "UNKNOWN · gated in this design" },
  { id: "advanced-technology", label: "Other technology workspaces", family: "Capability gates", state: "Unavailable", detail: "Other technology-specific workflows remain explicitly gated.", authority: "UNKNOWN · gated in this design" },
];
export function workbookHref(id: string) {
  const entry = workbookModules.find(m => m.id === id);
  const params = new URLSearchParams(window.location.search);
  params.delete("statement"); params.delete("sheet");
  if (entry?.destination) {
    const panel = ["scenarios", "history"].includes(entry.destination);
    if (!panel) params.set("statement", entry.destination);
    return `${fincoBasePath()}ResultsAnalysis?${params}#${panel ? entry.destination : "statement-workbook"}`;
  }
  params.set("sheet", id);
  return `${fincoBasePath()}ModelWorkspace?${params}#${id === "inputs" ? "inputs" : "workbook"}`;
}
