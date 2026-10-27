"""RC-UX A2 (Audit A GAP-R9) — React CAPEX spending-profile adapter over the REAL canonical planner.

The adapter is read-only: previews equal ``build_plan`` of the canonical contract, the single write is the EXISTING canonical save route
(posted with the token the adapter hands out), and a Legacy twin saved through the canonical service produces an identical Run.
"""
from __future__ import annotations

import json
import re
import sqlite3
from decimal import Decimal

import pytest

from tests.run_clone_csrf import post_valid_csrf
from tests.test_model_decision_workspace_v2 import env, tokens  # noqa: F401  (fixture)

OWNER = "decision-user"
READ = "/v2/model-react/capex/profiles"
PREVIEW = "/v2/model-react/capex/preview"
HDR = {"X-Finco-React-Request": "1"}


@pytest.fixture
def capex(env, monkeypatch):  # noqa: F811
    from app.v2.react_capex import router
    from app.v2.capex_router import capex_router
    monkeypatch.setenv("FINCO_MODEL_REACT_V1", "1")
    env.client.app.include_router(router, prefix="/v2")
    if not any(getattr(r, "path", "") == "/v2/capex/spending-profiles" for r in env.client.app.routes):
        env.client.app.include_router(capex_router, prefix="/v2/capex")
    return env


def read(env, record):
    response = env.client.get(READ, params={"project": record.project_code})
    assert response.status_code == 200, response.text[:600]
    return response.json()


def spec_of(rows):
    return json.dumps([[k, s, e, m] for k, s, e, m in rows], separators=(",", ":"))


def preview(env, record, rows, **extra):
    return env.client.get(PREVIEW, params={"project": record.project_code, "spec": spec_of(rows), **extra}, headers=HDR)


def db_dump():
    from app.persistence import db
    with sqlite3.connect(db.DB_PATH) as conn:
        return "\n".join(conn.iterdump())


def run(env, record):
    page = env.client.get("/v2/workbook", params={"project": record.project_code})
    response = post_valid_csrf(env.client, "/v2/workbook/run", headers={"HX-Request": "true"}, data={"project": record.project_code, **tokens(page.text)})
    assert response.status_code == 200
    from app.persistence.run_history_repository import get_run_history
    return get_run_history(OWNER, record.project_id)[0]


def test_router_is_mounted_before_the_project_catch_all():
    from app.v2.router import router
    paths = [getattr(route, "path", "") for route in router.routes]
    for path in ("/model-react/capex/profiles", "/model-react/capex/preview"):
        assert paths.count(path) == 1 and paths.index(path) < paths.index("/model-react/{project_code}")


@pytest.mark.parametrize("kind", ["solar", "wind", "data_center", "ev_charging"])
def test_projection_equals_the_canonical_catalogue_for_every_vertical(capex, kind):
    from app.capex_profiles.projection import catalogue
    from app.persistence.workspace_repository import get_workspace_state
    from app.workbook.service import WorkbookService
    record = capex.create(kind)
    data = read(capex, record)
    ws = get_workspace_state(OWNER, record.project_id)
    items, excluded = catalogue(WorkbookService.build_draft_input_set_from_workspace(ws), record.project_id)
    assert [i["item_key"] for i in data["items"]] == [i.item_key for i in items]
    assert [i["amount_keur"] for i in data["items"]] == [float(i.amount_keur) for i in items]
    assert [i["item_key"] for i in data["excluded"]] == [i.item_key for i in excluded]
    assert data["months"] > 0 and data["timeline"]["months"] == data["months"]
    assert data["shapes"] == ["UNIFORM", "FRONT_LOADED", "BACK_LOADED", "EXPLICIT", "MILESTONE"]
    assert data["edit"]["allowed"] is True and data["saved"]["rows"] == {} and data["saved"]["binding"]["saved"] is False
    assert data["semantics"]["save_runs_the_model"] is False and "not estimated" in data["semantics"]["idc_and_sources_uses"]
    from app.auth import validate_csrf_token
    assert validate_csrf_token(data["save"]["csrf_token"]) and data["save"]["url"] == "/v2/capex/spending-profiles/save"


def test_preview_equals_build_plan_exactly_and_reconciles_every_month(capex):
    from app.capex_profiles.contract import ProfileShape, ProfileSpec
    from app.capex_profiles.plan import build_plan
    from app.persistence.workspace_repository import get_workspace_state
    from app.v2.capex_profile_router import _context
    from app.workbook.service import WorkbookService
    record = capex.create("solar")
    data = read(capex, record)
    keys = [i["item_key"] for i in data["items"] if i["amount_keur"] > 0][:3]
    months = data["months"]
    explicit = ",".join([str(100 / months)] * months) if False else ",".join(["0"] * (months - 1) + ["100"])
    rows = [(keys[0], "FRONT_LOADED", "", ""), (keys[1], "EXPLICIT", explicit, ""), (keys[2], "MILESTONE", "", str(months))]
    response = preview(capex, record, rows)
    assert response.status_code == 200, response.text[:600]
    assert response.headers["cache-control"] == "private, no-store"
    plan = response.json()["plan"]
    ws = get_workspace_state(OWNER, record.project_id)
    ctx = _context(None, type("U", (), {"user_id": OWNER})(), record, ws, WorkbookService.build_draft_input_set_from_workspace(ws), OWNER)
    expected = build_plan(ctx["items"], [ProfileSpec(keys[0], ProfileShape.FRONT_LOADED), ProfileSpec(keys[1], ProfileShape.EXPLICIT,
                          tuple(explicit.split(","))), ProfileSpec(keys[2], ProfileShape.MILESTONE, milestone_month=months)], months, ctx["timeline"],
                          excluded_keys=frozenset(e.item_key for e in ctx["excluded"]), inactive_keys=ctx["inactive_keys"])
    assert plan["totals"]["profiled"] == f"{expected.profiled_total_keur:,.3f}"
    assert plan["totals"]["reconciles"] is True and plan["totals"]["unallocated"] == "0.000"
    assert [m["total"] for m in plan["months"]] == [f"{v:,.3f}" for v in expected.monthly_total_keur]
    assert [m["cumulative"] for m in plan["months"]] == [f"{v:,.3f}" for v in expected.monthly_cumulative_keur]
    assert plan["canonical"] is False and "PREVIEW ONLY" in plan["notice"]
    last = plan["months"][-1]
    assert Decimal(last["remaining"].replace(",", "")) == Decimal(0)                   # every profiled amount is fully allocated
    assert len(plan["months"]) == months and plan["item_order"] == keys


def test_invalid_rows_are_reported_individually_never_normalised(capex):
    record = capex.create("solar")
    data = read(capex, record)
    keys = [i["item_key"] for i in data["items"] if i["amount_keur"] > 0][:3]
    months = data["months"]
    bad_sum = ",".join(["1"] * months)                                                  # sums to `months` %, not 100 %
    rows = [(keys[0], "UNIFORM", "", ""), (keys[1], "EXPLICIT", bad_sum, ""), (keys[2], "EXPLICIT", "50,50", ""),
            ("NOT-A-REAL-ITEM", "UNIFORM", "", ""), (keys[0], "BACK_LOADED", "", "")]
    plan = preview(capex, record, rows).json()["plan"]
    by_key = {r["item_key"]: r for r in plan["rows"]}
    assert by_key[keys[1]]["status"] == "invalid" and by_key[keys[1]]["error_code"] == "CAPEX_PROFILE_WEIGHT_SUM_INVALID"
    assert by_key[keys[2]]["error_code"] == "CAPEX_PROFILE_PERIOD_COUNT_MISMATCH"
    assert by_key[keys[1]]["unallocated_display"] != "0.000"                            # an invalid amount is UNALLOCATED, not guessed
    assert plan["totals"]["reconciles"] is False
    assert any(e.startswith("CAPEX_PROFILE_UNKNOWN_ITEM") for e in plan["global_errors"])
    assert any(e.startswith("CAPEX_PROFILE_DUPLICATE_ITEM") for e in plan["global_errors"])
    assert [r for r in plan["rows"] if r["status"] == "valid"][0]["item_key"] == keys[0]   # one invalid row never hides the others


@pytest.mark.parametrize("params,status,code", [
    ({"spec": "not json"}, 422, "CAPEX_PROFILE_SPEC_INVALID_OR_TOO_LARGE"),
    ({"spec": "x" * 9000}, 422, "CAPEX_PROFILE_SPEC_INVALID_OR_TOO_LARGE"),
    ({"spec": '[["a","NOPE","",""]]'}, 422, "CAPEX_PROFILE_SHAPE_INVALID"),
    ({"spec": '[["a","UNIFORM"]]'}, 422, "CAPEX_PROFILE_SPEC_INVALID_OR_TOO_LARGE"),
    ({"spec": "[]", "extra": "1"}, 400, "INVALID_QUERY"),
])
def test_malformed_drafts_are_typed_refusals(capex, params, status, code):
    record = capex.create("solar")
    response = capex.client.get(PREVIEW, params={"project": record.project_code, **params}, headers=HDR)
    assert response.status_code == status and response.json()["code"] == code


def test_preview_requires_the_react_header_and_reads_never_write_or_run(capex, monkeypatch):
    record = capex.create("solar")
    keys = [i["item_key"] for i in read(capex, record)["items"]][:1]
    assert capex.client.get(PREVIEW, params={"project": record.project_code, "spec": "[]"}).status_code == 400
    read(capex, record)
    before = db_dump()

    def forbidden(*args, **kwargs):
        raise AssertionError("CAPEX adapter attempted model execution")

    monkeypatch.setattr("app.api.project_runner.run_project", forbidden)
    monkeypatch.setattr("app.services.production_financial_authority.run_clean_production", forbidden)
    for _ in range(2):
        read(capex, record)
        assert preview(capex, record, [(keys[0], "FRONT_LOADED", "", "")]).status_code == 200
    assert db_dump() == before
    for path in (READ, PREVIEW):
        assert capex.client.post(path, data={"project": record.project_code}).status_code == 405


def test_security_foreign_unauthenticated_flag_and_scenario_read_only(capex, monkeypatch):
    from app.auth import COOKIE_NAME, create_session_token
    record = capex.create("solar")
    for who in (None, "foreign-user"):
        with capex.client.__class__(capex.client.app) as client:
            if who:
                client.cookies.set(COOKIE_NAME, create_session_token(user_id=who, username="other"))
            for path, headers in ((READ, {}), (PREVIEW, HDR)):
                response = client.get(path, params={"project": record.project_code, "spec": "[]"}, headers=headers, follow_redirects=False)
                assert response.status_code == (404 if who else 401)
    assert capex.client.get(READ, params={"project": "no-such-project"}).status_code == 404
    monkeypatch.delenv("FINCO_MODEL_REACT_V1")
    assert capex.client.get(READ, params={"project": record.project_code}).status_code == 404


def test_save_through_the_canonical_route_binds_then_runs_identically_to_the_legacy_twin(capex):
    """Audit A GAP-R9 acceptance: React-saved FRONT_LOADED profile -> IDC and Total Uses equal a Legacy-saved twin; Save never runs."""
    from app.capex_profiles import config
    from app.capex_profiles.service import save_profiles
    from app.persistence.run_history_repository import get_run_history
    from app.persistence.workspace_repository import get_workspace_state
    react, legacy = capex.create("solar"), capex.create("solar")
    base = run(capex, react)
    assert run(capex, legacy) is not None
    data = read(capex, react)                       # the tokens are read AFTER the Run, as the React editor does on every reload
    keys = [i["item_key"] for i in data["items"] if i["amount_keur"] > 0]
    assert keys
    # React: post the canonical form with the adapter's token + content hash
    fields = {"project": react.project_code, "csrf_token": data["save"]["csrf_token"], "content_hash": data["save"]["content_hash"], "action": "save"}
    for index, key in enumerate(keys):
        fields.update({f"key_{index}": key, f"shape_{index}": "FRONT_LOADED", f"explicit_{index}": "", f"milestone_{index}": ""})
    response = capex.client.post("/v2/capex/spending-profiles/save", data=fields, follow_redirects=False)
    assert response.status_code == 303 and "saved=saved" in response.headers["location"]
    assert [h.history_id for h in get_run_history(OWNER, react.project_id)] == [base.history_id]       # Save never runs
    after = read(capex, react)
    assert after["saved"]["binding"]["bound"] is True and set(after["saved"]["rows"]) == set(keys)
    assert all(r["shape"] == "FRONT_LOADED" for r in after["saved"]["rows"].values())
    assert after["last_run"]["freshness"] == "STALE"                                                    # the Last Run is now STALE
    # Legacy twin: the canonical service the Legacy page uses
    ws = get_workspace_state(OWNER, legacy.project_id)
    doc = json.dumps({"version": 1, "profiles": [{"item_key": k, "shape": "FRONT_LOADED", "explicit_percent": [], "milestone_month": None} for k in keys]})
    from app.workbook.registry import WORKBOOK
    from app.workbook.workbook_identity import assemble_consistent_for_get
    save_profiles(owner=OWNER, project_id=legacy.project_id, expected_hash=assemble_consistent_for_get(OWNER, legacy.project_id, WORKBOOK.version).composite_hash,
                  expected_scenario_id=ws.active_scenario_id or "", raw=doc)
    a, b = run(capex, react), run(capex, legacy)
    assert a.history_id != base.history_id
    su = lambda e: e.runtime_summary["financing_evidence"]["sources_uses"]  # noqa: E731
    assert su(a)["capitalized_idc_keur"] == su(b)["capitalized_idc_keur"] != su(base)["capitalized_idc_keur"]
    assert su(a)["total_uses_keur"] == su(b)["total_uses_keur"]
    assert a.runtime_summary["project_irr"] == b.runtime_summary["project_irr"]
    assert a.debt_schedule["periods"][0] == b.debt_schedule["periods"][0] or a.debt_schedule["summary"] == b.debt_schedule["summary"]
    final = read(capex, react)
    assert final["last_run"]["freshness"] == "CURRENT" and final["last_run"]["used_profile"] is True
    assert final["last_run"]["sources_uses"]["capitalized_idc_keur"]["value"] == su(a)["capitalized_idc_keur"]
    assert config.SNAPSHOT_KEY in get_workspace_state(OWNER, react.project_id).draft_snapshot


def test_stale_content_hash_is_refused_by_the_canonical_route_and_the_draft_is_kept(capex):
    record = capex.create("solar")
    data = read(capex, record)
    key = data["items"][0]["item_key"]
    fields = {"project": record.project_code, "csrf_token": data["save"]["csrf_token"], "content_hash": "0" * 64, "action": "save",
              "key_0": key, "shape_0": "UNIFORM", "explicit_0": "", "milestone_0": ""}
    response = capex.client.post("/v2/capex/spending-profiles/save", data=fields, follow_redirects=False)
    assert response.status_code == 409
    assert re.search(r'data-testid="profile-error"[^>]*>Request rejected: ([A-Z_]+)', response.text)
    assert read(capex, record)["saved"]["rows"] == {}
    fields["csrf_token"] = "forged"
    assert capex.client.post("/v2/capex/spending-profiles/save", data=fields, follow_redirects=False).status_code == 403
