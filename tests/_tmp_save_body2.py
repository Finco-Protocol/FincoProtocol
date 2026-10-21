import os
os.environ["FINCO_MODEL_REACT_V1"] = "1"
import re
import pytest
from fastapi.testclient import TestClient

@pytest.fixture()
def env(tmp_path, monkeypatch):
    from app.persistence import db
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "sv2.db"))
    db.init_db()
    import main_web
    from app.auth import COOKIE_NAME, create_session_token
    from app.services.reference_seed_service import create_reference_seeded_project
    with TestClient(main_web.app) as client:
        client.cookies.set(COOKIE_NAME, create_session_token(user_id="sv2-user", username="admin"))
        rec = create_reference_seeded_project(user_id="sv2-user", template_source="generic_solar_reference",
                                              requested_name="SV2", capacity_mw=20)
        yield client, rec

def test_save(env):
    client, rec = env
    payload = client.get("/v2/model-react/inputs", params={"project": rec.project_code}).json()
    rows = [r for s in payload["grid"]["sections"] for c in s["categories"] for r in c["rows"]]
    cit = next(r for r in rows if r["field_id"] == "tax.assumptions.cit_rate_pct")
    print("CIT row:", {k: cit[k] for k in ("code", "field_id", "value", "editable", "unit")})
    save = payload["save"]
    body = {"project": rec.project_code, "csrf_token": save["csrf_token"],
        "cells": [{"field_id": "tax.assumptions.cit_rate_pct", "value": "21.5"}],
        "workbook_version": save["workbook_version"], "content_hash": save["content_hash"],
        "scenario_id": save["scenario_id"]}
    r = client.post("/v2/workbook/grid/save", json=body)
    print("SAVE:", r.status_code, r.text[:400])
