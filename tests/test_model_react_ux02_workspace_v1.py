"""UX-02 React Core Integration — contract tests for the integrated workspace surface.

Read-only projections over the canonical authorities (library / workspace / statements
/ inputs), with ALL mutations staying on the existing canonical routes.  Synthetic data
only; the engine runs through the canonical Run route exactly as the legacy tests do.
"""
from __future__ import annotations

import re
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.persistence import db
from app.persistence.workspace_repository import get_workspace_state

OWNER = "ux02-owner"
STRANGER = "ux02-stranger"

CIT = "tax.assumptions.cit_rate_pct"


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "ux02.db"))
    db.init_db()
    from app.auth import COOKIE_NAME, create_session_token
    from app.runtime.model_execution import reset_model_executor_for_tests
    from app.services.reference_seed_service import create_reference_seeded_project
    from fastapi import FastAPI
    from app.v2.grid_router import router as grid_router
    from app.v2.react_poc_router import router as poc_router
    from app.v2.react_workspace_router import router as workspace_router
    from app.v2.router import router as v2_router

    monkeypatch.delenv("FINCO_MODEL_REACT_V1", raising=False)
    app = FastAPI()
    app.include_router(v2_router, prefix="/v2")
    app.include_router(grid_router, prefix="/v2")
    # workspace routes BEFORE the PoC catch-all (same order as main_web)
    app.include_router(workspace_router, prefix="/v2")
    app.include_router(poc_router, prefix="/v2")
    with TestClient(app) as client:
        client.cookies.set(COOKIE_NAME, create_session_token(user_id=OWNER, username="admin"))
        stranger = TestClient(app)
        stranger.cookies.set(COOKIE_NAME, create_session_token(user_id=STRANGER, username="stranger"))

        def create(kind="solar", user=OWNER, name=None):
            return create_reference_seeded_project(
                user_id=user, requested_name=name or f"UX02 {kind}",
                template_source=f"generic_{kind}_reference", capacity_mw=16)

        yield SimpleNamespace(client=client, stranger=stranger, create=create)
    reset_model_executor_for_tests()


def flag_on(monkeypatch):
    monkeypatch.setenv("FINCO_MODEL_REACT_V1", "1")


def _run_canonical(env, code):
    page = env.client.get("/v2/workbook", params={"project": code})
    tokens = {k: re.search(f'name="{k}" value="([^"]*)"', page.text).group(1)
              for k in ("content_hash", "workbook_version")}
    response = env.client.post("/v2/workbook/run", headers={"HX-Request": "true"},
                               data=dict(project=code, **tokens))
    assert response.status_code == 200, response.text[:400]
    assert response.headers.get("X-Finco-Run-Outcome") != "FAILED"


# ───────────────────────────── flag / authorization ─────────────────────────────

@pytest.mark.parametrize("path", ["/v2/model-react/library", "/v2/model-react/workspace",
                                  "/v2/model-react/statements", "/v2/model-react/inputs"])
def test_endpoints_disabled_without_the_flag(env, path):
    response = env.client.get(path, params={"project": "x"})
    assert response.status_code == 404 and response.json()["code"] == "REACT_POC_DISABLED"


def test_library_lists_only_the_caller_projects_and_references(env):
    import os
    os.environ["FINCO_MODEL_REACT_V1"] = "1"
    try:
        own = env.create(kind="solar", name="Alpha Solar")
        env.create(kind="wind", user=STRANGER, name="Stranger Wind")
        payload = env.client.get("/v2/model-react/library").json()
        codes = [p["code"] for p in payload["projects"]]
        assert own.project_code in codes
        assert all(p["code"] != "stranger-wind" for p in payload["projects"]), \
            "another user's projects must never appear"
        assert any(r["protected_reference"] and r["reference"] for r in payload["references"]), \
            "reference models must be listed"
        assert payload["clone_url"] == "/library/clone/{source_project_id}"
    finally:
        os.environ.pop("FINCO_MODEL_REACT_V1", None)


def test_workspace_and_statements_require_authorization(env):
    import os
    os.environ["FINCO_MODEL_REACT_V1"] = "1"
    try:
        record = env.create()
        anonymous = TestClient(env.client.app if hasattr(env.client, "app") else None) if False else None
        foreign = env.stranger.get("/v2/model-react/workspace", params={"project": record.project_code})
        assert foreign.status_code == 404 and foreign.json()["code"] == "PROJECT_NOT_FOUND"
        foreign_statements = env.stranger.get("/v2/model-react/statements", params={"project": record.project_code})
        assert foreign_statements.status_code == 404
        foreign_inputs = env.stranger.get("/v2/model-react/inputs", params={"project": record.project_code})
        assert foreign_inputs.status_code == 404
    finally:
        os.environ.pop("FINCO_MODEL_REACT_V1", None)


# ───────────────────────────── statements: six destinations + parity ─────────────────────────────

def _bootstrapped_run(env, record):
    _run_canonical(env, record.project_code)
    payload = env.client.get("/v2/model-react/statements",
                             params={"project": record.project_code}).json()
    assert payload["ok"] and payload["state"] in ("CURRENT", "STALE"), payload.get("message")
    return payload


def test_six_statement_destinations_present_after_a_run(env):
    import os
    os.environ["FINCO_MODEL_REACT_V1"] = "1"
    try:
        record = env.create()
        payload = _bootstrapped_run(env, record)
        snapshot = payload["snapshot"]
        assert snapshot is not None
        assert [s["id"] for s in snapshot["sheets"]] == ["pl", "balance", "cashflow", "cfads", "debt", "sponsor"]
        assert snapshot["modelPeriods"] and snapshot["periodBands"]
        pl = snapshot["sheets"][0]
        assert pl["available"] and pl["rows"], "the P&L must carry the persisted rows"
        assert all(isinstance(r["model"], list) and r["model"] for r in pl["rows"])
        assert payload["status"]["dataOrigin"] == "caller-provided"
        assert payload["status"]["freshness"] in ("current", "stale")
    finally:
        os.environ.pop("FINCO_MODEL_REACT_V1", None)


def test_statement_values_match_the_persisted_run_evidence(env):
    import os
    os.environ["FINCO_MODEL_REACT_V1"] = "1"
    try:
        record = env.create()
        payload = _bootstrapped_run(env, record)
        from app.workbook.service import WorkbookService
        from app.workbook.runtime_projection import thaw_runtime_payload
        rr = WorkbookService.get_runtime_result(get_workspace_state(OWNER, record.project_id))
        persisted = thaw_runtime_payload(rr.financial_statements)["pnl"]["periods"]
        pl = payload["snapshot"]["sheets"][0]
        for row in pl["rows"]:
            if row["id"] in ("revenues_keur", "net_income_keur"):
                expected = [p.get(row["id"]) for p in persisted]
                assert len(row["model"]) == len(expected)
                for text, value in zip(row["model"], expected):
                    if value is None:
                        assert text == "—", "unavailable stays unavailable"
                    else:
                        assert text != "—"
                        assert float(text.replace(",", "")) == pytest.approx(float(value), abs=5e-3)
        # the legacy statements workspace must show the SAME state
        outputs = env.client.get("/v2/workbook/outputs", params={"project": record.project_code})
        legacy_state = re.search(r'data-testid="outputs-state" data-state="([A-Z_]+)"', outputs.text)
        assert legacy_state and legacy_state.group(1) == payload["state"]
    finally:
        os.environ.pop("FINCO_MODEL_REACT_V1", None)


def test_not_run_project_gets_no_snapshot_and_no_fabricated_values(env):
    import os
    os.environ["FINCO_MODEL_REACT_V1"] = "1"
    try:
        record = env.create()
        payload = env.client.get("/v2/model-react/statements", params={"project": record.project_code}).json()
        assert payload["state"] == "NOT_RUN"
        assert payload["snapshot"] is None
        assert payload["results"]["available"] is False
    finally:
        os.environ.pop("FINCO_MODEL_REACT_V1", None)


def test_results_metrics_carry_canonical_sources_or_are_absent(env):
    import os
    os.environ["FINCO_MODEL_REACT_V1"] = "1"
    try:
        record = env.create()
        payload = _bootstrapped_run(env, record)
        results = payload["results"]
        assert results["available"] is True
        for metric in results["metrics"]:
            if metric["available"]:
                assert metric["source"], "each displayed metric must name its canonical source"
        unavailable = [m for m in results["metrics"] if not m["available"]]
        for metric in unavailable:
            # the canonical returns projection marks unavailable metrics with the
            # literal NOT AVAILABLE display — never a fabricated number
            assert metric["display"] in ("—", "NOT AVAILABLE", "", None), \
                "unavailable metrics are never given values"
    finally:
        os.environ.pop("FINCO_MODEL_REACT_V1", None)


# ───────────────────────────── inputs grid ─────────────────────────────

def test_inputs_projection_exposes_the_canonical_grid_and_save_tokens(env):
    import os
    os.environ["FINCO_MODEL_REACT_V1"] = "1"
    try:
        record = env.create()
        payload = env.client.get("/v2/model-react/inputs", params={"project": record.project_code}).json()
        assert payload["ok"]
        assert payload["save"]["url"] == "/v2/workbook/grid/save"
        assert payload["save"]["csrf_token"] and payload["save"]["content_hash"]
        assert payload["save"]["max_cells"] == 50
        rows = [row for section in payload["grid"]["sections"]
                for category in section["categories"] for row in category["rows"]]
        assert rows, "the canonical projection must expose rows"
        assert all(row["field_id"] or not row["editable"] for row in rows)
        editable = [row for row in rows if row["editable"]]
        assert any(row["field_id"] == CIT for row in editable), "the CIT field must be grid-editable"
        read_only = [row for row in rows if not row["editable"]]
        assert all(row["reason"] for row in read_only), "read-only rows state their reason"
        assert payload["cost_line_boundary"]["capex_opex_editable"] is False
    finally:
        os.environ.pop("FINCO_MODEL_REACT_V1", None)


def test_grid_save_through_the_canonical_route_and_stale_classification(env):
    import os
    os.environ["FINCO_MODEL_REACT_V1"] = "1"
    try:
        record = env.create()
        inputs = env.client.get("/v2/model-react/inputs", params={"project": record.project_code}).json()
        response = env.client.post("/v2/workbook/grid/save", json={
            "project": record.project_code,
            "csrf_token": inputs["save"]["csrf_token"],
            "cells": [{"field_id": CIT, "value": "26.5"}],
            "workbook_version": inputs["save"]["workbook_version"],
            "content_hash": inputs["save"]["content_hash"],
            "scenario_id": inputs["save"]["scenario_id"],
        })
        assert response.status_code == 200
        out = response.json()
        assert out["ok"] and out["model_executed"] is False and out["run_state"] == "NOT_RUN"
        # a second Save with the SAME tokens is a stale conflict (no blind retry)
        replay = env.client.post("/v2/workbook/grid/save", json={
            "project": record.project_code,
            "csrf_token": inputs["save"]["csrf_token"],
            "cells": [{"field_id": CIT, "value": "27.5"}],
            "workbook_version": inputs["save"]["workbook_version"],
            "content_hash": inputs["save"]["content_hash"],
            "scenario_id": inputs["save"]["scenario_id"],
        })
        assert replay.status_code == 409 and replay.json()["reload"] is True
    finally:
        os.environ.pop("FINCO_MODEL_REACT_V1", None)


def test_protected_reference_inputs_are_read_only(env):
    import os
    os.environ["FINCO_MODEL_REACT_V1"] = "1"
    try:
        record = env.create()
        from app.persistence.db import get_connection

        with get_connection() as conn:
            conn.execute("UPDATE projects SET is_protected=1, is_readonly=1, project_role='reference' "
                         "WHERE project_id=?", (record.project_id,))
        payload = env.client.get("/v2/model-react/inputs", params={"project": record.project_code}).json()
        assert payload["project"]["protected_reference"] is True
        rows = [row for section in payload["grid"]["sections"]
                for category in section["categories"] for row in category["rows"]]
        assert all(row["editable"] is False for row in rows), "protected references expose no editable row"
    finally:
        os.environ.pop("FINCO_MODEL_REACT_V1", None)
