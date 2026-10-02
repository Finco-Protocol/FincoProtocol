# FINCO Yield — Y-LIVE V1: live ingestion, history, staging readiness

Status: **draft implementation, not deployed.** Yield execution remains OFF.
No custody, transaction, signing or token-deployment code is added.

```
SOURCE ──▶ RAW OBSERVATION ──▶ CANONICAL NORMALIZATION ──▶ CURRENT SNAPSHOT
                                        │                        │
                                        ▼                        ▼
                              APPEND-ONLY HISTORY      existing Yield product
                                                       (explore / detail / compare)
```

Invariants preserved: missing ≠ zero · unavailable ≠ zero · stale ≠ current ·
reference ≠ live · observation ≠ executable quote · `$FINCO` never touches the
math (zero diff in `financial_engine/**`, `finco_core/**`,
`finco_radar/authority/**`, `app/model_validation/**`, `app/verified/**`).

## 1. What already existed (reused, not duplicated)

| Concern | Authority reused |
|---|---|
| Opportunity identity | `finco_yield/identity.py` — `yld_` + sha256 of `{chain_id, protocol, product_type, contract_address, sorted underlying addresses, share_token}` |
| Freshness | `finco_yield/freshness.evaluate_freshness` (NATIVE_ENRICHED ≤ 1800 s; fail-closed on missing/future timestamps). **No second classifier.** |
| History | `finco_yield/history.YieldHistoryStore` (JSONL at `FINCO_YIELD_HISTORY_PATH`, `ImmutableObservationRecord`). Yield Alerts already read it. |
| Registry / UI | `finco_yield/registry.py`, `web.py`, `app/templates/yield/*` |

No prior collector existed on any remote branch (`finco_yield/ingestion.py` held
only an unused adapter protocol; `providers.py` is execution-provider code).

## 2. Canonical source-observation contract

`finco_yield/observation.py` → `SourceObservation` (`YIELD_SOURCE_OBSERVATION_V1`).

| Field | Meaning |
|---|---|
| `provider`, `source_record_id` | which provider / which source-native record (`"<chain_id>:<vault address>"`) |
| `chain_id`, `protocol`, `product_type`, `contract_address`, `underlying_address`, `share_token` | exact identity keys (canonical lower-case EVM addresses) |
| `fetched_at`, `observed_at`, `observed_at_policy` | `SOURCE_TIMESTAMP` or `FETCHED_AT`; the policy is recorded so a fetch time is never mistaken for a source timestamp |
| `tvl_usd`, `apy_total`, `apy_base`, `apy_rewards` | `Decimal \| None`; **`None` = UNAVAILABLE, never 0** |
| `source_native` | values exactly as the source supplied them |
| `derived` | how each FINCO field was obtained from source-native values |

`validate()` rejects: missing provenance, naive/future timestamps, invalid
identity, non-finite or out-of-range numbers (APY ∈ [-1, 100], TVL ≥ 0), and
observations with **no** proven economic value (`OBSERVATION_EMPTY`).
Identity is never derived from ticker, symbol, display name, fuzzy matching or
an LLM.

## 3. Source set (V1)

One explicit adapter, determined from the opportunities already in FINCO
(14 Morpho vaults, Ethereum `1` and Base `8453`; no other provider appears in the
bundled provenance).

**`MorphoGraphQLAdapter`** (`finco_yield/live_sources.py`)

* Endpoint: `POST https://api.morpho.org/graphql` (public, no credential).
  Override: `FINCO_YIELD_MORPHO_API_URL`.
* Query: `vaultByAddress(address, chainId) { address name symbol asset{address symbol} chain{id} state{apy netApy totalAssetsUsd} }`
  — one request per known vault, so each target fails independently.
* Identity check (collision protection): response `address`, `asset.address`
  and `chain.id` must equal the FINCO reference identity, else
  `SOURCE_IDENTITY_MISMATCH` (rejected).
* Mapping (APY values are fractions, `0.04 == 4 %`):

  | Source | FINCO | Note |
  |---|---|---|
  | `state.netApy` | `apy_total` | depositor-facing net APY |
  | `state.totalAssetsUsd` | `tvl_usd` | |
  | `state.apy` | `source_native` only | gross native APY, **never** mapped to `apy_base` |
  | — | `apy_base`, `apy_rewards` | **UNAVAILABLE**: the queried fields do not prove a split; FINCO never derives `base = total − rewards` |
* `observed_at`: no source timestamp is requested, so the documented
  `FETCHED_AT` policy applies.
* Typed failures only: `SOURCE_TIMEOUT`, `SOURCE_NETWORK_ERROR`,
  `SOURCE_RATE_LIMITED`, `SOURCE_ACCESS_DENIED`, `SOURCE_UPSTREAM_UNAVAILABLE`,
  `SOURCE_HTTP_ERROR`, `SOURCE_MALFORMED_JSON`, `SOURCE_GRAPHQL_ERROR`,
  `SOURCE_RECORD_NOT_FOUND`, `SOURCE_SCHEMA_REJECTED`, `SOURCE_IDENTITY_MISMATCH`,
  `OBSERVATION_*`. Provider/exception text is never surfaced (no secret leakage).
* The universe is the FINCO reference registry. V1 **refreshes known vaults**;
  it does not discover new ones.

## 4. Current snapshot

`finco_yield/snapshot.py` — `FINCO_YIELD_SNAPSHOT_PATH`, schema
`YIELD_CURRENT_SNAPSHOT_V1`, rows sorted by uid, `content_hash` over the rows.

* **History-backed (authority rule)**: append-only history is the canonical
  audit trail and the snapshot is derived from it. An observation advances the
  snapshot **only** when a valid canonical history hash (64 lower-case hex)
  covers it: newly appended, an exact duplicate already present, or an unchanged
  re-observation covered by an existing hashed history row. A history
  failure (append/read/corruption) means the UID is **not promoted**: its
  previous snapshot row is preserved, or it stays reference-only. If no
  observation is history-backed the snapshot is not rewritten (byte-identical)
  and the run is FAILED; if only some are, only those advance and the run is
  PARTIAL. `snapshot_row()` refuses a missing/invalid hash and the registry
  overlay never presents a row without a valid `history_observation_hash` as
  source-observed.
* **Atomic and durable**: temp file in the same directory, the **complete**
  payload written via `durable_io.write_all` (loops over short writes; zero
  progress fails closed), then `fsync`, and only then `os.replace`; a failed
  write leaves the previous file byte-identical and removes the temp file.
* **Merged**: every previous row is carried forward; a new row replaces its
  predecessor only if it is not older. Nothing is ever removed, so a provider
  failure can never replace a valid snapshot with `[]`, and an empty provider
  result is not treated as a valid empty universe.
* **Overlay, not replacement**: identity always comes from the reference row;
  the snapshot supplies observation values only. A live `None` does **not** fall
  back to the reference value.
* Read is validated (schema, structure, integrity hash); a bad file is an error
  (`SNAPSHOT_MISSING | _UNREADABLE | _MALFORMED | _SCHEMA_UNSUPPORTED |
  _INTEGRITY_FAILED`), never an empty snapshot.

## 5. Append-only history

Existing `YieldHistoryStore`, extended (`append` is unchanged):

| Method | Contract |
|---|---|
| `append_idempotent(record) -> (hash, appended)` | exact-retry dedupe by `observation_hash`; cross-process `flock`; the full line written via `write_all` then `fsync`; on any write failure the file is truncated back to its pre-append size so no torn canonical line is left; refuses a non-newline-terminated (torn) file |
| `latest(uid)` | newest observation for `uid` or `None` |
| `prior(uid, before=, limit=)` | up to `limit` observations strictly before a time |
| `window(uid, since=, until=)` | inclusive time window, ordered by `observed_at` then file order |

These three reads are the single canonical interface intended for the future
Yield Intelligence stream.

Collector dedupe policy: because `FETCHED_AT` observations carry a new time on
every run, an **unchanged** re-observation inside
`FINCO_YIELD_HISTORY_MIN_INTERVAL_SECONDS` (default 900, clamped to ≤ 1500) is
skipped; a changed value, or a heartbeat after the interval, is appended. The
clamp keeps the newest history row inside the 1800 s freshness window so Yield
Alerts never see healthy data as stale. The snapshot still advances on every
successful run.

History payload keys `apy_total`, `tvl_usd`, `apy_rewards` match what Yield
Alerts track; absent metrics are stored as `null`, which alerts treat as MISSING.

## 6. Freshness and provenance in the UI

* Freshness is the existing `evaluate_freshness`: **CURRENT / STALE** (plus the
  existing INVALID / FUTURE_TIMESTAMP guards). Last-known observations stay
  visible as STALE when a refresh fails. Missing live data falls back to the
  labelled reference sample, never to zeros.
* Every row carries `data_origin`: `SOURCE_OBSERVED` or `REFERENCE_FIXTURE`.
  A reference fixture is **never displayed as CURRENT** (it shows `REFERENCE`;
  STALE passes through unchanged).
* The explorer shows a banner: source-observed snapshot (timestamp, count of
  **source-observed** vs reference-only rows; a source-observed row may still be
  STALE and shows its own freshness), **reference fallback** (typed reason), or
  **reference sample — not live data**. Rows show origin and provider; the
  detail page shows origin, provider and fetch time.
* Execution planning still binds to the bundled registry only; an observation is
  never an executable quote.

## 7. Collector

```
python -m finco_yield.collect_live
```

| Variable | Default | Purpose |
|---|---|---|
| `FINCO_YIELD_COLLECTOR_ENABLED` | off | must be truthy for any run |
| `FINCO_YIELD_SNAPSHOT_PATH` | required | current snapshot (collector writes, web reads) |
| `FINCO_YIELD_HISTORY_PATH` | required | append-only history (existing variable) |
| `FINCO_YIELD_MORPHO_API_URL` | `https://api.morpho.org/graphql` | endpoint override |
| `FINCO_YIELD_SOURCE_TIMEOUT_SECONDS` | `8` | per-request timeout (0 < t ≤ 60) |
| `FINCO_YIELD_HISTORY_MIN_INTERVAL_SECONDS` | `900` | unchanged-observation heartbeat (≤ 1500) |

Exit codes: `0` OK · `2` FAILED · `3` PARTIAL · `4` DISABLED/CONFIG_ERROR ·
`75` LOCKED. Report (one JSON line on stdout; no secrets): `started_at`,
`finished_at`, `providers_attempted/succeeded/failed`, per-provider detail,
`observations_fetched/accepted/rejected`, `duplicates_skipped`,
`history_append{appended, skipped_duplicate, skipped_unchanged, failed, result}`,
`snapshot_update{result, rows, previous_preserved, reason}`, `status`,
`exit_code`.

Staging wiring (prepared, **not deployed**): `deploy/yield_collector_v1/`
(production layout + `staging/`), see its README for the activation checklist.

## 8. Known limitations / still fixture-only

* **Not live-verified.** The authoring sandbox cannot reach `api.morpho.org`
  (network egress policy), so the adapter was written against the *documented*
  `vaultByAddress` shape, and every test fixture is a **documented-shape
  synthetic fixture, not a captured live response**. The first manual run on a
  host with egress is the real integration check; a GraphQL schema difference
  would surface as `SOURCE_GRAPHQL_ERROR` / `SOURCE_SCHEMA_REJECTED` per target
  (never as zeros).
* `apy_base` / `apy_rewards` / `apy_intrinsic` stay UNAVAILABLE for source-observed rows.
* `observed_at` is the fetch time (`FETCHED_AT`), not a source timestamp.
* Universe is the 14 bundled vaults; no discovery of new vaults.
* The bundled JSON remains a REFERENCE / FALLBACK / development fixture.
* No history charts or analytics (Yield Intelligence V1).
* History reads are O(file size) per call (JSONL); fine at this scale, to be
  indexed when Yield Intelligence needs it.
