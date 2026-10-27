import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import "../../finco/_group.css";
import "../../styles/finco-live.css";
import "../../styles/rcm-new-project.css";
import { Shell } from "../../finco/_shared/FincoShell";
import {
  clearPending, createNewProject, fetchWizardOptions, fetchWizardPreview, fetchWizardStatus, readPending, savePending,
} from "./api";
import type {
  CreatedProject, PendingNotice, WizardFieldError, WizardInput, WizardOptions, WizardPreview, WizardTechnology,
} from "./types";

const STEPS = [
  { id: 1, label: "Technology" },
  { id: 2, label: "Project details" },
  { id: 3, label: "Timeline" },
  { id: 4, label: "Review & create" },
] as const;

const TIER_TEXT: Record<string, string> = {
  PILOT_CANDIDATE: "PILOT CANDIDATE", PREVIEW: "PREVIEW", RELEASE_CLOSED: "NOT RELEASED", UNCLASSIFIED: "UNCLASSIFIED",
};

const LIBRARY_URL = "/v2/model-react/";

function errorFor(errors: WizardFieldError[], field: string): string {
  return errors.find((e) => e.field === field)?.message ?? "";
}

function TierBadge({ tier }: { tier: string }) {
  return <span className={`rcm-tier rcm-tier-${tier.toLowerCase()}`} data-tier={tier}>{TIER_TEXT[tier] ?? tier}</span>;
}

/**
 * RC-M Lane A — New Project wizard (4 steps).
 *
 * Presentation only.  Technology cards, countries, bounds and timeline defaults arrive from the
 * canonical registries/factories; validation and the effective CAPEX/OPEX come from the server preview;
 * Create is one authenticated POST that makes a single user-owned working copy.  The wizard holds no
 * financial default, never runs the model, and never retries an ambiguous Create.
 */
export function NewProjectWizard({ onCancel }: { onCancel: () => void }) {
  const [options, setOptions] = useState<WizardOptions | null>(null);
  const [loadError, setLoadError] = useState("");
  const [step, setStep] = useState<1 | 2 | 3 | 4>(1);
  const [techKey, setTechKey] = useState("");
  const [ack, setAck] = useState(false);
  const [input, setInput] = useState<Omit<WizardInput, "technology">>({ name: "", country: "", capacity_mw: "" });
  const [countryTouched, setCountryTouched] = useState(false);
  const [errors, setErrors] = useState<WizardFieldError[]>([]);
  const [stepError, setStepError] = useState("");
  const [preview, setPreview] = useState<WizardPreview | null>(null);
  const [busy, setBusy] = useState<"" | "validating" | "creating">("");
  const [created, setCreated] = useState<CreatedProject | null>(null);
  const [unknown, setUnknown] = useState("");
  const [notice, setNotice] = useState<PendingNotice | null>(null);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const submitting = useRef(false);

  const loadOptions = useCallback(async () => {
    const result = await fetchWizardOptions();
    if (result.ok) { setOptions(result.options); setLoadError(""); } else setLoadError(result.message);
  }, []);

  useEffect(() => { void loadOptions(); }, [loadOptions]);

  // A previous Create whose outcome was never seen is reconciled by request identity, never repeated.
  useEffect(() => {
    const pending = readPending();
    if (!pending) return;
    let live = true;
    void fetchWizardStatus(pending).then((status) => {
      if (!live) return;
      if (status.kind === "created") { clearPending(); setNotice({ kind: "created", project: status.project }); }
      else setNotice({ kind: "unknown" });
    });
    return () => { live = false; };
  }, []);

  useEffect(() => { headingRef.current?.focus({ preventScroll: false }); }, [step]);

  const tech: WizardTechnology | undefined = useMemo(
    () => options?.technologies.find((t) => t.key === techKey), [options, techKey]);

  function chooseTechnology(candidate: WizardTechnology) {
    if (!candidate.creatable) return;
    setTechKey(candidate.key);
    setAck(false);
    setStepError("");
    setPreview(null);
    setInput((prev) => ({
      ...prev,
      country: countryTouched && prev.country ? prev.country : candidate.default_country ?? "",
      capacity_mw: candidate.default_capacity_mw !== undefined ? String(candidate.default_capacity_mw) : "",
    }));
  }

  function nextFromTechnology() {
    if (!tech || !tech.creatable) { setStepError("Select a technology to continue."); return; }
    if (tech.preview_acknowledgement_required && !ack) {
      setStepError("Acknowledge the preview limitations to continue."); return;
    }
    setStepError("");
    setStep(2);
  }

  async function nextFromDetails(event?: FormEvent) {
    event?.preventDefault();
    if (busy) return;
    setStepError("");
    setBusy("validating");
    const result = await fetchWizardPreview({ ...input, technology: techKey });
    setBusy("");
    if (result.kind === "ok") { setErrors([]); setPreview(result.preview); setStep(3); return; }
    if (result.kind === "invalid") {
      setErrors(result.errors);
      if (errorFor(result.errors, "technology")) { setStepError(errorFor(result.errors, "technology")); setStep(1); }
      return;
    }
    setStepError(result.message);
  }

  async function create() {
    if (!options || !preview || submitting.current) return;
    submitting.current = true;
    setBusy("creating");
    setStepError("");
    savePending(options.request_id);
    const result = await createNewProject({
      requestId: options.request_id, csrfToken: options.csrf_token,
      input: { ...input, technology: techKey }, acknowledgePreview: ack,
    });
    if (result.kind === "created") {
      clearPending();
      setCreated(result.project);
      window.location.assign(result.project.workspace_url);
      return;                                   // the page navigates away; submit stays locked
    }
    if (result.kind === "refused") {
      clearPending();
      submitting.current = false;
      setBusy("");
      if (result.errors?.length) { setErrors(result.errors); setStep(2); }
      setStepError(result.message);
      return;
    }
    // Unknown outcome: one read-only reconciliation by request id; otherwise fail closed (no retry control).
    const status = await fetchWizardStatus(options.request_id);
    if (status.kind === "created") {
      clearPending();
      setCreated(status.project);
      window.location.assign(status.project.workspace_url);
      return;
    }
    setBusy("");
    setUnknown(result.message);                 // submit stays locked on purpose: refresh the Library first
  }

  const crumb = "New project";

  if (loadError) {
    return (
      <Shell crumb={crumb} dataOrigin="canonical-run" originLabel="NEW PROJECT UNAVAILABLE">
        <main className="rx-page" role="main" data-new-project-wizard="error">
          <section className="rx-card">
            <h2>New Project unavailable</h2>
            <p className="rx-empty" role="alert">{loadError}</p>
            <p><button type="button" className="rx-button" onClick={() => void loadOptions()}>Retry</button>{" "}
              <button type="button" className="rx-button rx-button-secondary" onClick={onCancel}>Back to the Library</button></p>
          </section>
        </main>
      </Shell>
    );
  }
  if (!options) {
    return <main className="rx-page" role="main"><p className="rx-boot-loading" role="status">Loading New Project…</p></main>;
  }

  const locked = busy === "creating" || Boolean(unknown) || Boolean(created);
  const nameError = errorFor(errors, "name");
  const countryError = errorFor(errors, "country");
  const capacityError = errorFor(errors, "capacity_mw");
  const effective = preview?.effective;

  return (
    <Shell crumb={crumb} dataOrigin="canonical-run" originLabel="NEW PROJECT">
      <main className="rx-page rcm-wizard" role="main" id="fm-main-content" tabIndex={-1}
            data-new-project-wizard="true" data-wizard-step={step} data-create-state={created ? "created" : unknown ? "unknown" : busy === "creating" ? "creating" : "idle"}>
        <header className="rx-header">
          <div>
            <p className="rx-brand">FINCO Protocol · Model</p>
            <h1 className="rx-title">New project</h1>
          </div>
          <nav aria-label="Project Library"><a className="rx-legacy-link" href={LIBRARY_URL} onClick={(e) => { e.preventDefault(); onCancel(); }}>← Project Library</a></nav>
        </header>

        {notice && (
          <p className="rx-status rx-status-conflict rcm-notice" role="status" data-previous-create={notice.kind}>
            {notice.kind === "created"
              ? <>Your earlier request “{notice.project.name}” was created. <a href={notice.project.workspace_url}>Open it</a>.</>
              : <>Result unknown for your earlier create request — check the Project Library before creating a project again.</>}
            {" "}<button type="button" className="rx-button rx-button-secondary" onClick={() => { clearPending(); setNotice(null); }}>Dismiss</button>
          </p>
        )}

        <ol className="rcm-steps" aria-label="New project steps">
          {STEPS.map((s) => (
            <li key={s.id} className={s.id === step ? "active" : s.id < step ? "done" : ""}
                aria-current={s.id === step ? "step" : undefined} data-step-id={s.id}>
              <span className="rcm-step-num" aria-hidden="true">{s.id}</span><span className="rcm-step-label">{s.label}</span>
            </li>
          ))}
        </ol>
        <p className="rcm-step-compact" aria-hidden="true">Step {step} of 4 · {STEPS[step - 1].label}</p>

        <section className="rx-card" aria-labelledby="rcm-step-heading">
          <h2 id="rcm-step-heading" ref={headingRef} tabIndex={-1}>{step}. {STEPS[step - 1].label}</h2>

          {step === 1 && (
            <div data-wizard-panel="technology">
              <p className="rx-note">Choose the technology template. Defaults come from the canonical reference model; nothing is run until you press Run.</p>
              <div className="rcm-cards" role="radiogroup" aria-label="Technology">
                {options.technologies.map((t) => (
                  <button key={t.key} type="button" role="radio" aria-checked={techKey === t.key}
                          aria-disabled={!t.creatable} disabled={!t.creatable}
                          className={`rcm-card${techKey === t.key ? " selected" : ""}`} data-tech-card={t.key} data-creatable={t.creatable}
                          onClick={() => chooseTechnology(t)}>
                    <span className="rcm-card-head"><strong>{t.public_name}</strong><TierBadge tier={t.pilot_tier} /></span>
                    <span className="rcm-card-body">
                      {t.creatable
                        ? (t.limitations[0] ?? t.status_note ?? "")
                        : (t.reason || "Not released for working copies.")}
                    </span>
                  </button>
                ))}
              </div>
              {tech?.preview_acknowledgement_required && (
                <div className="rcm-preview-box" role="group" aria-label="Preview limitations" data-preview-limitations="true">
                  <strong>{tech.public_name} is a PREVIEW vertical.</strong>
                  <ul>{tech.limitations.map((l) => <li key={l}>{l}</li>)}</ul>
                  <label className="rcm-check"><input type="checkbox" checked={ack} data-preview-ack="true"
                         onChange={(e) => setAck(e.target.checked)} /> I understand the limitations of this preview.</label>
                </div>
              )}
            </div>
          )}

          {step === 2 && tech && (
            <form className="rcm-form" onSubmit={(e) => void nextFromDetails(e)} noValidate data-wizard-panel="details">
              {/* two text-like fields block implicit submission: an inert default button makes Enter advance */}
              <button type="submit" hidden tabIndex={-1} aria-hidden="true" />
              <div className="rcm-field">
                <label htmlFor="rcm-name">Project name</label>
                <input id="rcm-name" className="rx-input" type="text" autoComplete="off" value={input.name}
                       maxLength={options.bounds.name_max_length} aria-invalid={Boolean(nameError)}
                       aria-describedby={nameError ? "rcm-name-err" : undefined}
                       onChange={(e) => setInput({ ...input, name: e.target.value })} />
                {nameError && <span id="rcm-name-err" className="rx-status rx-status-error" role="alert">{nameError}</span>}
              </div>
              <div className="rcm-field">
                <label htmlFor="rcm-country">Country / market</label>
                <select id="rcm-country" className="rx-input" value={input.country} aria-invalid={Boolean(countryError)}
                        aria-describedby={countryError ? "rcm-country-err" : "rcm-country-hint"}
                        onChange={(e) => { setCountryTouched(true); setInput({ ...input, country: e.target.value }); }}>
                  {options.countries.map((c) => <option key={c.code} value={c.code}>{c.label}</option>)}
                </select>
                <span id="rcm-country-hint" className="rx-note">Location metadata only: every market uses the same Generic Tax Template.</span>
                {countryError && <span id="rcm-country-err" className="rx-status rx-status-error" role="alert">{countryError}</span>}
              </div>
              <div className="rcm-field">
                <label htmlFor="rcm-capacity">{tech.capacity_label}</label>
                <input id="rcm-capacity" className="rx-input" type="number" inputMode="decimal" step="any"
                       min={options.bounds.capacity_min_mw} max={options.bounds.capacity_max_mw} value={input.capacity_mw}
                       aria-invalid={Boolean(capacityError)} aria-describedby={capacityError ? "rcm-capacity-err" : "rcm-capacity-hint"}
                       onChange={(e) => setInput({ ...input, capacity_mw: e.target.value })} />
                <span id="rcm-capacity-hint" className="rx-note">
                  {options.bounds.capacity_min_mw}–{options.bounds.capacity_max_mw.toLocaleString("en-US")} MW · reference model: {tech.default_capacity_mw} MW. CAPEX and OPEX scale from the reference.
                </span>
                {capacityError && <span id="rcm-capacity-err" className="rx-status rx-status-error" role="alert">{capacityError}</span>}
              </div>
            </form>
          )}

          {step === 3 && tech && effective && (
            <div data-wizard-panel="timeline">
              <p className="rx-note">The timeline starts from the canonical {tech.public_name} reference. It is shown for review; adjust it in Inputs after the project exists.</p>
              <dl className="rcm-defs" data-timeline-defaults="true">
                <div><dt>Financial close</dt><dd data-timeline="financial_close">{effective.timeline.financial_close}</dd></div>
                <div><dt>Construction period</dt><dd data-timeline="construction_months">{effective.timeline.construction_months} months</dd></div>
                <div><dt>Commercial operation date (COD)</dt><dd data-timeline="cod_date">{effective.timeline.cod_date}</dd></div>
                <div><dt>Model horizon</dt><dd data-timeline="horizon_years">{effective.timeline.horizon_years} years</dd></div>
              </dl>
            </div>
          )}

          {step === 4 && tech && effective && preview && (
            <div data-wizard-panel="review">
              <p className="rx-note">Review the effective assumptions the server will save. Create makes one working copy in your account and does not run the model.</p>
              <table className="rcm-review" aria-label="Effective assumptions">
                <tbody>
                  <tr><th scope="row">Project</th><td data-review="name">{preview.normalised.name}</td></tr>
                  <tr><th scope="row">Technology</th><td data-review="technology">{tech.public_name} <TierBadge tier={tech.pilot_tier} /></td></tr>
                  <tr><th scope="row">Country / market</th><td data-review="country">{effective.country_label}</td></tr>
                  <tr><th scope="row">{effective.capacity_label}</th><td data-review="capacity">{effective.capacity_mw.toLocaleString("en-US")} MW <span className="rx-note">(reference {effective.reference_capacity_mw} MW · scale ×{effective.scale_ratio.toFixed(3)})</span></td></tr>
                  <tr><th scope="row">Total CAPEX (scaled)</th><td data-review="capex">{effective.total_capex_display} kEUR</td></tr>
                  <tr><th scope="row">OPEX, year 1 (scaled)</th><td data-review="opex">{effective.opex_y1_display} kEUR</td></tr>
                  <tr><th scope="row">Construction / COD / horizon</th><td data-review="timeline">{effective.timeline.construction_months} months · COD {effective.timeline.cod_date} · {effective.timeline.horizon_years} years</td></tr>
                  <tr><th scope="row">Tax template</th><td data-review="tax">{effective.tax_template}</td></tr>
                  <tr><th scope="row">Initial status</th><td data-review="status"><span className="rx-lib-badge">NOT RUN</span> Working copy · editable · saved to your account</td></tr>
                </tbody>
              </table>
            </div>
          )}

          {stepError && <p className="rx-status rx-status-error" role="alert" data-wizard-error="true">{stepError}</p>}
          {unknown && (
            <div className="rx-status rx-status-conflict" role="alert" data-create-unknown="true">
              <p>{unknown}</p>
              <p><a className="rx-button" href={LIBRARY_URL} data-refresh-library="true">Refresh the Library</a></p>
            </div>
          )}
          {created && <p className="rx-status rx-status-saved" role="status" data-create-success="true">Project created. Opening <a href={created.workspace_url}>{created.name}</a>…</p>}

          <div className="rcm-actions">
            <button type="button" className="rx-button rx-button-secondary" data-wizard-back="true"
                    disabled={step === 1 || locked || busy === "validating"} onClick={() => { setStepError(""); setStep((s) => (s > 1 ? ((s - 1) as 1 | 2 | 3) : s)); }}>Back</button>
            <button type="button" className="rx-button rx-button-secondary" data-wizard-cancel="true" disabled={locked} onClick={onCancel}>Cancel</button>
            {step === 1 && <button type="button" className="rx-button" data-wizard-next="true" disabled={!tech} onClick={nextFromTechnology}>Next</button>}
            {step === 2 && <button type="button" className="rx-button" data-wizard-next="true" disabled={busy === "validating"} onClick={() => void nextFromDetails()}>{busy === "validating" ? "Checking…" : "Next"}</button>}
            {step === 3 && <button type="button" className="rx-button" data-wizard-next="true" onClick={() => setStep(4)}>Next</button>}
            {step === 4 && <button type="button" className="rx-button" data-wizard-create="true" disabled={locked || !preview} aria-busy={busy === "creating"} onClick={() => void create()}>{busy === "creating" ? "Creating…" : "Create project"}</button>}
          </div>
        </section>
      </main>
    </Shell>
  );
}
