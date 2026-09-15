"""Phase 51E-2 — Vertical extraction of POST /download and GET /download orchestration.

This module owns the orchestration body that previously lived inside
the ``@app.post("/download")`` and ``@app.get("/download")`` route
handlers in ``main_web.py``.

Both routes are now thin: they authenticate the user, parse the form
(POST) or query params (GET), call the service, and render the
returned ``DownloadRouteOutcome`` via ``StreamingResponse`` (success)
or ``HTMLResponse`` (inline error).

Why a dataclass outcome instead of returning a ``Response``
directly:
- The route in ``main_web.py`` owns the FastAPI ``Request`` and the
  ``Jinja2Templates`` instance. Passing a ``Response`` across that
  boundary forces the service to depend on FastAPI internals, which
  would couple the service to the web framework and complicate future
  unit testing.
- Returning a plain dataclass keeps the service free of framework
  dependencies, and the route is the only place that calls
  ``StreamingResponse(...)`` and ``HTMLResponse(...)``.

This module does NOT import ``main_web``. All helper functions that
the route in ``main_web.py`` still owns (``_collect_form_snapshot``,
``_project_workspace_from_snapshot``, ``_canonical_project_type``,
``_normalize_template_source``, ``_resolve_runtime_snapshot_source``,
``_build_schema_from_form``, ``_scenario_provenance_for_record``,
``_replay_metadata_for_project``, ``_governance_snapshot``) are
passed in as callable dependencies by the route. The model execution
(clean production authority seam) and project lookup (``get_project_by_code``)
are also passed in as deps. The export builders
(``build_excel_export_for_post_request`` /
``build_values_only_export_for_project``) and the audit recorder
(``record_download_export``) are passed in as deps — the service
does NOT import them. The schema adapter (``build_projectinputs`` /
``build_projectinputs_from_snapshot``) is also passed in as a dep.
``utc_now_iso`` is passed in as a dep so the service is free of
clock coupling.

This keeps the import direction clean (``main_web`` ->
``download_service`` and never the reverse).

Phase 51E-2 explicitly preserves the 12 documented behavior quirks
that Phase 51E-1 characterized:

1. POST has TWO template branches for project_key resolution.
2. GET has HARDCODED project_code mapping ("generic_solar_reference" if
   project_type.lower() == "solar" otherwise "generic_wind_reference").
3. POST mutates ``runtime_origin = "saved_state"`` in the
   non-user_created branch when active_scenario_id is set.
4. POST uses ``build_excel_export_for_post_request``; GET uses
   ``build_values_only_export_for_project``.
5. POST uses hardcoded xlsx media_type; GET uses
   ``export.media_type``.
6. POST constructs filename in the route/orchestration; GET uses
   ``export.filename``.
7. GET passes ``scenario_id=None`` to ``record_download_export``;
   POST passes active scenario id (or None).
8. Inline error HTML in both routes is preserved; no Jinja
   templates are introduced.
9. Top-level ``except Exception`` broad catch is preserved; 500
   inline error page behavior remains.
10. ``artifact_path`` is a string describing the URL, not a
    filesystem path.
11. POST captures ``effective_runtime_origin`` from
    ``_resolve_runtime_snapshot_source`` but discards it downstream
    (parity quirk preserved exactly).
12. POST broad ``except (ValueError, Exception)`` on schema build
    is preserved as-is.

Export audit (record_download_export) is INTENDED Phase 49
export-audit behavior — NOT forbidden persistence. It is preserved
exactly (one call per successful POST /download or GET /download).

The /download route/service does NOT call any of:
- ``record_workspace_runtime`` (only /run)
- ``update_scenario_last_run_summary`` (only /run)
- ``record_compare_run`` (does not exist)
- ``record_export`` (direct call; 0 in main_web.py)
- ``db.add`` / ``db.commit`` / ``db.flush`` / ``session.add`` /
  ``session.commit``

Model execution (clean production authority seam) is in-memory only and has
no persistence side effect.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional, Union


@dataclass
class DownloadRouteOutcome:
    """Result of POST /download or GET /download orchestration.

    The route in ``main_web.py`` translates this into a
    ``StreamingResponse`` (success path) or ``HTMLResponse`` (inline
    error path).

    The shape supports both success (xlsx bytes) and error (HTML
    string) outcomes without forcing the service to depend on
    FastAPI's ``Response`` class.

    Fields:
        content: ``bytes`` for success (xlsx payload) or ``str`` for
            error (HTML body).
        media_type: MIME type for the response. For success POST it
            is hardcoded to the xlsx application type; for success
            GET it is the export object's media_type; for errors it
            is ``"text/html; charset=utf-8"``.
        filename: Optional ``Content-Disposition`` filename. ``None``
            for error responses; constructed for success POST;
            taken from ``export.filename`` for success GET.
        status_code: HTTP status code. Default 200. Set to 400 for
            schema build / runtime guard block / export error; 500
            for top-level exception.
        headers: Extra response headers (e.g. ``Content-Length``).
        is_error: ``True`` for HTML error responses; ``False`` for
            success.
    """

    content: Union[bytes, str]
    media_type: str
    filename: Optional[str] = None
    status_code: int = 200
    headers: dict = field(default_factory=dict)
    is_error: bool = False


@dataclass
class DownloadRouteDeps:
    """Dependencies that ``execute_post_download_route`` and
    ``execute_get_download_route`` need from the route.

    The route in ``main_web.py`` owns these helpers; passing them in
    as callables (rather than importing from ``main_web``) keeps the
    ``main_web`` -> ``download_service`` import direction clean and
    lets future test code inject test doubles.
    """

    # Form / snapshot helpers (used by POST)
    collect_form_snapshot: Callable[[Any], dict]
    project_workspace_from_snapshot: Callable[[Any, dict], tuple]

    # Project / template normalization (used by POST)
    canonical_project_type: Callable[[Any], str]
    normalize_template_source: Callable[..., str]

    # Runtime guard + resolution (used by POST)
    check_runtime_allowed: Callable[..., tuple]
    resolve_runtime_snapshot_source: Callable[..., tuple]

    # Schema / input adapters (used by POST)
    build_schema_from_form: Callable[..., Any]
    build_projectinputs: Callable[..., Any]
    build_projectinputs_from_snapshot: Callable[..., Any]

    # Replay / governance (used by both)
    scenario_provenance_for_record: Callable[..., Any]
    replay_metadata_for_project: Callable[..., Any]
    governance_snapshot: Callable[..., str, dict]

    # Model execution (used by both)
    # Project lookup (used by GET only)
    get_project_by_code: Callable[..., Any]

    # Export builders (POST uses _for_post_request, GET uses _for_project)
    build_excel_export_for_post_request: Callable[..., Any]
    build_values_only_export_for_project: Callable[..., Any]

    # Audit (intended export-audit, preserved from Phase 49)
    record_download_export: Callable[..., Any]

    # Utility
    utc_now_iso: Callable[[], str]


# ─────────────────────────────────────────────────────────────────────────────
# Inline error HTML format (preserved from legacy /download route)
# ─────────────────────────────────────────────────────────────────────────────


_INLINE_ERROR_HTML_TEMPLATE = (
    "<html><body><h2>Excel generation failed</h2><p>{message}</p>"
    "<a href='/'>Back</a></body></html>"
)
_INLINE_ERROR_MEDIA_TYPE = "text/html; charset=utf-8"


def _build_inline_error_outcome(message: str, status_code: int) -> DownloadRouteOutcome:
    """Build a DownloadRouteOutcome for an inline HTML error page.

    This preserves the legacy /download error page format
    (``<html><body><h2>Excel generation failed</h2><p>...</p><a
    href='/'>Back</a></body></html>``) with no Jinja template.
    """
    return DownloadRouteOutcome(
        content=_INLINE_ERROR_HTML_TEMPLATE.format(message=message),
        media_type=_INLINE_ERROR_MEDIA_TYPE,
        filename=None,
        status_code=status_code,
        headers={},
        is_error=True,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Service entry point — POST /download
# ─────────────────────────────────────────────────────────────────────────────


async def execute_post_download_route(
    *,
    request: Any,
    form: Any,
    user: Any,
    deps: DownloadRouteDeps,
) -> DownloadRouteOutcome:
    """Execute the POST /download orchestration and return a
    ``DownloadRouteOutcome``.

    Behavior preserved from the legacy POST /download route
    (Phase 51E-1 characterization):

      * Auth redirect is route-owned (not in the service).
      * ``await request.form()`` is route-owned.
      * Form parsing: 12 form fields
        (project_type, scenario, capacity_mw, tariff_eur_mwh,
        p50_hours, total_capex_keur, opex_y1_keur, gearing_pct,
        target_dscr, interest_rate_pct, tenor_years).
      * Schema build + override construction: ``_build_schema_from_form``
        then ``build_projectinputs(schema)``. On ``(ValueError,
        Exception)`` returns HTMLResponse 400 with "Invalid input:" prefix.
      * Snapshot + project/workspace resolution.
      * Runtime guard for user_created projects.
      * Runtime snapshot resolution via
        ``_resolve_runtime_snapshot_source(...)`` for user_created
        AND saved_state branches. **Parity quirk 11:** the
        ``effective_runtime_origin`` (4th tuple element) is captured
        into a local variable that is intentionally never read
        downstream.
      * Runtime origin mutation in non-user_created branch
        (**quirk 3**): when ``runtime_origin == "saved_state" and
        workspace_state.active_scenario_id``, mutate
        ``runtime_origin = "saved_state"``.
      * Project key resolution (**quirk 1**): user_created uses
        "Solar" or "Wind" from canonical; template-seeded uses
        "Generic Wind Reference" or "Generic Solar Reference" from normalized template_source, with
        "Solar"/"Wind" fallback.
      * Model execution: ``execute_production_demo`` (clean production authority seam).
      * Replay metadata + scenario provenance.
      * Baseline source flag if project_origin == "saved_baseline".
      * Excel generation via ``build_excel_export_for_post_request``.
      * Export error check: if ``export.has_error()``, return inline
        error HTML with ``export.error_content`` and
        ``export.status_code``.
      * **Export audit (preserved, INTENDED):**
        ``record_download_export(...)`` with full provenance.
      * Success: ``StreamingResponse`` with hardcoded xlsx
        media_type, route-constructed filename
        (``f"finco_model_{project_type.lower()}_{scenario.lower()}.xlsx"``).
      * Top-level ``except Exception`` (preserved): returns
        HTMLResponse 500 with inline error page.
    """
    # ── 1. Form parsing (12 fields) ─────────────────────────────────
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

    # ── 2. Schema build + override construction ──────────────────────
    # Preserved broad except (ValueError, Exception) — quirk 12.
    try:
        schema = deps.build_schema_from_form(
            project_type, scenario,
            capacity_mw, tariff_eur_mwh, p50_hours,
            total_capex_keur, opex_y1_keur,
            gearing_pct, target_dscr, interest_rate_pct, tenor_years,
        )
        override = deps.build_projectinputs(schema)
    except (ValueError, Exception) as e:
        return _build_inline_error_outcome(
            message=f"Invalid input: {str(e)}", status_code=400,
        )

    # ── 3. Snapshot + project/workspace resolution ───────────────────
    snapshot = deps.collect_form_snapshot(form)
    project_record, workspace_state = deps.project_workspace_from_snapshot(user, snapshot)
    project_code = project_record.project_code
    effective_project_type = project_record.project_type or project_type
    runtime_origin = "factory_base_runtime"
    runtime_snapshot = None
    active_scenario_record = None
    runtime_warning = None

    # ── 4. Runtime guard + snapshot resolution ───────────────────────
    if project_record.project_origin == "user_created":
        # user_created branch
        # Phase PILOT-HOTFIX-3: export uses the latest successful runtime
        # evidence (last_runtime_snapshot + last_runtime_summary) when
        # present, instead of requiring the current form snapshot to
        # bit-match the saved runtime boundary. The /run endpoint still
        # enforces the strict boundary (Section 3 of execute_run_route);
        # export only needs a frozen, project-scoped runtime result.
        # - If last_runtime_snapshot exists, use it. The current form
        #   boundary is irrelevant for export — the user is asking for
        #   a workbook derived from a successful run, not a fresh run.
        # - If no last_runtime_snapshot exists, fail with a clear
        #   user-facing message ("Run the model before exporting.")
        #   rather than the generic runtime-boundary message.
        if (
            workspace_state is not None
            and workspace_state.last_runtime_snapshot
            and len(workspace_state.last_runtime_snapshot) > 0
        ):
            # Latest runtime evidence is available — use it directly.
            # PILOT-HOTFIX-3: skip the strict form-boundary check and
            # skip resolve_runtime_snapshot_source (which would re-resolve
            # from saved_snapshot or baseline_snapshot, potentially
            # missing the scenario override). The last_runtime_snapshot
            # was written by the most recent successful /run and is
            # the authoritative export input.
            runtime_snapshot = workspace_state.last_runtime_snapshot
            # Re-resolve active_scenario_record from active_scenario_id
            # so the workbook carries the right scenario provenance.
            if workspace_state.active_scenario_id:
                try:
                    from app.persistence.scenarios_repository import get_scenario as _ph3_get_scenario
                    active_scenario_record = _ph3_get_scenario(
                        workspace_state.active_scenario_id, user.user_id,
                    )
                except Exception:
                    active_scenario_record = None
            runtime_origin = "saved_state"
            runtime_warning = None
        else:
            # No successful runtime yet — give a clear, user-friendly
            # error instead of the strict form-boundary message.
            return _build_inline_error_outcome(
                message="Run the model before exporting. The export uses the most recent successful runtime result for this project.",
                status_code=400,
            )
        override = deps.build_projectinputs_from_snapshot(runtime_snapshot)
        runtime_project_key = (
            "Solar"
            if deps.canonical_project_type(effective_project_type) == "Solar"
            else "Wind"
        )
    else:
        # non-user_created branch
        if deps.check_runtime_allowed(workspace_state, snapshot)[1] == "saved_state" and workspace_state.active_scenario_id:
            # Quirk 3: mutate runtime_origin
            runtime_origin = "saved_state"
            runtime_snapshot, active_scenario_record, runtime_warning, _effective_runtime_origin = (
                deps.resolve_runtime_snapshot_source(
                    user, project_record, workspace_state, runtime_origin,
                )
            )
            override = deps.build_projectinputs_from_snapshot(runtime_snapshot)
        runtime_seed = deps.normalize_template_source(
            project_record.template_source or project_record.source_project_template,
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

    # ── 5. Model execution — PR-8 production authority seam ──────────
    # Clean-ready projects export values computed by the clean G2C authority
    # exactly once; blocked projects keep the explicitly classified legacy
    # demo funnel. No route-dependent authority.
    try:
        from app.services.production_waterfall_seam import execute_production_demo

        demo, _authority_meta = execute_production_demo(
            runtime_project_key, scenario, project_inputs_override=override,
        )
    except Exception as e:  # noqa: BLE001
        err_str = str(e)
        # Section F: SHL_MATURITY_RESIDUAL_FAILS_CLOSED means the project is
        # economically unserviceable under CASH_SWEEP (SHL balance remains at
        # contractual maturity). Return a user-facing 400 — not a 500.
        if "SHL_MATURITY_RESIDUAL_FAILS_CLOSED" in err_str or (
            hasattr(e, "__cause__") and e.__cause__ and "SHL_MATURITY_RESIDUAL_FAILS_CLOSED" in str(e.__cause__)
        ):
            return _build_inline_error_outcome(
                message=(
                    "The project cannot be exported: the shareholder loan balance cannot be "
                    "fully repaid within the project horizon under the current assumptions "
                    "(SHL_MATURITY_RESIDUAL_FAILS_CLOSED). Reduce capex, increase tariff, "
                    "or extend the horizon before exporting."
                ),
                status_code=400,
            )
        # Top-level broad catch (quirk 9)
        return _build_inline_error_outcome(
            message=err_str, status_code=500,
        )

    # ── 6. Replay metadata + provenance + Excel generation ───────────
    try:
        filename = f"finco_model_{project_type.lower()}_{scenario.lower()}.xlsx"
        scenario_provenance = deps.scenario_provenance_for_record(
            project_record, active_scenario_record,
        )
        replay_metadata = deps.replay_metadata_for_project(
            project_code,
            export_type="excel_model_export",
            workbook_type="values_only_excel_export",
            export_timestamp=deps.utc_now_iso(),
            runtime_timestamp=deps.utc_now_iso(),
            project_id=project_record.project_id if project_record else None,
            scenario_id=workspace_state.active_scenario_id if runtime_origin == "saved_state" else None,
            scenario_name=active_scenario_record.scenario_name if active_scenario_record else scenario,
            runtime_origin=runtime_origin,
            artifact_name=filename,
            project_inputs_override=demo.project_inputs,
            template_origin_override=(
                "saved_project_assumptions"
                if project_record.project_origin == "user_created"
                else None
            ),
            active_scenario_id=workspace_state.active_scenario_id if runtime_origin == "saved_state" else None,
            active_scenario_name=workspace_state.active_scenario_name if runtime_origin == "saved_state" else None,
            scenario_provenance=scenario_provenance,
            warning_note=runtime_warning,
        )
        if project_record:
            replay_metadata["project_origin"] = project_record.project_origin
        replay_metadata.setdefault("capex_sub_lines_audit_mode", "active_only")
        if project_record and project_record.project_origin == "saved_baseline":
            replay_metadata["baseline_source"] = True

        export = deps.build_excel_export_for_post_request(
            result=demo.result,
            project_inputs=demo.project_inputs,
            project_type=project_type,
            scenario=scenario,
            runtime_origin=runtime_origin,
            replay_metadata=replay_metadata,
        )

        if export.has_error():
            return _build_inline_error_outcome(
                message=export.error_content, status_code=export.status_code,
            )

        excel_bytes = export.bytes_data

        # ── 7. INTENDED export audit (preserved from Phase 49) ──────
        deps.record_download_export(
            user_id=user.user_id,
            project_code=project_code,
            export_type="excel_model_export",
            artifact_name=filename,
            artifact_path=f"/download?project_type={project_type}&scenario={scenario}",
            project_id=project_record.project_id if project_record else None,
            governance_state=deps.governance_snapshot(project_code),
            replay_metadata=replay_metadata,
            scenario_id=active_scenario_record.scenario_id if active_scenario_record else None,
        )

        # ── 8. Success outcome ────────────────────────────────────────
        return DownloadRouteOutcome(
            content=excel_bytes,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            filename=filename,
            status_code=200,
            headers={"Content-Length": str(len(excel_bytes))},
            is_error=False,
        )
    except Exception as e:  # noqa: BLE001
        # Top-level broad catch (quirk 9)
        return _build_inline_error_outcome(
            message=str(e), status_code=500,
        )


# ─────────────────────────────────────────────────────────────────────────────
# Service entry point — GET /download
# ─────────────────────────────────────────────────────────────────────────────


async def execute_get_download_route(
    *,
    request: Any,
    user: Any,
    project_type: str,
    scenario: str,
    deps: DownloadRouteDeps,
) -> DownloadRouteOutcome:
    """Execute the GET /download orchestration and return a
    ``DownloadRouteOutcome``.

    Behavior preserved from the legacy GET /download route
    (Phase 51E-1 characterization):

      * Auth redirect is route-owned.
      * Query params with defaults: project_type='Solar',
        scenario='Base' (empty-string fallbacks to defaults).
      * Model execution: ``run_demo_project(project_type, scenario)``
        (no ``project_inputs_override``).
      * **Quirk 2 (HARDCODED project_code mapping):**
        ``project_code = "generic_solar_reference" if project_type.lower() == "solar"
        else "generic_wind_reference"``. Does NOT use
        ``_project_workspace_from_snapshot``.
      * Project record lookup: ``get_project_by_code(user.user_id, project_code)``;
        may be ``None`` if no project exists.
      * Filename: ``f"finco_model_{project_type.lower()}_{scenario.lower()}.xlsx"``
        (constructed in route/orchestration).
      * Replay metadata with
        ``export_type='excel_model_export'``,
        ``workbook_type='values_only_excel_export'``, both
        ``export_timestamp`` and ``runtime_timestamp`` =
        ``utc_now_iso()``, ``runtime_origin='factory_base_runtime'``.
      * Baseline source flag.
      * Excel generation via
        ``build_values_only_export_for_project(...)``.
      * Export error check.
      * **Export audit (preserved, INTENDED):**
        ``record_download_export(...)`` with
        ``scenario_id=None`` (**quirk 7**).
      * Success: ``StreamingResponse`` with ``export.media_type``
        (**quirk 5**) and ``export.filename`` (**quirk 6**).
      * Top-level ``except Exception`` broad catch (preserved):
        500 inline error page.
    """
    try:
        # Defaults: empty string -> default
        project_type = project_type if project_type else "Solar"
        scenario = scenario if scenario else "Base"

        # ── 1. Model execution (no override) — PR-8 production authority ──
        from app.services.production_waterfall_seam import execute_production_demo

        demo, _authority_meta = execute_production_demo(project_type, scenario)

        # ── 2. Truthful project lineage (PR-8 final correction) ─────────
        # ARTIFACT_PROJECT_LINEAGE_MATCHES_EXECUTED_PROJECT: the replay/
        # project lineage must describe the SAME project snapshot the
        # authority executed. Generic Solar/Wind exports carry generic
        # lineage (no persisted record → None is truthful and preferred over
        # falsely binding the artifact to Generic Solar Reference/Generic Wind Reference). Input-resolution
        # mapping only — no financial dispatch.
        _lineage_key = {
            "solar": "generic_solar",
            "test 1": "generic_solar",
            "wind": "generic_wind",
            "test 2": "generic_wind",
            "generic_wind_reference": "generic_wind_reference",
            "generic_solar_reference": "generic_solar_reference",
        }.get(project_type.lower())
        project_code = _lineage_key or project_type.lower()
        project_record = deps.get_project_by_code(user.user_id, project_code)

        # ── 3. Filename (constructed in orchestration) ────────────────
        filename = f"finco_model_{project_type.lower()}_{scenario.lower()}.xlsx"

        # ── 4. Replay metadata ─────────────────────────────────────────
        replay_metadata = deps.replay_metadata_for_project(
            project_code,
            export_type="excel_model_export",
            workbook_type="values_only_excel_export",
            export_timestamp=deps.utc_now_iso(),
            runtime_timestamp=deps.utc_now_iso(),
            project_id=project_record.project_id if project_record else None,
            scenario_name=scenario,
            runtime_origin="factory_base_runtime",
            artifact_name=filename,
        )
        if project_record and project_record.project_origin == "saved_baseline":
            replay_metadata["baseline_source"] = True

        # ── 5. Excel generation ───────────────────────────────────────
        export = deps.build_values_only_export_for_project(
            demo.result,
            demo.project_inputs,
            project_type,
            scenario,
            replay_metadata=replay_metadata,
        )

        if export.has_error():
            return _build_inline_error_outcome(
                message=export.error_content, status_code=export.status_code,
            )

        # ── 6. INTENDED export audit (preserved, scenario_id=None) ───
        deps.record_download_export(
            user_id=user.user_id,
            project_code=project_code,
            export_type="excel_model_export",
            artifact_name=filename,
            artifact_path=f"/download?project_type={project_type}&scenario={scenario}",
            project_id=project_record.project_id if project_record else None,
            governance_state=deps.governance_snapshot(project_code),
            replay_metadata=replay_metadata,
            scenario_id=None,
        )

        # ── 7. Success outcome ────────────────────────────────────────
        return DownloadRouteOutcome(
            content=export.bytes_data,
            media_type=export.media_type,
            filename=export.filename,
            status_code=200,
            headers={"Content-Length": str(len(export.bytes_data))},
            is_error=False,
        )
    except Exception as e:  # noqa: BLE001
        # Top-level broad catch (quirk 9)
        return _build_inline_error_outcome(
            message=str(e), status_code=500,
        )


# ─────────────────────────────────────────────────────────────────────────────
# Public type aliases
# ─────────────────────────────────────────────────────────────────────────────

# These are intentionally loose: we accept anything with a form-like
# interface, including FastAPI's awaitable form. Keeping them as aliases
# avoids forcing ``fastapi.Request`` to be imported here.
RequestLike = Any
FormLike = Any
