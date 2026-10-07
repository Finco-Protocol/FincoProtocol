"""Immutable Developer Economics V1 result contracts.

Developer Economics is a separate investor/developer ledger.  These contracts
carry its facts; they never carry sponsor or project returns.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum

DEVELOPER_ECONOMICS_METHODOLOGY = (
    "DEVELOPER_ECONOMICS_V1_SEPARATE_LEDGER_XIRR_OVER_OWN_DATED_CASHFLOWS"
)


class DeveloperMetricStatus(Enum):
    """Typed availability status for developer metrics.

    Value spellings are IDENTICAL to the repository's ``ReturnMetricStatus``
    vocabulary (pinned by a test) so canonical analytics passes ``source_status``
    verbatim. Defined locally because importing the sponsor_returns package here
    would create an import cycle (it imports the financing stack, which consumes
    the developer project uses).
    """

    OK = "OK"
    NO_NEGATIVE_CASHFLOW = "NO_NEGATIVE_CASHFLOW"      # no development spend
    NO_POSITIVE_CASHFLOW = "NO_POSITIVE_CASHFLOW"      # spend but no receipts
    NON_CONVERGENT = "NON_CONVERGENT"
    ZERO_CONTRIBUTION = "ZERO_CONTRIBUTION"            # MOIC denominator has no authority


@dataclass(frozen=True)
class DeveloperProjectUses:
    """The PROJECT-ledger uses created by Developer Economics (kEUR).

    Reimbursement and developer fee are kept as two typed fields — they are
    never collapsed into one ambiguous amount.
    """

    development_cost_reimbursement_keur: float = 0.0
    developer_fee_keur: float = 0.0
    # Typed book-basis treatment (DeveloperBookBasisMode value); None only when no uses.
    book_basis_mode: str | None = None

    @property
    def total_keur(self) -> float:
        return self.development_cost_reimbursement_keur + self.developer_fee_keur


@dataclass(frozen=True)
class DeveloperFeeBasisEvidence:
    """How the developer fee was sized (audit; proves the basis is non-circular)."""

    mode: str                       # DeveloperFeeMode value
    fee_value: float                # kEUR (FIXED_KEUR) or 0..1 fraction (PCT_OF_HARD_CAPEX)
    basis_keur: float | None        # None for FIXED_KEUR
    basis_authority: str            # exact basis definition
    fee_keur: float


@dataclass(frozen=True)
class DeveloperCashFlow:
    """One dated row of the developer's own cash-flow vector (kEUR)."""

    cashflow_date: date
    development_spend_keur: float                  # outflow magnitude (>= 0)
    development_cost_reimbursement_keur: float     # receipt
    developer_fee_keur: float                      # receipt
    net_developer_cashflow_keur: float             # receipts - spend


@dataclass(frozen=True)
class DeveloperEconomicsResult:
    """Developer ledger result.  MISSING != ZERO: unavailable metrics are None."""

    outcome: str                                   # DevelopmentOutcome value
    settlement_date: date                          # canonical Financial Close
    cashflows: tuple[DeveloperCashFlow, ...]
    total_development_spend_keur: float
    reimbursed_development_cost_keur: float
    developer_fee_keur: float
    total_developer_receipts_keur: float
    developer_moic: float | None
    developer_moic_status: DeveloperMetricStatus
    developer_xirr: float | None
    developer_xirr_status: DeveloperMetricStatus
    fee_basis: DeveloperFeeBasisEvidence
    methodology_authority: str = DEVELOPER_ECONOMICS_METHODOLOGY

    @property
    def project_uses(self) -> DeveloperProjectUses:
        return DeveloperProjectUses(
            development_cost_reimbursement_keur=self.reimbursed_development_cost_keur,
            developer_fee_keur=self.developer_fee_keur,
        )
