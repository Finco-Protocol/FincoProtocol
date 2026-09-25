"""Generic EV Charging Hub V1 — single EV economic authority.

Pure, typed functions and constants. No engine, persistence, routes, or UI.
Every EV economic derivation (equivalent full-load hours, energy delivered,
charging revenue, grid energy purchased, electricity procurement expense)
flows through this module so the factory, the reference seed service, and the
UI projections can never disagree.

All values are synthetic public-reference assumptions. Nothing here is a
market average, operator benchmark, or tariff forecast.
"""
from __future__ import annotations

# ── Reference configuration (spec F/O) ───────────────────────────────────────
REFERENCE_CAPACITY_MW = 5.0
CHARGING_POINTS = 40          # display metadata only — never a capacity authority
Y1_FULL_LOAD_HOURS = 1200.0
Y2_FULL_LOAD_HOURS = 1600.0
STABILIZED_FULL_LOAD_HOURS = 2000.0
CHARGING_PRICE_EUR_KWH = 0.40              # == 400 EUR/MWh
CHARGING_PRICE_ESCALATION = 0.02
CHARGING_EFFICIENCY = 0.94                 # delivered / purchased identity
ELECTRICITY_PRICE_EUR_KWH = 0.12           # == 120 EUR/MWh
ELECTRICITY_PRICE_ESCALATION = 0.02
AVAILABILITY = 0.98                        # display metadata: the equivalent
# full-load hours are NET of availability effects, so the engine runs at a
# neutral 1.0 combined availability and energy reconciles exactly.

CHARGING_PRICE_EUR_MWH = CHARGING_PRICE_EUR_KWH * 1000.0        # 400
ELECTRICITY_PRICE_EUR_MWH = ELECTRICITY_PRICE_EUR_KWH * 1000.0  # 120

# Fixed (non-power) OPEX, Y1 stabilized kEUR: B.01+B.02+B.05+B.06+B.07+B.10+B.11.
# Excludes the derived B.08 electricity procurement line by construction.
NON_POWER_OPEX_Y1_KEUR = 960.0

# Payment processing: V1 authority is the fixed B.11 amount (80 kEUR), which
# equals 2.0% of stabilized gross charging revenue at reference scale. V1 does
# not dynamically scale payment fees with revenue (documented limitation).
PAYMENT_FEE_PCT_OF_REVENUE_REPORTED = 0.02

FULL_LOAD_HOURS_RAMP: tuple[float, ...] = (
    Y1_FULL_LOAD_HOURS,
    Y2_FULL_LOAD_HOURS,
    STABILIZED_FULL_LOAD_HOURS,
)


def full_load_hours_for_year(year_index: int) -> float:
    """Equivalent full-load hours for a 1-based operating year.

    Y1 1200, Y2 1600, Y3+ 2000 (the last ramp value repeats).
    """
    clamped = min(max(int(year_index), 1), len(FULL_LOAD_HOURS_RAMP))
    return FULL_LOAD_HOURS_RAMP[clamped - 1]


def implied_utilisation_pct(year_index: int) -> float:
    """Displayed implied capacity utilisation (hours / 8760)."""
    return full_load_hours_for_year(year_index) / 8760.0 * 100.0


def energy_delivered_mwh(capacity_mw: float, year_index: int) -> float:
    """Energy delivered to vehicles: capacity MW × equivalent full-load hours."""
    return capacity_mw * full_load_hours_for_year(year_index)


def grid_energy_purchased_mwh(capacity_mw: float, year_index: int) -> float:
    """Grid energy purchased = energy delivered / charging efficiency."""
    return energy_delivered_mwh(capacity_mw, year_index) / CHARGING_EFFICIENCY


def charging_revenue_keur(
    capacity_mw: float,
    year_index: int,
    *,
    apply_price_escalation: bool = True,
) -> float:
    """Gross charging revenue kEUR = energy delivered × price (EUR/MWh) / 1000.

    ``apply_price_escalation=False`` gives the pre-escalation reconciliation
    values used by the acceptance contract (Y1 2400, Y2 3200, stabilized 4000
    at 5 MW).
    """
    price = CHARGING_PRICE_EUR_MWH
    if apply_price_escalation:
        price *= (1.0 + CHARGING_PRICE_ESCALATION) ** (int(year_index) - 1)
    return energy_delivered_mwh(capacity_mw, year_index) * price / 1000.0


def electricity_expense_keur(
    capacity_mw: float,
    year_index: int,
    *,
    apply_price_escalation: bool = True,
) -> float:
    """Electricity procurement expense kEUR for one operating year.

    = grid energy purchased MWh × electricity price EUR/MWh / 1000, with the
    electricity price escalating 2%/yr from Y1.
    """
    price = ELECTRICITY_PRICE_EUR_MWH
    if apply_price_escalation:
        price *= (1.0 + ELECTRICITY_PRICE_ESCALATION) ** (int(year_index) - 1)
    return grid_energy_purchased_mwh(capacity_mw, year_index) * price / 1000.0


def electricity_opex_item(*, capacity_mw: float = REFERENCE_CAPACITY_MW,
                          horizon_years: int = 20):
    """Build the DERIVED B.08 electricity-procurement OpexItem.

    One OpexItem expresses the whole deterministic schedule through the
    existing sustained-step mechanics (finco_core.opex.projections
    ``opex_item_amount_at_year``):

    - Y1 base amount = grid purchase at Y1 ramp hours × Y1 price;
    - a sustained step at Y2 (ramp 1600 h, price escalated once);
    - a sustained step at Y3 (stabilized 2000 h, price escalated twice);
    - Y4+ escalate from the Y3 step by the 2% electricity-price escalation.

    The item is DERIVED: it must be recomputed from the drivers on any
    capacity change, never linearly scaled.
    """
    from finco_core.inputs import OpexItem

    y1 = electricity_expense_keur(capacity_mw, 1)
    y2 = electricity_expense_keur(capacity_mw, 2)
    y3 = electricity_expense_keur(capacity_mw, 3)
    return OpexItem(
        name="Electricity Procurement",
        y1_amount_keur=y1,
        annual_inflation=ELECTRICITY_PRICE_ESCALATION,
        step_changes=((2, y2), (3, y3)),
    )


def effective_charging_price_eur_mwh(year_index: int) -> float:
    """Effective charging revenue rate per MWh of *stabilized* energy.

    The engine runs at stabilized 2000 equivalent full-load hours (the scalar
    hours authority); the utilisation ramp is encoded exactly into the
    per-calendar-year revenue rate: rate(n) = price × hours(n)/2000 ×
    1.02^(n-1). Multiplying back by stabilized energy reproduces the true
    charging revenue to floating-point exactness. Internal adapter — never
    surfaced as a "market price".
    """
    return CHARGING_PRICE_EUR_MWH * (full_load_hours_for_year(year_index) / STABILIZED_FULL_LOAD_HOURS) * (
        (1.0 + CHARGING_PRICE_ESCALATION) ** (int(year_index) - 1)
    )


def merchant_price_schedule(fc_year: int, horizon_years: int = 20) -> tuple[int, tuple[float, ...]]:
    """Calendar-year effective-price schedule for the engine's merchant path.

    Returns (start_year, prices) where prices[k] is the effective rate for
    calendar year fc_year + k. Index 0 (the financial-close year, containing
    only construction periods) repeats the first operating year's rate so the
    tuple always covers period end-years; operating year n lives at index n.
    """
    start = int(fc_year)
    prices = [effective_charging_price_eur_mwh(1)]
    for op_year in range(1, horizon_years + 1):
        prices.append(effective_charging_price_eur_mwh(op_year))
    return start, tuple(prices)


def scale_capacity(capacity_mw: float, *, horizon_years: int = 20):
    """Return (y1_amount, step_changes) for an arbitrary capacity.

    Used by the reference seed service so a working copy's electricity line is
    recomputed from the drivers (DERIVED) instead of linearly scaled.
    """
    item = electricity_opex_item(capacity_mw=capacity_mw, horizon_years=horizon_years)
    return item.y1_amount_keur, item.step_changes


__all__ = [
    "REFERENCE_CAPACITY_MW", "CHARGING_POINTS", "Y1_FULL_LOAD_HOURS",
    "Y2_FULL_LOAD_HOURS", "STABILIZED_FULL_LOAD_HOURS",
    "CHARGING_PRICE_EUR_KWH", "CHARGING_PRICE_EUR_MWH",
    "CHARGING_PRICE_ESCALATION", "CHARGING_EFFICIENCY",
    "ELECTRICITY_PRICE_EUR_KWH", "ELECTRICITY_PRICE_EUR_MWH",
    "ELECTRICITY_PRICE_ESCALATION", "AVAILABILITY", "NON_POWER_OPEX_Y1_KEUR",
    "PAYMENT_FEE_PCT_OF_REVENUE_REPORTED", "FULL_LOAD_HOURS_RAMP",
    "full_load_hours_for_year", "implied_utilisation_pct",
    "energy_delivered_mwh", "grid_energy_purchased_mwh",
    "charging_revenue_keur", "electricity_expense_keur",
    "electricity_opex_item", "scale_capacity",
    "effective_charging_price_eur_mwh", "merchant_price_schedule",
]
