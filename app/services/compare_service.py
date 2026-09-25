"""Phase 51C-2 — Vertical extraction of POST /compare orchestration.

This module owns the orchestration body that previously lived inside the
``@app.post("/compare")`` route handler in ``main_web.py``.

The route is now thin: it authenticates the user, parses the form, calls
``execute_compare_route(...)`` and renders the returned
``CompareRouteOutcome`` via the existing FastAPI / Jinja rendering path.

Why ``CompareRouteOutcome`` (return value) instead of building a Response
here:
- The route in ``main_web.py`` owns the FastAPI ``Request`` and the
  ``Jinja2Templates`` instance. Passing a ``Response`` across that
  boundary forces the service to depend on FastAPI internals, which
  would couple the service to the web framework and complicate future
  unit testing.
- Returning a plain dataclass keeps the service free of framework
  dependencies, and the route is the only place that calls
  ``templates.TemplateResponse(...)`` and ``HTMLResponse(...)``.

This module does NOT import ``main_web``. All helper functions that the
route in ``main_web.py`` still owns (``_collect_form_snapshot``,
``_project_workspace_from_snapshot``, ``_normalize_template_source``,
``_canonical_project_type``, ``_resolve_runtime_snapshot_source``,
``_build_schema_from_form``, ``build_projectinputs``,
``build_projectinputs_from_snapshot``, ``run_project``) are passed in
as callable dependencies by the route. This keeps the import direction
clean (``main_web`` -> ``compare_service`` and never the reverse).

Phase 51C-2 explicitly fixes two latent bugs that were characterized in
Phase 51C-1:

* Bug A: ``user_created`` path referenced ``runtime_snapshot`` which was
  never defined. This would raise ``NameError`` on first execution. The
  fix resolves the runtime snapshot through
  ``deps.resolve_runtime_snapshot_source`` BEFORE building inputs in
  the ``user_created`` branch.

* Bug B: ``saved_state`` + ``active_scenario`` path referenced a
  ``runtime_snapshot`` variable that was never set in that code path
  (the resolver was never called). The fix resolves the snapshot
  through ``deps.resolve_runtime_snapshot_source`` early in
  ``execute_compare_route`` and uses the resolved snapshot consistently
  across all execution branches.

The /compare route remains read-only — there are no persistence side
effects (no ``record_compare_run``, no ``record_workspace_runtime``,
no DB writes).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional


@dataclass
class CompareRouteOutcome:
    """Result of POST /compare orchestration.

    The route in ``main_web.py`` translates this into a FastAPI response.
    """

    template_name: str
    context: dict
    status_code: int = 200
    headers: dict = field(default_factory=dict)


@dataclass
class CompareRouteDeps:
    """Dependencies that ``execute_compare_route`` needs from the route.

    The route in ``main_web.py`` owns these helpers; passing them in as
    callables (rather than importing from ``main_web``) keeps the
    ``main_web`` -> ``compare_service`` import direction clean and lets
    future test code inject test doubles.
    """

    # Form / snapshot helpers
    collect_form_snapshot: Callable[[Any], dict]
    project_workspace_from_snapshot: Callable[[Any, dict], tuple]

    # Project / template normalization
    canonical_project_type: Callable[[Any], str]
    normalize_template_source: Callable[..., str]

    # Runtime guard + resolution (resolution is the key Bug B fix)
    check_runtime_allowed: Callable[..., tuple]
    resolve_runtime_snapshot_source: Callable[..., tuple]

    # Schema / input adapters
    build_schema_from_form: Callable[..., Any]
    build_projectinputs: Callable[..., Any]
    build_projectinputs_from_snapshot: Callable[..., Any]

    # Scenarios / project types (moved out of main_web globals for the
    # /compare service so it has no implicit module-scope dependencies).
    scenarios: list[str]
    project_types: list[str]

    # Snapshot error class (used for narrow except in user_created path)
    snapshot_input_error: type

    # Model execution
    run_project: Callable[..., dict]


# ─────────────────────────────────────────────────────────────────────────────
# Service entry point
# ─────────────────────────────────────────────────────────────────────────────


async def execute_compare_route(
    *,
    request: Any,
    form: Any,
    user: Any,
    deps: CompareRouteDeps,
) -> CompareRouteOutcome:
    """Execute the /compare orchestration and return a ``CompareRouteOutcome``.

    The route in ``main_web.py`` translates the outcome into a FastAPI
    response via ``templates.TemplateResponse(...)``.

    Phase 51C-2 explicitly fixes two latent bugs from Phase 51C-1:
      A. user_created path no longer raises NameError because
         ``runtime_snapshot`` is now resolved through
         ``deps.resolve_runtime_snapshot_source``.
      B. saved_state + active_scenario path now uses the resolved
         snapshot, not raw form values.

    Behavior preserved from the legacy /compare route:
      - Form parsing semantics (10 form fields).
      - Project / workspace resolution.
      - Runtime guard semantics (return errors.html on guard block).
      - Validation error semantics (project_type must be in project_types).
      - Generic wind/solar success response shape.
      - Generic Wind Reference / Generic Solar Reference response shape (key selection logic).
      - Per-scenario soft-error semantics: failing scenario becomes
        ``{"error": str(e)}`` and the loop continues.
      - Template names: ``partials/comparison.html`` on success,
        ``partials/errors.html`` on errors.
      - Status codes.
      - Context keys: ``project_type``, ``scenarios``, ``results``.
      - Read-only behavior: no persistence side effects.
    """
    # ── 1. Form parsing (10 fields, identical to legacy /compare) ─────────
    project_type = form.get("project_type", "")
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

    # ── 3. Runtime guard (errors.html on block) ──────────────────────────
    allow_run, runtime_origin, guard_message = deps.check_runtime_allowed(workspace_state, snapshot)
    if not allow_run:
        return CompareRouteOutcome(
            template_name="partials/errors.html",
            context={"errors": [guard_message]},
        )

    # ── 4. Project type validation (errors.html on invalid) ──────────────
    errors: list[str] = []
    effective_project_type = project_record.project_type or project_type
    if effective_project_type not in deps.project_types:
        errors.append(f"project_type must be one of {deps.project_types}")
        return CompareRouteOutcome(
            template_name="partials/errors.html",
            context={"errors": errors},
        )

    # ── 5. Runtime snapshot resolution (BUG FIX B) ──────────────────────
    # The legacy /compare route referenced ``runtime_snapshot`` on the
    # saved_state + active_scenario branch without ever calling
    # ``resolve_runtime_snapshot_source``. We now resolve it early and
    # share it across all branches. This mirrors the /run pattern.
    runtime_snapshot: Optional[dict] = None
    active_scenario_record = None
    runtime_warning: Optional[str] = None
    if (runtime_origin == "saved_state" and workspace_state.active_scenario_id) \
            or project_record.project_origin == "user_created":
        (
            runtime_snapshot,
            active_scenario_record,
            runtime_warning,
            effective_runtime_origin,
        ) = deps.resolve_runtime_snapshot_source(
            user, project_record, workspace_state, runtime_origin,
        )

    # ── 6. Override construction (user_created vs template-seeded) ───────
    if project_record.project_origin == "user_created":
        # BUG FIX A: runtime_snapshot is now defined via step 5 above.
        # The legacy /compare route referenced ``runtime_snapshot`` here
        # without ever defining it (NameError latent bug).
        try:
            override = deps.build_projectinputs_from_snapshot(runtime_snapshot)
        except deps.snapshot_input_error as e:  # type: ignore[misc]
            return CompareRouteOutcome(
                template_name="partials/errors.html",
                context={"errors": [str(e)]},
            )
        runtime_project_key = (
            "Solar"
            if deps.canonical_project_type(effective_project_type) == "Solar"
            else "Wind"
        )
    else:
        try:
            # BUG FIX B: saved_state + active_scenario now correctly uses
            # the resolved snapshot (which was missing in legacy /compare).
            if runtime_snapshot and runtime_origin == "saved_state" and workspace_state.active_scenario_id:
                override = deps.build_projectinputs_from_snapshot(runtime_snapshot)
            else:
                schema = deps.build_schema_from_form(
                    effective_project_type, "Base",
                    capacity_mw, tariff_eur_mwh, p50_hours,
                    total_capex_keur, opex_y1_keur,
                    gearing_pct, target_dscr, interest_rate_pct, tenor_years,
                )
                override = deps.build_projectinputs(schema)
        except ValueError as ve:
            return CompareRouteOutcome(
                template_name="partials/errors.html",
                context={"errors": [f"Invalid input: {str(ve)}"]},
            )
        except Exception as e:  # noqa: BLE001
            # Preserve the legacy overly-broad except (documented in 51C-1)
            return CompareRouteOutcome(
                template_name="partials/errors.html",
                context={"errors": [f"Invalid input: {str(e)}"]},
            )

        # Project key resolution (Generic Wind Reference / Generic Solar Reference / Solar / Wind)
        runtime_seed = deps.normalize_template_source(
            project_record.template_source or project_record.source_project_template,
            effective_project_type,
        )
        if runtime_seed == "generic_wind_reference":
            runtime_project_key = "Generic Wind Reference"
        elif runtime_seed == "generic_solar_reference":
            runtime_project_key = "Generic Solar Reference"
        elif runtime_seed == "generic_data_center_reference":
            runtime_project_key = "Generic Data Center Reference"
        else:
            runtime_project_key = (
                "Solar"
                if deps.canonical_project_type(effective_project_type) == "Solar"
                else "Wind"
            )

    # ── 7. Model execution loop (soft-error per scenario) ────────────────
    # /compare is read-only: NO persistence side effects. There is no
    # record_compare_run / record_workspace_runtime call on this path.
    results: dict[str, dict] = {}
    for sc in deps.scenarios:
        try:
            r = deps.run_project(runtime_project_key, sc, project_inputs_override=override)
            results[sc] = {
                "project_irr": r["kpis"].get("project_irr"),
                "equity_irr": r["kpis"].get("equity_irr"),
                "min_dscr": r["kpis"].get("min_dscr"),
                "avg_dscr": r["kpis"].get("avg_dscr"),
                "total_revenue_keur": r["kpis"].get("total_revenue_keur"),
                "total_ebitda_keur": r["kpis"].get("total_ebitda_keur"),
            }
        except Exception as e:  # noqa: BLE001
            # Soft-error semantics: failing scenario becomes {"error": str(e)}
            # and the loop continues (does not short-circuit).
            results[sc] = {"error": str(e)}

    # ── 8. Template response ─────────────────────────────────────────────
    return CompareRouteOutcome(
        template_name="partials/comparison.html",
        context={
            "project_type": effective_project_type,
            "scenarios": list(deps.scenarios),
            "results": results,
        },
    )


# ─────────────────────────────────────────────────────────────────────────────
# Public type aliases
# ─────────────────────────────────────────────────────────────────────────────

# These are intentionally loose: we accept anything with a form-like
# interface, including FastAPI's awaitable form. Keeping them as aliases
# avoids forcing ``fastapi.Request`` to be imported here.
RequestLike = Any
FormLike = Any
