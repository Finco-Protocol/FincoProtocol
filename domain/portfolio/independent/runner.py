"""Phase 1 MVP + Phase 2 DSRF: Run independent SPVs through the single-asset engine.

No pooled financing. No shared debt sculpting. No HoldCo. No SHL.
Each SPV runs its own waterfall independently; results are aggregated.

DSRF (Phase 2):
- enabled=False: zero impact, identical to dsrf=None.
- enabled=True: DSRF facility schedule computed; cash costs (commitment fee,
  interest, repayment) reduce distributable cash. IRR recalculation deferred.
"""
from __future__ import annotations

from datetime import date
from typing import Optional, Any

from domain.portfolio.independent.inputs import (
    IndependentPortfolioInputs,
    DSRFConfig,
)
from domain.portfolio.independent.result import (
    SPVOutput,
    IndependentPortfolioResult,
    aggregate_independent_results,
)
from domain.portfolio.independent.dsrf import run_dsrf_facility_schedule


class SPVWaterfallError(Exception):
    """Raised when an SPV waterfall fails and strict=True."""

    def __init__(self, project_code: str, cause: Exception):
        self.project_code = project_code
        self.cause = cause
        super().__init__(f"SPV '{project_code}' waterfall run failed: {cause}")


def run_independent_portfolio(
    portfolio_inputs: IndependentPortfolioInputs,
    *,
    rate_per_period: float = 0.02825,
    strict: bool = True,
) -> IndependentPortfolioResult:
    """Run independent SPV portfolio aggregation.

    Each SPV runs independently through the single-asset engine.
    Results are aggregated into portfolio KPIs.

    DSRF Phase 2 Step 3: When enabled=True, distributions are adjusted:
      adjusted_dist = max(0, original_dist - commitment_fee - interest - repayment)
    IRR values are from the original waterfall and are NOT recalculated.

    Args:
        portfolio_inputs: IndependentPortfolioInputs with N projects
        rate_per_period: Semi-annual interest rate (default 0.02825)
        strict: If True (default), any SPV waterfall failure raises SPVWaterfallError.
                If False, the failed SPV is included with zero outputs and warnings.

    Returns:
        IndependentPortfolioResult with per-SPV outputs and portfolio KPIs.

    Raises:
        SPVWaterfallError: when strict=True and any SPV waterfall fails.
    """
    # Resolve DSRF config
    dsrf_config = portfolio_inputs.dsrf
    dsrf_enabled = dsrf_config is not None and dsrf_config.enabled

    spv_outputs: list[SPVOutput] = []
    dsrf_results: list[Any] = []

    for proj in portfolio_inputs.projects:
        wf_result, spv_warnings, dsrf_result = _run_single_spv(
            proj, rate_per_period, dsrf_config, strict=strict
        )

        if wf_result is None:
            if strict:
                code = proj.info.code
                msg = (spv_warnings[0] if spv_warnings
                       else f"SPV '{code}' waterfall run failed")
                raise SPVWaterfallError(
                    project_code=code,
                    cause=Exception(msg),
                )
            spv_outputs.append(_build_spv_output(proj, None, spv_warnings, None))
            dsrf_results.append(None)
        else:
            spv_out = _build_spv_output(proj, wf_result, spv_warnings, dsrf_result)
            spv_outputs.append(spv_out)
            dsrf_results.append(dsrf_result)

    # Aggregate DSRF results across SPVs
    dsrf_aggregate = _aggregate_dsrf_results(dsrf_results) if dsrf_enabled else None

    return aggregate_independent_results(
        portfolio_name=portfolio_inputs.portfolio_name,
        spv_outputs=tuple(spv_outputs),
        dsrf_enabled=dsrf_enabled,
        dsrf_result=dsrf_aggregate,
    )


def _run_single_spv(
    project_inputs,
    rate_per_period: float,
    dsrf_config: Optional[DSRFConfig],
    strict: bool,
) -> tuple[Optional[Any], list[str], Optional[Any]]:
    """Run one SPV through the waterfall engine and optionally the DSRF facility.

    Returns (result, warnings, dsrf_result):
    - result: WaterfallResult on success, None on failure
    - warnings: list of warning strings (empty on success)
    - dsrf_result: DSRFResult if DSRF enabled and waterfall succeeded, else None
    """
    from domain.period_engine import PeriodEngine, PeriodFrequency
    from app.waterfall_core import run_waterfall_v3_core

    _info = getattr(project_inputs, "info", None)
    engine = PeriodEngine(
        financial_close=getattr(_info, "financial_close", date(2030, 1, 1)),
        construction_months=getattr(_info, "construction_months", 12),
        horizon_years=getattr(_info, "horizon_years", 25),
        ppa_years=getattr(getattr(project_inputs, "revenue", None), "ppa_term_years", 10),
        frequency=getattr(_info, "period_frequency", PeriodFrequency.SEMESTRIAL),
        cod_date=getattr(_info, "cod_date", None),
        period_axis_convention=getattr(
            getattr(_info, "period_axis_convention", "cod_anchor_two_construction_columns"),
            "value",
            getattr(_info, "period_axis_convention", "cod_anchor_two_construction_columns"),
        ),
    )
    all_periods = list(engine.periods())
    op_periods = [p for p in all_periods if p.is_operation]
    n_op = len(op_periods)

    # Pull financing params with safe fallbacks
    lockup_dscr = 1.10
    dsra_months = 6
    tax_rate = 0.10
    shl_amount = 0.0
    shl_rate = 0.0
    shl_idc_keur = 0.0
    shl_repay_method = "sculpt"
    shl_tenor = 0
    equity_irr_method = "xirr"
    share_capital_keur = 0.0
    sculpt_capex_keur = 0.0
    debt_sizing_method = "dscr_sculpt"

    if hasattr(project_inputs, "financing"):
        fin = project_inputs.financing
        lockup_dscr = getattr(fin, "lockup_dscr", 1.10)
        dsra_months = getattr(fin, "dsra_months", 6)
        shl_amount = getattr(fin, "shl_amount_keur", 0.0)
        shl_rate = getattr(fin, "shl_rate", 0.0)
        shl_idc_keur = getattr(fin, "shl_idc_keur", 0.0)
        shl_repay_method = getattr(fin, "shl_repayment_method", "sculpt")
        shl_tenor = getattr(fin, "shl_tenor_years", 0)
        equity_irr_method = getattr(fin, "equity_irr_method", "xirr")
        share_capital_keur = getattr(fin, "share_capital_keur", 0.0)
        sculpt_capex_keur = getattr(fin, "sculpt_capex_keur", 0.0)
        debt_sizing_method = getattr(fin, "debt_sizing_method", "dscr_sculpt")

    if hasattr(project_inputs, "tax"):
        tax_rate = getattr(project_inputs.tax, "corporate_rate", 0.10)

    if hasattr(project_inputs, "capex"):
        sculpt_capex_keur = getattr(
            project_inputs.capex, "sculpt_capex_keur", 0.0
        )

    fin = getattr(project_inputs, "financing", None)
    target_dscr = getattr(fin, "target_dscr", 1.15) if fin else 1.15

    try:
        result = run_waterfall_v3_core(
            inputs=project_inputs,
            engine=engine,
            rate_per_period=rate_per_period,
            tenor_periods=n_op,
            target_dscr=target_dscr,
            lockup_dscr=lockup_dscr,
            tax_rate=tax_rate,
            dsra_months=dsra_months,
            shl_amount=shl_amount,
            shl_rate=shl_rate,
            shl_idc_keur=shl_idc_keur,
            shl_repayment_method=shl_repay_method,
            shl_tenor_years=shl_tenor,
            equity_irr_method=equity_irr_method,
            share_capital_keur=share_capital_keur,
            sculpt_capex_keur=sculpt_capex_keur,
            debt_sizing_method=debt_sizing_method,
        )

        # Run DSRF facility schedule if enabled
        dsrf_result: Optional[Any] = None
        if dsrf_config is not None and dsrf_config.enabled:
            dsrf_result, dsrf_warnings = _run_spv_dsrf(project_inputs, result, dsrf_config)
            all_warnings: list[str] = []
            if dsrf_warnings:
                all_warnings.extend(dsrf_warnings)
            return result, all_warnings, dsrf_result

        return result, [], None

    except Exception as e:
        code = project_inputs.info.code
        if strict:
            raise SPVWaterfallError(
                project_code=code,
                cause=e,
            ) from e
        return None, [f"SPV '{code}' waterfall run failed: {e}"], None


def _run_spv_dsrf(
    project_inputs,
    wf_result: Any,
    dsrf_config: DSRFConfig,
) -> tuple[Optional[Any], list[str]]:
    """Extract semiannual schedules from waterfall result and run DSRF facility.

    Returns (dsrf_result, warnings):
    - dsrf_result: DSRFResult on success, None on failure
    - warnings: list of warning strings if extraction/calculation failed
    """
    from domain.portfolio.independent.dsrf import run_dsrf_facility_schedule

    code = project_inputs.info.code
    warnings: list[str] = []

    try:
        op_periods = [p for p in wf_result.periods if getattr(p, "is_operation", False)]
        if not op_periods:
            warnings.append(f"DSRF: no operation periods found for SPV '{code}'")
            return None, warnings

        semiannual_ds_schedule = tuple(
            max(0.0, getattr(p, "senior_ds_keur", 0.0))
            for p in op_periods
        )
        cfads_schedule = tuple(
            max(0.0, getattr(p, "cf_after_tax_keur", 0.0))
            for p in op_periods
        )

        if not semiannual_ds_schedule:
            warnings.append(f"DSRF: no senior debt service schedule for SPV '{code}'")
            return None, warnings

        if not cfads_schedule:
            warnings.append(f"DSRF: no CFADS schedule for SPV '{code}'")
            return None, warnings

        dsrf_result = run_dsrf_facility_schedule(
            spv_code=code,
            semiannual_debt_service_schedule=semiannual_ds_schedule,
            cfads_schedule=cfads_schedule,
            config=dsrf_config,
        )
        return dsrf_result, warnings

    except Exception as exc:
        warnings.append(f"DSRF: failed to compute facility for SPV '{code}': {exc}")
        return None, warnings


def _aggregate_dsrf_results(dsrf_results: list[Any]) -> Any:
    """Aggregate per-SPV DSRF results into portfolio-level DSRFResult.

    Sums: draw, repayment, commitment_fee, drawn_interest, debt_service_support,
    facility_limit, drawn_end, distribution_reduction across all SPVs.
    """
    from domain.portfolio.independent.dsrf import DSRFResult

    valid = [r for r in dsrf_results if r is not None]
    if not valid:
        return None

    config = valid[0].config

    total_draw = sum(getattr(r, "total_draw_keur", 0.0) for r in valid)
    total_repay = sum(getattr(r, "total_repayment_keur", 0.0) for r in valid)
    total_commit = sum(getattr(r, "total_commitment_fee_keur", 0.0) for r in valid)
    total_interest = sum(getattr(r, "total_drawn_interest_keur", 0.0) for r in valid)
    total_support = sum(getattr(r, "total_debt_service_support_keur", 0.0) for r in valid)
    facility = sum(getattr(r, "facility_limit_keur", 0.0) for r in valid)
    drawn_end = sum(getattr(r, "drawn_end_keur", 0.0) for r in valid)

    all_periods: list[Any] = []
    for r in valid:
        periods = getattr(r, "periods", [])
        if periods:
            all_periods.extend(periods)

    return DSRFResult(
        config=config,
        periods=tuple(all_periods),
        total_draw_keur=total_draw,
        total_repayment_keur=total_repay,
        total_commitment_fee_keur=total_commit,
        total_drawn_interest_keur=total_interest,
        total_debt_service_support_keur=total_support,
        facility_limit_keur=facility,
        drawn_end_keur=drawn_end,
    )


def _build_spv_output(
    project_inputs,
    wf_result: Optional[Any],
    warnings: list[str],
    dsrf_result: Optional[Any],
) -> SPVOutput:
    """Build SPVOutput from a waterfall result (or zero output on failure).

    Phase 2 Step 3: When dsrf_result is present, adjust total_distribution_keur:
      adjusted = max(0, original_dist - commitment_fee - drawn_interest - repayment)
    DSRF draw is NOT revenue — it cannot increase distributions.

    P0.1: Also compute per-period adjusted_period_distributions_keur.
    When dsrf_result periods align with wf_result periods, use
    DSRF-adjusted cash_available_for_distribution per period.
    Otherwise fall back to waterfall distribution per period and emit warning.
    """
    code = project_inputs.info.code
    name = getattr(project_inputs.info, "name", code)

    if wf_result is None:
        return SPVOutput(
            project_code=code,
            project_name=name,
            project_irr=0.0,
            equity_irr=0.0,
            total_revenue_keur=0.0,
            total_ebitda_keur=0.0,
            total_tax_keur=0.0,
            total_senior_ds_keur=0.0,
            total_distribution_keur=0.0,
            avg_dscr=0.0,
            min_dscr=0.0,
            waterfall_result=None,
            warnings=tuple(warnings),
        )

    # Extract DSRF fields and compute adjusted distribution
    original_dist = getattr(wf_result, "total_distribution_keur", 0.0)

    # ── P0.1: per-period adjusted distributions ─────────────────────────
    wf_periods = getattr(wf_result, "periods", [])
    dsrf_periods_list: list[Any] = getattr(dsrf_result, "periods", []) if dsrf_result else []

    # Build full-length adjusted array: start with all waterfall distributions,
    # then replace operation-period slots with DSRF cash_available values.
    # DSRF periods correspond only to operation periods (construction periods are skipped).
    if dsrf_result is not None and dsrf_periods_list and wf_periods:
        op_indexes = [
            idx for idx, p in enumerate(wf_periods)
            if getattr(p, "is_operation", False)
        ]
        if len(dsrf_periods_list) == len(op_indexes):
            # Aligned — map DSRF periods onto operation-period indexes in wf_periods
            adjusted = [
                getattr(p, "distribution_keur", 0.0) for p in wf_periods
            ]
            for dsrf_period, op_idx in zip(dsrf_periods_list, op_indexes):
                # P0.1 fix: adjusted = wf_dist - DSRF costs per operation period.
                # wf_dist is the waterfall distribution AFTER waterfall deductions (senior debt,
                # SHL, DSRA). DSRF costs (commitment fee, drawn interest, repayment) are
                # additional facility costs that further reduce what flows to HoldCo.
                # Using wf_dist - costs ensures HoldCo upstream ≤ raw wf distribution total.
                wf_dist = getattr(wf_periods[op_idx], "distribution_keur", 0.0)
                dsrf_cost = (
                    getattr(dsrf_period, "commitment_fee_keur", 0.0)
                    + getattr(dsrf_period, "drawn_interest_keur", 0.0)
                    + getattr(dsrf_period, "repayment_keur", 0.0)
                )
                adjusted[op_idx] = max(0.0, wf_dist - dsrf_cost)
            adjusted_period_distributions = tuple(adjusted)
        else:
            # Mismatch — fall back to waterfall per-period distributions (full length)
            adjusted_period_distributions = tuple(
                getattr(p, "distribution_keur", 0.0) for p in wf_periods
            )
            warnings.append(
                f"DSRF operation period count ({len(dsrf_periods_list)}) != "
                f"wf operation period count ({len(op_indexes)}) for SPV '{code}'. "
                f"Falling back to waterfall distributions for HoldCo."
            )
    else:
        # No DSRF or no periods — empty tuple signals no adjustment to HoldCo
        adjusted_period_distributions = ()

    if dsrf_result is not None:
        commit_fee = getattr(dsrf_result, "total_commitment_fee_keur", 0.0)
        drawn_interest = getattr(dsrf_result, "total_drawn_interest_keur", 0.0)
        repayment = getattr(dsrf_result, "total_repayment_keur", 0.0)
        reduction = commit_fee + drawn_interest + repayment

        dsrf_limit = getattr(dsrf_result, "facility_limit_keur", 0.0)
        dsrf_draw = getattr(dsrf_result, "total_draw_keur", 0.0)
        dsrf_repay = repayment
        dsrf_commit = commit_fee
        dsrf_interest = drawn_interest
        dsrf_support = getattr(dsrf_result, "total_debt_service_support_keur", 0.0)
        dsrf_drawn_end = getattr(dsrf_result, "drawn_end_keur", 0.0)
        dsrf_periods_out = getattr(dsrf_result, "periods", ())

        # P0.1 fix: total_distribution_keur equals sum(adjusted_period_distributions)
        # when DSRF per-period data is available. This makes the total consistent
        # with the per-period HoldCo feed.
        if adjusted_period_distributions:
            adjusted_dist = sum(adjusted_period_distributions)
            # Period-consistent audit trail: reduction = raw_wf_sum - sum(adjusted)
            raw_wf_sum = sum(getattr(p, "distribution_keur", 0.0) for p in wf_periods)
            dsrf_reduction = raw_wf_sum - adjusted_dist
        else:
            adjusted_dist = max(0.0, original_dist - reduction)
            dsrf_reduction = reduction
    else:
        adjusted_dist = original_dist
        dsrf_limit = 0.0
        dsrf_draw = 0.0
        dsrf_repay = 0.0
        dsrf_commit = 0.0
        dsrf_interest = 0.0
        dsrf_support = 0.0
        dsrf_drawn_end = 0.0
        dsrf_periods_out = ()
        dsrf_reduction = 0.0

    return SPVOutput(
        project_code=code,
        project_name=name,
        project_irr=getattr(wf_result, "project_irr", 0.0),
        equity_irr=getattr(wf_result, "equity_irr", 0.0),
        total_revenue_keur=getattr(wf_result, "total_revenue_keur", 0.0),
        total_ebitda_keur=getattr(wf_result, "total_ebitda_keur", 0.0),
        total_tax_keur=getattr(wf_result, "total_tax_keur", 0.0),
        total_senior_ds_keur=getattr(wf_result, "total_senior_ds_keur", 0.0),
        total_distribution_keur=adjusted_dist,
        avg_dscr=getattr(wf_result, "avg_dscr", 0.0),
        min_dscr=getattr(wf_result, "min_dscr", 0.0),
        waterfall_result=wf_result,
        warnings=tuple(warnings),
        adjusted_period_distributions_keur=adjusted_period_distributions,
        dsrf_facility_limit_keur=dsrf_limit,
        dsrf_total_draw_keur=dsrf_draw,
        dsrf_total_repayment_keur=dsrf_repay,
        dsrf_commitment_fee_keur=dsrf_commit,
        dsrf_drawn_interest_keur=dsrf_interest,
        dsrf_debt_service_support_keur=dsrf_support,
        dsrf_drawn_end_keur=dsrf_drawn_end,
        dsrf_periods=tuple(dsrf_periods_out),
        dsrf_distribution_reduction_keur=dsrf_reduction,
    )


__all__ = [
    "run_independent_portfolio",
    "SPVWaterfallError",
    "IndependentPortfolioInputs",
    "IndependentPortfolioResult",
    "SPVOutput",
    "DSRFConfig",
]
