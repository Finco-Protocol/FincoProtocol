# FINCO Crypto Terminal — Product Truth (V1)

One canonical statement of what the FINCO Crypto terminal supports today.
This file is pinned by `tests/test_unified_crypto_terminal_v1.py`; wording
here is product truth, not marketing.

## Domains (one terminal, three product domains)

- **Radar** (`/radar`, `/radar/crypto`) — AVAILABLE TODAY. Market discovery
  over canonical Radar authorities (R-LIVE, Radar crypto overview).
  Observations are reference evidence, never executable prices.
- **Tokenized Markets** (`/radar/tokenized-markets`) — AVAILABLE TODAY.
  Cross-venue tokenized-equity composition over the exact venue registry and
  persisted collector observations: reference evidence, representations,
  basis (basis bps = (token price / underlying reference − 1) × 10,000),
  24h/7d basis movement, cross-venue divergence, dislocation events.
  **Access**: `tokenized.basic` is PUBLIC (identity + current market state).
  `tokenized.history` and `tokenized.dislocation` are holder resources
  resolved through canonical entitlement; denials remove the payload at the
  composition boundary (never hidden markup). Gating INACTIVE preserves the
  approved ungated behaviour.
- **Yield** (`/yield`) — AVAILABLE TODAY. Opportunity listing with canonical
  market intelligence: movers (TVL floor), 30d stability (sigma),
  Morpho-native 30d averages where the provider exposes them, Treasury
  (DGS3MO) spread where both sides are current. **Execution remains OFF.**

## Crypto API V1 (`/api/v1/crypto/*`) — CONFIGURABLE BUT INACTIVE BY DEFAULT

Read-only endpoints adapting the same canonical read models as the UI:

- `GET /api/v1/crypto/tokenized` (public data; `tokenized.basic`)
- `GET /api/v1/crypto/tokenized/{canonical_asset_id}`
- `GET /api/v1/crypto/tokenized/{canonical_asset_id}/history` (`tokenized.history`)
- `GET /api/v1/crypto/tokenized/{canonical_asset_id}/dislocations` (`tokenized.dislocation`)
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

## NOT YET SUPPORTED

New providers/chains, PoR/attestation scoring, concentration scoring,
Gini/HHI, issuer risk scoring, staking, burn mechanics, Model↔RWA
integration, and any trading capability.
