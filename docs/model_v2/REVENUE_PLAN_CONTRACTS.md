# Model V2 Revenue Plan Contracts

Status: domain-level foundation (Workflow 02). Not wired into ProjectInputs;
the production runtime path is unchanged. The runtime bridge is a later,
independently reviewed workflow.

## Modules

| Module | Owns |
|---|---|
| `domain/revenue/plan.py` | `RevenuePlan`, `RevenueStream`, `RevenueAllocationGroup`, `RevenueStreamType`, `ContractRole`, `PriceIndexation`, fail-closed validation |
| `domain/revenue/plan_engine.py` | per-period volume allocation, stream composition, `RevenueStreamPeriodResult`, `RevenuePlanPeriodResult`, typed statuses, aggregation identity |
| `domain/revenue/legacy_plan_adapter.py` | pure-domain `RevenueConfig` → `RevenuePlan` representation (documented, fail-closed limitations) |

## Math authority (reuse, never duplicate)

All price resolution calls the existing domain authorities:

- PPA: `PPAParams.price_at_year` (indexation, floor, cap) and the existing
  balancing-cost convention `net = gross × (1 − balancing_cost_pct)`.
- Merchant: `MerchantParams.price_at_year` (custom curves, escalation,
  cannibalization) + `capture_rate_for_tech`.
- Fixed / premium / awarded tariffs: `FeedInTariffParams.price_at_year`
  (fixed indexation; premium clip `clip(spot + premium, floor, cap)`).
- CfD settlement: `CfDParams.cfd_payment_at_year` (two-way/one-way), invoked
  with the period's contractual volume.

## Primary vs overlay

`ContractRole.PRIMARY_ALLOCATION` streams consume eligible generation volume
in their `allocation_group`: PPA, Merchant, fixed FiT, indexed FiT,
auction-awarded tariff. `ContractRole.SETTLEMENT_OVERLAY` streams settle on
an explicitly declared contractual volume and consume no allocation
capacity: two-way CfD and sliding premium support. A market + CfD structure
is therefore first-class valid, and no MWh is ever monetized twice.

Residual merchant: a MERCHANT stream with `volume_share=None` receives
exactly `eligible − Σ explicit primary shares` of its group, floor zero.
Explicit shares are never normalized: a group contracting more than 100%
fails closed (`REVENUE_ALLOCATION_EXCEEDS_ELIGIBLE_GENERATION`).

## Statuses

`ACTIVE` / `DISABLED` / `NOT_STARTED` / `EXPIRED` / `UNAVAILABLE` per stream
period; `OK` / `PARTIALLY_UNALLOCATED` / `HAS_UNAVAILABLE_STREAMS` per plan
period. `stream_revenue_keur` is `None` when unavailable — MISSING and
UNAVAILABLE are never ZERO, INACTIVE is never UNAVAILABLE, EXPIRED is never
INVALID. An indexed FiT without an index factor for the year is
`UNAVAILABLE` (no silent extrapolation).

## Indexed FiT limitation

`INDEXED_FIT` computes `base tariff × explicit index factor[year]` and is
currency-neutral at this domain layer: there is no FX engine and no hedging
claim. Any future currency conversion must be a typed, auditable authority.

## Identities (tested)

- `total_revenue_keur = Σ stream_revenue_keur` for every period.
- `Σ allocated primary volumes + unallocated = eligible generation`.
- Overlay streams add only their settlement/support; their
  `underlying_market_revenue_keur` is a displayed component of the market
  sale that already belongs to the volume-owning primary stream.
