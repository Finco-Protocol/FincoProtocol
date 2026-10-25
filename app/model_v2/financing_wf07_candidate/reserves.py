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
from typing import NamedTuple, Optional

from app.model_v2.financing_wf07_candidate.contracts import (
    Decision, EvidenceStatus, Layer, ReserveType, Wf07Error, dec, enum, ident, index, opt_dec, unique,
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


COMPLETE = "COMPLETE"
TRUNCATED = "TRUNCATED"
UNAVAILABLE = "UNAVAILABLE"


class ForwardRequirement(NamedTuple):
    """Result of :func:`forward_requirement`.

    ``amount`` is ``None`` whenever ``status`` is UNAVAILABLE (never a zero).
    ``truncated`` is True when fewer than the requested horizon periods exist on
    the supplied axis; an amount of zero is then the sum over NO future periods.
    """

    amount: Optional[Decimal]
    truncated: bool
    status: str
    reasons: tuple


def validate_services(services) -> tuple:
    """Structural validation of contractual-service evidence; raises on malformed
    or conflicting input. Returns the rows as a tuple."""
    if not isinstance(services, (tuple, list)):
        raise Wf07Error("WF07_VALUE", "services must be a tuple or list of FacilityService")
    rows = tuple(services)
    if not all(isinstance(s, FacilityService) for s in rows):
        raise Wf07Error("WF07_VALUE", "every service row must be a FacilityService")
    unique([(s.period_index, s.facility_id) for s in rows], "facility service row")
    unique([s.source_id for s in rows], "debt-service source")
    layers = {}
    for s in rows:
        if layers.setdefault(s.facility_id, s.layer) is not s.layer:
            raise Wf07Error("WF07_FACILITY_LAYER", s.facility_id)
    return rows


def forward_requirement(services, period_index: int, horizon_periods: int,
                        facility_id: Optional[str] = None,
                        axis: Optional[tuple] = None) -> ForwardRequirement:
    """Candidate forward requirement: contractual SENIOR service of the next
    ``horizon_periods`` periods strictly after ``period_index``.

    ``facility_id=None`` aggregates every senior facility (multiple tranches are
    summed per period); a facility id gives the per-facility requirement. The
    horizon and the aggregate-vs-per-facility choice are OPEN owner decisions: the
    result is evidence to be supplied as a ReserveTargetEvidence, never applied
    implicitly.

    Input is validated: duplicate (period, facility) rows or duplicate source
    identities, non-FacilityService rows and a facility used in two layers raise.
    A requested facility that is unknown, or not SENIOR, raises (never a zero).

    Coverage is explicit. ``axis`` is the canonical operating period indices; when
    given, the window is the next ``horizon_periods`` axis periods and every
    senior facility in scope must have a row in each of them (explicit zero for a
    matured facility). Any missing row, a missing contractual value, or (without an
    axis) no future rows at all returns status UNAVAILABLE with typed reasons and
    ``amount=None``. Actual zero contractual service is a valid zero.
    """
    rows = validate_services(services)
    index(period_index, "period_index")
    if isinstance(horizon_periods, bool) or not isinstance(horizon_periods, int) or horizon_periods < 1:
        raise Wf07Error("WF07_VALUE", "horizon_periods must be a positive integer")
    senior_all = [s for s in rows if s.layer is Layer.SENIOR]
    if facility_id is not None:
        ident(facility_id, "facility_id")
        known = {s.facility_id: s.layer for s in rows}
        if facility_id not in known:
            raise Wf07Error("WF07_UNKNOWN_FACILITY", facility_id)
        if known[facility_id] is not Layer.SENIOR:
            raise Wf07Error("WF07_FACILITY_NOT_SENIOR", facility_id)
    scope = {s.facility_id for s in senior_all if facility_id is None or s.facility_id == facility_id}
    if not scope:
        return ForwardRequirement(None, False, UNAVAILABLE, ("WF07_NO_SENIOR_EVIDENCE",))
    if axis is not None:
        if not isinstance(axis, tuple) or not axis:
            raise Wf07Error("WF07_VALUE", "axis must be a non-empty tuple of period indices")
        for a in axis:
            index(a, "axis period")
        if list(axis) != sorted(set(axis)):
            raise Wf07Error("WF07_VALUE", "axis must be strictly increasing")
        future = [a for a in axis if a > period_index][:horizon_periods]
    else:
        future = sorted({s.period_index for s in senior_all if s.facility_id in scope
                         and s.period_index > period_index})[:horizon_periods]
        if not future:
            return ForwardRequirement(None, False, UNAVAILABLE, ("WF07_FORWARD_WINDOW_EMPTY",))
    by_key = {(s.period_index, s.facility_id): s for s in senior_all if s.facility_id in scope}
    total = Decimal(0)
    reasons = []
    for p in future:
        for fac in sorted(scope):
            row = by_key.get((p, fac))
            if row is None:
                reasons.append("WF07_FORWARD_FACILITY_ROW_MISSING")
            elif row.contractual_service is None:
                reasons.append("WF07_FORWARD_CONTRACTUAL_SERVICE_MISSING")
            else:
                total += row.contractual_service
    if reasons:
        return ForwardRequirement(None, False, UNAVAILABLE, tuple(sorted(set(reasons))))
    truncated = len(future) < horizon_periods
    return ForwardRequirement(total, truncated, TRUNCATED if truncated else COMPLETE, ())
