import { useCallback, useEffect, useState } from "react";
import { ProjectLibrary } from "../finco/ProjectLibrary";
import type { LibraryProjectViewModel } from "../finco/_shared/viewModels";
import { createWorkingCopy, fetchLibrary } from "./api";
import type { LibraryPayload } from "./types";

function toViewModel(project: LibraryPayload["projects"][number]): LibraryProjectViewModel {
  const lastRun = project.last_run;
  return {
    name: project.name,
    id: project.code,
    technology: project.project_type || project.template_source || "FINCO Model",
    size: "",
    region: "",
    sponsor: "",
    stage: project.protected_reference
      ? "Reference · read only"
      : lastRun?.available
        ? `Last Run ${lastRun.freshness}${lastRun.snapshot_id ? ` · ${lastRun.snapshot_id}` : ""}`
        : "No persisted Run",
    tone: project.protected_reference ? "blue" : lastRun?.freshness === "STALE" ? "amber" : lastRun?.available ? "green" : "gray",
    updated: lastRun?.ran_at || "",
    sourceKind: project.protected_reference ? "reference" : "reference-copy",
    parentReferenceId: null,
    parentReferenceName: null,
  };
}

/** UX-02 Project Library over the canonical project-list authorities. */
export function LibraryView({ onOpenProject }: { onOpenProject: (code: string) => void }) {
  const [library, setLibrary] = useState<LibraryPayload | null>(null);
  const [error, setError] = useState<{ code: string; message?: string } | null>(null);
  const [search] = useState("");
  const [page, setPage] = useState(1);
  const [cloneError, setCloneError] = useState("");

  const load = useCallback(async () => {
    const result = await fetchLibrary(search, page);
    if ("ok" in result && result.ok === true) setLibrary(result);
    else setError(result as { code: string; message?: string });
  }, [search, page]);

  useEffect(() => {
    void load();
  }, [load]);

  if (error) {
    return (
      <main className="rx-page" role="main">
        <section className="rx-card" data-library-state={error.code}>
          <h2>Project Library unavailable</h2>
          <p className="rx-empty" role="alert">{error.message || error.code}</p>
          <p className="rx-note">The classic FINCO Model interface remains available and authoritative.</p>
        </section>
      </main>
    );
  }

  if (!library) {
    return <main className="rx-page" role="main"><p className="rx-boot-loading" role="status">Loading the FINCO Model Project Library…</p></main>;
  }

  const workingProjects = library.projects.map(toViewModel);
  const referenceProjects = library.references.map(toViewModel);

  async function clone(project: LibraryProjectViewModel) {
    setCloneError("");
    const result = await createWorkingCopy({
      cloneUrlTemplate: library!.clone_url,
      csrfToken: library!.csrf_token,
      sourceProjectId: project.id,
      requestedName: `${project.name} (copy)`,
    });
    if (result.ok) {
      setPage(1);
      await load();
    } else {
      setCloneError(result.message);
    }
  }

  return (
    <main className="rx-page" role="main" data-library-view="true">
      <header className="rx-header">
        <div>
          <p className="rx-brand">FINCO Protocol · Model</p>
          <h1 className="rx-title">Project Library</h1>
        </div>
        <nav aria-label="Classic interface">
          <a className="rx-legacy-link" href="/">FINCO home ↗</a>
        </nav>
      </header>
      {cloneError && <p className="rx-status rx-status-error" role="alert">{cloneError}</p>}
      <ProjectLibrary
        sampleProjects={[...workingProjects, ...referenceProjects]}
        onNavigate={(href) => {
          // The harvested view navigates by href; the canonical route is the
          // project code this adapter injected as the view-model id.
          const code = decodeURIComponent(href.split("projectId=")[1] || "").split("&")[0];
          if (code) onOpenProject(code);
        }}
        onCreateWorkingCopy={clone}
      />
      <div className="rx-field-row" style={{ marginTop: "0.75rem" }} data-library-paging="true">
        <button type="button" className="rx-button rx-button-secondary" disabled={page <= 1}
                onClick={() => setPage((p) => Math.max(1, p - 1))}>Previous</button>
        <span className="rx-note">Page {library.page} of {library.total_pages} · {library.total} projects</span>
        <button type="button" className="rx-button rx-button-secondary" disabled={page >= library.total_pages}
                onClick={() => setPage((p) => p + 1)}>Next</button>
      </div>
      <p className="rx-note">
        Working-copy creation uses the canonical library clone operation; references
        are read-only and the same projects appear in the legacy Library. Search
        filters the loaded page locally; paging reads the canonical paged list.
      </p>
    </main>
  );
}
