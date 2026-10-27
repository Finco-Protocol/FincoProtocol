import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import "../../styles/rcm-analysis.css";
import { copyTsv, downloadCsv } from "../analysis/shared";
import { useReportDirty, useReportPending, useSingleFlight, useUnresolvedLock, WorkflowDialog } from "../workflow/workflowShared";
import { encodeSpec, fetchCapexPreview, fetchCapexProfiles, saveCapexProfile } from "./api";
import type { CapexPlan, CapexProfiles, Draft, DraftRow } from "./types";
import { friendlyMessage } from "../productLanguage";

const SHAPE_LABEL: Record<string, string> = {
  UNIFORM: "Uniform", FRONT_LOADED: "Front-loaded", BACK_LOADED: "Back-loaded", EXPLICIT: "Explicit % per month", MILESTONE: "Milestone (one month)",
};
const EMPTY: DraftRow = { shape: "", explicit: "", milestone: "" };

/** Excel / CSV paste for the explicit weights: one column, one row, tabs, semicolons or newlines all become the comma list the
 *  canonical contract reads.  Text clean-up only — no number is parsed or summed here; the server validates and reconciles. */
export function normalizePastedWeights(text: string): string {
  return text.split(/[\s,;]+/).map((cell) => cell.trim().replace(/%$/, "")).filter(Boolean).join(",");
}
const countWeights = (text: string) => (text.trim() ? text.split(",").length : 0);

function draftFromSaved(data: CapexProfiles): Draft {
  const draft: Draft = {};
  for (const item of data.items) draft[item.item_key] = { ...EMPTY, ...(data.saved.rows[item.item_key] ?? {}) };
  return draft;
}

/** Inputs > CAPEX spending profile (RC-UX A2, Audit A GAP-R9).  Shapes, monthly weights and milestones for the eligible CAPEX items.
 *  The preview is the canonical allocation of a DRAFT — never a Run result.  Save writes the Working Copy through the existing
 *  canonical route (CSRF + composite CAS) and never runs the model; IDC and Sources & Uses change only at the next Run. */
export function CapexStudio({ project, reloadKey = 0, onSaved }: { project: string; reloadKey?: number; onSaved: () => void }) {
  const [data, setData] = useState<CapexProfiles | null>(null);
  const [loadError, setLoadError] = useState("");
  const [draft, setDraft] = useState<Draft>({});
  const [history, setHistory] = useState<Draft[]>([]);
  const [plan, setPlan] = useState<{ plan: CapexPlan; spec: string } | null>(null);
  const [busy, setBusy] = useState<"" | "preview" | "save">("");
  const [status, setStatus] = useState<{ tone: "ok" | "error" | "conflict"; text: string } | null>(null);
  const [error, setError] = useState<{ code: string; message: string } | null>(null);
  const [dialog, setDialog] = useState<"reset" | null>(null);
  const [locked, setLocked] = useUnresolvedLock("capex-profile");
  const [bulk, setBulk] = useState("UNIFORM");
  const singleFlight = useSingleFlight();
  const load = useRef(0);

  const reload = useCallback(async (keepDraft = false) => {
    const mine = ++load.current;
    const result = await fetchCapexProfiles(project);
    if (mine !== load.current) return null;
    if (!result.ok) { setLoadError(friendlyMessage(result.code, result.message)); return null; }
    setLoadError(""); setData(result);
    if (!keepDraft) { setDraft(draftFromSaved(result)); setHistory([]); setPlan(null); }
    return result;
  }, [project]);

  // A save elsewhere bumps `reloadKey`: re-read the CAS tokens but never discard this studio's unsaved draft.
  const dirtyRef = useRef(0);
  useEffect(() => { void reload(dirtyRef.current > 0); }, [reload, reloadKey]);

  const keys = useMemo(() => (data?.items ?? []).map((i) => i.item_key), [data]);
  const saved = useMemo(() => (data ? draftFromSaved(data) : {}), [data]);
  const dirtyCount = data ? keys.filter((k) => JSON.stringify(draft[k] ?? EMPTY) !== JSON.stringify(saved[k] ?? EMPTY)).length : 0;
  dirtyRef.current = dirtyCount;
  useReportDirty("capex-profile", dirtyCount);
  useReportPending("capex-profile", busy !== "" || locked);

  const specNow = data ? encodeSpec(keys, draft) : "";
  const outdated = plan !== null && plan.spec !== specNow;
  const readOnly = !data?.edit.allowed || locked;

  const change = (key: string, patch: Partial<DraftRow>) => {
    setHistory((h) => [...h.slice(-19), draft]);
    setDraft((d) => ({ ...d, [key]: { ...(d[key] ?? EMPTY), ...patch } }));
    setStatus(null);
  };
  const undo = () => setHistory((h) => { if (!h.length) return h; setDraft(h[h.length - 1]); return h.slice(0, -1); });
  const applyBulk = () => {
    setHistory((h) => [...h.slice(-19), draft]);
    setDraft((d) => Object.fromEntries(keys.map((k) => [k, { ...(d[k] ?? EMPTY), shape: bulk }])));
  };
  const clearAll = () => { setHistory((h) => [...h.slice(-19), draft]); setDraft(Object.fromEntries(keys.map((k) => [k, { ...EMPTY }]))); };
  const discard = () => { if (data) { setHistory((h) => [...h.slice(-19), draft]); setDraft(draftFromSaved(data)); } };

  const runPreview = () => singleFlight(async () => {
    if (!data) return;
    setBusy("preview"); setError(null);
    const spec = encodeSpec(keys, draft);
    const result = await fetchCapexPreview(project, spec);
    setBusy("");
    if (result.ok) setPlan({ plan: result.plan, spec });
    else { setPlan(null); setError({ code: result.code, message: result.message ?? "The preview could not be computed." }); }
  });

  const save = (action: "save" | "reset") => singleFlight(async () => {
    if (!data || readOnly) return;
    setBusy("save"); setStatus(null); setDialog(null);
    const outcome = await saveCapexProfile({ url: data.save.url, project, csrfToken: data.save.csrf_token, contentHash: data.save.content_hash,
      action, items: keys, draft: action === "reset" ? Object.fromEntries(keys.map((k) => [k, { ...EMPTY }])) : draft });
    if (outcome.kind === "unknown") { setLocked(true); setStatus({ tone: "conflict", text: outcome.message }); setBusy(""); return; }
    if (outcome.kind === "refused") { setStatus({ tone: "error", text: outcome.message }); setBusy(""); void reload(true); return; }
    const fresh = await reload(false);
    setBusy("");
    const expected = action === "reset" ? [] : keys.filter((k) => draft[k]?.shape);
    const verified = fresh !== null && Object.keys(fresh.saved.rows).sort().join("|") === [...expected].sort().join("|")
      && expected.every((k) => fresh.saved.rows[k]?.shape === draft[k].shape);
    if (verified) {
      setStatus({ tone: "ok", text: action === "reset"
        ? "Saved profile removed and verified in the fresh projection. The the results are now outdated; the model was not run."
        : "Profile saved and verified in the fresh projection. The the results are now outdated: run the model to apply it. The model was not run." });
      onSaved();
    } else {
      setLocked(true);
      setStatus({ tone: "conflict", text: "The server answered success but the fresh projection could not confirm THIS change. Reload to reconcile — do not re-submit blindly." });
    }
  });

  if (!data) return <p className="rx-boot-loading" role="status" data-capex-studio="loading">{loadError || "Loading the CAPEX spending profile…"}</p>;

  const binding = data.saved.binding;
  const rowsExport = (p: CapexPlan): string[][] => [
    ["Month", "Month start", "Period", ...p.item_order, "Total", "Cumulative", "Remaining"],
    ...p.months.map((m) => [String(m.month), m.start ?? "—", m.period === null ? "—" : `P${m.period}`, ...p.item_order.map((k) => m.items[k] ?? "—"), m.total, m.cumulative, m.remaining]),
  ];

  return (
    <section className="rx-card" data-capex-studio="ready" data-capex-vertical={data.project.vertical} aria-label="CAPEX spending profile">
      <h2>CAPEX spending profile <span className="rcm-badge">PREVIEW IS NOT A RESULT</span></h2>
      <p className="rx-note" data-capex-binding={binding.saved ? (binding.bound ? "bound" : "unbound") : "none"}>
        {!binding.saved && "No monthly profile is saved: the Run uses the existing per-category construction timing."}
        {binding.saved && binding.bound && `A profile for ${binding.items} item${binding.items === 1 ? "" : "s"} is saved in the project. The next Run places those items on the monthly timeline; funding, IDC and Total Uses are then recomputed by the canonical engine.`}
        {binding.saved && !binding.bound && `A saved profile exists but cannot be applied (${binding.code}). The Run will refuse to execute until it is corrected or removed.`}
      </p>
      {data.saved.error && <p className="rx-status rx-status-error" role="alert">The stored profile document is invalid: {data.saved.error}</p>}
      {!data.edit.allowed && <p className="rx-note" data-capex-readonly="true">{data.edit.reason}</p>}
      <p className="rx-note">{data.project.name} · construction {data.months} months{data.timeline.available ? ` · dates from the project timeline (${data.timeline.source})` : ` · dates unavailable (${data.timeline.reason})`}.
        {" "}Save writes only this profile and never runs the model. {data.semantics.idc_and_sources_uses}</p>

      <div className="rcm-controls" aria-label="Bulk shape tools">
        <label className="rcm-field">Set every item to
          <select value={bulk} data-capex-bulk-shape="true" disabled={readOnly} onChange={(e) => setBulk(e.target.value)}>
            {data.shapes.filter((s) => s !== "EXPLICIT" && s !== "MILESTONE").map((s) => <option key={s} value={s}>{SHAPE_LABEL[s] ?? s}</option>)}
          </select>
        </label>
        <div className="rcm-controls-actions">
          <button type="button" className="rx-button rx-button-secondary" data-capex-bulk-apply="true" disabled={readOnly} onClick={applyBulk}>Apply to all items</button>
          <button type="button" className="rx-button rx-button-secondary" data-capex-clear="true" disabled={readOnly} onClick={clearAll}>Clear all shapes</button>
          <button type="button" className="rx-button rx-button-secondary" data-capex-undo="true" disabled={readOnly || !history.length} onClick={undo}>Undo</button>
          <button type="button" className="rx-button rx-button-secondary" data-capex-discard="true" disabled={readOnly || dirtyCount === 0} onClick={discard}>Discard changes</button>
        </div>
      </div>

      <p className="rcm-scroll-hint" aria-hidden="true">Swipe or scroll sideways for more columns →</p>
      <div className="rcm-scroll" tabIndex={0} role="region" aria-label="CAPEX items and shapes (scrolls horizontally)">
        <table className="rcm-table" data-capex-items="true">
          <thead><tr><th scope="col" className="rcm-sticky">Item</th><th scope="col">Amount (kEUR)</th><th scope="col" className="rcm-left">Shape</th><th scope="col" className="rcm-left">Monthly detail</th></tr></thead>
          <tbody>
            {data.items.map((item) => {
              const row = draft[item.item_key] ?? EMPTY;
              const changed = JSON.stringify(row) !== JSON.stringify(saved[item.item_key] ?? EMPTY);
              return (
                <tr key={item.item_key} data-capex-item={item.item_key} data-capex-changed={changed || undefined}>
                  <th scope="row" className="rcm-sticky">{item.item_key} {item.label}<span className="rcm-delta">{item.category_code}</span></th>
                  <td>{item.amount_display}</td>
                  <td className="rcm-left">
                    <select value={row.shape} disabled={readOnly} data-capex-shape={item.item_key} aria-label={`Shape for ${item.label}`}
                      onChange={(e) => change(item.item_key, { shape: e.target.value })}>
                      <option value="">— none (existing timing) —</option>
                      {data.shapes.map((s) => <option key={s} value={s}>{SHAPE_LABEL[s] ?? s}</option>)}
                    </select>
                  </td>
                  <td className="rcm-left" style={{ whiteSpace: "normal" }}>
                    {row.shape === "EXPLICIT" && (
                      <label className="rcm-field">Weights, % per month ({countWeights(row.explicit)} of {data.months} entered)
                        <textarea rows={2} value={row.explicit.split(",").join(", ")} disabled={readOnly} data-capex-explicit={item.item_key}
                          placeholder="Paste a column or row from Excel / CSV" aria-label={`Explicit monthly percentages for ${item.label}`}
                          onChange={(e) => change(item.item_key, { explicit: normalizePastedWeights(e.target.value) })} />
                      </label>
                    )}
                    {row.shape === "MILESTONE" && (
                      <label className="rcm-field">Milestone month (1–{data.months})
                        <input inputMode="numeric" value={row.milestone} disabled={readOnly} data-capex-milestone={item.item_key}
                          onChange={(e) => change(item.item_key, { milestone: e.target.value.replace(/[^0-9]/g, "") })} />
                      </label>
                    )}
                    {row.shape !== "EXPLICIT" && row.shape !== "MILESTONE" && <span className="rx-note">{row.shape ? "Calculated from the chosen shape." : "—"}</span>}
                  </td>
                </tr>
              );
            })}
            {!data.items.length && <tr><td colSpan={4} className="rcm-na">No eligible CAPEX items with a positive amount.</td></tr>}
          </tbody>
        </table>
      </div>
      {data.excluded.length > 0 && (
        <details><summary>Derived / financing items (not eligible for a spending profile): {data.excluded.length}</summary>
          <ul>{data.excluded.map((e) => <li key={e.item_key}><code>{e.item_key}</code> {e.label} — {e.amount_display} kEUR</li>)}</ul></details>
      )}

      <div className="rcm-controls-actions" style={{ marginTop: 12 }}>
        <button type="button" className="rx-button" data-capex-preview="true" disabled={busy !== "" || !keys.some((k) => draft[k]?.shape)} onClick={() => void runPreview()}>
          {busy === "preview" ? "Computing…" : "Preview monthly allocation (nothing saved)"}
        </button>
        <button type="button" className="rx-button" data-capex-save="true" disabled={readOnly || busy !== "" || dirtyCount === 0} onClick={() => void save("save")}>
          Save profile to the project{dirtyCount ? ` (${dirtyCount} item${dirtyCount === 1 ? "" : "s"} changed)` : ""}
        </button>
        {(binding.saved || data.saved.error) && (
          <button type="button" className="rx-button rx-button-secondary" data-capex-remove="true" disabled={readOnly || busy !== ""} onClick={() => setDialog("reset")}>Remove saved profile</button>
        )}
      </div>
      {status && <p className={`rx-status ${status.tone === "ok" ? "rx-status-ok" : "rx-status-error"}`} role={status.tone === "ok" ? "status" : "alert"} data-capex-status={status.tone}>{status.text}</p>}
      {error && <p className="rx-status rx-status-error" role="alert" data-capex-error={error.code}>{error.message} ({error.code})</p>}

      {plan && (
        <div className="rcm-result" data-capex-plan={outdated ? "outdated" : "current"} data-canonical="false">
          {outdated && <p className="rx-banner rx-banner-stale" role="status" data-capex-outdated="true">OUTDATED — the draft changed after this preview. Preview again.</p>}
          <h3 className="rcm-h3">Hypothetical monthly allocation</h3>
          <p className="rx-note">{plan.plan.notice}</p>
          <p className="rcm-status-line">
            <span className={`rcm-chip ${plan.plan.totals.reconciles ? "ok" : "warn"}`} data-capex-reconciles={String(plan.plan.totals.reconciles)}>
              {plan.plan.totals.reconciles ? "Profiled amounts reconcile exactly" : "Unallocated or invalid rows present"}
            </span>
            <span>Planned <strong data-capex-planned="true">{plan.plan.totals.planned}</strong> · profiled <strong data-capex-profiled="true">{plan.plan.totals.profiled}</strong> · unallocated <strong data-capex-unallocated="true">{plan.plan.totals.unallocated}</strong> kEUR</span>
          </p>
          {plan.plan.global_errors.map((e) => <p key={e} className="rx-status rx-status-error" role="alert" data-capex-global-error="true">{e}</p>)}
          <div className="rcm-scroll" tabIndex={0} role="region" aria-label="Per-item allocation status (scrolls)">
            <table className="rcm-table" data-capex-rows="true">
              <thead><tr><th scope="col" className="rcm-sticky">Item</th><th scope="col" className="rcm-left">Shape</th><th scope="col">Amount (kEUR)</th><th scope="col" className="rcm-left">Status</th><th scope="col">Unallocated (kEUR)</th></tr></thead>
              <tbody>{plan.plan.rows.map((r) => (
                <tr key={r.item_key} data-capex-row={r.item_key} data-status={r.status}>
                  <th scope="row" className="rcm-sticky">{r.item_key} {r.label}</th><td className="rcm-left">{SHAPE_LABEL[r.shape] ?? r.shape}</td><td>{r.amount_display}</td>
                  <td className="rcm-left">{r.status === "valid" ? <span className="rcm-chip ok">valid</span> : <span className="rcm-tag rcm-tag-bad" title={r.error_detail ?? ""}>{r.error_code}</span>}</td>
                  <td>{r.unallocated_display}</td></tr>))}</tbody>
            </table>
          </div>
          {plan.plan.item_order.length > 0 && (<>
            <div className="rcm-table-actions" style={{ marginTop: 10 }}>
              <button type="button" className="rx-button rx-button-secondary" data-copy-table="true" onClick={() => void copyTsv(rowsExport(plan.plan))}>Copy table</button>
              <button type="button" className="rx-button rx-button-secondary" data-download-csv="true" onClick={() => downloadCsv("capex-monthly-profile.csv", rowsExport(plan.plan))}>Download CSV</button>
            </div>
            <div className="rcm-scroll" tabIndex={0} role="region" aria-label="Monthly uses of the profiled items (scrolls)">
              <table className="rcm-table" data-capex-months="true">
                <thead><tr><th scope="col" className="rcm-sticky">Month</th><th scope="col" className="rcm-left">Start</th><th scope="col">Period</th>
                  {plan.plan.item_order.map((k) => <th scope="col" key={k}>{k}</th>)}<th scope="col">Total</th><th scope="col">Cumulative</th><th scope="col">Remaining</th></tr></thead>
                <tbody>{plan.plan.months.map((m) => (
                  <tr key={m.month} data-capex-month={m.month}><th scope="row" className="rcm-sticky">{m.month}</th><td className="rcm-left">{m.start ?? "—"}</td><td>{m.period === null ? "—" : `P${m.period}`}</td>
                    {plan.plan.item_order.map((k) => <td key={k}>{m.items[k] ?? "—"}</td>)}<td>{m.total}</td><td>{m.cumulative}</td><td>{m.remaining}</td></tr>))}</tbody>
              </table>
            </div>
          </>)}
          {plan.plan.period_equivalent_total.length > 0 && (
            <p className="rx-note" data-capex-period-equivalent="true">Equivalent on the existing construction periods (end-of-period payment convention; intra-period timing is not represented there):{" "}
              {plan.plan.period_equivalent_total.map((v, i) => `P${i} ${data.timeline.period_starts[i] ?? ""}–${data.timeline.period_ends[i] ?? ""}: ${v}`).join(" · ")} kEUR.</p>
          )}
        </div>
      )}

      <div className="rcm-result" data-capex-last-run={data.last_run.available ? (data.last_run.freshness ?? "") : "none"}>
        <h3 className="rcm-h3">Committed Last Run — Sources &amp; Uses and IDC</h3>
        {!data.last_run.available && <p className="rx-note">{data.last_run.note}</p>}
        {data.last_run.available && data.last_run.sources_uses && (<>
          <p className="rcm-status-line">
            <span className={`rcm-chip ${data.last_run.freshness === "CURRENT" ? "ok" : "warn"}`} data-capex-lr-freshness={data.last_run.freshness}>{data.last_run.freshness}</span>
            <span>{data.last_run.used_profile ? "Executed with the saved monthly profile." : "Executed with the existing per-category timing."} {data.last_run.basis}</span>
          </p>
          <dl className="rcm-facts">
            {([["base_project_capex_keur", "Hard CAPEX"], ["capitalized_idc_keur", "Capitalised IDC"], ["commitment_fee_keur", "Commitment fee"], ["structuring_fee_keur", "Structuring fee"],
               ["initial_dsra_funding_keur", "Initial DSRA funding"], ["total_uses_keur", "Total uses"], ["total_sources_keur", "Total sources"]] as const).map(([k, label]) => (
              <div key={k}><dt>{label} (kEUR)</dt><dd data-capex-lr={k}>{data.last_run.sources_uses?.[k]?.display ?? "—"}</dd></div>
            ))}
          </dl>
        </>)}
      </div>

      {dialog === "reset" && (
        <WorkflowDialog title="Remove the saved profile?" description="The monthly profile is removed from the project. The the results become outdated; the model is not run, and the next Run returns to the default per-category timing."
          confirmLabel="Remove profile" danger busy={busy !== ""} onConfirm={() => void save("reset")} onCancel={() => setDialog(null)} />
      )}
    </section>
  );
}
