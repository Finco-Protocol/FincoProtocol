// WF-React-2 — add / deactivate / reactivate CAPEX and OPEX lines through the
// canonical line commands.  Value edits stay in the atomic batch editor.
//
// Only soft deactivation exists in the canonical layer (there is no hard
// delete), and the canonical add/deactivate routes carry composite CAS plus row
// versions but no CSRF token (an inventoried gap this workflow does not hide or
// change).  An ambiguous outcome is reconciled against a fresh projection and
// never retried: a blind retry of Add could create a duplicate line.

import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { fetchCostLines } from "../api";
import type { CostLinePayload, CostLinesPayload } from "../types";
import { addCostLine, setCostLineActive } from "./workflowApi";
import { groupDisplayName } from "../costGroupDisplay";
import { validateNewCostLine, type NewCostLineDraft } from "./ModelWorkflowValidation";
import { Field, StatusNote, WorkflowDialog, useReportDirty, useReportPending, useSingleFlight, useUnresolvedLock, type StatusMessage } from "./workflowShared";

interface Props {
  project: string;
  data: CostLinesPayload;
  /** Re-read the canonical projection after a verified change. */
  onChanged: () => void;
  /** True from the moment newer saved data is announced until its read has landed: `data` then carries an older composite identity, so no command may use it. */
  refreshing?: boolean;
  /** A group the user chose in the grid ("+ line" on a group row): preselected in the existing form, typed text is kept. */
  presetGroup?: { code: string; nonce: number } | null;
  /** A row action chosen in the grid menu: routed through the same confirmed, CAS-guarded command as the buttons below. */
  rowAction?: { lineId: string; active: boolean; nonce: number } | null;
  /** PR-U1: where the inline add-line form is drawn (a cell under the group the user chose); `null` while no group is open. */
  slot?: HTMLElement | null;
  openGroup?: string | null;
  onClose?: () => void;
  /** Tells the grid whether a line command left an unresolved outcome, so the grid's own add / retire controls lock with it. */
  onLocked?: (locked: boolean) => void;
}

const EMPTY: NewCostLineDraft = { group: "", label: "", amount_keur: "0", inflation_pct: "0", notes: "" };

/** The name shown for a group code (D1, presentation only): never a bare code. The code stays the row/Save identity. */
export function costGroupLabel(code: string, eligible: ReadonlyArray<{ code: string; label: string }>): string {
  return groupDisplayName(code, eligible.find((g) => g.code === code)?.label);
}

export function CostLineManager({ project, data, onChanged, refreshing = false, presetGroup = null, rowAction = null, slot = null, openGroup = null, onClose, onLocked }: Props) {
  const { sheet, line_management: mgmt } = data;
  const readOnlyProject = data.project.protected_reference;
  const [draft, setDraft] = useState<NewCostLineDraft>(EMPTY);
  const [showErrors, setShowErrors] = useState(false);
  const [status, setStatus] = useState<StatusMessage | null>(null);
  const [inFlight, setInFlight] = useState(false);
  const [locked, setLocked] = useUnresolvedLock(`cost-add-${sheet}`);
  const [retire, setRetire] = useState<CostLinePayload | null>(null);

  useEffect(() => { onLocked?.(locked); }, [locked, onLocked]);
  const eligible = useMemo(() => mgmt.eligible_groups.map((g) => g.code), [mgmt.eligible_groups]);
  const errors = validateNewCostLine(draft, sheet, eligible);
  const dirty = draft.label.trim() !== "" || draft.group !== "" ? 1 : 0;
  useReportDirty(`cost-add-${sheet}`, dirty);
  useReportPending(`cost-add-${sheet}`, inFlight || locked);
  const singleFlight = useSingleFlight();

  const cas = { project, workbookVersion: data.save.workbook_version, contentHash: data.save.content_hash };
  const fieldsDisabled = readOnlyProject || inFlight || locked;      // typing stays possible while a newer saved state is being read
  const disabled = fieldsDisabled || refreshing;                       // commands wait: their composite identity would be the older one

  // Requests made in the grid before this form mounted are history, not new requests.
  const seenPreset = useRef(presetGroup?.nonce ?? 0);
  const seenAction = useRef(rowAction?.nonce ?? 0);
  useEffect(() => {
    if (!presetGroup || presetGroup.nonce === seenPreset.current) return;
    seenPreset.current = presetGroup.nonce;
    if (readOnlyProject || !mgmt.eligible_groups.some((g) => g.code === presetGroup.code)) return;
    setDraft((d) => ({ ...d, group: presetGroup.code }));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [presetGroup?.nonce]);

  // The inline form opens under the chosen group: focus its description so typing can start at once.
  useEffect(() => {
    if (slot && openGroup) window.setTimeout(() => slot.querySelector<HTMLElement>("input")?.focus({ preventScroll: false }), 0);
  }, [slot, openGroup]);

  const add = () => (disabled ? Promise.resolve() : singleFlight(runAdd));

  async function runAdd() {
    setShowErrors(true);
    if (Object.keys(errors).length) {
      setStatus({ tone: "error", text: "Fix the highlighted fields. Nothing was added." });
      return;
    }
    setInFlight(true);
    setStatus(null);
    const beforeInGroup = data.lines.filter((l) => l.category === draft.group && l.label === draft.label.trim()).length;
    const result = await addCostLine(data, cas, draft);
    if (result.outcome === "refused") {
      setStatus({ tone: "error", text: result.message });
      setInFlight(false);
      return;
    }
    if (result.outcome === "unknown") {
      setLocked(true);
      setStatus({ tone: "conflict", text: result.message });
      setInFlight(false);
      return;
    }
    const fresh = await fetchCostLines(project, sheet);
    const afterInGroup = fresh.ok === true
      ? fresh.lines.filter((l) => l.category === draft.group && l.label === draft.label.trim()).length : -1;
    setInFlight(false);
    if (afterInGroup === beforeInGroup + 1) {
      setStatus({ tone: "ok", text: `Line "${draft.label.trim()}" added and verified in the fresh projection. The model was not run.` });
      setDraft(EMPTY);
      setShowErrors(false);
      onChanged();
    } else {
      setLocked(true);
      setStatus({ tone: "conflict", text: "The add outcome is UNKNOWN: the server answered but the saved project could not confirm the new line. Reload to reconcile before adding again - an immediate retry could create a duplicate." });
    }
  }

  const NOT_NOW = "That action is not available right now (an update is still running or a change is waiting to be reconciled). Nothing was changed; try again in a moment.";
  const setActive = (line: CostLinePayload, active: boolean) => {
    if (disabled) { setStatus({ tone: "error", text: NOT_NOW }); return Promise.resolve(); }
    return singleFlight(() => runSetActive(line, active));
  };

  async function runSetActive(line: CostLinePayload, active: boolean) {
    setInFlight(true);
    setStatus(null);
    const result = await setCostLineActive(data, cas, line.sub_line_id, line.row_version, active);
    if (result.outcome !== "ok") {
      if (result.outcome === "unknown") setLocked(true);
      setStatus({ tone: result.outcome === "unknown" ? "conflict" : "error", text: result.message });
      setInFlight(false);
      return;
    }
    const fresh = await fetchCostLines(project, sheet);
    const persisted = fresh.ok === true ? fresh.lines.find((l) => l.sub_line_id === line.sub_line_id) : undefined;
    setInFlight(false);
    if (persisted && persisted.active === active) {
      setStatus({ tone: "ok", text: `Line "${line.label}" ${active ? "reactivated" : "deactivated"} and verified. Deactivation is reversible; no value was deleted. The model was not run.` });
      onChanged();
    } else {
      setLocked(true);
      setStatus({ tone: "conflict", text: "The outcome is UNKNOWN: the fresh projection could not confirm the change. Reload to reconcile." });
    }
  }

  useEffect(() => {
    if (!rowAction || rowAction.nonce === seenAction.current) return;
    seenAction.current = rowAction.nonce;
    const line = data.lines.find((l) => l.sub_line_id === rowAction.lineId);
    if (!line || line.active === rowAction.active) return;
    if (disabled) { setStatus({ tone: "error", text: NOT_NOW }); return; }
    if (rowAction.active) void setActive(line, true);
    else setRetire(line);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rowAction?.nonce]);

  const labelOf = (code: string) => costGroupLabel(code, mgmt.eligible_groups);
  const idp = `wf-add-${sheet}`;
  const form = (
    <div className="wf-section ci-inline-add" data-cost-line-manager={sheet} data-add-group={openGroup ?? undefined}>
      <div className="wf-inline-form">
        <Field id={`${idp}-group`} label="Group" error={showErrors ? errors.group : undefined}>
          {(p) => (
            <select {...p} className="fm-input" value={draft.group} disabled={fieldsDisabled} onChange={(e) => setDraft({ ...draft, group: e.target.value })}>
              <option value="">Select a group…</option>
              {mgmt.eligible_groups.map((g) => <option key={g.code} value={g.code}>{labelOf(g.code)}</option>)}
            </select>
          )}
        </Field>
        <Field id={`${idp}-label`} label="Line label" error={showErrors ? errors.label : undefined}>
          {(p) => <input {...p} className="fm-input" value={draft.label} disabled={fieldsDisabled} onChange={(e) => setDraft({ ...draft, label: e.target.value })} />}
        </Field>
        <Field id={`${idp}-amount`} label="Amount" unit={sheet === "opex" ? "k€ per year" : "k€"} error={showErrors ? errors.amount_keur : undefined}>
          {(p) => <input {...p} className="fm-input" inputMode="decimal" value={draft.amount_keur} disabled={fieldsDisabled} onChange={(e) => setDraft({ ...draft, amount_keur: e.target.value })} />}
        </Field>
        {sheet === "opex" && (
          <Field id={`${idp}-infl`} label="Inflation" unit="% per year" error={showErrors ? errors.inflation_pct : undefined}>
            {(p) => <input {...p} className="fm-input" inputMode="decimal" value={draft.inflation_pct} disabled={fieldsDisabled} onChange={(e) => setDraft({ ...draft, inflation_pct: e.target.value })} />}
          </Field>
        )}
        <Field id={`${idp}-notes`} label="Notes">
          {(p) => <input {...p} className="fm-input" value={draft.notes} disabled={fieldsDisabled} onChange={(e) => setDraft({ ...draft, notes: e.target.value })} />}
        </Field>
        <div className="fm-toolbar">
          <button type="button" className="fm-btn fm-btn-primary" disabled={disabled} data-cost-add={sheet} onClick={() => void add()}>
            {inFlight ? "Working…" : "Add line"}
          </button>
          <button type="button" className="fm-btn" disabled={inFlight || dirty === 0}
                  onClick={() => { setDraft(EMPTY); setShowErrors(false); setStatus(null); }}>Clear</button>
          <button type="button" className="fm-btn" disabled={inFlight} data-cost-add-close="true" onClick={() => onClose?.()}>Close</button>
        </div>
      </div>
      {sheet === "opex" && (
        <p className="rx-note" data-inflation-default="fallback">
          A new line starts at 0 % inflation: no project-wide OPEX escalation is saved, so none is assumed. Enter this line's own yearly inflation; existing lines are not changed.
        </p>
      )}
    </div>
  );

  return (
    <div className="wf-section" data-cost-line-commands={sheet}>
      <StatusNote status={status} />
      {locked && <div className="fm-banner" role="alert"><span className="fm-demo-label">RECONCILE</span><span className="fm-banner-copy">The last change outcome is unknown. Reload the workspace before changing lines again.</span></div>}
      {slot && createPortal(form, slot)}
      <p className="fm-info-note">Deactivating a line keeps it for the record and can be undone with Reactivate; lines are never deleted. Calculated groups cannot be changed here. Adding, deactivating and reactivating a line each save immediately and never run the model.</p>
      {retire && (
        <WorkflowDialog
          title={`Deactivate "${retire.label}"?`}
          description="The line stops contributing to totals once the model is next run. It can be reactivated later; nothing is deleted."
          confirmLabel="Deactivate line" danger busy={inFlight}
          onCancel={() => setRetire(null)}
          onConfirm={() => { const line = retire; setRetire(null); void setActive(line, false); }} />
      )}
    </div>
  );
}
