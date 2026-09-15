"""Pooled-financing portfolio waterfall.

Scope:
- Aligns project waterfall periods by date
- Pools CFADS (EBITDA - tax) per period
- Computes portfolio DSCR against pooled debt service
- Returns PortfolioResult with per-project results exposed

Behavior:
- Uses explicit portfolio_debt_service_schedule if provided
- Otherwise sculpts portfolio debt from pooled CFADS using
  shared_financing.target_dscr via closed_form_sculpt
- Does not yet implement cross-default enforcement
- portfolio_project_irr is experimental pooled CFADS IRR (date-aligned XIRR)
- portfolio_sponsor_irr remains a placeholder (requires equity-level CF aggregation)
"""
from dataclasses import dataclass, field
from typing import Optional
from datetime import date

from domain.waterfall.waterfall_engine import WaterfallResult
from domain.financing.sculpting_iterative import closed_form_sculpt
from domain.returns.xirr import xirr


@dataclass(frozen=True)
class PortfolioDebtSchedule:
    """Portfolio debt sizing result from sculpting."""
    debt_keur: float
    debt_service_schedule: tuple[float, ...]
    interest_schedule: tuple[float, ...] = ()
    principal_schedule: tuple[float, ...] = ()


@dataclass(frozen=True)
class PortfolioPeriod:
    period: int
    date: date
    pooled_revenue_keur: float
    pooled_ebitda_keur: float
    pooled_tax_keur: float
    pooled_cfads_keur: float
    portfolio_senior_interest_keur: float
    portfolio_senior_principal_keur: float
    portfolio_senior_ds_keur: float
    dscr: float


@dataclass(frozen=True)
class PortfolioResult:
    """Result of a portfolio pooled-financing waterfall.

    IRR aggregation not yet implemented — portfolio_project_irr and portfolio_sponsor_irr
    are placeholders until full cash-flow aggregation is ready.
    """
    periods: tuple[PortfolioPeriod, ...]
    project_results: tuple[tuple[str, WaterfallResult], ...]
    total_revenue_keur: float
    total_ebitda_keur: float
    total_tax_keur: float
    total_senior_ds_keur: float
    avg_dscr: float
    min_dscr: float
    # Aggregated debt schedule
    portfolio_debt_keur: float
    pooled_cfads_schedule: tuple[float, ...]
    portfolio_debt_service_schedule: tuple[float, ...]
    portfolio_project_irr: float = 0.0  # experimental pooled unlevered CFADS IRR
    portfolio_sponsor_irr: float = 0.0

    portfolio_cashflows: list[dict] = field(default_factory=list)
    # audit table — date-level breakdown of portfolio_project_irr cashflow inputs    # TODO: portfolio_sponsor_irr requires:
    # - Equity-level cash flows (after senior debt service)
    # - SHL (Subordinated_High_Yield) distribution logic
    # - Sponsor-specific TACC/CFADS aggregation
    # Not implemented — value remains 0.0 placeholder


def aggregate_project_results(
    project_results: tuple[tuple[str, WaterfallResult], ...],
) -> list[dict]:
    """Align project waterfalls by date, sum revenue/EBITDA/tax/CFADS."""
    # Collect all unique dates across projects
    date_map: dict[date, dict] = {}
    for name, result in project_results:
        for pr in result.periods:
            if not pr.is_operation:
                continue
            d = pr.date
            if d not in date_map:
                date_map[d] = dict(revenue=0.0, ebitda=0.0, tax=0.0, cfads=0.0,
                             senior_interest=0.0, senior_principal=0.0)
            date_map[d]["revenue"] += getattr(pr, "revenue_keur", 0.0)
            date_map[d]["ebitda"] += pr.ebitda_keur
            date_map[d]["tax"] += pr.tax_keur
            date_map[d]["cfads"] += pr.ebitda_keur - pr.tax_keur
            date_map[d]["senior_interest"] += pr.senior_interest_keur
            date_map[d]["senior_principal"] += pr.senior_principal_keur

    periods = []
    for d in sorted(date_map.keys()):
        m = date_map[d]
        periods.append({
            "date": d,
            "pooled_revenue_keur": m["revenue"],
            "pooled_ebitda_keur": m["ebitda"],
            "pooled_tax_keur": m["tax"],
            "pooled_cfads_keur": m["cfads"],
            "portfolio_senior_interest_keur": m["senior_interest"],
            "portfolio_senior_principal_keur": m["senior_principal"],
        })
    return periods


def portfolio_cfads_schedule(pooled_periods: list[dict]) -> list[float]:
    return [p["pooled_cfads_keur"] for p in pooled_periods]


def build_portfolio_debt_service_schedule(
    cfads_schedule: list[float],
    financing,  # shared FinancingParams
    rate_per_period: float,
) -> PortfolioDebtSchedule:
    """Sculpt portfolio debt from pooled CFADS schedule using closed_form_sculpt.

    Uses target_dscr from shared_financing to size debt and compute the schedule.
    """
    target_dscr = financing.target_dscr
    n = len(cfads_schedule)
    result = closed_form_sculpt(
        cfads_schedule=cfads_schedule,
        rate_schedule=[rate_per_period] * n,
        tenor_periods=n,
        target_dscr=target_dscr,
    )
    return PortfolioDebtSchedule(
        debt_keur=result.debt_keur,
        debt_service_schedule=tuple(result.payment_schedule),
        interest_schedule=tuple(result.interest_schedule),
        principal_schedule=tuple(result.principal_schedule),
    )


def run_portfolio_waterfall(
    portfolio_inputs,  # PortfolioInputs object
    project_results: tuple[tuple[str, WaterfallResult], ...],
    portfolio_debt_service_schedule: Optional[tuple[float, ...]] = None,
    rate_per_period: float = 0.02825,
) -> PortfolioResult:
    """Run pooled-financing portfolio waterfall.

    Args:
        portfolio_inputs: PortfolioInputs (provides cash_pooling flag and shared_financing)
        project_results: (name, WaterfallResult) tuples
        portfolio_debt_service_schedule: optional explicit debt service
        rate_per_period: Semi-annual interest rate (default 0.02825)

    Returns:
        PortfolioResult with pooled periods, per-project results, DSCR
    """
    pooled = aggregate_project_results(project_results)

    n = len(pooled)
    cfads_list = [p["pooled_cfads_keur"] for p in pooled]

    # Sculpt or require portfolio debt service schedule
    if portfolio_debt_service_schedule is not None:
        ds_schedule = list(portfolio_debt_service_schedule)
    elif portfolio_inputs is not None:
        pds = build_portfolio_debt_service_schedule(
            cfads_list,
            portfolio_inputs.shared_financing,
            rate_per_period,
        )
        ds_schedule = list(pds.debt_service_schedule)
    else:
        raise ValueError(
            "Either portfolio_inputs or explicit portfolio_debt_service_schedule is required"
        )

    total_rev = sum(p["pooled_revenue_keur"] for p in pooled)
    total_ebitda = sum(p["pooled_ebitda_keur"] for p in pooled)
    total_tax = sum(p["pooled_tax_keur"] for p in pooled)
    total_ds = sum(ds_schedule[:n])

    result_periods = []
    dscrs = []
    portfolio_debt = 0.0
    for i, p in enumerate(pooled):
        ds = ds_schedule[i] if i < len(ds_schedule) else 0.0
        cfads = p["pooled_cfads_keur"]
        dscr = cfads / ds if ds > 0 else 999.0
        dscrs.append(dscr)
        # Interest and principal from aggregate (pooled across projects)
        interest = p.get("portfolio_senior_interest_keur", 0.0)
        principal = p.get("portfolio_senior_principal_keur", 0.0)
        result_periods.append(PortfolioPeriod(
            period=i + 1,
            date=p["date"],
            pooled_revenue_keur=p["pooled_revenue_keur"],
            pooled_ebitda_keur=p["pooled_ebitda_keur"],
            pooled_tax_keur=p["pooled_tax_keur"],
            pooled_cfads_keur=cfads,
            portfolio_senior_interest_keur=interest,
            portfolio_senior_principal_keur=principal,
            portfolio_senior_ds_keur=ds,
            dscr=dscr,
        ))

    avg_d = sum(dscrs) / len(dscrs) if dscrs else 0.0
    min_d = min(dscrs) if dscrs else 0.0

    # Compute portfolio debt: 0.0 when explicit schedule is supplied,
    # sculpted pds.debt_keur otherwise (built above via build_portfolio_debt_service_schedule)
    if portfolio_debt_service_schedule is not None:
        # Explicit schedule provided — debt amount is not inferred from CFADS
        portfolio_debt = 0.0
    elif portfolio_inputs is not None:
        # Use sculpted debt from build_portfolio_debt_service_schedule()
        portfolio_debt = pds.debt_keur
    else:
        portfolio_debt = 0.0

    # ── portfolio_project_irr: date-aligned XIRR ─────────────────────────────────
    # Each project's CapEx outflow is placed on its own financial_close date.
    # Each project's operating CFADS is placed on its waterfall period dates.
    # Cash flows on the same date are aggregated before XIRR computation.
    try:
        irr_cf_list, irr_date_list = build_portfolio_project_cashflows(
            portfolio_inputs, project_results
        )
        irr = xirr(irr_cf_list, irr_date_list)
        portfolio_project_irr = irr if irr is not None else 0.0
    except Exception:
        portfolio_project_irr = 0.0

    return PortfolioResult(
        periods=tuple(result_periods),
        project_results=project_results,
        total_revenue_keur=total_rev,
        total_ebitda_keur=total_ebitda,
        total_tax_keur=total_tax,
        total_senior_ds_keur=total_ds,
        avg_dscr=avg_d,
        min_dscr=min_d,
        portfolio_debt_keur=portfolio_debt,
        pooled_cfads_schedule=tuple(cfads_list),
        portfolio_debt_service_schedule=tuple(ds_schedule),
        portfolio_project_irr=portfolio_project_irr,
        portfolio_sponsor_irr=0.0,
        portfolio_cashflows=build_portfolio_cashflow_table(portfolio_inputs, project_results),
        # portfolio_sponsor_irr requires equity-level cash flows (after senior debt service),
        # SHL distribution logic, and sponsor-specific TACC/CFADS aggregation.
        # Not implemented — remains 0.0 placeholder
    )


def build_portfolio_project_cashflows(portfolio_inputs, project_results):
    """Build date-aligned cash-flow series for portfolio XIRR.

    Each project's CapEx outflow is placed on its own financial_close date.
    Each project's CFADS is placed on its waterfall period dates.
    Cash flows on the same date are aggregated.

    Args:
        portfolio_inputs: PortfolioInputs (provides project list and financial_close dates)
        project_results: tuple of (project_code, WaterfallResult)

    Returns:
        (cash_flows: list[float], dates: list[date]) for xirr()
    """
    from collections import defaultdict

    cashflows = defaultdict(float)  # date → cumulative amount

    if portfolio_inputs and portfolio_inputs.projects:
        # Map project codes to their CapEx
        capex_by_code = {proj.info.code: proj.capex.total_capex for proj in portfolio_inputs.projects}
        fc_by_code = {proj.info.code: proj.info.financial_close for proj in portfolio_inputs.projects}

        for code, result in project_results:
            capex = capex_by_code.get(code, 0.0)
            fc_date = fc_by_code.get(code)
            if fc_date and capex > 0:
                cashflows[fc_date] -= capex  # outflow on project's financial_close

            if result and result.periods:
                for p in result.periods:
                    if p.is_operation:
                        cfads = p.ebitda_keur - p.tax_keur
                        if cfads is not None:
                            cashflows[p.date] += cfads
    else:
        # Fallback: no portfolio_inputs — cannot align CapEx by financial_close date.
        # Return empty series; portfolio_project_irr stays 0.0.
        return [], []

    sorted_dates = sorted(cashflows.keys())
    cf_list = [cashflows[d] for d in sorted_dates]
    date_list = sorted_dates
    return cf_list, date_list




def build_portfolio_cashflow_table(
    portfolio_inputs: Optional["PortfolioInputs"],
    project_results: tuple[tuple[str, "WaterfallResult"], ...],
) -> list[dict]:
    """Build a date-level breakdown of portfolio cash flows for auditability.

    Returns a list of dicts with keys:
        date, total_cashflow, breakdown (dict of project_code -> contribution_keur)

    Breakdown sums by date match total_cashflow exactly.

    Args:
        portfolio_inputs: PortfolioInputs (provides project list and CapEx dates)
        project_results: tuple of (project_code, WaterfallResult)

    Returns:
        List of cashflow rows sorted by date
    """
    from collections import defaultdict
    from datetime import date

    if not project_results:
        return []

    cashflows = defaultdict(lambda: defaultdict(float))  # date → {project_code: amount}
    capex_by_code = {}
    fc_by_code = {}

    if portfolio_inputs and portfolio_inputs.projects:
        capex_by_code = {proj.info.code: proj.capex.total_capex for proj in portfolio_inputs.projects}
        fc_by_code = {proj.info.code: proj.info.financial_close for proj in portfolio_inputs.projects}

    # CapEx outflows on project financial_close dates
    for code, capex in capex_by_code.items():
        fc = fc_by_code.get(code)
        if fc and capex > 0:
            cashflows[fc][code] -= capex

    # Operating CFADS on waterfall period dates
    for code, result in project_results:
        if result is None or not result.periods:
            continue
        for p in result.periods:
            if p.is_operation:
                cfads = p.ebitda_keur - p.tax_keur
                if cfads is not None:
                    cashflows[p.date][code] += cfads

    # Build sorted table
    rows = []
    for d in sorted(cashflows.keys()):
        breakdown = dict(cashflows[d])
        total = sum(breakdown.values())
        rows.append({"date": d, "total_cashflow": total, "breakdown": breakdown})

    return rows



__all__ = [
    "PortfolioPeriod",
    "PortfolioResult",
    "aggregate_project_results",
    "build_portfolio_cashflow_table",
    "build_portfolio_project_cashflows",
    "portfolio_cfads_schedule",
    "run_portfolio_waterfall",
]