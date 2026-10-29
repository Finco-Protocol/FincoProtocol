import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import StatementWorkbook from "../finco/_workbook/StatementWorkbook";
import { Shell } from "../finco/_shared/FincoShell";
import { AnalysisTools } from "./analysis/AnalysisTools";
import { FinancingStudio } from "./financing/FinancingStudio";
import { workspaceHeading } from "./adapters";
import { fetchInputs, fetchStatements, fetchWorkspace } from "./api";
import { RecoveryPanel } from "./RecoveryPanel";
import { toStatementSnapshot, toStatementStatus } from "./adapters";
import { FinancialResults } from "./FinancialResults";
import { WorkspaceNav, type WorkspaceSection } from "./WorkspaceNav";
import { WorkspaceSidebar } from "./WorkspaceSidebar";
import { FinancialOverview } from "./FinancialOverview";
import { ReportPrecisionControl } from "./ReportPrecision";
import { financialInputOrder } from "./inputLayout";
import { workspaceRoute, INPUT_DESTINATIONS, type WorkspaceDestination } from "./workspaceNavigation";
import { WorkspaceExtensionBoundary, type WorkspaceExtensionContext, type ConfirmedRun, type WorkspaceExtensions } from "./workspaceExtensions";
import "../styles/wsv2-core.css";
import { CanonicalInputGrid, type GridSaveOutcome } from "./CanonicalInputGrid";
import { CostLinesView, DiagnosticsView, RunsView, TrustView } from "./ux040506Views";
import { FinancialInsights } from "./insights";
import { InputsJumpNav, SaveScopeGuide, type InputsJump } from "./InputsGuide";
import { InputStudios } from "./studios/InputStudios";
import { FriendlyError, resultStatus, RESULT_STATUS_HELP } from "./productLanguage";
import { RunIdentityLabel } from "./runIdentity";
import { VerticalScopeBanner } from "./VerticalScope";
import "../styles/rc-react-mvp.css";
import { ModelExportView } from "./workflow/ModelExportView";
import { PPAEditorView } from "./workflow/PPAEditorView";
import { ScenarioWorkspace } from "./workflow/ScenarioWorkspace";
import { SheetFieldsEditor } from "./workflow/SheetFieldsEditor";
import { WorkflowBar } from "./workflow/WorkflowBar";
import { DirtyProvider, useLeaveGuard, useDirtyTotal } from "./workflow/workflowShared";
import { isRecoveryPayload, type InputsPayload, type RecoveryPayload, type RevenueContractsPayload, type StatementsPayload, type WorkspacePayload } from "./types";
import { fetchRevenueContracts } from "./api";

type Section = WorkspaceSection;

function sectionFromHash(): Section {
  return workspaceRoute(window.location.hash).section;
}

/** Chip text for the shell: whether the saved results match the project as it is saved now. */
const RUN_CHIP: Record<string, string> = { CURRENT: "RESULTS UP TO DATE", STALE: "RESULTS OUTDATED", NOT_RUN: "NOT RUN YET" };

function FreshnessBadge({ state }: { state: string }) {
  const cls = state === "CURRENT" ? "rx-badge rx-badge-ok"
    : state === "STALE" ? "rx-badge rx-badge-stale" : "rx-badge";
  return <span className={cls} data-freshness={state}>{resultStatus(state)}</span>;
}

function StatusRow({ workspace }: { workspace: WorkspacePayload }) {
  const identity = workspace.identity;
  return (
    <div className="rx-card" aria-labelledby="rx-status-heading" data-workspace-status="true">
      <h2 id="rx-status-heading">Project status</h2>
      <div className="rx-badges" data-working-copy-hash={workspace.workbook.composite_hash}>
        <FreshnessBadge state={workspace.freshness.state} />
      </div>
      <p className="rx-note" data-status-help="true">{RESULT_STATUS_HELP[workspace.freshness.state] ?? ""}</p>
      <p className="rx-run-identity" data-run-state={workspace.freshness.state}>
        {identity
          ? <>Last Run: <RunIdentityLabel snapshotId={identity.snapshot_id} />{" · "}scenario {identity.scenario_proven ? identity.scenario : "not available"}</>
          : "No Run yet. Use Run model above to calculate results; saving never runs the model."}
      </p>
      <p className="rx-note">Active scenario: {workspace.workbook.scenario_name || "Base Case"}</p>
      <VerticalScopeBanner vertical={workspace.vertical} />
      <details className="rx-advanced" data-advanced-details="true">
        <summary>Advanced details · audit trail</summary>
        <dl className="rcm-facts">
          <div><dt>Model checks</dt><dd data-integrity={workspace.integrity?.status ?? "UNAVAILABLE"}>{workspace.integrity?.status === "PASS" ? "Passed" : workspace.integrity?.status ?? "Not available"}</dd></div>
          <div><dt>Calculation engine</dt><dd data-engine-currency={workspace.engine.currency ?? "ENGINE_IDENTITY_UNKNOWN"}>{workspace.engine.currency === "CURRENT_ENGINE" ? "Current version"
            : workspace.engine.currency === "ENGINE_SUPERSEDED" ? "Superseded version" : "Version not recorded"}</dd></div>
          <div><dt>Saved inputs version</dt><dd className="fm-mono" style={{ overflowWrap: "anywhere" }}>{workspace.workbook.composite_hash}</dd></div>
          {identity && <div><dt>Last Run record</dt><dd className="fm-mono" style={{ overflowWrap: "anywhere" }}>{identity.snapshot_id}</dd></div>}
        </dl>
      </details>
    </div>
  );
}

function StatementIdentityConflict({ workspace, statements }: { workspace: WorkspacePayload; statements: StatementsPayload }) {
  return (
    <section className="rx-card" role="alert" data-statement-identity="conflict">
      <h2>Run views could not be matched</h2>
      <p>
        The statements for <strong>{statements.project.name}</strong> and the workspace for{" "}
        <strong>{workspace.project.name}</strong> describe different projects, Runs or input states.
        Figures are withheld. Reload to reconcile; if this persists, open the project again from My Projects.
      </p>
    </section>
  );
}

interface WorkspaceViewProps {
  project: string;
  onNavigateToLibrary: () => void;
  extensions?: WorkspaceExtensions;
}

/** The unsaved-change registry wraps the whole workspace so navigation, Reload and
 *  Run all consult the same state the editors report into. */
export function WorkspaceView(props: WorkspaceViewProps) {
  return <DirtyProvider><WorkspaceViewInner {...props} /></DirtyProvider>;
}

function WorkspaceViewInner({ project, onNavigateToLibrary, extensions }: WorkspaceViewProps) {
  const confirmIfDirty = useLeaveGuard();
  const { total: dirtyTotal } = useDirtyTotal();
  const dirtyTotalRef = useRef(dirtyTotal);
  dirtyTotalRef.current = dirtyTotal;
  const [section, setSection] = useState<Section>(sectionFromHash);
  const [destination, setDestination] = useState<WorkspaceDestination>(() => workspaceRoute(window.location.hash).destination);
  const destinationRef = useRef(destination);
  destinationRef.current = destination;
  const readEpoch = useRef(0);
  const [runRefresh, setRunRefresh] = useState<"idle" | "reading" | "blocked">("idle");
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
  const displayedInputs = useMemo(() => inputs ? financialInputOrder(inputs) : null, [inputs]);
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
    const epoch = readEpoch.current;
    const result = await fetchWorkspace(project);
    if (epoch !== readEpoch.current) return;
    if ("ok" in result && result.ok === true) setWorkspace(result);
    else setError(result as { code: string; message?: string });
  }, [project]);

  const loadStatements = useCallback(async () => {
    const epoch = readEpoch.current;
    const result = await fetchStatements(project);
    if (epoch !== readEpoch.current) return;
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
    ++readEpoch.current;
    setRunRefresh((state) => state === "reading" ? "blocked" : state);
    setStatements(null);
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
    if (runRefresh !== "idle") return;
    if ((section === "statements" || section === "overview") && !statements) void loadStatements();
    if ((section === "results" || section === "analysis") && !statements) void loadStatements();
    if (section === "inputs" && !inputs && !recovery) void loadInputs();
    if (section === "inputs" && !revenuePayload) void loadRevenue();
  }, [section, statements, inputs, recovery, revenuePayload, loadStatements, loadInputs, loadRevenue, runRefresh]);

  // Hash changes (typed URL, Back/Forward) are guarded like tab clicks: the URL has
  // already moved, so "stay" restores the hash of the section that is still shown.
  useEffect(() => {
    const onHash = () => {
      const route = workspaceRoute(window.location.hash);
      const raw = window.location.hash.replace(/^#/, "");
      // Native anchors (including Skip to main content) are not section routes.
      if (raw && route.destination !== raw) return;
      const adopt = () => { setSection(route.section); setDestination(route.destination); };
      if (allowNextHash.current) { allowNextHash.current = false; adopt(); return; }
      if (route.destination === destinationRef.current) return;
      // Moving between groups leaves the same editors mounted, so their drafts survive.
      if (route.section === sectionRef.current) { adopt(); return; }
      confirmIfDirty(adopt, {
        ignore: (key) => key === "run",
        onStay: () => window.history.replaceState(null, "", `${window.location.pathname}${window.location.search}#${destinationRef.current}`),
      });
    };
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, [confirmIfDirty]);

  function navigateTo(next: WorkspaceDestination) {
    if (next === destinationRef.current) return;
    const target = workspaceRoute(next);
    const adopt = () => {
      if (window.location.hash !== `#${next}`) allowNextHash.current = true;
      window.location.hash = next;
      setDestination(next);
      setSection(target.section);
    };
    if (target.section === sectionRef.current) adopt();
    else confirmIfDirty(adopt, { ignore: (key) => key === "run" });
  }
  function navigate(sectionId: Section) { navigateTo(sectionId); }

  useEffect(() => { window.scrollTo({ top: 0 }); }, [section]);

  useEffect(() => {
    const route = workspaceRoute(destination);
    if (!route.input || section !== "inputs" || !inputs) return;
    if (route.input === "capex" || route.input === "opex") {
      const sheet = route.input;
      setCostRequest((prev) => ({ sheet, nonce: prev.nonce + 1 }));
    }
    const target = route.input === "technical"
      ? document.querySelector<HTMLElement>('[data-grid-section="project_setup-technical"]')
        ?? document.getElementById(INPUT_DESTINATIONS[route.input].target)
      : document.getElementById(INPUT_DESTINATIONS[route.input].target);
    target?.scrollIntoView({ block: "start" });
    target?.focus({ preventScroll: true });
  }, [destination, section, inputs]);

  // Any other in-app link that leaves this page (Project Library breadcrumb, legacy
  // workbook, ...) asks first when edits are unsaved.  Modified clicks open a new
  // tab/window and downloads stay on the page, so they are not intercepted.
  const guardLinkClick = (event: React.MouseEvent) => {
    if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    const anchor = (event.target as HTMLElement).closest("a");
    if (!anchor) return;
    const href = anchor.getAttribute("href") || "";
    if (!href || href.startsWith("#") || anchor.hasAttribute("download") || (anchor.target && anchor.target !== "_self")) return;
    if (anchor.hasAttribute("data-nav-my-projects") || anchor.hasAttribute("data-nav-new-project-workspace")) return;
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

  const reconcileRun = useCallback(async (run: ConfirmedRun) => {
    const epoch = ++readEpoch.current;
    setRunRefresh("reading");
    setStatements(null);
    // No writes, engine calls or scope remounts here. Both projections must name
    // the exact Run the existing D-029 API already verified in persisted history.
    try {
      const [nextWorkspace, nextStatements] = await Promise.all([fetchWorkspace(project), fetchStatements(project)]);
      const fence = await fetchWorkspace(project);
      if (epoch !== readEpoch.current) return;
      if (!("ok" in nextWorkspace && nextWorkspace.ok === true && "ok" in nextStatements && nextStatements.ok === true && "ok" in fence && fence.ok === true)
        || nextWorkspace.project.code !== project || nextStatements.project.code !== project
        || fence.project.code !== project || fence.identity?.snapshot_id !== run.snapshotId
        || fence.workbook.composite_hash !== nextWorkspace.workbook.composite_hash
        || fence.workbook.version !== nextWorkspace.workbook.version
        || fence.workbook.scenario_id !== nextWorkspace.workbook.scenario_id
        || fence.freshness.state !== nextWorkspace.freshness.state
        || nextStatements.state !== nextWorkspace.freshness.state
        || nextStatements.freshness.state !== nextWorkspace.freshness.state
        || nextWorkspace.identity?.snapshot_id !== run.snapshotId || nextStatements.status.runId !== run.snapshotId) {
        setRunRefresh("blocked");
        return;
      }
      setWorkspace(nextWorkspace);
      setStatements(nextStatements);
      setDataVersion((version) => version + 1);
      setRunRefresh("idle");
      // A resume may happen with drafts: do not navigate away and destroy them.
      if (dirtyTotalRef.current === 0) {
        setSection("results"); setDestination("results");
        window.history.replaceState(null, "", `${window.location.pathname}${window.location.search}#results`);
      }
    } catch { if (epoch === readEpoch.current) setRunRefresh("blocked"); }
  }, [project]);

  // Reads the canonical Inputs projection again WITHOUT a page reload, so a staged draft survives reconciliation
  // of a lost Save response or a CAS conflict.  Every editor re-reads its CAS token through the data version.
  const reconcileInputs = useCallback(async (): Promise<InputsPayload | null> => {
    const result = await fetchInputs(project);
    if (!("ok" in result && result.ok === true)) return null;
    setRecovery(null);
    setInputs(result);
    setDataVersion((v) => v + 1);
    void loadWorkspace();
    return result;
  }, [project, loadWorkspace]);

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
          message: "We could not confirm the Save: the response was not readable. The server may have committed this Save. Reload to reconcile before saving again.",
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
          <h2>This project is unavailable</h2>
          <FriendlyError code={error.code} message={error.message} />
          <p>
            <button type="button" className="rx-button rx-button-secondary" onClick={onNavigateToLibrary}>Back to My Projects</button>
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
  // A project block without a code makes no identity claim (as before); a code that differs, or a Run/state that differs from the
  // workspace's own Run, withholds every figure.
  const statementsConflict = Boolean(statements && ((statements.project.code && statements.project.code !== workspace.project.code)
    || (statements.snapshot && (statements.status.runId !== workspace.identity?.snapshot_id
      || statements.state !== workspace.freshness.state))));

  const extensionContext: WorkspaceExtensionContext = {
    projectId: project, workbookVersion: workspace.workbook.version, contentHash: workspace.workbook.composite_hash,
    activeScenario: workspace.workbook.scenario_id, activeScenarioName: workspace.workbook.scenario_name,
    lastRunSnapshotId: workspace.identity?.snapshot_id ?? null,
    pendingChanges: extensions?.pendingChanges ?? [], validation: extensions?.validation ?? [],
    draftState: extensions?.draftState ?? "clean", onCommitted: afterMutation, onRefetch: loadWorkspace,
  };

  return (
    <div style={{ display: "contents" }} onClickCapture={guardLinkClick} data-leave-guard="true">
    <Shell crumb={workspace.project.name} dataOrigin="canonical-run" mainContentId="rx-main-content"
      originLabel={RUN_CHIP[workspace.freshness.state] ?? "RUN UNAVAILABLE"}>
      <div className="rx-page wsv2-page" role="main" id="rx-main-content" tabIndex={-1} data-react-workspace-version={workspace.react_workspace.version}>
        <header className="rx-header">
          <div>
            <p className="rx-brand">FINCO Protocol · Model</p>
            <h1 className="rx-title">{workspaceHeading(workspace)}
              {workspace.project.protected_reference && <span className="rx-badge">TEMPLATE · READ ONLY</span>}
            </h1>
          </div>
          <nav aria-label="Workspace navigation">
            <a className="rx-legacy-link" href="/v2/model-react/" data-nav-my-projects="true" onClick={(e) => { e.preventDefault(); confirmIfDirty(onNavigateToLibrary); }}>My Projects</a>
            {" · "}
            <a className="rx-legacy-link" href="/v2/model-react/#new-project" data-nav-new-project-workspace="true" onClick={(e) => { e.preventDefault(); confirmIfDirty(() => { window.location.href = "/v2/model-react/#new-project"; }); }}>New Project</a>
          </nav>
        </header>
        <div className="wsv2-layout">
        <WorkspaceSidebar active={destination} onNavigate={navigateTo} />
        <div className="wsv2-content" id="wsv2-content">
        <div className="wsv2-section-index"><WorkspaceNav active={section} onNavigate={navigate} /></div>
        <ReportPrecisionControl />
        <WorkflowBar
          project={project}
          freshness={workspace.freshness.state}
          protectedReference={Boolean(workspace.project.protected_reference)}
          contentHash={workspace.workbook.composite_hash}
          workbookVersion={workspace.workbook.version}
          onRan={reconcileRun}
          onReload={refreshAll}
          reconciliationBlocked={runRefresh !== "idle"}
        />
        {runRefresh !== "idle" && <div role={runRefresh === "blocked" ? "alert" : "status"} className="rx-card" data-run-refresh={runRefresh}>
          {runRefresh === "reading" ? "Reading the confirmed Run…" : "The Run was committed, but its current views could not be matched. Reload to reconcile before relying on the results. No extra Run was started."}
        </div>}
        <WorkspaceExtensionBoundary extensions={extensions} context={extensionContext}>
        {extensions?.renderChanges?.(extensionContext)}
        <div key={section === "scenarios" ? "scenarios" : `scope-${scopeEpoch}`} data-scope-epoch={scopeEpoch}>
        {section === "overview" && <>
          {runRefresh === "idle" && (statements ? statementsConflict
            ? <StatementIdentityConflict workspace={workspace} statements={statements} />
            : <FinancialOverview project={project} payload={statements} />
            : <p role="status">Loading saved Run overview…</p>)}
          <StatusRow workspace={workspace} />
        </>}
        {section === "inputs" && (
          recovery
            ? <RecoveryPanel project={project} payload={recovery} onRepaired={refreshAll} />
            : inputs && displayedInputs
            ? <>
              <InputsJumpNav onJump={jumpWithinInputs} />
              <SaveScopeGuide />
              <div id="wf-inputs-setup" tabIndex={-1}>
                <SheetFieldsEditor project={project} sheet="project_setup" title="Project & Timeline" reloadKey={dataVersion} onSaved={afterMutation} />
              </div>
              <div id="wf-inputs-grid" tabIndex={-1}>
                <CanonicalInputGrid payload={displayedInputs} busy={busy} onSave={saveCells} onReconcile={reconcileInputs} />
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
              <div id="wf-inputs-studios" tabIndex={-1}>
                <InputStudios project={project} protectedReference={Boolean(workspace.project.protected_reference)}
                  reloadKey={dataVersion} onSaved={afterMutation} onSaveCells={saveCells} />
              </div>
            </>
            : <p className="rx-boot-loading" role="status">Loading the project assumptions…</p>
        )}
        {section === "financing" && (
          <FinancingStudio project={project} reloadKey={dataVersion} onSaved={afterMutation} />
        )}
        {section === "scenarios" && (
          <ScenarioWorkspace project={project} freshness={workspace.freshness.state}
            onScenarioChanged={onScenarioChanged} onDataChanged={afterMutation} />
        )}
        {section === "diagnostics" && <DiagnosticsView project={project} />}
        {section === "trust" && <TrustView project={project} />}
        {section === "statements" && runRefresh === "idle" && (
          statements
            ? statementsConflict
            ? <StatementIdentityConflict workspace={workspace} statements={statements} />
            : <>
              {statements.state === "STALE" && (
                <p className="rx-banner rx-banner-stale" role="status" data-stale-banner="true">
                  Results outdated — the project changed after the last Run. The statements
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
            : <p className="rx-boot-loading" role="status">Loading the statements…</p>
        )}
        {section === "results" && runRefresh === "idle" && (
          statements
            ? statementsConflict
            ? <StatementIdentityConflict workspace={workspace} statements={statements} />
            : <div data-results-view="true" data-results-state={statements.state}>
              <div className="rx-badges" data-results-freshness="true"><FreshnessBadge state={workspace.freshness.state} /></div>
              <VerticalScopeBanner vertical={workspace.vertical} />
              <FinancialResults payload={statements} page="results" />
              <RunsView project={project} />
              <ModelExportView project={project} freshness={workspace.freshness.state} />
            </div>
            : <p className="rx-boot-loading" role="status">Loading the results…</p>
        )}
        {section === "analysis" && runRefresh === "idle" && (
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
                  Charts below show the project&rsquo;s Last Run. Credit intelligence further down reads only the committed Runs you select explicitly.
                </p>
                <FinancialResults payload={statements} page="analysis" />
              </>
              : <p className="rx-boot-loading" role="status">Loading the analysis…</p>}
            <div data-financial-insights="true">
              <FinancialInsights project={project} />
            </div>
          </div>
            )} />
        )}
        </div>
        </WorkspaceExtensionBoundary>
        <footer className="rx-footer">
          <p className="rx-note">
            Figures are read from this project&rsquo;s saved Run and workspace records; the browser
            never calculates financial results.
          </p>
        </footer>
        </div>
        </div>
      </div>
    </Shell>
    </div>
  );
}
