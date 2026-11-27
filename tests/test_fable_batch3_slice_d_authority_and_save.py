"""FINCO 36 Batch 3 — Slice D: Financial Authority, Save Readiness & Independent Probes (§5).

Covers:
1. E2E-01 / OD-NODEBT-01: explicit zero senior gearing refused at Save (single-field & batch)
   with ZERO_SENIOR_GEARING_NOT_SUPPORTED and zero DB mutation.
2. C1F-A-5: horizon_years <= senior_tenor_years refused at Save (single-field & batch) with
   DEBT_TENOR_EXCEEDS_HORIZON; valid paired batch edits succeed atomically in both input orders.
3. C1F-A-1 / P1-OPEX-02: scalar edits on line-owned active CAPEX/OPEX categories refused
   consistently on single-field Save (COST_CATEGORY_LINE_OWNED) with zero DB mutation.
4. C1F-C-1: prospective acquisition Save date validation against source Run horizon
   (CLOSING_NOT_WITHIN_SOURCE_HORIZON, EXIT_BEYOND_SOURCE_HORIZON,
   CLOSING_DATE_ENTITLEMENT_ORDER_AMBIGUOUS) while keeping acquisition flag OFF.
5. P1-FIN-01 & P1-FIN-02: independent Decimal(50) senior debt period parity and staged
   construction S&U / BS check on reference verticals.
6. P1-REV-03: combined % merchant balancing + EUR/MWh generation balancing additive probe.
7. F2-NEW-03: tax-loss continuity (opening + added - used - expired == closing) on DC & EV.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal, getcontext
import re
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import project_factories as pf
from app.auth import COOKIE_NAME, create_session_token
from app.model_v2.acquisition.economics import (
    AcquisitionPolicyError,
    AcquisitionTerms,
    validate_acquisition_dates_against_source,
)
from app.persistence import db
from app.persistence.workspace_repository import get_workspace_state
from app.services.production_financial_authority import run_clean_production
from app.services.reference_seed_service import create_reference_seeded_project
from app.v2.react_workspace_router import router as react_workspace_router
from app.v2.router import router as v2_router
from tests.model_react_test_helpers import react_workbook_tokens
from app.workbook.mutation_csrf import mutation_token
from app.workbook.update_service import (
    FieldValidationError,
    WorkbookUpdateService,
    validate_proposed_financing_horizon_snapshot,
)
from finco_core.engine.period_engine import PeriodEngine
from finco_core.revenue.generation import revenue_decomposition_schedule

getcontext().prec = 50


def _d(x) -> Decimal:
    return Decimal(repr(float(x)))


# ── 1. E2E-01 (Zero Senior Gearing) & C1F-A-5 (Horizon vs Senior Tenor) ──────


def test_slice_d_e2e_01_zero_gearing_and_c1f_a5_horizon_tenor_save_validation(tmp_path):
    user = "test-slice-d-user"
    db.DB_PATH = str(tmp_path / "sliced.db")
    db.init_db()
    app = FastAPI()
    app.include_router(v2_router, prefix="/v2")
    app.include_router(react_workspace_router, prefix="/v2")

    with TestClient(app) as client:
        client.cookies.set(COOKIE_NAME, create_session_token(user_id=user, username="admin"))
        rec = create_reference_seeded_project(
            user_id=user,
            requested_name="Slice D Solar",
            template_source="generic_solar_reference",
            capacity_mw=16,
        )

        def _get_tokens():
            return react_workbook_tokens(client, rec.project_code)

        req_ns = SimpleNamespace(cookies=client.cookies, state=SimpleNamespace())
        tokens0 = _get_tokens()

        # E2E-01: single-field gearing = 0 -> refused with ZERO_SENIOR_GEARING_NOT_SUPPORTED, zero mutation
        resp_zero = client.post(
            "/v2/workbook/update",
            data={
                "project": rec.project_code,
                "field_id": "debt.senior.gearing_pct",
                "value": "0",
                **tokens0,
                "csrf_token": mutation_token(req_ns, rec.project_code, "workbook-update"),
            },
            follow_redirects=False,
        )
        assert "ZERO_SENIOR_GEARING_NOT_SUPPORTED" in (resp_zero.headers.get("location", "") + resp_zero.text)
        assert _get_tokens() == tokens0

        # C1F-A-5: single-field horizon_years <= senior_tenor_years (default tenor=15, set horizon=15) -> refused
        resp_ht = client.post(
            "/v2/workbook/update",
            data={
                "project": rec.project_code,
                "field_id": "project_setup.technical.horizon_years",
                "value": "15",
                **tokens0,
                "csrf_token": mutation_token(req_ns, rec.project_code, "workbook-update"),
            },
            follow_redirects=False,
        )
        assert "DEBT_TENOR_EXCEEDS_HORIZON" in (resp_ht.headers.get("location", "") + resp_ht.text)
        assert _get_tokens() == tokens0

        # C1F-A-5: paired atomic batch edit (both orders) succeeds when proposed horizon > proposed tenor!
        ws = get_workspace_state(user, rec.project_id)
        with pytest.raises(FieldValidationError, match="DEBT_TENOR_EXCEEDS_HORIZON"):
            WorkbookUpdateService.apply_batch_draft_update(
                ws=ws,
                updates=[("project_setup.technical.horizon_years", "12"), ("debt.senior.tenor_years", "14")],
                content_hash=tokens0["content_hash"],
                workbook_version=tokens0["workbook_version"],
                expected_scenario_id=ws.active_scenario_id,
                project_record=rec,
                actor_user_id=user,
            )
        assert _get_tokens() == tokens0

        # Valid paired batch edit: shrink tenor to 10 AND horizon to 15 in reverse order -> succeeds!
        pis = WorkbookUpdateService.apply_batch_draft_update(
            ws=ws,
            updates=[("project_setup.technical.horizon_years", "15"), ("debt.senior.tenor_years", "10")],
            content_hash=tokens0["content_hash"],
            workbook_version=tokens0["workbook_version"],
            expected_scenario_id=ws.active_scenario_id,
            project_record=rec,
            actor_user_id=user,
        )
        assert pis is not None
        assert _get_tokens()["content_hash"] != tokens0["content_hash"]


# ── 2. C1F-A-1 / P1-OPEX-02: Single-Field Line-Owned Cost Scalar Refusal ─────


def test_slice_d_c1f_a1_single_field_refuses_line_owned_capex_and_opex_scalars(tmp_path):
    user = "test-slice-d-lines"
    db.DB_PATH = str(tmp_path / "sliced_lines.db")
    db.init_db()
    app = FastAPI()
    app.include_router(v2_router, prefix="/v2")
    app.include_router(react_workspace_router, prefix="/v2")

    with TestClient(app) as client:
        client.cookies.set(COOKIE_NAME, create_session_token(user_id=user, username="admin"))
        rec = create_reference_seeded_project(
            user_id=user,
            requested_name="Slice D Lines",
            template_source="generic_solar_reference",
            capacity_mw=16,
        )
        tokens = react_workbook_tokens(client, rec.project_code)
        req_ns = SimpleNamespace(cookies=client.cookies, state=SimpleNamespace())

        # Reference-seeded project has active CAPEX & OPEX cost lines -> scalar edit MUST refuse
        for fid in ("capex.C.grid_connection", "opex.lines.insurance"):
            resp = client.post(
                "/v2/workbook/update",
                data={
                    "project": rec.project_code,
                    "field_id": fid,
                    "value": "12345",
                    **tokens,
                    "csrf_token": mutation_token(req_ns, rec.project_code, "workbook-update"),
                },
                follow_redirects=False,
            )
            assert "COST_CATEGORY_LINE_OWNED" in (resp.headers.get("location", "") + resp.text), (fid, resp.status_code, resp.headers.get("location", ""), resp.text[:400])


# ── 3. C1F-C-1: Prospective Acquisition Date Validation Against Source Horizon


def test_slice_d_c1f_c1_acquisition_date_validation_rules():
    evidence = {
        "currency": "EUR",
        "unit": "kEUR",
        "authority": "COVENANT_GATED_G2C_AND_C1_PROJECT_RETURN",
        "equity_periods": [
            {"date": "2031-06-30", "net_legal_dividend_keur": 0.0, "legal_equity_contribution_keur": 500.0},
            {"date": "2031-12-31", "net_legal_dividend_keur": 200.0, "legal_equity_contribution_keur": 0.0},
            {"date": "2040-12-31", "net_legal_dividend_keur": 300.0, "legal_equity_contribution_keur": 0.0},
        ],
    }
    base_kw = dict(
        purchase_price_keur=1000.0,
        transaction_costs_keur=0.0,
        buyer_discount_rate=0.08,
        target_buyer_irr=0.08,
        bid_lower_bound_keur=100.0,
        bid_upper_bound_keur=5000.0,
    )

    # Closing on or after last source period -> CLOSING_NOT_WITHIN_SOURCE_HORIZON
    with pytest.raises(AcquisitionPolicyError, match="CLOSING_NOT_WITHIN_SOURCE_HORIZON"):
        validate_acquisition_dates_against_source(
            evidence,
            AcquisitionTerms(closing_date=date(2040, 12, 31), **base_kw),
        )

    # Exit beyond last source period -> EXIT_BEYOND_SOURCE_HORIZON
    with pytest.raises(AcquisitionPolicyError, match="EXIT_BEYOND_SOURCE_HORIZON"):
        validate_acquisition_dates_against_source(
            evidence,
            AcquisitionTerms(
                closing_date=date(2032, 1, 15),
                exit_date=date(2041, 6, 30),
                exit_proceeds_keur=500.0,
                **base_kw,
            ),
        )

    # Closing on a date with non-zero dividend/contribution -> CLOSING_DATE_ENTITLEMENT_ORDER_AMBIGUOUS
    with pytest.raises(AcquisitionPolicyError, match="CLOSING_DATE_ENTITLEMENT_ORDER_AMBIGUOUS"):
        validate_acquisition_dates_against_source(
            evidence,
            AcquisitionTerms(closing_date=date(2031, 12, 31), **base_kw),
        )

    # Valid in-horizon closing & exit dates pass cleanly
    rows = validate_acquisition_dates_against_source(
        evidence,
        AcquisitionTerms(
            closing_date=date(2032, 1, 15),
            exit_date=date(2040, 12, 31),
            exit_proceeds_keur=500.0,
            **base_kw,
        ),
    )
    assert len(rows) == 3


# ── 4. P1-FIN-01 & P1-FIN-02: Senior Debt Parity & Staged Construction S&U ──

# Established reconciliation tolerance policy (FINCO 36 Correction H):
# - Independent Decimal(50) construction draw / IDC / fee / capitalization / S&U arithmetic: <= 0.01 kEUR
# - Operating senior debt roll-forward & BS / CFS / P&L statement coherence: <= 0.01 kEUR
_FIN_TOL_KEUR = Decimal("0.01")


def _independent_construction_schedule_decimal(
    pi,
    *,
    senior_commitment_keur: Decimal,
    dsra_fc_use_keur: Decimal,
) -> dict:
    """Independently derive period construction CAPEX, draws, LMA ACT/360 IDC, fees and S&U in Decimal(50).

    Uses ONLY canonical ProjectInputs + sized senior commitment and FC DSRA use — never engine outputs.
    """
    from datetime import timedelta

    eng = PeriodEngine(
        financial_close=pi.info.financial_close,
        construction_months=pi.info.construction_months,
        horizon_years=pi.info.horizon_years,
        ppa_years=int(pi.revenue.ppa_term_years),
        cod_date=pi.info.cod_date,
    )
    c_periods = [p for p in eng.periods() if p.is_construction]
    n = len(c_periods)
    assert n > 0

    # 1. Inclusive construction period dates and LMA ACT/360 fractions
    period_bounds = [(p.start_date, p.end_date - timedelta(days=1)) for p in c_periods]
    fractions = [Decimal((end - start).days + 1) / Decimal(360) for start, end in period_bounds]

    # 2. Hard CAPEX per construction period directly from pi.capex items
    hard_capex = [Decimal("0")] * n
    for code in pi.capex._CAPEX_ITEM_FIELDS:
        item = getattr(pi.capex, code)
        amt = _d(item.amount_keur)
        if amt <= 0:
            continue
        hard_capex[0] += amt * _d(item.y0_share)
        for idx, share in enumerate(item.spending_profile):
            hard_capex[idx] += amt * _d(share)

    # 3. Contractual rates and sponsor equity inputs
    rate_sched = pi.financing.senior_debt_interest_config.rate_schedule
    if getattr(rate_sched, "explicit_all_in_rates", None):
        senior_rate = _d(rate_sched.explicit_all_in_rates[0])
    else:
        senior_rate = _d(pi.financing.all_in_rate)
    commit_fee_rate = _d(pi.financing.commitment_fee)
    struct_fee_rate = _d(pi.financing.structuring_fee) + _d(pi.financing.arrangement_fee)
    struct_fee_0 = senior_commitment_keur * struct_fee_rate
    share_capital = _d(pi.financing.share_capital_keur)

    # 4. Independent fixed-point over construction periods (sponsor-first waterfall: Share Capital -> SHL -> Senior)
    idc_total_est = Decimal("0")
    cfee_total_est = Decimal("0")
    hard_total = sum(hard_capex, Decimal("0"))
    rows = []
    converged = False
    for _ in range(50):
        total_uses_est = hard_total + struct_fee_0 + idc_total_est + cfee_total_est + dsra_fc_use_keur
        shl_total = max(Decimal("0"), total_uses_est - senior_commitment_keur - share_capital)
        rem_sc = share_capital
        rem_shl = shl_total
        opening_senior = Decimal("0")
        rows = []
        for t in range(n):
            frac = fractions[t]
            idc_t = opening_senior * senior_rate * frac
            cfee_t = (senior_commitment_keur - opening_senior) * commit_fee_rate * frac
            sfee_t = struct_fee_0 if t == 0 else Decimal("0")
            uses_t = hard_capex[t] + sfee_t + idc_t + cfee_t

            sc_draw = min(rem_sc, uses_t)
            rem_sc -= sc_draw
            shl_draw = min(rem_shl, uses_t - sc_draw)
            rem_shl -= shl_draw
            senior_draw = uses_t - sc_draw - shl_draw
            closing_senior = opening_senior + senior_draw

            rows.append({
                "start": period_bounds[t][0],
                "end": period_bounds[t][1],
                "fraction": frac,
                "hard_capex": hard_capex[t],
                "struct_fee": sfee_t,
                "idc": idc_t,
                "commit_fee": cfee_t,
                "uses": uses_t,
                "sc_draw": sc_draw,
                "shl_draw": shl_draw,
                "senior_draw": senior_draw,
                "opening_senior": opening_senior,
                "closing_senior": closing_senior,
            })
            opening_senior = closing_senior

        new_idc = sum((r["idc"] for r in rows), Decimal("0"))
        new_cfee = sum((r["commit_fee"] for r in rows), Decimal("0"))
        if abs(new_idc - idc_total_est) < Decimal("1e-12") and abs(new_cfee - cfee_total_est) < Decimal("1e-12"):
            idc_total_est, cfee_total_est = new_idc, new_cfee
            converged = True
            break
        idc_total_est, cfee_total_est = new_idc, new_cfee
    assert converged, "Independent Decimal(50) construction draw/IDC fixed-point did not converge within 50 iterations"

    total_cap_fin = idc_total_est + cfee_total_est + struct_fee_0
    total_uses = hard_total + total_cap_fin + dsra_fc_use_keur
    shl_total = max(Decimal("0"), total_uses - senior_commitment_keur - share_capital)
    return {
        "rows": rows,
        "hard_capex_total": hard_total,
        "idc_total": idc_total_est,
        "commit_fee_total": cfee_total_est,
        "struct_fee_total": struct_fee_0,
        "total_cap_fin": total_cap_fin,
        "gfa_at_cod": hard_total + total_cap_fin,
        "dsra_fc_use": dsra_fc_use_keur,
        "total_uses": total_uses,
        "share_capital": share_capital,
        "shl_total": shl_total,
        "senior_commitment": senior_commitment_keur,
    }


def _assert_construction_and_operating_coherence(
    pi,
    run,
    *,
    expected_final_date: date | None = None,
    override_cf=None,
    override_bs_periods=None,
) -> dict:
    """Verify construction draws, LMA ACT/360 IDC, capitalization bridge, S&U, and BS/CFS/P&L coherence."""
    from financial_engine.financing.generic_product_policy import build_sources_and_uses

    fin = run.g2c_result.financing_result
    cf = override_cf if override_cf is not None else fin.construction_financing
    fund = fin.construction_funding
    su = build_sources_and_uses(fin)
    mr = fin.project_model_result
    sd = mr.senior_debt
    fs = run.financial_statements_result
    bs_periods = override_bs_periods if override_bs_periods is not None else fs.balance_sheet_periods

    dsra_fc = _d(fund.non_construction_fc_use.uses_keur) if fund.non_construction_fc_use is not None else Decimal("0")
    oracle = _independent_construction_schedule_decimal(
        pi,
        senior_commitment_keur=_d(cf.final_senior_commitment_keur),
        dsra_fc_use_keur=dsra_fc,
    )

    # 1. Construction period-by-period draw, IDC (ACT/360), fee, and funding waterfall parity
    n_c = len(oracle["rows"])
    assert len(cf.period_start_dates) == n_c
    assert len(fund.periods) == n_c

    cum_uses = Decimal("0")
    cum_sc = Decimal("0")
    cum_shl = Decimal("0")
    cum_senior = Decimal("0")
    for t, exp in enumerate(oracle["rows"]):
        assert cf.period_start_dates[t] == exp["start"]
        assert cf.period_end_dates[t] == exp["end"]
        assert abs(_d(cf.hard_capex_uses_keur[t]) - exp["hard_capex"]) <= _FIN_TOL_KEUR
        assert abs(_d(cf.senior_idc_accrual_keur[t]) - exp["idc"]) <= _FIN_TOL_KEUR
        assert abs(_d(cf.senior_idc_capitalized_uses_keur[t]) - exp["idc"]) <= _FIN_TOL_KEUR
        assert abs(_d(cf.senior_commitment_fee_accrual_keur[t]) - exp["commit_fee"]) <= _FIN_TOL_KEUR
        assert abs(_d(cf.senior_draws_keur[t]) - exp["senior_draw"]) <= _FIN_TOL_KEUR

        fp = fund.periods[t]
        assert abs(_d(fp.project_cash_uses_keur) - exp["uses"]) <= _FIN_TOL_KEUR
        assert abs(_d(fp.share_capital_draw_keur) - exp["sc_draw"]) <= _FIN_TOL_KEUR
        assert abs(_d(fp.shl_cash_draw_keur) - exp["shl_draw"]) <= _FIN_TOL_KEUR
        assert abs(_d(fp.senior_draw_keur) - exp["senior_draw"]) <= _FIN_TOL_KEUR

        cum_uses += exp["uses"]
        cum_sc += exp["sc_draw"]
        cum_shl += exp["shl_draw"]
        cum_senior += exp["senior_draw"]
        assert abs(_d(fp.cumulative_project_cash_uses_keur) - cum_uses) <= _FIN_TOL_KEUR
        assert abs(_d(fp.cumulative_senior_draw_keur) - cum_senior) <= _FIN_TOL_KEUR
        assert abs(_d(fp.cumulative_shl_cash_draw_keur) - cum_shl) <= _FIN_TOL_KEUR
        assert abs(_d(fp.cumulative_share_capital_draw_keur) - cum_sc) <= _FIN_TOL_KEUR

        # Staged construction BS row matches cumulative funding (and cumulative capitalized uses where not E2E-05 pre-COD CIT guarded)
        bs_c = bs_periods[t]
        assert abs(_d(bs_c.senior_debt_balance_keur) - cum_senior) <= _FIN_TOL_KEUR
        assert abs(_d(bs_c.share_capital_keur) - cum_sc) <= _FIN_TOL_KEUR
        assert abs(_d(bs_c.shl_balance_keur) - cum_shl) <= _FIN_TOL_KEUR
        if bs_c.gross_fixed_assets_keur is not None:
            assert abs(_d(bs_c.gross_fixed_assets_keur) - cum_uses) <= _FIN_TOL_KEUR
            bs_assets = _d(bs_c.gross_fixed_assets_keur) + _d(bs_c.dsra_balance_keur or 0.0) + _d(bs_c.unrestricted_cash_keur or 0.0)
            bs_le = (
                _d(bs_c.senior_debt_balance_keur)
                + _d(bs_c.shl_balance_keur)
                + _d(bs_c.share_capital_keur)
                + _d(bs_c.share_premium_keur or 0.0)
                + _d(bs_c.additional_equity_keur or 0.0)
                + _d(bs_c.retained_earnings_keur or 0.0)
                + _d(bs_c.net_cit_payable_keur or 0.0)
            )
            assert abs(bs_assets - bs_le) <= _FIN_TOL_KEUR
        if bs_c.balance_check_keur is not None:
            assert abs(_d(bs_c.balance_check_keur)) <= _FIN_TOL_KEUR

    # 2. Capitalization bridge into COD & first operating period
    assert abs(_d(cf.total_capitalized_financing_keur) - oracle["total_cap_fin"]) <= _FIN_TOL_KEUR
    assert abs(_d(cf.senior_commitment_fee_capitalized_keur) - oracle["commit_fee_total"]) <= _FIN_TOL_KEUR
    assert abs(_d(sum(cf.structuring_fee_keur)) - oracle["struct_fee_total"]) <= _FIN_TOL_KEUR
    # First operating period BS carries full capitalized GFA (hard CAPEX + IDC + commitment fee + structuring fee)
    assert abs(_d(bs_periods[n_c].gross_fixed_assets_keur) - oracle["gfa_at_cod"]) <= _FIN_TOL_KEUR

    # Closing construction senior draws + FC DSRA senior draw == senior commitment == first operating period opening debt
    dsra_senior_draw = (
        _d(fund.non_construction_fc_use.senior_draw_keur) if fund.non_construction_fc_use is not None else Decimal("0")
    )
    assert abs((cum_senior + dsra_senior_draw) - oracle["senior_commitment"]) <= _FIN_TOL_KEUR
    first_op_period_idx = next(p.period_index for p in mr.periods if p.is_operation)
    sd_first_op_pos = sd.period_indices.index(first_op_period_idx)
    assert abs(_d(sd.senior_debt_opening_keur[sd_first_op_pos]) - oracle["senior_commitment"]) <= _FIN_TOL_KEUR

    # 3. Total S&U closure against independent Decimal oracle
    assert abs(_d(su.base_project_capex_keur) - oracle["hard_capex_total"]) <= _FIN_TOL_KEUR
    assert abs(_d(su.capitalized_idc_keur) - oracle["idc_total"]) <= _FIN_TOL_KEUR
    assert abs(_d(su.commitment_fee_keur) - oracle["commit_fee_total"]) <= _FIN_TOL_KEUR
    assert abs(_d(su.structuring_fee_keur) - oracle["struct_fee_total"]) <= _FIN_TOL_KEUR
    assert abs(_d(su.initial_dsra_funding_keur) - oracle["dsra_fc_use"]) <= _FIN_TOL_KEUR
    assert abs(_d(su.total_uses_keur) - oracle["total_uses"]) <= _FIN_TOL_KEUR
    assert abs(_d(su.total_sources_keur) - oracle["total_uses"]) <= _FIN_TOL_KEUR
    assert abs(_d(su.shareholder_loan_cash_keur) - oracle["shl_total"]) <= _FIN_TOL_KEUR
    assert abs(_d(su.difference_keur)) <= _FIN_TOL_KEUR

    # 4. Operating senior debt roll-forward & BS / P&L / CFS coherence
    periods_by_idx = {p.period_index: p for p in mr.periods}
    for i, idx in enumerate(sd.period_indices):
        p = periods_by_idx[idx]
        if not p.is_operation:
            continue
        opening = _d(sd.senior_debt_opening_keur[i])
        principal = _d(sd.senior_principal_keur[i])
        closing = _d(sd.senior_debt_closing_keur[i])
        interest = _d(sd.senior_interest_keur[i])
        ds = _d(sd.senior_debt_service_keur[i])
        assert abs((opening - principal) - closing) <= _FIN_TOL_KEUR
        assert abs((interest + principal) - ds) <= _FIN_TOL_KEUR

    for row in bs_periods:
        if row.balance_check_keur is not None:
            assert abs(_d(row.balance_check_keur)) <= _FIN_TOL_KEUR

    for prow in fs.income_statement_periods:
        ebit_calc = _d(prow.revenue_keur) - _d(prow.opex_keur) - _d(prow.book_depreciation_keur)
        assert abs(ebit_calc - _d(prow.ebit_keur)) <= _FIN_TOL_KEUR

    for crow in fs.pf_cash_waterfall_periods:
        ebitda_calc = _d(crow.revenue_cash_keur) - _d(crow.opex_cash_keur)
        assert abs(ebitda_calc - _d(crow.ebitda_keur)) <= _FIN_TOL_KEUR

    # 5. Terminal date / final stub check (for dated R04 runs and legacy controls)
    if expected_final_date is not None:
        assert bs_periods[-1].period_end == expected_final_date, (
            f"Expected terminal period_end {expected_final_date}, got {bs_periods[-1].period_end}"
        )

    return oracle


@pytest.mark.parametrize("kind", ["solar", "wind"])
def test_slice_d_p1_fin_01_and_02_senior_debt_decimal_parity_and_construction_bs(kind):
    """P1-FIN-01 & P1-FIN-02: independent Decimal(50) construction draw/IDC/capitalization/S&U & operating parity.

    Covers staged construction Solar (mid-period COD 2031-03-01) and Wind (mid-period COD 2031-09-01) on BOTH
    legacy reference controls and the dated R04 path (with final operating stub).
    """
    import json
    from app.workbook.revenue_multistream import apply_config
    from tests.test_fable_batch3_r04_review_route import MERCHANT, _ppa

    base = getattr(pf, f"create_generic_{kind}_reference")()
    cod = base.info.cod_date
    horizon_end = f"{cod.year + int(base.info.horizon_years)}-{cod.month:02d}-{cod.day:02d}"
    merchant = {**MERCHANT, "start_date": cod.isoformat(), "end_date": horizon_end}
    r04_json = json.dumps(
        {
            "version": 2,
            "technology": kind,
            "indexation_basis": "OPERATING_YEAR",
            "streams": [_ppa("ppa1", cod.isoformat(), f"{cod.year + 1}-{cod.month:02d}-{cod.day:02d}", 1000), merchant],
        },
        separators=(",", ":"),
    )
    dated_pi = apply_config(base, r04_json, project_type=kind)

    expected_dates = {
        ("solar", "legacy"): date(2055, 12, 31),
        ("solar", "dated_r04"): date(2056, 2, 29),
        ("wind", "legacy"): date(2058, 6, 30),
        ("wind", "dated_r04"): date(2058, 8, 31),
    }

    for mode, pi in (("legacy", base), ("dated_r04", dated_pi)):
        run = run_clean_production(pi, "Base", project_type=kind)
        oracle = _assert_construction_and_operating_coherence(
            pi,
            run,
            expected_final_date=expected_dates[(kind, mode)],
        )
        assert oracle["idc_total"] > Decimal("0"), f"{kind} {mode}: expected positive construction IDC"
        assert oracle["commit_fee_total"] > Decimal("0"), f"{kind} {mode}: expected positive commitment fee"


def test_slice_d_p1_fin_01_and_02_mutation_witnesses_wrong_draw_idc_and_missing_stub():
    """Targeted mutation witnesses: wrong construction draw, wrong ACT/365 IDC, and missing final stub MUST fail."""
    from app.workbook.revenue_multistream import apply_config
    from tests.test_fable_batch3_r04_review_route import MERCHANT, _ppa, book

    base = pf.create_generic_solar_reference()
    r04_json = book([_ppa("ppa1", "2031-03-01", "2032-03-01", 1000), MERCHANT])
    dated_pi = apply_config(base, r04_json, project_type="solar")
    run = run_clean_production(dated_pi, "Base", project_type="solar")
    cf = run.g2c_result.financing_result.construction_financing
    bs_periods = run.financial_statements_result.balance_sheet_periods

    # Witness 1: wrong senior draw (+50.0 kEUR in period 1) -> detected
    bad_draws = list(cf.senior_draws_keur)
    bad_draws[1] += 50.0
    with pytest.raises(AssertionError):
        _assert_construction_and_operating_coherence(
            dated_pi,
            run,
            expected_final_date=date(2056, 2, 29),
            override_cf=replace(cf, senior_draws_keur=tuple(bad_draws)),
        )

    # Witness 2: wrong IDC accrual (ACT/365 instead of LMA ACT/360) -> detected
    bad_idc = tuple(val * (360.0 / 365.0) for val in cf.senior_idc_accrual_keur)
    with pytest.raises(AssertionError):
        _assert_construction_and_operating_coherence(
            dated_pi,
            run,
            expected_final_date=date(2056, 2, 29),
            override_cf=replace(cf, senior_idc_accrual_keur=bad_idc),
        )

    # Witness 3: missing final operating stub (truncated last period) -> detected
    with pytest.raises(AssertionError):
        _assert_construction_and_operating_coherence(
            dated_pi,
            run,
            expected_final_date=date(2056, 2, 29),
            override_bs_periods=bs_periods[:-1],
        )


# ── 5. P1-REV-03: Dual % Merchant + EUR/MWh Balancing Basis Rejected (FINCO45A) ──


def test_slice_d_p1_rev_03_combined_percent_and_eur_mwh_balancing_additive():
    """Dual nonzero % merchant and per-MWh balancing must fail closed (DUAL_BALANCING_COST_BASIS_FORBIDDEN)."""
    base = pf.create_generic_solar_reference()
    pi = replace(
        base,
        revenue=replace(
            base.revenue,
            ppa_production_share=0.60,
            balancing_cost_pv=0.05,            # 5% of gross merchant revenue ONLY
            balancing_cost_eur_per_mwh=2.50,   # 2.50 EUR/MWh on total generation MWh
        ),
    )
    eng = PeriodEngine(
        financial_close=pi.info.financial_close,
        construction_months=pi.info.construction_months,
        horizon_years=pi.info.horizon_years,
        ppa_years=int(pi.revenue.ppa_term_years),
        cod_date=pi.info.cod_date,
    )
    with pytest.raises(ValueError, match="DUAL_BALANCING_COST_BASIS_FORBIDDEN"):
        revenue_decomposition_schedule(pi, eng)


# ── 6. F2-NEW-03: Tax Loss Continuity on DC & EV ─────────────────────────────


@pytest.mark.parametrize("kind", ["data_center", "ev_charging"])
def test_slice_d_f2_new_03_tax_loss_continuity(kind):
    pi = getattr(pf, f"create_generic_{kind}_reference")()
    run = run_clean_production(pi)
    tc = run.g2c_result.financing_result.project_model_result.tax_and_cfads
    prev_closing = None
    for ann in tc.annual_results:
        if prev_closing is not None:
            assert abs(ann.loss_opening_keur - prev_closing) <= 0.01
        calc_close = (
            ann.loss_opening_keur
            + ann.loss_generated_keur
            - ann.loss_used_keur
            - ann.loss_expired_keur
        )
        assert abs(calc_close - ann.loss_closing_keur) <= 0.01
        prev_closing = ann.loss_closing_keur
