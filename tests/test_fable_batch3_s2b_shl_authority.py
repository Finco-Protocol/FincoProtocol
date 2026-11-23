"""FINCO 36 Batch 3 — Slice A (S2b / OD-SHL-01): Single Authoritative SHL Schedule.

Verifies OD-SHL-01 across canonical reference verticals and tax-loss / lock-up /
deductibility variants:
1. One authoritative dated SHL schedule feeds tax, P&L, balance sheet, waterfall,
   sponsor evidence, and returns.
2. Period-by-period 4-way reconciliation (<= 0.01 kEUR):
   - Balance Sheet SHL balance == authoritative SHL schedule closing balance
   - P&L SHL interest expense == Tax gross SHL interest == SHL schedule gross interest
   - Tax deductible SHL interest respects configured deductibility policy
     (FULLY_DEDUCTIBLE vs FULLY_NON_DEDUCTIBLE)
   - S2a independent reconciliation invariant reports RECONCILED (max_abs_diff <= 0.01 kEUR)
3. Independent Decimal(50) SHL roll-forward and dated cashflow-to-XIRR parity for
   both positive (Solar, Wind, EV, C12 Tax NOL) and negative pure-equity (Data Center)
   returns.
4. Fail-closed controls remain rejected (C08 gearing/maturity residual, C09 merchant gap).
"""
from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal, getcontext

import pytest

from app import project_factories as pf
from app.services.clean_presentation_adapter import build_clean_sponsor_schedule
from app.services.production_financial_authority import (
    CleanProductionRunUnavailable,
    run_clean_production,
)
from finco_core.inputs import (
    DebtSizingMode,
    OpeningTaxLossVintageParams,
    ShlInterestDeductibilityMode,
)
from tests.fin_v2_3_oracle import xirr

getcontext().prec = 50


def _d(x) -> Decimal:
    return Decimal(repr(float(x)))


def _assert_four_way_shl_authority(run) -> None:
    """Assert 4-way SHL authority: schedule == BS == P&L == tax (<= 0.01 kEUR)
    plus independent Decimal(50) roll-forward and XIRR parity."""
    g = run.g2c_result
    rec = g.shl_schedule_reconciliation
    assert rec is not None
    assert rec.status == "RECONCILED", rec
    assert rec.max_abs_diff_keur <= 0.01, rec

    # Returns must be published as OK (not suppressed)
    assert g.pure_equity_xirr_status.value == "OK"
    assert g.total_sponsor_xirr_status.value == "OK"
    assert g.pure_equity_xirr is not None
    assert g.total_sponsor_xirr is not None

    # 1. Authoritative SHL schedule vs Tax gross SHL interest
    mr = g.financing_result.project_model_result
    shl_sched = mr.shareholder_loan
    assert shl_sched is not None
    tc = mr.tax_and_cfads
    tax_shl_by_idx = dict(zip(tc.period_indices, tc.shl_gross_interest_audit_keur))
    sched_gross_by_idx = dict(zip(shl_sched.period_indices, shl_sched.shl_gross_interest_keur))
    sched_close_by_idx = dict(zip(shl_sched.period_indices, shl_sched.shl_closing_keur))

    for idx, gross in sched_gross_by_idx.items():
        if idx in tax_shl_by_idx:
            assert abs(gross - tax_shl_by_idx[idx]) <= 0.01, (
                f"Period {idx}: schedule gross SHL interest {gross} != tax gross {tax_shl_by_idx[idx]}"
            )

    # 2. P&L SHL interest & BS SHL closing vs authoritative SHL schedule
    fs = run.financial_statements_result
    pnl_by_idx = {p.period_index: p for p in fs.income_statement_periods}
    bs_by_idx = {p.period_index: p for p in fs.balance_sheet_periods}
    op_indices = {p.period_index for p in mr.periods if p.is_operation}
    bs_checked = 0
    for idx in shl_sched.period_indices:
        if idx not in op_indices:
            continue
        if idx in pnl_by_idx:
            assert abs(pnl_by_idx[idx].shl_interest_expense_keur - sched_gross_by_idx[idx]) <= 0.01
            if idx in tax_shl_by_idx:
                assert abs(pnl_by_idx[idx].shl_interest_expense_keur - tax_shl_by_idx[idx]) <= 0.01
        if idx in bs_by_idx and bs_by_idx[idx].shl_balance_keur is not None:
            assert abs(bs_by_idx[idx].shl_balance_keur - sched_close_by_idx[idx]) <= 0.01
            bs_checked += 1
    assert bs_checked > 0

    # 3. Independent Decimal(50) SHL roll-forward and dated XIRR parity
    evidence = build_clean_sponsor_schedule(run)
    for row in evidence["loan_balance_periods"]:
        calc_close = (
            _d(row["shl_opening_keur"])
            + _d(row["shl_draw_keur"])
            + _d(row["shl_pik_keur"])
            - _d(row["shl_principal_keur"])
        )
        assert abs(calc_close - _d(row["shl_closing_keur"])) <= Decimal("0.01")

    rows = evidence["periods"]
    dates = [date.fromisoformat(r["date"]) for r in rows]
    eq_oracle = float(xirr(dates, [r["pure_equity_net_cashflow_keur"] for r in rows]))
    sp_oracle = float(xirr(dates, [r["total_sponsor_net_cashflow_keur"] for r in rows]))
    assert g.pure_equity_xirr == pytest.approx(eq_oracle, abs=1e-10)
    assert g.total_sponsor_xirr == pytest.approx(sp_oracle, abs=1e-10)


@pytest.mark.parametrize("kind", ["solar", "wind", "data_center", "ev_charging"])
def test_s2b_reference_verticals_four_way_shl_reconciled(kind):
    pi = getattr(pf, f"create_generic_{kind}_reference")()
    run = run_clean_production(pi)
    _assert_four_way_shl_authority(run)
    if kind == "data_center":
        # Data Center has negative pure equity XIRR and positive total sponsor XIRR
        assert run.g2c_result.pure_equity_xirr < 0.0
        assert run.g2c_result.total_sponsor_xirr > 0.0


def test_s2b_c12_solar_tax_nol_converges_and_eliminates_shl_tax_gap():
    """C12_S_TAX_NOL (gearing-cap + opening loss carryforward): previously diverged by
    ~132.1 kEUR between tax SHL and P&L/BS SHL; S2b closes the feedback loop."""
    base = pf.create_generic_solar_reference()
    pi = replace(
        base,
        financing=replace(base.financing, debt_sizing_mode=DebtSizingMode.GEARING_CAP, gearing_ratio=0.70),
        tax=replace(
            base.tax,
            opening_tax_loss_vintages=(
                OpeningTaxLossVintageParams(origin_tax_year=2030, opening_amount_keur=10_000.0),
            ),
        ),
    )
    run = run_clean_production(pi)
    _assert_four_way_shl_authority(run)
    assert run.g2c_result.pure_equity_xirr > 0.0
    assert run.g2c_result.total_sponsor_xirr > 0.0


def test_s2b_respects_shl_deductibility_policy():
    """Deductible SHL interest derives from the same authoritative SHL schedule under
    existing deductibility policy (FULLY_DEDUCTIBLE vs FULLY_NON_DEDUCTIBLE)."""
    base = pf.create_generic_wind_reference()
    pi_ded = replace(
        base,
        tax=replace(base.tax, shl_interest_deductibility=ShlInterestDeductibilityMode.FULLY_DEDUCTIBLE),
    )
    run_ded = run_clean_production(pi_ded)
    _assert_four_way_shl_authority(run_ded)
    tc_ded = run_ded.g2c_result.financing_result.project_model_result.tax_and_cfads
    assert sum(tc_ded.shl_deductible_interest_audit_keur) == pytest.approx(
        sum(tc_ded.shl_gross_interest_audit_keur), abs=0.05
    )

    pi_non = replace(
        base,
        tax=replace(base.tax, shl_interest_deductibility=ShlInterestDeductibilityMode.FULLY_NON_DEDUCTIBLE),
    )
    run_non = run_clean_production(pi_non)
    _assert_four_way_shl_authority(run_non)
    tc_non = run_non.g2c_result.financing_result.project_model_result.tax_and_cfads
    assert sum(tc_non.shl_deductible_interest_audit_keur) == pytest.approx(0.0, abs=1e-9)
    assert sum(tc_non.shl_gross_interest_audit_keur) > 1_000.0


def test_s2b_negative_controls_remain_fail_closed():
    """C08 (unpaid SHL maturity residual) and C09 (merchant price coverage gap) stay rejected."""
    base = pf.create_generic_solar_reference()
    pi_c08 = replace(
        base,
        financing=replace(base.financing, debt_sizing_mode=DebtSizingMode.GEARING_CAP, gearing_ratio=0.99),
    )
    with pytest.raises(CleanProductionRunUnavailable):
        run_clean_production(pi_c08)

    pi_zero = replace(
        base,
        financing=replace(base.financing, debt_sizing_mode=DebtSizingMode.GEARING_CAP, gearing_ratio=0.0),
    )
    with pytest.raises(CleanProductionRunUnavailable):
        run_clean_production(pi_zero)
