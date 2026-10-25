import React, { Suspense, lazy, useCallback, useEffect, useMemo, useState } from "react";
import { FincoTransferProvider } from "./context";
import {
  TRANSFER_CALLER_STATEMENT_STATUS,
  TRANSFER_DEMO_RUN_STATUS,
  TRANSFER_DEMO_STATEMENT,
  TRANSFER_EMPTY_STATEMENT_STATUS,
} from "./fixtures";
import {
  TRANSFER_CALLER_RESULTS_STATUS,
  TRANSFER_DEMO_RESULTS,
  TRANSFER_DEMO_RESULTS_STATUS,
  TRANSFER_EMPTY_RESULTS_STATUS,
  TRANSFER_PARTIAL_RESULTS,
} from "./resultsFixtures";
import { resolveTransferProductState, TRANSFER_DEMO_STATE_OPTIONS, type TransferDemoStateId } from "./productStates";
import { canonicalFincoHref, contextFromRoute, resolveFincoRoute } from "./routes";
import type { FincoRoute } from "./routes";
import type { ResultsPresentationSnapshot, ResultsRunStatus } from "../src/finco/_results/resultsContract";
import { SYNTHETIC_REFERENCE_PROJECTS as SYNTHETIC_LIBRARY_PROJECTS } from "../src/finco/_shared/demoProjectFixtures";
import type { StatementRunStatus } from "../src/finco/_workbook/statementContract";

const ProjectLibrary = lazy(async () => ({
  default: (await import("../src/finco/ProjectLibrary")).ProjectLibrary,
}));
const ModelWorkspace = lazy(async () => ({
  default: (await import("../src/finco/ModelWorkspace")).ModelWorkspace,
}));
const ResultsAnalysis = lazy(async () => ({
  default: (await import("../src/finco/ResultsAnalysisView")).ResultsAnalysisView,
}));

type LocationState = { pathname: string; search: string; hash: string };

function getBasePath(): string {
  return window.__FINCO_TRANSFER_BASE__ || "/";
}

function readLocation(): LocationState {
  return {
    pathname: window.location.pathname,
    search: window.location.search,
    hash: window.location.hash,
  };
}

function routeFromLocation(location: LocationState, basePath: string): FincoRoute {
  return resolveFincoRoute(location.pathname, location.search, basePath);
}

function TransferPage({
  route,
  resultsSnapshot,
  resultsStatus,
  statementSnapshot,
  statementStatus,
}: {
  route: FincoRoute;
  statementSnapshot: ReturnType<typeof resolveTransferProductState>["statementSnapshot"];
  resultsSnapshot: ResultsPresentationSnapshot | null;
  resultsStatus: ResultsRunStatus;
  statementStatus: StatementRunStatus;
}) {
  if (route.page === "library") return (
    <ProjectLibrary sampleProjects={SYNTHETIC_LIBRARY_PROJECTS} />
  );
  if (route.page === "workspace") return <ModelWorkspace />;
  if (route.page === "results") {
    return <ResultsAnalysis
      resultsSnapshot={resultsSnapshot}
      resultsStatus={resultsStatus}
      statementSnapshot={statementSnapshot}
      statementStatus={statementStatus}
    />;
  }
  return (
    <main className="finco-root fm-shell" style={{ paddingTop: 32 }}>
      <h1 className="fm-title">FINCO demo route unavailable</h1>
      <p className="fm-subtitle">This isolated transfer entry exposes only the existing Library, Workspace and Results pages.</p>
      <a className="fm-btn" href={`${getBasePath()}projects`}>Return to Project Library</a>
    </main>
  );
}

class TransferRouteErrorBoundary extends React.Component<
  { children: React.ReactNode },
  { failed: boolean }
> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  render() {
    if (this.state.failed) {
      return (
        <main className="finco-root fm-shell" role="alert" style={{ padding: 32 }}>
          <h1 className="fm-title">FINCO demo view could not load</h1>
          <p className="fm-subtitle">This visual-only route failed to render. No model run or data write was attempted.</p>
          <a className="fm-btn" href={`${getBasePath()}projects`}>Return to Project Library</a>
        </main>
      );
    }
    return this.props.children;
  }
}

export default function FincoTransferApp() {
  const basePath = getBasePath();
  const [location, setLocation] = useState(readLocation);
  const route = useMemo(() => routeFromLocation(location, basePath), [location, basePath]);
  const projectContext = useMemo(
    () => contextFromRoute(route, location.search),
    [route, location.search],
  );
  const params = new URLSearchParams(location.search);
  const rawState = params.get("qaState") as TransferDemoStateId | null;
  const stateId = TRANSFER_DEMO_STATE_OPTIONS.some((option) => option.id === rawState)
    ? rawState as TransferDemoStateId
    : params.get("mode") === "reference" ? "protected-reference" : "last-run-current";
  const productState = resolveTransferProductState(stateId);
  const legacyResultsVariant = rawState ? null : params.get("qaResults");
  const legacyStatementVariant = rawState ? null : params.get("qaStatement");
  const statementSnapshot = legacyStatementVariant === "empty"
    ? null
    : legacyStatementVariant ? TRANSFER_DEMO_STATEMENT : productState.statementSnapshot;
  const statementStatus = legacyStatementVariant === "empty"
    ? TRANSFER_EMPTY_STATEMENT_STATUS
    : legacyStatementVariant === "caller"
      ? TRANSFER_CALLER_STATEMENT_STATUS
      : productState.statementStatus;
  const resultsSnapshot = legacyResultsVariant === "empty"
    ? null
    : legacyResultsVariant === "partial"
      ? TRANSFER_PARTIAL_RESULTS
      : legacyResultsVariant ? TRANSFER_DEMO_RESULTS : productState.resultsSnapshot;
  const resultsStatus = legacyResultsVariant === "empty"
    ? TRANSFER_EMPTY_RESULTS_STATUS
    : legacyResultsVariant === "partial"
      ? TRANSFER_CALLER_RESULTS_STATUS
      : legacyResultsVariant ? TRANSFER_DEMO_RESULTS_STATUS : productState.resultsStatus;

  const chooseProductState = useCallback((next: TransferDemoStateId) => {
    const query = new URLSearchParams(window.location.search);
    query.set("qaState", next);
    query.set("mode", next === "protected-reference" ? "reference" : "working-copy");
    window.history.pushState(null, "", `${window.location.pathname}?${query.toString()}${window.location.hash}`);
    setLocation(readLocation());
  }, []);

  const navigate = useCallback((href: string) => {
    const canonicalHref = canonicalFincoHref(href, basePath, projectContext.projectId);
    if (!canonicalHref) {
      window.location.assign(href);
      return;
    }
    window.history.pushState(null, "", canonicalHref);
    setLocation(readLocation());
    window.scrollTo({ top: 0, behavior: "auto" });
  }, [basePath, projectContext.projectId]);

  useEffect(() => {
    const sync = () => setLocation(readLocation());
    window.addEventListener("popstate", sync);
    window.__FINCO_TRANSFER_NAVIGATE__ = navigate;
    return () => {
      window.removeEventListener("popstate", sync);
      if (window.__FINCO_TRANSFER_NAVIGATE__ === navigate) {
        delete window.__FINCO_TRANSFER_NAVIGATE__;
      }
    };
  }, [navigate]);

  const captureInternalLink = useCallback((event: React.MouseEvent<HTMLElement>) => {
    if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    const target = event.target instanceof Element ? event.target.closest("a[href]") : null;
    if (!(target instanceof HTMLAnchorElement) || target.target || target.hasAttribute("download")) return;
    const href = new URL(target.href, window.location.origin);
    if (href.origin !== window.location.origin) return;
    const canonicalHref = canonicalFincoHref(href.href, basePath, projectContext.projectId);
    if (!canonicalHref) return;
    const current = new URL(window.location.href);
    const canonical = new URL(canonicalHref, window.location.origin);
    if (canonical.pathname === current.pathname && canonical.search === current.search && canonical.hash !== current.hash) return;
    event.preventDefault();
    event.stopPropagation();
    navigate(canonicalHref);
  }, [basePath, navigate, projectContext.projectId]);

  const providerValue = useMemo(() => ({
    route,
    project: {
      id: projectContext.projectId,
      name: projectContext.projectName,
      technology: projectContext.technology,
      mode: projectContext.mode,
    },
    scenarioId: projectContext.scenarioId,
    contractId: projectContext.contractId,
    facilityId: projectContext.facilityId,
    statementSnapshot,
    statementStatus,
    navigate,
  }), [route, projectContext, navigate, statementStatus]);

  return (
    <FincoTransferProvider value={providerValue}>
      <div
        data-testid="finco-transfer-app"
        data-route={route.page}
        data-project-id={projectContext.projectId}
        data-scenario-id={projectContext.scenarioId}
        onClickCapture={captureInternalLink}
      >
        <aside
          data-testid="transfer-demo-state-selector"
          aria-label="Transfer harness demo state selector"
          style={{ display: "flex", alignItems: "center", flexWrap: "wrap", gap: 8, padding: "7px 12px", borderBottom: "1px solid #d7e0e8", background: "#f5f8fb", color: "#344a60", fontSize: 10 }}
        >
          <strong>QA STATE SELECTOR · transfer harness only</strong>
          <label style={{ display: "flex", alignItems: "center", gap: 5 }}>
            <span className="fm-sr-only">Transfer demo product state</span>
            <select aria-label="Transfer demo product state" data-testid="transfer-demo-state" value={stateId} onChange={(event) => chooseProductState(event.target.value as TransferDemoStateId)}>
              {TRANSFER_DEMO_STATE_OPTIONS.map((option) => <option key={option.id} value={option.id}>{option.label}</option>)}
            </select>
          </label>
          <span role="status">{productState.explanation}</span>
        </aside>
        <TransferRouteErrorBoundary key={`${route.page}:${route.projectId || "library"}:${location.search}`}>
          <Suspense fallback={<div role="status" style={{ padding: 24 }}>Loading FINCO demo view…</div>}>
              <TransferPage route={route} statementSnapshot={statementSnapshot} resultsSnapshot={resultsSnapshot} resultsStatus={resultsStatus} statementStatus={statementStatus} />
          </Suspense>
        </TransferRouteErrorBoundary>
      </div>
    </FincoTransferProvider>
  );
}
