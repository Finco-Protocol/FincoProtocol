# FINCO Protocol Roadmap

FINCO is being developed as deterministic financial-intelligence infrastructure for real-world assets.

The public product architecture is intentionally simple:

- **MODEL** — deterministic asset and project-finance economics;
- **RADAR** — source-aware market, company, macro and tokenized-asset intelligence;
- **YIELD** — read-only yield discovery, underwriting, evidence, history and monitoring;
- **CRYPTO** — verified-wallet/access presentation, canonical Yield Watchlist and in-app Yield Alerts.

The protocol layer is **VERIFY · API · $FINCO**. These layers expose evidence, machine access and optional service-entitlement infrastructure; they do not replace the financial, market or identity authorities underneath them.

Roadmap status is separated into **LIVE / IMPLEMENTED**, **Q4 2026**, **Q1 2027** and **LATER**. A merged implementation can still be feature-gated or not production-active; those states are stated explicitly below.

---

## LIVE / IMPLEMENTED

### FINCO Model — Infrastructure Model

Current modelling verticals:

- **Solar** — mature production modelling workflow;
- **Wind** — mature production modelling workflow;
- **Data Center** — implemented and supported; canonical reference passed the A3.1 vertical regression check;
- **EV Charging** — implemented and supported; A3.2 / P0.3 canonical reference;
- **Storage** — PREVIEW / reference scope; working-copy runtime not released.

Shared engine/product capabilities include operating assumptions, revenue, CAPEX, OPEX, construction financing, debt, DSCR/credit metrics, shareholder funding, tax/depreciation, reserves/cash waterfalls, financial statements, distributions, project/equity/sponsor returns, scenarios, sensitivities and controlled exports.

Trust/output layers already implemented include Canonical Last Run, Institutional XLSX Export, **Run Integrity Checks (shipped — H-4b)**, the **Reference Regression Check (P1.3)** and config-gated Ed25519 Signed Run issuance. A committed Last Run is replaced only by a subsequent committed run.

Run Integrity Checks cover **Sources & Uses**, **senior debt rollforward**, **DSCR**, **unfunded-cash deficit**, and **sponsor-return/XIRR input consistency**. They do not re-run the model, do not equal FINCO VERIFY, and remain separate from the Reference Regression Check and Signed Run evidence.

**M-6 full-tenor gearing sculpting** is a shipped engine capability under **explicit opt-in**. The corresponding **user-facing configuration not exposed** boundary remains important: engine capability does not imply every product workflow exposes that control.

Signed Run public trust-key discovery/public verification remains separate M-2 work.

### FINCO Radar

- BNB RWA market intelligence, cross-chain canonical identity and execution/premium-gap surfaces;
- R-LIVE exact-identity on-chain reference observations;
- **300-second TWAP with fail-closed freshness policies** — not a collapsed freshness SLA;
- AVAILABLE / STALE / UNAVAILABLE evidence states and 1h/24h historical ranges;
- **R-LIVE snapshot-first UX** and multi-asset collection;
- public read-only Radar/R-LIVE API;
- R-LIVE observations are reference evidence, **not executable prices**.

### FINCO Yield

PR #148 is merged. The read-only FINCO Yield V1 product is implemented, while Yield execution remains OFF.

Implemented scope:

- exact canonical opportunity identity;
- Ethereum/Base Morpho research observations and generic ERC-4626 authority path;
- source-aware freshness and typed evidence states;
- deterministic underwriting, component reconciliation, Organic Share, Reward Dependency and Reward-Off APY;
- amount/horizon-aware Net APY only when explicit costs exist;
- Explore / Detail / Compare / Evidence / immutable History;
- read-only Wallet Monitor reusing the existing verified FINCO wallet identity;
- canonical unsigned transaction-plan construction and provider-normalization boundaries;
- canonical per-user Yield Watchlist;
- deterministic in-app Yield Alerts using canonical Watchlist, History, freshness and support-state authority;
- deterministic alert IDs, atomic alert/checkpoint persistence and persisted read state;
- explicit authenticated manual alert Refresh; first evaluation establishes a baseline and does not replay historical changes.

Operational boundaries:

- `FINCO_YIELD_ENABLED=0` by default;
- `FINCO_YIELD_EXECUTION_ENABLED=0` by default;
- no private-key access;
- no server signing;
- no automatic broadcast;
- no custody;
- no FINCO-owned vault, allocator or pooled-funds product;
- no production mainnet money movement in the current workflow;
- external alert delivery is **NOT SHIPPED**;
- background alert scheduling is **NOT SHIPPED**;
- Email, Telegram, Discord and Push alert delivery are **NOT SHIPPED**.

Explore → Underwrite → Evidence → Monitor → Act remains the product direction, but “Act” does not mean Yield execution is enabled.

### FINCO Crypto / Wallet, Entitlement & Alerts

The integrated `/crypto` surface provides verified-wallet/access presentation, the canonical Yield Watchlist and the in-app Yield Alerts read model with manual Refresh, mark-read and mark-all-read behavior.

The entitlement runtime remains the canonical authority chain from authenticated session → verified wallet → approved deployment resolution → read-only balance evidence → token entitlement → resource policy → typed `ResourceAccessDecision` → server enforcement/presentation. Alerts do not implement a second token evaluator.

Production activation-readiness infrastructure is implemented as an operator/readiness validation layer around that runtime. It does not activate a token and does not select token economics. **Production token activation is not configured.**

Current production truth:

- production approved `$FINCO` deployment count = **0**;
- token gating default = **OFF**;
- production chain = **UNSET**;
- production token contract = **UNSET**;
- production threshold = **UNSET**;
- wallet ownership ≠ balance ≠ entitlement ≠ execution/metering;
- missing/unavailable/stale balance evidence ≠ zero;
- `INACTIVE` preserves existing ungated behaviour and is not entitlement;
- active-gate `DENY` fails closed before protected Alerts/evaluator/store access;
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

**$FINCO** is the service-entitlement/access layer. Entitlement and activation-readiness infrastructure are implemented, but no production deployment, chain, contract, threshold or final token economics is claimed.

### Experimental but merged

**JEV Radar Intelligence V1** is EXPERIMENTAL. Runtime defaults OFF; enabled-without-mode is SHADOW; VISIBLE requires explicit configuration. JEV interprets FINCO evidence but never replaces Model, Radar, Verify, identity or entitlement authority.

---

## Q4 2026 — ONCHAIN MARKETS & UTILITY

Everything in this section is a **TARGET** unless explicitly stated otherwise.

### Product cohesion

- **FINCO Terminal 1.0** — coherent navigation/workflow across Model, Radar, Yield and Crypto;
- preserve VERIFY · API · $FINCO as protocol-layer services rather than separate primary products;
- align public Product Truth surfaces so feature-gated/implemented/not-production-active states are explicit.

### Model — Institutional Modelling

- Institutional Model Runs;
- Advanced Project Finance;
- Scenario Control;
- Institutional Reporting and evidence lineage.

Model future asset coverage remains the track for infrastructure vertical expansion rather than the organizing principle of the protocol roadmap.

### External Trade Center

Target external-provider routing for **Buy / Sell / Swap**. FINCO analyzes, prepares and routes; a third-party provider or the user wallet executes. No custody. No server signing. No provider is canonical until separately selected. No provider code is implemented by this roadmap item.

### $FINCO Market Surface

Future market surface only after a canonical production token deployment and pool exist. Potential source-proven fields include canonical contract, chain, price, liquidity, 24h volume, FDV / market cap where supported, pool, explorer, wallet balance and utility/access state. Optional DEX visualization remains future external market visualization.

No token contract, chain, supply, price, pool or market cap is invented. Production deployment remains **0** today.

### RWA Basis / Tokenized Market Monitor

Future Radar/Crypto monitoring of exact source-proven economic identity across:

- underlying/reference market;
- tokenized representation;
- observed premium / discount;
- liquidity;
- volume;
- freshness;
- market state;
- source.

No ticker/name/fuzzy binding. A reference observation is not an executable price.

### DeFi + RWA Yield

Future evidence/underwriting-first categories may include:

- stablecoin yield;
- lending;
- ERC-4626 vaults;
- tokenized Treasury / money-market RWA yield;
- source-proven RWA credit opportunities.

These are not claims of current integrations.

### Yield — Alert Automation & External Delivery

The in-app Alerts engine, canonical Watchlist, persistence/read state and manual Refresh are already implemented.

- in-app Alerts = **implemented**;
- manual Refresh = **implemented**;
- scheduled monitoring/background evaluation = **target / NOT SHIPPED**;
- Telegram = **target / NOT SHIPPED**;
- Discord = **target / NOT SHIPPED**;
- Push = **target / NOT SHIPPED**;
- Email = **target / NOT SHIPPED**.

Yield execution remains independently gated and OFF unless a later reviewed activation changes that contract.

### Radar / intelligence

- FINCO Signals with evidence-backed persistence/history and explicit trigger context;
- continue R-LIVE operational hardening without changing canonical identity authority.

### Crypto / $FINCO activation readiness

Activation-readiness infrastructure is implemented. Q4 may harden operator workflow and observability while preserving these boundaries:

- canonical deployment provenance and explicit configuration;
- resource-specific policy/chain resolution;
- RPC chain/decimals checks and exact threshold precision validation;
- fail-closed activation controls;
- no roadmap step itself chooses a chain, contract or threshold;
- no final tokenomics are defined by this roadmap;
- no staking, burn or token spending is introduced by this phase.

### Wallet Intelligence

Read-only holdings mapped into FINCO canonical asset identity, tokenized-equity context and Radar. Ownership remains separate from entitlement and execution.

### Verification / Model ↔ Market

- source-proven Model ↔ `economic_asset_uid` ↔ canonical market evidence binding;
- public Signed Run trust distribution / verifier completion (M-2);
- optional On-chain Verify design work may continue, but no anchoring is currently implemented.

### FINCO API v1

Stable Model and Radar contracts, usage controls and production-oriented developer access without turning API availability into execution authority.

### $FINCO Access / Metered Utility — M-1

Token-linked service entitlement only after a canonical production deployment and explicit policy activation exist. Define metering only around useful scarce resources after activation prerequisites are explicit. **Token economics are not final; token launch is not claimed.**

---

## Q1 2027 — PROGRAMMABLE FINANCE

Everything in this section is a **TARGET**.

### User-Signed Execution

Target architecture:

Research → Evidence → Preflight → Transaction preparation → User wallet approval → User signature.

No custody. No FINCO server signing. No autonomous discretionary trading.

### FINCO Wallet Portfolio

Future source-proven wallet intelligence may include stablecoins, DeFi positions, RWA tokens, tokenized stocks, Yield positions, $FINCO, chain allocation, protocol allocation, yield earned and evidence/freshness state. Canonical identity only.

### FINCO Agent

Public direction:

observe → analyze → alert → prepare → human approve.

Potential tasks include explaining FINCO evidence, monitoring user-defined conditions, comparing canonical Yield opportunities, explaining wallet changes and preparing an execution route. The agent never becomes price authority, identity authority, calculation authority or entitlement authority, and it does not promise autonomous discretionary trading.

### RWA Collateral & Composability

Future exact-identity intelligence around tradable/transferable state, supported collateral venues, observed LTV parameters, borrowable assets and related lending/yield opportunities. Source-proven exact identity only.

### FINCO Proof / Onchain Attestation

Target flow:

Model / Evidence → Evidence Digest → Signed Run → Onchain Attestation → public commitment/timestamp.

The chain does not validate economic truth. It only proves the committed digest/attestation existed under the defined mechanism.

**Signed Run ≠ FINCO Verify ≠ economic truth.**

### Cross-Chain Routing

Future user-authorized routing across supported networks. No provider is canonical yet. No bridge implementation and no transaction execution implementation are included in the current product.

### Radar / Valuation Intelligence — secondary track

Valuation remains useful without dominating Programmable Finance:

- **FINCO Fair Value** — normalized fundamentals, explicit assumptions and traceable scenario-based valuation;
- **Fundamental Gap** — defined Fair Value versus underlying-market-price metric;
- **Tokenization Premium** — tokenized-market reference/execution context versus the underlying security;
- **Valuation & Tokenized Equity Screener**;
- **Financial Passport** combining asset identity, model version, valuation snapshot, market snapshot, evidence digest and verification state.

These are targets, not current capabilities. They do not grant investment recommendations, guaranteed outcomes or execution authority.

---

## LATER

### Model — Future Asset Coverage / Real-World Asset Expansion

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
- FINCO Agent Alpha extensions where AI explains typed FINCO evidence but never becomes calculation, identity, price or entitlement authority.

---

## Roadmap boundary

**Targets are sequencing, not guarantees.** A roadmap target does not mean a token, financial product, investment return or launch date is guaranteed. FINCO evidence and verification labels do not imply bank, audit or third-party certification unless explicitly stated.

No roadmap item by itself activates custody, server signing, automatic broadcast, staking, burn, token spending, production token gating or Yield execution.