"""
app.v2.router — Workbook V2 routes (always mounted; inactive-guard inside).

Mounted unconditionally in main_web.py so that GET /v2/workbook can issue
a 302 when the flag is off rather than returning a 404.  All mutation
endpoints reject requests with 409 via the require_v2_active dependency
when the flag is inactive.  See app/utils/workbook_flag.py for the flag
contract (absent → ACTIVE).

Authentication
--------------
Uses the canonical session resolver ``app.auth.resolve_request_session``
(cookie(s) → signed token → ``SessionData``), shared with main_web and the
Library so every surface interprets the same session material identically.
The resolved identity may be an admin or a demo session; its ``user_id``
attribute is used to scope DB lookups, matching the legacy convention in all
other routes.

Current routes
--------------
GET /v2/workbook
    Single-sheet workbook shell.  Accepts the same ``?project=`` query
    parameter as the legacy ``GET /``.  Returns a minimal HTML page built
    from the V2 template skeleton.  Schedule data is hydrated via the
    RuntimeResult sessionStorage script so the page loads without a model
    re-run.

    Protected reference projects (Generic Wind Reference/Generic Solar Reference factory_template origin)
    render in read-only mode with a working-copy CTA.  All other projects
    show live edit controls for the six BOUND Project Setup fields.

POST /v2/workbook/update
    Canonical V2 field edit endpoint.  Accepts a single field_id + value
    plus optimistic-concurrency token (content_hash).  Full pipeline:

      semantic field_id
      → WorkbookUpdateService.validate_field_update()
      → ProjectInputSet.with_value()
      → v2_atomic_draft_update() (BEGIN EXCLUSIVE)
      → HTMX partial response OR 303 redirect

    No legacy snapshot keys may appear in the request body.
    Protected references (Generic Wind Reference/Generic Solar Reference) are rejected with 409.
    Stale content_hash is rejected with 409.

HTMX behaviour
--------------
If the POST carries ``HX-Request: true``:
  - success: returns the re-rendered #v2-sheet-project-setup partial
    (all forms carry the new content_hash) plus an OOB status banner.
  - validation / stale / version error: returns the same partial with
    the fresh state and an error message in the OOB status banner.
Non-HTMX fallback: 303 redirect on success; redirect with ?v2_err=… on error.

Scope constraints
-----------------
- No engine calls, no formula logic, no parity changes.
- No legacy ``_collect_form_snapshot`` / ``_strip_empty_fields`` helpers.
- No reuse of ``build_input_set_from_workspace`` (removed in PR 4).
"""
from __future__ import annotations

import datetime
import os
import urllib.parse
from typing import Optional

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.utils.workbook_flag import (
    inputs_slice1_active,
    project_workbook_url,
    require_v2_active,
    workbook_v2_active,
)

from app.auth import resolve_request_session
from app.ui.capex_view_model import build_capex_view_model
from app.ui.inputs_summary import build_inputs_summary
from app.ui.opex_sheet_projection import build_opex_sheet_projection
from app.ui.opex_view_model import build_opex_view_model
from app.ui.inputs_slice1 import (
    build_inputs_slice1_sections,
    classify_slice1_field_id,
    slice1_rejection_message,
    KNOWN_SLICE1_EDITABLE,
)
from app.ui.project_context import build_project_context_for_record
from app.ui.protected_reference_service import is_protected_reference
from app.v2.scenario_presentation import OVERRIDE_EDITOR_FIELDS
from app.workbook.registry import WORKBOOK
from app.workbook.service import WorkbookService
from app.workbook.workbook_identity import assemble_consistent_for_get, assemble_for_workspace
from app.workbook.update_service import (
    FieldValidationError,
    NonEditableFieldError,
    ProtectedReferenceError,
    StaleContentError,
    UnknownFieldError,
    VersionMismatchError,
    WorkbookUpdateService,
)

router = APIRouter()

# The remove-override HTTP surface is intentionally narrower than the generic
# persistence API. Derive its authority from the fields exposed by the V2
# Scenario Override Editor so internal scenario payloads cannot be removed by
# a crafted request and the UI/router contracts cannot drift independently.
_REMOVABLE_OVERRIDE_FIELDS = frozenset(
    field_key for field_key, _label, _unit in OVERRIDE_EDITOR_FIELDS
)


def _fmt_runtime_at(ts: str) -> str:
    """Format an ISO timestamp into a human-readable string for the toolbar."""
    if not ts:
        return ""
    try:
        dt = datetime.datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return dt.strftime("%-d %b %Y, %H:%M")
    except Exception:
        return ts


def _build_pis_with_composite_identity(ws, project_record, workspace_owner_id: str):
    """Build ProjectInputSet with composite Workbook V2 identity.

    STAB-1B: uses assemble_consistent_for_get to read all four sources
    (workspace snapshot, CAPEX rows, OPEX rows, active scenario) inside a
    single consistent SQLite transaction.  The resulting composite hash is
    injected into the PIS so every form the browser receives carries a
    fully consistent workbook identity token.

    workspace_owner_id must be the owner of the workspace (REFERENCE_USER_ID
    for system reference projects, user.user_id for user-owned projects).
    """
    pis = WorkbookService.build_draft_input_set_from_workspace(ws)
    identity = assemble_consistent_for_get(
        user_id=workspace_owner_id,
        project_id=project_record.project_id,
        workbook_version=pis.workbook_version,
    )
    return pis.with_composite_hash(identity.composite_hash)


def _runtime_freshness(ws, pis):
    """Resolve presentation freshness from the canonical composite identity."""
    from app.workbook.runtime_authority import resolve_runtime_freshness

    return resolve_runtime_freshness(
        ws, current_composite_hash=getattr(pis, "content_hash", None)
    )


def _add_field_saved_trigger(resp: HTMLResponse, field_id: str, new_hash: str) -> HTMLResponse:
    import json as _json
    resp.headers["HX-Trigger"] = _json.dumps({
        "workbook-field-saved": {"field_id": field_id, "new_hash": new_hash}
    })
    return resp


def _add_field_error_trigger(resp: HTMLResponse, field_id: str, message: str) -> HTMLResponse:
    import json as _json
    resp.headers["HX-Trigger"] = _json.dumps({
        "workbook-field-error": {"field_id": field_id, "message": message}
    })
    return resp


def _cit_rate_display(pis) -> str:
    """Return CIT rate as a display string like '20.0%', or '—' if unavailable."""
    try:
        pi = pis.to_projectinputs()
        rate = pi.tax.corporate_rate
        if rate is None:
            return "—"
        return f"{round(rate * 100, 1):.1f}%"
    except Exception:
        return "—"


BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "app", "templates", "v2"))


def _get_current_user(request: Request):
    """Return the resolved SessionData (admin or demo), or None.

    Delegates to the canonical app.auth.resolve_request_session so Workbook
    V2 interprets session cookies exactly like main_web and the Library.
    """
    return resolve_request_session(request)


_SENIOR_UNRESOLVED = "UNRESOLVED"
_SENIOR_UNRESOLVED_NOTE = (
    "Senior authority unavailable — assumption cannot be edited safely.")
_SENIOR_LOCK_NOTE = (
    "Explicit calibrated period schedule controls this assumption.")


def _classify_senior_authority(pis):
    """R8 Correction A: classify (pricing_mode, dscr_mode) from the typed
    Senior capability of the materialised working copy.

    Fail-closed: when the working copy cannot be materialised, BOTH modes
    are ``UNRESOLVED`` — no factory is ever substituted and the original
    exception is logged with full context for diagnosis.  UNRESOLVED locks
    both scalar controls (see ``_lock_senior_fields_if_calibrated``)."""
    from app.input_adapter import senior_dscr_authority, senior_rate_authority
    from app.workbook.service import WorkbookService as _WS

    try:
        _pi = _WS.to_projectinputs(pis)
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning(
            "R8/N02: senior authority unresolvable (%s: %s) — "
            "Senior scalars locked.", type(exc).__name__, exc, exc_info=True)
        return _SENIOR_UNRESOLVED, _SENIOR_UNRESOLVED
    return senior_rate_authority(_pi)[0], senior_dscr_authority(_pi)[0]


def _lock_senior_fields_if_calibrated(debt_fields, pricing_mode, dscr_mode):
    """Mark the Senior scalar rows read-only with the honest reason when the
    typed authority is a calibrated schedule or cannot be resolved."""
    locked = {}
    if pricing_mode == "CALIBRATED":
        locked["debt.senior.interest_rate_pct"] = _SENIOR_LOCK_NOTE
    elif pricing_mode == _SENIOR_UNRESOLVED:
        locked["debt.senior.interest_rate_pct"] = _SENIOR_UNRESOLVED_NOTE
    if dscr_mode == "CALIBRATED":
        locked["debt.senior.target_dscr"] = _SENIOR_LOCK_NOTE
    elif dscr_mode == _SENIOR_UNRESOLVED:
        locked["debt.senior.target_dscr"] = _SENIOR_UNRESOLVED_NOTE
    for row in debt_fields:
        reason = locked.get(row["field_id"])
        if reason:
            row["binding_label"] = "template-locked"
            row["editable"] = False
            row["help_text"] = reason
            row["label"] = row["label"] + " (schedule-locked)"
    return debt_fields


def _build_sheet_fields(sheet_id: str, pis) -> list[dict]:
    """Build the field context list for any registry sheet.

    Returns one dict per FieldSpec ordered by section.order then field.order.
    Values come exclusively from pis.get(field_id).

    binding_label encodes the registry contract:
      "bound"           — BOUND INPUT, editable via the V2 save endpoint
      "partial"         — PARTIAL; partially wired to engine
      "display-only"    — DERIVED_DISPLAY; computed, never user-editable
      "template-locked" — TEMPLATE_LOCKED; frozen at project creation

    Validation metadata (required, min_value, max_value, step, help_text)
    is propagated from FieldSpec so templates can render HTML5 attrs without
    any field-specific knowledge.
    """
    from app.workbook.specs import BindingStatus
    sheet = WORKBOOK.sheet(sheet_id)
    rows: list[dict] = []
    for section in sorted(sheet.sections, key=lambda s: s.order):
        for fspec in sorted(section.fields, key=lambda f: f.order):
            bs = fspec.binding_status
            if bs == BindingStatus.DISPLAY_ONLY:
                binding_label = "display-only"
            elif bs == BindingStatus.TEMPLATE_LOCKED:
                binding_label = "template-locked"
            elif bs == BindingStatus.PARTIAL:
                binding_label = "partial"
            else:
                binding_label = "bound"

            field_type = fspec.field_type.value

            # Derive HTML step from registry decimals + field type.
            # Integer-typed fields always use step=1 regardless of decimals.
            if field_type in ("months", "years", "int"):
                step = "1"
            elif fspec.decimals is not None:
                if fspec.decimals == 0:
                    step = "1"
                else:
                    step = str(round(10 ** (-fspec.decimals), fspec.decimals))
            else:
                step = "any"

            value = pis.get(fspec.field_id)
            rows.append({
                "field_id": fspec.field_id,
                "label": fspec.label,
                "unit": fspec.unit,
                "field_type": field_type,
                "binding_label": binding_label,
                "options": list(fspec.options),
                "section_id": section.section_id,
                "section_label": section.label,
                "value": value,
                "required": fspec.required,
                "min_value": fspec.min_value,
                "max_value": fspec.max_value,
                "step": step,
                "help_text": fspec.description or "",
            })
    return rows


def _build_ps_fields(pis) -> list[dict]:
    """Build project_setup field list — delegates to _build_sheet_fields."""
    return _build_sheet_fields("project_setup", pis)


def _get_inputs_summary(project_record, pis, ws) -> dict:
    """Delegate to the canonical Inputs summary adapter.

    All CAPEX/OPEX aggregation is performed by build_inputs_summary using
    the canonical CapexViewModel and OpexViewModel — the same code paths
    used by the detailed CAPEX and OPEX sheets.  No field lists, no
    formulas, and no ViewModel construction live here.
    """
    return build_inputs_summary(project_record, pis, ws)


def _base_sheet_ctx(request, pis, ws, project_record, project, field_error=""):
    """Shared context dict for both sheet partials."""
    freshness = _runtime_freshness(ws, pis)
    return {
        "request": request,
        "project_code": project,
        "workbook_version": pis.workbook_version,
        "content_hash": pis.content_hash,
        "template_source": pis.template_source,
        "project_editable": not is_protected_reference(project_record),
        "ws_dirty": ws.dirty,
        "runtime_is_stale": freshness.is_stale,
        "runtime_state": freshness.state.value,
        "has_runtime": bool(ws.last_runtime_snapshot_id),
        "last_runtime_at": _fmt_runtime_at(getattr(ws, "last_runtime_at", None) or ""),
        "field_error": field_error,
        "active_scenario_name": getattr(ws, "active_scenario_name", None) or "",
    }


def _build_run_controls_oob(ctx: dict) -> str:
    """Return OOB HTML to refresh #v2-run-controls with the current composite hash."""
    run_controls_html = _templates.get_template("partials/_v2_run_controls.html").render(ctx)
    return '<div id="v2-run-controls" hx-swap-oob="true">' + run_controls_html + "</div>"


def _build_export_controls_oob(ctx: dict) -> str:
    """Return OOB HTML to refresh #v2-export-controls after a run."""
    export_html = _templates.get_template("partials/_v2_export_controls.html").render(ctx)
    return '<div id="v2-export-controls" hx-swap-oob="true">' + export_html + "</div>"


def _build_toolbar_state_oob(ctx: dict) -> str:
    """Return OOB HTML to refresh the toolbar runtime state chip."""
    toolbar_html = _templates.get_template("partials/_v2_toolbar_state.html").render(ctx)
    return '<div id="v2-toolbar-runtime-state" hx-swap-oob="true">' + toolbar_html + "</div>"


def _render_htmx_sheet(
    request: Request,
    pis,
    ws,
    project_record,
    project: str,
    field_error: str = "",
) -> HTMLResponse:
    """Render the project_setup sheet partial + OOB status banner for HTMX."""
    ctx = _base_sheet_ctx(request, pis, ws, project_record, project, field_error)
    ctx["ps_fields"] = _build_ps_fields(pis)
    sheet_html = _templates.get_template("partials/sheet_project_setup.html").render(ctx)
    banner_html = _templates.get_template("partials/_v2_status_banner.html").render(ctx)
    oob = '<div id="v2-status-banner" hx-swap-oob="true">' + banner_html + "</div>"
    if not field_error:
        oob += "\n" + _build_run_controls_oob(ctx)
    return HTMLResponse(content=sheet_html + "\n" + oob)


def _build_capex_vm_ctx(project_record, pis, ws=None, workspace_owner: str = "") -> dict:
    """Build CapexViewModel context for the CAPEX sheet.

    Returns capex_vm, capex_group_to_field, and capex_section_fields.
    All CAPEX financial totals come exclusively from CapexViewModel.
    No field lists, formulas, or aggregation are computed here.

    ``ws`` (workspace state) is optional; when supplied, the active scenario's
    ``_capex_sub_line_overrides`` are applied to sub-line amounts so the
    display matches the same effective economics as the Run path.
    """
    from app.persistence.capex_sub_lines import CAPEX_CATEGORY_TO_FIELD
    from app.input_adapter import build_projectinputs_from_snapshot

    snapshot = pis.to_snapshot()
    effective_pi = build_projectinputs_from_snapshot(snapshot)
    project_ctx = build_project_context_for_record(
        project_code=project_record.project_code,
        project_name=project_record.project_name,
        project_type=project_record.project_type,
        project_origin=project_record.project_origin,
        template_source=project_record.template_source,
        baseline_snapshot=snapshot,
        effective_project_inputs=effective_pi,
    )
    is_user = not (
        project_record.project_origin == "factory_template"
        and (project_record.template_source or "").strip().lower() in ("generic_wind_reference", "generic_solar_reference", "generic_storage_reference")
    )

    # Load active user-added sub-lines and apply any active scenario's
    # _capex_sub_line_overrides so the display matches the Run path exactly.
    from app.persistence.capex_sub_lines import get_active_sub_lines_for_project
    from app.services.capex_sub_lines_integration import _extract_sub_line_overrides
    import dataclasses as _dc

    sub_lines = list(get_active_sub_lines_for_project(project_record.project_id))

    # Resolve scenario overrides using the same contract as the Run path (Step 8).
    # Unlike the Run path which returns an HTTP error on failure, the display path
    # must still render — but it MUST NOT silently show Base economics when a
    # scenario is active and resolution fails.  Instead we surface an explicit
    # capex_scenario_error that the template renders as a visible warning.
    _scenario_overrides_raw = None
    capex_scenario_error: str = ""

    if ws is not None and getattr(ws, "active_scenario_id", None):
        _effective_owner = workspace_owner or project_record.project_code
        _active_scenario_id = ws.active_scenario_id
        try:
            from app.persistence.scenarios_repository import get_scenario as _get_sc
            _sc_rec = _get_sc(scenario_id=_active_scenario_id, user_id=_effective_owner)
            if _sc_rec is None:
                capex_scenario_error = (
                    f"Active scenario could not be found (id={_active_scenario_id!r}). "
                    "Re-select a scenario to see scenario economics."
                )
            elif _sc_rec.archived:
                capex_scenario_error = (
                    "Active scenario has been archived. "
                    "Re-select a scenario to see scenario economics."
                )
            elif _sc_rec.project_id != project_record.project_id:
                import logging as _log
                _log.getLogger(__name__).warning(
                    "_build_capex_vm_ctx: scenario project_id mismatch "
                    "scenario=%s scenario.project_id=%s expected=%s",
                    _active_scenario_id, _sc_rec.project_id, project_record.project_id,
                )
                capex_scenario_error = (
                    "Active scenario does not belong to this project. "
                    "Re-select a scenario to see scenario economics."
                )
            else:
                _scenario_overrides_raw = _sc_rec.overrides
        except Exception:
            import logging as _log
            _log.getLogger(__name__).exception(
                "_build_capex_vm_ctx: scenario repository lookup failed scenario=%s",
                _active_scenario_id,
            )
            capex_scenario_error = (
                "Scenario data could not be loaded. "
                "Re-select a scenario or reload the page."
            )

    from app.services.capex_sub_lines_integration import SubLineOverrideNonFiniteError
    try:
        sub_line_override_amounts = _extract_sub_line_overrides(_scenario_overrides_raw)
    except SubLineOverrideNonFiniteError as _nf_exc:
        # R3/F05: a historical persisted override carries NaN/Inf.
        # Surface an explicit error rather than silently showing Base economics.
        sub_line_override_amounts = {}
        if not capex_scenario_error:
            capex_scenario_error = (
                f"Scenario contains a non-finite CAPEX sub-line amount "
                f"and cannot be displayed. Re-select a scenario or contact support. "
                f"({_nf_exc})"
            )
    if sub_line_override_amounts:
        adjusted = []
        for sl in sub_lines:
            if sl.sub_line_id in sub_line_override_amounts:
                try:
                    sl = _dc.replace(sl, amount_keur=float(sub_line_override_amounts[sl.sub_line_id]))
                except Exception:
                    pass
            adjusted.append(sl)
        sub_lines = adjusted

    capex_vm = build_capex_view_model(project_ctx, is_user_project=is_user, sub_lines=sub_lines)

    # Registry field list for capex; keyed by short name for group mapping
    capex_fields = _build_sheet_fields("capex", pis)
    fields_by_key = {f["field_id"].split(".")[-1]: f for f in capex_fields}

    # Mapping: Excel group code → registry field dict.
    # C.08 and C.11 share the same registry field (capex.D.audit_legal).
    # The FIRST occurrence (C.08) gets the editable render_field form.
    # The SECOND occurrence (C.11) gets a read-only alias row that clearly
    # labels it as a shared field so neither group is silently hidden.
    #
    # capex_alias_groups: group code → {"owner": first_group_code, "field": field_dict}
    # Template uses this to render the SHARED FIELD badge on the alias group.
    seen_field_keys: dict[str, str] = {}   # field_key → first group code that owns it
    capex_group_to_field: dict[str, dict | None] = {}
    capex_alias_groups: dict[str, dict] = {}  # alias code → {owner, field}
    for code, field_key in CAPEX_CATEGORY_TO_FIELD.items():
        if field_key in seen_field_keys:
            # This group is an alias — the field is owned by an earlier group
            capex_group_to_field[code] = None
            capex_alias_groups[code] = {
                "owner": seen_field_keys[field_key],
                "field": fields_by_key.get(field_key),
            }
        else:
            capex_group_to_field[code] = fields_by_key.get(field_key)
            seen_field_keys[field_key] = code

    # Mapping: registry section_id → list of field dicts
    capex_section_fields: dict[str, list] = {}
    for f in capex_fields:
        capex_section_fields.setdefault(f["section_id"], []).append(f)

    return {
        "capex_vm": capex_vm,
        "capex_group_to_field": capex_group_to_field,
        "capex_section_fields": capex_section_fields,
        "capex_alias_groups": capex_alias_groups,
        "capex_scenario_error": capex_scenario_error,
    }


def _render_capex_htmx_sheet(
    request: Request,
    pis,
    ws,
    project_record,
    project: str,
    field_error: str = "",
    workspace_owner: str = "",
) -> HTMLResponse:
    """Render the CAPEX sheet partial + OOB status banner for HTMX."""
    ctx = _base_sheet_ctx(request, pis, ws, project_record, project, field_error)
    ctx.update(_build_capex_vm_ctx(project_record, pis, ws=ws, workspace_owner=workspace_owner))
    sheet_html = _templates.get_template("partials/sheet_capex.html").render(ctx)
    banner_html = _templates.get_template("partials/_v2_status_banner.html").render(ctx)
    oob = '<div id="v2-status-banner" hx-swap-oob="true">' + banner_html + "</div>"
    if not field_error:
        oob += "\n" + _build_run_controls_oob(ctx)
    return HTMLResponse(content=sheet_html + "\n" + oob)


def _build_opex_vm_ctx(project_record, pis) -> dict:
    """Build OpexViewModel context for the OPEX sheet.

    Delegates B.01–B.13 canonical structure to build_opex_sheet_projection()
    in app.ui.opex_sheet_projection.  The router owns no OPEX domain mappings.

    Returns opex_vm and opex_sheet_groups (always 13 OpexSheetGroup objects
    in canonical order — present for every project regardless of ViewModel
    group coverage).

    Per-line OPEX overrides are materialised by build_projectinputs_from_snapshot
    (via WorkbookService.to_projectinputs).  The effective ProjectInputs are passed
    to build_project_context_for_record so both display and Run use the same
    canonical effective OPEX — no separate display-layer recomputation.
    """
    from app.workbook.service import WorkbookService
    from app.revenue_input_validation import RevenueInputError
    try:
        effective_pi = WorkbookService.to_projectinputs(pis)
    except RevenueInputError:
        # Cross-field revenue validation (e.g. CONTRACT_ANNIVERSARY without a
        # date) must not break the OPEX display path — OPEX is independent of
        # PPA indexation policy.  Strip the incomplete revenue policy from the
        # snapshot and retry so the OPEX view model renders normally.
        _snap = dict(pis.to_snapshot())
        _snap.pop("rev_ppa_indexation_start_policy", None)
        from app.input_adapter import build_projectinputs_from_snapshot
        effective_pi = build_projectinputs_from_snapshot(_snap)
    snapshot = pis.to_snapshot()
    project_ctx = build_project_context_for_record(
        project_code=project_record.project_code,
        project_name=project_record.project_name,
        project_type=project_record.project_type,
        project_origin=project_record.project_origin,
        template_source=project_record.template_source,
        baseline_snapshot=snapshot,
        effective_project_inputs=effective_pi,
    )
    is_user = not (
        project_record.project_origin == "factory_template"
        and (project_record.template_source or "").strip().lower() in ("generic_wind_reference", "generic_solar_reference", "generic_storage_reference")
    )
    from app.persistence.opex_sub_lines import get_active_sub_lines_for_project as _get_opex_sub_lines
    opex_sub_lines = _get_opex_sub_lines(project_record.project_id)
    opex_vm = build_opex_view_model(project_ctx, is_user_project=is_user, sub_lines=opex_sub_lines)
    opex_fields = _build_sheet_fields("opex", pis)
    opex_sheet_groups = build_opex_sheet_projection(opex_vm, opex_fields)
    # F06 Correction A: escalation display helper for the group rows
    from app.ui.opex_view_model import group_escalation_display as _group_escalation_display
    opex_escalation_displays = {
        g.code: _group_escalation_display(g) for g in opex_vm.groups
    }

    # Summary section fields (e.g. opex.summary.total_y1 PARTIAL) rendered separately
    # at the bottom of the sheet so PARTIAL fields are never silently filtered out.
    opex_summary_fields = [f for f in opex_fields if f["section_id"] == "summary"]

    # F06 — competing OPEX display authority. The registry field
    # opex.summary.total_y1 is a persisted "display anchor" (snapshot scalar
    # opex_y1_keur) seeded once at project creation and never recomputed by
    # any OPEX mutation. Rendering that stale scalar on the same sheet as the
    # live KPI strip and grand total presents two competing "Total OPEX Y1"
    # authorities. The registry declares this field DERIVED from the per-line
    # OpexItems, so its displayed value is the live OpexViewModel Y1 total —
    # the identical number the sheet's dominant authority (KPI strip + grand
    # total row) already renders. Presentation only: the persisted anchor and
    # every engine input are untouched.
    for _summary_field in opex_summary_fields:
        if _summary_field["field_id"] == "opex.summary.total_y1":
            _summary_field["value"] = opex_vm.y1_total_opex

    # F06 Correction A — escalation display authority. The summary strip's
    # "Escalation" card previously showed the FIRST line's escalation (or a
    # fabricated 2.0% default) as if it governed the whole sheet.  The
    # effective engine-bound escalation is PER LINE (annual_inflation on
    # each effective OPEX item, consumed by the frozen orchestrator); a
    # single rate is displayed only when every line shares it, otherwise
    # the card is explicitly context-only.  Presentation layer: no engine
    # formula or persisted value is touched.
    _esc_rates = sorted({
        round(float(item.annual_inflation) * 100, 1)
        for item in effective_pi.opex
    })
    if not _esc_rates:
        _esc_value, _esc_label = "—", "no budget lines"
    elif len(_esc_rates) == 1:
        _esc_value = f"{_esc_rates[0]:.1f}%"
        _esc_label = "per annum — uniform across lines"
    else:
        _esc_value = "mixed"
        _esc_label = "varies by line — per-line rates are authoritative"

    return {
        "opex_vm": opex_vm,
        "opex_sheet_groups": opex_sheet_groups,
        "opex_escalation_displays": opex_escalation_displays,
        "opex_summary_fields": opex_summary_fields,
        "opex_escalation_summary": {
            "value": _esc_value,
            "label": _esc_label,
        },
    }


def _render_opex_htmx_sheet(
    request: Request,
    pis,
    ws,
    project_record,
    project: str,
    field_error: str = "",
) -> HTMLResponse:
    """Render the OPEX sheet partial + OOB status banner for HTMX."""
    ctx = _base_sheet_ctx(request, pis, ws, project_record, project, field_error)
    ctx.update(_build_opex_vm_ctx(project_record, pis))
    sheet_html = _templates.get_template("partials/sheet_opex.html").render(ctx)
    banner_html = _templates.get_template("partials/_v2_status_banner.html").render(ctx)
    oob = '<div id="v2-status-banner" hx-swap-oob="true">' + banner_html + "</div>"
    if not field_error:
        oob += "\n" + _build_run_controls_oob(ctx)
    return HTMLResponse(content=sheet_html + "\n" + oob)


def _build_revenue_ctx(pis, ws, projection=None) -> dict:
    """Build Revenue sheet context: registry fields + runtime derivation evidence.

    Revenue has no separate RuntimeResult sub-payload (unlike debt/tax/fs).
    Runtime evidence lives in runtime_summary["revenue_derivation"] which is
    always present on a successful run.  State classification reuses the
    same classify_runtime_state helper so the Revenue bar uses the same four
    states as the other output sheets.

    When a pre-built WorkbookRuntimeProjection bundle is supplied (GET handler),
    the runtime_summary is read from projection.fs.runtime_summary — it is the
    same thawed dict as rr.runtime_summary and avoids a second get_runtime_result call.
    """
    from app.workbook.runtime_projection import (
        build_runtime_projection_bundle,
        classify_runtime_state,
        thaw_runtime_payload,
    )
    from app.workbook.service import WorkbookService

    if projection is None:
        rr = WorkbookService.get_runtime_result(ws)
        projection = build_runtime_projection_bundle(
            rr, _runtime_freshness(ws, pis).is_stale)
        rs = thaw_runtime_payload(rr.runtime_summary) if rr else None
    else:
        # Re-use runtime_summary already thawed by fs projection (same dict);
        # avoids a second get_runtime_result call in the GET handler path.
        rs = projection.fs.runtime_summary

    # Classify revenue state using the shared FS projection meta (not Debt).
    # Revenue has no separate payload — its presence is determined by runtime_summary
    # existing at all, not by whether the debt schedule was produced.
    meta = projection.fs.meta
    revenue_derivation = rs.get("revenue_derivation") if rs else None
    # classify_runtime_state treats None as NOT_RUN; any truthy sentinel as "rr present".
    _rr_sentinel = object() if meta.has_runtime else None
    revenue_state = classify_runtime_state(_rr_sentinel, revenue_derivation, meta.is_dirty)

    return {
        "revenue_fields": _build_sheet_fields("revenue", pis),
        "revenue_state": revenue_state.value,
        "revenue_runtime_summary": rs,
    }


def _render_revenue_htmx_sheet(
    request: Request,
    pis,
    ws,
    project_record,
    project: str,
    field_error: str = "",
    projection=None,
) -> HTMLResponse:
    """Render the revenue sheet partial + OOB status banner for HTMX."""
    ctx = _base_sheet_ctx(request, pis, ws, project_record, project, field_error)
    ctx.update(_build_revenue_ctx(pis, ws, projection=projection))
    sheet_html = _templates.get_template("partials/sheet_revenue.html").render(ctx)
    banner_html = _templates.get_template("partials/_v2_status_banner.html").render(ctx)
    oob = '<div id="v2-status-banner" hx-swap-oob="true">' + banner_html + "</div>"
    if not field_error:
        oob += "\n" + _build_run_controls_oob(ctx)
    return HTMLResponse(content=sheet_html + "\n" + oob)


def _thaw(obj):
    """Recursively convert MappingProxyType to plain dict for Jinja2 iteration."""
    from app.workbook.runtime_projection import thaw_runtime_payload
    return thaw_runtime_payload(obj)


def _build_debt_ctx(pis, ws, projection=None) -> dict:
    """Build Senior Debt sheet context: registry fields + RuntimeResult output.

    When a pre-built WorkbookRuntimeProjection bundle is supplied (GET handler),
    it is reused so that only one get_runtime_result call is made per request.
    When called standalone (HTMX sheet re-render), the bundle is built here.
    """
    from app.workbook.runtime_projection import build_runtime_projection_bundle
    from app.workbook.service import WorkbookService
    if projection is None:
        rr = WorkbookService.get_runtime_result(ws)
        from app.workbook.runtime_projection import build_runtime_projection_bundle
        projection = build_runtime_projection_bundle(
            rr, _runtime_freshness(ws, pis).is_stale)
    d = projection.debt
    # R8/N02: policy-governed editability — calibrated schedules lock the
    # scalar Senior controls with the honest reason.
    senior_pricing_mode, senior_dscr_mode = _classify_senior_authority(pis)
    debt_fields = _lock_senior_fields_if_calibrated(
        _build_sheet_fields("debt", pis),
        senior_pricing_mode, senior_dscr_mode)
    return {
        "debt_fields": debt_fields,
        "debt_state": d.state.value,
        "debt_schedule": d.schedule,
        "debt_operational_periods": d.operational_periods,
        "runtime_summary": d.runtime_summary,
        "senior_pricing_mode": senior_pricing_mode,
        "senior_dscr_mode": senior_dscr_mode,
        "senior_lock_reason": (
            _SENIOR_LOCK_NOTE if (
                senior_pricing_mode == "CALIBRATED"
                or senior_dscr_mode == "CALIBRATED")
            else (
                _SENIOR_UNRESOLVED_NOTE if (
                    senior_pricing_mode == _SENIOR_UNRESOLVED
                    or senior_dscr_mode == _SENIOR_UNRESOLVED) else "")
        )
    }


def _render_debt_htmx_sheet(
    request: Request,
    pis,
    ws,
    project_record,
    project: str,
    field_error: str = "",
    projection=None,
) -> HTMLResponse:
    """Render the Senior Debt sheet partial + OOB status banner for HTMX."""
    ctx = _base_sheet_ctx(request, pis, ws, project_record, project, field_error)
    ctx.update(_build_debt_ctx(pis, ws, projection=projection))
    sheet_html = _templates.get_template("partials/sheet_senior_debt.html").render(ctx)
    banner_html = _templates.get_template("partials/_v2_status_banner.html").render(ctx)
    oob = '<div id="v2-status-banner" hx-swap-oob="true">' + banner_html + "</div>"
    if not field_error:
        oob += "\n" + _build_run_controls_oob(ctx)
    return HTMLResponse(content=sheet_html + "\n" + oob)


def _build_tax_ctx(pis, ws, projection=None) -> dict:
    """Build Tax sheet context: registry fields + RuntimeResult output.

    ``tax_fields`` contains the two BOUND Tax registry fields rendered in
    Section A via the render_field macro (cit_rate_pct, loss_carryforward_years).

    Option B hydration fills None values from pis.to_projectinputs().tax
    without calling the engine or writing to the snapshot.

    When a pre-built WorkbookRuntimeProjection bundle is supplied (GET handler),
    it is reused so that only one get_runtime_result call is made per request.
    """
    from app.workbook.runtime_projection import build_runtime_projection_bundle
    from app.workbook.service import WorkbookService
    if projection is None:
        rr = WorkbookService.get_runtime_result(ws)
        projection = build_runtime_projection_bundle(
            rr, _runtime_freshness(ws, pis).is_stale)
    t = projection.tax
    raw_fields = _build_sheet_fields("tax", pis)

    # Option B — effective-value projection.
    # When a Tax snapshot key is absent, pis.get(field_id) returns None even
    # though the engine would use a concrete factory default.  Project the
    # canonical effective value from pis.to_projectinputs().tax so the first
    # load shows real defaults rather than empty fields.
    # This path never calls the engine, never hard-codes a rate, never
    # writes to the snapshot, and never marks the workspace dirty.
    if any(f["value"] is None for f in raw_fields):
        from app.revenue_input_validation import RevenueInputError
        try:
            effective_tax = pis.to_projectinputs().tax
        except RevenueInputError:
            _snap = dict(pis.to_snapshot())
            _snap.pop("rev_ppa_indexation_start_policy", None)
            from app.input_adapter import build_projectinputs_from_snapshot
            effective_tax = build_projectinputs_from_snapshot(_snap).tax
        _TAX_FIELD_MAP = {
            "tax.assumptions.cit_rate_pct": lambda tx: round(tx.corporate_rate * 100, 10),
            "tax.assumptions.loss_carryforward_years": lambda tx: tx.loss_carryforward_years,
        }
        for f in raw_fields:
            if f["value"] is None:
                proj_fn = _TAX_FIELD_MAP.get(f["field_id"])
                if proj_fn is not None:
                    f["value"] = proj_fn(effective_tax)

    return {
        "tax_fields": raw_fields,
        "tax_state": t.state.value,
        "tax_schedule": t.schedule,
        "tax_operational_periods": t.operational_periods,
        "runtime_summary": t.runtime_summary,
    }


def _render_tax_htmx_sheet(
    request: Request,
    pis,
    ws,
    project_record,
    project: str,
    field_error: str = "",
    projection=None,
) -> HTMLResponse:
    """Render the Tax sheet partial + OOB status banner for HTMX."""
    ctx = _base_sheet_ctx(request, pis, ws, project_record, project, field_error)
    ctx.update(_build_tax_ctx(pis, ws, projection=projection))
    sheet_html = _templates.get_template("partials/sheet_tax.html").render(ctx)
    banner_html = _templates.get_template("partials/_v2_status_banner.html").render(ctx)
    oob = '<div id="v2-status-banner" hx-swap-oob="true">' + banner_html + "</div>"
    if not field_error:
        oob += "\n" + _build_run_controls_oob(ctx)
    return HTMLResponse(content=sheet_html + "\n" + oob)


# ── Legacy re-exports kept for backward compatibility with existing tests ──── #
# The canonical implementations live in app.workbook.runtime_projection.
from app.workbook.runtime_projection import (  # noqa: E402
    FS_PNL_ROW_DEFS    as _FS_PNL_ROW_DEFS,
    FS_PF_CF_ROW_DEFS  as _FS_PF_CF_ROW_DEFS,
    FS_BS_ROW_DEFS     as _FS_BS_ROW_DEFS,
    project_rows       as _fs_project_rows,
    project_period_labels as _fs_period_labels,
    fs_classify_statement as _fs_classify,
)

_FS_STATE_NOT_RUN        = "NOT_RUN"
_FS_STATE_CLEAN          = "CLEAN"
_FS_STATE_STALE          = "STALE"
_FS_STATE_FS_UNAVAILABLE = "FS_UNAVAILABLE"


def _build_financial_statements_ctx(pis, ws, projection=None) -> dict:
    """Build Financial Statements sheet context from persisted RuntimeResult.

    When a pre-built WorkbookRuntimeProjection bundle is supplied (GET handler),
    it is reused so that only one get_runtime_result call is made per request.
    """
    from app.workbook.runtime_projection import build_runtime_projection_bundle
    from app.workbook.service import WorkbookService
    if projection is None:
        rr = WorkbookService.get_runtime_result(ws)
        projection = build_runtime_projection_bundle(
            rr, _runtime_freshness(ws, pis).is_stale)
    f = projection.fs
    # Map the FS UNAVAILABLE state to the legacy template key for backward compat
    fs_state = f.state.value if f.state.value != "UNAVAILABLE" else "FS_UNAVAILABLE"
    return {
        "fs_state": fs_state,
        "fs_available": f.fs_available,
        "fs_pnl_rows": f.pnl_rows,
        "fs_bs_rows": f.bs_rows,
        "fs_pf_cf_rows": f.pf_cf_rows,
        "fs_pnl_period_labels": f.pnl_period_labels,
        "fs_bs_period_labels": f.bs_period_labels,
        "fs_pf_cf_period_labels": f.pf_cf_period_labels,
        "fs_pnl_classification": f.pnl_classification,
        "fs_bs_classification": f.bs_classification,
        "fs_pf_cf_classification": f.pf_cf_classification,
        "runtime_summary": f.runtime_summary,
        "fs_pnl_annual_rows": f.pnl_annual_rows,
        "fs_bs_annual_rows": f.bs_annual_rows,
        "fs_pf_cf_annual_rows": f.pf_cf_annual_rows,
        "fs_pnl_annual_labels": f.pnl_annual_labels,
        "fs_bs_annual_labels": f.bs_annual_labels,
        "fs_pf_cf_annual_labels": f.pf_cf_annual_labels,
        "fs_cit_rate_display": _cit_rate_display(pis),
    }


def _build_returns_ctx(ws, rr=None, *, runtime_is_stale=None) -> dict:
    """Build Returns context from the persisted Last Run only."""
    from app.v2.returns_projection import build_returns_projection
    from app.workbook.service import WorkbookService

    if rr is None:
        rr = WorkbookService.get_runtime_result(ws)
    return {"returns": build_returns_projection(
        rr, ws, runtime_is_stale=runtime_is_stale)}


def _build_all_oob(ws, *, request=None, project_record=None, project="",
                   workspace_owner="") -> str:
    """R6 Correction A: full post-Save stale-state refresh after a mutation.

    A financially causal successful Save (workspace now dirty, prior runtime
    still persisted) must make every visible runtime-state surface agree
    STALE in the same HTMX response: toolbar, Overview stale classification,
    debt/tax/FS runtime bars, scenario last-run statuses.  No engine call,
    no financial calculation.  Must NOT be appended on validation-error
    responses — those never mutate state.
    """
    from app.v2.post_run_ui import build_post_save_ui_state

    return build_post_save_ui_state(
        ws_fresh=ws, project_record=project_record, project=project,
        workspace_owner=workspace_owner, request=request,
    )


# Legacy alias so tests that imported the old helper continue to pass.
def _build_fs_runtime_bar_oob(ws) -> str:
    from app.workbook.runtime_projection import build_runtime_projection_bundle
    from app.v2.runtime_projection_views import build_fs_bar_oob
    from app.workbook.service import WorkbookService
    rr = WorkbookService.get_runtime_result(ws)
    projection = build_runtime_projection_bundle(rr, ws.dirty)
    return build_fs_bar_oob(projection)


def _render_financial_statements_htmx_sheet(
    request: Request,
    pis,
    ws,
    project_record,
    project: str,
    field_error: str = "",
) -> HTMLResponse:
    """Render the Financial Statements sheet partial + OOB status banner for HTMX."""
    ctx = _base_sheet_ctx(request, pis, ws, project_record, project, field_error)
    ctx.update(_build_financial_statements_ctx(pis, ws))
    sheet_html = _templates.get_template("partials/sheet_financial_statements.html").render(ctx)
    banner_html = _templates.get_template("partials/_v2_status_banner.html").render(ctx)
    oob = '<div id="v2-status-banner" hx-swap-oob="true">' + banner_html + "</div>"
    if not field_error:
        oob += "\n" + _build_run_controls_oob(ctx)
    return HTMLResponse(content=sheet_html + "\n" + oob)


def _render_inputs_htmx_sheet(
    request: Request,
    pis,
    ws,
    project_record,
    project: str,
    field_error: str = "",
    slice1_submitted_values: Optional[dict[str, str]] = None,
    slice1_field_errors: Optional[dict[str, str]] = None,
) -> HTMLResponse:
    """Render the inputs sheet partial + OOB status banner for HTMX."""
    ctx = _base_sheet_ctx(request, pis, ws, project_record, project, field_error)
    project_editable = not is_protected_reference(project_record)
    ctx.update({
        "technical_fields": _build_sheet_fields("project_setup", pis),
        "revenue_fields": _build_sheet_fields("revenue", pis),
        "capex_fields": _build_sheet_fields("capex", pis),
        "opex_fields": _build_sheet_fields("opex", pis),
        "debt_fields": _lock_senior_fields_if_calibrated(
            _build_sheet_fields("debt", pis),
            *_classify_senior_authority(pis)),
        "inputs_summary": _get_inputs_summary(project_record, pis, ws),
        "inputs_slice1_enabled": inputs_slice1_active(),
        "inputs_slice1_sections": build_inputs_slice1_sections(
            pis,
            project_editable=project_editable,
            submitted_values=slice1_submitted_values,
            field_errors=slice1_field_errors,
        ),
    })
    sheet_html = _templates.get_template("partials/sheet_inputs.html").render(ctx)
    banner_html = _templates.get_template("partials/_v2_status_banner.html").render(ctx)
    oob = '<div id="v2-status-banner" hx-swap-oob="true">' + banner_html + "</div>"
    if not field_error:
        oob += "\n" + _build_run_controls_oob(ctx)
    return HTMLResponse(content=sheet_html + "\n" + oob)


@router.get("/workbook", response_class=HTMLResponse)
async def v2_workbook(request: Request, project: Optional[str] = None, sheet: Optional[str] = None):
    """Workbook V2 shell page.

    Renders the V2 template skeleton and injects a sessionStorage hydration
    script from the persisted RuntimeResult (if one exists), so schedule
    data is available to the page on load without a model re-run.

    Protected reference projects (Generic Wind Reference/Generic Solar Reference factory_template origin)
    render all fields read-only with a working-copy CTA.

    Query parameters
    ----------------
    project : str, optional
        Project code.  When absent, redirects to the project home.
    sheet : str, optional
        Sheet name (e.g. "inputs").  Preserved on inactive redirect so the
        legacy URL fragment (#inputs) is reconstructed correctly.
    v2_err : str, optional
        URL-encoded error message from a failed non-HTMX POST.  Shown as
        a flash error in the status banner.
    """
    if not workbook_v2_active():
        if project:
            dest = project_workbook_url(project, sheet=sheet)
        else:
            dest = "/library"
        return RedirectResponse(url=dest, status_code=302)

    user = _get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    if not project:
        return RedirectResponse(url="/library", status_code=302)

    from app.persistence.projects_repository import resolve_accessible_project
    from app.persistence.workspace_repository import get_workspace_state

    project_record, workspace_owner = resolve_accessible_project(user.user_id, project)
    if project_record is None:
        return RedirectResponse(url="/library", status_code=302)

    ws = get_workspace_state(user_id=workspace_owner, project_id=project_record.project_id)
    if ws is None:
        return RedirectResponse(url="/library", status_code=302)

    # Decide unsupported runtime capability immediately after access and
    # workspace resolution.  Storage must return its controlled surface before
    # migrations, ProjectInputSet construction, hydration, or any economic
    # resolver can read or mutate its persisted state.
    _project_type_lower = (getattr(project_record, "project_type", "") or "").strip().lower()
    if _project_type_lower == "storage":
        from app.utils.workbook_flag import project_workbook_url as _wbu
        _storage_ref_url = _wbu("generic_storage_reference-reference")
        if is_protected_reference(project_record):
            return _templates.TemplateResponse(
                request=request,
                name="unsupported_workbook.html",
                context={
                    "user": user,
                    "project_code": project,
                    "project_name": project_record.project_name or project,
                    "project_type": project_record.project_type or "Storage",
                    "is_reference": True,
                    "library_url": "/library",
                    "reference_url": _storage_ref_url,
                    "reference_label": "Back to Model Workspace",
                },
            )
        return _templates.TemplateResponse(
            request=request,
            name="unsupported_workbook.html",
            context={
                "user": user,
                "project_code": project,
                "project_name": project_record.project_name or project,
                "project_type": project_record.project_type or "Storage",
                "is_reference": False,
                "library_url": "/library",
                "reference_url": _storage_ref_url,
                "reference_label": "View Storage Reference",
            },
        )

    # Migration: backfill missing canonical revenue keys for old Generic Solar Reference working
    # copies created before C2B3 (idempotent — only writes when keys are absent).
    try:
        from app.services.revenue_backfill import persist_revenue_backfill
        if persist_revenue_backfill(project_record.project_id, workspace_owner, project_record):
            ws = get_workspace_state(user_id=workspace_owner, project_id=project_record.project_id) or ws
    except Exception:
        pass  # migration failure must never block page render

    pis = _build_pis_with_composite_identity(ws, project_record, workspace_owner)
    runtime_freshness = _runtime_freshness(ws, pis)
    hydration_script = WorkbookService.runtime_hydration_script(ws)

    project_editable = not is_protected_reference(project_record)

    flash_error = ""
    raw_err = request.query_params.get("v2_err", "")
    if raw_err:
        try:
            flash_error = urllib.parse.unquote_plus(raw_err)[:500]
        except Exception:
            pass

    context = {
        "project_code": project,
        "project_name": project_record.project_name or project,
        "project_type": (project_record.project_type or "").capitalize(),
        "active_scenario_name": ws.active_scenario_name or "",
        "active_scenario_id": ws.active_scenario_id or "",
        "last_runtime_at": _fmt_runtime_at(getattr(ws, "last_runtime_at", None) or ""),
        "workbook_version": pis.workbook_version,
        "content_hash": pis.content_hash,
        "template_source": pis.template_source,
        "hydration_script": hydration_script,
        "ps_fields": _build_ps_fields(pis),
        "technical_fields": _build_sheet_fields("project_setup", pis),
        "capex_fields": _build_sheet_fields("capex", pis),
        "opex_fields": _build_sheet_fields("opex", pis),
        "debt_fields": _lock_senior_fields_if_calibrated(
            _build_sheet_fields("debt", pis),
            *_classify_senior_authority(pis)),
        "inputs_summary": _get_inputs_summary(project_record, pis, ws),
        "inputs_slice1_enabled": inputs_slice1_active(),
        "inputs_slice1_sections": build_inputs_slice1_sections(
            pis,
            project_editable=project_editable,
        ),
        "user": user,
        "project_editable": project_editable,
        "ws_dirty": ws.dirty,
        "runtime_is_stale": runtime_freshness.is_stale,
        "runtime_state": runtime_freshness.state.value,
        "has_runtime": bool(ws.last_runtime_snapshot_id),
        "flash_error": flash_error,
        "field_error": "",
        "scenario_url": f"/scenarios?project={urllib.parse.quote(project, safe='')}",
        "library_url": "/library",
    }
    context.update(_build_capex_vm_ctx(project_record, pis, ws=ws, workspace_owner=workspace_owner))
    context.update(_build_opex_vm_ctx(project_record, pis))
    # Build projection bundle once; pass it to all four output sheet builders.
    from app.workbook.runtime_projection import build_runtime_projection_bundle
    _rr = WorkbookService.get_runtime_result(ws)
    _projection = build_runtime_projection_bundle(
        _rr, runtime_freshness.is_stale)
    context.update(_build_revenue_ctx(pis, ws, projection=_projection))
    context.update(_build_debt_ctx(pis, ws, projection=_projection))
    context.update(_build_tax_ctx(pis, ws, projection=_projection))
    context.update(_build_financial_statements_ctx(pis, ws, projection=_projection))
    context.update(_build_returns_ctx(
        ws, rr=_rr, runtime_is_stale=runtime_freshness.is_stale))
    from app.v2.overview_projection import build_overview_projection
    context["overview"] = build_overview_projection(
        _rr, runtime_freshness.is_stale, pis,
        active_scenario_name=ws.active_scenario_name or "")

    # UI-3B: inject scenario presentations for the Scenarios tab.
    # GF-F05: pass runtime_freshness.is_stale so the GET path and OOB path
    # apply the same canonical freshness decision to scenario cards.
    try:
        from app.persistence.scenarios_repository import list_scenarios
        from app.v2.scenario_presentation import build_scenario_presentations
        _sc_records = list_scenarios(
            user_id=workspace_owner,
            project_id=project_record.project_id,
            include_archived=False,
        )
        _active_sc_id = ws.active_scenario_id if ws else None
        context["scenarios"] = build_scenario_presentations(
            _sc_records, _active_sc_id, global_is_stale=runtime_freshness.is_stale)
        context["active_scenario_id"] = _active_sc_id
    except Exception:
        context["scenarios"] = []
        context.setdefault("active_scenario_id", None)

    return _templates.TemplateResponse(request=request, name="workbook.html", context=context)


@router.post("/workbook/inputs-slice1/update")
async def v2_inputs_slice1_update(
    request: Request,
    field_id: str = Form(...),
    value: Optional[str] = Form(default=""),
    project: str = Form(...),
    workbook_version: str = Form(...),
    content_hash: str = Form(...),
    _: None = Depends(require_v2_active),
):
    """Feature-flagged Slice 1 edit endpoint.

    The endpoint is intentionally narrower than the general V2 edit endpoint:
    it accepts only fields classified as EDITABLE_BOUND in the Slice 1
    projection, then delegates validation/persistence to
    WorkbookUpdateService.apply_draft_update().
    """
    if not inputs_slice1_active():
        return JSONResponse({"error": "Inputs Slice 1 is disabled by configuration."}, status_code=409)

    user = _get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    is_htmx = request.headers.get("HX-Request") == "true"

    from app.persistence.projects_repository import resolve_accessible_project
    from app.persistence.workspace_repository import get_workspace_state

    project_record, workspace_owner = resolve_accessible_project(user.user_id, project)
    if project_record is None:
        return JSONResponse({"error": f"Project {project!r} not found."}, status_code=404)

    ws = get_workspace_state(user_id=workspace_owner, project_id=project_record.project_id)
    if ws is None:
        return JSONResponse({"error": "Workspace not found."}, status_code=404)

    def _json_error(message: str, status_code: int) -> JSONResponse:
        return JSONResponse({"error": message}, status_code=status_code)

    def _render_sheet_response(
        message: str = "",
        *,
        status_code: int = 200,
        preserve_submitted: bool = False,
        pis_for_render=None,
        ws_for_render=None,
    ) -> HTMLResponse:
        render_ws = ws_for_render or ws
        render_pis = pis_for_render
        if render_pis is None:
            render_pis = _build_pis_with_composite_identity(
                render_ws, project_record, workspace_owner
            )
        submitted = (
            {field_id: value or ""}
            if preserve_submitted and classify_slice1_field_id(field_id) == KNOWN_SLICE1_EDITABLE
            else None
        )
        errors = (
            {field_id: message}
            if message and classify_slice1_field_id(field_id) == KNOWN_SLICE1_EDITABLE
            else None
        )
        resp = _render_inputs_htmx_sheet(
            request,
            render_pis,
            render_ws,
            project_record,
            project,
            field_error=message,
            slice1_submitted_values=submitted,
            slice1_field_errors=errors,
        )
        resp.status_code = status_code
        return resp

    def _render_field_error(message: str, status_code: int, *, preserve_submitted: bool = False) -> HTMLResponse:
        pis_for_render = _build_pis_with_composite_identity(
            ws, project_record, workspace_owner
        )
        resp = _render_sheet_response(
            message,
            status_code=status_code,
            preserve_submitted=preserve_submitted,
            pis_for_render=pis_for_render,
        )
        return _add_field_error_trigger(resp, field_id, message)

    field_classification = classify_slice1_field_id(field_id)
    if field_classification != KNOWN_SLICE1_EDITABLE:
        status_code = 422
        msg = slice1_rejection_message(field_id, field_classification)
        return (
            _render_field_error(msg, status_code)
            if is_htmx else _json_error(msg, status_code)
        )

    try:
        updated_pis = WorkbookUpdateService.apply_draft_update(
            ws=ws,
            field_id=field_id,
            raw_value=value or "",
            content_hash=content_hash,
            workbook_version=workbook_version,
            project_record=project_record,
        )
    except ProtectedReferenceError as exc:
        return (
            _render_field_error(str(exc), 409)
            if is_htmx else _json_error(str(exc), 409)
        )
    except StaleContentError:
        msg = "Draft changed since page loaded - values refreshed. Please try your edit again."
        return _render_field_error(msg, 409) if is_htmx else _json_error(msg, 409)
    except VersionMismatchError as exc:
        if is_htmx:
            return HTMLResponse(
                content=str(exc),
                status_code=409,
                headers={"HX-Refresh": "true"},
            )
        return _json_error(str(exc), 409)
    except (UnknownFieldError, NonEditableFieldError) as exc:
        return (
            _render_field_error(str(exc), 422)
            if is_htmx else _json_error(str(exc), 422)
        )
    except FieldValidationError as exc:
        return (
            _render_field_error(str(exc), 422, preserve_submitted=True)
            if is_htmx else _json_error(str(exc), 422)
        )

    updated_ws_after = get_workspace_state(
        user_id=workspace_owner, project_id=project_record.project_id
    ) or ws
    try:
        updated_identity = assemble_consistent_for_get(
            user_id=workspace_owner,
            project_id=project_record.project_id,
            workbook_version=updated_pis.workbook_version,
        )
        updated_pis = updated_pis.with_composite_hash(updated_identity.composite_hash)
    except Exception:
        pass

    if is_htmx:
        resp = _render_sheet_response(
            pis_for_render=updated_pis,
            ws_for_render=updated_ws_after,
        )
        all_bars_oob = _build_all_oob(
            updated_ws_after,
            request=request,
            project_record=project_record,
            project=project,
            workspace_owner=workspace_owner,
        )
        final_resp = HTMLResponse(content=resp.body.decode() + "\n" + all_bars_oob)
        return _add_field_saved_trigger(final_resp, field_id, updated_pis.content_hash)

    return RedirectResponse(url=f"/v2/workbook?project={project}", status_code=303)


@router.post("/workbook/update")
async def v2_workbook_update(
    request: Request,
    field_id: str = Form(...),
    value: Optional[str] = Form(default=""),
    project: str = Form(...),
    workbook_version: str = Form(...),
    content_hash: str = Form(...),
    sheet_id: str = Form(default="project_setup"),
    _: None = Depends(require_v2_active),
):
    """V2 field edit endpoint — canonical edit pipeline.

    Accepts a single field update identified by semantic field_id (never a
    legacy snapshot key).  Applies optimistic concurrency via content_hash.

    HTMX (HX-Request: true):
        success → re-rendered sheet partial + OOB status banner (HTTP 200)
        error   → re-rendered sheet partial with error in status banner (HTTP 200)
    Non-HTMX:
        success → 303 redirect to GET /v2/workbook?project=<project>
        error   → 303 redirect with ?v2_err=<encoded message>
    """
    user = _get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    is_htmx = request.headers.get("HX-Request") == "true"

    from app.persistence.projects_repository import resolve_accessible_project
    from app.persistence.workspace_repository import get_workspace_state

    project_record, _workspace_owner = resolve_accessible_project(user.user_id, project)
    if project_record is None:
        return JSONResponse({"error": f"Project {project!r} not found."}, status_code=404)

    # Block mutations on protected reference projects.
    from app.services.project_library_service import is_protected_reference
    if is_protected_reference(project_record):
        return JSONResponse(
            {"error": "This is a protected reference model. Create a working copy to edit it."},
            status_code=403,
        )

    ws = get_workspace_state(user_id=_workspace_owner, project_id=project_record.project_id)
    if ws is None:
        return JSONResponse({"error": "Workspace not found."}, status_code=404)

    def _redirect_with_error(message: str) -> RedirectResponse:
        """Non-HTMX error: redirect to GET with flash message in ?v2_err."""
        err_param = urllib.parse.quote_plus(message)
        return RedirectResponse(
            url=f"/v2/workbook?project={project}&v2_err={err_param}",
            status_code=303,
        )

    def _htmx_error(pis_for_render, field_error: str) -> HTMLResponse:
        if sheet_id == "inputs":
            return _render_inputs_htmx_sheet(
                request, pis_for_render, ws, project_record, project,
                field_error=field_error,
            )
        if sheet_id == "revenue":
            return _render_revenue_htmx_sheet(
                request, pis_for_render, ws, project_record, project,
                field_error=field_error,
            )
        if sheet_id == "capex":
            return _render_capex_htmx_sheet(
                request, pis_for_render, ws, project_record, project,
                field_error=field_error,
                workspace_owner=_workspace_owner,
            )
        if sheet_id == "opex":
            return _render_opex_htmx_sheet(
                request, pis_for_render, ws, project_record, project,
                field_error=field_error,
            )
        if sheet_id == "debt":
            return _render_debt_htmx_sheet(
                request, pis_for_render, ws, project_record, project,
                field_error=field_error,
            )
        if sheet_id == "tax":
            return _render_tax_htmx_sheet(
                request, pis_for_render, ws, project_record, project,
                field_error=field_error,
            )
        if sheet_id == "financial_statements":
            return _render_financial_statements_htmx_sheet(
                request, pis_for_render, ws, project_record, project,
                field_error=field_error,
            )
        return _render_htmx_sheet(
            request, pis_for_render, ws, project_record, project,
            field_error=field_error,
        )

    try:
        updated_pis = WorkbookUpdateService.apply_draft_update(
            ws=ws,
            field_id=field_id,
            raw_value=value or "",
            content_hash=content_hash,
            workbook_version=workbook_version,
            project_record=project_record,
        )
    except ProtectedReferenceError as exc:
        if is_htmx:
            pis = _build_pis_with_composite_identity(ws, project_record, _workspace_owner)
            resp = _htmx_error(pis, str(exc))
            return _add_field_error_trigger(resp, field_id, str(exc))
        return JSONResponse({"error": str(exc)}, status_code=409)
    except StaleContentError as exc:
        if is_htmx:
            pis = _build_pis_with_composite_identity(ws, project_record, _workspace_owner)
            msg = (
                "Draft changed since page loaded — values refreshed. "
                "Please try your edit again."
            )
            resp = _htmx_error(pis, msg)
            return _add_field_error_trigger(resp, field_id, msg)
        return _redirect_with_error(str(exc))
    except VersionMismatchError as exc:
        return JSONResponse({"error": str(exc), "reload": True}, status_code=409)
    except (UnknownFieldError, NonEditableFieldError) as exc:
        return JSONResponse({"error": str(exc)}, status_code=422)
    except FieldValidationError as exc:
        if is_htmx:
            pis = _build_pis_with_composite_identity(ws, project_record, _workspace_owner)
            resp = _htmx_error(pis, str(exc))
            return _add_field_error_trigger(resp, field_id, str(exc))
        return _redirect_with_error(str(exc))

    # Success path — reload workspace and assemble composite identity consistently
    # so the re-rendered sheet carries a hash over the full post-mutation state.
    updated_ws_after = get_workspace_state(
        user_id=_workspace_owner, project_id=project_record.project_id
    ) or ws
    try:
        updated_identity = assemble_consistent_for_get(
            user_id=_workspace_owner,
            project_id=project_record.project_id,
            workbook_version=updated_pis.workbook_version,
        )
        updated_pis = updated_pis.with_composite_hash(updated_identity.composite_hash)
    except Exception:
        pass  # scalar hash already set by v2_atomic_draft_update; best-effort only

    if is_htmx:
        # Dispatch to the correct sheet renderer.
        if sheet_id == "inputs":
            resp = _render_inputs_htmx_sheet(
                request, updated_pis, updated_ws_after, project_record, project,
            )
        elif sheet_id == "revenue":
            resp = _render_revenue_htmx_sheet(
                request, updated_pis, updated_ws_after, project_record, project,
            )
        elif sheet_id == "capex":
            resp = _render_capex_htmx_sheet(
                request, updated_pis, updated_ws_after, project_record, project,
                workspace_owner=_workspace_owner,
            )
            # R6 Correction A: stale-state refresh (see opex branch).
            from app.v2.post_run_ui import build_post_save_ui_state

            _stale_refresh = build_post_save_ui_state(
                ws_fresh=updated_ws_after,
                project_record=project_record,
                project=project,
                workspace_owner=_workspace_owner,
            )
            resp = HTMLResponse(content=resp.body.decode() + "\n" + _stale_refresh)
        elif sheet_id == "opex":
            resp = _render_opex_htmx_sheet(
                request, updated_pis, updated_ws_after, project_record, project,
            )
            # R6 Correction B: OPEX field forms swap hx-target="#panel-opex"
            # with hx-swap="outerHTML" — the response must re-emit the PANEL
            # wrapper, otherwise the swap destroys #panel-opex and the OPEX
            # tab can never be shown again.  hx-swap-oob fragments in the
            # body are extracted by htmx before the swap, so they are not
            # nested into the panel.
            panel_open = (
                '<div class="v2-sheet-panel" role="tabpanel" id="panel-opex" '
                'aria-labelledby="tab-opex">'
                '<div class="v2-sheet-body">'
            )
            resp = HTMLResponse(
                content=panel_open + resp.body.decode() + "</div></div>")
            # R6 Correction A: these sheets have no runtime-derived values,
            # but the save made the workspace dirty — toolbar, Overview and
            # scenario statuses must agree stale in this same response.
            from app.v2.post_run_ui import build_post_save_ui_state

            _stale_refresh = build_post_save_ui_state(
                ws_fresh=updated_ws_after,
                project_record=project_record,
                project=project,
                workspace_owner=_workspace_owner,
            )
            resp = HTMLResponse(content=resp.body.decode() + "\n" + _stale_refresh)
        elif sheet_id == "debt":
            # Build projection once — pass to both sheet renderer and OOB bars.
            # ONE get_runtime_result call is made here (inside build_post_save_ui_state
            # via the fallback path when projection is None, or zero extra calls when
            # the caller already has a pre-built projection).
            from app.workbook.runtime_projection import build_runtime_projection_bundle
            from app.v2.runtime_projection_views import build_all_runtime_bar_oob
            from app.workbook.service import WorkbookService
            from app.v2.post_run_ui import build_post_save_ui_state
            _rr = WorkbookService.get_runtime_result(updated_ws_after)
            _proj = build_runtime_projection_bundle(_rr, updated_ws_after.dirty)
            resp = _render_debt_htmx_sheet(
                request, updated_pis, updated_ws_after, project_record, project,
                projection=_proj,
            )
            body = resp.body.decode() + "\n" + build_all_runtime_bar_oob(_proj)
            # R6 Correction A: stale-state refresh — pass pre-built rr+proj so
            # build_post_save_ui_state skips its own get_runtime_result call.
            # When _rr is None (no prior run), still pass it: the function
            # guards with `if rr is None` and will not re-call get_runtime_result
            # because _rr was already fetched above (it returned None once; no
            # second fetch needed — projection was built from None correctly).
            body += "\n" + build_post_save_ui_state(
                ws_fresh=updated_ws_after,
                project_record=project_record,
                project=project,
                workspace_owner=_workspace_owner,
                include_runtime_bars=False,
                rr=_rr,
                projection=_proj,
            )
            return _add_field_saved_trigger(HTMLResponse(content=body), field_id, updated_pis.content_hash)
        elif sheet_id == "tax":
            from app.workbook.runtime_projection import build_runtime_projection_bundle
            from app.v2.runtime_projection_views import build_all_runtime_bar_oob
            from app.workbook.service import WorkbookService
            from app.v2.post_run_ui import build_post_save_ui_state
            _rr = WorkbookService.get_runtime_result(updated_ws_after)
            _proj = build_runtime_projection_bundle(_rr, updated_ws_after.dirty)
            resp = _render_tax_htmx_sheet(
                request, updated_pis, updated_ws_after, project_record, project,
                projection=_proj,
            )
            body = resp.body.decode() + "\n" + build_all_runtime_bar_oob(_proj)
            # R6 Correction A: stale-state refresh (see debt branch).
            body += "\n" + build_post_save_ui_state(
                ws_fresh=updated_ws_after,
                project_record=project_record,
                project=project,
                workspace_owner=_workspace_owner,
                include_runtime_bars=False,
                rr=_rr,
                projection=_proj,
            )
            return _add_field_saved_trigger(HTMLResponse(content=body), field_id, updated_pis.content_hash)
        elif sheet_id == "financial_statements":
            # Full sheet re-render already contains #fs-runtime-bar; no OOB needed.
            resp = _render_financial_statements_htmx_sheet(
                request, updated_pis, updated_ws_after, project_record, project,
            )
            return _add_field_saved_trigger(resp, field_id, updated_pis.content_hash)
        else:
            resp = _render_htmx_sheet(
                request, updated_pis, updated_ws_after, project_record, project,
            )
        # Append OOB refresh of all three runtime bars so that editing any
        # sheet immediately reflects the dirty/clean state on Debt, Tax, and
        # Financial Statements without a full page reload.
        all_bars_oob = _build_all_oob(
            updated_ws_after,
            request=request,
            project_record=project_record,
            project=project,
            workspace_owner=_workspace_owner,
        )
        final_resp = HTMLResponse(content=resp.body.decode() + "\n" + all_bars_oob)
        return _add_field_saved_trigger(final_resp, field_id, updated_pis.content_hash)

    return RedirectResponse(
        url=f"/v2/workbook?project={project}",
        status_code=303,
    )


@router.post("/workbook/run")
async def v2_workbook_run(
    request: Request,
    project: str = Form(...),
    content_hash: str = Form(...),
    workbook_version: str = Form(...),
    _: None = Depends(require_v2_active),
):
    """V2 Run endpoint — canonical engine orchestration for Workbook V2.

    Pipeline (all checks fail-closed):
      1.  Auth
      2.  Load project_record + workspace_state
      3.  Runtime guard: check_runtime_allowed(ws, ws.draft_snapshot)
      4.  Version check: workbook_version must match WORKBOOK.version
      5.  Pre-engine identity CAS: content_hash must match current composite hash
      6.  Project type validation: Solar→"Solar", Wind→"Wind", else error
      7.  Materialise: build_draft_input_set_from_workspace(ws).to_projectinputs()
          (draft_snapshot is the canonical V2 run boundary after V2 edits)
      8.  Scenario resolution via get_scenario — fail closed on error
      9.  CAPEX fold (replace-semantics)
      10. OPEX fold (additive)
      11. run_project(project_type, scenario_name, project_inputs_override=override)
      12. v2_atomic_run_commit: final CAS + promote draft→saved + dirty=False
          Raises V2RunCommitConflictError if workbook changed during engine run
      13. ws_fresh = get_workspace_state(...); rr = WorkbookService.get_runtime_result(ws_fresh)
      14. build_runtime_projection_bundle(rr, ws_fresh.dirty)
      15. HTMX response: #v2-run-controls + #v2-status-banner + three sheet OOBs

    HTMX: always responds with 200 + HTML fragments (success or user-safe error).
    Non-HTMX: 303 redirect on success; redirect with ?v2_err=... on error.

    Scope constraints — NO engine formula modifications, NO parity changes.
    """
    from datetime import datetime, timezone

    from app.api.project_runner import run_project
    from app.persistence.workspace_repository import (
        V2RunCommitConflictError,
        get_workspace_state,
        v2_atomic_run_commit,
    )
    from app.services.capex_sub_lines_integration import apply_user_sub_lines_replacing_base
    from app.services.opex_sub_lines_integration import apply_user_sub_lines_to_opex
    from app.workbook.registry import WORKBOOK
    from app.workbook.runtime_projection import build_runtime_projection_bundle
    from app.workbook.workbook_identity import WorkbookIdentityError

    def _utc_compact() -> str:
        return datetime.now(timezone.utc).isoformat().replace(":", "").replace("-", "")

    user = _get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    is_htmx = request.headers.get("HX-Request") == "true"

    def _htmx_error(msg: str, ws_for_render=None) -> HTMLResponse:
        ctx: dict = {
            "ws_dirty": getattr(ws_for_render, "dirty", True),
            "has_runtime": bool(
                getattr(ws_for_render, "last_runtime_snapshot_id", None)
            ) if ws_for_render else False,
            "field_error": msg,
            "flash_error": "",
        }
        banner_html = _templates.get_template(
            "partials/_v2_status_banner.html"
        ).render(ctx)
        oob = '<div id="v2-status-banner" hx-swap-oob="true">' + banner_html + "</div>"
        return HTMLResponse(content=oob)

    def _non_htmx_error(msg: str) -> RedirectResponse:
        return RedirectResponse(
            url=f"/v2/workbook?project={project}&v2_err={urllib.parse.quote_plus(msg)}",
            status_code=303,
        )

    from app.persistence.projects_repository import resolve_accessible_project
    project_record, workspace_owner = resolve_accessible_project(user.user_id, project)
    if project_record is None:
        msg = f"Project {project!r} not found."
        return _htmx_error(msg) if is_htmx else _non_htmx_error(msg)

    ws = get_workspace_state(user_id=workspace_owner, project_id=project_record.project_id)
    if ws is None:
        msg = "Workspace not found."
        return _htmx_error(msg) if is_htmx else _non_htmx_error(msg)

    # ── Step 2b: unsupported project-type guard ───────────────────────────── #
    # Must come BEFORE the hash check so Storage projects always receive 409
    # (both HTMX and non-HTMX) rather than a stale-hash 303 redirect.
    # Covers all user-owned Storage projects (not just working_copy role) via
    # the is_protected_reference check — the capability boundary is
    # "protected reference" vs "user-owned editable project".
    _run_type_lower = (getattr(project_record, "project_type", "") or "").strip().lower()
    if _run_type_lower not in ("solar", "wind") and not is_protected_reference(project_record):
        _raw_type = project_record.project_type or "Unknown"
        msg = (
            f"{_raw_type} working-copy runtime is not yet supported. "
            "This project has not been modified. Return to the Model Workspace."
        )
        if is_htmx:
            # Return 409 with banner fragment; HTMX callers must also receive
            # a real non-success status — do not return 200 for HTMX here.
            banner_html = _templates.get_template("partials/_v2_status_banner.html").render({
                "ws_dirty": getattr(ws, "dirty", True),
                "has_runtime": bool(getattr(ws, "last_runtime_snapshot_id", None)),
                "field_error": msg,
                "flash_error": "",
            })
            oob = '<div id="v2-status-banner" hx-swap-oob="true">' + banner_html + "</div>"
            return HTMLResponse(content=oob, status_code=409)
        return JSONResponse({"error": msg}, status_code=409)

    # ── Step 3: V2 runtime origin ──────────────────────────────────────────── #
    # V2 runs always materialise from draft_snapshot and promote it to
    # saved_snapshot atomically.  The legacy runtime_guard_for_snapshot blocks
    # dirty workspaces (designed for the legacy saved-state-only run path).
    # V2 uses CAS-based locking (content_hash + final CAS) instead, so we
    # skip the legacy guard and assign the origin directly.
    runtime_origin = "v2_run"

    # ── Step 4: version check ──────────────────────────────────────────────── #
    pis_draft = WorkbookService.build_draft_input_set_from_workspace(ws)
    if pis_draft.workbook_version != workbook_version:
        msg = "Workbook version mismatch — please reload the page."
        return _htmx_error(msg, ws) if is_htmx else _non_htmx_error(msg)

    # ── Step 5: pre-engine identity CAS ───────────────────────────────────── #
    try:
        current_identity = assemble_consistent_for_get(
            user_id=workspace_owner,
            project_id=project_record.project_id,
            workbook_version=pis_draft.workbook_version,
        )
    except WorkbookIdentityError:
        msg = "Could not verify workbook identity — please reload."
        return _htmx_error(msg, ws) if is_htmx else _non_htmx_error(msg)
    if current_identity.composite_hash != content_hash:
        msg = (
            "Draft changed since page loaded — values refreshed. "
            "Please run again."
        )
        if not is_htmx:
            return _non_htmx_error(msg)
        # Return both the banner and refreshed run controls (with the current hash).
        stale_ctx: dict = {
            "ws_dirty": getattr(ws, "dirty", True),
            "has_runtime": bool(getattr(ws, "last_runtime_snapshot_id", None)),
            "field_error": msg,
            "flash_error": "",
            "project_code": project,
            "workbook_version": workbook_version,
            "content_hash": current_identity.composite_hash,
        }
        stale_banner_html = _templates.get_template(
            "partials/_v2_status_banner.html"
        ).render(stale_ctx)
        stale_banner_oob = (
            '<div id="v2-status-banner" hx-swap-oob="true">' + stale_banner_html + "</div>"
        )
        stale_controls_html = _templates.get_template(
            "partials/_v2_run_controls.html"
        ).render(stale_ctx)
        stale_controls_oob = (
            '<div id="v2-run-controls" hx-swap-oob="true">' + stale_controls_html + "</div>"
        )
        return HTMLResponse(content=stale_banner_oob + "\n" + stale_controls_oob)

    # ── Step 5b: protected reference guard ─────────────────────────────────── #
    # Protected reference models are immutable.  Run is a persistence operation
    # (v2_atomic_run_commit), so it must be blocked here — before engine execution
    # and before any persistence — consistent with the edit guard on /workbook/update.
    if is_protected_reference(project_record):
        msg = (
            "This is a protected reference model and cannot be run. "
            "Create a working copy to run the model."
        )
        return _htmx_error(msg, ws) if is_htmx else _non_htmx_error(msg)

    # ── Step 6: project type validation ───────────────────────────────────── #
    project_type_raw = (project_record.project_type or "").strip().lower()
    if project_type_raw == "solar":
        runtime_project_key = "Solar"
    elif project_type_raw == "wind":
        runtime_project_key = "Wind"
    else:
        # Unsupported runtime — Storage and any future unimplemented types.
        # HTMX: 200 + banner fragment (HTMX pattern); non-HTMX: 409 Conflict so
        # callers and tests receive a distinct 4xx rather than a redirect.
        _raw_type = project_record.project_type or "Unknown"
        msg = (
            f"{_raw_type} working-copy runtime is not yet supported. "
            "This project has not been modified. Return to the Model Workspace."
        )
        if is_htmx:
            return _htmx_error(msg, ws)
        return JSONResponse({"error": msg}, status_code=409)

    # ── Step 7: materialise from draft snapshot ────────────────────────────── #
    # draft_snapshot is the V2 canonical run boundary: it contains the exact
    # scalar values the user saw and approved when they clicked Run.
    try:
        override = WorkbookService.to_projectinputs(pis_draft)
    except Exception as _build_exc:
        import logging
        from app.revenue_input_validation import RevenueInputError
        if isinstance(_build_exc, RevenueInputError):
            # Cross-field contract violation — surface to user, do not log as error.
            _rev_err_msg = str(_build_exc)
            return _htmx_error(_rev_err_msg, ws) if is_htmx else _non_htmx_error(_rev_err_msg)
        logging.getLogger(__name__).exception(
            "v2_workbook_run: build_project_inputs failed project=%s user=%s",
            project, user.user_id,
        )
        msg = "Could not build project inputs — please reload and try again."
        return _htmx_error(msg, ws) if is_htmx else _non_htmx_error(msg)

    # ── Step 8: scenario resolution ────────────────────────────────────────── #
    active_scenario_id = ws.active_scenario_id
    active_scenario_name = ws.active_scenario_name
    scenario_name = active_scenario_name or "Base"
    _scenario_overrides_for_fold = None

    if active_scenario_id:
        import logging as _log
        from app.persistence.scenarios_repository import get_scenario
        sc_rec = get_scenario(scenario_id=active_scenario_id, user_id=workspace_owner)
        if sc_rec is None:
            msg = "Active scenario could not be found. Please re-select a scenario and try again."
            return _htmx_error(msg, ws) if is_htmx else _non_htmx_error(msg)
        if sc_rec.archived:
            msg = "Active scenario has been archived. Please re-select a scenario and try again."
            return _htmx_error(msg, ws) if is_htmx else _non_htmx_error(msg)
        if sc_rec.project_id != project_record.project_id:
            _log.getLogger(__name__).warning(
                "v2_workbook_run: scenario project_id mismatch "
                "scenario=%s scenario.project_id=%s expected=%s user=%s",
                active_scenario_id, sc_rec.project_id, project_record.project_id, user.user_id,
            )
            msg = "Active scenario does not belong to this project. Please re-select and try again."
            return _htmx_error(msg, ws) if is_htmx else _non_htmx_error(msg)
        _scenario_overrides_for_fold = sc_rec.overrides
        # Keep display name for provenance only; engine always receives "Base"
        # so the legacy ScenarioManager is never activated by a user-created name.
        scenario_name = sc_rec.scenario_name or scenario_name  # provenance / metadata only

    # ── Steps 9–10: CAPEX and OPEX fold ───────────────────────────────────── #
    from dataclasses import replace as _dc_replace
    folded_capex = apply_user_sub_lines_replacing_base(
        override.capex,
        project_id=project_record.project_id,
        scenario_overrides=_scenario_overrides_for_fold,
    )
    if folded_capex is not override.capex:
        override = _dc_replace(override, capex=folded_capex)

    folded_opex = apply_user_sub_lines_to_opex(
        override.opex,
        project_id=project_record.project_id,
        scenario_overrides=_scenario_overrides_for_fold,
    )
    if folded_opex is not override.opex:
        override = _dc_replace(override, opex=folded_opex)

    # ── Step 11: run the engine ────────────────────────────────────────────── #
    try:
        result = run_project(
            runtime_project_key,
            "Base",  # Contract A: always "Base"; display name must not activate legacy ScenarioManager
            project_inputs_override=override,
        )
    except Exception as exc:
        import logging
        logging.getLogger(__name__).exception("v2_workbook_run: engine failure")
        msg = "Engine run failed — please try again or contact support."
        return _htmx_error(msg, ws) if is_htmx else _non_htmx_error(msg)

    # ── Step 11b: enrich runtime_summary with derivation evidence ────────────── #
    # result["kpis"] is the raw engine KPI dict.  Derivation evidence is a
    # separate top-level key produced by _build_runtime_derivation_evidence.
    # We format and embed revenue_derivation here so it is persisted with the
    # runtime_summary and can be read back by _build_revenue_ctx without a
    # second engine call or an additional DB query.
    from app.ui.runtime_summary import _format_revenue_derivation as _fmt_rev_deriv
    _derivation_evidence = result.get("derivation_evidence", {})
    _revenue_derivation_raw = _derivation_evidence.get("revenue", {})
    _kpis_enriched = dict(result["kpis"])
    _kpis_enriched["revenue_derivation"] = _fmt_rev_deriv(_revenue_derivation_raw)

    # ── Step 12: atomic commit (final CAS + promote + dirty=False) ────────── #
    runtime_snapshot_id = _utc_compact()
    ran_at = datetime.now(timezone.utc)
    try:
        ws_committed = v2_atomic_run_commit(
            user_id=workspace_owner,
            project_id=project_record.project_id,
            project_code=project_record.project_code,
            expected_composite_hash=content_hash,
            runtime_snapshot_id=runtime_snapshot_id,
            runtime_origin=runtime_origin or "v2_run",
            runtime_summary=_kpis_enriched,
            financial_statements=result.get("financial_statements"),
            debt_schedule=result.get("debt_schedule"),
            tax_schedule=result.get("tax_schedule"),
            distribution_schedule=result.get("distribution_schedule"),
            sponsor_schedule=result.get("sponsor_schedule"),
            active_scenario_id=active_scenario_id,
            active_scenario_name=active_scenario_name,
            last_runtime_scenario_id=active_scenario_id,
            ran_at=ran_at,
        )
    except V2RunCommitConflictError:
        msg = (
            "Workbook changed while the engine was running — values refreshed. "
            "Please run again."
        )
        if not is_htmx:
            return _non_htmx_error(msg)
        # Re-fetch workspace to get the current hash for the run controls.
        ws_conflict = get_workspace_state(
            user_id=workspace_owner, project_id=project_record.project_id
        ) or ws
        pis_conflict = WorkbookService.build_draft_input_set_from_workspace(ws_conflict)
        try:
            conflict_identity = assemble_consistent_for_get(
                user_id=workspace_owner,
                project_id=project_record.project_id,
                workbook_version=pis_conflict.workbook_version,
            )
            conflict_hash = conflict_identity.composite_hash
        except WorkbookIdentityError:
            conflict_hash = ""
        conflict_ctx: dict = {
            "ws_dirty": getattr(ws_conflict, "dirty", True),
            "has_runtime": bool(getattr(ws_conflict, "last_runtime_snapshot_id", None)),
            "field_error": msg,
            "flash_error": "",
            "project_code": project,
            "workbook_version": workbook_version,
            "content_hash": conflict_hash,
        }
        conflict_banner_html = _templates.get_template(
            "partials/_v2_status_banner.html"
        ).render(conflict_ctx)
        conflict_banner_oob = (
            '<div id="v2-status-banner" hx-swap-oob="true">' + conflict_banner_html + "</div>"
        )
        conflict_controls_html = _templates.get_template(
            "partials/_v2_run_controls.html"
        ).render(conflict_ctx)
        conflict_controls_oob = (
            '<div id="v2-run-controls" hx-swap-oob="true">' + conflict_controls_html + "</div>"
        )
        return HTMLResponse(content=conflict_banner_oob + "\n" + conflict_controls_oob)
    except Exception as exc:
        import logging
        logging.getLogger(__name__).exception("v2_workbook_run: persistence failure")
        msg = "Run completed but could not be saved — please try again."
        return _htmx_error(msg, ws) if is_htmx else _non_htmx_error(msg)

    # ── Step 12b: persist KPIs to ScenarioRecord.last_run_summary ────────── #
    # This is the UI-3B per-scenario runtime isolation contract.
    # The workspace-level runtime evidence (last_runtime_summary_json) is
    # cleared on scenario switch, so Compare reads from each ScenarioRecord's
    # own last_run_summary_json instead.  We persist the run KPIs + provenance
    # here so that switching scenarios never corrupts another scenario's evidence.
    if active_scenario_id:
        try:
            from app.persistence.repository import update_scenario_last_run_summary
            from app.v2.scenario_presentation import _scenario_snapshot_hash
            from app.persistence.scenarios_repository import get_scenario as _get_sc
            _active_sc_rec = _get_sc(active_scenario_id, workspace_owner)
            _sc_snap_hash = _scenario_snapshot_hash(_active_sc_rec) if _active_sc_rec else None
            _sc_overrides_at_run = dict(getattr(_active_sc_rec, "overrides", None) or {})
            _sc_run_summary = {
                "kpis": dict(result["kpis"]),
                "snapshot_id": runtime_snapshot_id,
                "ran_at": ran_at.isoformat(),
                "scenario_id": active_scenario_id,
                "scenario_name": active_scenario_name or "",
                "scenario_snapshot_hash": _sc_snap_hash,
                "scenario_overrides_at_run": _sc_overrides_at_run,
            }
            update_scenario_last_run_summary(
                user_id=workspace_owner,
                scenario_id=active_scenario_id,
                last_run_summary=_sc_run_summary,
                replay_metadata={"v2_run": True, "project": project},
            )
        except Exception:
            import logging as _log
            _log.getLogger(__name__).exception(
                "v2_workbook_run: could not persist scenario last_run_summary "
                "scenario=%s project=%s", active_scenario_id, project
            )
            # Non-fatal: workspace run committed; Compare will show NOT_RUN until
            # user re-runs this scenario.
    else:
        # No explicit scenario selected — save to base case so Compare can show
        # this run's results when compared against an explicit scenario run.
        try:
            from app.persistence.repository import update_scenario_last_run_summary
            from app.persistence.scenarios_repository import get_base_case_scenario as _get_base
            _base_sc = _get_base(user_id=workspace_owner, project_id=project_record.project_id)
            if _base_sc:
                _base_run_summary = {
                    "kpis": dict(result["kpis"]),
                    "snapshot_id": runtime_snapshot_id,
                    "ran_at": ran_at.isoformat(),
                    "scenario_id": _base_sc.scenario_id,
                    "scenario_name": _base_sc.scenario_name or "Base Case",
                    "scenario_snapshot_hash": None,
                    "scenario_overrides_at_run": {},
                }
                update_scenario_last_run_summary(
                    user_id=workspace_owner,
                    scenario_id=_base_sc.scenario_id,
                    last_run_summary=_base_run_summary,
                    replay_metadata={"v2_run": True, "project": project},
                )
        except Exception:
            import logging as _log
            _log.getLogger(__name__).exception(
                "v2_workbook_run: could not persist base case last_run_summary "
                "project=%s", project
            )

    # ── Step 13–14: project from the persisted RuntimeResult ──────────────── #
    ws_fresh = ws_committed or get_workspace_state(
        user_id=workspace_owner, project_id=project_record.project_id
    )
    if ws_fresh is None:
        msg = "Run committed but workspace could not be reloaded."
        return _htmx_error(msg) if is_htmx else _non_htmx_error(msg)
    rr = WorkbookService.get_runtime_result(ws_fresh)
    if rr is None:
        msg = "Run committed but the persisted RuntimeResult could not be reconstructed."
        return _htmx_error(msg) if is_htmx else _non_htmx_error(msg)

    # ── Step 15: HTMX response ────────────────────────────────────────────── #
    if not is_htmx:
        return RedirectResponse(
            url=f"/v2/workbook?project={project}",
            status_code=303,
        )

    # R6/F07: ONE post-run UI projection authority — every runtime-dependent
    # visible surface is rendered from this single ws_fresh read and one
    # RuntimeProjectionBundle (run controls, status banner, toolbar,
    # Overview KPIs, debt, tax, FS, scenario last-run statuses).  The
    # previous hand-rolled assembly here omitted the Overview sheet, which
    # left stale pre-Run KPIs presented as current after a new Run.
    from app.v2.post_run_ui import build_post_run_ui_state

    combined = build_post_run_ui_state(
        request=request,
        ws_fresh=ws_fresh,
        project_record=project_record,
        project=project,
        workspace_owner=workspace_owner,
        rr=rr,
    )
    return HTMLResponse(content=combined)


# ═══════════════════════════════════════════════════════════════════════════════
# U2.1: Institutional workbook export route
# ═══════════════════════════════════════════════════════════════════════════════


@router.post("/workbook/export")
async def v2_workbook_export(
    request: Request,
    project: str = Form(...),
    _: None = Depends(require_v2_active),
):
    """Institutional workbook export — canonical last-run authority.

    Uses CANONICAL_LAST_RUN authority exclusively: the export reflects the
    inputs that produced the last committed engine run, NOT the current
    working-copy edits.  Zero engine execution; no financial computation.

    Fail-closed: returns 400 HTML error when no run has been committed.

    Not an HTMX endpoint: returns a binary file download via StreamingResponse
    (or HTMLResponse on error).  Standard form POST only.

    Access isolation: resolve_accessible_project() scopes the workspace to the
    authenticated user; unauthenticated requests redirect to /login.
    """
    from app.persistence.projects_repository import resolve_accessible_project
    from app.services.export_service import _make_streaming_response
    from app.services.v2_export_service import (
        build_canonical_last_run_institutional_workbook_export,
    )

    user = _get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    project_record, workspace_owner = resolve_accessible_project(user.user_id, project)
    if project_record is None:
        return HTMLResponse(
            content=(
                "<html><body><h2>Export failed</h2>"
                "<p>Project not found or not accessible.</p>"
                "<a href='/library'>Back to Library</a></body></html>"
            ),
            status_code=404,
        )

    safe_project = project_record.project_code or project
    # Derive runtime_project_code from template_source, mirroring main_web._normalize_template_source.
    _ts = (project_record.template_source or "").strip().lower()
    _known = {
        "generic_wind_reference", "generic_solar_reference", "generic_storage_reference",
        "generic_wind", "generic_solar", "generic_storage",
    }
    if _ts in _known:
        runtime_project_code = _ts
    else:
        _pt = (project_record.project_type or "").strip().lower()
        if _pt == "solar":
            runtime_project_code = "generic_solar"
        elif _pt in ("storage", "bess"):
            runtime_project_code = "generic_storage"
        else:
            runtime_project_code = "generic_wind"

    export = build_canonical_last_run_institutional_workbook_export(
        runtime_project_code,
        safe_project=safe_project,
        project_record=project_record,
        user_id=workspace_owner,
    )

    if export.status_code == 200:
        from app.persistence.repository import record_export
        _governance_state = {"g20_status": "BLOCKED", "r99_r102_status": "NOT APPROVED"}
        _meta = export.metadata or {}
        _replay_meta = {
            "export_type": "institutional_workbook",
            "workbook_type": "institutional_workbook",
            "export_timestamp": _meta.get("export_generated_at", ""),
            "export_generated_at": _meta.get("export_generated_at", ""),
            "runtime_timestamp": _meta.get("runtime_generated_at", ""),
            "runtime_origin": _meta.get("runtime_origin", "canonical_last_run"),
            "artifact_name": export.filename,
            "export_authority": _meta.get("export_authority", "CANONICAL_LAST_RUN"),
            "run_id": _meta.get("export_run_id", ""),
            "run_at": _meta.get("export_run_at", ""),
        }
        record_export(
            user_id=workspace_owner,
            # F05: use actual user project code, not template code.
            project_code=getattr(project_record, "project_code", None) or runtime_project_code,
            export_type="institutional_workbook",
            artifact_name=export.filename,
            artifact_path="/v2/workbook/export",
            project_id=getattr(project_record, "project_id", None),
            scenario_id=_meta.get("export_active_scenario_id") or None,
            runtime_snapshot_id=_meta.get("export_snapshot_id") or None,
            governance_state=_governance_state,
            replay_metadata={
                **_replay_meta,
                "runtime_project_code": runtime_project_code,
            },
        )

    return _make_streaming_response(export)


# ═══════════════════════════════════════════════════════════════════════════════
# UI-3B: Scenario management routes
# ═══════════════════════════════════════════════════════════════════════════════


def _scenario_list_html(user_id: str, project_id: str, project_code: str, ws) -> str:
    """Render the scenario list partial HTML (used by multiple endpoints)."""
    from app.persistence.scenarios_repository import list_scenarios
    from app.v2.scenario_presentation import build_scenario_presentations
    from app.workbook.runtime_authority import resolve_runtime_freshness
    from app.workbook.workbook_identity import assemble_consistent_for_get
    scenarios = list_scenarios(user_id=user_id, project_id=project_id, include_archived=False)
    active_id = ws.active_scenario_id if ws else None
    # GF-F04/F05: resolve canonical freshness with the REAL composite hash so
    # that a post-Run CURRENT workspace is not incorrectly forced to STALE.
    # Fail closed (STALE) only when identity assembly genuinely fails.
    try:
        identity = assemble_consistent_for_get(
            user_id=user_id,
            project_id=project_id,
            workbook_version=WORKBOOK.version,
        )
        current_hash = identity.composite_hash
    except Exception:
        current_hash = None  # fail closed per runtime-authority semantics
    freshness = resolve_runtime_freshness(ws, current_composite_hash=current_hash)
    presentations = build_scenario_presentations(
        scenarios, active_id, global_is_stale=freshness.is_stale)
    ctx = {
        "scenarios": presentations,
        "active_scenario_id": active_id,
        "project_code": project_code,
        "ws": ws,
    }
    return _templates.get_template("partials/sheet_scenarios.html").render(ctx)


def _scenario_authority_oob(
    request, ws, project_record, project: str, workspace_owner: str
) -> str:
    """Refresh every runtime-backed surface after a scenario mutation."""
    from app.v2.post_run_ui import build_post_save_ui_state

    return build_post_save_ui_state(
        ws_fresh=ws,
        project_record=project_record,
        project=project,
        workspace_owner=workspace_owner,
        request=request,
        include_banner_and_controls=True,
        include_scenario_list=False,
    )


@router.post("/workbook/scenarios/create")
async def v2_scenario_create(
    request: Request,
    project: str = Form(...),
    scenario_name: str = Form(...),
    _: None = Depends(require_v2_active),
):
    """Create a new child scenario forked from the Base Case.

    The new scenario starts with empty overrides (same effective inputs as Base Case).
    After creation the new scenario becomes the active scenario.
    """
    user = _get_current_user(request)
    if not user:
        return JSONResponse({"error": "Unauthenticated"}, status_code=401)

    from app.persistence.projects_repository import resolve_accessible_project
    from app.persistence.workspace_repository import get_workspace_state
    from app.persistence.scenarios_repository import (
        get_or_create_base_case_scenario,
        add_scenario,
        select_scenario,
        list_scenarios,
    )
    from app.workbook.service import WorkbookService

    project_record, workspace_owner = resolve_accessible_project(user.user_id, project)
    if project_record is None:
        return JSONResponse({"error": f"Project {project!r} not found."}, status_code=404)
    if is_protected_reference(project_record):
        return JSONResponse({"error": "Protected reference — cannot create scenarios."}, status_code=409)

    ws = get_workspace_state(user_id=workspace_owner, project_id=project_record.project_id)
    if ws is None:
        return JSONResponse({"error": "Workspace not found."}, status_code=404)

    name = (scenario_name or "").strip()
    if not name:
        return JSONResponse({"error": "Scenario name cannot be empty."}, status_code=422)
    if len(name) > 80:
        return JSONResponse({"error": "Scenario name too long (max 80 characters)."}, status_code=422)

    pis = WorkbookService.build_draft_input_set_from_workspace(ws)
    base_input_set = dict(pis.values)

    base_case = get_or_create_base_case_scenario(
        user_id=workspace_owner,
        project_id=project_record.project_id,
        project_code=project,
        project_name=project_record.project_name or project,
        project_type=project_record.project_type or "",
        source_project_template=project_record.full_inputs.get("source_project_template", "") if project_record.full_inputs else "",
        base_input_set=base_input_set,
        governance_state={},
    )

    new_sc = add_scenario(
        user_id=workspace_owner,
        project_id=project_record.project_id,
        project_code=project,
        scenario_name=name,
        parent_scenario_id=base_case.scenario_id,
        base_input_set=base_input_set,
        overrides={},
    )
    if new_sc is None:
        return JSONResponse({"error": "Failed to create scenario."}, status_code=500)

    select_scenario(user_id=workspace_owner, project_id=project_record.project_id, scenario_id=new_sc.scenario_id)
    ws = get_workspace_state(user_id=workspace_owner, project_id=project_record.project_id) or ws

    is_htmx = request.headers.get("HX-Request") == "true"
    if is_htmx:
        html = _scenario_list_html(workspace_owner, project_record.project_id, project, ws)
        return HTMLResponse(content=html + "\n" + _scenario_authority_oob(
            request, ws, project_record, project, workspace_owner))
    return RedirectResponse(url=f"/v2/workbook?project={project}", status_code=303)


@router.post("/workbook/scenarios/select")
async def v2_scenario_select(
    request: Request,
    project: str = Form(...),
    scenario_id: str = Form(...),
    _: None = Depends(require_v2_active),
):
    """Set the active scenario.  Clears stale runtime evidence for this project."""
    user = _get_current_user(request)
    if not user:
        return JSONResponse({"error": "Unauthenticated"}, status_code=401)

    from app.persistence.projects_repository import resolve_accessible_project
    from app.persistence.workspace_repository import get_workspace_state
    from app.persistence.scenarios_repository import select_scenario, get_scenario

    project_record, workspace_owner = resolve_accessible_project(user.user_id, project)
    if project_record is None:
        return JSONResponse({"error": "Project not found."}, status_code=404)

    sc = get_scenario(scenario_id=scenario_id, user_id=workspace_owner)
    if sc is None or sc.project_id != project_record.project_id or sc.archived:
        return JSONResponse({"error": "Scenario not found or archived."}, status_code=404)

    select_scenario(user_id=workspace_owner, project_id=project_record.project_id, scenario_id=scenario_id)
    ws = get_workspace_state(user_id=workspace_owner, project_id=project_record.project_id)

    is_htmx = request.headers.get("HX-Request") == "true"
    if is_htmx:
        html = _scenario_list_html(workspace_owner, project_record.project_id, project, ws)
        return HTMLResponse(content=html + "\n" + _scenario_authority_oob(
            request, ws, project_record, project, workspace_owner))
    return RedirectResponse(url=f"/v2/workbook?project={project}", status_code=303)


@router.post("/workbook/scenarios/rename")
async def v2_scenario_rename(
    request: Request,
    project: str = Form(...),
    scenario_id: str = Form(...),
    new_name: str = Form(...),
    _: None = Depends(require_v2_active),
):
    """Rename a scenario.  Base Case cannot be renamed."""
    user = _get_current_user(request)
    if not user:
        return JSONResponse({"error": "Unauthenticated"}, status_code=401)

    from app.persistence.projects_repository import resolve_accessible_project
    from app.persistence.workspace_repository import get_workspace_state
    from app.persistence.scenarios_repository import rename_scenario, get_scenario

    project_record, workspace_owner = resolve_accessible_project(user.user_id, project)
    if project_record is None:
        return JSONResponse({"error": "Project not found."}, status_code=404)

    sc = get_scenario(scenario_id=scenario_id, user_id=workspace_owner)
    if sc is None or sc.project_id != project_record.project_id:
        return JSONResponse({"error": "Scenario not found."}, status_code=404)
    if sc.is_base_case:
        return JSONResponse({"error": "Base Case cannot be renamed."}, status_code=409)

    name = (new_name or "").strip()
    if not name or len(name) > 80:
        return JSONResponse({"error": "Invalid scenario name."}, status_code=422)

    rename_scenario(user_id=workspace_owner, scenario_id=scenario_id, new_name=name)
    ws = get_workspace_state(user_id=workspace_owner, project_id=project_record.project_id)

    is_htmx = request.headers.get("HX-Request") == "true"
    if is_htmx:
        html = _scenario_list_html(workspace_owner, project_record.project_id, project, ws)
        return HTMLResponse(content=html)
    return RedirectResponse(url=f"/v2/workbook?project={project}", status_code=303)


@router.post("/workbook/scenarios/archive")
async def v2_scenario_archive(
    request: Request,
    project: str = Form(...),
    scenario_id: str = Form(...),
    _: None = Depends(require_v2_active),
):
    """Archive a scenario.  Base Case cannot be archived."""
    user = _get_current_user(request)
    if not user:
        return JSONResponse({"error": "Unauthenticated"}, status_code=401)

    from app.persistence.projects_repository import resolve_accessible_project
    from app.persistence.workspace_repository import get_workspace_state
    from app.persistence.scenarios_repository import archive_scenario, get_scenario, select_scenario, get_base_case_scenario

    project_record, workspace_owner = resolve_accessible_project(user.user_id, project)
    if project_record is None:
        return JSONResponse({"error": "Project not found."}, status_code=404)

    sc = get_scenario(scenario_id=scenario_id, user_id=workspace_owner)
    if sc is None or sc.project_id != project_record.project_id:
        return JSONResponse({"error": "Scenario not found."}, status_code=404)
    if sc.is_base_case:
        return JSONResponse({"error": "Base Case cannot be archived."}, status_code=409)

    ws = get_workspace_state(user_id=workspace_owner, project_id=project_record.project_id)
    archived_active = bool(ws and ws.active_scenario_id == scenario_id)
    archive_scenario(user_id=workspace_owner, scenario_id=scenario_id)

    # If the archived scenario was active, switch to Base Case
    if ws and ws.active_scenario_id == scenario_id:
        base = get_base_case_scenario(user_id=workspace_owner, project_id=project_record.project_id)
        if base:
            select_scenario(user_id=workspace_owner, project_id=project_record.project_id, scenario_id=base.scenario_id)
        ws = get_workspace_state(user_id=workspace_owner, project_id=project_record.project_id)

    is_htmx = request.headers.get("HX-Request") == "true"
    if is_htmx:
        html = _scenario_list_html(workspace_owner, project_record.project_id, project, ws)
        if archived_active:
            html += "\n" + _scenario_authority_oob(
                request, ws, project_record, project, workspace_owner)
        return HTMLResponse(content=html)
    return RedirectResponse(url=f"/v2/workbook?project={project}", status_code=303)


@router.post("/workbook/scenarios/update-overrides")
async def v2_scenario_update_overrides(
    request: Request,
    _: None = Depends(require_v2_active),
):
    """Patch financial overrides for a non-base-case scenario.

    Accepts multipart/form-data with fields: ``project``, ``scenario_id``,
    plus any combination of SCENARIO_INPUT_FIELDS (e.g. tariff_eur_mwh,
    gearing_pct).  Non-numeric submissions for numeric fields are silently
    skipped.  Unknown field names are silently dropped by the persistence
    layer (Phase 20B invariant).

    Base Case scenarios cannot be edited via this endpoint (409).
    Returns the re-rendered scenario list partial (HTMX OOB).
    """
    user = _get_current_user(request)
    if not user:
        return JSONResponse({"error": "Unauthenticated"}, status_code=401)

    try:
        form = await request.form()
    except Exception:
        return JSONResponse({"error": "Invalid form-data body."}, status_code=400)

    project = (form.get("project") or "").strip()
    scenario_id = (form.get("scenario_id") or "").strip()
    if not project or not scenario_id:
        return JSONResponse({"error": "project and scenario_id are required."}, status_code=422)

    # Parse submitted override fields; skip routing/meta fields.
    _SKIP_KEYS = frozenset({"project", "scenario_id", "csrf_token", "csrf"})
    overrides: dict = {}
    items = form.multi_items() if hasattr(form, "multi_items") else form.items()
    for key, val in items:
        if key in _SKIP_KEYS or not key or not val:
            continue
        try:
            overrides[key] = float(val)
        except (ValueError, TypeError):
            pass  # silently skip non-numeric; persistence layer drops unknown keys

    from app.persistence.projects_repository import resolve_accessible_project
    from app.persistence.workspace_repository import get_workspace_state
    from app.persistence.scenarios_repository import (
        get_scenario,
        update_scenario_overrides,
    )

    project_record, workspace_owner = resolve_accessible_project(user.user_id, project)
    if project_record is None:
        return JSONResponse({"error": "Project not found."}, status_code=404)
    if is_protected_reference(project_record):
        return JSONResponse({"error": "Protected reference — cannot edit overrides."}, status_code=409)

    sc = get_scenario(scenario_id=scenario_id, user_id=workspace_owner)
    if sc is None or sc.project_id != project_record.project_id:
        return JSONResponse({"error": "Scenario not found."}, status_code=404)
    if sc.is_base_case:
        return JSONResponse(
            {"error": "Base Case overrides cannot be edited via this endpoint. Use the Inputs tab."},
            status_code=409,
        )

    updated = update_scenario_overrides(workspace_owner, scenario_id, overrides)
    if updated is None:
        return JSONResponse({"error": "Failed to update overrides."}, status_code=500)

    ws = get_workspace_state(user_id=workspace_owner, project_id=project_record.project_id)
    is_htmx = request.headers.get("HX-Request") == "true"
    if is_htmx:
        html = _scenario_list_html(workspace_owner, project_record.project_id, project, ws)
        return HTMLResponse(content=html + "\n" + _scenario_authority_oob(
            request, ws, project_record, project, workspace_owner))
    return RedirectResponse(url=f"/v2/workbook?project={project}", status_code=303)


@router.post("/workbook/scenarios/remove-override")
async def v2_scenario_remove_override(
    request: Request,
    _: None = Depends(require_v2_active),
):
    """Remove a specific field override from a scenario, restoring Base Case inheritance.

    Semantics: removes the named key(s) from overrides_json so the scenario
    inherits the Base Case value for that field on the next run.

    Invariant (override-reset): key absent ≠ key present with 0.0.
    A genuine persisted 0.0 is untouched; only explicitly named keys are removed.

    Accepts form data: ``project``, ``scenario_id``, ``field`` (repeatable —
    submit multiple ``field`` values to remove several overrides at once).
    Base Case scenarios → 409.  Protected references → 409.
    """
    user = _get_current_user(request)
    if not user:
        return JSONResponse({"error": "Unauthenticated"}, status_code=401)

    try:
        form = await request.form()
    except Exception:
        return JSONResponse({"error": "Invalid form-data body."}, status_code=400)

    project = (form.get("project") or "").strip()
    scenario_id = (form.get("scenario_id") or "").strip()
    if not project or not scenario_id:
        return JSONResponse({"error": "project and scenario_id are required."}, status_code=422)

    # Collect one or more field keys to remove.
    fields_to_remove: list[str] = []
    items = form.multi_items() if hasattr(form, "multi_items") else form.items()
    for key, val in items:
        if key == "field" and val:
            fields_to_remove.append(val.strip())
    if not fields_to_remove:
        return JSONResponse({"error": "At least one 'field' parameter is required."}, status_code=422)

    invalid_fields = sorted({
        field for field in fields_to_remove
        if field not in _REMOVABLE_OVERRIDE_FIELDS
    })
    if invalid_fields:
        return JSONResponse(
            {
                "error": "One or more override fields are not removable.",
                "invalid_fields": invalid_fields,
            },
            status_code=422,
        )

    from app.persistence.projects_repository import resolve_accessible_project
    from app.persistence.workspace_repository import get_workspace_state
    from app.persistence.scenarios_repository import (
        get_scenario,
        remove_scenario_overrides,
    )

    project_record, workspace_owner = resolve_accessible_project(user.user_id, project)
    if project_record is None:
        return JSONResponse({"error": "Project not found."}, status_code=404)
    if is_protected_reference(project_record):
        return JSONResponse({"error": "Protected reference — cannot edit overrides."}, status_code=409)

    sc = get_scenario(scenario_id=scenario_id, user_id=workspace_owner)
    if sc is None or sc.project_id != project_record.project_id:
        return JSONResponse({"error": "Scenario not found."}, status_code=404)
    if sc.is_base_case:
        return JSONResponse(
            {"error": "Base Case overrides cannot be removed via this endpoint."},
            status_code=409,
        )

    updated = remove_scenario_overrides(workspace_owner, scenario_id, fields_to_remove)
    if updated is None:
        return JSONResponse({"error": "Failed to remove override."}, status_code=500)

    ws = get_workspace_state(user_id=workspace_owner, project_id=project_record.project_id)
    is_htmx = request.headers.get("HX-Request") == "true"
    if is_htmx:
        html = _scenario_list_html(workspace_owner, project_record.project_id, project, ws)
        return HTMLResponse(content=html + "\n" + _scenario_authority_oob(
            request, ws, project_record, project, workspace_owner))
    return RedirectResponse(url=f"/v2/workbook?project={project}", status_code=303)


@router.get("/workbook/scenarios/compare", response_class=HTMLResponse)
async def v2_scenario_compare(
    request: Request,
    project: Optional[str] = None,
    s1: Optional[str] = None,
    s2: Optional[str] = None,
    s3: Optional[str] = None,
):
    """Return compare table partial for up to 3 selected scenarios.

    Each scenario's runtime_summary is sourced from the persisted workspace
    runtime evidence (last_runtime_summary) for that scenario.  Only
    authoritative values from a completed engine run are shown.
    """
    user = _get_current_user(request)
    if not user:
        return HTMLResponse(content="<p>Unauthenticated.</p>", status_code=401)
    if not project:
        return HTMLResponse(content="<p>No project specified.</p>", status_code=400)

    from app.persistence.projects_repository import resolve_accessible_project
    from app.persistence.workspace_repository import get_workspace_state
    from app.persistence.scenarios_repository import get_scenario, list_scenarios, get_base_case_scenario
    from app.v2.scenario_kpi_projection import build_scenario_projection, build_compare_rows

    project_record, workspace_owner = resolve_accessible_project(user.user_id, project)
    if project_record is None:
        return HTMLResponse(content="<p>Project not found.</p>", status_code=404)

    ws = get_workspace_state(user_id=workspace_owner, project_id=project_record.project_id)
    all_scenarios = list_scenarios(user_id=workspace_owner, project_id=project_record.project_id, include_archived=False)

    selected_ids = [sid for sid in [s1, s2, s3] if sid]
    selected_scenarios = []
    for sid in selected_ids:
        sc = get_scenario(scenario_id=sid, user_id=workspace_owner)
        if sc and sc.project_id == project_record.project_id and not sc.archived:
            selected_scenarios.append(sc)

    projections = []
    for sc in selected_scenarios:
        rs = sc.last_run_summary or {}
        ran_at_str = (rs.get("ran_at") or "") if rs else ""
        has_result = bool(rs and rs.get("kpis"))
        if not has_result:
            is_stale = False  # will show as NOT_RUN
        else:
            from app.v2.scenario_presentation import _is_stale as _snap_is_stale
            is_stale = _snap_is_stale(sc)
        proj = build_scenario_projection(
            scenario_name=sc.scenario_name,
            runtime_summary=rs.get("kpis") if has_result else None,
            ran_at=ran_at_str,
            is_stale=is_stale,
        )
        # Patch in scenario_id
        from dataclasses import replace as _dcr
        proj = _dcr(proj, scenario_id=sc.scenario_id)
        projections.append(proj)

    rows = build_compare_rows(projections) if len(projections) >= 2 else []

    ctx = {
        "project_code": project,
        "project_name": project_record.project_name or project,
        "all_scenarios": all_scenarios,
        "selected_scenarios": selected_scenarios,
        "selected_ids": selected_ids,
        "projections": projections,
        "compare_rows": rows,
        "request": request,
    }
    return HTMLResponse(content=_templates.get_template("partials/sheet_compare.html").render(ctx))


@router.post("/workbook/scenarios/sensitivity/run", response_class=HTMLResponse)
async def v2_scenario_sensitivity_run(
    request: Request,
    project: str = Form(...),
    driver: str = Form(...),
    scenario_id: Optional[str] = Form(default=None),
    _: None = Depends(require_v2_active),
):
    """Run a bounded 5-point sensitivity on one driver.

    Causal chain:
      resolve_active_scenario_runtime_snapshot(scenario_id)
      → canonical resolved scenario snapshot (base + all field overrides)
      → ProjectInputSet
      → sensitivity driver with_value(field_id)
      → ProjectInputs
      → CAPEX/OPEX sub-line fold (for _capex_sub_line_overrides blobs)
      → run_project()
      → authoritative result

    No approximation. No interpolation. No client-side financial computation.
    Results are temporary — not written to scenario persistence.

    MVP supported drivers: tariff, generation, interest_rate, gearing
    (capex_total and opex_total removed — derived_display fields are not writable via with_value)
    """
    import logging as _logging

    user = _get_current_user(request)
    if not user:
        return HTMLResponse(content="<p>Unauthenticated.</p>", status_code=401)

    from app.persistence.projects_repository import resolve_accessible_project
    from app.persistence.workspace_repository import get_workspace_state
    from app.persistence.scenarios_repository import get_scenario, get_base_case_scenario
    from app.api.project_runner import run_project
    from app.workbook.service import WorkbookService
    from app.v2.scenario_kpi_projection import build_scenario_projection, KPI_CATALOG, _fmt
    from app.v2.output_metric_projection import build_output_metric_projection

    project_record, workspace_owner = resolve_accessible_project(user.user_id, project)
    if project_record is None:
        return HTMLResponse(content="<p>Project not found.</p>", status_code=404)
    if is_protected_reference(project_record):
        return HTMLResponse(content="<p>Protected reference — cannot run sensitivity.</p>", status_code=409)

    project_type_raw = (project_record.project_type or "").strip().lower()
    if project_type_raw not in ("solar", "wind"):
        return HTMLResponse(content=f"<p>Unsupported project type: {project_record.project_type!r}.</p>", status_code=409)
    runtime_key = project_type_raw.capitalize()

    ws = get_workspace_state(user_id=workspace_owner, project_id=project_record.project_id)
    if ws is None:
        return HTMLResponse(content="<p>Workspace not found.</p>", status_code=404)

    # Resolve active scenario overrides (or empty for Base Case)
    scenario_overrides: dict = {}
    scenario_display = "Base Case"
    if scenario_id:
        sc = get_scenario(scenario_id=scenario_id, user_id=workspace_owner)
        if sc and sc.project_id == project_record.project_id and not sc.archived:
            scenario_overrides = dict(sc.overrides or {})
            scenario_display = sc.scenario_name

    # Sensitivity driver definitions.
    # "field_id" is the canonical semantic field_id accepted by ProjectInputSet.with_value().
    # "snapshot_key" is retained as provenance metadata only — never passed to with_value().
    #
    # PCT fields (interest_rate_pct, gearing_pct) are stored as percentages (0-100 scale,
    # e.g. 4.5 = 4.5%, 70 = 70%).  Absolute steps are in percentage-point units.
    DRIVER_SPECS: dict[str, dict] = {
        "tariff": {
            "label": "Tariff / Energy Price",
            "field_id": "revenue.ppa.base_tariff",
            # Legacy projects populate revenue.ppa.tariff_legacy instead
            "field_id_fallback": "revenue.ppa.tariff_legacy",
            "snapshot_key": "rev_ppa_base_tariff",
            "steps": [-0.20, -0.10, 0.0, +0.10, +0.20],
            "step_labels": ["-20%", "-10%", "Base", "+10%", "+20%"],
            "mode": "pct_multiplier",
        },
        # capex_total (capex.summary.total) and opex_total (opex.summary.total_y1) are
        # derived_display / source_of_truth=derived_ui — not writable via with_value().
        # Removed from MVP sensitivity catalog per spec: "do not fake support".

        "generation": {
            "label": "P50 Operating Hours",
            "field_id": "project_setup.technical.p50_hours",
            "snapshot_key": "p50_hours",
            "steps": [-0.10, -0.05, 0.0, +0.05, +0.10],
            "step_labels": ["-10%", "-5%", "Base", "+5%", "+10%"],
            "mode": "pct_multiplier",
        },
        "interest_rate": {
            "label": "Senior Interest Rate",
            "field_id": "debt.senior.interest_rate_pct",
            "snapshot_key": "interest_rate_pct",
            # Stored as percentage (e.g. 4.5).  ±200 bps = ±2.0 percentage points.
            "steps": [-2.0, -1.0, 0.0, +1.0, +2.0],
            "step_labels": ["-200 bps", "-100 bps", "Base", "+100 bps", "+200 bps"],
            "mode": "absolute_add",
        },
        "gearing": {
            "label": "Gearing",
            "field_id": "debt.senior.gearing_pct",
            "snapshot_key": "gearing_pct",
            # Stored as percentage (e.g. 70).  ±10 pp = ±10.0 percentage points.
            "steps": [-10.0, -5.0, 0.0, +5.0, +10.0],
            "step_labels": ["-10 pp", "-5 pp", "Base", "+5 pp", "+10 pp"],
            "mode": "absolute_add",
        },
    }

    if driver not in DRIVER_SPECS:
        return HTMLResponse(content=f"<p>Unknown driver: {driver!r}.</p>", status_code=422)

    spec = DRIVER_SPECS[driver]
    field_id = spec["field_id"]
    field_id_fallback = spec.get("field_id_fallback")

    from app.services.capex_sub_lines_integration import apply_user_sub_lines_replacing_base as _apply_capex
    from app.services.opex_sub_lines_integration import apply_user_sub_lines_to_opex as _apply_opex
    from dataclasses import replace as _dc_replace
    from app.persistence.scenarios_repository import resolve_active_scenario_runtime_snapshot as _resolve_snap

    # Resolve selected scenario's canonical financial snapshot.
    # Uses resolve_active_scenario_runtime_snapshot so that scenario field overrides
    # (tariff, generation, interest_rate, gearing, etc.) are correctly merged into the
    # base case snapshot BEFORE any sensitivity driver override is applied.
    _scenario_rec = None
    _scenario_overrides_for_fold = None
    if scenario_id:
        _scenario_rec, _resolved_snap, _warn = _resolve_snap(
            workspace_owner, project_record.project_id, scenario_id
        )
        if _scenario_rec is None:
            return HTMLResponse(
                content="<p>Scenario not found, archived, or inaccessible.</p>",
                status_code=404,
            )
        # Double-check identity (resolve_active_scenario_runtime_snapshot already validates these)
        if _scenario_rec.project_id != project_record.project_id or _scenario_rec.archived:
            return HTMLResponse(
                content="<p>Scenario does not belong to this project or is archived.</p>",
                status_code=403,
            )
        if _resolved_snap is None:
            return HTMLResponse(
                content="<p>Could not resolve scenario inputs. Please re-run the scenario and retry.</p>",
                status_code=409,
            )
        scenario_display = _scenario_rec.scenario_name
        _scenario_overrides_for_fold = _scenario_rec.overrides
        # Build PIS from the fully resolved scenario snapshot (includes all field overrides)
        pis_base = WorkbookService.build_input_set(_resolved_snap)
    else:
        # Base Case: use workspace draft (canonical current inputs)
        pis_base = WorkbookService.build_draft_input_set_from_workspace(ws)

    # Snapshot of pis_base values before any sensitivity run (for non-destructive check)
    _pis_base_values_snapshot = dict(pis_base.values)

    # Resolve base value from the canonical field_id in pis_base.values.
    # For tariff, fall back to the legacy field_id if the canonical one is absent.
    base_val = pis_base.values.get(field_id)
    if base_val is None and field_id_fallback:
        base_val = pis_base.values.get(field_id_fallback)
        if base_val is not None:
            field_id = field_id_fallback  # use whichever field_id is populated

    results: list[dict] = []
    for step, step_label in zip(spec["steps"], spec["step_labels"]):
        # Each iteration works from a fresh pis_base — never accumulates, never mutates.
        try:
            if spec["mode"] == "pct_multiplier":
                if base_val is not None:
                    try:
                        new_val: object = float(base_val) * (1.0 + step)
                    except (TypeError, ValueError):
                        results.append({"label": step_label, "status": "FAILED",
                                        "error": f"Cannot apply multiplier to {field_id!r}", "kpis": {}})
                        continue
                else:
                    if step == 0.0:
                        new_val = None  # Base step: run scenario overrides only, no driver override
                    else:
                        results.append({"label": step_label, "status": "FAILED",
                                        "error": f"Base value for {field_id!r} not in workspace inputs", "kpis": {}})
                        continue
            else:  # absolute_add
                if base_val is not None:
                    try:
                        new_val = float(base_val) + step
                    except (TypeError, ValueError):
                        results.append({"label": step_label, "status": "FAILED",
                                        "error": f"Cannot apply offset to {field_id!r}", "kpis": {}})
                        continue
                else:
                    if step == 0.0:
                        new_val = None
                    else:
                        results.append({"label": step_label, "status": "FAILED",
                                        "error": f"Base value for {field_id!r} not in workspace inputs", "kpis": {}})
                        continue

            # Apply driver override to fresh PIS.  Fail-closed: if with_value() raises,
            # this point FAILS — we never silently run unchanged base inputs.
            pis_sens = pis_base
            if new_val is not None:
                pis_sens = pis_sens.with_value(field_id, str(new_val))  # raises on bad field_id

            # Causal chain: base PIS → driver override → ProjectInputs → CAPEX/OPEX scenario fold → engine
            pi_override = WorkbookService.to_projectinputs(pis_sens)
            folded_capex = _apply_capex(
                pi_override.capex,
                project_id=project_record.project_id,
                scenario_overrides=_scenario_overrides_for_fold,
            )
            if folded_capex is not pi_override.capex:
                pi_override = _dc_replace(pi_override, capex=folded_capex)
            folded_opex = _apply_opex(
                pi_override.opex,
                project_id=project_record.project_id,
                scenario_overrides=_scenario_overrides_for_fold,
            )
            if folded_opex is not pi_override.opex:
                pi_override = _dc_replace(pi_override, opex=folded_opex)

            eng_result = run_project(
                runtime_key,
                "Base",
                project_inputs_override=pi_override,
            )
            kpis_raw = eng_result.get("kpis", {})
            # Build canonical OutputMetricProjection for each KPI.
            step_metrics = {}
            for _key, _label, _unit, _fmt_code, _src in KPI_CATALOG:
                step_metrics[_key] = build_output_metric_projection(
                    _key, kpis_raw.get(_key), freshness="current"
                )
            # Compatibility: derived formatted/raw dicts from metrics.
            formatted_kpis = {k: m.display_value for k, m in step_metrics.items()}
            results.append({
                "label": step_label,
                "status": "OK",
                "metrics": step_metrics,
                "kpis": formatted_kpis,
                "kpis_raw": {k: m.raw_value for k, m in step_metrics.items()},
            })

        except Exception as exc:
            _logging.getLogger(__name__).exception(
                "sensitivity_run: driver=%s step=%s project=%s", driver, step, project
            )
            results.append({"label": step_label, "status": "FAILED", "error": str(exc)[:120], "kpis": {}})

    # Non-destructive proof: pis_base.values must be unchanged by sensitivity execution.
    # If sensitivity accidentally mutated shared state, this will catch it at runtime.
    _pis_after_values = dict(pis_base.values)
    if _pis_after_values != _pis_base_values_snapshot:
        _logging.getLogger(__name__).error(
            "sensitivity_run: NON-DESTRUCTIVE VIOLATION — pis_base mutated during sensitivity "
            "driver=%s project=%s", driver, project
        )

    # Build kpi_catalog as list of dicts for the template
    kpi_catalog_dicts = [
        {"key": k, "label": lbl, "unit": unit, "fmt": fmt_code, "source": src}
        for k, lbl, unit, fmt_code, src in KPI_CATALOG
    ]

    ctx = {
        "project_code": project,
        "driver": driver,
        "driver_label": spec["label"],
        "scenario_display": scenario_display,
        "results": results,
        "kpi_catalog": kpi_catalog_dicts,
        "request": request,
    }
    return HTMLResponse(content=_templates.get_template("partials/sheet_sensitivity_results.html").render(ctx))
