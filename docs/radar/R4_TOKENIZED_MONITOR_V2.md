# FINCO RADAR — R4 / WF-02: Tokenized Market Monitor V2

Status: **DRAFT FEATURE CANDIDATE — requires independent review and staging acceptance**.

Base observed: `main` at `6fc77de98bc0562fb51efdbf96e1803a29b5b148` (RC-2 PR #278). Only scoped presentation/read-model work, no execution, provider calls, collector activation or historical authority edits.

## Product and authority map

| Surface | Canonical authority (unchanged) | Scope |
|---|---|---|
| Identity, universe, source clocks | `VenueRegistry`, existing `tokenized_operational`, `tokenized_composition` | Verified current representation and public basic fields |
| Current token/reference basis | `finco_radar.venues.basis`, `finco_radar.venues.intelligence` | Only fresh, compatible price/reference evidence |
| 24h and 7d basis history | `build_tokenized_intelligence` | Persisted source-clock observations; history entitlement |
| Distribution: min / Q25 / median / Q75 / max / percentile / n / span | `compute_basis_distribution` (PR #183) | Own-history only, at least 8 observations, span >=3,600 s |
| Dislocation threshold, crossing, sign reversals, gaps, duration | `compute_dislocation_persistence` (PR #183) | Dislocation entitlement; unknown starts have no duration |
| Deepstate executed-market history | `build_deepstate_historical_context` (PR #276) | NVDA; BOTH premium entitlements; historical USDG/NVDA |
| Current Deepstate cross-venue | Existing R3 release-closed currentness policy | `UNAVAILABLE`; no normalized USD comparison or quote asserted |
| Collector health | Existing Tokenized collector health seam | Operational state is not market freshness |

R4 adds only `app/radar_ui/tokenized_monitor_v2.py`, which calls the canonical PR #183 calculators. No arithmetic/recalculation of basis or distribution is introduced. The existing `build_dislocation_monitor` remains the established cross-asset read-model; the already composed primary rows are projected directly to avoid a second store scan in the HTML request.

## Bounded read behavior and UI

The existing `/radar/tokenized-markets` primary view is capped to 60 reviewed underlyings. It uses persisted identities/observations and an exact selected `(venue_id, instrument_id)` match; no fuzzy asset linkage. The new overview counts are derived from the bounded displayed universe and should not be interpreted as network-wide coverage.

Filtering and sorting are server-side over pre-redacted values. `q` is truncated to 48 characters. Supported filters: available, stale, unavailable, current dislocation, current premium, current discount, eligible distribution and Deepstate historical proof. Sorts: evidence-first current dislocations, absolute current basis, eligible own-history percentile, provable duration and symbol. `None` is last, not zero. Current basis is suppressed when evidence is stale.

HTML and existing Crypto API V1 detail now share `app.crypto_terminal.tokenized_read.detail` for the premium read projection; no new API endpoint or API version. R4 attaches `intelligence.relative_value` only when available and entitled; the existing Deepstate `intelligence.deepstate_historical_market` payload remains gated.

## Entitlement matrix

| Data class | `tokenized.basic` | `tokenized.history` | `tokenized.dislocation` |
|---|---|---|---|
| Identity, price / reference, public current basis and evidence stamps | Basic authority | Not needed | Not needed |
| Basis movement, distribution & own-history percentile | — | Required | Not needed |
| Current dislocation state, threshold & proven duration | — | Not needed | Required |
| Deepstate historical fill provenance, normalization-rejection, historical pair status | — | Required | Required |
| Crypto API envelope | `crypto.api` gate applies first | Existing resource gate | Existing resource gate |

Premium-denied metrics are not embedded into HTML `data-*` attributes, JSON, sort metadata or hidden markup. Dislocation-only access may use raw persisted points **server-side** to compute canonical persistence but neither underlying points nor distribution are serialized.

## Evidence and acceptance contract

Required before review/merge: focused `pytest tests/test_radar_r4_tokenized_monitor_v2.py -q`, existing Tokenized and R3 regression suites, public-source safety scan, Python compilation, browser acceptance for landing and NVDA gated detail, exact-head 8-workflow CI matrix, source-identity clocks, and merge-base/frozen path inspection.

Staging (not performed here): load public primary/empty and catalog/audit views, check live/stale/unavailable semantics, all four premium entitlement combinations, no browser-initiated network acquisition, NVDA historical-only labels and rejected USDG/USD conversion; compare HTML against Crypto API response and screenshot the actual rendered pages. No activation of new financial/market authority.

**Not released; no merge; no deploy; no self-approval.**
