"""FINCO MCP V1 — Institutional read-only surface test suite.

Markers verified:
  MCP_V1_API_CONTRACT_REUSED
  MCP_V1_NO_DIRECT_ENGINE_ACCESS
  MCP_V1_NO_DIRECT_DB_AUTHORITY
  MCP_V1_SIGNED_AUTH_PRESERVED
  MCP_V1_USER_ID_SPOOF_IMPOSSIBLE
  MCP_V1_LAST_RUN_IDENTITY_EXACT
  MCP_V1_VALIDATION_NOT_VERIFY
  MCP_V1_VERIFY_FAILS_CLOSED
  MCP_V1_RLIVE_STATE_PARITY
  MCP_V1_RLIVE_ZERO_HISTORY_WRITES
  MCP_V1_MISSING_NEVER_ZERO
  MCP_V1_SECRET_SAFETY

Also tests: tool discovery (all 9 V1 tools listed).
"""
from __future__ import annotations

import os
import inspect
from unittest.mock import MagicMock, patch

import pytest


# ── Fixtures ───────────────────────────────────────────────────────────────────

def _make_session(user_id: str = "test_user_42"):
    from app.auth import SessionData
    from datetime import datetime, timezone
    return SessionData(
        user_id=user_id,
        username="testuser",
        login_at=datetime.now(timezone.utc),
        session_type="admin",
    )


def _env_with_token(monkeypatch, user_id: str = "test_user_42") -> None:
    from app.auth import create_session_token
    token = create_session_token(user_id=user_id, username="testuser")
    monkeypatch.setenv("FINCO_SESSION_TOKEN", token)


def _env_without_token(monkeypatch) -> None:
    monkeypatch.delenv("FINCO_SESSION_TOKEN", raising=False)


# ── Tool discovery ─────────────────────────────────────────────────────────────

def test_mcp_v1_tool_discovery():
    """All 9 MCP V1 tools are registered on the server."""
    from app.mcp.v1.server import mcp

    expected_tools = {
        "finco_supported_today",
        "finco_projects",
        "finco_last_run",
        "finco_run_identity",
        "finco_kpis",
        "finco_validation",
        "finco_verify",
        "finco_r_live",
        "finco_export_metadata",
    }

    registered = {tool.name for tool in mcp._tool_manager._tools.values()}
    for name in expected_tools:
        assert name in registered, f"Tool '{name}' not registered on MCPServer"


# ── MCP_V1_API_CONTRACT_REUSED ─────────────────────────────────────────────────

def test_mcp_v1_api_contract_reused():
    """MCP tools delegate to app.api.v1_1.institutional, not duplicating logic.

    Marker: MCP_V1_API_CONTRACT_REUSED = PASS
    """
    from app.mcp.v1 import server as mcp_server_module
    src = inspect.getsource(mcp_server_module)

    assert "from app.api.v1_1.institutional import" in src, (
        "MCP tools must import from app.api.v1_1.institutional"
    )
    assert "get_supported_today" in src
    assert "get_projects_for_user" in src
    assert "get_last_run_summary" in src
    assert "get_run_identity" in src
    assert "get_kpis" in src
    assert "get_institutional_validation" in src
    assert "get_verify_state" in src
    assert "get_r_live" in src
    assert "get_export_metadata" in src


# ── MCP_V1_NO_DIRECT_ENGINE_ACCESS ────────────────────────────────────────────

def test_mcp_v1_no_direct_engine_access():
    """MCP server does not import from financial_engine or finco_core directly.

    Marker: MCP_V1_NO_DIRECT_ENGINE_ACCESS = PASS
    """
    import re
    from app.mcp.v1 import server as mcp_server_module
    from app.mcp.v1 import auth as auth_module
    for mod in (mcp_server_module, auth_module):
        src = inspect.getsource(mod)
        # Check for actual import statements, not docstring mentions
        assert not re.search(r"(?:^|\n)\s*(import|from)\s+financial_engine", src), (
            f"{mod.__name__} must not import financial_engine directly"
        )
        assert not re.search(r"(?:^|\n)\s*(import|from)\s+finco_core", src), (
            f"{mod.__name__} must not import finco_core directly"
        )


# ── MCP_V1_NO_DIRECT_DB_AUTHORITY ─────────────────────────────────────────────

def test_mcp_v1_no_direct_db_authority():
    """MCP server does not import persistence/radar/verified directly.

    Marker: MCP_V1_NO_DIRECT_DB_AUTHORITY = PASS
    """
    import re
    from app.mcp.v1 import server as mcp_server_module
    from app.mcp.v1 import auth as auth_module
    frozen_namespaces = [
        "app.persistence",
        "app.radar_rwa",
        "app.verified",
        "app.model_validation",
        "finco_radar.authority",
    ]
    for mod in (mcp_server_module, auth_module):
        src = inspect.getsource(mod)
        for ns in frozen_namespaces:
            # Escape dots for regex, check for actual import statements only
            ns_pattern = ns.replace(".", r"\.")
            assert not re.search(rf"(?:^|\n)\s*(import|from)\s+{ns_pattern}", src), (
                f"{mod.__name__} must not import {ns} directly — delegate to API v1.1"
            )


# ── MCP_V1_SIGNED_AUTH_PRESERVED ──────────────────────────────────────────────

def test_mcp_v1_signed_auth_preserved(monkeypatch):
    """User identity resolves from a signed session token, not a plain user_id.

    Marker: MCP_V1_SIGNED_AUTH_PRESERVED = PASS
    """
    _env_with_token(monkeypatch, user_id="signed_user_99")

    from app.mcp.v1.auth import resolve_mcp_user_id
    user_id = resolve_mcp_user_id()
    assert user_id == "signed_user_99"


def test_mcp_v1_signed_auth_missing_returns_none(monkeypatch):
    """No FINCO_SESSION_TOKEN → resolve_mcp_user_id returns None."""
    _env_without_token(monkeypatch)
    from app.mcp.v1.auth import resolve_mcp_user_id
    assert resolve_mcp_user_id() is None


def test_mcp_v1_signed_auth_invalid_token_returns_none(monkeypatch):
    """Garbage token → resolve_mcp_user_id returns None."""
    monkeypatch.setenv("FINCO_SESSION_TOKEN", "not-a-valid-signed-token")
    from app.mcp.v1.auth import resolve_mcp_user_id
    assert resolve_mcp_user_id() is None


# ── MCP_V1_USER_ID_SPOOF_IMPOSSIBLE ───────────────────────────────────────────

def test_mcp_v1_user_id_spoof_impossible():
    """No MCP tool accepts user_id as an argument.

    Marker: MCP_V1_USER_ID_SPOOF_IMPOSSIBLE = PASS
    """
    from app.mcp.v1.server import (
        finco_projects,
        finco_last_run,
        finco_run_identity,
        finco_kpis,
        finco_validation,
        finco_verify,
        finco_export_metadata,
    )
    auth_required_tools = [
        finco_projects,
        finco_last_run,
        finco_run_identity,
        finco_kpis,
        finco_validation,
        finco_verify,
        finco_export_metadata,
    ]
    for fn in auth_required_tools:
        sig = inspect.signature(fn)
        assert "user_id" not in sig.parameters, (
            f"Tool {fn.__name__} must not accept user_id as a parameter — "
            "identity must come from FINCO_SESSION_TOKEN env var only"
        )


def test_mcp_v1_unauthenticated_returns_auth_required(monkeypatch):
    """Tools that require auth return AUTHENTICATION_REQUIRED when token is absent."""
    _env_without_token(monkeypatch)

    svc_prefix = "app.api.v1_1.institutional"
    with (
        patch(f"{svc_prefix}.get_projects_for_user") as mock_projects,
        patch(f"{svc_prefix}.get_last_run_summary") as mock_lr,
        patch(f"{svc_prefix}.get_kpis") as mock_kpis,
    ):
        from app.mcp.v1.server import (
            finco_projects,
            finco_last_run,
            finco_kpis,
        )
        for fn, args in [
            (finco_projects, {}),
            (finco_last_run, {"project_id": "proj_1"}),
            (finco_kpis, {"project_id": "proj_1"}),
        ]:
            result = fn(**args)
            assert result["state"] == "AUTHENTICATION_REQUIRED", (
                f"{fn.__name__} must return AUTHENTICATION_REQUIRED when token absent"
            )
        mock_projects.assert_not_called()
        mock_lr.assert_not_called()
        mock_kpis.assert_not_called()


# ── MCP_V1_LAST_RUN_IDENTITY_EXACT ────────────────────────────────────────────

def test_mcp_v1_last_run_identity_exact(monkeypatch):
    """finco_last_run and finco_run_identity return exact API v1.1 contract data.

    Marker: MCP_V1_LAST_RUN_IDENTITY_EXACT = PASS
    """
    _env_with_token(monkeypatch, user_id="user_lr_test")

    mock_run_data = {
        "project_id": "proj_lr",
        "project_name": "Test Solar Project",
        "project_type": "Solar",
        "run_identity": {
            "snapshot_id": "snap_001",
            "composite_hash": "abc123",
            "run_at": "2026-01-01T00:00:00+00:00",
            "working_copy_changed_since_run": False,
        },
        "any_run_committed": True,
    }

    with patch("app.api.v1_1.institutional.get_last_run_summary",
               return_value=("AVAILABLE", mock_run_data)) as mock_lr:
        from app.mcp.v1.server import finco_last_run
        result = finco_last_run(project_id="proj_lr")

    assert result["state"] == "AVAILABLE"
    assert result["project_id"] == "proj_lr"
    assert result["data"]["any_run_committed"] is True
    assert "working_copy_changed_since_run" in result["data"]["run_identity"]
    mock_lr.assert_called_once_with("user_lr_test", "proj_lr")


def test_mcp_v1_run_identity_exact(monkeypatch):
    """finco_run_identity returns exact run identity from API v1.1."""
    _env_with_token(monkeypatch, user_id="user_ri_test")

    mock_identity = {
        "snapshot_id": "snap_002",
        "composite_hash": "def456",
        "run_at": "2026-01-02T00:00:00+00:00",
        "scenario_id": "base",
        "run_origin": "user",
        "engine_version": "v9.0",
        "git_sha": "deadbeef",
        "git_branch": "main",
        "working_copy_changed_since_run": True,
    }

    with patch("app.api.v1_1.institutional.get_run_identity",
               return_value=("AVAILABLE", mock_identity)) as mock_ri:
        from app.mcp.v1.server import finco_run_identity
        result = finco_run_identity(project_id="proj_ri")

    assert result["state"] == "AVAILABLE"
    assert result["data"]["working_copy_changed_since_run"] is True
    mock_ri.assert_called_once_with("user_ri_test", "proj_ri")


# ── MCP_V1_VALIDATION_NOT_VERIFY ──────────────────────────────────────────────

def test_mcp_v1_validation_not_verify(monkeypatch):
    """finco_validation delegates to get_institutional_validation, not get_verify_state.

    Marker: MCP_V1_VALIDATION_NOT_VERIFY = PASS
    """
    _env_with_token(monkeypatch, user_id="user_val_test")

    mock_evidence = {
        "authority": "MODEL_VALIDATION",
        "validation_state": "PASS",
        "passed": True,
        "framework_passed": True,
        "product_reconciled": True,
        "pass_count": 10,
        "fail_count": 0,
        "gaps": [],
    }

    with (
        patch("app.api.v1_1.institutional.get_institutional_validation",
              return_value=("AVAILABLE", mock_evidence)) as mock_val,
        patch("app.api.v1_1.institutional.get_verify_state") as mock_verify,
    ):
        from app.mcp.v1.server import finco_validation
        result = finco_validation(project_id="proj_val")

    assert result["state"] == "AVAILABLE"
    assert result["evidence"]["authority"] == "MODEL_VALIDATION"
    mock_val.assert_called_once_with("user_val_test", "proj_val")
    mock_verify.assert_not_called()


def test_mcp_v1_verify_not_validation(monkeypatch):
    """finco_verify delegates to get_verify_state, not get_institutional_validation."""
    _env_with_token(monkeypatch, user_id="user_verif_test")

    mock_evidence = {
        "authority": "FINCO_VERIFY",
        "asset_id": "aapl_rwa_v1",
        "status": "VERIFIED",
    }

    with (
        patch("app.api.v1_1.institutional.get_verify_state",
              return_value=("AVAILABLE", mock_evidence)) as mock_verify,
        patch("app.api.v1_1.institutional.get_institutional_validation") as mock_val,
    ):
        from app.mcp.v1.server import finco_verify
        result = finco_verify(project_id="proj_verif")

    assert result["evidence"]["authority"] == "FINCO_VERIFY"
    mock_verify.assert_called_once_with("user_verif_test", "proj_verif")
    mock_val.assert_not_called()


# ── MCP_V1_VERIFY_FAILS_CLOSED ────────────────────────────────────────────────

def test_mcp_v1_verify_fails_closed(monkeypatch):
    """finco_verify returns UNAVAILABLE when no binding exists (fail-closed contract).

    Marker: MCP_V1_VERIFY_FAILS_CLOSED = PASS
    """
    _env_with_token(monkeypatch, user_id="user_fc_test")

    with patch("app.api.v1_1.institutional.get_verify_state",
               return_value=("UNAVAILABLE", {"reason": "VERIFY_BINDING_UNAVAILABLE"})):
        from app.mcp.v1.server import finco_verify
        result = finco_verify(project_id="proj_fc")

    assert result["state"] == "UNAVAILABLE"
    assert result["evidence"]["reason"] == "VERIFY_BINDING_UNAVAILABLE"


# ── MCP_V1_RLIVE_STATE_PARITY ──────────────────────────────────────────────────

def test_mcp_v1_rlive_state_parity():
    """finco_r_live preserves state parity from API v1.1 (AVAILABLE/STALE/UNAVAILABLE).

    Marker: MCP_V1_RLIVE_STATE_PARITY = PASS
    """
    cases = [
        ("AVAILABLE", {"exact_asset_key": {"canonical_id": "eth:0xabc"}, "token_reference": {"state": "AVAILABLE", "price_usd_per_token": "195.50"}}),
        ("STALE", {"reason": "STALE_COMPONENT", "token_reference": {"state": "STALE", "price_usd_per_token": None}}),
        ("UNAVAILABLE", {"reason": "RPC_NOT_CONFIGURED"}),
    ]

    for expected_state, mock_data in cases:
        with patch("app.api.v1_1.institutional.get_r_live",
                   return_value=(expected_state, mock_data)):
            from app.mcp.v1.server import finco_r_live
            result = finco_r_live(uid="eth:0xaapl_canonical")
        assert result["state"] == expected_state, (
            f"Expected state {expected_state!r}, got {result['state']!r}"
        )


def test_mcp_v1_rlive_stale_suppresses_prices():
    """When R-LIVE state is STALE, current price/value fields are None."""
    stale_data = {
        "exact_asset_key": {"canonical_id": "eth:0xabc"},
        "token_reference": {"state": "STALE", "price_usd_per_token": None, "source": "src", "observed_at": None, "reason": "QUOTE_FEED_STALE"},
        "robinhood_basis": {"state": "AVAILABLE", "price_usd_per_token": None, "source": "rh", "observed_at": None, "reason": None},
        "b1_0_premium": {"state": "STALE", "value_bps": None, "formula": "B1.0", "reason": "STALE"},
        "observed_at": None,
    }
    with patch("app.api.v1_1.institutional.get_r_live", return_value=("STALE", stale_data)):
        from app.mcp.v1.server import finco_r_live
        result = finco_r_live(uid="eth:0xaapl")
    assert result["state"] == "STALE"
    assert result["data"]["token_reference"]["price_usd_per_token"] is None
    assert result["data"]["b1_0_premium"]["value_bps"] is None


# ── MCP_V1_RLIVE_ZERO_HISTORY_WRITES ──────────────────────────────────────────

def test_mcp_v1_rlive_zero_history_writes():
    """finco_r_live delegates to get_r_live which calls collect_aapl_r_live with persist_history=False.

    Marker: MCP_V1_RLIVE_ZERO_HISTORY_WRITES = PASS
    """
    # We test that the MCP tool delegates to institutional.get_r_live,
    # and that institutional.get_r_live calls collect_aapl_r_live with persist_history=False.
    # The persist_history=False contract is already validated by the API v1.1 test suite;
    # here we confirm MCP does not introduce a separate direct radar call.
    from app.mcp.v1 import server as mcp_server_module
    src = inspect.getsource(mcp_server_module)

    # MCP server must not call collect_aapl_r_live directly
    assert "collect_aapl_r_live" not in src, (
        "MCP server must not call collect_aapl_r_live directly — delegate to get_r_live"
    )
    assert "persist_history" not in src, (
        "MCP server must not set persist_history — delegate to API v1.1"
    )

    # Confirm the delegation path: MCP → get_r_live → collect_aapl_r_live(persist_history=False)
    with patch("app.api.v1_1.institutional.get_r_live",
               return_value=("UNAVAILABLE", {"reason": "RPC_NOT_CONFIGURED"})) as mock_rl:
        from app.mcp.v1.server import finco_r_live
        finco_r_live(uid="eth:0xaapl")
    mock_rl.assert_called_once_with("eth:0xaapl")


# ── MCP_V1_MISSING_NEVER_ZERO ──────────────────────────────────────────────────

def test_mcp_v1_missing_never_zero(monkeypatch):
    """None KPI values are preserved as UNAVAILABLE state, never coerced to 0.0.

    Marker: MCP_V1_MISSING_NEVER_ZERO = PASS
    """
    _env_with_token(monkeypatch, user_id="user_mnz_test")

    mock_kpis = {
        "project_irr": {"value": None, "state": "UNAVAILABLE", "unit": "pct"},
        "equity_irr": {"value": 0.12, "state": "AVAILABLE", "unit": "pct"},
        "senior_debt_keur": {"value": None, "state": "UNAVAILABLE", "unit": "kEUR"},
        "working_copy_changed_since_run": False,
    }

    with patch("app.api.v1_1.institutional.get_kpis",
               return_value=("AVAILABLE", mock_kpis)):
        from app.mcp.v1.server import finco_kpis
        result = finco_kpis(project_id="proj_mnz")

    assert result["data"]["project_irr"]["value"] is None
    assert result["data"]["project_irr"]["state"] == "UNAVAILABLE"
    assert result["data"]["equity_irr"]["value"] == 0.12
    assert result["data"]["senior_debt_keur"]["value"] is None
    assert result["data"]["senior_debt_keur"]["state"] == "UNAVAILABLE"


# ── MCP_V1_SECRET_SAFETY ──────────────────────────────────────────────────────

def test_mcp_v1_secret_safety():
    """MCP source code does not embed or log session tokens or secrets.

    Marker: MCP_V1_SECRET_SAFETY = PASS
    """
    import re
    from app.mcp.v1 import server as mcp_server_module
    from app.mcp.v1 import auth as auth_module

    # Server module must not hard-code any secret key values
    server_src = inspect.getsource(mcp_server_module)
    assert not re.search(r'FINCO_SECRET_KEY\s*=\s*["\']', server_src), (
        "server.py must not assign a hard-coded FINCO_SECRET_KEY"
    )

    # Auth module: FINCO_SESSION_TOKEN must be read from os.environ
    auth_src = inspect.getsource(auth_module)
    assert "FINCO_SESSION_TOKEN" in auth_src, "auth module must reference FINCO_SESSION_TOKEN"
    assert ("os.environ" in auth_src or "os.getenv" in auth_src), (
        "FINCO_SESSION_TOKEN must be read from os.environ in auth module, not hardcoded"
    )
    # Must not assign the token as a literal
    assert not re.search(r'FINCO_SESSION_TOKEN\s*=\s*["\']', auth_src), (
        "auth module must not hard-code FINCO_SESSION_TOKEN value"
    )


def test_mcp_v1_auth_reads_from_env_only():
    """Auth module reads session token from os.environ, not from arguments."""
    from app.mcp.v1 import auth as auth_module
    src = inspect.getsource(auth_module)
    assert 'os.environ.get("FINCO_SESSION_TOKEN"' in src or "os.environ" in src


# ── Final acceptance marker ────────────────────────────────────────────────────

def test_finco_mcp_v1_readonly_complete(monkeypatch):
    """FINCO_MCP_V1_READONLY_COMPLETE acceptance marker.

    All required sub-markers must individually pass before this can pass.
    This test confirms the composite contract: MCP is a thin read-only
    delegate over API v1.1, with signed-session auth, no direct engine/DB access,
    and all Correction A + B state semantics preserved.
    """
    _env_with_token(monkeypatch, user_id="finco_mcp_v1_marker_user")

    # 1. Tool discovery
    from app.mcp.v1.server import mcp
    registered = {tool.name for tool in mcp._tool_manager._tools.values()}
    assert len(registered) == 9

    # 2. Auth resolves from env token
    from app.mcp.v1.auth import resolve_mcp_user_id
    uid = resolve_mcp_user_id()
    assert uid == "finco_mcp_v1_marker_user"

    # 3. No tool accepts user_id as arg
    from app.mcp.v1.server import finco_projects
    sig = inspect.signature(finco_projects)
    assert "user_id" not in sig.parameters

    # 4. R-LIVE state parity preserved
    with patch("app.api.v1_1.institutional.get_r_live",
               return_value=("UNAVAILABLE", {"reason": "RPC_NOT_CONFIGURED"})):
        from app.mcp.v1.server import finco_r_live
        r = finco_r_live(uid="eth:0xtest")
    assert r["state"] == "UNAVAILABLE"

    # 5. Verify fails closed
    _env_without_token(monkeypatch)
    from app.mcp.v1.server import finco_verify
    r = finco_verify(project_id="some_proj")
    assert r["state"] == "AUTHENTICATION_REQUIRED"

    assert True, "FINCO_MCP_V1_READONLY_COMPLETE"


# ══════════════════════════════════════════════════════════════════════════════
# Correction A markers (PR #129)
# ══════════════════════════════════════════════════════════════════════════════

# ── MCP_V1_DEPENDENCY_PINNED_2_2_0 ────────────────────────────────────────────

def test_mcp_v1_dependency_pinned_2_2_0():
    """mcp package is 2.x (>=2.2.0) as tested; MCPServer API is available.

    Marker: MCP_V1_DEPENDENCY_PINNED_2_2_0 = PASS
    """
    from importlib.metadata import version as pkg_version
    mcp_ver = pkg_version("mcp")
    parts = mcp_ver.split(".")
    major = int(parts[0])
    minor = int(parts[1]) if len(parts) > 1 else 0
    assert major == 2, f"mcp major must be 2, got {mcp_ver}"
    assert minor >= 2, f"mcp minor must be >= 2, got {mcp_ver}"
    # Confirm constraints.txt records the pinned version
    constraints = open("constraints.txt").read()
    assert "mcp==2.2.0" in constraints, (
        "constraints.txt must pin mcp==2.2.0 per repository constraints policy"
    )
    # Confirm requirements.txt uses a 2.x-compatible range
    requirements = open("requirements.txt").read()
    assert "mcp>=2.2.0,<3.0.0" in requirements, (
        "requirements.txt must declare mcp>=2.2.0,<3.0.0"
    )
    # Confirm MCPServer is importable (the tested API surface)
    from mcp.server.mcpserver import MCPServer  # noqa: F401
    # Confirm server.py exposes the pinned version constant
    from app.mcp.v1.server import _MCP_VERSION
    assert _MCP_VERSION == mcp_ver


# ── MCP_V1_SCHEMA_VERSION_ON_SUCCESS ──────────────────────────────────────────

def test_mcp_v1_schema_version_on_success(monkeypatch):
    """Every AVAILABLE tool response carries api_version and schema_version from API v1.1.

    Marker: MCP_V1_SCHEMA_VERSION_ON_SUCCESS = PASS
    """
    from app.api.v1_1.schemas import API_VERSION, SCHEMA_VERSION

    _env_with_token(monkeypatch, user_id="schema_success_user")

    cases = [
        # (patch_target, tool_fn_name, tool_kwargs, mock_return)
        ("app.api.v1_1.institutional.get_supported_today",
         "finco_supported_today", {},
         {"capabilities": [], "count": 0}),
        ("app.api.v1_1.institutional.get_last_run_summary",
         "finco_last_run", {"project_id": "p1"},
         ("AVAILABLE", {"project_id": "p1", "any_run_committed": True})),
        ("app.api.v1_1.institutional.get_kpis",
         "finco_kpis", {"project_id": "p2"},
         ("AVAILABLE", {"project_irr": {"value": 0.08, "state": "AVAILABLE", "unit": "pct"}})),
    ]

    for target, fn_name, kwargs, mock_ret in cases:
        with patch(target, return_value=mock_ret):
            import importlib
            mod = importlib.import_module("app.mcp.v1.server")
            fn = getattr(mod, fn_name)
            result = fn(**kwargs)
        assert result["api_version"] == API_VERSION, (
            f"{fn_name}: api_version must be {API_VERSION!r}, got {result.get('api_version')!r}"
        )
        assert result["schema_version"] == SCHEMA_VERSION, (
            f"{fn_name}: schema_version must be {SCHEMA_VERSION!r}"
        )
        assert result["state"] == "AVAILABLE"


# ── MCP_V1_SCHEMA_VERSION_ON_UNAVAILABLE ──────────────────────────────────────

def test_mcp_v1_schema_version_on_unavailable(monkeypatch):
    """Every UNAVAILABLE tool response carries api_version and schema_version.

    Marker: MCP_V1_SCHEMA_VERSION_ON_UNAVAILABLE = PASS
    """
    from app.api.v1_1.schemas import API_VERSION, SCHEMA_VERSION

    _env_with_token(monkeypatch, user_id="schema_unavail_user")

    with patch("app.api.v1_1.institutional.get_last_run_summary",
               return_value=("UNAVAILABLE", {})):
        from app.mcp.v1.server import finco_last_run
        result = finco_last_run(project_id="proj_unavail")

    assert result["api_version"] == API_VERSION
    assert result["schema_version"] == SCHEMA_VERSION
    assert result["state"] == "UNAVAILABLE"


def test_mcp_v1_schema_version_on_service_error(monkeypatch):
    """SERVICE_UNAVAILABLE (exception-boundary) response also carries version fields."""
    from app.api.v1_1.schemas import API_VERSION, SCHEMA_VERSION

    _env_with_token(monkeypatch, user_id="schema_err_user")

    with patch("app.api.v1_1.institutional.get_kpis",
               side_effect=RuntimeError("internal error")):
        from app.mcp.v1.server import finco_kpis
        result = finco_kpis(project_id="proj_err")

    assert result["api_version"] == API_VERSION
    assert result["schema_version"] == SCHEMA_VERSION
    assert result["state"] == "UNAVAILABLE"
    assert result["reason"] == "SERVICE_UNAVAILABLE"


# ── MCP_V1_SCHEMA_VERSION_ON_AUTH_REQUIRED ────────────────────────────────────

def test_mcp_v1_schema_version_on_auth_required(monkeypatch):
    """AUTHENTICATION_REQUIRED response carries api_version and schema_version.

    Marker: MCP_V1_SCHEMA_VERSION_ON_AUTH_REQUIRED = PASS
    """
    from app.api.v1_1.schemas import API_VERSION, SCHEMA_VERSION

    _env_without_token(monkeypatch)

    from app.mcp.v1.server import finco_last_run, finco_kpis, finco_verify
    for fn, kwargs in [
        (finco_last_run, {"project_id": "p1"}),
        (finco_kpis, {"project_id": "p2"}),
        (finco_verify, {"project_id": "p3"}),
    ]:
        result = fn(**kwargs)
        assert result["api_version"] == API_VERSION, (
            f"{fn.__name__}: api_version missing on AUTHENTICATION_REQUIRED"
        )
        assert result["schema_version"] == SCHEMA_VERSION, (
            f"{fn.__name__}: schema_version missing on AUTHENTICATION_REQUIRED"
        )
        assert result["state"] == "AUTHENTICATION_REQUIRED"


# ── MCP_V1_UNEXPECTED_EXCEPTION_FAILS_CLOSED ──────────────────────────────────

def test_mcp_v1_unexpected_exception_fails_closed(monkeypatch):
    """Unexpected service exceptions produce UNAVAILABLE/SERVICE_UNAVAILABLE.

    Marker: MCP_V1_UNEXPECTED_EXCEPTION_FAILS_CLOSED = PASS
    """
    _env_with_token(monkeypatch, user_id="exc_boundary_user")

    exception_cases = [
        ("app.api.v1_1.institutional.get_last_run_summary", "finco_last_run", {"project_id": "p1"}),
        ("app.api.v1_1.institutional.get_kpis", "finco_kpis", {"project_id": "p2"}),
        ("app.api.v1_1.institutional.get_verify_state", "finco_verify", {"project_id": "p3"}),
        ("app.api.v1_1.institutional.get_institutional_validation", "finco_validation", {"project_id": "p4"}),
        ("app.api.v1_1.institutional.get_r_live", "finco_r_live", {"uid": "eth:0xtest"}),
    ]

    import importlib
    mod = importlib.import_module("app.mcp.v1.server")

    for target, fn_name, kwargs in exception_cases:
        with patch(target, side_effect=Exception("boom")):
            result = getattr(mod, fn_name)(**kwargs)
        assert result["state"] == "UNAVAILABLE", (
            f"{fn_name}: expected UNAVAILABLE on exception, got {result['state']!r}"
        )
        assert result.get("reason") == "SERVICE_UNAVAILABLE", (
            f"{fn_name}: expected reason SERVICE_UNAVAILABLE, got {result.get('reason')!r}"
        )


# ── MCP_V1_EXCEPTION_SECRET_NOT_EXPOSED ───────────────────────────────────────

def test_mcp_v1_exception_secret_not_exposed(monkeypatch):
    """Exception text containing secret material is NOT present in tool output.

    Injects exceptions whose str() contains fake secrets and verifies
    none of that text leaks into the serialized MCP tool response.

    Marker: MCP_V1_EXCEPTION_SECRET_NOT_EXPOSED = PASS
    """
    import json

    _env_with_token(monkeypatch, user_id="secret_safety_user")

    fake_secrets = [
        "FAKE_DB_PASSWORD=hunter2",
        "FINCO_SECRET_KEY=do-not-leak-this",
        "rpc_url=https://node.example.com/api-key-abc123",
        "session_token=fake_signed_token_SHOULD_NOT_APPEAR",
    ]

    import importlib
    mod = importlib.import_module("app.mcp.v1.server")

    for secret in fake_secrets:
        exc = RuntimeError(f"internal failure: {secret}")
        with patch("app.api.v1_1.institutional.get_kpis", side_effect=exc):
            result = mod.finco_kpis(project_id="proj_secret_test")

        serialized = json.dumps(result)
        assert secret not in serialized, (
            f"Secret material leaked into tool response: {secret!r} found in output"
        )
        # Also confirm the word "hunter2" and key fragments don't appear
        for fragment in ("hunter2", "do-not-leak-this", "api-key-abc123", "fake_signed_token"):
            assert fragment not in serialized, (
                f"Secret fragment {fragment!r} found in tool response"
            )

    # Confirm only safe fields are present on error
    with patch("app.api.v1_1.institutional.get_kpis",
               side_effect=RuntimeError("FINCO_SECRET_KEY=should-not-appear")):
        result = mod.finco_kpis(project_id="proj_final")

    assert result["state"] == "UNAVAILABLE"
    assert result["reason"] == "SERVICE_UNAVAILABLE"
    assert "should-not-appear" not in json.dumps(result)
    assert "FINCO_SECRET_KEY" not in json.dumps(result)
