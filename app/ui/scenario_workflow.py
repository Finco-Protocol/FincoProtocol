"""Phase 25B-5 — Scenario workflow polish helpers (pure functions).

Goal: make the Base / Downside / Upside workflow obvious for a
first-time finance user. The data model is unchanged — this module
is a label-and-shape helper that the templates can call to render
clearer scenario cards, compare shortcuts, and quick summary cards.

All helpers are **pure**:
- No DB, no I/O, no time, no random, no side-effects.

The template side calls these helpers per scenario card and renders
the returned dict. The "active" highlight is already done via the
``svh-card--active`` class on the wrapper div (this module does not
override that — the CSS for it is added in ``static/styles.css``
under the ``.svh-*`` prefix).
"""
from __future__ import annotations

from typing import Any, Optional

# ── Constants ─────────────────────────────────────────────────────────────
# Scenario labels: the canonical "Base / Downside / Upside" triplet
# is recognised by name. Custom scenario names are passed through.

BASE_LABELS = {"base", "baseline", "case", "main"}
DOWNSIDE_LABELS = {"downside", "down", "low", "p10", "pessimistic", "stress"}
UPSIDE_LABELS = {"upside", "up", "high", "p90", "optimistic"}

# Numeric thresholds for "good / ok / bad" quick-summary chips.
EQUITY_IRR_OK = 0.08
EQUITY_IRR_GOOD = 0.12
DSCR_OK = 1.2
DSCR_GOOD = 1.5


# ── Label classification ──────────────────────────────────────────────────

def classify_scenario_label(scenario_name: str) -> dict[str, Any]:
    """Classify a scenario name into a canonical label.

    Returns
    -------
    dict with fields:
      - ``kind``: one of "base" | "downside" | "upside" | "custom"
      - ``display_name``: the original scenario name
      - ``icon``: a single character used as a visual hint
      - ``css_class``: CSS class for the label chip
    """
    name = (scenario_name or "").strip()
    name_lower = name.lower()
    if name_lower in BASE_LABELS:
        return {
            "kind": "base",
            "display_name": name,
            "icon": "B",
            "css_class": "sw-label--base",
        }
    if name_lower in DOWNSIDE_LABELS:
        return {
            "kind": "downside",
            "display_name": name,
            "icon": "D",
            "css_class": "sw-label--downside",
        }
    if name_lower in UPSIDE_LABELS:
        return {
            "kind": "upside",
            "display_name": name,
            "icon": "U",
            "css_class": "sw-label--upside",
        }
    return {
        "kind": "custom",
        "display_name": name,
        "icon": "•",
        "css_class": "sw-label--custom",
    }


# ── Quick summary card data ──────────────────────────────────────────────

def quick_summary_card(card: dict[str, Any]) -> dict[str, Any]:
    """Build a small KPI summary for a single scenario card.

    Returns
    -------
    dict with fields:
      - ``equity_irr_pct``: formatted IRR string (e.g. "11.4 %")
      - ``project_irr_pct``: formatted Project IRR string
      - ``avg_dscr_x``: formatted DSCR string (e.g. "1.45 x")
      - ``irr_state``: "good" | "ok" | "bad" | "n_a"
      - ``dscr_state``: "good" | "ok" | "bad" | "n_a"
    """
    def _fmt_pct(v: Optional[float]) -> str:
        if v is None:
            return "—"
        try:
            return f"{float(v) * 100:.1f} %"
        except (TypeError, ValueError):
            return "—"

    def _fmt_x(v: Optional[float]) -> str:
        if v is None:
            return "—"
        try:
            return f"{float(v):.2f} x"
        except (TypeError, ValueError):
            return "—"

    def _state_pct(v: Optional[float]) -> str:
        if v is None:
            return "n_a"
        try:
            f = float(v)
        except (TypeError, ValueError):
            return "n_a"
        if f >= EQUITY_IRR_GOOD:
            return "good"
        if f >= EQUITY_IRR_OK:
            return "ok"
        return "bad"

    def _state_dscr(v: Optional[float]) -> str:
        if v is None:
            return "n_a"
        try:
            f = float(v)
        except (TypeError, ValueError):
            return "n_a"
        if f >= DSCR_GOOD:
            return "good"
        if f >= DSCR_OK:
            return "ok"
        return "bad"

    eq = card.get("equity_irr")
    pr = card.get("project_irr")
    ds = card.get("avg_dscr")
    return {
        "equity_irr_pct": _fmt_pct(eq),
        "project_irr_pct": _fmt_pct(pr),
        "avg_dscr_x": _fmt_x(ds),
        "irr_state": _state_pct(eq),
        "dscr_state": _state_dscr(ds),
    }


# ── Compare shortcut links ───────────────────────────────────────────────

def build_compare_shortcut_links(
    cards: list[dict[str, Any]],
    active_scenario_id: str = "",
    project_code: str = "",
) -> list[dict[str, Any]]:
    """Build a list of "Compare with X" shortcut links for the active
    scenario.

    Each item is a dict suitable for the template:

      - ``href``: the ``/scenarios/compare`` URL with the appropriate
        ``left_scenario_id``, ``right_scenario_id`` and ``project``
        query params. ``project`` is always the currently loaded
        project's code -- UX-2G-COMPARE-FIX -- so the link never
        silently falls back to the route's "generic_wind_reference" default and
        resolves scenarios from the wrong project.
      - ``label``: "Compare with <name>"
      - ``kind``: "base" | "downside" | "upside" | "custom"
      - ``css_class``: visual chip class
    """
    if not active_scenario_id:
        return []
    # Find the active card and the candidate comparison targets.
    active_card = next(
        (c for c in cards if c.get("scenario_id") == active_scenario_id),
        None,
    )
    if not active_card:
        return []
    active_kind = classify_scenario_label(active_card.get("scenario_name", ""))["kind"]

    links: list[dict[str, Any]] = []
    for c in cards:
        cid = c.get("scenario_id", "")
        if not cid or cid == active_scenario_id:
            continue
        target_name = c.get("scenario_name", "")
        target_label = classify_scenario_label(target_name)
        # Prefer Base as the "left" side. If active is Base, compare
        # against Downside (or Upside if no Downside exists).
        if active_kind == "base":
            if target_label["kind"] not in ("downside", "upside"):
                continue
        elif target_label["kind"] == "base":
            pass  # Always allow "compare with base" link.
        elif target_label["kind"] in ("downside", "upside"):
            pass  # Other named scenario
        else:
            # Compare with custom scenarios too.
            pass
        _project_qs = f"&project={project_code}" if project_code else ""
        links.append({
            "href": (
                f"/scenarios/compare?left_scenario_id={active_scenario_id}"
                f"&right_scenario_id={cid}{_project_qs}"
            ),
            "label": f"Compare with {target_name}",
            "kind": target_label["kind"],
            "css_class": target_label["css_class"],
            "right_scenario_id": cid,
            "right_scenario_name": target_name,
        })
    # Sort: base first, then downside, then upside, then custom.
    order = {"base": 0, "downside": 1, "upside": 2, "custom": 3}
    links.sort(key=lambda l: (order.get(l["kind"], 9), l["label"]))
    return links


# ── Empty / one-scenario / multi-scenario state ───────────────────────────

def workflow_state(cards: list[dict[str, Any]]) -> dict[str, Any]:
    """Classify the scenario-list state for the empty-state notice.

    Returns
    -------
    dict with fields:
      - ``count``: number of scenarios
      - ``state``: "empty" | "one" | "two" | "many"
      - ``message``: a one-line user-facing message
      - ``css_class``: visual class for the notice
    """
    n = len(cards or [])
    if n == 0:
        return {
            "count": 0,
            "state": "empty",
            "message": "No saved scenarios yet. Save a snapshot to start comparing.",
            "css_class": "sw-empty--empty",
        }
    if n == 1:
        return {
            "count": 1,
            "state": "one",
            "message": (
                "One scenario saved. Add at least one more (Downside or "
                "Upside) to enable side-by-side compare."
            ),
            "css_class": "sw-empty--one",
        }
    if n == 2:
        return {
            "count": 2,
            "state": "two",
            "message": "Two scenarios ready. Use compare to view the delta.",
            "css_class": "sw-empty--two",
        }
    return {
        "count": n,
        "state": "many",
        "message": f"{n} scenarios saved. Pick a pair or run a multi-compare.",
        "css_class": "sw-empty--many",
    }


# ── Composer ──────────────────────────────────────────────────────────────

def build_scenario_workflow_ui(
    cards: list[dict[str, Any]],
    *,
    active_scenario_id: str = "",
    project_code: str = "",
) -> dict[str, Any]:
    """Build the full ``scenario_workflow_ui`` payload for the template.

    Combines the three concerns (label, quick summary, compare
    shortcut) into a single dict keyed by ``scenario_id`` for easy
    lookup, plus the workflow_state for the empty-state notice.

    Returns
    -------
    dict with fields:
      - ``by_scenario``: dict[scenario_id, dict] with keys
        ``label``, ``quick_summary``, ``is_active``
      - ``compare_links``: list of compare-shortcut dicts
      - ``state``: result of ``workflow_state(cards)``
    """
    by_scenario: dict[str, dict[str, Any]] = {}
    for c in (cards or []):
        sid = c.get("scenario_id", "")
        if not sid:
            continue
        by_scenario[sid] = {
            "label": classify_scenario_label(c.get("scenario_name", "")),
            "quick_summary": quick_summary_card(c),
            "is_active": bool(sid == active_scenario_id),
        }
    return {
        "by_scenario": by_scenario,
        "compare_links": build_compare_shortcut_links(
            list(cards or []),
            active_scenario_id=active_scenario_id,
            project_code=project_code,
        ),
        "state": workflow_state(list(cards or [])),
    }
