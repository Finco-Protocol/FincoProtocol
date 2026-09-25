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


def scaled_ev_reference_inputs(capacity_mw: float, horizon_years: int = 20):
    """EV reference ProjectInputs scaled to an arbitrary installed capacity.

    CAPEX and fixed OPEX scale linearly (PER_MW); the derived electricity
    schedule is recomputed from the drivers at the requested capacity;
    revenue derives from capacity through the engine. The revenue adapter's
    calendar rate schedule is capacity-independent (it encodes prices, not
    amounts). This is the seed base for EV working copies: building effective
    inputs from it keeps the V4-1 anchor check satisfied at every capacity.
    """
    import dataclasses

    from app.project_factories import create_default_ev_charging_project

    ratio = float(capacity_mw) / REFERENCE_CAPACITY_MW
    pi = create_default_ev_charging_project(capacity_mw=capacity_mw, horizon_years=horizon_years)
    scaled_capex_fields = {}
    for f in pi.capex.__dataclass_fields__.values():
        item = getattr(pi.capex, f.name)
        if hasattr(item, "amount_keur") and f.name not in ("idc_keur", "bank_fees_keur"):
            scaled_capex_fields[f.name] = dataclasses.replace(item, amount_keur=item.amount_keur * ratio)
    scaled_capex_fields["idc_keur"] = pi.capex.idc_keur
    scaled_capex_fields["bank_fees_keur"] = pi.capex.bank_fees_keur
    capex = dataclasses.replace(pi.capex, **scaled_capex_fields)
    opex = tuple(
        dataclasses.replace(item, y1_amount_keur=item.y1_amount_keur * ratio)
        if item.name != "Electricity Procurement" else item
        for item in pi.opex
    )
    return dataclasses.replace(pi, capex=capex, opex=opex)


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
    "scaled_ev_reference_inputs",
    "effective_charging_price_eur_mwh", "merchant_price_schedule",
]


# ── Correction B: typed driver authority (post-Data-Center pattern) ──────────
#
# The EV vertical now has ONE explicit, snapshot-persisted driver authority.
# Snapshot-key storage convention follows the workbook registry: escalations
# are persisted as human PERCENT values (2 means 2%), mirroring the DC
# convention.  The runtime adapter re-derives the revenue calendar schedule
# and the B.08 electricity OpexItem from the current drivers on every
# materialization — nothing derived is ever cached or linearly scaled.


from dataclasses import dataclass as _dataclass


@_dataclass(frozen=True)
class EVChargingDrivers:
    """Synthetic public generic EV Charging operating/revenue drivers.

    ``capacity_basis`` is always INSTALLED_CHARGING_MW: ``capacity_mw`` is
    installed charging capacity, never generation capacity.  Equivalent
    full-load hours are NET of availability effects (V1 policy): availability
    stays informational metadata and is never an economic driver here.
    """
    capacity_basis: str = "INSTALLED_CHARGING_MW"
    full_load_hours_y1: float = 1200.0
    full_load_hours_y2: float = 1600.0
    full_load_hours_stabilized: float = 2000.0
    charging_price_eur_kwh: float = 0.40
    charging_price_escalation: float = 0.02
    charging_efficiency: float = 0.94
    electricity_price_eur_kwh: float = 0.12
    electricity_price_escalation: float = 0.02


GENERIC_EV_CHARGING_REFERENCE_DRIVERS = EVChargingDrivers()

# Snapshot keys (percent-convention keys are stored as human-% values).
EV_DRIVER_SNAPSHOT_KEYS = {
    "ev_full_load_hours_y1",
    "ev_full_load_hours_y2",
    "ev_full_load_hours_stabilized",
    "ev_charging_price_eur_kwh",
    "ev_charging_price_escalation",
    "ev_charging_efficiency",
    "ev_electricity_price_eur_kwh",
    "ev_electricity_price_escalation",
}
_EV_PERCENT_KEYS = frozenset({
    "ev_charging_price_escalation",
    "ev_electricity_price_escalation",
})


def drivers_from_snapshot(
    snapshot: dict, base: EVChargingDrivers | None = None
) -> EVChargingDrivers:
    """Resolve EV drivers from a workspace snapshot over defaults.

    Unknown/blank/invalid keys fall back to the generic reference drivers;
    explicit snapshot edits always win.  Percent-convention keys are
    converted to fractions.
    """
    base = base or GENERIC_EV_CHARGING_REFERENCE_DRIVERS
    if not isinstance(snapshot, dict):
        return base

    def _num(key, default, *, low=None, high=None):
        raw = snapshot.get(key)
        if raw in (None, ""):
            return default
        try:
            value = float(raw)
        except (TypeError, ValueError):
            return default
        if key in _EV_PERCENT_KEYS:
            value = value / 100.0
        if low is not None and value < low:
            return default
        if high is not None and value > high:
            return default
        return value

    y1 = _num("ev_full_load_hours_y1", base.full_load_hours_y1, low=0.0)
    y2 = _num("ev_full_load_hours_y2", base.full_load_hours_y2, low=0.0)
    stabilized = _num("ev_full_load_hours_stabilized", base.full_load_hours_stabilized, low=0.0)
    # The ramp is monotonically non-decreasing by authority; clamp defensively.
    y2 = max(y2, y1)
    stabilized = max(stabilized, y2)
    efficiency = _num("ev_charging_efficiency", base.charging_efficiency, low=0.01, high=1.0)
    return EVChargingDrivers(
        capacity_basis="INSTALLED_CHARGING_MW",
        full_load_hours_y1=y1,
        full_load_hours_y2=y2,
        full_load_hours_stabilized=stabilized,
        charging_price_eur_kwh=_num(
            "ev_charging_price_eur_kwh", base.charging_price_eur_kwh, low=0.0
        ),
        charging_price_escalation=_num(
            "ev_charging_price_escalation", base.charging_price_escalation
        ),
        charging_efficiency=efficiency,
        electricity_price_eur_kwh=_num(
            "ev_electricity_price_eur_kwh", base.electricity_price_eur_kwh, low=0.0
        ),
        electricity_price_escalation=_num(
            "ev_electricity_price_escalation", base.electricity_price_escalation
        ),
    )


def ev_driver_snapshot_values(drivers: EVChargingDrivers) -> dict:
    """Return snapshot-key → string-value pairs for the given drivers.

    Escalations are emitted as human-% values per the snapshot convention.
    """
    return {
        "ev_full_load_hours_y1": f"{drivers.full_load_hours_y1:.12g}",
        "ev_full_load_hours_y2": f"{drivers.full_load_hours_y2:.12g}",
        "ev_full_load_hours_stabilized": f"{drivers.full_load_hours_stabilized:.12g}",
        "ev_charging_price_eur_kwh": f"{drivers.charging_price_eur_kwh:.12g}",
        "ev_charging_price_escalation": f"{drivers.charging_price_escalation * 100:.12g}",
        "ev_charging_efficiency": f"{drivers.charging_efficiency:.12g}",
        "ev_electricity_price_eur_kwh": f"{drivers.electricity_price_eur_kwh:.12g}",
        "ev_electricity_price_escalation": f"{drivers.electricity_price_escalation * 100:.12g}",
    }


def _driver_ramp(drivers: EVChargingDrivers) -> tuple:
    return (
        drivers.full_load_hours_y1,
        drivers.full_load_hours_y2,
        drivers.full_load_hours_stabilized,
    )


def driver_effective_rate_eur_mwh(
    drivers: EVChargingDrivers, year_index: int
) -> float:
    """Effective per-MWh charging rate for operating year ``year_index``.

    The engine runs at stabilized full-load hours; the utilisation ramp is
    encoded exactly into this rate (hours(n)/stabilized × price × escalation).
    """
    ramp = _driver_ramp(drivers)
    clamped = min(max(int(year_index), 1), len(ramp))
    hours = ramp[clamped - 1]
    return (
        drivers.charging_price_eur_kwh * 1000.0
        * (hours / drivers.full_load_hours_stabilized)
        * ((1.0 + drivers.charging_price_escalation) ** (year_index - 1))
    )


def driver_electricity_expense_keur(
    drivers: EVChargingDrivers, capacity_mw: float, year_index: int
) -> float:
    """Derived B.08 electricity expense from the CURRENT drivers."""
    ramp = _driver_ramp(drivers)
    clamped = min(max(int(year_index), 1), len(ramp))
    delivered = capacity_mw * ramp[clamped - 1]
    purchased = delivered / drivers.charging_efficiency
    price = (
        drivers.electricity_price_eur_kwh * 1000.0
        * ((1.0 + drivers.electricity_price_escalation) ** (year_index - 1))
    )
    return purchased * price / 1000.0


def apply_ev_charging_runtime_adapter(pi, drivers: EVChargingDrivers | None = None):
    """Map EV Charging drivers onto canonical generic FINCO engine inputs.

    Pure function: returns a replaced ``ProjectInputs``; the financial engine
    is not aware of EV Charging and keeps full authority over financing, tax,
    statements and returns.  MUST run LAST for EV-specific economic identity
    so generic PPA/merchant compatibility fields can never silently override
    the EV authority.

    Mapping contract (documented, deterministic):
      - technical.operating_hours_p50 = stabilized full-load hours;
        availability/degradation are folded into the EFLH authority
        (V1: EFLH are net of availability → runtime stays neutral at 1.0).
      - revenue.market_prices_by_calendar_year_eur_mwh = the effective
        per-calendar-year charging-rate schedule (utilisation ramp encoded
        exactly), rebuilt from the CURRENT drivers on every call.
      - ppa_base_tariff / ppa_index re-state the CURRENT declared price
        authority (charging price EUR/MWh + escalation).
      - the B.08 electricity OpexItem is rebuilt exactly from the current
        drivers: y1 + Y2/Y3 sustained steps + escalation.
    """
    import dataclasses

    drivers = drivers or GENERIC_EV_CHARGING_REFERENCE_DRIVERS
    capacity = float(pi.technical.capacity_mw)
    horizon = max(1, int(pi.info.horizon_years))
    fc_year = int(pi.info.financial_close.year)

    technical = dataclasses.replace(
        pi.technical,
        yield_scenario="P_50",
        operating_hours_p50=drivers.full_load_hours_stabilized,
        operating_hours_p90_10y=drivers.full_load_hours_stabilized,
        pv_degradation=0.0,
        plant_availability=1.0,
        grid_availability=1.0,
    )
    # Calendar schedule rebuilt from CURRENT drivers (index 0 = FC-year
    # placeholder at the Y1 rate; operating year n lives at index n).
    cal_prices = [driver_effective_rate_eur_mwh(drivers, 1)]
    for op_year in range(1, horizon + 1):
        cal_prices.append(driver_effective_rate_eur_mwh(drivers, op_year))
    revenue = dataclasses.replace(
        pi.revenue,
        ppa_base_tariff=drivers.charging_price_eur_kwh * 1000.0,
        ppa_index=drivers.charging_price_escalation,
        ppa_term_years=float(horizon),
        ppa_production_share=0.0,
        market_prices_by_calendar_year_eur_mwh=tuple(cal_prices),
        market_price_calendar_start_year=fc_year,
        market_inflation=drivers.charging_price_escalation,
        balancing_cost_pv=0.0,
        balancing_cost_bess=0.0,
        balancing_cost_wind_eur_mwh=0.0,
        balancing_cost_eur_per_mwh=0.0,
        balancing_cost_schedule=None,
        co2_enabled=False,
        co2_price_eur=0.0,
        co2_certificate_price_eur_per_mwh=0.0,
        co2_sales_schedule=None,
        ppa_tariff_by_operating_period=(),
        first_merchant_operating_period_index=0,
    )

    def _elec(year_index: int) -> float:
        return driver_electricity_expense_keur(drivers, capacity, year_index)

    from finco_core.inputs import OpexItem
    elec_item = OpexItem(
        name="Electricity Procurement",
        y1_amount_keur=_elec(1),
        annual_inflation=drivers.electricity_price_escalation,
        step_changes=((2, _elec(2)), (3, _elec(3))),
    )
    new_opex = []
    for item in pi.opex:
        if str(getattr(item, "name", "")) == "Electricity Procurement":
            new_opex.append(elec_item)
        else:
            new_opex.append(item)
    if not any(str(getattr(i, "name", "")) == "Electricity Procurement" for i in new_opex):
        new_opex.append(elec_item)

    return dataclasses.replace(
        pi, technical=technical, revenue=revenue, opex=tuple(new_opex)
    )
