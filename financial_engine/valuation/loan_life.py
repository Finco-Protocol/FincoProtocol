"""Additive loan-life and rolling coverage. Never sizes or amortises debt.

Maturity/payoff authority is FIN-V2-2 SENIOR_DEBT_EVIDENCE_V1. Callers without
that contract get an explicit refusal; no zero-filled schedule is interpreted
as a loan-life contract. Discount arithmetic is shared with canonical C2.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import math

from finco_core.inputs.valuation import (
    CoverageCfadsCase, CoverageCashflowBasis, CoverageDenominatorBasis,
    CoverageCalculationDatePolicy, LoanLifeConvention,
)
from financial_engine.valuation.model import _DatedAmount, discount_dated_cashflows, _DiscountError
from financial_engine.valuation.contracts import DiscountAuditRow


class LoanLifeStatus(str, Enum):
    OK = "OK"
    NOT_CONFIGURED = "NOT_CONFIGURED"
    NOT_APPLICABLE_NO_SENIOR = "NOT_APPLICABLE_NO_SENIOR"
    DEBT_EVIDENCE_NOT_AVAILABLE = "DEBT_EVIDENCE_NOT_AVAILABLE"
    DEBT_EVIDENCE_MISMATCH = "DEBT_EVIDENCE_MISMATCH"
    PERIOD_AXIS_MISMATCH = "PERIOD_AXIS_MISMATCH"
    UNSUPPORTED_CASHFLOW_AUTHORITY = "UNSUPPORTED_CASHFLOW_AUTHORITY"
    INVALID_DISCOUNT_POLICY = "INVALID_DISCOUNT_POLICY"
    NON_FINITE_RESULT = "NON_FINITE_RESULT"


@dataclass(frozen=True)
class CoverageObservation:
    period_index: int
    observation_date: str
    horizon_end_period_index: int
    horizon_end_date: str
    opening_senior_balance_keur: float
    pv_cfads_keur: float
    ratio: float
    periods: tuple[DiscountAuditRow, ...]


@dataclass(frozen=True)
class LoanLifeCoverage:
    status: LoanLifeStatus
    reason: str
    contractual: CoverageObservation | None = None
    actual_repayment: CoverageObservation | None = None
    plcr: CoverageObservation | None = None
    rolling: tuple[CoverageObservation, ...] = ()
    minimum: CoverageObservation | None = None


def calculate_loan_life_coverage(model, policy, debt_evidence, senior_terminal):
    senior = model.senior_debt
    if senior is None or senior.debt_size_keur <= 1e-9:
        return LoanLifeCoverage(LoanLifeStatus.NOT_APPLICABLE_NO_SENIOR, "No Senior debt")
    if policy is None or policy.annual_discount_rate is None or policy.cfads_case is None:
        return LoanLifeCoverage(LoanLifeStatus.NOT_CONFIGURED, "Explicit coverage rate and CFADS case required")
    if (policy.llcr_cashflow_basis is not CoverageCashflowBasis.RAW_SELECTED_CFADS
            or policy.plcr_cashflow_basis is not CoverageCashflowBasis.RAW_SELECTED_CFADS
            or policy.denominator_basis is not CoverageDenominatorBasis.SENIOR_OPENING_BALANCE
            or policy.calculation_date_policy is not CoverageCalculationDatePolicy.FIRST_SENIOR_PERIOD_OPENING):
        return LoanLifeCoverage(LoanLifeStatus.UNSUPPORTED_CASHFLOW_AUTHORITY, "Explicit raw selected CFADS and Senior opening required; reserves excluded")
    if not isinstance(debt_evidence, dict) or debt_evidence.get("schema_version") != "SENIOR_DEBT_EVIDENCE_V1" or debt_evidence.get("status") != "RECORDED":
        return LoanLifeCoverage(LoanLifeStatus.DEBT_EVIDENCE_NOT_AVAILABLE, "FIN-V2-2 maturity/payoff contract required")
    try:
        boundaries = debt_evidence["llcr_inputs"]["loan_life_end_candidates"]
        contractual = boundaries["contractual_maturity_period_index"]
        actual = boundaries["actual_payoff_period_index"]
        if type(contractual) is not int or type(actual) is not int or actual > contractual:
            raise ValueError("Maturity and extinguishment must be explicit supported indices")
        periods = tuple(model.periods)
        indices = tuple(p.period_index for p in periods)
        starts = tuple(p.period_start for p in periods)
        ends = tuple(p.period_end for p in periods)
        if len(set(indices)) != len(indices) or indices != tuple(sorted(indices)) or len(set(ends)) != len(ends) or any(a >= b for a, b in zip(starts, ends)):
            return LoanLifeCoverage(LoanLifeStatus.PERIOD_AXIS_MISMATCH, "Invalid canonical period calendar")
        by_index = {p.period_index: p for p in periods}
        if (contractual != senior_terminal.contractual_maturity_period_index
                or by_index[contractual].period_end.isoformat() != boundaries["contractual_maturity_date"]
                or by_index[actual].period_end.isoformat() != boundaries["actual_payoff_date"]):
            raise ValueError("Debt evidence dates differ from canonical schedule")
        si = tuple(senior.period_indices)
        opening = tuple(senior.senior_debt_opening_keur)
        closing = tuple(senior.senior_debt_closing_keur)
        if len(set(si)) != len(si) or not len(si) == len(opening) == len(closing) or any(i not in by_index for i in si):
            return LoanLifeCoverage(LoanLifeStatus.PERIOD_AXIS_MISMATCH, "Invalid Senior axis")
        balances = dict(zip(si, opening))
        close = dict(zip(si, closing))
        if balances.get(actual, 0) <= 1e-9 or close[actual] > 1e-4 or any(balances[i] > 1e-4 for i in si if i > actual):
            raise ValueError("Payoff contract does not reconcile to authoritative balances")
        vector = model.tax_and_cfads if policy.cfads_case is CoverageCfadsCase.BASE else model.debt_sizing
        values = tuple(vector.cfads_keur if policy.cfads_case is CoverageCfadsCase.BASE else vector.bank_cfads_keur)
        if tuple(vector.period_indices) != indices or len(values) != len(indices):
            return LoanLifeCoverage(LoanLifeStatus.PERIOD_AXIS_MISMATCH, "CFADS must match canonical dates/indices exactly")
        cfads = dict(zip(indices, values))
        operating = tuple(p for p in periods if p.is_operation)
        observations = tuple(p for p in operating if balances.get(p.period_index, 0) > 1e-9)
        if not observations:
            raise ValueError("No outstanding Senior balance on an operating observation date")
        def at(period, end):
            window = tuple(p for p in operating if period.period_index <= p.period_index <= end)
            dated = tuple(_DatedAmount(p.period_index, p.period_end, float(cfads[p.period_index])) for p in window)
            audit, pv = discount_dated_cashflows(valuation_date=period.period_start, cashflows=dated,
                annual_discount_rate=policy.annual_discount_rate, convention=policy.discount_convention,
                periodic_rate_conversion=policy.periodic_rate_conversion, periods_per_year=policy.periods_per_year,
                first_cashflow_timing=policy.first_cashflow_timing)
            balance = float(balances[period.period_index])
            ratio = pv / balance
            if not math.isfinite(ratio):
                raise _DiscountError("NON_FINITE_RESULT")
            return CoverageObservation(period.period_index, period.period_start.isoformat(), end,
                by_index[end].period_end.isoformat(), balance, pv, ratio, audit)
        end = actual if policy.rolling_loan_life is LoanLifeConvention.ACTUAL_REPAYMENT else contractual
        rolling = tuple(at(p, end) for p in observations if p.period_index <= end)
        first = observations[0]
        return LoanLifeCoverage(LoanLifeStatus.OK, "CFADS excludes reserve additions; BANK is the debt-sizing case, not P50",
            at(first, contractual), at(first, actual), at(first, operating[-1].period_index), rolling,
            min(rolling, key=lambda p: p.ratio))
    except _DiscountError as exc:
        return LoanLifeCoverage(LoanLifeStatus.INVALID_DISCOUNT_POLICY, exc.code)
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        return LoanLifeCoverage(LoanLifeStatus.DEBT_EVIDENCE_MISMATCH, str(exc))
