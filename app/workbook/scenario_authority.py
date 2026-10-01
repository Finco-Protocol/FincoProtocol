"""Single active-scenario override resolution for every presentation surface.

CAPEX sheet, OPEX sheet and Inputs Summary must read the active scenario's
overrides exactly as Run does (same scenario row, same project/archive guards).
A failure is returned as an explicit error string, never silently treated as
"no override" by callers that display economics.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


def resolve_active_scenario_overrides(
    project_record: Any, ws: Any, workspace_owner: str = "",
) -> tuple[Optional[dict], str]:
    """Return ``(overrides_or_None, error_message)`` for the active scenario."""
    if ws is None or not getattr(ws, "active_scenario_id", None):
        return None, ""
    owner = (
        getattr(ws, "user_id", None) or workspace_owner or project_record.project_code
    )
    scenario_id = ws.active_scenario_id
    try:
        from app.persistence.scenarios_repository import get_scenario

        rec = get_scenario(scenario_id=scenario_id, user_id=owner)
        if rec is None:
            return None, (
                f"Active scenario could not be found (id={scenario_id!r}). "
                "Re-select a scenario to see scenario economics."
            )
        if rec.archived:
            return None, (
                "Active scenario has been archived. "
                "Re-select a scenario to see scenario economics."
            )
        if rec.project_id != project_record.project_id:
            logger.warning(
                "scenario project_id mismatch scenario=%s scenario.project_id=%s expected=%s",
                scenario_id, rec.project_id, project_record.project_id,
            )
            return None, (
                "Active scenario does not belong to this project. "
                "Re-select a scenario to see scenario economics."
            )
        return rec.overrides, ""
    except Exception:
        logger.exception("scenario repository lookup failed scenario=%s", scenario_id)
        return None, (
            "Scenario data could not be loaded. "
            "Re-select a scenario or reload the page."
        )
