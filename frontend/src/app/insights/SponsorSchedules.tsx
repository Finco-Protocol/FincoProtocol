import { evidenceDisplay } from './presentation';
import type { InsightRun } from './types';

// Exact approved sheet_returns.html component fields, in canonical order.
// No sum, waterfall calculation, distribution-to-sponsor substitution, or annual mapping.
const SPONSOR_FIELDS = [
  ['share_capital_contribution_keur', 'Share capital'], ['share_premium_contribution_keur', 'Share premium'],
  ['other_committed_equity_contribution_keur', 'Other committed equity'], ['additional_equity_contribution_keur', 'Additional equity'],
  ['shl_cash_interest_receipt_keur', 'SHL cash interest received'], ['shl_principal_receipt_keur', 'SHL principal received'],
  ['legal_equity_distribution_keur', 'Legal equity distribution'],
] as const;
const DISTRIBUTION_FIELDS = [
  ['distribution_keur', 'Distribution'], ['cum_distribution_keur', 'Cumulative distribution'],
  ['cf_after_reserves_keur', 'Cash after reserves'], ['dsra_balance_keur', 'DSRA balance'],
  ['dsra_contribution_keur', 'DSRA contribution'], ['mra_balance_keur', 'MRA balance'],
  ['mra_contribution_keur', 'MRA contribution'], ['lockup_active', 'Lock-up'],
] as const;
export function SponsorSchedules({ run }: { run: InsightRun }) {
  const schedules = [
    { title: 'Sponsor cash flow components', source: run.sponsor.sponsor_source, rows: run.sponsor.sponsor_rows, fields: SPONSOR_FIELDS },
    { title: 'Distribution waterfall evidence', source: run.sponsor.distribution_source, rows: run.sponsor.distribution_rows, fields: DISTRIBUTION_FIELDS },
  ];
  return <>{schedules.map(schedule => <details className="fi-evidence" key={schedule.title}>
    <summary>{schedule.title}</summary><p>Run {run.identity.history_id} · {schedule.source || 'Source unavailable'} · monetary values in kEUR</p>
    {!schedule.rows.length ? <p>No persisted period evidence available.</p> : <div className="fi-table-scroll" tabIndex={0} role="region" aria-label={schedule.title}>
      <table><caption>{schedule.title} · persisted model periods · kEUR</caption><thead><tr><th scope="col">Persisted period</th><th scope="col">Persisted date</th>
        {schedule.fields.map(([key, label]) => <th scope="col" key={key}>{label}</th>)}</tr></thead>
        <tbody>{schedule.rows.map((row, index) => <tr key={index}><th scope="row">{typeof row.period === 'number' ? row.period : 'Period unavailable'}</th>
          <td>{typeof row.date === 'string' ? row.date : 'Date unavailable'}</td>
          {schedule.fields.map(([key]) => { const value = typeof row[key] === 'number' ? row[key] as number : null;
            return <td key={key} data-source-field={key}>{key === 'lockup_active' ? row[key] === true ? 'Active' : row[key] === false ? 'Open' : 'Unavailable' : evidenceDisplay(value, '', 'kEUR')}</td>;
          })}</tr>)}</tbody></table>
    </div>}
  </details>)}</>;
}
