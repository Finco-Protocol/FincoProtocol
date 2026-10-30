import { useCallback, useEffect, useRef, useState, type MouseEvent } from "react";
import "../finco/_group.css";
import "../styles/finco-live.css";
import "../styles/rcm-new-project.css";
import "../styles/rcux-product.css";
import { Shell } from "../finco/_shared/FincoShell";
import { fetchMyProjects, changeLifecycle } from "./library/api";
import { NO_FILTERS, type MyProjects, type ProjectCard, type ProjectFilters } from "./library/types";
import { FriendlyError } from "./productLanguage";
import { RunIdentityLabel } from "./runIdentity";

const EDITED = [["", "Any time"], ["7", "Last 7 days"], ["30", "Last 30 days"], ["90", "Last 90 days"]] as const;
const STATUSES = [["", "Any status"], ["not_run", "Not run yet"], ["current", "Results up to date"], ["outdated", "Results outdated"]] as const;
const SORTS = [["recent", "Recently updated"], ["name", "Name (A–Z)"], ["last_run", "Last Run"]] as const;

/** Saved timestamps are shown exactly (UTC, minute precision); the full instant is in the tooltip. */
export function formatSaved(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "—" : `${d.toISOString().slice(0, 10)} ${d.toISOString().slice(11, 16)} UTC`;
}
const capacityText = (p: ProjectCard) => (p.capacity_mw === null ? "—" : `${p.capacity_mw.toLocaleString("en-GB", { maximumFractionDigits: 2 })} MW`);

function statusClass(freshness: string): string {
  return freshness === "CURRENT" ? "rcux-status ok" : freshness === "STALE" ? "rcux-status warn" : "rcux-status";
}

function go(event: MouseEvent<HTMLAnchorElement>, to: () => void) {
  if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
  event.preventDefault();
  to();
}

function filtersFromUrl(): ProjectFilters {
  const q = new URLSearchParams(window.location.search);
  return { ...NO_FILTERS, search: q.get("search") || "", technology: q.get("technology") || "", country: q.get("country") || "",
    status: q.get("status") || "", edited: q.get("edited") || "", hasRuns: q.get("has_runs") === "1",
    archived: q.get("archived") === "1", sort: q.get("sort") || "recent",
    page: Number.isSafeInteger(Number(q.get("page"))) && Number(q.get("page")) > 0 ? Number(q.get("page")) : 1 };
}

/** My Projects: the user's own saved projects and work history.  System templates are not projects and never appear here —
 *  they are chosen when creating a project. */
export function LibraryView({ onOpenProject }: { onOpenProject: (code: string) => void }) {
  const [filters, setFilters] = useState<ProjectFilters>(filtersFromUrl);
  const [searchInput, setSearchInput] = useState(() => filtersFromUrl().search);
  const [data, setData] = useState<MyProjects | null>(null);
  const [error, setError] = useState<{ code: string; message?: string } | null>(null);
  const [loading, setLoading] = useState(true);
  const [lifecycleBusy, setLifecycleBusy] = useState("");
  const [lifecycleMessage, setLifecycleMessage] = useState("");
  const fromHistory = useRef(false);
  const restoreScroll = useRef<number | null>(null);
  /** Monotonic ticket of the newest list request: an older answer (e.g. the post-Archive refresh of the ACTIVE list arriving after the user opened
   *  "Show archived projects") must never replace the newer view. Aborted requests are already discarded; the lifecycle refresh is not abortable. */
  const latestLoad = useRef(0);

  useEffect(() => {
    const changed = (event: PopStateEvent) => {
      fromHistory.current = true;
      restoreScroll.current = (event.state as { wf03Scroll?: number } | null)?.wf03Scroll ?? 0;
      const next = filtersFromUrl(); setFilters(next); setSearchInput(next.search);
    };
    window.addEventListener("popstate", changed);
    return () => window.removeEventListener("popstate", changed);
  }, []);
  useEffect(() => {
    if (fromHistory.current) { fromHistory.current = false; return; }
    const q = new URLSearchParams();
    for (const key of ["search", "technology", "country", "status", "edited"] as const) if (filters[key]) q.set(key, filters[key]);
    if (filters.sort !== "recent") q.set("sort", filters.sort);
    if (filters.archived) q.set("archived", "1");
    if (filters.hasRuns) q.set("has_runs", "1");
    if (filters.page > 1) q.set("page", String(filters.page));
    const query = q.toString();
    if (query !== window.location.search.slice(1)) {
      window.history.replaceState({ ...window.history.state, wf03Scroll: window.scrollY }, "");
      window.history.pushState({ wf03Scroll: window.scrollY }, "", `${window.location.pathname}${query ? `?${query}` : ""}${window.location.hash}`);
    }
  }, [filters]);

  const load = useCallback(async (signal?: AbortSignal) => {
    const ticket = ++latestLoad.current;
    setLoading(true);
    const result = await fetchMyProjects(filters, signal);
    if (signal?.aborted || ticket !== latestLoad.current) return;
    if (result.ok) {
      setData(result); setError(null);
      if (restoreScroll.current !== null) {
        const top = restoreScroll.current; restoreScroll.current = null;
        requestAnimationFrame(() => window.scrollTo({ top }));
      }
    } else if (result.code !== "CANCELLED") setError(result);
    setLoading(false);
  }, [filters]);

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load]);

  const patch = (change: Partial<ProjectFilters>) => setFilters((f) => ({ ...f, ...change, page: change.page ?? 1 }));
  const filtered = filters.search !== "" || filters.technology !== "" || filters.country !== "" || filters.status !== "" || filters.edited !== "" || filters.hasRuns;
  const newProject = (path = "") => { window.location.hash = `new-project${path}`; };
  const lifecycleAction = async (project: ProjectCard) => {
    if (!project.lifecycle || lifecycleBusy) return;
    if (!project.archived && !window.confirm(`Archive ${project.name}? Saved inputs and Run history will be preserved.`)) return;
    setLifecycleBusy(project.code);
    try {
      const result = await changeLifecycle(project.code, project.lifecycle);
      setLifecycleMessage(result.message);
      if (result.confirmed) await load();
    } finally { setLifecycleBusy(""); }
  };

  if (error && !data) {
    return (
      <Shell crumb="My Projects" dataOrigin="canonical-run" originLabel="LIBRARY UNAVAILABLE">
        <main className="rx-page" role="main">
          <section className="rx-card" data-library-state={error.code}>
            <h2>My Projects is unavailable</h2>
            <FriendlyError code={error.code} message={error.message} />
            <p><button type="button" className="rx-button" onClick={() => void load()}>Try again</button></p>
          </section>
        </main>
      </Shell>
    );
  }
  if (!data) return <main className="rx-page" role="main"><p className="rx-boot-loading" role="status">Loading your projects…</p></main>;

  const empty = data.total_all === 0 && !data.archived;
  return (
    <Shell crumb="My Projects" dataOrigin="canonical-run" originLabel="MY PROJECTS">
      <main className="rx-page" role="main" data-library-view="true" id="fm-main-content" tabIndex={-1}>
        <header className="rx-header rcux-lib-head">
          <div>
            <p className="rx-brand">FINCO Protocol · Model</p>
            <h1 className="rx-title">My Projects</h1>
          </div>
          <div className="rcux-actions">
            <a className="rx-button rcm-new-project-cta" href="/v2/model-react/#new-project" data-new-project-cta="true"
               onClick={(e) => go(e, () => newProject())}>+ New Project</a>
            <a className="rx-button rx-button-secondary" href="/v2/model-react/#compare-projects" data-compare-projects-cta="true">Compare projects</a>
            <a className="rx-button rx-button-secondary" href="/v2/model-react/#new-project/template" data-choose-template-cta="true"
               onClick={(e) => go(e, () => newProject("/template"))}>Choose a template</a>
          </div>
        </header>
        <p><button type="button" className="rx-button rx-button-secondary" aria-pressed={filters.archived}
          onClick={() => patch({ archived: !filters.archived })}>{filters.archived ? "Show active projects" : "Show archived projects"}</button></p>
        {lifecycleMessage && <p className="rx-note" role="status">{lifecycleMessage}</p>}

        {empty ? (
          <section className="rx-card rcux-empty" data-library-empty="true" aria-labelledby="rcux-empty-h">
            <h2 id="rcux-empty-h">No projects yet.</h2>
            <p className="rx-note">Create your first project or start from a template.</p>
            <div className="rcux-actions" style={{ justifyContent: "center", display: "flex", gap: 8, flexWrap: "wrap" }}>
              <a className="rx-button" href="/v2/model-react/#new-project" data-empty-new-project="true" onClick={(e) => go(e, () => newProject())}>New Project</a>
              <a className="rx-button rx-button-secondary" href="/v2/model-react/#new-project/template" data-empty-choose-template="true"
                 onClick={(e) => go(e, () => newProject("/template"))}>Choose a Template</a>
            </div>
          </section>
        ) : (
          <>
            <form className="rcux-filters" role="search" aria-label="Find a project" data-library-filters="true"
                  onSubmit={(e) => { e.preventDefault(); patch({ search: searchInput }); }}>
              <label>Search
                <input type="search" value={searchInput} placeholder="Project name" data-filter-search="true" onChange={(e) => setSearchInput(e.target.value)} />
              </label>
              <label>Technology
                <select value={filters.technology} data-filter-technology="true" onChange={(e) => patch({ technology: e.target.value })}>
                  <option value="">All technologies</option>
                  {data.facets.technologies.map((t) => <option key={t.key} value={t.key}>{t.label} ({t.count})</option>)}
                </select>
              </label>
              <label>Country / market
                <select value={filters.country} data-filter-country="true" onChange={(e) => patch({ country: e.target.value })}>
                  <option value="">All countries</option>
                  {data.facets.countries.map((c) => <option key={c.code} value={c.code}>{c.label} ({c.count})</option>)}
                </select>
              </label>
              <label>Results
                <select value={filters.status} data-filter-status="true" onChange={(e) => patch({ status: e.target.value })}>
                  {STATUSES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                </select>
              </label>
              <label>Last updated
                <select value={filters.edited} data-filter-edited="true" onChange={(e) => patch({ edited: e.target.value })}>
                  {EDITED.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                </select>
              </label>
              <label>Sort by
                <select value={filters.sort} data-library-sort="true" onChange={(e) => patch({ sort: e.target.value })}>
                  {SORTS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                </select>
              </label>
              <label className="rcux-check"><input type="checkbox" checked={filters.hasRuns} data-filter-has-runs="true" onChange={(e) => patch({ hasRuns: e.target.checked })} /> Only projects with Runs</label>
              <label className="rcux-check"><input type="checkbox" checked={filters.archived} data-filter-archived="true" onChange={(e) => patch({ archived: e.target.checked })} /> Archived projects</label>
              <div className="rcm-controls-actions" style={{ display: "flex", gap: 8 }}>
                <button type="submit" className="rx-button rx-button-secondary">Search</button>
                {(filtered || searchInput) && <button type="button" className="rx-button rx-button-secondary" data-filter-clear="true"
                  onClick={() => { setSearchInput(""); setFilters({ ...NO_FILTERS, sort: filters.sort }); }}>Clear filters</button>}
              </div>
            </form>
            <p className="rx-note" role="status" aria-live="polite" data-library-count="true">
              {data.archived ? "Archived projects: " : ""}{data.total} of {data.total_all} project{data.total_all === 1 ? "" : "s"}{filtered ? " match your filters" : ""}.
              {" "}Last updated is the latest saved change or Run.
              {data.limits.capped ? ` Showing the ${data.limits.considered} most recently updated projects.` : ""}
            </p>
            {loading && <p className="rx-note" role="status">Updating…</p>}
            {error && <FriendlyError code={error.code} message={error.message} />}
            {data.projects.length === 0 ? (
              <p className="rx-empty" role="status" data-library-no-match="true">
                {data.archived ? "You have no archived projects." : "No projects match these filters."}
                {filtered && <> <button type="button" className="rx-button rx-button-secondary" onClick={() => { setSearchInput(""); setFilters({ ...NO_FILTERS, sort: filters.sort }); }}>Clear filters</button></>}
              </p>
            ) : (
              <div className="rcux-project-grid" data-library-section="my-projects">
                {data.projects.map((p) => (
                  <article key={p.code} className="rcux-project" data-project-code={p.code} data-project-kind="project" data-run-state={p.freshness}>
                    <h3><a href={p.links.open} aria-label={`Open project ${p.name}`} onClick={(e) => go(e, () => onOpenProject(p.code))}>{p.name}</a></h3>
                    <div><span className={statusClass(p.freshness)} data-project-status={p.freshness} data-run-state={p.freshness}>{p.status}</span>{p.archived && <span className="rcux-status"> Archived</span>}</div>
                    <dl>
                      <dt>Technology</dt><dd data-field="technology">{p.technology.label}{p.technology.pilot_tier === "PREVIEW" && <span className="rx-note" data-vertical-tier="PREVIEW"> · Preview technology — narrower validation than Solar and Wind</span>}</dd>
                      <dt>Country / market</dt><dd data-field="country">{p.country.label ?? "—"}</dd>
                      <dt>{p.capacity_label}</dt><dd data-field="capacity">{capacityText(p)}</dd>
                      <dt>Last updated</dt><dd data-field="last-updated" title={p.last_updated ?? undefined}>{formatSaved(p.last_updated)}</dd>
                      <dt>Last Run</dt><dd data-field="last-run" title={p.last_run.at ?? undefined}>{p.last_run.available
                        ? <>{formatSaved(p.last_run.at)}{p.last_run.snapshot_id && <> · <RunIdentityLabel snapshotId={p.last_run.snapshot_id} /></>}</>
                        : "Not run yet"}</dd>
                    </dl>
                    <div className="rcux-project-links">
                      {p.lifecycle && (p.lifecycle.can_archive || p.lifecycle.can_restore) && <button type="button"
                        className="rx-button rx-button-secondary" data-project-lifecycle={p.code} disabled={!!lifecycleBusy}
                        onClick={() => void lifecycleAction(p)}>{lifecycleBusy === p.code ? "Checking…" : p.archived ? "Restore project" : "Archive project"}</button>}
                      <a href={p.links.open} data-open-project={p.code} onClick={(e) => go(e, () => onOpenProject(p.code))}>Open project →</a>
                      <a href={p.links.scenarios} data-project-scenarios={p.code}>Scenarios</a>
                      <a href={p.links.run_history} data-project-run-history={p.code}>Run history</a>
                    </div>
                  </article>
                ))}
              </div>
            )}
            <div className="rx-lib-pager" data-library-paging="true">
              <button type="button" className="rx-button rx-button-secondary" disabled={data.page <= 1} onClick={() => setFilters((f) => ({ ...f, page: Math.max(1, f.page - 1) }))}>Previous</button>
              <span className="rx-note">Page {data.page} of {data.total_pages}</span>
              <button type="button" className="rx-button rx-button-secondary" disabled={data.page >= data.total_pages} onClick={() => setFilters((f) => ({ ...f, page: f.page + 1 }))}>Next</button>
            </div>
          </>
        )}
      </main>
    </Shell>
  );
}
