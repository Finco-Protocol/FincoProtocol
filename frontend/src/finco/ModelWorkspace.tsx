import React, { useCallback, useEffect, useRef, useState } from "react";
import "./_group.css";
import { DemoBanner, DemoContextStrip, Field, fincoBasePath, ModelNav, navigateFinco, Panel, projectWorkspaceHref, readProjectContext, Shell, Status } from "./_shared/FincoShell";

import { assumptionLabels, initialAssumptions, InputKey, validateAssumptions } from "./_shared/validation";
import InputGrid from "./_workbook/InputGrid";
import WorkbookNavigation from "./_workbook/WorkbookNavigation";
import ModuleSurface from "./_workbook/ModuleSurface";
import CostLinePlanner from "./_workbook/CostLinePlanner";
import { initialLineValues, LineSheet, lineErrors } from "./_workbook/periodGrid";
import { useDemoSessionState } from "./_shared/demoSession";
import { createDemoWorkingCopy, isDemoWorkingCopyId } from "./_shared/demoWorkingCopies";
import { gridErrors, scalarKeys } from "./_workbook/gridPaste";
import "./_workbook/workbook.css";
const legacySheets = ["inputs"];
const fragmentSheet: Record<string, string> = { inputs: "inputs", revenue: "inputs", costs: "inputs", financing: "inputs", checks: "inputs", trust: "inputs", scenarios: "scenarios" };
function readSheet() {
  return fragmentSheet[window.location.hash.slice(1)] || new URLSearchParams(window.location.search).get("sheet") || "input-grid";
}
function traceReturnUrl(source: URLSearchParams) {
  if (!source.get("returnStatement")) return null;
  const params = new URLSearchParams(source);
  const statement = params.get("returnStatement") || "pl";
  params.delete("sheet");
  params.delete("returnStatement");
  params.delete("returnView");
  params.delete("returnRow");
  params.set("statement", statement);
  params.set("statementView", source.get("returnView") || "annual");
  params.set("traceRow", source.get("returnRow") || "");
  params.set("returnTrace", "1");
  return `${fincoBasePath()}ResultsAnalysis?${params.toString()}#statement-workbook`;
}
const sectionTabs = [
  ["Project & timing", "inputs"],
  ["Revenue / PPA", "revenue"],
  ["Costs & tax", "costs"],
  ["Financing", "financing"],
  ["Credit assumptions", "checks"],
];

export function ModelWorkspace() {
  const project = readProjectContext();
  const invalidCopy = project.mode === "working-copy" && isDemoWorkingCopyId(project.id) && !project.registeredWorkingCopy;
  const referenceMode = project.mode === "reference" || invalidCopy;
  const incomingParams = new URLSearchParams(window.location.search);
  const traceReturnHref = traceReturnUrl(incomingParams);
  const [values, setValues] = useDemoSessionState("scalar-draft", initialAssumptions);
  const [committed, setCommitted] = useDemoSessionState("scalar-saved", initialAssumptions);
  const [sheet, setSheet] = useState(readSheet);
  const [cellEditing, setCellEditing] = useState(false);
  const [periodPending, setPeriodPending] = useState(false);
  const [lineValues, setLineValues] = useDemoSessionState("cost-line-draft", initialLineValues);
  const [lineCommitted, setLineCommitted] = useDemoSessionState("cost-line-saved", initialLineValues);
  const [lineSaveAck, setLineSaveAck] = useDemoSessionState<Record<"capex" | "opex", boolean>>("cost-line-save-ack", { capex: false, opex: false });
  const [frequency, setFrequency] = useState(incomingParams.get("operationPeriod") === "6M" ? "6M" : "3M");
  const [ppa, setPpa] = useState(["Fixed", "Indexed", "Scheduled"].includes(incomingParams.get("ppaMode") || "") ? incomingParams.get("ppaMode") || "Fixed" : "Fixed");
  const [tranche, setTranche] = useState(incomingParams.get("tranche") || "Senior debt");
  const [section, setSection] = useState(window.location.hash.slice(1) || "inputs");
  const [saved, setSaved] = useDemoSessionState("scalar-save-acknowledged", false);
  const [moduleSaveAck, setModuleSaveAck] = useDemoSessionState("module-save-acknowledged", false);
  const [message, setMessage] = useState("");
  const [moduleDraftsDirty, setModuleDraftsDirty] = useState<Record<string, boolean>>({});
  const moduleDraftsDirtyRef = useRef<Record<string, boolean>>({});
  const [, setContextRevision] = useState(0);
  const markModuleDraft = useCallback((id: string, dirty: boolean) => {
    const wasDirty = moduleDraftsDirtyRef.current[id] === true;
    moduleDraftsDirtyRef.current[id] = dirty;
    if (dirty) setModuleSaveAck(false);
    else if (wasDirty) setModuleSaveAck(true);
    setModuleDraftsDirty(current => current[id] === dirty ? current : { ...current, [id]: dirty });
  }, []);
  const moduleDraftDirty = Object.values(moduleDraftsDirty).some(Boolean);
  const jumpUntil = useRef(0);
  const syncedHash = useRef(window.location.hash);
  const formValidation = validateAssumptions(values, ppa);
  // The scalar Save boundary contains every authorized grid field, including
  // inactive PPA examples. Changing sheets must not bypass batch validation.
  const errors = gridErrors(values);
  const warnings = formValidation.warnings;
  const legacyView = legacySheets.includes(sheet);
  const scalarDirty = JSON.stringify(values) !== JSON.stringify(committed);
  const costDirty = JSON.stringify(lineValues) !== JSON.stringify(lineCommitted);
  const anyDemoSaveAck = saved || moduleSaveAck || Object.values(lineSaveAck).some(Boolean);
  const runBlocked = scalarDirty || costDirty || moduleDraftDirty || cellEditing || periodPending || Object.keys(errors).length > 0;
  const errorKeys = Object.keys(errors) as InputKey[];
  const warningCount = Object.keys(warnings).length;
  const blocked = errorKeys.length > 0;
  const activeNav = sheet === "scenarios" || section === "scenarios" ? "Scenarios" : section === "financing" ? "Financing" : section === "checks" ? "Model checks" : section === "trust" ? "Trust" : "Inputs";
  function updateContextParam(key: string, value: string) {
    const params = new URLSearchParams(window.location.search);
    params.set(key, value);
    window.history.replaceState(null, "", `${window.location.pathname}?${params.toString()}${window.location.hash}`);
    setContextRevision(revision => revision + 1);
  }
  function focusSection(id: string) {
    const target = document.getElementById(id);
    jumpUntil.current = performance.now() + 250;
    target?.focus({ preventScroll: true });
    if (target) {
      const navHeight = document.querySelector(".fm-workspace-nav")?.getBoundingClientRect().height || 0;
      window.scrollTo({ top: window.scrollY + target.getBoundingClientRect().top - navHeight - 16 });
    }
  }
  useEffect(() => {
    const syncSection = () => {
      const id = window.location.hash.slice(1) || "inputs";
      if (id === "scenarios") {
        const params = new URLSearchParams(window.location.search);
        params.set("sheet", "scenarios");
        window.history.replaceState(null, "", `${window.location.pathname}?${params}#workbook`);
        setSheet("scenarios");
        setSection("scenarios");
        syncedHash.current = "#workbook";
        jumpUntil.current = performance.now() + 250;
        requestAnimationFrame(() => focusSection("workbook"));
        return;
      }
      setSheet(readSheet());
      syncedHash.current = window.location.hash;
      jumpUntil.current = performance.now() + 250;
      setSection(id);
      if (window.location.hash) requestAnimationFrame(() => focusSection(id));
    };
    syncSection();
    window.addEventListener("hashchange", syncSection);
    window.addEventListener("popstate", syncSection);
    return () => { window.removeEventListener("hashchange", syncSection); window.removeEventListener("popstate", syncSection); };
  }, []);
  useEffect(() => {
    if (!legacyView) return;
    let frame = 0;
    const update = () => {
      frame = 0;
      // Native fragment scrolling can arrive before hashchange. Never let scrollspy
      // replace a pending click/back/forward destination before it receives focus.
      if (performance.now() < jumpUntil.current || window.location.hash !== syncedHash.current) return;
      const threshold = (document.querySelector(".fm-workspace-nav")?.getBoundingClientRect().height || 0) + 24;
      const sections = ["inputs", "revenue", "costs", "financing", "checks", "trust"]
        .map(id => ({ id, top: document.getElementById(id)?.getBoundingClientRect().top ?? Infinity }));
      const atBottom = Math.ceil(window.scrollY + window.innerHeight) >= document.documentElement.scrollHeight - 3;
      const candidates = (atBottom ? sections : sections.filter(item => item.top <= threshold)).sort((a, b) => b.top - a.top);
      const id = candidates[0]?.id || "inputs";
      setSection(id);
      // Replace only: manual scrolling must not add browser-history entries or move focus.
      syncedHash.current = `#${id}`;
      if (window.location.hash !== syncedHash.current) window.history.replaceState(null, "", syncedHash.current);
    };
    const onScroll = () => { if (!frame) frame = requestAnimationFrame(update); };
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => { window.removeEventListener("scroll", onScroll); cancelAnimationFrame(frame); };
  }, [legacyView]);
  function jumpTo(id: string) {
    jumpUntil.current = performance.now() + 250;
    if (id === "scenarios") {
      const params = new URLSearchParams(window.location.search);
      params.set("sheet", "scenarios");
      window.history.pushState(null, "", `${window.location.pathname}?${params}#workbook`);
      setSheet("scenarios");
      setCellEditing(false);
      setSection("scenarios");
      syncedHash.current = "#workbook";
      requestAnimationFrame(() => focusSection("workbook"));
      return;
    }
    setSheet("inputs");
    setCellEditing(false);
    const params = new URLSearchParams(window.location.search);
    params.set("sheet", "inputs");
    window.history.replaceState(null, "", `${window.location.pathname}?${params}${window.location.hash}`);
    setSection(id);
    if (window.location.hash === `#${id}`) requestAnimationFrame(() => focusSection(id));
    else window.location.hash = id;
  }
  function chooseSheet(id: string) {
    setSheet(id); setCellEditing(false);
    if (id === "investor") setTranche("Equity");
    if (id === "senior-debt") setTranche("Senior debt");
    const params = new URLSearchParams(window.location.search);
    params.set("sheet", id);
    params.delete("statement");
    window.history.pushState(null, "", `${window.location.pathname}?${params}#workbook`);
    syncedHash.current = "#workbook";
    setSection("workbook");
    requestAnimationFrame(() => focusSection("workbook"));
  }
  function change(key: InputKey, value: string) {
    if (referenceMode) {
      setMessage("Reference models are read-only. Create a local demo working copy before editing.");
      return;
    }
    setValues((v) => ({ ...v, [key]: value }));
    setSaved(false);
    setMessage("");
  }
  function save() {
    if (referenceMode) {
      setMessage("Reference models are read-only. No Save was performed; create a local demo working copy to edit.");
      return;
    }
    if (!allowAction()) return;
    setCommitted({ ...values });
    setSaved(true);
    setMessage("Scalar batch acknowledged in this browser-tab session only; no backend write or Run was triggered. CAPEX/OPEX line saves are separate.");
  }
  function allowAction() {
    if (referenceMode) {
      setMessage("Reference models are read-only. No Save or Run is available; create a local demo working copy.");
      return false;
    }
    if (cellEditing) { setMessage("Finish the active cell with Enter/Tab or cancel with Esc before Save or Run."); return false; }
    if (!blocked) return true;
    setSaved(false);
    setMessage("");
    document.getElementById("validation-summary")?.focus();
    document.getElementById("validation-summary")?.scrollIntoView({ block: "center" });
    return false;
  }
  function run() {
    if (!allowAction()) return;
    if (periodPending) { setMessage("Resolve the rejected CAPEX/OPEX paste before Run demo. The rejected range was not applied."); return; }
    if (scalarDirty || costDirty) { setMessage("Save the staged scalar batch and each dirty CAPEX/OPEX line batch before Run demo. Saving never runs a model."); return; }
    if (moduleDraftDirty) { setMessage("Save each dirty Revenue, Finance, Tax/Timing or Scenario draft in its own sheet before opening the fixed demo results. This does not run calculations."); return; }
    const target = new URL(`${fincoBasePath()}ResultsAnalysis${window.location.search}#results`, window.location.origin);
    target.searchParams.set("demoRun", "DEMO-FIXED-018");
    target.searchParams.set("freshness", "CURRENT_DEMO_SNAPSHOT");
    navigateFinco(`${target.pathname}${target.search}${target.hash}`);
  }
  function createWorkingCopyFromReference() {
    try {
      const copy = createDemoWorkingCopy({
        ...project,
        sponsor: "Synthetic reference sponsor",
      });
      navigateFinco(projectWorkspaceHref(copy, {
        mode: "working-copy",
        parentReferenceId: project.id,
      }));
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Could not create a local demo working copy in this browser tab.");
    }
  }
  function field(key: InputKey, label: string, unit?: string, hint?: string, type = "text") {
    return <Field id={`fm-${key}`} label={label} value={values[key]} unit={unit} type={type} hint={hint}
      error={errors[key]} warning={warnings[key]} onChange={v => change(key, v)} />;
  }
  function revealError(key: InputKey) {
    if (!legacyView) {
      setSheet("input-grid");
      requestAnimationFrame(() => document.getElementById(`wb-cell-${scalarKeys.indexOf(key)}-0`)?.focus());
      return;
    }
    if (["debt", "interest", "tenor"].includes(key)) setTranche("Senior debt");
    if (["mezzDebt", "mezzCoupon", "mezzPik"].includes(key)) setTranche("Mezzanine");
    if (["equity", "ownership"].includes(key)) setTranche("Equity");
    if (key === "indexation") setPpa("Indexed");
    if (key === "scheduledStep") setPpa("Scheduled");
    requestAnimationFrame(() => {
      const target = document.getElementById(`fm-${key}`);
      const parent = target?.closest(".fm-section");
      if (parent) { setSection(parent.id); syncedHash.current = `#${parent.id}`; window.history.replaceState(null, "", syncedHash.current); focusSection(parent.id); }
      target?.focus({ preventScroll: true });
    });
  }
  return <Shell crumb={`${project.name} · ${project.technology} · Model workspace`}>
    <main className="fm-shell">
      <DemoBanner copy={referenceMode
        ? invalidCopy
          ? "This local demo copy is unavailable in the current browser-tab session. Return to Project Library and create a new working copy; no reference or server data can be edited."
          : "Reference sample · inspection only. Inputs, inline editors, Save and Run are disabled. Create a local working copy to experiment; all values and outputs remain synthetic."
        : "Project drafts are isolated by demo project identity in this browser tab. Fixed Results remain shared synthetic examples and never recalculate from edits."} />
      <DemoContextStrip workingState={scalarDirty || costDirty || moduleDraftDirty ? "UNSAVED" : anyDemoSaveAck ? "DEMO SAVED" : "WORKING COPY · NOT SAVED"} />
      {referenceMode && <div id="reference-mode-help" className="fm-reference-banner" role="status">
        <div><strong>{invalidCopy ? "Demo working copy unavailable" : "REFERENCE · READ ONLY"}</strong>
          <span>{invalidCopy ? "This browser-tab session no longer contains that demo copy. Reference samples were not changed." : `${project.name} is an inspect-only synthetic reference. No edits, Save, or Run are allowed.`}</span></div>
        {invalidCopy
          ? <a className="fm-btn" href={`${fincoBasePath()}ProjectLibrary`}>Return to Project Library</a>
          : <button type="button" className="fm-btn fm-btn-primary" onClick={createWorkingCopyFromReference}>Create working copy</button>}
      </div>}
      {/bess|storage/i.test(project.technology) && <div className="fm-warning-summary" role="note">
        <strong>Storage / BESS preview-only gate.</strong> Project context is visible for design review; dispatch, degradation, storage revenue allocation and technology-specific calculations are unavailable.
      </div>}
      {traceReturnHref && <div className="fm-info-note fm-trace-return" role="note">
        <div><strong>Source trace opened this workbook section.</strong> The link is navigational only; no numerical input dependency is asserted.</div>
        <a href={traceReturnHref} onClick={event => {
          if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
          event.preventDefault();
          const liveHref = traceReturnUrl(new URLSearchParams(window.location.search));
          if (liveHref) navigateFinco(liveHref);
        }}>Return to the selected statement trace →</a>
      </div>}
      <div className="fm-shell-header">
        <div>
          <div className="fm-eyebrow">{project.id} · Model workspace</div>
          <a className="fm-small-link" href={`${fincoBasePath()}ProjectLibrary`}>← Project Library</a>
          <h1 className="fm-title">{project.name} <span style={{ fontSize: 13, color: "var(--muted)", fontWeight: 500 }}>· {project.size}</span></h1>
          <div className="fm-subtitle">{project.region} <span style={{ margin: "0 7px" }}>·</span> {project.technology} <span style={{ margin: "0 7px" }}>·</span> Shared demo assumptions v1.4</div>
        </div>
        <div className="fm-toolbar">
          <span className="fm-split-label">{referenceMode ? "REFERENCE · READ ONLY" : scalarDirty || costDirty ? "UNSAVED · staged demo" : saved ? "Acknowledged · browser session only" : "Demo draft · browser session only"}</span>
          <button className="fm-btn" onClick={save} disabled={referenceMode} aria-disabled={referenceMode || blocked || cellEditing} aria-describedby={referenceMode ? "reference-mode-help" : blocked ? "validation-summary" : undefined} type="button">{referenceMode ? "Save disabled · Reference" : saved ? "Demo acknowledged ✓" : "Save demo"}</button>
          <button className="fm-btn fm-btn-primary" onClick={run} disabled={referenceMode} aria-disabled={referenceMode || runBlocked} aria-describedby={referenceMode ? "reference-mode-help" : blocked ? "validation-summary" : undefined} type="button">{referenceMode ? "Run disabled · Reference" : <>Run demo <span style={{ marginLeft: 5, fontSize: 9, opacity: .75 }}>FIXED RESULTS</span></>}</button>
        </div>
      </div>
      <div className="fm-workspace-nav">
      <ModelNav active={activeNav} onSectionNavigate={jumpTo} />
      {legacyView &&
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 10, marginBottom: 12 }}>
        <div className="fm-tab-row" aria-label="Input sections" style={{ padding: 0 }}>
          {sectionTabs.map(([label, id]) =>
            <button type="button" key={id} className={`fm-tab${section === id ? " fm-tab-active" : ""}`} aria-pressed={section === id} aria-controls={id} onClick={() => jumpTo(id)}>{label}</button>
          )}
        </div>
        <div className="fm-legend"><span><i />Editable assumption</span><span><i className="calc" />Fixed / read-only demo</span></div>
      </div>
      }
      </div>
      {blocked && <section id="validation-summary" tabIndex={-1} role="alert" aria-labelledby="validation-title" className="fm-validation-summary">
        <strong id="validation-title">{errorKeys.length} blocking input {errorKeys.length === 1 ? "error" : "errors"} · Demo Save and Run unavailable</strong>
        <div>Correct the fields below. Validation checks input ranges and dates only; it does not calculate financial results.</div>
        <ul>{errorKeys.map(key => <li key={key}><button type="button" className="fm-small-link" onClick={() => revealError(key)}>{assumptionLabels[key]}: {errors[key]}</button></li>)}</ul>
      </section>}
      {warningCount > 0 && <div className="fm-warning-summary" role="status">{warningCount} review {warningCount === 1 ? "warning" : "warnings"} · Nonblocking input guidance only. No credit analysis has been run.</div>}
      {message && <div className="fm-info-note" role="status" style={{ marginBottom: 10 }}>{message}</div>}
      <div className="fm-wb-status"><span>Run UI: <strong>{scalarDirty || costDirty || moduleDraftDirty ? "STALE DEMO REFERENCE" : "NOT RUN"}</strong></span><span>Integrity: <strong>NOT EVALUATED</strong></span><span>Engine/version: <strong>NOT CONNECTED</strong></span><span>Fixed reference: <strong>DEMO-FIXED-018</strong></span>{moduleDraftDirty && <span>Module drafts: <strong>UNSAVED · local sheet Save required</strong></span>}</div>
      <div className="fm-wb-frequency"><span>Construction: <strong>monthly</strong></span><label>Operation display: <select aria-label="Workbook operation period display" value={frequency} onChange={event => {
        const value = event.target.value;
        setFrequency(value);
        updateContextParam("operationPeriod", value);
      }}><option value="3M">Quarterly (3M)</option><option value="6M">Semiannual (6M)</option></select></label><span>VIEW-ONLY sample periods · no aggregation or math · policy activation unverified</span></div>
      <div id="workbook" tabIndex={-1} className="fm-wb-layout">
      <WorkbookNavigation active={sheet} onSelect={chooseSheet} />
      <fieldset className="fm-reference-fieldset" disabled={referenceMode} aria-describedby={referenceMode ? "reference-mode-help" : undefined}>
      <legend className="fm-sr-only">{referenceMode ? "Read-only synthetic reference workbook" : "Synthetic working-copy workbook"}</legend>
      <div className="fm-reference-content">
      {sheet === "input-grid" ? <InputGrid values={values} committed={committed} errors={errors} blocked={blocked} dirty={scalarDirty} runBlocked={runBlocked} readOnly={referenceMode} onEditing={setCellEditing}
        onChange={next => { setValues(next); setSaved(false); setMessage(""); }} onSave={save} onRun={run} /> :
        <ModuleSurface sheet={sheet} onOpen={chooseSheet} errors={errorKeys.length} onDraftDirty={markModuleDraft} onContextChange={updateContextParam} />}
      {(sheet === "capex" || sheet === "opex") && <CostLinePlanner key={sheet} sheet={sheet} values={lineValues[sheet]} committed={lineCommitted[sheet]} operationPeriod={frequency} readOnly={referenceMode} onOperationPeriodChange={value => {
        setFrequency(value);
        updateContextParam("operationPeriod", value);
      }} onEditing={setCellEditing} onPendingError={setPeriodPending}
         onChange={next => { setLineValues(v => ({ ...v, [sheet]: next })); setLineSaveAck(v => ({ ...v, [sheet]: false })); setMessage(""); }}
        onSave={() => {
          const key = sheet as LineSheet;
          if (lineErrors(lineValues[key], key)) return;
          setLineCommitted(v => ({ ...v, [key]: lineValues[key].map(row => [...row]) }));
          setLineSaveAck(v => ({ ...v, [key]: true }));
          setMessage(`${key.toUpperCase()} line batch acknowledged atomically in this browser-tab session only. Scalar values and the other line batch are unchanged; no Run triggered.`);
        }} />}
      <div className="fm-main-grid" style={{ display: legacyView ? "grid" : "none" }}>
        <div>
          <div id="inputs" className="fm-section" tabIndex={-1}>
            <Panel title="Project & timeline" meta="Editable inputs">
              <div className="fm-field-grid">
                <Field label="Project name" value={project.name} />
                {field("capacity", "Installed capacity", "MWp", "Shared solar example; not the selected project's specific model.")}
                {field("cod", "Commercial operation", undefined, "Must follow construction start.", "date")}
                {field("term", "Operating life", "years", "Whole years; 1–60.")}
                {field("start", "Construction start", undefined, "Date ordering only; no timeline calculation.", "date")}
                <Field label="Construction period" value="21" unit="months" />
                <Field label="Reporting currency" value="EUR" calculated />
                <Field label="Model period" value="Annual · 2025–2057" calculated />
              </div>
            </Panel>
          </div>
          <div className="fm-section" id="revenue" tabIndex={-1}>
            <Panel title="Revenue & power purchase agreement" meta={`PPA editor · ${values.ppaTenor || "—"} years`}>
              <div className="fm-tab-row">
                {["Fixed", "Indexed", "Scheduled"].map((item) => <button key={item} type="button" aria-pressed={ppa === item} onClick={() => { setPpa(item); updateContextParam("ppaMode", item); setSaved(false); setMessage(""); }} className={`fm-tab${ppa === item ? " fm-tab-active" : ""}`}>{item}</button>)}
                <span className="fm-hint" style={{ marginLeft: "auto", paddingRight: 5 }}>Mode selection is a local demo interaction</span>
              </div>
              <div className="fm-field-grid">
                {field("ppaPrice", ppa === "Fixed" ? "Contract tariff" : ppa === "Indexed" ? "Base tariff" : "Year 1 tariff", "€/MWh", "Nonnegative nominal tariff; no revenue projection.")}
                {field("ppaTenor", "PPA tenor", "years", "Cannot exceed operating life.")}
                {field("contracted", "Contracted generation", "%", "Share of generation contracted; 0–100%.")}
                <Field label="Merchant tail" value="12" unit="years" calculated />
                {ppa === "Indexed" && field("indexation", "Annual indexation", "%", "Applies to base tariff in this illustrative editor only.")}
                {ppa === "Scheduled" && field("scheduledStep", "Step-up from year 6", "%", "One illustrative tariff step; no escalation calculation.")}
                {ppa === "Scheduled" && <Field label="Custom period schedule" value="Not prototyped" unavailable hint="Multi-period schedule import is unavailable in this prototype." />}
                <Field label="Net P50 yield" value="1,620" unit="kWh/kWp" calculated />
                <Field label="Degradation" value="0.45" unit="% p.a." />
              </div>
            </Panel>
          </div>
          <div className="fm-section" id="costs" tabIndex={-1}>
            <Panel title="CAPEX, spending profile, OPEX & tax" meta="EUR nominal · pre-financing">
              <div className="fm-section-heading" style={{ padding: "11px 12px 0" }}><h3>Development and construction</h3><span>Editable assumptions</span></div>
              <div className="fm-field-grid">
                {field("capex", "Total project CAPEX", "€m", "Nonnegative; fixed component breakdown does not reconcile.")}
                <Field label="EPC / equipment" value="82.6" unit="€m" />
                <Field label="Development & grid" value="12.4" unit="€m" />
                <Field label="Contingency" value="9.8" unit="€m" calculated />
              </div>
              <div className="fm-table-wrap"><table className="fm-table"><thead><tr><th>Spending profile</th><th className="right">2025</th><th className="right">2026</th><th className="right">2027</th><th className="right">Total</th></tr></thead><tbody><tr><td>Construction drawdown</td><td className="right fm-mono">18%</td><td className="right fm-mono">62%</td><td className="right fm-mono">20%</td><td className="right fm-mono">100%</td></tr></tbody></table></div>
              <div className="fm-field-grid">
                {field("opex", "Fixed O&M", "€m/yr", "Nonnegative annual assumption.")}
                <Field label="O&M escalation" value="2.00" unit="% p.a." />
                <Field label="Land lease" value="0.18" unit="€m / yr" />
                {field("tax", "Corporate tax", "%")}
              </div>
            </Panel>
          </div>
          <div className="fm-section" id="financing" tabIndex={-1}>
            <Panel title="Capital structure & financing" meta="Selected facility · EUR">
              <div className="fm-tab-row">
                {["Senior debt", "Mezzanine", "Equity"].map((item) => <button key={item} type="button" aria-pressed={tranche === item} onClick={() => { setTranche(item); updateContextParam("tranche", item); setSection("financing"); setSaved(false); setMessage(""); }} className={`fm-tab${tranche === item ? " fm-tab-active" : ""}`}>{item}</button>)}
              </div>
              <div className="fm-field-grid">
                {tranche === "Senior debt" ? <>
                  {field("debt", "Facility commitment", "€m", "Nonnegative commitment; sources and uses remain fixed.")}
                  {field("interest", "Margin over EURIBOR", "% p.a.", "Spread, not all-in interest; demo range 0–30%.")}
                  <Field label="Amortisation" value="Sculpted" />
                  {field("tenor", "Debt tenor", "years", "1–40 whole years, within operating life.")}
                  <Field label="Repayment grace" value="24" unit="months" />
                  <Field label="Arrangement fee" value="1.25" unit="%" />
                  <Field label="Hedge ratio" value="75" unit="%" />
                  <Field label="Debt / total uses" value="63.9" unit="%" calculated />
                </> : tranche === "Mezzanine" ? <>
                  {field("mezzDebt", "Mezzanine commitment", "€m", "Optional illustrative facility; not included in the fixed sources table.")}
                  {field("mezzCoupon", "Cash coupon", "% p.a.", "Cash-pay rate; 0–30%.")}
                  {field("mezzPik", "PIK component", "% p.a.", "Capitalised rate assumption only; no accruals.")}
                  <Field label="Repayment" value="Bullet · year 10" />
                  <Field label="Intercreditor terms" value="Not prototyped" unavailable hint="Waterfall and covenant interaction unavailable." />
                </> : <>
                  <Field label="Sponsor equity" value="37.8" unit="€m" calculated />
                  {field("equity", "Equity commitment", "€m", "Nonnegative sponsor assumption; no balancing calculation.")}
                  <Field label="Reserve funding" value="1.3" unit="€m" calculated />
                  {field("ownership", "Ownership", "%", "0–100%; distribution model is not calculated.")}
                </>}
              </div>
              <div className="fm-info-note">Sources & uses below are a fixed synthetic snapshot. Tranche edits do not reconcile or rebalance this table.</div>
              <div className="fm-table-wrap"><table className="fm-table"><thead><tr><th>Sources & uses</th><th className="right">€m</th><th className="right">%</th><th>Instrument</th></tr></thead><tbody>
                <tr><td>Senior secured debt</td><td className="right fm-mono">67.0</td><td className="right fm-mono">63.9%</td><td>Amortising · sculpted</td></tr>
                <tr><td>Equity contribution</td><td className="right fm-mono">37.8</td><td className="right fm-mono">36.1%</td><td>Ordinary shares</td></tr>
                <tr style={{ background: "#f4f7f8", fontWeight: 700 }}><td>Total project uses</td><td className="right fm-mono">104.8</td><td className="right fm-mono">100.0%</td><td>Fixed example · not reconciled</td></tr>
              </tbody></table></div>
            </Panel>
          </div>
          <div className="fm-section" id="checks" tabIndex={-1}>
            <Panel title="Credit assumptions & model checks" meta="Illustrative lender case">
              <div className="fm-field-grid">
                {field("dscr", "Minimum DSCR covenant", "x", "Positive value required; ≤1.00x raises a review warning.")}
                <Field label="Target DSCR" value="1.28" unit="x" />
                <Field label="EURIBOR curve" value="2.35" unit="% flat" />
                <Field label="P90 yield haircut" value="6.5" unit="%" />
              </div>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 8, padding: "0 12px 12px" }}>
                <Status tone={blocked ? "amber" : "green"}>{blocked ? `${errorKeys.length} input errors` : "Input format checks passed"}</Status><Status tone="gray">No financial checks run</Status><Status tone={warningCount ? "amber" : "gray"}>{warningCount} review warnings</Status>
              </div>
            </Panel>
          </div>
        </div>
        <aside>
          <Panel title="Model control" meta="Local demonstration">
            <div style={{ padding: 12 }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}><span className="fm-split-label">Current revision</span><Status tone="blue">Base case v1.4</Status></div>
              <div className="fm-divider" />
              <div className="fm-tiny-stat"><span>Last edited</span><strong>18 Jun 2025</strong></div>
              <div className="fm-tiny-stat"><span>Model currency</span><strong>EUR</strong></div>
              <div className="fm-tiny-stat"><span>Input state</span><strong>{saved ? "Acknowledged · view only" : "Demo draft"}</strong></div>
              <div className="fm-divider" />
              <button type="button" className="fm-btn" aria-disabled={blocked || cellEditing} style={{ width: "100%" }} onClick={save}>{saved ? "Demo acknowledged · session only" : "Save demo"}</button>
              <button type="button" onClick={run} aria-disabled={runBlocked} className="fm-btn fm-btn-primary" style={{ width: "100%", marginTop: 7 }}>View demo results →</button>
              <div style={{ marginTop: 9, color: "var(--muted)", fontSize: 9, lineHeight: 1.5 }}>Run model is a visual affordance only. It opens predetermined synthetic results; no formulas execute.</div>
            </div>
          </Panel>
          <Panel title="Input provenance" meta="Demo register">
            <div style={{ padding: 12 }}>
              {[["Project brief", "Fictional · 12 Jun 2025"], ["PPA term sheet", "Illustrative · 03 Jun 2025"], ["Lender assumptions", "Illustrative · 18 Jun 2025"]].map(([a,b]) =>
                <div key={a} className="fm-tiny-stat" style={{ paddingLeft: 0, paddingRight: 0 }}><span>{a}</span><strong style={{ fontSize: 9 }}>{b}</strong></div>
              )}
              <div className="fm-hint" style={{ marginTop: 9 }}>These labels represent invented sample materials; no files are attached.</div>
            </div>
          </Panel>
          <div id="trust" tabIndex={-1} className="fm-info-note fm-section" style={{ marginTop: 12 }}><strong style={{ display: "block", color: "var(--ink)", marginBottom: 3 }}>Trust boundary</strong>Selected project: {project.name} · {project.technology}. Local drafts are isolated by demo project ID in this browser tab, but use common synthetic starting values; the fixed results are shared and not project-specific. Drafts can be reset; nothing is saved to a backend and no financial calculations execute.</div>
        </aside>
      </div>
      </div>
      </fieldset>
      </div>
      <div className="fm-footer">Browser-tab demo session only · No backend persistence, live calculations, or API connection</div>
    </main>
  </Shell>;
}
