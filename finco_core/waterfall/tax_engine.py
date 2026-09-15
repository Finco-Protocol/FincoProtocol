"""Tax engine — period-based tax computation with ATAD, loss carryforward, and fiscal reintegration.

C3B3D0 arithmetic identity (deductible-only, correct):
    taxable_income = EBITDA - dep - deductible_interest + reintegration
    where deductible_interest = ATAD_cap(senior_interest + SHL_deductible_fraction)

    Equivalently expressed using gross interest:
    taxable_income = EBITDA - dep - gross_interest + disallowed_interest + reintegration
    where gross_interest = senior_interest + SHL_deductible_fraction
          disallowed_interest = max(0, gross_interest - ATAD_cap)

    These two formulations are algebraically identical:
        EBITDA - dep - deductible + reint
      = EBITDA - dep - (gross - disallowed) + reint
      = EBITDA - dep - gross + disallowed + reint  ✓

    Why the old identity (C3B3C) was UNSAFE when ATAD binds:
        old: taxable = EBITDA - dep - deductible_interest + disallowed_interest + reint
        When ATAD doesn't bind: deductible=gross, disallowed=0 → correct.
        When ATAD DOES bind: deductible=ATAD_cap < gross, disallowed=gross-ATAD_cap.
            old = EBITDA - dep - ATAD_cap + (gross - ATAD_cap) + reint
                = EBITDA - dep + gross - 2*ATAD_cap + reint  ← DOUBLE-COUNTS non-deductible
        The correct result = EBITDA - dep - ATAD_cap + reint (deductible-only).
        The old formula was dormant in production (ATAD min threshold > senior interest),
        but structurally wrong whenever ATAD binds. Removed in C3B3D0.

    disallowed_interest_keur is an AUDIT FIELD ONLY (like shl_non_deductible_keur).
    It is NOT added to taxable income.

    shl_non_deductible_keur is an audit field ONLY — it is NOT added to taxable income.

ATAD and thin-cap are INDEPENDENT policies (C3B3D0):
    atad_enabled in TaxParams controls ATAD interest limitation (Art. 4 ATAD).
    thin_cap_enabled controls the thin-capitalisation limitation (separate mechanism).
    Neither is derived from the other.

Controlled examples:
    No ATAD binding (ebitda=5000, dep=1000, senior=500, SHL=300):
        FULLY_DEDUCTIBLE:     TI = 5000-1000-800 = 3200
        FULLY_NON_DEDUCTIBLE: TI = 5000-1000-500 = 3500  (SHL simply not deducted)
        CUSTOM 50%:           TI = 5000-1000-650 = 3350

    ATAD binding (ebitda=5000, dep=1000, gross_interest=2000, atad_min=1000):
        ebitda_limit = 5000*0.30 = 1500; deductible_limit = max(1500, 1000) = 1500
        2000 > 1500 → ATAD binds: deductible=1500, disallowed=500
        TI = 5000 - 1000 - 1500 = 2500
        Gross check: 5000 - 1000 - 2000 + 500 = 2500 ✓
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from finco_core.inputs._models import ShlInterestDeductibilityMode


@dataclass(frozen=True)
class TaxPeriodResult:
    """Result of tax calculation for a single period.

    All fields in kEUR for auditability.
    """
    # Pre-loss taxable income components
    ebitda_keur: float
    co2_cit_bridge_keur: float  # CO2 revenue included in EBITDA for CIT (Phase 9)
    depreciation_keur: float
    deductible_interest_keur: float
    disallowed_interest_keur: float  # AUDIT ONLY — not added to taxable income (C3B3D0)
    fiscal_reintegration_keur: float  # Construction-period cost add-back (selected reference tax policy)
    # C3B3C audit field: non-deductible SHL kEUR (NOT added to taxable income).
    # = shl_interest_keur * (1 - deductible_pct). For FULLY_NON_DEDUCTIBLE = full SHL.
    shl_non_deductible_keur: float

    # Loss carryforward application
    taxable_income_before_losses_keur: float  # Before loss CF application
    loss_carryforward_applied_keur: float
    loss_carryforward_remaining_keur: float

    # Final taxable income and tax
    taxable_income_keur: float  # After loss CF
    tax_keur: float


def compute_period_tax(
    ebitda_keur: float,
    depreciation_keur: float,
    senior_interest_keur: float,
    shl_interest_keur: float,
    loss_carryforward_keur: float,
    tax_rate: float,
    fiscal_reintegration_keur: float = 0.0,
    atad_applies: bool = True,
    atad_ebitda_limit: float = 0.30,
    atad_min_threshold_keur: float = 3000.0,
    loss_carryforward_cap: float = 1.0,
    co2_revenue_keur: float = 0.0,
    shl_interest_deductibility: "ShlInterestDeductibilityMode | None" = None,
    shl_interest_deductible_pct: float | None = None,
) -> TaxPeriodResult:
    """Compute tax for a single period.

    Taxable income = EBITDA - depreciation - deductible_interest + fiscal_reintegration
                     - loss_carryforward
    Tax = max(0, taxable_income) * tax_rate

    disallowed_interest is an AUDIT FIELD ONLY — it is NOT added to taxable income.
    See module docstring for why adding it back is wrong when ATAD binds (C3B3D0).

    SHL deductibility (C3B3C deductible-only method):
        Only the deductible fraction of SHL interest enters the ATAD pool.
        The non-deductible fraction is simply never deducted — no addback required.
        shl_non_deductible_keur in TaxPeriodResult is an audit field only.

    Args:
        ebitda_keur: EBITDA in kEUR
        depreciation_keur: Depreciation in kEUR
        senior_interest_keur: Senior debt interest in kEUR
        shl_interest_keur: SHL interest in kEUR (gross accounting amount)
        loss_carryforward_keur: Prior tax losses available to apply
        tax_rate: Corporate tax rate (e.g., 0.10 for 10%)
        fiscal_reintegration_keur: Construction-period cost add-back (IDC, bank fees, etc.)
        atad_applies: Whether ATAD interest limitation applies (default True)
        atad_ebitda_limit: ATAD EBITDA limit (default 30%)
        atad_min_threshold_keur: ATAD minimum interest threshold (default 3000.0 kEUR)
        loss_carryforward_cap: Max % of profit that can be offset by losses (default 1.0)
        co2_revenue_keur: Phase 9 CO2 CIT bridge — added to EBITDA for taxable income
        shl_interest_deductibility: C3B3C typed SHL deductibility mode. When None,
            falls back to legacy behavior (SHL fully deductible).
        shl_interest_deductible_pct: Required for CUSTOM_DEDUCTIBLE_PERCENTAGE mode.

    Returns:
        TaxPeriodResult with full audit trail
    """
    # ── C3B3C: deductible-only SHL split ──────────────────────────────────────
    # Only the deductible fraction enters the ATAD pool alongside senior interest.
    # Senior interest is ALWAYS fully in the ATAD pool.
    from finco_core.inputs._models import ShlInterestDeductibilityMode as _ShlMode

    shl_deductible_keur = shl_interest_keur   # default: SHL fully deductible (legacy/None)
    shl_non_deductible_keur = 0.0             # audit field only

    if shl_interest_deductibility is not None:
        if shl_interest_deductibility == _ShlMode.FULLY_DEDUCTIBLE:
            shl_deductible_keur = shl_interest_keur
            shl_non_deductible_keur = 0.0
        elif shl_interest_deductibility == _ShlMode.FULLY_NON_DEDUCTIBLE:
            # SHL interest is entirely non-deductible: zero enters the ATAD pool.
            # No addback needed — the amount was never deducted in the first place.
            shl_deductible_keur = 0.0
            shl_non_deductible_keur = shl_interest_keur
        elif shl_interest_deductibility == _ShlMode.CUSTOM_DEDUCTIBLE_PERCENTAGE:
            pct = shl_interest_deductible_pct if shl_interest_deductible_pct is not None else 0.0
            shl_deductible_keur = shl_interest_keur * pct
            shl_non_deductible_keur = shl_interest_keur * (1.0 - pct)
        elif shl_interest_deductibility == _ShlMode.SUBJECT_TO_LIMITATIONS:
            # FAIL CLOSED: limitation engine (thin-cap/ATAD interaction for SHL)
            # is not yet implemented. THIN_CAP_FORMULA_NOT_CONFIGURED.
            raise NotImplementedError(
                "THIN_CAP_FORMULA_NOT_CONFIGURED: "
                "SUBJECT_TO_LIMITATIONS SHL deductibility requires an interest "
                "limitation engine that is not yet implemented. "
                "Set thin_cap_enabled=True only when the formula is proven."
            )

    # Only deductible SHL fraction enters the ATAD pool.
    total_interest = senior_interest_keur + shl_deductible_keur

    # ATAD: limit interest deduction
    if atad_applies:
        ebitda_limit = ebitda_keur * atad_ebitda_limit
        deductible_interest_limit = max(ebitda_limit, atad_min_threshold_keur)

        if total_interest <= deductible_interest_limit:
            deductible_interest = total_interest
            disallowed_interest = 0.0
        else:
            deductible_interest = deductible_interest_limit
            disallowed_interest = total_interest - deductible_interest_limit
    else:
        deductible_interest = total_interest
        disallowed_interest = 0.0

    # Taxable income before losses (C3B3D0 deductible-only identity).
    # Phase 9: CO2 CIT bridge — co2_revenue_keur added to EBITDA for taxable income.
    # disallowed_interest is an AUDIT FIELD ONLY — NOT added here.
    # shl_non_deductible_keur is an AUDIT FIELD ONLY — NOT added here.
    taxable_before_losses = (
        ebitda_keur
        + co2_revenue_keur
        - depreciation_keur
        - deductible_interest
        + fiscal_reintegration_keur
    )

    # Apply loss carryforward (capped at loss_carryforward_cap of profit)
    max_offset = taxable_before_losses * loss_carryforward_cap if taxable_before_losses > 0 else 0.0
    loss_used = min(loss_carryforward_keur, max(0.0, max_offset))
    remaining_loss_cf = max(0.0, loss_carryforward_keur - loss_used)

    # Final taxable income
    taxable_income = max(0.0, taxable_before_losses - loss_used)

    # Tax
    tax_keur = taxable_income * tax_rate

    return TaxPeriodResult(
        ebitda_keur=ebitda_keur,
        co2_cit_bridge_keur=co2_revenue_keur,
        depreciation_keur=depreciation_keur,
        deductible_interest_keur=deductible_interest,
        disallowed_interest_keur=disallowed_interest,
        fiscal_reintegration_keur=fiscal_reintegration_keur,
        shl_non_deductible_keur=shl_non_deductible_keur,
        taxable_income_before_losses_keur=max(0.0, taxable_before_losses),
        loss_carryforward_applied_keur=loss_used,
        loss_carryforward_remaining_keur=remaining_loss_cf,
        taxable_income_keur=taxable_income,
        tax_keur=tax_keur,
    )
