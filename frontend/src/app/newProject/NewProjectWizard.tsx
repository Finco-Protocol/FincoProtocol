import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type FormEvent } from "react";
import "../../finco/_group.css";
import "../../styles/finco-live.css";
import "../../styles/rcm-new-project.css";
import "../../styles/rcux-product.css";
import { plain } from "../productLanguage";
import { Shell } from "../../finco/_shared/FincoShell";
import {
  clearPending, createNewProject, fetchTemplates, fetchWizardOptions, fetchWizardPreview, fetchWizardStatus, pathFromHash, readPending, savePending,
  type WizardPath,
} from "./api";
import { pendingRequest, releasePendingRequest, retainPendingRequest } from "../library/api";
import type {
  CreatedProject, PendingNotice, TemplateCard, WizardFieldError, WizardInput, WizardOptions, WizardPreview, WizardTechnology,
} from "./types";

const STEPS = [
  { id: 1, label: "Start" },
  { id: 2, label: "Project details" },
  { id: 3, label: "Review & create" },
] as const;

const TIER_TEXT: Record<string, string> = {
  PILOT_CANDIDATE: "RELEASED", PREVIEW: "PREVIEW", RELEASE_CLOSED: "NOT RELEASED", UNCLASSIFIED: "UNCLASSIFIED",
};

const LIBRARY_URL = "/v2/model-react/";

const PATH_HASH: Record<WizardPath, string> = { "": "new-project", new: "new-project/new", template: "new-project/template" };

function errorFor(errors: WizardFieldError[], field: string): string {
  return errors.find((e) => e.field === field)?.message ?? "";
}

function TierBadge({ tier }: { tier: string }) {
  return <span className={`rcm-tier rcm-tier-${tier.toLowerCase()}`} data-tier={tier}>{TIER_TEXT[tier] ?? tier}</span>;
}

/**
 * New Project wizard (3 steps, two supported creation paths).
 *
 * Path A "Create a new project" is a guided setup that starts from FINCO's approved starting assumptions for the chosen technology
 * (a completely blank model is not available).  Path B "Start from a template" shows the approved template, its starting assumptions and
 * limitations first.  Both finish in the same request-keyed creator, which makes one project you own; the template is never modified.
 *
 * Presentation only.  Technologies, templates, countries, bounds and timeline defaults arrive from the server's registries; validation
 * and the effective CAPEX/OPEX come from the server preview.  The wizard holds no financial default, never runs the model, and never
 * retries an ambiguous Create.
 */
function SeededNewProjectWizard({ onCancel }: { onCancel: () => void }) {
  const [options, setOptions] = useState<WizardOptions | null>(null);
  const [loadError, setLoadError] = useState("");
  const [step, setStep] = useState<1 | 2 | 3>(1);
  const [path, setPath] = useState<WizardPath>(() => pathFromHash(window.location.hash));
  const [templates, setTemplates] = useState<TemplateCard[] | null>(null);
  const [templatesError, setTemplatesError] = useState("");
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

  // Templates are read only when that path is chosen (read-only; nothing is created or changed by looking).
  useEffect(() => {
    if (path !== "template" || templates) return;
    let live = true;
    void fetchTemplates().then((result) => {
      if (!live) return;
      if (result.ok) { setTemplates(result.templates); setTemplatesError(""); } else setTemplatesError(result.message);
    });
    return () => { live = false; };
  }, [path, templates]);

  const choosePath = (next: WizardPath) => {
    setPath(next);
    setTechKey(""); setAck(false); setStepError(""); setPreview(null);
    if (!readPending()) window.history.replaceState(null, "", `${window.location.pathname}${window.location.search}#${PATH_HASH[next]}`);
  };

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
    if (!tech || !tech.creatable) { setStepError(path === "template" ? "Select a template to continue." : "Select a technology to continue."); return; }
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
      window.location.assign(`${result.project.workspace_url.split("#")[0]}#inputs`);
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
      window.location.assign(`${status.project.workspace_url.split("#")[0]}#inputs`);
      return;
    }
    setBusy("");
    setUnknown(result.message);                 // submit stays locked on purpose: refresh the Library first
  }

  const crumb = "New project";
  const template = path === "template" ? templates?.find((t) => t.key === techKey) : undefined;

  if (loadError) {
    return (
      <Shell crumb={crumb} dataOrigin="canonical-run" originLabel="NEW PROJECT UNAVAILABLE">
        <main className="rx-page" role="main" data-new-project-wizard="error">
          <section className="rx-card">
            <h2>New Project is unavailable</h2>
            <p className="rx-empty" role="alert">{loadError}</p>
            <p><button type="button" className="rx-button" onClick={() => void loadOptions()}>Retry</button>{" "}
              <button type="button" className="rx-button rx-button-secondary" onClick={onCancel}>Back to My Projects</button></p>
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
          <nav aria-label="My Projects"><a className="rx-legacy-link" href={LIBRARY_URL} onClick={(e) => { e.preventDefault(); onCancel(); }}>← My Projects</a></nav>
        </header>

        {notice && (
          <p className="rx-status rx-status-conflict rcm-notice" role="status" data-previous-create={notice.kind}>
            {notice.kind === "created"
              ? <>Your earlier request “{notice.project.name}” was created. <a href={notice.project.workspace_url}>Open it</a>.</>
              : <>We could not confirm whether your earlier project was created — check My Projects before creating it again.</>}
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
        <p className="rcm-step-compact" aria-hidden="true">Step {step} of 3 · {STEPS[step - 1].label}</p>

        <section className="rx-card" aria-labelledby="rcm-step-heading">
          <h2 id="rcm-step-heading" ref={headingRef} tabIndex={-1}>{step}. {STEPS[step - 1].label}</h2>

          {step === 1 && (
            <div data-wizard-panel="technology" data-wizard-path={path || "unset"}>
              {path === "" && (
                <>
                  <p className="rx-note">How would you like to start? You can change this at any time before you create the project.</p>
                  <div className="rcux-paths" role="group" aria-label="How to start">
                    <button type="button" className="rcux-path" data-path-card="new" onClick={() => choosePath("new")}>
                      <strong>Approved Defaults</strong>
                      <span>Guided setup: name the project, pick the technology, market and capacity. FINCO fills in its approved starting assumptions, and every value stays editable afterwards.</span>

                    </button>
                    <button type="button" className="rcux-path" data-path-card="template" onClick={() => choosePath("template")}>
                      <strong>Start from a template</strong>
                      <span>Choose a ready-made starting model, review its starting assumptions and limitations, then create your own editable project from it.</span>
                    </button>
                  </div>
                  <div className="rx-advanced" data-blank-project-constraint="true">
                    <button type="button" className="rx-button rx-button-secondary" onClick={() => {
                      const url = new URL(window.location.href); url.searchParams.set("setup", "blank"); url.hash = "new-project";
                      window.history.pushState(window.history.state, "", url);
                      window.dispatchEvent(new HashChangeEvent("hashchange"));
                    }}>Blank setup draft</button>
                    <p>Save explicit inputs without starting assumptions. This is a non-runnable setup draft; promotion to a runnable model is not yet validated.</p>
                  </div>
                </>
              )}
              {path === "new" && (
                <>
                  <p className="rx-note" data-path-note="new">
                    <strong>Create a new project.</strong> Choose the technology. FINCO starts the project from its approved starting assumptions for that technology — nothing is run until you press Run.
                    {" "}<button type="button" className="rx-button rx-button-secondary" data-path-change="true" onClick={() => choosePath("")}>Change how I start</button>
                  </p>
                  <div className="rcm-cards" role="radiogroup" aria-label="Technology">
                    {options.technologies.map((t) => (
                      <button key={t.key} type="button" role="radio" aria-checked={techKey === t.key}
                              aria-disabled={!t.creatable} disabled={!t.creatable}
                              className={`rcm-card${techKey === t.key ? " selected" : ""}`} data-tech-card={t.key} data-creatable={t.creatable}
                              onClick={() => chooseTechnology(t)}>
                        <span className="rcm-card-head"><strong>{t.public_name}</strong><TierBadge tier={t.pilot_tier} /></span>
                        <span className="rcm-card-body">
                          {t.creatable
                            ? plain(t.limitations[0] ?? t.status_note ?? "")
                            : (t.reason || "Not available yet.")}
                        </span>
                      </button>
                    ))}
                  </div>
                </>
              )}
              {path === "template" && (
                <>
                  <p className="rx-note" data-path-note="template">
                    <strong>Start from a template.</strong> A template is a starting point, not a project: choosing it creates a new project you own, and the template itself never changes.
                    {" "}<button type="button" className="rx-button rx-button-secondary" data-path-change="true" onClick={() => choosePath("")}>Change how I start</button>
                  </p>
                  {templatesError && <p className="rx-status rx-status-error" role="alert">{templatesError}</p>}
                  {!templates && !templatesError && <p className="rx-note" role="status">Loading templates…</p>}
                  <div className="rcux-template-grid" role="radiogroup" aria-label="Project templates">
                    {(templates ?? []).map((t) => {
                      const wizardTech = options.technologies.find((x) => x.key === t.key);
                      return (
                        <button key={t.key} type="button" role="radio" aria-checked={techKey === t.key} disabled={!t.creatable || !wizardTech}
                                className="rcux-template" data-tech-card={t.key} data-template-card={t.key} data-creatable={t.creatable}
                                onClick={() => wizardTech && chooseTechnology(wizardTech)}>
                          <span className="rcm-card-head"><strong>{t.technology}</strong><TierBadge tier={t.pilot_tier} /></span>
                          <span>{t.description}</span>
                          {t.creatable ? (
                            <>
                              <span className="rx-note">{t.capacity_label}: <strong>{t.capacity_mw?.toLocaleString("en-GB")} MW</strong>
                                {t.timeline ? <> · construction {t.timeline.construction_months} months · operation to {t.timeline.horizon_years} years</> : null}</span>
                              {t.starting_assumptions.length > 0 && (
                                <ul aria-label={`Key starting assumptions for ${t.technology}`} data-template-assumptions={t.key}>
                                  {t.starting_assumptions.map((a) => <li key={a.label}>{a.label}: <strong>{a.value}{a.unit ? ` ${a.unit}` : ""}</strong></li>)}
                                </ul>
                              )}
                              <span className="rx-note">{t.market_note}</span>
                              {t.limitations[0] && <span className="rx-note">Limitation: {plain(t.limitations[0])}</span>}
                            </>
                          ) : <span className="rx-note">{t.reason || "Not available yet."}</span>}
                        </button>
                      );
                    })}
                  </div>
                </>
              )}
              {path !== "" && tech?.preview_acknowledgement_required && (
                <div className="rcm-preview-box" role="group" aria-label="Preview limitations" data-preview-limitations="true">
                  <strong>{tech.public_name} is a preview technology.</strong>
                  <ul>{tech.limitations.map((l) => <li key={l}>{plain(l)}</li>)}</ul>
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
                  {options.bounds.capacity_min_mw}–{options.bounds.capacity_max_mw.toLocaleString("en-US")} MW · starting size: {tech.default_capacity_mw} MW. CAPEX and OPEX scale with the capacity you enter.
                </span>
                {capacityError && <span id="rcm-capacity-err" className="rx-status rx-status-error" role="alert">{capacityError}</span>}
              </div>
            </form>
          )}

          {step === 3 && tech && effective && preview && (
            <div data-wizard-panel="review">
              <p className="rx-note">Review the starting assumptions the server will save. Create makes one new project in your account and does not run the model.{template ? " The template itself is not changed." : ""}</p>
              <table className="rcm-review" aria-label="Effective assumptions">
                <tbody>
                  <tr><th scope="row">Project</th><td data-review="name">{preview.normalised.name}</td></tr>
                  <tr><th scope="row">Technology</th><td data-review="technology">{tech.public_name} <TierBadge tier={tech.pilot_tier} /></td></tr>
                  <tr><th scope="row">Country / market</th><td data-review="country">{effective.country_label}</td></tr>
                  <tr><th scope="row">{effective.capacity_label}</th><td data-review="capacity">{effective.capacity_mw.toLocaleString("en-US")} MW <span className="rx-note">(starting size {effective.reference_capacity_mw} MW · scaled ×{effective.scale_ratio.toFixed(3)})</span></td></tr>
                  <tr><th scope="row">Total CAPEX (scaled)</th><td data-review="capex">{effective.total_capex_display} kEUR</td></tr>
                  <tr><th scope="row">OPEX, year 1 (scaled)</th><td data-review="opex">{effective.opex_y1_display} kEUR</td></tr>
                  <tr><th scope="row">Construction / COD / horizon</th><td data-review="timeline">{effective.timeline.construction_months} months · COD {effective.timeline.cod_date} · {effective.timeline.horizon_years} years</td></tr>
                  <tr><th scope="row">Tax template</th><td data-review="tax">{effective.tax_template}</td></tr>
                  {template && template.starting_assumptions.length > 0 && (
                    <tr><th scope="row">Template starting assumptions</th><td data-review="template-assumptions">{template.starting_assumptions.map((a) => `${a.label}: ${a.value}${a.unit ? ` ${a.unit}` : ""}`).join(" · ")}</td></tr>
                  )}
                  {!template && <tr><th scope="row">Starting assumptions</th><td data-review="starter">FINCO's approved starting assumptions for {tech.public_name}; every value is editable after creation.</td></tr>}
                  <tr><th scope="row">Initial status</th><td data-review="status"><span className="rx-lib-badge">NOT RUN YET</span> Your project · editable · saved to your account</td></tr>
                </tbody>
              </table>
            </div>
          )}

          {stepError && <p className="rx-status rx-status-error" role="alert" data-wizard-error="true">{stepError}</p>}
          {unknown && (
            <div className="rx-status rx-status-conflict" role="alert" data-create-unknown="true">
              <p>{unknown}</p>
              <p><a className="rx-button" href={LIBRARY_URL} data-refresh-library="true">Go to My Projects</a></p>
            </div>
          )}
          {created && <p className="rx-status rx-status-saved" role="status" data-create-success="true">Your project was created without running the model. Opening <a href={created.workspace_url}>{created.name}</a> — review your inputs, then choose Run model.</p>}

          <div className="rcm-actions">
            <button type="button" className="rx-button rx-button-secondary" data-wizard-back="true"
                    disabled={step === 1 || locked || busy === "validating"} onClick={() => { setStepError(""); setStep((s) => (s > 1 ? ((s - 1) as 1 | 2 | 3) : s)); }}>Back</button>
            <button type="button" className="rx-button rx-button-secondary" data-wizard-cancel="true" disabled={locked} onClick={onCancel}>Cancel</button>
            {step === 1 && <button type="button" className="rx-button" data-wizard-next="true" disabled={!tech || path === ""} onClick={nextFromTechnology}>Next</button>}
            {step === 2 && <button type="button" className="rx-button" data-wizard-next="true" disabled={busy === "validating"} onClick={() => void nextFromDetails()}>{busy === "validating" ? "Checking…" : "Next"}</button>}
            {step === 3 && <button type="button" className="rx-button" data-wizard-create="true" disabled={locked || !preview} aria-busy={busy === "creating"} onClick={() => void create()}>{busy === "creating" ? "Creating…" : "Create project"}</button>}
          </div>
        </section>
      </main>
    </Shell>
  );
}

type SetupField = { field_id: string; label: string; unit: string | null; required: boolean };
type SetupDraft = { draft_id: string; technology: string; name: string; country: string; fields: Record<string, string>;
  draft_version: number; state: string; readiness: { message: string; can_promote: boolean;
    missing: Array<{ field_id: string; label: string }>; invalid: Array<{ field_id: string; message: string }> } };

/** Separate persisted setup, never a seeded/partial canonical model. */
function BlankSetupWizard({ onCancel }: { onCancel: () => void }) {
  const [step, setStep] = useState<1 | 2 | 3>(1);
  const [technology, setTechnology] = useState("");
  const [name, setName] = useState("");
  const [country, setCountry] = useState("");
  const [fields, setFields] = useState<Record<string, string>>({});
  const [catalogue, setCatalogue] = useState<SetupField[]>([]);
  const [countries, setCountries] = useState<Array<{ code: string; label: string }>>([]);
  const [draft, setDraft] = useState<SetupDraft | null>(null);
  const [drafts, setDrafts] = useState<SetupDraft[]>([]);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [unknown, setUnknown] = useState<{ draftId: string | null; key: string } | null>(null);
  const [scope, setScope] = useState("");
  const [createToken, setCreateToken] = useState("");
  const [updateToken, setUpdateToken] = useState("");
  const baseline = useRef("");
  const heading = useRef<HTMLHeadingElement>(null);
  const retainedUrl = useRef(window.location.href);
  const allowLeave = useRef(false);
  const root = "/v2/model-react/setup-drafts";
  const raw = JSON.stringify({ technology, name, country, fields });
  const dirty = raw !== baseline.current && (!!name || !!country || Object.keys(fields).length > 0);

  const adopt = useCallback((next: SetupDraft) => {
    setDraft(next); setTechnology(next.technology); setName(next.name); setCountry(next.country); setFields(next.fields);
    baseline.current = JSON.stringify({ technology: next.technology, name: next.name, country: next.country, fields: next.fields });
  }, []);
  const open = useCallback(async (id: string) => {
    const response = await fetch(`${root}/${encodeURIComponent(id)}`, { credentials: "same-origin", cache: "no-store" });
    const data = await response.json() as { ok: boolean; draft?: SetupDraft; tokens?: { update: string } };
    if (response.ok && data.ok && data.draft) { adopt(data.draft); setUpdateToken(data.tokens?.update || ""); setStep(2); }
    else setMessage("This setup draft could not be read. Nothing was changed.");
  }, [adopt]);
  useEffect(() => {
    let live = true;
    void fetch(`${root}?technology=${encodeURIComponent(technology || "solar")}`, { credentials: "same-origin", cache: "no-store" })
      .then((r) => r.json()).then((data: { ok: boolean; fields: SetupField[]; drafts: SetupDraft[]; scope: string; csrf_token: string; countries: Array<{ code: string; label: string }> }) => {
        if (!live || !data.ok) return;
        setCatalogue(data.fields); setDrafts(data.drafts); setCreateToken(data.csrf_token); setScope(data.scope);
        setCountries(data.countries);
        const stored = pendingRequest<{ draftId: string | null; key: string }>(`finco-wf03-setup:${data.scope}`);
        if (stored) setUnknown(stored);
      }).catch(() => { if (live) setMessage("Setup drafts could not be loaded. Try again before saving."); });
    return () => { live = false; };
  }, [technology]);
  useEffect(() => { heading.current?.focus(); }, [step]);
  useLayoutEffect(() => {
    const before = (event: BeforeUnloadEvent) => { if (dirty || unknown) { event.preventDefault(); event.returnValue = ""; } };
    const changed = (event: Event) => {
      const next = window.location.href;
      if (next === retainedUrl.current) return;
      if (allowLeave.current) { retainedUrl.current = next; return; }
      if ((dirty || unknown) && !window.confirm("Leave this setup? Unsaved edits will be lost; a pending save must still be reconciled.")) {
        event.stopImmediatePropagation();
        window.history.replaceState(window.history.state, "", retainedUrl.current);
        // The shell also tracks hashes; restore its queued route before React
        // commits the navigation, so a refused Back cannot discard this form.
        window.dispatchEvent(new HashChangeEvent("hashchange"));
      } else retainedUrl.current = next;
    };
    window.addEventListener("beforeunload", before);
    // Capture before the shell's route listeners can unmount this dirty form.
    window.addEventListener("hashchange", changed, true);
    window.addEventListener("popstate", changed, true);
    return () => { window.removeEventListener("beforeunload", before); window.removeEventListener("hashchange", changed, true); window.removeEventListener("popstate", changed, true); };
  }, [dirty, unknown]);

  const settle = async (saved: SetupDraft) => {
    releasePendingRequest(`finco-wf03-setup:${scope}`); setUnknown(null); adopt(saved);
    await open(saved.draft_id); setStep(3); setMessage("Setup draft saved. No runnable project was created and the model was not run.");
  };
  const reconcile = async (attempt: { draftId: string | null; key: string }) => {
    const url = attempt.draftId ? `${root}/${attempt.draftId}/status` : `${root}/status`;
    const response = await fetch(`${url}?request_id=${attempt.key}`, { credentials: "same-origin", cache: "no-store" });
    const data = await response.json() as { ok: boolean; outcome?: string; draft?: SetupDraft };
    if (response.ok && data.ok && data.outcome === "COMMITTED" && data.draft) await settle(data.draft);
    else setMessage("The save result is still unknown. Keep this request and check its status again; do not create a replacement draft.");
  };
  const save = async () => {
    if (busy || !scope) return;
    setBusy(true);
    try {
      if (unknown) { await reconcile(unknown); return; }
      const attempt = { draftId: draft?.draft_id || null, key: crypto.randomUUID().replace(/-/g, "") };
      retainPendingRequest(`finco-wf03-setup:${scope}`, attempt);
      setUnknown(attempt);
      const response = await fetch(draft ? `${root}/${draft.draft_id}` : root, { method: draft ? "PATCH" : "POST",
        credentials: "same-origin", headers: { "Content-Type": "application/json", "X-CSRF-Token": draft ? updateToken : createToken },
        body: JSON.stringify({ request_id: attempt.key, technology, name, country, fields, ...(draft ? { draft_version: draft.draft_version } : {}) }) });
      const result = await response.json().catch(() => null) as { ok: boolean; draft?: SetupDraft; code?: string } | null;
      if (response.ok && result?.ok && result.draft) await settle(result.draft);
      else if (response.status >= 400 && response.status < 500) {
        releasePendingRequest(`finco-wf03-setup:${scope}`); setUnknown(null);
        setMessage("The draft was not saved. Check the entered values, session and saved version before trying again.");
      } else await reconcile(attempt);
    } catch { setMessage("The save could not be confirmed. Check the status of the same request before saving again."); }
    finally { setBusy(false); }
  };
  const cancel = () => { if ((!dirty && !unknown) || window.confirm("Leave this setup? Unsaved edits will be lost; any pending save still needs reconciliation.")) {
    allowLeave.current = true; onCancel();
  } };
  return <Shell crumb="Blank setup draft" dataOrigin="canonical-run" originLabel="SETUP ONLY">
    <main className="rx-page rcm-wizard" role="main" data-setup-draft="true" data-setup-dirty={dirty ? "true" : "false"}>
      <h1>Blank setup draft</h1><p>Explicit inputs only. This setup is saved separately and cannot Run, create scenarios or use Save All.</p>
      <ol className="rcm-steps">{STEPS.map((s) => <li key={s.id} className={s.id === step ? "active" : ""}>{s.id}. {s.id === 3 ? "Review & save setup" : s.label}</li>)}</ol>
      <section className="rx-card"><h2 ref={heading} tabIndex={-1}>{step === 1 ? "1. Start" : step === 2 ? "2. Project details" : "3. Review & save setup"}</h2>
        {message && <p role="status">{message}</p>}
        {step === 1 && <><label>Technology <select aria-label="Technology" value={technology} disabled={busy || !!unknown || !!draft} onChange={(e) => { setTechnology(e.target.value); setFields({}); }}>
          <option value="">Choose a technology</option><option value="solar">Solar PV</option><option value="wind">Onshore Wind</option>
          <option value="data_center">Data Center</option><option value="ev_charging">EV Charging</option></select></label>
          <p>Storage is not released.</p>{drafts.length > 0 && <details><summary>Resume a saved setup draft</summary>{drafts.map((d) => <p key={d.draft_id}>
            <button type="button" className="rx-button rx-button-secondary" disabled={busy || !!unknown} onClick={() => void open(d.draft_id)}>{d.name || "Unnamed setup"} · {d.technology}</button></p>)}</details>}</>}
        {step === 2 && <fieldset disabled={busy || !!unknown}><legend>Your explicit inputs</legend>
          <label>Setup name <input id="setup-project_setup.identity.project_name" value={name} maxLength={80} onChange={(e) => setName(e.target.value)} /></label>
          <label>Country / market <select aria-label="Country / market" id="setup-project_setup.identity.country_market" value={country} onChange={(e) => setCountry(e.target.value)}>
            <option value="">Choose a country / market</option>{countries.map((c) => <option key={c.code} value={c.code}>{c.label}</option>)}</select></label>
          {catalogue.map((f) => <p key={f.field_id}><label htmlFor={`setup-${f.field_id}`}>{f.label}{f.unit ? ` (${f.unit})` : ""}
            <input id={`setup-${f.field_id}`} value={fields[f.field_id] ?? ""} onChange={(e) => setFields((old) => ({ ...old, [f.field_id]: e.target.value }))} /></label></p>)}
        </fieldset>}
        {step === 3 && <><p>{name || "Unnamed setup"} · {technology} · {country || "Country not entered"}</p>
          <p>{Object.values(fields).filter((v) => v.trim() !== "").length} explicitly entered fields. Missing values are not replaced with defaults.</p>
          <p role="note">{draft?.readiness.message || "Promotion to a runnable model remains unavailable until every consumed input can be validated without starting assumptions."}</p>
          {!!draft?.readiness.missing.length && <details open><summary>Missing inputs</summary><ul>{draft.readiness.missing.map((f) => <li key={f.field_id}>
            <button type="button" onClick={() => { setStep(2); requestAnimationFrame(() => document.getElementById(`setup-${f.field_id}`)?.focus()); }}>{f.label} · {f.field_id}</button></li>)}</ul></details>}
          {!!draft?.readiness.invalid.length && <div role="alert"><h3>Review invalid inputs</h3><ul>{draft.readiness.invalid.map((f) => <li key={f.field_id}>
            <button type="button" onClick={() => { setStep(2); requestAnimationFrame(() => document.getElementById(`setup-${f.field_id}`)?.focus()); }}>{f.field_id}: {f.message}</button></li>)}</ul></div>}
          <button type="button" className="rx-button" disabled>Create runnable project — unavailable</button></>}
        <div className="rcm-actions"><button type="button" className="rx-button rx-button-secondary" disabled={busy} onClick={cancel}>My Projects</button>
          <button type="button" className="rx-button rx-button-secondary" disabled={step === 1 || busy || !!unknown} onClick={() => setStep((s) => (s - 1) as 1 | 2)}>Back</button>
          {step < 3 && <button type="button" className="rx-button" disabled={!technology || busy || !!unknown} onClick={() => setStep((s) => (s + 1) as 2 | 3)}>Next</button>}
          {(step === 3 || unknown) && <button type="button" className="rx-button" disabled={busy || !scope} onClick={() => void save()}>{busy ? "Checking…" : unknown ? "Reconcile saved request" : "Save setup draft"}</button>}
        </div>
      </section>
    </main>
  </Shell>;
}

export function NewProjectWizard({ onCancel }: { onCancel: () => void }) {
  // Reuse the existing shell's released #new-project route. A distinct query
  // choice survives reload/deep links without changing App's route authority.
  const selected = () => new URLSearchParams(window.location.search).get("setup") === "blank";
  const [blank, setBlank] = useState(selected);
  useEffect(() => {
    // The draft's navigation guard restores a refused URL during this event.
    // Read it after all listeners, rather than unmounting the child first.
    let pending: number | undefined;
    const changed = () => { window.clearTimeout(pending); pending = window.setTimeout(() => setBlank(selected()), 0); };
    window.addEventListener("hashchange", changed);
    window.addEventListener("popstate", changed);
    return () => { window.clearTimeout(pending); window.removeEventListener("hashchange", changed); window.removeEventListener("popstate", changed); };
  }, []);
  const exitBlank = () => {
    const url = new URL(window.location.href); url.searchParams.delete("setup");
    window.history.replaceState(window.history.state, "", url); onCancel();
  };
  return blank ? <BlankSetupWizard onCancel={exitBlank} /> : <SeededNewProjectWizard onCancel={onCancel} />;
}
