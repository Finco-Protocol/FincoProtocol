"""Phase 5D.1 distribution constraint evaluation runner."""
from __future__ import annotations

from typing import Optional

from domain.portfolio.distribution_constraints.inputs import (
    DistributionBlockReason,
    DistributionConstraintConfig,
    DistributionEnforcementMode,
)
from domain.portfolio.distribution_constraints.result import (
    DistributionConstraintPeriod,
    DistributionConstraintResult,
)


def evaluate_distribution_constraints(
    entity_code: str,
    cash_available_by_period: tuple[float, ...],
    requested_distributions_by_period: tuple[float, ...],
    config: Optional[DistributionConstraintConfig] = None,
) -> DistributionConstraintResult:
    """Evaluate distribution constraints for one entity across periods.

    This is a **pure helper**: it returns a new result object and does not
    mutate any input. It is not wired into the waterfall engine.

    Phase 5G — schema only, no active enforcement:
      - config is None or enabled=False → pass through unchanged
      - enforcement_mode=OFF → pass through unchanged (no reasons required)
      - WARNING_ONLY → compute reasons/warnings, allowed=requested
      - SOFT_CAP/HARD_BLOCK → same + "not active" warning

    Parameters
    ----------
    entity_code : str
        SPV or HoldCo entity code.
    cash_available_by_period : tuple[float, ...]
        Cash available per period (kEUR).
    requested_distributions_by_period : tuple[float, ...]
        Requested distribution per period (kEUR).
    config : DistributionConstraintConfig | None
        Constraint configuration. None or enabled=False → pass through.

    Returns
    -------
    DistributionConstraintResult
        Per-period constraint evaluation results with allowed amounts,
        retained cash, and block reasons.
    """
    # Pass through: None config, disabled, or OFF enforcement mode
    if config is None or not config.enabled:
        return _pass_through(
            entity_code, cash_available_by_period, requested_distributions_by_period
        )

    if config.enforcement_mode == DistributionEnforcementMode.OFF:
        return _pass_through(
            entity_code, cash_available_by_period, requested_distributions_by_period
        )

    lockup_set = set(config.manual_lockup_periods)
    min_reserve = config.minimum_cash_reserve_keur
    allow_neg = config.allow_negative_cash
    enforce_mode = config.enforcement_mode

    periods: list[DistributionConstraintPeriod] = []
    all_warnings: list[str] = []

    # SOFT_CAP and HARD_BLOCK are not active yet — emit warning
    if enforce_mode in (DistributionEnforcementMode.SOFT_CAP,
                         DistributionEnforcementMode.HARD_BLOCK):
        all_warnings.append(
            f"Enforcement mode {enforce_mode.value} not active in Phase 5G"
        )

    n = max(len(cash_available_by_period), len(requested_distributions_by_period))

    for i in range(n):
        cash = cash_available_by_period[i] if i < len(cash_available_by_period) else 0.0
        requested = (
            requested_distributions_by_period[i]
            if i < len(requested_distributions_by_period)
            else 0.0
        )

        reasons: list[DistributionBlockReason] = []
        warnings: list[str] = []
        allowed = requested  # Phase 5G: always pass through; compute reasons only

        # Compute potential constraint reasons for visibility
        # These are always computed so WARNING_ONLY/SOFT_CAP/HARD_BLOCK
        # show block reasons even though allowed is not reduced.
        potential_allowed = requested

        # 1. Manual lockup — compute reason
        if i in lockup_set:
            potential_allowed = 0.0
            reasons.append(DistributionBlockReason.MANUAL_LOCKUP)

        # 2. Minimum cash reserve — compute reason
        if potential_allowed > 0:
            max_after_reserve = max(0.0, cash - min_reserve)
            if max_after_reserve < potential_allowed:
                potential_allowed = max_after_reserve
                if DistributionBlockReason.MANUAL_LOCKUP not in reasons:
                    reasons.append(DistributionBlockReason.MINIMUM_CASH_RESERVE)

        # 3. Negative cash — record reason/warning
        if cash < 0 and not allow_neg:
            reasons.append(DistributionBlockReason.NEGATIVE_CASH)
            warnings.append(
                f"Period {i}: negative cash {cash:.1f} kEUR — "
                f"distribution allowed but cash is negative"
            )

        # Phase 5G: allowed always equals requested (no reduction)
        # Reasons/warnings are still visible for audit purposes.
        allowed = requested
        retained = cash - allowed

        periods.append(DistributionConstraintPeriod(
            period=i,
            entity_code=entity_code,
            cash_before_distribution_keur=cash,
            requested_distribution_keur=requested,
            allowed_distribution_keur=allowed,
            retained_cash_keur=retained,
            block_reasons=tuple(reasons),
            warnings=tuple(warnings),
        ))
        all_warnings.extend(warnings)

    return DistributionConstraintResult(
        entity_code=entity_code,
        periods=tuple(periods),
        total_requested_distribution_keur=sum(p.requested_distribution_keur for p in periods),
        total_allowed_distribution_keur=sum(p.allowed_distribution_keur for p in periods),
        total_retained_cash_keur=sum(p.retained_cash_keur for p in periods),
        warnings=tuple(all_warnings),
    )


def _pass_through(
    entity_code: str,
    cash_available_by_period: tuple[float, ...],
    requested_distributions_by_period: tuple[float, ...],
) -> DistributionConstraintResult:
    """No constraints applied — pass everything through unchanged."""
    n = max(len(cash_available_by_period), len(requested_distributions_by_period))
    periods: list[DistributionConstraintPeriod] = []

    for i in range(n):
        cash = cash_available_by_period[i] if i < len(cash_available_by_period) else 0.0
        requested = (
            requested_distributions_by_period[i]
            if i < len(requested_distributions_by_period)
            else 0.0
        )
        periods.append(DistributionConstraintPeriod(
            period=i,
            entity_code=entity_code,
            cash_before_distribution_keur=cash,
            requested_distribution_keur=requested,
            allowed_distribution_keur=requested,
            retained_cash_keur=cash - requested,
            block_reasons=(),
            warnings=(),
        ))

    return DistributionConstraintResult(
        entity_code=entity_code,
        periods=tuple(periods),
        total_requested_distribution_keur=sum(p.requested_distribution_keur for p in periods),
        total_allowed_distribution_keur=sum(p.allowed_distribution_keur for p in periods),
        total_retained_cash_keur=sum(p.retained_cash_keur for p in periods),
        warnings=(),
    )
