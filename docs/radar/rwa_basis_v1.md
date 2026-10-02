# RWA Basis / Tokenized Market Monitor V1

## Scope

V1 is a read-only derived Radar surface over existing R-LIVE authority. It answers one descriptive question for one already-reviewed economic asset: how does the source-proven tokenized observation relate to the Robinhood reference basis at one explicit evaluation time?

It creates no new identity authority and changes no finco_radar/authority file.

## Identity

A record is eligible only when reviewed R-LIVE policy already proves:

economic_asset_uid ↔ Robinhood registry deployment ↔ chain 4663 ↔ canonical token contract ↔ reviewed on-chain pool.

Runtime detail lookup accepts exact economic_asset_uid only. Ticker, company name, token name and display symbol are never identity lookup keys.

## Observations

The reference side reuses ROBINHOOD_STOCK_TOKEN_BOUND_PRICE: official underlying bid/ask midpoint transformed by canonical currentMultiplier into USD per token-equivalent.

The tokenized side reuses the independent R-LIVE Uniswap V3 TWAP converted through the reviewed USDG/USD Chainlink quote. It is a reference observation, not an executable quote.

Where present, liquidity is the source-proven raw Uniswap V3 active-liquidity value with an explicit raw unit. V1 has no source-proven 24h volume authority, so 24h volume remains unavailable.

## Basis

basis_fraction = (tokenized_value / reference_value) - 1

basis_bps = basis_fraction * 10,000

Positive values are PREMIUM, negative values DISCOUNT and zero PAR. These labels are descriptive.

Missing values are never coerced to zero. The reference denominator must be strictly positive. A factual tokenized zero remains zero. The derived layer reconstructs the Decimal calculation and requires it to equal the existing B1.0 authoritative basis value; mismatch suppresses the metric.

## Time and freshness

One timezone-aware evaluation_time is shared by snapshot and history reads. Both source timestamps and observation_age_difference_seconds are exposed.

The comparison window is existing R_LIVE_AUTHORITY_POLICY.max_evidence_skew_seconds. V1 does not create a generic freshness classifier. Current state comes from the canonical read-time R-LIVE snapshot view; STALE and UNAVAILABLE suppress current basis.

## History

V1 reuses the append-only, digest-verified B1.3 ledger. It creates no second history store.

The product exposes prior exact observation and existing exact 24h range. A 24h change is available only when the latest canonical history point is within one hour of evaluation time and one exact canonical point exists within ±1 hour of evaluation_time minus 24 hours. The nearest qualifying exact point is used and the actual observation gap is exposed.

There is no interpolation, synthetic backfill or re-timestamping.

## Surfaces

Browser: GET /radar/crypto/rwa/basis

Public read-only API:
- GET /api/v1.1/radar/rwa-basis
- GET /api/v1.1/radar/rwa-basis/{economic_asset_uid}

Unknown or malformed UIDs return typed UNBOUND. There is no ticker fallback and no write path.
