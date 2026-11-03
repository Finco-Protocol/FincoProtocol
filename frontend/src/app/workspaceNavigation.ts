import { isWorkspaceSection, type WorkspaceSection } from "./WorkspaceNav";

export const INPUT_DESTINATIONS = {
  project: { label: "Project & Timeline", target: "wf-inputs-setup" },
  technical: { label: "Technical & Production", target: "wf-inputs-grid" },
  capex: { label: "CAPEX", target: "wf-inputs-costs" },
  opex: { label: "OPEX", target: "wf-inputs-costs" },
  revenue: { label: "Revenue / PPA", target: "wf-inputs-revenue" },
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
