// WS-2 / M-008 — the pending-change store (pure, framework-free).
//
// ONE staging authority for every editable section.  It never saves, never runs the model
// and never derives a financial value: it records what the user typed against the
// canonical baseline the editor was loaded with, so the Changes drawer can show old/new
// values and the (gated) Save All can submit them together.
//
// The canonical workbook identity (`EditIdentity`) is READ-ONLY input owned by the shell
// (WSV2_INTERFACE_CONTRACT.md).  `rebase` re-reads it after a reload or a committed change;
// an edit whose baseline moved is MARKED as a conflict, never silently rebased.

export type EditSection = "inputs" | "ppa" | "capex" | "opex" | "financing";
export const EDIT_SECTIONS: readonly EditSection[] = ["inputs", "ppa", "capex", "opex", "financing"];

export const SECTION_LABEL: Record<EditSection, string> = {
  inputs: "Project inputs", ppa: "Revenue & PPA", capex: "CAPEX", opex: "OPEX", financing: "Financing",
};

/** Canonical identity the drafts were staged against (owned by the shell; read-only here). */
export interface EditIdentity {
  projectId: string;
  workbookVersion: string;
  contentHash: string;
  /** Active scenario id, `null` for the Base case. */
  activeScenario: string | null;
  lastRunSnapshotId: string | null;
}

export type ConflictCode = "CHANGED_ELSEWHERE" | "SCOPE_CHANGED" | "ROW_VERSION_STALE" | "SERVER_REJECTED";

export interface EditConflict { code: ConflictCode; message: string; serverValue?: string }

export interface PendingEdit {
  /** `${section}:${key}` — unique across sections. */
  id: string;
  section: EditSection;
  /** Stable canonical key: field_id, `kind:sub_line_id` or `contract_id:field`. */
  key: string;
  label: string;
  unit: string;
  /** Canonical text the editor loaded. */
  baseline: string;
  /** Text as typed (display form of the editor, e.g. percent for PPA). */
  value: string;
  /** Row/optimistic version for per-row writers (CAPEX/OPEX `row_version`). */
  rowVersion?: string;
  /** Value to submit to the canonical writer when it differs from `value` (PPA: ratio for a typed percent). */
  canonical?: string;
  /** Invalid drafts stay visible with their message and block Save All. */
  error?: string;
  conflict?: EditConflict;
  /** Writer-specific context that is not an editable value (CAPEX/OPEX line label, contract id). */
  meta?: Record<string, string>;
  order: number;
}

export interface PendingState {
  identity: EditIdentity | null;
  edits: Record<string, PendingEdit>;
  past: Array<Record<string, PendingEdit>>;
  future: Array<Record<string, PendingEdit>>;
  /** Incrementing stage order so the drawer lists edits in the order they were made. */
  counter: number;
  /** Id of the last single-key stage, used to coalesce keystrokes into one undo step. */
  lastKey: string | null;
  /** Whole-document payload an editor serialises for its section (PPA: the canonical contracts JSON). */
  documents: Partial<Record<EditSection, string>>;
}

export const HISTORY_LIMIT = 100;

export const initialState = (identity: EditIdentity | null = null): PendingState =>
  ({ identity, edits: {}, past: [], future: [], counter: 0, lastKey: null, documents: {} });

export const editId = (section: EditSection, key: string) => `${section}:${key}`;

export interface StageInput {
  section: EditSection; key: string; label: string; unit: string;
  baseline: string; value: string; rowVersion?: string; canonical?: string; error?: string;
  meta?: Record<string, string>;
}

export type PendingAction =
  | { type: "stage"; edit: StageInput; coalesce?: boolean }
  /** Several cells as ONE undo step (TSV paste, fill). */
  | { type: "stageMany"; edits: StageInput[] }
  | { type: "revert"; id: string }
  | { type: "revertSection"; section: EditSection }
  | { type: "discardAll" }
  | { type: "undo" }
  | { type: "redo" }
  /** Re-read the canonical identity/baselines; moved baselines become conflict markers. */
  | { type: "rebase"; identity: EditIdentity; baselines: Record<string, { value: string; rowVersion?: string }> }
  | { type: "markRejected"; conflicts: Record<string, EditConflict> }
  /** An editor publishes (or clears, with `null`) the serialised document of its section. */
  | { type: "document"; section: EditSection; json: string | null }
  /** A committed Save: drop exactly the edits that were saved. */
  | { type: "committed"; ids: string[]; identity: EditIdentity };

/** A section document only lives while that section still has edits. */
function pruneDocuments(documents: PendingState["documents"], edits: Record<string, PendingEdit>): PendingState["documents"] {
  return Object.fromEntries(Object.entries(documents).filter(([section]) =>
    Object.values(edits).some((e) => e.section === section))) as PendingState["documents"];
}

function push(state: PendingState, next: Record<string, PendingEdit>, lastKey: string | null, counter = state.counter): PendingState {
  return {
    ...state, edits: next, counter, lastKey, documents: pruneDocuments(state.documents, next),
    past: [...state.past.slice(-(HISTORY_LIMIT - 1)), state.edits], future: [],
  };
}

function applyStage(edits: Record<string, PendingEdit>, input: StageInput, counter: number): { edits: Record<string, PendingEdit>; counter: number } {
  const id = editId(input.section, input.key);
  const next = { ...edits };
  if (input.value === input.baseline && !input.error) { delete next[id]; return { edits: next, counter }; }
  const previous = edits[id];
  next[id] = {
    id, section: input.section, key: input.key, label: input.label, unit: input.unit,
    baseline: input.baseline, value: input.value, rowVersion: input.rowVersion, canonical: input.canonical, error: input.error, meta: input.meta,
    conflict: previous?.conflict?.code === "SCOPE_CHANGED" ? previous.conflict : undefined,
    order: previous?.order ?? counter + 1,
  };
  return { edits: next, counter: previous ? counter : counter + 1 };
}

export function pendingReducer(state: PendingState, action: PendingAction): PendingState {
  switch (action.type) {
    case "stage": {
      const id = editId(action.edit.section, action.edit.key);
      const { edits, counter } = applyStage(state.edits, action.edit, state.counter);
      if (edits === state.edits) return state;
      if (action.coalesce && state.lastKey === id && state.past.length > 0) {
        return { ...state, edits, counter, future: [], lastKey: id };
      }
      return push(state, edits, action.coalesce ? id : null, counter);
    }
    case "stageMany": {
      let edits = state.edits, counter = state.counter;
      for (const input of action.edits) ({ edits, counter } = applyStage(edits, input, counter));
      return push(state, edits, null, counter);
    }
    case "revert": {
      if (!state.edits[action.id]) return state;
      const next = { ...state.edits }; delete next[action.id];
      return push(state, next, null);
    }
    case "revertSection": {
      const next = Object.fromEntries(Object.entries(state.edits).filter(([, e]) => e.section !== action.section));
      return Object.keys(next).length === Object.keys(state.edits).length ? state : push(state, next, null);
    }
    case "discardAll":
      return Object.keys(state.edits).length === 0 ? state : push(state, {}, null);
    case "undo": {
      const previous = state.past[state.past.length - 1];
      if (!previous) return state;
      return { ...state, edits: previous, past: state.past.slice(0, -1), future: [state.edits, ...state.future], lastKey: null };
    }
    case "redo": {
      const [next, ...rest] = state.future;
      if (!next) return state;
      return { ...state, edits: next, past: [...state.past, state.edits], future: rest, lastKey: null };
    }
    case "rebase": {
      const scopeChanged = state.identity !== null
        && (state.identity.projectId !== action.identity.projectId || state.identity.activeScenario !== action.identity.activeScenario);
      const edits: Record<string, PendingEdit> = {};
      for (const [id, edit] of Object.entries(state.edits)) {
        const fresh = action.baselines[id];
        let conflict = edit.conflict;
        let baseline = edit.baseline;
        let rowVersion = edit.rowVersion;
        if (scopeChanged) {
          conflict = { code: "SCOPE_CHANGED", message: "The active scenario or project changed after this edit was staged. Revert it or re-enter it in the new scope." };
        } else if (fresh && fresh.value !== edit.baseline) {
          // Never rebase silently: keep the typed value, show who moved, and block Save All until resolved.
          conflict = { code: "CHANGED_ELSEWHERE", message: "This value changed after you started editing.", serverValue: fresh.value };
        } else if (fresh && edit.rowVersion !== undefined && fresh.rowVersion !== undefined && fresh.rowVersion !== edit.rowVersion) {
          conflict = { code: "ROW_VERSION_STALE", message: "This line was changed after you started editing.", serverValue: fresh.value };
        } else if (conflict && conflict.code !== "SCOPE_CHANGED" && conflict.code !== "SERVER_REJECTED") {
          conflict = undefined;
        }
        edits[id] = { ...edit, baseline, rowVersion, conflict };
      }
      return { ...state, identity: action.identity, edits, lastKey: null };
    }
    case "markRejected": {
      const edits = { ...state.edits };
      for (const [id, conflict] of Object.entries(action.conflicts)) if (edits[id]) edits[id] = { ...edits[id], conflict };
      return { ...state, edits, lastKey: null };
    }
    case "document": {
      const documents = { ...state.documents };
      if (action.json === null) delete documents[action.section]; else documents[action.section] = action.json;
      return { ...state, documents };
    }
    case "committed": {
      const drop = new Set(action.ids);
      const edits = Object.fromEntries(Object.entries(state.edits).filter(([id]) => !drop.has(id)));
      // A commit moves the baseline of everything: history of dropped edits would resurrect saved values.
      return { ...state, identity: action.identity, edits, documents: pruneDocuments(state.documents, edits), past: [], future: [], lastKey: null };
    }
  }
}

// ───────────────────────────── selectors ─────────────────────────────

export const orderedEdits = (state: PendingState): PendingEdit[] =>
  Object.values(state.edits).sort((a, b) => a.order - b.order);

export function countBySection(state: PendingState): Record<EditSection, number> {
  const counts: Record<EditSection, number> = { inputs: 0, ppa: 0, capex: 0, opex: 0, financing: 0 };
  for (const edit of Object.values(state.edits)) counts[edit.section] += 1;
  return counts;
}

export const totalCount = (state: PendingState) => Object.keys(state.edits).length;

export const conflicted = (state: PendingState) => orderedEdits(state).filter((e) => e.conflict);
export const invalid = (state: PendingState) => orderedEdits(state).filter((e) => e.error);

/** Fields that have their own separately authorised editor and are never part of Save All. */
export const SAVE_ALL_EXCLUDED_KEYS: readonly string[] = ["debt.financing.instruments", "revenue.multistream.contracts"];

export const F3_LIMIT_MESSAGE =
  "Financing collections (capital stack, facilities) are not included in Save All yet. Save them with their own editor; "
  + "Save All will not claim they were saved.";

/** Pending edits Save All cannot carry (Financing collections). */
export const unsupported = (state: PendingState) =>
  orderedEdits(state).filter((e) => SAVE_ALL_EXCLUDED_KEYS.includes(e.key));

/** Why Save All must not be offered right now, or `null` when the drafts are submittable. */
export function blockingReason(state: PendingState): string | null {
  if (totalCount(state) === 0) return "There are no pending changes.";
  if (unsupported(state).length) return F3_LIMIT_MESSAGE;
  if (invalid(state).length) return "Fix the highlighted invalid values first. Nothing is saved until every value is valid.";
  if (conflicted(state).length) return "Some values changed elsewhere or in another scenario. Revert or review them first.";
  return null;
}

/** Value a canonical writer must receive for this edit. */
export const submitValue = (edit: PendingEdit) => edit.canonical ?? edit.value;
