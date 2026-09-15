"""Phase 5D.1 distribution constraint result structures."""
from __future__ import annotations

from dataclasses import dataclass, field

from domain.portfolio.distribution_constraints.inputs import DistributionBlockReason


@dataclass(frozen=True)
class DistributionConstraintPeriod:
    """Single period result for distribution constraint evaluation.

    Fields
    ------
    period : int
        Period index
    entity_code : str
        Entity identifier (SPV or HoldCo)
    cash_before_distribution_keur : float
        Cash available before distribution and constraint application.
    requested_distribution_keur : float
        Distribution requested by the waterfall (unchanged by this layer).
    allowed_distribution_keur : float
        Distribution allowed after constraint evaluation.
        Always <= requested_distribution_keur.
    retained_cash_keur : float
        Cash retained = cash_before - allowed_distribution.
    block_reasons : tuple[DistributionBlockReason, ...]
        Zero or more reasons for constraint application.
        Empty tuple means no constraint was applied.
    warnings : tuple[str, ...]
        Warning messages (e.g., negative cash detected).
    """
    period: int
    entity_code: str
    cash_before_distribution_keur: float
    requested_distribution_keur: float
    allowed_distribution_keur: float
    retained_cash_keur: float
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
        expected_retained = self.cash_before_distribution_keur - self.allowed_distribution_keur
        if abs(self.retained_cash_keur - expected_retained) > 1e-6:
            raise ValueError(
                f"retained_cash_keur ({self.retained_cash_keur}) must equal "
                f"cash_before_distribution_keur ({self.cash_before_distribution_keur}) - "
                f"allowed_distribution_keur ({self.allowed_distribution_keur}) = {expected_retained}"
            )


@dataclass(frozen=True)
class DistributionConstraintResult:
    """Per-entity distribution constraint evaluation result.

    Aggregates constraint evaluation across all periods for one entity.
    """
    entity_code: str
    periods: tuple[DistributionConstraintPeriod, ...] = field(default_factory=tuple)
    total_requested_distribution_keur: float = 0.0
    total_allowed_distribution_keur: float = 0.0
    total_retained_cash_keur: float = 0.0
    warnings: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self):
        computed_requested = sum(p.requested_distribution_keur for p in self.periods)
        computed_allowed = sum(p.allowed_distribution_keur for p in self.periods)
        computed_retained = sum(p.retained_cash_keur for p in self.periods)

        if self.periods and self.total_requested_distribution_keur == 0.0:
            # Auto-fill when all totals default to 0.0
            object.__setattr__(self, 'total_requested_distribution_keur', computed_requested)
            object.__setattr__(self, 'total_allowed_distribution_keur', computed_allowed)
            object.__setattr__(self, 'total_retained_cash_keur', computed_retained)
        elif self.periods:
            # Validate provided totals against computed
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