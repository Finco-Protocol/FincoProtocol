// Typed integration boundary — canonical NON-MODEL data wiring (NOT CONNECTED).
//
// The Concept B NON-MODEL integration V1 ships the approved presentation with
// its local deterministic fixtures (`./_shared/fixtures.ts`).  Per the handoff
// contract ("No endpoint names are asserted in this package") and the GitHub
// integration brief ("Do not invent backend endpoints"), NOTHING in this tree
// fetches, imports or names a backend route.  Loading, empty, error and
// unavailable states in the UI are local presentation states.
//
// This file is the seam for the future authorized wiring only.  It records,
// in one typed place, which surface needs which canonical capability so the
// next integrator can implement the ports against the then-current approved
// source (Radar services live under `finco_radar/**` and `app/radar_ui/**`;
// release gating and API contracts there govern any future adapter) WITHOUT
// touching the presentation components.  The display guards in
// `./_shared/non-model-logic.ts` (300-second per-leg/pair freshness, MARKET
// versus REFERENCE separation, stale/unavailable suppression, exact-identity
// joins) must keep applying to whatever implementation backs these ports.

import type { Instrument } from "./_shared/fixtures";

/** The only data source wired in this integration. */
export type NonModelSourceKind = "local-fixtures";

export const ACTIVE_NONMODEL_SOURCE: NonModelSourceKind = "local-fixtures";

/**
 * Ports the Concept B screens would consume from canonical services.
 * Deliberately UNIMPLEMENTED: no canonical contract for these capabilities
 * has been approved for frontend consumption yet, so declaring concrete
 * endpoint shapes here would invent backend authority.
 */
export interface NonModelEvidencePort {
  /** Canonical instrument/representation universe with identity fields. */
  listInstruments(): Promise<readonly Instrument[]>;
}

export type CanonicalWiringStatus =
  | "NOT_CONNECTED"
  | "PENDING_AUTHORIZED_CONTRACT";

export interface CanonicalWiringNote {
  surface: string;
  status: CanonicalWiringStatus;
  dependency: string;
}

/**
 * Explicit dependency register (integration report §"Canonical connections
 * versus remaining placeholders").  Every row is an honest placeholder: the
 * screen renders honest local/empty/suppressed states until the named
 * dependency is separately authorized and integrated.
 */
export const CANONICAL_WIRING: readonly CanonicalWiringNote[] = [
  {
    surface: "Radar overview / R-LIVE / Tokenized / Stocks / Crypto",
    status: "NOT_CONNECTED",
    dependency:
      "Canonical instrument identity + MARKET/REFERENCE evidence feeds (finco_radar, app/radar_ui read services). Local fixtures only; no live feed is consumed or implied.",
  },
  {
    surface: "Economy",
    status: "NOT_CONNECTED",
    dependency:
      "Verified macro series source + freshness contract. Screen intentionally renders an honest empty state; synthetic economic data is forbidden.",
  },
  {
    surface: "Instrument detail / demo curve",
    status: "NOT_CONNECTED",
    dependency:
      "Authorized canonical time-series contract. Curves stay deterministic synthetic illustrations keyed to the full fixture ID; never live prices or history.",
  },
  {
    surface: "Crypto access / wallet / entitlement",
    status: "NOT_CONNECTED",
    dependency:
      "Separately approved entitlement + wallet identity contract (app.crypto_access, app.protocol.entitlement_evaluator). Controls stay simulated; gated actions stay disabled.",
  },
  {
    surface: "Watchlist / alert drafts",
    status: "NOT_CONNECTED",
    dependency:
      "Persistence, ownership, scheduling and delivery contracts. State stays in memory, resets on reload; no notification is implied by a draft.",
  },
] as const;
