"""R04 isolated global technical ceiling for simultaneous PPA contracts.  NOT ACTIVE, NOT wired into Save or Run.

Pure, deterministic, exact (``fractions.Fraction``) allocation of PPA delivery volumes against the authoritative technical production of ONE
selected case (P50 / P90-10y / ...). Owner-approved policy implemented here (and nothing else):

* the SUM of committed PPA energy over all overlapping contracts must be <= available generation in EVERY time interval; excess is a typed
  refusal (``GlobalCapExceeded``), never a warning, a truncation or a silent cap-up;
* contracts run for their TRUE date range [start, end) (end exclusive); calendar reporting years are only an aggregation of exact intervals;
* two volume representations that are never interchanged: ``ABSOLUTE_ANNUAL_MWH`` (prorated by days inside each contract anniversary year, so a
  leap year or Feb 29 never invents or drops energy) and ``PERCENT_OF_AVAILABLE`` (a fraction of the available energy of each interval);
* merchant / UNSOLD is only the uncontracted residual; it carries NO price (``price_status`` is EVIDENCE_REQUIRED, never zero-filled);
* the technical availability is an INPUT (segments of authoritative energy with provenance); the module never derives P50 itself, never
  hardcodes a capacity and never assumes a project-independent cap.

Prorating basis (explicit, labeled, never presented as seasonal parity): energy inside one availability segment is spread uniformly over
the segment's calendar days. With monthly segments this is a calendar-day pro-rata WITHIN each month; with annual segments it is the
labeled ``FLAT_DAY_PRORATA_FALLBACK``. Feb 29 anniversaries fall on Feb 28 in non-leap years (an owner-open convention).

Prices, indexation and CfD settlement are NOT computed here: the existing revenue engine remains their only authority.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_EVEN
from fractions import Fraction
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

CONTRACT_VERSION = "R04_GLOBAL_PPA_CAP_V1"
STATUS = {"active": False, "approved_for_finco": False, "wired_into_save_or_run": False}
MWH_PER_GWH = Fraction(1000)

ABSOLUTE_ANNUAL_MWH = "ABSOLUTE_ANNUAL_MWH"
PERCENT_OF_AVAILABLE = "PERCENT_OF_AVAILABLE"
BASES = (ABSOLUTE_ANNUAL_MWH, PERCENT_OF_AVAILABLE)
AVAILABILITY_BASES = ("PERIOD_ENGINE", "MONTHLY_PROFILE", "FLAT_DAY_PRORATA_FALLBACK")
ENERGY_UNITS = {"MWh": Fraction(1), "GWh": MWH_PER_GWH}


class R04Error(ValueError):
    """Typed, fail-closed refusal. ``code`` is stable; the message never contains client or workbook metadata."""

    def __init__(self, code: str, message: str = ""):
        super().__init__(f"{code}: {message}" if message else code)
        self.code = code


class GlobalCapExceeded(R04Error):
    def __init__(self, violations: Sequence["Violation"]):
        first = violations[0]
        super().__init__(
            "GLOBAL_PPA_CAP_EXCEEDED",
            f"{first.start.isoformat()}..{first.end.isoformat()} case={first.case_id} available={_gwh(first.available_mwh)} GWh "
            f"existing={_gwh(first.existing_mwh)} GWh requested={_gwh(first.requested_mwh)} GWh excess={_gwh(first.excess_mwh)} GWh "
            f"max_additional={_gwh(first.max_additional_mwh)} GWh")
        self.violations = tuple(violations)


def _gwh(value: Fraction) -> str:
    return str(to_decimal(value / MWH_PER_GWH))


def to_decimal(value: Fraction, places: int = 6) -> Decimal:
    q = Decimal(1).scaleb(-places)
    return (Decimal(value.numerator) / Decimal(value.denominator)).quantize(q, rounding=ROUND_HALF_EVEN)


def to_fraction(value, label: str = "value") -> Fraction:
    if isinstance(value, bool):
        raise R04Error("MALFORMED_NUMBER", label)
    if isinstance(value, Fraction):
        return value
    try:
        if isinstance(value, float):
            if value != value or value in (float("inf"), float("-inf")):
                raise R04Error("NON_FINITE", label)
            return Fraction(Decimal(repr(value)))
        if isinstance(value, int):
            return Fraction(value)
        dec = value if isinstance(value, Decimal) else Decimal(str(value).strip())
    except (ValueError, ArithmeticError):
        raise R04Error("MALFORMED_NUMBER", label) from None
    if not dec.is_finite():
        raise R04Error("NON_FINITE", label)
    return Fraction(dec)


@dataclass(frozen=True)
class AvailabilitySegment:
    start: date
    end: date            # exclusive
    mwh: Fraction        # authoritative energy available in [start, end)


@dataclass(frozen=True)
class AvailabilitySource:
    """The ONE selected authoritative technical production case for a project and scenario."""

    source_id: str
    project_id: str
    scenario_id: str
    case_id: str
    version: str
    basis: str
    segments: Tuple[AvailabilitySegment, ...]


@dataclass(frozen=True)
class Contract:
    contract_id: str
    start: date          # inclusive
    end: date            # exclusive
    basis: str
    value: Fraction      # MWh per anniversary year, or a fraction in [0, 1]


@dataclass(frozen=True)
class Violation:
    start: date
    end: date
    case_id: str
    available_mwh: Fraction
    existing_mwh: Fraction
    requested_mwh: Fraction
    excess_mwh: Fraction
    max_additional_mwh: Fraction


@dataclass(frozen=True)
class IntervalRow:
    start: date
    end: date
    available_mwh: Fraction
    per_contract_mwh: Mapping[str, Fraction]
    committed_mwh: Fraction
    residual_mwh: Fraction
    residual_status: str = "UNCONTRACTED_RESIDUAL"
    price_status: str = "EVIDENCE_REQUIRED"


@dataclass(frozen=True)
class AllocationReport:
    contract_version: str
    source_id: str
    case_id: str
    availability_basis: str
    intervals: Tuple[IntervalRow, ...]
    calendar_years: Mapping[int, Mapping[str, Fraction]]
    violations: Tuple[Violation, ...]
    status: str            # WITHIN_CAP | OVERSUBSCRIBED


# ------------------------------------------------------------------------------------------------ input parsing
def _date(value, label):
    if isinstance(value, date) and not hasattr(value, "hour"):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        raise R04Error("MALFORMED_DATE", label) from None


def contract_from_mapping(raw: Mapping) -> Contract:
    """Parse one contract; unknown fields, units, representations, reversed or empty windows are refused."""
    allowed = {"id", "start_date", "end_date", "volume"}
    if not isinstance(raw, Mapping) or set(raw) - allowed or allowed - set(raw):
        raise R04Error("MALFORMED_CONTRACT", "exactly id, start_date, end_date, volume")
    cid = raw["id"]
    if not isinstance(cid, str) or not cid.strip() or cid != cid.strip():
        raise R04Error("MALFORMED_CONTRACT_ID")
    start, end = _date(raw["start_date"], "start_date"), _date(raw["end_date"], "end_date")
    if end <= start:
        raise R04Error("REVERSED_OR_EMPTY_WINDOW", cid)
    vol = raw["volume"]
    if not isinstance(vol, Mapping) or set(vol) != {"value", "unit"}:
        raise R04Error("MALFORMED_VOLUME", cid)
    value = to_fraction(vol["value"], "volume")
    if value < 0:
        raise R04Error("NEGATIVE_VALUE", cid)
    unit = vol["unit"]
    if unit in ENERGY_UNITS:
        return Contract(cid, start, end, ABSOLUTE_ANNUAL_MWH, value * ENERGY_UNITS[unit])
    if unit == "PERCENT":
        if value > 100:
            raise R04Error("PERCENT_OUT_OF_RANGE", cid)
        return Contract(cid, start, end, PERCENT_OF_AVAILABLE, value / 100)
    raise R04Error("UNKNOWN_UNIT", f"{cid}: {unit!r} (energy MWh|GWh per year or PERCENT of available generation)")


def validate_source(source: AvailabilitySource) -> None:
    if source.basis not in AVAILABILITY_BASES:
        raise R04Error("UNKNOWN_AVAILABILITY_BASIS", source.basis)
    if not all(isinstance(x, str) and x for x in (source.source_id, source.project_id, source.scenario_id, source.case_id, source.version)):
        raise R04Error("MISSING_SOURCE_IDENTITY")
    if not source.segments:
        raise R04Error("MISSING_TECHNICAL_FORECAST")
    previous = None
    for seg in source.segments:
        if seg.end <= seg.start:
            raise R04Error("REVERSED_OR_EMPTY_SEGMENT")
        if seg.mwh < 0:
            raise R04Error("NEGATIVE_PRODUCTION")
        if previous is not None and seg.start < previous:
            raise R04Error("OVERLAPPING_OR_UNORDERED_SEGMENTS")
        previous = seg.end


def flat_day_prorata_segments(annual_mwh_by_year: Mapping[int, object], start: date, end: date) -> Tuple[AvailabilitySegment, ...]:
    """LABELED FALLBACK (basis FLAT_DAY_PRORATA_FALLBACK): one segment per calendar year, partial first/last years prorated by days."""
    out: List[AvailabilitySegment] = []
    cursor = start
    while cursor < end:
        year_end = min(date(cursor.year + 1, 1, 1), end)
        full_days = (date(cursor.year + 1, 1, 1) - date(cursor.year, 1, 1)).days
        if cursor.year not in annual_mwh_by_year:
            raise R04Error("MISSING_TECHNICAL_FORECAST", str(cursor.year))
        annual = to_fraction(annual_mwh_by_year[cursor.year], "annual_mwh")
        out.append(AvailabilitySegment(cursor, year_end, annual * (year_end - cursor).days / full_days))
        cursor = year_end
    return tuple(out)


# ------------------------------------------------------------------------------------------------ calendar helpers
def _anniversary(anchor: date, k: int) -> date:
    year = anchor.year + k
    try:
        return anchor.replace(year=year)
    except ValueError:                                  # Feb 29 in a non-leap year -> Feb 28
        return date(year, 2, 28)


def _overlap_days(a: date, b: date, c: date, d: date) -> int:
    lo, hi = max(a, c), min(b, d)
    return max(0, (hi - lo).days)


def _available(source: AvailabilitySource, a: date, b: date) -> Fraction:
    total = Fraction(0)
    for seg in source.segments:
        days = _overlap_days(a, b, seg.start, seg.end)
        if days:
            total += seg.mwh * days / (seg.end - seg.start).days
    return total


def _covered(source: AvailabilitySource, a: date, b: date) -> bool:
    return sum(_overlap_days(a, b, s.start, s.end) for s in source.segments) == (b - a).days


def _absolute_energy(contract: Contract, a: date, b: date) -> Fraction:
    total, k = Fraction(0), 0
    while True:
        lo, hi = _anniversary(contract.start, k), _anniversary(contract.start, k + 1)
        if lo >= b:
            break
        days = _overlap_days(a, b, lo, hi)
        if days:
            total += contract.value * days / (hi - lo).days
        k += 1
    return total


def _breakpoints(source: AvailabilitySource, contracts: Sequence[Contract]) -> List[date]:
    pts = set()
    for c in contracts:
        pts.update((c.start, c.end))
        k = 1
        while _anniversary(c.start, k) < c.end:
            pts.add(_anniversary(c.start, k))
            k += 1
    for seg in source.segments:
        pts.update((seg.start, seg.end))
    lo, hi = min(c.start for c in contracts), max(c.end for c in contracts)
    for year in range(lo.year, hi.year + 1):
        pts.add(date(year, 1, 1))
    return sorted(p for p in pts if lo <= p <= hi)


# ------------------------------------------------------------------------------------------------ the allocation
def allocate(source: AvailabilitySource, contracts: Sequence[Contract], *, expected_project_id: Optional[str] = None,
             expected_case_id: Optional[str] = None, candidate: Optional[Contract] = None, raise_on_violation: bool = True,
             rel_tolerance: Fraction = Fraction(0)) -> AllocationReport:
    """Validate the whole contract book (plus an optional ``candidate`` being saved) against the technical ceiling of every interval.

    ``rel_tolerance`` (default EXACT zero) only exists for float64-derived availability: an adapter that converts the released engine's floats may
    pass an explicit, documented relative tolerance (for example 1e-9); it never widens a breach larger than that.

    The result never depends on contract order. Existing committed energy in a violation is the book WITHOUT the candidate when a candidate
    is supplied (so ``max_additional`` is what that candidate could still be granted); otherwise it is the book minus the excess.
    """
    validate_source(source)
    if expected_project_id is not None and source.project_id != expected_project_id:
        raise R04Error("WRONG_PROJECT")
    if expected_case_id is not None and source.case_id != expected_case_id:
        raise R04Error("WRONG_TECHNICAL_CASE", f"selected {expected_case_id!r}, source is {source.case_id!r}")
    book = list(contracts) + ([candidate] if candidate is not None else [])
    ids = [c.contract_id for c in book]
    if len(set(ids)) != len(ids):
        raise R04Error("DUPLICATE_CONTRACT_ID")
    for c in book:
        if c.basis not in BASES:
            raise R04Error("UNKNOWN_VOLUME_BASIS", c.contract_id)
        if c.end <= c.start:
            raise R04Error("REVERSED_OR_EMPTY_WINDOW", c.contract_id)
        if c.value < 0 or (c.basis == PERCENT_OF_AVAILABLE and c.value > 1):
            raise R04Error("NEGATIVE_VALUE" if c.value < 0 else "PERCENT_OUT_OF_RANGE", c.contract_id)
    if not book:
        return AllocationReport(CONTRACT_VERSION, source.source_id, source.case_id, source.basis, (), {}, (), "WITHIN_CAP")
    rows: List[IntervalRow] = []
    violations: List[Violation] = []
    points = _breakpoints(source, book)
    for a, b in zip(points, points[1:]):
        active = [c for c in book if c.start < b and c.end > a]
        if not active:
            continue
        if not _covered(source, a, b):
            raise R04Error("OUTSIDE_TECHNICAL_HORIZON", f"{a.isoformat()}..{b.isoformat()} case={source.case_id}")
        available = _available(source, a, b)
        per = {c.contract_id: (_absolute_energy(c, a, b) if c.basis == ABSOLUTE_ANNUAL_MWH else c.value * available) for c in active}
        committed = sum(per.values(), Fraction(0))
        if committed > available * (1 + rel_tolerance):
            if candidate is not None:
                existing = sum((v for k, v in per.items() if k != candidate.contract_id), Fraction(0))
                requested = per.get(candidate.contract_id, Fraction(0))
            else:
                existing, requested = committed, Fraction(0)
            violations.append(Violation(a, b, source.case_id, available, existing, requested, committed - available,
                                        max(Fraction(0), available - existing) if candidate is not None else Fraction(0)))
        rows.append(IntervalRow(a, b, available, dict(sorted(per.items())), committed, available - committed))
    years: Dict[int, Dict[str, Fraction]] = {}
    for row in rows:
        y = years.setdefault(row.start.year, {"available_mwh": Fraction(0), "committed_mwh": Fraction(0), "residual_mwh": Fraction(0)})
        y["available_mwh"] += row.available_mwh
        y["committed_mwh"] += row.committed_mwh
        y["residual_mwh"] += row.residual_mwh
        for cid, v in row.per_contract_mwh.items():
            y[cid] = y.get(cid, Fraction(0)) + v
    report = AllocationReport(CONTRACT_VERSION, source.source_id, source.case_id, source.basis, tuple(rows),
                              {k: dict(v) for k, v in sorted(years.items())}, tuple(violations),
                              "OVERSUBSCRIBED" if violations else "WITHIN_CAP")
    if violations and raise_on_violation:
        raise GlobalCapExceeded(violations)
    return report


def check_new_contract(source: AvailabilitySource, existing: Sequence[Contract], candidate: Contract, **kw) -> AllocationReport:
    """The write-boundary question: does adding ``candidate`` to ``existing`` keep every interval within the ceiling? Atomic, no mutation."""
    return allocate(source, existing, candidate=candidate, **kw)


def headroom(source: AvailabilitySource, existing: Sequence[Contract], start: date, end: date) -> Tuple[IntervalRow, ...]:
    """Year-by-year (calendar-year-split) remaining energy over [start, end): ``residual_mwh`` is the most any new contract could add there."""
    probe = Contract("__probe__", start, end, PERCENT_OF_AVAILABLE, Fraction(0))
    report = allocate(source, existing, candidate=probe, raise_on_violation=False)
    return tuple(r for r in report.intervals if r.start >= start and r.end <= end)
