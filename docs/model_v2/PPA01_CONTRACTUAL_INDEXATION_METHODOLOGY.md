# PPA-01 contractual calendar indexation candidate

Status: methodology authorized for candidate development; exact financial
content, governance successor and production release NOT approved.

## Dates and review convention

`price_base_date` identifies the contractual reference date of the entered
EUR/MWh price. `resolved_start_date` is a checked resolution of SIGNATURE
(required signing_date), COD (canonical project COD), PPA_START (stream start),
or CUSTOM (required custom_start_date). These are separate dates, not defaults
for each other. `first_review_date` is explicitly entered and must equal the
first annual anniversary of the resolved start. Later reviews are exact annual
anniversaries; leap-day dates without an exact anniversary are refused, never
clamped. Other review frequencies/partial first-review rules remain unsupported.

The price base date must not follow the first PPA selling period or indexation
start. Retroactive use of a future-referenced base price is unsupported.
Annual fixed pricing holds P0 between price_base_date and indexation start;
there is no inferred rebasing before the start. At period start t its price is
P0 * (1+r)^n, where n counts effective annual reviews <= t. Reviews before COD
count, but generate no construction-period energy or revenue.

Dated CPI/PPI pricing uses an explicit `index_base_date` observation and an
explicit reference observation for EVERY annual review before the contract end,
including pre-COD reviews. At the latest effective review k the price is
P0 * I[k] / I[base]; before the first review it is P0. This direct ratio is
not compounded again by the annual-rate path. The customer explicitly chooses
the base reference and lagged observation dates: a base before indexation start
can produce contractual catch-up at the first review. It is never inferred.
To hold a COD-based initial index level, explicitly supply that base level.
The new dated ratio uses a local Decimal context before one float conversion,
so valid finite prices are not rejected for an overflowing intermediate P0*I.
Legacy/model-year arithmetic is not changed by that numeric implementation.

Each observation has a reference date, positive finite level, OBSERVED/FORECAST
label and source reference. OBSERVED requires an explicit publication_date no
later than its applicable review (or the resolved start for the base).
FORECAST requires publication_date=null and remains a user assumption.
Reference periods and publication dates are not effective review dates.
No external provider, lag inference, interpolation or extrapolation exists.

## Optional version-2 PPA terms

`indexation_timing` is an optional object on the existing PPA stream:

```text
method: ANNUAL_FIXED | DATED_INDEX_LEVELS
price_base_date: ISO date, <= resolved_start_date
start_rule: SIGNATURE | COD | PPA_START | CUSTOM
resolved_start_date: ISO date (checked, never an independent COD authority)
first_review_date: ISO date
review_frequency: ANNUAL
mid_period_policy: PERIOD_BOUNDARY_ONLY
signing_date: required only for SIGNATURE
custom_start_date: required only for CUSTOM
index_base_date: required only for DATED_INDEX_LEVELS
observations: required only for DATED_INDEX_LEVELS
reviews: required only for DATED_INDEX_LEVELS
```

An observation has exactly reference_date, level, basis, publication_date,
source_ref. A review has exactly effective_date, reference_date.
ANNUAL_FIXED uses the existing stream indexation_rate; DATED_INDEX_LEVELS
requires it to be zero. Legacy index_series and price_curve cannot be combined
with calendar terms. All dates are exact ISO dates. No absent date is invented.

The serialized COD resolution must equal ProjectInputs.info.cod_date from
Project Timeline, checked against PeriodEngine.cod. It is derived evidence,
not an editable second project COD. The first operating start can differ
(a short initial stub may be rolled into the next 30-Jun/31-Dec boundary).
The existing Save and Run axis validation both verify it. Changing project COD
without explicitly updating dependent contract terms fails closed.

## Period boundary policy

Owner explicitly authorized PERIOD_BOUNDARY_ONLY for this candidate. An
effective review strictly inside an active operating period refuses Save/Run
with its exact date; no rounding, period-start reset or within-period weighting.
Pre-COD reviews do not need operating boundaries. Reviews before a delayed PPA
start establish its opening price but allocate no PPA sales before commencement.
The end date remains exclusive. A partial first period follows the actual axis.

## Examples (independent Decimal expectations)

P0=60, annual rate=2%, signing 2028-12-31, COD 2030-12-31:

| Rule/anchor | First review | Price at COD | Price 2031-12-31 |
|---|---|---:|---:|
| SIGNATURE / 2028-12-31 | 2029-12-31 | 62.424 | 63.67248 |
| COD / 2030-12-31 | 2031-12-31 | 60 | 61.2 |
| CUSTOM / 2029-12-31 | 2030-12-31 | 61.2 | 62.424 |
| PPA_START / 2031-12-31 | 2032-12-31 | No PPA sales | 60 |

Explicit base=100, successive review observations=102,105,110 yield
61.2,63,66 EUR/MWh. Observations may predate COD and have distinct publication
dates. A missing observation at any required review is a refusal.

At 1000 MWh, 60% PPA at 62.424 and 40% Merchant at 80: PPA=37.4544 kEUR,
Merchant=32 kEUR, gross=69.4544 kEUR. Existing balancing/settlement is unchanged.

## Boundaries and acceptance

Legacy contracts without the optional object preserve the original arithmetic,
canonical JSON and model-year index_series behavior. No automatic migration.
No tax, debt, working-capital, period-engine, energy allocation, floor/cap,
governance pin or activation flag changes are authorized by this document.

Required tests include independent dated Decimal prices for Solar/Wind, all
four anchors, pre-COD and delayed starts, partial periods, missing/invalid
observations, publication lags, mixed-basis rejection, exact legacy parity,
scenario CAS, STALE/Run/CURRENT, immutable history, failed Save/Run preservation
and real Chromium editing. This is an implementation specification, not evidence
that those tests have already passed. New exact bytes require separate review.
