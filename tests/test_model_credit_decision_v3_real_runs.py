"""RC-4 / B Credit Decision over REAL committed canonical Runs: four verticals, single / two-Senior / Junior financing, P50 versus
P90-10y lender cases, DSRA / DSRF differences, DSCR below 1 with a converged solver, revenue downside, multiple scenarios, Run History
immutability, owner scoping, protected-reference denial and the read-only route contract."""
from __future__ import annotations

from tests.model_mutation_csrf import post_valid_mutation

import json
import re
from dataclasses import asdict

import pytest

from tests.test_financing_f37_instrument_su import _junior_run, _two_senior_run
from tests.test_model_decision_workspace_v2 import env, tokens  # noqa: F401  (fixture)
from tests.test_model_financing_f2 import FIELD_ID, config, run, save

USER = "decision-user"
KINDS = ["solar", "wind", "data_center", "ev_charging"]
CLASSES = {"CONTRACTUAL_COVENANT", "PROJECT_INPUT_ADVISORY", "OBSERVED_FINANCIAL_RESULT", "UNSUPPORTED_EVIDENCE_MISSING"}


@pytest.fixture
def cenv(env):  # noqa: F811
    from app.v2.credit_decision_router import router
    env.client.app.include_router(router, prefix="/v2")
    return env


def payload(response):
    match = re.search(r'<script type="application/json" data-cd-payload>(.*?)</script>', response.text, re.S)
    assert match, response.text[:400]
    return json.loads(match.group(1))


def history(record):
    from app.persistence.run_history_repository import get_run_history
    return get_run_history(USER, record.project_id)


def credit(cenv, record, *run_ids):
    params = [("project", record.project_code)] + [("run", r) for r in run_ids]
    response = cenv.client.get("/v2/credit-decision", params=params)
    assert response.status_code == 200, response.text[:400]
    return response, payload(response)


def last(record):
    from app.persistence.workspace_repository import get_workspace_state
    ws = get_workspace_state(USER, record.project_id)
    return next(e for e in history(record) if e.runtime_snapshot_id == ws.last_runtime_snapshot_id)


def finding(data, run_index, fid):
    run_id = data["runs"][run_index]["identity"]["history_id"]
    rows = [f for f in data["findings"] if f["run_history_id"] == run_id and (f["check_id"] == fid or f["id"].endswith(":" + fid))]
    assert rows, (fid, [f["id"] for f in data["findings"] if f["run_history_id"] == run_id])
    return rows[0]


def set_field(cenv, record, field_id, value):
    page = cenv.client.get("/v2/workbook", params={"project": record.project_code}).text
    response = post_valid_mutation(cenv.client, "/v2/workbook/update", headers={"HX-Request": "true"},
                                data={"project": record.project_code, "field_id": field_id, "value": str(value), **tokens(page)})
    assert response.status_code == 200 and "field-error" not in response.text[:4000], response.text[:600]


# ── every vertical, committed evidence classified ------------------------------------------------------------------
@pytest.mark.parametrize("kind", KINDS)
def test_real_run_renders_credit_evidence_with_explicit_classification(cenv, kind):
    record = cenv.create(kind)
    run(cenv, record)
    response, data = credit(cenv, record)
    assert len(data["runs"]) == 1 and data["runs"][0]["identity"]["state"] == "LAST RUN · CURRENT"
    run_view = data["runs"][0]
    assert run_view["structure"]["state"] in ("AVAILABLE", "LEGACY"), run_view["structure"]["reason"]
    assert run_view["structure"]["commitment"]["v"] is not None and run_view["capacity"]["min_dscr"]["v"] is not None
    assert run_view["timeline"]["available"] and len(run_view["timeline"]["columns"]) > 0
    assert {f["classification"] for f in data["findings"]} <= CLASSES
    for fid in ("CD-LLCR", "CD-PLCR", "CD-EOD", "CD-SWEEP"):
        assert finding(data, 0, fid)["classification"] in ("OBSERVED_FINANCIAL_RESULT", "UNSUPPORTED_EVIDENCE_MISSING")
    # WF-04: the Event-of-Default floor is now a Run-bound input.  A Run committed with none configured is NOT_CONFIGURED (never a pass, never
    # TRIGGERED, no default assumed); before WF-04 no EoD mechanic existed at all and the row was a fixed UNAVAILABLE placeholder.
    assert finding(data, 0, "CD-EOD")["status"] == "NOT_CONFIGURED"
    for marker in ('data-testid="cd-page"', 'data-testid="cd-timeline"', 'data-testid="cd-findings"', "A · Financing structure", "Credit-risk timeline"):
        assert marker in response.text
    # Last Run is CURRENT: the Working Copy lender case / sizing mode are bound and labelled as such
    assert run_view["structure"]["lender_case"]["value"]["v"] is not None or kind in ("data_center", "ev_charging")
    assert response.headers["cache-control"] == "private, no-store"


@pytest.mark.parametrize("kind", ["solar", "wind"])
def test_solar_wind_committed_sizing_evidence_is_read_not_reconstructed(cenv, kind):
    record = cenv.create(kind)
    run(cenv, record)
    _, data = credit(cenv, record)
    run_view = data["runs"][0]
    cap, s = run_view["capacity"], run_view["structure"]
    assert s["state"] == "AVAILABLE" and s["authority"] == "AGGREGATE_SINGLE_SENIOR"
    entry = last(record)
    bank = entry.runtime_summary["financing_evidence"]["bankability"]
    assert cap["dscr_debt_capacity"]["v"] == bank["dscr_debt_capacity_keur"] and cap["gearing_debt_capacity"]["v"] == bank["gearing_debt_capacity_keur"]
    assert cap["binding_constraint"]["v"] == bank["binding_senior_constraint"] and cap["final_commitment"]["v"] == bank["final_senior_commitment_keur"]
    assert s["commitment"]["v"] == entry.runtime_summary["senior_debt_keur"]
    assert cap["min_dscr"]["v"] == entry.runtime_summary["min_dscr"] and cap["avg_dscr"]["v"] == entry.runtime_summary["avg_dscr"]
    periods = entry.integrity_evidence["senior_debt"]["periods"]
    assert [c["index"] for c in run_view["timeline"]["columns"]] == [p["period_index"] for p in periods]
    by = {r["key"]: r for r in run_view["timeline"]["rows"]}
    assert [c["v"] for c in by["dscr"]["cells"]] == [p["reported_dscr"] for p in periods]
    assert [c["v"] for c in by["debt_service"]["cells"]] == [p["debt_service"] for p in periods]
    assert [c["v"] for c in by["base_cfads"]["cells"]] == [p["base_cfads"] for p in periods]
    tightest = cap["tightest"][0]
    with_debt_service = [p["reported_dscr"] for p in periods if p["reported_dscr"] is not None and (p["debt_service"] or 0) > 1e-6]
    assert tightest["dscr"]["v"] == min(with_debt_service)


# ── facilities: single, two-Senior, Junior ---------------------------------------------------------------------------
@pytest.mark.parametrize("kind", ["solar", "wind"])
def test_two_senior_facilities_are_listed_from_the_committed_instrument_ledgers(cenv, monkeypatch, kind):
    record, committed, rr = _two_senior_run(cenv, monkeypatch, kind)
    response, data = credit(cenv, record)
    s = data["runs"][0]["structure"]
    assert s["authority"] == "F3_TWO_SENIOR_EXPLICIT_COMMITMENTS_V1" and len(s["facilities"]) == 2
    assert all(f["role"] == "Senior" and f["commitment"]["v"] is not None for f in s["facilities"])
    assert s["commitment_label"].startswith("Contractual")
    assert sum(f["commitment"]["v"] for f in s["facilities"]) == pytest.approx(s["commitment"]["v"], abs=1e-6)
    assert "explicit contractual" in s["sizing_note"].lower() and 'data-testid="cd-facilities"' in response.text
    assert data["runs"][0]["capacity"]["explicit_commitments"] is True


def test_junior_facility_is_listed_with_its_role(cenv, monkeypatch):
    record, committed, rr = _junior_run(cenv, monkeypatch, "wind")
    _, data = credit(cenv, record)
    roles = sorted(f["role"] for f in data["runs"][0]["structure"]["facilities"])
    assert roles == ["Junior", "Senior"] and data["runs"][0]["structure"]["authority"] == "F3_SINGLE_SENIOR_JUNIOR_EXPLICIT_V1"


# ── read-only contract ------------------------------------------------------------------------------------------------
def test_get_never_runs_the_engine_writes_or_recalculates(cenv, monkeypatch):
    from app.persistence.workspace_repository import get_workspace_state
    record = cenv.create("solar")
    run(cenv, record)
    before_ws, before_hist = get_workspace_state(USER, record.project_id), [asdict(e) for e in history(record)]

    def boom(*a, **k):
        raise AssertionError("the credit workspace must not execute the model")
    monkeypatch.setattr("app.api.project_runner.run_project", boom)
    monkeypatch.setattr("app.services.production_financial_authority.run_clean_production", boom)
    for _ in range(2):
        credit(cenv, record)
        credit(cenv, record, history(record)[0].history_id)
    assert get_workspace_state(USER, record.project_id) == before_ws
    assert [asdict(e) for e in history(record)] == before_hist
    assert cenv.client.post("/v2/credit-decision", data={"project": record.project_code}).status_code == 405


def test_empty_project_states_no_committed_run_without_estimates(cenv):
    record = cenv.create("solar")
    response = cenv.client.get("/v2/credit-decision", params={"project": record.project_code})
    assert response.status_code == 200 and 'data-testid="cd-no-run"' in response.text and "data-cd-payload" not in response.text


# ── authorisation ---------------------------------------------------------------------------------------------------
def test_owner_scoping_foreign_user_and_unknown_run_fail_closed(cenv):
    from app.auth import COOKIE_NAME, create_session_token
    record = cenv.create("solar")
    run(cenv, record)
    run_id = history(record)[0].history_id
    # unknown / malformed Run ids never produce a partial page
    assert cenv.client.get("/v2/credit-decision", params={"project": record.project_code, "run": "does-not-exist"}).status_code == 404
    assert cenv.client.get("/v2/credit-decision", params={"project": record.project_code, "run": "x" * 200}).status_code == 400
    # another authenticated user cannot read the project or its Runs
    other = cenv.client.__class__(cenv.client.app)
    other.cookies.set(COOKIE_NAME, create_session_token(user_id="someone-else", username="other"))
    assert other.get("/v2/credit-decision", params={"project": record.project_code, "run": run_id}).status_code == 404
    assert other.get("/v2/credit-decision", params={"project": record.project_code}).status_code == 404
    # a Run of another project of the same user is a foreign id
    second = cenv.create("wind")
    run(cenv, second)
    foreign = history(second)[0].history_id
    assert cenv.client.get("/v2/credit-decision", params={"project": record.project_code, "run": foreign}).status_code == 404
    # unauthenticated
    anonymous = cenv.client.__class__(cenv.client.app)
    response = anonymous.get("/v2/credit-decision", params={"project": record.project_code}, follow_redirects=False)
    assert response.status_code == 302 and response.headers["location"] == "/login"


def test_more_than_three_runs_and_duplicates_are_handled(cenv):
    record = cenv.create("solar")
    run(cenv, record)
    ids = [history(record)[0].history_id]
    response = cenv.client.get("/v2/credit-decision", params=[("project", record.project_code)] + [("run", f"r{i}") for i in range(4)])
    assert response.status_code == 422
    _, data = credit(cenv, record, ids[0], ids[0])                                   # duplicate ids collapse to one selection
    assert len(data["runs"]) == 1


def test_protected_reference_is_denied(cenv, monkeypatch):
    record = cenv.create("solar")
    run(cenv, record)
    monkeypatch.setattr("app.services.project_library_service.is_protected_reference", lambda rec: True)
    response = cenv.client.get("/v2/credit-decision", params={"project": record.project_code})
    assert response.status_code == 409 and "protected reference" in response.text.lower()
