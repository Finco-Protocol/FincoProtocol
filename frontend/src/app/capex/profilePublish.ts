// PR2c — pure decision machine for the combined-save completion observer.
//
// The mounted provider (ProfileDraftProvider) owns the effects; THIS module owns the
// honest classification of what a disappearance of the staged profile edit means.
// It never retries, never guesses, and never treats an HTTP success as proof: every
// outcome is decided against a fresh authoritative read (`fresh`) and the authored
// session (the identity and server token the document was actually staged under).
import type { SavedRow } from "./types";
import { sameProfileDocument } from "./profileDraft";

/** One authoring session: from the first publication of a dirty profile draft until it
 *  is committed, reverted or explicitly reconciled.  `baselineExpected` records the
 *  saved profile rows the draft was authored against (for the external-clear verdict). */
export interface AuthoredSession {
  authoredHash: string;
  baseToken: string;
  submission: { project: string; scope: string; expected: Record<string, SavedRow> };
  baselineExpected: Record<string, SavedRow>;
}

export interface FreshProfiles {
  project: { code: string };
  save: { content_hash: string; scenario_id: string };
  saved: { rows: Record<string, SavedRow>; error: unknown };
}

export type DisappearanceOutcome =
  /** The combined save committed: the fresh saved document matches exactly what was published. */
  | { kind: "committed" }
  /** Nothing was written since authoring (same composite hash): an explicit revert/discard of the staged mirror. */
  | { kind: "reverted" }
  /** The workbook identity advanced while the saved profile document is unchanged: an external
   *  change cleared the staged mirror.  The draft is retained; the user reconciles and re-stages. */
  | { kind: "unstaged" }
  /** Anything else: outcome UNKNOWN.  Lock for human reconciliation; no speculative resubmit. */
  | { kind: "unknown" };

export function decideDisappearance(session: AuthoredSession | null, fresh: FreshProfiles | null): DisappearanceOutcome {
  if (!fresh || !session) return { kind: "unknown" };
  const scope = `${fresh.project.code}|${fresh.save.scenario_id}`;
  if (fresh.project.code === session.submission.project && scope === session.submission.scope
      && !fresh.saved.error && sameProfileDocument(fresh.saved.rows, session.submission.expected)) {
    return { kind: "committed" };
  }
  // A revert is proven only in the authored scope: the same composite hash somewhere else
  // (another scenario) is not evidence about this staged edit.
  if (fresh.project.code === session.submission.project && scope === session.submission.scope
      && fresh.save.content_hash === session.authoredHash) {
    return { kind: "reverted" };
  }
  if (!fresh.saved.error && sameProfileDocument(fresh.saved.rows, session.baselineExpected)) {
    return { kind: "unstaged" };
  }
  return { kind: "unknown" };
}
