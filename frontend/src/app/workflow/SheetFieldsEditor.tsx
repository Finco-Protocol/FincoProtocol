// WF-React-2 — registry-sheet field editor (Project setup, Financing, Tax).
//
// One component over the canonical `GET /v2/model-react/fields/{sheet}`
// projection and the canonical per-field writer `POST /v2/workbook/update`.
// That writer accepts a single field per request (there is no atomic multi-field
// batch for registry sheets), so each field has its own Save / Cancel.  Fields
// labelled anything other than `bound` stay read-only with their reason; the
// server remains the validation authority.

import { useCallback, useEffect, useMemo, useState } from "react";
import { fetchSheetFields, saveWorkbookField } from "../api";
import { useOptionalChanges } from "../editing/ChangesProvider";
import { sectionOfField } from "../editing/fieldSection";
import type { EditSection } from "../editing/pendingEdits";
import type { SheetFieldPayload, SheetFieldsPayload } from "../types";
import { isIsoDate, parseStrictDecimal } from "./ModelWorkflowValidation";
import { BINDING_PLAIN, STRUCTURED_PLAIN, plainFieldHelp, plainOptionLabel } from "../plainCopy";
import {
  Field, LoadingNote, StatusNote, UnavailableNote, useCanonicalRead, useReportDirty, useReportPending, useSingleFlight,
  useUnresolvedLock, type StatusMessage,
} from "./workflowShared";

const NUMERIC = new Set(["float", "int", "keur", "pct", "bps", "years", "months", "mwh", "mw"]);
const INTEGER = new Set(["int", "years", "months"]);

const BINDING_REASON = BINDING_PLAIN;

/** Sheets whose scalar fields stage into the shared pending-change store (WS-2); other sheets keep their own drafts. */
const SHEET_SECTION: Partial<Record<Props["sheet"], EditSection>> = { project_setup: "inputs", debt: "financing" };
/** Field-id prefix of each staged sheet (the same field is one pending edit whichever editor staged it). */
const SHEET_PREFIX: Partial<Record<Props["sheet"], string>> = { project_setup: "project_setup.", debt: "debt." };

/** Structured configuration payloads owned by dedicated typed editors (Capital
 *  Stack proposal, bankability configuration).  They are stored as JSON documents;
 *  a free-text box would be raw JSON mutation, so they stay read-only here. */
const STRUCTURED_PAYLOAD_FIELDS = new Set(["debt.financing.instruments", "debt.bankability.configuration"]);
const STRUCTURED_REASON = STRUCTURED_PLAIN;

export function validateSheetField(field: SheetFieldPayload, value: string): string | null {
  const text = value.trim();
  if (text === "") return field.required ? "A value is required." : null;
  if (field.field_type === "date") return isIsoDate(text) ? null : "Use a real date in YYYY-MM-DD form.";
  if (field.field_type === "select") {
    return !field.options?.length || field.options.includes(text) ? null : "Choose one of the listed options.";
  }
  if (field.field_type === "bool") return text === "true" || text === "false" ? null : "Choose yes or no.";
  if (NUMERIC.has(field.field_type ?? "")) {
    const parsed = parseStrictDecimal(text);
    if (!parsed.ok) return parsed.message;
    if (INTEGER.has(field.field_type ?? "") && !Number.isInteger(parsed.value)) return "Enter a whole number.";
    if (field.min_value !== null && field.min_value !== undefined && parsed.value < field.min_value) return `The value cannot be below ${field.min_value}.`;
    if (field.max_value !== null && field.max_value !== undefined && parsed.value > field.max_value) return `The value cannot exceed ${field.max_value}.`;
  }
  return null;
}

interface Props {
  project: string;
  sheet: "project_setup" | "debt" | "revenue";
  title: string;
  /** Called after a verified Save so the workspace refreshes its Run freshness. */
  onSaved?: () => void;
  /** Bumped when ANY editor committed a change: re-read the CAS tokens and values. */
  reloadKey?: number;
}

export function SheetFieldsEditor({ project, sheet, title, onSaved, reloadKey = 0 }: Props) {
  const fetcher = useCallback(() => fetchSheetFields(project, sheet), [project, sheet]);
  const read = useCanonicalRead<SheetFieldsPayload>(fetcher, [project, sheet], [reloadKey]);
  const store = useOptionalChanges();
  const section = SHEET_SECTION[sheet];
  const staged = store && section ? store : null;
  const [localDrafts, setLocalDrafts] = useState<Record<string, string>>({});
  const storeDrafts = useMemo<Record<string, string>>(() => {
    if (!staged || !section) return {};
    return Object.fromEntries(staged.edits.filter((e) => e.key.startsWith(SHEET_PREFIX[sheet] ?? "\u0000")).map((e) => [e.key, e.value]));
  }, [staged, section, sheet]);
  const drafts = staged ? storeDrafts : localDrafts;
  const setDrafts = (update: (prev: Record<string, string>) => Record<string, string>) => setLocalDrafts(update);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [status, setStatus] = useState<StatusMessage | null>(null);
  const [inFlight, setInFlight] = useState<string | null>(null);
  const [locked, setLocked] = useUnresolvedLock(`sheet-${sheet}`);
  // The persisted value each draft was started from: a draft whose field changed
  // underneath it (another tab, another editor) is dropped, never rebased silently.
  const [baselines, setBaselines] = useState<Record<string, string>>({});

  useEffect(() => { setLocalDrafts({}); setErrors({}); setStatus(null); setBaselines({}); }, [project, sheet]);
  useReportDirty(`sheet-${sheet}`, Object.keys(drafts).length);
  useReportPending(`sheet-${sheet}`, inFlight !== null || locked);
  const singleFlight = useSingleFlight();

  const data = read.state === "ready" ? read.data : null;
  useEffect(() => {
    if (!data) return;
    if (staged && section) {
      // Staged edits live in the shared store: a moved baseline is FLAGGED there (conflict), never silently dropped or rebased.
      const mine = staged.edits.filter((e) => e.key.startsWith(SHEET_PREFIX[sheet] ?? "\u0000"));
      if (mine.length && staged.identity) {
        staged.rebase(staged.identity, Object.fromEntries(mine.map((e) => {
          const field = data.fields.find((f) => f.field_id === e.key);
          return [e.id, { value: String(field?.value ?? "") }];
        })));
      }
      return;
    }
    const lost = Object.keys(drafts).filter((id) => {
      const field = data.fields.find((f) => f.field_id === id);
      return !field || String(field.value ?? "") !== baselines[id];
    });
    if (!lost.length) return;
    setDrafts((prev) => { const next = { ...prev }; lost.forEach((id) => delete next[id]); return next; });
    setStatus({ tone: "conflict", text: `${lost.length} unsaved edit(s) were discarded because the saved value changed since you started editing. Review the reloaded value and edit again.` });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data]);
  const sections = useMemo(() => {
    const map = new Map<string, { label: string; fields: SheetFieldPayload[] }>();
    for (const field of data?.fields ?? []) {
      const id = field.section_id ?? "other";
      const entry = map.get(id) ?? { label: field.section_label ?? "Other", fields: [] };
      entry.fields.push(field);
      map.set(id, entry);
    }
    return Array.from(map.values());
  }, [data]);

  const setDraft = (field: SheetFieldPayload, value: string, persisted: string) => {
    const fieldId = field.field_id;
    if (staged && section) {
      staged.stage({ section: sectionOfField(fieldId), key: fieldId, label: field.label, unit: field.unit ?? "", baseline: persisted, value }, { coalesce: true });
      setErrors((prev) => { const next = { ...prev }; delete next[fieldId]; return next; });
      setStatus(null);
      return;
    }
    setBaselines((prev) => (fieldId in prev ? prev : { ...prev, [fieldId]: persisted }));
    setDrafts((prev) => {
      const next = { ...prev };
      if (value === persisted) delete next[fieldId]; else next[fieldId] = value;
      return next;
    });
    setErrors((prev) => { const next = { ...prev }; delete next[fieldId]; return next; });
    setStatus(null);
  };

  async function saveField(field: SheetFieldPayload) {
    if (locked || inFlight !== null) return;
    await singleFlight(() => runSaveField(field));
  }

  async function runSaveField(field: SheetFieldPayload) {
    if (!data) return;
    const value = drafts[field.field_id];
    if (value === undefined) return;
    const problem = validateSheetField(field, value);
    if (problem) {
      setErrors((prev) => ({ ...prev, [field.field_id]: problem }));
      setStatus({ tone: "error", text: `${field.label}: ${problem} Nothing was saved.` });
      return;
    }
    setInFlight(field.field_id);
    setStatus(null);
    const result = await saveWorkbookField({
      updateUrl: data.save.url, project, fieldId: field.field_id, value, sheetId: sheet,
      workbookVersion: data.save.workbook_version, contentHash: data.save.content_hash,
      csrfToken: data.save.csrf_token, financingCsrfToken: data.save.financing_csrf_token,
      verifyCommitted: async () => {
        const fresh = await fetchSheetFields(project, sheet);
        if (fresh.ok !== true) return false;
        const persisted = fresh.fields.find((f) => f.field_id === field.field_id);
        if (!persisted) return false;
        const a = String(persisted.value ?? "").trim(), b = value.trim();
        if (a === b) return true;
        const na = Number(a), nb = Number(b);
        return Number.isFinite(na) && Number.isFinite(nb) && na === nb;
      },
    });
    setInFlight(null);
    if ("kind" in result) {
      setLocked(true);
      setStatus({ tone: "conflict", text: result.message });
    } else if (result.ok) {
      setStatus({ tone: "ok", text: `${field.label} saved and ${result.verified ? "verified in the fresh projection" : "accepted"}. The results are now out of date (STALE); the model was not run.` });
      if (staged && section) staged.revert(`${sectionOfField(field.field_id)}:${field.field_id}`);
      else setDrafts((prev) => { const next = { ...prev }; delete next[field.field_id]; return next; });
      read.reload();
      onSaved?.();
    } else {
      // Server verdicts (including stale-content 409s) keep the typed draft on screen.
      setErrors((prev) => ({ ...prev, [field.field_id]: result.message }));
      setStatus({ tone: "error", text: result.message });
    }
  }

  if (read.state === "loading") return <LoadingNote label={`Loading ${title.toLowerCase()}…`} />;
  if (read.state === "error") return <UnavailableNote message={read.message} onRetry={read.reload} />;
  const protectedRef = read.data.project.protected_reference;
  const editable = (f: SheetFieldPayload) => f.binding_label === "bound" && !protectedRef && !STRUCTURED_PAYLOAD_FIELDS.has(f.field_id);
  const dirtyCount = Object.keys(drafts).length;

  return (
    <section className="fm-card fm-section wf-section" aria-label={title} data-sheet-editor={sheet}>
      <div className="fm-card-title">
        <h2>{title}</h2>
        <span className="rx-save-scope" data-save-scope={sheet}><strong>Saves:</strong> one field at a time</span>
        {dirtyCount > 0 && <span className="wf-dirty" data-unsaved={dirtyCount}>{dirtyCount} unsaved</span>}
      </div>
      {protectedRef && <div className="fm-banner" role="note"><span className="fm-demo-label">READ-ONLY TEMPLATE</span><span className="fm-banner-copy">Read-only. Start a project from this template to edit.</span></div>}
      {locked && <div className="fm-banner" role="alert"><span className="fm-demo-label">RECONCILE</span><span className="fm-banner-copy">The last save outcome is unknown. Reload the workspace before saving again.</span></div>}
      <StatusNote status={status} />
      {sections.map((section) => (
        <div key={section.label}>
          <p className="wf-group-head">{section.label}</p>
          <div className="wf-grid">
            {section.fields.map((field) => {
              const persisted = String(field.value ?? "");   // the registry projection may carry a JSON number
              const current = drafts[field.field_id] ?? persisted;
              const id = `wf-${sheet}-${field.field_id.replace(/[^a-z0-9]+/gi, "-")}`;
              const canEdit = editable(field);
              const dirty = drafts[field.field_id] !== undefined;
              const help = plainFieldHelp(field.field_id, field.help_text);
              return (
                <div key={field.field_id} data-field-binding={field.binding_label} data-dirty={dirty || undefined}>
                  <Field id={id} label={field.label} unit={field.unit ?? undefined} error={errors[field.field_id]}
                         hint={canEdit ? help.hint
                           : STRUCTURED_PAYLOAD_FIELDS.has(field.field_id) ? STRUCTURED_REASON
                             : BINDING_REASON[field.binding_label] ?? help.hint}>
                    {(p) => canEdit ? (
                      field.field_type === "select" && field.options?.length ? (
                        <select {...p} className="fm-input" value={current} disabled={locked || inFlight !== null}
                                onChange={(e) => setDraft(field, e.target.value, persisted)}>
                          {!field.options.includes(current) && <option value={current}>{current || "—"}</option>}
                          {field.options.map((o) => <option key={o} value={o}>{field.option_labels?.[o] ?? plainOptionLabel(field.field_id, o) ?? o}</option>)}
                        </select>
                      ) : (
                        <input {...p} className="fm-input" type="text" autoComplete="off"
                               inputMode={NUMERIC.has(field.field_type ?? "") ? "decimal" : undefined}
                               value={current} disabled={locked || inFlight !== null}
                               onChange={(e) => setDraft(field, e.target.value, persisted)}
                               onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); void saveField(field); } }} />
                      )
                    ) : (
                      <output {...p} className="fm-field-value">{field.display_value ?? field.value ?? "—"}</output>
                    )}
                  </Field>
                  {help.technical && (
                    <details className="rx-tech"><summary>Technical note</summary><p className="wf-hint">{help.technical}</p></details>
                  )}
                  {canEdit && dirty && (
                    <div className="fm-toolbar">
                      <button type="button" className="fm-btn fm-btn-primary" disabled={locked || inFlight !== null}
                              aria-label={`Save ${field.label}`} onClick={() => void saveField(field)}>
                        {inFlight === field.field_id ? "Saving…" : "Save"}
                      </button>
                      <button type="button" className="fm-btn" disabled={inFlight !== null} aria-label={`Cancel edit of ${field.label}`}
                              onClick={() => setDraft(field, persisted, persisted)}>Cancel</button>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      ))}
      <p className="fm-info-note" data-save-scope-note={sheet}>Each field has its own Save and saves on its own. If another change was saved in the meantime, your edit is kept on screen and you are asked to reload before saving again. Calculated and fixed fields cannot be edited. Saving never runs the model.</p>
    </section>
  );
}
