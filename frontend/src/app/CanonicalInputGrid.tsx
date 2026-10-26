import { useMemo, useRef, useState } from "react";
import type { GridRowPayload, InputsPayload } from "./types";
import { useReportDirty, useReportPending, useSingleFlight } from "./workflow/workflowShared";

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
  onRefresh: () => void;
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
 * CAPEX/OPEX line items stay read-only navigation here (their canonical cost-line
 * batch writer is deliberately out of scope — C6).
 */
export function CanonicalInputGrid({ payload, busy, onSave, onRefresh }: CanonicalInputGridProps) {
  const rows = useMemo(() => flattenRows(payload), [payload]);
  const [drafts, setDrafts] = useState<Draft>({});
  const [status, setStatus] = useState<"idle" | "saving" | "saved" | "conflict" | "rejected" | "unknown">("idle");
  const [message, setMessage] = useState("");
  const [activeCode, setActiveCode] = useState<string>("");
  // Focus anchor: the disabled submit button would blur focus to <body> while a
  // Save is in flight, so focus stays on the active (readOnly, focusable) cell.
  const activeCellRef = useRef<HTMLInputElement | null>(null);
  const tableRef = useRef<HTMLTableElement>(null);

  const protectedRef = payload.project.protected_reference;
  const dirtyCodes = Object.keys(drafts).filter((code) => {
    const row = rows.find((r) => (r.field_id || r.code) === code);
    return row !== undefined && drafts[code] !== row.value;
  });
  const locked = status === "conflict" || status === "unknown" || busy;
  const singleFlight = useSingleFlight();
  // Unsaved work: only cells whose staged value really differs from the persisted
  // one.  Unresolved work: a Save in flight, an UNKNOWN outcome or a CAS conflict.
  // Both are reported to the workspace so Run, navigation and Reload see them.
  useReportDirty("input-grid", dirtyCodes.length);
  useReportPending("input-grid", status === "saving" || status === "conflict" || status === "unknown" || busy);

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
    const outcome = await onSave(cells);
    switch (outcome.kind) {
      case "saved":
        setDrafts({});
        setStatus("saved");
        setMessage(outcome.runState === "STALE"
          ? "Saved. The Working Copy is now newer than the persisted Last Run (STALE); nothing was re-run."
          : "Saved. The persisted Last Run is unchanged and was not re-run.");
        break;
      case "stale":
        setStatus("conflict");
        setMessage(outcome.message || "The model changed since this page loaded. Reload to continue.");
        break;
      case "rejected":
        setStatus("rejected");
        setMessage(outcome.message);
        break;
      case "unknown":
        setStatus("unknown");
        setMessage(outcome.message);
        break;
    }
  }

  const editableCount = rows.filter((r) => r.editable && payload.grid.editable).length;

  return (
    <section className="rx-card" aria-labelledby="rx-grid-heading" data-input-grid="canonical">
      <h2 id="rx-grid-heading">Inputs — Working Copy grid</h2>
      <p className="rx-note" data-grid-meta={payload.grid.content_hash.slice(0, 12)}>
        {editableCount} editable scalar {editableCount === 1 ? "field" : "fields"}
        {payload.grid.modified_since_run_count > 0 && ` · ${payload.grid.modified_since_run_count} modified since the Last Run`}
        {" · "}
        {payload.grid.baseline_note || "Edits save atomically through the canonical server authority; the model is never run."}
      </p>
      {(protectedRef || payload.grid.editable === false) && (
        <p className="rx-note" role="note">
          This project is a protected reference and is read-only. Create a working copy
          in the Project Library to edit it.
        </p>
      )}
      {payload.grid.sections.map((section) => (
        <div key={section.section_id} data-grid-section={section.section_id}>
          <h3 className="rx-section-title">{section.title}</h3>
          {section.categories.map((category) => (
            <div key={category.code} data-grid-category={category.code}>
              <p className="rx-category">
                {category.label}
                {category.total_display ? ` — ${category.total_display}` : ""}
              </p>
              <div className="rx-statement" style={{ overflowX: "auto" }}>
                <table ref={category === payload.grid.sections[0]?.categories[0] ? tableRef : undefined}
                       className="rx-table rx-input-table" data-grid-table={section.section_id}>
                  <thead>
                    <tr>
                      <th scope="col" className="rx-rowhead">Field</th>
                      <th scope="col">Value</th>
                      <th scope="col">Unit</th>
                      <th scope="col">Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {category.rows.map((row) => {
                      const rowKey = row.field_id || row.code;
                      const staged = drafts[rowKey];
                      const value = staged !== undefined ? staged : row.value;
                      const editableRow = row.editable && payload.grid.editable;
                      return (
                        <tr key={`${row.code}:${row.field_id}`} data-grid-row={row.field_id || row.code}
                            className={activeCode === rowKey ? "rx-active" : undefined}>
                          <th scope="row" className="rx-rowhead">{row.label}</th>
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
                                aria-label={`${row.label}${row.unit ? ` (${row.unit})` : ""}`}
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
                          <td className="rx-note">
                            {row.reason
                              ? row.reason
                              : row.modified_since_run
                                ? `Modified since Last Run (was ${row.baseline || "—"})`
                                : staged !== undefined && staged !== row.value
                                  ? "Staged edit"
                                  : ""}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          ))}
        </div>
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
          <button type="button" className="rx-button rx-button-secondary" data-reconcile-button="true" onClick={onRefresh}>
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
