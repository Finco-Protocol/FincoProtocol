"""OD-R04-02 Authoritative Global P50 Annual Physical PPA CAP & Shortfall Validator.

Implements the FINCO36 owner-approved R04 Phase 2 policy (OD-R04-02) for admitted
Solar and Wind projects:
- Annual physical PPA contracted volumes in exact MWh or GWh (1 GWh = 1000 MWh),
  parsed from strict decimal strings into exact ``Fraction`` arithmetic.
- Global validation of the SUM of all active physical delivery contracts (both
  ``ABSOLUTE_ANNUAL`` quantities and comparable physical ``volume_share`` streams)
  against ONE canonical P50 generation envelope built from the shared OD-TIME-01
  contractual calendar (``finco_core.engine.contractual_calendar``).
- Uses the canonical P50 envelope EVEN when the selected yield scenario or lender
  case is ``P90-10y`` (never silently rescales contractual commitments to P90).
- Partial calendar years (e.g. June 30 COD inclusive) prorate by exact eligible
  operating days / (365|366); degradation and availability are applied once inside
  the canonical generator and never double-applied.
- Exact ``Fraction`` comparison: an exact decimal input exceedance is NEVER
  rounded into acceptance. Predeclared numeric tolerance for floating-point
  reconciliation only: ``CAP_COMPARISON_TOLERANCE_MWH = Fraction(1, 1000)`` (0.001 MWh).
- On selected-case (e.g. P90-10y) generation shortfall below valid P50-capped fixed
  physical commitments: retains the contractual obligation, records shortfall by
  contract and period, and FAILS CLOSED (``R04_PHYSICAL_SHORTFALL_NO_SETTLEMENT_CONTRACT``)
  rather than fabricating negative merchant volume, silent haircuts, or zero buy-in prices.
- Admitted technologies: ``solar`` and ``wind`` only; DC, EV, BESS, and unsupported
  structures remain strictly fail-closed.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from fractions import Fraction
import hashlib
import json
import math
import re
from typing import Sequence

from finco_core.engine.contractual_calendar import (
    ContractualInterval,
    build_contractual_reporting_axis,
    contractual_generation_for_interval,
    days_in_calendar_year,
    intersect_intervals,
    operating_horizon_interval,
    split_at_dates,
)

R04_PRODUCTION_CONTRACT_VERSION = "R04_GLOBAL_P50_CAP_V1"
ADMITTED_TECHNOLOGIES = frozenset({"solar", "wind"})
GWH_TO_MWH = Fraction(1000)
CAP_COMPARISON_TOLERANCE_MWH = Fraction(1, 1000)  # 0.001 MWh max numeric reconciliation tolerance
WARNING_UTILIZATION_THRESHOLD = Fraction(95, 100)  # warn in UI when >= 95% of P50 cap committed

_DECIMAL_RE = re.compile(r"^(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$")


class R04CapValidationError(ValueError):
    """Typed fail-closed error for OD-R04-02 validation & shortfall enforcement."""

    def __init__(self, code: str, message: str, *, details: dict | None = None) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.details = details or {}


@dataclass(frozen=True)
class PhysicalContractRequest:
    """One physical delivery contract participating in the global P50 cap."""
    contract_id: str
    start_date: date
    end_date: date  # exclusive [start_date, end_date)
    mode: str  # "ABSOLUTE_ANNUAL" or "VOLUME_SHARE"
    annual_quantity_mwh: Fraction | None = None  # exact MWh/year when mode == "ABSOLUTE_ANNUAL"
    original_unit: str | None = None  # "MWh" or "GWh"
    volume_share: Fraction | None = None  # [0, 1] when mode == "VOLUME_SHARE"
    pricing_reference: str = ""

    def __post_init__(self) -> None:
        if self.end_date <= self.start_date:
            raise R04CapValidationError(
                "R04_CONTRACT_DATE_INVALID",
                f"Contract {self.contract_id!r} end_date must be after start_date.",
            )
        if self.mode == "ABSOLUTE_ANNUAL":
            if self.annual_quantity_mwh is None or self.annual_quantity_mwh < 0:
                raise R04CapValidationError(
                    "R04_QUANTITY_INVALID",
                    f"Contract {self.contract_id!r} requires non-negative annual_quantity_mwh.",
                )
            if self.volume_share is not None:
                raise R04CapValidationError(
                    "R04_DUAL_VOLUME_BASIS_FORBIDDEN",
                    f"Contract {self.contract_id!r} cannot specify both absolute annual quantity and volume share.",
                )
        elif self.mode == "VOLUME_SHARE":
            if self.volume_share is None or not (Fraction(0) <= self.volume_share <= Fraction(1)):
                raise R04CapValidationError(
                    "R04_SHARE_INVALID",
                    f"Contract {self.contract_id!r} requires volume_share in [0, 1].",
                )
            if self.annual_quantity_mwh is not None:
                raise R04CapValidationError(
                    "R04_DUAL_VOLUME_BASIS_FORBIDDEN",
                    f"Contract {self.contract_id!r} cannot specify both volume share and absolute annual quantity.",
                )
        else:
            raise R04CapValidationError(
                "R04_VOLUME_MODE_UNSUPPORTED",
                f"Unsupported physical delivery mode {self.mode!r}.",
            )


def parse_annual_quantity_spec(raw: object, *, contract_id: str) -> tuple[Fraction, str]:
    """Parse ``{"mode": "ABSOLUTE_ANNUAL", "amount": "<decimal>", "unit": "MWh"|"GWh"}`` into exact MWh ``Fraction``."""
    if not isinstance(raw, dict) or set(raw) != {"mode", "amount", "unit"}:
        raise R04CapValidationError(
            "R04_QUANTITY_SCHEMA",
            f"Contract {contract_id!r} annual_quantity requires exact keys mode, amount, unit.",
        )
    if raw["mode"] != "ABSOLUTE_ANNUAL":
        raise R04CapValidationError(
            "R04_QUANTITY_MODE_UNSUPPORTED",
            f"Contract {contract_id!r} annual_quantity.mode must be 'ABSOLUTE_ANNUAL'.",
        )
    unit = raw["unit"]
    if unit not in ("MWh", "GWh"):
        raise R04CapValidationError(
            "R04_QUANTITY_UNIT_UNSUPPORTED",
            f"Contract {contract_id!r} annual_quantity.unit must be 'MWh' or 'GWh', got {unit!r}.",
        )
    amount = raw["amount"]
    if not isinstance(amount, str) or len(amount) > 128 or _DECIMAL_RE.fullmatch(amount) is None:
        raise R04CapValidationError(
            "R04_QUANTITY_AMOUNT_INVALID",
            f"Contract {contract_id!r} annual_quantity.amount must be a finite non-negative decimal string.",
        )
    mwh = Fraction(amount) * (GWH_TO_MWH if unit == "GWh" else Fraction(1))
    return mwh, unit


@dataclass(frozen=True)
class CalendarYearCapStatus:
    year: int
    available_p50_mwh: Fraction
    committed_mwh: Fraction
    remaining_p50_mwh: Fraction
    utilization_ratio: Fraction
    warning: bool
    active_contract_ids: tuple[str, ...]


@dataclass(frozen=True)
class R04CapReviewSummary:
    contract_version: str
    technology: str
    selected_yield_scenario: str
    cap_envelope_basis: str  # always "P50"
    horizon_start: date
    horizon_end_exclusive: date
    yearly_status: tuple[CalendarYearCapStatus, ...]
    warning: bool
    provenance_sha256: str


@dataclass(frozen=True)
class R04ShortfallRecord:
    period_start: date
    period_end_exclusive: date
    calendar_year: int
    available_generation_mwh: float
    total_contracted_mwh: float
    shortfall_mwh: float
    contract_obligations_mwh: dict[str, float]


def _validate_admitted_inputs(project_inputs, *, technology: str) -> None:
    tech_norm = str(technology or "").strip().lower()
    if tech_norm not in ADMITTED_TECHNOLOGIES:
        raise R04CapValidationError(
            "R04_TECHNOLOGY_NOT_ADMITTED",
            f"R04 global P50 annual physical PPA cap is admitted only for solar/wind, got {technology!r}.",
        )
    tech = project_inputs.technical
    if getattr(tech, "bess_enabled", False) or getattr(tech, "bess_native_config_json", ""):
        raise R04CapValidationError(
            "R04_TECHNOLOGY_NOT_ADMITTED",
            "BESS hybrid/standalone structures are not admitted for R04 annual physical PPA cap.",
        )
    for field_name in (
        "capacity_mw",
        "operating_hours_p50",
        "plant_availability",
        "grid_availability",
        "pv_degradation",
    ):
        val = getattr(tech, field_name)
        if isinstance(val, bool) or not isinstance(val, (int, float)) or not math.isfinite(val):
            raise R04CapValidationError(
                "R04_P50_SOURCE_INVALID",
                f"Technical parameter {field_name} must be finite.",
            )
    if tech.capacity_mw <= 0 or tech.operating_hours_p50 <= 0:
        raise R04CapValidationError(
            "R04_P50_SOURCE_INVALID",
            "Canonical P50 envelope requires positive capacity_mw and operating_hours_p50.",
        )
    if not (0.0 <= tech.plant_availability <= 1.0 and 0.0 <= tech.grid_availability <= 1.0):
        raise R04CapValidationError(
            "R04_P50_SOURCE_INVALID",
            "Availability parameters must be in [0, 1].",
        )
    if not (0.0 <= tech.pv_degradation <= 1.0):
        raise R04CapValidationError(
            "R04_P50_SOURCE_INVALID",
            "Annual degradation must be in [0, 1].",
        )


def _exact_p50_mwh_for_subperiod(
    sub: ContractualInterval,
    *,
    cod: date,
    capacity_mw: float,
    hours_p50: float,
    combined_availability: float,
    annual_degradation: float,
) -> Fraction:
    """Exact rational P50 MWh for a subinterval inside one calendar year and one operating year."""
    mwh_float, subs = contractual_generation_for_interval(
        sub,
        cod=cod,
        capacity_mw=capacity_mw,
        annual_hours=hours_p50,
        combined_availability=combined_availability,
        annual_degradation=annual_degradation,
    )
    # Compute exact Fraction using the canonical subperiod structure (no double-degradation)
    base_annual = (
        Fraction(str(capacity_mw))
        * Fraction(str(hours_p50))
        * Fraction(str(combined_availability))
    )
    one_minus_deg = Fraction(1) - Fraction(str(annual_degradation))
    exact_total = Fraction(0)
    for s in subs:
        exact_total += base_annual * s.day_fraction * (one_minus_deg ** (s.operating_year - 1))
    return exact_total


def validate_global_p50_physical_cap(
    project_inputs,
    contracts: Sequence[PhysicalContractRequest],
    *,
    technology: str,
) -> R04CapReviewSummary:
    """Validate the SUM of all active physical contracts against ONE canonical P50 envelope.

    Checks EVERY calendar year and EVERY active subperiod partition across all
    contract start/end dates, Jan 1 boundaries, and COD anniversaries.
    Raises ``R04CapValidationError`` (code ``R04_GLOBAL_P50_CAP_EXCEEDED``) if the
    exact sum of physical commitments exceeds available P50 generation on any
    subperiod or calendar year.
    """
    _validate_admitted_inputs(project_inputs, technology=technology)

    cod = project_inputs.info.cod_date
    horizon_years = int(project_inputs.info.horizon_years)
    horizon_iv = operating_horizon_interval(cod, horizon_years)
    tech = project_inputs.technical
    cap_mw = float(tech.capacity_mw)
    hours_p50 = float(tech.operating_hours_p50)
    avail = float(tech.combined_availability)
    deg = float(tech.pv_degradation)

    # Check duplicate contract IDs and contract bounds vs project operating horizon
    seen_ids: set[str] = set()
    for c in contracts:
        if c.contract_id in seen_ids:
            raise R04CapValidationError(
                "R04_DUPLICATE_CONTRACT_ID",
                f"Duplicate physical contract id {c.contract_id!r}.",
            )
        seen_ids.add(c.contract_id)
        if c.start_date < horizon_iv.start or c.end_date > horizon_iv.end_exclusive:
            raise R04CapValidationError(
                "R04_CONTRACT_OUTSIDE_HORIZON",
                f"Contract {c.contract_id!r} [{c.start_date.isoformat()}, {c.end_date.isoformat()}) "
                f"extends outside operating horizon [{horizon_iv.start.isoformat()}, {horizon_iv.end_exclusive.isoformat()}).",
                details={
                    "contract_id": c.contract_id,
                    "contract_start": c.start_date.isoformat(),
                    "contract_end_exclusive": c.end_date.isoformat(),
                    "horizon_start": horizon_iv.start.isoformat(),
                    "horizon_end_exclusive": horizon_iv.end_exclusive.isoformat(),
                },
            )

    # Collect all boundary cut dates: Jan 1, COD anniversaries, and all contract start/end dates
    cut_dates: list[date] = [
        *(date(y, 1, 1) for y in range(horizon_iv.start.year + 1, horizon_iv.end_exclusive.year + 1)),
    ]
    from finco_core.engine.contractual_calendar import add_calendar_years

    for k in range(1, horizon_years):
        cut_dates.append(add_calendar_years(cod, k))
    for c in contracts:
        cut_dates.append(c.start_date)
        cut_dates.append(c.end_date)

    atomic_subs = split_at_dates(horizon_iv, cut_dates)

    # Accumulate calendar-year totals while enforcing exact subperiod cap on every slice
    by_year_avail: dict[int, Fraction] = {}
    by_year_commit: dict[int, Fraction] = {}
    by_year_cids: dict[int, list[str]] = {}

    for sub in atomic_subs:
        yr = sub.start.year
        yd = days_in_calendar_year(yr)
        sub_frac = Fraction(sub.days, yd)
        p50_sub = _exact_p50_mwh_for_subperiod(
            sub,
            cod=cod,
            capacity_mw=cap_mw,
            hours_p50=hours_p50,
            combined_availability=avail,
            annual_degradation=deg,
        )

        sub_committed = Fraction(0)
        active_cids: list[str] = []
        prior_committed = Fraction(0)
        for c in contracts:
            if c.start_date <= sub.start and sub.end_exclusive <= c.end_date:
                active_cids.append(c.contract_id)
                if c.mode == "ABSOLUTE_ANNUAL":
                    assert c.annual_quantity_mwh is not None
                    req = c.annual_quantity_mwh * sub_frac
                else:
                    assert c.volume_share is not None
                    req = p50_sub * c.volume_share
                prior_committed = sub_committed
                sub_committed += req

                if sub_committed > p50_sub:
                    excess = sub_committed - p50_sub
                    raise R04CapValidationError(
                        "R04_GLOBAL_P50_CAP_EXCEEDED",
                        (
                            f"Global P50 annual physical PPA cap exceeded in calendar year {yr} "
                            f"(subperiod {sub.start.isoformat()} to {sub.end_exclusive.isoformat()}): "
                            f"committed {float(sub_committed):.3f} MWh > available P50 {float(p50_sub):.3f} MWh "
                            f"(excess {float(excess):.3f} MWh; existing {float(prior_committed):.3f} MWh, "
                            f"contract {c.contract_id!r} requested {float(req):.3f} MWh)."
                        ),
                        details={
                            "year": yr,
                            "period_start": sub.start.isoformat(),
                            "period_end_exclusive": sub.end_exclusive.isoformat(),
                            "existing_committed_mwh": float(prior_committed),
                            "new_requested_mwh": float(req),
                            "total_committed_mwh": float(sub_committed),
                            "available_p50_mwh": float(p50_sub),
                            "excess_mwh": float(excess),
                            "offending_contract_id": c.contract_id,
                            "active_contract_ids": list(active_cids),
                            "cap_basis": "P50",
                        },
                    )

        by_year_avail[yr] = by_year_avail.get(yr, Fraction(0)) + p50_sub
        by_year_commit[yr] = by_year_commit.get(yr, Fraction(0)) + sub_committed
        cur_cids = by_year_cids.setdefault(yr, [])
        for cid in active_cids:
            if cid not in cur_cids:
                cur_cids.append(cid)

    yearly_status: list[CalendarYearCapStatus] = []
    any_warning = False
    for yr in sorted(by_year_avail):
        av = by_year_avail[yr]
        cm = by_year_commit[yr]
        rem = av - cm
        util = (cm / av) if av > 0 else Fraction(0)
        warn = util >= WARNING_UTILIZATION_THRESHOLD and cm > 0
        if warn:
            any_warning = True
        yearly_status.append(
            CalendarYearCapStatus(
                year=yr,
                available_p50_mwh=av,
                committed_mwh=cm,
                remaining_p50_mwh=rem,
                utilization_ratio=util,
                warning=warn,
                active_contract_ids=tuple(by_year_cids.get(yr, ())),
            )
        )

    prov_payload = {
        "contract_version": R04_PRODUCTION_CONTRACT_VERSION,
        "technology": str(technology).strip().lower(),
        "cod": cod.isoformat(),
        "horizon_years": horizon_years,
        "capacity_mw": cap_mw,
        "hours_p50": hours_p50,
        "combined_availability": avail,
        "degradation": deg,
        "contracts": [
            {
                "id": c.contract_id,
                "start": c.start_date.isoformat(),
                "end": c.end_date.isoformat(),
                "mode": c.mode,
                "annual_mwh": str(c.annual_quantity_mwh) if c.annual_quantity_mwh is not None else None,
                "share": str(c.volume_share) if c.volume_share is not None else None,
            }
            for c in contracts
        ],
    }
    prov_sha = hashlib.sha256(
        json.dumps(prov_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()

    return R04CapReviewSummary(
        contract_version=R04_PRODUCTION_CONTRACT_VERSION,
        technology=str(technology).strip().lower(),
        selected_yield_scenario=str(tech.yield_scenario),
        cap_envelope_basis="P50",
        horizon_start=horizon_iv.start,
        horizon_end_exclusive=horizon_iv.end_exclusive,
        yearly_status=tuple(yearly_status),
        warning=any_warning,
        provenance_sha256=prov_sha,
    )


def review_global_p50_physical_cap(project_inputs, contracts, *, technology: str) -> dict:
    """Non-mutating proposed-state REVIEW of the global P50 cap (OD-R04-02): the per-calendar-year table plus every exceeding slice.

    Same exact ``Fraction`` slice arithmetic as :func:`validate_global_p50_physical_cap` (same split dates, same canonical generator), but it
    never raises on an excess: it reports it, so the editor can show year, period, committed, available and remaining quantities.  It is
    advisory only - the canonical Save/Run validation stays the authority.  ``shortfall`` lists slices where the SELECTED case (e.g. P90-10y)
    generates less than the fixed physical commitments (the Run would refuse with R04_PHYSICAL_SHORTFALL_NO_SETTLEMENT_CONTRACT).
    """
    _validate_admitted_inputs(project_inputs, technology=technology)
    cod = project_inputs.info.cod_date
    horizon_years = int(project_inputs.info.horizon_years)
    horizon_iv = operating_horizon_interval(cod, horizon_years)
    tech = project_inputs.technical
    cap_mw, hours_p50 = float(tech.capacity_mw), float(tech.operating_hours_p50)
    avail, deg = float(tech.combined_availability), float(tech.pv_degradation)
    selected_is_p90 = str(tech.yield_scenario).upper().startswith("P90")
    hours_p90 = float(tech.operating_hours_p90_10y)
    hours_sel = hours_p90 if selected_is_p90 else hours_p50
    seen: set[str] = set()
    for c in contracts:
        if c.contract_id in seen:
            raise R04CapValidationError("R04_DUPLICATE_CONTRACT_ID", f"Duplicate physical contract id {c.contract_id!r}.")
        seen.add(c.contract_id)
        if c.start_date < horizon_iv.start or c.end_date > horizon_iv.end_exclusive:
            raise R04CapValidationError(
                "R04_CONTRACT_OUTSIDE_HORIZON",
                f"Contract {c.contract_id!r} [{c.start_date.isoformat()}, {c.end_date.isoformat()}) extends outside operating horizon "
                f"[{horizon_iv.start.isoformat()}, {horizon_iv.end_exclusive.isoformat()}).")
    from finco_core.engine.contractual_calendar import add_calendar_years

    cuts = [date(y, 1, 1) for y in range(horizon_iv.start.year + 1, horizon_iv.end_exclusive.year + 1)]
    cuts += [add_calendar_years(cod, k) for k in range(1, horizon_years)]
    for c in contracts:
        cuts += [c.start_date, c.end_date]
    years: dict[int, dict] = {}
    exceed: list[dict] = []
    shortfall: list[dict] = []
    p90_shortfall: list[dict] = []
    for sub in split_at_dates(horizon_iv, cuts):
        yr, frac = sub.start.year, Fraction(sub.days, days_in_calendar_year(sub.start.year))
        p50 = _exact_p50_mwh_for_subperiod(sub, cod=cod, capacity_mw=cap_mw, hours_p50=hours_p50, combined_availability=avail, annual_degradation=deg)
        sel = p50 if not selected_is_p90 else _exact_p50_mwh_for_subperiod(
            sub, cod=cod, capacity_mw=cap_mw, hours_p50=hours_sel, combined_availability=avail, annual_degradation=deg)
        p90 = _exact_p50_mwh_for_subperiod(
            sub, cod=cod, capacity_mw=cap_mw, hours_p50=hours_p90, combined_availability=avail, annual_degradation=deg)
        committed, active, fixed = Fraction(0), [], Fraction(0)
        for c in contracts:
            if c.start_date <= sub.start and sub.end_exclusive <= c.end_date:
                active.append(c.contract_id)
                req = c.annual_quantity_mwh * frac if c.mode == "ABSOLUTE_ANNUAL" else p50 * c.volume_share
                committed += req
                if c.mode == "ABSOLUTE_ANNUAL":
                    fixed += req
        row = years.setdefault(yr, {"year": yr, "available_p50_mwh": Fraction(0), "committed_mwh": Fraction(0), "contracts": []})
        row["available_p50_mwh"] += p50
        row["committed_mwh"] += committed
        row["contracts"] = sorted(set(row["contracts"]) | set(active))
        if committed > p50:
            exceed.append({"year": yr, "period_start": sub.start.isoformat(), "period_end_exclusive": sub.end_exclusive.isoformat(),
                           "available_p50_mwh": float(p50), "committed_mwh": float(committed), "excess_mwh": float(committed - p50),
                           "contracts": active})
        if fixed > p90:
            p90_shortfall.append({"year": yr, "period_start": sub.start.isoformat(), "period_end_exclusive": sub.end_exclusive.isoformat(),
                                  "p90_available_mwh": float(p90), "fixed_commitment_mwh": float(fixed), "shortfall_mwh": float(fixed - p90)})
        if fixed > sel:
            shortfall.append({"year": yr, "period_start": sub.start.isoformat(), "period_end_exclusive": sub.end_exclusive.isoformat(),
                              "selected_available_mwh": float(sel), "fixed_commitment_mwh": float(fixed), "shortfall_mwh": float(fixed - sel)})
    table = []
    for yr in sorted(years):
        r = years[yr]
        av, cm = r["available_p50_mwh"], r["committed_mwh"]
        util = (cm / av) if av > 0 else Fraction(0)
        table.append({"year": yr, "available_p50_mwh": float(av), "committed_mwh": float(cm), "remaining_p50_mwh": float(av - cm),
                      "utilization_ratio": float(util), "warning": bool(util >= WARNING_UTILIZATION_THRESHOLD and cm > 0),
                      "exceeded": cm > av, "contracts": r["contracts"]})
    return {"contract_version": R04_PRODUCTION_CONTRACT_VERSION, "cap_envelope_basis": "P50", "selected_yield_scenario": str(tech.yield_scenario),
            "selected_case_hours": hours_sel, "p50_hours": hours_p50, "years": table, "exceeded_slices": exceed, "shortfall_slices": shortfall,
            "p90_hours": hours_p90, "p90_shortfall_slices": p90_shortfall,
            "horizon_start": horizon_iv.start.isoformat(), "horizon_end_exclusive": horizon_iv.end_exclusive.isoformat(),
            "blocked": bool(exceed), "warning": any(r["warning"] for r in table),
            "shortfall_error_code": "R04_PHYSICAL_SHORTFALL_NO_SETTLEMENT_CONTRACT" if shortfall else None}


def allocate_r04_period_deliveries(
    interval: ContractualInterval,
    *,
    available_generation_mwh: float,
    contracts: Sequence[PhysicalContractRequest],
    allow_shortfall_without_settlement: bool = False,
) -> tuple[dict[str, float], float, R04ShortfallRecord | None]:
    """Allocate physical deliveries on ``interval`` without double-counting or negative merchant.

    - Sums fixed ``ABSOLUTE_ANNUAL`` obligations (prorated by ``overlap_days / (365|366)``)
      plus any ``VOLUME_SHARE`` obligations against ``available_generation_mwh``.
    - If ``available_generation_mwh < total_obligated_mwh - 0.001`` (e.g. P90 shortfall):
      records the exact shortfall by contract/period and FAILS CLOSED with
      ``R04_PHYSICAL_SHORTFALL_NO_SETTLEMENT_CONTRACT`` unless explicitly queried in
      diagnostic-only mode.
    - Returns ``(allocated_by_contract_id_mwh, residual_merchant_mwh, shortfall_record)``
      satisfying ``sum(allocated.values()) + residual_merchant_mwh == available_generation_mwh``.
    """
    if available_generation_mwh < 0.0 or not math.isfinite(available_generation_mwh):
        raise R04CapValidationError(
            "R04_GENERATION_INVALID",
            f"available_generation_mwh must be finite and non-negative, got {available_generation_mwh!r}.",
        )

    allocated: dict[str, float] = {}
    total_fixed = 0.0

    for c in contracts:
        c_iv = ContractualInterval(c.start_date, c.end_date)
        ov = intersect_intervals(interval, c_iv)
        if ov is None:
            allocated[c.contract_id] = 0.0
            continue
        if c.mode == "ABSOLUTE_ANNUAL":
            assert c.annual_quantity_mwh is not None
            # Split overlap by calendar year for exact 365/366 weighting
            jan1_cuts = [date(y, 1, 1) for y in range(ov.start.year + 1, ov.end_exclusive.year + 1)]
            req_mwh = Fraction(0)
            for sub in split_at_dates(ov, jan1_cuts):
                req_mwh += c.annual_quantity_mwh * Fraction(sub.days, days_in_calendar_year(sub.start.year))
            val = float(req_mwh)
        else:
            assert c.volume_share is not None
            val = available_generation_mwh * float(c.volume_share) * (ov.days / interval.days)
        allocated[c.contract_id] = val
        total_fixed += val

    tol = float(CAP_COMPARISON_TOLERANCE_MWH)
    if total_fixed > available_generation_mwh + tol:
        shortfall = total_fixed - available_generation_mwh
        rec = R04ShortfallRecord(
            period_start=interval.start,
            period_end_exclusive=interval.end_exclusive,
            calendar_year=interval.start.year,
            available_generation_mwh=available_generation_mwh,
            total_contracted_mwh=total_fixed,
            shortfall_mwh=shortfall,
            contract_obligations_mwh=dict(allocated),
        )
        if not allow_shortfall_without_settlement:
            raise R04CapValidationError(
                "R04_PHYSICAL_SHORTFALL_NO_SETTLEMENT_CONTRACT",
                (
                    f"Physical delivery shortfall in period {interval.start.isoformat()}..{interval.end_exclusive.isoformat()}: "
                    f"contracted {total_fixed:.3f} MWh exceeds available generation {available_generation_mwh:.3f} MWh "
                    f"(shortfall {shortfall:.3f} MWh). No approved shortfall settlement contract is configured; "
                    f"refusing negative merchant or silent haircut."
                ),
                details={
                    "period_start": interval.start.isoformat(),
                    "period_end_exclusive": interval.end_exclusive.isoformat(),
                    "calendar_year": interval.start.year,
                    "available_generation_mwh": available_generation_mwh,
                    "total_contracted_mwh": total_fixed,
                    "shortfall_mwh": shortfall,
                    "contract_obligations_mwh": dict(allocated),
                },
            )
        return allocated, 0.0, rec

    # Within 0.001 MWh numeric rounding tolerance at exact boundary, clamp residual to >= 0.0
    residual_merchant = max(0.0, available_generation_mwh - total_fixed)
    return allocated, residual_merchant, None


__all__ = [
    "R04_PRODUCTION_CONTRACT_VERSION",
    "ADMITTED_TECHNOLOGIES",
    "GWH_TO_MWH",
    "CAP_COMPARISON_TOLERANCE_MWH",
    "WARNING_UTILIZATION_THRESHOLD",
    "R04CapValidationError",
    "PhysicalContractRequest",
    "CalendarYearCapStatus",
    "R04CapReviewSummary",
    "R04ShortfallRecord",
    "parse_annual_quantity_spec",
    "validate_global_p50_physical_cap",
    "review_global_p50_physical_cap",
    "allocate_r04_period_deliveries",
]
