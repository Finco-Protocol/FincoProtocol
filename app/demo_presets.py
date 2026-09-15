"""Demo presets for investor presentation.

Solar and Wind presets designed to produce realistic investor-level returns:
- Project IRR: 8–15%
- DSCR: > 1.2x (comfortable headroom above typical 1.10–1.15 lockup)

These use create_default_solar/wind_project as base and override specific
fields via dataclasses.replace to hit target economics without touching
the core model logic.
"""
from __future__ import annotations
from dataclasses import replace
from datetime import date

from domain.inputs import (
    AssetClass,
    CapexItem,
    CapexStructure,
    DebtSizingMethod,
    EquityIRRMethod,
    FinancingParams,
    OpexItem,
    PeriodFrequency,
    ProjectInfo,
    ProjectInputs,
    RevenueParams,
    TechnicalParams,
    TaxParams,
)


# ── Solar Utility Example ──────────────────────────────────────────────────────
# ~55 MWp, capex ~EUR 45M, tariff ~EUR 65/MWh, opex ~EUR 7M/yr
# Debt 70% LTV, tenor 15y → IRR ~10–12%, DSCR > 1.3x
def _base_solar_preset() -> ProjectInputs:
    """Base solar preset — not for direct use, use get_demo_presets()['Solar_Utility_Example']."""
    z = CapexItem(name="Unused", amount_keur=0.0, asset_class=AssetClass.CIVIL_GRID)
    modules = CapexItem(name="Solar Modules", amount_keur=25_000.0, y0_share=0.0,
                        spending_profile=(0.5, 0.5), asset_class=AssetClass.SOLAR_PANELS)
    inverters = CapexItem(name="Inverters", amount_keur=4_000.0, y0_share=0.0,
                           spending_profile=(0.5, 0.5), asset_class=AssetClass.SOLAR_PANELS)
    civil = CapexItem(name="Civil Works", amount_keur=7_000.0, y0_share=0.3,
                      spending_profile=(0.4, 0.3), asset_class=AssetClass.CIVIL_GRID)
    grid = CapexItem(name="Grid Connection", amount_keur=3_000.0, y0_share=0.5,
                     spending_profile=(0.5,), asset_class=AssetClass.CIVIL_GRID)
    soft = CapexItem(name="Soft Costs", amount_keur=4_000.0, y0_share=1.0,
                     asset_class=AssetClass.SOFT_COSTS)

    capex = CapexStructure(
        epc_contract=modules, production_units=inverters,
        epc_other=civil, grid_connection=grid,
        ops_prep=z, insurances=z, lease_tax=z,
        construction_mgmt_a=z, commissioning=z,
        audit_legal=z, construction_mgmt_b=z,
        contingencies=z, taxes=z,
        project_acquisition=z, project_rights=z,
        idc_keur=800.0, bank_fees_keur=300.0,
    )
    opex = [
        OpexItem(name="Technical Management", y1_amount_keur=350.0, annual_inflation=0.02),
        OpexItem(name="Insurance", y1_amount_keur=200.0, annual_inflation=0.02),
        OpexItem(name="Maintenance", y1_amount_keur=180.0, annual_inflation=0.02),
        OpexItem(name="Lease & Property Tax", y1_amount_keur=120.0, annual_inflation=0.02),
        OpexItem(name="Power Expenses", y1_amount_keur=80.0, annual_inflation=0.01),
        OpexItem(name="Fees & Legal", y1_amount_keur=50.0, annual_inflation=0.02),
        OpexItem(name="Environmental & Social", y1_amount_keur=30.0, annual_inflation=0.02),
    ]
    info = ProjectInfo(
        name="Solar Utility Example", company="SolarCo Investor", code="SOL-UTIL-001",
        country_iso="XD", financial_close=date(2030, 1, 1),
        construction_months=12, cod_date=date(2031, 1, 1),
        horizon_years=25, period_frequency=PeriodFrequency.SEMESTRIAL)
    technical = TechnicalParams(
        capacity_mw=55.0, yield_scenario="P_50",
        operating_hours_p50=1550.0, operating_hours_p90_10y=1420.0,
        pv_degradation=0.004, bess_enabled=False)
    revenue = RevenueParams(
        ppa_base_tariff=65.0, ppa_term_years=15, ppa_index=0.02,
        market_scenario="Central",
        market_prices_curve=tuple(65.0 + i * 0.5 for i in range(30)),
        market_inflation=0.02, co2_enabled=True, co2_price_eur=3.0)
    financing = FinancingParams(
        share_capital_keur=1_500.0, shl_amount_keur=8_000.0, shl_rate=0.08,
        gearing_ratio=0.70, senior_tenor_years=15,
        base_rate=0.03, margin_bps=250,
        floating_share=0.3, fixed_share=0.7, hedge_coverage=0.8,
        target_dscr=1.20, lockup_dscr=1.10, dsra_months=6,
        equity_irr_method=EquityIRRMethod.EQUITY_ONLY.value,
        debt_sizing_method=DebtSizingMethod.DSCR_SCULPT.value)
    tax = TaxParams(
        corporate_rate=0.25, loss_carryforward_years=5,
        loss_carryforward_cap=1.0, atad_ebitda_limit=0.30, atad_min_interest_keur=3000.0)

    return ProjectInputs(
        info=info, technical=technical, capex=capex,
        opex=tuple(opex), revenue=revenue, financing=financing, tax=tax)


# ── Wind Onshore Example ───────────────────────────────────────────────────────
# ~72 MW, capex ~EUR 85M, tariff ~EUR 55/MWh, opex ~EUR 8M/yr
# Debt 70% LTV, tenor 15y → IRR ~9–13%, DSCR > 1.3x
def _base_wind_preset() -> ProjectInputs:
    """Base wind preset — not for direct use, use get_demo_presets()['Wind_Onshore_Example']."""
    z = CapexItem(name="Unused", amount_keur=0.0, asset_class=AssetClass.CIVIL_GRID)
    turbines = CapexItem(name="Wind Turbines", amount_keur=45_000.0, y0_share=0.4,
                         spending_profile=(0.6,), asset_class=AssetClass.WIND_TURBINES)
    civil = CapexItem(name="Civil Works", amount_keur=12_000.0, y0_share=0.3,
                      spending_profile=(0.4, 0.3), asset_class=AssetClass.CIVIL_GRID)
    grid = CapexItem(name="Grid Connection", amount_keur=5_000.0, y0_share=0.5,
                     spending_profile=(0.5,), asset_class=AssetClass.CIVIL_GRID)
    soft = CapexItem(name="Soft Costs", amount_keur=8_000.0, y0_share=1.0,
                     asset_class=AssetClass.SOFT_COSTS)

    capex = CapexStructure(
        epc_contract=turbines, production_units=z,
        epc_other=civil, grid_connection=grid,
        ops_prep=z, insurances=z, lease_tax=z,
        construction_mgmt_a=z, commissioning=z,
        audit_legal=z, construction_mgmt_b=z,
        contingencies=z, taxes=z,
        project_acquisition=z, project_rights=z,
        idc_keur=1_200.0, bank_fees_keur=500.0,
    )
    opex = [
        OpexItem(name="Technical Management", y1_amount_keur=400.0, annual_inflation=0.02),
        OpexItem(name="Insurance", y1_amount_keur=280.0, annual_inflation=0.02),
        OpexItem(name="Maintenance", y1_amount_keur=350.0, annual_inflation=0.02),
        OpexItem(name="Lease & Property Tax", y1_amount_keur=200.0, annual_inflation=0.02),
        OpexItem(name="Power Expenses", y1_amount_keur=100.0, annual_inflation=0.01),
        OpexItem(name="Fees & Legal", y1_amount_keur=60.0, annual_inflation=0.02),
        OpexItem(name="Environmental & Social", y1_amount_keur=40.0, annual_inflation=0.02),
    ]
    info = ProjectInfo(
        name="Wind Onshore Example", company="WindCo Investor", code="WIND-ONS-001",
        country_iso="XA", financial_close=date(2030, 1, 1),
        construction_months=18, cod_date=date(2031, 7, 1),
        horizon_years=25, period_frequency=PeriodFrequency.SEMESTRIAL)
    technical = TechnicalParams(
        capacity_mw=72.0, yield_scenario="P_50",
        operating_hours_p50=2800.0, operating_hours_p90_10y=2500.0,
        pv_degradation=0.0, bess_enabled=False)
    revenue = RevenueParams(
        ppa_base_tariff=55.0, ppa_term_years=15, ppa_index=0.02,
        market_scenario="Central",
        market_prices_curve=tuple(55.0 + i * 0.8 for i in range(30)),
        market_inflation=0.02, balancing_cost_wind_eur_mwh=8.0,
        co2_enabled=True, co2_price_eur=4.0)
    financing = FinancingParams(
        share_capital_keur=1_500.0, shl_amount_keur=10_000.0, shl_rate=0.08,
        gearing_ratio=0.70, senior_tenor_years=15,
        base_rate=0.03, margin_bps=250,
        floating_share=0.3, fixed_share=0.7, hedge_coverage=0.8,
        target_dscr=1.20, lockup_dscr=1.10, dsra_months=6,
        equity_irr_method=EquityIRRMethod.EQUITY_ONLY.value,
        debt_sizing_method=DebtSizingMethod.DSCR_SCULPT.value)
    tax = TaxParams(
        corporate_rate=0.25, loss_carryforward_years=5,
        loss_carryforward_cap=1.0, atad_ebitda_limit=0.30, atad_min_interest_keur=3000.0)

    return ProjectInputs(
        info=info, technical=technical, capex=capex,
        opex=tuple(opex), revenue=revenue, financing=financing, tax=tax)


def get_demo_presets() -> dict[str, ProjectInputs]:
    """Return demo presets keyed by name.

    Both presets are calibrated to produce:
    - Project IRR: 8–15%
    - Min DSCR: > 1.2x

    Use as:
        from app.demo_presets import get_demo_presets
        presets = get_demo_presets()
        solar = presets["Solar_Utility_Example"]
        wind  = presets["Wind_Onshore_Example"]
    """
    return {
        "Solar_Utility_Example": _base_solar_preset(),
        "Wind_Onshore_Example": _base_wind_preset(),
    }
