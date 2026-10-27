import { useCallback, useEffect, useRef, useState } from "react";
import "../../styles/rcm-analysis.css";
import { useDirtyTotal } from "../workflow/workflowShared";
import { applyGoalSeek, fetchGoalSeekCatalog, fetchGoalSeekTargets, solveGoalSeek, type ApplyOutcome } from "./analysisApi";
import { TierNote } from "./shared";
import type { AdapterFailure, GoalSeekApplied, GoalSeekCatalog, GoalSeekPreview, TypedGoalSeekTarget } from "./types";

const FAILURE_TEXT: Record<string, string> = {
  MODEL_BUSY: "The model engine is busy. Wait a moment and solve again.",
  CONTEXT_CHANGED: "The project changed while the solve was running, so the result was discarded. Solve again.",
};

/** Analysis > Goal Seek (tender pricing): solve the tariff that reaches a target return.  The solve is a PREVIEW — it never
 *  changes the Working Copy.  "Apply to Working Copy" is the only write (canonical CAS); it makes the Last Run STALE and never runs
 *  the model.  Save and Run stay separate, deliberate actions. */
export function GoalSeekPanel({ project, workbookHash, onApplied }: { project: string; workbookHash: string; onApplied: () => void }) {
  const [catalog, setCatalog] = useState<GoalSeekCatalog | null>(null);
  const [targets, setTargets] = useState<TypedGoalSeekTarget[] | null>(null);
  const [failure, setFailure] = useState<AdapterFailure | null>(null);
  const [metric, setMetric] = useState("project_irr");
  const [target, setTarget] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<{ code: string; message: string } | null>(null);
  const [preview, setPreview] = useState<GoalSeekPreview | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [applying, setApplying] = useState(false);
  const [applied, setApplied] = useState<GoalSeekApplied | null>(null);
  const [applyIssue, setApplyIssue] = useState<{ kind: "refused" | "unknown"; message: string } | null>(null);
  const abort = useRef<AbortController | null>(null);
  const sequence = useRef(0);
  const applyLock = useRef(false);
  const { total: unsaved, pendingKeys } = useDirtyTotal();

  useEffect(() => {
    let live = true;
    void fetchGoalSeekCatalog(project).then((result) => {
      if (!live) return;
      if (result.ok) setCatalog(result); else setFailure(result);
    });
    void fetchGoalSeekTargets(project).then((result) => { if (live && result.ok) setTargets(result.metrics); });
    return () => { live = false; abort.current?.abort(); };
  }, [project]);

  const typed = targets?.find((t) => t.key === metric);
  const solve = useCallback(async () => {
    if (!catalog || !typed || busy) return;
    abort.current?.abort();
    const controller = new AbortController();
    abort.current = controller;
    const mine = ++sequence.current;
    setBusy(true); setError(null); setApplied(null); setApplyIssue(null); setConfirming(false);
    const result = await solveGoalSeek({ project, metric, target: target.trim(), unit: typed.target_unit }, controller.signal);
    if (mine !== sequence.current) return;
    setBusy(false);
    if (result.ok) setPreview(result);
    else { setPreview(null); setError({ code: result.code, message: FAILURE_TEXT[result.code] ?? result.message ?? "Goal Seek could not be run. Nothing was changed." }); }
  }, [catalog, typed, busy, project, metric, target]);

  async function confirmApply() {
    if (!preview?.apply || applyLock.current) return;
    applyLock.current = true;
    setApplying(true); setApplyIssue(null);
    const outcome: ApplyOutcome = await applyGoalSeek(project, preview.apply);
    setApplying(false);
    if (outcome.kind === "applied") {
      setApplied(outcome.applied); setPreview(null); setConfirming(false);
      applyLock.current = false;
      onApplied();                                     // the workspace re-reads its tokens and freshness
      return;
    }
    setConfirming(false);
    setApplyIssue({ kind: outcome.kind, message: outcome.message });
    // an ambiguous outcome keeps the lock: the workspace must be reloaded to reconcile, never retried
    if (outcome.kind === "refused") applyLock.current = false;
  }

  if (failure) {
    return (
      <section className="rx-card" data-goal-seek-state={failure.code} aria-labelledby="rcm-gs-title">
        <h2 id="rcm-gs-title">Goal Seek — tender pricing</h2>
        <p className="rx-empty" role="alert" data-goal-seek-unavailable="true">
          {failure.code === "PROTECTED_REFERENCE" ? "Templates are read-only. Start a project from this template to solve a tariff." : failure.message || "Goal Seek is not available for this project."}
        </p>
        <p className="rx-note">Goal Seek is not available for this project type yet.</p>
      </section>
    );
  }
  if (!catalog || !targets) return <section className="rx-card"><p className="rx-boot-loading" role="status">Loading Goal Seek…</p></section>;

  const outdated = Boolean(preview?.apply && workbookHash && preview.apply.content_hash && workbookHash !== preview.apply.content_hash);
  const blocked = unsaved > 0 || pendingKeys.length > 0;
  const result = preview?.result;

  return (
    <section className="rx-card rcm-analysis" data-goal-seek-panel="true" aria-labelledby="rcm-gs-title">
      <h2 id="rcm-gs-title">Goal Seek — tender pricing <span className="rcm-badge">PREVIEW · NOT APPLIED</span></h2>
      <TierNote vertical={catalog.vertical} />
      <p className="rx-note">
        Find the {catalog.variable?.label.toLowerCase() ?? "tariff"} that reaches a target return. The solver runs the model on the <strong>saved project</strong>{" "}
        (at most {catalog.budgets.max_model_evaluations} model evaluations). A solve changes nothing until you press Apply; Apply makes the Last Run STALE and you Run deliberately.
      </p>
      {!catalog.available ? (
        <p className="rx-empty" role="alert" data-goal-seek-unavailable="true">{catalog.reason}</p>
      ) : (
        <form className="rcm-controls" onSubmit={(e) => { e.preventDefault(); void solve(); }} data-goal-seek-form="true">
          <label className="rcm-field">Target metric
            <select value={metric} data-gs-metric="true" onChange={(e) => { setMetric(e.target.value); setTarget(""); setPreview(null); setError(null); }}>
              {targets.map((m) => <option key={m.key} value={m.key}>{m.label}</option>)}
            </select>
          </label>
          <label className="rcm-field">{typed?.input_label ?? "Target"}
            <input value={target} inputMode="decimal" data-gs-target="true" data-gs-target-unit={typed?.target_unit} placeholder={`e.g. ${typed?.example ?? ""}`} onChange={(e) => setTarget(e.target.value)} />
            <span className="rx-note">Starting {catalog.variable?.label}: {catalog.current_tariff?.toFixed(2)} {catalog.variable?.unit}</span>
          </label>
          <div className="rcm-controls-actions">
            <button type="submit" className="rx-button" disabled={busy || !target.trim()} data-gs-solve="true" aria-busy={busy}>{busy ? "Solving…" : "Solve (preview)"}</button>
            {busy && <button type="button" className="rx-button rx-button-secondary" data-gs-cancel="true" onClick={() => abort.current?.abort()}>Cancel</button>}
          </div>
        </form>
      )}
      {busy && <p className="rx-note" role="status" data-gs-progress="true">Solving with the model — nothing is saved.</p>}
      {error && <p className="rx-status rx-status-error" role="alert" data-gs-error={error.code}>{error.message}</p>}

      {result && preview && (
        <div className="rcm-result" data-gs-result={result.status} data-gs-preview="true">
          <p className="rcm-status-line">
            <span className={`rcm-chip ${result.solved ? "ok" : "warn"}`} data-gs-status="true">{result.status.replace(/_/g, " ")}</span>
            <span className="rcm-badge" data-gs-committed="false">PREVIEW — project unchanged</span>
          </p>
          <p data-gs-message="true">{result.message}</p>
          <dl className="rcm-facts">
            <div><dt>Target</dt><dd>{result.target_metric_label} = {result.target_display}</dd></div>
            <div><dt>Starting {result.variable.label.toLowerCase()}</dt><dd data-gs-started="true">{result.started_from_display}</dd></div>
            {result.solved_display && <div><dt>Solved {result.variable.label.toLowerCase()}</dt><dd data-gs-solved="true">{result.solved_display}</dd></div>}
            {result.delta_display && <div><dt>Movement</dt><dd data-gs-delta="true">{result.delta_display}{result.variance_display ? ` · ${result.variance_display}` : ""}</dd></div>}
            {result.achieved_display && <div><dt>Achieved {result.target_metric_label}</dt><dd data-gs-achieved="true">{result.achieved_display}</dd></div>}
            {result.error_display && <div><dt>Target error</dt><dd data-gs-error-pp="true">{result.error_display}</dd></div>}
            <div><dt>Iterations · model runs</dt><dd data-gs-effort="true">{result.iterations} · {result.model_evaluations}</dd></div>
            <div><dt>Explored range</dt><dd>{result.lower_bound.toFixed(2)} – {result.upper_bound.toFixed(2)} {result.variable.unit}</dd></div>
          </dl>
          <p className="rx-note">{preview.provenance}</p>

          {preview.apply && (
            <div className="rcm-apply" data-gs-apply-box="true">
              {outdated && <p className="rx-banner rx-banner-stale" role="status" data-outdated-banner="true">The project changed after this solve. Solve again before applying.</p>}
              {blocked && <p className="rx-status rx-status-conflict" role="status" data-gs-blocked="true">
                Apply is disabled while this workspace has {unsaved > 0 ? `${unsaved} unsaved edit${unsaved === 1 ? "" : "s"}` : "a change in progress"} — Save or discard first, then solve again.</p>}
              {!confirming ? (
                <button type="button" className="rx-button" data-gs-apply="true" disabled={outdated || blocked || applying || Boolean(applyIssue && applyIssue.kind === "unknown")}
                        onClick={() => setConfirming(true)}>Apply to project…</button>
              ) : (
                <div role="group" aria-label="Confirm apply" className="rcm-confirm" data-gs-confirm="true">
                  <p>Write <strong>{result.solved_display}</strong> to the project tariff? The results become out of date; nothing is run.</p>
                  <button type="button" className="rx-button" data-gs-confirm-apply="true" disabled={applying} aria-busy={applying} onClick={() => void confirmApply()}>{applying ? "Applying…" : "Confirm apply"}</button>{" "}
                  <button type="button" className="rx-button rx-button-secondary" disabled={applying} onClick={() => setConfirming(false)}>Cancel</button>
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {applyIssue && (
        <p className={`rx-status ${applyIssue.kind === "unknown" ? "rx-status-conflict" : "rx-status-error"}`} role="alert" data-gs-apply-issue={applyIssue.kind}>
          {applyIssue.message}
          {applyIssue.kind === "unknown" && <> <button type="button" className="rx-button rx-button-secondary" onClick={() => window.location.reload()}>Reload the workspace</button></>}
        </p>
      )}
      {applied && (
        <p className="rx-status rx-status-saved" role="status" data-gs-applied="true" data-run-state={applied.run_state}>
          {applied.message} Next: open the status bar and press Run when ready.
        </p>
      )}
    </section>
  );
}
