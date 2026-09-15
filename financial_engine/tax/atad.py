"""financial_engine.tax.atad — Annual ATAD interest limitation.

Pure function. No imports from app, finco_core or any framework.

The ATAD threshold is ANNUAL (not per-period). One annual result is computed
per tax year, then deductible interest is allocated to periods chronologically.

Formula:
    deduction_capacity = max(atad_ebitda_limit × annual_EBITDA,
                             atad_de_minimis_threshold_keur_annual)
    deductible_interest = min(total_interest, deduction_capacity)
    disallowed_interest = total_interest - deductible_interest

Taxable income uses only deductible_interest as the deduction — disallowed
interest is NOT added back separately (it simply is not deducted).
"""
from __future__ import annotations

from financial_engine.tax.models import AtadAnnualResult, TaxYearCalculationBasis
from financial_engine.policies.tax import TaxPolicy


def calculate_annual_atad(
    basis: TaxYearCalculationBasis,
    policy: TaxPolicy,
) -> AtadAnnualResult:
    """Calculate the annual ATAD result for one tax year.

    Parameters
    ----------
    basis : aggregated annual inputs for this tax year
    policy : TaxPolicy (controls ATAD parameters)

    Returns
    -------
    AtadAnnualResult with annual totals and per-period chronological allocation.
    """
    total = basis.total_interest_keur
    n = len(basis.period_indices)

    if not policy.atad_enabled or total <= 0:
        return AtadAnnualResult(
            tax_year=basis.tax_year,
            total_interest_keur=total,
            deduction_capacity_keur=float("inf") if not policy.atad_enabled else 0.0,
            deductible_interest_keur=total,
            disallowed_interest_keur=0.0,
            binding_rule="disabled" if not policy.atad_enabled else "none",
            period_deductible_keur=tuple(0.0 for _ in range(n)),
            period_disallowed_keur=tuple(0.0 for _ in range(n)),
        )

    # Annual deduction capacity
    ebitda_based = basis.ebitda_keur * policy.atad_ebitda_limit
    threshold = policy.atad_de_minimis_threshold_keur_annual
    if ebitda_based >= threshold:
        capacity = ebitda_based
        binding_rule = "ebitda_30pct"
    else:
        capacity = threshold
        binding_rule = "min_threshold"

    deductible = min(total, max(0.0, capacity))
    disallowed = total - deductible

    # Allocate to periods chronologically (oldest period first consumes capacity)
    # We need per-period interest to do the allocation. However, TaxYearCalculationBasis
    # only stores the annual total. The caller must supply per-period interest via
    # calculate_atad_schedule_from_bases() which has the per-period breakdown.
    # This function returns the annual result; period allocation is done in the engine.
    return AtadAnnualResult(
        tax_year=basis.tax_year,
        total_interest_keur=total,
        deduction_capacity_keur=capacity,
        deductible_interest_keur=deductible,
        disallowed_interest_keur=disallowed,
        binding_rule=binding_rule,
        period_deductible_keur=tuple(0.0 for _ in range(n)),  # filled by engine
        period_disallowed_keur=tuple(0.0 for _ in range(n)),  # filled by engine
    )


def allocate_atad_to_periods(
    annual_result: AtadAnnualResult,
    period_interests: tuple[float, ...],
) -> AtadAnnualResult:
    """Allocate the annual ATAD deduction capacity to periods chronologically.

    Chronological allocation rule:
    - Period 0 (H1) consumes available capacity first.
    - Each subsequent period receives remaining capacity.
    - Deductible per period = min(interest_i, remaining_capacity)
    - Disallowed per period = interest_i - deductible_i

    This rule handles the H1-over-capacity case correctly:
        H1 interest = 5 000, H2 interest = 0, capacity = 3 000
        → H1: deductible = 3 000, disallowed = 2 000
        → H2: deductible = 0, disallowed = 0

    Parameters
    ----------
    annual_result : the AtadAnnualResult with annual totals
    period_interests : gross interest per period (same order as basis.period_indices)

    Returns
    -------
    Updated AtadAnnualResult with period_deductible_keur and period_disallowed_keur filled.
    """
    capacity = annual_result.deduction_capacity_keur
    if capacity == float("inf"):
        # ATAD disabled: all interest is deductible
        return AtadAnnualResult(
            tax_year=annual_result.tax_year,
            total_interest_keur=annual_result.total_interest_keur,
            deduction_capacity_keur=annual_result.deduction_capacity_keur,
            deductible_interest_keur=annual_result.deductible_interest_keur,
            disallowed_interest_keur=annual_result.disallowed_interest_keur,
            binding_rule=annual_result.binding_rule,
            period_deductible_keur=period_interests,
            period_disallowed_keur=tuple(0.0 for _ in period_interests),
        )

    remaining = capacity
    period_ded: list[float] = []
    period_dis: list[float] = []
    for interest in period_interests:
        ded = min(interest, max(0.0, remaining))
        dis = interest - ded
        period_ded.append(ded)
        period_dis.append(dis)
        remaining -= ded

    return AtadAnnualResult(
        tax_year=annual_result.tax_year,
        total_interest_keur=annual_result.total_interest_keur,
        deduction_capacity_keur=annual_result.deduction_capacity_keur,
        deductible_interest_keur=annual_result.deductible_interest_keur,
        disallowed_interest_keur=annual_result.disallowed_interest_keur,
        binding_rule=annual_result.binding_rule,
        period_deductible_keur=tuple(period_ded),
        period_disallowed_keur=tuple(period_dis),
    )
