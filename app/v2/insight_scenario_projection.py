"""app.v2.insight_scenario_projection — read-only cross-scenario intelligence for FINCO Insight.

Every value originates from a scenario's own committed Run in the immutable Run History
(``app.persistence.run_history_repository``) — the same authority the scenario workspace restores from
(newest successful entry per ``last_runtime_scenario_id``; a pre-scenario Base Case Run carries no scenario id).

* KPI values and deltas come from the existing ``build_scenario_projection`` / ``build_compare_rows``
  (canonical ``KPI_CATALOG`` formatting, pass-through, no recalculation).
* Model Quality is the Q1 report evaluated over that scenario's own committed evidence.
* Freshness against the Working Copy is only known for the ACTIVE scenario (canonical runtime freshness).
  Every other scenario is shown as its last committed Run ("HISTORICAL RUN"), never as CURRENT, and its
  thresholds are not bound (the Run does not persist them), so no covenant verdict is produced for it.
* Nothing here runs the engine, selects or creates a scenario, or writes.
"""
from __future__ import annotations

from typing import Any, Optional, Sequence

from app.model_quality import evaluate_model_quality
from app.model_quality.contracts import CheckStatus
from app.model_quality.evidence import evidence_from_history_entry
from app.v2.output_metric_projection import KPI_CATALOG
from app.v2.run_history_projection import _enriched_kpis
from app.v2.scenario_kpi_projection import build_compare_rows, build_scenario_projection

COMPARE_KEYS = ("project_irr", "equity_irr", "sponsor_irr", "senior_debt_keur", "min_dscr", "avg_dscr",
                "min_llcr", "target_dscr")
MAX_SCENARIOS = 8
HISTORY_SCAN_LIMIT = 200


def _newest_per_scenario(entries: Sequence[Any], scenarios: Sequence[Any]) -> dict[str, Any]:
    """Newest committed Run per scenario id (``entries`` are newest-first, the canonical ordering)."""
    base_ids = {s.scenario_id for s in scenarios if getattr(s, "is_base_case", False)}
    wanted = {s.scenario_id for s in scenarios}
    found: dict[str, Any] = {}
    for entry in entries:
        sid = getattr(entry, "last_runtime_scenario_id", None)
        if sid is None:
            targets = base_ids                      # pre-scenario Base Case Run (None == Base Case)
        else:
            targets = {sid} & wanted
        for target in targets:
            found.setdefault(target, entry)
    return found


def _quality_summary(entry: Any, *, freshness: Optional[str], scenario_id: str) -> dict[str, Any]:
    report = evaluate_model_quality(evidence_from_history_entry(
        entry, freshness=freshness, active_scenario_id=scenario_id, scenario_known=True))
    s = report.summary
    return {
        "score": s.score, "score_display": None if s.score is None else f"{s.score:.1f} / 100",
        "score_status": s.score_status,
        "coverage_weighted_pct": None if s.coverage_weighted is None else round(s.coverage_weighted * 100, 1),
        "blocked": s.blocked, "fail": s.failed, "warning": s.warnings, "unavailable": s.unavailable,
        "blocking_ids": list(report.blocking_findings),
    }


def build_scenario_insight(
    *, scenarios: Sequence[Any], run_history: Sequence[Any], active_scenario_id: Optional[str],
    active_run_state: str, last_run_snapshot_id: Optional[str],
    active_covenant_issue_count: Optional[int] = None, active_quality: Optional[dict] = None,
) -> dict[str, Any]:
    """Compact scenario comparison dict.  ``scenarios`` are non-archived scenario records."""
    scenarios = list(scenarios)[:MAX_SCENARIOS]
    if active_scenario_id is None:
        # The workspace records no scenario id for the Base Case (None == Base Case).
        active_scenario_id = next((s.scenario_id for s in scenarios if getattr(s, "is_base_case", False)), None)
    state = active_run_state if active_run_state in ("CURRENT", "STALE") else "NOT_RUN"
    newest = _newest_per_scenario(run_history, scenarios)
    rows: list[dict[str, Any]] = []
    projections: dict[str, Any] = {}
    for sc in scenarios:
        entry = newest.get(sc.scenario_id)
        is_active = sc.scenario_id == active_scenario_id
        row: dict[str, Any] = {
            "scenario_id": sc.scenario_id, "name": sc.scenario_name, "is_base": bool(sc.is_base_case),
            "is_active": is_active, "has_run": entry is not None,
        }
        if entry is None:
            row.update({"basis": "NO_RUN", "basis_note": "No committed Run for this scenario.", "quality": None})
            rows.append(row)
            continue
        matches_last = bool(last_run_snapshot_id) and entry.runtime_snapshot_id == last_run_snapshot_id
        if is_active:
            basis = state if matches_last else "HISTORICAL_RUN"
            note = {"CURRENT": "CURRENT — Working Copy matches this scenario's Last Run.",
                    "STALE": "STALE — the Working Copy changed after this Run; values are the PRIOR Run.",
                    "NOT_RUN": "NOT_RUN"}.get(basis, "Newest committed Run; it is not the workspace Last Run.")
        else:
            basis, note = "HISTORICAL_RUN", ("Last committed Run of this scenario. Freshness against the "
                                             "Working Copy is only evaluated for the active scenario.")
        proj = build_scenario_projection(sc.scenario_name, _enriched_kpis(entry), entry.ran_at,
                                         is_stale=(basis != "CURRENT"))
        projections[sc.scenario_id] = proj
        labels = {k: lbl for k, lbl, _u, _f, _s in KPI_CATALOG}
        row["kpis"] = [{"label": labels[k], "value": proj.kpis.get(k, "—")} for k in COMPARE_KEYS if k in labels]
        if is_active and matches_last and active_quality is not None:
            quality = dict(active_quality)      # the SAME report shown in Findings, never re-derived
        else:
            quality = _quality_summary(entry, freshness=None, scenario_id=sc.scenario_id)
        row.update({
            "basis": basis, "basis_note": note,
            "run": {"history_id": entry.history_id, "snapshot_id": entry.runtime_snapshot_id,
                    "ran_at": (entry.ran_at or "")[:16].replace("T", " "), "composite_hash": entry.composite_hash,
                    "engine_version": entry.engine_version},
            "quality": quality,
            "covenant_note": (
                (f"{active_covenant_issue_count} covenant/threshold finding(s) on the active Run"
                 if active_covenant_issue_count else "No covenant/threshold warning on the active Run")
                if is_active and basis == "CURRENT" and active_covenant_issue_count is not None
                else "Covenant thresholds are not bound to this Run, so no covenant verdict is shown."),
        })
        rows.append(row)

    active = next((r for r in rows if r["is_active"]), None)
    comparisons: list[dict[str, Any]] = []
    if active and active["has_run"]:
        base_proj = projections[active["scenario_id"]]
        for other in rows:
            if other["is_active"] or not other["has_run"]:
                continue
            table = build_compare_rows([base_proj, projections[other["scenario_id"]]])
            lines = [{"key": r.key, "label": r.label, "active": r.values[0], "other": r.values[1],
                      "delta": r.deltas[1]} for r in table if r.key in COMPARE_KEYS]
            comparisons.append({"scenario_id": other["scenario_id"], "name": other["name"], "rows": lines,
                                "other_basis": other["basis"]})
    banner = ""
    if active and active["basis"] == "STALE":
        banner = ("The active scenario's Working Copy has changed since its Run: its column is the PRIOR Run, "
                  "not the modified Working Copy.")
    return {
        "available": bool(rows), "state": state, "rows": rows, "comparisons": comparisons, "banner": banner,
        "active_scenario_id": active_scenario_id,
        "message": "" if rows else "No scenarios are available for this project.",
        "unavailable_note": "A metric shown as — is not persisted by that scenario's Run; nothing is estimated.",
    }


def build_scenario_insight_safe(**kwargs: Any) -> dict[str, Any]:
    try:
        return build_scenario_insight(**kwargs)
    except Exception:  # noqa: BLE001 - presentation adapter must fail closed
        return {"available": False, "state": "UNAVAILABLE", "rows": [], "comparisons": [], "banner": "",
                "message": "Scenario comparison could not be built from the persisted Runs.",
                "unavailable_note": ""}


__all__ = ["COMPARE_KEYS", "build_scenario_insight", "build_scenario_insight_safe"]
