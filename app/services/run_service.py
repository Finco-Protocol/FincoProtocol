"""Phase 51B — Vertical extraction of POST /run orchestration.

This module owns the orchestration body that previously lived inside the
``@app.post("/run")`` route handler in ``main_web.py``.

The route is now thin: it authenticates the user, parses the form, calls
``execute_run_route(...)`` and renders the returned ``RunRouteOutcome`` via
the existing FastAPI / Jinja rendering path.

Why ``RunRouteOutcome`` (return value) instead of building a Response here:
- The route in ``main_web.py`` owns the FastAPI ``Request`` and the
  ``Jinja2Templates`` instance. Passing a ``Response`` across that boundary
  forces the service to depend on FastAPI internals, which would couple
  the service to the web framework and complicate future unit testing.
- Returning a plain dataclass keeps the service free of framework
  dependencies, and the route is the only place that calls
  ``templates.TemplateResponse(...)`` and ``HTMLResponse(...)``.

This module does NOT import ``main_web``. All helper functions that the
route in ``main_web.py`` still owns (``_build_schema_from_form``,
``_format_kpis``, ``_replay_metadata_for_project``, etc.) are passed in as
callable dependencies by the route. This keeps the import direction clean
(``main_web`` -> ``run_service`` and never the reverse).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Mapping, Optional

from app.utils.script_json import dumps_for_script as _dumps_for_script


@dataclass
class RunRouteOutcome:
    """Result of POST /run orchestration.

    The route in ``main_web.py`` translates this into a FastAPI response.
    ``prepend_html`` is the sessionStorage save script that is prepended
    to ``partials/runtime_summary.html`` outputs (it must be prepended at
    the bytes level, not as Jinja context, so the service cannot put it
    inside ``context``).
    """

    template_name: str
    context: dict
    status_code: int = 200
    prepend_html: Optional[str] = None
    headers: dict = field(default_factory=dict)


# ─────────────────────────────────────────────────────────────────────────────
# Service entry point
# ─────────────────────────────────────────────────────────────────────────────


async def execute_run_route(
    *,
    request: RequestLike,
    form: FormLike,
    user: Any,
    deps: "RunRouteDeps",
) -> RunRouteOutcome:
    """Execute the /run orchestration and return a ``RunRouteOutcome``.

    Parameters
    ----------
    request
        A FastAPI ``Request`` (or any object exposing ``.url.path`` and
        a session-cookie friendly interface). The service does not use it
        for anything other than passing through to ``templates.TemplateResponse``;
        it is provided as a hook for the route to wire up its own request
        context.
    form
        An async form result (``await request.form()``). The service
        extracts form fields from this object.
    user
        The authenticated user object (must have ``user_id``).
    deps
        Bundle of dependencies from the route (helpers, persistence
        functions, runtime-resolution helper). See ``RunRouteDeps``.
    """
    # ── 1. Form parsing ─────────────────────────────────────────────────
    active_project = form.get("active_project", "").strip().lower()  # type: ignore[arg-type]
    project_type = form.get("project_type", "")
    scenario = form.get("scenario", "")
    scenario_id_from_form = form.get("scenario_id", "")
    capacity_mw = form.get("capacity_mw", "")
    tariff_eur_mwh = form.get("tariff_eur_mwh", "")
    p50_hours = form.get("p50_hours", "")
    total_capex_keur = form.get("total_capex_keur", "")
    opex_y1_keur = form.get("opex_y1_keur", "")
    gearing_pct = form.get("gearing_pct", "")
    target_dscr = form.get("target_dscr", "")
    interest_rate_pct = form.get("interest_rate_pct", "")
    tenor_years = form.get("tenor_years", "")

    # ── 2. Snapshot + project/workspace resolution ───────────────────────
    snapshot = deps.collect_form_snapshot(form)
    project_record, workspace_state = deps.project_workspace_from_snapshot(user, snapshot)
    project_code = project_record.project_code
    project_name = project_record.project_name

    # ── 2b. PILOT-HOTFIX-2: Auto-select scenario from form. ─────────────
    # Bug: prior to this fix, ``/run`` always read
    # ``workspace_state.active_scenario_id`` for the runtime snapshot.
    # If the user picked Downside from the dropdown without first
    # POSTing ``/scenarios/{id}/select``, ``active_scenario_id``
    # stayed on the Base scenario, and the runtime produced Base
    # results (no override applied). This hook honours the form's
    # ``scenario_id`` so a /run after /scenarios/save reflects the
    # override without a separate /scenarios/{id}/select call.
    # - User-created projects only.
    # - Skip when form lacks scenario_id (let the existing path run).
    # - Skip when active_scenario_id already matches.
    # - When auto-select succeeds, also update ``saved_snapshot`` to
    #   the active scenario's resolved snapshot so the runtime guard
    #   (§3) treats the form mismatch as an intentional scenario
    #   override rather than a stale draft. The form-state vs.
    #   runtime-boundary contract is preserved for the Base case
    #   (saved_snapshot stays at base values); only the auto-select
    #   path explicitly synchronises the bound snapshot.
    if (
        project_record.project_origin == "user_created"
        and scenario_id_from_form
        and (workspace_state is None
             or workspace_state.active_scenario_id != scenario_id_from_form)
    ):
        from app.persistence.scenarios_repository import (
            select_scenario,
            get_scenario as _get_scenario_for_select,
        )
        _target_scenario = _get_scenario_for_select(
            scenario_id_from_form, user.user_id,
        )
        if (
            _target_scenario is not None
            and _target_scenario.project_id == project_record.project_id
            and not _target_scenario.archived
        ):
            select_scenario(
                user.user_id, project_record.project_id, scenario_id_from_form,
            )
            # Refresh workspace_state so the snapshot resolver below
            # sees the newly-active scenario.
            project_record, workspace_state = deps.project_workspace_from_snapshot(
                user, snapshot,
            )
            # Synchronise saved_snapshot to the form snapshot so the
            # runtime guard (§3) accepts the boundary. We mirror the
            # form's view (including any 'scenario' / 'scenario_id'
            # fields the form may have submitted) so that
            # ``snapshots_equal(saved, current)`` holds and the guard
            # returns ``runtime_origin='saved_state'``. The scenario's
            # resolved snapshot (base + override) is still used for
            # the actual runtime run via ``resolve_runtime_snapshot_source``
            # (which reads ``active_scenario_id``). The next /save
            # overwrites this with the canonical workspace state.
            from app.persistence.repository import save_workspace_state
            _form_synced_snap = dict(snapshot or {})
            _form_synced_snap.setdefault(
                "project_name", project_record.project_name,
            )
            _form_synced_snap.setdefault(
                "project_type", project_record.project_type,
            )
            _form_synced_snap.setdefault(
                "project_origin", project_record.project_origin,
            )
            _form_synced_snap.setdefault(
                "template_source",
                project_record.template_source
                or project_record.source_project_template,
            )
            _form_synced_snap.setdefault(
                "active_project", project_record.project_code.lower(),
            )
            save_workspace_state(
                user_id=user.user_id,
                project_id=project_record.project_id,
                project_code=project_record.project_code,
                active_scenario_id=scenario_id_from_form,
                active_scenario_name=_target_scenario.scenario_name,
                draft_snapshot=_form_synced_snap,
                saved_snapshot=_form_synced_snap,
                last_runtime_snapshot=(
                    workspace_state.last_runtime_snapshot
                    if workspace_state else {}
                ),
                last_runtime_summary=(
                    workspace_state.last_runtime_summary
                    if workspace_state else {}
                ),
                last_runtime_snapshot_id=(
                    workspace_state.last_runtime_snapshot_id
                    if workspace_state else None
                ),
                last_runtime_origin=(
                    workspace_state.last_runtime_origin
                    if workspace_state else None
                ),
                last_runtime_scenario_id=(
                    workspace_state.last_runtime_scenario_id
                    if workspace_state else None
                ),
                dirty=False,
            )
            project_record, workspace_state = deps.project_workspace_from_snapshot(
                user, snapshot,
            )

    # ── 3. Runtime guard ────────────────────────────────────────────────
    allow_run, runtime_origin, guard_message = deps.check_runtime_allowed(workspace_state, snapshot)
    if not allow_run:
        return RunRouteOutcome(
            template_name="partials/errors.html",
            context={"errors": [guard_message]},
        )

    # ── 4. Runtime snapshot resolution ──────────────────────────────────
    runtime_seed = deps.normalize_template_source(
        project_record.template_source or project_record.source_project_template,
        project_record.project_type,
    )
    runtime_snapshot: Optional[dict] = None
    active_scenario_record = None
    runtime_warning: Optional[str] = None
    effective_runtime_origin = runtime_origin
    if (runtime_origin == "saved_state" and workspace_state.active_scenario_id) \
            or project_record.project_origin == "user_created":
        runtime_snapshot, active_scenario_record, runtime_warning, effective_runtime_origin = \
            deps.resolve_runtime_snapshot_source(
                user, project_record, workspace_state, runtime_origin,
            )

    # ── 5. Three execution paths ────────────────────────────────────────
    # Phase 51B: order and bodies preserved exactly from the original
    # /run route. Only the wrapper code (record/persistence calls) was
    # delegated to helper closures to remove repetition.
    if project_record.project_origin == "user_created":
        # CAPEX-PERSIST-1: persist any CAPEX sub-line form edits before
        # running, so the fold step in _execute_user_created_path
        # picks up the latest values. Phase 57A-8 temporary rows
        # (no name attr) are not submitted and remain non-persisted.
        from app.services.capex_sub_lines_integration import (
            persist_sub_line_form_edits,
        )
        persist_sub_line_form_edits(project_record.project_id, form)
        return await _execute_user_created_path(
            request=request, user=user, snapshot=snapshot, scenario=scenario,
            project_record=project_record, workspace_state=workspace_state,
            runtime_snapshot=runtime_snapshot, active_scenario_record=active_scenario_record,
            runtime_warning=runtime_warning,
            runtime_origin=runtime_origin, effective_runtime_origin=effective_runtime_origin,
            runtime_seed=runtime_seed,
            deps=deps,
        )

    if runtime_seed in {"generic_wind_reference", "generic_solar_reference"}:
        return await _execute_template_seeded_path(
            request=request, user=user, snapshot=snapshot, scenario=scenario,
            project_record=project_record, workspace_state=workspace_state,
            runtime_snapshot=runtime_snapshot, active_scenario_record=active_scenario_record,
            runtime_warning=runtime_warning, runtime_origin=runtime_origin,
            capacity_mw=capacity_mw, tariff_eur_mwh=tariff_eur_mwh, p50_hours=p50_hours,
            total_capex_keur=total_capex_keur, opex_y1_keur=opex_y1_keur,
            gearing_pct=gearing_pct, target_dscr=target_dscr, interest_rate_pct=interest_rate_pct,
            tenor_years=tenor_years, runtime_seed=runtime_seed, deps=deps,
        )

    # Generic template-seeded path
    return await _execute_generic_path(
        request=request, user=user, snapshot=snapshot, scenario=scenario,
        project_record=project_record, workspace_state=workspace_state,
        runtime_snapshot=runtime_snapshot, active_scenario_record=active_scenario_record,
        runtime_warning=runtime_warning, runtime_origin=runtime_origin,
        project_type=project_type, capacity_mw=capacity_mw, tariff_eur_mwh=tariff_eur_mwh,
        p50_hours=p50_hours, total_capex_keur=total_capex_keur, opex_y1_keur=opex_y1_keur,
        gearing_pct=gearing_pct, target_dscr=target_dscr, interest_rate_pct=interest_rate_pct,
        tenor_years=tenor_years, deps=deps,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Dependencies bundle (DI for helpers still in main_web.py)
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class RunRouteDeps:
    """Dependencies that ``execute_run_route`` needs from the route.

    The route in ``main_web.py`` owns these helpers; passing them in as
    callables (rather than importing from ``main_web``) keeps the
    ``main_web`` -> ``run_service`` import direction clean and lets
    future test code inject test doubles.
    """

    # Form/snapshot helpers
    collect_form_snapshot: Callable[[Any], dict]
    project_workspace_from_snapshot: Callable[[Any, dict], tuple]
    normalize_template_source: Callable[..., str]
    canonical_project_type: Callable[[Any], str]

    # Runtime guard + resolution
    check_runtime_allowed: Callable[..., tuple]
    resolve_runtime_snapshot_source: Callable[..., tuple]

    # Schema build + validation
    build_schema_from_form: Callable[..., Any]
    validate_form: Callable[[str, str, list], bool]
    format_kpis: Callable[[dict], list]
    default_workspace_snapshot: Callable[[str], dict]

    # Replay + governance
    replay_metadata_for_project: Callable[..., dict]
    governance_snapshot: Callable[..., dict]
    scenario_provenance_for_record: Callable[..., Any]

    # Model execution
    run_project: Callable[..., dict]

    # Snapshot -> project inputs adapter
    build_projectinputs: Callable[..., Any]
    build_projectinputs_from_snapshot: Callable[..., Any]

    # Persistence
    record_workspace_runtime: Callable[..., Any]
    update_scenario_last_run_summary: Callable[..., Any]

    # Summary serializer
    runtime_summary_to_dict: Callable[..., dict]

    # Snapshot error class (for narrow except in user_created path)
    snapshot_input_error: type


# ─────────────────────────────────────────────────────────────────────────────
# Path implementations
# ─────────────────────────────────────────────────────────────────────────────


async def _execute_user_created_path(
    *,
    request,
    user,
    snapshot: dict,
    scenario: str,
    project_record,
    workspace_state,
    runtime_snapshot: Optional[dict],
    active_scenario_record,
    runtime_warning: Optional[str],
    runtime_origin: str,
    effective_runtime_origin: str,
    runtime_seed: str = "",
    deps: RunRouteDeps,
) -> RunRouteOutcome:
    """User-created project run path (Phase 17C snapshot binding).

    Body is preserved **byte-for-byte** with the legacy /run user_created
    branch. The only thing that changes is that the route in main_web.py
    no longer contains this code.
    """
    try:
        # Y3: when a user-created project was seeded from Generic Wind Reference/Generic Solar Reference, start
        # from the factory base so calibrated configuration (SHL mechanics,
        # equity_irr_method, frozen DS schedule, tax params) is preserved.
        # Snapshot scalar values are applied on top via _resolve_user_inputs.
        _seed_base_uc = (
            _get_seed_base_inputs(runtime_seed)
            if runtime_seed in {"generic_wind_reference", "generic_solar_reference"} else None
        )
        if _seed_base_uc is not None and runtime_snapshot is not None:
            from app.input_adapter import _resolve_user_inputs as _rui, _snapshot_to_dict as _s2d
            override = _rui(base_inputs=_seed_base_uc, **_s2d(runtime_snapshot))
            from app.services.reference_seed_service import restore_reference_seed_technical_authority
            override = restore_reference_seed_technical_authority(override, runtime_snapshot)
        else:
            override = deps.build_projectinputs_from_snapshot(runtime_snapshot)

        # Phase 57A-9D: fold persisted user-added CAPEX
        # sub-lines into the input CapexStructure. This
        # is the explicit Run/materialization boundary.
        # It runs ONLY in the user-created path — factory
        # / template-seeded paths (Generic Wind Reference, Generic Solar Reference, Generic
        # Solar, Generic Wind) do NOT call this helper.
        # 57A-8 in-memory preview rows are NOT persisted,
        # so they cannot leak in here.
        if active_scenario_record is not None:
            _scenario_overrides_for_fold = (
                active_scenario_record.overrides
            )
        else:
            _scenario_overrides_for_fold = None
        # CAPEX-PERSIST-1: use replace-semantics fold so sub-line amounts
        # ARE the category total (not added on top of the base).
        # Generic Wind Reference/Generic Solar Reference short-circuit (no sub-lines) is preserved.
        from app.services.capex_sub_lines_integration import (
            apply_user_sub_lines_replacing_base,
        )
        folded_capex = apply_user_sub_lines_replacing_base(
            override.capex,
            project_id=project_record.project_id,
            scenario_overrides=_scenario_overrides_for_fold,
        )
        if folded_capex is not override.capex:
            # The fold produced a new CapexStructure (it
            # is frozen, so it had to). Replace the
            # override's capex with the folded one.
            from dataclasses import replace as _dc_replace
            override = _dc_replace(override, capex=folded_capex)

        # STAB-1A: fold persisted OPEX custom sub-lines into
        # the input opex tuple. Additive: each active sub-line
        # becomes a new OpexItem appended to the existing tuple.
        # B.09 "Fees" (no registry field) is the primary use
        # case — sub-lines create new costs where there were none.
        # The contingency OpexItem (percentage_of_opex) is
        # recomputed by the engine over the updated tuple.
        from app.services.opex_sub_lines_integration import (
            apply_user_sub_lines_to_opex,
        )
        folded_opex = apply_user_sub_lines_to_opex(
            override.opex,
            project_id=project_record.project_id,
            scenario_overrides=_scenario_overrides_for_fold,
        )
        if folded_opex is not override.opex:
            from dataclasses import replace as _dc_replace  # noqa: F811
            override = _dc_replace(override, opex=folded_opex)

        scenario_name = (
            (runtime_snapshot.get("scenario") if runtime_snapshot else None)
            or snapshot.get("scenario", "")
            or "Base"
        )
        runtime_project_key = (
            "Solar"
            if (runtime_snapshot.get("project_type") or project_record.project_type or "").strip().lower() == "solar"  # type: ignore[union-attr]
            else "Wind"
        )
        result = deps.run_project(runtime_project_key, scenario_name, project_inputs_override=override)
        kpis = deps.format_kpis(result["kpis"])
        runtime_summary = deps.runtime_summary_to_dict(result, project_record.project_code, project_record.project_name)
        runtime_snapshot_id = _utc_now_iso_compact()
        scenario_provenance = deps.scenario_provenance_for_record(project_record, active_scenario_record)
        bound_scenario_id = active_scenario_record.scenario_id if active_scenario_record else None
        bound_scenario_name = active_scenario_record.scenario_name if active_scenario_record else None

        # Persist (note: legacy /run passes runtime_snapshot through unchanged here;
        # the gate is only applied for the template-seeded and generic paths).
        replay_metadata = deps.replay_metadata_for_project(
            project_record.project_code,
            project_id=project_record.project_id,
            scenario_id=bound_scenario_id if effective_runtime_origin == "saved_state" else None,
            scenario_name=active_scenario_record.scenario_name if active_scenario_record else scenario_name,
            runtime_timestamp=_utc_now_iso_full_iso(),
            runtime_snapshot_id=runtime_snapshot_id,
            export_type="workspace_runtime_state",
            active_scenario_id=bound_scenario_id if effective_runtime_origin == "saved_state" else None,
            active_scenario_name=bound_scenario_name if effective_runtime_origin == "saved_state" else None,
            scenario_provenance=scenario_provenance,
            warning_note=runtime_warning,
        )
        deps.record_workspace_runtime(
            user_id=user.user_id,
            project_id=project_record.project_id,
            project_code=project_record.project_code,
            runtime_snapshot=runtime_snapshot,
            runtime_summary=result["kpis"],
            runtime_snapshot_id=runtime_snapshot_id,
            runtime_origin=effective_runtime_origin,
            governance_state=deps.governance_snapshot(project_record.project_code),
            active_scenario_id=bound_scenario_id if effective_runtime_origin == "saved_state" else None,
            active_scenario_name=bound_scenario_name if effective_runtime_origin == "saved_state" else None,
            replay_metadata=replay_metadata,
            financial_statements=result.get("financial_statements"),
            debt_schedule=result.get("debt_schedule"),
            tax_schedule=result.get("tax_schedule"),
            distribution_schedule=result.get("distribution_schedule"),
            sponsor_schedule=result.get("sponsor_schedule"),
        )
        if effective_runtime_origin == "saved_state" and bound_scenario_id:
            scenario_replay = deps.replay_metadata_for_project(
                project_record.project_code,
                project_id=project_record.project_id,
                scenario_id=workspace_state.active_scenario_id,
                scenario_name=active_scenario_record.scenario_name if active_scenario_record else scenario_name,
                runtime_timestamp=_utc_now_iso_full_iso(),
                runtime_snapshot_id=runtime_snapshot_id,
                export_type="scenario_runtime_summary",
                active_scenario_id=bound_scenario_id,
                active_scenario_name=bound_scenario_name,
                scenario_provenance=scenario_provenance,
                warning_note=runtime_warning,
            )
            deps.update_scenario_last_run_summary(
                user.user_id, bound_scenario_id, result["kpis"], replay_metadata=scenario_replay,
            )

        result_messages = list(result.get("messages", []))
        if runtime_warning:
            result_messages.append(runtime_warning)

        prepend_html = _build_sessionstorage_save_tag(
            runtime_summary=runtime_summary,
            runtime_origin=runtime_origin,
            workspace_state=workspace_state,
            runtime_snapshot_id=runtime_snapshot_id,
            financial_statements=result.get("financial_statements"),
            debt_schedule=result.get("debt_schedule"),
            tax_schedule=result.get("tax_schedule"),
            distribution_schedule=result.get("distribution_schedule"),
            sponsor_schedule=result.get("sponsor_schedule"),
        )
        return RunRouteOutcome(
            template_name="partials/runtime_summary.html",
            context={
                "kpis": kpis,
                "runtime_summary": runtime_summary,
                "run_data": {"project_type": project_record.project_type, "scenario": scenario_name},
                "messages": result_messages,
                "integration_status": result.get("integration_status", "full"),
                "financial_statements": result.get("financial_statements"),
            },
            prepend_html=prepend_html,
        )
    except deps.snapshot_input_error as e:  # type: ignore[misc]
        return RunRouteOutcome(
            template_name="partials/errors.html",
            context={"errors": [str(e)]},
        )
    except Exception as e:  # noqa: BLE001
        return RunRouteOutcome(
            template_name="partials/errors.html",
            context={"errors": [f"Model error ({project_record.project_code}): {str(e)}"]},
        )


async def _execute_template_seeded_path(
    *,
    request,
    user,
    snapshot: dict,
    scenario: str,
    project_record,
    workspace_state,
    runtime_snapshot: Optional[dict],
    active_scenario_record,
    runtime_warning: Optional[str],
    runtime_origin: str,
    capacity_mw, tariff_eur_mwh, p50_hours, total_capex_keur, opex_y1_keur,
    gearing_pct, target_dscr, interest_rate_pct, tenor_years,
    runtime_seed: str,
    deps: RunRouteDeps,
) -> RunRouteOutcome:
    """Generic Wind Reference/Generic Solar Reference template-seeded path (existing factory flow)."""
    try:
        project_key = "Generic Wind Reference" if runtime_seed == "generic_wind_reference" else "Generic Solar Reference"
        scenario_name = snapshot.get("scenario", "") or "Base"
        if runtime_snapshot and runtime_origin == "saved_state" and workspace_state.active_scenario_id:
            override = deps.build_projectinputs_from_snapshot(runtime_snapshot)
        else:
            project_type = project_record.project_type or deps.default_workspace_snapshot(runtime_seed)["project_type"]
            schema = deps.build_schema_from_form(
                project_type, scenario_name, capacity_mw, tariff_eur_mwh, p50_hours,
                total_capex_keur, opex_y1_keur, gearing_pct, target_dscr,
                interest_rate_pct, tenor_years,
            )
            # Stack R: use the project-specific factory as the base for
            # Generic Wind Reference and Generic Solar Reference seeds, so all calibrated configuration
            # (SHL mechanics, equity_irr_method, merchant curve, frozen DS
            # schedule, tax params, etc.) is preserved.  Generic projects
            # continue to use the original generic-factory path.
            _seed_base = _get_seed_base_inputs(runtime_seed)
            if _seed_base is not None:
                from app.input_adapter import build_projectinputs_seeded as _build_seeded
                override = _build_seeded(schema, _seed_base)
            else:
                override = deps.build_projectinputs(schema)
        result = deps.run_project(project_key, scenario_name, project_inputs_override=override)
        kpis = deps.format_kpis(result["kpis"])
        runtime_summary = deps.runtime_summary_to_dict(result, project_record.project_code, project_record.project_name)
        runtime_snapshot_id = _utc_now_iso_compact()
        scenario_provenance = deps.scenario_provenance_for_record(project_record, active_scenario_record)
        bound_scenario_id = active_scenario_record.scenario_id if active_scenario_record else None
        bound_scenario_name = active_scenario_record.scenario_name if active_scenario_record else None

        # Persist (template-seeded gates runtime_snapshot on saved_state).
        replay_metadata = deps.replay_metadata_for_project(
            project_record.project_code,
            project_id=project_record.project_id,
            scenario_id=bound_scenario_id if runtime_origin == "saved_state" else None,
            scenario_name=active_scenario_record.scenario_name if active_scenario_record else scenario_name,
            runtime_timestamp=_utc_now_iso_full_iso(),
            runtime_snapshot_id=runtime_snapshot_id,
            export_type="workspace_runtime_state",
            active_scenario_id=bound_scenario_id if runtime_origin == "saved_state" else None,
            active_scenario_name=bound_scenario_name if runtime_origin == "saved_state" else None,
            scenario_provenance=scenario_provenance,
            warning_note=runtime_warning,
        )
        deps.record_workspace_runtime(
            user_id=user.user_id,
            project_id=project_record.project_id,
            project_code=project_record.project_code,
            runtime_snapshot=runtime_snapshot if runtime_snapshot and runtime_origin == "saved_state" else snapshot,
            runtime_summary=result["kpis"],
            runtime_snapshot_id=runtime_snapshot_id,
            runtime_origin=runtime_origin,
            governance_state=deps.governance_snapshot(project_record.project_code),
            active_scenario_id=bound_scenario_id if runtime_origin == "saved_state" else None,
            active_scenario_name=bound_scenario_name if runtime_origin == "saved_state" else None,
            replay_metadata=replay_metadata,
            financial_statements=result.get("financial_statements"),
            debt_schedule=result.get("debt_schedule"),
            tax_schedule=result.get("tax_schedule"),
            distribution_schedule=result.get("distribution_schedule"),
            sponsor_schedule=result.get("sponsor_schedule"),
        )
        if runtime_origin == "saved_state" and bound_scenario_id:
            scenario_replay = deps.replay_metadata_for_project(
                project_record.project_code,
                project_id=project_record.project_id,
                scenario_id=workspace_state.active_scenario_id,
                scenario_name=active_scenario_record.scenario_name if active_scenario_record else scenario_name,
                runtime_timestamp=_utc_now_iso_full_iso(),
                runtime_snapshot_id=runtime_snapshot_id,
                export_type="scenario_runtime_summary",
                active_scenario_id=bound_scenario_id,
                active_scenario_name=bound_scenario_name,
                scenario_provenance=scenario_provenance,
                warning_note=runtime_warning,
            )
            deps.update_scenario_last_run_summary(
                user.user_id, bound_scenario_id, result["kpis"], replay_metadata=scenario_replay,
            )

        result_messages = list(result.get("messages", []))
        if runtime_warning:
            result_messages.append(runtime_warning)

        prepend_html = _build_sessionstorage_save_tag(
            runtime_summary=runtime_summary,
            runtime_origin=runtime_origin,
            workspace_state=workspace_state,
            runtime_snapshot_id=runtime_snapshot_id,
            financial_statements=result.get("financial_statements"),
            debt_schedule=result.get("debt_schedule"),
            tax_schedule=result.get("tax_schedule"),
            distribution_schedule=result.get("distribution_schedule"),
            sponsor_schedule=result.get("sponsor_schedule"),
        )
        return RunRouteOutcome(
            template_name="partials/runtime_summary.html",
            context={
                "kpis": kpis,
                "runtime_summary": runtime_summary,
                "run_data": {"project_type": project_record.project_type or runtime_seed.title(), "scenario": scenario_name},
                "messages": result_messages,
                "integration_status": result.get("integration_status", "full"),
                "financial_statements": result.get("financial_statements"),
            },
            prepend_html=prepend_html,
        )
    except Exception as e:  # noqa: BLE001
        return RunRouteOutcome(
            template_name="partials/errors.html",
            context={"errors": [f"Model error ({project_record.project_code}): {str(e)}"]},
        )


async def _execute_generic_path(
    *,
    request,
    user,
    snapshot: dict,
    scenario: str,
    project_record,
    workspace_state,
    runtime_snapshot: Optional[dict],
    active_scenario_record,
    runtime_warning: Optional[str],
    runtime_origin: str,
    project_type, capacity_mw, tariff_eur_mwh, p50_hours, total_capex_keur, opex_y1_keur,
    gearing_pct, target_dscr, interest_rate_pct, tenor_years,
    deps: RunRouteDeps,
) -> RunRouteOutcome:
    """Generic template-seeded path (kpis.html output, no sessionStorage script)."""
    errors: list[str] = []
    effective_project_type = project_record.project_type or project_type
    if not deps.validate_form(effective_project_type, scenario, errors):
        return RunRouteOutcome(
            template_name="partials/errors.html",
            context={"errors": errors},
        )

    try:
        if runtime_snapshot and runtime_origin == "saved_state" and workspace_state.active_scenario_id:
            override = deps.build_projectinputs_from_snapshot(runtime_snapshot)
            scenario_name = scenario
        else:
            try:
                schema = deps.build_schema_from_form(
                    effective_project_type, scenario, capacity_mw, tariff_eur_mwh, p50_hours,
                    total_capex_keur, opex_y1_keur, gearing_pct, target_dscr,
                    interest_rate_pct, tenor_years,
                )
            except ValueError as ve:
                return RunRouteOutcome(
                    template_name="partials/errors.html",
                    context={"errors": [str(ve)]},
                )
            override = deps.build_projectinputs(schema)
            scenario_name = scenario
        runtime_project_key = (
            "Solar" if deps.canonical_project_type(effective_project_type) == "Solar" else "Wind"
        )
        result = deps.run_project(runtime_project_key, scenario_name, project_inputs_override=override)
        kpis = deps.format_kpis(result["kpis"])
        # STAB-7: compute runtime_summary so dashboard OOB refresh works for generic projects.
        runtime_summary = deps.runtime_summary_to_dict(result, project_record.project_code, project_record.project_name)
        runtime_snapshot_id = _utc_now_iso_compact()
        scenario_provenance = deps.scenario_provenance_for_record(project_record, active_scenario_record)
        bound_scenario_id = active_scenario_record.scenario_id if active_scenario_record else None
        bound_scenario_name = active_scenario_record.scenario_name if active_scenario_record else None

        # Persist (generic path: same gate as template-seeded on saved_state).
        replay_metadata = deps.replay_metadata_for_project(
            project_record.project_code,
            project_id=project_record.project_id,
            scenario_id=bound_scenario_id if runtime_origin == "saved_state" else None,
            scenario_name=active_scenario_record.scenario_name if active_scenario_record else scenario_name,
            runtime_timestamp=_utc_now_iso_full_iso(),
            runtime_snapshot_id=runtime_snapshot_id,
            export_type="workspace_runtime_state",
            active_scenario_id=bound_scenario_id if runtime_origin == "saved_state" else None,
            active_scenario_name=bound_scenario_name if runtime_origin == "saved_state" else None,
            scenario_provenance=scenario_provenance,
            warning_note=runtime_warning,
        )
        deps.record_workspace_runtime(
            user_id=user.user_id,
            project_id=project_record.project_id,
            project_code=project_record.project_code,
            runtime_snapshot=runtime_snapshot if runtime_snapshot and runtime_origin == "saved_state" else snapshot,
            runtime_summary=result["kpis"],
            runtime_snapshot_id=runtime_snapshot_id,
            runtime_origin=runtime_origin,
            governance_state=deps.governance_snapshot(project_record.project_code),
            active_scenario_id=bound_scenario_id if runtime_origin == "saved_state" else None,
            active_scenario_name=bound_scenario_name if runtime_origin == "saved_state" else None,
            replay_metadata=replay_metadata,
            financial_statements=result.get("financial_statements"),
            debt_schedule=result.get("debt_schedule"),
            tax_schedule=result.get("tax_schedule"),
            distribution_schedule=result.get("distribution_schedule"),
            sponsor_schedule=result.get("sponsor_schedule"),
        )
        if runtime_origin == "saved_state" and bound_scenario_id:
            scenario_replay = deps.replay_metadata_for_project(
                project_record.project_code,
                project_id=project_record.project_id,
                scenario_id=workspace_state.active_scenario_id,
                scenario_name=active_scenario_record.scenario_name if active_scenario_record else scenario_name,
                runtime_timestamp=_utc_now_iso_full_iso(),
                runtime_snapshot_id=runtime_snapshot_id,
                export_type="scenario_runtime_summary",
                active_scenario_id=bound_scenario_id,
                active_scenario_name=bound_scenario_name,
                scenario_provenance=scenario_provenance,
                warning_note=runtime_warning,
            )
            deps.update_scenario_last_run_summary(
                user.user_id, bound_scenario_id, result["kpis"], replay_metadata=scenario_replay,
            )

        result_messages = list(result.get("messages", []))
        if runtime_warning:
            result_messages.append(runtime_warning)

        # STAB-7: generate sessionStorage script so main_web.py wires up the
        # OOB dashboard refresh (same as template-seeded path).
        prepend_html = _build_sessionstorage_save_tag(
            runtime_summary=runtime_summary,
            runtime_origin=runtime_origin,
            workspace_state=workspace_state,
            runtime_snapshot_id=runtime_snapshot_id,
            financial_statements=result.get("financial_statements"),
            debt_schedule=result.get("debt_schedule"),
            tax_schedule=result.get("tax_schedule"),
            distribution_schedule=result.get("distribution_schedule"),
            sponsor_schedule=result.get("sponsor_schedule"),
        )
        return RunRouteOutcome(
            template_name="partials/kpis.html",
            context={
                "kpis": kpis,
                "runtime_summary": runtime_summary,
                "run_data": {
                    "project_type": effective_project_type,
                    "scenario": scenario_name,
                    "capacity_mw": capacity_mw,
                    "tariff_eur_mwh": tariff_eur_mwh,
                    "total_capex_keur": total_capex_keur,
                    "gearing_pct": gearing_pct,
                },
                "messages": result_messages,
                "integration_status": result.get("integration_status", "full"),
                "financial_statements": result.get("financial_statements"),
            },
            prepend_html=prepend_html,
        )
    except Exception as e:  # noqa: BLE001
        return RunRouteOutcome(
            template_name="partials/errors.html",
            context={"errors": [f"Model error: {str(e)}"]},
        )


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers (NOT part of public API)
# ─────────────────────────────────────────────────────────────────────────────


def _get_seed_base_inputs(runtime_seed: str):
    """Stack R: return a calibrated ProjectInputs for Generic Wind Reference/Generic Solar Reference seeds.

    Returns None for any other seed so the generic factory path is used.
    """
    if runtime_seed == "generic_wind_reference":
        from app.project_factories import create_generic_wind_reference
        return create_generic_wind_reference()
    if runtime_seed == "generic_solar_reference":
        from app.project_factories import create_generic_solar_reference
        return create_generic_solar_reference()
    return None


def _utc_now_iso_compact() -> str:
    """Return a UTC ISO string with ``:`` and ``-`` removed (matches legacy)."""
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat().replace(":", "").replace("-", "")


def _utc_now_iso_full_iso() -> str:
    """Full ISO-8601 UTC string (with ``:`` and ``-``)."""
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def _build_sessionstorage_save_tag(
    *,
    runtime_summary: dict,
    runtime_origin: str,
    workspace_state,
    runtime_snapshot_id: str,
    financial_statements: "dict | None" = None,
    debt_schedule: "dict | None" = None,
    tax_schedule: "dict | None" = None,
    distribution_schedule: "dict | None" = None,
    sponsor_schedule: "dict | None" = None,
) -> str:
    """Return the sessionStorage save ``<script>`` block.

    Preserves the legacy per-origin ``dirty`` / ``dirty_label`` /
    ``last_runtime_origin_label`` logic from the original /run route.
    The route in main_web.py decides whether to inject this after
    ``<body`` (for the ``<!DOCTYPE`` template-seeded flow) or to
    prepend it directly to the body (for the user_created flow).
    """
    if runtime_origin in ("saved_state", "workspace_base"):
        is_clean = True
    else:
        is_clean = False
    if runtime_origin == "saved_state":
        dirty_label = "Clean saved state"
    elif runtime_origin == "workspace_base":
        dirty_label = "Clean workspace base"
    else:
        dirty_label = "Unsaved edits"
    if runtime_origin == "saved_state":
        last_origin_label = "Runtime bound to saved scenario snapshot"
    elif runtime_origin == "workspace_base":
        last_origin_label = "Runtime bound to clean workspace base"
    else:
        last_origin_label = "Runtime bound to clean workspace base"
    # Phase D1: persist FS payload to sessionStorage so sheet_financials.html
    # can render real engine output without a separate HTTP round-trip.
    # FS data is read-only engine output from assemble_financial_statements().
    # All schedule/summary payloads are serialized with _dumps_for_script so
    # that user-controlled strings containing </script> cannot terminate the
    # enclosing script element.  The outer json.dumps wraps the safe JSON
    # string in a JavaScript string literal.  Values round-trip exactly
    # after JSON.parse() in the browser.
    fs_script = ""
    if financial_statements is not None:
        fs_script = (
            'sessionStorage.setItem("lastFinancialStatements", '
            + json.dumps(_dumps_for_script(financial_statements))
            + ');'
        )
    else:
        # Clear stale FS data when a run produces no FS (degrade gracefully).
        fs_script = 'sessionStorage.removeItem("lastFinancialStatements");'

    # Phase E2: persist debt schedule payload to sessionStorage so
    # sheet_senior_debt.html can render real engine output without a
    # separate HTTP round-trip. Data is read-only engine output from
    # _serialize_debt_schedule(WaterfallResult).
    ds_script = ""
    if debt_schedule is not None:
        ds_script = (
            'sessionStorage.setItem("lastDebtSchedule", '
            + json.dumps(_dumps_for_script(debt_schedule))
            + ');'
        )
    else:
        # Clear stale debt schedule data when a run produces none.
        ds_script = 'sessionStorage.removeItem("lastDebtSchedule");'

    # Phase F2: persist tax schedule payload to sessionStorage so
    # sheet_tax.html can render real engine output without a
    # separate HTTP round-trip. Data is read-only engine output from
    # _serialize_tax_schedule(WaterfallResult).
    ts_script = ""
    if tax_schedule is not None:
        ts_script = (
            'sessionStorage.setItem("lastTaxSchedule", '
            + json.dumps(_dumps_for_script(tax_schedule))
            + ');'
        )
    else:
        # Clear stale tax schedule data when a run produces none.
        ts_script = 'sessionStorage.removeItem("lastTaxSchedule");'

    # Phase G1: persist distribution schedule payload to sessionStorage so
    # _sheet_distributions_partial.html can render real engine output without
    # a separate HTTP round-trip. Data is read-only engine output from
    # _serialize_distribution_schedule(WaterfallResult).
    dist_script = ""
    if distribution_schedule is not None:
        dist_script = (
            'sessionStorage.setItem("lastDistributionSchedule", '
            + json.dumps(_dumps_for_script(distribution_schedule))
            + ');'
        )
    else:
        # Clear stale distribution schedule data when a run produces none.
        dist_script = 'sessionStorage.removeItem("lastDistributionSchedule");'

    # Phase H3: persist sponsor schedule payload to sessionStorage so
    # _sheet_sponsor_partial.html can render real engine output without a
    # separate HTTP round-trip. Data is read-only engine output from
    # _serialize_sponsor_schedule(SponsorCashflowResult, SponsorIrrResult, SponsorMoicResult).
    sponsor_script = ""
    if sponsor_schedule is not None:
        sponsor_script = (
            'sessionStorage.setItem("lastSponsorSchedule", '
            + json.dumps(_dumps_for_script(sponsor_schedule))
            + ');'
        )
    else:
        # Clear stale sponsor schedule data when a run produces none.
        sponsor_script = 'sessionStorage.removeItem("lastSponsorSchedule");'

    return (
        '<script>'
        + fs_script
        + ds_script
        + ts_script
        + dist_script
        + sponsor_script
        + 'sessionStorage.setItem("lastRuntimeSummary", ' + json.dumps(_dumps_for_script(runtime_summary)) + ');'
        'window.applyWorkspaceStateMeta && window.applyWorkspaceStateMeta(' + _dumps_for_script({
            "dirty": False if is_clean else True,
            "dirty_label": dirty_label,
            "active_scenario_id": getattr(workspace_state, "active_scenario_id", "") or "",
            "active_scenario_name": getattr(workspace_state, "active_scenario_name", "") or "",
            "last_runtime_origin": runtime_origin,
            "last_runtime_origin_label": last_origin_label,
            "last_runtime_snapshot_id": runtime_snapshot_id,
        }) + ');'
        'window._populateRuntimeBlock && window._populateRuntimeBlock();'
        '</script>'
    )


# ─────────────────────────────────────────────────────────────────────────────
# Public type aliases
# ─────────────────────────────────────────────────────────────────────────────

# These are intentionally loose: we accept anything with a __getattr__/form
# interface, including FastAPI's awaitable form. Keeping them as aliases
# avoids forcing ``fastapi.Request`` to be imported here.
RequestLike = Any
FormLike = Any
