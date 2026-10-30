import type { Failure, MyProjects, ProjectFilters, LifecycleCapability } from "./types";

export async function fetchMyProjects(filters: ProjectFilters, signal?: AbortSignal): Promise<MyProjects | Failure> {
  const params = new URLSearchParams();
  if (filters.search.trim()) params.set("search", filters.search.trim());
  if (filters.technology) params.set("technology", filters.technology);
  if (filters.country) params.set("country", filters.country);
  if (filters.status) params.set("status", filters.status);
  if (filters.edited) params.set("edited", filters.edited);
  if (filters.hasRuns) params.set("has_runs", "1");
  if (filters.archived) params.set("archived", "1");
  params.set("sort", filters.sort);
  params.set("page", String(filters.page));
  try {
    const response = await fetch(`/v2/model-react/my-projects?${params}`, { credentials: "same-origin", cache: "no-store", headers: { Accept: "application/json" }, signal });
    const body = await response.json().catch(() => null) as (MyProjects | Failure) | null;
    if (response.ok && body && body.ok === true) return body;
    const failed = (body ?? {}) as { code?: string; message?: string };
    return { ok: false, code: failed.code || `HTTP_${response.status}`, message: failed.message };
  } catch (error) {
    if ((error as { name?: string })?.name === "AbortError") return { ok: false, code: "CANCELLED" };
    return { ok: false, code: "SERVER_UNREACHABLE" };
  }
}

/** Pending (unresolved) request keys are held in MEMORY ONLY, per page. The RC5 production quarantine forbids any browser-side persistence
 *  (web storage, IndexedDB), so a full reload honestly loses the key: it is then treated as unknown, the authoritative server state is
 *  re-read, and any new action starts from the server's current lifecycle version, where server-side CAS and idempotent receipts prevent a
 *  duplicate transition. The key holds no token or financial data and is namespaced by the server's owner/project scope. */
const pendingRequests = new Map<string, unknown>();
export function pendingRequest<T>(key: string): T | undefined { return pendingRequests.get(key) as T | undefined; }
export function retainPendingRequest(key: string, value: unknown): void { pendingRequests.set(key, value); }
export function releasePendingRequest(key: string): void { pendingRequests.delete(key); }

export async function changeLifecycle(code: string, capability: LifecycleCapability): Promise<{ confirmed: boolean; message: string }> {
  const storage = `finco-wf03-lifecycle:${capability.scope}`;
  type Attempt = { action: "archive" | "unarchive"; request_id: string; expected_archived: boolean; lifecycle_version: number };
  let attempt: Attempt;
  try {
    const prior = pendingRequest<Attempt>(storage);
    attempt = prior ?? {
      action: capability.archived ? "unarchive" : "archive",
      request_id: crypto.randomUUID().replace(/-/g, ""),
      expected_archived: capability.archived, lifecycle_version: capability.lifecycle_version,
    };
    if (!/^[a-f0-9]{32}$/.test(attempt.request_id) || !["archive", "unarchive"].includes(attempt.action)
        || typeof attempt.expected_archived !== "boolean" || !Number.isSafeInteger(attempt.lifecycle_version)) {
      return { confirmed: false, message: "The pending request could not be read. Keep this tab open and reconcile its status before another action." };
    }
    retainPendingRequest(storage, attempt);
  } catch {
    return { confirmed: false, message: "The pending request could not be retained. No new action was sent." };
  }
  const root = `/library/projects/${encodeURIComponent(code)}`;
  const reconcile = async () => {
    const result = await fetch(`${root}/lifecycle/status?request_id=${attempt.request_id}`, { credentials: "same-origin", cache: "no-store" });
    const body = await result.json().catch(() => null) as { ok?: boolean; outcome?: string } | null;
    return result.ok && body?.ok === true && body.outcome === "COMMITTED";
  };
  let definiteRefusal = false;
  try {
    const { action, ...body } = attempt;
    const result = await fetch(`${root}/${action}`, { method: "POST", credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRF-Token": capability.tokens[action] }, body: JSON.stringify(body) });
    const outcome = await result.json().catch(() => null) as { ok?: boolean } | null;
    if (result.ok && outcome?.ok === true) {
      releasePendingRequest(storage);
      return { confirmed: true, message: "The lifecycle action is confirmed. The model was not run." };
    }
    definiteRefusal = result.status >= 400 && result.status < 500;
  } catch { /* A lost response must be reconciled using the SAME key. */ }
  try {
    if (await reconcile()) {
      releasePendingRequest(storage);
      return { confirmed: true, message: "The original action was confirmed. Review the current project state." };
    }
    if (definiteRefusal) {
      releasePendingRequest(storage);
      return { confirmed: true, message: "The action was refused. Refresh and review the current project state before trying again." };
    }
  } catch { /* UNKNOWN is not failure or success; the pending key stays. */ }
  return { confirmed: false, message: "The result is unknown. Keep the same request and select the action again to reconcile; do not create a new request." };
}
