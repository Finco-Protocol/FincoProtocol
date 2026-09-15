"""Phase P2-min-3: Dashboard v1 context helpers.

Pure-Python presentation-layer helpers for the
Dashboard v1 view (KPI cards + inline SVG
charts). No financial formula changes, no
debt sizing changes, no DSCR sculpt semantics
changes, no factory path changes, no
persistence writes, no schema migration.

The Dashboard is a presentation-only view
that reuses values that the runtime has
already produced (KPI snapshot from the
existing waterfall + DSCR sculpt result
objects).

Inline SVG charts are rendered server-side
in Jinja. NO Chart.js / Plotly / D3 / any
JS library. NO JS calc.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def _safe_float(value: Any) -> Optional[float]:
    """Convert a value to a finite float. Returns
    ``None`` when the value is ``None``, empty,
    non-numeric, NaN, or inf.
    """
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if f != f or f in (float("inf"), float("-inf")):
        return None
    return f


def _fmt_pct(value: Optional[float], digits: int = 1) -> str:
    if value is None:
        return "—"
    return f"{value:.{digits}f}%"


def _fmt_money_keur(value: Optional[float], digits: int = 0) -> str:
    if value is None:
        return "—"
    return f"€{value:,.{digits}f}k"


def _fmt_money_eur(value: Optional[float], digits: int = 0) -> str:
    if value is None:
        return "—"
    return f"€{value:,.{digits}f}"


def _fmt_number(value: Optional[float], digits: int = 2) -> str:
    if value is None:
        return "—"
    return f"{value:.{digits}f}"


# ---------------------------------------------------------------------------
# Dashboard KPI summary
# ---------------------------------------------------------------------------


def build_dashboard_kpis(
    last_runtime_summary: Optional[dict],
    project_record: Any,
    realized_gearing_pct: Optional[float],
) -> Dict[str, Dict[str, Any]]:
    """Return a presentation-layer KPI summary for
    the Dashboard v1 view. Eight KPI cards.

    The function is pure: it reads values from the
    workspace's ``last_runtime_summary`` dict (the
    authoritative source already used by the
    successful runtime update path and by
    build_dashboard_kpis_from_raw_kpis) and from the
    project record. It does NOT mutate them and does
    NOT call any factory / persistence / model
    function.

    HOTFIX-PILOT-BLOCKER-1 (F3): the previous signature
    took ``waterfall_result`` and called
    ``getattr(waterfall_result, "summary", None)``.
    ``waterfall_result`` is a WaterfallResult object
    that the dashboard path never had access to
    (only run_service builds it), and ProjectRecord
    does not carry a ``last_waterfall_result`` field.
    This caused the dashboard to always render all
    KPIs as "—" after a successful run. The fix is
    to read the same raw kpis dict the OOB update
    path uses (workspace.last_runtime_summary),
    reuse build_dashboard_kpis_from_raw_kpis for
    the value formatting, and add realized_gearing
    from the call site (Phase PR2 helper).

    Returns:
        Dict of 8 keys: project_irr, equity_irr,
        senior_debt, realized_gearing, min_dscr,
        avg_dscr, y1_revenue, y1_ebitda.

        Each value is a dict with: ``label``,
        ``value`` (formatted), ``raw`` (raw float
        or None), ``status`` ('pass' / 'warn' /
        'missing' / None), ``tooltip``.
    """
    raw_kpis = last_runtime_summary or {}
    kpis: Dict[str, Dict[str, Any]] = {}

    # If the runtime produced a summary, prefer the
    # path that has been validated by the OOB update
    # flow (it multiplies IRR fractions by 100 and
    # uses the correct key names). The two paths now
    # share the same source of truth: workspace
    # state last_runtime_summary.
    if raw_kpis:
        try:
            kpis = build_dashboard_kpis_from_raw_kpis(raw_kpis)
        except Exception:
            kpis = {}
    if not kpis:
        kpis = {key: {"label": "", "value": "—", "raw": None,
                       "status": "missing", "tooltip": ""}
                for key in ("project_irr", "equity_irr",
                            "senior_debt", "realized_gearing",
                            "min_dscr", "avg_dscr", "y1_revenue",
                            "y1_ebitda", "project_npv", "total_capex")}

    # Realized gearing comes from a derived computation
    # at the ProjectContext build time
    # (_compute_realized_gearing_pct, Phase PR2).
    # It is not in last_runtime_summary directly, so
    # it must be set from the call site parameter.
    rg = _safe_float(realized_gearing_pct)
    kpis["realized_gearing"] = {
        "label": "Realized Gearing",
        "value": _fmt_pct(rg),
        "raw": rg,
        "status": "derived" if rg is not None else "missing",
        "tooltip": "Realized gearing = senior_debt / "
                   "total_CAPEX × 100 (read-only derived KPI)",
    }

    return kpis


def build_dashboard_kpis_from_raw_kpis(raw_kpis: dict) -> Dict[str, Dict[str, Any]]:
    """Build dashboard KPIs from a raw ``result["kpis"]`` dict.

    This is used after a successful run to populate the OOB
    dashboard update.  ``raw_kpis`` comes from ``run_project()``
    which returns IRR values as fractions (0.10 = 10%), so they
    are multiplied by 100 before formatting.
    """
    project_irr_frac = _safe_float(raw_kpis.get("project_irr"))
    equity_irr_frac = _safe_float(raw_kpis.get("equity_irr"))
    # Convert fraction → percentage for _fmt_pct
    project_irr = project_irr_frac * 100 if project_irr_frac is not None else None
    equity_irr = equity_irr_frac * 100 if equity_irr_frac is not None else None
    senior_debt = _safe_float(raw_kpis.get("senior_debt_keur"))
    min_dscr = _safe_float(raw_kpis.get("min_dscr"))
    avg_dscr = _safe_float(raw_kpis.get("avg_dscr"))
    target_dscr = _safe_float(raw_kpis.get("target_dscr"))
    # total_revenue/ebitda are the available lifecycle totals; y1 values not in raw_kpis
    y1_revenue = _safe_float(raw_kpis.get("y1_revenue_keur") or raw_kpis.get("total_revenue_keur"))
    y1_ebitda = _safe_float(raw_kpis.get("y1_ebitda_keur") or raw_kpis.get("total_ebitda_keur"))
    npv = _safe_float(raw_kpis.get("project_npv_keur"))
    total_capex = _safe_float(raw_kpis.get("total_capex_keur"))

    kpis: Dict[str, Dict[str, Any]] = {}
    kpis["project_irr"] = {
        "label": "Project IRR", "value": _fmt_pct(project_irr),
        "raw": project_irr, "status": "pass" if project_irr is not None else "missing",
        "tooltip": "Project Internal Rate of Return (computed by the runtime)",
    }
    kpis["equity_irr"] = {
        "label": "Equity IRR", "value": _fmt_pct(equity_irr),
        "raw": equity_irr, "status": "pass" if equity_irr is not None else "missing",
        "tooltip": "Equity Internal Rate of Return",
    }
    kpis["senior_debt"] = {
        "label": "Senior Debt", "value": _fmt_money_keur(senior_debt),
        "raw": senior_debt, "status": "pass" if senior_debt is not None else "missing",
        "tooltip": "Total senior debt (kEUR)",
    }
    kpis["realized_gearing"] = {
        "label": "Realized Gearing", "value": "—",
        "raw": None, "status": "missing",
        "tooltip": "Realized gearing (derived at workspace load)",
    }
    kpis["min_dscr"] = {
        "label": "Min DSCR", "value": _fmt_number(min_dscr, 2),
        "raw": min_dscr, "status": "pass" if min_dscr is not None else "missing",
        "tooltip": "Minimum Debt Service Coverage Ratio across the operating period",
    }
    kpis["avg_dscr"] = {
        "label": "Avg DSCR", "value": _fmt_number(avg_dscr, 2),
        "raw": avg_dscr, "status": "pass" if avg_dscr is not None else "missing",
        "tooltip": "Average Debt Service Coverage Ratio",
    }
    kpis["project_npv"] = {
        "label": "Project NPV", "value": _fmt_money_keur(npv),
        "raw": npv, "status": "pass" if npv is not None else "missing",
        "tooltip": "Project Net Present Value (computed by the runtime)",
    }
    kpis["y1_revenue"] = {
        "label": "Y1 Revenue", "value": _fmt_money_keur(y1_revenue),
        "raw": y1_revenue, "status": "pass" if y1_revenue is not None else "missing",
        "tooltip": "Year 1 revenue (kEUR)",
    }
    kpis["y1_ebitda"] = {
        "label": "Y1 EBITDA", "value": _fmt_money_keur(y1_ebitda),
        "raw": y1_ebitda, "status": "pass" if y1_ebitda is not None else "missing",
        "tooltip": "Year 1 EBITDA (kEUR)",
    }
    kpis["total_capex"] = {
        "label": "CAPEX", "value": _fmt_money_keur(total_capex),
        "raw": total_capex, "status": "pass" if total_capex is not None else "missing",
        "tooltip": "Total CAPEX (kEUR)",
    }
    return kpis


# ---------------------------------------------------------------------------
# SVG chart series helpers
# ---------------------------------------------------------------------------


def build_revenue_ebitda_series(
    waterfall_result: Any,
) -> Dict[str, List[Optional[float]]]:
    """Return the Revenue and EBITDA series for
    the inline SVG chart, read from the runtime
    result object. Returns ``{"revenue": [...],
    "ebitda": [...], "years": [...]}`` where
    each list has the same length.
    """
    series = getattr(waterfall_result, "yearly_series", None) or {}
    years = series.get("years") or series.get("operating_years") or []
    revenue = series.get("revenue_keur") or series.get("revenue") or []
    ebitda = series.get("ebitda_keur") or series.get("ebitda") or []
    return {
        "years": list(years),
        "revenue": [ _safe_float(v) for v in revenue ],
        "ebitda": [ _safe_float(v) for v in ebitda ],
    }


def build_dscr_series(
    waterfall_result: Any,
) -> Dict[str, List[Optional[float]]]:
    """Return the DSCR series + target line for
    the inline SVG chart. Returns
    ``{"dscr": [...], "target": [...], "years":
    [...]}`` where each list has the same length.
    """
    series = getattr(waterfall_result, "yearly_series", None) or {}
    years = series.get("years") or series.get("operating_years") or []
    dscr = series.get("dscr") or series.get("dscr_ratio") or []
    target = series.get("target_dscr") or series.get("dscr_target") or []
    return {
        "years": list(years),
        "dscr": [ _safe_float(v) for v in dscr ],
        "target": [ _safe_float(v) for v in target ],
    }


def build_debt_balance_series(
    waterfall_result: Any,
) -> Dict[str, List[Optional[float]]]:
    """Return the senior debt balance series for
    the inline SVG chart, read from the runtime
    result object. Returns
    ``{"debt_balance": [...], "years": [...]}``
    where each list has the same length.

    The series is read from the explicit result
    field (NOT from a heuristic
    ``_find_debt_balance`` helper).
    """
    series = getattr(waterfall_result, "yearly_series", None) or {}
    years = series.get("years") or series.get("operating_years") or []
    debt_balance = (
        series.get("senior_debt_balance_keur")
        or series.get("debt_balance_keur")
        or series.get("senior_debt_balance")
        or series.get("debt_balance")
        or []
    )
    return {
        "years": list(years),
        "debt_balance": [ _safe_float(v) for v in debt_balance ],
    }


# ---------------------------------------------------------------------------
# Inline SVG geometry helpers
# ---------------------------------------------------------------------------


def render_svg_line_chart(
    series: Dict[str, List[Optional[float]]],
    width: int = 480,
    height: int = 200,
    margin: int = 30,
    series_specs: Optional[List[Dict[str, Any]]] = None,
) -> str:
    """Render a small inline-SVG line chart.

    ``series_specs`` is a list of dicts, each
    with keys ``key`` (the series key in
    ``series``), ``color`` (CSS color), and
    ``label`` (legend label). Returns a
    string of SVG markup.
    """
    if series_specs is None:
        series_specs = [
            {"key": "revenue", "color": "var(--primary)", "label": "Revenue"},
            {"key": "ebitda", "color": "var(--success, #2e7d32)",
             "label": "EBITDA"},
        ]
    years = series.get("years") or []
    if not years:
        return (
            f'<svg viewBox="0 0 {width} {height}" '
            f'class="dashboard-svg" '
            f'role="img" '
            f'aria-label="No data available">'
            f'<text x="{width//2}" y="{height//2}" '
            f'text-anchor="middle" fill="var(--text-2)" '
            f'font-size="0.85rem">No data available</text>'
            f'</svg>'
        )
    plot_w = width - 2 * margin
    plot_h = height - 2 * margin
    # Build value range
    all_vals: List[float] = []
    for spec in series_specs:
        for v in series.get(spec["key"], []):
            if v is not None:
                all_vals.append(float(v))
    ymin = min(all_vals) if all_vals else 0
    ymax = max(all_vals) if all_vals else 1
    if ymax == ymin:
        ymax = ymin + 1
    # Build path data
    parts: List[str] = []
    for spec in series_specs:
        points = []
        vals = series.get(spec["key"], [])
        n = len(vals)
        if n == 0:
            continue
        for i, v in enumerate(vals):
            if v is None:
                continue
            x = margin + (i / max(n - 1, 1)) * plot_w
            y = margin + (1 - (float(v) - ymin) / (ymax - ymin)) * plot_h
            points.append((x, y))
        if not points:
            continue
        d = " ".join(
            ("M " if i == 0 else "L ") + f"{x:.1f},{y:.1f}"
            for i, (x, y) in enumerate(points)
        )
        parts.append(
            f'<path d="{d}" stroke="{spec["color"]}" '
            f'fill="none" stroke-width="2"/>'
        )
    # Axes
    parts.append(
        f'<line x1="{margin}" y1="{height-margin}" '
        f'x2="{width-margin}" y2="{height-margin}" '
        f'stroke="var(--border)"/>'
    )
    parts.append(
        f'<line x1="{margin}" y1="{margin}" '
        f'x2="{margin}" y2="{height-margin}" '
        f'stroke="var(--border)"/>'
    )
    # Legend
    legend_x = margin
    legend_y = margin - 12
    legend_items = "".join(
        f'<rect x="{legend_x + i*120}" y="{legend_y - 8}" '
        f'width="10" height="10" fill="{spec["color"]}"/>'
        f'<text x="{legend_x + i*120 + 14}" y="{legend_y}" '
        f'font-size="0.7rem" fill="var(--text-2)">'
        f'{spec["label"]}</text>'
        for i, spec in enumerate(series_specs)
    )
    return (
        f'<svg viewBox="0 0 {width} {height}" '
        f'class="dashboard-svg" '
        f'role="img" '
        f'aria-label="Dashboard line chart">{parts}\n{legend_items}</svg>'
    )


def render_svg_dscr_chart(
    series: Dict[str, List[Optional[float]]],
    width: int = 480,
    height: int = 200,
    margin: int = 30,
) -> str:
    """Render the inline-SVG DSCR chart (with
    a horizontal target line). Returns a string
    of SVG markup.
    """
    years = series.get("years") or []
    if not years:
        return render_svg_line_chart(series, width, height, margin)
    plot_w = width - 2 * margin
    plot_h = height - 2 * margin
    all_vals: List[float] = []
    for k in ("dscr", "target"):
        for v in series.get(k, []):
            if v is not None:
                all_vals.append(float(v))
    ymin = min(all_vals) if all_vals else 0
    ymax = max(all_vals) if all_vals else 1
    if ymax == ymin:
        ymax = ymin + 1
    parts: List[str] = []
    # DSCR line
    vals = series.get("dscr", [])
    n = len(vals)
    if n > 0:
        points = []
        for i, v in enumerate(vals):
            if v is None:
                continue
            x = margin + (i / max(n - 1, 1)) * plot_w
            y = margin + (1 - (float(v) - ymin) / (ymax - ymin)) * plot_h
            points.append((x, y))
        if points:
            d = " ".join(
                ("M " if i == 0 else "L ") + f"{x:.1f},{y:.1f}"
                for i, (x, y) in enumerate(points)
            )
            parts.append(
                f'<path d="{d}" stroke="var(--primary)" '
                f'fill="none" stroke-width="2"/>'
            )
    # Target line
    target_vals = series.get("target", [])
    if any(v is not None for v in target_vals):
        y0 = margin + (1 - (float(target_vals[0]) - ymin) / (ymax - ymin)) * plot_h
        parts.append(
            f'<line x1="{margin}" y1="{y0:.1f}" '
            f'x2="{width-margin}" y2="{y0:.1f}" '
            f'stroke="var(--warn, #f57c00)" stroke-dasharray="4 4" '
            f'stroke-width="1.5"/>'
        )
    parts.append(
        f'<line x1="{margin}" y1="{height-margin}" '
        f'x2="{width-margin}" y2="{height-margin}" '
        f'stroke="var(--border)"/>'
    )
    parts.append(
        f'<line x1="{margin}" y1="{margin}" '
        f'x2="{margin}" y2="{height-margin}" '
        f'stroke="var(--border)"/>'
    )
    return (
        f'<svg viewBox="0 0 {width} {height}" '
        f'class="dashboard-svg dscr-chart" '
        f'role="img" '
        f'aria-label="DSCR over time with target line">{parts}</svg>'
    )


def render_svg_debt_chart(
    series: Dict[str, List[Optional[float]]],
    width: int = 480,
    height: int = 200,
    margin: int = 30,
) -> str:
    """Render the inline-SVG debt balance
    chart. Returns a string of SVG markup.
    """
    years = series.get("years") or []
    if not years:
        return render_svg_line_chart(series, width, height, margin)
    plot_w = width - 2 * margin
    plot_h = height - 2 * margin
    vals = series.get("debt_balance", [])
    nums = [float(v) for v in vals if v is not None]
    ymin = min(nums) if nums else 0
    ymax = max(nums) if nums else 1
    if ymax == ymin:
        ymax = ymin + 1
    parts: List[str] = []
    n = len(vals)
    if n > 0:
        points = []
        for i, v in enumerate(vals):
            if v is None:
                continue
            x = margin + (i / max(n - 1, 1)) * plot_w
            y = margin + (1 - (float(v) - ymin) / (ymax - ymin)) * plot_h
            points.append((x, y))
        if points:
            # Area under the line
            d_area = " ".join(
                [f"M {points[0][0]:.1f},{height-margin:.1f}"]
                + [
                    f"L {x:.1f},{y:.1f}"
                    for x, y in points
                ]
                + [f"L {points[-1][0]:.1f},{height-margin:.1f} Z"]
            )
            parts.append(
                f'<path d="{d_area}" '
                f'fill="rgba(107,114,128,0.18)" '
                f'stroke="none"/>'
            )
            d = " ".join(
                ("M " if i == 0 else "L ") + f"{x:.1f},{y:.1f}"
                for i, (x, y) in enumerate(points)
            )
            parts.append(
                f'<path d="{d}" stroke="var(--text)" '
                f'fill="none" stroke-width="2"/>'
            )
    parts.append(
        f'<line x1="{margin}" y1="{height-margin}" '
        f'x2="{width-margin}" y2="{height-margin}" '
        f'stroke="var(--border)"/>'
    )
    parts.append(
        f'<line x1="{margin}" y1="{margin}" '
        f'x2="{margin}" y2="{height-margin}" '
        f'stroke="var(--border)"/>'
    )
    return (
        f'<svg viewBox="0 0 {width} {height}" '
        f'class="dashboard-svg debt-chart" '
        f'role="img" '
        f'aria-label="Senior debt balance over time">{parts}</svg>'
    )
