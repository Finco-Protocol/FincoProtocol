"""RC-M Lane C — contract tests for the React Investor & Sponsor adapter and the canonical agreement Save it fronts.

The adapter is read-only; the Save stays the canonical F4 route.  Proven: access order, terms/evidence/funding equal the Legacy
loader, the typed agreement saved through the canonical route is read back exactly, the CAS / validation / CSRF / ownership
refusals leave the Working Copy unchanged, Run-bound evidence equals the Legacy investor workspace for the same agreement, and SHL
facts are read-only.  Synthetic data only.
"""
from __future__ import annotations

import json
import re
from types import SimpleNamespace

import pytest
from bs4 import BeautifulSoup
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.persistence import db
from app.persistence.workspace_repository import get_workspace_state
from tests.run_clone_csrf import post_valid_csrf

OWNER, STRANGER = "rcm-inv-owner", "rcm-inv-stranger"
READ = "/v2/model-react/investors/agreement"
SAVE = "/v2/workbook/investor/agreement"


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "rcm_inv.db"))
    db.init_db()
    from app.auth import COOKIE_NAME, create_session_token
    from app.runtime.model_execution import reset_model_executor_for_tests
    from app.services.reference_seed_service import create_reference_seeded_project
    from app.v2.react_investors import router as investors_router
    from app.v2.react_poc_router import router as poc_router
    from app.v2.react_workspace_router import router as workspace_router
    from app.v2.router import router as v2_router

    monkeypatch.setenv("FINCO_MODEL_REACT_V1", "1")
    app = FastAPI()
    app.include_router(v2_router, prefix="/v2")
    app.include_router(workspace_router, prefix="/v2")
    app.include_router(investors_router, prefix="/v2")
    app.include_router(poc_router, prefix="/v2")
    with TestClient(app) as client:
        client.cookies.set(COOKIE_NAME, create_session_token(user_id=OWNER, username="admin"))
        stranger = TestClient(app)
        stranger.cookies.set(COOKIE_NAME, create_session_token(user_id=STRANGER, username="stranger"))
        anonymous = TestClient(app)

        def create(kind="solar", user=OWNER):
            return create_reference_seeded_project(user_id=user, template_source=f"generic_{kind}_reference", requested_name=f"Inv {kind}", capacity_mw=20.0)

        yield SimpleNamespace(client=client, stranger=stranger, anonymous=anonymous, create=create)
    reset_model_executor_for_tests()


def view(env, record, client=None):
    return (client or env.client).get(READ, params={"project": record.project_code})


def run_canonical(env, record):
    page = env.client.get("/v2/workbook", params={"project": record.project_code})
    toks = {k: re.search(f'name="{k}" value="([^"]*)"', page.text).group(1) for k in ("content_hash", "workbook_version")}
    response = post_valid_csrf(env.client, "/v2/workbook/run", headers={"HX-Request": "true"}, data=dict(project=record.project_code, **toks))
    assert response.status_code == 200, response.text[:300]


def agreement(funding, *, agreement_id="AGR-1", version=1, split=(0.6, 0.4)):
    investors = [{"investor_id": f"INV-{n}", "investment_class": "COMMON_EQUITY", "ownership_fraction": f, "commitment_keur": 1000.0} for n, f in zip("AB", split)]
    contributions = [{"investor_id": inv["investor_id"], "cash_date": row["date"], "amount_keur": round(row["paid_in_keur"] * inv["ownership_fraction"], 10)}
                     for row in funding for inv in investors]
    return {"schema_version": 1, "agreement_id": agreement_id, "version": version, "currency": "EUR", "unit": "kEUR", "policy": "RESIDUAL_ONLY",
            "investors": investors, "contributions": contributions}


def post_save(env, record, doc, *, action="save", client=None, **override):
    body = view(env, record, client).json() if "content_hash" not in override or "csrf_token" not in override else None
    data = {"project": record.project_code, "csrf_token": (body or {}).get("save", {}).get("csrf_token", ""),
            "content_hash": (body or {}).get("identity", {}).get("content_hash", ""), "agreement": json.dumps(doc), "action": action}
    data.update(override)
    return (client or env.client).post(SAVE, data=data, headers={"HX-Request": "true"})


# ── guards ─────────────────────────────────────────────────────────────────

def test_requires_flag_session_and_project_access(env, monkeypatch):
    record = env.create()
    assert env.anonymous.get(READ, params={"project": record.project_code}).status_code == 401
    assert view(env, record, env.stranger).status_code == 404
    assert env.client.get(READ, params={"project": "nope"}).status_code == 404
    monkeypatch.setenv("FINCO_MODEL_REACT_V1", "0")
    assert view(env, record).status_code == 404


def test_a_fresh_working_copy_has_no_agreement_and_sponsor_facts_are_read_only(env):
    record = env.create()
    body = view(env, record).json()
    assert body["ok"] and body["editable"] and body["terms"] is None and body["workflow"]["state"] == "NONE"
    assert body["evidence"] is None and body["unavailable"] and body["save"]["next_version"] == 1 and body["save"]["csrf_token"]
    labels = {r["label"] for r in body["sponsor"]["equity"]} | {r["label"] for r in body["sponsor"]["shl"]}
    assert {"Share capital", "SHL interest rate"} <= labels
    assert body["sponsor"]["repayment"] and body["sponsor"]["day_count"]
    assert "SHL" not in json.dumps(body["save"])                                       # no SHL control is writable
    assert "Preferences and carry" in body["not_released"] and "NAV / terminal valuation" in body["not_released"]


def test_reference_models_are_not_editable(env):
    from app.persistence.projects_repository import get_reference_by_template_source
    from app.services.project_library_service import ensure_reference_models

    ensure_reference_models()
    reference = get_reference_by_template_source("generic_solar_reference")
    body = view(env, reference).json()
    assert body["ok"] and body["editable"] is False


# ── Save through the canonical route, read back ────────────────────────────

def test_a_typed_agreement_saved_through_the_canonical_route_is_read_back_and_never_runs(env):
    record = env.create()
    run_canonical(env, record)
    funding = view(env, record).json()["funding"]
    assert funding and all(f["paid_in_keur"] > 0 for f in funding)
    doc = agreement(funding)
    before_snapshot = get_workspace_state(record.user_id, record.project_id).last_runtime_snapshot_id
    response = post_save(env, record, doc)
    assert response.status_code == 200, response.text[:300]
    body = view(env, record).json()
    assert body["terms"]["agreement_id"] == "AGR-1" and body["terms"]["version"] == 1
    assert [i["investor_id"] for i in body["terms"]["investors"]] == ["INV-A", "INV-B"]
    assert sum(i["ownership_fraction"] for i in body["terms"]["investors"]) == pytest.approx(1.0)
    assert body["workflow"]["state"] == "SAVED_NOT_RUN" and body["save"]["next_version"] == 2
    assert body["state"] == "STALE"
    assert get_workspace_state(record.user_id, record.project_id).last_runtime_snapshot_id == before_snapshot


def test_run_bound_evidence_equals_the_legacy_workspace_for_the_same_agreement(env):
    record = env.create()
    run_canonical(env, record)
    doc = agreement(view(env, record).json()["funding"])
    assert post_save(env, record, doc).status_code == 200
    run_canonical(env, record)
    body = view(env, record).json()
    assert body["workflow"]["state"] == "INCORPORATED" and body["state"] == "CURRENT"
    evidence = body["evidence"]
    assert [r["investor_id"] for r in evidence["investors"]] == ["INV-A", "INV-B"] and evidence["snapshot_id"]
    legacy = env.client.get("/v2/workbook/investor/agreement", params={"project": record.project_code})
    table = BeautifulSoup(legacy.text, "html.parser").select_one("[data-testid='f4-capital-accounts']")
    rows = [[td.get_text(" ", strip=True) for td in tr.find_all("td")] for tr in table.select("tbody tr")]
    assert len(rows) == 2
    for row, mine in zip(rows, evidence["investors"]):
        assert row[0] == mine["investor_id"] and row[1] == f"{mine['ownership_fraction'] * 100:.2f}%"
        assert row[2] == f"{mine['total_paid_in_keur']:,.2f}" and row[5] == f"{mine['residual_distributions_keur']:,.2f}"
        assert row[7] == (f"{mine['dpi']:.3f}x" if mine["dpi"] is not None else "UNAVAILABLE")
        assert row[8] == (f"{mine['xirr'] * 100:.2f}%" if mine["xirr"] is not None else mine["xirr_status"])
    assert sum(r["residual_distributions_keur"] for r in evidence["investors"]) > 0
    # ownership splits the same canonical receipts: 60/40 of the distributions
    a, b = evidence["investors"]
    assert a["residual_distributions_keur"] / (a["residual_distributions_keur"] + b["residual_distributions_keur"]) == pytest.approx(0.6, abs=1e-9)


def test_evidence_is_not_presented_after_the_agreement_changes_without_a_run(env):
    record = env.create()
    run_canonical(env, record)
    funding = view(env, record).json()["funding"]
    assert post_save(env, record, agreement(funding)).status_code == 200
    run_canonical(env, record)
    assert post_save(env, record, agreement(funding, version=2, split=(0.5, 0.5))).status_code == 200
    body = view(env, record).json()
    assert body["workflow"]["state"] == "INCORPORATED_STALE" or body["workflow"]["state"] == "SAVED_NOT_RUN"
    assert body["evidence"]["agreement"]["version"] == 1 and body["terms"]["version"] == 2      # the Run's recorded agreement is shown as such


# ── refusals leave everything unchanged ────────────────────────────────────

def snapshot(record):
    return dict(get_workspace_state(record.user_id, record.project_id).draft_snapshot)


@pytest.mark.parametrize("mutate,status", [
    (lambda doc: {**doc, "investors": [{**doc["investors"][0], "ownership_fraction": 0.5}, doc["investors"][1]]}, 422),     # ownership != 1
    (lambda doc: {**doc, "policy": "PREFERRED"}, 422),
    (lambda doc: {**doc, "currency": "USD"}, 422),
    (lambda doc: {**doc, "version": 2}, 409),                                                                             # version CAS
    (lambda doc: {**doc, "investors": [{**doc["investors"][0], "investment_class": "SHL"}, doc["investors"][1]]}, 422),
    (lambda doc: {**doc, "investors": [{**doc["investors"][0], "commitment_keur": 0.0}, doc["investors"][1]]}, 422),     # paid-in > commitment
    (lambda doc: {**doc, "investors": doc["investors"] + [doc["investors"][0]]}, 422),                                    # duplicate investor
    (lambda doc: {**doc, "extra": 1}, 422),
])
def test_invalid_or_conflicting_agreements_are_refused_without_a_write(env, mutate, status):
    record = env.create()
    run_canonical(env, record)
    doc = agreement(view(env, record).json()["funding"])
    before = snapshot(record)
    response = post_save(env, record, mutate(doc))
    assert response.status_code == status, response.text[:200]
    assert snapshot(record) == before and view(env, record).json()["terms"] is None


def test_csrf_stale_hash_and_cross_user_saves_are_refused(env):
    record = env.create()
    run_canonical(env, record)
    doc = agreement(view(env, record).json()["funding"])
    before = snapshot(record)
    assert post_save(env, record, doc, csrf_token="x", content_hash="x").status_code == 403
    token = view(env, record).json()["save"]["csrf_token"]
    stale = post_save(env, record, doc, csrf_token=token, content_hash="0" * 64)
    assert stale.status_code == 409
    stranger_token = view(env, record, env.stranger).status_code
    assert stranger_token == 404
    other = env.stranger.post(SAVE, data={"project": record.project_code, "csrf_token": token, "content_hash": "x", "agreement": json.dumps(doc), "action": "save"})
    assert other.status_code == 404
    assert snapshot(record) == before


def test_removing_the_working_agreement_returns_to_none(env):
    record = env.create()
    run_canonical(env, record)
    funding = view(env, record).json()["funding"]
    assert post_save(env, record, agreement(funding)).status_code == 200
    assert post_save(env, record, {}, action="remove").status_code == 200
    body = view(env, record).json()
    assert body["terms"] is None and body["workflow"]["state"] == "NONE"


def test_the_adapter_never_writes(env):
    record = env.create()
    before = (snapshot(record), get_workspace_state(record.user_id, record.project_id).dirty)
    for _ in range(3):
        assert view(env, record).status_code == 200
    ws = get_workspace_state(record.user_id, record.project_id)
    assert (dict(ws.draft_snapshot), ws.dirty) == before
