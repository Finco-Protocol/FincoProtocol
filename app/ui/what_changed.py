"""Phase 25B-3 — "What changed since previous run?" delta helper.

Pure read-only helper. Computes a list of metric deltas between the
current run summary and a previously persisted run summary. No DB
access, no I/O, no side effects.

Hard contract:
- Function takes two dicts (previous, current) and returns a list of
  metric dicts ready for Jinja2 rendering.
- Tolerates None / missing / wrong-type values by returning
  ``{"state": "n_a"}`` for that metric.
- The list of supported metrics is fixed and ordered for stable
  display.
- No financial formulas are introduced — the helper only subtracts
  two values and divides by a divisor (for percentage delta) with
  zero/None guards.
"""
from __future__ import annotations

from typing import Any, Optional

# Metrics displayed in the What Changed panel.
# Each entry: (key_in_summary, display_label, format)
#   format = "pct"   → rendered as percent (multiplied by 100 in display)
#   format = "keur"  → rendered as k-EUR (no scaling needed)
#   format = "x"     → rendered as ratio (no scaling)
#   format = "raw"   → rendered with 4 decimal places
WHAT_CHANGED_METRICS: list[tuple[str, str, str]] = [
    ("project_irr", "Project IRR", "pct"),
    ("equity_irr", "Equity IRR", "pct"),
    ("avg_dscr", "Avg DSCR", "x"),
    ("min_dscr", "Min DSCR", "x"),
    ("total_revenue_keur", "Revenue", "keur"),
    ("total_opex_keur", "OPEX", "keur"),
    ("total_ebitda_keur", "EBITDA", "keur"),
    ("total_capex_keur", "CAPEX", "keur"),
    ("total_distributions_keur", "Distributions", "keur"),
    ("senior_debt_keur", "Senior Debt", "keur"),
]


def _coerce_float(v: Any) -> Optional[float]:
    """Best-effort conversion to float. Returns None on failure or None."""
    if v is None:
        return None
    if isinstance(v, bool):
        return None  # bool is not a numeric metric
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        s = v.strip().rstrip("%").rstrip("x")
        if not s or s in ("—", "-", "n/a", "N/A", "NOT_AVAILABLE"):
            return None
        try:
            return float(s)
        except ValueError:
            return None
    return None


def _format_value(v: float, fmt: str) -> str:
    if fmt == "pct":
        return f"{v * 100:.2f}%"
    if fmt == "keur":
        # k-EUR (already in kEUR) — use thousands separator
        if v >= 0:
            return f"{v:,.0f} kEUR"
        return f"-{abs(v):,.0f} kEUR"
    if fmt == "x":
        return f"{v:.2f}x"
    return f"{v:.4f}"


def _format_delta(d: float, fmt: str) -> str:
    if fmt == "pct":
        # IRRs come in as decimals (0.085), so delta is in absolute percent points
        return f"{d * 100:+.2f} pp"
    if fmt == "keur":
        if d >= 0:
            return f"+{d:,.0f} kEUR"
        return f"{d:,.0f} kEUR"
    if fmt == "x":
        return f"{d:+.2f}x"
    return f"{d:+.4f}"


def _percent_delta(d: float, prev: float, fmt: str) -> Optional[str]:
    """Percentage change vs previous. Returns None for IRRs and ratios
    (where percent change is misleading or unstable), or for zero
    previous value."""
    if fmt != "keur":
        return None  # only show % for kEUR values
    if prev == 0:
        return None
    pct = (d / prev) * 100.0
    sign = "+" if pct >= 0 else ""
    return f"{sign}{pct:.1f}%"


def compute_metric_delta(
    metric_key: str,
    display_label: str,
    fmt: str,
    previous: Optional[dict[str, Any]],
    current: Optional[dict[str, Any]],
) -> dict[str, Any]:
    """Compute the delta row for a single metric.

    Returns a dict with keys:
      key, label, format,
      has_previous, has_current,
      current_display, previous_display,
      delta_display, percent_display (or None),
      state: "n_a" | "zero" | "positive" | "negative"
    """
    prev_raw = (previous or {}).get(metric_key)
    cur_raw = (current or {}).get(metric_key)
    prev_v = _coerce_float(prev_raw)
    cur_v = _coerce_float(cur_raw)

    if cur_v is None and prev_v is None:
        return {
            "key": metric_key,
            "label": display_label,
            "format": fmt,
            "has_previous": False,
            "has_current": False,
            "current_display": "—",
            "previous_display": "—",
            "delta_display": "—",
            "percent_display": None,
            "state": "n_a",
        }
    if cur_v is None:
        return {
            "key": metric_key,
            "label": display_label,
            "format": fmt,
            "has_previous": prev_v is not None,
            "has_current": False,
            "current_display": "—",
            "previous_display": _format_value(prev_v, fmt),
            "delta_display": "—",
            "percent_display": None,
            "state": "n_a",
        }
    if prev_v is None:
        return {
            "key": metric_key,
            "label": display_label,
            "format": fmt,
            "has_previous": False,
            "has_current": True,
            "current_display": _format_value(cur_v, fmt),
            "previous_display": "—",
            "delta_display": "—",
            "percent_display": None,
            "state": "n_a",
        }
    d = cur_v - prev_v
    if abs(d) < 1e-9:
        state = "zero"
    elif d > 0:
        state = "positive"
    else:
        state = "negative"
    return {
        "key": metric_key,
        "label": display_label,
        "format": fmt,
        "has_previous": True,
        "has_current": True,
        "current_display": _format_value(cur_v, fmt),
        "previous_display": _format_value(prev_v, fmt),
        "delta_display": _format_delta(d, fmt),
        "percent_display": _percent_delta(d, prev_v, fmt),
        "state": state,
        # raw floats (used by tests)
        "current_value": cur_v,
        "previous_value": prev_v,
        "delta_value": d,
    }


def compute_what_changed(
    previous: Optional[dict[str, Any]],
    current: Optional[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Compute all metric deltas and return a list ready for Jinja2."""
    return [
        compute_metric_delta(key, label, fmt, previous, current)
        for (key, label, fmt) in WHAT_CHANGED_METRICS
    ]


def has_any_comparable_delta(panel_rows: list[dict[str, Any]]) -> bool:
    """True if at least one row has a real (non n_a) delta to display."""
    return any(r.get("state") in ("positive", "negative", "zero") for r in panel_rows)


def build_scenario_card_deltas(
    card: dict[str, Any],
) -> dict[str, Any]:
    """Return a copy of the summary card with delta-enrichment fields.

    The card already carries the *current* run summary (subset: project_irr,
    equity_irr, avg_dscr, etc.). The previous run summary is fetched from
    ``card["previous_run_summary"]`` (set by the caller from
    ``scenario.replay_metadata['previous_run_summary']``).

    Returns a *new* dict so the caller's original card is not mutated.
    Adds the following fields, ready for the ``what_changed_panel.html``
    partial:

      - ``has_previous_run``: bool
      - ``panel_rows``: list[dict] (one row per supported metric)
      - ``is_user_project``: bool (from card, default False)
      - ``template_source``: str (from card, default "")

    Pure function, no DB access, no I/O.
    """
    if not isinstance(card, dict):
        raise TypeError("card must be a dict")
    enriched = dict(card)
    is_user_project = bool(card.get("is_user_project", False))
    template_source = str(card.get("template_source", "") or "")
    previous = card.get("previous_run_summary") or None
    current = {
        "project_irr": card.get("project_irr"),
        "equity_irr": card.get("equity_irr"),
        "avg_dscr": card.get("avg_dscr"),
        # Other fields default to None when the card subset is limited.
    }
    has_previous = isinstance(previous, dict) and bool(previous)
    enriched["has_previous_run"] = has_previous
    enriched["is_user_project"] = is_user_project
    enriched["template_source"] = template_source
    enriched["panel_rows"] = compute_what_changed(
        previous if has_previous else None,
        current,
    )
    return enriched
