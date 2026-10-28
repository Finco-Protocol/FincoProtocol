import { useEffect, useRef, useState } from "react";
import "../../styles/rcm-analysis.css";
import { fetchScenarios } from "../api";
import { FriendlyError } from "../productLanguage";
import { useReportDirty, useSingleFlight } from "../workflow/workflowShared";
import { commitWhatIf, fetchWhatIfOptions, fetchWhatIfPreview } from "./api";
import type { WhatIfCandidate, WhatIfOptions, WhatIfPreview } from "./types";

const fmt = (n: number, unit: string) => `${n.toLocaleString("en-GB", { maximumFractionDigits: 4 })}${unit === "x" ? "x" : unit ? ` ${unit}` : ""}`;

/** Analysis > What-if.  Three separate steps that never blur: PREVIEW (reads, writes nothing, is not a Run) → CREATE the scenario
 *  (one assumption changed, saved NOT RUN) → RUN it deliberately in Scenarios, then compare in Run history.  The preview shows the
 *  assumption change only: no projected KPI exists until the new scenario has been run. */
export function WhatIfPanel({ project, onCreated }: { project: string; onCreated: () => void }) {
  const [options, setOptions] = useState<WhatIfOptions | null>(null);
  const [failure, setFailure] = useState<{ code: string; message?: string } | null>(null);
  const [checkId, setCheckId] = useState("");
  const [value, setValue] = useState("");
  const [name, setName] = useState("");
  const [preview, setPreview] = useState<{ data: WhatIfPreview["preview"]; key: string } | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState<"" | "preview" | "create">("");
  const [error, setError] = useState<{ code: string; message?: string } | null>(null);
  const [outcome, setOutcome] = useState<{ tone: "ok" | "unknown"; text: string } | null>(null);
  const singleFlight = useSingleFlight();
  const seq = useRef(0);

  const load = () => {
    const mine = ++seq.current;
    void fetchWhatIfOptions(project).then((result) => {
      if (mine !== seq.current) return;
      if (result.ok) { setOptions(result); setFailure(null); setCheckId((c) => c || result.candidates.find((x) => x.eligible)?.check_id || ""); }
      else setFailure(result);
    });
  };
  useEffect(load, [project]);   // eslint-disable-line react-hooks/exhaustive-deps

  const candidate: WhatIfCandidate | undefined = options?.candidates.find((c) => c.check_id === checkId);
  const draftKey = `${checkId}|${value}|${name}`;
  const outdated = preview !== null && preview.key !== draftKey;
  useReportDirty("whatif-draft", value.trim() || name.trim() ? 1 : 0);

  const runPreview = () => singleFlight(async () => {
    if (!candidate) return;
    setBusy("preview"); setError(null); setOutcome(null); setConfirmed(false);
    const result = await fetchWhatIfPreview({ project, checkId, value, name });
    setBusy("");
    if (result.ok) setPreview({ data: result.preview, key: draftKey }); else { setPreview(null); setError(result); }
  });

  const create = () => singleFlight(async () => {
    if (!preview || outdated || !confirmed) return;
    setBusy("create"); setError(null);
    const result = await commitWhatIf(preview.data.commit.url, project, preview.data.token);
    if (result.kind === "created") {
      // Verify THIS scenario exists in a fresh read before saying so.
      const fresh = await fetchScenarios(project);
      const found = fresh.ok === true && fresh.scenarios.some((s) => s.scenario_id === result.scenarioId && !s.is_base_case);
      setBusy("");
      if (found) {
        setOutcome({ tone: "ok", text: `Scenario “${preview.data.scenario_name}” was created and confirmed. It has not been run: open Scenarios, select it and press Run model, then compare it with the Base Case in Run history.` });
        setPreview(null); setValue(""); setName(""); setConfirmed(false); onCreated();
      } else setOutcome({ tone: "unknown", text: "The scenario was reported as created but could not be confirmed. Check Scenarios before creating it again." });
      return;
    }
    setBusy("");
    if (result.kind === "refused") { setError({ code: result.code }); return; }
    setOutcome({ tone: "unknown", text: "We could not confirm whether the scenario was created. Check Scenarios before creating it again." });
  });

  if (failure) return <section className="rx-card" data-whatif-state="error"><h2>What-if</h2><FriendlyError code={failure.code} message={failure.message} /></section>;
  if (!options) return <p className="rx-boot-loading" role="status" data-whatif-state="loading">Loading What-if…</p>;
  const eligible = options.candidates.filter((c) => c.eligible);

  return (
    <section className="rx-card rcm-analysis" data-whatif-panel="true" data-whatif-state="ready" aria-label="What-if">
      <h2>What-if <span className="rcm-badge" data-ephemeral-badge="true">PREVIEW IS NOT A RUN</span></h2>
      <p className="rx-note">Change one assumption in a new scenario to see how the project could respond. {options.semantics.note}</p>
      <ol className="rx-note" data-whatif-steps="true">
        <li><strong>Preview</strong> — shows the change; saves nothing and calculates nothing.</li>
        <li><strong>Create the scenario</strong> — saved as “not run”; your Base Case and every earlier Run stay exactly as they are.</li>
        <li><strong>Run it</strong> in Scenarios, then <strong>compare</strong> in Run history.</li>
      </ol>
      {options.run_state === "NOT_RUN" && <p className="rx-empty" role="status" data-whatif-unavailable="not-run">Run the model first: a What-if starts from the findings of a saved Run.</p>}
      {options.run_state !== "NOT_RUN" && eligible.length === 0 && (
        <p className="rx-empty" role="status" data-whatif-unavailable="none">What-if is not available for this project{options.candidates[0]?.reason ? "" : " type"} yet. It supports Solar and Wind projects with a single senior loan.</p>
      )}
      {options.run_state === "STALE" && <p className="rx-banner rx-banner-stale" role="status">Results outdated — the findings below describe the earlier Run, not the inputs as saved now.</p>}
      {eligible.length > 0 && (
        <form className="rcm-controls" onSubmit={(e) => { e.preventDefault(); void runPreview(); }}>
          <label className="rcm-field">Based on finding
            <select value={checkId} data-whatif-finding="true" onChange={(e) => { setCheckId(e.target.value); setPreview(null); setValue(""); }}>
              {eligible.map((c) => <option key={c.check_id} value={c.check_id}>{c.finding} · {c.finding_status}</option>)}
            </select>
          </label>
          <p className="rx-note" data-whatif-assumption="true">Assumption changed: <strong>{candidate?.assumption}</strong>{candidate?.original != null ? <> · currently <strong>{fmt(candidate.original, candidate.unit)}</strong></> : null}</p>
          <label className="rcm-field">New value{candidate?.unit ? ` (${candidate.unit})` : ""}
            <input inputMode="decimal" value={value} data-whatif-value="true" onChange={(e) => setValue(e.target.value)} />
          </label>
          <label className="rcm-field">Scenario name
            <input value={name} maxLength={80} data-whatif-name="true" onChange={(e) => setName(e.target.value)} />
          </label>
          <div className="rcm-controls-actions">
            <button type="submit" className="rx-button" data-whatif-preview="true" disabled={busy !== "" || !candidate || !value.trim() || !name.trim()}>
              {busy === "preview" ? "Preparing…" : "Preview the change (nothing saved)"}</button>
          </div>
        </form>
      )}
      {error && <FriendlyError code={error.code} message={error.message} />}
      {preview && (
        <div className="rcm-result" data-whatif-preview-result={outdated ? "outdated" : "current"}>
          {outdated && <p className="rx-banner rx-banner-stale" role="status" data-whatif-outdated="true">OUTDATED — the inputs above changed after this preview. Preview again.</p>}
          <dl className="rcm-facts">
            <div><dt>Assumption</dt><dd>{candidate?.assumption}</dd></div>
            <div><dt>Current value</dt><dd data-whatif-original="true">{fmt(preview.data.assumption.original, preview.data.assumption.unit)}</dd></div>
            <div><dt>New value</dt><dd data-whatif-proposed="true">{fmt(preview.data.assumption.proposed, preview.data.assumption.unit)}</dd></div>
            <div><dt>Change</dt><dd data-whatif-delta="true">{preview.data.assumption.delta >= 0 ? "+" : ""}{fmt(preview.data.assumption.delta, preview.data.assumption.unit)}</dd></div>
            <div><dt>New scenario</dt><dd>{preview.data.scenario_name} <span className="rx-note">(not created yet)</span></dd></div>
          </dl>
          {preview.data.stale && <p className="rx-banner rx-banner-stale" role="status">Results outdated — this is based on the inputs as saved now, not on recalculated results.</p>}
          <p className="rx-note" data-whatif-limits="true">{preview.data.semantics.note}</p>
          <div className="rcm-confirm">
            <label className="rcm-check"><input type="checkbox" checked={confirmed} data-whatif-confirm="true" disabled={outdated || busy !== ""} onChange={(e) => setConfirmed(e.target.checked)} />
              {" "}I confirm creating a separate scenario with exactly this change. It will not be run.</label>
            <button type="button" className="rx-button" data-whatif-create="true" disabled={!confirmed || outdated || busy !== ""} onClick={() => void create()}>
              {busy === "create" ? "Creating…" : "Create the What-if scenario"}</button>
          </div>
        </div>
      )}
      {outcome && <p className={`rx-status ${outcome.tone === "ok" ? "rx-status-ok" : "rx-status-conflict"}`} role={outcome.tone === "ok" ? "status" : "alert"} data-whatif-outcome={outcome.tone}>
        {outcome.text}{outcome.tone === "ok" && <> <a href="#scenarios" data-whatif-open-scenarios="true">Open Scenarios</a></>}</p>}
    </section>
  );
}
