"""Construction P&L Statement - determines initial tax loss carryforward.

During the construction period, certain costs are capitalized (not expensed)
and certain items may generate revenue. This creates a book vs. tax difference
that determines the initial tax loss carryforward into the operational phase.

Key items:
- IDC (Interest During Construction): capitalized, not deductible during construction
- Bank fees, commitment fees: capitalized as part of CAPEX
- Pre-operational OpEx: expensed but before COD
- Construction period revenue: any revenue generated before COD

The initial_tax_loss_keur from this statement is used by the waterfall engine
to properly model CIT timing - without it, CIT starts too early (Y1 instead of Y3).
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class ConstructionPLStatement:
    """
    P&L statement for the construction period.

    Used to deterministically compute the initial tax loss carryforward
    that offsets EBT in early operational years, delaying CIT start.

    In Excel, this is implicitly handled via the "tax loss carryforward" schedule.
    In our model, we make it explicit and computed from construction financials.

    Example for Generic Solar Reference (18-month construction):
        IDC: ~1,169 kEUR (capitalized, depreciates after COD)
        Bank fees: ~300 kEUR (capitalized)
        Commitment fees: ~470 kEUR (already in CAPEX, not additional)
        Pre-operational OpEx: ~0 (no revenue before COD)
        Construction revenue: 0
        Initial tax loss: ~1,469 kEUR + construction period timing effects

    The 9,000 kEUR figure in the old code included construction-period interest
    that was capitalized in Excel but not tracked separately in our model.
    With this class, we explicitly model all construction-period financial effects.
    """
    # Capitalized costs (not expensed during construction, depreciated after COD)
    idc_keur: float = 0.0              # Interest During Construction
    bank_fees_keur: float = 0.0        # Bank upfront fees (capitalized)
    commitment_fees_keur: float = 0.0  # Commitment fees on undrawn balance

    # Pre-operational costs (expensed before COD, not capitalized)
    pre_operational_opex_keur: float = 0.0

    # Revenue during construction (rare for project finance, but possible)
    construction_period_revenue_keur: float = 0.0

    # Additional book-vs-tax differences during construction
    # (e.g., construction-period interest that Excel capitalizes but we don't track)
    other_book_tax_difference_keur: float = 0.0

    @property
    def book_loss_keur(self) -> float:
        """
        Book loss during construction period.

        = Capitalized costs + Pre-operational OpEx + Other differences - Revenue

        Note: Capitalized costs (IDC, bank fees, commitment fees) are NOT
        deductible during construction. They are added to the asset base and
        depreciated after COD. This creates a timing difference: book shows
        loss (via depreciation) while tax shows no loss during construction.
        """
        return (
            self.idc_keur
            + self.bank_fees_keur
            + self.commitment_fees_keur
            + self.pre_operational_opex_keur
            + self.other_book_tax_difference_keur
            - self.construction_period_revenue_keur
        )

    @property
    def initial_tax_loss_keur(self) -> float:
        """
        Initial tax loss carryforward entering operational phase.

        This is the amount that can be used to offset taxable profit in the
        first operational years, delaying when CIT becomes payable.

        For Generic Market A: loss carryforward up to 5 years, 100% cap.

        The construction period creates a tax loss because:
        1. Interest during construction is capitalized (not deductible)
        2. Bank/commitment fees are capitalized (not deductible)
        3. Pre-operational costs may be expensed but before COD

        Returns:
            Initial tax loss carryforward in kEUR
        """
        return max(0.0, self.book_loss_keur)

    def validate(self) -> list[str]:
        """
        Validate the construction P&L statement.

        Returns:
            List of validation errors. Empty = valid.
        """
        errors = []

        if self.idc_keur < 0:
            errors.append("IDC cannot be negative")

        if self.bank_fees_keur < 0:
            errors.append("Bank fees cannot be negative")

        if self.commitment_fees_keur < 0:
            errors.append("Commitment fees cannot be negative")

        if self.pre_operational_opex_keur < 0:
            errors.append("Pre-operational OpEx cannot be negative")

        if self.construction_period_revenue_keur < 0:
            errors.append("Construction period revenue cannot be negative")

        return errors


def create_default_construction_pl(
    idc_keur: float = 0.0,
    bank_fees_keur: float = 0.0,
    commitment_fees_keur: float = 0.0,
) -> ConstructionPLStatement:
    """
    Create a default ConstructionPLStatement with given financing costs.

    Args:
        idc_keur: Interest During Construction
        bank_fees_keur: Bank upfront fees
        commitment_fees_keur: Commitment fees on undrawn balance

    Returns:
        ConstructionPLStatement with the given values
    """
    return ConstructionPLStatement(
        idc_keur=idc_keur,
        bank_fees_keur=bank_fees_keur,
        commitment_fees_keur=commitment_fees_keur,
    )


__all__ = [
    "ConstructionPLStatement",
    "create_default_construction_pl",
]