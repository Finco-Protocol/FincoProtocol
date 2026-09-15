"""Phase 4C SHL end-to-end integration layer.

Bridges the SHL engine output to the portfolio/waterfall flow without
direct coupling between SHL engine internals and waterfall engine internals.

No sculpting. No capitalization. No tax logic.

Sequencing (Phase 4C):
  1. run_independent_portfolio(inputs) → IndependentPortfolioResult
  2. run_shl_portfolio(shl_inputs)     → SHLPortfolioResult
  3. group_shl_facilities_by_borrower(shl_portfolio_result)
                                        → dict[borrower_code, tuple[SHLFacilityResult, ...]]
  4. enrich_portfolio_result_with_shl(portfolio_result, shl_by_borrower)
  5. build_holdco_result(holdco_inputs, portfolio_result)
"""
from __future__ import annotations

from domain.portfolio.shl.result import (
    SHLFacilityResult,
    SHLPortfolioResult,
)


def build_shl_period_lookup(
    shl_result: SHLFacilityResult,
) -> dict[int, tuple[float, float]]:
    """Build a period-index → (interest_keur, principal_keur) lookup from an SHL facility result.

    This is the integration bridge: SHL engine output is mapped to a simple
    dict that can be used to annotate waterfall periods without coupling
    to SHL engine internals.

    Parameters
    ----------
    shl_result : SHLFacilityResult
        Result from run_shl_facility()

    Returns
    -------
    dict[int, tuple[float, float]]
        Mapping from period_index → (interest_paid_keur, principal_paid_keur).
        Returns empty dict if shl_result has no periods.

    Example
    -------
    >>> lookup = build_shl_period_lookup(facility_result)
    >>> lookup[0]
    (50.0, 200.0)
    >>> lookup[1]
    (45.0, 200.0)
    """
    if not shl_result or not shl_result.periods:
        return {}

    return {
        p.period_index: (p.interest_paid_keur, p.principal_paid_keur)
        for p in shl_result.periods
    }


def group_shl_facilities_by_borrower(
    shl_portfolio_result: SHLPortfolioResult,
) -> dict[str, tuple[SHLFacilityResult, ...]]:
    """Group SHL facility results by borrower_entity_code.

    Parameters
    ----------
    shl_portfolio_result : SHLPortfolioResult
        Result from run_shl_portfolio()

    Returns
    -------
    dict[str, tuple[SHLFacilityResult, ...]]
        Mapping from borrower_entity_code → tuple of SHLFacilityResult.
        Empty dict if shl_portfolio_result has no facilities.

    Example
    -------
    >>> grouped = group_shl_facilities_by_borrower(shl_portfolio)
    >>> solar_facilities = grouped["SOLAR-1"]
    >>> len(solar_facilities)
    2
    """
    if not shl_portfolio_result or not shl_portfolio_result.facilities:
        return {}

    by_borrower: dict[str, list[SHLFacilityResult]] = {}
    for fac_result in shl_portfolio_result.facilities:
        borrower = fac_result.facility.borrower_entity_code
        if borrower not in by_borrower:
            by_borrower[borrower] = []
        by_borrower[borrower].append(fac_result)

    return {k: tuple(v) for k, v in by_borrower.items()}


def _safe_float(value, default=0.0):
    """Cast value to float, rejecting bool and non-numeric types.

    MagicMock returns a Mock object for any attribute. Using isinstance
    guards to ensure we only treat real numbers as SHL values.
    """
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return float(value)
    return default


def inject_shl_into_waterfall_periods(
    wf_periods: list,
    shl_lookup: dict[int, tuple[float, float]],
) -> None:
    """Inject SHL interest/principal into waterfall period objects in-place.

    This is the actual integration hook: SHL cash flows are written directly
    onto waterfall period objects so HoldCo (via _safe_get_float) can read them.

    SHL principal is NOT deducted from distribution_keur in this phase
    (deferred to future retained-earnings / cash-account phase).

    Collision policy for each period:
      - existing > 0 and injected > 0  → raise ValueError (use one path only)
      - injected > 0 and existing == 0 → set injected value
      - injected == 0 and existing > 0 → preserve existing value (no overwrite)
      - both zero / missing            → set to 0.0

    Parameters
    ----------
    wf_periods : list
        List of waterfall period objects (e.g. WaterfallPeriod instances).
        Modified in-place.
    shl_lookup : dict[int, tuple[float, float]]
        Period-index → (interest_keur, principal_keur) lookup.
        Periods not in lookup receive shl_interest_keur=0.0, shl_principal_keur=0.0.

    Raises
    ------
    ValueError
        If a period already has non-zero shl_interest_keur or shl_principal_keur
        and the lookup would inject a non-zero value for the same field.
    """
    for p in wf_periods:
        idx = getattr(p, "period_index", None)
        if idx is not None and idx in shl_lookup:
            interest, principal = shl_lookup[idx]
        else:
            interest, principal = 0.0, 0.0

        # Guard against collision: SPV-internal SHL already set non-zero value
        existing_interest = _safe_float(getattr(p, "shl_interest_keur", None))
        existing_principal = _safe_float(getattr(p, "shl_principal_keur", None))
        if interest > 0 and existing_interest > 0:
            raise ValueError(
                f"SHL collision on period {idx}: "
                f"SPV has shl_interest_keur={existing_interest}, "
                f"portfolio SHL injection would overwrite with {interest}. "
                f"Use either SPV-internal SHL or portfolio-level SHL, not both."
            )
        if principal > 0 and existing_principal > 0:
            raise ValueError(
                f"SHL collision on period {idx}: "
                f"SPV has shl_principal_keur={existing_principal}, "
                f"portfolio SHL injection would overwrite with {principal}. "
                f"Use either SPV-internal SHL or portfolio-level SHL, not both."
            )

        # Set only when injecting non-zero; preserve existing non-zero values
        if interest > 0:
            p.shl_interest_keur = float(interest)
        elif interest == 0 and existing_interest == 0:
            p.shl_interest_keur = 0.0
        # else: existing > 0, injected == 0 → preserve existing (do nothing)

        if principal > 0:
            p.shl_principal_keur = float(principal)
        elif principal == 0 and existing_principal == 0:
            p.shl_principal_keur = 0.0
        # else: existing > 0, injected == 0 → preserve existing (do nothing)


def enrich_portfolio_result_with_shl(
    portfolio_result,
    shl_by_borrower_code: dict[str, tuple[SHLFacilityResult, ...]],
) -> None:
    """Enrich SPV waterfall periods in an IndependentPortfolioResult with SHL flows.

    This is a Phase 4C in-place enrichment hook. Future immutable refactor
    may replace this.

    Sequencing:
      1. Run portfolio: result = run_independent_portfolio(inputs)
      2. Run SHL portfolio: shl_portfolio = run_shl_portfolio(shl_inputs)
      3. Group: shl_by_borrower = group_shl_facilities_by_borrower(shl_portfolio)
      4. Enrich: enrich_portfolio_result_with_shl(result, shl_by_borrower)
      5. Aggregate HoldCo: holdco_result = build_holdco_result(...)

    Behaviour:
      - Finds SPV by spv.project_code (== borrower_entity_code)
      - Gets tuple of SHLFacilityResult for that SPV
      - Builds combined period lookup (summing overlapping periods)
      - Injects shl_interest_keur and shl_principal_keur into waterfall periods
      - Periods without SHL receive 0.0
      - distribution_keur is UNCHANGED
      - adjusted_period_distributions_keur is UNCHANGED
      - function mutates waterfall periods in-place and returns None

    Parameters
    ----------
    portfolio_result : IndependentPortfolioResult
        Result from run_independent_portfolio(). Mutated in-place.
    shl_by_borrower_code : dict[str, tuple[SHLFacilityResult, ...]]
        Mapping from borrower_entity_code → tuple of SHLFacilityResult.
        Multiple facilities per borrower are summed per period.
    """
    for spv in portfolio_result.spv_outputs:
        wf = spv.waterfall_result
        if wf is None or not hasattr(wf, "periods") or not wf.periods:
            continue

        entity_code = spv.project_code
        facilities = shl_by_borrower_code.get(entity_code)
        if not facilities:
            continue

        # Build combined per-period lookup from all facilities for this borrower
        shl_lookup: dict[int, tuple[float, float]] = {}
        for fac_result in facilities:
            fac_lookup = build_shl_period_lookup(fac_result)
            for pidx, (interest, principal) in fac_lookup.items():
                if pidx in shl_lookup:
                    existing = shl_lookup[pidx]
                    shl_lookup[pidx] = (existing[0] + interest, existing[1] + principal)
                else:
                    shl_lookup[pidx] = (interest, principal)

        inject_shl_into_waterfall_periods(list(wf.periods), shl_lookup)


__all__ = [
    "build_shl_period_lookup",
    "group_shl_facilities_by_borrower",
    "inject_shl_into_waterfall_periods",
    "enrich_portfolio_result_with_shl",
]
