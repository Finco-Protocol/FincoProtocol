"""Export and audit persistence functions extracted from app/persistence/repository.py.

This module holds Group E export/audit persistence functions extracted
during Phase 53C. The functions are re-exported from
app.persistence.repository for backward compatibility.

Function inventory (Group E, from Phase 52A/52C/52E/52G):

- ScenarioExportRecord (moved to records.py in Phase 53I-2)
- record_export           (high-risk write, audited by Phase 49 tests)
- list_exports
- get_scenario_history
- compare_scenarios
- build_export_lineage
- base_vs_active_compare
- _scenario_runtime_dict
- _build_compare_metrics
- _delta_sign_class
- _format_db_timestamp

Behavior is preserved exactly as it was in repository.py. The only
change is the file location.

Note on record_export: this is one of the 7 high-risk writes
identified in Phase 52. The Phase 52 plan classified Group E as
auto-merge eligible because the audit pipeline is already pinned by
Phase 49 tests (test_phase49d3a_export_audit_recording_characterization
and related). The move here does not change behavior, signatures, or
SQL text. Replay_metadata defaulting is preserved verbatim.
"""
from __future__ import annotations

import uuid
from typing import Any, Optional

from app.persistence._helpers import _from_iso, _from_json, _now_utc, _to_json, snapshots_equal
from app.persistence.db import get_cursor
# Phase 53I-2: ScenarioExportRecord moved to app/persistence/records.py
from app.persistence.records import ScenarioExportRecord




def record_export(
    user_id: str,
    project_code: str,
    export_type: str,
    artifact_name: str,
    artifact_path: Optional[str] = None,
    project_id: Optional[str] = None,
    scenario_id: Optional[str] = None,
    governance_state: Optional[dict[str, Any]] = None,
    runtime_snapshot_id: Optional[str] = None,
    replay_metadata: Optional[dict[str, Any]] = None,
) -> ScenarioExportRecord:
    export_id = uuid.uuid4().hex[:16]
    created_at = _now_utc()
    governance_state = governance_state or {}
    replay_metadata = dict(replay_metadata or {})
    replay_metadata.setdefault("project_id", project_id)
    replay_metadata.setdefault("scenario_id", scenario_id)
    replay_metadata.setdefault("export_id", export_id)
    replay_metadata.setdefault("runtime_snapshot_id", runtime_snapshot_id)
    replay_metadata.setdefault("export_timestamp", created_at.isoformat())

    with get_cursor() as cur:
        cur.execute(
            """
            INSERT INTO scenario_exports (
                export_id, scenario_id, project_id, user_id, export_type, artifact_name,
                artifact_path, project_code, governance_state_json, runtime_snapshot_id, replay_metadata_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                export_id,
                scenario_id,
                project_id,
                user_id,
                export_type,
                artifact_name,
                artifact_path,
                project_code,
                _to_json(governance_state),
                runtime_snapshot_id,
                _to_json(replay_metadata),
                created_at.isoformat(),
            ),
        )

    return ScenarioExportRecord(
        export_id=export_id,
        scenario_id=scenario_id,
        project_id=project_id,
        user_id=user_id,
        export_type=export_type,
        artifact_name=artifact_name,
        artifact_path=artifact_path,
        project_code=project_code,
        governance_state=governance_state,
        runtime_snapshot_id=runtime_snapshot_id,
        replay_metadata=replay_metadata,
        created_at=created_at,
    )


def list_exports(
    user_id: str,
    project_id: Optional[str] = None,
    scenario_id: Optional[str] = None,
    limit: int = 20,
) -> list[ScenarioExportRecord]:
    query = "SELECT * FROM scenario_exports WHERE user_id=?"
    params: list[Any] = [user_id]
    if project_id:
        query += " AND project_id=?"
        params.append(project_id)
    if scenario_id:
        query += " AND scenario_id=?"
        params.append(scenario_id)
    query += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)

    with get_cursor() as cur:
        cur.execute(query, tuple(params))
        return [ScenarioExportRecord.from_row(row) for row in cur.fetchall()]


def get_scenario_history(
    user_id: str,
    project_id: Optional[str] = None,
    limit: int = 40,
) -> list["ScenarioRecord"]:
    """Return saved-scenario history including archived items."""
    # Imported lazily to avoid circular import (list_scenarios is in repository.py)
    from app.persistence.repository import list_scenarios
    return list_scenarios(
        user_id=user_id,
        project_id=project_id,
        include_archived=True,
        limit=limit,
    )


def compare_scenarios(
    user_id: str,
    left_scenario_id: str,
    right_scenario_id: str,
) -> Optional[dict[str, Any]]:
    """Build a lightweight comparison matrix for two saved scenarios."""
    # Imported lazily to avoid circular import
    from app.persistence.repository import get_scenario
    left = get_scenario(left_scenario_id, user_id)
    right = get_scenario(right_scenario_id, user_id)
    if left is None or right is None:
        return None

    # _metric_value and _safe_number are in _helpers
    from app.persistence._helpers import _metric_value, _safe_number

    metrics = []
    for metric in [
        "Revenue",
        "OPEX",
        "EBITDA",
        "Senior Debt",
        "SHL",
        "DSCR",
        "Project IRR",
        "Equity IRR",
        "CAPEX",
        "Distributions",
    ]:
        left_value = _metric_value(left, metric)
        right_value = _metric_value(right, metric)
        left_num = _safe_number(left_value)
        right_num = _safe_number(right_value)
        delta = None if left_num is None or right_num is None else right_num - left_num
        metrics.append(
            {
                "metric": metric,
                "left_value": left_value,
                "right_value": right_value,
                "delta": delta,
            }
        )

    governance_rows = [
        {
            "label": "G20",
            "left_value": left.governance_state.get("g20_status", "BLOCKED"),
            "right_value": right.governance_state.get("g20_status", "BLOCKED"),
        },
        {
            "label": "R99/R102",
            "left_value": left.governance_state.get("r99_r102_status", "NOT APPROVED"),
            "right_value": right.governance_state.get("r99_r102_status", "NOT APPROVED"),
        },
    ]

    return {
        "left": left,
        "right": right,
        "metrics": metrics,
        "governance_rows": governance_rows,
    }


# Phase 25B-2 — Multi-scenario compare (2-4 scenarios)
MULTI_COMPARE_MIN_SCENARIOS = 2
MULTI_COMPARE_MAX_SCENARIOS = 4
MULTI_COMPARE_METRIC_ORDER = [
    "Revenue",
    "OPEX",
    "EBITDA",
    "CFADS",
    "CAPEX",
    "Senior Debt",
    "SHL",
    "Min DSCR",
    "Avg DSCR",
    "Project IRR",
    "Equity IRR",
    "Distributions",
]
MULTI_COMPARE_METRIC_LABELS = {
    "Revenue": "Revenue (kEUR)",
    "OPEX": "OPEX (kEUR)",
    "EBITDA": "EBITDA (kEUR)",
    "CFADS": "CFADS (kEUR)",
    "CAPEX": "CAPEX (kEUR)",
    "Senior Debt": "Senior Debt (kEUR)",
    "SHL": "SHL Balance (kEUR)",
    "Min DSCR": "Min DSCR",
    "Avg DSCR": "Avg DSCR",
    "DSCR": "Avg DSCR",
    "Project IRR": "Project IRR",
    "Equity IRR": "Equity IRR",
    "Distributions": "Distributions (kEUR)",
}
# Metrics where a higher delta vs Base is favourable (green)
MULTI_COMPARE_HIGHER_IS_BETTER: set[str] = {
    "Revenue", "EBITDA", "CFADS", "Min DSCR", "Avg DSCR", "DSCR",
    "Project IRR", "Equity IRR", "Distributions",
}
# Metrics where a lower delta vs Base is favourable (green)
MULTI_COMPARE_LOWER_IS_BETTER: set[str] = {
    "OPEX", "CAPEX", "Senior Debt", "SHL",
}


def compare_multi_scenarios(
    user_id: str,
    scenario_ids: list[str],
) -> Optional[dict[str, Any]]:
    """Build a comparison matrix for 2-4 saved scenarios.

    Phase 25B-2 (Multi-Scenario Compare). The first scenario in
    ``scenario_ids`` is treated as the base reference for deltas.

    Returns a dict with:
      - scenarios: list[ScenarioRecord] (in input order)
      - metrics: list[dict] (per metric: values[] + deltas[] + sign_classes[])
      - governance_rows: list[dict] (G20 + R99/R102 per scenario)

    Returns None if:
      - fewer than MULTI_COMPARE_MIN_SCENARIOS (2) scenarios
      - more than MULTI_COMPARE_MAX_SCENARIOS (4) scenarios
      - any of the scenario_ids cannot be resolved for the user
      - duplicate scenario_ids in the input

    Pure read-only: no persistence side effects, no model execution.
    """
    # Validate input shape
    if not isinstance(scenario_ids, list):
        return None
    if len(scenario_ids) < MULTI_COMPARE_MIN_SCENARIOS:
        return None
    if len(scenario_ids) > MULTI_COMPARE_MAX_SCENARIOS:
        return None
    # Reject duplicates (defensive)
    if len(set(scenario_ids)) != len(scenario_ids):
        return None

    from app.persistence.repository import get_scenario
    from app.persistence._helpers import _metric_value, _safe_number

    records: list[Any] = []
    for sid in scenario_ids:
        rec = get_scenario(sid, user_id)
        if rec is None:
            return None
        records.append(rec)

    base_record = records[0]

    metrics: list[dict[str, Any]] = []
    for metric_key in MULTI_COMPARE_METRIC_ORDER:
        values: list[Any] = []
        deltas: list[Optional[float]] = []
        sign_classes: list[str] = []
        for rec in records:
            raw = _metric_value(rec, metric_key)
            values.append(raw)
            num = _safe_number(raw)
            if num is None or _safe_number(_metric_value(base_record, metric_key)) is None:
                deltas.append(None)
                sign_classes.append("scm-delta--na")
            else:
                base_num = _safe_number(_metric_value(base_record, metric_key))
                delta = num - base_num
                deltas.append(delta)
                if delta == 0:
                    sign_classes.append("scm-delta--zero")
                elif metric_key in MULTI_COMPARE_HIGHER_IS_BETTER:
                    sign_classes.append("scm-delta--good" if delta > 0 else "scm-delta--bad")
                elif metric_key in MULTI_COMPARE_LOWER_IS_BETTER:
                    sign_classes.append("scm-delta--good" if delta < 0 else "scm-delta--bad")
                else:
                    sign_classes.append("scm-delta--pos" if delta > 0 else "scm-delta--neg")
        metrics.append(
            {
                "metric": metric_key,
                "label": MULTI_COMPARE_METRIC_LABELS.get(metric_key, metric_key),
                "values": values,
                "deltas": deltas,
                "sign_classes": sign_classes,
            }
        )

    governance_rows: list[dict[str, Any]] = []
    for gov_key, default_val in (
        ("g20_status", "BLOCKED"),
        ("r99_r102_status", "NOT APPROVED"),
    ):
        values: list[str] = []
        for rec in records:
            values.append(rec.governance_state.get(gov_key, default_val))
        governance_rows.append({"label": gov_key, "values": values})

    return {
        "scenarios": records,
        "base_scenario_id": base_record.scenario_id,
        "metrics": metrics,
        "governance_rows": governance_rows,
    }


# ── V4-2 Part B — Input Difference Viewer ───────────────────────────────

_INPUT_FIELD_META: list[tuple[str, str, str]] = [
    # (snapshot_key, section, label)
    ("project_name", "Project", "Project Name"),
    ("project_type", "Project", "Project Type"),
    ("country_market", "Project", "Country / Market"),
    ("cod_date", "Project", "COD Date"),
    ("construction_months", "Project", "Construction Months"),
    ("horizon_years", "Project", "Horizon Years"),
    ("capacity_mw", "Technical", "Capacity (MW)"),
    ("p50_hours", "Technical", "P50 Hours"),
    ("total_capex_keur", "CAPEX", "Total CAPEX (kEUR)"),
    ("opex_y1_keur", "OPEX", "OPEX Y1 (kEUR)"),
    ("tariff_eur_mwh", "Revenue", "Tariff (EUR/MWh)"),
    ("ppa_term_years", "Revenue", "PPA Term (yrs)"),
    ("gearing_pct", "Financing", "Gearing (%)"),
    ("interest_rate_pct", "Financing", "Interest Rate"),
    ("tenor_years", "Financing", "Tenor (yrs)"),
    ("target_dscr", "Financing", "Target DSCR"),
]


def diff_scenario_inputs(
    user_id: str,
    base_scenario_id: str,
    other_scenario_id: str,
) -> Optional[dict[str, Any]]:
    """Return input-level differences between two saved scenarios.

    V4-2 Part B. Pure read-only, no model execution.
    Diffs the ``snapshot`` flat dicts of base vs other scenario.

    Returns a dict with:
      - base: ScenarioRecord
      - other: ScenarioRecord
      - rows: list[dict] — each row has section, field, base_val, other_val, changed (bool), delta_str
    """
    from app.persistence.repository import get_scenario

    base = get_scenario(base_scenario_id, user_id)
    other = get_scenario(other_scenario_id, user_id)
    if base is None or other is None:
        return None

    base_snap = base.snapshot or {}
    other_snap = other.snapshot or {}

    rows: list[dict[str, Any]] = []
    for key, section, label in _INPUT_FIELD_META:
        bv = base_snap.get(key, "")
        ov = other_snap.get(key, "")
        changed = str(bv) != str(ov)
        # Compute numeric delta when possible
        delta_str = ""
        if changed:
            try:
                b_num = float(bv) if bv not in ("", None) else None
                o_num = float(ov) if ov not in ("", None) else None
                if b_num is not None and o_num is not None:
                    delta = o_num - b_num
                    delta_str = f"{delta:+.4g}"
            except (ValueError, TypeError):
                pass
        rows.append({
            "section": section,
            "field": label,
            "base_val": bv or "—",
            "other_val": ov or "—",
            "changed": changed,
            "delta_str": delta_str,
        })

    return {
        "base": base,
        "other": other,
        "rows": rows,
        "changed_count": sum(1 for r in rows if r["changed"]),
    }


def build_export_lineage(
    user_id: str,
    project_id: Optional[str] = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Return export history with scenario lineage context."""
    exports = list_exports(user_id=user_id, project_id=project_id, limit=limit)
    # Imported lazily to avoid circular import
    from app.persistence.repository import get_scenario
    lineage = []
    for item in exports:
        scenario = get_scenario(item.scenario_id, user_id) if item.scenario_id else None
        lineage.append(
            {
                "export_id": item.export_id,
                "artifact_name": item.artifact_name,
                "export_type": item.export_type,
                "project_code": item.project_code,
                "scenario_name": scenario.scenario_name if scenario else "Workspace export",
                "copied_from_scenario_id": scenario.copied_from_scenario_id if scenario else None,
                "created_at": item.created_at,
                "governance_state": item.governance_state,
                "replay_metadata": item.replay_metadata,
            }
        )
    return lineage


def base_vs_active_compare(user_id: str, project_id: str) -> Optional[dict[str, Any]]:
    """Pre-compute Base Case vs Active Scenario comparison for the Compare workspace tab.

    Returns a dict with 'base' and 'active' ScenarioRecords (or None), plus
    computed metrics/deltas when both are available, and an 'empty_state' string
    when only partial context is available.
    """
    # Imported lazily to avoid circular import
    from app.persistence.repository import (
        get_workspace_state,
        seed_scenarios_if_needed,
        get_base_case_scenario,
        get_scenario,
    )
    # Get workspace state to find the active scenario
    ws = get_workspace_state(user_id, project_id)
    active_scenario_id = ws.active_scenario_id if ws else None

    # Ensure base case exists
    seed_scenarios_if_needed(
        user_id=user_id,
        project_id=project_id,
        project_code=ws.project_code if ws else "",
        project_type="solar",
        source_project_template=ws.saved_snapshot.get("template_source", "") if ws and ws.saved_snapshot else "",
        baseline_snapshot=ws.saved_snapshot if ws and ws.saved_snapshot else {},
        governance_state={},
        template_origin="workspace",
    )
    base_scenario = get_base_case_scenario(user_id, project_id)

    if base_scenario is None:
        return None

    result = {"base": base_scenario, "active": None}

    if not active_scenario_id:
        result["empty_state"] = "No active scenario selected — select a saved scenario to compare against Base Case."
        return result

    active = get_scenario(active_scenario_id, user_id)
    if active is None:
        result["empty_state"] = "Active scenario not found."
        return result

    result["active"] = active

    # Build metrics for both
    base_metrics = _build_compare_metrics(base_scenario)
    active_metrics = _build_compare_metrics(active)

    # Compute deltas
    metrics = []
    for key in base_metrics:
        b_val = base_metrics[key]
        a_val = active_metrics.get(key)
        delta = None
        sign_class = "delta-neutral"
        if b_val is not None and a_val is not None:
            delta = a_val - b_val
            if delta > 0:
                sign_class = "delta-positive"
            elif delta < 0:
                sign_class = "delta-negative"
            else:
                sign_class = "delta-neutral"
        metrics.append({
            "key": key,
            "base_value": b_val,
            "active_value": a_val,
            "delta": delta,
            "sign_class": sign_class,
        })

    result["metrics"] = metrics
    return result


def _scenario_runtime_dict(record: "ScenarioRecord") -> dict[str, Any]:
    """Build a runtime provenance dict from a ScenarioRecord for display in Compare tab provenance cards."""
    snapshot = record.snapshot or {}
    last_run = record.last_run_summary or {}
    replay = record.replay_metadata or {}
    overrides = record.overrides or {}
    return {
        "scenario_id": record.scenario_id,
        "scenario_name": record.scenario_name,
        "is_base_case": record.is_base_case,
        "last_run_summary": last_run,
        "total_revenue_keur": last_run.get("total_revenue_keur"),
        "total_opex_keur": last_run.get("total_opex_keur"),
        "total_ebitda_keur": last_run.get("total_ebitda_keur"),
        "senior_debt_keur": last_run.get("senior_debt_keur"),
        "shl_balance_keur": last_run.get("shl_balance_keur"),
        "project_irr": last_run.get("project_irr"),
        "equity_irr": last_run.get("equity_irr"),
        "avg_dscr": last_run.get("avg_dscr"),
        "min_dscr": last_run.get("min_dscr"),
        "total_capex_keur": float(snapshot.get("total_capex_keur", 0) or 0),
        "replay_metadata": replay,
        "runtime_origin": replay.get("runtime_origin", "workspace"),
        "runtime_timestamp": replay.get("runtime_timestamp"),
        "run_id": replay.get("run_id"),
        "override_field_count": len(overrides),
        "override_field_list": sorted(overrides.keys()),
    }


def _build_compare_metrics(record: "ScenarioRecord") -> dict[str, Optional[float]]:
    """Build a flat metrics dict from a ScenarioRecord for scenario comparison."""
    from app.persistence._helpers import _safe_number
    last_run = record.last_run_summary or {}
    snapshot = record.snapshot or {}
    return {
        "total_revenue_keur": _safe_number(last_run.get("total_revenue_keur")),
        "total_opex_keur": _safe_number(last_run.get("total_opex_keur")),
        "total_ebitda_keur": _safe_number(last_run.get("total_ebitda_keur")),
        "senior_debt_keur": _safe_number(last_run.get("senior_debt_keur")),
        "shl_balance_keur": _safe_number(last_run.get("shl_balance_keur")),
        "project_irr": _safe_number(last_run.get("project_irr")),
        "equity_irr": _safe_number(last_run.get("equity_irr")),
        "avg_dscr": _safe_number(last_run.get("avg_dscr")),
        "min_dscr": _safe_number(last_run.get("min_dscr")),
        "total_capex_keur": _safe_number(snapshot.get("total_capex_keur")),
    }


def _delta_sign_class(delta: Optional[float]) -> str:
    """Return Bootstrap color class for a delta value."""
    if delta is None:
        return "delta-neutral"
    if delta > 0:
        return "delta-positive"
    if delta < 0:
        return "delta-negative"
    return "delta-neutral"


def _format_db_timestamp(value: Any) -> str:
    """Format a timestamp from the DB (datetime or ISO string) for display."""
    if value is None:
        return "—"
    if hasattr(value, "strftime"):
        return value.strftime("%d %b %Y %H:%M")
    # Already a string
    try:
        from datetime import datetime
        dt = datetime.fromisoformat(str(value))
        return dt.strftime("%d %b %Y %H:%M")
    except Exception:
        return str(value)
