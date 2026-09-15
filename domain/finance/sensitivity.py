"""Sensitivity analysis — tornado, spider, one-way analysis.

Provides functions for:
- run_tornado_analysis: one-factor sensitivity → list of SensitivityResult
- run_spider_analysis: multi-variable spider table → dict with variables/steps/matrix

Implements the domain-facing API (replaces the legacy core.finance.sensitivity).
"""
from dataclasses import dataclass
from typing import Optional

from domain.inputs import ProjectInputs
from domain.waterfall.waterfall_engine import run_waterfall
from domain.returns.xirr import robust_xirr


@dataclass(frozen=True)
class SensitivityResult:
    """Result of a one-way sensitivity run.

    Fields match test_sensitivity.py expectations:
    variable, low_value, high_value, low_irr, high_irr, impact_bps
    """
    variable: str
    low_value: float
    high_value: float
    low_irr: float
    high_irr: float
    impact_bps: float  # (high_irr - low_irr) * 10000


def _run_waterfall_for_inputs(inputs: ProjectInputs) -> object:
    """Helper: run waterfall for a given ProjectInputs.

    Uses domain.waterfall.waterfall_engine.cached_run_waterfall directly.
    """
    from domain.period_engine import PeriodEngine
    from domain.waterfall.waterfall_engine import cached_run_waterfall

    engine = PeriodEngine(
        financial_close=inputs.info.financial_close,
        construction_months=inputs.info.construction_months,
        horizon_years=inputs.info.horizon_years,
        ppa_years=inputs.revenue.ppa_term_years,
        frequency=inputs.info.period_frequency,  # PeriodFrequency enum
        cod_date=inputs.info.cod_date,
        period_axis_convention=getattr(
            inputs.info.period_axis_convention,
            "value",
            inputs.info.period_axis_convention,
        ),
    )

    # Compute semi-annual rate from all-in rate
    all_in_rate = inputs.financing.all_in_rate
    rate_per_period = all_in_rate / 2

    # Determine tenor in periods (senior_tenor_years × 2)
    tenor_periods = inputs.financing.senior_tenor_years * 2

    result = cached_run_waterfall(
        inputs=inputs,
        engine=engine,
        rate_per_period=rate_per_period,
        tenor_periods=tenor_periods,
        target_dscr=inputs.financing.target_dscr,
        lockup_dscr=inputs.financing.lockup_dscr,
        tax_rate=inputs.tax.corporate_rate,
        dsra_months=inputs.financing.dsra_months,
        shl_amount=inputs.financing.shl_amount_keur,
        shl_rate=inputs.financing.shl_rate,
        discount_rate_project=0.0641,
        discount_rate_equity=0.0965,
    )
    return result


def _ppa_tariff_sensitivity(
    inputs: ProjectInputs,
    factor: float,
    target_irr_basis: str = "project",
) -> float:
    """Compute IRR at a PPA tariff modified by factor (±20%, ±13%, ±7%)."""
    from dataclasses import replace

    adj_tariff = inputs.revenue.ppa_base_tariff * factor
    mod_inputs = replace(
        inputs,
        revenue=replace(inputs.revenue, ppa_base_tariff=adj_tariff),
    )
    result = _run_waterfall_for_inputs(mod_inputs)
    return result.equity_irr if target_irr_basis == "equity" else result.project_irr


def _generation_sensitivity(
    inputs: ProjectInputs,
    factor: float,
    target_irr_basis: str = "project",
) -> float:
    """Compute IRR at generation modified by factor."""
    from dataclasses import replace

    mod_inputs = replace(
        inputs,
        technical=replace(inputs.technical, operating_hours_p50=inputs.technical.operating_hours_p50 * factor),
    )
    result = _run_waterfall_for_inputs(mod_inputs)
    return result.equity_irr if target_irr_basis == "equity" else result.project_irr


def _capex_sensitivity(
    inputs: ProjectInputs,
    factor: float,
    target_irr_basis: str = "project",
) -> float:
    """Compute IRR at CAPEX modified by factor (scales all CapexItem amounts)."""
    from domain.inputs import CapexStructure, CapexItem
    from dataclasses import replace

    def scale_item(item: CapexItem) -> CapexItem:
        return replace(item, amount_keur=item.amount_keur * factor)

    # Build new CapexStructure with scaled CapexItems
    scaled_capex = CapexStructure(
        epc_contract=scale_item(inputs.capex.epc_contract),
        production_units=scale_item(inputs.capex.production_units),
        epc_other=scale_item(inputs.capex.epc_other),
        grid_connection=scale_item(inputs.capex.grid_connection),
        ops_prep=scale_item(inputs.capex.ops_prep),
        insurances=scale_item(inputs.capex.insurances),
        lease_tax=scale_item(inputs.capex.lease_tax),
        construction_mgmt_a=scale_item(inputs.capex.construction_mgmt_a),
        commissioning=scale_item(inputs.capex.commissioning),
        audit_legal=scale_item(inputs.capex.audit_legal),
        construction_mgmt_b=scale_item(inputs.capex.construction_mgmt_b),
        contingencies=scale_item(inputs.capex.contingencies),
        taxes=scale_item(inputs.capex.taxes),
        project_acquisition=scale_item(inputs.capex.project_acquisition),
        project_rights=scale_item(inputs.capex.project_rights),
        idc_keur=inputs.capex.idc_keur * factor,
        commitment_fees_keur=inputs.capex.commitment_fees_keur * factor,
        bank_fees_keur=inputs.capex.bank_fees_keur * factor,
        other_financial_keur=inputs.capex.other_financial_keur * factor,
        vat_costs_keur=inputs.capex.vat_costs_keur * factor,
        reserve_accounts_keur=inputs.capex.reserve_accounts_keur * factor,
    )

    mod_inputs = replace(inputs, capex=scaled_capex)
    result = _run_waterfall_for_inputs(mod_inputs)
    return result.equity_irr if target_irr_basis == "equity" else result.project_irr


def _opex_sensitivity(
    inputs: ProjectInputs,
    factor: float,
    target_irr_basis: str = "project",
) -> float:
    """Compute IRR at OPEX modified by factor (scales all OpexItem amounts)."""
    from domain.inputs import OpexItem
    from dataclasses import replace

    # inputs.opex is a tuple of OpexItem; scale each one's y1_amount_keur
    scaled_opex = tuple(
        replace(item, y1_amount_keur=item.y1_amount_keur * factor)
        for item in inputs.opex
    )

    mod_inputs = replace(inputs, opex=scaled_opex)
    result = _run_waterfall_for_inputs(mod_inputs)
    return result.equity_irr if target_irr_basis == "equity" else result.project_irr


def _rate_sensitivity(
    inputs: ProjectInputs,
    delta_bps: float,
    target_irr_basis: str = "project",
) -> float:
    """Compute IRR at rate + delta_bps by adjusting base_rate."""
    from dataclasses import replace

    # all_in_rate = base_rate + margin_bps/10000, so adjust base_rate
    rate_adj = delta_bps / 10000.0
    mod_inputs = replace(
        inputs,
        financing=replace(inputs.financing, base_rate=inputs.financing.base_rate + rate_adj),
    )
    result = _run_waterfall_for_inputs(mod_inputs)
    return result.equity_irr if target_irr_basis == "equity" else result.project_irr


def run_tornado_analysis(
    inputs: ProjectInputs,
    target_irr_basis: str = "project",
) -> list[SensitivityResult]:
    """Run tornado analysis — one-way sensitivity for 5 key variables.

    Returns list[SensitivityResult], sorted by |impact_bps| descending.

    Variables:
    - PPA Tariff: ±20% range
    - Generation: ±20% range
    - CAPEX: ±20% range
    - OPEX: ±20% range
    - Interest Rate: ±150bps range
    """
    base_tariff = inputs.revenue.ppa_base_tariff
    base_gen = inputs.technical.operating_hours_p50
    base_capex = inputs.capex.hard_capex_keur
    base_opex = sum(item.y1_amount_keur for item in inputs.opex)
    results = []

    # PPA Tariff: low = -20%, high = +20%
    low_irr = _ppa_tariff_sensitivity(inputs, 0.80, target_irr_basis)
    high_irr = _ppa_tariff_sensitivity(inputs, 1.20, target_irr_basis)
    results.append(SensitivityResult(
        variable="PPA Tariff",
        low_value=base_tariff * 0.80,
        high_value=base_tariff * 1.20,
        low_irr=low_irr,
        high_irr=high_irr,
        impact_bps=(high_irr - low_irr) * 10000,
    ))

    # Generation: low = -20%, high = +20%
    low_irr = _generation_sensitivity(inputs, 0.80, target_irr_basis)
    high_irr = _generation_sensitivity(inputs, 1.20, target_irr_basis)
    results.append(SensitivityResult(
        variable="Generation",
        low_value=base_gen * 0.80,
        high_value=base_gen * 1.20,
        low_irr=low_irr,
        high_irr=high_irr,
        impact_bps=(high_irr - low_irr) * 10000,
    ))

    # CAPEX: low = -20% (more negative = better), high = +20%
    low_irr = _capex_sensitivity(inputs, 0.80, target_irr_basis)
    high_irr = _capex_sensitivity(inputs, 1.20, target_irr_basis)
    results.append(SensitivityResult(
        variable="CAPEX",
        low_value=base_capex * 0.80,
        high_value=base_capex * 1.20,
        low_irr=low_irr,
        high_irr=high_irr,
        impact_bps=(high_irr - low_irr) * 10000,
    ))

    # OPEX: low = -20% (lower cost = higher IRR), high = +20%
    low_irr = _opex_sensitivity(inputs, 0.80, target_irr_basis)
    high_irr = _opex_sensitivity(inputs, 1.20, target_irr_basis)
    results.append(SensitivityResult(
        variable="OPEX",
        low_value=base_opex * 0.80,
        high_value=base_opex * 1.20,
        low_irr=low_irr,
        high_irr=high_irr,
        impact_bps=(high_irr - low_irr) * 10000,
    ))

    # Interest Rate: low = +150bps (higher rate = lower IRR), high = -150bps
    base_rate = inputs.financing.base_rate + inputs.financing.margin_bps / 10000.0
    low_irr = _rate_sensitivity(inputs, 150, target_irr_basis)   # rate +150bps
    high_irr = _rate_sensitivity(inputs, -150, target_irr_basis)  # rate -150bps
    results.append(SensitivityResult(
        variable="Interest Rate",
        low_value=base_rate + 0.015,
        high_value=base_rate - 0.015,
        low_irr=low_irr,
        high_irr=high_irr,
        impact_bps=(high_irr - low_irr) * 10000,
    ))

    # Sort by |impact_bps| descending
    results.sort(key=lambda r: abs(r.impact_bps), reverse=True)
    return results


def run_spider_analysis(
    inputs: ProjectInputs,
    n_steps: int = 7,
    target_irr_basis: str = "project",
) -> dict:
    """Run spider analysis — multi-variable sensitivity matrix.

    Returns:
        dict with keys:
        - variables: list of variable names
        - steps: list of step fractions (e.g., [-0.20, -0.13, -0.07, 0.0, 0.07, 0.13, 0.20])
        - matrix: dict[variable] → list of IRR values per step
    """
    steps = []
    if n_steps == 7:
        steps = [-0.20, -0.13, -0.07, 0.0, 0.07, 0.13, 0.20]
    elif n_steps == 5:
        steps = [-0.20, -0.10, 0.0, 0.10, 0.20]
    else:
        import numpy as np
        steps = list(np.linspace(-0.20, 0.20, n_steps))

    variables = ["PPA Tariff", "Generation", "CAPEX", "OPEX", "Interest Rate"]
    matrix = {}

    base_tariff = inputs.revenue.ppa_base_tariff
    base_gen = inputs.technical.operating_hours_p50
    base_capex = inputs.capex.hard_capex_keur
    base_opex = sum(item.y1_amount_keur for item in inputs.opex)
    base_rate = inputs.financing.base_rate + inputs.financing.margin_bps / 10000.0

    for var in variables:
        irr_values = []
        for step in steps:
            factor = 1.0 + step
            if var == "PPA Tariff":
                irr = _ppa_tariff_sensitivity(inputs, factor, target_irr_basis)
            elif var == "Generation":
                irr = _generation_sensitivity(inputs, factor, target_irr_basis)
            elif var == "CAPEX":
                irr = _capex_sensitivity(inputs, factor, target_irr_basis)
            elif var == "OPEX":
                irr = _opex_sensitivity(inputs, factor, target_irr_basis)
            elif var == "Interest Rate":
                # Rate sensitivity: step maps to ±150bps
                delta_bps = step * 150
                irr = _rate_sensitivity(inputs, delta_bps, target_irr_basis)
            irr_values.append(irr)
        matrix[var] = irr_values

    return {
        "variables": variables,
        "steps": steps,
        "matrix": matrix,
    }
