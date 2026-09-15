"""Immutable G2B sponsor-return result contracts.

GENERIC MVP POLICY — not canonical source truth.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum


class ReturnMetricStatus(Enum):
    """Typed status for sponsor return metrics."""
    OK = "OK"
    NO_NEGATIVE_CASHFLOW = "NO_NEGATIVE_CASHFLOW"
    NO_POSITIVE_CASHFLOW = "NO_POSITIVE_CASHFLOW"
    ZERO_CONTRIBUTION = "ZERO_CONTRIBUTION"
    NON_CONVERGENT = "NON_CONVERGENT"
    UNDEFINED = "UNDEFINED"
    UPSTREAM_FINANCIAL_FEEDBACK_NOT_CLOSED = "UPSTREAM_FINANCIAL_FEEDBACK_NOT_CLOSED"
    UNPAID_SHL_AT_CONTRACTUAL_MATURITY = "UNPAID_SHL_AT_CONTRACTUAL_MATURITY"


class SponsorDistributionPolicy(Enum):
    """Typed distribution policy label.

    DISTRIBUTE_ALL_POST_SHL_CASH:
      legal-equity distribution in an operating period equals the available
      non-negative cash remaining after Senior and SHL cash service.

      GENERIC MVP POLICY — no DSRA, no MRA, no distribution account,
      no lock-up, no minimum cash reserve, no dividend WHT, no capital account,
      no promote.
    """
    DISTRIBUTE_ALL_POST_SHL_CASH = "DISTRIBUTE_ALL_POST_SHL_CASH"


@dataclass(frozen=True)
class SponsorCashFlowPeriod:
    """Immutable sponsor cash flow for one model period.

    Note on period_index: construction periods use the G2A funding schedule
    monthly index (1..construction_months); operating periods use the model's
    semiannual period index (first operating index > 0). These two index spaces
    may overlap. Use is_construction to disambiguate.

    Sign convention (investor perspective):
      contributions: positive field value, negative net cash flow
      receipts:      positive field value, positive net cash flow

    pure_equity_net_cashflow_keur
      = legal_equity_distribution_keur
        - share_capital_contribution_keur
        - share_premium_contribution_keur
        - other_committed_equity_contribution_keur
        - additional_equity_contribution_keur

    total_sponsor_net_cashflow_keur
      = pure_equity_net_cashflow_keur
        - shl_cash_contribution_keur
        + shl_cash_interest_receipt_keur
        + shl_principal_receipt_keur

    PIK does NOT appear in either net cashflow identity.
    """
    period_index: int
    cashflow_date: date
    is_construction: bool  # True for construction draw periods

    # Contributions (positive field = cash out from sponsor)
    share_capital_contribution_keur: float
    share_premium_contribution_keur: float
    other_committed_equity_contribution_keur: float
    additional_equity_contribution_keur: float
    shl_cash_contribution_keur: float

    # Receipts (positive field = cash in to sponsor)
    shl_cash_interest_receipt_keur: float
    shl_principal_receipt_keur: float
    post_shl_cash_available_keur: float
    legal_equity_distribution_keur: float
    cash_shortfall_keur: float  # >= 0; positive when post-SHL cash is negative

    # Net cashflows
    pure_equity_net_cashflow_keur: float
    total_sponsor_net_cashflow_keur: float


@dataclass(frozen=True)
class SponsorReturnResult:
    """Immutable G2B sponsor return summary.

    Downstream-only: does not feed back into debt sizing, tax, SHL, or
    construction funding. No circular financial dependency.
    """
    # G2A financing result reference (stored as object to avoid circular import)
    financing_result: object

    distribution_policy: SponsorDistributionPolicy
    cashflow_periods: tuple[SponsorCashFlowPeriod, ...]

    # Contribution totals
    total_share_capital_contributed_keur: float
    total_share_premium_contributed_keur: float
    total_other_committed_equity_contributed_keur: float
    total_additional_equity_contributed_keur: float
    total_legal_equity_contributed_keur: float
    total_shl_cash_contributed_keur: float
    total_sponsor_contributed_keur: float

    # Receipt totals
    total_shl_cash_interest_received_keur: float
    total_shl_principal_received_keur: float
    total_legal_equity_distributions_keur: float
    total_sponsor_receipts_keur: float

    # Pure Legal Equity metrics
    pure_equity_xirr: float | None
    pure_equity_xirr_status: ReturnMetricStatus
    pure_equity_moic: float | None
    pure_equity_moic_status: ReturnMetricStatus

    # Total Sponsor metrics
    total_sponsor_xirr: float | None
    total_sponsor_xirr_status: ReturnMetricStatus
    total_sponsor_moic: float | None
    total_sponsor_moic_status: ReturnMetricStatus

    # BULLET fail-closed state
    # True if contractual BULLET balloon exceeded available project cash at maturity.
    # When True: all four return metrics are None / UNPAID_SHL_AT_CONTRACTUAL_MATURITY
    # and post-maturity legal-equity distributions are zero.
    shl_bullet_unpaid_at_maturity: bool = False
