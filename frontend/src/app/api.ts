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

export type CreateWorkingCopyResult =
  | { ok: true; projectCode: string }
  /** The canonical route explicitly refused (4xx with a JSON error) - nothing
   *  was created; the user may adjust and retry. */
  | { ok: false; message: string }
  /** The transport outcome could not be confirmed: the canonical route answers
   *  success with a redirect AFTER creating the copy, so a lost response does
   *  NOT prove that no Working Copy exists.  The caller must reconcile (reload
   *  the Library) and never blind-retry, which could create duplicates. */
  | { kind: "unknown"; message: string };

export function isCloneUnknown(
  result: CreateWorkingCopyResult,
): result is Extract<CreateWorkingCopyResult, { kind: "unknown" }> {
  return "kind" in result;
}

function projectCodeFromRedirectedUrl(url: string): string | null {
  try {
    return new URL(url).searchParams.get("project");
  } catch {
    return null;
  }
}

/** Working-copy creation through the EXISTING canonical `/library/clone/{id}`
 *  route (303 redirect to the new project's workbook on success, 400 JSON on a
 *  refusal, 5xx page on server failure).  Correction-A semantics apply: an
 *  ambiguous transport outcome is classified `unknown` and never retried
 *  automatically, because a retry could create a duplicate Working Copy. */
export async function createWorkingCopy(args: CreateWorkingCopyArgs): Promise<CreateWorkingCopyResult> {
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
    return {
      kind: "unknown",
      message: "The creation result is UNKNOWN: the connection failed before a definitive response. "
        + "The server may have created the Working Copy. Reload the Project Library to reconcile "
        + "before trying again - an immediate retry could create a duplicate.",
    };
  }
  if (response.ok) {
    // Success contract: 303 redirect to the new project's workbook (followed
    // automatically); the new project code travels in the final URL.
    const code = projectCodeFromRedirectedUrl(response.url);
    if (code) return { ok: true, projectCode: code };
    return {
      kind: "unknown",
      message: "The creation result is UNKNOWN: the server accepted the request but the new "
        + "project code could not be read from the response. Reload the Project Library to "
        + "reconcile before trying again - an immediate retry could create a duplicate.",
    };
  }
  if (response.status === 401) {
    return { ok: false, message: "Your session is not authorized. Sign in again; nothing was created." };
  }
  let payload: { error?: string } | null = null;
  try {
    payload = (await response.json()) as { error?: string };
  } catch {
    payload = null;
  }
  if (payload && payload.error) {
    return { ok: false, message: payload.error };
  }
  if (response.status >= 500) {
    return {
      ok: false,
      message: `Working-copy creation failed on the server (HTTP ${response.status}). `
        + "Check the Project Library before retrying so a partially created copy is not duplicated.",
    };
  }
  return { ok: false, message: `Working-copy creation failed (HTTP ${response.status}).` };
}
