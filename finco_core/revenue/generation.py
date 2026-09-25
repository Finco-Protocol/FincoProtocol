"""Generation calculation - period-based production in MWh.

Matches Excel CF sheet row 21 formula:
    G21 = $B21 × G$7 × G$6 × G$20 × (1-G$19) × (1-Degradation)

Where:
- B21: capacity (MW)
- G7: day_fraction (period days / 365 or leap-year denominator)
- G6: operation flag (1 if operating, 0 if not)
- G20: operating hours for yield scenario
- G19: curtailment assumption
- Degradation: annual degradation factor

NOTE: This module contains PURE functions only.
Caching is handled in the app layer.

Authoritative location: finco_core.revenue.generation (V2-7).
Legacy location: domain.revenue.generation (compatibility shim).
"""
from typing import Sequence, Optional
from finco_core.inputs import TechnicalParams, ProjectInputs
from finco_core.engine.period_engine import PeriodEngine, PeriodMeta



def _is_p90_10y_scenario(yield_scenario: str) -> bool:
    """Normalize common P90-10y spellings used across Excel/app inputs."""
    normalized = str(yield_scenario).replace("_", "-").upper()
    return normalized in {"P90-10Y", "P90-10-Y", "P90 10Y"}


def _selected_operating_hours(tech: TechnicalParams, yield_scenario: str | None = None) -> float:
    """Return operating hours for the selected yield scenario."""
    selected = yield_scenario if yield_scenario is not None else tech.yield_scenario
    if _is_p90_10y_scenario(str(selected)):
        return tech.operating_hours_p90_10y
    return tech.operating_hours_p50


def period_generation(
    tech: TechnicalParams,
    periods: Sequence[PeriodMeta],
    year_index: int,
    yield_scenario: str | None = None,
) -> float:
    """Calculate annual generation (sum of all operating periods in one year)."""
    op_periods = [p for p in periods if p.is_operation and p.year_index == year_index]
    if not op_periods:
        return 0.0

    hours = _selected_operating_hours(tech, yield_scenario)
    availability = tech.plant_availability * tech.grid_availability
    degradation_factor = (1 - tech.pv_degradation) ** (year_index - 1)

    total_generation = 0.0
    for period in op_periods:
        generation = (
            tech.capacity_mw
            * hours
            * period.day_fraction
            * availability
            * degradation_factor
        )
        total_generation += generation

    return total_generation


def annual_generation_mwh(
    tech: TechnicalParams,
    year_index: int,
    yield_scenario: str | None = None,
) -> float:
    """Calculate annual generation in MWh."""
    hours = _selected_operating_hours(tech, yield_scenario)
    availability = tech.plant_availability * tech.grid_availability
    degradation = (1 - tech.pv_degradation) ** (year_index - 1)

    return tech.capacity_mw * hours * availability * degradation


def period_revenue(
    tech: TechnicalParams,
    period: PeriodMeta,
    ppa_tariff_eur_mwh: float,
    market_price_eur_mwh: Optional[float] = None,
    ppa_active: bool = True,
) -> float:
    """Calculate revenue for a single period."""
    if not period.is_operation:
        return 0.0

    hours = _selected_operating_hours(tech)
    availability = tech.plant_availability * tech.grid_availability
    degradation = (1 - tech.pv_degradation) ** (period.year_index - 1)

    generation_mwh = tech.capacity_mw * hours * period.day_fraction * availability * degradation

    if ppa_active:
        price = ppa_tariff_eur_mwh
    elif market_price_eur_mwh is not None:
        price = market_price_eur_mwh
    else:
        price = ppa_tariff_eur_mwh

    return generation_mwh * price / 1000


def full_generation_schedule(
    inputs: ProjectInputs,
    engine: PeriodEngine,
    yield_scenario: str | None = None,
) -> dict[int, float]:
    """Generate full schedule of period generation in MWh."""
    schedule = {}
    hours = _selected_operating_hours(inputs.technical, yield_scenario)

    for period in engine.periods():
        if not period.is_operation:
            schedule[period.index] = 0.0
            continue

        availability = inputs.technical.combined_availability
        degradation = (1 - inputs.technical.pv_degradation) ** (period.year_index - 1)

        generation = (
            inputs.technical.capacity_mw
            * hours
            * period.day_fraction
            * availability
            * degradation
        )

        schedule[period.index] = generation

    return schedule


def _period_energy_revenue_keur(
    *,
    generation_mwh: float,
    ppa_tariff: float,
    market_price: float,
    ppa_active: bool,
    ppa_share: float,
) -> float:
    """Return energy revenue for one period before balancing and certificates."""
    bounded_ppa_share = min(max(ppa_share, 0.0), 1.0)
    if ppa_active:
        ppa_generation = generation_mwh * bounded_ppa_share
        merchant_generation = generation_mwh - ppa_generation
        return (ppa_generation * ppa_tariff + merchant_generation * market_price) / 1000
    return generation_mwh * market_price / 1000


def _period_merchant_revenue_keur(
    *,
    generation_mwh: float,
    ppa_tariff: float,
    market_price: float,
    ppa_active: bool,
    ppa_share: float,
) -> tuple[float, float, float, float]:
    """Return (ppa_revenue_keur, gross_merchant_revenue_keur, ppa_mwh, merchant_mwh).

    Splits gross electricity revenue into PPA and merchant components for
    accurate merchant-only balancing deduction (Excel CF row 40).
    """
    bounded_ppa_share = min(max(ppa_share, 0.0), 1.0)
    if ppa_active:
        ppa_mwh = generation_mwh * bounded_ppa_share
        merchant_mwh = generation_mwh - ppa_mwh
    else:
        ppa_mwh = 0.0
        merchant_mwh = generation_mwh
    ppa_rev = ppa_mwh * ppa_tariff / 1000
    merchant_rev = merchant_mwh * market_price / 1000
    return ppa_rev, merchant_rev, ppa_mwh, merchant_mwh


def _certificate_revenue_keur(*, generation_mwh: float, enabled: bool, price_eur_mwh: float) -> float:
    """Return certificate/CO2 revenue for one period.

    Kept as a separate pure function because Excel workbooks often expose this
    as its own revenue row. Splitting it from energy revenue makes calibration
    deltas explainable and prevents certificate logic from being hidden inside
    tariff mechanics.
    """
    if not enabled:
        return 0.0
    return generation_mwh * price_eur_mwh / 1000


def revenue_decomposition_schedule(
    inputs: ProjectInputs,
    engine: PeriodEngine,
) -> dict[int, dict[str, float | bool]]:
    """Generate period-level revenue decomposition for calibration diagnostics."""
    decompositions: dict[int, dict[str, float | bool]] = {}
    generation_schedule = full_generation_schedule(inputs, engine)

    for period in engine.periods():
        generation_mwh = generation_schedule[period.index]
        if not period.is_operation:
            decompositions[period.index] = {
                "is_operation": False,
                "is_ppa_active": False,
                "generation_mwh": 0.0,
                "ppa_tariff_eur_mwh": 0.0,
                "market_price_eur_mwh": 0.0,
                "ppa_generation_mwh": 0.0,
                "merchant_generation_mwh": 0.0,
                "ppa_revenue_keur": 0.0,
                "gross_merchant_revenue_keur": 0.0,
                "gross_electricity_revenue_keur": 0.0,
                "electricity_revenue_keur": 0.0,
                "co2_certificate_revenue_keur": 0.0,
                "balancing_cost_keur": 0.0,
                "net_revenue_after_balancing_keur": 0.0,
                "energy_revenue_keur": 0.0,
                "balancing_cost_pv_keur": 0.0,
                "balancing_cost_wind_keur": 0.0,
                "co2_revenue_keur": 0.0,
                "co2_eur_mwh": 0.0,
                "balancing_cost_eur_mwh": 0.0,
                "revenue_keur": 0.0,
            }
            continue

        # Use per-period tariff schedule when available (policy-driven).
        tariff_pp = inputs.revenue.tariff_at_operating_period(period.operating_period_index)
        tariff = tariff_pp if tariff_pp is not None else inputs.revenue.tariff_at_year(period.year_index)
        # Calendar-year price lookup when schedule is present (matches Excel CF row 30);
        # falls back to operating-year lookup for projects without a CY schedule.
        period_end_year = period.end_date.year
        market_price = inputs.revenue.market_price_for_period(
            period_end_year=period_end_year,
            operating_year=period.year_index,
        )
        ppa_active = period.is_ppa_active
        first_merchant_idx = inputs.revenue.first_merchant_operating_period_index
        if first_merchant_idx is not None:
            ppa_active = period.operating_period_index < first_merchant_idx
        ppa_revenue_keur, gross_merchant_revenue_keur, ppa_generation_mwh, merchant_generation_mwh = (
            _period_merchant_revenue_keur(
                generation_mwh=generation_mwh,
                ppa_tariff=tariff,
                market_price=market_price,
                ppa_active=ppa_active,
                ppa_share=inputs.revenue.ppa_production_share,
            )
        )
        energy_revenue_keur = ppa_revenue_keur + gross_merchant_revenue_keur
        gross_electricity_revenue_keur = energy_revenue_keur
        # Phase 7: explicit certificate and balancing cost inputs (EUR/MWh)
        # Fallback priority (per PR #90 backward-compat requirement):
        #   schedule > co2_certificate_price_eur_per_mwh > co2_price_eur
        if inputs.revenue.co2_sales_schedule is not None:
            co2_eur_mwh = inputs.revenue.co2_sales_schedule.value_for_period(
                operating_period_index=period.operating_period_index,
                operating_year_index=period.operating_year_index,
                period_in_year=period.period_in_year,
            )
        elif inputs.revenue.co2_certificate_price_eur_per_mwh != 0.0:
            co2_eur_mwh = inputs.revenue.co2_certificate_price_eur_per_mwh
        else:
            co2_eur_mwh = inputs.revenue.co2_price_eur
        co2_certificate_revenue_keur = _certificate_revenue_keur(
            generation_mwh=generation_mwh,
            enabled=inputs.revenue.co2_enabled,
            price_eur_mwh=co2_eur_mwh,
        )
        # Phase 7: explicit balancing cost EUR/MWh
        # Fallback priority:
        #   schedule > balancing_cost_eur_per_mwh > balancing_cost_wind_eur_mwh
        if inputs.revenue.balancing_cost_schedule is not None:
            balancing_eur_mwh = inputs.revenue.balancing_cost_schedule.value_for_period(
                operating_period_index=period.operating_period_index,
                operating_year_index=period.operating_year_index,
                period_in_year=period.period_in_year,
            )
        elif inputs.revenue.balancing_cost_eur_per_mwh != 0.0:
            balancing_eur_mwh = inputs.revenue.balancing_cost_eur_per_mwh
        else:
            balancing_eur_mwh = inputs.revenue.balancing_cost_wind_eur_mwh
        # Balancing deduction applied ONLY to gross merchant electricity revenue,
        # matching Excel CF row 40: = -input_source_ref * Spot_Sales_kEUR.
        # PPA revenue and CO2 revenue are not included in the deduction basis.
        balancing_cost_pv_keur = gross_merchant_revenue_keur * inputs.revenue.balancing_cost_pv
        balancing_cost_wind_keur = generation_mwh * balancing_eur_mwh / 1000
        balancing_cost_keur = balancing_cost_pv_keur + balancing_cost_wind_keur
        # Net revenue after all deductions
        net_revenue_after_balancing_keur = (
            energy_revenue_keur
            - balancing_cost_pv_keur
            - balancing_cost_wind_keur
            + co2_certificate_revenue_keur
        )
        # Legacy total for backward compatibility
        revenue_keur = net_revenue_after_balancing_keur

        decompositions[period.index] = {
            "is_operation": True,
            "is_ppa_active": ppa_active,
            "generation_mwh": generation_mwh,
            "ppa_tariff_eur_mwh": tariff,
            "market_price_eur_mwh": market_price,
            # Merchant decomposition (Stage C2B — Excel CF row 30 / row 40 lineage)
            "ppa_generation_mwh": ppa_generation_mwh,
            "merchant_generation_mwh": merchant_generation_mwh,
            "ppa_revenue_keur": ppa_revenue_keur,
            "gross_merchant_revenue_keur": gross_merchant_revenue_keur,
            "gross_electricity_revenue_keur": gross_electricity_revenue_keur,
            # Phase 7: explicit revenue split
            "electricity_revenue_keur": energy_revenue_keur,
            "co2_certificate_revenue_keur": co2_certificate_revenue_keur,
            "balancing_cost_keur": balancing_cost_keur,
            "net_revenue_after_balancing_keur": net_revenue_after_balancing_keur,
            # Legacy aliases for backward compatibility
            "energy_revenue_keur": energy_revenue_keur,
            "co2_revenue_keur": co2_certificate_revenue_keur,
            "balancing_cost_pv_keur": balancing_cost_pv_keur,
            "balancing_cost_wind_keur": balancing_cost_wind_keur,
            "co2_eur_mwh": co2_eur_mwh,
            "balancing_cost_eur_mwh": balancing_eur_mwh,
            "revenue_keur": revenue_keur,
        }

    return decompositions


def full_revenue_schedule(
    inputs: ProjectInputs,
    engine: PeriodEngine,
) -> dict[int, float]:
    """Generate full schedule of period revenue in kEUR."""
    return {
        period_index: float(decomposition["revenue_keur"])
        for period_index, decomposition in revenue_decomposition_schedule(inputs, engine).items()
    }


__all__ = [
    "period_generation",
    "annual_generation_mwh",
    "period_revenue",
    "full_generation_schedule",
    "full_revenue_schedule",
    "revenue_decomposition_schedule",
]
