"""BESS commercial and lender-facing contracts (WF-08A) — RELEASE-CLOSED CANDIDATE.

Not released financial authority, not imported by any production path, and no product surface. It consumes the
existing native BESS evidence (``domain/bess``) and settlement proposals, adds typed commercial contracts around
them, and records every unresolved economic choice as an OPEN Financial Owner decision. See
``docs/model_v2/BESS_COMMERCIAL_CANDIDATE_OWNER_DECISION_PACKET.md`` and
``docs/model_v2/BESS_COMMERCIAL_CANDIDATE_SOURCE_INVENTORY.md``.
"""
from app.bess_commercial_candidate.contracts import (  # noqa: F401
    ACTIVATION_ENABLED, CANDIDATE, NOT_APPLICABLE, UNAVAILABLE, AugmentationTrigger, BessCommercialError,
    ChargingBasis, Decision, Direction, Party, RevenueClass, Service, canonical_json, identity, require_release,
)
from app.bess_commercial_candidate.charging import (  # noqa: F401
    ChargingPeriod, ChargingStatement, LegKind, ReceiptLeg, StatementLine, charging_book, charging_statement,
    native_charging_period, native_net_spread_period, reconcile_with_native_hours,
)
from app.bess_commercial_candidate.revenue import (  # noqa: F401
    LENDER_TREATMENT, LenderPresentation, LenderTreatment, RevenueLine, link_to_allocation, present_for_lender,
    stack_by_service,
)
from app.bess_commercial_candidate.allocation import (  # noqa: F401
    AllocationResult, AllocationRow, EnergyClaim, ReservationClaim, allocate,
)
from app.bess_commercial_candidate.tolling import (  # noqa: F401
    PerformanceDeduction, TollingContract, TollingOpenDecisions, TollingPeriod, TollingStatement,
    reservation_for_tolling, tolling_statement,
)
from app.bess_commercial_candidate.augmentation import (  # noqa: F401
    AugmentationCommercialPolicy, EventAlignment, TriggerEvidence, augmentation_financial_posting,
    evaluate_trigger, native_event_alignment,
)
from app.bess_commercial_candidate.lcos import LcosReceiptSet, build_lcos_receipts  # noqa: F401
