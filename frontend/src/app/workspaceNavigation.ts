import { isWorkspaceSection, type WorkspaceSection } from "./WorkspaceNav";

export const INPUT_DESTINATIONS = {
  project: { label: "Project & Timeline", target: "wf-inputs-setup" },
  technical: { label: "Technical & Production", target: "wf-inputs-grid" },
  capex: { label: "CAPEX", target: "wf-inputs-costs" },
  opex: { label: "OPEX", target: "wf-inputs-costs" },
  revenue: { label: "Revenue / PPA", target: "wf-inputs-revenue" },
} as const;
export type InputDestination = keyof typeof INPUT_DESTINATIONS;
export type WorkspaceDestination = WorkspaceSection | `inputs/${InputDestination}`;

export function workspaceRoute(hash: string): { section: WorkspaceSection; input: InputDestination | null; destination: WorkspaceDestination } {
  const raw = hash.replace(/^#/, "");
  const input = raw.startsWith("inputs/") ? raw.slice(7) : "";
  if (Object.prototype.hasOwnProperty.call(INPUT_DESTINATIONS, input)) {
    return { section: "inputs", input: input as InputDestination, destination: raw as WorkspaceDestination };
  }
  const section = isWorkspaceSection(raw) ? raw : "overview";
  return { section, input: null, destination: section };
}
