"""Phase 3B HoldCo aggregation runner with Phase 4B SHL upstream integration.

P4B: SHL interest and principal are read from waterfall periods and upstreamed
to HoldCo. SHL principal is tracked separately and excluded from taxable income.
SHL interest contributes to HoldCo gross income (taxable). Dividend is also
taxable income.

No tax template engine. No HoldCo IRR. No monthly model.
No pooled financing. No retained earnings. No cash sweep.
No SHL sculpting. No SHL capitalization.

Inputs:
  - HoldCoInputs (SPV codes, ownership %, HoldCo entity config)
  - IndependentPortfolioResult (SPV outputs with per-period waterfall results)

Output:
  - HoldCoResult with per-period HoldCoSPVContribution and sponsor distribution
"""
from __future__ import annotations

import warnings
from dataclasses import replace
from typing import Optional

from domain.portfolio.holdco import (
    HoldCoInputs,
    HoldCoResult,
    HoldCoPeriodResult,
    HoldCoSPVContribution,
    HoldCoEntity,
)
from domain.portfolio.independent import IndependentPortfolioResult
from domain.portfolio.independent.result import SPVOutput


def _safe_get_float(obj, attr, default=0.0):
    """Get a float attribute from an object, returning default if absent or not a real float.

    MagicMock (from tests) returns a Mock object for any attribute even if not set.
    Using isinstance(x, float) to distinguish real floats from Mock objects.
    """
    val = getattr(obj, attr, default)
    if isinstance(val, bool):
        return default
    if isinstance(val, (int, float)):
        return float(val)
    return default


def build_holdco_result(
    holdco_inputs: HoldCoInputs,
    portfolio_result: IndependentPortfolioResult,
) -> HoldCoResult:
    """Build HoldCoResult from HoldCoInputs and IndependentPortfolioResult.

    Aggregation is linear:
      1. For each period: read per-SPV distributions from waterfall_result.periods
      2. Apply ownership % → holdco_share per SPV
      3. Sum holdco_shares → gross_income
      4. Deduct HoldCo opex → taxable_income = max(0, gross_income - opex)
      5. Apply flat tax rate → tax = taxable_income * tax_rate_pa
      6. Compute sponsor distribution = max(0, taxable_income - tax)

    Warnings emitted for:
      - SPV in HoldCoInputs not found in portfolio_result
      - period count mismatch between SPVs

    Parameters
    ----------
    holdco_inputs : HoldCoInputs
        HoldCo configuration (SPV codes, ownership %, entity config)
    portfolio_result : IndependentPortfolioResult
        IndependentPortfolioResult from the portfolio runner

    Returns
    -------
    HoldCoResult
        Per-period aggregation with sponsor distributions (holdco_irr=None)
    """
    # ── Step 1: validate alignment ────────────────────────────────────────
    align_warnings = _validate_holdco_alignment(holdco_inputs, portfolio_result)

    # ── Step 2: collect per-period data from each SPV ─────────────────────
    # P1.2: Use max-period alignment — determine period count as the maximum
    # across all SPVs that have waterfall_result.periods. Shorter SPVs
    # contribute 0.0 after their last period (zero-padding).
    spv_map: dict[str, SPVOutput] = {spv.project_code: spv for spv in portfolio_result.spv_outputs}

    # Collect period counts from SPVs that have waterfall data
    period_counts_by_spv: dict[str, int] = {}
    for spv in portfolio_result.spv_outputs:
        if spv.waterfall_result is not None and spv.waterfall_result.periods:
            period_counts_by_spv[spv.project_code] = len(spv.waterfall_result.periods)

    if not period_counts_by_spv:
        # No waterfall data — return empty result with alignment warnings
        return HoldCoResult(
            name=holdco_inputs.name,
            periods=[],
            warnings=tuple(align_warnings),
            spv_codes=holdco_inputs.spv_codes,
        )

    num_periods = max(period_counts_by_spv.values())  # P1.2: max, not min

    # ── Step 3: build ownership lookup ─────────────────────────────────────
    ownership_map: dict[str, float] = {
        o.spv_code: o.ownership_pct for o in holdco_inputs.ownerships
    }

    entity: HoldCoEntity = holdco_inputs.entity or HoldCoEntity(name=holdco_inputs.name)
    tax_rate = entity.tax_rate_pa
    opex_keur = entity.opex.annual_opex_keur

    # P1.2: Use max-period alignment. Reference any SPV with waterfall data
    # to determine semiannual vs annual (we use the first SPV for this).
    first_valid_spv = next(
        (spv for spv in portfolio_result.spv_outputs
         if spv.waterfall_result is not None and spv.waterfall_result.periods),
        None
    )
    if first_valid_spv is not None:
        first_periods = first_valid_spv.waterfall_result.periods
        # Semiannual model: period_in_year is 1 (H1) or 2 (H2)
        periods_in_year = 2 if any(
            p.period_in_year == 2 for p in first_periods if hasattr(p, 'period_in_year')
        ) else 1
    else:
        periods_in_year = 1
    opex_per_period = opex_keur / periods_in_year

    # ── Step 4: aggregate per period ──────────────────────────────────────
    periods: list[HoldCoPeriodResult] = []
    total_spv_distributions = 0.0
    total_gross_income = 0.0
    total_opex = 0.0
    total_tax = 0.0
    total_sponsor_dist = 0.0

    for period_idx in range(num_periods):
        contributions: list[HoldCoSPVContribution] = []
        period_gross = 0.0
        period_spv_dist = 0.0

        for ownership in holdco_inputs.ownerships:
            spv_code = ownership.spv_code
            ownership_pct = ownership.ownership_pct

            spv = spv_map.get(spv_code)
            if spv is None:
                # SPV not found in portfolio result — contributed 0 this period
                contributions.append(HoldCoSPVContribution(
                    period=period_idx,
                    spv_code=spv_code,
                    ownership_pct=ownership_pct,
                    spv_distribution_keur=0.0,
                    holdco_share_keur=0.0,
                ))
                continue

            # Get per-period distribution from waterfall (with zero-padding for short SPVs)
            if spv.waterfall_result is not None and spv.waterfall_result.periods:
                periods_data = spv.waterfall_result.periods
                if period_idx < len(periods_data):
                    # P0.1: HoldCo must consume DSRF-adjusted period distributions
                    # to avoid overstating upstream cash.
                    if spv.adjusted_period_distributions_keur and period_idx < len(spv.adjusted_period_distributions_keur):
                        spv_dist = spv.adjusted_period_distributions_keur[period_idx]
                    else:
                        spv_dist = periods_data[period_idx].distribution_keur
                    # P4B: Read SHL interest/principal from waterfall period
                    wf_period = periods_data[period_idx]
                    shl_interest_raw = _safe_get_float(wf_period, 'shl_interest_keur', 0.0)
                    shl_principal_raw = _safe_get_float(wf_period, 'shl_principal_keur', 0.0)
                else:
                    # P1.2: SPV has fewer periods than max — zero-padding
                    spv_dist = 0.0
                    shl_interest_raw = 0.0
                    shl_principal_raw = 0.0
            else:
                spv_dist = 0.0
                shl_interest_raw = 0.0
                shl_principal_raw = 0.0

            # P4B: SHL upstreaming — three cash flow components
            # 1. dividend: equity distribution from waterfall
            # 2. SHL interest: taxable HoldCo income
            # 3. SHL principal: cash movement only (NOT taxable income)
            dividend_share = spv_dist * ownership_pct
            shl_interest_share = shl_interest_raw * ownership_pct
            shl_principal_share = shl_principal_raw * ownership_pct
            # holdco_income = dividend + SHL interest (principal excluded from taxable income)
            holdco_income_share = dividend_share + shl_interest_share
            period_gross += holdco_income_share
            period_spv_dist += spv_dist

            contributions.append(HoldCoSPVContribution(
                period=period_idx,
                spv_code=spv_code,
                ownership_pct=ownership_pct,
                spv_distribution_keur=spv_dist,  # raw SPV distribution
                dividend_keur=dividend_share,     # HoldCo dividend portion
                shl_interest_keur=shl_interest_share,  # 0.0 until SHL
                shl_principal_keur=shl_principal_share,  # balance-sheet only, NOT in period_gross
                holdco_share_keur=holdco_income_share,  # dividend + SHL interest
            ))

        # Apply OpEx (per-period), tax, compute sponsor distribution
        taxable = max(0.0, period_gross - opex_per_period)
        tax = taxable * tax_rate
        sponsor_dist = max(0.0, taxable - tax)

        # P1.1: period-level SHL-ready fields — dividends only (SHL = 0.0 for now)
        period_dividend = sum(c.dividend_keur for c in contributions)
        period_shl_interest = sum(c.shl_interest_keur for c in contributions)
        period_shl_principal = sum(c.shl_principal_keur for c in contributions)

        periods.append(HoldCoPeriodResult(
            period=period_idx,
            contributions=contributions,
            gross_income_keur=period_gross,
            holdco_opex_keur=opex_per_period,
            taxable_income_keur=taxable,
            tax_keur=tax,
            distribution_to_sponsor_keur=sponsor_dist,
            holdco_irr=None,
            dividend_keur=period_dividend,       # P1.1: sum of dividend components
            shl_interest_keur=period_shl_interest,  # P1.1: 0.0 until SHL
            shl_principal_keur=period_shl_principal,  # P1.1: 0.0 until SHL
        ))

        total_spv_distributions += period_spv_dist
        total_gross_income += period_gross
        total_opex += opex_per_period
        total_tax += tax
        total_sponsor_dist += sponsor_dist

    # P1.1: Compute SHL-ready totals (dividend = sum of all distributions, SHL = 0.0)
    total_dividend = sum(p.dividend_keur for p in periods)
    total_shl_interest = sum(p.shl_interest_keur for p in periods)
    total_shl_principal = sum(p.shl_principal_keur for p in periods)

    result = HoldCoResult(
        name=holdco_inputs.name,
        periods=periods,
        total_spv_distributions_keur=total_spv_distributions,
        total_gross_income_keur=total_gross_income,
        total_opex_keur=total_opex,
        total_tax_keur=total_tax,
        total_distribution_to_sponsor_keur=total_sponsor_dist,
        holdco_irr=None,
        spv_codes=holdco_inputs.spv_codes,
        warnings=tuple(align_warnings),
        # P1.1: SHL-ready totals
        total_dividend_keur=total_dividend,
        total_shl_interest_keur=total_shl_interest,
        total_shl_principal_keur=total_shl_principal,
    )

    # is_placeholder = False since aggregation actually ran
    return replace(result)  # immutable copy


def _validate_holdco_alignment(
    holdco_inputs: HoldCoInputs,
    portfolio_result: IndependentPortfolioResult,
) -> list[str]:
    """Validate alignment between HoldCoInputs and IndependentPortfolioResult.

    Emits warnings (not errors) for:
      - SPV code in HoldCoInputs not found in portfolio_result.spv_outputs
      - Period count mismatch between SPVs (uses shortest with warning)
    """
    warnings_list: list[str] = []

    # Check SPV codes
    portfolio_spv_codes = {spv.project_code for spv in portfolio_result.spv_outputs}
    for ownership in holdco_inputs.ownerships:
        if ownership.spv_code not in portfolio_spv_codes:
            warnings_list.append(
                f"HoldCoInputs references SPV '{ownership.spv_code}' "
                f"which is not in portfolio_result"
            )

    # Check period alignment — P1.2: warn about mismatch but use max-period alignment
    period_counts: dict[str, int] = {}
    for spv in portfolio_result.spv_outputs:
        if spv.waterfall_result is not None and spv.waterfall_result.periods:
            period_counts[spv.project_code] = len(spv.waterfall_result.periods)

    if period_counts:
        unique_counts = set(period_counts.values())
        if len(unique_counts) > 1:
            min_count = min(unique_counts)
            max_count = max(unique_counts)
            warnings_list.append(
                f"Period count mismatch across SPVs: "
                f"min={min_count}, max={max_count}. "
                f"Using max-period ({max_count} periods) with zero-padding for shorter SPVs."
            )

    return warnings_list


def aggregate_holdco_periods(
    holdco_inputs: HoldCoInputs,
    portfolio_result: IndependentPortfolioResult,
) -> list[HoldCoPeriodResult]:
    """Alias for build_holdco_result — returns the period list.

    Provided for API symmetry with the planned aggregation interface.
    """
    return build_holdco_result(holdco_inputs, portfolio_result).periods


def validate_holdco_alignment(
    holdco_inputs: HoldCoInputs,
    portfolio_result: IndependentPortfolioResult,
) -> list[str]:
    """Validate HoldCoInputs alignment against IndependentPortfolioResult.

    Returns list of warning strings (empty = aligned).
    """
    return _validate_holdco_alignment(holdco_inputs, portfolio_result)