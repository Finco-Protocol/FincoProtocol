import { useCallback, useEffect, useState } from "react";
import { fetchBootstrap, readHostConfig, type HostConfig } from "./api/client";
import type {
  BootstrapError,
  BootstrapPayload,
  FreshnessProjection,
  GridSaveSuccess,
} from "./api/types";
import { CitRateField } from "./components/CitRateField";
import { PnlNotRun, PnlStatement } from "./components/PnlStatement";
import { EngineBadge, FreshnessBadge, IntegrityBadge, RunIdentityLine } from "./components/StatusBar";

type Phase =
  | { kind: "loading" }
  | { kind: "error"; failure: BootstrapError }
  | { kind: "ready"; data: BootstrapPayload };

function ErrorView({ failure, legacyUrl, onRetry }: { failure: BootstrapError; legacyUrl: string; onRetry: () => void }) {
  const text =
    failure.code === "REACT_POC_DISABLED"
      ? "The React preview is disabled by its feature flag on this server."
      : failure.code === "AUTH_REQUIRED"
        ? "Your session is not authorized. Sign in and reload."
        : failure.code === "PROJECT_NOT_FOUND"
          ? "This project does not exist or is not accessible with your account."
          : failure.message || "The FINCO Model server could not provide the authorized workspace snapshot.";
  return (
    <main className="rx-page" role="main">
      <Header legacyUrl={legacyUrl} projectName={null} />
      <section className="rx-card" data-bootstrap-state={failure.code}>
        <h2>React preview unavailable</h2>
        <p className="rx-empty" role="alert">{text}</p>
        {failure.code !== "REACT_POC_DISABLED" && (
          <p>
            <button type="button" className="rx-button" onClick={onRetry}>Retry</button>
          </p>
        )}
        <p className="rx-note">The classic FINCO Model interface remains available and authoritative.</p>
      </section>
    </main>
  );
}

function Header({ legacyUrl, projectName }: { legacyUrl: string; projectName: string | null }) {
  return (
    <header className="rx-header">
      <div>
        <p className="rx-brand">FINCO Protocol · Model</p>
        <h1 className="rx-title">
          React Preview (UX-01 PoC)
          {projectName ? <span className="rx-project-name"> — {projectName}</span> : null}
        </h1>
      </div>
      <nav aria-label="Legacy interface">
        <a className="rx-legacy-link" href={legacyUrl}>Open the legacy workbook ↗</a>
      </nav>
    </header>
  );
}

export default function App({ host }: { host: HTMLElement }) {
  const [config] = useState<HostConfig | null>(() => readHostConfig(host));
  const [phase, setPhase] = useState<Phase>({ kind: "loading" });
  const [identity, setIdentity] = useState<{
    compositeHash: string;
    workbookVersion: string;
    scenarioId: string | null;
    csrfToken: string;
    freshness: FreshnessProjection;
  } | null>(null);

  const load = useCallback(async () => {
    if (!config) return;
    setPhase({ kind: "loading" });
    const result = await fetchBootstrap(config);
    if (result.ok) {
      setIdentity({
        compositeHash: result.workbook.composite_hash,
        workbookVersion: result.workbook.version,
        scenarioId: result.workbook.scenario_id,
        csrfToken: result.csrf_token,
        freshness: result.freshness,
      });
      setPhase({ kind: "ready", data: result });
    } else {
      setPhase({ kind: "error", failure: result });
    }
  }, [config]);

  useEffect(() => {
    if (!config) {
      setPhase({ kind: "error", failure: { ok: false, code: "WORKSPACE_UNAVAILABLE", message: "Host page configuration is missing." } });
      return;
    }
    void load();
  }, [config, load]);

  // The canonical Save returns the new authoritative composite hash; the parent
  // owns it so a subsequent Save is CAS-checked against the fresh identity.
  const handleSaved = useCallback(
    (body: GridSaveSuccess) => {
      setIdentity((prev) =>
        prev
          ? {
              ...prev,
              compositeHash: body.content_hash,
              workbookVersion: body.workbook_version,
              scenarioId: body.scenario_id,
              freshness: { ...prev.freshness, state: body.run_state, is_stale: body.run_state === "STALE" },
            }
          : prev,
      );
    },
    [],
  );

  if (!config || phase.kind === "loading") {
    return (
      <main className="rx-page" role="main">
        <p className="rx-boot-loading" role="status">Loading the FINCO Model React preview…</p>
      </main>
    );
  }

  if (phase.kind === "error") {
    return <ErrorView failure={phase.failure} legacyUrl={config.legacyUrl} onRetry={() => void load()} />;
  }

  const data = phase.data;
  const outputs = data.outputs;
  const showStaleBanner = identity?.freshness.state === "STALE";

  return (
    <main className="rx-page" role="main" data-react-poc-version={data.react_poc.version}>
      <Header legacyUrl={config.legacyUrl} projectName={data.project.name} />
      {identity && (
        <section className="rx-card" aria-labelledby="rx-status-heading">
          <h2 id="rx-status-heading">Working Copy status</h2>
          <div className="rx-badges" data-working-copy-hash={identity.compositeHash}>
            <FreshnessBadge freshness={identity.freshness} />
            <IntegrityBadge outputs={outputs} />
            <EngineBadge outputs={outputs} />
          </div>
          <RunIdentityLine outputs={outputs} />
          {showStaleBanner && (
            <p className="rx-banner rx-banner-stale" role="status" data-stale-banner="true">
              STALE — the Working Copy changed after the persisted Last Run. The statements
              below are the prior Run&rsquo;s values; they are not the current inputs.
              The React PoC does not run the model.
            </p>
          )}
        </section>
      )}
      {identity && (
        <CitRateField
          field={data.field}
          workbook={{
            version: identity.workbookVersion,
            composite_hash: identity.compositeHash,
            scenario_id: identity.scenarioId,
            scenario_name: data.workbook.scenario_name,
          }}
          csrfToken={identity.csrfToken}
          saveUrl={config.saveUrl}
          projectCode={config.project}
          onSaved={handleSaved}
        />
      )}
      {outputs.pnl ? <PnlStatement pnl={outputs.pnl} /> : <PnlNotRun state={outputs.state === "UNAVAILABLE" ? "UNAVAILABLE" : "NOT_RUN"} />}
      <footer className="rx-footer">
        <p className="rx-note">
          UX-01 architecture proof: React 18 + TypeScript + Vite shell over the existing
          canonical FINCO Model authorities. The legacy Jinja2/HTMX workbook remains the
          default experience for ordinary users.
        </p>
      </footer>
    </main>
  );
}
