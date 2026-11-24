import { useEffect, useState } from "react";
import { FriendlyError } from "../productLanguage";
import { groupDisplayName } from "../costGroupDisplay";
import { showKeur } from "../costAmounts";
import { useCostUnit } from "../CostUnit";
import { useReportPrecision } from "../ReportPrecision";

/** FINCO38 / PR-U2b — Inputs > OPEX > Years, per saved line with canonical annual OPEX exceptions.
 *  Server view model supplies escalated base + saved annual overrides (kEUR nominal); browser never
 *  invents financial outputs. Explicit 0 is distinct from blank/inherited; clearing restores inheritance.
 *  Save delegates to the canonical atomic CAS writer without running the model; refused Save preserves dirty edits. */
export type Series = Array<number | null>;
export interface LineRow {
  sub_line_id: string; business_code?: string; label: string; y1_keur: number; inflation_pct: number;
  values: Series; overridden_years?: number[]; source: "saved_line";
}
export interface DriverRow { label: string; values: Series; source: "technology_driver" }
export interface Group {
  code: string; name: string; derived: boolean; has_data: boolean; values: Series; lines: LineRow[]; drivers: DriverRow[];
  placeholder_rows_not_listed: number; reconciles: boolean | null;
}
interface Base { group: string; field_id: string; value: string; editable: boolean; used_by_run: boolean; note: string | null }
export interface AnnualExceptionEntry { line_key: string; year: number; amount_keur: number }
export interface AnnualExceptionsMeta {
  editable: boolean; base_token: string; content_hash: string; workbook_version: string;
  scenario_id: string | null; csrf_token: string | null; endpoint: string;
  overrides: AnnualExceptionEntry[];
}
export interface Payload {
  ok: true; unit: string; years: number[]; groups: Group[]; contingency: { rate_pct: number; by_year: Series };
  totals: { excluding_contingency: Series; including_contingency: Series }; bases: unknown; basis: string;
  annual_exceptions?: AnnualExceptionsMeta;
}
export type Failure = { code: string; message?: string };

export async function loadOpexLineYears(project: string, signal?: AbortSignal): Promise<Payload | Failure> {
  try {
    const r = await fetch(`/v2/model-react/opex-projection/lines?${new URLSearchParams({ project })}`, { credentials: "same-origin", cache: "no-store", headers: { Accept: "application/json" }, signal });
    const body = await r.json().catch(() => null) as (Payload | (Failure & { ok: false })) | null;
    if (r.ok && body && body.ok === true) return body;
    return { code: (body as Failure | null)?.code ?? `HTTP_${r.status}`, message: (body as Failure | null)?.message };
  } catch {
    return { code: "SERVER_UNREACHABLE" };
  }
}

export async function loadOpexAnnualEditor(project: string, signal?: AbortSignal): Promise<AnnualExceptionsMeta | null> {
  try {
    const r = await fetch(`/v2/model-react/opex-projection/annual-exceptions/editor?${new URLSearchParams({ project })}`, { credentials: "same-origin", cache: "no-store", headers: { Accept: "application/json" }, signal });
    const body = await r.json().catch(() => null) as (AnnualExceptionsMeta & { ok?: boolean }) | null;
    if (r.ok && body && body.ok === true && body.editable) return body;
    return null;
  } catch {
    return null;
  }
}

function baseRows(bases: unknown): Base[] {
  return Array.isArray(bases) ? (bases as Base[]) : [];
}

function cellKey(lineKey: string, year: number): string {
  return `${lineKey}::${year}`;
}

export function OpexLineYears({ project, reloadKey, onMutated }: { project: string; reloadKey: number; onMutated?: () => void }) {
  const [unit] = useCostUnit();
  const { precision } = useReportPrecision();
  const cell = (v: number | null | undefined) => (v === null || v === undefined || Number.isNaN(v) ? "—" : showKeur(v, unit, precision));
  const [data, setData] = useState<Payload | null>(null);
  const [editorMeta, setEditorMeta] = useState<AnnualExceptionsMeta | null>(null);
  const [failure, setFailure] = useState<Failure | null>(null);
  const [editing, setEditing] = useState(false);
  // Staged overrides: key -> string value ("" means revert to inherited)
  const [draftEdits, setDraftEdits] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saveNote, setSaveNote] = useState<string | null>(null);
  const [boundScope, setBoundScope] = useState<string>("");

  useEffect(() => {
    let live = true;
    setDraftEdits({});
    setSaveError(null);
    setSaveNote(null);
    setEditing(false);
    void Promise.all([loadOpexLineYears(project), loadOpexAnnualEditor(project)]).then(([r, ed]) => {
      if (!live) return;
      if ("years" in r) {
        setData(r);
        setFailure(null);
      } else {
        setFailure(r);
      }
      setEditorMeta(ed);
      const nextScope = `${project}::${ed?.scenario_id ?? ""}`;
      if (boundScope && boundScope !== nextScope) {
        setDraftEdits({});
        setSaveError(null);
        setSaveNote(null);
        setEditing(false);
      }
      setBoundScope(nextScope);
    });
    return () => { live = false; };
  }, [project, reloadKey]);

  if (failure) return <FriendlyError code={failure.code} message={failure.message} />;
  if (!data) return <p className="rx-boot-loading" role="status" data-opex-lines="loading">Loading OPEX lines by year…</p>;
  const bases = baseRows(data.bases);
  const meta = editorMeta;
  const canEdit = Boolean(meta?.editable && meta?.csrf_token);
  const savedMap: Record<string, number> = {};
  for (const ov of meta?.overrides ?? []) {
    savedMap[cellKey(ov.line_key, ov.year)] = ov.amount_keur;
  }
  const dirtyCount = Object.keys(draftEdits).length;

  async function handleSaveAnnual() {
    if (!meta || !canEdit || saving) return;
    setSaving(true);
    setSaveError(null);
    setSaveNote(null);
    try {
      const merged: Record<string, number> = { ...savedMap };
      for (const [k, raw] of Object.entries(draftEdits)) {
        const trimmed = raw.trim();
        if (trimmed === "") {
          delete merged[k];
        } else {
          const num = Number(trimmed);
          if (!Number.isFinite(num) || num < 0) {
            setSaveError(`Invalid kEUR amount "${raw}" — enter a finite number >= 0 or clear to inherit.`);
            setSaving(false);
            return;
          }
          merged[k] = num;
        }
      }
      const overrides: AnnualExceptionEntry[] = Object.entries(merged).map(([k, amount_keur]) => {
        const [line_key, yrStr] = k.split("::");
        return { line_key, year: Number(yrStr), amount_keur };
      });
      const resp = await fetch(meta.endpoint, {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({
          project,
          csrf_token: meta.csrf_token,
          workbook_version: meta.workbook_version,
          content_hash: meta.content_hash,
          scenario_id: meta.scenario_id,
          base_token: meta.base_token,
          overrides,
        }),
      });
      const body = await resp.json().catch(() => null) as { ok?: boolean; message?: string; code?: string } | null;
      if (!resp.ok || !body?.ok) {
        // Preserve dirty draftEdits on refusal (never silently discard)
        setSaveError(body?.message || `Save refused (${body?.code || resp.status}). Your edits are preserved.`);
        setSaving(false);
        return;
      }
      setDraftEdits({});
      setSaveNote("Annual OPEX overrides saved (Run not executed; Run model to refresh outputs).");
      const [fresh, freshEd] = await Promise.all([loadOpexLineYears(project), loadOpexAnnualEditor(project)]);
      if ("years" in fresh) setData(fresh);
      setEditorMeta(freshEd);
      onMutated?.();
    } catch {
      setSaveError("Network error while saving annual OPEX overrides. Your edits are preserved.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className="rx-card rcm-analysis" data-opex-lines="ready" aria-label="OPEX lines by year">
      <div className="cw-head">
        <h3>OPEX lines by year</h3>
        {canEdit && (
          <div data-opex-annual-controls="true" style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap", alignItems: "center" }}>
            <button type="button" className="fm-btn" data-opex-annual-toggle="true" onClick={() => { setEditing((v) => !v); setSaveError(null); }}>
              {editing ? "Done editing annual overrides" : "Edit annual overrides (kEUR)"}
            </button>
            {editing && dirtyCount > 0 && (
              <>
                <button type="button" className="fm-btn fm-btn-primary" data-opex-annual-save="true" disabled={saving} onClick={() => void handleSaveAnnual()}>
                  {saving ? "Saving…" : `Save annual overrides (${dirtyCount})`}
                </button>
                <button type="button" className="fm-btn" data-opex-annual-discard="true" disabled={saving} onClick={() => { setDraftEdits({}); setSaveError(null); }}>
                  Discard unsaved
                </button>
              </>
            )}
          </div>
        )}
      </div>
      <p className="rx-note" data-opex-lines-basis="true">{data.basis}</p>
      {editing && (
        <p className="rx-note" data-opex-annual-help="true">
          Enter nominal annual totals in <strong>kEUR</strong> to override a single operating year (explicit <code>0</code> overrides to zero; clear a cell to restore escalated inheritance).
        </p>
      )}
      {saveError && <p className="rx-error" role="alert" data-opex-annual-error="true">{saveError}</p>}
      {saveNote && <p className="rx-note" role="status" data-opex-annual-saved="true">{saveNote}</p>}
      <div className="rcm-scroll" tabIndex={0} role="region" aria-label="OPEX by saved line and year">
        <table className="fm-table rcux-opex-proj" data-opex-lines-table="true">
          <thead><tr><th scope="col">Line</th><th scope="col" className="fm-num">Escalation</th>{data.years.map((y) => <th key={y} scope="col" className="fm-num">Y{y}</th>)}</tr></thead>
          <tbody>
            {data.groups.filter((g) => !g.derived).map((g) => [
              <tr key={g.code} className="u2-opex-group" data-opex-line-group={g.code} data-opex-reconciles={g.reconciles === null ? "unknown" : String(g.reconciles)}>
                <th scope="row"><strong>{groupDisplayName(g.code, g.name)}</strong>{g.reconciles === false ? " — lines do not add up to the group; reload" : ""}</th>
                <td />
                {g.values.map((v, i) => <td key={i} className="fm-num"><strong>{cell(v)}</strong></td>)}
              </tr>,
              ...g.lines.map((l) => {
                const lineKey = l.business_code ?? l.sub_line_id;
                const ovSet = new Set(l.overridden_years ?? []);
                return (
                  <tr key={l.sub_line_id} data-opex-line={l.sub_line_id} data-opex-line-code={lineKey} data-opex-line-source="saved_line">
                    <th scope="row" className="u2-opex-line">{l.label}</th>
                    <td className="fm-num">{l.inflation_pct}%</td>
                    {l.values.map((v, i) => {
                      const yr = data.years[i];
                      const k = cellKey(lineKey, yr);
                      const isOverridden = ovSet.has(yr);
                      const staged = Object.prototype.hasOwnProperty.call(draftEdits, k) ? draftEdits[k] : undefined;
                      const effectiveState = staged !== undefined ? (staged.trim() === "" ? "inherited" : "override") : (isOverridden ? "override" : "inherited");
                      return (
                        <td key={i} className="fm-num" data-opex-annual-cell={`${lineKey}:${yr}`} data-opex-annual-state={effectiveState}>
                          {editing && canEdit ? (
                            <input
                              type="text"
                              inputMode="decimal"
                              aria-label={`${l.label} Year ${yr} nominal kEUR`}
                              data-opex-annual-input={`${lineKey}:${yr}`}
                              value={staged !== undefined ? staged : (isOverridden ? String(savedMap[k]) : "")}
                              placeholder={v === null || v === undefined ? "—" : String(Number(v.toFixed(2)))}
                              onChange={(e) => setDraftEdits((prev) => ({ ...prev, [k]: e.target.value }))}
                              style={{ width: "5.5rem", textAlign: "right", fontWeight: effectiveState === "override" ? 700 : 400 }}
                            />
                          ) : (
                            <span title={isOverridden ? "Explicit annual override (nominal kEUR)" : "Inherited escalated base"}>
                              {cell(v)}{isOverridden ? " *" : ""}
                            </span>
                          )}
                        </td>
                      );
                    })}
                  </tr>
                );
              }),
              ...g.drivers.map((d, n) => (
                <tr key={`${g.code}-d${n}`} data-opex-line-source="technology_driver">
                  <th scope="row" className="u2-opex-line">{d.label} <span className="rx-note">(from technology inputs, read-only)</span></th>
                  <td />
                  {d.values.map((v, i) => <td key={i} className="fm-num">{cell(v)}</td>)}
                </tr>)),
            ])}
            <tr data-opex-lines-row="contingency"><th scope="row">Applied contingency ({data.contingency.rate_pct.toFixed(1)}%)</th><td />{data.contingency.by_year.map((v, i) => <td key={i} className="fm-num">{cell(v)}</td>)}</tr>
            <tr data-opex-lines-row="total"><th scope="row">Total of line items</th><td />{data.totals.including_contingency.map((v, i) => <td key={i} className="fm-num"><strong>{cell(v)}</strong></td>)}</tr>
          </tbody>
        </table>
      </div>
      {bases.length > 0 && (
        <div data-opex-lines-bases="true">
          <h4>Group base amounts (Year 1, not in the rows above)</h4>
          <div className="rcm-scroll" tabIndex={0} role="region" aria-label="OPEX group base amounts">
          <table className="fm-table">
            <thead><tr><th scope="col">Group</th><th scope="col" className="fm-num">Year 1</th><th scope="col">Used by the Run</th></tr></thead>
            <tbody>
              {bases.map((b) => {
                const n = b.value === "" ? null : Number(b.value);
                return (
                  <tr key={b.field_id} data-opex-base={b.field_id} data-opex-base-used={b.used_by_run ? "true" : "false"}>
                    <th scope="row">{groupDisplayName(b.group, b.group)}</th>
                    <td className="fm-num">{n === null || !Number.isFinite(n) ? "—" : cell(n)}</td>
                    <td>{b.used_by_run ? "Yes, added when the model runs" : (b.note ?? "No")}</td>
                  </tr>);
              })}
            </tbody>
          </table>
          </div>
        </div>)}
    </section>
  );
}
