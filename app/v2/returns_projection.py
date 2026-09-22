"""Workbook V2 Returns presentation over persisted Last Run evidence.

This module is deliberately projection-only.  It accepts the immutable
``RuntimeResult`` reconstructed from workspace persistence and never calls a
financial engine or derives sponsor economics.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional

from app.workbook.runtime_projection import thaw_runtime_payload


NOT_AVAILABLE = "NOT AVAILABLE"


@dataclass(frozen=True)
class ReturnsMetric:
    key: str
    label: str
    value: Optional[float]
    display: str
    unit: str
    source: str


@dataclass(frozen=True)
class ReturnsProjection:
    state: str
    has_runtime: bool
    scenario_name: str
    ran_at: str
    metrics: tuple[ReturnsMetric, ...]
    sponsor_rows: tuple[dict[str, Any], ...]
    distribution_rows: tuple[dict[str, Any], ...]
    sponsor_available: bool
    distribution_available: bool
    sponsor_source: str
    distribution_source: str


def _number(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    if not isinstance(value, (int, float)):
        return None
    return float(value)


def _fmt(value: Optional[float], kind: str) -> str:
    if value is None:
        return NOT_AVAILABLE
    if kind == "percent":
        return f"{value * 100:,.2f}%"
    if kind == "multiple":
        return f"{value:,.2f}x"
    return f"{value:,.0f} kEUR"


def _metric(key: str, label: str, value: Any, kind: str, source: str) -> ReturnsMetric:
    parsed = _number(value)
    unit = {"percent": "%", "multiple": "x", "keur": "kEUR"}[kind]
    return ReturnsMetric(key, label, parsed, _fmt(parsed, kind), unit, source)


def _last_run_scenario(ws: Any) -> str:
    identity = getattr(ws, "last_runtime_identity", None)
    if isinstance(identity, Mapping):
        name = identity.get("scenario_name")
        if isinstance(name, str) and name.strip():
            return name.strip()
    scenario_id = getattr(ws, "last_runtime_scenario_id", None)
    if isinstance(scenario_id, str) and scenario_id.strip():
        return f"Scenario ID: {scenario_id.strip()}"
    return NOT_AVAILABLE


def build_returns_projection(
    rr: Any,
    ws: Any,
    *,
    runtime_is_stale: Optional[bool] = None,
) -> ReturnsProjection:
    """Project persisted Returns evidence without calculating economics."""
    if rr is None:
        return ReturnsProjection(
            state="NOT_RUN",
            has_runtime=False,
            scenario_name="",
            ran_at="",
            metrics=(),
            sponsor_rows=(),
            distribution_rows=(),
            sponsor_available=False,
            distribution_available=False,
            sponsor_source="",
            distribution_source="",
        )

    runtime = thaw_runtime_payload(rr.runtime_summary or {})
    sponsor = thaw_runtime_payload(rr.sponsor_schedule or {})
    distribution = thaw_runtime_payload(rr.distribution_schedule or {})
    sponsor_summary = sponsor.get("summary") if isinstance(sponsor, dict) else None
    sponsor_summary = sponsor_summary if isinstance(sponsor_summary, dict) else {}

    sponsor_periods = sponsor.get("periods") if isinstance(sponsor, dict) else None
    sponsor_periods = sponsor_periods if isinstance(sponsor_periods, list) else []
    distribution_periods = (
        distribution.get("periods") if isinstance(distribution, dict) else None
    )
    distribution_periods = (
        distribution_periods if isinstance(distribution_periods, list) else []
    )

    metrics = (
        _metric("project_irr", "Project IRR", runtime.get("project_irr"), "percent",
                "RuntimeResult.runtime_summary.project_irr"),
        _metric("equity_irr", "Equity IRR", runtime.get("equity_irr"), "percent",
                "RuntimeResult.runtime_summary.equity_irr"),
        _metric("total_equity_invested", "Total Equity Invested",
                sponsor_summary.get("total_legal_equity_contributed_keur"), "keur",
                "RuntimeResult.sponsor_schedule.summary.total_legal_equity_contributed_keur"),
        _metric("total_shl_funded", "Total SHL Funded",
                sponsor_summary.get("total_shl_cash_contributed_keur"), "keur",
                "RuntimeResult.sponsor_schedule.summary.total_shl_cash_contributed_keur"),
        _metric("total_sponsor_distributions", "Total Sponsor Distributions",
                sponsor_summary.get("total_legal_equity_distributions_keur"), "keur",
                "RuntimeResult.sponsor_schedule.summary.total_legal_equity_distributions_keur"),
        _metric("sponsor_net_cash_flow", "Sponsor Net Cash Flow", None, "keur",
                "Not persisted by the canonical clean sponsor schedule"),
        _metric("sponsor_moic", "Sponsor MOIC",
                sponsor_summary.get("total_sponsor_moic"), "multiple",
                "RuntimeResult.sponsor_schedule.summary.total_sponsor_moic"),
    )

    return ReturnsProjection(
        state="STALE" if (
            bool(getattr(ws, "dirty", False))
            if runtime_is_stale is None else runtime_is_stale
        ) else "CLEAN",
        has_runtime=True,
        scenario_name=_last_run_scenario(ws),
        ran_at=getattr(rr, "ran_at", "") or "",
        metrics=metrics,
        sponsor_rows=tuple(dict(row) for row in sponsor_periods if isinstance(row, Mapping)),
        distribution_rows=tuple(
            dict(row) for row in distribution_periods if isinstance(row, Mapping)
        ),
        sponsor_available=bool(sponsor_periods),
        distribution_available=bool(distribution_periods),
        sponsor_source=(sponsor.get("source", "") if isinstance(sponsor, dict) else ""),
        distribution_source=(
            distribution.get("summary", {}).get("distribution_source", "")
            if isinstance(distribution, dict)
            and isinstance(distribution.get("summary"), dict)
            else ""
        ),
    )
