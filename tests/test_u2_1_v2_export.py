"""U2.1 — V2 Workbook institutional export tests.

Covers:
  A. No-run state: resolve_export_authority raises CANONICAL_LAST_RUN_UNAVAILABLE
     when any_run_committed is False; build_institutional_workbook_export returns
     a 400 ExportResponse, not bytes.
  B. Canonical export: factory-reference path returns a successful ExportResponse
     with bytes, xlsx media type, canonical filename, and FACTORY_REFERENCE authority.
  C. Working-changed flag: export metadata carries export_working_changed_since_run
     "true" when working inputs differ from the last run.
  D. Scenario lineage: export metadata carries export_active_scenario_name and
     export_last_runtime_scenario_id when authority has scenario identity.
  E. Authority identity: ResolvedExportAuthority.authority_mode is always
     CANONICAL_LAST_RUN (or FACTORY_REFERENCE) — never PREVIEW_WORKING.
  F. Access isolation: resolve_export_authority scopes to user_id via workspace
     read; returns FACTORY_REFERENCE authority when project_record is None.
  G. No financial execution: build_institutional_workbook_export does not call
     run_project() or run_clean_production(); pure export, zero engine runs.

No DB writes.  No engine execution.  All factories use public reference fixtures.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# A. No-run state — fail-closed
# ---------------------------------------------------------------------------


def test_canonical_raises_when_no_run_committed():
    """_resolve_canonical_last_run_path raises ValueError when no run exists."""
    from app.services.export_service import _resolve_canonical_last_run_path

    fake_project_record = SimpleNamespace(project_id="proj-001", project_origin="user_created")
    fake_ws = SimpleNamespace(
        any_run_committed=False,
        last_runtime_snapshot=None,
        last_runtime_snapshot_id=None,
        last_runtime_scenario_id=None,
        last_runtime_identity=None,
        dirty=False,
        draft_snapshot={},
    )

    with pytest.raises(ValueError, match="CANONICAL_LAST_RUN_UNAVAILABLE"):
        _resolve_canonical_last_run_path(fake_project_record, "user-abc", fake_ws)


def test_build_institutional_workbook_export_no_run_returns_400():
    """build_institutional_workbook_export returns a 400 error response (not bytes)
    when no run has been committed and the workspace raises CANONICAL_LAST_RUN_UNAVAILABLE."""
    from app.services.export_service import build_institutional_workbook_export

    fake_record = SimpleNamespace(
        project_id="proj-001",
        project_origin="user_created",
        project_code="test_proj",
        project_type="Wind",
        template_source="generic_wind",
    )

    with patch(
        "app.services.export_service.resolve_export_authority",
        side_effect=ValueError("CANONICAL_LAST_RUN_UNAVAILABLE: no committed run exists"),
    ):
        export = build_institutional_workbook_export(
            "generic_wind",
            safe_project="test_proj",
            project_record=fake_record,
            user_id="user-abc",
        )

    assert export.status_code == 400
    assert export.bytes_data is None
    assert export.has_error()
    assert "CANONICAL_LAST_RUN_UNAVAILABLE" in (export.error_content or "")


# ---------------------------------------------------------------------------
# B. Canonical export — factory path produces bytes (zero DB, zero engine)
# ---------------------------------------------------------------------------


def test_build_institutional_workbook_export_factory_path_returns_bytes():
    """Factory-path export (project_record=None) returns bytes with xlsx media type."""
    from app.services.export_service import build_institutional_workbook_export

    export = build_institutional_workbook_export(
        "generic_wind_reference",
        safe_project="generic_wind_reference",
        project_record=None,
        user_id=None,
    )

    assert export.status_code == 200
    assert export.bytes_data is not None
    assert len(export.bytes_data) > 0
    assert export.media_type == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    assert export.filename is not None
    assert "institutional_workbook_skeleton" in export.filename
    assert not export.has_error()


def test_factory_export_metadata_authority_mode():
    """Factory-path export metadata carries FACTORY_REFERENCE authority."""
    from app.services.export_service import build_institutional_workbook_export

    export = build_institutional_workbook_export(
        "generic_solar_reference",
        safe_project="generic_solar_reference",
        project_record=None,
        user_id=None,
    )

    assert export.status_code == 200
    assert export.metadata.get("export_authority") == "FACTORY_REFERENCE"


# ---------------------------------------------------------------------------
# C. Working-changed flag
# ---------------------------------------------------------------------------


def test_export_metadata_working_changed_true():
    """working_changed_since_run=True is encoded as 'true' in export metadata."""
    from app.services.export_service import (
        ExportResponse,
        EXPORT_AUTHORITY_CANONICAL_LAST_RUN,
        ResolvedExportAuthority,
        build_institutional_workbook_export,
    )
    from app.project_factories import create_generic_wind_reference

    fake_pi = create_generic_wind_reference()

    mock_authority = ResolvedExportAuthority(
        project_inputs=fake_pi,
        current_snapshot={},
        runtime_origin="saved_state",
        active_scenario_id="sc-001",
        active_scenario_name="Base Case",
        last_runtime_scenario_id="sc-001",
        any_run_committed=True,
        authority_mode=EXPORT_AUTHORITY_CANONICAL_LAST_RUN,
        run_id=None,
        run_at="2026-01-01T00:00:00+00:00",
        working_changed_since_run=True,
    )

    fake_record = SimpleNamespace(
        project_id="proj-001",
        project_origin="user_created",
        project_code="test_proj",
        project_type="Wind",
        template_source="generic_wind",
    )

    with patch(
        "app.services.export_service.resolve_export_authority",
        return_value=mock_authority,
    ):
        export = build_institutional_workbook_export(
            "generic_wind",
            safe_project="test_proj",
            project_record=fake_record,
            user_id="user-abc",
        )

    assert export.status_code == 200
    assert export.metadata.get("export_working_changed_since_run") == "true"


def test_export_metadata_working_changed_false():
    """working_changed_since_run=False is encoded as 'false' in export metadata."""
    from app.services.export_service import (
        EXPORT_AUTHORITY_CANONICAL_LAST_RUN,
        ResolvedExportAuthority,
        build_institutional_workbook_export,
    )
    from app.project_factories import create_generic_wind_reference

    fake_pi = create_generic_wind_reference()

    mock_authority = ResolvedExportAuthority(
        project_inputs=fake_pi,
        current_snapshot={},
        runtime_origin="saved_state",
        active_scenario_id="sc-001",
        active_scenario_name="Base Case",
        last_runtime_scenario_id="sc-001",
        any_run_committed=True,
        authority_mode=EXPORT_AUTHORITY_CANONICAL_LAST_RUN,
        run_id=None,
        run_at="2026-01-01T00:00:00+00:00",
        working_changed_since_run=False,
    )

    fake_record = SimpleNamespace(
        project_id="proj-001",
        project_origin="user_created",
        project_code="test_proj",
        project_type="Wind",
        template_source="generic_wind",
    )

    with patch(
        "app.services.export_service.resolve_export_authority",
        return_value=mock_authority,
    ):
        export = build_institutional_workbook_export(
            "generic_wind",
            safe_project="test_proj",
            project_record=fake_record,
            user_id="user-abc",
        )

    assert export.status_code == 200
    assert export.metadata.get("export_working_changed_since_run") == "false"


# ---------------------------------------------------------------------------
# D. Scenario lineage in export metadata
# ---------------------------------------------------------------------------


def test_export_metadata_carries_scenario_lineage():
    """Export metadata includes scenario name and last-run scenario id for lineage."""
    from app.services.export_service import (
        EXPORT_AUTHORITY_CANONICAL_LAST_RUN,
        ResolvedExportAuthority,
        build_institutional_workbook_export,
    )
    from app.project_factories import create_generic_wind_reference

    fake_pi = create_generic_wind_reference()

    mock_authority = ResolvedExportAuthority(
        project_inputs=fake_pi,
        current_snapshot={},
        runtime_origin="saved_state",
        active_scenario_id="sc-scenario-x",
        active_scenario_name="High Wind",
        last_runtime_scenario_id="sc-scenario-y",
        any_run_committed=True,
        authority_mode=EXPORT_AUTHORITY_CANONICAL_LAST_RUN,
        run_id=None,
        run_at="2026-06-01T00:00:00+00:00",
        working_changed_since_run=False,
    )

    fake_record = SimpleNamespace(
        project_id="proj-002",
        project_origin="user_created",
        project_code="test_proj2",
        project_type="Wind",
        template_source="generic_wind",
    )

    with patch(
        "app.services.export_service.resolve_export_authority",
        return_value=mock_authority,
    ):
        export = build_institutional_workbook_export(
            "generic_wind",
            safe_project="test_proj2",
            project_record=fake_record,
            user_id="user-def",
        )

    assert export.status_code == 200
    assert export.metadata.get("export_active_scenario_name") == "High Wind"
    assert export.metadata.get("export_last_runtime_scenario_id") == "sc-scenario-y"
    assert export.metadata.get("export_authority") == EXPORT_AUTHORITY_CANONICAL_LAST_RUN


# ---------------------------------------------------------------------------
# E. Authority identity — CANONICAL_LAST_RUN or FACTORY_REFERENCE, never PREVIEW
# ---------------------------------------------------------------------------


def test_resolve_export_authority_default_mode_is_canonical():
    """resolve_export_authority's default authority_mode is CANONICAL_LAST_RUN."""
    import inspect
    from app.services.export_service import (
        resolve_export_authority,
        EXPORT_AUTHORITY_CANONICAL_LAST_RUN,
    )

    sig = inspect.signature(resolve_export_authority)
    default = sig.parameters["authority_mode"].default
    assert default == EXPORT_AUTHORITY_CANONICAL_LAST_RUN


def test_resolve_export_authority_factory_project_returns_factory_reference():
    """Factory/reference projects always get FACTORY_REFERENCE regardless of mode."""
    from app.services.export_service import (
        resolve_export_authority,
        EXPORT_AUTHORITY_CANONICAL_LAST_RUN,
        EXPORT_AUTHORITY_FACTORY_REFERENCE,
    )

    fake_record = SimpleNamespace(
        project_id="proj-ref",
        project_origin="factory_template",
    )
    authority = resolve_export_authority(
        fake_record,
        "user-xyz",
        authority_mode=EXPORT_AUTHORITY_CANONICAL_LAST_RUN,
    )
    assert authority.authority_mode == EXPORT_AUTHORITY_FACTORY_REFERENCE


def test_resolve_export_authority_none_project_returns_factory_reference():
    """project_record=None always yields FACTORY_REFERENCE (factory path)."""
    from app.services.export_service import (
        resolve_export_authority,
        EXPORT_AUTHORITY_FACTORY_REFERENCE,
    )

    authority = resolve_export_authority(None, "user-xyz")
    assert authority.authority_mode == EXPORT_AUTHORITY_FACTORY_REFERENCE
    assert authority.project_inputs is None


# ---------------------------------------------------------------------------
# F. Access isolation — workspace read is user-scoped
# ---------------------------------------------------------------------------


def test_resolve_export_authority_user_id_none_returns_factory_reference():
    """user_id=None triggers factory path — no workspace read attempted."""
    from app.services.export_service import (
        resolve_export_authority,
        EXPORT_AUTHORITY_FACTORY_REFERENCE,
    )

    fake_record = SimpleNamespace(
        project_id="proj-001",
        project_origin="user_created",
    )
    authority = resolve_export_authority(fake_record, user_id=None)
    assert authority.authority_mode == EXPORT_AUTHORITY_FACTORY_REFERENCE


def test_export_route_access_isolation_uses_workspace_owner():
    """The V2 export route calls resolve_accessible_project, scoping the workspace
    to the authenticated user's accessible projects only."""
    from app.v2 import router as v2_router
    import inspect

    src = inspect.getsource(v2_router.v2_workbook_export)
    assert "resolve_accessible_project" in src
    assert "workspace_owner" in src


# ---------------------------------------------------------------------------
# G. No financial execution
# ---------------------------------------------------------------------------


def test_no_run_project_call_in_export_service():
    """build_institutional_workbook_export must not call run_project or
    run_clean_production — zero engine execution guarantee."""
    import inspect
    from app.services import export_service

    src = inspect.getsource(export_service.build_institutional_workbook_export)
    assert "run_project" not in src
    assert "run_clean_production" not in src


def test_v2_export_route_no_engine_call():
    """The V2 export route handler itself must not call run_project or
    run_clean_production."""
    from app.v2 import router as v2_router
    import inspect

    src = inspect.getsource(v2_router.v2_workbook_export)
    assert "run_project" not in src
    assert "run_clean_production" not in src


def test_export_response_is_streaming_or_html_error():
    """_make_streaming_response returns StreamingResponse on success
    and HTMLResponse on error — never raises."""
    from fastapi.responses import HTMLResponse, StreamingResponse
    from app.services.export_service import ExportResponse, _make_streaming_response

    success = ExportResponse(
        bytes_data=b"PKfake",
        filename="test.xlsx",
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        status_code=200,
    )
    resp_ok = _make_streaming_response(success)
    assert isinstance(resp_ok, StreamingResponse)

    error = ExportResponse(
        status_code=400,
        error_content="<html><body>error</body></html>",
    )
    resp_err = _make_streaming_response(error)
    assert isinstance(resp_err, HTMLResponse)
    assert resp_err.status_code == 400
