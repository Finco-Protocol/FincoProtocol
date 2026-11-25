"""FINCO41-A — Acquisition: source-bound lifecycle, C1F-C-1/C1F-ERR-01, Demo FK disposal & independent Decimal oracle."""
from __future__ import annotations

import copy
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, localcontext
import json
import re
import sqlite3
from types import SimpleNamespace as NS

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import demo_cleanup, project_factories as pf
from app.auth import COOKIE_NAME, create_session_token, generate_csrf_token
from app.model_v2.acquisition.csrf_binding import issue_token
from app.model_v2.acquisition.economics import (
    ACTIVATION_ENABLED,
    STATUS,
    AcquisitionPolicyError,
    AcquisitionTerms,
    buyer_cashflows,
    enterprise_equity_bridge,
    evaluate,
    validate_acquisition_dates_against_source,
)
from app.model_v2.acquisition.evidence import (
    KEY as ACQ_EVIDENCE_KEY,
    AcquisitionEvidenceError,
    bind,
    extract,
    validate,
)
from app.persistence.acquisition_repository import (
    AcquisitionCaseConflict,
    list_cases,
    make_document,
    read_case,
    save_case,
)
from app.services.production_financial_authority import run_clean_production
from finco_core.engine.date_authority import DATE_AUTHORITY_VERSION, dated_life_end_exclusive
from finco_core.engine.period_engine import PeriodEngine, PeriodFrequency


# ---------------------------------------------------------------------------
# Independent 40-digit Decimal oracle (ZERO calls to finco_core.sponsor / economics)
# ---------------------------------------------------------------------------

def _dec(x) -> Decimal:
    return Decimal(str(x))


def _oracle_xnpv(rate: Decimal, flows: list[tuple[date, Decimal]]) -> Decimal:
    with localcontext() as ctx:
        ctx.prec = 50
        d0 = flows[0][0]
        base = Decimal(1) + rate
        total = Decimal(0)
        for d, amt in flows:
            exp = Decimal((d - d0).days) / Decimal(365)
            total += amt / (base ** exp)
        return total


def _oracle_xirr(flows: list[tuple[date, Decimal]]) -> Decimal:
    with localcontext() as ctx:
        ctx.prec = 50
        lo = Decimal("-0.999")
        hi = Decimal("10.0")
        f_lo = _oracle_xnpv(lo, flows)
        for _ in range(160):
            mid = (lo + hi) / Decimal(2)
            f_mid = _oracle_xnpv(mid, flows)
            if f_mid == 0:
                return mid
            if (f_lo > 0 and f_mid > 0) or (f_lo < 0 and f_mid < 0):
                lo, f_lo = mid, f_mid
            else:
                hi = mid
        return (lo + hi) / Decimal(2)


def _oracle_bridge(
    *,
    ev: Decimal,
    senior_debt: Decimal,
    shl_balance: Decimal,
    debt_like: Decimal,
    unrestricted_cash: Decimal,
    wc_adj: Decimal,
    tx_adj: Decimal,
) -> Decimal:
    return ev - senior_debt - shl_balance - debt_like + unrestricted_cash + wc_adj + tx_adj


def _oracle_bid_ceiling(
    *,
    target_irr: Decimal,
    closing_date: date,
    tx_costs: Decimal,
    closing_adj: Decimal,
    post_flows: list[tuple[date, Decimal]],
    lo: Decimal,
    hi: Decimal,
) -> Decimal:
    with localcontext() as ctx:
        ctx.prec = 50
        for _ in range(140):
            mid = (lo + hi) / Decimal(2)
            flows = [(closing_date, -(mid + tx_costs + closing_adj)), *post_flows]
            val = _oracle_xnpv(target_irr, flows)
            if val >= 0:
                lo = mid
            else:
                hi = mid
        return (lo + hi) / Decimal(2)


def _oracle_buyer_eval(evidence: dict, terms: AcquisitionTerms) -> dict:
    with localcontext() as ctx:
        ctx.prec = 50
        init = -(
            _dec(terms.purchase_price_keur)
            + _dec(terms.transaction_costs_keur)
            + _dec(terms.closing_adjustment_keur)
        )
        by_date: dict[date, Decimal] = {terms.closing_date: init}
        invested = -init if init < 0 else Decimal(0)
        received = init if init > 0 else Decimal(0)
        for row in evidence["equity_periods"]:
            d = date.fromisoformat(row["date"])
            if d <= terms.closing_date:
                continue
            if terms.exit_date is not None and d > terms.exit_date:
                continue
            div = _dec(row["net_legal_dividend_keur"])
            call = _dec(row["legal_equity_contribution_keur"])
            by_date[d] = by_date.get(d, Decimal(0)) + div - call
            if div > 0:
                received += div
            if call > 0:
                invested += call
        if terms.exit_date is not None:
            ex = _dec(terms.exit_proceeds_keur)
            by_date[terms.exit_date] = by_date.get(terms.exit_date, Decimal(0)) + ex
            if ex > 0:
                received += ex
        flows = sorted(by_date.items())
        post_flows = [(d, amt) for d, amt in flows if d > terms.closing_date]
        npv = _oracle_xnpv(_dec(terms.buyer_discount_rate), flows)
        irr = _oracle_xirr(flows) if any(a < 0 for _, a in flows) and any(a > 0 for _, a in flows) else None
        moic = (received / invested) if invested > 0 else None
        ceiling = _oracle_bid_ceiling(
            target_irr=_dec(terms.target_buyer_irr),
            closing_date=terms.closing_date,
            tx_costs=_dec(terms.transaction_costs_keur),
            closing_adj=_dec(terms.closing_adjustment_keur),
            post_flows=post_flows,
            lo=_dec(terms.bid_lower_bound_keur),
            hi=_dec(terms.bid_upper_bound_keur),
        )
        return {
            "flows": flows,
            "npv": npv,
            "irr": irr,
            "moic": moic,
            "bid_ceiling": ceiling,
        }


def _dated_inputs(kind: str, cod: date):
    base = pf.create_generic_solar_reference() if kind == "solar" else pf.create_generic_wind_reference()
    fc = date(cod.year - 1, cod.month, cod.day)
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


def _bound_evidence(clean_run, *, snapshot_id: str = "snap-finco41a"):
    src = extract(clean_run.g2c_result)
    bound = bind(
        src,
        owner_id="owner-A",
        project_id="proj-A",
        snapshot_id=snapshot_id,
        composite_hash="a" * 64,
        scenario_id=None,
    )
    return validate(
        bound,
        owner_id="owner-A",
        project_id="proj-A",
        snapshot_id=snapshot_id,
        composite_hash="a" * 64,
        scenario_id=None,
    )


# ---------------------------------------------------------------------------
# 1. Independent Decimal Oracle Tests (Legacy + Dated + Stubs + Exit + Bridge)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "label,factory_fn,closing_date,exit_date,exit_proceeds",
    [
        ("legacy_solar_simple", lambda: (pf.create_generic_solar_reference(), "solar"), date(2031, 1, 15), None, None),
        ("legacy_wind_exit", lambda: (pf.create_generic_wind_reference(), "wind"), date(2031, 1, 15), date(2045, 6, 30), 2500.0),
        ("dated_solar_leap_stub", lambda: (_dated_inputs("solar", date(2031, 3, 1)), "solar"), date(2031, 9, 15), None, None),
        ("dated_wind_non_aligned_stub", lambda: (_dated_inputs("wind", date(2031, 9, 1)), "wind"), date(2032, 3, 15), date(2058, 8, 31), 1200.0),
    ],
)
def test_acquisition_decimal_oracle_parity_legacy_and_dated(label, factory_fn, closing_date, exit_date, exit_proceeds):
    pi, ptype = factory_fn()
    run = run_clean_production(pi, project_type=ptype)
    ev = _bound_evidence(run, snapshot_id=f"snap-{label}")
    terms = AcquisitionTerms(
        closing_date=closing_date,
        purchase_price_keur=8000.0,
        transaction_costs_keur=150.0,
        closing_adjustment_keur=-50.0,
        buyer_discount_rate=0.09,
        target_buyer_irr=0.10,
        bid_lower_bound_keur=500.0,
        bid_upper_bound_keur=50000.0,
        exit_date=exit_date,
        exit_proceeds_keur=exit_proceeds,
    )
    observed = evaluate(ev, terms)
    expected = _oracle_buyer_eval(ev, terms)

    assert observed["status"] == STATUS
    assert ACTIVATION_ENABLED is False
    assert len(observed["buyer_cashflows"]) == len(expected["flows"])
    for obs_row, (exp_d, exp_amt) in zip(observed["buyer_cashflows"], expected["flows"]):
        assert obs_row["date"] == exp_d.isoformat()
        assert abs(Decimal(str(obs_row["amount_keur"])) - exp_amt) <= Decimal("1e-7")
        assert all("SHL" not in c["component"] for c in obs_row["components"])

    assert abs(Decimal(str(observed["buyer_npv_keur"])) - expected["npv"]) <= Decimal("1e-6")
    assert observed["buyer_irr"] is not None and expected["irr"] is not None
    assert abs(Decimal(str(observed["buyer_irr"])) - expected["irr"]) <= Decimal("1e-7")
    assert abs(Decimal(str(observed["buyer_moic"])) - expected["moic"]) <= Decimal("1e-7")
    assert observed["bid_ceiling_status"] == "ROOT_FOUND"
    assert abs(Decimal(str(observed["bid_ceiling_keur"])) - expected["bid_ceiling"]) <= Decimal("1e-5")


def test_ev_to_equity_bridge_decimal_oracle_and_negative_controls():
    out = enterprise_equity_bridge(
        enterprise_value_keur=42500.0,
        senior_debt_keur=26000.0,
        unrestricted_cash_keur=850.0,
        restricted_cash_keur=1933.53,
        shl_balance_keur=8200.0,
        debt_like_keur=300.0,
        working_capital_adjustment_keur=-120.5,
        transaction_adjustment_keur=70.5,
    )
    expected = _oracle_bridge(
        ev=_dec(42500.0),
        senior_debt=_dec(26000.0),
        shl_balance=_dec(8200.0),
        debt_like=_dec(300.0),
        unrestricted_cash=_dec(850.0),
        wc_adj=_dec(-120.5),
        tx_adj=_dec(70.5),
    )
    assert Decimal(str(out["equity_value_keur"])) == expected
    assert out["restricted_cash_excluded_keur"] == 1933.53

    # Negative controls: tampering source evidence, binding, or injecting SHL fails closed
    run = run_clean_production(pf.create_generic_solar_reference(), project_type="solar")
    ev = _bound_evidence(run)
    tampered = copy.deepcopy(ev)
    tampered["equity_periods"][2]["net_legal_dividend_keur"] += 10.0
    with pytest.raises(AcquisitionEvidenceError, match="EVIDENCE_DIGEST_MISMATCH"):
        validate(tampered, owner_id="owner-A", project_id="proj-A", snapshot_id="snap-finco41a", composite_hash="a" * 64, scenario_id=None)

    with pytest.raises(AcquisitionEvidenceError, match="EVIDENCE_RUN_BINDING_MISMATCH"):
        validate(ev, owner_id="owner-B", project_id="proj-A", snapshot_id="snap-finco41a", composite_hash="a" * 64, scenario_id=None)


def test_unsupported_structures_and_exit_edges_fail_closed():
    run = run_clean_production(_dated_inputs("solar", date(2031, 3, 1)), project_type="solar")
    ev = _bound_evidence(run)
    base = dict(
        closing_date=date(2031, 9, 15),
        purchase_price_keur=5000.0,
        transaction_costs_keur=100.0,
        buyer_discount_rate=0.08,
        target_buyer_irr=0.09,
        bid_lower_bound_keur=100.0,
        bid_upper_bound_keur=20000.0,
    )
    # Last operating date on 2031-03-01 25y dated Solar is 2056-02-29 (leap day)
    latest = date.fromisoformat(ev["equity_periods"][-1]["date"])
    assert latest == date(2056, 2, 29)

    for bad_kw, match in [
        ({"ownership_fraction": 0.6}, "OWNERSHIP_NOT_100_PERCENT"),
        ({"shl_policy": "ACQUIRE_SHL"}, "SHL_RIGHTS_POLICY_UNSUPPORTED"),
        ({"transaction_type": "LEVERAGED_REFI"}, "TRANSACTION_STRUCTURE_UNSUPPORTED"),
        ({"exit_date": date(2040, 1, 1), "exit_proceeds_keur": None}, "EXIT_FIELDS_INCOMPLETE"),
        ({"exit_date": None, "exit_proceeds_keur": 100.0}, "EXIT_FIELDS_INCOMPLETE"),
        ({"exit_date": date(2040, 1, 1), "exit_proceeds_keur": -5.0}, "exit_proceeds_keur_NEGATIVE"),
        ({"exit_date": date(2031, 9, 15), "exit_proceeds_keur": 100.0}, "EXIT_DATE_INVALID"),
        ({"exit_date": date(2056, 3, 1), "exit_proceeds_keur": 100.0}, "EXIT_BEYOND_SOURCE_HORIZON"),
        ({"closing_date": date(2056, 2, 29)}, "CLOSING_NOT_WITHIN_SOURCE_HORIZON"),
        ({"closing_date": date(2031, 12, 31)}, "CLOSING_DATE_ENTITLEMENT_ORDER_AMBIGUOUS"),
    ]:
        with pytest.raises(AcquisitionPolicyError, match=match):
            validate_acquisition_dates_against_source(ev, AcquisitionTerms(**{**base, **bad_kw}))


# ---------------------------------------------------------------------------
# 2. Real HTTP Source-Bound Lifecycle, C1F-ERR-01, Immutability & Demo FK Cleanup
# ---------------------------------------------------------------------------

@pytest.fixture
def acq_lifecycle_env(tmp_path, monkeypatch):
    db_path = tmp_path / "finco41_acq.db"
    from app.persistence import db as persistence_db
    monkeypatch.setattr(persistence_db, "DB_PATH", str(db_path))
    monkeypatch.setenv("FINCO_DB_PATH", str(db_path))
    monkeypatch.setenv("FINCO_MODEL_EXECUTION_MODE", "thread")
    monkeypatch.setenv("APP_MODE", "development")
    monkeypatch.setenv("FINCO_M6_CANDIDATE_REVIEW", "1")
    persistence_db.init_db()

    from app.services.reference_seed_service import create_reference_seeded_project
    from app.runtime.model_execution import ModelExecutor, ModelExecutionConfig, reset_model_executor_for_tests
    from app.v2 import acquisition_router
    from app.v2.router import router as v2_router
    import app.auth as auth_mod

    executor = ModelExecutor(ModelExecutionConfig(mode="thread"))
    reset_model_executor_for_tests(executor)

    # Allow test admin review via explicit test-only admin session resolver
    monkeypatch.setattr(
        auth_mod,
        "resolve_admin_session",
        lambda req: NS(user_id="owner_acq", username="admin") if req.cookies.get("finco_admin_test") == "1" else None,
    )

    app = FastAPI()
    app.include_router(v2_router, prefix="/v2")
    app.include_router(acquisition_router.router, prefix="/v2")

    rec = create_reference_seeded_project(
        user_id="owner_acq",
        template_source="generic_solar_reference",
        requested_name="FINCO41 Acquisition Project",
        capacity_mw=20.0,
    )
    other = create_reference_seeded_project(
        user_id="foreign_acq",
        template_source="generic_solar_reference",
        requested_name="Foreign Project",
        capacity_mw=20.0,
    )
    sess = create_session_token(user_id="owner_acq", username="owner_acq")
    try:
        with TestClient(app) as client:
            client.cookies.set(COOKIE_NAME, sess)
            yield {"client": client, "record": rec, "other": other, "db_path": str(db_path), "session": sess}
    finally:
        assert executor.shutdown_and_join() == []
        reset_model_executor_for_tests()


def _extract_csrf_and_history(html_text: str) -> tuple[str, str, str]:
    csrf = re.search(r'name="csrf_token"\s+value="([^"]+)"', html_text).group(1)
    hid = re.search(r'name="history_id"\s+value="([^"]+)"', html_text).group(1)
    rev = re.search(r'name="expected_revision"\s+value="([^"]+)"', html_text).group(1)
    return csrf, hid, rev


def test_real_http_lifecycle_c1f_err01_immutability_and_review_gate(acq_lifecycle_env, monkeypatch):
    client = acq_lifecycle_env["client"]
    rec = acq_lifecycle_env["record"]
    other = acq_lifecycle_env["other"]
    db_path = acq_lifecycle_env["db_path"]

    # 1. Execute Run 1 via POST /v2/workbook/run
    from tests.run_clone_csrf import post_valid_csrf
    from app.workbook.workbook_identity import assemble_consistent_for_get
    from app.workbook.registry import WORKBOOK
    ident1 = assemble_consistent_for_get(user_id="owner_acq", project_id=rec.project_id, workbook_version=WORKBOOK.version)
    r_run1 = post_valid_csrf(
        client,
        "/v2/workbook/run",
        headers={"HX-Request": "true"},
        data={"project": rec.project_code, "content_hash": ident1.composite_hash, "workbook_version": WORKBOOK.version},
    )
    assert r_run1.status_code == 200, r_run1.text[:300]

    # 2. GET /v2/valuation-acquisition displays AVAILABLE_SOURCE_FACTS + calendar authority
    page1 = client.get(f"/v2/valuation-acquisition?project={rec.project_code}")
    assert page1.status_code == 200
    assert "AVAILABLE_SOURCE_FACTS" in page1.text
    assert 'data-testid="m6-calendar-authority"' in page1.text
    assert "LEGACY_CALENDAR/v0" in page1.text
    assert "CANDIDATE_NOT_AUTHORIZED" in page1.text
    csrf1, hid1, rev1 = _extract_csrf_and_history(page1.text)
    assert rev1 == "0"

    # 3. C1F-ERR-01: partial bridge -> 422; negative expected_revision -> 422; C1F-C-1 out-of-horizon -> 422
    base_form = {
        "project": rec.project_code,
        "csrf_token": csrf1,
        "history_id": hid1,
        "case_id": "",
        "expected_revision": "0",
        "closing_date": "2031-07-15",
        "purchase_price_keur": "12000",
        "transaction_costs_keur": "200",
        "closing_adjustment_keur": "0",
        "buyer_discount_rate": "0.09",
        "target_buyer_irr": "0.10",
        "bid_lower_bound_keur": "1000",
        "bid_upper_bound_keur": "40000",
    }
    bad_partial = client.post(
        "/v2/valuation-acquisition/save",
        data={**base_form, "enterprise_value_keur": "40000"},
    )
    assert bad_partial.status_code == 422
    assert bad_partial.json()["error"] == "CASE_BRIDGE_PARTIAL_UNAVAILABLE"

    bad_neg_rev = client.post(
        "/v2/valuation-acquisition/save",
        data={**base_form, "expected_revision": "-1"},
    )
    assert bad_neg_rev.status_code == 422
    assert bad_neg_rev.json()["error"] == "EXPECTED_REVISION_INVALID"

    bad_c1f_c1 = client.post(
        "/v2/valuation-acquisition/save",
        data={**base_form, "closing_date": "2065-01-01"},
    )
    assert bad_c1f_c1.status_code == 422
    assert bad_c1f_c1.json()["error"] == "CLOSING_NOT_WITHIN_SOURCE_HORIZON"
    assert list_cases(owner_id="owner_acq", project_id=rec.project_id) == []

    # 4. Valid Save with full closing bridge -> 303 redirect, rev 1 persisted
    full_bridge = {
        "enterprise_value_keur": "41000",
        "senior_debt_keur": "26000",
        "unrestricted_cash_keur": "500",
        "restricted_cash_keur": "1900",
        "shl_balance_keur": "3500",
        "debt_like_keur": "0",
        "working_capital_adjustment_keur": "0",
        "transaction_adjustment_keur": "0",
    }
    ok_save = client.post(
        "/v2/valuation-acquisition/save",
        data={**base_form, **full_bridge},
        follow_redirects=False,
    )
    assert ok_save.status_code == 303
    cases = list_cases(owner_id="owner_acq", project_id=rec.project_id)
    assert len(cases) == 1
    case_id = cases[0]["case_id"]
    assert cases[0]["revision"] == 1

    # 5. Review gate is closed without admin cookie -> 403 REVIEW_BOUNDARY_CLOSED
    denied_review = client.post(
        "/v2/valuation-acquisition/review-candidate",
        data={"project": rec.project_code, "csrf_token": csrf1, "case_id": case_id},
    )
    assert denied_review.status_code == 403
    assert denied_review.json()["error"] == "REVIEW_BOUNDARY_CLOSED"

    # 6. Admin DEV review returns Decimal-verified metrics + bridge delta + source_calendar
    client.cookies.set("finco_admin_test", "1")
    ok_review = client.post(
        "/v2/valuation-acquisition/review-candidate",
        data={"project": rec.project_code, "csrf_token": csrf1, "case_id": case_id},
    )
    assert ok_review.status_code == 200, ok_review.text
    rj = ok_review.json()
    assert rj["source_history_id"] == hid1
    assert rj["source_calendar"]["date_authority_version"] == "LEGACY_CALENDAR/v0"
    assert rj["candidate"]["enterprise_equity_bridge"]["equity_value_keur"] == 12000.0
    assert rj["candidate"]["bridge_vs_purchase_price_delta_keur"] == 0.0

    # Review C1F-ERR-01: missing case -> 409; unexpected error -> 500 INTERNAL_ERROR
    miss_review = client.post(
        "/v2/valuation-acquisition/review-candidate",
        data={"project": rec.project_code, "csrf_token": csrf1, "case_id": "00000000-0000-4000-8000-000000000000"},
    )
    assert miss_review.status_code == 409
    assert miss_review.json()["error"] == "CASE_NOT_FOUND"

    # 7. Mutate project (Run 2) -> case remains pinned to Run 1, shows SOURCE_OUTDATED, rebind denied 409
    from tests.model_mutation_csrf import post_valid_mutation
    ident_b = assemble_consistent_for_get(user_id="owner_acq", project_id=rec.project_id, workbook_version=WORKBOOK.version)
    upd = post_valid_mutation(
        client,
        "/v2/workbook/update",
        headers={"HX-Request": "true"},
        data={
            "project": rec.project_code,
            "field_id": "revenue.ppa.base_tariff",
            "value": "55.0",
            "content_hash": ident_b.composite_hash,
            "workbook_version": WORKBOOK.version,
        },
    )
    assert upd.status_code == 200, upd.text[:300]
    ident2 = assemble_consistent_for_get(user_id="owner_acq", project_id=rec.project_id, workbook_version=WORKBOOK.version)
    r_run2 = post_valid_csrf(
        client,
        "/v2/workbook/run",
        headers={"HX-Request": "true"},
        data={"project": rec.project_code, "content_hash": ident2.composite_hash, "workbook_version": WORKBOOK.version},
    )
    assert r_run2.status_code == 200, r_run2.text[:300]

    from app.persistence.run_history_repository import get_run_history
    hist = get_run_history("owner_acq", rec.project_id, limit=5)
    assert len(hist) >= 2
    hid2 = hist[0].history_id
    assert hid2 != hid1

    case_page = client.get(f"/v2/valuation-acquisition?project={rec.project_code}&case_id={case_id}")
    assert case_page.status_code == 200
    assert "SOURCE_OUTDATED" in case_page.text

    # Rebind attempt to Run 2 fails with 409 CASE_SOURCE_REBIND_FORBIDDEN
    rebind_try = client.post(
        "/v2/valuation-acquisition/save",
        data={**base_form, "history_id": hid2, "case_id": case_id, "expected_revision": "1"},
    )
    assert rebind_try.status_code == 409
    assert rebind_try.json()["error"] == "CASE_SOURCE_REBIND_FORBIDDEN"

    # Stale CAS update -> 409 CASE_CAS_CONFLICT
    stale_cas = client.post(
        "/v2/valuation-acquisition/save",
        data={**base_form, "case_id": case_id, "expected_revision": "0"},
    )
    assert stale_cas.status_code == 409
    assert stale_cas.json()["error"] == "CASE_CAS_CONFLICT"

    # Foreign tenant: wrong-project CSRF -> 403; project-bound CSRF for foreign project -> 404; GET -> 404
    wrong_proj_csrf = client.post(
        "/v2/valuation-acquisition/save",
        data={**base_form, "project": other.project_code},
    )
    assert wrong_proj_csrf.status_code == 403
    foreign_tok = issue_token(NS(cookies={COOKIE_NAME: acq_lifecycle_env["session"]}, state=NS()), other.project_code)
    foreign_try = client.post(
        "/v2/valuation-acquisition/save",
        data={**base_form, "project": other.project_code, "csrf_token": foreign_tok},
    )
    assert foreign_try.status_code == 404
    assert client.get(f"/v2/valuation-acquisition?project={other.project_code}").status_code == 404

    # Review against original Run 1 still matches Run 1 source immutably
    ok_review_after = client.post(
        "/v2/valuation-acquisition/review-candidate",
        data={"project": rec.project_code, "csrf_token": csrf1, "case_id": case_id},
    )
    assert ok_review_after.status_code == 200
    assert ok_review_after.json()["candidate"]["buyer_npv_keur"] == rj["candidate"]["buyer_npv_keur"]


def test_demo_cleanup_disposes_demo_acquisition_cases_without_fk_failure(tmp_path, monkeypatch):
    db_path = tmp_path / "demo_acq.db"
    from app.persistence import db as persistence_db
    monkeypatch.setattr(persistence_db, "DB_PATH", str(db_path))
    monkeypatch.setenv("FINCO_DB_PATH", str(db_path))
    monkeypatch.setenv("FINCO_MODEL_EXECUTION_MODE", "thread")
    persistence_db.init_db()

    from app.services.reference_seed_service import create_reference_seeded_project
    from app.persistence.run_history_repository import get_run_history

    demo_uid = "demo_acq_cleanup_1"
    rec = create_reference_seeded_project(
        user_id=demo_uid,
        template_source="generic_solar_reference",
        requested_name="Demo Acq",
        capacity_mw=20.0,
    )
    # Run once so model_run_history exists
    from app.runtime.model_execution import ModelExecutor, ModelExecutionConfig, reset_model_executor_for_tests
    from app.v2.router import router as v2_router
    from tests.run_clone_csrf import post_valid_csrf
    from app.workbook.workbook_identity import assemble_consistent_for_get
    from app.workbook.registry import WORKBOOK
    executor = ModelExecutor(ModelExecutionConfig(mode="thread"))
    reset_model_executor_for_tests(executor)
    app = FastAPI()
    app.include_router(v2_router, prefix="/v2")
    try:
        with TestClient(app) as client:
            client.cookies.set(COOKIE_NAME, create_session_token(user_id=demo_uid, username="demo"))
            ident = assemble_consistent_for_get(user_id=demo_uid, project_id=rec.project_id, workbook_version=WORKBOOK.version)
            r = post_valid_csrf(
                client,
                "/v2/workbook/run",
                headers={"HX-Request": "true"},
                data={"project": rec.project_code, "content_hash": ident.composite_hash, "workbook_version": WORKBOOK.version},
            )
            assert r.status_code == 200, r.text[:300]
    finally:
        assert executor.shutdown_and_join() == []
        reset_model_executor_for_tests()

    entry = get_run_history(demo_uid, rec.project_id, limit=1)[0]
    terms = AcquisitionTerms(
        closing_date=date(2031, 7, 15),
        purchase_price_keur=5000.0,
        transaction_costs_keur=100.0,
        buyer_discount_rate=0.09,
        target_buyer_irr=0.10,
        bid_lower_bound_keur=500.0,
        bid_upper_bound_keur=20000.0,
    )
    doc = make_document(entry, terms)
    case_id, rev = save_case(owner_id=demo_uid, project_id=rec.project_id, document=doc)
    assert rev == 1 and case_id

    # Terminal disposal with foreign_keys=ON MUST succeed and clear acquisition tables cleanly
    summary = demo_cleanup.cleanup_all_demo_data()
    assert summary["model_m6_acquisition_revisions"] == 1
    assert summary["model_m6_acquisition_cases"] == 1
    assert summary["projects"] == 1
    with persistence_db.get_connection() as conn:
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        assert conn.execute("SELECT COUNT(*) FROM model_m6_acquisition_cases").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM model_m6_acquisition_revisions").fetchone()[0] == 0
