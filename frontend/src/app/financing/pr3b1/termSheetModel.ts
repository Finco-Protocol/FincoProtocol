import type { CreditCell } from '../../credit/types';
import type { EvidenceMetric } from '../types';
import type { Evidence, Gate } from './types';
export interface Term { label: string; display: string; source: string; reason?: string }
export interface TermGroup { label: string; rows: Term[] }
export const creditTerm = (label: string, c: CreditCell | undefined, source: string): Term => ({ label,
  display: c?.v == null ? 'NOT AVAILABLE' : c.d, source, reason: c?.reason });
export const metricTerm = (m: EvidenceMetric): Term => ({ label: m.label, display: m.value == null ? 'NOT AVAILABLE' : m.display, source: m.source, reason: m.reason });
export function termSheetModel(e: Evidence, gate: Gate): TermGroup[] {
  const s = e.studio, run = gate.showRun ? e.credit.data?.runs[0] : undefined;
  const runLabel = gate.state === 'HISTORICAL' ? 'Historical Run' : 'Last Run';
  const detail = (names: string[]) => s.senior_detail_rows.filter(([k]) => names.includes(k)).map(([label, display]) => ({
    label, display: display ?? 'NOT AVAILABLE', source: 'Working Copy · model information; not new Run verification' }));
  const workingGearing = e.fields.fields.find(f => f.field_id === 'debt.senior.gearing_pct');
  const absent = (label: string, reason: string): Term => ({ label, display: 'NOT AVAILABLE', reason, source: 'Last Run' });
  return [
    { label: 'Size', rows: [creditTerm(`Requested gearing · ${runLabel}`, run?.structure.requested_gearing, `${runLabel} · structure.requested_gearing`),
      { label: 'Requested gearing · Working Copy', display: workingGearing?.value == null ? 'NOT AVAILABLE' : workingGearing.display_value ?? 'NOT AVAILABLE', source: 'Working Copy · debt.senior.gearing_pct (%)' },
      creditTerm('Senior commitment (sized)', run?.capacity.final_commitment, 'Last Run · capacity.final_commitment (kEUR)'),
      { label: 'Independently committed', display: 'UNAVAILABLE — no independently evidenced lender commitment',
        reason: 'Sized aggregate is not a separately persisted individual lender commitment.', source: 'Contract limitation' }] },
    { label: 'Pricing', rows: detail(['All-in interest rate', 'Base rate', 'Margin']).concat([
      { label: 'Pricing authority', display: s.senior_pricing_mode, source: 'Working Copy · all-in rate authoritative; base/margin informational' }]) },
    { label: 'Tenor', rows: run ? [
      creditTerm('First debt service', run.structure.tenor?.first_debt_service_date, 'Last Run · structure.tenor.first_debt_service_date'),
      creditTerm('Last debt service', run.structure.tenor?.last_debt_service_date, 'Last Run · structure.tenor.last_debt_service_date'),
      creditTerm('Contractual maturity', run.structure.tenor?.contractual_maturity_date, 'Last Run · structure.tenor.contractual_maturity_date')]
      : [absent('Debt service dates', gate.reason)] },
    { label: 'Repayment', rows: detail(['Amortization']) },
    { label: 'Fees', rows: detail(['Commitment fee', 'Arrangement fee', 'Structuring fee']) },
    { label: 'Covenants', rows: detail(['Lock-up DSCR', 'Minimum LLCR']) },
    { label: 'Reserves', rows: detail(['DSRA coverage']).concat([{ label: 'Reserve support', display: s.reserve_view.support, source: 'Working Copy · reserve policy' }, metricTerm(s.reserve_view.requirement)]) },
    { label: 'Sponsor', rows: [...s.sponsor_view.equity, ...s.sponsor_view.other, ...s.sponsor_view.shl].map(metricTerm) },
  ];
}
