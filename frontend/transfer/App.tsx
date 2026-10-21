import React, { Suspense, lazy, useCallback, useEffect, useMemo, useState } from "react";
import { FincoTransferProvider } from "./context";
import { TRANSFER_DEMO_RUN_STATUS, TRANSFER_DEMO_STATEMENT } from "./fixtures";
import { canonicalFincoHref, contextFromRoute, resolveFincoRoute } from "./routes";
import type { FincoRoute } from "./routes";

const ProjectLibrary = lazy(async () => ({
  default: (await import("../src/finco/ProjectLibrary")).ProjectLibrary,
}));
const ModelWorkspace = lazy(async () => ({
  default: (await import("../src/finco/ModelWorkspace")).ModelWorkspace,
}));
const ResultsAnalysis = lazy(async () => ({
  default: (await import("../src/finco/ResultsAnalysis")).ResultsAnalysis,
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

function TransferPage({ route }: { route: FincoRoute }) {
  if (route.page === "library") return <ProjectLibrary />;
  if (route.page === "workspace") return <ModelWorkspace />;
  if (route.page === "results") {
    return <ResultsAnalysis statementSnapshot={TRANSFER_DEMO_STATEMENT} statementStatus={TRANSFER_DEMO_RUN_STATUS} />;
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
    statementSnapshot: TRANSFER_DEMO_STATEMENT,
    statementStatus: TRANSFER_DEMO_RUN_STATUS,
    navigate,
  }), [route, projectContext, navigate]);

  return (
    <FincoTransferProvider value={providerValue}>
      <div
        data-testid="finco-transfer-app"
        data-route={route.page}
        data-project-id={projectContext.projectId}
        data-scenario-id={projectContext.scenarioId}
        onClickCapture={captureInternalLink}
      >
        <TransferRouteErrorBoundary key={`${route.page}:${route.projectId || "library"}:${location.search}`}>
          <Suspense fallback={<div role="status" style={{ padding: 24 }}>Loading FINCO demo view…</div>}>
            <TransferPage route={route} />
          </Suspense>
        </TransferRouteErrorBoundary>
      </div>
    </FincoTransferProvider>
  );
}
