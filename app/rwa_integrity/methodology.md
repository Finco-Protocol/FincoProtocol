# RWA Integrity & Trust Intelligence V1 — methodology

## What this vertical answers

For one tokenized representation: *what do we actually know, how complete is
the evidence, and what structural integrity/dependency risks are
observable?* — using only canonical FINCO authorities, with typed evidence
states and deterministic flags.  No opaque scoring.

## Evidence vocabulary

| State | Meaning |
|---|---|
| VERIFIED | An approved source affirmatively proves the claim. |
| PARTIAL | Some approved evidence exists; coverage incomplete. |
| UNAVAILABLE | No approved evidence exists (unknown ≠ negative). |
| STALE | Evidence exists but is past its freshness authority. |
| CONFLICT | Approved sources disagree. |
| QUARANTINED | Subject representation is registry-quarantined. |
| NOT_APPLICABLE | The claim does not apply to this shape. |

Missing evidence is never mapped to FAILED/FALSE/ZERO.  Unknown is not
negative evidence.

## Authority map (all reused, none re-created)

| Authority | Owner | Used for |
|---|---|---|
| `finco_radar.venues.VenueRegistry` | PR #175 | canonical underlying / representation identity, platform, network, chain_id, contract, instrument_type, source_ref, registry status (ACTIVE/QUARANTINED/CONFLICT/INACTIVE) |
| `finco_radar.venues.VenueMarketStore` | PR #175 | persisted market observations |
| `finco_radar.venues.intelligence.build_tokenized_intelligence` | PR #179 | freshness, basis availability, cross-venue divergence state |
| `app.radar_ui.market_read.MarketReadService` | pre-existing | underlying bound-reference authority |
| `app.rwa_integrity.contracts` | this PR | backing/attestation evidence contract + typed states |

Market-intelligence mathematics (basis, divergence, dislocation) are NOT
recomputed here; the integrity layer interprets the typed state of the
merged #179 authority.

## Attestation scope binding

Every attestation record binds through canonical_asset_id + chain_id +
contract_address (where applicable).  An issuer-level statement does not
prove backing for every representation by that issuer; cross-chain
coverage is never inferred; an attestation silent on a dimension the
caller requires does not bind.

## Attestation freshness

published_at (source) and observed_at (FINCO ingestion) are distinct and
never substituted.  No usable published_at → UNAVAILABLE (never current).
Age beyond `attestation_stale_days` (default 180) or an expired
`valid_through` → STALE.

## Dependency intelligence

Count-based structural concentration over the canonical representation
universe: representation_count, venue_count, chain_count, source_count,
with SINGLE_* dependency flags.  This is representation/venue/chain/source
concentration — NOT token-holder concentration (no holder data exists in
V1, and none is implied).

## Integrity flags

Deterministic, fact-based: IDENTITY_CONFLICT,
REPRESENTATION_QUARANTINED, MARKET_EVIDENCE_UNAVAILABLE/STALE,
REFERENCE_EVIDENCE_UNAVAILABLE, BASIS_EVIDENCE_UNAVAILABLE,
SINGLE_VENUE/CHAIN/SOURCE/REPRESENTATION_DEPENDENCY,
ATTESTATION_UNAVAILABLE/STALE/SCOPE_MISMATCH.  No subjective language.

## V1 non-goal: composite trust score

No 0–100 score, no A/B/C rating, no safe/unsafe recommendation.  The
evidence matrix IS the product; a scored model would require an explicitly
reviewed methodology and is deferred.

## History/events

A typed event model (REPRESENTATION_QUARANTINED,
IDENTITY_CONFLICT_DETECTED, ATTESTATION_BECAME_STALE, …) is defined by the
state transition rules in #179; a first observation already in a bad
state must not fabricate a transition.  Event persistence is deferred
until an events consumer exists.
