"""Phase 51J-2 — POST /scenarios/save route family vertical extraction.

This module owns the orchestration body that previously lived
inline in main_web.py for:

- POST /scenarios/save (save_scenario_endpoint)

The route handler in main_web.py is now a thin wrapper
(auth + form + deps bundle + service call + render). The full
orchestration (project_record / existing_workspace_state
resolution, soft-block handling, scenario_name construction,
last_run_summary preservation/reset, save_scenario kwargs
assembly and call, bind_workspace_to_scenario kwargs assembly
and call, read-only list_scenarios/get_scenario_history/list_exports
/build_export_lineage calls, scenario_summary_cards assembly with
export_count, replay_metadata/governance metadata assembly,
workspace render context assembly, success/error context
assembly) lives here.

This service does NOT import main_web or main_api. The route
in main_web.py wires the deps bundle and calls
``execute_scenarios_save_route(...)``. The service returns a
``ScenariosSaveRouteOutcome`` dataclass which the route
translates to a ``TemplateResponse`` (success or block) or
``RedirectResponse`` (auth). Auth is route-owned, so the service
does not produce redirects itself.

15 characterized behaviors preserved (Phase 51J-1):

draft
1. POST /scenarios/save exists.
2. Unauthenticated -> 302 redirect to /login (NOT 401 JSON).
3. Authenticated + valid form -> 200 + HTML workspace render.
4. Authenticated + factory_template / saved_baseline project ->
   200 + HTML workspace render with 'Save is not available' message
   (soft-block, not 4xx).
5. Authenticated + user_created (or other) project -> 200 + HTML
   workspace render with 'Saved scenario snapshot for {project_name}.'
   message (success).
6. user_id derived from session, never from form.
7. Form is collected ONCE via _collect_form_snapshot(form).
8. scenario_name is built as
   f"{project_name} {snapshot.get('scenario', 'Base')}
   {dt.now().strftime('%Y-%m-%d %H:%M')}" (timestamp IS the suffix).
9. save_scenario called exactly once per success (after the
   project_origin block check).
10. bind_workspace_to_scenario called exactly once per success
    (after save_scenario).
11. last_run_summary preserved if and only if existing_workspace_state
    exists AND its last_runtime_snapshot equals the current snapshot.
    Otherwise reset to {}.
12. replay_metadata.export_type for save_scenario =
    'saved_scenario_snapshot'.
13. replay_metadata.export_type for bind_workspace_to_scenario =
    'workspace_saved_boundary' (with non-ASCII char).
14. Response is full workspace render via _render_scenario_workspace.
15. scenario_summary_cards have 10 specific fields including
    export_count (computed per scenario_name from export_lineage).

10 characterized quirks preserved:

1. scenario_name format: timestamp is the name suffix
   (f"{project_name} {snapshot.get('scenario', 'Base')}
   {dt.now().strftime('%Y-%m-%d %H:%M')}").
2. Blocked message replaces underscores with spaces in
   project_origin (e.g. 'factory template' instead of
   'factory_template').
3. Blocked message includes the suggestion
   'Use 'Save As' to create a user project.'.
4. last_run_summary preserved if and only if
   existing_workspace_state exists AND its last_runtime_snapshot
   equals the current snapshot. Otherwise reset to {}.
5. Blocked branch is a soft-fail: 200 + workspace render with
   error message, NOT 4xx. save_scenario and
   bind_workspace_to_scenario are NEVER called in the blocked
   branch.
6. No HX-Trigger header (unlike /save-run which sets
   HX-Trigger: refreshHistory). The success response is a
   full workspace render, not an HTMX partial.
7. scenario_summary_cards.export_count is computed by
   counting entries in export_lineage per scenario_name.
8. scenario_summary_cards include 10 specific fields:
   scenario_id, scenario_name, project_code, updated_at,
   copied_from_scenario_id, project_irr, equity_irr, avg_dscr,
   export_count, governance_state.
9. Two distinct replay_metadata export_type values:
   - save_scenario uses 'saved_scenario_snapshot'
   - bind_workspace_to_scenario uses 'workspace_saved_boundary'
10. Route does NOT call _validate_form and accepts any form
    input as a snapshot. (Same as /scenarios/state/draft and
    /scenarios/state/discard.)

Intended persistence side effects (NOT forbidden):

- save_scenario(...) -- 1 call per success.
- bind_workspace_to_scenario(...) -- 1 call per success (after
  save_scenario).
- list_scenarios, get_scenario_history, list_exports,
  build_export_lineage -- 1× each per success (read-only).
- _governance_snapshot, _replay_metadata_for_project --
  2× per success (save + bind).
- _workspace_state_meta, dt.now -- 1× per success (name
  construction + metadata).

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
- direct save_workspace_state call outside bind_workspace_to_scenario
  (bind_workspace_to_scenario internally calls save_workspace_state)
- run_project / model execution
- build_institutional_workbook_export
- build_excel_export_for_post_request
- build_runtime_summary_csv_export
- build_values_only_export_for_project
- unrelated persistence writes

Phase 51F guardrails: this module does NOT import main_web or
main_api. The engine-output golden guardrail, parity-core lock
guardrail, and no-service-imports guardrail remain green.

Why a separate service module (not extending scenario_state_service.py
or scenario_state_route_service.py):

- scenario_state_service.py is data-layer only (no Request, no
  form, no auth). Adding route orchestration would mix data-layer
  and route-orchestration concerns.

- scenario_state_route_service.py handles workspace draft/discard
  mutations WITHOUT scenario row creation. /scenarios/save
  creates a new ScenarioRecord and binds workspace, which is a
  different concern.

Backend remains source of truth. rc1 remains frozen.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional


# ─────────────────────────────────────────────────────────────────────────────
# Public dataclasses
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class ScenariosSaveRouteOutcome:
    """Result of POST /scenarios/save orchestration.

    The route in ``main_web.py`` translates this into a FastAPI
    response via ``TemplateResponse(...)`` (success or block) or
    ``RedirectResponse(...)`` (auth). For symmetry with the
    broader Phase 51 family the outcome also carries
    ``is_redirect`` and ``redirect_url`` in case future routes
    need to redirect; auth is currently route-owned, so the
    service does not produce redirects itself.

    Fields:
        template_name: Jinja template to render. Default
            ``"scenarios/_workspace_partial.html"`` (the partial
            that ``_render_scenario_workspace`` returns inside).
            The route does not need to know this — it just calls
            ``_render_scenario_workspace`` via the deps.
        context: Jinja context dict. For success:
            ``{user, project_record, workspace_state, scenarios,
            history, exports, export_lineage, scenario_summary_cards,
            message}``. For block: empty scenarios/history/exports/
            lineage/cards + error message.
        status_code: HTTP status code. 200 for both success and
            block (no 4xx in either case; the route currently
            uses the workspace render for both paths).
        headers: Extra response headers. Default empty (the
            current routes do not emit HX-Trigger or HX-Redirect).
        is_redirect: ``True`` if the route should redirect (e.g.
            unauthenticated -> /login). Currently unused (the
            route returns 401 JSON in the auth path; for the
            /scenarios/save route, auth is a 302 redirect to /login
            and is route-owned, so the service does not produce
            redirects itself). Included for symmetry with Phase
            51B/51C-2/51D-2/51E-2/51G-2/51H-2.
        redirect_url: URL to redirect to (when is_redirect is
            True). Currently unused.
    """

    template_name: str = "scenarios/_workspace_partial.html"
    context: dict = field(default_factory=dict)
    status_code: int = 200
    headers: dict = field(default_factory=dict)
    is_redirect: bool = False
    redirect_url: Optional[str] = None


@dataclass
class ScenariosSaveRouteDeps:
    """Dependencies that ``execute_scenarios_save_route`` needs
    from the route.

    The route in ``main_web.py`` owns these helpers; passing them
    in as callables (rather than importing from ``main_web``) keeps
    the ``main_web`` -> ``scenarios_save_service`` import
    direction clean and lets future test code inject test doubles.

    The bundle has 13 callables. No constants are needed because
    the route does not validate the form (Quirk 10) -- it accepts
    any form input as a snapshot.
    """

    # Snapshot / project / workspace resolution
    collect_form_snapshot: Callable[..., dict]
    project_workspace_from_snapshot: Callable[..., tuple]

    # Block / soft-fail helpers (no current helper; the block check
    # is inline in the service)
    # (intentionally omitted: block check is structural and lives
    # in the service body, not as a separate helper)

    # Persistence (intended writes)
    save_scenario: Callable[..., Any]
    bind_workspace_to_scenario: Callable[..., Any]

    # Read-only queries for response render
    list_scenarios: Callable[..., Any]
    get_scenario_history: Callable[..., Any]
    list_exports: Callable[..., Any]
    build_export_lineage: Callable[..., Any]

    # Governance / replay metadata assembly
    governance_snapshot: Callable[..., dict]
    replay_metadata_for_project: Callable[..., dict]

    # Snapshot diff (for last_run_summary conditional)
    snapshots_equal: Callable[..., bool]

    # Response render
    render_scenario_workspace: Callable[..., Any]

    # Current datetime provider (allows test injection)
    # Optional: if None, the service uses ``__import__('datetime').datetime.now()``
    # Note: dt is the current alias used in main_web.py
    # (``from datetime import datetime as dt``).
    # We accept a callable that returns a datetime object so tests
    # can inject a fixed timestamp.
    utc_now: Optional[Callable[..., Any]] = None


# ─────────────────────────────────────────────────────────────────────────────
# Service entry point
# ─────────────────────────────────────────────────────────────────────────────


async def execute_scenarios_save_route(
    *,
    request: Any,
    form: Any,
    user: Any,
    deps: ScenariosSaveRouteDeps,
) -> ScenariosSaveRouteOutcome:
    """Execute the POST /scenarios/save orchestration and return
    a ScenariosSaveRouteOutcome.

    Mirrors the legacy ``save_scenario_endpoint`` route body in
    main_web.py (Phase 51J-1 characterization).

    Behavior:
    - Reads form snapshot via ``deps.collect_form_snapshot(form)``.
    - Resolves project_record + existing_workspace_state via
      ``deps.project_workspace_from_snapshot(user, snapshot)``.
    - **Soft-blocks** factory_template and saved_baseline projects:
      returns 200 + workspace render with 'Save is not available'
      message. save_scenario and bind_workspace_to_scenario are
      NOT called in this branch.
    - Computes scenario_name as
      f"{project_name} {snapshot.get('scenario', 'Base')}
      {dt.now().strftime('%Y-%m-%d %H:%M')}" (timestamp is the
      name suffix; the timestamp format is preserved exactly).
    - Calls ``deps.save_scenario(...)`` ONCE with the snapshot,
      governance state, last_run_summary (preserved if existing
      workspace state matches; otherwise reset to {}), and
      replay_metadata (export_type='saved_scenario_snapshot').
    - Calls ``deps.bind_workspace_to_scenario(...)`` ONCE after
      save_scenario with the saved_record and
      replay_metadata (export_type='workspace_saved_boundary',
      scenario_id=saved_record.scenario_id).
    - Calls read-only list_scenarios/get_scenario_history/
      list_exports/build_export_lineage ONCE each.
    - Assembles scenario_summary_cards with 10 specific fields
      including export_count (computed per scenario_name from
      export_lineage).
    - Returns the workspace render via
      ``deps.render_scenario_workspace(...)`` with the populated
      context.
    """
    snapshot = deps.collect_form_snapshot(form)
    project_record, existing_workspace_state = deps.project_workspace_from_snapshot(
        user, snapshot
    )

    # ── Block check (soft-fail) ─────────────────────────────────────
    # Quirk 2: the message replaces underscores with spaces in
    # project_origin.
    # Quirk 3: the message includes the suggestion 'Use Save As'.
    # Quirk 5: the block is a soft-fail (200 + render, not 4xx).
    if project_record.project_origin in ("factory_template", "saved_baseline"):
        block_message = (
            f"Save is not available for "
            f"{project_record.project_origin.replace('_', ' ')} "
            f"'{project_record.project_code}'. "
            f"Use 'Save As' to create a user project."
        )
        return deps.render_scenario_workspace(
            request, user, project_record, existing_workspace_state,
            [], [], [], [], [],
            message=block_message,
        )

    # ── Success branch ──────────────────────────────────────────────
    project_code = project_record.project_code
    project_name = project_record.project_name

    # Quirk 1: scenario_name format. Timestamp IS the name suffix.
    if deps.utc_now is not None:
        now = deps.utc_now()
        timestamp_str = now.strftime("%Y-%m-%d %H:%M")
    else:
        from datetime import datetime as _dt
        timestamp_str = _dt.now().strftime("%Y-%m-%d %H:%M")
    scenario_name = (
        f"{project_name} "
        f"{snapshot.get('scenario', 'Base')} "
        f"{timestamp_str}"
    )

    # Quirk 4: last_run_summary is preserved iff existing_workspace_state
    # exists AND its last_runtime_snapshot equals the current snapshot.
    last_run_summary = (
        existing_workspace_state.last_runtime_summary
        if existing_workspace_state
        and deps.snapshots_equal(
            existing_workspace_state.last_runtime_snapshot, snapshot
        )
        else {}
    )

    # Persist the new ScenarioRecord.
    saved_record = deps.save_scenario(
        user_id=user.user_id,
        project_id=project_record.project_id,
        scenario_name=scenario_name,
        project_code=project_code,
        source_project_template=(
            project_record.template_source
            or project_record.source_project_template
        ),
        snapshot=snapshot,
        governance_state=deps.governance_snapshot(project_code),
        last_run_summary=last_run_summary,
        replay_metadata=deps.replay_metadata_for_project(
            project_code,
            project_id=project_record.project_id,
            export_type="saved_scenario_snapshot",
        ),
    )

    # Bind the workspace to the new scenario.
    workspace_state = deps.bind_workspace_to_scenario(
        user.user_id,
        project_record.project_id,
        project_code,
        saved_record,
        governance_state=deps.governance_snapshot(project_code),
        replay_metadata=deps.replay_metadata_for_project(
            project_code,
            project_id=project_record.project_id,
            scenario_id=saved_record.scenario_id,
            export_type="workspace_saved_boundary",
        ),
    )

    # Read-only queries for the response render context.
    scenarios = deps.list_scenarios(
        user.user_id,
        project_id=project_record.project_id,
        include_archived=False,
        limit=12,
    )
    history = deps.get_scenario_history(
        user.user_id,
        project_id=project_record.project_id,
        limit=20,
    )
    exports = deps.list_exports(
        user.user_id,
        project_id=project_record.project_id,
        limit=8,
    )
    export_lineage = deps.build_export_lineage(
        user.user_id,
        project_id=project_record.project_id,
        limit=8,
    )

    # Quirk 7: scenario_summary_cards.export_count is computed by
    # counting entries in export_lineage per scenario_name.
    # Quirk 8: scenario_summary_cards have 10 specific fields.
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

    # Quirk 6: success response is full workspace render (no
    # HX-Trigger, no HX-Redirect, no template).
    return deps.render_scenario_workspace(
        request,
        user,
        project_record,
        workspace_state,
        scenarios,
        history,
        exports,
        export_lineage,
        scenario_summary_cards,
        message=f"Saved scenario snapshot for {project_name}.",
    )
