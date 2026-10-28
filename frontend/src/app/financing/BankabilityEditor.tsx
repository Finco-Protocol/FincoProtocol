import { useCallback, useEffect, useMemo, useRef, useState, type ClipboardEvent, type KeyboardEvent } from "react";
import "../../styles/rcm-financing.css";
import { fetchSheetFields, saveWorkbookField } from "../api";
import { StatusNote, useReportDirty, useReportPending, useSingleFlight, useUnresolvedLock, type StatusMessage } from "../workflow/workflowShared";
import { fetchFinancingStudio } from "./financingApi";
import {
  advisoryProblems, configText, draftFromView, serializeBankability, type BankabilityDraft, type RatesMode, type ReserveMode, type TargetsMode,
} from "./serializeBankability";
import type { BankabilityView } from "./types";

const FIELD = "debt.bankability.configuration";

/** Typed editor for the canonical bankability configuration (sizing, lender case, rates, DSCR targets, fees, reserve).
 *  It serialises the form exactly like the Legacy editor and saves through the canonical per-field writer
 *  (composite-hash CAS, CSRF, rate/fee/reserve authority gates).  The server stays the only validator. */
export function BankabilityEditor({ project, view, editable, identityHash, onSaved, onChanged }: {
  project: string; view: BankabilityView; editable: boolean; identityHash: string;
  onSaved: () => void; onChanged: () => void;
}) {
  const baseline = useMemo(() => draftFromView(view), [view]);
  const baselineText = useMemo(() => configText(view), [view]);
  const [draft, setDraft] = useState<BankabilityDraft>(baseline);
  const [status, setStatus] = useState<StatusMessage | null>(null);
  const [problems, setProblems] = useState<string[]>([]);
  const [inFlight, setInFlight] = useState(false);
  const [confirmReset, setConfirmReset] = useState(false);
  const [locked, setLocked] = useUnresolvedLock("sheet-debt-bankability");
  const singleFlight = useSingleFlight();
  const grid = useRef<HTMLTableElement>(null);

  // A new authoritative view replaces the draft (a draft whose baseline moved underneath it is never silently rebased).
  const seen = useRef(baselineText);
  useEffect(() => {
    if (seen.current !== baselineText) { seen.current = baselineText; setDraft(baseline); setProblems([]); }
  }, [baseline, baselineText]);
  // Only a different project resets the editor; a reload after a Save keeps its success message (the baseline effect above re-bases a clean draft).
  useEffect(() => { setDraft(baseline); setStatus(null); setProblems([]); setConfirmReset(false); }, [project]); // eslint-disable-line react-hooks/exhaustive-deps

  const draftText = serializeBankability(draft);
  const dirty = draftText !== baselineText;
  useReportDirty("sheet-debt-bankability", dirty ? 1 : 0);
  useReportPending("sheet-debt-bankability", inFlight || locked);

  const set = <K extends keyof BankabilityDraft>(key: K, value: BankabilityDraft[K]) => { setDraft((d) => ({ ...d, [key]: value })); setStatus(null); setProblems([]); };
  const periods = view.periods ?? [];
  const periodMode = draft.targetsMode === "periods";
  const rateMode = draft.ratesMode === "periods";

  const save = useCallback(async (value: string, label: string) => {
    await singleFlight(async () => {
      setInFlight(true); setStatus(null);
      try {
        const tokenRead = await fetchSheetFields(project, "debt");
        if (!("ok" in tokenRead) || tokenRead.ok !== true) { setStatus({ tone: "error", text: "The save tokens could not be read. Nothing was saved. Reload and try again." }); return; }
        if (tokenRead.save.content_hash !== identityHash) {
          setStatus({ tone: "conflict", text: "The project changed after this view loaded. Nothing was saved — reload to see the current values." });
          onChanged();
          return;
        }
        const result = await saveWorkbookField({
          updateUrl: tokenRead.save.url, project, fieldId: FIELD, value, workbookVersion: tokenRead.save.workbook_version,
          contentHash: tokenRead.save.content_hash, csrfToken: tokenRead.save.csrf_token, sheetId: "debt",
          verifyCommitted: async () => {
            const fresh = await fetchFinancingStudio(project);
            if (!fresh.ok) return false;
            const expected = value === "" ? {} : JSON.parse(value);
            return JSON.stringify(fresh.bankability.config ?? {}) === JSON.stringify(expected)
              || JSON.stringify(sortKeys(fresh.bankability.config ?? {})) === JSON.stringify(sortKeys(expected));
          },
        });
        if ("kind" in result) { setLocked(true); setStatus({ tone: "conflict", text: result.message }); return; }
        if (!result.ok) { setStatus({ tone: "error", text: `${result.message} Nothing was changed.` }); return; }
        setStatus({ tone: "ok", text: `${label} saved and read back. The Last Run, if any, is now Results outdated — press Run when ready.` });
        onSaved();
      } finally { setInFlight(false); setConfirmReset(false); }
    });
  }, [project, identityHash, singleFlight, setLocked, onSaved, onChanged]);

  function submit() {
    const found = advisoryProblems(draft, view);
    setProblems(found);
    if (found.length) { setStatus({ tone: "error", text: "Fix the highlighted problems before saving. Nothing was saved." }); return; }
    void save(draftText, "Bankability configuration");
  }

  // Excel-like grid: arrow keys move between rows of a column, Enter moves down, TSV paste fills downward (still a draft until Save)
  function moveFocus(event: KeyboardEvent<HTMLInputElement>, row: number, column: "target" | "rate") {
    const delta = event.key === "ArrowDown" || event.key === "Enter" ? 1 : event.key === "ArrowUp" ? -1 : 0;
    if (!delta) return;
    event.preventDefault();
    grid.current?.querySelector<HTMLInputElement>(`[data-grid-cell="${column}-${row + delta}"]`)?.focus();
  }
  function paste(event: ClipboardEvent<HTMLInputElement>, row: number, column: "target" | "rate") {
    const text = event.clipboardData.getData("text");
    if (!/[\t\n]/.test(text)) return;                       // a single value pastes normally
    event.preventDefault();
    const lines = text.replace(/\r/g, "").split("\n").filter((l) => l.trim() !== "");
    const twoColumns = column === "target" && lines.some((l) => l.includes("\t"));
    setDraft((d) => {
      const targets = [...d.targets]; const rates = [...d.rates];
      lines.forEach((line, offset) => {
        const index = row + offset;
        if (index >= periods.length) return;
        const parts = line.split("\t");
        if (column === "target") { targets[index] = parts[0].trim(); if (parts[1] !== undefined) rates[index] = parts[1].trim(); }
        else rates[index] = parts[0].trim();
      });
      return { ...d, targets, rates, ratesMode: twoColumns ? "periods" : d.ratesMode };   // still drafts: nothing is saved or validated as final
    });
    setStatus(null);
  }
  const fill = (key: "targets" | "rates", value: string) => { setDraft((d) => ({ ...d, [key]: d[key].map(() => value) })); setStatus(null); };

  if (!view.available) {
    return <section className="rx-card" data-bankability-state="unavailable"><h3 className="rcm-h3">Bankability configuration</h3>
      <p className="rx-empty" role="status" data-bankability-reason="true">{view.reason ?? "The bankability editor is unavailable for this project."}</p></section>;
  }
  const cfgFees = view.config?.fees;
  const disabled = !editable || locked || inFlight;
  const autoReserve = view.automatic_reserve;

  return (
    <section className="rx-card rcm-fin" data-bankability-editor="true" aria-labelledby="rcm-bank-title">
      <h3 id="rcm-bank-title" className="rcm-h3">Bankability configuration <span className="rcm-badge" data-bank-dirty={dirty}>{dirty ? "UNSAVED CHANGES" : "SAVED"}</span></h3>
      <p className="rx-note">Working inputs, project-owned across scenarios. The Last Run stays unchanged until you Run. Save writes only this configuration; the server validates every value.</p>
      {!editable && <p className="rx-status rx-status-conflict" role="status" data-bank-readonly="true">Read-only: templates cannot be edited. Start a project from this template to change financing terms.</p>}
      {locked && <p className="rx-status rx-status-conflict" role="alert" data-bank-locked="true">A previous save has an unknown outcome. Reload the workspace to reconcile before editing again.</p>}

      <fieldset className="rcm-fieldset" disabled={disabled}>
        <legend>B · Lender base case &amp; debt sizing</legend>
        <div className="rcm-grid2">
          <label className="rcm-field">Debt sizing method
            <select data-bank="sizing_mode" value={draft.sizingMode} onChange={(e) => set("sizingMode", e.target.value)}>
              <option value="">Existing project method (no override)</option>
              <option value="flat_dscr_sculpted">DSCR sculpting with gearing cap</option>
              <option value="gearing_cap">Gearing cap / level principal</option>
            </select></label>
          {view.renewable
            ? <label className="rcm-field">Lender production case
              <select data-bank="lender_case" value={draft.lenderCase} onChange={(e) => set("lenderCase", e.target.value)}>
                <option value="">Existing lender case (no override)</option>
                <option value="P_50">P50</option><option value="P90-10y">P90-10Y</option>
              </select></label>
            : <p className="rx-note">Renewable production-yield cases do not apply to this project.</p>}
        </div>
        <p className="rx-note">Lender sizing does not replace the operating production case. Requested gearing is a cap, not funded debt. Frozen schedules and minimum-DSCR mode are not executable here.</p>
      </fieldset>

      <fieldset className="rcm-fieldset" disabled={disabled}>
        <legend>C · Interest rate</legend>
        <div className="rcm-grid2">
          <label className="rcm-field">Rate authority
            <select data-bank="rates_mode" value={draft.ratesMode} onChange={(e) => set("ratesMode", e.target.value as RatesMode)}>
              <option value="inherit">Existing rate authority (no override)</option>
              <option value="periods">Explicit all-in rates by operating period</option>
            </select></label>
          <label className="rcm-field">Day-count convention
            <select data-bank="day_count" value={draft.dayCount} onChange={(e) => set("dayCount", e.target.value)}>
              <option value="">Existing day count (no override)</option>
              <option value="act_360">ACT/360</option><option value="act_365">ACT/365</option>
            </select></label>
        </div>
        <p className="rx-note">Annual all-in percentages by actual SEMESTRIAL debt period. Fixed/floating/hedge pricing modes are not supported by this editor.</p>
      </fieldset>

      <fieldset className="rcm-fieldset" disabled={disabled}>
        <legend>D · Repayment &amp; sculpting</legend>
        <div className="rcm-grid2">
          <label className="rcm-field">Target DSCR authority
            <select data-bank="targets_mode" value={draft.targetsMode} onChange={(e) => set("targetsMode", e.target.value as TargetsMode)}>
              <option value="inherit">Existing target authority (no override)</option>
              <option value="scalar">Single target for all periods</option>
              <option value="periods">Period-specific targets</option>
            </select></label>
          <label className="rcm-field">Single target (x)
            <input data-bank="target_scalar" inputMode="decimal" value={draft.targetScalar} disabled={disabled || draft.targetsMode !== "scalar"} onChange={(e) => set("targetScalar", e.target.value)} />
          </label>
        </div>
        <div className="rcm-grid-actions">
          <button type="button" className="rx-button rx-button-secondary" disabled={disabled || !periodMode} data-bank-fill="targets" onClick={() => { const v = window.prompt("Set every period's target DSCR (x) to:", draft.targets[0] ?? ""); if (v !== null) fill("targets", v.trim()); }}>Set all targets…</button>
          <button type="button" className="rx-button rx-button-secondary" disabled={disabled || !rateMode} data-bank-fill="rates" onClick={() => { const v = window.prompt("Set every period's all-in rate (%) to:", draft.rates[0] ?? ""); if (v !== null) fill("rates", v.trim()); }}>Set all rates…</button>
          <span className="rx-note">Tip: paste two tab-separated columns (target, rate) from a spreadsheet into the first cell to fill downward.</span>
        </div>
        <p className="rx-note">Periods are the actual SEMESTRIAL debt periods, including partial periods. Period targets require DSCR sculpting.</p>
        <div className="rcm-scroll" tabIndex={0} role="region" aria-label="Debt periods (scrolls horizontally)">
          <table className="rcm-table" ref={grid} data-bank-grid="true">
            <thead><tr><th scope="col" className="rcm-sticky">Period</th><th scope="col" className="rcm-left">Start</th><th scope="col" className="rcm-left">End</th><th scope="col">Target DSCR (x)</th><th scope="col">Annual all-in (%)</th></tr></thead>
            <tbody>
              {periods.map((p, i) => (
                <tr key={p.number}>
                  <th scope="row" className="rcm-sticky">{p.number} <small>[{p.index}]</small></th>
                  <td className="rcm-left">{p.start}</td><td className="rcm-left">{p.end}</td>
                  <td><input aria-label={`Target DSCR period ${p.number}`} data-grid-cell={`target-${i}`} inputMode="decimal" value={draft.targets[i] ?? ""} disabled={disabled || !periodMode}
                             onChange={(e) => { const next = [...draft.targets]; next[i] = e.target.value; set("targets", next); }}
                             onKeyDown={(e) => moveFocus(e, i, "target")} onPaste={(e) => paste(e, i, "target")} /></td>
                  <td><input aria-label={`All-in rate period ${p.number}`} data-grid-cell={`rate-${i}`} inputMode="decimal" value={draft.rates[i] ?? ""} disabled={disabled || !rateMode}
                             onChange={(e) => { const next = [...draft.rates]; next[i] = e.target.value; set("rates", next); }}
                             onKeyDown={(e) => moveFocus(e, i, "rate")} onPaste={(e) => paste(e, i, "rate")} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </fieldset>

      <fieldset className="rcm-fieldset" disabled={disabled}>
        <legend>E · Financing fees</legend>
        {view.fees_editable || cfgFees ? (
          <>
            <label className="rcm-check"><input type="checkbox" data-bank="fees_enabled" checked={draft.feesEnabled} onChange={(e) => set("feesEnabled", e.target.checked)} />
              {view.fees_editable ? " Set construction financing fees" : " Existing conflicting fee override — uncheck to remove it before Save/Run"}</label>
            {view.fees_editable && (
              <div className="rcm-grid3">
                {([["commitment_pct", "Commitment (% p.a.)"], ["structuring_pct", "Structuring (%)"], ["arrangement_pct", "Arrangement (%)"]] as const).map(([key, title]) => (
                  <label className="rcm-field" key={key}>{title}
                    <input data-bank-fee={key} inputMode="decimal" value={draft.fees[key]} disabled={disabled || !draft.feesEnabled}
                           onChange={(e) => set("fees", { ...draft.fees, [key]: e.target.value })} /></label>
                ))}
              </div>
            )}
          </>
        ) : <p className="rx-note" data-bank-fees-locked="true">Explicit construction pricing or materialized financing CAPEX owns fees. No competing manual fee input is permitted.</p>}
      </fieldset>

      <fieldset className="rcm-fieldset" disabled={disabled}>
        <legend>F · Reserve facilities</legend>
        {view.reserve_editable ? (
          <div className="rcm-grid3">
            <label className="rcm-field">Reserve policy
              <select data-bank="reserve_mode" value={draft.reserveMode} onChange={(e) => set("reserveMode", e.target.value as ReserveMode)}>
                <option value="inherit">Existing reserve policy (no override)</option>
                <option value="none">NONE</option>
                {autoReserve && <option value="automatic_peak">Automatic peak forward debt service</option>}
                <option value="cash_fixed">CASH_DSRA / fixed amount</option>
                <option value="dsrf">DSRF / standby support</option>
              </select></label>
            <label className="rcm-field">Coverage (months)<input data-bank="months" inputMode="numeric" value={draft.months} disabled={disabled || draft.reserveMode !== "automatic_peak"} onChange={(e) => set("months", e.target.value)} /></label>
            <label className="rcm-field">Required reserve (kEUR)<input data-bank="requirement_keur" inputMode="decimal" value={draft.requirement} disabled={disabled || !["cash_fixed", "dsrf"].includes(draft.reserveMode)} onChange={(e) => set("requirement", e.target.value)} /></label>
            <label className="rcm-field">DSRF commitment (kEUR)<input data-bank="commitment_keur" inputMode="decimal" value={draft.commitment} disabled={disabled || draft.reserveMode !== "dsrf"} onChange={(e) => set("commitment", e.target.value)} /></label>
            <label className="rcm-field">DSRF commitment fee (% p.a.)<input data-bank="fee_pct" inputMode="decimal" value={draft.feePct} disabled={disabled || draft.reserveMode !== "dsrf"} onChange={(e) => set("feePct", e.target.value)} /></label>
          </div>
        ) : <p className="rx-note" data-bank-reserve-locked="true">The reserve funding of the CAPEX plan is already set elsewhere in the project, so it cannot be entered a second time here.</p>}
        <p className="rx-note">CASH_DSRA funds a cash reserve in Uses. DSRF supplies standby support, not cash funding. No DSRF draw/replenishment engine is provided.</p>
      </fieldset>

      {problems.length > 0 && (
        <ul className="rx-status rx-status-error rcm-problems" role="alert" data-bank-problems="true">{problems.map((p) => <li key={p}>{p}</li>)}</ul>
      )}
      <div className="rcm-actions-row">
        <button type="button" className="rx-button" data-bank-save="true" disabled={disabled || !dirty} aria-busy={inFlight} onClick={submit}>{inFlight ? "Saving…" : "Save bankability"}</button>
        <button type="button" className="rx-button rx-button-secondary" data-bank-discard="true" disabled={disabled || !dirty} onClick={() => { setDraft(baseline); setProblems([]); setStatus(null); }}>Discard changes</button>
        {!confirmReset
          ? <button type="button" className="rx-button rx-button-secondary" data-bank-reset="true" disabled={disabled || Object.keys(view.config ?? {}).length === 0} onClick={() => setConfirmReset(true)}>Reset configuration…</button>
          : <span role="group" aria-label="Confirm reset" data-bank-reset-confirm="true">Remove the whole bankability configuration?{" "}
            <button type="button" className="rx-button" data-bank-reset-yes="true" disabled={inFlight} onClick={() => void save("", "Reset")}>Reset</button>{" "}
            <button type="button" className="rx-button rx-button-secondary" onClick={() => setConfirmReset(false)}>Keep</button></span>}
      </div>
      <StatusNote status={status} />
    </section>
  );
}

/** Stable key order, so an unchanged config compares equal however the server ordered its keys. */
function sortKeys(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(sortKeys);
  if (value && typeof value === "object") return Object.fromEntries(Object.entries(value as Record<string, unknown>).sort(([a], [b]) => a.localeCompare(b)).map(([k, v]) => [k, sortKeys(v)]));
  return value;
}
