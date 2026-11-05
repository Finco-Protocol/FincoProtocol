/** One route and navigation vocabulary for the financial workspace. */
export type WorkspaceSection = "overview" | "inputs" | "statements" | "results" | "analysis"
  | "financing" | "debt-metrics" | "scenarios" | "diagnostics" | "trust";
export const SECTION_LABELS: Record<WorkspaceSection, string> = {
  overview: "Overview", inputs: "Inputs", statements: "Statements", results: "Results", analysis: "Analysis",
  financing: "Financing", "debt-metrics": "Debt metrics", scenarios: "Scenarios", diagnostics: "Model checks", trust: "Trust",
};
export const WORKSPACE_SECTIONS = (["inputs", "statements", "financing", "results", "scenarios", "analysis", "diagnostics", "trust", "debt-metrics"] as WorkspaceSection[])
  .map((id, index) => ({ id, label: SECTION_LABELS[id], number: String(index + 1).padStart(2, "0") }));
export function isWorkspaceSection(value: string): value is WorkspaceSection {
  return Object.prototype.hasOwnProperty.call(SECTION_LABELS, value);
}

export const INPUT_DESTINATIONS = {
  project: { label: "Project & Timeline", target: "wf-inputs-setup" },
  technical: { label: "Technical & Production", target: "wf-inputs-grid" },
  capex: { label: "CAPEX", target: "wf-inputs-costs" },
  opex: { label: "OPEX", target: "wf-inputs-costs" },
  revenue: { label: "Revenue / PPA", target: "wf-inputs-revenue" },
  tax: { label: "Tax", target: "wf-inputs-grid" },
} as const;
export type InputDestination = keyof typeof INPUT_DESTINATIONS;

/** PR-U1: CAPEX and OPEX are dedicated workbenches with two views each (CAPEX: Lines / Monthly schedule, OPEX: Lines / Years). */
export type CostSheetId = "capex" | "opex";
export type CostView = "lines" | "monthly" | "years";
export const COST_VIEWS: Readonly<Record<CostSheetId, ReadonlyArray<{ id: CostView; label: string; hash: string }>>> = {
  capex: [{ id: "lines", label: "Lines", hash: "inputs/capex" }, { id: "monthly", label: "Monthly schedule", hash: "inputs/capex/monthly" }],
  opex: [{ id: "lines", label: "Lines", hash: "inputs/opex" }, { id: "years", label: "Years", hash: "inputs/opex/years" }],
};

export type WorkspaceDestination = WorkspaceSection | `inputs/${InputDestination}` | "inputs/capex/monthly" | "inputs/opex/years";

export const WORKSPACE_NAV_GROUPS: ReadonlyArray<{ label: string; destination?: WorkspaceDestination; items: ReadonlyArray<{ destination: WorkspaceDestination; label: string }> }> = [
  { label: "Model", items: [{ destination: "overview", label: SECTION_LABELS.overview }] },
  { label: "Inputs", destination: "inputs", items: [
    { destination: "inputs/project", label: "Project" }, { destination: "inputs/technical", label: "Technical" },
    { destination: "inputs/capex", label: "CAPEX" }, { destination: "inputs/opex", label: "OPEX" },
    { destination: "inputs/revenue", label: "Revenue" }, { destination: "financing", label: SECTION_LABELS.financing },
    { destination: "inputs/tax", label: "Tax" },
  ] },
  { label: "Outputs", items: [{ destination: "statements", label: SECTION_LABELS.statements }, { destination: "results", label: SECTION_LABELS.results }, { destination: "debt-metrics", label: SECTION_LABELS["debt-metrics"] }] },
  { label: "Decide", items: [{ destination: "scenarios", label: SECTION_LABELS.scenarios }, { destination: "analysis", label: SECTION_LABELS.analysis }] },
  { label: "Check", items: [{ destination: "diagnostics", label: SECTION_LABELS.diagnostics }, { destination: "trust", label: SECTION_LABELS.trust }] },
];

/** A period view retains its parent workbench's navigation highlight. */
export function activeNavigationDestination(destination: WorkspaceDestination): WorkspaceDestination {
  return destination === "inputs/capex/monthly" ? "inputs/capex" : destination === "inputs/opex/years" ? "inputs/opex" : destination;
}

/** Short links people can type or bookmark; the canonical hash is what the app keeps in the address bar. */
const ALIASES: Readonly<Record<string, string>> = {
  capex: "inputs/capex", "capex/monthly": "inputs/capex/monthly", opex: "inputs/opex", "opex/years": "inputs/opex/years",
};

/** The canonical form of a hash (without the leading #): `capex` -> `inputs/capex`; anything else is returned unchanged. */
export function canonicalHash(hash: string): string {
  const raw = hash.replace(/^#/, "");
  return Object.prototype.hasOwnProperty.call(ALIASES, raw) ? ALIASES[raw] : raw;
}

export interface WorkspaceRoute {
  section: WorkspaceSection;
  input: InputDestination | null;
  /** Which view of the CAPEX / OPEX workbench; `lines` for every other destination. */
  view: CostView;
  destination: WorkspaceDestination;
}

export function workspaceRoute(hash: string): WorkspaceRoute {
  const raw = canonicalHash(hash);
  if (raw === "inputs/capex/monthly") return { section: "inputs", input: "capex", view: "monthly", destination: raw };
  if (raw === "inputs/opex/years") return { section: "inputs", input: "opex", view: "years", destination: raw };
  const input = raw.startsWith("inputs/") ? raw.slice(7) : "";
  if (Object.prototype.hasOwnProperty.call(INPUT_DESTINATIONS, input)) {
    return { section: "inputs", input: input as InputDestination, view: "lines", destination: raw as WorkspaceDestination };
  }
  const section = isWorkspaceSection(raw) ? raw : "overview";
  return { section, input: null, view: "lines", destination: section };
}

/** True for the two dedicated cost workbenches. */
export function isCostWorkbench(route: WorkspaceRoute): route is WorkspaceRoute & { input: CostSheetId } {
  return route.input === "capex" || route.input === "opex";
}
