import { useEffect, useLayoutEffect, useRef, useState, type FormEvent } from "react";
import type { BessCapability, BessPreview, BessResponse } from "./types";
import "./bessSetup.css";

/** Local memory only. This form never addresses a project, scenario or writer. */
export function BessSetupPreview({ capability, requestId, csrfToken }: {
  capability: BessCapability; requestId: string; csrfToken: string;
}) {
  const [cap, setCap] = useState(capability);
  const [open, setOpen] = useState(false);
  const [raw, setRaw] = useState("");
  const [loadedRaw, setLoadedRaw] = useState<string | null>(null);
  const [values, setValues] = useState<Record<string, string>>({});
  const [edits, setEdits] = useState<Record<string, string>>({});
  const [result, setResult] = useState<BessPreview | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const revision = useRef(0);
  const pending = useRef<AbortController | null>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  const retainedUrl = useRef(window.location.href);
  const allowLeave = useRef(false);

  function invalidate() {
    revision.current += 1;
    pending.current?.abort(); pending.current = null;
    setResult(null); setError(""); setBusy(false);
  }
  useEffect(() => () => { revision.current += 1; pending.current?.abort(); }, []);
  useEffect(() => {
    setCap(capability);
    revision.current += 1; pending.current?.abort();
    setResult(null); setBusy(false);
  }, [capability, requestId, csrfToken]);
  useEffect(() => { if (open) heading.current?.focus(); }, [open]);
  useLayoutEffect(() => {
    if (!raw) return;
    const warn = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = ""; };
    const confirmLeave = () => window.confirm("Leave Storage setup? The local BESS input will be lost; nothing has been saved.");
    const click = (event: MouseEvent) => {
      if (!(event.target instanceof Element) || !event.target.closest("[data-wizard-cancel]")) return;
      if (!confirmLeave()) { event.preventDefault(); event.stopImmediatePropagation(); }
      else allowLeave.current = true;
    };
    const changed = (event: Event) => {
      const next = new URL(window.location.href);
      if (next.href === retainedUrl.current) return;
      // Seeded path changes retain this mounted editor and all raw inputs.
      if (allowLeave.current || (next.hash.startsWith("#new-project") && next.searchParams.get("setup") !== "blank")) {
        retainedUrl.current = next.href; return;
      }
      if (!confirmLeave()) {
        event.stopImmediatePropagation();
        window.history.replaceState(window.history.state, "", retainedUrl.current);
        window.dispatchEvent(new HashChangeEvent("hashchange"));
      } else retainedUrl.current = next.href;
    };
    window.addEventListener("beforeunload", warn);
    window.addEventListener("click", click, true);
    window.addEventListener("hashchange", changed, true);
    window.addEventListener("popstate", changed, true);
    return () => {
      window.removeEventListener("beforeunload", warn); window.removeEventListener("click", click, true);
      window.removeEventListener("hashchange", changed, true); window.removeEventListener("popstate", changed, true);
    };
  }, [raw]);

  async function validate(event: FormEvent) {
    event.preventDefault();
    if (!cap.preview_supported || busy) return;
    invalidate();
    const attempt = revision.current;
    const controller = new AbortController(); pending.current = controller;
    setBusy(true);
    try {
      const response = await fetch("/v2/model-react/new-project/bess-preview", {
        method: "POST", credentials: "same-origin", signal: controller.signal,
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({ request_id: requestId, csrf_token: csrfToken, native_json: raw,
          edits: loadedRaw === raw ? edits : {} }),
      });
      const body: BessResponse | null = await response.json().catch(() => null);
      if (attempt !== revision.current) return;
      if (body?.capability) setCap(body.capability);
      if (!response.ok || !body?.ok || !body.preview || !body.capability?.preview_supported) {
        setError(response.status === 401 || response.status === 403
          ? "Session validation expired. Your local input is retained; sign in and reopen setup to validate."
          : `${body?.code ?? "BESS_PREVIEW_UNAVAILABLE"}: ${body?.message ?? "Validation is unavailable. Your local input is retained."}`);
        return;
      }
      setResult(body.preview);
      if (loadedRaw !== raw) {
        setValues(body.preview.battery); setEdits({}); setLoadedRaw(raw);
      }
    } catch {
      if (attempt === revision.current) setError("The server could not validate this input. Your local input is retained.");
    } finally {
      if (attempt === revision.current) { setBusy(false); pending.current = null; }
    }
  }

  return <section className="bess-setup" aria-labelledby="bess-setup-title" data-bess-setup="true">
    <div className="bess-setup-heading">
      <div><h3 id="bess-setup-title">Standalone Storage / BESS</h3>
        <p>Separate battery storage model · financial lifecycle unavailable</p></div>
      <span className="rcm-tier rcm-tier-release_closed">NOT RELEASED</span>
    </div>
    <dl className="bess-capabilities" aria-label="Storage availability">
      {([
        ["Registered reference", cap.reference_exists], ["Setup preview", cap.preview_supported],
        ["Create project", cap.create_supported], ["Save inputs", cap.save_supported], ["Financial Run", cap.run_supported],
      ] as const).map(([label, supported]) => <div key={label}><dt>{label}</dt><dd>{supported ? "Available" : "Unavailable"}</dd></div>)}
    </dl>
    <p>The protected Storage reference stays read-only. This preview keeps input in this browser tab only; it does not create a financial project or save a draft.</p>
    <button type="button" className="rx-button rx-button-secondary" aria-expanded={open} aria-controls="bess-local-preview"
      disabled={!cap.preview_supported || !csrfToken} onClick={() => setOpen(!open)}>
      {open ? "Hide setup preview (keep input)" : "Preview standalone Storage inputs"}
    </button>
    <div id="bess-local-preview" hidden={!open}>
      <h4 ref={heading} tabIndex={-1}>Local BESS setup preview</h4>
      <p id="bess-input-help">Paste your complete native BESS configuration JSON. Declare dispatch, EUR/MWh prices, UTC hourly start/end, battery balance and degradation conventions explicitly. FINCO supplies no assumptions here. Use synthetic inputs for evaluation.</p>
      <form onSubmit={(event) => void validate(event)} noValidate>
        <label htmlFor="bess-native-json">Explicit native configuration (JSON)</label>
        <textarea id="bess-native-json" rows={6} value={raw} spellCheck={false}
          aria-describedby="bess-input-help bess-local-warning" aria-invalid={Boolean(error)}
          onChange={(event) => { invalidate(); setRaw(event.target.value); }} />
        <p id="bess-local-warning" className="rx-note">Input is lost when you leave or reload this page. Hiding this preview or changing the setup path keeps it here until you leave.</p>
        {loadedRaw !== null && <fieldset disabled={loadedRaw !== raw || !cap.preview_supported}>
          <legend>Canonical battery inputs</legend>
          {loadedRaw !== raw && <p role="status">Configuration changed. Validate it to refresh these fields; earlier edits are retained until validation succeeds.</p>}
          <div className="bess-field-grid">{cap.fields.map((field) => <div key={field.name}>
            <label htmlFor={`bess-${field.name}`}>{field.label} ({field.unit})</label>
            <input id={`bess-${field.name}`} type="text" inputMode="decimal" value={values[field.name] ?? ""}
              data-bess-field={field.name} aria-describedby="bess-physical-help"
              onChange={(event) => { invalidate(); setValues({ ...values, [field.name]: event.target.value });
                setEdits({ ...edits, [field.name]: event.target.value }); }} />
            <small>{field.name}</small>
          </div>)}</div>
          <p id="bess-physical-help">Usable DC energy differs from installed energy. Efficiencies and state of health are fractions, not percentages. Round-trip efficiency must match charge × discharge efficiency. Equivalent full cycles come from the explicit dispatch and native DC two-way convention; no cycles/day assumption is added.</p>
        </fieldset>}
        <p><button className="rx-button" type="submit" disabled={!raw.trim() || busy || !cap.preview_supported || !csrfToken}
          aria-busy={busy}>{busy ? "Validating…" : "Validate setup on server"}</button></p>
        <div aria-live="polite" aria-atomic="true">
          {error && <p role="alert" className="rx-status rx-status-error" data-bess-error="true">{error}</p>}
          {result && <div className="bess-validation" data-bess-validated="true">
            <strong>Native schema valid · financial activation blocked</strong>
            <dl><div><dt>Duration (usable MWh ÷ discharge MW)</dt><dd><output>{result.battery.duration_hours} h</output></dd></div>
              <div><dt>Explicit hourly horizon</dt><dd>{result.start} → {result.end}</dd></div>
              <div><dt>Dispatch</dt><dd>{result.dispatch_mode} · {result.dispatch_rows} rows · {result.events} events</dd></div></dl>
            <p>Schema validation does not evaluate physical dispatch balance, align a financial period axis, or prove revenue, financing or Results. Nothing was saved or run.</p>
          </div>}
        </div>
      </form>
    </div>
    <details><summary>Why Create, Save and Run are unavailable</summary>
      <ul>{cap.blockers.map((blocker) => <li key={blocker.code}>{blocker.message}</li>)}</ul>
    </details>
    <p className="rx-note">Solar+BESS and Wind+BESS setup are outside this standalone preview.</p>
  </section>;
}
