export interface ImportFailure { ok: false; code: string; message?: string }

export interface ImportField { id: string; label: string; unit: string }
export interface ImportContext {
  ok: true; project: { code: string; name: string }; csrf_token: string; content_hash: string; workbook_version: string; scenario_id: string;
  limits: { max_upload_bytes: number; formats: string[]; max_proposals: number; max_approved: number; encodings: string[] };
  fields: ImportField[];
  semantics: { reads_file_in_memory_only: boolean; file_is_stored: boolean; apply_runs_the_model: boolean; apply_marks_results_stale: boolean };
}

export type RowStatus = "ready" | "needs_review" | "unchanged" | "invalid" | "unsupported" | "unsupported_for_apply";
export interface ImportRow {
  id: number; sheet: string; section: string; source_cell: string; label: string; original_value: string; source_unit: string | null;
  field_id: string | null; normalized_value: string | null; current_value: string | number | null; mapping_method: string; confidence_class: string;
  explanation: string[]; category: string; status: RowStatus; reason: string | null; duplicate_target: boolean; bulk_selectable: boolean;
  manual_scalar_mapping_allowed: boolean; owner_editor: string | null;
}
export interface ImportPreview {
  ok: true; stage: "review"; detected: number; totals: Record<string, number>; digest: string; preview_ticket: string;
  content_hash: string; workbook_version: string; categories: string[]; category_counts: Record<string, number>;
  counts: { exact: number; ambiguous: number; bulk_selectable: number; attention: number }; rows: ImportRow[];
}
export interface ApprovedRow {
  source_id: number; sheet: string; cell: string; label: string; field_id: string; value: string; unit: string; original_value: string;
  current_value: string | null; changed: boolean; normalization: string; corrections: string[]; correction_note: string;
  extracted_unit: string; chosen_unit: string; canonical_unit: string;
}
export interface ImportConfirm {
  ok: true; stage: "confirm"; approved_ticket: string; approved: ApprovedRow[]; approved_count: number; changed_count: number; unchecked_count: number;
}
export interface SavedRow {
  field_id: string; source: string; label: string; original_value: string; source_unit: string | null; normalization: string;
  previous_value: string | number | null; actual_value: string | number | null; approved_value: string; corrections: string[]; correction_note: string;
}
export interface ImportResult {
  ok: true; stage: "result"; saved: SavedRow[]; applied_count: number; skipped_count: number; freshness: string; approved_at: string | null;
  transaction_identity: string | null; semantics: { model_was_run: boolean; note: string };
}
/** The user's decision for one row of the review table. */
export interface RowChoice { keep: boolean; field: string; unit: string; manual: string }
