import { useState } from "react";
import { FriendlyError } from "../productLanguage";
import { isFailure, requestCertificate, requestReferenceRegression, type TrustCertificate, type TrustFailure, type TrustValidation } from "./api";

const dash = (v: string | number | null | undefined) => (v === null || v === undefined || v === "" ? "—" : String(v));
const yesNo = (v: boolean | null | undefined) => (v === null || v === undefined ? "—" : v ? "yes" : "no");

const CERTIFICATE_UNAVAILABLE: Record<string, string> = {
  SIGNING_KEY_UNAVAILABLE: "Run certificates are not available in this environment yet.",
  COMMITTED_LAST_RUN_REQUIRED: "Run the model first. A certificate describes a saved Run.",
};

/** Trust > the two evidence requests that used to open classic pages.  Both are explicit: nothing is requested while the page renders,
 *  and both results are shown here.  The reference regression is regression protection for the reference library — never a validation of
 *  this project; a certificate proves a Run is unaltered, never that it is correct (it is not FINCO Verify). */
export function TrustEvidence({ project, hasRun }: { project: string; hasRun: boolean }) {
  const [busy, setBusy] = useState<"" | "validation" | "certificate">("");
  const [validation, setValidation] = useState<TrustValidation | null>(null);
  const [certificate, setCertificate] = useState<TrustCertificate | null>(null);
  const [failure, setFailure] = useState<{ which: "validation" | "certificate"; error: TrustFailure } | null>(null);

  async function load(which: "validation" | "certificate") {
    if (busy) return;
    setBusy(which); setFailure(null);
    if (which === "validation") {
      const r = await requestReferenceRegression(project);
      if (isFailure(r)) setFailure({ which, error: r }); else setValidation(r);
    } else {
      const r = await requestCertificate(project);
      if (isFailure(r)) setFailure({ which, error: r }); else setCertificate(r);
    }
    setBusy("");
  }

  return (
    <>
      <section className="fm-card fm-section" aria-label="Reference regression evidence" data-trust-panel="validation">
        <div className="fm-card-title"><h3>Reference regression evidence</h3><span>{validation ? validation.state : hasRun ? "ON REQUEST" : "UNAVAILABLE"}</span></div>
        <p className="fm-info-note">Reference regression only; it is not a validation of this project or its Run. It is not run by opening this page.</p>
        {hasRun
          ? <button type="button" className="fm-btn" data-trust-load="validation" disabled={busy !== ""} aria-busy={busy === "validation"} onClick={() => void load("validation")}>
              {busy === "validation" ? "Running the reference regression…" : validation ? "Run it again" : "Run the reference regression (separate evidence)"}
            </button>
          : <p className="fm-info-note" data-trust-unavailable="validation">Run the model first. The reference regression is requested for a saved Run.</p>}
        {failure?.which === "validation" && (
          failure.error.code === "MODEL_BUSY"
            ? <p className="fm-info-note" role="status" data-trust-busy="true">The model is busy right now. Try again in a few seconds.</p>
            : <FriendlyError code={failure.error.code} message={failure.error.message} />)}
        {validation && (validation.state === "AVAILABLE"
          ? <div data-trust-result="validation">
              <p className="fm-info-note">It re-runs the reference models against pinned expected values. It does not independently validate your project's Run and does not establish accounting, debt or cash integrity.</p>
              <table className="fm-table"><tbody>
                <tr><th scope="row">Regression state</th><td data-trust-validation-state="true">{dash(validation.validation_state)}</td></tr>
                <tr><th scope="row">Checks passed / failed</th><td>{dash(validation.pass_count)} / {dash(validation.fail_count)}</td></tr>
                <tr><th scope="row">Framework passed</th><td>{yesNo(validation.framework_passed)}</td></tr>
                <tr><th scope="row">Product reconciled</th><td>{yesNo(validation.product_reconciled)}</td></tr>
              </tbody></table>
              {validation.gaps.length > 0 && <p className="fm-info-note">Known gaps ({dash(validation.gap_count)}): {validation.gaps.map((g) => dash(g.name)).join(" · ")}</p>}
              <details className="rx-tech-details"><summary>Advanced details / Audit trail</summary><p className="fm-mono">{dash(validation.authority)}</p></details>
            </div>
          : <p className="fm-info-note" role="status" data-trust-result="validation" data-trust-state="unavailable">
              Unavailable. {validation.reason === "COMMITTED_LAST_RUN_REQUIRED" ? "There is no saved Run yet." : "No reference regression evidence is available for this project. This is an intentional unavailable state, not an error."}
            </p>)}
      </section>

      <section className="fm-card fm-section" aria-label="Run certificate" data-trust-panel="certificate">
        <div className="fm-card-title"><h3>Run certificate</h3><span>{certificate ? certificate.state : hasRun ? "ON REQUEST" : "UNAVAILABLE"}</span></div>
        <p className="fm-info-note">Provenance only; it shows that the saved Run has not been altered. It is not an independent verification of the results.</p>
        {hasRun
          ? <button type="button" className="fm-btn" data-trust-load="certificate" disabled={busy !== ""} aria-busy={busy === "certificate"} onClick={() => void load("certificate")}>
              {busy === "certificate" ? "Requesting the certificate…" : certificate ? "Request it again" : "Request certificate"}
            </button>
          : <p className="fm-info-note" data-trust-unavailable="certificate">Run the model first. A certificate describes a saved Run.</p>}
        {failure?.which === "certificate" && <FriendlyError code={failure.error.code} message={failure.error.message} />}
        {certificate && (certificate.state === "AVAILABLE"
          ? <div data-trust-result="certificate">
              <table className="fm-table"><tbody>
                <tr><th scope="row">Issued at</th><td>{dash(certificate.issued_at)}</td></tr>
                <tr><th scope="row">Run</th><td className="fm-mono">{dash(certificate.snapshot_id)}</td></tr>
                <tr><th scope="row">Workbook version</th><td>{dash(certificate.workbook_version)}</td></tr>
                {certificate.engine_version && <tr><th scope="row">Engine version</th><td>{certificate.engine_version}</td></tr>}
                <tr><th scope="row">Scenario inputs applied</th><td>{certificate.effective_input_status === "EFFECTIVENESS_NOT_ESTABLISHED" || !certificate.effective_input_status ? "Not established for this Run" : certificate.effective_input_status}</td></tr>
              </tbody></table>
              <p className="fm-info-note">The signature shows that the saved Run is unaltered, not that scenario changes were applied.</p>
              <details className="rx-tech-details"><summary>Advanced details / Audit trail</summary>
                <p className="fm-mono">Schema {dash(certificate.schema_version)} · issuer {dash(certificate.issuer)} · composite hash {dash(certificate.composite_hash_short)} · key {dash(certificate.key_id)} · {dash(certificate.signature_algorithm)} · payload digest {dash(certificate.payload_digest)} · origin {dash(certificate.run_origin)}</p>
                <p className="fm-mono">{dash(certificate.authority)}</p>
              </details>
            </div>
          : <p className="fm-info-note" role="status" data-trust-result="certificate" data-trust-state="unavailable">
              Unavailable. {CERTIFICATE_UNAVAILABLE[certificate.reason ?? ""] ?? "The certificate could not be issued. Run the model again and retry."}
            </p>)}
      </section>
    </>
  );
}
