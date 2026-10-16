# FINCO RADAR — R6 Tokenized Signal Feed V1 / Workstream A

**Status:** DRAFT CANDIDATE — independent governance/security approval required. NO MERGE, DEPLOY or staging execution.

**Integration baseline (preflight):** `main` at `540e1f4bb54d53ad6d2c1628074b94fdb0c9eb06`. R5 PR #279, R4 PR #280, R3 PR #276, Evidence Clock #237 and relative value #183 are present in main.

## Mission and authority

The existing `/radar/tokenized-markets/{canonical_asset_id}` detail gains a **Signals & Events** accordion. Read-only API: `GET /api/v1/crypto/tokenized/{canonical_asset_id}/signals`.

One shared adapter, `app/crypto_terminal/tokenized_signal_read.py`, calls **only** `build_tokenized_signal_lifecycle` from the unchanged `app/crypto_terminal/tokenized_signal_lifecycle.py`.

The R5 function remains sole authority for identity, original event IDs, digests, source observation clocks, threshold crossing, transitions, persistence, stale evidence and alert eligibility. The adapter serializes those original facts and reverses the already bounded chronological event list to show newest first (max **30**). It never derives a second event ID or creates a new observation/event store.

## Event field/provenance matrix

| Field | Source authority | Meaning |
|---|---|---|
| `event_id`, `kind` | R5 `SignalLifecycleEvent` | Original deterministic ID and typed lifecycle transition |
| `identity.canonical_asset_id/venue_id/chain_id/instrument_id/contract_address/representation_type` | R5 exact registry binding | No symbol-only, Deepstate, or cross-instrument substitution |
| `source_observed_at` | R5 `MarketObservation.ts` | Original MARKET time, never API clock or `collected_at` |
| `prior_observation_digest`, `current_observation_digest` | R5 immutable market rows | Original evidence lineage |
| `previous_classification`, `current_classification`, `continuity_state` | R5 classification/gap proof | Same direction alone never proves uninterrupted duration |
| `basis_bps`, `threshold_bps`, `basis_reason` | R5 via #179 | Canonical pricing/reference evidence; unavailable != zero |
| `proven_crossing_source_timestamp`, `persistence_start_state`, `observed_span_seconds` | R5 via #183 | No duration without a proven start |
| `temporal_classification`, `evidence_state`, `suppression_reason` | R5 source-clock policy | Historical cannot be relabeled actionable |
| `distribution` | R5 via #183 exact own-history metrics | Distribution is not probability or forecast |
| `eligible_for_future_alert` | R5 factual eligibility | Not a notification, delivery, subscription or signal to trade |
| `current_deepstate_signals` | R5 release-closed value | `UNAVAILABLE`; original USDG/NVDA historical fills never generate current signal |

## Access matrix and fail-closed behavior

| crypto.api | tokenized.history | tokenized.dislocation | R6 API/HTML full feed |
|---|---|---|---|
| Denied | any | any | HTTP 403 API; no lifecycle call |
| Allowed | Denied | Denied | API HTTP 403; HTML locked; no lifecycle call |
| Allowed | Allowed | Denied | API HTTP 403; HTML locked; no lifecycle call |
| Allowed | Denied | Allowed | API HTTP 403; HTML locked; no lifecycle call |
| Allowed | Allowed | Allowed | Bounded R5 read-only feed; no notifications |

R6 does **not** modify `/dislocations`: that endpoint retains its independent dislocation entitlement. The API uses the existing `crypto.api` adapter first, then `tokenized.history` and `tokenized.dislocation`, then the existing BASIC decision; source composition occurs only after every required authorization. HTML likewise requires both premium access decisions before calling the adapter. Denied payloads contain no event, digest, basis, threshold, distribution, hidden metadata or event ID.

The existing token gating inactive decision semantics are inherited unmodified. Nothing enables token gating.

## Security and bounded evidence controls

- 30 newest events at most, from an R5 bounded seven-day source window, max 20 exact representations and 256 observations per representation.
- No provider/network calls, collection, market writes, event database, alerts, predictions, trading or external notifications.
- No changes to any venue authority, R5 lifecycle, basis/distribution/persistence calculations, source clocks, normalization or historical Deepstate policy.
- Empty or absent store yields an explicit `HISTORY_UNAVAILABLE` or `NO_OBSERVED_EVENTS` result; no invented rows.
- API preserves the existing V1 `api_version`, `schema_version`, `resource`, `state`, `as_of`, `data` envelope, including sanitized denial and unknown-asset results.
- HTML details remain in the existing Radar interface; no new dashboard or landing-page scan across all 60 monitored assets.
- The R6 product is a read projection, not a notification delivery system.

## Proposed scope and governance

Workstream A owns exactly:
`app/crypto_terminal/tokenized_signal_read.py`,
`app/radar_ui/tokenized_router.py`,
`app/api/v1/crypto_router.py`,
`app/templates/radar/tokenized_markets_detail.html`,
`static/css/radar-signal-feed.css`,
`tests/test_radar_r6_tokenized_signal_feed.py`,
`docs/radar/R6_TOKENIZED_SIGNAL_FEED_V1.md`.

The four existing production changed files are not covered by any broad blanket path exemption. RC-2 / RC-3 historical content pins must remain intact; any successor exact-content path/blob proposal requires **independent approval** before integration. Production and financial/venue/collector namespaces remain untouched. No CI workflow modifications.

## Exact-head release gates and staging (NOT executed)

1. Focused local: R6 tests, R5 lifecycle tests, R4 Monitor regression, Tokenized HTML/API and entitlement tests, compile, and `tools/public_safety_scan.py`.
2. Independent exact-head review: diff/changed-file authority, all mandatory CI including full Public Safety and evidence artifacts, normal merge-base and branch divergence.
3. Future authorized staging acceptance at `staging.finco.one`: approved R6/R4 build SHA; asset detail and event drill-down screenshot; source timestamp/digest parity against API; newest-first/max 30; no-current/stale/unknown-prior cases; sign reversal and evidence gaps; all 4 premium combinations; `crypto.api` fail-closed; network panel verifies no acquisition/POST or leak; no current Deepstate signal; no alert delivery claim.
4. Only after approved RC-3 integration and explicit deploy authorization may staging be exercised. Production `app.finco.one` untouched.

**NO SELF-APPROVAL. NO MERGE. NO DEPLOY. NO STAGING EXECUTION.**
