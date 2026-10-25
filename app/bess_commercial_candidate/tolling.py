"""Tolling candidate (WF-08A, release-closed): contracted capacity with an availability-based fee.

The contract records what is DECLARED: contracted capacity, availability fee rate, contract dates,
guaranteed availability, who owns the energy and who is responsible for dispatch. It introduces no
unsupported assumption:

- the fee schedule is ``capacity x rate x overlap days / 365`` under the single declared convention
  ``ACT_365_FIXED``; any other day-count is unsupported (Financial Owner decision);
- performance deductions are DECLARED amounts with evidence — no formula links an availability shortfall
  to a deduction amount (that formula is an OPEN Financial Owner decision);
- merchant-upside allocation, availability-penalty formula, who bears charging cost and who bears
  degradation risk are typed :class:`Decision` fields that can only be ``OPEN``.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from decimal import Decimal
from typing import Optional

from app.bess_commercial_candidate.contracts import (
    exact_arithmetic,
    CANDIDATE, NOT_APPLICABLE, UNAVAILABLE, BessCommercialError, Decision, Direction, Party, Service,
    calendar_date, dec, enum_member, ident, open_decision, opt_dec, require_release, tuple_of, unique,
)
from app.bess_commercial_candidate.allocation import ReservationClaim

DAY_COUNT = "ACT_365_FIXED"
_ONE = Decimal(1)
_ZERO = Decimal(0)


@dataclass(frozen=True)
class TollingOpenDecisions:
    """Allocations the Financial Owner has not decided. Only OPEN is representable."""

    merchant_upside_allocation: Decision = Decision.OPEN
    availability_penalty_formula: Decision = Decision.OPEN
    charging_cost_bearer: Decision = Decision.OPEN
    degradation_risk_bearer: Decision = Decision.OPEN

    def __post_init__(self):
        for name in ("merchant_upside_allocation", "availability_penalty_formula",
                     "charging_cost_bearer", "degradation_risk_bearer"):
            open_decision(getattr(self, name), name)


@dataclass(frozen=True)
class TollingContract:
    contract_id: str
    contracted_capacity_mw: Decimal
    availability_fee_eur_mw_year: Decimal
    start: date                     # inclusive
    end: date                       # exclusive
    guaranteed_availability: Optional[Decimal]   # None = no guarantee declared
    energy_ownership: Party
    dispatch_responsibility: Party
    evidence_ref: str
    day_count: str = DAY_COUNT
    open_decisions: TollingOpenDecisions = TollingOpenDecisions()

    def __post_init__(self):
        ident(self.contract_id, "contract_id")
        ident(self.evidence_ref, "evidence_ref")
        dec(self.contracted_capacity_mw, "contracted_capacity_mw", positive=True)
        dec(self.availability_fee_eur_mw_year, "availability_fee_eur_mw_year", nonnegative=True)
        opt_dec(self.guaranteed_availability, "guaranteed_availability", minimum=_ZERO, maximum=_ONE)
        if not calendar_date(self.start, "start") < calendar_date(self.end, "end"):
            raise BessCommercialError("BESS_COMMERCIAL_TIME: tolling end must be after start")
        enum_member(self.energy_ownership, Party, "energy_ownership")
        enum_member(self.dispatch_responsibility, Party, "dispatch_responsibility")
        if self.day_count != DAY_COUNT:
            raise BessCommercialError(
                f"BESS_COMMERCIAL_UNSUPPORTED: day_count {self.day_count!r}; only {DAY_COUNT} is "
                "implemented and the convention is an OPEN Financial Owner decision")
        if not isinstance(self.open_decisions, TollingOpenDecisions):
            raise BessCommercialError("BESS_COMMERCIAL_SCHEMA: open_decisions must be TollingOpenDecisions")


@dataclass(frozen=True)
class PerformanceDeduction:
    """A DECLARED deduction with evidence; its size is not derived from availability here."""

    deduction_id: str
    period_id: str
    amount_keur: Decimal
    reason_ref: str

    def __post_init__(self):
        ident(self.deduction_id, "deduction_id")
        ident(self.period_id, "period_id")
        ident(self.reason_ref, "reason_ref")
        dec(self.amount_keur, "deduction amount_keur", nonnegative=True)


@dataclass(frozen=True)
class TollingPeriod:
    """One aligned financial period [start, end)."""

    period_id: str
    start: date
    end: date
    measured_availability: Optional[Decimal]     # None = MISSING evidence; Decimal(0) = measured zero
    deductions: tuple = ()

    def __post_init__(self):
        ident(self.period_id, "period_id")
        if not calendar_date(self.start, "period start") < calendar_date(self.end, "period end"):
            raise BessCommercialError("BESS_COMMERCIAL_TIME: period end must be after start")
        opt_dec(self.measured_availability, "measured_availability", minimum=_ZERO, maximum=_ONE)
        for deduction in tuple_of(self.deductions, "deductions"):
            if not isinstance(deduction, PerformanceDeduction):
                raise BessCommercialError("BESS_COMMERCIAL_SCHEMA: PerformanceDeduction required")
        unique([d.deduction_id for d in self.deductions], "deduction_id")


@dataclass(frozen=True)
class TollingStatement:
    status: str
    reason: str
    contract_id: str
    period_id: str
    in_term_days: int
    period_days: int
    scheduled_fee_keur: Optional[Decimal]
    measured_availability: Optional[Decimal]
    guaranteed_availability: Optional[Decimal]
    availability_shortfall: Optional[Decimal]
    declared_deductions_keur: Optional[Decimal]
    net_fee_keur: Optional[Decimal]


def _overlap_days(contract: TollingContract, period: TollingPeriod) -> int:
    return max(0, (min(contract.end, period.end) - max(contract.start, period.start)).days)


@exact_arithmetic
def tolling_statement(contract: TollingContract, period: TollingPeriod, *,
                      rated_discharge_mw: Optional[Decimal] = None) -> TollingStatement:
    """Availability fee schedule and DECLARED deductions for one period; no penalty formula."""
    require_release()
    if rated_discharge_mw is not None and contract.contracted_capacity_mw > dec(
            rated_discharge_mw, "rated_discharge_mw", positive=True):
        raise BessCommercialError(
            "BESS_COMMERCIAL_ALLOCATION: contracted tolling capacity exceeds the rated discharge power")
    days = (period.end - period.start).days
    in_term = _overlap_days(contract, period)
    base = (contract.contract_id, period.period_id, in_term, days)
    for deduction in period.deductions:
        if deduction.period_id != period.period_id:
            raise BessCommercialError(
                f"BESS_COMMERCIAL_SCHEMA: deduction {deduction.deduction_id!r} belongs to another period")
    if in_term == 0:
        if period.deductions:
            raise BessCommercialError("BESS_COMMERCIAL_TOLLING: deductions declared outside the contract term")
        return TollingStatement(NOT_APPLICABLE, "period outside the contract term", *base,
                                None, period.measured_availability, contract.guaranteed_availability,
                                None, None, None)
    if period.measured_availability is None:
        return TollingStatement(UNAVAILABLE, "measured availability evidence is missing (missing is not zero)",
                                *base, None, None, contract.guaranteed_availability, None, None, None)
    scheduled = (contract.contracted_capacity_mw * contract.availability_fee_eur_mw_year
                 * Decimal(in_term) / Decimal(365) / 1000)
    guaranteed = contract.guaranteed_availability
    shortfall = None if guaranteed is None else max(guaranteed - period.measured_availability, _ZERO)
    declared = sum((d.amount_keur for d in period.deductions), _ZERO)
    if period.deductions:
        if guaranteed is None:
            raise BessCommercialError(
                "BESS_COMMERCIAL_TOLLING: a deduction needs a declared guaranteed availability to be breached")
        if shortfall == 0:
            raise BessCommercialError(
                "BESS_COMMERCIAL_TOLLING: a deduction is declared although measured availability meets the guarantee")
        if declared > scheduled:
            raise BessCommercialError(
                "BESS_COMMERCIAL_TOLLING: declared deductions exceed the scheduled fee; negative fee "
                "treatment is an OPEN Financial Owner decision")
    return TollingStatement(CANDIDATE, "scheduled fee and declared deductions; no penalty formula applied",
                            *base, scheduled, period.measured_availability, guaranteed, shortfall,
                            declared, scheduled - declared)


@exact_arithmetic
def reservation_for_tolling(contract: TollingContract, claim_id: str, start: datetime, end: datetime,
                            direction: Direction = Direction.DISCHARGE_AC) -> ReservationClaim:
    """The CAPACITY_RESERVATION claim a tolling contract places on the battery (MW, no MWh)."""
    require_release()
    term_start = datetime.combine(contract.start, time(), timezone.utc)
    term_end = datetime.combine(contract.end, time(), timezone.utc)
    if start < term_start or end > term_end:
        raise BessCommercialError("BESS_COMMERCIAL_TIME: reservation window lies outside the tolling term")
    return ReservationClaim(claim_id, Service.CAPACITY_RESERVATION, start, end, direction,
                            contract.contracted_capacity_mw, contract.contract_id)
