# FINCO Radar R3 — FINCO LIQUIDITY

## Scope

R3 creates the canonical executable liquidity authority on top of frozen R0 execution quotes (R0 — execution quote authority), R1 canonical asset identity, and R2 directional reference GAP authority. It answers:

> How does actual executable on-chain economics behave as trade size changes, how wide is the executable BUY/SELL market, and how stable is the execution route?

R3 is read-only. It does not submit trades, sign transactions, custody funds, approve tokens, connect wallets, create trading recommendations, label assets BUY/SELL/ARBITRAGE, rank assets by opportunity, produce a 0–100 liquidity score, create historical signals, or implement any R4/R5/R6 behavior.

R3 provides **liquidity evidence and typed analytics**, not a trading signal.

## No composite liquidity score

R3 deliberately does not create a weighted score. No formula such as `40% spread + 30% size impact + 30% GAP` is permitted. The economically distinct components are preserved separately in the snapshot, and a later phase (R5) may consume them only once signal policy exists.

## Canonical identity

Every R3 comparison is keyed by the R1 authority for one exact canonical deployment:

`chain_id + contract_address`

All four execution observations (BUY $100, BUY $1,000, SELL $100, SELL $1,000) MUST come from that one canonical asset. Observations are never stitched from different assets. Ticker remains discovery/reference metadata only and can never repair an identity mismatch. The exact quote objects used for every R3 calculation are retained in reconstructible evidence (`quoteMatrixEvidence`).

## Three distinct size metrics

This is the core economic discipline of R3:

`R0 size impact != R2 directional GAP delta != R3 executable spread`

1. **R0 size impact** (consumed, never recomputed): the canonical router-level quote-rate delta from `finco_radar.quotes.normalization.quote_size_impact_bps` over the $100/$1,000 pair per side. Positive = larger quote has a worse output/input rate; it may include route switching; it is NOT realized slippage and NOT same-pool AMM depth.

2. **R2 directional GAP delta** (consumed from the R2 authority): `buyDirectionalGapDeltaBps = BUY_gap_1000 - BUY_gap_100` and `sellDirectionalGapDeltaBps = SELL_gap_1000 - SELL_gap_100`, where each GAP compares the quote-implied token price with the multiplier-adjusted official reference side (ASK for BUY, BID for SELL). Sign interpretation is **side-specific and must never be generalized**: for BUY, positive = larger BUY is worse; for SELL, positive = larger SELL is better.

3. **R3 executable spread** (R3-owned): see below.

Tests prove these metrics can differ numerically for identical evidence.

## Executable spread formula

For each notional where valid BUY and SELL observations exist:

`P_buy = BUY execution price USD/token`

`P_sell = SELL execution price USD/token`

`P_exec_mid = (P_buy + P_sell) / 2`

`execution_spread_bps = ((P_buy - P_sell) / P_exec_mid) × 10,000`

Computed separately at $100 and $1,000, plus:

`executionSpreadDeltaBps = spread_1000 - spread_100`

Both execution prices come from the same settlement-converted route economics the frozen R2 authority uses: BUY `P = settlement_in × USD_per_settlement / token_out`; SELL `P = settlement_out × USD_per_settlement / token_in`.

This metric is called an **executable quote spread** (or cross-side executable spread) because BUY and SELL are independent routed execution quotes. It is NOT realized slippage and NOT an order-book bid/ask spread. If one side is missing, no spread is emitted; if economics are non-finite, R3 fails typed closed rather than emitting a number.

## Route stability

R3 builds deterministic route signatures from R0 `QuoteEvidence.route`, canonicalizing each leg to an ordered `(tool, canonical_from_asset, canonical_to_asset)` triple. Valid 20-byte EVM addresses are trimmed and lowercased (deployment identity is case-insensitive); arbitrary non-address identifiers keep their content verbatim and are never rewritten into addresses or replaced by tickers; tool names use a documented lowercased convention. Raw leg amounts may be retained as evidence but never determine route identity. Per side, R3 compares the $100 route with the $1,000 route and exposes `buyRouteChanged` / `sellRouteChanged` plus both canonical signatures.

`route change != automatically poor liquidity`

A changed route is evidence only. R3 does not interpret it and does not create a penalty score.

**Route evidence is mandatory.** Absence of route evidence means UNKNOWN, not unchanged. A build fails typed closed with `ROUTE_EVIDENCE_UNAVAILABLE` when `quote.evidence` is missing, the route list is empty, or a leg lacks identity information — so a successful `LIQUIDITY_OK` snapshot guarantees four authoritative route signatures, and a PASS artifact can never serialize `NO_ROUTE_EVIDENCE`.

## Provider cost evidence

R0 already preserves `fee_cost_usd` and `gas_cost_usd`. R3 normalizes them as evidence per quote, where available:

`fee_bps_of_notional = fee_cost_usd / requested_notional_usd × 10,000`

`gas_bps_of_notional = gas_cost_usd / requested_notional_usd × 10,000`

`reported_cost_bps = (fee_cost_usd + gas_cost_usd) / requested_notional_usd × 10,000` (only when BOTH amounts are present; a missing amount is never treated as zero)

`provider fee/gas evidence != automatically additive all-in cost`

### Cost double-counting boundary

R3 does NOT add fee/gas to the execution price. Doing so could double-count route economics, because there is no source-proven contract that these amounts are economically excluded from the normalized route `fromAmount`/`toAmount`. Each cost record carries a typed treatment state:

- `EVIDENCE_ONLY_INCLUSION_UNRESOLVED` — default, fail-safe. The amounts remain evidence only and never enter execution economics.
- `SOURCE_PROVEN_INCLUDED` / `SOURCE_PROVEN_EXCLUDED` — only with explicit source proof.

Unresolved costs are structurally incapable of moving R3 execution prices or spreads.

## Temporal coherence

R3 compares multiple quotes against each other, so quote-pair timing is explicit and mandatory. `LiquidityComparisonPolicy(max_quote_pair_skew_seconds)` is caller-supplied — there is no default and no hidden threshold inside the engine. Four comparisons are validated against the policy:

- BUY size pair: `abs(BUY_100.quoted_at - BUY_1000.quoted_at)`
- SELL size pair: `abs(SELL_100.quoted_at - SELL_1000.quoted_at)`
- $100 cross-side pair: `abs(BUY_100.quoted_at - SELL_100.quoted_at)`
- $1,000 cross-side pair: `abs(BUY_1000.quoted_at - SELL_1000.quoted_at)`

Every required pair must be within policy, otherwise R3 fails closed with `EVIDENCE_TIME_MISMATCH`. All observed pair skews and the actual maximum are preserved in the snapshot. Live proofs may explicitly use `max_quote_pair_skew_seconds = 120`; that is a caller declaration, not an engine default. R2 reference-time coherence remains R2 authority; R3 owns quote-to-quote coherence for liquidity comparisons.

## Identity and lineage validation

R3 fails closed unless all four quotes and all four R2 observations refer to the same canonical deployment. Validated: chain ID, token contract address, settlement chain ID, settlement contract address, side, requested notional, asset UID / R1 key, quote source lineage (all four quotes share one non-empty source), and R2 observation lineage (UID, key, side, notional, `quoted_at`, quote source, execution price — plus, exactly and without tolerance, the derived token amount, the derived settlement USD amount, and the fee/gas evidence — must all match the bound quote). The required notional matrix is exactly `{BUY 100, BUY 1000, SELL 100, SELL 1000}` — no duplicates, no missing rows, no substitutions.

Exact amount lineage means a proportionally rescaled fake observation with an identical execution price is rejected: `observation.token_amount` must equal the quote-derived token amount and `observation.settlement_amount_usd` must equal `settlement_amount × usd_per_asset` derived from the same quote. Fee/gas lineage is correspondence only and never economically additive.

## Typed statuses

`LiquidityStatus` — materially different causes never collapse to a generic BLOCKED:

- `LIQUIDITY_OK`
- `QUOTE_MATRIX_INCOMPLETE`
- `QUOTE_UNAVAILABLE`
- `INSUFFICIENT_LIQUIDITY`
- `IDENTITY_MISMATCH`
- `R2_LINEAGE_MISMATCH`
- `EVIDENCE_TIME_MISMATCH`
- `NON_FINITE_ECONOMICS`
- `COST_EVIDENCE_INVALID`
- `ROUTE_EVIDENCE_UNAVAILABLE`

Every failure travels as `LiquidityComputationError` carrying its typed status. Infrastructure/network errors remain separate from economic/authority statuses (the live proof classifies them as `INFRASTRUCTURE_ERROR` in the candidate audit).

## R4/R5/R6 boundaries

Every snapshot declares:

- `referenceStateAuthority = R4_NOT_YET_APPLIED`
- `signalAuthority = R5_NOT_YET_APPLIED`
- `terminalAuthority = R6_NOT_YET_APPLIED`

R4 will own reference-state classification; R5 will own signals/history; R6 will own the terminal UI. R3 pre-authorizes none of them.

## Why R3 is not a signal

R3 exposes measurements only. It emits no HIGH/LOW LIQUIDITY, GOOD/BAD, A/B/C, 1–5, 0–100, BUY/SELL, ARBITRAGE or OPPORTUNITY labels, and contains no ranking, score or signal field (enforced by focused tests and the workflow gate). Policy-driven interpretation comes later, only where an explicit authority grants it.

## Acceptance criteria

A PASS R3 artifact requires:

- one exact canonical deployment;
- four `QUOTE_OK` observations forming the exact $100/$1,000 BUY/SELL matrix;
- all identity invariants and R2 lineage checks;
- all required temporal comparisons inside the declared R3 policy;
- finite BUY size impact, SELL size impact, executable spread at $100, executable spread at $1,000, and spread delta;
- deterministic route evidence;
- provider-cost evidence explicitly classified with no double-counted all-in cost;
- no score, no signal;
- preserved candidate audit trail.

It does NOT gate on whether liquidity metrics are positive or negative, and does NOT gate on whether routes changed — those are observed outcomes, not PASS/FAIL criteria.

R3 regression gates rerun the R2, R1 and R0 live proofs and retain the original R0 size-aware acceptance. `financial_engine/` and `finco_core/` remain unchanged, as do all R0/R1/R2 production sources.
