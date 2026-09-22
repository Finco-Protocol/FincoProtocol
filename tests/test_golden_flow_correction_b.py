"""Golden Flow Correction B: composite identity is runtime freshness authority."""
from __future__ import annotations

import re
import uuid
from types import SimpleNamespace
from unittest.mock import patch


def _ws(**overrides):
    values = {
        "last_runtime_snapshot_id": "run-1",
        "any_run_committed": True,
        "draft_snapshot": {"x": 1},
        "last_runtime_snapshot": {"x": 1},
        "last_runtime_composite_hash": "hash-1",
        "dirty": False,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_runtime_freshness_uses_modern_composite_hash_and_fails_closed():
    from app.workbook.runtime_authority import (
        RuntimeAuthorityState,
        resolve_runtime_freshness,
    )

    current = resolve_runtime_freshness(
        _ws(), current_composite_hash="hash-1")
    stale = resolve_runtime_freshness(
        _ws(), current_composite_hash="hash-2")
    unresolved = resolve_runtime_freshness(
        _ws(), current_composite_hash=None)

    assert current.state is RuntimeAuthorityState.CURRENT
    assert stale.state is RuntimeAuthorityState.STALE
    assert unresolved.state is RuntimeAuthorityState.STALE
    assert unresolved.source == "identity_unresolved"


def test_runtime_freshness_preserves_legacy_scalar_fallback():
    from app.workbook.runtime_authority import RuntimeAuthorityState, resolve_runtime_freshness

    clean = resolve_runtime_freshness(
        _ws(last_runtime_composite_hash=None), current_composite_hash="working")
    stale = resolve_runtime_freshness(
        _ws(last_runtime_composite_hash=None, draft_snapshot={"x": 2}),
        current_composite_hash="working",
    )

    assert clean.state is RuntimeAuthorityState.CURRENT
    assert stale.state is RuntimeAuthorityState.STALE
    assert clean.source == stale.source == "legacy_scalar_fallback"


def _hashes(html: str) -> list[str]:
    return re.findall(r'name="content_hash"\s+value="([^"]+)"', html)


def test_active_scenario_override_stays_stale_on_reopen_and_first_run_succeeds():
    import main_web
    from app.api import project_runner
    from app.auth import COOKIE_NAME, create_session_token
    from app.persistence.projects_repository import create_project_record
    from app.persistence.scenarios_repository import get_scenario
    from app.persistence.workspace_repository import get_workspace_state, save_workspace_state
    from app.workbook.registry import WORKBOOK
    from app.workbook.workbook_identity import assemble_consistent_for_get
    from starlette.testclient import TestClient

    owner = "flow-b-" + uuid.uuid4().hex[:10]
    code = "flow-b-" + uuid.uuid4().hex[:10]
    snapshot = main_web._project_baseline_snapshot("Solar", "generic_solar")
    snapshot.update({
        "active_project": code,
        "project_name": "Synthetic Flow B",
        "project_type": "Solar",
        "project_origin": "user_created",
        "country_market": "Synthetic Market",
        "scenario": "Base",
    })
    record = create_project_record(
        user_id=owner,
        project_code=code,
        project_name="Synthetic Flow B",
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
    cookie = {"Cookie": f"{COOKIE_NAME}={create_session_token(user_id=owner, username=owner)}"}
    htmx = {**cookie, "HX-Request": "true"}

    calls = 0
    real_run = project_runner.run_project

    def counted_run(*args, **kwargs):
        nonlocal calls
        calls += 1
        return real_run(*args, **kwargs)

    with patch("app.api.project_runner.run_project", side_effect=counted_run):
        with TestClient(main_web.app, raise_server_exceptions=False) as client:
            created = client.post(
                "/v2/workbook/scenarios/create",
                data={"project": code, "scenario_name": "Scenario X"},
                headers=htmx,
            )
            assert created.status_code == 200, created.text
            create_hash = _hashes(created.text)[-1]

            first_run = client.post(
                "/v2/workbook/run",
                data={
                    "project": code,
                    "workbook_version": WORKBOOK.version,
                    "content_hash": create_hash,
                },
                headers=htmx,
            )
            assert first_run.status_code == 200, first_run.text
            assert calls == 1

            before = get_workspace_state(owner, record.project_id)
            assert before is not None
            scenario_id = before.active_scenario_id
            old_snapshot_id = before.last_runtime_snapshot_id
            old_runtime_at = before.last_runtime_at
            old_runtime_hash = before.last_runtime_composite_hash
            current_before = assemble_consistent_for_get(
                owner, record.project_id, WORKBOOK.version).composite_hash
            assert current_before == old_runtime_hash

            calls_before_mutation = calls
            changed_p50 = float(snapshot["p50_hours"]) * 1.1
            mutated = client.post(
                "/v2/workbook/scenarios/update-overrides",
                data={
                    "project": code,
                    "scenario_id": scenario_id,
                    "p50_hours": str(changed_p50),
                },
                headers=htmx,
            )
            assert mutated.status_code == 200, mutated.text
            assert calls == calls_before_mutation
            assert 'id="v2-run-controls" hx-swap-oob="true"' in mutated.text
            assert 'data-testid="toolbar-runtime-state">Stale<' in mutated.text
            assert 'data-testid="overview-status-stale"' in mutated.text
            assert "Working changes pending" in mutated.text
            assert "Run required" in mutated.text
            assert "STALE" in mutated.text

            after = get_workspace_state(owner, record.project_id)
            current_after = assemble_consistent_for_get(
                owner, record.project_id, WORKBOOK.version).composite_hash
            returned_hash = _hashes(mutated.text)[-1]
            assert after.dirty is False
            assert current_after != old_runtime_hash
            assert returned_hash == current_after
            assert after.last_runtime_composite_hash == old_runtime_hash
            assert after.last_runtime_snapshot_id == old_snapshot_id
            assert after.last_runtime_at == old_runtime_at
            assert get_scenario(scenario_id, owner).last_run_summary

            reopened = client.get(f"/v2/workbook?project={code}", headers=cookie)
            assert reopened.status_code == 200, reopened.text
            assert 'data-testid="toolbar-runtime-state">Stale<' in reopened.text
            assert 'data-testid="overview-status-stale"' in reopened.text
            assert "Working changes pending" in reopened.text
            assert calls == calls_before_mutation

            rerun = client.post(
                "/v2/workbook/run",
                data={
                    "project": code,
                    "workbook_version": WORKBOOK.version,
                    "content_hash": returned_hash,
                },
                headers=htmx,
            )
            assert rerun.status_code == 200, rerun.text
            assert "Draft changed since page loaded" not in rerun.text
            assert calls == calls_before_mutation + 1
            assert 'data-testid="toolbar-runtime-state">Current<' in rerun.text

            final_ws = get_workspace_state(owner, record.project_id)
            final_hash = assemble_consistent_for_get(
                owner, record.project_id, WORKBOOK.version).composite_hash
            assert final_ws.last_runtime_composite_hash == final_hash
            assert final_ws.last_runtime_snapshot_id != old_snapshot_id
            assert final_ws.last_runtime_at != old_runtime_at
