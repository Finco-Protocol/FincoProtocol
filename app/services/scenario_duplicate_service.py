"""Phase 51K-2 — POST /scenarios/{scenario_id}/duplicate route family
vertical extraction.

This module owns the orchestration body that previously lived
inline in main_web.py for:

- POST /scenarios/{scenario_id}/duplicate (duplicate_scenario_endpoint)

The route handler in main_web.py is now a thin wrapper
(auth + path parameter + deps bundle + service call + render). The
full orchestration (original scenario lookup, 404 early return,
duplicate_scenario call, project_record resolution, read-only
list_scenarios/get_scenario_history/list_exports/
build_export_lineage calls, scenario_summary_cards assembly with
export_count, workspace_state resolution, response context
assembly) lives here.

This service does NOT import main_web or main_api. The route in
main_web.py wires the deps bundle and calls
``execute_scenario_duplicate_route(...)``. The service returns a
``ScenarioDuplicateRouteOutcome`` dataclass which the route
translates to a ``TemplateResponse`` (success) or
``JSONResponse`` (404 not found) or ``RedirectResponse`` (auth).
Auth is route-owned, so the service does not produce redirects
itself.

20 characterized behaviors preserved (Phase 51K-1):

1. POST /scenarios/{scenario_id}/duplicate exists.
2. Auth check via get_current_user(request) (route-owned).
3. Unauthenticated -> 302 redirect to /login (NOT 401 JSON).
4. scenario_id is the path parameter.
5. scenario_id is passed to get_scenario(scenario_id, user.user_id).
6. scenario_id is passed to duplicate_scenario(user.user_id,
   scenario_id).
7. user_id derived from session, never from form.
8. get_scenario called once.
9. duplicate_scenario called once (after the None check).
10. If original is None -> 404 JSON {error: 'Scenario not found'}.
11. project_record resolved via
    get_project_by_code(user.user_id, original.project_code).
12. Read-only queries (list_scenarios, get_scenario_history,
    list_exports, build_export_lineage) called once each.
13. scenario_summary_cards have 10 specific fields including
    export_count (computed per scenario_name from export_lineage).
14. workspace_state resolved inline in the render call.
15. No replay_metadata passed to duplicate_scenario (Quirk 1,
    different from /scenarios/save).
16. No _governance_snapshot call (Quirk 4, different from
    /scenarios/save).
17. Success response is full workspace render via
    _render_scenario_workspace (NOT HTMX partial).
18. 404 response is JSON, not HTML, not redirect, not template.
19. No HTMX headers (no HX-Trigger, no HX-Redirect).
20. Success message is
    f'Duplicated {original.scenario_name}.'.

10 characterized quirks preserved:

1. duplicate_scenario is called WITHOUT replay_metadata
   (different from /scenarios/save which passes
   export_type='saved_scenario_snapshot'). The repository function
   is the single source of truth for the duplicate's metadata.
2. 404 response is JSON, NOT HTML, NOT redirect, NOT template
   render.
3. Success message is f'Duplicated {original.scenario_name}.' (with
   period).
4. The route does NOT call _governance_snapshot (different from
   /scenarios/save which calls it 2x per success). The repository
   function duplicate_scenario is the single source of truth.
5. workspace_state is resolved inline in the
   _render_scenario_workspace call
   (get_workspace_state(user.user_id, original.project_id)), not
   stored in a separate variable. The render call has 9
   positional args + 1 keyword arg (message=...).
6. scenario_summary_cards have 10 specific fields (same shape as
   /scenarios/save's cards).
7. scenario_summary_cards.export_count is computed by counting
   entries in export_lineage per scenario_name.
8. The route is path-parameter-only; it does NOT read form input
   (no await request.form()). Different from /scenarios/save which
   accepts any form input as snapshot.
9. The route does NOT emit HX-Trigger or HX-Redirect. The success
   response is a full workspace render.
10. The route is currently inline orchestration (no service
    pattern yet) — pre-extraction. After 51K-2 it uses
    execute_scenario_duplicate_route(...).

Intended persistence side effects (NOT forbidden):

- get_scenario(...) -- 1 call per request (read, lookup).
- duplicate_scenario(...) -- 1 call per success (write, the
  duplication).
- get_project_by_code(...) -- 1 call per success (read).
- list_scenarios(...) -- 1 call per success (read, render context).
- get_scenario_history(...) -- 1 call per success (read, render
  context).
- list_exports(...) -- 1 call per success (read, render context).
- build_export_lineage(...) -- 1 call per success (read, render
  context).
- get_workspace_state(...) -- 1 call per success (read, render
  context).

Per 404 (scenario not found): only get_scenario is called (1
call); all other persistence calls are 0. The route short-
circuits with the 404 JSON.

Forbidden side effects (must NOT be introduced):

- record_export
- record_download_export
- record_runtime_summary_export
- record_institutional_workbook_export
- record_workspace_runtime
- update_scenario_last_run_summary
- save_run
- save_project
- direct save_workspace_state call outside the
  duplicate_scenario repository function
- run_project / model execution
- build_institutional_workbook_export
- build_excel_export_for_post_request
- build_runtime_summary_csv_export
- build_values_only_export_for_project
- db.add / db.commit / db.flush (direct)
- session.add / session.commit (direct)
- unrelated persistence writes
- _validate_form (the route does not validate the form because
  it does not read form input)

Phase 51F guardrails: this module does NOT import main_web or
main_api. The engine-output golden guardrail, parity-core lock
guardrail, and no-service-imports guardrail remain green.

Why a separate service module (not extending scenario_state_service.py
or scenario_state_route_service.py or scenarios_save_service.py):

- scenario_state_service.py is data-layer only (no Request, no
  user, no auth). Adding route orchestration would mix data-
  layer and route-orchestration concerns.

- scenario_state_route_service.py handles workspace draft/discard
  mutations WITHOUT scenario row creation. /scenarios/{id}/
  duplicate calls duplicate_scenario (which creates a new
  ScenarioRecord); this is a different concern.

- scenarios_save_service.py is for /scenarios/save (creates a new
  ScenarioRecord from form snapshot). Duplicate copies an existing
  ScenarioRecord; different concern.

Backend remains source of truth. rc1 remains frozen.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional


# ─────────────────────────────────────────────────────────────────────────────
# Public dataclasses
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class ScenarioDuplicateRouteOutcome:
    """Result of POST /scenarios/{scenario_id}/duplicate orchestration.

    The route in ``main_web.py`` translates this into a FastAPI
    response via ``TemplateResponse(...)`` (success) or
    ``JSONResponse(...)`` (404 not found) or
    ``RedirectResponse(...)`` (auth). For symmetry with the
    broader Phase 51 family the outcome also carries
    ``is_redirect`` and ``redirect_url`` in case future routes
    need to redirect; auth is currently route-owned, so the
    service does not produce redirects itself.

    Fields:
        template_name: Jinja template to render (success path).
            Default ``"scenarios/_workspace_partial.html"`` (the
            partial that ``_render_scenario_workspace`` returns
            inside). The route does not need to know this — it
            just calls ``_render_scenario_workspace`` via the
            deps.
        context: Jinja context dict (success path). For success:
            the full workspace render context (request, user,
            project_record, workspace_state, scenarios, history,
            exports, export_lineage, scenario_summary_cards,
            message). The service calls
            ``deps.render_scenario_workspace(...)`` directly and
            returns the rendered response; the route does not
            need to inspect this context.
        payload: JSON payload for non-template responses (e.g.
            404 not found). The route constructs a ``JSONResponse``
            with ``content=outcome.payload`` and
            ``status_code=outcome.status_code``.
        status_code: HTTP status code. 200 for success; 404 for
            scenario not found. Other status codes are not
            produced by this service.
        headers: Extra response headers. Default empty (the
            current route does not emit HX-Trigger or
            HX-Redirect).
        is_redirect: ``True`` if the route should redirect (e.g.
            unauthenticated -> /login). Currently unused (auth is
            route-owned). Included for symmetry with Phase
            51B/51C-2/51D-2/51E-2/51G-2/51H-2/51J-2.
        redirect_url: URL to redirect to (when is_redirect is
            True). Currently unused.
    """

    template_name: str = "scenarios/_workspace_partial.html"
    context: dict = field(default_factory=dict)
    payload: dict = field(default_factory=dict)
    status_code: int = 200
    headers: dict = field(default_factory=dict)
    is_redirect: bool = False
    redirect_url: Optional[str] = None


@dataclass
class ScenarioDuplicateRouteDeps:
    """Dependencies that ``execute_scenario_duplicate_route`` needs
    from the route.

    The route in ``main_web.py`` owns these helpers; passing them
    in as callables (rather than importing from ``main_web``) keeps
    the ``main_web`` -> ``scenario_duplicate_service`` import
    direction clean and lets future test code inject test doubles.

    The bundle has 9 callables. No constants are needed because
    the route is path-parameter-only (Quirk 8) — it does not
    validate the form (it does not read form input at all).
    """

    # Original scenario lookup
    get_scenario: Callable[..., Any]

    # Persistence (intended write)
    duplicate_scenario: Callable[..., Any]

    # Project resolution
    get_project_by_code: Callable[..., Any]

    # Read-only queries for response render
    list_scenarios: Callable[..., Any]
    get_scenario_history: Callable[..., Any]
    list_exports: Callable[..., Any]
    build_export_lineage: Callable[..., Any]

    # Workspace state resolution
    get_workspace_state: Callable[..., Any]

    # Response render
    render_scenario_workspace: Callable[..., Any]


# ─────────────────────────────────────────────────────────────────────────────
# Service entry point
# ─────────────────────────────────────────────────────────────────────────────


async def execute_scenario_duplicate_route(
    *,
    request: Any,
    scenario_id: str,
    user: Any,
    deps: ScenarioDuplicateRouteDeps,
) -> ScenarioDuplicateRouteOutcome:
    """Execute the POST /scenarios/{scenario_id}/duplicate
    orchestration and return a ScenarioDuplicateRouteOutcome.

    Mirrors the legacy ``duplicate_scenario_endpoint`` route body
    in main_web.py (Phase 51K-1 characterization).

    Behavior:
    - Resolves original via
      ``deps.get_scenario(scenario_id, user.user_id)``.
    - **404 early return:** if original is None, returns
      ``ScenarioDuplicateRouteOutcome`` with
      ``status_code=404`` and
      ``payload={"error": "Scenario not found"}``. The route
      renders this as a JSONResponse.
    - Calls ``deps.duplicate_scenario(user.user_id, scenario_id)``
      ONCE (after the None check).
    - Resolves project_record via
      ``deps.get_project_by_code(user.user_id,
      original.project_code)``.
    - Calls read-only list_scenarios/get_scenario_history/
      list_exports/build_export_lineage ONCE each.
    - Assembles scenario_summary_cards with 10 specific fields
      including export_count (computed per scenario_name from
      export_lineage).
    - Resolves workspace_state via
      ``deps.get_workspace_state(user.user_id,
      original.project_id)`` (inline in the render call).
    - Returns the workspace render via
      ``deps.render_scenario_workspace(...)`` with success
      message ``f"Duplicated {original.scenario_name}."``.
    """
    # ── Original scenario lookup ────────────────────────────────────
    original = deps.get_scenario(scenario_id, user.user_id)

    # ── 404 early return (Quirk 2) ──────────────────────────────────
    if original is None:
        return ScenarioDuplicateRouteOutcome(
            status_code=404,
            payload={"error": "Scenario not found"},
        )

    # ── Persist the duplicate (Quirk 1: no replay_metadata) ─────────
    deps.duplicate_scenario(user.user_id, scenario_id)

    # ── Read-only queries for response render context ───────────────
    project_record = deps.get_project_by_code(
        user.user_id, original.project_code
    )
    scenarios = deps.list_scenarios(
        user.user_id,
        project_id=original.project_id,
        include_archived=False,
        limit=12,
    )
    history = deps.get_scenario_history(
        user.user_id,
        project_id=original.project_id,
        limit=20,
    )
    exports = deps.list_exports(
        user.user_id,
        project_id=original.project_id,
        limit=8,
    )
    export_lineage = deps.build_export_lineage(
        user.user_id,
        project_id=original.project_id,
        limit=8,
    )

    # ── scenario_summary_cards assembly (Quirks 6, 7) ───────────────
    # Quirk 6: 10 specific fields. Quirk 7: export_count computed
    # per scenario_name from export_lineage.
    scenario_summary_cards: list = []
    export_counts: dict = {}
    for entry in export_lineage:
        export_counts[entry["scenario_name"]] = (
            export_counts.get(entry["scenario_name"], 0) + 1
        )
    for item in scenarios:
        summary = item.last_run_summary or {}
        scenario_summary_cards.append(
            {
                "scenario_id": item.scenario_id,
                "scenario_name": item.scenario_name,
                "project_code": item.project_code,
                "updated_at": item.updated_at,
                "copied_from_scenario_id": item.copied_from_scenario_id,
                "project_irr": summary.get("project_irr"),
                "equity_irr": summary.get("equity_irr"),
                "avg_dscr": summary.get("avg_dscr"),
                "export_count": export_counts.get(item.scenario_name, 0),
                "governance_state": item.governance_state,
            }
        )

    # ── Workspace state resolution (Quirk 5: inline) ────────────────
    # workspace_state is resolved inline in the render call, not
    # stored in a separate variable.

    # ── Success response render (Quirk 3) ───────────────────────────
    # Quirk 3: success message is
    # f"Duplicated {original.scenario_name}." (with period).
    # Quirk 9: full workspace render, not HTMX partial.
    return deps.render_scenario_workspace(
        request,
        user,
        project_record,
        deps.get_workspace_state(user.user_id, original.project_id),
        scenarios,
        history,
        exports,
        export_lineage,
        scenario_summary_cards,
        message=f"Duplicated {original.scenario_name}.",
    )
