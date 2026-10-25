"""Golden Flow Correction B: composite identity is runtime freshness authority."""
from __future__ import annotations

from tests.run_clone_csrf import post_valid_csrf

import re
import uuid
from types import SimpleNamespace
from unittest.mock import patch

import pytest


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


@pytest.fixture
def reference_runs_seeded(tmp_path, monkeypatch):
    """Explicit, isolated precondition: the system reference projects hold their canonical last runs.

    App startup seeds them (four model runs) when the database is fresh and is a no-op afterwards. Without this
    fixture the test passed or failed depending on whether an earlier module had started the app against the same
    shared database, and the startup seeding was counted as user Runs (5 instead of 1). The fixture points the
    persistence layer at a private database, seeds there BEFORE the Run counter exists, and restores the shared path,
    so the test neither depends on nor writes the shared database. ``calls == 1`` and every other assertion are unchanged.
    """
    from app.persistence import db
    from app.services.project_library_service import ensure_reference_canonical_last_runs, ensure_reference_models

    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "golden-flow.db"))
    ensure_reference_models()
    ensure_reference_canonical_last_runs()


def test_active_scenario_override_stays_stale_on_reopen_and_first_run_succeeds(reference_runs_seeded):
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

            first_run = post_valid_csrf(client,
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

            from app.persistence.run_history_repository import get_run_history
            import copy as _copy
            frozen_history = _copy.deepcopy([(h.history_id, h.runtime_summary) for h in get_run_history(owner, record.project_id)])
            calls_before_mutation = calls

            # RC-5: P50 is not a bound scenario override. The rejected Save persists nothing, mutates nothing, runs nothing and invents no STALE.
            ws_before_reject = get_workspace_state(owner, record.project_id)
            rejected = client.post(
                "/v2/workbook/scenarios/update-overrides",
                data={"project": code, "scenario_id": scenario_id, "p50_hours": str(float(snapshot["p50_hours"]) * 1.1)},
                headers=htmx,
            )
            assert rejected.status_code == 422 and "SCENARIO_OVERRIDE_UNBOUND" in rejected.text, rejected.text[:300]
            assert "p50_hours" not in (get_scenario(scenario_id, owner).overrides or {})
            ws_after_reject = get_workspace_state(owner, record.project_id)
            for field in ("draft_snapshot", "dirty", "last_runtime_snapshot_id", "last_runtime_composite_hash", "last_runtime_at"):
                assert getattr(ws_after_reject, field) == getattr(ws_before_reject, field), field
            assert assemble_consistent_for_get(owner, record.project_id, WORKBOOK.version).composite_hash == old_runtime_hash
            assert calls == calls_before_mutation

            # A genuine supported scenario override: the contracted tariff (a valid value different from the starting one).
            start_tariff = float(snapshot["tariff_eur_mwh"])
            changed_tariff = round(start_tariff * 1.1, 2)
            assert changed_tariff != start_tariff
            mutated = client.post(
                "/v2/workbook/scenarios/update-overrides",
                data={
                    "project": code,
                    "scenario_id": scenario_id,
                    "tariff_eur_mwh": str(changed_tariff),
                },
                headers=htmx,
            )
            assert mutated.status_code == 200, mutated.text
            assert float(get_scenario(scenario_id, owner).overrides["tariff_eur_mwh"]) == changed_tariff       # persisted
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

            rerun = post_valid_csrf(client,
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
            # the new tariff override was consumed by the canonical Run, and the earlier committed Run evidence is unchanged
            consumed = final_ws.last_runtime_summary["scenario_revenue_input"]
            assert float(consumed["effective_tariff_eur_mwh"]) == changed_tariff and consumed["scenario_id"] == scenario_id, consumed
            history = get_run_history(owner, record.project_id)
            by_id = {h.history_id: h.runtime_summary for h in history}
            for history_id, summary in frozen_history:
                assert by_id[history_id] == summary
            assert len(history) == len(frozen_history) + 1
