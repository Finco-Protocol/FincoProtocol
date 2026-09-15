"""Phase 5H — Enforcement simulation report helpers.

Simulation compares constraint results against requested distributions
to show what WOULD be restricted under future SOFT_CAP/HARD_BLOCK modes.
No enforcement is applied; this is reporting/signal only.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from domain.portfolio.distribution_constraints.result import (
        DistributionConstraintPeriod,
        DistributionConstraintResult,
    )


@dataclass(frozen=True)
class DistributionConstraintSimulationPeriod:
    """Simulated period result showing what would be restricted.

    Extends the constraint result period with `would_restrict_keur`,
    which is the delta between requested and allowed — i.e., how much
    would be blocked under a future enforcing mode.
    """
    period: int
    entity_code: str
    cash_before_distribution_keur: float
    requested_distribution_keur: float
    allowed_distribution_keur: float
    would_restrict_keur: float  # requested - effective_allowed; 0 if allowed >= requested
    retained_cash_keur: float
    block_reasons: tuple[str, ...] = field(default_factory=tuple)
    warnings: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self):
        expected_restrict = self.requested_distribution_keur - self.allowed_distribution_keur
        if abs(self.would_restrict_keur - expected_restrict) > 1e-6:
            raise ValueError(
                f"would_restrict_keur ({self.would_restrict_keur}) must equal "
                f"requested ({self.requested_distribution_keur}) - "
                f"allowed ({self.allowed_distribution_keur}) = {expected_restrict}"
            )
        if self.would_restrict_keur < -1e-6:
            raise ValueError(
                f"would_restrict_keur ({self.would_restrict_keur}) cannot be negative; "
                f"allowed cannot exceed requested"
            )
        expected_retained = self.cash_before_distribution_keur - self.allowed_distribution_keur
        if abs(self.retained_cash_keur - expected_retained) > 1e-6:
            raise ValueError(
                f"retained_cash_keur ({self.retained_cash_keur}) must equal "
                f"cash_before ({self.cash_before_distribution_keur}) - "
                f"allowed ({self.allowed_distribution_keur}) = {expected_retained}"
            )


@dataclass(frozen=True)
class DistributionConstraintSimulationResult:
    """Per-entity simulation result.

    Aggregates simulation across all periods for one entity.
    """
    entity_code: str
    periods: tuple[DistributionConstraintSimulationPeriod, ...] = field(default_factory=tuple)
    total_requested_distribution_keur: float = 0.0
    total_allowed_distribution_keur: float = 0.0
    total_would_restrict_keur: float = 0.0
    total_retained_cash_keur: float = 0.0
    warnings: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self):
        if self.periods:
            computed_requested = sum(p.requested_distribution_keur for p in self.periods)
            computed_allowed = sum(p.allowed_distribution_keur for p in self.periods)
            computed_would_restrict = sum(p.would_restrict_keur for p in self.periods)
            computed_retained = sum(p.retained_cash_keur for p in self.periods)

            all_totals_zero = (
                self.total_requested_distribution_keur == 0.0
                and self.total_allowed_distribution_keur == 0.0
                and self.total_would_restrict_keur == 0.0
                and self.total_retained_cash_keur == 0.0
            )

            if all_totals_zero:
                # Auto-fill all when everything is default-initialized
                object.__setattr__(self, 'total_requested_distribution_keur', computed_requested)
                object.__setattr__(self, 'total_allowed_distribution_keur', computed_allowed)
                object.__setattr__(self, 'total_would_restrict_keur', computed_would_restrict)
                object.__setattr__(self, 'total_retained_cash_keur', computed_retained)
            else:
                # Validate each provided total against computed
                for got, expected, name in [
                    (self.total_requested_distribution_keur, computed_requested, "total_requested"),
                    (self.total_allowed_distribution_keur, computed_allowed, "total_allowed"),
                    (self.total_would_restrict_keur, computed_would_restrict, "total_would_restrict"),
                    (self.total_retained_cash_keur, computed_retained, "total_retained"),
                ]:
                    if abs(got - expected) > 1e-6:
                        raise ValueError(
                            f"{name} ({got}) does not match sum of periods ({expected})"
                        )


def _safe_block_reason(reason: object) -> str:
    """Convert a block reason to string safely.

    - If reason has .value (enum-like), use reason.value
    - Otherwise use str(reason)
    """
    if hasattr(reason, 'value'):
        return str(reason.value)
    return str(reason)


def simulate_distribution_enforcement(
    constraint_results: tuple["DistributionConstraintResult", ...],
    effective_allowed_by_entity_period: Optional[dict[tuple[str, int], float]] = None,
) -> tuple[DistributionConstraintSimulationResult, ...]:
    """Simulate enforcement against one or more constraint results.

    This is a **pure reporter**: it reads constraint results and produces
    simulation reports showing what WOULD be restricted under future
    enforcing modes. No input is mutated; no distributions are blocked.

    Parameters
    ----------
    constraint_results : tuple[DistributionConstraintResult, ...]
        One or more entity constraint results from
        ``evaluate_distribution_constraints()``.
    effective_allowed_by_entity_period : dict[tuple[str, int], float] | None
        Optional override for effective allowed amount per (entity_code, period).
        If a key (entity_code, period) exists, its value is used as the
        effective allowed amount for simulation. Otherwise,
        ``period.allowed_distribution_keur`` is used.
        This allows "what-if" simulation for future enforcement modes
        without modifying constraint result semantics.

    Returns
    -------
    tuple[DistributionConstraintSimulationResult, ...]
        One simulation result per input entity, in the same order.
        Empty input → empty output.
    """
    if not constraint_results:
        return ()

    effective_map = effective_allowed_by_entity_period or {}
    simulations: list[DistributionConstraintSimulationResult] = []

    for result in constraint_results:
        sim_periods: list[DistributionConstraintSimulationPeriod] = []

        for period in result.periods:
            # Use effective override if provided, otherwise use period's allowed
            effective_allowed = effective_map.get(
                (period.entity_code, period.period),
                period.allowed_distribution_keur,
            )
            would_restrict = period.requested_distribution_keur - effective_allowed

            # Convert block_reasons to strings safely
            block_reason_strs = tuple(_safe_block_reason(r) for r in period.block_reasons)

            sim_periods.append(DistributionConstraintSimulationPeriod(
                period=period.period,
                entity_code=period.entity_code,
                cash_before_distribution_keur=period.cash_before_distribution_keur,
                requested_distribution_keur=period.requested_distribution_keur,
                allowed_distribution_keur=effective_allowed,  # represents effective used
                would_restrict_keur=max(0.0, would_restrict),
                retained_cash_keur=period.cash_before_distribution_keur - effective_allowed,
                block_reasons=block_reason_strs,
                warnings=period.warnings,
            ))

        simulations.append(DistributionConstraintSimulationResult(
            entity_code=result.entity_code,
            periods=tuple(sim_periods),
            warnings=result.warnings,
        ))

    return tuple(simulations)
