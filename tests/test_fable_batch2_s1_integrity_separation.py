"""FINCO 35 Batch 2 — Slice B (S1): Integrity / covenant separation (P1-INT-01a, P1-INT-01c).

Covers OD-INTEGRITY-01:
- C04 (reserve-funded shortfall 5.97 kEUR at DSCR ~0.990): NO_UNFUNDED_CASH_DEFICIT PASS with
  RESERVE_FUNDED_PRE_RESERVE_DEFICIT warning; DSCR_SCULPTING_FEASIBLE NOT_APPLICABLE.
- C12 (solar NOL with auto reserve covering shortfalls): NO_UNFUNDED_CASH_DEFICIT PASS with
  RESERVE_FUNDED_PRE_RESERVE_DEFICIT; DSCR_SCULPTING_FEASIBLE NOT_APPLICABLE.
- C05 (no reserve, negative distribution account -1.90 kEUR): MUST STAY FAIL.
- C03 / C06 (gearing_cap level_principal): DSCR_SCULPTING_FEASIBLE NOT_APPLICABLE,
  repayment_method sealed in senior_debt evidence.
- C01 / C02 (sculpted controls): DSCR_SCULPTING_FEASIBLE PASS, repayment_method=dscr_sculpted.
- Pre-reserve deficit without a verifying post-reserve BS row: MUST FAIL (fail-closed).
"""
from __future__ import annotations

import copy
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
from app.run_integrity.checks import check_dscr_feasibility, check_no_unfunded_deficit, run_integrity_checks
from app.run_integrity.contracts import CheckStatus, OverallStatus
from app.services.reference_seed_service import create_reference_seeded_project
from app.v2.react_workspace_router import router as react_workspace_router
from app.v2.router import router as v2_router
from tests.model_react_test_helpers import react_workbook_tokens
from app.workbook.financing_csrf import issue_token
from tests.model_mutation_csrf import post_valid_mutation

def _bank(**kw):
    return json.dumps({"version": 1, **kw}, separators=(",", ":"))


def _reserve(mode, req=0.0, months=0):
    return {"mode": mode, "months": months, "requirement_keur": req, "commitment_keur": 0.0, "fee_pct": 0.0}


def _run_case(tmp_path, name: str, kind: str, edits: list[tuple[str, str]]):
    user = "test-s1-user"
    db.DB_PATH = str(tmp_path / f"{name}.db")
    db.init_db()
    app = FastAPI()
    app.include_router(v2_router, prefix="/v2")
    app.include_router(react_workspace_router, prefix="/v2")
    with TestClient(app) as client:
        client.cookies.set(COOKIE_NAME, create_session_token(user_id=user, username="admin"))
        rec = create_reference_seeded_project(
            user_id=user,
            requested_name=f"S1 {name}",
            template_source=f"generic_{kind}_reference",
            capacity_mw=16,
        )
        for field_id, value in edits:
            tokens = react_workbook_tokens(client, rec.project_code)
            r = post_valid_mutation(
                client,
                "/v2/workbook/update",
                headers={"HX-Request": "true"},
                data={"project": rec.project_code, "field_id": field_id, "value": str(value), **tokens},
            )
            assert r.status_code == 200
        tokens = react_workbook_tokens(client, rec.project_code)
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
        ev = json.loads(h["integrity_evidence"]) if isinstance(h["integrity_evidence"], str) else h["integrity_evidence"]
        return ev, run_integrity_checks(ev)


def _check(report, check_id: str):
    return next(c for c in report.checks if c.check_id == check_id)


def test_c04_reserve_funded_shortfall_passes_with_warning_and_c05_stays_fail(tmp_path):
    # C04: wind gearing_cap + fixed cash DSRA 120 kEUR, tariff 50.10 -> min DSCR ~0.990, shortfall ~5.97 kEUR covered by DSRA
    ev_c04, rep_c04 = _run_case(
        tmp_path,
        "c04",
        "wind",
        [
            ("debt.bankability.configuration", _bank(sizing_mode="gearing_cap", reserve=_reserve("cash_fixed", 120.0))),
            ("revenue.ppa.base_tariff", "50.10"),
        ],
    )
    assert ev_c04["senior_debt"]["repayment_method"] == "level_principal"
    assert ev_c04["senior_debt"]["debt_sizing_mode"] == "gearing_cap"
    chk_def = _check(rep_c04, "NO_UNFUNDED_CASH_DEFICIT")
    assert chk_def.status is CheckStatus.PASS
    assert chk_def.reason_code == "RESERVE_FUNDED_PRE_RESERVE_DEFICIT"
    assert "kEUR" in chk_def.detail
    chk_sc = _check(rep_c04, "DSCR_SCULPTING_FEASIBLE")
    assert chk_sc.status is CheckStatus.NOT_APPLICABLE
    assert chk_sc.reason_code == "NOT_SCULPTED_REPAYMENT_METHOD"
    assert rep_c04.overall is OverallStatus.PASS

    # C05 negative control: same tariff 50.10, NO reserve -> negative distribution account -> MUST STAY FAIL
    _, rep_c05 = _run_case(
        tmp_path,
        "c05",
        "wind",
        [
            ("debt.bankability.configuration", _bank(sizing_mode="gearing_cap", reserve=_reserve("none"))),
            ("revenue.ppa.base_tariff", "50.10"),
        ],
    )
    chk_def_c05 = _check(rep_c05, "NO_UNFUNDED_CASH_DEFICIT")
    assert chk_def_c05.status is CheckStatus.FAIL
    assert chk_def_c05.reason_code == "NEGATIVE_CASH_WITHOUT_FUNDING_SOURCE"
    assert rep_c05.overall is OverallStatus.FAIL


def test_c03_gearing_cap_not_applicable_and_c01_sculpted_pass(tmp_path):
    ev_c03, rep_c03 = _run_case(
        tmp_path,
        "c03",
        "wind",
        [("debt.bankability.configuration", _bank(sizing_mode="gearing_cap"))],
    )
    assert ev_c03["senior_debt"]["repayment_method"] == "level_principal"
    assert _check(rep_c03, "DSCR_SCULPTING_FEASIBLE").status is CheckStatus.NOT_APPLICABLE
    assert rep_c03.overall is OverallStatus.PASS

    ev_c01, rep_c01 = _run_case(tmp_path, "c01", "solar", [])
    assert ev_c01["senior_debt"]["repayment_method"] == "dscr_sculpted"
    assert _check(rep_c01, "DSCR_SCULPTING_FEASIBLE").status is CheckStatus.PASS
    assert _check(rep_c01, "NO_UNFUNDED_CASH_DEFICIT").status is CheckStatus.PASS
    assert _check(rep_c01, "NO_UNFUNDED_CASH_DEFICIT").reason_code is None
    assert rep_c01.overall is OverallStatus.PASS


def test_c12_solar_nol_reserve_funded_shortfall_passes_with_warning(tmp_path):
    _, rep_c12 = _run_case(
        tmp_path,
        "c12",
        "solar",
        [
            ("debt.bankability.configuration", _bank(sizing_mode="gearing_cap")),
            ("revenue.ppa.base_tariff", "38"),
            ("tax.assumptions.loss_carryforward_years", "2"),
        ],
    )
    chk_def = _check(rep_c12, "NO_UNFUNDED_CASH_DEFICIT")
    assert chk_def.status is CheckStatus.PASS
    assert chk_def.reason_code == "RESERVE_FUNDED_PRE_RESERVE_DEFICIT"
    assert _check(rep_c12, "DSCR_SCULPTING_FEASIBLE").status is CheckStatus.NOT_APPLICABLE


def test_pre_reserve_deficit_without_post_reserve_bs_fails_closed():
    ev = {
        "cash": [{"period_index": 5, "cash_after_senior_before_reserves": -10.0}],
        "balance_sheet": [],  # missing post-reserve verification -> must fail closed!
    }
    chk = check_no_unfunded_deficit(ev)
    assert chk.status is CheckStatus.FAIL
    assert chk.reason_code == "NEGATIVE_CASH_WITHOUT_FUNDING_SOURCE"
