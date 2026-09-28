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
  - No raw exception text in tool responses.
  - financial_engine/**, finco_core/**, app/radar_rwa/**, finco_radar/authority/** = ZERO DIFF.
  - PRODUCTION_VERIFIED_ASSET_COUNT must not increase.
  - No XLSX binary exposed via MCP V1.

Auth: FINCO_SESSION_TOKEN env var → signed session → user_id.
      Tools that require auth return AUTHENTICATION_REQUIRED state when absent.

SDK: mcp>=2.0.0 (MCPServer, formerly FastMCP).
"""
from __future__ import annotations

from typing import Any

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

# ── Auth response helper ────────────────────────────────────────────────────

def _auth_required_response() -> dict[str, Any]:
    return {
        "state": "AUTHENTICATION_REQUIRED",
        "reason": (
            "A valid FINCO_SESSION_TOKEN environment variable is required. "
            "Set a signed session token before starting the MCP server."
        ),
    }


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
    return {
        "state": "AVAILABLE",
        "data": get_supported_today(),
    }


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
    return {
        "state": "AVAILABLE",
        "data": get_projects_for_user(user_id),
    }


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
    state, data = get_last_run_summary(user_id, project_id)
    return {"state": state, "project_id": project_id, "data": data}


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
    state, data = get_run_identity(user_id, project_id)
    return {"state": state, "project_id": project_id, "data": data}


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
    state, data = get_kpis(user_id, project_id)
    return {"state": state, "project_id": project_id, "data": data}


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
    state, evidence = get_institutional_validation(user_id, project_id)
    return {"state": state, "project_id": project_id, "evidence": evidence}


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
    state, evidence = get_verify_state(user_id, project_id)
    return {"state": state, "project_id": project_id, "evidence": evidence}


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
    state, data = get_r_live(uid)
    return {"state": state, "data": data}


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
    state, data = get_export_metadata(user_id, project_id)
    return {"state": state, "project_id": project_id, "data": data}
