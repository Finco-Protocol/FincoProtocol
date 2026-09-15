"""Portfolio-level runner — runs project waterfalls and aggregates results."""
from typing import Optional
from domain.portfolio.inputs import PortfolioInputs
from domain.portfolio.waterfall import PortfolioResult, run_portfolio_waterfall
from domain.waterfall.waterfall_engine import WaterfallResult
from app.waterfall_core import run_waterfall_v3_core


def run_portfolio_from_inputs(
    portfolio_inputs: PortfolioInputs,
    *,
    project_results: Optional[tuple[tuple[str, WaterfallResult], ...]] = None,
    portfolio_debt_service_schedule: Optional[tuple[float, ...]] = None,
    rate_per_period: float = 0.02825,
) -> PortfolioResult:
    """Run portfolio waterfall — either precomputed results or fresh from ProjectInputs.

    Note on input mapping:
    - Portfolio-level: target_dscr, lockup_dscr from shared_financing
    - Project-level: tax_rate, shl_*, equity_irr_method, sculpt_capex, debt_sizing_method
      from each project's own inputs (preserves project economics)

    Args:
        portfolio_inputs: PortfolioInputs with projects and shared financing
        project_results: Optional precomputed (name, WaterfallResult) tuples.
            If None, each project in portfolio_inputs.projects is run through
            run_waterfall_v3_core first.
        portfolio_debt_service_schedule: Optional explicit debt service schedule.
            If None, sculpted from pooled CFADS using closed_form_sculpt.
        rate_per_period: Semi-annual interest rate (default 0.02825).
    """
    if project_results is not None:
        return run_portfolio_waterfall(
            portfolio_inputs,
            project_results,
            portfolio_debt_service_schedule,
            rate_per_period,
        )

    # Run each project through waterfall
    results = []
    for proj in portfolio_inputs.projects:
        from domain.period_engine import PeriodEngine
        engine = PeriodEngine(
            financial_close=proj.info.financial_close,
            construction_months=proj.info.construction_months,
            horizon_years=proj.info.horizon_years,
            ppa_years=proj.revenue.ppa_term_years,
            frequency=proj.info.period_frequency,
            cod_date=proj.info.cod_date,
            period_axis_convention=getattr(
                proj.info.period_axis_convention,
                "value",
                proj.info.period_axis_convention,
            ),
        )
        all_periods = list(engine.periods())
        op_periods = [p for p in all_periods if p.is_operation]
        # Use project-level and shared financing inputs, not hard-coded values
        lockup_dscr = getattr(portfolio_inputs.shared_financing, 'lockup_dscr', 1.10)
        dsra_months = getattr(proj.financing, 'dsra_months', 6)
        tax_rate = getattr(proj.tax, 'corporate_rate', 0.10) if hasattr(proj, 'tax') else 0.10
        result = run_waterfall_v3_core(
            inputs=proj,
            engine=engine,
            rate_per_period=rate_per_period,
            tenor_periods=len(op_periods),
            target_dscr=portfolio_inputs.shared_financing.target_dscr,
            lockup_dscr=lockup_dscr,
            tax_rate=tax_rate,
            dsra_months=dsra_months,
            shl_amount=proj.financing.shl_amount_keur,
            shl_rate=proj.financing.shl_rate,
            shl_idc_keur=proj.financing.shl_idc_keur,
            shl_repayment_method=proj.financing.shl_repayment_method,
            shl_tenor_years=getattr(proj.financing, 'shl_tenor_years', 0),
            equity_irr_method=proj.financing.equity_irr_method,
            share_capital_keur=proj.financing.share_capital_keur,
            sculpt_capex_keur=proj.capex.sculpt_capex_keur,
            debt_sizing_method=proj.financing.debt_sizing_method,
        )
        results.append((proj.info.code, result))

    return run_portfolio_waterfall(
        portfolio_inputs,
        tuple(results),
        portfolio_debt_service_schedule,
        rate_per_period,
    )


__all__ = ["run_portfolio_from_inputs"]
