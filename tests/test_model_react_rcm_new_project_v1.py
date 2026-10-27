"""RC-M Lane A — contract tests for the React New Project wizard adapter.

The adapter is a thin JSON layer over the canonical reference-seeded creation service.  These tests prove
the authorization/CSRF order, bounded validation, the release posture per vertical, same-input parity with
the canonical service, idempotent double-submit and fail-closed unknown outcomes.  Synthetic data only; no
engine Run is started here.
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.persistence import db
from app.persistence.projects_repository import list_project_records

OWNER = "rcm-np-owner"
STRANGER = "rcm-np-stranger"
BASE = "/v2/model-react/new-project"


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "rcm_np.db"))
    db.init_db()
    from app.auth import COOKIE_NAME, create_session_token
    from app.runtime.model_execution import reset_model_executor_for_tests
    from app.v2.react_poc_router import router as poc_router
    from app.v2.react_workspace_router import router as workspace_router
    from app.v2.router import router as v2_router

    monkeypatch.setenv("FINCO_MODEL_REACT_V1", "1")
    app = FastAPI()
    app.include_router(v2_router, prefix="/v2")
    app.include_router(workspace_router, prefix="/v2")
    app.include_router(poc_router, prefix="/v2")
    with TestClient(app) as client:
        client.cookies.set(COOKIE_NAME, create_session_token(user_id=OWNER, username="admin"))
        stranger = TestClient(app)
        stranger.cookies.set(COOKIE_NAME, create_session_token(user_id=STRANGER, username="stranger"))
        anonymous = TestClient(app)

        def options(who=None):
            return (who or client).get(f"{BASE}/options").json()

        def body(opts, **over):
            data = {"request_id": opts["request_id"], "csrf_token": opts["csrf_token"], "name": "RCM Solar One",
                    "technology": "solar", "country": "XA", "capacity_mw": 20.0, "acknowledge_preview": False}
            data.update(over)
            return data

        def mine(who=OWNER):
            return [r for r in list_project_records(user_id=who, include_archived=True)]

        yield SimpleNamespace(client=client, stranger=stranger, anonymous=anonymous, options=options, body=body, mine=mine,
                              app=app)
    reset_model_executor_for_tests()


# ── options ────────────────────────────────────────────────────────────────

def test_options_require_a_session_and_the_react_flag(env, monkeypatch):
    assert env.anonymous.get(f"{BASE}/options").status_code == 401
    monkeypatch.setenv("FINCO_MODEL_REACT_V1", "0")
    assert env.client.get(f"{BASE}/options").status_code == 404


def test_options_describe_the_release_posture_from_the_canonical_registry(env):
    opts = env.options()
    techs = {t["key"]: t for t in opts["technologies"]}
    assert set(techs) == {"solar", "wind", "data_center", "ev_charging", "storage"}
    for key in ("solar", "wind"):
        assert techs[key]["creatable"] and techs[key]["pilot_tier"] == "PILOT_CANDIDATE"
        assert techs[key]["preview_acknowledgement_required"] is False
    for key in ("data_center", "ev_charging"):
        assert techs[key]["creatable"] and techs[key]["pilot_tier"] == "PREVIEW"
        assert techs[key]["preview_acknowledgement_required"] is True and techs[key]["limitations"]
    assert techs["storage"]["creatable"] is False and techs["storage"]["pilot_tier"] == "RELEASE_CLOSED"
    assert "template_source" not in techs["storage"]       # a closed vertical carries no creation handle
    assert uuid.UUID(opts["request_id"]).hex == opts["request_id"] and opts["csrf_token"]
    assert {c["code"] for c in opts["countries"]} >= {"XA", "XB", "XD", "XE", "DE"}
    assert env.options()["request_id"] != opts["request_id"]


def test_option_defaults_are_read_from_the_canonical_reference_factories(env):
    from app.project_factories import create_generic_solar_reference, create_generic_wind_reference

    techs = {t["key"]: t for t in env.options()["technologies"]}
    for key, factory in (("solar", create_generic_solar_reference), ("wind", create_generic_wind_reference)):
        pi = factory()
        assert techs[key]["default_capacity_mw"] == float(pi.technical.capacity_mw)
        assert techs[key]["timeline"] == {
            "financial_close": pi.info.financial_close.isoformat(), "construction_months": int(pi.info.construction_months),
            "cod_date": pi.info.cod_date.isoformat(), "horizon_years": int(pi.info.horizon_years)}


# ── preview (read-only validation) ─────────────────────────────────────────

@pytest.mark.parametrize("params,field", [
    ({"name": "", "technology": "solar", "country": "XA", "capacity_mw": "20"}, "name"),
    ({"name": "x" * 81, "technology": "solar", "country": "XA", "capacity_mw": "20"}, "name"),
    ({"name": "ok", "technology": "storage", "country": "XC", "capacity_mw": "20"}, "technology"),
    ({"name": "ok", "technology": "hydro", "country": "XA", "capacity_mw": "20"}, "technology"),
    ({"name": "ok", "technology": "solar", "country": "ZZ", "capacity_mw": "20"}, "country"),
    ({"name": "ok", "technology": "solar", "country": "XA", "capacity_mw": "0.05"}, "capacity_mw"),
    ({"name": "ok", "technology": "solar", "country": "XA", "capacity_mw": "10001"}, "capacity_mw"),
    ({"name": "ok", "technology": "solar", "country": "XA", "capacity_mw": "nan"}, "capacity_mw"),
    ({"name": "ok", "technology": "solar", "country": "XA", "capacity_mw": "abc"}, "capacity_mw"),
])
def test_preview_rejects_invalid_input_with_a_field_error_and_writes_nothing(env, params, field):
    before = len(env.mine())
    response = env.client.get(f"{BASE}/preview", params=params)
    assert response.status_code == 422 and response.json()["code"] == "VALIDATION_FAILED"
    assert field in {e["field"] for e in response.json()["errors"]}
    assert len(env.mine()) == before


def test_preview_effective_assumptions_equal_what_the_canonical_service_persists(env):
    from app.persistence.workspace_repository import get_workspace_state
    from app.services.reference_seed_service import create_reference_seeded_project

    for tech, template, country in (("solar", "generic_solar_reference", "XA"), ("wind", "generic_wind_reference", "XB")):
        preview = env.client.get(f"{BASE}/preview", params={"name": f"P {tech}", "technology": tech, "country": country,
                                                            "capacity_mw": "37.5"}).json()
        assert preview["ok"] and preview["writes_nothing"] is True
        direct = create_reference_seeded_project(user_id="rcm-np-oracle", template_source=template,
                                                 requested_name=f"Oracle {tech}", capacity_mw=37.5, country_market=country)
        snapshot = get_workspace_state("rcm-np-oracle", direct.project_id).draft_snapshot
        eff = preview["effective"]
        assert eff["total_capex_keur"] == pytest.approx(float(snapshot["total_capex_keur"]), rel=1e-9)
        assert eff["opex_y1_keur"] == pytest.approx(float(snapshot["opex_y1_keur"]), rel=1e-9)
        assert float(snapshot["capacity_mw"]) == eff["capacity_mw"] == 37.5
        assert snapshot["country_market"] == country and snapshot["tax_template"] == eff["tax_template"]
    assert not [r for r in env.mine()]                      # preview itself created nothing for the caller


# ── create: authorization, CSRF and release gates ──────────────────────────

def test_create_requires_a_session(env):
    opts = env.options()
    assert env.anonymous.post(f"{BASE}/create", json=env.body(opts)).status_code == 401
    assert env.mine() == []


@pytest.mark.parametrize("mutate", ["missing", "tampered", "wrong_request_id", "library_clone_token"])
def test_create_refuses_a_bad_csrf_token_and_writes_nothing(env, mutate):
    from app.workbook.financing_csrf import issue_token

    opts = env.options()
    token = {"missing": "", "tampered": opts["csrf_token"][:-4] + "0000",
             "library_clone_token": issue_token(None, "", purpose="library-clone-v1") or "x"}.get(mutate, opts["csrf_token"])
    other = env.options()
    request_id = other["request_id"] if mutate == "wrong_request_id" else opts["request_id"]
    response = env.client.post(f"{BASE}/create", json=env.body(opts, csrf_token=token, request_id=request_id))
    assert response.status_code == 403 and response.json()["code"] == "CSRF_INVALID"
    assert env.mine() == []


def test_a_token_issued_to_another_session_is_refused(env):
    stolen = env.options(env.stranger)
    response = env.client.post(f"{BASE}/create", json=env.body(stolen))
    assert response.status_code == 403 and env.mine() == [] and env.mine(STRANGER) == []


def test_malformed_and_extra_fields_are_refused_before_any_write(env):
    opts = env.options()
    assert env.client.post(f"{BASE}/create", content=b"not json").status_code == 400
    assert env.client.post(f"{BASE}/create", json=env.body(opts, template_source="generic_storage_reference")).status_code == 400
    assert env.client.post(f"{BASE}/create", json=env.body(opts, user_id="someone-else")).status_code == 400
    assert env.client.post(f"{BASE}/create", json={**env.body(opts), "capacity_mw": "twenty"}).status_code == 400
    assert env.mine() == [] and env.mine("someone-else") == []


def test_storage_and_unknown_technologies_cannot_be_created(env):
    for tech in ("storage", "bess", "hydro"):
        opts = env.options()
        response = env.client.post(f"{BASE}/create", json=env.body(opts, technology=tech, country="XC"))
        assert response.status_code == 422, tech
        assert "technology" in {e["field"] for e in response.json()["errors"]}
    assert env.mine() == []


@pytest.mark.parametrize("tech,country", [("data_center", "XD"), ("ev_charging", "XE")])
def test_preview_verticals_require_an_explicit_acknowledgement(env, tech, country):
    opts = env.options()
    refused = env.client.post(f"{BASE}/create", json=env.body(opts, technology=tech, country=country, capacity_mw=10.0))
    assert refused.status_code == 409 and refused.json()["code"] == "PREVIEW_ACKNOWLEDGEMENT_REQUIRED"
    assert env.mine() == []
    accepted = env.client.post(f"{BASE}/create", json=env.body(opts, technology=tech, country=country, capacity_mw=10.0,
                                                                acknowledge_preview=True))
    assert accepted.status_code == 200 and accepted.json()["ok"]
    assert len(env.mine()) == 1


# ── create: effect, ownership, idempotency ─────────────────────────────────

def test_create_makes_exactly_one_owned_unprotected_not_run_working_copy(env):
    opts = env.options()
    response = env.client.post(f"{BASE}/create", json=env.body(opts, name="  RCM   Solar One  "))
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] and payload["replayed"] is False and payload["idempotency_recorded"] is True
    assert payload["project"]["freshness"] == "NOT_RUN" and payload["project"]["name"] == "RCM Solar One"
    rows = env.mine()
    assert len(rows) == 1 and env.mine(STRANGER) == []
    record = rows[0]
    assert record.project_code == payload["project"]["code"] and record.user_id == OWNER
    assert getattr(record, "project_role", "working_copy") != "reference"
    assert not getattr(record, "is_protected", False) and not getattr(record, "is_readonly", False)
    assert record.replay_metadata["react_new_project"]["request_id"] == opts["request_id"]
    shell = env.client.get("/v2/model-react/workspace", params={"project": record.project_code}).json()
    assert shell["ok"] and shell["freshness"]["state"] == "NOT_RUN" and shell["freshness"]["has_runtime"] is False
    assert shell["project"]["protected_reference"] is False and shell["vertical"]["key"] == "solar"
    library = env.client.get("/v2/model-react/library").json()
    created = [p for p in library["projects"] if p["code"] == record.project_code]
    assert len(created) == 1 and created[0]["last_run"]["available"] is False
    assert not any(p["code"] == record.project_code for p in library["references"])


def test_stamping_preserves_the_working_copy_identity_and_the_seed_snapshot(env):
    from app.persistence.workspace_repository import get_workspace_state
    from app.services.reference_seed_service import create_reference_seeded_project

    oracle = create_reference_seeded_project(user_id="rcm-np-oracle", template_source="generic_wind_reference",
                                             requested_name="Oracle", capacity_mw=30.0, country_market="XB")
    opts = env.options()
    code = env.client.post(f"{BASE}/create", json=env.body(opts, technology="wind", country="XB", capacity_mw=30.0)).json()["project"]["code"]
    created = [r for r in env.mine() if r.project_code == code][0]
    for attr in ("project_role", "is_protected", "is_readonly", "project_origin", "template_source", "source_project_id", "project_type", "archived"):
        assert getattr(created, attr, None) == getattr(oracle, attr, None), attr
    a = get_workspace_state(OWNER, created.project_id).draft_snapshot
    b = get_workspace_state("rcm-np-oracle", oracle.project_id).draft_snapshot
    volatile = {"project_name", "active_project", "_reference_seed_profile"}
    assert {k: v for k, v in a.items() if k not in volatile} == {k: v for k, v in b.items() if k not in volatile}


def test_double_submit_and_replay_never_create_a_second_project(env):
    opts = env.options()
    first = env.client.post(f"{BASE}/create", json=env.body(opts)).json()
    second = env.client.post(f"{BASE}/create", json=env.body(opts)).json()
    third = env.client.post(f"{BASE}/create", json=env.body(opts, name="A different name")).json()
    assert first["replayed"] is False and second["replayed"] is True and third["replayed"] is True
    assert first["project"]["code"] == second["project"]["code"] == third["project"]["code"]
    assert len(env.mine()) == 1


def test_parallel_submits_of_one_request_create_one_project(env):
    from concurrent.futures import ThreadPoolExecutor

    opts = env.options()
    data = env.body(opts)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: env.client.post(f"{BASE}/create", json=data).json(), range(4)))
    assert all(r["ok"] for r in results) and len({r["project"]["code"] for r in results}) == 1
    assert sum(1 for r in results if not r["replayed"]) == 1 and len(env.mine()) == 1


def test_two_wizard_sessions_with_one_name_get_distinct_codes(env):
    codes = []
    for _ in range(2):
        opts = env.options()
        codes.append(env.client.post(f"{BASE}/create", json=env.body(opts)).json()["project"]["code"])
    assert len(set(codes)) == 2 and len(env.mine()) == 2


# ── unknown outcome / reconciliation ───────────────────────────────────────

def test_a_server_failure_is_reported_as_unknown_never_as_not_created(env, monkeypatch):
    import app.services.reference_seed_service as seed

    def boom(**_kw):
        raise RuntimeError("connection lost after a partial write")

    monkeypatch.setattr(seed, "create_reference_seeded_project", boom)
    opts = env.options()
    response = env.client.post(f"{BASE}/create", json=env.body(opts))
    assert response.status_code == 500 and response.json()["code"] == "CREATE_OUTCOME_UNKNOWN"
    assert "Result unknown" in response.json()["message"]
    status = env.client.get(f"{BASE}/status", params={"request_id": opts["request_id"]}).json()
    assert status == {"ok": True, "created": False, "conclusive": False}


def test_status_reconciles_a_created_request_and_is_owner_scoped(env):
    opts = env.options()
    code = env.client.post(f"{BASE}/create", json=env.body(opts)).json()["project"]["code"]
    mine = env.client.get(f"{BASE}/status", params={"request_id": opts["request_id"]}).json()
    assert mine["created"] and mine["conclusive"] and mine["project"]["code"] == code
    theirs = env.stranger.get(f"{BASE}/status", params={"request_id": opts["request_id"]}).json()
    assert theirs["created"] is False and "project" not in theirs
    assert env.client.get(f"{BASE}/status", params={"request_id": "not-hex"}).status_code == 422
    assert env.anonymous.get(f"{BASE}/status", params={"request_id": opts["request_id"]}).status_code == 401


def test_an_existing_clone_path_is_unchanged(env):
    """The new adapter does not touch the Library clone contract (same token purpose, same route)."""
    library = env.client.get("/v2/model-react/library").json()
    assert library["clone_url"] == "/library/clone/{source_project_id}" and library["csrf_token"]


@pytest.mark.parametrize("tech,template,country", [("solar", "generic_solar_reference", "XA"), ("wind", "generic_wind_reference", "XB")])
def test_wizard_created_and_directly_created_twins_have_identical_run_results(env, tech, template, country):
    """Same effective inputs, same runtime: the committed Run of the wizard project equals the twin's, metric for metric."""
    import re

    from app.services.reference_seed_service import create_reference_seeded_project
    from tests.run_clone_csrf import post_valid_csrf

    opts = env.options()
    code = env.client.post(f"{BASE}/create", json=env.body(opts, technology=tech, country=country, capacity_mw=33.0, name=f"Twin {tech}")).json()["project"]["code"]
    twin = create_reference_seeded_project(user_id=OWNER, template_source=template, requested_name=f"Twin direct {tech}", capacity_mw=33.0, country_market=country)
    for project in (code, twin.project_code):
        page = env.client.get("/v2/workbook", params={"project": project})
        tokens = {k: re.search(f'name="{k}" value="([^"]*)"', page.text).group(1) for k in ("content_hash", "workbook_version")}
        assert post_valid_csrf(env.client, "/v2/workbook/run", headers={"HX-Request": "true"}, data=dict(project=project, **tokens)).status_code == 200

    def metrics(project):
        results = env.client.get("/v2/model-react/statements", params={"project": project}).json()["results"]
        return {m["label"]: m["display"] for m in results["metrics"]}

    mine, theirs = metrics(code), metrics(twin.project_code)
    assert mine == theirs and mine["Project IRR"] != "Not available"
