// Typed API adapters for the UX-01 React PoC.
//
// Same-origin fetches only (session cookie credentials).  There is exactly ONE
// mutation authority in this application: the existing canonical
// POST /v2/workbook/grid/save (C0 atomic batch writer with composite CAS and
// CSRF).  This client never calls any other write endpoint and never runs the
// model.

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
  | { kind: "error"; message: string };

/** One Save attempt through the canonical CAS authority.  Never retries on its
 *  own: a stale conflict (409) requires an explicit user reload. */
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
    return { kind: "error", message: "The FINCO Model server is unreachable. Nothing was saved." };
  }
  const body = await parseJson(response);
  if (response.status === 401) {
    return { kind: "unauthorized", body: (body as GridSaveFailure) || { ok: false, code: "AUTH_REQUIRED" } };
  }
  if (response.status === 409) {
    return { kind: "stale", body: (body as GridSaveFailure) || { ok: false, code: "STALE_CONTENT" } };
  }
  if (response.ok && body && typeof body === "object" && (body as GridSaveSuccess).ok === true) {
    return { kind: "saved", body: body as GridSaveSuccess };
  }
  return {
    kind: "rejected",
    body: (body as GridSaveFailure) || { ok: false, code: `HTTP_${response.status}` },
  };
}
