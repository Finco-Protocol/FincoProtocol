import type { Evidence } from './types';
import { checkRunEvidence } from './runEvidence';

const finite = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v);
/** Consistency checks only. Never repairs, allocates or creates a financial value. */
export function debtProvenance(e: Evidence) {
  const gate = checkRunEvidence(e);
  const run = gate.showRun ? e.credit.data?.runs[0] : undefined;
  const selected = gate.showRun ? e.studio.selected_run?.view : undefined;
  const dm = run?.debt_metrics;
  const rows = dm?.available ? dm.periods : [];
  const frequency = dm?.axis?.frequency ?? 'UNAVAILABLE';
  const ppy = ({ ANNUAL: 1, SEMIANNUAL: 2, QUARTERLY: 4, MONTHLY: 12 } as Record<string, number>)[frequency];
  let reason = gate.showRun ? '' : gate.reason;
  const dates = new Set<string>(), indexes = new Set<number>();
  if (!reason && (!rows.length || !ppy || dm?.axis?.periods_per_year !== ppy
      || dm?.axis?.period_count !== rows.length
      || selected?.repayment.axis?.frequency !== frequency
      || selected?.repayment.axis?.period_count !== rows.length
      || selected?.repayment.axis?.periods_per_year !== ppy
      || !selected?.repayment.rows.every(p => p.axis === 'RUN_DEBT_SERVICE_PERIOD')))
    reason = 'Native period axis is incomplete, mixed or unsupported.';
  for (let i = 0; !reason && i < rows.length; i++) {
    const p = rows[i], prev = rows[i - 1];
    if (!Number.isInteger(p.period_index) || !p.date || !/^\d{4}-\d{2}-\d{2}$/.test(p.date)
        || !Number.isFinite(Date.parse(p.date)) || new Date(p.date).toISOString().slice(0, 10) !== p.date
        || dates.has(p.date) || indexes.has(p.period_index)
        || (prev && (p.period_index !== prev.period_index + 1 || p.date <= (prev.date ?? p.date)))) {
      reason = 'Missing, duplicate or unordered native periods.'; break;
    }
    dates.add(p.date); indexes.add(p.period_index);
    if (frequency === 'MONTHLY' && (!Number.isInteger(p.year) || !Number.isInteger(p.period_in_year)
        || p.period_in_year! < 1 || p.period_in_year! > 12
        || (prev && (p.year! * 12 + p.period_in_year! !== prev.year! * 12 + prev.period_in_year! + 1
          || new Date(p.date).getUTCFullYear() * 12 + new Date(p.date).getUTCMonth()
            !== new Date(prev.date!).getUTCFullYear() * 12 + new Date(prev.date!).getUTCMonth() + 1)))) {
      reason = 'Missing or mixed monthly operating periods.'; break;
    }
    // Unknown values stay unknown. Validate identities only when all operands exist.
    const { senior_opening_keur: opening, principal_keur: principal, senior_closing_keur: closing,
      interest_keur: interest, debt_service_keur: service } = p;
    const values = [opening, principal, closing, interest, service];
    if (values.some(v => v != null && !finite(v))) { reason = 'Malformed native debt amount.'; break; }
    const close = (a: number, b: number) => Math.abs(a - b) <= 1e-6 + 16 * Number.EPSILON * Math.max(1, Math.abs(a), Math.abs(b));
    if ((finite(opening) && finite(principal) && finite(closing) && !close(opening - principal, closing))
        || (finite(principal) && finite(interest) && finite(service) && !close(principal + interest, service))
        || (prev && finite(prev.senior_closing_keur) && finite(opening) && !close(prev.senior_closing_keur, opening))) {
      reason = 'Native debt amounts do not reconcile. Reload source evidence.';
    }
  }
  const identity = run?.identity;
  const money = (v: unknown) => finite(v) ? String(v) : 'UNAVAILABLE';
  const requested = run?.structure.requested_gearing;
  const sized = run?.capacity.final_commitment;
  const last = !reason ? rows[rows.length - 1] : undefined;
  const concepts = [
    { label: 'Requested', value: finite(requested?.v) ? requested!.d : 'UNAVAILABLE', unit: 'ratio displayed as %', period: 'Selected Run input', source: 'credit.structure.requested_gearing', coverage: 'Aggregate Senior target; no requested cash amount' },
    { label: 'Sized', value: money(sized?.v), unit: 'kEUR', period: 'Selected Run sizing', source: 'credit.capacity.final_commitment', coverage: 'Aggregate Senior; no per-facility allocation' },
    { label: 'Committed', value: 'UNAVAILABLE', unit: 'kEUR', period: 'UNAVAILABLE', source: 'No independent legal commitment source', coverage: 'No independently persisted lender commitment' },
    { label: 'Drawn', value: money(selected?.construction?.fc_senior_draw?.unit === 'kEUR' ? selected.construction.fc_senior_draw.value : null), unit: 'kEUR', period: 'FC/COD only', source: selected?.construction?.fc_senior_draw?.source ?? 'UNAVAILABLE', coverage: 'Aggregate Senior FC/COD draw only; construction draws shown separately below' },
    { label: 'Outstanding', value: money(last?.senior_closing_keur), unit: 'kEUR', period: last ? `Closing · ${last.date} · period ${last.period_index}` : 'UNAVAILABLE', source: 'debt_metrics.periods[].senior_closing_keur', coverage: 'Aggregate Senior; no construction or per-instrument ledger' },
  ];
  return { gate, identity, concepts, periods: reason ? [] : rows, reason,
    frequency,
    monthly: 'MONTHLY_SCHEDULE_NOT_AVAILABLE',
    monthlyReason: 'No accepted monthly instrument repayment contract. Any supplied native aggregate periods remain aggregate Senior, without interpolation or facility allocation.',
    source: 'Selected committed Run · debt_metrics.periods · kEUR · aggregate Senior' };
}
