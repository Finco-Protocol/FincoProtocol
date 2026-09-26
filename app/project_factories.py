"""Synthetic project factories for FINCO Protocol public reference models.

All reference models in this module are fictional. They use synthetic sponsors,
user-assigned market codes, and round-number assumptions. No client workbook,
project, company, or jurisdiction-specific calibration data is included.
"""
from __future__ import annotations

import math
from dataclasses import replace
from datetime import date
from dateutil.relativedelta import relativedelta

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
    SHLRepaymentMethod,
    TaxParams,
    TechnicalParams,
)
from domain.revenue.bess import BessParams
from finco_core.inputs._models import DebtSizingMode, GearingBasisMode, SponsorFundingMode
from finco_core.inputs.senior_rate_schedule import (
    SeniorDayCountConvention,
    SeniorDebtInterestConfig,
    SeniorRateMode,
    SeniorRateSchedule,
)
from financial_engine.financial_statements.contracts import (
    AccountingPolicyAuthority,
    AccountingPolicyConfig,
)

# Generic clean accounting policy. Public reference models deliberately avoid
# jurisdiction- or client-specific accounting authority claims.
_GENERIC_CLEAN_ACCOUNTING_POLICY = AccountingPolicyConfig(
    preconstruction_retained_earnings_keur=0.0,
    preconstruction_retained_earnings_authority=AccountingPolicyAuthority.GENERIC_FINCO_POLICY,
    opening_re_authority=AccountingPolicyAuthority.GENERIC_FINCO_POLICY,
    shl_construction_accounting_authority=AccountingPolicyAuthority.GENERIC_FINCO_POLICY,
    book_capitalization_authority=AccountingPolicyAuthority.UNRESOLVED,
    book_capitalization_components={},
    legal_reserve_policy=None,
    legal_reserve_authority=AccountingPolicyAuthority.UNRESOLVED,
    cash_interest_authority=AccountingPolicyAuthority.UNRESOLVED,
)

def _generic_clean_senior_interest_config(
    *,
    annual_all_in_rate: float,
    tenor_years: int,
) -> SeniorDebtInterestConfig:
    """Explicit clean senior-rate contract for fictional generic projects."""
    return SeniorDebtInterestConfig(
        enabled=True,
        rate_schedule=SeniorRateSchedule(
            mode=SeniorRateMode.EXPLICIT_ALL_IN_SCHEDULE,
            explicit_all_in_rates=(annual_all_in_rate,) * (tenor_years * 2),
        ),
        day_count=SeniorDayCountConvention.ACT_360,
    )

def create_default_solar_project(
    capacity_mw: float = 50.0,
    horizon_years: int = 20,
    construction_months: int = 12,
) -> ProjectInputs:
    """Test 1 — Solar: fictional utility-scale solar project for demos and tests.

    50 MW solar PV, EUR 50/MWh PPA, 20-year horizon. Entirely fictional —
    no real company, no real project, no Excel calibration data.
    """
    z = CapexItem(name="Unused", amount_keur=0.0, asset_class=AssetClass.CIVIL_GRID)
    modules = CapexItem(name="Solar Modules", amount_keur=20_000.0, y0_share=0.0,
                        spending_profile=(0.5, 0.5), asset_class=AssetClass.SOLAR_PANELS)
    inverters = CapexItem(name="Inverters", amount_keur=3_000.0, y0_share=0.0,
                           spending_profile=(0.5, 0.5), asset_class=AssetClass.SOLAR_PANELS)
    civil = CapexItem(name="Civil Works", amount_keur=5_000.0, y0_share=0.3,
                      spending_profile=(0.4, 0.3), asset_class=AssetClass.CIVIL_GRID)
    grid = CapexItem(name="Grid Connection", amount_keur=2_000.0, y0_share=0.5,
                     spending_profile=(0.5,), asset_class=AssetClass.CIVIL_GRID)
    soft = CapexItem(name="Soft Costs", amount_keur=3_000.0, y0_share=1.0,
                     asset_class=AssetClass.SOFT_COSTS)

    capex = CapexStructure(
        epc_contract=modules, production_units=inverters,
        epc_other=civil, grid_connection=grid,
        ops_prep=z, insurances=z, lease_tax=z,
        construction_mgmt_a=z, commissioning=z,
        audit_legal=soft, construction_mgmt_b=z,
        contingencies=z, taxes=z,
        project_acquisition=z, project_rights=z,
        idc_keur=0.0, bank_fees_keur=0.0,  # Generic-path: factory-direct must match resolver (which zeros via _zero_financial_capex_subfields)
    )
    opex = [
        OpexItem(name="Technical Management", y1_amount_keur=150.0, annual_inflation=0.02),
        OpexItem(name="Insurance", y1_amount_keur=100.0, annual_inflation=0.02),
        OpexItem(name="Maintenance", y1_amount_keur=80.0, annual_inflation=0.02),
        OpexItem(name="Lease & Tax", y1_amount_keur=50.0, annual_inflation=0.02),
    ]
    _solar_fc = date(2030, 1, 1)
    info = ProjectInfo(name="Generic Solar Model", company="Synthetic Sponsor", code="GEN-SOLAR-1",
        country_iso="XA", financial_close=_solar_fc,
        construction_months=construction_months,
        cod_date=_solar_fc + relativedelta(months=construction_months),
        horizon_years=horizon_years, period_frequency=PeriodFrequency.SEMESTRIAL)
    technical = TechnicalParams(capacity_mw=capacity_mw, yield_scenario="P_50",
        operating_hours_p50=1500.0, operating_hours_p90_10y=1400.0,
        pv_degradation=0.004, bess_enabled=False)
    # Market price curve: Y1/Y2 explicit per the synthetic reference specification, then 2%/yr
    # compounding from Y2 (matches market_inflation and the synthetic
    # reference convention's Revenue-tab formula, =Y2*(1+esc)^(year-2)).
    solar_market_y1, solar_market_y2, solar_market_escalation = 60.0, 61.0, 0.02
    solar_market_curve = (solar_market_y1, solar_market_y2) + tuple(
        solar_market_y2 * (1 + solar_market_escalation) ** (i - 1) for i in range(2, 30)
    )
    # Synthetic reference: the G1A reference convention has no PV-revenue-based balancing
    # deduction (only the flat EUR/MWh row, zero for Solar), so the domain
    # default balancing_cost_pv=0.025 must be zeroed here to match the spec.
    revenue = RevenueParams(ppa_base_tariff=50.0, ppa_term_years=10, ppa_index=0.02,
        market_scenario="Central", market_prices_curve=solar_market_curve,
        market_inflation=0.02, co2_enabled=False, balancing_cost_pv=0.0)
    # Synthetic funding assumption: 500 share capital + 7,750 SHL reconciles
    # the 25% sponsor share. G2A derives that SHL from Sources & Uses and does
    # not use either legacy SHL amount as its runtime funding authority.
    #
    # Synthetic repayment policy: CASH_SWEEP from post-senior to end-of-horizon makes a newly-created
    # generic solar project economically serviceable (terminal SHL balance = 0).
    # BULLET left 6,629 kEUR unpaid because distributable cash at the BULLET
    # maturity (senior+2) was insufficient for a lump-sum repayment.
    # CASH_SWEEP with eligibility starting at the first post-senior period
    # progressively repays principal from real project cash flows, which is the
    # standard project-finance cash waterfall after senior debt is retired.
    # No calibration to a target IRR; repayment follows actual modelled cash.
    _solar_senior_tenor_years: int = 15
    _solar_constr_semesters: int = math.ceil(construction_months / 6)
    _solar_shl_elig_start: int = _solar_constr_semesters + _solar_senior_tenor_years * 2
    _solar_shl_maturity: int = _solar_constr_semesters + horizon_years * 2 - 1
    financing = FinancingParams(share_capital_keur=500.0, shl_amount_keur=7_750.0, shl_rate=0.08,
        gearing_ratio=0.75, senior_tenor_years=_solar_senior_tenor_years, base_rate=0.03, margin_bps=250,
        floating_share=0.3, fixed_share=0.7, hedge_coverage=0.8,
        target_dscr=1.20, lockup_dscr=1.10, dsra_months=6,
        equity_irr_method=EquityIRRMethod.EQUITY_ONLY.value,
        debt_sizing_method=DebtSizingMethod.DSCR_SCULPT.value,
        debt_sizing_mode=DebtSizingMode.FLAT_DSCR_SCULPTED,
        sponsor_funding_mode=SponsorFundingMode.SHARE_CAPITAL_THEN_SHL,
        gearing_basis_mode=GearingBasisMode.TOTAL_PROJECT_USES,
        senior_debt_interest_config=_generic_clean_senior_interest_config(
            annual_all_in_rate=0.03 + 250 / 10000,
            tenor_years=_solar_senior_tenor_years,
        ),
        clean_shl_principal_keur=7_750.0,  # compatibility assertion; G2A derives principal
        clean_shl_repayment_method=SHLRepaymentMethod.CASH_SWEEP,
        shl_principal_eligibility_start_period=_solar_shl_elig_start,
        shl_maturity_period_index=_solar_shl_maturity,
        shl_day_count_convention="PERIOD_AXIS_ACTUAL_YEAR",
        shl_construction_day_count_fraction=0.0,
    )
    tax = TaxParams(corporate_rate=0.25, loss_carryforward_years=5,
        loss_carryforward_cap=1.0, atad_ebitda_limit=0.30, atad_min_interest_keur=3000.0,
        clean_cash_tax_timing_enabled=True)

    return ProjectInputs(info=info, technical=technical, capex=capex,
        opex=tuple(opex), revenue=revenue, financing=financing, tax=tax,
        accounting_policy_config=_GENERIC_CLEAN_ACCOUNTING_POLICY)


def create_default_wind_project(
    capacity_mw: float = 40.0,
    horizon_years: int = 25,
    construction_months: int = 18,
) -> ProjectInputs:
    """Test 2 — Wind: fictional utility-scale wind project for demos and tests.

    40 MW onshore wind, EUR 60/MWh PPA, 25-year horizon. Entirely fictional —
    no real company, no real project, no Excel calibration data.
    """
    z = CapexItem(name="Unused", amount_keur=0.0, asset_class=AssetClass.CIVIL_GRID)
    turbines = CapexItem(name="Wind Turbines", amount_keur=30_000.0, y0_share=0.4,
                         spending_profile=(0.6,), asset_class=AssetClass.WIND_TURBINES)
    civil = CapexItem(name="Civil Works", amount_keur=6_000.0, y0_share=0.3,
                      spending_profile=(0.4, 0.3), asset_class=AssetClass.CIVIL_GRID)
    grid = CapexItem(name="Grid Connection", amount_keur=3_000.0, y0_share=0.5,
                     spending_profile=(0.5,), asset_class=AssetClass.CIVIL_GRID)
    # The canonical public generic input calls this ``Soft Costs`` but places
    # it in the audit_legal CapexStructure field.  C.08 is therefore its
    # established public owner; do not invent a C.15 split.
    soft = CapexItem(name="Soft Costs", amount_keur=4_000.0, y0_share=1.0,
                     asset_class=AssetClass.SOFT_COSTS)

    capex = CapexStructure(
        # Turbines are production equipment.  Keep the public generic
        # economics unchanged while placing construction scope in C.02.
        production_units=turbines, epc_contract=civil,
        epc_other=z, grid_connection=grid,
        ops_prep=z, insurances=z, lease_tax=z,
        construction_mgmt_a=z, commissioning=z,
        audit_legal=soft, construction_mgmt_b=z,
        contingencies=z, taxes=z,
        project_acquisition=z, project_rights=z,
        idc_keur=0.0, bank_fees_keur=0.0,  # Generic-path: factory-direct must match resolver (which zeros via _zero_financial_capex_subfields)
    )
    opex = [
        OpexItem(name="Technical Management", y1_amount_keur=200.0, annual_inflation=0.02),
        OpexItem(name="Insurance", y1_amount_keur=150.0, annual_inflation=0.02),
        OpexItem(name="Maintenance", y1_amount_keur=120.0, annual_inflation=0.02),
        OpexItem(name="Lease & Tax", y1_amount_keur=80.0, annual_inflation=0.02),
    ]
    _wind_fc = date(2030, 1, 1)
    info = ProjectInfo(name="Generic Wind Model", company="Synthetic Sponsor", code="GEN-WIND-1",
        country_iso="XB", financial_close=_wind_fc,
        construction_months=construction_months,
        cod_date=_wind_fc + relativedelta(months=construction_months),
        horizon_years=horizon_years, period_frequency=PeriodFrequency.SEMESTRIAL)
    technical = TechnicalParams(capacity_mw=capacity_mw, yield_scenario="P_50",
        operating_hours_p50=3000.0, operating_hours_p90_10y=2700.0,
        pv_degradation=0.0, bess_enabled=False)
    # Market price curve: Y1/Y2 explicit per the synthetic reference specification, then 2%/yr
    # compounding from Y2 (matches market_inflation and the synthetic
    # reference convention's Revenue-tab formula, =Y2*(1+esc)^(year-2)).
    wind_market_y1, wind_market_y2, wind_market_escalation = 65.0, 66.3, 0.02
    wind_market_curve = (wind_market_y1, wind_market_y2) + tuple(
        wind_market_y2 * (1 + wind_market_escalation) ** (i - 1) for i in range(2, 30)
    )
    # Synthetic reference: the G1A reference convention has no PV-revenue-based balancing
    # deduction (only the flat 8 EUR/MWh row, already modeled via
    # balancing_cost_wind_eur_mwh below), so the domain default
    # balancing_cost_pv=0.025 must be zeroed here to match the spec.
    revenue = RevenueParams(ppa_base_tariff=60.0, ppa_term_years=12, ppa_index=0.02,
        market_scenario="Central", market_prices_curve=wind_market_curve,
        market_inflation=0.02, balancing_cost_wind_eur_mwh=8.0,
        co2_enabled=False, co2_price_eur=0.0, balancing_cost_pv=0.0)
    # Synthetic funding assumption: 500 share capital + 10,250 SHL reconciles
    # the 25% sponsor share. G2A derives that SHL from Sources & Uses and does
    # not use either legacy SHL amount as its runtime funding authority.
    #
    # Synthetic repayment policy: CASH_SWEEP — same reasoning as Solar. BULLET left 6,388 kEUR unpaid.
    _wind_senior_tenor_years: int = 15
    _wind_constr_semesters: int = math.ceil(construction_months / 6)
    _wind_shl_elig_start: int = _wind_constr_semesters + _wind_senior_tenor_years * 2
    _wind_shl_maturity: int = _wind_constr_semesters + horizon_years * 2 - 1
    financing = FinancingParams(share_capital_keur=500.0, shl_amount_keur=10_250.0, shl_rate=0.08,
        gearing_ratio=0.75, senior_tenor_years=_wind_senior_tenor_years, base_rate=0.03, margin_bps=250,
        floating_share=0.3, fixed_share=0.7, hedge_coverage=0.8,
        target_dscr=1.20, lockup_dscr=1.10, dsra_months=6,
        equity_irr_method=EquityIRRMethod.EQUITY_ONLY.value,
        debt_sizing_method=DebtSizingMethod.DSCR_SCULPT.value,
        debt_sizing_mode=DebtSizingMode.FLAT_DSCR_SCULPTED,
        sponsor_funding_mode=SponsorFundingMode.SHARE_CAPITAL_THEN_SHL,
        gearing_basis_mode=GearingBasisMode.TOTAL_PROJECT_USES,
        senior_debt_interest_config=_generic_clean_senior_interest_config(
            annual_all_in_rate=0.03 + 250 / 10000,
            tenor_years=_wind_senior_tenor_years,
        ),
        clean_shl_principal_keur=10_250.0,  # compatibility assertion; G2A derives principal
        clean_shl_repayment_method=SHLRepaymentMethod.CASH_SWEEP,
        shl_principal_eligibility_start_period=_wind_shl_elig_start,
        shl_maturity_period_index=_wind_shl_maturity,
        shl_day_count_convention="PERIOD_AXIS_ACTUAL_YEAR",
        shl_construction_day_count_fraction=0.0,
    )
    tax = TaxParams(corporate_rate=0.25, loss_carryforward_years=5,
        loss_carryforward_cap=1.0, atad_ebitda_limit=0.30, atad_min_interest_keur=3000.0,
        clean_cash_tax_timing_enabled=True)

    return ProjectInputs(info=info, technical=technical, capex=capex,
        opex=tuple(opex), revenue=revenue, financing=financing, tax=tax,
        accounting_policy_config=_GENERIC_CLEAN_ACCOUNTING_POLICY)


def create_default_bess_project(
    power_mw: float = 50.0,
    energy_mwh: float = 200.0,
    cycles_per_year: float = 300,
    horizon_years: int = 25,
    construction_months: int = 12,
) -> ProjectInputs:
    """Generic standalone BESS project — round numbers for tests/examples, not Excel calibration."""
    z = CapexItem(name="Unused", amount_keur=0.0, asset_class=AssetClass.CIVIL_GRID)
    cells = CapexItem(name="BESS Cells", amount_keur=22_000.0, y0_share=0.0,
                      spending_profile=(0.5, 0.5), asset_class=AssetClass.BESS_CELLS)
    pe = CapexItem(name="Power Electronics", amount_keur=3_000.0, y0_share=0.0,
                   spending_profile=(0.5, 0.5), asset_class=AssetClass.BESS_POWER_ELECTRONICS)
    civil = CapexItem(name="Civil & Grid", amount_keur=2_000.0, y0_share=0.3,
                      spending_profile=(0.4, 0.3), asset_class=AssetClass.CIVIL_GRID)
    soft = CapexItem(name="Soft Costs", amount_keur=1_500.0, y0_share=1.0,
                     asset_class=AssetClass.SOFT_COSTS)

    capex = CapexStructure(
        epc_contract=cells, production_units=pe,
        epc_other=civil, grid_connection=z,
        ops_prep=z, insurances=z, lease_tax=z,
        construction_mgmt_a=z, commissioning=z,
        audit_legal=z, construction_mgmt_b=z,
        contingencies=z, taxes=z,
        project_acquisition=z, project_rights=z,
        idc_keur=0.0, bank_fees_keur=0.0,  # Generic-path: factory-direct must match resolver (which zeros via _zero_financial_capex_subfields)
    )
    opex = [
        OpexItem(name="Technical Management", y1_amount_keur=150.0, annual_inflation=0.02),
        OpexItem(name="Insurance", y1_amount_keur=100.0, annual_inflation=0.02),
        OpexItem(name="Maintenance", y1_amount_keur=80.0, annual_inflation=0.02),
        OpexItem(name="Lease & Tax", y1_amount_keur=50.0, annual_inflation=0.02),
    ]
    info = ProjectInfo(
        name="Generic Storage Model", company="Synthetic Sponsor", code="GEN-STORAGE-1",
        country_iso="XC", financial_close=date(2030, 1, 1),
        construction_months=construction_months, cod_date=date(2031, 1, 1),
        horizon_years=horizon_years, period_frequency=PeriodFrequency.SEMESTRIAL)
    bess_params = BessParams(
        power_mw=power_mw,
        energy_mwh=energy_mwh,
        cycles_per_year=cycles_per_year,
        round_trip_efficiency=0.88,
        availability=0.98,
        annual_degradation=0.02,
        arbitrage_spread_eur_mwh=40.0,
        ancillary_revenue_eur_mw_year=25000.0,
        capacity_revenue_eur_mw_year=0.0,
        augmentation_capex_keur=0.0,
    )
    technical = TechnicalParams(
        capacity_mw=power_mw, yield_scenario="P_50",
        operating_hours_p50=0.0, operating_hours_p90_10y=0.0,
        pv_degradation=0.0, bess_enabled=True, bess_degradation=0.02,
        bess=bess_params)
    revenue = RevenueParams(
        ppa_base_tariff=0.0, ppa_term_years=0, ppa_index=0.0,
        market_scenario="Central",
        market_prices_curve=tuple(60.0 + i for i in range(30)),
        market_inflation=0.02, co2_enabled=False)
    financing = FinancingParams(
        share_capital_keur=500.0, shl_amount_keur=5_000.0, shl_rate=0.08,
        gearing_ratio=0.75, senior_tenor_years=15, base_rate=0.03, margin_bps=250,
        floating_share=0.3, fixed_share=0.7, hedge_coverage=0.8,
        target_dscr=1.20, lockup_dscr=1.10, dsra_months=6,
        equity_irr_method=EquityIRRMethod.EQUITY_ONLY.value,
        debt_sizing_method=DebtSizingMethod.DSCR_SCULPT.value)
    tax = TaxParams(
        corporate_rate=0.25, loss_carryforward_years=5,
        loss_carryforward_cap=1.0, atad_ebitda_limit=0.30, atad_min_interest_keur=3000.0)

    return ProjectInputs(info=info, technical=technical, capex=capex,
        opex=tuple(opex), revenue=revenue, financing=financing, tax=tax)


def create_default_solar_bess_project(
    solar_capacity_mw: float = 50.0,
    bess_power_mw: float = 10.0,
    bess_energy_mwh: float = 20.0,
    bess_cycles_per_year: float = 365.0,
    horizon_years: int = 25,
    construction_months: int = 12,
) -> ProjectInputs:
    """Generic solar + BESS hybrid project."""
    z = CapexItem(name="Unused", amount_keur=0.0, asset_class=AssetClass.CIVIL_GRID)
    modules = CapexItem(name="Solar Modules", amount_keur=20_000.0, y0_share=0.0,
                        spending_profile=(0.5, 0.5), asset_class=AssetClass.SOLAR_PANELS)
    inverters = CapexItem(name="Inverters", amount_keur=3_000.0, y0_share=0.0,
                           spending_profile=(0.5, 0.5), asset_class=AssetClass.SOLAR_PANELS)
    cells = CapexItem(name="BESS Cells", amount_keur=5_000.0, y0_share=0.0,
                      spending_profile=(0.5, 0.5), asset_class=AssetClass.BESS_CELLS)
    civil = CapexItem(name="Civil Works", amount_keur=3_000.0, y0_share=0.3,
                      spending_profile=(0.4, 0.3), asset_class=AssetClass.CIVIL_GRID)
    grid = CapexItem(name="Grid Connection", amount_keur=2_000.0, y0_share=0.5,
                     spending_profile=(0.5,), asset_class=AssetClass.CIVIL_GRID)
    capex = CapexStructure(
        epc_contract=modules, production_units=inverters,
        epc_other=civil, grid_connection=grid,
        ops_prep=z, insurances=z, lease_tax=z,
        construction_mgmt_a=z, commissioning=z,
        audit_legal=z, construction_mgmt_b=z,
        contingencies=z, taxes=z,
        project_acquisition=z, project_rights=z,
        idc_keur=0.0, bank_fees_keur=0.0,  # Generic-path: factory-direct must match resolver (which zeros via _zero_financial_capex_subfields)
    )
    opex = [
        OpexItem(name="Technical Management", y1_amount_keur=150.0, annual_inflation=0.02),
        OpexItem(name="Insurance", y1_amount_keur=100.0, annual_inflation=0.02),
        OpexItem(name="Maintenance", y1_amount_keur=80.0, annual_inflation=0.02),
        OpexItem(name="Lease & Tax", y1_amount_keur=50.0, annual_inflation=0.02),
    ]
    info = ProjectInfo(
        name="Generic Solar+Storage", company="Synthetic Sponsor", code="GEN-SOLAR-STORAGE-1",
        country_iso="XA", financial_close=date(2030, 1, 1),
        construction_months=construction_months, cod_date=date(2031, 1, 1),
        horizon_years=horizon_years, period_frequency=PeriodFrequency.SEMESTRIAL)
    bess_params = BessParams(
        power_mw=bess_power_mw,
        energy_mwh=bess_energy_mwh,
        cycles_per_year=bess_cycles_per_year,
        round_trip_efficiency=0.88,
        availability=0.98,
        annual_degradation=0.02,
        arbitrage_spread_eur_mwh=40.0,
        ancillary_revenue_eur_mw_year=25000.0,
    )
    technical = TechnicalParams(
        capacity_mw=solar_capacity_mw, yield_scenario="P_50",
        operating_hours_p50=1500.0, operating_hours_p90_10y=1400.0,
        pv_degradation=0.004, bess_degradation=0.02,
        plant_availability=0.99, grid_availability=0.99,
        bess_enabled=True, bess=bess_params)
    revenue = RevenueParams(
        ppa_base_tariff=60.0, ppa_term_years=10, ppa_index=0.02,
        market_scenario="Central", market_prices_curve=tuple(65.0 + i for i in range(30)),
        market_inflation=0.02, co2_enabled=True, co2_price_eur=5.0)
    financing = FinancingParams(
        share_capital_keur=500.0, shl_amount_keur=5_000.0, shl_rate=0.08,
        gearing_ratio=0.75, senior_tenor_years=15, base_rate=0.03, margin_bps=250,
        floating_share=0.3, fixed_share=0.7, hedge_coverage=0.8,
        target_dscr=1.20, lockup_dscr=1.10, dsra_months=6,
        equity_irr_method=EquityIRRMethod.EQUITY_ONLY.value,
        debt_sizing_method=DebtSizingMethod.DSCR_SCULPT.value)
    tax = TaxParams(
        corporate_rate=0.25, loss_carryforward_years=5,
        loss_carryforward_cap=1.0, atad_ebitda_limit=0.30, atad_min_interest_keur=3000.0)

    return ProjectInputs(info=info, technical=technical, capex=capex,
        opex=tuple(opex), revenue=revenue, financing=financing, tax=tax)



def create_default_wind_bess_project(
    wind_capacity_mw: float = 80.0,
    bess_power_mw: float = 10.0,
    bess_energy_mwh: float = 20.0,
    bess_cycles_per_year: float = 365.0,
    horizon_years: int = 25,
    construction_months: int = 18,
) -> ProjectInputs:
    """Generic wind + BESS hybrid project."""
    z = CapexItem(name="Unused", amount_keur=0.0, asset_class=AssetClass.CIVIL_GRID)
    turbines = CapexItem(name="Wind Turbines", amount_keur=30_000.0, y0_share=0.4,
                         spending_profile=(0.6,), asset_class=AssetClass.WIND_TURBINES)
    cells = CapexItem(name="BESS Cells", amount_keur=5_000.0, y0_share=0.0,
                      spending_profile=(0.5, 0.5), asset_class=AssetClass.BESS_CELLS)
    civil = CapexItem(name="Civil Works", amount_keur=4_000.0, y0_share=0.3,
                      spending_profile=(0.4, 0.3), asset_class=AssetClass.CIVIL_GRID)
    grid = CapexItem(name="Grid Connection", amount_keur=3_000.0, y0_share=0.5,
                     spending_profile=(0.5,), asset_class=AssetClass.CIVIL_GRID)
    capex = CapexStructure(
        epc_contract=turbines, production_units=cells,
        epc_other=civil, grid_connection=grid,
        ops_prep=z, insurances=z, lease_tax=z,
        construction_mgmt_a=z, commissioning=z,
        audit_legal=z, construction_mgmt_b=z,
        contingencies=z, taxes=z,
        project_acquisition=z, project_rights=z,
        idc_keur=0.0, bank_fees_keur=0.0,  # Generic-path: factory-direct must match resolver (which zeros via _zero_financial_capex_subfields)
    )
    opex = [
        OpexItem(name="Technical Management", y1_amount_keur=200.0, annual_inflation=0.02),
        OpexItem(name="Insurance", y1_amount_keur=150.0, annual_inflation=0.02),
        OpexItem(name="Maintenance", y1_amount_keur=120.0, annual_inflation=0.02),
        OpexItem(name="Lease & Tax", y1_amount_keur=80.0, annual_inflation=0.02),
    ]
    info = ProjectInfo(
        name="Generic Wind+Storage", company="Synthetic Sponsor", code="GEN-WIND-STORAGE-1",
        country_iso="XB", financial_close=date(2030, 1, 1),
        construction_months=construction_months, cod_date=date(2031, 7, 1),
        horizon_years=horizon_years, period_frequency=PeriodFrequency.SEMESTRIAL)
    bess_params = BessParams(
        power_mw=bess_power_mw,
        energy_mwh=bess_energy_mwh,
        cycles_per_year=bess_cycles_per_year,
        round_trip_efficiency=0.88,
        availability=0.98,
        annual_degradation=0.02,
        arbitrage_spread_eur_mwh=35.0,
        ancillary_revenue_eur_mw_year=25000.0,
    )
    technical = TechnicalParams(
        capacity_mw=wind_capacity_mw, yield_scenario="P_50",
        operating_hours_p50=3000.0, operating_hours_p90_10y=2700.0,
        pv_degradation=0.0, bess_degradation=0.02,
        plant_availability=0.97, grid_availability=0.99,
        bess_enabled=True, bess=bess_params)
    revenue = RevenueParams(
        ppa_base_tariff=65.0, ppa_term_years=12, ppa_index=0.02,
        market_scenario="Central", market_prices_curve=tuple(60.0 + i for i in range(30)),
        market_inflation=0.02, balancing_cost_wind_eur_mwh=8.0,
        co2_enabled=True, co2_price_eur=4.0)
    financing = FinancingParams(
        share_capital_keur=500.0, shl_amount_keur=6_000.0, shl_rate=0.08,
        gearing_ratio=0.75, senior_tenor_years=15, base_rate=0.03, margin_bps=250,
        floating_share=0.3, fixed_share=0.7, hedge_coverage=0.8,
        target_dscr=1.20, lockup_dscr=1.10, dsra_months=6,
        equity_irr_method=EquityIRRMethod.EQUITY_ONLY.value,
        debt_sizing_method=DebtSizingMethod.DSCR_SCULPT.value)
    tax = TaxParams(
        corporate_rate=0.25, loss_carryforward_years=5,
        loss_carryforward_cap=1.0, atad_ebitda_limit=0.30, atad_min_interest_keur=3000.0)


    return ProjectInputs(info=info, technical=technical, capex=capex,
        opex=tuple(opex), revenue=revenue, financing=financing, tax=tax)

def create_generic_solar_reference() -> ProjectInputs:
    """Protected synthetic Solar reference for public demos and regression tests."""
    base = create_default_solar_project(
        capacity_mw=64.0,
        horizon_years=25,
        construction_months=14,
    )
    return replace(
        base,
        info=replace(
            base.info,
            name="Generic Solar Reference",
            company="Synthetic Sponsor A",
            code="REF-SOLAR-A",
            country_iso="XA",
        ),
    )


def create_generic_wind_reference() -> ProjectInputs:
    """Protected synthetic Wind reference for public demos and regression tests."""
    base = create_default_wind_project(
        capacity_mw=48.0,
        horizon_years=27,
        construction_months=20,
    )
    return replace(
        base,
        info=replace(
            base.info,
            name="Generic Wind Reference",
            company="Synthetic Sponsor B",
            code="REF-WIND-B",
            country_iso="XB",
        ),
    )


def create_generic_storage_reference() -> ProjectInputs:
    """Protected synthetic standalone storage reference for public demos."""
    base = create_default_bess_project(
        power_mw=40.0,
        energy_mwh=160.0,
        cycles_per_year=280,
        horizon_years=22,
        construction_months=10,
    )
    return replace(
        base,
        info=replace(
            base.info,
            name="Generic Storage Reference",
            company="Synthetic Sponsor C",
            code="REF-STORAGE-C",
            country_iso="XC",
        ),
    )


def create_default_data_center_project(
    capacity_mw: float = 20.0,
    horizon_years: int = 20,
    construction_months: int = 24,
) -> ProjectInputs:
    """Test 3 — Data Center: fictional IT-load data center for demos and tests.

    20 MW IT load capacity, 200,000 kEUR CAPEX (10,000 kEUR/MW IT), 20-year
    horizon.  ``capacity_mw`` means IT Load Capacity (MW) — never generation
    capacity.  Operating economics (occupancy ramp, EUR/kW/month service
    price, PUE, electricity cost) live in ``app.data_center_authority`` and
    are mapped onto the generic engine inputs by its runtime adapter;
    financing, tax, statements and returns remain FINCO engine authority.
    Entirely fictional — no real company, operator, or project.
    """
    from app.data_center_authority import (
        GENERIC_DATA_CENTER_REFERENCE_DRIVERS,
        apply_data_center_runtime_adapter,
        annual_power_cost_keur,
        occupancy_for_year,
    )

    _dc = GENERIC_DATA_CENTER_REFERENCE_DRIVERS
    z = CapexItem(name="Unused", amount_keur=0.0, asset_class=AssetClass.CIVIL_GRID)
    # Data Center technical plant (UPS/electrical, cooling, backup
    # generation, white space): classified under the generic CIVIL_GRID
    # asset class with an explicit per-item 15-year useful-life override
    # (the frozen finco_core/financial_engine production paths gain zero
    # diff; the class-level DC asset class is deliberately not introduced
    # for V1).  See the PR asset-class decision.
    technical_plant = CapexItem(
        name="Data Center Technical Plant", amount_keur=80_000.0, y0_share=0.0,
        spending_profile=(0.25, 0.35, 0.25, 0.15), asset_class=AssetClass.CIVIL_GRID,
        useful_life_override=15,
    )
    building = CapexItem(
        name="Building Shell and Fit-Out", amount_keur=55_000.0, y0_share=0.0,
        spending_profile=(0.35, 0.35, 0.2, 0.1), asset_class=AssetClass.CIVIL_GRID,
    )
    grid = CapexItem(
        name="Grid Connection", amount_keur=20_000.0, y0_share=0.0,
        spending_profile=(0.5, 0.3, 0.2), asset_class=AssetClass.CIVIL_GRID,
    )
    ops_prep = CapexItem(
        name="Operations Readiness", amount_keur=5_000.0, y0_share=1.0,
        asset_class=AssetClass.SOFT_COSTS,
    )
    site = CapexItem(
        name="Balance of Plant / Site Infrastructure", amount_keur=15_000.0, y0_share=0.0,
        spending_profile=(0.5, 0.3, 0.2), asset_class=AssetClass.CIVIL_GRID,
    )
    soft = CapexItem(
        name="Soft Costs", amount_keur=8_000.0, y0_share=1.0,
        asset_class=AssetClass.SOFT_COSTS,
    )
    owner_eng = CapexItem(
        name="Owner's Engineering / Construction Supervision", amount_keur=7_000.0, y0_share=1.0,
        asset_class=AssetClass.SOFT_COSTS,
    )
    contingency = CapexItem(
        name="Construction Contingency", amount_keur=10_000.0, y0_share=0.0,
        spending_profile=(0.25, 0.35, 0.25, 0.15), asset_class=AssetClass.CIVIL_GRID,
        useful_life_override=15,
    )

    capex = CapexStructure(
        production_units=technical_plant, epc_contract=building,
        grid_connection=grid, ops_prep=ops_prep, epc_other=site,
        insurances=z, lease_tax=z,
        construction_mgmt_a=owner_eng, commissioning=z,
        audit_legal=soft, construction_mgmt_b=z,
        contingencies=contingency, taxes=z,
        project_acquisition=z, project_rights=z,
        idc_keur=0.0, bank_fees_keur=0.0,  # Generic-path: factory-direct must match resolver (which zeros via _zero_financial_capex_subfields)
    )
    # Non-power OPEX parents (B.01/B.02/B.05/B.06/B.07/B.10) are flat with 2%
    # escalation.  B.08 power expenses are DERIVED by the runtime adapter from
    # IT MW × occupancy × PUE × 8,760 × EUR/MWh; the Y1 amount below is the
    # derived year-1 value and is recomputed on every runtime resolution.
    _occ_y1 = occupancy_for_year(_dc, 1)
    power_y1 = annual_power_cost_keur(
        capacity_mw=capacity_mw,
        occupancy=_occ_y1,
        pue=_dc.pue,
        electricity_price_eur_mwh=_dc.electricity_price_eur_mwh,
    )
    opex = [
        OpexItem(name="Technical Management", y1_amount_keur=2_000.0, annual_inflation=0.02),
        OpexItem(name="Infrastructure Maintenance", y1_amount_keur=3_500.0, annual_inflation=0.02),
        OpexItem(name="Security", y1_amount_keur=1_200.0, annual_inflation=0.02),
        OpexItem(name="Insurance", y1_amount_keur=1_000.0, annual_inflation=0.02),
        OpexItem(name="Lease & Tax", y1_amount_keur=1_200.0, annual_inflation=0.02),
        OpexItem(name="Audit, Accounting & Legal", y1_amount_keur=800.0, annual_inflation=0.02),
        OpexItem(name="Power Expenses", y1_amount_keur=power_y1, annual_inflation=0.0),
    ]
    _dc_fc = date(2030, 1, 1)
    info = ProjectInfo(name="Generic Data Center Model", company="Synthetic Sponsor D",
        code="GEN-DC-1", country_iso="XD", financial_close=_dc_fc,
        construction_months=construction_months,
        cod_date=_dc_fc + relativedelta(months=construction_months),
        horizon_years=horizon_years, period_frequency=PeriodFrequency.SEMESTRIAL)
    # Full-time IT-load basis: revenue utilization is carried by the occupancy
    # authority (mapped onto the engine market-price curve), so availability
    # and degradation are neutral here.
    technical = TechnicalParams(capacity_mw=capacity_mw, yield_scenario="P_50",
        operating_hours_p50=8760.0, operating_hours_p90_10y=8760.0,
        pv_degradation=0.0, plant_availability=_dc.availability,
        grid_availability=1.0, bess_enabled=False)
    revenue = RevenueParams(ppa_base_tariff=0.0, ppa_term_years=_dc.contract_term_years,
        ppa_index=_dc.revenue_escalation,
        market_scenario="Central", market_prices_curve=(),
        market_inflation=_dc.revenue_escalation, co2_enabled=False,
        balancing_cost_pv=0.0, balancing_cost_wind_eur_mwh=0.0)
    _dc_senior_tenor_years: int = 12
    _dc_constr_semesters: int = math.ceil(construction_months / 6)
    _dc_shl_elig_start: int = _dc_constr_semesters + _dc_senior_tenor_years * 2
    _dc_shl_maturity: int = _dc_constr_semesters + horizon_years * 2 - 1
    # Sponsor funding convention (same authority as Solar/Wind): senior debt
    # sizes from gearing/DSCR; sponsor share = 1 − gearing, split as
    # share capital then SHL (G2A derives the runtime SHL principal).
    #
    # DOCUMENTED SYNTHETIC-ASSUMPTION CORRECTION (FINCO Generic Data Center
    # Reference V1, category B): at the synthetic operating economics
    # (10,000 kEUR/MW CAPEX, 175 EUR/kW/month all-in service price, PUE 1.30,
    # 70 EUR/MWh) the DSCR-1.30 debt capacity is ~40% of project uses, well
    # below the suggested 65% senior gearing cap.  Gearing stays 0.65 as the
    # cap; the sponsor funding mix is therefore set to 40% share capital with
    # the SHL residual (~20%) so the stack is debt-serviceable under the
    # generic SHL CASH_SWEEP convention (sweep after senior maturity).  This
    # is a financing-mix choice, NOT a calibration to a target IRR: no
    # CAPEX/price/occupancy/OPEX value was tuned.
    # share_capital/shl amounts below are 20 MW placeholders; the runtime
    # adapter scales sponsor equity proportionally (4,000 kEUR/MW IT).
    financing = FinancingParams(share_capital_keur=80_000.0, shl_amount_keur=39_600.0, shl_rate=0.08,
        gearing_ratio=0.65, senior_tenor_years=_dc_senior_tenor_years, base_rate=0.03, margin_bps=300,
        floating_share=0.3, fixed_share=0.7, hedge_coverage=0.8,
        target_dscr=1.30, lockup_dscr=1.15, dsra_months=6,
        equity_irr_method=EquityIRRMethod.EQUITY_ONLY.value,
        debt_sizing_method=DebtSizingMethod.DSCR_SCULPT.value,
        debt_sizing_mode=DebtSizingMode.FLAT_DSCR_SCULPTED,
        sponsor_funding_mode=SponsorFundingMode.SHARE_CAPITAL_THEN_SHL,
        gearing_basis_mode=GearingBasisMode.TOTAL_PROJECT_USES,
        senior_debt_interest_config=_generic_clean_senior_interest_config(
            annual_all_in_rate=0.03 + 300 / 10000,
            tenor_years=_dc_senior_tenor_years,
        ),
        clean_shl_principal_keur=39_600.0,  # compatibility assertion; G2A derives principal
        clean_shl_repayment_method=SHLRepaymentMethod.CASH_SWEEP,
        shl_principal_eligibility_start_period=_dc_shl_elig_start,
        shl_maturity_period_index=_dc_shl_maturity,
        shl_day_count_convention="PERIOD_AXIS_ACTUAL_YEAR",
        shl_construction_day_count_fraction=0.0,
    )
    tax = TaxParams(corporate_rate=0.25, loss_carryforward_years=5,
        loss_carryforward_cap=1.0, atad_ebitda_limit=0.30, atad_min_interest_keur=3000.0,
        clean_cash_tax_timing_enabled=True)

    raw = ProjectInputs(info=info, technical=technical, capex=capex,
        opex=tuple(opex), revenue=revenue, financing=financing, tax=tax,
        accounting_policy_config=_GENERIC_CLEAN_ACCOUNTING_POLICY)
    # The factory returns canonical runtime-adapted inputs: the Data Center
    # operating authority (occupancy ramp, service price, PUE-derived power
    # OPEX) is mapped onto the generic engine inputs here so every consumer
    # (API, preview, workbook, tests) sees identical economics.  The runtime
    # re-applies the same adapter with user-edited drivers at snapshot
    # resolution time (idempotent by construction).
    return apply_data_center_runtime_adapter(raw, _dc)


def create_generic_data_center_reference() -> ProjectInputs:
    """Protected synthetic Data Center reference for public demos and tests.

    20 MW IT load capacity; 200,000 kEUR total CAPEX; 24-month construction;
    20-year operating horizon; semestrial periods; synthetic 2030 financial
    close; generic synthetic market code XD (Synthetic Sponsor D).
    """
    base = create_default_data_center_project(
        capacity_mw=20.0,
        horizon_years=20,
        construction_months=24,
    )
    return replace(
        base,
        info=replace(
            base.info,
            name="Generic Data Center Reference",
            company="Synthetic Sponsor D",
            code="REF-DATACENTER-D",
            country_iso="XD",
        ),
    )


__all__ = [
    "create_generic_solar_reference",
    "create_generic_wind_reference",
    "create_generic_storage_reference",
    "create_generic_data_center_reference",
    "create_generic_ev_charging_reference",
    "create_default_ev_charging_project",
    "create_default_solar_project",
    "create_default_wind_project",
    "create_default_bess_project",
    "create_default_solar_bess_project",
    "create_default_wind_bess_project",
    "create_default_data_center_project",
]


# ── Generic EV Charging Hub (V1) ─────────────────────────────────────────────
#
# A high-power EV charging site is a load-serving infrastructure asset, not a
# generator. The existing FINCO engine is reused unchanged: the EV economics
# authority (app.ev_charging_economics) derives charging revenue and the
# electricity-procurement schedule from three physical drivers (capacity MW,
# equivalent full-load hours, prices), and adapts them onto the canonical
# project cash-flow inputs:
#
#   capacity_mw                       = installed charging capacity (MW)
#   operating_hours_by_year           = equivalent full-load charging hours
#                                       ramp (Y1 1200, Y2 1600, Y3+ 2000)
#   ppa_base_tariff (internal only)   = charging price EUR/MWh (400 = 0.40/kWh)
#   ppa_index (internal only)         = charging price escalation (2%/yr)
#
# The PPA-named revenue fields are a documented internal compatibility
# adapter; they must never surface as PPA/P50/P90 terminology in EV UI/API.
# The equivalent full-load hours are net of availability effects, so the
# engine runs at neutral combined availability 1.0 and energy reconciles
# exactly; the 0.98 physical availability is display metadata only.
#
# Electricity procurement (B.08) is DERIVED from the drivers as one OpexItem
# with sustained steps (Y2 ramp, Y3 stabilized) and 2%/yr price escalation.
# Payment processing (B.11) is a fixed Y1 amount that equals 2.0% of
# stabilized gross charging revenue at reference scale; V1 does not
# dynamically scale payment fees (documented limitation, one authority only).


def create_default_ev_charging_project(
    capacity_mw: float = 5.0,
    horizon_years: int = 20,
    construction_months: int = 12,
) -> ProjectInputs:
    """Generic EV charging hub project — synthetic round numbers, no calibration.

    Reference scale: 5 MW installed charging capacity, 40 charging points
    (display metadata only), 9,000 kEUR CAPEX (1,800 kEUR/MW), 20-year
    operating horizon on a semestrial period axis.
    """
    from app.ev_charging_economics import electricity_opex_item
    from app.ev_charging_economics import merchant_price_schedule as ev_merchant_price_schedule

    z = CapexItem(name="Unused", amount_keur=0.0, asset_class=AssetClass.CIVIL_GRID)
    # V1 frozen-path compromise: charging equipment rides the existing
    # generic infrastructure class with an explicit 10-year useful-life
    # override (DC fast-charger service life). The user-facing taxonomy
    # stays "Charging Equipment" (EV-specific); CIVIL_GRID is an
    # implementation compatibility class, not a claim that chargers are
    # civil/grid works.
    equipment = CapexItem(name="Charging Equipment", amount_keur=4_000.0, y0_share=0.0,
                          spending_profile=(0.5, 0.5), asset_class=AssetClass.CIVIL_GRID,
                          useful_life_override=10)
    epc = CapexItem(name="EPC / Electrical Installation", amount_keur=1_500.0, y0_share=0.3,
                    spending_profile=(0.4, 0.3), asset_class=AssetClass.CIVIL_GRID)
    site = CapexItem(name="Site / Civil Infrastructure", amount_keur=800.0, y0_share=0.3,
                     spending_profile=(0.4, 0.3), asset_class=AssetClass.CIVIL_GRID)
    grid = CapexItem(name="Grid Connection", amount_keur=1_500.0, y0_share=0.5,
                     spending_profile=(0.5,), asset_class=AssetClass.CIVIL_GRID)
    ops_readiness = CapexItem(name="Operations Readiness", amount_keur=200.0, y0_share=1.0,
                              asset_class=AssetClass.SOFT_COSTS)
    legal = CapexItem(name="Legal / Professional", amount_keur=250.0, y0_share=1.0,
                      asset_class=AssetClass.SOFT_COSTS)
    owners_eng = CapexItem(name="Owner's Engineering / Construction Management", amount_keur=250.0,
                           y0_share=1.0, asset_class=AssetClass.SOFT_COSTS)
    contingency = CapexItem(name="Contingency", amount_keur=500.0, y0_share=1.0,
                            asset_class=AssetClass.SOFT_COSTS)

    capex = CapexStructure(
        production_units=equipment,      # C.01
        epc_contract=epc,                # C.02
        grid_connection=grid,            # C.03
        ops_prep=ops_readiness,          # C.04
        epc_other=site,                  # C.05
        audit_legal=legal,               # C.08
        construction_mgmt_a=owners_eng,  # C.09
        contingencies=contingency,       # C.13
        insurances=z, lease_tax=z,
        construction_mgmt_b=z, commissioning=z,
        taxes=z, project_acquisition=z, project_rights=z,
        idc_keur=0.0, bank_fees_keur=0.0,  # Generic-path: factory-direct must match resolver
    )
    # Fixed non-power OPEX (960 kEUR stabilized) + the DERIVED B.08 electricity
    # line. Names match the canonical OPEX groups so the public detail
    # catalogue decomposes them without relabeling.
    opex = [
        OpexItem(name="Technical Management", y1_amount_keur=200.0, annual_inflation=0.02),
        OpexItem(name="Maintenance", y1_amount_keur=300.0, annual_inflation=0.02),
        OpexItem(name="Security / HSE", y1_amount_keur=60.0, annual_inflation=0.02),
        OpexItem(name="Insurance", y1_amount_keur=80.0, annual_inflation=0.02),
        OpexItem(name="Lease & Tax", y1_amount_keur=180.0, annual_inflation=0.02),
        OpexItem(name="Audit & Accounting & Legal", y1_amount_keur=60.0, annual_inflation=0.02),
        OpexItem(name="Bank Fees", y1_amount_keur=80.0, annual_inflation=0.02),
        electricity_opex_item(capacity_mw=capacity_mw, horizon_years=horizon_years),
    ]
    _ev_fc = date(2030, 1, 1)
    info = ProjectInfo(name="Generic EV Charging Model", company="Synthetic Sponsor",
        code="GEN-EVCHARGE-1", country_iso="XE", financial_close=_ev_fc,
        construction_months=construction_months,
        cod_date=_ev_fc + relativedelta(months=construction_months),
        horizon_years=horizon_years, period_frequency=PeriodFrequency.SEMESTRIAL)
    # The engine runs at stabilized 2000 h; the Y1/Y2 utilisation ramp is
    # encoded exactly into the per-calendar-year effective-rate schedule
    # (see the revenue adapter below and app/ev_charging_economics.py).
    technical = TechnicalParams(capacity_mw=capacity_mw, yield_scenario="P_50",
        operating_hours_p50=2000.0, operating_hours_p90_10y=2000.0,
        pv_degradation=0.0, bess_enabled=False,
        plant_availability=1.0, grid_availability=1.0)
    # Internal compatibility adapter (documented in ev_charging_economics):
    # the engine runs at stabilized 2000 h; the utilisation ramp is encoded
    # exactly into the per-calendar-year effective charging rate, which the
    # frozen pipeline transports via the existing merchant schedule fields.
    # The PPA-named fields below remain the DECLARED price authority
    # (400 EUR/MWh = 0.40 EUR/kWh, 2% escalation) and the only values the
    # UI/API may surface — as "Charging Price", never as PPA/market terms.
    _ev_price_curve = tuple(400.0 * (1.02 ** i) for i in range(30))
    _ev_cal_start, _ev_cal_prices = ev_merchant_price_schedule(int(_ev_fc.year), horizon_years)
    revenue = RevenueParams(ppa_base_tariff=400.0, ppa_term_years=horizon_years, ppa_index=0.02,
        market_scenario="Central", market_prices_curve=_ev_price_curve,
        market_inflation=0.02, co2_enabled=False, balancing_cost_pv=0.0,
        first_merchant_operating_period_index=0,
        market_price_calendar_start_year=_ev_cal_start,
        market_prices_by_calendar_year_eur_mwh=_ev_cal_prices)
    # Funding: 65% gearing on total uses -> senior ~5,850 kEUR, sponsor ~3,150.
    # share_capital 500 + SHL 2,650 reconciles the sponsor share; G2A derives
    # the SHL from Sources & Uses (compatibility assertion only).
    _ev_senior_tenor_years: int = 10
    _ev_constr_semesters: int = math.ceil(construction_months / 6)
    _ev_shl_elig_start: int = _ev_constr_semesters + _ev_senior_tenor_years * 2
    _ev_shl_maturity: int = _ev_constr_semesters + horizon_years * 2 - 1
    financing = FinancingParams(share_capital_keur=500.0, shl_amount_keur=2_650.0, shl_rate=0.08,
        gearing_ratio=0.65, senior_tenor_years=_ev_senior_tenor_years, base_rate=0.03, margin_bps=300,
        floating_share=0.3, fixed_share=0.7, hedge_coverage=0.8,
        target_dscr=1.30, lockup_dscr=1.15, dsra_months=6,
        equity_irr_method=EquityIRRMethod.EQUITY_ONLY.value,
        debt_sizing_method=DebtSizingMethod.DSCR_SCULPT.value,
        debt_sizing_mode=DebtSizingMode.FLAT_DSCR_SCULPTED,
        sponsor_funding_mode=SponsorFundingMode.SHARE_CAPITAL_THEN_SHL,
        gearing_basis_mode=GearingBasisMode.TOTAL_PROJECT_USES,
        senior_debt_interest_config=_generic_clean_senior_interest_config(
            annual_all_in_rate=0.03 + 300 / 10000,
            tenor_years=_ev_senior_tenor_years,
        ),
        clean_shl_principal_keur=2_650.0,  # compatibility assertion; G2A derives principal
        clean_shl_repayment_method=SHLRepaymentMethod.CASH_SWEEP,
        shl_principal_eligibility_start_period=_ev_shl_elig_start,
        shl_maturity_period_index=_ev_shl_maturity,
        shl_day_count_convention="PERIOD_AXIS_ACTUAL_YEAR",
        shl_construction_day_count_fraction=0.0,
    )
    tax = TaxParams(corporate_rate=0.25, loss_carryforward_years=5,
        loss_carryforward_cap=1.0, atad_ebitda_limit=0.30, atad_min_interest_keur=3000.0,
        clean_cash_tax_timing_enabled=True)

    return ProjectInputs(info=info, technical=technical, capex=capex,
        opex=tuple(opex), revenue=revenue, financing=financing, tax=tax,
        accounting_policy_config=_GENERIC_CLEAN_ACCOUNTING_POLICY)


def create_generic_ev_charging_reference() -> ProjectInputs:
    """Protected synthetic EV Charging reference for public demos and regression tests."""
    base = create_default_ev_charging_project(
        capacity_mw=5.0,
        horizon_years=20,
        construction_months=12,
    )
    return replace(
        base,
        info=replace(
            base.info,
            name="Generic EV Charging Hub Reference",
            company="Synthetic Sponsor E",
            code="REF-EVCHARGE-E",
            country_iso="XE",
        ),
    )
