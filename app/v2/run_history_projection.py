"""app.v2.run_history_projection — Run Intelligence presentation projections.

Presentation-only reads over the EXISTING canonical append-only Run History
authority (``app.persistence.run_history_repository`` — the read API's first
production consumer).  No persistence semantics change, no engine execution,
no financial recomputation: every value displayed here is either identity
metadata stored on the immutable history row or a persisted KPI rendered
through the canonical ``OutputMetricProjection`` catalog.

STATUS SEMANTICS (canonical correction — do not fork the freshness authority):

- ``CURRENT`` / ``STALE`` describe ONLY the canonical Last Run relative to
  the current Working Copy (existing ``resolve_runtime_freshness`` authority
  owns that decision; this module merely renders its result).
- Every older immutable successful run is ``HISTORICAL``.  A historical run
  MAY additionally expose the presentation-only indicator
  ``MATCHES WORKING COPY`` when its stored composite hash (or, for V2-bound
  rows, the stored binding economic identity) equals the current Working
  Copy identity — that indicator NEVER makes the row CURRENT.  Multiple
  historical rows may legitimately match.
- Failed execution attempts are never recorded in canonical history; the
  surface states this honestly and fabricates nothing.

The Last Run row is identified by ``runtime_snapshot_id`` equality with the
workspace's ``last_runtime_snapshot_id`` — presentation labeling only; the
canonical Last Run itself remains the workspace authority.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Optional

from app.v2.output_metric_projection import build_output_metric_projection
from app.v2.scenario_kpi_projection import (
    build_compare_rows,
    build_scenario_projection,
)

# Bounded listing size for the Run History surface.
HISTORY_LIST_LIMIT = 25

STATUS_HISTORICAL = "HISTORICAL"
INDICATOR_MATCHES = "MATCHES WORKING COPY"


def _short(value: Any, keep: int = 8) -> str:
    text = str(value or "")
    return text[:keep] if text else "—"


def _display_ts(value: Any) -> str:
    text = str(value or "")
    return text[:16].replace("T", " ") if text else "—"


def _enriched_kpis(entry: Any) -> dict:
    """Persisted KPI view for one history row.

    Base = the row's ``runtime_summary`` (raw engine kpis, pass-through).
    Debt-coverage and sponsor-schedule summary fields are merged from the
    SAME stored row's schedules via the canonical source-key mapping —
    identical sourcing to the Overview projection, still pass-through with
    zero recomputation.
    """
    from app.v2.output_metric_projection import SPONSOR_SUMMARY_SOURCE_KEYS

    kpis = dict(getattr(entry, "runtime_summary", None) or {})
    debt_summary = (getattr(entry, "debt_schedule", None) or {}).get(
        "summary", {}) or {}
    for key in ("min_llcr", "target_dscr"):
        if key in debt_summary and kpis.get(key) is None:
            kpis[key] = debt_summary.get(key)
    sponsor_summary = (getattr(entry, "sponsor_schedule", None) or {}).get(
        "summary", {}) or {}
    for catalog_key, field in SPONSOR_SUMMARY_SOURCE_KEYS.items():
        if kpis.get(catalog_key) is None:
            kpis[catalog_key] = sponsor_summary.get(field)
    return kpis


@dataclass(frozen=True)
class RunHistoryRow:
    """One dense listing row (display payload only)."""

    history_id: str
    ran_at_display: str
    scenario_name: str
    origin: str
    engine_version: str
    workbook_version: str
    snapshot_short: str
    composite_short: str
    is_last_run: bool
    matches_working_copy: bool
    detail_url: str
    compare_url: str

    @property
    def status_label(self) -> str:
        return "LAST RUN" if self.is_last_run else STATUS_HISTORICAL


def build_run_history_rows(
    entries: Iterable[Any],
    *,
    ws: Any,
    current_composite_hash: Optional[str],
    project_code: str,
    detail_url_tpl: str = "/v2/workbook/run-history/detail?project={project}&history_id={history_id}",
    compare_url_tpl: str = "/v2/workbook/run-history/compare?project={project}&history_id={history_id}",
) -> list[RunHistoryRow]:
    """Project immutable history entries into dense listing rows.

    ``matches_working_copy`` is the presentation-only indicator: the row's
    stored composite hash equals the current Working Copy composite hash
    (or, for V2-bound rows, the stored binding economic identity equals the
    current selection digest).  It never changes a row's HISTORICAL status.
    """
    from app.model_v2.persistence import read_workspace_run_binding

    last_snapshot_id = str(getattr(ws, "last_runtime_snapshot_id", "") or "")
    current_digest = None
    try:
        binding = read_workspace_run_binding(
            getattr(ws, "last_runtime_identity", None))
        if binding is not None:
            current_digest = binding.get("economic_identity")
    except Exception:
        current_digest = None

    rows: list[RunHistoryRow] = []
    for entry in entries:
        matches = bool(
            current_composite_hash
            and entry.composite_hash
            and str(entry.composite_hash) == str(current_composite_hash)
        )
        if not matches and current_digest:
            stored = (getattr(entry, "model_v2_binding", None) or {}).get(
                "economic_identity")
            matches = bool(stored and str(stored) == str(current_digest))
        rows.append(RunHistoryRow(
            history_id=entry.history_id,
            ran_at_display=_display_ts(entry.ran_at),
            scenario_name=getattr(entry, "active_scenario_name", None)
            or "Base",
            origin=str(getattr(entry, "runtime_origin", "") or "—"),
            engine_version=str(getattr(entry, "engine_version", "") or "—"),
            workbook_version=str(getattr(entry, "workbook_version", "") or "—"),
            snapshot_short=_short(getattr(entry, "runtime_snapshot_id", None)),
            composite_short=_short(getattr(entry, "composite_hash", None)),
            is_last_run=bool(
                last_snapshot_id
                and str(entry.runtime_snapshot_id) == last_snapshot_id
            ),
            matches_working_copy=matches,
            detail_url=detail_url_tpl.format(project=project_code,
                                             history_id=entry.history_id),
            compare_url=compare_url_tpl.format(project=project_code,
                                               history_id=entry.history_id),
        ))
    return rows


def run_history_metrics(entry: Any) -> list[tuple[str, str, str]]:
    """Canonical metric rows for one historical run's detail view.

    Ordered by the KPI catalog; every value is the persisted
    KPI/schedule-summary number rendered through
    ``build_output_metric_projection`` — unavailable stays unavailable
    ('—'), legitimate zero stays zero, nothing is reconstructed.
    Returns (key, label, display_value) tuples.
    """
    from app.v2.output_metric_projection import KPI_CATALOG

    kpis = _enriched_kpis(entry)
    rows: list[tuple[str, str, str]] = []
    for entry_key, _label, _unit, _fmt, _source in KPI_CATALOG:
        m = build_output_metric_projection(entry_key, kpis.get(entry_key))
        rows.append((entry_key, m.label, m.display_value))
    return rows


def build_run_compare(
    *,
    last_run_kpis: Optional[dict],
    last_run_ran_at: str,
    last_run_is_stale: bool,
    history_entry: Any,
    last_run_label: str = "Last Run",
) -> dict:
    """Current-vs-historical compare via the EXISTING compare machinery.

    Column 1 = canonical Last Run (chip CURRENT or STALE from the freshness
    authority), column 2 = the selected immutable historical run (chip
    HISTORICAL, with the presentation-only MATCHES WORKING COPY indicator
    where applicable).  Deltas come from ``build_compare_rows`` (raw float
    delta vs the first column) — read-only data-source substitution with no
    financial recomputation.
    """
    last_proj = build_scenario_projection(
        last_run_label,
        last_run_kpis or None,
        last_run_ran_at,
        last_run_is_stale,
    )
    hist_label = (f"Historical run · "
                  f"{_display_ts(getattr(history_entry, 'ran_at', ''))}")
    hist_proj = build_scenario_projection(
        hist_label,
        _enriched_kpis(history_entry) or None,
        str(getattr(history_entry, "ran_at", "") or ""),
        False,  # an immutable historical snapshot is never 'stale'
    )
    rows = build_compare_rows([last_proj, hist_proj])
    return {
        "columns": [
            {"label": last_run_label, "state": "STALE" if last_run_is_stale else "CURRENT",
             "ran_at": last_proj.ran_at},
            {"label": hist_label, "state": STATUS_HISTORICAL,
             "ran_at": hist_proj.ran_at},
        ],
        "rows": rows,
    }


__all__ = [
    "HISTORY_LIST_LIMIT",
    "INDICATOR_MATCHES",
    "STATUS_HISTORICAL",
    "RunHistoryRow",
    "build_run_compare",
    "build_run_history_rows",
    "run_history_metrics",
]
