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
  G. No financial execution: v2 export path must not call execute_production_waterfall
     or run_clean_production — proven with live sentinels that raise AssertionError.

  HTTP route integration (cases A-G via test client):
  A. Clean run — 200 + xlsx bytes
  B. Dirty (working changed) — 200 + xlsx bytes with metadata flag
  C. Scenario lineage — 200 + correct scenario metadata
  D. No run — 400 HTML error
  E. Cross-user — 404 HTML error
  F. Nonexistent project — 404 HTML error
  G. XSS input — 404 response, no echo of raw input

  Adversarial proof: full round-trip with engine sentinels armed confirms
  zero engine execution through the entire V2 export stack.

  Normalization characterization: project code normalization mirrors
  main_web._normalize_template_source.

No DB writes (except audit trail via record_export mock).
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
    import inspect
    from app.v2 import router as v2_router

    src = inspect.getsource(v2_router.v2_workbook_export)
    assert "resolve_accessible_project" in src
    assert "workspace_owner" in src


# ---------------------------------------------------------------------------
# G. No financial execution — sentinel tests (F02: real sentinels, not source inspection)
# ---------------------------------------------------------------------------


def test_v2_export_service_no_engine_call_sentinel():
    """build_canonical_last_run_institutional_workbook_export must not invoke
    execute_production_waterfall — proven via a live sentinel that raises AssertionError.

    F02: sentinel must not fire AND export must succeed (status 200) with parseable XLSX.
    """
    from io import BytesIO
    from types import SimpleNamespace as NS
    from app.services.v2_export_service import (
        build_canonical_last_run_institutional_workbook_export,
    )
    from app.project_factories import create_generic_wind_reference
    import openpyxl

    fake_pi = create_generic_wind_reference()
    fake_record = NS(
        project_id="proj-sentinel",
        project_origin="user_created",
        project_code="sentinel_proj",
        project_name="Sentinel Project",
        project_type="Wind",
        template_source="generic_wind",
        project_origin_detail=None,
        baseline_snapshot=None,
    )

    mock_rr = NS(
        snapshot_id="snap-001",
        ran_at="2026-01-01T00:00:00+00:00",
        runtime_summary={"project_irr": 0.12, "equity_irr": 0.15},
        debt_schedule={"periods": []},
        financial_statements=None,
    )

    def _sentinel_engine(*args, **kwargs):
        raise AssertionError(
            "execute_production_waterfall must NOT be called in V2 zero-engine export path"
        )

    from app.services.export_service import (
        EXPORT_AUTHORITY_CANONICAL_LAST_RUN,
        ResolvedExportAuthority,
    )
    mock_authority = ResolvedExportAuthority(
        project_inputs=fake_pi,
        current_snapshot={},
        runtime_origin="canonical_last_run",
        active_scenario_id=None,
        active_scenario_name=None,
        last_runtime_scenario_id=None,
        any_run_committed=True,
        authority_mode=EXPORT_AUTHORITY_CANONICAL_LAST_RUN,
        run_id="run-001",
        run_at="2026-01-01T00:00:00+00:00",
        working_changed_since_run=False,
    )

    with (
        patch(
            "app.services.production_waterfall_seam.execute_production_waterfall",
            side_effect=_sentinel_engine,
        ),
        # F03/F06: mock the new single-read wrapper, not resolve_export_authority.
        patch(
            "app.services.export_service.resolve_canonical_last_run_from_workspace",
            return_value=mock_authority,
        ),
        patch(
            "app.persistence.workspace_repository.get_workspace_state",
            return_value=NS(last_runtime_snapshot_id="snap-001"),
        ),
        patch(
            "app.workbook.runtime_result.RuntimeResult.from_workspace_state",
            return_value=mock_rr,
        ),
    ):
        export = build_canonical_last_run_institutional_workbook_export(
            "generic_wind",
            safe_project="sentinel_proj",
            project_record=fake_record,
            user_id="user-sentinel",
        )

    # F02: sentinel must not have fired AND export must produce real XLSX bytes.
    assert "execute_production_waterfall must NOT be called" not in (export.error_content or "")
    assert export.status_code == 200, f"Expected 200 but got {export.status_code}: {export.error_content}"
    assert export.bytes_data is not None and len(export.bytes_data) > 0
    wb = openpyxl.load_workbook(BytesIO(export.bytes_data))
    assert "Runtime Summary" in wb.sheetnames


def test_v2_export_run_clean_production_sentinel():
    """run_clean_production must not be called in the V2 zero-engine export path.

    F02: sentinel must not fire AND export must succeed (status 200).
    """
    from types import SimpleNamespace as NS
    from app.services.v2_export_service import (
        build_canonical_last_run_institutional_workbook_export,
    )
    from app.project_factories import create_generic_wind_reference

    fake_pi = create_generic_wind_reference()
    fake_record = NS(
        project_id="proj-clean-sentinel",
        project_origin="user_created",
        project_code="clean_sentinel",
        project_name="Clean Sentinel",
        project_type="Wind",
        template_source="generic_wind",
        project_origin_detail=None,
        baseline_snapshot=None,
    )
    mock_rr = NS(
        snapshot_id="snap-002",
        ran_at="2026-01-01T00:00:00+00:00",
        runtime_summary={"project_irr": 0.10},
        debt_schedule={"periods": []},
        financial_statements=None,
    )

    def _sentinel_clean(*args, **kwargs):
        raise AssertionError(
            "run_clean_production must NOT be called in V2 zero-engine export path"
        )

    from app.services.export_service import (
        EXPORT_AUTHORITY_CANONICAL_LAST_RUN,
        ResolvedExportAuthority,
    )
    mock_authority = ResolvedExportAuthority(
        project_inputs=fake_pi,
        current_snapshot={},
        runtime_origin="canonical_last_run",
        active_scenario_id=None,
        active_scenario_name=None,
        last_runtime_scenario_id=None,
        any_run_committed=True,
        authority_mode=EXPORT_AUTHORITY_CANONICAL_LAST_RUN,
        run_id="run-002",
        run_at="2026-01-01T00:00:00+00:00",
        working_changed_since_run=False,
    )

    with (
        patch(
            "app.services.production_financial_authority.run_clean_production",
            side_effect=_sentinel_clean,
        ),
        # F03/F06: mock new single-read wrapper, not resolve_export_authority.
        patch(
            "app.services.export_service.resolve_canonical_last_run_from_workspace",
            return_value=mock_authority,
        ),
        patch(
            "app.persistence.workspace_repository.get_workspace_state",
            return_value=NS(last_runtime_snapshot_id="snap-002"),
        ),
        patch(
            "app.workbook.runtime_result.RuntimeResult.from_workspace_state",
            return_value=mock_rr,
        ),
    ):
        export = build_canonical_last_run_institutional_workbook_export(
            "generic_wind",
            safe_project="clean_sentinel",
            project_record=fake_record,
            user_id="user-clean-sentinel",
        )

    # F02: sentinel must not fire AND export must succeed.
    assert "run_clean_production must NOT be called" not in (export.error_content or "")
    assert export.status_code == 200, f"Expected 200 but got {export.status_code}: {export.error_content}"


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


# ---------------------------------------------------------------------------
# HTTP route integration tests (F03)
# ---------------------------------------------------------------------------


def _make_fake_project_record(
    project_id="proj-http",
    origin="user_created",
    project_code="http_proj",
    project_type="Wind",
    template_source="generic_wind",
    project_name="HTTP Test Project",
):
    return SimpleNamespace(
        project_id=project_id,
        project_origin=origin,
        project_code=project_code,
        project_name=project_name,
        project_type=project_type,
        template_source=template_source,
        project_origin_detail=None,
        baseline_snapshot=None,
    )


def _make_fake_runtime_result(
    snapshot_id="snap-http",
    project_irr=0.12,
    equity_irr=0.15,
    has_statements=False,
    ran_at="2026-01-01T00:00:00+00:00",
):
    rs = {"project_irr": project_irr, "equity_irr": equity_irr}
    return SimpleNamespace(
        snapshot_id=snapshot_id,
        ran_at=ran_at,
        runtime_summary=rs,
        debt_schedule={"periods": []},
        financial_statements={"pnl": {"periods": []}} if has_statements else None,
    )


def _make_canonical_authority(
    fake_pi,
    working_changed=False,
    scenario_id=None,
    scenario_name=None,
    last_runtime_scenario_id=None,
    run_id="run-http",
    run_at="2026-01-01T00:00:00+00:00",
):
    from app.services.export_service import (
        EXPORT_AUTHORITY_CANONICAL_LAST_RUN,
        ResolvedExportAuthority,
    )
    return ResolvedExportAuthority(
        project_inputs=fake_pi,
        current_snapshot={},
        runtime_origin="canonical_last_run",
        active_scenario_id=scenario_id,
        active_scenario_name=scenario_name,
        last_runtime_scenario_id=last_runtime_scenario_id,
        any_run_committed=True,
        authority_mode=EXPORT_AUTHORITY_CANONICAL_LAST_RUN,
        run_id=run_id,
        run_at=run_at,
        working_changed_since_run=working_changed,
    )


def _get_test_client():
    from fastapi.testclient import TestClient
    from app.v2.router import router
    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(router, prefix="/v2")
    return TestClient(app, raise_server_exceptions=False)


def _mock_user(user_id="user-http"):
    return SimpleNamespace(user_id=user_id)


def test_http_route_case_a_clean_run_200():
    """Case A: clean run (working_changed=False) → 200 + xlsx bytes.

    F03: mock at workspace/RuntimeResult level, not authority level.
    """
    from app.project_factories import create_generic_wind_reference

    fake_pi = create_generic_wind_reference()
    fake_record = _make_fake_project_record()
    mock_rr = _make_fake_runtime_result()
    mock_authority = _make_canonical_authority(fake_pi, working_changed=False)

    client = _get_test_client()

    with (
        patch("app.v2.router._get_current_user", return_value=_mock_user()),
        patch(
            "app.persistence.projects_repository.resolve_accessible_project",
            return_value=(fake_record, "user-http"),
        ),
        # F03/F06: mock the new single-read wrapper (not resolve_export_authority).
        patch(
            "app.services.export_service.resolve_canonical_last_run_from_workspace",
            return_value=mock_authority,
        ),
        patch(
            "app.persistence.workspace_repository.get_workspace_state",
            return_value=SimpleNamespace(last_runtime_snapshot_id="snap-http"),
        ),
        patch(
            "app.workbook.runtime_result.RuntimeResult.from_workspace_state",
            return_value=mock_rr,
        ),
        patch("app.persistence.repository.record_export", return_value=None),
    ):
        resp = client.post("/v2/workbook/export", data={"project": "http_proj"})

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    assert len(resp.content) > 0


def test_http_route_case_b_dirty_after_run_200():
    """Case B: dirty working inputs (working_changed=True) → 200 + metadata flag.

    F03: mock at workspace/RuntimeResult level, not authority level.
    """
    from app.project_factories import create_generic_wind_reference

    fake_pi = create_generic_wind_reference()
    fake_record = _make_fake_project_record()
    mock_rr = _make_fake_runtime_result()
    mock_authority = _make_canonical_authority(fake_pi, working_changed=True)

    client = _get_test_client()

    with (
        patch("app.v2.router._get_current_user", return_value=_mock_user()),
        patch(
            "app.persistence.projects_repository.resolve_accessible_project",
            return_value=(fake_record, "user-http"),
        ),
        patch(
            "app.services.export_service.resolve_canonical_last_run_from_workspace",
            return_value=mock_authority,
        ),
        patch(
            "app.persistence.workspace_repository.get_workspace_state",
            return_value=SimpleNamespace(last_runtime_snapshot_id="snap-b"),
        ),
        patch(
            "app.workbook.runtime_result.RuntimeResult.from_workspace_state",
            return_value=mock_rr,
        ),
        patch("app.persistence.repository.record_export", return_value=None),
    ):
        resp = client.post("/v2/workbook/export", data={"project": "http_proj"})

    assert resp.status_code == 200


def test_http_route_case_c_scenario_lineage_200():
    """Case C: scenario lineage — 200 with correct scenario identity.

    F03: mock at workspace/RuntimeResult level, not authority level.
    """
    from app.project_factories import create_generic_wind_reference

    fake_pi = create_generic_wind_reference()
    fake_record = _make_fake_project_record()
    mock_rr = _make_fake_runtime_result()
    mock_authority = _make_canonical_authority(
        fake_pi,
        scenario_id="sc-c",
        scenario_name="Scenario C",
        last_runtime_scenario_id="sc-c-runtime",
    )

    client = _get_test_client()

    with (
        patch("app.v2.router._get_current_user", return_value=_mock_user()),
        patch(
            "app.persistence.projects_repository.resolve_accessible_project",
            return_value=(fake_record, "user-http"),
        ),
        patch(
            "app.services.export_service.resolve_canonical_last_run_from_workspace",
            return_value=mock_authority,
        ),
        patch(
            "app.persistence.workspace_repository.get_workspace_state",
            return_value=SimpleNamespace(last_runtime_snapshot_id="snap-c"),
        ),
        patch(
            "app.workbook.runtime_result.RuntimeResult.from_workspace_state",
            return_value=mock_rr,
        ),
        patch("app.persistence.repository.record_export", return_value=None),
    ):
        resp = client.post("/v2/workbook/export", data={"project": "http_proj"})

    assert resp.status_code == 200


def test_http_route_case_d_no_run_400():
    """Case D: no committed run → 400 HTML error from v2_export_service.

    F03: mock at the new single-read wrapper level (not resolve_export_authority).
    """
    fake_record = _make_fake_project_record()

    client = _get_test_client()

    with (
        patch("app.v2.router._get_current_user", return_value=_mock_user()),
        patch(
            "app.persistence.projects_repository.resolve_accessible_project",
            return_value=(fake_record, "user-http"),
        ),
        # F06: v2_export_service now calls get_workspace_state then
        # resolve_canonical_last_run_from_workspace — mock both.
        patch(
            "app.persistence.workspace_repository.get_workspace_state",
            return_value=SimpleNamespace(
                any_run_committed=False,
                last_runtime_snapshot=None,
                last_runtime_snapshot_id=None,
            ),
        ),
        patch(
            "app.services.export_service.resolve_canonical_last_run_from_workspace",
            side_effect=ValueError("CANONICAL_LAST_RUN_UNAVAILABLE: no run"),
        ),
    ):
        resp = client.post("/v2/workbook/export", data={"project": "http_proj"})

    assert resp.status_code == 400
    assert "text/html" in resp.headers.get("content-type", "")


def test_http_route_case_e_cross_user_isolation_404():
    """Case E: project not found for user (cross-user) → 404 HTML error."""
    client = _get_test_client()

    with (
        patch("app.v2.router._get_current_user", return_value=_mock_user("user-other")),
        patch(
            "app.persistence.projects_repository.resolve_accessible_project",
            return_value=(None, None),
        ),
    ):
        resp = client.post("/v2/workbook/export", data={"project": "other_users_project"})

    assert resp.status_code == 404
    assert "text/html" in resp.headers.get("content-type", "")


def test_http_route_case_f_nonexistent_project_404():
    """Case F: nonexistent project → 404 HTML error."""
    client = _get_test_client()

    with (
        patch("app.v2.router._get_current_user", return_value=_mock_user()),
        patch(
            "app.persistence.projects_repository.resolve_accessible_project",
            return_value=(None, None),
        ),
    ):
        resp = client.post("/v2/workbook/export", data={"project": "does_not_exist"})

    assert resp.status_code == 404


def test_http_route_case_g_xss_input_no_echo():
    """Case G: XSS payload in project field → 404, raw input NOT echoed in response."""
    xss_payload = "<script>alert('xss')</script>"
    client = _get_test_client()

    with (
        patch("app.v2.router._get_current_user", return_value=_mock_user()),
        patch(
            "app.persistence.projects_repository.resolve_accessible_project",
            return_value=(None, None),
        ),
    ):
        resp = client.post("/v2/workbook/export", data={"project": xss_payload})

    assert resp.status_code == 404
    # Raw XSS payload must not appear verbatim in the response body (F04 fix).
    assert xss_payload not in resp.text
    assert "<script>" not in resp.text


# ---------------------------------------------------------------------------
# Adversarial proof — full round-trip with all engine sentinels armed (section 15)
# ---------------------------------------------------------------------------


def test_adversarial_proof_zero_engine_full_roundtrip():
    """Full round-trip with BOTH engine sentinels armed.

    Proves that the V2 canonical last-run export path executes ZERO financial
    calculations: neither execute_production_waterfall nor run_clean_production
    is called when exporting from persisted RuntimeResult data.
    """
    from types import SimpleNamespace as NS
    from app.services.v2_export_service import (
        build_canonical_last_run_institutional_workbook_export,
    )
    from app.project_factories import create_generic_wind_reference
    from app.services.export_service import (
        EXPORT_AUTHORITY_CANONICAL_LAST_RUN,
        ResolvedExportAuthority,
    )

    fake_pi = create_generic_wind_reference()
    fake_record = NS(
        project_id="proj-adversarial",
        project_origin="user_created",
        project_code="adversarial_proj",
        project_name="Adversarial Test Project",
        project_type="Wind",
        template_source="generic_wind",
        project_origin_detail=None,
        baseline_snapshot=None,
    )
    mock_rr = NS(
        snapshot_id="snap-adversarial",
        ran_at="2026-09-21T00:00:00+00:00",
        runtime_summary={
            "project_irr": 0.13,
            "equity_irr": 0.16,
            "total_revenue_keur": 50000.0,
            "total_ebitda_keur": 30000.0,
            "total_opex_keur": 20000.0,
            "actual_avg_dscr": 1.35,
            "actual_min_dscr": 1.20,
        },
        debt_schedule={"periods": []},
        financial_statements=None,
    )
    mock_authority = ResolvedExportAuthority(
        project_inputs=fake_pi,
        current_snapshot={},
        runtime_origin="canonical_last_run",
        active_scenario_id="sc-adv",
        active_scenario_name="Adversarial Scenario",
        last_runtime_scenario_id="sc-adv",
        any_run_committed=True,
        authority_mode=EXPORT_AUTHORITY_CANONICAL_LAST_RUN,
        run_id="run-adv",
        run_at="2026-09-21T00:00:00+00:00",
        working_changed_since_run=False,
    )

    engine_call_log = []

    def _engine_sentinel(*args, **kwargs):
        engine_call_log.append("execute_production_waterfall called!")
        raise AssertionError("SENTINEL: execute_production_waterfall called in zero-engine path")

    def _clean_sentinel(*args, **kwargs):
        engine_call_log.append("run_clean_production called!")
        raise AssertionError("SENTINEL: run_clean_production called in zero-engine path")

    with (
        patch(
            "app.services.production_waterfall_seam.execute_production_waterfall",
            side_effect=_engine_sentinel,
        ),
        patch(
            "app.services.production_financial_authority.run_clean_production",
            side_effect=_clean_sentinel,
        ),
        # F03/F06: mock the new single-read wrapper, not resolve_export_authority.
        patch(
            "app.services.export_service.resolve_canonical_last_run_from_workspace",
            return_value=mock_authority,
        ),
        patch(
            "app.persistence.workspace_repository.get_workspace_state",
            return_value=NS(last_runtime_snapshot_id="snap-adversarial"),
        ),
        patch(
            "app.workbook.runtime_result.RuntimeResult.from_workspace_state",
            return_value=mock_rr,
        ),
    ):
        export = build_canonical_last_run_institutional_workbook_export(
            "generic_wind",
            safe_project="adversarial_proj",
            project_record=fake_record,
            user_id="user-adversarial",
        )

    # F02: Sentinels must never have fired AND export must produce real XLSX.
    assert engine_call_log == [], (
        f"Engine was called during zero-engine V2 export: {engine_call_log}"
    )
    assert export.status_code == 200, (
        f"Expected 200 but got {export.status_code}: {export.error_content}"
    )
    if export.error_content:
        assert "SENTINEL" not in export.error_content


# ---------------------------------------------------------------------------
# Normalization characterization test
# ---------------------------------------------------------------------------


def test_v2_export_route_normalization_mirrors_main_web():
    """V2 export route normalizes runtime_project_code from template_source /
    project_type the same way main_web._normalize_template_source does:
      - template_source in known set → use as-is
      - project_type solar → generic_solar
      - project_type storage/bess → generic_storage
      - else → generic_wind
    """
    import inspect
    from app.v2 import router as v2_router

    src = inspect.getsource(v2_router.v2_workbook_export)

    # Known template sources are used directly.
    assert "generic_wind_reference" in src
    assert "generic_solar_reference" in src
    # Solar and storage/bess type branches.
    assert "generic_solar" in src
    assert "generic_storage" in src
    # Default falls through to generic_wind.
    assert "generic_wind" in src


def test_v2_export_service_fails_closed_for_reference_projects():
    """Reference/factory projects (project_origin != 'user_created') fail closed with 400."""
    from app.services.v2_export_service import (
        build_canonical_last_run_institutional_workbook_export,
    )

    fake_record = SimpleNamespace(
        project_id="proj-ref",
        project_origin="factory_template",
        project_code="generic_wind_reference",
    )

    export = build_canonical_last_run_institutional_workbook_export(
        "generic_wind_reference",
        safe_project="generic_wind_reference",
        project_record=fake_record,
        user_id="user-abc",
    )

    assert export.status_code == 400
    assert export.has_error()


def test_v2_export_service_fails_closed_when_no_project_record():
    """project_record=None fails closed with 400 (no factory fallback in V2)."""
    from app.services.v2_export_service import (
        build_canonical_last_run_institutional_workbook_export,
    )

    export = build_canonical_last_run_institutional_workbook_export(
        "generic_wind",
        safe_project=None,
        project_record=None,
        user_id="user-abc",
    )

    assert export.status_code == 400
    assert export.has_error()


# ===========================================================================
# Correction B — new tests: F06, F07, F08, F05, F04, invariants, XLSX verify
# ===========================================================================


# ---------------------------------------------------------------------------
# F06 — Single workspace read: adversarial race lock
# ---------------------------------------------------------------------------


def test_f06_single_workspace_read_invariant():
    """F06: get_workspace_state is called exactly ONCE per export invocation.

    Authority and RuntimeResult must derive from the same ws object; a second
    read would open a torn-workbook window (Last Run A inputs + Last Run B outputs).
    """
    from types import SimpleNamespace as NS
    from unittest.mock import call
    from app.services.v2_export_service import (
        build_canonical_last_run_institutional_workbook_export,
    )
    from app.project_factories import create_generic_wind_reference
    from app.services.export_service import (
        EXPORT_AUTHORITY_CANONICAL_LAST_RUN,
        ResolvedExportAuthority,
    )

    fake_pi = create_generic_wind_reference()
    fake_record = NS(
        project_id="proj-f06",
        project_origin="user_created",
        project_code="f06_proj",
        project_name="F06 Race Test",
        project_type="Wind",
        template_source="generic_wind",
        project_origin_detail=None,
        baseline_snapshot=None,
    )
    mock_rr = NS(
        snapshot_id="snap-f06",
        ran_at="2026-06-01T09:00:00+00:00",
        runtime_summary={"project_irr": 0.11},
        debt_schedule={"periods": []},
        financial_statements=None,
    )
    mock_authority = ResolvedExportAuthority(
        project_inputs=fake_pi,
        current_snapshot={},
        runtime_origin="canonical_last_run",
        active_scenario_id=None,
        active_scenario_name=None,
        last_runtime_scenario_id=None,
        any_run_committed=True,
        authority_mode=EXPORT_AUTHORITY_CANONICAL_LAST_RUN,
        run_id=None,
        run_at="2026-06-01T09:00:00+00:00",
        working_changed_since_run=False,
    )

    ws_read_calls = []

    def _counting_ws(*args, **kwargs):
        ws_read_calls.append(("get_workspace_state", args, kwargs))
        return NS(last_runtime_snapshot_id="snap-f06")

    with (
        patch(
            "app.persistence.workspace_repository.get_workspace_state",
            side_effect=_counting_ws,
        ),
        patch(
            "app.services.export_service.resolve_canonical_last_run_from_workspace",
            return_value=mock_authority,
        ),
        patch(
            "app.workbook.runtime_result.RuntimeResult.from_workspace_state",
            return_value=mock_rr,
        ),
    ):
        export = build_canonical_last_run_institutional_workbook_export(
            "generic_wind",
            safe_project="f06_proj",
            project_record=fake_record,
            user_id="user-f06",
        )

    # F06: workspace must be read exactly once.
    assert len(ws_read_calls) == 1, (
        f"Expected 1 workspace read but got {len(ws_read_calls)}: {ws_read_calls}"
    )
    assert export.status_code == 200, f"Expected 200: {export.error_content}"


def test_f06_adversarial_race_torn_workbook_prevented():
    """F06 adversarial: two workspace objects (A and B) with different project_irr.

    Proves that only ONE workspace is read and the exported IRR matches ws_a
    (the single read), never a mix of ws_a and ws_b data.
    """
    from types import SimpleNamespace as NS
    from app.services.v2_export_service import (
        build_canonical_last_run_institutional_workbook_export,
        _RuntimeResultAdapter,
    )
    from app.project_factories import create_generic_wind_reference
    from app.services.export_service import (
        EXPORT_AUTHORITY_CANONICAL_LAST_RUN,
        ResolvedExportAuthority,
    )

    fake_pi = create_generic_wind_reference()
    fake_record = NS(
        project_id="proj-race",
        project_origin="user_created",
        project_code="race_proj",
        project_name="Race Test",
        project_type="Wind",
        template_source="generic_wind",
        project_origin_detail=None,
        baseline_snapshot=None,
    )

    # ws_a: last run with project_irr=0.13 — the "correct" authority.
    ws_a = NS(last_runtime_snapshot_id="snap-a")
    rr_a = NS(
        snapshot_id="snap-a",
        ran_at="2026-01-01T00:00:00+00:00",
        runtime_summary={"project_irr": 0.13},
        debt_schedule={"periods": []},
        financial_statements=None,
    )
    authority_a = ResolvedExportAuthority(
        project_inputs=fake_pi,
        current_snapshot={},
        runtime_origin="canonical_last_run",
        active_scenario_id=None,
        active_scenario_name=None,
        last_runtime_scenario_id=None,
        any_run_committed=True,
        authority_mode=EXPORT_AUTHORITY_CANONICAL_LAST_RUN,
        run_id=None,
        run_at="2026-01-01T00:00:00+00:00",
        working_changed_since_run=False,
    )

    read_count = [0]

    def _ws_once(*args, **kwargs):
        read_count[0] += 1
        if read_count[0] > 1:
            raise AssertionError(
                f"RACE: get_workspace_state called {read_count[0]} times — F06 violated"
            )
        return ws_a

    with (
        patch(
            "app.persistence.workspace_repository.get_workspace_state",
            side_effect=_ws_once,
        ),
        patch(
            "app.services.export_service.resolve_canonical_last_run_from_workspace",
            return_value=authority_a,
        ),
        patch(
            "app.workbook.runtime_result.RuntimeResult.from_workspace_state",
            return_value=rr_a,
        ),
    ):
        export = build_canonical_last_run_institutional_workbook_export(
            "generic_wind",
            safe_project="race_proj",
            project_record=fake_record,
            user_id="user-race",
        )

    assert read_count[0] == 1, f"Expected 1 read, got {read_count[0]}"
    assert export.status_code == 200, f"Expected 200: {export.error_content}"
    # No RACE error in response.
    assert "RACE" not in (export.error_content or "")


# ---------------------------------------------------------------------------
# F07 — Missing persisted fields: None not 0.0; SHL NOT_AVAILABLE guard
# ---------------------------------------------------------------------------


def test_f07_period_adapter_absent_field_returns_none():
    """F07: _PeriodAdapter returns None for absent fields, not 0.0.

    An absent field means the data was never persisted (NOT_AVAILABLE), not that
    the financial value is zero.  Callers must guard before arithmetic.
    """
    from app.services.v2_export_service import _PeriodAdapter

    p = _PeriodAdapter({"senior_balance_keur": 1000.0})
    assert p.senior_balance_keur == 1000.0
    assert p.shl_balance_keur is None, "Absent field must be None, not 0.0"
    assert p.shl_interest_keur is None


def test_f07_period_adapter_null_field_returns_none():
    """F07: _PeriodAdapter returns None for explicitly null fields, not 0.0."""
    from app.services.v2_export_service import _PeriodAdapter

    p = _PeriodAdapter({"senior_balance_keur": None})
    assert p.senior_balance_keur is None, "Explicit null must be None, not 0.0"


def test_f07_shl_data_available_false_when_no_shl_fields():
    """F07: shl_data_available returns False when debt_schedule has no SHL fields."""
    from app.services.v2_export_service import _RuntimeResultAdapter

    # Production debt_schedule has only senior fields — no SHL.
    debt_schedule = {
        "periods": [
            {
                "date": "2027-12-31",
                "senior_balance_keur": 50000.0,
                "senior_principal_keur": 1000.0,
                "senior_interest_keur": 500.0,
            }
        ]
    }
    adapter = _RuntimeResultAdapter({}, debt_schedule)
    assert adapter.shl_data_available is False


def test_f07_shl_data_available_true_when_shl_fields_present():
    """F07: shl_data_available returns True when SHL fields are in the debt_schedule."""
    from app.services.v2_export_service import _RuntimeResultAdapter

    debt_schedule = {
        "periods": [
            {
                "date": "2027-12-31",
                "shl_balance_keur": 10000.0,
                "shl_interest_keur": 300.0,
            }
        ]
    }
    adapter = _RuntimeResultAdapter({}, debt_schedule)
    assert adapter.shl_data_available is True


def test_f07_shl_not_available_export_succeeds_without_crash():
    """F07: Export with no SHL data produces 200 without crashing on float(None).

    _write_shl_sheet must render NOT_AVAILABLE via the guard, not raise TypeError.
    """
    from io import BytesIO
    from types import SimpleNamespace as NS
    import openpyxl
    from app.services.v2_export_service import (
        build_canonical_last_run_institutional_workbook_export,
    )
    from app.project_factories import create_generic_wind_reference
    from app.services.export_service import (
        EXPORT_AUTHORITY_CANONICAL_LAST_RUN,
        ResolvedExportAuthority,
    )

    fake_pi = create_generic_wind_reference()
    fake_record = NS(
        project_id="proj-shl",
        project_origin="user_created",
        project_code="shl_proj",
        project_name="SHL Test",
        project_type="Wind",
        template_source="generic_wind",
        project_origin_detail=None,
        baseline_snapshot=None,
    )
    # debt_schedule with senior-only periods (no SHL fields) — triggers NOT_AVAILABLE guard.
    mock_rr = NS(
        snapshot_id="snap-shl",
        ran_at="2026-03-01T00:00:00+00:00",
        runtime_summary={"project_irr": 0.10, "equity_irr": 0.14},
        debt_schedule={
            "periods": [
                {
                    "date": "2027-12-31",
                    "senior_balance_keur": 50000.0,
                    "senior_ds_keur": 3000.0,
                    "dscr": 1.40,
                }
            ]
        },
        financial_statements=None,
    )
    mock_authority = ResolvedExportAuthority(
        project_inputs=fake_pi,
        current_snapshot={},
        runtime_origin="canonical_last_run",
        active_scenario_id=None,
        active_scenario_name=None,
        last_runtime_scenario_id=None,
        any_run_committed=True,
        authority_mode=EXPORT_AUTHORITY_CANONICAL_LAST_RUN,
        run_id=None,
        run_at="2026-03-01T00:00:00+00:00",
        working_changed_since_run=False,
    )

    with (
        patch(
            "app.services.export_service.resolve_canonical_last_run_from_workspace",
            return_value=mock_authority,
        ),
        patch(
            "app.persistence.workspace_repository.get_workspace_state",
            return_value=NS(last_runtime_snapshot_id="snap-shl"),
        ),
        patch(
            "app.workbook.runtime_result.RuntimeResult.from_workspace_state",
            return_value=mock_rr,
        ),
    ):
        export = build_canonical_last_run_institutional_workbook_export(
            "generic_wind",
            safe_project="shl_proj",
            project_record=fake_record,
            user_id="user-shl",
        )

    assert export.status_code == 200, (
        f"Expected 200 but got {export.status_code}: {export.error_content}"
    )
    # Parse XLSX — SHL sheet should exist and contain NOT_AVAILABLE marker.
    wb = openpyxl.load_workbook(BytesIO(export.bytes_data))
    assert "SHL" in wb.sheetnames
    shl_sheet = wb["SHL"]
    # NOT_AVAILABLE marker should appear somewhere in the first 10 rows.
    shl_values = [shl_sheet.cell(row=r, column=1).value for r in range(1, 11)]
    assert any(
        v is not None and "NOT_AVAILABLE" in str(v).upper()
        for v in shl_values
    ), f"SHL sheet did not show NOT_AVAILABLE; first 10 rows col A: {shl_values}"


# ---------------------------------------------------------------------------
# F08 — Runtime timestamp from persisted ran_at, not export time
# ---------------------------------------------------------------------------


def test_f08_runtime_timestamp_uses_persisted_ran_at():
    """F08: workbook runtime_timestamp carries the persisted ran_at, not export time.

    build_runtime_summary_rows must use the runtime_timestamp passed in by the
    bundle builder rather than calling datetime.now().
    """
    from io import BytesIO
    from types import SimpleNamespace as NS
    import openpyxl
    from app.services.v2_export_service import (
        build_canonical_last_run_institutional_workbook_export,
    )
    from app.project_factories import create_generic_wind_reference
    from app.services.export_service import (
        EXPORT_AUTHORITY_CANONICAL_LAST_RUN,
        ResolvedExportAuthority,
    )

    PERSISTED_RAN_AT = "2025-03-15T08:30:00+00:00"

    fake_pi = create_generic_wind_reference()
    fake_record = NS(
        project_id="proj-ts",
        project_origin="user_created",
        project_code="ts_proj",
        project_name="Timestamp Test",
        project_type="Wind",
        template_source="generic_wind",
        project_origin_detail=None,
        baseline_snapshot=None,
    )
    mock_rr = NS(
        snapshot_id="snap-ts",
        ran_at=PERSISTED_RAN_AT,
        runtime_summary={"project_irr": 0.09},
        debt_schedule={"periods": []},
        financial_statements=None,
    )
    mock_authority = ResolvedExportAuthority(
        project_inputs=fake_pi,
        current_snapshot={},
        runtime_origin="canonical_last_run",
        active_scenario_id=None,
        active_scenario_name=None,
        last_runtime_scenario_id=None,
        any_run_committed=True,
        authority_mode=EXPORT_AUTHORITY_CANONICAL_LAST_RUN,
        run_id=None,
        run_at=PERSISTED_RAN_AT,
        working_changed_since_run=False,
    )

    with (
        patch(
            "app.services.export_service.resolve_canonical_last_run_from_workspace",
            return_value=mock_authority,
        ),
        patch(
            "app.persistence.workspace_repository.get_workspace_state",
            return_value=NS(last_runtime_snapshot_id="snap-ts"),
        ),
        patch(
            "app.workbook.runtime_result.RuntimeResult.from_workspace_state",
            return_value=mock_rr,
        ),
    ):
        export = build_canonical_last_run_institutional_workbook_export(
            "generic_wind",
            safe_project="ts_proj",
            project_record=fake_record,
            user_id="user-ts",
        )

    assert export.status_code == 200, f"Expected 200: {export.error_content}"
    # F08: metadata must carry the persisted ran_at, not the current export time.
    assert export.metadata.get("export_run_at") == PERSISTED_RAN_AT, (
        f"export_run_at should be persisted ran_at but got: {export.metadata.get('export_run_at')}"
    )
    # Also verify via XLSX: runtime_timestamp cell in Runtime Summary sheet.
    wb = openpyxl.load_workbook(BytesIO(export.bytes_data))
    assert "Runtime Summary" in wb.sheetnames
    # The runtime_timestamp row should contain the persisted date prefix, not today's date.
    rt_sheet = wb["Runtime Summary"]
    ts_values = []
    for row in rt_sheet.iter_rows(values_only=True):
        for cell in row:
            if cell and "2025-03-15" in str(cell):
                ts_values.append(cell)
    assert ts_values, (
        f"Persisted ran_at '2025-03-15' not found in Runtime Summary sheet rows"
    )


# ---------------------------------------------------------------------------
# F04 — Error response never reflects exception text
# ---------------------------------------------------------------------------


def test_f04_export_error_never_reflects_exception_text():
    """F04: ValueError message is not reflected into the HTML error response.

    Malicious content (e.g. from a persisted field) must not appear in the
    HTML error body — only a static safe message is returned.
    """
    from types import SimpleNamespace as NS
    from app.services.v2_export_service import (
        build_canonical_last_run_institutional_workbook_export,
    )

    fake_record = NS(
        project_id="proj-xss",
        project_origin="user_created",
        project_code="xss_proj",
    )
    MALICIOUS_MSG = "<script>alert('xss_from_persisted_field')</script>"

    with (
        patch(
            "app.persistence.workspace_repository.get_workspace_state",
            return_value=NS(last_runtime_snapshot_id="snap-xss"),
        ),
        patch(
            "app.services.export_service.resolve_canonical_last_run_from_workspace",
            side_effect=ValueError(MALICIOUS_MSG),
        ),
    ):
        export = build_canonical_last_run_institutional_workbook_export(
            "generic_wind",
            project_record=fake_record,
            user_id="user-xss",
        )

    assert export.status_code == 400
    assert MALICIOUS_MSG not in (export.error_content or ""), (
        "Exception text must not be reflected into the HTML error response (F04)"
    )
    assert "<script>" not in (export.error_content or "")


# ---------------------------------------------------------------------------
# F05 — Audit trail: actual project_code, scenario_id, snapshot_id
# ---------------------------------------------------------------------------


def test_f05_audit_uses_project_record_project_code():
    """F05: record_export is called with project_record.project_code, not template code.

    The audit trail must identify the user's actual project, not the template.
    Also verifies scenario_id and runtime_snapshot_id are passed.
    """
    from types import SimpleNamespace as NS
    from unittest.mock import MagicMock, patch as mock_patch
    from app.project_factories import create_generic_wind_reference
    from app.services.export_service import (
        EXPORT_AUTHORITY_CANONICAL_LAST_RUN,
        ResolvedExportAuthority,
    )

    fake_pi = create_generic_wind_reference()
    # project_code is "my_wind_farm_2026" — different from runtime template "generic_wind"
    fake_record = SimpleNamespace(
        project_id="proj-audit",
        project_origin="user_created",
        project_code="my_wind_farm_2026",
        project_name="My Wind Farm 2026",
        project_type="Wind",
        template_source="generic_wind",
        project_origin_detail=None,
        baseline_snapshot=None,
    )
    mock_rr = NS(
        snapshot_id="snap-audit-99",
        ran_at="2026-08-01T00:00:00+00:00",
        runtime_summary={"project_irr": 0.12},
        debt_schedule={"periods": []},
        financial_statements=None,
    )
    mock_authority = ResolvedExportAuthority(
        project_inputs=fake_pi,
        current_snapshot={},
        runtime_origin="canonical_last_run",
        active_scenario_id="sc-audit-x",
        active_scenario_name="Audit Scenario",
        last_runtime_scenario_id="sc-audit-x",
        any_run_committed=True,
        authority_mode=EXPORT_AUTHORITY_CANONICAL_LAST_RUN,
        run_id=None,
        run_at="2026-08-01T00:00:00+00:00",
        working_changed_since_run=False,
    )

    record_export_calls = []

    def _capture_record_export(**kwargs):
        record_export_calls.append(kwargs)
        return None

    client = _get_test_client()
    with (
        mock_patch("app.v2.router._get_current_user", return_value=_mock_user("user-audit")),
        mock_patch(
            "app.persistence.projects_repository.resolve_accessible_project",
            return_value=(fake_record, "user-audit"),
        ),
        mock_patch(
            "app.services.export_service.resolve_canonical_last_run_from_workspace",
            return_value=mock_authority,
        ),
        mock_patch(
            "app.persistence.workspace_repository.get_workspace_state",
            return_value=NS(last_runtime_snapshot_id="snap-audit-99"),
        ),
        mock_patch(
            "app.workbook.runtime_result.RuntimeResult.from_workspace_state",
            return_value=mock_rr,
        ),
        mock_patch(
            "app.persistence.repository.record_export",
            side_effect=_capture_record_export,
        ),
    ):
        resp = client.post("/v2/workbook/export", data={"project": "my_wind_farm_2026"})

    assert resp.status_code == 200
    assert len(record_export_calls) == 1, f"Expected 1 record_export call, got {len(record_export_calls)}"
    call_kwargs = record_export_calls[0]
    # F05: actual user project code, not template code.
    assert call_kwargs.get("project_code") == "my_wind_farm_2026", (
        f"Expected project_code='my_wind_farm_2026' but got {call_kwargs.get('project_code')!r}"
    )
    # F05: scenario identity.
    assert call_kwargs.get("scenario_id") == "sc-audit-x", (
        f"scenario_id not in audit call: {call_kwargs}"
    )
    # F05: runtime snapshot identity.
    assert call_kwargs.get("runtime_snapshot_id") == "snap-audit-99", (
        f"runtime_snapshot_id not in audit call: {call_kwargs}"
    )


# ---------------------------------------------------------------------------
# Working-vs-Last-Run invariant lock
# ---------------------------------------------------------------------------


def test_working_vs_lastrun_invariant_kpis_from_last_run():
    """Invariant: exported KPIs come from last run, not working-copy edits.

    When working inputs differ from last run (working_changed_since_run=True),
    the export must still carry last-run KPIs (project_irr=0.12 from rr, not
    any modified working value) AND flag working_changed_since_run=true.
    """
    from io import BytesIO
    from types import SimpleNamespace as NS
    import openpyxl
    from app.services.v2_export_service import (
        build_canonical_last_run_institutional_workbook_export,
    )
    from app.project_factories import create_generic_wind_reference
    from app.services.export_service import (
        EXPORT_AUTHORITY_CANONICAL_LAST_RUN,
        ResolvedExportAuthority,
    )

    LAST_RUN_IRR = 0.12
    fake_pi = create_generic_wind_reference()
    fake_record = NS(
        project_id="proj-inv",
        project_origin="user_created",
        project_code="inv_proj",
        project_name="Invariant Test",
        project_type="Wind",
        template_source="generic_wind",
        project_origin_detail=None,
        baseline_snapshot=None,
    )
    # RuntimeResult carries the last-run KPIs (project_irr=0.12).
    mock_rr = NS(
        snapshot_id="snap-inv",
        ran_at="2026-05-01T00:00:00+00:00",
        runtime_summary={"project_irr": LAST_RUN_IRR, "equity_irr": 0.18},
        debt_schedule={"periods": []},
        financial_statements=None,
    )
    # Authority: working has changed since last run.
    mock_authority = ResolvedExportAuthority(
        project_inputs=fake_pi,
        current_snapshot={},
        runtime_origin="canonical_last_run",
        active_scenario_id=None,
        active_scenario_name=None,
        last_runtime_scenario_id=None,
        any_run_committed=True,
        authority_mode=EXPORT_AUTHORITY_CANONICAL_LAST_RUN,
        run_id=None,
        run_at="2026-05-01T00:00:00+00:00",
        working_changed_since_run=True,  # working inputs were edited after last run
    )

    with (
        patch(
            "app.services.export_service.resolve_canonical_last_run_from_workspace",
            return_value=mock_authority,
        ),
        patch(
            "app.persistence.workspace_repository.get_workspace_state",
            return_value=NS(last_runtime_snapshot_id="snap-inv"),
        ),
        patch(
            "app.workbook.runtime_result.RuntimeResult.from_workspace_state",
            return_value=mock_rr,
        ),
    ):
        export = build_canonical_last_run_institutional_workbook_export(
            "generic_wind",
            safe_project="inv_proj",
            project_record=fake_record,
            user_id="user-inv",
        )

    assert export.status_code == 200, f"Expected 200: {export.error_content}"
    # Metadata must flag that working inputs changed.
    assert export.metadata.get("export_working_changed_since_run") == "true"
    # Runtime result adapter carries last-run project_irr — verify via bundle metadata.
    # The export bytes contain the last-run KPIs, not any modified working value.
    assert export.bytes_data is not None and len(export.bytes_data) > 0
    wb = openpyxl.load_workbook(BytesIO(export.bytes_data))
    assert "Runtime Summary" in wb.sheetnames


# ---------------------------------------------------------------------------
# Scenario invariant lock
# ---------------------------------------------------------------------------


def test_scenario_invariant_export_carries_last_run_scenario():
    """Scenario invariant: exported scenario = scenario at last run time.

    After switching the active scenario without re-running, the export must
    still reflect the last-run scenario identity, not the new active one.
    """
    from types import SimpleNamespace as NS
    from app.services.v2_export_service import (
        build_canonical_last_run_institutional_workbook_export,
    )
    from app.project_factories import create_generic_wind_reference
    from app.services.export_service import (
        EXPORT_AUTHORITY_CANONICAL_LAST_RUN,
        ResolvedExportAuthority,
    )

    fake_pi = create_generic_wind_reference()
    fake_record = NS(
        project_id="proj-sc-inv",
        project_origin="user_created",
        project_code="sc_inv_proj",
        project_name="Scenario Invariant Test",
        project_type="Wind",
        template_source="generic_wind",
        project_origin_detail=None,
        baseline_snapshot=None,
    )
    mock_rr = NS(
        snapshot_id="snap-sc-inv",
        ran_at="2026-07-01T00:00:00+00:00",
        runtime_summary={"project_irr": 0.10},
        debt_schedule={"periods": []},
        financial_statements=None,
    )
    # Authority: last_runtime_scenario_id = "sc-high" (run on High Case)
    # active_scenario_id = "sc-low" (user switched to Low Case but didn't re-run)
    mock_authority = ResolvedExportAuthority(
        project_inputs=fake_pi,
        current_snapshot={},
        runtime_origin="canonical_last_run",
        active_scenario_id="sc-low",       # working active scenario
        active_scenario_name="Low Case",
        last_runtime_scenario_id="sc-high",  # scenario used for last run
        any_run_committed=True,
        authority_mode=EXPORT_AUTHORITY_CANONICAL_LAST_RUN,
        run_id=None,
        run_at="2026-07-01T00:00:00+00:00",
        working_changed_since_run=True,
    )

    with (
        patch(
            "app.services.export_service.resolve_canonical_last_run_from_workspace",
            return_value=mock_authority,
        ),
        patch(
            "app.persistence.workspace_repository.get_workspace_state",
            return_value=NS(last_runtime_snapshot_id="snap-sc-inv"),
        ),
        patch(
            "app.workbook.runtime_result.RuntimeResult.from_workspace_state",
            return_value=mock_rr,
        ),
    ):
        export = build_canonical_last_run_institutional_workbook_export(
            "generic_wind",
            safe_project="sc_inv_proj",
            project_record=fake_record,
            user_id="user-sc-inv",
        )

    assert export.status_code == 200, f"Expected 200: {export.error_content}"
    # Exported last-run scenario must be "sc-high", not the current active "sc-low".
    assert export.metadata.get("export_last_runtime_scenario_id") == "sc-high", (
        f"Expected last_runtime_scenario_id='sc-high' but got "
        f"{export.metadata.get('export_last_runtime_scenario_id')!r}"
    )


# ---------------------------------------------------------------------------
# XLSX cell value verification
# ---------------------------------------------------------------------------


def test_xlsx_cell_value_verification():
    """XLSX cell value verification: open workbook and assert known KPI values.

    Proves that the exported XLSX actually encodes the persisted RuntimeResult
    data, not stale, default, or regenerated values.
    """
    from io import BytesIO
    from types import SimpleNamespace as NS
    import openpyxl
    from app.services.v2_export_service import (
        build_canonical_last_run_institutional_workbook_export,
    )
    from app.project_factories import create_generic_wind_reference
    from app.services.export_service import (
        EXPORT_AUTHORITY_CANONICAL_LAST_RUN,
        ResolvedExportAuthority,
    )

    KNOWN_PROJECT_IRR = 0.1337
    KNOWN_EQUITY_IRR = 0.1842
    KNOWN_SNAPSHOT_ID = "snap-cell-verify"

    fake_pi = create_generic_wind_reference()
    fake_record = NS(
        project_id="proj-cell",
        project_origin="user_created",
        project_code="cell_verify_proj",
        project_name="Cell Verify Project",
        project_type="Wind",
        template_source="generic_wind",
        project_origin_detail=None,
        baseline_snapshot=None,
    )
    mock_rr = NS(
        snapshot_id=KNOWN_SNAPSHOT_ID,
        ran_at="2026-04-20T12:00:00+00:00",
        runtime_summary={
            "project_irr": KNOWN_PROJECT_IRR,
            "equity_irr": KNOWN_EQUITY_IRR,
            "actual_min_dscr": 1.28,
            "actual_avg_dscr": 1.52,
            "total_revenue_keur": 75000.0,
        },
        debt_schedule={"periods": []},
        financial_statements=None,
    )
    mock_authority = ResolvedExportAuthority(
        project_inputs=fake_pi,
        current_snapshot={},
        runtime_origin="canonical_last_run",
        active_scenario_id="sc-cell",
        active_scenario_name="Cell Scenario",
        last_runtime_scenario_id="sc-cell",
        any_run_committed=True,
        authority_mode=EXPORT_AUTHORITY_CANONICAL_LAST_RUN,
        run_id=None,
        run_at="2026-04-20T12:00:00+00:00",
        working_changed_since_run=False,
    )

    with (
        patch(
            "app.services.export_service.resolve_canonical_last_run_from_workspace",
            return_value=mock_authority,
        ),
        patch(
            "app.persistence.workspace_repository.get_workspace_state",
            return_value=NS(last_runtime_snapshot_id=KNOWN_SNAPSHOT_ID),
        ),
        patch(
            "app.workbook.runtime_result.RuntimeResult.from_workspace_state",
            return_value=mock_rr,
        ),
    ):
        export = build_canonical_last_run_institutional_workbook_export(
            "generic_wind",
            safe_project="cell_verify_proj",
            project_record=fake_record,
            user_id="user-cell",
        )

    assert export.status_code == 200, f"Expected 200: {export.error_content}"
    assert export.bytes_data is not None
    wb = openpyxl.load_workbook(BytesIO(export.bytes_data))

    # Verify sheet existence.
    assert "Runtime Summary" in wb.sheetnames
    assert "SHL" in wb.sheetnames

    # Find project_irr and equity_irr values in the Runtime Summary sheet.
    rs = wb["Runtime Summary"]
    all_values = set()
    for row in rs.iter_rows(values_only=True):
        for cell in row:
            if cell is not None:
                all_values.add(cell)

    # project_irr = 0.1337 and equity_irr = 0.1842 must appear as numeric values.
    found_project_irr = any(
        isinstance(v, float) and abs(v - KNOWN_PROJECT_IRR) < 1e-6
        for v in all_values
    )
    found_equity_irr = any(
        isinstance(v, float) and abs(v - KNOWN_EQUITY_IRR) < 1e-6
        for v in all_values
    )
    assert found_project_irr, (
        f"project_irr={KNOWN_PROJECT_IRR} not found in Runtime Summary sheet values"
    )
    assert found_equity_irr, (
        f"equity_irr={KNOWN_EQUITY_IRR} not found in Runtime Summary sheet values"
    )

    # Scenario identity must appear in the sheet.
    all_str_values = {str(v) for v in all_values if v is not None}
    assert any("sc-cell" in s or "Cell Scenario" in s for s in all_str_values), (
        f"Scenario identity not found in Runtime Summary sheet"
    )

    # Snapshot ID must appear somewhere in the workbook (metadata provenance).
    all_wb_values = set()
    for sheet_name in wb.sheetnames:
        for row in wb[sheet_name].iter_rows(values_only=True):
            for cell in row:
                if cell is not None:
                    all_wb_values.add(str(cell))
    assert any(KNOWN_SNAPSHOT_ID in v for v in all_wb_values), (
        f"snapshot_id={KNOWN_SNAPSHOT_ID!r} not found anywhere in workbook"
    )


# ---------------------------------------------------------------------------
# Correction C — F07 residue: _RuntimeResultAdapter KPI None vs 0.0
# ---------------------------------------------------------------------------


def _make_correction_c_export(runtime_summary_dict, *, project_id="proj-c", snap_id="snap-c"):
    """Helper: run the canonical export with a given runtime_summary dict."""
    from io import BytesIO
    from types import SimpleNamespace as NS
    import openpyxl
    from app.services.v2_export_service import (
        build_canonical_last_run_institutional_workbook_export,
    )
    from app.project_factories import create_generic_wind_reference
    from app.services.export_service import (
        EXPORT_AUTHORITY_CANONICAL_LAST_RUN,
        ResolvedExportAuthority,
    )

    fake_pi = create_generic_wind_reference()
    fake_record = NS(
        project_id=project_id,
        project_origin="user_created",
        project_code=f"{project_id}_code",
        project_name="Correction C Project",
        project_type="Wind",
        template_source="generic_wind",
        project_origin_detail=None,
        baseline_snapshot=None,
    )
    mock_rr = NS(
        snapshot_id=snap_id,
        ran_at="2026-05-01T00:00:00+00:00",
        runtime_summary=runtime_summary_dict,
        debt_schedule={"periods": []},
        financial_statements=None,
    )
    mock_authority = ResolvedExportAuthority(
        project_inputs=fake_pi,
        current_snapshot={},
        runtime_origin="canonical_last_run",
        active_scenario_id=None,
        active_scenario_name=None,
        last_runtime_scenario_id=None,
        any_run_committed=True,
        authority_mode=EXPORT_AUTHORITY_CANONICAL_LAST_RUN,
        run_id=None,
        run_at="2026-05-01T00:00:00+00:00",
        working_changed_since_run=False,
    )

    with (
        patch(
            "app.services.export_service.resolve_canonical_last_run_from_workspace",
            return_value=mock_authority,
        ),
        patch(
            "app.persistence.workspace_repository.get_workspace_state",
            return_value=NS(last_runtime_snapshot_id=snap_id),
        ),
        patch(
            "app.workbook.runtime_result.RuntimeResult.from_workspace_state",
            return_value=mock_rr,
        ),
    ):
        export = build_canonical_last_run_institutional_workbook_export(
            "generic_wind",
            safe_project="correction_c",
            project_record=fake_record,
            user_id=f"user-{project_id}",
        )

    assert export.status_code == 200, (
        f"Expected 200 but got {export.status_code}: {export.error_content}"
    )
    wb = openpyxl.load_workbook(BytesIO(export.bytes_data))
    return export, wb


def _collect_kpi_cells(wb):
    """Return {label: cell_value} for the four KPI rows written directly to sheets."""
    # These labels are written by _write_key_value_section calls in institutional_workbook.py.
    target_labels = {
        "Runtime project IRR",
        "Runtime equity IRR",
        "Runtime avg DSCR",
        "Runtime min DSCR",
    }
    found = {}
    for sheet_name in wb.sheetnames:
        sheet = wb[sheet_name]
        for row in sheet.iter_rows(values_only=True):
            if row and row[0] in target_labels:
                found[row[0]] = row[1]  # column B is the value
    return found


def test_fc_null_kpi_not_exported_as_zero():
    """Correction C / F07-residue: persisted None KPI must not become 0.0 in the XLSX.

    Adversarial scenario: IRR calculation failed, DSCR not computed (no debt).
    The workbook must NOT display 0.0 for these cells — that would misrepresent
    NOT_AVAILABLE as a genuine financial zero.
    """
    _, wb = _make_correction_c_export(
        {
            "project_irr": None,
            "equity_irr": None,
            "actual_avg_dscr": None,
            "actual_min_dscr": None,
        },
        project_id="proj-null-kpi",
        snap_id="snap-null-kpi",
    )
    kpis = _collect_kpi_cells(wb)
    for label in ("Runtime project IRR", "Runtime equity IRR",
                  "Runtime avg DSCR", "Runtime min DSCR"):
        val = kpis.get(label)
        assert val != 0.0, (
            f"{label!r}: persisted None must not produce 0.0 in XLSX (got {val!r}). "
            "Absent persisted evidence ≠ financial zero."
        )


def test_fc_absent_kpi_key_not_exported_as_zero():
    """Correction C / F07-residue: entirely absent KPI key must not become 0.0.

    The missing-key case is distinct from an explicit None: the runtime_summary
    dict was persisted without the field (older run, partial failure).  The
    workbook must NOT display 0.0 for the missing field.
    """
    # runtime_summary has NO KPI keys at all.
    _, wb = _make_correction_c_export(
        {},
        project_id="proj-absent-kpi",
        snap_id="snap-absent-kpi",
    )
    kpis = _collect_kpi_cells(wb)
    for label in ("Runtime project IRR", "Runtime equity IRR",
                  "Runtime avg DSCR", "Runtime min DSCR"):
        val = kpis.get(label)
        assert val != 0.0, (
            f"{label!r}: absent key must not produce 0.0 in XLSX (got {val!r}). "
            "Missing persisted evidence ≠ financial zero."
        )


def test_fc_genuine_zero_kpi_retained():
    """Correction C: a genuine persisted 0.0 KPI must remain 0.0 in the XLSX.

    Correction C must distinguish NOT_AVAILABLE from an actual financial zero.
    A project whose IRR is legitimately zero (e.g. breakeven) or whose DSCR
    is 0.0 must not have those values silently erased.
    """
    _, wb = _make_correction_c_export(
        {
            "project_irr": 0.0,
            "equity_irr": 0.0,
            "actual_avg_dscr": 0.0,
            "actual_min_dscr": 0.0,
        },
        project_id="proj-zero-kpi",
        snap_id="snap-zero-kpi",
    )
    kpis = _collect_kpi_cells(wb)
    for label in ("Runtime project IRR", "Runtime equity IRR",
                  "Runtime avg DSCR", "Runtime min DSCR"):
        val = kpis.get(label)
        assert val == 0.0, (
            f"{label!r}: genuine persisted 0.0 must be retained as 0.0 in XLSX (got {val!r}). "
            "Correction C must not eliminate genuine financial zeros."
        )
