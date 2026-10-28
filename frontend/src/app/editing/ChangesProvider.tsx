// WS-2 / M-008 — ChangesProvider: the ONE client-side pending-change authority.
//
// Mounted by the shell (WSV2_INTERFACE_CONTRACT.md) around the Inputs/PPA/CAPEX/OPEX/Financing
// editors so drafts survive moving between those sections for the current editing session.
// It reads the canonical identity the shell owns and never fetches, saves, runs or retries.
// Drafts live in memory only: an exit/reload is guarded by the browser's own "leave site?"
// prompt (no silent storage restore - see SAVE_ALL_TRANSACTION_DESIGN.md §Draft survival).
//
// Editors that are rendered without a shell (tests, isolated use) get a private provider from
// `EnsureChangesProvider`, so there is never a second, competing store inside one tree.

import {
  createContext, useCallback, useContext, useEffect, useMemo, useReducer, useRef,
  type ReactNode,
} from "react";
import {
  conflicted, countBySection, editId, initialState, invalid, orderedEdits, pendingReducer, totalCount,
  blockingReason, type EditConflict, type EditIdentity, type EditSection, type PendingAction, type PendingEdit,
  type PendingState, type StageInput,
} from "./pendingEdits";

export interface ChangesApi {
  state: PendingState;
  identity: EditIdentity | null;
  edits: PendingEdit[];
  total: number;
  bySection: Record<EditSection, number>;
  invalidCount: number;
  conflictCount: number;
  /** `null` = submittable. */
  blocking: string | null;
  canUndo: boolean;
  canRedo: boolean;
  get: (section: EditSection, key: string) => PendingEdit | undefined;
  stage: (edit: StageInput, options?: { coalesce?: boolean }) => void;
  stageMany: (edits: StageInput[]) => void;
  revert: (id: string) => void;
  revertSection: (section: EditSection) => void;
  discardAll: () => void;
  undo: () => void;
  redo: () => void;
  rebase: (identity: EditIdentity, baselines: Record<string, { value: string; rowVersion?: string }>) => void;
  markRejected: (conflicts: Record<string, EditConflict>) => void;
  setDocument: (section: EditSection, json: string | null) => void;
  committed: (ids: string[], identity: EditIdentity) => void;
}

const ChangesContext = createContext<ChangesApi | null>(null);

export function ChangesProvider({ identity, children }: { identity: EditIdentity | null; children: ReactNode }) {
  const [state, dispatch] = useReducer(pendingReducer, identity, initialState);
  const identityKey = identity ? `${identity.projectId}|${identity.activeScenario}|${identity.contentHash}` : "";
  const first = useRef(true);
  // A new canonical identity (reload, committed change elsewhere, scenario switch) is re-read, never rebased silently:
  // editors call `rebase` with fresh baselines; until then an identity of another scope is flagged by the reducer.
  useEffect(() => {
    if (first.current) { first.current = false; return; }
    if (identity && state.identity && identityKey !== `${state.identity.projectId}|${state.identity.activeScenario}|${state.identity.contentHash}`) {
      dispatch({ type: "rebase", identity, baselines: {} });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [identityKey]);

  const total = totalCount(state);
  useEffect(() => {
    if (total === 0) return undefined;
    const guard = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = ""; };
    window.addEventListener("beforeunload", guard);
    return () => window.removeEventListener("beforeunload", guard);
  }, [total]);

  const send = useCallback((action: PendingAction) => dispatch(action), []);
  const api = useMemo<ChangesApi>(() => ({
    state,
    identity: state.identity,
    edits: orderedEdits(state),
    total,
    bySection: countBySection(state),
    invalidCount: invalid(state).length,
    conflictCount: conflicted(state).length,
    blocking: blockingReason(state),
    canUndo: state.past.length > 0,
    canRedo: state.future.length > 0,
    get: (section, key) => state.edits[editId(section, key)],
    stage: (edit, options) => send({ type: "stage", edit, coalesce: options?.coalesce }),
    stageMany: (edits) => send({ type: "stageMany", edits }),
    revert: (id) => send({ type: "revert", id }),
    revertSection: (section) => send({ type: "revertSection", section }),
    discardAll: () => send({ type: "discardAll" }),
    undo: () => send({ type: "undo" }),
    redo: () => send({ type: "redo" }),
    rebase: (next, baselines) => send({ type: "rebase", identity: next, baselines }),
    markRejected: (conflicts) => send({ type: "markRejected", conflicts }),
    setDocument: (section, json) => send({ type: "document", section, json }),
    committed: (ids, next) => send({ type: "committed", ids, identity: next }),
  }), [state, total, send]);

  return <ChangesContext.Provider value={api}>{children}</ChangesContext.Provider>;
}

/** The pending-change store; throws when no provider is mounted (use `EnsureChangesProvider` at an editor root). */
export function useChanges(): ChangesApi {
  const api = useContext(ChangesContext);
  if (!api) throw new Error("useChanges must be used inside a ChangesProvider");
  return api;
}

export const useOptionalChanges = (): ChangesApi | null => useContext(ChangesContext);

/** Uses the shell's provider when there is one; otherwise mounts a private one for this subtree. */
export function EnsureChangesProvider({ identity, children }: { identity: EditIdentity | null; children: ReactNode }) {
  const existing = useContext(ChangesContext);
  if (existing) return <>{children}</>;
  return <ChangesProvider identity={identity}>{children}</ChangesProvider>;
}
