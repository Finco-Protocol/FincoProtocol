import { useMemo, useRef, useState } from "react";
import { labelWithUnit } from "./fieldLabel";
import type { GridCategoryPayload, GridRowPayload, GridSectionPayload, InputsPayload } from "./types";
import { useDirtyTotal, useReportDirty, useReportPending, useSingleFlight } from "./workflow/workflowShared";
import { plain } from "./productLanguage";
import { classifyAttempt, type ReconcileVerdict } from "./gridReconcile";

export type GridSaveOutcome =
  | { kind: "saved"; contentHash: string; runState: string }
  | { kind: "stale"; message: string }
  | { kind: "rejected"; message: string }
  | { kind: "unknown"; message: string };

interface CanonicalInputGridProps {
  payload: InputsPayload;
  busy: boolean;
  /** Performs the canonical atomic batch Save (POST /v2/workbook/grid/save). */
  onSave: (cells: Array<{ field_id: string; value: string }>) => Promise<GridSaveOutcome>;
  /** Re-reads the canonical Inputs projection WITHOUT leaving the page (drafts survive).  `null` = the read failed. */
  onReconcile: () => Promise<InputsPayload | null>;
}

type Draft = Record<string, string>;

function flattenRows(payload: InputsPayload): GridRowPayload[] {
  return payload.grid.sections.flatMap((s) => s.categories.flatMap((c) => c.rows));
}

/**
 * Canonical Excel-like scalar grid (UX-02 / Workstream C).
 *
 * Rows come from the canonical Hybrid Inputs grid projection (the SAME builder the
 * legacy grid panel renders) — no second field registry exists client-side.  Staged
 * edits save atomically through the existing `POST /v2/workbook/grid/save` (C0
 * writer, composite CAS, CSRF, ≤50 cells).  Every Correction-A safeguard applies:
 * invalid values keep the typed draft, stale CAS blocks until reload, unknown
 * outcomes never claim success or failure, and saving never runs the model.
 * CAPEX/OPEX amounts are built from line items, so they are shown here as derived
 * totals; the line items themselves are edited in the CAPEX / OPEX editors below.
 *
 * Layout (U01): one table per section with a single header, a group row only where a
 * category has several rows, and sections that hold nothing editable collapsed by
 * default.  Every editable cell stays in the DOM and in the tab order of an open section.
 */

type RowState = "editable" | "derived" | "unavailable";

const DERIVED_REASON = /sum of line items|calculated|linked to|derived|locked by the model|computed/i;

function rowState(row: GridRowPayload, gridEditable: boolean): RowState {
  if (row.editable && gridEditable) return "editable";
  if (row.reason && DERIVED_REASON.test(row.reason)) return "derived";
  if (!row.value && !row.reason) return "unavailable";
  return row.reason ? "unavailable" : "derived";
}

const STATE_TEXT: Record<RowState, string> = { editable: "Editable", derived: "Derived", unavailable: "Not editable here" };

function sectionCounts(section: GridSectionPayload, gridEditable: boolean) {
  const counts: Record<RowState, number> = { editable: 0, derived: 0, unavailable: 0 };
  for (const category of section.categories) for (const row of category.rows) counts[rowState(row, gridEditable)] += 1;
  return counts;
}

/** A category row only adds information when it groups several rows or names something other than its single row. */
function showsGroupRow(category: GridCategoryPayload): boolean {
  return category.rows.length > 1 || (category.rows[0] !== undefined && category.rows[0].label.trim() !== category.label.trim());
}
export function CanonicalInputGrid({ payload, busy, onSave, onReconcile }: CanonicalInputGridProps) {
  const rows = useMemo(() => flattenRows(payload), [payload]);
  const [drafts, setDrafts] = useState<Draft>({});
  const { isUnresolved, setUnresolved } = useDirtyTotal();
  // An UNKNOWN / conflicting Save survives this grid unmounting (navigation): a remount starts locked.
  const [status, setStatus] = useState<"idle" | "saving" | "saved" | "conflict" | "rejected" | "unknown" | "reconciling">(
    () => (isUnresolved("input-grid") ? "unknown" : "idle"));
  const [message, setMessage] = useState(
    () => (isUnresolved("input-grid") ? "A previous Save outcome is unresolved. Reload to reconcile before saving again." : ""));
  const [activeCode, setActiveCode] = useState<string>("");
  // The last submitted batch and the composite hash it was built on: the evidence a reconciliation needs.
  const attempt = useRef<{ cells: Array<{ field_id: string; value: string }>; baselineHash: string } | null>(null);
  // Focus anchor: the disabled submit button would blur focus to <body> while a
  // Save is in flight, so focus stays on the active (readOnly, focusable) cell.
  const activeCellRef = useRef<HTMLInputElement | null>(null);
  const tableRef = useRef<HTMLTableElement>(null);

  const protectedRef = payload.project.protected_reference;
  const dirtyCodes = Object.keys(drafts).filter((code) => {
    const row = rows.find((r) => (r.field_id || r.code) === code);
    return row !== undefined && drafts[code] !== row.value;
  });
  const locked = status === "conflict" || status === "unknown" || status === "reconciling" || busy;
  const singleFlight = useSingleFlight();
  // Unsaved work: only cells whose staged value really differs from the persisted
  // one.  Unresolved work: a Save in flight, an UNKNOWN outcome or a CAS conflict.
  // Both are reported to the workspace so Run, navigation and Reload see them.
  useReportDirty("input-grid", dirtyCodes.length);
  useReportPending("input-grid", status === "saving" || status === "conflict" || status === "unknown" || status === "reconciling" || busy);

  function stage(code: string, value: string) {
    if (protectedRef || locked) return;
    setDrafts((prev) => ({ ...prev, [code]: value }));
    if (status === "saved" || status === "rejected") {
      setStatus("idle");
      setMessage("");
    }
  }

  function discard() {
    setDrafts({});
    setStatus("idle");
    setMessage("");
  }

  async function save() {
    if (protectedRef || locked || dirtyCodes.length === 0) return;
    await singleFlight(runSave);
  }

  async function runSave() {
    const cells = dirtyCodes.map((code) => ({
      field_id: rows.find((r) => (r.field_id || r.code) === code)?.field_id || code,
      value: drafts[code],
    }));
    if (cells.length > payload.save.max_cells) {
      setStatus("rejected");
      setMessage(`At most ${payload.save.max_cells} cells can be saved in one atomic batch.`);
      return;
    }
    setStatus("saving");
    setMessage("");
    activeCellRef.current?.focus();
    attempt.current = { cells, baselineHash: payload.save.content_hash };
    const outcome = await onSave(cells);
    switch (outcome.kind) {
      case "saved":
        attempt.current = null;
        setDrafts({});
        setStatus("saved");
        setMessage(outcome.runState === "STALE"
          ? "Saved. The project changed after the last Run (results outdated); nothing was re-run."
          : "Saved. The last Run is unchanged and was not re-run.");
        break;
      case "stale":
        setUnresolved("input-grid", true);
        setStatus("conflict");
        setMessage(outcome.message || "The model changed since this page loaded. Reload to continue.");
        break;
      case "rejected":
        setStatus("rejected");
        setMessage(outcome.message);
        break;
      case "unknown":
        setUnresolved("input-grid", true);
        setStatus("unknown");
        setMessage(outcome.message);
        break;
    }
  }

  /** Reconcile an UNKNOWN or conflicting Save with the canonical server state, without leaving the page and without
   *  re-sending anything.  Committed: drafts are cleared.  Not committed / changed elsewhere: drafts stay editable.
   *  The read failing keeps the grid locked (fail-closed). */
  async function reconcile() {
    const wasStatus = status;
    if (wasStatus !== "unknown" && wasStatus !== "conflict") return;
    setStatus("reconciling");
    setMessage("Checking the saved state on the server…");
    const fresh = await onReconcile();
    if (!fresh) {
      setStatus(wasStatus);
      setMessage("The saved state could not be read. Nothing was changed; check the connection and press Reload now again.");
      return;
    }
    const freshRows = flattenRows(fresh).map((r) => ({ field_id: r.field_id || r.code, value: r.value ?? "" }));
    const evidence = attempt.current;
    const verdict: ReconcileVerdict | null = evidence ? classifyAttempt(evidence, { save: fresh.save, rows: freshRows }) : null;
    setUnresolved("input-grid", false);
    attempt.current = null;
    if (verdict === "committed") {
      setDrafts({});
      setStatus("saved");
      setMessage("Reconciled: this Save had been committed on the server. It was not sent twice and the last Run was not re-run.");
    } else if (verdict === "not_committed") {
      setStatus("idle");
      setMessage("Reconciled: this Save did not reach the server, so nothing changed. Your edits are kept — press Save to retry.");
    } else if (verdict === "changed_elsewhere") {
      setStatus("idle");
      setMessage("Reconciled: the saved values changed elsewhere. Your edits are kept and are saved against the latest version only when you press Save — review them first.");
    } else {
      setStatus("idle");
      setMessage(wasStatus === "conflict"
        ? "Reloaded the latest saved state. Your staged edits are kept; review them, then Save."
        : "Reloaded the saved state. No pending Save remained to reconcile.");
    }
  }

  const editableCount = rows.filter((r) => r.editable && payload.grid.editable).length;
  const sections = payload.grid.sections.map((section) => ({ section, counts: sectionCounts(section, payload.grid.editable) }));
  // Sections with something to edit start open; purely derived ones start collapsed.  A read-only
  // grid (protected reference) has nothing editable, so every section starts open: its values ARE the content.
  const [opened, setOpened] = useState<Record<string, boolean>>({});
  const readOnlyGrid = protectedRef || payload.grid.editable === false;
  const defaultOpen = (counts: Record<RowState, number>) => counts.editable > 0 || readOnlyGrid;
  const isOpen = (id: string, counts: Record<RowState, number>) => opened[id] ?? defaultOpen(counts);
  // A section holding unsaved edits can neither collapse nor hide them: Save writes every staged cell, so each must stay visible.
  const stagedIn = (section: GridSectionPayload) => section.categories.reduce((sum, category) => sum
    + category.rows.filter((row) => dirtyCodes.includes(row.field_id || row.code)).length, 0);

  return (
    <section className="rx-card" aria-labelledby="rx-grid-heading" data-input-grid="canonical">
      <h2 id="rx-grid-heading">Assumptions</h2>
      <p className="rx-save-scope" data-save-scope="grid">
        <strong>Saves:</strong> every edited cell below, together, with <em>Save staged cells</em>. All are saved or none.
        Saving does not run the model.
      </p>
      <p className="rx-note" data-grid-meta={payload.grid.content_hash.slice(0, 12)}>
        {editableCount} editable {editableCount === 1 ? "field" : "fields"}
        {payload.grid.modified_since_run_count > 0 && ` · ${payload.grid.modified_since_run_count} changed since the last Run`}
        {" · "}Derived values follow their line items or the model and cannot be typed over.
      </p>
      {(protectedRef || payload.grid.editable === false) && (
        <p className="rx-note" role="note">
          This project is a read-only template. Start a project from this template
          (New Project → Start from a template) to edit it.
        </p>
      )}
      <div className="rx-toolbar-compact">
        <button type="button" className="rx-button rx-button-secondary" data-grid-expand-all="true"
          onClick={() => setOpened(Object.fromEntries(sections.map(({ section }) => [section.section_id, true])))}>Expand all sections</button>
        <button type="button" className="rx-button rx-button-secondary" data-grid-collapse-derived="true"
          onClick={() => setOpened(Object.fromEntries(sections.map(({ section, counts }) => [section.section_id, defaultOpen(counts)])))}>Show editable sections only</button>
      </div>
      {sections.map(({ section, counts }, sectionIndex) => (
        <details key={section.section_id} className="rx-input-section" data-grid-section={section.section_id}
          open={isOpen(section.section_id, counts) || stagedIn(section) > 0}
          onToggle={(event) => {
            const open = (event.currentTarget as HTMLDetailsElement).open;
            if (!open && stagedIn(section) > 0) { (event.currentTarget as HTMLDetailsElement).open = true; return; }
            setOpened((prev) => (prev[section.section_id] === open ? prev : { ...prev, [section.section_id]: open }));
          }}>
          <summary>
            <h3 className="rx-section-title">{section.title}</h3>
            <span className="rx-section-meta">
              {counts.editable > 0 && `${counts.editable} editable`}
              {counts.editable > 0 && (counts.derived + counts.unavailable) > 0 && " · "}
              {counts.derived > 0 && `${counts.derived} derived`}
              {counts.derived > 0 && counts.unavailable > 0 && " · "}
              {counts.unavailable > 0 && `${counts.unavailable} not editable here`}
              {stagedIn(section) > 0 && <strong className="rx-staged-count" data-staged-in-section={stagedIn(section)}> · {stagedIn(section)} unsaved edit{stagedIn(section) === 1 ? "" : "s"}</strong>}
            </span>
          </summary>
          <div className="rx-statement rx-input-scroll">
            <table ref={sectionIndex === 0 ? tableRef : undefined} className="rx-table rx-input-table" data-grid-table={section.section_id}>
              <colgroup><col className="rx-col-field" /><col className="rx-col-value" /><col className="rx-col-unit" /><col className="rx-col-status" /></colgroup>
              <thead>
                <tr>
                  <th scope="col" className="rx-rowhead">Field</th>
                  <th scope="col">Value</th>
                  <th scope="col">Unit</th>
                  <th scope="col">Status</th>
                </tr>
              </thead>
              {section.categories.map((category) => (
                <tbody key={category.code} data-grid-category={category.code}>
                  {showsGroupRow(category) && (
                    <tr className="rx-cat-row">
                      <th scope="colgroup" colSpan={4}>{category.label}{category.total_display ? ` — ${category.total_display}` : ""}</th>
                    </tr>
                  )}
                  {category.rows.map((row) => {
                    const rowKey = row.field_id || row.code;
                    const staged = drafts[rowKey];
                    const value = staged !== undefined ? staged : row.value;
                    const state = rowState(row, payload.grid.editable);
                    const editableRow = state === "editable";
                    return (
                      <tr key={`${row.code}:${row.field_id}`} data-grid-row={row.field_id || row.code} data-row-state={state}
                          className={activeCode === rowKey ? "rx-active" : undefined}>
                        <th scope="row" className="rx-rowhead">{plain(row.label)}</th>
                        <td>
                          {editableRow ? (
                            <input
                              className="rx-input rx-grid-input"
                              type="text"
                              inputMode="decimal"
                              autoComplete="off"
                              maxLength={payload.save.max_value_chars}
                              value={value}
                              readOnly={locked}
                              aria-readonly={locked || undefined}
                              data-locked={locked ? "true" : "false"}
                              aria-label={labelWithUnit(plain(row.label), row.unit)}
                              data-field-id={row.field_id}
                              data-grid-cell={row.field_id || row.code}
                              ref={(el) => {
                                if (rowKey === activeCode) activeCellRef.current = el;
                              }}
                              onFocus={() => setActiveCode(rowKey)}
                              onChange={(e) => {
                                stage(rowKey, e.target.value);
                              }}
                            />
                          ) : (
                            <span data-locked-value={row.field_id || row.code} title={row.reason || "Read-only"}>{value || "—"}</span>
                          )}
                        </td>
                        <td>{row.unit}</td>
                        <td className="rx-note rx-status-cell">
                          <span className={`rx-state rx-state-${state}`}>{STATE_TEXT[state]}</span>
                          {row.reason
                            ? <span className="rx-state-reason"> {row.reason}</span>
                            : row.modified_since_run
                              ? <span className="rx-state-reason"> Changed since Last Run (was {row.baseline || "—"})</span>
                              : staged !== undefined && staged !== row.value
                                ? <span className="rx-state-reason"> Staged edit</span>
                                : null}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              ))}
            </table>
          </div>
        </details>
      ))}
      <div className="rx-field-row" style={{ marginTop: "0.75rem" }}>
        <button
          type="button"
          id="rx-grid-save"
          className="rx-button"
          disabled={protectedRef || dirtyCodes.length === 0 || locked || busy}
          data-save-state={status}
          data-dirty-count={dirtyCodes.length}
          onClick={() => void save()}
        >
          {status === "saving" ? "Saving…"
            : status === "reconciling" ? "Checking…"
            : status === "unknown" ? "Reload to reconcile"
              : status === "conflict" ? "Reload required"
                : `Save ${dirtyCodes.length || ""} staged ${dirtyCodes.length === 1 ? "cell" : "cells"}`}
        </button>
        {dirtyCodes.length > 0 && !locked && (
          <button type="button" className="rx-button rx-button-secondary" onClick={discard} data-discard="true">
            Discard staged edits
          </button>
        )}
        {(status === "conflict" || status === "unknown") && (
          <button type="button" className="rx-button rx-button-secondary" data-reconcile-button="true" onClick={() => void reconcile()}>
            Reload now
          </button>
        )}
      </div>
      <p id="rx-grid-status" role="status" aria-live="polite" className={`rx-status rx-status-${status}`}>
        {message}
      </p>
      <p className="rx-note">{payload.cost_line_boundary.note}</p>
    </section>
  );
}
