// WF-React-2 — one status and action bar for every editable section.
//
// Save stays inside each editor; this bar is the single place that shows the
// Run state (CURRENT / STALE / NOT RUN), the number of unsaved edits, a Reload
// action and the one explicit Run action.  Run is refused while edits are
// unsaved, so the model can never silently run against a different state than
// the one on screen, and Save never triggers it.
//
// D-029: every deliberate Run carries one UUIDv4 intent.  After an ambiguous
// outcome (lost response, in-progress, reload) the SAME intent is resumed with
// its ORIGINAL binding; the server returns the original committed result and
// never recalculates.  A definitive failure consumes the intent.

import { useCallback, useEffect, useRef, useState } from "react";
import { fetchRuns, runModel } from "../api";
import { clearRunIntent, createRunIntent, loadRunIntent, type RunIntent } from "../runIntent";
import type { RunsPayload } from "../types";
import { StatusNote, useCanonicalRead, useDirtyTotal, useReportPending, useUnresolvedLock, type StatusMessage } from "./workflowShared";

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
  const { total, breakdown, pendingKeys, confirmIfDirty } = useDirtyTotal();
  const fetcher = useCallback(() => fetchRuns(project), [project]);
  const read = useCanonicalRead<RunsPayload>(fetcher, [project]);
  const [status, setStatus] = useState<StatusMessage | null>(null);
  const [running, setRunning] = useState(false);
  const [locked, setLocked] = useUnresolvedLock("run");
  // The unresolved intent for this project (kept across reloads; bounded client storage, no tokens).
  const [pending, setPending] = useState<RunIntent | null>(() => loadRunIntent(project));
  useEffect(() => {
    const restored = loadRunIntent(project);
    setPending(restored);
    if (restored) setLocked(true);
  }, [project, setLocked]);
  // Synchronous guard: two activations in the same tick (double click, repeated
  // Enter) must produce at most one canonical Run request.
  const inFlight = useRef(false);
  // A Run in flight or with an unknown outcome also blocks every other mutation's
  // "Run" path and is visible to the rest of the workspace.
  useReportPending("run", running || locked);

  const contract = read.state === "ready" ? read.data.run_contract : null;
  // A NEW Run keeps every original guard.  While an earlier Run is unconfirmed, the primary Run action stays
  // locked (as before) and a separate Resume action re-sends that Run's ORIGINAL intent and binding: it can only
  // replay or refuse, never calculate against today's draft, so unsaved edits do not block it.
  const resuming = pending !== null;
  const blockedReason = protectedReference ? "Protected references cannot be run. Create a Working Copy."
    : total > 0 ? `Save or cancel your ${total} unsaved edit${total === 1 ? "" : "s"} before running.`
      : pendingKeys.some((k) => k !== "run") ? "A save or change is still in progress or unresolved. Wait for it, or reload to reconcile, before running."
        : locked || resuming ? "The last Run outcome is not confirmed. Resume it, or reload to reconcile, before starting a new Run."
          : !contract ? "Run is unavailable until the run contract is loaded." : "";

  async function run(resume = false) {
    if (inFlight.current || !contract || protectedReference) return;
    if (resume ? pending === null : Boolean(blockedReason)) return;
    inFlight.current = true;
    setRunning(true);
    setStatus(null);
    let intent = pending;
    if (!intent) {
      try {
        intent = createRunIntent(project, contentHash, workbookVersion);
      } catch {
        setRunning(false);
        inFlight.current = false;
        setStatus({ tone: "error", text: "Run could not start: this browser cannot create a secure Run key. Nothing was run." });
        return;
      }
      setPending(intent);
    }
    const result = await runModel({ runUrl: contract.url, csrfToken: contract.csrf_token, project, intent });
    setRunning(false);
    inFlight.current = false;
    if ("kind" in result) {
      // Ambiguous: keep the intent so the next press resumes it with the original binding.
      setLocked(true);
      setStatus({ tone: "conflict", text: result.message });
    } else if (result.ok) {
      clearRunIntent(project);
      setPending(null);
      setLocked(false);
      setStatus({ tone: "ok", text: result.outcome === "REPLAYED"
        ? "This Run was already committed; its original result is shown. Nothing was recalculated."
        : "Run committed from the canonical engine. Results come from the persisted evidence only." });
      onRan();
    } else {
      if (!result.retain) {
        clearRunIntent(project);
        setPending(null);
      }
      // A committed Run whose history cannot be read back needs a reload before anything else.
      setLocked(result.outcome === "HISTORY_UNAVAILABLE");
      setStatus({ tone: result.outcome === "HISTORY_UNAVAILABLE" ? "conflict" : "error", text: result.message });
    }
  }

  return (
    <div className="wf-bar" role="region" aria-label="Model status and actions" data-workflow-bar="true"
         data-bar-freshness={freshness} data-unsaved={total}
         data-dirty-keys={Object.keys(breakdown).join(",")} data-pending-keys={pendingKeys.join(",")}>
      <span className="rx-badge" data-run-state-label={freshness}><strong>{LABEL[freshness] ?? freshness}</strong></span>
      <span className="fm-info-note" style={{ margin: 0 }}>{MEANING[freshness] ?? ""}</span>
      {total > 0 && <span className="wf-dirty" role="status" data-unsaved-indicator="true">{total} unsaved edit{total === 1 ? "" : "s"}</span>}
      <div className="wf-bar-actions">
        <button type="button" className="fm-btn" onClick={() => confirmIfDirty(onReload, { draftsOnly: true })} data-wf-reload="true">Reload</button>
        <button type="button" className="fm-btn fm-btn-primary" disabled={running || Boolean(blockedReason)}
                aria-describedby="wf-run-hint" data-wf-run="true" onClick={() => void run()}>
          {running ? "Run in progress…" : "Run model"}
        </button>
        {resuming && !protectedReference && contract && (
          <button type="button" className="fm-btn" disabled={running}
                  aria-describedby="wf-run-hint" data-wf-resume="true" onClick={() => void run(true)}>
            Resume last Run
          </button>
        )}
      </div>
      <p id="wf-run-hint" className="fm-info-note" style={{ margin: 0, flexBasis: "100%" }}>
        {blockedReason || "Run is a separate, deliberate action: Save, scenario selection and comparison never execute the model."}
        {resuming && " Resuming asks the server for that Run's original result; it does not calculate again."}
      </p>
      <div style={{ flexBasis: "100%" }}><StatusNote status={status} /></div>
    </div>
  );
}
