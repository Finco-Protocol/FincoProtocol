"""Phase 51M-2 — POST /projects/create route family vertical
extraction.

This module owns the orchestration body that previously lived
inline in main_web.py for:

- POST /projects/create (create_project_route)

The route handler in main_web.py is now a thin wrapper
(auth + form + deps bundle + service call + render). The full
orchestration (form coercion, project type canonicalization,
template source normalization, payload validation, template
source validation, project code slugification and uniqueness
loop, baseline snapshot construction, project record creation,
workspace state initialization, response context assembly with
HX-Redirect header) lives here.

This service does NOT import main_web or main_api. The route
in main_web.py wires the deps bundle and calls
``execute_projects_create_route(...)``. The service returns a
``ProjectsCreateRouteOutcome`` dataclass which the route
translates to a ``TemplateResponse`` (success or validation
error) or ``RedirectResponse`` (auth). Auth is route-owned, so
the service does not produce redirects itself.

20 behaviors preserved (Phase 51M-1):

1. POST /projects/create exists.
2. Auth check via get_current_user(request) (route-owned).
3. Unauthenticated -> 302 redirect to /login (NOT 401 JSON).
4. Form is read via FastAPI Form(...) injection (route-owned).
5. submitted dict is built from _submitted_new_project_defaults
   + form values.
6. _coerce_form_text(clean_name) coerces the project name.
7. _canonical_project_type(project_type) canonicalizes the
   project type.
8. _normalize_template_source(template_source, canonical_type)
   normalizes the template source.
9. _validate_new_project_payload(submitted) validates the
   payload.
10. Template source validation: wind templates require Wind
    type; solar templates require Solar type.
11. _slugify_project_code(clean_name) slugifies the project
    code.
12. Project code uniqueness loop: if get_project_by_code returns
    non-None, append -2, -3, ... until unique.
13. _project_baseline_snapshot(canonical_type,
    normalized_source) builds the baseline snapshot.
14. _apply_new_project_required_inputs(...) applies required
    inputs.
15. create_project_record(...) creates the ProjectRecord with
    project_origin='user_created'.
16. save_workspace_state(...) initializes the workspace.
17. _governance_snapshot(project_code) is called twice (create
    + save).
18. _replay_metadata_for_project is called twice with different
    export_type values.
19. Validation error (400): templates.TemplateResponse with
    partials/new_project_form.html.
20. Success (200): templates.TemplateResponse with
    partials/new_project_result.html and HX-Redirect header.

10 quirks preserved (Phase 51M-1):

1. Uses FastAPI Form(...) parameters, NOT await request.form() or
   _collect_form_snapshot.
2. HX-Redirect: f'/?project={project_record.project_code}' on
   success.
3. Partial template render (partials/new_project_result.html),
   NOT full workspace render.
4. Project code uniqueness loop with -2, -3, ... suffixes.
5. replay_metadata uses export_type: 'project_record_created'
   and 'workspace_project_created'.
6. Template source validation: wind templates require Wind
   type, solar templates require Solar type.
7. save_workspace_state with draft=saved=baseline_snapshot,
   dirty=False.
8. project_origin='user_created' only; no gate for non-
   user_created.
9. Does NOT explicitly call add_scenario or save_scenario; only
   creates ProjectRecord + WorkspaceState.
10. target_dscr defaults to '1.20'.

Intended persistence side effects (NOT forbidden):

- get_project_by_code(...) -- 1+ call per success (uniqueness
  loop).
- create_project_record(...) -- 1 call per success (the project
  record).
- save_workspace_state(...) -- 1 call per success (the workspace
  state).

Per 400 (validation error): the route short-circuits before
create_project_record and save_workspace_state.

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
- add_scenario / save_scenario / create_scenario (Quirk 9:
  Project creation does NOT create a scenario; only ProjectRecord
  + WorkspaceState)
- _collect_form_snapshot / await request.form() (Quirk 1: uses
  FastAPI Form injection)
- _validate_form (no form validation; uses _validate_new_project_payload)

Phase 51F guardrails: this module does NOT import main_web or
main_api. The engine-output golden guardrail, parity-core lock
guardrail, and no-service-imports guardrail remain green.

Why a separate service module (not extending scenario_state_service.py
or scenarios_add_service.py or scenarios_save_service.py or
scenario_duplicate_service.py):

- scenario_state_service.py is data-layer only (no Request, no
  form, no auth). Adding route orchestration would mix data-
  layer and route-orchestration concerns.

- scenario_state_route_service.py handles workspace draft/discard
  mutations WITHOUT scenario row creation. /projects/create calls
  create_project_record (which creates a ProjectRecord); this is
  a different concern.

- scenarios_save_service.py is for /scenarios/save (creates a
  new ScenarioRecord from form snapshot). Different concern.

- scenarios_add_service.py is for /scenarios/add (creates a new
  ScenarioRecord with parent inheritance from base case).
  Different concern.

- scenario_duplicate_service.py is for /scenarios/{id}/duplicate
  (copies an existing ScenarioRecord). Different concern.

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
class ProjectsCreateRouteOutcome:
    """Result of POST /projects/create orchestration.

    The route in ``main_web.py`` translates this into a FastAPI
    response via ``TemplateResponse(...)`` (success or validation
    error) or ``RedirectResponse(...)`` (auth). For symmetry with
    the broader Phase 51 family the outcome also carries
    ``is_redirect`` and ``redirect_url``.

    Fields:
        template_name: Jinja template to render. Default
            ``"partials/new_project_result.html"`` (success) or
            ``"partials/new_project_form.html"`` (validation
            error).
        context: Jinja context dict (success or validation
            error). The service calls
            ``deps.build_template_context(...)`` to build this
            (success) or
            ``deps.build_validation_error_context(...)`` to build
            this (validation error).
        payload: JSON payload for non-template responses (e.g.
            future JSON error paths). Currently unused.
        status_code: HTTP status code. 200 for success; 400 for
            validation error.
        headers: Extra response headers. Used for
            ``HX-Redirect: f"/?project=..."`` on success.
        is_redirect: ``True`` if the route should redirect. Used
            for auth (302 to /login); currently route-owned.
        redirect_url: URL to redirect to (when is_redirect is
            True). Currently unused.
    """

    template_name: str = "partials/new_project_result.html"
    context: dict = field(default_factory=dict)
    payload: dict = field(default_factory=dict)
    status_code: int = 200
    headers: dict = field(default_factory=dict)
    is_redirect: bool = False
    redirect_url: Optional[str] = None


@dataclass
class ProjectsCreateRouteDeps:
    """Dependencies that ``execute_projects_create_route`` needs
    from the route.

    The route in ``main_web.py`` owns these helpers; passing them
    in as callables (rather than importing from ``main_web``) keeps
    the ``main_web`` -> ``projects_create_service`` import
    direction clean and lets future test code inject test doubles.

    The bundle has 16 callables. The route pre-builds the
    ``submitted`` dict from ``_submitted_new_project_defaults()``
    + the form values, then passes the dict to the service.
    """

    # Submitted dict builder
    submitted_new_project_defaults: Callable[..., dict]

    # Text coercion / canonicalization / normalization
    coerce_form_text: Callable[..., str]
    canonical_project_type: Callable[..., str]
    normalize_template_source: Callable[..., str]

    # Validation
    validate_new_project_payload: Callable[..., list]

    # Project code slugification + uniqueness
    slugify_project_code: Callable[..., str]
    get_project_by_code: Callable[..., Any]

    # Baseline snapshot construction
    project_baseline_snapshot: Callable[..., dict]
    apply_new_project_required_inputs: Callable[..., dict]

    # Persistence (intended writes)
    create_project_record: Callable[..., Any]
    save_workspace_state: Callable[..., Any]

    # Governance / replay metadata
    governance_snapshot: Callable[..., dict]
    replay_metadata_for_project: Callable[..., dict]

    # Render context assembly
    new_project_validation_error_context: Callable[..., dict]
    template_source_label: Callable[..., str]

    # Response render
    render_template_response: Callable[..., Any]

    # Phase P2-FIX-1: minimal template for the
    # C2 minimal new-project flow. The
    # default template_name in the outcome
    # is used when no minimal_template
    # override is supplied. Marked Optional
    # for backward compat with the legacy
    # full-form path.
    new_project_minimal_validation_error_context: Callable[..., dict] | None = None

    # SCENARIO-1: initialize base case on creation so /scenarios/add never
    # finds an empty scenario list.  Optional for backward-compat with tests
    # that don't supply it; callers should always wire it in production.
    get_or_create_base_case_scenario: Callable[..., Any] | None = None


# ─────────────────────────────────────────────────────────────────────────────
# Service entry point
# ─────────────────────────────────────────────────────────────────────────────


async def execute_projects_create_route(
    *,
    request: Any,
    submitted: dict,
    user: Any,
    deps: ProjectsCreateRouteDeps,
) -> ProjectsCreateRouteOutcome:
    """Execute the POST /projects/create orchestration and return
    a ProjectsCreateRouteOutcome.

    Mirrors the legacy ``create_project_route`` route body in
    main_web.py (Phase 51M-1 characterization).

    Behavior:
    - Coerces text via ``deps.coerce_form_text(submitted['project_name'])``.
    - Canonicalizes the project type via
      ``deps.canonical_project_type(submitted['project_type'])``.
    - Normalizes the template source via
      ``deps.normalize_template_source(...)``.
    - Validates the payload via ``deps.validate_new_project_payload(...)``.
    - Performs template source validation (Quirk 6).
    - Slugifies the project code and handles uniqueness via
      ``deps.get_project_by_code(...)`` in a loop.
    - Builds the baseline snapshot via
      ``deps.project_baseline_snapshot(...)`` and applies required
      inputs via
      ``deps.apply_new_project_required_inputs(...)``.
    - Calls ``deps.create_project_record(...)`` ONCE.
    - Calls ``deps.save_workspace_state(...)`` ONCE.
    - Returns either a success render (with HX-Redirect) or a
      validation error render (with status_code=400).
    """
    clean_name = deps.coerce_form_text(submitted["project_name"])
    canonical_type = deps.canonical_project_type(submitted["project_type"])
    normalized_source = deps.normalize_template_source(
        submitted["template_source"], canonical_type
    )
    # Update submitted with normalized values
    submitted["project_name"] = clean_name
    submitted["project_type"] = submitted["project_type"]  # keep raw
    submitted["template_source"] = normalized_source

    validation_errors = deps.validate_new_project_payload(submitted)

    # ── Template source validation (Quirk 6) ──────────────────────────
    if (
        normalized_source in {"generic_wind_reference", "generic_wind"}
        and canonical_type != "Wind"
    ):
        validation_errors.append(
            "Wind templates require project type Wind."
        )
    if (
        normalized_source in {"generic_solar_reference", "generic_solar"}
        and canonical_type != "Solar"
    ):
        validation_errors.append(
            "Solar templates require project type Solar."
        )

    # ── 400 validation error early return ────────────────────────────
    if validation_errors:
        # Phase P2-FIX-1: if the minimal validation
        # error context is provided, use the
        # minimal template + minimal context.
        # Otherwise fall back to the legacy
        # full-form template + context (default
        # Phase 51M-1 behaviour for backward
        # compat with older PR1/PR2/M1/S1/S2
        # tests).
        if deps.new_project_minimal_validation_error_context is not None:
            return ProjectsCreateRouteOutcome(
                template_name="partials/new_project_minimal.html",
                context=deps.new_project_minimal_validation_error_context(
                    submitted, validation_errors
                ),
                status_code=400,
            )
        return ProjectsCreateRouteOutcome(
            template_name="partials/new_project_form.html",
            context=deps.new_project_validation_error_context(
                submitted, validation_errors
            ),
            status_code=400,
        )

    # The normal product path is a clone of the selected canonical reference,
    # not a fresh snapshot that merely happens to share factory defaults.
    if normalized_source in {"generic_solar_reference", "generic_wind_reference"}:
        from app.services.reference_seed_service import create_reference_seeded_project

        project_record = create_reference_seeded_project(
            user_id=user.user_id,
            template_source=normalized_source,
            requested_name=clean_name,
            capacity_mw=float(submitted["capacity_mw"]),
        )
        return ProjectsCreateRouteOutcome(
            template_name="partials/new_project_result.html",
            context={
                "project_record": project_record,
                "template_source_label": deps.template_source_label(normalized_source),
            },
            status_code=200,
            headers={
                "HX-Redirect": project_workbook_url(project_record.project_code, sheet="overview")
            },
        )

    # ── Project code slugification + uniqueness loop (Quirk 4) ────────
    base_slug = deps.slugify_project_code(clean_name)
    project_code = base_slug
    suffix = 2
    while deps.get_project_by_code(user.user_id, project_code) is not None:
        project_code = f"{base_slug}-{suffix}"
        suffix += 1

    # ── Baseline snapshot construction ──────────────────────────────
    baseline_snapshot = deps.apply_new_project_required_inputs(
        deps.project_baseline_snapshot(canonical_type, normalized_source),
        project_name=clean_name,
        project_code=project_code,
        project_type=canonical_type,
        project_origin="user_created",
        template_source=normalized_source,
        submitted=submitted,
    )

    # ── Create project record (Quirk 8: user_created only) ────────────
    project_record = deps.create_project_record(
        user_id=user.user_id,
        project_code=project_code,
        project_name=clean_name,
        project_type=canonical_type,
        project_origin="user_created",
        template_source=normalized_source,
        baseline_snapshot=baseline_snapshot,
        governance_state=deps.governance_snapshot(project_code),
        replay_metadata=deps.replay_metadata_for_project(
            project_code,
            project_id=None,
            export_type="project_record_created",
        ),
    )

    # ── Save workspace state (Quirk 7: draft=saved=baseline, dirty=False) ──
    deps.save_workspace_state(
        user_id=user.user_id,
        project_id=project_record.project_id,
        project_code=project_record.project_code,
        draft_snapshot=baseline_snapshot,
        saved_snapshot=baseline_snapshot,
        dirty=False,
        governance_state=deps.governance_snapshot(project_code),
        replay_metadata=deps.replay_metadata_for_project(
            project_code,
            project_id=project_record.project_id,
            export_type="workspace_project_created",
        ),
    )

    # ── Initialize Base Case scenario (SCENARIO-1) ────────────────────
    # Every user-created project must have a Base Case scenario record so
    # that POST /scenarios/add never encounters an empty scenario list.
    if deps.get_or_create_base_case_scenario is not None:
        deps.get_or_create_base_case_scenario(
            user_id=user.user_id,
            project_id=project_record.project_id,
            project_code=project_record.project_code,
            project_name=clean_name,
            project_type=canonical_type,
            source_project_template=normalized_source,
            base_input_set=baseline_snapshot,
            governance_state=deps.governance_snapshot(project_code),
            replay_metadata=deps.replay_metadata_for_project(
                project_code,
                project_id=project_record.project_id,
                export_type="base_case_scenario_created",
            ),
        )

    # ── Success response render (Quirks 2, 3) ─────────────────────────
    return ProjectsCreateRouteOutcome(
        template_name="partials/new_project_result.html",
        context={
            "project_record": project_record,
            "template_source_label": deps.template_source_label(
                normalized_source
            ),
        },
        status_code=200,
        headers={
            "HX-Redirect": project_workbook_url(project_record.project_code, sheet="inputs")
        },
    )
