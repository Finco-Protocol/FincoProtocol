"""RC-UX Addendum A — React Trust evidence adapter (certificate + reference regression) over the REAL canonical builders.

The adapter replaces the classic ``/v2/workbook/trust/*`` HTML fragments: each response equals the section dict the same canonical
builder returns to those fragments, projected through an allow-list.  Nothing is written, nothing is estimated, unavailable stays unavailable.
"""
from __future__ import annotations

import sqlite3

import pytest

from tests.test_model_decision_workspace_v2 import env  # noqa: F401  (fixture)
from tests.test_model_financing_f2 import run

CERT = "/v2/model-react/trust/certificate"
VALID = "/v2/model-react/trust/validation"
HDR = {"X-Finco-React-Request": "1"}


@pytest.fixture
def trust(env, monkeypatch):  # noqa: F811
    from app.v2.react_trust import router
    monkeypatch.setenv("FINCO_MODEL_REACT_V1", "1")
    env.client.app.include_router(router, prefix="/v2")
    return env


def db_dump():
    from app.persistence import db
    with sqlite3.connect(db.DB_PATH) as conn:
        return "\n".join(conn.iterdump())


def test_router_is_mounted_before_the_project_catch_all():
    from app.v2.router import router
    paths = [getattr(route, "path", "") for route in router.routes]
    for path in ("/model-react/trust/certificate", "/model-react/trust/validation"):
        assert paths.count(path) == 1 and paths.index(path) < paths.index("/model-react/{project_code}")


@pytest.mark.parametrize("path", [CERT, VALID])
def test_flag_header_session_and_ownership_are_enforced(trust, monkeypatch, path):
    record = trust.create("solar")
    assert trust.client.get(path, params={"project": record.project_code}).json()["code"] == "REQUEST_HEADER_REQUIRED"
    assert trust.client.get(path, params={"project": "nope"}, headers=HDR).status_code == 404
    assert trust.client.get(path, params={"project": ""}, headers=HDR).status_code == 404
    from fastapi.testclient import TestClient
    anonymous = TestClient(trust.client.app)
    assert anonymous.get(path, params={"project": record.project_code}, headers=HDR).status_code == 401
    monkeypatch.delenv("FINCO_MODEL_REACT_V1")
    assert trust.client.get(path, params={"project": record.project_code}, headers=HDR).json()["code"] == "REACT_POC_DISABLED"


@pytest.mark.parametrize("path,key", [(CERT, "certificate"), (VALID, "validation")])
def test_without_a_committed_run_the_evidence_is_unavailable_never_a_pass(trust, path, key):
    record = trust.create("solar")
    response = trust.client.get(path, params={"project": record.project_code}, headers=HDR)
    assert response.status_code == 200 and response.headers["cache-control"] == "private, no-store"
    section = response.json()[key]
    assert section["state"] == "UNAVAILABLE" and section.get("reason") == "COMMITTED_LAST_RUN_REQUIRED"
    assert section.get("passed") in (None, False)


def test_certificate_equals_the_canonical_builder_and_is_read_only(trust, monkeypatch):
    from app.ui.trust_pack import build_certificate_fragment
    from app.v2.react_trust import CERTIFICATE_KEYS
    record = trust.create("solar")
    run(trust, record)
    before = db_dump()
    response = trust.client.get(CERT, params={"project": record.project_code}, headers=HDR)
    assert response.status_code == 200
    section = response.json()["certificate"]
    assert set(section) == set(CERTIFICATE_KEYS)
    expected = build_certificate_fragment(record.user_id, record.project_id)
    if section["state"] == "AVAILABLE":
        assert section["snapshot_id"] == expected["snapshot_id"] and section["composite_hash"] == expected["composite_hash"]
        assert section["not_verify"] is True                                     # a certificate is provenance, never FINCO Verify
    else:
        assert section["reason"] == expected["reason"]                           # e.g. SIGNING_KEY_UNAVAILABLE stays an honest unavailable state
    classic = trust.client.get("/v2/workbook/trust/certificate", params={"project": record.project_code})
    assert (section["state"] == "AVAILABLE") == ("trust-pack-certificate-body" in classic.text)
    assert db_dump() == before


def test_validation_is_the_reference_regression_only_and_equals_the_canonical_builder(trust):
    from app.ui.trust_pack import build_validation_fragment
    record = trust.create("solar")
    run(trust, record)
    before = db_dump()
    response = trust.client.get(VALID, params={"project": record.project_code}, headers=HDR)
    assert response.status_code == 200
    section = response.json()["validation"]
    expected = build_validation_fragment(record.user_id, record.project_id)
    for key in ("state", "validation_state", "pass_count", "fail_count", "framework_passed", "product_reconciled", "gap_count"):
        assert section[key] == expected[key], key
    assert [g["name"] for g in section["gaps"]] == [g["name"] for g in expected["gaps"]]
    assert "REFERENCE REGRESSION" in section["authority"]
    assert db_dump() == before


def test_a_busy_model_executor_is_a_429_and_nothing_is_reported_as_passed(trust, monkeypatch):
    from app.runtime import model_execution as me
    record = trust.create("solar")
    run(trust, record)

    async def busy(*_a, **_k):
        raise me.ModelExecutionBusy()
    monkeypatch.setattr(me, "run_model_thread", busy)
    response = trust.client.get(VALID, params={"project": record.project_code}, headers=HDR)
    assert response.status_code == 429 and response.json()["code"] == "MODEL_BUSY" and response.headers["retry-after"] == "5"
    assert "validation" not in response.json()
