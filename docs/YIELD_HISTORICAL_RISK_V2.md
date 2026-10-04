# Yield Historical Risk & Persistence V2

`finco_yield/risk.py` — `YIELD_HISTORICAL_RISK_V2`

A pure derived read model over the canonical `YieldHistoryStore`. It extends
existing Yield intelligence with deterministic historical APY distribution,
persistence, TVL and reward context. It performs no acquisition, writes,
provider/network calls, forecasting, composite scoring or trading
recommendations.

## Canonical authorities

- Observation history: `YieldHistoryStore`; V2 is read-only.
- Row values: the existing canonical row-field semantics are reused, including
  top-level fields and safe `payload` mapping access.
- Freshness: `evaluate_freshness`; V2 does not create a second freshness
  classifier.
- APY sigma: the existing `build_intelligence` authority only. Supported V2
  windows map 1:1 to existing horizons: 24h → 24h, 7d → 7d, 30d → 30d.
  Unsupported custom windows expose no canonical sigma. No second standard
  deviation is computed.
- V1 APY delta mathematics and current Treasury authority are untouched.
  V2 fabricates no historical Treasury series.

## Current evidence versus historical window

Historical statistics use observations inside `[as_of - window, as_of]`.
Current evidence is different: `current_apy`, `current_tvl`, reward context
and `freshness` are bound to the **actual latest canonical observation**.

Therefore an older APY- or TVL-bearing row is never silently promoted to
current. If the latest canonical row lacks a usable `apy_total`:

- `current_apy = null`;
- `apy_distribution.percentile = null`;
- `current_vs_peak_delta_bps = null`;
- historical distribution facts may remain available when eligible; and
- the top-level context is not fully AVAILABLE.

The newest in-window usable APY/TVL may also be exposed explicitly as
`last_observed_apy` / `last_observed_apy_at` and
`last_observed_tvl` / `last_observed_tvl_at`. These are deliberately not
current semantics.

A future-dated latest canonical row is excluded from historical distribution
statistics but still drives canonical freshness, so `FUTURE_TIMESTAMP` is
preserved in the V2 output rather than being hidden by the last in-window row.

## Freshness contract

The exact canonical freshness string is preserved:

- `CURRENT` → eligible for normal AVAILABLE behavior;
- `STALE` → top-level `STALE`;
- `UNKNOWN`, `INVALID`, `FUTURE_TIMESTAMP` → fail closed as
  `PARTIAL`, with a typed `LATEST_FRESHNESS_<STATE>` reason.

Invalid or future evidence is never described as merely old.

## Distribution eligibility

Within the historical window, an APY point is usable when it has a parseable
timestamp and a finite numeric `apy_total`.

- Count gate: at least `MIN_USABLE_OBSERVATIONS = 10` usable APY points.
  This gate controls publication of min/q25/median/q75/max.
- Span gate: at least `MIN_HISTORY_SPAN_SECONDS = 3600` between earliest and
  latest usable APY points.
- Current percentile requires **both** count + span gates and a usable APY on
  the actual latest canonical row.

Thus a sample that passes span but fails count remains PARTIAL with
distribution statistics withheld. A count-qualified but short-span sample may
publish historical distribution facts while withholding the current
percentile. The implementation does not weaken the count gate to make PARTIAL
look more complete.

Percentile uses the deterministic midrank policy:

`(# below + 0.5 × # equal) / count`

Quartiles use deterministic nearest-rank
`index = ceil(p × n) - 1`, with no interpolation.

## APY compression

`trailing_peak_apy` is a historical maximum over usable in-window APY
observations. `current_vs_peak_delta_bps` is computed only when the actual
latest canonical row has a usable current APY. A prior APY is never used as a
substitute current value.

## TVL context

`current_tvl` is taken only from the actual latest canonical row. If that row
has no TVL, `current_tvl = null`; an older TVL may remain available only as
explicit last-observed evidence with its timestamp.

Trailing min/max, observation count and TVL change/drawdown facts remain
historical context. TVL movement is liquidity/participation context, never
investor loss.

## Reward dependency

Reward fields come only from the actual latest canonical row using safe
canonical row-field access. `reward_apy_share = apy_rewards / apy_total` is
published only when both components exist and total APY is non-zero.
Components are never inferred. A malformed non-dict payload fails soft:
reward context becomes unavailable while valid historical APY context remains
intact.

## Persistence

Persistence facts are explicitly `OBSERVATION_BASED`, never time-weighted or
predictive. They describe fractions of usable observations around/above the
window median and do not imply future persistence.

## Input and failure rules

`window` must be a positive `timedelta`. Zero or negative windows are
rejected. Missing values remain null, never zero. Sections fail independently
where possible.

There is no Yield Sharpe, risk-adjusted APY score, rating, grade, forecast,
recommendation, provider acquisition, execution/signing/custody path, or
historical Treasury fabrication in V2.
