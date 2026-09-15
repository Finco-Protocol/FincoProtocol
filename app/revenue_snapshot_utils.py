"""Revenue snapshot materialization utilities.

Single source of truth for deriving canonical rev_* snapshot keys from a
live ProjectInputs / RevenueParams instance.

Used by:
- project_save_as_service.py  (new working-copy seed)
- migration paths              (old working-copy backfill)
- tests
"""
from __future__ import annotations

import json


def materialize_revenue_snapshot_defaults(revenue) -> dict:
    """Return a dict of canonical rev_* snapshot keys from a RevenueParams instance.

    All percentage values are in UI units (e.g. 2.0 for 2%), not engine fractions.
    The caller decides which keys to write (e.g. skip keys the user already set).

    Args:
        revenue: A RevenueParams instance (finco_core.inputs._models.RevenueParams).

    Returns:
        dict mapping snapshot key → string value (all values are strings, matching
        the snapshot storage convention).
    """
    result = {}

    # PPA base tariff
    if hasattr(revenue, "ppa_base_tariff") and revenue.ppa_base_tariff is not None:
        result["rev_ppa_base_tariff"] = str(revenue.ppa_base_tariff)

    # PPA escalation index — stored as UI % (engine uses fraction)
    if hasattr(revenue, "ppa_index") and revenue.ppa_index is not None:
        result["rev_ppa_index"] = str(round(revenue.ppa_index * 100.0, 6))

    # PPA term years
    if hasattr(revenue, "ppa_term_years") and revenue.ppa_term_years is not None:
        result["rev_ppa_term_years"] = str(int(revenue.ppa_term_years))

    # PPA production share — stored as UI % (engine uses fraction)
    if hasattr(revenue, "ppa_production_share") and revenue.ppa_production_share is not None:
        result["rev_ppa_production_share"] = str(round(revenue.ppa_production_share * 100.0, 6))

    # PPA indexation policy
    if hasattr(revenue, "ppa_indexation_start_policy") and revenue.ppa_indexation_start_policy is not None:
        result["rev_ppa_indexation_start_policy"] = str(revenue.ppa_indexation_start_policy)

    # PPA indexation start date (optional)
    if hasattr(revenue, "ppa_indexation_start_date") and revenue.ppa_indexation_start_date is not None:
        result["rev_ppa_indexation_start_date"] = revenue.ppa_indexation_start_date.isoformat()

    # Merchant balancing % — stored as UI % (engine uses fraction)
    if hasattr(revenue, "balancing_cost_pv") and revenue.balancing_cost_pv is not None:
        result["rev_merchant_balancing_pct"] = str(round(revenue.balancing_cost_pv * 100.0, 6))

    # Balancing EUR/MWh
    if hasattr(revenue, "balancing_cost_eur_per_mwh") and revenue.balancing_cost_eur_per_mwh is not None:
        result["rev_balancing_cost_eur_per_mwh"] = str(revenue.balancing_cost_eur_per_mwh)

    # CO2 enabled
    if hasattr(revenue, "co2_enabled") and revenue.co2_enabled is not None:
        result["rev_co2_enabled"] = "true" if revenue.co2_enabled else "false"

    # CO2 price EUR/MWh — prefer canonical field
    co2_price = None
    if hasattr(revenue, "co2_certificate_price_eur_per_mwh") and revenue.co2_certificate_price_eur_per_mwh:
        co2_price = revenue.co2_certificate_price_eur_per_mwh
    elif hasattr(revenue, "co2_price_eur") and revenue.co2_price_eur:
        co2_price = revenue.co2_price_eur
    if co2_price is not None:
        result["rev_co2_price_eur_mwh"] = str(co2_price)

    # Calendar-year merchant price curve
    if (
        hasattr(revenue, "market_price_calendar_start_year")
        and hasattr(revenue, "market_prices_by_calendar_year_eur_mwh")
        and revenue.market_price_calendar_start_year is not None
        and revenue.market_prices_by_calendar_year_eur_mwh
    ):
        start = revenue.market_price_calendar_start_year
        prices = revenue.market_prices_by_calendar_year_eur_mwh
        curve = [
            {"year": start + i, "price_eur_mwh": p}
            for i, p in enumerate(prices)
        ]
        result["rev_merchant_price_curve_json"] = json.dumps(curve)

    return result
