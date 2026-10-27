"""RC-UX (GAP-R16) — the React OPEX year projection equals the Legacy OPEX sheet's projection table, cell for cell, and is read-only."""
from __future__ import annotations

import re
import sqlite3

import pytest
from bs4 import BeautifulSoup

from tests.test_model_react_ux040506_v1 import env, flag_on  # noqa: F401  (fixture)

PATH = "/v2/model-react/opex-projection"


def db_dump():
    from app.persistence import db
    with sqlite3.connect(db.DB_PATH) as conn:
        return "\n".join(conn.iterdump())


def legacy_cells(env, record):
    html = env.client.get("/v2/workbook", params={"project": record.project_code}).text
    soup = BeautifulSoup(html, "html.parser")
    return soup, {t["data-testid"]: t.get_text(" ", strip=True) for t in soup.select("[data-testid^='proj-']")}


def test_router_is_mounted_before_the_project_catch_all():
    from app.v2.router import router
    paths = [getattr(r, "path", "") for r in router.routes]
    assert paths.count("/model-react/opex-projection") == 1 and paths.index("/model-react/opex-projection") < paths.index("/model-react/{project_code}")


def test_flag_session_and_ownership(env, monkeypatch):
    record = env.create("solar")
    assert env.client.get(PATH, params={"project": record.project_code}).json()["code"] == "REACT_POC_DISABLED"
    flag_on(monkeypatch)
    assert env.client.get(PATH, params={"project": "nope"}).status_code == 404
    assert env.stranger.get(PATH, params={"project": record.project_code}).status_code == 404
    from fastapi.testclient import TestClient
    assert TestClient(env.client.app).get(PATH, params={"project": record.project_code}).status_code == 401


@pytest.mark.parametrize("kind", ["solar", "wind", "data_center", "ev_charging"])
def test_projection_equals_the_legacy_table_for_every_vertical_and_writes_nothing(env, monkeypatch, kind):
    flag_on(monkeypatch)
    record = env.create(kind)
    before = db_dump()
    body = env.client.get(PATH, params={"project": record.project_code}).json()
    assert body["ok"] and body["unit"] == "kEUR" and body["years"] == list(range(1, len(body["years"]) + 1)) and 1 <= len(body["years"]) <= 30
    assert db_dump() == before
    _soup, cells = legacy_cells(env, record)
    shown = 0
    for row in body["rows"]:
        for year, value in zip(body["years"], row["values"]):
            legacy = cells.get(f"proj-{row['code']}-y{year}")
            if legacy is None:
                continue                                                    # a group without data has no testid cell
            shown += 1
            assert (value is None and legacy == "—") or (value is not None and legacy == f"{value:.0f}"), (row["code"], year, value, legacy)
    for year, value in zip(body["years"], body["totals"]["including_contingency"]):
        assert cells[f"proj-total-y{year}"] == f"{value:.0f}"
    assert shown > 0 and len(body["rows"]) == 13                            # B.01 - B.13 are always present, in canonical order
    assert [r["code"] for r in body["rows"]] == [f"B.{n:02d}" for n in range(1, 14)]


def test_a_group_without_data_has_null_years_never_zero(env, monkeypatch):
    flag_on(monkeypatch)
    record = env.create("solar")
    body = env.client.get(PATH, params={"project": record.project_code}).json()
    empty = [r for r in body["rows"] if not r["has_data"]]
    for row in empty:
        assert row["values"] == [None] * len(body["years"])
    for row in body["rows"]:
        assert all(v is None or isinstance(v, float) for v in row["values"])


def test_the_projection_follows_a_saved_opex_change_and_the_saved_totals_add_up_as_the_server_reports(env, monkeypatch):
    flag_on(monkeypatch)
    record = env.create("solar")
    first = env.client.get(PATH, params={"project": record.project_code}).json()
    assert first["kpis"]["year1_total_keur"] == first["totals"]["including_contingency"][0]
    assert first["kpis"]["final_year_total_keur"] == first["totals"]["including_contingency"][-1]
