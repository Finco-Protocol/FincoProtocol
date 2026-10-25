import React, { useEffect, useId } from "react";
import { fincoWorkingCopyBridge, type FincoWorkingCopySummary } from "./fincoProjectBridge";
import { ThemeSelector } from "./ThemeSelector";

declare global {
  interface Window {
    __FINCO_TRANSFER_APP__?: boolean;
    __FINCO_TRANSFER_BASE__?: string;
    __FINCO_TRANSFER_NAVIGATE__?: (href: string) => void;
  }
}

export function fincoBasePath(): string {
  return window.__FINCO_TRANSFER_APP__
    ? window.__FINCO_TRANSFER_BASE__ || "/"
    : "/__mockup/preview/finco-model/";
}

export function navigateFinco(href: string): void {
  if (window.__FINCO_TRANSFER_NAVIGATE__) {
    window.__FINCO_TRANSFER_NAVIGATE__(href);
    return;
  }
  window.location.assign(href);
}

export type ProjectContext = {
  name: string;
  id: string;
  technology: string;
  size: string;
  region: string;
  mode?: "reference" | "working-copy";
  parentReferenceId?: string | null;
  parentReferenceName?: string | null;
  registeredWorkingCopy?: boolean;
};

export function readProjectContext(): ProjectContext {
  const params = new URLSearchParams(window.location.search);
  const id = params.get("projectId") || "PRJ-0241";
  const mode = params.get("mode") === "reference" ? "reference" : "working-copy";
  let copy: FincoWorkingCopySummary | undefined;
  const bridge = mode === "working-copy" ? fincoWorkingCopyBridge() : undefined;
  if (bridge) {
    try {
      copy = bridge.read(id);
    } catch {
      copy = undefined;
    }
  }
  return {
    name: copy?.name || params.get("project") || "FINCO Model project",
    id: copy?.id || id,
    technology: copy?.technology || params.get("technology") || "Solar PV",
    size: copy?.size || params.get("size") || "120 MWp",
    region: copy?.region || params.get("region") || "Region not set",
    mode,
    parentReferenceId: copy?.parentReferenceId ?? params.get("parentReferenceId"),
    parentReferenceName: copy?.parentReferenceName ?? null,
    registeredWorkingCopy: Boolean(copy),
  };
}

export function projectWorkspaceHref(
  project: ProjectContext,
  options: { mode?: "reference" | "working-copy"; parentReferenceId?: string } = {},
): string {
  const mode = options.mode || "working-copy";
  const params = new URLSearchParams({
    project: project.name,
    projectId: project.id,
    technology: project.technology,
    size: project.size,
    region: project.region,
    sheet: "input-grid",
    mode,
  });
  const parentReferenceId = options.parentReferenceId || project.parentReferenceId;
  if (mode === "working-copy" && parentReferenceId) params.set("parentReferenceId", parentReferenceId);
  return `${fincoBasePath()}ModelWorkspace?${params.toString()}#workbook`;
}

export function Shell({ children, crumb = "Project library", mainContentId = "fm-main-content", dataOrigin = "synthetic-demo", originLabel, libraryHref }: {
  children: React.ReactNode;
  crumb?: string;
  mainContentId?: string;
  dataOrigin?: "synthetic-demo" | "caller-provided" | "canonical-run" | "unavailable";
  /** Live application only: the persisted-state chip text (e.g. "CURRENT RUN"). */
  originLabel?: string;
  /** Live application only: the real Project Library route (the demo path is a design-harness route). */
  libraryHref?: string;
}) {
  const live = dataOrigin === "canonical-run";
  const originText = originLabel ?? (dataOrigin === "synthetic-demo"
    ? "SYNTHETIC DEMO DATA"
    : dataOrigin === "caller-provided" ? "DATA ORIGIN UNVERIFIED" : dataOrigin === "canonical-run" ? "PERSISTED PROJECT DATA" : "NO RESULTS DATA");
  useEffect(() => {
    const fragment = decodeURIComponent(window.location.hash.slice(1));
    if (!fragment) return;
    const targetId = fragment === "workbook" && new URLSearchParams(window.location.search).get("mode") === "reference"
      ? "reference-mode-help"
      : fragment;
    const frame = window.requestAnimationFrame(() => {
      const target = document.getElementById(targetId) ?? document.getElementById(mainContentId);
      if (target instanceof HTMLElement) target.focus({ preventScroll: true });
    });
    return () => window.cancelAnimationFrame(frame);
  }, [mainContentId]);
  return (
    <div className="finco-root">
      <a className="fm-skip-link" href={`#${mainContentId}`}>Skip to main content</a>
      <header className="fm-topbar">
        <div className="fm-brand">
          <div className="fm-mark">FM</div>
          <div className="fm-brand-name">FINCO <span style={{ fontWeight: 500 }}>MODEL</span></div>
          <div className="fm-brand-caption">Renewable project finance</div>
        </div>
        <div className="fm-top-right">
          <span className={live ? "fm-live-label" : "fm-demo-label"} data-origin-chip={dataOrigin}>{originText}</span>
          <ThemeSelector />
          <span>{live ? "EUR" : "EUR · IFRS"}</span>
          {!live && <div className="fm-avatar">AR</div>}
        </div>
      </header>
      <nav className="fm-workspace-bar" aria-label="Project breadcrumb">
        {live
          ? <><a href={libraryHref ?? "/v2/model-react/"}>Project Library</a><span aria-hidden="true">/</span><span className="fm-crumb-current" aria-current="page">{crumb}</span></>
          : <><a href={`${fincoBasePath()}ProjectLibrary`}>Portfolio</a><span aria-hidden="true">/</span><strong>Renewables</strong><span aria-hidden="true">/</span><span className="fm-crumb-current" aria-current="page">{crumb}</span></>}
      </nav>
      {!live && <div className="fm-notice">Design prototype • No live calculations or backend connection</div>}
      {children}
    </div>
  );
}

export function DemoBanner({ copy = "Illustrative project assumptions and fixed outputs. No live calculations." }: { copy?: string }) {
  return <div className="fm-banner"><span className="fm-demo-label">SYNTHETIC DEMO DATA</span><span className="fm-banner-copy">{copy}</span></div>;
}

export function DemoContextStrip({ workingState }: { workingState: string }) {
  const project = readProjectContext();
  const params = new URLSearchParams(window.location.search);
  const isReference = project.mode === "reference";
  const parentId = project.parentReferenceId;
  const scenario = params.get("scenario") || "base";
  const scenarioNames: Record<string, string> = { base: "Base example", downside: "Downside example", upside: "Upside example" };
  const contract = params.get("contract") || "PPA-A example";
  const facility = params.get("facility") || params.get("tranche") || "Senior A example";
  const reset = () => {
    if (!window.confirm("Clear this browser tab's local FINCO demo drafts and working-copy entries, then reload? Fixed Last Run values will remain unchanged.")) return;
    fincoWorkingCopyBridge()?.clear();
    window.location.reload();
  };
  return <section className="fm-context-strip" aria-label="Demo project and run context">
    <div className="fm-context-items">
      <span><small>Project</small><strong>{project.name} · {project.technology}</strong></span>
      <span><small>{isReference ? "Project mode" : "Working copy"}</small><strong>{isReference ? "REFERENCE · READ ONLY" : `${workingState} · browser session only`}</strong></span>
      {isReference
        ? <span><small>Editing / Save / Run</small><strong>Disabled · inspect only</strong></span>
        : parentId && <span><small>Parent reference</small><strong>{project.parentReferenceName || parentId}</strong></span>}
      <span><small>Scenario</small><strong>{scenarioNames[scenario] || scenario}</strong></span>
      <span><small>Contract / facility</small><strong>{contract} · {facility}</strong></span>
      <span><small>Last Run</small><strong>DEMO-FIXED-018 · fixed reference</strong></span>
      <span><small>Freshness / engine</small><strong>UNKNOWN · NOT CONNECTED</strong></span>
      <span><small>Financial integrity</small><strong>NOT EVALUATED</strong></span>
    </div>
    <button type="button" className="fm-context-reset" disabled={isReference}
      aria-describedby={isReference ? "reference-reset-help" : undefined}
      title={isReference ? "Reset is disabled in read-only Reference mode." : undefined}
      onClick={reset}>Reset local demo session</button>
    {isReference && <span id="reference-reset-help" className="fm-sr-only">Reset is disabled in Reference mode to protect the local demo session. Create a working copy to use local demo controls.</span>}
  </section>;
}

const navItems = [
  { label: "Inputs", number: "01", route: "ModelWorkspace", hash: "inputs" },
  { label: "Statements", number: "02", route: "ModelWorkspace", hash: "statements" },
  { label: "Financing", number: "03", route: "ModelWorkspace", hash: "financing" },
  { label: "Results", number: "04", route: "ResultsAnalysis", hash: "results" },
  { label: "Scenarios", number: "05", route: "ModelWorkspace", hash: "scenarios" },
  { label: "Analysis", number: "06", route: "ResultsAnalysis", hash: "analysis" },
  { label: "Model checks", number: "07", route: "ModelWorkspace", hash: "checks" },
  { label: "Trust", number: "08", route: "ModelWorkspace", hash: "trust" },
];
export function ModelNav({ active = "Inputs", onSectionNavigate }: { active?: string; onSectionNavigate?: (id: string) => void }) {
  const search = window.location.search;
  return <nav className="fm-nav" aria-label="Model sections">{navItems.map(({ label, number, route, hash }) => (
    <a
      key={label}
      href={`${fincoBasePath()}${route}${search}#${hash}`}
      className={active === label ? "active" : ""}
      aria-current={active === label ? "page" : undefined}
      onKeyDown={event => {
        if (event.key !== "Enter") return;
        event.preventDefault();
        if (route === "ModelWorkspace" && onSectionNavigate) {
          onSectionNavigate(hash);
        } else {
          navigateFinco(`${fincoBasePath()}${route}${window.location.search}#${hash}`);
        }
      }}
      onClick={event => {
        if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
        if (route === "ModelWorkspace" && onSectionNavigate) {
          event.preventDefault();
          onSectionNavigate(hash);
        } else {
          event.preventDefault();
          navigateFinco(`${fincoBasePath()}${route}${window.location.search}#${hash}`);
        }
      }}
    >
      <span className="fm-nav-num">{number}</span>{label}
    </a>
  ))}</nav>;
}

export function Status({ children, tone = "gray" }: { children: React.ReactNode; tone?: "green" | "blue" | "amber" | "gray" }) {
  return <span className={`fm-status fm-status-${tone}`}>{children}</span>;
}

export function Field({ label, value, unit, calculated = false, invalid = false, hint, onChange, type = "text", id, error, warning, unavailable = false }: {
  label: string; value: string; unit?: string; calculated?: boolean; invalid?: boolean; hint?: string;
  onChange?: (value: string) => void; type?: string;
  id?: string; error?: string; warning?: string; unavailable?: boolean;
}) {
  const fixed = calculated || !onChange;
  const generatedId = useId();
  const inputId = id || generatedId;
  const bad = Boolean(error || invalid);
  const description = error || (invalid ? hint || "Value must be greater than zero" : warning || hint);
  return <div className="fm-field">
    <label htmlFor={inputId}>{label} <span className="fm-field-state">{unavailable ? "Unavailable" : calculated ? "Fixed demo" : fixed ? "Read-only demo" : "Editable"}</span></label>
    <div style={{ position: "relative" }}>
      <input id={inputId} className={`fm-input${fixed ? " fm-input-calculated" : ""}${bad ? " fm-input-invalid" : ""}`} value={value} type={type}
        readOnly={fixed} disabled={unavailable} onChange={onChange ? (e) => onChange(e.target.value) : undefined}
        aria-invalid={bad || undefined} aria-describedby={description ? `${inputId}-help` : undefined} aria-readonly={fixed || undefined} style={unit ? { paddingRight: 52 } : undefined} />
      {unit && <span className="fm-split-label" style={{ position: "absolute", right: 8, top: 8 }}>{unit}</span>}
    </div>
    {description && <span id={`${inputId}-help`} className={bad ? "fm-invalid-note" : warning ? "fm-warning-note" : "fm-hint"}>{bad ? "Error: " : warning ? "Warning: " : ""}{description}</span>}
  </div>;
}

export function Panel({ title, meta, children, className = "" }: { title: string; meta?: string; children: React.ReactNode; className?: string }) {
  return <section className={`fm-card ${className}`}><div className="fm-card-title"><h2>{title}</h2>{meta && <span>{meta}</span>}</div>{children}</section>;
}
