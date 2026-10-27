"""RC-UX (GAP-R14) — React Compare Projects over the REAL persisted Last Runs: parity with the Legacy page, honest unavailability, no templates."""
from __future__ import annotations

import sqlite3

import pytest
from bs4 import BeautifulSoup

from tests.test_model_decision_workspace_v2 import env  # noqa: F401  (fixture)
from tests.test_model_financing_f2 import run

PATH = "/v2/model-react/compare-projects"


@pytest.fixture
def cmp(env, monkeypatch):  # noqa: F811
    from app.v2.react_compare_projects import router
    monkeypatch.setenv("FINCO_MODEL_REACT_V1", "1")
    env.client.app.include_router(router, prefix="/v2")
    return env


def db_dump():
    from app.persistence import db
    with sqlite3.connect(db.DB_PATH) as conn:
        return "\n".join(conn.iterdump())


def get(env, *codes, **extra):
    return env.client.get(PATH, params=[("code", c) for c in codes] + list(extra.items()))


def test_router_is_mounted_before_the_project_catch_all():
    from app.v2.router import router
    paths = [getattr(r, "path", "") for r in router.routes]
    assert paths.count("/model-react/compare-projects") == 1 and paths.index("/model-react/compare-projects") < paths.index("/model-react/{project_code}")


def test_flag_and_session_are_required(env, monkeypatch):
    from app.v2.react_compare_projects import router
    env.client.app.include_router(router, prefix="/v2")
    assert env.client.get(PATH).json()["code"] == "REACT_POC_DISABLED"
    monkeypatch.setenv("FINCO_MODEL_REACT_V1", "1")
    from fastapi.testclient import TestClient
    assert TestClient(env.client.app).get(PATH).status_code == 401


def test_a_run_project_and_an_unrun_project_are_compared_honestly_and_the_page_matches_legacy(cmp):
    ran = cmp.create("solar")
    unrun = cmp.create("wind")
    run(cmp, ran)
    before = db_dump()
    body = get(cmp, ran.project_code, unrun.project_code).json()
    assert db_dump() == before                                                       # zero writes
    assert body["ok"] and [c["code"] for c in body["columns"]] == [ran.project_code, unrun.project_code]
    first, second = body["columns"]
    assert first["runnable"] is True and first["run_state"] in ("CURRENT", "STALE") and first["run_identity"] and first["run_url"].endswith("#results")
    assert second["runnable"] is False and second["metrics"] == {} and second["run_url"] is None        # not calculated, not zero
    assert first["metrics"]["project_irr"] not in ("", None) and first["metrics"]["min_dscr"]
    legacy = cmp.client.get("/v2/compare-projects", params={"projects": f"{ran.project_code},{unrun.project_code}"})
    soup = BeautifulSoup(legacy.text, "html.parser")
    table = {tr.find("td").get_text(strip=True): [td.get_text(strip=True) for td in tr.find_all("td")[1:]] for tr in soup.select("tr") if tr.find("td")}
    labels = {"total_capex_keur": "Total CAPEX (kEUR)", "capex_per_mw": "CAPEX / MW", "total_revenue_keur": "Operating Revenue (kEUR)",
              "total_ebitda_keur": "EBITDA (kEUR)", "project_irr": "Project IRR", "equity_irr": "Pure Equity IRR", "total_sponsor_xirr": "Total Sponsor IRR",
              "senior_debt_keur": "Senior Debt (kEUR)", "gearing_cap_pct": "Gearing", "min_dscr": "Minimum DSCR", "min_llcr": "Min LLCR"}
    checked = 0
    for key, label in labels.items():
        row = next((v for k, v in table.items() if k.startswith(label)), None)
        assert row is not None, label
        for column, legacy_cell in zip(body["columns"], row):
            assert column["metrics"].get(key, "—") == legacy_cell, (key, column["code"], column["metrics"].get(key), legacy_cell)
            checked += 1
    assert checked >= 20
    assert [c["ebitda_margin"] for c in body["columns"]] == next(v for k, v in table.items() if k.startswith("EBITDA margin"))
    assert [c["ran_at"] for c in body["columns"]] == next(v for k, v in table.items() if k == "Last Run")


def test_a_template_and_an_unknown_code_are_left_out_not_compared(cmp):
    from app.persistence.projects_repository import get_reference_by_template_source
    from app.services.project_library_service import ensure_reference_models
    ensure_reference_models()
    template = get_reference_by_template_source("generic_solar_reference")
    mine = cmp.create("solar")
    body = get(cmp, template.project_code, "nope", mine.project_code).json()
    assert [c["code"] for c in body["columns"]] == [mine.project_code]
    assert {(x["code"], x["reason"]) for x in body["left_out"]} == {(template.project_code, "TEMPLATE"), ("nope", "NOT_FOUND")}
    assert template.project_code not in {p["code"] for p in body["picker"]} and mine.project_code in {p["code"] for p in body["picker"]}


def test_at_most_five_projects_are_compared_and_duplicates_count_once(cmp):
    records = [cmp.create("solar") for i in range(6)]
    codes = [r.project_code for r in records]
    body = get(cmp, codes[0], codes[0], *codes[1:]).json()
    assert [c["code"] for c in body["columns"]] == codes[:5] and body["max_projects"] == 5
    assert body["left_out"] == [{"code": codes[5], "reason": "LIMIT"}]


def test_sorting_ranks_unavailable_last_and_never_as_zero(cmp):
    a, b, c = cmp.create("solar"), cmp.create("solar"), cmp.create("solar")
    run(cmp, a)
    body = get(cmp, b.project_code, a.project_code, c.project_code, sort="project_irr").json()
    assert body["columns"][0]["code"] == a.project_code and body["sort"] == "project_irr"          # the only project with a value first, the others last
    assert get(cmp, a.project_code, sort="not_a_metric").json()["sort"] == ""                         # an unknown key is ignored, not trusted
    tech = get(cmp, a.project_code, b.project_code, technology="Wind").json()
    assert tech["columns"] == [] and "Solar" in tech["technologies"]
