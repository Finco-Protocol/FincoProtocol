"""Generation Losses & Pre-COD candidate (WF-03A) — typed contracts.

RELEASE-CLOSED CANDIDATE. This package is not released financial
authority, is never imported by any production path, and adds no product
surface. Every public entry point is gated behind :data:`ACTIVATION_ENABLED`
(a module-level literal ``False``). Only isolated acceptance fixtures may
enable the gate in memory; no environment variable, customer payload or
product surface can enable it.

Scope (deterministic core only; every open economics choice is listed in
``docs/model_v2/WF03A_FINANCIAL_OWNER_DECISIONS.md`` and is NOT assumed):

A. Transmission loss factor — flat or explicitly dated series; gross vs
   grid-delivered energy tracked separately with an exact conservation
   identity; invalid factors, gaps and overlapping windows fail closed.
B. Degradation onset — an explicit first-affected operating year. The
   canonical released convention (``finco_core/revenue/generation.py``:
   ``(1 - pv_degradation) ** (year_index - 1)``, i.e. degradation first
   bites in operating year 2) is preserved EXACTLY by the default onset
   value 2; the candidate never silently changes first-year conventions.
C. First-year availability — an independent first-operating-year
   availability with normal availability afterwards. Partial COD years
   are handled by canonical ``day_fraction`` proration only; this module
   never annualises.
D. Volume adjustment events — named, dated, non-overlapping energy-loss
   events with per-event attribution and an optional compensation basis
   (contracted price or merchant market evidence). Compensation changes
   cash receipts, never physical MWh. Overlapping windows fail closed so
   double deductions are impossible by construction; overlap precedence
   and compensation pricing are Financial-Owner-gated.
E. Pre-COD commissioning — an explicit commissioning window before COD
   with monthly ramp percentages and a price-basis vocabulary
   (FIXED / PPA / MARKET). Physical commissioning generation and
   potential sales are separate ledgers; a missing merchant market price
   is UNAVAILABLE, never a fabricated zero. This module NEVER posts
   commissioning receipts into the construction waterfall, tax, IDC or
   equity balancing — that requires an approved Financial Owner
   accounting decision.

Financial invariants enforced here (tested in
``tests/test_generation_v2_candidate.py``): gross = delivered + losses;
compensation never changes physical MWh; transmission loss applied at
most once; no silent double deductions; explicit degradation onset
semantics; first-year vs normal availability single-sourced; commissioning
production never re-enters operating revenue; pre-COD months never
silently treated as post-COD; missing evidence stays UNAVAILABLE;
unsupported combinations fail closed.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import date
from typing import Optional, Tuple

#: Release-closure flag (house convention). Candidate content is not
#: released authority. Only isolated acceptance fixtures enable this gate;
#: no environment variable or customer payload can enable it.
ACTIVATION_ENABLED = False


def require_release() -> None:
    if not ACTIVATION_ENABLED:
        raise ValueError(
            "GENERATION_V2_RELEASE_CLOSED: independent financial release "
            "approval required")


# ── Strict primitives ────────────────────────────────────────────────────────


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


def _pct(value, label: str) -> float:
    """Percentage 0..100 (loss/compensation percentages, NOT fractions)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) \
            or not math.isfinite(float(value)):
        raise _fail("GENERATION_V2_VALUE", f"{label} must be a finite number")
    v = float(value)
    if not 0.0 <= v <= 100.0:
        raise _fail("GENERATION_V2_VALUE",
                    f"{label} is a percentage and must be within [0, 100], "
                    f"got {v!r}")
    return v


def _date(value, label: str) -> date:
    if not isinstance(value, date):
        raise _fail("GENERATION_V2_SCHEMA", f"{label} must be a datetime.date")
    return value


def _choice(value, label: str, allowed) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise _fail("GENERATION_V2_UNSUPPORTED",
                    f"{label} {value!r} is not supported (supported: "
                    f"{sorted(allowed)})")
    return value


def _require_date_order(start: date, end: date, start_label: str,
                        end_label: str) -> None:
    if end <= start:
        raise _fail("GENERATION_V2_VALUE",
                    f"{end_label} ({end}) must be strictly after "
                    f"{start_label} ({start})")


# ── A. Transmission loss factor ──────────────────────────────────────────────

LOSS_MODES = ("FLAT", "DATED_SERIES")


@dataclass(frozen=True)
class LossFactorWindow:
    """One dated transmission-loss window (``valid_until`` EXCLUSIVE).

    ``loss_factor`` is the fraction of energy lost in transmission
    (0.03 = 3% loss). Canonical date semantics: window edges must be
    exact dates the caller aligns to canonical period boundaries or
    construction-month edges; this contract never moves a date."""

    valid_from: date
    valid_until: date
    loss_factor: float

    def validate(self) -> None:
        _date(self.valid_from, "loss window valid_from")
        _date(self.valid_until, "loss window valid_until")
        _require_date_order(self.valid_from, self.valid_until,
                            "valid_from", "valid_until")
        _num(self.loss_factor, "loss_factor", minimum=0.0, maximum=1.0)


@dataclass(frozen=True)
class TransmissionLossFactor:
    """Flat or explicitly dated transmission loss configuration.

    FLAT: one ``flat_factor`` for every evaluation date.
    DATED_SERIES: non-overlapping, gap-free-from-start windows; a date
    not covered by any window is a typed UNAVAILABLE, never an implicit
    factor of zero."""

    mode: str
    flat_factor: Optional[float] = None
    windows: Tuple[LossFactorWindow, ...] = ()

    def validate(self) -> None:
        _choice(self.mode, "transmission_loss.mode", LOSS_MODES)
        if self.mode == "FLAT":
            if self.flat_factor is None:
                raise _fail("GENERATION_V2_SCHEMA",
                            "FLAT mode requires flat_factor")
            _num(self.flat_factor, "transmission_loss.flat_factor",
                 minimum=0.0, maximum=1.0)
            if self.windows:
                raise _fail("GENERATION_V2_SCHEMA",
                            "FLAT mode must not carry windows")
        else:
            if not self.windows:
                raise _fail("GENERATION_V2_SCHEMA",
                            "DATED_SERIES requires at least one window")
            if self.flat_factor is not None:
                raise _fail("GENERATION_V2_SCHEMA",
                            "DATED_SERIES must not carry flat_factor")
            ordered = sorted(self.windows, key=lambda w: w.valid_from)
            for window in ordered:
                window.validate()
            for earlier, later in zip(ordered, ordered[1:]):
                if later.valid_from < earlier.valid_until:
                    raise _fail(
                        "GENERATION_V2_OVERLAP",
                        f"loss windows [{earlier.valid_from}..{earlier.valid_until})"
                        f" and [{later.valid_from}..{later.valid_until}) overlap; "
                        "overlapping loss windows cannot silently duplicate "
                        "deductions (OWNER DECISION REQUIRED for precedence)")

    def covers(self, when: date) -> bool:
        self.validate()
        if self.mode == "FLAT":
            return True
        return any(w.valid_from <= when < w.valid_until for w in self.windows)

    def factor_on(self, when: date) -> Optional[float]:
        """The loss factor on an exact date, or None when the dated series
        does not cover the date (typed UNAVAILABLE at the caller)."""
        self.validate()
        if self.mode == "FLAT":
            return self.flat_factor
        for w in self.windows:
            if w.valid_from <= when < w.valid_until:
                return w.loss_factor
        return None


# ── B. Degradation onset ─────────────────────────────────────────────────────


@dataclass(frozen=True)
class DegradationOnset:
    """Explicit degradation onset in canonical operating-year indexing.

    ``first_affected_year`` is the first operating year whose production
    factor is below 1.0 (when ``annual_rate`` > 0). The candidate factor
    for an operating year ``y`` is::

        1.0                                      if y < first_affected_year
        (1 - annual_rate) ** (y - first_affected_year + 1)   otherwise

    ``first_affected_year=2`` reproduces the canonical released formula
    ``(1 - pv_degradation) ** (year_index - 1)`` EXACTLY (year 1 factor
    1.0, year 2 factor (1-d)^1, ...). ``first_affected_year=1`` bites in
    the first operating year; ``annual_rate=0`` yields no degradation at
    any onset. No first-year convention is changed silently."""

    annual_rate: float
    first_affected_year: int = 2

    def validate(self) -> None:
        _num(self.annual_rate, "degradation.annual_rate", minimum=0.0,
             maximum=1.0)
        if not isinstance(self.first_affected_year, int) \
                or isinstance(self.first_affected_year, bool) \
                or self.first_affected_year < 1:
            raise _fail("GENERATION_V2_VALUE",
                        "degradation.first_affected_year must be an integer "
                        ">= 1 (canonical operating-year indexing starts at 1)")

    def factor_for(self, operating_year_index: int) -> float:
        self.validate()
        if not isinstance(operating_year_index, int) \
                or isinstance(operating_year_index, bool) \
                or operating_year_index < 1:
            raise _fail(
                "GENERATION_V2_VALUE",
                f"operating_year_index must be an integer >= 1, got "
                f"{operating_year_index!r}")
        if self.annual_rate == 0.0:
            return 1.0
        if operating_year_index < self.first_affected_year:
            return 1.0
        exponent = operating_year_index - self.first_affected_year + 1
        return (1.0 - self.annual_rate) ** exponent

    @staticmethod
    def canonical(rate: float) -> "DegradationOnset":
        """The factory reproducing the released convention exactly."""
        onset = DegradationOnset(annual_rate=rate, first_affected_year=2)
        onset.validate()
        return onset


# ── C. First-year availability ───────────────────────────────────────────────

PARTIAL_COD_TREATMENTS = ("FIRST_YEAR_AVAILABILITY",)


@dataclass(frozen=True)
class FirstYearAvailability:
    """Independent first-operating-year availability.

    Every operating period with ``operating_year_index == 1`` (including a
    partial COD stub) uses ``first_year_availability``; all later
    operating years use ``normal_availability``. Exactly one of the two
    applies to any period — they can never conflict.

    Partial COD years: the canonical ``day_fraction`` proration of the
    released engine is the ONLY annualisation; this candidate adds none.
    V1 pins ``partial_cod_treatment = FIRST_YEAR_AVAILABILITY`` (the stub
    is part of operating year 1); alternative treatments (e.g. full normal
    availability for the stub) are Financial-Owner decisions and fail
    closed here."""

    first_year_availability: float
    normal_availability: float
    partial_cod_treatment: str = "FIRST_YEAR_AVAILABILITY"

    def validate(self) -> None:
        _num(self.first_year_availability, "first_year_availability",
             minimum=0.0, maximum=1.0, exclusive_min=True)
        _num(self.normal_availability, "normal_availability",
             minimum=0.0, maximum=1.0, exclusive_min=True)
        _choice(self.partial_cod_treatment,
                "partial_cod_treatment", PARTIAL_COD_TREATMENTS)

    def availability_for(self, operating_year_index: int) -> float:
        self.validate()
        if not isinstance(operating_year_index, int) \
                or isinstance(operating_year_index, bool) \
                or operating_year_index < 1:
            raise _fail("GENERATION_V2_VALUE",
                        f"operating_year_index must be an integer >= 1, got "
                        f"{operating_year_index!r}")
        if operating_year_index == 1:
            return self.first_year_availability
        return self.normal_availability


# ── D. Volume adjustment events ──────────────────────────────────────────────

COMPENSATION_BASES = ("NONE", "CONTRACTED", "MERCHANT")


@dataclass(frozen=True)
class VolumeAdjustmentEvent:
    """One named, dated energy-loss event.

    ``valid_until`` is EXCLUSIVE. ``energy_loss_pct`` is the share of the
    affected period energy physically lost to the event (e.g. curtailment
    or grid outage). ``compensation_basis`` decides the cash ledger:

    - NONE: no compensation (pure loss);
    - CONTRACTED: lost energy compensated at the explicit
      ``compensation_price_eur_mwh``;
    - MERCHANT: lost energy compensated at the market price evidence
      supplied at evaluation; a missing market price for an affected date
      is UNAVAILABLE (never zero).

    ``compensation_pct`` is the compensated share of the lost revenue
    (0..100). Compensation is a CASH receipt only — it never changes
    delivered or lost physical MWh. Overlapping windows fail closed so a
    deduction can never be duplicated; precedence schemes are Financial-
    Owner decisions."""

    event_id: str
    valid_from: date
    valid_until: date
    energy_loss_pct: float
    compensation_basis: str = "NONE"
    compensation_pct: float = 0.0
    compensation_price_eur_mwh: Optional[float] = None

    def validate(self) -> None:
        if not isinstance(self.event_id, str) or not self.event_id.strip():
            raise _fail("GENERATION_V2_SCHEMA",
                        "event_id is required and must be non-empty")
        if len(self.event_id) > 200:
            raise _fail("GENERATION_V2_IDENTITY",
                        "event_id must be at most 200 characters")
        _date(self.valid_from, "valid_from")
        _date(self.valid_until, "valid_until")
        _require_date_order(self.valid_from, self.valid_until,
                            "valid_from", "valid_until")
        _pct(self.energy_loss_pct, "energy_loss_pct")
        _choice(self.compensation_basis, "compensation_basis",
                COMPENSATION_BASES)
        _pct(self.compensation_pct, "compensation_pct")
        if self.compensation_basis == "CONTRACTED":
            if self.compensation_price_eur_mwh is None:
                raise _fail(
                    "GENERATION_V2_SCHEMA",
                    "CONTRACTED compensation requires "
                    "compensation_price_eur_mwh")
            _num(self.compensation_price_eur_mwh,
                 "compensation_price_eur_mwh", minimum=0.0)
        elif self.compensation_price_eur_mwh is not None:
            raise _fail(
                "GENERATION_V2_SCHEMA",
                "compensation_price_eur_mwh requires "
                "compensation_basis='CONTRACTED'")
        if self.compensation_basis == "NONE" and self.compensation_pct != 0.0:
            raise _fail(
                "GENERATION_V2_VALUE",
                "compensation_pct requires a compensation basis other than "
                "NONE")


def validate_no_event_overlaps(
        events: Tuple[VolumeAdjustmentEvent, ...]) -> Tuple[VolumeAdjustmentEvent, ...]:
    """Fail closed when any two event windows overlap in time.

    Non-overlapping windows make a double deduction impossible by
    construction: every date is attributed to at most one event."""
    require_release()
    ordered = sorted(events, key=lambda e: e.valid_from)
    seen_ids = set()
    for event in ordered:
        event.validate()
        if event.event_id in seen_ids:
            raise _fail("GENERATION_V2_IDENTITY",
                        f"duplicate event_id {event.event_id!r}")
        seen_ids.add(event.event_id)
    for earlier, later in zip(ordered, ordered[1:]):
        if later.valid_from < earlier.valid_until:
            raise _fail(
                "GENERATION_V2_OVERLAP",
                f"volume-adjustment events {earlier.event_id!r} "
                f"[{earlier.valid_from}..{earlier.valid_until}) and "
                f"{later.event_id!r} [{later.valid_from}.."
                f"{later.valid_until}) overlap; overlapping loss events "
                "cannot silently duplicate deductions (precedence is a "
                "Financial Owner decision)")
    return tuple(ordered)


# ── E. Pre-COD commissioning ─────────────────────────────────────────────────

PRICE_BASES = ("FIXED", "PPA", "MARKET")


@dataclass(frozen=True)
class PreCodCommissioning:
    """Explicit pre-COD commissioning window with a monthly ramp.

    The window is ``[commissioning_start, cod_date)`` — the COD month
    itself is NEVER part of the commissioning window (pre-COD months are
    never silently treated as post-COD periods). ``monthly_ramp_pct``
    carries one percentage per calendar month of the window, in order;
    its length must equal the window's month count exactly.

    ``price_basis``: FIXED settles at ``fixed_price_eur_mwh``; PPA at
    ``ppa_price_eur_mwh``; MARKET at the merchant price evidence supplied
    at evaluation — a month without market evidence is UNAVAILABLE, never
    zero. This contract produces PROPOSALS only: nothing here is posted
    into the construction waterfall, tax, IDC or equity balancing."""

    commissioning_start: date
    cod_date: date
    monthly_ramp_pct: Tuple[float, ...]
    price_basis: str
    fixed_price_eur_mwh: Optional[float] = None
    ppa_price_eur_mwh: Optional[float] = None

    def _validate_window_geometry(self) -> None:
        """Window and ramp geometry (answerable before commercial terms)."""
        _date(self.commissioning_start, "commissioning_start")
        _date(self.cod_date, "cod_date")
        _require_date_order(self.commissioning_start, self.cod_date,
                            "commissioning_start", "cod_date")
        if not isinstance(self.monthly_ramp_pct, tuple) \
                or not self.monthly_ramp_pct:
            raise _fail("GENERATION_V2_SCHEMA",
                        "monthly_ramp_pct must be a non-empty tuple of "
                        "monthly percentages")
        for i, pct in enumerate(self.monthly_ramp_pct):
            p = _pct(pct, f"monthly_ramp_pct[{i}]")
            if p == 0.0:
                raise _fail(
                    "GENERATION_V2_VALUE",
                    f"monthly_ramp_pct[{i}] must be strictly positive (a "
                    "commissioning month with zero ramp is not a "
                    "commissioning month; drop the month instead)")

    def validate(self) -> None:
        self._validate_window_geometry()
        _choice(self.price_basis, "price_basis", PRICE_BASES)
        if self.price_basis in ("FIXED", "PPA"):
            price = (self.fixed_price_eur_mwh if self.price_basis == "FIXED"
                     else self.ppa_price_eur_mwh)
            label = ("fixed_price_eur_mwh" if self.price_basis == "FIXED"
                     else "ppa_price_eur_mwh")
            if price is None:
                raise _fail("GENERATION_V2_SCHEMA",
                            f"{self.price_basis} basis requires {label}")
            _num(price, label, minimum=0.0)
        elif self.fixed_price_eur_mwh is not None \
                or self.ppa_price_eur_mwh is not None:
            raise _fail(
                "GENERATION_V2_SCHEMA",
                "fixed/ppa prices require the matching price_basis")

    def window_months(self) -> int:
        """Exact count of calendar months in [start, cod)."""
        self._validate_window_geometry()
        months = ((self.cod_date.year - self.commissioning_start.year) * 12
                  + self.cod_date.month - self.commissioning_start.month)
        return months


# ── Deterministic serialization ──────────────────────────────────────────────


def canonical_json(payload) -> str:
    """Sorted-key, ASCII, NaN-refusing canonical JSON for candidate
    payloads (same convention the released candidates use)."""
    require_release()
    return json.dumps(payload, sort_keys=True, ensure_ascii=True,
                      allow_nan=False, separators=(",", ":"))
