# Model V2 Revenue Runtime Parity Contract (Workflow 05B, Correction A)

Status: PRODUCTION-PATH-VERIFIED. Every structure this contract claims as
runtime-supported is proven through the REAL production chain — not merely
present on composed `ProjectInputs`. Every other structure fails closed
with a typed seam. The frozen core remains the one calculation authority;
this layer owns only the field mapping.

## The production chain (traced, Correction A §2)

```
RevenuePlan → compose_project_inputs → ProjectInputs(revenue=…)
→ run_clean_production (app/services/production_financial_authority)
→ financial_engine.adapters.project_inputs.from_project_inputs
→ OperatingModelInput.revenue : RevenueInput   (clean contract)
→ financial_engine.orchestrator.run_operating_model
→ finco_core ProjectInputs proxy → revenue_decomposition_schedule
→ EBITDA / CFADS / debt service / shareholder waterfall / returns
```

The clean `RevenueInput` contract (financial_engine/inputs.py) forwards
exactly: `ppa_base_tariff`, `ppa_term_years`, `ppa_index`,
`ppa_production_share`, `market_prices_curve`, `market_inflation`,
`balancing_cost_pv`, `balancing_cost_wind_eur_mwh`,
`balancing_cost_eur_per_mwh`, CO2 fields,
`first_merchant_operating_period_index`, `ppa_indexation_start_policy` /
`_date`, and the merchant calendar-year fields.

**It has NO field for `ppa_tariff_by_operating_period`.** The orchestrator
derives its own per-period schedule solely from the indexation policy. A
per-period tariff schedule composed on `ProjectInputs` therefore NEVER
reaches the engine. Any capability that requires one is a missing
production seam — classified as such below, never claimed as supported.

## Field governance classification (Correction A §3)

A selected RevenuePlan is THE revenue authority. On every selection the
bridge writes a COMPLETE plan-governed override set (explicit supersession
— no stale base value can leak through a partial overwrite):

| Class | Fields | Treatment on V2 selection |
|---|---|---|
| A — plan-governed | `ppa_base_tariff`, `ppa_term_years`, `ppa_index`, `ppa_production_share` | Written from the selected fixed-tariff stream (stream owns term/share; nested price-authority lifecycle metadata is documentation only). No tariff stream → all four zeroed (term 0 kills the PPA window). |
| A — plan-governed | `ppa_tariff_by_operating_period` | Always neutralized to `()` — V2 never supplies per-period schedules (production seam missing; see above) and a base schedule would override the analytic path. |
| A — plan-governed | `ppa_indexation_start_policy`, `ppa_indexation_start_date` | Always neutralized to `None` — V2 index semantics = plan `price_at_year` (geometric from operating year 1) = the legacy `tariff_at_year` path; a base policy would change the timing. |
| A — plan-governed | `market_prices_curve`, `market_inflation` | Written from the selected merchant authority (capture rate embedded — plan semantics); no merchant stream → curve `()`, inflation `0.0`. |
| A — plan-governed | `market_price_calendar_start_year`, `market_prices_by_calendar_year_eur_mwh` | Always neutralized — the calendar-year schedule takes precedence over the curve in `market_price_for_period`; a V2 selection must supersede it. |
| A — plan-governed | `first_merchant_operating_period_index` | Always neutralized — a base value overrides the entire PPA-active boundary (`ppa_active = op_idx < idx`). |
| A — plan-governed | `balancing_cost_pv` | Always `0.0` — V2 plan semantics carry NO merchant balancing percentage. |
| B — orthogonal | `co2_*`, `balancing_cost_wind_eur_mwh`, `balancing_cost_eur_per_mwh`, `balancing_cost_schedule` | Project physical/regulatory authorities outside the plan vocabulary — a selection neither reads nor mutates them (proven to survive, and to reach production, by the wind E2E). |

## Expressible structures (exact economics, production-proven)

- **Merchant-only** — exactly ONE enabled merchant stream, `start_year=1`,
  unlimited term; `volume_share=None` (residual) or `1.0`
  (Correction B2: an explicit share below 1.0 would leave plan-unallocated
  volume that the runtime would still sell — fail closed).
  `market_prices_curve` expanded per horizon year through
  `MerchantParams.price_at_year` (the SAME authority plan_engine uses;
  escalation and cannibalization baked in), technology capture rate
  embedded (solar 0.85 / wind 0.90 / per-stream override).
- **One fixed-tariff contract, starting year 1**: PPA, FIT_FIXED or
  AUCTION_AWARDED_TARIFF on the analytic authority —
  `ppa_base_tariff` (contract price), `ppa_index` (PPA `ppa_price_index`
  or FiT `fit_index`), `ppa_production_share` (stream `volume_share`),
  `ppa_term_years` (stream term; unlimited → full horizon).
- **PPA / FiT + residual merchant** (`volume_share=None`, year 1,
  unlimited — Correction B2) — share < 1 with the merchant curve carrying
  the residual. An EXPLICIT merchant share alongside a tariff stream is
  not the runtime residual semantics — fail closed.
- **Term-limited tariff** — only when the term anniversary coincides with
  a period START on the project's actual calendar axis (the engine window
  is DATE-anchored: COD + term; a mid-period anniversary would price a
  partial period at the tariff while the plan has the year inactive).
  Unlimited terms cover the horizon and need no alignment.
- **Residual/tail merchant requirement** — a partial-share or term-limited
  tariff contract REQUIRES a selected merchant stream: unallocated volume
  sells at `market_price_at_year`, which falls back to the PPA tariff when
  the curve is empty; "unallocated volume earns nothing" is inexpressible
  otherwise.

E2E proof (`tests/test_model_v2_revenue_runtime_parity.py::TestProductionE2E`):
compose → `run_clean_production` → total income-statement revenue equals
the Workflow 02 `evaluate_revenue_plan` applied to the runtime's own
generation schedule (`full_generation_schedule`) — merchant-only, PPA-only,
PPA+residual (term-limited, boundary-aligned), fixed FiT, auction, wind
capture, calendar-schedule supersession. No finance formula is
reimplemented in the tests.

## Fail-closed seams (typed, documented — never approximated)

| Seam | Trigger |
|---|---|
| `RUNTIME_SUPPORT_OVERLAY_SEAM_MISSING` | Enabled CfD or premium-FiT stream — no additive support-settlement field in the frozen core. |
| `RUNTIME_TARIFF_PATH_MULTIPLE_UNSUPPORTED` | More than one enabled fixed-tariff-family stream — ONE tariff path and ONE horizon-constant share exist; sequential, gapped or different-share chains are inexpressible even when price schedules could be concatenated (Correction A §10). |
| `RUNTIME_DELAYED_START_TARIFF_SEAM_MISSING` | `start_year > 1` — the engine window opens at COD; pre-start volume cannot be released to merchant. |
| `RUNTIME_TARIFF_TERM_GRAIN_SEAM_MISSING` | Fractional `term_years` — plan grain is model years, engine window is date-anchored; boundary half-periods diverge. |
| `RUNTIME_TARIFF_TERM_ALIGNMENT_SEAM_MISSING` | Integer term whose COD anniversary falls inside an operating period (partial period priced at the tariff vs plan-inactive year). |
| `RUNTIME_UNALLOCATED_VOLUME_WITHOUT_MERCHANT` | Partial-share or term-limited tariff without a selected merchant authority. |
| `RUNTIME_INDEXED_FIT_AUTHORITY_MISSING` | An ACTIVE indexed-FiT year without a factor — MISSING ≠ ZERO, never a zero tariff, never extrapolation (the plan contract itself refuses a stream without a base tariff). |
| `RUNTIME_INDEXED_FIT_SCHEDULE_SEAM_MISSING` | Indexed FiT with complete factors — needs a per-year tariff schedule, which the production adapter does not forward. |
| `RUNTIME_MULTIPLE_MERCHANT_STREAMS_UNSUPPORTED` | More than one enabled merchant stream — the runtime has ONE merchant price path; plan_engine evaluates each independently. Curves are never averaged or combined (Correction B1). |
| `RUNTIME_MERCHANT_LIFECYCLE_SEAM_MISSING` | Merchant stream with `start_year > 1` or finite `term_years` — the runtime residual path sells from COD to horizon end; it cannot open late, stop early, or gap (Correction B2). |
| `RUNTIME_MERCHANT_ALLOCATION_SEAM_MISSING` | Merchant `volume_share` explicit below 1.0 (plan-unallocated volume would still be sold by the runtime), or an explicit merchant share alongside a tariff stream (Correction B2). |
| `RUNTIME_PPA_FLOOR_CAP_SEAM_MISSING` | Non-zero PPA `ppa_price_floor` / `ppa_price_cap` — plan `price_at_year` applies them after indexation; the runtime analytic path has no floor/cap field and per-period schedules do not reach the production engine (Correction B3). |
| `RUNTIME_PPA_BALANCING_SEAM_MISSING` | Non-zero plan `balancing_cost_pct` / `imbalance_penalty_pct` — plan semantics deduct it from PPA revenue; the frozen core deducts `balancing_cost_pv` from MERCHANT revenue only (Excel CF row 40). Different deduction bases: NOT mappable (Correction A §7). |
| `RUNTIME_MERCHANT_PRICE_INVALID` / `RUNTIME_CAPTURE_RATE_INVALID` / `RUNTIME_TARIFF_VALUE_NON_FINITE` / `RUNTIME_PERIOD_FREQUENCY_UNSUPPORTED` / `RUNTIME_HORIZON_INVALID` | Degenerate inputs. |

## Period axis (Correction A §5)

Tariff indexation uses the OPERATING YEAR exclusively (the engine's
`tariff_at_year(period.year_index)`; periods_per_year ∈ {1, 2, 4}).
Semestrial proof: both periods of operating year Y carry the year-Y tariff
(`TestPeriodAxis`). Tariff selection is never annualized/4 and never
indexed by period number.

## Economic identity hash

The composition hash binds the plan payload through an ECONOMIC
projection: `counterparty` and `lender_eligible` (documented non-economic
fields on `RevenueStream`) are excluded — presentation changes do not move
`composition_hash`; economic changes always do.

## Technology parameter

`compose_project_inputs(..., technology=...)` selects the capture-rate
authority (solar/wind). Wind compositions must pass `technology="wind"`.

## Regression matrix

`tests/test_model_v2_revenue_runtime_parity.py` — 54 tests, markers
`RUNTIME_PARITY_*`: production-path contract, supersession (adversarial
stale base), PPA/merchant/FiT/auction parity, allocation and lifecycle,
indexed-FiT MISSING≠ZERO, all seams, identity, period axis, production
E2E, legacy passthrough, no-frozen-diff.
