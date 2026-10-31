import { FriendlyError } from "./productLanguage";

/** How a failed Run is explained.  Presentation only: the server's refusal is never overridden and nothing is retried here. */
export type RunFailureKind = "SHL" | "TIMELINE" | "FINANCING" | "INPUTS" | "TRANSIENT" | "CONFLICT" | "EXECUTION" | "REFUSED";

export interface RunFailureView {
  kind: RunFailureKind;
  /** True only for a failure the server reports as transient (busy or timed out, or a changed project). A financial refusal is never retryable. */
  retryable: boolean;
  guidance: string;
  /** Hash destinations that exist in the workspace (`workspaceNavigation.ts`, `WorkspaceNav.tsx`). */
  links: ReadonlyArray<{ href: string; label: string }>;
}

const INPUTS = { href: "#inputs", label: "the saved inputs" } as const;
const PROJECT = { href: "#inputs/project", label: "Project & Timeline" } as const;
const FINANCING = { href: "#financing", label: "Financing / Equity" } as const;
const CHECKS = { href: "#diagnostics", label: "Model checks" } as const;

/**
 * Classifies from the typed envelope the server already sends (`error_code` of the Run intent and its user-safe `message`).
 * `error_code` is one of ADMISSION_REFUSED, ENGINE_TIMEOUT, ENGINE_FAILED, FINANCIAL_REFUSED, FINAL_CAS_CONFLICT, CANCELLED; the
 * reviewed refusal wording (shareholder loan, F3 facility rules, period grid) arrives in `message`.
 */
export function classifyRunFailure(code: string | undefined, message: string): RunFailureView {
  const text = `${code || ""} ${message}`;
  if (/SHL_MATURITY|shareholder.loan.*(?:matur|repa|residual|unpaid)/i.test(text)) {
    return { kind: "SHL", retryable: false, links: [FINANCING, CHECKS],
      guidance: "The shareholder loan cannot be repaid under the current model terms. Review its maturity and available cash in Financing / Equity. Terms that are read-only need Financial Owner review; this screen cannot override the refusal. The previous Last Run is preserved." };
  }
  if (/PERIOD_GRID|horizon|timeline/i.test(text)) {
    return { kind: "TIMELINE", retryable: false, links: [PROJECT, FINANCING, CHECKS],
      guidance: "The saved dates do not fit the model's period grid. Adjust the project timeline, then Run again. Running again without a change gives the same result." };
  }
  if (/\bF3_|gearing cap|facility|Senior service|financing structure/i.test(text)) {
    return { kind: "FINANCING", retryable: false, links: [FINANCING, INPUTS, CHECKS],
      guidance: "The financing terms stopped this Run as a financial constraint, not a system fault. Change the facility or cash inputs; running again without a change gives the same result. The previous Last Run is preserved." };
  }
  if (/ADMISSION_REFUSED|ENGINE_TIMEOUT/i.test(text)) {
    return { kind: "TRANSIENT", retryable: true, links: [CHECKS],
      guidance: "Nothing was calculated or saved and the inputs are unchanged. It is safe to choose Run model again shortly. The previous Last Run is preserved." };
  }
  if (/FINAL_CAS_CONFLICT/i.test(text)) {
    return { kind: "CONFLICT", retryable: true, links: [INPUTS],
      guidance: "The project changed while the model was running, so nothing was saved. Use Reload to read the latest saved version, review it, then Run again." };
  }
  if (/\b(incomplete|missing|not runnable|not classified|required input)\b/i.test(text)) {
    return { kind: "INPUTS", retryable: false, links: [INPUTS, PROJECT, CHECKS],
      guidance: "The saved inputs are incomplete or not runnable. Complete the required inputs, save them, then Run again. Nothing is estimated for missing values." };
  }
  if (/FINANCIAL_REFUSED|integrity checks stopped|FAIL_CLOSED/i.test(text)) {
    return { kind: "REFUSED", retryable: false, links: [INPUTS, FINANCING, CHECKS],
      guidance: "The model's checks refused these inputs, so no result was produced. Review your recent changes first; running again without a change gives the same result. The previous Last Run is preserved." };
  }
  return { kind: "EXECUTION", retryable: false, links: [INPUTS, CHECKS],
    guidance: "The calculation did not complete and nothing was saved. The previous Last Run is preserved. If a second Run fails the same way, contact support and quote the reference shown above." };
}

/** Only the server's already-safe typed failure reaches this presentation layer. */
export function RunFailureNotice({ code, message }: { code?: string; message: string }) {
  const view = classifyRunFailure(code, message);
  return <div data-run-failure="true" data-run-failure-kind={view.kind} data-run-failure-retryable={view.retryable ? "true" : "false"}>
    <FriendlyError code={code} message={message} />
    <p className="rx-note" data-run-failure-guidance="true">{view.guidance}</p>
    <p className="rx-note" data-run-failure-links="true">Review {view.links.map((link, index) =>
      <span key={link.href}>{index > 0 && " · "}<a href={link.href}>{link.label}</a></span>)}.</p>
  </div>;
}
