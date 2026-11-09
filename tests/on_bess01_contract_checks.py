"""Explicit local BESS checks: opt in by filename; no automatic CI collection.

Synthetic inputs only. No activation constant is patched and no Run is called.
"""
import ast
import json
from pathlib import Path
import subprocess

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.services.bess_setup_preview import capability, preview
from domain.bess.contracts import BessInputError
from domain.bess.synthetic import example

BASE = "/v2/model-react/new-project"
ROOT = Path(__file__).resolve().parents[1]


def native():
    return {"version": 1, "configuration": example(), "variable_om_eur_per_dc_mwh": 0}


@pytest.fixture
def client(tmp_path, monkeypatch):
    from app.auth import COOKIE_NAME, create_session_token
    from app.persistence import db
    from app.v2.react_new_project import router
    from app.v2.bess_setup_router import router as bess_router
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "synthetic.db"))
    monkeypatch.setenv("FINCO_MODEL_REACT_V1", "1")
    db.init_db()
    app = FastAPI()
    app.include_router(router, prefix="/v2")
    app.include_router(bess_router, prefix="/v2")
    with TestClient(app) as c:
        c.cookies.set(COOKIE_NAME, create_session_token(user_id="synthetic-bess-owner", username="admin"))
        yield c


def payload(client):
    opts = client.get(BASE + "/bess-options").json()
    return {"request_id": opts["request_id"], "csrf_token": opts["csrf_token"],
            "native_json": json.dumps(native()), "edits": {}}


def test_capability_separates_reference_preview_and_financial_lifecycle():
    from app.workbook.bess_config import ACTIVATION_ENABLED, apply_config, admitted
    assert ACTIVATION_ENABLED is False
    cap = capability()
    assert cap["reference_exists"] and cap["preview_supported"]
    assert not any(cap[k] for k in ("create_supported", "save_supported", "run_supported"))
    assert cap["persistence"] == "BROWSER_MEMORY_ONLY"
    assert not admitted({"bess_native_config_json": json.dumps(native())})
    with pytest.raises(ValueError, match="BESS_FINANCIAL_ACTIVATION_RELEASE_CLOSED"):
        apply_config(None, json.dumps(native()))


def test_native_preview_derives_only_duration_and_preserves_document():
    raw = json.dumps(native())
    result = preview(raw, {"discharge_power_mw": "2", "usable_energy_mwh": "4", "installed_energy_mwh": "4"})
    assert result["battery"]["duration_hours"] == "2.0"
    assert result["persisted"] is False and result["financial_calculation_count"] == 0
    assert not result["physical_balance_verified"] and not result["financial_horizon_verified"]
    assert json.loads(raw) == native()


@pytest.mark.parametrize("field,value,code", [
    ("discharge_power_mw", "0", "BESS_NUMBER"),
    ("discharge_power_mw", "-1", "BESS_NUMBER"),
    ("usable_energy_mwh", "0", "BESS_NUMBER"),
    ("installed_energy_mwh", "-1", "BESS_NUMBER"),
    ("discharge_power_mw", "2 MW", "BESS_NUMBER"),
    ("charge_efficiency", "1.1", "BESS_NUMBER"),
    ("charge_efficiency", "0", "BESS_EFFICIENCY"),
    ("round_trip_efficiency", "0.1", "BESS_RTE"),
    ("cycle_loss_per_efc", "-0.1", "BESS_NUMBER"),
    ("calendar_loss_per_year", "true", "BESS_NUMBER"),
    ("minimum_soh", '"0.8"', "BESS_NUMBER"),
    ("usable_energy_mwh", "NaN", "BESS_NUMBER"),
])
def test_native_negative_edits(field, value, code):
    with pytest.raises(BessInputError, match=code):
        preview(json.dumps(native()), {field: value})


@pytest.mark.parametrize("fault,code", [
    ("duration", "BESS_DURATION"), ("units", "BESS_POLICY"),
    ("date", "BESS_HORIZON"), ("hour", "BESS_DISPATCH"),
    ("hybrid", "BESS_POLICY"), ("inventory", "BESS_INITIAL_SOC"),
])
def test_native_negative_documents(fault, code):
    doc = native()
    config = doc["configuration"]
    if fault == "duration": config["battery"]["duration_hours"] = 999
    elif fault == "units": config["price_unit"] = "USD_PER_MWH"
    elif fault == "date": config["end"] = config["start"]
    elif fault == "hour": config["dispatch"].pop()
    elif fault == "hybrid": config["technology"] = "SOLAR_BESS"
    elif fault == "inventory": config["battery"]["initial_energy_mwh"] = 999
    with pytest.raises(BessInputError, match=code):
        preview(json.dumps(doc), {})


def test_no_synthetic_or_partial_document_is_invented():
    with pytest.raises(BessInputError): preview("{}", {})
    with pytest.raises(BessInputError): preview(json.dumps(native()), {"cycles_per_day": "2"})
    with pytest.raises(BessInputError): preview('{"version":1,"version":1}', {})


def test_route_is_authenticated_csrf_bound_and_non_persisting(client):
    from app.persistence.db import get_cursor
    with get_cursor() as cur:
        before = list(cur.execute("SELECT * FROM projects").fetchall())
    body = payload(client)
    response = client.post(BASE + "/bess-preview", json=body)
    assert response.status_code == 200 and response.json()["ok"]
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["persisted"] is False
    assert not response.json()["capability"]["run_supported"]
    with get_cursor() as cur:
        assert list(cur.execute("SELECT * FROM projects").fetchall()) == before
    for bad in ({**body, "request_id": "f" * 32}, {**body, "csrf_token": "expired"}):
        assert client.post(BASE + "/bess-preview", json=bad).status_code == 403
    assert client.post(BASE + "/bess-preview", json=body, headers={"Origin": "https://foreign.invalid"}).status_code == 403
    from app.auth import COOKIE_NAME, create_session_token
    client.cookies.set(COOKIE_NAME, create_session_token(user_id="synthetic-other", username="admin"))
    assert client.post(BASE + "/bess-preview", json=body).status_code == 403
    client.cookies.clear()
    assert client.post(BASE + "/bess-preview", json=body).status_code == 401


def test_route_refuses_scope_injection_bad_units_and_unavailable_preview(client, monkeypatch):
    body = payload(client)
    assert client.post(BASE + "/bess-preview", json={**body, "project": "foreign", "scenario": "foreign"}).status_code == 422
    body["edits"] = {"discharge_power_mw": "1 MW"}
    response = client.post(BASE + "/bess-preview", json=body)
    assert response.status_code == 422 and response.json()["code"] == "BESS_NUMBER"
    body["edits"] = {}
    from app.v2 import bess_setup_router
    monkeypatch.setattr(bess_setup_router, "capability", lambda: {**capability(), "preview_supported": False})
    assert client.post(BASE + "/bess-preview", json=body).status_code == 409


def test_stream_bound_content_type_and_error_redaction(client):
    body = payload(client)
    assert client.post(BASE + "/bess-preview", content="x", headers={"Content-Type": "text/plain"}).status_code == 415
    assert client.post(BASE + "/bess-preview", content=b"x" * 2_100_001,
                       headers={"Content-Type": "application/json"}).status_code == 413
    body["native_json"] = json.dumps({"private-source-marker": 1})
    response = client.post(BASE + "/bess-preview", json=body)
    assert response.status_code == 422 and "private-source-marker" not in response.text


def test_storage_create_clone_and_seed_stay_closed(client):
    from app.services.project_library_service import CLONEABLE_TEMPLATE_SOURCES
    from app.services.reference_seed_service import CLONEABLE_SEED_TEMPLATE_SOURCES
    from app.v2.react_new_project import _creatable
    assert "generic_storage_reference" not in CLONEABLE_TEMPLATE_SOURCES | CLONEABLE_SEED_TEMPLATE_SOURCES
    assert _creatable("storage")[0] is False
    options = client.get(BASE + "/options").json()
    response = client.post(BASE + "/create", json={"request_id": options["request_id"], "csrf_token": options["csrf_token"],
        "name": "Synthetic Storage", "technology": "storage", "country": "XA", "capacity_mw": 1})
    assert response.status_code == 422 and response.json()["code"] == "VALIDATION_FAILED"


def test_existing_creation_and_financial_authorities_are_byte_identical():
    path = "app/v2/react_new_project.py"
    old = subprocess.check_output(["git", "show", "91e89bdd:" + path], cwd=ROOT).decode()
    new = (ROOT / path).read_text()
    def functions(raw):
        return {n.name: ast.dump(n, include_attributes=False) for n in ast.parse(raw).body
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    a, b = functions(old), functions(new)
    for name in a:
        if name != "react_new_project_options": assert a[name] == b[name], name
    changed = subprocess.check_output(["git", "diff", "--name-only", "91e89bdd", "--", "financial_engine", "finco_core",
        "domain", "app/services/project_library_service.py", "app/services/reference_seed_service.py",
        "app/workbook/bess_config.py", "app/product_capability.py"], cwd=ROOT).decode()
    assert changed == ""
