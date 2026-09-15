"""Uncached waterfall core used by both Streamlit cache and headless calibration.

This module must not import Streamlit. It is the production calculation path
that CLI scripts, tests, and app/cache.py can all call.
"""
from __future__ import annotations

import csv
import warnings
from pathlib import Path
from typing import TYPE_CHECKING

from finco_core.ebitda import calculate_ebitda_keur

if TYPE_CHECKING:
    from domain.inputs import ProjectInputs
    from domain.period_engine import PeriodEngine
    from domain.waterfall.waterfall_engine import WaterfallResult


def run_waterfall_v3_core(
    inputs: "ProjectInputs",
    engine: "PeriodEngine",
    rate_per_period: float,
    tenor_periods: int,
    target_dscr: float = 1.15,
    lockup_dscr: float = 1.10,
    tax_rate: float = 0.10,
    dsra_months: int = 6,
    shl_amount: float = 0.0,
    shl_rate: float = 0.0,
    shl_idc_keur: float = 0.0,
    shl_repayment_method: str = "bullet",
    shl_tenor_years: int = 0,
    shl_wht_rate: float = 0.0,
    discount_rate_project: float = 0.0641,
    discount_rate_equity: float = 0.0965,
    fixed_debt_keur: float | None = None,
    fixed_ds_keur: float | None = None,
    rate_schedule: list[float] | None = None,
    senior_sculpting_config: object | None = None,
    equity_irr_method: str = "equity_only",
    share_capital_keur: float = 0.0,
    sculpt_capex_keur: float = 0.0,
    debt_sizing_method: str = "dscr_sculpt",
    dscr_schedule: list[float] | None = None,
    advanced_opex_line_items: tuple | None = None,
    advanced_capex_line_items: tuple | None = None,
    advanced_capex_depreciation_schedule: "DepreciationSchedule | None" = None,
    # Generic Wind Reference-specific: cap SHL sweep cash at R99-equivalent (reference-compatible).
    # Prevents SHL principal from consuming cash that Excel would hold back.
    use_senior_sweep_cash_cap_for_shl: bool = False,
    # Phase 7F C1a: propagated for config identity only; not wired into runtime yet.
    use_reference_covenant_input_engine: bool = False,
    use_shl_fcf_waterfall_engine: bool = False,
    use_tax_bridge_engine: bool = False,
    use_shl_gross_accrued_for_pnl: bool = False,
    use_reference_shl_repayment_alignment: bool = False,
    reference_shl_principal_eligibility_start_period: int | None = None,
    shl_fcf_waterfall_cash_schedule_keur: tuple[float, ...] = (),
    shl_fcf_waterfall_minimum_cash_retained_keur: float = 0.0,
    generic_wind_reference_cit_cash_tax_start_operating_index: int | None = None,
    use_shl_canonical_engine: bool = False,
    use_depreciation_canonical_engine: bool = False,
    use_senior_debt_sizing_engine: bool = False,
    # Phase 23A: wire explicit reference senior debt service schedule into runtime.
    # When True and use_senior_debt_sizing_engine=True, per-period senior debt
    # service is taken from the frozen schedule (canonical sizing capacity) and
    # DSCR becomes a backward-computed output. Default False preserves behavior.
    use_frozen_excel_senior_debt_schedule: bool = False,
    # CO2 revenue bridge — wire CO2 certificate revenue into period.revenue_keur.
    # Activated by explicit flag; no project-code dispatch. default=False.
    # R99/R102: BLOCKED — CO2 bridge affects revenue/EBITDA only, no CIT or distribution change.
    use_co2_revenue_bridge: bool = False,
    # CO2→CIT bridge — add CO2 to taxable income (not EBITDA).
    # Activated by explicit flag; no project-code dispatch. default=False.
    # R99/R102: BLOCKED — only taxable income affected.
    use_co2_cit_bridge: bool = False,
    # Phase 9B: Dual-run validation — compare DA equity_distribution_paid_keur vs
    # WaterfallEngine.distribution_keur without changing runtime authority.
    # R99/R102: BLOCKED — no promotion in dual-run mode.
    use_dualrun_validation: bool = False,
    # Phase 9C: Wire DA equity_distribution_paid_keur into runtime distribution.
    # Flag=True: distribution_keur = DA equity_distribution_paid_keur (audit metadata attached).
    # Flag=False: exact legacy runtime behavior, distribution_keur unchanged.
    # R99/R102: BLOCKED — no promotion. SHL R102: UNCONNECTED.
    use_distributionaccount_runtime_wiring: bool = False,
) -> dict:
    """Run the full waterfall without Streamlit cache dependencies.

    FINCO Model calibration note:
    - `domain.waterfall.run_waterfall()` sculpts debt using the first
      `tenor_periods` entries of the EBITDA schedule.
    - If construction rows are included in that list, sculpting starts with two
      zero-CFADS periods while debt repayment output starts at the first
      operating period. That creates a principal/interest timing mismatch.
    - The headless calibration core therefore passes operation-only periods and
      operation-only schedules into the waterfall engine.

    advanced_opex_line_items: if provided (non-empty tuple), the advanced
      OpexLineItem engine is used to generate the OPEX schedule instead of
      the legacy OpexItem/OpexParams path. This enables granular per-line-item
      OPEX modeling with manual/hardcoded override support.

    advanced_capex_depreciation_schedule: if provided (from
      app.depreciation_engine.generate_schedule()), the new asset-class
      depreciation schedule is used for the tax-shield calculation instead of
      the legacy CapexItem-based schedule. This enables per-asset-class
      depreciable lives (solar modules 25 yr, inverters 10 yr, etc.).
    """
    from domain.waterfall.waterfall_engine import run_waterfall
    from domain.revenue.generation import full_revenue_schedule, full_generation_schedule, revenue_decomposition_schedule
    from domain.opex.projections import opex_schedule_period
    from domain.financing.depreciation_schedule import build_depreciation_schedule
    from finco_core.inputs._models import TaxDepreciationMode

    _ = use_reference_covenant_input_engine  # C1a intentionally leaves runtime behavior unchanged.
    construction_diagnostic = None
    if getattr(inputs.info, "use_construction_schedule_engine", False):
        from domain.construction.runtime_adapter import build_runtime_construction_schedule

        construction_diagnostic = build_runtime_construction_schedule(inputs)

    all_periods = list(engine.periods())
    periods_list = [p for p in all_periods if p.is_operation]
    revenue_dict = full_revenue_schedule(inputs, engine)
    generation_dict = full_generation_schedule(inputs, engine)

    # Phase 9 CO2 revenue bridge: extract CO2 certificate revenue by period.
    # When use_co2_revenue_bridge=True, CO2 is added to period.revenue_keur
    # (and therefore EBITDA) before the waterfall run.
    # Activation is controlled by the use_co2_revenue_bridge flag; no project-code dispatch.
    # R99/R102: BLOCKED — CO2 bridge only affects revenue/EBITDA chain.
    co2_revenue_by_period: dict[int, float] = {}
    co2_base_revenue_by_period: dict[int, float] = {}
    if use_co2_revenue_bridge:
        decompositions = revenue_decomposition_schedule(inputs, engine)
        for period_idx, decomp in decompositions.items():
            if decomp.get("is_operation", False):
                co2_keur = decomp.get("co2_revenue_keur", 0.0)
                base_rev = revenue_dict.get(period_idx, 0.0)
                co2_revenue_by_period[period_idx] = co2_keur
                co2_base_revenue_by_period[period_idx] = base_rev

    # CO2→CIT bridge: extract CO2 for taxable income injection.
    # CO2 is added directly to taxable income in TaxEngine (not EBITDA).
    # Activation is controlled by the use_co2_cit_bridge flag; no project-code dispatch.
    # Must not be used simultaneously with use_co2_revenue_bridge=True.
    # R99/R102: BLOCKED — only taxable income / cash tax affected.
    co2_cit_bridge_by_period: dict[int, float] = {}
    if use_co2_cit_bridge:
        if use_co2_revenue_bridge:
            raise ValueError(
                "use_co2_cit_bridge and use_co2_revenue_bridge cannot both be True; "
                "they target different computation chains"
            )
        decompositions = revenue_decomposition_schedule(inputs, engine)
        for period_idx, decomp in decompositions.items():
            if decomp.get("is_operation", False):
                co2_keur = decomp.get("co2_revenue_keur", 0.0)
                co2_cit_bridge_by_period[period_idx] = co2_keur

    # OPEX: default legacy path remains unchanged. The Phase 7H line-item
    # engine is available only behind an explicit project/config flag.
    if getattr(inputs.info, "use_opex_line_item_engine", False):
        from domain.opex.runtime_adapter import build_runtime_opex_schedule

        opex_period = build_runtime_opex_schedule(inputs, engine).period_schedule_keur
    elif advanced_opex_line_items:
        from app.opex_engine import apply_opex_line_items_to_project
        horizon_years = inputs.info.horizon_years
        annual_opex = apply_opex_line_items_to_project(advanced_opex_line_items, horizon_years)
        # Convert annual → per-period using period day fraction
        opex_period: dict[int, float] = {}
        for p in periods_list:
            annual_val = annual_opex[p.year_index] if p.year_index < len(annual_opex) else 0.0
            opex_period[p.index] = annual_val * p.day_fraction
    else:
        opex_period = opex_schedule_period(inputs, engine)

    # CAPEX: use advanced CapexLineItems if provided, otherwise fall back to legacy path
    # Computes total_capex_override from the sum of CapexLineItem amounts.
    # This is passed to run_waterfall() to override inputs.capex.total_capex.
    total_capex_override: float | None = None
    if advanced_capex_line_items:
        from app.capex_engine import generate_capex_schedule
        capex_sched = generate_capex_schedule(advanced_capex_line_items, tenor_periods)
        total_capex_override = sum(capex_sched.total_by_period)
    else:
        total_capex_override = None

    horizon_years = inputs.info.horizon_years

    # Depreciation schedule: use advanced CapexLineItem schedule if provided,
    # otherwise fall back to legacy CapexItem path for backward compatibility.
    if advanced_capex_depreciation_schedule is not None:
        # Map DepreciationSchedule (0-based year index) → {year_index: annual_dep}
        dep_schedule_annual = {
            y + 1: advanced_capex_depreciation_schedule.total_by_period[y]
            for y in range(len(advanced_capex_depreciation_schedule.total_by_period))
        }
    else:
        # Use book_depreciable_capex_items() so financing-cost components (IDC,
        # commitment fees, bank fees, VAT) enter the depreciable basis with their
        # correct per-item useful lives encoded via useful_life_override.
        dep_schedule_annual = build_depreciation_schedule(
            capex_items=inputs.capex.book_depreciable_capex_items(),
            horizon_years=horizon_years,
            senior_tenor_years=inputs.financing.senior_tenor_years,
        )

    ebitda_schedule: list[float] = []
    revenue_schedule: list[float] = []
    generation_schedule: list[float] = []
    depreciation_schedule: list[float] = []
    opex_schedule: list[float] = []

    for p in periods_list:
        rev = revenue_dict.get(p.index, 0)
        # CO2 bridge: add CO2 certificate revenue to base revenue.
        # When use_co2_revenue_bridge=True: adds to EBITDA via rev→ebitda chain.
        # When use_co2_cit_bridge=True: SKIP here; CO2 added to taxable income only.
        # R99/R102 remain unchanged.
        if use_co2_revenue_bridge and not use_co2_cit_bridge:
            co2_add = co2_revenue_by_period.get(p.index, 0.0)
            rev = rev + co2_add
        gen = generation_dict.get(p.index, 0)
        opex = opex_period.get(p.index, 0)
        ebitda = calculate_ebitda_keur(rev, opex)
        annual_dep = dep_schedule_annual.get(p.year_index, 0.0)
        dep = annual_dep * p.day_fraction

        revenue_schedule.append(rev)
        generation_schedule.append(gen)
        ebitda_schedule.append(ebitda)
        depreciation_schedule.append(dep)
        opex_schedule.append(opex)

    # Explicit tax-depreciation schedule derived from policy in inputs.tax.
    # BOOK_BASED_PERCENTAGE: tax_dep = book_dep * deductible_pct.
    # Generic Solar Reference: 100% (reference methodology P&L shows no dep add-back in Fiscal Reintegration).
    _tax_dep_mode = getattr(inputs.tax, 'tax_depreciation_mode', TaxDepreciationMode.BOOK_BASED_PERCENTAGE)
    _tax_dep_pct = getattr(inputs.tax, 'tax_deductible_book_dep_pct', 1.0)
    if _tax_dep_mode == TaxDepreciationMode.BOOK_BASED_PERCENTAGE:
        tax_depreciation_schedule: list[float] = [d * _tax_dep_pct for d in depreciation_schedule]
    else:
        # STATUTORY_TAX_SCHEDULE and CUSTOM_SCHEDULE are not yet implemented.
        # Failing fast here prevents silent incorrect output — no fallback to book dep.
        # To use these modes, supply a pre-computed schedule or implement the required runtime.
        raise NotImplementedError(
            f"TaxDepreciationMode.{_tax_dep_mode.name} is not yet implemented. "
            "Only BOOK_BASED_PERCENTAGE is currently supported. "
            "Supply a BOOK_BASED_PERCENTAGE configuration, or implement the required "
            "schedule logic before activating this mode. "
            "No silent fallback to book depreciation is permitted."
        )

    # Resolve total_capex — use advanced CAPEX if provided, else fall back to inputs
    total_capex_for_waterfall = (
        total_capex_override if total_capex_override is not None
        else inputs.capex.total_capex
    )

    result = run_waterfall(
        ebitda_schedule=ebitda_schedule,
        revenue_schedule=revenue_schedule,
        generation_schedule=generation_schedule,
        depreciation_schedule=depreciation_schedule,
        opex_schedule=opex_schedule,
        periods=periods_list,
        total_capex=total_capex_for_waterfall,
        rate_per_period=rate_per_period,
        tenor_periods=tenor_periods,
        target_dscr=target_dscr,
        lockup_dscr=lockup_dscr,
        tax_rate=tax_rate,
        dsra_months=dsra_months,
        shl_amount=shl_amount,
        shl_rate=shl_rate,
        shl_idc_keur=shl_idc_keur,
        shl_repayment_method=shl_repayment_method,
        shl_tenor_years=shl_tenor_years,
        shl_wht_rate=shl_wht_rate,
        use_shl_fcf_waterfall_engine=use_shl_fcf_waterfall_engine,
        shl_fcf_waterfall_cash_schedule_keur=shl_fcf_waterfall_cash_schedule_keur,
        shl_fcf_waterfall_minimum_cash_retained_keur=shl_fcf_waterfall_minimum_cash_retained_keur,
        discount_rate_project=discount_rate_project,
        discount_rate_equity=discount_rate_equity,
        financial_close=inputs.info.financial_close,
        gearing_ratio=inputs.financing.gearing_ratio,
        fixed_debt_keur=fixed_debt_keur if fixed_debt_keur is not None else getattr(inputs.financing, "fixed_debt_keur", None),
        fixed_ds_keur=fixed_ds_keur if fixed_ds_keur is not None else getattr(inputs.financing, "fixed_ds_keur", None),
        rate_schedule=rate_schedule,
        senior_sculpting_config=senior_sculpting_config,
        idc_keur=inputs.capex.idc_keur,
        bank_fees_keur=inputs.capex.bank_fees_keur,
        commitment_fees_keur=inputs.capex.commitment_fees_keur,
        equity_irr_method=equity_irr_method,
        share_capital_keur=share_capital_keur,
        sculpt_capex_keur=sculpt_capex_keur,
        prior_tax_loss_keur=inputs.tax.initial_tax_loss_keur,
        debt_sizing_method=debt_sizing_method,
        dscr_schedule=dscr_schedule if dscr_schedule is not None else getattr(inputs.financing, "dscr_schedule", None),
        use_senior_sweep_cash_cap_for_shl=use_senior_sweep_cash_cap_for_shl,
        use_reference_shl_repayment_alignment=use_reference_shl_repayment_alignment,
        reference_shl_principal_eligibility_start_period=(
            reference_shl_principal_eligibility_start_period
        ),
        co2_cit_bridge_by_period=co2_cit_bridge_by_period,
        tax_depreciation_schedule=tax_depreciation_schedule,
    )
    result.project_code = getattr(inputs.info, "code", "")
    # Phase 9 CO2 revenue bridge audit metadata.
    # R99/R102: BLOCKED — bridge only affects revenue/EBITDA.
    if use_co2_revenue_bridge:
        result._co2_revenue_bridge = {
            "enabled": True,
            "co2_by_period": co2_revenue_by_period,
            "base_revenue_by_period": co2_base_revenue_by_period,
            "project_code": getattr(inputs.info, "code", ""),
        }
        # Annotate each period with its CO2 bridge contribution for audit visibility
        for wp in result.periods:
            p_idx = getattr(wp, "period", None)
            if p_idx in co2_revenue_by_period:
                setattr(wp, "co2_revenue_bridge_keur", co2_revenue_by_period[p_idx])
    else:
        result._co2_revenue_bridge = {"enabled": False}

    # Phase 9 CO2→CIT bridge audit metadata.
    # R99/R102: BLOCKED — bridge only affects taxable income / cash tax.
    if use_co2_cit_bridge:
        result._co2_cit_bridge = {
            "enabled": True,
            "co2_by_period": co2_cit_bridge_by_period,
            "project_code": getattr(inputs.info, "code", ""),
        }
        # Annotate each period with its CO2 CIT bridge contribution for audit visibility
        for wp in result.periods:
            p_idx = getattr(wp, "period", None)
            if p_idx in co2_cit_bridge_by_period:
                setattr(wp, "co2_cit_bridge_keur", co2_cit_bridge_by_period[p_idx])
    else:
        result._co2_cit_bridge = {"enabled": False}
    result.use_shl_gross_accrued_for_pnl = use_shl_gross_accrued_for_pnl
    if use_shl_gross_accrued_for_pnl or use_tax_bridge_engine:
        raise RuntimeError(
            "Legacy calibration bridge is not available in the sanitized FINCO Protocol runtime. "
            "Use the canonical deterministic engine path instead."
        )
    if construction_diagnostic is not None:
        result.construction_schedule_diagnostic = construction_diagnostic
    # Phase 8.1: wire canonical ShlEngine into runtime when flag is True.
    # R99/R102: BLOCKED — canonical wiring affects SHL fields only.
    if use_shl_canonical_engine:
        from domain.shl.canonical_wiring import wire_canonical_shl_into_waterfall
        wiring_result = wire_canonical_shl_into_waterfall(
            waterfall_result=result,
            shl_amount_keur=shl_amount,
            shl_rate=shl_rate,
            shl_idc_keur=shl_idc_keur,
            shl_repayment_method=shl_repayment_method,
            shl_wht_rate=shl_wht_rate,
            shl_tenor_years=shl_tenor_years,
        )
        from domain.shl.canonical_wiring import apply_canonical_shl_wiring
        apply_canonical_shl_wiring(result, wiring_result)
        result._canonical_shl_wiring = wiring_result
    # Phase 8: wire canonical DepreciationEngine into runtime when flag is True.
    # Canonical engine computes per-asset-class book and tax depreciation;
    # its outputs override waterfall period depreciation_keur and
    # tax_depreciation_audit_keur after run_waterfall completes.
    # R99/R102: BLOCKED — depreciation wiring affects P&L and tax-shield only.
    if use_depreciation_canonical_engine:
        from domain.depreciation.canonical_wiring import build_canonical_depreciation_wiring
        dep_wiring = build_canonical_depreciation_wiring(
            project_name=getattr(inputs.info, 'name', 'Project'),
            capex_items=inputs.capex.book_depreciable_capex_items(),
            horizon_years=horizon_years,
            cod_period=2,  # semiannual: COD = period 2 (first operating period)
            period_frequency="semiannual",
        )
        if dep_wiring.canonical_engine_result is not None:
            # Override waterfall period depreciation fields with canonical values
            from domain.depreciation.canonical_wiring import wire_canonical_depreciation_into_waterfall
            wiring_result = wire_canonical_depreciation_into_waterfall(
                dep_wiring.canonical_engine_result,
                period_count=len(result.periods),
            )
            for i, period in enumerate(result.periods):
                if i < len(wiring_result.book_depreciation_by_period):
                    period.depreciation_keur = wiring_result.book_depreciation_by_period[i]
                if i < len(wiring_result.tax_depreciation_by_period):
                    period.tax_depreciation_audit_keur = wiring_result.tax_depreciation_by_period[i]
            result._canonical_depreciation_wiring = wiring_result
    # Phase 8: canonical SeniorDebtSizing wiring.
    # Computes debt service capacity from explicit sizing_cfads and per-period dscr_schedule.
    # Result is attached as _canonical_senior_debt_sizing audit attribute.
    # R99/R102: BLOCKED — sizing wiring does not touch distribution gates.
    # R99/R102: BLOCKED — this wiring does not affect R99/R102 gates.
    if use_senior_debt_sizing_engine:
        from domain.senior_debt_sizing.canonical_wiring import (
            build_canonical_senior_debt_sizing_from_inputs,
        )
        # Extract EBITDA schedule and DSCR schedule from project inputs
        op_periods = [p for p in result.periods if getattr(p, 'is_operation', False)]
        horizon_years = inputs.info.horizon_years
        ebitda_schedule = []
        for p in op_periods:
            ebitda_val = (
                getattr(p, 'revenue_keur', 0.0)
                - getattr(p, 'opex_keur', 0.0)
            )
            ebitda_schedule.append(ebitda_val)
        dscr_schedule = (
            inputs.financing.dscr_schedule
            if inputs.financing.dscr_schedule
            else [1.15] * (horizon_years * 2)
        )

        # Public/corporate runtime deliberately excludes historical reference-policy
        # sizing inputs. Canonical sizing is derived from the current deterministic
        # model inputs only. Explicit external schedules must enter through a typed,
        # separately validated authority path rather than repository fixtures.
        explicit_sizing_cfads = None
        explicit_dscr_schedule = None

        # Use fixture DSCR schedule when available, otherwise fall back to inputs
        if explicit_dscr_schedule is not None:
            dscr_for_sizing = explicit_dscr_schedule
        else:
            dscr_for_sizing = tuple(dscr_schedule[:len(ebitda_schedule)])

        sizing_result = build_canonical_senior_debt_sizing_from_inputs(
            project_name=getattr(inputs.info, 'name', 'Project'),
            project_code=getattr(inputs.info, 'code', ''),
            ebitda_schedule=tuple(ebitda_schedule),
            tax_rate=inputs.tax.corporate_rate,
            dscr_schedule=dscr_for_sizing,
            use_explicit_sizing_cfads=(explicit_sizing_cfads is not None),
            explicit_sizing_cfads=explicit_sizing_cfads,
        )
        result._canonical_senior_debt_sizing = sizing_result

    # Compatibility path: frozen senior debt-service capacity runtime wiring.
    # When the legacy compatibility flag and canonical sizing engine are both enabled,
    # per-period senior debt-service capacity is taken from the canonical sizing result
    # (canonical sizing capacity = sizing_cfads / target_dscr) instead of the
    # waterfall-computed sculpted service. DSCR becomes a backward-computed output.
    #
    # Guardrails:
    #   - use_senior_debt_sizing_engine must be True (canonical result required)
    #   - _canonical_senior_debt_sizing must be present (sizing result attached)
    #   - synthetic references only after explicit validation
    #
    # R99/R102: BLOCKED — frozen schedule wiring does not touch distribution gates.
    # G20: BLOCKED — no governance promotion in this phase.
    if use_frozen_excel_senior_debt_schedule and use_senior_debt_sizing_engine:
        canon = getattr(result, '_canonical_senior_debt_sizing', None)
        if canon is not None:
            frozen_ds = getattr(canon, 'debt_service_capacity_keur_by_period', None)
            if frozen_ds:
                op_periods = [
                    (i, p) for i, p in enumerate(result.periods)
                    if getattr(p, 'is_operation', False)
                ]
                # Stack Q: sizing CFADS and active DS indices (Generic Solar Reference fixture only).
                # When available, use sizing CFADS for period.dscr instead of actual
                # EBITDA — this aligns the reported DSCR with the reference methodology basis.
                _sizing_cfads = getattr(result, '_generic_solar_reference_sizing_cfads', None)
                _csv_ds_active = getattr(result, '_generic_solar_reference_csv_ds_active_op_indices', None)

                # Y1: track which op-period indices have frozen_value > 0 so
                # DSCR averaging uses only fixture-active periods (same basis as reference methodology).
                _frozen_active_op_indices: set = set()
                for op_idx, (period_idx, period) in enumerate(op_periods):
                    if op_idx < len(frozen_ds):
                        frozen_value = frozen_ds[op_idx]
                        # Y1: Do NOT override period.senior_ds_keur.
                        # Keep senior_ds_keur = senior_interest_keur + senior_principal_keur
                        # so that sum(period.senior_ds_keur) == result.total_senior_ds_keur.
                        # The frozen capacity is used only for DSCR computation below.
                        period._frozen_senior_ds_capacity_keur = frozen_value
                        # Attach audit metadata
                        period._frozen_senior_ds_override = True
                        period._frozen_senior_ds_source = getattr(
                            inputs.financing, 'frozen_schedule_note',
                            'canonical_sizing_capacity'
                        )
                        # Recompute DSCR using frozen service.
                        # Stack Q: prefer sizing CFADS from fixture (reference methodology FCF for banks)
                        # over actual EBITDA. Sizing CFADS = canonical sizing CFADS,
                        # which is the CFADS used in the reference methodology for DSCR computation.
                        if _sizing_cfads is not None and op_idx < len(_sizing_cfads):
                            cfads = _sizing_cfads[op_idx]
                        else:
                            cfads = getattr(period, 'cfads_keur', None)
                            if cfads is None:
                                cfads = getattr(period, 'revenue_keur', 0.0) - getattr(period, 'opex_keur', 0.0)
                        # Y1: only override DSCR when the fixture has a non-zero
                        # DS value; preserve engine DSCR for zero-fixture periods.
                        if frozen_value > 0:
                            period.dscr = cfads / frozen_value
                            _frozen_active_op_indices.add(op_idx)
                # Recompute result-level DSCR averages to match reference methodology.
                # Stack Q: for Generic Solar Reference, filter to CSV-active DS periods only (ds_r57 > 0)
                # to exclude canonical-only DS periods (where reference debt service=0 but canonical
                # sizing produces non-zero capacity from residual sizing CFADS).
                # This aligns actual_avg_dscr with the reference methodology DSCR computation basis.
                if _csv_ds_active is not None:
                    # Generic Solar Reference fixture path: use CSV-active periods and sizing CFADS basis.
                    _active_dsrs = [
                        p.dscr
                        for op_i, (_, p) in enumerate(op_periods)
                        if op_i in _csv_ds_active
                        and p.dscr not in (float('inf'), float('-inf'))
                        and p.dscr == p.dscr  # NaN guard
                    ]
                else:
                    # Y1: use fixture-active op-period indices for DSCR averaging.
                    # Only periods where frozen_value > 0 (fixture has DS) are included,
                    # matching the reference methodology DSCR computation basis.
                    _active_dsrs = [
                        p.dscr
                        for op_i, (_, p) in enumerate(op_periods)
                        if op_i in _frozen_active_op_indices
                        and p.dscr not in (float('inf'), float('-inf'))
                        and p.dscr == p.dscr  # NaN guard
                    ]
                if _active_dsrs:
                    _new_avg_dscr = sum(_active_dsrs) / len(_active_dsrs)
                    if _new_avg_dscr < result.actual_avg_dscr:
                        result.actual_avg_dscr = _new_avg_dscr
                        result.actual_min_dscr = min(_active_dsrs)
                # Attach result-level audit flag.
                # _frozen_senior_ds_wired is set ONLY when actual frozen schedule was used.
                # If fixture loading failed, _frozen_senior_ds_wired stays False so downstream
                # knows the frozen path was NOT fully reference-policy.
                if getattr(result, '_frozen_fixture_loaded', False):
                    result._frozen_senior_ds_wired = True
                    result._frozen_senior_ds_note = (
                        f"Frozen senior DS capacity wired for {getattr(inputs.info, 'code', '?')}. "
                        f"DSCR is now a backward-computed output. "
                        f"Canonical sizing CFADS; repository fixture loading is disabled."
                    )
                else:
                    # Fixture not loaded (Generic Solar Reference or Generic Wind Reference with missing fixture) —
                    # fall back to ebitda-derived canonical capacity.
                    # Do NOT set _frozen_senior_ds_wired=True to avoid false implication
                    # of reference-policy schedule.
                    result._frozen_senior_ds_wired = False
                    result._frozen_senior_ds_note = (
                        f"Frozen senior DS capacity wired (fallback: ebitda-derived capacity) "
                        f"for {getattr(inputs.info, 'code', '?')}. "
                        f"Repository fixture loading is disabled."
                    )
            else:
                warnings.warn(
                    "[Phase 23A] legacy frozen-schedule compatibility flag enabled but "
                    "canonical result has no debt_service_capacity_keur_by_period. "
                    "Falling back to existing behavior."
                )
        else:
            warnings.warn(
                "[Phase 23A] legacy frozen-schedule compatibility flag enabled but "
                "_canonical_senior_debt_sizing not found. "
                "Ensure use_senior_debt_sizing_engine=True."
            )

    # Phase 9B: Dual-run validation — side-by-side DA vs WE comparison.
    # NO runtime routing — waterfall result is not modified.
    # R99/R102: BLOCKED — DA remains audit-only.
    if use_dualrun_validation:
        _attach_dualrun_validation(result, inputs, periods_list)

    # Phase 9C: Wire DA equity_distribution_paid_keur into runtime distribution.
    # Flag=True: distribution_keur = DA equity_distribution_paid_keur.
    # Flag=False: exact legacy runtime behavior, distribution_keur unchanged.
    # R99/R102: BLOCKED. SHL R102: UNCONNECTED. Sponsor: reads distribution_keur only.
    if use_distributionaccount_runtime_wiring:
        _apply_distributionaccount_runtime_wiring(result, inputs)

    return result


def _apply_distributionaccount_runtime_wiring(
    result: "WaterfallResult",
    inputs: "ProjectInputs",
) -> None:
    """Wire DA equity_distribution_paid_keur into runtime distribution_keur.

    When use_distributionaccount_runtime_wiring=True, the waterfall result's
    distribution_keur is replaced with DA's equity_distribution_paid_keur.
    Audit metadata is attached to each period and the result.

    NO runtime routing when flag=False. distribution_keur remains unchanged.
    R99/R102: BLOCKED in DA (governed mode). SHL R102: unconnected.
    """
    from domain.distribution_account.engine import DistributionAccountEngine
    compute_da = DistributionAccountEngine.compute
    from domain.distribution_account.inputs import (
        CovenantGatePolicy,
        DistributionAccountInputs,
        DistributionAccountPeriodInput,
    )

    is_reference_wind = (getattr(inputs.info, "code", "") == "REF-WIND-B")
    is_reference_solar = (getattr(inputs.info, "code", "") == "REF-SOLAR-A")
    covenant_gate_policy = inputs.financing.covenant_gate_policy
    senior_tenor_years = inputs.financing.senior_tenor_years

    # Covenant gate policy: DA runtime wiring only applies to R99_R102_APPLICABLE projects.
    if covenant_gate_policy != CovenantGatePolicy.R99_R102_APPLICABLE:
        result.distribution_source = "covenant_gate_not_applicable"
        result.da_paid_distribution_keur = 0.0
        result.legacy_distribution_keur = result.total_distribution_keur
        result.distribution_wiring_delta_keur = 0.0
        for wp in result.periods:
            wp.distribution_source = "covenant_gate_not_applicable"
            wp.da_paid_distribution_keur = 0.0
            wp.legacy_distribution_keur = wp.distribution_keur
            wp.distribution_wiring_delta_keur = 0.0
        return

    # Build DA period inputs using the same cash-source logic as dual-run
    da_period_inputs: list[DistributionAccountPeriodInput] = []
    for wp in result.periods:
        p_idx = getattr(wp, "period", None)
        if p_idx is None:
            continue

        r99_fcf = getattr(wp, "r99_fcf_for_distribution_keur", 0.0)
        cf_after_reserves = getattr(wp, "cf_after_reserves_keur", 0.0)
        cf_after_tax = getattr(wp, "cf_after_tax_keur", 0.0)
        senior_ds = getattr(wp, "senior_ds_keur", 0.0)

        # Use the same cash source selection as dual-run
        if r99_fcf > 0 and cf_after_reserves > 0 and abs(r99_fcf - cf_after_reserves) < 0.01:
            post_shl_cash = r99_fcf
        elif cf_after_reserves > 0:
            post_shl_cash = cf_after_reserves
        else:
            post_shl_cash = max(0.0, cf_after_tax - senior_ds)

        post_senior_cash = max(0.0, cf_after_tax - senior_ds)

        da_period_inputs.append(DistributionAccountPeriodInput(
            period_index=p_idx,
            operating_period_index=getattr(wp, "operating_period_index", p_idx),
            period_date=getattr(wp, "date", None) or __import__("datetime").date(2029, 12, 31),
            opening_distribution_account_balance_keur=0.0,
            post_senior_cash_available_keur=post_senior_cash,
            post_shl_cash_available_keur=post_shl_cash,
            senior_debt_service_keur=senior_ds,
            actual_dscr=getattr(wp, "dscr", 1.5),
            target_distribution_dscr=1.0,
            dsra_current_balance_keur=getattr(wp, "dsra_balance_keur", 0.0),
            dsra_required_balance_keur=getattr(wp, "dsra_balance_keur", 0.0),
            is_reference_wind=is_reference_wind,
            is_reference_solar=is_reference_solar,
            senior_tenor_years=senior_tenor_years,
            minimum_cash_reserve_keur=0.0,
            runtime_economic_mode=True,  # Runtime staging mode: gates for explicit wiring only
        ))

    da_inputs = DistributionAccountInputs(
        project_name=getattr(inputs.info, "name", "Project"),
        period_inputs=tuple(da_period_inputs),
        is_reference_wind=is_reference_wind,
        is_reference_solar=is_reference_solar,
        covenant_gate_policy=covenant_gate_policy,
    )

    da_result = compute_da(da_inputs)

    # Wire DA output into waterfall result
    total_da_paid = 0.0
    for wp, da_period in zip(result.periods, da_result.period_results):
        legacy_dist = wp.distribution_keur
        da_paid = da_period.equity_distribution_paid_keur

        wp.legacy_distribution_keur = legacy_dist
        wp.da_paid_distribution_keur = da_paid
        wp.distribution_source = "distribution_account"
        wp.distribution_wiring_delta_keur = da_paid - legacy_dist
        # Pass-through alias: distribution_keur becomes DA paid when flag=True
        wp.distribution_keur = da_paid

        total_da_paid += da_paid

    result.da_paid_distribution_keur = total_da_paid
    result.legacy_distribution_keur = result.total_distribution_keur
    result.distribution_source = "distribution_account"
    result.distribution_wiring_delta_keur = total_da_paid - result.total_distribution_keur
    # Recalculate total - pre-wiring sum is stale after per-period overrides
    result.total_distribution_keur = sum(p.distribution_keur for p in result.periods)














def _attach_dualrun_validation(result, inputs, periods_list) -> None:
    """Attach dual-run validation metadata to waterfall result (audit only).

    NO runtime routing. Result is not modified. DA remains audit-only.

    Runs two DA evaluations side-by-side:
    1. Governed mode (normal) — R99/R102 always BLOCKED
    2. Economic mode (audit-only) — R99/R102 evaluated using cash logic

    Cash source hierarchy for DA dual-run input (best available):
      1. r99_fcf_for_distribution_keur   — post-tax, post-senior-DS, post-reserves
         (Generic Wind Reference R99 engine; zero for non-Generic Wind Reference when engine is not active)
      2. cf_after_reserves_keur          — post-senior-DS, post-reserve sweep
         (available on every period after DSRA block)
      3. cf_after_tax_keur               — post-tax cash before debt service
         (fallback only; not a distribution proxy)

    The revenue - opex proxy is NOT used.
    """
    from domain.distribution_account.dualrun_validation import run_dual_validation
    from domain.distribution_account.inputs import (
        CovenantGatePolicy,
        DistributionAccountInputs,
        DistributionAccountPeriodInput,
        R99R102GateInputs,
    )

    # Build DA period inputs for both governed and economic modes
    governed_periods: list[DistributionAccountPeriodInput] = []
    economic_periods: list[DistributionAccountPeriodInput] = []

    for wp in result.periods:
        p_idx = getattr(wp, "period", None)
        if p_idx is None:
            continue

        # -----------------------------------------------------------------
        # Cash source selection (best available, descending preference)
        # -----------------------------------------------------------------
        r99_fcf = getattr(wp, "r99_fcf_for_distribution_keur", 0.0)
        cf_after_reserves = getattr(wp, "cf_after_reserves_keur", 0.0)
        cf_after_tax = getattr(wp, "cf_after_tax_keur", 0.0)
        senior_ds = getattr(wp, "senior_ds_keur", 0.0)

        # Cash source selection — use the same source as runtime distribution
        #
        # The waterfall runtime distributes cf_after_reserves_keur (via the distribution
        # section of waterfall_engine.py). In normal (non-tax_bridge) mode, r99_fcf
        # and cf_after_reserves are computed from the same CF and are equal.
        #
        # In Generic Wind Reference tax_bridge mode (_apply_generic_wind_reference_tax_bridge_runtime_cash_tax),
        # r99_fcf is recomputed with cash-tax (bridge overwrites cf_after_tax but
        # NOT cf_after_reserves). This causes r99_fcf != cf_after_reserves.
        #
        # For Phase C comparison to be meaningful, DA must use the SAME cash source
        # as the runtime distribution. When r99_fcf diverges from cf_after_reserves,
        # use cf_after_reserves (runtime's distribution source).
        #
        # Approach: detect divergence and use cf_after_reserves in that case.
        if r99_fcf > 0 and cf_after_reserves > 0 and abs(r99_fcf - cf_after_reserves) < 0.01:
            # Normal non-tax-bridge: r99_fcf == cf_after_reserves, use either
            post_shl_cash = r99_fcf
        elif cf_after_reserves > 0:
            # Tax-bridge divergence: runtime distributes cf_after_reserves
            post_shl_cash = cf_after_reserves
        else:
            post_shl_cash = max(0.0, cf_after_tax - senior_ds)

        post_senior_cash = max(0.0, cf_after_tax - senior_ds)

        is_reference_wind = (getattr(inputs.info, "code", "") == "REF-WIND-B")
        is_reference_solar = (getattr(inputs.info, "code", "") == "REF-SOLAR-A")
        covenant_gate_policy = inputs.financing.covenant_gate_policy
        senior_tenor_years = inputs.financing.senior_tenor_years

        # Common fields for both governed and economic inputs
        common_fields = dict(
            period_index=p_idx,
            operating_period_index=getattr(wp, "operating_period_index", p_idx),
            period_date=getattr(wp, "date", None) or __import__('datetime').date(2029, 12, 31),
            opening_distribution_account_balance_keur=0.0,
            post_senior_cash_available_keur=post_senior_cash,
            post_shl_cash_available_keur=post_shl_cash,
            senior_debt_service_keur=senior_ds,
            actual_dscr=getattr(wp, "dscr", 1.5),
            target_distribution_dscr=1.0,
            dsra_current_balance_keur=getattr(wp, "dsra_balance_keur", 0.0),
            dsra_required_balance_keur=getattr(wp, "dsra_balance_keur", 0.0),
            is_reference_wind=is_reference_wind,
            is_reference_solar=is_reference_solar,
            senior_tenor_years=senior_tenor_years,
            minimum_cash_reserve_keur=0.0,
        )

        # Governed mode: R99/R102 always blocked (normal DA behavior)
        governed_periods.append(DistributionAccountPeriodInput(
            **common_fields,
            audit_economic_mode=False,
        ))

        # Economic mode: R99/R102 evaluated using cash logic (audit-only)
        economic_periods.append(DistributionAccountPeriodInput(
            **common_fields,
            audit_economic_mode=True,
        ))

    governed_inputs = DistributionAccountInputs(
        project_name=getattr(inputs.info, "name", "Project"),
        period_inputs=tuple(governed_periods),
        is_reference_wind=is_reference_wind,
        is_reference_solar=is_reference_solar,
        covenant_gate_policy=covenant_gate_policy,
    )

    economic_inputs = DistributionAccountInputs(
        project_name=getattr(inputs.info, "name", "Project"),
        period_inputs=tuple(economic_periods),
        is_reference_wind=is_reference_wind,
        is_reference_solar=is_reference_solar,
        covenant_gate_policy=covenant_gate_policy,
    )

    try:
        dual_result = run_dual_validation(result, governed_inputs, economic_inputs)
        result._dualrun_validation = dual_result
    except Exception as exc:
        result._dualrun_validation = exc


__all__ = ["run_waterfall_v3_core"]
