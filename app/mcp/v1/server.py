"""FINCO MCP V1 — Read-only institutional agent interface.

Thin wrapper over the merged API v1.1 institutional service layer.
MCP is NOT a new authority layer — it delegates every data request to:
  app.api.v1_1.institutional.*

Contract guarantees (mirrors Correction A + Correction B):
  - Signed session only — FINCO_SESSION_TOKEN env var, never tool args.
  - AVAILABLE / UNAVAILABLE / STALE semantics preserved from API v1.1.
  - MISSING != ZERO: None values stay None.
  - /validation != /verify (separate authorities, separate tools).
  - Verify fails closed when no source-proven binding exists.
  - R-LIVE GET performs zero history writes.
  - No raw exception text, stack traces, secrets, or env values in responses.
  - financial_engine/**, finco_core/**, app/radar_rwa/**, finco_radar/authority/** = ZERO DIFF.
  - PRODUCTION_VERIFIED_ASSET_COUNT must not increase.
  - No XLSX binary exposed via MCP V1.

Auth: FINCO_SESSION_TOKEN env var → signed session → user_id.
      Tools that require auth return AUTHENTICATION_REQUIRED state when absent.

Versioning: every response carries api_version + schema_version from API v1.1.
Exception boundary: unexpected service exceptions → UNAVAILABLE/SERVICE_UNAVAILABLE.

SDK: mcp==2.2.0 (MCPServer).
"""
from __future__ import annotations

from typing import Any, Optional

from importlib.metadata import version as _pkg_version

# ── SDK version gate ───────────────────────────────────────────────────────────
# Fail fast if a version that lacks MCPServer is loaded at import time.
_MCP_VERSION: str = _pkg_version("mcp")
_mcp_version_parts = _MCP_VERSION.split(".")
_mcp_major = int(_mcp_version_parts[0])
_mcp_minor = int(_mcp_version_parts[1]) if len(_mcp_version_parts) > 1 else 0
if (_mcp_major, _mcp_minor) < (2, 2):
    raise RuntimeError(
        f"FINCO MCP V1 requires mcp>=2.2.0; "
        f"running mcp=={_MCP_VERSION}. "
        "Update the mcp package: pip install 'mcp>=2.2.0,<3.0.0'"
    )

from mcp.server.mcpserver import MCPServer

from app.mcp.v1.auth import AuthenticationRequired, require_mcp_user_id

mcp = MCPServer(
    "FINCO Institutional MCP V1",
    description=(
        "Read-only agent interface over FINCO institutional API v1.1. "
        "Exposes last-run summaries, KPIs, run identity, model validation, "
        "asset verification, and R-LIVE reference data. Zero engine reruns. "
        "Zero history writes on read."
    ),
    version="1.0.0",
)

# ── Sentinel for service-layer errors ────────────────────────────────────────
_SERVICE_ERROR = object()


# ── Response helpers ──────────────────────────────────────────────────────────

def _build_response(
    state: str,
    *,
    project_id: Optional[str] = None,
    data: Optional[Any] = None,
    evidence: Optional[Any] = None,
    reason: Optional[str] = None,
) -> dict[str, Any]:
    """Build a versioned MCP tool response.

    Every response carries api_version and schema_version from API v1.1.
    These are the same constants used by the HTTP router — MCP is NOT
    a second schema authority.
    """
    from app.api.v1_1.schemas import API_VERSION, SCHEMA_VERSION
    r: dict[str, Any] = {
        "api_version": API_VERSION,
        "schema_version": SCHEMA_VERSION,
        "state": state,
    }
    if project_id is not None:
        r["project_id"] = project_id
    if reason is not None:
        r["reason"] = reason
    if data is not None:
        r["data"] = data
    if evidence is not None:
        r["evidence"] = evidence
    return r


def _auth_required_response() -> dict[str, Any]:
    """Typed AUTHENTICATION_REQUIRED response — versioned, no session details."""
    return _build_response(
        "AUTHENTICATION_REQUIRED",
        reason=(
            "A valid FINCO_SESSION_TOKEN environment variable is required. "
            "Set a signed session token before starting the MCP server."
        ),
    )


def _service_unavailable_response(project_id: Optional[str] = None) -> dict[str, Any]:
    """Closed-boundary SERVICE_UNAVAILABLE — no exception text, no secrets."""
    return _build_response(
        "UNAVAILABLE",
        project_id=project_id,
        reason="SERVICE_UNAVAILABLE",
    )


def _safe_call(fn: Any, *args: Any, **kwargs: Any) -> Any:
    """Call fn(*args, **kwargs), returning _SERVICE_ERROR on any exception.

    Never exposes exception text, repr, stack traces, session tokens,
    RPC URLs, database paths, or any environment value.
    AuthenticationRequired is NOT caught here — it is handled before
    service calls and has its own typed state.
    """
    try:
        return fn(*args, **kwargs)
    except Exception:
        return _SERVICE_ERROR


# ── Tool 1: finco_supported_today ──────────────────────────────────────────

@mcp.tool(
    description=(
        "Return canonical FINCO supported-today capabilities from PRODUCT_CAPABILITIES. "
        "Public — no session required."
    )
)
def finco_supported_today() -> dict[str, Any]:
    """Return the full set of capabilities FINCO supports today."""
    from app.api.v1_1.institutional import get_supported_today
    result = _safe_call(get_supported_today)
    if result is _SERVICE_ERROR:
        return _service_unavailable_response()
    return _build_response("AVAILABLE", data=result)


# ── Tool 2: finco_projects ─────────────────────────────────────────────────

@mcp.tool(
    description=(
        "List all projects for the authenticated session user. "
        "Requires a valid FINCO_SESSION_TOKEN."
    )
)
def finco_projects() -> dict[str, Any]:
    """Return project list for the session user."""
    try:
        user_id = require_mcp_user_id()
    except AuthenticationRequired:
        return _auth_required_response()

    from app.api.v1_1.institutional import get_projects_for_user
    result = _safe_call(get_projects_for_user, user_id)
    if result is _SERVICE_ERROR:
        return _service_unavailable_response()
    return _build_response("AVAILABLE", data=result)


# ── Tool 3: finco_last_run ─────────────────────────────────────────────────

@mcp.tool(
    description=(
        "Return canonical Last Run summary for a project. "
        "State is AVAILABLE (committed run exists) or UNAVAILABLE (no committed run). "
        "STALE is not a valid state here. "
        "Requires a valid FINCO_SESSION_TOKEN."
    )
)
def finco_last_run(project_id: str) -> dict[str, Any]:
    """Return the canonical Last Run summary for the given project_id."""
    try:
        user_id = require_mcp_user_id()
    except AuthenticationRequired:
        return _auth_required_response()

    from app.api.v1_1.institutional import get_last_run_summary
    result = _safe_call(get_last_run_summary, user_id, project_id)
    if result is _SERVICE_ERROR:
        return _service_unavailable_response(project_id)
    state, data = result
    return _build_response(state, project_id=project_id, data=data)


# ── Tool 4: finco_run_identity ─────────────────────────────────────────────

@mcp.tool(
    description=(
        "Return run identity and certificate metadata for a project's canonical Last Run. "
        "Includes working_copy_changed_since_run flag. "
        "Requires a valid FINCO_SESSION_TOKEN."
    )
)
def finco_run_identity(project_id: str) -> dict[str, Any]:
    """Return run identity / certificate metadata for the given project_id."""
    try:
        user_id = require_mcp_user_id()
    except AuthenticationRequired:
        return _auth_required_response()

    from app.api.v1_1.institutional import get_run_identity
    result = _safe_call(get_run_identity, user_id, project_id)
    if result is _SERVICE_ERROR:
        return _service_unavailable_response(project_id)
    state, data = result
    return _build_response(state, project_id=project_id, data=data)


# ── Tool 5: finco_kpis ─────────────────────────────────────────────────────

@mcp.tool(
    description=(
        "Return core institutional KPIs from the canonical Last Run. "
        "No model re-run: values are read from persisted last_runtime_summary. "
        "MISSING != ZERO: unavailable KPIs carry state UNAVAILABLE, not 0.0. "
        "Requires a valid FINCO_SESSION_TOKEN."
    )
)
def finco_kpis(project_id: str) -> dict[str, Any]:
    """Return institutional KPIs (IRR, DSCR, NPV, etc.) for the given project_id."""
    try:
        user_id = require_mcp_user_id()
    except AuthenticationRequired:
        return _auth_required_response()

    from app.api.v1_1.institutional import get_kpis
    result = _safe_call(get_kpis, user_id, project_id)
    if result is _SERVICE_ERROR:
        return _service_unavailable_response(project_id)
    state, data = result
    return _build_response(state, project_id=project_id, data=data)


# ── Tool 6: finco_validation ───────────────────────────────────────────────

@mcp.tool(
    description=(
        "Return P1 institutional model validation evidence for a project's vertical. "
        "Delegates to app.model_validation.runner — NOT app.verified. "
        "Runs against the canonical reference; Working Copy state is irrelevant. "
        "Requires a valid FINCO_SESSION_TOKEN."
    )
)
def finco_validation(project_id: str) -> dict[str, Any]:
    """Return model validation evidence for the given project_id."""
    try:
        user_id = require_mcp_user_id()
    except AuthenticationRequired:
        return _auth_required_response()

    from app.api.v1_1.institutional import get_institutional_validation
    result = _safe_call(get_institutional_validation, user_id, project_id)
    if result is _SERVICE_ERROR:
        return _service_unavailable_response(project_id)
    state, evidence = result
    return _build_response(state, project_id=project_id, evidence=evidence)


# ── Tool 7: finco_verify ───────────────────────────────────────────────────

@mcp.tool(
    description=(
        "Return canonical Verify evidence for a project from app.verified. "
        "NOT the same as model validation — separate authority, separate binding. "
        "Fails closed when no source-proven binding exists in the asset registry. "
        "PRODUCTION_VERIFIED_ASSET_COUNT must not increase. "
        "Requires a valid FINCO_SESSION_TOKEN."
    )
)
def finco_verify(project_id: str) -> dict[str, Any]:
    """Return Verify evidence for the given project_id."""
    try:
        user_id = require_mcp_user_id()
    except AuthenticationRequired:
        return _auth_required_response()

    from app.api.v1_1.institutional import get_verify_state
    result = _safe_call(get_verify_state, user_id, project_id)
    if result is _SERVICE_ERROR:
        return _service_unavailable_response(project_id)
    state, evidence = result
    return _build_response(state, project_id=project_id, evidence=evidence)


# ── Tool 8: finco_r_live ───────────────────────────────────────────────────

@mcp.tool(
    description=(
        "Return R-LIVE exact AssetKey reference data. "
        "State parity: AVAILABLE requires ALL four current components "
        "(onchain, token, underlying, premium) to be AVAILABLE. "
        "STALE if any component is STALE (price/value fields suppressed). "
        "UNAVAILABLE if any component is UNAVAILABLE/IDENTITY_UNAVAILABLE. "
        "GET performs zero history writes. "
        "uid must be the exact canonical_id (chain:address) — no ticker/fuzzy identity. "
        "Public — no session required."
    )
)
def finco_r_live(uid: str) -> dict[str, Any]:
    """Return R-LIVE reference data for the exact AssetKey uid."""
    from app.api.v1_1.institutional import get_r_live
    result = _safe_call(get_r_live, uid)
    if result is _SERVICE_ERROR:
        return _service_unavailable_response()
    state, data = result
    return _build_response(state, data=data)


# ── Tool 9: finco_export_metadata ──────────────────────────────────────────

@mcp.tool(
    description=(
        "Return XLSX export contract metadata for a project's canonical Last Run. "
        "Does NOT produce or return the XLSX binary. "
        "Use the download_path from the response to retrieve the file via the HTTP API. "
        "Requires a valid FINCO_SESSION_TOKEN."
    )
)
def finco_export_metadata(project_id: str) -> dict[str, Any]:
    """Return XLSX export metadata (path, filename, authority) for the given project_id."""
    try:
        user_id = require_mcp_user_id()
    except AuthenticationRequired:
        return _auth_required_response()

    from app.api.v1_1.institutional import get_export_metadata
    result = _safe_call(get_export_metadata, user_id, project_id)
    if result is _SERVICE_ERROR:
        return _service_unavailable_response(project_id)
    state, data = result
    return _build_response(state, project_id=project_id, data=data)
