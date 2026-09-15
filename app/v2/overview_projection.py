"""app.v2.overview_projection — OverviewProjection for UI-3A decision dashboard.

Read-only presentation projection. No financial arithmetic.
All KPI values come from the authoritative RuntimeResult.runtime_summary
(pre-formatted strings produced by build_runtime_summary) or from
debt_schedule.summary (raw floats formatted here with _fmt_x).

Gaps documented at module level:
  equity_npv_keur  — not in runtime_summary; not in any persisted schedule
  plcr             — not in any persisted output in Phase B4

Architecture:
  build_overview_projection(rr, is_dirty, pis)
      → OverviewProjection
      → consumed by router._build_overview_ctx() → template context
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.workbook.runtime_projection import (
    RuntimeProjectionState,
    classify_schedule_state,
    extract_periods,
    thaw_runtime_payload,
)
from app.v2.output_metric_projection import (
    OutputMetricProjection,
    build_overview_metric_projections,
    extract_numeric_runtime_kpis,
)

NOT_AVAILABLE = "NOT_AVAILABLE"


def _fmt_x(v: Any) -> str:
    """Format a raw float as 'X.XXx', returning NOT_AVAILABLE for None/NaN/inf."""
    if v is None:
        return NOT_AVAILABLE
    try:
        f = float(v)
        if f != f or abs(f) == float("inf"):
            return NOT_AVAILABLE
        return f"{f:.2f}x"
    except (TypeError, ValueError):
        return NOT_AVAILABLE


@dataclass(frozen=True)
class OverviewProjection:
    """Immutable presentation bundle for the Overview dashboard sheet.

    KPI string fields carry either a pre-formatted value from runtime_summary
    (e.g. "8.50%", "1.45x", "45,000 kEUR") or the sentinel "NOT_AVAILABLE".
    No financial arithmetic is performed in this class or its builder.

    Documented gaps (Phase B4):
        equity_npv  — equity NPV not in runtime_summary nor any schedule payload
        plcr        — PLCR not in any persisted output
    """

    # ── State ─────────────────────────────────────────────────────────── #
    state: RuntimeProjectionState          # NOT_RUN / CLEAN / STALE / UNAVAILABLE
    snapshot_id: Optional[str]             # compact run id or None
    ran_at: Optional[str]                  # ISO-8601 string or None

    # ── KPIs from runtime_summary (pre-formatted strings) ─────────────── #
    project_irr: str                       # "8.50%" | NOT_AVAILABLE
    equity_irr: str                        # "12.30%" | NOT_AVAILABLE
    avg_dscr: str                          # "1.45x"  | NOT_AVAILABLE
    min_dscr: str                          # "1.32x"  | NOT_AVAILABLE
    total_capex_keur: str                  # "45,000 kEUR" | NOT_AVAILABLE
    senior_debt_keur: str                  # "27,000 kEUR" | NOT_AVAILABLE
    total_revenue_keur: str
    total_ebitda_keur: str
    total_cfads_keur: str

    # ── KPIs from debt_schedule.summary (raw → formatted here) ─────────── #
    min_llcr: str                          # "1.28x" | NOT_AVAILABLE
    target_dscr: str                       # "1.30x" | NOT_AVAILABLE
    periods_in_lockup: str                 # "0" | NOT_AVAILABLE

    # ── Phase B4 gaps (not in any persisted output) ────────────────────── #
    equity_npv: str = NOT_AVAILABLE
    plcr: str = NOT_AVAILABLE

    # ── Chart data — raw debt schedule periods (thawed dicts) ────────────── #
    # None when state is NOT_RUN or debt schedule unavailable.
    # Each period dict has: date, is_operation, senior_balance_keur,
    # senior_ds_keur, senior_principal_keur, senior_interest_keur, dscr.
    chart_debt_periods: Optional[List[Dict]] = field(default=None)

    # ── Project context (from ProjectInputs — display strings) ──────────── #
    project_name: str = ""
    project_type: str = ""                 # template_source: "generic_solar" etc.
    country_iso: str = ""
    capacity_mw: str = ""                  # "50.0 MW"
    cod_year: str = ""                     # "2031-01-01"
    horizon_years: str = ""               # "20 years"
    gearing_pct: str = ""                  # "75.0%"
    senior_tenor_years: str = ""           # "15 years"
    input_target_dscr: str = ""            # "1.20x"

    # ── UI-3B: active scenario identity ──────────────────────────────────── #
    active_scenario_name: str = ""         # "Base Case" | scenario display name

    # ── UI-4B: normalized timestamp display (avoids Jinja slice) ─────────── #
    run_timestamp_display: str = ""        # "2026-09-08 14:32 UTC" | ""

    # ── UI-4A: canonical OutputMetricProjection objects (OUTPUT_METRIC_CONTRACT_ACTUALLY_WIRED) #
    # Templates render metric.display_value directly — no sentinel repair needed.
    output_metrics: Dict[str, OutputMetricProjection] = field(default_factory=dict)


def build_overview_projection(
    rr: Any,
    is_dirty: bool,
    pis: Any,
    active_scenario_name: str = "",
) -> OverviewProjection:
    """Build OverviewProjection from RuntimeResult + ProjectInputSet.

    Parameters
    ----------
    rr : RuntimeResult | None
        The current RuntimeResult; None when no run has been performed.
    is_dirty : bool
        Whether the workspace has unsaved edits since the last run.
    pis : ProjectInputSet
        Current editable input set — used for project context only.

    Returns
    -------
    OverviewProjection
        Immutable projection ready for template rendering.
    """
    # ── State classification (reuses existing debt-schedule classifier) ── #
    _debt_raw = getattr(rr, "debt_schedule", None) if rr else None
    debt_schedule = thaw_runtime_payload(_debt_raw) if _debt_raw else None
    state = classify_schedule_state(rr, debt_schedule, is_dirty)

    _has_runtime = rr is not None
    _snapshot_id: Optional[str] = (
        str(rr.snapshot_id) if _has_runtime and getattr(rr, "snapshot_id", None) else None
    )
    _ran_at: Optional[str] = (
        str(rr.ran_at) if _has_runtime and getattr(rr, "ran_at", None) else None
    )

    # ── KPIs: extract clean numerics from persisted runtime_summary ─────── #
    # extract_numeric_runtime_kpis() is fail-closed: only KPI_CATALOG keys,
    # only int/float (non-NaN, non-inf). Never calls rr.raw_kpis.
    _rs_raw = getattr(rr, "runtime_summary", None) if rr is not None else None
    _rs_thawed = thaw_runtime_payload(_rs_raw) if _rs_raw else {}
    rs: Dict[str, Any] = extract_numeric_runtime_kpis(_rs_thawed)

    _PCT_KEYS  = {"project_irr", "equity_irr"}
    _RATIO_KEYS = {"avg_dscr", "min_dscr"}
    _KEUR_KEYS  = {"total_capex_keur", "senior_debt_keur",
                   "total_revenue_keur", "total_ebitda_keur", "total_cfads_keur"}

    def _get(key: str) -> str:
        v = rs.get(key, NOT_AVAILABLE)
        if v is None or v == "":
            return NOT_AVAILABLE
        if isinstance(v, str):
            return v if v else NOT_AVAILABLE
        # Raw numeric value — format by key type
        try:
            f = float(v)
            if f != f or abs(f) == float("inf"):
                return NOT_AVAILABLE
            if key in _PCT_KEYS:
                return f"{f * 100:.2f}%"
            if key in _RATIO_KEYS:
                return f"{f:.2f}x"
            if key in _KEUR_KEYS:
                return f"{f:,.0f} kEUR"
            return str(v)
        except (TypeError, ValueError):
            return str(v)

    # ── min_llcr / target_dscr from debt_schedule.summary ─────────────── #
    _debt_summary: Dict[str, Any] = (
        debt_schedule.get("summary", {}) if debt_schedule else {}
    )
    min_llcr = _fmt_x(_debt_summary.get("min_llcr"))
    target_dscr_str = _fmt_x(_debt_summary.get("target_dscr"))
    _raw_lockup = _debt_summary.get("periods_in_lockup")
    periods_lockup = (
        str(int(_raw_lockup)) if _raw_lockup is not None else NOT_AVAILABLE
    )

    # ── Chart data: all debt schedule periods ─────────────────────────── #
    chart_debt_periods: Optional[List[Dict]] = None
    if debt_schedule:
        _all = extract_periods(debt_schedule, operational_only=False)
        if _all is not None:
            chart_debt_periods = _all

    # ── Project context from pis ──────────────────────────────────────── #
    _project_name = ""
    _project_type = getattr(pis, "template_source", "") or ""
    _country_iso = ""
    _capacity_mw = NOT_AVAILABLE
    _cod_year = NOT_AVAILABLE
    _horizon_years = NOT_AVAILABLE
    _gearing_pct = NOT_AVAILABLE
    _senior_tenor = NOT_AVAILABLE
    _input_target_dscr = NOT_AVAILABLE
    try:
        pi = pis.to_projectinputs()
        _project_name = getattr(pi.info, "name", "") or ""
        _country_iso = getattr(pi.info, "country_iso", "") or ""
        _cap = getattr(pi.technical, "capacity_mw", None)
        if _cap is not None:
            _capacity_mw = f"{float(_cap):.1f} MW"
        _cod = getattr(pi.info, "cod_date", None)
        if _cod is not None:
            _cod_year = str(_cod)[:10]
        _hy = getattr(pi.info, "horizon_years", None)
        if _hy is not None:
            _horizon_years = f"{int(_hy)} years"
        _gr = getattr(pi.financing, "gearing_ratio", None)
        if _gr is not None:
            _gearing_pct = f"{float(_gr) * 100:.1f}%"
        _st = getattr(pi.financing, "senior_tenor_years", None)
        if _st is not None:
            _senior_tenor = f"{int(_st)} years"
        _td = getattr(pi.financing, "target_dscr", None)
        if _td is not None:
            _input_target_dscr = _fmt_x(_td)
    except Exception:
        pass

    # ── UI-4B: normalize timestamp display in Python, not Jinja ─────────── #
    _run_ts_display = ""
    if _ran_at:
        try:
            _run_ts_display = _ran_at[:16].replace("T", " ") + " UTC"
        except Exception:
            _run_ts_display = ""

    # ── UI-4A: build canonical OutputMetricProjection objects from raw floats ── #
    _freshness = (
        "not_run" if state in (RuntimeProjectionState.NOT_RUN, RuntimeProjectionState.UNAVAILABLE)
        else "stale" if state == RuntimeProjectionState.STALE
        else "current"
    )
    _output_metrics = build_overview_metric_projections(
        rs,
        _debt_summary,
        freshness=_freshness,
        scenario_id=None,
        run_timestamp=_ran_at,
    )

    return OverviewProjection(
        state=state,
        snapshot_id=_snapshot_id,
        ran_at=_ran_at,
        project_irr=_get("project_irr"),
        equity_irr=_get("equity_irr"),
        avg_dscr=_get("avg_dscr"),
        min_dscr=_get("min_dscr"),
        total_capex_keur=_get("total_capex_keur"),
        senior_debt_keur=_get("senior_debt_keur"),
        total_revenue_keur=_get("total_revenue_keur"),
        total_ebitda_keur=_get("total_ebitda_keur"),
        total_cfads_keur=_get("total_cfads_keur"),
        min_llcr=min_llcr,
        target_dscr=target_dscr_str,
        periods_in_lockup=periods_lockup,
        chart_debt_periods=chart_debt_periods,
        project_name=_project_name,
        project_type=_project_type,
        country_iso=_country_iso,
        capacity_mw=_capacity_mw,
        cod_year=_cod_year,
        horizon_years=_horizon_years,
        gearing_pct=_gearing_pct,
        senior_tenor_years=_senior_tenor,
        input_target_dscr=_input_target_dscr,
        active_scenario_name=active_scenario_name or "",
        output_metrics=_output_metrics,
        run_timestamp_display=_run_ts_display,
    )
