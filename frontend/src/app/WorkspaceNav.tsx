import type { MouseEvent } from "react";

export type WorkspaceSection =
  | "overview" | "inputs" | "statements" | "results" | "analysis"
  | "financing" | "scenarios" | "diagnostics" | "trust";

/** Order and numbering follow the approved FINCO Model section model. */
export const WORKSPACE_SECTIONS: ReadonlyArray<{ id: WorkspaceSection; label: string; number: string }> = [
  { id: "inputs", label: "Inputs", number: "01" },
  { id: "statements", label: "Statements", number: "02" },
  { id: "financing", label: "Financing", number: "03" },
  { id: "results", label: "Results", number: "04" },
  { id: "scenarios", label: "Scenarios", number: "05" },
  { id: "analysis", label: "Analysis", number: "06" },
  { id: "diagnostics", label: "Model checks", number: "07" },
  { id: "trust", label: "Trust", number: "08" },
];

export const SECTION_LABELS: Record<WorkspaceSection, string> = {
  overview: "Overview",
  ...Object.fromEntries(WORKSPACE_SECTIONS.map((s) => [s.id, s.label])),
} as Record<WorkspaceSection, string>;

const SECTION_IDS = ["overview", ...WORKSPACE_SECTIONS.map((s) => s.id)] as WorkspaceSection[];

export function isWorkspaceSection(value: string): value is WorkspaceSection {
  return (SECTION_IDS as string[]).includes(value);
}

/**
 * Section navigation for the live workspace.  Every item is a real in-page link
 * (`#section`) so open-in-new-tab, copy-link, Back/Forward and refresh behave;
 * unmodified primary clicks are routed through `onNavigate` without a reload.
 */
export function WorkspaceNav({ active, onNavigate }: { active: WorkspaceSection; onNavigate: (section: WorkspaceSection) => void }) {
  const go = (event: MouseEvent<HTMLAnchorElement>, id: WorkspaceSection) => {
    if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    onNavigate(id);
  };
  return (
    <nav className="fm-nav" aria-label="Model sections" data-workspace-nav="true">
      {WORKSPACE_SECTIONS.map(({ id, label, number }) => (
        <a
          key={id}
          href={`#${id}`}
          className={active === id ? "active" : ""}
          aria-current={active === id ? "page" : undefined}
          onClick={(event) => go(event, id)}
        >
          <span className="fm-nav-num">{number}</span>{label}
        </a>
      ))}
    </nav>
  );
}
