"""FINCO Protocol web application with FINCO Model workspace."""
import asyncio
import hashlib
import json
import logging
import os
import pathlib
import re
import subprocess
from datetime import datetime as dt
from dateutil.relativedelta import relativedelta

from fastapi import FastAPI, Request, Form, Response, Depends, HTTPException, status
from fastapi.responses import HTMLResponse, StreamingResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from typing import Any, Optional

# Import existing model logic (no changes to these)
from app.api.project_runner import run_project
from app.excel_export import build_excel_export
from app.capex_engine import build_capex_line_items_from_defaults
from app.project_factories import create_generic_solar_reference, create_generic_wind_reference, create_generic_storage_reference, create_generic_data_center_reference
from app.project_factories import create_default_solar_project, create_default_wind_project

# Phase P2-FIX-6: C2 first-edit UX. The state banner
# uses ``is_protected_reference`` to decide whether
# to render the 'Create editable copy' button.
from app.ui.protected_reference_service import is_protected_reference

# U3-SAVED-PROJECT-FLOW-CLEANUP: per-project validation tier badge for
# the project browser cards. Presentation-only; no engine/formula impact.
from app.validation_status import get_validation_status

# Import schema and adapter for custom inputs
from app.input_schema import ProjectInputsSchema, RevenueInput, CapexInput, OpexInput, DebtInput
from app.input_adapter import SnapshotInputError, build_projectinputs, build_projectinputs_from_snapshot

# Import auth
from app.auth import (
    verify_login,
    create_session_token,
    decode_session_token,
    make_session_cookie,
    clear_session_cookie,
    generate_csrf_token,
    validate_csrf_token,
    _check_rate_limit,
    _record_failed_login,
    _clear_failed_logins,
    COOKIE_NAME,
    # Demo session
    DEMO_COOKIE_NAME,
    create_demo_session_token,
    decode_demo_session_token,
    make_demo_cookie,
    clear_demo_cookie,
    new_demo_user_id,
    check_demo_rate_limit,
    resolve_request_session,
)

# Import persistence
from app.persistence.repository import (
    _now_utc,
    add_scenario,
    get_or_create_base_case_scenario,
    archive_scenario,
    base_vs_active_compare,
    bind_workspace_to_scenario,
    build_export_lineage,
    compare_scenarios,
    count_runs,
    create_project_record,
    delete_run,
    discard_workspace_draft,
    duplicate_scenario,
    get_project_by_code,
    get_project_record,
    get_run,
    get_scenario,
    get_scenario_provenance,
    get_scenario_history,
    get_workspace_state,
    list_exports,
    list_baseline_records,
    list_project_records,
    list_runs,
    list_scenarios,
    promote_scenario_to_base_case,
    _get_least_created_scenario_for_project,
    record_workspace_runtime,
    rename_scenario,
    save_project,
    save_run,
    save_scenario,
    save_workspace_state,
    seed_baseline_projects_if_needed,
    select_scenario,
    snapshots_equal,
    update_project_record,
    update_scenario_last_run_summary,
    update_scenario_overrides,
)
from app.persistence.provenance import build_replay_metadata, utc_now_iso
from app.ui.project_context import build_project_context_for_record, get_project_context
from app.ui.runtime_summary import runtime_summary_to_dict, NOT_AVAILABLE
from app.ui.what_changed import build_scenario_card_deltas
# Phase 25B-4 — dirty-state UI helpers (pure functions, no DB, no I/O)
from app.ui.dirty_state import build_dirty_state_ui
# Phase 25B-5 — scenario workflow polish helpers (pure functions, no DB, no I/O)
from app.ui.scenario_workflow import build_scenario_workflow_ui
# Phase 25B-6 — generic project review pack helpers (pure functions, no DB, no I/O)
from app.ui.project_review import build_project_review_ui
from app.ui.capex_view_model import build_capex_view_model
from app.ui.opex_view_model import build_opex_view_model
from app.export.runtime_summary import build_runtime_summary_csv, build_runtime_summary_rows
from app.export.institutional_workbook import export_institutional_workbook_skeleton
from app.workbook import RuntimeResult
from app.services.export_service import build_values_only_export_for_project, build_runtime_summary_csv_export, build_institutional_workbook_export, build_excel_export_for_post_request
from app.services.export_audit_service import record_runtime_summary_export, record_institutional_workbook_export, record_download_export
from app.services.scenario_state_service import build_workspace_state_metadata, scenario_provenance_for_record, resolve_runtime_snapshot, RuntimeSnapshotResolution, check_runtime_allowed
from app.services.compare_service import CompareRouteDeps, execute_compare_route
from app.services.validation_service import ValidateRouteDeps, execute_validate_route
from app.services.download_service import DownloadRouteDeps, execute_post_download_route, execute_get_download_route
from app.services.model_preview import validate_preview_payload as _model_preview_validate_payload, build_preview_response as _model_preview_build_response

# -- Asset versioning ---------------------------------------------------------
# Derived from git commit SHA so every deploy gets a unique cache-busting token.
# Falls back to an MD5 of styles.css mtime if git is unavailable.
def _compute_asset_version() -> str:
    try:
        sha = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=os.path.dirname(os.path.abspath(__file__)),
            stderr=subprocess.DEVNULL,
            timeout=5,
        ).decode().strip()
        if sha:
            return sha
    except Exception:
        pass
    css_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "styles.css")
    try:
        mtime = str(os.path.getmtime(css_path))
        return hashlib.md5(mtime.encode()).hexdigest()[:8]
    except Exception:
        return "dev"


ASSET_VERSION = _compute_asset_version()

_logger = logging.getLogger(__name__)
_logger.info("FINCO Model startup: asset_version=%s", ASSET_VERSION)

# -- FastAPI app --------------------------------------------------------------
app = FastAPI(
    title="FINCO Protocol",
    # Disable FastAPI's built-in /docs and /openapi.json.
    # /api/docs serves self-hosted swagger-ui (CSP-compliant).
    # /api/openapi.json serves a filtered public schema (/api/v1/** only).
    # /docs is reserved for FINCO product documentation.
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

# -- Model run concurrency limiter (P6.6) -------------------------------------
# Bounds concurrent model runs to prevent resource exhaustion.
#
# Design:
#   - asyncio.Semaphore(_MAX_CONCURRENT_RUNS) limits concurrent /run executions.
#   - Acquisition is non-blocking: locked() returns False immediately if full.
#   - Full → immediate 503 "Model busy" (fail-fast; no queue).
#   - This is per-process: with Gunicorn multi-worker, each worker has its own
#     semaphore, so the effective total = FINCO_MAX_CONCURRENT_RUNS × workers.
#     Default 8 × 1 worker (uvicorn) or set FINCO_MAX_CONCURRENT_RUNS=2 with
#     4 workers to get effective limit of 8. Document this in deploy/staging config.
#   - FINCO_MAX_CONCURRENT_RUNS=0 disables the limiter (dev/single-user mode).
_MAX_CONCURRENT_RUNS = int(os.getenv("FINCO_MAX_CONCURRENT_RUNS", "8"))
_run_semaphore: asyncio.Semaphore | None = (
    asyncio.Semaphore(_MAX_CONCURRENT_RUNS) if _MAX_CONCURRENT_RUNS > 0 else None
)


async def _acquire_run_slot() -> bool:
    """Non-blocking attempt to acquire a model-run slot.

    Returns True if acquired (caller must call _release_run_slot()).
    Returns False immediately when all slots are busy — caller returns 503.

    Atomic in asyncio's single-threaded model: locked() is checked and
    acquire() is called with no intervening await points. When the semaphore
    is unlocked (value > 0), acquire() decrement is synchronous — the while
    loop inside asyncio.Semaphore.acquire() only awaits when value == 0.
    The locked() check and the acquire() therefore form a single atomic unit
    with no TOCTOU gap.
    """
    if _run_semaphore is None:
        return True
    if _run_semaphore.locked():
        return False
    await _run_semaphore.acquire()
    return True


def _release_run_slot() -> None:
    if _run_semaphore is not None:
        _run_semaphore.release()


@app.on_event("startup")
async def _bootstrap_reference_models():
    """Idempotent: ensure system reference projects exist before first request."""
    try:
        from app.services.project_library_service import (
            ensure_reference_models,
            ensure_reference_canonical_last_runs,
        )
        ensure_reference_models()
        ensure_reference_canonical_last_runs()
    except Exception:
        import logging
        logging.getLogger(__name__).exception("Failed to bootstrap reference models at startup")


@app.on_event("startup")
async def _schedule_demo_cleanup():
    """Schedule recurring demo TTL cleanup in a daemon thread (P6.5).

    TTL authority: ``MAX(updated_at)`` across ALL project rows owned by a
    demo user_id. A session is expired only when its most-recently-updated
    project is beyond the TTL window. No fresh session object is deleted
    merely because another object in the same session is old.

    Runs once at startup (deferred 5 min) then repeats every FINCO_DEMO_TTL_HOURS
    hours so long-lived staging processes clean up without operator intervention.
    """
    import threading
    import time as _time

    from app.auth import DEMO_TTL_HOURS

    def _run():
        _time.sleep(300)  # defer 5 min so startup I/O settles
        while True:
            try:
                from app.demo_cleanup import cleanup_expired_demo_data
                cleanup_expired_demo_data()
            except Exception:
                import logging
                logging.getLogger(__name__).exception("Demo TTL cleanup failed")
            # Sleep for the full TTL period before next sweep
            _time.sleep(max(3600, DEMO_TTL_HOURS * 3600))

    t = threading.Thread(target=_run, daemon=True, name="demo-cleanup")
    t.start()


# -- Template setup -----------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "app", "templates"))
templates.env.globals["htmx"] = True
templates.env.globals["asset_version"] = ASSET_VERSION

# -- Project Library (always mounted) ----------------------------------------
from app.library.router import router as _library_router
app.include_router(_library_router)

# -- Workbook V2 — always mounted (inactive guard inside each router) ---------
# The V2 routers are mounted unconditionally so that:
#   1. ``GET /v2/workbook`` can issue a 302 to the library when the flag is off.
#   2. All 11 mutation endpoints return 409 (via require_v2_active dependency)
#      instead of 404 when the flag is off, preserving a consistent contract.
#
# Flag default changed in PR-A: absent → ACTIVE (see app/utils/workbook_flag.py).
from app.v2.router import router as _v2_router
app.include_router(_v2_router, prefix="/v2")
from app.v2.capex_router import capex_router as _v2_capex_router
app.include_router(_v2_capex_router, prefix="/v2/capex")
from app.v2.opex_router import opex_router as _v2_opex_router
app.include_router(_v2_opex_router, prefix="/v2/opex")

# -- FINCO Radar v1 (Post-R12 P2) — narrow read-only Radar surface ------------
# Read-only product UI over the frozen R0-R12 authority and the canonical
# P1 acquisition runtime. One refresh -> one immutable snapshot_id; all
# panels and the Evidence Inspector reference that exact snapshot.
from app.radar_ui.router import router as _radar_router
app.include_router(_radar_router)

# -- FINCO Protocol Shell (Unified home + Verify surface) ----------------------
from app.protocol_ui.router import router as _protocol_router
app.include_router(_protocol_router)

# -- FINCO Public Model & Radar API v1 -----------------------------------------
# Mount ONLY the canonical public v1 router so that:
#   - /api/v1/model/references/** and /api/v1/radar/** are reachable
#   - legacy bare routes (/api/v1/run, /api/v1/validate, /api/v1/project-types,
#     /api/v1/scenarios) are NOT exposed through the public web app
# app.api.v1.router already includes the model router (model_router.router).
# main_api.py mounts these same routers for the standalone API process.
from app.api.v1.router import router as _api_v1_router
import app.api.v1.run_limiter as _run_limiter  # noqa: F401 — initialises semaphore
app.include_router(_api_v1_router, prefix="/api/v1")


def _friendly_error(exc: Exception, context: str = "") -> str:
    """Return a user-safe error message; log the raw exception server-side."""
    _logger.exception("Runtime error%s: %s", f" in {context}" if context else "", exc)
    ctx = f" while running {context}" if context else ""
    return f"An error occurred{ctx}. Please check your inputs or contact support if the problem persists."


def _jinja_fmt_kpi(v: Any, fmt: str) -> str:
    """Format a KPI value for display in the sensitivity table."""
    if v is None:
        return "—"
    try:
        f = float(v)
    except (TypeError, ValueError):
        return str(v)
    if fmt == "pct":
        return f"{f:.2%}"
    if fmt == "x":
        return f"{f:.4f}x"
    if fmt == "keur":
        return f"{f:,.1f}"
    if fmt == "yrs_f":
        return f"{f:.1f} yrs"
    return f"{f:.4g}"


def _jinja_fmt_delta(v: Any, fmt: str) -> str:
    if v is None:
        return "—"
    try:
        f = float(v)
    except (TypeError, ValueError):
        return str(v)
    if fmt == "pct":
        return f"{f:+.2%}"
    if fmt == "x":
        return f"{f:+.4f}x"
    if fmt == "keur":
        return f"{f:+,.1f}"
    return f"{f:+.4g}"


templates.env.globals["_fmt_kpi"] = _jinja_fmt_kpi
templates.env.globals["_fmt_delta"] = _jinja_fmt_delta
def _intcomma(v):
    try:
        return "{:,}".format(int(float(str(v))))
    except (ValueError, TypeError):
        return str(v) if v else ""
templates.env.filters["intcomma"] = _intcomma

# -- Static files -------------------------------------------------------------
# resolve_static_dir prefers the source-checkout path in dev mode and falls
# back to the installed `static` package in a clean-install environment.
from app._asset_paths import resolve_static_dir as _resolve_static_dir
_static_dir = _resolve_static_dir(BASE_DIR)
if _static_dir:
    app.mount("/static", StaticFiles(directory=_static_dir), name="static")

# -- Observability middleware -------------------------------------------------
# Import only if middleware files exist (graceful degradation)
try:
    from app.logging_config import configure_logging
    configure_logging()
except Exception:
    pass

try:
    from app.middleware.security_headers import SecurityHeadersMiddleware
    from app.middleware.request_logging import RequestLoggingMiddleware
    from app.middleware.exception_handler import ExceptionHandlerMiddleware

    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(RequestLoggingMiddleware)
    # ExceptionHandlerMiddleware must be last (catches all remaining errors)
    app.add_middleware(ExceptionHandlerMiddleware)
except Exception:
    pass  # middleware registration failure should not break the app

# -- Demo session middleware --------------------------------------------------
# Provisions an anonymous demo session for visitors with no session cookie.
# Stores the new token in request.state so get_current_user() can read it
# within the same request; also sets the cookie on the outgoing response.

_DEMO_PROVISION_SKIP_PREFIXES = (
    "/static",
    "/login",
    "/logout",
    "/public-health",
    "/readyz",
    "/health",
    "/favicon",
    "/api",  # public developer API — no demo session created on stateless API calls
)


async def _demo_session_middleware(request, call_next):
    """Auto-provision anonymous demo sessions for new visitors."""
    has_admin = COOKIE_NAME in request.cookies
    has_demo = DEMO_COOKIE_NAME in request.cookies
    path = request.url.path

    new_demo_token: Optional[str] = None
    if (
        not has_admin
        and not has_demo
        and not any(path.startswith(p) for p in _DEMO_PROVISION_SKIP_PREFIXES)
    ):
        demo_id = new_demo_user_id()
        new_demo_token = create_demo_session_token(demo_id)
        request.state.demo_session_token = new_demo_token

    response = await call_next(request)

    if new_demo_token is not None:
        cookie = make_demo_cookie(new_demo_token)
        response.set_cookie(**cookie)

    return response


app.middleware("http")(_demo_session_middleware)


# -- HTTP error observability middleware --------------------------------------

async def _http_error_observability_middleware(request: Request, call_next):
    """Log structured events for 4xx/5xx responses via app.observability."""
    response = await call_next(request)
    if response.status_code >= 400:
        try:
            from app.observability import log_http_error
            log_http_error(
                status_code=response.status_code,
                path=request.url.path,
                method=request.method,
            )
        except Exception:
            pass
    return response


app.middleware("http")(_http_error_observability_middleware)

# -- Shared caveats (visible in UI) -------------------------------------------
CAVEATS = [
    "Synthetic reference models are illustrative and not jurisdiction-specific advice",
    "Outputs are deterministic model results and require professional review",
    "FINCO Radar and token-market functionality are separate from the modelling engine",
]

# -- KPI names ----------------------------------------------------------------
KPI_LABELS = {
    "project_irr": "Project IRR",
    "equity_irr": "Equity IRR",
    "min_dscr": "Min DSCR",
    "avg_dscr": "Avg DSCR",
    "total_revenue_keur": "Total Revenue (kEUR)",
    "total_ebitda_keur": "Total EBITDA (kEUR)",
}

SCENARIOS = ["Base", "Downside", "Upside"]
PROJECT_TYPES = ["Solar", "Wind", "Data Center"]

# Phase 20E: Scenario tab editable fields (section groups)
SCENARIO_EDITABLE_FIELDS = [
    ("Identity", [
        ("project_name", "Project Name"),
        ("country_market", "Country / Market"),
    ]),
    ("Schedule", [
        ("cod_date", "COD Date"),
        ("construction_months", "Construction (months)"),
        ("horizon_years", "Horizon (years)"),
    ]),
    ("Technical", [
        ("capacity_mw", "Capacity (MW)"),
        ("p50_hours", "P50 Hours"),
        ("ppa_term_years", "PPA Term (years)"),
    ]),
    ("Revenue / PPA", [
        ("tariff_eur_mwh", "Tariff (EUR/MWh)"),
    ]),
    ("CAPEX Summary", [
        ("total_capex_keur", "Total CAPEX (kEUR)"),
    ]),
    ("OPEX Summary", [
        ("opex_y1_keur", "Y1 OPEX (kEUR)"),
    ]),
    ("Financing", [
        ("gearing_pct", "Gearing (%)"),
        ("target_dscr", "Target DSCR"),
        ("interest_rate_pct", "Interest Rate (%)"),
        ("tenor_years", "Tenor (years)"),
    ]),
]
FACTORY_TEMPLATE_OPTIONS = [
    {
        "project_code": "generic_wind_reference",
        "label": "Generic Wind Reference",
        "meta": "48 MW · Generic Market B",
        "project_type": "Wind",
        "template_source": "generic_wind_reference",
    },
    {
        "project_code": "generic_solar_reference",
        "label": "Generic Solar Reference",
        "meta": "64 MW · Generic Market A",
        "project_type": "Solar",
        "template_source": "generic_solar_reference",
    },
    {
        "project_code": "generic_storage_reference",
        "label": "Generic Storage Reference",
        "meta": "40 MW / 160 MWh · Generic Market C",
        "project_type": "Storage",
        "template_source": "generic_storage_reference",
    },
    {
        "project_code": "generic_data_center_reference",
        "label": "Generic Data Center Reference",
        "meta": "20 MW IT · Generic Market D",
        "project_type": "Data Center",
        "template_source": "generic_data_center_reference",
    },
]
NEW_PROJECT_TEMPLATE_OPTIONS = [
    {"value": "generic_wind", "label": "Generic Wind (exploratory)", "project_type": "Wind"},
    {"value": "generic_solar", "label": "Generic Solar (exploratory)", "project_type": "Solar"},
    {"value": "generic_wind_reference", "label": "Generic Wind Reference", "project_type": "Wind"},
    {"value": "generic_solar_reference", "label": "Generic Solar Reference", "project_type": "Solar"},
    {"value": "generic_storage_reference", "label": "Generic Storage Reference", "project_type": "Storage"},
    {"value": "generic_data_center_reference", "label": "Generic Data Center Reference", "project_type": "Data Center"},
    {"value": "generic_ev_charging_reference", "label": "Generic EV Charging Hub Reference", "project_type": "EV Charging"},]


# -- Auth dependency ----------------------------------------------------------

def get_current_user(request: Request):
    """Extract session from cookie — delegates to the canonical resolver.

    The shared authority is app.auth.resolve_request_session (admin → demo
    cookie → provisioned demo → None); this wrapper keeps the historical
    entrypoint name for existing imports and templates.
    """
    return resolve_request_session(request)

def require_auth(request: Request):
    """Require auth - returns user or raises redirect to /login."""
    user = get_current_user(request)
    if not user:
        # Return redirect URL for caller to use (avoiding async issues)
        raise HTTPException(status_code=302)
    return user


def _governance_snapshot(project_code: str | None = None) -> dict:
    project_label = (project_code or "").upper() or "GENERAL"
    return {
        "project_code": project_label,
        "g20_status": "BLOCKED",
        "r99_r102_status": "NOT APPROVED",
        "accepted_conventions_state": "Phase 10 closeout baseline",
        "evidence_posture_summary": "Runtime vs governance distinction preserved",
    }


def _slugify_project_code(project_name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", (project_name or "").strip().lower()).strip("-")
    return base or "project"


def _canonical_project_type(project_type: str | None) -> str:
    value = (project_type or "").strip().lower()
    if value in {"storage", "bess"}:
        return "Storage"
    if value in {"data center", "data_center", "datacenter"}:
        return "Data Center"
    if value == "solar":
        return "Solar"
    if value in {"ev charging", "ev_charging", "evcharging"}:
        return "EV Charging"
    return "Wind"


def _normalize_template_source(template_source: str | None, project_type: str | None) -> str:
    source = (template_source or "").strip().lower()
    if source in {"generic_wind_reference", "generic_solar_reference", "generic_storage_reference", "generic_data_center_reference", "generic_ev_charging_reference", "generic_wind", "generic_solar", "generic_storage", "generic_data_center", "generic_ev_charging"}:
        return source
    canonical = _canonical_project_type(project_type)
    if canonical == "Solar":
        return "generic_solar"
    if canonical == "Storage":
        return "generic_storage"
    if canonical == "Data Center":
        return "generic_data_center"
    if canonical == "EV Charging":
        return "generic_ev_charging"
    return "generic_wind"

def _template_source_label(template_source: str | None) -> str:
    mapping = {
        "generic_wind_reference": "Generic Wind Reference",
        "generic_solar_reference": "Generic Solar Reference",
        "generic_storage_reference": "Generic Storage Reference",
        "generic_data_center_reference": "Generic Data Center Reference",
        "generic_wind": "Generic Wind",
        "generic_solar": "Generic Solar",
        "generic_data_center": "Generic Data Center",
        "none": "none",
    }
    return mapping.get((template_source or "").strip().lower(), "none")


def _project_identity_from_template_source(template_source: str, fallback_project_type: str | None = None) -> tuple[str, str]:
    source = _normalize_template_source(template_source, fallback_project_type)
    if source == "generic_solar_reference":
        return "generic_solar_reference", "Generic Solar Reference"
    if source == "generic_wind_reference":
        return "generic_wind_reference", "Generic Wind Reference"
    if source == "generic_storage_reference":
        return "generic_storage_reference", "Generic Storage Reference"
    if source == "generic_data_center_reference":
        return "generic_data_center_reference", "Generic Data Center Reference"
    if source == "generic_data_center":
        return "generic_data_center", "Generic Data Center Project"
    if source == "generic_ev_charging_reference":
        return "generic_ev_charging_reference", "Generic EV Charging Hub Reference"
    if source == "generic_solar":
        return "generic_solar", "Generic Solar Project"
    if source == "generic_ev_charging":
        return "generic_ev_charging", "Generic EV Charging Project"
    return "generic_wind", "Generic Wind Project"


def _collect_form_snapshot(form) -> dict:
    fields = [
        "active_project",
        "project_name",
        "project_type",
        "project_origin",
        "template_source",
        "country_market",
        "scenario",
        "capacity_mw",
        "tariff_eur_mwh",
        "p50_hours",
        "total_capex_keur",
        "opex_y1_keur",
        "gearing_pct",
        "target_dscr",
        "interest_rate_pct",
        "tenor_years",
        "cod_date",
        "construction_months",
        "horizon_years",
        "capacity_factor",
        "ppa_term_years",
        # ── Individual CAPEX line items ──────────────────────────────────
        "capex_epc_contract_keur",
        "capex_production_units_keur",
        "capex_epc_other_keur",
        "capex_grid_connection_keur",
        "capex_ops_prep_keur",
        "capex_insurances_keur",
        "capex_lease_tax_keur",
        "capex_construction_mgmt_a_keur",
        "capex_commissioning_keur",
        "capex_audit_legal_keur",
        "capex_construction_mgmt_b_keur",
        "capex_contingencies_keur",
        "capex_taxes_keur",
        "capex_project_acquisition_keur",
        "capex_project_rights_keur",
        "capex_idc_keur",
        "capex_bank_fees_keur",
        "capex_commitment_fees_keur",
        "capex_other_financial_keur",
        "capex_vat_costs_keur",
        "capex_reserve_accounts_keur",
        # ── Individual OPEX line items (added by Phase 20J) ──────────────
        # These use the slugified item code from _slugify_code() in project_context
        # Snapshot persistence is backward-compatible: absence of opex_<code>_y1_keur
        # means "use factory defaults" — backend remains authoritative.
        "opex_technical_management_y1_keur",
        "opex_o_and_m_preventive_and_corrective_y1_keur",
        "opex_maintain_site_y1_keur",
        "opex_clean_material_y1_keur",
        "opex_security_y1_keur",
        "opex_insurance_y1_keur",
        "opex_lease_and_property_tax_y1_keur",
        "opex_power_expenses_y1_keur",
        "opex_audit_and_accounting_and_legal_y1_keur",
        "opex_bank_fees_opex_y1_keur",
        "opex_environmental_and_social_management_y1_keur",
        "opex_contingencies_y1_keur",
        # Phase 20K — Revenue snapshot fields
        "rev_ppa_base_tariff",
        "rev_ppa_index",
        "rev_ppa_term_years",
        "rev_ppa_production_share",
        "rev_balancing_cost",
        "rev_co2_enabled",
        "rev_co2_price",
        # Phase 20L — Construction / IDC snapshot fields
        "construction_months",
        "idc_keur",
        # STAB-6: Phase 56C added currency to the baseline saved_snapshot.
        # Must be collected here so saved_norm and current_norm both contain it.
        "currency",
    ]
    return {field: form.get(field, "") for field in fields}


def _project_baseline_snapshot(project_type: str, template_source: str) -> dict:
    canonical_type = _canonical_project_type(project_type)
    normalized_source = _normalize_template_source(template_source, canonical_type)
    identity_code, _ = _project_identity_from_template_source(normalized_source, canonical_type)
    baseline = {
        "active_project": "",
        "project_name": "",
        "project_type": canonical_type,
        "project_origin": "factory_template",
        "template_source": normalized_source,
        "country_market": "",
        "scenario": "Base",
        "capacity_mw": "",
        "tariff_eur_mwh": "",
        "p50_hours": "",
        "total_capex_keur": "",
        "opex_y1_keur": "",
        "gearing_pct": "",
        "target_dscr": "",
        "interest_rate_pct": "",
        "tenor_years": "",
        "cod_date": "",
        "construction_months": "",
        "horizon_years": "",
        "capacity_factor": "",
        "ppa_term_years": "",
    }

    if normalized_source == "generic_wind_reference":
        project_inputs = create_generic_wind_reference()
        baseline.update(
            {
                "active_project": "generic_wind_reference",
                "project_name": project_inputs.info.name,
                "project_type": "Wind",
                "project_origin": "factory_template",
                "template_source": "generic_wind_reference",
                "country_market": project_inputs.info.country_iso,
                "capacity_mw": str(project_inputs.technical.capacity_mw),
                "tariff_eur_mwh": str(project_inputs.revenue.ppa_base_tariff),
                "p50_hours": str(project_inputs.technical.operating_hours_p50),
                "total_capex_keur": str(project_inputs.capex.total_capex),
                "opex_y1_keur": str(sum(item.y1_amount_keur for item in project_inputs.opex)),
                "target_dscr": str(project_inputs.financing.target_dscr),
                "interest_rate_pct": str(project_inputs.financing.base_rate + project_inputs.financing.margin_bps / 10_000),
                "tenor_years": str(project_inputs.financing.senior_tenor_years),
                "cod_date": str(project_inputs.info.cod_date),
                "construction_months": str(project_inputs.info.construction_months),
                "horizon_years": str(project_inputs.info.horizon_years),
                "capacity_factor": f"{(project_inputs.technical.operating_hours_p50 / 8760) * 100:.2f}",
                "ppa_term_years": str(int(project_inputs.revenue.ppa_term_years)),
            }
        )
        return baseline

    if normalized_source == "generic_solar_reference":
        project_inputs = create_generic_solar_reference()
        from app.revenue_snapshot_utils import materialize_revenue_snapshot_defaults
        baseline.update(
            {
                "active_project": "generic_solar_reference",
                "project_name": project_inputs.info.name,
                "project_type": "Solar",
                "project_origin": "factory_template",
                "template_source": "generic_solar_reference",
                "country_market": project_inputs.info.country_iso,
                "capacity_mw": str(project_inputs.technical.capacity_mw),
                "tariff_eur_mwh": str(project_inputs.revenue.ppa_base_tariff),
                "p50_hours": str(project_inputs.technical.operating_hours_p50),
                "total_capex_keur": str(project_inputs.capex.total_capex),
                "opex_y1_keur": str(sum(item.y1_amount_keur for item in project_inputs.opex)),
                "gearing_pct": str((getattr(project_inputs.financing, "gearing_ratio", 0.0) or 0.0) * 100),
                "target_dscr": str(project_inputs.financing.target_dscr),
                "interest_rate_pct": str(project_inputs.financing.base_rate + project_inputs.financing.margin_bps / 10_000),
                "tenor_years": str(project_inputs.financing.senior_tenor_years),
                "cod_date": str(project_inputs.info.cod_date),
                "construction_months": str(project_inputs.info.construction_months),
                "horizon_years": str(project_inputs.info.horizon_years),
                "capacity_factor": f"{(project_inputs.technical.operating_hours_p50 / 8760) * 100:.2f}",
                "ppa_term_years": str(int(project_inputs.revenue.ppa_term_years)),
            }
        )
        baseline.update(materialize_revenue_snapshot_defaults(project_inputs.revenue))
        return baseline

    if normalized_source == "generic_storage_reference":
        project_inputs = create_generic_storage_reference()
        baseline.update(
            {
                "active_project": "generic_storage_reference",
                "project_name": project_inputs.info.name,
                "project_type": "Storage",
                "project_origin": "factory_template",
                "template_source": "generic_storage_reference",
                "country_market": project_inputs.info.country_iso,
                "capacity_mw": str(project_inputs.technical.capacity_mw),
                "tariff_eur_mwh": "0",
                "p50_hours": "0",
                "total_capex_keur": str(project_inputs.capex.total_capex),
                "opex_y1_keur": str(sum(item.y1_amount_keur for item in project_inputs.opex)),
                "gearing_pct": str((getattr(project_inputs.financing, "gearing_ratio", 0.0) or 0.0) * 100),
                "target_dscr": str(project_inputs.financing.target_dscr),
                "interest_rate_pct": str(project_inputs.financing.base_rate + project_inputs.financing.margin_bps / 10_000),
                "tenor_years": str(project_inputs.financing.senior_tenor_years),
                "cod_date": str(project_inputs.info.cod_date),
                "construction_months": str(project_inputs.info.construction_months),
                "horizon_years": str(project_inputs.info.horizon_years),
                "capacity_factor": "",
                "ppa_term_years": "0",
            }
        )
        return baseline

    if normalized_source in {"generic_data_center_reference", "generic_data_center"}:
        project_inputs = create_generic_data_center_reference()
        baseline.update(
            {
                "active_project": identity_code,
                "project_name": project_inputs.info.name,
                "project_type": "Data Center",
                "project_origin": "factory_template",
                "template_source": normalized_source,
                "country_market": project_inputs.info.country_iso,
                "capacity_mw": str(project_inputs.technical.capacity_mw),
                "tariff_eur_mwh": "0",
                "p50_hours": str(project_inputs.technical.operating_hours_p50),
                "total_capex_keur": str(project_inputs.capex.total_capex),
                "opex_y1_keur": str(sum(item.y1_amount_keur for item in project_inputs.opex)),
                "gearing_pct": str((getattr(project_inputs.financing, "gearing_ratio", 0.0) or 0.0) * 100),
                "target_dscr": str(project_inputs.financing.target_dscr),
                "interest_rate_pct": str(project_inputs.financing.base_rate + project_inputs.financing.margin_bps / 10_000),
                "tenor_years": str(project_inputs.financing.senior_tenor_years),
                "cod_date": str(project_inputs.info.cod_date),
                "construction_months": str(project_inputs.info.construction_months),
                "horizon_years": str(project_inputs.info.horizon_years),
                "capacity_factor": "",
                "ppa_term_years": str(int(project_inputs.revenue.ppa_term_years)),
            }
        )
        return baseline

    if normalized_source == "generic_solar":
        project_inputs = create_default_solar_project()
    elif normalized_source == "generic_storage":
        project_inputs = create_generic_storage_reference()
    else:
        project_inputs = create_default_wind_project()
    baseline.update(
        {
            "active_project": identity_code,
            "project_name": project_inputs.info.name,
            "project_type": canonical_type,
            "project_origin": "factory_template",
            "template_source": normalized_source,
            "country_market": project_inputs.info.country_iso,
            "capacity_mw": str(project_inputs.technical.capacity_mw),
            "tariff_eur_mwh": str(project_inputs.revenue.ppa_base_tariff),
            "p50_hours": str(project_inputs.technical.operating_hours_p50),
            "total_capex_keur": str(project_inputs.capex.total_capex),
            "opex_y1_keur": str(sum(item.y1_amount_keur for item in project_inputs.opex)),
            "gearing_pct": str((getattr(project_inputs.financing, "gearing_ratio", 0.0) or 0.0) * 100),
            "target_dscr": str(project_inputs.financing.target_dscr),
            "interest_rate_pct": str(project_inputs.financing.base_rate + project_inputs.financing.margin_bps / 10_000),
            "tenor_years": str(project_inputs.financing.senior_tenor_years),
            "cod_date": str(project_inputs.info.cod_date),
            "construction_months": str(project_inputs.info.construction_months),
            "horizon_years": str(project_inputs.info.horizon_years),
            "capacity_factor": f"{(project_inputs.technical.operating_hours_p50 / 8760) * 100:.2f}",
            "ppa_term_years": str(int(project_inputs.revenue.ppa_term_years)),
        }
    )
    return baseline


def _project_inputs_for_code(project_code: str):
    code = (project_code or "generic_wind_reference").strip().lower()
    if code == "generic_solar":
        return create_default_solar_project()
    if code == "generic_wind":
        return create_default_wind_project()
    if code == "generic_solar_reference":
        return create_generic_solar_reference()
    if code == "generic_storage_reference":
        return create_generic_storage_reference()
    if code in {"generic_data_center_reference", "generic_data_center"}:
        return create_generic_data_center_reference()
    return create_generic_wind_reference()


def _default_workspace_snapshot(project_code: str) -> dict:
    code = (project_code or "generic_wind_reference").strip().lower()
    if code in {"generic_solar_reference", "generic_solar"}:
        project_type = "Solar"
    elif code in {"generic_storage_reference", "generic_storage"}:
        project_type = "Storage"
    elif code in {"generic_data_center_reference", "generic_data_center"}:
        project_type = "Data Center"
    else:
        project_type = "Wind"
    return _project_baseline_snapshot(project_type, code)


def _project_record_to_context(project_record, baseline_snapshot: dict | None = None):
    return build_project_context_for_record(
        project_code=project_record.project_code,
        project_name=project_record.project_name,
        project_type=project_record.project_type,
        project_origin=project_record.project_origin,
        template_source=project_record.template_source or project_record.source_project_template,
        baseline_snapshot=baseline_snapshot,
    )


def _submitted_new_project_defaults() -> dict[str, str]:
    return {
        "project_name": "",
        "project_type": "Wind",
        "template_source": "generic_wind",
        "country_market": "Generic Market A",
        "capacity_mw": "",
        "cod_date": "",
        "construction_months": "",
        "horizon_years": "",
        "tariff_eur_mwh": "",
        "ppa_term_years": "",
        "p50_hours": "",
        "opex_y1_keur": "",
        "total_capex_keur": "",
        "gearing_pct": "",
        "interest_rate_pct": "",
        "tenor_years": "",
        "target_dscr": "1.20",
    }


def _minimal_submitted_new_project_defaults() -> dict[str, str]:
    """Phase P2-FIX-1: minimal submitted defaults.

    Only the 4 visible fields (project_name,
    project_type, country_market, capacity_mw)
    + template_source. No tariff, PPA, P50,
    OPEX, CAPEX, gearing, interest, tenor,
    DSCR, factory function names.
    """
    return {
        "project_name": "",
        "project_type": "Wind",
        "template_source": P2_MIN_DEFAULT_TEMPLATE_SOURCE,
        "country_market": "Generic Market A",
        "capacity_mw": "",
    }


# Phase 25B-1: Generic defaults prefill helper (UI-driven, read-only).
# The form has a "Use generic defaults" button that calls
# GET /projects/new/defaults?template_source=generic_solar|generic_wind.
# This helper produces a dict of all 16 form fields, derived from
# the EXISTING generic factory functions
# (create_default_solar_project / create_default_wind_project) -- no
# new financial formulas are introduced. The prefill is for round-
# number exploratory sketching only; the user is expected to review
# every field before saving.
#
# Hard contract:
# - Only the two generic template sources are accepted.
#   Any other template_source (generic_wind_reference, generic_solar_reference, etc.) is rejected.
# - The factory functions are read-only; we map their existing
#   ProjectInputs to form fields, never mutate them.
# - Returns a JSON-serializable dict[str, str] of form field values.
# - The prefill is EXPLICITLY marked as exploratory; the form
#   shows an EXPLORATORY badge when the user clicks the button.
_GENERIC_PREFILL_ALLOWED_SOURCES = {"generic_solar", "generic_wind"}


def _generic_prefill_values(template_source: str) -> dict[str, str] | None:
    """Return prefill values for the new project form, or None if
    the template_source is not generic.

    The values come from the existing generic factory functions
    in app/project_factories.py -- no new financial formulas
    are introduced. The factory functions are read-only: we
    only read attributes and stringify them.
    """
    if template_source not in _GENERIC_PREFILL_ALLOWED_SOURCES:
        return None
    # Lazy import to avoid pulling the project_factories module
    # into /projects/new if not needed.
    from app.project_factories import (
        create_default_solar_project,
        create_default_wind_project,
    )
    if template_source == "generic_solar":
        pi = create_default_solar_project()
        project_type = "Solar"
        default_name = "Generic Solar Project"
    else:
        pi = create_default_wind_project()
        project_type = "Wind"
        default_name = "Generic Wind Project"
    # OPEX Y1 is the sum of all opex items, mirroring the
    # existing _project_baseline_snapshot mapping.
    opex_y1 = sum(float(getattr(item, "y1_amount_keur", 0.0) or 0.0)
                  for item in pi.opex)
    # Interest rate: base + margin (bps -> decimal).
    margin_dec = float(getattr(pi.financing, "margin_bps", 0) or 0) / 10_000.0
    interest = float(getattr(pi.financing, "base_rate", 0.0) or 0.0) + margin_dec
    # Gearing: ratio -> percentage string with one decimal.
    gearing_pct = float(getattr(pi.financing, "gearing_ratio", 0.0) or 0.0) * 100.0
    return {
        "project_name": default_name,
        "project_type": project_type,
        "template_source": template_source,
        "country_market": str(pi.info.country_iso or "Generic Market A"),
        "capacity_mw": f"{float(pi.technical.capacity_mw):.1f}",
        "cod_date": str(pi.info.cod_date),
        "construction_months": str(int(pi.info.construction_months)),
        "horizon_years": str(int(pi.info.horizon_years)),
        "tariff_eur_mwh": f"{float(pi.revenue.ppa_base_tariff):.1f}",
        "ppa_term_years": str(int(pi.revenue.ppa_term_years)),
        "p50_hours": f"{float(pi.technical.operating_hours_p50):.0f}",
        "opex_y1_keur": f"{opex_y1:.1f}",
        "total_capex_keur": f"{float(pi.capex.total_capex):.0f}",
        "gearing_pct": f"{gearing_pct:.1f}",
        "interest_rate_pct": f"{interest * 100:.2f}",
        "tenor_years": str(int(pi.financing.senior_tenor_years)),
        "target_dscr": f"{float(pi.financing.target_dscr):.2f}",
    }


def _parse_iso_date(value: str | None) -> dt | None:
    """Parse an ISO-8601 date (YYYY-MM-DD) string into a ``datetime``,
    or return ``None`` if the value is empty / malformed. Phase 56D."""
    text = (value or "").strip()
    if not text:
        return None
    try:
        return dt.strptime(text, "%Y-%m-%d")
    except ValueError:
        return None


def _derive_cod_date(
    construction_start_date: str | None,
    construction_duration_months: str | None,
) -> str | None:
    """Derive the COD (Commercial Operation Date) from the construction
    start date and the construction duration in months.

    Phase 56D — COD is no longer a primary manual input. It is
    derived server-side from:

        COD = construction_start_date + construction_duration_months

    Date convention (deterministic, per Phase 56D policy):

    - Same day-of-month when possible (e.g. 2025-01-15 + 24 months
      = 2027-01-15).
    - If the target month has fewer days, snap to month-end
      (e.g. 2025-01-31 + 1 month = 2025-02-28, not 2025-03-03).
    - Leap-year behavior is deterministic (handled by ``relativedelta``).
    - Duration must be a positive integer number of months.
    - Missing start OR missing/invalid duration returns ``None`` (no
      fake date is invented).

    Returns:
        ISO-8601 date string (YYYY-MM-DD) on success, or ``None`` if
        the inputs are missing/invalid.
    """
    start = _parse_iso_date(construction_start_date)
    if start is None:
        return None
    text = (construction_duration_months or "").strip()
    if not text:
        return None
    try:
        months = int(float(text))
    except ValueError:
        return None
    if months <= 0:
        return None
    derived = start + relativedelta(months=months)
    return derived.strftime("%Y-%m-%d")


async def _read_optional_form_fields(request: Request) -> dict[str, str]:
    """Read optional 56C/56D form fields from the request body without
    going through ``request.form()`` (which is forbidden by the
    Phase 51M-1 golden characterization — the route must use
    ``Form(...)`` parameters only).

    The route signature is frozen at 18 Form fields (Phase 51M-1
    golden). New optional fields (spv_name, currency,
    construction_start_date, construction_duration_months) live
    in the raw body and are read by the route via
    ``request.body()`` + ``urllib.parse.parse_qs``.

    Returns:
        A flat dict of form-key -> first-value (empty string if
        the key is absent or the body is empty).
    """
    from urllib.parse import parse_qs

    try:
        raw_body = await request.body()
    except Exception:
        return {}
    if not raw_body:
        return {}
    try:
        decoded = raw_body.decode("utf-8")
    except UnicodeDecodeError:
        return {}
    parsed: dict[str, str] = {}
    for _k, _vs in parse_qs(decoded, keep_blank_values=True).items():
        if _vs:
            parsed[_k] = _vs[0]
    return parsed


def _apply_56d_extras_to_submitted(
    submitted: dict[str, str],
    extra: dict[str, str],
) -> dict[str, str]:
    """Phase 56C/56D: merge the 4 extra form fields into the
    submitted dict so they land in the baseline_snapshot via
    ``_apply_new_project_required_inputs``.

    COD policy (Phase 56D, manual override NOT supported):

    - COD is ALWAYS derived server-side from
      ``construction_start_date + construction_duration_months``.
    - The server-derived value ALWAYS wins when it can be
      computed (i.e. when both start and duration are valid).
    - A manually supplied ``cod_date`` in the form body is
      IGNORED when derivation succeeds. This is by design:
      manual COD override is deferred in 56D; a future
      override would require explicit audited override logic.
    - If start or duration is missing or invalid, derivation
      returns ``None`` and the existing validation handles
      missing COD safely (no fake date is invented)."""
    submitted["spv_name"] = (extra.get("spv_name", "") or "").strip()
    submitted["currency"] = (
        (extra.get("currency", "") or "").strip() or "EUR"
    )
    submitted["construction_start_date"] = (
        (extra.get("construction_start_date", "") or "").strip()
    )
    submitted["construction_duration_months"] = (
        (extra.get("construction_duration_months", "") or "").strip()
    )
    derived_cod = _derive_cod_date(
        submitted["construction_start_date"],
        submitted["construction_duration_months"],
    )
    # Phase 56D policy: derived COD always wins when derivable.
    # Manual override is deferred; a future override would need
    # explicit audited logic.
    if derived_cod:
        submitted["cod_date"] = derived_cod
    return submitted


def _coerce_form_text(value: str | None) -> str:
    return (value or "").strip()


def _coerce_form_float(value: str | None) -> float | None:
    text = _coerce_form_text(value)
    if not text:
        return None
    return float(text)


def _coerce_form_int(value: str | None) -> int | None:
    text = _coerce_form_text(value)
    if not text:
        return None
    return int(float(text))


def _format_snapshot_number(value: float | int | None, decimals: int | None = None) -> str:
    if value is None:
        return ""
    if decimals is not None:
        return f"{float(value):.{decimals}f}"
    if isinstance(value, int) or float(value).is_integer():
        return str(int(float(value)))
    return str(float(value))


def _new_project_validation_error_context(submitted: dict[str, str], validation_errors: list[str]) -> dict[str, object]:
    return {
        "project_types": PROJECT_TYPES,
        "template_options": NEW_PROJECT_TEMPLATE_OPTIONS,
        "validation_errors": validation_errors,
        "submitted": submitted,
    }


def _new_project_minimal_validation_error_context(submitted: dict[str, str], validation_errors: list[str]) -> dict[str, object]:
    """Phase P2-FIX-1: minimal context for the
    C2 minimal new-project flow. Renders
    the same fields as
    ``_render_new_project_minimal_form``
    so the error response shows the same
    4 visible fields the user just
    submitted (not the legacy full-form
    with 17 driver fields).
    """
    return {
        "project_types": PROJECT_TYPES,
        "validation_errors": validation_errors,
        "submitted": _minimal_submitted_new_project_defaults() | dict(submitted),
        "default_template_source": P2_MIN_DEFAULT_TEMPLATE_SOURCE,
    }


def _validate_new_project_payload(submitted: dict[str, str]) -> list[str]:
    errors: list[str] = []
    project_name = _coerce_form_text(submitted.get("project_name"))
    project_type = submitted.get("project_type", "")
    country_market = _coerce_form_text(submitted.get("country_market"))

    if not project_name:
        errors.append("Project name is required.")
    if project_type not in PROJECT_TYPES:
        errors.append(f"Project type must be one of {PROJECT_TYPES}.")
    if not country_market:
        errors.append("Country or market is required.")

    def require_float(
        field_name: str,
        label: str,
        *,
        min_value: float | None = None,
        max_value: float | None = None,
        strictly_positive: bool = False,
    ) -> float | None:
        text = _coerce_form_text(submitted.get(field_name))
        if not text:
            errors.append(f"{label} is required.")
            return None
        try:
            value = float(text)
        except ValueError:
            errors.append(f"{label} must be a number.")
            return None
        if strictly_positive and value <= 0:
            errors.append(f"{label} must be > 0.")
        elif min_value is not None and value < min_value:
            errors.append(f"{label} must be >= {min_value}.")
        if max_value is not None and value > max_value:
            errors.append(f"{label} must be <= {max_value}.")
        return value

    def require_int(
        field_name: str,
        label: str,
        *,
        min_value: int | None = None,
        max_value: int | None = None,
        strictly_positive: bool = False,
    ) -> int | None:
        text = _coerce_form_text(submitted.get(field_name))
        if not text:
            errors.append(f"{label} is required.")
            return None
        try:
            value = int(float(text))
        except ValueError:
            errors.append(f"{label} must be a whole number.")
            return None
        if strictly_positive and value <= 0:
            errors.append(f"{label} must be > 0.")
        elif min_value is not None and value < min_value:
            errors.append(f"{label} must be >= {min_value}.")
        if max_value is not None and value > max_value:
            errors.append(f"{label} must be <= {max_value}.")
        return value

    # COD is OPTIONAL in P2-FIX-1 (C2 minimal
    # form). The full form still validates
    # it via the construction_start_date +
    # construction_duration_months
    # derivation, but a minimal form
    # submission (4 visible fields) may
    # legitimately have no COD yet — COD can
    # be edited later in the workspace.
    _has_construction_start = bool(
        _coerce_form_text(submitted.get("construction_start_date"))
    )
    _has_construction_duration = bool(
        _coerce_form_text(submitted.get("construction_duration_months"))
    )
    _has_explicit_cod = bool(_coerce_form_text(submitted.get("cod_date")))
    if not _has_explicit_cod and not (
        _has_construction_start and _has_construction_duration
    ):
        # No explicit COD and no derivation
        # inputs. P2-FIX-1: this is allowed in
        # the C2 minimal flow. Skip the error.
        pass

    capacity_mw = require_float("capacity_mw", "Capacity (MW)", strictly_positive=True)

    # Phase 56C: the 11 detailed financial assumptions are no longer
    # required at project creation. They are now entered in the
    # Inputs sheet after the project exists. We still validate them
    # when they are present (so the legacy full-form path keeps
    # working), but we no longer error on empty/missing values.
    def optional_float(field_name: str, label: str) -> float | None:
        text = _coerce_form_text(submitted.get(field_name))
        if not text:
            return None
        try:
            return float(text)
        except ValueError:
            errors.append(f"{label} must be a number.")
            return None

    def optional_int(field_name: str, label: str) -> int | None:
        text = _coerce_form_text(submitted.get(field_name))
        if not text:
            return None
        try:
            return int(float(text))
        except ValueError:
            errors.append(f"{label} must be a whole number.")
            return None

    tariff = optional_float("tariff_eur_mwh", "Tariff (EUR/MWh)")
    p50_hours = optional_float("p50_hours", "P50 hours")
    opex_y1 = optional_float("opex_y1_keur", "OPEX Y1 (kEUR)")
    total_capex = optional_float("total_capex_keur", "Total CAPEX (kEUR)")
    gearing_pct = optional_float("gearing_pct", "Gearing (%)")
    interest_rate_pct = optional_float("interest_rate_pct", "Interest rate (%)")
    tenor_years = optional_int("tenor_years", "Tenor (years)")
    target_dscr = optional_float("target_dscr", "Target DSCR")
    construction_months = optional_int("construction_months", "Construction months")
    horizon_years = optional_int("horizon_years", "Horizon years")
    ppa_term_years = optional_int("ppa_term_years", "PPA term years")

    if (
        ppa_term_years is not None
        and horizon_years is not None
        and ppa_term_years > horizon_years
    ):
        errors.append("PPA term years should be less than or equal to horizon years.")

    return errors


def _apply_new_project_required_inputs(
    baseline_snapshot: dict[str, str],
    *,
    project_name: str,
    project_code: str,
    project_type: str,
    project_origin: str,
    template_source: str,
    submitted: dict[str, str],
) -> dict[str, str]:
    """Layer the user's submitted form values onto the factory-derived
    baseline snapshot.

    U2-NEW-PROJECT-SIMPLIFICATION: the minimal create form only submits
    project_name/project_type/country_market/capacity_mw -- every other
    field arrives as an empty string. A blank submitted value must NOT
    blank out the factory default already present in ``baseline_snapshot``
    (e.g. tariff, PPA term, OPEX, CAPEX, gearing, interest rate, tenor,
    DSCR, COD, construction/horizon years); it should simply leave that
    default in place so the created project remains runnable/exportable
    with the same assumptions as the underlying generic template. Only
    a non-blank submitted value overrides the baseline default.
    """
    snapshot = dict(baseline_snapshot)

    def _override_or_keep(field_name: str, formatted_value: str) -> str:
        return formatted_value if formatted_value else snapshot.get(field_name, "")

    snapshot.update(
        {
            "active_project": project_code,
            "project_name": project_name,
            "project_type": project_type,
            "project_origin": project_origin,
            "template_source": template_source,
            "country_market": _coerce_form_text(submitted.get("country_market")) or snapshot.get("country_market", ""),
            "capacity_mw": _override_or_keep("capacity_mw", _format_snapshot_number(_coerce_form_float(submitted.get("capacity_mw")))),
            "cod_date": _coerce_form_text(submitted.get("cod_date")) or snapshot.get("cod_date", ""),
            "construction_months": _override_or_keep("construction_months", _format_snapshot_number(_coerce_form_int(submitted.get("construction_months")))),
            "horizon_years": _override_or_keep("horizon_years", _format_snapshot_number(_coerce_form_int(submitted.get("horizon_years")))),
            "tariff_eur_mwh": _override_or_keep("tariff_eur_mwh", _format_snapshot_number(_coerce_form_float(submitted.get("tariff_eur_mwh")))),
            "ppa_term_years": _override_or_keep("ppa_term_years", _format_snapshot_number(_coerce_form_int(submitted.get("ppa_term_years")))),
            "p50_hours": _override_or_keep("p50_hours", _format_snapshot_number(_coerce_form_float(submitted.get("p50_hours")))),
            "opex_y1_keur": _override_or_keep("opex_y1_keur", _format_snapshot_number(_coerce_form_float(submitted.get("opex_y1_keur")))),
            "total_capex_keur": _override_or_keep("total_capex_keur", _format_snapshot_number(_coerce_form_float(submitted.get("total_capex_keur")))),
            "gearing_pct": _override_or_keep("gearing_pct", _format_snapshot_number(_coerce_form_float(submitted.get("gearing_pct")))),
            "interest_rate_pct": _override_or_keep("interest_rate_pct", _format_snapshot_number(_coerce_form_float(submitted.get("interest_rate_pct")))),
            "tenor_years": _override_or_keep("tenor_years", _format_snapshot_number(_coerce_form_int(submitted.get("tenor_years")))),
            "target_dscr": _override_or_keep("target_dscr", _format_snapshot_number(_coerce_form_float(submitted.get("target_dscr")), decimals=2)),
        }
    )
    # Phase 56C + 56D: write the new v1 master-data fields and
    # the construction start/duration inputs (which drive the
    # derived cod_date above) into the baseline_snapshot so they
    # survive into the saved scenario.
    snapshot["spv_name"] = _coerce_form_text(submitted.get("spv_name"))
    snapshot["currency"] = (
        _coerce_form_text(submitted.get("currency")) or "EUR"
    )
    snapshot["construction_start_date"] = _coerce_form_text(
        submitted.get("construction_start_date")
    )
    snapshot["construction_duration_months"] = _format_snapshot_number(
        _coerce_form_int(submitted.get("construction_duration_months"))
    )
    return snapshot


def _project_persistence_metadata(project_ctx=None, form_snapshot: dict | None = None, project_record=None) -> tuple[str, str]:
    if project_record is not None:
        return project_record.project_code, project_record.project_name
    if project_ctx is not None:
        return project_ctx.id, project_ctx.name
    active_project = (form_snapshot or {}).get("active_project", "").strip().lower()
    if active_project:
        project_code, project_name = _project_identity_from_template_source(active_project, (form_snapshot or {}).get("project_type"))
        return project_code, project_name
    project_type = _canonical_project_type((form_snapshot or {}).get("project_type"))
    default_source = _normalize_template_source((form_snapshot or {}).get("template_source"), project_type)
    project_code, project_name = _project_identity_from_template_source(default_source, project_type)
    return project_code, project_name


def _workspace_state_meta(workspace_state) -> dict:
    # Phase 50B: implementation moved to scenario_state_service.build_workspace_state_metadata
    return build_workspace_state_metadata(workspace_state)


def _format_ui_timestamp(value) -> str:
    if value is None:
        return "unavailable"
    if hasattr(value, "strftime"):
        return value.strftime("%Y-%m-%d %H:%M")
    text = str(value).strip()
    return text or "unavailable"


def _runtime_summary_for_index(workspace_state) -> dict | None:
    """Build a conservative runtime_summary dict for index.html.

    This is the data the UI-2.6 last-run indicator consumes.

    Source: only fields already in the workspace state record.
    - `run_id` ← `last_runtime_snapshot_id` (real, from prior run)
    - `last_run_at` ← `last_runtime_at` (real timestamp from prior run)

    Returns None if no real runtime data exists, so the indicator
    partial correctly renders nothing (no fake run_id, no fake timestamp).

    The function is read-only — it does not write or mutate state.
    """
    if workspace_state is None:
        return None
    run_id = workspace_state.last_runtime_snapshot_id
    last_run_at = workspace_state.last_runtime_at
    if not run_id and not last_run_at:
        return None
    result: dict = {}
    if run_id:
        result["run_id"] = str(run_id)
    if last_run_at is not None:
        ts = _format_ui_timestamp(last_run_at)
        if ts and ts != "unavailable":
            result["last_run_at"] = ts
    return result if result else None


def _validation_summary_for_context_legacy(project_code: str | None) -> dict | None:
    """Build a conservative validation_summary dict for UI-2.3.

    Source: only existing governance state via `_governance_snapshot`.
    Maps real governance status fields to pass/warn/fail counts:
    - G20 BLOCKED or R99/R102 NOT APPROVED -> fail count
    - Other governance state -> warn count
    - All clear -> pass count (no items to review)

    Returns None if no real governance snapshot can be built.

    The function is read-only — it does not write or mutate state.
    """
    if not project_code:
        return None
    snap = _governance_snapshot(project_code)
    if not snap:
        return None
    pass_count = 0
    warn_count = 0
    fail_count = 0
    # G20 BLOCKED and R99/R102 NOT APPROVED are real, existing hard-stop
    # governance states. They are NOT no-go copy: they are internal
    # governance state flags, not positive UI claims.
    g20 = (snap.get("g20_status") or "").upper()
    r99 = (snap.get("r99_r102_status") or "").upper()
    if g20 == "BLOCKED":
        fail_count += 1
    elif g20:
        warn_count += 1
    else:
        pass_count += 1
    if r99 == "NOT APPROVED":
        fail_count += 1
    elif r99:
        warn_count += 1
    else:
        pass_count += 1
    return {
        "pass_count": pass_count,
        "warn_count": warn_count,
        "fail_count": fail_count,
        "last_validated_at": "",  # No real value exists; left blank intentionally
    }


def _validation_summary_for_context(
    project_record,
    validation_errors: list[str] | None = None,
) -> dict | None:
    """Build UI-2.3 validation summary from current run/input issues only.

    Platform governance guards stay visible via
    ``_governance_guard_summary_for_context`` and do not make every run
    look broken by default.
    """
    if project_record is None:
        return None
    issue_count = len([err for err in (validation_errors or []) if str(err).strip()])
    if issue_count > 0:
        return {
            "pass_count": 0,
            "warn_count": 0,
            "fail_count": issue_count,
            "actual_issue_count": issue_count,
            "last_validated_at": "",
        }
    return {
        "pass_count": 1,
        "warn_count": 0,
        "fail_count": 0,
        "actual_issue_count": 0,
        "last_validated_at": "",
    }


def _governance_guard_summary_for_context(project_record) -> dict | None:
    """Build platform-level governance / feature guard UI context."""
    if project_record is None:
        return None
    snap = project_record.governance_state or _governance_snapshot(project_record.project_code)
    template_source = (
        (project_record.template_source or "")
        or str((project_record.baseline_snapshot or {}).get("template_source", ""))
    ).strip().lower()
    project_code = (project_record.project_code or "").strip().lower()

    items: list[dict[str, str]] = []
    g20 = (snap.get("g20_status") or "").upper()
    if g20:
        items.append(
            {
                "title": "G20",
                "status": g20,
                "badge_class": "badge-blocked" if g20 == "BLOCKED" else "badge-warn",
                "detail": "Platform-level governance guard, not a current-run validation failure.",
            }
        )
    r99 = (snap.get("r99_r102_status") or "").upper()
    if r99:
        items.append(
            {
                "title": "R99/R102",
                "status": r99,
                "badge_class": "badge-notapproved" if r99 == "NOT APPROVED" else "badge-warn",
                "detail": "Feature promotion guard, not a current-run validation failure.",
            }
        )
    if template_source in {"generic_solar", "generic_wind"} or project_code in {"generic_solar", "generic_wind"}:
        items.append(
            {
                "title": "Generic project path",
                "status": "EXPLORATORY / UNVALIDATED",
                "badge_class": "badge-warn",
                "detail": "Reference-status only. Synthetic reference status does not imply jurisdiction-specific or lender-grade validation.",
            }
        )
    return {
        "label": "Governance / Feature Guards",
        "items": items,
        "has_items": bool(items),
        "note": "These are platform-level limitations and review boundaries, not current-run validation errors.",
    }


def _banner_context_for_index(
    project_record,
    workspace_state,
    validation_errors: list | None = None,
) -> str | None:
    """Build a conservative banner_context for UI-2.1.

    Returns one of the supported 11 contexts, or None for "no banner".
    Uses only existing state signals, never invents new ones.

    Deterministic priority order (highest first):
    1. validation_failed - only if explicit validation_errors list non-empty
    2. stale_result - workspace_state.dirty AND last_runtime_snapshot_id
    2b. stale_scenario - active_scenario_id != last_runtime_scenario_id (R9/N03)
    3. browser_draft - dirty without runtime snapshot
    4. factory_template - project_origin is not user_created
    5. active_scenario - workspace_state has an active_scenario_id
    6. user_created_project - project_origin is user_created
    7. None - no clear state (banner not rendered)

    The function is read-only.
    """
    if validation_errors and len(validation_errors) > 0:
        return "validation_failed"
    dirty = bool(workspace_state and getattr(workspace_state, "dirty", False))
    has_runtime = bool(
        workspace_state and getattr(workspace_state, "last_runtime_snapshot_id", None)
    )
    if dirty and has_runtime:
        return "stale_result"
    if dirty and not has_runtime:
        return "browser_draft"
    # R9/N03: scenario switch without re-run — active != last-run scenario.
    # last_runtime_scenario_id is preserved across scenario switches.
    if workspace_state:
        from app.ui.dirty_state import _scenario_changed
        _active_sid = getattr(workspace_state, "active_scenario_id", None) or ""
        _last_run_sid = getattr(workspace_state, "last_runtime_scenario_id", None)  # None = never run or Base run
        _any_run = bool(getattr(workspace_state, "any_run_committed", False))
        if _scenario_changed(_active_sid, _last_run_sid, any_run_committed=_any_run):
            return "stale_result"
    is_user = bool(
        project_record and getattr(project_record, "project_origin", "") == "user_created"
    )
    has_active = bool(
        workspace_state and getattr(workspace_state, "active_scenario_id", None)
    )
    if not is_user:
        return "factory_template"
    if has_active:
        return "active_scenario"
    if is_user:
        return "user_created_project"
    return None


def _build_export_lineage_ui_context(project_record, workspace_state, export_lineage: list[dict[str, object]]) -> dict[str, object]:
    workspace_meta = _workspace_state_meta(workspace_state)
    project_label = project_record.project_name if project_record else "Workspace Project"
    project_code = project_record.project_code.upper() if project_record else "GENERAL"
    runtime_snapshot_id = workspace_state.last_runtime_snapshot_id if workspace_state else ""
    runtime_generated_at = _format_ui_timestamp(workspace_state.last_runtime_at if workspace_state else None)
    scenario_revision = _format_ui_timestamp(workspace_state.updated_at if workspace_state else None)
    # R9/N03: detect scenario-switch stale (active != last-run scenario)
    _active_sid = (workspace_state.active_scenario_id or "") if workspace_state else ""
    _active_sname = (workspace_state.active_scenario_name or "") if workspace_state else ""
    _last_run_sid = workspace_meta.get("last_runtime_scenario_id") if workspace_meta else None  # None = never run or Base
    _any_run = bool(workspace_meta.get("any_run_committed", False)) if workspace_meta else False
    from app.ui.dirty_state import _scenario_changed as _sc_changed
    _scenario_stale = _sc_changed(_active_sid, _last_run_sid, any_run_committed=_any_run)
    action_note = (
        "Unsaved draft edits are active. Exports remain descriptive only, and runtime-backed artifacts stay tied to the last clean backend snapshot until you save and run again."
        if workspace_meta["dirty"]
        else (
            "Active scenario changed since last Run. Exports reflect current saved inputs for the active scenario but the persisted runtime was produced under a different scenario. Re-run to align lineage."
            if _scenario_stale
            else "Draft and saved state are aligned. Runtime-backed exports reflect the last clean backend snapshot shown in the runtime summary."
        )
    )
    current_context = {
        "project_label": project_label,
        "project_code": project_code,
        "active_scenario_name": _active_sname or "Workspace Base",
        "active_scenario_id": _active_sid or "not_applicable",
        "last_runtime_scenario_id": _last_run_sid or "not_applicable",
        "scenario_lineage_stale": _scenario_stale,
        "scenario_revision": scenario_revision,
        "runtime_snapshot_id": runtime_snapshot_id or "unavailable",
        "runtime_generated_at": runtime_generated_at,
        "runtime_origin_label": workspace_meta["last_runtime_origin_label"],
        "dirty": workspace_meta["dirty"],
        "dirty_label": workspace_meta["dirty_label"],
        "governance_summary": "G20 remains BLOCKED; R99/R102 remain NOT APPROVED.",
        "action_note": action_note,
    }
    action_cards = [
        {
            "artifact_name": "Values-only Excel export",
            "artifact_type": "excel_model_export",
            "href": "/download",
            "represents": "Submitted form values plus descriptive provenance and reviewer notes.",
            "authority_note": "Descriptive only. This workbook is backend-authored and does not become the calculation engine.",
            "availability_note": (
                "Dirty draft is allowed here because the export reflects submitted workbook values, not a hidden runtime promotion."
                if workspace_meta["dirty"]
                else "Available from the current submitted form state."
            ),
        },
        {
            "artifact_name": "Runtime summary CSV",
            "artifact_type": "runtime_summary_csv",
            "href": f"/exports/runtime-summary.csv?project={project_record.project_code if project_record else 'generic_wind_reference'}",
            "represents": "Backend runtime metrics and provenance for the active project.",
            "authority_note": "Descriptive only. Reviewer should treat it as a record of backend runtime output, not as a live browser calculation.",
            "availability_note": (
                "Current draft is newer than the last runtime snapshot. Save and run again if you need export lineage to match the current draft."
                if workspace_meta["dirty"]
                else "Uses the last clean backend runtime context for the active project."
            ),
        },
        {
            "artifact_name": "Institutional workbook",
            "artifact_type": "institutional_workbook",
            "href": f"/exports/institutional-workbook.xlsx?project={project_record.project_code if project_record else 'generic_wind_reference'}",
            "represents": "Reviewer-facing workbook with runtime summary, provenance, cover notes, and governance context.",
            "authority_note": "Descriptive only. Numeric sheets remain tied to backend runtime/export behavior and do not override runtime authority.",
            "availability_note": (
                "Current draft is newer than the last runtime snapshot. Save and run again before sharing if the reviewer needs the latest draft reflected in runtime-backed sections."
                if workspace_meta["dirty"]
                else "Uses the last clean backend runtime context for the active project."
            ),
        },
    ]
    recent_exports = []
    for item in export_lineage:
        replay_metadata = item.get("replay_metadata", {}) if isinstance(item, dict) else {}
        recent_exports.append(
            {
                "artifact_name": item.get("artifact_name", "Export artifact"),
                "export_type": item.get("export_type", "unknown"),
                "scenario_name": item.get("scenario_name", "Workspace export"),
                "created_at": _format_ui_timestamp(item.get("created_at")),
                "scenario_id": replay_metadata.get("scenario_id") or "not_applicable",
                "scenario_revision": replay_metadata.get("scenario_revision") or "unavailable",
                "runtime_snapshot_id": replay_metadata.get("runtime_snapshot_id") or "unavailable",
                "runtime_origin": replay_metadata.get("runtime_origin") or "unavailable",
                "runtime_generated_at": replay_metadata.get("runtime_timestamp") or "unavailable",
                "export_generated_at": replay_metadata.get("export_timestamp") or _format_ui_timestamp(item.get("created_at")),
                "branch_name": replay_metadata.get("branch_name") or "unavailable",
                "commit_sha": replay_metadata.get("commit_sha") or "unavailable",
                "template_origin": replay_metadata.get("template_origin") or "unavailable",
                "runtime_flag_count": replay_metadata.get("runtime_flag_count") or "unavailable",
                "governance_summary": (
                    f"{item.get('governance_state', {}).get('g20_status', 'BLOCKED')} / "
                    f"{item.get('governance_state', {}).get('r99_r102_status', 'NOT APPROVED')}"
                ),
            }
        )
    return {
        "current_context": current_context,
        "action_cards": action_cards,
        "recent_exports": recent_exports,
    }


def _format_compare_value(value) -> str:
    if value in (None, "", "NOT_AVAILABLE"):
        return "pending / unavailable"
    return str(value)


def _format_compare_delta(value) -> str:
    if value is None:
        return "not_applicable"
    return str(value)


def _build_compare_ui_context(compare_result: dict, workspace_state) -> dict:
    workspace_meta = _workspace_state_meta(workspace_state)
    left = compare_result["left"]
    right = compare_result["right"]
    compare_metrics = []
    for row in compare_result["metrics"]:
        compare_metrics.append(
            {
                "metric": row["metric"],
                "left_value": _format_compare_value(row["left_value"]),
                "right_value": _format_compare_value(row["right_value"]),
                "delta": _format_compare_delta(row["delta"]),
            }
        )

    left_replay = dict(left.replay_metadata or {})
    right_replay = dict(right.replay_metadata or {})
    dirty_note = (
        "Current workspace draft has unsaved edits. Those browser-side edits are not part of this comparison; the compare panel only reflects saved scenario snapshots and saved runtime summaries."
        if workspace_meta["dirty"]
        else "Current workspace draft is aligned to the saved boundary, so this comparison is reading saved scenario snapshots without hidden draft drift."
    )
    return {
        "left": left,
        "right": right,
        "metrics": compare_metrics,
        "governance_rows": compare_result["governance_rows"],
        "compare_generated_at": utc_now_iso(),
        "dirty_note": dirty_note,
        "left_context": {
            "scenario_timestamp": _format_ui_timestamp(left.updated_at),
            "runtime_timestamp": left_replay.get("runtime_timestamp") or "unavailable",
            "runtime_snapshot_id": left_replay.get("runtime_snapshot_id") or "unavailable",
            "runtime_origin": left_replay.get("runtime_origin") or "not_applicable",
            "source_label": "saved scenario snapshot with saved runtime summary",
        },
        "right_context": {
            "scenario_timestamp": _format_ui_timestamp(right.updated_at),
            "runtime_timestamp": right_replay.get("runtime_timestamp") or "unavailable",
            "runtime_snapshot_id": right_replay.get("runtime_snapshot_id") or "unavailable",
            "runtime_origin": right_replay.get("runtime_origin") or "not_applicable",
            "source_label": "saved scenario snapshot with saved runtime summary",
        },
        "workspace_dirty": workspace_meta["dirty"],
        "workspace_runtime_origin_label": workspace_meta["last_runtime_origin_label"],
        "governance_summary": "G20 remains BLOCKED. R99/R102 remain NOT APPROVED. Accepted conventions remain explanatory only.",
        "missing_metric_note": "Pending, unavailable, and not_applicable markers are intentional. They do not mean zero unless the source value is actually zero.",
    }


def _replay_metadata_for_project(
    project_code: str,
    *,
    export_type: str | None = None,
    workbook_type: str | None = None,
    export_timestamp: str | None = None,
    runtime_timestamp: str | None = None,
    project_id: str | None = None,
    scenario_id: str | None = None,
    scenario_name: str | None = None,
    scenario_revision: str | None = None,
    runtime_snapshot_id: str | None = None,
    runtime_origin: str | None = None,
    artifact_name: str | None = None,
    project_inputs_override=None,
    template_origin_override: str | None = None,
    baseline_source: bool | None = None,
    active_scenario_id: str | None = None,
    active_scenario_name: str | None = None,
    scenario_provenance: dict | None = None,
    warning_note: str | None = None,
) -> dict:
    project_inputs = project_inputs_override or _project_inputs_for_code(project_code)
    governance_state = _governance_snapshot(project_code)
    replay_metadata = build_replay_metadata(
        project_key=project_code,
        project_inputs=project_inputs,
        governance_state=governance_state,
        project_id=project_id,
        scenario_id=scenario_id,
        scenario_name=scenario_name,
        scenario_revision=scenario_revision,
        runtime_timestamp=runtime_timestamp,
        export_timestamp=export_timestamp,
        runtime_snapshot_id=runtime_snapshot_id,
        runtime_origin=runtime_origin,
        artifact_name=artifact_name,
        export_type=export_type,
        workbook_type=workbook_type,
        active_project=project_code,
    )
    if template_origin_override:
        replay_metadata["template_origin"] = template_origin_override
    if baseline_source is not None:
        replay_metadata["baseline_source"] = baseline_source
    replay_metadata["active_scenario_id"] = active_scenario_id or replay_metadata.get("scenario_id") or "not_applicable"
    replay_metadata["active_scenario_name"] = active_scenario_name or replay_metadata.get("scenario_name") or "not_applicable"
    if scenario_provenance:
        replay_metadata.update(scenario_provenance)
        replay_metadata["active_scenario_id"] = scenario_provenance.get("scenario_id") or replay_metadata["active_scenario_id"]
        replay_metadata["active_scenario_name"] = scenario_provenance.get("scenario_name") or replay_metadata["active_scenario_name"]
    if warning_note:
        replay_metadata["warning_note"] = warning_note
    return replay_metadata


_SIDEBAR_RECENT_LIMIT = 8  # Project Library: cap sidebar recent-project list


def _user_project_selector_items(user) -> list[dict[str, str]]:
    """Return up to _SIDEBAR_RECENT_LIMIT most-recent user-owned projects for the sidebar.

    Does not include reference projects (those live in the full project library).
    """
    from app.persistence.projects_repository import list_recent_projects
    items = []
    for record in list_recent_projects(user.user_id, limit=_SIDEBAR_RECENT_LIMIT):
        if record.project_origin not in ("user_created", "saved_baseline"):
            continue
        role_label = ""
        if record.project_role == "working_copy":
            role_label = " · Copy"
        items.append(
            {
                "project_code": record.project_code,
                "label": record.project_name,
                "meta": f"{record.project_type or 'Unknown'}{role_label}",
            }
        )
    return items


def _consolidated_project_records(user) -> list[dict[str, str]]:
    """Phase P2-FIX-1: single project list (presentation only).

    Returns ALL projects visible to this user as a single
    list: factory fixtures (Generic Wind Reference Wind, Generic Solar Reference Solar PV)
    plus user_created projects. No "Factory Templates" /
    "Saved Baselines" / "My Projects" split in the UI.
    Origin distinction lives in the data model, not in
    the rendered visible text.

    The list is deduped by ``project_code`` and ordered
    with reference projects first (Generic Wind Reference Wind, Generic Solar Reference
    Solar PV), then user_created projects alphabetically.
    """
    seen: set[str] = set()
    items: list[dict[str, str]] = []
    for opt in FACTORY_TEMPLATE_OPTIONS:
        code = opt["project_code"]
        if code in seen:
            continue
        seen.add(code)
        items.append(
            {
                "project_code": code,
                "label": opt["label"],
                "meta": opt.get("meta", ""),
                "project_type": opt.get("project_type", ""),
                "origin_class": "project",
            }
        )
    for record in list_project_records(user_id=user.user_id):
        if record.project_origin != "user_created":
            continue
        if record.project_code in seen:
            continue
        seen.add(record.project_code)
        items.append(
            {
                "project_code": record.project_code,
                "label": record.project_name,
                # Phase P2-FIX-5E: drop the 'seed' suffix
                # from user-facing meta line.
                "meta": f"{record.project_type or 'Unknown'}",
                "project_type": record.project_type or "",
                "origin_class": "project",
            }
        )
    items.sort(
        key=lambda it: (
            0 if it["project_code"] in {"generic_wind_reference", "generic_solar_reference", "generic_storage_reference", "generic_data_center_reference", "generic_ev_charging_reference"} else 1,            it["label"].lower(),
        )
    )
    return items


def _project_validation_badge(template_source: str) -> dict[str, str]:
    """Map a template_source (e.g. generic_wind_reference/generic_solar_reference/generic_solar/generic_wind)
    to a user-facing validation tier label + tone for the project browser
    card. Presentation-only -- does not call any engine or validation
    logic, just labels the existing static classification."""
    status = get_validation_status(template_source or "")
    return {"label": status.tier_label, "tone": status.tier_tone}


def _my_project_card(record) -> dict[str, str]:
    snapshot = record.baseline_snapshot or {}
    return {
        "project_code": record.project_code,
        "name": record.project_name,
        "project_type": record.project_type or "",
        "country": snapshot.get("country_market", "") or "",
        "capacity_mw": snapshot.get("capacity_mw", "") or "",
        "last_saved": _format_ui_timestamp(getattr(record, "updated_at", None)),
        "validation": _project_validation_badge(record.template_source or ""),
    }


def _my_project_cards(user) -> list[dict[str, str]]:
    """U3-SAVED-PROJECT-FLOW-CLEANUP: 'My Projects' cards for the project
    browser. User-created projects only, most-recently-saved first."""
    records = [
        r for r in list_project_records(user_id=user.user_id)
        if r.project_origin == "user_created"
    ]
    records.sort(
        key=lambda r: getattr(r, "updated_at", None).timestamp() if getattr(r, "updated_at", None) else 0,
        reverse=True,
    )
    return [_my_project_card(r) for r in records]


def _example_project_cards() -> list[dict[str, str]]:
    """U3-SAVED-PROJECT-FLOW-CLEANUP: 'Example Projects' cards for the
    project browser. Static reference projects (Generic Wind Reference / Generic Solar Reference) -- always
    available, not user-saved, shown separately from My Projects."""
    cards = []
    for opt in FACTORY_TEMPLATE_OPTIONS:
        capacity_mw, _, country = opt.get("meta", "").partition(" MW · ")
        cards.append(
            {
                "project_code": opt["project_code"],
                "name": opt["label"],
                "project_type": opt.get("project_type", ""),
                "country": country.strip(),
                "capacity_mw": capacity_mw.strip(),
                "last_saved": "",
                "validation": _project_validation_badge(opt.get("project_code", "")),
            }
        )
    return cards


def _resolve_project_record(user, project_selection: str | None, form_snapshot: dict | None = None):
    selection = (project_selection or "").strip().lower()
    if selection:
        user_project = get_project_record(user_id=user.user_id, project_code=selection)
        if user_project is not None:
            return user_project

    if selection in {"generic_wind_reference", "generic_solar_reference", "generic_storage_reference", "generic_data_center_reference", "generic_ev_charging_reference", "generic_wind", "generic_solar", "generic_storage", "generic_data_center", "generic_ev_charging"}:
        project_code = selection
        project_name = _project_identity_from_template_source(selection)[1]
        if selection in {"generic_solar_reference", "generic_solar"}:
            project_type = "Solar"
        elif selection in {"generic_data_center_reference", "generic_data_center"}:
            project_type = "Data Center"
        elif selection in {"generic_ev_charging_reference", "generic_ev_charging"}:
            project_type = "EV Charging"
        else:
            project_type = "Wind"
        template_source = selection
    else:
        project_code, project_name = _project_persistence_metadata(None, form_snapshot)
        project_type = _canonical_project_type((form_snapshot or {}).get("project_type"))
        template_source = _normalize_template_source(project_code, project_type)

    return save_project(
        user_id=user.user_id,
        project_code=project_code,
        project_name=project_name,
        project_type=project_type,
        project_origin="factory_template",
        source_project_template=template_source,
        template_source=template_source,
        baseline_snapshot=_default_workspace_snapshot(project_code),
        governance_state=_governance_snapshot(project_code),
        last_run_summary={},
        replay_metadata=_replay_metadata_for_project(
            project_code,
            project_id=None,
            export_type="workspace_project_state",
        ),
    )


def _ensure_workspace_for_project(user, project_record):
    workspace_state = get_workspace_state(user.user_id, project_record.project_id)
    if workspace_state is None:
        base_snapshot = project_record.baseline_snapshot or _default_workspace_snapshot(project_record.project_code)
        base_snapshot = dict(base_snapshot)
        base_snapshot["active_project"] = project_record.project_code
        base_snapshot["project_type"] = project_record.project_type or base_snapshot.get("project_type") or "Wind"
        workspace_state = save_workspace_state(
            user_id=user.user_id,
            project_id=project_record.project_id,
            project_code=project_record.project_code,
            draft_snapshot=base_snapshot,
            saved_snapshot=base_snapshot,
            dirty=False,
            governance_state=_governance_snapshot(project_record.project_code),
            replay_metadata=_replay_metadata_for_project(
                project_record.project_code,
                project_id=project_record.project_id,
                export_type="workspace_draft_state",
            ),
        )
    return workspace_state


def _project_workspace_from_snapshot(user, snapshot: dict):
    project_record = _resolve_project_record(user, snapshot.get("active_project"), snapshot)
    workspace_state = _ensure_workspace_for_project(user, project_record)
    return project_record, workspace_state


def _template_origin_for_record(project_record) -> str:
    template_seed = _normalize_template_source(
        project_record.template_source or project_record.source_project_template,
        project_record.project_type,
    )
    return f"project_factory:{(template_seed or project_record.project_code or 'unknown').lower()}"


def _scenario_provenance_for_record(project_record, scenario_record):
    # Phase 50B: implementation moved to scenario_state_service.scenario_provenance_for_record
    return scenario_provenance_for_record(project_record, scenario_record)


def _resolve_runtime_snapshot_source(user, project_record, workspace_state, runtime_origin: str) -> tuple[dict, object | None, str | None, str]:
    """Thin backward-compatible wrapper around scenario_state_service.resolve_runtime_snapshot.

    Phase 50C-2: Canonical implementation moved to resolve_runtime_snapshot().
    This wrapper preserves the old tuple-return API at existing call sites.
    """
    result = resolve_runtime_snapshot(
        user=user,
        project_record=project_record,
        workspace_state=workspace_state,
        runtime_origin=runtime_origin,
    )
    return (
        result.snapshot,
        result.scenario_record,
        result.warning,
        result.effective_runtime_origin,
    )


def _clean_user_project_runtime_snapshot(
    user, project_record, workspace_state, runtime_origin: str
) -> dict:
    """Return the clean backend-authored runtime snapshot for a
    user_created project used by the /save-run user_created branch.

    Phase 51G-3 bugfix: prior to this, the /save-run user_created
    branch referenced this function by name but it was never defined,
    causing a NameError that the broad ``except Exception`` caught and
    surfaced as a 200 + save_result-err with message
    "Model error: name '_clean_user_project_runtime_snapshot' is not
    defined". This is the canonical adapter that delegates to
    ``_resolve_runtime_snapshot_source`` and returns only the snapshot
    dict that ``build_projectinputs_from_snapshot`` consumes.

    The runtime snapshot here is the same one the /run user_created
    path uses (Phase 17C snapshot binding): it is the resolved
    clean snapshot (workspace saved_snapshot when present, otherwise
    project baseline_snapshot), augmented with project-identifying
    fields (project_name, project_type, project_origin,
    template_source, active_project) by the underlying
    ``resolve_runtime_snapshot`` function. No form data is folded in
    here — the form-driven field set is collected separately in the
    service when the snapshot does not yet contain the necessary
    keys, but for /save-run the user_created project must already
    have a complete baseline_snapshot (created at project creation
    time via ``_apply_new_project_required_inputs``). If the snapshot
    is missing a required field, ``build_projectinputs_from_snapshot``
    raises ``SnapshotInputError`` and the service surfaces that as
    a 200 + save_result-err with a clear validation message — not
    as a NameError.
    """
    snapshot, _scenario_record, _warning, _effective_origin = (
        _resolve_runtime_snapshot_source(
            user=user,
            project_record=project_record,
            workspace_state=workspace_state,
            runtime_origin=runtime_origin,
        )
    )
    return dict(snapshot or {})


def _current_project_workspace(user, project_record):
    workspace_state = _ensure_workspace_for_project(user, project_record)
    scenarios = list_scenarios(user.user_id, project_id=project_record.project_id, include_archived=False, limit=12)
    history = get_scenario_history(user.user_id, project_id=project_record.project_id, limit=20)
    exports = list_exports(user.user_id, project_id=project_record.project_id, limit=8)
    export_lineage = build_export_lineage(user.user_id, project_id=project_record.project_id, limit=8)
    scenario_summary_cards = []
    export_counts: dict[str, int] = {}
    for entry in export_lineage:
        export_counts[entry["scenario_name"]] = export_counts.get(entry["scenario_name"], 0) + 1
    is_user_project_flag = project_record.project_origin == "user_created"
    template_source_str = (project_record.template_source or "").strip().lower()
    for item in scenarios:
        summary = item.last_run_summary or {}
        # Phase 25B-3 — read the previous run summary that
        # update_scenario_last_run_summary() preserves in replay_metadata
        # before the new last_run_summary overwrites it.
        previous_summary = (item.replay_metadata or {}).get("previous_run_summary") or {}
        card = {
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
            "previous_run_summary": previous_summary,
            "is_user_project": is_user_project_flag,
            "template_source": template_source_str,
        }
        # Enrich with delta panel rows (pure helper, no I/O)
        card = build_scenario_card_deltas(card)
        scenario_summary_cards.append(card)
    return project_record, workspace_state, scenarios, history, exports, export_lineage, scenario_summary_cards


def _render_scenario_workspace(
    request: Request,
    user,
    project_record,
    workspace_state,
    scenarios,
    history,
    exports,
    export_lineage,
    scenario_summary_cards,
    message: str | None = None,
    compare_result: dict | None = None,
    multi_compare_result: dict | None = None,
    multi_compare_error: str | None = None,
    multi_compare_parsed_ids: list | None = None,
    dirty_state_ui: dict | None = None,
    scenario_workflow_ui: dict | None = None,
    project_review_ui: dict | None = None,
    # V4-2 Part B
    input_diff_result: dict | None = None,
    input_diff_error: str | None = None,
    # V4-2 Part D
    fs_compare_result: dict | None = None,
    fs_compare_error: str | None = None,
    # V4-3
    sensitivity_result: dict | None = None,
    sensitivity_error: str | None = None,
    sensitivity_extra: dict | None = None,
    # V4-4
    lender_case_result: dict | None = None,
    lender_case_error: str | None = None,
    lender_base_kpis: dict | None = None,
    lender_scenario_name: str | None = None,
    covenant_periods: list | None = None,
    covenant_error: str | None = None,
    covenant_thresholds: dict | None = None,
    credit_summary: dict | None = None,
    credit_summary_error: str | None = None,
    # V4-5
    exec_summary: dict | None = None,
    exec_summary_error: str | None = None,
    ic_pack: dict | None = None,
    ic_pack_error: str | None = None,
    credit_pack: dict | None = None,
    credit_pack_error: str | None = None,
    # V4-7
    bess_revenue: dict | None = None,
    bess_revenue_error: str | None = None,
    bess_asset: dict | None = None,
    bess_asset_error: str | None = None,
):
    # Phase 25B-6 — defensive default for runtime_summary
    # (used by project_review_ui when not pre-populated).
    runtime_summary = _runtime_summary_for_index(workspace_state)
    if dirty_state_ui is None:
        # Phase 25B-4 — defensive default.
        from app.ui.dirty_state import build_dirty_state_ui
        workspace_meta = _workspace_state_meta(workspace_state)
        dirty_state_ui = build_dirty_state_ui(
            dirty=bool(workspace_meta.get("dirty", False)),
            has_runtime_snapshot=bool(workspace_meta.get("last_runtime_snapshot_id", "")),
            is_user_project=project_record.project_origin == "user_created",
            active_scenario_id=workspace_meta.get("active_scenario_id", "") or "",
            last_runtime_scenario_id=workspace_meta.get("last_runtime_scenario_id"),  # None = never run
            any_run_committed=bool(workspace_meta.get("any_run_committed", False)),
            scenarios=[
                {"scenario_id": c.get("scenario_id"), "scenario_name": c.get("scenario_name")}
                for c in (scenario_summary_cards or [])
            ],
        )
    if scenario_workflow_ui is None:
        # Phase 25B-5 — defensive default.
        from app.ui.scenario_workflow import build_scenario_workflow_ui
        scenario_workflow_ui = build_scenario_workflow_ui(
            cards=list(scenario_summary_cards or []),
            active_scenario_id=(
                str(getattr(workspace_state, "active_scenario_id", "") or "")
                if workspace_state is not None
                else ""
            ),
            project_code=getattr(project_record, "project_code", "") or "",
        )
    if project_review_ui is None:
        # Phase 25B-6 — defensive default.
        from app.ui.project_review import build_project_review_ui
        project_review_ui = build_project_review_ui(
            project_ctx=project_record,
            last_run_summary=runtime_summary,
        )
    if dirty_state_ui is None:
        # Phase 25B-4 — defensive default. _workspace_refresh_payload
        # should always populate this, but a None here keeps the
        # workspace renderable when called from older code paths.
        from app.ui.dirty_state import build_dirty_state_ui
        workspace_meta = _workspace_state_meta(workspace_state)
        dirty_state_ui = build_dirty_state_ui(
            dirty=bool(workspace_meta.get("dirty", False)),
            has_runtime_snapshot=bool(workspace_meta.get("last_runtime_snapshot_id", "")),
            is_user_project=project_record.project_origin == "user_created",
            active_scenario_id=workspace_meta.get("active_scenario_id", "") or "",
            last_runtime_scenario_id=workspace_meta.get("last_runtime_scenario_id"),  # None = never run
            any_run_committed=bool(workspace_meta.get("any_run_committed", False)),
            scenarios=[
                {"scenario_id": c.get("scenario_id"), "scenario_name": c.get("scenario_name")}
                for c in (scenario_summary_cards or [])
            ],
        )
    if scenario_workflow_ui is None:
        # Phase 25B-5 — defensive default. _workspace_refresh_payload
        # populates this in the canonical path; older callers that
        # still return 5-tuples from _current_project_workspace get
        # a fresh workflow UI here so the template never breaks.
        from app.ui.scenario_workflow import build_scenario_workflow_ui
        scenario_workflow_ui = build_scenario_workflow_ui(
            cards=list(scenario_summary_cards or []),
            active_scenario_id=(
                str(getattr(workspace_state, "active_scenario_id", "") or "")
                if workspace_state is not None
                else ""
            ),
            project_code=getattr(project_record, "project_code", "") or "",
        )
    # Build lightweight KPI context for the chrome strip.
    from app.ui.dashboard import build_dashboard_kpis as _build_kpis
    _last_rs = getattr(workspace_state, "last_runtime_summary", None) if workspace_state else None
    _dash_kpis = _build_kpis(
        last_runtime_summary=_last_rs,
        project_record=project_record,
        realized_gearing_pct=None,
    )
    _ws_meta = _workspace_state_meta(workspace_state)

    return templates.TemplateResponse(
        request=request,
        name="scenarios_page.html",
        context={
            "user": user,
            "project_record": project_record,
            "workspace_state": workspace_state,
            "workspace_state_meta": _ws_meta,
            # Chrome context — KPI strip and sheet tabs
            "dashboard_kpis": _dash_kpis,
            "dirty": _ws_meta.get("dirty", False),
            "factory_template_projects": FACTORY_TEMPLATE_OPTIONS,
            "user_project_records": _user_project_selector_items(user),
            "active_project_code": getattr(project_record, "project_code", ""),
            "scenario_records": scenarios,
            "scenario_history": history,
            "export_records": exports,
            "export_lineage": export_lineage,
            "export_lineage_ui": _build_export_lineage_ui_context(project_record, workspace_state, export_lineage),
            "scenario_summary_cards": scenario_summary_cards,
            "workspace_message": message,
            "compare_result": compare_result,
            "multi_compare_result": multi_compare_result,
            "multi_compare_error": multi_compare_error,
            "multi_compare_parsed_ids": multi_compare_parsed_ids or [],
            "is_user_project": project_record.project_origin == "user_created",
            # Phase 24-H: exploratory warning flag (user_created + generic)
            "is_exploratory_project": (
                project_record.project_origin == "user_created"
                and (project_record.template_source or "").strip().lower()
                in {"generic_solar", "generic_wind"}
            ),
            # Phase 25B-6 — runtime summary (used by
            # project review card + debt DSCR/SHL panel)
            "runtime_summary": runtime_summary,
            # Phase 25B-4 — visual dirty-state UI payload
            "dirty_state_ui": dirty_state_ui,
            # Phase 25B-5 — scenario workflow polish UI payload
            "scenario_workflow_ui": scenario_workflow_ui,
            # Phase 25B-6: Generic project review pack (read-only UI payload)
            "project_review_ui": project_review_ui,
            # Phase P2-FIX-2: Audit / reviewer mode flag (default False).
            "audit_mode": False,
            # V4-2: input diff and FS compare
            "input_diff_result": input_diff_result,
            "input_diff_error": input_diff_error,
            "fs_compare_result": fs_compare_result,
            "fs_compare_error": fs_compare_error,
            # V4-3: sensitivity
            "sensitivity_result": sensitivity_result,
            "sensitivity_error": sensitivity_error,
            **(sensitivity_extra or {}),
            # V4-4: lender case, covenant, credit summary
            "lender_case_result": lender_case_result,
            "lender_case_error": lender_case_error,
            "lender_base_kpis": lender_base_kpis,
            "lender_scenario_name": lender_scenario_name or "",
            "covenant_periods": covenant_periods,
            "covenant_error": covenant_error,
            "covenant_thresholds": covenant_thresholds or {
                "event_of_default": 1.05,
                "lockup": 1.10,
                "distribution": 1.15,
                "cash_sweep": 1.20,
            },
            "credit_summary": credit_summary,
            "credit_summary_error": credit_summary_error,
            # V4-5: IC / credit reporting pack
            "exec_summary": exec_summary,
            "exec_summary_error": exec_summary_error,
            "ic_pack": ic_pack,
            "ic_pack_error": ic_pack_error,
            "credit_pack": credit_pack,
            "credit_pack_error": credit_pack_error,
            "bess_revenue": bess_revenue,
            "bess_revenue_error": bess_revenue_error,
            "bess_asset": bess_asset,
            "bess_asset_error": bess_asset_error,
        },
    )


def _workspace_refresh_payload(user, project_record, workspace_state=None):
    # Phase 25B-6 — build the runtime_summary dict
    # once so the project_review_ui payload has
    # access to it.
    runtime_summary = _runtime_summary_for_index(workspace_state)
    scenarios = list_scenarios(user.user_id, project_id=project_record.project_id, include_archived=False, limit=12)
    history = get_scenario_history(user.user_id, project_id=project_record.project_id, limit=20)
    exports = list_exports(user.user_id, project_id=project_record.project_id, limit=8)
    export_lineage = build_export_lineage(user.user_id, project_id=project_record.project_id, limit=8)
    export_counts = {}
    for entry in export_lineage:
        export_counts[entry["scenario_name"]] = export_counts.get(entry["scenario_name"], 0) + 1
    scenario_summary_cards = []
    is_user_project_flag = project_record.project_origin == "user_created"
    template_source_str = (project_record.template_source or "").strip().lower()
    for item in scenarios:
        summary = item.last_run_summary or {}
        previous_summary = (item.replay_metadata or {}).get("previous_run_summary") or {}
        card = {
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
            "previous_run_summary": previous_summary,
            "is_user_project": is_user_project_flag,
            "template_source": template_source_str,
        }
        card = build_scenario_card_deltas(card)
        scenario_summary_cards.append(card)

    # Phase 25B-4 — build the dirty-state UI payload (visual only).
    # Pure helper, no DB, no I/O.
    workspace_meta_for_ds = _workspace_state_meta(workspace_state)
    has_runtime_snapshot = bool(
        workspace_meta_for_ds.get("last_runtime_snapshot_id", "")
    )
    is_user_project = (
        getattr(project_record, "project_origin", "") == "user_created"
    )
    active_scenario_id = (
        workspace_meta_for_ds.get("active_scenario_id", "") or ""
    )
    dot_input_scenarios = [
        {
            "scenario_id": c.get("scenario_id"),
            "scenario_name": c.get("scenario_name"),
        }
        for c in (scenario_summary_cards or [])
    ]
    dirty_state_ui = build_dirty_state_ui(
        dirty=bool(workspace_meta_for_ds.get("dirty", False)),
        has_runtime_snapshot=has_runtime_snapshot,
        is_user_project=is_user_project,
        active_scenario_id=active_scenario_id,
        last_runtime_scenario_id=workspace_meta_for_ds.get("last_runtime_scenario_id"),  # None = never run
        any_run_committed=bool(workspace_meta_for_ds.get("any_run_committed", False)),
        scenarios=dot_input_scenarios,
    )

    # Phase 25B-5 — build the scenario workflow polish UI payload.
    active_sid_for_workflow = ""
    if workspace_state is not None and getattr(
        workspace_state, "active_scenario_id", None
    ):
        active_sid_for_workflow = str(workspace_state.active_scenario_id)
    elif hasattr(project_record, "_workspace_state") and getattr(
        project_record, "_workspace_state", None
    ) is not None:
        active_sid_for_workflow = str(
            getattr(project_record._workspace_state, "active_scenario_id", "") or ""
        )
    scenario_workflow_ui = build_scenario_workflow_ui(
        cards=scenario_summary_cards,
        active_scenario_id=active_sid_for_workflow,
        project_code=getattr(project_record, "project_code", "") or "",
    )

    # Phase 25B-6 — build the project review pack UI payload.
    # Pure helper, no DB, no I/O. Returns the review
    # sections (assumptions / KPIs / scenarios /
    # exploratory notes / known exclusions) keyed
    # by project context.
    project_review_ui = build_project_review_ui(
        project_ctx=project_record,
        last_run_summary=runtime_summary,
    )

    return (
        scenarios,
        history,
        exports,
        export_lineage,
        scenario_summary_cards,
        dirty_state_ui,
        scenario_workflow_ui,
        project_review_ui,
    )
# -- Helpers ------------------------------------------------------------------

def _build_schema_from_form(
    project_type: str,
    scenario: str,
    capacity_mw: Optional[str] = None,
    tariff_eur_mwh: Optional[str] = None,
    p50_hours: Optional[str] = None,
    total_capex_keur: Optional[str] = None,
    opex_y1_keur: Optional[str] = None,
    gearing_pct: Optional[str] = None,
    target_dscr: Optional[str] = None,
    interest_rate_pct: Optional[str] = None,
    tenor_years: Optional[str] = None,
    cod_date: Optional[str] = None,
    construction_months: Optional[str] = None,
    horizon_years: Optional[str] = None,
    ppa_term_years_form: Optional[str] = None,
) -> ProjectInputsSchema:
    """Build ProjectInputsSchema from form fields.

    Blank optional fields -> None -> factory defaults preserved.
    Raises ValueError for invalid numeric values.

    Phase PR1: the four timing fields
    (cod_date, construction_months,
    horizon_years, ppa_term_years) are now
    carried into the ProjectInputsSchema
    directly. This eliminates the silent
    template-default drift between Path A
    (form -> snapshot, used by
    /projects/create) and Path B
    (form -> schema, used by
    compare_service, download_service,
    run_service). The two paths now
    produce identical ProjectInputs for
    identical form inputs.

    The four new kwargs are all optional
    with default None. Callers that do not
    pass them get the same behaviour as
    before PR1 (factory defaults preserved).

    ``ppa_term_years_form`` is the form-side
    name (to avoid colliding with the
    nested ``RevenueInput.ppa_term_years``
    in case the legacy caller passed the
    nested one). The form name in the
    create form is ``ppa_term_years``.
    """
    def _float(val: Optional[str]) -> Optional[float]:
        if val is None or val.strip() == "":
            return None
        f = float(val)
        if f < 0:
            raise ValueError(f"{val} must be non-negative")
        return f

    def _int(val: Optional[str]) -> Optional[int]:
        if val is None or val.strip() == "":
            return None
        i = int(float(val))
        if i < 0:
            raise ValueError(f"{val} must be non-negative")
        return i

    revenue = None
    if tariff_eur_mwh or p50_hours or ppa_term_years_form:
        revenue = RevenueInput(
            tariff_eur_mwh=_float(tariff_eur_mwh),
            p50_hours=_float(p50_hours),
            ppa_term_years=_int(ppa_term_years_form) if ppa_term_years_form else None,
        )

    capex = None
    if total_capex_keur:
        capex = CapexInput(total_capex_keur=_float(total_capex_keur))

    opex = None
    if opex_y1_keur:
        opex = OpexInput(opex_y1_keur=_float(opex_y1_keur))

    debt = None
    if any([gearing_pct, target_dscr, interest_rate_pct, tenor_years]):
        debt = DebtInput(
            gearing_pct=_float(gearing_pct) if gearing_pct else None,
            target_dscr=_float(target_dscr) if target_dscr else None,
            interest_rate_pct=_float(interest_rate_pct) if interest_rate_pct else None,
            tenor_years=_int(tenor_years) if tenor_years else None,
        )

    return ProjectInputsSchema(
        project_type=project_type,
        scenario=scenario,
        capacity_mw=_float(capacity_mw) if capacity_mw else None,
        cod_date=(cod_date or None) if cod_date else None,
        construction_months=_int(construction_months) if construction_months else None,
        horizon_years=_int(horizon_years) if horizon_years else None,
        revenue=revenue,
        capex=capex,
        opex=opex,
        debt=debt,
    )


def _build_schema_from_form_with_timing(form_data) -> "Callable[..., ProjectInputsSchema]":
    """Return a callable that wraps
    ``_build_schema_from_form`` with the four
    timing fields already bound from
    ``form_data``.

    Phase PR1: this is the integration point
    for Path B services
    (``run_service``, ``compare_service``,
    ``download_service``,
    ``save_run_service``). The four timing
    fields (cod_date, construction_months,
    horizon_years, ppa_term_years) are
    extracted from the FastAPI form payload
    once at the route level, then bound
    into the schema-build helper via
    ``functools.partial``.

    The wrapped helper has the SAME 11-arg
    signature that Path B services already
    expect, so no service-side changes are
    needed. The four timing fields are
    forwarded transparently.

    If a form field is missing or empty
    (e.g. a service does not include the
    form's timing fields), the wrapped
    helper still works — the missing fields
    are treated as ``None`` and the schema
    falls back to factory defaults for
    those fields (preserving pre-PR1
    behaviour).
    """
    import functools
    timing = timing_fields_from_form_data(form_data)
    return functools.partial(
        _build_schema_from_form,
        cod_date=timing.get("cod_date"),
        construction_months=timing.get("construction_months"),
        horizon_years=timing.get("horizon_years"),
        ppa_term_years_form=timing.get("ppa_term_years"),
    )


def timing_fields_from_form_data(form_data) -> dict:
    """Extract the four timing fields from a
    FastAPI ``Form(...)`` flat dict (or any
    mapping). Empty / missing values map to
    ``None`` so the wrapped
    ``_build_schema_from_form`` treats them
    as "no value" and the base schema is
    preserved for that field.
    """
    def _opt(key: str):
        if form_data is None:
            return None
        v = form_data.get(key)
        if v is None:
            return None
        if isinstance(v, str) and v.strip() == "":
            return None
        return v
    return {
        "cod_date": _opt("cod_date"),
        "construction_months": _opt("construction_months"),
        "horizon_years": _opt("horizon_years"),
        "ppa_term_years": _opt("ppa_term_years"),
    }


def _validate_form(project_type: str, scenario: str, errors: list[str]) -> bool:
    """Perform basic form validation. Returns True if valid."""
    if project_type not in PROJECT_TYPES:
        errors.append(f"project_type must be one of {PROJECT_TYPES}")
    if scenario not in SCENARIOS:
        errors.append(f"scenario must be one of {SCENARIOS}")
    return len(errors) == 0


def _validate_numeric_field(name: str, val: Optional[str], max_val: Optional[float] = None):
    """Validate a numeric form field. Returns (value, error_message)."""
    if not val or val.strip() == "":
        return None, None
    try:
        f = float(val)
        if f < 0:
            return None, f"{name} must be non-negative"
        if max_val is not None and f > max_val:
            return None, f"{name} must be <= {max_val}"
        return f, None
    except ValueError:
        return None, f"{name} must be a number"


def _format_kpis(kpis: dict) -> list[dict]:
    """Convert raw KPI dict into label/value pairs for template."""
    rows = []
    for key, label in KPI_LABELS.items():
        val = kpis.get(key)
        if val is None:
            display = "-"
        elif key in ("project_irr", "equity_irr"):
            display = f"{val * 100:.2f}%"
        elif key in ("min_dscr", "avg_dscr"):
            display = f"{val:.3f}x"
        elif key in ("total_revenue_keur", "total_ebitda_keur"):
            display = f"{val:,.0f}"
        else:
            display = str(val)
        rows.append({"label": label, "key": key, "value": display})
    return rows


# -- Auth Routes --------------------------------------------------------------

def _get_client_ip(request: Request) -> str:
    """Extract client IP from request, checking X-Forwarded-For first."""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


@app.get("/login")
async def login_get(request: Request):
    """Login page."""
    user = get_current_user(request)
    if user:
        return RedirectResponse(url="/", status_code=302)

    csrf_token = generate_csrf_token()
    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={"csrf_token": csrf_token},
    )


@app.post("/login")
async def login_post(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    csrf_token: str = Form(...),
):
    """Process login. Set session cookie on success. Validates CSRF + rate limit."""
    ip = _get_client_ip(request)

    # Rate limit check
    allowed, seconds_left = _check_rate_limit(ip)
    if not allowed:
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context={
                "error": f"Too many failed attempts. Try again in {seconds_left}s.",
                "csrf_token": generate_csrf_token(),
            },
            status_code=429,
        )

    # CSRF validation
    if not validate_csrf_token(csrf_token):
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context={
                "error": "Invalid or expired form. Please try again.",
                "csrf_token": generate_csrf_token(),
            },
            status_code=403,
        )

    if verify_login(username, password):
        _clear_failed_logins(ip)
        token = create_session_token()
        cookie = make_session_cookie(token)
        response = RedirectResponse(url="/", status_code=302)
        response.set_cookie(**cookie)
        return response

    # Failed login
    _record_failed_login(ip)
    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={
            "error": "Invalid username or password.",
            "csrf_token": generate_csrf_token(),
        },
        status_code=401,
    )


@app.post("/logout")
async def logout():
    """F05 Correction A: log out of BOTH session kinds.

    A visitor may hold an admin session, a demo session, or both.  Clearing
    only the admin cookie would leave a demo cookie fully authenticated, so
    both clearing cookies are always set and /login is actually reachable."""
    response = RedirectResponse(url="/login", status_code=302)
    response.set_cookie(**clear_session_cookie())
    response.set_cookie(**clear_demo_cookie())
    return response


# -- Public Routes ------------------------------------------------------------

@app.get("/public-health")
async def public_health():
    """Public health check - no auth required. Lightweight, no auth needed."""
    return {
        "status": "ok",
        "app": "finco-protocol",
        "mode": "private-preview",
    }


@app.get("/readyz")
async def readyz():
    """Readiness check — no auth required. Lightweight diagnostics.

    Checks: app import OK, config resolved, DB path accessible, backup dir accessible.
    Does NOT trigger model run. Does NOT access scenario data.
    """
    from app.observability import get_app_health_status
    health = get_app_health_status()
    if health["status"] == "error":
        return JSONResponse(health, status_code=503)
    return JSONResponse(health)


@app.get("/health")
async def health(request: Request):
    """Private health check - requires auth."""
    user = get_current_user(request)
    if not user:
        return JSONResponse({"status": "unauthenticated", "detail": "Login required"}, status_code=401)
    return JSONResponse({"status": "ok"})


# -- Protected Routes ---------------------------------------------------------

@app.get("/")
async def index(request: Request, project: str | None = None):
    """Landing route. Requires auth. Supports protected reference and working-model project selections.

    Phase P2-FIX-1: ``GET /`` is the canonical
    Project Home URL. The legacy ``/home`` route
    redirects here (canonicalisation).

    Hotfix project-library-data-hygiene: ``GET /`` with no
    project now redirects to ``/library`` (the paginated
    Project Library) instead of rendering the legacy
    Project Home. The library is the single authoritative
    entry point for the project list (20 per page, search,
    role filter, cross-user isolation). The legacy Project
    Home and the ``/home`` redirect target are preserved for
    back-compat but are no longer reached via ``/``.

    Behaviour:
    - ``GET /`` (no project) -> 302 to ``/library``.
    - ``GET /?project=generic_wind_reference`` (or any project) opens
      that project's workspace (unchanged).
    """
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    if not (project or "").strip():
        # No project selected: render the unified Protocol home (three product
        # surfaces: Model, Radar READ-ONLY, Verify).  The paginated Project
        # Library is still reachable from the nav and from /library directly.
        return templates.TemplateResponse(
            request=request,
            name="protocol_home.html",
            context={"user": user},
        )

    project_code = (project or "").strip()
    if project_code:
        from app.utils.workbook_flag import project_workbook_url, workbook_v2_active
        if workbook_v2_active():
            return RedirectResponse(url=project_workbook_url(project_code), status_code=302)

    project_record = _resolve_project_record(user, project)
    (
        project_record,
        workspace_state,
        scenario_records,
        scenario_history,
        export_records,
        export_lineage,
        scenario_summary_cards,
    ) = _current_project_workspace(user, project_record)
    ctx = _project_record_to_context(
        project_record,
        workspace_state.draft_snapshot if workspace_state else project_record.baseline_snapshot,
    )

    # Seed baseline records if not yet present for this user
    baseline_records = seed_baseline_projects_if_needed(user.user_id)
    baseline_project_items = [
        {
            "project_code": r.project_code,
            "label": r.project_name,
            "meta": f"{r.project_type or 'Unknown'} · baseline",
            "is_readonly": r.is_readonly,
        }
        for r in list_baseline_records(user.user_id)
    ]

    # Phase 56H-1 hotfix: hoist validation_errors to a local variable
    # so that downstream helpers (_banner_context_for_index) can
    # reference it. Previously it was a dict-literal entry only, which
    # left the bare name undefined when referenced from inside the
    # same dict literal (causing NameError on GET /).
    validation_errors: list[str] = []

    _index_response = templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "project_types": PROJECT_TYPES,
            "scenarios": SCENARIOS,
            "caveats": CAVEATS,
            "form_data": workspace_state.draft_snapshot if workspace_state else project_record.baseline_snapshot or _default_workspace_snapshot(project_record.project_code),
            "validation_errors": validation_errors,
            "success_message": None,
            "user": user,
            "project_ctx": ctx,
            "workspace_state": workspace_state,
            "workspace_state_meta": _workspace_state_meta(workspace_state),
            "active_project_code": project_record.project_code,
            # Phase P2-FIX-6: C2 first-edit UX. The state
            # banner uses this flag to decide whether
            # to render the 'Create editable copy' button
            # for the active project. Only Generic Wind Reference /
            # Generic Solar Reference are protected references. User-
            # created working copies of these are not
            # protected (they have project_origin =
            # 'user_created').
            "is_protected_reference": is_protected_reference(project_record),
            # Phase P2-FIX-1: single consolidated project
            # list (presentation only). The underlying
            # factory_template / user_created / saved_
            # baseline distinction lives in the data
            # model, NOT in the visible UI.
            "consolidated_project_records": _consolidated_project_records(user),
            "factory_template_projects": FACTORY_TEMPLATE_OPTIONS,
            "user_project_records": _user_project_selector_items(user),
            "baseline_project_records": baseline_project_items,
            "new_project_template_options": NEW_PROJECT_TEMPLATE_OPTIONS,
            "project_record": project_record,
            "scenario_records": scenario_records,
            "scenario_history": scenario_history,
            "export_records": export_records,
            "export_lineage": export_lineage,
            "export_lineage_ui": _build_export_lineage_ui_context(project_record, workspace_state, export_lineage),
            "scenario_summary_cards": scenario_summary_cards,
            "compare_result": None,
            # Phase P2-FIX-4: Five-Area Navigation.
            # The compressed nav bar is rendered
            # above the existing ws-tab ribbon for
            # EVERY project (factory_template,
            # user_created, saved_baseline). The
            # previous P2-min-4 gate that only
            # enabled the compressed nav for
            # user_created projects was removed.
            # The compressed view is the new normal
            # for every project, including protected
            # references (Generic Wind Reference / Generic Solar Reference). The
            # existing ws-tab buttons + panel panels
            # + routes are preserved (hidden != deleted).
            "nav_compression_enabled": True,
            # Phase P2-FIX-4: Dashboard v1 (presentation only).
            # Inline dashboard data: 8 KPI cards + 3 inline-SVG
            # charts. Server-rendered. NO Chart.js / Plotly / D3.
            # NO JS calc. NO formula / factory / model change.
            #
            # The dashboard is now enabled for EVERY project
            # (user_created, factory_template,
            # saved_baseline). For protected references
            # (Generic Wind Reference / Generic Solar Reference) the dashboard shows a
            # "No run yet" CTA because the runtime snapshot
            # belongs to the working copy, not the read-only
            # reference. The CTA lets the user open / run
            # from a clear next-step surface.
            **(_build_index_dashboard_context(
                project_record=project_record,
                realized_gearing_pct=getattr(ctx, "realized_gearing_pct", None),
                workspace_state=workspace_state,
            ) if project_record.project_origin in (
                "user_created", "factory_template", "saved_baseline"
            ) else {}),
            "workspace_message": None,
            "is_user_project": project_record.project_origin == "user_created",
            # PR B — CAPEX Excel grid view model (sheet_capex_grid.html)
            "capex_vm": build_capex_view_model(
                ctx,
                is_user_project=project_record.project_origin == "user_created",
            ),
            # PR D — OPEX Excel grid view model (sheet_opex_grid.html)
            "opex_vm": build_opex_view_model(
                ctx,
                is_user_project=project_record.project_origin == "user_created",
            ),
            # Phase 24-H: exploratory warning flag (user_created + generic)
            "is_exploratory_project": (
                project_record.project_origin == "user_created"
                and (project_record.template_source or "").strip().lower()
                in {"generic_solar", "generic_wind"}
            ),
            # Phase 20E: scenario tab context
            "base_case_record": next((s for s in scenario_records if s.is_base_case), None),
            "non_base_scenarios": [s for s in scenario_records if not s.is_base_case],
            "scenario_editable_fields": SCENARIO_EDITABLE_FIELDS,
            # Phase M2 / STAB-1: live scenario matrix context.
            # Pass last_runtime_summary (raw kpis dict) so Base KPI rows
            # populate from the last run result rather than showing "—".
            **__import__("app.ui.scenario_matrix", fromlist=["build_matrix_context"]).build_matrix_context(
                ctx, scenario_records,
                runtime_kpis=getattr(workspace_state, "last_runtime_summary", None) or None,
            ),
            # Phase 55E: UI-2.6 run-source indicator context
            # Derived from existing workspace_state (last_runtime_snapshot_id,
            # last_runtime_at). None when no real runtime data exists.
            "runtime_summary": _runtime_summary_for_index(workspace_state),
            # Phase 57C: UI-2.3 validation summary bar context now reflects
            # actual current-run/input issues only. Platform guards render
            # separately below the bar.
            "validation_summary": _validation_summary_for_context(
                project_record, validation_errors
            ),
            "governance_guard_summary": _governance_guard_summary_for_context(
                project_record
            ),
            # Phase 55G: UI-2.1 state clarity banner context
            # Derived from existing project_record, workspace_state, validation_errors.
            # Deterministic priority; None when no clear state.
            "banner_context": _banner_context_for_index(
                project_record, workspace_state, validation_errors
            ),
            # Phase P2-FIX-2: Audit / reviewer mode flag.
            # Default False (normal mode). Relocated governance /
            # lineage / runtime-source / review-boundary content
            # renders only in the audit tab (which always includes
            # _audit_governance_relocated.html), and the overview
            # shell suppresses the same content unless audit_mode
            # is True. This is presentation-only.
            "audit_mode": False,
        },
    )

    # Workbook V2 PR 3: hydrate sessionStorage from DB on page load so that
    # schedule data (FS, debt, tax, distribution, sponsor) survives browser
    # refresh without a re-run. workspace_state is already scoped to the
    # authenticated user + active project, so no cross-project/user leak.
    _rr = RuntimeResult.from_workspace_state(workspace_state) if workspace_state else None
    if _rr is not None:
        _hydration_script = _rr.to_sessionstorage_script()
        if _hydration_script:
            _body = _index_response.body.decode("utf-8")
            if _body.startswith("<!DOCTYPE"):
                _body = _body.replace("<body", _hydration_script + "<body", 1)
            else:
                _body = _hydration_script + _body
            return HTMLResponse(content=_body, status_code=200)
    return _index_response


@app.post("/validate")
async def validate(request: Request):
    """Validate form inputs. Requires auth.

    Phase 51D-2: orchestration extracted into
    ``app.services.validation_service.execute_validate_route``. The
    route is now thin: auth, form parse, deps bundle, service call,
    render.
    """
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    form = await request.form()
    deps = ValidateRouteDeps(
        collect_form_snapshot=_collect_form_snapshot,
        project_workspace_from_snapshot=_project_workspace_from_snapshot,
        canonical_project_type=_canonical_project_type,
        normalize_template_source=_normalize_template_source,
        check_runtime_allowed=check_runtime_allowed,
        resolve_runtime_snapshot_source=_resolve_runtime_snapshot_source,
        build_schema_from_form=_build_schema_from_form_with_timing(form),
        validate_numeric_field=_validate_numeric_field,
        project_types=PROJECT_TYPES,
        scenarios=SCENARIOS,
        snapshot_input_error=SnapshotInputError,
    )
    outcome = await execute_validate_route(
        request=request, form=form, user=user, deps=deps,
    )
    return templates.TemplateResponse(
        request=request,
        name=outcome.template_name,
        context=outcome.context,
        status_code=outcome.status_code,
    )


@app.post("/run")
async def run(request: Request):
    """Run model with custom inputs. Requires auth.

    Thin orchestration wrapper (Phase 51B). The route is responsible for
    auth, form parsing and final template rendering. The full /run
    orchestration body (project/workspace resolution, runtime guard,
    runtime snapshot resolution, three execution paths, persistence side
    effects, sessionStorage script construction) lives in
    ``app.services.run_service.execute_run_route``.
    """
    from app.services.run_service import (
        RunRouteDeps,
        execute_run_route,
    )

    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    # P6.7 — demo session rate limiting for model runs
    if user.is_demo:
        allowed, retry_after = check_demo_rate_limit(user.user_id, "model_run")
        if not allowed:
            return templates.TemplateResponse(
                request=request,
                name="errors.html",
                context={
                    "error_title": "Run limit reached",
                    "error_message": (
                        f"Demo sessions are limited to {20} model runs per hour. "
                        f"Try again in {retry_after}s."
                    ),
                },
                status_code=429,
            )

    # P6.6 — global concurrency limiter (atomic non-blocking acquire)
    slot_acquired = await _acquire_run_slot()
    if not slot_acquired:
        from app.observability import log_capacity_busy
        log_capacity_busy(max_slots=_MAX_CONCURRENT_RUNS or 0)
        return templates.TemplateResponse(
            request=request,
            name="errors.html",
            context={
                "error_title": "Model busy",
                "error_message": (
                    "All model run slots are in use. Please wait a moment and try again."
                ),
            },
            status_code=503,
        )

    # P6.D — outer try/finally begins immediately after successful acquisition.
    # Every exit path after this point (form parse error, deps construction,
    # observability setup, execute_run_route, template render) is covered by
    # _release_run_slot(), preventing permanent slot leaks.
    import time as _time
    from app.observability import log_run_started, log_run_completed, log_run_failed
    _run_start = _time.monotonic()
    _run_started_logged = False
    try:
        form = await request.form()

        deps = RunRouteDeps(
            collect_form_snapshot=_collect_form_snapshot,
            project_workspace_from_snapshot=_project_workspace_from_snapshot,
            normalize_template_source=_normalize_template_source,
            canonical_project_type=_canonical_project_type,
            check_runtime_allowed=check_runtime_allowed,
            resolve_runtime_snapshot_source=_resolve_runtime_snapshot_source,
            build_schema_from_form=_build_schema_from_form_with_timing(form),
            validate_form=_validate_form,
            format_kpis=_format_kpis,
            default_workspace_snapshot=_default_workspace_snapshot,
            replay_metadata_for_project=_replay_metadata_for_project,
            governance_snapshot=_governance_snapshot,
            scenario_provenance_for_record=_scenario_provenance_for_record,
            run_project=run_project,
            build_projectinputs=build_projectinputs,
            build_projectinputs_from_snapshot=build_projectinputs_from_snapshot,
            record_workspace_runtime=record_workspace_runtime,
            update_scenario_last_run_summary=update_scenario_last_run_summary,
            runtime_summary_to_dict=runtime_summary_to_dict,
            snapshot_input_error=SnapshotInputError,
        )

        log_run_started(user.user_id)
        _run_started_logged = True

        try:
            outcome = await execute_run_route(
                request=request, form=form, user=user, deps=deps,
            )
            _run_ms = (_time.monotonic() - _run_start) * 1000
            log_run_completed(_run_ms)
        except Exception as _run_exc:
            _run_ms = (_time.monotonic() - _run_start) * 1000
            log_run_failed(type(_run_exc).__name__)
            raise
    except Exception:
        if not _run_started_logged:
            # Pre-execution failure: slot was held but run never started.
            # Log run_failed with a synthetic type so observers see the leak
            # path was covered (run_started was never emitted intentionally).
            pass
        raise
    finally:
        _release_run_slot()

    # Plain errors.html path: just render the template (no prepend_html).
    if not outcome.prepend_html:
        return templates.TemplateResponse(
            request=request,
            name=outcome.template_name,
            context=outcome.context,
            status_code=outcome.status_code,
        )

    # sessionStorage-bearing path: render, then prepend the save <script>.
    # Preserve the legacy behaviour where Generic Wind Reference/Generic Solar Reference outputs (which start
    # with ``<!DOCTYPE``) get the script injected after ``<body``, while
    # user_created outputs (which do not) get a direct prepended script.
    rendered = templates.TemplateResponse(
        request=request,
        name=outcome.template_name,
        context=outcome.context,
        status_code=outcome.status_code,
    )
    body_str = rendered.body.decode("utf-8")
    if body_str.startswith("<!DOCTYPE"):
        body_str = body_str.replace("<body", outcome.prepend_html + "<body")
    else:
        body_str = outcome.prepend_html + body_str

    # OOB dashboard KPI update — append after the runtime_summary HTML so
    # HTMX swaps #dashboard-v1 in-place without a full page reload.
    # Read raw KPIs from the workspace state that record_workspace_runtime
    # just saved; extract project from form (available in this route scope).
    # STAB-1: OOB dashboard KPI + scenario matrix refresh after a successful run.
    # STAB-7: kpis.html (generic path) now also carries prepend_html + runtime_summary,
    # so extend the gate to include it alongside runtime_summary.html.
    if outcome.template_name in {"partials/runtime_summary.html", "partials/kpis.html"}:
        _active_project_code = form.get("active_project", "").strip().lower()
        _project_rec = _resolve_project_record(user, _active_project_code, {"active_project": _active_project_code})
        if _project_rec:
            _ws = get_workspace_state(user.user_id, _project_rec.project_id)
            raw_kpis = getattr(_ws, "last_runtime_summary", None) or {} if _ws else {}
            if raw_kpis:
                from app.ui.dashboard import build_dashboard_kpis_from_raw_kpis
                from app.ui.scenario_matrix import build_matrix_context as _bmc
                from app.ui.project_context import get_project_context as _get_ctx
                import datetime as _dt

                # ── 1. Dashboard OOB ─────────────────────────────────────
                oob_kpis = build_dashboard_kpis_from_raw_kpis(raw_kpis)
                rs = outcome.context.get("runtime_summary", {})
                run_status_label = (
                    rs.get("last_runtime_origin_label", "Backend runtime")
                    if isinstance(rs, dict) else "Backend runtime"
                )
                oob_dash = templates.TemplateResponse(
                    request=request,
                    name="partials/_dashboard_oob.html",
                    context={
                        "dashboard_kpis": oob_kpis,
                        "run_status_label": run_status_label,
                        "run_timestamp": _dt.datetime.now(tz=_dt.timezone.utc).strftime("%H:%M UTC"),
                    },
                )
                body_str += oob_dash.body.decode("utf-8")

                # ── 2. Scenario Matrix OOB ───────────────────────────────
                try:
                    _oob_ctx = _get_ctx(_project_rec.project_code)
                    _oob_scenarios = list_scenarios(user.user_id, project_id=_project_rec.project_id)
                    _matrix_ctx = _bmc(
                        _oob_ctx, _oob_scenarios, runtime_kpis=raw_kpis,
                    )
                    oob_matrix = templates.TemplateResponse(
                        request=request,
                        name="partials/_scenario_matrix_oob.html",
                        context={**_matrix_ctx},
                    )
                    body_str += oob_matrix.body.decode("utf-8")
                except Exception as exc:
                    _logger.warning(
                        "scenario_matrix_oob failed (non-blocking): "
                        "project_code=%r route=/run component=scenario_matrix_oob exc=%r",
                        getattr(_project_rec, "project_code", None),
                        repr(exc),
                    )

                # ── 3. Active Result Sheet OOB ───────────────────────────
                # UX-2: if the user is viewing a runtime-backed result sheet,
                # refresh it so the shared_runtime_block shows the new KPIs.
                _RUNTIME_SHEET_MAP = {
                    "senior-debt":   "partials/sheet_senior_debt.html",
                    "shl":           "partials/sheet_shl.html",
                    "tax":           "partials/sheet_tax.html",
                    "pl":            "partials/sheet_financials.html",
                    "cashflow":      "partials/sheet_financials.html",
                    "balance":       "partials/sheet_financials.html",
                    "distributions": "partials/_sheet_distributions_partial.html",
                    "sponsor":       "partials/_sheet_sponsor_partial.html",
                }
                _active_tab = (form.get("active_tab") or "overview").strip().lower()
                _sheet_template = _RUNTIME_SHEET_MAP.get(_active_tab)
                if _sheet_template:
                    try:
                        _shared_block = templates.TemplateResponse(
                            request=request,
                            name="partials/shared_runtime_block.html",
                            context={},
                        )
                        _sheet_inner = templates.TemplateResponse(
                            request=request,
                            name=_sheet_template,
                            context={
                                "project_ctx": _get_ctx(_project_rec.project_code),
                                "audit_mode": False,
                                "financial_statements": outcome.context.get("financial_statements"),
                                "runtime_summary": outcome.context.get("runtime_summary"),
                            },
                        )
                        oob_sheet_html = (
                            '<div id="panel-' + _active_tab + '" hx-swap-oob="true">'
                            + _shared_block.body.decode("utf-8")
                            + _sheet_inner.body.decode("utf-8")
                            + '</div>'
                        )
                        body_str += oob_sheet_html
                    except Exception as exc:
                        _logger.warning(
                            "active_sheet_oob failed (non-blocking): "
                            "active_tab=%r template=%r exc=%r",
                            _active_tab,
                            _sheet_template,
                            repr(exc),
                        )

    return HTMLResponse(content=body_str, status_code=rendered.status_code)


@app.post("/model/preview")
async def model_preview(request: Request):
    """C2-PR7: backend preview endpoint CONTRACT STUB. Requires auth.

    C2-PR23: this route is now a thin adapter over
    app.services.model_preview's validate_preview_payload() /
    build_preview_response() — the validation/computation/echo logic
    itself moved there (see docs/C2_PR23_PREVIEW_SERVICE_BOUNDARY.md
    for the characterization-test-then-refactor methodology used to
    prove zero behaviour change). The route itself still owns exactly:
      (a) auth check
      (b) project authorization check (get_project_by_code)
      (c) calling into the service
      (d) returning the JSON response

    Accepts the C2-PR6 client-side preview-payload shape (see
    ``static/modelling/recalc-preview.js``'s ``buildPreviewPayload``/
    ``validatePreviewPayload``) and returns a deterministic no-op
    response for the "operating preview" fields. C2-PR24 adds the
    first backend-computed field ("debt") — see
    docs/C2_PR24_BACKEND_DEBT_PREVIEW_STUB.md.

      - It never calls the financial/calculation engine
        (``app/waterfall_core.py``, ``domain/*``, or any other
        financial code).
      - It never mutates persistence, the database, or session state.
      - It never writes to disk.
      - It never triggers a model Run.
      - It never touches export logic.
      - It has zero side effects beyond returning a response.

    A malformed/incomplete body never produces a 500 or an unhandled
    exception — it always degrades to a safe
    ``{"ok": false, "status": "invalid-payload", ...}`` response.

    C2-PR9 (Runtime Request Hardening) adds project authorization: if
    the payload's ``project`` field is non-null, the authenticated
    user must own that project (the same ``get_project_by_code(user_id,
    project_code)`` lookup every other project-scoped route in this
    file already uses to scope access — no new authorization
    mechanism is invented here). A project the user cannot access
    yields a safe ``forbidden-project`` JSON response, never a 500 and
    never any project data belonging to another user. ``project: null``
    behaves exactly as before this PR (no regression).

    See docs/C2_PR7_BACKEND_PREVIEW_ENDPOINT_CONTRACT_STUB_NOTE.md,
    docs/C2_PR9_RUNTIME_REQUEST_HARDENING.md,
    docs/C2_PR23_PREVIEW_SERVICE_BOUNDARY.md, and
    docs/C2_PR24_BACKEND_DEBT_PREVIEW_STUB.md for the full route-choice
    rationale, request/response schema, and no-side-effect/
    authorization verification approach.
    """
    user = get_current_user(request)
    if not user:
        return JSONResponse({"status": "unauthenticated", "detail": "Login required"}, status_code=401)

    try:
        body = await request.json()
    except Exception:
        body = None

    ok, errors = _model_preview_validate_payload(body)
    if not ok:
        # C2-PR8: deliberately no "overview" key on the invalid-payload
        # branch (rather than adding one with updated: false) — an
        # invalid request never produced anything for the client to
        # render, so there is nothing to describe; the client-side
        # runtime renderer (static/modelling/runtime-renderer.js)
        # already treats a missing "overview" field as a safe no-op.
        return JSONResponse(
            {
                "ok": False,
                "status": "invalid-payload",
                "executed": False,
                "accepted": False,
                "warnings": errors,
            },
            status_code=200,
        )

    # C2-PR9: project authorization. ``project`` is optional/nullable
    # in the payload contract (see docs/C2_PR7_*); when present, the
    # authenticated user must actually own that project_code. This
    # reuses the exact same lookup (`get_project_by_code`) every other
    # project-scoped route in this file (e.g. the export routes above)
    # already uses for authorization — a project record that does not
    # belong to this user (or does not exist at all) is indistinguishable
    # here, by design, so this never leaks whether a project_code exists
    # for someone else.
    project_code = body.get("project")
    project_record = None
    if project_code is not None:
        project_record = get_project_by_code(user.user_id, project_code)
        if project_record is None:
            return JSONResponse(
                {
                    "ok": False,
                    "status": "forbidden-project",
                    "accepted": False,
                    "executed": False,
                    "warnings": ["Project access denied."],
                },
                status_code=200,
            )

    response_body = _model_preview_build_response(body, project_record)
    return JSONResponse(response_body, status_code=200)




@app.post("/compare")
async def compare(request: Request):
    """Run Base/Downside/Upside comparison. Requires auth.

    Phase 51C-2: orchestration extracted into
    ``app.services.compare_service.execute_compare_route``. The route is
    now thin: auth, form parse, deps bundle, service call, render.
    """
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    form = await request.form()
    deps = CompareRouteDeps(
        collect_form_snapshot=_collect_form_snapshot,
        project_workspace_from_snapshot=_project_workspace_from_snapshot,
        canonical_project_type=_canonical_project_type,
        normalize_template_source=_normalize_template_source,
        check_runtime_allowed=check_runtime_allowed,
        resolve_runtime_snapshot_source=_resolve_runtime_snapshot_source,
        build_schema_from_form=_build_schema_from_form_with_timing(form),
        build_projectinputs=build_projectinputs,
        build_projectinputs_from_snapshot=build_projectinputs_from_snapshot,
        scenarios=SCENARIOS,
        project_types=PROJECT_TYPES,
        snapshot_input_error=SnapshotInputError,
        run_project=run_project,
    )
    outcome = await execute_compare_route(
        request=request, form=form, user=user, deps=deps,
    )
    return templates.TemplateResponse(
        request=request,
        name=outcome.template_name,
        context=outcome.context,
        status_code=outcome.status_code,
    )


@app.post("/download")
async def download_post(request: Request):
    """Generate Excel export with current form values. Requires auth.

    Phase 51E-2: orchestration extracted into
    ``app.services.download_service.execute_post_download_route``.
    The route is now thin: auth, form parse, deps bundle, service
    call, render StreamingResponse or HTMLResponse.
    """
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    # P6.7 — demo rate limiting for export generation
    if user.is_demo:
        allowed, retry_after = check_demo_rate_limit(user.user_id, "export_generate")
        if not allowed:
            return HTMLResponse(
                content=f"<p>Export limit reached. Try again in {retry_after}s.</p>",
                status_code=429,
            )

    form = await request.form()
    deps = DownloadRouteDeps(
        collect_form_snapshot=_collect_form_snapshot,
        project_workspace_from_snapshot=_project_workspace_from_snapshot,
        canonical_project_type=_canonical_project_type,
        normalize_template_source=_normalize_template_source,
        check_runtime_allowed=check_runtime_allowed,
        resolve_runtime_snapshot_source=_resolve_runtime_snapshot_source,
        build_schema_from_form=_build_schema_from_form_with_timing(form),
        build_projectinputs=build_projectinputs,
        build_projectinputs_from_snapshot=build_projectinputs_from_snapshot,
        scenario_provenance_for_record=_scenario_provenance_for_record,
        replay_metadata_for_project=_replay_metadata_for_project,
        governance_snapshot=_governance_snapshot,
        get_project_by_code=get_project_by_code,
        build_excel_export_for_post_request=build_excel_export_for_post_request,
        build_values_only_export_for_project=build_values_only_export_for_project,
        record_download_export=record_download_export,
        utc_now_iso=utc_now_iso,
    )
    outcome = await execute_post_download_route(
        request=request, form=form, user=user, deps=deps,
    )
    if outcome.is_error:
        return HTMLResponse(
            content=outcome.content, status_code=outcome.status_code,
        )
    return StreamingResponse(
        iter([outcome.content]),
        media_type=outcome.media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{outcome.filename}"',
            **outcome.headers,
        },
        status_code=outcome.status_code,
    )


@app.get("/download")
async def download_get(request: Request, project_type: str = "Solar", scenario: str = "Base"):
    """Generate Excel export (GET - uses factory defaults). Requires auth.

    Phase 51E-2: orchestration extracted into
    ``app.services.download_service.execute_get_download_route``.
    The route is now thin: auth, query params, deps bundle, service
    call, render StreamingResponse or HTMLResponse.
    """
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    deps = DownloadRouteDeps(
        collect_form_snapshot=_collect_form_snapshot,
        project_workspace_from_snapshot=_project_workspace_from_snapshot,
        canonical_project_type=_canonical_project_type,
        normalize_template_source=_normalize_template_source,
        check_runtime_allowed=check_runtime_allowed,
        resolve_runtime_snapshot_source=_resolve_runtime_snapshot_source,
        build_schema_from_form=_build_schema_from_form_with_timing(None),
        build_projectinputs=build_projectinputs,
        build_projectinputs_from_snapshot=build_projectinputs_from_snapshot,
        scenario_provenance_for_record=_scenario_provenance_for_record,
        replay_metadata_for_project=_replay_metadata_for_project,
        governance_snapshot=_governance_snapshot,
        get_project_by_code=get_project_by_code,
        build_excel_export_for_post_request=build_excel_export_for_post_request,
        build_values_only_export_for_project=build_values_only_export_for_project,
        record_download_export=record_download_export,
        utc_now_iso=utc_now_iso,
    )
    outcome = await execute_get_download_route(
        request=request, user=user,
        project_type=project_type, scenario=scenario,
        deps=deps,
    )
    if outcome.is_error:
        return HTMLResponse(
            content=outcome.content, status_code=outcome.status_code,
        )
    return StreamingResponse(
        iter([outcome.content]),
        media_type=outcome.media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{outcome.filename}"',
            **outcome.headers,
        },
        status_code=outcome.status_code,
    )


@app.get("/exports/runtime-summary.csv")
async def runtime_summary_export(request: Request, project: str = "generic_wind_reference"):
    """Download standardized Phase 10 runtime summary CSV. Requires auth."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    # P6.7 — demo rate limiting
    if user.is_demo:
        allowed, retry_after = check_demo_rate_limit(user.user_id, "export_generate")
        if not allowed:
            return HTMLResponse(
                content=f"<p>Export limit reached. Try again in {retry_after}s.</p>",
                status_code=429,
            )

    safe_project = project.strip().lower() if project else "generic_wind_reference"
    project_record = get_project_by_code(user.user_id, safe_project)
    runtime_project_code = safe_project
    if project_record is not None:
        runtime_project_code = _normalize_template_source(project_record.template_source or project_record.source_project_template, project_record.project_type)

    export = build_runtime_summary_csv_export(
        runtime_project_code,
        safe_project=safe_project,
        project_record=project_record,
        user_id=user.user_id,
    )
    if export.has_error():
        return HTMLResponse(content=export.error_content, status_code=export.status_code)

    record_runtime_summary_export(
        user_id=user.user_id,
        project_code=safe_project,
        artifact_name=export.filename,
        project_id=project_record.project_id if project_record else None,
        governance_state=_governance_snapshot(safe_project),
        replay_metadata=_replay_metadata_for_project(
            safe_project,
            export_type="runtime_summary_csv",
            export_timestamp=export.metadata["export_generated_at"],
            runtime_timestamp=export.metadata["runtime_generated_at"],
            project_id=project_record.project_id if project_record else None,
            runtime_origin=export.metadata["runtime_origin"],
            artifact_name=export.filename,
            baseline_source=(project_record.project_origin == "saved_baseline") if project_record else None,
        ),
    )
    return StreamingResponse(
        iter([export.bytes_data]),
        media_type=export.media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{export.filename}"',
            "Content-Length": str(len(export.bytes_data)),
        },
    )


@app.get("/exports/institutional-workbook.xlsx")
async def institutional_workbook_export(request: Request, project: str = "generic_wind_reference"):
    """Download Phase 10 institutional workbook skeleton. Requires auth."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    # P6.7 — demo rate limiting
    if user.is_demo:
        allowed, retry_after = check_demo_rate_limit(user.user_id, "export_generate")
        if not allowed:
            return HTMLResponse(
                content=f"<p>Export limit reached. Try again in {retry_after}s.</p>",
                status_code=429,
            )

    safe_project = project.strip().lower() if project else "generic_wind_reference"
    project_record = get_project_by_code(user.user_id, safe_project)
    runtime_project_code = safe_project
    if project_record is not None:
        runtime_project_code = _normalize_template_source(project_record.template_source or project_record.source_project_template, project_record.project_type)

    export = build_institutional_workbook_export(runtime_project_code, safe_project=safe_project, project_record=project_record, user_id=user.user_id)
    if export.has_error():
        return HTMLResponse(content=export.error_content, status_code=export.status_code)

    record_institutional_workbook_export(
        user_id=user.user_id,
        project_code=safe_project,
        artifact_name=export.filename,
        project_id=project_record.project_id if project_record else None,
        governance_state=_governance_snapshot(safe_project),
        replay_metadata=_replay_metadata_for_project(
            safe_project,
            export_type="institutional_workbook",
            workbook_type="institutional_workbook_runtime_binding",
            export_timestamp=export.metadata["export_generated_at"],
            runtime_timestamp=export.metadata["runtime_generated_at"],
            project_id=project_record.project_id if project_record else None,
            runtime_origin=export.metadata["runtime_origin"],
            artifact_name=export.filename,
            baseline_source=(project_record.project_origin == "saved_baseline") if project_record else None,
        ),
    )
    return StreamingResponse(
        iter([export.bytes_data]),
        media_type=export.media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{export.filename}"',
            "Content-Length": str(len(export.bytes_data)),
        },
    )


@app.get("/projects/new")
async def new_project_form(request: Request):
    """Phase P2-FIX-1: minimal new-project form.

    Renders the same minimal form as
    ``/projects/new/minimal`` (4 visible
    fields: project name, technology,
    country, capacity MW + optional COD).
    All other driver values come from the
    canonical generic factory defaults
    (server-side, hidden inputs).

    Does NOT render: tariff, PPA, P50,
    OPEX, CAPEX, gearing, interest, tenor,
    DSCR, factory function names, or the
    EXPLORATORY banner block.
    """
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    return templates.TemplateResponse(
        request=request,
        name="project_new_page.html",
        context={
            "project_types": PROJECT_TYPES,
            "validation_errors": [],
            "submitted": _minimal_submitted_new_project_defaults(),
            "default_template_source": P2_MIN_DEFAULT_TEMPLATE_SOURCE,
        },
    )


# Phase 25B-1: Generic defaults prefill endpoint.
# Returns JSON with the 16 form-field values derived from the
# existing generic factory functions. Read-only. Accepts only
# generic_solar / generic_wind; any other template_source
# returns 400 to prevent factory leakage.
@app.get("/projects/new/defaults")
async def new_project_defaults(
    request: Request,
    template_source: str = "generic_solar",
):
    user = get_current_user(request)
    if not user:
        return JSONResponse({"detail": "auth required"}, status_code=401)
    if template_source not in _GENERIC_PREFILL_ALLOWED_SOURCES:
        return JSONResponse(
            {
                "detail": (
                    "prefill only available for generic_solar / generic_wind; "
                    f"got {template_source!r}"
                ),
                "allowed": sorted(_GENERIC_PREFILL_ALLOWED_SOURCES),
            },
            status_code=400,
        )
    values = _generic_prefill_values(template_source)
    if values is None:
        # Defensive: should be unreachable because of the
        # _GENERIC_PREFILL_ALLOWED_SOURCES check above.
        return JSONResponse({"detail": "prefill unavailable"}, status_code=400)
    return JSONResponse({
        "template_source": template_source,
        "values": values,
        "warning": (
            "EXPLORATORY / not Excel-parity validated. "
            "Not lender / bank / external-audit ready. "
            "Defaults are round numbers for sketching only."
        ),
    })


# Phase 25B-1: Server-side prefill (non-JS fallback).
# If the user opens /projects/new?template_source=generic_solar
# directly (or clicks a link from the docs), the form is
# rendered with all 16 fields prefilled. The form template
# still has the EXPLORATORY notice and the prefill button
# for further refresh.
@app.get("/projects/new/prefill")
async def new_project_form_prefilled(
    request: Request,
    template_source: str = "generic_solar",
):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    submitted = _submitted_new_project_defaults()
    if template_source in _GENERIC_PREFILL_ALLOWED_SOURCES:
        prefill = _generic_prefill_values(template_source)
        if prefill:
            submitted.update(prefill)
    return templates.TemplateResponse(
        request=request,
        name="partials/new_project_form.html",
        context={
            "project_types": PROJECT_TYPES,
            "template_options": NEW_PROJECT_TEMPLATE_OPTIONS,
            "validation_errors": [],
            "submitted": submitted,
        },
    )


# ---------------------------------------------------------------------------
# Phase P2-min-1: Project Home (presentation entry point)
# ---------------------------------------------------------------------------

def _resolve_technology(record) -> str:
    """Derive technology label from record fields — never from run state."""
    if record.project_type:
        return record.project_type
    snap = record.baseline_snapshot or {}
    if snap.get("project_type"):
        return snap["project_type"]
    # Derive from template_source as last resort
    ts = (record.template_source or record.source_project_template or "").lower()
    if "data_center" in ts or "datacenter" in ts.replace(" ", "_"):
        return "Data Center"
    if "solar" in ts or ts == "generic_solar_reference":
        return "Solar PV"
    if "wind" in ts or ts == "generic_wind_reference":
        return "Wind"
    return "—"


def _find_existing_working_copy(user_id: str, source_project_code: str):
    """Return the first user-owned working copy of source_project_code, or None."""
    for record in list_project_records(user_id=user_id):
        if record.project_origin != "user_created":
            continue
        meta = record.replay_metadata or {}
        if (
            meta.get("export_type") == "working_copy_from_protected_reference"
            and meta.get("source_project_code") == source_project_code
        ):
            return record
    return None


def _home_user_projects(user) -> list:
    """Return the user-created project items for the Project Home table.

    Returns richer data than the old card grid: technology (from record,
    never run state), country, capacity, last-edited, last-run, status.
    Factory templates, baselines, and parity fixtures are hidden (presentation
    filter only — they remain reachable from /projects/browse).
    """
    rows = []
    for record in list_project_records(user_id=user.user_id):
        if record.project_origin != "user_created":
            continue
        snap = record.baseline_snapshot or {}
        last_run = record.last_run_summary or {}
        # Status
        if last_run:
            run_at = last_run.get("run_at") or last_run.get("timestamp") or ""
            updated = str(record.updated_at or "")
            if run_at and updated and updated > run_at:
                status = "Needs rerun"
            else:
                status = "Run completed"
        else:
            status = "Draft"
        from app.utils.workbook_flag import project_workbook_url as _pwurl
        import urllib.parse as _up
        code = record.project_code
        rows.append({
            "project_code": code,
            "name": record.project_name,
            "technology": _resolve_technology(record),
            "country": snap.get("country_market") or "—",
            "capacity_mw": snap.get("capacity_mw") or "—",
            "last_edited": str(record.updated_at)[:10] if record.updated_at else "—",
            "last_run": str(last_run.get("run_at") or last_run.get("timestamp") or "")[:10] or "—",
            "status": status,
            # Canonical destination URLs — flag-aware, built server-side
            "workbook_url": _pwurl(code),
            "workbook_url_inputs": _pwurl(code, sheet="inputs"),
            "workbook_url_capex": _pwurl(code, sheet="capex"),
            "workbook_url_opex": _pwurl(code, sheet="opex"),
            "workbook_url_results": _pwurl(code),
            "workbook_url_scenarios": f"/scenarios?project={_up.quote(code, safe='')}",
        })
    return rows


# Default template source for the minimal new-project form.
# Generic Solar is the default because the brief asks for
# technology-only (no other selector). The user can change it
# later from the workspace inputs.
P2_MIN_DEFAULT_TEMPLATE_SOURCE = "generic_solar"


def _build_index_dashboard_context(
    project_record,
    realized_gearing_pct=None,
    workspace_state=None,
) -> dict:
    """Phase P2-min-3: build the inline
    Dashboard v1 data (KPI cards + 3 SVG
    charts) for the workspace Overview.

    Server-rendered. Pure-Python: reads
    values from the project record and the
    realized gearing helper. NO Chart.js /
    Plotly / D3 / JS calc. NO formula /
    factory / model change.

    HOTFIX-PILOT-BLOCKER-1 (F3): The dashboard
    now reads KPIs from
    ``workspace_state.last_runtime_summary`` (the
    authoritative source already used by the
    runtime update path). The previous
    ``getattr(project_record, "last_waterfall_result")``
    always returned None, which made the dashboard
    render all KPIs as "—" after a successful run.
    """
    from app.ui.dashboard import (
        build_dashboard_kpis,
        build_revenue_ebitda_series,
        build_dscr_series,
        build_debt_balance_series,
        render_svg_line_chart,
        render_svg_dscr_chart,
        render_svg_debt_chart,
    )

    last_runtime_summary = (
        getattr(workspace_state, "last_runtime_summary", None) if workspace_state else None
    )
    kpis = build_dashboard_kpis(
        last_runtime_summary=last_runtime_summary,
        project_record=project_record,
        realized_gearing_pct=realized_gearing_pct,
    )
    # For the revenue/ebitda chart we still need a WaterfallResult-like
    # shape. Reuse the previously-stub waterfall_result by wrapping the
    # last_runtime_summary into a SimpleNamespace with ``summary`` and
    # ``yearly_series`` attributes so the existing chart builders
    # continue to work without API change.
    class _StubW:
        def __init__(self, kpis_dict):
            self.summary = kpis_dict or {}
            self.yearly_series = {}
    waterfall_result = _StubW(last_runtime_summary or {})
    revenue_ebitda_series = build_revenue_ebitda_series(waterfall_result)
    dscr_series = build_dscr_series(waterfall_result)
    debt_series = build_debt_balance_series(waterfall_result)

    return {
        "dashboard_enabled": True,
        "dashboard_kpis": kpis,
        "dashboard_chart_revenue_ebitda_svg": render_svg_line_chart(
            revenue_ebitda_series,
            series_specs=[
                {"key": "revenue", "color": "var(--primary)",
                 "label": "Revenue"},
                {"key": "ebitda", "color": "var(--success, #2e7d32)",
                 "label": "EBITDA"},
            ],
        ),
        "dashboard_chart_dscr_svg": render_svg_dscr_chart(dscr_series),
        "dashboard_chart_debt_svg": render_svg_debt_chart(debt_series),
    }


@app.get("/home", response_class=HTMLResponse)
async def project_home(request: Request):
    """Phase P2-FIX-1: legacy /home redirects to /
    (canonicalisation). GET / now renders the
    Project Home directly.
    """
    return RedirectResponse(url="/", status_code=302)


def _render_project_home(request: Request, user):
    """Phase P2-FIX-1 + P2-FIX-5A: shared Project Home
    renderer. Used by ``GET /`` (canonical) and
    ``GET /home`` (legacy redirect target).

    Phase P2-FIX-1 originally returned
    ``partials/project_home.html`` directly (no
    ``base.html``), which produced a raw HTML
    fragment. Phase P2-FIX-5A renders the wrapper
    ``project_home_page.html`` which is a full
    standalone HTML document (DOCTYPE, head, body,
    CSS bundle, JS bundle, top header, brand).
    The workspace-context base.html is not
    extended because it requires ``workspace_state``
    and other workspace-only context that the
    Project Home / new-project / project-browser
    pages do not have.
    """
    return templates.TemplateResponse(
        request=request,
        name="project_home_page.html",
        context={
            "home_user_projects": _home_user_projects(user),
        },
    )


@app.get("/projects/new/minimal", response_class=HTMLResponse)
async def new_project_minimal(request: Request):
    """Phase P2-FIX-1: legacy /projects/new/minimal
    redirects to /projects/new (canonicalisation).
    Both routes now serve the same minimal form.
    """
    return RedirectResponse(url="/projects/new", status_code=302)


@app.get("/projects")
async def projects_redirect(request: Request):
    """WF-3: /projects is the canonical full-table view (alias for /projects/browse)."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    return RedirectResponse(url="/projects/browse", status_code=302)


@app.get("/known-limitations")
async def known_limitations_page(request: Request):
    """U6: standalone Known Limitations page, reachable from Help and footer."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    return templates.TemplateResponse(
        request=request,
        name="known_limitations_page.html",
        context={"user": user},
    )


@app.get("/pilot-guide")
async def pilot_guide_page(request: Request):
    """EXTERNAL-FRIENDLY-PILOT-PREP-A: standalone Pilot Guide page,
    reachable from Help and the footer. Renders the existing
    docs/external_pilot_guide.md content; presentation only."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    guide_path = pathlib.Path(__file__).resolve().parent / "docs" / "external_pilot_guide.md"
    guide_text = guide_path.read_text()
    return templates.TemplateResponse(
        request=request,
        name="pilot_guide_page.html",
        context={"user": user, "guide_text": guide_text},
    )


@app.get("/help")
async def help_page(request: Request):
    """Redirect the header Help link to the project browser's Help/Guidance entry point."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    return RedirectResponse(url="/projects/browse", status_code=302)


@app.get("/projects/browse")
async def project_browser(request: Request):
    """Render project browser partial — factory templates, baselines, user projects."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    baseline_records = seed_baseline_projects_if_needed(user.user_id)
    baseline_project_items = [
        {
            "project_code": r.project_code,
            "label": r.project_name,
            "meta": f"{r.project_type or 'Unknown'} · baseline",
            "is_readonly": r.is_readonly,
        }
        for r in list_baseline_records(user.user_id)
    ]

    return templates.TemplateResponse(
        request=request,
        name="project_browse_page.html",
        context={
            # Phase P2-FIX-1: single consolidated project
            # list (presentation only).
            "consolidated_project_records": _consolidated_project_records(user),
            "factory_template_projects": FACTORY_TEMPLATE_OPTIONS,
            "baseline_project_records": baseline_project_items,
            "user_project_records": _user_project_selector_items(user),
            "my_project_cards": _my_project_cards(user),
            "example_project_cards": _example_project_cards(),
            "active_project_code": request.query_params.get("active") or "",
        },
    )


@app.post("/projects/create")
async def create_project_route(
    request: Request,
    project_name: str = Form(...),
    project_type: str = Form(...),
    template_source: str = Form(""),
    country_market: str = Form("Generic Market A"),
    capacity_mw: str = Form(""),
    cod_date: str = Form(""),
    construction_months: str = Form(""),
    horizon_years: str = Form(""),
    tariff_eur_mwh: str = Form(""),
    ppa_term_years: str = Form(""),
    p50_hours: str = Form(""),
    opex_y1_keur: str = Form(""),
    total_capex_keur: str = Form(""),
    gearing_pct: str = Form(""),
    interest_rate_pct: str = Form(""),
    tenor_years: str = Form(""),
    target_dscr: str = Form("1.20"),
):
    """Create a new project.

    Thin orchestration wrapper (Phase 51M-2). The route is
    responsible for auth, FastAPI Form() injection, building the
    submitted dict from form values, deps bundle construction, and
    final response rendering. The full /projects/create
    orchestration body (text coercion, project type
    canonicalization, template source normalization, payload
    validation, template source validation, project code
    slugification and uniqueness loop, baseline snapshot
    construction, project record creation, workspace state
    initialization, response context assembly with HX-Redirect
    header) lives in
    ``app.services.projects_create_service.execute_projects_create_route``.

    Phase 56D: COD is ALWAYS derived server-side from
    ``construction_start_date + construction_duration_months`` (the
    two new form fields added in 56C). Manual COD override is
    NOT supported in 56D — a manually supplied cod_date in the
    form body is IGNORED when derivation succeeds. A future
    manual override would require explicit audited override
    logic and is out of scope here. The 56D logic lives in
    ``_apply_56d_extras_to_submitted``.
    """
    from app.services.projects_create_service import (
        ProjectsCreateRouteDeps,
        execute_projects_create_route,
    )

    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    # P6.7 — demo session rate limiting for project creation
    if user.is_demo:
        allowed, retry_after = check_demo_rate_limit(user.user_id, "project_create")
        if not allowed:
            return templates.TemplateResponse(
                request=request,
                name="errors.html",
                context={
                    "error_title": "Project limit reached",
                    "error_message": (
                        f"Demo sessions are limited to 5 new projects per hour. "
                        f"Try again in {retry_after}s."
                    ),
                },
                status_code=429,
            )

    # Build submitted dict from defaults + form values
    submitted = _submitted_new_project_defaults()
    submitted.update(
        {
            "project_name": project_name,
            "project_type": project_type,
            "template_source": template_source,
            "country_market": country_market,
            "capacity_mw": capacity_mw,
            "cod_date": cod_date,
            "construction_months": construction_months,
            "horizon_years": horizon_years,
            "tariff_eur_mwh": tariff_eur_mwh,
            "ppa_term_years": ppa_term_years,
            "p50_hours": p50_hours,
            "opex_y1_keur": opex_y1_keur,
            "total_capex_keur": total_capex_keur,
            "gearing_pct": gearing_pct,
            "interest_rate_pct": interest_rate_pct,
            "tenor_years": tenor_years,
            "target_dscr": target_dscr,
        }
    )
    # Phase 56C + 56D: capture the 4 extra form fields (added in 56C
    # but NOT in the 51M-1 frozen route signature) by parsing the
    # raw body. Helpers do the heavy lifting so the route body
    # stays slim (60-110 non-blank line ceiling).
    extra = await _read_optional_form_fields(request)
    _apply_56d_extras_to_submitted(submitted, extra)

    deps = ProjectsCreateRouteDeps(
        submitted_new_project_defaults=_submitted_new_project_defaults,
        coerce_form_text=_coerce_form_text,
        canonical_project_type=_canonical_project_type,
        normalize_template_source=_normalize_template_source,
        validate_new_project_payload=_validate_new_project_payload,
        slugify_project_code=_slugify_project_code,
        get_project_by_code=get_project_by_code,
        project_baseline_snapshot=_project_baseline_snapshot,
        apply_new_project_required_inputs=_apply_new_project_required_inputs,
        create_project_record=create_project_record,
        save_workspace_state=save_workspace_state,
        get_or_create_base_case_scenario=get_or_create_base_case_scenario,
        governance_snapshot=_governance_snapshot,
        replay_metadata_for_project=_replay_metadata_for_project,
        new_project_validation_error_context=_new_project_validation_error_context,
        new_project_minimal_validation_error_context=_new_project_minimal_validation_error_context,
        template_source_label=_template_source_label,
        render_template_response=templates.TemplateResponse,
    )
    outcome = await execute_projects_create_route(
        request=request, submitted=submitted, user=user, deps=deps,
    )
    # For non-HTMX browsers, translate HX-Redirect into a real 303.
    if outcome.status_code == 200 and outcome.headers and "HX-Redirect" in outcome.headers:
        if request.headers.get("HX-Request") != "true":
            return RedirectResponse(url=outcome.headers["HX-Redirect"], status_code=303)
    return templates.TemplateResponse(
        request=request,
        name=outcome.template_name,
        context=outcome.context,
        status_code=outcome.status_code,
        headers=outcome.headers or None,
    )


@app.get("/scenarios")
async def list_scenarios_endpoint(request: Request, project: str = "generic_wind_reference"):
    """Render the saved scenario and export-history workspace for the active project."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    project_record = _resolve_project_record(user, project)
    project_record, workspace_state, scenarios, history, exports, export_lineage, scenario_summary_cards = _current_project_workspace(user, project_record)
    compare_result = base_vs_active_compare(user.user_id, project_record.project_id) if workspace_state else None
    return _render_scenario_workspace(
        request,
        user,
        project_record,
        workspace_state,
        scenarios,
        history,
        exports,
        export_lineage,
        scenario_summary_cards,
        compare_result=compare_result,
    )


@app.post("/scenarios/state/draft")
async def save_workspace_draft_endpoint(request: Request):
    """Persist unsaved workspace edits (thin route; orchestration in
    app.services.scenario_state_route_service.execute_draft_route)."""
    from app.services.scenario_state_route_service import (
        ScenarioStateRouteDeps,
        execute_draft_route,
    )
    from app.services.project_library_service import is_protected_reference
    from app.ui.protected_reference_service import first_edit_response
    from app.persistence.repository import (
        get_project_record as gpr_for_p2fix3_guard,
    )

    user = get_current_user(request)
    if not user:
        return JSONResponse({"error": "Login required"}, status_code=401)

    form = await request.form()

    # ── P2-FIX-8 PR3: Transparent copy-on-first-save ────────────
    # If the active project is a protected reference (Generic Wind Reference /
    # Generic Solar Reference), automatically route through the copy mechanism
    # instead of returning 409. The user's first Save lands in
    # their working copy — no explicit button needed.
    #
    # Dedup: if a working copy of the same source already exists
    # for this user, redirect to that instead of creating a new one.
    try:
        active_project_code = (
            form.get("active_project")
            or form.get("project_code")
            or ""
        )
        if active_project_code:
            guard_record = gpr_for_p2fix3_guard(
                user_id=user.user_id, project_code=active_project_code
            )
            if is_protected_reference(guard_record):
                # Dedup: redirect to existing copy if one exists
                existing = _find_existing_working_copy(
                    user.user_id, active_project_code
                )
                if existing:
                    from app.utils.workbook_flag import project_workbook_url as _pwurl
                    redirect_url = _pwurl(existing.project_code)
                    return JSONResponse(
                        {"redirect": redirect_url},
                        status_code=200,
                        headers={"HX-Redirect": redirect_url},
                    )
                # No existing copy — create one transparently
                redirect_url = (
                    f"/projects/{active_project_code}/confirm-first-edit-copy"
                )
                return JSONResponse(
                    {"redirect": redirect_url},
                    status_code=200,
                    headers={"HX-Redirect": redirect_url},
                )
    except Exception:
        pass

    deps = ScenarioStateRouteDeps(
        collect_form_snapshot=_collect_form_snapshot,
        project_workspace_from_snapshot=_project_workspace_from_snapshot,
        save_workspace_state=save_workspace_state,
        discard_workspace_draft=discard_workspace_draft,
        snapshots_equal=snapshots_equal,
        default_workspace_snapshot=_default_workspace_snapshot,
        governance_snapshot=_governance_snapshot,
        replay_metadata_for_project=_replay_metadata_for_project,
        workspace_state_meta=_workspace_state_meta,
    )
    outcome = await execute_draft_route(
        request=request, form=form, user=user, deps=deps,
    )
    if outcome.is_redirect:
        return RedirectResponse(
            url=outcome.redirect_url or "/login",
            status_code=outcome.status_code,
        )
    return JSONResponse(
        content=outcome.payload,
        status_code=outcome.status_code,
        headers=outcome.headers or None,
    )


@app.post("/scenarios/state/discard")
async def discard_workspace_draft_endpoint(request: Request):
    """Discard unsaved workspace edits (thin route; orchestration in
    app.services.scenario_state_route_service.execute_discard_route)."""
    from app.services.scenario_state_route_service import (
        ScenarioStateRouteDeps,
        execute_discard_route,
    )

    user = get_current_user(request)
    if not user:
        return JSONResponse({"error": "Login required"}, status_code=401)

    form = await request.form()
    deps = ScenarioStateRouteDeps(
        collect_form_snapshot=_collect_form_snapshot,
        project_workspace_from_snapshot=_project_workspace_from_snapshot,
        save_workspace_state=save_workspace_state,
        discard_workspace_draft=discard_workspace_draft,
        snapshots_equal=snapshots_equal,
        default_workspace_snapshot=_default_workspace_snapshot,
        governance_snapshot=_governance_snapshot,
        replay_metadata_for_project=_replay_metadata_for_project,
        workspace_state_meta=_workspace_state_meta,
    )
    outcome = await execute_discard_route(
        request=request, form=form, user=user, deps=deps,
    )
    if outcome.is_redirect:
        return RedirectResponse(
            url=outcome.redirect_url or "/login",
            status_code=outcome.status_code,
        )
    return JSONResponse(
        content=outcome.payload,
        status_code=outcome.status_code,
        headers=outcome.headers or None,
    )


@app.get("/scenarios/history")
async def scenario_history_endpoint(request: Request, project: str = "generic_wind_reference"):
    """Refresh scenario history and lineage for the active project."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    project_record = _resolve_project_record(user, project)
    project_record, workspace_state, _, _, _, _, _ = _current_project_workspace(user, project_record)
    scenarios, history, exports, export_lineage, scenario_summary_cards, dirty_state_ui, scenario_workflow_ui, project_review_ui = _workspace_refresh_payload(user, project_record, workspace_state)
    return _render_scenario_workspace(
        request,
        user,
        project_record,
        workspace_state,
        scenarios,
        history,
        exports,
        export_lineage,
        scenario_summary_cards,
        dirty_state_ui=dirty_state_ui,
        scenario_workflow_ui=scenario_workflow_ui,
        project_review_ui=project_review_ui,
        message="Refreshed scenario history and export lineage.",
    )


@app.get("/scenarios/compare")
async def scenario_compare_endpoint(
    request: Request,
    project: str = "generic_wind_reference",
    left_scenario_id: str | None = None,
    right_scenario_id: str | None = None,
):
    """Render a lightweight, governance-aware scenario comparison."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    project_record = _resolve_project_record(user, project)
    project_record, workspace_state, _, _, _, _, _ = _current_project_workspace(user, project_record)
    scenarios, history, exports, export_lineage, scenario_summary_cards, dirty_state_ui, scenario_workflow_ui, project_review_ui = _workspace_refresh_payload(user, project_record, workspace_state)
    compare_result = None
    message = "Select two saved scenarios to compare."
    if left_scenario_id and right_scenario_id:
        # P1-COMPARE-VALIDATION: validate ownership before comparing.
        # Both scenarios must exist, belong to the same user, and belong to
        # the project currently loaded in the workspace. Without this check a
        # caller could pass scenario IDs from a different project and get back
        # a misleading "Scenario compare ready" banner with no numeric data.
        _left_sc = get_scenario(left_scenario_id, user.user_id)
        _right_sc = get_scenario(right_scenario_id, user.user_id)
        _project_id = project_record.project_id if project_record else None
        if _left_sc is None or _right_sc is None:
            message = "One or both scenarios could not be found."
        elif _left_sc.project_id != _project_id or _right_sc.project_id != _project_id:
            message = "Selected scenarios do not belong to the same project."
        else:
            compare_result = compare_scenarios(user.user_id, left_scenario_id, right_scenario_id)
            if compare_result is None:
                message = "Could not compare those scenarios."
            else:
                compare_result = _build_compare_ui_context(compare_result, workspace_state)
                message = "Scenario compare ready. Review numeric deltas together with governance posture."

    return _render_scenario_workspace(
        request,
        user,
        project_record,
        workspace_state,
        scenarios,
        history,
        exports,
        export_lineage,
        scenario_summary_cards,
        dirty_state_ui=dirty_state_ui,
        scenario_workflow_ui=scenario_workflow_ui,
        project_review_ui=project_review_ui,        message=message,
        compare_result=compare_result,
    )


@app.get("/scenarios/compare-panel")
async def scenario_compare_panel_endpoint(
    request: Request,
    project: str = "",
    left_scenario_id: str | None = None,
    right_scenario_id: str | None = None,
):
    """UX-2G-COMPARE-FIX: HTMX-only fragment for the in-workspace Compare tab.

    Returns just the ``scenario_compare.html`` markup (no shell, no
    ``<head>``) so the "Compare with X" shortcut and the Compare tab
    can swap content into ``#panel-compare`` without ever leaving the
    SPA. Unlike the legacy ``/scenarios/compare`` route, ``project``
    has no silent default here -- a missing/blank project resolves to
    the empty-state fragment rather than guessing a project, which is
    what previously let scenarios from the wrong project (e.g. generic_wind_reference)
    leak into the comparison.
    """
    user = get_current_user(request)
    if not user:
        return HTMLResponse(
            '<div class="ps-mini-empty" data-testid="compare-empty-state">'
            '<div class="ps-history-item"><div class="ps-history-title">Session expired</div>'
            '<div class="ps-history-meta">Sign in again to compare scenarios.</div></div></div>',
            status_code=401,
        )

    compare_result = None
    if project and left_scenario_id and right_scenario_id:
        project_record = _resolve_project_record(user, project)
        _project_id = project_record.project_id if project_record else None
        _left_sc = get_scenario(left_scenario_id, user.user_id)
        _right_sc = get_scenario(right_scenario_id, user.user_id)
        if (
            _left_sc is not None
            and _right_sc is not None
            and _project_id is not None
            and _left_sc.project_id == _project_id
            and _right_sc.project_id == _project_id
        ):
            _, workspace_state, _, _, _, _, _ = _current_project_workspace(user, project_record)
            raw_compare_result = compare_scenarios(user.user_id, left_scenario_id, right_scenario_id)
            if raw_compare_result is not None:
                compare_result = _build_compare_ui_context(raw_compare_result, workspace_state)

    return templates.TemplateResponse(
        request=request,
        name="partials/scenario_compare.html",
        context={
            "compare_panel": True,
            "compare_result": compare_result,
            "audit_mode": False,
        },
    )


# ── Phase 25B-2 — Multi-scenario compare (2-4 scenarios) ────────────────
@app.get("/scenarios/compare-multi")
async def scenario_compare_multi_endpoint(
    request: Request,
    project: str = "generic_wind_reference",
    scenario_ids: str = "",
):
    """Render a multi-scenario comparison (Base / Downside / Upside / Custom).

    Phase 25B-2. Read-only. Accepts a comma-separated list of 2-4
    scenario_ids via the ``scenario_ids`` query string parameter. The
    first scenario in the list is treated as the base reference for
    deltas. Soft-error semantics: invalid input (empty / <2 / >4 /
    unresolved ids) returns a 200 response with an explicit
    ``error_state`` so the UI can show a clear message instead of
    a 500.
    """
    from app.persistence.exports_repository import (
        compare_multi_scenarios,
        MULTI_COMPARE_MIN_SCENARIOS,
        MULTI_COMPARE_MAX_SCENARIOS,
    )

    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    project_record = _resolve_project_record(user, project)
    project_record, workspace_state, scenarios, history, exports, export_lineage, scenario_summary_cards = (
        _current_project_workspace(user, project_record)
    )

    # Parse scenario_ids (comma-separated)
    parsed_ids: list[str] = []
    if scenario_ids:
        for piece in scenario_ids.split(","):
            piece = piece.strip()
            if piece:
                parsed_ids.append(piece)

    error_state: Optional[str] = None
    if not parsed_ids:
        error_state = (
            f"Select between {MULTI_COMPARE_MIN_SCENARIOS} and "
            f"{MULTI_COMPARE_MAX_SCENARIOS} saved scenarios to compare."
        )
    elif len(parsed_ids) < MULTI_COMPARE_MIN_SCENARIOS:
        error_state = (
            f"Multi-compare needs at least {MULTI_COMPARE_MIN_SCENARIOS} "
            f"scenarios; you provided {len(parsed_ids)}."
        )
    elif len(parsed_ids) > MULTI_COMPARE_MAX_SCENARIOS:
        error_state = (
            f"Multi-compare supports at most {MULTI_COMPARE_MAX_SCENARIOS} "
            f"scenarios; you provided {len(parsed_ids)}."
        )
    elif len(set(parsed_ids)) != len(parsed_ids):
        error_state = "Multi-compare does not allow duplicate scenario_ids."

    multi_compare_result = None
    if not error_state:
        multi_compare_result = compare_multi_scenarios(user.user_id, parsed_ids)
        if multi_compare_result is None:
            error_state = (
                "One or more scenario_ids could not be resolved for the "
                "current user. Check that the scenarios exist and belong "
                "to the same project."
            )

    return _render_scenario_workspace(
        request,
        user,
        project_record,
        workspace_state,
        scenarios,
        history,
        exports,
        export_lineage,
        scenario_summary_cards,
        message=error_state or (
            f"Multi-scenario compare ready across {len(parsed_ids)} scenarios. "
            "Review numeric deltas together with governance posture."
        ),
        multi_compare_result=multi_compare_result,
        multi_compare_error=error_state,
        multi_compare_parsed_ids=parsed_ids,
    )


# ── V4-2 Part B — Input Difference Viewer ────────────────────────────────
@app.get("/scenarios/input-diff")
async def scenario_input_diff_endpoint(
    request: Request,
    project: str = "generic_wind_reference",
    base_id: str = "",
    other_id: str = "",
):
    """Show field-level input differences between two saved scenarios.

    V4-2 Part B. Read-only; no model execution. Diffs the flat snapshot
    dicts of base vs other scenario and renders changed fields highlighted.
    """
    from app.persistence.exports_repository import diff_scenario_inputs

    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    project_record = _resolve_project_record(user, project)
    project_record, workspace_state, scenarios, history, exports, export_lineage, scenario_summary_cards = (
        _current_project_workspace(user, project_record)
    )

    error_state: str | None = None
    diff_result = None

    if not base_id or not other_id:
        error_state = "Provide base_id and other_id query parameters to compare two scenarios."
    elif base_id == other_id:
        error_state = "base_id and other_id must be different scenarios."
    else:
        diff_result = diff_scenario_inputs(user.user_id, base_id, other_id)
        if diff_result is None:
            error_state = "One or both scenario IDs could not be resolved for the current user."

    return _render_scenario_workspace(
        request,
        user,
        project_record,
        workspace_state,
        scenarios,
        history,
        exports,
        export_lineage,
        scenario_summary_cards,
        message=error_state or f"Input diff: {diff_result['changed_count']} fields changed." if diff_result else error_state,
        input_diff_result=diff_result,
        input_diff_error=error_state,
    )


# ── V4-2 Part D — Financial Statements Compare ───────────────────────────
@app.get("/scenarios/fs-compare")
async def scenario_fs_compare_endpoint(
    request: Request,
    project: str = "generic_wind_reference",
    scenario_ids: str = "",
):
    """Run canonical engine per scenario and show FS side-by-side.

    V4-2 Part D. Accepts comma-separated list of exactly 2 scenario_ids.
    Re-runs the engine for each using the saved snapshot (no persistence
    side effects). Uses assemble_financial_statements() — same formulas
    as the institutional workbook.
    """
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    project_record = _resolve_project_record(user, project)
    project_record, workspace_state, scenarios, history, exports, export_lineage, scenario_summary_cards = (
        _current_project_workspace(user, project_record)
    )

    parsed_ids: list[str] = [p.strip() for p in scenario_ids.split(",") if p.strip()]
    error_state: str | None = None
    fs_compare = None

    if len(parsed_ids) != 2:
        error_state = "FS compare requires exactly 2 scenario IDs."
    else:
        try:
            from app.persistence.repository import get_scenario
            from app.input_adapter import build_projectinputs_from_snapshot
            from app.services.production_waterfall_seam import classify_or_fail

            records = []
            statements_per_scenario: list[Any] = []
            for sid in parsed_ids:
                rec = get_scenario(sid, user.user_id)
                if rec is None:
                    raise ValueError(f"Scenario {sid} not found.")
                records.append(rec)
                snap = dict(rec.snapshot or {})
                proj = build_projectinputs_from_snapshot(snap)
                # Phase B4: financial-statements assembly is a historical
                # legacy-runtime concept and is NOT part of the clean G2C
                # production authority. FS Compare is explicitly
                # feature-unavailable on the production surface for every
                # classification — the legacy waterfall is NEVER run merely
                # to preserve this screen (typed reason returned instead).
                decision = classify_or_fail(proj)
                raise ValueError(
                    "FS_COMPARE_NOT_AVAILABLE_ON_PRODUCTION_RUNTIME: "
                    "financial-statements comparison is not provided by the "
                    "clean G2C production authority (classification "
                    f"{decision.classification.value}, reason "
                    f"{decision.reason_code}). No legacy runtime exists on "
                    "this route."
                )

            # Build comparison rows for PnL, Balance Sheet, Cash Waterfall
            def _fs_rows_pnl(fs_list):
                rows = [{"label": "Income Statement (P&L)", "is_section": True}]
                fields = [
                    ("Revenue (kEUR)", "revenues_keur"),
                    ("OpEx (kEUR)", "operating_expenses_keur"),
                    ("Depreciation (kEUR)", "depreciation_keur"),
                    ("EBIT (kEUR)", "ebit_keur"),
                    ("Senior Interest (kEUR)", "senior_interest_expense_keur"),
                    ("SHL Interest (kEUR)", "shl_interest_expense_keur"),
                    ("EBT (kEUR)", "earnings_before_tax_keur"),
                    ("CIT Accrual (kEUR)", "cit_accrual_keur"),
                    ("Net Income (kEUR)", "net_income_keur"),
                ]
                periods_count = min(len(fs.pnl.periods) for fs in fs_list)
                for label, attr in fields:
                    totals = [round(sum(getattr(p, attr, 0.0) for p in fs.pnl.periods[:periods_count]), 1) for fs in fs_list]
                    rows.append({"label": f"{label} (total)", "values": totals})
                return rows

            def _fs_rows_bs(fs_list):
                rows = [{"label": "Balance Sheet (final period)", "is_section": True}]
                fields = [
                    ("Net Fixed Assets (kEUR)", "net_fixed_assets_keur"),
                    ("Cash (kEUR)", "cash_keur"),
                    ("Total Assets (kEUR)", "total_assets_keur"),
                    ("Share Capital (kEUR)", "share_capital_keur"),
                    ("Retained Earnings (kEUR)", "retained_earnings_keur"),
                    ("SHL Balance (kEUR)", "shl_balance_keur"),
                    ("Senior Balance (kEUR)", "senior_balance_keur"),
                    ("Total Liabilities & Equity (kEUR)", "total_liabilities_and_equity_keur"),
                ]
                for label, attr in fields:
                    vals = [round(getattr(fs.balance_sheet.periods[-1], attr, 0.0), 1) if fs.balance_sheet.periods else 0.0 for fs in fs_list]
                    rows.append({"label": label, "values": vals})
                return rows

            def _fs_rows_cf(fs_list):
                rows = [{"label": "Cash Flow Waterfall (total)", "is_section": True}]
                fields = [
                    ("EBITDA (kEUR)", "ebitda_cash_keur"),
                    ("Senior DS (kEUR)", "senior_total_ds_keur"),
                    ("FCF for Dividends (kEUR)", "fcf_for_dividends_keur"),
                    ("Net Dividends (kEUR)", "net_dividends_keur"),
                ]
                periods_count = min(len(fs.pf_cash_waterfall.periods) for fs in fs_list)
                for label, attr in fields:
                    totals = [round(sum(getattr(p, attr, 0.0) for p in fs.pf_cash_waterfall.periods[:periods_count]), 1) for fs in fs_list]
                    rows.append({"label": label, "values": totals})
                return rows

            combined_rows = {
                "Income Statement": _fs_rows_pnl(statements_per_scenario),
                "Balance Sheet": _fs_rows_bs(statements_per_scenario),
                "Cash Flow": _fs_rows_cf(statements_per_scenario),
            }
            fs_compare = {
                "scenarios": records,
                "statements": combined_rows,
                "sheet_names": ["Income Statement", "Balance Sheet", "Cash Flow"],
            }
        except Exception as exc:
            error_state = f"FS compare failed: {exc}"

    return _render_scenario_workspace(
        request,
        user,
        project_record,
        workspace_state,
        scenarios,
        history,
        exports,
        export_lineage,
        scenario_summary_cards,
        message=error_state or "Financial statements compare ready.",
        fs_compare_result=fs_compare,
        fs_compare_error=error_state,
    )


# ── V4-3 — Sensitivity & Tornado Analysis ────────────────────────────────

_SENSITIVITY_DEFAULT_SHOCKS = [
    "capex", "opex", "ppa_price", "merchant_price",
    "yield", "availability", "interest_rate", "tax_rate",
]
_SENSITIVITY_DEFAULT_LEVELS = [-15.0, -10.0, -5.0, 5.0, 10.0, 15.0]
_SENSITIVITY_DEFAULT_TORNADO_KPI = "equity_irr"


def _resolve_sensitivity_project(user, project: str, scenario_id: str = "") -> Any:
    """Resolve ProjectInputs for the sensitivity run.

    Uses the named scenario's snapshot if provided, otherwise uses the
    factory base for the named project (generic_wind_reference/generic_solar_reference/generic).
    """
    if scenario_id:
        from app.persistence.repository import get_scenario
        from app.input_adapter import build_projectinputs_from_snapshot
        rec = get_scenario(scenario_id, user.user_id)
        if rec is not None and rec.snapshot:
            return build_projectinputs_from_snapshot(dict(rec.snapshot)), (rec.scenario_name if rec else "Base")
    # Fall back to factory base
    p = project.lower()
    if p == "generic_solar_reference":
        from app.project_factories import create_generic_solar_reference
        return create_generic_solar_reference(), "Generic Solar Reference (factory)"
    if p in {"generic_data_center_reference", "generic_data_center"}:
        from app.project_factories import create_generic_data_center_reference
        return create_generic_data_center_reference(), "Generic Data Center Reference (factory)"
    from app.project_factories import create_generic_wind_reference
    return create_generic_wind_reference(), "Generic Wind Reference"


@app.get("/scenarios/sensitivity")
async def scenario_sensitivity_endpoint(
    request: Request,
    project: str = "generic_wind_reference",
    scenario_id: str = "",
    shocks: str = "",
    levels: str = "",
    tornado_kpi: str = _SENSITIVITY_DEFAULT_TORNADO_KPI,
):
    """Run sensitivity analysis and render results including tornado chart.

    V4-3 Parts A–C. Read-only; no persistence side effects.
    shocks: comma-separated shock keys (defaults to all 8)
    levels: comma-separated signed percentages (defaults to ±5/10/15%)
    """
    from app.services.sensitivity_service import (
        run_sensitivity, build_tornado_data, SHOCK_REGISTRY, KPI_DEFS,
    )

    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    project_record = _resolve_project_record(user, project)
    project_record, workspace_state, scenarios, history, exports, export_lineage, scenario_summary_cards = (
        _current_project_workspace(user, project_record)
    )

    shock_types = [s.strip() for s in shocks.split(",") if s.strip()] or _SENSITIVITY_DEFAULT_SHOCKS
    shock_types = [s for s in shock_types if s in SHOCK_REGISTRY]
    shock_levels = []
    if levels:
        for v in levels.split(","):
            try:
                shock_levels.append(float(v.strip()))
            except ValueError:
                pass
    if not shock_levels:
        shock_levels = _SENSITIVITY_DEFAULT_LEVELS

    error_state: str | None = None
    sens_result = None
    tornado = None
    scenario_name = "Base"

    try:
        proj, scenario_name = _resolve_sensitivity_project(user, project, scenario_id)
        sens_result = run_sensitivity(proj, shock_types, shock_levels)
        tornado = build_tornado_data(sens_result, kpi_key=tornado_kpi)
    except Exception as exc:
        error_state = _friendly_error(exc, "sensitivity analysis")

    # Tornado KPI label and format hint
    kpi_label_map = {k: lbl for k, lbl, _ in (sens_result["kpi_defs"] if sens_result else KPI_DEFS)}
    kpi_fmt_map = {k: fmt for k, _, fmt in (sens_result["kpi_defs"] if sens_result else KPI_DEFS)}
    tornado_kpi_label = kpi_label_map.get(tornado_kpi, tornado_kpi)
    tornado_kpi_is_pct = kpi_fmt_map.get(tornado_kpi, "") == "pct"

    # Build export URLs
    _base_url = f"/scenarios/sensitivity/export?project={project}&scenario_id={scenario_id}&shocks={shocks}&levels={levels}&tornado_kpi={tornado_kpi}"
    csv_url = _base_url + "&fmt=csv"
    xlsx_url = _base_url + "&fmt=xlsx"

    extra = {
        "sensitivity_scenario_name": scenario_name,
        "sensitivity_shock_types": shock_types,
        "sensitivity_levels": shock_levels,
        "tornado_data": tornado or [],
        "tornado_kpi_label": tornado_kpi_label,
        "tornado_kpi_is_pct": tornado_kpi_is_pct,
        "sensitivity_export_csv_url": csv_url,
        "sensitivity_export_xlsx_url": xlsx_url,
    }

    return _render_scenario_workspace(
        request,
        user,
        project_record,
        workspace_state,
        scenarios,
        history,
        exports,
        export_lineage,
        scenario_summary_cards,
        message=error_state or f"Sensitivity analysis complete — {len(sens_result['rows']) if sens_result else 0} scenarios.",
        sensitivity_result=sens_result,
        sensitivity_error=error_state,
        sensitivity_extra=extra,
    )


@app.get("/scenarios/sensitivity/export")
async def scenario_sensitivity_export_endpoint(
    request: Request,
    project: str = "generic_wind_reference",
    scenario_id: str = "",
    shocks: str = "",
    levels: str = "",
    tornado_kpi: str = _SENSITIVITY_DEFAULT_TORNADO_KPI,
    fmt: str = "csv",
):
    """Export sensitivity results as CSV or Excel.

    V4-3 Part D. Read-only; no persistence side effects.
    """
    from fastapi.responses import Response
    from app.services.sensitivity_service import (
        run_sensitivity, export_sensitivity_csv, export_sensitivity_xlsx, SHOCK_REGISTRY,
    )

    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    shock_types = [s.strip() for s in shocks.split(",") if s.strip()] or _SENSITIVITY_DEFAULT_SHOCKS
    shock_types = [s for s in shock_types if s in SHOCK_REGISTRY]
    shock_levels = []
    if levels:
        for v in levels.split(","):
            try:
                shock_levels.append(float(v.strip()))
            except ValueError:
                pass
    if not shock_levels:
        shock_levels = _SENSITIVITY_DEFAULT_LEVELS

    try:
        proj, _ = _resolve_sensitivity_project(user, project, scenario_id)
        sens_result = run_sensitivity(proj, shock_types, shock_levels)
    except Exception as exc:
        _logger.exception("Sensitivity export failed: %s", exc)
        return Response(content="Export failed — please check your inputs.", status_code=500, media_type="text/plain")

    if fmt == "xlsx":
        content = export_sensitivity_xlsx(sens_result)
        return Response(
            content=content,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": "attachment; filename=sensitivity.xlsx"},
        )

    # Default: CSV
    content = export_sensitivity_csv(sens_result)
    return Response(
        content=content,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=sensitivity.csv"},
    )


# ── V4-4 — Lender Case, Covenant Dashboard, Credit Summary ───────────────

def _resolve_lender_project(user, project: str, scenario_id: str = ""):
    """Resolve ProjectInputs for lender case / covenant runs."""
    from app.services.sensitivity_service import _resolve_sensitivity_project as _rsp
    return _rsp(user, project, scenario_id)


@app.get("/scenarios/lender-case")
async def scenario_lender_case_endpoint(
    request: Request,
    project: str = "",
    scenario_id: str = "",
    yield_p90: float = 0.0,
    yield_haircut: float = 0.0,
    ppa_haircut: float = 0.0,
    merchant_haircut: float = 0.0,
    capex_contingency: float = 0.0,
    opex_contingency: float = 0.0,
    interest_stress: float = 0.0,
    inflation_stress: float = 0.0,
    availability_stress: float = 0.0,
):
    """Run engine under lender-stress adjustments, compare vs base.

    V4-4 Part A. Read-only; no persistence side effects.
    """
    from app.services.lender_case_service import run_lender_case
    from app.services.reporting_kpi_sources import build_canonical_report_kpis

    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    adjustments = {
        "yield_p90": yield_p90,
        "yield_haircut": yield_haircut,
        "ppa_haircut": ppa_haircut,
        "merchant_haircut": merchant_haircut,
        "capex_contingency": capex_contingency,
        "opex_contingency": opex_contingency,
        "interest_stress": interest_stress,
        "inflation_stress": inflation_stress,
        "availability_stress": availability_stress,
    }

    lc_result = None
    lc_error = None
    base_kpis = None
    scenario_name = ""

    try:
        proj, scenario_name = _resolve_lender_project(user, project, scenario_id)

        # Base run for comparison KPIs — PR-8 production authority seam
        # (clean G2C for clean-ready projects; explicit legacy for blocked).
        from app.services.production_waterfall_seam import execute_production_waterfall

        base_execution = execute_production_waterfall(proj)
        base_kpis = build_canonical_report_kpis(base_execution.result)

        lc_result = run_lender_case(proj, adjustments)
    except Exception as exc:
        lc_error = _friendly_error(exc, "lender case")

    project_record = _resolve_project_record(user, project)
    project_record, workspace_state, scenarios, history, exports, export_lineage, scenario_summary_cards = (
        _current_project_workspace(user, project_record)
    )
    return _render_scenario_workspace(
        request, user, project_record, workspace_state,
        scenarios, history, exports, export_lineage, scenario_summary_cards,
        lender_case_result=lc_result,
        lender_case_error=lc_error,
        lender_base_kpis=base_kpis,
        lender_scenario_name=scenario_name,
    )


@app.get("/scenarios/covenant")
async def scenario_covenant_endpoint(
    request: Request,
    project: str = "",
    scenario_id: str = "",
):
    """Show per-period DSCR/LLCR/PLCR covenant analytics with RAG status.

    V4-4 Parts B & D. Read-only; no persistence side effects.
    """
    from app.services.lender_case_service import (
        build_covenant_periods,
        DSCR_EVENT_OF_DEFAULT, DSCR_LOCKUP, DSCR_DISTRIBUTION, DSCR_CASH_SWEEP,
    )

    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    cov_periods = None
    cov_error = None
    thresholds = {
        "event_of_default": DSCR_EVENT_OF_DEFAULT,
        "lockup": DSCR_LOCKUP,
        "distribution": DSCR_DISTRIBUTION,
        "cash_sweep": DSCR_CASH_SWEEP,
    }

    try:
        proj, _ = _resolve_lender_project(user, project, scenario_id)
        # PR-8 production authority seam (clean G2C for clean-ready projects;
        # explicitly-classified legacy calibration for blocked projects).
        from app.services.production_waterfall_seam import execute_production_waterfall

        execution = execute_production_waterfall(proj)
        cov_periods = build_covenant_periods(execution.result)
    except Exception as exc:
        cov_error = _friendly_error(exc, "covenant analytics")

    project_record = _resolve_project_record(user, project)
    project_record, workspace_state, scenarios, history, exports, export_lineage, scenario_summary_cards = (
        _current_project_workspace(user, project_record)
    )
    return _render_scenario_workspace(
        request, user, project_record, workspace_state,
        scenarios, history, exports, export_lineage, scenario_summary_cards,
        covenant_periods=cov_periods,
        covenant_error=cov_error,
        covenant_thresholds=thresholds,
    )


@app.get("/scenarios/credit-summary")
async def scenario_credit_summary_endpoint(
    request: Request,
    project: str = "",
    scenario_id: str = "",
    lender_yield_haircut: float = 0.0,
    lender_ppa_haircut: float = 0.0,
    lender_capex_contingency: float = 0.0,
    lender_opex_contingency: float = 0.0,
):
    """Generate one-page printable credit summary for lenders.

    V4-4 Part C. Base + optional lender case side-by-side.
    Read-only; no persistence side effects.
    """
    from app.services.lender_case_service import (
        build_credit_summary, run_lender_case,
    )
    from app.services.reporting_kpi_sources import build_canonical_report_kpis

    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    cs = None
    cs_error = None

    try:
        proj, _ = _resolve_lender_project(user, project, scenario_id)
        # PR-8 production authority seam (clean G2C for clean-ready projects).
        from app.services.production_waterfall_seam import execute_production_waterfall

        base_execution = execute_production_waterfall(proj)
        base_kpis = build_canonical_report_kpis(base_execution.result)

        lender_kpis = None
        adjustments = {
            "yield_haircut": lender_yield_haircut,
            "ppa_haircut": lender_ppa_haircut,
            "capex_contingency": lender_capex_contingency,
            "opex_contingency": lender_opex_contingency,
        }
        if any(v != 0.0 for v in adjustments.values()):
            lc = run_lender_case(proj, adjustments)
            lender_kpis = lc["kpis"]

        cs = build_credit_summary(proj, base_kpis, lender_kpis)
    except Exception as exc:
        cs_error = _friendly_error(exc, "credit summary")

    project_record = _resolve_project_record(user, project)
    project_record, workspace_state, scenarios, history, exports, export_lineage, scenario_summary_cards = (
        _current_project_workspace(user, project_record)
    )
    return _render_scenario_workspace(
        request, user, project_record, workspace_state,
        scenarios, history, exports, export_lineage, scenario_summary_cards,
        credit_summary=cs,
        credit_summary_error=cs_error,
    )


# ── V4-5 — IC / Credit Memo Reporting Pack ────────────────────────────────

def _resolve_report_project(user, project: str, scenario_id: str = ""):
    """Resolve ProjectInputs for IC / credit reporting."""
    from app.services.sensitivity_service import _resolve_sensitivity_project as _rsp
    return _rsp(user, project, scenario_id)


def _run_base_result(proj):
    """Run the production financial authority for a ProjectInputs.

    PR-8 correction pass: this seam serves every reporting route
    (exec-summary, IC/credit packs, BESS dashboards, report export).
    Clean-ready projects execute the clean G2C authority exactly once
    (read-only legacy-shaped view); explicitly blocked projects execute the
    explicitly-classified legacy calibration waterfall. No route-dependent
    authority: SAME_PROJECT_SAME_SNAPSHOT_SAME_AUTHORITY.
    """
    from app.services.production_waterfall_seam import execute_production_waterfall

    execution = execute_production_waterfall(proj)
    return execution.result


@app.get("/scenarios/exec-summary")
async def scenario_exec_summary_endpoint(
    request: Request,
    project: str = "",
    scenario_id: str = "",
):
    """Generate printable executive summary from canonical engine.

    V4-5 Part A. Read-only; no persistence side effects.
    """
    from app.services.ic_report_service import build_exec_summary

    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    es = None
    es_error = None

    try:
        proj, scenario_name = _resolve_report_project(user, project, scenario_id)
        result = _run_base_result(proj)
        es = build_exec_summary(proj, result, scenario_name)
    except Exception as exc:
        es_error = _friendly_error(exc, "executive summary")

    project_record = _resolve_project_record(user, project)
    project_record, workspace_state, scenarios, history, exports, export_lineage, scenario_summary_cards = (
        _current_project_workspace(user, project_record)
    )
    return _render_scenario_workspace(
        request, user, project_record, workspace_state,
        scenarios, history, exports, export_lineage, scenario_summary_cards,
        exec_summary=es,
        exec_summary_error=es_error,
    )


@app.get("/scenarios/ic-pack")
async def scenario_ic_pack_endpoint(
    request: Request,
    project: str = "",
    scenario_id: str = "",
):
    """Generate Investment Committee Pack from canonical engine.

    V4-5 Part B. Read-only; no persistence side effects.
    """
    from app.services.ic_report_service import build_ic_pack
    from app.services.lender_case_service import build_covenant_periods

    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    ic = None
    ic_error = None

    try:
        proj, scenario_name = _resolve_report_project(user, project, scenario_id)
        result = _run_base_result(proj)
        covenant_periods = build_covenant_periods(result)
        ic = build_ic_pack(proj, result, scenario_name, covenant_periods=covenant_periods)
    except Exception as exc:
        ic_error = _friendly_error(exc, "IC pack")

    project_record = _resolve_project_record(user, project)
    project_record, workspace_state, scenarios, history, exports, export_lineage, scenario_summary_cards = (
        _current_project_workspace(user, project_record)
    )
    return _render_scenario_workspace(
        request, user, project_record, workspace_state,
        scenarios, history, exports, export_lineage, scenario_summary_cards,
        ic_pack=ic,
        ic_pack_error=ic_error,
    )


@app.get("/scenarios/credit-pack")
async def scenario_credit_pack_endpoint(
    request: Request,
    project: str = "",
    scenario_id: str = "",
):
    """Generate Credit Committee Pack from canonical engine.

    V4-5 Part C. Read-only; no persistence side effects.
    """
    from app.services.ic_report_service import build_credit_pack
    from app.services.lender_case_service import (
        build_covenant_periods,
        DSCR_EVENT_OF_DEFAULT, DSCR_LOCKUP, DSCR_DISTRIBUTION, DSCR_CASH_SWEEP,
    )

    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    cp = None
    cp_error = None
    thresholds = {
        "event_of_default": DSCR_EVENT_OF_DEFAULT,
        "lockup": DSCR_LOCKUP,
        "distribution": DSCR_DISTRIBUTION,
        "cash_sweep": DSCR_CASH_SWEEP,
    }

    try:
        proj, scenario_name = _resolve_report_project(user, project, scenario_id)
        result = _run_base_result(proj)
        cov_periods = build_covenant_periods(result)
        cp = build_credit_pack(
            proj, result, scenario_name,
            covenant_periods=cov_periods,
            covenant_thresholds=thresholds,
        )
    except Exception as exc:
        cp_error = _friendly_error(exc, "credit pack")

    project_record = _resolve_project_record(user, project)
    project_record, workspace_state, scenarios, history, exports, export_lineage, scenario_summary_cards = (
        _current_project_workspace(user, project_record)
    )
    return _render_scenario_workspace(
        request, user, project_record, workspace_state,
        scenarios, history, exports, export_lineage, scenario_summary_cards,
        credit_pack=cp,
        credit_pack_error=cp_error,
        covenant_thresholds=thresholds,
    )


@app.get("/scenarios/bess-revenue")
async def scenario_bess_revenue_endpoint(
    request: Request,
    project: str = "",
    scenario_id: str = "",
):
    """V4-7 Part C: BESS Revenue Breakdown panel."""
    from app.services.bess_service import build_bess_revenue_breakdown

    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    br = None
    br_error = None
    try:
        proj, _scenario_name = _resolve_report_project(user, project, scenario_id)
        result = _run_base_result(proj)
        br = build_bess_revenue_breakdown(proj, result)
        if br is None:
            br_error = "Project does not have BESS enabled or BessParams not configured."
    except Exception as exc:
        br_error = _friendly_error(exc, "BESS revenue breakdown")

    project_record = _resolve_project_record(user, project)
    project_record, workspace_state, scenarios, history, exports, export_lineage, scenario_summary_cards = (
        _current_project_workspace(user, project_record)
    )
    return _render_scenario_workspace(
        request, user, project_record, workspace_state,
        scenarios, history, exports, export_lineage, scenario_summary_cards,
        bess_revenue=br,
        bess_revenue_error=br_error,
    )


@app.get("/scenarios/bess-asset")
async def scenario_bess_asset_endpoint(
    request: Request,
    project: str = "",
    scenario_id: str = "",
):
    """V4-7 Part D: Battery Asset Dashboard panel."""
    from app.services.bess_service import build_bess_asset_dashboard

    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    ba = None
    ba_error = None
    try:
        proj, _scenario_name = _resolve_report_project(user, project, scenario_id)
        result = _run_base_result(proj)
        ba = build_bess_asset_dashboard(proj, result)
        if ba is None:
            ba_error = "Project does not have BESS enabled or BessParams not configured."
    except Exception as exc:
        ba_error = _friendly_error(exc, "BESS asset dashboard")

    project_record = _resolve_project_record(user, project)
    project_record, workspace_state, scenarios, history, exports, export_lineage, scenario_summary_cards = (
        _current_project_workspace(user, project_record)
    )
    return _render_scenario_workspace(
        request, user, project_record, workspace_state,
        scenarios, history, exports, export_lineage, scenario_summary_cards,
        bess_asset=ba,
        bess_asset_error=ba_error,
    )


@app.get("/scenarios/report/export")
async def scenario_report_export_endpoint(
    request: Request,
    project: str = "",
    scenario_id: str = "",
    fmt: str = "xlsx",
):
    """Export IC/credit reporting pack.

    V4-5 Part D. Formats: xlsx, docx.
    Read-only; no persistence side effects.
    """
    from app.services.ic_report_service import export_report_xlsx, export_report_docx
    from app.services.lender_case_service import build_covenant_periods
    from fastapi.responses import Response

    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    try:
        proj, scenario_name = _resolve_report_project(user, project, scenario_id)
        result = _run_base_result(proj)
        cov_periods = build_covenant_periods(result)
    except Exception as exc:
        _logger.exception("Report export failed: %s", exc)
        return Response(content="Export failed — please check your inputs.", status_code=500, media_type="text/plain")

    slug = (getattr(proj.info, "name", project) or project).replace(" ", "_")[:24]

    if fmt == "docx":
        content = export_report_docx(proj, result, scenario_name, report_type="ic",
                                     covenant_periods=cov_periods)
        return Response(
            content=content,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers={"Content-Disposition": f"attachment; filename={slug}_IC_Pack.docx"},
        )

    if fmt == "docx_credit":
        content = export_report_docx(proj, result, scenario_name, report_type="credit",
                                     covenant_periods=cov_periods)
        return Response(
            content=content,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers={"Content-Disposition": f"attachment; filename={slug}_Credit_Pack.docx"},
        )

    # Default: xlsx
    content = export_report_xlsx(proj, result, scenario_name, covenant_periods=cov_periods)
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={slug}_Report_Pack.xlsx"},
    )


@app.post("/scenarios/save")
async def save_scenario_endpoint(request: Request):
    """Persist the current form snapshot as a saved scenario.

    Thin orchestration wrapper (Phase 51J-2). The route is responsible
    for auth, form parsing, deps bundle construction, and final
    response rendering. The full /scenarios/save orchestration body
    (project/workspace resolution, soft-block handling, scenario_name
    construction, last_run_summary conditional, save_scenario kwargs
    assembly and call, bind_workspace_to_scenario kwargs assembly
    and call, read-only list_scenarios/get_scenario_history/
    list_exports/build_export_lineage calls, scenario_summary_cards
    assembly with export_count, replay_metadata/governance metadata
    assembly, workspace render context assembly) lives in
    ``app.services.scenarios_save_service.execute_scenarios_save_route``.
    """
    from app.services.scenarios_save_service import (
        ScenariosSaveRouteDeps,
        execute_scenarios_save_route,
    )

    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    form = await request.form()
    deps = ScenariosSaveRouteDeps(
        collect_form_snapshot=_collect_form_snapshot,
        project_workspace_from_snapshot=_project_workspace_from_snapshot,
        save_scenario=save_scenario,
        bind_workspace_to_scenario=bind_workspace_to_scenario,
        list_scenarios=list_scenarios,
        get_scenario_history=get_scenario_history,
        list_exports=list_exports,
        build_export_lineage=build_export_lineage,
        governance_snapshot=_governance_snapshot,
        replay_metadata_for_project=_replay_metadata_for_project,
        snapshots_equal=snapshots_equal,
        render_scenario_workspace=_render_scenario_workspace,
        utc_now=None,
    )
    # The service owns the render call (returns the rendered
    # response directly via _render_scenario_workspace).
    return await execute_scenarios_save_route(
        request=request, form=form, user=user, deps=deps,
    )


@app.get("/scenarios/{scenario_id}/load")
async def load_scenario_endpoint(request: Request, scenario_id: str):
    """Load a saved scenario snapshot back into the form."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    record = get_scenario(scenario_id, user.user_id)
    if record is None:
        return JSONResponse({"error": "Scenario not found"}, status_code=404)
    bind_workspace_to_scenario(
        user.user_id,
        record.project_id,
        record.project_code,
        record,
        governance_state=record.governance_state,
        replay_metadata=_replay_metadata_for_project(
            record.project_code,
            project_id=record.project_id,
            scenario_id=record.scenario_id,
            export_type="workspace_loaded_scenario",
        ),
    )

    return templates.TemplateResponse(
        request=request,
        name="partials/scenario_load_result.html",
        context={
            "record": record,
            "message": f"Loaded {record.scenario_name}. The form has been refreshed with the saved snapshot.",
            "project_code": record.project_code,
            "workspace_state_meta": _workspace_state_meta(get_workspace_state(user.user_id, record.project_id)),
        },
        headers={"HX-Trigger": "scenarioLoaded"},
    )


@app.post("/scenarios/{scenario_id}/duplicate")
async def duplicate_scenario_endpoint(request: Request, scenario_id: str):
    """Duplicate a saved scenario snapshot.

    Thin orchestration wrapper (Phase 51K-2). The route is responsible
    for auth, path-parameter parsing, deps bundle construction, and
    final response rendering. The full /scenarios/{scenario_id}/
    duplicate orchestration body (original scenario lookup, 404
    early return, duplicate_scenario call, project_record resolution,
    read-only list_scenarios/get_scenario_history/list_exports/
    build_export_lineage calls, scenario_summary_cards assembly with
    export_count, workspace_state resolution, success render context
    assembly) lives in
    ``app.services.scenario_duplicate_service.execute_scenario_duplicate_route``.
    """
    from app.services.scenario_duplicate_service import (
        ScenarioDuplicateRouteDeps,
        execute_scenario_duplicate_route,
    )

    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    deps = ScenarioDuplicateRouteDeps(
        get_scenario=get_scenario,
        duplicate_scenario=duplicate_scenario,
        get_project_by_code=get_project_by_code,
        list_scenarios=list_scenarios,
        get_scenario_history=get_scenario_history,
        list_exports=list_exports,
        build_export_lineage=build_export_lineage,
        get_workspace_state=get_workspace_state,
        render_scenario_workspace=_render_scenario_workspace,
    )
    # The service returns either the rendered workspace
    # response (success) or a ScenarioDuplicateRouteOutcome
    # (404 not found, with status_code + payload). The route
    # translates the outcome to a JSONResponse.
    result = await execute_scenario_duplicate_route(
        request=request, scenario_id=scenario_id, user=user, deps=deps,
    )
    # If the service returned a FastAPI response (TemplateResponse
    # from deps.render_scenario_workspace), pass it through.
    if hasattr(result, "status_code") and hasattr(result, "body"):
        return result
    # Otherwise it's a ScenarioDuplicateRouteOutcome for the
    # 404 not-found path.
    return JSONResponse(
        content=result.payload,
        status_code=result.status_code,
        headers=result.headers or None,
    )


def _build_scenario_tab_context(user, project_record, scenarios, workspace_state):
    """Build context dict for scenario_tab.html.

    Splits scenario_records into base_case_record and non_base_scenarios.
    """
    base_case_record = None
    non_base_scenarios = []
    for s in scenarios:
        if s.is_base_case:
            base_case_record = s
        else:
            non_base_scenarios.append(s)
    return {
        "user": user,
        "project_record": project_record,
        "workspace_state": workspace_state,
        "scenario_records": scenarios,
        "base_case_record": base_case_record,
        "non_base_scenarios": non_base_scenarios,
        "is_user_project": project_record.project_origin == "user_created",
        # Phase 24-H: exploratory warning flag (user_created + generic)
        "is_exploratory_project": (
            project_record.project_origin == "user_created"
            and (project_record.template_source or "").strip().lower()
            in {"generic_solar", "generic_wind"}
        ),
        # SCENARIO-2 fix: HTMX partial must include editable fields so the
        # scenario matrix tbody renders immediately after Add Scenario.
        "scenario_editable_fields": SCENARIO_EDITABLE_FIELDS,
    }


@app.post("/scenarios/add")
async def add_scenario_endpoint(request: Request):
    """Add a new non-base scenario inheriting from the project's Base Case.

    Only available for user_created projects.

    Thin orchestration wrapper (Phase 51L-2). The route is responsible
    for auth, form parsing, deps bundle construction, and final
    response rendering. The full /scenarios/add orchestration body
    (form input read, validation, project lookup, user_created gate,
    base case lookup, oldest-scenario promotion fallback,
    base_input_set fallback chain, add_scenario call assembly, post-add
    scenario list reload, workspace_state lookup, response context
    assembly with HX-Trigger header, 5 explicit error paths) lives
    in
    ``app.services.scenarios_add_service.execute_scenarios_add_route``.
    """
    from app.services.scenarios_add_service import (
        ScenariosAddRouteDeps,
        execute_scenarios_add_route,
    )

    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    # P6.7 — demo rate limiting for scenario creation
    if user.is_demo:
        allowed, retry_after = check_demo_rate_limit(user.user_id, "scenario_add")
        if not allowed:
            return JSONResponse(
                {
                    "error": (
                        f"Demo sessions are limited to 15 new scenarios per hour. "
                        f"Try again in {retry_after}s."
                    )
                },
                status_code=429,
            )

    form = await request.form()
    deps = ScenariosAddRouteDeps(
        get_project_record=get_project_record,
        list_scenarios=list_scenarios,
        get_least_created_scenario_for_project=_get_least_created_scenario_for_project,
        promote_scenario_to_base_case=promote_scenario_to_base_case,
        add_scenario=add_scenario,
        get_workspace_state=get_workspace_state,
        build_scenario_tab_context=_build_scenario_tab_context,
        get_or_create_base_case_scenario=get_or_create_base_case_scenario,
    )
    result = await execute_scenarios_add_route(
        request=request, form=form, user=user, deps=deps,
    )
    # If the result is a JSON error path (4xx/5xx), translate to JSONResponse.
    if result.payload:
        return JSONResponse(
            content=result.payload,
            status_code=result.status_code,
            headers=result.headers or None,
        )
    # Success: translate to TemplateResponse.
    return templates.TemplateResponse(
        request=request,
        name=result.template_name,
        context=result.context,
        headers=result.headers or None,
    )


@app.post("/scenarios/{scenario_id}/select")
async def select_scenario_endpoint(request: Request, scenario_id: str):
    """Set the active scenario for the current workspace.

    Thin orchestration wrapper (Phase 51S-2). The route is
    responsible for auth, path param, deps bundle construction,
    and final response rendering. The full
    /scenarios/{scenario_id}/select orchestration body (scenario
    lookup, gate, select_scenario write, partial template
    re-render with HX-Trigger JSON payload) lives in
    ``app.services.scenario_select_service.execute_scenario_select_route``.
    """
    from app.services.scenario_select_service import (
        ScenarioSelectRouteDeps,
        execute_scenario_select_route,
    )

    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    deps = ScenarioSelectRouteDeps(
        get_scenario=get_scenario,
        select_scenario=select_scenario,
        get_workspace_state=get_workspace_state,
        get_project_record=get_project_record,
        list_scenarios=list_scenarios,
        build_scenario_tab_context=_build_scenario_tab_context,
    )
    outcome = await execute_scenario_select_route(
        request=request, scenario_id=scenario_id, user=user, deps=deps,
    )
    if outcome.status_code >= 400:
        return JSONResponse(outcome.payload, status_code=outcome.status_code)
    return templates.TemplateResponse(
        request=request,
        name=outcome.template_name,
        context=outcome.context,
        headers=outcome.headers or None,
    )


@app.post("/scenarios/{scenario_id}/update-overrides")
async def update_overrides_endpoint(request: Request, scenario_id: str):
    """Patch overrides for a non-base scenario. Accepts JSON body or form-data.

    P1-CLEANUP-SPRINT-2: Accepts both ``application/json`` and
    ``application/x-www-form-urlencoded`` (or ``multipart/form-data``).
    JSON behaviour is unchanged. Form-data fallback parses submitted
    fields into an overrides dict. Invalid payloads return a friendly
    HTTP 400 instead of a 500.

    Thin orchestration wrapper (Phase 51R-2). The route is
    responsible for auth, body parsing, deps bundle construction,
    and final response rendering. The full
    /scenarios/{scenario_id}/update-overrides orchestration body
    (scenario lookup, is_base_case gate, update_scenario_overrides,
    500 failure path, partial template re-render) lives in
    ``app.services.scenario_update_overrides_service.execute_scenario_update_overrides_route``.
    """
    from app.services.scenario_update_overrides_service import (
        ScenarioUpdateOverridesRouteDeps,
        execute_scenario_update_overrides_route,
    )

    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    # P1-CLEANUP-SPRINT-2: dual body parsing (JSON or form-data).
    # Detection: content-type header. Fallback order is
    # "if JSON works, use JSON; else try form-data; else 400".
    overrides: dict = {}
    content_type = (request.headers.get("content-type") or "").lower()
    if "application/json" in content_type:
        try:
            body = await request.json()
        except Exception:
            body = None
        if isinstance(body, dict):
            overrides = body
        elif body is None:
            return JSONResponse(
                content={"error": "Invalid JSON body. Expected JSON object."},
                status_code=400,
            )
        else:
            return JSONResponse(
                content={"error": "Invalid JSON body. Expected a JSON object."},
                status_code=400,
            )
    else:
        try:
            form = await request.form()
        except Exception:
            return JSONResponse(
                content={"error": "Invalid form-data body."},
                status_code=400,
            )
        # Form-data: parse all submitted fields into overrides dict.
        # Skip known framework fields (project_code, scenario_id, csrf, _)
        # so the dict represents only user override values.
        _SKIP_KEYS = {"project_code", "scenario_id", "csrf_token", "csrf"}
        for key, val in form.multi_items() if hasattr(form, "multi_items") else form.items():
            if key in _SKIP_KEYS or key.startswith("_"):
                continue
            overrides[key] = val

    deps = ScenarioUpdateOverridesRouteDeps(
        get_scenario=get_scenario,
        update_scenario_overrides=update_scenario_overrides,
        get_project_record=get_project_record,
        get_workspace_state=get_workspace_state,
        list_scenarios=list_scenarios,
        build_scenario_tab_context=_build_scenario_tab_context,
    )
    outcome = await execute_scenario_update_overrides_route(
        request=request, scenario_id=scenario_id, overrides=overrides,
        user=user, deps=deps,
    )
    if outcome.status_code >= 400:
        return JSONResponse(outcome.payload, status_code=outcome.status_code)
    return templates.TemplateResponse(
        request=request,
        name=outcome.template_name,
        context=outcome.context,
        headers=outcome.headers or None,
    )


@app.post("/projects/{project_code}/confirm-first-edit-copy")
async def confirm_first_edit_copy_endpoint(
    request: Request, project_code: str,
):
    """Phase P2-FIX-3 (C2 first-edit trigger):

    The user is opening a protected reference project (Generic Wind Reference Wind
    or Generic Solar Reference Solar PV) and has confirmed the prompt:

        "This is a protected reference project. Create an editable
        copy?"

    This route creates a user-owned working copy from the
    protected reference and redirects the user to the new copy.
    The original reference fixture is NOT mutated.

    The new project gets a new project_code like ``generic_wind_reference_your_copy``
    (via the existing save-as name-generation logic), the
    project_origin is set to ``user_created``, and the
    replay_metadata records the source.

    If the source is NOT a protected reference (i.e. someone hit
    this URL on a generic / user-created project), the route
    returns 400 — this URL is reserved for the C2 transition.
    """
    from app.ui.protected_reference_service import (
        is_protected_reference,
    )
    from app.persistence.repository import get_project_record as gpr

    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    source = gpr(user_id=user.user_id, project_code=project_code)
    if source is None:
        return JSONResponse(
            {"error": "project_not_found", "project_code": project_code},
            status_code=404,
        )
    if not is_protected_reference(source):
        return JSONResponse(
            {
                "error": "not_a_protected_reference",
                "message": (
                    "This endpoint is only valid for protected "
                    "reference projects (Generic Wind Reference / Generic Solar Reference)."
                ),
                "project_code": project_code,
            },
            status_code=400,
        )

    # P2-FIX-8 PR3: Dedup — if user already has a working copy of
    # this source, redirect to it instead of creating another.
    existing = _find_existing_working_copy(user.user_id, project_code)
    if existing:
        from app.utils.workbook_flag import project_workbook_url as _pwurl
        return RedirectResponse(
            url=_pwurl(existing.project_code), status_code=302
        )

    # Reuse the existing /save-as machinery. The deps below are
    # the same as /save-as (Phase 51O-2) with two modifications:
    # - replay_metadata tags the transition as
    #   "working_copy_from_protected_reference" (audit / reviewer
    #   can trace the lineage).
    # - the resulting project_origin is "user_created" (via
    #   execute_project_save_as_route default for non-user
    #   source).
    from app.services.project_save_as_service import (
        ProjectSaveAsRouteDeps,
        execute_project_save_as_route,
    )

    def _project_record_creation_governance_state():
        return {
            "g20": "BLOCKED",
            "r99_r102": "NOT_APPROVED",
            "lender_ready": False,
        }

    def _workspace_state_initialization_governance_state():
        return {
            "g20": "BLOCKED",
            "r99_r102": "NOT_APPROVED",
            "lender_ready": False,
        }

    def _build_project_replay_metadata(source, project_code):
        return {
            "export_type": "working_copy_from_protected_reference",
            "source_project_code": project_code,
            "source_project_origin": source.project_origin,
            "created_via": "p2fix3_first_edit_confirmation",
            "baseline_source": False,
        }

    def _build_workspace_replay_metadata(source, project_code):
        return {
            "export_type": "working_copy_workspace_initialized",
            "source_project_code": project_code,
            "baseline_source": False,
        }

    def _is_already_user_project(source):
        # is_already_user_project is a defensive gate in
        # execute_project_save_as_route. For the C2 first-edit
        # trigger, we ALWAYS want a new copy, so we return False
        # unconditionally. (The service treats this as a hint
        # only; the main work is the save_project call.)
        return False

    deps = ProjectSaveAsRouteDeps(
        get_project_record=gpr,
        save_project=save_project,
        save_workspace_state=save_workspace_state,
        now_utc=_now_utc,
        project_record_creation_governance_state=_project_record_creation_governance_state,
        workspace_state_initialization_governance_state=_workspace_state_initialization_governance_state,
        build_project_replay_metadata=_build_project_replay_metadata,
        build_workspace_replay_metadata=_build_workspace_replay_metadata,
        is_already_user_project=_is_already_user_project,
        get_or_create_base_case_scenario=get_or_create_base_case_scenario,
    )
    outcome = await execute_project_save_as_route(
        request=request, project_code=project_code, user=user, deps=deps,
    )
    if outcome.is_redirect:
        return RedirectResponse(
            url=outcome.redirect_url, status_code=outcome.status_code
        )
    # If the save-as service returned a JSON outcome (e.g. 200
    # with the new project_code), forward it. The frontend can
    # then navigate to the new project_code.
    return JSONResponse(
        outcome.payload, status_code=outcome.status_code
    )


@app.post("/projects/{project_code}/save-as")
async def save_project_as_endpoint(request: Request, project_code: str):
    """Duplicate a factory template or saved baseline into a
    user-editable project.

    Thin orchestration wrapper (Phase 51O-2). The route is
    responsible for auth, the path parameter, deps bundle
    construction, and final response rendering. The full
    /projects/{project_code}/save-as orchestration body (source
    project lookup, gate on user_created, new_code/new_name
    generation, save_project with governance_state + replay_metadata,
    save_workspace_state with governance_state + replay_metadata)
    lives in
    ``app.services.project_save_as_service.execute_project_save_as_route``.
    """
    from app.services.project_save_as_service import (
        ProjectSaveAsRouteDeps,
        execute_project_save_as_route,
    )
    from app.persistence.repository import get_project_record as gpr

    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    def _project_record_creation_governance_state():
        return {"g20": "BLOCKED", "r99_r102": "NOT_APPROVED", "lender_ready": False}

    def _workspace_state_initialization_governance_state():
        return {"g20": "BLOCKED", "r99_r102": "NOT_APPROVED", "lender_ready": False}

    def _build_project_replay_metadata(source, project_code):
        return {
            "export_type": "project_duplicated",
            "source_project_code": project_code,
            "source_project_origin": source.project_origin,
            "baseline_source": source.project_origin == "saved_baseline",
        }

    def _build_workspace_replay_metadata(source, project_code):
        return {
            "export_type": "workspace_duplicated",
            "source_project_code": project_code,
            "baseline_source": source.project_origin == "saved_baseline",
        }

    def _is_already_user_project(source):
        return source.project_origin == "user_created"

    deps = ProjectSaveAsRouteDeps(
        get_project_record=gpr,
        save_project=save_project,
        save_workspace_state=save_workspace_state,
        now_utc=_now_utc,
        project_record_creation_governance_state=_project_record_creation_governance_state,
        workspace_state_initialization_governance_state=_workspace_state_initialization_governance_state,
        build_project_replay_metadata=_build_project_replay_metadata,
        build_workspace_replay_metadata=_build_workspace_replay_metadata,
        is_already_user_project=_is_already_user_project,
        get_or_create_base_case_scenario=get_or_create_base_case_scenario,
    )
    outcome = await execute_project_save_as_route(
        request=request, project_code=project_code, user=user, deps=deps,
    )
    if outcome.is_redirect:
        return RedirectResponse(url=outcome.redirect_url, status_code=outcome.status_code)
    return JSONResponse(outcome.payload, status_code=outcome.status_code)


@app.post("/scenarios/{scenario_id}/rename")
async def rename_scenario_endpoint(request: Request, scenario_id: str):
    """Rename a saved scenario.

    Thin orchestration wrapper (Phase 51P-2). The route is
    responsible for auth, form read, path param, deps bundle
    construction, and final response rendering. The full
    /scenarios/{scenario_id}/rename orchestration body (scenario
    lookup, gate, rename, workspace re-render with summary cards)
    lives in
    ``app.services.scenario_rename_service.execute_scenario_rename_route``.
    """
    from app.services.scenario_rename_service import (
        ScenarioRenameRouteDeps,
        execute_scenario_rename_route,
    )

    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    form = await request.form()
    new_name = (form.get("scenario_name", "") or "").strip()

    def _render_with_summary_cards(
        request, user, project_record, workspace_state, scenarios, history,
        exports, export_lineage, message
    ):
        # Build scenario_summary_cards inline (Quirks 3/4)
        export_counts = {}
        for entry in export_lineage:
            export_counts[entry["scenario_name"]] = (
                export_counts.get(entry["scenario_name"], 0) + 1
            )
        scenario_summary_cards = []
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
        return _render_scenario_workspace(
            request, user, project_record, workspace_state, scenarios, history,
            exports, export_lineage, scenario_summary_cards, message
        )

    deps = ScenarioRenameRouteDeps(
        get_scenario=get_scenario,
        rename_scenario=rename_scenario,
        get_project_by_code=get_project_by_code,
        list_scenarios=list_scenarios,
        get_scenario_history=get_scenario_history,
        list_exports=list_exports,
        build_export_lineage=build_export_lineage,
        get_workspace_state=get_workspace_state,
        render_scenario_workspace=_render_with_summary_cards,
    )
    outcome = await execute_scenario_rename_route(
        request=request, scenario_id=scenario_id, new_name=new_name,
        user=user, deps=deps,
    )
    if outcome.status_code >= 400:
        return JSONResponse(outcome.payload, status_code=outcome.status_code)
    return outcome.rendered_response


@app.post("/scenarios/{scenario_id}/archive")
async def archive_scenario_endpoint(request: Request, scenario_id: str):
    """Soft-archive a saved scenario.

    Thin orchestration wrapper (Phase 51Q-2). The route is
    responsible for auth, path param, deps bundle construction,
    and final response rendering. The full
    /scenarios/{scenario_id}/archive orchestration body (scenario
    lookup, soft-archive, workspace re-render) lives in
    ``app.services.scenario_archive_service.execute_scenario_archive_route``.
    """
    from app.services.scenario_archive_service import (
        ScenarioArchiveRouteDeps,
        execute_scenario_archive_route,
    )

    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    def _render_with_summary_cards(
        request, user, project_record, workspace_state, scenarios, history,
        exports, export_lineage, message
    ):
        export_counts = {}
        for entry in export_lineage:
            export_counts[entry["scenario_name"]] = (
                export_counts.get(entry["scenario_name"], 0) + 1
            )
        scenario_summary_cards = []
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
        return _render_scenario_workspace(
            request, user, project_record, workspace_state, scenarios, history,
            exports, export_lineage, scenario_summary_cards, message
        )

    deps = ScenarioArchiveRouteDeps(
        get_scenario=get_scenario,
        archive_scenario=archive_scenario,
        get_project_by_code=get_project_by_code,
        list_scenarios=list_scenarios,
        get_scenario_history=get_scenario_history,
        list_exports=list_exports,
        build_export_lineage=build_export_lineage,
        get_workspace_state=get_workspace_state,
        render_scenario_workspace=_render_with_summary_cards,
    )
    outcome = await execute_scenario_archive_route(
        request=request, scenario_id=scenario_id, user=user, deps=deps,
    )
    if outcome.status_code >= 400:
        return JSONResponse(outcome.payload, status_code=outcome.status_code)
    return outcome.rendered_response


@app.get("/runs")
async def list_runs_endpoint(request: Request):
    """List recent runs for the authenticated user."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    runs = list_runs(user.user_id, limit=20)
    data = [{
        "run_id": r.run_id,
        "project_type": r.project_type,
        "scenario": r.scenario,
        "created_at": r.created_at.isoformat() if hasattr(r.created_at, 'isoformat') else r.created_at,
        "inputs": r.inputs,
        "kpis": r.kpis,
    } for r in runs]
    return templates.TemplateResponse(
        request=request,
        name="partials/run_history.html",
        context={"runs": data, "user": user},
    )


@app.post("/save-run")
async def save_run_endpoint(request: Request):
    """Save current model run to persistence.

    Thin orchestration wrapper (Phase 51G-2). The route is responsible
    for auth, form parsing, snapshot collection, deps bundle construction,
    and final template rendering. The full /save-run orchestration body
    (project/workspace resolution, runtime guard, two execution paths,
    intended runtime persistence writes, save_result-ok / save_result-err
    context assembly) lives in
    ``app.services.save_run_service.execute_save_run_route``.

    Phase 51G-3: the pre-existing latent bug
    ``_clean_user_project_runtime_snapshot`` is now fixed. The
    helper is defined in main_web (delegates to
    ``_resolve_runtime_snapshot_source``) and injected as
    ``deps.clean_user_project_runtime_snapshot``. The user_created
    branch of the service now reaches run_project + save_run +
    save_project on the success path.
    """
    from app.services.save_run_service import (
        SaveRunRouteDeps,
        execute_save_run_route,
    )

    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    form = await request.form()
    snapshot = _collect_form_snapshot(form)

    # HOTFIX-PILOT-BLOCKER-1 (F4): Defense in depth for /run
    # routing. The hidden form's active_project may carry a stale
    # value (the source reference's identity, copied via the
    # draft_snapshot chain). The URL ?project= param is the
    # authoritative source for which workspace the user is
    # actually viewing. If URL and form disagree, prefer URL.
    # This prevents record_workspace_runtime from updating the
    # wrong workspace.
    _url_project = request.query_params.get("project", "").strip().lower()
    _form_active = (snapshot.get("active_project", "") or "").strip().lower()
    if _url_project and _form_active and _url_project != _form_active:
        # Verify URL project is a real user-owned project for this
        # user. If so, override the snapshot's active_project.
        _url_rec = get_project_record(
            user_id=user.user_id, project_code=_url_project
        )
        if _url_rec is not None:
            snapshot["active_project"] = _url_rec.project_code
            # Also fix project_origin if URL rec is user_created
            # (working copy / new project) but form has factory_template.
            if _url_rec.project_origin == "user_created":
                snapshot["project_origin"] = "user_created"

    deps = SaveRunRouteDeps(
        project_workspace_from_snapshot=_project_workspace_from_snapshot,
        check_runtime_allowed=check_runtime_allowed,
        validate_form=_validate_form,
        project_types=PROJECT_TYPES,
        scenarios=SCENARIOS,
        clean_user_project_runtime_snapshot=_clean_user_project_runtime_snapshot,
        canonical_project_type=_canonical_project_type,
        build_projectinputs_from_snapshot=build_projectinputs_from_snapshot,
        build_schema_from_form=_build_schema_from_form_with_timing(form),
        build_projectinputs=build_projectinputs,
        normalize_template_source=_normalize_template_source,
        run_project=run_project,
        save_run=save_run,
        save_project=save_project,
        replay_metadata_for_project=_replay_metadata_for_project,
        governance_snapshot=_governance_snapshot,
        utc_now_iso=utc_now_iso,
    )

    outcome = await execute_save_run_route(
        request=request, form=form, user=user, snapshot=snapshot, deps=deps,
    )

    if outcome.is_redirect:
        return RedirectResponse(
            url=outcome.redirect_url or "/login",
            status_code=outcome.status_code,
        )

    return templates.TemplateResponse(
        request=request,
        name=outcome.template_name,
        context=outcome.context,
        status_code=outcome.status_code,
        headers=outcome.headers,
    )


@app.get("/run/{run_id}")
async def get_run_endpoint(request: Request, run_id: str):
    """Load a saved run by ID."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    record = get_run(run_id, user.user_id)
    if record is None:
        from fastapi.responses import JSONResponse
        return JSONResponse({"error": "Run not found"}, status_code=404)

    return templates.TemplateResponse(
        request=request,
        name="partials/kpis.html",
        context={
            "kpis": _format_kpis(record.kpis),
            "run_data": {
                "project_type": record.project_type,
                "scenario": record.scenario,
                "capacity_mw": record.inputs.get("capacity_mw", ""),
                "tariff_eur_mwh": record.inputs.get("tariff_eur_mwh", ""),
                "total_capex_keur": record.inputs.get("total_capex_keur", ""),
                "gearing_pct": record.inputs.get("gearing_pct", ""),
            },
            "messages": [f"Loaded run {run_id} from {record.created_at.strftime('%Y-%m-%d %H:%M')}"] ,
            "integration_status": "full",
        },
    )


# ── Phase M3 — Inline Matrix Override Editing ────────────────────────────────

def _m3_get_scenario_or_422(scenario_id: str, user):
    """Lookup scenario; return (scenario, err_response) where err_response is
    non-None when the lookup fails or the scenario is the base case."""
    from app.ui.scenario_matrix import ALL_ROWS
    scenario = get_scenario(scenario_id, user.user_id)
    if scenario is None:
        return None, JSONResponse({"error": "Scenario not found"}, status_code=422)
    if getattr(scenario, "is_base_case", False):
        return None, JSONResponse({"error": "Base case is read-only"}, status_code=422)
    return scenario, None


def _m3_col_key_for_scenario(scenario_id: str, col_downside, col_upside, col_custom) -> str:
    """Return the column key string for a scenario record."""
    if col_downside and getattr(col_downside, "scenario_id", None) == scenario_id:
        return "downside"
    if col_upside and getattr(col_upside, "scenario_id", None) == scenario_id:
        return "upside"
    if col_custom and getattr(col_custom, "scenario_id", None) == scenario_id:
        return "custom"
    return "downside"  # fallback


def _m3_cell_class(col_key: str) -> str:
    return "matrix-cell-scenario"


@app.post("/matrix/scenario/{scenario_id}/set-field")
async def m3_set_field(
    request: Request,
    scenario_id: str,
    field: str = Form(...),
    value: str = Form(...),
):
    """M3: Save a single field override for a non-base scenario cell."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    from app.ui.scenario_matrix import ALL_ROWS, INPUT_ROWS, _get_scenario_input_value

    # Validate field
    valid_attrs = {r.attr for r in ALL_ROWS}
    if field not in valid_attrs:
        return JSONResponse({"error": f"Unknown field: {field}"}, status_code=422)

    # Find the row
    row = next((r for r in ALL_ROWS if r.attr == field), None)

    # Parse numeric value
    try:
        numeric_value = float(value)
    except (TypeError, ValueError):
        return JSONResponse({"error": f"Non-numeric value for field {field}"}, status_code=422)

    scenario, err = _m3_get_scenario_or_422(scenario_id, user)
    if err is not None:
        return err

    # Save override
    update_scenario_overrides(
        user_id=user.user_id,
        scenario_id=scenario_id,
        overrides={field: numeric_value},
    )

    # Re-read updated scenario
    updated_scenario = get_scenario(scenario_id, user.user_id)

    # Get display value
    display_value = _get_scenario_input_value(updated_scenario, row)

    # Determine col_key from query param or default
    col_key = request.query_params.get("col", "downside")

    cell_class = _m3_cell_class(col_key)

    response = templates.TemplateResponse(
        request=request,
        name="partials/_matrix_cell_updated.html",
        context={
            "scenario_id": scenario_id,
            "field": field,
            "col_key": col_key,
            "cell_class": cell_class,
            "display_value": display_value,
        },
    )
    response.headers["HX-Trigger"] = "matrixCellSaved"
    return response


@app.get("/matrix/scenario/{scenario_id}/cell-edit")
async def m3_cell_edit(
    request: Request,
    scenario_id: str,
    field: str,
    col: str = "downside",
):
    """M3: Return the inline edit form for a matrix cell."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    from app.ui.scenario_matrix import ALL_ROWS, _get_scenario_input_value

    scenario, err = _m3_get_scenario_or_422(scenario_id, user)
    if err is not None:
        return err

    valid_attrs = {r.attr for r in ALL_ROWS}
    if field not in valid_attrs:
        return JSONResponse({"error": f"Unknown field: {field}"}, status_code=422)

    row = next((r for r in ALL_ROWS if r.attr == field), None)

    # Get raw value from overrides/snapshot/base_input_set
    raw_val = None
    for src in (
        getattr(scenario, "overrides", None) or {},
        getattr(scenario, "snapshot", None) or {},
        getattr(scenario, "base_input_set", None) or {},
    ):
        v = src.get(field)
        if v is not None:
            raw_val = v
            break

    raw_value = str(raw_val) if raw_val is not None else ""
    cell_class = _m3_cell_class(col)

    return templates.TemplateResponse(
        request=request,
        name="partials/_matrix_cell_edit.html",
        context={
            "scenario_id": scenario_id,
            "field": field,
            "col_key": col,
            "cell_class": cell_class,
            "raw_value": raw_value,
        },
    )


@app.get("/matrix/scenario/{scenario_id}/cell-view")
async def m3_cell_view(
    request: Request,
    scenario_id: str,
    field: str,
    col: str = "downside",
):
    """M3: Return the cell view (cancel/reset to current value)."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    from app.ui.scenario_matrix import ALL_ROWS, _get_scenario_input_value

    scenario, err = _m3_get_scenario_or_422(scenario_id, user)
    if err is not None:
        return err

    valid_attrs = {r.attr for r in ALL_ROWS}
    if field not in valid_attrs:
        return JSONResponse({"error": f"Unknown field: {field}"}, status_code=422)

    row = next((r for r in ALL_ROWS if r.attr == field), None)
    display_value = _get_scenario_input_value(scenario, row)
    cell_class = _m3_cell_class(col)

    return templates.TemplateResponse(
        request=request,
        name="partials/_matrix_cell_updated.html",
        context={
            "scenario_id": scenario_id,
            "field": field,
            "col_key": col,
            "cell_class": cell_class,
            "display_value": display_value,
        },
    )

def _m4_template_to_project_type(source_project_template: str) -> str:
    """Map source_project_template to project_type string for run_project."""
    source = (source_project_template or "").strip().lower()
    if source in ("generic_solar_reference", "generic_solar"):
        return "Solar"
    if source in ("generic_data_center_reference", "generic_data_center"):
        return "Generic Data Center Reference"
    return "Wind"


@app.post("/matrix/scenario/{scenario_id}/run")
async def m4_run_scenario(request: Request, scenario_id: str):
    """M4: Run the engine for a non-base scenario and save the summary."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    scenario = get_scenario(scenario_id, user.user_id)
    if scenario is None or scenario.is_base_case:
        return JSONResponse({"error": "Scenario not found or is base case"}, status_code=422)

    col_key = request.query_params.get("col", "downside")

    # Build effective snapshot: start from template defaults, overlay
    # base_input_set, then snapshot, then current overrides.  Strip
    # empty-string values so legacy records whose numeric fields were
    # stored as '' (e.g. Generic Wind Reference gearing_pct) don't shadow a valid default.
    def _nonempty(d):
        return {k: v for k, v in (d or {}).items() if v is not None and str(v).strip() != ""}

    # Determine template source first (needed to choose defaults layer)
    template_source = scenario.source_project_template or ""
    if not template_source:
        proj_rec = get_project_record(user_id=scenario.user_id, project_id=scenario.project_id)
        template_source = (proj_rec.template_source if proj_rec else None) or "generic_wind"
    project_type = _m4_template_to_project_type(template_source)

    # Map from matrix display field names (attr) to canonical engine field names.
    # The scenario matrix stores overrides using the attr names from ALL_ROWS,
    # but build_projectinputs_from_snapshot expects the canonical snapshot names.
    _MATRIX_ALIAS_TO_CANONICAL = {
        "ppa_tariff_eur_mwh":   "tariff_eur_mwh",
        "operating_hours_p50":  "p50_hours",
        "opex_y1_total_keur":   "opex_y1_keur",
        "senior_tenor_years":   "tenor_years",
    }

    def _resolve_aliases(d):
        out = {}
        for k, v in (d or {}).items():
            out[_MATRIX_ALIAS_TO_CANONICAL.get(k, k)] = v
        return out

    template_defaults = _nonempty(_default_workspace_snapshot(template_source))
    effective_snapshot = {
        **template_defaults,
        **_nonempty(_resolve_aliases(scenario.base_input_set)),
        **_nonempty(_resolve_aliases(scenario.snapshot)),
        **_nonempty(_resolve_aliases(scenario.overrides)),
    }

    try:
        project_inputs = build_projectinputs_from_snapshot(effective_snapshot)
        result = run_project(
            project_type=project_type,
            scenario="Base",
            project_inputs_override=project_inputs,
        )
        summary = runtime_summary_to_dict(
            result,
            project_id=scenario.project_id,
            project_name=scenario.scenario_name,
        )
        update_scenario_last_run_summary(
            user_id=user.user_id,
            scenario_id=scenario_id,
            last_run_summary=summary,
        )

        kpis = result.get("kpis", {})
        # IRR-ANOMALY-1-FIX: matrix badge now uses the same top-level
        # metrics as the Dashboard Run summary (project_irr + avg_dscr)
        # so Base vs Downside comparisons are not misled by mixing
        # Project IRR with Equity IRR, or Avg DSCR with Min DSCR.
        # Phase: presentation-only fix. Engine output and overrides
        # are unchanged.
        project_irr_raw = kpis.get("project_irr")
        avg_dscr_raw = kpis.get("avg_dscr")
        project_irr = f"{float(project_irr_raw) * 100:.2f}%" if project_irr_raw is not None else None
        avg_dscr = f"{avg_dscr_raw:.2f}x".replace(".00x", ".0x") if avg_dscr_raw is not None else None

        response = templates.TemplateResponse(
            request=request,
            name="partials/_matrix_run_result.html",
            context={
                "scenario_id": scenario_id,
                "col_key": col_key,
                "run_ok": True,
                "project_irr": project_irr,
                "avg_dscr": avg_dscr,
                "error_msg": None,
            },
        )
        response.headers["HX-Trigger"] = "matrixRunComplete"
        return response

    except Exception as exc:
        response = templates.TemplateResponse(
            request=request,
            name="partials/_matrix_run_result.html",
            context={
                "scenario_id": scenario_id,
                "col_key": col_key,
                "run_ok": False,
                "project_irr": None,
                "avg_dscr": None,
                "error_msg": str(exc)[:120],
            },
        )
        response.headers["HX-Trigger"] = "matrixRunComplete"
        return response

# ── End M4 ───────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8765)
