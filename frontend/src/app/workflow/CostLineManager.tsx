// WF-React-2 — add / deactivate / reactivate CAPEX and OPEX lines through the
// canonical line commands.  Value edits stay in the atomic batch editor.
//
// Only soft deactivation exists in the canonical layer (there is no hard
// delete), and the canonical add/deactivate routes carry composite CAS plus row
// versions but no CSRF token (an inventoried gap this workflow does not hide or
// change).  An ambiguous outcome is reconciled against a fresh projection and
// never retried: a blind retry of Add could create a duplicate line.

import { useMemo, useState } from "react";
import { fetchCostLines } from "../api";
import type { CostLinePayload, CostLinesPayload } from "../types";
import { addCostLine, setCostLineActive } from "./workflowApi";
import { validateNewCostLine, type NewCostLineDraft } from "./ModelWorkflowValidation";
import { Field, StatusNote, WorkflowDialog, useReportDirty, useReportPending, useSingleFlight, type StatusMessage } from "./workflowShared";

interface Props {
  project: string;
  data: CostLinesPayload;
  /** Re-read the canonical projection after a verified change. */
  onChanged: () => void;
}

const EMPTY: NewCostLineDraft = { group: "", label: "", amount_keur: "0", inflation_pct: "0", notes: "" };

export function CostLineManager({ project, data, onChanged }: Props) {
  const { sheet, line_management: mgmt } = data;
  const readOnlyProject = data.project.protected_reference;
  const [draft, setDraft] = useState<NewCostLineDraft>(EMPTY);
  const [showErrors, setShowErrors] = useState(false);
  const [status, setStatus] = useState<StatusMessage | null>(null);
  const [inFlight, setInFlight] = useState(false);
  const [locked, setLocked] = useState(false);
  const [retire, setRetire] = useState<CostLinePayload | null>(null);

  const eligible = useMemo(() => mgmt.eligible_groups.map((g) => g.code), [mgmt.eligible_groups]);
  const errors = validateNewCostLine(draft, sheet, eligible);
  const dirty = draft.label.trim() !== "" || draft.group !== "" ? 1 : 0;
  useReportDirty(`cost-add-${sheet}`, dirty);
  useReportPending(`cost-add-${sheet}`, inFlight || locked);
  const singleFlight = useSingleFlight();

  const cas = { project, workbookVersion: data.save.workbook_version, contentHash: data.save.content_hash };
  const disabled = readOnlyProject || inFlight || locked;

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
      setStatus({ tone: "conflict", text: "The add outcome is UNKNOWN: the canonical redirect arrived but the fresh projection could not confirm the new line. Reload to reconcile before adding again - an immediate retry could create a duplicate." });
    }
  }

  const setActive = (line: CostLinePayload, active: boolean) => (disabled ? Promise.resolve() : singleFlight(() => runSetActive(line, active)));

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

  const grouped = useMemo(() => {
    const map = new Map<string, CostLinePayload[]>();
    for (const line of data.lines) map.set(line.category, [...(map.get(line.category) ?? []), line]);
    return Array.from(map.entries());
  }, [data.lines]);
  const labelOf = (code: string) => mgmt.eligible_groups.find((g) => g.code === code)?.label ?? code;
  const idp = `wf-add-${sheet}`;

  return (
    <div className="wf-section" data-cost-line-manager={sheet}>
      <p className="wf-group-head">Add or retire {sheet === "capex" ? "CAPEX" : "OPEX"} lines</p>
      <StatusNote status={status} />
      {locked && <div className="fm-banner" role="alert"><span className="fm-demo-label">RECONCILE</span><span className="fm-banner-copy">The last change outcome is unknown. Reload the workspace before changing lines again.</span></div>}
      <div className="wf-inline-form">
        <Field id={`${idp}-group`} label="Group" error={showErrors ? errors.group : undefined}>
          {(p) => (
            <select {...p} className="fm-input" value={draft.group} disabled={disabled} onChange={(e) => setDraft({ ...draft, group: e.target.value })}>
              <option value="">Select a group…</option>
              {mgmt.eligible_groups.map((g) => <option key={g.code} value={g.code}>{g.label}</option>)}
            </select>
          )}
        </Field>
        <Field id={`${idp}-label`} label="Line label" error={showErrors ? errors.label : undefined}>
          {(p) => <input {...p} className="fm-input" value={draft.label} disabled={disabled} onChange={(e) => setDraft({ ...draft, label: e.target.value })} />}
        </Field>
        <Field id={`${idp}-amount`} label="Amount" unit="k€" error={showErrors ? errors.amount_keur : undefined}>
          {(p) => <input {...p} className="fm-input" inputMode="decimal" value={draft.amount_keur} disabled={disabled} onChange={(e) => setDraft({ ...draft, amount_keur: e.target.value })} />}
        </Field>
        {sheet === "opex" && (
          <Field id={`${idp}-infl`} label="Inflation" unit="% per year" error={showErrors ? errors.inflation_pct : undefined}>
            {(p) => <input {...p} className="fm-input" inputMode="decimal" value={draft.inflation_pct} disabled={disabled} onChange={(e) => setDraft({ ...draft, inflation_pct: e.target.value })} />}
          </Field>
        )}
        <Field id={`${idp}-notes`} label="Notes">
          {(p) => <input {...p} className="fm-input" value={draft.notes} disabled={disabled} onChange={(e) => setDraft({ ...draft, notes: e.target.value })} />}
        </Field>
        <div className="fm-toolbar">
          <button type="button" className="fm-btn fm-btn-primary" disabled={disabled} data-cost-add={sheet} onClick={() => void add()}>
            {inFlight ? "Working…" : "Add line"}
          </button>
          <button type="button" className="fm-btn" disabled={inFlight || dirty === 0}
                  onClick={() => { setDraft(EMPTY); setShowErrors(false); setStatus(null); }}>Clear</button>
        </div>
      </div>

      <div className="wf-table-wrap">
        <table className="fm-table" aria-label={`${sheet === "capex" ? "CAPEX" : "OPEX"} lines by group`}>
          <thead><tr><th scope="col">Group</th><th scope="col">Line</th><th scope="col">Amount (k€)</th><th scope="col">State</th><th scope="col"><span className="fm-sr-only">Actions</span></th></tr></thead>
          <tbody>
            {grouped.flatMap(([code, lines]) => lines.map((line) => (
              <tr key={line.sub_line_id} className={line.active ? undefined : "wf-inactive"} data-line-state={line.active ? "active" : "inactive"}>
                <td>{labelOf(code)}</td>
                <td>{line.label}</td>
                <td className="fm-mono">{String(line.amount_keur ?? "—")}</td>
                <td>{line.active ? "active" : "deactivated"}</td>
                <td>
                  {line.active
                    ? <button type="button" className="fm-btn" disabled={disabled} aria-label={`Deactivate ${line.label}`} onClick={() => setRetire(line)}>Deactivate</button>
                    : <button type="button" className="fm-btn" disabled={disabled} aria-label={`Reactivate ${line.label}`} onClick={() => void setActive(line, true)}>Reactivate</button>}
                </td>
              </tr>
            )))}
            {!data.lines.length && <tr><td colSpan={5}><span role="status">No lines are projected for this sheet.</span></td></tr>}
          </tbody>
        </table>
      </div>
      <p className="fm-info-note">Deactivation is a reversible soft delete (no hard delete exists). Derived groups and read-only groups are refused by the server. {mgmt.csrf_note}</p>
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
