import { useEffect, useState } from 'react';
import { fetchInsights, fetchInsightsHistory } from './client';
import { CreditEvidenceCards } from './CreditEvidenceCards';
import { CreditTimeline } from './CreditTimeline';
import { EvidenceDisclosure } from './EvidenceDisclosure';
import { MetricCards } from './MetricCards';
import { SponsorSchedules } from './SponsorSchedules';
import { ScenarioComparison } from './ScenarioComparison';
import { evidenceDisplay, evidenceUnitLabel } from './presentation';
import { parseRunSnapshotId, runIdentityText } from '../runIdentity';
import { resultStatus, runStateLabel } from '../productLanguage';
import type { HistoryPayload, InsightsPayload, InsightRun, RunReference } from './types';
import './insights.css';
import { friendlyMessage } from '../productLanguage';

/** Explicit local view selection only. Does not select a workspace scenario or execute a Run. */
export function HistoricalRunSelector({ history, selected, onChange, onRead, busy = false }: {
  history: HistoryPayload; selected: string[]; onChange: (ids: string[]) => void; onRead: () => void; busy?: boolean;
}) {
  const maxRuns = Math.min(3, history.max_runs);
  return <section className="fi-panel"><h3>Historical Run intelligence</h3>
    <p>Project results: {resultStatus(history.working_copy.freshness)}. Historical Run identities are immutable; historical does not mean stale.</p>
    <fieldset><legend>Select one to {maxRuns} committed Runs. Selection order defines the comparison reference.</legend>
      {history.history.map(run => <label className="fi-run-option" key={run.identity.history_id}>
        <input type="checkbox" checked={selected.includes(run.identity.history_id)}
          disabled={busy || (!selected.includes(run.identity.history_id) && selected.length >= maxRuns)}
          onChange={event => onChange(event.target.checked ? [...selected, run.identity.history_id] : selected.filter(id => id !== run.identity.history_id))} />
        <span><strong>{run.identity.scenario}</strong> · {parseRunSnapshotId(run.identity.snapshot_id) ? runIdentityText(run.identity.snapshot_id) : (run.identity.ran_at || runIdentityText(run.identity.snapshot_id))} · {runStateLabel(run.identity.state)}<br />
          <small>Run reference {run.identity.history_id}</small></span>
      </label>)}
      {!history.history.length && <p>No committed Run evidence is available.</p>}
    </fieldset>
    <button type="button" disabled={busy || selected.length < 1 || selected.length > maxRuns} onClick={onRead}>{busy ? 'Reading evidence…' : 'Read selected Run evidence'}</button>
    <p className="fi-meta">{history.history_limit} most recent Runs maximum. Selected Runs: {selected.join(' → ') || 'none'}.</p>
    <details><summary>Scenario Run availability</summary>
      {history.scenarios.map(scenario => <p key={scenario.scenario_id ?? 'base'}><strong>{scenario.name}{scenario.is_base_case ? ' · Base Case' : ''}</strong>: {scenario.committed_run
        ? `Committed Run ${scenario.committed_run.history_id}` : scenario.availability === 'not_run' ? 'No committed Run exists for this scenario.' : 'Committed Run evidence unavailable.'} {scenario.reason}</p>)}
      {!history.scenarios_complete && <p>{history.scenarios_omitted} scenarios omitted by the listing limit.</p>}
    </details>
  </section>;
}

export function SponsorEvidence({ project, run }: { project: string; run: InsightRun }) {
  return <section className="fi-panel"><h3>Sponsor and investment evidence</h3>
    <p>Project IRR, Pure Equity IRR and Total Sponsor IRR keep their separate definitions. Distributions are not total sponsor cash flow.</p>
    <div className="fi-metrics">{run.sponsor.metrics.map(metric => <article className="fi-metric" key={metric.key} data-sponsor-metric={metric.key}>
      <h4>{metric.label}</h4><p className="fi-metric-value">{evidenceDisplay(metric.value, metric.display, metric.unit)} <small>{evidenceUnitLabel(metric.value, metric.display, metric.unit)}</small></p>
      <p>{metric.availability || (metric.value === null ? 'Unavailable' : 'Persisted')} {metric.reason}</p>
      <p className="fi-source">{metric.source}</p>
      <EvidenceDisclosure project={project} run={run} source={metric.source} unit={metric.unit} period="Committed Run aggregate" limitation={metric.reason} />
    </article>)}</div>
    <p>Sponsor schedule: {run.sponsor.sponsor_available ? 'Persisted' : 'Unavailable'} · {run.sponsor.sponsor_source || 'Source unavailable'}</p>
    <p>Distribution schedule: {run.sponsor.distribution_available ? 'Persisted' : 'Unavailable'} · {run.sponsor.distribution_source || 'Source unavailable'}</p>
    <SponsorSchedules run={run} />
    <EvidenceDisclosure project={project} run={run} source="Canonical returns projection and persisted sponsor / distribution schedules" />
  </section>;
}

export function CreditDashboard({ project, run }: { project: string; run: InsightRun }) {
  const convergence = run.credit.capacity.convergence as { converged?: boolean | null; note?: string; termination_reason?: { d?: string } } | undefined;
  return <section className="fi-run" aria-label={`Credit evidence for Run ${run.identity.history_id}`} data-selected-history={run.identity.history_id}>
    <div className="fi-panel"><h3>{run.identity.scenario} · {runStateLabel(run.identity.state)}</h3><p>{run.identity.ran_at} · Run {run.identity.history_id}</p>
      <EvidenceDisclosure project={project} run={run} source="Immutable Run History" />
      <p>Run Integrity: {run.credit.integrity.status}. {run.credit.integrity.reason}</p>
      <p>Numerical solver convergence: {convergence?.converged === true ? 'Converged' : convergence?.converged === false ? 'Not converged' : 'Unavailable'}.
        {' '}{convergence?.termination_reason?.d}</p>
      <p>{convergence?.note || 'Numerical convergence is separate from credit feasibility and contractual compliance.'}</p>
      <h3>Credit indicators</h3><MetricCards project={project} run={run} metrics={run.metrics} />
      <CreditEvidenceCards project={project} run={run} />
    </div>
    <section className="fi-panel"><h3>Credit findings</h3>
      {!run.credit.findings.length && <p>No credit findings available.</p>}
      {run.credit.findings.map(finding => <details className="fi-finding" key={finding.id}>
        <summary>{finding.title} · {finding.status}</summary><p>{finding.classification}</p><p>{finding.detail}</p>
        <p>Source: {finding.source} {finding.evidence_source}</p><p>Authority: {finding.authority || 'Unavailable'}</p>
        {finding.actual && <p>Observed: {finding.actual.d} {finding.actual.reason}</p>}
        {finding.threshold && <p>Threshold: {finding.threshold.d} {finding.threshold.reason}</p>}
        <EvidenceDisclosure project={project} run={run} source={finding.evidence_source || finding.source} limitation={finding.reason} />
      </details>)}
    </section>
    <CreditTimeline project={project} run={run} timeline={run.credit.timeline} />
    <SponsorEvidence project={project} run={run} />
  </section>;
}

/** Reusable presentation entry point, deliberately disconnected from the served workspace until #378 integration. */
export function FinancialInsightsView({ history, payload, selected, onSelection, onRead, busy, error }: {
  history: HistoryPayload; payload: InsightsPayload | null; selected: string[];
  onSelection: (ids: string[]) => void; onRead: () => void; busy?: boolean; error?: string;
}) {
  // Refuse evidence with a different project or a selection other than the explicit one.
  const matching = payload && payload.project.project_id === history.project.project_id
    && payload.runs.length === selected.length && payload.runs.every((run, index) => run.identity.history_id === selected[index]
      && run.metrics.every(metric => metric.history_id === run.identity.history_id && metric.snapshot_id === run.identity.snapshot_id
        && metric.scenario_id === run.identity.scenario_id));
  return <div className="fi-insights"><h2>Financial intelligence · {history.project.name}</h2>
    <p>Read-only analysis of committed Run evidence.</p>
    <HistoricalRunSelector history={history} selected={selected} onChange={onSelection} onRead={onRead} busy={busy} />
    {error && <p role="alert">{error}</p>}
    <div aria-live="polite">{busy ? 'Reading selected committed evidence…' : !matching ? 'Select committed Runs and read their evidence.' : ''}</div>
    {matching && payload && <><p>{payload.credit.policy?.disclosure}</p><ScenarioComparison payload={payload} />
      {payload.runs.map(run => <CreditDashboard key={run.identity.history_id} project={history.project.code} run={run} />)}</>}
  </div>;
}

/** Optional isolated data container. No automatic Run selection; requests are GET-only and uncached. */
export function FinancialInsights({ project }: { project: string }) {
  const [history, setHistory] = useState<HistoryPayload | null>(null);
  const [selected, setSelected] = useState<string[]>([]);
  const [payload, setPayload] = useState<InsightsPayload | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [request, setRequest] = useState<{ ids: string[]; sequence: number } | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    setHistory(null); setSelected([]); setPayload(null); setRequest(null); setError(''); setBusy(false);
    void fetchInsightsHistory(project, controller.signal).then(result => {
      if (controller.signal.aborted) return;
      if (result.ok) setHistory(result); else setError(friendlyMessage(result.code, result.message));
    }).catch(() => { /* Effect cancellation. */ });
    return () => controller.abort();
  }, [project]);
  useEffect(() => {
    if (!request) return;
    const controller = new AbortController();
    setBusy(true); setPayload(null); setError('');
    void fetchInsights(project, request.ids, controller.signal).then(result => {
      if (controller.signal.aborted) return;
      if (result.ok) setPayload(result); else setError(friendlyMessage(result.code, result.message));
      setBusy(false);
    }).catch(() => { if (!controller.signal.aborted) { setError('Evidence unavailable.'); setBusy(false); } });
    return () => controller.abort();
  }, [project, request]);
  if (!history || history.project.code !== project) return <div className="fi-insights" role="status">{error || 'Reading committed Run history…'}</div>;
  return <FinancialInsightsView history={history} payload={payload} selected={selected} busy={busy} error={error}
    onSelection={ids => { setSelected(ids); setPayload(null); }} onRead={() => setRequest(previous => ({ ids: [...selected], sequence: (previous?.sequence ?? 0) + 1 }))} />;
}

export type { RunReference };
