"""WF-A test support: real committed Runs on the real application, driven only through its public routes.

Nothing here changes the application: every stress is applied through an existing, released input route
(workspace field update, CAPEX/OPEX contingency, F2 bankability configuration) and every result is the immutable
Run History entry the product itself committed.  Synthetic reference projects only.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

USER = "wfa-owner"
LAB = None   # set by make_lab: stress setups route through the lab client


def make_lab(tmp_path_factory, name: str = "wfa"):
    """Module-scoped lab: isolated database, authenticated client against the full application."""
    import pytest
    from app.persistence import db
    patch = pytest.MonkeyPatch()
    patch.setattr(db, "DB_PATH", str(tmp_path_factory.mktemp(name) / f"{name}.db"))
    db.init_db()
    from fastapi.testclient import TestClient
    from app.auth import COOKIE_NAME, create_session_token
    from main_web import app
    client = TestClient(app)
    client.cookies.set(COOKIE_NAME, create_session_token(user_id=USER, username="admin"))
    global LAB
    LAB = SimpleNamespace(client=client, patch=patch)
    return LAB


def project(kind: str, label: str = "", capacity_mw: float = 16):
    from app.services.reference_seed_service import create_reference_seeded_project
    return create_reference_seeded_project(user_id=USER, requested_name=f"WFA {kind} {label}".strip(),
                                           template_source=f"generic_{kind}_reference", capacity_mw=capacity_mw)


def tokens(record):
    from app.persistence.workspace_repository import get_workspace_state
    from app.workbook.service import WorkbookService
    from app.workbook.workbook_identity import assemble_consistent_for_get
    ws = get_workspace_state(USER, record.project_id)
    pis = WorkbookService.build_draft_input_set_from_workspace(ws)
    identity = assemble_consistent_for_get(user_id=USER, project_id=record.project_id, workbook_version=pis.workbook_version)
    return {"workbook_version": pis.workbook_version, "content_hash": identity.composite_hash}


def update_field(lab, record, field_id: str, value, sheet_id: str = "debt"):
    response = lab.client.post("/v2/workbook/update", headers={"HX-Request": "true"}, data={
        "project": record.project_code, "sheet_id": sheet_id, "field_id": field_id, "value": str(value), **tokens(record)})
    assert response.status_code == 200, response.text[:400]
    assert '"workbook-field-error"' not in response.headers.get("HX-Trigger", ""), (field_id, value, response.text[:600])
    return response


def set_contingency(lab, record, kind: str, pct: float):
    response = lab.client.post("/v2/capex/contingency", headers={"HX-Request": "true"}, data={
        "project": record.project_code, "kind": kind, "contingency_pct": str(pct), **tokens(record)})
    assert response.status_code in (200, 204, 303), response.text[:400]
    return response


def set_bankability(lab, record, config: dict):
    from app.workbook import bankability_config as bc
    return update_field(lab, record, bc.FIELD_ID, json.dumps({"version": 1, **config}))


def commit_run(lab, record):
    from app.persistence.run_history_repository import get_latest_history_entry
    from app.persistence.workspace_repository import get_workspace_state
    response = lab.client.post("/v2/workbook/run", headers={"HX-Request": "true"}, data={
        "project": record.project_code, **tokens(record)})
    assert response.status_code == 200, response.text[:600]
    ws = get_workspace_state(USER, record.project_id)
    assert ws.last_runtime_summary and not ws.dirty, "Run was not committed"
    return get_latest_history_entry(USER, record.project_id)
