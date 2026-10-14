# FINCO RADAR R5 / WF-03 — Tokenized Dislocation Lifecycle V1

## Authority inventory and isolation

This is an additive **read-only factual event projection**. It has no provider,
trade execution, wallet, settlement, trading recommendation, prediction or
notification-delivery authority.

- **#179:** `finco_radar.venues.intelligence._basis_from_observation`,
  `_events`, `build_tokenized_intelligence` and
  `effective_observation_state` remain the only approved Tokenized basis,
  crossing, MARKET freshness and reference comparability authorities.
  `dislocation_threshold_bps()` is reused; no second threshold.
- **#183:** `relative_value._classify`,
  `compute_basis_distribution` and `compute_dislocation_persistence`
  supply the original own-history taxonomy and provenance-aware persistence.
  Distribution percentiles are **positions within one's own observed basis
  history**, never probability, return or profit estimates.
- **#21:** canonical `json.dumps(sort_keys=True, separators=(",", ":"),
  ensure_ascii=False)` and SHA-256 deterministic serialization is reused as
  a *format convention*. The original R5 `SignalSnapshot` has legacy
  side/size/liquidity inputs and is intentionally NOT passed Tokenized venue
  observations. The different semantic event domain merits new typed names.
- **#276:** Deepstate historical executed NVDA/USDG fills remain separate
  from active tokenized representations. This module does not inspect or
  normalize Deepstate as a current market. `current_deepstate_signals =
  UNAVAILABLE`; no USDG parity assumption or freshness policy change.

The module is `app/crypto_terminal/tokenized_signal_lifecycle.py`, used as
a library function by a **future** appropriately authorized consumer.
There is no new route/API/UI integration, so it cannot bypass existing
`crypto.api`, `tokenized.history` or `tokenized.dislocation` entitlements.
Future callers MUST enforce resource checks **before** invoking it.

## Exact representation identity

Every history stream is keyed by the full:
`canonical_asset_id + venue_id + chain_id + contract_address +
instrument_id + representation_type`.

The registry must resolve the exact ACTIVE representation. A missing chain or
contract fails closed (no symbol-only fallback). The existing store is read
through `get_window_for_identity` and `get_latest_for_identity`.
An observation must agree with this identity, must supply independent
persisted chain/asset-key provenance, and must use the reviewed
`USD_PER_TOKENIZED_SHARE_EQUIVALENT` comparison unit. R-LIVE observations
additionally require
the approved exact `asset_key` and `economic_asset_uid`. Quarantined,
wrong-lineage and Deepstate execution evidence is never signal-producing.
Such a rejected row also breaks potential economic continuity.

The original observation digest is retained; source `ts` and
`collected_at` are kept separate. Same-clock rows with distinct digests
cannot establish a causal sequence; out-of-order source times fail closed.
The earliest visible historical row has `UNKNOWN_PRIOR`, NOT an invented
appearance. Evidence gaps require genuine new observations before economic
transition claims resume.

## Strict transition matrix

| Before | After | Factual projection |
|---|---|---|
| Unknown/first evidence | Dislocated/normal/unusable | NO_MATERIAL_CHANGE (diagnostic only) |
| Valid within threshold | Valid dislocated; existing #179 crossing fact | DISLOCATION_APPEARED |
| Valid dislocated | Valid within threshold | DISLOCATION_CLEARED |
| Valid premium vs discount | Valid opposite dislocation with #179 sign reversal | DISLOCATION_DIRECTION_CHANGED |
| Valid same-direction dislocation | New valid same-direction observation | DISLOCATION_PERSISTENCE_UPDATED |
| Valid comparable evidence | STALE | EVIDENCE_BECAME_STALE, never cleared |
| Valid comparable evidence | UNAVAILABLE | EVIDENCE_BECAME_UNAVAILABLE, never cleared |
| STALE/UNAVAILABLE | Valid new observation | EVIDENCE_RECOVERED; prior dislocation continuity not proved |
| Otherwise | Any admissible no-op | NO_MATERIAL_CHANGE |

All source transitions are observation-based. An appearance requires a
provable same-identity crossing from a usable predecessor. Sign reversals
rely on canonical #179 crossing events and #183 episode policy.
`DISLOCATION_PERSISTENCE_UPDATED` only states another same-direction
sample was observed; it never proves continuous availability between
sample timestamps. Source-clock span (if #183 proves its start) is reported
as `observed_span_seconds`, not uptime or a wall-clock SLA.

An unavailable basis suppresses persistence claims. Current freshness
is calculated only by the existing #179 read-time authority.
Historical event records are labelled historical and are not current
market alerts, even if previously valid.

## Deterministic event provenance

`event_id = SHA256(UTF8(canonical_json(payload)))` where payload contains:
contract version, exact full representation identity, event kind, original
source timestamp, current/prior MarketObservation digests, canonical basis
and rejection reason, original threshold, previous/current classifications,
and continuity state.

Collection/transport clock, read `as_of`, random IDs and delivery metadata
are excluded from event identity. The projected event retains original
digests, canonical threshold, #183 distribution context and persistence
start status. Distribution context is the **current own-history summary at
evaluation time**, not a backdated percentile as of an old event.

## Alert readiness without delivery

Events have `eligible_for_future_alert`, `suppression_reason`,
`temporal_classification`, `evidence_state` and a neutral factual
`description`. Eligibility is only a candidate: a valid, current,
non-gap economic appeared/cleared/direction-changed event. Persistence
updates, evidence-state transitions, no-ops and historical economic
events are suppressed as delivery candidates. **No notifications enabled**
in this PR; no user preferences, destinations, webhook, Telegram,
Discord, email, push or scheduler.

The public API / access boundary has not changed. A later alert delivery
workflow must add the user-specific subscription/policy authority,
entitlement checks, dedupe/outbox, safe transport, revocation and audit
without altering these source-event facts.

## Bounds and acceptance

Historical source window = seven days (matches #179/#183); at most 20 exact
representations, 256 processed observations per representation, and 60
projected events per evaluation. All timestamps are original source clocks.
Store APIs are read-only. No new database or write operation. Note that the
existing store returns a seven-day window before the adapter trims its
in-memory processing tail; this V1 bound applies to processing and output,
not to upstream SQLite row count.

Acceptance includes deterministic IDs and repeat reads, exact registry
isolation, digest collisions, source time order, missing predecessor,
quarantine, stale/unavailable transitions, gap recovery, sign reversal,
valid clearing, distribution insufficiency, Deepstate isolation,
bounded outputs and no read-path provider or database writes.

**Independent final review and exact-head mandatory CI required.**
No self-approval, merge, staging deploy or R4 UI change.

## RC-2 / RC-3 exact-content successor governance — Correction A proposal

**Not an approval or a deployment authorization.** PR #279 is an R5/RC-3
candidate developed after the normal RC-2 merge, not a replacement for RC-2
source authority. The original RC-2 merge is
`6fc77de98bc0562fb51efdbf96e1803a29b5b148`, with parents
`5058c6b4935168241d6923676cb32955cb903185` and
`2155a76bfff4acc3a4e15f7cf35012933ce1a10c`. Its exact tree is
`4fdcd03b5e0ed3c4b87d9016f2522bfe50bf0d05`.

The historical verifier in `tests/test_rc2_integration_manifest.py` remains
unchanged in authority and still validates the complete RC-2 exact blob set,
financial candidates, CSRF call-site inventory, router AST and source-head
ancestry, release-closed Revenue V3/Junior flags and the byte-exact two-line
CI-budget workflow delta. It still rejects RC-3 content if applied directly
to RC-2.

A **separate successor validator** checks that exactly one path is added:
`app/crypto_terminal/tokenized_signal_lifecycle.py`, with git diff
**status A**, worktree git blob and committed HEAD git blob both exactly
`6f3cb95782426dee5ed7dfa1a5bac71b29388014`. It additionally pins
the merged RC-2 commit parents/tree/ancestry. Only that verified addition
is subtracted from the input to the *historical* RC-2 verifier. No other
production path is exempted, including any sibling under
`app/crypto_terminal/`. No wildcard, status M, descendant grant or
prospective replacement blob is accepted.

Focused mutations must reject: one-byte R5 content drift, changed committed
blob, missing/duplicate/M/D R5 status, extra production files, changed
financial blob, missing/replaced RC-2 source head, CSRF inventory drift and
changed merge parents/tree/ancestry. Scope excludes all product/price/collector/
entitlement/notification authority and CI workflow modifications.

The proposer neither approves this successor nor authorizes merge. An
independent reviewer must verify the pinned content and successful exact-head
Public Safety before a merge decision.
