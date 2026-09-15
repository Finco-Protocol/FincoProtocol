"""
app.v2.scenario_kpi_projection — thin authoritative KPI formatter for Scenario Compare
and Sensitivity output surfaces.

Authority contract:
  Every scalar displayed in Scenario Compare or Sensitivity is sourced exclusively
  from an authoritative RuntimeResult / run_project() kpis dict.  This module
  formats those raw floats into display strings using the canonical KPI_CATALOG
  defined in output_metric_projection — one catalog for the whole application.

No financial computation. No interpolation. No independent calculation.
No separate KPI catalog — imports from output_metric_projection.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from app.v2.output_metric_projection import (
    KPI_CATALOG,
    OutputMetricProjection,
    _safe_float,
    _apply_fmt,
    build_output_metric_projection,
)

_NA = "—"


def _fmt(v: Any, fmt: str) -> str:
    """Format raw numeric value using canonical formatter.

    Delegates to output_metric_projection._safe_float() and _apply_fmt()
    so there is exactly one formatting definition for all surfaces.
    """
    f = _safe_float(v)
    if f is None:
        return _NA
    return _apply_fmt(f, fmt)


def _raw(v: Any, fmt: str = "") -> Optional[float]:
    """Return raw float for delta arithmetic, or None if unavailable."""
    return _safe_float(v)


@dataclass(frozen=True)
class ScenarioKpiRow:
    """One KPI row across N scenarios for the compare table."""
    key: str
    label: str
    fmt: str
    values: list[str]      # formatted display strings, one per scenario
    deltas: list[str]      # delta vs first scenario ("—" for base, "+1.23%" etc.)
    raw_values: list[Optional[float]]


@dataclass(frozen=True)
class ScenarioProjection:
    """Formatted KPI output for one scenario (for compare or sensitivity)."""
    scenario_id: Optional[str]
    scenario_name: str
    state: str             # "CLEAN" | "STALE" | "NOT_RUN"
    ran_at: str
    kpis: dict[str, str]          # key → formatted display string
    kpis_raw: dict[str, Optional[float]]  # key → raw float (None if unavailable)
    metrics: dict[str, OutputMetricProjection] = None  # canonical OutputMetricProjection objects


def build_scenario_projection(
    scenario_name: str,
    runtime_summary: Optional[dict],
    ran_at: Optional[str],
    is_stale: bool,
) -> ScenarioProjection:
    """Build a ScenarioProjection from a persisted runtime_summary dict.

    runtime_summary must be the raw engine kpis dict (raw floats).
    No financial computation performed here — only formatting via the
    canonical KPI_CATALOG from output_metric_projection.
    """
    rs = runtime_summary or {}
    if not rs:
        state = "NOT_RUN"
    elif is_stale:
        state = "STALE"
    else:
        state = "CLEAN"

    metrics: dict[str, OutputMetricProjection] = {}
    freshness = "not_run" if state == "NOT_RUN" else "stale" if state == "STALE" else "current"
    for entry in KPI_CATALOG:
        key, _label, _unit, fmt, _source = entry
        v = rs.get(key)
        metrics[key] = build_output_metric_projection(
            key, v, freshness=freshness, run_timestamp=ran_at
        )

    # kpis / kpis_raw derived from metrics — not independent authority
    kpis: dict[str, str] = {k: m.display_value for k, m in metrics.items()}
    kpis_raw: dict[str, Optional[float]] = {k: m.raw_value for k, m in metrics.items()}

    return ScenarioProjection(
        scenario_id=None,
        scenario_name=scenario_name,
        state=state,
        ran_at=(ran_at or "")[:16].replace("T", " "),
        kpis=kpis,
        kpis_raw=kpis_raw,
        metrics=metrics,
    )


def build_compare_rows(projections: list[ScenarioProjection]) -> list[ScenarioKpiRow]:
    """Build KPI comparison rows from a list of ScenarioProjection objects.

    Sources display_value and raw_value exclusively from p.metrics[key]
    (OutputMetricProjection).  No string parsing.  No separate kpis/kpis_raw
    dictionaries consulted.

    Delta rule: raw float delta, formatted with sign — never string parsing.
    0.085 vs 0.070 → raw delta -0.015 → display "-1.50%".
    """
    rows: list[ScenarioKpiRow] = []
    for entry in KPI_CATALOG:
        key, label, _unit, fmt, _source = entry
        # Source exclusively from metrics (OutputMetricProjection)
        metrics_per_proj = [
            (p.metrics or {}).get(key)
            for p in projections
        ]
        vals = [
            m.display_value if m is not None else _NA
            for m in metrics_per_proj
        ]
        raw_vals = [
            m.raw_value if m is not None else None
            for m in metrics_per_proj
        ]
        base_raw = raw_vals[0] if raw_vals else None

        deltas: list[str] = []
        for i, rv in enumerate(raw_vals):
            if i == 0:
                deltas.append("—")
            elif rv is None or base_raw is None:
                deltas.append(_NA)
            else:
                d = rv - base_raw
                if fmt == "pct":
                    deltas.append(f"{d * 100:+.2f}%")
                elif fmt == "ratio":
                    deltas.append(f"{d:+.2f}x")
                elif fmt == "keur":
                    deltas.append(f"{d:+,.0f} kEUR")
                else:
                    deltas.append(f"{d:+.2f}")

        rows.append(ScenarioKpiRow(
            key=key,
            label=label,
            fmt=fmt,
            values=vals,
            deltas=deltas,
            raw_values=raw_vals,
        ))
    return rows
