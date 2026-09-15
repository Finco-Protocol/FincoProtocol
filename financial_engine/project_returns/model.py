"""Decision-complete downstream returns and maturity authority.

This module consumes one already-computed clean G2C financing/waterfall result.
It never sizes financing, changes upstream schedules, or manufactures terminal
cash. Project tax is recomputed on the canonical operating periods with zero
financing interest so Project XIRR remains genuinely unlevered.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import replace
from datetime import date
from typing import TYPE_CHECKING

from finco_core.sponsor.xirr import robust_xirr

from financial_engine.project_returns.contracts import (
    CashAccountTerminalState,
    CashAccountTerminalStatus,
    DebtTerminalState,
    DebtTerminalStatus,
    DecisionCompleteReturnSummary,
    ProjectReturnStatus,
    ProjectReturnCashFlow,
    ProjectReturnResult,
    ReturnMetricSummary,
    ShlTerminalState,
    ShlTerminalStatus,
    TerminalFinancialState,
)
from financial_engine.sponsor_returns.contracts import ReturnMetricStatus

if TYPE_CHECKING:
    from finco_core.inputs import ProjectInputs
    from financial_engine.financing.contracts import ProjectFinancingResult
    from financial_engine.shareholder_waterfall.contracts import (
        CovenantGatedWaterfallPeriod,
    )


_TOL = 1e-7
_PROJECT_RETURN_AUTHORITY = (
    "C1_UNLEVERED_HARD_CAPEX_PLUS_EBITDA_MINUS_ZERO_FINANCING_INTEREST_CASH_TAX"
)


def _status(cashflows: list[float], xirr: float | None) -> ProjectReturnStatus:
    if not any(value < -_TOL for value in cashflows):
        return ProjectReturnStatus.NO_NEGATIVE_CASHFLOW
    if not any(value > _TOL for value in cashflows):
        return ProjectReturnStatus.NO_POSITIVE_CASHFLOW
    if xirr is None:
        return ProjectReturnStatus.NON_CONVERGENT
    return ProjectReturnStatus.OK


class _ProjectReturnAuthorityError(ValueError):
    def __init__(self, status: ProjectReturnStatus, message: str) -> None:
        super().__init__(message)
        self.status = status


def _construction_investment_rows(
    project_inputs: "ProjectInputs",
    financing: "ProjectFinancingResult",
) -> tuple[tuple[tuple[date, float], ...], str]:
    """Return authoritative hard-CAPEX timing without financing uses."""
    construction = financing.construction_financing
    hard_capex = financing.project_uses.hard_project_capex_keur
    if construction is not None:
        dates = construction.period_end_dates
        amounts = construction.hard_capex_uses_keur
        if len(dates) != len(amounts):
            raise _ProjectReturnAuthorityError(
                ProjectReturnStatus.HARD_CAPEX_TIMING_UNAVAILABLE,
                "C1_PROJECT_RETURN_CONSTRUCTION_AXIS_LENGTH_MISMATCH",
            )
        if abs(sum(amounts) - hard_capex) > _TOL:
            raise _ProjectReturnAuthorityError(
                ProjectReturnStatus.HARD_CAPEX_TIMING_UNAVAILABLE,
                "C1_PROJECT_RETURN_HARD_CAPEX_TIMING_DOES_NOT_RECONCILE",
            )
        return (
            tuple((cash_date, float(amount)) for cash_date, amount in zip(dates, amounts)),
            "TYPED_CONSTRUCTION_FINANCING_HARD_CAPEX_VECTOR",
        )

    periods = financing.construction_funding.periods
    period_uses = tuple(float(period.project_cash_uses_keur) for period in periods)
    uses = financing.project_uses
    construction_funding_is_hard_capex_only = (
        abs(uses.explicit_financing_cost_uses_keur) <= _TOL
        and abs(uses.reserve_account_funding_keur) <= _TOL
        and abs(uses.other_explicit_project_uses_keur) <= _TOL
        and abs(uses.total_project_uses_keur - hard_capex) <= _TOL
        and financing.construction_funding.non_construction_fc_use is None
    )
    if (
        periods
        and construction_funding_is_hard_capex_only
        and abs(sum(period_uses) - hard_capex) <= _TOL
    ):
        financial_close = project_inputs.info.financial_close
        from financial_engine.sponsor_returns.model import _construction_period_date

        return (
            tuple(
                (_construction_period_date(financial_close, period.period_index), amount)
                for period, amount in zip(periods, period_uses)
            ),
            "CANONICAL_HARD_CAPEX_ONLY_CONSTRUCTION_FUNDING_VECTOR",
        )

    raise _ProjectReturnAuthorityError(
        ProjectReturnStatus.HARD_CAPEX_TIMING_UNAVAILABLE,
        "PROJECT_RETURN_HARD_CAPEX_TIMING_UNAVAILABLE",
    )


def _unlevered_cash_tax_by_period(
    project_inputs: "ProjectInputs",
    financing: "ProjectFinancingResult",
) -> tuple[dict[int, float], float]:
    from financial_engine.adapters.tax_inputs import (
        FinancingInterestContext,
        build_tax_contract_from_project_inputs,
    )
    from financial_engine.tax.engine import calculate_tax
    from financial_engine.adapters.project_inputs import from_project_inputs
    from financial_engine.orchestrator import _build_period_engine, _compute_depreciation

    tax_contract = build_tax_contract_from_project_inputs(
        project_inputs,
        financing_interest_context=(
            FinancingInterestContext.UNLEVERED_ZERO_FINANCING_INTEREST
        ),
    )
    if tax_contract.period_interest:
        raise ValueError("C1_PROJECT_RETURN_FINANCING_INTEREST_LEAK")
    model = financing.project_model_result
    operating_input = from_project_inputs(project_inputs)
    period_metadata = _build_period_engine(operating_input).periods()
    if tuple(period.index for period in period_metadata) != tuple(
        period.period_index for period in model.periods
    ):
        raise ValueError("C1_UNLEVERED_TAX_PERIOD_AXIS_MISMATCH")
    if tuple(period.end_date for period in period_metadata) != tuple(
        period.period_end for period in model.periods
    ):
        raise ValueError("C1_UNLEVERED_TAX_PERIOD_DATE_MISMATCH")
    _, tax_depreciation = _compute_depreciation(
        operating_input, list(period_metadata)
    )
    unlevered_periods = tuple(
        replace(
            period,
            tax_depreciation_keur=float(
                tax_depreciation.get(period.period_index, 0.0)
            ),
        )
        for period in model.periods
    )
    tax_result = calculate_tax(unlevered_periods, tax_contract)
    return (
        {
            period.period_index: float(period.cash_tax_keur)
            for period in tax_result.period_results
        },
        float(tax_result.terminal_unpaid_tax_keur),
    )


def _project_return_failure(
    *,
    financing: "ProjectFinancingResult",
    status: ProjectReturnStatus,
    hard_capex_timing_authority: str | None,
    terminal_unpaid_project_tax_keur: float = 0.0,
    cashflows: tuple[ProjectReturnCashFlow, ...] = (),
) -> ProjectReturnResult:
    uses = financing.project_uses
    return ProjectReturnResult(
        cashflows=cashflows,
        project_xirr=None,
        project_xirr_status=status,
        total_hard_capex_investment_keur=float(uses.hard_project_capex_keur),
        excluded_financing_cost_uses_keur=float(
            uses.explicit_financing_cost_uses_keur
        ),
        excluded_reserve_funding_keur=float(uses.reserve_account_funding_keur),
        other_explicit_project_uses_keur=float(
            uses.other_explicit_project_uses_keur
        ),
        total_operating_inflow_keur=sum(
            float(period.ebitda_keur)
            for period in financing.project_model_result.periods
            if period.is_operation
        ),
        total_project_tax_outflow_keur=sum(
            row.project_tax_outflow_keur for row in cashflows
        ),
        terminal_unpaid_project_tax_keur=terminal_unpaid_project_tax_keur,
        terminal_component_keur=0.0,
        hard_capex_timing_authority=hard_capex_timing_authority,
        methodology_authority=_PROJECT_RETURN_AUTHORITY,
    )


def _project_return(
    project_inputs: "ProjectInputs",
    financing: "ProjectFinancingResult",
) -> ProjectReturnResult:
    model = financing.project_model_result
    uses = financing.project_uses
    if abs(uses.other_explicit_project_uses_keur) > _TOL:
        return _project_return_failure(
            financing=financing,
            status=ProjectReturnStatus.UNCLASSIFIED_OTHER_PROJECT_USE,
            hard_capex_timing_authority=None,
        )
    try:
        construction_rows, timing_authority = _construction_investment_rows(
            project_inputs, financing
        )
    except _ProjectReturnAuthorityError as exc:
        return _project_return_failure(
            financing=financing,
            status=exc.status,
            hard_capex_timing_authority=None,
        )

    cash_tax, terminal_unpaid_tax = _unlevered_cash_tax_by_period(
        project_inputs, financing
    )
    by_date: dict[date, list[float]] = defaultdict(lambda: [0.0, 0.0, 0.0, 0.0])

    for cash_date, amount in construction_rows:
        by_date[cash_date][0] += amount

    for period in model.periods:
        if not period.is_operation:
            continue
        values = by_date[period.period_end]
        values[1] += float(period.ebitda_keur)
        values[2] += cash_tax.get(period.period_index, 0.0)

    rows: list[ProjectReturnCashFlow] = []
    for cash_date in sorted(by_date):
        investment, operating, tax, terminal = by_date[cash_date]
        rows.append(ProjectReturnCashFlow(
            cashflow_date=cash_date,
            project_investment_outflow_keur=investment,
            project_operating_inflow_keur=operating,
            project_tax_outflow_keur=tax,
            terminal_component_keur=terminal,
            net_unlevered_project_cashflow_keur=(
                operating - tax + terminal - investment
            ),
        ))

    values = [row.net_unlevered_project_cashflow_keur for row in rows]
    dates = [row.cashflow_date for row in rows]
    xirr = None if abs(terminal_unpaid_tax) > _TOL else robust_xirr(values, dates)
    status = (
        ProjectReturnStatus.TERMINAL_PROJECT_TAX_OUTSIDE_HORIZON
        if abs(terminal_unpaid_tax) > _TOL
        else _status(values, xirr)
    )
    return ProjectReturnResult(
        cashflows=tuple(rows),
        project_xirr=xirr,
        project_xirr_status=status,
        total_hard_capex_investment_keur=sum(
            row.project_investment_outflow_keur for row in rows
        ),
        excluded_financing_cost_uses_keur=(
            financing.project_uses.explicit_financing_cost_uses_keur
        ),
        excluded_reserve_funding_keur=(
            financing.project_uses.reserve_account_funding_keur
        ),
        other_explicit_project_uses_keur=(
            financing.project_uses.other_explicit_project_uses_keur
        ),
        total_operating_inflow_keur=sum(
            row.project_operating_inflow_keur for row in rows
        ),
        total_project_tax_outflow_keur=sum(
            row.project_tax_outflow_keur for row in rows
        ),
        terminal_unpaid_project_tax_keur=terminal_unpaid_tax,
        terminal_component_keur=0.0,
        hard_capex_timing_authority=timing_authority,
        methodology_authority=_PROJECT_RETURN_AUTHORITY,
    )


def _date_for_period(
    periods: tuple["CovenantGatedWaterfallPeriod", ...],
    period_index: int | None,
) -> date | None:
    if period_index is None:
        return None
    return next(
        (period.cashflow_date for period in periods if period.period_index == period_index and not period.is_construction),
        None,
    )


def _senior_terminal_state(
    model: object,
    periods: tuple["CovenantGatedWaterfallPeriod", ...],
) -> DebtTerminalState:
    senior = model.senior_debt
    senior_axis = tuple(getattr(model.axis_contract, "senior_axis", ()))
    senior_maturity = senior_axis[-1] if senior_axis else None
    senior_applicable = senior is not None and float(senior.debt_size_keur) > _TOL
    if not senior_applicable:
        return DebtTerminalState(
            contractual_maturity_period_index=None,
            contractual_maturity_date=None,
            balance_at_contractual_maturity_keur=0.0,
            terminal_model_horizon_balance_keur=0.0,
            status=DebtTerminalStatus.NOT_APPLICABLE,
        )

    closing_by_period = {
        int(period_index): float(closing)
        for period_index, closing in zip(
            senior.period_indices, senior.senior_debt_closing_keur
        )
    }
    if senior_maturity not in closing_by_period:
        raise ValueError("C1_SENIOR_MATURITY_BALANCE_MISSING_FROM_CANONICAL_SCHEDULE")
    maturity_balance = closing_by_period[senior_maturity]
    horizon_balance = float(senior.senior_debt_closing_keur[-1])
    return DebtTerminalState(
        contractual_maturity_period_index=senior_maturity,
        contractual_maturity_date=_date_for_period(periods, senior_maturity),
        balance_at_contractual_maturity_keur=maturity_balance,
        terminal_model_horizon_balance_keur=horizon_balance,
        status=(
            DebtTerminalStatus.REPAID
            if maturity_balance <= _TOL
            else DebtTerminalStatus.OUTSTANDING_AT_MATURITY
        ),
    )


def _shl_terminal_state(
    shl_contract: object | None,
    periods: tuple["CovenantGatedWaterfallPeriod", ...],
    *,
    shl_repayment_mode: str | None,
    shl_maturity_period_index: int | None,
) -> ShlTerminalState:
    operating_periods = tuple(period for period in periods if not period.is_construction)
    maturity_row = next(
        (
            period
            for period in operating_periods
            if period.period_index == shl_maturity_period_index
        ),
        None,
    )
    horizon_row = operating_periods[-1] if operating_periods else None
    horizon_balance = (
        float(horizon_row.shl_closing_balance_keur) if horizon_row else 0.0
    )
    shl_applicable = shl_contract is not None and (
        float(getattr(shl_contract, "initial_principal_keur", 0.0)) > _TOL
    )
    if not shl_applicable:
        return ShlTerminalState(
            repayment_mode=shl_repayment_mode,
            contractual_maturity_period_index=None,
            contractual_maturity_date=None,
            opening_balance_at_maturity_keur=0.0,
            accrual_at_maturity_keur=0.0,
            contractual_outstanding_at_maturity_keur=0.0,
            contractual_amount_due_at_maturity_keur=0.0,
            amount_paid_at_maturity_keur=0.0,
            unpaid_at_maturity_keur=0.0,
            balance_at_contractual_maturity_keur=0.0,
            terminal_model_horizon_balance_keur=0.0,
            status=ShlTerminalStatus.NOT_APPLICABLE,
        )

    last_period_index = max(
        (period.period_index for period in operating_periods), default=-1
    )
    maturity_reached = (
        shl_maturity_period_index is not None
        and last_period_index >= shl_maturity_period_index
    )
    opening_at_maturity = (
        float(maturity_row.shl_opening_balance_keur) if maturity_row else 0.0
    )
    accrual_at_maturity = float(maturity_row.shl_pik_keur) if maturity_row else 0.0
    outstanding_at_maturity = opening_at_maturity + accrual_at_maturity
    # The typed SHL contract requires no residual at contractual maturity for
    # every repayment mode. The full pre-principal outstanding amount is due at
    # that boundary; this audit classification never manufactures a cash payment.
    amount_due = outstanding_at_maturity if maturity_row else 0.0
    amount_paid = (
        float(maturity_row.actual_shl_principal_paid_keur) if maturity_row else 0.0
    )
    maturity_balance = (
        float(maturity_row.actual_shl_closing_balance_keur)
        if maturity_row else horizon_balance
    )
    unpaid_at_maturity = (
        max(0.0, outstanding_at_maturity - amount_paid)
        if maturity_reached else 0.0
    )

    if maturity_reached and maturity_balance > _TOL:
        status = ShlTerminalStatus.UNPAID_AT_CONTRACTUAL_MATURITY
    elif horizon_balance <= _TOL:
        status = ShlTerminalStatus.REPAID
    else:
        status = ShlTerminalStatus.OUTSTANDING_WITHIN_CONTRACTUAL_TERM

    return ShlTerminalState(
        repayment_mode=shl_repayment_mode,
        contractual_maturity_period_index=shl_maturity_period_index,
        contractual_maturity_date=_date_for_period(
            periods, shl_maturity_period_index
        ),
        opening_balance_at_maturity_keur=opening_at_maturity,
        accrual_at_maturity_keur=accrual_at_maturity,
        contractual_outstanding_at_maturity_keur=outstanding_at_maturity,
        contractual_amount_due_at_maturity_keur=amount_due,
        amount_paid_at_maturity_keur=amount_paid,
        unpaid_at_maturity_keur=unpaid_at_maturity,
        balance_at_contractual_maturity_keur=maturity_balance,
        terminal_model_horizon_balance_keur=horizon_balance,
        status=status,
    )


def _terminal_state(
    financing: "ProjectFinancingResult",
    periods: tuple["CovenantGatedWaterfallPeriod", ...],
    *,
    shl_repayment_mode: str | None,
    shl_maturity_period_index: int | None,
) -> TerminalFinancialState:
    model = financing.project_model_result
    shl_contract = financing.shareholder_loan_model_input
    operating_periods = tuple(period for period in periods if not period.is_construction)
    terminal_row = operating_periods[-1] if operating_periods else None

    da_terminal = float(terminal_row.distribution_account_closing_keur) if terminal_row else 0.0
    da_status = (
        CashAccountTerminalStatus.STRANDED_CASH if da_terminal > _TOL
        else CashAccountTerminalStatus.CASH_SHORTFALL if da_terminal < -_TOL
        else CashAccountTerminalStatus.RELEASED
    )
    dsra = model.cash_dsra
    dsra_applicable = dsra is not None and (
        str(getattr(dsra.mode, "value", dsra.mode)) == "CASH_DSRA"
    )
    dsra_terminal = float(dsra.final_closing_balance_keur) if dsra is not None else 0.0
    dsra_status = (
        CashAccountTerminalStatus.NOT_APPLICABLE if not dsra_applicable
        else CashAccountTerminalStatus.RELEASED if abs(dsra_terminal) <= _TOL
        else CashAccountTerminalStatus.REMAINING_BALANCE
    )

    return TerminalFinancialState(
        senior=_senior_terminal_state(model, periods),
        shareholder_loan=_shl_terminal_state(
            shl_contract,
            periods,
            shl_repayment_mode=shl_repayment_mode,
            shl_maturity_period_index=shl_maturity_period_index,
        ),
        distribution_account=CashAccountTerminalState(
            terminal_closing_balance_keur=da_terminal,
            status=da_status,
        ),
        senior_dsra=CashAccountTerminalState(
            terminal_closing_balance_keur=dsra_terminal,
            status=dsra_status,
        ),
    )


def build_decision_complete_return_summary(
    *,
    project_inputs: "ProjectInputs",
    financing: "ProjectFinancingResult",
    waterfall_periods: tuple["CovenantGatedWaterfallPeriod", ...],
    pure_equity_xirr: float | None,
    pure_equity_xirr_status: ReturnMetricStatus,
    pure_equity_moic: float | None,
    pure_equity_moic_status: ReturnMetricStatus,
    total_sponsor_xirr: float | None,
    total_sponsor_xirr_status: ReturnMetricStatus,
    total_sponsor_moic: float | None,
    total_sponsor_moic_status: ReturnMetricStatus,
    total_legal_equity_contributed_keur: float,
    total_legal_equity_distributions_keur: float,
    total_sponsor_contributed_keur: float,
    total_sponsor_receipts_keur: float,
    deductible_shl_covenant_feedback_status: str | None,
    shl_repayment_mode: str | None,
    shl_maturity_period_index: int | None,
) -> DecisionCompleteReturnSummary:
    """Build one immutable downstream summary from already-authoritative values."""
    return DecisionCompleteReturnSummary(
        project=_project_return(project_inputs, financing),
        legal_equity=ReturnMetricSummary(
            xirr=pure_equity_xirr,
            xirr_status=pure_equity_xirr_status,
            moic=pure_equity_moic,
            moic_status=pure_equity_moic_status,
            total_contributions_keur=total_legal_equity_contributed_keur,
            total_receipts_keur=total_legal_equity_distributions_keur,
            net_cashflow_keur=(
                total_legal_equity_distributions_keur
                - total_legal_equity_contributed_keur
            ),
        ),
        total_sponsor=ReturnMetricSummary(
            xirr=total_sponsor_xirr,
            xirr_status=total_sponsor_xirr_status,
            moic=total_sponsor_moic,
            moic_status=total_sponsor_moic_status,
            total_contributions_keur=total_sponsor_contributed_keur,
            total_receipts_keur=total_sponsor_receipts_keur,
            net_cashflow_keur=total_sponsor_receipts_keur - total_sponsor_contributed_keur,
        ),
        terminal=_terminal_state(
            financing,
            waterfall_periods,
            shl_repayment_mode=shl_repayment_mode,
            shl_maturity_period_index=shl_maturity_period_index,
        ),
        deductible_shl_covenant_feedback_status=(
            deductible_shl_covenant_feedback_status
        ),
    )
