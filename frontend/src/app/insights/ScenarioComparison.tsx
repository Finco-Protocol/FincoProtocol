import { evidenceDisplay } from './presentation';
import type { InsightsPayload } from './types';
import { runIdentityText } from '../runIdentity';

export function ScenarioComparison({ payload }: { payload: InsightsPayload }) {
  return <section className="fi-panel"><h3>Committed Run KPI comparison</h3>
    <p>Reference: first explicitly selected Run. Changes are supplied by the canonical scenario comparison authority.</p>
    <div className="fi-table-scroll" tabIndex={0} role="region" aria-label="Scenario KPI comparison">
      <table><caption>Saved scenario KPIs · {payload.project.name}</caption><thead><tr><th scope="col">Metric</th><th scope="col">Unit</th>
        {payload.comparison.columns.map((identity, index) => <th scope="col" key={identity.history_id} data-snapshot-id={identity.snapshot_id}>{index === 0 ? 'Reference · ' : ''}{identity.scenario}<br />
          {identity.history_id}<br /><small>Run reference · {runIdentityText(identity.snapshot_id)}</small></th>)}<th scope="col">Data source</th></tr></thead>
        <tbody>{payload.comparison.rows.map(row => <tr key={row.key}><th scope="row">{row.label}</th><td>{row.unit || 'Unavailable'}</td>
          {payload.comparison.columns.map((identity, index) => <td key={identity.history_id} data-history-id={identity.history_id}>
            {evidenceDisplay(row.raw_values[index] ?? null, row.values[index], row.unit)}
            <small>{row.availability[index] || 'Unavailable'}</small><small>{row.sources?.[index] || row.source}</small>{index > 0 && <small>Change: {row.deltas[index] || 'Unavailable'}</small>}
          </td>)}<td className="fi-source">{row.source}</td></tr>)}</tbody></table>
    </div></section>;
}
