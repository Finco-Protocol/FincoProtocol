"""Golden Flow Correction A: Inputs Slice 1 Save preserves Last Run authority."""
from __future__ import annotations

import uuid
from unittest.mock import patch


def test_inputs_slice1_htmx_save_uses_resolved_owner_and_preserves_last_run():
    import main_web
    from app.auth import COOKIE_NAME, create_session_token
    from app.persistence.projects_repository import create_project_record
    from app.persistence.workspace_repository import (
        get_workspace_state,
        save_workspace_state,
    )
    from app.workbook.registry import WORKBOOK
    from app.workbook.workbook_identity import assemble_consistent_for_get
    from starlette.testclient import TestClient

    owner = "gf-f01-" + uuid.uuid4().hex[:10]
    code = "gf-f01-" + uuid.uuid4().hex[:10]
    snapshot = main_web._project_baseline_snapshot("Solar", "generic_solar")
    snapshot.update({
        "active_project": code,
        "project_name": "Golden Flow F01",
        "project_type": "Solar",
        "project_origin": "user_created",
        "country_market": "Synthetic Market",
        "scenario": "Base",
    })
    record = create_project_record(
        user_id=owner,
        project_code=code,
        project_name="Golden Flow F01",
        project_type="Solar",
        project_origin="user_created",
        template_source="generic_solar",
        baseline_snapshot=snapshot,
    )
    save_workspace_state(
        user_id=owner,
        project_id=record.project_id,
        project_code=code,
        draft_snapshot=snapshot,
        saved_snapshot=snapshot,
        dirty=False,
    )
    token = create_session_token(user_id=owner, username=owner)
    headers = {"Cookie": f"{COOKIE_NAME}={token}"}

    with TestClient(main_web.app, raise_server_exceptions=False) as client:
        identity = assemble_consistent_for_get(
            user_id=owner,
            project_id=record.project_id,
            workbook_version=WORKBOOK.version,
        )
        run_response = client.post(
            "/v2/workbook/run",
            data={
                "project": code,
                "workbook_version": WORKBOOK.version,
                "content_hash": identity.composite_hash,
            },
            headers={**headers, "HX-Request": "true"},
        )
        assert run_response.status_code == 200, run_response.text

        before = get_workspace_state(user_id=owner, project_id=record.project_id)
        assert before is not None
        assert before.last_runtime_snapshot_id
        assert before.last_runtime_at
        assert before.last_runtime_summary
        assert before.dirty is False
        snapshot_id = before.last_runtime_snapshot_id
        runtime_at = before.last_runtime_at
        runtime_summary = before.last_runtime_summary

        current_identity = assemble_consistent_for_get(
            user_id=owner,
            project_id=record.project_id,
            workbook_version=WORKBOOK.version,
        )
        changed_p50 = float(before.draft_snapshot["p50_hours"]) * 1.2
        with (
            patch(
                "app.api.project_runner.run_project",
                side_effect=AssertionError("run_project called during Save"),
            ) as run_project,
            patch(
                "app.services.production_financial_authority.run_clean_production",
                side_effect=AssertionError("run_clean_production called during Save"),
            ) as run_clean,
            patch(
                "app.services.production_waterfall_seam.execute_production_waterfall",
                side_effect=AssertionError("execute_production_waterfall called during Save"),
            ) as waterfall,
        ):
            response = client.post(
                "/v2/workbook/inputs-slice1/update",
                data={
                    "field_id": "project_setup.technical.p50_hours",
                    "value": str(changed_p50),
                    "project": code,
                    "workbook_version": WORKBOOK.version,
                    "content_hash": current_identity.composite_hash,
                },
                headers={**headers, "HX-Request": "true"},
            )

        assert response.status_code == 200, response.text
        assert "NameError" not in response.text
        assert 'hx-swap-oob="true"' in response.text
        assert 'id="v2-toolbar-runtime-state"' in response.text
        assert 'id="v2-sheet-returns"' in response.text
        assert "Working changes pending" in response.text

        after = get_workspace_state(user_id=owner, project_id=record.project_id)
        assert after is not None
        assert float(after.draft_snapshot["p50_hours"]) == changed_p50
        assert after.dirty is True
        assert after.last_runtime_snapshot_id == snapshot_id
        assert after.last_runtime_at == runtime_at
        assert after.last_runtime_summary == runtime_summary
        run_project.assert_not_called()
        run_clean.assert_not_called()
        waterfall.assert_not_called()
