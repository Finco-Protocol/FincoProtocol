// WS-2 / M-008 — Save All request model and honest availability.
//
// Save All MUST be ONE server transaction that either commits every section or none
// (SAVE_ALL_TRANSACTION_DESIGN.md).  The client therefore never loops over the existing
// per-section writers: it builds a single typed request for a single endpoint and, while
// that endpoint is not released, reports the feature as BLOCKED instead of pretending.

import { F3_LIMIT_MESSAGE, orderedEdits, submitValue, unsupported, type EditIdentity, type PendingState } from "./pendingEdits";

/** Server capability descriptor.  Absent or `available: false` means Save All is gated. */
export interface SaveAllCapability {
  available: boolean;
  url?: string;
  csrf_token?: string;
  /** Section ids the server will accept in one transaction. */
  sections?: string[];
  reason?: string;
}

export const SAVE_ALL_BLOCKED_REASON =
  "Save All is not released yet: it needs one all-or-none server transaction across sections, which is waiting for Financial Owner path authorization. "
  + "Your changes stay staged here; save each section with its own Save button.";

export type SaveAllAvailability =
  | { state: "available"; url: string; csrfToken: string }
  | { state: "blocked"; reason: string };

export function saveAllAvailability(capability: SaveAllCapability | null | undefined): SaveAllAvailability {
  if (!capability || capability.available !== true || !capability.url || !capability.csrf_token) {
    return { state: "blocked", reason: capability?.reason || SAVE_ALL_BLOCKED_REASON };
  }
  return { state: "available", url: capability.url, csrfToken: capability.csrf_token };
}

export interface ScalarCell { field_id: string; value: string }
export interface CostLineEditWire { kind: "capex" | "opex"; sub_line_id: string; label: string; amount_keur: string; row_version: string; inflation_pct?: string }

/** Wire body of the single Save All request. */
export interface SaveAllRequest {
  project: string;
  csrf_token: string;
  workbook_version: string;
  content_hash: string;
  scenario_id: string | null;
  /** Client-generated; the server returns the stored outcome for a replay of the same id (retry/idempotency). */
  request_id: string;
  cells: ScalarCell[];
  contracts_json: string | null;
  cost_lines: CostLineEditWire[];
}

export type BuildResult = { ok: true; request: SaveAllRequest } | { ok: false; reason: string };

/**
 * Builds the single request from the staged edits.  Refuses (never partially builds) when a draft is invalid or
 * conflicted, a CAPEX/OPEX edit has no row version/label, or the PPA section has edits but no serialised document.
 * Scalar edits of the `inputs` and `financing` sections are the C0 grid cells; Financing collections (F3) are not
 * part of this request.
 */
export function buildSaveAllRequest(
  state: PendingState, identity: EditIdentity, csrfToken: string, requestId: string,
): BuildResult {
  const edits = orderedEdits(state);
  if (edits.length === 0) return { ok: false, reason: "There are no pending changes." };
  if (unsupported(state).length) return { ok: false, reason: F3_LIMIT_MESSAGE };
  if (edits.some((e) => e.error)) return { ok: false, reason: "At least one pending value is invalid." };
  if (edits.some((e) => e.conflict)) return { ok: false, reason: "At least one pending value is in conflict." };
  if (state.identity && (state.identity.contentHash !== identity.contentHash || state.identity.activeScenario !== identity.activeScenario)) {
    return { ok: false, reason: "The staged changes belong to a different version of the project. Reload and review them." };
  }

  const cells: ScalarCell[] = [];
  const lines = new Map<string, CostLineEditWire>();
  let ppaEdits = 0;
  for (const edit of edits) {
    if (edit.section === "inputs" || edit.section === "financing") {
      cells.push({ field_id: edit.key, value: submitValue(edit) });
    } else if (edit.section === "ppa") {
      ppaEdits += 1;
    } else {
      const [subLineId, column] = edit.key.split("#");
      const id = `${edit.section}:${subLineId}`;
      if (!subLineId || !edit.rowVersion || !edit.meta?.label) return { ok: false, reason: `Line ${edit.label} is missing its identity; reload and try again.` };
      const line = lines.get(id) ?? {
        kind: edit.section as "capex" | "opex", sub_line_id: subLineId, label: edit.meta.label,
        amount_keur: edit.meta.amount_keur ?? "", row_version: edit.rowVersion,
      };
      if (column === "inflation") line.inflation_pct = submitValue(edit);
      else line.amount_keur = submitValue(edit);
      lines.set(id, line);
    }
  }
  for (const line of lines.values()) if (line.amount_keur === "") return { ok: false, reason: "A cost line has no amount." };
  const contracts = state.documents.ppa ?? null;
  if (ppaEdits > 0 && contracts === null) return { ok: false, reason: "The PPA changes were not serialised; reopen the PPA section." };

  return {
    ok: true,
    request: {
      project: identity.projectId, csrf_token: csrfToken, workbook_version: identity.workbookVersion,
      content_hash: identity.contentHash, scenario_id: identity.activeScenario, request_id: requestId,
      cells, contracts_json: ppaEdits > 0 ? contracts : null, cost_lines: [...lines.values()],
    },
  };
}

export type SaveAllOutcome =
  | { kind: "saved"; contentHash: string; runState: string; savedIds: string[] }
  | { kind: "rejected"; code: string; message: string; conflicts: Record<string, { message: string }> }
  | { kind: "stale"; message: string }
  /** Network loss / unreadable answer: the commit may or may not have happened.  Reconcile by `request_id`, never re-submit blindly. */
  | { kind: "unknown"; message: string };
