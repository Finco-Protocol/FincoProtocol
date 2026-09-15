"""Phase 51L-2 — POST /scenarios/add route family vertical extraction.

This module owns the orchestration body that previously lived
inline in main_web.py for:

- POST /scenarios/add (add_scenario_endpoint)

The route handler in main_web.py is now a thin wrapper
(auth + form + deps bundle + service call + render). The full
orchestration (form input read, validation, project lookup,
user_created gate, base case lookup, oldest-scenario
promotion fallback, base_input_set fallback chain, add_scenario
call assembly, post-add scenario list reload, workspace_state
lookup, response context assembly with HX-Trigger header,
5 explicit error paths with JSON payload) lives here.

This service does NOT import main_web or main_api. The route
in main_web.py wires the deps bundle and calls
``execute_scenarios_add_route(...)``. The service returns a
``ScenariosAddRouteOutcome`` dataclass which the route
translates to a ``TemplateResponse`` (success) or
``JSONResponse`` (error path) or ``RedirectResponse`` (auth).
Auth is route-owned, so the service does not produce redirects
itself.

15 behaviors preserved (Phase 51L-1):

1. POST /scenarios/add exists.
2. Auth check via get_current_user(request) (route-owned).
3. Unauthenticated -> 302 redirect to /login (NOT 401 JSON).
4. Form read via await request.form() (route-owned).
5. Form input via individual form.get() calls: project_code,
   scenario_name (NOT _collect_form_snapshot).
6. scenario_name / project_code are .strip()-ed.
7. Validation: missing project_code -> 400 JSON
   {error: 'project_code is required'}.
8. Validation: missing scenario_name -> 400 JSON
   {error: 'scenario_name is required'}.
9. get_project_record(user_id=user.user_id, project_code=project_code)
   resolves the project.
10. If project_record is None -> 404 JSON {error: 'Project not found'}.
11. If project_origin != 'user_created' -> 403 JSON
    {error: 'Add Scenario is only available for user-created projects'}.
12. list_scenarios(user.user_id, project_id=project_record.project_id,
    include_archived=False) finds the base case.
13. Fallback: if no base_case but other scenarios exist, promote
    the oldest via _get_least_created_scenario_for_project +
    promote_scenario_to_base_case.
14. add_scenario(...) is called exactly once with:
    - parent_scenario_id=base_case.scenario_id
    - base_input_set=base_case.snapshot or base_case.base_input_set or {}
    - overrides={}
    - governance_state={}
    - replay_metadata with action='add_scenario',
      parent_scenario_id, project_code.
15. Success response: templates.TemplateResponse(
    name='partials/scenario_tab.html',
    context=_build_scenario_tab_context(user, project_record, scenarios, ws),
    headers={'HX-Trigger': 'scenarioAdded'}).
    Failure -> 500 JSON {error: 'Failed to create scenario'}.

10 quirks preserved (Phase 51L-1):

1. Form input via individual form.get() calls, NOT
   _collect_form_snapshot.
2. HX-Trigger: scenarioAdded on success.
3. Partial template render: partials/scenario_tab.html, NOT
   full workspace render.
4. Fallback: promote oldest scenario to base case if none
   exists.
5. replay_metadata uses action='add_scenario', NOT export_type.
6. governance_state={} (empty dict); repository is source of
   truth.
7. overrides={} (empty dict); user adds later.
8. Only user_created projects can add scenarios (403 otherwise).
9. base_input_set fallback chain:
   base_case.snapshot or base_case.base_input_set or {}.
10. Re-read scenarios list after add (with limit=12) for render
    context.

Intended persistence side effects (NOT forbidden):

- get_project_record(...) -- 1 call per request.
- list_scenarios(...) -- 2 calls per success (1 for base case
  lookup, 1 for render context).
- _get_least_created_scenario_for_project(...) -- 0 or 1 call
  (only if no base case AND other scenarios exist).
- promote_scenario_to_base_case(...) -- 0 or 1 call (only if
  no base case AND oldest exists).
- add_scenario(...) -- 1 call per success (after all checks).
- get_workspace_state(...) -- 1 call per success.

Per 400 (missing project_code or scenario_name): NO persistence
calls happen. The route short-circuits with the 400 JSON.

Per 404 (project not found): only get_project_record is called;
all other persistence calls are 0.

Per 403 (non-user_created project): only get_project_record is
called; all other persistence calls are 0.

Per 500 (add_scenario failure): get_project_record, list_scenarios
(base case), _get_least_created_scenario_for_project,
promote_scenario_to_base_case, and add_scenario are called;
list_scenarios (render) and get_workspace_state are NOT called.

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
  bind_workspace_to_scenario behavior
- run_project / model execution
- build_institutional_workbook_export
- build_excel_export_for_post_request
- build_runtime_summary_csv_export
- build_values_only_export_for_project
- db.add / db.commit / db.flush (direct)
- session.add / session.commit (direct)
- unrelated persistence writes
- _collect_form_snapshot (route uses individual form.get())

Phase 51F guardrails: this module does NOT import main_web or
main_api. The engine-output golden guardrail, parity-core lock
guardrail, and no-service-imports guardrail remain green.

Why a separate service module (not extending scenario_state_service.py
or scenario_state_route_service.py or scenarios_save_service.py
or scenario_duplicate_service.py):

- scenario_state_service.py is data-layer only (no Request, no
  form, no auth). Adding route orchestration would mix data-
  layer and route-orchestration concerns.

- scenario_state_route_service.py handles workspace draft/discard
  mutations WITHOUT scenario row creation. /scenarios/add calls
  add_scenario (which creates a new ScenarioRecord); this is a
  different concern.

- scenarios_save_service.py is for /scenarios/save (creates a
  new ScenarioRecord from form snapshot). /scenarios/add creates
  a new non-base scenario with parent inheritance from the
  base case. Different concern.

- scenario_duplicate_service.py is for /scenarios/{id}/duplicate
  (copies an existing ScenarioRecord). Different concern.

Backend remains source of truth. rc1 remains frozen.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional


# ─────────────────────────────────────────────────────────────────────────────
# Public dataclasses
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class ScenariosAddRouteOutcome:
    """Result of POST /scenarios/add orchestration.

    The route in ``main_web.py`` translates this into a FastAPI
    response via ``TemplateResponse(...)`` (success) or
    ``JSONResponse(...)`` (error path) or
    ``RedirectResponse(...)`` (auth). For symmetry with the
    broader Phase 51 family the outcome also carries
    ``is_redirect`` and ``redirect_url`` in case future routes
    need to redirect; auth is currently route-owned, so the
    service does not produce redirects itself.

    Fields:
        template_name: Jinja template to render (success path).
            Default ``"partials/scenario_tab.html"``.
        context: Jinja context dict (success path). The service
            calls ``deps.build_scenario_tab_context(...)`` to
            build this.
        payload: JSON payload for non-template responses (e.g.
            400/403/404/500 errors). The route constructs a
            ``JSONResponse`` with ``content=outcome.payload``
            and ``status_code=outcome.status_code``.
        status_code: HTTP status code. 200 for success; 400/403/
            404/500 for error paths. Other status codes are not
            produced by this service.
        headers: Extra response headers. Used for
            ``HX-Trigger: scenarioAdded`` on success.
        is_redirect: ``True`` if the route should redirect (e.g.
            unauthenticated -> /login). Currently unused (auth is
            route-owned).
        redirect_url: URL to redirect to (when is_redirect is
            True). Currently unused.
    """

    template_name: str = "partials/scenario_tab.html"
    context: dict = field(default_factory=dict)
    payload: dict = field(default_factory=dict)
    status_code: int = 200
    headers: dict = field(default_factory=dict)
    is_redirect: bool = False
    redirect_url: Optional[str] = None


@dataclass
class ScenariosAddRouteDeps:
    """Dependencies that ``execute_scenarios_add_route`` needs
    from the route.

    The route in ``main_web.py`` owns these helpers; passing them
    in as callables (rather than importing from ``main_web``) keeps
    the ``main_web`` -> ``scenarios_add_service`` import
    direction clean and lets future test code inject test doubles.

    The bundle has 8 callables. No constants are needed because
    the route reads individual form fields (Quirk 1) and does
    not use form-schema constants.
    """

    # Project resolution
    get_project_record: Callable[..., Any]

    # Scenario lookup / base case management
    list_scenarios: Callable[..., Any]
    get_least_created_scenario_for_project: Callable[..., Any]
    promote_scenario_to_base_case: Callable[..., Any]

    # Persistence (intended write)
    add_scenario: Callable[..., Any]

    # Workspace state resolution
    get_workspace_state: Callable[..., Any]

    # Render context assembly
    build_scenario_tab_context: Callable[..., Any]

    # SCENARIO-1 lazy repair: create Base Case on first /scenarios/add
    # for legacy projects that have zero scenario rows.  Optional for
    # backward-compat with tests that don't supply it.
    get_or_create_base_case_scenario: Callable[..., Any] | None = None


# ─────────────────────────────────────────────────────────────────────────────
# Service entry point
# ─────────────────────────────────────────────────────────────────────────────


async def execute_scenarios_add_route(
    *,
    request: Any,
    form: Any,
    user: Any,
    deps: ScenariosAddRouteDeps,
) -> ScenariosAddRouteOutcome:
    """Execute the POST /scenarios/add orchestration and return
    a ScenariosAddRouteOutcome.

    Mirrors the legacy ``add_scenario_endpoint`` route body in
    main_web.py (Phase 51L-1 characterization).

    Behavior:
    - Reads form snapshot via the form argument (the route has
      already called ``await request.form()``).
    - Reads individual form fields via ``form.get(...)``:
      ``project_code`` and ``scenario_name`` (Quirk 1).
    - Validates: missing project_code -> 400 JSON; missing
      scenario_name -> 400 JSON.
    - Resolves project_record via
      ``deps.get_project_record(user_id=user.user_id,
      project_code=project_code)``.
    - If project_record is None -> 404 JSON
      {error: 'Project not found'}.
    - If project_record.project_origin != 'user_created' -> 403
      JSON {error: 'Add Scenario is only available for
      user-created projects'}.
    - Finds the base case via
      ``deps.list_scenarios(user.user_id,
      project_id=project_record.project_id, include_archived=False)``.
    - If no base_case but other scenarios exist, promotes the
      oldest via
      ``deps.get_least_created_scenario_for_project(user.user_id,
      project_record.project_id)`` +
      ``deps.promote_scenario_to_base_case(user.user_id,
      oldest.scenario_id)``.
    - Calls ``deps.add_scenario(...)`` ONCE with the right
      kwargs.
    - If new_scenario is None -> 500 JSON
      {error: 'Failed to create scenario'}.
    - Re-reads scenarios (with limit=12) and workspace_state for
      the render context.
    - Returns the rendered workspace response via
      ``deps.render_template_response(...)`` with HX-Trigger
      header.
    """
    # ── Form input read (Quirk 1) ────────────────────────────────────
    project_code = form.get("project_code", "").strip()
    scenario_name = form.get("scenario_name", "").strip()

    # ── Validation error paths (400) ─────────────────────────────────
    if not project_code:
        return ScenariosAddRouteOutcome(
            status_code=400,
            payload={"error": "project_code is required"},
        )
    if not scenario_name:
        return ScenariosAddRouteOutcome(
            status_code=400,
            payload={"error": "scenario_name is required"},
        )

    # ── Project resolution (and 404/403 error paths) ────────────────
    project_record = deps.get_project_record(
        user_id=user.user_id, project_code=project_code
    )
    if project_record is None:
        return ScenariosAddRouteOutcome(
            status_code=404,
            payload={"error": "Project not found"},
        )
    if project_record.project_origin != "user_created":
        return ScenariosAddRouteOutcome(
            status_code=403,
            payload={
                "error": "Add Scenario is only available for "
                          "user-created projects"
            },
        )

    # ── Base case lookup (Quirk 4 fallback) ──────────────────────────
    # Find the Base Case scenario for this project.
    base_case = None
    scenarios = deps.list_scenarios(
        user.user_id,
        project_id=project_record.project_id,
        include_archived=False,
    )
    for s in scenarios:
        if s.is_base_case:
            base_case = s
            break

    # If no base case exists but other scenarios do, promote the
    # oldest one to base case. This handles projects where
    # scenarios were imported/copied without a designated base
    # case. We pick the one with the earliest created_at so we
    # promote the original scenario, not a later derivative.
    if base_case is None and scenarios:
        oldest = deps.get_least_created_scenario_for_project(
            user.user_id, project_record.project_id
        )
        if oldest:
            base_case = deps.promote_scenario_to_base_case(
                user.user_id, oldest.scenario_id
            )
        else:
            base_case = None

    # ── SCENARIO-1 lazy repair: zero-scenario legacy projects ─────────
    # Projects created before the SCENARIO-1 fix have no scenario rows.
    # The promotion fallback above only fires when scenarios is non-empty.
    # For the empty case we lazily create the Base Case now so that this
    # and all future /scenarios/add calls succeed without a migration.
    if base_case is None and deps.get_or_create_base_case_scenario is not None:
        ws_state = deps.get_workspace_state(
            user.user_id, project_record.project_id
        )
        base_input = {}
        if ws_state is not None:
            base_input = (
                ws_state.saved_snapshot
                or ws_state.draft_snapshot
                or {}
            )
        base_case = deps.get_or_create_base_case_scenario(
            user_id=user.user_id,
            project_id=project_record.project_id,
            project_code=project_record.project_code,
            project_name=project_record.project_name,
            project_type=project_record.project_type,
            source_project_template=project_record.source_project_template,
            base_input_set=base_input,
            governance_state={},
        )

    # Safety: if base_case is still None (not wired or all repair paths
    # failed), return a clean 500 rather than crashing with AttributeError.
    if base_case is None:
        return ScenariosAddRouteOutcome(
            status_code=500,
            payload={"error": "No base case scenario found for this project"},
        )

    # ── Add scenario (Quirks 5, 6, 7, 9) ─────────────────────────────
    new_scenario = deps.add_scenario(
        user_id=user.user_id,
        project_id=project_record.project_id,
        project_code=project_record.project_code,
        scenario_name=scenario_name,
        parent_scenario_id=base_case.scenario_id,
        base_input_set=(
            base_case.snapshot or base_case.base_input_set or {}
        ),
        overrides={},
        governance_state={},
        replay_metadata={
            "action": "add_scenario",
            "parent_scenario_id": base_case.scenario_id,
            "project_code": project_code,
        },
    )

    # ── 500 error path ──────────────────────────────────────────────
    if new_scenario is None:
        return ScenariosAddRouteOutcome(
            status_code=500,
            payload={"error": "Failed to create scenario"},
        )

    # ── Re-read scenarios + workspace_state for render context ─────
    # (Quirk 10)
    scenarios = deps.list_scenarios(
        user.user_id,
        project_id=project_record.project_id,
        include_archived=False,
        limit=12,
    )
    ws = deps.get_workspace_state(user.user_id, project_record.project_id)

    # ── Success response render (Quirks 2, 3) ───────────────────────
    # Build the template context via build_scenario_tab_context.
    # The route in main_web.py translates this to
    # templates.TemplateResponse(name=template_name,
    # context=context, headers=headers).
    context = deps.build_scenario_tab_context(
        user, project_record, scenarios, ws
    )
    return ScenariosAddRouteOutcome(
        template_name="partials/scenario_tab.html",
        context=context,
        status_code=200,
        headers={"HX-Trigger": "scenarioAdded"},
    )
