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


__all__ = [
    "create_generic_solar_reference",
    "create_generic_wind_reference",
    "create_generic_storage_reference",
    "create_default_solar_project",
    "create_default_wind_project",
    "create_default_bess_project",
    "create_default_solar_bess_project",
    "create_default_wind_bess_project",
]
