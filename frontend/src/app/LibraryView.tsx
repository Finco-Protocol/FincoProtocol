import { useCallback, useEffect, useState, type FormEvent, type MouseEvent } from "react";
import "../finco/_group.css";
import "../styles/finco-live.css";
import { Shell } from "../finco/_shared/FincoShell";
import { createWorkingCopy, fetchLibrary, isCloneUnknown } from "./api";
import type { LibraryPayload, LibraryProject } from "./types";

const FRESHNESS_TEXT: Record<string, string> = { CURRENT: "CURRENT", STALE: "STALE", NOT_RUN: "NOT RUN" };

/** Reference templates whose working-copy runtime is not available yet (legacy Library parity). */
function cloneUnavailable(project: LibraryProject): boolean {
  return /storage|bess/i.test(`${project.template_source} ${project.project_type}`);
}

function projectKind(project: LibraryProject): string {
  return project.project_type || project.template_source || "Type not recorded";
}

function RunCell({ project }: { project: LibraryProject }) {
  const run = project.last_run;
  if (!run || !run.available) {
    return <span data-run-state="NOT_RUN"><span className="rx-lib-badge">NOT RUN</span> No persisted Run</span>;
  }
  const freshness = run.freshness || "UNKNOWN";
  return (
    <span data-run-state={freshness}>
      <span className={`rx-lib-badge${freshness === "STALE" ? " rx-lib-badge-stale" : ""}`}>{FRESHNESS_TEXT[freshness] ?? freshness}</span>{" "}
      {freshness === "STALE" ? "Prior Run " : "Run "}<code className="rx-lib-code">{run.snapshot_id || "id unavailable"}</code>
      {run.ran_at && <><br /><span className="rx-note">{run.ran_at}</span></>}
    </span>
  );
}

/** UX-02 Project Library over the canonical project-list authorities. */
export function LibraryView({ onOpenProject }: { onOpenProject: (code: string) => void }) {
  const [library, setLibrary] = useState<LibraryPayload | null>(null);
  const [error, setError] = useState<{ code: string; message?: string } | null>(null);
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [cloneError, setCloneError] = useState("");
  const [cloneUnknown, setCloneUnknown] = useState(false);
  const [busyClone, setBusyClone] = useState<string | null>(null);

  const load = useCallback(async () => {
    const result = await fetchLibrary(search, page);
    if ("ok" in result && result.ok === true) { setLibrary(result); setError(null); }
    else setError(result as { code: string; message?: string });
  }, [search, page]);

  useEffect(() => {
    void load();
  }, [load]);

  if (error) {
    return (
      <Shell crumb="All projects" dataOrigin="canonical-run" originLabel="LIBRARY UNAVAILABLE">
        <main className="rx-page" role="main">
          <section className="rx-card" data-library-state={error.code}>
            <h2>Project Library unavailable</h2>
            <p className="rx-empty" role="alert">{error.message || error.code}</p>
            <p className="rx-note">The classic FINCO Model interface remains available and authoritative.</p>
          </section>
        </main>
      </Shell>
    );
  }

  if (!library) {
    return <main className="rx-page" role="main"><p className="rx-boot-loading" role="status">Loading the FINCO Model Project Library…</p></main>;
  }

  async function clone(project: LibraryProject) {
    setCloneError("");
    setCloneUnknown(false);
    setBusyClone(project.code);
    try {
      const result = await createWorkingCopy({
        cloneUrlTemplate: library!.clone_url,
        csrfToken: library!.csrf_token,
        sourceProjectId: project.project_id || project.code,
        requestedName: `${project.name} (copy)`,
      });
      if (isCloneUnknown(result)) {
        // The canonical clone answers success with a redirect AFTER creating
        // the copy: an ambiguous outcome must be reconciled, never retried.
        setCloneUnknown(true);
        return;
      }
      if (result.ok) {
        setSearchInput("");
        setSearch("");
        setPage(1);
        await load();
      } else {
        setCloneError(result.message);
      }
    } finally {
      setBusyClone(null);
    }
  }

  function open(event: MouseEvent<HTMLAnchorElement>, project: LibraryProject) {
    if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    onOpenProject(project.code);
  }

  function submitSearch(event: FormEvent) {
    event.preventDefault();
    setPage(1);
    setSearch(searchInput.trim());
  }

  const href = (project: LibraryProject) => `/v2/model-react/${encodeURIComponent(project.code)}`;

  return (
    <Shell crumb="All projects" dataOrigin="canonical-run" originLabel="WORKSPACE LIBRARY">
      <main className="rx-page" role="main" data-library-view="true" id="fm-main-content" tabIndex={-1}>
        <header className="rx-header">
          <div>
            <p className="rx-brand">FINCO Protocol · Model</p>
            <h1 className="rx-title">Project Library</h1>
          </div>
          <nav aria-label="Classic interface">
            <a className="rx-legacy-link" href="/">FINCO home ↗</a>
          </nav>
        </header>
        <p className="rx-note" data-library-persistence="true">
          Working copies are saved to your account on the server and can be reopened from any session.
          Reference models are shared and read-only: open one to inspect it, or create a working copy to edit
          and run it. Run status is read from each project&rsquo;s persisted Run.
        </p>
        {cloneError && <p className="rx-status rx-status-error" role="alert">{cloneError}</p>}
        {cloneUnknown && (
          <p className="rx-status rx-status-conflict" role="alert" data-clone-unknown="true">
            The creation result is UNKNOWN — the server may have created the Working Copy.
            <button type="button" className="rx-button rx-button-secondary"
                    data-reconcile-button="true" onClick={() => { setCloneUnknown(false); void load(); }}>
              Reload the Library to reconcile
            </button>
          </p>
        )}
        <div className="rx-lib">
          <form className="rx-lib-toolbar" role="search" onSubmit={submitSearch} data-library-search="true">
            <div className="rx-lib-search">
              <input type="search" aria-label="Search projects" placeholder="Search by project name or code…"
                value={searchInput} onChange={(event) => setSearchInput(event.target.value)} />
              <button type="submit" className="rx-button rx-button-secondary">Search</button>
              {(search || searchInput) && (
                <button type="button" className="rx-button rx-button-secondary"
                        onClick={() => { setSearchInput(""); setSearch(""); setPage(1); }}>Clear</button>
              )}
            </div>
            <span className="rx-note" data-library-count="true">
              {search ? `Search “${search}”: ` : ""}{library.total} working {library.total === 1 ? "copy" : "copies"} · {library.references.length} reference {library.references.length === 1 ? "model" : "models"}
            </span>
          </form>

          <section className="rx-card" aria-labelledby="rx-lib-working" data-library-section="working-copies">
            <h2 id="rx-lib-working">Your working copies</h2>
            {library.projects.length === 0
              ? <p className="rx-empty" role="status">{search ? "No working copies match this search." : "You have no working copies yet. Create one from a reference model below."}</p>
              : (
                <table className="rx-lib-table">
                  <thead><tr><th>Project</th><th>Type</th><th>Status</th><th>Last Run</th><th>Actions</th></tr></thead>
                  <tbody>
                    {library.projects.map((project) => (
                      <tr key={project.code} data-project-code={project.code} data-project-kind="working-copy">
                        <td data-label="Project"><strong>{project.name}</strong><div className="rx-lib-code">{project.code}</div></td>
                        <td data-label="Type">{projectKind(project)}{project.template_source && project.template_source !== project.project_type && <div className="rx-lib-code">Template: {project.template_source}</div>}</td>
                        <td data-label="Status"><span className="rx-lib-badge rx-lib-badge-copy">WORKING COPY</span><div className="rx-note">Editable · saved on the server</div></td>
                        <td data-label="Last Run"><RunCell project={project} /></td>
                        <td data-label="Actions">
                          <div className="rx-lib-actions">
                            <a className="fm-small-link" href={href(project)} aria-label={`Open working copy ${project.name}`} onClick={(event) => open(event, project)}>Open working copy →</a>
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            <div className="rx-lib-pager" data-library-paging="true">
              <button type="button" className="rx-button rx-button-secondary" disabled={page <= 1}
                      onClick={() => setPage((p) => Math.max(1, p - 1))}>Previous</button>
              <span className="rx-note">Page {library.page} of {library.total_pages} · {library.total} working {library.total === 1 ? "copy" : "copies"}</span>
              <button type="button" className="rx-button rx-button-secondary" disabled={page >= library.total_pages}
                      onClick={() => setPage((p) => p + 1)}>Next</button>
            </div>
          </section>

          <section className="rx-card" aria-labelledby="rx-lib-references" data-library-section="references">
            <h2 id="rx-lib-references">Reference models</h2>
            {library.references.length === 0
              ? <p className="rx-empty" role="status">{search ? "No reference models match this search." : "No reference models are available."}</p>
              : (
                <table className="rx-lib-table">
                  <thead><tr><th>Reference</th><th>Type</th><th>Status</th><th>Last Run</th><th>Actions</th></tr></thead>
                  <tbody>
                    {library.references.map((project) => {
                      const blocked = cloneUnavailable(project);
                      return (
                        <tr key={project.code} data-project-code={project.code} data-project-kind="reference">
                          <td data-label="Reference"><strong>{project.name}</strong><div className="rx-lib-code">{project.code}</div></td>
                          <td data-label="Type">{projectKind(project)}{blocked && <div className="rx-note">Preview-only technology</div>}</td>
                          <td data-label="Status"><span className="rx-lib-badge rx-lib-badge-reference">REFERENCE</span><div className="rx-note">Read-only · shared</div></td>
                          <td data-label="Last Run"><RunCell project={project} /></td>
                          <td data-label="Actions">
                            <div className="rx-lib-actions">
                              <a className="fm-small-link" href={href(project)} aria-label={`Open reference ${project.name}`} onClick={(event) => open(event, project)}>Open reference →</a>
                              {blocked
                                ? <span className="rx-note" data-clone-unavailable="true">Working copy not yet available</span>
                                : <button type="button" className="fm-small-link fm-library-copy-action"
                                    disabled={busyClone !== null} aria-label={`Create working copy of ${project.name}`}
                                    onClick={() => void clone(project)}>{busyClone === project.code ? "Creating…" : "Create working copy"}</button>}
                            </div>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              )}
          </section>
        </div>
      </main>
    </Shell>
  );
}
