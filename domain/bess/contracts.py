"""Immutable, bounded standalone BESS inputs. No legacy spread/default inference."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from enum import Enum

MAX_HOURS = 300_000
MAX_JSON_BYTES = 2_000_000


class BessInputError(ValueError):
    pass


class DispatchMode(str, Enum):
    EXPLICIT_HOURLY = "EXPLICIT_HOURLY"
    FIXED_DAILY_PLAN = "FIXED_DAILY_PLAN"


class EventKind(str, Enum):
    AUGMENT = "AUGMENT"
    REPLACE = "REPLACE"


def exact(value, keys, label):
    if not isinstance(value, dict) or set(value) != set(keys):
        raise BessInputError(f"BESS_SCHEMA: {label} requires exactly {sorted(keys)}")


def text(value, label):
    if not isinstance(value, str) or not value.strip() or value != value.strip() or len(value) > 200:
        raise BessInputError(f"BESS_EVIDENCE: bounded explicit {label} required")
    return value


def number(value, label, *, maximum=None, positive=False):
    if type(value) not in (int, float):
        raise BessInputError(f"BESS_NUMBER: {label} must be numeric")
    try:
        result = Decimal(str(value))
    except InvalidOperation as exc:
        raise BessInputError(f"BESS_NUMBER: invalid {label}") from exc
    if not result.is_finite() or result < 0 or (positive and result == 0) or (maximum is not None and result > maximum):
        raise BessInputError(f"BESS_NUMBER: invalid finite non-negative {label}")
    if result > Decimal("1e15"):
        raise BessInputError(f"BESS_NUMBER: {label} exceeds candidate numerical domain")
    return result


def whole(value, label, minimum, maximum):
    if type(value) is not int or not minimum <= value <= maximum:
        raise BessInputError(f"BESS_INTEGER: invalid {label}")
    return value


def stamp(value):
    if not isinstance(value, str) or len(value) != 20 or not value.endswith("Z"):
        raise BessInputError("BESS_TIME: exact YYYY-MM-DDTHH:00:00Z UTC timestamp required")
    try:
        result = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise BessInputError("BESS_TIME: invalid UTC timestamp") from exc
    if not 1900 <= result.year <= 2199 or result.strftime("%Y-%m-%dT%H:%M:%SZ") != value or result.minute or result.second:
        raise BessInputError("BESS_TIME: only exact UTC hours supported; no offsets/DST/intraday inference")
    return result


@dataclass(frozen=True)
class Battery:
    charge_power_mw: Decimal
    discharge_power_mw: Decimal
    grid_import_limit_mw: Decimal
    grid_export_limit_mw: Decimal
    installed_energy_mwh: Decimal
    usable_energy_mwh: Decimal
    duration_hours: Decimal
    soc_min: Decimal
    soc_max: Decimal
    initial_energy_mwh: Decimal
    terminal_energy_mwh: Decimal
    charge_efficiency: Decimal
    discharge_efficiency: Decimal
    round_trip_efficiency: Decimal
    calendar_loss_per_year: Decimal
    cycle_loss_per_efc: Decimal
    minimum_soh: Decimal
    useful_life_years: int


@dataclass(frozen=True)
class DispatchPoint:
    coordinate: datetime | int
    charge_mw: Decimal
    discharge_mw: Decimal
    auxiliary_grid_mw: Decimal
    available: bool
    buy_price_eur_mwh: Decimal
    sell_price_eur_mwh: Decimal
    import_charge_eur_mwh: Decimal
    export_charge_eur_mwh: Decimal
    source_ref: str


@dataclass(frozen=True)
class Outage:
    start: datetime
    end: datetime
    source_ref: str


@dataclass(frozen=True)
class Augmentation:
    at: datetime
    kind: EventKind
    installed_energy_mwh: Decimal
    usable_energy_mwh: Decimal
    cost_keur: Decimal
    useful_life_years: int
    source_ref: str
    tax_book_policy: str


@dataclass(frozen=True)
class BessConfiguration:
    battery: Battery
    start: datetime
    end: datetime
    mode: DispatchMode
    points: tuple[DispatchPoint, ...]
    outages: tuple[Outage, ...]
    events: tuple[Augmentation, ...]
    source_ref: str
    canonical_json: str


def _unique(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise BessInputError(f"BESS_SCHEMA: duplicate key {key}")
        obj[key] = value
    return obj


def parse_configuration(raw: str) -> BessConfiguration:
    if not isinstance(raw, str) or len(raw.encode("utf-8")) > MAX_JSON_BYTES:
        raise BessInputError("BESS_SIZE: bounded JSON configuration required")
    try:
        obj = json.loads(raw, object_pairs_hook=_unique)
    except (ValueError, TypeError, RecursionError) as exc:
        raise BessInputError("BESS_SCHEMA: invalid bounded JSON") from exc
    exact(obj, {"version", "technology", "time_convention", "degradation_convention", "efc_convention",
        "price_unit", "settlement_policy", "information_policy", "source_ref", "battery", "start", "end",
        "dispatch_mode", "dispatch", "outages", "events", "outage_policy", "cohort_policy"}, "configuration")
    policies = {"version": 1, "technology": "STANDALONE_GRID_BESS", "time_convention": "UTC_HOURLY_END_EXCLUSIVE",
        "degradation_convention": "ADDITIVE_CALENDAR_ACT365_AND_CYCLE", "efc_convention": "DC_TWO_WAY_OVER_2_NOMINAL_USABLE",
        "price_unit": "EUR_PER_MWH", "settlement_policy": "CANONICAL_FINANCIAL_PERIOD_END",
        "information_policy": "USER_DECLARED_EX_ANTE_FIXED_PLAN",
        "outage_policy": "SUSPEND_FIXED_PLAN_VALIDATE_EXPLICIT", "cohort_policy": "AGGREGATE_DC_POOL_NOMINAL_CYCLE_ALLOCATION"}
    if type(obj["version"]) is not int or any(obj[key] != expected for key, expected in policies.items()):
        raise BessInputError("BESS_POLICY: unsupported technology/time/unit/settlement/dispatch policy")
    source = text(obj["source_ref"], "source_ref")
    start, end = stamp(obj["start"]), stamp(obj["end"])
    hours = int((end - start).total_seconds() / 3600)
    if not 1 <= hours <= MAX_HOURS:
        raise BessInputError("BESS_HORIZON: 1-300000 exact hourly intervals required")
    values = obj["battery"]
    keys = set(Battery.__dataclass_fields__)
    exact(values, keys, "battery")
    fractional = {"soc_min", "soc_max", "charge_efficiency", "discharge_efficiency", "round_trip_efficiency",
                  "calendar_loss_per_year", "cycle_loss_per_efc", "minimum_soh"}
    positive = keys - fractional - {"initial_energy_mwh", "terminal_energy_mwh", "useful_life_years"}
    parsed = {key: number(value, key, maximum=1 if key in fractional else None, positive=key in positive)
              for key, value in values.items() if key != "useful_life_years"}
    parsed["useful_life_years"] = whole(values["useful_life_years"], "useful_life_years", 1, 50)
    battery = Battery(**parsed)
    if battery.usable_energy_mwh > battery.installed_energy_mwh or not battery.soc_min < battery.soc_max:
        raise BessInputError("BESS_CAPACITY: usable energy / SoC range invalid")
    if not battery.soc_min * battery.usable_energy_mwh <= battery.initial_energy_mwh <= battery.soc_max * battery.usable_energy_mwh:
        raise BessInputError("BESS_INITIAL_SOC: opening inventory outside SoC range")
    if battery.charge_efficiency == 0 or battery.discharge_efficiency == 0 or battery.minimum_soh == 0:
        raise BessInputError("BESS_EFFICIENCY: positive efficiencies and minimum SoH required")
    if abs(battery.round_trip_efficiency - battery.charge_efficiency * battery.discharge_efficiency) > Decimal("1e-12"):
        raise BessInputError("BESS_RTE: round-trip efficiency must equal charge efficiency times discharge efficiency")
    if abs(battery.duration_hours - battery.usable_energy_mwh / battery.discharge_power_mw) > Decimal("1e-12"):
        raise BessInputError("BESS_DURATION: usable MWh / discharge MW must equal duration hours")
    try:
        mode = DispatchMode(obj["dispatch_mode"])
    except (ValueError, TypeError) as exc:
        raise BessInputError("BESS_DISPATCH: unsupported mode") from exc
    rows = obj["dispatch"]
    required = {"charge_mw", "discharge_mw", "auxiliary_grid_mw", "available", "buy_price_eur_mwh",
                "sell_price_eur_mwh", "import_charge_eur_mwh", "export_charge_eur_mwh", "source_ref"}
    axis_key = "timestamp" if mode is DispatchMode.EXPLICIT_HOURLY else "utc_hour"
    expected_count = hours if mode is DispatchMode.EXPLICIT_HOURLY else 24
    if not isinstance(rows, list) or len(rows) != expected_count:
        raise BessInputError("BESS_DISPATCH: complete contiguous hourly timeline or exactly 24 daily UTC rows required")
    points = []
    from datetime import timedelta
    for index, row in enumerate(rows):
        exact(row, required | {axis_key}, "dispatch row")
        coordinate = stamp(row[axis_key]) if mode is DispatchMode.EXPLICIT_HOURLY else whole(row[axis_key], "utc_hour", 0, 23)
        expected = start + timedelta(hours=index) if mode is DispatchMode.EXPLICIT_HOURLY else index
        if coordinate != expected:
            raise BessInputError("BESS_CONTINUITY: duplicate, missing or reordered dispatch hour")
        if type(row["available"]) is not bool:
            raise BessInputError("BESS_AVAILABILITY: explicit Boolean required")
        numeric = {k: number(row[k], k) for k in required - {"available", "source_ref"}}
        points.append(DispatchPoint(coordinate, **numeric, available=row["available"], source_ref=text(row["source_ref"], "dispatch source")))
    outages = []
    if not isinstance(obj["outages"], list) or len(obj["outages"]) > 1000:
        raise BessInputError("BESS_OUTAGE: bounded outage list required")
    for row in obj["outages"]:
        exact(row, {"start", "end", "source_ref"}, "outage")
        a, b = stamp(row["start"]), stamp(row["end"])
        if not start <= a < b <= end or (outages and a < outages[-1].end):
            raise BessInputError("BESS_OUTAGE: ordered nonoverlapping in-horizon outage required")
        outages.append(Outage(a, b, text(row["source_ref"], "outage source")))
    events = []
    if not isinstance(obj["events"], list) or len(obj["events"]) > 24:
        raise BessInputError("BESS_EVENT: bounded event list required")
    for row in obj["events"]:
        exact(row, {"at", "kind", "installed_energy_mwh", "usable_energy_mwh", "cost_keur", "useful_life_years",
                    "source_ref", "tax_book_policy"}, "event")
        at = stamp(row["at"])
        try:
            kind = EventKind(row["kind"])
        except (ValueError, TypeError) as exc:
            raise BessInputError("BESS_EVENT: unsupported event") from exc
        if not start <= at < end or (events and at <= events[-1].at) or row["tax_book_policy"] != "UNRESOLVED":
            raise BessInputError("BESS_EVENT: ordered dated events, unresolved book/tax policy required")
        installed = number(row["installed_energy_mwh"], "event installed MWh", positive=True)
        usable = number(row["usable_energy_mwh"], "event usable MWh", positive=True)
        if usable > installed:
            raise BessInputError("BESS_EVENT: usable energy exceeds installed energy")
        events.append(Augmentation(at, kind, installed, usable, number(row["cost_keur"], "event cost", positive=True),
            whole(row["useful_life_years"], "event useful_life_years", 1, 50), text(row["source_ref"], "event source"), "UNRESOLVED"))
    return BessConfiguration(battery, start, end, mode, tuple(points), tuple(outages), tuple(events), source,
                             json.dumps(obj, sort_keys=True, separators=(",", ":"), allow_nan=False))
