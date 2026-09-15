"""finco_core.construction.allocator — Canonical per-period construction source allocator.

PR9_CANONICAL_CONSTRUCTION_ALLOCATOR: single authority for per-period Senior draw
calculation during construction. Both Stage B2 and the G2A construction schedule
must use this function so Senior draw used for IDC == Senior draw in funding schedule.

Waterfall order (per project-finance convention):
  1. Share Capital
  2. Share Premium
  3. Other Committed Equity (other_committed_equity_keur)
  4. Additional Equity (residual equity derived by G2A fixed point)
  5. SHL (shl_cash_keur)
  6. Junior (junior_keur)
  7. Senior (senior_commitment_keur — drawn last, residual)

Each layer fills in order until its available amount is exhausted or the period
need is met. Senior is the residual after all other sources.

Identity-free. No project-name dispatch.
"""
from __future__ import annotations

from dataclasses import dataclass

from finco_core._numeric import require_finite_real


@dataclass(frozen=True)
class ConstructionPeriodAllocation:
    """Canonical per-period source allocation result."""
    period_index: int
    period_uses_keur: float
    share_capital_draw_keur: float
    share_premium_draw_keur: float
    other_committed_equity_draw_keur: float
    additional_equity_draw_keur: float
    shl_draw_keur: float
    junior_draw_keur: float
    senior_draw_keur: float
    total_sources_keur: float
    residual_keur: float  # total_sources - period_uses (should be ~0)


_WATERFALL_ORDER = [
    "share_capital", "share_premium", "other_committed_equity",
    "additional_equity", "shl", "junior", "senior"
]


def _validate_allocator_inputs(
    period_uses: tuple[float, ...],
    share_capital_keur: float,
    share_premium_keur: float,
    other_committed_equity_keur: float,
    additional_equity_keur: float,
    shl_cash_keur: float,
    junior_keur: float,
    senior_commitment_keur: float,
    tolerance_keur: float,
) -> None:
    error = "PR9_CONSTRUCTION_ALLOCATOR_INVALID_NUMERIC"
    for index, uses in enumerate(period_uses):
        require_finite_real(
            f"period_uses[{index}]", uses, minimum=0.0, error_code=error
        )
    source_values = {
        "share_capital_keur": share_capital_keur,
        "share_premium_keur": share_premium_keur,
        "other_committed_equity_keur": other_committed_equity_keur,
        "additional_equity_keur": additional_equity_keur,
        "shl_cash_keur": shl_cash_keur,
        "junior_keur": junior_keur,
        "senior_commitment_keur": senior_commitment_keur,
    }
    for name, value in source_values.items():
        require_finite_real(name, value, minimum=0.0, error_code=error)
    require_finite_real(
        "tolerance_keur",
        tolerance_keur,
        minimum=0.0,
        strictly_greater=True,
        error_code=error,
    )


def _allocate_core(
    period_uses: tuple[float, ...],
    share_capital_keur: float,
    share_premium_keur: float,
    other_committed_equity_keur: float,
    additional_equity_keur: float,
    shl_cash_keur: float,
    junior_keur: float,
    senior_commitment_keur: float,
    tolerance_keur: float = 1e-9,
) -> tuple[tuple[ConstructionPeriodAllocation, ...], float]:
    """Single waterfall algorithm — shared core for strict and provisional paths.

    Returns (allocations, total_unfunded_keur). Never raises on shortfall;
    callers enforce their own invariants. Unfunded residual is diagnostic only.

    PR9_CANONICAL_LAYER_A_ALLOCATOR_SINGLE_AUTHORITY: this is the ONE implementation
    of the seven-source waterfall. Both allocate_construction_sources_per_period (strict)
    and allocate_construction_sources_provisional call this function.
    """
    _validate_allocator_inputs(
        period_uses,
        share_capital_keur,
        share_premium_keur,
        other_committed_equity_keur,
        additional_equity_keur,
        shl_cash_keur,
        junior_keur,
        senior_commitment_keur,
        tolerance_keur,
    )
    if not period_uses:
        return (), 0.0

    remaining = {
        "share_capital": share_capital_keur,
        "share_premium": share_premium_keur,
        "other_committed_equity": other_committed_equity_keur,
        "additional_equity": additional_equity_keur,
        "shl": shl_cash_keur,
        "junior": junior_keur,
        "senior": senior_commitment_keur,
    }

    allocations = []
    total_unfunded = 0.0
    for idx, uses in enumerate(period_uses):
        need = uses
        draws: dict[str, float] = {k: 0.0 for k in _WATERFALL_ORDER}
        for src in _WATERFALL_ORDER:
            if need <= tolerance_keur:
                break
            draw = min(remaining[src], need)
            draws[src] = draw
            remaining[src] -= draw
            need -= draw
        if need > tolerance_keur:
            total_unfunded += need
        total_s = sum(draws.values())
        allocations.append(ConstructionPeriodAllocation(
            period_index=idx,
            period_uses_keur=uses,
            share_capital_draw_keur=draws["share_capital"],
            share_premium_draw_keur=draws["share_premium"],
            other_committed_equity_draw_keur=draws["other_committed_equity"],
            additional_equity_draw_keur=draws["additional_equity"],
            shl_draw_keur=draws["shl"],
            junior_draw_keur=draws["junior"],
            senior_draw_keur=draws["senior"],
            total_sources_keur=total_s,
            residual_keur=total_s - uses,
        ))

    return tuple(allocations), total_unfunded


def allocate_construction_sources_per_period(
    period_uses: tuple[float, ...],
    share_capital_keur: float,
    share_premium_keur: float,
    other_committed_equity_keur: float,
    additional_equity_keur: float,
    shl_cash_keur: float,
    junior_keur: float,
    senior_commitment_keur: float,
    tolerance_keur: float = 1e-9,
) -> tuple[ConstructionPeriodAllocation, ...]:
    """Allocate construction sources per period using canonical waterfall.

    Drains each source in waterfall order: Share Capital → Share Premium →
    Other Committed Equity → Additional Equity → SHL → Junior → Senior.

    Returns per-period allocations. The senior_draw per period is the canonical
    value to feed into Stage B2 for IDC computation.

    Raises ValueError("PR9_CONSTRUCTION_FUNDING_SHORTFALL: Senior facility commitment
    breached: ...") if total sources < total uses - tolerance.
    """
    _validate_allocator_inputs(
        period_uses,
        share_capital_keur,
        share_premium_keur,
        other_committed_equity_keur,
        additional_equity_keur,
        shl_cash_keur,
        junior_keur,
        senior_commitment_keur,
        tolerance_keur,
    )
    n = len(period_uses)
    if n == 0:
        return ()

    total_uses = sum(period_uses)
    total_sources = (
        share_capital_keur + share_premium_keur + other_committed_equity_keur
        + additional_equity_keur + shl_cash_keur + junior_keur + senior_commitment_keur
    )
    if total_sources < total_uses - tolerance_keur:
        raise ValueError(
            f"PR9_CONSTRUCTION_FUNDING_SHORTFALL: Senior facility commitment breached: "
            f"total_sources={total_sources:.6f} kEUR < total_uses={total_uses:.6f} kEUR, "
            f"shortfall={total_uses - total_sources:.6f} kEUR"
        )

    allocations, _ = _allocate_core(
        period_uses,
        share_capital_keur, share_premium_keur, other_committed_equity_keur,
        additional_equity_keur, shl_cash_keur, junior_keur, senior_commitment_keur,
        tolerance_keur,
    )
    return allocations


def allocate_construction_sources_provisional(
    period_uses: tuple[float, ...],
    share_capital_keur: float,
    share_premium_keur: float,
    other_committed_equity_keur: float,
    additional_equity_keur: float,
    shl_cash_keur: float,
    junior_keur: float,
    senior_commitment_keur: float,
    tolerance_keur: float = 1e-9,
) -> tuple[tuple[ConstructionPeriodAllocation, ...], float]:
    """Provisional allocation for outer-loop intermediate iterations.

    Same canonical seven-source waterfall as the strict function, but returns
    (allocations, unfunded_uses_keur) instead of raising on shortfall.

    unfunded_uses_keur:
    - is diagnostic state only
    - does NOT increase Senior or any other source
    - does NOT earn Senior IDC
    - does NOT affect commitment-fee basis
    - must be >= 0 and finite

    Used ONLY by run_stage_b2_provisional / outer G2A intermediate iterations
    where Senior may not yet be fully sized for IDC.

    PR9_CANONICAL_LAYER_A_ALLOCATOR_SINGLE_AUTHORITY: shares _allocate_core with
    the strict path — there is ONE waterfall algorithm.
    """
    if not period_uses:
        return (), 0.0
    return _allocate_core(
        period_uses,
        share_capital_keur, share_premium_keur, other_committed_equity_keur,
        additional_equity_keur, shl_cash_keur, junior_keur, senior_commitment_keur,
        tolerance_keur,
    )
