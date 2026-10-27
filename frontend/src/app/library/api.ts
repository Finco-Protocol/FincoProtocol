import type { Failure, MyProjects, ProjectFilters } from "./types";

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
