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


@pytest.fixture(autouse=True, scope="module")
def _finco47_legacy_ssr_rollback():
    """Module-scoped so module/session fixtures that seed over HTTP see the legacy SSR
    surface this module still exercises; default production flag stays React ON and the
    environment is restored exactly when the module finishes."""
    patch = pytest.MonkeyPatch()
    patch.setenv("FINCO_MODEL_REACT_V1", "0")
    try:
        yield
    finally:
        patch.undo()


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


def test_p90_validation_rejects_gt_p50_zero_reverse_p50_stale_cas_and_forged_lender_case(tmp_path):
    user, client, rec = _setup(tmp_path, "p90_val", "solar")
    try:
        before_ws = get_workspace_state(user, rec.project_id)
        before_hash = _tokens(client, rec.project_code)["content_hash"]

        # 1) P90 > P50 (1600 > 1500) rejected at Save, no DB mutation
        r_gt = _edit(client, rec.project_code, "project_setup.technical.p90_10y_hours", "1600")
        assert "field-error" in r_gt.text or r_gt.status_code in (400, 422)
        assert "workbook-field-saved" not in (r_gt.headers.get("HX-Trigger") or "")
        ws_after_gt = get_workspace_state(user, rec.project_id)
        assert float(ws_after_gt.draft_snapshot["operating_hours_p90_10y"]) == 1400.0
        assert _tokens(client, rec.project_code)["content_hash"] == before_hash

        # 2) P90 = 0 and malformed P90 rejected at Save, no DB mutation
        for bad_val in ("0", "-100", "abc", "nan"):
            r_bad = _edit(client, rec.project_code, "project_setup.technical.p90_10y_hours", bad_val)
            assert "field-error" in r_bad.text or r_bad.status_code in (400, 422), bad_val
            assert "workbook-field-saved" not in (r_bad.headers.get("HX-Trigger") or ""), bad_val
            ws_bad = get_workspace_state(user, rec.project_id)
            assert float(ws_bad.draft_snapshot["operating_hours_p90_10y"]) == 1400.0
            assert _tokens(client, rec.project_code)["content_hash"] == before_hash

        # 3) Single P50-only reduction below saved explicit P90 (1300 < 1400) rejected at Save before CAS/DB mutation
        r_p50 = _edit(client, rec.project_code, "project_setup.technical.p50_hours", "1300")
        assert "field-error" in r_p50.text or r_p50.status_code in (400, 422)
        assert "workbook-field-saved" not in (r_p50.headers.get("HX-Trigger") or "")
        ws_after_p50 = get_workspace_state(user, rec.project_id)
        assert float(ws_after_p50.draft_snapshot["p50_hours"]) == 1500.0
        assert float(ws_after_p50.draft_snapshot["operating_hours_p90_10y"]) == 1400.0
        assert _tokens(client, rec.project_code)["content_hash"] == before_hash
        # Worksheet GET remains clean (never stuck in recovery)
        wb_get = client.get("/v2/workbook", params={"project": rec.project_code})
        assert wb_get.status_code == 200
        assert 'data-testid="workbook-recovery-back"' not in wb_get.text

        # 4) Valid P50-only edit >= saved explicit P90 (1450 >= 1400) succeeds while preserving explicit P90=1400
        r_p50_ok = _edit(client, rec.project_code, "project_setup.technical.p50_hours", "1450")
        assert r_p50_ok.status_code == 200 and "field-error" not in r_p50_ok.text[:6000]
        assert "workbook-field-saved" in (r_p50_ok.headers.get("HX-Trigger") or "")
        ws_p50_ok = get_workspace_state(user, rec.project_id)
        assert float(ws_p50_ok.draft_snapshot["p50_hours"]) == 1450.0
        assert float(ws_p50_ok.draft_snapshot["operating_hours_p90_10y"]) == 1400.0
        assert _tokens(client, rec.project_code)["content_hash"] != before_hash

        # 5) Stale CAS rejected
        stale = _tokens(client, rec.project_code)
        r_ok = _edit(client, rec.project_code, "project_setup.technical.p90_10y_hours", "1380", tokens=stale)
        assert r_ok.status_code == 200 and "field-error" not in r_ok.text[:6000]
        r_stale = _edit(client, rec.project_code, "project_setup.technical.p90_10y_hours", "1390", tokens=stale)
        assert r_stale.status_code == 409 or "stale" in r_stale.text.lower() or "changed" in r_stale.text.lower()
        assert float(get_workspace_state(user, rec.project_id).draft_snapshot["operating_hours_p90_10y"]) == 1380.0

        # 6) P1B-TECH-02: forged/unknown lender_case rejected fail-closed at canonical Save
        forged = json.dumps({"version": 1, "lender_case": "P99_UNKNOWN"})
        r_forged = _edit(client, rec.project_code, "debt.bankability.configuration", forged)
        assert "field-error" in r_forged.text or r_forged.status_code in (400, 422)

        # 7) Direct adapter fails closed on P90 > P50 and on explicit numeric zero 0 / 0.0
        bad_snap = dict(before_ws.draft_snapshot)
        bad_snap["operating_hours_p90_10y"] = "1600"
        with pytest.raises(ValueError, match="P90_EXCEEDS_P50"):
            build_projectinputs_from_snapshot(bad_snap)

        for zero_val in (0, 0.0, "0", "0.0"):
            zero_snap = dict(before_ws.draft_snapshot)
            zero_snap["operating_hours_p90_10y"] = zero_val
            with pytest.raises(ValueError, match="P90_INVALID|operating_hours_p90_10y"):
                build_projectinputs_from_snapshot(zero_snap)
    finally:
        client.__exit__(None, None, None)


def test_paired_batch_p50_p90_updates_succeed_in_either_order_and_reject_invalid_pairs(tmp_path):
    from app.workbook.draft_recovery import diagnose_draft
    from app.workbook.registry import WORKBOOK
    from app.workbook.update_service import FieldValidationError, WorkbookUpdateService

    user, client, rec = _setup(tmp_path, "p90_batch", "solar")
    try:
        # Order A: P50 lowered first (1300 < old P90 1400), paired with P90 lowered to 1200 -> atomic proposed state valid!
        ws0 = get_workspace_state(user, rec.project_id)
        toks0 = _tokens(client, rec.project_code)
        WorkbookUpdateService.apply_batch_draft_update(
            ws=ws0,
            updates=[
                ("project_setup.technical.p50_hours", "1300"),
                ("project_setup.technical.p90_10y_hours", "1200"),
            ],
            content_hash=toks0["content_hash"],
            workbook_version=WORKBOOK.version,
            expected_scenario_id=ws0.active_scenario_id,
            project_record=rec,
            actor_user_id=user,
        )
        ws_a = get_workspace_state(user, rec.project_id)
        assert float(ws_a.draft_snapshot["p50_hours"]) == 1300.0
        assert float(ws_a.draft_snapshot["operating_hours_p90_10y"]) == 1200.0

        # Order B: P90 lowered first (1100), then P50 lowered to 1180 -> identical valid atomic commit
        toks_a = _tokens(client, rec.project_code)
        WorkbookUpdateService.apply_batch_draft_update(
            ws=ws_a,
            updates=[
                ("project_setup.technical.p90_10y_hours", "1100"),
                ("project_setup.technical.p50_hours", "1180"),
            ],
            content_hash=toks_a["content_hash"],
            workbook_version=WORKBOOK.version,
            expected_scenario_id=ws_a.active_scenario_id,
            project_record=rec,
            actor_user_id=user,
        )
        ws_b = get_workspace_state(user, rec.project_id)
        assert float(ws_b.draft_snapshot["p50_hours"]) == 1180.0
        assert float(ws_b.draft_snapshot["operating_hours_p90_10y"]) == 1100.0

        # Invalid paired batch (P50=1150, P90=1170) refused with zero DB mutation
        toks_b = _tokens(client, rec.project_code)
        with pytest.raises(FieldValidationError):
            WorkbookUpdateService.apply_batch_draft_update(
                ws=ws_b,
                updates=[
                    ("project_setup.technical.p50_hours", "1150"),
                    ("project_setup.technical.p90_10y_hours", "1170"),
                ],
                content_hash=toks_b["content_hash"],
                workbook_version=WORKBOOK.version,
                expected_scenario_id=ws_b.active_scenario_id,
                project_record=rec,
                actor_user_id=user,
            )
        ws_b_after = get_workspace_state(user, rec.project_id)
        assert _tokens(client, rec.project_code)["content_hash"] == toks_b["content_hash"]
        assert float(ws_b_after.draft_snapshot["p50_hours"]) == 1180.0
        assert float(ws_b_after.draft_snapshot["operating_hours_p90_10y"]) == 1100.0

        # Persisted invalid legacy draft is diagnosed as repairable on project_setup.technical.p90_10y_hours
        corrupted = dict(ws_b_after.draft_snapshot)
        corrupted["operating_hours_p90_10y"] = "1600"
        diag = diagnose_draft(corrupted)
        assert diag is not None and len(diag.issues) >= 1
        issue = diag.issues[0]
        assert issue.snapshot_key == "operating_hours_p90_10y"
        assert issue.field_id == "project_setup.technical.p90_10y_hours"
        assert issue.repairable is True
    finally:
        client.__exit__(None, None, None)

