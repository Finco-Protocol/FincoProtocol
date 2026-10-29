// WS-2 / M-008, M-009 — the ONE mount of the pending-change store into the WS-1 shell.
//
// WS-1 exposes `WorkspaceExtensions.wrapWorkspace` (provider boundary) and `renderChanges` (drawer slot).
// This module supplies both and nothing else: no shell edit beyond passing `extensions={ws2Extensions}`.
//  * ONE ChangesProvider, keyed by project, identity taken from the shell's read-only context;
//  * pending/invalid/conflicted edits are bridged into the existing DirtyProvider so navigation and Run
//    keep a single leave guard (sections that already report their own staged count are not double counted);
//  * Save All is offered only when the server publishes the capability, sends ONE request, reconciles an
//    UNKNOWN outcome by re-sending the identical request (idempotent), and never runs the model.

import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { fetchWorkspace } from "../api";
import type { WorkspaceExtensionContext, WorkspaceExtensions } from "../workspaceExtensions";
import { useRegisterDiscard, useReportPending } from "../workflow/workflowShared";
import { ChangesDrawer } from "./ChangesDrawer";
import { ChangesProvider, useChanges } from "./ChangesProvider";
import type { EditIdentity, EditSection } from "./pendingEdits";
import { buildSaveAllRequest, saveAllAvailability, type SaveAllCapability, type SaveAllOutcome } from "./saveAll";
import { createSaveAllSession } from "./saveAllSession";
import { postSaveAll } from "./saveAllApi";

const toIdentity = (c: WorkspaceExtensionContext): EditIdentity => ({
  projectId: c.projectId, workbookVersion: c.workbookVersion, contentHash: c.contentHash,
  activeScenario: c.activeScenario, lastRunSnapshotId: c.lastRunSnapshotId,
});

/** Editors keep reporting their own unsaved counts to the existing leave guard (Run, section navigation, My Projects, external links all
 *  still ask, exactly as before).  The store only adds: an explicit "Discard changes and continue" also clears the staged drafts, so nothing
 *  discarded can reappear later, and an unresolved conflict is reported as pending. */
/** Scalar fields are shared between the assumption grid and the sheet editors (one field = one pending edit), so discarding any of those
 *  editors clears the scalar sections; the other sections map one-to-one. */
const sectionsOfDirtyKey = (key: string): EditSection[] =>
  key === "input-grid" || key.startsWith("sheet-project_setup") || key.startsWith("sheet-debt") ? ["inputs", "financing"]
    : key === "revenue-ppa" ? ["ppa"]
      : key === "cost-lines-capex" ? ["capex"]
        : key === "cost-lines-opex" ? ["opex"] : [];

function DirtyBridge() {
  const changes = useChanges();
  const registerDiscard = useRegisterDiscard();
  const revert = useRef(changes.revertSection);
  revert.current = changes.revertSection;
  useEffect(() => registerDiscard((keys) => {
    const sections = new Set(keys.flatMap(sectionsOfDirtyKey));
    sections.forEach((section) => revert.current(section));
  }), [registerDiscard]);
  useReportPending("changes-store-conflict", changes.conflictCount > 0);
  return null;
}

/** Re-reads the server-published capability whenever the saved version changes (read-only GET, same endpoint the shell uses). */
function useSaveAllCapability(project: string, contentHash: string): SaveAllCapability | null {
  const [capability, setCapability] = useState<SaveAllCapability | null>(null);
  useEffect(() => {
    let live = true;
    void fetchWorkspace(project).then((result) => {
      if (!live) return;
      const published = (result as { save_all?: SaveAllCapability } | null)?.save_all;
      setCapability(published ?? null);
    });
    return () => { live = false; };
  }, [project, contentHash]);
  return capability;
}

function Ws2Drawer({ context }: { context: WorkspaceExtensionContext }) {
  const changes = useChanges();
  const capability = useSaveAllCapability(context.projectId, context.contentHash);
  const session = useRef(createSaveAllSession());
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<{ tone: "ok" | "error" | "unknown"; text: string } | null>(null);
  const inFlight = useRef(false);

  const save = useCallback(async () => {
    const availability = saveAllAvailability(capability);
    if (availability.state !== "available" || inFlight.current || !changes.identity) return;
    const built = buildSaveAllRequest(changes.state, changes.identity, availability.csrfToken, "pending");
    if (!built.ok) { setMessage({ tone: "error", text: built.reason }); return; }
    const request = session.current.next(built.request, () => `sa-${crypto.randomUUID()}`);
    inFlight.current = true; setSaving(true); setMessage(null);
    const ids = changes.edits.map((e) => e.id);
    let outcome: SaveAllOutcome;
    try { outcome = await postSaveAll(availability.url, request); } finally { inFlight.current = false; setSaving(false); }
    if (outcome.kind === "saved") {
      session.current.settle();
      changes.committed(ids, { ...changes.identity, contentHash: outcome.contentHash || changes.identity.contentHash });
      setMessage({ tone: "ok", text: "All changes were saved together. The model was not run; the last Run is now outdated." });
      context.onCommitted();
    } else if (outcome.kind === "stale") {
      session.current.settle();
      setMessage({ tone: "error", text: `${outcome.message} Your changes are kept; reload the saved version and review them.` });
      void context.onRefetch();
    } else if (outcome.kind === "rejected") {
      session.current.settle();
      changes.markRejected(Object.fromEntries(Object.entries(outcome.conflicts).map(([id, c]) => [id, { code: "SERVER_REJECTED" as const, message: c.message }])));
      setMessage({ tone: "error", text: `${outcome.message} Nothing was saved.` });
    } else {
      setMessage({ tone: "unknown", text: outcome.message });     // the attempt is kept: pressing Save All again re-sends the identical request
    }
  }, [capability, changes, context]);

  return (
    <>
      <ChangesDrawer capability={capability} onSaveAll={() => void save()} saving={saving} />
      {message && <p className="rx-note" role={message.tone === "ok" ? "status" : "alert"} data-save-all-message={message.tone}>{message.text}</p>}
    </>
  );
}

export const ws2Extensions: WorkspaceExtensions = {
  wrapWorkspace: (context: WorkspaceExtensionContext, content: ReactNode) => (
    <ChangesProvider key={context.projectId} identity={toIdentity(context)} shell><DirtyBridge />{content}</ChangesProvider>
  ),
  renderChanges: (context: WorkspaceExtensionContext) => <Ws2Drawer context={context} />,
};
