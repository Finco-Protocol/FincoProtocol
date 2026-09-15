"""Phase 51G-2 — Vertical extraction of POST /save-run orchestration.

This module owns the orchestration body that previously lived inside
the ``@app.post("/save-run")`` route handler in ``main_web.py``.

The route is now thin: it authenticates the user, parses the form,
collects the snapshot, calls ``execute_save_run_route(...)`` and
renders the returned ``SaveRunRouteOutcome`` via the existing
FastAPI / Jinja / HTMX rendering path.

Why ``SaveRunRouteOutcome`` (return value) instead of building a
Response here:
- The route in ``main_web.py`` owns the FastAPI ``Request`` and
  the ``Jinja2Templates`` instance. Passing a ``Response`` across
  that boundary forces the service to depend on FastAPI internals,
  which would couple the service to the web framework and
  complicate future unit testing.
- Returning a plain dataclass keeps the service free of framework
  dependencies, and the route is the only place that calls
  ``templates.TemplateResponse(...)`` and
  ``RedirectResponse(...)``.

This module does NOT import ``main_web``. All helper functions
that the route in ``main_web.py`` still owns
(``_collect_form_snapshot``, ``_project_workspace_from_snapshot``,
``_canonical_project_type``, ``_build_schema_from_form``,
``_normalize_template_source``, ``_replay_metadata_for_project``,
``_governance_snapshot``, ``_validate_form``) are passed in as
callable dependencies by the route. The model execution
(``run_project``) and persistence (``save_run``, ``save_project``)
are also passed in as deps. The service does NOT import them.
``utc_now_iso`` is passed in as a dep so the service is free of
clock coupling. ``PROJECT_TYPES`` and ``SCENARIOS`` constants are
also passed in as deps (the route reads them from main_web scope).

This keeps the import direction clean (``main_web`` ->
``save_run_service`` and never the reverse).

Phase 51G-2 explicitly preserves the 15 documented behaviors and
7 quirks that Phase 51G-1 characterized:

15 characterized behaviors preserved:
1. POST /save-run exists and remains functional.
2. Unauthenticated request redirects 302 to /login (route-owned).
3. Auth + dirty/empty state returns 200 + save_result-err +
   HX-Trigger: refreshHistory.
4. Auth + factory_template origin + valid form returns 200 +
   save_result-ok + HX-Trigger.
5. user_id derived from session, never from form.
6. Form fields exactly: capacity_mw, tariff_eur_mwh, p50_hours,
   total_capex_keur, opex_y1_keur, gearing_pct, target_dscr,
   interest_rate_pct, tenor_years.
7. Project code and name come from project_record, not form.
8. effective_project_type = project_record.project_type or
   form.project_type.
9. check_runtime_allowed unpacks 3-tuple: allow_run,
   runtime_origin, guard_message.
10. Two model-execution branches: user_created and
    factory_template.
11. factory_template branch maps template_source to runtime key
    (generic_wind_reference / generic_solar_reference / Solar / Wind).
12. Model execution wrapped in broad except Exception.
13. save_run called first, save_project second.
14. save_project.runtime_timestamp = run_record.created_at
    .isoformat(), not utc_now_iso().
15. All 4 non-auth responses use partials/save_result.html +
    HX-Trigger: refreshHistory.

7 characterized quirks preserved:
1. (RESOLVED in 51G-3) The user_created branch previously
   referenced ``_clean_user_project_runtime_snapshot`` which was
   not defined anywhere, causing a NameError on every save for
   user_created projects. Phase 51G-3 fixes this by introducing
   ``deps.clean_user_project_runtime_snapshot`` (injected from
   ``main_web._clean_user_project_runtime_snapshot``). The fix is
   a small, narrow adapter that delegates to the existing
   ``_resolve_runtime_snapshot_source`` (Phase 50C-2) and returns
   the snapshot dict that ``build_projectinputs_from_snapshot``
   consumes. The fix does not introduce any new persistence side
   effects, does not change factory_template behavior, does not
   change save_run/save_project ordering, and does not change
   replay_metadata export_type values.
2. runtime_origin captured but not used to mutate state.
3. save_project.runtime_timestamp = run_record.created_at, not
   utc_now_iso.
4. save_project.replay_metadata.project_id explicitly None.
5. All 4 non-auth responses use same partial template.
6. _validate_form uses hardcoded PROJECT_TYPES / SCENARIOS sets.
7. save_run before save_project (ordering).

Intended runtime persistence side effects (NOT forbidden):
- ``save_run(...)`` — 1 call per success → ``RunRecord`` row.
  ``replay_metadata.export_type = "saved_run_metadata"``.
- ``save_project(...)`` — 1 call per success →
  ``ProjectRecord.last_run_summary`` update.
  ``replay_metadata.export_type = "saved_run_project_state"``.
- Order: save_run FIRST, then save_project.
- save_project.runtime_timestamp = run_record.created_at
  .isoformat() (locked to run timestamp).
- save_project.replay_metadata.project_id is explicitly None.

Forbidden side effects (must NOT be introduced):
- ``record_export``
- ``record_download_export``
- ``record_runtime_summary_export``
- ``record_institutional_workbook_export``
- ``record_workspace_runtime``
- ``update_scenario_last_run_summary``
- ``db.add`` / ``db.commit`` / ``db.flush``
- ``session.add`` / ``session.commit``

The /save-run service does NOT call any of the forbidden helpers.
It only calls ``save_run`` + ``save_project`` (intended runtime
persistence) + ``run_project`` (in-memory model exec).

Phase 51G-3: the user_created branch now reaches run_project
+ save_run + save_project on the success path. The model-execution
``except Exception`` still wraps the entire branch (Behavior 12),
so a malformed snapshot raises ``SnapshotInputError`` from
``build_projectinputs_from_snapshot`` and the service surfaces
that as a 200 + save_result-err with the message, not a NameError.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional


# ─────────────────────────────────────────────────────────────────────────────
# Public dataclasses
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class SaveRunRouteOutcome:
    """Result of POST /save-run orchestration.

    The route in ``main_web.py`` translates this into a FastAPI
    response via ``templates.TemplateResponse(...)`` (success or
    error) or ``RedirectResponse(...)`` (unauthenticated — but auth
    is route-owned so this case is typically not produced by the
    service).

    Fields:
        template_name: Jinja template to render. Default
            ``"partials/save_result.html"`` (the only template the
            service emits for non-auth responses).
        context: Jinja context dict. For success:
            ``{success: True, run_id, project_type, scenario,
            created_at}``. For error:
            ``{success: False, error}``.
        status_code: HTTP status code. Always 200 (HTMX partial —
            not a real HTTP error). The route may override if
            needed.
        headers: Extra response headers. Default includes
            ``HX-Trigger: refreshHistory`` (HTMX refresh hook).
        is_redirect: ``True`` if the route should redirect (e.g.
            unauthenticated → /login). Auth is route-owned, so the
            service typically does not produce this; included for
            symmetry with the Phase 51B/51C-2/51D-2/51E-2 pattern.
        redirect_url: URL to redirect to (when is_redirect is
            True). Typically ``/login``.
    """

    template_name: str = "partials/save_result.html"
    context: dict = field(default_factory=dict)
    status_code: int = 200
    headers: dict = field(
        default_factory=lambda: {"HX-Trigger": "refreshHistory"}
    )
    is_redirect: bool = False
    redirect_url: Optional[str] = None


@dataclass
class SaveRunRouteDeps:
    """Dependencies that ``execute_save_run_route`` needs from the
    route.

    The route in ``main_web.py`` owns these helpers; passing them
    in as callables (rather than importing from ``main_web``) keeps
    the ``main_web`` -> ``save_run_service`` import direction
    clean and lets future test code inject test doubles.

    The bundle has 16 callables + 2 constants.
    """

    # Snapshot / project / runtime guard
    project_workspace_from_snapshot: Callable[..., tuple]
    check_runtime_allowed: Callable[..., tuple]

    # Validation (uses PROJECT_TYPES / SCENARIOS — both passed in)
    validate_form: Callable[..., bool]
    project_types: list
    scenarios: list

    # User_created branch
    # Phase 51G-3: clean_user_project_runtime_snapshot is now an
    # explicit dep. Prior to 51G-3, the service referenced a module-
    # level ``_clean_user_project_runtime_snapshot`` symbol that was
    # not defined anywhere, causing a NameError on every save for
    # user_created projects. See docstring on
    # ``execute_save_run_route`` and the Phase 51G-1 / 51G-2 history.
    clean_user_project_runtime_snapshot: Callable[..., dict]
    canonical_project_type: Callable[..., str]
    build_projectinputs_from_snapshot: Callable[..., Any]

    # Factory_template branch
    build_schema_from_form: Callable[..., Any]
    build_projectinputs: Callable[..., Any]
    normalize_template_source: Callable[..., str]

    # Model execution
    run_project: Callable[..., Any]

    # Persistence (INTENDED — these are the only persistence writes
    # on the /save-run path)
    save_run: Callable[..., Any]
    save_project: Callable[..., Any]

    # Replay / governance / timestamp
    replay_metadata_for_project: Callable[..., dict]
    governance_snapshot: Callable[..., dict]
    utc_now_iso: Callable[..., str]


# ─────────────────────────────────────────────────────────────────────────────
# Service entry point
# ─────────────────────────────────────────────────────────────────────────────

async def execute_save_run_route(
    *,
    request: Any,
    form: Any,
    user: Any,
    snapshot: dict,
    deps: SaveRunRouteDeps,
) -> SaveRunRouteOutcome:
    """Execute the /save-run orchestration and return a
    ``SaveRunRouteOutcome``.

    Parameters
    ----------
    request
        The FastAPI ``Request`` (or any object the route passes
        through). The service does not currently use it directly,
        but it is part of the Phase 51B/51C-2/51D-2/51E-2 entry
        point signature for symmetry.
    form
        An async form result (``await request.form()``). The
        service extracts 9 form fields plus ``project_type`` and
        ``scenario`` from this object.
    user
        The authenticated user object (must have ``user_id``).
    snapshot
        The form snapshot dict (from
        ``_collect_form_snapshot(form)``). The route computes this
        before calling the service so that the service does not
        depend on ``_collect_form_snapshot``.
    deps
        Bundle of dependencies from the route. See
        ``SaveRunRouteDeps``.

    Returns
    -------
    SaveRunRouteOutcome
        Dataclass describing the response template, context, and
        headers. The route translates this into a FastAPI response.

    Notes
    -----
    Behavior preservation: this function preserves the exact
    sequence and call shape of the original /save-run route from
    main_web.py:2624-2760 (Phase 51G-1 characterization baseline).
    See ``docs/phase51g1_save_run_route_golden_characterization.md``
    for the full behavior map.
    """
    # ── 1. Snapshot + project/workspace resolution ──────────────────
    project_record, workspace_state = deps.project_workspace_from_snapshot(
        user, snapshot
    )
    project_code = project_record.project_code
    project_name = project_record.project_name

    # ── 2. Runtime guard ─────────────────────────────────────────────
    allow_run, runtime_origin, guard_message = deps.check_runtime_allowed(
        workspace_state, snapshot
    )
    if not allow_run:
        # Quirk 5: All 4 non-auth responses use save_result.html
        # partial + HX-Trigger: refreshHistory
        return SaveRunRouteOutcome(
            context={"success": False, "error": guard_message},
        )

    # ── 3. user_id from session (NEVER from form) ────────────────────
    # Quirk 0: never trust user_id from client; always derive from session
    user_id = user.user_id

    # ── 4. Build inputs dict (exactly 9 fields) ──────────────────────
    inputs = {
        "capacity_mw": form.get("capacity_mw", ""),
        "tariff_eur_mwh": form.get("tariff_eur_mwh", ""),
        "p50_hours": form.get("p50_hours", ""),
        "total_capex_keur": form.get("total_capex_keur", ""),
        "opex_y1_keur": form.get("opex_y1_keur", ""),
        "gearing_pct": form.get("gearing_pct", ""),
        "target_dscr": form.get("target_dscr", ""),
        "interest_rate_pct": form.get("interest_rate_pct", ""),
        "tenor_years": form.get("tenor_years", ""),
    }

    # ── 5. Validate form (uses hardcoded PROJECT_TYPES / SCENARIOS) ─
    # Quirk 6: validate_form uses hardcoded PROJECT_TYPES / SCENARIOS
    project_type = form.get("project_type", "")
    scenario = form.get("scenario", "")
    errors: list[str] = []
    effective_project_type = project_record.project_type or project_type
    if not deps.validate_form(
        effective_project_type, scenario, errors
    ):
        return SaveRunRouteOutcome(
            context={
                "success": False,
                "error": errors[0] if errors else "Invalid form",
            },
        )

    # ── 6. Model execution (branched) ───────────────────────────────
    # Behavior 10: two branches (user_created vs factory_template)
    # Behavior 11: factory_template maps template_source → runtime key
    # Behavior 12: model wrapped in broad except Exception
    try:
        if project_record.project_origin == "user_created":
            # ── user_created branch ──────────────────────────────
            # Phase 51G-3 bugfix: previously this branch referenced
            # ``_clean_user_project_runtime_snapshot`` (a module-level
            # symbol that was never defined) and so failed with a
            # NameError on every save for user_created projects. The
            # actual implementation now lives in
            # ``main_web._clean_user_project_runtime_snapshot`` and is
            # injected as ``deps.clean_user_project_runtime_snapshot``.
            # See:
            # - Phase 51G-1 characterization: test_user_created_branch_has_latent_name_error
            # - Phase 51G-2 extraction (preserved the bug as a quirk)
            # - Phase 51G-3 fix: this branch now reaches run_project
            #   / save_run / save_project on the success path.
            runtime_snapshot = deps.clean_user_project_runtime_snapshot(
                user, project_record, workspace_state, runtime_origin
            )
            override = deps.build_projectinputs_from_snapshot(runtime_snapshot)
            runtime_project_key = (
                "Solar"
                if deps.canonical_project_type(effective_project_type) == "Solar"
                else "Wind"
            )
        else:
            # ── factory_template branch ─────────────────────────
            schema = deps.build_schema_from_form(
                effective_project_type, scenario,
                inputs.get("capacity_mw"), inputs.get("tariff_eur_mwh"),
                inputs.get("p50_hours"), inputs.get("total_capex_keur"),
                inputs.get("opex_y1_keur"), inputs.get("gearing_pct"),
                inputs.get("target_dscr"), inputs.get("interest_rate_pct"),
                inputs.get("tenor_years"),
            )
            override = deps.build_projectinputs(schema)
            runtime_seed = deps.normalize_template_source(
                project_record.template_source
                or project_record.source_project_template,
                effective_project_type,
            )
            if runtime_seed == "generic_wind_reference":
                runtime_project_key = "Generic Wind Reference"
            elif runtime_seed == "generic_solar_reference":
                runtime_project_key = "Generic Solar Reference"
            else:
                runtime_project_key = (
                    "Solar"
                    if deps.canonical_project_type(effective_project_type) == "Solar"
                    else "Wind"
                )
        result = deps.run_project(
            runtime_project_key, scenario, project_inputs_override=override
        )
        kpis = result["kpis"]
    except Exception as e:
        return SaveRunRouteOutcome(
            context={"success": False, "error": f"Model error: {str(e)}"},
        )

    # ── 7. Persistence (INTENDED writes) ────────────────────────────
    # Behavior 13: save_run first, then save_project (ordering pinned)
    # Quirk 7: save_run before save_project
    try:
        run_record = deps.save_run(
            user_id=user_id,
            project_type=effective_project_type,
            scenario=scenario,
            inputs=inputs,
            kpis=kpis,
            replay_metadata=deps.replay_metadata_for_project(
                project_code,
                export_type="saved_run_metadata",
                runtime_timestamp=deps.utc_now_iso(),
            ),
        )
        # Quirk 3: save_project.runtime_timestamp = run_record.created_at
        # (NOT utc_now_iso) — locked to run timestamp
        # Quirk 4: project_id explicitly None
        deps.save_project(
            user_id=user_id,
            project_code=project_code,
            project_name=project_name,
            source_project_template=project_code,
            governance_state=deps.governance_snapshot(project_code),
            last_run_summary=kpis,
            replay_metadata=deps.replay_metadata_for_project(
                project_code,
                project_id=None,
                export_type="saved_run_project_state",
                runtime_timestamp=run_record.created_at.isoformat(),
            ),
        )
        # ── 8. Success response ───────────────────────────────────
        return SaveRunRouteOutcome(
            context={
                "success": True,
                "run_id": run_record.run_id,
                "project_type": effective_project_type,
                "scenario": scenario,
                "created_at": run_record.created_at.isoformat(),
            },
        )
    except Exception as e:
        return SaveRunRouteOutcome(
            context={"success": False, "error": f"Save failed: {str(e)}"},
        )
