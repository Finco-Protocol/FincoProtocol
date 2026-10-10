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

from fastapi import APIRouter, Depends, Form, Query, Request
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
    FieldErrorClass,
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


def _pct(fraction, digits: int = 2) -> str | None:
    """Format a fraction as a human-readable percentage without mutating stored value."""
    if fraction is None:
        return None
    return f"{float(fraction) * 100:.{digits}f}%"


def _fmt_runtime_at(ts) -> str:
    """Format an ISO timestamp or datetime into a human-readable string for the toolbar."""
    if not ts:
        return ""
    try:
        if isinstance(ts, datetime.datetime):
            dt = ts
        else:
            dt = datetime.datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        return dt.strftime("%-d %b %Y, %H:%M")
    except Exception:
        return ""


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


def _add_field_error_trigger(
    resp: HTMLResponse, field_id: str, message: str,
    error_class: Optional[FieldErrorClass] = None,
) -> HTMLResponse:
    """Attach the field-error HX event.

    ``error_class`` is the canonical server classification
    (``FieldValidationError.error_class``) and is the ONLY typed authority the
    browser may use.  It is JSON ``null`` for every rejection that is not a typed
    field-value validation outcome (stale draft, protected project, non-editable
    field, authority gate) — never fabricated.  Only a real ``FieldErrorClass``
    is serialised, so nothing else can reach the browser as a class.
    """
    import json as _json
    resp.headers["HX-Trigger"] = _json.dumps({
        "workbook-field-error": {
            "field_id": field_id,
            "message": message,
            "error_class": error_class.value if isinstance(error_class, FieldErrorClass) else None,
        }
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
    from app.v2.register_path_map import register_path_for_field
    from app.workbook.registry import (
        DATA_CENTER_FIELD_IDS,
        DC_CAPACITY_LABEL,
        DC_DERIVED_OPEX_FIELD_ID,
        DC_RENEWABLE_EXCLUDED_FIELD_IDS,
        EV_CHARGING_FIELD_IDS,
        EV_RENEWABLE_EXCLUDED_FIELD_IDS,
        is_data_center_project_type,
    )
    sheet = WORKBOOK.sheet(sheet_id)
    # Technology-conditional visibility: Data Center projects show the Data
    # Center driver fields and never the renewable-only controls; every other
    # technology hides the Data Center section.  EV Charging (Correction B)
    # mirrors this: EV shows the EV driver section and never the renewable/
    # PPA controls; every other technology hides the EV section.
    _dc_template = str(getattr(pis, "template_source", "") or "").strip().lower() == "generic_data_center_reference"
    _dc_type = is_data_center_project_type(pis.get("project_setup.identity.project_type") if hasattr(pis, "get") else None)
    is_data_center = _dc_template or _dc_type
    _origin = getattr(pis, "snapshot_origin", None) or {}
    try:
        _ev_template = str(_origin.get("template_source", "") or "").strip().lower() == "generic_ev_charging_reference"
    except AttributeError:
        _ev_template = False
    _ev_type = str(pis.get("project_setup.identity.project_type") or "").strip().lower() in (
        "ev charging", "ev_charging",
    ) if hasattr(pis, "get") else False
    is_ev_charging = _ev_template or _ev_type
    rows: list[dict] = []
    for section in sorted(sheet.sections, key=lambda s: s.order):
        for fspec in sorted(section.fields, key=lambda f: f.order):
            if is_data_center and fspec.field_id in DC_RENEWABLE_EXCLUDED_FIELD_IDS:
                continue
            if not is_data_center and fspec.field_id in DATA_CENTER_FIELD_IDS:
                continue
            if is_ev_charging and fspec.field_id in EV_RENEWABLE_EXCLUDED_FIELD_IDS:
                continue
            if not is_ev_charging and fspec.field_id in EV_CHARGING_FIELD_IDS:
                continue
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
            # Build option_labels: maps each option value to its display label.
            # Non-empty only when the canonical options have friendly labels
            # (currently: country_market). Template uses it for <option> display.
            if fspec.field_id == "project_setup.identity.country_market" and fspec.options:
                from app.workbook.country_options import COUNTRY_CODE_TO_LABEL
                option_labels: dict = COUNTRY_CODE_TO_LABEL
            else:
                option_labels = {}
            # For PCT-type read-only fields stored as fractions (e.g. 0.055), provide
            # display_value so the template can show "5.50%" without mutating the stored value.
            if field_type == "pct" and value is not None and not fspec.options:
                try:
                    v = float(value)
                    display_v = v * 100 if 0.0 < abs(v) < 1.0 else v
                    display_value: object = f"{display_v:.2f}%"
                except (TypeError, ValueError):
                    display_value = value
            else:
                display_value = value
            field_label = fspec.label
            if is_data_center and fspec.field_id == "project_setup.technical.capacity_mw":
                field_label = DC_CAPACITY_LABEL
            if (
                is_data_center
                and fspec.field_id == DC_DERIVED_OPEX_FIELD_ID
                and binding_label == "bound"
            ):
                # B.08 Power Expenses is a DERIVED authority for Data Center
                # (IT MW × occupancy × PUE × 8,760 × EUR/MWh): display-only.
                binding_label = "display-only"
            rows.append({
                "field_id": fspec.field_id,
                "label": field_label,
                "unit": fspec.unit,
                "field_type": field_type,
                "binding_label": binding_label,
                "options": list(fspec.options),
                "option_labels": option_labels,
                "section_id": section.section_id,
                "section_label": section.label,
                "value": value,
                "display_value": display_value,
                "required": fspec.required,
                "min_value": fspec.min_value,
                "max_value": fspec.max_value,
                "step": step,
                "help_text": fspec.description or "",
                # Proven Assumption Register path (exact engine_path claim) or None.
                "register_path": register_path_for_field(fspec.field_id),
            })
    # EV Charging (V1): presentation-only label/visibility adapter.
    from app.v2.ev_labels import apply_ev_presentation
    return apply_ev_presentation(rows, pis)


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


def _format_assumption_display(value):
    """UX Correction B1: presentation-only assumption value formatting.

    The canonical ``AssumptionEntry.value`` is NEVER touched — this renders
    the display string only (no parse-format-reparse, no rounding of stored
    values, no financial calculation):

    - ``None``           → em dash (missing is never zero)
    - ``bool``           → Yes / No (truthful display)
    - ``str`` / ``int``  → verbatim
    - ``float``          → institutional finite display (max 4 decimals,
      thousands separators, trailing zeros trimmed); non-finite → em dash
    - ``list`` / ``dict`` → recursive: numeric leaves formatted the same
      way, so raw long float reprs never reach the UI
    """
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, str):
        return value
    if isinstance(value, int):
        return f"{value:,}"
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            return "—"
        rounded = round(value, 4)
        if rounded == 0:
            return "0"
        text = f"{rounded:,.4f}"
        if "." in text:
            text = text.rstrip("0").rstrip(".")
        return text
    if isinstance(value, (list, tuple)):
        return ", ".join(_format_assumption_display(v) for v in value)
    if isinstance(value, dict):
        return ", ".join(
            f"{k}: {_format_assumption_display(v)}"
            for k, v in value.items())
    return str(value)


def _build_assumption_register_view(pis):
    """UX Correction A4/B1/B2: read-only Workflow 04 Assumption Register view.

    Pure construction over the working-copy ProjectInputs
    (``build_assumption_register`` — no I/O, no engine execution).  Used by
    the Trust sheet section (#assumption-register).  Fail closed: any
    construction failure renders a typed UNAVAILABLE view — never a
    fabricated register.

    B1: values render through the presentation formatter — raw float
    precision never reaches the UI and stored/canonical values stay
    byte-identical.  B2: on EV workbooks the register rows pass through the
    existing EV presentation authority (``app.v2.ev_labels``) — charging
    terminology for the internal compatibility price fields, and
    compatibility-only generation/PPA rows omitted (canonical identities
    unchanged).
    """
    try:
        from app.model_v2.assumption_register import (
            AssumptionSourceKind,
            RegisterContext,
            build_assumption_register,
        )
        inputs = pis.to_projectinputs()
        register = build_assumption_register(
            inputs,
            RegisterContext.for_working_copy(
                state_provenance=AssumptionSourceKind.USER_INPUT,
                workbook_composite_hash=getattr(pis, "content_hash", None),
            ),
        )
        rows = []
        for e in register.entries:
            rows.append({
                "section": e.section,
                "path": e.canonical_path,
                "label": e.label,
                "value": _format_assumption_display(e.value),
                "unit": e.unit or "",
                "source": e.source_ref or e.source_kind.value,
            })
        from app.v2.ev_labels import is_ev_pis, apply_ev_register_presentation
        if is_ev_pis(pis):
            rows = apply_ev_register_presentation(rows)
        return {
            "available": True,
            "entry_count": len(rows),
            "fingerprint": register.fingerprint,
            "rows": rows,
        }
    except Exception:
        return {"available": False, "entry_count": 0,
                "fingerprint": "", "rows": []}


def _quality_row_from_block(quality: dict) -> dict:
    sc = quality["score"]
    counts = sc["counts"]
    return {"score": sc["score"], "score_display": sc["score_display"], "score_status": sc["score_status"],
            "coverage_weighted_pct": sc["coverage_weighted_pct"], "blocked": sc["blocked"],
            "fail": counts["fail"], "warning": counts["warning"], "unavailable": counts["unavailable"],
            "blocking_ids": [c["check_id"] for c in quality["groups"]["blocking"]]}


def _attach_insight(smart_panel, *, ws, pis, project_record, workspace_owner, runtime_state, register_view):
    """Q3: attach the read-only Model Quality / covenant / scenario views to the Smart Panel projection.

    Pure reads of persisted evidence (workspace Last Run, Run History, scenario records); never runs the
    engine and never writes.  Any failure leaves typed UNAVAILABLE views — it can never fail the page.
    """
    import dataclasses
    from app.v2.insight_quality_projection import build_quality_insight_safe
    from app.v2.insight_scenario_projection import build_scenario_insight_safe

    register_paths = [str(r.get("path")) for r in ((register_view or {}).get("rows") or []) if isinstance(r, dict)]
    strip = smart_panel.kpi_strip
    kpi_keys = [it.key for it in strip.items] if strip else []
    effective_inputs = None
    if runtime_state == "CURRENT":
        try:
            effective_inputs = pis.to_projectinputs()
        except Exception:  # noqa: BLE001 - thresholds then stay unavailable
            effective_inputs = None
    active_id = getattr(ws, "active_scenario_id", None) if ws else None
    # The scenario shown with the Findings belongs to the COMMITTED Last Run (ws.last_runtime_scenario_id), not
    # to the Working Copy scenario currently selected.  NULL is the canonical Base Case; an unresolvable id stays
    # UNAVAILABLE (never Base Case, never the active scenario's name).
    last_run_scenario_name = ""
    if ws is not None and runtime_state != "NOT_RUN":
        try:
            from app.persistence.scenario_insight_reads import resolve_last_run_scenario
            resolved = resolve_last_run_scenario(workspace_owner, project_record.project_id,
                                                 getattr(ws, "last_runtime_scenario_id", None))
            last_run_scenario_name = resolved.label or ""
        except Exception:  # noqa: BLE001 - identity then stays UNAVAILABLE
            last_run_scenario_name = ""
    quality = build_quality_insight_safe(
        ws, run_state=runtime_state, project_inputs=effective_inputs, active_scenario_id=active_id,
        scenario_name=last_run_scenario_name,
        register_paths=register_paths, kpi_keys=kpi_keys)
    scenario_view: dict = {}
    try:
        from app.persistence.scenario_insight_reads import list_insight_scenarios, newest_committed_runs
        chosen = list_insight_scenarios(workspace_owner, project_record.project_id, active_id)
        latest = newest_committed_runs(workspace_owner, project_record.project_id, chosen.records)
        issue_count = None
        if quality.get("available") and quality.get("terms_bound"):
            issue_count = sum(1 for c in quality.get("covenants", ())
                              if c.get("status") in ("FAIL", "WARNING"))
        scenario_view = build_scenario_insight_safe(
            scenarios=chosen.records, latest_runs=latest, active_scenario_id=active_id, active_run_state=runtime_state,
            last_run_snapshot_id=getattr(ws, "last_runtime_snapshot_id", None) if ws else None,
            active_covenant_issue_count=issue_count, candidates=chosen.candidates,
            scenarios_complete=chosen.complete,
            active_quality=(_quality_row_from_block(quality) if quality.get("available") else None))
    except Exception:  # noqa: BLE001 - fail closed to a typed UNAVAILABLE view
        scenario_view = build_scenario_insight_safe(
            scenarios=[], latest_runs={}, active_scenario_id=None, active_run_state="NOT_RUN",
            last_run_snapshot_id=None, scenarios_complete=False)
    return dataclasses.replace(smart_panel, insight={"quality": quality, "scenarios": scenario_view})


def _base_sheet_ctx(request, pis, ws, project_record, project, field_error="", *, freshness=None):
    """Shared context dict for both sheet partials."""
    from app.workbook.registry import is_data_center_project_type as _is_dc_type_bsc
    if freshness is None:
        freshness = _runtime_freshness(ws, pis)
    _dc_tmpl = str(getattr(pis, "template_source", "") or "").strip().lower() == "generic_data_center_reference"
    _dc_type = _is_dc_type_bsc(pis.get("project_setup.identity.project_type") if hasattr(pis, "get") else None)
    _ev_tmpl = str(getattr(pis, "template_source", "") or "").strip().lower() == "generic_ev_charging_reference"
    _ev_type = str(pis.get("project_setup.identity.project_type") or "").strip().lower() in (
        "ev charging", "ev_charging",
    ) if hasattr(pis, "get") else False
    return {
        "request": request,
        "project_code": project,
        "workbook_version": pis.workbook_version,
        "content_hash": pis.content_hash,
        "template_source": pis.template_source,
        "is_data_center": _dc_tmpl or _dc_type,
        "is_ev_charging": _ev_tmpl or _ev_type,
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
        and (project_record.template_source or "").strip().lower() in ("generic_wind_reference", "generic_solar_reference", "generic_storage_reference", "generic_data_center_reference")
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
    from app.workbook.scenario_authority import resolve_active_scenario_overrides
    _scenario_overrides_raw, capex_scenario_error = resolve_active_scenario_overrides(
        project_record, ws, workspace_owner,
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

    from app.contingency_authority import resolve_pct as _resolve_cont_pct
    _cont_pct, _cont_src = _resolve_cont_pct(
        getattr(project_record, "replay_metadata", None), _scenario_overrides_raw, "capex",
    )
    capex_vm = build_capex_view_model(
        project_ctx, is_user_project=is_user, sub_lines=sub_lines,
        contingency_pct=_cont_pct, contingency_source=_cont_src,
    )

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
        "capex_inactive_lines": _inactive_cost_lines(project_record.project_id, "capex"),
        "capex_vm": capex_vm,
        "capex_group_to_field": capex_group_to_field,
        "capex_section_fields": capex_section_fields,
        "capex_alias_groups": capex_alias_groups,
        "capex_scenario_error": capex_scenario_error,
    }


def _inactive_cost_lines(project_id: str, kind: str) -> dict[str, list[dict]]:
    """Deactivated CAPEX/OPEX lines grouped by parent code, for the Reactivate
    list. Read-only presentation data straight from the persisted rows (the
    same rows the Reactivate command acts on); inactive lines are never part of
    any total."""
    from app.persistence.db import get_cursor

    if kind == "capex":
        from app.persistence.capex_sub_lines import list_inactive_sub_lines
        group_attr = "parent_category_code"
    else:
        from app.persistence.opex_sub_lines import list_inactive_sub_lines
        group_attr = "parent_group_code"
    try:
        with get_cursor() as cur:
            rows = list_inactive_sub_lines(cur, project_id)
    except Exception:  # presentation helper: never break the sheet
        return {}
    grouped: dict[str, list[dict]] = {}
    for r in rows:
        grouped.setdefault(getattr(r, group_attr), []).append({
            "sub_line_id": r.sub_line_id,
            "row_version": r.updated_at or "",
            "code": r.business_code,
            "label": r.label,
            "amount_keur": float(r.amount_keur or 0.0),
            "inflation_pct": getattr(r, "inflation_pct", None),
            "source": r.source,
        })
    return grouped


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


def _build_opex_vm_ctx(project_record, pis, ws=None, workspace_owner: str = "") -> dict:
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
        and (project_record.template_source or "").strip().lower() in ("generic_wind_reference", "generic_solar_reference", "generic_storage_reference", "generic_data_center_reference")
    )
    from app.persistence.opex_sub_lines import get_active_sub_lines_for_project as _get_opex_sub_lines
    opex_sub_lines = _get_opex_sub_lines(project_record.project_id)
    from app.contingency_authority import resolve_pct as _resolve_cont_pct
    from app.workbook.scenario_authority import resolve_active_scenario_overrides
    _ox_overrides, _ox_err = resolve_active_scenario_overrides(project_record, ws, workspace_owner)
    _ox_pct, _ox_src = _resolve_cont_pct(
        getattr(project_record, "replay_metadata", None), _ox_overrides, "opex",
    )
    opex_vm = build_opex_view_model(
        project_ctx, is_user_project=is_user, sub_lines=opex_sub_lines,
        contingency_pct=_ox_pct, contingency_source=_ox_src,
    )
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
        "opex_inactive_lines": _inactive_cost_lines(project_record.project_id, "opex"),
        "opex_scenario_error": _ox_err,
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
    ctx.update(_build_opex_vm_ctx(project_record, pis, ws=ws))
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

    fields = _build_sheet_fields("revenue", pis)
    by_id = {field["field_id"]: field for field in fields}

    # Presentation-only binding evidence.  These values are the existing
    # registry fields that the adapter passes to RevenueParams; no revenue is
    # calculated here and no Jinja expression infers a price from outputs.
    def _value(field_id):
        field = by_id.get(field_id)
        return field.get("value") if field else None

    curve_rows = []
    raw_curve = _value("revenue.merchant.price_curve_json")
    if isinstance(raw_curve, str) and raw_curve.strip():
        try:
            import json
            decoded = json.loads(raw_curve)
            if isinstance(decoded, list):
                curve_rows = tuple(
                    {"year": row.get("year"), "price": row.get("price_eur_mwh")}
                    for row in decoded
                    if isinstance(row, dict)
                )
        except (TypeError, ValueError):
            # The field editor owns validation; an invalid draft is never
            # silently interpreted as a price authority in this projection.
            curve_rows = ()

    return {
        "revenue_fields": fields,
        "revenue_state": revenue_state.value,
        "revenue_runtime_summary": rs,
        "revenue_pricing_basis": (
            ("Contracted tariff", _value("revenue.ppa.base_tariff"), "EUR/MWh"),
            ("PPA term", _value("revenue.ppa.term_years"), "years"),
            ("PPA escalation", _value("revenue.ppa.index"), "%"),
            ("Merchant balancing", _value("revenue.balancing.merchant_pct"), "% of spot sales"),
            ("Balancing cost", _value("revenue.balancing.cost_eur_per_mwh"), "EUR/MWh"),
            ("CO2 revenue", _value("revenue.balancing.co2_enabled"), ""),
            ("CO2 certificate price", _value("revenue.balancing.co2_price_eur_mwh"), "EUR/MWh"),
        ),
        "merchant_curve_rows": curve_rows,
        "merchant_start_year": str(pis.get("project_setup.technical.cod_date") or "")[:4],
        # Data Center transparent revenue reconciliation (spec M): shown only
        # for Data Center projects; power cost belongs to OPEX (B.08), never
        # to Revenue.
        "revenue_dc_reconciliation": _build_dc_revenue_reconciliation(pis),
        "revenue_output_context": {
            # Already-formatted persisted evidence is displayed verbatim,
            # never parsed or used as an input to presentation arithmetic.
            "generation": (revenue_derivation or {}).get("sample_generation_mwh"),
            "period": (revenue_derivation or {}).get("sample_period_label"),
            "persisted_revenue": (revenue_derivation or {}).get("display_value_keur"),
        },
    }


def _build_dc_revenue_reconciliation(pis) -> list[tuple[str, object, str]]:
    """Return the Data Center revenue reconciliation rows for the Revenue sheet.

    Deterministic display math from the persisted Data Center drivers only:
        Core capacity revenue (stabilized, pre-indexation, kEUR)
            = IT capacity MW × 1,000 kW/MW × 12 × price(EUR/kW/month) × occupancy
    The indexation, occupancy ramp and capacity edits are derived at runtime
    by app.data_center_authority; no separate revenue amount is stored.
    """
    if not hasattr(pis, "get"):
        return []

    def _f(field_id: str, default: float | None = None) -> float | None:
        v = pis.get(field_id)
        if v in (None, ""):
            return default
        try:
            return float(v)
        except (TypeError, ValueError):
            return default

    capacity = _f("project_setup.technical.capacity_mw")
    price = _f("revenue.data_center.service_price")
    occ_stab = _f("revenue.data_center.occupancy_stabilized")
    if capacity is None or price is None or occ_stab is None:
        return []
    occ_fraction = occ_stab / 100.0 if occ_stab > 1.0 else occ_stab
    occupied_mw = capacity * occ_fraction
    core_revenue_keur = capacity * 12.0 * price * occ_fraction
    escalation = _f("revenue.data_center.revenue_escalation", 0.0)
    return [
        ("IT Capacity", f"{capacity:.12g}", "MW IT"),
        ("Available IT Capacity", f"{capacity * 1000:.12g}", "kW"),
        ("Occupancy (Stabilized)", f"{occ_fraction * 100:.12g}", "%"),
        ("Occupied IT MW", f"{occupied_mw:.12g}", "MW"),
        ("Service Price", f"{price:.12g}", "EUR/kW/month"),
        ("Core Capacity Revenue (stabilized, pre-indexation)", f"{core_revenue_keur:.12g}", "kEUR/yr"),
        ("Revenue Escalation", f"{(escalation / 100.0 if escalation > 1.0 else escalation) * 100:.12g}", "%/yr"),
        ("Total Revenue", "Runtime-derived (occupancy ramp + indexation)", ""),
    ]


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


def _enum_value(value):
    """Present a typed enum without inferring a financing policy."""
    return getattr(value, "value", value) if value is not None else None


def _build_sponsor_funding_presentation(fin, rr, freshness) -> dict:
    """Separate current typed financing inputs from immutable Last Run evidence.

    This is intentionally a projection helper: it reads neither an engine nor
    any legacy financing amount, and it never derives a terminal SHL value.
    """
    state = getattr(getattr(freshness, "state", None), "value", "NOT_RUN")
    if state not in {"NOT_RUN", "CURRENT", "STALE"}:
        state = "NOT_RUN"
    evidence_status = {
        "NOT_RUN": "UNAVAILABLE",
        "CURRENT": "CURRENT",
        "STALE": "LAST RUN / STALE",
    }[state]
    freshness_label = {
        "NOT_RUN": "NOT RUN — Last Run evidence unavailable",
        "CURRENT": "CURRENT — Last Run evidence",
        "STALE": "LAST RUN / STALE — Working inputs may differ from persisted evidence",
    }[state]
    sponsor_schedule = _thaw(getattr(rr, "sponsor_schedule", None) or {})
    sponsor_summary = (
        sponsor_schedule.get("summary", {})
        if isinstance(sponsor_schedule, dict) else {}
    )
    return {
        "sponsor_working_rows": (
            ("Sponsor funding mode", _enum_value(getattr(fin, "sponsor_funding_mode", None)) if fin else None, "Reference model"),
            ("Share capital contribution", getattr(fin, "share_capital_keur", None), "Reference model"),
            ("Share premium contribution", getattr(fin, "share_premium_keur", None), "Reference model"),
            ("Other equity before SHL", getattr(fin, "other_equity_funding_before_shl_keur", None), "Reference model"),
            ("Configured SHL amount", getattr(fin, "shl_amount_keur", None), "Reference model"),
            ("SHL interest rate", f"{getattr(fin, 'shl_rate', 0.0) * 100:.2f}%" if fin else None, "Reference model"),
            ("SHL repayment method", _enum_value(getattr(fin, "clean_shl_repayment_method", None)) if fin else None, "Reference model"),
            ("SHL repayment eligibility start", getattr(fin, "shl_principal_eligibility_start_period", None) if fin else None, "Reference model"),
            ("SHL maturity", getattr(fin, "shl_maturity_period_index", None) if fin else None, "Reference model"),
            ("SHL day-count convention", _enum_value(getattr(fin, "shl_day_count_convention", None)) if fin else None, "Reference model"),
        ),
        "sponsor_last_run_rows": (
            ("Runtime-derived SHL principal", sponsor_summary.get("total_shl_cash_contributed_keur"), evidence_status),
            # The persisted sponsor presentation contract has no terminal SHL
            # balance/status.  Absence is shown truthfully rather than rebuilt.
            ("Terminal SHL balance / status", None, "UNAVAILABLE"),
        ),
        "sponsor_funding_freshness": {
            "state": state,
            "label": freshness_label,
            "evidence_status": evidence_status,
        },
    }


def _build_debt_ctx(pis, ws, projection=None, *, context=None) -> dict:
    """Build Senior Debt sheet context: registry fields + RuntimeResult output.

    When a pre-built WorkbookRuntimeProjection bundle is supplied (GET handler),
    it is reused so that only one get_runtime_result call is made per request.
    When called standalone (HTMX sheet re-render), the bundle is built here.
    """
    from app.workbook.runtime_projection import build_runtime_projection_bundle
    from app.workbook.service import WorkbookService
    if context is not None:
        context.require_binding(ws, context.project_record, context.runtime_result)
    if projection is None:
        rr = WorkbookService.get_runtime_result(ws)
        from app.workbook.runtime_projection import build_runtime_projection_bundle
        projection = build_runtime_projection_bundle(
            rr, _runtime_freshness(ws, pis).is_stale)
    d = projection.debt
    # Sponsor/SHL is a presentation of the existing typed financing inputs and
    # persisted Last Run sponsor schedule.  It deliberately does not expose
    # the legacy configured amount as a runtime authority or create a second
    # write path.
    try:
        finance_pi = pis.to_projectinputs()
        fin = finance_pi.financing
    except Exception:
        finance_pi = None
        fin = None
    rr_for_sponsor = context.runtime_result if context is not None else WorkbookService.get_runtime_result(ws)
    sponsor_funding = _build_sponsor_funding_presentation(
        fin, rr_for_sponsor, context.freshness if context is not None else _runtime_freshness(ws, pis)
    )
    # R8/N02: policy-governed editability — calibrated schedules lock the
    # scalar Senior controls with the honest reason.
    senior_pricing_mode, senior_dscr_mode = _classify_senior_authority(pis)
    from app.v2.financing_projection import (
        build_financing_evidence, build_reserve_view, build_sponsor_view,
        senior_editor_fields,
    )
    debt_fields = _lock_senior_fields_if_calibrated(
        senior_editor_fields(_build_sheet_fields("debt", pis), finance_pi),
        senior_pricing_mode, senior_dscr_mode)
    from app.workbook.bankability_config import FIELD_ID, SNAPSHOT_KEY, build_view
    bankability = build_view(finance_pi, pis.snapshot_origin.get(SNAPSHOT_KEY),
        project_type=pis.snapshot_origin.get("project_type"))
    if bankability.get("available"):
        from app.workbook.bankability_config import workspace_fees_editable
        try:
            bankability["fees_editable"] = workspace_fees_editable(finance_pi, ws)
        except (ValueError, AttributeError):
            bankability["fees_editable"] = False
    debt_fields = [f for f in debt_fields if f["field_id"] != FIELD_ID]
    for field in debt_fields:
        key = {"debt.senior.interest_rate_pct": "rates_pct", "debt.senior.target_dscr": "targets"}.get(field["field_id"])
        if key and bankability.get("config", {}).get(key) is not None:
            field["editable"] = False
            field["binding_label"] = "template-locked"
            field["help_text"] = "Bankability configuration owns this input; edit or reset the configuration below."
    if bankability.get("config", {}).get("rates_pct") is not None:
        senior_pricing_mode = "WORKING_CONFIG"
    if bankability.get("config", {}).get("targets") is not None:
        senior_dscr_mode = "WORKING_CONFIG"
    financing_evidence = build_financing_evidence(rr_for_sponsor)
    from app.workbook.multisenior_config import (
        FIELD_ID as f3_field, SNAPSHOT_KEY as f3_key, build_view as build_f3_view, scope_for_workspace,
    )
    f3 = build_f3_view(finance_pi, pis.snapshot_origin.get(f3_key), scope_for_workspace(ws),
        rr_for_sponsor.runtime_summary if rr_for_sponsor else None,
        owner_id=ws.user_id, project_id=ws.project_id)
    debt_fields = [f for f in debt_fields if f["field_id"] != f3_field]
    if f3["active"]:
        from app.workbook.multisenior_config import activation_financing_params
        fin = activation_financing_params(fin)
        sponsor_funding = _build_sponsor_funding_presentation(
            fin, rr_for_sponsor, context.freshness if context is not None else _runtime_freshness(ws, pis))
        senior_pricing_mode = senior_dscr_mode = "MULTI_SENIOR"
        bankability = {"available": False, "reason": "Two-Senior terms own rates, fees, repayment and maturity. Single-Senior bankability controls are inactive."}
        for field in debt_fields:
            if field["field_id"] not in {"debt.senior.gearing_pct", "debt.senior.lockup_dscr", "debt.senior.min_llcr"}:
                field["editable"] = False
                field["help_text"] = "Owned by the active two-Senior configuration."
    _actual_senior, _actual_gearing = financing_evidence["metrics"][:2]
    from app.input_adapter import senior_rate_authority
    _flat_senior_rate = senior_rate_authority(finance_pi)[1] if finance_pi else None
    return {
        "debt_fields": debt_fields,
        "bankability": bankability,
        "multisenior": f3,
        "debt_state": d.state.value,
        "debt_schedule": d.schedule,
        "debt_operational_periods": d.operational_periods,
        "runtime_summary": d.runtime_summary,
        "senior_pricing_mode": senior_pricing_mode,
        "senior_dscr_mode": senior_dscr_mode,
        "debt_actual_senior_keur_display": _actual_senior.display if _actual_senior.value is not None else None,
        "debt_actual_gearing_pct_display": _actual_gearing.display if _actual_gearing.value is not None else None,
        "financing_evidence": financing_evidence,
        "reserve_view": build_reserve_view(fin),
        "sponsor_view": build_sponsor_view(fin, rr_for_sponsor),
        "senior_detail_rows": (
            ("Max. gearing cap", _pct(getattr(fin, "gearing_ratio", None)) if fin else None),
            ("Lock-up DSCR", f"{getattr(fin, 'lockup_dscr', 0.0):.2f}x" if fin else None),
            ("Minimum LLCR", f"{getattr(fin, 'min_llcr', 0.0):.2f}x" if fin else None),
        ) if f3["active"] else (
            ("Max. gearing cap", _pct(getattr(fin, "gearing_ratio", None)) if fin else None),
            ("All-in interest rate", _pct(_flat_senior_rate)),
            ("Base rate", f"{getattr(fin, 'base_rate', 0.0) * 100:.2f}%" if fin else None),
            ("Margin", f"{getattr(fin, 'margin_bps', 0)} bps" if fin else None),
            ("Commitment fee", f"{getattr(fin, 'commitment_fee', 0.0) * 100:.2f}%" if fin else None),
            ("Arrangement fee", f"{getattr(fin, 'arrangement_fee', 0.0) * 100:.2f}%" if fin else None),
            ("Structuring fee", f"{getattr(fin, 'structuring_fee', 0.0) * 100:.2f}%" if fin else None),
            ("Lock-up DSCR", f"{getattr(fin, 'lockup_dscr', 0.0):.2f}x" if fin else None),
            ("Minimum LLCR", f"{getattr(fin, 'min_llcr', 0.0):.2f}x" if fin else None),
            ("Amortization", getattr(fin, "amortization_type", None) if fin else None),
            ("DSRA coverage", f"{getattr(fin, 'dsra_months', 0)} months" if fin else None),
        ),
        **sponsor_funding,
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

    from app.workbook.registry import is_data_center_project_type as _is_dc_type
    _is_dc_template = str(getattr(pis, "template_source", "") or "").strip().lower() == "generic_data_center_reference"
    _is_dc = _is_dc_template or _is_dc_type(pis.get("project_setup.identity.project_type") if hasattr(pis, "get") else None)
    _is_ev_template = str(getattr(pis, "template_source", "") or "").strip().lower() == "generic_ev_charging_reference"
    _is_ev = _is_ev_template or str(pis.get("project_setup.identity.project_type") or "").strip().lower() in (
        "ev charging", "ev_charging",
    ) if hasattr(pis, "get") else False

    context = {
        "project_code": project,
        "project_name": project_record.project_name or project,
        "project_type": (project_record.project_type or "").capitalize(),
        "is_data_center": _is_dc,
        "is_ev_charging": _is_ev,
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
        "cert_project_code": (
            project_record.project_code
            if ws.any_run_committed and getattr(ws, "last_runtime_identity", None) is not None
            else ""
        ),
        "flash_error": flash_error,
        "field_error": "",
        "library_url": "/library",
    }
    # Model Trust Pack V1: read-only composition of existing canonical read
    # services (API v1.1 institutional builders).  No engine execution, no
    # state mutation; fails closed to explicit UNAVAILABLE sections.
    from app.ui.trust_pack import build_trust_pack
    try:
        context["trust_pack"] = build_trust_pack(

            workspace_owner,
            project_record.project_id,
            project_code=project_record.project_code,
            any_run_committed=bool(ws.any_run_committed),
        )
    except Exception:  # fail closed — an evidence surface must never 500
        from app.api.v1_1.institutional import STATE_UNAVAILABLE as _TUP
        context["trust_pack"] = {
            "overall_state": _TUP,
            "last_run": {"state": _TUP, "working_copy_changed_since_run": False},
            "kpis": {"state": _TUP, "rows": [], "lineage": {}},
            "validation": {
                "state": "DEFERRED",
                "load_url": f"/v2/workbook/trust/validation?project={project_record.project_code}",
                "gaps": [],
                "gap_count": 0,
            },
            "verify": {"state": _TUP, "verify_url": f"/verify/run/{project_record.project_code}"},
            "export": {"state": _TUP},
            "methodology": {"state": _TUP, "rows": [], "page_url": "/model/methodology"},
        }
    context.update(_build_capex_vm_ctx(project_record, pis, ws=ws, workspace_owner=workspace_owner))
    context.update(_build_opex_vm_ctx(project_record, pis, ws=ws, workspace_owner=workspace_owner))
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

    # UX Foundation: compact workspace header + persistent left navigation.
    # Presentation projections only — identity comes from the same pis the
    # overview uses; state comes from the canonical freshness authority.
    context["assumption_register_view"] = _build_assumption_register_view(pis)

    from app.v2.workspace_shell_projection import (
        build_workspace_header_projection,
        workspace_nav_groups,
    )
    context["header"] = build_workspace_header_projection(
        project_name=project_record.project_name or project,
        technology=context.get("project_type", ""),
        country_iso=getattr(context.get("overview"), "country_iso", ""),
        capacity_mw=getattr(context.get("overview"), "capacity_mw", None),
        project_editable=context.get("project_editable", True),
        runtime_state=runtime_freshness.state.value,
        has_runtime=bool(context.get("has_runtime")),
        last_runtime_at_display=context.get("last_runtime_at", "") or "",
        active_scenario_name=context.get("active_scenario_name", "") or "",
    )
    context["ws_nav_groups"] = workspace_nav_groups()

    # UX Foundation Phase C: contextual Smart Panel (availability +
    # navigation over existing authorities; never an engine call).
    from app.v2.smart_panel_projection import build_smart_panel_projection
    # Run Intelligence V1: read-only run history listing on its own tab.
    context.update(_run_history_listing_ctx(project_record, ws, pis))

    context["smart_panel"] = build_smart_panel_projection(
        trust_pack=context.get("trust_pack"),
        runtime_state=runtime_freshness.state.value,
        has_runtime=bool(context.get("has_runtime")),
        project_key=str(getattr(pis, "template_source", "") or ""),
        assumption_register_view=context.get("assumption_register_view"),
    )
    context["smart_panel"] = _attach_insight(
        context["smart_panel"], ws=ws, pis=pis, project_record=project_record,
        workspace_owner=workspace_owner, runtime_state=runtime_freshness.state.value,
        register_view=context.get("assumption_register_view"))

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

    def _render_field_error(
        message: str, status_code: int, *, preserve_submitted: bool = False,
        error_class: Optional[FieldErrorClass] = None,
    ) -> HTMLResponse:
        pis_for_render = _build_pis_with_composite_identity(
            ws, project_record, workspace_owner
        )
        resp = _render_sheet_response(
            message,
            status_code=status_code,
            preserve_submitted=preserve_submitted,
            pis_for_render=pis_for_render,
        )
        return _add_field_error_trigger(resp, field_id, message, error_class)

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
            _render_field_error(
                str(exc), 422, preserve_submitted=True, error_class=exc.error_class)
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
            return _add_field_error_trigger(resp, field_id, str(exc), exc.error_class)
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


# Presentation-only: typed engine fail-closed reasons -> plain language.
# The engine's decision (and its typed reason) is unchanged; nothing is saved
# on a failed run and the previous Last Run stays exactly as it was.
_ENGINE_FAIL_CLOSED_MESSAGES = (
    ("F3_PERIOD_OVERFUNDING", "F3_PERIOD_OVERFUNDING: A dated facility draw exceeds construction Uses in that period. Adjust the draw dates or amounts. No Run was saved."),
    ("F3_AGGREGATE_GEARING_CAP_EXCEEDED", "F3_AGGREGATE_GEARING_CAP_EXCEEDED: The explicit facility commitments exceed the project gearing cap. No automatic resizing is applied; no Run was saved."),
    ("F3_CONTRACTUAL_SERVICE_CASH_SHORTFALL", "F3_CONTRACTUAL_SERVICE_CASH_SHORTFALL: Base cash cannot pay the contractual Senior service, including maturity principal. No repayment or refinancing was manufactured; no Run was saved."),
    ("F3_MATURITY_NOT_ON_OPERATING_BOUNDARY", "F3_MATURITY_NOT_ON_OPERATING_BOUNDARY: Facility maturity must match a canonical operating period end. No Run was saved."),
    ("F3_DRAW_OUTSIDE_CONSTRUCTION", "F3_DRAW_OUTSIDE_CONSTRUCTION: Facility draws must fall within construction. No Run was saved."),
    ("F3_GRACE_EXCEEDS_MATURITY", "F3_GRACE_EXCEEDS_MATURITY: No principal-eligible period remains before maturity. No Run was saved."),
    ("SHL_MATURITY_RESIDUAL_FAILS_CLOSED",
     "These inputs leave part of the shareholder loan unpaid at its maturity, so "
     "the model did not produce a result. Review OPEX, CAPEX, revenue or "
     "shareholder-loan terms and run again. Your edits are saved; the previous "
     "Last Run is unchanged."),
)
_ENGINE_FAIL_CLOSED_GENERIC = (
    "The model's integrity checks stopped this run for the current inputs, so no "
    "result was produced. Review your recent changes and run again. Your edits "
    "are saved; the previous Last Run is unchanged."
)


def _engine_failure_message(exc: BaseException) -> str:
    """Safe user message for an engine failure (never raw internals).

    Reads only the TYPED reason the engine already produced (process mode:
    ``ModelWorkerError.reason_code/detail``; thread mode: the engine exception
    text). Unknown failures keep the generic message."""
    evidence = " ".join(
        str(part) for part in (
            getattr(exc, "reason_code", ""), getattr(exc, "detail", ""), exc,
        ) if part
    )
    for token, message in _ENGINE_FAIL_CLOSED_MESSAGES:
        if token in evidence:
            return message
    if "FAIL_CLOSED" in evidence:
        return _ENGINE_FAIL_CLOSED_GENERIC
    return "Engine run failed — please try again or contact support."


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

    from app.services.run_stage_timing import (
        log_run_stages, mark as _stage_mark, start_run_stages,
    )
    start_run_stages()

    from app.persistence.projects_repository import resolve_accessible_project
    project_record, workspace_owner = resolve_accessible_project(user.user_id, project)
    if project_record is None:
        msg = f"Project {project!r} not found."
        return _htmx_error(msg) if is_htmx else _non_htmx_error(msg)

    ws = get_workspace_state(user_id=workspace_owner, project_id=project_record.project_id)
    if ws is None:
        msg = "Workspace not found."
        return _htmx_error(msg) if is_htmx else _non_htmx_error(msg)
    _stage_mark("project_workspace_resolved")

    # ── Step 2b: unsupported project-type guard ───────────────────────────── #
    # Must come BEFORE the hash check so Storage projects always receive 409
    # (both HTMX and non-HTMX) rather than a stale-hash 303 redirect.
    # Covers all user-owned Storage projects (not just working_copy role) via
    # the is_protected_reference check — the capability boundary is
    # "protected reference" vs "user-owned editable project".
    _run_type_lower = (getattr(project_record, "project_type", "") or "").strip().lower()
    if _run_type_lower not in ("solar", "wind", "data center", "ev charging") and not is_protected_reference(project_record):
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
    elif project_type_raw in ("data center", "data_center", "datacenter"):
        runtime_project_key = "Generic Data Center Reference"
    elif project_type_raw in ("ev charging", "ev_charging"):
        runtime_project_key = "Generic EV Charging Hub Reference"
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

        if not sc_rec.is_base_case and "tariff_eur_mwh" in (sc_rec.overrides or {}):
            from app.workbook.scenario_revenue_authority import bind_scenario_tariff
            try:
                effective_snapshot = bind_scenario_tariff(
                    dict(pis_draft.snapshot_origin), sc_rec.overrides)
                override = WorkbookService.to_projectinputs(
                    WorkbookService.build_input_set(effective_snapshot))
            except ValueError as exc:
                msg = str(exc)
                return _htmx_error(msg, ws) if is_htmx else _non_htmx_error(msg)

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

    from app.workbook.bankability_config import SNAPSHOT_KEY, assert_materialized_fee_authority
    try:
        assert_materialized_fee_authority(override, pis_draft.snapshot_origin.get(SNAPSHOT_KEY))
        from app.workbook.multisenior_config import SNAPSHOT_KEY as f3_key, apply_state
        f3_scope = "base" if not active_scenario_id or sc_rec.is_base_case else active_scenario_id
        override = apply_state(override, pis_draft.snapshot_origin.get(f3_key), f3_scope,
            bankability_raw=pis_draft.snapshot_origin.get(SNAPSHOT_KEY))
    except ValueError as exc:
        msg = str(exc)
        return _htmx_error(msg, ws) if is_htmx else _non_htmx_error(msg)

    # ── Step 11: run the engine ────────────────────────────────────────────── #
    # P0-A: the calculation runs in the bounded model executor (worker process), never on the
    # event loop. The final CAS (v2_atomic_run_commit, step 12) is unchanged and runs only after
    # the calculation returns, so a stale calculation still fails closed.
    from app.runtime.model_execution import (
        BUSY_MESSAGE, ModelExecutionBusy, ModelExecutionFailed, ModelExecutionTimeout,
        run_model_process,
    )
    _stage_mark("model_entered")
    try:
        result = await run_model_process(
            run_project,
            runtime_project_key,
            "Base",  # Contract A: always "Base"; display name must not activate legacy ScenarioManager
            project_inputs_override=override,
        )
        _stage_mark("model_completed")
    except ModelExecutionBusy:
        # BUSY != CALCULATION_FAILED: nothing ran, nothing changed, safe to retry.
        if is_htmx:
            busy = _htmx_error(BUSY_MESSAGE, ws)
            busy.status_code = 429
            busy.headers["Retry-After"] = "5"
            busy.headers["X-Finco-Model-Busy"] = "1"
            return busy
        return JSONResponse({"state": "MODEL_EXECUTION_BUSY", "message": BUSY_MESSAGE},
                            status_code=429, headers={"Retry-After": "5"})
    except (ModelExecutionTimeout, ModelExecutionFailed):
        import logging
        logging.getLogger(__name__).error("v2_workbook_run: executor failure or timeout")
        msg = "The calculation could not be completed. Nothing was saved; please retry."
        return _htmx_error(msg, ws) if is_htmx else _non_htmx_error(msg)
    except Exception as exc:
        import logging
        logging.getLogger(__name__).exception("v2_workbook_run: engine failure")
        msg = _engine_failure_message(exc)
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
    _scenario_revenue_input = None
    if runtime_project_key in ("Solar", "Wind"):
        _scenario_revenue_input = {
            "effective_tariff_eur_mwh": override.revenue.ppa_base_tariff,
            "scenario_id": active_scenario_id,
            "authority": "materialized_project_inputs",
        }
        _kpis_enriched["scenario_revenue_input"] = _scenario_revenue_input

    # ── Step 12: atomic commit (final CAS + promote + dirty=False) ────────── #
    runtime_snapshot_id = _utc_compact()
    ran_at = datetime.now(timezone.utc)
    # F1 Correction A: bind engine-produced finance evidence to the exact
    # successful V2 commit. This same runtime_summary is atomically captured
    # in Last Run and the append-only Run History entry by existing CAS.
    if "financing_evidence" in result:
        _kpis_enriched["financing_evidence"] = {
            **result["financing_evidence"],
            "run_binding": {
                "snapshot_id": runtime_snapshot_id,
                "composite_hash": content_hash,
                "scenario_id": active_scenario_id,
                **({"financing_scope": f3_scope} if result["financing_evidence"].get("facility_authority") else {}),
            },
        }
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
            integrity_evidence=result.get("integrity_evidence"),
            active_scenario_id=active_scenario_id,
            active_scenario_name=active_scenario_name,
            last_runtime_scenario_id=active_scenario_id,
            ran_at=ran_at,
        )
        _stage_mark("persistence_completed")
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
                "scenario_revenue_input": _scenario_revenue_input,
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
                    "scenario_revenue_input": _scenario_revenue_input,
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
    from app.v2.post_run_ui import build_coherent_post_run_ui_state
    from app.v2.post_run_context import PostRunContextChanged
    from app.workbook.workbook_identity import WorkbookIdentityError

    try:
        combined = build_coherent_post_run_ui_state(
            request=request, ws_fresh=ws_fresh, project_record=project_record,
            project=project, workspace_owner=workspace_owner, rr=rr)
    except (PostRunContextChanged, WorkbookIdentityError, PermissionError):
        # The Run remains committed. Do not emit a mixed CURRENT response or
        # overwrite a concurrent scenario's evidence; existing GET reconciles.
        return HTMLResponse(
            "Run saved. Workspace changed while updating the view; reload the workbook.",
            status_code=409)
    _stage_mark("response_generated")
    log_run_stages(project_type=project_record.project_type, origin="v2_workbook_run")
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
        "generic_data_center_reference",
        "generic_wind", "generic_solar", "generic_storage", "generic_data_center",
    }
    if _ts in _known:
        runtime_project_code = _ts
    else:
        _pt = (project_record.project_type or "").strip().lower()
        if _pt == "solar":
            runtime_project_code = "generic_solar"
        elif _pt in ("storage", "bess"):
            runtime_project_code = "generic_storage"
        elif _pt in ("data center", "data_center", "datacenter"):
            runtime_project_code = "generic_data_center"
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
# Model Trust Pack V1 — on-demand Reference Regression Check evidence fragment.
# Deliberately a user-triggered load (explicit click in the Trust Pack panel):
# vertical validation executes the reference production model inside
# app.model_validation, so it must never run during workbook page rendering.
# ═══════════════════════════════════════════════════════════════════════════════


@router.get("/workbook/financing/investor")
async def v2_financing_investor(request: Request, project: str):
    """Refresh the owned, read-only Investor surface without a shared OOB edit."""
    user = _get_current_user(request)
    if not user:
        return JSONResponse({"error": "auth required"}, status_code=401)
    from app.persistence.projects_repository import resolve_accessible_project
    from app.v2.post_run_context import PostRunRequestContext, PostRunContextChanged
    from app.workbook.workbook_identity import WorkbookIdentityError

    record, owner = resolve_accessible_project(user.user_id, project)
    if record is None:
        return HTMLResponse("Project not found.", status_code=404)
    try:
        context = PostRunRequestContext.capture(owner_id=owner, project_id=record.project_id)
        ctx = _base_sheet_ctx(request, context.inputs, context.workspace, context.project_record,
                              project, freshness=context.freshness)
        ctx.update(_build_debt_ctx(context.inputs, context.workspace,
                                  projection=context.projection, context=context))
        html = _templates.get_template("partials/sheet_investor.html").render(ctx)
        context.validate_current()
    except (PostRunContextChanged, WorkbookIdentityError, PermissionError):
        html = '<div id="v2-sheet-investor" role="status">Financing evidence unavailable: workspace changed during response assembly. Reload the workbook to refresh.</div>'
    return HTMLResponse(html, headers={"Cache-Control": "no-store"})


@router.get("/workbook/outputs")
async def v2_outputs_workspace(request: Request, project: str):
    """Statements & Debt output workspace: read-only presentation of the persisted Last Run.

    One coherent authorized snapshot (``PostRunRequestContext``) supplies the Run evidence, the canonical
    CURRENT/STALE/NOT_RUN freshness and the Run Integrity verdict.  No engine call, no write.
    """
    user = _get_current_user(request)
    if not user:
        return JSONResponse({"error": "auth required"}, status_code=401)
    from app.persistence.projects_repository import resolve_accessible_project
    from app.v2.post_run_context import PostRunRequestContext, PostRunContextChanged
    from app.workbook.workbook_identity import WorkbookIdentityError
    from app.api.v1_1.institutional import get_run_integrity_checks
    from app.v2.output_workspace_projection import build_output_workspace_safe

    record, owner = resolve_accessible_project(user.user_id, project)
    if record is None:
        return HTMLResponse("Project not found.", status_code=404)
    try:
        context = PostRunRequestContext.capture(owner_id=owner, project_id=record.project_id)
        state, report = get_run_integrity_checks(owner, record.project_id, context=context)
        outputs = build_output_workspace_safe(
            runtime_result=context.runtime_result, workspace=context.workspace, freshness=context.freshness,
            integrity_report=report if state == "AVAILABLE" else None)
        context.validate_current()
    except (PostRunContextChanged, WorkbookIdentityError, PermissionError):
        outputs = {"state": "UNAVAILABLE", "message": "Statements unavailable: the workspace changed while the response "
                   "was assembled. Reload to refresh."}
    html = _templates.get_template("partials/sheet_outputs.html").render(outputs=outputs, project_code=project)
    return HTMLResponse(html, headers={"Cache-Control": "no-store"})


@router.get("/workbook/financing/integrity")
async def v2_financing_integrity(request: Request, project: str):
    """Authorized, read-only near-KPI view of the canonical integrity authority.

    Loaded independently so existing post-run OOB assembly stays untouched.
    """
    user = _get_current_user(request)
    if not user:
        return JSONResponse({"error": "auth required"}, status_code=401)
    from app.persistence.projects_repository import resolve_accessible_project
    from app.v2.post_run_context import PostRunRequestContext, PostRunContextChanged
    from app.workbook.workbook_identity import WorkbookIdentityError
    from app.api.v1_1.institutional import get_run_integrity_checks
    from app.v2.financing_projection import integrity_view

    record, owner = resolve_accessible_project(user.user_id, project)
    if record is None:
        return HTMLResponse("Project not found.", status_code=404)
    try:
        context = PostRunRequestContext.capture(owner_id=owner, project_id=record.project_id)
        # Same institutional read used by Trust, with V6's coherent authorized snapshot.
        state, report = get_run_integrity_checks(owner, record.project_id, context=context)
        view = integrity_view(report if state == "AVAILABLE" else {}, context.freshness.state.value)
        context.validate_current()
    except (PostRunContextChanged, WorkbookIdentityError, PermissionError):
        # Never pair one run's verdict with another run's freshness.
        view = integrity_view({}, "UNAVAILABLE")
    html = _templates.get_template("partials/_financing_integrity.html").render(
        financing_integrity=view, project_code=project)
    return HTMLResponse(html, headers={"Cache-Control": "no-store"})


@router.get("/workbook/trust/certificate")
async def v2_trust_certificate_fragment(request: Request, project: str):
    user = _get_current_user(request)
    if not user:
        return JSONResponse({"error": "auth required"}, status_code=401)

    from app.persistence.projects_repository import resolve_accessible_project
    from app.ui.trust_pack import build_certificate_fragment

    project_record, workspace_owner = resolve_accessible_project(user.user_id, project)
    if project_record is None:
        return HTMLResponse(
            content="<div class=\"v2-trust-note\">Project not found.</div>",
            status_code=404,
        )
    try:
        section = build_certificate_fragment(workspace_owner, project_record.project_id)
    except Exception:
        section = {"state": "UNAVAILABLE", "reason": "CERTIFICATE_UNAVAILABLE", "not_verify": True}
    return _templates.TemplateResponse(
        request=request,
        name="partials/_trust_certificate_body.html",
        context={"trust_certificate": section},
    )


@router.get("/workbook/trust/validation")
async def v2_trust_validation_fragment(request: Request, project: str):
    user = _get_current_user(request)
    if not user:
        return JSONResponse({"error": "auth required"}, status_code=401)

    from app.persistence.projects_repository import resolve_accessible_project
    from app.persistence.workspace_repository import get_workspace_state as _gws
    from app.ui.trust_pack import build_validation_fragment

    project_record, workspace_owner = resolve_accessible_project(user.user_id, project)
    if project_record is None:
        return HTMLResponse(
            content="<div class=\"v2-trust-note\">Project not found.</div>",
            status_code=404,
        )
    ws = _gws(workspace_owner, project_record.project_id)
    if ws is None or not ws.any_run_committed:
        return HTMLResponse(content=(
            "<div class=\"v2-trust-note\" data-testid=\"trust-pack-validation-unavailable\">"
            "<span class=\"v2-trust-chip v2-trust-chip--unavailable\">UNAVAILABLE</span> "
            "No committed Last Run — validation evidence is unavailable.</div>"
        ))
    # P0-A: the Reference Regression Check runs the P1.3 reconciliation (model work). Bounded
    # thread offload behind the shared admission gate; never on the event loop.
    from app.runtime.model_execution import BUSY_MESSAGE, ModelExecutionBusy, run_model_thread
    try:
        section = await run_model_thread(
            build_validation_fragment, workspace_owner, project_record.project_id)
    except ModelExecutionBusy:
        return HTMLResponse(
            content=(f"<div class=\"v2-trust-note\" data-testid=\"trust-pack-validation-busy\">"
                     f"<span class=\"v2-trust-chip v2-trust-chip--unavailable\">UNAVAILABLE</span> "
                     f"{BUSY_MESSAGE}</div>"),
            status_code=429, headers={"Retry-After": "5", "X-Finco-Model-Busy": "1"},
        )
    except Exception:
        section = {"state": "UNAVAILABLE"}
    return _templates.TemplateResponse(
        request=request,
        name="partials/_trust_validation_body.html",
        context={"trust_validation": section},
    )


# ═══════════════════════════════════════════════════════════════════════════════
# UI-3B: Scenario management routes
# ═══════════════════════════════════════════════════════════════════════════════


def _scenario_list_html(user_id: str, project_id: str, project_code: str, ws, *, context=None) -> str:
    """Render the scenario list partial HTML (used by multiple endpoints)."""
    from app.persistence.scenarios_repository import list_scenarios
    from app.v2.scenario_presentation import build_scenario_presentations
    from app.workbook.runtime_authority import resolve_runtime_freshness
    from app.workbook.workbook_identity import assemble_consistent_for_get
    if context is not None:
        context.require_scope(user_id, project_id)
        context.require_binding(ws, context.project_record, context.runtime_result)
    scenarios = (context.scenarios if context is not None else
                 list_scenarios(user_id=user_id, project_id=project_id, include_archived=False))
    active_id = ws.active_scenario_id if ws else None
    # GF-F04/F05: resolve canonical freshness with the REAL composite hash so
    # that a post-Run CURRENT workspace is not incorrectly forced to STALE.
    # Fail closed (STALE) only when identity assembly genuinely fails.
    try:
        identity = context.identity if context is not None else assemble_consistent_for_get(
            user_id=user_id,
            project_id=project_id,
            workbook_version=WORKBOOK.version,
        )
        current_hash = identity.composite_hash
    except Exception:
        current_hash = None  # fail closed per runtime-authority semantics
    freshness = (context.freshness if context is not None else
                 resolve_runtime_freshness(ws, current_composite_hash=current_hash))
    presentations = build_scenario_presentations(
        scenarios, active_id, global_is_stale=freshness.is_stale)
    from app.persistence.projects_repository import get_project_by_id
    from app.workbook.registry import is_data_center_project_type
    _scen_record = context.project_record if context is not None else get_project_by_id(project_id)
    ctx = {
        "scenarios": presentations,
        "active_scenario_id": active_id,
        "project_code": project_code,
        "ws": ws,
        "is_data_center": is_data_center_project_type(
            getattr(_scen_record, "project_type", "")
        ),
        "is_ev_charging": str(getattr(_scen_record, "project_type", "")).lower() in ("ev charging", "ev_charging"),
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


@router.post("/reference-seed/reset")
async def v2_reference_seed_reset(
    request: Request,
    project: str = Form(...),
    _: None = Depends(require_v2_active),
):
    """Restore overridden CAPEX/OPEX seed lines to canonical unit rates."""
    user = _get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    from app.persistence.projects_repository import resolve_accessible_project
    from app.services.project_library_service import is_protected_reference
    from app.services.reference_seed_service import reset_reference_seeded_lines

    record, owner = resolve_accessible_project(user.user_id, project)
    if record is None:
        return JSONResponse({"error": "Project not found."}, status_code=404)
    if owner != user.user_id or is_protected_reference(record):
        return JSONResponse({"error": "Editable working copy required."}, status_code=403)
    try:
        reset_reference_seeded_lines(user_id=owner, project_code=project)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=409)
    return RedirectResponse(url=f"/v2/workbook?project={project}", status_code=303)


def _scenario_history_unreadable_html() -> str:
    return ('<p class="v2-scenario-empty" data-testid="scenario-history-unreadable">'
            "This scenario's latest saved run could not be read, so it was not "
            "restored and the active scenario is unchanged. Run the scenario "
            "again to create a fresh result.</p>")


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

    from app.persistence.run_history_repository import RunHistoryError

    try:
        selected = select_scenario(user_id=workspace_owner, project_id=project_record.project_id, scenario_id=scenario_id)
    except RunHistoryError:
        # The scenario's newest Run History row is unreadable: selection is
        # refused (nothing was written) and an older run is never substituted.
        return HTMLResponse(
            content=_scenario_history_unreadable_html(),
            status_code=409)
    if not selected:
        return JSONResponse({"error": "Scenario not found or archived."}, status_code=404)
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

    # If the archived scenario is active, switch to Base Case FIRST (a
    # refused/unreadable Base restore must not leave a half-done archive).
    if archived_active:
        from app.persistence.run_history_repository import RunHistoryError

        base = get_base_case_scenario(user_id=workspace_owner, project_id=project_record.project_id)
        if base:
            try:
                select_scenario(user_id=workspace_owner, project_id=project_record.project_id, scenario_id=base.scenario_id)
            except RunHistoryError:
                return HTMLResponse(content=_scenario_history_unreadable_html(), status_code=409)
    archive_scenario(user_id=workspace_owner, scenario_id=scenario_id)
    if archived_active:
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

    if "tariff_eur_mwh" in overrides:
        from app.workbook.scenario_revenue_authority import bind_scenario_tariff
        try:
            bind_scenario_tariff({"project_type": project_record.project_type}, overrides)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=422)
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


# ---------------------------------------------------------------------------
# Run Intelligence V1 — Run History surface (read-only consumers of the
# append-only run-history authority).  No engine execution, no mutation,
# no reconstruction of missing metrics.
# ---------------------------------------------------------------------------

def _run_history_listing_ctx(project_record, ws, pis, *, freshness=None):
    """Shared Run History listing context (workbook GET + OOB + route).

    Read-only composition over the append-only history authority; fails
    closed to a typed error row set on malformed stored payloads.
    """
    from app.persistence.run_history_repository import (
        RunHistoryError,
        get_run_history,
    )
    from app.v2.run_history_projection import (
        HISTORY_LIST_LIMIT,
        build_run_history_rows,
    )
    from app.workbook.runtime_authority import resolve_runtime_freshness

    if freshness is None:
        freshness = resolve_runtime_freshness(ws, current_composite_hash=pis.content_hash)
    # the workspace record carries its owner (canonical history key)
    workspace_owner = getattr(ws, "user_id", None)
    try:
        entries = get_run_history(
            workspace_owner, project_record.project_id,
            limit=HISTORY_LIST_LIMIT)
        rows = build_run_history_rows(
            entries, ws=ws, current_composite_hash=pis.content_hash,
            project_code=project_record.project_code)
        available, error_code = True, ""
    except RunHistoryError as exc:  # malformed stored payload — fail closed
        rows, available, error_code = [], False, str(exc)
    return {
        "rows": rows,
        "available": available,
        "error_code": error_code,
        "failed_note": True,
        "project_code": project_record.project_code,
        "project_editable": not is_protected_reference(project_record),
        "last_run_state": freshness.state.value,
        "last_run_at": _fmt_runtime_at(getattr(ws, "last_runtime_at", None) or ""),
        "last_run_snapshot_short": str(
            getattr(ws, "last_runtime_snapshot_id", "") or "")[:8] or "—",
        "limit": HISTORY_LIST_LIMIT,
    }


@router.get("/workbook/run-history", response_class=HTMLResponse)
async def v2_run_history(
    request: Request,
    project: Optional[str] = None,
):
    """Read-only Run History listing for one project.

    Newest-first immutable successful runs with institutional metadata.
    CURRENT/STALE describe only the canonical Last Run (rendered by the
    workspace header/banner authorities); every listed row is HISTORICAL,
    optionally flagged MATCHES WORKING COPY when its stored identity equals
    the current Working Copy identity.  No engine execution, no mutation.
    """
    user = _get_current_user(request)
    if not user:
        return HTMLResponse(content="<p>Unauthenticated.</p>", status_code=401)
    if not project:
        return HTMLResponse(content="<p>No project specified.</p>", status_code=400)

    from app.persistence.projects_repository import resolve_accessible_project
    from app.persistence.workspace_repository import get_workspace_state
    from app.persistence.run_history_repository import (
        RunHistoryError,
        get_run_history,
    )
    from app.v2.run_history_projection import (
        HISTORY_LIST_LIMIT,
        build_run_history_rows,
    )
    from app.workbook.runtime_authority import resolve_runtime_freshness

    project_record, workspace_owner = resolve_accessible_project(user.user_id, project)
    if project_record is None:
        return HTMLResponse(content="<p>Project not found.</p>", status_code=404)
    ws = get_workspace_state(user_id=workspace_owner, project_id=project_record.project_id)
    if ws is None:
        return HTMLResponse(content="<p>No workspace state.</p>", status_code=404)

    pis = _build_pis_with_composite_identity(ws, project_record, workspace_owner)
    ctx = _run_history_listing_ctx(project_record, ws, pis)
    return _templates.TemplateResponse(
        request=request, name="partials/sheet_run_history.html", context=ctx)


@router.get("/workbook/run-history/detail", response_class=HTMLResponse)
async def v2_run_history_detail(
    request: Request,
    project: Optional[str] = None,
    history_id: Optional[str] = None,
):
    """Read-only historical run detail: identity, canonical KPIs, integrity
    evidence.  No restore / rerun / mutation functionality exists."""
    user = _get_current_user(request)
    if not user:
        return HTMLResponse(content="<p>Unauthenticated.</p>", status_code=401)
    if not project or not history_id:
        return HTMLResponse(
            content="<p>Project and history_id required.</p>", status_code=400)

    from app.persistence.projects_repository import resolve_accessible_project
    from app.persistence.run_history_repository import (
        RunHistoryError,
        get_run_history_entry,
    )
    from app.v2.run_history_projection import run_history_metrics

    project_record, workspace_owner = resolve_accessible_project(user.user_id, project)
    if project_record is None:
        return HTMLResponse(content="<p>Project not found.</p>", status_code=404)

    try:
        entry = get_run_history_entry(
            workspace_owner, project_record.project_id, history_id)
    except RunHistoryError as exc:  # malformed stored payload — fail closed
        return HTMLResponse(
            content=f"<p role=\"alert\">RUN_HISTORY_PAYLOAD_MALFORMED: {exc}</p>",
            status_code=422)
    if entry is None:  # unknown or foreign id — fail closed
        return HTMLResponse(
            content="<p>Run history entry not found.</p>", status_code=404)

    integrity = getattr(entry, "integrity_evidence", None) or {}
    identity = getattr(entry, "last_runtime_identity", None) or {}
    ctx = {
        "entry": entry,
        "metrics": run_history_metrics(entry),
        "ran_at_display": str(getattr(entry, "ran_at", "") or "")[:16].replace("T", " "),
        "scenario_name": getattr(entry, "active_scenario_name", None) or "Base",
        "origin": str(getattr(entry, "runtime_origin", "") or "—"),
        "engine_version": str(getattr(entry, "engine_version", "") or "—"),
        "workbook_version": str(getattr(entry, "workbook_version", "") or "—"),
        "snapshot_short": str(getattr(entry, "runtime_snapshot_id", "") or "")[:8],
        "composite_short": str(getattr(entry, "composite_hash", "") or "")[:8],
        "integrity_items": (
            sorted(integrity.items()) if isinstance(integrity, dict) else []),
        "project_code": project_record.project_code,
    }
    return _templates.TemplateResponse(
        request=request, name="partials/run_history_detail.html", context=ctx)


@router.get("/workbook/run-history/compare", response_class=HTMLResponse)
async def v2_run_history_compare(
    request: Request,
    project: Optional[str] = None,
    history_id: Optional[str] = None,
):
    """Canonical Last Run vs one selected immutable historical run.

    Read-only data-source substitution over the existing compare machinery —
    no financial recomputation, no engine execution, UNAVAILABLE stays
    unavailable.  If the Last Run is STALE relative to the Working Copy that
    is displayed honestly: the comparison compares persisted runs.
    """
    user = _get_current_user(request)
    if not user:
        return HTMLResponse(content="<p>Unauthenticated.</p>", status_code=401)
    if not project or not history_id:
        return HTMLResponse(
            content="<p>Project and history_id required.</p>", status_code=400)

    from app.persistence.projects_repository import resolve_accessible_project
    from app.persistence.workspace_repository import get_workspace_state
    from app.persistence.run_history_repository import (
        RunHistoryError,
        get_run_history_entry,
    )
    from app.workbook.runtime_authority import resolve_runtime_freshness
    from app.v2.run_history_projection import (
        _enriched_kpis,
        build_run_compare,
    )

    project_record, workspace_owner = resolve_accessible_project(user.user_id, project)
    if project_record is None:
        return HTMLResponse(content="<p>Project not found.</p>", status_code=404)
    ws = get_workspace_state(user_id=workspace_owner, project_id=project_record.project_id)
    if ws is None:
        return HTMLResponse(content="<p>No workspace state.</p>", status_code=404)

    pis = _build_pis_with_composite_identity(ws, project_record, workspace_owner)
    freshness = resolve_runtime_freshness(ws, current_composite_hash=pis.content_hash)

    try:
        entry = get_run_history_entry(
            workspace_owner, project_record.project_id, history_id)
    except RunHistoryError as exc:
        return HTMLResponse(
            content=f"<p role=\"alert\">RUN_HISTORY_PAYLOAD_MALFORMED: {exc}</p>",
            status_code=422)
    if entry is None:
        return HTMLResponse(
            content="<p>Run history entry not found.</p>", status_code=404)

    class _LastRunView:
        """Scheduling-source view over the workspace's persisted Last Run."""
        runtime_summary = dict(getattr(ws, "last_runtime_summary", None) or {})
        debt_schedule = getattr(ws, "last_debt_schedule", None) or {}
        sponsor_schedule = getattr(ws, "last_sponsor_schedule", None) or {}

    compare = build_run_compare(
        last_run_kpis=_enriched_kpis(_LastRunView()),
        last_run_ran_at=_fmt_runtime_at(getattr(ws, "last_runtime_at", None) or ""),
        last_run_is_stale=freshness.is_stale,
        history_entry=entry,
    )
    matches = bool(
        entry.composite_hash and pis.content_hash
        and str(entry.composite_hash) == str(pis.content_hash)
    )
    ctx = {
        "compare": compare,
        "history_id": entry.history_id,
        "project_code": project_record.project_code,
        "matches_working_copy": matches,
        "last_run_state": freshness.state.value,
    }
    return _templates.TemplateResponse(
        request=request, name="partials/run_history_compare.html", context=ctx)


# ---------------------------------------------------------------------------
# Decision Support V1 — expanded same-project run compare (Run A vs Run B)
# and cross-project canonical Last Run comparison.  READ ONLY over
# persisted successful canonical runs; no engine execution, no mutation.
# ---------------------------------------------------------------------------

def _run_identity_of(entry):
    return getattr(entry, "last_runtime_identity", None) or {}


def _run_side_view(entry):
    """One comparison side from an immutable history entry."""
    from app.v2.run_history_projection import _enriched_kpis

    class _EntryView:
        runtime_summary = dict(getattr(entry, "runtime_summary", None) or {})
        debt_schedule = getattr(entry, "debt_schedule", None) or {}
        sponsor_schedule = getattr(entry, "sponsor_schedule", None) or {}

    return {
        "kpis": _enriched_kpis(_EntryView()),
        "ran_at": str(getattr(entry, "ran_at", "") or "")[:16].replace("T", " "),
        "scenario": getattr(entry, "active_scenario_name", None) or "Base",
        "snapshot": str(getattr(entry, "runtime_snapshot_id", "") or "")[:8],
        "identity": _run_identity_of(entry),
        "sponsor_summary": (getattr(entry, "sponsor_schedule", None) or {}).get("summary", {}),
        "debt_summary": (getattr(entry, "debt_schedule", None) or {}).get("summary", {}),
    }


def _last_run_side(ws, freshness):
    """The canonical Last Run side from the workspace record.

    Correction A5: the scenario label comes from the PERSISTED run-bound
    identity (``last_runtime_identity["scenario_name"]``) — never from the
    workspace's current ``active_scenario_name``, which describes the later,
    mutable Working Copy selection.  Legacy-safe fallback only when the
    persisted identity genuinely lacks the field.
    """
    from app.v2.run_history_projection import _enriched_kpis

    identity = getattr(ws, "last_runtime_identity", None) or {}
    persisted_scenario = identity.get("scenario_name")
    class _LastView:
        runtime_summary = dict(getattr(ws, "last_runtime_summary", None) or {})
        debt_schedule = getattr(ws, "last_debt_schedule", None) or {}
        sponsor_schedule = getattr(ws, "last_sponsor_schedule", None) or {}

    return {
        "kpis": _enriched_kpis(_LastView()),
        "ran_at": _fmt_runtime_at(getattr(ws, "last_runtime_at", None) or ""),
        "scenario": persisted_scenario or getattr(
            ws, "active_scenario_name", None) or "Base",
        "snapshot": str(getattr(ws, "last_runtime_snapshot_id", "") or "")[:8],
        "identity": identity,
        "sponsor_summary": (getattr(ws, "last_sponsor_schedule", None) or {}).get("summary", {}),
        "debt_summary": (getattr(ws, "last_debt_schedule", None) or {}).get("summary", {}),
        "state": freshness.state.value,
    }


@router.get("/workbook/run-compare", response_class=HTMLResponse)
async def v2_run_compare_expanded(
    request: Request,
    project: Optional[str] = None,
    run_a: Optional[str] = None,      # "last" (default) or a history_id
    run_b: Optional[str] = None,      # a history_id (required)
):
    """Expanded same-project run comparison (Decision Support V1).

    Default: canonical Last Run (A) vs a selected immutable historical
    successful run (B).  Run A may also be an older history_id
    (historical-vs-historical).  Sections: variance over persisted canonical
    metrics, changed assumptions from the persisted run-bound input
    identities, and a deterministic factual Drivers-of-Change summary.
    Labels follow Run Intelligence semantics: only the canonical Last Run is
    CURRENT/STALE; every selected historical run stays HISTORICAL.
    No engine execution, no mutation.
    """
    user = _get_current_user(request)
    if not user:
        return HTMLResponse(content="<p>Unauthenticated.</p>", status_code=401)
    if not project or not run_b:
        return HTMLResponse(
            content="<p>Project and run_b required.</p>", status_code=400)

    from app.persistence.projects_repository import resolve_accessible_project
    from app.persistence.workspace_repository import get_workspace_state
    from app.persistence.run_history_repository import (
        RunHistoryError,
        get_run_history_entry,
    )
    from app.workbook.runtime_authority import resolve_runtime_freshness
    from app.v2.decision_support_projection import (
        build_assumption_diff,
        build_drivers_of_change,
        build_run_variance,
        run_metric_view,
    )

    project_record, workspace_owner = resolve_accessible_project(user.user_id, project)
    if project_record is None:
        return HTMLResponse(content="<p>Project not found.</p>", status_code=404)
    ws = get_workspace_state(user_id=workspace_owner, project_id=project_record.project_id)
    if ws is None:
        return HTMLResponse(content="<p>No workspace state.</p>", status_code=404)

    pis = _build_pis_with_composite_identity(ws, project_record, workspace_owner)
    freshness = resolve_runtime_freshness(ws, current_composite_hash=pis.content_hash)

    def _entry_or_404(history_id):
        try:
            return get_run_history_entry(
                workspace_owner, project_record.project_id, history_id)
        except RunHistoryError as exc:  # malformed payload — fail closed
            return ("error", f"RUN_HISTORY_PAYLOAD_MALFORMED: {exc}")
        # None handled by caller (404)

    entry_a = None
    if run_a and run_a != "last":
        got = _entry_or_404(run_a)
        if isinstance(got, tuple):
            return HTMLResponse(content=f"<p role=\"alert\">{got[1]}</p>", status_code=422)
        if got is None:
            return HTMLResponse(content="<p>Run A history entry not found.</p>", status_code=404)
        entry_a = got
    got_b = _entry_or_404(run_b)
    if isinstance(got_b, tuple):
        return HTMLResponse(content=f"<p role=\"alert\">{got_b[1]}</p>", status_code=422)
    if got_b is None:
        return HTMLResponse(content="<p>Run B history entry not found.</p>", status_code=404)
    entry_b = got_b

    side_a_view = (_run_side_view(entry_a) if entry_a is not None
                   else _last_run_side(ws, freshness))
    side_a_label = ("Last Run" if entry_a is None
                    else f"Historical Run · {side_a_view['ran_at']}")
    side_a_is_last = entry_a is None
    side_b_view = _run_side_view(entry_b)

    view_a = run_metric_view(side_a_view["kpis"], side_a_view["sponsor_summary"],
                             side_a_view["debt_summary"])
    view_b = run_metric_view(side_b_view["kpis"], side_b_view["sponsor_summary"],
                             side_b_view["debt_summary"])
    sections = build_run_variance(view_a, view_b)
    assumptions = build_assumption_diff(
        side_a_view["identity"], side_b_view["identity"])
    drivers = build_drivers_of_change(assumptions, sections)

    ctx = {
        "project_code": project_record.project_code,
        "project_name": project_record.project_name,
        "side_a": {"label": side_a_label, "ran_at": side_a_view["ran_at"],
                   "scenario": side_a_view["scenario"],
                   "snapshot": side_a_view["snapshot"],
                   "is_last": side_a_is_last,
                   "state": (freshness.state.value if side_a_is_last
                             else "HISTORICAL")},
        "side_b": {"label": f"Historical Run · {side_b_view['ran_at']}",
                   "ran_at": side_b_view["ran_at"],
                   "scenario": side_b_view["scenario"],
                   "snapshot": side_b_view["snapshot"],
                   "state": "HISTORICAL",
                   "matches_working_copy": bool(
                       entry_b.composite_hash and pis.content_hash
                       and str(entry_b.composite_hash) == str(pis.content_hash))},
        "sections": sections,
        "assumptions": assumptions,
        "drivers": drivers,
        "back_url": f"/v2/workbook/run-history?project={project_record.project_code}",
        "workspace_url": f"/v2/workbook?project={project_record.project_code}",
    }
    return _templates.TemplateResponse(
        request=request, name="partials/run_compare_expanded.html", context=ctx)


def _ds_country(record) -> str:
    base = getattr(record, "baseline_snapshot", None) or {}
    return str(base.get("country_iso", "") or base.get("country", "") or "")


def _ds_capacity(record) -> str:
    """Capacity display with explicit None semantics — numeric zero is a
    valid persisted value, never silently treated as missing (Correction
    §4 of DS post-merge review)."""
    base = getattr(record, "baseline_snapshot", None) or {}
    cap = base.get("capacity_mw")
    if cap is None:
        return ""
    try:
        return f"{float(cap):.1f} MW"
    except (TypeError, ValueError):
        return ""


def _ds_sort_num(display: str) -> float:
    """Deterministic sort key from a formatted display value ('—' sorts last)."""
    try:
        return float(str(display).replace(",", "").rstrip("%x"))
    except (ValueError, TypeError):
        return float("-inf")


def _ds_picker_projects(user_id: str) -> list[dict]:
    """Bounded list of the user's own projects for the Compare picker."""
    from app.persistence.projects_repository import list_projects

    try:
        records = list_projects(user_id)
    except Exception:  # picker is a convenience; manual tokens still work
        return []
    return [{"code": r.project_code, "name": r.project_name,
             "technology": r.project_type or ""} for r in records[:100]]


def _ds_meta_label(project_record, attr: str, normalizer) -> str:
    """Stage / perspective as stored (normalised); unset is shown as unset, never inferred."""
    try:
        return normalizer(getattr(project_record, attr, None)) or ""
    except ValueError:
        return ""


def _ds_run_state(ws, project_record, workspace_owner: str) -> str:
    """CURRENT / STALE / NOT_RUN from the canonical freshness authority; UNKNOWN when it
    cannot be determined reliably (never asserted).  Read-only; no engine."""
    if ws is None:
        return "UNKNOWN"
    try:
        pis = _build_pis_with_composite_identity(ws, project_record, workspace_owner)
        return _runtime_freshness(ws, pis).state.value
    except Exception:
        return "UNKNOWN"


@router.get("/compare-projects", response_class=HTMLResponse)
async def compare_projects_page(
    request: Request,
    projects: Optional[str] = None,
    sort: Optional[str] = None,
    technology: Optional[str] = None,
    pick: list[str] = Query(default=[]),
):
    """Cross-project canonical Last Run comparison (Decision Support V1).

    Read-only comparison of the LATEST SUCCESSFUL canonical Last Run for up
    to five selected projects.  A project without a successful canonical Run
    is shown as unavailable — never calculated, never sourced from the
    Working Copy.  No engine execution on this surface.
    """
    user = _get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    from app.persistence.projects_repository import resolve_accessible_project
    from app.persistence.workspace_repository import get_workspace_state
    from app.model_v2.project_metadata import perspective_value, stage_value
    from app.v2.decision_support_projection import (
        CROSS_PROJECT_MAX,
        build_cross_project_rows,
    )

    # Correction A4/A5(post-merge): normalize selection — strip whitespace,
    # drop empties, de-duplicate preserving first-seen order over ALL raw
    # tokens; the CROSS_PROJECT_MAX cap applies AFTER accessibility
    # resolution, so garbage prefixes (unknown/inaccessible codes) never
    # crowd out a valid later selection.  Duplicates never consume a second
    # column.
    raw_codes: list[str] = []
    for raw_code in [*(projects or "").split(","), *pick]:
        code = raw_code.strip()
        if code and code not in raw_codes:
            raw_codes.append(code)

    # Correction A3: resolve each candidate code DIRECTLY through the
    # existing authorization authority (bounded: raw_codes length is the
    # only loop bound, resolved rows capped at 5) — no fixed-size page
    # scan.  Bootstrap authorities are NEVER invoked: a GET comparison
    # render performs zero database writes.
    payloads: list[dict] = []
    resolved_count = 0
    for code in raw_codes:
        if resolved_count >= CROSS_PROJECT_MAX:
            break
        project_record, workspace_owner = resolve_accessible_project(
            user.user_id, code)
        if project_record is None:
            continue  # unknown / inaccessible code stays unavailable
        resolved_count += 1
        try:
            ws = get_workspace_state(workspace_owner, project_record.project_id)
        except Exception:  # evidence read failure == unavailable
            ws = None
        ran_at = getattr(ws, "last_runtime_at", None) if ws else None
        _base = getattr(project_record, "baseline_snapshot", None) or {}
        _cap_raw = _base.get("capacity_mw")
        try:
            _cap_num = float(_cap_raw) if _cap_raw else None
        except (TypeError, ValueError):
            _cap_num = None
        payloads.append({
            "project_code": project_record.project_code,
            "project_name": project_record.project_name,
            "technology": project_record.project_type or "",
            "country": _ds_country(project_record),
            "capacity_display": _ds_capacity(project_record),
            "capacity_mw": _cap_num,
            "stage": _ds_meta_label(project_record, "project_stage", stage_value),
            "perspective": _ds_meta_label(project_record, "model_perspective", perspective_value),
            "run_state": _ds_run_state(ws, project_record, workspace_owner),
            "run_identity": str(getattr(ws, "last_runtime_composite_hash", "") or "")[:8] if ws else "",
            "runnable": bool(ran_at is not None),
            "ran_at_display": (str(ran_at)[:16].replace("T", " ")
                               if ran_at else ""),
            "runtime_summary": (getattr(ws, "last_runtime_summary", None) or {}) if ws else {},
            "sponsor_summary": ((getattr(ws, "last_sponsor_schedule", None) or {})
                                .get("summary", {})) if ws else {},
            "debt_summary": ((getattr(ws, "last_debt_schedule", None) or {})
                             .get("summary", {})) if ws else {},
        })

    rows = build_cross_project_rows(payloads)
    if sort:
        from app.v2.decision_support_projection import sort_cross_project_rows
        rows = sort_cross_project_rows(
            rows, sort, descending=(sort not in ("total_capex_keur", "total_tax_keur")))
    techs = sorted({r.technology for r in rows if r.technology != "—"})
    if technology:
        rows = [r for r in rows if r.technology == technology]

    from main_web import templates as _main_templates

    ctx = {
        "rows": rows,
        "projects": [r.project_code for r in rows],
        "selected": [r.project_code for r in rows],
        "sort": sort or "",
        "technology_filter": technology or "",
        "technologies": techs,
        "max_projects": CROSS_PROJECT_MAX,
        "user": user,
        # Picker options: the user's own accessible (non-archived) projects.
        # Selection still resolves through resolve_accessible_project; no engine.
        "picker_projects": _ds_picker_projects(user.user_id),
        "unresolved_tokens": [c for c in raw_codes if c not in
                              {p["project_code"] for p in payloads}],
    }
    # the page extends base.html — render from the ROOT template directory
    return _main_templates.TemplateResponse(
        request=request, name="compare_projects.html", context=ctx)


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

    from app.v2.post_run_context import PostRunRequestContext, PostRunContextChanged
    from app.workbook.workbook_identity import WorkbookIdentityError
    try:
        read_context = PostRunRequestContext.capture(owner_id=workspace_owner, project_id=project_record.project_id)
    except (PostRunContextChanged, WorkbookIdentityError, PermissionError):
        return HTMLResponse("Scenario comparison unavailable: coherent workspace evidence could not be read.", status_code=409)
    ws = read_context.workspace
    all_scenarios = [sc for sc in read_context.scenarios if not sc.archived]
    by_id = {sc.scenario_id: sc for sc in all_scenarios}
    selected_ids = list(dict.fromkeys(sid for sid in [s1, s2, s3] if sid))
    selected_scenarios = [by_id[sid] for sid in selected_ids if sid in by_id]

    # The selected Base Case is always the comparison reference. When it is
    # absent the first selected alternative is labelled explicitly as reference.
    selected_scenarios.sort(key=lambda sc: not sc.is_base_case)
    selected_ids = [sc.scenario_id for sc in selected_scenarios]
    from app.v2.scenario_presentation import build_scenario_presentations
    global_stale = read_context.freshness.is_stale
    states = {sc.scenario_id: sc for sc in build_scenario_presentations(
        selected_scenarios, ws.active_scenario_id if ws else None, global_is_stale=global_stale)}

    projections = []
    for sc in selected_scenarios:
        rs = sc.last_run_summary or {}
        ran_at_str = (rs.get("ran_at") or "") if rs else ""
        has_result = bool(rs and rs.get("kpis"))
        if not has_result:
            is_stale = False  # will show as NOT_RUN
        else:
            is_stale = states[sc.scenario_id].is_stale
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
    from app.v2.decision_workspace import scenario_assumptions

    ctx = {
        "project_code": project,
        "project_name": project_record.project_name or project,
        "all_scenarios": all_scenarios,
        "selected_scenarios": selected_scenarios,
        "selected_ids": selected_ids,
        "projections": projections,
        "compare_rows": rows,
        "compare_assumptions": scenario_assumptions(selected_scenarios),
        "request": request,
    }
    html = _templates.get_template("partials/sheet_compare.html").render(ctx)
    try:
        read_context.validate_current()
    except (PostRunContextChanged, WorkbookIdentityError, PermissionError):
        return HTMLResponse("Scenario comparison unavailable: workspace changed during assembly. Reopen Compare.",
                            status_code=409, headers={"Cache-Control": "no-store"})
    return HTMLResponse(content=html, headers={"Cache-Control": "no-store"})


@router.get("/workbook/decision/{surface}", response_class=HTMLResponse)
async def v2_decision_sheet(request: Request, surface: str, project: str):
    """Refresh analysis controls from one authorized coherent read snapshot."""
    if surface not in ("sensitivity", "goal-seek"):
        return HTMLResponse("Decision surface not found.", status_code=404)
    user = _get_current_user(request)
    if not user:
        return HTMLResponse("Unauthenticated.", status_code=401)
    from app.persistence.projects_repository import resolve_accessible_project
    from app.v2.post_run_context import PostRunRequestContext, PostRunContextChanged
    from app.workbook.workbook_identity import WorkbookIdentityError
    record, owner = resolve_accessible_project(user.user_id, project)
    if record is None:
        return HTMLResponse("Project not found.", status_code=404)
    try:
        context = PostRunRequestContext.capture(owner_id=owner, project_id=record.project_id)
        ctx = _base_sheet_ctx(request, context.inputs, context.workspace, context.project_record,
                              project, freshness=context.freshness)
        ctx["scenarios"] = context.scenarios
        ctx["active_scenario_id"] = context.workspace.active_scenario_id
        ctx["revenue_fields"] = _build_sheet_fields("revenue", context.inputs)
        filename = "sheet_sensitivity.html" if surface == "sensitivity" else "sheet_goal_seek.html"
        html = _templates.get_template("partials/" + filename).render(ctx)
        context.validate_current()
    except (PostRunContextChanged, WorkbookIdentityError, PermissionError):
        return HTMLResponse("Analysis controls unavailable: workspace changed. Reopen this tab to refresh.",
                            status_code=409, headers={"Cache-Control": "no-store"})
    return HTMLResponse(html, headers={"Cache-Control": "no-store"})


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
    _dc_template_src = str(getattr(project_record, "template_source", "") or "").strip().lower()
    _is_dc_sens = (
        project_type_raw in ("data center", "data_center", "datacenter")
        or _dc_template_src == "generic_data_center_reference"
    )
    if not _is_dc_sens and project_type_raw not in ("solar", "wind"):
        return HTMLResponse(content=f"<p>Unsupported project type: {project_record.project_type!r}.</p>", status_code=409)
    if _is_dc_sens:
        runtime_key = "Generic Data Center Reference"
    else:
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
            "dc_excluded": True,  # renewable-only driver
        },
        # Data Center-native drivers
        "service_price": {
            "label": "Service Price (EUR/kW/month)",
            "field_id": "revenue.data_center.service_price",
            "snapshot_key": "dc_service_price_eur_kw_month",
            "steps": [-0.20, -0.10, 0.0, +0.10, +0.20],
            "step_labels": ["-20%", "-10%", "Base", "+10%", "+20%"],
            "mode": "pct_multiplier",
            "dc_only": True,
        },
        "dc_occupancy": {
            "label": "Stabilised Occupancy",
            "field_id": "revenue.data_center.occupancy_stabilized",
            "snapshot_key": "dc_occupancy_stabilized",
            # ±10 pp absolute — stored as percent (85 = 85%), so steps are in pp units
            "steps": [-10.0, -5.0, 0.0, +5.0, +10.0],
            "step_labels": ["-10 pp", "-5 pp", "Base", "+5 pp", "+10 pp"],
            "mode": "absolute_add",
            "dc_only": True,
        },
        # Correction B: IT MW / PUE / electricity price are canonical BOUND
        # source drivers — each modifies ONE source input and the existing DC
        # runtime adapter recomputes dependent revenue/OPEX.
        "dc_it_mw": {
            "label": "IT Load Capacity",
            "field_id": "project_setup.technical.capacity_mw",
            "snapshot_key": "capacity_mw",
            "steps": [-0.20, -0.10, 0.0, +0.10, +0.20],
            "step_labels": ["-20%", "-10%", "Base", "+10%", "+20%"],
            "mode": "pct_multiplier",
            "dc_only": True,
        },
        "dc_pue": {
            "label": "PUE",
            "field_id": "revenue.data_center.pue",
            "snapshot_key": "dc_pue",
            "steps": [-0.10, -0.05, 0.0, +0.05, +0.10],
            "step_labels": ["-10%", "-5%", "Base", "+5%", "+10%"],
            "mode": "pct_multiplier",
            "dc_only": True,
        },
        "dc_electricity_price": {
            "label": "Electricity Price",
            "field_id": "revenue.data_center.electricity_price",
            "snapshot_key": "dc_electricity_price_eur_mwh",
            "steps": [-0.20, -0.10, 0.0, +0.10, +0.20],
            "step_labels": ["-20%", "-10%", "Base", "+10%", "+20%"],
            "mode": "pct_multiplier",
            "dc_only": True,
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
            "dc_excluded": True,  # renewable-only driver
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

    _spec_candidate = DRIVER_SPECS[driver]
    if _is_dc_sens and _spec_candidate.get("dc_excluded"):
        return HTMLResponse(
            content=f"<p>Driver {driver!r} is not available for Data Center projects.</p>",
            status_code=422,
        )
    if not _is_dc_sens and _spec_candidate.get("dc_only"):
        return HTMLResponse(
            content=f"<p>Driver {driver!r} is only available for Data Center projects.</p>",
            status_code=422,
        )

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
        try:
            _scenario_rec, _resolved_snap, _warn = _resolve_snap(
                workspace_owner, project_record.project_id, scenario_id
            )
        except ValueError as exc:
            from html import escape
            return HTMLResponse(f"<p>Scenario input unavailable: {escape(str(exc))}</p>", status_code=422)
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

            from app.workbook.bankability_config import SNAPSHOT_KEY, assert_materialized_fee_authority
            assert_materialized_fee_authority(pi_override, pis_sens.snapshot_origin.get(SNAPSHOT_KEY))
            from app.workbook.multisenior_config import SNAPSHOT_KEY as f3_key, apply_state
            f3_scope = "base" if not scenario_id or _scenario_rec.is_base_case else scenario_id
            pi_override = apply_state(pi_override, pis_sens.snapshot_origin.get(f3_key), f3_scope,
                bankability_raw=pis_sens.snapshot_origin.get(SNAPSHOT_KEY))

            # P0-A: do not run the engine inline. Queue the point; the whole grid executes as ONE
            # admitted, ordered task in the model executor (see below).
            results.append({"label": step_label, "status": "PENDING", "_pi": pi_override,
                            "input_value": new_val if new_val is not None else base_val})

        except Exception as exc:
            _logging.getLogger(__name__).exception(
                "sensitivity_run: driver=%s step=%s project=%s", driver, step, project
            )
            results.append({"label": step_label, "status": "FAILED", "error": str(exc)[:120], "kpis": {}})

    # ── P0-A: execute the queued points as one bounded task, preserving step order ────────── #
    from app.runtime.model_execution import (
        BUSY_MESSAGE as _BUSY_MESSAGE, ModelExecutionBusy as _Busy, run_model_process as _run_proc,
    )
    from app.services.sensitivity_execution import (
        run_sensitivity_points as _run_points, sensitivity_grid_size_error as _grid_error,
    )
    _pending = [r for r in results if r.get("status") == "PENDING"]
    _size_error = _grid_error(len(_pending))
    if _size_error:
        return HTMLResponse(content=f"<p>{_size_error}</p>", status_code=422)
    if _pending:
        try:
            _outputs = await _run_proc(_run_points, runtime_key, [r["_pi"] for r in _pending])
        except _Busy:
            return HTMLResponse(
                content=f"<p>{_BUSY_MESSAGE}</p>", status_code=429,
                headers={"Retry-After": "5", "X-Finco-Model-Busy": "1"},
            )
        except Exception:
            _logging.getLogger(__name__).exception(
                "sensitivity_run: executor failure driver=%s project=%s", driver, project)
            _outputs = [{"error": "Calculation could not be completed."}] * len(_pending)
        for _r, _out in zip(_pending, _outputs):
            _r.pop("_pi", None)
            if "error" in _out:
                _r.update(status="FAILED", error=_out["error"], kpis={})
                continue
            kpis_raw = _out.get("kpis", {})
            step_metrics = {}
            for _key, _label, _unit, _fmt_code, _src in KPI_CATALOG:
                step_metrics[_key] = build_output_metric_projection(
                    _key, kpis_raw.get(_key), freshness="current"
                )
            _r.update(
                status="OK",
                metrics=step_metrics,
                kpis={k: m.display_value for k, m in step_metrics.items()},
                kpis_raw={k: m.raw_value for k, m in step_metrics.items()},
            )

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
        "is_data_center": _is_dc_sens,
        "request": request,
    }
    from app.v2.decision_workspace import sensitivity_presentation
    ctx["sensitivity_view"] = sensitivity_presentation(results, driver, spec["label"])
    ctx["sensitivity_input"] = {"field": field_id, "value": base_val, "mode": spec["mode"]}
    return HTMLResponse(content=_templates.get_template("partials/sheet_sensitivity_results.html").render(ctx))



# ══════════════════════════════════════════════════════════════════════════════
# Goal Seek / Tender V1 — canonical decision support
#
# One calculation contract: solve the canonical scalar revenue-price input
# (PPA base tariff) for a target canonical return metric, using the SAME
# canonical run authority as the Workbook. Candidate evaluation is
# persistence-free (existing sensitivity candidate authority); only the
# explicit "Apply to Working Copy" action writes anything, through the
# canonical field-save authority (WorkbookUpdateService.apply_draft_update),
# which triggers the normal STALE semantics. A Goal Seek candidate run is
# never presented as the canonical Last Run.
# "Tender" is a UX label for the same solve (target-return pricing).
# ══════════════════════════════════════════════════════════════════════════════


def _render_goal_seek_results(ctx: dict) -> HTMLResponse:
    from app.v2.decision_workspace import tender_presentation
    ctx["tender"] = tender_presentation(ctx.get("result"))
    return HTMLResponse(
        content=_templates.get_template("partials/goal_seek_results.html").render(ctx))


def _goal_seek_resolve_tariff_field(variable, pis_draft) -> tuple[str, object]:
    """Server-side resolution of the ONE permitted Goal Seek apply field and the
    current tariff raw value.

    The apply field is ALWAYS the canonical solve-variable field: it is the
    editable, BOUND field, and the canonical key wins over the legacy snapshot
    key in canonical input composition. The legacy key is read-only evidence
    for the STARTING value only (projects seeded before the canonical key
    existed carry only ``tariff_eur_mwh``); the legacy field is PARTIAL /
    non-editable and can never be an apply target."""
    snapshot_origin = dict(getattr(pis_draft, "snapshot_origin", {}) or {})
    raw_current = snapshot_origin.get("rev_ppa_base_tariff")
    if raw_current is None and variable.fallback_field_id:
        raw_current = snapshot_origin.get("tariff_eur_mwh")
    return variable.field_id, raw_current


def _goal_seek_apply_ctx(*, project: str, field_id: str, solved_display: str,
                         content_hash: str, workbook_version: str,
                         target_metric: str, target_value: str) -> dict:
    return {
        "apply_project": project,
        "apply_field_id": field_id,
        "apply_value": solved_display,
        "apply_content_hash": content_hash,
        "apply_workbook_version": workbook_version,
        "target_metric": target_metric,
        "target_value": target_value,
    }


@router.post("/workbook/goal-seek/run", response_class=HTMLResponse)
async def v2_workbook_goal_seek_run(
    request: Request,
    project: str = Form(...),
    target_metric: str = Form(...),
    target_value: str = Form(...),
    _: None = Depends(require_v2_active),
):
    """Solve the canonical tariff for a target return metric.

    Candidate evaluations reuse the persistence-free sensitivity candidate
    authority; nothing is persisted by this route. The returned partial
    carries the typed result and (when SOLVED) the Apply-to-Working-Copy
    action wired to the canonical field-save authority.
    """
    import math

    from app.persistence.projects_repository import resolve_accessible_project
    from app.persistence.workspace_repository import get_workspace_state
    from app.services.project_library_service import is_protected_reference

    user = _get_current_user(request)
    if not user:
        return HTMLResponse(content="<p>Unauthenticated.</p>", status_code=401)

    from dataclasses import replace as dc_replace

    from app.services.goal_seek import (
        GoalSeekModelRunError,
        GoalSeekStatus,
        make_canonical_evaluator,
        resolve_metric,
        resolve_solve_variable,
        solve_tariff_for_metric,
    )

    def _fail(status_code: int, message: str,
              status: str = GoalSeekStatus.INVALID_REQUEST.value) -> HTMLResponse:
        return _render_goal_seek_results({
            "result": {
                "status": status,
                "target_metric_label": str(target_metric),
                "message": message,
            },
            "apply": None,
            "request": request,
        }) if status_code == 200 else HTMLResponse(
            content=f"<p>{message}</p>", status_code=status_code)

    project_record, workspace_owner = resolve_accessible_project(user.user_id, project)
    if project_record is None:
        return HTMLResponse(content=f"<p>Project {project!r} not found.</p>",
                            status_code=404)
    if is_protected_reference(project_record):
        return HTMLResponse(
            content="<p>This is a protected reference model. Create a working copy to edit it.</p>",
            status_code=409)
    ws = get_workspace_state(user_id=workspace_owner, project_id=project_record.project_id)
    if ws is None:
        return HTMLResponse(content="<p>Workspace not found.</p>", status_code=404)

    # ── Solve-variable resolution (typed, fail closed) ────────────────────── #
    project_type_raw = (project_record.project_type or "").strip().lower()
    if project_type_raw == "solar":
        runtime_project_key = "Solar"
    elif project_type_raw == "wind":
        runtime_project_key = "Wind"
    elif project_type_raw in ("data center", "data_center", "datacenter"):
        runtime_project_key = "Generic Data Center Reference"
    elif project_type_raw in ("ev charging", "ev_charging"):
        runtime_project_key = "Generic EV Charging Hub Reference"
    else:
        runtime_project_key = None
    variable = resolve_solve_variable(project_type_raw)
    if runtime_project_key is None or variable is None:
        return _render_goal_seek_results({
            "result": {
                "status": GoalSeekStatus.INVALID_REQUEST.value,
                "target_metric_label": str(target_metric),
                "message": (f"Project type {project_type_raw!r} has no "
                            "supported scalar revenue-price solve variable in "
                            "V1 (supported: solar, wind)."),
            },
            "apply": None,
            "request": request,
        })

    metric = resolve_metric(target_metric)
    if metric is None:
        return _render_goal_seek_results({
            "result": {
                "status": GoalSeekStatus.INVALID_REQUEST.value,
                "target_metric_label": str(target_metric),
                "message": "Unknown target metric. Supported: Project IRR, "
                           "Pure Equity IRR, Total Sponsor IRR.",
            },
            "apply": None,
            "request": request,
        })
    try:
        target_pct = float(str(target_value).strip().replace("%", ""))
        if not math.isfinite(target_pct):
            raise ValueError("not finite")
    except (TypeError, ValueError):
        return _render_goal_seek_results({
            "result": {
                "status": GoalSeekStatus.INVALID_REQUEST.value,
                "target_metric_label": metric.label,
                "message": f"Target {target_value!r} is not a valid number.",
            },
            "apply": None,
            "request": request,
        })
    target_fraction = target_pct / 100.0

    # ── Canonical input construction (mirrors the canonical Run path) ─────── #
    pis_draft = WorkbookService.build_draft_input_set_from_workspace(ws)
    try:
        override = WorkbookService.to_projectinputs(pis_draft)
    except Exception as build_exc:
        import logging
        logging.getLogger(__name__).exception(
            "goal-seek: build_project_inputs failed project=%s", project)
        return _render_goal_seek_results({
            "result": {
                "status": GoalSeekStatus.MODEL_RUN_FAILED.value,
                "target_metric_label": metric.label,
                "message": ("Could not build project inputs — "
                            f"{build_exc}"),
            },
            "apply": None,
            "request": request,
        })

    _scenario_overrides_for_fold = None
    if ws.active_scenario_id:
        from app.persistence.scenarios_repository import get_scenario
        sc_rec = get_scenario(scenario_id=ws.active_scenario_id,
                              user_id=workspace_owner)
        if (sc_rec is None or sc_rec.archived
                or sc_rec.project_id != project_record.project_id):
            return _render_goal_seek_results({
                "result": {
                    "status": GoalSeekStatus.INVALID_REQUEST.value,
                    "target_metric_label": metric.label,
                    "message": "Active scenario could not be resolved. "
                               "Please re-select a scenario and try again.",
                },
                "apply": None,
                "request": request,
            })
        _scenario_overrides_for_fold = sc_rec.overrides

    from app.services.capex_sub_lines_integration import (
        apply_user_sub_lines_replacing_base,
    )
    from app.services.opex_sub_lines_integration import apply_user_sub_lines_to_opex

    folded_capex = apply_user_sub_lines_replacing_base(
        override.capex,
        project_id=project_record.project_id,
        scenario_overrides=_scenario_overrides_for_fold,
    )
    if folded_capex is not override.capex:
        override = dc_replace(override, capex=folded_capex)
    folded_opex = apply_user_sub_lines_to_opex(
        override.opex,
        project_id=project_record.project_id,
        scenario_overrides=_scenario_overrides_for_fold,
    )
    if folded_opex is not override.opex:
        override = dc_replace(override, opex=folded_opex)

    from app.workbook.bankability_config import SNAPSHOT_KEY, assert_materialized_fee_authority
    try:
        assert_materialized_fee_authority(override, pis_draft.snapshot_origin.get(SNAPSHOT_KEY))
    except ValueError as exc:
        return _render_goal_seek_results({"result": {"status": GoalSeekStatus.INVALID_REQUEST.value,
            "target_metric_label": metric.label, "message": str(exc)}, "apply": None, "request": request})
    from app.workbook.multisenior_config import SNAPSHOT_KEY as f3_key, apply_state, scope_for_workspace
    try:
        override = apply_state(override, pis_draft.snapshot_origin.get(f3_key), scope_for_workspace(ws),
            bankability_raw=pis_draft.snapshot_origin.get(SNAPSHOT_KEY))
    except ValueError as exc:
        return _render_goal_seek_results({"result": {"status": GoalSeekStatus.INVALID_REQUEST.value,
            "target_metric_label": metric.label, "message": str(exc)}, "apply": None, "request": request})

    # ── Current canonical tariff (draft state the user sees) ──────────────── #
    apply_field_id, raw_current = _goal_seek_resolve_tariff_field(variable, pis_draft)
    try:
        current_tariff = float(str(raw_current).strip())
        if not math.isfinite(current_tariff) or current_tariff <= 0:
            raise ValueError("non-positive")
    except (TypeError, ValueError):
        return _render_goal_seek_results({
            "result": {
                "status": GoalSeekStatus.INVALID_REQUEST.value,
                "target_metric_label": metric.label,
                "message": ("The current tariff on this working copy is "
                            "missing or not a positive number; Goal Seek "
                            "cannot derive an adaptive bracket."),
            },
            "apply": None,
            "request": request,
        })

    # ── Deterministic bracketed solve (persistence-free candidates) ───────── #
    from app.runtime.model_execution import ModelExecutionBusy
    evaluator = make_canonical_evaluator(runtime_project_key, override, metric)
    try:
        result = await solve_tariff_for_metric(
            project_type=project_type_raw,
            current_tariff=current_tariff,
            target_value=target_fraction,
            metric_key=metric.key,
            evaluate_batch=evaluator,
        )
    except ModelExecutionBusy:
        return HTMLResponse(
            content="<p>The model engine is busy — please retry in a moment.</p>",
            status_code=429,
            headers={"Retry-After": "5", "X-Finco-Model-Busy": "1"})
    except GoalSeekModelRunError as exc:
        result = GoalSeekResult(
            status=GoalSeekStatus.MODEL_RUN_FAILED.value,
            solve_variable=variable.key,
            solve_variable_label=variable.label,
            solve_variable_unit=variable.unit,
            solve_field_id=apply_field_id,
            target_metric=metric.key,
            target_metric_label=metric.label,
            target_value=target_fraction,
            solved_input_value=None,
            achieved_metric_value=None,
            absolute_target_error=None,
            iterations=0,
            model_evaluations=0,
            lower_bound=0.0,
            upper_bound=0.0,
            bracket_lower=None,
            bracket_upper=None,
            started_from_value=current_tariff,
            message=f"Canonical model run failed: {exc}")

    apply_ctx = None
    if result.solved and result.solved_input_value is not None:
        # CANONICAL APPLY VALUE (exact float that was evaluated and proven);
        # the 2-decimal figure is display-only (template). repr() round-trips.
        solved_display = repr(float(result.solved_input_value))
        content_hash = ""
        workbook_version = WORKBOOK.version
        try:
            identity = assemble_consistent_for_get(
                user_id=workspace_owner,
                project_id=project_record.project_id,
                workbook_version=workbook_version,
            )
            content_hash = identity.composite_hash
        except Exception:
            content_hash = ""
        apply_ctx = _goal_seek_apply_ctx(
            project=project,
            field_id=apply_field_id,
            solved_display=solved_display,
            content_hash=content_hash,
            workbook_version=workbook_version,
            target_metric=metric.key,
            target_value=str(target_pct),
        )

    return _render_goal_seek_results({
        "result": result,
        "apply": apply_ctx,
        "request": request,
    })


@router.post("/workbook/goal-seek/apply", response_class=HTMLResponse)
async def v2_workbook_goal_seek_apply(
    request: Request,
    project: str = Form(...),
    field_id: str = Form(...),
    value: str = Form(...),
    content_hash: str = Form(...),
    workbook_version: str = Form(...),
    target_metric: str = Form(default=""),
    target_value: str = Form(default=""),
    _: None = Depends(require_v2_active),
):
    """Apply a SOLVED Goal Seek tariff to the Working Copy.

    Uses the canonical field-save authority (WorkbookUpdateService
    → v2_atomic_draft_update CAS). This is the ONLY write in the Goal Seek
    flow; it triggers the normal STALE semantics — the model stays STALE
    until the user presses the normal Run button. A Goal Seek candidate run
    is never written as the canonical Last Run.
    """
    from app.persistence.projects_repository import resolve_accessible_project
    from app.persistence.workspace_repository import get_workspace_state
    from app.services.goal_seek import GoalSeekStatus
    from app.services.project_library_service import is_protected_reference

    user = _get_current_user(request)
    if not user:
        return HTMLResponse(content="<p>Unauthenticated.</p>", status_code=401)

    project_record, workspace_owner = resolve_accessible_project(user.user_id, project)
    if project_record is None:
        return HTMLResponse(content=f"<p>Project {project!r} not found.</p>",
                            status_code=404)
    if is_protected_reference(project_record):
        return HTMLResponse(
            content="<p>This is a protected reference model. Create a working copy to edit it.</p>",
            status_code=409)
    ws = get_workspace_state(user_id=workspace_owner, project_id=project_record.project_id)
    if ws is None:
        return HTMLResponse(content="<p>Workspace not found.</p>", status_code=404)

    # ── Server-side contract: Goal Seek Apply is NOT a generic edit endpoint ─ #
    import math as _math

    from app.services.goal_seek import resolve_solve_variable as _resolve_var

    def _reject(message: str) -> HTMLResponse:
        return _render_goal_seek_results({
            "result": {
                "status": GoalSeekStatus.INVALID_REQUEST.value,
                "target_metric_label": target_metric,
                "message": message,
            },
            "apply": None,
            "request": request,
        })

    _variable = _resolve_var((project_record.project_type or "").strip().lower())
    if _variable is None:
        return _reject("This project type has no supported Goal Seek solve "
                       "variable; nothing was applied.")
    _permitted_field, _ = _goal_seek_resolve_tariff_field(
        _variable, WorkbookService.build_draft_input_set_from_workspace(ws))
    if field_id != _permitted_field:
        return _reject("Submitted field is not the Goal Seek solve variable "
                       "for this project; nothing was applied.")
    try:
        _numeric = float(str(value).strip())
        if not _math.isfinite(_numeric):
            raise ValueError("not finite")
    except (TypeError, ValueError):
        return _reject("Solved value is not a finite number; nothing was applied.")

    def _ctx(message: str, *, applied: bool, error: bool = False) -> HTMLResponse:
        fresh_hash = content_hash
        try:
            identity = assemble_consistent_for_get(
                user_id=workspace_owner,
                project_id=project_record.project_id,
                workbook_version=workbook_version,
            )
            fresh_hash = identity.composite_hash
        except Exception:
            pass
        response = _render_goal_seek_results({
            "result": {
                "status": "APPLIED" if applied else GoalSeekStatus.INVALID_REQUEST.value,
                "target_metric_label": target_metric,
                "message": message,
            },
            "apply": None if applied or error else _goal_seek_apply_ctx(
                project=project,
                field_id=field_id,
                solved_display=value,
                content_hash=fresh_hash,
                workbook_version=workbook_version,
                target_metric=target_metric,
                target_value=target_value,
            ),
            "applied": applied,
            "applied_value": f"{_numeric:.2f} EUR/MWh",
            "applied_field_id": field_id,
            "content_hash": fresh_hash,
            "workbook_version": workbook_version,
            "project": project,
            "request": request,
        })
        if applied:
            # Reuse the existing post-save UI authority: Apply changed the
            # composite hash, so the next normal Run must receive fresh tokens.
            from app.v2.post_run_ui import build_post_save_ui_state
            fresh_ws = get_workspace_state(
                user_id=workspace_owner, project_id=project_record.project_id)
            if fresh_ws is None:
                return HTMLResponse(content=response.body.decode() +
                    "<p>Input applied; workspace unavailable for control refresh. Reopen the workbook.</p>",
                    status_code=409)
            refresh = build_post_save_ui_state(
                ws_fresh=fresh_ws, project_record=project_record, project=project,
                workspace_owner=workspace_owner, request=request,
                include_banner_and_controls=True)
            response = HTMLResponse(content=response.body.decode() + "\n" + refresh)
        return response

    try:
        WorkbookUpdateService.apply_draft_update(
            ws=ws,
            field_id=field_id,
            raw_value=value,
            content_hash=content_hash,
            workbook_version=workbook_version,
            project_record=project_record,
        )
    except StaleContentError:
        return _ctx(
            "Draft changed since the solve — the solved tariff was NOT "
            "applied (atomic safety). Re-run Goal Seek on the current draft.",
            applied=False, error=True)
    except (UnknownFieldError, NonEditableFieldError, FieldValidationError,
            ProtectedReferenceError, VersionMismatchError) as exc:
        return _ctx(f"Solved tariff could not be applied: {exc}",
                    applied=False, error=True)

    return _ctx(
        f"Applied {field_id} = {value} to the Working Copy. The model is "
        "now STALE — press Run to make it canonical. (Goal Seek candidate "
        "runs never wrote Run History or Last Run.)",
        applied=True)
