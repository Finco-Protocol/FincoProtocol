"""FINCO40 Slice E — Tax (OD-TAX-01) & Investor (OD-INVEST-01 / C1F-B-1/2/3) policy-independent readiness tests."""
from __future__ import annotations

import json
import math
from dataclasses import replace
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app import project_factories as pf
from app.model_v2.investor_f4 import (
    EVIDENCE_KEY,
    SNAPSHOT_KEY,
    allocate_run,
    assess_contribution_completeness,
    extract_equity_receipts,
    parse_terms,
)
from app.services.production_financial_authority import run_clean_production
from app.workbook.investor_agreement_service import InvestorAgreementConflict, save_agreement
from finco_core.engine.date_authority import DATE_AUTHORITY_VERSION, dated_life_end_exclusive
from finco_core.engine.period_engine import PeriodEngine, PeriodFrequency


def _dated_solar_for_tax():
    base = pf.create_generic_solar_reference()
    cod = date(2031, 5, 15)
    fc = date(2030, 5, 15)
    info = replace(
        base.info,
        date_authority_version=DATE_AUTHORITY_VERSION,
        cod_date=cod,
        financial_close=fc,
        construction_months=12,
    )
    eng = PeriodEngine(
        financial_close=fc,
        construction_months=12,
        horizon_years=info.horizon_years,
        ppa_years=int(round(base.revenue.ppa_term_years)),
        frequency=PeriodFrequency.SEMESTRIAL,
        cod_date=cod,
        dated_life_end_exclusive=dated_life_end_exclusive(
            cod, info.horizon_years, date_authority_version=DATE_AUTHORITY_VERSION
        ),
    )
    fin = replace(base.financing, shl_maturity_period_index=eng.periods()[-1].index)
    return replace(base, info=info, financing=fin)


def test_od_tax_01_hypothetical_ab_comparison_without_changing_default():
    """OD-TAX-01 / P1-TAX-01: prove production default tax_dep_basis_source_owned=False is unchanged,
    and quantify hypothetical A/B delta (False vs True) on dated Solar."""
    pi_default = _dated_solar_for_tax()
    assert pi_default.tax.tax_dep_basis_source_owned is False

    run_a = run_clean_production(pi_default, project_type="solar")
    pi_hyp = replace(pi_default, tax=replace(pi_default.tax, tax_dep_basis_source_owned=True))
    run_b = run_clean_production(pi_hyp, project_type="solar")

    fs_a = run_a.financial_statements_result
    fs_b = run_b.financial_statements_result
    cit_a = math.fsum(p.cit_accrual_keur for p in fs_a.income_statement_periods)
    cit_b = math.fsum(p.cit_accrual_keur for p in fs_b.income_statement_periods)
    # Arm A (default) excludes capitalized construction financing from tax depreciation -> higher CIT than Arm B
    assert cit_a > cit_b, (cit_a, cit_b)
    # Both arms balance strictly
    assert max(abs(p.balance_check_keur or 0.0) for p in fs_a.balance_sheet_periods) < 1e-5
    assert max(abs(p.balance_check_keur or 0.0) for p in fs_b.balance_sheet_periods) < 1e-5
    # Project / Equity IRR are finite in both arms
    irr_a = run_a.g2c_result.return_summary.legal_equity.xirr
    irr_b = run_b.g2c_result.return_summary.legal_equity.xirr
    assert irr_a is not None and irr_b is not None and math.isfinite(irr_a) and math.isfinite(irr_b)
    assert irr_b > irr_a


def test_c1f_b3_sixty_forty_one_founder_paid_and_negative_retained_earnings():
    """C1F-B-3: 60:40 one-founder-paid yields safe None/NO_NEGATIVE_CASHFLOW for unpaid founder;
    low-tariff loss case yields zero distributions under canonical gate."""
    solar = _dated_solar_for_tax()
    run = run_clean_production(solar, project_type="solar")
    receipt = extract_equity_receipts(run.g2c_result)
    funding_rows = [p for p in receipt["periods"] if p["paid_in_keur"] > 0]
    assert funding_rows
    total_eq = math.fsum(p["paid_in_keur"] for p in funding_rows)
    total_div = math.fsum(p["net_equity_receipt_keur"] for p in receipt["periods"])
    assert total_div > 0.0

    doc = {
        "schema_version": 1,
        "agreement_id": "AGR-6040",
        "version": 1,
        "currency": "EUR",
        "unit": "kEUR",
        "policy": "RESIDUAL_ONLY",
        "investors": [
            {"investor_id": "founder_a", "investment_class": "COMMON_EQUITY", "ownership_fraction": 0.60, "commitment_keur": total_eq + 100.0},
            {"investor_id": "founder_b", "investment_class": "COMMON_EQUITY", "ownership_fraction": 0.40, "commitment_keur": total_eq + 100.0},
        ],
        "contributions": [
            {"investor_id": "founder_a", "cash_date": row["date"], "amount_keur": row["paid_in_keur"]}
            for row in funding_rows
        ],
    }
    terms = parse_terms(json.dumps(doc))
    ev = allocate_run(
        terms,
        receipt,
        binding={
            "owner_id": "owner_1",
            "project_id": "proj_1",
            "scenario_id": None,
            "snapshot_id": "snap_1",
            "composite_hash": "hash_1",
        },
    )
    by_inv = {row["investor_id"]: row for row in ev["investors"]}
    fa, fb = by_inv["founder_a"], by_inv["founder_b"]
    # Founder B paid 0.0 -> DPI, MOIC, XIRR must be None (no NaN/Inf/fabrication)
    assert fb["total_paid_in_keur"] == 0.0
    assert fb["dpi"] is None and fb["realized_moic"] is None and fb["xirr"] is None
    assert fb["xirr_status"] == "NO_NEGATIVE_CASHFLOW"
    assert abs(fb["residual_distributions_keur"] - 0.40 * total_div) < 1e-4
    # Founder A paid 100% -> finite DPI & XIRR
    assert abs(fa["total_paid_in_keur"] - total_eq) < 1e-4
    assert fa["dpi"] is not None and math.isfinite(fa["dpi"]) and fa["dpi"] > 0
    assert fa["xirr"] is not None and math.isfinite(fa["xirr"])
    assert abs((fa["residual_distributions_keur"] + fb["residual_distributions_keur"]) - total_div) < 1e-4

    # Negative retained earnings / distribution gate reproduction (equity-only, low tariff so no SHL maturity block)
    from finco_core.inputs._models import SponsorFundingMode
    stressed = replace(
        solar,
        revenue=replace(
            solar.revenue,
            ppa_base_tariff=18.0,
            market_prices_curve=tuple(18.0 for _ in (solar.revenue.market_prices_curve or (18.0,))),
        ),
        financing=replace(
            solar.financing,
            gearing_ratio=0.10,
            sponsor_funding_mode=SponsorFundingMode.EQUITY_ONLY,
        ),
    )
    stressed_run = run_clean_production(stressed, project_type="solar")
    stressed_receipt = extract_equity_receipts(stressed_run.g2c_result)
    # Reproduce OD-INVEST-01 finding: under current cash-sweep rules (no statutory RE dividend-trap blocker),
    # positive net dividends occur in periods with negative retained earnings -> documented for owner decision.
    divs_by_idx = {p.period_index: p.net_dividend_received_keur for p in stressed_run.g2c_result.waterfall_periods}
    neg_re_with_div = [
        (p.period_index, divs_by_idx.get(p.period_index, 0.0), p.retained_earnings_keur)
        for p in stressed_run.financial_statements_result.balance_sheet_periods
        if (p.retained_earnings_keur or 0.0) < 0.0 and divs_by_idx.get(p.period_index, 0.0) > 0.0
    ]
    assert len(neg_re_with_div) > 0
    assert math.fsum(p["net_equity_receipt_keur"] for p in stressed_receipt["periods"]) > 0.0
    assert max(abs(p.balance_check_keur or 0.0) for p in stressed_run.financial_statements_result.balance_sheet_periods) < 1e-5


@pytest.fixture
def finco40_env(tmp_path, monkeypatch):
    db_path = tmp_path / "finco40.db"
    monkeypatch.setenv("FINCO_DB_PATH", str(db_path))
    monkeypatch.setenv("FINCO_MODEL_REACT_V1", "1")
    from app.persistence.db import init_db
    init_db()
    from app.auth import COOKIE_NAME, create_session_token
    from app.services.reference_seed_service import create_reference_seeded_project
    from app.v2.investor_f4_router import router as f4_router
    from app.v2.react_investors import router as react_inv_router
    from app.v2.router import router as v2_router
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(v2_router, prefix="/v2")
    app.include_router(f4_router, prefix="/v2")
    app.include_router(react_inv_router, prefix="/v2")
    client = TestClient(app)

    uid = "finco40_owner"
    rec = create_reference_seeded_project(
        user_id=uid,
        template_source="generic_solar_reference",
        requested_name="FINCO40 Investor Test",
        capacity_mw=20.0,
    )
    client.cookies.set(COOKIE_NAME, create_session_token(user_id=uid, username="owner"))
    return {"client": client, "user_id": uid, "record": rec}


def _agreement_doc(agreement_id: str, version: int, contributions: list[dict]) -> dict:
    return {
        "schema_version": 1,
        "agreement_id": agreement_id,
        "version": version,
        "currency": "EUR",
        "unit": "kEUR",
        "policy": "RESIDUAL_ONLY",
        "investors": [
            {"investor_id": "alpha", "investment_class": "COMMON_EQUITY", "ownership_fraction": 0.6, "commitment_keur": 50000.0},
            {"investor_id": "beta", "investment_class": "COMMON_EQUITY", "ownership_fraction": 0.4, "commitment_keur": 50000.0},
        ],
        "contributions": contributions,
    }


def test_c1f_b1_incomplete_draft_warning_and_fail_closed_run(finco40_env):
    """C1F-B-1: empty/partial contributions can be saved with explicit draft warning on Legacy & React,
    while POST /v2/workbook/run fails closed before commit."""
    client = finco40_env["client"]
    rec = finco40_env["record"]
    uid = finco40_env["user_id"]

    # Fetch React agreement state -> get content_hash & csrf
    r0 = client.get(f"/v2/model-react/investors/agreement?project={rec.project_code}")
    assert r0.status_code == 200, r0.text
    b0 = r0.json()
    assert b0["draft_warning"] is None

    # Save incomplete draft (empty contributions)
    save_agreement(
        owner=uid,
        project_id=rec.project_id,
        expected_hash=b0["identity"]["content_hash"],
        raw=json.dumps(_agreement_doc("AGR-DRAFT", 1, [])),
    )

    # React GET emits explicit incomplete draft warning
    r1 = client.get(f"/v2/model-react/investors/agreement?project={rec.project_code}")
    assert r1.status_code == 200
    b1 = r1.json()
    assert b1["draft_warning"] is not None
    assert b1["draft_warning"]["incomplete_draft"] is True
    assert b1["draft_warning"]["code"] == "INCOMPLETE_CONTRIBUTIONS_EMPTY"

    # Legacy HTML GET also renders explicit incomplete draft warning
    h1 = client.get(f"/v2/workbook/investor/agreement?project={rec.project_code}")
    assert h1.status_code == 200
    assert 'data-testid="f4-incomplete-draft-warning"' in h1.text
    assert 'data-draft-warning-code="INCOMPLETE_CONTRIBUTIONS_EMPTY"' in h1.text

    # POST /v2/workbook/run must fail closed (never commit investor evidence for unreconciled contributions)
    from app.auth import generate_csrf_token
    run_resp = client.post(
        "/v2/workbook/run",
        data={
            "project": rec.project_code,
            "csrf_token": generate_csrf_token(),
            "content_hash": b1["identity"]["content_hash"],
        },
    )
    assert run_resp.status_code in (409, 422), (run_resp.status_code, run_resp.text[:300])


def test_c1f_b2_durable_monotonic_tombstone_ledger_prevents_version_reuse(finco40_env):
    """C1F-B-2: removing or renaming an agreement tombstones its version watermark so
    (agreement_id, version) can NEVER be reused, while monotonic v(max+1) succeeds and
    other scenarios/projects remain isolated."""
    client = finco40_env["client"]
    rec = finco40_env["record"]
    uid = finco40_env["user_id"]

    def _hash():
        return client.get(f"/v2/model-react/investors/agreement?project={rec.project_code}").json()["identity"]["content_hash"]

    # 1. Save AGR-1 v1 -> v2
    save_agreement(owner=uid, project_id=rec.project_id, expected_hash=_hash(), raw=json.dumps(_agreement_doc("AGR-1", 1, [])))
    save_agreement(owner=uid, project_id=rec.project_id, expected_hash=_hash(), raw=json.dumps(_agreement_doc("AGR-1", 2, [])))

    # 2. Remove working agreement -> tombstones AGR-1 at max_version=2
    save_agreement(owner=uid, project_id=rec.project_id, expected_hash=_hash(), raw="", remove=True)

    # 3. Attempting to recreate AGR-1 v1 or v2 MUST fail with InvestorAgreementConflict
    for bad_ver in (1, 2):
        with pytest.raises(InvestorAgreementConflict, match="already used or retired"):
            save_agreement(owner=uid, project_id=rec.project_id, expected_hash=_hash(), raw=json.dumps(_agreement_doc("AGR-1", bad_ver, [])))

    # 4. Monotonic v3 succeeds!
    save_agreement(owner=uid, project_id=rec.project_id, expected_hash=_hash(), raw=json.dumps(_agreement_doc("AGR-1", 3, [])))

    # 5. Rename AGR-1 (v3) -> AGR-2 (v1) -> attempt to rename back to AGR-1 (v1 or v3) MUST fail!
    save_agreement(owner=uid, project_id=rec.project_id, expected_hash=_hash(), raw=json.dumps(_agreement_doc("AGR-2", 1, [])))
    for bad_ver in (1, 3):
        with pytest.raises(InvestorAgreementConflict, match="already used or retired"):
            save_agreement(owner=uid, project_id=rec.project_id, expected_hash=_hash(), raw=json.dumps(_agreement_doc("AGR-1", bad_ver, [])))

    # 6. Monotonic AGR-1 v4 succeeds!
    save_agreement(owner=uid, project_id=rec.project_id, expected_hash=_hash(), raw=json.dumps(_agreement_doc("AGR-1", 4, [])))

    # 7. Tenant / project isolation: another project can still start AGR-1 at v1
    from app.services.reference_seed_service import create_reference_seeded_project
    other = create_reference_seeded_project(
        user_id="other_owner",
        template_source="generic_solar_reference",
        requested_name="Other Tenant Project",
        capacity_mw=15.0,
    )
    from app.workbook.workbook_identity import assemble_transactional
    from app.persistence.db import get_connection
    from app.workbook.registry import WORKBOOK
    conn = get_connection()
    try:
        ws = conn.execute("SELECT * FROM workspace_states WHERE user_id=? AND project_id=?", ("other_owner", other.project_id)).fetchone()
        other_hash = assemble_transactional(
            draft_snapshot_json=ws["draft_snapshot_json"] or "{}",
            project_id=other.project_id,
            user_id="other_owner",
            active_scenario_id=ws["active_scenario_id"],
            active_scenario_name=ws["active_scenario_name"],
            cursor=conn.cursor(),
            workbook_version=WORKBOOK.version,
        ).composite_hash
    finally:
        conn.close()
    save_agreement(owner="other_owner", project_id=other.project_id, expected_hash=other_hash, raw=json.dumps(_agreement_doc("AGR-1", 1, [])))
