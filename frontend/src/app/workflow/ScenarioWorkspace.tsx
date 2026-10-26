// WF-React-2 — scenario workspace over the canonical scenario authority.
//
// Create / select / rename / archive and override edits post to the existing
// canonical scenario routes.  NONE of them starts a Run, and nothing here
// computes a financial result: KPI comparison stays explicitly unavailable
// until a persisted per-scenario projection exists.  Every mutation is verified
// against a fresh canonical projection; an unverifiable outcome is UNKNOWN and
// is never retried.

import { useCallback, useMemo, useState } from "react";
import { fetchRuns, fetchScenarios } from "../api";
import type { RunHistoryEntry, ScenarioRecordPayload, ScenariosPayload } from "../types";
import { ScenarioCompareView } from "../ux07ScenarioViews";
import { fetchScenarioOverrides, postWorkflowForm } from "./workflowApi";
import { validateOverrideValue } from "./ModelWorkflowValidation";
import {
  Field, LoadingNote, StatusNote, UnavailableNote, WorkflowDialog, useCanonicalRead, useLeaveGuard, useReportDirty,
  useReportPending, useSingleFlight, useUnresolvedLock, type StatusMessage,
} from "./workflowShared";

type DialogState =
  | { kind: "rename"; scenario: ScenarioRecordPayload }
  | { kind: "archive"; scenario: ScenarioRecordPayload }
  | { kind: "reset"; scenario: ScenarioRecordPayload; fieldId: string; label: string }
  | null;

interface Props {
  project: string;
  /** Freshness of the ACTIVE scenario's Last Run (CURRENT / STALE / NOT_RUN). */
  freshness: string;
  /** The ACTIVE scenario changed (select / create): every scope-bound editor must remount. */
  onScenarioChanged: () => void;
  /** A committed change inside the same scope (rename, archive, override): re-read CAS tokens only. */
  onDataChanged: () => void;
}

export function ScenarioWorkspace({ project, freshness, onScenarioChanged, onDataChanged }: Props) {
  const fetcher = useCallback(() => fetchScenarios(project), [project]);
  const read = useCanonicalRead<ScenariosPayload>(fetcher, [project]);
  const runsFetcher = useCallback(() => fetchRuns(project), [project]);
  const runsRead = useCanonicalRead(runsFetcher, [project]);
  const [newName, setNewName] = useState("");
  const [nameError, setNameError] = useState<string | undefined>();
  const [status, setStatus] = useState<StatusMessage | null>(null);
  const [busy, setBusy] = useState(false);
  const [locked, setLocked] = useUnresolvedLock("scenario-workspace");
  const [dialog, setDialog] = useState<DialogState>(null);
  const [compareId, setCompareId] = useState("");
  const [overrideId, setOverrideId] = useState("");
  const [overrideRefresh, setOverrideRefresh] = useState(0);
  useReportDirty("scenario-new", newName.trim() ? 1 : 0);
  useReportPending("scenario-workspace", busy || locked);
  const singleFlight = useSingleFlight();
  const confirmIfDirty = useLeaveGuard();
  // Selecting or creating a scenario changes the scope every other editor is bound to:
  // unsaved edits elsewhere must be explicitly kept (stay) or discarded first.
  const guardScope = (proceed: () => void, onStay?: () => void) =>
    confirmIfDirty(proceed, { ignore: (key) => key.startsWith("scenario-"), onStay });

  const latestRun = useMemo(() => {
    const map = new Map<string, RunHistoryEntry>();
    if (runsRead.state === "ready") {
      for (const run of runsRead.data.runs) {
        const key = run.active_scenario_id ?? "";
        if (key && !map.has(key)) map.set(key, run);
      }
    }
    return map;
  }, [runsRead]);

  /** Post a scenario mutation and verify THIS mutation in a fresh projection. */
  const act = (
    url: string,
    fields: Record<string, string>,
    verify: (fresh: ScenariosPayload) => boolean,
    success: string,
    scope = false,
  ): Promise<boolean> => singleFlight(() => runAct(url, fields, verify, success, scope)).then(Boolean);

  const runAct = async (
    url: string,
    fields: Record<string, string>,
    verify: (fresh: ScenariosPayload) => boolean,
    success: string,
    scope: boolean,
  ): Promise<boolean> => {
    setBusy(true);
    setStatus(null);
    const result = await postWorkflowForm(url, fields);
    if (result.outcome !== "ok") {
      if (result.outcome === "unknown") setLocked(true);
      setStatus({ tone: result.outcome === "unknown" ? "conflict" : "error", text: result.message });
      setBusy(false);
      return false;
    }
    const fresh = await fetchScenarios(project);
    setBusy(false);
    if (fresh.ok === true && verify(fresh)) {
      setStatus({ tone: "ok", text: `${success} Verified in the fresh projection. No Run was started.` });
      read.reload();
      if (scope) onScenarioChanged(); else onDataChanged();
      return true;
    }
    setLocked(true);
    setStatus({ tone: "conflict", text: "The scenario action answered success, but the fresh projection could not confirm THIS change. Reload to reconcile - do not re-submit blindly." });
    return false;
  };

  if (read.state === "loading") return <LoadingNote label="Loading scenarios…" />;
  if (read.state === "error") return <UnavailableNote message={read.message} onRetry={read.reload} />;
  const data = read.data;
  const protectedRef = data.project.protected_reference;
  const disabled = protectedRef || busy || locked;
  const nameTaken = (name: string) => data.scenarios.some((s) => !s.archived && s.name.trim().toLowerCase() === name.trim().toLowerCase());

  const create = async () => {
    const name = newName.trim();
    if (!name) { setNameError("A scenario name is required."); return; }
    if (name.length > 200) { setNameError("Keep the name within 200 characters."); return; }
    if (nameTaken(name)) { setNameError("A scenario with this name already exists."); return; }
    setNameError(undefined);
    const ok = await new Promise<boolean>((resolve) => guardScope(() => {
      void act(data.mutations.create.url, { project, scenario_name: name },
        (fresh) => fresh.scenarios.some((s) => s.name === name && !data.scenarios.some((old) => old.scenario_id === s.scenario_id)),
        `Scenario "${name}" created from the Base Case (no overrides yet) and selected.`, true).then(resolve);
    }, () => resolve(false)));
    if (ok) setNewName("");
  };

  return (
    <section className="fm-card fm-section wf-section" aria-label="Scenario management" data-scenario-workspace="true">
      <div className="fm-card-title"><h2>Scenarios</h2><span>selecting or editing a scenario never runs the model</span></div>
      {protectedRef && <div className="fm-banner" role="note"><span className="fm-demo-label">PROTECTED REFERENCE</span><span className="fm-banner-copy">References have a single immutable case. Create a Working Copy to manage scenarios.</span></div>}
      {locked && <div className="fm-banner" role="alert"><span className="fm-demo-label">RECONCILE</span><span className="fm-banner-copy">The last scenario action could not be confirmed. Reload the workspace before changing scenarios again.</span></div>}
      <StatusNote status={status} />
      <p className="fm-info-note" data-active-scenario-banner="true">
        Active scenario: <strong>{data.active_scenario_name || "Base Case"}</strong>. Its Last Run is <strong data-active-freshness={freshness}>{freshness === "NOT_RUN" ? "NOT RUN" : freshness}</strong>.
        Edits in Inputs, Financing and Revenue apply to this scope.
      </p>
      <div className="wf-table-wrap">
        <table className="fm-table">
          <thead><tr><th scope="col">Scenario</th><th scope="col">Type</th><th scope="col">Overrides</th><th scope="col">Committed Run evidence</th><th scope="col">Actions</th></tr></thead>
          <tbody>
            {data.scenarios.map((s) => {
              const run = latestRun.get(s.scenario_id);
              return (
                <tr key={s.scenario_id} data-scenario-row={s.name} data-archived={s.archived || undefined}>
                  <th scope="row">{s.name}{s.active && <strong data-active-scenario="true"> · active</strong>}</th>
                  <td>{s.is_base_case ? "Base Case" : s.archived ? "Archived" : "Child scenario"}</td>
                  <td>{s.is_base_case ? "—" : s.override_count}</td>
                  <td data-run-evidence={run ? "AVAILABLE" : "UNAVAILABLE"}>
                    {runsRead.state !== "ready" ? "Unavailable"
                      : run ? <><span className="fm-mono">{String(run.runtime_snapshot_id ?? "").slice(0, 12)}</span> · {run.ran_at ?? "time unavailable"}{s.active ? ` · ${freshness === "NOT_RUN" ? "NOT RUN" : freshness}` : " · historical"}</>
                        : "No committed Run"}
                  </td>
                  <td>
                    <span className="fm-toolbar" style={{ flexWrap: "wrap" }}>
                      {!s.active && !s.archived && (
                        <button type="button" className="fm-btn" disabled={disabled} aria-label={`Select scenario ${s.name}`}
                                onClick={() => guardScope(() => void act(data.mutations.select.url, { project, scenario_id: s.scenario_id },
                                  (fresh) => fresh.active_scenario_id === s.scenario_id, `Scenario "${s.name}" selected.`, true))}>Select</button>
                      )}
                      {!s.is_base_case && !s.archived && (
                        <>
                          <button type="button" className="fm-btn" disabled={disabled} aria-label={`Rename scenario ${s.name}`}
                                  onClick={() => setDialog({ kind: "rename", scenario: s })}>Rename</button>
                          <button type="button" className="fm-btn" disabled={disabled} aria-label={`Edit overrides of ${s.name}`}
                                  aria-pressed={overrideId === s.scenario_id}
                                  onClick={() => confirmIfDirty(() => setOverrideId(overrideId === s.scenario_id ? "" : s.scenario_id),
                                    { ignore: (key) => !key.startsWith("scenario-overrides-") })}>Overrides</button>
                          <button type="button" className="fm-btn" disabled={disabled} aria-label={`Archive scenario ${s.name}`}
                                  onClick={() => setDialog({ kind: "archive", scenario: s })}>Archive</button>
                        </>
                      )}
                      {!s.archived && (
                        <button type="button" className="fm-btn" aria-label={`Compare with scenario ${s.name}`}
                                aria-pressed={compareId === s.scenario_id}
                                onClick={() => setCompareId(compareId === s.scenario_id ? "" : s.scenario_id)}>Compare</button>
                      )}
                    </span>
                  </td>
                </tr>
              );
            })}
            {!data.scenarios.length && <tr><td colSpan={5}><span role="status">No scenarios exist yet - only the Base Case is present.</span></td></tr>}
          </tbody>
        </table>
      </div>

      {!protectedRef && (
        <div className="wf-inline-form">
          <Field id="wf-new-scenario" label="New scenario name" error={nameError}
                 hint="Forks the Base Case with no overrides, becomes the active scenario and is not run.">
            {(p) => <input {...p} className="fm-input" value={newName} disabled={disabled} maxLength={200}
                           onChange={(e) => { setNewName(e.target.value); setNameError(undefined); }}
                           onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); void create(); } }} />}
          </Field>
          <div className="fm-toolbar">
            <button type="button" className="fm-btn fm-btn-primary" disabled={disabled} aria-label="Create scenario" onClick={() => void create()}>Create scenario</button>
          </div>
        </div>
      )}

      {overrideId && <OverrideEditor key={`${overrideId}-${overrideRefresh}`} project={project} scenarioId={overrideId} disabled={disabled}
                                     onChange={(s) => { setStatus(s); onDataChanged(); read.reload(); }}
                                     onReset={(fieldId, label) => { const sc = data.scenarios.find((x) => x.scenario_id === overrideId); if (sc) setDialog({ kind: "reset", scenario: sc, fieldId, label }); }} />}

      {compareId && <ScenarioCompareView project={project} scenarioId={compareId} />}

      <div className="fm-banner" role="note" data-kpi-compare="unavailable">
        <span className="fm-demo-label">KPI COMPARISON UNAVAILABLE</span>
        <span className="fm-banner-copy">No persisted per-scenario KPI projection exists yet, so revenue, EBITDA, CFADS, DSCR, debt service and returns are not
          compared here and are never computed in the browser. Assumption compare and each scenario&rsquo;s committed Run evidence are shown instead.</span>
      </div>
      <p className="fm-info-note">{data.mutations.note}</p>

      {dialog?.kind === "rename" && (
        <WorkflowDialog title={`Rename "${dialog.scenario.name}"`} confirmLabel="Rename" busy={busy}
          input={{ label: "Scenario name", initial: dialog.scenario.name }}
          onCancel={() => setDialog(null)}
          onConfirm={(name) => {
            const sc = dialog.scenario;
            if (nameTaken(name) && name.toLowerCase() !== sc.name.toLowerCase()) { setStatus({ tone: "error", text: "A scenario with this name already exists. Nothing was changed." }); setDialog(null); return; }
            setDialog(null);
            void act(data.mutations.rename.url, { project, scenario_id: sc.scenario_id, new_name: name },
              (fresh) => fresh.scenarios.some((x) => x.scenario_id === sc.scenario_id && x.name === name), `Scenario renamed to "${name}".`);
          }} />
      )}
      {dialog?.kind === "archive" && (
        <WorkflowDialog title={`Archive "${dialog.scenario.name}"?`} danger confirmLabel="Archive scenario" busy={busy}
          description="An archived scenario can no longer be selected or compared. Its committed Run history is kept. This does not run the model."
          onCancel={() => setDialog(null)}
          onConfirm={() => {
            const sc = dialog.scenario;
            setDialog(null);
            void act(data.mutations.archive.url, { project, scenario_id: sc.scenario_id },
              (fresh) => fresh.scenarios.some((x) => x.scenario_id === sc.scenario_id && x.archived), `Scenario "${sc.name}" archived.`);
          }} />
      )}
      {dialog?.kind === "reset" && (
        <WorkflowDialog title={`Remove the ${dialog.label} override?`} confirmLabel="Remove override" danger busy={busy}
          description={`"${dialog.scenario.name}" will inherit the Working Copy value again. The persisted Run history is unchanged and the model is not run.`}
          onCancel={() => setDialog(null)}
          onConfirm={() => {
            const { scenario, fieldId } = dialog;
            setDialog(null);
            void (async () => {
              setBusy(true);
              const result = await postWorkflowForm("/v2/workbook/scenarios/remove-override", { project, scenario_id: scenario.scenario_id, field: fieldId });
              if (result.outcome !== "ok") {
                if (result.outcome === "unknown") setLocked(true);
                setStatus({ tone: result.outcome === "unknown" ? "conflict" : "error", text: result.message });
                setBusy(false);
                return;
              }
              const fresh = await fetchScenarioOverrides(project, scenario.scenario_id);
              setBusy(false);
              const row = fresh.ok === true ? fresh.fields.find((f) => f.field_id === fieldId) : undefined;
              if (row && !row.overridden) {
                setStatus({ tone: "ok", text: `Override removed; "${scenario.name}" inherits the Working Copy value. Verified. No Run was started.` });
                read.reload();
                onDataChanged();
                setOverrideRefresh((n) => n + 1);
              } else {
                setLocked(true);
                setStatus({ tone: "conflict", text: "The removal could not be confirmed in the fresh projection. Reload to reconcile." });
              }
            })();
          }} />
      )}
    </section>
  );
}

// ───────────────────────────── override editor ─────────────────────────────

function OverrideEditor({ project, scenarioId, disabled, onChange, onReset }: {
  project: string; scenarioId: string; disabled: boolean;
  onChange: (status: StatusMessage) => void;
  onReset: (fieldId: string, label: string) => void;
}) {
  const fetcher = useCallback(() => fetchScenarioOverrides(project, scenarioId), [project, scenarioId]);
  const read = useCanonicalRead(fetcher, [project, scenarioId]);
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [local, setLocal] = useState<StatusMessage | null>(null);
  const [unresolved, setUnresolved] = useUnresolvedLock(`scenario-overrides-${scenarioId}`);
  useReportDirty(`scenario-overrides-${scenarioId}`, Object.keys(drafts).length);
  useReportPending(`scenario-overrides-${scenarioId}`, busy || unresolved);
  const singleFlight = useSingleFlight();

  if (read.state === "loading") return <LoadingNote label="Loading the scenario overrides…" />;
  if (read.state === "error") return <UnavailableNote message={read.message} onRetry={read.reload} />;
  const data = read.data;
  const locked = disabled || busy || unresolved || !data.editable;

  const saveOverride = (fieldId: string, label: string) => (locked ? Promise.resolve() : singleFlight(() => runSaveOverride(fieldId, label)));

  async function runSaveOverride(fieldId: string, label: string) {
    const value = drafts[fieldId];
    if (value === undefined) return;
    const problem = validateOverrideValue(value);
    if (problem) { setErrors((prev) => ({ ...prev, [fieldId]: problem })); return; }
    setBusy(true);
    setLocal(null);
    const result = await postWorkflowForm(data.mutations.update.url, { project, scenario_id: scenarioId, [fieldId]: value.trim() });
    if (result.outcome !== "ok") {
      setBusy(false);
      if (result.outcome === "refused") setErrors((prev) => ({ ...prev, [fieldId]: result.message }));
      if (result.outcome === "unknown") setUnresolved(true);
      setLocal({ tone: result.outcome === "unknown" ? "conflict" : "error", text: result.message });
      return;
    }
    const fresh = await fetchScenarioOverrides(project, scenarioId);
    setBusy(false);
    const row = fresh.ok === true ? fresh.fields.find((f) => f.field_id === fieldId) : undefined;
    if (row && row.overridden && Number(row.override_value) === Number(value)) {
      setDrafts((prev) => { const next = { ...prev }; delete next[fieldId]; return next; });
      const message: StatusMessage = { tone: "ok", text: `${label} override saved and verified. The Last Run is unchanged; run the model to price this scenario.` };
      setLocal(message);
      onChange(message);
      read.reload();
    } else {
      setUnresolved(true);
      setLocal({ tone: "conflict", text: "The override save outcome is UNKNOWN: the fresh projection could not confirm it. Reload to reconcile - nothing was re-submitted." });
    }
  }

  return (
    <div className="fm-card fm-section wf-section" style={{ marginTop: 12 }} aria-label={`Overrides of ${data.scenario.name}`} data-override-editor={data.scenario.name}>
      <div className="fm-card-title"><h3>Overrides - {data.scenario.name}</h3><span>only fields the canonical Run applies</span></div>
      <StatusNote status={local} />
      <div className="wf-table-wrap">
        <table className="fm-table">
          <thead><tr><th scope="col">Assumption</th><th scope="col">Working Copy</th><th scope="col">Scenario value</th><th scope="col">Source</th><th scope="col">Actions</th></tr></thead>
          <tbody>
            {data.fields.map((f) => {
              const current = drafts[f.field_id] ?? (f.overridden ? String(f.override_value ?? "") : "");
              return (
                <tr key={f.field_id} data-override-field={f.field_id} data-overridden={f.overridden}>
                  <th scope="row">{f.label} <span className="wf-unit">({f.unit})</span></th>
                  <td className="fm-mono">{f.base_value === null ? "—" : String(f.base_value)}</td>
                  <td>
                    <Field id={`wf-ov-${f.field_id}`} label={`${f.label} scenario value`} error={errors[f.field_id]}>
                      {(p) => <input {...p} className="fm-input" inputMode="decimal" disabled={locked}
                                     placeholder={f.overridden ? undefined : `inherits ${f.base_value ?? "—"}`}
                                     value={current}
                                     onChange={(e) => { setDrafts((prev) => ({ ...prev, [f.field_id]: e.target.value })); setErrors((prev) => { const n = { ...prev }; delete n[f.field_id]; return n; }); }} />}
                    </Field>
                  </td>
                  <td>{f.overridden ? "Overridden" : "Inherited"}</td>
                  <td>
                    <span className="fm-toolbar" style={{ flexWrap: "wrap" }}>
                      <button type="button" className="fm-btn fm-btn-primary" disabled={locked || drafts[f.field_id] === undefined}
                              aria-label={`Save override for ${f.label}`} onClick={() => void saveOverride(f.field_id, f.label)}>Save</button>
                      <button type="button" className="fm-btn" disabled={locked || drafts[f.field_id] === undefined}
                              onClick={() => setDrafts((prev) => { const n = { ...prev }; delete n[f.field_id]; return n; })}>Cancel</button>
                      <button type="button" className="fm-btn" disabled={locked || !f.overridden}
                              aria-label={`Remove override for ${f.label}`} onClick={() => onReset(f.field_id, f.label)}>Reset to inherited</button>
                    </span>
                  </td>
                </tr>
              );
            })}
            {!data.fields.length && <tr><td colSpan={5}><span role="status">No assumption can currently be overridden per scenario.</span></td></tr>}
          </tbody>
        </table>
      </div>
      {data.unsupported_override_keys.length > 0 && (
        <p className="fm-info-note" role="note">Stored overrides the Run does not apply (not shown as editable): {data.unsupported_override_keys.join(", ")}.</p>
      )}
      <p className="fm-info-note">{data.mutations.note}</p>
    </div>
  );
}
