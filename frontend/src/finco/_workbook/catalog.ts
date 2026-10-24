import { fincoBasePath } from "../_shared/FincoShell";

export type SurfaceState = "Interactive demo" | "Visual mock" | "Unavailable";
export type WorkbookArea = "overview" | "inputs" | "financing" | "results" | "scenarios" | "analysis" | "findings";
export const workbookModules: { id: string; label: string; family: string; state: SurfaceState; destination?: string; detail: string; authority?: string }[] = [
  { id: "overview", label: "Overview", family: "Project", state: "Interactive demo", detail: "Project context and fixed illustrative examples." },
  { id: "diagnostics", label: "Findings", family: "Review", state: "Interactive demo", detail: "Input review notes only; no financial checks are performed." },
  { id: "scenarios", label: "Scenarios", family: "Review & analysis", state: "Interactive demo", detail: "Three independently editable local assumption records; all results remain fixed synthetic values." },
  { id: "compare", label: "Compare scenarios", family: "Review & analysis", state: "Interactive demo", detail: "Fixed Base/Downside/Upside examples; no deltas or results are calculated." },
  { id: "run-compare", label: "Compare saved runs", family: "Review & analysis", state: "Interactive demo", detail: "Select up to three fixed illustrative result records; no runs are created." },
  { id: "sensitivity", label: "Sensitivity", family: "Review & analysis", state: "Interactive demo", detail: "Selectable pre-authored sensitivity fixtures; no live solver." },
  { id: "goal-seek", label: "Target analysis", family: "Review & analysis", state: "Visual mock", detail: "Target and driver setup preview; no solver is available." },
  { id: "inputs", label: "Project setup", family: "Assumptions", state: "Interactive demo", detail: "Project identity and timeline fields." },
  { id: "input-grid", label: "Input Grid", family: "Assumptions", state: "Interactive demo", detail: "Keyboard-first scalar grid, staged edits, undo/cancel and validated local paste." },
  { id: "revenue", label: "Revenue & PPA", family: "Assumptions", state: "Interactive demo", detail: "Three independent local contract drafts with Fixed, Indexed and Scheduled fields; no price or allocation calculation." },
  { id: "advanced-revenue", label: "Merchant revenue", family: "Assumptions", state: "Unavailable", detail: "Merchant settlement and advanced revenue are not available in this preview.", authority: "Not available in this design preview." },
  { id: "cost-plan", label: "Cost plan", family: "Assumptions", state: "Interactive demo", detail: "Choose the existing CAPEX construction plan or OPEX operating profile." },
  { id: "capex", label: "CAPEX / spending", family: "Assumptions", state: "Interactive demo", detail: "Separate local cost-line save and partial monthly planner; no drawdown calculation." },
  { id: "opex", label: "OPEX / profiles", family: "Assumptions", state: "Interactive demo", detail: "Separate local cost-line save and partial operating profile; no escalation math." },
  { id: "investor", label: "Investor & Equity", family: "Capital & tax", state: "Interactive demo", detail: "Independent local facility/investor draft fields; returns and distribution waterfalls remain fixed or unavailable." },
  { id: "senior-debt", label: "Debt facilities", family: "Capital & tax", state: "Interactive demo", detail: "Five independent local facility drafts; sizing, DSCR sculpting and covenant tests are not available." },
  { id: "tax", label: "Tax & timing", family: "Assumptions", state: "Interactive demo", detail: "Local project milestone, display frequency and tax assumption editors; no schedules or tax calculations." },
  { id: "sources-uses", label: "Sources & uses", family: "Capital & tax", state: "Visual mock", detail: "Fixed illustrative funding and reserve view; figures do not reconcile." },
  { id: "pl", label: "Financial Statements · P&L", family: "Outputs", state: "Interactive demo", destination: "pl", detail: "Fixed statement workbook with expandable rows and sample traces." },
  { id: "balance", label: "Balance Sheet", family: "Outputs", state: "Interactive demo", destination: "balance", detail: "Fixed example balance-sheet rows, not an engine-balanced statement." },
  { id: "cashflow", label: "Cash Flow", family: "Outputs", state: "Interactive demo", destination: "cashflow", detail: "Fixed cash-flow waterfall example." },
  { id: "cfads", label: "CFADS", family: "Outputs", state: "Interactive demo", destination: "cfads", detail: "Fixed CFADS bridge example." },
  { id: "debt", label: "Statements & Debt", family: "Outputs", state: "Interactive demo", destination: "debt", detail: "Per-facility fixed construction and operating schedule samples." },
  { id: "sponsor", label: "Returns / Sponsor Returns", family: "Outputs", state: "Interactive demo", destination: "sponsor", detail: "Fixed sponsor contribution/distribution and return examples." },
  { id: "trust-pack", label: "Model record", family: "Review & analysis", state: "Visual mock", detail: "A display-only record of sample assumptions and results; no certified file is produced." },
  { id: "history", label: "Run history", family: "Review & analysis", state: "Interactive demo", detail: "Three fixed illustrative result records; Save and Run do not add history." },
  { id: "excel-migration", label: "Import workbook", family: "Assumptions", state: "Unavailable", detail: "Workbook file review is not yet available in this preview.", authority: "No file is uploaded or read." },
  { id: "exports", label: "Export results", family: "Outputs", state: "Unavailable", detail: "Downloading workbook or report files is not yet available in this preview.", authority: "No file is generated or downloaded." },
  { id: "financing-trace", label: "Facility guide", family: "Capital & tax", state: "Visual mock", detail: "Illustrative facility labels and navigation only; no calculated source detail." },
  { id: "credit-decision", label: "Lender review", family: "Capital & tax", state: "Interactive demo", detail: "Fixed lender-review examples and period/facility selectors; no sizing or compliance test." },
  { id: "advanced", label: "Advanced project options", family: "Project", state: "Unavailable", detail: "Advanced storage and hybrid project features are not available in this preview.", authority: "Not available in this design preview." },
  { id: "developer-economics", label: "Developer economics", family: "Capital & tax", state: "Unavailable", detail: "Developer economics are not available in this preview.", authority: "Not available in this design preview." },
  { id: "developer-decision", label: "Development decision", family: "Capital & tax", state: "Unavailable", detail: "Development decision tools are not available in this preview.", authority: "Not available in this design preview." },
  { id: "acquisition", label: "Acquisition review", family: "Project", state: "Unavailable", detail: "Acquisition review is not available in this preview.", authority: "Not available in this design preview." },
  { id: "investor-waterfall", label: "Investor distributions", family: "Capital & tax", state: "Unavailable", detail: "Investor-class distribution waterfalls are not available in this preview.", authority: "Not available in this design preview." },
  { id: "bess-storage", label: "Storage project", family: "Project", state: "Unavailable", detail: "Storage dispatch and battery degradation are not available in this preview.", authority: "Not available in this design preview." },
  { id: "data-center", label: "Data center", family: "Project", state: "Unavailable", detail: "Data-center-specific modeling is not available in this preview.", authority: "Not available in this design preview." },
  { id: "ev-charging", label: "EV charging", family: "Project", state: "Unavailable", detail: "EV-charging-specific modeling is not available in this preview.", authority: "Not available in this design preview." },
  { id: "advanced-technology", label: "Other technologies", family: "Project", state: "Unavailable", detail: "Other technology-specific modeling is not available in this preview.", authority: "Not available in this design preview." },
];

const areaByModule: Record<string, WorkbookArea> = {
  overview: "overview",
  inputs: "inputs",
  "input-grid": "inputs",
  revenue: "inputs",
  "advanced-revenue": "inputs",
  "cost-plan": "inputs",
  capex: "inputs",
  opex: "inputs",
  tax: "inputs",
  advanced: "inputs",
  "bess-storage": "inputs",
  "data-center": "inputs",
  "ev-charging": "inputs",
  "advanced-technology": "inputs",
  acquisition: "inputs",
  "senior-debt": "financing",
  investor: "financing",
  "sources-uses": "financing",
  "credit-decision": "financing",
  "financing-trace": "financing",
  "investor-waterfall": "financing",
  pl: "results",
  balance: "results",
  cashflow: "results",
  cfads: "results",
  debt: "results",
  sponsor: "results",
  history: "results",
  "trust-pack": "results",
  "excel-migration": "inputs",
  exports: "results",
  scenarios: "scenarios",
  compare: "scenarios",
  "run-compare": "scenarios",
  sensitivity: "analysis",
  "goal-seek": "analysis",
  "developer-economics": "analysis",
  "developer-decision": "analysis",
  diagnostics: "findings",
};

export const workbookAreaLabels: Record<WorkbookArea, string> = {
  overview: "Overview",
  inputs: "Inputs",
  financing: "Financing",
  results: "Results",
  scenarios: "Scenarios",
  analysis: "Analysis",
  findings: "Findings",
};

export function workbookAreaForModule(id: string): WorkbookArea {
  return areaByModule[id] || "findings";
}

export function workbookModulesForArea(area: WorkbookArea) {
  return workbookModules.filter((module) =>
    areaByModule[module.id] === area &&
    !["capex", "opex"].includes(module.id),
  );
}

export function workbookSelectedModule(id: string): string {
  return ["capex", "opex"].includes(id) ? "cost-plan" : id;
}

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
  return `${fincoBasePath()}ModelWorkspace?${params}#${id === "overview" ? "overview" : "workbook"}`;
}
