# JEV Radar Intelligence V1 — delta review dossier

Status: **experimental, pre-release, draft PR #146**, default OFF. Not shipped, not deployed.
Public Product Truth (README, ROADMAP, `OPUS_V1_REVIEW/**`) is deliberately not updated.

This dossier is written so that a clean-room reviewer can answer six questions:
usefulness, scoping, authority contamination, scientific defensibility, production
characteristics, and ship / keep experimental / remove. Section 10 gives the author's own
assessment; every claim in the other sections can be checked against the files named.

## 1. Purpose

Attach small, typed, probabilistic **interpretation labels** to canonical R-LIVE evidence, so
that a reader of an R-LIVE asset page gets a quick "what regime does this premium series look
like, and does it deserve attention" reading. Jev (TypeSafe's System One model) is a fast
classifier of structured state: it returns typed answers with probabilities. It is not a
generator, a retrieval system or a calculator, and V1 uses it only as a classifier.

Not in scope: chat, narrative or news explanation, financial calculation, trading signals,
Verify, model-input generation, economic truth.

## 2. Architecture

```
FINCO canonical R-LIVE evidence          (read-only, exact approved canonical_id)
  → deterministic feature extraction     (Decimal arithmetic, closed-vocabulary buckets)
  → identity-blinded feature state       (no ticker, name, uid, price or premium value)
  → typed Jev request                    (2 questions, POST /v1/systemone)
  → strict response validation           (closed IDs, bounded probabilities, fail closed)
  → read-only labels                     (API route + small experimental panel)
```

Files (`app/radar_rwa/jev_intelligence/`): `contracts.py` (types, versions, disclosure),
`config.py` (env, modes), `features.py` (all arithmetic), `questions.py` (request and response
validation), `transport.py` (HTTP), `cache.py`, `telemetry.py`, `service.py` (orchestration).
Plus `app/api/v1_1/r_live_intelligence_router.py`, a small edit to
`app/radar_ui/r_live_router.py` and `app/templates/radar/r_live_detail.html`, one mount line in
`main_web.py`, and `tests/test_jev_radar_intelligence.py`.

### 2.1 Canonical inputs (audited against current main)

| Input | Source (existing, unchanged) | Used for |
|---|---|---|
| Current B1.0 premium (bps) and composite state | `app.api.v1_1.institutional.get_r_live` → `r_live_service` | current level, positions, direction |
| Freshness (`market_activity_age_seconds`, `retrieved_at`) | same | activity bucket, evaluation clock |
| 1h and 24h premium range low / high / count | `read_r_live_ranges` (read-only) | positions, shape, width, density |
| Ordered premium history points | `read_r_live_history(limit=100)` (read-only) | 1h and 24h direction |

Audited and **not available** in current R-LIVE: liquidity, depth, volume, trade counts, wallet
or flow data, executable quotes. V1 therefore has no such feature and makes no such claim
(no whale, wash-trading, organic-demand, smart-money or wallet-quality language; a test scans
the package and panel for this vocabulary).

### 2.2 Deterministic features (`JEV_RLIVE_FEATURES_V1`)

All values are closed-vocabulary strings. A missing input yields `UNAVAILABLE`, never 0, never
inferred. If the current observation is not `AVAILABLE`, or the 24h range is not available, no
Jev call is made (`CANONICAL_CURRENT_NOT_AVAILABLE`, `INSUFFICIENT_HISTORY`).

| Feature | Rule (thresholds are declared constants in `features.py`) |
|---|---|
| `premium_level` | absolute premium bps: <10 near parity, <50 moderate, <150 wide, else extreme; side from sign |
| `position_in_1h_range`, `position_in_24h_range` | below / lower third / middle third / upper third / above range, or flat range |
| `direction_1h`, `direction_24h` | sign of (current − earliest in-window point); flat if \|Δ\| < 2 bps; unavailable unless the earliest point covers ≥50% of the window and the 100-point read is not truncated |
| `short_long_agreement` | agree / disagree / flat involved, from the two directions |
| `range_shape` | 1h width ÷ 24h width: ≤0.25 compressed, ≤0.75 intermediate, else expanded |
| `range_width_24h` | 24h width bps: <5 narrow, <25 moderate, else wide |
| `observation_density_1h`, `_24h` | count buckets (1h: <3 / <12; 24h: <12 / <72) |
| `market_activity_age` | age of last pool activity: ≤5m, ≤1h, ≤6h, over 6h |

Jev is never asked to compute any of these. The tests assert that no feature value is numeric,
that identity strings and the premium never appear in the outbound request, and that the
instructions contain no calculate/compute request.

### 2.3 Jev questions (`JEV_RLIVE_QUESTIONS_V1`)

Exactly two, in one request (request body about 1.8 KB, roughly 460 input tokens by a
characters÷4 heuristic; the provider's own count is captured in `usage`, see §6):

1. `market_regime` — **Choice**: `criteria` is a mapping of `MOMENTUM`, `MEAN_REVERTING`,
   `RANGE_BOUND`, `UNRESOLVED` to descriptions.
2. `attention` — **Score**: `criteria` is the ordered list `NORMAL`, `ELEVATED`, `HIGH`.

Request contract (locked by `tests/fixtures/typesafe_systemone_contract.json` and tests): Choice
and Score both take `criteria`. `options` is not a Choice request field and `legend` is a Score
**response** field, never a request field; neither appears in the request.

Both instructions state that the state describes the premium/discount series of an on-chain
token reference versus a source-bound equity basis, that only the supplied buckets may be
judged, and that identity inference, recomputation and advice are forbidden.

Deliberately omitted: a persistence "likely to persist" Noul (no immutable outcome policy or
baseline, see §4) and a movement-quality Choice (FINCO has no wallet-flow or trade-level
evidence, so an organic-versus-abrupt distinction would not be evidence-backed).

### 2.4 Typed outputs

Response contract (strict, no defaults): Choice requires `type = choice`, a valid `choice`,
`probabilities` (keys within the criteria, each in [0,1], sum ≤ 1.001, containing the chosen
option) and `confidence`. Score requires `type = score`, `score`, `legend` (exactly
`{0: NORMAL, 1: ELEVATED, 2: HIGH}`), `probabilities` and `confidence`. A missing `type` is
invalid, not defaulted. Score is a 0-based level index and must satisfy 0 ≤ score ≤ 2; values
outside that range are rejected, not rounded into a label. Level policy (`ROUND_HALF_UP`, so a
tie goes to the higher attention level): 0.4999 → NORMAL, 0.5 → ELEVATED, 1.4999 → ELEVATED,
1.5 → HIGH, 2.0 → HIGH; the boundaries are tested.

`IntelligenceResult` (`contracts.py`): state (`AVAILABLE`, `DISABLED`, `UNAVAILABLE`,
`INVALID_RESPONSE`), reason, canonical identity, observation digest, input fingerprint, feature
and question schema versions, regime answer (choice, per-option probabilities, confidence),
attention answer (state, score, confidence), requested and resolved model and whether they
match, `evaluated_at`, provenance (evaluation clock, feature sources, authority label
`JEV_INTERPRETATION_NON_CANONICAL`), diagnostics (cache status, latency, attempts, provider
request id, usage, failure category) and the disclosure text.

### 2.5 API and UI

- `GET /api/v1.1/radar/r-live/{canonical_id}/intelligence`, unauthenticated like the other public
  R-LIVE reads, `Cache-Control: no-store`, in its own router so the reviewed six-route public
  R-LIVE contract is unchanged (an existing test still passes). No history write from GET.
- OFF and SHADOW: the route returns `DISABLED` and never evaluates. VISIBLE: it evaluates.
- UI: a small "Jev Intelligence" section with an Experimental badge on the R-LIVE detail page,
  rendered only in VISIBLE mode (the OFF and SHADOW pages contain no panel and no fetch). It shows
  regime, attention, confidence, evaluation time, resolved model and a short fingerprint, plus the
  disclosure. Canonical panels are always present; a Jev failure only changes the panel to a typed
  "unavailable" line. No recommendation vocabulary.

### 2.6 Cache, timeout, retry, limits

| Behaviour | Value |
|---|---|
| Cache key | `(economic_asset_uid, input_fingerprint, question_schema_version, requested_model, observation_digest)` |
| TTL | 30 s if last pool activity ≤5m, 60 s if ≤1h, else 120 s (clamped 30–120) |
| Coalescing | concurrent identical requests share one in-flight call |
| What is cached | only `AVAILABLE` results; failures are never replayed as answers |
| Per-attempt timeout / retries | 5 s / 2 retries (3 attempts); backoff 0.25 s then 0.5 s; total budget 12 s |
| Retried | 408, 429, 5xx (including 529), timeouts, network errors; `Retry-After` honoured |
| Not retried | 401/403 (auth), 400/404/422 (invalid request) |
| Rate limit | **process-wide** (one Python process, not host-global): 30 evaluations per minute by default (`FINCO_JEV_MAX_EVALUATIONS_PER_MINUTE`), then `JEV_RATE_LIMITED`. With N web workers the theoretical host ceiling is about N × that value until a shared limiter exists |

The fingerprint covers only coarse buckets, and different canonical evidence can share it. A
result carries the observation digest, evaluation clock and provenance of the evidence it
interprets, so the key includes `observation_digest`: the same exact observation is a cache hit,
while any different canonical evidence forces a new evaluation even if the buckets are identical.
A regression test (same fingerprint, different digest → two provider calls, each with its own
`observation_digest` and `as_of`) locks this. Evidence correctness is preferred over reuse; a
consequence is that the cache saves calls only for repeated reads of the same observation.

### 2.7 Failure modes

Every failure is a typed state; none produces fabricated intelligence and none touches
canonical data. Reasons include `JEV_INTELLIGENCE_DISABLED`, `ASSET_UID_INVALID`,
`CANONICAL_CURRENT_UNAVAILABLE`, `CANONICAL_IDENTITY_MISMATCH`, `CANONICAL_CURRENT_NOT_AVAILABLE`,
`INSUFFICIENT_HISTORY`, `HISTORY_UNAVAILABLE`, `JEV_API_KEY_NOT_CONFIGURED`, `JEV_RATE_LIMITED`,
`JEV_TRANSPORT_UNAVAILABLE` (with failure category `TIMEOUT`, `NETWORK`, `HTTP_408`, `HTTP_429`,
`HTTP_5XX`, `AUTH`, `INVALID_REQUEST`, `RETRY_BUDGET_EXHAUSTED`), and `INVALID_RESPONSE` with a
closed reason such as `JEV_UNEXPECTED_QUESTION_OUTPUT` or `CONFIDENCE_OUT_OF_BOUNDS`. No raw
provider text, key or exception is ever returned or logged.

## 3. Authority boundary

```
FINCO canonical data → deterministic features → JEV interpretation      (one direction only)
```

Nothing flows back. The evidence for each non-equivalence:

| Claim | Structural evidence | Test |
|---|---|---|
| **JEV ≠ calculation authority** | All arithmetic is in `features.py`; Jev receives only buckets, never numbers; its output is a label with probabilities and is not used in any FINCO number | features tests; "request is identity-blinded and has no arithmetic or numbers" |
| **JEV ≠ FINCO Verify** | Package never references `app.verified`, `app.persistence` or any Verify writer; no VERIFIED status can be produced; output authority is `JEV_INTERPRETATION_NON_CANONICAL` | forbidden-import scan; zero-diff on `app/verified/**` |
| **JEV ≠ canonical identity authority** | Input must be an exact approved `canonical_id` (tickers, names, case variants, prefixed forms rejected); the returned evidence's key and uid are re-checked against the reviewed policy; the outbound request carries no identity | identity tests; substitution test |
| **JEV ≠ executable-price authority** | No price, quote or premium value is sent or returned; the disclosure states it is not an executable price; no execution field exists in the outputs | request-blinding test; disclosure in every response |
| **JEV ≠ Signed Run authority** | No import of run-certificate or Model code; results live only in process memory and telemetry, never in any certificate or stored artifact | forbidden-import scan; zero-diff on `financial_engine/**`, `finco_core/**` |

Zero-diff evidence (against `origin/main`): `financial_engine/**`, `finco_core/**`,
`app/model_validation/**`, `app/verified/**`, `finco_radar/**` — no changes. Reproduce with:
`git diff origin/main --name-only -- financial_engine finco_core app/model_validation app/verified finco_radar`
(expected output: empty).

Read-path writes: a test replaces the history store's write methods and the engine's entry
point with recorders and asserts nothing is called; a second test runs the real read functions
against a real ledger and asserts the ledger file is byte-identical afterwards. (Opening a
read-only SQLite handle on a WAL database can create empty `-wal`/`-shm` sidecars, exactly as the
existing canonical range/history reads already do; ledger content never changes.)

## 4. Predictive claims

**No predictive output ships in V1.** `market_regime` and `attention` are descriptive
classification labels of the current premium series. They make no statement about a future
observation, and the UI labels them "Market regime (premium series)" and "Attention state".

| Candidate predictive output | T0 | Horizon | Outcome rule | Evaluation window | Policy version | Baseline | Calibration | Decision |
|---|---|---|---|---|---|---|---|---|
| `likely_to_persist` (Noul) | not defined | not defined | not defined | not defined | none | not defined | none | **Not shipped.** No immutable outcome policy or same-information baseline exists on the current R-LIVE architecture. |
| Movement quality (Choice) | n/a | n/a | n/a | n/a | none | n/a | none | **Not shipped.** No supporting evidence class in FINCO. |

Consequence: `PREDICTIVE_QUESTION_INCLUDED = NO`, `OUTCOME_POLICY_DEFINED = N/A`,
`BASELINE_DEFINED = N/A`. Enabling a predictive question later requires, before any outcome is
collected: exact T0, target horizon, first eligible observation, tolerance window, label rule,
an immutable policy version, and a deterministic baseline on the same information set (the
discipline PR #119 applied to its own experiment).

**Scientific status of the descriptive labels.** There is no ground truth for "regime" or
"attention", so they cannot be calibrated against outcomes as they stand. What is verified is
engineering correctness (deterministic features, closed schemas, fail-closed validation), not
that the labels are right. The recommended validation before any visible release is: run SHADOW,
sample labels, have a reviewer label the same buckets blind, and compare agreement with a
deterministic rule baseline (e.g. direction agreement plus range position). Until then the labels
are unvalidated model opinions and are presented as such.

## 5. Production characteristics

| Item | Value |
|---|---|
| Provider | TypeSafe (System One "Jev") |
| Endpoint | `POST https://api.typesafe.ai/v1/systemone` (diagnostic-only `GET /v1/models`, never on the request path) |
| Auth | `Authorization: Bearer $TYPESAFE_API_KEY`; key held in memory only, redacted in `repr`, never logged or serialized; a response echoing the key is rejected |
| Requested model | `FINCO_JEV_MODEL`, default `jev-latest`; recorded per result |
| Resolved model | taken from the provider response `model`; recorded per result; `model_match` is false when they differ. An alias is not treated as immutable |
| Timeout / retry | see §2.6 |
| Caching | see §2.6 |
| Feature flag | `FINCO_JEV_INTELLIGENCE_ENABLED` (default `0`) |
| Modes | OFF (default), SHADOW (enabled with no mode; evaluates through the operator function `evaluate_shadow`, telemetry only, not exposed), VISIBLE (`FINCO_JEV_INTELLIGENCE_MODE=VISIBLE`: API and panel). Unknown mode fails closed to OFF. Never silently promoted |
| Request fan-out | one provider request per cache miss per asset, two questions per request. Panel only on the per-asset detail page, so no landing-page fan-out. Worst case is bounded per process by the process-wide limit (30 per minute by default), so the host ceiling is about N × 30 with N workers; the TTL cache only helps for repeated reads of the same exact observation |
| Provider usage telemetry | whatever scalar `usage` fields the provider returns are recorded verbatim (closed scalar map); provider request id captured only if it matches a safe pattern |
| Local telemetry | bounded in-memory ring plus a structured log line: outcome, cache status, latency, requested and resolved model, request id, usage, failure category |
| Latency | vendor-reported 70–500 ms (secondary sources, **not measured here**). The page path also performs the existing live R-LIVE acquisition, so end-to-end latency is dominated by that, not by Jev |
| Cost | **not measured**. No provider call has been made with a real key in this work. Request size is about 460 input tokens by heuristic. `telemetry.estimate_request_cost_usd` is an explicit estimate helper using a vendor-published rate that was not verified against vendor documentation; treat any monetary figure derived from it as unsupported until real `usage` data from SHADOW exists |

Provider contract status: the vendor documentation site was unreachable from the build
environment. The first implementation used a community SDK's shape (`options`, `legend`), which
an independent review found to be wrong; V1 now follows the current System One schema
(`criteria` for both Choice and Score) and locks it with a fixture and tests. **No live provider
call has been made** (no `TYPESAFE_API_KEY` in the build environment: `LIVE_PROVIDER_SMOKE =
SKIPPED_NO_KEY`), so the contract is validated against the documented schema, not against the
live service. The first live call must be made in SHADOW; a mismatch would surface as
`INVALID_RESPONSE` or an `INVALID_REQUEST` failure (fail closed), not as wrong labels.

## 6. Reuse from PR #119 (experimental, remains experimental)

PR #119 was used as a **design reference**. Nothing was merged, imported or rebased from it.

**Reused as design (concepts):** Bearer-key handling, bounded timeout/retry/`Retry-After`,
sanitized failure categories, closed response validation, input fingerprinting, requested versus
resolved model tracking, usage and latency telemetry, feature allowlisting with a hard assertion,
no-secret guarantees, and strict authority separation (Jev downstream only).

**Refactored (new code, same shape):** the HTTP transport is a new file adapted from
`typesafe_transport.py`: the closed failure-category set, `Retry-After` parsing, retryable-status
rule, status-to-category map and the secret-echo guard are carried over near-verbatim; the client
protocol gained `GET`, request-id capture, a 529 retry and tighter defaults (5 s timeout, 2
retries, 12 s budget versus 10 s, 3 retries, 30 s). The typed-result and validation pattern from
`interpretation.py` / `jev.py` was reworked for two questions (Choice and Score) instead of one Noul.

**Deliberately rejected:** the RWA Reflex state and its old canonical-data assumptions
(execution impact, effective gap, basis z-score, structural premium, liquidity and depth
features), the event detector and T+60/T+65 outcome policy, the append-only shadow ledger and
its SQLite writes, the `likely_transient` Noul, and the experiment's evaluation harness and
workflow. Current R-LIVE does not provide those inputs, and V1 ships no predictive claim.

## 7. Test and acceptance evidence

`tests/test_jev_radar_intelligence.py`: 113 tests covering deterministic features (including
missing-is-unavailable and fail-closed on stale or unavailable canonical input), exact-identity
and substitution rejection, transport (redaction, timeout, 408, 429 with `Retry-After`, 5xx,
auth and malformed no-retry, bounded retries, malformed and secret-echo responses, safe request
id), response validation (unexpected IDs, out-of-bounds probabilities, legend mismatch, model
mismatch surfaced), caching (hit, changed bucket, expiry, separate model, failures not cached,
concurrent coalescing), modes and the flag (OFF makes zero calls, SHADOW default, invalid mode),
authority (forbidden-import scan, no writes, no engine call, byte-identical real ledger, canonical
data unchanged on Jev failure), API (OFF/SHADOW/VISIBLE, disclosure, identity) and UI (no panel
when OFF/SHADOW, Experimental badge, canonical panels retained, no recommendation vocabulary).

Focused acceptance also run: R-LIVE current, ranges/history, landing, collector and public API
tests (all pass); public repository safety scan (pass); `compileall` (clean). The one Radar
browser test in that set that errors, `test_radar_n04_browser`, also errors on the base commit in
this sandbox. Full-suite result: see the PR description and the final report.

## 8. Known limitations and risks

1. Labels are unvalidated (no ground truth); see §4.
2. Provider contract aligned to the documented System One schema but not validated live; verify with the first SHADOW call.
3. Latency and cost are unmeasured for this workload; no live call has been made.
4. The SHADOW trigger is a callable, not wired to a scheduler.
5. Coarse buckets mean the model sees little information; expect many `UNRESOLVED` and `NORMAL`
   answers. That is honest but limits usefulness.
6. The panel drives one live R-LIVE acquisition plus one cached provider call per view; a public
   unauthenticated route is protected only by the same-observation cache and a process-wide limit
   (about N × the limit across N workers).
7. `market_regime` names could be misread as forecasts; mitigated by labelling and disclosure, not
   eliminated.

## 9. How to review quickly

1. Read §3 and run the zero-diff command.
2. Open `features.py` (all arithmetic) and `questions.py` (the only text sent to Jev).
3. Run `pytest tests/test_jev_radar_intelligence.py`.
4. Set `FINCO_JEV_INTELLIGENCE_ENABLED=1` and `FINCO_JEV_INTELLIGENCE_MODE=VISIBLE` with a
   throwaway key in staging only, and inspect one result and the telemetry snapshot.

## 10. Author assessment against the six review questions

1. **Is JEV useful?** Unproven. The design is cheap and low risk, but the input is a single
   premium series reduced to buckets, so the added information over a deterministic rule is likely
   small. Usefulness needs SHADOW data and a blind comparison against a rule baseline.
2. **Correctly scoped?** Yes for V1: descriptive labels only, no predictive claim, no data FINCO
   does not have.
3. **Contaminates a canonical authority?** No, on the evidence in §3: zero diffs in protected
   paths, no imports of engine, Verify or persistence code, no writes, no identity in the request.
4. **Scientifically defensible?** The engineering is; the labels are not yet validated (§4).
   Nothing predictive is claimed.
5. **Production characteristics acceptable?** Bounded and fail-closed, default OFF; but latency
   and cost are unmeasured and the wire format is unverified against vendor docs (§5).
6. **Recommendation:** **keep experimental.** Merge only as default-OFF code if desired, run
   SHADOW to measure latency, usage, agreement with a rule baseline and label stability, and
   decide on VISIBLE afterwards. Remove it if SHADOW shows the labels add nothing over the
   deterministic buckets.
