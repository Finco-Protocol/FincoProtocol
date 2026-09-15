"""Phase 5D.3 SPV retained cash overlay — audit-only result objects.

No mutation of SPVOutput. No distribution_keur changes. No enforcement.
This phase maps DistributionConstraintResult → SPVRetainedCashOverlay for
audit/inspection purposes only.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from domain.portfolio.distribution_constraints.inputs import (
    DistributionBlockReason,
    DistributionConstraintConfig,
)
from domain.portfolio.distribution_constraints.result import DistributionConstraintResult
from domain.portfolio.distribution_constraints.integration import (
    evaluate_constraints_from_portfolio_ledger,
)
from domain.portfolio.cash_ledger.result import PortfolioCashLedger


@dataclass(frozen=True)
class SPVRetainedCashPeriod:
    """Single period SPV retained cash result.

    Shows what cash would be retained if constraints were applied.
    Does not modify the actual waterfall output.

    Fields
    ------
    period : int
        Period index
    entity_code : str
        SPV identifier
    requested_distribution_keur : float
        Distribution requested by waterfall (unchanged)
    allowed_distribution_keur : float
        Distribution allowed after constraint evaluation
    retained_cash_keur : float
        Cash retained = cash_before - allowed
    cash_before_distribution_keur : float
        Cash position before distributions and constraints
    block_reasons : tuple[DistributionBlockReason, ...]
        Zero or more constraint reasons
    warnings : tuple[str, ...]
        Warning messages
    """
    period: int
    entity_code: str
    requested_distribution_keur: float
    allowed_distribution_keur: float
    retained_cash_keur: float
    cash_before_distribution_keur: float
    block_reasons: tuple[DistributionBlockReason, ...] = ()
    warnings: tuple[str, ...] = ()

    def __post_init__(self):
        if self.period < 0:
            raise ValueError(f"period must be >= 0, got {self.period}")
        if not self.entity_code or not self.entity_code.strip():
            raise ValueError(
                f"entity_code must be non-empty and non-whitespace, "
                f"got {self.entity_code!r}"
            )
        if self.allowed_distribution_keur > self.requested_distribution_keur:
            raise ValueError(
                f"allowed_distribution_keur ({self.allowed_distribution_keur}) cannot exceed "
                f"requested_distribution_keur ({self.requested_distribution_keur})"
            )
        expected_retained = (
            self.cash_before_distribution_keur - self.allowed_distribution_keur
        )
        if abs(self.retained_cash_keur - expected_retained) > 1e-6:
            raise ValueError(
                f"retained_cash_keur ({self.retained_cash_keur}) must equal "
                f"cash_before_distribution_keur ({self.cash_before_distribution_keur}) - "
                f"allowed_distribution_keur ({self.allowed_distribution_keur}) = {expected_retained}"
            )


@dataclass(frozen=True)
class SPVRetainedCashOverlay:
    """Per-SPV retained cash overlay across all periods.

    This is an audit-only result: it shows what distributions WOULD be
    constrained to, and what cash WOULD be retained, without changing
    any SPVOutput or waterfall field.
    """
    entity_code: str
    periods: tuple[SPVRetainedCashPeriod, ...] = field(default_factory=tuple)
    total_requested_distribution_keur: float = 0.0
    total_allowed_distribution_keur: float = 0.0
    total_retained_cash_keur: float = 0.0
    warnings: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self):
        computed_requested = sum(p.requested_distribution_keur for p in self.periods)
        computed_allowed = sum(p.allowed_distribution_keur for p in self.periods)
        computed_retained = sum(p.retained_cash_keur for p in self.periods)

        if self.periods and self.total_requested_distribution_keur == 0.0:
            object.__setattr__(self, 'total_requested_distribution_keur', computed_requested)
            object.__setattr__(self, 'total_allowed_distribution_keur', computed_allowed)
            object.__setattr__(self, 'total_retained_cash_keur', computed_retained)
        elif self.periods:
            if abs(self.total_requested_distribution_keur - computed_requested) > 1e-6:
                raise ValueError(
                    f"total_requested_distribution_keur ({self.total_requested_distribution_keur}) "
                    f"does not match sum of periods ({computed_requested})"
                )
            if abs(self.total_allowed_distribution_keur - computed_allowed) > 1e-6:
                raise ValueError(
                    f"total_allowed_distribution_keur ({self.total_allowed_distribution_keur}) "
                    f"does not match sum of periods ({computed_allowed})"
                )
            if abs(self.total_retained_cash_keur - computed_retained) > 1e-6:
                raise ValueError(
                    f"total_retained_cash_keur ({self.total_retained_cash_keur}) "
                    f"does not match sum of periods ({computed_retained})"
                )


def build_spv_retained_cash_overlay(
    constraint_result: DistributionConstraintResult,
) -> SPVRetainedCashOverlay:
    """Map a DistributionConstraintResult → SPVRetainedCashOverlay.

    No mutation of constraint_result.
    """
    overlay_periods: list[SPVRetainedCashPeriod] = []
    for cp in constraint_result.periods:
        overlay_periods.append(SPVRetainedCashPeriod(
            period=cp.period,
            entity_code=cp.entity_code,
            requested_distribution_keur=cp.requested_distribution_keur,
            allowed_distribution_keur=cp.allowed_distribution_keur,
            retained_cash_keur=cp.retained_cash_keur,
            cash_before_distribution_keur=cp.cash_before_distribution_keur,
            block_reasons=cp.block_reasons,
            warnings=cp.warnings,
        ))

    return SPVRetainedCashOverlay(
        entity_code=constraint_result.entity_code,
        periods=tuple(overlay_periods),
        total_requested_distribution_keur=constraint_result.total_requested_distribution_keur,
        total_allowed_distribution_keur=constraint_result.total_allowed_distribution_keur,
        total_retained_cash_keur=constraint_result.total_retained_cash_keur,
        warnings=constraint_result.warnings,
    )


def build_spv_retained_cash_overlays_from_portfolio_ledger(
    portfolio_ledger: PortfolioCashLedger,
    config_by_entity: dict[str, DistributionConstraintConfig] | None = None,
    default_config: DistributionConstraintConfig | None = None,
) -> tuple[SPVRetainedCashOverlay, ...]:
    """Build SPV retained cash overlays for all entities in a portfolio ledger.

    Parameters
    ----------
    portfolio_ledger : PortfolioCashLedger
        Portfolio cash ledger (from build_portfolio_cash_ledger).
    config_by_entity : dict[str, DistributionConstraintConfig] | None
        Per-entity constraint configurations.
    default_config : DistributionConstraintConfig | None
        Fallback config for unconfigured entities.

    Returns
    -------
    tuple[SPVRetainedCashOverlay, ...]
        One overlay per entity, in portfolio entity order.
        No filtering — all entities are included.

    No mutation of portfolio_ledger or any source objects.
    """
    constraint_results = evaluate_constraints_from_portfolio_ledger(
        portfolio_ledger=portfolio_ledger,
        config_by_entity=config_by_entity,
        default_config=default_config,
    )

    return tuple(
        build_spv_retained_cash_overlay(result)
        for result in constraint_results
    )