"""FINCO 35 Batch 2 — Slice A (S2a): SHL schedule reconciliation & independent interest arithmetic.

Covers:
1. E2E-03 (S2a): Direct period-by-period reconciliation between G2A/tax SHL schedule
   and waterfall/statement SHL schedule (by period_index, not positional zip).
   - Data Center (C13): diverges without covenant lock-up -> returns suppressed
     (UPSTREAM_FINANCIAL_FEEDBACK_NOT_CLOSED, None != 0.0), project metrics preserved.
   - Solar (C01) / Wind (C02): reconciled -> returns published as OK.
   - Fail-closed unit tests: missing schedule, axis mismatch, duplicate index,
     non-finite values, tolerance boundary (0.01 kEUR), reordered period_index alignment.
   - Investor returns suppression under UPSTREAM_FINANCIAL_FEEDBACK_NOT_CLOSED.
2. Independent Decimal(50) period arithmetic for senior interest, SHL interest,
   and total interest (opening/draw/repay, ACT/360 day count, PIK/IDC separation)
   plus deliberate synthetic mutation witnesses (senior interest x 1.01, SHL omission).
"""
from __future__ import annotations

import copy
import json
import re
import uuid
from datetime import date
from decimal import Decimal, getcontext
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth import COOKIE_NAME, create_session_token
from app.persistence import db
from app.persistence.run_history_repository import get_run_history
from app.run_integrity.checks import check_interest_and_debt_service
from app.run_integrity.contracts import CheckStatus
from app.services.reference_seed_service import create_reference_seeded_project
from app.v2.router import router as v2_router
from app.workbook.financing_csrf import issue_token
from financial_engine.shareholder_waterfall.model import (
    SHL_RECONCILIATION_TOLERANCE_KEUR,
    reconcile_shl_schedules,
)


@pytest.fixture(autouse=True)
def _finco47_legacy_ssr_rollback(monkeypatch):
    """Scoped to this legacy SSR test module; default production flag stays React ON."""
    monkeypatch.setenv("FINCO_MODEL_REACT_V1", "0")

getcontext().prec = 50


def _d(x) -> Decimal:
    return Decimal(repr(float(x)))


def _make_schedule(indices, opening, gross, cash, pik, principal, closing):
    return SimpleNamespace(
        period_indices=tuple(indices),
        shl_opening_keur=tuple(opening),
        shl_gross_interest_keur=tuple(gross),
        shl_cash_interest_keur=tuple(cash),
        shl_pik_interest_keur=tuple(pik),
        shl_principal_keur=tuple(principal),
        shl_closing_keur=tuple(closing),
    )


def _run_v2_reference(tmp_path, kind: str):
    """Run real canonical V2 Save -> Run -> sealed History for a reference vertical."""
    user = "test-s2a-user"
    db.DB_PATH = str(tmp_path / f"{kind}.db")
    db.init_db()
    app = FastAPI()
    app.include_router(v2_router, prefix="/v2")
    with TestClient(app) as client:
        client.cookies.set(COOKIE_NAME, create_session_token(user_id=user, username="admin"))
        rec = create_reference_seeded_project(
            user_id=user,
            requested_name=f"S2a {kind}",
            template_source=f"generic_{kind}_reference",
            capacity_mw=16,
        )
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
        assert resp.status_code == 200, resp.text[:500]
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
        return body, h


# ── S2a: Unit & Negative Controls on reconcile_shl_schedules ──────────────────


def test_reconcile_shl_no_shl_is_not_applicable():
    rec = reconcile_shl_schedules(None, None, has_shl=False, shl_interest_deductible=True)
    assert rec.status == "NOT_APPLICABLE"
    assert rec.reason_code is None
    assert rec.max_abs_diff_keur == 0.0


def test_reconcile_shl_missing_schedule_fails_closed():
    sched = _make_schedule([1, 2], [100.0, 90.0], [5.0, 4.5], [5.0, 4.5], [0.0, 0.0], [10.0, 10.0], [90.0, 80.0])
    rec_a = reconcile_shl_schedules(None, sched, has_shl=True, shl_interest_deductible=True)
    assert rec_a.status == "MISSING_EVIDENCE"
    assert rec_a.reason_code == "SHL_SCHEDULE_EVIDENCE_MISSING"

    rec_b = reconcile_shl_schedules(sched, None, has_shl=True, shl_interest_deductible=True)
    assert rec_b.status == "MISSING_EVIDENCE"
    assert rec_b.reason_code == "SHL_SCHEDULE_EVIDENCE_MISSING"


def test_reconcile_shl_axis_mismatch_and_duplicates_fail_closed():
    s1 = _make_schedule([1, 2], [100.0, 90.0], [5.0, 4.5], [5.0, 4.5], [0.0, 0.0], [10.0, 10.0], [90.0, 80.0])
    s2 = _make_schedule([1, 3], [100.0, 90.0], [5.0, 4.5], [5.0, 4.5], [0.0, 0.0], [10.0, 10.0], [90.0, 80.0])
    rec = reconcile_shl_schedules(s1, s2, has_shl=True, shl_interest_deductible=True)
    assert rec.status == "INVALID_EVIDENCE"
    assert rec.reason_code == "SHL_SCHEDULE_AXIS_MISMATCH"

    s_dup = _make_schedule([1, 1], [100.0, 90.0], [5.0, 4.5], [5.0, 4.5], [0.0, 0.0], [10.0, 10.0], [90.0, 80.0])
    rec_dup = reconcile_shl_schedules(s_dup, s1, has_shl=True, shl_interest_deductible=True)
    assert rec_dup.status == "INVALID_EVIDENCE"
    assert rec_dup.reason_code == "SHL_SCHEDULE_AXIS_MISMATCH"


def test_reconcile_shl_compares_by_period_index_not_positional_zip():
    s1 = _make_schedule([1, 2], [100.0, 90.0], [5.0, 4.5], [5.0, 4.5], [0.0, 0.0], [10.0, 10.0], [90.0, 80.0])
    s2 = _make_schedule([2, 1], [90.0, 100.0], [4.5, 5.0], [4.5, 5.0], [0.0, 0.0], [10.0, 10.0], [80.0, 90.0])
    rec = reconcile_shl_schedules(s1, s2, has_shl=True, shl_interest_deductible=True)
    assert rec.status == "RECONCILED"
    assert rec.max_abs_diff_keur == 0.0


def test_reconcile_shl_nonfinite_fails_closed():
    s1 = _make_schedule([1], [100.0], [5.0], [5.0], [0.0], [10.0], [90.0])
    s_nan = _make_schedule([1], [100.0], [float("nan")], [5.0], [0.0], [10.0], [90.0])
    rec = reconcile_shl_schedules(s1, s_nan, has_shl=True, shl_interest_deductible=True)
    assert rec.status == "INVALID_EVIDENCE"
    assert rec.reason_code == "SHL_SCHEDULE_NONFINITE"
    assert rec.first_divergent_field == "gross_interest"


def test_reconcile_shl_tolerance_boundary():
    assert SHL_RECONCILIATION_TOLERANCE_KEUR == 0.01
    s1 = _make_schedule([1, 2], [100.0, 90.0], [5.0, 4.5], [5.0, 4.5], [0.0, 0.0], [10.0, 10.0], [90.0, 80.0])
    s_within = _make_schedule([1, 2], [100.0, 90.0], [5.0, 4.5], [5.0, 4.5], [0.0, 0.0], [10.0, 10.0], [90.009, 80.0])
    rec_ok = reconcile_shl_schedules(s1, s_within, has_shl=True, shl_interest_deductible=True)
    assert rec_ok.status == "RECONCILED"

    s_over = _make_schedule([1, 2], [100.0, 90.0], [5.0, 4.52], [5.0, 4.5], [0.0, 0.02], [10.0, 10.0], [90.0, 80.02])
    rec_bad = reconcile_shl_schedules(s1, s_over, has_shl=True, shl_interest_deductible=True)
    assert rec_bad.status == "DIVERGED"
    assert rec_bad.reason_code == "SHL_SCHEDULE_DIVERGENCE"
    assert rec_bad.first_divergent_period_index == 2
    assert rec_bad.max_abs_diff_keur == pytest.approx(0.02, abs=1e-9)
    assert rec_bad.periods_divergent_count == 1


# ── S2a: Canonical End-to-End Verification (C13 DC vs C01 Solar / C02 Wind) ──


def test_c13_data_center_s2b_reconciles_shl_and_publishes_returns(tmp_path):
    """Under Batch 3 S2b (OD-SHL-01), C13 Data Center converges to one authoritative SHL
    schedule (tax == P&L == BS == waterfall), so shareholder returns are published as OK."""
    _, h = _run_v2_reference(tmp_path, "data_center")
    rs = h["runtime_summary"]
    ev = h["integrity_evidence"]

    assert rs["equity_irr"] is not None
    assert rs["total_sponsor_xirr"] is not None
    assert rs["share_capital_irr_status"] == "OK"
    assert rs["total_sponsor_xirr_status"] == "OK"
    assert ev["sponsor"]["reported"]["pure_equity_xirr"] is not None
    assert ev["sponsor"]["reported"]["total_sponsor_xirr"] is not None
    assert ev["sponsor"]["reported"]["pure_equity_xirr_status"] == "OK"
    assert ev["sponsor"]["reported"]["total_sponsor_xirr_status"] == "OK"

    # Project metrics unaffected and preserved
    assert rs["min_dscr"] == pytest.approx(1.3, abs=1e-4)
    assert rs["project_irr"] is not None


def test_s2a_guard_still_suppresses_returns_on_unclosed_divergence(monkeypatch):
    """Independent S2a invariant: if SHL schedule reconciliation ever reports DIVERGED
    (> 0.01 kEUR), shareholder/sponsor returns remain suppressed with explicit status."""
    from app import project_factories as pf
    from app.services.production_financial_authority import run_clean_production
    from financial_engine.shareholder_waterfall import model as wf_mod
    from financial_engine.shareholder_waterfall.model import ShlScheduleReconciliation

    real_reconcile = wf_mod.reconcile_shl_schedules
    calls = {"n": 0}

    def force_diverged(sched_a, sched_b, *, has_shl, shl_interest_deductible, tolerance_keur=0.01):
        calls["n"] += 1
        if calls["n"] == 1:
            return real_reconcile(
                sched_a, sched_b,
                has_shl=has_shl,
                shl_interest_deductible=shl_interest_deductible,
                tolerance_keur=tolerance_keur,
            )
        return ShlScheduleReconciliation(
            status="DIVERGED",
            reason_code="SHL_SCHEDULE_DIVERGENCE",
            tolerance_keur=tolerance_keur,
            max_abs_diff_keur=12.34,
            first_divergent_period_index=1,
            first_divergent_field="gross_interest",
            max_divergent_period_index=1,
            max_divergent_field="gross_interest",
            cumulative_gross_interest_diff_keur=12.34,
            periods_divergent_count=1,
            schedule_a_source="g2a_tax_shl",
            schedule_b_source="g2c_waterfall_shl",
            shl_interest_deductible=shl_interest_deductible,
        )

    from app.services import production_financial_authority as authority
    monkeypatch.setattr(wf_mod, "reconcile_shl_schedules", force_diverged)
    authority._POLICY_RUN_CACHE.clear()
    try:
        run = run_clean_production(pf.create_generic_solar_reference())
    finally:
        authority._POLICY_RUN_CACHE.clear()
    g = run.g2c_result
    assert g.shl_schedule_reconciliation.status == "DIVERGED"
    assert g.pure_equity_xirr is None
    assert g.total_sponsor_xirr is None
    assert g.pure_equity_xirr_status.value == "UPSTREAM_FINANCIAL_FEEDBACK_NOT_CLOSED"
    assert g.total_sponsor_xirr_status.value == "UPSTREAM_FINANCIAL_FEEDBACK_NOT_CLOSED"
    assert g.return_summary.project.project_xirr is not None



def test_c01_solar_and_c02_wind_reconciled_shl_keeps_returns_ok(tmp_path):
    for kind in ("solar", "wind"):
        _, h = _run_v2_reference(tmp_path, kind)
        rs = h["runtime_summary"]
        assert rs["share_capital_irr_status"] == "OK"
        assert rs["total_sponsor_xirr_status"] == "OK"
        assert rs["equity_irr"] is not None
        assert rs["total_sponsor_xirr"] is not None


# ── Independent Decimal Interest Arithmetic & Mutation Witnesses ──────────────


def _verify_independent_interest_oracle_from_sealed_history(h: dict) -> tuple[Decimal, Decimal, Decimal]:
    """Independent Decimal(50) verification of senior interest, SHL interest, and total P&L interest
    from sealed Run history evidence (no engine helper imports).
    """
    ev = h["integrity_evidence"]
    senior_rows = ev["senior_debt"]["periods"]
    senior_by_idx: dict[int, Decimal] = {}
    for row in senior_rows:
        idx = int(row["period_index"])
        opening = _d(row["opening"])
        rate = _d(row["annual_rate"])
        day_frac = _d(row["day_fraction"])
        expected_int = opening * rate * day_frac
        actual_int = _d(row["interest"])
        actual_prin = _d(row["principal"])
        actual_ds = _d(row["debt_service"])
        assert abs(actual_int - expected_int) <= Decimal("0.01"), (
            f"Senior interest mismatch at period {idx}: expected={expected_int}, actual={actual_int}"
        )
        assert abs(actual_ds - (actual_int + actual_prin)) <= Decimal("0.01"), (
            f"Senior DS mismatch at period {idx}: ds={actual_ds}, int+prin={actual_int + actual_prin}"
        )
        senior_by_idx[idx] = actual_int

    # SHL and total interest from sealed P&L (fs["pnl"]["periods"])
    fs = h["financial_statements"]
    pnl_rows = fs["pnl"]["periods"]
    shl_by_idx: dict[int, Decimal] = {}
    pnl_total = Decimal("0")
    for pnl_row in pnl_rows:
        idx = int(pnl_row["period"])
        act_senior = _d(pnl_row["senior_interest_expense_keur"])
        act_shl = _d(pnl_row["shl_interest_expense_keur"])
        if idx not in senior_by_idx and act_senior == Decimal("0") and act_shl == Decimal("0"):
            # Construction or post-debt zero-interest period
            continue
        exp_senior = senior_by_idx.get(idx, Decimal("0"))
        assert abs(act_senior - exp_senior) <= Decimal("0.02"), (
            f"P&L senior interest != schedule at period {idx}: {act_senior} vs {exp_senior}"
        )
        # Total interest deducted from EBIT to reach EBT must equal senior + SHL
        ebit = _d(pnl_row["ebit_keur"])
        ebt = _d(pnl_row["earnings_before_tax_keur"])
        implied_total_int = ebit - ebt
        assert abs(implied_total_int - (act_senior + act_shl)) <= Decimal("0.02"), (
            f"P&L implied total interest (EBIT-EBT={implied_total_int}) != senior+SHL ({act_senior + act_shl}) at period {idx}"
        )
        shl_by_idx[idx] = act_shl
        pnl_total += act_senior + act_shl

    # Cross-check SHL cash interest + PIK against sponsor schedule
    sponsor_rows = h["sponsor_schedule"]["periods"]
    for sp in sponsor_rows:
        if sp.get("axis_kind") != "OPERATING":
            continue
        idx = int(sp["period"])
        cash_int = _d(sp["shl_cash_interest_receipt_keur"])
        pik = _d(sp["shl_pik_keur"])
        gross = shl_by_idx.get(idx, Decimal("0"))
        assert abs((cash_int + pik) - gross) <= Decimal("0.02"), (
            f"SHL cash({cash_int}) + PIK({pik}) != gross({gross}) at period {idx}"
        )

    return sum(senior_by_idx.values(), Decimal("0")), sum(shl_by_idx.values(), Decimal("0")), pnl_total


def test_independent_interest_decimal_oracle_solar_and_wind(tmp_path):
    for kind in ("solar", "wind"):
        _, h = _run_v2_reference(tmp_path, kind)
        tot_sen, tot_shl, tot_pnl = _verify_independent_interest_oracle_from_sealed_history(h)
        assert tot_sen > Decimal("0")
        assert tot_shl > Decimal("0")
        assert abs(tot_pnl - (tot_sen + tot_shl)) <= Decimal("0.05")


def test_interest_mutation_witnesses_caught(tmp_path):
    """Deliberate synthetic mutations:
    1) senior_interest * 1.01 -> caught by both independent Decimal oracle AND run_integrity_checks.
    2) omitting SHL interest from P&L total interest (EBT) -> caught by independent Decimal oracle.
    """
    _, h = _run_v2_reference(tmp_path, "solar")

    # Witness 1: senior interest * 1.01 in integrity evidence
    mutated_ev = copy.deepcopy(h["integrity_evidence"])
    mutated_ev["senior_debt"]["periods"][0]["interest"] *= 1.01
    chk = check_interest_and_debt_service(mutated_ev)
    assert chk.status is CheckStatus.FAIL
    assert chk.reason_code == "INTEREST_OR_DEBT_SERVICE_MISMATCH"

    mutated_h = copy.deepcopy(h)
    mutated_h["integrity_evidence"] = mutated_ev
    with pytest.raises(AssertionError, match="Senior interest mismatch"):
        _verify_independent_interest_oracle_from_sealed_history(mutated_h)

    # Witness 2: omitting SHL interest from P&L EBT (total interest) caught by independent oracle
    mutated_h2 = copy.deepcopy(h)
    for row in mutated_h2["financial_statements"]["pnl"]["periods"]:
        if row["shl_interest_expense_keur"] > 1.0:
            row["earnings_before_tax_keur"] = row["ebit_keur"] - row["senior_interest_expense_keur"]
            break
    with pytest.raises(AssertionError, match="P&L implied total interest"):
        _verify_independent_interest_oracle_from_sealed_history(mutated_h2)

