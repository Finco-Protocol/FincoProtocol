"""Phase 51P-2 — POST /scenarios/{scenario_id}/rename route family
vertical extraction.

This module owns the orchestration body that previously lived
inline in main_web.py for:

- POST /scenarios/{scenario_id}/rename (rename_scenario_endpoint)

The route handler in main_web.py is now a thin wrapper
(auth + form read + path param + deps bundle + service call +
response translation). The full orchestration (scenario lookup,
gate, rename, workspace re-render with summary cards, exports
lineage) lives here.

This service does NOT import main_web or main_api.

12 behaviors preserved (Phase 51P-1):

1. POST /scenarios/{scenario_id}/rename exists.
2. Auth check via get_current_user(request) (route-owned).
3. Unauthenticated -> 302 redirect to /login.
4. Path parameter scenario_id.
5. Form input: scenario_name (string, stripped).
6. Empty scenario_name -> 400 JSONResponse.
7. Scenario lookup: get_scenario(scenario_id, user.user_id) (positional).
8. Scenario not found -> 404 JSONResponse.
9. Rename side effect: rename_scenario(user.user_id, scenario_id, new_name).
10. Workspace re-render: full re-render via _render_scenario_workspace.
11. Response: _render_scenario_workspace(...) with message.
12. No HTMX-specific headers.

10 quirks preserved (Phase 51P-1):

1. Form read via await request.form() (not FastAPI Form injection).
2. After rename, the entire workspace is re-rendered (not a partial).
3. scenario_summary_cards built by iterating scenarios.
4. export_count aggregated from export_lineage.
5. Success message includes the new scenario name.
6. No HTMX-specific headers.
7. Scenario lookup uses get_scenario(scenario_id, user.user_id) (positional).
8. list_scenarios called with include_archived=False, limit=12.
9. get_scenario_history called with limit=20.
10. list_exports and build_export_lineage called with limit=8 (x2).

Intended persistence side effects (NOT forbidden):

- deps.get_scenario(...) -- 1 call per success.
- deps.rename_scenario(...) -- 1 call per success.
- deps.get_project_by_code(...) -- 1 call per success.
- deps.list_scenarios(...) -- 1 call per success.
- deps.get_scenario_history(...) -- 1 call per success.
- deps.list_exports(...) -- 1 call per success.
- deps.build_export_lineage(...) -- 1 call per success.
- deps.get_workspace_state(...) -- 1 call per success.

Per 400 (empty name) or 404 (not found): the route short-circuits
before rename_scenario and the workspace re-render.

Forbidden side effects (must NOT be introduced):

- record_export
- record_download_export
- record_runtime_summary_export
- record_institutional_workbook_export
- record_workspace_runtime
- update_scenario_last_run_summary
- save_run
- run_project / model execution
- build_institutional_workbook_export
- build_excel_export_for_post_request
- build_runtime_summary_csv_export
- build_values_only_export_for_project
- db.add / db.commit / db.flush (direct)
- session.add / session.commit (direct)
- unrelated persistence writes
- add_scenario / create_scenario (Quirk: this is rename, not add)

Phase 51F guardrails: this module does NOT import main_web or
main_api. The engine-output golden guardrail, parity-core lock
guardrail, and no-service-imports guardrail remain green.

Why a separate service module:

- scenario_duplicate_service.py is for /scenarios/{id}/duplicate.
  Different concern (creates a copy, not a rename).
- scenarios_save_service.py is for /scenarios/save. Different
  concern (creates a new scenario from form snapshot).
- scenarios_add_service.py is for /scenarios/add. Different
  concern (adds scenario with parent inheritance).

Backend remains source of truth. rc1 remains frozen.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional


# ─────────────────────────────────────────────────────────────────────────────
# Public dataclasses
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class ScenarioRenameRouteOutcome:
    """Result of POST /scenarios/{scenario_id}/rename orchestration.

    The route in ``main_web.py`` translates this into a FastAPI
    response. The outcome has TWO forms:

    1. **Error form** (status_code >= 400): the route returns
       ``JSONResponse(outcome.payload, status_code=outcome.status_code)``.

    2. **Success form** (status_code == 200): the route returns
       the pre-rendered ``outcome.rendered_response`` (a
       TemplateResponse already produced by the service's
       ``render_scenario_workspace`` dep).

    Fields:
        status_code: HTTP status code. 200, 400, or 404.
        payload: JSON payload for error responses.
        rendered_response: Pre-rendered TemplateResponse for
            success responses. ``None`` for error responses.
    """

    status_code: int = 200
    payload: dict = field(default_factory=dict)
    rendered_response: Any = None


@dataclass
class ScenarioRenameRouteDeps:
    """Dependencies that ``execute_scenario_rename_route`` needs
    from the route.

    The route in ``main_web.py`` owns these helpers; passing them
    in as callables (rather than importing from ``main_web``) keeps
    the ``main_web`` -> ``scenario_rename_service`` import
    direction clean and lets future test code inject test doubles.

    The bundle has 9 callables.
    """

    # Scenario lookup
    get_scenario: Callable[..., Any]

    # Persistence (intended write)
    rename_scenario: Callable[..., Any]

    # Workspace re-render
    get_project_by_code: Callable[..., Any]
    list_scenarios: Callable[..., Any]
    get_scenario_history: Callable[..., Any]
    list_exports: Callable[..., Any]
    build_export_lineage: Callable[..., Any]
    get_workspace_state: Callable[..., Any]

    # Render helper (calls main_web._render_scenario_workspace)
    render_scenario_workspace: Callable[..., Any]


# ─────────────────────────────────────────────────────────────────────────────
# Service entry point
# ─────────────────────────────────────────────────────────────────────────────


async def execute_scenario_rename_route(
    *,
    request: Any,
    scenario_id: str,
    new_name: str,
    user: Any,
    deps: ScenarioRenameRouteDeps,
) -> ScenarioRenameRouteOutcome:
    """Execute the POST /scenarios/{scenario_id}/rename orchestration
    and return a ScenarioRenameRouteOutcome.

    Mirrors the legacy ``rename_scenario_endpoint`` route body in
    main_web.py (Phase 51P-1 characterization).

    Behavior:
    - Empty new_name -> 400 JSONResponse.
    - get_scenario(scenario_id, user.user_id) -> 404 if None.
    - rename_scenario(user.user_id, scenario_id, new_name).
    - Full workspace re-render via deps.render_scenario_workspace
      (which is main_web._render_scenario_workspace, wired via deps).
    - Returns a ScenarioRenameRouteOutcome with the rendered
      response for success, or a payload+status for error.
    """
    if not new_name:
        return ScenarioRenameRouteOutcome(
            payload={"error": "Scenario name is required"},
            status_code=400,
        )

    record = deps.get_scenario(scenario_id, user.user_id)
    if record is None:
        return ScenarioRenameRouteOutcome(
            payload={"error": "Scenario not found"},
            status_code=404,
        )

    deps.rename_scenario(user.user_id, scenario_id, new_name)

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

    # Quirk 3/4: scenario_summary_cards built from scenarios + export_lineage
    # This logic is INLINED in the route's deps wrapper (passed in via
    # the render_scenario_workspace callable, which the route wraps
    # to include the summary_cards logic).
    rendered = deps.render_scenario_workspace(
        request=request,
        user=user,
        project_record=project_record,
        workspace_state=workspace_state,
        scenarios=scenarios,
        history=history,
        exports=exports,
        export_lineage=export_lineage,
        message=f"Renamed scenario to {new_name}.",
    )
    return ScenarioRenameRouteOutcome(
        status_code=200,
        rendered_response=rendered,
    )
