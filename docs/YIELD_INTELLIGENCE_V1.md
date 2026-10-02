# FINCO Yield — Intelligence V1

Status: draft implementation. Read-only. Yield execution remains OFF
(`FINCO_YIELD_EXECUTION_ENABLED=0`). No forecast, no interpolation, no invented
yield, no recommendation vocabulary.

```
source observation ──▶ canonical history ──▶ intelligence derivation
                       (YieldHistoryStore)     (finco_yield/intelligence.py)
```

Intelligence is a **derived read model**. It owns no source truth, persists
nothing, and adds no collector, history store or freshness classifier. It reads
history **only** through `YieldHistoryStore.latest / prior / window` and
classifies freshness **only** through `freshness.evaluate_freshness`.

## Time anchor

One evaluation takes one explicit, timezone-aware `as_of` (naive / non-datetime
→ `IntelligenceError`, fail closed; normalised to UTC). The module never reads
the clock. `as_of` is used for **freshness only**; comparison horizons are
anchored on the latest observation's own `observed_at`, so the numbers are
reproducible regardless of when they are computed.

## Exact baseline rule (24h and 7d)

For horizon `H` ∈ {24h, 7d}:

```
cutoff(H) = latest.observed_at − H
baseline  = the single most recent canonical observation with observed_at ≤ cutoff(H)
```

Implemented as `YieldHistoryStore.prior(uid, before = cutoff + 1 µs, limit = 1)`
(`prior` is strictly-before; 1 µs is the timestamp resolution, so the rule is
exactly `≤ cutoff`). An observation **after** the cutoff is never a baseline,
however close. Values are never interpolated. No baseline ⇒ the horizon
comparison is `NO_BASELINE` / coverage `INSUFFICIENT_HISTORY` — never a zero
delta. The result exposes `baseline.observed_at` and
`baseline_offset_seconds = cutoff − baseline.observed_at` (≥ 0) so a stale
baseline is visible; no threshold is applied.

The 24h / 7d window is `YieldHistoryStore.window(uid, since=cutoff, until=latest.observed_at)`
(both ends inclusive; it contains the latest observation and a baseline that
falls exactly on the cutoff).

## Formulas (Decimal only; APY values are fractions, `0.04 == 4 %`)

```
apy_delta_fraction = latest.apy_total − baseline.apy_total
apy_delta_bps      = apy_delta_fraction × 10 000          # 4.00 % → 4.25 % = +25 bps
tvl_delta_usd      = latest.tvl_usd − baseline.tvl_usd
tvl_delta_fraction = latest.tvl_usd / baseline.tvl_usd − 1   # only if baseline > 0
```

Window statistics (APY and TVL independently): `observation_count` (rows in the
window), `available_count` (rows with a numeric value), `minimum`, `maximum`,
`range = maximum − minimum` over the real numeric values only. No numeric value ⇒
`None` for all three.

## Missing-data semantics

* `None` is UNAVAILABLE, never zero; a factual `0` is valid data.
* A delta is unavailable (with a typed state) if there is no baseline
  (`NO_BASELINE`), the latest value is missing (`LATEST_VALUE_MISSING`) or the
  baseline value is missing (`BASELINE_VALUE_MISSING`). The baseline is not
  replaced by an older observation that happens to have a value.
* A factual-zero TVL baseline keeps the absolute delta; the percentage is
  `UNDEFINED_ZERO_BASELINE`.
* Non-numeric / non-finite stored values are treated as missing.
* No history for the UID ⇒ status `INSUFFICIENT_HISTORY` with no numbers.
  Unconfigured history ⇒ `HISTORY_NOT_CONFIGURED`; unreadable/corrupt history ⇒
  `HISTORY_UNAVAILABLE` (typed, never zeros).

## Coverage (per horizon)

`AVAILABLE` · `INSUFFICIENT_HISTORY` (no baseline) · `NO_NUMERIC_APY` ·
`NO_NUMERIC_TVL` (precedence in that order).

## Freshness

`evaluate_freshness` on the latest observation's reconstructed `SourceReference`
at `as_of` — `CURRENT` / `STALE` (plus the existing `INVALID` /
`FUTURE_TIMESTAMP`; `UNKNOWN` if the row has no recognised source authority). A
source-observed row may be STALE. The bundled reference fixture is not history
and is never historical live evidence.

## Direction labels

`UP` / `DOWN` / `UNCHANGED` / `UNAVAILABLE`, derived only from the sign of a
factual numeric delta. Presentation only.

## Surfaces

* **Detail page** (`/yield/<uid>`): compact “Yield Intelligence” table — current
  APY / TVL, 24h Δ, 7d Δ, APY and TVL ranges, observation counts, history
  coverage, freshness. Unavailable ⇒ `—`.
* **JSON** `GET /yield/<uid>/intelligence.json` (schema `YIELD_INTELLIGENCE_V1`):
  `uid`, `as_of`, `history_status`, `intelligence.{latest, freshness, horizons}`;
  deterministic (`canonical_json`, Decimals as exact strings, UTC microsecond
  timestamps). Exact canonical UID only; unknown UID → 404 (no ticker/contract
  lookup). No provider secrets.
* **Entitlement**: derived from history, so it follows the **existing**
  `YieldResource.HISTORY` decision (same as `history.json`); no new threshold or
  token policy. When that decision denies, the JSON returns the existing typed
  403 and the detail page shows a neutral restricted note with no numbers.

## Performance

History reads are O(file). One evaluation shares **one** file read
(`_ReadOnceHistory` overrides only `read_all` of the canonical store; `latest`,
`prior`, `window` are the canonical implementations). No cache, index or second
store.

## Alerts boundary

Alerts remain authoritative and unchanged. `build_intelligence()` returns typed
metrics a future alert rule can reuse without re-implementing history logic.
No notification or alert evaluation is added.

## Not in V1

Charts, forecasting, interpolation, Explore summaries, persistence of derived
results, alert rules.
