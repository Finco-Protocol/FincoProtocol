# FINCO Radar R0 — Execution Quote Authority

## Scope

R0 establishes a read-only, amount-specific execution quote authority. It does not execute swaps, hold keys, request approvals, or modify the FINCO Model engine.

Canonical asset identity is `chain_id + contract_address`; ticker symbols are display/discovery metadata only.

## Source inventory

| Source | Amount-specific | Route | Direction | Fees | Gas | Settlement explicit | Block-bound | Auth / rate limit | R0 role |
|---|---|---|---|---|---|---|---|---|---|
| LI.FI v1 quote | Yes | Yes | Yes | Yes | Yes | Yes | No; FINCO records an immediately observed chain block separately | Public quota without key; key raises limits | Implemented live R0 adapter |
| 0x Swap API v2 | Yes | Yes | Yes | Yes | Yes | Yes | Response includes execution-oriented quote metadata; exact fields are provider-version dependent | API key required | Production candidate / cross-check |
| 1inch swap APIs | Yes | Yes | Yes | Provider-dependent | Yes | Yes | Provider-dependent | Commercial/API access must be reviewed | Secondary candidate |
| Robinhood Stock Token price API | No execution route | No | Underlying bid/ask only | No | No | USD reference | Reference timestamp, not DEX execution block | Public documented limits | Reference/sizing only; never execution authority |
| Explorer display price / last trade | Not sufficient | No | Usually ambiguous | No | No | Often implicit | Diagnostic only | Varies | Explicitly rejected as execution authority |

## Selected R0 authority

The implemented authority is LI.FI `GET /v1/quote` because it can be exercised without a secret and returns an amount-specific same-chain route plus transaction request data. R0 preserves the raw request, selected route steps, amount fields, fee/gas estimates, transaction target/data, and a chain block observed immediately after the provider response.

The quote is marked `SOURCE_UNBOUND` / `OBSERVED_IMMEDIATELY_AFTER_QUOTE_SOURCE_UNBOUND`; an observed block must not be misrepresented as a provider-bound quote block.

## Direction and notional semantics

- BUY $N: $N is converted through an explicit settlement-asset USD reference, then quoted as exact input settlement asset -> Stock Token.
- SELL $N: official Stock Token reference data is used only to size the token input representing approximately $N; the executable economics come exclusively from the route quote.
- $100 versus $1,000 differences are a signed router-level quote-rate delta. Positive means the larger quote has a worse rate; negative means it has a better rate.
- The delta may include route switching when the router selects a different venue/path at the larger size. It is not realized slippage and is not evidence of same-pool AMM depth.

## Settlement policy

Stablecoins are not assumed to equal one USD. A quote request carries `SettlementReference` with an explicit state, source, observation time, and USD-per-asset value. Missing/unusable settlement reference fails closed as `SETTLEMENT_REFERENCE_UNAVAILABLE` before an execution quote request is made.

The R0 live proof uses the quote provider's token metadata USD value only as an explicit settlement reference input. This is sufficient to prevent an implicit 1:1 assumption but is not yet an independent settlement oracle. Because LI.FI supplies both this metadata reference and the execution quote, R0 has a common-source dependency: an incorrect or stale `priceUSD` can shift the requested notional calibration even though the route quote itself remains amount-specific. Later reference-state work should replace/cross-check this input with a dedicated independent authoritative source.

The Robinhood Mainnet USDG contract used by the live proof is the Paxos-published canonical address for chain ID 4663: `0x5fc5360D0400a0Fd4f2af552ADD042D716F1d168` (Paxos USDG mainnet documentation: https://docs.paxos.com/guides/stablecoin/usdg/mainnet).

## Typed failure states

- `QUOTE_OK`
- `QUOTE_UNAVAILABLE`
- `ROUTE_UNAVAILABLE`
- `INSUFFICIENT_LIQUIDITY`
- `UNSUPPORTED_ASSET`
- `SETTLEMENT_REFERENCE_UNAVAILABLE`
- `STALE_QUOTE`
- `AUTH_REQUIRED`
- `RATE_LIMITED`
- `QUOTE_SOURCE_ERROR`

Unknown or failed execution pricing never falls back to a spot/display price.

## Evidence

Each successful quote can retain:

- exact request parameters;
- raw input/output amounts and decimals;
- normalized input/output amounts;
- route/tool steps;
- fee and gas fields;
- transaction target and calldata;
- quote timestamp;
- source request ID;
- immediately observed chain block number/hash with explicit non-binding semantics;
- settlement reference state and raw evidence;
- official Stock Token sizing reference evidence for SELL notional construction.

The live proof additionally records whether the $100 and $1,000 quotes used different route/tool sequences for each direction.

No secrets are persisted.

## Live acceptance proof

`python -m finco_radar.r0.live_proof` probes ordered fallback candidate Stock Tokens and requires all four observations for one representative asset:

- BUY $100
- BUY $1,000
- SELL $100
- SELL $1,000

All four observations must be `QUOTE_OK`. The dedicated size-aware gate then requires at least one of BUY or SELL to show a non-zero $100-versus-$1,000 router-level quote-rate delta. Therefore the gate intentionally blocks only when `BUY == 0 and SELL == 0`; requiring both directions to be non-zero would be stricter than the R0 acceptance criterion.

The proof writes `artifacts/radar_r0_live_quote_evidence.json` and the dedicated GitHub Action uploads the raw evidence artifact. R0 is not considered passed merely because deterministic mock tests pass.
