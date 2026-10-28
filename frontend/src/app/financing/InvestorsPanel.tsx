import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import "../../styles/rcm-financing.css";
import { StatusNote, useReportDirty, useReportPending, useSingleFlight, useUnresolvedLock, type StatusMessage } from "../workflow/workflowShared";
import { draftFromTerms, isSame, serializeAgreement, type AgreementDraft } from "./serializeAgreement";
import type { InvestorPayload, SponsorMetric } from "./types";

type Read = { ok: true; data: InvestorPayload } | { ok: false; code: string; message?: string };

async function fetchInvestors(project: string): Promise<Read> {
  try {
    const response = await fetch(`/v2/model-react/investors/agreement?project=${encodeURIComponent(project)}`, { credentials: "same-origin", headers: { Accept: "application/json" } });
    const body = await response.json().catch(() => null) as (InvestorPayload | { code?: string; message?: string }) | null;
    if (response.ok && body && (body as { ok?: boolean }).ok) return { ok: true, data: body as InvestorPayload };
    const failed = (body ?? {}) as { code?: string; message?: string };
    return { ok: false, code: failed.code || `HTTP_${response.status}`, message: failed.message };
  } catch {
    return { ok: false, code: "SERVER_UNREACHABLE", message: "The FINCO Model server is unreachable." };
  }
}

const pct = (v: number | null, digits = 2) => (v === null ? null : `${(v * 100).toFixed(digits)}%`);
const money = (v: number | null) => (v === null ? "UNAVAILABLE" : v.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 }));

function Metric({ m }: { m: SponsorMetric }) {
  return <div data-sponsor-metric={m.label}><dt>{m.label}</dt><dd>{m.display}{m.value === null && m.reason && <span className="rcm-reason">{m.reason}</span>}</dd></div>;
}

/** Investor & sponsor agreement: typed common-equity holders and actual paid-in capital, saved through the canonical F4 route
 *  (session CSRF, composite-hash CAS, agreement-version CAS); Run-bound evidence and the shareholder-loan facts are read-only. */
export function InvestorsPanel({ project, reloadKey, onSaved }: { project: string; reloadKey: number; onSaved: () => void }) {
  const [read, setRead] = useState<Read | null>(null);
  const [draft, setDraft] = useState<AgreementDraft>({ agreementId: "", investors: [], contributions: [] });
  const [status, setStatus] = useState<StatusMessage | null>(null);
  const [inFlight, setInFlight] = useState(false);
  const [confirmRemove, setConfirmRemove] = useState(false);
  const [locked, setLocked] = useUnresolvedLock("sheet-debt-investors");
  const singleFlight = useSingleFlight();
  const shown = useRef("");

  const load = useCallback(async () => {
    const result = await fetchInvestors(project);
    setRead(result);
    return result;
  }, [project]);
  useEffect(() => { void load(); }, [load, reloadKey]);

  const data = read && read.ok ? read.data : null;
  const baseline = useMemo(() => draftFromTerms(data?.terms ?? null), [data]);
  // a new authoritative agreement replaces the draft; an edited draft is never rebased silently (the CAS refuses a stale Save)
  useEffect(() => {
    const key = JSON.stringify(baseline);
    if (shown.current !== key) { shown.current = key; setDraft(baseline); }
  }, [baseline]);

  const dirty = !isSame(draft, baseline);
  useReportDirty("sheet-debt-investors", dirty ? 1 : 0);
  useReportPending("sheet-debt-investors", inFlight || locked);

  const edit = (next: AgreementDraft) => { setDraft(next); setStatus(null); };
  const ownershipTotal = draft.investors.reduce((sum, r) => sum + (r.ownershipPct.trim() === "" ? 0 : Number(r.ownershipPct) || 0), 0);

  const submit = useCallback(async (action: "save" | "remove") => {
    if (!data) return;
    await singleFlight(async () => {
      setInFlight(true); setStatus(null);
      try {
        const body = new URLSearchParams({
          project, csrf_token: data.save.csrf_token, content_hash: data.identity.content_hash,
          agreement: action === "save" ? serializeAgreement(draft, { agreementId: data.save.saved_agreement_id, nextVersion: data.save.next_version }) : "",
          action,
        });
        let response: Response;
        try {
          response = await fetch(data.save.url, { method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/x-www-form-urlencoded", "HX-Request": "true" }, body: body.toString() });
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
          setStatus({ tone: response.status === 409 ? "conflict" : "error", text: `${failure?.error || "The agreement could not be saved."} Nothing was changed.` });
          if (response.status === 409) void load();
          return;
        }
        const fresh = await load();
        const expectedVersion = data.save.next_version;
        const confirmed = fresh.ok && (action === "remove" ? fresh.data.terms === null
          : fresh.data.terms !== null && fresh.data.terms.agreement_id === draft.agreementId && fresh.data.terms.version === (draft.agreementId === data.save.saved_agreement_id ? expectedVersion : 1));
        if (!confirmed) { setLocked(true); setStatus({ tone: "conflict", text: "Result UNKNOWN — the server accepted the request but the fresh read could not confirm it. Reload to reconcile." }); return; }
        setStatus({ tone: "ok", text: action === "save" ? "Agreement saved and read back. It is NOT in any Run yet — press Run to produce investor evidence." : "Working agreement removed." });
        onSaved();
      } finally { setInFlight(false); setConfirmRemove(false); }
    });
  }, [data, draft, project, load, singleFlight, setLocked, onSaved]);

  if (!read) return <section className="rx-card"><p className="rx-boot-loading" role="status">Loading the investor agreement…</p></section>;
  if (!read.ok || !data) return <section className="rx-card" data-investors-state="error"><h3 className="rcm-h3">Investors &amp; sponsor</h3><p className="rx-empty" role="alert">{(read as { message?: string }).message || "The investor view is unavailable right now. Nothing was changed."}</p></section>;

  const disabled = !data.editable || locked || inFlight;
  const sponsor = data.sponsor;
  return (
    <section className="rx-card rcm-fin" data-investors-panel="true" data-investor-workflow={data.workflow.state} aria-labelledby="rcm-inv-title">
      <h3 id="rcm-inv-title" className="rcm-h3">Common-equity investor agreement <span className="rcm-badge" data-investor-state={data.state}>{data.state}</span></h3>
      <p className="rx-note">Residual common equity only. <strong>Ownership %</strong> allocates results between investors and does not change Sources &amp; Uses; <strong>commitments and paid-in capital</strong> describe funding and must reconcile with the equity in the financing plan before Run.</p>
      <p className="rx-status rx-status-conflict" role="status" data-investor-workflow-text="true">{data.workflow.text}</p>
      {!data.editable && <p className="rx-status rx-status-conflict" data-investors-readonly="true">Read-only: templates cannot be edited. Start a project from this template to define an agreement.</p>}
      {locked && <p className="rx-status rx-status-conflict" role="alert" data-investors-locked="true">A previous save has an unknown outcome. Reload the workspace to reconcile before editing again.</p>}

      <fieldset className="rcm-fieldset" disabled={disabled}>
        <legend>Agreement &amp; holders</legend>
        <label className="rcm-field">Agreement ID
          <input data-inv="agreement_id" maxLength={128} value={draft.agreementId} onChange={(e) => edit({ ...draft, agreementId: e.target.value })} /></label>
        <p className="rx-note">Saved version {data.terms ? data.terms.version : "— (none)"} · working scenario {data.identity.scenario_name || "Base"} · next Save writes version {draft.agreementId === data.save.saved_agreement_id ? data.save.next_version : 1}.</p>
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
        <button type="button" className="rx-button rx-button-secondary" data-inv-discard="true" disabled={disabled || !dirty} onClick={() => { setDraft(baseline); setStatus(null); }}>Discard changes</button>
        {data.terms && (!confirmRemove
          ? <button type="button" className="rx-button rx-button-secondary" data-inv-remove="true" disabled={disabled} onClick={() => setConfirmRemove(true)}>Remove working agreement…</button>
          : <span role="group" aria-label="Confirm removal">Remove the working agreement? <button type="button" className="rx-button" data-inv-remove-yes="true" disabled={inFlight} onClick={() => void submit("remove")}>Remove</button>{" "}
            <button type="button" className="rx-button rx-button-secondary" onClick={() => setConfirmRemove(false)}>Keep</button></span>)}
      </div>
      <StatusNote status={status} />

      <h4 className="rcm-h4">Investor evidence from the {data.state === "CURRENT" ? "last Run" : "last Run (not the current inputs)"} <span className="rcm-badge rcm-badge-derived">DERIVED · READ ONLY</span></h4>
      {data.evidence ? (
        <>
          <p className="rx-note" data-investor-binding="true">Run {data.evidence.snapshot_id} · agreement {data.evidence.agreement.agreement_id} v{data.evidence.agreement.version} · EUR / kEUR · <a href={data.export_url}>Export Run-bound investor workbook</a></p>
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
      <h4 className="rcm-h4">Returns — Project IRR is not Pure Equity IRR is not Total Sponsor IRR</h4>
      <dl className="rcm-facts" data-sponsor-returns="true">{sponsor.returns.map((m) => <Metric key={m.label} m={m} />)}</dl>
      <h4 className="rcm-h4">Not released</h4>
      <ul className="rcm-closed" data-investors-closed="true">{data.not_released.map((n) => <li key={n}>{n}</li>)}</ul>
    </section>
  );
}
