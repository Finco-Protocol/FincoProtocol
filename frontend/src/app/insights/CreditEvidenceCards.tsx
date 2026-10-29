import { useReportPrecision } from "../ReportPrecision";
import { EvidenceDisclosure } from './EvidenceDisclosure';
import { evidenceDisplay, evidenceUnitLabel } from './presentation';
import type { EvidenceCell, InsightRun } from './types';

/** Select approved projection cells verbatim. No new aggregation, ratio, threshold, or financial authority. */
const CAPACITY: [string, string, string][] = [
  ['dscr_debt_capacity', 'DSCR debt capacity', 'kEUR'], ['gearing_debt_capacity', 'Gearing debt capacity', 'kEUR'],
  ['final_commitment', 'Final senior commitment', 'kEUR'], ['binding_constraint', 'Binding sizing constraint', 'text'],
  ['debt_service_total', 'Senior debt service', 'kEUR'], ['principal_total', 'Senior principal', 'kEUR'],
  ['interest_total', 'Senior interest', 'kEUR'], ['base_cfads_total', 'Base CFADS', 'kEUR'],
  ['bank_cfads_total', 'Lender / sizing CFADS', 'kEUR'], ['cfads_statement_total', 'Statement CFADS', 'kEUR'],
];
const STRUCTURE: [string, string, string][] = [
  ['commitment', 'Senior debt commitment', 'kEUR'], ['actual_gearing', 'Actual funded gearing', '%'],
  ['requested_gearing', 'Requested gearing cap', '%'], ['total_uses', 'Total project uses', 'kEUR'],
  ['sponsor_contributed', 'Total sponsor investment', 'kEUR'], ['equity_sources', 'Equity funding sources', 'kEUR'],
  ['shl_cash', 'Shareholder loan cash contribution', 'kEUR'],
];
const RESERVE: [string, string, string][] = [
  ['initial_dsra_funding', 'Initial DSRA funding', 'kEUR'], ['dsra_peak_balance', 'Peak DSRA balance', 'kEUR'],
  ['dsra_final_balance', 'Final DSRA balance', 'kEUR'], ['regime', 'Reserve instrument', 'text'],
];
function asCell(value: unknown): EvidenceCell | null {
  return value && typeof value === 'object' && 'v' in value && 'd' in value ? value as EvidenceCell : null;
}
export function CreditEvidenceCards({ project, run }: { project: string; run: InsightRun }) {
  const { precision } = useReportPrecision();
  const reserve = run.credit.structure.reserve as Record<string, unknown> | undefined;
  const items = [
    ...CAPACITY.map(([key, label, unit]) => ({ key, label, unit, cell: asCell(run.credit.capacity[key]), source: `Credit Decision · capacity.${key}` })),
    ...STRUCTURE.map(([key, label, unit]) => ({ key, label, unit, cell: asCell(run.credit.structure[key]), source: `Credit Decision · structure.${key}` })),
    ...RESERVE.map(([key, label, unit]) => ({ key, label, unit, cell: asCell(reserve?.[key]), source: `Credit Decision · structure.reserve.${key}` })),
  ];
  return <><h3>Debt capacity, service and reserves</h3><div className="fi-metrics">{items.map(item => {
    const numeric = typeof item.cell?.v === 'number' ? item.cell.v : null;
    const text = item.unit === 'text';
    const available = text ? typeof item.cell?.v === 'string' : numeric !== null;
    return <article className="fi-metric" key={item.key} data-credit-cell={item.key}>
      <h4>{item.label}</h4><p className="fi-metric-value">{text ? item.cell?.d || 'Unavailable' : evidenceDisplay(numeric, item.cell?.d || '', item.unit, precision)} <small>{text ? '' : evidenceUnitLabel(numeric, item.cell?.d || '', item.unit)}</small></p>
      <p className="fi-meta">{item.cell?.basis || 'Saved credit results'} · Run {run.identity.history_id}</p>
      {!available && <p>{item.cell?.reason || 'Not available in this Run.'}</p>}
      <EvidenceDisclosure project={project} run={run} source={item.source} unit={item.unit} period={item.cell?.basis || 'Committed Run'} limitation={item.cell?.reason} />
    </article>;
  })}</div></>;
}
