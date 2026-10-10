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
        whatif._mapping("QM-SD-006", object(), "data_center", "10")
    with pytest.raises(whatif.Q4Rejected, match="Q4_FINDING_MAPPING_UNAVAILABLE"):
        whatif._mapping("QM-COV-001", object(), "solar", "1.3")


@pytest.mark.parametrize("name", ["", " ", "X" * 81, "ABC" + chr(10) + "DEF", "ABC" + chr(13) + "DEF", "ABC" + chr(0) + "DEF"])
def test_q4_scenario_name_bound(name):
    with pytest.raises(whatif.Q4Rejected):
        whatif._assert_name(name)


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
    result = c.get("/v2/workbook/whatif/compare",
        params={"project": record.project_code, "scenario_id": sid}, cookies=cookie(user))
    assert result.status_code == 200, result.text
    assert 'data-testid="q4-committed-compare"' in result.text
    assert "Canonical Run Integrity" in result.text
    assert len(get_run_history(user, record.project_id)) == len(history0) + 1
