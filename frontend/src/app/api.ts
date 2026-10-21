// Authorized fetch adapters for the UX-02 React workspace.  Same-origin only;
// every mutation stays on the canonical routes (grid/save, cost-lines/save,
// library/clone, workbook/run — the latter deliberately not called from here).

import type {
  InputsPayload,
  LibraryPayload,
  StatementsPayload,
  WorkspacePayload,
} from "./types";

async function getJson<T>(url: string): Promise<T | { ok: false; code: string; message?: string }> {
  let response: Response;
  try {
    response = await fetch(url, { credentials: "same-origin", headers: { Accept: "application/json" } });
  } catch {
    return { ok: false, code: "SERVER_UNREACHABLE", message: "The FINCO Model server is unreachable." };
  }
  let body: unknown;
  try {
    body = await response.json();
  } catch {
    body = null;
  }
  if (!response.ok || !body || typeof body !== "object") {
    const failed = body as { code?: string; message?: string } | null;
    return {
      ok: false,
      code: (failed && failed.code) || `HTTP_${response.status}`,
      message: (failed && failed.message) || undefined,
    };
  }
  return body as T;
}

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

/** A Save/Run committing concurrently can invalidate one read snapshot
 *  (WORKSPACE_UNAVAILABLE); retry briefly before surfacing it. */
async function withContentionRetry<T extends { ok: boolean; code?: string }>(
  fetcher: () => Promise<T>,
): Promise<T> {
  let result = await fetcher();
  for (let attempt = 0; result.ok === false && result.code === "WORKSPACE_UNAVAILABLE" && attempt < 3; attempt += 1) {
    await sleep(600 * (attempt + 1));
    result = await fetcher();
  }
  return result;
}

export const fetchLibrary = (search: string, page: number) =>
  getJson<LibraryPayload>(`/v2/model-react/library?search=${encodeURIComponent(search)}&page=${page}`);

export const fetchWorkspace = (project: string) =>
  withContentionRetry(() =>
    getJson<WorkspacePayload>(`/v2/model-react/workspace?project=${encodeURIComponent(project)}`));

export const fetchStatements = (project: string) =>
  withContentionRetry(() =>
    getJson<StatementsPayload>(`/v2/model-react/statements?project=${encodeURIComponent(project)}`));

export const fetchInputs = (project: string) =>
  withContentionRetry(() =>
    getJson<InputsPayload>(`/v2/model-react/inputs?project=${encodeURIComponent(project)}`));

export interface CreateWorkingCopyArgs {
  cloneUrlTemplate: string;
  csrfToken: string;
  sourceProjectId: string;
  requestedName: string;
}

/** Working-copy creation through the EXISTING canonical library clone route. */
export async function createWorkingCopy(args: CreateWorkingCopyArgs): Promise<{ ok: true; projectCode: string } | { ok: false; message: string }> {
  const url = args.cloneUrlTemplate.replace("{source_project_id}", encodeURIComponent(args.sourceProjectId));
  const body = new URLSearchParams({ csrf_token: args.csrfToken });
  if (args.requestedName.trim()) body.set("requested_name", args.requestedName.trim());
  let response: Response;
  try {
    response = await fetch(url, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/x-www-form-urlencoded", Accept: "application/json" },
      body: body.toString(),
    });
  } catch {
    return { ok: false, message: "The FINCO Model server is unreachable. The working copy was not created." };
  }
  let payload: { project_code?: string; error?: string } | null = null;
  try {
    payload = (await response.clone().json()) as { project_code?: string; error?: string };
  } catch {
    payload = null;
  }
  if (response.ok && payload && payload.project_code) {
    return { ok: true, projectCode: payload.project_code };
  }
  if (response.status === 401) return { ok: false, message: "Your session is not authorized. Sign in again." };
  if (response.status === 403) return { ok: false, message: "Working-copy creation was denied for this project." };
  return {
    ok: false,
    message: (payload && payload.error) || `Working-copy creation failed (HTTP ${response.status}).`,
  };
}
