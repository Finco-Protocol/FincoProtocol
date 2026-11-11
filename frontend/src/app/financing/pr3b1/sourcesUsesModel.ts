import type { SuRow } from '../types';
import type { Evidence, Gate } from './types';
export function sourcesUsesModel(e: Evidence, gate: Gate) {
  if (!gate.showRun) return null;
  const su = e.studio.selected_run!.view!.sources_uses;
  const total = (label: string, row: unknown): SuRow => {
    if (row && typeof row === 'object' && 'value' in row) return row as SuRow;
    return { label, value: typeof row === 'number' && Number.isFinite(row) ? row : null,
      display: typeof row === 'number' ? String(row) : 'NOT AVAILABLE', reason: 'No server display/row metadata supplied.', authority: 'Last Run · sources_uses' };
  };
  return { sources: su.sources ?? [], uses: su.uses ?? [], totals: [total('Total Sources', su.total_sources), total('Total Uses', su.total_uses), total('Funding Residual', su.residual)],
    balance: su.balance_status ?? 'UNAVAILABLE', integrity: su.integrity ?? 'UNAVAILABLE', note: su.integrity_note,
    reason: su.su_authority_gap || su.funding_waterfall_reason,
    construction: su.construction_rows ?? [],
    // No sum and no unsupported per-facility assignment. One authoritative value per construction period.
    drawn: (su.construction_rows ?? []).map(row => ({ period: row.period, date: row.date, seniorDraw: row.fields.find(f => f.label === 'Senior draw') ?? null })) };
}
