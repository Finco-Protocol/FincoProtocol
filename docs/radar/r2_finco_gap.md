# FINCO Radar R2 — FINCO GAP

## Scope

R2 adds the directional quote/reference computation layer on top of frozen R0 execution quotes and R1 canonical identity. It is read-only. It does not submit transactions, sign wallets, custody assets, create signals, or decide whether a reference is current/expectedly-static/stale.

## Canonical identity

Every R2 observation is keyed by the R1 authority:

`chain_id + contract_address`

Ticker is discovery/reference metadata only. A numeric gap is never produced from a ticker-only join.

## Official reference economics

Robinhood `/prices/{symbol}` returns raw underlying-equity bid/ask and does **not** apply the Stock Token corporate-action multiplier. R2 therefore applies the canonical R1 `currentMultiplier` exactly once:

`token_bid = raw_underlying_bid × currentMultiplier`

`token_ask = raw_underlying_ask × currentMultiplier`

Only USD-denominated reference rows are accepted in R2. Unsupported currency requires a future explicit FX authority; R2 does not assume an FX rate.

## Directional execution price

R0 provides same-chain exact-input normalized execution quotes.

For BUY:

`execution_price = settlement_input × settlement_USD_per_asset / token_output`

The economically matching reference comparator is the multiplier-adjusted official **ASK**.

For SELL:

`execution_price = settlement_output × settlement_USD_per_asset / token_input`

The economically matching reference comparator is the multiplier-adjusted official **BID**.

The midpoint is never a FINCO GAP comparator. It may be used only to size an exact-input SELL request before the execution quote is obtained.

## FINCO GAP formula

For either side:

`gap_bps = (execution_price / reference_side_price - 1) × 10,000`

Interpretation is intentionally raw and directional:

- positive = on-chain quote-implied token price is above the relevant official reference side;
- negative = on-chain quote-implied token price is below it;
- for BUY, positive generally means a more expensive on-chain purchase;
- for SELL, positive generally means a richer on-chain sale.

R2 does not collapse these into an opportunity score. R5 owns signals.

## Size comparison

R2 compares the directional GAP at two notionals. The formulas are:

`buyDirectionalGapDeltaBps = BUY_gap_1000 - BUY_gap_100`

`sellDirectionalGapDeltaBps = SELL_gap_1000 - SELL_gap_100`

The sign interpretation is **side-specific and must never be generalized across both sides**. A positive delta does not mean "worse" on both sides, because the two sides measure opposite economic directions: the BUY gap rises when the on-chain purchase price rises, while the SELL gap rises when the on-chain sale proceeds rise.

For BUY:

- positive delta = larger size is **worse** — the on-chain purchase is more expensive relative to the multiplier-adjusted ASK;
- negative delta = larger size is **better**.

For SELL:

- positive delta = larger size is **better** — the on-chain sale is richer relative to the multiplier-adjusted BID;
- negative delta = larger size is **worse**.

These deltas are the R2 directional-GAP size comparison only. They are not a liquidity score and not an all-in execution-cost model; R3 owns those.

### R0 size-impact authority

R2 emits the canonical R0 size-impact fields `r0BuySizeImpactBps` and `r0SellSizeImpactBps` in its `sizeComparison` block. They are computed with the canonical helper `finco_radar.quotes.normalization.quote_size_impact_bps` over the same BUY/SELL $100/$1,000 execution quote pairs that produced the directional GAP observations, for evidence alignment only. R2 does not redefine or reinterpret the metric: R0 size impact (output/input rate delta) remains distinct from the directional GAP delta (execution price vs multiplier-adjusted reference side), and the R0 live proof continues to publish `sizeImpactBps` in its own evidence artifact (`radar_r0_regression_on_r2.json`). `r0SizeImpactAuthority` in the R2 artifact states this provenance.

## Candidate audit trail

The live proof evaluates candidate symbols in order and accepts the first that independently supplies all four valid observations. Candidates rejected before it are preserved in the PASS artifact under `candidateAttempts.skippedCandidates` as **audit-only** evidence.

This does not change PASS acceptance. One candidate must still provide all four BUY/SELL observations on its own, and observations are never stitched across candidates. The audit trail exists so that a systematic identity or economic failure affecting earlier candidates remains visible in a PASS artifact instead of being silently discarded.

## Cost boundary

R2 derives execution price from the normalized route `fromAmount` / `toAmount` economics already returned by the quote authority. Separately reported `feeCosts` and `gasCosts` are preserved in evidence but are **not added** to R2 execution price because doing so could double-count route economics without a dedicated cost-authority contract.

R3 FINCO LIQUIDITY owns size deterioration, route quality and future all-in execution-cost treatment.

## Reference-state boundary

R2 preserves `generatedAt` and `isTradingHalt` from the official reference but does not classify:

- current vs expected-static;
- market closed vs stale;
- corporate-action pause;
- unexpected staleness.

Every R2 observation therefore carries:

`referenceStateAuthority = R4_NOT_YET_APPLIED`

R4 must authorize reference state before R2 numbers can become terminal/signal authority. The R2 live proof selects a non-halted observation only to demonstrate the computation path; that is not a substitute for R4.

## Fail-closed rules

R2 refuses to compute a numeric gap when:

- R0 quote status is not `QUOTE_OK`;
- quote token identity differs from the R1 canonical key;
- BUY/SELL route orientation is inconsistent;
- settlement USD reference is unusable;
- official bid/ask/multiplier is non-positive or non-finite;
- official ask is below bid;
- reference currency is not USD;
- R1 binding UID/key/symbol does not match the canonical asset;
- exact canonical deployment evidence is absent or duplicated;
- reference timestamp is malformed or timezone-naive.

### Typed status contract

Every R2 failure carries a typed `GapStatus` on `GapComputationError`, so callers categorize failures without parsing message text.

R1 normalization helpers such as `normalize_symbol()` and `normalize_asset_uid()` raise their own exception family (`RegistrySourceError`, `RegistryConflictError`, `RegistryLookupError`). Those types are not part of the R2 typed contract, so without conversion a malformed symbol or UID would escape R2 untyped and bypass `GapStatus` entirely.

Every R2 boundary that calls into R1 validation therefore converts them:

- malformed or broken binding identity → `REFERENCE_BINDING_FAILED`;
- malformed reference content → `REFERENCE_INVALID`.

R1 code is never modified; the conversion happens only at the R2 boundary. An already-typed `GapComputationError` raised inside a converted block passes through unchanged rather than being relabelled.

## Acceptance

R2 live acceptance requires one canonical Robinhood Chain asset with four valid observations:

- BUY $100;
- BUY $1,000;
- SELL $100;
- SELL $1,000.

Each must preserve exact canonical identity, use ASK for BUY and BID for SELL, emit a finite gap, and explicitly disclose that R4 reference-state authority is not yet applied. R1 and R0 live proofs are rerun as regressions. `financial_engine/` and `finco_core/` remain unchanged.
