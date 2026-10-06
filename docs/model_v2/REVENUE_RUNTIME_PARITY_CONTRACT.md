# Model V2 Revenue Runtime Parity Contract (Workflow 05B)

Status: the runtime-parity bridge extends the Workflow 05 revenue bridge so a
validated Workflow 02 `RevenuePlan` reaches the EXISTING canonical runtime
(`finco_core/revenue/generation.py::revenue_decomposition_schedule`) with
exact economics. The frozen core remains the one calculation authority; this
layer only decides WHICH canonical `RevenueParams` fields a plan maps onto —
it never adds a shadow engine and never duplicates PPA or merchant
mathematics.

## Module

| Module | Owns |
|---|---|
| `app/services/model_v2_composition/runtime_parity.py` | `bridge_plan_to_runtime_revenue(plan, *, base_inputs, technology)` — stream→`RevenueParams` field mapping, per-operating-period tariff schedules, capture-rate embedding, fail-closed seam registry |

`compose.py::_revenue_params_from_plan` applies the returned overrides onto
the canonical `RevenueParams` copy inside the existing composition
precedence (base → cost template → revenue plan → scenario carried).

## Expressible mappings (exact economics, no duplication)

| Plan authority | Canonical `RevenueParams` field(s) | Semantics |
|---|---|---|
| Merchant `base_price_eur_mwh` / scenario / custom curve | `market_prices_curve` (expanded per horizon year via `MerchantParams.price_at_year`) + `market_inflation` | Technology capture rate (solar 0.85 / wind 0.90 default; per-stream override) is EMBEDDED into the curve values — the runtime sells at curve price and must not discount again |
| PPA base tariff + index + term | `ppa_base_tariff`, `ppa_index`, `ppa_term_years`, `ppa_production_share` | Copied verbatim; PeriodEngine lifecycle (`is_ppa_active`) stays the runtime authority |
| PPA with delayed start or finite term under a semestrial/quarterly axis | `ppa_tariff_by_operating_period` | Per-operating-period schedule built from `tariff_at_year`, aligned to the axis via `periods_per_year_for` |
| Explicit FiT factor schedule (`indexed_fit_index_factors`) | `ppa_base_tariff` + `ppa_tariff_by_operating_period` | Factor for year Y applies to `base_tariff × factor[Y-1]`; a missing factor year fails closed (typed unavailable — never extrapolated) |
| Auction-awarded fixed tariff | `ppa_base_tariff` (+ share/term) | Auction is a fixed-tariff authority at the runtime seam |
| Allocation shares across the tariff family | `ppa_production_share` | Only when exactly one fixed-tariff stream is simultaneously ACTIVE |

## Fail-closed seams (documented, never approximated)

| Seam code | Trigger | Why |
|---|---|---|
| `RUNTIME_SUPPORT_OVERLAY_SEAM_MISSING` | Any enabled CfD or premium-FiT stream | The frozen core `RevenueParams` has NO additive support-settlement field; stuffing settlements into PPA tariffs or merchant prices would corrupt the merchant/PPA split |
| `RUNTIME_TARIFF_PATH_OVERLAP` | Two fixed-tariff-family streams simultaneously ACTIVE | The canonical runtime expresses exactly ONE tariff path |
| `RUNTIME_DELAYED_START_SHARE_RELEASE_UNSUPPORTED` | PPA with `start_year > 1` while `ppa_production_share < 1` | The runtime production share is horizon-constant; the pre-start 100% merchant residual is inexpressible |
| `RUNTIME_INDEXED_FIT_AUTHORITY_MISSING` | `indexed_fit_index_factors` shorter than the required year | Typed unavailable; no extrapolation |
| `RUNTIME_PERIOD_FREQUENCY_UNSUPPORTED` | Axis period count not in {1, 2, 4} per year | The per-period schedule builder only supports Annual/Semestrial/Quarterly |
| `RUNTIME_MERCHANT_PRICE_INVALID` | Non-finite or negative expanded price | Refuse to write a corrupt curve |
| `RUNTIME_CAPTURE_RATE_INVALID` | Capture rate outside (0, 1] | Refuse to silently scale to zero |

Multi-PPA allocation remains a Workflow 02 PLAN-level concept (plan engine
validates shares sum ≤ 1); at the runtime seam it fails closed because the
canonical authority carries one PPA tariff path.

## Economic identity hash

The composition hash binds the plan payload through an ECONOMIC projection:
`counterparty` and `lender_eligible` (documented non-economic fields on
`RevenueStream`) are excluded. Presentation metadata changes therefore do
not change `composition_hash`; economic changes always do.

## Technology parameter

`compose_project_inputs(..., technology=...)` selects the capture-rate
authority (`capture_rate_solar` / `capture_rate_wind`). Callers composing
wind projects must pass `technology="wind"`; the default is solar.

## Regression matrix

`tests/test_model_v2_revenue_runtime_parity.py` — markers
`RUNTIME_PARITY_*`: PPA (full/partial/indexed), merchant (solar/wind
capture/custom curve), allocation, indexed FiT (explicit schedule +
missing-authority fail-closed), auction fixed tariff, CfD/premium
seam-missing, delayed-PPA share release, tariff-path overlap, lifecycle
windows through `ppa_tariff_by_operating_period`, identity (label change
does not move the hash; economic change does), and no-frozen-diff.
