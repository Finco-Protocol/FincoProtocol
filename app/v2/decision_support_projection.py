"""app.v2.decision_support_projection — Decision Support V1 projections.

Read-only analytical projections over PERSISTED canonical successful Run
data (the append-only run-history authority and the workspace Last Run
record).  No engine execution, no recomputation of financial results, no
model mutation — every displayed value is either identity metadata or a
persisted number, formatted through the canonical OutputMetricProjection
catalog.  The only arithmetic is the variance arithmetic defined here.

Sections (§4): Returns / Project Economics / Debt / Sponsor / Tax /
Reserves-Cash.  Percentage variance is computed ONLY where the metric is a
ratio against a non-zero base; rate metrics (IRR) present absolute
percentage-point deltas (§5).  Assumption differences come from the
persisted run-bound input identity (§6); the Drivers-of-Change block is a
deterministic factual summary — never a causal attribution (§7).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from app.v2.output_metric_projection import build_output_metric_projection

# ---------------------------------------------------------------------------
# Metric catalog: (key, label, section, kind)
# kind drives variance presentation:
#   "pct"   → stored as a fraction; delta shown in percentage points (pp)
#   "x"     → ratio; absolute delta shown with x
#   "keur"  → kEUR amounts; absolute + % variance (safe denominator)
# Values are sourced from the persisted runtime KPI dict (pass-through).
# ---------------------------------------------------------------------------

VARIANCE_SECTIONS: tuple[tuple[str, str], ...] = (
    ("returns", "Returns"),
    ("economics", "Project Economics"),
    ("debt", "Debt"),
    ("sponsor", "Sponsor"),
    ("tax", "Tax"),
    ("reserves", "Reserves / Cash"),
)

_METRICS: tuple[tuple[str, str, str, str], ...] = (
    # ── Returns ──
    ("project_irr", "Project IRR", "returns", "pct"),
    ("equity_irr", "Pure Equity IRR", "returns", "pct"),
    ("total_sponsor_xirr", "Total Sponsor IRR", "returns", "pct"),
    ("project_npv_keur", "Project NPV", "returns", "keur"),
    ("pure_equity_moic", "Pure Equity MOIC", "returns", "x"),
    ("sponsor_moic", "Total Sponsor MOIC", "returns", "x"),
    # ── Project Economics ──
    ("total_capex_keur", "Total CAPEX", "economics", "keur"),
    ("total_project_uses_keur", "Total Project Uses", "economics", "keur"),
    ("total_revenue_keur", "Operating Revenue", "economics", "keur"),
    ("total_ebitda_keur", "EBITDA", "economics", "keur"),
    ("total_opex_keur", "Total OPEX", "economics", "keur"),
    ("total_distributions_keur", "Distributions", "economics", "keur"),
    # ── Debt ──
    ("senior_debt_keur", "Senior Debt", "debt", "keur"),
    ("gearing_cap_pct", "Gearing", "debt", "pct"),
    ("min_dscr", "Minimum DSCR", "debt", "x"),
    ("avg_dscr", "Average DSCR", "debt", "x"),
    ("min_llcr", "Min LLCR", "debt", "x"),
    ("total_senior_ds_keur", "Senior Debt Service", "debt", "keur"),
    # ── Sponsor ──
    ("total_legal_equity_contributed_keur", "Equity Contributed",
     "sponsor", "keur"),
    ("total_shl_cash_contributed_keur", "SHL Contributed", "sponsor", "keur"),
    ("total_legal_equity_distributions_keur", "Dividends", "sponsor", "keur"),
    ("total_shl_principal_received_keur", "SHL Principal Received",
     "sponsor", "keur"),
    ("total_sponsor_receipts_keur", "Total Sponsor Receipts",
     "sponsor", "keur"),
    # ── Tax ──
    ("total_tax_keur", "Total Cash Tax", "tax", "keur"),
)

# Metrics stored on the sponsor/debt schedule summaries rather than kpis.
_SUMMARY_SOURCED: dict[str, tuple[str, str]] = {
    "total_legal_equity_contributed_keur":
        ("sponsor", "total_legal_equity_contributed_keur"),
    "total_shl_cash_contributed_keur":
        ("sponsor", "total_shl_cash_contributed_keur"),
    "total_legal_equity_distributions_keur":
        ("sponsor", "total_legal_equity_distributions_keur"),
    "total_sponsor_receipts_keur":
        ("sponsor", "total_sponsor_receipts_keur"),
    "total_shl_principal_received_keur":
        ("sponsor", "total_shl_principal_received_keur"),
    "min_llcr": ("debt", "min_llcr"),
}

_NA = "—"


def _fmt(kind: str, value: Optional[float]) -> str:
    if value is None:
        return _NA
    if kind == "pct":
        return f"{value * 100:.2f}%"
    if kind == "x":
        return f"{value:.2f}x"
    return f"{value:,.0f}"


def _fetch(raw: dict, key: str) -> Optional[float]:
    v = raw.get(key)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    f = float(v)
    return None if f != f or f in (float("inf"), float("-inf")) else f


def run_metric_view(runtime_summary: dict,
                    sponsor_summary: dict,
                    debt_summary: dict) -> dict[str, Optional[float]]:
    """Persisted raw values for every catalog metric (pass-through only).

    Sponsor/debt-summary-sourced metrics are read from their persisted
    schedule summaries (the same authority the Returns sheet uses); missing
    values stay None — unavailable is never zero.
    """
    view: dict[str, Optional[float]] = {}
    for key, _label, _section, _kind in _METRICS:
        if key in _SUMMARY_SOURCED:
            where, field = _SUMMARY_SOURCED[key]
            raw = sponsor_summary if where == "sponsor" else debt_summary
            view[key] = _fetch(raw or {}, field)
        else:
            view[key] = _fetch(runtime_summary or {}, key)
    return view


@dataclass(frozen=True)
class VarianceRow:
    label: str
    kind: str
    value_a: str
    value_b: str
    abs_delta: str
    pp_delta: str       # percentage-point delta for "pct" metrics only
    pct_delta: str      # safe % variance for keur metrics (None → "—")
    direction: str      # "up" | "down" | "flat" | "" (direction, NOT judgment)


@dataclass(frozen=True)
class VarianceSection:
    key: str
    title: str
    rows: tuple[VarianceRow, ...]


def _variance_fields(kind: str, a: Optional[float], b: Optional[float]):
    abs_delta = pp_delta = pct_delta = _NA
    direction = ""
    if a is None or b is None:
        return abs_delta, pp_delta, pct_delta, direction
    d = b - a
    abs_delta = _fmt(kind, abs(d)) if kind != "pct" else f"{d * 100:+.2f} pp"
    if kind == "pct":
        pp_delta = f"{d * 100:+.2f} pp"
        pct_delta = _NA          # never present an IRR delta as % growth (§5)
    elif d != 0 and a != 0:
        pct_delta = f"{d / abs(a) * 100:+.1f}%"
    direction = "flat" if d == 0 else ("up" if d > 0 else "down")
    return abs_delta, pp_delta, pct_delta, direction


def build_run_variance(view_a: dict[str, Optional[float]],
                       view_b: dict[str, Optional[float]]) -> list[VarianceSection]:
    """Variance sections between two persisted metric views (A → B)."""
    sections: list[VarianceSection] = []
    for sec_key, sec_title in VARIANCE_SECTIONS:
        rows: list[VarianceRow] = []
        for key, label, section, kind in _METRICS:
            if section != sec_key:
                continue
            a, b = view_a.get(key), view_b.get(key)
            abs_d, pp_d, pct_d, direction = _variance_fields(kind, a, b)
            rows.append(VarianceRow(
                label=label, kind=kind,
                value_a=_fmt(kind, a), value_b=_fmt(kind, b),
                abs_delta=abs_d, pp_delta=pp_d, pct_delta=pct_d,
                direction=direction,
            ))
        sections.append(VarianceSection(key=sec_key, title=sec_title,
                                        rows=tuple(rows)))
    return sections


# ---------------------------------------------------------------------------
# §6 — assumption / driver differences from the persisted run-bound identity
# ---------------------------------------------------------------------------

_ASSUMPTION_CATEGORY = (
    ("revenue", "Revenue"), ("capex", "CAPEX"), ("opex", "OPEX"),
    ("financing", "Financing"), ("tax", "Tax"),
    ("development", "Development Economics"), ("scenario", "Scenario"),
    ("other", "Other"),
)


@dataclass(frozen=True)
class AssumptionDiffRow:
    category: str
    name: str
    value_a: str
    value_b: str


def build_assumption_diff(identity_a: Optional[dict],
                          identity_b: Optional[dict]) -> list[AssumptionDiffRow]:
    """Changed assumptions between two persisted run-bound input identities.

    Compares the canonical persisted binding payloads: CAPEX/OPEX rows by
    their sub-line identity and scenario overrides by key.  Rows identical
    in both runs are omitted (changed-only view, §6).  Presentation-only
    state is never consulted.
    """
    a = identity_a or {}
    b = identity_b or {}
    rows: list[AssumptionDiffRow] = []

    def _rows(side, key):
        payload = side.get(key) or ()
        return {str(item.get("sub_line_id", item.get("name", i))): item
                for i, item in enumerate(payload)
                if isinstance(item, dict)}

    a_capex, b_capex = _rows(a, "capex_rows"), _rows(b, "capex_rows")
    for idx in sorted(set(a_capex) | set(b_capex)):
        ca, cb = a_capex.get(idx), b_capex.get(idx)
        if (ca or {}).get("amount_keur") != (cb or {}).get("amount_keur"):
            rows.append(AssumptionDiffRow(
                category="capex",
                name=(ca or cb).get("name") or idx,
                value_a=_fmt("keur", _fetch(ca or {}, "amount_keur")),
                value_b=_fmt("keur", _fetch(cb or {}, "amount_keur")),
            ))
    a_opex, b_opex = _rows(a, "opex_rows"), _rows(b, "opex_rows")
    for idx in sorted(set(a_opex) | set(b_opex)):
        oa, ob = a_opex.get(idx), b_opex.get(idx)
        if (oa or {}).get("amount_keur") != (ob or {}).get("amount_keur"):
            rows.append(AssumptionDiffRow(
                category="opex",
                name=(oa or ob).get("name") or idx,
                value_a=_fmt("keur", _fetch(oa or {}, "amount_keur")),
                value_b=_fmt("keur", _fetch(ob or {}, "amount_keur")),
            ))
    a_ov, b_ov = a.get("scenario_overrides") or {}, b.get("scenario_overrides") or {}
    for key in sorted(set(a_ov) | set(b_ov)):
        if a_ov.get(key) != b_ov.get(key):
            rows.append(AssumptionDiffRow(
                category="scenario", name=str(key),
                value_a=_NA if a_ov.get(key) is None else str(a_ov[key]),
                value_b=_NA if b_ov.get(key) is None else str(b_ov[key]),
            ))
    return rows


def build_drivers_of_change(assumptions: list[AssumptionDiffRow],
                            sections: list[VarianceSection],
                            changed_output_limit: int = 6) -> dict:
    """Deterministic factual summary (§7): changed assumptions + moved
    outputs.  NOT attribution mathematics — no causal percentages, no
    generated explanations."""
    changed_names = [a.name for a in assumptions]
    moved = []
    for section in sections:
        for row in section.rows:
            if row.direction and row.direction != "flat":
                moved.append((row.label,
                              row.pp_delta if row.pp_delta != _NA
                              else (row.pct_delta if row.pct_delta != _NA
                                    else row.abs_delta)))
    return {
        "changed_assumptions": changed_names,
        "no_assumption_changes": not changed_names,
        "moved_outputs": tuple(moved[:changed_output_limit]),
        "more_outputs": max(0, len(moved) - changed_output_limit),
    }


# ---------------------------------------------------------------------------
# §8-§11 — cross-project comparison rows
# ---------------------------------------------------------------------------

_CROSS_METRICS: tuple[tuple[str, str, str], ...] = (
    ("total_capex_keur", "Total CAPEX (kEUR)", "keur"),
    ("total_revenue_keur", "Revenue (kEUR)", "keur"),
    ("total_ebitda_keur", "EBITDA (kEUR)", "keur"),
    ("project_irr", "Project IRR", "pct"),
    ("equity_irr", "Pure Equity IRR", "pct"),
    ("total_sponsor_xirr", "Total Sponsor IRR", "pct"),
    ("pure_equity_moic", "Pure Equity MOIC", "x"),
    ("sponsor_moic", "Total Sponsor MOIC", "x"),
    ("senior_debt_keur", "Senior Debt (kEUR)", "keur"),
    ("gearing_cap_pct", "Gearing", "pct"),
    ("min_dscr", "Minimum DSCR", "x"),
    ("min_llcr", "Min LLCR", "x"),
    ("total_tax_keur", "Total Cash Tax (kEUR)", "keur"),
)

CROSS_PROJECT_MAX = 5


@dataclass(frozen=True)
class CrossProjectRow:
    """One project column's canonical Last Run snapshot."""

    project_code: str
    project_name: str
    technology: str
    country: str
    capacity_display: str
    runnable: bool
    ran_at_display: str
    metrics: dict[str, str]          # key → display (AVAILABLE only)
    ebitda_margin: str               # derived ratio label (presentation only)


def build_cross_project_rows(
    projects: list[dict],
) -> list[CrossProjectRow]:
    """Build cross-project comparison rows from PRE-ASSEMBLED per-project
    payloads (the route resolves metadata + the latest successful canonical
    run per project — bounded to CROSS_PROJECT_MAX).

    ``projects`` items carry: project_code/name/technology/country,
    capacity_mw, runnable flag, ran_at and the persisted runtime summary +
    sponsor/debt schedule summaries.  A project without a successful
    canonical Run is listed as unavailable — never calculated.
    """
    rows: list[CrossProjectRow] = []
    for p in projects[:CROSS_PROJECT_MAX]:
        metrics: dict[str, str] = {}
        margin = _NA
        if p.get("runnable"):
            view = run_metric_view(p.get("runtime_summary") or {},
                                   p.get("sponsor_summary") or {},
                                   p.get("debt_summary") or {})
            for key, _label, kind in _CROSS_METRICS:
                metrics[key] = _fmt(kind, view.get(key))
            capex, ebitda, revenue = (view.get("total_capex_keur"),
                                      view.get("total_ebitda_keur"),
                                      view.get("total_revenue_keur"))
            if capex and ebitda and revenue:
                # EBITDA margin on revenue — presentation ratio of persisted values
                margin = f"{(ebitda / revenue) * 100:.1f}%"
            cap_mw = p.get("capacity_mw")
            if capex and isinstance(cap_mw, (int, float)) and cap_mw > 0:
                metrics["capex_per_mw"] = f"{capex / float(cap_mw):,.0f}"
        rows.append(CrossProjectRow(
            project_code=p.get("project_code", ""),
            project_name=p.get("project_name", ""),
            technology=p.get("technology", "") or "—",
            country=p.get("country", "") or "—",
            capacity_display=p.get("capacity_display", "") or "—",
            runnable=bool(p.get("runnable")),
            ran_at_display=p.get("ran_at_display", "") or _NA,
            metrics=metrics,
            ebitda_margin=margin,
        ))
    return rows


__all__ = [
    "CROSS_PROJECT_MAX",
    "AssumptionDiffRow",
    "CrossProjectRow",
    "VarianceRow",
    "VarianceSection",
    "build_assumption_diff",
    "build_cross_project_rows",
    "build_drivers_of_change",
    "build_run_variance",
    "run_metric_view",
]
