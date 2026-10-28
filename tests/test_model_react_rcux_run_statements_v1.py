"""RC-UX (Addendum A, R-HIST-STATEMENTS) — the React statements of an earlier Run equal the Legacy historical page cell for cell, come from the Run's own entry
(not the edited inputs), write nothing, and are isolated to the owner."""
from __future__ import annotations

import re
import sqlite3

import pytest

from tests.test_model_financing_f2 import run
from tests.test_sc34_statements_drilldown import OWNER, env, history  # noqa: F401  (fixture)

PATH = "/v2/model-react/analysis/run-statements"


@pytest.fixture
def renv(env, monkeypatch):  # noqa: F811
    from app.v2.react_run_statements import router
    monkeypatch.setenv("FINCO_MODEL_REACT_V1", "1")
    env.client.app.include_router(router, prefix="/v2")
    return env


def db_dump():
    from app.persistence import db
    with sqlite3.connect(db.DB_PATH) as conn:
        return "\n".join(conn.iterdump())


def test_router_is_mounted_before_the_project_catch_all():
    from app.v2.router import router
    paths = [getattr(r, "path", "") for r in router.routes]
    assert paths.count("/model-react/analysis/run-statements") == 1 and paths.index("/model-react/analysis/run-statements") < paths.index("/model-react/{project_code}")


def test_flag_session_ownership_and_input_validation(env, monkeypatch):  # noqa: F811
    from fastapi.testclient import TestClient
    from app.auth import COOKIE_NAME, create_session_token
    from app.v2.react_run_statements import router
    env.client.app.include_router(router, prefix="/v2")
    assert env.client.get(PATH, params={"project": "x", "history_id": "y"}).json()["code"] == "REACT_POC_DISABLED"
    monkeypatch.setenv("FINCO_MODEL_REACT_V1", "1")
    assert TestClient(env.client.app).get(PATH, params={"project": "x", "history_id": "y"}).status_code == 401
    record = env.create("solar")
    run(env, record)
    entry = history(record)[0]
    stranger = TestClient(env.client.app)
    stranger.cookies.set(COOKIE_NAME, create_session_token(user_id="other-sc34-user", username="admin"))
    assert stranger.get(PATH, params={"project": record.project_code, "history_id": entry.history_id}).status_code == 404
    assert env.client.get(PATH, params={"project": record.project_code}).status_code == 400
    assert env.client.get(PATH, params={"project": record.project_code, "history_id": "nope"}).json()["code"] == "RUN_NOT_FOUND"


@pytest.mark.parametrize("kind", ["solar", "wind", "data_center", "ev_charging"])
def test_the_json_equals_the_legacy_historical_page_cell_for_cell_and_writes_nothing(renv, kind):
    record = renv.create(kind)
    run(renv, record)
    entry = history(record)[0]
    before = db_dump()
    body = renv.client.get(PATH, params={"project": record.project_code, "history_id": entry.history_id}).json()
    assert db_dump() == before
    assert body["ok"] and body["statements"]["history_id"] == entry.history_id
    assert body["statements"]["status_dimensions"]["run_context"] == "HISTORICAL_RUN"
    html = renv.client.get("/v2/workbook/run-history/statements", params={"project": record.project_code, "history_id": entry.history_id}).text
    checked = 0
    for statement in body["statements"]["drilldown"]["statements"]:
        for basis, view in statement["views"].items():
            tree = re.search(r'data-st-tree="%s" data-st-basis="%s".*?</table>' % (statement["id"], basis), html, re.S).group(0)
            for node in view["nodes"]:
                if node["cells"] is None:
                    continue
                row = re.search(r'data-st-key="%s"[^>]*>.*?</tr>' % re.escape(node["key"]), tree, re.S).group(0)
                shown = [float(v) if v != "" else None for v in re.findall(r'data-raw="([^"]*)"', row)]
                assert shown == pytest.approx([c["v"] for c in node["cells"]], abs=1e-9, nan_ok=True) or shown == [c["v"] for c in node["cells"]], (statement["id"], basis, node["key"])
                checked += 1
    assert checked > 20


def test_an_earlier_run_shows_its_own_values_not_the_edited_inputs(renv):
    record = renv.create("solar")
    run(renv, record)
    first = history(record)[0]
    expected = [p["revenues_keur"] for p in first.financial_statements["pnl"]["periods"]]
    from tests.model_mutation_csrf import post_valid_mutation
    from tests.test_model_decision_workspace_v2 import tokens
    page = renv.client.get("/v2/workbook", params={"project": record.project_code}).text
    from app.persistence.workspace_repository import get_workspace_state
    ws = get_workspace_state(OWNER, record.project_id)
    tariff = float(ws.draft_snapshot.get("rev_ppa_base_tariff") or ws.draft_snapshot["tariff_eur_mwh"])
    post_valid_mutation(renv.client, "/v2/workbook/update", headers={"HX-Request": "true"},
                        data=dict(project=record.project_code, sheet_id="revenue", field_id="revenue.ppa.base_tariff", value=str(tariff * 1.5), **tokens(page)))
    run(renv, record)
    body = renv.client.get(PATH, params={"project": record.project_code, "history_id": first.history_id}).json()
    pnl = next(s for s in body["statements"]["drilldown"]["statements"] if s["id"] == "pnl")
    revenue = next(n for n in pnl["views"]["model"]["nodes"] if n["key"] == "revenues_keur")
    assert [c["v"] for c in revenue["cells"]] == pytest.approx(expected, abs=1e-9)
    assert body["statements"]["status_dimensions"]["input_freshness"] == "STALE"                  # the inputs have since changed; the values did not
