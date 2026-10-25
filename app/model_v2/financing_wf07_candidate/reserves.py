"""Reserve contracts, evidence and ledgers: DSRA (cash) and DSRF (facility).

DSRA and DSRF are separate contract types and are never netted. A DSRA is
cash: opening + deposits - draws - releases = closing. A DSRF is an undrawn
standby limit: opening drawn + draws - restorations = closing drawn, and
availability = limit - drawn. A DSRF never carries a cash deposit.
The reserve TARGET (horizon, measurement date, aggregate vs per-facility) is
OPEN and is therefore supplied as explicit evidence; the helpers below only
derive candidate requirements from supplied contractual schedules.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from app.model_v2.financing_wf07_candidate.contracts import (
    Decision, EvidenceStatus, Layer, ReserveType, Wf07Error, dec, enum, ident, index, opt_dec,
)


@dataclass(frozen=True)
class ReserveContract:
    reserve_id: str
    reserve_type: ReserveType
    #: DSRF only: the facility limit. A DSRA has no limit and a DSRF must have one.
    facility_limit: Optional[Decimal] = None
    limit_evidence_id: Optional[str] = None
    fee_policy: Decision = Decision.OPEN

    def __post_init__(self):
        ident(self.reserve_id, "ReserveContract.reserve_id")
        enum(self.reserve_type, ReserveType, "reserve_type")
        if self.fee_policy is not Decision.OPEN:
            raise Wf07Error("WF07_DECISION_NOT_OPEN", "reserve fee policy is an OPEN owner decision")
        if self.reserve_type is ReserveType.DSRF:
            if self.facility_limit is None or self.limit_evidence_id is None:
                raise Wf07Error("WF07_DSRF_FACILITY_EVIDENCE_MISSING", self.reserve_id)
            dec(self.facility_limit, "facility_limit", positive=True)
            ident(self.limit_evidence_id, "limit_evidence_id")
        elif self.facility_limit is not None or self.limit_evidence_id is not None:
            raise Wf07Error("WF07_DSRA_IS_CASH_NOT_A_FACILITY", self.reserve_id)


@dataclass(frozen=True)
class ReserveTargetEvidence:
    period_index: int
    reserve_id: str
    target: Optional[Decimal]
    source_id: str
    status: EvidenceStatus = EvidenceStatus.EVIDENCED

    def __post_init__(self):
        index(self.period_index, "target.period_index")
        ident(self.reserve_id, "target.reserve_id")
        opt_dec(self.target, "target.target", nonnegative=True)
        ident(self.source_id, "target.source_id")
        enum(self.status, EvidenceStatus, "target.status")


@dataclass(frozen=True)
class ReserveOpening:
    """Existing reserve position at the first operating period: DSRA cash balance
    or DSRF drawn amount, with its source."""

    reserve_id: str
    amount: Decimal
    source_id: str

    def __post_init__(self):
        ident(self.reserve_id, "opening.reserve_id")
        dec(self.amount, "opening.amount", nonnegative=True)
        ident(self.source_id, "opening.source_id")


@dataclass(frozen=True)
class DsraRow:
    """opening + deposit - draw - release = closing; cash conservation is checked by the engine."""

    reserve_id: str
    period_index: int
    opening: Decimal
    target: Decimal
    deposit: Decimal
    draw: Decimal
    release: Decimal
    closing: Decimal
    shortfall_to_target: Decimal


@dataclass(frozen=True)
class DsrfRow:
    """opening_drawn + draw - restoration = closing_drawn; available = limit - drawn."""

    reserve_id: str
    period_index: int
    limit: Decimal
    opening_drawn: Decimal
    target: Decimal
    draw: Decimal
    restoration: Decimal
    closing_drawn: Decimal
    available: Decimal
    coverage_shortfall: Decimal


@dataclass(frozen=True)
class FacilityService:
    """One facility's contractual service for one period, supplied as evidence."""

    period_index: int
    facility_id: str
    layer: Layer
    contractual_service: Optional[Decimal]
    source_id: str
    #: Amount actually paid, if the caller supplies it. For a shortfall it is
    #: the ONLY admissible allocation (no implicit pro-rata).
    paid_service: Optional[Decimal] = None

    def __post_init__(self):
        index(self.period_index, "service.period_index")
        ident(self.facility_id, "service.facility_id")
        enum(self.layer, Layer, "service.layer")
        if self.layer is Layer.SHAREHOLDER_LOAN:
            raise Wf07Error("WF07_SHL_IS_NOT_A_FACILITY", "use ShlTerms for shareholder loans")
        opt_dec(self.contractual_service, "contractual_service", nonnegative=True)
        ident(self.source_id, "service.source_id")
        opt_dec(self.paid_service, "paid_service", nonnegative=True)


def forward_requirement(services, period_index: int, horizon_periods: int,
                        facility_id: Optional[str] = None):
    """Candidate forward requirement: contractual SENIOR service of the next
    ``horizon_periods`` periods strictly after ``period_index``.

    ``facility_id=None`` aggregates every senior facility (multiple tranches are
    summed per period); a facility id gives the per-facility requirement.
    Returns ``(amount, truncated)``; ``truncated`` is True when fewer than
    ``horizon_periods`` future periods exist. Any missing contractual service in
    the window returns ``(None, False)`` (UNAVAILABLE, never zero). The horizon
    and the aggregate-vs-per-facility choice are OPEN owner decisions: the result
    is evidence to be supplied as a ReserveTargetEvidence, never applied implicitly.
    """
    index(period_index, "period_index")
    if isinstance(horizon_periods, bool) or not isinstance(horizon_periods, int) or horizon_periods < 1:
        raise Wf07Error("WF07_VALUE", "horizon_periods must be a positive integer")
    senior = [s for s in services if s.layer is Layer.SENIOR
              and (facility_id is None or s.facility_id == facility_id)]
    future = sorted({s.period_index for s in senior if s.period_index > period_index})[:horizon_periods]
    total = Decimal(0)
    for p in future:
        for s in senior:
            if s.period_index == p:
                if s.contractual_service is None:
                    return None, False
                total += s.contractual_service
    return total, len(future) < horizon_periods
