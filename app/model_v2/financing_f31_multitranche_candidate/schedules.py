"""Candidate N-tranche facility schedules — released math, plain inputs.

Mirrors the released two-Senior schedule math
(``financial_engine/financing/multisenior.build_facility_schedules``) rule
for rule, on PLAIN date inputs (no ``ProjectInputs``, no engine import) so
the candidate stays non-authoritative and import-isolated. The N=2
equivalence property test proves byte-level agreement (1e-9) with the
released engine on identical fixtures; for N >= 3 no released authority
exists and this candidate math is the design proposal.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from math import fsum
from typing import Optional, Sequence

from dateutil.relativedelta import relativedelta

from finco_core.inputs.financing_instruments import (
    FinancingCollection,
    FinancingError,
    FinancingInstrument,
)

TOLERANCE_KEUR = 1e-7

_ACT_DENOMINATORS = {"act_365": 365.0, "act_360": 360.0}


def _check_day_count(day_count: str) -> str:
    if day_count not in _ACT_DENOMINATORS:
        raise FinancingError("F3_DAY_COUNT_UNSUPPORTED", day_count)
    return day_count


def period_day_fraction(start: date, end_exclusive: date, day_count: str) -> float:
    """Released ACT primitive (exclusive end): days / 365 or days / 360."""
    denominator = _ACT_DENOMINATORS[_check_day_count(day_count)]
    return (end_exclusive - start).days / denominator


def period_interest(opening_keur: float, annual_rate: float, fraction: float) -> float:
    """Released primitive: opening balance x annual rate x day fraction."""
    return opening_keur * annual_rate * fraction


@dataclass(frozen=True)
class CandidatePeriod:
    """Plain canonical period evidence (dates only — axis-agnostic)."""

    period_index: int
    start: date
    end: date
    is_operation: bool


@dataclass(frozen=True)
class CandidateFacilitySchedule:
    """One tranche's contractual ledger — released FacilitySchedule shape."""

    instrument_id: str
    commitment_keur: float
    maturity_period_index: int
    period_indices: tuple[int, ...]
    opening_keur: tuple[float, ...]
    interest_keur: tuple[float, ...]
    principal_keur: tuple[float, ...]
    debt_service_keur: tuple[float, ...]
    closing_keur: tuple[float, ...]
    construction_draws_keur: tuple[float, ...]
    construction_idc_keur: tuple[float, ...]
    construction_commitment_fees_keur: tuple[float, ...]
    upfront_fees_keur: tuple[float, ...]


def _maturity_index(instrument: FinancingInstrument,
                    operating: Sequence[CandidatePeriod]) -> int:
    matching = [p for p in operating
                if p.end == instrument.repayment.maturity_date]
    if len(matching) != 1:
        raise FinancingError(
            "F3_MATURITY_NOT_ON_OPERATING_BOUNDARY", instrument.instrument_id)
    return matching[0].period_index


def _level_principal_map(instrument: FinancingInstrument, indices: tuple[int, ...],
                         repayment_start: int, maturity: int) -> dict[int, float]:
    """Released build_level_principal_schedule principal map (pre-interest)."""
    repayment = [i for i in indices if repayment_start <= i <= maturity]
    if not repayment:
        raise FinancingError("F3_GRACE_EXCEEDS_MATURITY", instrument.instrument_id)
    level = instrument.commitment_keur / len(repayment)
    principal, balance = {}, instrument.commitment_keur
    for idx in indices:
        if idx in set(repayment) and balance > 0.0:
            amount = min(level, balance)
        else:
            amount = 0.0
        principal[idx] = amount
        balance -= amount
    return principal


def _bullet_principal_map(instrument: FinancingInstrument, maturity: int) -> dict[int, float]:
    return {maturity: instrument.commitment_keur}


def _operating_rows(instrument: FinancingInstrument, indices: tuple[int, ...],
                    operating_by_index: dict[int, CandidatePeriod],
                    principal_by_period: dict[int, float],
                    day_count: str) -> tuple[dict[int, float], dict[int, tuple[float, ...]]]:
    """Released two-pass roll: principal plan -> interest on that profile."""
    # Pass 1: opening profile under the principal plan alone (no interest).
    opening_by_period, balance = {}, instrument.commitment_keur
    for idx in indices:
        opening_by_period[idx] = balance
        balance -= principal_by_period.get(idx, 0.0)
    # Pass 2: contractual fixed cash interest on that opening profile.
    interest = {
        idx: period_interest(
            opening_by_period[idx], instrument.interest.fixed_rate,
            period_day_fraction(
                operating_by_index[idx].start, operating_by_index[idx].end,
                day_count))
        for idx in indices
    }
    # Final roll: interest + explicit principal, capped at balance.
    rows, balance = {}, instrument.commitment_keur
    for idx in indices:
        amount = min(max(0.0, principal_by_period.get(idx, 0.0)), balance)
        rows[idx] = (balance, interest[idx], amount, interest[idx] + amount,
                     balance - amount)
        balance -= amount
    return interest, rows


def build_candidate_facility_schedules(
    collection: FinancingCollection,
    construction_periods: Sequence[tuple[date, date]],
    operating_periods: Sequence[CandidatePeriod],
    *,
    day_count: str,
) -> tuple[CandidateFacilitySchedule, ...]:
    """One contractual ledger per tranche (N >= 2), released math mirrored."""
    _check_day_count(day_count)
    # Released API shape: the caller passes the full canonical period list;
    # the operating axis is filtered here exactly like the released engine.
    operating = tuple(p for p in operating_periods if p.is_operation)
    if not operating:
        raise FinancingError("F3_OPERATING_AXIS_MISSING")
    operating_by_index = {p.period_index: p for p in operating}
    first_start = operating[0].start
    schedules = []
    for instrument in collection.ordered():
        maturity = _maturity_index(instrument, operating)
        debt_periods = tuple(p for p in operating if p.period_index <= maturity)
        indices = tuple(p.period_index for p in debt_periods)
        grace_end = first_start + relativedelta(
            months=instrument.repayment.grace_months)
        eligible = [p for p in debt_periods if p.start >= grace_end]
        if not eligible:
            raise FinancingError(
                "F3_GRACE_EXCEEDS_MATURITY", instrument.instrument_id)
        if instrument.repayment.mode.value == "LEVEL_PRINCIPAL":
            principal = _level_principal_map(
                instrument, indices, eligible[0].period_index, maturity)
        else:
            principal = _bullet_principal_map(instrument, maturity)
        interest, rows = _operating_rows(
            instrument, indices, operating_by_index, principal, day_count)
        if abs(rows[maturity][4]) > TOLERANCE_KEUR:
            raise FinancingError(
                "F3_FACILITY_MATURITY_UNSETTLED", instrument.instrument_id)
        draws, idc, fees, upfront = [], [], [], []
        opening = 0.0
        mapped_dates = set()
        commitment_rate = next(
            (f.rate for f in instrument.fees if f.kind == "COMMITMENT"), 0.0)
        upfront_total = fsum(
            f.rate * instrument.commitment_keur
            for f in instrument.fees if f.kind == "UPFRONT")
        for i, (start, end) in enumerate(construction_periods):
            end_exclusive = end + timedelta(days=1)
            entries = [d for d in instrument.drawdowns
                       if start <= d.draw_date < end_exclusive]
            mapped_dates.update(d.draw_date for d in entries)
            drawn = fsum(d.amount_keur for d in entries)
            span = period_day_fraction(start, end_exclusive, day_count)
            # Each dated cash draw accrues from its own date, never the whole
            # period by an averaged construction rate or funding-profile replay.
            accrued = period_interest(opening, instrument.interest.fixed_rate, span) + fsum(
                period_interest(d.amount_keur, instrument.interest.fixed_rate,
                                period_day_fraction(d.draw_date, end_exclusive, day_count))
                for d in entries)
            undrawn_integral = (
                (instrument.commitment_keur - opening) * span
                - fsum(d.amount_keur * period_day_fraction(
                    d.draw_date, end_exclusive, day_count) for d in entries))
            draws.append(drawn)
            idc.append(accrued)
            fees.append(commitment_rate * undrawn_integral)
            upfront.append(upfront_total if i == 0 else 0.0)
            opening += drawn
        if mapped_dates != {d.draw_date for d in instrument.drawdowns}:
            raise FinancingError(
                "F3_DRAW_OUTSIDE_CONSTRUCTION", instrument.instrument_id)
        schedules.append(CandidateFacilitySchedule(
            instrument_id=instrument.instrument_id,
            commitment_keur=instrument.commitment_keur,
            maturity_period_index=maturity,
            period_indices=indices,
            opening_keur=tuple(rows[i][0] for i in indices),
            interest_keur=tuple(rows[i][1] for i in indices),
            principal_keur=tuple(rows[i][2] for i in indices),
            debt_service_keur=tuple(rows[i][3] for i in indices),
            closing_keur=tuple(rows[i][4] for i in indices),
            construction_draws_keur=tuple(draws),
            construction_idc_keur=tuple(idc),
            construction_commitment_fees_keur=tuple(fees),
            upfront_fees_keur=tuple(upfront),
        ))
    return tuple(schedules)


def build_candidate_aggregate(
    facilities: Sequence[CandidateFacilitySchedule],
) -> dict[int, dict[str, float]]:
    """Aggregate ledgers: per operating period, sums across all tranches.

    Released invariant: aggregate interest/principal/debt service/closing ==
    the sum of the facility ledgers (handshake authority in the released
    path). Tranches with different maturities simply drop out of the sums
    after their own maturity.
    """
    aggregate: dict[int, dict[str, float]] = {}
    for facility in facilities:
        for position, idx in enumerate(facility.period_indices):
            bucket = aggregate.setdefault(
                idx, {"opening": 0.0, "interest": 0.0, "principal": 0.0,
                      "debt_service": 0.0, "closing": 0.0})
            bucket["opening"] = fsum((
                bucket["opening"], facility.opening_keur[position]))
            bucket["interest"] = fsum((
                bucket["interest"], facility.interest_keur[position]))
            bucket["principal"] = fsum((
                bucket["principal"], facility.principal_keur[position]))
            bucket["debt_service"] = fsum((
                bucket["debt_service"], facility.debt_service_keur[position]))
            bucket["closing"] = fsum((
                bucket["closing"], facility.closing_keur[position]))
    return aggregate


def latest_maturity_period(facilities: Sequence[CandidateFacilitySchedule]) -> int:
    """The aggregate senior maturity = the latest tranche maturity."""
    return max(f.maturity_period_index for f in facilities)


def optional_total(*values: Optional[float]) -> Optional[float]:
    """None-safe sum used by reconciliation inputs."""
    if any(v is None for v in values):
        return None
    return fsum(v for v in values if v is not None)
