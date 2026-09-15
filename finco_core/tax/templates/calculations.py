"""Phase 6B.1 — Tax calculation primitives using TaxTemplate schema.

These are pure functions. No mutation, no side effects, no waterfall wiring.
Use Phase 6A TaxTemplate schema types (CITTier, TaxDepreciationRule).

CAVEAT: This module implements raw calculation logic only.
No ATAD interest limitation, no thin-cap adjustment, no loss carryforward,
no withholding tax — those are handled by a future tax engine layer.
"""
from __future__ import annotations

from finco_core.tax.templates.inputs import (
    CITTier,
    TaxDepreciationRule,
)


# ── CIT ───────────────────────────────────────────────────────────────────────

def calculate_progressive_cit(
    taxable_profit_keur: float,
    cit_tiers: tuple[CITTier, ...],
) -> float:
    """Calculate CIT for a given taxable profit using progressive bracket tiers.

    Pure function: no mutation of inputs.

    Parameters
    ----------
    taxable_profit_keur : float
        Taxable profit in thousands of EUR. Can be negative or zero.
    cit_tiers : tuple[CITTier, ...]
        CIT brackets. Tiers are sorted internally by min_profit_keur.
        Contiguity and boundedness are assumed (validated at TaxTemplate
        construction time via TaxTemplate.__post_init__).

    Returns
    -------
    float
        Total CIT liability in kEUR. Returns 0.0 when taxable_profit <= 0
        or when tiers is empty.

    Algorithm
    ---------
    For each tier (sorted by min_profit_keur):
        lower = tier.min_profit_keur
        upper = tier.max_profit_keur or taxable_profit_keur  (unbounded → cap at profit)
        taxable_in_tier = max(0, min(profit, upper) - lower)
        tax += taxable_in_tier * tier.tax_rate
        stop when lower >= taxable_profit_keur

    No rounding is applied — raw floating-point arithmetic only.

    Examples
    --------
    Flat 10%: single tier (0, None, 0.10)
      calculate_progressive_cit(1000, tiers) → 100.0

    Progressive 9%/15%:
      tiers = (CITTier(0, 100_000, 0.09), CITTier(100_000, None, 0.15))
      calculate_progressive_cit(150_000, tiers) → 16_500.0
      # 100,000 × 9% = 9,000; 50,000 × 15% = 7,500 → total = 16,500
    """
    if taxable_profit_keur <= 0.0:
        return 0.0

    if not cit_tiers:
        return 0.0

    # Sort tiers by min_profit_keur — does not mutate original tuple
    sorted_tiers = sorted(cit_tiers, key=lambda t: t.min_profit_keur)

    total_tax = 0.0

    for tier in sorted_tiers:
        lower = tier.min_profit_keur

        # Stop if this tier starts at or above the total profit
        if lower >= taxable_profit_keur:
            break

        # Upper bound: bounded tier → use max_profit_keur; unbounded → cap at profit
        upper = tier.max_profit_keur
        if upper is None:
            upper = taxable_profit_keur

        # Profit slice within this tier, clamped to [0, profit]
        taxable_in_tier = max(0.0, min(taxable_profit_keur, upper) - lower)
        total_tax += taxable_in_tier * tier.tax_rate

    return total_tax


# ── Depreciation ──────────────────────────────────────────────────────────────

def get_tax_depreciation_rate(rule: TaxDepreciationRule) -> float:
    """Compute the effective annual tax depreciation rate for a rule.

    Pure function: no mutation of rule.

    Parameters
    ----------
    rule : TaxDepreciationRule
        Depreciation rule for one asset category.

    Returns
    -------
    float
        Effective annual tax depreciation rate as a decimal
        (e.g., 0.05 = 5% per year). Returns 0.0 when
        rule.deductible is False or no rate can be derived.

    Validation (raises ValueError for invalid inputs)
    ------------------------------------------------
    - annual_rate < 0
    - useful_life_years <= 0 (when annual_rate is None)
    - max_deductible_rate < 0

    Rules (applied in order)
    ------------------------
    1. deductible=False → return 0.0 immediately
    2. annual_rate is set → validate non-negative, use directly
    3. useful_life_years is set and > 0 → rate = 1 / useful_life_years
    4. max_deductible_rate is set → cap applies to base rate above
    5. Otherwise → return 0.0

    Effective rate = min(base_rate, max_deductible_rate) when cap exists.

    Examples
    --------
    Straight-line 20y: useful_life_years=20 → rate=0.05
    DB 25%: annual_rate=0.25 → rate=0.25
    Generic Market C infrastructure cap: base_rate=0.05, max_cap=0.025 → effective=0.025
    Non-deductible land: deductible=False → 0.0
    """
    if rule.deductible is False:
        return 0.0

    # Validate annual_rate
    if rule.annual_rate is not None:
        if rule.annual_rate < 0.0:
            raise ValueError(
                f"TaxDepreciationRule annual_rate must be >= 0, "
                f"got {rule.annual_rate}"
            )
        base_rate = rule.annual_rate
    elif rule.useful_life_years is not None:
        if rule.useful_life_years <= 0.0:
            raise ValueError(
                f"TaxDepreciationRule useful_life_years must be > 0 "
                f"(when annual_rate is not set), got {rule.useful_life_years}"
            )
        base_rate = 1.0 / rule.useful_life_years
    else:
        # Cannot derive a rate — e.g. deductible but no rate info
        return 0.0

    # Validate max_deductible_rate
    if rule.max_deductible_rate is not None:
        if rule.max_deductible_rate < 0.0:
            raise ValueError(
                f"TaxDepreciationRule max_deductible_rate must be >= 0, "
                f"got {rule.max_deductible_rate}"
            )
        return min(base_rate, rule.max_deductible_rate)

    return base_rate


def calculate_tax_depreciation_keur(
    asset_cost_keur: float,
    rule: TaxDepreciationRule,
) -> float:
    """Calculate annual tax depreciation amount for a given asset cost.

    Pure function: no mutation of rule.

    Parameters
    ----------
    asset_cost_keur : float
        Asset cost in thousands of EUR. Must be >= 0.
    rule : TaxDepreciationRule
        Depreciation rule for this asset category.

    Returns
    -------
    float
        Annual tax depreciation deduction in kEUR.
        Returns 0.0 for non-deductible assets.

    Raises
    ------
    ValueError
        If asset_cost_keur is negative.

    Notes
    -----
    bonus_depreciation_pct is not applied in this primitive —
    future extension point for year-1 bonus deduction logic.
    """
    if asset_cost_keur < 0.0:
        raise ValueError(
            f"asset_cost_keur must be >= 0, got {asset_cost_keur}"
        )

    if asset_cost_keur == 0.0:
        return 0.0

    rate = get_tax_depreciation_rate(rule)
    return asset_cost_keur * rate


# ── Taxable Income ────────────────────────────────────────────────────────────

def calculate_taxable_income_keur(
    ebitda_keur: float,
    deductible_interest_keur: float,
    tax_depreciation_keur: float,
    non_deductible_addbacks_keur: float = 0.0,
) -> float:
    """Calculate taxable income from EBITDA.

    Pure function: no side effects.

    Formula
    -------
    taxable_income = ebitda
                   - deductible_interest
                   - tax_depreciation
                   + non_deductible_addbacks

    Parameters
    ----------
    ebitda_keur : float
        EBITDA in thousands of EUR.
    deductible_interest_keur : float
        Deductible interest expense in kEUR.
    tax_depreciation_keur : float
        Annual tax depreciation deduction in kEUR.
    non_deductible_addbacks_keur : float, optional
        Non-deductible expenses to add back (e.g., entertainment,
        provisions). Default 0.0.

    Returns
    -------
    float
        Taxable income in kEUR. May be negative.

    Note
    ----
    This primitive does NOT apply:
    - ATAD EBITDA interest limitation (apply separately via tax engine)
    - Thin-cap interest adjustment
    - Loss carryforward utilisation
    - Deferred tax accounting
    """
    return (
        ebitda_keur
        - deductible_interest_keur
        - tax_depreciation_keur
        + non_deductible_addbacks_keur
    )