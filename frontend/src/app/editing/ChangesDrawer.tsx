// WS-2 / M-008 — the optional, user-toggleable Changes panel.
//
// Shows every staged edit by section (old -> new, with unit), per-field Undo, per-section Undo,
// Discard All, conflict/invalid markers and the canonical identity the drafts were staged on.
// Save All is offered only when the server publishes the all-or-none capability; otherwise it is
// shown as BLOCKED with the reason.  Nothing here runs the model.

import { useEffect, useId, useRef, useState } from "react";
import "../../styles/ws2-editing.css";
import { WorkflowDialog } from "../workflow/workflowShared";
import { useChanges } from "./ChangesProvider";
import { EDIT_SECTIONS, SECTION_LABEL, type EditSection, type PendingEdit } from "./pendingEdits";
import { saveAllAvailability, type SaveAllCapability } from "./saveAll";

const shortHash = (hash: string | undefined) => (hash ? hash.slice(0, 12) : "unknown");

function EditRow({ edit, onRevert }: { edit: PendingEdit; onRevert: () => void }) {
  const unit = edit.unit ? ` ${edit.unit}` : "";
  return (
    <li className="ws2-change" data-change-id={edit.id} data-conflict={edit.conflict?.code} data-invalid={edit.error ? "true" : undefined}>
      <div className="ws2-change-main">
        <span className="ws2-change-label">{edit.label}</span>
        <span className="ws2-change-values">
          <del aria-label="Saved value">{edit.baseline === "" ? "—" : edit.baseline}{unit}</del>
          <span aria-hidden="true"> → </span>
          <ins aria-label="New value">{edit.value === "" ? "—" : edit.value}{unit}</ins>
        </span>
        {edit.error && <span className="ws2-change-flag" role="note">Invalid: {edit.error}</span>}
        {edit.conflict && (
          <span className="ws2-change-flag" role="note" data-conflict-code={edit.conflict.code}>
            Conflict: {edit.conflict.message}{edit.conflict.serverValue !== undefined ? ` Current saved value: ${edit.conflict.serverValue}${unit}.` : ""}
          </span>
        )}
      </div>
      <button type="button" className="fm-btn ws2-change-undo" onClick={onRevert} aria-label={`Undo change to ${edit.label}`}>Undo</button>
    </li>
  );
}

export interface ChangesDrawerProps {
  /** Server capability for the all-or-none Save All (absent = BLOCKED). */
  capability?: SaveAllCapability | null;
  /** Called with the activation of an AVAILABLE Save All.  The shell owns the request and its reconciliation. */
  onSaveAll?: () => void;
  saving?: boolean;
}

export function ChangesDrawer({ capability, onSaveAll, saving = false }: ChangesDrawerProps) {
  const changes = useChanges();
  const [open, setOpen] = useState(false);
  const [confirm, setConfirm] = useState(false);
  const panelId = useId();
  const toggleRef = useRef<HTMLButtonElement>(null);
  const availability = saveAllAvailability(capability);
  const grouped = EDIT_SECTIONS.map((section) => ({ section, edits: changes.edits.filter((e) => e.section === section) })).filter((g) => g.edits.length > 0);

  // Escape closes the panel and returns focus to its toggle.
  useEffect(() => {
    if (!open) return undefined;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !confirm) { setOpen(false); toggleRef.current?.focus(); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, confirm]);

  const saveDisabled = availability.state === "blocked" || changes.blocking !== null || saving || !onSaveAll;
  const saveReason = availability.state === "blocked" ? availability.reason : changes.blocking;

  return (
    <div className="ws2-changes" data-changes-drawer={open ? "open" : "closed"}>
      <button ref={toggleRef} type="button" className="fm-btn ws2-changes-toggle" aria-expanded={open} aria-controls={panelId} data-changes-toggle="true"
              onClick={() => setOpen((v) => !v)}>
        Changes
        <span className="ws2-changes-badge" data-changes-count={changes.total} aria-label={`${changes.total} pending change${changes.total === 1 ? "" : "s"}`}>{changes.total}</span>
      </button>
      <section id={panelId} className="ws2-changes-panel" role="region" aria-label="Pending changes" hidden={!open}>
        <header className="ws2-changes-head">
          <h2>Pending changes</h2>
          <p className="rx-note" data-changes-identity="true">
            Staged on saved version <code>{shortHash(changes.identity?.contentHash)}</code>
            {changes.identity?.workbookVersion ? ` · workbook ${changes.identity.workbookVersion}` : ""}
            {` · ${changes.identity?.activeScenario ? "scenario " + changes.identity.activeScenario : "Base case"}`}.
            Nothing is saved and the model has not been run.
          </p>
        </header>
        {changes.total === 0 ? <p className="rx-note" role="status">No pending changes.</p> : (
          <>
            <div className="ws2-changes-tools">
              <button type="button" className="fm-btn" disabled={!changes.canUndo} onClick={changes.undo}>Undo last</button>
              <button type="button" className="fm-btn" disabled={!changes.canRedo} onClick={changes.redo}>Redo</button>
              <button type="button" className="fm-btn" data-changes-discard-all="true" onClick={() => setConfirm(true)}>Discard all</button>
            </div>
            {grouped.map(({ section, edits }) => (
              <div key={section} className="ws2-changes-section" data-changes-section={section}>
                <h3>{SECTION_LABEL[section as EditSection]} <span className="ws2-changes-badge">{edits.length}</span>
                  <button type="button" className="fm-btn" onClick={() => changes.revertSection(section)} aria-label={`Undo all ${SECTION_LABEL[section]} changes`}>Undo section</button>
                </h3>
                <ul>{edits.map((edit) => <EditRow key={edit.id} edit={edit} onRevert={() => changes.revert(edit.id)} />)}</ul>
              </div>
            ))}
          </>
        )}
        <footer className="ws2-changes-foot">
          <button type="button" className="fm-btn fm-btn-primary" data-save-all="true" data-save-all-state={availability.state}
                  disabled={saveDisabled} aria-describedby={`${panelId}-why`} onClick={() => onSaveAll?.()}>
            {saving ? "Saving…" : `Save all ${changes.total || ""} changes`}
          </button>
          <p id={`${panelId}-why`} className="rx-note" data-save-all-reason="true" role={availability.state === "blocked" ? "note" : undefined}>
            {saveDisabled && changes.total > 0 ? saveReason : "All sections are saved together or not at all. Saving never runs the model; the last Run becomes outdated."}
          </p>
        </footer>
      </section>
      {confirm && (
        <WorkflowDialog title="Discard all pending changes?" description={`${changes.total} staged change${changes.total === 1 ? "" : "s"} will be removed. You can still undo this from the Changes panel.`}
          confirmLabel="Discard all" cancelLabel="Keep changes" danger
          onCancel={() => setConfirm(false)} onConfirm={() => { changes.discardAll(); setConfirm(false); }} />
      )}
    </div>
  );
}
