"""Phase 5D.2 integration: cash ledger → distribution constraint evaluator.

Bridges Phase 5A/5B cash ledger outputs with Phase 5D.1 constraint evaluator.
Audit-only: no mutation of cash ledger or any source results.
Not wired into waterfall — produces optional constraint result objects only.
"""
from __future__ import annotations

from typing import Optional

from domain.portfolio.cash_ledger.inputs import CashMovementType
from domain.portfolio.cash_ledger.result import (
    EntityCashLedger,
    PortfolioCashLedger,
)
from domain.portfolio.distribution_constraints.inputs import (
    DistributionConstraintConfig,
)
from domain.portfolio.distribution_constraints.result import (
    DistributionConstraintResult,
)
from domain.portfolio.distribution_constraints.runner import (
    evaluate_distribution_constraints,
)

# Movements to exclude from cash-available computation
# (these represent distributions going OUT, not operational cash)
DISTRIBUTION_OUTFLOW_TYPES: frozenset[CashMovementType] = frozenset([
    CashMovementType.EQUITY_DISTRIBUTION,
    CashMovementType.SPONSOR_DISTRIBUTION,
])


def cash_available_by_period_from_entity_ledger(
    entity_ledger: EntityCashLedger,
) -> tuple[float, ...]:
    """Derive cash available before distribution per period from an entity ledger.

    Cash available = opening_cash + all movements EXCEPT equity/sponsor distributions.
    This represents the cash position the entity has before making any distributions,
    which is the correct input for constraint evaluation.

    Parameters
    ----------
    entity_ledger : EntityCashLedger
        Per-entity cash ledger (from build_entity_cash_ledger or build_portfolio_cash_ledger).

    Returns
    -------
    tuple[float, ...]
        Cash available before distribution per period (kEUR), in period order.
        Empty tuple if ledger has no periods.

    Notes
    -----
    - EQUITY_DISTRIBUTION and SPONSOR_DISTRIBUTION are excluded (they ARE the distribution)
    - All other movement types are included with their signed ledger amounts
    - opening_cash_keur is captured via the first period's opening or rolling forward
    """
    if not entity_ledger.periods:
        return ()

    result: list[float] = []
    for period in entity_ledger.periods:
        # Cash available before distributions = opening + non-distribution movements
        non_dist_sum = sum(
            m.amount_keur
            for m in period.movements
            if m.movement_type not in DISTRIBUTION_OUTFLOW_TYPES
        )
        result.append(period.opening_cash_keur + non_dist_sum)

    return tuple(result)


def requested_distributions_from_entity_ledger(
    entity_ledger: EntityCashLedger,
) -> tuple[float, ...]:
    """Extract requested distribution amounts per period from an entity ledger.

    EQUITY_DISTRIBUTION and SPONSOR_DISTRIBUTION movements in the cash ledger
    represent distributions going OUT (negative amounts in the ledger).
    This function converts them to positive "requested distribution" values.

    Parameters
    ----------
    entity_ledger : EntityCashLedger
        Per-entity cash ledger.

    Returns
    -------
    tuple[float, ...]
        Requested distribution per period (kEUR, always positive), in period order.
        0.0 for periods with no distribution movements.
    """
    if not entity_ledger.periods:
        return ()

    result: list[float] = []
    for period in entity_ledger.periods:
        period_dist = 0.0
        for m in period.movements:
            if m.movement_type in DISTRIBUTION_OUTFLOW_TYPES:
                # Distributions are stored as negative in the ledger; take absolute value
                period_dist += abs(m.amount_keur)
        result.append(period_dist)

    return tuple(result)


def evaluate_constraints_from_entity_ledger(
    entity_ledger: EntityCashLedger,
    config: Optional[DistributionConstraintConfig] = None,
) -> DistributionConstraintResult:
    """Evaluate distribution constraints for a single entity from its cash ledger.

    This is a convenience wrapper that:
      1. Extracts cash available from the ledger
      2. Extracts requested distributions from the ledger
      3. Calls evaluate_distribution_constraints()

    No mutation of entity_ledger.

    Parameters
    ----------
    entity_ledger : EntityCashLedger
        Cash ledger for one entity.
    config : DistributionConstraintConfig | None
        Constraint configuration. None means pass-through (all allowed = requested).

    Returns
    -------
    DistributionConstraintResult
        Constraint evaluation result for this entity.
    """
    cash_available = cash_available_by_period_from_entity_ledger(entity_ledger)
    requested = requested_distributions_from_entity_ledger(entity_ledger)

    return evaluate_distribution_constraints(
        entity_code=entity_ledger.entity_code,
        cash_available_by_period=cash_available,
        requested_distributions_by_period=requested,
        config=config,
    )


def evaluate_constraints_from_portfolio_ledger(
    portfolio_ledger: PortfolioCashLedger,
    config_by_entity: Optional[dict[str, DistributionConstraintConfig]] = None,
    default_config: Optional[DistributionConstraintConfig] = None,
) -> tuple[DistributionConstraintResult, ...]:
    """Evaluate distribution constraints for all entities in a portfolio ledger.

    Parameters
    ----------
    portfolio_ledger : PortfolioCashLedger
        Portfolio-level cash ledger from build_portfolio_cash_ledger.
    config_by_entity : dict[str, DistributionConstraintConfig] | None
        Optional per-entity constraint configurations.
        If an entity has an entry here, that config is used.
    default_config : DistributionConstraintConfig | None
        Fallback config for entities not in config_by_entity.
        If None, pass-through is used for those entities.

    Returns
    -------
    tuple[DistributionConstraintResult, ...]
        One result per entity, in the same order as portfolio_ledger.entities.
        Empty tuple if portfolio has no entities.

    No mutation of portfolio_ledger or any contained entity ledgers.
    """
    if not portfolio_ledger.entities:
        return ()

    results: list[DistributionConstraintResult] = []
    for entity in portfolio_ledger.entities:
        cfg = None
        if config_by_entity is not None and entity.entity_code in config_by_entity:
            cfg = config_by_entity[entity.entity_code]
        elif default_config is not None:
            cfg = default_config
        # else: cfg = None → pass-through

        result = evaluate_constraints_from_entity_ledger(entity, config=cfg)
        results.append(result)

    return tuple(results)