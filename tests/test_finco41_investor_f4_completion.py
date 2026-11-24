"""FINCO41-B — Investor F4 policy-independent completion, Decimal oracle, ledger UX & OD-INVEST-01 5-option analysis."""
from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal, localcontext
import json
import math
import re

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import project_factories as pf
from app.auth import COOKIE_NAME, create_session_token, generate_csrf_token
from app.model_v2.investor_f4 import (
    EVIDENCE_KEY,
    InvestorAgreementInputError,
    allocate_run,
    assess_contribution_completeness,
    extract_equity_receipts,
    parse_terms,
    validate_evidence,
)
from app.model_v2.investor_f4_candidate.p2_contracts import parse_contract as parse_p2_contract
from app.model_v2.investor_f4_candidate.p2_evaluator import evaluate_p2_candidate
from app.persistence import db as persistence_db
from app.persistence.investor_agreement_ledger_repository import list_scope_versions
from app.persistence.run_history_repository import get_run_history
from app.runtime.model_execution import ModelExecutor, ModelExecutionConfig, reset_model_executor_for_tests
from app.services.production_financial_authority import run_clean_production
from app.workbook.investor_agreement_service import InvestorAgreementConflict, save_agreement
from app.workbook.registry import WORKBOOK
from app.workbook.workbook_identity import assemble_consistent_for_get
from finco_core.engine.date_authority import DATE_AUTHORITY_VERSION, dated_life_end_exclusive
from finco_core.engine.period_engine import PeriodEngine, PeriodFrequency
from finco_core.inputs._models import SponsorFundingMode
from finco_core.inputs.distribution_accounting_policy import (
    DistributionAccountingAuthority,
    DistributionAccountingPolicy,
    OpeningUCAuthority,
)
from tests.model_mutation_csrf import post_valid_mutation
from tests.run_clone_csrf import post_valid_csrf


# ---------------------------------------------------------------------------
# Independent 40-digit Decimal oracle (ZERO calls to run_waterfall / robust_xirr)
# ---------------------------------------------------------------------------

def _dec(v) -> Decimal:
    return Decimal(str(v))


def _oracle_xnpv(rate: Decimal, flows: list[tuple[date, Decimal]]) -> Decimal:
    with localcontext() as ctx:
        ctx.prec = 50
        d0 = flows[0][0]
        base = Decimal(1) + rate
        return sum(amt / (base ** (Decimal((d - d0).days) / Decimal(365))) for d, amt in flows)


def _oracle_xirr(flows: list[tuple[date, Decimal]]) -> Decimal | None:
    if not any(a < 0 for _, a in flows) or not any(a > 0 for _, a in flows):
        return None
    with localcontext() as ctx:
        ctx.prec = 50
        lo = Decimal("-0.999")
        hi = Decimal("20.0")
        f_lo = _oracle_xnpv(lo, flows)
        for _ in range(180):
            mid = (lo + hi) / Decimal(2)
            f_mid = _oracle_xnpv(mid, flows)
            if f_mid == 0:
                return mid
            if (f_lo > 0 and f_mid > 0) or (f_lo < 0 and f_mid < 0):
                lo, f_lo = mid, f_mid
            else:
                hi = mid
        return (lo + hi) / Decimal(2)


def _oracle_investor_accounts(terms, receipt: dict) -> dict[str, dict]:
    with localcontext() as ctx:
        ctx.prec = 50
        periods = receipt["periods"]
        per_inv: dict[str, dict] = {}
        for inv in terms.investors:
            frac = _dec(inv.ownership_fraction)
            paid_total = Decimal(0)
            dist_total = Decimal(0)
            flows: list[tuple[date, Decimal]] = []
            for p in periods:
                d = date.fromisoformat(p["date"])
                contrib = sum(
                    (_dec(c.amount_keur) for c in terms.contributions if c.investor_id == inv.investor_id and c.cash_date == d),
                    Decimal(0),
                )
                dist = _dec(p["net_equity_receipt_keur"]) * frac
                paid_total += contrib
                dist_total += dist
                flows.append((d, dist - contrib))
            dpi = (dist_total / paid_total) if paid_total > 0 else None
            xirr = _oracle_xirr(flows)
            per_inv[inv.investor_id] = {
                "paid": paid_total,
                "dist": dist_total,
                "dpi": dpi,
                "xirr": xirr,
            }
        return per_inv


def _dated_solar(*, tariff: float | None = None, gearing: float | None = None, equity_only: bool = False):
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
    rev = base.revenue
    if tariff is not None:
        rev = replace(
            rev,
            ppa_base_tariff=tariff,
            market_prices_curve=tuple(tariff for _ in (rev.market_prices_curve or (tariff,))),
        )
    fin = replace(
        base.financing,
        shl_maturity_period_index=eng.periods()[-1].index,
        **({"gearing_ratio": gearing} if gearing is not None else {}),
        **({"sponsor_funding_mode": SponsorFundingMode.EQUITY_ONLY} if equity_only else {}),
    )
    return replace(base, info=info, revenue=rev, financing=fin)


# ---------------------------------------------------------------------------
# 1. Independent Decimal Oracle: 60:40, staggered timing, 1-founder-paid, 3-way split
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("use_dated", [False, True])
def test_investor_f4_decimal_oracle_staggered_and_shl_exclusion(use_dated):
    pi = _dated_solar() if use_dated else pf.create_generic_solar_reference()
    run = run_clean_production(pi, project_type="solar")
    receipt = extract_equity_receipts(run.g2c_result)
    funding_rows = [p for p in receipt["periods"] if p["paid_in_keur"] > 0]
    assert len(funding_rows) >= 1

    # Staggered timing: if >=2 funding dates exist, alpha funds earlier period & beta catches up; else 60:40 split
    total_eq = math.fsum(p["paid_in_keur"] for p in funding_rows)
    if len(funding_rows) >= 2:
        contribs = [
            {"investor_id": "alpha", "cash_date": funding_rows[0]["date"], "amount_keur": funding_rows[0]["paid_in_keur"]},
            {"investor_id": "beta", "cash_date": funding_rows[1]["date"], "amount_keur": funding_rows[1]["paid_in_keur"]},
        ]
        for extra in funding_rows[2:]:
            contribs.append({"investor_id": "alpha", "cash_date": extra["date"], "amount_keur": extra["paid_in_keur"] * 0.6})
            contribs.append({"investor_id": "beta", "cash_date": extra["date"], "amount_keur": extra["paid_in_keur"] * 0.4})
    else:
        contribs = [
            {"investor_id": "alpha", "cash_date": funding_rows[0]["date"], "amount_keur": funding_rows[0]["paid_in_keur"] * 0.6},
            {"investor_id": "beta", "cash_date": funding_rows[0]["date"], "amount_keur": funding_rows[0]["paid_in_keur"] * 0.4},
        ]

    doc = {
        "schema_version": 1,
        "agreement_id": "AGR-6040-STAGGERED",
        "version": 1,
        "currency": "EUR",
        "unit": "kEUR",
        "policy": "RESIDUAL_ONLY",
        "investors": [
            {"investor_id": "alpha", "investment_class": "COMMON_EQUITY", "ownership_fraction": 0.60, "commitment_keur": total_eq + 100.0},
            {"investor_id": "beta", "investment_class": "COMMON_EQUITY", "ownership_fraction": 0.40, "commitment_keur": total_eq + 100.0},
        ],
        "contributions": contribs,
    }
    terms = parse_terms(json.dumps(doc))
    binding = {
        "owner_id": "owner-f4",
        "project_id": "proj-f4",
        "scenario_id": None,
        "snapshot_id": "snap-f4",
        "composite_hash": "b" * 64,
    }
    ev = allocate_run(terms, receipt, binding=binding)
    oracle = _oracle_investor_accounts(terms, receipt)

    # Total investor distributions reconcile 100% to canonical net dividends (zero SHL bleed-in)
    canonical_net_div = math.fsum(p["net_equity_receipt_keur"] for p in receipt["periods"])
    canonical_shl_cash = math.fsum(
        p.shl_cash_interest_receipt_keur + p.actual_shl_principal_paid_keur
        for p in run.g2c_result.waterfall_periods
    )
    assert canonical_shl_cash > 0.0
    total_allocated = math.fsum(row["residual_distributions_keur"] for row in ev["investors"])
    assert abs(total_allocated - canonical_net_div) <= 1e-6

    for row in ev["investors"]:
        exp = oracle[row["investor_id"]]
        assert abs(_dec(row["total_paid_in_keur"]) - exp["paid"]) <= Decimal("1e-6")
        assert abs(_dec(row["residual_distributions_keur"]) - exp["dist"]) <= Decimal("1e-6")
        assert abs(_dec(row["dpi"]) - exp["dpi"]) <= Decimal("1e-6")
        assert abs(_dec(row["xirr"]) - exp["xirr"]) <= Decimal("1e-6")

    # Negative controls: tampered evidence digest / agreement digest / wrong binding fail closed
    tampered = dict(ev)
    tampered["retained_cash_keur"] = 1.0
    with pytest.raises(ValueError, match="digest mismatch"):
        validate_evidence(tampered, **binding)
    with pytest.raises(ValueError, match="identity mismatch"):
        validate_evidence(ev, **{**binding, "owner_id": "other-owner"})


def test_three_investor_conservation_and_unsupported_currency_class_refusals():
    solar = _dated_solar()
    run = run_clean_production(solar, project_type="solar")
    receipt = extract_equity_receipts(run.g2c_result)
    funding_rows = [p for p in receipt["periods"] if p["paid_in_keur"] > 0]
    total_eq = math.fsum(p["paid_in_keur"] for p in funding_rows)
    doc = {
        "schema_version": 1,
        "agreement_id": "AGR-3WAY",
        "version": 1,
        "currency": "EUR",
        "unit": "kEUR",
        "policy": "RESIDUAL_ONLY",
        "investors": [
            {"investor_id": "inv_a", "investment_class": "COMMON_EQUITY", "ownership_fraction": 0.3333, "commitment_keur": total_eq + 10.0},
            {"investor_id": "inv_b", "investment_class": "COMMON_EQUITY", "ownership_fraction": 0.3333, "commitment_keur": total_eq + 10.0},
            {"investor_id": "inv_c", "investment_class": "COMMON_EQUITY", "ownership_fraction": 0.3334, "commitment_keur": total_eq + 10.0},
        ],
        "contributions": [
            {"investor_id": "inv_a", "cash_date": row["date"], "amount_keur": row["paid_in_keur"]}
            for row in funding_rows
        ],
    }
    terms = parse_terms(json.dumps(doc))
    ev = allocate_run(
        terms,
        receipt,
        binding={"owner_id": "o1", "project_id": "p1", "scenario_id": None, "snapshot_id": "s1", "composite_hash": "h1"},
    )
    canonical_net_div = math.fsum(p["net_equity_receipt_keur"] for p in receipt["periods"])
    assert abs(math.fsum(i["residual_distributions_keur"] for i in ev["investors"]) - canonical_net_div) <= 1e-6
    by_id = {i["investor_id"]: i for i in ev["investors"]}
    assert by_id["inv_b"]["dpi"] is None and by_id["inv_b"]["xirr_status"] == "NO_NEGATIVE_CASHFLOW"
    assert by_id["inv_c"]["dpi"] is None and by_id["inv_c"]["xirr_status"] == "NO_NEGATIVE_CASHFLOW"

    # Typed refusals for unsupported currencies, units, policies, classes, over-commitment
    for mut in [
        {"currency": "USD"},
        {"unit": "MEUR"},
        {"policy": "ROC_FIRST"},
        {"investors": [{**doc["investors"][0], "investment_class": "SHAREHOLDER_LOAN"}, *doc["investors"][1:]]},
        {"investors": [{**doc["investors"][0], "ownership_fraction": 0.50}, *doc["investors"][1:]]},
    ]:
        bad = {**doc, **mut}
        with pytest.raises(InvestorAgreementInputError):
            parse_terms(json.dumps(bad))


# ---------------------------------------------------------------------------
# 2. Monotonic Ledger UX, Stale/NOT_RUN Advisory, React History Replay & Export
# ---------------------------------------------------------------------------

@pytest.fixture
def inv_env(tmp_path, monkeypatch):
    db_path = tmp_path / "finco41_inv.db"
    monkeypatch.setattr(persistence_db, "DB_PATH", str(db_path))
    monkeypatch.setenv("FINCO_DB_PATH", str(db_path))
    monkeypatch.setenv("FINCO_MODEL_REACT_V1", "1")
    monkeypatch.setenv("FINCO_MODEL_EXECUTION_MODE", "thread")
    persistence_db.init_db()

    executor = ModelExecutor(ModelExecutionConfig(mode="thread"))
    reset_model_executor_for_tests(executor)

    from app.services.reference_seed_service import create_reference_seeded_project
    from app.v2.investor_f4_router import router as f4_router
    from app.v2.react_investors import router as react_inv_router
    from app.v2.router import router as v2_router

    app = FastAPI()
    app.include_router(v2_router, prefix="/v2")
    app.include_router(f4_router, prefix="/v2")
    app.include_router(react_inv_router, prefix="/v2")

    uid = "finco41_inv_owner"
    rec = create_reference_seeded_project(
        user_id=uid,
        template_source="generic_solar_reference",
        requested_name="FINCO41 Investor Project",
        capacity_mw=20.0,
    )
    try:
        with TestClient(app) as client:
            client.cookies.set(COOKIE_NAME, create_session_token(user_id=uid, username="owner"))
            yield {"client": client, "user_id": uid, "record": rec}
    finally:
        assert executor.shutdown_and_join() == []
        reset_model_executor_for_tests()


def _agr(aid: str, ver: int, contribs: list[dict], *, commitment: float = 50000.0) -> dict:
    return {
        "schema_version": 1,
        "agreement_id": aid,
        "version": ver,
        "currency": "EUR",
        "unit": "kEUR",
        "policy": "RESIDUAL_ONLY",
        "investors": [
            {"investor_id": "alpha", "investment_class": "COMMON_EQUITY", "ownership_fraction": 0.6, "commitment_keur": commitment},
            {"investor_id": "beta", "investment_class": "COMMON_EQUITY", "ownership_fraction": 0.4, "commitment_keur": commitment},
        ],
        "contributions": contribs,
    }


def test_ledger_next_versions_recreate_stale_advisory_and_react_history_replay(inv_env):
    client = inv_env["client"]
    rec = inv_env["record"]
    uid = inv_env["user_id"]

    # 1. NOT_RUN with non-empty contributions -> UNVERIFIED_NO_LAST_RUN advisory (not false COMPLETE)
    r0 = client.get(f"/v2/model-react/investors/agreement?project={rec.project_code}").json()
    assert r0["state"] == "NOT_RUN"
    save_agreement(
        owner=uid,
        project_id=rec.project_id,
        expected_hash=r0["identity"]["content_hash"],
        raw=json.dumps(_agr("AGR-RETIRE", 1, [{"investor_id": "alpha", "cash_date": "2030-06-30", "amount_keur": 500.0}])),
    )
    r_not_run = client.get(f"/v2/model-react/investors/agreement?project={rec.project_code}").json()
    assert r_not_run["draft_warning"]["code"] == "UNVERIFIED_NO_LAST_RUN"
    assert r_not_run["draft_warning"]["incomplete_draft"] is False
    assert "not been verified against a canonical Run yet" in r_not_run["draft_warning"]["advisory_message"]
    html_not_run = client.get(f"/v2/workbook/investor/agreement?project={rec.project_code}").text
    assert 'data-testid="f4-stale-funding-advisory"' in html_not_run
    assert 'data-ledger-next-versions=' in html_not_run

    # 2. Remove AGR-RETIRE -> ledger_next_versions exposes {"AGR-RETIRE": 2} in both React JSON & Legacy HTML
    client.post(
        "/v2/workbook/investor/agreement",
        data={
            "project": rec.project_code,
            "csrf_token": r_not_run["save"]["csrf_token"],
            "content_hash": r_not_run["identity"]["content_hash"],
            "action": "remove",
            "agreement": "",
        },
        headers={"HX-Request": "true"},
    )
    r_after_rem = client.get(f"/v2/model-react/investors/agreement?project={rec.project_code}").json()
    assert r_after_rem["terms"] is None
    assert r_after_rem["save"]["ledger_next_versions"]["AGR-RETIRE"] == 2
    html_after_rem = client.get(f"/v2/workbook/investor/agreement?project={rec.project_code}").text
    assert '"AGR-RETIRE": 2' in html_after_rem or '"AGR-RETIRE":2' in html_after_rem

    # Attempting v1 fails with 409; recreating at v2 (from ledger_next_versions) succeeds
    bad_v1 = client.post(
        "/v2/workbook/investor/agreement",
        data={
            "project": rec.project_code,
            "csrf_token": r_after_rem["save"]["csrf_token"],
            "content_hash": r_after_rem["identity"]["content_hash"],
            "action": "save",
            "agreement": json.dumps(_agr("AGR-RETIRE", 1, [])),
        },
        headers={"HX-Request": "true"},
    )
    assert bad_v1.status_code == 409

    # Run once first to obtain exact canonical funding dates
    ident = assemble_consistent_for_get(user_id=uid, project_id=rec.project_id, workbook_version=WORKBOOK.version)
    run1 = post_valid_csrf(
        client,
        "/v2/workbook/run",
        headers={"HX-Request": "true"},
        data={"project": rec.project_code, "content_hash": ident.composite_hash, "workbook_version": WORKBOOK.version},
    )
    assert run1.status_code == 200, run1.text[:300]

    r_run1 = client.get(f"/v2/model-react/investors/agreement?project={rec.project_code}").json()
    funding = r_run1["funding"]
    assert funding
    contribs = [
        {"investor_id": "alpha", "cash_date": row["date"], "amount_keur": row["paid_in_keur"] * 0.6}
        for row in funding
    ] + [
        {"investor_id": "beta", "cash_date": row["date"], "amount_keur": row["paid_in_keur"] * 0.4}
        for row in funding
    ]
    next_v = r_run1["save"]["ledger_next_versions"]["AGR-RETIRE"]
    assert next_v == 2
    ok_recreate = client.post(
        "/v2/workbook/investor/agreement",
        data={
            "project": rec.project_code,
            "csrf_token": r_run1["save"]["csrf_token"],
            "content_hash": r_run1["identity"]["content_hash"],
            "action": "save",
            "agreement": json.dumps(_agr("AGR-RETIRE", next_v, contribs)),
        },
        headers={"HX-Request": "true"},
    )
    assert ok_recreate.status_code == 200

    # Run 2 incorporates AGR-RETIRE v2
    ident2 = assemble_consistent_for_get(user_id=uid, project_id=rec.project_id, workbook_version=WORKBOOK.version)
    run2 = post_valid_csrf(
        client,
        "/v2/workbook/run",
        headers={"HX-Request": "true"},
        data={"project": rec.project_code, "content_hash": ident2.composite_hash, "workbook_version": WORKBOOK.version},
    )
    assert run2.status_code == 200
    r_run2 = client.get(f"/v2/model-react/investors/agreement?project={rec.project_code}").json()
    assert r_run2["workflow"]["state"] == "INCORPORATED"
    assert r_run2["evidence"]["agreement"]["agreement_id"] == "AGR-RETIRE"
    assert r_run2["evidence"]["agreement"]["version"] == 2
    assert r_run2["draft_warning"]["stale_funding_reference"] is False

    # 3. Mutate CAPEX/tariff -> workspace becomes STALE; draft_warning surfaces stale_funding_reference advisory
    upd = post_valid_mutation(
        client,
        "/v2/workbook/update",
        headers={"HX-Request": "true"},
        data={
            "project": rec.project_code,
            "field_id": "revenue.ppa.base_tariff",
            "value": "70.0",
            "content_hash": r_run2["identity"]["content_hash"],
            "workbook_version": WORKBOOK.version,
        },
    )
    assert upd.status_code == 200
    r_stale = client.get(f"/v2/model-react/investors/agreement?project={rec.project_code}").json()
    assert r_stale["state"] == "STALE"
    assert r_stale["draft_warning"]["stale_funding_reference"] is True
    assert "STALE" in r_stale["draft_warning"]["advisory_message"]

    # 4. Remove working agreement + Run 3 without agreement -> Run 2 historical replay & export in React stay immutable
    rem_res = client.post(
        "/v2/workbook/investor/agreement",
        data={
            "project": rec.project_code,
            "csrf_token": r_stale["save"]["csrf_token"],
            "content_hash": r_stale["identity"]["content_hash"],
            "action": "remove",
            "agreement": "",
        },
        headers={"HX-Request": "true"},
    )
    assert rem_res.status_code == 200
    ident3 = assemble_consistent_for_get(user_id=uid, project_id=rec.project_id, workbook_version=WORKBOOK.version)
    run3 = post_valid_csrf(
        client,
        "/v2/workbook/run",
        headers={"HX-Request": "true"},
        data={"project": rec.project_code, "content_hash": ident3.composite_hash, "workbook_version": WORKBOOK.version},
    )
    assert run3.status_code == 200

    hist = get_run_history(uid, rec.project_id, limit=5)
    h_with_f4 = next(h for h in hist if EVIDENCE_KEY in (h.runtime_summary or {}))
    r_curr = client.get(f"/v2/model-react/investors/agreement?project={rec.project_code}").json()
    assert r_curr["evidence"] is None
    assert len(r_curr["history"]) >= 3

    r_hist = client.get(
        f"/v2/model-react/investors/agreement?project={rec.project_code}&history_id={h_with_f4.history_id}"
    ).json()
    assert r_hist["editable"] is False
    assert r_hist["workflow"]["state"] == "HISTORICAL"
    assert r_hist["selected_history_id"] == h_with_f4.history_id
    assert r_hist["evidence"]["agreement"]["agreement_id"] == "AGR-RETIRE"
    assert r_hist["evidence"]["agreement"]["version"] == 2
    assert f"history_id={h_with_f4.history_id}" in r_hist["export_url"]
    exp = client.get(r_hist["export_url"])
    assert exp.status_code == 200
    assert exp.headers["content-type"].startswith("application/vnd.openxmlformats-officedocument")


# ---------------------------------------------------------------------------
# 3. OD-INVEST-01 5-Option Comparative Analysis (Non-Production; Defaults Unchanged)
# ---------------------------------------------------------------------------

def test_od_invest_01_five_option_comparative_matrix_preserves_defaults():
    """Reproduce exact FINCO40 negative-RE case and quantify all 5 OD-INVEST-01 policy options
    reusing merged #271 F4/P2 offline evaluator and DistributionAccountingPolicy (non-production)."""
    # Option 1: Status quo economic cash sweep on low-tariff equity-only dated Solar
    stressed_pi = _dated_solar(tariff=18.0, gearing=0.10, equity_only=True)
    assert stressed_pi.distribution_accounting_policy is None  # default unchanged!
    run_opt1 = run_clean_production(stressed_pi, project_type="solar")
    rec_opt1 = extract_equity_receipts(run_opt1.g2c_result)

    divs_1 = {p.period_index: p.net_dividend_received_keur for p in run_opt1.g2c_result.waterfall_periods}
    neg_re_rows_1 = [
        (p.period_index, divs_1.get(p.period_index, 0.0), p.retained_earnings_keur)
        for p in run_opt1.financial_statements_result.balance_sheet_periods
        if (p.retained_earnings_keur or 0.0) < 0.0 and divs_1.get(p.period_index, 0.0) > 0.0
    ]
    total_div_opt1 = math.fsum(p["net_equity_receipt_keur"] for p in rec_opt1["periods"])
    min_re_opt1 = min(p.retained_earnings_keur or 0.0 for p in run_opt1.financial_statements_result.balance_sheet_periods)
    assert len(neg_re_rows_1) == 51
    assert abs(total_div_opt1 - 26494.0) < 200.0
    assert abs(min_re_opt1 - (-29070.0)) < 200.0

    # Option 2: Statutory Retained-Earnings Blocker (hypothetical DistributionAccountingPolicy(enabled=True))
    opt2_pi = replace(
        stressed_pi,
        distribution_accounting_policy=DistributionAccountingPolicy(
            enabled=True,
            authority=DistributionAccountingAuthority.GENERIC_FINCO_POLICY,
            dividend_wht_rate=stressed_pi.tax.wht_sponsor_dividends,
            legal_reserve_cap_fraction=0.0,
            opening_uc_authority=OpeningUCAuthority.CAUSALLY_DERIVED_ZERO,
        ),
    )
    run_opt2 = run_clean_production(opt2_pi, project_type="solar")
    rec_opt2 = extract_equity_receipts(run_opt2.g2c_result)
    total_div_opt2 = math.fsum(p["net_equity_receipt_keur"] for p in rec_opt2["periods"])
    divs_2 = {p.period_index: p.net_dividend_received_keur for p in run_opt2.g2c_result.waterfall_periods}
    neg_re_rows_2 = [
        p.period_index
        for p in run_opt2.financial_statements_result.balance_sheet_periods
        if (p.retained_earnings_keur or 0.0) < 0.0 and divs_2.get(p.period_index, 0.0) > 0.0
    ]
    assert neg_re_rows_2 == []
    assert total_div_opt2 < total_div_opt1
    assert max(abs(p.balance_check_keur or 0.0) for p in run_opt2.financial_statements_result.balance_sheet_periods) < 1e-5

    # Options 3 & 4: Reuse merged #271 F4/P2 offline evaluator on positive-cashflow dated Solar
    base_solar = _dated_solar()
    run_base = run_clean_production(base_solar, project_type="solar")
    base_receipt = extract_equity_receipts(run_base.g2c_result)
    funding_rows = [p for p in base_receipt["periods"] if p["paid_in_keur"] > 0]
    total_eq = math.fsum(p["paid_in_keur"] for p in funding_rows)
    p2_receipt = {
        "schema_version": 1,
        "source": base_receipt["source"],
        "return_status": base_receipt["return_status"],
        "periods": [
            {
                "date": p["date"],
                "paid_in_keur": str(p["paid_in_keur"]),
                "gross_dividend_keur": str(p["gross_dividend_keur"]),
                "dividend_wht_keur": str(p["dividend_wht_keur"]),
                "net_equity_receipt_keur": str(p["net_equity_receipt_keur"]),
            }
            for p in base_receipt["periods"]
        ],
    }
    p2_contribs = [
        {"investor_id": "LP", "date": row["date"], "amount_keur": str(row["paid_in_keur"])}
        for row in funding_rows
    ]
    policies = {
        "schema_version": 2,
        "approval": "CANDIDATE_NOT_AUTHORIZED",
        "agreement_id": "OD_INVEST_01_COMPARISON",
        "version": 1,
        "currency": "EUR",
        "unit": "kEUR",
        "preferred_method": "SIMPLE_ON_UNRETURNED_CAPITAL",
        "day_count": "ACT_365_FIXED",
        "accrual_start": "EACH_CONTRIBUTION_DATE",
        "accrual_stop": "EACH_RETURN_OF_CAPITAL_DATE",
        "partial_return": "REDUCE_FUTURE_ACCRUAL_BASE",
        "cash_shortfall": "CARRY_UNPAID_ENTITLEMENT",
        "hurdle_basis": "CUMULATIVE_UNPAID_PREF_NOT_IRR",
        "negative_distribution": "REJECT",
    }
    p2_binding = {
        "owner_id": "o1",
        "project_id": "p1",
        "scenario_id": "base",
        "snapshot_id": "s1",
        "composite_hash": "h1",
    }
    # Option 3: Explicit ROC + 80/20 Residual
    opt3_doc = {
        **policies,
        "classes": [{"id": "ORD", "preferred_rate_pa": None}],
        "investors": [
            {"id": "LP", "class_id": "ORD", "ownership_fraction": "0.80", "commitment_keur": str(total_eq + 100.0)},
            {"id": "GP", "class_id": "ORD", "ownership_fraction": "0.20", "commitment_keur": "100"},
        ],
        "contributions": p2_contribs,
        "stages": [
            {"kind": "RETURN_OF_CAPITAL", "class_id": "ORD", "beneficiary_id": None, "lifetime_cap_keur": None, "fraction": None},
            {"kind": "RESIDUAL", "class_id": None, "beneficiary_id": None, "lifetime_cap_keur": None, "fraction": None},
        ],
    }
    ev_opt3 = evaluate_p2_candidate(parse_p2_contract(json.dumps(opt3_doc)), p2_receipt, binding=p2_binding)

    # Option 4: ROC -> 8% Preferred Return -> GP Catch-up (100%) -> 80/20 Carry
    opt4_doc = {
        **policies,
        "classes": [{"id": "LP_PREF", "preferred_rate_pa": "0.08"}, {"id": "GP_ORD", "preferred_rate_pa": None}],
        "investors": [
            {"id": "LP", "class_id": "LP_PREF", "ownership_fraction": "0.80", "commitment_keur": str(total_eq + 100.0)},
            {"id": "GP", "class_id": "GP_ORD", "ownership_fraction": "0.20", "commitment_keur": "100"},
        ],
        "contributions": p2_contribs,
        "stages": [
            {"kind": "RETURN_OF_CAPITAL", "class_id": "LP_PREF", "beneficiary_id": None, "lifetime_cap_keur": None, "fraction": None},
            {"kind": "PREFERRED_RETURN", "class_id": "LP_PREF", "beneficiary_id": None, "lifetime_cap_keur": None, "fraction": None},
            {"kind": "CATCH_UP", "class_id": None, "beneficiary_id": "GP", "lifetime_cap_keur": "500", "fraction": None},
            {"kind": "CARRY", "class_id": None, "beneficiary_id": "GP", "lifetime_cap_keur": None, "fraction": "0.20"},
            {"kind": "RESIDUAL", "class_id": None, "beneficiary_id": None, "lifetime_cap_keur": None, "fraction": None},
        ],
    }
    ev_opt4 = evaluate_p2_candidate(parse_p2_contract(json.dumps(opt4_doc)), p2_receipt, binding=p2_binding)

    # Option 5: Levered Solar SHL lender-specific cash vs Legal Equity cash separation
    shl_interest = math.fsum(p.shl_cash_interest_receipt_keur for p in run_base.g2c_result.waterfall_periods)
    shl_principal = math.fsum(p.actual_shl_principal_paid_keur for p in run_base.g2c_result.waterfall_periods)
    total_div_base = math.fsum(p["net_equity_receipt_keur"] for p in base_receipt["periods"])

    inv3 = {r["id"]: r for r in ev_opt3["investors"]}
    inv4 = {r["id"]: r for r in ev_opt4["investors"]}
    assert Decimal(inv3["LP"]["returned_capital_keur"]) > 0
    assert Decimal(inv4["LP"]["paid_preference_keur"]) > 0
    assert Decimal(inv4["GP"]["catch_up_keur"]) > 0
    assert Decimal(inv4["GP"]["carry_keur"]) > 0
    assert shl_interest > 0 and shl_principal > 0 and total_div_base > 0
    assert (
        run_base.g2c_result.return_summary.legal_equity.xirr
        != run_base.g2c_result.return_summary.total_sponsor.xirr
    )
    print(
        "OD_INVEST_01_METRICS:",
        json.dumps(
            {
                "opt1_cash_sweep_net_div_keur": round(total_div_opt1, 2),
                "opt1_neg_re_periods": len(neg_re_rows_1),
                "opt1_min_re_keur": round(min_re_opt1, 2),
                "opt2_statutory_re_net_div_keur": round(total_div_opt2, 2),
                "opt2_neg_re_periods": len(neg_re_rows_2),
                "opt2_end_unrestricted_cash_keur": round(run_opt2.financial_statements_result.balance_sheet_periods[-1].unrestricted_cash_keur or 0.0, 2),
                "opt2_end_da_balance_keur": round(run_opt2.financial_statements_result.balance_sheet_periods[-1].distribution_account_balance_keur or 0.0, 2),
                "opt3_lp_roc_keur": inv3["LP"]["returned_capital_keur"],
                "opt3_lp_residual_keur": inv3["LP"]["residual_keur"],
                "opt3_gp_residual_keur": inv3["GP"]["residual_keur"],
                "opt4_lp_pref_keur": inv4["LP"]["paid_preference_keur"],
                "opt4_gp_catchup_keur": inv4["GP"]["catch_up_keur"],
                "opt4_gp_carry_keur": inv4["GP"]["carry_keur"],
                "opt4_lp_residual_keur": inv4["LP"]["residual_keur"],
                "opt5_base_net_div_keur": round(total_div_base, 2),
                "opt5_base_shl_interest_keur": round(shl_interest, 2),
                "opt5_base_shl_principal_keur": round(shl_principal, 2),
                "opt5_legal_equity_xirr": round(run_base.g2c_result.return_summary.legal_equity.xirr or 0.0, 6),
                "opt5_total_sponsor_xirr": round(run_base.g2c_result.return_summary.total_sponsor.xirr or 0.0, 6),
            }
        ),
    )
