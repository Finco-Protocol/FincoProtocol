// WF-React-2 — guided Revenue / PPA contract editor.
//
// Replaces the raw-JSON textarea.  The canonical contract payload
// (`contracts.raw`) is parsed into typed drafts; only fields the Revenue V1/V2
// authority defines as plain scalars are edited here.  Contractual index
// series, indexation timing, price rounding and CfD references are preserved
// byte-for-byte and shown read-only.  The editor never prices, indexes or
// rounds: the canonical writer validates and its verdict is displayed verbatim.

import { useEffect, useMemo, useState } from "react";
import { saveRevenueContracts } from "../api";
import { plain } from "../productLanguage";
import { calendarFrom, dateGuidance, type DateGuidance } from "./contractDates";
import {
  buildContractPayload, contractClass, countContractEdits, newPpaStream, parseContractModel,
  validateContractModel, type ContractModel, type StreamDraft,
} from "./ModelWorkflowValidation";
import {
  Field, StatusNote, WorkflowDialog, useReportDirty, useReportPending, useSingleFlight, useUnresolvedLock,
  type StatusMessage,
} from "./workflowShared";

type RevenueSave = { url: string; csrf_token: string; content_hash: string; workbook_version: string };

interface Props {
  project: string;
  protectedReference: boolean;
  contracts: Record<string, unknown>;
  save: RevenueSave;
  onSaved?: () => void;
}

/** Order-independent structural equality of two JSON texts (the canonical
 *  writer re-serialises with sorted keys). */
function sameJson(a: string, b: string): boolean {
  const norm = (value: unknown): unknown => Array.isArray(value) ? value.map(norm)
    : value && typeof value === "object"
      ? Object.fromEntries(Object.keys(value as object).sort().map((k) => [k, norm((value as Record<string, unknown>)[k])]))
      : value;
  try {
    return JSON.stringify(norm(JSON.parse(a))) === JSON.stringify(norm(JSON.parse(b)));
  } catch {
    return false;
  }
}

type FreshRevenue = { ok?: boolean; contracts?: { raw?: string }; save?: RevenueSave } | null;

async function readFreshRevenue(project: string): Promise<FreshRevenue> {
  try {
    const response = await fetch(`/v2/model-react/revenue?project=${encodeURIComponent(project)}`,
      { credentials: "same-origin", headers: { Accept: "application/json" } });
    return (await response.json()) as FreshRevenue;
  } catch {
    return null;
  }
}

/** Why a contract date is not an operating-period boundary and the nearest accepted dates, one click each (the date is never rounded for the user). */
function DateHelp({ guidance, readOnly, onUse }: { guidance: DateGuidance | null; readOnly: boolean; onUse: (date: string) => void }) {
  if (!guidance) return null;
  return (
    <div className="wf-date-help" role="status" data-date-guidance="true">
      <small>{guidance.message}</small>
      {!readOnly && guidance.suggestions.map((sug, k) => (
        <button key={sug.value} type="button" className="fm-btn" data-date-suggestion={sug.value} data-date-suggestion-rank={k} onClick={() => onUse(sug.value)}>{sug.label}</button>
      ))}
    </div>
  );
}

function cloneModel(model: ContractModel): ContractModel {
  return JSON.parse(JSON.stringify(model)) as ContractModel;
}

export function PPAEditorView({ project, protectedReference, contracts, save, onSaved }: Props) {
  const raw = typeof contracts.raw === "string" ? (contracts.raw as string) : "";
  const hasContract = contracts.active === true && raw.trim() !== "";
  const technology = String(contracts.technology ?? "");
  const scope = plain(String(contracts.scope ?? "Project / Base case"));
  const operatingWindow = (contracts.operating_window ?? null) as { start: string; end: string } | null;
  const calendar = useMemo(() => calendarFrom(contracts), [contracts]);

  const parsed = useMemo(() => (hasContract ? parseContractModel(raw) : null), [hasContract, raw]);
  const savedModel = parsed && parsed.ok ? parsed.model : null;

  const [draft, setDraft] = useState<ContractModel | null>(savedModel ? cloneModel(savedModel) : null);
  const [showErrors, setShowErrors] = useState(false);
  const [status, setStatus] = useState<StatusMessage | null>(null);
  const [inFlight, setInFlight] = useState(false);
  const [removeIndex, setRemoveIndex] = useState<number | null>(null);
  const [lockedByUnknown, setLockedByUnknown] = useUnresolvedLock("revenue-ppa");
  const [creating, setCreating] = useState(false);

  // A new persisted payload (after a Save, a scenario switch or a reload) resets
  // the editor to the server-authoritative state.
  useEffect(() => {
    setDraft(savedModel ? cloneModel(savedModel) : null);
    setShowErrors(false);
    setLockedByUnknown(false);
    setCreating(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [raw]);

  const errors = useMemo(() => (draft ? validateContractModel(draft) : {}), [draft]);
  const editCount = savedModel && draft ? countContractEdits(savedModel, draft) : creating && draft ? 1 : 0;
  useReportDirty("revenue-ppa", editCount);
  useReportPending("revenue-ppa", inFlight || lockedByUnknown);
  const singleFlight = useSingleFlight();
  const readOnly = protectedReference || inFlight || lockedByUnknown;

  const update = (index: number, patch: Partial<StreamDraft>) => {
    setDraft((prev) => prev ? { ...prev, streams: prev.streams.map((s, i) => (i === index ? { ...s, ...patch } : s)) } : prev);
    setStatus(null);
  };

  const submit = (model: ContractModel, originalRaw: string) => singleFlight(() => runSubmit(model, originalRaw));

  const runSubmit = async (model: ContractModel, originalRaw: string) => {
    if (lockedByUnknown) return;
    setShowErrors(true);
    const problems = validateContractModel(model);
    if (Object.keys(problems).length) {
      setStatus({ tone: "error", text: `Fix ${Object.keys(problems).length} highlighted field(s) before saving. Nothing was saved.` });
      return;
    }
    const payload = buildContractPayload(originalRaw, model);
    if (payload === null) {
      setStatus({ tone: "error", text: "The saved contract data could not be read; reload and try again." });
      return;
    }
    setInFlight(true);
    setStatus(null);
    const result = await saveRevenueContracts({
      saveUrl: save.url, project, csrfToken: save.csrf_token, contentHash: save.content_hash, contractsJson: payload,
    });
    if ("kind" in result) {
      setLockedByUnknown(true);
      setStatus({ tone: "conflict", text: result.message });
      setInFlight(false);
      return;
    }
    if (!result.ok) {
      // A refusal changed nothing; the typed draft stays on screen.
      setStatus({ tone: "error", text: result.message });
      setInFlight(false);
      return;
    }
    // A clean redirect alone is not proof: reconcile against the fresh projection.
    const fresh = await readFreshRevenue(project);
    const freshRaw = fresh?.ok === true && typeof fresh.contracts?.raw === "string" ? fresh.contracts.raw : null;
    setInFlight(false);
    if (freshRaw !== null && fresh?.save && fresh.save.content_hash !== save.content_hash && sameJson(freshRaw, payload)) {
      setStatus({ tone: "ok", text: "Contracts saved atomically and verified in the fresh projection. The project is now newer than the Last Run (results outdated); the model was not run." });
      onSaved?.();
    } else if (freshRaw !== null && fresh?.save && fresh.save.content_hash !== save.content_hash) {
      setStatus({ tone: "conflict", text: "Contracts were saved, but the saved data differs from what was submitted (the server normalised it). Review the reloaded values before continuing; the model was not run." });
      onSaved?.();
    } else {
      setLockedByUnknown(true);
      setStatus({ tone: "conflict", text: "The save outcome is UNKNOWN: the server answered but the saved project could not confirm it. Reload to reconcile - your edits are preserved and nothing was re-submitted." });
    }
  };

  // ── no contract book yet ──
  if (!hasContract) {
    const canCreate = (technology === "solar" || technology === "wind") && !protectedReference;
    const seed = (): ContractModel => ({
      version: 2, technology,
      streams: [newPpaStream([], operatingWindow)],
      preservedKeys: [[]],
    });
    return (
      <section className="fm-card fm-section wf-section" aria-label="Revenue and PPA contracts" data-ppa-editor="empty">
        <div className="fm-card-title"><h3>Revenue &amp; PPA contracts</h3><span>{scope}</span></div>
        <div className="fm-banner" role="note">
          <span className="fm-demo-label">NO CONTRACT BOOK</span>
          <span className="fm-banner-copy">This project prices revenue from its single-price PPA inputs. You can define an explicit contract
            book here; nothing is created until you enter every value and save.</span>
        </div>
        {canCreate && !creating && (
          <button type="button" className="fm-btn fm-btn-primary" onClick={() => { setDraft(seed()); setCreating(true); setShowErrors(false); }}>
            Define a PPA contract
          </button>
        )}
        {!canCreate && <p className="fm-info-note">{protectedReference
          ? "Templates are read-only. Start a project from this template to define contracts."
          : "Guided contract creation is available for Solar and Wind projects."}</p>}
        {creating && draft && renderEditor(draft, true)}
      </section>
    );
  }

  if (parsed && !parsed.ok) {
    return (
      <section className="fm-card fm-section wf-section" aria-label="Revenue and PPA contracts" data-ppa-editor="readonly">
        <div className="fm-card-title"><h3>Revenue &amp; PPA contracts</h3><span>{scope}</span></div>
        <div className="fm-banner" role="note">
          <span className="fm-demo-label">READ ONLY</span>
          <span className="fm-banner-copy">{parsed.message} Nothing was changed; correct the stored contract data before editing.</span>
        </div>
        <details><summary>Show the stored contract payload</summary>
          <pre className="fm-mono wf-table-wrap">{JSON.stringify(JSON.parse(raw), null, 2)}</pre></details>
      </section>
    );
  }

  function renderEditor(model: ContractModel, isCreate: boolean) {
    const err = (i: number, field: string) => (showErrors ? errors[`streams.${i}.${field}`] : undefined);
    const baseRaw = isCreate ? JSON.stringify({ version: 2, technology, indexation_basis: "OPERATING_YEAR", streams: [] }) : raw;
    return (
      <>
        <StatusNote status={status} />
        {protectedReference && <div className="fm-banner" role="note"><span className="fm-demo-label">READ-ONLY TEMPLATE</span><span className="fm-banner-copy">Read-only. Start a project from this template to edit contracts.</span></div>}
        {lockedByUnknown && <div className="fm-banner" role="alert"><span className="fm-demo-label">RECONCILE</span><span className="fm-banner-copy">The last save outcome is unknown. Reload the workspace before editing again.</span></div>}
        {model.streams.map((s, i) => {
          const preserved = model.preservedKeys[i] ?? [];
          const klass = contractClass(s, preserved);
          const pid = `ppa-${i}`;
          return (
            <div key={i} className="wf-stream" data-ppa-stream={s.id} data-contract-class={klass}>
              <div className="wf-stream-head">
                <strong>{s.id || "New contract"} <span className="wf-class" data-contract-class-label={klass}>{klass}</span></strong>
                <button type="button" className="fm-btn" disabled={readOnly || model.streams.length <= 1}
                        aria-label={`Remove contract ${s.id || i + 1}`} onClick={() => setRemoveIndex(i)}>Remove</button>
              </div>
              <div className="wf-grid">
                <Field id={`${pid}-id`} label="Contract identity" error={err(i, "id")} hint={s.isNew ? undefined : "The identity is a fixed reference; change it only if nothing else depends on it."}>
                  {(p) => <input {...p} className="fm-input" value={s.id} disabled={readOnly} onChange={(e) => update(i, { id: e.target.value })} />}
                </Field>
                <Field id={`${pid}-ref`} label="Source reference" error={err(i, "source_ref")}>
                  {(p) => <input {...p} className="fm-input" value={s.source_ref} disabled={readOnly} onChange={(e) => update(i, { source_ref: e.target.value })} />}
                </Field>
                <Field id={`${pid}-start`} label="Start date" unit="YYYY-MM-DD" error={err(i, "start_date")}>
                  {(p) => <><input {...p} className="fm-input" inputMode="numeric" placeholder="YYYY-MM-DD" value={s.start_date} disabled={readOnly} onChange={(e) => update(i, { start_date: e.target.value })} />
                    <DateHelp guidance={dateGuidance("start_date", s.start_date, s.end_date, calendar)} readOnly={readOnly} onUse={(d) => update(i, { start_date: d })} /></>}
                </Field>
                <Field id={`${pid}-end`} label="End date" unit="YYYY-MM-DD, exclusive" error={err(i, "end_date")}>
                  {(p) => <><input {...p} className="fm-input" inputMode="numeric" placeholder="YYYY-MM-DD" value={s.end_date} disabled={readOnly} onChange={(e) => update(i, { end_date: e.target.value })} />
                    <DateHelp guidance={dateGuidance("end_date", s.start_date, s.end_date, calendar)} readOnly={readOnly} onUse={(d) => update(i, { end_date: d })} /></>}
                </Field>
                <Field id={`${pid}-share`} label="Contracted volume share" unit="0-1; blank only for merchant" error={err(i, "volume_share")}>
                  {(p) => <input {...p} className="fm-input" inputMode="decimal" value={s.volume_share} disabled={readOnly} onChange={(e) => update(i, { volume_share: e.target.value })} />}
                </Field>
                <Field id={`${pid}-price`} label={s.curve ? "Base tariff (reference)" : "Tariff"} unit="€/MWh" error={err(i, "price_eur_mwh")}>
                  {(p) => <input {...p} className="fm-input" inputMode="decimal" value={s.price_eur_mwh} disabled={readOnly} onChange={(e) => update(i, { price_eur_mwh: e.target.value })} />}
                </Field>
                <Field id={`${pid}-idx`} label="Indexation rate" unit="per operating year, 0.02 = 2%" error={err(i, "indexation_rate")}>
                  {(p) => <input {...p} className="fm-input" inputMode="decimal" value={s.indexation_rate} disabled={readOnly || s.curve !== null} onChange={(e) => update(i, { indexation_rate: e.target.value })} />}
                </Field>
                {s.type === "merchant" && (
                  <Field id={`${pid}-capture`} label="Capture rate" unit="0-1" error={err(i, "capture_rate")}>
                    {(p) => <input {...p} className="fm-input" inputMode="decimal" value={s.capture_rate} disabled={readOnly} onChange={(e) => update(i, { capture_rate: e.target.value })} />}
                  </Field>
                )}
              </div>
              {preserved.length > 0 && (
                <p className="wf-readonly-keys" data-preserved-keys={preserved.join(",")}>
                  Preserved read-only: {preserved.map((k) => k.replace(/_/g, " ")).join(", ")}. These terms are carried over unchanged;
                  they cannot be edited in this view.
                </p>
              )}
              {s.curve && renderCurve(i, s)}
              {!s.curve && model.version === 2 && s.type === "ppa" && preserved.length === 0 && (
                <button type="button" className="fm-btn" disabled={readOnly} onClick={() => update(i, { curve: [{ period_start: s.start_date, price_eur_mwh: s.price_eur_mwh }], indexation_rate: "0" })}>
                  Switch to a scheduled price curve
                </button>
              )}
            </div>
          );
        })}
        <div className="fm-toolbar wf-toolbar" style={{ flexWrap: "wrap" }}>
          <button type="button" className="fm-btn" disabled={readOnly || model.streams.length >= 24}
                  onClick={() => setDraft((prev) => prev ? { ...prev, streams: [...prev.streams, newPpaStream(prev.streams, operatingWindow)], preservedKeys: [...prev.preservedKeys, []] } : prev)}>
            Add PPA contract
          </button>
          <button type="button" className="fm-btn fm-btn-primary" disabled={readOnly || (!isCreate && editCount === 0)}
                  data-ppa-save="true" onClick={() => void submit(model, baseRaw)}>
            Save contracts{editCount ? ` (${editCount} edit${editCount === 1 ? "" : "s"})` : ""}
          </button>
          <button type="button" className="fm-btn" disabled={inFlight || (!isCreate && editCount === 0)}
                  onClick={() => { if (isCreate) { setCreating(false); setDraft(null); } else if (savedModel) setDraft(cloneModel(savedModel)); setShowErrors(false); setStatus(null); }}>
            Cancel edits
          </button>
        </div>
        {removeIndex !== null && (
          <WorkflowDialog
            title="Remove this contract?"
            description={`Contract "${model.streams[removeIndex]?.id}" is removed from the draft. Nothing is saved until you press Save contracts; the server then validates the remaining contracts.`}
            confirmLabel="Remove from draft" danger
            onCancel={() => setRemoveIndex(null)}
            onConfirm={() => {
              const index = removeIndex;
              setDraft((prev) => prev ? { ...prev, streams: prev.streams.filter((_, i) => i !== index), preservedKeys: prev.preservedKeys.filter((_, i) => i !== index) } : prev);
              setRemoveIndex(null);
            }} />
        )}
        <p className="fm-info-note">
          Contracts are checked when you save. If a contract is rejected, nothing is saved and the message names the problem. Saving never
          runs the model; changed contracts mark the Last Run STALE until you run again.
        </p>
      </>
    );
  }

  function renderCurve(i: number, s: StreamDraft) {
    const points = s.curve ?? [];
    const pointErr = (p: number, field: string) => (showErrors ? errors[`streams.${i}.curve.${p}.${field}`] : undefined);
    const setPoints = (next: typeof points) => update(i, { curve: next });
    return (
      <div className="wf-curve" data-ppa-curve={s.id}>
        <p className="wf-group-head">Scheduled tariff points (effective from each period start, ascending)</p>
        {showErrors && errors[`streams.${i}.curve`] && <small className="wf-error" role="alert">{errors[`streams.${i}.curve`]}</small>}
        <table className="fm-table">
          <thead><tr><th scope="col">Effective from</th><th scope="col">Tariff (€/MWh)</th><th scope="col"><span className="fm-sr-only">Actions</span></th></tr></thead>
          <tbody>
            {points.map((point, p) => (
              <tr key={p}>
                <td>
                  <Field id={`ppa-${i}-pt-${p}-d`} label={`Point ${p + 1} effective date`} error={pointErr(p, "period_start")}>
                    {(a) => <input {...a} className="fm-input" placeholder="YYYY-MM-DD" value={point.period_start} disabled={readOnly}
                                   onChange={(e) => setPoints(points.map((x, k) => (k === p ? { ...x, period_start: e.target.value } : x)))} />}
                  </Field>
                </td>
                <td>
                  <Field id={`ppa-${i}-pt-${p}-v`} label={`Point ${p + 1} tariff`} error={pointErr(p, "price_eur_mwh")}>
                    {(a) => <input {...a} className="fm-input" inputMode="decimal" value={point.price_eur_mwh} disabled={readOnly}
                                   onChange={(e) => setPoints(points.map((x, k) => (k === p ? { ...x, price_eur_mwh: e.target.value } : x)))} />}
                  </Field>
                </td>
                <td><button type="button" className="fm-btn" disabled={readOnly || points.length <= 1} aria-label={`Remove point ${p + 1} of ${s.id}`}
                            onClick={() => setPoints(points.filter((_, k) => k !== p))}>Remove</button></td>
              </tr>
            ))}
          </tbody>
        </table>
        <button type="button" className="fm-btn" disabled={readOnly || points.length >= 600}
                onClick={() => setPoints([...points, { period_start: "", price_eur_mwh: "" }])}>Add point</button>
        <small className="wf-hint"> The server checks that the curve covers every operating period; gaps or overlaps are refused with its own message.</small>
      </div>
    );
  }

  return (
    <section className="fm-card fm-section wf-section" aria-label="Revenue and PPA contract editor" data-ppa-editor="guided">
      <div className="fm-card-title"><h3>Revenue &amp; PPA contracts</h3>
        <span>{scope}{contracts.overridden ? " · scenario-overridden" : ""} · {technology || "technology unknown"}</span></div>
      {draft && renderEditor(draft, false)}
    </section>
  );
}
