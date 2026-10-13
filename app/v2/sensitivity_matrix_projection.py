"""Two-driver sensitivity matrix — pure request validation and result projection (M3).

No financial arithmetic of the model lives here.  This module only:
  * declares which canonical drivers can be combined, in which unit, and within which bounds;
  * validates levels / threshold requests (fail closed);
  * turns the raw KPI values the canonical runner returned into a deterministic, accessible matrix:
    base value, deltas, threshold status per cell and the adjacent pairs that bracket a crossing.

Break-even is NEVER interpolated: a bracket only states that two adjacent evaluated cells disagree.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Mapping, Optional, Sequence

from app.v2.output_metric_projection import KPI_CATALOG, _apply_fmt, _safe_float

MAX_LEVELS_PER_AXIS = 5
MIN_LEVELS_PER_AXIS = 3
MAX_CELLS = MAX_LEVELS_PER_AXIS * MAX_LEVELS_PER_AXIS

STATUS_OK = "OK"
STATUS_FAILED = "FAILED"
STATUS_UNAVAILABLE = "UNAVAILABLE"
TH_PASS, TH_FAIL, TH_UNAVAILABLE, TH_NONE = "PASS", "FAIL", "UNAVAILABLE", "NOT_SET"

#: How a shock is applied.  ``FIELD`` = one canonical ProjectInputSet field (applied BEFORE materialisation);
#: ``TYPED`` = the existing typed-ProjectInputs shock of the legacy sensitivity service (applied AFTER the
#: CAPEX/OPEX sub-line fold, BEFORE financing materialisation).
FIELD, TYPED = "FIELD", "TYPED"
PCT, ABS = "pct", "abs"


@dataclass(frozen=True)
class DriverSpec:
    key: str
    label: str
    unit_label: str           # "%", "bps", "pp"
    apply: str                # FIELD | TYPED
    mode: str                 # PCT (relative) | ABS (additive in field units)
    field_id: Optional[str]
    fallback_field_id: Optional[str]
    field_scale: float        # level -> field-unit factor for ABS mode (bps -> pp = 0.01)
    default_levels: tuple[float, ...]        # the explicit 5-level choice
    max_abs_level: float
    verticals: frozenset[str]
    typed_shock: Optional[str] = None   # key understood by app.services.sensitivity_service._apply_shock

    @property
    def default_levels_3(self) -> tuple[float, ...]:
        """Default 3-level axis: Base and the inner (half-range) shocks of the 5-level default."""
        inner = self.default_levels[3]
        return (-inner, 0.0, inner)

    def defaults_for(self, size: int) -> tuple[float, ...]:
        return self.default_levels if size == 5 else self.default_levels_3


_REN = frozenset({"solar", "wind"})
_DC = frozenset({"data_center"})
_ALL = _REN | _DC

DRIVERS: dict[str, DriverSpec] = {d.key: d for d in (
    DriverSpec("capex", "CAPEX", "%", TYPED, PCT, None, None, 1.0, (-20, -10, 0, 10, 20), 50, _ALL, "capex"),
    DriverSpec("opex", "OPEX", "%", TYPED, PCT, None, None, 1.0, (-20, -10, 0, 10, 20), 50, _ALL, "opex"),
    DriverSpec("tariff", "PPA / Tariff price", "%", FIELD, PCT, "revenue.ppa.base_tariff",
               "revenue.ppa.tariff_legacy", 1.0, (-20, -10, 0, 10, 20), 50, _REN),
    DriverSpec("merchant_price", "Merchant price", "%", TYPED, PCT, None, None, 1.0, (-20, -10, 0, 10, 20), 50,
               _REN, "merchant_price"),
    DriverSpec("generation", "Yield (P50 hours)", "%", FIELD, PCT, "project_setup.technical.p50_hours", None, 1.0,
               (-10, -5, 0, 5, 10), 30, _REN),
    DriverSpec("interest_rate", "Senior interest rate", "bps", FIELD, ABS, "debt.senior.interest_rate_pct", None,
               0.01, (-200, -100, 0, 100, 200), 500, _ALL),
    DriverSpec("gearing", "Senior gearing", "pp", FIELD, ABS, "debt.senior.gearing_pct", None, 1.0,
               (-10, -5, 0, 5, 10), 20, _ALL),
    DriverSpec("service_price", "Service price (EUR/kW/month)", "%", FIELD, PCT, "revenue.data_center.service_price",
               None, 1.0, (-20, -10, 0, 10, 20), 50, _DC),
    DriverSpec("dc_occupancy", "Stabilised occupancy", "pp", FIELD, ABS, "revenue.data_center.occupancy_stabilized",
               None, 1.0, (-10, -5, 0, 5, 10), 20, _DC),
    DriverSpec("dc_it_mw", "IT load capacity", "%", FIELD, PCT, "project_setup.technical.capacity_mw", None, 1.0,
               (-20, -10, 0, 10, 20), 50, _DC),
    DriverSpec("dc_pue", "PUE", "%", FIELD, PCT, "revenue.data_center.pue", None, 1.0, (-10, -5, 0, 5, 10), 30, _DC),
    DriverSpec("dc_electricity_price", "Electricity price", "%", FIELD, PCT, "revenue.data_center.electricity_price",
               None, 1.0, (-20, -10, 0, 10, 20), 50, _DC),
)}

#: Canonical application order of TYPED shocks: they touch disjoint ProjectInputs fields, so the order cannot change
#: the result; it is fixed anyway so the contract is explicit and a test can assert order-independence.
TYPED_ORDER = ("capex", "opex", "merchant_price")


class MatrixRequestError(ValueError):
    """Typed, user-presentable validation failure (HTTP 422)."""

    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code, self.message = code, message


def vertical_key(project_type: str | None) -> str | None:
    key = (project_type or "").strip().lower()
    if key in ("solar", "solar_pv"):
        return "solar"
    if key in ("wind", "wind_onshore"):
        return "wind"
    if key in ("data center", "data_center", "datacenter"):
        return "data_center"
    return None


def drivers_for(vertical: str | None) -> list[DriverSpec]:
    return [d for d in DRIVERS.values() if vertical in d.verticals]


DEFAULT_GRID_SIZE = 3
GRID_SIZES = (3, 5)


def parse_grid_size(raw: str | int | None) -> int:
    """3 (default, 9 evaluations) or the explicit 5 (25 evaluations)."""
    if raw is None or str(raw).strip() == "":
        return DEFAULT_GRID_SIZE
    try:
        size = int(str(raw).strip())
    except ValueError:
        size = -1
    if size not in GRID_SIZES:
        raise MatrixRequestError("MATRIX_GRID_INVALID", f"Grid size must be one of {GRID_SIZES}.")
    return size


def parse_levels(raw: str | Sequence[float] | None, spec: DriverSpec, size: int = DEFAULT_GRID_SIZE) -> tuple[float, ...]:
    """Validated, ascending, unique, finite levels in the driver's displayed unit (size-dependent default when blank)."""
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        values: list[float] = [float(v) for v in spec.defaults_for(size)]
    else:
        items = raw.split(",") if isinstance(raw, str) else list(raw)
        values = []
        for item in items:
            try:
                number = float(str(item).strip())
            except (TypeError, ValueError):
                raise MatrixRequestError("MATRIX_LEVEL_INVALID", f"{spec.label}: {item!r} is not a number.") from None
            if not math.isfinite(number):
                raise MatrixRequestError("MATRIX_LEVEL_INVALID", f"{spec.label}: levels must be finite.")
            values.append(number)
    if len(values) < MIN_LEVELS_PER_AXIS or len(values) > MAX_LEVELS_PER_AXIS:
        raise MatrixRequestError("MATRIX_LEVEL_COUNT",
                                 f"{spec.label}: {MIN_LEVELS_PER_AXIS} to {MAX_LEVELS_PER_AXIS} levels are required "
                                 f"(received {len(values)}).")
    if len(set(values)) != len(values):
        raise MatrixRequestError("MATRIX_LEVEL_DUPLICATE", f"{spec.label}: levels must be distinct.")
    for number in values:
        if abs(number) > spec.max_abs_level:
            raise MatrixRequestError("MATRIX_LEVEL_OUT_OF_BOUNDS",
                                     f"{spec.label}: |{number:g}| exceeds the V1 bound of "
                                     f"{spec.max_abs_level:g} {spec.unit_label}.")
        if spec.mode == PCT and number <= -100:
            raise MatrixRequestError("MATRIX_LEVEL_OUT_OF_BOUNDS", f"{spec.label}: a change of -100% or lower is invalid.")
    return tuple(sorted(values))


def resolve_pair(driver_a: str, driver_b: str, vertical: str | None) -> tuple[DriverSpec, DriverSpec]:
    if vertical is None:
        raise MatrixRequestError("MATRIX_VERTICAL_UNSUPPORTED",
                                 "Two-driver sensitivity supports Solar, Wind and Data Center projects only.")
    for key in (driver_a, driver_b):
        spec = DRIVERS.get(key)
        if spec is None:
            raise MatrixRequestError("MATRIX_DRIVER_UNSUPPORTED", f"Unknown driver {key!r}.")
        if vertical not in spec.verticals:
            raise MatrixRequestError("MATRIX_DRIVER_UNSUPPORTED",
                                     f"Driver {key!r} is not available for this project type.")
    if driver_a == driver_b:
        raise MatrixRequestError("MATRIX_DRIVER_DUPLICATE", "Select two different drivers.")
    return DRIVERS[driver_a], DRIVERS[driver_b]


#: Catalog metrics the matrix CANNOT obtain from the canonical run result, with the reason.  They are not offered.
#: ``total_cfads_keur`` is a documented raw-authority gap of the catalog itself: neither ``result["kpis"]`` nor the
#: debt / sponsor schedule summaries of ``run_project`` carry it, and no CFADS is recomputed here.
UNSUPPORTED_METRICS: dict[str, str] = {
    "total_cfads_keur": "Total CFADS is not produced by the canonical run result (documented catalog gap); "
                        "it is not recomputed here.",
}
#: Offered, but legitimately UNAVAILABLE unless the project configures the basis; flagged in the selector.
CONDITIONAL_METRICS: dict[str, str] = {
    "project_npv_keur": "only when a valuation basis is configured",
    "equity_npv_keur": "only when a valuation basis is configured",
    "min_llcr": "only when the run produces an LLCR",
}


def supported_metrics() -> list[dict[str, str]]:
    """Selectable metrics: the existing catalog minus entries the canonical run cannot supply."""
    return [{"key": k, "label": lbl, "unit": unit, "fmt": fmt,
             "note": CONDITIONAL_METRICS.get(k, "")}
            for k, lbl, unit, fmt, _src in KPI_CATALOG if k not in UNSUPPORTED_METRICS]


def resolve_metric(key: str) -> tuple:
    entry = next((c for c in KPI_CATALOG if c[0] == key), None)
    if entry is None:
        raise MatrixRequestError("MATRIX_METRIC_UNSUPPORTED", f"Unknown metric {key!r}.")
    if key in UNSUPPORTED_METRICS:
        raise MatrixRequestError("MATRIX_METRIC_UNSUPPORTED", UNSUPPORTED_METRICS[key])
    return entry


def parse_threshold(raw: str | None, fmt: str) -> Optional[float]:
    """Explicit user threshold in DISPLAY units (``9`` = 9 % for a percentage metric).  None when blank."""
    if raw is None or not str(raw).strip():
        return None
    try:
        number = float(str(raw).strip().replace("%", "").replace("x", ""))
    except ValueError:
        raise MatrixRequestError("MATRIX_THRESHOLD_INVALID", f"Threshold {raw!r} is not a number.") from None
    if not math.isfinite(number):
        raise MatrixRequestError("MATRIX_THRESHOLD_INVALID", "Threshold must be finite.")
    return number / 100.0 if fmt == "pct" else number


def format_delta(delta: Optional[float], fmt: str) -> str:
    if delta is None:
        return "—"
    if fmt == "pct":
        return f"{delta * 100:+.2f} pp"
    if fmt == "ratio":
        return f"{delta:+.3f}x"
    return f"{delta:+,.0f} kEUR"


def classify(value: Optional[float], threshold: Optional[float]) -> str:
    if threshold is None:
        return TH_NONE
    if value is None:
        return TH_UNAVAILABLE
    return TH_PASS if value >= threshold else TH_FAIL


def level_label(spec: DriverSpec, level: float) -> str:
    if level == 0:
        return "Base"
    sign = "+" if level > 0 else "−"
    return f"{sign}{abs(level):g} {spec.unit_label}"


def build_matrix(*, spec_a: DriverSpec, spec_b: DriverSpec, levels_a: Sequence[float], levels_b: Sequence[float],
                 metric_key: str, cell_outputs: Mapping[tuple[int, int], Mapping[str, Any]],
                 base_output: Optional[Mapping[str, Any]], threshold: Optional[float],
                 shock_info: Mapping[tuple[int, int], Mapping[str, Any]]) -> dict[str, Any]:
    """Project raw runner outputs into the matrix view model.  Pure; deterministic; no model calls."""
    entry = resolve_metric(metric_key)
    _key, label, unit, fmt, _source = entry

    def read(output: Optional[Mapping[str, Any]]) -> tuple[str, Optional[float], str]:
        if output is None:
            return STATUS_UNAVAILABLE, None, "No evaluation."
        if "error" in output:
            return STATUS_FAILED, None, str(output["error"])
        raw = _safe_float((output.get("kpis") or {}).get(metric_key))
        return (STATUS_OK, raw, "") if raw is not None else (STATUS_UNAVAILABLE, None, "Metric not produced by the run.")

    base_status, base_value, base_reason = read(base_output)
    cells: list[dict[str, Any]] = []
    grid: dict[tuple[int, int], dict[str, Any]] = {}
    for j, lb in enumerate(levels_b):
        for i, la in enumerate(levels_a):
            status, value, reason = read(cell_outputs.get((i, j)))
            injected = shock_info.get((i, j), {})
            if injected.get("error"):
                status, value, reason = STATUS_FAILED, None, str(injected["error"])
            delta = (value - base_value) if (value is not None and base_value is not None) else None
            rel = (delta / abs(base_value) * 100.0) if (delta is not None and base_value not in (None, 0)
                                                        and fmt == "keur") else None
            cell = {
                "i": i, "j": j, "level_a": la, "level_b": lb,
                "label_a": level_label(spec_a, la), "label_b": level_label(spec_b, lb),
                "status": status, "reason": reason, "raw": value,
                "display": _apply_fmt(value, fmt) if value is not None else "—",
                "delta": delta, "delta_display": format_delta(delta, fmt),
                "delta_pct": None if rel is None else f"{rel:+.1f}%",
                "threshold_status": classify(value, threshold) if status != STATUS_FAILED
                else (TH_UNAVAILABLE if threshold is not None else TH_NONE),
                "inputs": dict(injected.get("inputs", {})),
                "is_base": la == 0 and lb == 0,
            }
            cells.append(cell)
            grid[(i, j)] = cell

    brackets: list[dict[str, Any]] = []
    definite = {TH_PASS, TH_FAIL}
    if threshold is not None:
        for j in range(len(levels_b)):
            for i in range(len(levels_a)):
                here = grid[(i, j)]
                for di, dj, axis in ((1, 0, "A"), (0, 1, "B")):
                    other = grid.get((i + di, j + dj))
                    if other is None:
                        continue
                    if {here["threshold_status"], other["threshold_status"]} == definite:
                        brackets.append({
                            "axis": axis, "from": (here["label_a"], here["label_b"]),
                            "to": (other["label_a"], other["label_b"]),
                            "from_status": here["threshold_status"], "to_status": other["threshold_status"],
                            "note": "A threshold crossing lies between these two evaluated cells; "
                                    "no boundary value is inferred.",
                        })
    counts = {s: sum(1 for c in cells if c["status"] == s) for s in (STATUS_OK, STATUS_FAILED, STATUS_UNAVAILABLE)}
    th_counts = {s: sum(1 for c in cells if c["threshold_status"] == s)
                 for s in (TH_PASS, TH_FAIL, TH_UNAVAILABLE, TH_NONE)}
    return {
        "metric": {"key": metric_key, "label": label, "unit": unit, "fmt": fmt},
        "driver_a": {"key": spec_a.key, "label": spec_a.label, "unit": spec_a.unit_label,
                     "levels": [{"value": v, "label": level_label(spec_a, v)} for v in levels_a]},
        "driver_b": {"key": spec_b.key, "label": spec_b.label, "unit": spec_b.unit_label,
                     "levels": [{"value": v, "label": level_label(spec_b, v)} for v in levels_b]},
        "base": {"status": base_status, "raw": base_value, "reason": base_reason,
                 "display": _apply_fmt(base_value, fmt) if base_value is not None else "—"},
        "threshold": None if threshold is None else {
            "raw": threshold, "display": _apply_fmt(threshold, fmt), "comparator": ">=",
            "origin": "User-provided for this analysis; not a lender covenant or FINCO-authorised threshold."},
        "cells": cells,
        "rows": [[grid[(i, j)] for i in range(len(levels_a))] for j in range(len(levels_b))],
        "brackets": brackets,
        "counts": counts,
        "threshold_counts": th_counts,
    }
