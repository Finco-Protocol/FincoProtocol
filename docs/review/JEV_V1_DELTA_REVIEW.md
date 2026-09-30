# JEV Radar Intelligence V1 — delta review dossier

Internal review artifact for PR #146. Status: **experimental, pre-release, draft, default OFF**.
Public Product Truth (README, ROADMAP, `OPUS_V1_REVIEW/**`, /docs, /roadmap, /verify,
/protocol/finco) is deliberately not touched and nothing here claims JEV is shipped.

A reviewer should be able to judge the feature from this file: usefulness, scope, authority
contamination, scientific defensibility, production characteristics, and ship / keep
experimental / remove (§16).

## A. Product purpose

Attach small, typed, probabilistic **interpretation labels** to canonical R-LIVE evidence: which
regime the premium/discount series looks like, and how much analyst attention the current state
deserves. Jev (TypeSafe System One) is used only as a fast classifier of structured state.

Not in scope: chat, narrative or news, calculation, trading signals, Verify, Model-input
generation, economic truth, prediction.

## B. Architecture

```
canonical FINCO evidence (R-LIVE, exact approved canonical_id, read-only)
  → deterministic feature extraction   (Decimal arithmetic, closed-vocabulary buckets)
  → identity-blinded feature state     (only the bucket strings leave FINCO)
  → typed Jev request                  (2 questions, POST /v1/systemone)
  → strict response validation         (closed IDs, bounded values; fail closed)
  → typed interpretation               (API route + small experimental panel, VISIBLE mode only)
```

Flow is one-directional. Package `app/radar_rwa/jev_intelligence/`: `contracts.py` (types,
versions, disclosure), `config.py`, `features.py` (all arithmetic and the feature contract),
`questions.py` (request text and response validation), `transport.py`, `cache.py`,
`telemetry.py`, `shadow.py`, `service.py`. Outside the package: the separate route
`app/api/v1_1/r_live_intelligence_router.py`, a five-line enqueue-only hook in
`app/api/v1_1/r_live_public_router.py` (`get_r_live`), the panel in
`app/templates/radar/r_live_detail.html` and its context flag in `app/radar_ui/r_live_router.py`,
one mount line in `main_web.py`, and the operator tool `tools/jev_live_smoke.py`.

Canonical inputs (audited against current main; all existing, read-only, unchanged): the current
B1.0 premium and state via `get_r_live`; freshness evidence; the 1h/24h premium range summary
(`read_r_live_ranges`); ordered history points (`read_r_live_history`, limit 100). **Not available
in current R-LIVE and therefore not used or claimed:** liquidity, depth, volume, trade counts,
wallet or flow data, executable quotes.

## C. Exact outbound features (`JEV_RLIVE_FEATURES_V1`)

The request `state` is exactly `{"features": {...}}`: these eleven closed-vocabulary buckets and
nothing else (no schema version, fingerprint, identity, price, premium value, timestamp, user,
workspace or entitlement). The machine-readable version is `features.FEATURE_CONTRACT`; a test
asserts it matches the emitted keys, that no raw value or identity is sent, that every emitted
bucket is inside the documented vocabulary, and that each feature appears below.

All values are computed in Python `Decimal`. **Missing data**: a missing input yields
`UNAVAILABLE` for that feature (never 0, never inferred). If the current observation is not
`AVAILABLE`, or the 24h range is not available, no call is made at all.

| Feature | Canonical source | Deterministic transformation and buckets | Missing | Raw value sent | Identity exposed | Supports |
|---|---|---|---|---|---|---|
| `premium_level` | current B1.0 premium | \|bps\| <10 near parity; <50 moderate; <150 wide; else extreme; side from sign (7 values) | call not made | no | no | attention |
| `position_in_1h_range` | premium + 1h range | below / lower third / middle third / upper third / above / flat range | UNAVAILABLE | no | no | regime, attention |
| `position_in_24h_range` | premium + 24h range | same buckets over the 24h range | call not made | no | no | regime, attention |
| `direction_1h` | premium + history points | sign of (current − earliest in-window point); flat if \|Δ\|<2 bps; needs ≥50% window coverage and an untruncated read | UNAVAILABLE | no | no | regime |
| `direction_24h` | premium + history points | same rule over 24h | UNAVAILABLE | no | no | regime |
| `short_long_agreement` | the two directions | agree / disagree / flat involved | UNAVAILABLE | no | no | regime |
| `range_shape` | 1h and 24h ranges | 1h width ÷ 24h width: ≤0.25 compressed, ≤0.75 intermediate, else expanded; flat range | UNAVAILABLE | no | no | regime, attention |
| `range_width_24h` | 24h range | width bps: <5 narrow, <25 moderate, else wide | call not made | no | no | regime, attention |
| `observation_density_1h` | 1h range count | <3 sparse, <12 moderate, else dense | UNAVAILABLE | no | no | attention |
| `observation_density_24h` | 24h range count | <12 sparse, <72 moderate, else dense | UNAVAILABLE | no | no | attention |
| `market_activity_age` | freshness (last pool activity age) | ≤5 min, ≤1 h, ≤6 h, over 6 h | UNAVAILABLE | no | no | attention |

Jev is never asked to compute any of these, and the question text forbids recomputation.
Minimisation review: no ticker, company name, token contract, wallet, user, workspace,
entitlement or private FINCO data is sent, and none is required by either question. The local
input fingerprint and observation digest stay inside FINCO.

## D. Exact questions (`JEV_RLIVE_QUESTIONS_V1`, frozen)

1. `market_regime` — Choice, `criteria` = `MOMENTUM`, `MEAN_REVERTING`, `RANGE_BOUND`,
   `UNRESOLVED` (each with a short descriptive sentence).
2. `attention` — Score, `criteria` = ordered list `NORMAL`, `ELEVATED`, `HIGH`.

Both instructions say the state describes the premium/discount series of an on-chain token
reference versus a source-bound equity basis, that only the supplied buckets may be judged, that
`UNAVAILABLE` means unknown, and that identity inference, recomputation and advice are forbidden.
A test scans the request for forecast, recommendation, whale, smart-money, manipulation and
wash-trading language.

Evidence review: `market_regime` is supported by direction, position, agreement and range-shape
features; `attention` by premium level, position, shape, width, density and activity age (each
question has at least three supporting canonical features). Both are kept. **Deliberately not
included:** a persistence Noul (see §M) and a movement-quality Choice (FINCO has no wallet-flow or
trade-level evidence). Nothing was added to pad the set.

## E. Provider contract

- Endpoint `POST https://api.typesafe.ai/v1/systemone`; `Authorization: Bearer $TYPESAFE_API_KEY`;
  diagnostic-only `GET /v1/models` (never on the request path).
- **Request**: `{model, state, questions}`. Choice and Score both use `criteria` (Choice: mapping
  label → description; Score: ordered list). `options` and `legend` are never sent (`legend` is a
  Score response field). Locked by `tests/fixtures/typesafe_systemone_contract.json`, a strict
  validator, and tests that fail on the old shapes.
- **Response** (strict, no defaults): Choice needs `type = choice`, a valid `choice`,
  `probabilities` (keys within the criteria, each in [0,1], sum ≤ 1.001, including the chosen
  option) and `confidence`. Score needs `type = score`, `score`, `legend` exactly
  `{0: NORMAL, 1: ELEVATED, 2: HIGH}`, `probabilities` and `confidence`. Only the two expected
  answer IDs are accepted. The resolved model string must match a conservative identifier pattern.
- **Score policy**: a 0-based level index; must satisfy 0 ≤ score ≤ 2 (out of range is rejected,
  not rounded). Level = nearest index with `ROUND_HALF_UP` (a tie goes to the higher attention
  level): 0.4999 → NORMAL, 0.5 → ELEVATED, 1.4999 → ELEVATED, 1.5 → HIGH. Boundaries are tested.
- Transport: 5 s per attempt, 2 retries (3 attempts), backoff 0.25 s then 0.5 s, 12 s total
  budget; retry 408/429/5xx (incl. 529) and network errors, honour `Retry-After`; no retry on
  401/403/400/404/422; responses declaring more than 256 KB are refused; a response echoing the
  key is rejected.

## F. Failure behaviour

Every failure is a typed state and none fabricates intelligence or touches canonical data:
`DISABLED`, `UNAVAILABLE` and `INVALID_RESPONSE` with closed reasons (`ASSET_UID_INVALID`,
`CANONICAL_CURRENT_UNAVAILABLE`, `CANONICAL_IDENTITY_MISMATCH`, `CANONICAL_CURRENT_NOT_AVAILABLE`,
`INSUFFICIENT_HISTORY`, `HISTORY_UNAVAILABLE`, `JEV_API_KEY_NOT_CONFIGURED`, `JEV_RATE_LIMITED`,
`JEV_TRANSPORT_UNAVAILABLE` with failure category `TIMEOUT`, `NETWORK`, `HTTP_408`, `HTTP_429`,
`HTTP_5XX`, `AUTH`, `INVALID_REQUEST`, `RETRY_BUDGET_EXHAUSTED`, and response-validation reasons).
No raw provider text, key or exception is returned or logged.

**Isolation** (tested at API level): a TypeSafe outage makes JEV unavailable and nothing else. The
canonical R-LIVE response is byte-identical with and without a failing, timing-out, unauthorised
or hanging provider; the R-LIVE landing and detail pages stay up; startup and import never
initialise the provider (construction is lazy and patched to fail in the test); a missing key is
`JEV_API_KEY_NOT_CONFIGURED`, not a crash.

**User-facing states** (VISIBLE panel): calm muted text, never a red error and never a raw code:
provider unavailable or timeout → "Interpretation temporarily unavailable."; rate limited →
"Interpretation paused to limit provider calls."; invalid provider response or anything unknown →
"Interpretation unavailable."; stale or unavailable canonical evidence → "Canonical evidence is
stale or unavailable, so no interpretation is offered."; too little history → "Not enough
canonical history for an interpretation yet."; not configured → "Interpretation is not
configured." The reason code is only a bounded data attribute.

## G. Cache, rate limit, cost and call control

| Item | Behaviour |
|---|---|
| Cache key | `(economic_asset_uid, input_fingerprint, question_schema_version, requested_model, observation_digest)`; a tuple, so delimiter-shifted fields cannot collide |
| Why the digest | different canonical evidence can share coarse buckets; binding to the exact observation prevents a hit returning an older observation's provenance. Locked by a same-bucket regression that fails without the fix |
| TTL | 30 s if last pool activity ≤5 min, 60 s if ≤1 h, else 120 s |
| Coalescing | concurrent identical requests share one in-flight call (tested with 5 and 8 concurrent readers) |
| Cached | only `AVAILABLE` results; failures are never replayed |
| Rate limit | **process-wide** (one process, not host-global), 30 evaluations/minute by default; then `JEV_RATE_LIMITED`. With N workers the theoretical host ceiling is about N × the limit. No shared limiter is built |
| Reloads and repeats | 12 page reloads plus 12 API reads of the same evidence produce one provider call; new evidence produces exactly one more |
| Fan-out | one provider request per cache miss per asset, two questions each (request body about 1.8 KB, roughly 460 tokens by a characters÷4 heuristic; the provider's own count is captured when supplied). The panel exists only on the per-asset detail page, so there is no landing-page fan-out |
| Cost | **not measured; no live call has been made.** No monetary figure is claimed. Provider `usage` fields are recorded verbatim (bounded scalars) so SHADOW will produce evidence. `telemetry.estimate_request_cost_usd` is an explicitly labelled estimate from an unverified published rate |

## H. OFF / SHADOW / VISIBLE

| Mode | How selected | Behaviour |
|---|---|---|
| OFF (default) | `FINCO_JEV_INTELLIGENCE_ENABLED` unset or `0`; unknown mode also fails closed here | zero provider calls, zero extra canonical reads, no panel, no fetch, canonical behaviour unchanged |
| SHADOW | enabled with no mode, or `FINCO_JEV_INTELLIGENCE_MODE=SHADOW` | the hook in the canonical single-asset R-LIVE read enqueues the **observation just served** (no second RPC) to a lazily started, bounded single worker (queue of 8; overflow is dropped, never blocks). Results go to telemetry and a bounded in-memory log of sanitized summaries marked `SHADOW_NOT_PUBLIC`. The public intelligence route returns `DISABLED` and never evaluates; no panel is rendered; never promoted |
| VISIBLE | `FINCO_JEV_INTELLIGENCE_MODE=VISIBLE` (explicit only) | the intelligence route evaluates on request (cache and limit apply); the panel renders. No shadow enqueue |

Configuration surface (all optional; safe defaults): `FINCO_JEV_INTELLIGENCE_ENABLED` (default `0`),
`FINCO_JEV_INTELLIGENCE_MODE` (default SHADOW when enabled), `TYPESAFE_API_KEY` (read only when a
call is needed; never logged), `FINCO_JEV_MODEL` (default `jev-latest`),
`FINCO_JEV_MAX_EVALUATIONS_PER_MINUTE` (default 30, per process). Requested and resolved models
are both recorded; `model_match` is false when they differ, because an alias is not immutable.

Telemetry (bounded, in-memory plus a structured log line, never a second data store): request
count, outcome, cache hit/miss, latency, requested and resolved model, provider request id (only
if it matches a safe pattern), provider usage scalars, failure category. Never the key, the
Authorization header, request or response bodies, or session data.

Public surfaces: `GET /api/v1.1/radar/r-live/{canonical_id}/intelligence` (own router, `no-store`;
the reviewed six-route public R-LIVE contract is unchanged) and the R-LIVE detail panel.

## I. Security and privacy boundary

Sent to Jev: eleven closed-vocabulary buckets. Never sent: identity, ticker, name, contract,
wallet, user, workspace, entitlement, any number, timestamp or private data (a test scans the
outbound request). Exact `canonical_id` only, with the returned evidence's key and uid re-checked;
tickers, names, case variants, prefixed or padded forms are rejected, and hostile identifiers
(traversal, script text, null bytes, 5,000 characters, SQL text) are typed rejections that are
truncated and never reflected as markup. Adversarial provider output is tested: injected extra
keys and text are ignored and never exposed; HTML in model, choice or legend fails validation;
NaN, ±Infinity, out-of-range scores, malformed or huge probability objects, over-size responses
and secret echo all fail closed; usage metadata is capped (16 keys, safe names, short values).
The panel writes every provider value with `textContent` only (a browser test proves an
`<img onerror>` payload stays inert text). Result data lives only in process memory.

## J. What was reused from PR #119 (design reference only)

Concepts: Bearer-key handling, bounded timeout/retry/`Retry-After`, sanitized failure categories,
closed response validation, input fingerprinting, requested-versus-resolved model tracking,
usage/latency telemetry, feature allowlisting with a hard assertion, no-secret guarantees, and
strict authority separation. Code: the HTTP transport is a new file adapted from
`typesafe_transport.py`; the failure-category set, `Retry-After` parsing, retryable-status rule,
status-to-category map and secret-echo guard are carried over near-verbatim, with a `GET` path,
request-id capture, 529 retry, size guard and tighter defaults added. Nothing was merged,
imported or rebased from that branch; #119 remains experimental and undispositioned.

## K. What was deliberately not reused

The RWA Reflex state and its old canonical-data assumptions (execution impact, effective gap,
basis z-score, structural premium, liquidity and depth features), the event detector and
T+60/T+65 outcome policy, the append-only shadow ledger and its SQLite writes, the
`likely_transient` Noul, and the experiment's evaluation harness and workflow. Current R-LIVE does
not provide those inputs and V1 ships no predictive claim.

## L. What remains experimental

All of it: the labels are unvalidated (no ground truth for "regime" or "attention"), the provider
contract is unvalidated against the live service, latency and cost are unmeasured, and there is no
scheduler for SHADOW beyond the canonical-read hook. The panel is labelled Experimental and never
uses prediction, forecast, signal, recommendation or verified language.

## M. Known limitations

1. **Predictive claims: none ship.** A persistence Noul has no T0, horizon, outcome rule,
   evaluation window, policy version, deterministic baseline or calibration on the current R-LIVE
   architecture, so it is `NOT_SHIPPED`. Enabling it needs, before any outcome is collected: exact
   T0, target horizon, first eligible observation, tolerance window, label rule, an immutable
   policy version and a same-information baseline.
2. Descriptive labels cannot be calibrated as they stand. Suggested validation: run SHADOW, have a
   reviewer label the same buckets blind, and compare with a deterministic rule baseline.
3. The information Jev sees is small (eleven buckets); expect many `UNRESOLVED` and `NORMAL`
   answers. Honest, but it limits usefulness.
4. SHADOW evaluates only observations served by the single-asset canonical read; the landing-page
   batch stream is not hooked (it would fan out to every approved asset).
5. The limiter and cache are process-local.
6. Opening a read-only SQLite handle on a WAL ledger can create empty `-wal`/`-shm` sidecars, as
   the existing canonical reads already do; ledger content never changes.
7. A public unauthenticated route relies on the same-observation cache and the process-wide limit
   for spend control.

## N. Live provider validation status

`LIVE_PROVIDER_SMOKE = SKIPPED_NO_KEY`. No `TYPESAFE_API_KEY` exists in the build environment, so
no real call was made and nothing is claimed about live behaviour. The request contract follows
the documented System One schema and is locked by a fixture; it is validated against that schema,
not against the live service. `tools/jev_live_smoke.py` is the bounded operator check (at most one
model-discovery request and one synthetic evaluation; prints only the closed summary; never the
key, headers or payloads; not part of CI). Run it once in SHADOW, then review the printed
resolved model, latency and usage before any VISIBLE use.

## O. Authority statements

- **JEV ≠ FINCO calculation authority**: every number is computed in `features.py`; Jev receives
  only buckets; nothing it returns feeds a FINCO number.
- **JEV ≠ R-LIVE canonical authority**: read-only consumer; the canonical response is identical
  with JEV off, failing or hanging (tested); no history, price or state write.
- **JEV ≠ FINCO Verify**: no `app.verified` or persistence import; no VERIFIED status can be
  produced; output authority is `JEV_INTERPRETATION_NON_CANONICAL`.
- **JEV ≠ Signed Run**: no run-certificate or Model code; results are never part of any
  certificate or stored artifact.
- **JEV ≠ identity authority**: exact reviewed `canonical_id` only, re-verified against the
  returned evidence; the request carries no identity.
- **JEV ≠ executable-price authority**: no price or premium value is sent or returned; the
  disclosure says it is not an executable price.
- **JEV ≠ investment recommendation**: no BUY/SELL/LONG/SHORT, target, outperformance or advice
  vocabulary in the package, request or panel (scanned by tests).

Zero-diff evidence against `origin/main` for `financial_engine/**`, `finco_core/**`,
`app/model_validation/**`, `app/verified/**` and `finco_radar/**`:
`git diff origin/main --name-only -- financial_engine finco_core app/model_validation app/verified finco_radar`
(expected output: empty). A forbidden-import scan covers the whole package and the smoke tool.

## P. Test and acceptance evidence

`tests/test_jev_radar_intelligence.py` (core: features, identity, transport, contract, cache,
modes, authority, API, UI, real read-only ledger), `tests/test_jev_shadow_universe_security.py`
(SHADOW runtime and isolation, the **current approved R-LIVE universe** built from repository
authority through the real `format_r_live_result` — every approved asset yields a valid blinded
request, stale/unavailable evidence fails closed, no asset substitution, no ticker lookup —
feature contract, adversarial security, call control, configuration, smoke tool, UI safety,
telemetry) and `tests/test_jev_panel_browser.py` (desktop 1280 and mobile 390: Experimental label,
canonical data retained, calm failure states, no overflow, inert hostile strings). No universe
count is hard-coded. Final counts and full-suite and exact-head CI results are in the PR
description and final report.

## Q. Author assessment against the six review questions

1. **Is JEV useful?** Unproven. Cheap and low risk, but the input is one premium series reduced to
   buckets, so the gain over a deterministic rule may be small. Usefulness needs SHADOW data and a
   blind comparison against a rule baseline.
2. **Correctly scoped?** Yes: descriptive labels only, no predictive claim, no data FINCO lacks.
3. **Contaminates a canonical authority?** No on the evidence in §O: zero diffs in protected paths,
   no engine/Verify/persistence imports, no writes, no identity sent, canonical responses unchanged
   under JEV failure.
4. **Scientifically defensible?** The engineering is; the labels are not yet validated (§M).
   Nothing predictive is claimed.
5. **Production characteristics acceptable?** Bounded, fail-closed, default OFF, provider failure
   isolated. Latency, cost and live contract behaviour are unmeasured (§G, §N).
6. **Recommendation: keep experimental.** Run SHADOW to measure latency, usage, label stability and
   agreement with a rule baseline, then decide on VISIBLE. Remove it if the labels add nothing
   over the deterministic buckets.
