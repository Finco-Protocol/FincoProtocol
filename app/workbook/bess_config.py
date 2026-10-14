"""M7 native serialized contract and capability admission; no finance calculator."""
from dataclasses import fields, replace
from datetime import date
import json

from finco_core.inputs.bess_native import NativeBessTechnicalParams, parse_native_contract
from finco_core.inputs._models import TechnicalParams

FIELD_ID = "project_setup.bess.configuration"
SNAPSHOT_KEY = "bess_native_config_json"
ACTIVATION_ENABLED = False


def canonical_json(raw):
    return parse_native_contract(raw).canonical_json


def admitted(snapshot):
    if not ACTIVATION_ENABLED or not (snapshot or {}).get(SNAPSHOT_KEY):
        return False
    try:
        contract = parse_native_contract(snapshot[SNAPSHOT_KEY])
        return not contract.configuration.events and not contract.configuration.battery.initial_energy_mwh and not contract.configuration.battery.terminal_energy_mwh
    except ValueError:
        return False


def native_base_inputs():
    """Original synthetic baseline; existing accounting/financing policy, explicit defaults."""
    from app.project_factories import create_default_bess_project, _GENERIC_CLEAN_ACCOUNTING_POLICY, _generic_clean_senior_interest_config
    from finco_core.inputs._models import SponsorFundingMode, GearingBasisMode, DebtSizingMode, DebtSizingCaseConfig, YieldScenario, DebtServiceReserveSupportMode, SHLRepaymentMethod
    project = create_default_bess_project()
    return replace(project, accounting_policy_config=_GENERIC_CLEAN_ACCOUNTING_POLICY,
        financing=replace(project.financing, sponsor_funding_mode=SponsorFundingMode.EQUITY_ONLY,
            gearing_basis_mode=GearingBasisMode.TOTAL_PROJECT_USES, debt_sizing_mode=DebtSizingMode.FLAT_DSCR_SCULPTED,
            debt_sizing_case=DebtSizingCaseConfig(production_yield_scenario=YieldScenario.P50),
            clean_shl_principal_keur=0.0, shl_amount_keur=0.0, dsra_months=0,
            clean_shl_repayment_method=SHLRepaymentMethod.CASH_SWEEP, shl_day_count_convention="PERIOD_AXIS_ACTUAL_YEAR",
            shl_principal_eligibility_start_period=2, shl_maturity_period_index=51,
            dsra_support_mode=DebtServiceReserveSupportMode.NONE,
            senior_debt_interest_config=_generic_clean_senior_interest_config(annual_all_in_rate=.055, tenor_years=15)),
        tax=replace(project.tax, clean_cash_tax_timing_enabled=True))


def apply_config(project, raw):
    if not ACTIVATION_ENABLED:
        raise ValueError("BESS_FINANCIAL_ACTIVATION_RELEASE_CLOSED")
    contract = parse_native_contract(raw)
    config = contract.configuration
    if not project.technical.bess_enabled or project.technical.operating_hours_p50 or project.technical.operating_hours_p90_10y:
        raise ValueError("BESS_STANDALONE_SCOPE_REQUIRED")
    if config.events:
        raise ValueError("BESS_POST_COD_ACCOUNTING_RELEASE_CLOSED")
    if config.battery.initial_energy_mwh or config.battery.terminal_energy_mwh:
        raise ValueError("BESS_INVENTORY_FINANCIAL_BASIS_UNRESOLVED")
    tech = NativeBessTechnicalParams(**{f.name: getattr(project.technical, f.name) for f in fields(TechnicalParams)},
                                    bess_native_config_json=contract.canonical_json)
    tech = replace(tech, capacity_mw=float(config.battery.discharge_power_mw), bess=None)
    # No legacy annual spread/ancillary/certificate authority may coexist.
    if getattr(project.revenue, "multistream_config_json", "") or project.revenue.co2_enabled:
        raise ValueError("BESS_DUPLICATE_REVENUE_AUTHORITY")
    project = replace(project, technical=tech,
        revenue=replace(project.revenue, ppa_base_tariff=0, ppa_term_years=0, ppa_production_share=0))
    if project.financing.senior_debt_interest_config is None:
        from app.project_factories import _generic_clean_senior_interest_config
        project = replace(project, financing=replace(project.financing,
            senior_debt_interest_config=_generic_clean_senior_interest_config(
                annual_all_in_rate=project.financing.base_rate + project.financing.margin_bps / 10000,
                tenor_years=project.financing.senior_tenor_years)))
    from financial_engine.adapters.project_inputs import from_project_inputs
    from financial_engine.orchestrator import _build_period_engine
    periods = tuple(p for p in _build_period_engine(from_project_inputs(project)).periods() if p.is_operation)
    if config.start.date() != periods[0].start_date or config.end.date() != periods[-1].end_date:
        raise ValueError("BESS_FINANCE_AXIS: configuration must cover complete canonical horizon")
    return project
