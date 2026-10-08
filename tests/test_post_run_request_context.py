"""V6 production context: real persisted states, immutable evidence, isolation.

Wall-clock thresholds belong to the paired benchmark, not these tests.
"""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError, replace
import json
import re
import sqlite3

import pytest

from app.v2.post_run_context import PostRunContextChanged, PostRunRequestContext


def _tokens(client, cookies, code):
    response = client.get("/v2/workbook", params={"project": code}, cookies=cookies)
    assert response.status_code == 200
    return (re.search(r'name="content_hash" value="([^"]+)"', response.text).group(1),
            re.search(r'name="workbook_version" value="([^"]+)"', response.text).group(1))


@pytest.fixture(scope="module")
def seed_database(tmp_path_factory):
    from app.auth import COOKIE_NAME, create_session_token
    from app.persistence import db
    from app.runtime.model_execution import reset_model_executor_for_tests
    from app.services.reference_seed_service import create_reference_seeded_project
    from fastapi.testclient import TestClient
    import main_web

    patch = pytest.MonkeyPatch()
    path = tmp_path_factory.mktemp("post-run-context-seed") / "seed.db"
    patch.setattr(db, "DB_PATH", str(path))
    db.init_db()
    projects = {}
    try:
        with TestClient(main_web.app) as client:
            for case, template, capacity in (("solar", "generic_solar_reference", 64.0),
                                              ("wind", "generic_wind_reference", 48.0),
                                              ("data_center", "generic_data_center_reference", 16.0),
                                              ("ev_charging", "generic_ev_charging_reference", 1.0)):
                uid = "test-context-" + case
                record = create_reference_seeded_project(
                    user_id=uid, template_source=template, capacity_mw=capacity,
                    requested_name="Context " + case)
                cookies = {COOKIE_NAME: create_session_token(user_id=uid, username="admin")}
                h, v = _tokens(client, cookies, record.project_code)
                response = client.post("/v2/workbook/run", cookies=cookies,
                    headers={"HX-Request": "true"}, data={"project": record.project_code,
                    "content_hash": h, "workbook_version": v})
                assert response.status_code == 200
                projects[case] = record
        yield path, projects
    finally:
        reset_model_executor_for_tests()
        patch.undo()


@pytest.fixture
def state_db(seed_database, tmp_path, monkeypatch):
    from app.persistence import db
    source_path, projects = seed_database
    target = tmp_path / "context.db"
    with sqlite3.connect(source_path) as source, sqlite3.connect(target) as copy:
        source.backup(copy)
    monkeypatch.setattr(db, "DB_PATH", str(target))
    return projects


def _capture(pr, **kwargs):
    return PostRunRequestContext.capture(owner_id=pr.user_id, project_id=pr.project_id, **kwargs)


def _args(pr, ws=None):
    from app.persistence.workspace_repository import get_workspace_state
    from app.workbook.service import WorkbookService
    if ws is None:
        ws = get_workspace_state(pr.user_id, pr.project_id)
    return dict(request=None, project=pr.project_code, workspace_owner=pr.user_id,
                project_record=pr, ws_fresh=ws, rr=WorkbookService.get_runtime_result(ws))


def _fast(context):
    from app.v2.post_run_ui import build_post_run_ui_state
    return build_post_run_ui_state(request=None, project=context.project_record.project_code,
        workspace_owner=context.owner_id, project_record=context.project_record,
        ws_fresh=context.workspace, rr=context.runtime_result, context=context)


def _edit(pr, hours=2300):
    from app.persistence.workspace_repository import get_workspace_state
    from app.workbook.update_service import WorkbookUpdateService
    context = _capture(pr)
    WorkbookUpdateService.apply_draft_update(
        ws=get_workspace_state(pr.user_id, pr.project_id),
        field_id="project_setup.technical.p50_hours", raw_value=str(hours),
        content_hash=context.identity.composite_hash,
        workbook_version=context.inputs.workbook_version, project_record=pr)


@pytest.mark.parametrize("case", ["solar", "wind"])
@pytest.mark.parametrize("state", ["CURRENT", "STALE", "NOT_RUN"])
def test_real_lifecycle_exact_html_and_trust(state_db, case, state):
    from app.services.reference_seed_service import create_reference_seeded_project
    from app.ui.trust_pack import build_trust_pack
    from app.v2.post_run_ui import build_post_run_ui_state
    pr = state_db[case]
    if state == "STALE":
        _edit(pr)
    elif state == "NOT_RUN":
        pr = create_reference_seeded_project(user_id=pr.user_id,
            template_source=pr.template_source, capacity_mw=64.0 if case == "solar" else 48.0,
            requested_name="Never Run " + case)
    context = _capture(pr)
    assert context.freshness.state.value == state
    assert _fast(context) == build_post_run_ui_state(**_args(pr))
    plain = build_trust_pack(pr.user_id, pr.project_id, project_code=pr.project_code,
                            any_run_committed=context.workspace.any_run_committed)
    shared = build_trust_pack(pr.user_id, pr.project_id, project_code=pr.project_code,
                             any_run_committed=context.workspace.any_run_committed, context=context)
    assert shared == plain


def test_nested_snapshot_is_immutable_and_detached(state_db):
    context = _capture(state_db["solar"])
    with pytest.raises(FrozenInstanceError):
        context.owner_id = "other"
    with pytest.raises(FrozenInstanceError):
        context.workspace.dirty = True
    with pytest.raises(TypeError):
        context.workspace.draft_snapshot["new"] = "value"
    with pytest.raises(TypeError):
        context.runtime_result.runtime_summary["new"] = 1
    with pytest.raises(TypeError):
        context.runtime_result.debt_schedule["periods"].append({})
    with pytest.raises(TypeError):
        context.identity.scenario.overrides["new"] = 1


@pytest.mark.parametrize("service", ["get_run_identity", "get_kpis", "get_verify_state",
                                      "get_export_metadata", "get_run_integrity_checks"])
def test_context_never_grants_cross_owner_or_project_access(state_db, service):
    from app.api.v1_1 import institutional
    pr, other = state_db["solar"], state_db["wind"]
    context = _capture(pr)
    call = getattr(institutional, service)
    with pytest.raises(PermissionError):
        call(other.user_id, pr.project_id, context=context)
    with pytest.raises(PermissionError):
        call(pr.user_id, other.project_id, context=context)
    with pytest.raises(PermissionError):
        PostRunRequestContext.capture(owner_id=other.user_id, project_id=pr.project_id)
    assert institutional.get_run_identity(other.user_id, pr.project_id)[0] == "UNAVAILABLE"


@pytest.mark.parametrize("service", ["get_run_identity", "get_kpis", "get_verify_state",
                                      "get_export_metadata", "get_run_integrity_checks"])
def test_non_context_institutional_calls_keep_legacy_call_shapes(state_db, monkeypatch, service):
    from app.api.v1_1 import institutional
    pr = state_db["solar"]
    call = getattr(institutional, service)
    expected = call(pr.user_id, pr.project_id)
    original_loader = institutional._load_workspace
    original_adapter = institutional._runtime_result_adapter

    def legacy_loader(owner_id, project_id):
        return original_loader(owner_id, project_id)

    def legacy_adapter(workspace):
        return original_adapter(workspace)

    monkeypatch.setattr(institutional, "_load_workspace", legacy_loader)
    monkeypatch.setattr(institutional, "_runtime_result_adapter", legacy_adapter)
    assert call(pr.user_id, pr.project_id) == expected


def test_same_owner_two_projects_no_binding_reuse(state_db):
    from app.services.reference_seed_service import create_reference_seeded_project
    pr = state_db["solar"]
    other = create_reference_seeded_project(user_id=pr.user_id,
        template_source=pr.template_source, requested_name="Second Project", capacity_mw=32.0)
    context, other_context = _capture(pr), _capture(other)
    with pytest.raises(PermissionError):
        context.require_scope(pr.user_id, other.project_id)
    with pytest.raises(ValueError):
        context.require_binding(context.workspace, context.project_record, other_context.runtime_result)


def test_no_repeated_runtime_draft_or_institutional_db_reads(state_db, monkeypatch):
    from app.persistence import projects_repository, workspace_repository
    from app.workbook.service import WorkbookService
    context = _capture(state_db["solar"])
    def forbidden(*a, **k):
        raise AssertionError("Redundant same-snapshot read/projection")
    monkeypatch.setattr(projects_repository, "get_project", forbidden)
    monkeypatch.setattr(workspace_repository, "get_workspace_state", forbidden)
    monkeypatch.setattr(WorkbookService, "get_runtime_result", forbidden)
    monkeypatch.setattr(WorkbookService, "build_draft_input_set_from_workspace", forbidden)
    html = _fast(context)
    for target in ("v2-run-controls", "v2-export-controls", "v2-status-banner",
                   "v2-toolbar-runtime-state", "v2-sheet-overview", "v2-sheet-senior-debt",
                   "v2-sheet-tax", "v2-sheet-financial-statements", "v2-sheet-returns",
                   "v2-sheet-scenarios", "model-workspace-header", "model-smart-panel",
                   "v2-sheet-run-history"):
        assert re.search(r'id="' + target + r'"[^>]*hx-swap-oob', html)


def test_wrong_supplied_runtime_is_reconciled_from_persistence(state_db):
    pr = state_db["solar"]
    good = _capture(pr)
    fake = replace(good.runtime_result, snapshot_id="not-the-persisted-run")
    repaired = _capture(pr, expected_workspace=good.workspace, runtime_result=fake)
    assert repaired.runtime_result == good.runtime_result
    assert repaired.runtime_result.snapshot_id != fake.snapshot_id


@pytest.mark.parametrize("corruption", ["hash", "summary", "scenario"])
def test_invalid_persisted_authority_fails_closed(state_db, corruption):
    from app.persistence.db import get_cursor
    from app.workbook.workbook_identity import WorkbookIdentityError
    pr = state_db["solar"]
    with get_cursor() as cur:
        if corruption == "hash":
            cur.execute("UPDATE workspace_states SET last_runtime_identity_json=? WHERE project_id=?",
                        (json.dumps({"composite_hash": "different"}), pr.project_id))
        elif corruption == "summary":
            cur.execute("UPDATE workspace_states SET last_runtime_summary_json='{}' WHERE project_id=?",
                        (pr.project_id,))
        else:
            from app.persistence.scenarios_repository import get_or_create_base_case_scenario
            foreign = state_db["wind"]
            sc = get_or_create_base_case_scenario(user_id=foreign.user_id, project_id=foreign.project_id,
                project_code=foreign.project_code, project_name=foreign.project_name,
                project_type=foreign.project_type, source_project_template=foreign.template_source,
                base_input_set={}, governance_state={})
            cur.execute("UPDATE workspace_states SET active_scenario_id=? WHERE project_id=?",
                        (sc.scenario_id, pr.project_id))
    with pytest.raises(WorkbookIdentityError):
        _capture(pr)


def test_concurrent_edit_invalidates_old_context_and_reconciles(state_db, monkeypatch):
    from app.v2 import post_run_ui
    pr = state_db["solar"]
    old = _capture(pr)
    original = post_run_ui._build_smart_panel_oob
    calls = []
    def edit_during_render(*a, **k):
        if not calls:
            calls.append(True)
            with ThreadPoolExecutor(max_workers=1) as pool:
                pool.submit(_edit, pr).result(timeout=15)
        return original(*a, **k)
    monkeypatch.setattr(post_run_ui, "_build_smart_panel_oob", edit_during_render)
    html = post_run_ui.build_coherent_post_run_ui_state(**_args(pr))
    with pytest.raises(PostRunContextChanged):
        old.validate_current()
    new = _capture(pr)
    assert new.freshness.state.value == "STALE"
    assert new.workspace.last_runtime_snapshot_id == old.workspace.last_runtime_snapshot_id
    assert new.workspace.last_runtime_at == old.workspace.last_runtime_at
    assert new.workspace.last_runtime_composite_hash == old.workspace.last_runtime_composite_hash
    assert html == _fast(new)


def test_context_isolated_between_concurrent_same_owner_requests(state_db):
    pr = state_db["solar"]
    with ThreadPoolExecutor(max_workers=2) as pool:
        left, right = list(pool.map(lambda _: _capture(pr), range(2)))
    assert left is not right and left.workspace is not right.workspace
    assert left.runtime_result is not right.runtime_result
    assert left.identity.composite_hash == right.identity.composite_hash
    assert _fast(left) == _fast(right)


def test_repeated_concurrent_changes_fail_without_mutating_last_run(state_db, monkeypatch):
    from app.v2 import post_run_ui
    pr = state_db["solar"]
    before = _capture(pr)
    original = post_run_ui._build_smart_panel_oob
    changes = []
    def mutate(*a, **k):
        changes.append(True)
        _edit(pr, hours=2300 + len(changes))
        return original(*a, **k)
    monkeypatch.setattr(post_run_ui, "_build_smart_panel_oob", mutate)
    with pytest.raises(PostRunContextChanged):
        post_run_ui.build_coherent_post_run_ui_state(**_args(pr))
    assert len(changes) == 2
    assert _capture(pr).workspace.last_runtime_snapshot_id == before.workspace.last_runtime_snapshot_id


@pytest.mark.parametrize("case", ["data_center", "ev_charging"])
def test_other_technologies_exact_html_and_projection(state_db, case):
    from app.v2.post_run_ui import build_post_run_ui_state
    pr = state_db[case]
    context = _capture(pr)
    assert context.freshness.state.value == "CURRENT"
    assert _fast(context) == build_post_run_ui_state(**_args(pr))


def test_scenario_switch_during_render_restores_correct_run_and_legacy_base(state_db, monkeypatch):
    from app.auth import COOKIE_NAME, create_session_token
    from app.persistence.scenarios_repository import list_scenarios, select_scenario
    from app.v2 import post_run_ui
    from fastapi.testclient import TestClient
    import main_web

    pr = state_db["solar"]
    base_run = _capture(pr)
    cookies = {COOKIE_NAME: create_session_token(user_id=pr.user_id, username="admin")}
    try:
        with TestClient(main_web.app) as client:
            response = client.post("/v2/workbook/scenarios/create", cookies=cookies,
                headers={"HX-Request": "true"},
                data={"project": pr.project_code, "scenario_name": "Context Scenario"})
            assert response.status_code == 200
            scenarios = list_scenarios(pr.user_id, pr.project_id)
            base = next(s for s in scenarios if s.is_base_case)
            child = next(s for s in scenarios if not s.is_base_case)
            h, v = _tokens(client, cookies, pr.project_code)
            response = client.post("/v2/workbook/run", cookies=cookies,
                headers={"HX-Request": "true"}, data={"project": pr.project_code,
                "content_hash": h, "workbook_version": v})
            assert response.status_code == 200
            child_run = _capture(pr)
            assert child_run.workspace.last_runtime_scenario_id == child.scenario_id
            original = post_run_ui._build_smart_panel_oob
            selected = []
            def select_during_render(*a, **k):
                if not selected:
                    with ThreadPoolExecutor(max_workers=1) as pool:
                        assert pool.submit(select_scenario, pr.user_id, pr.project_id,
                                           base.scenario_id).result(timeout=15)
                    selected.append(True)
                return original(*a, **k)
            monkeypatch.setattr(post_run_ui, "_build_smart_panel_oob", select_during_render)
            html = post_run_ui.build_coherent_post_run_ui_state(**_args(pr))
            restored_base = _capture(pr)
            assert restored_base.workspace.last_runtime_snapshot_id == base_run.workspace.last_runtime_snapshot_id
            assert restored_base.workspace.last_runtime_scenario_id is None
            assert restored_base.freshness.state.value == "CURRENT"
            assert restored_base.freshness.source == "pre_scenario_base_equivalence"
            assert restored_base.workspace.last_runtime_identity == base_run.workspace.last_runtime_identity
            assert html == _fast(restored_base)
            with pytest.raises(PostRunContextChanged):
                child_run.validate_current()
            assert select_scenario(pr.user_id, pr.project_id, child.scenario_id)
            restored_child = _capture(pr)
            assert restored_child.workspace.last_runtime_snapshot_id == child_run.workspace.last_runtime_snapshot_id
            assert restored_child.workspace.last_runtime_scenario_id == child.scenario_id
            assert restored_child.runtime_result == child_run.runtime_result
            assert restored_child.freshness.state.value == "CURRENT"
    finally:
        from app.runtime.model_execution import reset_model_executor_for_tests
        reset_model_executor_for_tests()
