"""Total Sponsor NPV over canonical dated equity AND SHL cash flows."""
from dataclasses import dataclass
from enum import Enum
import math

from finco_core.inputs.valuation import DiscountConvention, SponsorValuationDatePolicy
from financial_engine.valuation.model import _DatedAmount, _DiscountError, discount_dated_cashflows
from financial_engine.valuation.contracts import DiscountAuditRow


class SponsorNpvStatus(str, Enum):
    OK = "OK"
    NOT_CONFIGURED = "NOT_CONFIGURED"
    CASHFLOW_EVIDENCE_UNAVAILABLE = "CASHFLOW_EVIDENCE_UNAVAILABLE"
    UNSUPPORTED_DISCOUNT_CONVENTION = "UNSUPPORTED_DISCOUNT_CONVENTION"
    INVALID_DISCOUNT_POLICY = "INVALID_DISCOUNT_POLICY"
    UNPAID_SHL_AT_CONTRACTUAL_MATURITY = "UNPAID_SHL_AT_CONTRACTUAL_MATURITY"


@dataclass(frozen=True)
class SponsorNpvResult:
    status: SponsorNpvStatus
    npv_keur: float | None = None
    valuation_date: str | None = None
    periods: tuple[DiscountAuditRow, ...] = ()
    reason: str = ""


def calculate_total_sponsor_npv(waterfall, policy, unpaid_at_maturity=False, *, financial_close=None):
    if policy is None or policy.annual_discount_rate is None:
        return SponsorNpvResult(SponsorNpvStatus.NOT_CONFIGURED)
    if unpaid_at_maturity:
        return SponsorNpvResult(SponsorNpvStatus.UNPAID_SHL_AT_CONTRACTUAL_MATURITY)
    if policy.discount_convention is not DiscountConvention.ACT_365_FIXED:
        return SponsorNpvResult(SponsorNpvStatus.UNSUPPORTED_DISCOUNT_CONVENTION)
    if not waterfall or any(p.cashflow_date is None for p in waterfall):
        return SponsorNpvResult(SponsorNpvStatus.CASHFLOW_EVIDENCE_UNAVAILABLE)
    equity_keys = ('share_capital_contribution_keur', 'share_premium_contribution_keur',
                   'other_committed_equity_contribution_keur', 'additional_equity_contribution_keur')
    required = (*equity_keys, 'shl_cash_contribution_keur', 'legal_equity_distribution_keur',
                'shl_cash_interest_receipt_keur', 'actual_shl_principal_paid_keur', 'total_sponsor_net_cashflow_keur')
    for p in waterfall:
        if any(not hasattr(p,k) or not isinstance(getattr(p,k),(float,int)) or not math.isfinite(getattr(p,k)) for k in required):
            return SponsorNpvResult(SponsorNpvStatus.CASHFLOW_EVIDENCE_UNAVAILABLE, reason='Missing contribution/receipt authority')
        expected = (-sum(getattr(p,k) for k in equity_keys)-p.shl_cash_contribution_keur
                    +p.legal_equity_distribution_keur+p.shl_cash_interest_receipt_keur+p.actual_shl_principal_paid_keur)
        if abs(expected-p.total_sponsor_net_cashflow_keur)>1e-6:
            return SponsorNpvResult(SponsorNpvStatus.CASHFLOW_EVIDENCE_UNAVAILABLE, reason='Total Sponsor flow does not reconcile')
    dated = tuple(_DatedAmount(None, p.cashflow_date, p.total_sponsor_net_cashflow_keur) for p in waterfall)
    if tuple(p.cashflow_date for p in waterfall) != tuple(sorted(p.cashflow_date for p in waterfall)):
        return SponsorNpvResult(SponsorNpvStatus.CASHFLOW_EVIDENCE_UNAVAILABLE, reason="Dates out of order")
    valuation_date = (financial_close if policy.valuation_date_policy is SponsorValuationDatePolicy.FINANCIAL_CLOSE
                      else policy.explicit_valuation_date)
    if valuation_date is None:
        return SponsorNpvResult(SponsorNpvStatus.INVALID_DISCOUNT_POLICY, reason="Valuation date required")
    try:
        rows, value = discount_dated_cashflows(valuation_date=valuation_date, cashflows=dated,
            annual_discount_rate=policy.annual_discount_rate, convention=policy.discount_convention)
        return SponsorNpvResult(SponsorNpvStatus.OK, value, valuation_date.isoformat(), rows)
    except _DiscountError as exc:
        return SponsorNpvResult(SponsorNpvStatus.INVALID_DISCOUNT_POLICY, reason=exc.code)
    except (OverflowError, ZeroDivisionError, ValueError, TypeError) as exc:
        return SponsorNpvResult(SponsorNpvStatus.INVALID_DISCOUNT_POLICY, reason=type(exc).__name__)
