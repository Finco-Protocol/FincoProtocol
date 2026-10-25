import React, { useId } from "react";
import type { ProjectContext } from "./FincoShell";
import "./source-authority.css";

export type SourceAuthorityState = "draft" | "saved" | "reference" | "fixed";

type SourceAuthorityDrawerProps = {
  project: ProjectContext;
  scenarioId: string;
  selection: string;
  state: SourceAuthorityState;
  sourceLabel: string;
  valueLabel?: string;
  relatedHref: string;
  relatedLabel: string;
  note: string;
};

const stateLabels: Record<SourceAuthorityState, string> = {
  draft: "Unsaved changes in this preview",
  saved: "Saved in this browser preview only",
  reference: "Protected reference · read-only",
  fixed: "Fixed example value",
};

export default function SourceAuthorityDrawer({
  project,
  scenarioId,
  selection,
  state,
  sourceLabel,
  valueLabel,
  relatedHref,
  relatedLabel,
  note,
}: SourceAuthorityDrawerProps) {
  const contentId = useId();

  return <details className="fm-source-authority" data-testid="source-authority-drawer">
    <summary aria-controls={contentId}>Input details · {selection}</summary>
    <div id={contentId} className="fm-source-authority-content">
      <dl>
        <div><dt>Project / scenario</dt><dd>{project.name} · {scenarioId}</dd></div>
        <div><dt>Selected item</dt><dd>{selection}{valueLabel ? ` · ${valueLabel}` : ""}</dd></div>
        <div><dt>Editing status</dt><dd>{stateLabels[state]}</dd></div>
        <div><dt>Example source</dt><dd>{sourceLabel}</dd></div>
      </dl>
      <p>{note}</p>
      <a href={relatedHref}>{relatedLabel}</a>
      <small>This link opens a related section only; it does not show how the value was calculated.</small>
    </div>
  </details>;
}
