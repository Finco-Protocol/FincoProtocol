"""Generation Losses & Pre-COD candidate (WF-03A).

RELEASE-CLOSED CANDIDATE — this package is not released financial
authority, is never imported by any production path, and adds no product
surface. See ``contracts.py`` for the typed scope and
``docs/model_v2/WF03A_FINANCIAL_OWNER_DECISIONS.md`` for the open
financial decisions.

Naming: ``GENERATION_V2_*`` per the candidate package name; the released
generation authority (``finco_core/revenue/generation.py``, PPA-01 pinned)
is never modified by this candidate.
"""
from app.generation_v2_candidate.contracts import (  # noqa: F401
    ACTIVATION_ENABLED,
    COMPENSATION_BASES,
    LOSS_MODES,
    PARTIAL_COD_TREATMENTS,
    PRICE_BASES,
    DegradationOnset,
    FirstYearAvailability,
    LossFactorWindow,
    PreCodCommissioning,
    TransmissionLossFactor,
    VolumeAdjustmentEvent,
    canonical_json,
    require_release,
    validate_no_event_overlaps,
)
from app.generation_v2_candidate.pure import (  # noqa: F401
    EventAttribution,
    OperatingPeriodAdjustments,
    PreCodMonthProposal,
    PreCodProposal,
    TransmissionSplit,
    VolumeAdjustmentOutcome,
    apply_transmission_loss,
    apply_transmission_loss_to_periods,
    apply_volume_adjustments,
    build_pre_cod_proposal,
    compose_operating_adjustments,
    month_sequence,
    overlap_days,
    period_days_inclusive,
)

__all__ = [
    "ACTIVATION_ENABLED", "require_release",
    "LOSS_MODES", "COMPENSATION_BASES", "PRICE_BASES",
    "PARTIAL_COD_TREATMENTS",
    "LossFactorWindow", "TransmissionLossFactor",
    "DegradationOnset", "FirstYearAvailability",
    "VolumeAdjustmentEvent", "PreCodCommissioning",
    "validate_no_event_overlaps", "canonical_json",
    "TransmissionSplit", "OperatingPeriodAdjustments",
    "EventAttribution", "VolumeAdjustmentOutcome",
    "PreCodMonthProposal", "PreCodProposal",
]
