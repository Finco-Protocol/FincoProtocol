import type { Evidence } from './types';
import { debtProvenance } from './debtProvenanceModel';

export function DebtProvenance({ evidence }: { evidence: Evidence }) {
  const m = debtProvenance(evidence);
  return <details data-f04-debt-provenance="true" open><summary>Requested / Sized / Committed / Drawn / Outstanding</summary>
    <p>Aggregate Senior evidence · {m.gate.state}. Facility terms do not prove individual Run allocations.</p>
    {m.identity && <small>Run {m.identity.history_id} · snapshot {m.identity.snapshot_id} · fingerprint {m.identity.composite_hash} · scenario {m.identity.scenario_id ?? 'Base'}</small>}
    <div className="pr3b1-scroll" tabIndex={0} role="region" aria-label="Debt quantity provenance"><table>
      <thead><tr>{['Quantity', 'Value', 'Unit', 'Period / coverage', 'Source'].map(h => <th scope="col" key={h}>{h}</th>)}</tr></thead>
      <tbody>{m.concepts.map(c => <tr key={c.label}><th scope="row">{c.label}</th><td>{c.value}</td><td>{c.unit}</td><td>{c.period}<small>{c.coverage}</small></td><td>{c.source}</td></tr>)}</tbody>
    </table></div>
    <p>{m.monthly} · {m.monthlyReason}</p>
    {m.reason && <p>Native repayment evidence · UNAVAILABLE · {m.reason}</p>}
  </details>;
}
