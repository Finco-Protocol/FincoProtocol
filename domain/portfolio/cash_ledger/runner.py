"""Phase 5A cash ledger runner — pure helper functions for ledger construction."""
from __future__ import annotations

from collections import defaultdict
from typing import Optional

from domain.portfolio.cash_ledger.inputs import CashMovement
from domain.portfolio.cash_ledger.result import (
    CashLedgerPeriod,
    EntityCashLedger,
    PortfolioCashLedger,
)


def build_entity_cash_ledger(
    entity_code: str,
    movements: tuple[CashMovement, ...],
    opening_cash_keur: float = 0.0,
) -> EntityCashLedger:
    """Build an entity cash ledger from a sequence of cash movements.

    Group movements by period, sort periods ascending, and roll forward
    opening/closing cash balances per period.

    Parameters
    ----------
    entity_code : str
        Entity identifier (e.g. SPV project code or "HOLDCO")
    movements : tuple[CashMovement, ...]
        All cash movements for this entity
    opening_cash_keur : float
        Opening cash balance for period 0 (default 0.0)

    Returns
    -------
    EntityCashLedger
        Per-period ledger with opening/closing roll-forward
    """
    # Group movements by period
    by_period: dict[int, list[CashMovement]] = defaultdict(list)
    for m in movements:
        if m.entity_code == entity_code:
            by_period[m.period].append(m)

    if not by_period:
        return EntityCashLedger(
            entity_code=entity_code,
            periods=(),
            total_movements_keur=0.0,
            ending_cash_keur=opening_cash_keur,
            warnings=(),
        )

    sorted_periods = sorted(by_period.keys())
    ledger_periods: list[CashLedgerPeriod] = []
    total_movements = 0.0
    all_warnings: list[str] = []
    current_opening = opening_cash_keur

    for period in sorted_periods:
        period_movements = tuple(by_period[period])
        movement_sum = sum(m.amount_keur for m in period_movements)
        total_movements += movement_sum
        closing = current_opening + movement_sum
        period_warnings = list[str]()
        if closing < 0:
            period_warnings.append(
                f"Negative closing cash for {entity_code} period {period}: {closing:.1f} kEUR"
            )
        ledger_periods.append(CashLedgerPeriod(
            period=period,
            entity_code=entity_code,
            opening_cash_keur=current_opening,
            movements=period_movements,
            closing_cash_keur=closing,
            retained_cash_keur=closing,  # Phase 5A: retained = closing
            warnings=tuple(period_warnings),
        ))
        all_warnings.extend(period_warnings)
        current_opening = closing

    return EntityCashLedger(
        entity_code=entity_code,
        periods=tuple(ledger_periods),
        total_movements_keur=total_movements,
        ending_cash_keur=current_opening,
        warnings=tuple(all_warnings),
    )


def build_portfolio_cash_ledger(
    movements: tuple[CashMovement, ...],
    opening_cash_by_entity: Optional[dict[str, float]] = None,
) -> PortfolioCashLedger:
    """Build a portfolio cash ledger from all cash movements.

    Groups movements by entity_code and builds an EntityCashLedger per entity.

    Parameters
    ----------
    movements : tuple[CashMovement, ...]
        All cash movements across all entities
    opening_cash_by_entity : dict[str, float] | None
        Optional opening cash per entity (default: all entities start at 0.0)

    Returns
    -------
    PortfolioCashLedger
        Portfolio-level aggregation
    """
    opening_cash_by_entity = opening_cash_by_entity or {}

    # Group movements by entity
    by_entity: dict[str, list[CashMovement]] = defaultdict(list)
    for m in movements:
        by_entity[m.entity_code].append(m)

    entities: list[EntityCashLedger] = []
    all_warnings: list[str] = []
    total_ending = 0.0

    for entity_code, entity_movements in sorted(by_entity.items()):
        opening = opening_cash_by_entity.get(entity_code, 0.0)
        entity_ledger = build_entity_cash_ledger(
            entity_code=entity_code,
            movements=tuple(entity_movements),
            opening_cash_keur=opening,
        )
        entities.append(entity_ledger)
        total_ending += entity_ledger.ending_cash_keur
        all_warnings.extend(entity_ledger.warnings)

    return PortfolioCashLedger(
        entities=tuple(entities),
        total_ending_cash_keur=total_ending,
        warnings=tuple(all_warnings),
    )


def reconcile_cash_ledger(entity_ledger: EntityCashLedger) -> tuple[str, ...]:
    """Reconcile an entity cash ledger — verify opening/closing consistency.

    Checks:
    - Period N opening == Period N-1 closing
    - Closing == opening + movement sum

    Parameters
    ----------
    entity_ledger : EntityCashLedger
        Entity ledger to reconcile

    Returns
    -------
    tuple[str, ...]
        Tuple of warning strings (empty = fully reconciled)
    """
    warnings: list[str] = []
    periods = entity_ledger.periods

    for i, period in enumerate(periods):
        # Verify closing = opening + movement sum
        movement_sum = sum(m.amount_keur for m in period.movements)
        expected_closing = period.opening_cash_keur + movement_sum
        if abs(period.closing_cash_keur - expected_closing) > 1e-6:
            warnings.append(
                f"{entity_ledger.entity_code} period {period.period}: "
                f"closing {period.closing_cash_keur:.4f} != "
                f"opening {period.opening_cash_keur:.4f} + sum {movement_sum:.4f}"
            )

        # Verify period N opening == period N-1 closing
        if i > 0:
            prev = periods[i - 1]
            if abs(period.opening_cash_keur - prev.closing_cash_keur) > 1e-6:
                warnings.append(
                    f"{entity_ledger.entity_code} period {period.period}: "
                    f"opening {period.opening_cash_keur:.4f} != "
                    f"previous closing {prev.closing_cash_keur:.4f}"
                )

    return tuple(warnings)
