# FINCO Protocol

[![Public Safety and Model Smoke](https://github.com/Finco-Protocol/FincoProtocol/actions/workflows/public_safety_and_smoke.yml/badge.svg?branch=main)](https://github.com/Finco-Protocol/FincoProtocol/actions/workflows/public_safety_and_smoke.yml)
[![Dependency Security Audit](https://github.com/Finco-Protocol/FincoProtocol/actions/workflows/dependency_security_audit.yml/badge.svg?branch=main)](https://github.com/Finco-Protocol/FincoProtocol/actions/workflows/dependency_security_audit.yml)
[![Protocol Verification Corpus](https://github.com/Finco-Protocol/FincoProtocol/actions/workflows/protocol_verification.yml/badge.svg?branch=main)](https://github.com/Finco-Protocol/FincoProtocol/actions/workflows/protocol_verification.yml)

**RWA Infrastructure Intelligence**

FINCO Protocol is deterministic infrastructure for **RWA modelling, market intelligence, and verification**.

> **Most RWA platforms start with the token. FINCO starts with the asset.**

> **AI explains. FINCO calculates.**

Before infrastructure can become a meaningful real-world asset representation, someone still has to model what the underlying asset produces, what it earns, what it costs, how it is financed, how taxes and reserves affect cash generation, and what investors ultimately receive. FINCO is building that analytical layer.

The architecture combines a deterministic infrastructure-modelling engine, crypto and tokenized-asset market intelligence, typed evidence, reproducible calculations, and an off-chain verification layer designed for future cryptographic anchoring.

## Product surfaces

### FINCO Model — RWA infrastructure modelling engine

FINCO Model is the deterministic modelling surface for real-world infrastructure assets.

The current modelling verticals are:

- Solar and Wind — mature production modelling workflows;
- Data Center — implemented and vertically validated modelling workflow (A3.1);
- EV Charging — implemented modelling workflow (A3.2, canonical reference and working-copy runtime supported);
- Storage — limited/reference scope (reference viewable; working-copy runtime not released).

Solar and Wind are the most mature modules.

The current engine can model and reconcile:

- physical and operating assumptions,
- production and availability,
- revenue structures and indexation,
- CAPEX and construction schedules,
- operating expenditure,
- construction and long-term financing,
- senior debt sizing and amortization,
- interest and debt-service coverage,
- shareholder loans and sponsor funding,
- corporate tax and loss carryforward,
- tax and book depreciation,
- cash reserves and liquidity accounts,
- project cash flows and cash waterfalls,
- financial statements,
- investor distributions,
- project, equity, and sponsor returns,
- IRR, NPV, DSCR, and other credit / return metrics,
- scenarios, sensitivities, reporting, and controlled exports.

For a Solar or Wind asset, FINCO can take the model from installed capacity, production, pricing, and operating assumptions through debt, tax, reserves, distributions, and final investor returns. Data Center and EV Charging follow the same framework with asset-specific operating assumptions.

That same deterministic architecture is designed to support additional RWA infrastructure verticals by adding asset-specific operating assumptions while preserving the common financial, financing, tax, cash-flow, reporting, and verification layers.

### Infrastructure expansion roadmap

Planned infrastructure verticals include:

- **Transport infrastructure** — toll roads, highways, concessions, and related assets;
- **Real estate** — commercial and residential buildings;
- **Hospitality** — hotels and other operating real-estate assets;
- **Water infrastructure** — desalination, water-treatment, and wastewater facilities;
- **Digital infrastructure** — data centers and related capacity assets;
- **Energy infrastructure** — storage, utilities, and other generation / network assets;
- **Logistics infrastructure** — ports, terminals, and logistics facilities;
- **Telecom infrastructure** — towers, networks, and connectivity assets;
- **Industrial infrastructure** — long-life industrial and process facilities.

These verticals are roadmap targets, not claims that all asset-specific modules are already implemented. Solar and Wind are mature production modelling workflows; Data Center is an implemented and vertically validated modelling workflow (A3.1 complete); EV Charging is an implemented modelling workflow (A3.2 complete, canonical reference and working-copy runtime supported); Storage remains limited/reference scope (reference viewable; working-copy runtime not released).

See [docs/RWA_INFRASTRUCTURE.md](docs/RWA_INFRASTRUCTURE.md) for the RWA infrastructure thesis, current engine capabilities, and planned module expansion.

### Why this matters for RWA

A token, security, or on-chain representation does not by itself explain the economics of the underlying infrastructure asset.

An RWA analytical layer still needs to answer questions such as:

- What drives revenue?
- What CAPEX is required and when?
- How much debt can the asset support?
- What happens to cash after operating costs, debt service, taxes, and reserves?
- What returns accrue to equity or other capital providers?
- Which assumptions changed between two valuations?
- Can the result be reproduced and independently reconciled?

FINCO is designed to calculate that layer before, alongside, or independently of tokenization.

### FINCO Radar — crypto and tokenized-asset intelligence

FINCO Radar is the crypto and tokenized-asset market-intelligence surface of FINCO Protocol.

Radar is architecturally separate from the infrastructure modelling engine. Its staged architecture includes canonical asset identity, execution quotes, execution-aware GAP analysis, size-aware liquidity and route evidence, reference-state semantics, deterministic evidence and signals, terminal surfaces, and execution simulation.

The purpose is to analyze how a tokenized or crypto asset actually trades while FINCO Model analyzes the economics of the underlying real-world infrastructure asset.

### FINCO Radar — R-LIVE

R-LIVE is a first-class Radar domain providing on-chain reference prices for a
reviewed pool of tokenized equities on Robinhood Chain (chain 4663).

The current reviewed approved display universe is:

AAPL, NVDA, AMZN, GOOGL, TSLA, AVGO, NFLX, AMD

Each approved identity is exact: a specific canonical AssetKey / economic_asset_uid
/ Uniswap V3 pool deployment reviewed from the official Robinhood asset registry and
confirmed via on-chain observation. There is no ticker-based or fuzzy lookup; runtime
has no pool discovery or fallback.

R-LIVE derives a 300-second on-chain TWAP with USDG/USD conversion via the canonical
Chainlink oracle. USDG is never assumed to equal USD 1. If no Swap occurred in the
300-second window, the observation is STALE. STALE and UNAVAILABLE suppress current
numeric output and are structurally distinct from empty/zero.

**R-LIVE is a reference observation — it is not a tradeable or executable price.**
R-LIVE does not create FINCO VERIFIED status. R-LIVE data does not flow into the
financial engine.

The public R-LIVE API surface:

```
GET /api/v1.1/radar/r-live/assets                   — list approved identities
GET /api/v1.1/radar/r-live/{canonical_id}            — current reference (exact identity only)
GET /api/v1.1/radar/r-live/{canonical_id}/history    — historical evidence (read-only)
```

The R-LIVE collector (`python -m app.radar_rwa.r_live_collect`, no-arg) collects all
approved registry assets serially. STALE/UNAVAILABLE per-asset market states are not
process failures. Requires `ROBINHOOD_RPC_URL` and `RADAR_BNB_INTELLIGENCE_DB_PATH`
(shared durable B1.3 ledger; never committed to Git; staging/production must be separate).

Global Radar navigation lands on R-LIVE (`/radar` → `/radar/r-live`). Stocks remains at
`/radar/stocks`. Crypto and Economy are separate Radar domains.

### FINCO Protocol layer — verification now, on-chain later

The Protocol layer implements off-chain verification and composition. Current capabilities include:

- **Signed Run Certificate V1** — Ed25519 asymmetric signed evidence of what was computed.
  Issued from a committed Last Run only. Requires `FINCO_RUN_CERT_SIGNING_KEY` deployment
  configuration; fails closed without it (`SIGNING_KEY_UNAVAILABLE`). Third-party verifiable
  with the FINCO public key. **Not FINCO Verify. Not economic truth.**
- **Model Trust Pack UX V1** — a seven-section read-only evidence surface in the V2 workbook
  (A: Last Run Identity, B: Core KPIs, C: MODEL VALIDATION, D: FINCO VERIFY, E: Institutional
  Export, F: Methodology, G: Signed Run Certificate). Zero engine calls at render. Zero DB writes.
  Explicitly separates the three authority layers: MODEL VALIDATION ≠ FINCO VERIFY ≠ Signed Run.
- **Verified Assets** — composed records that bind model economics, a Run Certificate, Radar
  evidence and protocol metadata into a single verifiable asset record. V1 assets currently
  render as MODEL_ONLY because no canonical model↔market identity mapping is yet established
  in production.

The verification layer validates already-produced evidence rather than replacing either
calculation engine. A sanitized public corpus covers generic Solar, generic Wind, and
synthetic Radar liquidity evidence.

No blockchain anchoring or smart-contract deployment is claimed by the current verification implementation.

The intended architecture remains:

> **Model off-chain. Verify on-chain.**

A future anchoring layer can publish compact evidence digests while full calculations and evidence remain off-chain.

**$FINCO access and entitlement:** The protocol access and service-entitlement layer is implemented. The $FINCO token is not yet launched. Token access is not a calculation authority and does not change model outputs or evidence truth. Exact token economics, access thresholds, network deployment, and smart-contract design are not final and should not be inferred from the current codebase.

## Verification and CI

FINCO is structured to expose repeatable verification procedures and per-run evidence rather than relying on repository claims alone.

The main release CI gates currently perform:

- configured public-release safety scanning for defined identifiers/patterns/artifact types,
- Python compilation checks,
- dependency consistency checks,
- synthetic reference and regression tests,
- resolved-environment dependency vulnerability auditing with retained evidence,
- deterministic cross-surface Protocol verification with a content-addressed synthetic corpus.

The Protocol verification gate runs focused Model/Radar invariant checks, builds the public validation corpus twice, requires byte-identical JSON, runs the public-safety scan, and uploads the resulting corpus as retention-limited evidence. The corpus content digest and GitHub artifact ZIP digest are separate evidence values and are not represented as blockchain anchoring.

The safety scan, dependency audit, and verification corpus are automated controls, not general-purpose confidentiality, provenance, external-data-truth, or vulnerability-free guarantees. Controlled public release still requires human review.

Radar components also use dedicated evidence-oriented workflows for component-specific runtime and deterministic gates.

See [docs/PROTOCOL_VERIFICATION.md](docs/PROTOCOL_VERIFICATION.md) for the content-addressed verification layer and public corpus. See [docs/VERIFICATION.md](docs/VERIFICATION.md) for the wider verification model, local reproduction commands, evidence boundaries, CI provenance, and known limitations. See [docs/GOVERNANCE.md](docs/GOVERNANCE.md) for repository governance, dependency-security automation, target `main` protection, and pre-public-release controls.

## Public reference models

This repository contains only synthetic reference data:

| Reference | Market | Purpose |
| --- | --- | --- |
| Generic Solar Reference | Generic Market A (`XA`) | renewable RWA modelling demonstration |
| Generic Wind Reference | Generic Market B (`XB`) | renewable RWA modelling demonstration |
| Generic Storage Reference | Generic Market C (`XC`) | storage / BESS reference capability (view-only; runtime not released) |
| Generic Data Center Reference | Generic Market D (`XD`) | data-center RWA modelling demonstration |
| Generic EV Charging Hub Reference | Generic Market E (`XE`) | EV charging RWA modelling demonstration |

`XA`, `XB`, `XC`, `XD`, and `XE` are user-assigned market identifiers used only for synthetic examples. They do not represent real jurisdictions.

No client project, company, workbook, saved project, production database, project-specific spreadsheet, or historical calibration artifact is part of the corporate repository.

## Repository provenance

The corporate repository is a clean-room sanitized codebase derived from a private development lineage and prepared for controlled public release. Historical branches, commits, client datasets, calibration evidence, screenshots, exports, working databases, and source materials are intentionally not imported.

The migration policy is fail-closed: source enters this repository only after sanitization and public-safety checks.

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
pip install -r requirements.txt -c constraints.txt
uvicorn main_web:app --reload
```

Build the deterministic public verification corpus with:

```bash
python tools/build_public_validation_corpus.py \
  --output artifacts/finco-public-validation-corpus.json
```

FINCO Model is the current RWA infrastructure modelling surface. FINCO Radar R-LIVE V2 is live with a reviewed 8-asset surface. Signed Run Certificate V1 (Ed25519), Model Trust Pack UX V1, Verified Assets V1, API v1.1, and MCP V1 are implemented. The $FINCO token is not yet launched. Blockchain anchoring remains future work.

## Safety boundaries

- deterministic engine outputs are not investment, tax, legal, or credit advice;
- synthetic reference markets are illustrative and are not jurisdictional tax templates;
- Solar and Wind are mature production modelling workflows; Data Center is an implemented and vertically validated modelling workflow (A3.1 complete); EV Charging is an implemented modelling workflow (A3.2 complete); Storage remains limited/reference scope (reference viewable; working-copy runtime not released); further asset-class modules are roadmap items until implemented and validated;
- FINCO Model does not require wallet signing, custody, swaps, approvals, or private keys;
- Radar and Protocol verification remain architecturally separate from the RWA infrastructure modelling engine;
- a deterministic evidence digest is not proof that external market data is true and is not an on-chain notarization by itself;
- planned token utility does not imply that a token contract, token sale, staking system, or token-gated production service is currently live.

## Long-term direction

**Most RWA platforms start with the token. FINCO starts with the asset.**

**Model off-chain. Verify on-chain.**

The long-term direction is a common deterministic modelling and verification layer for tokenized and non-tokenized real-world infrastructure: renewable energy first, broader infrastructure next.

The research roadmap includes financial digital twins, cross-market price truth, execution-aware simulation, machine-readable due diligence, self-auditing models, autonomous finance agents, infrastructure asset knowledge graphs, and cryptographic model / valuation proofs.

## Status

Sanitized corporate codebase under active development and prepared for controlled public release.

**Model:** Solar and Wind are mature production modelling workflows. Data Center is an implemented and vertically validated modelling workflow (A3.1 complete). EV Charging is an implemented modelling workflow (A3.2 complete, canonical reference and working-copy runtime supported). Storage remains limited/reference scope (reference viewable; working-copy runtime not released).

**Radar / R-LIVE:** R-LIVE V2 is live — registry-driven 8-asset reviewed surface (AAPL, NVDA, AMZN, GOOGL, TSLA, AVGO, NFLX, AMD) on Robinhood Chain with 300-second freshness gate, USDG/USD Chainlink conversion, and public read-only API. Global Radar lands on R-LIVE.

**Protocol:** Signed Run Certificate V1 (Ed25519) is live. Model Trust Pack UX V1 (7-section read-only evidence surface) is live. Verified Assets V1 (currently MODEL_ONLY) are active. API v1.1 institutional surface and MCP V1 read-only agent interface are live.

**Token / Access:** B2.2 token entitlement and B2.3 usage metering are implemented. The $FINCO token is not yet launched. Public deployment, live token launch, and blockchain anchoring remain roadmap functionality.
