import { useCallback, useEffect, useRef, useState } from "react";
import StatementWorkbook from "../finco/_workbook/StatementWorkbook";
import { Shell } from "../finco/_shared/FincoShell";
import { AnalysisTools } from "./analysis/AnalysisTools";
import { FinancingStudio } from "./financing/FinancingStudio";
import { workspaceHeading } from "./adapters";
import { fetchInputs, fetchStatements, fetchWorkspace } from "./api";
import { RecoveryPanel } from "./RecoveryPanel";
import { toStatementSnapshot, toStatementStatus } from "./adapters";
import { FinancialResults } from "./FinancialResults";
import { WorkspaceNav, isWorkspaceSection, type WorkspaceSection } from "./WorkspaceNav";
import { CanonicalInputGrid, type GridSaveOutcome } from "./CanonicalInputGrid";
import { CostLinesView, DiagnosticsView, RunsView, TrustView } from "./ux040506Views";
import { FinancialInsights } from "./insights";
import { InputsJumpNav, SaveScopeGuide, type InputsJump } from "./InputsGuide";
import { RunIdentityLabel } from "./runIdentity";
import { VerticalScopeBanner } from "./VerticalScope";
import "../styles/rc-react-mvp.css";
import { ModelExportView } from "./workflow/ModelExportView";
import { PPAEditorView } from "./workflow/PPAEditorView";
import { ScenarioWorkspace } from "./workflow/ScenarioWorkspace";
import { SheetFieldsEditor } from "./workflow/SheetFieldsEditor";
import { WorkflowBar } from "./workflow/WorkflowBar";
import { DirtyProvider, useLeaveGuard } from "./workflow/workflowShared";
import { isRecoveryPayload, type InputsPayload, type RecoveryPayload, type RevenueContractsPayload, type StatementsPayload, type WorkspacePayload } from "./types";
import { fetchRevenueContracts } from "./api";

type Section = WorkspaceSection;

function sectionFromHash(): Section {
  const raw = window.location.hash.replace("#", "");
  return isWorkspaceSection(raw) ? raw : "overview";
}

/** Chip text for the shell: the persisted Run state of this Working Copy. */
const RUN_CHIP: Record<string, string> = { CURRENT: "CURRENT RUN", STALE: "STALE RUN", NOT_RUN: "NOT RUN" };

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
          ? <>Last Run: <RunIdentityLabel snapshotId={identity.snapshot_id} />{" · "}scenario {identity.scenario_proven ? identity.scenario : "UNAVAILABLE"}</>
          : "No persisted Run yet. Use the Run model button above to run the model; saving never runs it."}
      </p>
      <p className="rx-note">Active scenario: {workspace.workbook.scenario_name || "Base Case"}</p>
      <VerticalScopeBanner vertical={workspace.vertical} />
    </div>
  );
}

function StatementIdentityConflict({ workspace, statements }: { workspace: WorkspacePayload; statements: StatementsPayload }) {
  return (
    <section className="rx-card" role="alert" data-statement-identity="conflict">
      <h2>Statements do not match this project</h2>
      <p>
        The statements returned belong to <strong>{statements.project.name}</strong>, not to{" "}
        <strong>{workspace.project.name}</strong>. Nothing is shown so that figures are never read under the wrong project.
        Reload the workspace; if this persists, open the project again from the Project Library.
      </p>
    </section>
  );
}

interface WorkspaceViewProps {
  project: string;
  legacyUrl: string;
  onNavigateToLibrary: () => void;
}

/** The unsaved-change registry wraps the whole workspace so navigation, Reload and
 *  Run all consult the same state the editors report into. */
export function WorkspaceView(props: WorkspaceViewProps) {
  return <DirtyProvider><WorkspaceViewInner {...props} /></DirtyProvider>;
}

function WorkspaceViewInner({ project, legacyUrl, onNavigateToLibrary }: WorkspaceViewProps) {
  const confirmIfDirty = useLeaveGuard();
  const [section, setSection] = useState<Section>(sectionFromHash);
  const sectionRef = useRef<Section>(section);
  sectionRef.current = section;
  const allowNextHash = useRef(false);
  // Bumped when the ACTIVE scenario changes: every scope-bound editor remounts so a
  // draft can never be applied to a different scenario's CAS identity.
  const [scopeEpoch, setScopeEpoch] = useState(0);
  const [workspace, setWorkspace] = useState<WorkspacePayload | null>(null);
  const [error, setError] = useState<{ code: string; message?: string } | null>(null);
  const [statements, setStatements] = useState<StatementsPayload | null>(null);
  const [inputs, setInputs] = useState<InputsPayload | null>(null);
  const [recovery, setRecovery] = useState<RecoveryPayload | null>(null);
  const [revenuePayload, setRevenuePayload] = useState<RevenueContractsPayload | null>(null);
  const [busy, setBusy] = useState(false);
  // Bumped after ANY committed change so every editor re-reads its CAS tokens;
  // unsaved drafts in other editors are reconciled, never silently rebased.
  const [dataVersion, setDataVersion] = useState(0);
  // Which line-item sheet the CAPEX / OPEX jump links ask for (the editor itself guards unsaved edits).
  const [costRequest, setCostRequest] = useState<{ sheet: "capex" | "opex"; nonce: number }>({ sheet: "capex", nonce: 0 });

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
    if ("ok" in result && result.ok === true) { setRecovery(null); setInputs(result); }
    else if (isRecoveryPayload(result)) setRecovery(result);
  }, [project]);

  useEffect(() => {
    void loadWorkspace();
  }, [loadWorkspace]);

  const loadRevenue = useCallback(async () => {
    const result = await fetchRevenueContracts(project);
    if (result.ok === true) setRevenuePayload(result);
  }, [project]);

  const afterMutation = useCallback(() => {
    setDataVersion((v) => v + 1);
    void loadWorkspace();
  }, [loadWorkspace]);

  useEffect(() => {
    if (dataVersion === 0) return;
    void loadInputs();
    void loadRevenue();
  }, [dataVersion, loadInputs, loadRevenue]);

  // A scenario switch changes the scope of every projection: drop them all.
  const onScenarioChanged = useCallback(() => {
    setScopeEpoch((n) => n + 1);
    setInputs(null);
    setRecovery(null);
    setStatements(null);
    setRevenuePayload(null);
    afterMutation();
  }, [afterMutation]);

  useEffect(() => {
    if (section === "statements" && !statements) void loadStatements();
    if ((section === "results" || section === "analysis") && !statements) void loadStatements();
    if (section === "inputs" && !inputs && !recovery) void loadInputs();
    if (section === "inputs" && !revenuePayload) void loadRevenue();
  }, [section, statements, inputs, recovery, revenuePayload, loadStatements, loadInputs, loadRevenue]);

  // Hash changes (typed URL, Back/Forward) are guarded like tab clicks: the URL has
  // already moved, so "stay" restores the hash of the section that is still shown.
  useEffect(() => {
    const onHash = () => {
      if (allowNextHash.current) { allowNextHash.current = false; setSection(sectionFromHash()); return; }
      const raw = window.location.hash.replace("#", "");
      const target = isWorkspaceSection(raw) ? raw : sectionRef.current;
      if (target === sectionRef.current) return;
      confirmIfDirty(() => setSection(target), {
        ignore: (key) => key === "run",
        onStay: () => window.history.replaceState(null, "", `${window.location.pathname}${window.location.search}#${sectionRef.current}`),
      });
    };
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, [confirmIfDirty]);

  function navigate(sectionId: Section) {
    if (sectionId === sectionRef.current) return;
    // The status bar (and its Run) stays mounted across sections, so a Run is not abandoned by switching tabs.
    confirmIfDirty(() => {
      if (window.location.hash !== `#${sectionId}`) allowNextHash.current = true;
      window.location.hash = sectionId;
      setSection(sectionId);
    }, { ignore: (key) => key === "run" });
  }

  // Any other in-app link that leaves this page (Project Library breadcrumb, legacy
  // workbook, ...) asks first when edits are unsaved.  Modified clicks open a new
  // tab/window and downloads stay on the page, so they are not intercepted.
  const guardLinkClick = (event: React.MouseEvent) => {
    if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    const anchor = (event.target as HTMLElement).closest("a");
    if (!anchor) return;
    const href = anchor.getAttribute("href") || "";
    if (!href || href.startsWith("#") || anchor.hasAttribute("download") || (anchor.target && anchor.target !== "_self")) return;
    event.preventDefault();
    event.stopPropagation();
    confirmIfDirty(() => window.location.assign(anchor.href));
  };

  const jumpWithinInputs = (jump: InputsJump) => {
    if (jump.kind === "section" && jump.section) { navigate(jump.section as Section); return; }
    if (jump.kind === "cost-sheet" && jump.sheet) setCostRequest((prev) => ({ sheet: jump.sheet!, nonce: prev.nonce + 1 }));
    const target = document.getElementById(jump.id);
    target?.scrollIntoView({ block: "start" });
    target?.focus({ preventScroll: true });
  };

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
        afterMutation();
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
  }, [inputs, project, afterMutation]);

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

  // Statements carry their own project block; if it names a different project than the authorized
  // workspace, nothing from it is shown (no cross-project data under the wrong identity).
  const statementsConflict = Boolean(statements?.project?.code && statements.project.code !== workspace.project.code);

  return (
    <div style={{ display: "contents" }} onClickCapture={guardLinkClick} data-leave-guard="true">
    <Shell crumb={workspace.project.name} dataOrigin="canonical-run" mainContentId="rx-main-content"
      originLabel={RUN_CHIP[workspace.freshness.state] ?? "RUN UNAVAILABLE"}>
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
            <a className="rx-legacy-link" href="#library" onClick={(e) => { e.preventDefault(); confirmIfDirty(onNavigateToLibrary); }}>Project Library</a>
          </nav>
        </header>
        <WorkspaceNav active={section} onNavigate={navigate} />
        <WorkflowBar
          project={project}
          freshness={workspace.freshness.state}
          protectedReference={Boolean(workspace.project.protected_reference)}
          contentHash={workspace.workbook.composite_hash}
          workbookVersion={workspace.workbook.version}
          onRan={refreshAll}
          onReload={refreshAll}
        />
        <div key={section === "scenarios" ? "scenarios" : `scope-${scopeEpoch}`} data-scope-epoch={scopeEpoch}>
        {section === "overview" && <StatusRow workspace={workspace} />}
        {section === "inputs" && (
          recovery
            ? <RecoveryPanel project={project} payload={recovery} onRepaired={refreshAll} />
            : inputs
            ? <>
              <InputsJumpNav onJump={jumpWithinInputs} />
              <SaveScopeGuide />
              <div id="wf-inputs-setup" tabIndex={-1}>
                <SheetFieldsEditor project={project} sheet="project_setup" title="Project setup" reloadKey={dataVersion} onSaved={afterMutation} />
              </div>
              <div id="wf-inputs-grid" tabIndex={-1}>
                <CanonicalInputGrid payload={inputs} busy={busy} onSave={saveCells} onRefresh={refreshAll} />
              </div>
              <div id="wf-inputs-costs" tabIndex={-1}>
                <CostLinesView project={project} reloadKey={dataVersion} onMutated={afterMutation}
                  requestedSheet={costRequest.sheet} requestNonce={costRequest.nonce} />
              </div>
              <div id="wf-inputs-revenue" tabIndex={-1}>
                {revenuePayload && (
                  <PPAEditorView
                    project={project}
                    protectedReference={Boolean(workspace.project.protected_reference)}
                    contracts={revenuePayload.contracts}
                    save={revenuePayload.save}
                    onSaved={afterMutation}
                  />
                )}
              </div>
            </>
            : <p className="rx-boot-loading" role="status">Loading the canonical input grid…</p>
        )}
        {section === "financing" && (
          <FinancingStudio project={project} reloadKey={dataVersion} onSaved={afterMutation} legacyUrl={legacyUrl} />
        )}
        {section === "scenarios" && (
          <ScenarioWorkspace project={project} freshness={workspace.freshness.state}
            onScenarioChanged={onScenarioChanged} onDataChanged={afterMutation} />
        )}
        {section === "diagnostics" && <DiagnosticsView project={project} />}
        {section === "trust" && <TrustView project={project} />}
        {section === "statements" && (
          statements
            ? statementsConflict
            ? <StatementIdentityConflict workspace={workspace} statements={statements} />
            : <>
              {statements.state === "STALE" && (
                <p className="rx-banner rx-banner-stale" role="status" data-stale-banner="true">
                  STALE — the Working Copy changed after the persisted Last Run. The statements
                  are the prior Run&rsquo;s values; they are not the current inputs.
                </p>
              )}
              <div data-statements-view="true" data-statements-state={statements.state}>
                <VerticalScopeBanner vertical={workspace.vertical} />
                <StatementWorkbook
                  projectIdentity={{ code: workspace.project.code, name: workspace.project.name, type: workspace.project.project_type }}
                  snapshot={statements.state === "NOT_RUN" || statements.state === "UNAVAILABLE" ? null : toStatementSnapshot(statements)}
                  status={toStatementStatus(statements)}
                />
              </div>
            </>
            : <p className="rx-boot-loading" role="status">Loading the persisted statements…</p>
        )}
        {section === "results" && (
          statements
            ? statementsConflict
            ? <StatementIdentityConflict workspace={workspace} statements={statements} />
            : <div data-results-view="true" data-results-state={statements.state}>
              <VerticalScopeBanner vertical={workspace.vertical} />
              <FinancialResults payload={statements} page="results" />
              <RunsView project={project} />
              <ModelExportView project={project} freshness={workspace.freshness.state} legacyUrl={legacyUrl} />
            </div>
            : <p className="rx-boot-loading" role="status">Loading the persisted results…</p>
        )}
        {section === "analysis" && (
          <AnalysisTools project={project} protectedReference={Boolean(workspace.project.protected_reference)}
            workbookHash={workspace.workbook.composite_hash} onApplied={afterMutation}
            overview={(
          <div data-analysis-view="true" data-analysis-state={statements?.state ?? "LOADING"}>
            {statements
              ? statementsConflict
              ? <StatementIdentityConflict workspace={workspace} statements={statements} />
              : <>
                <VerticalScopeBanner vertical={workspace.vertical} />
                <p className="rx-note" data-analysis-scope="last-run">
                  Charts below show the Working Copy&rsquo;s Last Run. Credit intelligence further down reads only the committed Runs you select explicitly.
                </p>
                <FinancialResults payload={statements} page="analysis" />
              </>
              : <p className="rx-boot-loading" role="status">Loading the persisted analysis…</p>}
            <div data-financial-insights="true">
              <FinancialInsights project={project} />
            </div>
          </div>
            )} />
        )}
        </div>
        <footer className="rx-footer">
          <p className="rx-note">
            Figures are read from this project&rsquo;s saved Run and workspace records; the browser
            never calculates financial results. The classic workbook remains available.
          </p>
        </footer>
      </div>
    </Shell>
    </div>
  );
}
