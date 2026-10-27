"""RC-M Lane C — contract tests for the React Financing Studio adapter and the typed bankability Save path.

The adapter is read-only and adds no authority: its view is the Legacy Debt-sheet context; every write stays on the canonical per-field
writer.  Proven here: access order, equality with the canonical ``build_view`` oracle, that a typed configuration saved through the
canonical route is exactly what the studio reads back, that malformed values are rejected without persisting, that a calibrated period
schedule locks the scalar controls, and Sources & Uses of the committed Run.  Synthetic data only.
"""
from __future__ import annotations

import json
import re
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.persistence import db
from app.persistence.workspace_repository import get_workspace_state
from tests.model_mutation_csrf import post_valid_mutation
from tests.run_clone_csrf import post_valid_csrf

OWNER, STRANGER = "rcm-fin-owner", "rcm-fin-stranger"
STUDIO = "/v2/model-react/financing/studio"
FIELD = "debt.bankability.configuration"


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "rcm_fin.db"))
    db.init_db()
    from app.auth import COOKIE_NAME, create_session_token
    from app.runtime.model_execution import reset_model_executor_for_tests
    from app.services.reference_seed_service import create_reference_seeded_project
    from app.v2.react_financing import router as financing_router
    from app.v2.react_poc_router import router as poc_router
    from app.v2.react_workspace_router import router as workspace_router
    from app.v2.router import router as v2_router

    monkeypatch.setenv("FINCO_MODEL_REACT_V1", "1")
    app = FastAPI()
    app.include_router(v2_router, prefix="/v2")
    app.include_router(workspace_router, prefix="/v2")
    app.include_router(financing_router, prefix="/v2")
    app.include_router(poc_router, prefix="/v2")
    with TestClient(app) as client:
        client.cookies.set(COOKIE_NAME, create_session_token(user_id=OWNER, username="admin"))
        stranger = TestClient(app)
        stranger.cookies.set(COOKIE_NAME, create_session_token(user_id=STRANGER, username="stranger"))
        anonymous = TestClient(app)

        def create(kind="solar", user=OWNER, capacity=20.0):
            return create_reference_seeded_project(user_id=user, template_source=f"generic_{kind}_reference",
                                                   requested_name=f"Fin {kind}", capacity_mw=capacity)

        yield SimpleNamespace(client=client, stranger=stranger, anonymous=anonymous, create=create)
    reset_model_executor_for_tests()


def studio(env, record, client=None):
    return (client or env.client).get(STUDIO, params={"project": record.project_code})


def tokens(env, record):
    body = env.client.get("/v2/model-react/fields/debt", params={"project": record.project_code}).json()
    return body["save"]


def save_field(env, record, field_id, value, *, token_kind="csrf_token"):
    t = tokens(env, record)
    return env.client.post("/v2/workbook/update", follow_redirects=False, data={
        "project": record.project_code, "field_id": field_id, "value": value, "workbook_version": t["workbook_version"],
        "content_hash": t["content_hash"], "sheet_id": "debt", "csrf_token": t[token_kind]})


def run_canonical(env, record):
    page = env.client.get("/v2/workbook", params={"project": record.project_code})
    toks = {k: re.search(f'name="{k}" value="([^"]*)"', page.text).group(1) for k in ("content_hash", "workbook_version")}
    response = post_valid_csrf(env.client, "/v2/workbook/run", headers={"HX-Request": "true"}, data=dict(project=record.project_code, **toks))
    assert response.status_code == 200, response.text[:300]


def config(**over):
    return json.dumps({"version": 1, **over})


# ── guards ─────────────────────────────────────────────────────────────────

def test_requires_flag_session_and_project_access(env, monkeypatch):
    record = env.create()
    assert env.anonymous.get(STUDIO, params={"project": record.project_code}).status_code == 401
    assert studio(env, record, env.stranger).status_code == 404
    assert env.client.get(STUDIO, params={"project": "nope"}).status_code == 404
    monkeypatch.setenv("FINCO_MODEL_REACT_V1", "0")
    assert studio(env, record).status_code == 404


def test_reference_models_are_readable_but_not_editable(env):
    from app.persistence.projects_repository import get_reference_by_template_source
    from app.services.project_library_service import ensure_reference_models

    ensure_reference_models()
    reference = get_reference_by_template_source("generic_wind_reference")
    body = studio(env, reference).json()
    assert body["ok"] and body["editable"] is False and body["project"]["protected_reference"] is True


# ── view equals the canonical oracle ───────────────────────────────────────

def test_studio_bankability_view_equals_the_canonical_build_view(env):
    from app.persistence.projects_repository import resolve_accessible_project
    from app.v2.react_workspace_router import _jsonable
    from app.workbook.bankability_config import SNAPSHOT_KEY, build_view
    from app.workbook.service import WorkbookService

    record = env.create()
    body = studio(env, record).json()
    assert body["ok"] and body["editable"] and body["freshness"] == "NOT_RUN"
    _rec, owner = resolve_accessible_project(OWNER, record.project_code)
    ws = get_workspace_state(owner, record.project_id)
    pis = WorkbookService.build_draft_input_set_from_workspace(ws)
    oracle = build_view(pis.to_projectinputs(), pis.snapshot_origin.get(SNAPSHOT_KEY), project_type=pis.snapshot_origin.get("project_type"))
    shown = body["bankability"]
    assert shown["available"] and shown["periods"] == _jsonable(oracle["periods"])
    for key in ("config", "lender", "renewable", "mode", "day_count", "reserve_editable", "automatic_reserve", "fees", "scalar_target"):
        assert shown[key] == _jsonable(oracle[key]), key
    assert body["senior_pricing_mode"] == "FLAT" and body["senior_dscr_mode"] == "FLAT_SCALAR"
    assert body["multisenior"].get("active") is False and body["capital_stack"]["status"]


def test_studio_identity_matches_the_field_projection_cas_tokens(env):
    record = env.create()
    body = studio(env, record).json()
    save = tokens(env, record)
    assert body["identity"]["content_hash"] == save["content_hash"] and body["identity"]["workbook_version"] == save["workbook_version"]
    assert body["save"] == {"field_id": FIELD, "tokens_from": "/v2/model-react/fields/debt"}


# ── typed Save through the canonical writer, read back by the studio ───────

def periods_of(env, record):
    return studio(env, record).json()["bankability"]["periods"]


def test_a_typed_configuration_saved_through_the_canonical_route_is_what_the_studio_reads_back(env):
    record = env.create()
    n = len(periods_of(env, record))
    cfg = {"version": 1, "sizing_mode": "flat_dscr_sculpted", "lender_case": "P_50", "day_count": "act_365",
           "targets": [1.25] * n, "rates_pct": [5.75] * n, "fees": {"commitment_pct": 1.1, "structuring_pct": 0.9, "arrangement_pct": 0.2},
           "reserve": {"mode": "cash_fixed", "months": 0, "requirement_keur": 120.0, "commitment_keur": 0, "fee_pct": 0}}
    response = save_field(env, record, FIELD, json.dumps(cfg))
    assert response.status_code in (302, 303) and "v2_err" not in response.headers.get("location", ""), response.headers
    body = studio(env, record).json()
    assert body["bankability"]["config"] == cfg
    assert {p["target"] for p in body["bankability"]["periods"]} == {1.25} and {p["rate_pct"] for p in body["bankability"]["periods"]} == {5.75}
    assert body["bankability"]["day_count"] == "act_365" and body["bankability"]["lender"] == "P_50"
    # reset sends an empty value, exactly like the Legacy editor, and returns to the project's own authority
    assert save_field(env, record, FIELD, "").status_code in (302, 303)
    assert studio(env, record).json()["bankability"]["config"] == {}


def test_a_period_rate_schedule_locks_the_scalar_senior_controls(env):
    record = env.create()
    n = len(periods_of(env, record))
    assert save_field(env, record, FIELD, config(rates_pct=[6.0] * n)).status_code in (302, 303)
    fields = {f["field_id"]: f for f in env.client.get("/v2/model-react/fields/debt", params={"project": record.project_code}).json()["fields"]}
    rate = fields.get("debt.senior.interest_rate_pct")
    assert rate is not None
    refused = save_field(env, record, "debt.senior.interest_rate_pct", "4.5")
    assert refused.status_code in (302, 303) and "v2_err" in refused.headers.get("location", "")       # no scalar over a typed vector
    assert studio(env, record).json()["senior_pricing_mode"] == "WORKING_CONFIG"


@pytest.mark.parametrize("bad", [
    '{"version": 1, "fees": {"commitment_pct": 11, "structuring_pct": 1, "arrangement_pct": 0}}',
    '{"version": 1, "fees": {"commitment_pct": -1, "structuring_pct": 1, "arrangement_pct": 0}}',
    '{"version": 1, "fees": {"commitment_pct": 1, "structuring_pct": 1}}',
    '{"version": 1, "rates_pct": [21]}',
    '{"version": 1, "rates_pct": [NaN]}',
    '{"version": 1, "targets": [0.5]}',
    '{"version": 1, "targets": [], "target_scalar": 3.5}',
    '{"version": 1, "target_scalar": 1.3}',                                  # scalar needs the fallback selection (targets == [])
    '{"version": 1, "sizing_mode": "frozen"}',
    '{"version": 1, "lender_case": "P99"}',
    '{"version": 1, "day_count": "30_360"}',
    '{"version": 1, "reserve": {"mode": "dsrf", "months": 0, "requirement_keur": 100, "commitment_keur": 10, "fee_pct": 1}}',
    '{"version": 1, "reserve": {"mode": "none", "months": 0, "requirement_keur": 5, "commitment_keur": 0, "fee_pct": 0}}',
    '{"version": 2}', '{"version": 1, "extra": 1}', '[1, 2]', 'not json', '{"version": 1, "version": 1}',
])
def test_malformed_configurations_are_rejected_and_nothing_is_persisted(env, bad):
    record = env.create()
    before = dict(get_workspace_state(record.user_id, record.project_id).draft_snapshot)
    response = save_field(env, record, FIELD, bad)
    assert response.status_code in (302, 303) and "v2_err" in response.headers.get("location", ""), (bad, response.headers)
    assert dict(get_workspace_state(record.user_id, record.project_id).draft_snapshot) == before
    assert studio(env, record).json()["bankability"]["config"] == {}


def test_a_stale_cas_is_refused_without_overwriting(env):
    record = env.create()
    t = tokens(env, record)
    n = len(periods_of(env, record))
    assert save_field(env, record, FIELD, config(day_count="act_365")).status_code in (302, 303)
    stale = env.client.post("/v2/workbook/update", follow_redirects=False, data={
        "project": record.project_code, "field_id": FIELD, "value": config(day_count="act_360", rates_pct=[7.0] * n),
        "workbook_version": t["workbook_version"], "content_hash": t["content_hash"], "sheet_id": "debt", "csrf_token": t["csrf_token"]})
    assert "v2_err" in stale.headers.get("location", "")
    assert studio(env, record).json()["bankability"]["config"] == {"version": 1, "day_count": "act_365"}


def test_cross_user_and_missing_token_saves_fail_as_before(env):
    record = env.create()
    t = tokens(env, record)
    data = {"project": record.project_code, "field_id": FIELD, "value": config(day_count="act_365"), "workbook_version": t["workbook_version"],
            "content_hash": t["content_hash"], "sheet_id": "debt"}
    assert env.client.post("/v2/workbook/update", data={**data, "csrf_token": ""}, follow_redirects=False).status_code == 403
    assert env.stranger.post("/v2/workbook/update", data={**data, "csrf_token": t["csrf_token"]}, follow_redirects=False).status_code in (403, 404)
    assert studio(env, record).json()["bankability"]["config"] == {}


# ── Sources & Uses of the committed Run ────────────────────────────────────

def test_sources_and_uses_is_the_committed_run_and_is_labelled_stale_after_an_edit(env):
    record = env.create()
    before = studio(env, record).json()["sources_uses"]
    assert before["available"] and before["view"]["has_financing_evidence"] is False and before["view"]["freshness"] == "NOT_RUN"
    run_canonical(env, record)
    body = studio(env, record).json()
    view = body["sources_uses"]["view"]
    assert body["freshness"] == "CURRENT" and view["has_financing_evidence"] is True and view["freshness"] == "CURRENT"
    sources = {r["label"]: r["value"] for r in view["sources"]}
    uses = {r["label"]: r["value"] for r in view["uses"]}
    assert sources["Senior debt (actual sized)"] > 0 and uses["Hard project CAPEX"] > 0 and view["balance_status"]
    assert body["financing_evidence"]["metrics"][0]["display"].endswith("kEUR")
    # a deliberate edit makes the committed Run STALE; the view then says so instead of presenting it as current
    assert save_field(env, record, FIELD, config(day_count="act_365")).status_code in (302, 303)
    stale = studio(env, record).json()
    assert stale["freshness"] == "STALE" and stale["sources_uses"]["view"]["freshness"] == "STALE"
    assert {r["label"]: r["value"] for r in stale["sources_uses"]["view"]["sources"]} == sources     # still the prior Run's figures


def test_the_studio_never_writes(env):
    record = env.create()
    before = (dict(get_workspace_state(record.user_id, record.project_id).draft_snapshot), get_workspace_state(record.user_id, record.project_id).dirty)
    for _ in range(3):
        assert studio(env, record).status_code == 200
    after_ws = get_workspace_state(record.user_id, record.project_id)
    assert (dict(after_ws.draft_snapshot), after_ws.dirty) == before
