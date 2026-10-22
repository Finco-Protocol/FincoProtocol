import React, { useMemo, useState } from "react";
import "./_group.css";
import { DemoBanner, navigateFinco, projectWorkspaceHref, Shell, Status } from "./_shared/FincoShell";
import {
  createDemoWorkingCopy,
  createLocalDemoProject,
  listDemoWorkingCopies,
  type DemoWorkingCopy,
} from "./_shared/demoWorkingCopies";
import { SYNTHETIC_REFERENCE_PROJECTS } from "./_shared/demoProjectFixtures";
import type { LibraryProjectViewModel } from "./_shared/viewModels";

export type ProjectLibraryProps = {
  sampleProjects?: readonly LibraryProjectViewModel[];
  onNavigate?: (href: string) => void;
};

function readCopies() {
  try {
    return { copies: listDemoWorkingCopies(), error: "" };
  } catch (error) {
    return { copies: [] as DemoWorkingCopy[], error: error instanceof Error ? error.message : "The local demo session could not be read." };
  }
}

function toLibraryProject(copy: DemoWorkingCopy): LibraryProjectViewModel {
  return {
    ...copy,
    stage: copy.kind === "reference-copy" ? "Working copy" : "New demo project",
    tone: copy.kind === "reference-copy" ? "green" : "gray",
    updated: "This browser tab",
    sourceKind: copy.kind,
  };
}

export function ProjectLibrary({
  sampleProjects = SYNTHETIC_REFERENCE_PROJECTS,
  onNavigate = navigateFinco,
}: ProjectLibraryProps = {}) {
  const [query, setQuery] = useState("");
  const [stage, setStage] = useState("All stages");
  const [technology, setTechnology] = useState("All technologies");
  const [copyState, setCopyState] = useState(readCopies);
  const projects = useMemo(() => [
    ...sampleProjects,
    ...copyState.copies.map(toLibraryProject),
  ], [copyState.copies]);
  const created = copyState.copies.some(copy => copy.kind === "new-demo-project");
  const filtered = useMemo(() => projects.filter((p) =>
    `${p.name} ${p.id} ${p.region} ${p.sponsor} ${p.parentReferenceName ?? ""}`.toLowerCase().includes(query.toLowerCase())
    && (stage === "All stages" || p.stage === stage)
    && (technology === "All technologies" || p.technology === technology)
  ), [projects, query, stage, technology]);

  function createDemo() {
    if (created) return;
    try {
      createLocalDemoProject({
        name: "New solar project",
        technology: "Solar PV",
        size: "—",
        region: "Location not set",
        sponsor: "Unassigned",
      });
      setCopyState(readCopies());
    } catch (error) {
      setCopyState(current => ({
        ...current,
        error: error instanceof Error ? error.message : "The demo project could not be added to this browser-tab session.",
      }));
    }
    setQuery("");
    setStage("All stages");
    setTechnology("All technologies");
  }
  function openReference(project: LibraryProjectViewModel) {
    onNavigate(projectWorkspaceHref(project, { mode: "reference" }));
  }
  function createWorkingCopy(project: LibraryProjectViewModel) {
    try {
      const copy = createDemoWorkingCopy(project);
      onNavigate(projectWorkspaceHref(copy, {
        mode: "working-copy",
        parentReferenceId: project.id,
      }));
    } catch (error) {
      setCopyState(current => ({
        ...current,
        error: error instanceof Error ? error.message : "The working copy could not be created in this browser-tab session.",
      }));
    }
  }
  function openCopy(project: LibraryProjectViewModel) {
    onNavigate(projectWorkspaceHref(project, {
      mode: "working-copy",
      parentReferenceId: project.parentReferenceId ?? undefined,
    }));
  }
  return <Shell crumb="Project library">
    <main className="fm-shell">
      <DemoBanner copy={`${sampleProjects.length} fictional reference projects · References are read-only. Demo copies live only in this browser-tab session, survive reload here, and are cleared by Reset local demo session or closing the tab. Nothing is stored on a server.`} />
      <div className="fm-shell-header">
        <div><div className="fm-eyebrow">Portfolio / renewable energy</div><h1 className="fm-title">Project library</h1><div className="fm-subtitle">Review and open project finance models across the portfolio.</div></div>
        <div className="fm-toolbar">
          <button className="fm-btn" type="button" onClick={() => { setQuery(""); setStage("All stages"); setTechnology("All technologies"); }}>Reset filters</button>
          <button className="fm-btn fm-btn-primary" type="button" disabled={created} onClick={createDemo}>{created ? "Demo project added" : "+ Create project"}</button>
        </div>
      </div>
      <div className="fm-info-note" role="note"><strong>Reference → Working Copy:</strong> Open a reference to inspect it without editing, or create a separate local synthetic copy. Copy names are unique; changing a copy does not alter the reference or other copies. Reload preserves this browser-tab session; Reset or closing the tab clears it. Portfolio totals and charts remain fixed synthetic reference snapshots; local copies and new demo rows do not update them.</div>
      {copyState.error && <div className="fm-wf-error-summary" role="alert">{copyState.error}</div>}
      <div className="fm-kpi-grid" style={{ marginBottom: 16 }}>
        <div className="fm-kpi"><div className="fm-kpi-label">Project records</div><div className="fm-kpi-value">{String(projects.length).padStart(2, "0")}</div><div className="fm-kpi-note">across 3 markets</div></div>
        <div className="fm-kpi"><div className="fm-kpi-label">Installed capacity</div><div className="fm-kpi-value">530<span style={{ fontSize: 13, letterSpacing: 0 }}> MW</span></div><div className="fm-kpi-note">solar, wind and storage</div></div>
        <div className="fm-kpi"><div className="fm-kpi-label">Under credit review</div><div className="fm-kpi-value">02</div><div className="fm-kpi-note">1.4 GWp equivalent pipeline</div></div>
        <div className="fm-kpi"><div className="fm-kpi-label">Last model update</div><div className="fm-kpi-value" style={{ fontSize: 19 }}>18 JUN</div><div className="fm-kpi-note">2025 · 14:32 CET</div></div>
      </div>
      <section className="fm-card">
        <div className="fm-card-title"><h2>Project register</h2><span>{filtered.length} of {projects.length} records · sorted by last updated</span></div>
        <div style={{ padding: "11px 12px", display: "flex", flexWrap: "wrap", alignItems: "center", gap: 8, borderBottom: "1px solid var(--line-soft)" }}>
          <input className="fm-search" aria-label="Search projects" placeholder="Search project, sponsor or region…" value={query} onChange={(e) => setQuery(e.target.value)} />
          <select className="fm-filter" aria-label="Filter stage" value={stage} onChange={(e) => setStage(e.target.value)}>
            <option>All stages</option><option>Draft</option><option>Base case</option><option>Credit review</option><option>Needs review</option><option>Working copy</option><option>New demo project</option>
          </select>
          <select className="fm-filter" aria-label="Filter technology" value={technology} onChange={(e) => setTechnology(e.target.value)}>
            <option>All technologies</option><option>Solar PV</option><option>Onshore wind</option><option>Solar + BESS</option>
          </select>
          <span style={{ marginLeft: "auto" }} className="fm-pill">EUR reporting</span>
        </div>
        <div className="fm-table-tools" id="library-scroll-help">More project columns ↔ Scroll inside the register, or focus it and use ← / →.</div>
        <div className="fm-table-wrap" role="region" tabIndex={0} aria-label="Project register, scrollable columns" aria-describedby="library-scroll-help"
          onKeyDown={event => {
            if (event.key === "ArrowRight" || event.key === "ArrowLeft") {
              event.preventDefault();
              event.currentTarget.scrollBy({ left: event.key === "ArrowRight" ? 120 : -120 });
            }
          }}>
          <table className="fm-table">
            <thead><tr><th>Project / reference</th><th>Technology</th><th>Capacity</th><th>Region</th><th>Stage</th><th>Sponsor</th><th>Updated</th><th>Actions</th></tr></thead>
            <tbody>{filtered.map((p) => <tr key={p.id}>
              <td><strong className="fm-project-name">{p.name}</strong><div className="fm-hint fm-mono" style={{ marginTop: 3 }}>{p.id}</div>
                {p.parentReferenceName && <div className="fm-hint" style={{ marginTop: 3 }}>Parent reference: {p.parentReferenceName} · {p.parentReferenceId}</div>}
                {p.sourceKind !== "reference" && <div className="fm-hint" style={{ marginTop: 3 }}>Demo only · not persisted</div>}
              </td>
              <td>
                <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: 5 }}>
                  <span>{p.technology}</span>
                  {/bess|storage/i.test(p.technology) && <Status tone="amber">Preview-only technology</Status>}
                </div>
              </td><td className="fm-mono">{p.size}</td><td>{p.region}</td>
              <td><Status tone={p.tone}>{p.stage}</Status></td><td>{p.sponsor}</td><td className="fm-mono">{p.updated}</td>
              <td>
                <div className="fm-library-actions">
                 {p.sourceKind === "reference"
                    ? <>
                      <button type="button" className="fm-small-link" aria-label={`Open reference ${p.name}`} onClick={() => openReference(p)}>Open reference →</button>
                      <button type="button" className="fm-small-link fm-library-copy-action" aria-label={`Create working copy from ${p.name}`} onClick={() => createWorkingCopy(p)}>Create working copy</button>
                    </>
                    : <>
                      <button type="button" className="fm-small-link" aria-label={`Open working copy ${p.name}`} onClick={() => openCopy(p)}>Open working copy →</button>
                       {p.parentReferenceId && <button type="button" className="fm-small-link" aria-label={`Open parent reference ${p.parentReferenceName}`} onClick={() => openReference(sampleProjects.find(seed => seed.id === p.parentReferenceId) ?? p)}>Open reference</button>}
                    </>}
                </div>
              </td>
            </tr>)}
            {filtered.length === 0 && <tr><td colSpan={8} style={{ padding: 30, textAlign: "center", color: "var(--muted)" }}>No projects match these filters. Adjust your search or reset filters.</td></tr>}
            </tbody>
          </table>
        </div>
      </section>
      <div className="fm-main-grid" style={{ marginTop: 14 }}>
        <section className="fm-card">
          <div className="fm-card-title"><h2>Portfolio composition</h2><span>by installed nameplate capacity</span></div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", padding: "15px 16px", gap: 16 }}>
            {[["Solar PV", "346 MW", "65%", "#345f80"], ["Onshore wind", "184 MW", "35%", "#8299aa"], ["Storage", "40 MW", "Included", "#b4c1c9"]].map(([label, amount, pct, color]) =>
              <div key={label}><div style={{ display: "flex", justifyContent: "space-between", gap: 8, color: "var(--ink-soft)", fontSize: 10 }}><span>{label}</span><span className="fm-mono">{amount}</span></div><div style={{ height: 4, marginTop: 8, background: "#e8edf0" }}><div style={{ height: 4, width: pct === "65%" ? "65%" : pct === "35%" ? "35%" : "18%", background: color }} /></div></div>
            )}
          </div>
        </section>
        <section className="fm-info-note" style={{ alignSelf: "stretch", display: "flex", flexDirection: "column", justifyContent: "center" }}>
          <strong style={{ color: "var(--ink)", marginBottom: 4 }}>Prototype interactions</strong>
          Search and filters update this local register. Opening a sample is read-only. “Create working copy” creates a unique, project-scoped session copy with parent attribution; local Save never persists to a server, and fixed Results remain shared synthetic examples.
        </section>
      </div>
      <div className="fm-footer">Portfolio data shown is synthetic and illustrative · All entities are fictional</div>
    </main>
  </Shell>;
}
