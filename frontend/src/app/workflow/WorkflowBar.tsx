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
import { RunFailureNotice } from "../RunFailureNotice";
import type { ConfirmedRun } from "../workspaceExtensions";
import type { RunsPayload } from "../types";
import { SAVE_ALL_EXCLUDES } from "../InputsGuide";
import { useSaveAllBridge } from "../saveAllBridge";
import { StatusNote, useCanonicalRead, useDirtyTotal, useReportPending, useUnresolvedLock, type StatusMessage } from "./workflowShared";

interface Props {
  project: string;
  freshness: string;
  protectedReference: boolean;
  contentHash: string;
  workbookVersion: string;
  reconciliationBlocked?: boolean;
  /** Presentation only: shown in the top bar. */
  projectName?: string;
  technology?: string;
  scenarioName?: string;
  onRan: (run: ConfirmedRun) => Promise<void>;
  onReload: () => void;
}

const LABEL: Record<string, string> = { CURRENT: "UP TO DATE", STALE: "OUTDATED", NOT_RUN: "NOT RUN" };
const MEANING: Record<string, string> = {
  CURRENT: "Results match the current inputs.",
  STALE: "Inputs changed after the Last Run; results show the prior Run.",
  NOT_RUN: "No committed Run yet.",
};

export function WorkflowBar({ project, freshness, protectedReference, contentHash, workbookVersion, onRan, onReload, reconciliationBlocked = false, projectName, technology, scenarioName }: Props) {
  const saveAll = useSaveAllBridge();
  const { total, breakdown, pendingKeys, confirmIfDirty } = useDirtyTotal();
  const fetcher = useCallback(() => fetchRuns(project), [project]);
  const read = useCanonicalRead<RunsPayload>(fetcher, [project]);
  const [status, setStatus] = useState<StatusMessage | null>(null);
  const [failure, setFailure] = useState<{ code?: string; message: string } | null>(null);
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
  const blockedReason = protectedReference ? "Templates cannot be run. Start a project from this template."
    : reconciliationBlocked ? "Refresh the confirmed Run views before starting another Run."
    : total > 0 ? `Save or cancel your ${total} unsaved edit${total === 1 ? "" : "s"} before running.`
      : pendingKeys.some((k) => k !== "run") ? "A save or change is still in progress or unresolved. Wait for it, or reload to reconcile, before running."
        : locked || resuming ? "The last Run outcome is not confirmed. Resume it, or reload to reconcile, before starting a new Run."
          : !contract ? "Run is unavailable until the run contract is loaded." : "";

  // Last committed Run identity (newest by time). A STALE result is the prior Run, so its id and date are always shown with the label.
  const runs = read.state === "ready" ? read.data.runs : [];
  const lastRun = runs.length ? runs.reduce((a, b) => (Date.parse(b.ran_at) > Date.parse(a.ran_at) ? b : a)) : null;
  const lastRunWhen = lastRun && !Number.isNaN(Date.parse(lastRun.ran_at)) ? new Date(lastRun.ran_at).toISOString().slice(0, 16).replace("T", " ") + " UTC" : "";

  async function run(resume = false) {
    if (inFlight.current || !contract || protectedReference) return;
    if (resume ? pending === null : Boolean(blockedReason)) return;
    inFlight.current = true;
    setRunning(true);
    setStatus(null);
    setFailure(null);
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
        : "Run committed. Results come from the saved Run only. Check Run Integrity and Credit findings before relying on them." });
      await onRan({ historyId: result.historyId, snapshotId: result.snapshotId, runIntentId: intent.id });
    } else {
      if (!result.retain) {
        clearRunIntent(project);
        setPending(null);
      }
      // A committed Run whose history cannot be read back needs a reload before anything else.
      setLocked(result.outcome === "HISTORY_UNAVAILABLE");
      // The typed outcome keeps its established status contract (conflict for an unreadable history, error otherwise) next to the guidance notice.
      setStatus({ tone: result.outcome === "HISTORY_UNAVAILABLE" ? "conflict" : "error", text: result.message });
      setFailure({ code: result.errorCode, message: result.message });
    }
    setRunning(false);
    inFlight.current = false;
  }

  const techLabel = technology ? technology.charAt(0).toUpperCase() + technology.slice(1) : "";
  const saveAllDisabled = total === 0 || saveAll.disabled || saveAll.run === null || running;
  return (
    <div className="wf-bar ci-bar" role="region" aria-label="Model status and actions" data-workflow-bar="true"
         data-bar-freshness={freshness} data-unsaved={total}
         data-dirty-keys={Object.keys(breakdown).join(",")} data-pending-keys={pendingKeys.join(",")}>
      <span className="ci-bar-id" data-bar-project="true">
        <strong>{projectName || project}</strong>
        {techLabel && <span className="ci-chip ci-chip-tech">{techLabel}</span>}
      </span>
      <label className="ci-bar-scenario">
        <span>Scenario</span>
        <select disabled aria-label="Active scenario" title="The active scenario is chosen in the Scenarios section." data-bar-scenario="true">
          <option>{scenarioName || "Base Case"}</option>
        </select>
      </label>
      {total > 0
        ? <span className="wf-dirty ci-state" role="status" data-unsaved-indicator="true">{total} unsaved edit{total === 1 ? "" : "s"}</span>
        : <span className="ci-state ci-saved" data-saved-indicator="true">Saved</span>}
      <span className="rx-badge ci-run-badge" data-run-state-label={freshness} title={MEANING[freshness] ?? ""}><strong>{LABEL[freshness] ?? freshness}</strong></span>
      {lastRun && (
        <span className="ci-lastrun" data-last-run-id={lastRun.history_id}>
          Run <code>{lastRun.history_id.slice(0, 8)}</code>{lastRunWhen && ` · ${lastRunWhen}`}{lastRun.active_scenario_name ? ` · ${lastRun.active_scenario_name}` : " · Base"}
        </span>
      )}
      <div className="wf-bar-actions">
        <button type="button" className="fm-btn" onClick={() => confirmIfDirty(onReload, { draftsOnly: true })} data-wf-reload="true">Reload</button>
        <button type="button" className="fm-btn ci-save-all" disabled={saveAllDisabled} data-bar-save-all="true" data-bar-save-all-total={total}
                title={saveAllDisabled && total > 0 ? saveAll.reason : "Saves every staged assumption, contract and cost-line change in one step. The model is not run. Financing collections are saved separately."}
                onClick={() => saveAll.run?.()}>
          {saveAll.saving ? "Saving…" : "Save changes"}
        </button>
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
      <p id="wf-run-hint" className={blockedReason || resuming ? "ci-hint" : "ci-hint rx-sr-only"}>
        {blockedReason || "Run is a separate, deliberate action: Save, scenario selection and comparison never execute the model."}
        {resuming && " Resuming asks the server for that Run's original result; it does not calculate again."}
      </p>
      <details className="ci-help" data-bar-help="true">
        <summary>How saving and running work</summary>
        <p className="fm-info-note" data-save-scope-note="true">
          Save All writes staged assumptions, contracts and cost lines in one step. Not included — saved separately: {SAVE_ALL_EXCLUDES.toLowerCase()}.
        </p>
        <p className="fm-info-note">{MEANING[freshness] ?? ""}</p>
      </details>
      <div style={{ flexBasis: "100%" }}><StatusNote status={status} />{failure && <RunFailureNotice {...failure} />}</div>
    </div>
  );
}
