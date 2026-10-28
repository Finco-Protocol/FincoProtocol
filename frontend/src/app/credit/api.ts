import type { CreditFailure, CreditPayload } from "./types";

/** Read-only GET of the credit-decision adapter.  Without Run ids the server uses the Last Run; nothing is written or run. */
export async function fetchCreditDecision(project: string, historyIds: readonly string[], signal?: AbortSignal): Promise<CreditPayload | CreditFailure> {
  const query = new URLSearchParams({ project });
  historyIds.forEach((id) => query.append("run", id));
  try {
    const response = await fetch(`/v2/model-react/analysis/credit-decision?${query}`, {
      method: "GET", credentials: "same-origin", cache: "no-store", headers: { Accept: "application/json", "X-Finco-React-Request": "1" }, redirect: "error", signal,
    });
    const body = await response.json().catch(() => null) as CreditPayload | CreditFailure | null;
    if (response.ok && body && body.ok === true) return body;
    const failed = (body ?? {}) as { code?: string; message?: string };
    return { ok: false, code: failed.code || `HTTP_${response.status}`,
      message: failed.message || (response.status === 401 ? "Your session is not authorized. Sign in again." : "The credit evidence could not be read. Nothing was changed.") };
  } catch (error) {
    if (signal?.aborted) throw error;
    return { ok: false, code: "SERVER_UNREACHABLE", message: "The FINCO Model server is unreachable. Nothing was changed." };
  }
}
