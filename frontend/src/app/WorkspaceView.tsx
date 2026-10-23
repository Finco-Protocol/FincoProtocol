import { useCallback, useEffect, useState } from "react";
import StatementWorkbook from "../finco/_workbook/StatementWorkbook";
import { ResultsAnalysisView } from "../finco/ResultsAnalysisView";
import { Shell, ModelNav } from "../finco/_shared/FincoShell";
import { workspaceHeading } from "./adapters";
import { fetchInputs, fetchStatements, fetchWorkspace } from "./api";
import {
  toResultsRunStatus,
  toResultsSnapshot,
  toStatementSnapshot,
  toStatementStatus,
} from "./adapters";
import { CanonicalInputGrid, type GridSaveOutcome } from "./CanonicalInputGrid";
import type { InputsPayload, StatementsPayload, WorkspacePayload } from "./types";

type Section = "overview" | "inputs" | "statements" | "results" | "gated";

// Harvested ModelNav labels → canonical React sections.  Design modules whose
// canonical backend admission is not yet verified stay visibly gated (D4).
const NAV_TO_SECTION: Record<string, Section> = {
  inputs: "inputs",
  statements: "statements",
  results: "results",
  financing: "gated",
  scenarios: "gated",
  analysis: "gated",
  checks: "gated",
  trust: "gated",
  overview: "overview",
};
const SECTION_LABELS: Record<string, string> = {
  overview: "Overview", inputs: "Inputs", statements: "Statements", results: "Results",
};

const SECTION_IDS: Section[] = ["overview", "inputs", "statements", "results"];

function sectionFromHash(): Section {
  const raw = window.location.hash.replace("#", "");
  return (SECTION_IDS as string[]).includes(raw) ? (raw as Section) : "overview";
}

function FreshnessBadge({ state }: { state: string }) {
  const cls = state === "CURRENT" ? "rx-badge rx-badge-ok"
    : state === "STALE" ? "rx-badge rx-badge-stale" : "rx-badge";
  return <span className={cls} data-freshness={state}>{state === "NOT_RUN" ? "NOT RUN" : state}</span>;
}

function StatusRow({ workspace }: { workspace: WorkspacePayload }) {
  const identity = workspace.identity;
  return (
    <div className="rx-card" aria-labelledby="rx-status-heading" data-workspace-status="true">
      <h2 id="rx-status-heading">Working Copy status</h2>
      <div className="rx-badges" data-working-copy-hash={workspace.workbook.composite_hash}>
        <FreshnessBadge state={workspace.freshness.state} />
        <span className="rx-badge" data-integrity={workspace.integrity?.status ?? "UNAVAILABLE"}>
          Integrity: {workspace.integrity?.status ?? "UNAVAILABLE"}
        </span>
        <span className="rx-badge" data-engine-currency={workspace.engine.currency ?? "ENGINE_IDENTITY_UNKNOWN"}>
          Engine: {workspace.engine.currency === "CURRENT_ENGINE" ? "current"
            : workspace.engine.currency === "ENGINE_SUPERSEDED" ? "superseded" : "identity unknown"}
        </span>
      </div>
      <p className="rx-run-identity" data-run-state={workspace.freshness.state}>
        {identity
          ? <>Last Run: snapshot <code>{identity.snapshot_id.slice(0, 12)}</code>{" · "}ran {identity.ran_at || "unavailable"}{" · "}scenario {identity.scenario_proven ? identity.scenario : "UNAVAILABLE"}</>
          : "No persisted Run. Use the legacy workbook Run control; the React workspace never runs the model."}
      </p>
      <p className="rx-note">Scenario: {workspace.workbook.scenario_name || "Base Case"} · Composite {workspace.workbook.composite_hash.slice(0, 12)}</p>
    </div>
  );
}

export function WorkspaceView({ project, legacyUrl, onNavigateToLibrary }: {
  project: string;
  legacyUrl: string;
  onNavigateToLibrary: () => void;
}) {
  const [section, setSection] = useState<Section>(sectionFromHash);
  const [workspace, setWorkspace] = useState<WorkspacePayload | null>(null);
  const [error, setError] = useState<{ code: string; message?: string } | null>(null);
  const [statements, setStatements] = useState<StatementsPayload | null>(null);
  const [inputs, setInputs] = useState<InputsPayload | null>(null);
  const [busy, setBusy] = useState(false);

  const loadWorkspace = useCallback(async () => {
    setError(null);
    const result = await fetchWorkspace(project);
    if ("ok" in result && result.ok === true) setWorkspace(result);
    else setError(result as { code: string; message?: string });
  }, [project]);

  const loadStatements = useCallback(async () => {
    const result = await fetchStatements(project);
    if ("ok" in result && result.ok === true) setStatements(result);
  }, [project]);

  const loadInputs = useCallback(async () => {
    const result = await fetchInputs(project);
    if ("ok" in result && result.ok === true) setInputs(result);
  }, [project]);

  useEffect(() => {
    void loadWorkspace();
  }, [loadWorkspace]);

  useEffect(() => {
    if (!workspace) return;
    // Keep the harvested readProjectContext() on canonical values.
    const params = new URLSearchParams(window.location.search);
    params.set("project", workspace.project.name);
    params.set("projectId", workspace.project.code);
    params.set("technology", workspace.project.project_type || workspace.project.template_source || "FINCO Model");
    params.set("mode", workspace.project.protected_reference ? "reference" : "working-copy");
    window.history.replaceState(null, "", `${window.location.pathname}?${params.toString()}${window.location.hash}`);
  }, [workspace]);

  useEffect(() => {
    if (section === "statements" && !statements) void loadStatements();
    if (section === "results" && !statements) void loadStatements();
    if (section === "inputs" && !inputs) void loadInputs();
  }, [section, statements, inputs, loadStatements, loadInputs]);

  useEffect(() => {
    const onHash = () => setSection(sectionFromHash());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  function navigate(sectionId: string) {
    window.location.hash = sectionId;
    setSection((SECTION_IDS as string[]).includes(sectionId) ? (sectionId as Section) : "gated");
  }

  const refreshAll = useCallback(() => {
    window.location.reload();
  }, []);

  const saveCells = useCallback(async (cells: Array<{ field_id: string; value: string }>): Promise<GridSaveOutcome> => {
    if (!inputs) return { kind: "rejected", message: "The grid is not loaded." };
    setBusy(true);
    try {
      let response: Response;
      try {
        response = await fetch(inputs.save.url, {
          method: "POST",
          credentials: "same-origin",
          headers: { "Content-Type": "application/json", Accept: "application/json" },
          body: JSON.stringify({
            project,
            csrf_token: inputs.save.csrf_token,
            cells,
            workbook_version: inputs.save.workbook_version,
            content_hash: inputs.save.content_hash,
            scenario_id: inputs.save.scenario_id,
          }),
        });
      } catch {
        return {
          kind: "unknown",
          message: "The Save result is UNKNOWN: the connection failed before a definitive response. The server may have committed this Save. Reload to reconcile before saving again.",
        };
      }
      let body: unknown = null;
      try {
        body = await response.json();
      } catch {
        body = null;
      }
      const b = (body ?? {}) as Record<string, unknown>;
      if (response.status === 409) {
        return { kind: "stale", message: (b.message as string) || "The model changed since this page loaded. Reload to continue." };
      }
      if (response.status === 401) {
        return { kind: "rejected", message: "Your session is not authorized. Sign in again; nothing was saved." };
      }
      if (response.ok && b.ok === true
        && Array.isArray(b.saved) && typeof b.content_hash === "string" && b.content_hash.length > 0
        && typeof b.workbook_version === "string"
        && (b.run_state === "NOT_RUN" || b.run_state === "CURRENT" || b.run_state === "STALE")
        && b.model_executed === false) {
        // Canonical Save: adopt the NEW authoritative composite hash and refresh
        // the inputs projection (fresh values + a fresh CSRF token for the next save).
        setInputs((prev) => prev ? {
          ...prev,
          save: { ...prev.save, content_hash: b.content_hash as string, csrf_token: "" },
        } : prev);
        void loadInputs();
        void loadWorkspace();
        return { kind: "saved", contentHash: b.content_hash as string, runState: b.run_state as string };
      }
      if (response.ok) {
        return {
          kind: "unknown",
          message: "The Save result is UNKNOWN: the response was not a readable canonical verdict. The server may have committed this Save. Reload to reconcile before saving again.",
        };
      }
      if (b.cells && Array.isArray(b.cells)) {
        const failed = (b.cells as Array<{ message?: string }>).find((c) => c.message);
        return { kind: "rejected", message: failed?.message || (b.message as string) || "The server rejected the Save." };
      }
      return { kind: "rejected", message: (b.message as string) || `The server rejected the Save (HTTP ${response.status}).` };
    } finally {
      setBusy(false);
    }
  }, [inputs, project, loadInputs, loadWorkspace]);

  if (error) {
    return (
      <main className="rx-page" role="main">
        <section className="rx-card" data-workspace-state={error.code}>
          <h2>Workspace unavailable</h2>
          <p className="rx-empty" role="alert">{error.message || error.code}</p>
          <p><a className="rx-legacy-link" href={legacyUrl}>Open the legacy workbook</a> ·{" "}
            <button type="button" className="rx-button rx-button-secondary" onClick={onNavigateToLibrary}>Back to Project Library</button>
          </p>
        </section>
      </main>
    );
  }

  if (!workspace) {
    return <main className="rx-page" role="main"><p className="rx-boot-loading" role="status">Loading the FINCO Model React workspace…</p></main>;
  }

  return (
    <Shell crumb={workspace.project.name} dataOrigin="caller-provided" mainContentId="rx-main-content">
      <div className="rx-page" role="main" data-react-workspace-version={workspace.react_workspace.version}>
        <header className="rx-header">
          <div>
            <p className="rx-brand">FINCO Protocol · Model</p>
            <h1 className="rx-title">{workspaceHeading(workspace)}
              {workspace.project.protected_reference && <span className="rx-badge">REFERENCE · READ ONLY</span>}
            </h1>
          </div>
          <nav aria-label="Workspace navigation">
            <a className="rx-legacy-link" href={legacyUrl}>Legacy workbook ↗</a>
            {" · "}
            <a className="rx-legacy-link" href="#library" onClick={(e) => { e.preventDefault(); onNavigateToLibrary(); }}>Project Library</a>
          </nav>
        </header>
        <div onClickCapture={(event) => {
          const anchor = (event.target as HTMLElement).closest("a");
          if (!anchor) return;
          const hash = (anchor.getAttribute("href") || "").split("#")[1];
          if (!hash) return;
          event.preventDefault();
          event.stopPropagation();
          navigate(NAV_TO_SECTION[hash] ?? "overview");
        }}>
          <ModelNav active={SECTION_LABELS[section] ?? "Inputs"} onSectionNavigate={(id) => navigate(NAV_TO_SECTION[id] ?? "overview")} />
        </div>
        <p className="rx-note">
          Run action: the canonical Run stays in the{" "}
          <a href={`${legacyUrl}`}>legacy workbook</a> — the React workspace never runs
          the model and saving never triggers one.
        </p>
        {section === "overview" && <StatusRow workspace={workspace} />}
        {section === "inputs" && (
          inputs
            ? <>
              <CanonicalInputGrid payload={inputs} busy={busy} onSave={saveCells} onRefresh={refreshAll} />
            </>
            : <p className="rx-boot-loading" role="status">Loading the canonical input grid…</p>
        )}
        {section === "statements" && (
          statements
            ? <>
              {statements.state === "STALE" && (
                <p className="rx-banner rx-banner-stale" role="status" data-stale-banner="true">
                  STALE — the Working Copy changed after the persisted Last Run. The statements
                  are the prior Run&rsquo;s values; they are not the current inputs.
                </p>
              )}
              <div data-statements-view="true" data-statements-state={statements.state}>
                <StatementWorkbook
                  snapshot={statements.state === "NOT_RUN" || statements.state === "UNAVAILABLE" ? null : toStatementSnapshot(statements)}
                  status={toStatementStatus(statements)}
                />
              </div>
            </>
            : <p className="rx-boot-loading" role="status">Loading the persisted statements…</p>
        )}
        {section === "gated" && (
          <section className="rx-card" data-feature-gate="true">
            <h2>Capability gated</h2>
            <p className="rx-empty" role="note">
              This module&rsquo;s canonical backend admission has not been verified for the
              React workspace yet. Its canonical experience remains in the{" "}
              <a href={legacyUrl}>legacy workbook</a>. A design presence in the React
              prototype does not make a capability available.
            </p>
          </section>
        )}
        {section === "results" && (
          statements
            ? <div data-results-view="true" data-results-state={statements.state}>
              <ResultsAnalysisView
                resultsSnapshot={toResultsSnapshot(statements)}
                resultsStatus={toResultsRunStatus(statements)}
                statementSnapshot={toStatementSnapshot(statements)}
                statementStatus={toStatementStatus(statements)}
              />
            </div>
            : <p className="rx-boot-loading" role="status">Loading the persisted results…</p>
        )}
        <footer className="rx-footer">
          <p className="rx-note">
            UX-02 integrated React workbook over the canonical FINCO Model authorities.
            The legacy Jinja2/HTMX workbook remains the default experience.
          </p>
        </footer>
      </div>
    </Shell>
  );
}
