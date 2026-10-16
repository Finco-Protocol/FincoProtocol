# PPA-01 contractual calendar indexation candidate

Status: methodology authorized for candidate development; exact financial
content, governance successor and production release NOT approved.

## C2 optional contractual rounding

Version-2 PPA contracts may explicitly supply `price_rounding` with boolean
`enabled`, `decimal_places` (2, 3, 4 or 6) and `method` (HALF_UP or HALF_EVEN).
Absent or disabled means OFF, without migrating any saved contract. Enabled
policies require explicit precision and method. Merchant, CfD, version-3 books
and explicit price curves cannot acquire this indexed-PPA policy.

The single existing PPAParams price authority applies original base price,
indexation, existing floor/cap, then Decimal quantization, then existing revenue
and settlement. No new floor/cap JSON fields exist. It never rounds an earlier
rounded price: every review starts from the original base and index methodology.
Before the first completed annual review the base is not quantized; the first
model-year index observation is a base, not a completed review. Pre-COD reviews
can establish a rounded opening contractual price, without pre-COD sales.

At 1000 MWh, indexed 63.07404 rounded HALF_UP/2 becomes 63.07 EUR/MWh and
63.07 kEUR gross revenue. Ties 62.345 give 62.35 (HALF_UP) or 62.34 (HALF_EVEN);
62.355 gives 62.36 for both. Rounding after a cap of 62.345 may yield 62.35;
rounding after a floor of 62.345 may yield 62.34. There is deliberately no second
clamp or hidden financial correction.

Enabled calculations retain Decimal through indexation and quantization. An
explicitly quantized zero is valid, unlike loss of a positive unrounded Decimal
during float conversion. The owner separately authorized rejecting that loss
in the dated CPI/PPI OFF path: positive 1e-816 now refuses deterministically;
representable subnormals and genuine zero keep their previous float values.
C1 model-year overflow/underflow protections remain intact.

The existing editor exposes a collapsed policy control, default OFF, and saved
price stages from Python. Unsaved edits hide those stages until a successful
Save. JavaScript serializes policy, never computes contractual rounding.
The existing committed `scenario_revenue_input.multistream_config_json` binds
the exact policy and original terms; period revenue audit binds actual prices,
quantities and outcomes. Historical evidence is not recomputed or migrated.

These are candidate semantics, not released financial authority. Three exact
protected blobs require renewed independent review and explicit owner release
authorization before a governance successor can be enabled.

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
