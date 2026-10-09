"""app.v2.kpi_strip_projection — persistent Key-metrics strip (presentation only).

A compact, always-visible set of the headline outputs of the persisted Last Run, so a
user does not have to return to Overview.  Every value is read from the SAME persisted
authorities the Overview already uses and goes through the canonical
``OutputMetricProjection`` builder (raw value -> display string, never the reverse):

* ``runtime_summary``            Project IRR, Pure Equity IRR, Min DSCR, Senior Debt, ...
* ``sponsor_schedule.summary``   Total Sponsor IRR / MOIC (explicit per-key field map)
* ``runtime_summary.actual_gearing_pct``  Actual gearing (fraction)

No arithmetic, no inference between metrics, no engine execution, no Run.  A metric that
the persisted Last Run does not carry (Project NPV, total CFADS today) is shown as
unavailable with the reason — never as zero and never derived from period values.  A genuine
persisted 0 stays 0.  When the Working Copy changed since the Last Run the values are the
PRIOR run's and are labelled as such; when there is no Last Run nothing is shown.

The independent Run-integrity verdict (PASS / FAIL / INCOMPLETE) is carried alongside and is
never merged with freshness: a CURRENT Last Run can have a FAIL integrity verdict, and a STALE
one is not an integrity failure.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from app.v2.output_metric_projection import (
    SPONSOR_SUMMARY_SOURCE_KEYS,
    _apply_fmt,
    _safe_float,
    build_output_metric_projection,
)

# (key, label, unit, fmt, source, persisted field, drill tab, authority-gap note)
#   source: "runtime_summary" | "sponsor_schedule.summary"
_GAP_NOT_PERSISTED = "Not persisted by the model run (authority gap) — never derived here."
STRIP_SPEC: tuple[tuple, ...] = (
    ("project_irr", "Project IRR", "%", "pct", "runtime_summary", "project_irr", "tab-returns", ""),
    ("equity_irr", "Pure Equity IRR", "%", "pct", "runtime_summary", "equity_irr", "tab-returns", ""),
    ("sponsor_irr", "Total Sponsor IRR", "%", "pct", "sponsor_schedule.summary",
     SPONSOR_SUMMARY_SOURCE_KEYS["sponsor_irr"], "tab-returns", ""),
    ("sponsor_moic", "Total Sponsor MOIC", "x", "ratio", "sponsor_schedule.summary",
     SPONSOR_SUMMARY_SOURCE_KEYS["sponsor_moic"], "tab-returns", ""),
    ("project_npv_keur", "Project NPV", "kEUR", "keur", "runtime_summary", "project_npv_keur",
     "tab-returns", _GAP_NOT_PERSISTED),
    ("min_dscr", "Min DSCR", "x", "ratio", "runtime_summary", "min_dscr", "tab-debt", ""),
    ("senior_debt_keur", "Senior Debt", "kEUR", "keur", "runtime_summary", "senior_debt_keur",
     "tab-debt", ""),
    ("actual_gearing_pct", "Actual Gearing", "%", "pct", "runtime_summary", "actual_gearing_pct",
     "tab-debt", ""),
    ("total_cfads_keur", "Total CFADS", "kEUR", "keur", "runtime_summary", "total_cfads_keur",
     "tab-debt", _GAP_NOT_PERSISTED),
)

_FRESHNESS = {"CURRENT": "current", "STALE": "stale", "NOT_RUN": "not_run"}


@dataclass(frozen=True)
class KpiStripItem:
    key: str
    label: str
    display: str
    unit: str
    raw_value: Optional[float]
    available: bool
    freshness: str            # current | stale | not_run
    source: str               # persisted authority, e.g. "runtime_summary.project_irr"
    drill_tab: str
    note: str = ""            # why unavailable (typed) or ""

    @property
    def title(self) -> str:
        bits = [f"Source: {self.source}"]
        if self.unit:
            bits.append(f"Unit: {self.unit}")
        if self.freshness == "stale":
            bits.append("Prior Last Run — Working Copy has changed since.")
        if self.note and not self.available:
            bits.append(self.note)
        return " · ".join(bits)


@dataclass(frozen=True)
class KpiStrip:
    state: str                              # NOT_RUN | CURRENT | STALE
    items: tuple[KpiStripItem, ...]
    caption: str
    run_at_display: str = ""
    scenario_name: str = ""
    snapshot_short: str = ""
    integrity_value: str = ""               # PASS | FAIL | INCOMPLETE | UNAVAILABLE | ""
    integrity_tone: str = ""
    integrity_detail: str = ""

    @property
    def has_values(self) -> bool:
        return self.state != "NOT_RUN"


def _persisted(source: Any, kind: str, field: str) -> Any:
    block = (source or {}).get("sponsor_summary" if kind == "sponsor_schedule.summary" else "runtime_summary")
    return (block or {}).get(field) if isinstance(block, dict) else None


def build_kpi_strip(
    source: Optional[dict[str, Any]],
    *,
    runtime_state: str,
    integrity: Optional[dict[str, Any]] = None,
    last_run: Optional[dict[str, Any]] = None,
    scenario_name: str = "",
) -> KpiStrip:
    """Project the strip from the persisted Last Run (``source``) and the freshness state.

    ``source`` is ``{"state": "AVAILABLE", "runtime_summary": {...}, "sponsor_summary": {...}}``
    as composed by the Trust Pack from the workspace's persisted payloads.
    """
    state = str(runtime_state or "").strip().upper()
    state = state if state in _FRESHNESS else "NOT_RUN"
    have_run = isinstance(source, dict) and str(source.get("state", "")).upper() == "AVAILABLE"
    if not have_run:
        state = "NOT_RUN"
    freshness = _FRESHNESS[state]

    items: list[KpiStripItem] = []
    for key, label, unit, fmt, kind, field, tab, gap in STRIP_SPEC:
        raw = _persisted(source, kind, field) if state != "NOT_RUN" else None
        if key == "actual_gearing_pct":
            f = _safe_float(raw)
            display = _apply_fmt(f, "pct") if f is not None else "—"
            raw_f = f
        else:
            proj = build_output_metric_projection(key, raw, freshness=freshness)
            display, raw_f = proj.display_value, proj.raw_value
        available = raw_f is not None
        if state == "NOT_RUN":
            note = "Run the model to produce this value."
        elif available:
            note = ""
        else:
            note = gap or "Not available in this Last Run."
        items.append(KpiStripItem(
            key=key, label=label, display=display, unit=unit, raw_value=raw_f,
            available=available, freshness=freshness,
            source=f"{kind}.{field}", drill_tab=tab, note=note,
        ))

    caption = {
        "CURRENT": "Last Run — matches the current Working Copy.",
        "STALE": "Prior Last Run — the Working Copy has changed since; values are not current.",
        "NOT_RUN": "No Last Run yet — run the model to see key metrics.",
    }[state]

    lr = last_run or {}
    integ_value = integ_tone = integ_detail = ""
    if state != "NOT_RUN" and isinstance(integrity, dict) and integrity:
        from app.v2.smart_panel_projection import _integrity_row
        row = _integrity_row(integrity)
        if row is not None:
            integ_value, integ_tone, integ_detail = row.value, row.tone, row.detail
    return KpiStrip(
        state=state, items=tuple(items), caption=caption,
        run_at_display=str(lr.get("run_at_display") or "") if state != "NOT_RUN" else "",
        scenario_name=str(scenario_name or ""),
        snapshot_short=str(lr.get("composite_hash_short") or "") if state != "NOT_RUN" else "",
        integrity_value=integ_value, integrity_tone=integ_tone, integrity_detail=integ_detail,
    )


__all__ = ["KpiStrip", "KpiStripItem", "STRIP_SPEC", "build_kpi_strip"]
