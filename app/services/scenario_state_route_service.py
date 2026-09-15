"""Phase 51H-2 — /scenarios/state/* route family vertical extraction.

This module owns the orchestration body that previously lived
inline in main_web.py for:

- POST /scenarios/state/draft (save_workspace_draft_endpoint)
- POST /scenarios/state/discard (discard_workspace_draft_endpoint)

The route handlers in main_web.py are now thin wrappers (auth +
form + deps bundle + service call + JSONResponse construction).
The full orchestration (active_project / active_scenario logic,
workspace_state draft/discard logic, replay metadata assembly,
save_workspace_state / discard_workspace_draft kwargs assembly
and calls, fallback clean workspace creation for discard, and
response payload assembly) lives here.

This service does NOT import main_web or main_api. The route
in main_web.py wires the deps bundle and calls
``execute_draft_route(...)`` or ``execute_discard_route(...)``.
The service returns a ``ScenarioStateRouteOutcome`` dataclass
which the route translates to a ``JSONResponse`` (or
``RedirectResponse`` for ``is_redirect=True``, but currently
both routes return JSON, never redirect).

15 characterized behaviors preserved (Phase 51H-1):

draft
1. POST /scenarios/state/draft exists.
2. Unauthenticated -> 401 JSON ``{"error": "Login required"}``
   (NOT 302 redirect to /login).
3. Authenticated + valid form -> 200 + JSON payload.
4. Authenticated + empty form -> 200 + JSON payload (no 400).
5. Authenticated + unknown active_project -> 200 + JSON
   (falls back to factory_template project).
6. user_id derived from session, never from form.
7. draft_snapshot = current form snapshot.
8. saved_snapshot = existing.saved_snapshot OR project
   baseline_snapshot OR default.
9. dirty = not snapshots_equal(snapshot, saved_snapshot).
10. replay_metadata.export_type = "workspace_draft_state".
11. replay_metadata.scenario_id = active_scenario_id (when present).
12. Response does NOT include 'snapshot' key.
13. Response message is a fixed string.
14. No HX-Trigger, no HX-Redirect, no template render.
15. user_id always = user.user_id.

discard
1. POST /scenarios/state/discard exists.
2. Unauthenticated -> 401 JSON (NOT 302 redirect).
3. Authenticated + valid form -> 200 + JSON payload.
4. Authenticated + empty form -> 200 + JSON payload (no 400).
5. Authenticated + unknown active_project -> 200 + JSON
   (falls back to factory_template project).
6. user_id derived from session, never from form.
7. discard_workspace_draft is always called once.
8. If discard_workspace_draft returns None, save_workspace_state
   is called once as fallback with baseline_snapshot.
9. Fallback: draft_snapshot = saved_snapshot = baseline_snapshot,
   dirty = False.
10. Response includes 'snapshot' key (full draft_snapshot dict).
11. Response message is a fixed string.
12. No HX-Trigger, no HX-Redirect, no template render.
13. last_runtime_* fields are preserved (not modified).
14. user_id always = user.user_id.
15. response includes all required keys.

12 characterized quirks preserved:

1. Draft message is a fixed string
   ("Workspace draft captured. Saved scenario authority is
   unchanged.").
2. Discard message is a fixed string
   ("Unsaved edits discarded. Workspace restored to the last
   saved runtime boundary.").
3. Discard response includes 'snapshot' key; draft does NOT.
4. Draft reads 'current_saved_scenario_id' from form (when no
   existing workspace) OR uses existing.active_scenario_id
   (when existing).
5. Draft replay_metadata uses scenario_id=active_scenario_id
   when present (NOT when None).
6. Discard fallback creates a clean workspace when none exists.
7. Draft does NOT modify last_runtime_* fields (preserved by
   the repository's save_workspace_state, since the route does
   not pass them as kwargs).
8. Discard keeps last_runtime_* fields (preserved by
   discard_workspace_draft, which copies them from the
   existing record).
9. Unauth returns 401 JSON, NOT 302 redirect.
10. No HX-Trigger header (unlike /save-run which sets
    HX-Trigger: refreshHistory).
11. Routes do NOT validate form fields strictly (no
    _validate_form call); they accept any form input as a
    snapshot.
12. Routes do NOT check for HTMX-request header; they
    respond the same way for HTMX and non-HTMX callers.

Intended persistence side effects (NOT forbidden):

- Draft:
    save_workspace_state(...) -- 1 call per success.
- Discard:
    discard_workspace_draft(...) -- 1 call per discard.
    save_workspace_state(...) -- 0-1 call as fallback when
    discard_workspace_draft returns None (only on a fresh
    project with no existing workspace_state). Note that
    discard_workspace_draft internally calls save_workspace_state
    to UPDATE the existing row, so the discard path always
    results in 1-2 writes.

Forbidden side effects (must NOT be introduced):

- record_export
- record_download_export
- record_runtime_summary_export
- record_institutional_workbook_export
- record_workspace_runtime
- update_scenario_last_run_summary
- db.add / db.commit / db.flush
- session.add / session.commit
- save_run
- save_project
- save_scenario
- model/run calculation calls
- Excel export calls
- unrelated persistence writes

Phase 51F guardrails: this module does NOT import main_web or
main_api. The engine-output golden guardrail, parity-core lock
guardrail, and no-service-imports guardrail remain green.

Backend remains source of truth. rc1 remains frozen.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional


# ─────────────────────────────────────────────────────────────────────────────
# Public dataclasses
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class ScenarioStateRouteOutcome:
    """Result of a /scenarios/state/* route orchestration.

    The route in ``main_web.py`` translates this into a FastAPI
    response via ``JSONResponse(...)`` (the only path the current
    routes use). For symmetry with the broader Phase 51 family
    the outcome also carries ``is_redirect`` and ``redirect_url``
    in case future routes need to redirect; auth is currently
    route-owned, so the service does not produce redirects itself.

    Fields:
        payload: The JSON dict that becomes the JSONResponse body.
        status_code: HTTP status code. 200 for success, 401 for
            unauth (route-owned, but included for completeness).
        headers: Extra response headers. Default empty (the
            current routes do not emit HX-Trigger or HX-Redirect).
        is_redirect: ``True`` if the route should redirect (e.g.
            unauthenticated -> /login). Currently unused (the
            routes return 401 JSON, not a redirect). Included
            for symmetry with Phase 51B/51C-2/51D-2/51E-2/51G-2.
        redirect_url: URL to redirect to (when is_redirect is
            True). Currently unused.
    """

    payload: dict = field(default_factory=dict)
    status_code: int = 200
    headers: dict = field(default_factory=dict)
    is_redirect: bool = False
    redirect_url: Optional[str] = None


@dataclass
class ScenarioStateRouteDeps:
    """Dependencies that ``execute_draft_route`` and
    ``execute_discard_route`` need from the route.

    The route in ``main_web.py`` owns these helpers; passing them
    in as callables (rather than importing from ``main_web``) keeps
    the ``main_web`` -> ``scenario_state_route_service`` import
    direction clean and lets future test code inject test doubles.

    The bundle has 9 callables (the helpers used by draft/discard
    orchestration). Constants (e.g. ``project_types``) are NOT
    needed because the scenario-state routes do not validate the
    form (quirk 11) — they accept any form input as a snapshot.
    """

    # Project / workspace resolution
    collect_form_snapshot: Callable[..., dict]
    project_workspace_from_snapshot: Callable[..., tuple]

    # Workspace_state persistence (intended writes)
    save_workspace_state: Callable[..., Any]
    discard_workspace_draft: Callable[..., Any]

    # Workspace state helpers
    snapshots_equal: Callable[..., bool]
    default_workspace_snapshot: Callable[..., dict]

    # Governance / replay metadata assembly
    governance_snapshot: Callable[..., dict]
    replay_metadata_for_project: Callable[..., dict]

    # Response assembly
    workspace_state_meta: Callable[..., dict]


# ─────────────────────────────────────────────────────────────────────────────
# Service entry points
# ─────────────────────────────────────────────────────────────────────────────


async def execute_draft_route(
    *,
    request: Any,
    form: Any,
    user: Any,
    deps: ScenarioStateRouteDeps,
) -> ScenarioStateRouteOutcome:
    """Execute the /scenarios/state/draft orchestration and return
    a ScenarioStateRouteOutcome.

    Mirrors the legacy ``save_workspace_draft_endpoint`` route
    body in main_web.py (Phase 51H-1 characterization).

    Behavior:
    - Reads form snapshot via ``deps.collect_form_snapshot(form)``.
    - Resolves project_record + existing workspace_state via
      ``deps.project_workspace_from_snapshot(user, snapshot)``.
    - Computes ``saved_snapshot``, ``active_scenario_id``,
      ``active_scenario_name`` (preserving existing values when
      a workspace_state already exists, otherwise seeding from
      form / project baseline).
    - Calls ``deps.save_workspace_state(...)`` ONCE with:
        - draft_snapshot = current form snapshot
        - saved_snapshot = existing.saved_snapshot OR project
          baseline OR default
        - dirty = not snapshots_equal(snapshot, saved_snapshot)
        - replay_metadata.export_type = "workspace_draft_state"
        - replay_metadata.scenario_id = active_scenario_id
          (when present)
    - Builds payload via ``deps.workspace_state_meta(workspace_state)``
      and adds the fixed message string.
    - Does NOT add a 'snapshot' key (draft quirk 3).
    - Does NOT set HX-Trigger, HX-Redirect, or template_name
      (draft quirks 9, 10, 14).
    """
    snapshot = deps.collect_form_snapshot(form)
    project_record, existing = deps.project_workspace_from_snapshot(user, snapshot)
    project_code = project_record.project_code
    saved_snapshot = (
        existing.saved_snapshot
        if existing
        else (project_record.baseline_snapshot or deps.default_workspace_snapshot(project_code))
    )
    active_scenario_id = (
        existing.active_scenario_id
        if existing
        else (form.get("current_saved_scenario_id", "") or None)
    )
    active_scenario_name = (
        existing.active_scenario_name if existing else None
    )
    workspace_state = deps.save_workspace_state(
        user_id=user.user_id,
        project_id=project_record.project_id,
        project_code=project_code,
        active_scenario_id=active_scenario_id,
        active_scenario_name=active_scenario_name,
        draft_snapshot=snapshot,
        saved_snapshot=saved_snapshot,
        dirty=not deps.snapshots_equal(snapshot, saved_snapshot),
        governance_state=deps.governance_snapshot(project_code),
        replay_metadata=deps.replay_metadata_for_project(
            project_code,
            project_id=project_record.project_id,
            scenario_id=active_scenario_id,
            export_type="workspace_draft_state",
        ),
    )
    payload = dict(deps.workspace_state_meta(workspace_state))
    payload["message"] = (
        "Workspace draft captured. Saved scenario authority is unchanged."
    )
    return ScenarioStateRouteOutcome(
        payload=payload,
        status_code=200,
    )


async def execute_discard_route(
    *,
    request: Any,
    form: Any,
    user: Any,
    deps: ScenarioStateRouteDeps,
) -> ScenarioStateRouteOutcome:
    """Execute the /scenarios/state/discard orchestration and return
    a ScenarioStateRouteOutcome.

    Mirrors the legacy ``discard_workspace_draft_endpoint`` route
    body in main_web.py (Phase 51H-1 characterization).

    Behavior:
    - Reads form snapshot via ``deps.collect_form_snapshot(form)``.
    - Resolves project_record via
      ``deps.project_workspace_from_snapshot(user, snapshot)``.
    - Calls ``deps.discard_workspace_draft(user.user_id,
      project_record.project_id)`` ONCE (always).
    - If discard_workspace_draft returns None, calls
      ``deps.save_workspace_state(...)`` ONCE as fallback with:
        - draft_snapshot = saved_snapshot = baseline_snapshot
        - dirty = False
        - replay_metadata.export_type = "workspace_draft_state"
    - Builds payload via ``deps.workspace_state_meta(workspace_state)``
      and adds the 'snapshot' key (= workspace_state.draft_snapshot)
      AND the fixed message string.
    - Does NOT set HX-Trigger, HX-Redirect, or template_name
      (discard quirks 9, 10, 14).
    """
    snapshot = deps.collect_form_snapshot(form)
    project_record, _ = deps.project_workspace_from_snapshot(user, snapshot)
    project_code = project_record.project_code
    workspace_state = deps.discard_workspace_draft(
        user.user_id, project_record.project_id
    )
    if workspace_state is None:
        # Quirk 6: fallback creates a clean workspace when none exists.
        baseline_snapshot = (
            project_record.baseline_snapshot
            or deps.default_workspace_snapshot(project_code)
        )
        workspace_state = deps.save_workspace_state(
            user_id=user.user_id,
            project_id=project_record.project_id,
            project_code=project_code,
            draft_snapshot=baseline_snapshot,
            saved_snapshot=baseline_snapshot,
            dirty=False,
            governance_state=deps.governance_snapshot(project_code),
            replay_metadata=deps.replay_metadata_for_project(
                project_code,
                project_id=project_record.project_id,
                export_type="workspace_draft_state",
            ),
        )
    payload = dict(deps.workspace_state_meta(workspace_state))
    # Quirk 3: discard response includes 'snapshot' key.
    payload["snapshot"] = workspace_state.draft_snapshot
    payload["message"] = (
        "Unsaved edits discarded. Workspace restored to the last "
        "saved runtime boundary."
    )
    return ScenarioStateRouteOutcome(
        payload=payload,
        status_code=200,
    )
