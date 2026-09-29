# FINCO Protocol Roadmap

FINCO is being developed as deterministic infrastructure for **RWA modelling,
market intelligence, and verification**.

The modelling strategy is vertical: begin with a deeply modelled infrastructure
category, preserve a common financial / verification core, then add asset-specific
operating modules without duplicating the underlying engine.

---

## SHIPPED

### FINCO Model — RWA infrastructure modelling

Current production modelling verticals:

- **Solar** — mature production modelling workflow
- **Wind** — mature production modelling workflow
- **Data Center** — implemented modelling workflow whose canonical reference passed the A3.1 vertical regression check
- **EV Charging** — implemented modelling workflow (A3.2, P0.3 canonical reference)
- **Storage** — PREVIEW (reference viewable; working-copy runtime not released)

Shared engine capabilities shipped:

- physical and operating assumptions,
- production and revenue structures,
- CAPEX and construction schedules,
- operating expenditure,
- debt financing and amortization,
- DSCR and credit metrics,
- shareholder funding,
- tax and depreciation,
- reserves and cash waterfalls,
- financial statements,
- distributions,
- project / equity / sponsor returns,
- scenarios, sensitivities, reporting, and controlled exports.

Institutional output capabilities:

- Canonical Last Run (committed snapshot — unchanged by Working Copy edits;
  replaced only by a subsequent committed run)
- Institutional XLSX Export (P1.2) — reads committed Last Run only
- Reference Regression Check (P1.3) — re-runs canonical reference-model KPIs
  against pinned expected values; regression protection for the reference
  library. Does NOT independently validate a user's Last Run (H-4A).
- EV Institutional Reconciliation (P1.4)
- Institutional Trust Pack (P1.1) — methodology HTML, DSCR, XIRR ACT/365F

### Signed Run Certificate V1 (PR #132)

Ed25519 asymmetric signed certificate issued from committed Last Run only.
Requires `FINCO_RUN_CERT_SIGNING_KEY`. Fails closed without it. Signature
verification works when the relying party independently holds the trusted
FINCO public key; public trust-key distribution and a public verifier are
not yet complete. Proves computational integrity — not economic truth.

### Model Trust Pack UX V1 (PR #133)

Seven-section read-only evidence surface in the V2 workbook. Zero engine calls
at render. Explicitly separates Reference Regression Check ≠ FINCO VERIFY ≠
Signed Run. The Reference Regression Check is regression protection for the
reference library, not independent validation of a user's Last Run.

### Run Integrity Checks (planned — P0, not shipped)

Independent checks validating the integrity of a user's actual Last Run
(accounting, debt, and cash-flow reconciliation of the committed snapshot).
Planned as a P0 roadmap capability. **Not implemented in V1** — do not
represent as shipped. Distinct from the Reference Regression Check (P1.3),
which re-runs canonical reference models against pinned expected values.

### Radar / R-LIVE

- **Radar B1.1–B1.3** — BNB RWA market intelligence, cross-chain canonical
  identity, premium/execution gap, exact-identity history
- **R-LIVE V2** (PR #136 / #137) — registry-driven on-chain reference surface.
  300-second freshness gate. USDG/USD Chainlink conversion. Public API. UX shell.
  `/radar` → `/radar/r-live`. Exact canonical identity only; no ticker/fuzzy lookup.
- **R-LIVE multi-asset collector** (PR #139) — no-arg `python -m app.radar_rwa.r_live_collect`
  collects all approved registry assets serially. STALE/UNAVAILABLE market states
  are not process failures. Staging config contract: `ROBINHOOD_RPC_URL` +
  `RADAR_BNB_INTELLIGENCE_DB_PATH`; staging/production ledgers must be separate files.
- **R-LIVE V2 freshness/history/13-asset expansion** (PR #140, merged 2026-09-29) —
  13 source-proven approved assets: AAPL, NVDA, AMZN, GOOGL, TSLA, AVGO, NFLX, AMD,
  DELL, SNAP, INTC, MSFT, META. Source-component freshness clocks (market activity age,
  oracle age, block age, `effective_evidence_at`, `collected_at`). `collected_at` ≠
  `effective_evidence_at`. 1h/24h ranges: collection-timestamp-selected, HISTORICAL,
  >=2 points, no interpolation. STALE last-available UX (explicit HISTORICAL label;
  STALE badge stays STALE). Landing batch: 2 requests total (not 16). 6 public R-LIVE
  API routes (up from 3). SCAN_COMPLETE = NO (environment-blocked; no standards
  weakened; 13 admitted = source-proven).
  Full suite at exact head: 4703 passed, 38 skipped, 0 failed; 6/6 workflows SUCCESS.

### API / MCP

- **API v1.1** (PR #125) — thin read-only institutional surface over canonical authorities
- **MCP V1** (PR #129) — read-only institutional agent interface (9 tools; signed session identity)
- **R-LIVE public API** (PR #137 / #140) — 6 unauthenticated read-only routes

### Token / Access / Metering

- **B2.1 FINCO Verify** — fail-closed Verified provenance gate and dossier entitlement
- **B2.2 Token Entitlement** — fail-closed FINCO token entitlement for Verified dossiers
- **B2.3 Usage Metering** (PR #128, #135) — append-only off-chain ledger; subject-scoped
  idempotency; concurrent duplicate fix (PR #135)

### Documentation / Release Integrity

- V1 Product Truth Freeze (PR #130)
- Opus Handoff Pack V1 (PR #131)
- Post-PR137 Product Truth Refresh (PR #138, earlier)
- Post-PR140 Final Docs / Review Package Refresh (PR #138, this revision)

---

## CURRENT / OPERATIONAL

These capabilities are implemented and code-complete. The following operational
activities are underway or required before full production deployment:

- **R-LIVE canonical history accumulation** — collector active; accumulating 13-asset
  canonical history on production VPS; requires `ROBINHOOD_RPC_URL` + `RADAR_BNB_INTELLIGENCE_DB_PATH`
  (identical path for web and collector; staging/production separate)
- **R-LIVE wide admission scan** — blocked by review environment egress policy
  (HTTP 403 on api.robinhood.com and rpc.mainnet.chain.robinhood.com);
  SCAN_COMPLETE = NO; additional asset admission possible when environment permits
- **Staging performance observation** — observe real staging R-LIVE performance
  with 13-asset surface; validate 1h/24h range accumulation
- **Signed Run Certificate** — requires `FINCO_RUN_CERT_SIGNING_KEY` in deployment configuration
- **MCP V1** — requires `FINCO_SESSION_TOKEN` deployment configuration;
  server-session isolation review for multi-user shared deployments
- **B2.3 metering coverage** — MCP tool-call hook wiring not confirmed for all production paths
- **Final docs / review package** — this PR (PR #138 post-PR140 revision)
- **Final Release Integrity Audit** — pending

---

## NEXT

- **Clean-room Opus review** — independent security and authority review from
  this docs PR snapshot (post-PR#140 product truth)
- **Corrections from independent review** — apply findings

### Expand the model

- richer merchant and contracted revenue structures,
- additional storage / hybrid-asset logic,
- portfolio-level renewable analysis,
- broader scenario and sensitivity tooling.

### Add first non-renewable RWA infrastructure modules

Priority candidates:

- **Transport infrastructure** — toll roads, highways, concessions;
- **Real estate** — commercial and residential buildings;
- **Hospitality** — hotels and operating real-estate assets;
- **Water infrastructure** — desalination, water treatment, wastewater.

These modules reuse the common financing, tax, cash-flow, financial-statement,
return, and verification layers while adding vertical-specific operating assumptions.

### Market and verification layers

- stronger model / market evidence linkage,
- richer deterministic signals,
- cross-market reference reconciliation,
- execution-aware simulation,
- model integrity / audit diagnostics,
- portfolio intelligence.

---

## LATER

Additional infrastructure verticals may include:

- energy storage and utilities,
- ports and logistics infrastructure,
- telecom infrastructure,
- industrial and process facilities,
- district heating / cooling,
- other long-duration contracted or regulated infrastructure.

Longer-term platform capabilities include:

- live infrastructure financial digital twins,
- machine-readable due diligence,
- infrastructure asset knowledge graphs,
- capital-structure and refinancing optimization,
- global relative-value analysis,
- autonomous model-maintenance agents.

---

## EXPERIMENTAL

- **Jev / Reflex** (issue #119) — experimental shadow; explicitly NOT V1 scope;
  not merged to main; not a supported capability.

---

## Research

- cryptographic proof-of-model and proof-of-valuation,
- zero-knowledge financial proofs,
- on-chain financial attestations,
- counterfactual market simulation,
- autonomous capital-allocation research.

Research items and future infrastructure verticals are exploratory roadmap targets
and are not delivery commitments until separately implemented and validated.
