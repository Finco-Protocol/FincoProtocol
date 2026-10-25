"""Generation Losses & Pre-COD candidate — pure calculation helpers.

RELEASE-CLOSED: every public function calls ``require_release()`` and the
package is never imported by production. All helpers are deterministic,
side-effect free and unit-explicit (MWh, EUR, EUR/MWh; percentages 0..100
where a name says ``_pct``). MISSING evidence yields a typed ``None`` or a
typed error — never a fabricated zero.

Canonical date semantics: helpers consume exact ``datetime.date`` values
and declared day/hour counts. Tests drive them with canonical
``PeriodEngine`` periods (Jun 30 / Dec 31 boundaries, COD stubs) and the
monthly construction grid WITHOUT changing released periodisation.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Mapping, Optional, Sequence, Tuple

_ONE_DAY = timedelta(days=1)

from app.generation_v2_candidate.contracts import (
    ACTIVATION_ENABLED,
    DegradationOnset,
    FirstYearAvailability,
    PreCodCommissioning,
    TransmissionLossFactor,
    VolumeAdjustmentEvent,
    require_month_aligned,
    require_release,
    validate_no_event_overlaps,
)

activation_enabled = lambda: ACTIVATION_ENABLED  # noqa: E731


def _fail(code: str, message: str) -> ValueError:
    return ValueError(f"{code}: {message}")


def _num(value, label: str, *, minimum: Optional[float] = None,
         maximum: Optional[float] = None, exclusive_min: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) \
            or not math.isfinite(float(value)):
        raise _fail("GENERATION_V2_VALUE",
                    f"{label} must be a finite number, got {value!r}")
    v = float(value)
    if minimum is not None:
        if exclusive_min and v <= minimum:
            raise _fail("GENERATION_V2_VALUE",
                        f"{label} must be strictly above {minimum}")
        if not exclusive_min and v < minimum:
            raise _fail("GENERATION_V2_VALUE",
                        f"{label} must be at least {minimum}")
    if maximum is not None and v > maximum:
        raise _fail("GENERATION_V2_VALUE",
                    f"{label} must be at most {maximum}")
    return v


def _energy(value, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) \
            or not math.isfinite(float(value)) or float(value) < 0:
        raise _fail("GENERATION_V2_VALUE",
                    f"{label} must be finite non-negative energy (MWh), got "
                    f"{value!r}")
    return float(value)


# ── A. Transmission loss application ─────────────────────────────────────────


@dataclass(frozen=True)
class TransmissionSplit:
    """Exact gross → delivered + loss split for one evaluation date.

    Invariant (exact, by construction): ``delivered_mwh + loss_mwh ==
    gross_mwh`` — the loss is computed first (``gross × factor``) and the
    delivered quantity is the remainder, never two independent roundings."""

    gross_mwh: float
    delivered_mwh: float
    loss_mwh: float
    loss_factor: float
    on_date: date


def apply_transmission_loss(
    factor: TransmissionLossFactor,
    gross_mwh: float,
    on_date: date,
) -> Optional[TransmissionSplit]:
    """Apply the transmission loss factor valid on one exact date.

    Returns ``None`` when a DATED_SERIES does not cover the date (typed
    UNAVAILABLE at the caller — never an implicit factor of zero). FLAT
    factors cover every date. A zero-energy split is a legitimate ZERO;
    missing coverage is the only UNAVAILABLE path."""
    require_release()
    factor_obj = factor.factor_on(on_date)
    if factor_obj is None:
        return None
    gross = _energy(gross_mwh, "gross_mwh")
    loss = gross * factor_obj
    delivered = gross - loss
    return TransmissionSplit(
        gross_mwh=gross,
        delivered_mwh=delivered,
        loss_mwh=loss,
        loss_factor=factor_obj,
        on_date=on_date,
    )


@dataclass(frozen=True)
class SubperiodGeneration:
    """Independently evidenced gross generation for an inclusive day span
    INSIDE one operating period (e.g. metered generation before and after a
    loss-factor change). It is evidence supplied by the caller; this package
    never derives it by prorating the period total over days."""

    first_day: date
    last_day: date
    gross_mwh: float


@dataclass(frozen=True)
class PeriodLossOutcome:
    """Transmission outcome for one inclusive-day operating period.

    ``basis`` is ``UNIFORM_FACTOR`` (one factor provably applies to every day
    of the period) or ``SUBPERIOD_EVIDENCE`` (the factor changes inside the
    period and the split follows independently evidenced sub-period
    generation). ``splits`` are the exact gross -> delivered + loss rows."""

    first_day: date
    last_day: date
    gross_mwh: float
    delivered_mwh: float
    loss_mwh: float
    basis: str
    splits: Tuple[TransmissionSplit, ...]


def _check_span(first_day, last_day, label: str) -> None:
    if not isinstance(first_day, date) or not isinstance(last_day, date):
        raise _fail("GENERATION_V2_SCHEMA", f"{label} requires date first_day/last_day")
    if last_day < first_day:
        raise _fail("GENERATION_V2_VALUE",
                    f"{label} last_day ({last_day}) precedes first_day ({first_day})")


def _split_uniform(factor: TransmissionLossFactor, first_day: date,
                   last_day: date, gross: float) -> TransmissionSplit:
    span = factor.factor_over(first_day, last_day)
    if span.status == "UNCOVERED":
        raise _fail(
            "GENERATION_V2_UNAVAILABLE",
            f"no transmission loss factor covers {first_day}..{last_day}; a "
            "dated series must cover every evaluated period (gaps never "
            "pass energy through unadjusted)")
    if span.status == "VARIES":
        raise _fail(
            "GENERATION_V2_UNAVAILABLE",
            f"the transmission loss factor changes on "
            f"{', '.join(d.isoformat() for d in span.change_dates)} inside "
            f"{first_day}..{last_day}")
    loss = gross * span.factor
    return TransmissionSplit(gross_mwh=gross, delivered_mwh=gross - loss,
                             loss_mwh=loss, loss_factor=span.factor,
                             on_date=last_day)


def _evidenced_subperiods(factor, first_day, last_day, gross, evidence):
    """Validate independently evidenced sub-period generation for a period
    whose factor changes inside it; return one exact split per sub-period."""
    parts = tuple(evidence)
    if not parts or not all(isinstance(p, SubperiodGeneration) for p in parts):
        raise _fail("GENERATION_V2_SCHEMA",
                    "sub-period evidence must be SubperiodGeneration rows")
    # 1. geometry first: the sub-periods must tile [first_day, last_day] exactly
    expected_start = first_day
    for part in parts:
        _check_span(part.first_day, part.last_day, "sub-period")
        if part.first_day != expected_start:
            raise _fail(
                "GENERATION_V2_OVERLAP" if part.first_day < expected_start
                else "GENERATION_V2_UNAVAILABLE",
                f"sub-period evidence must tile {first_day}..{last_day} "
                f"exactly; expected a sub-period starting {expected_start}, "
                f"got {part.first_day}")
        expected_start = part.last_day + _ONE_DAY
    if expected_start != last_day + _ONE_DAY:
        raise _fail("GENERATION_V2_UNAVAILABLE",
                    f"sub-period evidence ends before {last_day}; every day of "
                    "the period needs evidenced generation")
    # 2. each sub-period needs one provable factor; amounts must reconcile
    splits, total = [], 0.0
    for part in parts:
        sub_gross = _energy(part.gross_mwh, f"sub-period gross_mwh[{part.first_day}]")
        splits.append(_split_uniform(factor, part.first_day, part.last_day, sub_gross))
        total += sub_gross
    if abs(total - gross) > 1e-9 * max(1.0, abs(gross)):
        raise _fail(
            "GENERATION_V2_VALUE",
            f"sub-period generation ({total}) does not reconcile with the "
            f"period gross ({gross})")
    return tuple(splits)


def apply_transmission_loss_to_spans(
    factor: TransmissionLossFactor,
    spans: Sequence[Tuple[date, date, float]],
    *,
    subperiod_evidence: Optional[Mapping[Tuple[date, date], Sequence[SubperiodGeneration]]] = None,
) -> Tuple[PeriodLossOutcome, ...]:
    """Apply the transmission loss factor to inclusive-day operating periods.

    ``spans`` are ``(first_day, last_day, gross_mwh)`` rows (``last_day`` is
    the canonical period end; convert a released row ``(start, end]`` to
    ``start + 1 day .. end``, and a COD stub that includes its start day to
    ``start .. end``). The factor must be PROVABLY uniform over every day of
    the span:

    - uniform -> one exact split at that factor;
    - uncovered -> typed UNAVAILABLE (gaps never pass energy unadjusted);
    - the factor changes inside the period -> the split follows
      ``subperiod_evidence[(first_day, last_day)]``, independently evidenced
      sub-period generation that tiles the period and reconciles with its
      gross; without it the period fails closed. The period total is NEVER
      prorated over days and the last day's factor is NEVER applied to the
      whole period (allocation of generation across a factor change is
      OWNER DECISION D-09).

    Conservation holds per sub-period, per period and in total."""
    require_release()
    evidence = subperiod_evidence or {}
    rows = tuple(spans)
    for row in rows:
        if not isinstance(row, tuple) or len(row) != 3:
            raise _fail("GENERATION_V2_SCHEMA",
                        "spans rows must be (first_day, last_day, gross_mwh)")
        _check_span(row[0], row[1], "period")
    ordered = sorted(rows, key=lambda r: (r[0], r[1]))
    for earlier, later in zip(ordered, ordered[1:]):
        if later[0] <= earlier[1]:
            raise _fail("GENERATION_V2_OVERLAP",
                        f"period {later[0]}..{later[1]} overlaps period "
                        f"{earlier[0]}..{earlier[1]}; one day can carry only "
                        "one period's energy")
    outcomes = []
    total_gross = 0.0
    for first_day, last_day, gross in rows:
        gross = _energy(gross, f"gross_mwh[{first_day}..{last_day}]")
        total_gross += gross
        status = factor.factor_over(first_day, last_day).status
        if status == "VARIES":
            given = evidence.get((first_day, last_day))
            if given is None:
                change = factor.factor_over(first_day, last_day).change_dates
                raise _fail(
                    "GENERATION_V2_UNAVAILABLE",
                    f"the transmission loss factor changes on "
                    f"{', '.join(d.isoformat() for d in change)} inside the "
                    f"period {first_day}..{last_day}; independently evidenced "
                    "sub-period generation is required and no proration or "
                    "last-day factor is applied (OWNER DECISION REQUIRED, D-09)")
            splits = _evidenced_subperiods(factor, first_day, last_day, gross, given)
            basis = "SUBPERIOD_EVIDENCE"
        else:
            splits = (_split_uniform(factor, first_day, last_day, gross),)
            basis = "UNIFORM_FACTOR"
        outcomes.append(PeriodLossOutcome(
            first_day=first_day, last_day=last_day, gross_mwh=gross,
            delivered_mwh=sum(x.delivered_mwh for x in splits),
            loss_mwh=sum(x.loss_mwh for x in splits), basis=basis, splits=splits))
    total_loss = sum(o.loss_mwh for o in outcomes)
    total_delivered = sum(o.delivered_mwh for o in outcomes)
    if abs((total_delivered + total_loss) - total_gross) > 1e-9 * max(1.0, abs(total_gross)):
        raise _fail("GENERATION_V2_VALUE", "transmission conservation identity broken")
    return tuple(outcomes)


def apply_transmission_loss_to_periods(
    factor: TransmissionLossFactor,
    periods: Sequence[Tuple],
    *,
    subperiod_evidence: Optional[Mapping[Tuple[date, date], Sequence[SubperiodGeneration]]] = None,
) -> Tuple[Tuple[date, float, float], ...]:
    """Apply the factor to period rows; returns ``(period_end, delivered_mwh,
    loss_mwh)`` rows (conservation per row and in total).

    Rows are ``(first_day, last_day, gross_mwh)`` (see
    :func:`apply_transmission_loss_to_spans`) or, for a FLAT factor only,
    ``(period_end, gross_mwh)``. A DATED_SERIES cannot be applied from a
    period end alone: one date cannot show that a single factor applies to
    the whole period, so a two-field row with a dated series fails closed
    instead of silently using the last day's factor for the entire period."""
    require_release()
    rows = []
    for row in periods:
        if isinstance(row, tuple) and len(row) == 2:
            if factor.mode != "FLAT":
                raise _fail(
                    "GENERATION_V2_SCHEMA",
                    "a DATED_SERIES loss factor needs (first_day, last_day, "
                    "gross_mwh) rows: a period end date alone cannot show "
                    "that one factor applies to the whole period")
            period_end, gross = row
            rows.append((period_end, period_end, gross))
        else:
            rows.append(row)
    outcomes = apply_transmission_loss_to_spans(
        factor, rows, subperiod_evidence=subperiod_evidence)
    return tuple((o.last_day, o.delivered_mwh, o.loss_mwh) for o in outcomes)


# ── B/C. Canonical-shape operating adjustments ───────────────────────────────


@dataclass(frozen=True)
class OperatingPeriodAdjustments:
    """One operating period's candidate adjustment factors.

    ``availability`` is single-sourced (first-year vs normal by operating
    year index); ``degradation_factor`` follows the explicit onset; the
    transmission ``loss_factor`` (None = the factor config does not cover
    the period boundary — typed UNAVAILABLE upstream). The composed
    multiplier applies each mechanism EXACTLY ONCE."""

    period_index: int
    operating_year_index: int
    availability: float
    degradation_factor: float
    loss_factor: Optional[float]
    loss_state: str = "UNIFORM"


def compose_operating_adjustments(
    *,
    period_index: int,
    operating_year_index: int,
    on_date: date,
    degradation: DegradationOnset,
    availability: FirstYearAvailability,
    transmission_loss: TransmissionLossFactor,
    period_first_day: Optional[date] = None,
) -> OperatingPeriodAdjustments:
    """Compose the candidate adjustments for one canonical operating period.

    Each mechanism is applied exactly once: degradation onset (explicit),
    availability (single-sourced by operating year), transmission loss
    (evaluated at the period's canonical boundary date; ``None`` when the
    dated series does not cover it). No double application is possible by
    construction — the factors are independent dimensions."""
    require_release()
    degradation.validate()
    availability.validate()
    if not isinstance(period_index, int) or isinstance(period_index, bool) \
            or period_index < 0:
        raise _fail("GENERATION_V2_VALUE",
                    "period_index must be a non-negative integer")
    # ``on_date`` is the period's last day. A FLAT factor is uniform by
    # definition. A DATED_SERIES factor is reported only when it provably
    # applies to every day [period_first_day, on_date]; otherwise loss_factor
    # stays None (typed UNAVAILABLE upstream) with an explicit loss_state —
    # the factor on the last day is never used for a whole period.
    if transmission_loss.mode == "FLAT":
        loss_factor, loss_state = transmission_loss.flat_factor, "UNIFORM"
    elif period_first_day is None:
        loss_factor, loss_state = None, "SPAN_NOT_SUPPLIED"
    else:
        span = transmission_loss.factor_over(period_first_day, on_date)
        loss_factor = span.factor if span.status == "UNIFORM" else None
        loss_state = {"UNIFORM": "UNIFORM", "UNCOVERED": "UNCOVERED",
                      "VARIES": "VARIES_WITHIN_PERIOD"}[span.status]
    return OperatingPeriodAdjustments(
        period_index=period_index,
        operating_year_index=operating_year_index,
        availability=availability.availability_for(operating_year_index),
        degradation_factor=degradation.factor_for(operating_year_index),
        loss_factor=loss_factor,
        loss_state=loss_state,
    )


# ── D. Volume adjustment events ──────────────────────────────────────────────


@dataclass(frozen=True)
class EventAttribution:
    """The deduction of one event on one period (per-event attribution)."""

    event_id: str
    affected_mwh: float
    lost_mwh: float
    overlap_days: int
    period_days: int


@dataclass(frozen=True)
class VolumeAdjustmentOutcome:
    """Result of applying non-overlapping events to one period's energy.

    ``net_mwh + total_lost_mwh == gross_mwh`` (exact conservation of the
    physical adjustment). ``compensated_mwh`` and ``compensation_eur`` are
    CASH-side only: they never enter ``net_mwh``. ``unavailable_compensation``
    marks MWh whose compensation needs merchant market evidence that is
    missing (UNAVAILABLE — never a fabricated zero)."""

    gross_mwh: float
    net_mwh: float
    total_lost_mwh: float
    attributions: Tuple[EventAttribution, ...]
    compensated_mwh: float
    compensation_eur: Optional[Decimal]
    unavailable_compensation_mwh: float


def overlap_days(
    period_start: date, period_end: date,
    valid_from: date, valid_until: date,
) -> int:
    """Exact day count of the intersection of a period and an event window.

    ``period_end`` is inclusive (a canonical period covers its end date);
    ``valid_until`` is exclusive (event vocabulary). Zero when disjoint.
    Deterministic day-count proration; no hour-level interpolation."""
    require_release()
    if period_end < period_start:
        raise _fail("GENERATION_V2_VALUE", "period_end precedes period_start")
    if valid_until <= valid_from:
        raise _fail("GENERATION_V2_VALUE", "valid_until precedes valid_from")
    last_inclusive = min(period_end, valid_until - _ONE_DAY)
    first = max(period_start, valid_from)
    if last_inclusive < first:
        return 0
    return (last_inclusive - first).days + 1


def period_days_inclusive(period_start: date, period_end: date) -> int:
    require_release()
    if period_end < period_start:
        raise _fail("GENERATION_V2_VALUE",
                    "period_end precedes period_start")
    return (period_end - period_start).days + 1


def apply_volume_adjustments(
    gross_mwh: float,
    period_start: date,
    period_end: date,
    events: Sequence[VolumeAdjustmentEvent],
    *,
    merchant_prices: Optional[Mapping[date, float]] = None,
) -> VolumeAdjustmentOutcome:
    """Apply non-overlapping named events to one period's gross energy.

    Deterministic attribution: each event's affected energy is
    ``gross × overlap_fraction × energy_loss_pct/100`` where
    ``overlap_fraction`` is the exact day-count intersection over the
    period's day count. Because windows never overlap (validated here
    again), every date is attributed to at most one event and the total
    deduction can never exceed the gross energy: a sum of attributions
    above ``gross`` fails closed instead of silently over-deducting.

    Compensation: CONTRACTED events settle at their explicit price;
    MERCHANT events settle at ``merchant_prices`` for the event's first
    affected day — a missing price makes that event's compensation
    UNAVAILABLE (tracked separately, never zero). Compensation changes
    cash only: ``net_mwh`` is independent of it."""
    require_release()
    gross = _energy(gross_mwh, "gross_mwh")
    ordered = validate_no_event_overlaps(tuple(events))
    p_days = period_days_inclusive(period_start, period_end)
    attributions = []
    total_lost = 0.0
    compensated_mwh = 0.0
    unavailable_mwh = 0.0
    compensation_total = Decimal(0)
    any_unavailable = False
    for event in ordered:
        o_days = overlap_days(period_start, period_end,
                              event.valid_from, event.valid_until)
        if o_days <= 0:
            continue
        fraction = o_days / p_days
        affected = gross * fraction
        lost = affected * (event.energy_loss_pct / 100.0)
        attributions.append(EventAttribution(
            event_id=event.event_id,
            affected_mwh=affected,
            lost_mwh=lost,
            overlap_days=o_days,
            period_days=p_days,
        ))
        total_lost += lost
        if event.compensation_basis == "NONE":
            continue
        compensated = lost * (event.compensation_pct / 100.0)
        if compensated == 0.0:
            continue
        if event.compensation_basis == "CONTRACTED":
            price = Decimal(str(event.compensation_price_eur_mwh))
            compensation_total += Decimal(str(compensated)) * price
            compensated_mwh += compensated
        else:  # MERCHANT
            anchor = max(event.valid_from, period_start)
            price = (merchant_prices or {}).get(anchor)
            if price is None:
                any_unavailable = True
                unavailable_mwh += compensated
                continue
            compensation_total += Decimal(str(compensated)) * Decimal(str(price))
            compensated_mwh += compensated
    if total_lost > gross + 1e-9:
        raise _fail(
            "GENERATION_V2_VALUE",
            "volume-adjustment deductions exceed the period's gross energy "
            f"({total_lost} > {gross}); deductions cannot exceed physical "
            "production")
    net = gross - total_lost
    return VolumeAdjustmentOutcome(
        gross_mwh=gross,
        net_mwh=net,
        total_lost_mwh=total_lost,
        attributions=tuple(attributions),
        compensated_mwh=compensated_mwh,
        # an aggregate over incomplete compensation evidence is not
        # published (UNAVAILABLE evidence never becomes a fabricated zero)
        compensation_eur=None if any_unavailable else compensation_total,
        unavailable_compensation_mwh=unavailable_mwh,
    )


# ── E. Pre-COD commissioning proposals ───────────────────────────────────────


@dataclass(frozen=True)
class PreCodMonthProposal:
    """One commissioning month's proposal row.

    ``gross_mwh`` is the physical pre-COD generation proposal.
    ``potential_sales_eur`` is the separate commercial proposal line;
    ``None`` means UNAVAILABLE (missing merchant market evidence) — never
    a fabricated zero. ``sales_state`` is ``PRICED`` or ``UNAVAILABLE``."""

    year: int
    month: int
    ramp_pct: float
    hours: float
    gross_mwh: float
    sales_state: str
    price_eur_mwh: Optional[float]
    potential_sales_eur: Optional[Decimal]


@dataclass(frozen=True)
class PreCodProposal:
    """Deterministic pre-COD volume + revenue proposal.

    ``physical_total_mwh`` covers only physically generated pre-COD
    energy. ``potential_sales_total_eur`` is ``None`` when ANY month is
    UNAVAILABLE (a total over incomplete evidence is not published) —
    per-month rows still carry the priced months. This proposal is never
    posted into the construction waterfall, tax, IDC or equity balancing."""

    commissioning_start: date
    cod_date: date
    price_basis: str
    months: Tuple[PreCodMonthProposal, ...]
    physical_total_mwh: float
    potential_sales_total_eur: Optional[Decimal]
    unavailable_sales_months: int


def month_sequence(start: date, end_exclusive: date) -> Tuple[Tuple[int, int], ...]:
    """Exact (year, month) sequence of the months in [start, end_exclusive)."""
    require_release()
    if end_exclusive <= start:
        raise _fail("GENERATION_V2_VALUE",
                    "the commissioning window is empty")
    require_month_aligned(start, "window start")
    require_month_aligned(end_exclusive, "window end (COD)")
    out = []
    y, m = start.year, start.month
    while (y, m) != (end_exclusive.year, end_exclusive.month):
        out.append((y, m))
        m += 1
        if m == 13:
            m, y = 1, y + 1
        if len(out) > 1200:
            raise _fail("GENERATION_V2_VALUE",
                        "commissioning window implausibly long")
    return tuple(out)


def build_pre_cod_proposal(
    commissioning: PreCodCommissioning,
    *,
    capacity_mw: float,
    month_hours: Mapping[Tuple[int, int], float],
    availability: float,
    market_prices: Optional[Mapping[Tuple[int, int], float]] = None,
) -> PreCodProposal:
    """Deterministic pre-COD volume and revenue proposal.

    Physical: ``capacity_mw × declared month hours × ramp_pct/100 ×
    availability`` per commissioning month. Commercial: FIXED/PPA settle
    every month at the explicit price; MARKET needs declared evidence per
    month — a missing price is UNAVAILABLE for that month (never zero)
    and suppresses only the TOTAL, never the priced months' rows.

    No waterfall/tax/IDC/equity posting happens here or anywhere in this
    package."""
    require_release()
    commissioning.validate()
    cap = _num(capacity_mw, "capacity_mw", minimum=0.0, exclusive_min=True)
    avail = _num(availability, "availability", minimum=0.0, maximum=1.0,
                 exclusive_min=True)
    months = month_sequence(commissioning.commissioning_start,
                            commissioning.cod_date)
    if len(months) != len(commissioning.monthly_ramp_pct):
        raise _fail(
            "GENERATION_V2_SCHEMA",
            f"the commissioning window has {len(months)} months but "
            f"monthly_ramp_pct carries {len(commissioning.monthly_ramp_pct)} "
            "entries; the ramp must cover exactly the window")
    rows = []
    physical_total = 0.0
    sales_total = Decimal(0)
    unavailable = 0
    for (year, month), ramp in zip(months, commissioning.monthly_ramp_pct):
        key = (year, month)
        if key not in month_hours:
            raise _fail(
                "GENERATION_V2_UNAVAILABLE",
                f"no declared hours for commissioning month {year}-{month:02d}; "
                "declared hours are required (never fabricated)")
        hours = _num(month_hours[key], f"month_hours[{year}-{month:02d}]",
                     minimum=0.0)
        gross = cap * hours * (ramp / 100.0) * avail
        physical_total += gross
        price: Optional[float] = None
        sales: Optional[Decimal] = None
        state = "PRICED"
        if commissioning.price_basis == "FIXED":
            price = commissioning.fixed_price_eur_mwh
        elif commissioning.price_basis == "PPA":
            price = commissioning.ppa_price_eur_mwh
        else:
            evidence = (market_prices or {}).get(key)
            if evidence is None:
                state = "UNAVAILABLE"
                unavailable += 1
            else:
                price = _num(evidence, f"market_prices[{year}-{month:02d}]",
                             minimum=0.0)
        if state == "PRICED":
            sales = (Decimal(str(gross)) * Decimal(str(price))
                     ).quantize(Decimal("0.000001"))
            sales_total += sales
        rows.append(PreCodMonthProposal(
            year=year, month=month, ramp_pct=float(ramp), hours=hours,
            gross_mwh=gross, sales_state=state, price_eur_mwh=price,
            potential_sales_eur=sales,
        ))
    total_eur: Optional[Decimal] = None if unavailable else sales_total
    return PreCodProposal(
        commissioning_start=commissioning.commissioning_start,
        cod_date=commissioning.cod_date,
        price_basis=commissioning.price_basis,
        months=tuple(rows),
        physical_total_mwh=physical_total,
        potential_sales_total_eur=total_eur,
        unavailable_sales_months=unavailable,
    )
