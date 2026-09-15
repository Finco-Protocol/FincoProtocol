"""Phase 51O-2 — POST /projects/{project_code}/save-as route family
vertical extraction.

This module owns the orchestration body that previously lived
inline in main_web.py for:

- POST /projects/{project_code}/save-as (save_project_as_endpoint)

The route handler in main_web.py is now a thin wrapper
(auth + path param + deps bundle + service call + response
translation). The full orchestration (source project lookup, gate
on user_created, new_code/new_name generation, save_project with
governance_state + replay_metadata, save_workspace_state with
governance_state + replay_metadata) lives here.

This service does NOT import main_web or main_api. The route
in main_web.py wires the deps bundle and calls
``execute_project_save_as_route(...)``. The service returns a
``ProjectSaveAsRouteOutcome`` dataclass which the route
translates to a ``RedirectResponse`` (302 success or 302 auth) or
``JSONResponse`` (404 / 400). Auth is route-owned, so the service
does not produce redirects itself; it sets ``is_redirect=True``
and ``redirect_url`` and the route translates.

16 behaviors preserved (Phase 51O-1):

1. POST /projects/{project_code}/save-as exists.
2. Auth check via get_current_user(request) (route-owned).
3. Unauthenticated -> 302 redirect to /login (NOT 401 JSON).
4. Path parameter project_code: target project to duplicate.
5. Source project lookup: get_project_record(user_id, project_code).
6. 404 if source not found.
7. 400 if source.project_origin == "user_created".
8. new_code = f"{project_code}-copy-{now.strftime('%Y%m%d%H%M%S')}"
9. new_name = f"{source.project_name} (Copy)"
10. save_project creates new record with project_origin="user_created",
    is_readonly=False, last_run_summary={}.
11. save_workspace_state initializes workspace from
    source.baseline_snapshot, draft=saved=baseline, dirty=False.
12. Both calls inject governance_state dict with g20=BLOCKED,
    r99_r102=NOT_APPROVED, lender_ready=False.
13. replay_metadata.export_type: "project_duplicated" (save_project)
    and "workspace_duplicated" (save_workspace_state).
14. Response: 302 redirect to /?project={new_code}.
15. No HTMX-specific headers (no HX-Trigger, no HX-Redirect).
16. No model execution. No exports.

10 quirks preserved (Phase 51O-1):

1. Local import `from app.persistence.repository import
   get_project_record as gpr` (now in the service; route no longer
   needs the local import).
2. new_code = f"{project_code}-copy-{now.strftime('%Y%m%d%H%M%S')}"
3. new_name = f"{source.project_name} (Copy)"
4. governance_state dict inlined twice (same dict, replicated for
   save_project and save_workspace_state; not a helper).
5. baseline_source is a computed boolean:
   source.project_origin == "saved_baseline".
6. last_run_summary={} (empty dict, not None).
7. draft_snapshot=saved_snapshot=source.baseline_snapshot (new
   workspace starts clean).
8. 400 path returns JSONResponse (not friendly UI).
9. 404 path returns JSONResponse with formatted error.
10. Success returns 302 RedirectResponse (not HX-Redirect).

Intended persistence side effects (NOT forbidden):

- deps.get_project_record(...) -- 1 call per success (source lookup).
- deps.save_project(...) -- 1 call per success (new project record).
- deps.save_workspace_state(...) -- 1 call per success (new workspace).

Per 404 (source not found): short-circuit before save_project and
save_workspace_state.
Per 400 (source is already user_created): short-circuit before
save_project and save_workspace_state.

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
- add_scenario / save_scenario / create_scenario (Phase 51M-2
  /projects/create does NOT create a scenario; this route also
  does NOT create a scenario; only ProjectRecord + WorkspaceState)
- _collect_form_snapshot / await request.form() (Quirk 1 of
  /projects/create: uses FastAPI Form injection -- save-as uses
  neither Form nor await request.form(); it uses path params only)
- templates.TemplateResponse (Quirk 8/9/10: 400/404 use JSONResponse,
  success uses RedirectResponse; no template rendering in this route)

Phase 51F guardrails: this module does NOT import main_web or
main_api. The engine-output golden guardrail, parity-core lock
guardrail, and no-service-imports guardrail remain green.

Why a separate service module (not extending project_save_as
logic into projects_create_service.py):

- projects_create_service.py handles /projects/create (new project
  from form snapshot, with template validation and 18 form fields).
  Different concern.

- scenario_state_service.py is data-layer only (no Request, no
  form, no auth).

- scenario_state_route_service.py handles /scenarios/state/draft
  and /scenarios/state/discard. Different concern.

- scenarios_save_service.py is for /scenarios/save. Different concern.

- scenario_duplicate_service.py is for /scenarios/{id}/duplicate.
  Different concern.

- scenarios_add_service.py is for /scenarios/add. Different concern.

The new project_save_as_service.py is the right place for the
project-copy/save-as orchestration.

Backend remains source of truth. rc1 remains frozen.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from app.utils.workbook_flag import project_workbook_url


# ─────────────────────────────────────────────────────────────────────────────
# Public dataclasses
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class ProjectSaveAsRouteOutcome:
    """Result of POST /projects/{project_code}/save-as orchestration.

    The route in ``main_web.py`` translates this into a FastAPI
    response via ``RedirectResponse(...)`` (success or auth) or
    ``JSONResponse(...)`` (404 / 400). For symmetry with the
    broader Phase 51 family the outcome also carries
    ``template_name`` (unused), ``context`` (unused),
    ``payload`` (for JSON error), ``status_code``, ``headers``
    (unused), ``is_redirect``, and ``redirect_url``.

    Fields:
        template_name: Jinja template to render. Default unused
            (this route does not render templates).
        context: Jinja context dict. Unused.
        payload: JSON payload for non-redirect responses (404/400).
        status_code: HTTP status code. 200, 302, 400, or 404.
        headers: Extra response headers. Unused.
        is_redirect: ``True`` if the route should redirect. Used
            for auth (302 to /login) and success (302 to
            /?project={new_code}).
        redirect_url: URL to redirect to (when is_redirect is
            True). E.g., ``/login`` (auth) or
            ``/?project={new_code}`` (success).
    """

    template_name: str = ""
    context: dict = field(default_factory=dict)
    payload: dict = field(default_factory=dict)
    status_code: int = 200
    headers: dict = field(default_factory=dict)
    is_redirect: bool = False
    redirect_url: Optional[str] = None


@dataclass
class ProjectSaveAsRouteDeps:
    """Dependencies that ``execute_project_save_as_route`` needs
    from the route.

    The route in ``main_web.py`` owns these helpers; passing them
    in as callables (rather than importing from ``main_web``) keeps
    the ``main_web`` -> ``project_save_as_service`` import
    direction clean and lets future test code inject test doubles.

    The bundle has 9 callables.
    """

    # Source project lookup
    get_project_record: Callable[..., Any]

    # Persistence (intended writes)
    save_project: Callable[..., Any]
    save_workspace_state: Callable[..., Any]

    # Time
    now_utc: Callable[..., Any]

    # Governance state builders
    project_record_creation_governance_state: Callable[..., dict]
    workspace_state_initialization_governance_state: Callable[..., dict]

    # Replay metadata builders
    build_project_replay_metadata: Callable[..., dict]
    build_workspace_replay_metadata: Callable[..., dict]

    # Source gating
    is_already_user_project: Callable[..., bool]

    # SCENARIO-1: initialize base case so /scenarios/add never finds an
    # empty scenario list.  Optional for backward-compat with older tests.
    get_or_create_base_case_scenario: Callable[..., Any] | None = None


# ─────────────────────────────────────────────────────────────────────────────
# Service entry point
# ─────────────────────────────────────────────────────────────────────────────


async def execute_project_save_as_route(
    *,
    request: Any,
    project_code: str,
    user: Any,
    deps: ProjectSaveAsRouteDeps,
) -> ProjectSaveAsRouteOutcome:
    """Execute the POST /projects/{project_code}/save-as
    orchestration and return a ProjectSaveAsRouteOutcome.

    Mirrors the legacy ``save_project_as_endpoint`` route body in
    main_web.py (Phase 51O-1 characterization).

    Behavior:
    - Source lookup: deps.get_project_record(user_id, project_code).
    - 404 if source is None.
    - 400 if source.project_origin == "user_created".
    - new_code = f"{project_code}-copy-{now.strftime('%Y%m%d%H%M%S')}"
    - new_name = f"{source.project_name} (Copy)"
    - save_project with project_origin="user_created",
      is_readonly=False, last_run_summary={}, and the
      project_record_creation_governance_state dict.
    - save_workspace_state with
      draft_snapshot=saved_snapshot=source.baseline_snapshot,
      dirty=False, and the
      workspace_state_initialization_governance_state dict.
    - Returns either a 302 redirect outcome (success) or a JSON
      error outcome (404 / 400).
    """
    source = deps.get_project_record(
        user_id=user.user_id, project_code=project_code
    )
    if source is None:
        return ProjectSaveAsRouteOutcome(
            payload={"error": f"Project '{project_code}' not found"},
            status_code=404,
        )
    if deps.is_already_user_project(source):
        return ProjectSaveAsRouteOutcome(
            payload={"error": "Already a user project"},
            status_code=400,
        )

    now = deps.now_utc()
    new_code = f"{project_code}-copy-{now.strftime('%Y%m%d%H%M%S')}"
    new_name = f"{source.project_name} (Copy)"

    # Create the new project record (Quirk: project_origin=user_created,
    # is_readonly=False, last_run_summary={})
    new_record = deps.save_project(
        user_id=user.user_id,
        project_code=new_code,
        project_name=new_name,
        project_type=source.project_type,
        project_origin="user_created",
        source_project_template=source.source_project_template,
        template_source=source.template_source,
        baseline_snapshot=source.baseline_snapshot,
        is_readonly=False,
        governance_state=deps.project_record_creation_governance_state(),
        last_run_summary={},
        replay_metadata=deps.build_project_replay_metadata(
            source, project_code
        ),
    )

    # HOTFIX-PILOT-BLOCKER-1 (F1): Sanitize the inherited snapshot
    # so the working copy has its OWN identity, not the source's.
    # Without this, draft_snapshot/saved_snapshot still contain
    # active_project="generic_wind_reference" / project_origin="factory_template",
    # which causes (a) the /run route to resolve the WRONG project
    # via _resolve_project_record(), and (b) the workspace to be
    # recorded under the Generic Wind Reference reference, leaving the working copy
    # workspace empty. We overwrite the three identity fields
    # (active_project, project_origin, project_name) with the new
    # copy's values. template_source stays as source.template_source
    # so the engine still picks the right factory defaults.
    working_copy_snapshot = dict(source.baseline_snapshot or {})
    working_copy_snapshot["active_project"] = new_record.project_code
    working_copy_snapshot["project_origin"] = "user_created"
    working_copy_snapshot["project_name"] = new_record.project_name

    # Materialize canonical rev_* defaults for Generic Solar Reference working copies so that
    # UI fields show actual values rather than blank fields backed by invisible
    # factory inheritance.  Only seed keys that are absent — never overwrite a
    # value already in the source snapshot.
    if (source.template_source or "").lower() == "generic_solar_reference":
        from app.project_factories import create_generic_solar_reference
        from app.revenue_snapshot_utils import materialize_revenue_snapshot_defaults
        _generic_solar_reference_factory = create_generic_solar_reference()
        _rev_defaults = materialize_revenue_snapshot_defaults(_generic_solar_reference_factory.revenue)
        for key, default_val in _rev_defaults.items():
            if not working_copy_snapshot.get(key):
                working_copy_snapshot[key] = default_val

    # Initialize the new workspace (Quirk: draft=saved=baseline, dirty=False)
    deps.save_workspace_state(
        user_id=user.user_id,
        project_id=new_record.project_id,
        project_code=new_record.project_code,
        draft_snapshot=working_copy_snapshot,
        saved_snapshot=working_copy_snapshot,
        dirty=False,
        governance_state=deps.workspace_state_initialization_governance_state(),
        replay_metadata=deps.build_workspace_replay_metadata(
            source, project_code
        ),
    )

    # ── Initialize Base Case scenario (SCENARIO-1) ────────────────────
    if deps.get_or_create_base_case_scenario is not None:
        deps.get_or_create_base_case_scenario(
            user_id=user.user_id,
            project_id=new_record.project_id,
            project_code=new_record.project_code,
            project_name=new_name,
            project_type=new_record.project_type,
            source_project_template=new_record.source_project_template,
            base_input_set=dict(source.baseline_snapshot or {}),
            governance_state=deps.project_record_creation_governance_state(),
            replay_metadata={"export_type": "base_case_scenario_created",
                             "source_project_code": project_code},
        )

    return ProjectSaveAsRouteOutcome(
        status_code=302,
        is_redirect=True,
        redirect_url=project_workbook_url(new_code),
    )
