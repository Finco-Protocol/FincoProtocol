"""V4-7: BESS revenue and asset dashboard service.

Wraps domain/revenue/bess.py to produce per-period breakdowns and
lifetime summary data for the UI panels. Does NOT touch waterfall_core.py.
"""
from __future__ import annotations

from typing import Any


def _get_bess_params(proj: Any):
    """Return BessParams from project or None if BESS not configured."""
    tech = proj.technical
    if not getattr(tech, "bess_enabled", False):
        return None
    bess = getattr(tech, "bess", None)
    return bess


def build_bess_revenue_breakdown(proj: Any, result: Any) -> dict | None:
    """Build per-period BESS revenue breakdown for the UI panel.

    Returns None if project has no BESS or params not attached.
    """
    from domain.revenue.bess import bess_revenue_breakdown

    params = _get_bess_params(proj)
    if params is None:
        return None

    periods_data = []
    annual: dict[int, dict] = {}

    for p in result.periods:
        if not getattr(p, "is_operation", False):
            continue
        yi = getattr(p, "year_index", 1) or 1
        day_fraction = 0.5  # semestrial

        bd = bess_revenue_breakdown(params, yi, day_fraction)
        period_dict = {
            "period": p.period,
            "date": str(p.date) if p.date else None,
            "year_index": yi,
            "discharged_mwh": round(bd.discharged_mwh, 1),
            "arbitrage_keur": round(bd.arbitrage_revenue_keur, 1),
            "capacity_keur": round(bd.capacity_revenue_keur, 1),
            "ancillary_keur": round(bd.ancillary_revenue_keur, 1),
            "freq_reg_keur": round(bd.frequency_regulation_keur, 1),
            "reserve_keur": round(bd.reserve_market_keur, 1),
            "fixed_contracted_keur": round(bd.fixed_contracted_keur, 1),
            "augmentation_cost_keur": round(bd.augmentation_cost_keur, 1),
            "total_revenue_keur": round(bd.total_revenue_keur, 1),
            "net_revenue_keur": round(bd.net_revenue_keur, 1),
            "state_of_health_pct": round(bd.state_of_health * 100, 2),
        }
        periods_data.append(period_dict)

        # Aggregate annual
        if yi not in annual:
            annual[yi] = {k: 0.0 for k in [
                "discharged_mwh", "arbitrage_keur", "capacity_keur",
                "ancillary_keur", "freq_reg_keur", "reserve_keur",
                "fixed_contracted_keur", "augmentation_cost_keur",
                "total_revenue_keur", "net_revenue_keur",
            ]}
            annual[yi]["state_of_health_pct"] = period_dict["state_of_health_pct"]
        for k in annual[yi]:
            if k != "state_of_health_pct":
                annual[yi][k] = annual[yi][k] + period_dict[k]

    annual_list = [{"year": yi, **v} for yi, v in sorted(annual.items())]

    # Lifetime totals
    lifetime_arbitrage = sum(p["arbitrage_keur"] for p in periods_data)
    lifetime_capacity = sum(p["capacity_keur"] for p in periods_data)
    lifetime_ancillary = sum(p["ancillary_keur"] for p in periods_data)
    lifetime_freq_reg = sum(p["freq_reg_keur"] for p in periods_data)
    lifetime_reserve = sum(p["reserve_keur"] for p in periods_data)
    lifetime_fixed = sum(p["fixed_contracted_keur"] for p in periods_data)
    lifetime_net = sum(p["net_revenue_keur"] for p in periods_data)
    lifetime_discharge = sum(p["discharged_mwh"] for p in periods_data)

    return {
        "params": {
            "power_mw": params.power_mw,
            "energy_mwh": params.energy_mwh,
            "cycles_per_year": params.cycles_per_year,
            "round_trip_efficiency_pct": round(params.round_trip_efficiency * 100, 1),
            "availability_pct": round(params.availability * 100, 1),
            "annual_degradation_pct": round(params.annual_degradation * 100, 2),
            "arbitrage_spread_eur_mwh": params.arbitrage_spread_eur_mwh,
            "ancillary_revenue_eur_mw_year": params.ancillary_revenue_eur_mw_year,
            "capacity_revenue_eur_mw_year": params.capacity_revenue_eur_mw_year,
            "frequency_regulation_eur_mw_year": params.frequency_regulation_eur_mw_year,
            "reserve_market_eur_mw_year": params.reserve_market_eur_mw_year,
            "fixed_contracted_eur_mw_year": params.fixed_contracted_eur_mw_year,
            "depth_of_discharge_pct": round(params.depth_of_discharge * 100, 1),
            "cycle_life": params.cycle_life,
            "replacement_year": params.replacement_year,
        },
        "periods": periods_data,
        "annual": annual_list,
        "lifetime": {
            "arbitrage_keur": round(lifetime_arbitrage, 0),
            "capacity_keur": round(lifetime_capacity, 0),
            "ancillary_keur": round(lifetime_ancillary, 0),
            "freq_reg_keur": round(lifetime_freq_reg, 0),
            "reserve_keur": round(lifetime_reserve, 0),
            "fixed_contracted_keur": round(lifetime_fixed, 0),
            "net_revenue_keur": round(lifetime_net, 0),
            "discharged_mwh": round(lifetime_discharge, 0),
        },
    }


def build_bess_asset_dashboard(proj: Any, result: Any) -> dict | None:
    """Build battery asset dashboard data (capacity, SoH, degradation, augmentation).

    Returns None if project has no BESS.
    """
    from domain.revenue.bess import bess_state_of_health, bess_effective_energy_mwh

    params = _get_bess_params(proj)
    if params is None:
        return None

    horizon = proj.info.horizon_years
    years = list(range(1, horizon + 1))

    soh_curve = []
    capacity_curve = []
    for yi in years:
        soh = bess_state_of_health(params, yi)
        eff_e = bess_effective_energy_mwh(params, yi)
        soh_curve.append({"year": yi, "soh_pct": round(soh * 100, 2)})
        capacity_curve.append({"year": yi, "energy_mwh": round(eff_e, 2), "power_mw": params.power_mw})

    # Augmentation event
    augmentation_events = []
    if params.replacement_year > 0 and params.augmentation_capex_keur > 0:
        augmentation_events.append({
            "year": params.replacement_year,
            "capex_keur": params.augmentation_capex_keur,
            "label": f"Battery Augmentation Y{params.replacement_year}",
        })

    # Estimated cycle consumption
    final_soh = bess_state_of_health(params, horizon)

    return {
        "params_summary": {
            "rated_power_mw": params.power_mw,
            "rated_energy_mwh": params.energy_mwh,
            "cycle_life": params.cycle_life,
            "annual_degradation_pct": round(params.annual_degradation * 100, 2),
            "depth_of_discharge_pct": round(params.depth_of_discharge * 100, 1),
            "replacement_year": params.replacement_year,
        },
        "soh_curve": soh_curve,
        "capacity_curve": capacity_curve,
        "augmentation_events": augmentation_events,
        "end_of_life": {
            "final_soh_pct": round(final_soh * 100, 2),
            "final_energy_mwh": round(bess_effective_energy_mwh(params, horizon), 2),
        },
    }
