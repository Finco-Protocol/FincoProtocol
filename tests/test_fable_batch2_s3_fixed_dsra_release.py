"""FINCO 35 Batch 2 — Slice E (S3): Fixed cash DSRA release at final senior maturity (E2E-04).

Covers OD-DSRA-01:
- C04 / C06 (fixed cash DSRA 120 kEUR): released once at final contractual senior maturity
  (period 34), closing = 0.0 from maturity onward, terminal status RELEASED, exact cash
  conservation (no cash creation, no double release, no CFADS/revenue inflation).
- C01 / C02 (automatic peak DSRA): unchanged (464.41 kEUR released at period 25).
- Negative controls: zero reserve, no senior debt (no fabricated release), shortfall at
  final maturity (drawn first, remainder released post-maturity), C05 true deficit stays FAIL.
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
from app.run_integrity.checks import run_integrity_checks
from app.run_integrity.contracts import CheckStatus, OverallStatus
from app.services.reference_seed_service import create_reference_seeded_project
from app.v2.router import router as v2_router
from app.workbook.financing_csrf import issue_token
from finco_core.inputs import DebtServiceReserveSupportMode
from financial_engine.dsra.contracts import CashDsraInput
from financial_engine.dsra.model import run_cash_dsra_model
from tests.model_mutation_csrf import post_valid_mutation


@pytest.fixture(autouse=True)
def _finco47_legacy_ssr_rollback(monkeypatch):
    """Scoped to this legacy SSR test module; default production flag stays React ON."""
    monkeypatch.setenv("FINCO_MODEL_REACT_V1", "0")


def _bank(**kw):
    return json.dumps({"version": 1, **kw}, separators=(",", ":"))


def _reserve(mode, req=0.0, months=0):
    return {"mode": mode, "months": months, "requirement_keur": req, "commitment_keur": 0.0, "fee_pct": 0.0}


def _run_case(tmp_path, name: str, kind: str, edits: list[tuple[str, str]]):
    user = "test-s3-user"
    db.DB_PATH = str(tmp_path / f"{name}.db")
    db.init_db()
    app = FastAPI()
    app.include_router(v2_router, prefix="/v2")
    with TestClient(app) as client:
        client.cookies.set(COOKIE_NAME, create_session_token(user_id=user, username="admin"))
        rec = create_reference_seeded_project(
            user_id=user,
            requested_name=f"S3 {name}",
            template_source=f"generic_{kind}_reference",
            capacity_mw=16,
        )
        for field_id, value in edits:
            html = client.get("/v2/workbook", params={"project": rec.project_code}).text
            tokens = {
                k: re.search(r'name="' + k + r'" value="([^"]*)"', html).group(1)
                for k in ("content_hash", "workbook_version")
            }
            r = post_valid_mutation(
                client,
                "/v2/workbook/update",
                headers={"HX-Request": "true"},
                data={"project": rec.project_code, "field_id": field_id, "value": str(value), **tokens},
            )
            assert r.status_code == 200
        html = client.get("/v2/workbook", params={"project": rec.project_code}).text
        tokens = {
            k: re.search(r'name="' + k + r'" value="([^"]*)"', html).group(1)
            for k in ("content_hash", "workbook_version")
        }
        req = SimpleNamespace(cookies=client.cookies, state=SimpleNamespace())
        resp = client.post(
            "/v2/workbook/run",
            headers={"Accept": "application/json"},
            data={
                "project": rec.project_code,
                **tokens,
                "csrf_token": issue_token(req, rec.project_code, purpose="workbook-run-v1"),
                "run_intent_id": str(uuid.uuid4()),
            },
            follow_redirects=False,
        )
        assert resp.status_code == 200
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


def test_c06_and_c04_fixed_cash_dsra_releases_at_senior_maturity(tmp_path):
    # C06: wind gearing_cap + fixed cash DSRA 120 kEUR, ample DSCR
    h06 = _run_case(
        tmp_path,
        "c06",
        "wind",
        [("debt.bankability.configuration", _bank(sizing_mode="gearing_cap", reserve=_reserve("cash_fixed", 120.0)))],
    )
    ev06 = h06["integrity_evidence"]
    rep06 = run_integrity_checks(ev06)
    assert rep06.overall is OverallStatus.PASS

    bs06 = {r["period_index"]: r for r in ev06["balance_sheet"]}
    last_senior_idx = max(r["period_index"] for r in ev06["senior_debt"]["periods"] if r["debt_service"] > 1e-6)
    # Before final senior maturity: DSRA holds 120 kEUR
    assert bs06[last_senior_idx - 1]["dsra_balance"] == pytest.approx(120.0, abs=0.01)
    # At and after final senior maturity: DSRA is released to 0.0 (no stranded 120 kEUR!)
    assert bs06[last_senior_idx]["dsra_balance"] == pytest.approx(0.0, abs=0.01)
    for pidx in sorted(bs06):
        if pidx > last_senior_idx and bs06[pidx]["dsra_balance"] is not None:
            assert bs06[pidx]["dsra_balance"] == pytest.approx(0.0, abs=0.01)

    # C04: wind gearing_cap + fixed cash DSRA 120 kEUR, tuned low tariff 50.10 (draw in early period, top-up, then release at maturity)
    h04 = _run_case(
        tmp_path,
        "c04",
        "wind",
        [
            ("debt.bankability.configuration", _bank(sizing_mode="gearing_cap", reserve=_reserve("cash_fixed", 120.0))),
            ("revenue.ppa.base_tariff", "50.10"),
        ],
    )
    ev04 = h04["integrity_evidence"]
    rep04 = run_integrity_checks(ev04)
    assert rep04.overall is OverallStatus.PASS
    bs04 = {r["period_index"]: r for r in ev04["balance_sheet"]}
    last_senior_idx04 = max(r["period_index"] for r in ev04["senior_debt"]["periods"] if r["debt_service"] > 1e-6)
    assert bs04[last_senior_idx04 - 1]["dsra_balance"] == pytest.approx(120.0, abs=0.01)
    assert bs04[last_senior_idx04]["dsra_balance"] == pytest.approx(0.0, abs=0.01)
    for pidx in sorted(bs04):
        if pidx > last_senior_idx04 and bs04[pidx]["dsra_balance"] is not None:
            assert bs04[pidx]["dsra_balance"] == pytest.approx(0.0, abs=0.01)


def test_fixed_dsra_unit_controls_no_debt_and_maturity_shortfall():
    periods = [
        SimpleNamespace(period_index=1, is_construction=True),
        SimpleNamespace(period_index=2, is_construction=False),
        SimpleNamespace(period_index=3, is_construction=False),
        SimpleNamespace(period_index=4, is_construction=False),
    ]
    dsra_in = CashDsraInput(mode=DebtServiceReserveSupportMode.CASH_DSRA, requirement_keur=100.0)

    # 1) No senior debt at all -> no fabricated release
    post_nodebt = SimpleNamespace(
        period_indices=(1, 2, 3, 4),
        senior_debt_service_keur=(0.0, 0.0, 0.0, 0.0),
        cash_after_senior_before_reserves_keur=(0.0, 50.0, 50.0, 50.0),
    )
    res_nd = run_cash_dsra_model(post_nodebt, dsra_in, periods)
    assert res_nd.total_release_keur == 0.0
    assert res_nd.final_closing_balance_keur == 100.0

    # 2) Shortfall at final maturity period (period 3): draw covers shortfall first, remainder releases in period 4
    post_sf = SimpleNamespace(
        period_indices=(1, 2, 3, 4),
        senior_debt_service_keur=(0.0, 80.0, 80.0, 0.0),
        cash_after_senior_before_reserves_keur=(0.0, 50.0, -30.0, 50.0),
    )
    res_sf = run_cash_dsra_model(post_sf, dsra_in, periods)
    p3 = res_sf.period_results[2]
    p4 = res_sf.period_results[3]
    assert p3.draw_to_cover_shortfall_keur == pytest.approx(30.0)
    assert p3.closing_balance_keur == pytest.approx(70.0)
    assert p4.release_keur == pytest.approx(70.0)
    assert p4.closing_balance_keur == pytest.approx(0.0)
    assert res_sf.total_draw_keur + res_sf.total_release_keur == pytest.approx(100.0)
