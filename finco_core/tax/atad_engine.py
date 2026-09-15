"""ATAD adjustment v3 - annual threshold, semi-annual model.

Implements Blueprint S1-3 fix:
- ATAD threshold of 3,000 kEUR is GODIŠNJI (annual), not per period
- In semi-annual model: H1 always passes (1,500 < 3,000 threshold)
- H2 check is done at ANNUAL level (H1 + H2 together)

Key insight:
- ATAD allows the HIGHER of:
  1. 30% × EBITDA (annual)
  2. 3M EUR minimum threshold (annual)
- For semi-annual periods, H1 interest is always deductible
- H2 interest is checked against remaining annual capacity

v2 bug:
  - atad_min_interest_keur was treated as per-period (1,500 < threshold always)
  - Actually 3,000 kEUR is ANNUAL, so H2 can be blocked if H1 used capacity

v3 fix:
  - atad_adjustment_v3 tracks accumulated annual interest + EBITDA
  - H1: always passes (first half of year, no accumulated values)
  - H2: check accumulated annual total against 3M EUR / 30% EBITDA limit

Example for Generic Solar Reference:
  Annual EBITDA ≈ 12,000 kEUR → 30% × 12,000 = 3,600 kEUR
  3M EUR threshold is binding if EBITDA is low (e.g., early years)

  H1 interest = 1,500 kEUR → always deductible
  H2 interest = 1,500 kEUR → annual check: 3,000 < 3,600? No → fully deductible

  vs high interest scenario:
  H1 interest = 2,000 kEUR
  H2 interest = 2,000 kEUR → annual check: 4,000 > 3,600? Yes → excess = 400
    deductible = 3,600, addback = 400
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class ATADResult:
    """Result of ATAD adjustment for a period."""
    deductible_interest_keur: float   # Interest that can be deducted
    disallowed_addback_keur: float   # Excess interest added back to taxable profit
    annual_limit_keur: float          # The binding annual limit (30% EBITDA or 3M EUR)
    limit_type: str                   # "ebitda_30pct" or "min_threshold"

    @property
    def total_interest_keur(self) -> float:
        """Total interest (deductible + disallowed)."""
        return self.deductible_interest_keur + self.disallowed_addback_keur


def atad_limit_annual(
    annual_ebitda_keur: float,
    atad_ebitda_limit: float = 0.30,
    atad_min_interest_keur_annual: float = 3000.0,
) -> tuple[float, str]:
    """Calculate annual ATAD limit.

    Args:
        annual_ebitda_keur: Annual EBITDA
        atad_ebitda_limit: ATAD EBITDA limit (30% default)
        atad_min_interest_keur_annual: Minimum threshold (3M EUR default)

    Returns:
        (limit_keur, limit_type) — limit_type is "ebitda_30pct" or "min_threshold"
    """
    ebitda_limit = annual_ebitda_keur * atad_ebitda_limit
    if ebitda_limit >= atad_min_interest_keur_annual:
        return ebitda_limit, "ebitda_30pct"
    else:
        return atad_min_interest_keur_annual, "min_threshold"


def atad_adjustment_v3(
    interest_h2_keur: float,
    ebitda_h2_keur: float,
    period_in_year: int,
    atad_ebitda_limit: float = 0.30,
    atad_min_interest_keur_annual: float = 3000.0,
    accumulated_annual_interest: float = 0.0,
    accumulated_annual_ebitda: float = 0.0,
) -> ATADResult:
    """Calculate ATAD adjustment for H2 period with annual threshold check.

    The 3M EUR ATAD threshold is ANNUAL, not per-period.
    In a semi-annual model:
    - H1 (period_in_year=1): always deductible (first half, no accumulated check)
    - H2 (period_in_year=2): check against accumulated annual totals

    Args:
        interest_h2_keur: Interest expense in H2 (kEUR)
        ebitda_h2_keur: EBITDA in H2 (kEUR)
        period_in_year: 1 = H1, 2 = H2
        atad_ebitda_limit: ATAD EBITDA limit (30%)
        atad_min_interest_keur_annual: Minimum threshold (3,000 kEUR annual)
        accumulated_annual_interest: H1 interest (for H2 checking)
        accumulated_annual_ebitda: H1 EBITDA (for H2 checking)

    Returns:
        ATADResult with deductible/disallowed split
    """
    if period_in_year == 1:
        # H1: always fully deductible (first half of year)
        # No accumulated check needed for H1
        annual_limit, limit_type = atad_limit_annual(
            ebitda_h2_keur * 2,  # Extrapolate to full year for limit comparison
            atad_ebitda_limit,
            atad_min_interest_keur_annual,
        )
        return ATADResult(
            deductible_interest_keur=interest_h2_keur,
            disallowed_addback_keur=0.0,
            annual_limit_keur=annual_limit,
            limit_type=limit_type,
        )

    # H2: check against annual totals
    total_annual_interest = accumulated_annual_interest + interest_h2_keur
    total_annual_ebitda = accumulated_annual_ebitda + ebitda_h2_keur

    annual_limit, limit_type = atad_limit_annual(
        total_annual_ebitda,
        atad_ebitda_limit,
        atad_min_interest_keur_annual,
    )

    # H1 interest was already deducted, so H2 limit = annual_limit - H1_deducted
    h2_limit = max(0.0, annual_limit - accumulated_annual_interest)

    if interest_h2_keur <= h2_limit:
        return ATADResult(
            deductible_interest_keur=interest_h2_keur,
            disallowed_addback_keur=0.0,
            annual_limit_keur=annual_limit,
            limit_type=limit_type,
        )
    else:
        return ATADResult(
            deductible_interest_keur=h2_limit,
            disallowed_addback_keur=interest_h2_keur - h2_limit,
            annual_limit_keur=annual_limit,
            limit_type=limit_type,
        )


def atad_adjustment_simple(
    interest_keur: float,
    ebitda_keur: float,
    atad_ebitda_limit: float = 0.30,
    atad_min_interest_keur: float = 3000.0,
) -> tuple[float, float]:
    """Simple per-period ATAD (backward compatible).

    Use this for single-period calculations where annual threshold
    doesn't apply. For semi-annual model, use atad_adjustment_v3.

    Returns:
        (deductible_interest, disallowed_addback)
    """
    limit = max(ebitda_keur * atad_ebitda_limit, atad_min_interest_keur)
    if interest_keur <= limit:
        return interest_keur, 0.0
    else:
        return limit, interest_keur - limit


def atad_schedule_v3(
    interest_schedule: list[float],
    ebitda_schedule: list[float],
    atad_ebitda_limit: float = 0.30,
    atad_min_interest_keur_annual: float = 3000.0,
) -> list[ATADResult]:
    """Generate full ATAD schedule with annual threshold logic.

    Works for both semi-annual and annual periods.
    For semi-annual: periods 0,2,4,6... = H1; 1,3,5,7... = H2

    Args:
        interest_schedule: Interest per period
        ebitda_schedule: EBITDA per period
        atad_ebitda_limit: ATAD EBITDA limit
        atad_min_interest_keur_annual: Annual minimum threshold

    Returns:
        List of ATADResult for each period
    """
    results = []
    accumulated_interest = 0.0
    accumulated_ebitda = 0.0

    for period in range(len(interest_schedule)):
        interest = interest_schedule[period]
        ebitda = ebitda_schedule[period]

        # Determine if H1 or H2 based on period index
        # Semi-annual: even = H1, odd = H2
        # For general case, use period_in_year from period metadata
        # Here we assume semi-annual: even = H1, odd = H2
        period_in_year = (period % 2) + 1  # 1 for even, 2 for odd

        if period_in_year == 1:
            # H1: reset accumulated, apply simple check
            accumulated_interest = 0.0
            accumulated_ebitda = 0.0
            result = atad_adjustment_v3(
                interest_h2_keur=interest,
                ebitda_h2_keur=ebitda,
                period_in_year=1,
                atad_ebitda_limit=atad_ebitda_limit,
                atad_min_interest_keur_annual=atad_min_interest_keur_annual,
            )
        else:
            # H2: use accumulated H1 values
            result = atad_adjustment_v3(
                interest_h2_keur=interest,
                ebitda_h2_keur=ebitda,
                period_in_year=2,
                atad_ebitda_limit=atad_ebitda_limit,
                atad_min_interest_keur_annual=atad_min_interest_keur_annual,
                accumulated_annual_interest=accumulated_interest,
                accumulated_annual_ebitda=accumulated_ebitda,
            )
            # After H2, reset for next year
            accumulated_interest = 0.0
            accumulated_ebitda = 0.0

        # Update accumulated for H2 to use
        if period_in_year == 1:
            accumulated_interest = interest
            accumulated_ebitda = ebitda

        results.append(result)

    return results


__all__ = [
    "ATADResult",
    "atad_limit_annual",
    "atad_adjustment_v3",
    "atad_adjustment_simple",
    "atad_schedule_v3",
]