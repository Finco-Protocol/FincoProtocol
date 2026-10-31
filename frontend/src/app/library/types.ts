// RC-UX Addendum B transport contract for GET /v2/model-react/my-projects (app/v2/react_projects.py).  Every value is a saved fact of the
// caller's own project; a value that was never recorded is null and is shown as such.
export interface ProjectCard {
  lifecycle?: LifecycleCapability;
  code: string; name: string;
  technology: { key: string; label: string; pilot_tier: string };
  country: { code: string | null; label: string | null };
  capacity_mw: number | null; capacity_label: string;
  last_updated: string | null; last_run: { available: boolean; at: string | null; snapshot_id: string | null }; has_runs: boolean;
  freshness: string; status: string; archived: boolean;
  links: { open: string; scenarios: string; run_history: string };
}
export interface MyProjects {
  ok: true; projects: ProjectCard[]; total: number; total_all: number; page: number; page_size: number; total_pages: number;
  sort: string; archived: boolean;
  facets: { technologies: Array<{ key: string; label: string; count: number }>; countries: Array<{ code: string; label: string; count: number }> };
  limits: { considered: number; capped: boolean }; notes: Record<string, string>;
}
export interface Failure { ok: false; code: string; message?: string }
export interface ProjectFilters {
  search: string; technology: string; country: string; status: string; edited: string; hasRuns: boolean; sort: string; archived: boolean; page: number;
}
export const NO_FILTERS: ProjectFilters = { search: "", technology: "", country: "", status: "", edited: "", hasRuns: false, sort: "recent", archived: false, page: 1 };

export interface LifecycleCapability {
  archived: boolean; lifecycle_version: number; archive_origin: string | null;
  scope: string; can_archive: boolean; can_restore: boolean;
  tokens: { archive: string; unarchive: string };
}
