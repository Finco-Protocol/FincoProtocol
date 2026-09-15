"""Phase 5D.1 distribution constraint inputs."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class DistributionBlockReason(str, Enum):
    """Reasons why a distribution may be blocked or reduced.

    NONE: no constraint applied
    NEGATIVE_CASH: cash available is negative
    MINIMUM_CASH_RESERVE: result would breach minimum cash reserve
    DSRF_REPAYMENT: DSRF repayment claim on available cash
    SHL_PRINCIPAL_REPAYMENT: SHL principal repayment claim on available cash
    HOLDCO_RESTRICTION: HoldCo-level restriction
    TAX_RESTRICTION: tax-related restriction
    MANUAL_LOCKUP: user-configured distribution pause
    OTHER: catch-all for unclassified reasons
    """
    NONE = "NONE"
    NEGATIVE_CASH = "NEGATIVE_CASH"
    MINIMUM_CASH_RESERVE = "MINIMUM_CASH_RESERVE"
    DSRF_REPAYMENT = "DSRF_REPAYMENT"
    SHL_PRINCIPAL_REPAYMENT = "SHL_PRINCIPAL_REPAYMENT"
    HOLDCO_RESTRICTION = "HOLDCO_RESTRICTION"
    TAX_RESTRICTION = "TAX_RESTRICTION"
    MANUAL_LOCKUP = "MANUAL_LOCKUP"
    OTHER = "OTHER"


class DistributionEnforcementMode(str, Enum):
    """Distribution enforcement mode — controls how constraints are applied.

    Phase 5G is schema-only. No mode is actively enforced.
    OFF and config.enabled=False both pass through with no reasons required.
    WARNING_ONLY/SOFT_CAP/HARD_BLOCK compute reasons/warnings but do not
    reduce allowed_distribution_keur.

    OFF:         audit-only, all distributions pass through unchanged (no reasons).
    WARNING_ONLY: compute reasons/warnings but allowed = requested (no cash impact).
    SOFT_CAP:    future — allowed = requested, warning added.
    HARD_BLOCK:  future — allowed = requested, warning added.
    """
    OFF = "OFF"
    WARNING_ONLY = "WARNING_ONLY"
    SOFT_CAP = "SOFT_CAP"
    HARD_BLOCK = "HARD_BLOCK"


@dataclass(frozen=True)
class DistributionConstraintConfig:
    """Configuration for distribution constraint evaluation.

    This class controls two separate concerns:

    1. ``enabled`` — whether constraint evaluation is active at the call site.

       - ``enabled=False`` (default): all distributions pass through unchanged.
         The evaluator returns requested amounts with no block reasons or warnings.
         Use this to disable constraints for a specific call without removing config.

       - ``enabled=True``: evaluator inspects constraints and applies the configured
         ``enforcement_mode`` behavior.

    2. ``enforcement_mode`` — what happens once enabled.

       - ``OFF`` (default): audit-only pass-through. All distributions pass through
         unchanged; no block reasons or warnings are recorded. This is the safe
         default when constraints are configured but not yet enforced.

       - ``WARNING_ONLY``: compute block reasons and warnings for visibility, but
         ``allowed_distribution_keur`` stays equal to ``requested_distribution_keur``.
         No actual cash impact.

       - ``SOFT_CAP`` / ``HARD_BLOCK``: future modes. Currently emit a "not active
         in Phase 5G" warning but otherwise behave like ``WARNING_ONLY``.
         ``allowed`` always equals ``requested`` in Phase 5G.

    Phase 5G is schema-only. No mode reduces ``allowed_distribution_keur`` or
    changes waterfall economics.

    Parameters
    ----------
    enabled : bool
        If False (default), all distributions pass through unchanged.
        This makes constraint evaluation opt-in at the call site.
        Even with ``enabled=True``, ``OFF`` mode (default) still passes through.
    enforcement_mode : DistributionEnforcementMode
        Controls behavior once enabled. Default ``OFF`` is audit-only pass-through.
        ``SOFT_CAP`` and ``HARD_BLOCK`` are schema-only until future enforcement phase.
    minimum_cash_reserve_keur : float
        Minimum cash balance to maintain. Distributions are constrained
        so that closing cash >= this value. Default 0.0.
    allow_negative_cash : bool
        If False (default), negative cash adds NEGATIVE_CASH reason
        but does not block the distribution. Phase 5D.5 enforcement
        will treat this as a hard block.
    manual_lockup_periods : tuple[int, ...]
        Period indices where distribution is manually locked at 0.
        Default empty tuple. Accepts list[int] which is normalized to tuple.
    """
    enabled: bool = False
    minimum_cash_reserve_keur: float = 0.0
    allow_negative_cash: bool = False
    manual_lockup_periods: tuple[int, ...] = ()
    enforcement_mode: DistributionEnforcementMode = DistributionEnforcementMode.OFF

    def __post_init__(self):
        if self.minimum_cash_reserve_keur < 0:
            raise ValueError(
                f"minimum_cash_reserve_keur must be >= 0, "
                f"got {self.minimum_cash_reserve_keur}"
            )

        raw = self.manual_lockup_periods

        # Normalize list to tuple
        if isinstance(raw, list):
            normalized = tuple(raw)
        else:
            normalized = raw

        # Reject any bool values (bool is subclass of int in Python)
        for p in normalized:
            if isinstance(p, bool):
                raise ValueError(
                    f"manual_lockup_periods must contain only integers >= 0, "
                    f"got bool {p}"
                )
            if not isinstance(p, int):
                raise ValueError(
                    f"manual_lockup_periods must contain only integers >= 0, "
                    f"got {type(p).__name__}"
                )
            if p < 0:
                raise ValueError(
                    f"manual_lockup_periods must all be >= 0, got {p}"
                )

        # Normalize to tuple using object.__setattr__ (frozen dataclass)
        if normalized != self.manual_lockup_periods:
            object.__setattr__(self, 'manual_lockup_periods', normalized)

        # enforcement_mode must be DistributionEnforcementMode, not None/string/bool
        if not isinstance(self.enforcement_mode, DistributionEnforcementMode):
            raise ValueError(
                f"enforcement_mode must be a DistributionEnforcementMode, "
                f"got {type(self.enforcement_mode).__name__}"
            )