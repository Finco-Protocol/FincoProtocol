import type { SheetFieldPayload, SheetFieldsPayload, WorkspacePayload } from '../../types';
import type { SaveAllCapability, SaveAllRequest } from '../../editing/saveAll';
import type { PendingEdit } from '../../editing/pendingEdits';
import { validateSheetField } from '../../workflow/SheetFieldsEditor';

export type EditingWorkspace = WorkspacePayload & { save_all?: SaveAllCapability & { excluded?: string[] } };
export type Block = 'terms' | 'repayment' | 'funding';
export const BLOCKS: ReadonlyArray<{ id: Block; label: string }> = [
  { id: 'terms', label: 'Structure & Terms' }, { id: 'repayment', label: 'Repayment & Covenants' }, { id: 'funding', label: 'Facilities / Funding' },
];
export const structured = (id: string) => id === 'debt.financing.instruments' || id === 'debt.bankability.configuration';
/** Grouping is presentation only. Eligibility is always the server's binding + capability. */
export function blockOf(f: SheetFieldPayload): Block {
  if (/sponsor|equity|shareholder|junior|financing\.instruments/.test(f.field_id)) return 'funding';
  return /dscr|llcr|tenor|grace|repayment|maturity|amortization|contract\./.test(f.field_id) ? 'repayment' : 'terms';
}
export function canEdit(f: SheetFieldPayload, w: EditingWorkspace, fields: SheetFieldsPayload): boolean {
  return w.save_all?.available === true && w.save_all.sections?.includes('cells') === true
    && !w.project.protected_reference && !fields.project.protected_reference && f.binding_label === 'bound'
    && f.field_id.startsWith('debt.') && !structured(f.field_id) && !w.save_all.excluded?.includes(f.field_id);
}
export function buildBlockRequest(w: EditingWorkspace, fields: SheetFieldsPayload, project: string, scenario: string | null,
  loadedHash: string, edits: PendingEdit[], id: string): SaveAllRequest {
  if (w.project.code !== project || fields.project.code !== project || w.workbook.scenario_id !== scenario
    || w.workbook.composite_hash !== fields.save.content_hash || w.workbook.version !== fields.save.workbook_version
    || loadedHash !== w.workbook.composite_hash) throw new Error('STALE: saved identity changed. Reload saved values; your draft is retained.');
  if (!edits.length || !w.save_all?.url || !w.save_all.csrf_token) throw new Error('This block has no available atomic Save contract.');
  const cells = edits.map(e => {
    const f = fields.fields.find(f => f.field_id === e.key);
    if (!f || !canEdit(f, w, fields) || e.section !== 'financing' || e.conflict || e.error
      || String(f.value ?? '') !== e.baseline) throw new Error('STALE: a field or permission changed. Reload and review the retained draft.');
    const problem = validateSheetField(f, e.value);
    if (problem) throw new Error(`${f.label}: ${problem}`);
    return { field_id: e.key, value: e.value };
  });
  return { project, scenario_id: scenario, content_hash: w.workbook.composite_hash, workbook_version: w.workbook.version,
    csrf_token: w.save_all.csrf_token, request_id: id, cells, contracts_json: null, cost_lines: [] };
}
