"""Phase 51Q-2 — POST /scenarios/{scenario_id}/archive route family
vertical extraction.

This module owns the orchestration body that previously lived
inline in main_web.py for:

- POST /scenarios/{scenario_id}/archive (archive_scenario_endpoint)

The route handler in main_web.py is now a thin wrapper
(auth + path param + deps bundle + service call + response
translation). The full orchestration (scenario lookup, soft-archive,
workspace re-render) lives here.

This service does NOT import main_web or main_api.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional


@dataclass
class ScenarioArchiveRouteOutcome:
    """Result of POST /scenarios/{scenario_id}/archive orchestration.

    Two forms:
    - Error (status_code >= 400): JSONResponse(payload, status_code)
    - Success (status_code == 200): outcome.rendered_response
    """
    status_code: int = 200
    payload: dict = field(default_factory=dict)
    rendered_response: Any = None


@dataclass
class ScenarioArchiveRouteDeps:
    """Dependencies that ``execute_scenario_archive_route`` needs
    from the route.

    The bundle has 9 callables.
    """
    # Scenario lookup
    get_scenario: Callable[..., Any]
    # Persistence (intended write)
    archive_scenario: Callable[..., Any]
    # Workspace re-render
    get_project_by_code: Callable[..., Any]
    list_scenarios: Callable[..., Any]
    get_scenario_history: Callable[..., Any]
    list_exports: Callable[..., Any]
    build_export_lineage: Callable[..., Any]
    get_workspace_state: Callable[..., Any]
    # Render helper
    render_scenario_workspace: Callable[..., Any]


async def execute_scenario_archive_route(
    *,
    request: Any,
    scenario_id: str,
    user: Any,
    deps: ScenarioArchiveRouteDeps,
) -> ScenarioArchiveRouteOutcome:
    """Execute the POST /scenarios/{scenario_id}/archive orchestration
    and return a ScenarioArchiveRouteOutcome.

    Mirrors the legacy ``archive_scenario_endpoint`` route body in
    main_web.py (Phase 51Q-1 characterization).

    Behavior:
    - get_scenario(scenario_id, user.user_id) -> 404 if None.
    - archive_scenario(user.user_id, scenario_id) (no third arg).
    - Full workspace re-render via deps.render_scenario_workspace.
    """
    record = deps.get_scenario(scenario_id, user.user_id)
    if record is None:
        return ScenarioArchiveRouteOutcome(
            payload={"error": "Scenario not found"},
            status_code=404,
        )

    deps.archive_scenario(user.user_id, scenario_id)

    # Workspace re-render (Quirk 2: full re-render, not partial)
    project_record = deps.get_project_by_code(user.user_id, record.project_code)
    scenarios = deps.list_scenarios(
        user.user_id, project_id=record.project_id, include_archived=False, limit=12
    )
    history = deps.get_scenario_history(
        user.user_id, project_id=record.project_id, limit=20
    )
    exports = deps.list_exports(
        user.user_id, project_id=record.project_id, limit=8
    )
    export_lineage = deps.build_export_lineage(
        user.user_id, project_id=record.project_id, limit=8
    )
    workspace_state = deps.get_workspace_state(user.user_id, record.project_id)

    rendered = deps.render_scenario_workspace(
        request=request,
        user=user,
        project_record=project_record,
        workspace_state=workspace_state,
        scenarios=scenarios,
        history=history,
        exports=exports,
        export_lineage=export_lineage,
        message=f"Archived {record.scenario_name}.",
    )
    return ScenarioArchiveRouteOutcome(
        status_code=200,
        rendered_response=rendered,
    )
