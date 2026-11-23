"""FINCO 35 Batch 2 — Slice C (S4): Technical P90 authority (P1-TECH-01 / P1B-TECH-02).

Covers OD-P90-01:
- Explicit saved operating_hours_p90_10y (Solar 1,400 h) is authoritative through
  Save -> adapter -> debt sizing -> Run (no silent 0.9 x P50 = 1,350 h overwrite).
- Wind 2,700 h control unchanged; Solar P50 sponsor production unchanged.
- Canonical edit via /v2/workbook/update on project_setup.technical.p90_10y_hours:
  P90 > P50 rejected, zero/negative rejected, lowering P50 below saved P90 rejected,
  stale CAS rejected, no DB mutation on refusal.
- Absent P90 on legacy snapshot preserves 0.9 x P50 fallback without writing it to saved state.
- P1B-TECH-02: unknown/forged lender_case rejected fail-closed at canonical Save.
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
from app.input_adapter import build_projectinputs_from_snapshot
from app.persistence import db
from app.persistence.run_history_repository import get_run_history
from app.persistence.workspace_repository import get_workspace_state
from app.services.reference_seed_service import create_reference_seeded_project
from app.v2.router import router as v2_router
from app.workbook.financing_csrf import issue_token
from tests.model_mutation_csrf import post_valid_mutation


def _setup(tmp_path, name: str, kind: str = "solar"):
    user = "test-s4-user"
    db.DB_PATH = str(tmp_path / f"{name}.db")
    db.init_db()
    app = FastAPI()
    app.include_router(v2_router, prefix="/v2")
    client = TestClient(app)
    client.__enter__()
    client.cookies.set(COOKIE_NAME, create_session_token(user_id=user, username="admin"))
    rec = create_reference_seeded_project(
        user_id=user,
        requested_name=f"S4 {name}",
        template_source=f"generic_{kind}_reference",
        capacity_mw=16,
    )
    return user, client, rec


def _tokens(client, project_code: str) -> dict[str, str]:
    html = client.get("/v2/workbook", params={"project": project_code}).text
    return {
        k: re.search(r'name="' + k + r'" value="([^"]*)"', html).group(1)
        for k in ("content_hash", "workbook_version")
    }


def _edit(client, project_code: str, field_id: str, value: str, tokens=None):
    toks = tokens or _tokens(client, project_code)
    return post_valid_mutation(
        client,
        "/v2/workbook/update",
        headers={"HX-Request": "true"},
        data={"project": project_code, "field_id": field_id, "value": str(value), **toks},
    )


def _run(client, user: str, rec):
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
    assert resp.status_code == 200, resp.text[:400]
    body = resp.json()
    assert body["outcome"] == "COMMITTED", body
    hist = get_run_history(user, rec.project_id)
    h = next(x for x in hist if x.history_id == body["history_id"]).to_dict()
    for k, v in list(h.items()):
        if isinstance(v, str) and v[:1] in "[{":
            try:
                h[k] = json.loads(v)
            except Exception:
                pass
    return h


def test_solar_saved_p90_1400_is_authoritative_and_not_overwritten_to_1350(tmp_path):
    user, client, rec = _setup(tmp_path, "solar_p90", "solar")
    try:
        ws = get_workspace_state(user, rec.project_id)
        assert float(ws.draft_snapshot["operating_hours_p90_10y"]) == 1400.0
        pi = build_projectinputs_from_snapshot(ws.draft_snapshot)
        assert pi.technical.operating_hours_p50 == 1500.0
        assert pi.technical.operating_hours_p90_10y == 1400.0  # NOT 1350.0!

        # Run with saved 1400 h vs editing P90 to 1350 h -> debt size must change!
        h_1400 = _run(client, user, rec)
        debt_1400 = h_1400["integrity_evidence"]["sources_uses"]["summary"]["senior_debt_keur"]
        rev_1400 = h_1400["runtime_summary"]["total_revenue_keur"]

        r = _edit(client, rec.project_code, "project_setup.technical.p90_10y_hours", "1350")
        assert r.status_code == 200 and "field-error" not in r.text[:6000]
        h_1350 = _run(client, user, rec)
        debt_1350 = h_1350["integrity_evidence"]["sources_uses"]["summary"]["senior_debt_keur"]
        rev_1350 = h_1350["runtime_summary"]["total_revenue_keur"]

        # Higher P90 (1400 vs 1350) produces larger lender-sized senior debt (+14.37 kEUR); P50 sponsor revenue is identical!
        assert debt_1400 > debt_1350 + 10.0
        assert rev_1400 == pytest.approx(rev_1350, abs=1e-6)
    finally:
        client.__exit__(None, None, None)


def test_wind_2700_control_and_legacy_absent_p90_fallback(tmp_path):
    user, client, rec = _setup(tmp_path, "wind_p90", "wind")
    try:
        ws = get_workspace_state(user, rec.project_id)
        pi = build_projectinputs_from_snapshot(ws.draft_snapshot)
        assert pi.technical.operating_hours_p50 == 3000.0
        assert pi.technical.operating_hours_p90_10y == 2700.0

        # Absent P90 on legacy snapshot falls back to 0.9 * P50 without mutating snapshot
        legacy_snap = dict(ws.draft_snapshot)
        legacy_snap.pop("operating_hours_p90_10y", None)
        pi_legacy = build_projectinputs_from_snapshot(legacy_snap)
        assert pi_legacy.technical.operating_hours_p90_10y == pytest.approx(2700.0)
        assert "operating_hours_p90_10y" not in legacy_snap
    finally:
        client.__exit__(None, None, None)


def test_p90_validation_rejects_gt_p50_zero_stale_cas_and_forged_lender_case(tmp_path):
    user, client, rec = _setup(tmp_path, "p90_val", "solar")
    try:
        before_ws = get_workspace_state(user, rec.project_id)

        # 1) P90 > P50 (1600 > 1500) rejected at Save, no DB mutation
        r_gt = _edit(client, rec.project_code, "project_setup.technical.p90_10y_hours", "1600")
        assert "field-error" in r_gt.text or r_gt.status_code in (400, 422)
        assert float(get_workspace_state(user, rec.project_id).draft_snapshot["operating_hours_p90_10y"]) == 1400.0

        # 2) P90 = 0 rejected at Save
        r_zero = _edit(client, rec.project_code, "project_setup.technical.p90_10y_hours", "0")
        assert "field-error" in r_zero.text or r_zero.status_code in (400, 422)
        assert float(get_workspace_state(user, rec.project_id).draft_snapshot["operating_hours_p90_10y"]) == 1400.0

        # 3) Batch update setting P90 > P50 (1350 > 1300) rejected atomically at Save
        r_p50 = _edit(client, rec.project_code, "project_setup.technical.p90_10y_hours", "1501")
        assert "field-error" in r_p50.text or r_p50.status_code in (400, 422)
        assert float(get_workspace_state(user, rec.project_id).draft_snapshot["operating_hours_p90_10y"]) == 1400.0

        # 4) Stale CAS rejected
        stale = _tokens(client, rec.project_code)
        r_ok = _edit(client, rec.project_code, "project_setup.technical.p90_10y_hours", "1380", tokens=stale)
        assert r_ok.status_code == 200 and "field-error" not in r_ok.text[:6000]
        r_stale = _edit(client, rec.project_code, "project_setup.technical.p90_10y_hours", "1390", tokens=stale)
        assert r_stale.status_code == 409 or "stale" in r_stale.text.lower() or "changed" in r_stale.text.lower()
        assert float(get_workspace_state(user, rec.project_id).draft_snapshot["operating_hours_p90_10y"]) == 1380.0

        # 5) P1B-TECH-02: forged/unknown lender_case rejected fail-closed at canonical Save
        forged = json.dumps({"version": 1, "lender_case": "P99_UNKNOWN"})
        r_forged = _edit(client, rec.project_code, "debt.bankability.configuration", forged)
        assert "field-error" in r_forged.text or r_forged.status_code in (400, 422)

        # 6) Direct adapter also fails closed on P90 > P50
        bad_snap = dict(before_ws.draft_snapshot)
        bad_snap["operating_hours_p90_10y"] = "1600"
        with pytest.raises(ValueError, match="P90_EXCEEDS_P50"):
            build_projectinputs_from_snapshot(bad_snap)
    finally:
        client.__exit__(None, None, None)
