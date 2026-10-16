# PPA-01 — Explicit CPI/PPI index series on a Revenue V2 PPA

Status: implemented on `feat/model-sc34-input-workflow-reliability`; for independent financial review. PR #289 is an implementation reference only
(its `PPAParams.ppa_index_values` helper is not wired to Revenue V2 and is **not** used).

## Convention (reconciled with existing FINCO policy — no new time basis)

* Revenue V2 already prices indexed PPAs on the **model operating year** (`indexation_basis: OPERATING_YEAR`, engine `year_index`: year 1 = first
  operating year from COD, partial first period included). The index series uses exactly the same year key. Contract-year ≠ operating-year when a
  contract starts after COD or COD is mid-period; the series is keyed by operating year so no second basis is introduced.
* Price for operating year *y*: `P_y = price_eur_mwh × level[y] ÷ level[base]`, base = first observation. `price_eur_mwh` is the price at the base level.
* The year key is the existing canonical `PeriodMeta.year_index`: for the semiannual axis it advances after two operating periods, including a partial first period. It is not a calendar-year label, contract anniversary or an independently reconstructed elapsed-year count.
* Distinct economic inputs stay distinct: `indexation_rate` (annual %), `price_curve` (explicit EUR/MWh) and `index_series` (published levels) are
  mutually exclusive on one stream (`REVENUE_V2_INDEX_MIXED_BASIS`).
* Levels are supplied by the user (observed = published, forecast = user assumption; the flag is evidence only and does not change the
  calculation). Nothing is invented, interpolated, extrapolated or replaced by an annual rate.

## Typed schema (version 2 PPA only; optional key, absent for every legacy contract)

`"index_series": [{"operating_year": int>=1, "level": finite>0, "basis": "OBSERVED"|"FORECAST"}, ...]` — 1–60 points, strictly increasing and
**continuous** years (gap → `REVENUE_V2_INDEX_GAP`, duplicate/unordered → `REVENUE_V2_INDEX_ORDER`).

Axis validation (Save and Run, `validate_axis`): the first (base) year must be ≤ the first priced operating year (`REVENUE_V2_INDEX_BASE`) and every
priced operating year needs a level (`REVENUE_V2_INDEX_COVERAGE`). A series longer than the contract is allowed (unused years are ignored).

## Structural versus financial evaluation (Correction A)

`validate_structure_at(date)` checks dated activity, volume allocation and overlay coverage and returns no financial plan. The parser calls this method before the canonical axis is available; it neither invents a year nor claims an indexed price.

`plan_at(date, year_index)` is financial pricing. An active index-series PPA requires a positive integer canonical operating-year key; a missing, boolean, fractional or string key fails with `REVENUE_V2_INDEX_YEAR_CONTEXT`. A valid year without a supplied observation fails with `REVENUE_V2_INDEX_COVERAGE`. Canonical `evaluate(period, generation)` passes `period.year_index`. No annual-rate fallback, interpolation or extrapolation is permitted. Legacy non-series plans retain their existing no-year behavior, and an inactive series does not require an irrelevant year.

This is a candidate financial-authority change. No new release pin is authorized by this document; independent exact-blob and operating-year convention acceptance is required before governance release.

## Unchanged

Fixed, annual-rate indexed and Scheduled PPAs, Merchant/residual Merchant, CfD, volume allocation, contract dates/settlement, floor/cap handling
(applied to the resolved price by the existing `PPAParams.price_at_year`), Revenue V3 (release-closed; it re-parses energy streams through the same
parser and therefore inherits the schema, but is not enabled), commercial stress (`ppa_down` scales `price_eur_mwh`, levels untouched).

## Open points for the financial reviewer

1. Confirm that keying by model operating year (not contract year) is the intended institutional convention for contracts starting after COD.
2. Per-period committed evidence already records the effective `price_eur_mwh`; the index level itself is retained in the committed configuration.
   Adding explicit `index_level` to the per-period evidence schema was not done (protected evidence schema).
3. Floor/cap are not exposed in the Revenue V2 JSON schema; they were not added.
