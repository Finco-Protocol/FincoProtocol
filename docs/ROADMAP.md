# FINCO Protocol Roadmap

FINCO is being developed as deterministic financial-intelligence infrastructure for real-world assets.

The public product architecture is intentionally simple:

- **MODEL** — deterministic asset and project-finance economics;
- **RADAR** — source-aware market, company, macro and tokenized-asset intelligence;
- **YIELD** — read-only yield discovery, underwriting, evidence, history and monitoring;
- **CRYPTO** — verified-wallet identity, entitlement and protocol-access foundations.

The protocol layer is **VERIFY · API · $FINCO**. These layers expose evidence, machine access and optional service-entitlement infrastructure; they do not replace the financial, market or identity authorities underneath them.

Roadmap status is separated into **LIVE / IMPLEMENTED**, **Q4 2026**, **Q1 2027** and **LATER**. A merged implementation can still be feature-gated or not production-active; those states are stated explicitly below.

---

## LIVE / IMPLEMENTED

### FINCO Model

Current modelling verticals:

- **Solar** — mature production modelling workflow;
- **Wind** — mature production modelling workflow;
- **Data Center** — implemented and supported; canonical reference passed the A3.1 vertical regression check;
- **EV Charging** — implemented and supported; A3.2 / P0.3 canonical reference;
- **Storage** — PREVIEW / reference scope; working-copy runtime not released.

Shared engine/product capabilities include operating assumptions, revenue, CAPEX, OPEX, construction financing, debt, DSCR/credit metrics, shareholder funding, tax/depreciation, reserves/cash waterfalls, financial statements, distributions, project/equity/sponsor returns, scenarios, sensitivities and controlled exports.

Trust/output layers already implemented include Canonical Last Run, Institutional XLSX Export, Run Integrity Checks, the Reference Regression Check and config-gated Ed25519 Signed Run issuance. Signed Run public trust-key discovery/public verification remains separate M-2 work.

### FINCO Radar

- BNB RWA market intelligence, cross-chain canonical identity and execution/premium-gap surfaces;
- R-LIVE exact-identity on-chain reference observations;
- **300-second TWAP with fail-closed freshness policies** — not a collapsed freshness SLA;
- AVAILABLE / STALE / UNAVAILABLE evidence states and 1h/24h historical ranges;
- snapshot-first UX and multi-asset collection;
- public read-only Radar/R-LIVE API;
- R-LIVE observations are reference evidence, **not executable prices**.

### FINCO Yield

PR #148 is merged. The read-only FINCO Yield V1 product is implemented, but production execution is not activated.

Implemented scope:

- exact canonical opportunity identity;
- Ethereum/Base Morpho research observations and generic ERC-4626 authority path;
- source-aware freshness and typed evidence states;
- deterministic underwriting, component reconciliation, Organic Share, Reward Dependency and Reward-Off APY;
- amount/horizon-aware Net APY only when explicit costs exist;
- Explore / Detail / Compare / Evidence / immutable History;
- read-only Wallet Monitor reusing the existing verified FINCO wallet identity;
- canonical unsigned transaction-plan construction and provider-normalization boundaries;
- Yield watchlist foundation with per-user canonical opportunity identity.

Operational boundaries:

- `FINCO_YIELD_ENABLED=0` by default;
- `FINCO_YIELD_EXECUTION_ENABLED=0` by default;
- no private-key access;
- no server-side signing;
- no automatic broadcast;
- no custody;
- no FINCO-owned vault, allocator or pooled-funds product;
- no production mainnet money movement in the current workflow;
- external alert delivery is **NOT SHIPPED**.

### FINCO Crypto / Wallet & Entitlement Foundation

Crypto Utility V0 is merged and implements the authority chain from authenticated session → verified wallet → approved deployment resolution → read-only balance evidence → token entitlement → resource policy → typed `ResourceAccessDecision` → server enforcement/presentation.

Current production truth:

- production approved `$FINCO` deployment count = **0**;
- token gating default = **OFF**;
- production chain = **UNSET**;
- production token contract = **UNSET**;
- production threshold = **UNSET**;
- wallet ownership ≠ balance ≠ entitlement ≠ execution/metering;
- missing/unavailable/stale balance evidence ≠ zero;
- `INACTIVE` preserves existing ungated behaviour and is not entitlement;
- active-gate `DENY` fails closed;
- Yield execution remains independently OFF even if entitlement preflight succeeds;
- no tokenomics, staking, burn, token spending, custody, server signing or automatic broadcast is activated.

### VERIFY · API · $FINCO

**VERIFY** currently combines distinct authorities rather than one cumulative certification:

- Run Integrity Checks;
- Reference Regression Check;
- Signed Run evidence;
- FINCO Verify binding state;
- Verified Assets composition.

Production VERIFIED assets remain **0**. `MODEL_ONLY` never means VERIFIED.

**API** provides read-only public Model/Radar access and R-LIVE routes. API availability does not imply execution authority.

**$FINCO** is the service-entitlement/access layer. Its infrastructure is implemented, but no production deployment, chain, contract, threshold or final token economics is claimed.

### Experimental but merged

**JEV Radar Intelligence V1** is EXPERIMENTAL. Runtime defaults OFF; enabled-without-mode is SHADOW; VISIBLE requires explicit configuration. JEV interprets FINCO evidence but never replaces Model, Radar, Verify, identity or entitlement authority.

---

## Q4 2026

### Product cohesion

- **FINCO Terminal 1.0** — coherent navigation/workflow across Model, Radar, Yield and Crypto;
- preserve VERIFY · API · $FINCO as protocol-layer services rather than separate primary products;
- align public Product Truth surfaces so feature-gated/implemented/not-production-active states are explicit.

### Model — Institutional Modelling

- Institutional Model Runs;
- Advanced Project Finance;
- Scenario Control;
- Institutional Reporting and evidence lineage.

Infrastructure vertical expansion remains under the **Model / future asset coverage** track rather than dominating the protocol roadmap.

### Radar / intelligence

- FINCO Signals with evidence-backed persistence/history and explicit trigger context;
- continue R-LIVE operational hardening without changing canonical identity authority.

### Yield

- harden the read-only evidence and monitoring workflow;
- build from the shipped watchlist foundation toward typed external alert delivery;
- external alert delivery remains NOT SHIPPED until a separate implementation proves it;
- keep execution independently gated and OFF unless a later reviewed activation changes that contract.

### Crypto / $FINCO activation readiness

- production deployment-provenance and explicit configuration path;
- entitlement observability and fail-closed activation controls;
- no roadmap step itself chooses a chain, contract or threshold;
- no final tokenomics are defined by this roadmap;
- no staking, burn or token spending is introduced by this phase.

### Verification / Model ↔ Market

- source-proven Model ↔ `economic_asset_uid` ↔ canonical market evidence binding;
- public Signed Run trust distribution / verifier completion (M-2);
- optional On-chain Verify design work may continue, but no anchoring is claimed live.

### Metered Utility — M-1

Define metering only around useful scarce resources after production activation prerequisites are explicit. **Token economics are not final; token launch is not claimed.**

---

## Q1 2027

### Valuation & Protocol Intelligence

- **FINCO Fair Value** — normalized fundamentals, explicit assumptions and traceable scenario-based valuation;
- **Fundamental Gap** — defined Fair Value versus underlying-market-price metric;
- **Tokenization Premium** — tokenized-market reference/execution context versus the underlying security;
- Valuation & Tokenized Equity Screener;
- Portfolio Intelligence Preview;
- Financial Passport combining asset identity, model version, valuation snapshot, market snapshot, evidence digest and verification state.

These are targets, not current capabilities. They do not grant investment recommendations, guaranteed outcomes or execution authority.

---

## LATER

### Model future asset coverage

Additional operating modules may include deeper Storage/hybrid assets, transport infrastructure, real estate, hospitality, water infrastructure, ports/logistics, telecom, industrial/process facilities and other long-duration contracted or regulated assets.

These remain **Model** verticals that reuse the common financing, tax, cash-flow, statements, returns and verification core.

### Enterprise Modelling Platform

Not a current Q4 priority:

- Team Workspaces & Approvals;
- Portfolio Modelling;
- Advanced Financing Structures;
- Audit & Model Governance;
- broader enterprise integrations and collaboration controls.

### Verification / research

- **L2 / Merkle Anchoring** after the public Signed Run trust model is complete;
- cryptographic proof-of-model / proof-of-valuation research;
- zero-knowledge financial proofs;
- on-chain financial attestations;
- FINCO Agent Alpha and other agent-assisted workflows where AI explains typed FINCO evidence but never becomes calculation, identity, price or entitlement authority.

---

## Roadmap boundary

**Targets are sequencing, not guarantees.** A roadmap target does not mean a token, financial product, investment return or launch date is guaranteed. FINCO evidence and verification labels do not imply bank, audit or third-party certification unless explicitly stated.

No roadmap item by itself activates custody, server signing, automatic broadcast, staking, burn, token spending, production token gating or Yield execution.
