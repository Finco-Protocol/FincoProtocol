# Yield Historical Risk & Persistence V2

`finco_yield/risk.py` — `YIELD_HISTORICAL_RISK_V2`

A PURE DERIVED READ MODEL over the canonical `YieldHistoryStore`.  It extends
the existing Yield intelligence (current APY, historical deltas, sigma,
movers, Treasury spread) with deterministic historical distribution,
persistence and TVL/reward context.  No acquisition, no writes, no provider
calls, no new store, no forecasting.

## Source authority

- Canonical observation history: `YieldHistoryStore.window` (append-only JSONL,
  `YIELD_OBSERVATION_V1` records).  V2 reads only; it never writes, backfills
  or re-timestamps.
- APY sigma: composed from the EXISTING canonical intelligence authority
  (`build_intelligence(...).horizon("30d").apy_sigma`,
  source `FINCO_HISTORICAL`).  V2 does NOT implement a second standard
  deviation.
- Freshness: the existing canonical classifier (`evaluate_freshness` over the
  row's source reference).  No second classifier.
- Treasury: untouched.  The CURRENT spread remains the existing canonical
  metric; V2 never reconstructs historical Treasury values and never applies
  the current Treasury yield to historical Yield observations.

## Eligibility policy

Within the window (default 30 days), an APY point is usable when the
observation carries a parseable timestamp and a finite numeric `apy_total`.
Two gates must BOTH be met before a percentile is published:

- `MIN_USABLE_OBSERVATIONS = 10` usable points (same bar as the canonical
  sigma), and
- `MIN_HISTORY_SPAN_SECONDS = 3600` between the earliest and latest usable
  point (a burst collected over a few minutes is not history).

Typed states: both gates met and the latest observation CURRENT → `AVAILABLE`;
both met but the latest observation is STALE/INVALID/FUTURE → `STALE`;
exactly one gate met → `PARTIAL` (APY context/compression published;
quartiles and percentile both require the count gate, so on PARTIAL they
stay withheld — a sub-threshold sample must not look like a distribution);
neither → `INSUFFICIENT_HISTORY`; no usable points → `UNAVAILABLE`.

## Percentile algorithm

`apy_distribution.percentile` is the rank of the CURRENT (latest canonical)
APY within the SAME pool's usable observed APY values in the window, as a
fraction 0..1 by the **midrank** tie policy:

    percentile = (#values strictly below + 0.5 × #values equal) / count

Ties resolve deterministically to the halfway rank.  It is descriptive only:
NOT an expected return, probability, forecast, or cross-pool comparison.

## Quartile algorithm

q25/q50/q75 use the deterministic nearest-rank rule on the ascending usable
values: `index = ceil(p × n) − 1`, no interpolation (with an even count the
median is the upper-middle element).  The persistence fractions use the same
q50, so every statistic is reproducible from the sorted canonical values.

## Observation-based vs time-based

All persistence facts are computed over USABLE OBSERVATIONS and are labelled
`OBSERVATION_BASED`.  With irregularly spaced observations they never imply
elapsed-time persistence and are never time-weighted:

- `fraction_within_10pct_of_median` — usable observations with
  `|value − median| ≤ 0.1 × |median|` over the count;
- `fraction_above_window_median` — usable observations strictly above the
  window median over the count.

## APY compression

`trailing_peak_apy` is the maximum usable APY in the window;
`current_vs_peak_delta_bps = (current − peak) × 10,000`.  This is a factual
APY-compression measure.  APY movement is NOT asset price return: it is never
called a loss, a drawdown of capital, or a negative return.

## TVL context and TVL drawdown

Where canonical TVL observations exist: current (newest TVL-bearing
observation), trailing min/max, observation count,
`tvl_drawdown_fraction = (current_tvl / trailing_max_tvl) − 1` published only
when current and trailing max exist and trailing max > 0, and
`baseline_change_fraction = (current_tvl / earliest_tvl) − 1` when the
earliest usable TVL > 0.  A TVL reduction is factual liquidity/participation
context — never investor loss.  Missing TVL stays unavailable.

## Reward dependency

`reward_apy_share = apy_rewards / apy_total` from the LATEST canonical
observation, only when both components exist and `apy_total ≠ 0`.  Components
are never fabricated or inferred by subtraction; a missing component leaves
the share unavailable.  The share is a factual number with an evidence state —
it is never labelled safe/unsafe.

## Missing-evidence rules

Every section is independently available: missing rewards APY leaves the APY
distribution intact; missing TVL leaves the APY context intact; insufficient
APY history leaves the current canonical APY unchanged.  Missing values
serialize as null — never zero.  One malformed observation is skipped as
unusable and fabricates nothing.

## Why there is no composite risk score

There is no Yield Sharpe, risk-adjusted APY score, quality score, 0–100
score or A/B/C grade in V2.  A historical risk-adjusted statistic would
require a matched historical Treasury series for every Yield observation,
which is not canonical today; the CURRENT Treasury spread is not sufficient
to construct one, and none is invented.  V2 publishes facts only; any later
presentation may sort by individual factual metrics, and no
BEST/SAFEST/HIGHEST-QUALITY/BUY decision exists in the read model.
