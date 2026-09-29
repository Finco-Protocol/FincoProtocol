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
- **Data Center** — implemented and vertically validated modelling workflow (A3.1)
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

- Canonical Last Run (committed, immutable snapshot)
- Institutional XLSX Export (P1.2) — reads committed Last Run only
- MODEL VALIDATION (P1.3) — reference reconciliation and tolerance checks
- EV Institutional Reconciliation (P1.4)
- Institutional Trust Pack (P1.1) — methodology HTML, DSCR, XIRR ACT/365F

### Signed Run Certificate V1 (PR #132)

Ed25519 asymmetric signed certificate issued from committed Last Run only.
Requires `FINCO_RUN_CERT_SIGNING_KEY`. Fails closed without it. Third-party
verifiable. Proves computational integrity — not economic truth.

### Model Trust Pack UX V1 (PR #133)

Seven-section read-only evidence surface in the V2 workbook. Zero engine calls
at render. Explicitly separates MODEL VALIDATION ≠ FINCO VERIFY ≠ Signed Run.

### Radar / R-LIVE

- **Radar B1.1–B1.3** — BNB RWA market intelligence, cross-chain canonical
  identity, premium/execution gap, exact-identity history
- **R-LIVE V2** (PR #136 / #137) — registry-driven 8-asset on-chain reference
  surface: AAPL, NVDA, AMZN, GOOGL, TSLA, AVGO, NFLX, AMD. 300-second freshness
  gate. USDG/USD Chainlink conversion. Public API. UX shell. `/radar` → `/radar/r-live`.
  Exact canonical identity only; no ticker/fuzzy lookup.

### API / MCP

- **API v1.1** (PR #125) — thin read-only institutional surface over canonical authorities
- **MCP V1** (PR #129) — read-only institutional agent interface (9 tools; signed session identity)
- **R-LIVE public API** (PR #137) — 3 unauthenticated read-only routes

### Token / Access / Metering

- **B2.1 FINCO Verify** — fail-closed Verified provenance gate and dossier entitlement
- **B2.2 Token Entitlement** — fail-closed FINCO token entitlement for Verified dossiers
- **B2.3 Usage Metering** (PR #128, #135) — append-only off-chain ledger; subject-scoped
  idempotency; concurrent duplicate fix (PR #135)

### Documentation / Release Integrity

- V1 Product Truth Freeze (PR #130)
- Opus Handoff Pack V1 (PR #131)
- Post-PR137 Product Truth Refresh (this PR)

---

## CURRENT / OPERATIONALIZATION

These capabilities are implemented but require operational configuration for
production data to flow:

- **R-LIVE production collector** — requires `ROBINHOOD_RPC_URL` + systemd
  collector activated on a VPS to accumulate live history
- **Signed Run Certificate** — requires `FINCO_RUN_CERT_SIGNING_KEY` in
  deployment configuration
- **MCP V1** — requires `FINCO_SESSION_TOKEN` deployment configuration;
  server-session isolation review for multi-user shared deployments
- **B2.3 metering coverage** — MCP tool-call hook wiring not confirmed for
  all production traffic paths
- **Final documentation / product truth** — this PR
- **Final release integrity audit** — pending

---

## NEXT

- **Clean-room Opus review** — independent security and authority review from
  this docs PR snapshot
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
