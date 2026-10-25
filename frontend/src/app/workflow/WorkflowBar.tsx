// WF-React-2 — one status and action bar for every editable section.
//
// Save stays inside each editor; this bar is the single place that shows the
// Run state (CURRENT / STALE / NOT RUN), the number of unsaved edits, a Reload
// action and the one explicit Run action.  Run is refused while edits are
// unsaved, so the model can never silently run against a different state than
// the one on screen, and Save never triggers it.

import { useCallback, useState } from "react";
import { fetchRuns, runModel } from "../api";
import type { RunsPayload } from "../types";
import { StatusNote, useCanonicalRead, useDirtyTotal, type StatusMessage } from "./workflowShared";

interface Props {
  project: string;
  freshness: string;
  protectedReference: boolean;
  contentHash: string;
  workbookVersion: string;
  onRan: () => void;
  onReload: () => void;
}

const LABEL: Record<string, string> = { CURRENT: "CURRENT", STALE: "STALE", NOT_RUN: "NOT RUN" };
const MEANING: Record<string, string> = {
  CURRENT: "Results match the current inputs.",
  STALE: "Inputs changed after the Last Run; results show the prior Run.",
  NOT_RUN: "No committed Run yet.",
};

export function WorkflowBar({ project, freshness, protectedReference, contentHash, workbookVersion, onRan, onReload }: Props) {
  const { total } = useDirtyTotal();
  const fetcher = useCallback(() => fetchRuns(project), [project]);
  const read = useCanonicalRead<RunsPayload>(fetcher, [project]);
  const [status, setStatus] = useState<StatusMessage | null>(null);
  const [running, setRunning] = useState(false);
  const [locked, setLocked] = useState(false);

  const contract = read.state === "ready" ? read.data.run_contract : null;
  const blockedReason = protectedReference ? "Protected references cannot be run. Create a Working Copy."
    : total > 0 ? `Save or cancel your ${total} unsaved edit${total === 1 ? "" : "s"} before running.`
      : locked ? "The last Run outcome is unknown. Reload to reconcile first."
        : !contract ? "Run is unavailable until the run contract is loaded." : "";

  async function run() {
    if (!contract || blockedReason) return;
    setRunning(true);
    setStatus(null);
    const result = await runModel({
      runUrl: contract.url, csrfToken: contract.csrf_token, project, contentHash, workbookVersion,
    });
    setRunning(false);
    if ("kind" in result) {
      setLocked(true);
      setStatus({ tone: "conflict", text: result.message });
    } else if (result.ok) {
      setStatus({ tone: "ok", text: "Run committed from the canonical engine. Results come from the persisted evidence only." });
      onRan();
    } else {
      setStatus({ tone: "error", text: result.message });
    }
  }

  return (
    <div className="wf-bar" role="region" aria-label="Model status and actions" data-workflow-bar="true"
         data-bar-freshness={freshness} data-unsaved={total}>
      <span className="rx-badge" data-run-state-label={freshness}><strong>{LABEL[freshness] ?? freshness}</strong></span>
      <span className="fm-info-note" style={{ margin: 0 }}>{MEANING[freshness] ?? ""}</span>
      {total > 0 && <span className="wf-dirty" role="status" data-unsaved-indicator="true">{total} unsaved edit{total === 1 ? "" : "s"}</span>}
      <div className="wf-bar-actions">
        <button type="button" className="fm-btn" onClick={onReload} data-wf-reload="true">Reload</button>
        <button type="button" className="fm-btn fm-btn-primary" disabled={running || Boolean(blockedReason)}
                aria-describedby="wf-run-hint" data-wf-run="true" onClick={() => void run()}>
          {running ? "Run in progress…" : "Run model"}
        </button>
      </div>
      <p id="wf-run-hint" className="fm-info-note" style={{ margin: 0, flexBasis: "100%" }}>
        {blockedReason || "Run is a separate, deliberate action: Save, scenario selection and comparison never execute the model."}
      </p>
      <div style={{ flexBasis: "100%" }}><StatusNote status={status} /></div>
    </div>
  );
}
