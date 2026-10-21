import { useMemo, useState } from "react";
import { saveGridCell, type SaveOutcome } from "../api/client";
import type { FieldProjection, GridSaveSuccess, WorkbookIdentityProjection } from "../api/types";

export type SaveStatus = "idle" | "saving" | "saved" | "conflict" | "rejected" | "error";

interface CitRateFieldProps {
  field: FieldProjection;
  workbook: WorkbookIdentityProjection;
  csrfToken: string;
  saveUrl: string;
  projectCode: string;
  /** Parent must persist the new authoritative identity returned by the canonical Save. */
  onSaved: (body: GridSaveSuccess) => void;
}

function failureMessage(outcome: Extract<SaveOutcome, { kind: "rejected" | "stale" | "unauthorized" }>): string {
  const body = outcome.body;
  if (outcome.kind === "unauthorized") {
    return "Your session is not authorized for this action. Sign in again; nothing was saved.";
  }
  if (body.cells) {
    const failed = body.cells.find((c) => !c.ok);
    if (failed && failed.message) return failed.message;
  }
  if (body.message) return body.message;
  return `The server rejected the Save (${body.code}). Nothing was saved.`;
}

/**
 * The ONE editable canonical input of the PoC: `tax.assumptions.cit_rate_pct`.
 *
 * Server authority is never duplicated: the raw string is sent to the existing
 * canonical `POST /v2/workbook/grid/save`, which re-validates and applies it
 * atomically under composite CAS.  A failed Save keeps every typed character;
 * a stale conflict demands an explicit reload (no blind retry); success adopts
 * the server's new composite hash and canonical display value.
 */
export function CitRateField(props: CitRateFieldProps) {
  const { field, workbook, csrfToken, saveUrl, projectCode, onSaved } = props;
  const [draft, setDraft] = useState<string>(field.value);
  const [status, setStatus] = useState<SaveStatus>("idle");
  const [message, setMessage] = useState<string>("");
  const [reloadRequired, setReloadRequired] = useState(false);

  const inputId = "rx-cit-rate-input";
  const statusId = "rx-cit-rate-status";
  const conflict = status === "conflict" || reloadRequired;
  const disabled = !field.editable || status === "saving" || conflict;

  const describedBy = useMemo(
    () => (message ? statusId : undefined),
    [message],
  );

  async function handleSave(event: React.FormEvent) {
    event.preventDefault();
    if (disabled) return;
    setStatus("saving");
    setMessage("");
    const outcome = await saveGridCell({
      config: { project: projectCode, bootstrapUrl: "", saveUrl, legacyUrl: "" },
      csrfToken,
      contentHash: workbook.composite_hash,
      workbookVersion: workbook.version,
      scenarioId: workbook.scenario_id,
      fieldId: field.field_id,
      rawValue: draft,
    });
    switch (outcome.kind) {
      case "saved": {
        const savedValue = outcome.body.saved.find((s) => s.field_id === field.field_id);
        if (savedValue) setDraft(savedValue.value);
        onSaved(outcome.body);
        setStatus("saved");
        setMessage(
          outcome.body.run_state === "STALE"
            ? "Saved. The Working Copy is now newer than the persisted Last Run (STALE); nothing was re-run."
            : "Saved. The persisted Last Run is unchanged and was not re-run.",
        );
        break;
      }
      case "stale":
        setStatus("conflict");
        setReloadRequired(true);
        setMessage(
          outcome.body.message ||
            "The model changed since this page loaded. Reload to continue; your staged edit was not saved.",
        );
        break;
      case "rejected":
      case "unauthorized":
        setStatus(outcome.kind === "unauthorized" ? "error" : "rejected");
        setMessage(failureMessage(outcome));
        break;
      case "error":
        setStatus("error");
        setMessage(outcome.message);
        break;
    }
  }

  if (!field.editable) {
    return (
      <section className="rx-card" aria-labelledby="rx-input-heading">
        <h2 id="rx-input-heading">Working Copy input</h2>
        <div className="rx-field">
          <span className="rx-field-label">{field.label} ({field.unit ?? "%"})</span>
          <output className="rx-field-value" data-field-id={field.field_id}>{field.value}</output>
        </div>
        <p className="rx-note" role="note">
          This project is a protected reference and is read-only. Create a working copy
          in the legacy workbook to edit it.
        </p>
      </section>
    );
  }

  return (
    <section className="rx-card" aria-labelledby="rx-input-heading">
      <h2 id="rx-input-heading">Working Copy input</h2>
      <form onSubmit={handleSave}>
        <label htmlFor={inputId} className="rx-field-label">
          {field.label} ({field.unit ?? "%"})
        </label>
        <div className="rx-field-row">
          <input
            id={inputId}
            className="rx-input"
            type="text"
            inputMode="decimal"
            autoComplete="off"
            maxLength={64}
            value={draft}
            onChange={(e) => {
              setDraft(e.target.value);
              if (status === "saved" || status === "rejected") {
                setStatus("idle");
                setMessage("");
              }
            }}
            aria-describedby={describedBy}
            data-field-id={field.field_id}
          />
          <button type="submit" className="rx-button" disabled={disabled} data-save-state={status}>
            {status === "saving" ? "Saving…" : conflict ? "Reload required" : "Save"}
          </button>
        </div>
        <p id={statusId} role="status" aria-live="polite" className={`rx-status rx-status-${status}`}>
          {message}
        </p>
        <p className="rx-note">
          Validation, persistence and concurrency are enforced by the canonical server
          authority. Saving never runs the model; the Last Run is only re-classified.
        </p>
      </form>
    </section>
  );
}
