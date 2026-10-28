import type { CompareFailure, ComparePayload } from "./types";

/** Read-only GET of the compare adapter.  Two or three distinct committed Runs, explicitly selected; nothing is written. */
export async function fetchCompare(project: string, historyIds: readonly string[], signal?: AbortSignal): Promise<ComparePayload | CompareFailure> {
  if (historyIds.length < 2 || historyIds.length > 3 || new Set(historyIds).size !== historyIds.length || historyIds.some((id) => !id.trim())) {
    return { ok: false, code: "EXPLICIT_RUN_SELECTION_REQUIRED", message: "Select two or three distinct committed Runs to compare." };
  }
  const query = new URLSearchParams({ project });
  historyIds.forEach((id) => query.append("run", id));
  try {
    const response = await fetch(`/v2/model-react/compare?${query}`, {
      method: "GET", credentials: "same-origin", cache: "no-store", headers: { Accept: "application/json" }, redirect: "error", signal,
    });
    const body = await response.json().catch(() => null) as ComparePayload | CompareFailure | null;
    if (response.ok && body && body.ok === true) return body;
    const failed = (body ?? {}) as { code?: string; message?: string };
    return { ok: false, code: failed.code || `HTTP_${response.status}`,
      message: failed.message || (response.status === 401 ? "Your session is not authorized. Sign in again." : "The comparison could not be read. Nothing was changed.") };
  } catch (error) {
    if (signal?.aborted) throw error;
    return { ok: false, code: "SERVER_UNREACHABLE", message: "The FINCO Model server is unreachable. Nothing was changed." };
  }
}
