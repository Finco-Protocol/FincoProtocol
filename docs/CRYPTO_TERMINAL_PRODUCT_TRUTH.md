# FINCO Crypto Terminal — Product Truth (V1)

One canonical statement of what the FINCO Crypto terminal supports today.
This file is pinned by `tests/test_unified_crypto_terminal_v1.py`; wording
here is product truth, not marketing.

## Code capability vs operational data availability

These are different facts and are never merged into one claim:

- **CODE CAPABILITY** — a route, read model or authority exists and is tested.
- **OPERATIONAL DATA AVAILABILITY** — persisted evidence currently exists. It is
  derived at read time from persisted authorities (registry, collector health,
  market store), never assumed from the presence of code.

## Domains (one terminal, three product domains)

- **Radar / R-LIVE** (`/radar`, `/radar/r-live`) — AVAILABLE TODAY. R-LIVE is the
  primary FINCO crypto product: a reviewed set of tokenized equities (exact
  AssetKeys only) with token price against its economic reference, premium /
  discount, the age of EACH evidence leg (market activity and oracle age are
  shown separately) and a permanent observation history. Values depend on the
  background collector; observations are reference evidence, never executable
  prices.
- **Tokenized Markets** (`/radar/tokenized-markets`) — UI and authorities:
  SHIPPED. Live collector: runtime-dependent. Market coverage: derived from
  current persisted observations. The surface is presented as a **PREVIEW**
  unless the operational state is PARTIAL_LIVE or LIVE. The operational state
  is one of `IDENTITY_ONLY`, `COLLECTOR_NOT_STARTED`, `COLLECTOR_UNHEALTHY`,
  `NO_PRICED_OBSERVATIONS`, `PARTIAL_LIVE`, `LIVE` and is computed from the
  collector health store, the market store and the reviewed live-collection
  universe — see "Tokenized operational state" below. Four counts are shown
  separately and never conflated: identity catalog, live-collector eligible,
  priced now, history available.
  The seeded `VenueRegistry` is a **research identity source** (third-party
  seeded). It is NOT FINCO-verified market coverage and no seed fact becomes
  market evidence. Malformed / numeric-only identities and representations whose
  exact chain+contract disagree (type or underlying) are excluded from the
  public list but stay inspectable in the audit view.
  Cross-venue basis (basis bps = (token price / underlying reference − 1) ×
  10,000), 24h/7d basis movement, cross-venue divergence and dislocation events
  exist as capabilities and only render where persisted evidence exists.
  **Access**: `tokenized.basic` is PUBLIC (identity + current market state).
  `tokenized.history` and `tokenized.dislocation` are holder resources
  resolved through canonical entitlement; denials remove the payload at the
  composition boundary (never hidden markup). Gating INACTIVE preserves the
  approved ungated behaviour.
  **RWA Integrity V1** is factual/public product information inside the same
  Tokenized Markets detail: canonical representation integrity profiles,
  identity state, market/reference evidence state, ACTIVE-set dependency facts,
  and an attestation/backing evidence contract with explicit
  UNAVAILABLE/STALE/CONFLICT states. There is no composite trust score.
- **Yield** (`/yield`) — code capability: SHIPPED. The default public Explore
  shows **live, source-observed opportunities only**; the bundled reference
  sample is a development / research aid reachable only through an explicit
  research-mode opt-in and is never shown beside live rows. If few live rows
  exist the live universe is small — FINCO does not fill it with fixtures.
  Opportunity listing with canonical market intelligence: movers (TVL floor),
  30d stability (sigma), Morpho-native 30d averages where the provider exposes
  them, Treasury (DGS3MO) spread where both sides are current.
  **Execution remains OFF.**

## Tokenized operational state

| State | Meaning |
|---|---|
| `IDENTITY_ONLY` | No reviewed live-collection universe can be collected (identity catalog only) |
| `COLLECTOR_NOT_STARTED` | Collector health is `NEVER_RUN` |
| `COLLECTOR_UNHEALTHY` | Collector ran but never succeeded, or is currently unhealthy |
| `NO_PRICED_OBSERVATIONS` | Collector healthy but the store holds nothing priced |
| `PARTIAL_LIVE` | Some, not all, reviewed assets have fresh priced evidence (or health is degraded) |
| `LIVE` | Every reviewed asset has fresh priced evidence and the collector is healthy |

Only `PARTIAL_LIVE` and `LIVE` present Tokenized Markets as an operating
product; every other state is labelled PREVIEW / DATA COLLECTION NOT ACTIVE.

## Known data limitations (public, plain language)

- The seeded registry records both a `debt-security` and a `tokenized-equity`
  type for the same exact chain+contract of the reviewed R-LIVE Robinhood
  tokens. The live collector requires exactly one exact identity match, so
  until that identity conflict is resolved by a reviewed decision the
  live-collector eligible count is 0 and Tokenized Markets stays in
  `IDENTITY_ONLY`. No fuzzy correction is applied.
- R-LIVE chart ranges are shown as stored. No generic outlier rule is defined
  yet (a defensible bound needs a reviewed data-quality decision), so extreme
  observations are neither deleted nor flagged automatically.

## Crypto API V1 (`/api/v1/crypto/*`) — CONFIGURABLE BUT INACTIVE BY DEFAULT (developer documentation)

Read-only endpoints adapting the same canonical read models as the UI:

- `GET /api/v1/crypto/tokenized` (public data; `tokenized.basic`)
- `GET /api/v1/crypto/tokenized/{canonical_asset_id}`
- `GET /api/v1/crypto/tokenized/{canonical_asset_id}/history` (`tokenized.history`)
- `GET /api/v1/crypto/tokenized/{canonical_asset_id}/dislocations` (`tokenized.dislocation`)
- `GET /api/v1/crypto/tokenized/{canonical_asset_id}/integrity` (RWA Integrity V1; `crypto.api` only)
- `GET /api/v1/crypto/yield`
- `GET /api/v1/crypto/yield/{canonical_id}`

**Access**: every endpoint resolves the `crypto.api` capability first.
Canonical `Decision.INACTIVE` (the shipped default) keeps the API DENIED —
gating-off never activates the API. Denials are typed sanitized payloads
(`CRYPTO_API_ACCESS_REQUIRED` / `TOKENIZED_PREMIUM_REQUIRED` + safe fields)
and never include protected data.

## Token gating — CONFIGURABLE BUT INACTIVE BY DEFAULT

The $FINCO deployment is not launched. Entitlement policies ship disabled;
when gating is INACTIVE, approved pre-gating behaviour is preserved and no
request is treated as entitled. When gating is enabled, holder resources
resolve through the canonical entitlement authority; failures fail closed.

## Cross-cutting truth

- Missing data is null/“—”, never zero. Stale is not current. QUARANTINED
  representations are not active market evidence. Reference fixtures are
  never live data. **Tokenized Markets** browser/API reads are
  acquisition-free: market evidence comes only from the persisted
  VenueMarketStore written by the separate collector. **Yield** reads are
  canonical snapshot/history reads; the Treasury benchmark (DGS3MO) may
  refresh through its bounded local FRED cache — no other upstream
  acquisition exists on any Crypto read path.
- Freshness (market evidence age) and entitlement (access authority) are
  SEPARATE authorities and never collapsed.
- No execution, signing, custody, swapping, or auto-invest exists anywhere
  in the Crypto terminal.
- RWA Integrity V1 has no approved external Proof-of-Reserves/attestation
  source yet; normal production attestation state may therefore be UNAVAILABLE.
  FINCO does not claim verified reserves or full backing without such evidence.
- RWA Integrity V1 does not perform token-holder concentration analysis, does
  not expose a 0–100/A-B-C composite trust score, and is not an investment
  recommendation.

## NOT YET SUPPORTED

New providers/chains, an approved external PoR/attestation authority,
token-holder concentration analysis (including Gini/HHI), issuer risk scoring,
composite trust scoring, staking, burn mechanics, Model↔RWA integration, and
any trading capability.
