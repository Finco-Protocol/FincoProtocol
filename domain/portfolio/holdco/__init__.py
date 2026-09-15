"""Phase 3A HoldCo domain skeleton.

Planning only. No SHL. No tax template. No cash flow calculations yet.
No Excel export. No UI. Pure dataclass + validation layer.
"""
from __future__ import annotations

from domain.portfolio.holdco.inputs import (
    HoldCoInputs,
    HoldCoEntity,
    SPVOwnership,
    HoldCoOpexInputs,
)
from domain.portfolio.holdco.result import (
    HoldCoResult,
    HoldCoPeriodResult,
    HoldCoSPVContribution,
)
from domain.portfolio.holdco.runner import (
    build_holdco_result,
    aggregate_holdco_periods,
    validate_holdco_alignment,
)

__all__ = [
    "HoldCoInputs",
    "HoldCoEntity",
    "SPVOwnership",
    "HoldCoOpexInputs",
    "HoldCoResult",
    "HoldCoPeriodResult",
    "HoldCoSPVContribution",
    "build_holdco_result",
    "aggregate_holdco_periods",
    "validate_holdco_alignment",
]