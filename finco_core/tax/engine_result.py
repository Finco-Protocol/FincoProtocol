"""Phase 6B.4 — SPV tax engine result models.

Immutable dataclasses that carry the output of run_spv_tax_engine().
No mutation, no side effects, no waterfall wiring.

CAVEAT: These are pure result containers. No cashflow wiring,
no deferred tax accounting, no HoldCo logic — those are handled
by a future tax engine layer.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

__all__ = [
    "SPVTaxPeriodResult",
    "SPVTaxResult",
]


@dataclass(frozen=True)
class SPVTaxPeriodResult:
    """Single period result from the SPV tax engine.

    Captures the full tax calculation for one reporting period:
    EBITDA → taxable income → CIT payable.

    Attributes
    ----------
    period : int
        Period index (0-based).
    ebitda_keur : float
        EBITDA in thousands of EUR.
    deductible_interest_keur : float
        Deductible interest expense in kEUR.
    book_depreciation_keur : float
        Book (accounting) depreciation charge in kEUR.
    tax_depreciation_keur : float
        Tax-deductible depreciation claimed in kEUR.
    non_deductible_depreciation_keur : float
        Current-period timing difference (book dep - tax dep claimed).
        This is a **delta only** — not the accumulated pool.
        Note: accumulated depreciation timing difference is tracked in
        ``TaxDepreciationSchedule.accumulated_non_deductible_depreciation_keur``
        and is not currently carried in ``SPVTaxPeriodResult``. Future
        reporting extensions may expose it.
    taxable_income_before_losses_keur : float
        Taxable income after EBITDA, interest, tax depreciation,
        and non-deductible addbacks — but before loss carryforward usage.
    loss_used_keur : float
        Tax losses utilised in this period (from opening loss pool).
    taxable_income_after_losses_keur : float
        Taxable income after loss carryforward utilisation.
        Must be >= 0 for CIT to be payable.
    cit_payable_keur : float
        Corporate income tax payable in kEUR.
        0 when taxable_income_after_losses <= 0.
    closing_loss_carryforward_keur : float
        Remaining loss pool at end of this period (carried to next period).
    effective_tax_rate : float
        Effective CIT rate as a decimal: cit_payable / taxable_income_after_losses.
        0.0 when taxable income is <= 0 or not positive.
        Must be in [0.0, 1.0] where taxable income > 0.
    """
    period: int
    ebitda_keur: float
    deductible_interest_keur: float
    book_depreciation_keur: float
    tax_depreciation_keur: float
    non_deductible_depreciation_keur: float
    taxable_income_before_losses_keur: float
    loss_used_keur: float
    taxable_income_after_losses_keur: float
    cit_payable_keur: float
    closing_loss_carryforward_keur: float
    effective_tax_rate: float

    def __post_init__(self):
        """Validate numeric consistency."""
        # No NaN / inf
        for field in (
            "ebitda_keur", "deductible_interest_keur",
            "book_depreciation_keur", "tax_depreciation_keur",
            "non_deductible_depreciation_keur", "taxable_income_before_losses_keur",
            "loss_used_keur", "taxable_income_after_losses_keur",
            "cit_payable_keur", "closing_loss_carryforward_keur",
            "effective_tax_rate",
        ):
            val = getattr(self, field)
            if val != val:  # NaN check
                raise ValueError(f"{field} must not be NaN, got {val}")
            if val == float("inf") or val == float("-inf"):
                raise ValueError(f"{field} must not be inf, got {val}")

        # effective_tax_rate in [0, 1] when taxable income positive
        if self.taxable_income_after_losses_keur > 0:
            if not (0.0 <= self.effective_tax_rate <= 1.0):
                raise ValueError(
                    f"effective_tax_rate must be in [0,1] when taxable income > 0, "
                    f"got {self.effective_tax_rate}"
                )


@dataclass(frozen=True)
class SPVTaxResult:
    """Complete SPV tax engine result for one entity and tax year.

    Produced by ``run_spv_tax_engine()``.
    Aggregate totals are computed from per-period results.

    Attributes
    ----------
    entity_code : str
        Entity identifier (e.g., "SPV-001").
    country_code : str
        ISO country code of tax jurisdiction.
    tax_year : int
        Tax year.
    periods : tuple[SPVTaxPeriodResult, ...]
        Per-period tax results.
    total_taxable_income_before_losses_keur : float
        Sum of all period ``taxable_income_before_losses_keur``.
    total_loss_used_keur : float
        Sum of all period ``loss_used_keur``.
    total_taxable_income_after_losses_keur : float
        Sum of all period ``taxable_income_after_losses_keur``.
        Does NOT equal total_taxable_income_before_losses - total_loss_used
        because periods with negative taxable income generate losses (taxable_after
        is floored at 0). For example, if period 1 has taxable_before = -200,
        loss_used in that period = 0 and taxable_after = 0 (no positive income
        to offset).
    total_cit_payable_keur : float
        Sum of all period ``cit_payable_keur``.
    ending_loss_carryforward_keur : float
        Loss pool remaining after the final period.
    """
    entity_code: str
    country_code: str
    tax_year: int
    periods: tuple[SPVTaxPeriodResult, ...]
    total_taxable_income_before_losses_keur: float
    total_loss_used_keur: float
    total_taxable_income_after_losses_keur: float
    total_cit_payable_keur: float
    ending_loss_carryforward_keur: float

    def __post_init__(self):
        """Validate totals reconciliation and field consistency."""
        # Non-empty entity code
        if not self.entity_code or not self.entity_code.strip():
            raise ValueError("entity_code must be non-empty")

        # No NaN / inf on aggregates
        for field in (
            "total_taxable_income_before_losses_keur",
            "total_loss_used_keur",
            "total_taxable_income_after_losses_keur",
            "total_cit_payable_keur",
            "ending_loss_carryforward_keur",
        ):
            val = getattr(self, field)
            if val != val:  # NaN check
                raise ValueError(f"{field} must not be NaN, got {val}")
            if val == float("inf") or val == float("-inf"):
                raise ValueError(f"{field} must not be inf, got {val}")

        # Totals reconciliation: sum of period taxable_income_before_losses
        computed_before = sum(p.taxable_income_before_losses_keur for p in self.periods)
        if abs(computed_before - self.total_taxable_income_before_losses_keur) > 1e-6:
            raise ValueError(
                f"total_taxable_income_before_losses_keur mismatch: "
                f"passed {self.total_taxable_income_before_losses_keur}, "
                f"computed {computed_before:.4f}"
            )

        # Totals reconciliation: sum of period loss_used
        computed_loss_used = sum(p.loss_used_keur for p in self.periods)
        if abs(computed_loss_used - self.total_loss_used_keur) > 1e-6:
            raise ValueError(
                f"total_loss_used_keur mismatch: "
                f"passed {self.total_loss_used_keur}, "
                f"computed {computed_loss_used:.4f}"
            )

        # Totals reconciliation: sum of period taxable_income_after_losses
        computed_after = sum(p.taxable_income_after_losses_keur for p in self.periods)
        if abs(computed_after - self.total_taxable_income_after_losses_keur) > 1e-6:
            raise ValueError(
                f"total_taxable_income_after_losses_keur mismatch: "
                f"passed {self.total_taxable_income_after_losses_keur}, "
                f"computed {computed_after:.4f}"
            )

        # Totals reconciliation: sum of period cit_payable
        computed_cit = sum(p.cit_payable_keur for p in self.periods)
        if abs(computed_cit - self.total_cit_payable_keur) > 1e-6:
            raise ValueError(
                f"total_cit_payable_keur mismatch: "
                f"passed {self.total_cit_payable_keur}, "
                f"computed {computed_cit:.4f}"
            )

        # ending_loss_carryforward should match last period
        if self.periods:
            last = self.periods[-1]
            if abs(last.closing_loss_carryforward_keur - self.ending_loss_carryforward_keur) > 1e-6:
                raise ValueError(
                    f"ending_loss_carryforward_keur mismatch: "
                    f"passed {self.ending_loss_carryforward_keur}, "
                    f"last period closing {last.closing_loss_carryforward_keur:.4f}"
                )