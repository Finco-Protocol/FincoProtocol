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


def apply_transmission_loss_to_periods(
    factor: TransmissionLossFactor,
    periods: Sequence[Tuple[date, float]],
) -> Tuple[Tuple[date, float, float], ...]:
    """Apply the factor to (period_end_date, gross_mwh) rows.

    Each row's delivery is evaluated at the period END date (the canonical
    boundary alignment surface). A DATED_SERIES gap over any requested
    period fails closed with the exact uncovered boundary — gaps can never
    silently pass energy through unadjusted. Returns
    ``(period_end, delivered_mwh, loss_mwh)`` rows; conservation holds per
    row and in total."""

    require_release()
    out = []
    total_gross = 0.0
    for period_end, gross in periods:
        gross = _energy(gross, f"gross_mwh[{period_end}]")
        total_gross += gross
        split = apply_transmission_loss(factor, gross, period_end)
        if split is None:
            raise _fail(
                "GENERATION_V2_UNAVAILABLE",
                f"no transmission loss factor covers the canonical boundary "
                f"{period_end}; a dated series must cover every evaluated "
                "period (gaps never pass energy through unadjusted)")
        out.append((period_end, split.delivered_mwh, split.loss_mwh))
    total_loss = sum(l for _, _, l in out)
    total_delivered = sum(d for _, d, _ in out)
    if abs((total_delivered + total_loss) - total_gross) > 1e-9:
        raise _fail("GENERATION_V2_VALUE",
                    "transmission conservation identity broken")
    return tuple(out)


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


def compose_operating_adjustments(
    *,
    period_index: int,
    operating_year_index: int,
    on_date: date,
    degradation: DegradationOnset,
    availability: FirstYearAvailability,
    transmission_loss: TransmissionLossFactor,
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
    return OperatingPeriodAdjustments(
        period_index=period_index,
        operating_year_index=operating_year_index,
        availability=availability.availability_for(operating_year_index),
        degradation_factor=degradation.factor_for(operating_year_index),
        loss_factor=transmission_loss.factor_on(on_date),
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
