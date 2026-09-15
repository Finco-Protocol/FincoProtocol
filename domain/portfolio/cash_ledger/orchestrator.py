"""Phase 5B cash ledger orchestrator — wire Phase 5A ledger to existing portfolio results.

Audit-only layer. No mutation of source results. No financial output changes.
"""
from __future__ import annotations

from typing import Any, Optional

from domain.portfolio.cash_ledger.adapters import (
    movements_from_holdco_result,
    movements_from_spv_output,
)
from domain.portfolio.cash_ledger.runner import build_portfolio_cash_ledger
from domain.portfolio.cash_ledger.result import PortfolioCashLedger


def build_cash_ledger_from_results(
    portfolio_result: Optional[Any] = None,
    holdco_result: Optional[Any] = None,
    opening_cash_by_entity: Optional[dict[str, float]] = None,
) -> PortfolioCashLedger:
    """Build a portfolio cash ledger from existing portfolio and HoldCo results.

    This is an **optional audit layer** — it reads existing results and produces
    a cash ledger representation. It does **not** modify either input result.

    Parameters
    ----------
    portfolio_result : IndependentPortfolioResult | None
        Portfolio result containing per-SPV outputs (SPVOutput objects).
        If provided, each SPV's distributions are mapped via movements_from_spv_output().
    holdco_result : HoldCoResult | None
        HoldCo result containing per-period fields (dividend, SHL interest/principal,
        opex, tax, distribution_to_sponsor).
        If provided, mapped via movements_from_holdco_result().
    opening_cash_by_entity : dict[str, float] | None
        Optional opening cash balance per entity (entity_code → opening kEUR).
        Defaults to 0.0 for all entities.

    Returns
    -------
    PortfolioCashLedger
        Portfolio-level cash ledger aggregating all entities.

    Rules
    -----
    - No mutation of portfolio_result or holdco_result
    - Empty inputs (both None) return empty PortfolioCashLedger
    - SPV distributions prefer DSRF-adjusted values over raw waterfall
    - SHL interest and principal are included as movements when present in waterfall
    """
    all_movements: list[Any] = []

    # Map SPV outputs → cash movements (defensive: handle missing/None spv_outputs)
    if portfolio_result is not None:
        spv_outputs = getattr(portfolio_result, "spv_outputs", ()) or ()
        for spv in spv_outputs:
            movements = movements_from_spv_output(spv)
            all_movements.extend(movements)

    # Map HoldCo result → cash movements
    if holdco_result is not None:
        movements = movements_from_holdco_result(holdco_result)
        all_movements.extend(movements)

    # Build portfolio ledger from combined movements
    return build_portfolio_cash_ledger(
        movements=tuple(all_movements),
        opening_cash_by_entity=opening_cash_by_entity,
    )