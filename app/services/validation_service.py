"""Phase 51D-2 — Vertical extraction of POST /validate orchestration.

This module owns the orchestration body that previously lived inside the
``@app.post("/validate")`` route handler in ``main_web.py``.

The route is now thin: it authenticates the user, parses the form, calls
``execute_validate_route(...)`` and renders the returned
``ValidateRouteOutcome`` via the existing FastAPI / Jinja rendering
path.

Why ``ValidateRouteOutcome`` (return value) instead of building a
Response here:
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
``_project_workspace_from_snapshot``, ``_resolve_runtime_snapshot_source``,
``_build_schema_from_form``, ``_validate_numeric_field``,
``check_runtime_allowed``) are passed in as callable dependencies by
the route. This keeps the import direction clean (``main_web`` ->
``validation_service`` and never the reverse).

Phase 51D-2 explicitly preserves the runtime-snapshot parity quirk
that Phase 51D-1 characterized:

* ``/validate`` must still call ``resolve_runtime_snapshot_source``.
* It may capture only the first tuple element as ``runtime_snapshot``.
* The resolved snapshot must remain unused downstream (the legacy
  /validate route captured but did not use it).
* This is preserved for parity with /run and /compare; do NOT remove
  it as cleanup in Phase 51D-2.

The /validate route remains read-only — there are no persistence
side effects (no ``record_*``, no DB writes).

Validation stage order is preserved EXACTLY from the legacy /validate
route:

  Stage A: enum validation (project_type, scenario)
  Stage B: numeric field validation (9 fields, _validate_numeric_field)
  Stage C: schema build validation (_build_schema_from_form, ValueError
           catch, gated by ``if not errors:``)

Errors accumulate across stages (no short-circuit on first error).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional


@dataclass
class ValidateRouteOutcome:
    """Result of POST /validate orchestration.

    The route in ``main_web.py`` translates this into a FastAPI response.
    """

    template_name: str
    context: dict
    status_code: int = 200
    headers: dict = field(default_factory=dict)


@dataclass
class ValidateRouteDeps:
    """Dependencies that ``execute_validate_route`` needs from the route.

    The route in ``main_web.py`` owns these helpers; passing them in as
    callables (rather than importing from ``main_web``) keeps the
    ``main_web`` -> ``validation_service`` import direction clean and lets
    future test code inject test doubles.

    Notes on dependency shape (Phase 51D-2):

    * ``validate_numeric_field`` is the per-field validation helper
      (signature: ``(name, val, max_val) -> (value, error_message)``).
      It is NOT a whole-form helper.

    * ``canonical_project_type`` and ``normalize_template_source`` are
      NOT used by the /validate service today (the legacy /validate
      route did not use them either). They are kept in the deps bundle
      for parity with ``compare_service`` and ``run_service`` patterns.

    * ``snapshot_input_error`` is NOT used by /validate today. Kept for
      parity with the /compare pattern.

    * ``resolve_runtime_snapshot_source`` IS called by the service (see
      the parity-preservation note in the module docstring).
    """

    # Form / snapshot helpers
    collect_form_snapshot: Callable[[Any], dict]
    project_workspace_from_snapshot: Callable[[Any, dict], tuple]

    # Project / template normalization (parity with compare_service;
    # NOT used by /validate today)
    canonical_project_type: Callable[[Any], str]
    normalize_template_source: Callable[..., str]

    # Runtime guard + resolution
    check_runtime_allowed: Callable[..., tuple]
    resolve_runtime_snapshot_source: Callable[..., tuple]

    # Schema / input adapters
    build_schema_from_form: Callable[..., Any]

    # Numeric field validation (per-field helper, NOT whole-form)
    validate_numeric_field: Callable[..., tuple]

    # Constants (moved out of main_web globals for the /validate
    # service so it has no implicit module-scope dependencies).
    project_types: list[str]
    scenarios: list[str]

    # Snapshot error class (parity with compare_service; NOT used by
    # /validate today)
    snapshot_input_error: type


# ─────────────────────────────────────────────────────────────────────────────
# Service entry point
# ─────────────────────────────────────────────────────────────────────────────


async def execute_validate_route(
    *,
    request: Any,
    form: Any,
    user: Any,
    deps: ValidateRouteDeps,
) -> ValidateRouteOutcome:
    """Execute the /validate orchestration and return a ``ValidateRouteOutcome``.

    The route in ``main_web.py`` translates the outcome into a FastAPI
    response via ``templates.TemplateResponse(...)``.

    Behavior preserved from the legacy /validate route (Phase 51D-1
    characterization):

      * Form parsing semantics (12 form fields).
      * Project / workspace resolution.
      * Runtime guard semantics (return errors.html on guard block).
      * **Runtime snapshot resolution parity call** — Phase 51D-1
        documented that the legacy /validate route called
        ``_resolve_runtime_snapshot_source`` for parity with /run and
        /compare, but only used the first tuple element (the snapshot
        itself) and discarded the rest. The resolved snapshot was
        captured but NOT used downstream. **This exact behavior is
        preserved** — the service calls the resolver for parity and
        captures the snapshot into a local variable that is never read.
        Do NOT remove this call as cleanup in Phase 51D-2.
      * Stage A enum validation (project_type in deps.project_types,
        scenario in deps.scenarios).
      * Stage B numeric field validation (9 fields with pinned max
        values: capacity_mw=2000.0, tariff_eur_mwh=1000.0,
        p50_hours=10000.0, total_capex_keur=1_000_000.0,
        opex_y1_keur=500_000.0, gearing_pct=100.0, target_dscr=10.0,
        interest_rate_pct=30.0, tenor_years=50.0). Empty numeric
        field passes Stage B (treated as optional).
      * Stage C schema build validation: only runs if Stage A and B
        have no errors (gated by ``if not errors:``); catches
        ``ValueError`` specifically (NOT bare ``Exception``); appends
        ``str(ve)`` on error.
      * Errors accumulate across all three stages (no short-circuit).
      * Template name: ``partials/validation.html``.
      * Status code: 200.
      * Context keys: ``valid`` (bool), ``errors`` (list), and
        ``form_data`` (dict subset of form fields: project_type,
        scenario).
      * Read-only behavior: no persistence side effects.
    """
    # ── 1. Form parsing (12 fields, identical to legacy /validate) ─────
    project_type = form.get("project_type", "")
    scenario = form.get("scenario", "")
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
        return ValidateRouteOutcome(
            template_name="partials/errors.html",
            context={"errors": [guard_message]},
        )

    # ── 4. Runtime snapshot resolution (PARITY CALL — Phase 51D-1 quirk) ──
    # The legacy /validate route called _resolve_runtime_snapshot_source
    # for parity with /run and /compare, but only used the first tuple
    # element (the snapshot itself) and discarded the rest. The resolved
    # snapshot was captured into a local variable but NEVER read
    # downstream. We preserve this exact behavior:
    #   - call the resolver when the parity branch matches
    #   - capture only the first tuple element
    #   - leave the captured snapshot unused
    # Do NOT remove this call as cleanup in Phase 51D-2.
    runtime_snapshot: Optional[dict] = None  # noqa: F841 — captured, intentionally unused (parity)
    if (runtime_origin == "saved_state" and workspace_state.active_scenario_id) \
            or project_record.project_origin == "user_created":
        runtime_snapshot, _, _, _ = deps.resolve_runtime_snapshot_source(
            user,
            project_record,
            workspace_state,
            runtime_origin,
        )

    # ── 5. Stage A: enum validation ─────────────────────────────────────
    errors: list[str] = []
    if project_type not in deps.project_types:
        errors.append(f"project_type must be one of {deps.project_types}")
    if scenario not in deps.scenarios:
        errors.append(f"scenario must be one of {deps.scenarios}")

    # ── 6. Stage B: numeric field validation (9 fields, exact max values) ──
    numeric_checks = [
        ("capacity_mw", capacity_mw, 2000.0),
        ("tariff_eur_mwh", tariff_eur_mwh, 1000.0),
        ("p50_hours", p50_hours, 10000.0),
        ("total_capex_keur", total_capex_keur, 1_000_000.0),
        ("opex_y1_keur", opex_y1_keur, 500_000.0),
        ("gearing_pct", gearing_pct, 100.0),
        ("target_dscr", target_dscr, 10.0),
        ("interest_rate_pct", interest_rate_pct, 30.0),
        ("tenor_years", tenor_years, 50.0),
    ]
    for fname, fval, max_val in numeric_checks:
        _, err = deps.validate_numeric_field(fname, fval, max_val)
        if err:
            errors.append(err)

    # ── 7. Stage C: schema build validation (gated by `if not errors:`) ──
    if not errors:
        try:
            schema = deps.build_schema_from_form(
                project_type, scenario,
                capacity_mw, tariff_eur_mwh, p50_hours,
                total_capex_keur, opex_y1_keur,
                gearing_pct, target_dscr, interest_rate_pct, tenor_years,
            )
        except ValueError as ve:
            errors.append(str(ve))

    # ── 8. Template response ─────────────────────────────────────────────
    return ValidateRouteOutcome(
        template_name="partials/validation.html",
        context={
            "valid": len(errors) == 0,
            "errors": errors,
            "form_data": {"project_type": project_type, "scenario": scenario},
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
