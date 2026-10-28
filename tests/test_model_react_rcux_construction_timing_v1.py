"""RC-UX (GAP-R17) — server-side construction timing: exact parity with the Legacy date library, the engine's representability rule, read-only."""
from __future__ import annotations

import json
import shutil
import sqlite3
import subprocess
from datetime import date, timedelta

import pytest

from app.v2 import react_construction_timing as T
from tests.test_model_react_ux040506_v1 import env, flag_on  # noqa: F401  (fixture)

PATH = "/v2/model-react/construction-timing"
NODE = shutil.which("node")


def db_dump():
    from app.persistence import db
    with sqlite3.connect(db.DB_PATH) as conn:
        return "\n".join(conn.iterdump())


def sample_dates():
    days = [date(2024, 1, 31), date(2024, 2, 29), date(2023, 2, 28), date(2030, 7, 1), date(2031, 8, 31), date(2029, 12, 31), date(2028, 2, 29),
            date(2041, 6, 30), date(2030, 3, 31), date(2030, 4, 30), date(2027, 10, 31), date(2032, 1, 1)]
    return days + [date(2030, 1, 1) + timedelta(days=37 * n) for n in range(40)]


@pytest.mark.skipif(NODE is None, reason="node is part of the frontend toolchain")
def test_add_months_equals_the_legacy_date_library_for_a_grid_of_month_end_cases():
    """The browser-side Legacy library (static/js/date_duration.js) is the reference; the server must give the same date for every case."""
    cases = [(d.isoformat(), n) for d in sample_dates() for n in (-120, -37, -18, -12, -6, -1, 1, 6, 12, 18, 24, 60, 120)]
    script = ("global.window={};global.document={addEventListener(){},querySelectorAll(){return[]}};require('./static/js/date_duration.js');"
              "const cases=JSON.parse(process.argv[1]);console.log(JSON.stringify(cases.map(([d,n])=>window.FincoDates.addMonths(d,n))));")
    out = subprocess.run([NODE, "-e", script, json.dumps(cases)], cwd=T.__file__.rsplit("/app/", 1)[0], capture_output=True, text=True, check=True)
    legacy = json.loads(out.stdout)
    mine = [T.add_months(date.fromisoformat(d), n).isoformat() for d, n in cases]
    assert mine == legacy and len(cases) > 500


def test_representability_is_the_engines_rule_and_suggestions_are_representable():
    assert T.representable(date(2030, 7, 1), 12)
    cod = date(2029, 2, 28)                       # 28 Feb minus 12 months = 28 Feb 2028; plus 12 months = 28 Feb 2029: reproducible
    assert T.representable(cod, 12)
    odd = date(2030, 2, 28)                       # 28 Feb 2030 - 1 month = 28 Jan; + 1 month = 28 Feb: reproducible
    assert T.representable(odd, 1)
    clash = date(2030, 3, 30)                     # 30 Mar - 1 month = 28 Feb (clamped); + 1 month = 28 Mar != 30 Mar
    assert not T.representable(clash, 1)
    got = T.suggestions(clash, 1)
    assert got and all(T.representable(date.fromisoformat(s), 1) for s in got)
    assert T.plan(start=date(2030, 2, 28), months=None, end=clash, saved_cod=None, saved_months=None)["ok"] is False


@pytest.mark.parametrize("start,months,ok,cod,derived,adjusted", [
    ("2029-07-01", 12, True, "2030-07-01", "2029-07-01", False),
    ("2029-01-31", 1, True, "2029-02-28", "2029-01-28", True),         # month-end adjusted: the model derives the start as 28 Jan
    ("2029-07-01", 0, False, None, None, None),
    ("2029-07-01", 121, False, None, None, None),
])
def test_plan_from_start_and_duration(start, months, ok, cod, derived, adjusted):
    result = T.plan(start=date.fromisoformat(start), months=months, end=None, saved_cod=None, saved_months=None)
    assert result["ok"] is ok
    if ok:
        assert (result["cod_date"], result["derived_start"], result["month_end_adjusted"]) == (cod, derived, adjusted)
        assert result["cells"] == [{"field_id": T.COD_FIELD, "value": cod}, {"field_id": T.MONTHS_FIELD, "value": str(months)}]


def test_plan_from_start_and_an_explicit_end_needs_a_whole_number_of_months():
    good = T.plan(start=date(2029, 7, 1), months=None, end=date(2031, 1, 1), saved_cod=None, saved_months=None)
    assert good["ok"] and good["construction_months"] == 18 and good["duration"] == "18 months"
    bad = T.plan(start=date(2029, 7, 1), months=None, end=date(2031, 1, 15), saved_cod=None, saved_months=None)
    assert not bad["ok"] and "whole number of months" in bad["message"]
    assert not T.plan(start=date(2029, 7, 1), months=None, end=date(2029, 6, 1), saved_cod=None, saved_months=None)["ok"]
    assert not T.plan(start=None, months=12, end=None, saved_cod=None, saved_months=None)["ok"]


def test_endpoint_reads_the_saved_timing_plans_and_writes_nothing(env, monkeypatch):
    flag_on(monkeypatch)
    record = env.create("solar")
    before = db_dump()
    body = env.client.get(PATH, params={"project": record.project_code}).json()
    assert body["ok"] and body["saved"]["cod_date"] and body["saved"]["construction_months"] and body["saved"]["engine_reproducible"] is True
    cod = date.fromisoformat(body["saved"]["cod_date"])
    assert body["saved"]["derived_start"] == T.add_months(cod, -body["saved"]["construction_months"]).isoformat()
    planned = env.client.get(PATH, params={"project": record.project_code, "start": "2029-07-01", "months": "24"}).json()["plan"]
    assert planned["ok"] and planned["cod_date"] == "2031-07-01" and planned["changed"] is True
    same = env.client.get(PATH, params={"project": record.project_code, "start": body["saved"]["derived_start"], "months": str(body["saved"]["construction_months"])}).json()["plan"]
    assert same["ok"] and same["changed"] is False                                   # the saved timing is recognised as unchanged
    assert env.client.get(PATH, params={"project": record.project_code, "start": "nonsense", "months": "12"}).json()["plan"]["ok"] is False
    assert db_dump() == before


def test_flag_session_and_ownership(env, monkeypatch):
    record = env.create("solar")
    assert env.client.get(PATH, params={"project": record.project_code}).json()["code"] == "REACT_POC_DISABLED"
    flag_on(monkeypatch)
    assert env.client.get(PATH, params={"project": "nope"}).status_code == 404
    assert env.stranger.get(PATH, params={"project": record.project_code}).status_code == 404
    from fastapi.testclient import TestClient
    assert TestClient(env.client.app).get(PATH, params={"project": record.project_code}).status_code == 401


def test_router_is_mounted_before_the_project_catch_all():
    from app.v2.router import router
    paths = [getattr(r, "path", "") for r in router.routes]
    assert paths.count("/model-react/construction-timing") == 1 and paths.index("/model-react/construction-timing") < paths.index("/model-react/{project_code}")
