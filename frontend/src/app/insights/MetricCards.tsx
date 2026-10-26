import { evidenceDisplay, evidenceUnitLabel } from './presentation';
import { EvidenceDisclosure } from './EvidenceDisclosure';
import type { Metric, RunReference } from './types';

export function MetricCards({ project, run, metrics }: { project: string; run: RunReference; metrics: Metric[] }) {
  return <div className="fi-metrics">{metrics.map(metric => {
    const available = metric.raw_value !== null && Number.isFinite(metric.raw_value);
    return <article className="fi-metric" key={metric.key} data-metric={metric.key} data-available={available}
      data-history-id={metric.history_id} data-snapshot-id={metric.snapshot_id} data-raw-value={available ? metric.raw_value! : undefined}>
      <h4>{metric.label}</h4><p className="fi-metric-value">{evidenceDisplay(metric.raw_value, metric.display_value, metric.unit)} <small>{evidenceUnitLabel(metric.raw_value, metric.display_value, metric.unit)}</small></p>
      <p className="fi-meta">{metric.availability} · {metric.period} · Run {metric.history_id}</p>
      {!available && <p>{metric.reason || 'This Run did not persist authoritative evidence.'}</p>}
      <p className="fi-source">{metric.source}</p>
      <EvidenceDisclosure project={project} run={run} source={metric.source} unit={metric.unit} period={metric.period} limitation={metric.reason} />
    </article>;
  })}</div>;
}
