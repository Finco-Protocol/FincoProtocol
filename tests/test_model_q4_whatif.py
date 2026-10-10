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


@pytest.mark.parametrize("name", ["", " ", "X" * 81, "ABC\\nDEF"])
def test_q4_scenario_name_bound(name):
    with pytest.raises(whatif.Q4Rejected):
        whatif._assert_name(name)


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
