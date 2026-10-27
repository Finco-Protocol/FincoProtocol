// RC-UX Addendum B — one place for the words a financial user sees.
//
// Internal terms (canonical authority, composite hash, CAS, snapshot, freshness ...) stay in the data, the audit trail and the stable error
// codes; the ordinary UI shows the business meaning.  Established project-finance terms (DSCR, LLCR, IRR, NPV, PPA, CAPEX, OPEX ...) are
// legitimate vocabulary and are never replaced here.

import { useState, type ReactNode } from "react";

/** Run freshness as a financial user reads it.  The raw state stays in `data-*` attributes and in the audit trail. */
export const RESULT_STATUS: Record<string, string> = {
  CURRENT: "Results up to date",
  STALE: "Results outdated",
  NOT_RUN: "Not run yet",
  UNKNOWN: "Status unavailable",
};
export const resultStatus = (state: string | null | undefined): string => RESULT_STATUS[state ?? ""] ?? "Status unavailable";

/** Run-state text of the Run History projection ("LAST RUN · CURRENT", "HISTORICAL" ...) as a financial user reads it. */
export function runStateLabel(state: string | null | undefined): string {
  const s = (state ?? "").toUpperCase();
  if (s.includes("CURRENT")) return "Last Run · results up to date";
  if (s.includes("STALE")) return "Last Run · results outdated";
  if (s.includes("HISTORICAL")) return "Earlier Run";
  return state ? state : "Status unavailable";
}

/** Display text supplied by the server, cleaned of implementation vocabulary.  Used only for descriptive copy, never for numbers. */
export function plain(text: string | null | undefined): string {
  return (text ?? "")
    .replace(/\bWorking Copy\b/g, "Project").replace(/\bworking copy\b/g, "project")
    .replace(/\bReference model\b/g, "The starting model").replace(/\breference model\b/g, "starting model")
    .replace(/\s*\((legacy|derived) key\)/gi, "")
    .replace(/\bcanonical (clean )?/gi, "").replace(/\bPersisted\b/g, "Saved").replace(/\bpersisted\b/g, "saved");
}

/** Where a figure comes from, in business words.  The exact internal path stays available as a tooltip / in the audit trail. */
export function dataSourceLabel(source: string | null | undefined): string {
  const s = source ?? "";
  if (!s) return "—";
  if (s.startsWith("runtime_summary.financing_evidence")) return "Financing results";
  if (s.startsWith("runtime_summary")) return "Run results";
  if (s.startsWith("sponsor_schedule")) return "Sponsor returns";
  if (s.startsWith("debt_schedule")) return "Debt schedule";
  if (s.startsWith("distribution_schedule")) return "Distribution schedule";
  if (s.startsWith("financial_statements")) return "Financial statements";
  return /_|\./.test(s) ? "Run results" : s;
}

/** One-sentence explanation shown next to the status. */
export const RESULT_STATUS_HELP: Record<string, string> = {
  CURRENT: "The results were calculated from the inputs as they are saved now.",
  STALE: "Inputs changed after the last Run. The figures shown are from that earlier Run — run the model to update them.",
  NOT_RUN: "The model has not been run yet.",
};

/** Business wording for stable internal error codes.  Codes are preserved in the technical details and in tests. */
const FRIENDLY: Array<[RegExp, string]> = [
  [/CAS|VERSION_MISMATCH|CONFLICT|STALE_PREVIEW|SELECT_BASE_FIRST|SCENARIO_SWITCH/i, "This project was changed elsewhere. Reload the latest version before saving."],
  [/CSRF|TOKEN/i, "Your session security check expired. Reload the page and try again — nothing was changed."],
  [/AUTH_REQUIRED|UNAUTHORI[SZ]ED|SESSION/i, "Your session has expired. Sign in again — nothing was changed."],
  [/INVALID_COD|RELATIVE_PERIOD|OUTSIDE_TIMELINE|DATE_OUTSIDE/i, "The selected date is outside the project's supported financing timeline. Choose a date within the available period."],
  [/SCALAR_SHOCK_UNSUPPORTED|SHOCK_UNSUPPORTED|DRIVER_UNSUPPORTED/i, "This assumption cannot be adjusted in the selected financial configuration."],
  [/WEIGHT_SUM_INVALID/i, "The monthly percentages must add up to exactly 100%."],
  [/PERIOD_COUNT_MISMATCH/i, "Enter one percentage for every construction month."],
  [/WEIGHT_NEGATIVE|WEIGHT_INVALID|WEIGHT_NON_FINITE/i, "Monthly percentages must be numbers of zero or more."],
  [/MILESTONE_MONTH_INVALID/i, "The milestone month must be within the construction period."],
  [/DURATION_INVALID/i, "The construction duration is not available for this project."],
  [/READ_ONLY|PROTECTED|PROJECT_READ_ONLY/i, "This project cannot be edited. Nothing was changed."],
  [/PROJECT_NOT_FOUND|NOT_FOUND/i, "This project could not be found in your account."],
  [/MODEL_BUSY|BUSY/i, "The model is busy. Wait a moment and try again."],
  [/RATE_LIMITED/i, "Too many requests in a short time. Wait a moment and try again."],
  [/RUN_NOT_FOUND|RUN_HISTORY_UNAVAILABLE|RUN_EVIDENCE_UNAVAILABLE/i, "The saved results for this Run could not be read. Nothing was changed."],
  [/EXPLICIT_RUN_SELECTION_REQUIRED/i, "Select two or three Runs to compare."],
  [/PREVIEW_ACKNOWLEDGEMENT_REQUIRED/i, "Confirm that you understand the limitations of this preview technology to continue."],
  [/REQUEST_ID_REUSED|CREATE_IN_FLIGHT|OUTCOME_UNKNOWN|REQUEST_ID_CONSUMED/i, "We could not confirm whether the project was created. Check My Projects before creating it again."],
  [/SERVER_UNREACHABLE/i, "The server could not be reached. Check your connection — nothing was changed."],
];

/** True for text that is a bare code or carries implementation jargon: such text is never shown as the main message. */
export function looksTechnical(message: string | null | undefined): boolean {
  const m = (message ?? "").trim();
  if (!m) return true;
  return /^[A-Z][A-Z0-9_]{3,}(\b|:)/.test(m) || /\bHTTP[_ ]?\d{3}\b|v2_err|\bcanonical\b|\bcomposite\b|\bCAS\b|\bsnapshot\b|_[A-Z]{2,}_/i.test(m);
}

/** Plain-language message.  A human sentence from the server is kept; a bare code or jargon is replaced by the business wording for that
 *  code, and an unknown code never reaches the user as a bare token. */
export function friendlyMessage(code: string | null | undefined, serverMessage?: string | null, fallback = "Something went wrong. Nothing was changed."): string {
  if (serverMessage && serverMessage.trim() && !looksTechnical(serverMessage)) return serverMessage.trim();
  if (code) for (const [pattern, text] of FRIENDLY) if (pattern.test(code)) return text;
  if (serverMessage && serverMessage.trim() && !/^[A-Z0-9_ :.-]+$/.test(serverMessage.trim())) return serverMessage.trim();
  return fallback;
}

/** A message plus an expandable technical-details panel.  The stable code stays available for support and audit. */
export function FriendlyError({ code, message, role = "alert", className = "rx-status rx-status-error", children }: {
  code?: string | null; message?: string | null; role?: "alert" | "status"; className?: string; children?: ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const text = friendlyMessage(code, message);
  const technical = (code && code !== text) || (message && message !== text);
  return (
    <div className={className} role={role} data-error-code={code || undefined}>
      <span>{text}</span>
      {children}
      {technical && (
        <details open={open} onToggle={(e) => setOpen((e.target as HTMLDetailsElement).open)} className="rx-tech-details" data-technical-details="true">
          <summary>Technical details</summary>
          <p className="fm-mono">{code ? `Code: ${code}` : ""}{code && message ? " · " : ""}{message && message !== text ? message : ""}</p>
        </details>
      )}
    </div>
  );
}
