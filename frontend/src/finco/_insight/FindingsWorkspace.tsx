import React, { useMemo, useState } from "react";
import { filterFindings, type InsightArea, type InsightExplainItem, type InsightFindingPresentation, type InsightFindingsFilters } from "./insightContract";
import type { InsightPriorityGroup } from "./insightContract";
import "./insight.css";

const priorities: { id: InsightPriorityGroup; label: string }[] = [
  { id: "needs-attention", label: "Needs attention" },
  { id: "worth-a-look", label: "Worth a look" },
  { id: "could-not-check", label: "Couldn’t be checked yet" },
];

const covenantExamples = [
  { period: "2029", facility: "Senior A example", dscr: "1.30x", reference: "1.20x illustrative review reference" },
  { period: "2029", facility: "Mezzanine example", dscr: "1.08x", reference: "1.20x illustrative review reference" },
  { period: "2030", facility: "Senior B example", dscr: "Unavailable", reference: "No current result supplied" },
];

const areaLabels: Record<InsightArea, string> = {
  project: "Project",
  inputs: "Inputs",
  financing: "Financing",
  results: "Results",
  scenarios: "Scenarios",
  analysis: "Analysis",
  tax: "Tax",
};

export type FindingsWorkspaceProps = {
  findings: readonly InsightFindingPresentation[];
  contextLabel: string;
  onExplain: (item: InsightExplainItem) => void;
  onNavigate: (target: NonNullable<InsightFindingPresentation["destination"]>) => void;
};

export default function FindingsWorkspace({ findings, contextLabel, onExplain, onNavigate }: FindingsWorkspaceProps) {
  const [filters, setFilters] = useState<InsightFindingsFilters>({ severity: "all", area: "all", status: "all" });
  const visible = useMemo(() => filterFindings(findings, filters), [findings, filters]);

  function explain(finding: InsightFindingPresentation) {
    onExplain({
      id: `finding-${finding.id}`,
      kind: "Finding",
      title: finding.title,
      value: finding.evidenceState === "current" ? finding.displayedValue : "Unavailable",
      contextLabel,
      basis: finding.evidenceState === "current"
        ? "Fixed illustrative check values only. Any related section is a navigation aid, not a calculation path."
        : finding.checkNote,
      destination: finding.destination,
    });
  }

  return (
    <section className="fm-findings-workspace" aria-labelledby="fm-findings-title">
      <header className="fm-findings-heading">
        <div><span className="fm-eyebrow">Review queue</span><h2 id="fm-findings-title">Findings</h2>
          <p>Contextual notes for this project preview. No lender decision or financial check is performed.</p></div>
        <span className="fm-insight-disclosure">Illustrative design preview · {contextLabel}</span>
      </header>
      <div className="fm-findings-filters" aria-label="Filter findings">
        <label>Severity
          <select aria-label="Filter findings by severity" value={filters.severity} onChange={(event) => setFilters((current) => ({ ...current, severity: event.target.value as InsightFindingsFilters["severity"] }))}>
            <option value="all">All severities</option><option value="high">High</option><option value="moderate">Moderate</option><option value="information">Information</option>
          </select>
        </label>
        <label>Area
          <select aria-label="Filter findings by area" value={filters.area} onChange={(event) => setFilters((current) => ({ ...current, area: event.target.value as InsightFindingsFilters["area"] }))}>
            <option value="all">All areas</option>{Object.entries(areaLabels).map(([id, label]) => <option key={id} value={id}>{label}</option>)}
          </select>
        </label>
        <label>Status
          <select aria-label="Filter findings by status" value={filters.status} onChange={(event) => setFilters((current) => ({ ...current, status: event.target.value as InsightFindingsFilters["status"] }))}>
            <option value="all">All statuses</option>{priorities.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}
          </select>
        </label>
      </div>
      {priorities.map((priority) => {
        const group = visible.filter((finding) => finding.priorityGroup === priority.id);
        return <section className="fm-findings-group" key={priority.id} aria-label={priority.label}>
          <h3>{priority.label}<span>{group.length}</span></h3>
          {group.map((finding) => (
            <article className="fm-findings-row" key={finding.id} data-testid={`findings-row-${finding.id}`}>
              <div className="fm-findings-row-main">
                <div className="fm-insight-finding-heading">
                  <span className={`fm-insight-severity ${finding.severity}`}>{finding.severity}</span>
                  <span>{areaLabels[finding.area]}</span>
                  <span className="fm-insight-evidence-state">{finding.evidenceState === "current" ? "Fixed example" : finding.evidenceState === "stale" ? "Earlier example" : "Not checked"}</span>
                </div>
                <h4>{finding.title}</h4><p>{finding.why}</p>
                {finding.evidenceState === "current" ? <div className="fm-findings-evidence">
                  <span>{finding.evidenceLabel}: <strong>{finding.displayedValue}</strong></span>
                  <span>{finding.thresholdLabel}: <strong>{finding.displayedThreshold}</strong></span>
                </div> : <p className="fm-insight-unavailable">{finding.checkNote}</p>}
                {finding.adviceText && finding.evidenceState === "current" && <p className="fm-insight-advice"><strong>Suggested review:</strong> {finding.adviceText}</p>}
              </div>
              <div className="fm-insight-finding-actions">
                {finding.destination && <button type="button" className="fm-small-link" onClick={() => onNavigate(finding.destination!)}>Go to related input</button>}
                <button type="button" className="fm-small-link" onClick={() => explain(finding)}>Explain</button>
              </div>
            </article>
          ))}
        </section>;
      })}
      {!visible.length && <div className="fm-insight-empty-state" role="status">No findings match these filters.</div>}
      <section className="fm-findings-credit" aria-labelledby="fm-findings-credit-title">
        <div className="fm-findings-credit-heading"><div><span className="fm-eyebrow">Illustrative lender review</span><h3 id="fm-findings-credit-title">Lender readiness &amp; covenants</h3></div>
          <span className="fm-insight-unavailable">Not assessed</span></div>
        <p>Pre-authored period examples for layout only. No covenant thresholds are tested, and no DSCR is calculated.</p>
        <div className="fm-findings-table-scroll" role="region" aria-label="Illustrative period covenant examples" tabIndex={0}>
          <table className="fm-findings-table"><caption>Fixed sample values · not a lender conclusion</caption>
            <thead><tr><th scope="col">Period</th><th scope="col">Facility</th><th scope="col">Displayed DSCR</th><th scope="col">Review reference</th><th scope="col">Assessment</th></tr></thead>
            <tbody>{covenantExamples.map((row) => <tr key={`${row.facility}-${row.period}`}><th scope="row">{row.period}</th><td>{row.facility}</td><td>{row.dscr}</td><td>{row.reference}</td><td>Not assessed</td></tr>)}</tbody>
          </table>
        </div>
        <p className="fm-findings-footnote">This period view is illustrative. A displayed comparison does not establish covenant compliance or lender readiness.</p>
      </section>
      <div className="fm-findings-empty-coverage">
        <strong>Some review areas are not included</strong>
        <span>Tax schedules, committed scenario results, supporting documents and lender evidence may be unavailable in this preview.</span>
      </div>
    </section>
  );
}

