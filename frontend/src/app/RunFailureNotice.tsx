import { FriendlyError } from "./productLanguage";

/** Only the server's already-safe typed failure reaches this presentation layer. */
export function RunFailureNotice({ code, message }: { code?: string; message: string }) {
  const shareholderLoan = /SHL_MATURITY|shareholder.loan.*(?:matur|repa|residual)/i.test(`${code || ""} ${message}`);
  const timing = /PERIOD_GRID|horizon|timeline/i.test(`${code || ""} ${message}`);
  return <div data-run-failure="true">
    <FriendlyError code={code} message={message} />
    {shareholderLoan && <p className="rx-note">The shareholder loan cannot be repaid under the current model terms. Review its maturity and available cash in Financing / Equity. Terms that are read-only need Financial Owner review; this screen cannot override the refusal. The previous Last Run is preserved.</p>}
    <p className="rx-note">Review {timing ? <a href="#inputs/project">Project & Timeline</a> : <a href="#inputs">the saved inputs</a>}
      {" · "}<a href="#financing">Financing / Equity</a>{" · "}<a href="#diagnostics">Model checks</a>.</p>
  </div>;
}
