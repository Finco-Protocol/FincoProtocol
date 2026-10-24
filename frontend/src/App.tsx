import { useCallback, useEffect, useState } from "react";
import { readHostConfig, type HostConfig } from "./api/client";
import { LibraryView } from "./app/LibraryView";
import { FincoNonModelExperience } from "./nonmodel/FincoNonModelExperience";
import { ThemeProvider } from "./finco/_shared/ThemeSelector";
import { WorkspaceView } from "./app/WorkspaceView";

type Phase = "loading" | "error" | "ready";

function ErrorView({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <main className="rx-page" role="main">
      <section className="rx-card" data-app-state="error">
        <h2>React preview unavailable</h2>
        <p className="rx-empty" role="alert">{message}</p>
        <p>
          <button type="button" className="rx-button" onClick={onRetry}>Retry</button>
        </p>
        <p className="rx-note">The classic FINCO Model interface remains available and authoritative.</p>
      </section>
    </main>
  );
}

/**
 * Mount-time surface selector (Concept B NON-MODEL integration V1).
 *
 * `data-surface="non-model"` on the host mount element renders the isolated
 * Concept B NON-MODEL experience (public Landing, Radar, Crypto and Roadmap
 * preview surfaces; app/v2/nonmodel_router.py serves that host page). The
 * attribute comes from static server-rendered markup and cannot change for a
 * mounted root, so reading it before any hook introduces no hook-order hazard.
 * Every other value keeps the Model workspace behavior below unchanged.
 */
export default function App({ host }: { host: HTMLElement }) {
  if (host.dataset.surface === "non-model") {
    return <FincoNonModelExperience />;
  }
  return <ModelApp host={host} />;
}

/**
 * UX-02 integrated React application.
 *
 * Route adapter (minimal, consistent with the FastAPI surface):
 *   `/v2/model-react/`                 → Project Library (canonical projects)
 *   `/v2/model-react/{project}`        → Model Workspace (inputs / statements / results)
 * Sections live in the URL hash, so Back/Forward and direct refresh work without
 * any second account/session system.  The feature flag, same-origin assets and
 * the legacy Jinja2/HTMX fallback are unchanged from UX-01.
 */
function ModelApp({ host }: { host: HTMLElement }) {
  const [config] = useState<HostConfig | null>(() => readHostConfig(host));
  const [phase, setPhase] = useState<Phase>("loading");
  const [errorMessage, setErrorMessage] = useState("");
  const [nonce, setNonce] = useState(0);

  useEffect(() => {
    if (!config) {
      setErrorMessage("Host page configuration is missing.");
      setPhase("error");
      return;
    }
    setPhase("ready");
  }, [config, nonce]);

  const retry = useCallback(() => setNonce((n) => n + 1), []);

  if (!config || phase === "loading") {
    return (
      <main className="rx-page" role="main">
        <p className="rx-boot-loading" role="status">Loading the FINCO Model React preview…</p>
      </main>
    );
  }

  if (phase === "error") {
    return <ErrorView message={errorMessage} onRetry={retry} />;
  }

  const project = config.project;
  // UX-03B: the theme layer is presentation-only; scoping it to the mount root
  // keeps the legacy Jinja/HTMX UI untouched and no data path is involved.
  if (project) {
    return (
      <ThemeProvider host={host}>
        <WorkspaceView
          key={project}
          project={project}
          legacyUrl={config.legacyUrl}
          onNavigateToLibrary={() => { window.location.href = "/v2/model-react/"; }}
        />
      </ThemeProvider>
    );
  }
  return (
    <ThemeProvider host={host}>
      <LibraryView
        onOpenProject={(code) => { window.location.href = `/v2/model-react/${encodeURIComponent(code)}`; }}
      />
    </ThemeProvider>
  );
}
