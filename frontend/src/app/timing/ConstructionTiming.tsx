import { useEffect, useRef, useState } from "react";
import "../../styles/rcm-analysis.css";
import { FriendlyError } from "../productLanguage";
import type { GridSaveOutcome } from "../CanonicalInputGrid";

/** Inputs > Studios > Construction timing.  The saved inputs are the Commercial Operation Date and the construction duration; the construction START is
 *  derived by the model (COD minus the duration, month-end adjusted).  This studio shows that derived start and lets the user plan from a start date
 *  plus a duration, or a start date plus an end date.  Every date is calculated by the SERVER with the model's calendar convention — the browser does
 *  no date arithmetic — and nothing is saved until Save, which uses the existing atomic input writer. */
interface Saved { cod_date: string | null; construction_months: number | null; derived_start: string | null; duration: string | null; engine_reproducible: boolean; month_end_adjusted: boolean }
interface Plan {
  ok: boolean; message?: string; suggestions?: string[]; cod_date?: string; construction_months?: number; duration?: string; derived_start?: string;
  month_end_adjusted?: boolean; changed?: boolean; cells?: Array<{ field_id: string; value: string }>;
}
interface Payload { ok: true; project: { code: string; protected_reference: boolean }; saved: Saved; limits: { min_months: number; max_months: number }; plan: Plan | null; basis: string }
type Failure = { code: string; message?: string };

async function load(project: string, query: Record<string, string>): Promise<Payload | Failure> {
  const params = new URLSearchParams({ project, ...Object.fromEntries(Object.entries(query).filter(([, v]) => v !== "")) });
  try {
    const response = await fetch(`/v2/model-react/construction-timing?${params}`, { credentials: "same-origin", cache: "no-store", headers: { Accept: "application/json" } });
    const body = await response.json().catch(() => null) as (Payload | (Failure & { ok: false })) | null;
    if (response.ok && body && body.ok === true) return body;
    return { code: (body as Failure | null)?.code ?? `HTTP_${response.status}`, message: (body as Failure | null)?.message };
  } catch {
    return { code: "SERVER_UNREACHABLE" };
  }
}

export function ConstructionTiming({ project, protectedReference, reloadKey, onSaveCells, onSaved }: {
  project: string; protectedReference: boolean; reloadKey: number;
  onSaveCells?: (cells: Array<{ field_id: string; value: string }>) => Promise<GridSaveOutcome>; onSaved: () => void;
}) {
  const [base, setBase] = useState<Payload | null>(null);
  const [failure, setFailure] = useState<Failure | null>(null);
  const [mode, setMode] = useState<"duration" | "end">("duration");
  const [start, setStart] = useState("");
  const [duration, setDuration] = useState("");
  const [unit, setUnit] = useState<"years" | "months">("years");
  const [end, setEnd] = useState("");
  const [plan, setPlan] = useState<Plan | null>(null);
  const [saving, setSaving] = useState(false);
  const [outcome, setOutcome] = useState<{ tone: "ok" | "error"; text: string } | null>(null);
  const seq = useRef(0);

  useEffect(() => {
    let live = true;
    void load(project, {}).then((r) => {
      if (!live) return;
      if ("saved" in r) { setBase(r); setFailure(null); if (r.saved.derived_start && r.saved.construction_months) { setStart(r.saved.derived_start); setUnit(r.saved.construction_months % 12 === 0 ? "years" : "months"); setDuration(String(r.saved.construction_months % 12 === 0 ? r.saved.construction_months / 12 : r.saved.construction_months)); } }
      else setFailure(r);
    });
    return () => { live = false; };
  }, [project, reloadKey]);

  // The plan is asked of the server whenever the inputs change; a stale answer never replaces a newer one.
  useEffect(() => {
    if (!base || !start) { setPlan(null); return; }
    const months = mode === "duration" && duration.trim() !== "" && /^\d+(\.\d+)?$/.test(duration.trim()) ? String(Number(duration) * (unit === "years" ? 12 : 1)) : "";
    if (mode === "duration" && !months) { setPlan({ ok: false, message: "Enter a positive duration that is a whole number of months (for example 15 years or 18 months)." }); return; }
    if (mode === "end" && !end) { setPlan(null); return; }
    const mine = ++seq.current;
    const timer = window.setTimeout(() => {
      void load(project, mode === "duration" ? { start, months } : { start, end }).then((r) => { if (mine === seq.current && "plan" in r) setPlan(r.plan); });
    }, 200);
    return () => window.clearTimeout(timer);
  }, [base, project, mode, start, duration, unit, end]);

  if (failure) return <FriendlyError code={failure.code} message={failure.message} />;
  if (!base) return <p className="rx-boot-loading" role="status" data-timing="loading">Loading construction timing…</p>;
  const saved = base.saved;

  async function save() {
    if (!plan?.ok || !plan.cells || !onSaveCells || saving) return;
    setSaving(true); setOutcome(null);
    const result = await onSaveCells(plan.cells);
    setSaving(false);
    if (result.kind === "saved") { setOutcome({ tone: "ok", text: "Construction timing saved. Your results are now out of date until you run the model." }); onSaved(); }
    else setOutcome({ tone: "error", text: (result as { message?: string }).message ?? "The timing was not saved. Nothing was changed." });
  }

  return (
    <section className="rx-card rcm-analysis" data-timing="ready" aria-label="Construction timing">
      <h3>Construction timing</h3>
      <p className="rx-note">{base.basis}</p>
      <dl className="rcm-facts">
        <div><dt>Commercial Operation Date (COD)</dt><dd data-timing-cod="true">{saved.cod_date ?? "Not set"}</dd></div>
        <div><dt>Construction duration</dt><dd data-timing-duration="true">{saved.duration ?? "Not set"}</dd></div>
        <div><dt>Construction start (derived)</dt><dd data-timing-derived="true">{saved.derived_start ?? "—"}</dd></div>
      </dl>
      {saved.month_end_adjusted && <p className="rx-note" data-timing-note="month-end">The start is month-end adjusted: it falls on the last day of a shorter month.</p>}
      {saved.cod_date && !saved.engine_reproducible && <p className="rx-status rx-status-conflict" role="status" data-timing-warning="true">The saved COD and duration cannot be reproduced exactly by the model (month-end). Pick a different date or duration below.</p>}
      {protectedReference || !onSaveCells ? (
        <p className="rx-empty" role="status" data-timing-readonly="true">{protectedReference ? "Templates are read-only. Start a project from this template to plan its timing." : "Timing can be planned from the project workspace."}</p>
      ) : (
        <>
          <div className="rcm-controls" role="group" aria-label="Plan the construction timing">
            <label className="rcm-field">Construction start date
              <input type="date" value={start} data-timing-start="true" onChange={(e) => { setStart(e.target.value); setOutcome(null); }} />
            </label>
            <label className="rcm-field">Plan from
              <select value={mode} data-timing-mode="true" onChange={(e) => { setMode(e.target.value as "duration" | "end"); setOutcome(null); }}>
                <option value="duration">Start date + duration</option>
                <option value="end">Start date + end date (COD)</option>
              </select>
            </label>
            {mode === "duration" ? (
              <>
                <label className="rcm-field">Duration
                  <input value={duration} inputMode="decimal" data-timing-months="true" onChange={(e) => { setDuration(e.target.value); setOutcome(null); }} />
                </label>
                <label className="rcm-field">Unit
                  <select value={unit} data-timing-unit="true" onChange={(e) => setUnit(e.target.value as "years" | "months")}><option value="years">years</option><option value="months">months</option></select>
                </label>
              </>
            ) : (
              <label className="rcm-field">End date (COD)
                <input type="date" value={end} data-timing-end="true" onChange={(e) => { setEnd(e.target.value); setOutcome(null); }} />
              </label>
            )}
          </div>
          {plan && !plan.ok && (
            <p className="rx-status rx-status-error" role="status" data-timing-plan="invalid">{plan.message}
              {plan.suggestions && plan.suggestions.length > 0 && <> Nearest dates that work: {plan.suggestions.map((s) => <button key={s} type="button" className="rx-button rx-button-secondary" data-timing-suggestion={s} onClick={() => { setMode("end"); setEnd(s); }}>Use {s}</button>)}</>}
            </p>
          )}
          {plan?.ok && (
            <p className="rx-note" role="status" data-timing-plan="valid">
              COD {plan.cod_date} · {plan.duration} · construction starts {plan.derived_start}{plan.month_end_adjusted ? " (month-end adjusted)" : ""}.{plan.changed ? "" : " This is already saved."}
            </p>
          )}
          <div className="rcm-controls-actions">
            <button type="button" className="rx-button" data-timing-save="true" disabled={!plan?.ok || !plan.changed || saving} aria-busy={saving} onClick={() => void save()}>{saving ? "Saving…" : "Save timing"}</button>
          </div>
          {outcome && <p className={`rx-status ${outcome.tone === "ok" ? "rx-status-saved" : "rx-status-error"}`} role="status" data-timing-outcome={outcome.tone}>{outcome.text}</p>}
        </>
      )}
    </section>
  );
}
