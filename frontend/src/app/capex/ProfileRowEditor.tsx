import { useEffect, useRef, useState } from "react";
import { useCapexProfileDraft } from "./ProfileDraftProvider";
import { emptyProfileRow, explicitInputText, explicitValues, editMonth, pasteMonths, sameDraftRow, SHAPE_LABEL } from "./profileDraft";
import { checkExplicit, parsePercentages, padWithZeros, trimTrailingZeros, type CommaMode } from "./profileImport";
import { isUserLineKey } from "./profileFocus";

export function ProfileShapeSelect({ itemKey, label }: { itemKey: string; label: string }) {
  const c = useCapexProfileDraft(false);
  const row = (c.scopeMismatch ? c.saved[itemKey] : c.draft[itemKey]) ?? emptyProfileRow();
  return <select value={row.shape} disabled={!c.editable(itemKey)} data-capex-shape={itemKey} data-pr2b-shape={itemKey}
    title={SHAPE_LABEL[row.shape] ?? "Model default — no override"} aria-label={`Shape for ${label}`} onChange={e => c.changeShape(itemKey, e.target.value)}>
    <option value="">Model default — no override</option>
    {c.data?.shapes.map(shape => <option key={shape} value={shape}>{SHAPE_LABEL[shape] ?? shape}</option>)}
  </select>;
}

export function ProfileDraftNotice() {
  const c = useCapexProfileDraft(false);
  return <div className="pr2b-notice" data-pr2b-draft-state={!c.data ? c.loadError ? "unavailable" : "loading" : c.locked ? "unknown" : c.scopeMismatch ? "scope-mismatch" : c.dirtyCount ? "unsaved" : "saved"}>
    <p><strong>{c.dirtyCount ? `Unsaved profile — ${c.dirtyCount} item(s)` : !c.data ? c.loadError ? "Not available — profile inputs could not be loaded" : "Loading profile inputs…" : "Saved profile inputs"}</strong>. Profile Save is separate from line amounts/comments and never runs the model.</p>
    {c.loadError && <p role="alert">{c.loadError}</p>}
    {c.stale && <p role="alert" data-pr2b-stale="true">{c.stale}</p>}
    {c.scopeMismatch && <details data-pr2b-retained-draft="true"><summary>Review the retained draft from its original project/scenario</summary>
      <p>These are retained draft inputs, not the current project's saved values.</p>
      <p>Retained from {c.baseline?.project.name} · {c.baseline?.edit.base_case ? "Base case" : "previous scenario"}.</p>
      <ul>{Object.entries(c.draft).filter(([, row]) => row.shape).map(([key, row]) => <li key={key}>{c.baseline?.items.find(i => i.item_key === key)?.label ?? "Retired item"} · {SHAPE_LABEL[row.shape] ?? "Profile"}
        {row.shape === "EXPLICIT" ? ` · ${explicitInputText(row.explicit)} %` : row.shape === "MILESTONE" ? ` · M${row.milestone}` : ""}</li>)}</ul></details>}
    {c.data && !c.data.edit.allowed && <p data-capex-readonly="true">{c.data.edit.reason}</p>}
    {c.locked && <p role="alert">UNKNOWN outcome — profile controls stay locked. Read-back does not retry the save.</p>}
    {c.status && <p className={`rx-status ${c.status.tone === "ok" ? "rx-status-ok" : "rx-status-error"}`} role={c.status.tone === "ok" ? "status" : "alert"} data-capex-status={c.status.tone}>{c.status.text}</p>}
    {c.error && <p role="alert" data-capex-error={c.error.code}>{c.error.message} ({c.error.code})</p>}
  </div>;
}

export function ProfileDraftActions() {
  const c = useCapexProfileDraft(false);
  const blocked = c.readOnly || c.externalPending || Boolean(c.stale) || !c.data || c.problems.length > 0 || Boolean(c.data.saved.error);
  return <div className="pr2b-actions">
    <button type="button" className="rx-button" data-capex-save="true" data-capex-save-blocked={c.problems.length > 0 || undefined}
      disabled={blocked || (!c.dirtyCount && !c.orphans.length)} onClick={() => void c.save("save")}
      title="Saves the whole profile document only, not staged line amounts or comments">Save profile to the project{c.dirtyCount ? ` (${c.dirtyCount} item${c.dirtyCount === 1 ? "" : "s"} changed)` : ""}</button>
    <button type="button" className="rx-button rx-button-secondary" data-capex-preview="true" disabled={Boolean(c.busy) || c.locked || c.scopeMismatch || !c.specNow || !c.keys.some(k => c.draft[k]?.shape)} onClick={() => void c.runPreview()}>Preview monthly allocation (nothing saved)</button>
    <button type="button" className="rx-button rx-button-secondary" data-capex-undo="true" disabled={c.readOnly || !c.history.length} onClick={c.undo}>Undo profile change</button>
    <button type="button" className="rx-button rx-button-secondary" data-capex-redo="true" disabled={c.readOnly || !c.future.length} onClick={c.redo}>Redo profile change</button>
    <button type="button" className="rx-button rx-button-secondary" data-capex-discard="true" disabled={Boolean(c.busy) || c.locked || !c.dirtyCount} onClick={c.discard}>Discard profile changes</button>
    {(c.stale || c.locked || c.loadError) && <button type="button" className="rx-button rx-button-secondary" data-pr2b-reconcile="true" disabled={Boolean(c.busy)} onClick={() => void c.reconcile()}>Read back / reconcile retained draft</button>}
    {c.problems.length > 0 && c.dirtyCount > 0 && <p role="alert" data-capex-save-blocked-reason="true">Save is blocked: {c.problems.map(p => p.message).join(" ")}</p>}
  </div>;
}

/** Both surfaces bind these controls to the same raw draft. No cell owns a second schedule. */
export function ProfileRowEditor({ itemKey, label, showShape = true, monthsInitiallyOpen = true, inline = false }: {
  itemKey: string; label: string; showShape?: boolean; monthsInitiallyOpen?: boolean; inline?: boolean;
}) {
  const c = useCapexProfileDraft(false);
  const [monthsOpen, setMonthsOpen] = useState(monthsInitiallyOpen);
  const [importer, setImporter] = useState<{ text: string; mode?: CommaMode; at: number | null } | null>(null);
  const [fileError, setFileError] = useState("");
  const importDialog = useRef<HTMLDialogElement>(null);
  const root = useRef<HTMLDivElement>(null);
  useEffect(() => { if (importer && !importDialog.current?.open) importDialog.current?.showModal(); else if (!importer && importDialog.current?.open) importDialog.current.close(); }, [Boolean(importer)]);
  if (!c.data) return <p role="status">{c.loadError || "Loading the canonical profile inputs…"}</p>;
  if (!c.data.items.some(i => i.item_key === itemKey)) return <p data-pr2b-unavailable={itemKey}>Not available: this line is not an eligible saved positive-amount CAPEX item.</p>;
  const row = (c.scopeMismatch ? c.saved[itemKey] : c.draft[itemKey]) ?? emptyProfileRow();
  const parsed = explicitValues(row.explicit);
  const values = row.explicit.kind === "cells" ? row.explicit.values : parsed.status === "ok" ? parsed.values : [];
  const check = parsed.status === "ok" ? checkExplicit(parsed.values, c.data.months) : null;
  const disabled = !c.editable(itemKey);
  const changed = !c.scopeMismatch && !sameDraftRow(row, c.saved[itemKey] ?? emptyProfileRow());
  const pasted = importer ? parsePercentages(importer.text, importer.mode) : null;
  const importCheck = pasted?.status === "ok" ? checkExplicit(pasted.values, c.data.months) : null;
  const openImport = (text = "", at: number | null = null) => { setFileError(""); setImporter({ text, at }); };
  return <div ref={root} className="pr2b-editor" data-pr2b-editor={itemKey} data-pr2b-input-source="unsaved-profile-draft" data-pr2b-row-state={changed ? "unsaved" : "saved"}
    onKeyDown={e => {
      e.stopPropagation();
      if (e.ctrlKey || e.metaKey) {
        if (e.key.toLowerCase() === "z") { e.preventDefault(); if (e.shiftKey) c.redo(); else c.undo(); }
        if (e.key.toLowerCase() === "y") { e.preventDefault(); c.redo(); }
      }
    }} onPaste={e => e.stopPropagation()}>
    <div className="pr2b-row-heading">{showShape && <label>Payment profile <ProfileShapeSelect itemKey={itemKey} label={label} /></label>}
      <span className="rcm-badge">{changed ? "UNSAVED PROFILE" : "SAVED PROFILE INPUTS"}</span></div>
    {isUserLineKey(itemKey) && <p className="rx-note" data-capex-user-line={itemKey}>A line you added: its profile is kept under the line's code. If you retire the line while it still has a profile, the next Run stops until that profile is cleared.</p>}
    {row.shape === "EXPLICIT" && <div data-capex-explicit-tools={itemKey}>
      <label className="rcm-field">Weights, % per month ({values.length} of {c.data.months} entered)
        <textarea rows={2} value={explicitInputText(row.explicit)} disabled={disabled} data-capex-explicit={itemKey}
          aria-label={`Explicit monthly percentages for ${label}`} onChange={e => c.change(itemKey, { explicit: { kind: "text", text: e.target.value } })} />
      </label>
      {parsed.status === "ambiguous" && <fieldset data-pr2b-ambiguous={itemKey}><legend>{parsed.reason}</legend>
        <label><input type="radio" name={`comma-${itemKey}`} disabled={disabled} onChange={() => c.change(itemKey, { explicit: { kind: "text", text: explicitInputText(row.explicit), commaMode: "decimal" } })} /> Comma is a decimal separator</label>
        <label><input type="radio" name={`comma-${itemKey}`} disabled={disabled} onChange={() => c.change(itemKey, { explicit: { kind: "text", text: explicitInputText(row.explicit), commaMode: "separator" } })} /> Comma separates months</label>
      </fieldset>}
      <p className={check?.ok ? "rx-note" : "rx-status rx-status-error"} data-capex-explicit-check={check?.ok ? "ok" : "invalid"} data-pr2b-sigma="validation-hint" role="status">
        Draft Σ % (validation hint): {check?.total ?? "—"} %. {parsed.status === "ambiguous" ? parsed.reason : parsed.status === "error" ? parsed.message : check?.problems.join(" ")}
      </p>
      <div className="pr2b-actions"><button type="button" className="rx-button rx-button-secondary" disabled={disabled} data-capex-import-open={itemKey} onClick={() => openImport()}>Import % from Excel / CSV…</button>
        <button type="button" className="rx-button rx-button-secondary" aria-expanded={monthsOpen} data-capex-month-grid-toggle={itemKey} onClick={() => setMonthsOpen(v => !v)}>{monthsOpen ? "Hide months" : "Enter month by month"}</button></div>
      {monthsOpen && <div className="pr2b-months" role="group" aria-label={`Monthly percentages for ${label}`} data-capex-month-grid={itemKey}>
        {Array.from({ length: Math.max(c.data.months, values.length) }, (_, i) => <label key={i} className="pr2b-month"><span>M{i + 1} %</span>
          <input inputMode="decimal" value={values[i] ?? ""} disabled={disabled || (row.explicit.kind === "text" && parsed.status !== "ok")}
            data-capex-month-input={`${itemKey}:${i + 1}`} aria-label={`${label}, month ${i + 1}, percent`}
            aria-invalid={i >= c.data!.months || undefined} onChange={e => c.change(itemKey, { explicit: editMonth(row.explicit, i, e.target.value) })}
            onKeyDown={e => {
              if (!["Enter", "ArrowDown", "ArrowUp", "ArrowLeft", "ArrowRight"].includes(e.key)) return;
              if (e.key === "ArrowLeft" && e.currentTarget.selectionStart !== 0) return;
              if (e.key === "ArrowRight" && e.currentTarget.selectionEnd !== e.currentTarget.value.length) return;
              const inputs = Array.from(root.current?.querySelectorAll<HTMLInputElement>("[data-capex-month-input]") ?? []);
              const target = inputs[i + (["ArrowUp", "ArrowLeft"].includes(e.key) ? -1 : 1)];
              if (target) { e.preventDefault(); target.focus(); target.scrollIntoView({ block: "nearest", inline: "nearest" }); }
            }} onPaste={e => {
              e.preventDefault(); e.stopPropagation();
              const text = e.clipboardData.getData("text/plain"), result = pasteMonths(row.explicit, i, text);
              if (result.status === "ok") c.change(itemKey, { explicit: result.input }); else openImport(text, i);
            }} />
        </label>)}
      </div>}
      {parsed.status === "ok" && values.length !== c.data.months && <div className="pr2b-actions">
        {padWithZeros(parsed.values.join(","), c.data.months) && <button type="button" className="rx-button rx-button-secondary" data-capex-fix="pad" disabled={disabled}
          onClick={() => c.change(itemKey, { explicit: { kind: "cells", values: padWithZeros(parsed.values.join(","), c.data!.months)!.split(",") } })}>Add the missing months at 0 %</button>}
        {trimTrailingZeros(parsed.values.join(","), c.data.months) && <button type="button" className="rx-button rx-button-secondary" data-capex-fix="trim" disabled={disabled}
          onClick={() => c.change(itemKey, { explicit: { kind: "cells", values: trimTrailingZeros(parsed.values.join(","), c.data!.months)!.split(",") } })}>Remove extra months (all 0 %)</button>}
      </div>}
    </div>}
    {row.shape === "MILESTONE" && <label className="rcm-field">Milestone month (1–{c.data.months})
      <input inputMode="numeric" value={row.milestone} disabled={disabled} data-capex-milestone={itemKey} aria-label={`Milestone month for ${label}`}
        onChange={e => c.change(itemKey, { milestone: e.target.value })} />
      {c.problems.filter(p => p.key === itemKey).map(p => <span key={p.message} role="alert">{p.message}</span>)}
    </label>}
    {!["EXPLICIT", "MILESTONE"].includes(row.shape) && <p className="rx-note">{row.shape ? `${SHAPE_LABEL[row.shape] ?? row.shape}: allocation is computed by the server preview, not in this editor.` : "Model default timing — no profile override. No monthly amount is inferred here."}</p>}
    {inline && <>
      {c.plan && <div data-pr2b-preview="server" data-pr2b-preview-state={c.outdated ? "stale" : "current"}>
        <strong>{c.outdated ? "Stale preview — preview again" : "Preview — not Saved / Last Run"}</strong>
        <div className="pr2b-months">{c.plan.plan.months.map(m => <div key={m.month}><span>M{m.month} (kEUR)</span><strong>{m.items[itemKey] ?? "—"}</strong></div>)}</div>
      </div>}</>}
    <dialog ref={importDialog} className="pr2b-import" data-capex-import-dialog={importer ? itemKey : undefined} aria-label={`Import monthly percentages for ${label}`}
      onCancel={e => { e.preventDefault(); setImporter(null); }}>
      {importer && <><h3>Import monthly % — {label}</h3><p>Apply changes only the shared draft. No value is rescaled; Save remains a separate profile-only action.</p>
        <textarea rows={3} value={importer.text} data-capex-import-text="true" aria-label="Pasted percentages" onChange={e => setImporter({ ...importer, text: e.target.value, mode: undefined })} />
        <label>Choose file… <input type="file" accept=".csv,.tsv,.txt,text/csv,text/plain" data-capex-import-file="true" onChange={e => {
          const file = e.target.files?.[0]; if (!file) return;
          if (file.size > 64 * 1024) { setFileError("The import file exceeds 64 KiB."); return; }
          void file.text().then(text => setImporter({ text, at: importer.at }));
        }} /></label>
        {fileError && <p role="alert">{fileError}</p>}
        {pasted?.status === "ambiguous" && <fieldset data-capex-import-ambiguous="true"><legend>{pasted.reason}</legend>
          <label><input type="radio" name={`import-comma-${itemKey}`} onChange={() => setImporter({ ...importer, mode: "decimal" })} /> The comma is a decimal separator (one value)</label>
          <label><input type="radio" name={`import-comma-${itemKey}`} onChange={() => setImporter({ ...importer, mode: "separator" })} /> The comma separates months</label>
        </fieldset>}
        {pasted?.status === "error" && <p role="alert" data-capex-import-error="true">{pasted.message}</p>}
        {importCheck && <p data-capex-import-check={importCheck.ok ? "ok" : "invalid"}>Draft validation: {importCheck.total} %. {importCheck.problems.join(" ")}</p>}
        <button type="button" className="rx-button rx-button-secondary" data-capex-import-cancel="true" onClick={() => setImporter(null)}>Cancel</button>
        <button type="button" className="rx-button" data-capex-import-apply="true" disabled={disabled || pasted?.status !== "ok" || (importer.at === null && !importCheck?.ok)} onClick={() => {
          if (pasted?.status !== "ok") return;
          if (importer.at === null) c.change(itemKey, { explicit: { kind: "cells", values: pasted.values } });
          else { const result = pasteMonths(row.explicit, importer.at, importer.text, importer.mode); if (result.status === "ok") c.change(itemKey, { explicit: result.input }); }
          setImporter(null);
        }}>Apply to the draft</button>
      </>}
    </dialog>
  </div>;
}
