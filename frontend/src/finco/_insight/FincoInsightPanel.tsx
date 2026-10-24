import React, { useEffect, useMemo, useRef, useState } from "react";
import {
  contextualFindings,
  insightChangesSummary,
  type InsightContext,
  type InsightExplainItem,
  type InsightFindingPresentation,
  type InsightMode,
} from "./insightContract";
import "./insight.css";

export type FincoInsightPanelProps = {
  open: boolean;
  mode: InsightMode;
  context: InsightContext;
  findings: readonly InsightFindingPresentation[];
  explainItems: readonly InsightExplainItem[];
  selectedExplainItem: InsightExplainItem | null;
  onModeChange: (mode: InsightMode) => void;
  onRequestClose: () => void;
  onExplain: (item: InsightExplainItem) => void;
  onNavigate: (target: NonNullable<InsightFindingPresentation["destination"]>) => void;
  onOpenFindings: () => void;
};

const modes: { id: InsightMode; label: string }[] = [
  { id: "review", label: "Review" },
  { id: "explain", label: "Explain" },
  { id: "changes", label: "Changes" },
];

const priorityGroups = [
  { id: "needs-attention", label: "Needs attention" },
  { id: "worth-a-look", label: "Worth a look" },
  { id: "could-not-check", label: "Couldn’t be checked yet" },
] as const;

function FindingCard({
  finding,
  onExplain,
  onNavigate,
}: {
  finding: InsightFindingPresentation;
  onExplain: () => void;
  onNavigate: () => void;
}) {
  const current = finding.evidenceState === "current";
  return (
    <article className={`fm-insight-finding fm-insight-finding-${finding.priorityGroup}`} data-testid={`insight-finding-${finding.id}`}>
      <div className="fm-insight-finding-heading">
        <span className={`fm-insight-severity ${finding.severity}`}>{finding.severity}</span>
        <span className="fm-insight-evidence-state">{current ? "Current example" : finding.evidenceState === "stale" ? "Earlier example" : "Not available"}</span>
      </div>
      <h4>{finding.title}</h4>
      <p>{finding.why}</p>
      {current ? (
        <dl className="fm-insight-evidence">
          <div><dt>{finding.evidenceLabel}</dt><dd>{finding.displayedValue}{finding.evidenceValue && !/[a-z%€]/i.test(finding.evidenceValue) ? ` ${finding.area === "inputs" ? "years" : ""}` : ""}</dd></div>
          <div><dt>{finding.thresholdLabel}</dt><dd>{finding.displayedThreshold}</dd></div>
        </dl>
      ) : <p className="fm-insight-unavailable">{finding.checkNote}</p>}
      {current && finding.adviceText && <p className="fm-insight-advice"><strong>Suggested review:</strong> {finding.adviceText}</p>}
      <div className="fm-insight-finding-actions">
        {finding.destination && <button type="button" className="fm-small-link" onClick={onNavigate}>Go to related input</button>}
        <button type="button" className="fm-small-link" onClick={onExplain}>Explain</button>
      </div>
    </article>
  );
}

export default function FincoInsightPanel({
  open,
  mode,
  context,
  findings,
  explainItems,
  selectedExplainItem,
  onModeChange,
  onRequestClose,
  onExplain,
  onNavigate,
  onOpenFindings,
}: FincoInsightPanelProps) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [search, setSearch] = useState("");
  const relevantFindings = useMemo(
    () => contextualFindings(findings, context.activeArea),
    [context.activeArea, findings],
  );
  const matchingExplainItems = useMemo(() => {
    const items = selectedExplainItem
      ? [selectedExplainItem, ...explainItems.filter((item) => item.id !== selectedExplainItem.id)]
      : [...explainItems];
    const query = search.trim().toLowerCase();
    return query
      ? items.filter((item) => `${item.title} ${item.value} ${item.unit || ""} ${item.contextLabel}`.toLowerCase().includes(query))
      : items;
  }, [explainItems, search, selectedExplainItem]);
  const changes = insightChangesSummary(context);

  useEffect(() => {
    const element = dialog.current;
    if (!element) return;
    if (open && !element.open) {
      element.showModal();
      element.querySelector<HTMLButtonElement>("[data-insight-close]")?.focus();
    } else if (!open && element.open) {
      element.close();
    }
  }, [open]);

  function changeMode(next: InsightMode) {
    onModeChange(next);
  }

  function handleTabKey(event: React.KeyboardEvent<HTMLDivElement>) {
    if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
    const currentIndex = modes.findIndex((item) => item.id === mode);
    const nextIndex = event.key === "Home"
      ? 0
      : event.key === "End"
        ? modes.length - 1
        : (currentIndex + (event.key === "ArrowRight" ? 1 : -1) + modes.length) % modes.length;
    event.preventDefault();
    changeMode(modes[nextIndex].id);
    requestAnimationFrame(() => document.getElementById(`fm-insight-tab-${modes[nextIndex].id}`)?.focus());
  }

  function explainFinding(finding: InsightFindingPresentation) {
    onExplain({
      id: `finding-${finding.id}`,
      kind: "Finding",
      title: finding.title,
      value: finding.evidenceState === "current" ? finding.displayedValue : "Unavailable",
      unit: finding.evidenceState === "current" ? finding.thresholdLabel : undefined,
      contextLabel: `${context.projectName} · ${context.scenarioId}`,
      basis: finding.evidenceState === "current"
        ? "Fixed illustrative check values. The related input link is navigation only, not a calculation path."
        : finding.checkNote,
      destination: finding.destination,
    });
    onModeChange("explain");
  }

  function requestDestination(target: NonNullable<InsightFindingPresentation["destination"]>) {
    onNavigate(target);
  }

  return (
    <dialog
      ref={dialog}
      id="fm-insight-dialog"
      className="fm-insight-panel"
      aria-labelledby="fm-insight-title"
      aria-describedby="fm-insight-description"
      data-testid="finco-insight-panel"
      onCancel={(event) => { event.preventDefault(); onRequestClose(); }}
      onClick={(event) => { if (event.target === event.currentTarget) onRequestClose(); }}
    >
      <div className="fm-insight-panel-inner">
        <header className="fm-insight-panel-header">
          <div>
            <span className="fm-eyebrow">Project review</span>
            <h2 id="fm-insight-title">FINCO Insight</h2>
            <p id="fm-insight-description">{context.projectName} · {context.technology} · {context.scenarioId}</p>
          </div>
          <button data-insight-close type="button" className="fm-btn" aria-label="Close FINCO Insight" onClick={onRequestClose}>Close</button>
        </header>
        <div className="fm-insight-disclosure" role="note">
          Illustrative design preview · No financial calculations, lender assessment, or live data.
        </div>
        <div className="fm-insight-mode-tabs" role="tablist" aria-label="Insight view" onKeyDown={handleTabKey}>
          {modes.map((item) => (
            <button
              key={item.id}
              id={`fm-insight-tab-${item.id}`}
              type="button"
              role="tab"
              aria-selected={mode === item.id}
              aria-controls={`fm-insight-panel-${item.id}`}
              tabIndex={mode === item.id ? 0 : -1}
              onClick={() => changeMode(item.id)}
            >{item.label}</button>
          ))}
        </div>
        {mode === "review" && (
          <section id="fm-insight-panel-review" className="fm-insight-panel-content" role="tabpanel" aria-labelledby="fm-insight-tab-review" tabIndex={0}>
            <div className="fm-insight-context-line"><strong>{context.activeScreen}</strong><span>{context.statusLabel}</span></div>
            <p className="fm-insight-context-detail">{context.statusDetail}</p>
            {priorityGroups.map((group) => {
              const groupFindings = relevantFindings.filter((item) => item.priorityGroup === group.id);
              return (
                <section className="fm-insight-group" key={group.id} aria-label={group.label}>
                  <h3>{group.label}<span>{groupFindings.length}</span></h3>
                  {groupFindings.length ? groupFindings.map((finding) => (
                    <FindingCard
                      key={finding.id}
                      finding={finding}
                      onExplain={() => explainFinding(finding)}
                      onNavigate={() => finding.destination && requestDestination(finding.destination)}
                    />
                  )) : <p className="fm-insight-empty-group">No items in this group for the current view.</p>}
                </section>
              );
            })}
            <button type="button" className="fm-insight-all-findings" onClick={onOpenFindings}>See all findings →</button>
          </section>
        )}
        {mode === "explain" && (
          <section id="fm-insight-panel-explain" className="fm-insight-panel-content" role="tabpanel" aria-labelledby="fm-insight-tab-explain" tabIndex={0}>
            <label className="fm-insight-search">Find an item
              <input id="fm-insight-search" type="search" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search indicators, inputs or rows" />
            </label>
            {selectedExplainItem && (
              <article className="fm-insight-explanation" data-testid="insight-explanation">
                <span className="fm-insight-evidence-state">{selectedExplainItem.kind}</span>
                <h3>{selectedExplainItem.title}</h3>
                <p className="fm-insight-explanation-value">{selectedExplainItem.value}{selectedExplainItem.unit ? ` ${selectedExplainItem.unit}` : ""}{selectedExplainItem.period ? ` · ${selectedExplainItem.period}` : ""}</p>
                <p>{selectedExplainItem.basis}</p>
                <small>{selectedExplainItem.contextLabel}</small>
                {selectedExplainItem.destination
                  ? <button type="button" className="fm-small-link" onClick={() => selectedExplainItem.destination && requestDestination(selectedExplainItem.destination)}>Open related section →</button>
                  : <p className="fm-insight-unavailable">We don’t have the source details for this value yet.</p>}
              </article>
            )}
            <div className="fm-insight-search-results" role="list" aria-label="Available display items">
              {matchingExplainItems.map((item) => (
                <div role="listitem" key={item.id}>
                  <button type="button" onClick={() => onExplain(item)} aria-current={selectedExplainItem?.id === item.id ? "true" : undefined}>
                    <span>{item.kind} · {item.title}</span><strong>{item.value}{item.unit ? ` ${item.unit}` : ""}</strong>
                  </button>
                </div>
              ))}
              {!matchingExplainItems.length && <p role="status">No matching items. Try a different search.</p>}
            </div>
          </section>
        )}
        {mode === "changes" && (
          <section id="fm-insight-panel-changes" className="fm-insight-panel-content" role="tabpanel" aria-labelledby="fm-insight-tab-changes" tabIndex={0}>
            <dl className="fm-insight-changes">
              <div><dt>Current status</dt><dd>{changes.currentStatus}</dd></div>
              <div><dt>Inputs</dt><dd>{changes.inputs}</dd></div>
              <div><dt>Results</dt><dd>{changes.results}</dd></div>
               <div><dt>Working scenario</dt><dd>{changes.workingScenario}</dd></div>
               <div><dt>Last Run scenario</dt><dd>{changes.lastRunScenario}</dd></div>
               <div><dt>Last Run reference</dt><dd>{changes.lastRunReference}</dd></div>
               <div><dt>Result source</dt><dd>{changes.resultOrigin}</dd></div>
               <div><dt>Run date</dt><dd>{changes.resultDate}</dd></div>
               <div><dt>Freshness</dt><dd>{changes.freshness}</dd></div>
               <div><dt>Calculation details</dt><dd>{changes.calculationVersion}</dd></div>
               <div><dt>Review status</dt><dd>{changes.resultChecks}</dd></div>
            </dl>
            {changes.conflict && <p className="fm-insight-unavailable" role="status">{changes.conflict}</p>}
            <p className="fm-insight-changes-note">{changes.note}</p>
            <p className="fm-insight-changes-note">Save in this preview does not calculate results. Input edits never change the fixed example figures.</p>
          </section>
        )}
      </div>
    </dialog>
  );
}

