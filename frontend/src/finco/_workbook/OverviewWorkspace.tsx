import React from "react";
import "./overview.css";
import { resultsValueText, type ResultsChartModel, type ResultsDisplayValue } from "../_results/resultsContract";
import type { ProjectContext } from "../_shared/FincoShell";
import type { InsightExplainInput, InsightFindingPresentation } from "../_insight/insightContract";

export type OverviewWorkspaceProps = {
  project: ProjectContext;
  status: { label: string; tone: string; detail: string };
  kpis: readonly { id: string; label: string; value: ResultsDisplayValue; note: string }[];
  charts: readonly { id: string; title: string; model: ResultsChartModel | null }[];
  readOnly: boolean;
  onOpenSheet: (id: string) => void;
  topFindings?: readonly InsightFindingPresentation[];
  onExplain?: (item: InsightExplainInput) => void;
  onNavigateFinding?: (target: NonNullable<InsightFindingPresentation["destination"]>) => void;
};

function chartSegments(chart: ResultsChartModel) {
  return chart.series.map((series) => {
    const segments: typeof series.points[] = [];
    let active: typeof series.points = [];
    series.points.forEach((point) => {
      if (point.value.kind === "value" && point.geometry) active.push(point);
      else if (active.length) {
        segments.push(active);
        active = [];
      }
    });
    if (active.length) segments.push(active);
    return { series, segments };
  });
}

function OverviewChart({ title, model }: { title: string; model: ResultsChartModel | null }) {
  if (!model) {
    return (
      <div className="fm-overview-chart-empty" role="status">
        <span className="fm-overview-empty-mark" aria-hidden="true">—</span>
        <strong>Chart unavailable</strong>
        <span>No chart model was supplied.</span>
      </div>
    );
  }

  const rendered = chartSegments(model);
  const hasGeometry = rendered.some(({ series, segments }) =>
    series.kind === "bar"
      ? series.points.some((point) => point.value.kind === "value" && point.geometry)
      : segments.some((segment) => segment.length > 0),
  );
  if (!hasGeometry) {
    return (
      <div className="fm-overview-chart-empty" role="status">
        <span className="fm-overview-empty-mark" aria-hidden="true">—</span>
        <strong>Chart values unavailable</strong>
        <span>No displayable chart values were supplied.</span>
      </div>
    );
  }

  return (
    <div className="fm-overview-chart-visual">
      <svg className="fm-overview-svg" viewBox="0 0 600 155" role="img" aria-label={model.ariaLabel || title}>
        {model.gridLines.map((y, index) => (
          <line key={`${index}-${y}`} x1={model.gridStartX} y1={y} x2={model.gridEndX} y2={y} className="fm-overview-gridline" />
        ))}
        {rendered.map(({ series, segments }) => (
          <g key={series.id}>
            {series.kind === "line" && segments.map((segment, index) => {
              const path = segment.map((point, pointIndex) =>
                `${pointIndex === 0 ? "M" : "L"}${point.geometry!.x} ${point.geometry!.y}`,
              ).join(" ");
              const complete = segments.length === 1 && segment.length === series.points.length;
              const area = complete && series.area
                ? `${path} L ${segment[segment.length - 1].geometry!.x} ${model.baselineY} L ${segment[0].geometry!.x} ${model.baselineY} Z`
                : null;
              return (
                <React.Fragment key={`${series.id}-${index}`}>
                  {area && <path d={area} className={`fm-overview-area ${series.tone}`} />}
                  <path d={path} className={`fm-overview-line ${series.tone}`} />
                </React.Fragment>
              );
            })}
            {series.kind === "line" && series.points.filter((point) => point.marker && point.value.kind === "value" && point.geometry).map((point) => (
              <circle key={point.period} cx={point.geometry!.x} cy={point.geometry!.y} r="2.8" className={`fm-overview-marker ${series.tone}`}>
                <title>{point.value.kind === "value" ? point.value.tooltip || `${point.period}: ${point.value.text}` : ""}</title>
              </circle>
            ))}
            {series.kind === "bar" && series.points.filter((point) => point.value.kind === "value" && point.geometry).map((point) => (
              <rect key={point.period} x={point.geometry!.x} y={point.geometry!.y}
                width={point.geometry!.width ?? 18} height={point.geometry!.height ?? 0}
                className={`fm-overview-bar ${series.tone}`}>
                <title>{point.value.kind === "value" ? point.value.tooltip || `${point.period}: ${point.value.text}` : ""}</title>
              </rect>
            ))}
          </g>
        ))}
        {model.periodLabels.map(({ label, x }, index) => (
          <text key={`${index}-${label}`} x={x} y="145" textAnchor="middle" className="fm-overview-axis-label">{label}</text>
        ))}
        <text x={model.axisLabelX} y="28" className="fm-overview-axis-label">{model.axisTopLabel}</text>
        <text x={model.axisLabelX} y="126" className="fm-overview-axis-label">{model.axisBottomLabel}</text>
      </svg>
      <div className="fm-overview-legend" aria-label="Chart legend">
        {model.series.map((series) => (
          <span key={series.id}><i className={`fm-overview-legend-mark ${series.kind} ${series.tone}`} />{series.label}</span>
        ))}
        {model.caption && <span className="fm-overview-chart-caption">{model.caption}</span>}
      </div>
    </div>
  );
}

function KpiValue({ value }: { value: ResultsDisplayValue }) {
  const text = resultsValueText(value);
  return (
    <span className={value.kind === "unavailable" ? "fm-overview-unavailable" : undefined}
      aria-label={value.kind === "unavailable" ? `${text}${value.reason ? `: ${value.reason}` : ""}` : undefined}>
      {text}
    </span>
  );
}

function activateFromKeyboard(event: React.KeyboardEvent<HTMLButtonElement>, action: () => void) {
  if (event.key !== "Enter" && event.key !== " ") return;
  event.preventDefault();
  action();
}

export function OverviewWorkspace({ project, status, kpis, charts, readOnly, onOpenSheet, topFindings = [], onExplain, onNavigateFinding }: OverviewWorkspaceProps) {
  const tone = ["green", "blue", "amber", "gray"].includes(status.tone) ? status.tone : "gray";
  const chartSlots = Array.from({ length: 4 }, (_, index) => charts[index] ?? null);

  return (
    <section className="fm-overview" aria-label="Project overview">
      <header className="fm-overview-heading">
        <div>
          <div className="fm-overview-eyebrow">Project overview <span aria-hidden="true">/</span> {project.id}</div>
          <h2>Starting point</h2>
          <p>A concise view of project context and supplied model indicators.</p>
        </div>
        <div className="fm-overview-actions" aria-label="Overview destinations">
          <button type="button" id="overview-open-input-grid" className="fm-btn" onKeyDown={event => activateFromKeyboard(event, () => onOpenSheet("input-grid"))} onClick={() => onOpenSheet("input-grid")}>
            Open Input Grid <span aria-hidden="true">→</span>
          </button>
          <button type="button" className="fm-btn fm-btn-primary" onKeyDown={event => activateFromKeyboard(event, () => onOpenSheet("findings"))} onClick={() => onOpenSheet("findings")}>
            Open Findings <span aria-hidden="true">→</span>
          </button>
        </div>
      </header>

      <section className="fm-overview-project" aria-label="Project context">
        <div className="fm-overview-project-title">
          <span className="fm-overview-label">Project context</span>
          <strong>{project.name}</strong>
          <span className="fm-overview-project-id">{project.id}</span>
        </div>
        <dl className="fm-overview-context">
          <div><dt>Technology</dt><dd>{project.technology || "Unavailable"}</dd></div>
          <div><dt>Installed size</dt><dd>{project.size || "Unavailable"}</dd></div>
          <div><dt>Region</dt><dd>{project.region || "Unavailable"}</dd></div>
          <div><dt>Workspace mode</dt><dd>{project.mode === "reference" ? "Reference" : project.mode === "working-copy" ? "Working copy" : "Unavailable"}</dd></div>
        </dl>
        <div className="fm-overview-state">
          <span className="fm-overview-label">Project status</span>
          <span className={`fm-overview-status ${tone}`} role="status">{status.label || "Unavailable"}</span>
          <p>{status.detail || "Status detail unavailable."}</p>
          <span className="fm-overview-readonly">{readOnly ? "Read-only view" : "Workspace view"}</span>
        </div>
      </section>

      <section className="fm-overview-kpis" aria-label="Supplied project indicators">
        <div className="fm-overview-section-head">
          <div><span className="fm-overview-label">At a glance</span><h3>Key indicators</h3></div>
           <span>Shared fixed examples · not project-specific</span>
        </div>
        {kpis.length ? (
          <div className="fm-overview-kpi-grid">
            {kpis.map((item) => (
              <article className="fm-overview-kpi" key={item.id}>
                <span className="fm-overview-kpi-label">{item.label}</span>
                <strong className="fm-overview-kpi-value"><KpiValue value={item.value} /></strong>
                <span className="fm-overview-kpi-note">{item.note}</span>
                {onExplain && <button type="button" className="fm-small-link fm-overview-explain" onClick={event => {
                  event.currentTarget.focus();
                  onExplain({
                  id: `overview-kpi-${item.id}`,
                  kind: "Indicator",
                  title: item.label,
                  value: resultsValueText(item.value),
                  basis: item.note.includes("Earlier")
                    ? "Earlier fixed illustrative indicator. It does not reflect the current input draft."
                    : "Fixed illustrative indicator supplied for this preview. No calculation path or project-specific source detail is supplied.",
                  });
                }}>Explain</button>}
              </article>
            ))}
          </div>
        ) : (
          <div className="fm-overview-unavailable-panel" role="status">
            <strong>Indicators unavailable</strong>
            <span>No KPI display values were supplied.</span>
          </div>
        )}
      </section>

      <section className="fm-overview-charts" aria-label="Project chart overview">
        <div className="fm-overview-section-head">
          <div><span className="fm-overview-label">Display only</span><h3>Project profiles</h3></div>
          <span>Chart values are not recalculated here</span>
        </div>
        <div className="fm-overview-chart-grid">
          {chartSlots.map((slot, index) => (
            <article className={`fm-overview-chart-card${index === 0 ? " lead" : ""}`} key={slot?.id ?? `unavailable-chart-${index}`}>
              <div className="fm-overview-chart-title">
                <div><span className="fm-overview-chart-index">{String(index + 1).padStart(2, "0")}</span><h4>{slot?.title || `Chart ${index + 1}`}</h4></div>
                 <span>{slot?.model ? "Shared fixed example" : "Unavailable"}</span>
              </div>
              <OverviewChart title={slot?.title || `Chart ${index + 1}`} model={slot?.model ?? null} />
            </article>
          ))}
        </div>
      </section>

      <section className="fm-overview-findings" aria-label="Top findings">
        <div className="fm-overview-findings-copy">
          <span className="fm-overview-label">Review queue</span>
          <h3>Top findings</h3>
          <p>Shared review notes for this preview. They are not lender conclusions.</p>
        </div>
        <div className="fm-overview-findings-empty" role="status">
          {topFindings.length ? topFindings.slice(0, 2).map((finding) => <div className="fm-overview-finding-item" key={finding.id}>
            <strong>{finding.title}</strong>
            <span>{finding.evidenceState === "current" ? finding.why : "Couldn’t be checked yet · no current example evidence."}</span>
            <div>{onExplain && <button type="button" className="fm-small-link" onClick={event => {
              event.currentTarget.focus();
              onExplain({
              id: `finding-${finding.id}`,
              kind: "Finding",
              title: finding.title,
              value: finding.evidenceState === "current" ? finding.displayedValue : "Unavailable",
              basis: finding.checkNote,
              destination: finding.destination,
              });
            }}>Explain</button>}{finding.destination && onNavigateFinding && <button type="button" className="fm-small-link" onClick={() => onNavigateFinding(finding.destination!)}>Go to input</button>}</div>
          </div>) : <span>No findings match this screen.</span>}
        </div>
        <button type="button" className="fm-overview-findings-link" onKeyDown={event => activateFromKeyboard(event, () => onOpenSheet("findings"))} onClick={() => onOpenSheet("findings")}>
          View Findings <span aria-hidden="true">→</span>
        </button>
      </section>
      <p className="fm-overview-footnote">Overview uses supplied project and display data only. It does not run or verify financial calculations.</p>
    </section>
  );
}

export default OverviewWorkspace;
