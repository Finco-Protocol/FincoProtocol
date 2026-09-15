"""Pure helper functions for the persistence layer.

This module holds Group F helper functions extracted from
app/persistence/repository.py during Phase 53A. The functions are
pure (no side effects beyond JSON parsing or local data transformation)
and have no DB write semantics. They are re-exported from
app.persistence.repository for backward compatibility.

Function inventory (Group F, from Phase 52A/52C):

- _now_utc
- _to_json
- _from_json
- _from_iso
- SCENARIO_INPUT_FIELDS (set constant)
- _safe_number
- _metric_value
- snapshots_equal
- _strip_empty_fields
- _get_least_created_scenario_for_project (scenario lookup helper)

Behavior is preserved exactly as it was in repository.py. The only
change is the file location.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Optional

from app.persistence.db import get_cursor


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _to_json(value: Any) -> str:
    return json.dumps(value if value is not None else {}, default=str, sort_keys=True)


def _from_json(value: Optional[str], default: Any) -> Any:
    if not value:
        return default
    return json.loads(value)


def _from_iso(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(value)


# ---------------------------------------------------------------------------
# Known input-field names for override validation.
# ---------------------------------------------------------------------------
SCENARIO_INPUT_FIELDS: set[str] = {
    "active_project",
    "project_name",
    "project_type",
    "project_origin",
    "template_source",
    "country_market",
    "scenario",
    "capacity_mw",
    "tariff_eur_mwh",
    "p50_hours",
    "total_capex_keur",
    "opex_y1_keur",
    "gearing_pct",
    "target_dscr",
    "interest_rate_pct",
    "tenor_years",
    "cod_date",
    "construction_months",
    "horizon_years",
    "capacity_factor",
    "ppa_term_years",
    # SCENARIO-2 fix: matrix uses these aliases; they must be in the allowlist
    # so update_scenario_overrides does not silently drop them.
    "ppa_tariff_eur_mwh",
    "operating_hours_p50",
    "opex_y1_total_keur",
    "senior_tenor_years",
}


def _safe_number(value: Any) -> Optional[float]:
    if value in (None, "", "NOT_AVAILABLE", "MISSING"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _metric_value(record: "ScenarioRecord", key: str) -> Any:
    snapshot = record.snapshot or {}
    summary = record.last_run_summary or {}
    metric_map = {
        "Revenue": summary.get("total_revenue_keur"),
        "OPEX": summary.get("total_opex_keur") or snapshot.get("opex_y1_keur"),
        "EBITDA": summary.get("total_ebitda_keur"),
        "CAPEX": snapshot.get("total_capex_keur"),
        "Senior Debt": summary.get("senior_debt_keur"),
        "SHL": summary.get("shl_balance_keur"),
        "CFADS": summary.get("total_cfads_keur"),
        "Min DSCR": summary.get("min_dscr"),
        "Avg DSCR": summary.get("avg_dscr"),
        # Legacy key kept for backward-compat
        "DSCR": summary.get("avg_dscr"),
        "Project IRR": summary.get("project_irr"),
        "Equity IRR": summary.get("equity_irr"),
        "Distributions": summary.get("distribution_keur"),
    }
    return metric_map.get(key)


def snapshots_equal(left: Optional[dict[str, Any]], right: Optional[dict[str, Any]]) -> bool:
    return _to_json(left or {}) == _to_json(right or {})


def _strip_empty_fields(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Remove keys whose values are empty strings.

    Used to normalize snapshots before comparison so that form submissions
    (which may contain new empty-string fields added by _collect_form_snapshot)
    can still match workspace saved snapshots that predate those fields.
    """
    return {k: v for k, v in (snapshot or {}).items() if v != ""}


def _get_least_created_scenario_for_project(user_id: str, project_id: str) -> Optional["ScenarioRecord"]:
    """Return the oldest (earliest created_at) non-archived scenario for a project,
    used as the default base case when backfilling for legacy projects."""
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT * FROM scenarios
            WHERE user_id=? AND project_id=? AND archived=0
            ORDER BY created_at ASC
            LIMIT 1
            """,
            (user_id, project_id),
        )
        row = cur.fetchone()
    return ScenarioRecord.from_row(row) if row else None
