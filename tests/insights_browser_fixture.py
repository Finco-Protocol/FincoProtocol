"""Private real-Run fixture for isolated WF-REACT-3 browser acceptance.

The caller keeps this context open while serving ``app``. Cookies remain in
memory; only committed, token-free financial API evidence is written to disk.
"""
from __future__ import annotations

from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3

import pytest

from tests.test_model_decision_workspace_v2 import env
from tests.test_model_credit_decision_v3_real_runs import last
from tests.test_model_financing_f2 import run


@contextmanager
def browser_fixture(evidence_dir):
    """Yield ``(app, records, auth_cookie, db_snapshot)`` over private SQLite.

    ``records`` contains two distinct committed Solar scenarios and one Wind
    Run, each with its exact JSON oracle. ``auth_cookie`` must never be saved.
    The returned app exposes the canonical workflow and insights routes.
    """
    from app.auth import COOKIE_NAME
    from app.persistence import db
    from app.persistence.scenarios_repository import list_scenarios
    from app.v2.react_insights_router import router as insights_router

    evidence_dir = Path(evidence_dir)
    fixture_dir = evidence_dir / "local-fixture"
    fixture_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setenv("FINCO_MODEL_REACT_V1", "1")
    generator = env.__wrapped__(fixture_dir, monkeypatch)
    try:
        isolated = next(generator)
        isolated.client.app.include_router(insights_router, prefix="/v2")
        solar = isolated.create("solar")
        run(isolated, solar)
        solar_base = last(solar)
        response = isolated.client.post("/v2/workbook/scenarios/create", headers={"HX-Request": "true"},
            data={"project": solar.project_code, "scenario_name": "Browser revenue downside"})
        assert response.status_code == 200, response.text[:500]
        scenario = next(s for s in list_scenarios(user_id="decision-user", project_id=solar.project_id)
                        if s.scenario_name == "Browser revenue downside")
        response = isolated.client.post("/v2/workbook/scenarios/update-overrides", headers={"HX-Request": "true"},
            data={"project": solar.project_code, "scenario_id": scenario.scenario_id, "tariff_eur_mwh": "40"})
        assert response.status_code == 200, response.text[:500]
        run(isolated, solar)
        solar_down = last(solar)
        assert solar_down.last_runtime_scenario_id == scenario.scenario_id
        assert solar_base.last_runtime_scenario_id is None
        wind = isolated.create("wind")
        run(isolated, wind)
        wind_entry = last(wind)
        records = []
        for kind, project, entry in (("solar", solar, solar_base), ("solar", solar, solar_down),
                                     ("wind", wind, wind_entry)):
            response = isolated.client.get("/v2/model-react/insights",
                params={"project": project.project_code, "run": entry.history_id})
            assert response.status_code == 200, response.text[:1000]
            records.append({"kind": kind, "code": project.project_code,
                            "history_id": entry.history_id, "payload": response.json()})
        # Analytical JSON contains financial evidence and provenance only. Keep
        # the session cookie entirely separate from the serialized oracle.
        (evidence_dir / "canonical-api-oracle.json").write_text(
            json.dumps(records, indent=2, sort_keys=True), encoding="utf-8")
        cookie = {"name": COOKIE_NAME, "value": isolated.client.cookies.get(COOKIE_NAME)}
        assert cookie["value"]
        def db_snapshot():
            with sqlite3.connect(db.DB_PATH) as connection:
                return "\n".join(connection.iterdump())
        yield isolated.client.app, records, cookie, db_snapshot
    finally:
        try:
            next(generator, None)
        finally:
            monkeypatch.undo()
