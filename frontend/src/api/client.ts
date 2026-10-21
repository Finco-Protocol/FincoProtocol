// Typed API adapters for the UX-01 React PoC.
//
// Same-origin fetches only (session cookie credentials).  There is exactly ONE
// mutation authority in this application: the existing canonical
// POST /v2/workbook/grid/save (C0 atomic batch writer with composite CAS and
// CSRF).  This client never calls any other write endpoint and never runs the
// model.
//
// Save outcomes are strictly classified (Correction A): the canonical server is
// the ONLY persistence authority, and a lost or unreadable response is NOT
// evidence that nothing was saved.  Ambiguous transports surface as
// `unknown` outcomes that require explicit user reconciliation — never an
// automatic retry.

import type {
  BootstrapError,
  BootstrapPayload,
  GridSaveFailure,
  GridSaveSuccess,
} from "./types";

export interface HostConfig {
  project: string;
  bootstrapUrl: string;
  saveUrl: string;
  legacyUrl: string;
}

export function readHostConfig(root: HTMLElement | null): HostConfig | null {
  if (!root) return null;
  const project = (root.dataset.project || "").trim();
  const bootstrapUrl = (root.dataset.bootstrapUrl || "").trim();
  const saveUrl = (root.dataset.saveUrl || "").trim();
  const legacyUrl = (root.dataset.legacyUrl || "").trim();
  if (!bootstrapUrl || !saveUrl || !legacyUrl) return null;
  return { project, bootstrapUrl, saveUrl, legacyUrl };
}

async function parseJson(response: Response): Promise<unknown> {
  try {
    return await response.json();
  } catch {
    return null;
  }
}

export async function fetchBootstrap(config: HostConfig): Promise<BootstrapPayload | BootstrapError> {
  const url = `${config.bootstrapUrl}?project=${encodeURIComponent(config.project)}`;
  let response: Response;
  try {
    response = await fetch(url, { credentials: "same-origin", headers: { Accept: "application/json" } });
  } catch {
    return { ok: false, code: "WORKSPACE_UNAVAILABLE", message: "The FINCO Model server is unreachable." };
  }
  const body = await parseJson(response);
  if (!response.ok || !body || typeof body !== "object") {
    const failed = body as Partial<BootstrapError> | null;
    return {
      ok: false,
      code: (failed && failed.code) || "WORKSPACE_UNAVAILABLE",
      message: (failed && failed.message) || undefined,
    };
  }
  const payload = body as BootstrapPayload;
  if (payload.ok !== true || !payload.field || !payload.outputs) {
    return { ok: false, code: "WORKSPACE_UNAVAILABLE" };
  }
  return payload;
}

export interface SaveInputArgs {
  config: HostConfig;
  csrfToken: string;
  contentHash: string;
  workbookVersion: string;
  scenarioId: string | null;
  fieldId: string;
  rawValue: string;
}

export type SaveOutcome =
  | { kind: "saved"; body: GridSaveSuccess }
  | { kind: "stale"; body: GridSaveFailure }
  | { kind: "rejected"; body: GridSaveFailure }
  | { kind: "unauthorized"; body: GridSaveFailure }
  /** The transaction result could not be confirmed.  The canonical server may
   *  have committed.  Requires explicit user reconciliation; never retried
   *  automatically. */
  | { kind: "unknown"; reason: SaveOutcomeUnknownReason; message: string };

export type SaveOutcomeUnknownReason =
  /** The request never reached a definitive response (connection failure, drop
   *  mid-response).  A commit may or may not have happened. */
  | "no_definitive_response"
  /** The server answered 2xx but the body was missing, malformed or not a
   *  canonical Save verdict — persistence cannot be confirmed either way. */
  | "unverifiable_response"
  /** The server answered 5xx; an error after a possible commit cannot be
   *  distinguished from an error before it. */
  | "server_error";

/** Confirmed canonical verdicts (success OR an explicit server refusal). */
export type SaveVerdict = Extract<SaveOutcome, { kind: "saved" | "stale" | "rejected" | "unauthorized" }>;

function isCanonicalVerdict(body: unknown): body is GridSaveSuccess | GridSaveFailure {
  return Boolean(body) && typeof body === "object" && "ok" in (body as Record<string, unknown>);
}

const CANONICAL_RUN_STATES = new Set(["NOT_RUN", "CURRENT", "STALE"]);

/**
 * A response counts as a confirmed canonical Save success ONLY when it carries
 * every mandatory field of the grid/save contract.  A bare `{"ok": true}` (or
 * any success-shaped body with missing/mistyped fields) is NOT sufficient
 * evidence of persistence: the workbook identity must never be updated from an
 * incomplete verdict, so such responses are treated as UNKNOWN.
 */
function isCanonicalSaveSuccess(body: unknown): body is GridSaveSuccess {
  if (!body || typeof body !== "object") return false;
  const b = body as Record<string, unknown>;
  if (b.ok !== true || !Array.isArray(b.saved) || b.saved.length === 0) return false;
  const savedOk = (b.saved as unknown[]).every((s) => {
    if (!s || typeof s !== "object") return false;
    const cell = s as Record<string, unknown>;
    return typeof cell.field_id === "string" && cell.field_id.length > 0
      && typeof cell.value === "string";
  });
  return savedOk
    && typeof b.content_hash === "string" && b.content_hash.length > 0
    && typeof b.workbook_version === "string" && b.workbook_version.length > 0
    && typeof b.run_state === "string" && CANONICAL_RUN_STATES.has(b.run_state)
    && b.model_executed === false
    && (b.scenario_id === null || typeof b.scenario_id === "string");
}

/** One Save attempt through the canonical CAS authority.  Never retries on its
 *  own: a stale conflict (409) requires an explicit user reload, and an
 *  ambiguous transport requires explicit reconciliation. */
export async function saveGridCell(args: SaveInputArgs): Promise<SaveOutcome> {
  let response: Response;
  try {
    response = await fetch(args.config.saveUrl, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({
        project: args.config.project,
        csrf_token: args.csrfToken,
        cells: [{ field_id: args.fieldId, value: args.rawValue }],
        workbook_version: args.workbookVersion,
        content_hash: args.contentHash,
        scenario_id: args.scenarioId,
      }),
    });
  } catch {
    return {
      kind: "unknown",
      reason: "no_definitive_response",
      message: "The Save result is UNKNOWN: the connection failed before a definitive response. "
        + "The server may have committed this Save. Your edit is kept below — reload to "
        + "reconcile with the server before saving again.",
    };
  }
  const body = await parseJson(response);
  if (response.status === 401) {
    return { kind: "unauthorized", body: (body as GridSaveFailure) || { ok: false, code: "AUTH_REQUIRED" } };
  }
  if (response.status === 409) {
    return { kind: "stale", body: (body as GridSaveFailure) || { ok: false, code: "STALE_CONTENT" } };
  }
  // Confirmed canonical verdicts: the grid/save contract answers every 4xx with
  // a JSON verdict and guarantees nothing was persisted on those paths.
  if (response.status < 500 && isCanonicalVerdict(body)) {
    if (response.ok) {
      // Only a COMPLETE canonical success may update the workbook identity;
      // anything success-shaped but incomplete is unverifiable.
      if (isCanonicalSaveSuccess(body)) {
        return { kind: "saved", body };
      }
      return {
        kind: "unknown",
        reason: "unverifiable_response",
        message: "The Save result is UNKNOWN: the server answered success status but the response "
          + "was not a readable canonical Save verdict. The server may have committed this Save. "
          + "Your edit is kept below — reload to reconcile with the server before saving again.",
      };
    }
    if ((body as GridSaveFailure).ok === false) {
      return { kind: "rejected", body: body as GridSaveFailure };
    }
  }
  if (response.ok) {
    return {
      kind: "unknown",
      reason: "unverifiable_response",
      message: "The Save result is UNKNOWN: the server answered success status but the response "
        + "was not a readable canonical Save verdict. The server may have committed this Save. "
        + "Your edit is kept below — reload to reconcile with the server before saving again.",
    };
  }
  if (response.status >= 500) {
    return {
      kind: "unknown",
      reason: "server_error",
      message: "The Save result is UNKNOWN: the server reported an error that could have occurred "
        + "after committing. The server may have committed this Save. Your edit is kept below — "
        + "reload to reconcile with the server before saving again.",
    };
  }
  // 4xx without a canonical verdict: per the canonical route contract, no 4xx
  // path persists anything, so this is a confirmed rejection with an
  // unidentified reason.
  return {
    kind: "rejected",
    body: { ok: false, code: `HTTP_${response.status}` },
  };
}
