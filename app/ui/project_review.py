"""Phase 25B-6 — Generic project review pack helpers (pure functions).

Goal: a third-party reviewer can understand a generic project from a
single review card. The data is already in the project context and
runtime summary; this module is a *shape* helper that arranges the
fields into four clearly grouped review sections:

  - Assumptions summary  (key inputs, formatted)
  - KPIs summary         (from last run)
  - Scenario summary     (count, names, kinds)
  - Exploratory / known exclusions  (text notices)

All helpers are **pure**:
- No DB, no I/O, no time, no random, no side-effects.
- No formula changes (no NPV/IRR/DSCR computations here).
- No schema changes.
"""
from __future__ import annotations

from typing import Any, Optional

# ── Constants ─────────────────────────────────────────────────────────────

# Known exclusions: text-only. No computations.
KNOWN_EXCLUSIONS = [
    "Construction schedule engine (use_construction_schedule_engine=False) — not promoted.",
    "Senior IDC (Interest During Construction) is not promoted to the senior debt schedule.",
    "Debt sculpting coverage depends on the selected financing configuration.",
    "Pari-passu reserves / construction reserves engine — not active in the runtime.",
    "Tax coverage depends on the selected typed tax policy.",
    "Depreciation follows the selected typed depreciation policy.",
    "Multi-user / multi-tenant — single-user internal pilot mode only.",
    "Lender / bank approval — this app does not provide credit analysis.",
    "External audit / certification — the Audit tab is internal review tooling.",
    "Enterprise SaaS / RBAC — no production deployment; not certified.",
]

EXPLORATORY_LIMITATIONS = [
    (
        "Generic Solar / Generic Wind projects are internal-use model only. "
        "They are synthetic working models and should be reviewed within their stated validation scope."
    ),
    (
        "The 'What changed since previous run?' delta panel compares the "
        "current run to the previous one for the same scenario, but the "
        "absolute values are not externally validated."
    ),
    (
        "Saved scenarios preserve a snapshot of the input form, not the "
        "full calculation state. To recover exact numbers, re-run the "
        "scenario after Save."
    ),
]


# ── Assumptions summary ───────────────────────────────────────────────────

def _fmt_mw(v: Optional[float]) -> str:
    if v is None:
        return "—"
    try:
        return f"{float(v):.2f} MW"
    except (TypeError, ValueError):
        return "—"

def _fmt_eur_mwh(v: Optional[float]) -> str:
    if v is None:
        return "—"
    try:
        return f"{float(v):.2f} EUR/MWh"
    except (TypeError, ValueError):
        return "—"

def _fmt_hours(v: Optional[float]) -> str:
    if v is None:
        return "—"
    try:
        return f"{float(v):,.0f} h/yr"
    except (TypeError, ValueError):
        return "—"

def _fmt_keur(v: Optional[float]) -> str:
    if v is None:
        return "—"
    try:
        return f"{float(v):,.0f} kEUR"
    except (TypeError, ValueError):
        return "—"

def _fmt_pct(v: Optional[float]) -> str:
    """Format a decimal (e.g. ``0.97``) as a percent string.

    Input is interpreted as a 0-1 fraction. Output is a percent
    string (e.g. ``"97.0 %"``). ``None`` and non-numeric values
    return ``"—"``.

    Python's ``f"{0.97:.1f}"`` returns ``"1.0"`` (banker's rounding
    combined with the implicit ×100 in the formatter). We work
    around that by scaling manually with ``round(..., 1)`` so that
    ``0.97`` displays as ``"97.0 %"``.
    """
    if v is None:
        return "—"
    try:
        scaled_pct = round(float(v) * 100, 1)
        return f"{scaled_pct:.1f} %"
    except (TypeError, ValueError):
        return "—"

def _fmt_x(v: Optional[float]) -> str:
    if v is None:
        return "—"
    try:
        return f"{float(v):.2f} x"
    except (TypeError, ValueError):
        return "—"

def _fmt_years(v: Optional[int]) -> str:
    if v is None:
        return "—"
    try:
        return f"{int(v)} years"
    except (TypeError, ValueError):
        return "—"

def _fmt_bool(v: Optional[bool]) -> str:
    if v is None:
        return "—"
    return "Enabled" if bool(v) else "Disabled"

def _fmt_date(v: Optional[str]) -> str:
    if not v:
        return "—"
    return str(v)


def build_assumptions_summary(project_ctx: Any) -> list[dict[str, Any]]:
    """Build a list of key assumption rows for the review card.

    Each row is a dict with ``label`` and ``value`` keys, ready for
    the template to render as a 2-column key-value table.

    Only fields that the user can change via the input form are
    included — the review card is about the project as-set-up, not
    about the runtime details.
    """
    rows: list[dict[str, Any]] = []
    if project_ctx is None:
        return rows

    # Project identity
    rows.append({"label": "Project name", "value": getattr(project_ctx, "name", "—") or "—"})
    rows.append({"label": "Project code", "value": getattr(project_ctx, "code", "—") or "—"})
    rows.append({"label": "Country", "value": getattr(project_ctx, "country_iso", "—") or "—"})
    rows.append({"label": "Technology", "value": getattr(project_ctx, "technology", "—") or "—"})

    # Capacity / yield
    rows.append({"label": "Capacity", "value": _fmt_mw(getattr(project_ctx, "capacity_mw", None))})
    rows.append({"label": "P50 operating hours", "value": _fmt_hours(getattr(project_ctx, "operating_hours_p50", None))})
    rows.append({"label": "Plant availability", "value": _fmt_pct(getattr(project_ctx, "plant_availability", None))})
    rows.append({"label": "Grid availability", "value": _fmt_pct(getattr(project_ctx, "grid_availability", None))})

    # Revenue
    rows.append({"label": "PPA tariff", "value": _fmt_eur_mwh(getattr(project_ctx, "ppa_tariff_eur_mwh", None))})
    rows.append({"label": "PPA term", "value": _fmt_years(getattr(project_ctx, "ppa_term_years", None))})
    rows.append({"label": "PPA indexation", "value": _fmt_pct(getattr(project_ctx, "ppa_index_pct", None))})
    rows.append({"label": "CO2 revenue", "value": _fmt_bool(getattr(project_ctx, "co2_enabled", None))})

    # Schedule
    rows.append({"label": "Financial close", "value": _fmt_date(getattr(project_ctx, "financial_close", None))})
    rows.append({"label": "Commercial operation date", "value": _fmt_date(getattr(project_ctx, "cod_date", None))})
    rows.append({"label": "Horizon", "value": _fmt_years(getattr(project_ctx, "horizon_years", None))})

    # CAPEX / financing
    rows.append({"label": "Total CAPEX", "value": _fmt_keur(getattr(project_ctx, "total_capex_keur", None))})
    rows.append({"label": "Senior debt", "value": _fmt_keur(getattr(project_ctx, "senior_debt_keur", None))})
    rows.append({"label": "SHL amount", "value": _fmt_keur(getattr(project_ctx, "shl_amount_keur", None))})
    rows.append({"label": "Interest rate", "value": _fmt_pct(getattr(project_ctx, "interest_rate_pct", None))})
    rows.append({"label": "Senior tenor", "value": _fmt_years(getattr(project_ctx, "senior_tenor_years", None))})
    rows.append({"label": "Target DSCR", "value": _fmt_x(getattr(project_ctx, "target_dscr", None))})
    rows.append({"label": "Indicative gearing (input)", "value": _fmt_pct(getattr(project_ctx, "gearing_pct", None))})

    return rows


# ── KPIs summary ──────────────────────────────────────────────────────────

def build_kpis_summary(
    last_run_summary: Optional[dict[str, Any]],
    project_ctx: Any = None,
) -> list[dict[str, Any]]:
    """Build a list of key KPI rows for the review card.

    The values come from the last run summary (already produced by
    the backend). When the project has not been run yet, every value
    is "—".
    """
    summary = last_run_summary or {}
    rows: list[dict[str, Any]] = []

    def _from_summary(key: str, fmt) -> str:
        v = summary.get(key)
        if v is None:
            return "—"
        return fmt(v)

    rows.append({"label": "Project IRR", "value": _from_summary("project_irr", _fmt_pct)})
    rows.append({"label": "Equity IRR", "value": _from_summary("equity_irr", _fmt_pct)})
    rows.append({"label": "Average DSCR", "value": _from_summary("avg_dscr", _fmt_x)})
    rows.append({"label": "Minimum DSCR", "value": _from_summary("min_dscr", _fmt_x)})
    rows.append({"label": "Total revenue (Y1)", "value": _from_summary("total_revenue_keur", _fmt_keur)})
    rows.append({"label": "Total OPEX (Y1)", "value": _from_summary("total_opex_keur", _fmt_keur)})
    rows.append({"label": "EBITDA (Y1)", "value": _from_summary("ebitda_keur", _fmt_keur)})
    rows.append({"label": "Total distributions", "value": _from_summary("total_distributions_keur", _fmt_keur)})
    rows.append({"label": "Senior debt (end)", "value": _from_summary("senior_debt_end_keur", _fmt_keur)})
    return rows


# ── Scenario summary ──────────────────────────────────────────────────────

def build_scenario_summary(
    cards: list[dict[str, Any]],
    workflow_ui: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Build a scenario-list summary for the review card.

    Returns
    -------
    dict with fields:
      - ``count``: int
      - ``names``: list[str]
      - ``kinds``: list[str] (one of base / downside / upside / custom)
      - ``active_name``: str or ""
      - ``by_kind``: dict[kind, count]
    """
    cards = cards or []
    by_kind: dict[str, int] = {"base": 0, "downside": 0, "upside": 0, "custom": 0}
    names: list[str] = []
    active_name = ""
    workflow_by_scenario = (workflow_ui or {}).get("by_scenario", {})
    for c in cards:
        sid = c.get("scenario_id", "")
        name = c.get("scenario_name", "") or ""
        if name:
            names.append(name)
        if sid and sid in workflow_by_scenario:
            kind = workflow_by_scenario[sid]["label"]["kind"]
        else:
            kind = "custom"
        by_kind[kind] = by_kind.get(kind, 0) + 1
        if c.get("is_active") and not active_name:
            active_name = name
    return {
        "count": len(cards),
        "names": names,
        "kinds": [k for k, v in by_kind.items() if v > 0],
        "active_name": active_name,
        "by_kind": by_kind,
    }


# ── Composer ──────────────────────────────────────────────────────────────

def build_project_review_ui(
    *,
    project_ctx: Any = None,
    last_run_summary: Optional[dict[str, Any]] = None,
    scenario_cards: Optional[list[dict[str, Any]]] = None,
    scenario_workflow_ui: Optional[dict[str, Any]] = None,
    project_origin: str = "",
    template_source: str = "",
    is_user_project: bool = True,
) -> dict[str, Any]:
    """Build the full ``project_review_ui`` payload for the template.

    Combines the four review sections (assumptions, KPIs, scenario
    summary, exploratory / known exclusions) plus a top-level
    classification (exploratory / reference-validated / factory).

    Returns
    -------
    dict with fields:
      - ``classification``: "exploratory" | "parity_validated" | "factory_template"
      - ``is_user_project``: bool
      - ``template_source``: str
      - ``assumptions``: list[{label, value}]
      - ``kpis``: list[{label, value}]
      - ``scenarios``: dict (output of build_scenario_summary)
      - ``exploratory_limitations``: list[str]
      - ``known_exclusions``: list[str]
      - ``has_run``: bool (True when last_run_summary has at least one
        non-None value)
    """
    classification = "factory_template"
    if is_user_project and template_source in ("generic_solar", "generic_wind"):
        classification = "exploratory"
    elif is_user_project:
        classification = "user_created"  # custom user project
    # else: factory_template (Generic Wind Reference / Generic Solar Reference)

    has_run = bool(last_run_summary) and any(
        v is not None for v in (last_run_summary or {}).values()
    )

    return {
        "classification": classification,
        "is_user_project": is_user_project,
        "template_source": template_source or "",
        "assumptions": build_assumptions_summary(project_ctx),
        "kpis": build_kpis_summary(last_run_summary, project_ctx=project_ctx),
        "scenarios": build_scenario_summary(
            list(scenario_cards or []), workflow_ui=scenario_workflow_ui,
        ),
        "exploratory_limitations": list(EXPLORATORY_LIMITATIONS),
        "known_exclusions": list(KNOWN_EXCLUSIONS),
        "has_run": has_run,
    }
