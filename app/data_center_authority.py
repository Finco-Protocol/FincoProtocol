"""Generic Data Center reference authority — drivers, canonical identities, runtime adapter.

This module is the single application-layer authority for the Generic Data
Center Reference V1 economics.  It contains:

1.  The typed synthetic public driver set (``DataCenterDrivers``) — SYNTHETIC
    PUBLIC GENERIC DATA, explicitly not a market average.
2.  The canonical economic identities:
      - Core capacity revenue (kEUR) = IT MW × 12 × price(EUR/kW/month) × occupancy
      - Facility power (MW) = IT load MW × occupancy × PUE
      - Annual electricity cost (kEUR) = facility MWh × price(EUR/MWh) / 1000
3.  The deterministic runtime adapter that maps Data Center drivers onto the
    existing generic FINCO engine inputs (market-price curve for the
    occupancy/escalation revenue path; ``OpexItem.step_changes`` for the
    derived B.08 power expense).  The financial engine remains untouched.

All values are synthetic.  No client workbook, market database, or
jurisdiction-specific calibration is used or implied.
"""
from __future__ import annotations

from dataclasses import dataclass, replace

# Snapshot keys carrying user-editable Data Center drivers.  They are stored
# verbatim in the workspace snapshot and resolved by ``drivers_from_snapshot``.
DC_DRIVER_SNAPSHOT_KEYS: tuple[str, ...] = (
    "dc_service_price_eur_kw_month",
    "dc_revenue_escalation",
    "dc_occupancy_y1",
    "dc_occupancy_y2",
    "dc_occupancy_stabilized",
    "dc_pue",
    "dc_electricity_price_eur_mwh",
    "dc_electricity_price_escalation",
    "dc_availability",
    "dc_contract_term_years",
)

# Canonical OPEX item name for the derived power expense (routes to B.08 in
# app.v2.opex_assembly._OPEX_NAME_TO_CODE).
DC_POWER_OPEX_ITEM_NAME = "Power Expenses"

# Deterministic occupancy ramp mapping onto the canonical period axis:
# operating year 1 → occupancy_y1, year 2 → occupancy_y2, year 3+ →
# stabilized_occupancy.  Both semestral periods of an operating year use that
# year's occupancy value (annual authority mapped 1:1 onto each period pair).
def occupancy_for_year(drivers: "DataCenterDrivers", operating_year: int) -> float:
    if operating_year <= 1:
        return drivers.occupancy_y1
    if operating_year <= 2:
        return drivers.occupancy_y2
    return drivers.stabilized_occupancy


@dataclass(frozen=True)
class DataCenterDrivers:
    """Synthetic public generic Data Center operating/revenue drivers.

    ``capacity_basis`` is always IT_LOAD_MW: ``capacity_mw`` for a Data
    Center project means IT load capacity, never generation capacity.
    """
    capacity_basis: str = "IT_LOAD_MW"
    service_price_eur_kw_month: float = 175.0
    revenue_escalation: float = 0.02
    occupancy_y1: float = 0.55
    occupancy_y2: float = 0.70
    stabilized_occupancy: float = 0.85
    pue: float = 1.30
    electricity_price_eur_mwh: float = 70.0
    electricity_price_escalation: float = 0.02
    availability: float = 1.0
    contract_term_years: float = 10.0


GENERIC_DATA_CENTER_REFERENCE_DRIVERS = DataCenterDrivers()

# Sponsor equity is proportional to IT capacity (same convention as CAPEX and
# non-power OPEX): 4,000 kEUR share capital per MW IT at the 20 MW reference
# (80,000 kEUR total).  The SHL residual and senior debt remain derived by the
# existing Sources & Uses / DSCR-sculpting authority; this keeps the sponsor
# funding mix debt-serviceable across seeded capacities (a fixed absolute
# equity amount leaves the SHL sweep under-water at larger capacities).
DC_SHARE_CAPITAL_KEUR_PER_MW = 4_000.0

# Base contracted service period; after the base term V1 continues service
# revenue under the same indexed convention (deterministic policy A — the
# revenue curve simply continues, there is no merchant curve and no
# terminal-value assumption).
DC_POST_TERM_POLICY = "CONTINUE_INDEXED_SERVICE_REVENUE"

_CURVE_YEARS = 30  # deterministic explicit horizon, same convention as Solar/Wind


# Snapshot-key storage convention: rate drivers (occupancy, escalations,
# availability) are persisted as UI PERCENT values (55 means 55%), matching
# the workbook registry PCT convention.  ``drivers_from_snapshot`` converts
# them to fractions; ``dc_driver_snapshot_values`` converts fractions back.
_PERCENT_KEYS = frozenset({
    "dc_occupancy_y1",
    "dc_occupancy_y2",
    "dc_occupancy_stabilized",
    "dc_revenue_escalation",
    "dc_electricity_price_escalation",
    "dc_availability",
})


def drivers_from_snapshot(
    snapshot: dict, base: DataCenterDrivers | None = None
) -> DataCenterDrivers:
    """Resolve Data Center drivers from a workspace snapshot over defaults.

    Unknown/blank keys fall back to the generic reference drivers; explicit
    snapshot edits always win (same precedence contract as the seed profile).
    Percent-convention keys are converted to fractions.
    """
    base = base or GENERIC_DATA_CENTER_REFERENCE_DRIVERS
    if not isinstance(snapshot, dict):
        return base

    def _num(key: str, default: float, *, low: float | None = None, high: float | None = None) -> float:
        raw = snapshot.get(key)
        if raw in (None, ""):
            return default
        try:
            value = float(raw)
        except (TypeError, ValueError):
            return default
        if key in _PERCENT_KEYS:
            value = value / 100.0
        if low is not None and value < low:
            return default
        if high is not None and value > high:
            return default
        return value

    occupancy_y1 = _num("dc_occupancy_y1", base.occupancy_y1, low=0.0, high=1.0)
    occupancy_y2 = _num("dc_occupancy_y2", base.occupancy_y2, low=0.0, high=1.0)
    stabilized = _num("dc_occupancy_stabilized", base.stabilized_occupancy, low=0.0, high=1.0)
    # The ramp is monotonically non-decreasing by authority; clamp defensively.
    occupancy_y2 = max(occupancy_y2, occupancy_y1)
    stabilized = max(stabilized, occupancy_y2)
    return DataCenterDrivers(
        capacity_basis="IT_LOAD_MW",
        service_price_eur_kw_month=_num(
            "dc_service_price_eur_kw_month", base.service_price_eur_kw_month, low=0.0
        ),
        revenue_escalation=_num("dc_revenue_escalation", base.revenue_escalation),
        occupancy_y1=occupancy_y1,
        occupancy_y2=occupancy_y2,
        stabilized_occupancy=stabilized,
        pue=_num("dc_pue", base.pue, low=1.0),
        electricity_price_eur_mwh=_num(
            "dc_electricity_price_eur_mwh", base.electricity_price_eur_mwh, low=0.0
        ),
        electricity_price_escalation=_num(
            "dc_electricity_price_escalation", base.electricity_price_escalation
        ),
        availability=_num("dc_availability", base.availability, low=0.0, high=1.0),
        contract_term_years=_num(
            "dc_contract_term_years", base.contract_term_years, low=0.0
        ),
    )


def dc_driver_snapshot_values(drivers: DataCenterDrivers) -> dict[str, str]:
    """Return snapshot-key → string-value pairs for the given drivers.

    Used when seeding a Data Center working copy so the driver authority is
    persisted explicitly (never buried in comments).  Rate drivers use the
    percent snapshot convention (55 means 55%).
    """
    return {
        "dc_service_price_eur_kw_month": f"{drivers.service_price_eur_kw_month:.12g}",
        "dc_revenue_escalation": f"{drivers.revenue_escalation * 100.0:.12g}",
        "dc_occupancy_y1": f"{drivers.occupancy_y1 * 100.0:.12g}",
        "dc_occupancy_y2": f"{drivers.occupancy_y2 * 100.0:.12g}",
        "dc_occupancy_stabilized": f"{drivers.stabilized_occupancy * 100.0:.12g}",
        "dc_pue": f"{drivers.pue:.12g}",
        "dc_electricity_price_eur_mwh": f"{drivers.electricity_price_eur_mwh:.12g}",
        "dc_electricity_price_escalation": f"{drivers.electricity_price_escalation * 100.0:.12g}",
        "dc_availability": f"{drivers.availability * 100.0:.12g}",
        "dc_contract_term_years": f"{drivers.contract_term_years:.12g}",
    }


def core_capacity_revenue_keur(
    *, capacity_mw: float, service_price_eur_kw_month: float, occupancy: float
) -> float:
    """Canonical identity: IT MW × 1,000 kW/MW × 12 months × EUR/kW/month × occupancy, in kEUR."""
    return float(capacity_mw) * 1_000.0 * 12.0 * float(service_price_eur_kw_month) * float(occupancy) / 1_000.0


def facility_power_mw(*, it_load_mw: float, occupancy: float, pue: float) -> float:
    """Canonical identity: facility power = IT load × occupancy × PUE."""
    return float(it_load_mw) * float(occupancy) * float(pue)


def annual_power_cost_keur(
    *, capacity_mw: float, occupancy: float, pue: float, electricity_price_eur_mwh: float
) -> float:
    """Canonical identity: facility MWh (= MW × 8,760) × EUR/MWh, in kEUR."""
    facility_mw = facility_power_mw(it_load_mw=capacity_mw, occupancy=occupancy, pue=pue)
    return facility_mw * 8_760.0 * float(electricity_price_eur_mwh) / 1_000.0


def equivalent_market_price_eur_mwh(
    *, service_price_eur_kw_month: float, occupancy: float
) -> float:
    """Return the EUR/MWh price that reproduces the capacity-revenue identity.

    The engine computes revenue as MWh × EUR/MWh with annual generation of
    capacity_mw × 8,760 MWh (full-time IT-load basis, availability/degradation
    folded into the occupancy authority).  Solving
        capacity_mw × 8,760 × price / 1000 = capacity_mw × 12 × P × occupancy
    gives price = 12,000 × P × occupancy / 8,760 EUR/MWh.
    """
    return 12_000.0 * float(service_price_eur_kw_month) * float(occupancy) / 8_760.0


def equivalent_market_curve(drivers: DataCenterDrivers, years: int = _CURVE_YEARS) -> tuple[float, ...]:
    """Deterministic nominal EUR/MWh curve encoding the occupancy ramp and escalation.

    Year y (1-based): 12,000 × P × occupancy_y × (1 + escalation)^(y-1) / 8,760.
    After the ramp stabilizes the curve compounds at the revenue escalation,
    matching the engine's ``market_inflation`` extrapolation convention used by
    the Solar/Wind synthetic references (explicit entries, no hidden growth).
    """
    values: list[float] = []
    for year in range(1, years + 1):
        occ = occupancy_for_year(drivers, year)
        nominal = equivalent_market_price_eur_mwh(
            service_price_eur_kw_month=drivers.service_price_eur_kw_month,
            occupancy=occ,
        ) * (1.0 + drivers.revenue_escalation) ** (year - 1)
        values.append(nominal)
    return tuple(values)


def power_step_changes(
    drivers: DataCenterDrivers, capacity_mw: float, horizon_years: int
) -> tuple[tuple[int, float], ...]:
    """Derived B.08 power expense per operating year as ``OpexItem.step_changes``.

    Year y: IT MW × occupancy_y × PUE × 8,760 h × EUR/MWh × (1 + esc)^(y-1),
    in kEUR.  Electricity-price escalation is explicit in the steps, so the
    item's ``annual_inflation`` is set to 0 when this authority is applied.
    """
    steps: list[tuple[int, float]] = []
    for year in range(1, max(1, int(horizon_years)) + 1):
        occ = occupancy_for_year(drivers, year)
        cost = annual_power_cost_keur(
            capacity_mw=capacity_mw,
            occupancy=occ,
            pue=drivers.pue,
            electricity_price_eur_mwh=drivers.electricity_price_eur_mwh,
        ) * (1.0 + drivers.electricity_price_escalation) ** (year - 1)
        steps.append((year, cost))
    return tuple(steps)


def apply_data_center_runtime_adapter(pi, drivers: DataCenterDrivers | None = None):
    """Map Data Center drivers onto canonical generic FINCO engine inputs.

    Pure function: returns a replaced ``ProjectInputs``; the financial engine
    is not aware of Data Center and keeps its full authority over financing,
    tax, statements and returns.

    Mapping contract (documented, deterministic):
      - technical.operating_hours_p50 = 8,760 (full-time IT-load basis);
        availability/degradation are folded into the occupancy authority.
      - revenue.market_prices_curve = equivalent EUR/MWh curve (occupancy ramp
        + escalation); market_inflation = revenue escalation (curve is
        explicit per year, inflation only documents the convention).
      - ppa_production_share = 0 (all contracted service revenue rides the
        synthetic indexed service-price curve; no PPA abstraction exists),
        balancing and CO2 disabled.
      - the B.08 power item receives exact per-year step_changes derived from
        IT MW × occupancy × PUE × 8,760 × electricity price.
    """
    drivers = drivers or GENERIC_DATA_CENTER_REFERENCE_DRIVERS
    horizon = max(1, int(pi.info.horizon_years))
    curve = equivalent_market_curve(drivers)

    technical = replace(
        pi.technical,
        yield_scenario="P_50",
        operating_hours_p50=8_760.0,
        operating_hours_p90_10y=8_760.0,
        pv_degradation=0.0,
        plant_availability=drivers.availability,
        grid_availability=1.0,
    )
    revenue = replace(
        pi.revenue,
        ppa_base_tariff=equivalent_market_price_eur_mwh(
            service_price_eur_kw_month=drivers.service_price_eur_kw_month,
            occupancy=drivers.stabilized_occupancy,
        ),
        ppa_term_years=float(drivers.contract_term_years),
        ppa_index=drivers.revenue_escalation,
        ppa_production_share=0.0,
        market_prices_curve=curve,
        market_inflation=drivers.revenue_escalation,
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
        first_merchant_operating_period_index=None,
    )

    steps = power_step_changes(drivers, float(pi.technical.capacity_mw), horizon)
    new_opex: list = []
    for item in pi.opex:
        if str(getattr(item, "name", "")) == DC_POWER_OPEX_ITEM_NAME:
            new_opex.append(replace(
                item,
                y1_amount_keur=steps[0][1] if steps else float(item.y1_amount_keur),
                annual_inflation=0.0,
                step_changes=steps,
                percentage_of_opex=0.0,
            ))
        else:
            new_opex.append(item)

    # Sponsor equity scales with IT capacity (see DC_SHARE_CAPITAL_KEUR_PER_MW);
    # senior debt and the SHL residual remain engine/S&U-derived.
    capacity = float(pi.technical.capacity_mw)
    share_capital_keur = capacity * DC_SHARE_CAPITAL_KEUR_PER_MW
    financing = replace(
        pi.financing,
        share_capital_keur=share_capital_keur,
        # Legacy placeholder amounts; G2A derives the runtime SHL principal.
        shl_amount_keur=share_capital_keur * 0.5,
        clean_shl_principal_keur=share_capital_keur * 0.5,
    )

    return replace(
        pi,
        technical=technical,
        revenue=revenue,
        opex=tuple(new_opex),
        financing=financing,
    )


def is_data_center_snapshot(snapshot: dict) -> bool:
    """Return True when a workspace snapshot belongs to a Data Center project."""
    if not isinstance(snapshot, dict):
        return False
    template_source = str(snapshot.get("template_source") or "").lower()
    if template_source == "generic_data_center_reference":
        return True
    project_type = str(snapshot.get("project_type") or "").strip().lower()
    if project_type in {"data center", "data_center", "datacenter"}:
        return True
    return any(key in snapshot for key in DC_DRIVER_SNAPSHOT_KEYS)


__all__ = [
    "DataCenterDrivers",
    "DC_DRIVER_SNAPSHOT_KEYS",
    "DC_POWER_OPEX_ITEM_NAME",
    "DC_POST_TERM_POLICY",
    "GENERIC_DATA_CENTER_REFERENCE_DRIVERS",
    "annual_power_cost_keur",
    "apply_data_center_runtime_adapter",
    "core_capacity_revenue_keur",
    "dc_driver_snapshot_values",
    "drivers_from_snapshot",
    "equivalent_market_curve",
    "equivalent_market_price_eur_mwh",
    "facility_power_mw",
    "is_data_center_snapshot",
    "occupancy_for_year",
    "power_step_changes",
]
