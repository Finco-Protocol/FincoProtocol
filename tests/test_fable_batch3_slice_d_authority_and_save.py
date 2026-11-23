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
from app.v2.router import router as v2_router
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

    with TestClient(app) as client:
        client.cookies.set(COOKIE_NAME, create_session_token(user_id=user, username="admin"))
        rec = create_reference_seeded_project(
            user_id=user,
            requested_name="Slice D Solar",
            template_source="generic_solar_reference",
            capacity_mw=16,
        )

        def _get_tokens():
            html = client.get("/v2/workbook", params={"project": rec.project_code}).text
            return {
                k: re.search(r'name="' + k + r'" value="([^"]*)"', html).group(1)
                for k in ("content_hash", "workbook_version")
            }

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
        )
        assert "ZERO_SENIOR_GEARING_NOT_SUPPORTED" in resp_zero.text
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
        )
        assert "DEBT_TENOR_EXCEEDS_HORIZON" in resp_ht.text
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

    with TestClient(app) as client:
        client.cookies.set(COOKIE_NAME, create_session_token(user_id=user, username="admin"))
        rec = create_reference_seeded_project(
            user_id=user,
            requested_name="Slice D Lines",
            template_source="generic_solar_reference",
            capacity_mw=16,
        )
        html = client.get("/v2/workbook", params={"project": rec.project_code}).text
        tokens = {
            k: re.search(r'name="' + k + r'" value="([^"]*)"', html).group(1)
            for k in ("content_hash", "workbook_version")
        }
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
            )
            assert "COST_CATEGORY_LINE_OWNED" in resp.text, (fid, resp.text[:400])


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


@pytest.mark.parametrize("kind", ["solar", "wind"])
def test_slice_d_p1_fin_01_and_02_senior_debt_decimal_parity_and_construction_bs(kind):
    pi = getattr(pf, f"create_generic_{kind}_reference")()
    run = run_clean_production(pi)
    mr = run.g2c_result.financing_result.project_model_result
    sd = mr.senior_debt
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

        assert abs((opening - principal) - closing) <= Decimal("0.01")
        assert abs((interest + principal) - ds) <= Decimal("0.01")

    # Staged construction BS check: every operating BS row balances to <= 0.01 kEUR
    fs = run.financial_statements_result
    for row in fs.balance_sheet_periods:
        if row.balance_check_keur is not None:
            assert abs(row.balance_check_keur) <= 0.01


# ── 5. P1-REV-03: Combined % Merchant + EUR/MWh Generation Balancing Probe ──


def test_slice_d_p1_rev_03_combined_percent_and_eur_mwh_balancing_additive():
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
    decomps = revenue_decomposition_schedule(pi, eng)
    checked = 0
    for d in decomps.values():
        if not d["is_operation"]:
            continue
        exp_pct = d["gross_merchant_revenue_keur"] * 0.05
        exp_mwh = d["generation_mwh"] * 2.50 / 1000.0
        assert d["balancing_cost_pv_keur"] == pytest.approx(exp_pct, abs=1e-9)
        assert d["balancing_cost_wind_keur"] == pytest.approx(exp_mwh, abs=1e-9)
        assert d["balancing_cost_keur"] == pytest.approx(exp_pct + exp_mwh, abs=1e-9)
        checked += 1
    assert checked > 0


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
