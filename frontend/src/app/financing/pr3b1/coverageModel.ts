import type { Evidence, Gate } from './types';
const severity: Record<string, number> = { CRITICAL: 0, HIGH: 1, MEDIUM: 2, LOW: 3, INFORMATION: 4, ERROR: 1, FAIL: 1, WARNING: 2, WARN: 2, INFO: 3, OK: 4 };
export function coverageModel(e: Evidence, gate: Gate) {
  if (!gate.showRun) return null;
  const r = e.credit.data!.runs[0], dm = r.debt_metrics;
  const findings = e.credit.data!.findings.filter(f => f.run_history_id === r.identity.history_id);
  const group = (classes: string[]) => findings.filter(f => classes.includes(f.classification) || classes.includes(f.metric))
    .sort((a, b) => (severity[a.severity ?? ''] ?? 5) - (severity[b.severity ?? ''] ?? 5));
  return { integrity: r.integrity, integrityFindings: group(['SOURCES_USES', 'ACCOUNTING_INTEGRITY', 'PROVENANCE']),
    otherFindings: findings.filter(f => !['SOURCES_USES', 'ACCOUNTING_INTEGRITY', 'PROVENANCE', 'SENIOR_DEBT', 'CASH_LIQUIDITY'].includes(f.classification) && !['SOURCES_USES', 'ACCOUNTING_INTEGRITY', 'PROVENANCE', 'SENIOR_DEBT', 'CASH_LIQUIDITY'].includes(f.metric)),
    bankabilityFindings: group(['SENIOR_DEBT', 'CASH_LIQUIDITY']), capacity: r.capacity,
    debtMetrics: dm, periods: dm?.available ? dm.periods : [],
    // Aggregate binding is not assigned to individual facilities.
    bindingScope: 'Aggregate Senior only; no per-tier binding conclusion',
    outstanding: dm?.available ? dm.periods.map(p => ({ period: p.period_index, date: p.date, opening: p.senior_opening_keur, closing: p.senior_closing_keur })) : [] };
}
