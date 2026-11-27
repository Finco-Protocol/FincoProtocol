"""FINCO 35 Batch 2 — Slice F: Save/Run consistency and truthfulness.

Covers:
- E2E-01 / C1-Q-05: C07 zero gearing fails closed with typed ZERO_SENIOR_GEARING_NOT_SUPPORTED;
  C08 1% gearing stays SHL maturity refusal; horizon <= debt tenor gets DEBT_TENOR_EXCEEDS_HORIZON;
  no internal exception leak, prior Last Run preserved.
- C1-Q-02: single-field project_setup.technical.horizon_years edit that invalidates an existing
  saved PPA contract book is rejected atomically with no DB mutation.
- C1F-A-1: batch/import category-scalar updates (capex.C.grid_connection, opex.lines.insurance)
  targeting categories owned by active cost lines are refused with COST_CATEGORY_LINE_OWNED
  (no pretend Applied, no STALE flag, no silent no-op); non-cost scalars still apply cleanly.
"""
from __future__ import annotations

import json
import re
import uuid
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth import COOKIE_NAME, create_session_token
from app.persistence import db
from app.persistence.run_history_repository import get_run_history
from app.persistence.workspace_repository import get_workspace_state
from app.services.reference_seed_service import create_reference_seeded_project
from app.v2.react_workspace_router import router as react_workspace_router
from app.v2.router import router as v2_router
from tests.model_react_test_helpers import react_workbook_tokens
from app.workbook.financing_csrf import issue_token
from app.workbook.registry import WORKBOOK
from app.workbook.update_service import (
    BatchApplyError,
    WorkbookUpdateService,
    find_line_owned_cost_fields,
)
from tests.model_mutation_csrf import post_valid_mutation

def _setup(tmp_path, name: str, kind: str = "solar"):
    user = "test-slicef-user"
    db.DB_PATH = str(tmp_path / f"{name}.db")
    db.init_db()
    app = FastAPI()
    app.include_router(v2_router, prefix="/v2")
    app.include_router(react_workspace_router, prefix="/v2")
    client = TestClient(app)
    client.__enter__()
    client.cookies.set(COOKIE_NAME, create_session_token(user_id=user, username="admin"))
    rec = create_reference_seeded_project(
        user_id=user,
        requested_name=f"SliceF {name}",
        template_source=f"generic_{kind}_reference",
        capacity_mw=16,
    )
    return user, client, rec


def _tokens(client, project_code: str) -> dict[str, str]:
    return react_workbook_tokens(client, project_code)


def _edit(client, project_code: str, field_id: str, value: str):
    return post_valid_mutation(
        client,
        "/v2/workbook/update",
        headers={"HX-Request": "true"},
        data={"project": project_code, "field_id": field_id, "value": str(value), **_tokens(client, project_code)},
    )


def _run(client, rec):
    req = SimpleNamespace(cookies=client.cookies, state=SimpleNamespace())
    resp = client.post(
        "/v2/workbook/run",
        headers={"Accept": "application/json"},
        data={
            "project": rec.project_code,
            **_tokens(client, rec.project_code),
            "csrf_token": issue_token(req, rec.project_code, purpose="workbook-run-v1"),
            "run_intent_id": str(uuid.uuid4()),
        },
        follow_redirects=False,
    )
    return resp.status_code, resp.json()


def test_c07_zero_gearing_and_c08_and_horizon_tenor_typed_refusals(tmp_path):
    user, client, rec = _setup(tmp_path, "c07_c08", "solar")
    try:
        # Baseline Run succeeds -> establishes prior Last Run
        st0, b0 = _run(client, rec)
        assert st0 == 200 and b0["outcome"] == "COMMITTED"
        assert len(get_run_history(user, rec.project_id)) == 1

        # C07 / E2E-01: 0% senior gearing -> refused at Save with ZERO_SENIOR_GEARING_NOT_SUPPORTED, prior Run preserved
        r = _edit(client, rec.project_code, "debt.senior.gearing_pct", "0")
        assert "ZERO_SENIOR_GEARING_NOT_SUPPORTED" in r.text
        assert "Traceback" not in r.text
        assert len(get_run_history(user, rec.project_id)) == 1

        # C08: 1% senior gearing -> SHL unpaid at maturity refusal at Run (distinct from zero gearing)
        r = _edit(client, rec.project_code, "debt.senior.gearing_pct", "1")
        assert r.status_code == 200
        _, b_c08 = _run(client, rec)
        assert b_c08["outcome"] == "FAILED"
        assert "shareholder loan unpaid" in b_c08["message"].lower()
        assert len(get_run_history(user, rec.project_id)) == 1

        # C1F-A-5 / C1-Q-05: horizon <= debt tenor (10y horizon vs 12y+ tenor) -> refused at Save with DEBT_TENOR_EXCEEDS_HORIZON
        _edit(client, rec.project_code, "debt.senior.gearing_pct", "75")
        r_ten = _edit(client, rec.project_code, "project_setup.technical.horizon_years", "10")
        assert "DEBT_TENOR_EXCEEDS_HORIZON" in r_ten.text
        assert "PR8_PROJECT_TYPE_NOT_CLASSIFIED" not in r_ten.text
    finally:
        client.__exit__(None, None, None)


def test_c1f_a1_line_owned_cost_scalars_refused_in_batch_apply(tmp_path):
    user, client, rec = _setup(tmp_path, "c1f_a1", "solar")
    try:
        ws = get_workspace_state(user, rec.project_id)
        toks = _tokens(client, rec.project_code)
        before_hash = toks["content_hash"]

        # Line-owned cost fields are detected
        blocked = find_line_owned_cost_fields(
            rec.project_id,
            ["capex.C.grid_connection", "opex.lines.insurance", "debt.senior.gearing_pct"],
        )
        assert "capex.C.grid_connection" in blocked
        assert "opex.lines.insurance" in blocked
        assert "debt.senior.gearing_pct" not in blocked

        # Batch apply of line-owned CAPEX scalar refuses with COST_CATEGORY_LINE_OWNED and zero DB mutation
        with pytest.raises(BatchApplyError) as exc_info:
            WorkbookUpdateService.apply_batch_draft_update(
                ws=ws,
                updates=[("capex.C.grid_connection", "5000")],
                content_hash=toks["content_hash"],
                workbook_version=WORKBOOK.version,
                expected_scenario_id=ws.active_scenario_id,
                project_record=rec,
                actor_user_id=user,
                reject_line_owned=True,
            )
        assert exc_info.value.code == "COST_CATEGORY_LINE_OWNED"
        assert _tokens(client, rec.project_code)["content_hash"] == before_hash

        # Batch apply of line-owned OPEX scalar refuses with COST_CATEGORY_LINE_OWNED
        with pytest.raises(BatchApplyError) as exc_info2:
            WorkbookUpdateService.apply_batch_draft_update(
                ws=ws,
                updates=[("opex.lines.insurance", "500")],
                content_hash=toks["content_hash"],
                workbook_version=WORKBOOK.version,
                expected_scenario_id=ws.active_scenario_id,
                project_record=rec,
                actor_user_id=user,
                reject_line_owned=True,
            )
        assert exc_info2.value.code == "COST_CATEGORY_LINE_OWNED"

        # Non-cost scalar (debt.senior.gearing_pct) still applies cleanly!
        pis_after = WorkbookUpdateService.apply_batch_draft_update(
            ws=ws,
            updates=[("debt.senior.gearing_pct", "60")],
            content_hash=toks["content_hash"],
            workbook_version=WORKBOOK.version,
            expected_scenario_id=ws.active_scenario_id,
            project_record=rec,
            actor_user_id=user,
        )
        assert float(pis_after.get("debt.senior.gearing_pct")) == 60.0
    finally:
        client.__exit__(None, None, None)


def test_c1_q02_single_field_horizon_edit_rejected_when_incompatible_with_saved_ppa_book(tmp_path):
    from app.workbook.update_service import FieldValidationError, _validate_ppa_book_against_proposed_snapshot

    user, client, rec = _setup(tmp_path, "c1_q02", "solar")
    try:
        # Build a valid canonical multistream PPA contract extending to 2045-12-31
        ws = get_workspace_state(user, rec.project_id)
        contracts = json.dumps({
            "schema_version": 2,
            "technology": "solar",
            "contracts": [
                {
                    "id": "ppa_1",
                    "type": "ppa",
                    "name": "Main PPA",
                    "share_pct": 100.0,
                    "start_date": "2031-03-01",
                    "end_date": "2045-12-31",
                    "price_eur_mwh": 65.0,
                    "escalation_pct": 2.0,
                },
            ],
        })
        snap = dict(ws.draft_snapshot)
        snap["rev_multistream_config_json"] = contracts
        snap["horizon_years"] = "5"
        # Shrinking horizon to 5 years (ends 2036, before PPA end 2045) MUST raise FieldValidationError!
        with pytest.raises(FieldValidationError, match="incompatible with the saved PPA contract book"):
            _validate_ppa_book_against_proposed_snapshot(snap)
    finally:
        client.__exit__(None, None, None)
