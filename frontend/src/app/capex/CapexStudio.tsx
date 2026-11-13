import { useEffect, useState } from "react";
import "../../styles/rcm-analysis.css";
import { copyTsv, downloadCsv } from "../analysis/shared";
import type { CapexPlan } from "./types";
import { groupDisplayName } from "../costGroupDisplay";
import { formatMoneyText } from "../units";
import { useReportPrecision } from "../ReportPrecision";
import { parsePercentages } from "./profileImport";
import { takeProfileFocus } from "./profileFocus";
import { emptyProfileRow, sameDraftRow, SHAPE_LABEL } from "./profileDraft";
import { EnsureCapexProfileDraft, useCapexProfileDraft } from "./ProfileDraftProvider";
import { ProfileRowEditor, ProfileShapeSelect, ProfileDraftActions, ProfileDraftNotice } from "./ProfileRowEditor";

/** Compatibility formatter for unambiguous row/column imports. Editors retain raw/ambiguous input in the shared draft. */
export function normalizePastedWeights(text: string): string {
  const parsed = parsePercentages(text);
  return parsed.status === "ok" ? parsed.values.join(",") : text;
}

/** Inputs > CAPEX spending profile (RC-UX A2, Audit A GAP-R9).  Shapes, monthly weights and milestones for the eligible CAPEX items.
 *  The preview is the canonical allocation of a DRAFT — never a Run result.  Save writes the Working Copy through the existing
 *  canonical route (CSRF + composite CAS) and never runs the model; IDC and Sources & Uses change only at the next Run. */
export function CapexStudio(props: { project: string; reloadKey?: number; onSaved: () => void }) {
  return <EnsureCapexProfileDraft {...props}><CapexStudioView project={props.project} /></EnsureCapexProfileDraft>;
}

function CapexStudioView({ project }: { project: string }) {
  const { precision } = useReportPrecision();
  // Amounts follow the report precision (default 0 decimals); exports and the saved document keep the exact server text.
  const fmt = (text: string | null | undefined) => (text === null || text === undefined || text === "—" || text === "" ? "—" : formatMoneyText(text.replace(/,/g, ""), "kEUR", "kEUR", precision));
  const c = useCapexProfileDraft();
  const { data, draft, saved, plan, loadError, orphans, readOnly } = c;
  const [bulk, setBulk] = useState("UNIFORM");
  const [focusKey, setFocusKey] = useState<string | null>(() => takeProfileFocus());
  const [lineNames, setLineNames] = useState<Record<string, string>>({});
  useEffect(() => {
    if (!orphans.length) return;
    const abort = new AbortController();
    void fetch(`/v2/model-react/costlines?sheet=capex&project=${encodeURIComponent(project)}`, { credentials: "same-origin", cache: "no-store", signal: abort.signal, headers: { Accept: "application/json" } })
      .then(r => r.ok ? r.json() : null).then(body => {
        const names: Record<string, string> = {};
        for (const line of body?.projection?.lines ?? []) if (line.finco_display_code) names[line.finco_display_code] = line.label;
        if (!abort.signal.aborted) setLineNames(names);
      }).catch(() => undefined);
    return () => abort.abort();
  }, [orphans.join("|"), project]);
  useEffect(() => {
    if (!data || !focusKey) return;
    const el = document.querySelector<HTMLElement>(`[data-capex-shape="${CSS.escape(focusKey)}"]`);
    if (el) { el.scrollIntoView({ block: "center" }); el.focus({ preventScroll: true }); }
    const timer = window.setTimeout(() => setFocusKey(null), 4000);
    return () => window.clearTimeout(timer);
  }, [data, focusKey]);

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
      {orphans.length > 0 && (
        <div className="rx-banner rx-banner-stale" role="status" data-capex-orphans={orphans.length}>
          <strong>Saved profile for {orphans.length === 1 ? "a line that is" : `${orphans.length} lines that are`} not active:</strong>{" "}
          {orphans.map((k) => lineNames[k] ?? "a retired line").join(", ")}. Retiring a line keeps its profile, but the next Run is refused while it is
          stored (CAPEX_PROFILE_LEAF_UNKNOWN). Reactivate the line on CAPEX · Lines to use it again, or save this page to remove it (you will be asked to confirm).
        </div>)}
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
          <button type="button" className="rx-button rx-button-secondary" data-capex-bulk-apply="true" disabled={readOnly} onClick={() => c.applyBulk(bulk)}>Apply to all items</button>
          <button type="button" className="rx-button rx-button-secondary" data-capex-clear="true" disabled={readOnly} onClick={c.clearAll}>Clear all shapes</button>
        </div>
      </div>

      <p className="rcm-scroll-hint" aria-hidden="true">Swipe or scroll sideways for more columns →</p>
      <div className="rcm-scroll" tabIndex={0} role="region" aria-label="CAPEX items and shapes (scrolls horizontally)">
        <table className="rcm-table" data-capex-items="true">
          <thead><tr><th scope="col" className="rcm-sticky">Item</th><th scope="col">Amount (kEUR)</th><th scope="col" className="rcm-left">Shape</th><th scope="col" className="rcm-left">Monthly detail</th></tr></thead>
          <tbody>
            {data.items.map((item) => {
              const row = draft[item.item_key] ?? emptyProfileRow();
              const changed = !c.scopeMismatch && !sameDraftRow(row, saved[item.item_key] ?? emptyProfileRow());
              return (
                <tr key={item.item_key} data-capex-item={item.item_key} data-capex-changed={changed || undefined}
                    data-capex-focused={focusKey === item.item_key || undefined} className={focusKey === item.item_key ? "rcm-row-focus" : undefined}>
                  <th scope="row" className="rcm-sticky">{item.label}<span className="rcm-delta">{groupDisplayName(item.category_code, "")}</span></th>
                  <td data-exact={item.amount_keur}>{fmt(item.amount_display)}</td>
                  <td className="rcm-left"><ProfileShapeSelect itemKey={item.item_key} label={item.label} /></td>
                  <td className="rcm-left" style={{ whiteSpace: "normal" }}><ProfileRowEditor itemKey={item.item_key} label={item.label} showShape={false} monthsInitiallyOpen={false} /></td>
                </tr>
              );
            })}
            {!data.items.length && <tr><td colSpan={4} className="rcm-na">No eligible CAPEX items with a positive amount.</td></tr>}
          </tbody>
        </table>
      </div>
      {data.excluded.length > 0 && (
        <details><summary>Derived / financing items (not eligible for a spending profile): {data.excluded.length}</summary>
          <ul>{data.excluded.map((e) => <li key={e.item_key}>{e.label} — {fmt(e.amount_display)} kEUR</li>)}</ul></details>
      )}

      <ProfileDraftActions />
      <ProfileDraftNotice />
      {(data.saved.binding.saved || data.saved.error) && <button type="button" className="rx-button rx-button-secondary" data-capex-remove="true"
        disabled={readOnly || Boolean(c.stale)} onClick={() => c.setDialog("reset")}>Remove saved profile</button>}

      {plan && (
        <div className="rcm-result" data-capex-plan={c.outdated ? "outdated" : "current"} data-canonical="false">
          {c.outdated && <p className="rx-banner rx-banner-stale" role="status" data-capex-outdated="true">OUTDATED — the draft changed after this preview. Preview again.</p>}
          <h3 className="rcm-h3">Hypothetical monthly allocation</h3>
          <p className="rx-note">{plan.plan.notice}</p>
          <p className="rcm-status-line">
            <span className={`rcm-chip ${plan.plan.totals.reconciles ? "ok" : "warn"}`} data-capex-reconciles={String(plan.plan.totals.reconciles)}>
              {plan.plan.totals.reconciles ? "Profiled amounts reconcile exactly" : "Unallocated or invalid rows present"}
            </span>
            <span>Planned <strong data-capex-planned="true">{fmt(plan.plan.totals.planned)}</strong> · profiled <strong data-capex-profiled="true">{fmt(plan.plan.totals.profiled)}</strong> · unallocated <strong data-capex-unallocated="true">{fmt(plan.plan.totals.unallocated)}</strong> kEUR</span>
          </p>
          {plan.plan.global_errors.map((e) => <p key={e} className="rx-status rx-status-error" role="alert" data-capex-global-error="true">{e}</p>)}
          <div className="rcm-scroll" tabIndex={0} role="region" aria-label="Per-item allocation status (scrolls)">
            <table className="rcm-table" data-capex-rows="true">
              <thead><tr><th scope="col" className="rcm-sticky">Item</th><th scope="col" className="rcm-left">Shape</th><th scope="col">Amount (kEUR)</th><th scope="col" className="rcm-left">Status</th><th scope="col">Unallocated (kEUR)</th></tr></thead>
              <tbody>{plan.plan.rows.map((r) => (
                <tr key={r.item_key} data-capex-row={r.item_key} data-status={r.status}>
                  <th scope="row" className="rcm-sticky">{r.label}</th><td className="rcm-left">{SHAPE_LABEL[r.shape] ?? r.shape}</td><td>{fmt(r.amount_display)}</td>
                  <td className="rcm-left">{r.status === "valid" ? <span className="rcm-chip ok">valid</span> : <span className="rcm-tag rcm-tag-bad" title={r.error_detail ?? ""}>{r.error_code}</span>}</td>
                  <td>{fmt(r.unallocated_display)}</td></tr>))}</tbody>
            </table>
          </div>
          {plan.plan.item_order.length > 0 && (
            <details className="rx-card ci-expanded-monthly" data-capex-expanded-monthly="true">
              <summary>Expanded monthly view — per-month table with Copy / CSV ({plan.plan.months.length} months, kEUR)</summary>
              <p className="rx-note" data-capex-expanded-note="true">The same canonical server preview as above, full-width. Amounts in kEUR are exact server text; the browser never re-rounds them. With Report precision at 0 decimals the sum of the rounded visible cells can differ slightly from the unrounded canonical total — stored values are never changed for display.</p>
              <div className="rcm-table-actions" style={{ marginTop: 10 }}>
                <button type="button" className="rx-button rx-button-secondary" data-copy-table="true" onClick={() => void copyTsv(rowsExport(plan.plan))}>Copy table</button>
                <button type="button" className="rx-button rx-button-secondary" data-download-csv="true" onClick={() => downloadCsv("capex-monthly-profile.csv", rowsExport(plan.plan))}>Download CSV</button>
              </div>
              <div className="rcm-scroll" tabIndex={0} role="region" aria-label="Monthly uses of the profiled items (scrolls)">
                <table className="rcm-table" data-capex-months="true">
                  <thead><tr><th scope="col" className="rcm-sticky">Month</th><th scope="col" className="rcm-left">Start</th><th scope="col">Period</th>
                    {plan.plan.item_order.map((k) => <th scope="col" key={k} title={`${k} — exact server value in kEUR`}>{k}</th>)}<th scope="col">Total (kEUR)</th><th scope="col">Cumulative (kEUR)</th><th scope="col">Remaining (kEUR)</th></tr></thead>
                  <tbody>{plan.plan.months.map((m) => (
                    <tr key={m.month} data-capex-month={m.month}><th scope="row" className="rcm-sticky">{m.month}</th><td className="rcm-left">{m.start ?? "—"}</td><td>{m.period === null ? "—" : `P${m.period}`}</td>
                      {plan.plan.item_order.map((k) => <td key={k}>{fmt(m.items[k])}</td>)}<td>{fmt(m.total)}</td><td>{fmt(m.cumulative)}</td><td>{fmt(m.remaining)}</td></tr>))}</tbody>
                </table>
              </div>
              {plan.plan.period_equivalent_total.length > 0 && (
                <p className="rx-note" data-capex-period-equivalent="true">Equivalent on the existing construction periods (end-of-period payment convention; intra-period timing is not represented there):{" "}
                  {plan.plan.period_equivalent_total.map((v, i) => `P${i} ${data.timeline.period_starts[i] ?? ""}–${data.timeline.period_ends[i] ?? ""}: ${fmt(v)}`).join(" · ")} kEUR.</p>
              )}
            </details>
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

    </section>
  );
}
