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
  draft: "Local demo draft · save state not recorded",
  saved: "Demo saved · this browser session only",
  reference: "Protected reference · read-only",
  fixed: "Fixed synthetic reference",
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
    <summary aria-controls={contentId}>Source &amp; status · {selection}</summary>
    <div id={contentId} className="fm-source-authority-content">
      <dl>
        <div><dt>Project / scenario</dt><dd>{project.name} · {scenarioId}</dd></div>
        <div><dt>Selected item</dt><dd>{selection}{valueLabel ? ` · ${valueLabel}` : ""}</dd></div>
        <div><dt>State</dt><dd>{stateLabels[state]}</dd></div>
        <div><dt>Displayed source</dt><dd>{sourceLabel}</dd></div>
      </dl>
      <p>{note}</p>
      <a href={relatedHref}>{relatedLabel}</a>
      <small>Navigation association only; verified calculation lineage is not available.</small>
    </div>
  </details>;
}
