import { useReportPrecision } from "../ReportPrecision";
import { reportAmount, reportEvidence } from "../reportFormatting";
import { useCallback, useEffect, useRef, useState } from "react";
import "../../styles/rcm-financing.css";
import { StatusNote, useReportDirty, useReportPending, useSingleFlight, useUnresolvedLock, type StatusMessage } from "../workflow/workflowShared";
import { draftFromTerms, friendlyAgreementError, identityProblems, isSame, resolveNextVersion, serializeAgreement, type AgreementDraft } from "./serializeAgreement";
import type { InvestorPayload, SponsorMetric } from "./types";

type Read = { ok: true; data: InvestorPayload } | { ok: false; code: string; message?: string };

const EMPTY_DRAFT: AgreementDraft = { agreementId: "", investors: [], contributions: [] };

async function fetchInvestors(project: string, historyId: string | null = null, signal?: AbortSignal): Promise<Read> {
  try {
    const query = new URLSearchParams({ project });
    if (historyId) query.set("history_id", historyId);
    const response = await fetch(`/v2/model-react/investors/agreement?${query.toString()}`, {
      credentials: "same-origin",
      headers: { Accept: "application/json" },
      signal,
    });
    const body = await response.json().catch(() => null) as (InvestorPayload | { code?: string; message?: string }) | null;
    if (response.ok && body && (body as { ok?: boolean }).ok) return { ok: true, data: body as InvestorPayload };
    const failed = (body ?? {}) as { code?: string; message?: string };
    return { ok: false, code: failed.code || `HTTP_${response.status}`, message: failed.message };
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") {
      return { ok: false, code: "ABORTED" };
    }
    return { ok: false, code: "SERVER_UNREACHABLE", message: "The FINCO Model server is unreachable." };
  }
}

const pct = (v: number | null, digits = 2) => (v === null ? null : `${(v * 100).toFixed(digits)}%`);

function Metric({ m }: { m: SponsorMetric }) {
  const { precision } = useReportPrecision();
  return <div data-sponsor-metric={m.label}><dt>{m.label}</dt><dd>{reportEvidence(m.value, m.display, m.label, precision)}{m.value === null && m.reason && <span className="rcm-reason">{m.reason}</span>}</dd></div>;
}

/** Investor & sponsor agreement: typed common-equity holders and actual paid-in capital, saved through the canonical F4 route
 *  (session CSRF, composite-hash CAS, agreement-version CAS); Run-bound evidence and historical Runs are read-only. */
export function InvestorsPanel({ project, reloadKey, onSaved }: { project: string; reloadKey: number; onSaved: () => void }) {
  const { precision } = useReportPrecision();
  const money = (value: number | null) => reportAmount(value, precision);
  const [read, setRead] = useState<Read | null>(null);
  const [selectedHistoryId, setSelectedHistoryId] = useState<string | null>(null);
  const [pendingHistoryTarget, setPendingHistoryTarget] = useState<string | null | undefined>(undefined);
  const [loadingSelection, setLoadingSelection] = useState(false);
  const [workingBaseline, setWorkingBaseline] = useState<AgreementDraft>(EMPTY_DRAFT);
  const [draft, setDraft] = useState<AgreementDraft>(EMPTY_DRAFT);
  const [status, setStatus] = useState<StatusMessage | null>(null);
  const [inFlight, setInFlight] = useState(false);
  const [confirmRemove, setConfirmRemove] = useState(false);
  const [locked, setLocked] = useUnresolvedLock("sheet-debt-investors");
  const singleFlight = useSingleFlight();
  const shown = useRef("");
  const requestSeq = useRef(0);
  const activeTarget = useRef<{ project: string; historyId: string | null }>({ project, historyId: null });
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    abortRef.current?.abort();
    requestSeq.current += 1;
    activeTarget.current = { project, historyId: null };
    shown.current = "";
    setSelectedHistoryId(null);
    setPendingHistoryTarget(undefined);
    setConfirmRemove(false);
    setWorkingBaseline(EMPTY_DRAFT);
    setDraft(EMPTY_DRAFT);
    setStatus(null);
    setRead(null);
  }, [project]);

  const load = useCallback(async (historyId: string | null = selectedHistoryId): Promise<Read> => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    const seq = ++requestSeq.current;
    activeTarget.current = { project, historyId };
    setLoadingSelection(true);
    try {
      const result = await fetchInvestors(project, historyId, controller.signal);
      if (seq !== requestSeq.current || activeTarget.current.project !== project || activeTarget.current.historyId !== historyId) {
        return { ok: false, code: "STALE_RESPONSE" };
      }
      if (!result.ok && result.code === "ABORTED") {
        return result;
      }
      setRead(result);
      return result;
    } finally {
      if (seq === requestSeq.current) {
        setLoadingSelection(false);
      }
    }
  }, [project, selectedHistoryId]);

  useEffect(() => {
    void load(selectedHistoryId);
    return () => {
      abortRef.current?.abort();
    };
  }, [load, reloadKey, selectedHistoryId]);

  const data = read && read.ok ? read.data : null;
  const isHistorical = Boolean(data && (data.selected_history_id || data.state === "HISTORICAL"));

  // Only non-historical working responses establish the editable baseline; inspecting history never clobbers a dirty draft.
  useEffect(() => {
    if (!data || data.selected_history_id || data.state === "HISTORICAL") return;
    const nextBaseline = draftFromTerms(data.terms ?? null);
    setWorkingBaseline(nextBaseline);
    const key = JSON.stringify(nextBaseline);
    if (shown.current !== key) {
      shown.current = key;
      setDraft(nextBaseline);
    }
  }, [data]);

  const dirty = !isSame(draft, workingBaseline);
  useReportDirty("sheet-debt-investors", dirty ? 1 : 0);
  useReportPending("sheet-debt-investors", inFlight || locked || loadingSelection);

  const edit = (next: AgreementDraft) => {
    if (isHistorical || loadingSelection) return;
    setDraft(next);
    setStatus(null);
  };
  const ownershipTotal = draft.investors.reduce((sum, r) => sum + (r.ownershipPct.trim() === "" ? 0 : Number(r.ownershipPct) || 0), 0);

  const requestHistorySelection = (targetHistoryId: string | null) => {
    if (inFlight || locked) return;
    setConfirmRemove(false);
    if (targetHistoryId !== null && !isHistorical && dirty) {
      setPendingHistoryTarget(targetHistoryId);
      return;
    }
    setPendingHistoryTarget(undefined);
    setStatus(null);
    setSelectedHistoryId(targetHistoryId);
  };

  const submit = useCallback(async (action: "save" | "remove") => {
    if (!data || isHistorical || !data.save || loadingSelection) return;
    const saveMeta = {
      agreementId: data.save.saved_agreement_id,
      nextVersion: data.save.next_version,
      ledgerNextVersions: data.save.ledger_next_versions,
    };
    const saveUrl = data.save.url;
    const csrfToken = data.save.csrf_token;
    if (action === "save") {
      const problems = identityProblems(draft);
      if (problems.length) { setStatus({ tone: "error", text: `${problems.join(" ")} Nothing was changed.` }); return; }
    }
    await singleFlight(async () => {
      setInFlight(true); setStatus(null);
      try {
        const expectedVersion = resolveNextVersion(draft.agreementId, saveMeta);
        const body = new URLSearchParams({
          project, csrf_token: csrfToken, content_hash: data.identity.content_hash,
          agreement: action === "save" ? serializeAgreement(draft, saveMeta) : "",
          action,
        });
        let response: Response;
        try {
          response = await fetch(saveUrl, { method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/x-www-form-urlencoded", "HX-Request": "true" }, body: body.toString() });
        } catch {
          setLocked(true);
          setStatus({ tone: "conflict", text: "Result UNKNOWN — the connection failed before a definitive response. Reload the workspace to see whether the agreement was saved; do not submit again blindly." });
          return;
        }
        if (response.status >= 500) {
          setLocked(true);
          setStatus({ tone: "conflict", text: "Result UNKNOWN — the server failed while saving. Reload the workspace to reconcile before saving again." });
          return;
        }
        if (!response.ok) {
          const failure = await response.json().catch(() => null) as { error?: string } | null;
          setStatus({ tone: response.status === 409 ? "conflict" : "error", text: `${friendlyAgreementError(failure?.error)} Nothing was changed.` });
          if (response.status === 409) void load(null);
          return;
        }
        const fresh = await load(null);
        const confirmed = fresh.ok && (action === "remove" ? fresh.data.terms === null
          : fresh.data.terms !== null && fresh.data.terms.agreement_id === draft.agreementId && fresh.data.terms.version === expectedVersion);
        if (!confirmed) { setLocked(true); setStatus({ tone: "conflict", text: "Result UNKNOWN — the server accepted the request but the fresh read could not confirm it. Reload to reconcile." }); return; }
        setStatus({ tone: "ok", text: action === "save" ? "Agreement saved and read back. It is NOT in any Run yet — press Run to produce investor evidence." : "Working agreement removed." });
        onSaved();
      } finally { setInFlight(false); setConfirmRemove(false); }
    });
  }, [data, isHistorical, loadingSelection, draft, project, load, singleFlight, setLocked, onSaved]);

  if (!read) return <section className="rx-card"><p className="rx-boot-loading" role="status">Loading the investor agreement…</p></section>;
  if (!read.ok || !data) return <section className="rx-card" data-investors-state="error"><h3 className="rcm-h3">Investors &amp; sponsor</h3><p className="rx-empty" role="alert">{(read as { message?: string }).message || "The investor view is unavailable right now. Nothing was changed."}</p></section>;

  const disabled = !data.editable || isHistorical || !data.save || locked || inFlight || loadingSelection;
  const sponsor = data.sponsor;
  const histRunLabel = `${data.identity.snapshot_id || data.evidence?.snapshot_id || data.selected_history_id || ""} (${data.identity.scenario_name || "Base"})`.trim();
  const nextVersionPreview = !isHistorical && data.save
    ? resolveNextVersion(draft.agreementId, {
        agreementId: data.save.saved_agreement_id,
        nextVersion: data.save.next_version,
        ledgerNextVersions: data.save.ledger_next_versions,
      })
    : null;

  return (
    <section
      className="rx-card rcm-fin"
      data-investors-panel="true"
      data-investor-workflow={data.workflow.state}
      data-investor-scope={data.identity.scope || (isHistorical ? "HISTORICAL" : "CURRENT")}
      aria-labelledby="rcm-inv-title"
    >
      <h3 id="rcm-inv-title" className="rcm-h3">Common-equity investor agreement <span className="rcm-badge" data-investor-state={data.state}>{data.state}</span></h3>
      <p className="rx-note">Residual common equity only. <strong>Ownership %</strong> allocates results between investors and does not change Sources &amp; Uses; <strong>commitments and paid-in capital</strong> describe funding and must reconcile with the equity in the financing plan before Run.</p>
      <p className="rx-status rx-status-conflict" role="status" data-investor-workflow-text="true">{data.workflow.text}</p>
      {loadingSelection && (
        <p className="rx-note" role="status" data-investor-loading="true">Loading selected Run view…</p>
      )}
      {!isHistorical && data.draft_warning?.incomplete_draft && (
        <p className="rx-status rx-status-conflict" role="alert" data-investor-draft-warning={data.draft_warning.code}>
          {data.draft_warning.message}
        </p>
      )}
      {!isHistorical && data.draft_warning?.advisory_message && (
        <p className="rx-status rx-status-conflict" role="status" data-investor-funding-advisory={data.draft_warning.funding_reference_state || data.draft_warning.code}>
          {data.draft_warning.advisory_message}
        </p>
      )}
      {(!data.editable || isHistorical) && (
        <div className="rx-status rx-status-conflict" data-investors-readonly="true">
          <p>
            {isHistorical
              ? `Read-only historical Run ${data.identity.snapshot_id || data.selected_history_id} · scenario ${data.identity.scenario_name || "Base"}${data.identity.ran_at ? ` · ran ${data.identity.ran_at}` : ""}${data.identity.content_hash ? ` · hash ${data.identity.content_hash.slice(0, 12)}` : ""}.`
              : "Read-only: templates cannot be edited. Start a project from this template to define an agreement."}
          </p>
          {isHistorical && dirty && (
            <p className="rx-note" data-investor-draft-parked="true">
              Unsaved changes in your working draft remain preserved locally until you return to Last Run / Working agreement.
            </p>
          )}
          {isHistorical && (
            <button
              type="button"
              className="rx-button rx-button-secondary"
              data-inv-history-current-banner="true"
              disabled={loadingSelection}
              onClick={() => requestHistorySelection(null)}
            >
              Return to Last Run / Working agreement
            </button>
          )}
        </div>
      )}
      {locked && <p className="rx-status rx-status-conflict" role="alert" data-investors-locked="true">A previous save has an unknown outcome. Reload the workspace to reconcile before editing again.</p>}

      {!isHistorical && (
        <>
          <fieldset className="rcm-fieldset" disabled={disabled}>
            <legend>Agreement &amp; holders</legend>
            <label className="rcm-field">Agreement ID
              <input data-inv="agreement_id" maxLength={128} value={draft.agreementId} onChange={(e) => edit({ ...draft, agreementId: e.target.value })} /></label>
            <p className="rx-note">Saved version {data.terms ? data.terms.version : "— (none)"} · working scenario {data.identity.scenario_name || "Base"} · next Save writes version {nextVersionPreview ?? 1}.</p>
            <div className="rcm-scroll" tabIndex={0} role="region" aria-label="Investors (scrolls horizontally)">
              <table className="rcm-table" data-inv-holders="true">
                <thead><tr><th scope="col" className="rcm-left">Investor ID</th><th scope="col">Legal ownership %</th><th scope="col">Commitment kEUR</th><th scope="col"><span className="rx-sr-only">Remove</span></th></tr></thead>
                <tbody>
                  {draft.investors.map((r, i) => (
                    <tr key={i} data-inv-holder={i}>
                      <td><input aria-label="Investor ID" value={r.investorId} onChange={(e) => edit({ ...draft, investors: draft.investors.map((x, j) => (j === i ? { ...x, investorId: e.target.value } : x)) })} /></td>
                      <td><input aria-label="Legal ownership percent" inputMode="decimal" value={r.ownershipPct} onChange={(e) => edit({ ...draft, investors: draft.investors.map((x, j) => (j === i ? { ...x, ownershipPct: e.target.value } : x)) })} /></td>
                      <td><input aria-label="Commitment kEUR" inputMode="decimal" value={r.commitment} onChange={(e) => edit({ ...draft, investors: draft.investors.map((x, j) => (j === i ? { ...x, commitment: e.target.value } : x)) })} /></td>
                      <td><button type="button" className="rx-button rx-button-secondary" aria-label={`Remove investor ${r.investorId || i + 1}`} data-inv-remove-holder={i} onClick={() => edit({ ...draft, investors: draft.investors.filter((_, j) => j !== i) })}>×</button></td>
                    </tr>
                  ))}
                  {draft.investors.length === 0 && <tr><td colSpan={4} className="rcm-na">No investors yet.</td></tr>}
                </tbody>
              </table>
            </div>
            <p className="rx-note" data-inv-ownership-total={ownershipTotal.toFixed(4)}>Ownership entered: {ownershipTotal.toFixed(2)}% — the server requires exactly 100%.</p>
            <button type="button" className="rx-button rx-button-secondary" data-inv-add="holder" onClick={() => edit({ ...draft, investors: [...draft.investors, { investorId: "", ownershipPct: "", commitment: "" }] })}>Add investor</button>
          </fieldset>

          <fieldset className="rcm-fieldset" disabled={disabled}>
            <legend>Actual paid-in capital</legend>
            <p className="rx-note">Commitments stay separate from actual paid-in cash. Run requires exact-date agreement with the legal-equity funding below; a commitment never manufactures a paid-in event.</p>
            <div className="rcm-scroll" tabIndex={0} role="region" aria-label="Paid-in contributions (scrolls horizontally)">
              <table className="rcm-table" data-inv-contributions="true">
                <thead><tr><th scope="col" className="rcm-left">Investor ID</th><th scope="col" className="rcm-left">Cash date</th><th scope="col">Paid-in kEUR</th><th scope="col"><span className="rx-sr-only">Remove</span></th></tr></thead>
                <tbody>
                  {draft.contributions.map((r, i) => (
                    <tr key={i} data-inv-contribution={i}>
                      <td><input aria-label="Contribution investor ID" value={r.investorId} onChange={(e) => edit({ ...draft, contributions: draft.contributions.map((x, j) => (j === i ? { ...x, investorId: e.target.value } : x)) })} /></td>
                      <td><input aria-label="Contribution date" type="date" value={r.cashDate} onChange={(e) => edit({ ...draft, contributions: draft.contributions.map((x, j) => (j === i ? { ...x, cashDate: e.target.value } : x)) })} /></td>
                      <td><input aria-label="Paid-in kEUR" inputMode="decimal" value={r.amount} onChange={(e) => edit({ ...draft, contributions: draft.contributions.map((x, j) => (j === i ? { ...x, amount: e.target.value } : x)) })} /></td>
                      <td><button type="button" className="rx-button rx-button-secondary" aria-label={`Remove contribution ${i + 1}`} onClick={() => edit({ ...draft, contributions: draft.contributions.filter((_, j) => j !== i) })}>×</button></td>
                    </tr>
                  ))}
                  {draft.contributions.length === 0 && <tr><td colSpan={4} className="rcm-na">No contributions yet.</td></tr>}
                </tbody>
              </table>
            </div>
            <button type="button" className="rx-button rx-button-secondary" data-inv-add="contribution" onClick={() => edit({ ...draft, contributions: [...draft.contributions, { investorId: "", cashDate: "", amount: "" }] })}>Add contribution</button>
            {data.funding.length > 0 && (
              <details className="rcm-details"><summary>Last Run actual equity funding (reference)</summary>
                <table className="rcm-table rcm-draws" data-inv-funding="true"><thead><tr><th scope="col" className="rcm-left">Exact cash date</th><th scope="col">Paid-in kEUR</th></tr></thead>
                  <tbody>{data.funding.map((f) => <tr key={f.date}><td className="rcm-left">{f.date}</td><td>{money(f.paid_in_keur)}</td></tr>)}</tbody></table></details>
            )}
          </fieldset>

          <div className="rcm-actions-row">
            <button type="button" className="rx-button" data-inv-save="true" disabled={disabled || !dirty} aria-busy={inFlight} onClick={() => void submit("save")}>{inFlight ? "Saving…" : "Save agreement"}</button>
            <button type="button" className="rx-button rx-button-secondary" data-inv-discard="true" disabled={disabled || !dirty} onClick={() => { setDraft(workingBaseline); setStatus(null); }}>Discard changes</button>
            {data.terms && (!confirmRemove
              ? <button type="button" className="rx-button rx-button-secondary" data-inv-remove="true" disabled={disabled} onClick={() => setConfirmRemove(true)}>Remove working agreement…</button>
              : <span role="group" aria-label="Confirm removal">Remove the working agreement? <button type="button" className="rx-button" data-inv-remove-yes="true" disabled={inFlight} onClick={() => void submit("remove")}>Remove</button>{" "}
                <button type="button" className="rx-button rx-button-secondary" onClick={() => setConfirmRemove(false)}>Keep</button></span>)}
          </div>
          <StatusNote status={status} />
        </>
      )}

      {isHistorical && data.funding.length > 0 && (
        <details className="rcm-details"><summary>Historical Run actual equity funding (reference)</summary>
          <table className="rcm-table rcm-draws" data-inv-funding="true"><thead><tr><th scope="col" className="rcm-left">Exact cash date</th><th scope="col">Paid-in kEUR</th></tr></thead>
            <tbody>{data.funding.map((f) => <tr key={f.date}><td className="rcm-left">{f.date}</td><td>{money(f.paid_in_keur)}</td></tr>)}</tbody></table></details>
      )}

      <h4 className="rcm-h4" data-investor-evidence-heading="true">
        {isHistorical
          ? `Historical investor evidence — Run ${histRunLabel}`
          : `Investor evidence from the ${data.state === "CURRENT" ? "last Run" : "last Run (not the current inputs)"}`}{" "}
        <span className="rcm-badge rcm-badge-derived">DERIVED · READ ONLY</span>
      </h4>
      {data.evidence ? (
        <>
          <p className="rx-note" data-investor-binding="true">Run {data.evidence.snapshot_id} · agreement {data.evidence.agreement.agreement_id} v{data.evidence.agreement.version} · EUR / kEUR · <a href={data.export_url}>Export {isHistorical ? "historical" : "Run-bound"} investor workbook</a></p>
          <div className="rcm-scroll" tabIndex={0} role="region" aria-label="Investor capital accounts (scrolls horizontally)">
            <table className="rcm-table" data-investor-evidence="true">
              <thead><tr><th scope="col" className="rcm-left rcm-sticky">Investor</th><th scope="col">Ownership</th><th scope="col">Paid-in kEUR</th><th scope="col">Uncalled kEUR</th><th scope="col">Returned capital kEUR</th><th scope="col">Residual cash kEUR</th><th scope="col">Unreturned paid-in kEUR</th><th scope="col">DPI / realized MOIC</th><th scope="col">XIRR</th></tr></thead>
              <tbody>{data.evidence.investors.map((i) => (
                <tr key={i.investor_id} data-evidence-row={i.investor_id}>
                  <th scope="row" className="rcm-left rcm-sticky">{i.investor_id}</th><td>{pct(i.ownership_fraction)}</td><td>{money(i.total_paid_in_keur)}</td><td>{money(i.uncalled_capital_keur)}</td>
                  <td>{money(i.returned_capital_keur)}</td><td>{money(i.residual_distributions_keur)}</td><td>{money(i.unreturned_paid_in_keur)}</td>
                  <td>{i.dpi === null ? "UNAVAILABLE" : `${i.dpi.toFixed(3)}x`}</td><td>{i.xirr === null ? i.xirr_status : pct(i.xirr)}</td>
                </tr>))}</tbody>
            </table>
          </div>
          <p className="rx-note">Realized MOIC = cumulative net cash distributions ÷ actual paid-in capital; no NAV or total-value multiple. Return of capital is zero under residual-only terms.</p>
        </>
      ) : <p className="rx-empty" role="status" data-investor-evidence-unavailable="true">{data.unavailable}</p>}

      {data.history && data.history.length > 0 && (
        <details className="rcm-details" data-investor-history="true">
          <summary>Immutable investor Run History ({data.history.length})</summary>
          {pendingHistoryTarget !== undefined && (
            <div className="rx-status rx-status-conflict" role="alertdialog" aria-label="Unsaved working draft confirmation" data-inv-history-dirty-prompt="true">
              <p>You have unsaved working agreement edits. Switching to a historical Run enters read-only mode.</p>
              <div className="rcm-actions-row">
                <button
                  type="button"
                  className="rx-button rx-button-secondary"
                  data-inv-history-keep-draft="true"
                  onClick={() => {
                    const target = pendingHistoryTarget;
                    setPendingHistoryTarget(undefined);
                    setStatus(null);
                    setSelectedHistoryId(target ?? null);
                  }}
                >
                  View history (keep unsaved draft)
                </button>
                <button
                  type="button"
                  className="rx-button"
                  data-inv-history-discard-draft="true"
                  onClick={() => {
                    const target = pendingHistoryTarget;
                    setPendingHistoryTarget(undefined);
                    setDraft(workingBaseline);
                    setStatus(null);
                    setSelectedHistoryId(target ?? null);
                  }}
                >
                  Discard draft &amp; view history
                </button>
                <button
                  type="button"
                  className="rx-button rx-button-secondary"
                  data-inv-history-cancel="true"
                  onClick={() => setPendingHistoryTarget(undefined)}
                >
                  Cancel
                </button>
              </div>
            </div>
          )}
          <ul>
            <li>
              <button type="button" className="rx-button rx-button-secondary" data-inv-history-current="true"
                disabled={!data.selected_history_id && selectedHistoryId === null}
                onClick={() => requestHistorySelection(null)}>
                Last Run / Working agreement
              </button>
            </li>
            {data.history.map((run) => (
              <li key={run.history_id}>
                <button type="button" className="rx-button rx-button-secondary" data-inv-history-id={run.history_id}
                  disabled={data.selected_history_id === run.history_id}
                  onClick={() => requestHistorySelection(run.history_id)}>
                  {run.ran_at} · {run.scenario_name} · {run.has_investor_evidence ? "Investor evidence" : "No F4 agreement"}
                </button>
              </li>
            ))}
          </ul>
        </details>
      )}

      {!isHistorical && (
        <>
          <h4 className="rcm-h4">Sponsor funding &amp; shareholder loan <span className="rcm-badge rcm-badge-derived">READ ONLY</span></h4>
          <p className="rx-note" data-shl-readonly="true">No shareholder-loan control is editable under the released authority. These are the typed financing inputs and the last Run; undistributed shareholder-loan proceeds are not share-capital returns.</p>
          <dl className="rcm-facts" data-sponsor-facts="true">
            <div><dt>Funding mode</dt><dd>{sponsor.mode}</dd></div>
            {[...sponsor.equity, ...sponsor.other, ...sponsor.shl].map((m) => <Metric key={m.label} m={m} />)}
            <div><dt>SHL repayment</dt><dd>{sponsor.repayment}</dd></div>
            <div><dt>SHL day count</dt><dd>{sponsor.day_count}</dd></div>
            <div><dt>Principal eligibility starts (period)</dt><dd>{sponsor.eligibility ?? "—"}</dd></div>
            <div><dt>SHL maturity (period)</dt><dd>{sponsor.maturity ?? "—"}</dd></div>
          </dl>
        </>
      )}

      {isHistorical && (
        <>
          <h4 className="rcm-h4">Historical financing assumptions <span className="rcm-badge rcm-badge-derived">UNAVAILABLE IN HISTORY</span></h4>
          <p className="rx-empty" role="status" data-sponsor-inputs-unavailable="true">
            {sponsor.inputs_unavailable_reason || "Historical financing input assumptions are not persisted in Run History; current working inputs are omitted."}
          </p>
        </>
      )}

      <h4 className="rcm-h4" data-sponsor-returns-heading="true">
        {isHistorical
          ? `Historical Run sponsor returns — ${histRunLabel}`
          : "Returns — Project IRR is not Pure Equity IRR is not Total Sponsor IRR"}
      </h4>
      <dl className="rcm-facts" data-sponsor-returns="true">{sponsor.returns.map((m) => <Metric key={m.label} m={m} />)}</dl>
      <h4 className="rcm-h4">Not released</h4>
      <ul className="rcm-closed" data-investors-closed="true">{data.not_released.map((n) => <li key={n}>{n}</li>)}</ul>
    </section>
  );
}
