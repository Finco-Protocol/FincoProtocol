"""Phase 5D.4 HoldCo retained cash overlay — audit-only HoldCo-level retained cash helpers.

No mutation of HoldCo results. No waterfall changes. No enforcement.
Informational overlay only.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from typing import Any


def _safe_float(value: Any, default: float = 0.0) -> float:
    """Cast value to float, rejecting bool and non-numeric types."""
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return float(value)
    return default


def _safe_entity_code(value: Any, default: str = "HOLDCO") -> str:
    """Extract non-empty string entity code, rejecting bool/int/float/Mock."""
    if isinstance(value, str) and value.strip():
        return value
    return default


def holdco_requested_distribution_by_period(
    holdco_result: Any,
) -> tuple[float, ...]:
    """Extract requested sponsor distribution per period from HoldCo result.

    Priority:
      1. distribution_to_sponsor_keur from each HoldCoPeriodResult
      2. 0.0 if not available

    No fallback to total_after_tax_cashflow_keur — that field does not
    exist in HoldCoPeriodResult. If distribution_to_sponsor_keur is missing,
    0.0 is used for that period.

    Parameters
    ----------
    holdco_result : HoldCoResult
        HoldCo result object with .periods attribute.

    Returns
    -------
    tuple[float, ...]
        Requested distribution (>= 0) per period, in period order.
    """
    if not hasattr(holdco_result, "periods"):
        return ()

    result: list[float] = []
    for period in holdco_result.periods:
        dist = _safe_float(getattr(period, "distribution_to_sponsor_keur", None))
        result.append(max(0.0, dist))

    return tuple(result)


def holdco_available_distribution_by_period(
    holdco_result: Any,
    retained_cash_by_period: tuple[float, ...],
) -> tuple[float, ...]:
    """Compute available distribution per period after retained cash deduction.

    Formula per period:
        available = max(0, requested - retained)

    Result length = max(len(requested), len(retained_cash_by_period)).
    The shorter sequence is zero-padded.

    Parameters
    ----------
    holdco_result : Any
        HoldCo result object.
    retained_cash_by_period : tuple[float, ...]
        Retained cash amount per period (overlay-only).

    Returns
    -------
    tuple[float, ...]
        Available distribution per period (>= 0).
    """
    requested = holdco_requested_distribution_by_period(holdco_result)
    n = max(len(requested), len(retained_cash_by_period))

    result: list[float] = []
    for i in range(n):
        req = requested[i] if i < len(requested) else 0.0
        ret = retained_cash_by_period[i] if i < len(retained_cash_by_period) else 0.0
        result.append(max(0.0, req - ret))

    return tuple(result)


@dataclass(frozen=True)
class HoldCoRetainedCashOverlay:
    """HoldCo-level retained cash overlay result.

    Audit-only: shows what sponsor distributions WOULD be constrained to
    given the retained cash policy, without changing any HoldCo result field.

    Fields
    ------
    entity_code : str
        HoldCo identifier.
    retained_cash_by_period : tuple[float, ...]
        Retained cash per period (overlay-only input).
    requested_distribution_by_period : tuple[float, ...]
        Raw requested distribution per period from HoldCo result.
    available_distribution_by_period : tuple[float, ...]
        Distribution available after retained cash deduction.
        Always >= 0.
    warnings : tuple[str, ...]
        Warnings (e.g., tuple length mismatch).
    """
    entity_code: str
    retained_cash_by_period: tuple[float, ...] = field(default_factory=tuple)
    requested_distribution_by_period: tuple[float, ...] = field(default_factory=tuple)
    available_distribution_by_period: tuple[float, ...] = field(default_factory=tuple)
    warnings: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self):
        if not self.entity_code or not self.entity_code.strip():
            raise ValueError(
                f"entity_code must be non-empty and non-whitespace, "
                f"got {self.entity_code!r}"
            )
        for v in self.retained_cash_by_period:
            if v < 0:
                raise ValueError(
                    f"retained_cash_by_period values must be >= 0, got {v}"
                )
        for v in self.available_distribution_by_period:
            if v < 0:
                raise ValueError(
                    f"available_distribution_by_period values must be >= 0, got {v}"
                )

        # Warn on length mismatch
        warnings: list[str] = list(self.warnings)
        if (len(self.retained_cash_by_period) != len(self.requested_distribution_by_period)
                and len(self.retained_cash_by_period) > 0
                and len(self.requested_distribution_by_period) > 0):
            warnings.append(
                f"retained_cash_by_period length ({len(self.retained_cash_by_period)}) "
                f"!= requested_distribution_by_period length "
                f"({len(self.requested_distribution_by_period)})"
            )

        if warnings and not self.warnings:
            object.__setattr__(self, 'warnings', tuple(warnings))


def build_holdco_retained_cash_overlay(
    holdco_result: Any,
    retained_cash_by_period: tuple[float, ...],
) -> HoldCoRetainedCashOverlay:
    """Build a HoldCo retained cash overlay from a HoldCo result.

    Parameters
    ----------
    holdco_result : Any
        HoldCo result object (e.g., HoldCoResult).
    retained_cash_by_period : tuple[float, ...]
        Retained cash per period (audit-only overlay input).

    Returns
    -------
    HoldCoRetainedCashOverlay
        Audit-only overlay showing requested vs available distributions.

    No mutation of holdco_result.
    """
    entity_code = _safe_entity_code(getattr(holdco_result, "name", None))

    requested = holdco_requested_distribution_by_period(holdco_result)
    available = holdco_available_distribution_by_period(holdco_result, retained_cash_by_period)

    return HoldCoRetainedCashOverlay(
        entity_code=str(entity_code),
        retained_cash_by_period=retained_cash_by_period,
        requested_distribution_by_period=requested,
        available_distribution_by_period=available,
        warnings=(),
    )