"""Q4 safety and integration checks. Real Solar/Wind lifecycle remains a release gate."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from app.v2 import whatif


def test_q4_allowlist_is_exactly_q1_to_workbook_to_scenario():
    from app.model_quality.registry import REGISTRY
    from app.persistence._helpers import SCENARIO_INPUT_FIELDS
    from app.workbook.registry import WORKBOOK
    from app.workbook.specs import ScenarioPolicy
    from app.v2.register_path_map import register_path_for_field

    checks = {check.check_id: check for check in REGISTRY}
    assert set(whatif.CANDIDATES) == {"QM-SD-004", "QM-SD-006", "QM-SD-007"}
    for check_id, (path, field_id, override) in whatif.CANDIDATES.items():
        assert path in checks[check_id].assumptions
        spec = WORKBOOK.field(field_id)
        assert register_path_for_field(field_id) == path
        assert spec.snapshot_key == override
        assert spec.scenario_policy is ScenarioPolicy.OVERRIDE
        assert spec.editable
        assert override in SCENARIO_INPUT_FIELDS


def test_q4_does_not_guess_unknown_findings_or_verticals():
    with pytest.raises(whatif.Q4Rejected, match="Q4_VERTICAL_NOT_ENABLED"):
        whatif._mapping("QM-SD-006", object(), "data_center", "10", run_state="CURRENT")
    with pytest.raises(whatif.Q4Rejected, match="Q4_FINDING_MAPPING_UNAVAILABLE"):
        whatif._mapping("QM-COV-001", object(), "solar", "1.3", run_state="CURRENT")


@pytest.mark.parametrize("name", ["", " ", "X" * 81, "ABC" + chr(10) + "DEF", "ABC" + chr(13) + "DEF", "ABC" + chr(0) + "DEF"])
def test_q4_scenario_name_bound(name):
    with pytest.raises(whatif.Q4Rejected):
        whatif._assert_name(name)


@pytest.mark.parametrize("fid", [
    "debt.senior.gearing_pct", "debt.senior.target_dscr",
])
def test_q4_selected_active_f3_never_downgrades_to_legacy_scalar(fid):
    from tests.test_model_financing_f3_workspace import state
    from app.workbook.multisenior_config import SNAPSHOT_KEY
    with pytest.raises(whatif.Q4Rejected, match="Q4_F3_COMPETING_SENIOR_EDITOR"):
        whatif._validate_financing(
            {SNAPSHOT_KEY: state(active=True, scope="base")},
            fid, 50.0 if fid.endswith("gearing_pct") else 1.4,
            scope="base",
        )


def test_q4_unicode_name_and_semantic_field_resolution():
    assert whatif._assert_name("Šibenik — scenarij") == "Šibenik — scenarij"
    from app.workbook.input_set import ProjectInputSet
    from app.workbook.registry import WORKBOOK
    snapshot = {
        "active_project": "synthetic",
        "template_source": "generic_solar_reference",
        "project_origin": "working_copy",
        "project_type": "solar_pv",
        "gearing_pct": "72.0",
        "target_dscr": "1.2",
    }
    pis = ProjectInputSet.from_snapshot(snapshot)
    assert pis.get("debt.senior.gearing_pct") == 72.0
    assert pis.get("debt.senior.target_dscr") == 1.2
    assert pis.values.get("gearing_pct") is None
    assert WORKBOOK.field("debt.senior.gearing_pct").snapshot_key == "gearing_pct"


def test_unsigned_confirmation_rejected_before_database_connection():
    with patch("app.persistence.db.get_connection", side_effect=AssertionError("must not touch DB")):
        with pytest.raises(whatif.Q4Rejected, match="Q4_CONFIRMATION_INVALID_OR_EXPIRED"):
            whatif.commit(owner="alice", project_id="project", project_type="solar", token="broken")


def test_signed_confirmation_owner_and_project_mismatch_rejected_before_database():
    data = dict(owner="alice", project_id="p1", project_type="solar", version="1",
                name="Candidate", nonce="nonce")
    token = whatif._token_serializer().dumps(data)
    with patch("app.persistence.db.get_connection", side_effect=AssertionError("must not touch DB")):
        with pytest.raises(whatif.Q4Rejected, match="Q4_CONFIRMATION_SCOPE_MISMATCH"):
            whatif.commit(owner="bob", project_id="p1", project_type="solar", token=token)
        with pytest.raises(whatif.Q4Rejected, match="Q4_CONFIRMATION_SCOPE_MISMATCH"):
            whatif.commit(owner="alice", project_id="p2", project_type="solar", token=token)


@pytest.fixture
def q4_http(tmp_path, monkeypatch):
    from app.persistence import db
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "q4.db"))
    db.init_db()
    from fastapi.testclient import TestClient
    from app.auth import COOKIE_NAME, create_session_token
    from main_web import app

    c = TestClient(app)
    def cookies(owner):
        return {COOKIE_NAME: create_session_token(user_id=owner, username="admin")}
    return c, cookies


def test_q4_rejects_not_run_and_no_scenario_is_written(q4_http):
    from app.services.reference_seed_service import create_reference_seeded_project
    from app.persistence.scenarios_repository import list_scenarios

    c, cookie = q4_http
    record = create_reference_seeded_project(
        user_id="q4-owner", template_source="generic_solar_reference",
        requested_name="Q4 test solar", capacity_mw=40)
    before = len(list_scenarios("q4-owner", record.project_id))
    payload = dict(project=record.project_code, check_id="QM-SD-006",
                   scenario_name="Debt What-if", proposed_value="55")
    rejected = c.post("/v2/workbook/whatif/preview", data=payload, cookies=cookie("q4-owner"))
    assert rejected.status_code == 409
    assert "q4-rejected" in rejected.text
    assert len(list_scenarios("q4-owner", record.project_id)) == before


def test_q4_rejects_cross_owner_project(q4_http):
    from app.services.reference_seed_service import create_reference_seeded_project

    c, cookie = q4_http
    record = create_reference_seeded_project(
        user_id="owner-a", template_source="generic_wind_reference",
        requested_name="Q4 test wind", capacity_mw=40)
    attempt = c.post("/v2/workbook/whatif/preview",
        data={"project": record.project_code, "check_id": "QM-SD-006",
              "proposed_value": "40", "scenario_name": "Foreign"},
        cookies=cookie("owner-b"))
    assert attempt.status_code in (403, 404)
    assert "q4-rejected" in attempt.text


@pytest.mark.parametrize("vertical,template", [
    ("solar", "generic_solar_reference"),
    ("wind", "generic_wind_reference"),
])
def test_q4_real_base_preview_commit_run_compare(q4_http, vertical, template):
    """Run real financial engine twice; never infer KPI from the preview."""
    import re

    from app.services.reference_seed_service import create_reference_seeded_project
    from app.persistence.workspace_repository import get_workspace_state
    from app.persistence.scenarios_repository import list_scenarios
    from app.persistence.run_history_repository import get_run_history

    c, cookie = q4_http
    user = "q4-real-" + vertical
    record = create_reference_seeded_project(
        user_id=user, template_source=template,
        requested_name="Q4 Real " + vertical, capacity_mw=40)
    url = "/v2/workbook?project=" + record.project_code

    def identity(html):
        return (re.search(r'name="content_hash" value="([^"]+)"', html).group(1),
                re.search(r'name="workbook_version" value="([^"]+)"', html).group(1))

    def run_explicitly():
        page = c.get(url, cookies=cookie(user))
        assert page.status_code == 200
        h, v = identity(page.text)
        result = c.post("/v2/workbook/run",
                        data={"project": record.project_code, "content_hash": h,
                              "workbook_version": v},
                        cookies=cookie(user), headers={"HX-Request": "true"})
        assert result.status_code == 200
        assert "Run failed" not in result.text

    # Wind reference may intentionally leave gearing unbound. Explicitly Save
    # an owner-controlled value before the Base Run; never infer a default.
    if not get_workspace_state(user, record.project_id).draft_snapshot.get("gearing_pct"):
        page = c.get(url, cookies=cookie(user))
        h, v = identity(page.text)
        updated = c.post("/v2/workbook/update", data={
            "field_id": "debt.senior.gearing_pct",
            "value": "65", "project": record.project_code,
            "workbook_version": v, "content_hash": h, "sheet_id": "debt",
        }, cookies=cookie(user), headers={"HX-Request": "true"})
        assert updated.status_code == 200
        assert float(get_workspace_state(user, record.project_id).draft_snapshot["gearing_pct"]) == 65
    run_explicitly()
    ws0 = get_workspace_state(user, record.project_id)
    history0 = get_run_history(user, record.project_id)
    assert history0 and ws0.last_runtime_snapshot_id
    initial_count = len(list_scenarios(user, record.project_id))
    original_gear = float(ws0.draft_snapshot["gearing_pct"])
    candidate = 50 if original_gear != 50 else 51

    preview_response = c.post("/v2/workbook/whatif/preview",
        data={"project": record.project_code, "check_id": "QM-SD-006",
              "scenario_name": "Q4 " + vertical + " What-if",
              "proposed_value": str(candidate)}, cookies=cookie(user))
    assert preview_response.status_code == 200, preview_response.text
    assert "NOT A RUN" in preview_response.text
    assert "Original input</dt><dd>" + str(original_gear) in preview_response.text
    assert "Proposed input</dt><dd>" + str(float(candidate)) in preview_response.text
    token = re.search(r'name="token" value="([^"]+)"', preview_response.text).group(1)
    assert len(get_run_history(user, record.project_id)) == len(history0)
    assert len(list_scenarios(user, record.project_id)) == initial_count

    # Change the Working Copy after preview: the exact composite CAS must reject it.
    page_before_edit = c.get(url, cookies=cookie(user)).text
    h, v = identity(page_before_edit)
    original_hours = float(ws0.draft_snapshot["p50_hours"])
    changed = c.post("/v2/workbook/update", data={
        "field_id": "project_setup.technical.p50_hours",
        "value": str(original_hours + 1), "project": record.project_code,
        "workbook_version": v, "content_hash": h, "sheet_id": "project_setup"},
        cookies=cookie(user), headers={"HX-Request": "true"})
    assert changed.status_code == 200
    rejected_stale = c.post("/v2/workbook/whatif/commit",
        data={"project": record.project_code, "token": token, "confirmed": "yes"},
        cookies=cookie(user))
    assert rejected_stale.status_code == 409
    assert "Q4_STALE_PREVIEW_CONFLICT" in rejected_stale.text
    assert len(list_scenarios(user, record.project_id)) == initial_count

    # Fresh user-controlled preview explicitly discloses STALE Run provenance.
    refreshed = c.post("/v2/workbook/whatif/preview",
        data={"project": record.project_code, "check_id": "QM-SD-006",
              "scenario_name": "Q4 " + vertical + " What-if",
              "proposed_value": str(candidate)}, cookies=cookie(user))
    assert refreshed.status_code == 200, refreshed.text
    assert "STALE" in refreshed.text
    token = re.search(r'name="token" value="([^"]+)"', refreshed.text).group(1)

    # Failure AFTER INSERT, immediately before COMMIT must roll back all effects.
    from app.persistence import db
    real_connection = db.get_connection

    class FailCommit:
        def __init__(self, conn):
            self.conn = conn
        def cursor(self):
            return self.conn.cursor()
        def execute(self, sql, *args):
            if sql == "COMMIT":
                raise RuntimeError("Q4_INJECTED_PRECOMMIT_FAILURE")
            return self.conn.execute(sql, *args)
        def close(self):
            self.conn.close()

    with patch("app.persistence.db.get_connection",
               side_effect=lambda: FailCommit(real_connection())):
        with pytest.raises(RuntimeError, match="Q4_INJECTED_PRECOMMIT_FAILURE"):
            whatif.commit(owner=user, project_id=record.project_id,
                          project_type=record.project_type or '', token=token)
    assert len(list_scenarios(user, record.project_id)) == initial_count
    assert len(get_run_history(user, record.project_id)) == len(history0)

    created = c.post("/v2/workbook/whatif/commit",
        data={"project": record.project_code, "token": token, "confirmed": "yes"},
        cookies=cookie(user))
    assert created.status_code == 200, created.text
    assert "NOT_RUN" in created.text
    sid = re.search(r"ID ([0-9a-f]{16})", created.text).group(1)
    scenarios = list_scenarios(user, record.project_id)
    assert len(scenarios) == initial_count + (2 if initial_count == 0 else 1)
    child = next(sc for sc in scenarios if sc.scenario_id == sid)
    assert child.overrides == {"gearing_pct": candidate}
    from app.persistence.scenarios_repository import resolve_scenario_snapshot
    from app.workbook.input_set import ProjectInputSet
    effective = resolve_scenario_snapshot(child.base_input_set, child.overrides)
    assert ProjectInputSet.from_snapshot(effective).get("debt.senior.gearing_pct") == candidate
    assert float(child.base_input_set["gearing_pct"]) == original_gear
    ws_before_select = get_workspace_state(user, record.project_id)
    assert ws_before_select.active_scenario_id == ws0.active_scenario_id
    assert ws_before_select.last_runtime_snapshot_id == ws0.last_runtime_snapshot_id
    assert len(get_run_history(user, record.project_id)) == len(history0)

    replay = c.post("/v2/workbook/whatif/commit",
        data={"project": record.project_code, "token": token, "confirmed": "yes"},
        cookies=cookie(user))
    assert replay.status_code == 409

    no_run = c.get("/v2/workbook/whatif/compare",
        params={"project": record.project_code, "scenario_id": sid}, cookies=cookie(user))
    assert "NOT_RUN" in no_run.text

    chosen = c.post("/v2/workbook/scenarios/select",
        data={"project": record.project_code, "scenario_id": sid},
        cookies=cookie(user), headers={"HX-Request": "true"})
    assert chosen.status_code == 200
    assert get_workspace_state(user, record.project_id).active_scenario_id == sid

    # Inspect the actual ProjectInputs forwarded to the real engine process.
    from app.runtime import model_execution
    actual_engine = model_execution.run_model_process
    observed = []
    async def capture_engine(func, *args, **kwargs):
        pi = kwargs["project_inputs_override"]
        observed.append((pi.financing.gearing_ratio, pi.financing.target_dscr))
        return await actual_engine(func, *args, **kwargs)
    with patch.object(model_execution, "run_model_process", capture_engine):
        run_explicitly()
    assert observed and observed[-1][0] == pytest.approx(candidate / 100)
    from app.services.export_service import resolve_canonical_last_run_from_workspace
    latest_ws = get_workspace_state(user, record.project_id)
    replay = resolve_canonical_last_run_from_workspace(record, user, latest_ws)
    assert replay.project_inputs.financing.gearing_ratio == pytest.approx(candidate / 100)
    result = c.get("/v2/workbook/whatif/compare",
        params={"project": record.project_code, "scenario_id": sid}, cookies=cookie(user))
    assert result.status_code == 200, result.text
    assert 'data-testid="q4-committed-compare"' in result.text
    assert "Canonical Run Integrity" in result.text
    assert len(get_run_history(user, record.project_id)) == len(history0) + 1



def test_q4_solar_target_dscr_real_engine_effective_change(q4_http):
    """Q4 uses the existing flat-DSCR authority; engine input is observed."""
    import re
    from app.services.reference_seed_service import create_reference_seeded_project
    from app.persistence.workspace_repository import get_workspace_state
    from app.persistence.scenarios_repository import list_scenarios
    from app.persistence.run_history_repository import get_run_history
    from app.runtime import model_execution
    from app.workbook.registry import WORKBOOK

    client, cookies = q4_http
    owner = "q4-dscr-solar-owner"
    project = create_reference_seeded_project(
        user_id=owner, template_source="generic_solar_reference",
        requested_name="DSCR Scenario Q4", capacity_mw=30,
    )
    url = "/v2/workbook"
    def auth_get():
        return client.get(url, params={"project": project.project_code}, cookies=cookies(owner))
    def _fields():
        html = auth_get().text
        return {k: re.search(r'name="' + k + r'" value="([^"]+)"', html).group(1)
                for k in ("content_hash", "workbook_version")}
    def _run():
        response = client.post("/v2/workbook/run", cookies=cookies(owner),
            headers={"HX-Request": "true"},
            data=dict(project=project.project_code, **_fields()))
        assert response.status_code == 200, response.text[:900]
        ws = get_workspace_state(owner, project.project_id)
        assert ws.last_runtime_summary and not ws.dirty, response.text[:900]

    # Source-proven explicit scalar; no model default or inferred value.
    ws = get_workspace_state(owner, project.project_id)
    if not ws.draft_snapshot.get("target_dscr"):
        response = client.post("/v2/workbook/update", cookies=cookies(owner),
            headers={"HX-Request": "true"}, data=dict(
                project=project.project_code, field_id="debt.senior.target_dscr",
                value="1.20", sheet_id="debt", **_fields()))
        assert response.status_code == 200
        assert float(get_workspace_state(owner, project.project_id).draft_snapshot["target_dscr"]) == 1.20
    _run()
    old = get_workspace_state(owner, project.project_id)
    original = float(old.draft_snapshot["target_dscr"])
    candidate = 1.35 if original != 1.35 else 1.3

    preview = client.post("/v2/workbook/whatif/preview", cookies=cookies(owner),
        data={"project": project.project_code, "check_id": "QM-SD-007",
              "proposed_value": str(candidate), "scenario_name": "DSCR-adjusted Q4"})
    assert preview.status_code == 200, preview.text
    assert f"Original input</dt><dd>{original}" in preview.text
    assert f"Proposed input</dt><dd>{candidate}" in preview.text
    token = re.search(r'name="token" value="([^"]+)"', preview.text).group(1)
    confirmed = client.post("/v2/workbook/whatif/commit", cookies=cookies(owner),
        data={"project": project.project_code, "token": token, "confirmed": "yes"})
    assert confirmed.status_code == 200, confirmed.text
    child = next(x for x in list_scenarios(owner, project.project_id)
                 if x.scenario_name == "DSCR-adjusted Q4")
    assert child.overrides == {"target_dscr": candidate}
    previous_history = tuple(get_run_history(owner, project.project_id))
    selected = client.post("/v2/workbook/scenarios/select", cookies=cookies(owner),
        headers={"HX-Request": "true"},
        data={"project": project.project_code, "scenario_id": child.scenario_id})
    assert selected.status_code == 200

    true_process = model_execution.run_model_process
    consumed = []
    async def verified_real_engine(func, *args, **kwargs):
        consumed.append(kwargs["project_inputs_override"].financing.target_dscr)
        return await true_process(func, *args, **kwargs)
    with patch.object(model_execution, "run_model_process", verified_real_engine):
        _run()
    assert consumed == pytest.approx([candidate])
    from app.services.export_service import resolve_canonical_last_run_from_workspace
    replay = resolve_canonical_last_run_from_workspace(
        project, owner, get_workspace_state(owner, project.project_id))
    assert replay.project_inputs.financing.target_dscr == pytest.approx(candidate)
    history = get_run_history(owner, project.project_id)
    assert len(history) == len(previous_history) + 1
    assert any(e.last_runtime_scenario_id == child.scenario_id for e in history)
    assert all(any(e.history_id == initial.history_id for e in history)
               for initial in previous_history)
    assert float(old.draft_snapshot["target_dscr"]) == original


def test_q4_token_tamper_and_scope_fail_closed():
    token = whatif._token_serializer().dumps({
        "owner": "alice", "project_id": "first", "project_type": "solar",
        "version": "1.0", "name": "Q4", "nonce": "unique",
    })
    with patch("app.persistence.db.get_connection",
               side_effect=AssertionError("invalid ticket must not touch DB")):
        for changed in (token[:-2] + "xY", "wrong-ticket"):
            with pytest.raises(whatif.Q4Rejected):
                whatif.commit(owner="alice", project_id="first",
                              project_type="solar", token=changed)
        with pytest.raises(whatif.Q4Rejected, match="SCOPE_MISMATCH"):
            whatif.commit(owner="alice", project_id="other",
                          project_type="solar", token=token)



def test_q4_atomic_rollback_after_base_insert_before_child_insert(q4_http):
    """A failure after lazy Base bootstrap rolls BOTH inserts back."""
    import re
    from app.persistence import db
    from app.services.reference_seed_service import create_reference_seeded_project
    from app.persistence.workspace_repository import get_workspace_state
    from app.persistence.run_history_repository import get_run_history
    from app.persistence.scenarios_repository import list_scenarios

    client, cookies = q4_http
    user = "q4-atomic-base-owner"
    project = create_reference_seeded_project(
        user_id=user, requested_name="Q4 Atomic Bootstrap Solar",
        template_source="generic_solar_reference", capacity_mw=40,
    )
    def page_tokens():
        response = client.get("/v2/workbook", params={"project": project.project_code},
                              cookies=cookies(user))
        assert response.status_code == 200
        return {key: re.search(r'name="' + key + r'" value="([^"]+)"', response.text).group(1)
                for key in ("content_hash", "workbook_version")}
    run = client.post("/v2/workbook/run", cookies=cookies(user),
                      headers={"HX-Request": "true"},
                      data=dict(project=project.project_code, **page_tokens()))
    assert run.status_code == 200
    before = get_workspace_state(user, project.project_id)
    history_before = tuple(get_run_history(user, project.project_id))
    bases_before = tuple(list_scenarios(user, project.project_id))
    assert not bases_before, "Test requires lazy Base initialization"
    candidate = 50 if float(before.draft_snapshot["gearing_pct"]) != 50 else 51
    preview = client.post("/v2/workbook/whatif/preview",
        cookies=cookies(user),
        data={"project": project.project_code, "check_id": "QM-SD-006",
              "scenario_name": "Atomic Base + What-if",
              "proposed_value": str(candidate)})
    assert preview.status_code == 200, preview.text
    ticket = re.search(r'name="token" value="([^"]+)"', preview.text).group(1)

    real_get_connection = db.get_connection
    class RejectSecondInsert:
        def __init__(self, raw):
            self.raw = raw
            self.inserts = 0
        def cursor(self):
            parent = self
            class Cursor:
                def __init__(self):
                    self.inner = parent.raw.cursor()
                def execute(self, sql, *args):
                    if sql.lstrip().upper().startswith("INSERT INTO SCENARIOS"):
                        parent.inserts += 1
                        if parent.inserts == 2:
                            raise RuntimeError("Q4_INJECTED_CHILD_INSERT_FAILURE")
                    return self.inner.execute(sql, *args)
                def __getattr__(self, name):
                    return getattr(self.inner, name)
            return Cursor()
        def execute(self, *args):
            return self.raw.execute(*args)
        def close(self):
            return self.raw.close()

    with patch("app.persistence.db.get_connection",
               side_effect=lambda: RejectSecondInsert(real_get_connection())):
        with pytest.raises(RuntimeError, match="Q4_INJECTED_CHILD_INSERT_FAILURE"):
            whatif.commit(owner=user, project_id=project.project_id,
                          project_type=project.project_type, token=ticket)
    assert tuple(list_scenarios(user, project.project_id)) == bases_before
    assert tuple(get_run_history(user, project.project_id)) == history_before
    assert get_workspace_state(user, project.project_id) == before
