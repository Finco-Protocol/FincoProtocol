import { useEffect, useState } from "react";
import { Shell } from "../finco/_shared/FincoShell";
import { APP_ROUTES } from "./appNavigation";
import { fetchJsonEndpoint, signOutSession } from "./api";

interface CapabilitiesResp {
  capabilities?: Array<{
    key: string;
    public_name: string;
    status: string;
    runnable: boolean;
    status_note?: string;
    limitations?: string[];
  }>;
}

interface SupportedTodayResp {
  verticals?: Array<{ key: string; public_name: string; status: string; runnable: boolean }>;
  boundaries?: Record<string, unknown>;
}

interface SigningKeysResp {
  keys?: Array<{ key_id: string; algorithm?: string; status?: string }>;
}

export function GuideMethodologyView({ onBack }: { onBack: () => void }) {
  const [caps, setCaps] = useState<CapabilitiesResp | null>(null);
  const [err, setErr] = useState("");

  useEffect(() => {
    let live = true;
    void fetchJsonEndpoint<CapabilitiesResp>("/api/v1/capabilities").then((res) => {
      if (!live) return;
      if (res && "capabilities" in res) setCaps(res);
      else setErr("Capabilities summary is temporarily unavailable.");
    });
    return () => { live = false; };
  }, []);

  return (
    <Shell crumb="Guide & Methodology" dataOrigin="canonical-run" originLabel="PLATFORM GUIDE">
      <main className="rx-page" role="main" id="fm-main-content" tabIndex={-1} data-app-info-view="guide">
        <header className="rx-header">
          <div>
            <p className="rx-brand">FINCO Protocol · Model</p>
            <h1 className="rx-title">Pilot Guide, Methodology &amp; Scope</h1>
          </div>
          <nav aria-label="My Projects">
            <a className="rx-legacy-link" href={APP_ROUTES.library} onClick={(e) => { e.preventDefault(); onBack(); }}>← My Projects</a>
          </nav>
        </header>
        <section className="rx-card">
          <h2>Workflow &amp; Authority Boundaries</h2>
          <p className="rx-note">
            FINCO Model is server-authoritative: every calculation, validation, Save, and Run executes in the deterministic Python backend.
            Saving assumptions updates the working draft without running the model; results refresh only on an explicit Run.
          </p>
          <p className="rx-note">
            Supported verticals and release status below are loaded directly from the server capability registry.
          </p>
        </section>
        <section className="rx-card" aria-label="Supported technologies and limitations">
          <h2>Supported Technologies &amp; Known Boundaries</h2>
          {err && <p className="rx-empty" role="status">{err}</p>}
          {!caps && !err && <p className="rx-note" role="status">Loading capability registry…</p>}
          {caps?.capabilities?.map((c) => (
            <div key={c.key} style={{ marginBottom: "1rem", paddingBottom: "0.75rem", borderBottom: "1px solid var(--fo-slate-200, #e2e8f0)" }}>
              <p style={{ margin: "0 0 0.25rem" }}>
                <strong>{c.public_name}</strong> · <span className="rx-badge">{c.status}</span> · {c.runnable ? "Runnable" : "Read-only / Release-closed"}
              </p>
              {c.status_note && <p className="rx-note" style={{ margin: "0.25rem 0" }}>{c.status_note}</p>}
              {c.limitations && c.limitations.length > 0 && (
                <ul style={{ margin: "0.25rem 0 0", paddingLeft: "1.25rem", fontSize: "0.9rem" }}>
                  {c.limitations.map((lim, idx) => <li key={idx}>{lim}</li>)}
                </ul>
              )}
            </div>
          ))}
        </section>
      </main>
    </Shell>
  );
}

export function PlatformApiVerifyView({ onBack }: { onBack: () => void }) {
  const [supported, setSupported] = useState<SupportedTodayResp | null>(null);
  const [keys, setKeys] = useState<SigningKeysResp | null>(null);
  const [meta, setMeta] = useState<Record<string, unknown> | null>(null);

  useEffect(() => {
    let live = true;
    void Promise.all([
      fetchJsonEndpoint<SupportedTodayResp>("/api/v1_1/supported-today"),
      fetchJsonEndpoint<SigningKeysResp>("/api/v1_1/protocol/signing-keys"),
      fetchJsonEndpoint<Record<string, unknown>>("/api/v1/meta"),
    ]).then(([sup, sk, mt]) => {
      if (!live) return;
      if (sup && !("ok" in sup && sup.ok === false)) setSupported(sup as SupportedTodayResp);
      if (sk && !("ok" in sk && sk.ok === false)) setKeys(sk as SigningKeysResp);
      if (mt && !("ok" in mt && mt.ok === false)) setMeta(mt as Record<string, unknown>);
    });
    return () => { live = false; };
  }, []);

  return (
    <Shell crumb="API & Verification" dataOrigin="canonical-run" originLabel="API & VERIFICATION">
      <main className="rx-page" role="main" id="fm-main-content" tabIndex={-1} data-app-info-view="platform">
        <header className="rx-header">
          <div>
            <p className="rx-brand">FINCO Protocol · Platform</p>
            <h1 className="rx-title">API Surface &amp; Public Verification</h1>
          </div>
          <nav aria-label="My Projects">
            <a className="rx-legacy-link" href={APP_ROUTES.library} onClick={(e) => { e.preventDefault(); onBack(); }}>← My Projects</a>
          </nav>
        </header>
        <section className="rx-card">
          <h2>Programmatic Read-Only API v1 &amp; v1.1</h2>
          <p className="rx-note">
            FINCO exposes read-only endpoints under <code>/api/v1</code> and <code>/api/v1_1</code> for canonical reference models, project status,
            run identity, exports, and run-certificate verification.
          </p>
          {meta && (
            <dl className="rcm-facts">
              <div><dt>API version</dt><dd>{String(meta.api_version ?? "v1")}</dd></div>
              <div><dt>Engine version</dt><dd>{String(meta.engine_version ?? "canonical")}</dd></div>
            </dl>
          )}
        </section>
        <section className="rx-card">
          <h2>Run Certificate Signing Keys &amp; Verification</h2>
          <p className="rx-note">
            A signed Run certificate attests that the persisted Run snapshot is unaltered; it does not assert external economic truth.
            Per-project Trust &amp; Integrity checks remain inside each project&rsquo;s Trust section.
          </p>
          {keys?.keys && keys.keys.length > 0 ? (
            <ul>
              {keys.keys.map((k) => (
                <li key={k.key_id}><code>{k.key_id}</code> ({k.algorithm ?? "Ed25519"} · {k.status ?? "active"})</li>
              ))}
            </ul>
          ) : (
            <p className="rx-note" role="status">No active public signing keys published in this environment.</p>
          )}
          {supported?.verticals && (
            <p className="rx-note">Active registry verticals: {supported.verticals.map((v) => `${v.public_name} (${v.status})`).join(", ")}</p>
          )}
        </section>
        <section className="rx-card">
          <h2>FINCO Radar Boundary</h2>
          <p className="rx-note">
            FINCO Radar is deployed as a separate external service and is not embedded inside FINCO Model. No external Radar URL is configured in this workspace.
          </p>
        </section>
      </main>
    </Shell>
  );
}

export function AccountSessionView({ onBack }: { onBack: () => void }) {
  const [health, setHealth] = useState<{ status: string } | null>(null);
  const [signingOut, setSigningOut] = useState(false);

  useEffect(() => {
    let live = true;
    void fetchJsonEndpoint<{ status?: string }>("/health").then((res) => {
      if (!live) return;
      if (res && "status" in res && typeof res.status === "string") setHealth({ status: res.status });
      else setHealth({ status: "unauthenticated" });
    });
    return () => { live = false; };
  }, []);

  const handleSignOut = async () => {
    setSigningOut(true);
    await signOutSession();
  };

  return (
    <Shell crumb="Account & Session" dataOrigin="canonical-run" originLabel="SESSION">
      <main className="rx-page" role="main" id="fm-main-content" tabIndex={-1} data-app-info-view="account">
        <header className="rx-header">
          <div>
            <p className="rx-brand">FINCO Protocol · Account</p>
            <h1 className="rx-title">Session &amp; Access</h1>
          </div>
          <nav aria-label="My Projects">
            <a className="rx-legacy-link" href={APP_ROUTES.library} onClick={(e) => { e.preventDefault(); onBack(); }}>← My Projects</a>
          </nav>
        </header>
        <section className="rx-card">
          <h2>Current Session</h2>
          <p className="rx-note">
            Authentication status: <strong data-session-status={health?.status ?? "checking"}>{health ? health.status : "Checking…"}</strong>
          </p>
          <p className="rx-note">
            Sessions use same-origin HttpOnly cookies and operation-scoped CSRF tokens for every mutation.
          </p>
          <p>
            <button type="button" className="rx-button" disabled={signingOut} data-account-signout="true" onClick={() => void handleSignOut()}>
              {signingOut ? "Signing out…" : "Sign out"}
            </button>
          </p>
        </section>
      </main>
    </Shell>
  );
}
