"""WF-11: additive, strictly non-authoritative OPEX candidate schedule validation.

No persistence, Run path, schema extension or new allocation authority is defined here.
The existing OPEX engine remains the sole source of effective financial amounts.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Iterable
import re

MAX_EVENTS = 60
MAX_HORIZON = 60
MAX_AMOUNT_KEUR = Decimal("1000000000000")
_NUMBER = re.compile(r"(?:0|[1-9][0-9]*)(?:\.[0-9]{1,6})?\Z")
_CODE = re.compile(r"B\.(?:0[1-9]|1[0-2])(?:\.(?:[0-9]{2}|U[0-9]{3}))?\Z")


class OpexProfileError(ValueError):
    """Explicit, fail-closed candidate validation error."""


def positive_amount(value: object) -> Decimal:
    """Finite, nonnegative kEUR value; never silently coerce a text unit."""
    if isinstance(value, bool):
        raise OpexProfileError("AMOUNT_INVALID")
    txt = str(value)
    if not _NUMBER.fullmatch(txt):
        raise OpexProfileError("AMOUNT_INVALID")
    try:
        number = Decimal(txt)
    except InvalidOperation as exc:
        raise OpexProfileError("AMOUNT_INVALID") from exc
    if not number.is_finite() or number < 0 or number > MAX_AMOUNT_KEUR:
        raise OpexProfileError("AMOUNT_INVALID")
    return number


def _positive_int(value: object, *, max_value: int, label: str) -> int:
    if isinstance(value, bool) or not re.fullmatch(r"[1-9][0-9]*", str(value)):
        raise OpexProfileError(label)
    num = int(str(value))
    if not 1 <= num <= max_value:
        raise OpexProfileError(label)
    return num


@dataclass(frozen=True)
class MaintenanceCandidate:
    """One *proposal*, never a canonical effective input or financial event."""
    event_id: str
    owner_line: str
    start_year: int
    amount_keur: Decimal
    recurrence: str = "ONE_OFF"
    interval_years: int | None = None
    classification: str = "UNRESOLVED"
    provenance: str = "USER_PROPOSED"


def validate_maintenance(events: Iterable[MaintenanceCandidate], *, horizon_years: int,
                         eligible_lines: Iterable[str]) -> tuple[MaintenanceCandidate, ...]:
    """Validate identity, owner and horizon without granting accounting approval."""
    horizon = _positive_int(horizon_years, max_value=MAX_HORIZON, label="HORIZON_INVALID")
    owners = set(eligible_lines)
    bounded = tuple(events)
    if len(bounded) > MAX_EVENTS:
        raise OpexProfileError("EVENT_LIMIT")
    identities: set[str] = set()
    occupied: set[tuple[str, int]] = set()
    for e in bounded:
        if (not e.event_id or len(e.event_id) > 64 or not re.fullmatch(r"[A-Za-z0-9_-]+", e.event_id)
                or e.event_id in identities):
            raise OpexProfileError("EVENT_ID_DUPLICATE_OR_INVALID")
        identities.add(e.event_id)
        if not _CODE.fullmatch(e.owner_line) or e.owner_line not in owners:
            raise OpexProfileError("UNKNOWN_OR_DERIVED_OWNER")
        year = _positive_int(e.start_year, max_value=horizon, label="YEAR_OUT_OF_HORIZON")
        positive_amount(e.amount_keur)
        if e.classification not in ("UNRESOLVED", "OPEX_EXPENSE_PROPOSED", "CAPITAL_REPLACEMENT_REVIEW"):
            raise OpexProfileError("CLASSIFICATION_INVALID")
        if e.provenance != "USER_PROPOSED":
            raise OpexProfileError("PROVENANCE_INVALID")
        if e.recurrence == "ONE_OFF":
            if e.interval_years is not None:
                raise OpexProfileError("RECURRENCE_INVALID")
            years = (year,)
        elif e.recurrence == "EVERY_N_YEARS":
            interval = _positive_int(e.interval_years, max_value=horizon, label="RECURRENCE_INVALID")
            years = range(year, horizon + 1, interval)
        else:
            raise OpexProfileError("RECURRENCE_INVALID")
        for occurrence in years:
            identity = (e.owner_line, occurrence)
            if identity in occupied:
                raise OpexProfileError("DOUBLE_COUNTING_RISK_DUPLICATE_EVENT_PERIOD")
            occupied.add(identity)
    return bounded


def maintenance_preview(events: Iterable[MaintenanceCandidate], *, horizon_years: int,
                        eligible_lines: Iterable[str]) -> dict[int, Decimal]:
    """Separate additive *candidate* expense; never folded into canonical annual OPEX."""
    validated = validate_maintenance(events, horizon_years=horizon_years, eligible_lines=eligible_lines)
    totals = {year: Decimal("0") for year in range(1, horizon_years + 1)}
    for e in validated:
        if e.recurrence == "ONE_OFF":
            years = (e.start_year,)
        else:
            years = range(e.start_year, horizon_years + 1, e.interval_years)
        for year in years:
            totals[year] += positive_amount(e.amount_keur)
    return totals


def seasonal_candidate(annual_amount: object, weights: Iterable[object], *,
                       frequency: str = "SEMIANNUAL") -> tuple[Decimal, ...]:
    """Hypothetical FULL-year split; not a period-axis/stub calculation.

    A quarterly preview is not operationally authorized. Caller must present
    it as candidate-only until a separately approved frequency contract exists.
    """
    annual = positive_amount(annual_amount)
    proposed = tuple(positive_amount(w) for w in weights)
    if frequency not in ("SEMIANNUAL", "QUARTERLY_CANDIDATE"):
        raise OpexProfileError("FREQUENCY_UNAUTHORIZED")
    if len(proposed) != (2 if frequency == "SEMIANNUAL" else 4):
        raise OpexProfileError("FREQUENCY_LENGTH_INVALID")
    if sum(proposed) != Decimal("100"):
        raise OpexProfileError("SEASONAL_WEIGHTS_MUST_TOTAL_100")
    allocated = tuple((annual * w / Decimal("100")) for w in proposed)
    if sum(allocated) != annual:
        raise OpexProfileError("SEASONAL_CONSERVATION_FAILED")
    return allocated


AUTHORITY = "CANDIDATE_ONLY_NOT_SAVED_NOT_RUN"
