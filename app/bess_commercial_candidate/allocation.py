"""Declared dispatch allocation and revenue stacking (WF-08A, release-closed).

Four services are kept separate:

- ``ENERGY_THROUGHPUT``       physical AC MWh moved under a throughput-based obligation;
- ``MERCHANT_ENERGY``         physical AC MWh settled at a merchant price;
- ``CAPACITY_RESERVATION``    reserved MW over a window — it does NOT consume physical throughput;
- ``ANCILLARY_AVAILABILITY``  reserved availability MW over a window — also no throughput by itself.

Energy claims reference native hourly evidence (``ac_charge_mwh`` / ``ac_discharge_mwh`` of
``domain.bess.dispatch.HourEvidence``). The same physical MWh can be claimed once: the sum of claims for
an (hour, direction) cannot exceed the native quantity, claim identities are unique, and a claim on a
direction with no native energy is rejected. Whether one MW may back several services at once is an OPEN
Financial Owner decision; this candidate conservatively rejects over-reservation of the rated power.
No battery physics is recalculated.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Optional

from app.bess_commercial_candidate.contracts import (
    exact_arithmetic,
    CANDIDATE, BessCommercialError, Direction, Service, dec, enum_member, ident, opt_ident,
    reconciles, require_release, tuple_of, unique, utc_hour,
)

_ENERGY_SERVICES = (Service.ENERGY_THROUGHPUT, Service.MERCHANT_ENERGY)
_RESERVATION_SERVICES = (Service.CAPACITY_RESERVATION, Service.ANCILLARY_AVAILABILITY)
_ONE_HOUR = timedelta(hours=1)


@dataclass(frozen=True)
class EnergyClaim:
    claim_id: str
    service: Service
    hour: datetime
    direction: Direction
    mwh: Decimal
    obligation_ref: Optional[str] = None

    def __post_init__(self):
        ident(self.claim_id, "claim_id")
        enum_member(self.service, Service, "service")
        if self.service not in _ENERGY_SERVICES:
            raise BessCommercialError(
                f"BESS_COMMERCIAL_ALLOCATION: {self.service.value} is not an energy-consuming service; "
                "reservations carry MW over a window, never MWh")
        utc_hour(self.hour, "hour")
        enum_member(self.direction, Direction, "direction")
        dec(self.mwh, "mwh", positive=True)
        opt_ident(self.obligation_ref, "obligation_ref")


@dataclass(frozen=True)
class ReservationClaim:
    """Reserved MW over [start, end). It consumes no physical throughput by itself."""

    claim_id: str
    service: Service
    start: datetime
    end: datetime
    direction: Direction
    reserved_mw: Decimal
    obligation_ref: Optional[str] = None

    def __post_init__(self):
        ident(self.claim_id, "claim_id")
        enum_member(self.service, Service, "service")
        if self.service not in _RESERVATION_SERVICES:
            raise BessCommercialError(
                f"BESS_COMMERCIAL_ALLOCATION: {self.service.value} is an energy service; "
                "a reservation claim must be CAPACITY_RESERVATION or ANCILLARY_AVAILABILITY")
        utc_hour(self.start, "start")
        utc_hour(self.end, "end")
        if not self.start < self.end:
            raise BessCommercialError("BESS_COMMERCIAL_TIME: reservation end must be after start")
        enum_member(self.direction, Direction, "direction")
        dec(self.reserved_mw, "reserved_mw", positive=True)
        opt_ident(self.obligation_ref, "obligation_ref")


@dataclass(frozen=True)
class AllocationRow:
    hour: datetime
    direction: Direction
    native_mwh: Decimal
    claimed_mwh: Decimal
    unallocated_mwh: Decimal
    reserved_mw: Decimal
    headroom_mw: Decimal


@dataclass(frozen=True)
class AllocationResult:
    status: str
    rows: tuple
    claimed_mwh: Decimal
    unallocated_mwh: Decimal
    fully_allocated: bool


def _native(hours) -> dict:
    index = {}
    for hour in tuple_of(hours, "native_hours"):
        start = utc_hour(hour.start, "native hour start")
        if start in index:
            raise BessCommercialError(f"BESS_COMMERCIAL_ALLOCATION: duplicate native hour {start.isoformat()}")
        index[start] = hour
    if not index:
        raise BessCommercialError("BESS_COMMERCIAL_ALLOCATION: native hourly evidence required")
    return index


@exact_arithmetic
def allocate(energy_claims, reservation_claims, native_hours, *, rated_discharge_mw: Decimal,
             rated_charge_mw: Decimal) -> AllocationResult:
    """Reconcile declared claims with native hourly dispatch evidence; fail closed on double claims."""
    require_release()
    energy_claims = tuple_of(energy_claims, "energy_claims")
    reservation_claims = tuple_of(reservation_claims, "reservation_claims")
    rated = {Direction.DISCHARGE_AC: dec(rated_discharge_mw, "rated_discharge_mw", positive=True),
             Direction.CHARGE_AC: dec(rated_charge_mw, "rated_charge_mw", positive=True)}
    native = _native(native_hours)
    unique([c.claim_id for c in energy_claims] + [c.claim_id for c in reservation_claims], "claim_id")
    quantity = lambda hour, direction: (hour.ac_discharge_mwh if direction is Direction.DISCHARGE_AC
                                        else hour.ac_charge_mwh)

    claimed: dict = {}
    for claim in energy_claims:
        if not isinstance(claim, EnergyClaim):
            raise BessCommercialError("BESS_COMMERCIAL_SCHEMA: EnergyClaim required")
        hour = native.get(claim.hour)
        if hour is None:
            raise BessCommercialError(
                f"BESS_COMMERCIAL_ALLOCATION: claim {claim.claim_id!r} is outside the native dispatch evidence")
        key = (claim.hour, claim.direction)
        available = quantity(hour, claim.direction)
        if available <= 0:
            raise BessCommercialError(
                f"BESS_COMMERCIAL_ALLOCATION: claim {claim.claim_id!r} claims {claim.direction.value} energy "
                "in an hour with none in the native evidence")
        claimed[key] = claimed.get(key, Decimal(0)) + claim.mwh
        if claimed[key] - available > 0 and not reconciles(claimed[key], available):
            raise BessCommercialError(
                f"BESS_COMMERCIAL_DOUBLE_COUNT: the same MWh is claimed twice in {claim.hour.isoformat()} "
                f"{claim.direction.value} (claimed {claimed[key]} of {available} native MWh)")

    reserved: dict = {}
    for claim in reservation_claims:
        if not isinstance(claim, ReservationClaim):
            raise BessCommercialError("BESS_COMMERCIAL_SCHEMA: ReservationClaim required")
        at = claim.start
        while at < claim.end:
            hour = native.get(at)
            if hour is None:
                raise BessCommercialError(
                    f"BESS_COMMERCIAL_ALLOCATION: reservation {claim.claim_id!r} extends outside the native evidence")
            if not hour.available:
                raise BessCommercialError(
                    f"BESS_COMMERCIAL_ALLOCATION: reservation {claim.claim_id!r} covers an unavailable hour "
                    f"{at.isoformat()}")
            key = (at, claim.direction)
            reserved[key] = reserved.get(key, Decimal(0)) + claim.reserved_mw
            if reserved[key] > rated[claim.direction]:
                raise BessCommercialError(
                    f"BESS_COMMERCIAL_DOUBLE_COUNT: more than the rated {claim.direction.value} power is "
                    f"reserved in {at.isoformat()} (whether one MW may back several services is an OPEN "
                    "Financial Owner decision)")
            at += _ONE_HOUR

    rows, total_claimed = [], Decimal(0)
    for key in sorted(set(claimed) | set(reserved), key=lambda k: (k[0], k[1].value)):
        hour, direction = key
        native_mwh = quantity(native[hour], direction)
        amount = claimed.get(key, Decimal(0))
        mw = reserved.get(key, Decimal(0))
        rows.append(AllocationRow(hour, direction, native_mwh, amount, max(native_mwh - amount, Decimal(0)),
                                  mw, rated[direction] - mw))
        total_claimed += amount
    all_native = sum((quantity(h, d) for h in native.values() for d in Direction), Decimal(0))
    unallocated = all_native - total_claimed
    return AllocationResult(CANDIDATE, tuple(rows), total_claimed, unallocated,
                            reconciles(unallocated, Decimal(0)))
