"""Phase 6C.2 — HoldCo / intercompany tax calculation primitives.

Pure functions — no mutation, no side effects, no waterfall wiring.

These are building blocks for a future HoldCo tax engine (Phase 6C.3+).
No active CIT calculation, no WHT engine, no deferred tax.
"""
from __future__ import annotations

import math


__all__ = [
    # Primary functions
    "calculate_withholding_tax_keur",
    "calculate_holdco_taxable_income_before_limitations",
    "exclude_shl_principal_from_taxable_income",
    "calculate_interest_limitation_keur",
    "calculate_deductible_interest_after_limitation_keur",
    # Aliases
    "split_shl_receipt_tax_components",
    "split_shl_tax_treatment",
    "calculate_interest_deductibility_limit_keur",
    "calculate_holdco_taxable_income_before_cit_keur",
]


# ── Validation helpers ────────────────────────────────────────────────────────

def _rate_in_0_1(value: float, name: str) -> None:
    if not (0.0 <= value <= 1.0):
        raise ValueError(f"{name} must be between 0 and 1, got {value}")


def _non_negative(value: float, name: str) -> None:
    if value < 0.0:
        raise ValueError(f"{name} must be non-negative, got {value}")


def _no_nan_inf(value: float, name: str) -> None:
    if math.isnan(value) or math.isinf(value):
        raise ValueError(f"{name} must not be NaN or Inf, got {value}")


# ── WHT calculation ───────────────────────────────────────────────────────────

def calculate_withholding_tax_keur(
    gross_amount_keur: float,
    withholding_rate: float,
) -> float:
    """Calculate WHT amount on a gross intercompany payment.

    Pure function — no mutation, no side effects.

    Parameters
    ----------
    gross_amount_keur : float
        Gross payment amount before WHT in kEUR. Must be >= 0, no NaN/inf.
    withholding_rate : float
        WHT rate as a decimal (0 = no WHT, 0.12 = 12%). Must be in [0, 1].

    Returns
    -------
    float
        WHT amount in kEUR = gross_amount_keur * withholding_rate.

    Raises
    ------
    ValueError
        If gross_amount_keur < 0 or withholding_rate outside [0, 1].

    Examples
    --------
    >>> calculate_withholding_tax_keur(1000.0, 0.12)
    120.0
    >>> calculate_withholding_tax_keur(1000.0, 0.0)
    0.0
    """
    _non_negative(gross_amount_keur, "gross_amount_keur")
    _no_nan_inf(gross_amount_keur, "gross_amount_keur")
    _rate_in_0_1(withholding_rate, "withholding_rate")
    _no_nan_inf(withholding_rate, "withholding_rate")
    return gross_amount_keur * withholding_rate


# ── HoldCo taxable income before limitations ──────────────────────────────────

def calculate_holdco_taxable_income_before_limitations(
    dividend_income_keur: float,
    shl_interest_income_keur: float,
    holdco_opex_keur: float,
) -> float:
    """Calculate HoldCo taxable income before thin-cap / EBITDA limits.

    Pure function — no mutation, no side effects.

    SHL principal is NOT included (excluded via separate function).

    Formula:
        taxable_income = dividend_income + shl_interest_income - holdco_opex

    Parameters
    ----------
    dividend_income_keur : float
        Taxable dividend income in kEUR. Must be >= 0.
    shl_interest_income_keur : float
        Taxable SHL interest income in kEUR. Must be >= 0.
    holdco_opex_keur : float
        Deductible HoldCo operating expenses in kEUR. Must be >= 0.

    Returns
    -------
    float
        Taxable income before interest limitation in kEUR.
        Can be negative (loss position carried forward per template rules).

    Raises
    ------
    ValueError
        If any input is NaN or Inf, or if any input is negative.

    Examples
    --------
    >>> calculate_holdco_taxable_income_before_limitations(1000.0, 200.0, 50.0)
    1150.0
    """
    for name, val in [
        ("dividend_income_keur", dividend_income_keur),
        ("shl_interest_income_keur", shl_interest_income_keur),
        ("holdco_opex_keur", holdco_opex_keur),
    ]:
        _non_negative(val, name)
        _no_nan_inf(val, name)
    return dividend_income_keur + shl_interest_income_keur - holdco_opex_keur


# ── SHL principal exclusion ───────────────────────────────────────────────────

def exclude_shl_principal_from_taxable_income(
    shl_principal_keur: float,
) -> float:
    """Exclude SHL principal from HoldCo taxable income.

    Pure function — no mutation, no side effects.

    SHL principal repayments are recovery of investment, NOT income.
    They have zero taxable income impact (neither taxable nor deductible).

    Parameters
    ----------
    shl_principal_keur : float
        SHL principal repayment received in kEUR. Must be >= 0.

    Returns
    -------
    float
        0.0 — SHL principal has no taxable income impact.

    Raises
    ------
    ValueError
        If shl_principal_keur < 0 (principal cannot be negative).

    Examples
    --------
    >>> exclude_shl_principal_from_taxable_income(500.0)
    0.0
    """
    _non_negative(shl_principal_keur, "shl_principal_keur")
    _no_nan_inf(shl_principal_keur, "shl_principal_keur")
    return 0.0


# ── Interest deductibility limitation ───────────────────────────────────────

def calculate_interest_limitation_keur(
    interest_amount_keur: float,
    ebitda_keur: float,
    interest_limitation_pct_ebitda: float | None,
) -> float:
    """Calculate the non-deductible interest amount per ATAD EBITDA rule.

    Pure function — no mutation, no side effects.

    ATAD rule (EU Anti-Tax Avoidance Directive):
    Net interest expense is limited to interest_limitation_pct_ebitda
    of EBITDA. Any excess is non-deductible but carried forward.
    If EBITDA <= 0, the limit is 0 — all interest is non-deductible.

    Parameters
    ----------
    interest_amount_keur : float
        Total interest expense in kEUR. Must be >= 0.
    ebitda_keur : float
        EBITDA in kEUR. Used as the limitation base.
        May be negative (ATAD allows full non-deductibility when EBITDA <= 0).
        Must not be NaN or Inf.
    interest_limitation_pct_ebitda : float | None
        Fraction of EBITDA to which interest is limited (e.g., 0.30 for 30%).
        None = no EBITDA limitation applies (unlimited deductibility).
        Must be between 0 and 1 if provided.

    Returns
    -------
    float
        Non-deductible / limited interest in kEUR.
        If interest_limitation_pct_ebitda is None → returns 0 (no limit).
        If ebitda_keur <= 0 → returns interest_amount_keur (all non-deductible).
        Otherwise: max(0, interest_amount - ebitda * interest_limitation_pct_ebitda).

    Raises
    ------
    ValueError
        If interest_amount_keur < 0.
        If ebitda_keur is NaN or Inf.
        If interest_limitation_pct_ebitda is not None and outside [0, 1].

    Examples
    --------
    >>> calculate_interest_limitation_keur(200.0, 1000.0, 0.30)
    0.0  # 200 < 300 limit
    >>> calculate_interest_limitation_keur(400.0, 1000.0, 0.30)
    100.0  # 400 - 300 = 100 excess
    >>> calculate_interest_limitation_keur(200.0, 1000.0, None)
    0.0  # no limit
    >>> calculate_interest_limitation_keur(200.0, -100.0, 0.30)
    200.0  # EBITDA <= 0, all interest is limited
    """
    _non_negative(interest_amount_keur, "interest_amount_keur")
    _no_nan_inf(interest_amount_keur, "interest_amount_keur")
    _no_nan_inf(ebitda_keur, "ebitda_keur")

    if interest_limitation_pct_ebitda is None:
        return 0.0

    if not (0.0 <= interest_limitation_pct_ebitda <= 1.0):
        raise ValueError(
            f"interest_limitation_pct_ebitda must be between 0 and 1 or None, "
            f"got {interest_limitation_pct_ebitda}"
        )

    if ebitda_keur <= 0:
        return interest_amount_keur

    limit = max(0.0, ebitda_keur * interest_limitation_pct_ebitda)
    excess = interest_amount_keur - limit
    return max(0.0, excess)


def calculate_deductible_interest_after_limitation_keur(
    interest_amount_keur: float,
    ebitda_keur: float,
    interest_limitation_pct_ebitda: float | None,
) -> float:
    """Calculate deductible interest after ATAD EBITDA limitation is applied.

    Pure function — no mutation, no side effects.

    Parameters
    ----------
    interest_amount_keur : float
        Total interest expense in kEUR.
    ebitda_keur : float
        EBITDA in kEUR. May be negative.
    interest_limitation_pct_ebitda : float | None
        ATAD EBITDA limitation fraction. None = no limit.

    Returns
    -------
    float
        Deductible interest in kEUR = interest_amount - limited_excess.
        Always >= 0.

    Examples
    --------
    >>> calculate_deductible_interest_after_limitation_keur(200.0, 1000.0, 0.30)
    200.0  # all within 300 limit
    >>> calculate_deductible_interest_after_limitation_keur(400.0, 1000.0, 0.30)
    300.0  # 300 deductible, 100 excess
    >>> calculate_deductible_interest_after_limitation_keur(200.0, -100.0, 0.30)
    0.0  # EBITDA <= 0, all interest is limited
    """
    _non_negative(interest_amount_keur, "interest_amount_keur")
    _no_nan_inf(interest_amount_keur, "interest_amount_keur")
    _no_nan_inf(ebitda_keur, "ebitda_keur")

    if interest_limitation_pct_ebitda is None:
        return interest_amount_keur

    excess = calculate_interest_limitation_keur(
        interest_amount_keur, ebitda_keur, interest_limitation_pct_ebitda
    )
    return max(0.0, interest_amount_keur - excess)


# ── Aliases ──────────────────────────────────────────────────────────────────

def split_shl_receipt_tax_components(
    shl_interest_income_keur: float,
    shl_principal_received_keur: float,
) -> tuple[float, float]:
    """Split SHL receipts into taxable interest and non-taxable principal amount.

    Pure function — no mutation, no side effects.

    SHL interest income is taxable. SHL principal repayments are recovery of
    investment — they have zero taxable income impact (not taxable, not deductible)
    but the amount must be tracked for audit purposes.

    Parameters
    ----------
    shl_interest_income_keur : float
        Taxable SHL interest income in kEUR. Must be >= 0.
    shl_principal_received_keur : float
        SHL principal repayment received in kEUR. Must be >= 0.

    Returns
    -------
    tuple[float, float]
        (taxable_interest_income_keur, non_taxable_principal_keur)
        The principal amount is returned for audit tracking — it does NOT
        enter the taxable income calculation.

    Examples
    --------
    >>> split_shl_receipt_tax_components(200.0, 500.0)
    (200.0, 500.0)
    """
    _non_negative(shl_interest_income_keur, "shl_interest_income_keur")
    _non_negative(shl_principal_received_keur, "shl_principal_received_keur")
    _no_nan_inf(shl_interest_income_keur, "shl_interest_income_keur")
    _no_nan_inf(shl_principal_received_keur, "shl_principal_received_keur")
    return (shl_interest_income_keur, shl_principal_received_keur)


def split_shl_tax_treatment(
    shl_interest_income_keur: float,
    shl_principal_received_keur: float,
) -> tuple[float, float]:
    """Alias for split_shl_receipt_tax_components.

    .. deprecated::
        Use :func:`split_shl_receipt_tax_components` instead.
        This alias is kept for backward compatibility.

    The second return value is the non-taxable principal **amount** (not
    taxable income impact). It must NOT be used as a taxable income modifier.

    Examples
    --------
    >>> split_shl_tax_treatment(200.0, 500.0)
    (200.0, 500.0)
    """
    return split_shl_receipt_tax_components(
        shl_interest_income_keur, shl_principal_received_keur
    )


def calculate_interest_deductibility_limit_keur(
    interest_expense_keur: float,
    ebitda_keur: float,
    config,  # InterestDeductibilityConfig
) -> tuple[float, float]:
    """Calculate deductible and non-deductible interest using a config object.

    Pure function — no mutation, no side effects.

    Parameters
    ----------
    interest_expense_keur : float
        Total interest expense in kEUR.
    ebitda_keur : float
        EBITDA in kEUR. May be negative.
    config
        InterestDeductibilityConfig with thin_cap_ratio and
        interest_limitation_pct_ebitda fields.

    Returns
    -------
    tuple[float, float]
        (deductible_interest_keur, limited_interest_keur)

    Examples
    --------
    >>> from finco_core.tax.holdco_inputs import InterestDeductibilityConfig
    >>> cfg = InterestDeductibilityConfig(interest_limitation_pct_ebitda=0.30)
    >>> calculate_interest_deductibility_limit_keur(400.0, 1000.0, cfg)
    (300.0, 100.0)
    """
    pct = getattr(config, "interest_limitation_pct_ebitda", None)
    deductible = calculate_deductible_interest_after_limitation_keur(
        interest_expense_keur, ebitda_keur, pct
    )
    limited = max(0.0, interest_expense_keur - deductible)
    return (deductible, limited)


def calculate_holdco_taxable_income_before_cit_keur(
    dividend_income_keur: float,
    shl_interest_income_keur: float,
    holdco_opex_keur: float,
) -> float:
    """Alias for calculate_holdco_taxable_income_before_limitations.

    Calculates HoldCo taxable income before CIT and interest limitations.

    Pure function — no mutation, no side effects.

    Examples
    --------
    >>> calculate_holdco_taxable_income_before_cit_keur(1000.0, 200.0, 50.0)
    1150.0
    """
    return calculate_holdco_taxable_income_before_limitations(
        dividend_income_keur,
        shl_interest_income_keur,
        holdco_opex_keur,
    )