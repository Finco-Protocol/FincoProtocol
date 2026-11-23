"""FABLE-HTTP-02 (C1F-ERR-01 / C1F A-4, B-4, C-2) — bounded error contract.

Negative HTTP controls proving that rejected acquisition/investor saves:

- never echo raw interpreter text ("invalid literal for int()...",
  "Expecting property name...", "month must be in 1..12") to the client;
- map plain input validation to bounded 422 with stable codes;
- keep true CAS/source-state conflicts at 409 with their stable reason text;
- never persist state on a rejected mutation.
"""
from __future__ import annotations

import json
import re
import sqlite3
from contextlib import closing
from types import SimpleNamespace as NS

import pytest
from tests.test_model_decision_workspace_v2 import env  # noqa: F401  (reviewed investor harness fixture)

# ── acquisition save (M6 harness pattern from test_m6_institutional_acquisition_candidate) ──

# Internally coherent synthetic source evidence: production-shaped periods that extend beyond the closing date
# (2027-01-01) used by the forms below, so the C1F-C-1 date gate admits them and the injected save_case failure is reached.
_SYNTHETIC_SOURCE_EVIDENCE = {
    "currency": "EUR", "unit": "kEUR", "authority": "COVENANT_GATED_G2C_AND_C1_PROJECT_RETURN",
    "equity_periods": tuple(
        {"date": f"{year}-12-31", "net_legal_dividend_keur": 100.0, "legal_equity_contribution_keur": 0.0}
        for year in range(2027, 2032)),
}


@pytest.fixture()
def acq_env(tmp_path, monkeypatch):
    path = str(tmp_path / "cases.db")

    def get():
        conn = sqlite3.connect(path, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    import app.persistence.acquisition_repository as repo
    monkeypatch.setattr(repo, "get_connection", get)
    from app.persistence import db as persistence_db
    monkeypatch.setattr(persistence_db, "DB_PATH", path)
    with closing(get()) as c:
        c.execute("CREATE TABLE projects (project_id TEXT PRIMARY KEY,user_id TEXT,archived INTEGER,"
                  "is_protected INTEGER,is_readonly INTEGER)")
        c.execute("CREATE TABLE model_run_history (history_id TEXT PRIMARY KEY,user_id TEXT,"
                  "project_id TEXT,runtime_snapshot_id TEXT,composite_hash TEXT,last_runtime_scenario_id TEXT)")
        c.execute("INSERT INTO projects VALUES ('project-A','owner-A',0,0,0)")
        c.execute("INSERT INTO model_run_history VALUES ('h-1','owner-A','project-A','snapshot-123',?,NULL)",
                  ('c' * 64,))

    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.v2 import acquisition_router
    import app.v2.router as workbook_router
    from app.auth import create_session_token, COOKIE_NAME
    from app.model_v2.acquisition.csrf_binding import issue_token

    monkeypatch.setattr(workbook_router, "_get_current_user", lambda request: NS(user_id="owner-A"))
    monkeypatch.setattr(acquisition_router, "_record",
                        lambda request, project: (NS(user_id="owner-A"),
                                                  NS(project_id="project-A", project_code="project-A"),
                                                  "owner-A"))
    # The evidence gate is out of scope here: the negative controls target the
    # expected_revision parse and the error-class -> status mapping.
    monkeypatch.setattr(acquisition_router, "_history_entry",
                        lambda owner, record, history_id: NS(history_id="h-1", runtime_summary={},
                                                             runtime_snapshot_id="snapshot-123",
                                                             composite_hash="c" * 64,
                                                             last_runtime_scenario_id=None))
    monkeypatch.setattr(acquisition_router, "_run_evidence",
                        lambda entry, owner, project_id: (_SYNTHETIC_SOURCE_EVIDENCE, "AVAILABLE_SOURCE_FACTS"))
    import app.ui.protected_reference_service as protected_ref
    monkeypatch.setattr(protected_ref, "is_protected_reference", lambda record: False)
    app = FastAPI()
    app.include_router(acquisition_router.router, prefix="/v2")
    with TestClient(app) as client:
        session = create_session_token(user_id="owner-A", username="m6-test")
        client.cookies.set(COOKIE_NAME, session)
        request_stub = NS(cookies={COOKIE_NAME: session}, state=NS())
        token = issue_token(request_stub, "project-A")
        yield client, token


_INTERPRETER_FRAGMENTS = ("invalid literal", "Traceback", "Exception", "int() with base 10")


def test_acq_save_non_integer_expected_revision_is_bounded_422(acq_env):
    client, token = acq_env
    r = client.post("/v2/valuation-acquisition/save", data={
        "project": "project-A", "csrf_token": token, "history_id": "h-1",
        "case_id": "", "expected_revision": "abc"})
    assert r.status_code == 422
    payload = r.json()
    assert payload["error"] == "EXPECTED_REVISION_INVALID"
    for fragment in _INTERPRETER_FRAGMENTS:
        assert fragment not in r.text
    # Zero mutation: no case row exists.
    from app.persistence.acquisition_repository import list_cases
    assert list_cases(owner_id="owner-A", project_id="project-A") == []


def test_acq_save_non_finite_number_is_bounded_422(acq_env):
    client, token = acq_env
    form = {"project": "project-A", "csrf_token": token, "history_id": "h-1",
            "case_id": "", "expected_revision": "0", "closing_date": "2027-01-01",
            "purchase_price_keur": "nan"}
    r = client.post("/v2/valuation-acquisition/save", data=form)
    assert r.status_code == 422, r.status_code
    assert r.json()["error"] == "CASE_purchase_price_NONFINITE"
    for fragment in _INTERPRETER_FRAGMENTS:
        assert fragment not in r.text


def test_acq_save_bad_date_is_validation_422_not_conflict_409(acq_env):
    client, token = acq_env
    form = {"project": "project-A", "csrf_token": token, "history_id": "h-1",
            "case_id": "", "expected_revision": "0", "closing_date": "not-a-date"}
    r = client.post("/v2/valuation-acquisition/save", data=form)
    assert r.status_code == 422, r.status_code
    assert r.json()["error"] == "CASE_DATE_INVALID"


def test_acq_save_conflict_family_keeps_409(acq_env, monkeypatch):
    client, token = acq_env
    from app.persistence.acquisition_repository import AcquisitionCaseConflict

    def _conflict(owner_id, project_id, document, case_id, expected_revision):
        raise AcquisitionCaseConflict("CASE_REVISION_CONFLICT")

    import app.v2.acquisition_router as router_module
    monkeypatch.setattr(router_module, "save_case", _conflict)
    form = {"project": "project-A", "csrf_token": token, "history_id": "h-1",
            "case_id": "", "expected_revision": "0", "closing_date": "2027-01-01",
            "purchase_price_keur": "10", "transaction_costs_keur": "1",
            "buyer_discount_rate": "0.1", "target_buyer_irr": "0.12",
            "bid_lower_bound_keur": "5", "bid_upper_bound_keur": "15",
            "closing_adjustment_keur": "0"}
    r = client.post("/v2/valuation-acquisition/save", data=form)
    assert r.status_code == 409, r.status_code
    assert r.json()["error"] == "CASE_REVISION_CONFLICT"


# ── investor agreement save (reviewed env harness from test_investor_f4_workspace) ──

def test_investor_save_malformed_json_is_bounded_422(env):
    from tests.test_investor_f4_workspace import save, document, page
    record = env.create()
    assert save(env, record, document()).status_code == 200
    # Post the raw malformed payload exactly like a broken client would (the
    # reviewed save() helper json-encodes its argument).
    html = page(env, record).text
    r = env.client.post("/v2/workbook/investor/agreement", data=dict(
        project=record.project_code, action="save",
        content_hash=re.search(r'name="content_hash" value="([^"]*)"', html).group(1),
        csrf_token=re.search(r'name="csrf_token" value="([^"]*)"', html).group(1),
        agreement="{not json"), headers={"HX-Request": "true"})
    assert r.status_code == 422
    body = r.text
    assert "Expecting" not in body and "property name" not in body
    assert r.json()["error"] == "F4 agreement payload is not valid JSON"


def test_investor_save_bad_iso_date_is_bounded_422(env):
    from tests.test_investor_f4_workspace import save, document, page
    record = env.create()
    assert save(env, record, document()).status_code == 200
    doc = document()
    doc["contributions"][0]["cash_date"] = "2026-13-45"
    html = page(env, record).text
    r = env.client.post("/v2/workbook/investor/agreement", data=dict(
        project=record.project_code, action="save",
        content_hash=re.search(r'name="content_hash" value="([^"]*)"', html).group(1),
        csrf_token=re.search(r'name="csrf_token" value="([^"]*)"', html).group(1),
        agreement=json.dumps(doc)), headers={"HX-Request": "true"})
    assert r.status_code == 422
    body = r.text
    assert "month must be in" not in body
    assert r.json()["error"] == "Contribution date must be explicit ISO date"


def test_investor_save_conflict_keeps_409_with_stable_text(env):
    from tests.test_investor_f4_workspace import save, document, page
    record = env.create()
    assert save(env, record, document()).status_code == 200
    # Stale composite hash is a true CAS conflict -> 409 with the stable text.
    html = page(env, record).text
    token = re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)
    r = env.client.post("/v2/workbook/investor/agreement", data=dict(
        project=record.project_code, csrf_token=token, action="save",
        agreement=json.dumps(document()), content_hash="stale"))
    assert r.status_code == 409
    assert r.json()["error"] == "Working inputs or scenario changed; reload"


def test_acq_save_unexpected_programming_error_is_controlled_500(acq_env, monkeypatch, caplog):
    """An unexpected internal fault is NOT presented as user validation: the
    client gets a safe 500 body, nothing persists, and the server keeps full
    telemetry without embedding caller-supplied values."""
    import logging as _logging

    def _bug(owner_id, project_id, document, case_id, expected_revision):
        raise TypeError("internal contract violation (simulated programming error)")

    import app.v2.acquisition_router as router_module
    monkeypatch.setattr(router_module, "save_case", _bug)
    form = {"project": "project-A", "csrf_token": acq_env[1], "history_id": "h-1",
            "case_id": "", "expected_revision": "0", "closing_date": "2027-01-01",
            "purchase_price_keur": "10", "transaction_costs_keur": "1",
            "buyer_discount_rate": "0.1", "target_buyer_irr": "0.12",
            "bid_lower_bound_keur": "5", "bid_upper_bound_keur": "15",
            "closing_adjustment_keur": "0"}
    with caplog.at_level(_logging.ERROR, logger="app.v2.acquisition_router"):
        r = acq_env[0].post("/v2/valuation-acquisition/save", data=form)
    assert r.status_code == 500
    assert r.json()["error"] == "INTERNAL_ERROR"
    assert "internal contract violation" not in r.text
    from app.persistence.acquisition_repository import list_cases
    assert list_cases(owner_id="owner-A", project_id="project-A") == []
    recs = [rec for rec in caplog.records if "ACQUISITION_SAVE_UNEXPECTED_ERROR" in rec.getMessage()]
    assert recs, "full server-side telemetry is retained"
    assert "project-A" not in recs[0].getMessage(), "no caller-supplied identifiers in the log line"
    assert recs[0].exc_info is not None, "traceback retained for telemetry"


def test_investor_save_unexpected_programming_error_is_controlled_500(env, monkeypatch):
    from tests.test_investor_f4_workspace import save, document, page
    record = env.create()
    assert save(env, record, document()).status_code == 200
    import app.v2.investor_f4_router as router_module

    def _bug(*a, **k):
        raise TypeError("internal contract violation (simulated programming error)")

    monkeypatch.setattr(router_module, "save_agreement", _bug)
    html = page(env, record).text
    r = env.client.post("/v2/workbook/investor/agreement", data=dict(
        project=record.project_code, action="save",
        content_hash=re.search(r'name="content_hash" value="([^"]*)"', html).group(1),
        csrf_token=re.search(r'name="csrf_token" value="([^"]*)"', html).group(1),
        agreement=json.dumps(document())), headers={"HX-Request": "true"})
    assert r.status_code == 500
    assert r.json()["error"] == "INTERNAL_ERROR"


def test_acq_save_closing_outside_source_horizon_is_422_before_persistence(acq_env, monkeypatch):
    """C1F-C-1 gate: a closing date at/after the last source period is refused with 422 and save_case is never reached."""
    import app.v2.acquisition_router as router_module
    calls = []
    monkeypatch.setattr(router_module, "save_case", lambda *a, **k: calls.append(1))
    form = {"project": "project-A", "csrf_token": acq_env[1], "history_id": "h-1",
            "case_id": "", "expected_revision": "0", "closing_date": "2031-12-31",
            "purchase_price_keur": "10", "transaction_costs_keur": "1",
            "buyer_discount_rate": "0.1", "target_buyer_irr": "0.12",
            "bid_lower_bound_keur": "5", "bid_upper_bound_keur": "15",
            "closing_adjustment_keur": "0"}
    r = acq_env[0].post("/v2/valuation-acquisition/save", data=form)
    assert r.status_code == 422
    assert calls == []
    from app.persistence.acquisition_repository import list_cases
    assert list_cases(owner_id="owner-A", project_id="project-A") == []
