import { evidenceHref } from './presentation';
import type { RunReference } from './types';

export function EvidenceDisclosure({ project, run, source, unit, period, limitation }: {
  project: string; run: RunReference; source: string; unit?: string; period?: string; limitation?: string;
}) {
  const identity = run.identity;
  const fields = [['Project', project], ['Scenario', identity.scenario], ['Scenario ID', identity.scenario_id],
    ['Run / history ID', identity.history_id], ['Snapshot', identity.snapshot_id], ['Composite identity', identity.composite_hash],
    ['Run timestamp', identity.ran_at], ['Context', identity.state], ['Engine', identity.engine_version],
    ['Workbook', identity.workbook_version], ['Source', source], ['Unit', unit], ['Period', period]];
  return <details className="fi-evidence"><summary>Source and Run evidence</summary>
    <dl>{fields.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value || 'Unavailable'}</dd></div>)}</dl>
    {limitation && <p>{limitation}</p>}
    <div className="fi-links">{Object.entries(run.links).map(([label, href]) => evidenceHref(href)
      ? <a key={label} href={evidenceHref(href)}>{label.replace(/_/g, ' ')}</a> : null)}</div>
  </details>;
}
