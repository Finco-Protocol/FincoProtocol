"""Phase 51S-2 — POST /scenarios/{scenario_id}/select route family
vertical extraction.

This module owns the orchestration body that previously lived
inline in main_web.py for:

- POST /scenarios/{scenario_id}/select (select_scenario_endpoint)

The route handler in main_web.py is now a thin wrapper
(auth + path param + deps bundle + service call + response
translation). The full orchestration (scenario lookup, gate,
select_scenario write, partial template re-render with HX-Trigger
JSON payload) lives here.

This service does NOT import main_web or main_api.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional


@dataclass
class ScenarioSelectRouteOutcome:
    """Result of POST /scenarios/{scenario_id}/select orchestration.

    Two forms:
    - Error (status_code >= 400): JSONResponse(payload, status_code)
    - Success (status_code == 200): template_name + context + headers
    """
    template_name: str = "partials/scenario_tab.html"
    context: dict = field(default_factory=dict)
    payload: dict = field(default_factory=dict)
    status_code: int = 200
    headers: dict = field(default_factory=dict)
    rendered_response: Any = None


@dataclass
class ScenarioSelectRouteDeps:
    """Dependencies that ``execute_scenario_select_route`` needs
    from the route.

    The bundle has 6 callables.
    """
    # Scenario lookup
    get_scenario: Callable[..., Any]
    # Persistence (intended write)
    select_scenario: Callable[..., Any]
    # Workspace state for re-render
    get_workspace_state: Callable[..., Any]
    get_project_record: Callable[..., Any]
    list_scenarios: Callable[..., Any]
    # Render helper
    build_scenario_tab_context: Callable[..., dict]


async def execute_scenario_select_route(
    *,
    request: Any,
    scenario_id: str,
    user: Any,
    deps: ScenarioSelectRouteDeps,
) -> ScenarioSelectRouteOutcome:
    """Execute the POST /scenarios/{scenario_id}/select
    orchestration and return a ScenarioSelectRouteOutcome.

    Mirrors the legacy ``select_scenario_endpoint`` route body in
    main_web.py (Phase 51S-1 characterization).
    """
    record = deps.get_scenario(scenario_id, user.user_id)
    if record is None:
        return ScenarioSelectRouteOutcome(
            payload={"error": "Scenario not found"},
            status_code=404,
        )

    ok = deps.select_scenario(user.user_id, record.project_id, scenario_id)
    if not ok:
        return ScenarioSelectRouteOutcome(
            payload={"error": "Failed to select scenario"},
            status_code=500,
        )

    # Workspace re-render (Quirk 4: partial template, NOT full workspace)
    ws = deps.get_workspace_state(user.user_id, record.project_id)
    project_record = deps.get_project_record(
        user_id=user.user_id, project_code=record.project_code
    )
    scenarios = deps.list_scenarios(
        user.user_id, project_id=record.project_id, include_archived=False, limit=12
    )
    context = deps.build_scenario_tab_context(user, project_record, scenarios, ws)
    return ScenarioSelectRouteOutcome(
        template_name="partials/scenario_tab.html",
        context=context,
        status_code=200,
        headers={"HX-Trigger": f"scenarioSelected:{{\"scenario_id\": \"{scenario_id}\"}}"},
    )
