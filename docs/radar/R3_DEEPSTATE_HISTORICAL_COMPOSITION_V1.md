# FINCO Radar R3 — Deepstate Historical Cross-Venue Read Model (V1)

## Authority and scope

R3 is a **read-only additive composition** in
`app/crypto_terminal/deepstate_composition.py`. It uses the reviewed
Deepstate execution collector (#192/#193), the append-only
`VenueMarketStore`, the canonical Robinhood/NVDA registry and R-LIVE identity
policy, and the existing basis/divergence arithmetic. It does not edit
`finco_radar/venues/intelligence.py`, `relative_value.py`,
`robinhood_live.py`, `basis.py`, the collector, any pricing model or frozen
financial authority.

**Deepstate is not a VenueRegistry representation.** It is an independent
executed-trade MARKET source for exactly:

- Chain: Robinhood Chain 4663.
- Router: `0x6cf19308C22FC82ea620Fa0B3E94948d20f27B96`.
- Pool: `0x42819cadfbb25aab80543236e280fba4e61aa61e0b5b777541de54ae69da35e4`.
- Reviewed book: `0xdf941c235503a5d2e67aee5dea00f2965f99421c0d034bd77f924c05c66bf399`.
- Underlying: exact NVDA registry contract, chain ID, and R-LIVE
  `economic_asset_uid`. Textual ticker similarity never supplies identity.

## Four separate claims

1. `HISTORICAL_EXECUTION_PROVEN`: original executed match, source block
   timestamp, tx/hash, block/hash, log/match index and raw **USDG/NVDA** amount
   are preserved; collection time never replaces execution time.
2. `HISTORICAL_COMPARISON_AVAILABLE`: requires independently source-proven
   **USDG/USD** normalization, applicable reviewed age policy, matching
   economic-asset/market-clock identities, identical normalized units and
   **≤300 seconds** execution-to-R-LIVE market clock skew. No interpolation.
3. Current Deepstate market freshness: **UNAVAILABLE**. The collector retains
   `deepstate_freshness_policy=NOT_YET_APPROVED` and
   `FreshnessState.UNAVAILABLE`.
4. Current executable quote authority: **UNAVAILABLE**. A historical fill
   never establishes availability or a tradable bid/ask.

The production read model intentionally does **not** pass a normalization
policy. Even source-enriched stored observations remain historically raw
unless a future separately reviewed policy activation is made. A pure
`ReviewedNormalizationPolicy` seam permits deterministic **candidate tests**,
not current market activation. The existing `normalize_to_usd` arithmetic
is reused only after strict source, feed, block proof, Decimal and timestamp
validation. `USDG = USD` is never assumed.

## Read model and access

The existing `app.crypto_terminal.tokenized_read.detail` composes an
optional `deepstate_history` for NVDA only when the existing
`tokenized.history` **and** `tokenized.dislocation` access checks permit it.
`app/api/v1/crypto_router.py` serializes it additively as
`intelligence.deepstate_historical_market` under the already authorized
`/crypto/tokenized/{canonical_asset_id}` endpoint, with no new endpoint or
provider acquisition. The API-wide `crypto.api` denial remains unchanged.
R-LIVE representations, basis/reference, #183 history/dislocation and current
`cross_venue` stay exactly as before.

No new UI/Monitor route is created in R3; any separate product surface
must first be reconciled with #170/#179.

## Eligibility/reason matrix

| Evidence | Result | Reason when unavailable |
|---|---|---|
| Exact Deepstate tx/Router/book/chain/pool and source clock | Historical proof | `INVALID_MARKET_EVIDENCE` |
| Wrong canonical registry contract/chain/underlying | Not composable | `EXACT_IDENTITY_UNAVAILABLE` |
| No genuine persisted history | Not composable | `HISTORICAL_COMPARISON_UNAVAILABLE` |
| USDG/USD rate, source, feed identity, timestamp or block proof missing | Raw only | `MISSING_NORMALIZATION_EVIDENCE` |
| Production policy not independently reviewed | Raw only | `NORMALIZATION_POLICY_UNAPPROVED` |
| Invalid/stale/future rate beyond a reviewed candidate policy | Raw only | `MISSING_NORMALIZATION_EVIDENCE` / `NORMALIZATION_OUTSIDE_APPROVED_TIME_POLICY` |
| R-LIVE evidence has a different quoted unit | No comparison | `COMPARISON_UNIT_MISMATCH` |
| Execution vs R-LIVE canonical MARKET timestamp > 300 s | No comparison | `SOURCE_TIME_SKEW_EXCEEDED` |
| All historical evidence and candidate policy gates pass | Historical pair only | `HISTORICAL_COMPARISON_AVAILABLE` |
| Any existing historical fill used as a current quote | Always refused | `DEEPSTATE_CURRENT_FRESHNESS_POLICY_NOT_APPROVED` |

The 30-day source-clock window and maximum 120 returned Deepstate matches are
**historical read/output bounds**, not a live freshness SLA, comparison skew
expansion, or assumed market availability.

## Future activation requirements (not part of R3)

A distinct reviewed authority must establish an original USDG/USD source and
immutable quote source identity, chain/feed/block proof, heartbeat/age limit,
timestamp alignment and a reviewed method of associating the normalization
quote to each exact Deepstate execution. A separate market-data availability
policy and an **independent executable-quote authority** are required for any
future current cross-venue product. Neither is activated here.

Post-merge staging acceptance should confirm historical NVDA fills display
as raw USDG evidence, that normalized/divergence/current states are unavailable
without the above approvals, and that existing Tokenized and Crypto API access
denials, current R-LIVE market clocks and #183 percentiles remain unchanged.
