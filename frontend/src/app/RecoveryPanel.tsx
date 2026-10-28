import { useRef, useState } from "react";
import type { RecoveryPayload } from "./types";

type Outcome =
  | { kind: "idle" }
  | { kind: "saving" }
  | { kind: "rejected"; message: string }
  | { kind: "stale"; message: string }
  | { kind: "unknown"; message: string };

interface RecoveryPanelProps {
  project: string;
  payload: RecoveryPayload;
  /** Called after the canonical Save committed; the workspace reloads from the server. */
  onRepaired: () => void;
}

/**
 * Working Copy recovery (SC-3).  Shown instead of the input grid when the stored draft contains a value
 * the canonical adapter cannot read.  It lists each invalid stored value with its reason and lets the
 * owner submit an explicit replacement through the EXISTING atomic grid Save (operation-bound CSRF +
 * composite CAS).  Nothing is corrected, clamped or discarded client-side, no Run is started, and the
 * panel offers no editor for protected references.
 */
export function RecoveryPanel({ project, payload, onRepaired }: RecoveryPanelProps) {
  const [values, setValues] = useState<Record<string, string>>({});
  const [outcome, setOutcome] = useState<Outcome>({ kind: "idle" });
  const inFlight = useRef(false);
  const save = payload.save;
  const editable = Boolean(save) && !payload.project.protected_reference;
  const locked = outcome.kind === "saving" || outcome.kind === "stale" || outcome.kind === "unknown";

  async function submit(fieldId: string) {
    if (!save || inFlight.current) return;
    const value = (values[fieldId] ?? "").trim();
    if (!value) {
      setOutcome({ kind: "rejected", message: "Enter a replacement value." });
      return;
    }
    inFlight.current = true;
    setOutcome({ kind: "saving" });
    try {
      let response: Response;
      try {
        response = await fetch(save.url, {
          method: "POST",
          credentials: "same-origin",
          headers: { "Content-Type": "application/json", Accept: "application/json" },
          body: JSON.stringify({
            project,
            csrf_token: save.csrf_token,
            cells: [{ field_id: fieldId, value }],
            workbook_version: save.workbook_version,
            content_hash: save.content_hash,
            scenario_id: save.scenario_id,
          }),
        });
      } catch {
        setOutcome({
          kind: "unknown",
          message: "The Save result is UNKNOWN: the connection failed before a definitive response. Reload to reconcile before saving again.",
        });
        return;
      }
      let body: Record<string, unknown> = {};
      try {
        body = (await response.json()) as Record<string, unknown>;
      } catch {
        body = {};
      }
      if (response.status === 409) {
        setOutcome({ kind: "stale", message: (body.message as string) || "The model changed since this page loaded. Reload to continue." });
      } else if (response.status === 401 || response.status === 403) {
        setOutcome({ kind: "rejected", message: "Your session is not authorized for this Save. Sign in again; nothing was changed." });
      } else if (response.ok && body.ok === true && body.model_executed === false) {
        onRepaired();
      } else {
        const cells = Array.isArray(body.cells) ? (body.cells as Array<{ field_id?: string; ok?: boolean; message?: string }>) : [];
        const bad = cells.find((c) => c.field_id === fieldId && c.ok === false);
        setOutcome({
          kind: "rejected",
          message: (bad && bad.message) || (body.message as string) || "The replacement was not accepted. Nothing was changed.",
        });
      }
    } finally {
      inFlight.current = false;
    }
  }

  return (
    <section className="rx-card" aria-labelledby="rx-recovery-heading" data-working-copy-recovery="true"
      data-recovery-code={payload.code}>
      <h2 id="rx-recovery-heading">This project needs repair</h2>
      <p className="rx-note" data-testid="react-recovery-message">{payload.recovery.message}</p>
      <p className="rx-note">
        No value was corrected, rounded, clamped or discarded, and the model was not run. A replacement is
        saved only when you submit it.
      </p>
      {payload.project.protected_reference && (
        <p className="rx-status rx-status-error" role="alert">This is a protected reference and cannot be edited.</p>
      )}
      {!payload.recovery.complete && (
        <p className="rx-note">More problems may exist; replace the listed value(s), then reload.</p>
      )}
      <ul className="rx-recovery-list" style={{ listStyle: "none", padding: 0 }}>
        {payload.recovery.issues.map((issue) => (
          <li key={`${issue.snapshot_key}:${issue.reason}`} data-recovery-issue={issue.field_id ?? issue.snapshot_key}
            style={{ marginBottom: "1rem" }}>
            <strong>{issue.label}</strong>{issue.unit ? <small> ({issue.unit})</small> : null}
            <div>Stored value: <code>{issue.stored_value === "" ? "(empty)" : issue.stored_value}</code></div>
            <div>Reason: {issue.reason}</div>
            {issue.repairable && issue.field_id && editable ? (
              <form onSubmit={(e) => { e.preventDefault(); void submit(issue.field_id as string); }}>
                <label>
                  Replacement value
                  <input type="text" inputMode="decimal" autoComplete="off" disabled={locked}
                    value={values[issue.field_id] ?? ""}
                    onChange={(e) => setValues((prev) => ({ ...prev, [issue.field_id as string]: e.target.value }))} />
                </label>{" "}
                <button type="submit" disabled={locked}>{outcome.kind === "saving" ? "Saving…" : "Replace value"}</button>
              </form>
            ) : !payload.project.protected_reference ? (
              <div>This value cannot be repaired from this view.</div>
            ) : null}
          </li>
        ))}
      </ul>
      {outcome.kind !== "idle" && outcome.kind !== "saving" && (
        <p className={`rx-status ${outcome.kind === "rejected" ? "rx-status-error" : "rx-status-conflict"}`}
          role="alert" data-recovery-outcome={outcome.kind}>
          {outcome.message}
          {(outcome.kind === "stale" || outcome.kind === "unknown") && (
            <> <button type="button" onClick={() => window.location.reload()}>Reload</button></>
          )}
        </p>
      )}
    </section>
  );
}
